"""Validate referral codes during student/advisor signup and create referral rows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase


async def resolve_signup_referral_or_raise(
    db: AsyncIOMotorDatabase,
    code: str | None,
    signup_as: Literal["advisor", "student"],
    new_user_email: str,
) -> dict[str, str] | None:
    """
    If `code` is empty, returns None.
    Otherwise validates code type (ADV vs STU flow), referrer eligibility (>=2 sessions),
    and self-referral. Returns dict with uid, role, email for insert.
    """
    if not code or not str(code).strip():
        return None
    code_n = str(code).strip().upper()
    new_user_email = new_user_email.strip().lower()
    if not new_user_email:
        raise HTTPException(status_code=400, detail="Email is required to use a referral code.")

    if signup_as == "advisor":
        ref = await db.advisors.find_one({"referral_code": code_n})
        if not ref:
            alt = await db.students.find_one({"referral_code": code_n})
            if alt:
                raise HTTPException(
                    status_code=400,
                    detail="That code is for student referrals. Use an advisor code (e.g. ADV-…).",
                )
            raise HTTPException(status_code=400, detail="Invalid referral code.")
        if int(ref.get("total_sessions") or 0) < 2:
            raise HTTPException(
                status_code=400,
                detail="That referral code is not active yet. The referrer must complete at least 2 sessions.",
            )
        r_email = str(ref.get("college_email") or ref.get("personal_email") or "").strip().lower()
        if r_email == new_user_email:
            raise HTTPException(status_code=400, detail="You cannot use your own referral code.")
        return {"uid": ref["firebase_uid"], "role": "advisor", "email": r_email}

    ref = await db.students.find_one({"referral_code": code_n})
    if not ref:
        alt = await db.advisors.find_one({"referral_code": code_n})
        if alt:
            raise HTTPException(
                status_code=400,
                detail="That code is for advisor referrals. Use a student code (e.g. STU-…).",
            )
        raise HTTPException(status_code=400, detail="Invalid referral code.")
    if int(ref.get("total_sessions") or 0) < 2:
        raise HTTPException(
            status_code=400,
            detail="That referral code is not active yet. The referrer must complete at least 2 sessions.",
        )
    r_email = str(ref.get("email") or "").strip().lower()
    if r_email == new_user_email:
        raise HTTPException(status_code=400, detail="You cannot use your own referral code.")
    return {"uid": ref["firebase_uid"], "role": "student", "email": r_email}


async def insert_referral_from_signup(
    db: AsyncIOMotorDatabase,
    referrer: dict[str, str],
    referred_email: str,
    referred_role: Literal["advisor", "student"],
) -> None:
    reward_rule = (
        "3% of referred advisor next 5 sessions"
        if referred_role == "advisor"
        else "10% discount on next advisor session"
    )
    now = datetime.now(timezone.utc)
    await db.referrals.insert_one(
        {
            "referrer_uid": referrer["uid"],
            "referrer_role": referrer["role"],
            "referrer_email": referrer["email"],
            "referred_email": referred_email.strip().lower(),
            "referred_role": referred_role,
            "reward_rule": reward_rule,
            "status": "pending",
            "source": "signup",
            "created_at": now,
        }
    )
