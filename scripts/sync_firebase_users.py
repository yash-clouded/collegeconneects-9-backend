import asyncio
import os
import sys
import re
from datetime import datetime, timezone
from firebase_admin import auth as fb_auth, initialize_app, credentials, get_app
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Add parent to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load env from .env
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path)

MONGODB_URI = os.getenv("MONGODB_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME", "collegeconnect")
FIREBASE_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")

# Regex to detect college emails
COLLEGE_EMAIL_PATTERN = re.compile(r".*@.*(\.ac\.in|\.edu\.in|\.edu)$", re.IGNORECASE)

async def sync_users():
    # Initialize Firebase
    try:
        get_app()
    except ValueError:
        if not FIREBASE_JSON:
             print("Error: FIREBASE_SERVICE_ACCOUNT_PATH not found in .env")
             return
        fb_path = FIREBASE_JSON
        if not os.path.isabs(fb_path):
            fb_path = os.path.join(os.path.dirname(dotenv_path), fb_path)
        cred = credentials.Certificate(fb_path)
        initialize_app(cred)
    
    # Initialize Mongo
    if not MONGODB_URI:
        print("Error: MONGODB_URI not found in .env")
        return
        
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    
    print(f"Syncing Firebase users with MongoDB database: {DATABASE_NAME}")
    
    fb_users = []
    page = fb_auth.list_users()
    while page:
        fb_users.extend(page.users)
        page = page.get_next_page()
    
    print(f"Processing {len(fb_users)} users...")
    
    synced_count = 0
    already_exists_count = 0
    
    for u in fb_users:
        email = u.email.lower()
        uid = u.uid
        display_name = u.display_name or "New User"
        
        # Check if exists in either collection
        in_students = await db.students.find_one({"email": email})
        in_advisors = await db.advisors.find_one({"college_email": email})
        
        if in_students or in_advisors:
            already_exists_count += 1
            continue
            
        # Determine role
        is_advisor = bool(COLLEGE_EMAIL_PATTERN.match(email))
        role = "advisor" if is_advisor else "student"
        
        now = datetime.now(timezone.utc)
        
        if role == "student":
            doc = {
                "firebase_uid": uid,
                "email": email,
                "name": display_name,
                "phone": "",
                "state": "",
                "academic_status": "Awaiting Profile Setup",
                "jee_mains_percentile": "",
                "jee_mains_rank": "",
                "jee_advanced_rank": "",
                "created_at": now,
                "updated_at": now,
                "total_sessions": 0,
                "is_sync_recovered": True
            }
            await db.students.insert_one(doc)
        else:
            doc = {
                "firebase_uid": uid,
                "college_email": email,
                "name": display_name,
                "phone": "",
                "state": "",
                "branch": "Awaiting Profile Setup",
                "bio": "Recovered profile. Please update your details.",
                "session_price": "199", # Default
                "current_study_year": 1,
                "preferred_timezones": [],
                "total_earnings": 0,
                "total_sessions": 0,
                "total_students": 0,
                "created_at": now,
                "updated_at": now,
                "is_sync_recovered": True
            }
            await db.advisors.insert_one(doc)
        
        print(f"Created {role} record for: {email}")
        synced_count += 1
        
    print(f"\nSync Complete!")
    print(f"- Total Firebase users: {len(fb_users)}")
    print(f"- Already in MongoDB: {already_exists_count}")
    print(f"- New records created: {synced_count}")

if __name__ == "__main__":
    asyncio.run(sync_users())
