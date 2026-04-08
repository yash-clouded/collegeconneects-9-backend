"""Presigned PUT URLs for college ID images (private S3 bucket)."""

from __future__ import annotations

import uuid
import secrets
from typing import Literal

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings

_CONTENT_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def s3_configured() -> bool:
    return bool(
        settings.aws_access_key_id
        and settings.aws_secret_access_key
        and settings.aws_region
        and settings.s3_bucket
    )


def _client():
    return boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        config=BotoConfig(signature_version="s3v4"),
    )


def _validate_uid(uid: str) -> None:
    import re
    if not re.match(r"^[A-Za-z0-9_-]{1,128}$", uid):
        raise ValueError("Invalid Firebase UID format.")

def generate_college_id_presigned_put(
    firebase_uid: str,
    role: Literal["advisor", "student"],
    side: Literal["front", "back"],
    content_type: str,
) -> tuple[str, str, str]:
    """
    Returns (presigned_put_url, object_key, bucket).
    """
    _validate_uid(firebase_uid)
    if not s3_configured():
        raise RuntimeError("S3 is not configured (missing AWS credentials or bucket).")

    ct = (content_type or "image/jpeg").split(";")[0].strip().lower()
    if ct not in _CONTENT_EXT:
        raise ValueError(
            f"Unsupported content type {content_type!r}. Use image/jpeg, image/png, or image/webp.",
        )
    ext = _CONTENT_EXT[ct]
    prefix = (settings.s3_college_ids_prefix or "college-ids").strip().strip("/")
    key = f"{prefix}/{role}s/{firebase_uid}/{side}_{uuid.uuid4().hex[:12]}.{ext}"
    bucket = settings.s3_bucket

    try:
        cli = _client()
        url = cli.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ContentType": ct,
            },
            ExpiresIn=900,
            HttpMethod="PUT",
        )
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"S3 presign failed: {e!s}") from e

    return url, key, bucket


def generate_profile_picture_presigned_put(
    firebase_uid: str,
    role: Literal["advisor", "student"],
    content_type: str,
) -> tuple[str, str, str]:
    """Returns (presigned_put_url, object_key, bucket) for optional profile avatar."""
    _validate_uid(firebase_uid)
    if not s3_configured():
        raise RuntimeError("S3 is not configured (missing AWS credentials or bucket).")

    ct = (content_type or "image/jpeg").split(";")[0].strip().lower()
    if ct not in _CONTENT_EXT:
        raise ValueError(
            f"Unsupported content type {content_type!r}. Use image/jpeg, image/png, or image/webp.",
        )
    ext = _CONTENT_EXT[ct]
    prefix = (settings.s3_profile_pictures_prefix or "profile-pictures").strip().strip("/")
    key = f"{prefix}/{role}s/{firebase_uid}/avatar_{uuid.uuid4().hex[:12]}.{ext}"
    bucket = settings.s3_bucket

    try:
        cli = _client()
        url = cli.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ContentType": ct,
            },
            ExpiresIn=900,
            HttpMethod="PUT",
        )
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"S3 presign failed: {e!s}") from e

    return url, key, bucket


def generate_temp_college_id_presigned_put(
    role: Literal["advisor", "student"],
    side: Literal["front", "back"],
    content_type: str,
    upload_group_id: str | None = None,
) -> tuple[str, str, str]:
    """Returns (presigned_put_url, temp_object_key, bucket) for unauthenticated pre-signup uploads."""
    if not s3_configured():
        raise RuntimeError("S3 is not configured (missing AWS credentials or bucket).")

    ct = (content_type or "image/jpeg").split(";")[0].strip().lower()
    if ct not in _CONTENT_EXT:
        raise ValueError(
            f"Unsupported content type {content_type!r}. Use image/jpeg, image/png, or image/webp.",
        )
    ext = _CONTENT_EXT[ct]
    prefix = (settings.s3_temp_college_ids_prefix or "college-ids-temp").strip().strip("/")
    group = (upload_group_id or secrets.token_hex(8)).strip()
    if not group:
        group = secrets.token_hex(8)
    key = f"{prefix}/{role}s/{group}/{side}_{uuid.uuid4().hex[:12]}.{ext}"
    bucket = settings.s3_bucket

    try:
        cli = _client()
        url = cli.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ContentType": ct,
            },
            ExpiresIn=300,
            HttpMethod="PUT",
        )
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"S3 presign failed: {e!s}") from e

    return url, key, bucket


def upload_temp_college_id_object(
    role: Literal["advisor", "student"],
    side: Literal["front", "back"],
    content_type: str,
    content: bytes,
    upload_group_id: str | None = None,
) -> tuple[str, str]:
    """Direct backend upload to temporary S3 location. Returns (key, bucket)."""
    if not s3_configured():
        raise RuntimeError("S3 is not configured (missing AWS credentials or bucket).")

    ct = (content_type or "image/jpeg").split(";")[0].strip().lower()
    if ct not in _CONTENT_EXT:
        raise ValueError(
            f"Unsupported content type {content_type!r}. Use image/jpeg, image/png, or image/webp.",
        )
    ext = _CONTENT_EXT[ct]
    prefix = (settings.s3_temp_college_ids_prefix or "college-ids-temp").strip().strip("/")
    group = (upload_group_id or secrets.token_hex(8)).strip() or secrets.token_hex(8)
    key = f"{prefix}/{role}s/{group}/{side}_{uuid.uuid4().hex[:12]}.{ext}"
    bucket = settings.s3_bucket

    try:
        cli = _client()
        cli.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=ct,
        )
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"S3 direct upload failed: {e!s}") from e

    return key, bucket


def temp_college_id_keys_valid_for_role(
    role: Literal["advisor", "student"],
    front_key: str,
    back_key: str,
) -> bool:
    prefix = (settings.s3_temp_college_ids_prefix or "college-ids-temp").strip().strip("/")
    base = f"{prefix}/{role}s/"
    fk = str(front_key or "").strip()
    bk = str(back_key or "").strip()
    if not fk.startswith(base) or not bk.startswith(base):
        return False
    fn_f = fk.split("/")[-1] if fk else ""
    fn_b = bk.split("/")[-1] if bk else ""
    return fn_f.startswith("front_") and fn_b.startswith("back_")


def move_temp_college_id_to_user(
    firebase_uid: str,
    role: Literal["advisor", "student"],
    side: Literal["front", "back"],
    temp_key: str,
) -> str:
    """Copy temp upload object to permanent user path and delete temp object; returns final key."""
    _validate_uid(firebase_uid)
    if not s3_configured():
        raise RuntimeError("S3 is not configured (missing AWS credentials or bucket).")

    temp_prefix = (settings.s3_temp_college_ids_prefix or "college-ids-temp").strip().strip("/")
    source_key = str(temp_key or "").strip()
    expected_base = f"{temp_prefix}/{role}s/"
    if not source_key.startswith(expected_base):
        raise ValueError("Temporary college ID key is invalid for this role.")

    filename = source_key.split("/")[-1]
    if side == "front" and not filename.startswith("front_"):
        raise ValueError("Temporary front key is invalid.")
    if side == "back" and not filename.startswith("back_"):
        raise ValueError("Temporary back key is invalid.")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "jpg"

    final_prefix = (settings.s3_college_ids_prefix or "college-ids").strip().strip("/")
    final_key = f"{final_prefix}/{role}s/{firebase_uid}/{side}_{uuid.uuid4().hex[:12]}.{ext}"
    bucket = settings.s3_bucket

    try:
        cli = _client()
        cli.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": source_key},
            Key=final_key,
            MetadataDirective="COPY",
        )
        cli.delete_object(Bucket=bucket, Key=source_key)
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"S3 move failed: {e!s}") from e

    return final_key


def profile_picture_key_valid_for_uid(
    firebase_uid: str,
    role: Literal["advisor", "student"],
    key: str,
) -> bool:
    prefix = (settings.s3_profile_pictures_prefix or "profile-pictures").strip().strip("/")
    base = f"{prefix}/{role}s/{firebase_uid}/"
    k = str(key).strip()
    if not k.startswith(base):
        return False
    fn = k.split("/")[-1] if k else ""
    return fn.startswith("avatar_")


def college_id_keys_valid_for_uid(
    firebase_uid: str,
    role: Literal["advisor", "student"],
    front_key: str | None,
    back_key: str | None,
) -> bool:
    """Ensure keys were issued for this Firebase user (prefix + filename side markers)."""
    if not front_key or not back_key:
        return False
    prefix = (settings.s3_college_ids_prefix or "college-ids").strip().strip("/")
    base = f"{prefix}/{role}s/{firebase_uid}/"
    fk = str(front_key).strip()
    bk = str(back_key).strip()
    if not fk.startswith(base) or not bk.startswith(base):
        return False
    fn_f = fk.split("/")[-1] if fk else ""
    fn_b = bk.split("/")[-1] if bk else ""
    return fn_f.startswith("front_") and fn_b.startswith("back_")
