from datetime import datetime, timezone, timedelta
import secrets
from typing import Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError

from app.database import get_database
from app.deps import firebase_claims
from app.referral_rewards import apply_referral_rewards_on_session_accept
from app.referral_signup import insert_referral_from_signup, resolve_signup_referral_or_raise
from app.mailer import (
    send_advisor_session_update_email_to_student,
    send_booking_email_to_advisor,
)
from app.s3_service import (
    college_id_keys_valid_for_uid,
    move_temp_college_id_to_user,
    profile_picture_key_valid_for_uid,
    s3_configured,
)
from app.schemas.advisor import AdvisorCreate, AdvisorResponse
from app.temp_uploads import get_temp_upload_record, mark_temp_upload_claimed

router = APIRouter(prefix="/advisors", tags=["advisors"])


def _normalize_advisor_doc(doc: dict) -> dict:
    """Return advisor doc with stable snake_case keys (backward-compatible)."""
    if "detected_college" not in doc and "detectedCollege" in doc:
        doc["detected_college"] = doc.get("detectedCollege")
    if "session_price" not in doc and "sessionPrice" in doc:
        doc["session_price"] = doc.get("sessionPrice")
    if "jee_mains_percentile" not in doc and "jeeMainsPercentile" in doc:
        doc["jee_mains_percentile"] = doc.get("jeeMainsPercentile")
    if "jee_mains_rank" not in doc and "jeeMainsRank" in doc:
        doc["jee_mains_rank"] = doc.get("jeeMainsRank")
    if "jee_advanced_rank" not in doc and "jeeAdvancedRank" in doc:
        doc["jee_advanced_rank"] = doc.get("jeeAdvancedRank")
    if "personal_email" not in doc and "personalEmail" in doc:
        doc["personal_email"] = doc.get("personalEmail")
    if "language_other" not in doc and "languageOther" in doc:
        doc["language_other"] = doc.get("languageOther")
    if "preferred_timezones" not in doc and "preferredTimezones" in doc:
        doc["preferred_timezones"] = doc.get("preferredTimezones")
    return doc


async def _add_advisor_stats(doc: dict, db) -> dict:
    """Add total_sessions, total_earnings, and total_students to the advisor doc."""
    advisor_id = doc.get("id") or str(doc.get("_id", ""))
    if not advisor_id:
        return doc
        
    bookings_cursor = db.bookings.find({"advisor_id": advisor_id})
    bookings = await bookings_cursor.to_list(length=1000)
    
    unique_students = set()
    total_earnings = 0
    for b in bookings:
        sid = b.get("student_id")
        if sid:
            unique_students.add(sid)
        if b.get("status") in ["confirmed", "finalized"]:
            try:
                total_earnings += int(b.get("session_price") or 0)
            except (ValueError, TypeError):
                pass
                
    doc["total_sessions"] = len(bookings)
    doc["total_earnings"] = total_earnings
    doc["total_students"] = len(unique_students)
    return doc


class AdvisorProfileUpdate(BaseModel):
    name: str | None = None
    branch: str | None = None
    phone: str | None = None
    personal_email: str | None = None
    state: str | None = None
    jee_mains_percentile: str | None = None
    jee_mains_rank: str | None = None
    jee_advanced_rank: str | None = None
    bio: str | None = None
    languages: list[str] | None = None
    language_other: str | None = None
    preferred_timezones: list[str] | None = None
    session_price: str | None = None


class AdvisorBookingCreate(BaseModel):
    advisor_id: str
    selected_slot: str


class AdvisorSessionUpdateNotify(BaseModel):
    action: Literal["accept", "reject", "change"]
    student_email: str
    student_name: str
    old_slot: str
    new_slot: str | None = None


class AdvisorReferralCreate(BaseModel):
    referred_email: str


@router.get("/list")
async def list_advisors() -> list[dict]:
    docs = (
        await get_database()
        .advisors.find(
            {
                "is_self_healed": {"$ne": True},
                "name": {"$ne": "New User"},
                "detected_college": {"$ne": "", "$exists": True},
                "branch": {"$ne": "Awaiting Profile Setup", "$exists": True}
            },
            {
                "name": 1,
                "branch": 1,
                "bio": 1,
                "session_price": 1,
                "detected_college": 1,
                "languages": 1,
                "preferred_timezones": 1,
                "preferredTimezones": 1,
            },
        )
        .sort("updated_at", -1)
        .to_list(length=200)
    )
    out: list[dict] = []
    for d in docs:
        d = _normalize_advisor_doc(d)
        langs = d.get("languages")
        if not isinstance(langs, list):
            langs = []
        slots = d.get("preferred_timezones") or d.get("preferredTimezones")
        if not isinstance(slots, list):
            slots = []
        out.append(
            {
                "id": str(d.get("_id")),
                "name": d.get("name") or "",
                "college": d.get("detected_college") or "",
                "branch": d.get("branch") or "",
                "session_price": str(d.get("session_price", "") or ""),
                "bio": d.get("bio") or "",
                "languages": langs,
                "preferred_timezones": [str(x) for x in slots if x is not None],
            }
        )
    return out


@router.post("/book")
async def book_advisor(
    payload: AdvisorBookingCreate,
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
    advisor = _normalize_advisor_doc(advisor)
    advisor_email = str(advisor.get("college_email") or "").strip().lower()
    if not advisor_email:
        advisor_email = str(advisor.get("personal_email") or "").strip().lower()
    if not advisor_email:
        raise HTTPException(status_code=400, detail="Advisor email is missing.")
    selected_slot = str(payload.selected_slot or "").strip()
    if not selected_slot:
        raise HTTPException(status_code=400, detail="Select one preferred time slot.")
    preferred_slots = advisor.get("preferred_timezones") or advisor.get("preferredTimezones") or []
    if not isinstance(preferred_slots, list):
        preferred_slots = []
    normalized_slots = [str(s).strip() for s in preferred_slots if str(s).strip()]
    if selected_slot not in normalized_slots:
        raise HTTPException(
            status_code=400,
            detail="Selected slot must be one of advisor preferred time slots.",
        )

    try:
        send_booking_email_to_advisor(
            advisor_email=advisor_email,
            advisor_name=str(advisor.get("name") or "Advisor"),
            student_name=str(student.get("name") or "Student"),
            student_email=student_email,
            selected_slot=selected_slot,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Booking email could not be sent via Resend: {e!s}",
        ) from e

    # Persist the booking in the database
    now = datetime.now(timezone.utc)
    # Assume 1 hour session for now, adjust if there's a specific duration
    # We need to parse selected_slot or just store it. 
    # For now, we'll store the text slot and a placeholder scheduled_time if we can't parse it easily.
    # In a real app, selected_slot should be a timestamp.
    booking_doc = {
        "advisor_id": str(advisor["_id"]),
        "student_id": str(student["_id"]),
        "advisor_name": str(advisor.get("name") or "Advisor"),
        "student_name": str(student.get("name") or "Student"),
        "student_email": student_email,
        "selected_slot": selected_slot,
        "session_price": str(advisor.get("session_price", "")),
        "status": "pending",
        "scheduled_time": now + timedelta(days=1), # Placeholder: use actual slot parsing if possible
        "end_time": now + timedelta(days=1, hours=1),
        "student_joined": False,
        "advisor_joined": False,
        "created_at": now,
        "updated_at": now
    }
    result = await db.bookings.insert_one(booking_doc)

    return {
        "ok": True,
        "booking_id": str(result.inserted_id),
        "advisor_email": advisor_email,
        "selected_slot": selected_slot,
        "email_sent": True,
        "email_error": "",
    }



@router.post("/sessions/notify-student")
async def notify_student_about_session_update(
    payload: AdvisorSessionUpdateNotify,
    claims: dict = Depends(firebase_claims),
) -> dict:
    uid = claims["uid"]
    db = get_database()
    advisor = await db.advisors.find_one({"firebase_uid": uid})
    if not advisor:
        raise HTTPException(status_code=404, detail="Advisor profile not found.")
    advisor = _normalize_advisor_doc(advisor)
    advisor_name = str(advisor.get("name") or "Advisor")

    old_slot = str(payload.old_slot or "").strip()
    if payload.action in ("reject", "change") and not old_slot:
        raise HTTPException(status_code=400, detail="Old slot is required.")
    preferred_slots = advisor.get("preferred_timezones") or advisor.get("preferredTimezones") or []
    normalized_slots = [str(s).strip() for s in preferred_slots if str(s).strip()]
    if payload.action == "change":
        new_slot = str(payload.new_slot or "").strip()
        if not new_slot:
            raise HTTPException(status_code=400, detail="New slot is required for change.")
        if new_slot not in normalized_slots:
            raise HTTPException(
                status_code=400,
                detail="New slot must be one of your preferred time slots.",
            )
    else:
        new_slot = None

    if payload.action == "accept":
        student_email = str(payload.student_email).strip().lower()
        await db.advisors.update_one(
            {"_id": advisor["_id"]},
            {"$inc": {"total_sessions": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        await db.students.update_one(
            {"email": student_email},
            {"$inc": {"total_sessions": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        await apply_referral_rewards_on_session_accept(db, advisor, student_email)
        return {"ok": True}

    try:
        send_advisor_session_update_email_to_student(
            student_email=str(payload.student_email).strip().lower(),
            student_name=str(payload.student_name).strip() or "Student",
            advisor_name=advisor_name,
            action=payload.action,
            old_slot=old_slot,
            new_slot=new_slot,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not send email via Resend: {e!s}",
        ) from e

    return {"ok": True}


@router.post("", response_model=AdvisorResponse, status_code=status.HTTP_201_CREATED)
async def create_advisor(
    payload: AdvisorCreate,
    claims: dict = Depends(firebase_claims),
) -> AdvisorResponse:
    uid = claims["uid"]
    if not claims.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email in Firebase before completing signup.",
        )
    claim_email = (claims.get("email") or "").lower()
    if claim_email != str(payload.college_email).lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="College email does not match your Firebase sign-in session.",
        )

    db = get_database()
    front_key = payload.college_id_front_key
    back_key = payload.college_id_back_key

    if s3_configured():
        has_direct_keys = bool(front_key and back_key)
        if has_direct_keys and not college_id_keys_valid_for_uid(
            uid,
            "advisor",
            front_key,
            back_key,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="College ID upload keys do not match this account or session.",
            )

        if (not has_direct_keys) and payload.id_upload_token:
            temp = await get_temp_upload_record(
                db,
                role="advisor",
                raw_token=str(payload.id_upload_token),
            )
            if not temp:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Temporary ID upload token is invalid or expired. Re-upload your ID card.",
                )
            try:
                front_key = move_temp_college_id_to_user(
                    uid,
                    "advisor",
                    "front",
                    str(temp.get("front_key") or ""),
                )
                back_key = move_temp_college_id_to_user(
                    uid,
                    "advisor",
                    "back",
                    str(temp.get("back_key") or ""),
                )
            except (ValueError, RuntimeError) as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Could not finalize temporary ID uploads: {e!s}",
                ) from e
            claimed = await mark_temp_upload_claimed(
                db,
                role="advisor",
                raw_token=str(payload.id_upload_token),
                claimed_by_uid=uid,
            )
            if not claimed:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Temporary ID upload token was already used. Please re-upload your ID card.",
                )

        # We allow minimal signup without ID keys. They will be required before the advisor can be 'verified'.
        # if not front_key or not back_key:
        #     raise HTTPException(
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #         detail="College ID front and back uploads are required (S3 object keys missing).",
        #     )

        if payload.profile_picture:
            pp = str(payload.profile_picture).strip()
            if pp.startswith("data:"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Profile picture must be uploaded to S3 (use presigned upload), not embedded as base64.",
                )
            if not profile_picture_key_valid_for_uid(uid, "advisor", pp):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Profile picture key does not match this account or session.",
                )

    now = datetime.now(timezone.utc)
    doc = payload.model_dump(by_alias=False)
    doc["college_id_front_key"] = str(front_key)
    doc["college_id_back_key"] = str(back_key)
    doc.pop("id_upload_token", None)
    doc.pop("referral_code", None)
    referrer_info = await resolve_signup_referral_or_raise(
        db,
        payload.referral_code,
        "advisor",
        str(payload.college_email).lower(),
    )
    doc["firebase_uid"] = uid
    doc["college_email"] = str(payload.college_email).lower()
    pe = doc.get("personal_email")
    if pe:
        doc["personal_email"] = str(pe).lower()
    else:
        doc.pop("personal_email", None)
    doc["created_at"] = now
    doc["updated_at"] = now
    doc.setdefault("total_sessions", 0)

    try:
        result = await db.advisors.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An advisor with this college email or account already exists.",
        )
    except OperationFailure as e:
        if e.code == 11000:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An advisor with this college email or account already exists.",
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
                    "referred_email": str(payload.college_email).lower(),
                    "referred_role": "advisor",
                }
            )
            if not already:
                await insert_referral_from_signup(
                    db,
                    referrer_info,
                    str(payload.college_email).lower(),
                    "advisor",
                )
        except Exception:
            await db.advisors.delete_one({"_id": result.inserted_id})
            raise

    return AdvisorResponse(
        id=str(result.inserted_id),
        college_email=payload.college_email,
        name=payload.name,
        created_at=now,
    )


@router.get("/me")
async def get_my_advisor(claims: dict = Depends(firebase_claims)) -> dict:
    uid = claims["uid"]
    db = get_database()
    doc = await db.advisors.find_one({"firebase_uid": uid})
    if not doc:
        # Check if they are already a student
        student_doc = await db.students.find_one({"firebase_uid": uid})
        if student_doc:
            raise HTTPException(
                status_code=403, 
                detail="This account is registered as a Student. Please use the Student Portal."
            )

        # SELF-HEALING: Create skeleton if missing
        email = (claims.get("email") or "").lower()
        if not email:
            raise HTTPException(status_code=404, detail="Advisor profile not found")
        
        # Check if they look like an advisor by email
        import re
        is_advisor_email = bool(re.match(r".*@.*(\.ac\.in|\.edu\.in|\.edu)$", email, re.IGNORECASE))
        if not is_advisor_email:
             # If they hit /advisors/me but aren't an advisor by email, still create skeleton here
             # as they explicitly tried to access advisor dashboard.
             pass

        now = datetime.now(timezone.utc)
        new_doc = {
            "firebase_uid": uid,
            "college_email": email,
            "name": claims.get("name") or email.split("@")[0],
            "phone": "",
            "state": "",
            "branch": "Awaiting Profile Setup",
            "bio": "Recovered profile. Please update your details.",
            "session_price": "199",
            "current_study_year": 1,
            "preferred_timezones": [],
            "total_earnings": 0,
            "total_sessions": 0,
            "total_students": 0,
            "created_at": now,
            "updated_at": now,
            "is_self_healed": True
        }
        res = await db.advisors.insert_one(new_doc)
        new_doc["_id"] = res.inserted_id
        doc = new_doc
    
    doc = _normalize_advisor_doc(doc)
    doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    return await _add_advisor_stats(doc, db)


@router.patch("/me")
async def update_my_advisor(
    payload: AdvisorProfileUpdate,
    claims: dict = Depends(firebase_claims),
) -> dict:
    uid = claims["uid"]
    db = get_database()
    doc = await db.advisors.find_one({"firebase_uid": uid})
    if not doc:
        claim_email = (claims.get("email") or "").lower()
        if claim_email:
            doc = await db.advisors.find_one({"college_email": claim_email})
            if doc:
                await db.advisors.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"firebase_uid": uid}},
                )
                doc["firebase_uid"] = uid
    if not doc:
        raise HTTPException(status_code=404, detail="Advisor profile not found")

    updates = payload.model_dump(exclude_unset=True)
    # Keep compatibility with older camelCase Mongo documents.
    if "session_price" in updates:
        updates["sessionPrice"] = updates["session_price"]
    if "jee_mains_percentile" in updates:
        updates["jeeMainsPercentile"] = updates["jee_mains_percentile"]
    if "jee_mains_rank" in updates:
        updates["jeeMainsRank"] = updates["jee_mains_rank"]
    if "jee_advanced_rank" in updates:
        updates["jeeAdvancedRank"] = updates["jee_advanced_rank"]
    if "personal_email" in updates:
        updates["personalEmail"] = updates["personal_email"]
    if "language_other" in updates:
        updates["languageOther"] = updates["language_other"]
    if "preferred_timezones" in updates:
        updates["preferredTimezones"] = updates["preferred_timezones"]
    if "personal_email" in updates and updates["personal_email"]:
        updates["personal_email"] = str(updates["personal_email"]).lower()
    if not updates:
        doc["id"] = str(doc.pop("_id"))
        doc.pop("password_hash", None)
        return doc

    updates["updated_at"] = datetime.now(timezone.utc)
    if doc.get("is_self_healed"):
        updates["is_self_healed"] = False
    await db.advisors.update_one({"_id": doc["_id"]}, {"$set": updates})
    fresh = await db.advisors.find_one({"_id": doc["_id"]})
    if not fresh:
        raise HTTPException(status_code=404, detail="Advisor profile not found")
    fresh = _normalize_advisor_doc(fresh)
    fresh["id"] = str(fresh.pop("_id"))
    fresh.pop("password_hash", None)
    return await _add_advisor_stats(fresh, db)


@router.get("/id/{advisor_id}")
async def get_advisor(advisor_id: str) -> dict:
    if not ObjectId.is_valid(advisor_id):
        raise HTTPException(status_code=400, detail="Invalid id")
    doc = await get_database().advisors.find_one({"_id": ObjectId(advisor_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    doc = _normalize_advisor_doc(doc)
    doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    return doc


@router.get("/referrals/summary")
async def advisor_referral_summary(claims: dict = Depends(firebase_claims)) -> dict:
    uid = claims["uid"]
    db = get_database()
    advisor = await db.advisors.find_one({"firebase_uid": uid})
    if not advisor:
        raise HTTPException(status_code=404, detail="Advisor profile not found")

    referral_code = str(advisor.get("referral_code") or "").strip()
    if not referral_code:
        referral_code = f"ADV-{secrets.token_hex(4).upper()}"
        await db.advisors.update_one(
            {"_id": advisor["_id"]},
            {"$set": {"referral_code": referral_code, "updated_at": datetime.now(timezone.utc)}},
        )
    attended_sessions = int(advisor.get("total_sessions") or 0)
    total_referrals = await db.referrals.count_documents(
        {"referrer_uid": uid, "referrer_role": "advisor"}
    )
    earnings = float(advisor.get("referral_earnings_inr") or 0)
    return {
        "ok": True,
        "referral_code": referral_code,
        "attended_sessions": attended_sessions,
        "can_refer": attended_sessions >= 2,
        "total_referrals": total_referrals,
        "referral_earnings_inr": round(earnings, 2),
        "program_note": "You earn 3% from the referred advisor's next 5 sessions.",
    }


@router.post("/referrals/create")
async def advisor_create_referral(
    payload: AdvisorReferralCreate, claims: dict = Depends(firebase_claims)
) -> dict:
    uid = claims["uid"]
    referrer_email = (claims.get("email") or "").lower()
    db = get_database()
    advisor = await db.advisors.find_one({"firebase_uid": uid})
    if not advisor:
        raise HTTPException(status_code=404, detail="Advisor profile not found")
    attended_sessions = int(advisor.get("total_sessions") or 0)
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
            "referrer_role": "advisor",
            "referred_email": referred_email,
            "referred_role": "advisor",
        }
    )
    if existing:
        raise HTTPException(status_code=409, detail="Referral already recorded for this email.")
    await db.referrals.insert_one(
        {
            "referrer_uid": uid,
            "referrer_role": "advisor",
            "referrer_email": referrer_email,
            "referred_email": referred_email,
            "referred_role": "advisor",
            "reward_rule": "3% of referred advisor next 5 sessions",
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
        }
    )
    return {"ok": True}
