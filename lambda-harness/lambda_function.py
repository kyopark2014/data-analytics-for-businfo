"""API Gateway → async jobs (DynamoDB) → InvokeHarness worker.

Public (sync, short):
  GET  /health
  POST /jobs          → 202 { jobId, status, sessionId }
  GET  /jobs/{jobId}  → job status / result
  POST /invoke        → sync InvokeHarness (API GW ~29s; short prompts only)

Internal (async Event invoke):
  { "jobWorker": true, "jobId": "...", "prompt": "...", ... }
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from decimal import Decimal
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
JOBS_TABLE = (os.environ.get("JOBS_TABLE") or "").strip()
JOB_TTL_SECONDS = int(os.environ.get("JOB_TTL_SECONDS") or str(24 * 3600))
# DynamoDB item soft limit (~400KB); leave headroom for other attributes.
MAX_RESULT_CHARS = int(os.environ.get("MAX_RESULT_CHARS") or "350000")
DEFAULT_SKILLS = [
    name.strip()
    for name in (os.environ.get("DEFAULT_SKILLS") or "businfo").split(",")
    if name.strip()
]

_runtime_client = None
_lambda_client = None
_ddb = None


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


def _lambda():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", region_name=BEDROCK_REGION)
    return _lambda_client


def _table():
    global _ddb
    if _ddb is None:
        if not JOBS_TABLE:
            raise RuntimeError("JOBS_TABLE is not configured")
        _ddb = boto3.resource("dynamodb", region_name=BEDROCK_REGION).Table(JOBS_TABLE)
    return _ddb


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
        "body": json.dumps(body, ensure_ascii=False, default=_json_default),
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if body is None:
        if "prompt" in event or event.get("jobWorker"):
            return {
                k: event[k]
                for k in (
                    "prompt",
                    "sessionId",
                    "session_id",
                    "actorId",
                    "actor_id",
                    "skills",
                    "jobWorker",
                    "jobId",
                    "job_id",
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


def _path_parts(path: str) -> List[str]:
    return [p for p in path.strip("/").split("/") if p]


def _job_id_from_event(event: Dict[str, Any], path: str) -> Optional[str]:
    params = event.get("pathParameters") or {}
    for key in ("jobId", "job_id", "id"):
        value = params.get(key)
        if value:
            return str(value)
    parts = _path_parts(path)
    if len(parts) >= 2 and parts[-2] == "jobs":
        return parts[-1]
    return None


def _normalize_session_id(session_id: Optional[str]) -> str:
    sid = (session_id or "").strip() or str(uuid.uuid4())
    if len(sid) < 33:
        sid = f"{sid}-{uuid.uuid4()}"
    return sid


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


def _truncate_result(text: str) -> Tuple[str, bool]:
    if len(text) <= MAX_RESULT_CHARS:
        return text, False
    return text[:MAX_RESULT_CHARS] + "\n\n…(결과가 길어 일부만 저장했습니다)", True


def _put_job(item: Dict[str, Any]) -> None:
    _table().put_item(Item=item)


def _update_job(job_id: str, **attrs: Any) -> None:
    names: Dict[str, str] = {}
    values: Dict[str, Any] = {}
    parts: List[str] = []
    for i, (key, value) in enumerate(attrs.items()):
        nk = f"#k{i}"
        nv = f":v{i}"
        names[nk] = key
        values[nv] = value
        parts.append(f"{nk} = {nv}")
    names["#updatedAt"] = "updatedAt"
    values[":updatedAt"] = int(time.time())
    parts.append("#updatedAt = :updatedAt")
    _table().update_item(
        Key={"jobId": job_id},
        UpdateExpression="SET " + ", ".join(parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    resp = _table().get_item(Key={"jobId": job_id})
    return resp.get("Item")


def _public_job(item: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "jobId": item.get("jobId"),
        "status": item.get("status"),
        "sessionId": item.get("sessionId"),
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
    }
    if item.get("status") == "SUCCEEDED":
        out["result"] = item.get("result") or ""
        if item.get("resultTruncated"):
            out["resultTruncated"] = True
        if item.get("skills"):
            try:
                out["skills"] = json.loads(item["skills"])
            except (TypeError, json.JSONDecodeError):
                out["skills"] = item.get("skills")
    if item.get("status") == "FAILED":
        out["error"] = item.get("error") or "Job failed"
    return out


def _enqueue_worker(payload: Dict[str, Any], context: Any) -> None:
    function_name = (
        os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or getattr(context, "function_name", None)
        or ""
    )
    if not function_name:
        raise RuntimeError("Cannot resolve Lambda function name for async worker")
    _lambda().invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def _handle_create_job(payload: Dict[str, Any], context: Any) -> Dict[str, Any]:
    if not JOBS_TABLE:
        return _response(500, {"error": "JOBS_TABLE is not configured"})
    if not HARNESS_ARN:
        return _response(500, {"error": "HARNESS_ARN is not configured"})

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return _response(400, {"error": "Missing required field: prompt"})

    session_id = _normalize_session_id(
        payload.get("sessionId") or payload.get("session_id")
    )
    actor_id = payload.get("actorId") or payload.get("actor_id")
    skills = build_harness_skills(payload)
    job_id = str(uuid.uuid4())
    now = int(time.time())

    item = {
        "jobId": job_id,
        "status": "QUEUED",
        "prompt": prompt,
        "sessionId": session_id,
        "createdAt": now,
        "updatedAt": now,
        "ttl": now + JOB_TTL_SECONDS,
    }
    if actor_id:
        item["actorId"] = str(actor_id)
    if skills:
        item["skills"] = json.dumps(skills, ensure_ascii=False)
    _put_job(item)

    worker_payload: Dict[str, Any] = {
        "jobWorker": True,
        "jobId": job_id,
        "prompt": prompt,
        "sessionId": session_id,
        "skills": skills,
    }
    if actor_id:
        worker_payload["actorId"] = actor_id

    try:
        _enqueue_worker(worker_payload, context)
    except Exception as e:
        logger.exception("Failed to enqueue job worker")
        _update_job(job_id, status="FAILED", error=f"Failed to enqueue worker: {e}")
        return _response(
            502,
            {"error": str(e), "jobId": job_id, "status": "FAILED", "sessionId": session_id},
        )

    return _response(
        202,
        {
            "jobId": job_id,
            "status": "QUEUED",
            "sessionId": session_id,
            "pollPath": f"/jobs/{job_id}",
        },
    )


def _handle_get_job(job_id: str) -> Dict[str, Any]:
    if not JOBS_TABLE:
        return _response(500, {"error": "JOBS_TABLE is not configured"})
    if not job_id:
        return _response(400, {"error": "Missing jobId"})
    item = _get_job(job_id)
    if not item:
        return _response(404, {"error": "Job not found", "jobId": job_id})
    return _response(200, _public_job(item))


def _run_job_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(payload.get("jobId") or payload.get("job_id") or "").strip()
    if not job_id:
        logger.error("jobWorker missing jobId")
        return {"ok": False, "error": "missing jobId"}

    prompt = (payload.get("prompt") or "").strip()
    session_id = _normalize_session_id(
        payload.get("sessionId") or payload.get("session_id")
    )
    actor_id = payload.get("actorId") or payload.get("actor_id")
    skills = build_harness_skills(payload)

    try:
        _update_job(job_id, status="RUNNING")
    except Exception:
        logger.exception("Failed to mark job RUNNING: %s", job_id)

    if not HARNESS_ARN:
        _update_job(job_id, status="FAILED", error="HARNESS_ARN is not configured")
        return {"ok": False, "jobId": job_id, "error": "HARNESS_ARN missing"}

    if not prompt:
        # Recover prompt from stored item if worker payload was truncated
        item = _get_job(job_id) or {}
        prompt = (item.get("prompt") or "").strip()
    if not prompt:
        _update_job(job_id, status="FAILED", error="Missing prompt")
        return {"ok": False, "jobId": job_id, "error": "missing prompt"}

    try:
        result = _collect_harness_text(
            HARNESS_ARN,
            prompt,
            session_id,
            actor_id=actor_id,
            skills=skills,
        )
        result, truncated = _truncate_result(result)
        attrs: Dict[str, Any] = {
            "status": "SUCCEEDED",
            "result": result,
            "sessionId": session_id,
        }
        if truncated:
            attrs["resultTruncated"] = True
        if skills:
            attrs["skills"] = json.dumps(skills, ensure_ascii=False)
        _update_job(job_id, **attrs)
        logger.info("job %s SUCCEEDED chars=%s", job_id, len(result))
        return {"ok": True, "jobId": job_id, "status": "SUCCEEDED"}
    except Exception as e:
        logger.exception("job %s FAILED", job_id)
        _update_job(job_id, status="FAILED", error=str(e), sessionId=session_id)
        return {"ok": False, "jobId": job_id, "status": "FAILED", "error": str(e)}


def _handle_sync_invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy synchronous path (API Gateway ~29s). Prefer POST /jobs."""
    if not HARNESS_ARN:
        return _response(500, {"error": "HARNESS_ARN is not configured"})

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return _response(400, {"error": "Missing required field: prompt"})

    session_id = _normalize_session_id(
        payload.get("sessionId") or payload.get("session_id")
    )
    actor_id = payload.get("actorId") or payload.get("actor_id")
    skills = build_harness_skills(payload)
    logger.info("sync invoke skills=%s", skills)

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


def handler(event, context):
    logger.info(
        "event keys=%s", list(event.keys()) if isinstance(event, dict) else type(event)
    )

    # Async worker (direct Lambda Event invoke — not API Gateway)
    if isinstance(event, dict) and event.get("jobWorker"):
        return _run_job_worker(event)

    method, path = _route_key(event)
    parts = _path_parts(path)

    if method == "OPTIONS":
        return _response(200, {"ok": True})

    if method == "GET" and parts and parts[-1] == "health":
        return _response(
            200,
            {
                "status": "ok",
                "harnessConfigured": bool(HARNESS_ARN),
                "skillsConfigured": bool(S3_BUCKET and DEFAULT_SKILLS),
                "jobsTableConfigured": bool(JOBS_TABLE),
                "defaultSkills": DEFAULT_SKILLS,
                "region": BEDROCK_REGION,
                "mode": "async-jobs",
            },
        )

    if method == "POST" and parts and parts[-1] == "jobs":
        try:
            payload = _parse_body(event)
        except json.JSONDecodeError as e:
            return _response(400, {"error": f"Invalid JSON body: {e}"})
        return _handle_create_job(payload, context)

    if method == "GET" and parts and "jobs" in parts:
        job_id = _job_id_from_event(event, path)
        return _handle_get_job(job_id or "")

    if method == "POST" and parts and parts[-1] == "invoke":
        try:
            payload = _parse_body(event)
        except json.JSONDecodeError as e:
            return _response(400, {"error": f"Invalid JSON body: {e}"})
        return _handle_sync_invoke(payload)

    # Function URL root POST → treat as job create when jobs table is configured
    if method == "POST" and (not parts or parts == [""]):
        try:
            payload = _parse_body(event)
        except json.JSONDecodeError as e:
            return _response(400, {"error": f"Invalid JSON body: {e}"})
        if JOBS_TABLE:
            return _handle_create_job(payload, context)
        return _handle_sync_invoke(payload)

    return _response(405, {"error": f"Method not allowed: {method} {path}"})
