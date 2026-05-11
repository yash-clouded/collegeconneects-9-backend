import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

async def check_duplicates():
    load_dotenv()
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("DATABASE_NAME", "collegeconnect")
    
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    
    email_to_check = "25mc3054@rgipt.ac.in"
    
    print(f"Checking for email: {email_to_check}")
    
    student = await db.students.find_one({"email": email_to_check})
    advisor = await db.advisors.find_one({"college_email": email_to_check})
    
    if student:
        print(f"Student found! UID: {student.get('firebase_uid')}, Role: {student.get('role')}")
    else:
        print("Student NOT found.")
        
    if advisor:
        print(f"Advisor found! UID: {advisor.get('firebase_uid')}, Role: {advisor.get('role')}")
    else:
        print("Advisor NOT found.")

    # Also check by UID if we found any
    uid = (student or {}).get("firebase_uid") or (advisor or {}).get("firebase_uid")
    if uid:
        print(f"\nChecking by UID: {uid}")
        s2 = await db.students.find_one({"firebase_uid": uid})
        a2 = await db.advisors.find_one({"firebase_uid": uid})
        if s2: print(f"Found in students by UID: {s2.get('email')}")
        if a2: print(f"Found in advisors by UID: {a2.get('college_email')}")

if __name__ == "__main__":
    asyncio.run(check_duplicates())
