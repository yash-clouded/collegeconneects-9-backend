from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import secrets
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.database import get_database
from app.mailer import send_password_reset_otp_email, send_signup_otp_email

router = APIRouter(prefix="/auth", tags=["auth"])

OTP_TTL_MINUTES = 10
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_MAX_ATTEMPTS = 5


class PasswordResetRequest(BaseModel):
    role: str = Field(pattern="^(student|advisor)$")
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    role: str = Field(pattern="^(student|advisor)$")
    email: EmailStr
    otp: str = Field(min_length=4, max_length=12)
    new_password: str = Field(min_length=6, max_length=128)


def _now() -> datetime:
    # Use UTC-naive datetimes everywhere to match MongoDB's datetime behavior
    # and avoid naive/aware subtraction errors.
    return datetime.utcnow()


def _hash_otp(*, otp: str, salt: str) -> str:
    return hashlib.sha256(f"{otp}:{salt}".encode("utf-8")).hexdigest()


async def _ensure_profile_exists(role: str, email: str) -> None:
    db = get_database()
    if role == "student":
        exists = await db.students.count_documents({"email": email.lower()}, limit=1)
    else:
        exists = await db.advisors.count_documents(
            {"college_email": email.lower()},
            limit=1,
        )
    if not exists:
        raise HTTPException(status_code=404, detail=f"{role.title()} account not found.")


@router.post("/password-reset/request")
async def request_password_reset(payload: PasswordResetRequest) -> dict:
    role = payload.role
    email = payload.email.lower().strip()
    await _ensure_profile_exists(role, email)

    db = get_database()
    now = _now()
    active = await db.password_reset_otps.find_one(
        {"email": email, "role": role, "expires_at": {"$gt": now}},
        sort=[("created_at", -1)],
    )
    if active:
        created_at = active.get("created_at")
        if isinstance(created_at, datetime):
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
            if (now - created_at).total_seconds() < OTP_RESEND_COOLDOWN_SECONDS:
                raise HTTPException(
                    status_code=429,
                    detail="Please wait a moment before requesting another OTP.",
                )

    otp = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    otp_hash = _hash_otp(otp=otp, salt=salt)
    expires_at = now + timedelta(minutes=OTP_TTL_MINUTES)

    res = await db.password_reset_otps.insert_one(
        {
            "email": email,
            "role": role,
            "otp_hash": otp_hash,
            "salt": salt,
            "attempts": 0,
            "created_at": now,
            "expires_at": expires_at,
        }
    )
    doc_id = res.inserted_id

    try:
        send_password_reset_otp_email(to_email=email, otp_code=otp, role=role)
    except Exception as e:
        # Cleanup OTP on failure so the user can retry immediately without 429 cooldown
        await db.password_reset_otps.delete_one({"_id": doc_id})
        raise HTTPException(
            status_code=502,
            detail="Could not send OTP email. Please try again later.",
        ) from e

    return {"ok": True, "expires_in_seconds": OTP_TTL_MINUTES * 60}


@router.post("/password-reset/confirm")
async def confirm_password_reset(payload: PasswordResetConfirm) -> dict:
    role = payload.role
    email = payload.email.lower().strip()
    await _ensure_profile_exists(role, email)

    db = get_database()
    now = _now()
    doc = await db.password_reset_otps.find_one(
        {"email": email, "role": role, "expires_at": {"$gt": now}},
        sort=[("created_at", -1)],
    )
    if not doc:
        raise HTTPException(status_code=400, detail="OTP expired or not found. Request a new one.")

    attempts = int(doc.get("attempts") or 0)
    if attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Request a new OTP.")

    salt = str(doc.get("salt") or "")
    expected_hash = str(doc.get("otp_hash") or "")
    got_hash = _hash_otp(otp=payload.otp.strip(), salt=salt)
    if got_hash != expected_hash:
        await db.password_reset_otps.update_one(
            {"_id": doc["_id"]},
            {"$set": {"attempts": attempts + 1}},
        )
        raise HTTPException(status_code=400, detail="Invalid OTP.")

    # OTP verified: reset Firebase Auth password.
    try:
        from firebase_admin import auth as fb_auth

        user = await asyncio.to_thread(fb_auth.get_user_by_email, email)
        await asyncio.to_thread(fb_auth.update_user, user.uid, password=payload.new_password)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail="Could not update account password. Please try again.",
        ) from e
    finally:
        # Invalidate OTP whether Firebase succeeds or fails (prevents reuse).
        await db.password_reset_otps.delete_many(
            {"email": email, "role": role},
        )

    return {"ok": True}


# --- Sign-up OTP (Resend) → then Firebase user created with email_verified=True ---


class SignupOtpRequest(BaseModel):
    role: str = Field(pattern="^(student|advisor)$")
    email: EmailStr


class SignupOtpVerify(BaseModel):
    role: str = Field(pattern="^(student|advisor)$")
    email: EmailStr
    otp: str = Field(min_length=4, max_length=12)
    password: str = Field(min_length=6, max_length=128)


async def _firebase_user_exists(email: str) -> bool:
    from firebase_admin import auth as fb_auth

    try:
        await asyncio.to_thread(fb_auth.get_user_by_email, email)
        return True
    except fb_auth.UserNotFoundError:
        return False


async def _mongo_profile_exists(role: str, email: str) -> bool:
    db = get_database()
    if role == "student":
        n = await db.students.count_documents({"email": email.lower()}, limit=1)
    else:
        n = await db.advisors.count_documents({"college_email": email.lower()}, limit=1)
    return n > 0


@router.post("/signup-otp/request")
async def request_signup_otp(payload: SignupOtpRequest) -> dict:
    role = payload.role
    email = payload.email.lower().strip()

    # We only block if BOTH firebase and mongo profile exist. 
    # If firebase exists but mongo doesn't, we allow OTP request to "self-heal" the missing profile.
    if await _firebase_user_exists(email) and await _mongo_profile_exists(role, email):
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Sign in instead.",
        )
    # (Handled by the combined check above)

    db = get_database()
    now = _now()
    active = await db.signup_otps.find_one(
        {"email": email, "role": role, "expires_at": {"$gt": now}},
        sort=[("created_at", -1)],
    )
    if active:
        created_at = active.get("created_at")
        if isinstance(created_at, datetime):
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
            if (now - created_at).total_seconds() < OTP_RESEND_COOLDOWN_SECONDS:
                raise HTTPException(
                    status_code=429,
                    detail="Please wait a moment before requesting another code.",
                )

    otp = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    otp_hash = _hash_otp(otp=otp, salt=salt)
    expires_at = now + timedelta(minutes=OTP_TTL_MINUTES)

    res = await db.signup_otps.insert_one(
        {
            "email": email,
            "role": role,
            "otp_hash": otp_hash,
            "salt": salt,
            "attempts": 0,
            "created_at": now,
            "expires_at": expires_at,
        }
    )
    doc_id = res.inserted_id

    try:
        send_signup_otp_email(to_email=email, otp_code=otp, role=role)
    except Exception as e:
        await db.signup_otps.delete_one({"_id": doc_id})
        raise HTTPException(
            status_code=502,
            detail="Could not send verification email. Please try again later.",
        ) from e

    return {"ok": True, "expires_in_seconds": OTP_TTL_MINUTES * 60}


@router.post("/signup-otp/verify")
async def verify_signup_otp(payload: SignupOtpVerify) -> dict:
    from firebase_admin import auth as fb_auth

    role = payload.role
    email = payload.email.lower().strip()

    if await _mongo_profile_exists(role, email):
        raise HTTPException(
            status_code=409,
            detail="This email is already registered. Sign in instead.",
        )

    db = get_database()
    now = _now()
    doc = await db.signup_otps.find_one(
        {"email": email, "role": role, "expires_at": {"$gt": now}},
        sort=[("created_at", -1)],
    )
    if not doc:
        raise HTTPException(
            status_code=400,
            detail="Code expired or not found. Request a new one.",
        )

    attempts = int(doc.get("attempts") or 0)
    if attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Request a new code.")

    salt = str(doc.get("salt") or "")
    expected_hash = str(doc.get("otp_hash") or "")
    got_hash = _hash_otp(otp=payload.otp.strip(), salt=salt)
    if got_hash != expected_hash:
        await db.signup_otps.update_one(
            {"_id": doc["_id"]},
            {"$set": {"attempts": attempts + 1}},
        )
        raise HTTPException(status_code=400, detail="Invalid code.")

    try:
        await asyncio.to_thread(
            fb_auth.create_user,
            email=email,
            password=payload.password,
            email_verified=True,
        )
    except fb_auth.EmailAlreadyExistsError:
        # User already in Firebase? That's fine if they are missing a MongoDB profile.
        # We delete the OTP so they can proceed.
        await db.signup_otps.delete_many({"email": email, "role": role})
        return {"ok": True}
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail="Could not create your sign-in account. Try again in a moment.",
        ) from e

    await db.signup_otps.delete_many({"email": email, "role": role})
    return {"ok": True}

