"""Verify AWS S3 credentials and bucket reachability (reads backend/.env)."""

from __future__ import annotations

import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings
from app.s3_service import (
    _client,
    generate_college_id_presigned_put,
    generate_profile_picture_presigned_put,
    s3_configured,
)


def main() -> int:
    print("CollegeConnect S3 check")
    print("-" * 40)

    missing: list[str] = []
    if not settings.aws_access_key_id:
        missing.append("AWS_ACCESS_KEY_ID")
    if not settings.aws_secret_access_key:
        missing.append("AWS_SECRET_ACCESS_KEY")
    if not settings.aws_region:
        missing.append("AWS_REGION")
    if not settings.s3_bucket:
        missing.append("S3_BUCKET")

    if missing:
        print("NOT CONFIGURED — missing in backend/.env:", ", ".join(missing))
        return 2

    print(f"Region:     {settings.aws_region}")
    print(f"Bucket:     {settings.s3_bucket}")
    print(f"Key prefix: {(settings.s3_college_ids_prefix or 'college-ids').strip().strip('/')}")
    print(
        f"Profile prefix: {(settings.s3_profile_pictures_prefix or 'profile-pictures').strip().strip('/')}",
    )
    print("-" * 40)

    cli = _client()
    try:
        cli.head_bucket(Bucket=settings.s3_bucket)
        print("head_bucket: OK")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        print("head_bucket: skipped or failed (", code or str(e), ")")
        if code in ("403", "AccessDenied"):
            print(
                "  (Normal if IAM only allows s3:PutObject on a prefix; presign below is what matters.)",
            )
        elif code == "404":
            print("  Hint: Wrong bucket name or region.")
            return 1
    except BotoCoreError as e:
        print("Network / config error:", e)
        return 1

    try:
        url, key, bucket = generate_college_id_presigned_put(
            "diagnostic-test-uid",
            "student",
            "front",
            "image/jpeg",
        )
        assert bucket == settings.s3_bucket
        assert url.startswith("http")
        print("presign PutObject: OK")
        print(f"  sample key: {key}")
    except RuntimeError as e:
        print("presign FAILED:", e)
        return 1

    try:
        _url, pkey, pbucket = generate_profile_picture_presigned_put(
            "diagnostic-test-uid",
            "student",
            "image/jpeg",
        )
        assert pbucket == settings.s3_bucket
        print("presign profile picture PutObject: OK")
        print(f"  sample key: {pkey}")
    except RuntimeError as e:
        print("presign profile picture FAILED:", e)
        return 1

    print("-" * 40)
    print("All S3 checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
