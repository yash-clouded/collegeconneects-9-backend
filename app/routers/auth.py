from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.database import get_database
from app.jwt_service import create_access_token
from app.mailer import send_password_reset_otp_email, send_signup_otp_email
from app.security import hash_password, verify_password

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


class LoginRequest(BaseModel):
    role: str = Field(pattern="^(student|advisor)$")
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


def _now() -> datetime:
    # Always use timezone-aware UTC timestamps for OTP expiry comparisons.
    return datetime.now(timezone.utc)


def _hash_otp(*, otp: str, salt: str) -> str:
    return hashlib.sha256(f"{otp}:{salt}".encode("utf-8")).hexdigest()


def _build_jwt_claims(*, uid: str, email: str, role: str, name: str | None = None) -> dict:
    return {
        "uid": uid,
        "email": email.lower().strip(),
        "email_verified": True,
        "name": name or email.split("@")[0],
        "role": role,
        "auth_provider": "jwt",
    }


async def _issue_login_token(*, role: str, email: str) -> dict:
    db = get_database()
    normalized_email = email.lower().strip()
    account = await db.auth_accounts.find_one({"role": role, "email": normalized_email})
    if not account:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    claims = _build_jwt_claims(
        uid=str(account.get("uid") or ""),
        email=normalized_email,
        role=role,
        name=str(account.get("name") or normalized_email.split("@")[0]),
    )
    token, expires_in = create_access_token(claims=claims)
    return {
        "ok": True,
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": {
            "uid": claims["uid"],
            "email": claims["email"],
            "role": role,
            "name": claims["name"],
        },
    }


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
    await _ensure_firebase_user_exists_for_password_reset(email)

    db = get_database()
    now = _now()
    active = await db.password_reset_otps.find_one(
        {"email": email, "role": role, "expires_at": {"$gt": now}},
        sort=[("created_at", -1)],
    )
    if active:
        created_at = active.get("created_at")
        if isinstance(created_at, datetime):
            # Backward compatible: if older OTP docs stored naive datetimes,
            # assume they were UTC.
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
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
    await _ensure_firebase_user_exists_for_password_reset(email)

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

    # OTP verified: update password hash in Mongo for both auth + profile collections.
    new_hash = hash_password(payload.new_password)
    now_dt = _now()
    profile_query = {"email": email} if role == "student" else {"college_email": email}
    profile_collection = db.students if role == "student" else db.advisors
    profile_doc = await profile_collection.find_one(profile_query)
    if not profile_doc:
        raise HTTPException(status_code=404, detail="Account profile not found.")

    # Backward-compatible migration: create auth_accounts row if legacy user doesn't have one yet.
    auth_doc = await db.auth_accounts.find_one({"role": role, "email": email})
    if not auth_doc:
        uid = str(profile_doc.get("firebase_uid") or "") or uuid.uuid4().hex
        await db.auth_accounts.insert_one(
            {
                "uid": uid,
                "role": role,
                "email": email,
                "name": str(profile_doc.get("name") or email.split("@")[0]),
                "password_hash": new_hash,
                "created_at": now_dt,
                "updated_at": now_dt,
            }
        )
    else:
        await db.auth_accounts.update_one(
            {"_id": auth_doc["_id"]},
            {"$set": {"password_hash": new_hash, "updated_at": now_dt}},
        )

    upd = await profile_collection.update_one(
        {"_id": profile_doc["_id"]},
        {"$set": {"password_hash": new_hash, "updated_at": now_dt}},
    )
    if upd.matched_count == 0:
        raise HTTPException(status_code=500, detail="Password updated, but profile sync failed.")

    # Invalidate OTP only after a successful password change.
    await db.password_reset_otps.delete_many(
        {"email": email, "role": role},
    )

    return {"ok": True}


@router.post("/login")
async def login_with_password(payload: LoginRequest) -> dict:
    role = payload.role
    email = payload.email.lower().strip()
    db = get_database()
    account = await db.auth_accounts.find_one({"role": role, "email": email})
    if account:
        if not verify_password(payload.password, str(account.get("password_hash") or "")):
            raise HTTPException(status_code=401, detail="Invalid credentials.")
    else:
        # Backward-compatible fallback: allow login from profile password_hash and
        # auto-create auth_accounts entry for JWT-native auth.
        profile_collection = db.students if role == "student" else db.advisors
        profile_query = {"email": email} if role == "student" else {"college_email": email}
        profile = await profile_collection.find_one(profile_query)
        if not profile:
            raise HTTPException(status_code=401, detail="Invalid credentials.")
        password_hash = str(profile.get("password_hash") or "")
        if not password_hash or not verify_password(payload.password, password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials.")
        uid = str(profile.get("firebase_uid") or "") or uuid.uuid4().hex
        now_dt = _now()
        await db.auth_accounts.insert_one(
            {
                "uid": uid,
                "role": role,
                "email": email,
                "name": str(profile.get("name") or email.split("@")[0]),
                "password_hash": password_hash,
                "created_at": now_dt,
                "updated_at": now_dt,
            }
        )
    return await _issue_login_token(role=role, email=email)


# --- Sign-up OTP (Resend) → then Firebase user created with email_verified=True ---


class SignupOtpRequest(BaseModel):
    role: str = Field(pattern="^(student|advisor)$")
    email: EmailStr


class SignupOtpVerify(BaseModel):
    role: str = Field(pattern="^(student|advisor)$")
    email: EmailStr
    otp: str = Field(min_length=4, max_length=12)
    password: str = Field(min_length=6, max_length=128)


class TokenExchangeRequest(BaseModel):
    firebase_id_token: str | None = None


@router.post("/token/exchange")
async def exchange_firebase_for_jwt(
    payload: TokenExchangeRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    raise HTTPException(status_code=410, detail="Firebase token exchange removed. Use /api/auth/login.")


async def _mongo_profile_exists(role: str | None, email: str, allow_recovered: bool = False) -> bool:
    db = get_database()
    email = email.lower()
    
    if role == "student":
        doc = await db.students.find_one({"email": email})
    elif role == "advisor":
        doc = await db.advisors.find_one({"college_email": email})
    else:
        # Check both
        student_doc = await db.students.find_one({"email": email})
        advisor_doc = await db.advisors.find_one({"college_email": email})
        doc = student_doc or advisor_doc
    
    if not doc:
        return False
        
    if allow_recovered:
        # If it's a sync-recovered or self-healed profile, we don't count it as a "conflict" blocking signup
        if doc.get("is_sync_recovered") or doc.get("is_self_healed"):
            return False
            
    return True


@router.post("/signup-otp/request")
async def request_signup_otp(payload: SignupOtpRequest) -> dict:
    role = payload.role
    email = payload.email.lower().strip()

    # We block if the user already exists in EITHER collection in MongoDB, 
    # regardless of which role they are trying to sign up for now.
    if await _mongo_profile_exists(None, email, allow_recovered=False):
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists on our platform. Please sign in.",
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
            # Backward compatible: if older OTP docs stored naive datetimes,
            # assume they were UTC.
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
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
    role = payload.role
    email = payload.email.lower().strip()

    if await _mongo_profile_exists(role, email, allow_recovered=True):
        # We only block if it's a REAL (non-skeleton) profile.
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
        # Check if it was ever generated to see if it just expired
        expired_doc = await db.signup_otps.find_one(
            {"email": email, "role": role},
            sort=[("created_at", -1)],
        )
        if expired_doc:
            raise HTTPException(
                status_code=400,
                detail="Verification code expired. Please request a new one.",
            )
        raise HTTPException(
            status_code=400,
            detail="Verification code not found. Please request a new one.",
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

    existing = await db.auth_accounts.find_one({"role": role, "email": email})
    now_dt = _now()
    password_hash = hash_password(payload.password)
    if existing:
        await db.auth_accounts.update_one(
            {"_id": existing["_id"]},
            {"$set": {"password_hash": password_hash, "updated_at": now_dt}},
        )
        uid = str(existing.get("uid") or "")
    else:
        uid = uuid.uuid4().hex
        await db.auth_accounts.insert_one(
            {
                "uid": uid,
                "role": role,
                "email": email,
                "name": email.split("@")[0],
                "password_hash": password_hash,
                "created_at": now_dt,
                "updated_at": now_dt,
            }
        )

    await db.signup_otps.delete_many({"email": email, "role": role})
    claims = _build_jwt_claims(uid=uid, email=email, role=role)
    token, expires_in = create_access_token(claims=claims)
    return {
        "ok": True,
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": {
            "uid": claims["uid"],
            "email": claims["email"],
            "role": role,
            "name": claims["name"],
        },
    }

