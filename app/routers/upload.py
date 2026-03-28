"""Presigned uploads to S3 (college ID cards)."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.deps import firebase_claims
from app.s3_service import (
    generate_college_id_presigned_put,
    generate_profile_picture_presigned_put,
    s3_configured,
)

router = APIRouter(prefix="/upload", tags=["upload"])


class CollegeIdPresignBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    role: str = Field(description="advisor or student")
    side: str = Field(description="front or back")
    content_type: str = Field(default="image/jpeg", alias="contentType")

    @field_validator("content_type")
    @classmethod
    def validate_mime(cls, v: str) -> str:
        from app.s3_service import _CONTENT_EXT
        ct = (v or "").split(";")[0].strip().lower()
        if ct not in _CONTENT_EXT:
            raise ValueError(f"Unsupported MIME type {v}. Use JPEG, PNG, or WebP.")
        return ct


class CollegeIdPresignResponse(BaseModel):
    uploadUrl: str
    key: str
    bucket: str


class ProfilePicturePresignBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    role: str = Field(description="advisor or student")
    content_type: str = Field(default="image/jpeg", alias="contentType")

    @field_validator("content_type")
    @classmethod
    def validate_mime(cls, v: str) -> str:
        from app.s3_service import _CONTENT_EXT
        ct = (v or "").split(";")[0].strip().lower()
        if ct not in _CONTENT_EXT:
            raise ValueError(f"Unsupported MIME type {v}. Use JPEG, PNG, or WebP.")
        return ct


@router.post("/college-id/presign", response_model=CollegeIdPresignResponse)
async def presign_college_id_upload(
    body: CollegeIdPresignBody,
    claims: dict = Depends(firebase_claims),
) -> CollegeIdPresignResponse:
    if not s3_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File uploads are not configured. Set AWS S3 environment variables on the API server.",
        )
    role = (body.role or "").strip().lower()
    side = (body.side or "").strip().lower()
    if role not in ("advisor", "student"):
        raise HTTPException(status_code=400, detail='role must be "advisor" or "student".')
    if side not in ("front", "back"):
        raise HTTPException(status_code=400, detail='side must be "front" or "back".')

    uid = claims.get("uid") or claims.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token.")

    try:
        url, key, bucket = generate_college_id_presigned_put(
            str(uid),
            role,  # type: ignore[arg-type]
            side,  # type: ignore[arg-type]
            body.content_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    return CollegeIdPresignResponse(uploadUrl=url, key=key, bucket=bucket)


@router.post("/profile-picture/presign", response_model=CollegeIdPresignResponse)
async def presign_profile_picture_upload(
    body: ProfilePicturePresignBody,
    claims: dict = Depends(firebase_claims),
) -> CollegeIdPresignResponse:
    if not s3_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File uploads are not configured. Set AWS S3 environment variables on the API server.",
        )
    role = (body.role or "").strip().lower()
    if role not in ("advisor", "student"):
        raise HTTPException(status_code=400, detail='role must be "advisor" or "student".')

    uid = claims.get("uid") or claims.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token.")

    try:
        url, key, bucket = generate_profile_picture_presigned_put(
            str(uid),
            role,  # type: ignore[arg-type]
            body.content_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    return CollegeIdPresignResponse(uploadUrl=url, key=key, bucket=bucket)
