from datetime import datetime, timezone
import secrets
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError

from app.database import get_database
from app.deps import firebase_claims
from app.mailer import send_student_final_slot_email_to_advisor
from app.referral_signup import insert_referral_from_signup, resolve_signup_referral_or_raise
from app.s3_service import (
    college_id_keys_valid_for_uid,
    profile_picture_key_valid_for_uid,
    s3_configured,
)
from app.schemas.student import StudentCreate, StudentResponse

router = APIRouter(prefix="/students", tags=["students"])


class StudentProfileUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    state: str | None = None
    academic_status: str | None = None
    jee_mains_percentile: str | None = None
    jee_mains_rank: str | None = None
    jee_advanced_rank: str | None = None
    language_other: str | None = None
    languages: list[str] | None = None


class StudentFinalSlotNotify(BaseModel):
    advisor_id: str
    old_slot: str
    new_slot: str


class StudentReferralCreate(BaseModel):
    referred_email: str
    referred_role: Literal["student", "advisor"]


@router.post("", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    payload: StudentCreate,
    claims: dict = Depends(firebase_claims),
) -> StudentResponse:
    uid = claims["uid"]
    if not claims.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email in Firebase before completing signup.",
        )
    claim_email = (claims.get("email") or "").lower()
    if claim_email != str(payload.email).lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email does not match your Firebase sign-in session.",
        )

    if s3_configured():
        if payload.profile_picture:
            pp = str(payload.profile_picture).strip()
            if pp.startswith("data:"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Profile picture must be uploaded to S3 (use presigned upload), not embedded as base64.",
                )
            if not profile_picture_key_valid_for_uid(uid, "student", pp):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Profile picture key does not match this account or session.",
                )

    db = get_database()
    now = datetime.now(timezone.utc)
    doc = payload.model_dump(by_alias=False)
    doc.pop("referral_code", None)
    referrer_info = await resolve_signup_referral_or_raise(
        db,
        payload.referral_code,
        "student",
        str(payload.email).lower(),
    )
    doc["firebase_uid"] = uid
    doc["email"] = str(payload.email).lower()
    doc["created_at"] = now
    doc["updated_at"] = now
    doc.setdefault("total_sessions", 0)

    try:
        result = await db.students.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A student with this email or account already exists.",
        )
    except OperationFailure as e:
        if e.code == 11000:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A student with this email or account already exists.",
            ) from e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {getattr(e, 'details', None) or str(e)}",
        ) from e
    except PyMongoError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {e!s}",
        ) from e

    if referrer_info:
        try:
            already = await db.referrals.find_one(
                {
                    "referred_email": str(payload.email).lower(),
                    "referred_role": "student",
                }
            )
            if not already:
                await insert_referral_from_signup(
                    db,
                    referrer_info,
                    str(payload.email).lower(),
                    "student",
                )
        except Exception:
            await db.students.delete_one({"_id": result.inserted_id})
            raise

    return StudentResponse(
        id=str(result.inserted_id),
        email=payload.email,
        name=payload.name,
        created_at=now,
    )


@router.get("/me", response_model=StudentResponse)
async def get_my_student(claims: dict = Depends(firebase_claims)) -> StudentResponse:
    uid = claims["uid"]
    db = get_database()
    doc = await db.students.find_one({"firebase_uid": uid})
    if not doc:
        claim_email = (claims.get("email") or "").lower()
        if claim_email:
            doc = await db.students.find_one({"email": claim_email})
            if doc:
                # Backfill UID for older rows created before firebase_uid mapping.
                await db.students.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"firebase_uid": uid}},
                )
                doc["firebase_uid"] = uid
    if not doc:
        raise HTTPException(status_code=404, detail="Student profile not found")

    # Calculate stats dynamically
    confirmed_bookings = await db.bookings.find({
        "student_email": doc["email"],
        "status": {"$in": ["confirmed", "finalized"]}
    }).to_list(length=1000)

    total_sessions = len(confirmed_bookings)
    total_spent = 0.0
    for b in confirmed_bookings:
        try:
            total_spent += float(b.get("session_price") or 0)
        except (ValueError, TypeError):
            continue

    # Update doc with calculated stats
    doc["id"] = str(doc.pop("_id"))
    doc["total_sessions"] = total_sessions
    doc["total_spent"] = total_spent
    
    return StudentResponse(**doc)


@router.patch("/me")
async def update_my_student(
    payload: StudentProfileUpdate,
    claims: dict = Depends(firebase_claims),
) -> dict:
    uid = claims["uid"]
    db = get_database()
    doc = await db.students.find_one({"firebase_uid": uid})
    if not doc:
        claim_email = (claims.get("email") or "").lower()
        if claim_email:
            doc = await db.students.find_one({"email": claim_email})
            if doc:
                await db.students.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"firebase_uid": uid}},
                )
                doc["firebase_uid"] = uid
    if not doc:
        raise HTTPException(status_code=404, detail="Student profile not found")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        doc["id"] = str(doc.pop("_id"))
        doc.pop("password_hash", None)
        return doc

    updates["updated_at"] = datetime.now(timezone.utc)
    await db.students.update_one({"_id": doc["_id"]}, {"$set": updates})
    fresh = await db.students.find_one({"_id": doc["_id"]})
    if not fresh:
        raise HTTPException(status_code=404, detail="Student profile not found")
    fresh["id"] = str(fresh.pop("_id"))
    fresh.pop("password_hash", None)
    return fresh


@router.get("/id/{student_id}")
async def get_student(student_id: str) -> dict:
    if not ObjectId.is_valid(student_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    doc = await get_database().students.find_one({"_id": ObjectId(student_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    return doc


@router.post("/sessions/notify-advisor-final-slot")
async def notify_advisor_final_slot(
    payload: StudentFinalSlotNotify,
    claims: dict = Depends(firebase_claims),
) -> dict:
    uid = claims["uid"]
    student_email = (claims.get("email") or "").lower()
    if not student_email:
        raise HTTPException(status_code=400, detail="Student email not found in token.")
    if not ObjectId.is_valid(payload.advisor_id):
        raise HTTPException(status_code=400, detail="Invalid advisor id.")

    db = get_database()
    student = await db.students.find_one({"firebase_uid": uid})
    if not student:
        student = await db.students.find_one({"email": student_email})
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    advisor = await db.advisors.find_one({"_id": ObjectId(payload.advisor_id)})
    if not advisor:
        raise HTTPException(status_code=404, detail="Advisor not found.")
    advisor_email = str(advisor.get("college_email") or advisor.get("personal_email") or "").strip().lower()
    if not advisor_email:
        raise HTTPException(status_code=400, detail="Advisor email is missing.")

    preferred_slots = advisor.get("preferred_timezones") or advisor.get("preferredTimezones") or []
    allowed = [str(s).strip() for s in preferred_slots if str(s).strip()]
    old_slot = str(payload.old_slot or "").strip()
    new_slot = str(payload.new_slot or "").strip()
    if not old_slot or not new_slot:
        raise HTTPException(status_code=400, detail="Old slot and new slot are required.")
    if new_slot not in allowed:
        raise HTTPException(status_code=400, detail="Final slot must be one of advisor preferred slots.")

    try:
        send_student_final_slot_email_to_advisor(
            advisor_email=advisor_email,
            advisor_name=str(advisor.get("name") or "Advisor"),
            student_name=str(student.get("name") or "Student"),
            student_email=student_email,
            old_slot=old_slot,
            new_slot=new_slot,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not send email via Resend: {e!s}",
        ) from e
    return {"ok": True}


@router.get("/referrals/summary")
async def student_referral_summary(claims: dict = Depends(firebase_claims)) -> dict:
    uid = claims["uid"]
    db = get_database()
    student = await db.students.find_one({"firebase_uid": uid})
    if not student:
        claim_email = (claims.get("email") or "").lower()
        if claim_email:
            student = await db.students.find_one({"email": claim_email})
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found")

    referral_code = str(student.get("referral_code") or "").strip()
    if not referral_code:
        referral_code = f"STU-{secrets.token_hex(4).upper()}"
        await db.students.update_one(
            {"_id": student["_id"]},
            {"$set": {"referral_code": referral_code, "updated_at": datetime.now(timezone.utc)}},
        )
    attended_sessions = int(student.get("total_sessions") or 0)
    total_referrals = await db.referrals.count_documents(
        {"referrer_uid": uid, "referrer_role": "student"}
    )
    rewards = float(student.get("referral_rewards_inr") or 0)
    return {
        "ok": True,
        "referral_code": referral_code,
        "attended_sessions": attended_sessions,
        "can_refer": attended_sessions >= 2,
        "total_referrals": total_referrals,
        "referral_rewards_inr": round(rewards, 2),
        "program_note": "You earn 10% discount on your next advisor session per valid referral.",
    }


@router.post("/referrals/create")
async def student_create_referral(
    payload: StudentReferralCreate, claims: dict = Depends(firebase_claims)
) -> dict:
    uid = claims["uid"]
    referrer_email = (claims.get("email") or "").lower()
    db = get_database()
    student = await db.students.find_one({"firebase_uid": uid})
    if not student:
        if referrer_email:
            student = await db.students.find_one({"email": referrer_email})
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found")
    attended_sessions = int(student.get("total_sessions") or 0)
    if attended_sessions < 2:
        raise HTTPException(
            status_code=403,
            detail="Referral unlocks after attending at least 2 sessions.",
        )
    referred_email = str(payload.referred_email or "").strip().lower()
    if not referred_email:
        raise HTTPException(status_code=400, detail="Referred email is required.")
    if referred_email == referrer_email:
        raise HTTPException(status_code=400, detail="You cannot refer yourself.")
    existing = await db.referrals.find_one(
        {
            "referrer_uid": uid,
            "referrer_role": "student",
            "referred_email": referred_email,
            "referred_role": payload.referred_role,
        }
    )
    if existing:
        raise HTTPException(status_code=409, detail="Referral already recorded for this email.")
    await db.referrals.insert_one(
        {
            "referrer_uid": uid,
            "referrer_role": "student",
            "referrer_email": referrer_email,
            "referred_email": referred_email,
            "referred_role": payload.referred_role,
            "reward_rule": "10% discount on next advisor session",
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
        }
    )
    return {"ok": True}
