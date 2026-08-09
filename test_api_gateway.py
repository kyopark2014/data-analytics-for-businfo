#!/usr/bin/env python3
"""API Gateway → async jobs → Lambda worker → Harness smoke test."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

working_dir = os.path.dirname(os.path.abspath(__file__))
_config_path = os.path.join(working_dir, "config.json")
API_NAME = "api-harness-businfo"
POLL_INTERVAL_S = 2.0
POLL_MAX_S = 300.0


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


def _base_from_url(url: str) -> str:
    u = (url or "").rstrip("/")
    for suffix in ("/jobs", "/invoke", "/health"):
        if u.endswith(suffix):
            return u[: -len(suffix)]
    return u


def resolve_api_urls(
    cfg: Dict[str, Any], region: str
) -> Tuple[str, str, str, Dict[str, Any]]:
    """Resolve jobs/health/invoke URLs from config.json."""
    updates: Dict[str, Any] = {}
    jobs_url = (cfg.get("apiJobsUrl") or cfg.get("apiGatewayUrl") or "").strip().rstrip(
        "/"
    )
    health_url = (cfg.get("apiGatewayHealthUrl") or "").strip().rstrip("/")
    invoke_url = (cfg.get("apiGatewayInvokeUrl") or "").strip().rstrip("/")

    if jobs_url.endswith("/invoke"):
        jobs_url = jobs_url[: -len("/invoke")] + "/jobs"
        updates["apiJobsUrl"] = jobs_url
        updates["apiGatewayUrl"] = jobs_url

    if jobs_url and not jobs_url.endswith("/jobs"):
        base = _base_from_url(jobs_url)
        jobs_url = f"{base}/jobs"
        updates["apiJobsUrl"] = jobs_url
        updates["apiGatewayUrl"] = jobs_url

    if jobs_url and not health_url:
        health_url = _base_from_url(jobs_url) + "/health"
        updates["apiGatewayHealthUrl"] = health_url

    if jobs_url and not invoke_url:
        invoke_url = _base_from_url(jobs_url) + "/invoke"
        updates["apiGatewayInvokeUrl"] = invoke_url

    if jobs_url:
        return jobs_url, health_url, invoke_url, updates

    found = _find_http_api(
        region,
        api_name=API_NAME,
        api_id=(cfg.get("apiGatewayId") or "").strip(),
    )
    if not found:
        raise SystemExit(
            f"apiJobsUrl not found in {_config_path} "
            f"(looked for HTTP API name={API_NAME!r}).\n"
            "Deploy first:\n"
            "  python installer.py --harness-only\n"
            "Then re-run this script; URL will be read from config.json."
        )

    endpoint = found["api_endpoint"].rstrip("/")
    jobs_url = f"{endpoint}/jobs"
    health_url = f"{endpoint}/health"
    invoke_url = f"{endpoint}/invoke"
    updates.update(
        {
            "apiGatewayId": found["api_id"],
            "apiJobsUrl": jobs_url,
            "apiGatewayUrl": jobs_url,
            "apiGatewayHealthUrl": health_url,
            "apiGatewayInvokeUrl": invoke_url,
        }
    )
    return jobs_url, health_url, invoke_url, updates


def http_json(
    method: str,
    url: str,
    body: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
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

    jobs_url, health_url, invoke_url, updates = resolve_api_urls(cfg, region)
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
    if len(session_id) < 33:
        session_id = f"{session_id}-{uuid.uuid4()}"

    skills_override = os.environ.get("SKILLS", "").strip()
    skills_payload: Optional[Any] = None
    if skills_override:
        skills_payload = [n.strip() for n in skills_override.split(",") if n.strip()]

    print(f"config={_config_path}")
    print(f"region={region}")
    print(f"projectName={cfg.get('projectName', '')}")
    print(f"apiJobsUrl={jobs_url}")
    print(f"apiGatewayHealthUrl={health_url}")
    print(f"apiGatewayInvokeUrl={invoke_url}")
    print(f"jobsTableName={cfg.get('jobsTableName', '')}")
    print(f"lambdaHarnessArn={cfg.get('lambdaHarnessArn', '')}")
    print(f"HARNESS_ARN={cfg.get('HARNESS_ARN', '')}")
    print(f"defaultSkills={cfg.get('defaultSkills', 'businfo')}")
    print(f"skillsS3Prefix={cfg.get('skillsS3Prefix', '')}")
    print(f"sessionId={session_id}")
    print(f"prompt={prompt}")
    if skills_payload is not None:
        print(f"skillsOverride={skills_payload}")
    print("---", flush=True)

    print("[1/3] GET /health", flush=True)
    status, health_body, _ = http_json("GET", health_url, timeout=15.0)
    print(f"status={status}")
    print(json.dumps(health_body, ensure_ascii=False, indent=2))
    if status != 200 or health_body.get("status") != "ok":
        raise SystemExit(f"Health check failed with HTTP {status}")
    if not health_body.get("harnessConfigured", True):
        print(
            "warning: Lambda reports harnessConfigured=false",
            file=sys.stderr,
        )
    if not health_body.get("jobsTableConfigured", True):
        print(
            "warning: Lambda reports jobsTableConfigured=false "
            "(redeploy with installer.py --harness-only)",
            file=sys.stderr,
        )
    print("---", flush=True)

    print("[2/3] POST /jobs  (create async job)", flush=True)
    create_body: Dict[str, Any] = {"prompt": prompt, "sessionId": session_id}
    if skills_payload is not None:
        create_body["skills"] = skills_payload
    status, body, raw = http_json("POST", jobs_url, body=create_body, timeout=30.0)
    print(f"status={status}", flush=True)
    if status not in (200, 202):
        print(raw)
        raise SystemExit(f"Create job failed with HTTP {status}")
    job_id = body.get("jobId")
    if not job_id:
        print(raw)
        raise SystemExit("Create job response missing jobId")
    print(json.dumps(body, ensure_ascii=False, indent=2), flush=True)
    print("---", flush=True)

    poll_url = f"{jobs_url.rstrip('/')}/{job_id}"
    print(f"[3/3] GET {poll_url}  (poll until SUCCEEDED/FAILED)", flush=True)
    deadline = time.time() + POLL_MAX_S
    final: Dict[str, Any] = {}
    while time.time() < deadline:
        status, final, raw = http_json("GET", poll_url, timeout=30.0)
        if status != 200:
            print(raw)
            raise SystemExit(f"Poll failed with HTTP {status}")
        job_status = final.get("status")
        print(f"  status={job_status}", flush=True)
        if job_status in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(POLL_INTERVAL_S)
    else:
        raise SystemExit(f"Timed out waiting for job {job_id} after {POLL_MAX_S:.0f}s")

    if final.get("status") == "FAILED":
        raise SystemExit(f"Job failed: {final.get('error')}")

    result = final.get("result")
    returned_session = final.get("sessionId") or session_id
    print(result if result is not None else raw)
    print(flush=True)
    print(f"[jobId: {job_id}]")
    print(f"[sessionId: {returned_session}]")
    if final.get("skills"):
        print(f"[skills: {json.dumps(final.get('skills'), ensure_ascii=False)}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
