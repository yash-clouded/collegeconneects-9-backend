from datetime import datetime, timezone, timedelta
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from app.database import get_database
from app.deps import firebase_claims
from app.schemas.booking import BookingCreate, BookingResponse, BookingUpdate
from app.services.google_meet import google_meet_service

router = APIRouter(prefix="/bookings", tags=["bookings"])

@router.post("", response_model=BookingResponse)
async def create_booking(payload: BookingCreate, claims: dict = Depends(firebase_claims)):
    db = get_database()
    now = datetime.now(timezone.utc)
    
    doc: dict = payload.model_dump()
    doc["status"] = "pending"
    doc["created_at"] = now
    doc["updated_at"] = now
    doc["student_joined"] = False
    doc["advisor_joined"] = False
    
    result = await db.bookings.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    return doc

@router.get("/me", response_model=list[BookingResponse])
async def get_my_bookings(claims: dict = Depends(firebase_claims)):
    uid = claims["uid"]
    db = get_database()
    
    # Check if student
    student = await db.students.find_one({"firebase_uid": uid})
    if student:
        cursor = db.bookings.find({"student_id": str(student["_id"])})
    else:
        # Check if advisor
        advisor = await db.advisors.find_one({"firebase_uid": uid})
        if advisor:
            cursor = db.bookings.find({"advisor_id": str(advisor["_id"])})
        else:
            return []
            
    bookings = await cursor.to_list(length=100)
    for b in bookings:
        b["id"] = str(b.pop("_id"))
    return bookings

@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(booking_id: str, claims: dict = Depends(firebase_claims)):
    if not ObjectId.is_valid(booking_id):
        raise HTTPException(status_code=400, detail="Invalid booking ID")
        
    db = get_database()
    doc = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    doc["id"] = str(doc.pop("_id"))
    return doc

@router.patch("/{booking_id}/join")
async def join_booking(booking_id: str, claims: dict = Depends(firebase_claims)):
    if not ObjectId.is_valid(booking_id):
        raise HTTPException(status_code=400, detail="Invalid booking ID")
        
    db = get_database()
    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    uid = claims["uid"]
    student = await db.students.find_one({"firebase_uid": uid})
    advisor = await db.advisors.find_one({"firebase_uid": uid})
    
    update = {}
    if student and str(student["_id"]) == booking["student_id"]:
        update["student_joined"] = True
    elif advisor and str(advisor["_id"]) == booking["advisor_id"]:
        update["advisor_joined"] = True
    else:
        raise HTTPException(status_code=403, detail="Not authorized to join this booking")
        
    update["updated_at"] = datetime.now(timezone.utc)
    await db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$set": update})
    return {"message": "Joined successfully"}

@router.post("/{booking_id}/report-noshow")
async def report_noshow(booking_id: str, claims: dict = Depends(firebase_claims)):
    if not ObjectId.is_valid(booking_id):
        raise HTTPException(status_code=400, detail="Invalid booking ID")
        
    db = get_database()
    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    now = datetime.now(timezone.utc)
    # Convert scheduled_time from doc (which is a datetime object in Mongo)
    start_time = booking["scheduled_time"]
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
        
    if now < start_time + timedelta(minutes=15):
        raise HTTPException(status_code=400, detail="Cannot report no-show before 15 minutes have passed")
        
    # Logic to confirm the other person didn't join
    uid = claims["uid"]
    student = await db.students.find_one({"firebase_uid": uid})
    advisor = await db.advisors.find_one({"firebase_uid": uid})
    
    if student and str(student["_id"]) == booking["student_id"]:
        if booking.get("advisor_joined"):
            return {"ok": False, "message": "Advisor did join the meeting."}
        # Mark as advisor no-show
        await db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$set": {"status": "cancelled", "noshow": "advisor"}})
    elif advisor and str(advisor["_id"]) == booking["advisor_id"]:
        if booking.get("student_joined"):
            return {"ok": False, "message": "Student did join the meeting."}
        # Mark as student no-show
        await db.bookings.update_one({"_id": ObjectId(booking_id)}, {"$set": {"status": "cancelled", "noshow": "student"}})
    else:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    return {"ok": True}
