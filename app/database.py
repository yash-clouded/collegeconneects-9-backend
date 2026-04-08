from __future__ import annotations
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_database() -> AsyncIOMotorDatabase:
    return get_client()[settings.database_name]


async def connect_db() -> None:
    client = get_client()
    await client.admin.command("ping")
    db = get_database()
    # Unique email per role; Firebase-backed profiles also have firebase_uid
    await db.students.create_index("email", unique=True)
    await db.advisors.create_index("college_email", unique=True)
    await db.students.create_index("firebase_uid", unique=True, sparse=True)
    await db.advisors.create_index("firebase_uid", unique=True, sparse=True)
    # Password reset OTPs (Resend) — auto-expire docs after `expires_at`.
    await db.password_reset_otps.create_index("email")
    await db.password_reset_otps.create_index("role")
    await db.password_reset_otps.create_index("expires_at", expireAfterSeconds=0)
    # Sign-up OTPs (Resend) — same TTL pattern as password reset
    await db.signup_otps.create_index("email")
    await db.signup_otps.create_index("role")
    await db.signup_otps.create_index("expires_at", expireAfterSeconds=0)
    # Temporary unauthenticated signup ID uploads (short-lived + one-time token)
    await db.signup_temp_uploads.create_index("token_hash", unique=True)
    await db.signup_temp_uploads.create_index("role")
    await db.signup_temp_uploads.create_index("expires_at", expireAfterSeconds=0)
    
    # Bookings indexes for performance
    await db.bookings.create_index("status")
    await db.bookings.create_index("razorpay_order_id")
    await db.bookings.create_index("created_at")


async def close_db() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
