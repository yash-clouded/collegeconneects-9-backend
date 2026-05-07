from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.config import settings


def _require_secret() -> str:
    secret = (settings.jwt_secret_key or "").strip()
    if not secret:
        raise ValueError("JWT_SECRET_KEY is not configured.")
    return secret


def create_access_token(*, claims: dict[str, Any]) -> tuple[str, int]:
    secret = _require_secret()
    expires_delta = timedelta(minutes=max(1, int(settings.jwt_access_token_exp_minutes)))
    now = datetime.now(timezone.utc)
    expire_at = now + expires_delta
    payload = {
        **claims,
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int(expire_at.timestamp()),
        "token_type": "access",
    }
    token = jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    secret = _require_secret()
    return jwt.decode(
        token,
        secret,
        algorithms=[settings.jwt_algorithm],
        issuer=settings.jwt_issuer,
        options={"require": ["exp", "iat", "iss"]},
    )
