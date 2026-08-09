"""API Gateway / Function URL → InvokeHarness proxy (stateless, buffered)."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

HARNESS_ARN = os.environ.get("HARNESS_ARN", "")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION") or os.environ.get(
    "AWS_REGION", "us-west-2"
)
S3_BUCKET = os.environ.get("S3_BUCKET", "").strip()
SKILLS_S3_PREFIX = (os.environ.get("SKILLS_S3_PREFIX") or "skills").strip().strip("/")
DEFAULT_SKILLS = [
    name.strip()
    for name in (os.environ.get("DEFAULT_SKILLS") or "businfo").split(",")
    if name.strip()
]

_runtime_client = None


def _client():
    global _runtime_client
    if _runtime_client is None:
        _runtime_client = boto3.client(
            "bedrock-agentcore",
            region_name=BEDROCK_REGION,
            config=Config(
                read_timeout=300,
                connect_timeout=60,
                retries={"max_attempts": 0},
            ),
        )
    return _runtime_client


def _response(
    status_code: int,
    body: Dict[str, Any],
    *,
    cors: bool = True,
) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if cors:
        headers.update(
            {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            }
        )
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(body, ensure_ascii=False),
    }


def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if body is None:
        # Function URL / direct invoke may pass the payload at the top level
        if "prompt" in event:
            return {
                k: event[k]
                for k in (
                    "prompt",
                    "sessionId",
                    "session_id",
                    "actorId",
                    "actor_id",
                    "skills",
                )
                if k in event
            }
        return {}
    if event.get("isBase64Encoded"):
        import base64

        body = base64.b64decode(body).decode("utf-8")
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    if isinstance(body, str):
        body = body.strip()
        if not body:
            return {}
        return json.loads(body)
    if isinstance(body, dict):
        return body
    return {}


def _route_key(event: Dict[str, Any]) -> Tuple[str, str]:
    """Return (method, path) for API Gateway HTTP API or Function URL."""
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    method = (
        http.get("method")
        or event.get("httpMethod")
        or request_context.get("httpMethod")
        or "POST"
    ).upper()
    path = (
        http.get("path")
        or event.get("rawPath")
        or event.get("path")
        or "/"
    )
    return method, path


def _skill_names_from_payload(payload: Dict[str, Any]) -> List[str]:
    raw = payload.get("skills")
    if raw is None:
        return list(DEFAULT_SKILLS)
    if isinstance(raw, str):
        names = [n.strip() for n in raw.split(",") if n.strip()]
        return names or list(DEFAULT_SKILLS)
    if isinstance(raw, list):
        names: List[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                names.append(item.strip())
            elif isinstance(item, dict):
                # Already an InvokeHarness skill object — skip name mapping later
                return []
        return names or list(DEFAULT_SKILLS)
    return list(DEFAULT_SKILLS)


def build_harness_skills(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build InvokeHarness ``skills`` list (S3 URIs for businfo by default)."""
    raw = payload.get("skills")
    if isinstance(raw, list) and raw and all(isinstance(x, dict) for x in raw):
        return raw  # type: ignore[return-value]

    names = _skill_names_from_payload(payload)
    if not names:
        return []
    if not S3_BUCKET:
        logger.warning("S3_BUCKET unset; cannot attach S3 skills %s", names)
        return [{"path": f"skills/{name}"} for name in names]

    return [
        {"s3": {"uri": f"s3://{S3_BUCKET}/{SKILLS_S3_PREFIX}/{name}/"}}
        for name in names
    ]


def _collect_harness_text(
    harness_arn: str,
    prompt: str,
    session_id: str,
    actor_id: Optional[str] = None,
    skills: Optional[List[Dict[str, Any]]] = None,
) -> str:
    kwargs: Dict[str, Any] = {
        "harnessArn": harness_arn,
        "runtimeSessionId": session_id,
        "messages": [
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
    }
    if actor_id:
        kwargs["actorId"] = actor_id
    if skills:
        kwargs["skills"] = skills

    response = _client().invoke_harness(**kwargs)
    stream = response.get("stream")
    if stream is None:
        raise RuntimeError(f"Empty Harness response: {response}")

    chunks: list[str] = []
    for event in stream:
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta") or {}
            text = delta.get("text")
            if text:
                chunks.append(text)
        elif "runtimeClientError" in event:
            msg = (event["runtimeClientError"] or {}).get("message") or "unknown error"
            raise RuntimeError(f"Harness runtime error: {msg}")
    return "".join(chunks)


def handler(event, context):
    logger.info("event keys=%s", list(event.keys()) if isinstance(event, dict) else type(event))

    method, path = _route_key(event)

    if method == "OPTIONS":
        return _response(200, {"ok": True})

    if method == "GET" and path.rstrip("/").endswith("health"):
        return _response(
            200,
            {
                "status": "ok",
                "harnessConfigured": bool(HARNESS_ARN),
                "skillsConfigured": bool(S3_BUCKET and DEFAULT_SKILLS),
                "defaultSkills": DEFAULT_SKILLS,
                "region": BEDROCK_REGION,
            },
        )

    if method != "POST":
        return _response(405, {"error": f"Method not allowed: {method}"})

    if not HARNESS_ARN:
        return _response(500, {"error": "HARNESS_ARN is not configured"})

    try:
        payload = _parse_body(event)
    except json.JSONDecodeError as e:
        return _response(400, {"error": f"Invalid JSON body: {e}"})

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return _response(400, {"error": "Missing required field: prompt"})

    session_id = (
        payload.get("sessionId")
        or payload.get("session_id")
        or str(uuid.uuid4())
    )
    # runtimeSessionId: recommend >= 33 chars
    if len(session_id) < 33:
        session_id = f"{session_id}-{uuid.uuid4()}"

    actor_id = payload.get("actorId") or payload.get("actor_id")
    skills = build_harness_skills(payload)
    logger.info("invoke skills=%s", skills)

    try:
        result = _collect_harness_text(
            HARNESS_ARN,
            prompt,
            session_id,
            actor_id=actor_id,
            skills=skills,
        )
    except Exception as e:
        logger.exception("InvokeHarness failed")
        return _response(502, {"error": str(e), "sessionId": session_id})

    return _response(
        200,
        {
            "result": result,
            "sessionId": session_id,
            "skills": skills,
        },
    )
