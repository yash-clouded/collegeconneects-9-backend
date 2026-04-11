import asyncio
import os
import sys
from firebase_admin import auth as fb_auth, initialize_app, credentials, get_app
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Add parent to path to allow imports if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load env from .env
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path)

MONGODB_URI = os.getenv("MONGODB_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME", "collegeconnects")
FIREBASE_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")

async def check_sync():
    # Initialize Firebase
    fb_service_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    
    try:
        get_app()
    except ValueError:
        if not fb_service_path:
             print("Error: FIREBASE_SERVICE_ACCOUNT_PATH not found in .env")
             return
        
        # If the path is relative, make it relative to the .env file (backend root)
        if not os.path.isabs(fb_service_path):
            backend_root = os.path.dirname(dotenv_path)
            fb_service_path = os.path.join(backend_root, fb_service_path)
            
        print(f"Using Firebase Service Account: {fb_service_path}")
        cred = credentials.Certificate(fb_service_path)
        initialize_app(cred)
    
    # Initialize Mongo
    mongo_uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("DATABASE_NAME", "collegeconnects")
    
    if not mongo_uri:
        print("Error: MONGODB_URI not found in .env")
        return
        
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]
    
    print(f"Connecting to MongoDB: {db_name}")
    print("Fetching Firebase users...")
    fb_users = []
    page = fb_auth.list_users()
    while page:
        fb_users.extend(page.users)
        page = page.get_next_page()
    
    print(f"Total Firebase Users Found: {len(fb_users)}")
    
    missing = []
    found_count = 0
    for u in fb_users:
        email = u.email.lower()
        # Check student
        s = await db.students.find_one({"email": email})
        if s: 
            found_count += 1
            continue
        
        # Check advisor
        a = await db.advisors.find_one({"college_email": email})
        if a: 
            found_count += 1
            continue
        
        missing.append({"email": email, "uid": u.uid, "name": u.display_name})
    
    print(f"Users found in MongoDB: {found_count}")
    print(f"\nMissing Users in MongoDB ({len(missing)}):")
    for m in missing:
        print(f"- {m['email']} ({m['name'] or 'No Name'})")

if __name__ == "__main__":
    asyncio.run(check_sync())
