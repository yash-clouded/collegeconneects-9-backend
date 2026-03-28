"""Credit referral rewards when a session is accepted (advisor accepts student booking)."""

from __future__ import annotations

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase


def _session_price_inr(advisor_doc: dict) -> float:
    try:
        return max(0.0, float(str(advisor_doc.get("session_price") or "0").strip() or 0))
    except (TypeError, ValueError):
        return 0.0


def _advisor_email(advisor_doc: dict) -> str:
    e = str(advisor_doc.get("college_email") or "").strip().lower()
    if e:
        return e
    return str(advisor_doc.get("personal_email") or "").strip().lower()


async def apply_referral_rewards_on_session_accept(
    db: AsyncIOMotorDatabase,
    advisor_doc: dict,
    student_email: str,
) -> None:
    """
    When an advisor accepts a session, attribute rewards to referrers:
    - Advisor → advisor: 3% of this session price, up to 5 sessions per referral row.
    - Student → student: 10% of session price once (first accepted session for referred student).
    - Student → advisor: 3% of this session price, up to 5 sessions per referral row.
    """
    now = datetime.now(timezone.utc)
    student_email = (student_email or "").strip().lower()
    advisor_email = _advisor_email(advisor_doc)
    price = _session_price_inr(advisor_doc)
    if price <= 0 or not advisor_email:
        return

    # A) This advisor was referred by another advisor — 3% × 5
    ref_aa = await db.referrals.find_one(
        {
            "referred_email": advisor_email,
            "referred_role": "advisor",
            "referrer_role": "advisor",
        }
    )
    if ref_aa and int(ref_aa.get("sessions_rewarded") or 0) < 5:
        cut = round(price * 0.03, 2)
        if cut > 0:
            await db.referrals.update_one(
                {"_id": ref_aa["_id"]},
                {
                    "$inc": {"sessions_rewarded": 1, "total_reward_inr": cut},
                    "$set": {"updated_at": now},
                },
            )
            await db.advisors.update_one(
                {"firebase_uid": ref_aa["referrer_uid"]},
                {"$inc": {"referral_earnings_inr": cut}},
            )

    # B) This student was referred by another student — 10% once
    if student_email:
        ref_ss = await db.referrals.find_one(
            {
                "referred_email": student_email,
                "referred_role": "student",
                "referrer_role": "student",
            }
        )
        if ref_ss and not ref_ss.get("discount_credited"):
            cut = round(price * 0.10, 2)
            if cut > 0:
                await db.referrals.update_one(
                    {"_id": ref_ss["_id"]},
                    {
                        "$set": {"discount_credited": True, "updated_at": now},
                        "$inc": {"total_reward_inr": cut},
                    },
                )
                await db.students.update_one(
                    {"firebase_uid": ref_ss["referrer_uid"]},
                    {"$inc": {"referral_rewards_inr": cut}},
                )

    # C) This advisor was referred by a student — 3% × 5 (credited as rewards on student)
    ref_sa = await db.referrals.find_one(
        {
            "referred_email": advisor_email,
            "referred_role": "advisor",
            "referrer_role": "student",
        }
    )
    if ref_sa and int(ref_sa.get("sessions_rewarded") or 0) < 5:
        cut = round(price * 0.03, 2)
        if cut > 0:
            await db.referrals.update_one(
                {"_id": ref_sa["_id"]},
                {
                    "$inc": {"sessions_rewarded": 1, "total_reward_inr": cut},
                    "$set": {"updated_at": now},
                },
            )
            await db.students.update_one(
                {"firebase_uid": ref_sa["referrer_uid"]},
                {"$inc": {"referral_rewards_inr": cut}},
            )
