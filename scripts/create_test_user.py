import asyncio
from datetime import datetime, timezone
from firebase_admin import auth as fb_auth
from app.database import connect_db, get_database
from app.firebase_service import init_firebase_admin

async def create_test_user():
    # Credentials from USER
    u = "aura1322"
    p = "aura1322"
    email = f"{u}@collegeconnects.co.in"

    print(f"Creating user {u} in Firebase...")
    
    # 1. Initialize Firebase
    init_firebase_admin()
    
    # 2. Create in Firebase
    try:
        user = fb_auth.get_user_by_email(email)
        print(f"User {u} already exists in Firebase with UID: {user.uid}")
        uid = user.uid
    except Exception:
        user = fb_auth.create_user(
            email=email,
            password=p,
            display_name=u,
            email_verified=True
        )
        print(f"User {u} created in Firebase with UID: {user.uid}")
        uid = user.uid

    # 3. Connect to DB
    await connect_db()
    db = get_database()
    
    # 4. Check if already in MongoDB
    existing = await db.students.find_one({"email": email})
    if existing:
        print(f"User {u} already exists in MongoDB.")
        # Update firebase_uid just in case
        await db.students.update_one({"_id": existing["_id"]}, {"$set": {"firebase_uid": uid}})
    else:
        # 5. Insert into MongoDB
        now = datetime.now(timezone.utc)
        test_student = {
            "name": u,
            "email": email,
            "phone": "9999999999",
            "gender": "Other",
            "state": "Test",
            "upi_id": "test@upi",
            "academic_status": "Testing",
            "jee_mains_percentile": "99.9",
            "jee_mains_rank": "1",
            "jee_advanced_rank": "1",
            "languages": ["English"],
            "firebase_uid": uid,
            "created_at": now,
            "updated_at": now,
            "total_sessions": 0
        }
        await db.students.insert_one(test_student)
        print(f"User {u} added to MongoDB.")

    print("\nSUCCESS! You can now log in with:")
    print(f"Email: {email}")
    print(f"Password: {p}")

if __name__ == "__main__":
    asyncio.run(create_test_user())
