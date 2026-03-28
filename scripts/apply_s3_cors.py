"""
Apply CORS to the S3 bucket from backend/aws/s3-cors.example.json.

Requires IAM permission: s3:PutBucketCORS on the bucket (one-time setup).
Run from repo root:  cd backend && .venv\\Scripts\\python scripts/apply_s3_cors.py
Or:                   backend\\.venv\\Scripts\\python backend/scripts/apply_s3_cors.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings
from app.s3_service import s3_configured


def main() -> None:
    if not s3_configured():
        print("Missing S3 settings in backend/.env (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET).")
        sys.exit(1)

    cors_file = _backend_root / "aws" / "s3-cors.example.json"
    if not cors_file.is_file():
        print(f"Missing {cors_file}")
        sys.exit(1)

    raw = json.loads(cors_file.read_text(encoding="utf-8"))
    rules = raw.get("CORSRules")
    if not isinstance(rules, list) or not rules:
        print("Invalid JSON: expected top-level { \"CORSRules\": [ ... ] }")
        sys.exit(1)

    client = boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    try:
        client.put_bucket_cors(
            Bucket=settings.s3_bucket,
            CORSConfiguration={"CORSRules": rules},
        )
    except (ClientError, BotoCoreError) as e:
        print(f"put_bucket_cors failed: {e}")
        print("Ensure this IAM user has s3:PutBucketCORS on the bucket, or set CORS manually in the S3 console.")
        sys.exit(1)

    print(f"OK — CORS applied to s3://{settings.s3_bucket} ({settings.aws_region})")


if __name__ == "__main__":
    main()
