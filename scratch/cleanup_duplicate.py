import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

async def cleanup_dual_role():
    load_dotenv()
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("DATABASE_NAME", "collegeconnect")
    
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    
    # The email to fix
    email_to_fix = "25mc3054@rgipt.ac.in"
    
    print(f"Cleaning up dual-role for: {email_to_fix}")
    
    # 1. Find the UID
    advisor = await db.advisors.find_one({"college_email": email_to_fix})
    if not advisor:
        print("Advisor record not found. Skipping.")
        return
        
    uid = advisor.get("firebase_uid")
    print(f"Target UID: {uid}")
    
    # 2. Check if a student record exists with this UID
    student = await db.students.find_one({"firebase_uid": uid})
    if student:
        print(f"Found duplicate Student record (ID: {student['_id']}). Deleting...")
        res = await db.students.delete_one({"_id": student["_id"]})
        print(f"Deleted {res.deleted_count} student record(s).")
    else:
        print("No duplicate student record found.")

    # 3. Ensure the advisor record has the correct role set
    await db.advisors.update_one({"_id": advisor["_id"]}, {"$set": {"role": "advisor"}})
    print("Advisor record verified and role set to 'advisor'.")

if __name__ == "__main__":
    asyncio.run(cleanup_dual_role())
