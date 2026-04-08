from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import secrets

def _now() -> datetime:
    return datetime.utcnow()


def hash_temp_upload_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_temp_upload_token() -> str:
    return secrets.token_urlsafe(32)


async def create_temp_upload_record(
    db,
    *,
    role: str,
    front_key: str,
    back_key: str,
    ttl_minutes: int,
) -> str:
    token = issue_temp_upload_token()
    token_hash = hash_temp_upload_token(token)
    now = _now()
    await db.signup_temp_uploads.insert_one(
        {
            "token_hash": token_hash,
            "role": role,
            "front_key": front_key,
            "back_key": back_key,
            "created_at": now,
            "expires_at": now + timedelta(minutes=max(1, int(ttl_minutes))),
            "claimed": False,
        }
    )
    return token


async def get_temp_upload_record(
    db,
    *,
    role: str,
    raw_token: str,
) -> dict | None:
    token_hash = hash_temp_upload_token(raw_token)
    now = _now()
    doc = await db.signup_temp_uploads.find_one(
        {
            "token_hash": token_hash,
            "role": role,
            "claimed": {"$ne": True},
            "expires_at": {"$gt": now},
        }
    )
    return doc


async def mark_temp_upload_claimed(
    db,
    *,
    role: str,
    raw_token: str,
    claimed_by_uid: str,
) -> bool:
    token_hash = hash_temp_upload_token(raw_token)
    now = _now()
    result = await db.signup_temp_uploads.update_one(
        {
            "token_hash": token_hash,
            "role": role,
            "claimed": {"$ne": True},
            "expires_at": {"$gt": now},
        },
        {
            "$set": {
                "claimed": True,
                "claimed_by_uid": claimed_by_uid,
                "claimed_at": now,
            }
        },
    )
    return result.modified_count == 1
