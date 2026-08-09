#!/usr/bin/env python3
"""Minimal InvokeHarness smoke test using config.json."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

working_dir = os.path.dirname(os.path.abspath(__file__))
_config_path = os.path.join(working_dir, "config.json")
DEFAULT_SKILLS = ["businfo"]


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


def harness_name_from_config(cfg: Dict[str, Any]) -> str:
    name = (cfg.get("harnessName") or cfg.get("projectName") or "businfo").strip()
    return name.replace("-", "_")


def resolve_harness_arn(cfg: Dict[str, Any], region: str) -> tuple[str, Dict[str, Any]]:
    """Resolve Harness ARN from config.json, refreshing missing fields when possible."""
    arn = (cfg.get("HARNESS_ARN") or cfg.get("harnessArn") or "").strip()
    harness_id = (cfg.get("HARNESS_ID") or cfg.get("harnessId") or "").strip()
    updates: Dict[str, Any] = {}

    control = boto3.client("bedrock-agentcore-control", region_name=region)

    if arn and ":harness/" in arn:
        return arn, updates

    if harness_id:
        try:
            h = control.get_harness(harnessId=harness_id)["harness"]
            arn = (h.get("arn") or "").strip()
            if arn:
                updates["HARNESS_ARN"] = arn
                updates["HARNESS_ID"] = h.get("harnessId") or harness_id
                if h.get("harnessName"):
                    updates["harnessName"] = h["harnessName"]
                return arn, updates
        except ClientError as e:
            print(f"get_harness({harness_id}) failed: {e}", file=sys.stderr)

    api_name = harness_name_from_config(cfg)
    token: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"maxResults": 50}
        if token:
            kwargs["nextToken"] = token
        resp = control.list_harnesses(**kwargs)
        for h in resp.get("harnesses") or []:
            if h.get("harnessName") == api_name:
                harness_id = h.get("harnessId") or ""
                arn = (h.get("arn") or "").strip()
                if not arn and harness_id:
                    detail = control.get_harness(harnessId=harness_id)["harness"]
                    arn = (detail.get("arn") or "").strip()
                if arn:
                    updates["HARNESS_ARN"] = arn
                    updates["HARNESS_ID"] = harness_id
                    updates["harnessName"] = api_name
                    return arn, updates
        token = resp.get("nextToken")
        if not token:
            break

    raise SystemExit(
        f"Harness ARN not found in {_config_path} "
        f"(looked for harnessName={api_name!r}).\n"
        "Deploy first:\n"
        "  python installer.py --harness-only\n"
        "Then re-run this script; ARN will be read from config.json."
    )


def resolve_skills(cfg: Dict[str, Any]) -> list[dict]:
    """Build InvokeHarness skills payload (default: businfo on project S3)."""
    raw_uris = cfg.get("defaultSkillUris")
    if isinstance(raw_uris, list) and raw_uris:
        skills = []
        for item in raw_uris:
            if isinstance(item, str) and item.startswith("s3://"):
                skills.append({"s3": {"uri": item.rstrip("/") + "/"}})
            elif isinstance(item, dict):
                skills.append(item)
        if skills:
            return skills

    bucket = (cfg.get("bucketName") or "").strip()
    prefix = (cfg.get("skillsS3Prefix") or "").strip()
    names_raw = cfg.get("defaultSkills") or ",".join(DEFAULT_SKILLS)
    if isinstance(names_raw, list):
        names = [str(n).strip() for n in names_raw if str(n).strip()]
    else:
        names = [n.strip() for n in str(names_raw).split(",") if n.strip()]
    names = names or list(DEFAULT_SKILLS)

    if prefix.startswith("s3://"):
        base = prefix.rstrip("/")
        # skillsS3Prefix may already be s3://bucket/skills/
        return [{"s3": {"uri": f"{base}/{name}/"}} for name in names]

    if not bucket:
        raise SystemExit(
            "bucketName missing in config.json; cannot attach businfo skill. "
            "Run: python installer.py --harness-only"
        )
    skills_prefix = prefix.strip("/") or "skills"
    return [
        {"s3": {"uri": f"s3://{bucket}/{skills_prefix}/{name}/"}} for name in names
    ]


def main() -> int:
    cfg = load_config(_config_path)
    bedrock_region = cfg.get("region") or os.environ.get("AWS_REGION") or "us-west-2"

    harness_arn, updates = resolve_harness_arn(cfg, bedrock_region)
    if updates:
        cfg.update(updates)
        save_config(_config_path, cfg)
        print(f"Updated {_config_path} with: {', '.join(updates.keys())}")

    skills = resolve_skills(cfg)

    boto_config = Config(
        read_timeout=300,
        connect_timeout=60,
        retries={"max_attempts": 0},
    )
    runtime = boto3.client(
        "bedrock-agentcore",
        region_name=bedrock_region,
        config=boto_config,
    )

    session_id = os.environ.get(
        "RUNTIME_SESSION_ID",
        "1234abcd-12ab-34cd-56ef-1234567890ab",
    )
    prompt = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "businfo skill로 오늘 버스 도착 요약을 한 문단으로 알려주세요."
    )

    print(f"config={_config_path}")
    print(f"region={bedrock_region}")
    print(f"projectName={cfg.get('projectName', '')}")
    print(f"harnessArn={harness_arn}")
    print(f"skills={json.dumps(skills, ensure_ascii=False)}")
    print(f"apiGatewayUrl={cfg.get('apiGatewayUrl', '')}")
    print(f"lambdaFunctionUrl={cfg.get('lambdaFunctionUrl', '')}")
    print(f"runtimeSessionId={session_id}")
    print(f"prompt={prompt}")
    print("---", flush=True)

    response = runtime.invoke_harness(
        harnessArn=harness_arn,
        runtimeSessionId=session_id,
        messages=[
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
        skills=skills,
    )

    stream = response.get("stream")
    if stream is None:
        raise SystemExit(f"Empty Harness response: {response}")

    for event in stream:
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            if "text" in delta:
                print(delta["text"], end="", flush=True)
        elif "messageStop" in event:
            print(f"\n\n[Stop reason: {event['messageStop'].get('stopReason')}]")
        elif "metadata" in event:
            usage = event["metadata"].get("usage", {})
            print(
                f"\n[Tokens - input: {usage.get('inputTokens')}, "
                f"output: {usage.get('outputTokens')}]"
            )
        elif "runtimeClientError" in event:
            print(f"\n[Error]: {event['runtimeClientError'].get('message')}")
        else:
            keys = [k for k in event.keys() if not k.startswith("_")]
            if keys:
                print(f"\n[{', '.join(keys)}]", flush=True)

    print(flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
