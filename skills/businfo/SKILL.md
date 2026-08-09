---
name: businfo
description: Amazon Athena(AwsDataCatalog.businfo)로 실시간 버스 도착·잔여좌석 정보를 조회합니다. 차량번호(번호판), 노선 ID, 최근 N시간, 일별 요약 조회에 사용합니다. 사용자가 "버스 잔여좌석", "버스 도착", "차량번호", "노선", "businfo", "Athena 버스" 등을 요청할 때 사용합니다.
---

# Businfo (Athena)

경기 버스 도착/잔여좌석 데이터를 **Amazon Athena**로 조회합니다. 임의 SQL을 새로 짜지 말고, 아래 스크립트를 실행하세요.

## When to Use

- 특정 차량번호의 잔여좌석 추이 (예: 경기74아3798 오늘)
- 최근 N시간 버스 도착 현황
- 노선 ID별 도착/좌석 조회
- 일별 건수·노선·차량 요약
- businfo / Athena 버스 데이터 관련 질문

## Setup (code interpreter)

AgentCore code 인터프리터에는 skill 파일이 미리 마운트되지 않을 수 있습니다.
**조회 전에 반드시 S3에서 동기화**하세요.

```bash
# 계정/리전에 맞게 버킷명 확인 (환경변수 S3_BUCKET 우선)
BUCKET="${S3_BUCKET:-businfo-$(aws sts get-caller-identity --query Account --output text)-us-west-2}"
aws s3 sync "s3://${BUCKET}/skills/businfo/" /tmp/businfo/
CLI=/tmp/businfo/scripts/query_businfo.py
```

| 스크립트 | 용도 |
| --- | --- |
| `/tmp/businfo/scripts/query_businfo.py` | 조회 CLI (recent / plate / route / summary / sql) |
| `/tmp/businfo/scripts/lib_athena.py` | Athena·Glue·파티션 헬퍼 (직접 실행하지 않음) |

S3 원본: `s3://{bucket}/skills/businfo/`

**IMPORTANT**: 동기화 없이 `/home/.agents/...` 나 `skills/businfo/...` 상대경로를 가정하지 마세요.

## Critical Rules

1. **반드시 스크립트로 조회**하세요. AWS CLI로 ad-hoc SQL을 새로 작성하지 마세요.
2. 조회 전 스크립트가 Glue 파티션을 자동 등록합니다. 별도 `MSCK REPAIR` 불필요.
3. 시각은 사용자에게 **KST**로 보여주세요. (원본 timestamp는 Unix epoch 문자열)
4. 이 데이터는 특정 정류장 기준 수집이라, 하루 종일 연속이 아니라 **해당 지점 근처일 때만** 관측됩니다. 결과가 적으면 그 점을 설명하세요.
5. `sql` 서브커맨드는 `SELECT`/`WITH`/`SHOW`/`DESCRIBE`/`EXPLAIN`만 허용됩니다.

## Data Model

| 항목 | 값 |
| --- | --- |
| Region | `us-west-2` |
| Catalog | `AwsDataCatalog` |
| Database / Table | `businfo` / `businfo` |
| Workgroup | `primary` |
| Partition | `partition_0=YYYY`, `partition_1=MM`, `partition_2=DD`, `partition_3=HH` (UTC) |
| S3 data | `s3://businfo-{account}-us-west-2/businfo/YYYY/MM/DD/HH/` |

컬럼:

| 컬럼 | 설명 |
| --- | --- |
| `timestamp` | Unix epoch (string) |
| `routeid` | 노선 ID |
| `remainseatcnt` | 잔여좌석 |
| `plateno` | 차량번호 |
| `predicttime` | 도착 예측(분) |

## Quick Start

```bash
BUCKET="${S3_BUCKET:-businfo-$(aws sts get-caller-identity --query Account --output text)-us-west-2}"
aws s3 sync "s3://${BUCKET}/skills/businfo/" /tmp/businfo/
CLI=/tmp/businfo/scripts/query_businfo.py

# 최근 1시간
python "$CLI" recent --hours 1

# 차량번호 금일 잔여좌석
python "$CLI" plate "경기74아3798" --day today

# 노선 금일
python "$CLI" route 222000076 --day today

# 일별 요약
python "$CLI" summary --day today

# JSON 출력
python "$CLI" plate "경기74아3798" --day today --json
```

### Agent usage

```python
import os, subprocess

bucket = os.environ.get("S3_BUCKET") or (
    "businfo-" + __import__("boto3").client("sts").get_caller_identity()["Account"] + "-us-west-2"
)
subprocess.run(["aws", "s3", "sync", f"s3://{bucket}/skills/businfo/", "/tmp/businfo/"], check=True)
CLI = "/tmp/businfo/scripts/query_businfo.py"

r = subprocess.run(
    ["python", CLI, "plate", "경기74아3798", "--day", "today", "--json"],
    capture_output=True, text=True,
)
print(r.stdout)
```

## Subcommands

| 명령 | 설명 | 주요 옵션 |
| --- | --- |
| `recent` | 최근 N시간 | `--hours`, `--limit` |
| `plate <번호>` | 차량별 잔여좌석 + 시간대 요약 | `--day`, `--limit` |
| `route <routeid>` | 노선별 도착 | `--day`, `--limit` |
| `summary` | 일별 집계 | `--day` |
| `sql "<SQL>"` | 읽기 전용 커스텀 SQL | — |

`--day` 값: `today` / `yesterday` / `YYYY-MM-DD` (KST 기준 일자)

## Response Format

사용자 응답은 한국어로, 가능하면 표로 정리합니다.

```
차량번호: 경기74아3798
날짜: 2026-08-05
관측: N건 | 잔여좌석 min=.. max=.. avg=..

시간대별 / 상세 추이 표
```

관측이 특정 시간대에만 있으면 "정류장 근접 시에만 수집"된다고 안내하세요.

## Dependencies

- `boto3` (code 인터프리터 / runtime에 포함)
- AWS CLI (`aws`) — skill sync용
- AWS 자격증명: Athena / Glue / S3 읽기 + Athena 결과 버킷 쓰기
- 기본 결과 위치: `s3://aws-athena-query-results-{account}-us-west-2/`

환경변수(선택):

| 변수 | 기본 |
| --- | --- |
| `S3_BUCKET` | `businfo-{account}-us-west-2` |
| `BUSINFO_REGION` | `us-west-2` |
| `BUSINFO_DATABASE` / `BUSINFO_TABLE` | `businfo` |
| `BUSINFO_OUTPUT_LOCATION` | Athena results bucket |
| `BUSINFO_DATA_PREFIX` | `s3://businfo-{account}-{region}/businfo/` |

## Troubleshooting

### `No such file or directory: /tmp/businfo/...`

`aws s3 sync s3://{bucket}/skills/businfo/ /tmp/businfo/`를 먼저 실행하세요.

### `no S3 data for YYYY-MM-DD`

해당 일자 Firehose 적재가 없습니다. 날짜를 확인하거나 `recent`로 최근 창을 조회하세요.

### `AccessDenied` / credentials

`aws sts get-caller-identity`로 계정·권한을 확인하세요. Athena·Glue·결과 S3·skills S3 권한이 필요합니다.

### 결과가 비어 있음

파티션은 스크립트가 등록하지만, S3에 파일이 없으면 빈 결과입니다. `summary --day today`로 먼저 확인하세요.
