from __future__ import annotations
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import get_app
import asyncio

from app.firebase_service import verify_id_token

security = HTTPBearer(auto_error=False)


async def firebase_claims(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    try:
        get_app()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Firebase Admin not configured (set FIREBASE_SERVICE_ACCOUNT_PATH or "
                "GOOGLE_APPLICATION_CREDENTIALS in backend/.env to your service account JSON)"
            ),
        ) from e
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <Firebase ID token> required",
        )
    try:
        return await asyncio.to_thread(verify_id_token, creds.credentials)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Firebase token.",
        )
