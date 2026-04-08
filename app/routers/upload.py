"""Presigned uploads to S3 (college ID cards)."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings
from app.database import get_database
from app.deps import firebase_claims
from app.s3_service import (
    _CONTENT_EXT,
    generate_temp_college_id_presigned_put,
    generate_college_id_presigned_put,
    generate_profile_picture_presigned_put,
    s3_configured,
    temp_college_id_keys_valid_for_role,
    upload_temp_college_id_object,
)
from app.temp_uploads import create_temp_upload_record

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


class TempCollegeIdPairPresignBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    role: str = Field(description="advisor or student")
    front_content_type: str = Field(default="image/jpeg", alias="frontContentType")
    back_content_type: str = Field(default="image/jpeg", alias="backContentType")

    @field_validator("front_content_type", "back_content_type")
    @classmethod
    def validate_mime(cls, v: str) -> str:
        from app.s3_service import _CONTENT_EXT
        ct = (v or "").split(";")[0].strip().lower()
        if ct not in _CONTENT_EXT:
            raise ValueError(f"Unsupported MIME type {v}. Use JPEG, PNG, or WebP.")
        return ct


class TempCollegeIdPairPresignResponse(BaseModel):
    tempUploadToken: str
    bucket: str
    expiresAt: datetime
    front: CollegeIdPresignResponse
    back: CollegeIdPresignResponse


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


@router.post("/college-id/temp/presign", response_model=TempCollegeIdPairPresignResponse)
async def presign_temp_college_id_pair_upload(
    body: TempCollegeIdPairPresignBody,
) -> TempCollegeIdPairPresignResponse:
    """Unauthenticated temporary upload URLs for signup ID OCR flow.

    Security model:
    - short-lived presigned URLs
    - keys under temporary prefix only
    - returns one-time token stored hashed in Mongo with TTL
    - token is consumed during final authenticated signup profile creation
    """
    if not s3_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File uploads are not configured. Set AWS S3 environment variables on the API server.",
        )

    role = (body.role or "").strip().lower()
    if role not in ("advisor", "student"):
        raise HTTPException(status_code=400, detail='role must be "advisor" or "student".')

    try:
        front_url, front_key, bucket = generate_temp_college_id_presigned_put(
            role,  # type: ignore[arg-type]
            "front",
            body.front_content_type,
        )
        back_url, back_key, _ = generate_temp_college_id_presigned_put(
            role,  # type: ignore[arg-type]
            "back",
            body.back_content_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    if not temp_college_id_keys_valid_for_role(role, front_key, back_key):
        raise HTTPException(status_code=500, detail="Could not issue temporary upload keys.")

    db = get_database()
    ttl = max(1, int(settings.signup_temp_upload_ttl_minutes or 30))
    token = await create_temp_upload_record(
        db,
        role=role,
        front_key=front_key,
        back_key=back_key,
        ttl_minutes=ttl,
    )
    expires_at = datetime.utcnow() + timedelta(minutes=ttl)

    return TempCollegeIdPairPresignResponse(
        tempUploadToken=token,
        bucket=bucket,
        expiresAt=expires_at,
        front=CollegeIdPresignResponse(uploadUrl=front_url, key=front_key, bucket=bucket),
        back=CollegeIdPresignResponse(uploadUrl=back_url, key=back_key, bucket=bucket),
    )


@router.post("/college-id/temp/upload", response_model=TempCollegeIdPairPresignResponse)
async def upload_temp_college_id_pair(
    role: str = Form(...),
    front_file: UploadFile = File(...),
    back_file: UploadFile = File(...),
) -> TempCollegeIdPairPresignResponse:
    """Unauthenticated direct upload path for temporary signup ID images.

    Useful when S3 browser CORS is restricted; backend performs S3 upload directly.
    """
    if not s3_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File uploads are not configured. Set AWS S3 environment variables on the API server.",
        )

    role = (role or "").strip().lower()
    if role not in ("advisor", "student"):
        raise HTTPException(status_code=400, detail='role must be "advisor" or "student".')

    front_ct = (front_file.content_type or "").split(";")[0].strip().lower()
    back_ct = (back_file.content_type or "").split(";")[0].strip().lower()
    if front_ct not in _CONTENT_EXT or back_ct not in _CONTENT_EXT:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, or WebP files are supported.")

    front_bytes = await front_file.read()
    back_bytes = await back_file.read()
    max_bytes = 5 * 1024 * 1024
    if len(front_bytes) > max_bytes or len(back_bytes) > max_bytes:
        raise HTTPException(status_code=400, detail="Each image must be <= 5MB.")

    group_id = __import__("secrets").token_hex(8)
    try:
        front_key, bucket = upload_temp_college_id_object(
            role,  # type: ignore[arg-type]
            "front",
            front_ct,
            front_bytes,
            upload_group_id=group_id,
        )
        back_key, _ = upload_temp_college_id_object(
            role,  # type: ignore[arg-type]
            "back",
            back_ct,
            back_bytes,
            upload_group_id=group_id,
        )
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    db = get_database()
    ttl = max(1, int(settings.signup_temp_upload_ttl_minutes or 30))
    token = await create_temp_upload_record(
        db,
        role=role,
        front_key=front_key,
        back_key=back_key,
        ttl_minutes=ttl,
    )
    expires_at = datetime.utcnow() + timedelta(minutes=ttl)

    return TempCollegeIdPairPresignResponse(
        tempUploadToken=token,
        bucket=bucket,
        expiresAt=expires_at,
        front=CollegeIdPresignResponse(uploadUrl="", key=front_key, bucket=bucket),
        back=CollegeIdPresignResponse(uploadUrl="", key=back_key, bucket=bucket),
    )
