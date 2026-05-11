import asyncio
import os
import sys
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Load env
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path)

async def diagnose():
    client = AsyncIOMotorClient(os.getenv("MONGODB_URI"))
    db = client[os.getenv("DATABASE_NAME", "collegeconnect")]
    
    total_advisors = await db.advisors.count_documents({})
    visible_advisors = await db.advisors.count_documents({
        "name": {"$ne": "New User"},
        "branch": {"$exists": True, "$ne": "", "$nin": ["Awaiting Profile Setup"]}
    })
    
    awaiting_setup = await db.advisors.count_documents({"branch": "Awaiting Profile Setup"})
    new_user_name = await db.advisors.count_documents({"name": "New User"})
    
    print(f"--- Advisor Diagnostics ---")
    print(f"Total Advisors in DB: {total_advisors}")
    print(f"Visible in Student Portal: {visible_advisors}")
    print(f"Hidden (Awaiting Setup): {awaiting_setup}")
    print(f"Hidden (New User Name): {new_user_name}")
    
    total_students = await db.students.count_documents({})
    print(f"\n--- Student Diagnostics ---")
    print(f"Total Students in DB: {total_students}")

if __name__ == "__main__":
    asyncio.run(diagnose())
