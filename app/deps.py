from __future__ import annotations
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from app.jwt_service import decode_access_token

security = HTTPBearer(auto_error=False)


async def firebase_claims(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <JWT token> required",
        )

    try:
        claims = decode_access_token(creds.credentials)
        if claims.get("uid"):
            return claims
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
