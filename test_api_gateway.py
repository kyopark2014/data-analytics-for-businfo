#!/usr/bin/env python3
"""API Gateway → Lambda → Harness smoke test using config.json."""

from __future__ import annotations

import json
import os
import sys
import uuid
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

working_dir = os.path.dirname(os.path.abspath(__file__))
_config_path = os.path.join(working_dir, "config.json")
API_NAME = "api-harness-businfo"


def load_config(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                raise SystemExit(f"{path} is empty. Run installer.py first.")
            return json.loads(content)
    except FileNotFoundError:
        raise SystemExit(f"Missing {path}. Run installer.py first.") from None
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON in {path}: {e}") from e


def save_config(path: str, cfg: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _find_http_api(region: str, api_name: str, api_id: str = "") -> Optional[Dict[str, str]]:
    client = boto3.client("apigatewayv2", region_name=region)
    if api_id:
        try:
            api = client.get_api(ApiId=api_id)
            return {
                "api_id": api["ApiId"],
                "api_endpoint": api["ApiEndpoint"],
            }
        except ClientError as e:
            print(f"get_api({api_id}) failed: {e}", file=sys.stderr)

    paginator = client.get_paginator("get_apis")
    for page in paginator.paginate():
        for api in page.get("Items") or []:
            if api.get("Name") == api_name:
                return {
                    "api_id": api["ApiId"],
                    "api_endpoint": api["ApiEndpoint"],
                }
    return None


def resolve_api_urls(
    cfg: Dict[str, Any], region: str
) -> Tuple[str, str, Dict[str, Any]]:
    """Resolve invoke/health URLs from config.json, refreshing when possible."""
    updates: Dict[str, Any] = {}
    invoke_url = (cfg.get("apiGatewayUrl") or "").strip().rstrip("/")
    health_url = (cfg.get("apiGatewayHealthUrl") or "").strip().rstrip("/")

    if invoke_url and not health_url:
        if invoke_url.endswith("/invoke"):
            health_url = invoke_url[: -len("/invoke")] + "/health"
        else:
            health_url = invoke_url.rstrip("/") + "/health"
        updates["apiGatewayHealthUrl"] = health_url

    if invoke_url:
        return invoke_url, health_url, updates

    found = _find_http_api(
        region,
        api_name=API_NAME,
        api_id=(cfg.get("apiGatewayId") or "").strip(),
    )
    if not found:
        raise SystemExit(
            f"apiGatewayUrl not found in {_config_path} "
            f"(looked for HTTP API name={API_NAME!r}).\n"
            "Deploy first:\n"
            "  python installer.py --harness-only\n"
            "Then re-run this script; URL will be read from config.json."
        )

    endpoint = found["api_endpoint"].rstrip("/")
    invoke_url = f"{endpoint}/invoke"
    health_url = f"{endpoint}/health"
    updates.update(
        {
            "apiGatewayId": found["api_id"],
            "apiGatewayUrl": invoke_url,
            "apiGatewayHealthUrl": health_url,
        }
    )
    return invoke_url, health_url, updates


def http_json(
    method: str,
    url: str,
    body: Optional[Dict[str, Any]] = None,
    timeout: float = 90.0,
) -> Tuple[int, Dict[str, Any], str]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode() or 0
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        status = e.code
    except urllib.error.URLError as e:
        raise SystemExit(f"Request failed: {url}\n{e}") from e

    parsed: Dict[str, Any] = {}
    if raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
    return status, parsed, raw


def main() -> int:
    cfg = load_config(_config_path)
    region = cfg.get("region") or os.environ.get("AWS_REGION") or "us-west-2"

    invoke_url, health_url, updates = resolve_api_urls(cfg, region)
    if updates:
        cfg.update(updates)
        save_config(_config_path, cfg)
        print(f"Updated {_config_path} with: {', '.join(updates.keys())}")

    prompt = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "businfo skill로 오늘 버스 도착 요약을 한 문단으로 알려주세요."
    )
    session_id = os.environ.get(
        "RUNTIME_SESSION_ID",
        "1234abcd-12ab-34cd-56ef-1234567890ab",
    )
    # Lambda recommends runtimeSessionId length >= 33
    if len(session_id) < 33:
        session_id = f"{session_id}-{uuid.uuid4()}"

    # Lambda DEFAULT_SKILLS=businfo attaches S3 skill; optional override via env.
    skills_override = os.environ.get("SKILLS", "").strip()
    skills_payload: Optional[Any] = None
    if skills_override:
        skills_payload = [n.strip() for n in skills_override.split(",") if n.strip()]

    print(f"config={_config_path}")
    print(f"region={region}")
    print(f"projectName={cfg.get('projectName', '')}")
    print(f"apiGatewayUrl={invoke_url}")
    print(f"apiGatewayHealthUrl={health_url}")
    print(f"lambdaHarnessArn={cfg.get('lambdaHarnessArn', '')}")
    print(f"HARNESS_ARN={cfg.get('HARNESS_ARN', '')}")
    print(f"defaultSkills={cfg.get('defaultSkills', 'businfo')}")
    print(f"skillsS3Prefix={cfg.get('skillsS3Prefix', '')}")
    print(f"sessionId={session_id}")
    print(f"prompt={prompt}")
    if skills_payload is not None:
        print(f"skillsOverride={skills_payload}")
    print("---", flush=True)

    # 1) Health
    print("[1/2] GET /health", flush=True)
    status, health_body, _ = http_json("GET", health_url, timeout=15.0)
    print(f"status={status}")
    print(json.dumps(health_body, ensure_ascii=False, indent=2))
    if status != 200 or not health_body.get("status") == "ok":
        if status != 200:
            raise SystemExit(f"Health check failed with HTTP {status}")
    if not health_body.get("harnessConfigured", True):
        print(
            "warning: Lambda reports harnessConfigured=false "
            "(HARNESS_ARN env may be missing)",
            file=sys.stderr,
        )
    if not health_body.get("skillsConfigured", True):
        print(
            "warning: Lambda reports skillsConfigured=false "
            "(S3_BUCKET / DEFAULT_SKILLS env may be missing)",
            file=sys.stderr,
        )
    print("---", flush=True)

    # 2) Invoke via API Gateway → Lambda → Harness (businfo skill attached)
    print("[2/2] POST /invoke  (API Gateway → Lambda → Harness + businfo skill)", flush=True)
    invoke_body: Dict[str, Any] = {"prompt": prompt, "sessionId": session_id}
    if skills_payload is not None:
        invoke_body["skills"] = skills_payload
    # API GW integration timeout ~29s; allow a little headroom on the client.
    status, body, raw = http_json(
        "POST",
        invoke_url,
        body=invoke_body,
        timeout=35.0,
    )
    print(f"status={status}", flush=True)
    if status != 200:
        print(raw)
        raise SystemExit(f"Invoke failed with HTTP {status}")

    result = body.get("result")
    returned_session = body.get("sessionId") or session_id
    if result is None and body.get("error"):
        raise SystemExit(f"Invoke error: {body.get('error')}")

    print(result if result is not None else raw)
    print(flush=True)
    print(f"[sessionId: {returned_session}]")
    if body.get("skills"):
        print(f"[skills: {json.dumps(body.get('skills'), ensure_ascii=False)}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
