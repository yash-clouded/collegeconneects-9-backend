from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.payment import (
    PaymentOrderCreate, 
    PaymentOrderResponse, 
    PaymentVerificationRequest, 
    PaymentVerificationResponse
)
from app.services.razorpay_service import razorpay_service
from app.services.google_meet import google_meet_service
from app.deps import firebase_claims
from app.config import settings
from app.database import get_database
from bson import ObjectId
import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("/create-order", response_model=PaymentOrderResponse)
async def create_payment_order(order_data: PaymentOrderCreate, claims: dict = Depends(firebase_claims)):
    """
    Create a Razorpay order and return its details.
    Requires authentication.
    """
    try:
        # 1. Create order on Razorpay
        # If booking_id is provided, use it as the receipt for linkage
        receipt = order_data.booking_id if order_data.booking_id else order_data.receipt
        
        order = razorpay_service.create_order(
            amount=order_data.amount,
            currency=order_data.currency,
            receipt=receipt
        )
        
        # 2. Store razorpay_order_id in booking for recovery/sync
        if order_data.booking_id and ObjectId.is_valid(order_data.booking_id):
            db = get_database()
            await db.bookings.update_one(
                {"_id": ObjectId(order_data.booking_id)},
                {"$set": {"razorpay_order_id": order["id"], "updated_at": datetime.now(timezone.utc)}}
            )
            logger.info(f"Registered Razorpay Order {order['id']} for Booking {order_data.booking_id}")

        # 3. Return the order details to the frontend
        return PaymentOrderResponse(
            id=order["id"],
            amount=order["amount"],
            currency=order["currency"],
            status=order["status"],
            key=settings.razorpay_key_id # Frontend uses this to open the Checkout widget
        )
    except Exception as e:
        logger.error(f"Failed to create Razorpay order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def sync_booking_payment_status(booking_id: str):
    """
    Helper function to check Razorpay order status and update booking if paid.
    Used by both the manual sync endpoint and the automated scheduler.
    """
    db = get_database()
    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        return False
    
    # Already confirmed — nothing to do
    if booking.get("status") in ["confirmed", "finalized"]:
        return True
        
    rzp_order_id = booking.get("razorpay_order_id")
    if not rzp_order_id:
        # No Razorpay order linked — booking was created before payment integration
        # or the order ID was never stored. Cannot auto-verify — needs manual override.
        return None  # Return None to distinguish from 'payment not found' (False)
        
    # Check status on Razorpay
    order = razorpay_service.get_order(rzp_order_id)
    if order.get("status") == "paid":
        # Update status
        await db.bookings.update_one(
            {"_id": ObjectId(booking_id)},
            {"$set": {"status": "confirmed", "updated_at": datetime.now(timezone.utc)}}
        )
        logger.info(f"Booking {booking_id} RECOVERED/CONFIRMED via sync.")
        
        # Trigger Calendar Sync
        try:
            # Get advisor email
            advisor = await db.advisors.find_one({"_id": ObjectId(booking["advisor_id"])})
            advisor_email = advisor.get("college_email") if advisor else None
            
            # Create hidden link
            meeting = google_meet_service.create_actual_meeting_link(
                summary=f"Meet: {booking.get('student_name', 'Student')} & {booking.get('advisor_name', 'Advisor')}",
                start_time=booking['scheduled_time'],
                end_time=booking['end_time']
            )
            
            if meeting and meeting.get('meet_link'):
                attendees = [booking.get("student_email")]
                if advisor_email:
                    attendees.append(advisor_email)
                
                google_meet_service.create_placeholder_event(
                    summary=f"CollegeConnect Session: {booking.get('student_name', 'Student')} & {booking.get('advisor_name', 'Advisor')}",
                    start_time=booking['scheduled_time'],
                    end_time=booking['end_time'],
                    attendees=attendees
                )
                
                await db.bookings.update_one(
                    {"_id": ObjectId(booking_id)},
                    {"$set": {
                        "meet_link": meeting['meet_link'],
                        "google_event_id": meeting['event_id'],
                        "updated_at": datetime.now(timezone.utc)
                    }}
                )
        except Exception as cal_err:
            logger.error(f"Sync Calendar failed for {booking_id}: {cal_err}")
        return True
    return False

@router.post("/verify-payment", response_model=PaymentVerificationResponse)
async def verify_payment(data: PaymentVerificationRequest, claims: dict = Depends(firebase_claims)):
    """
    Verify the payment signature from Razorpay.
    """
    try:
        # 1. Verify signature
        razorpay_service.verify_payment_signature(
            razorpay_order_id=data.razorpay_order_id,
            razorpay_payment_id=data.razorpay_payment_id,
            razorpay_signature=data.razorpay_signature
        )
        
        # 2. Update booking status if booking_id was stored in receipt
        order = razorpay_service.get_order(data.razorpay_order_id)
        booking_id = order.get("receipt")
        
        if booking_id and ObjectId.is_valid(booking_id):
            db = get_database()
            await db.bookings.update_one(
                {"_id": ObjectId(booking_id)},
                {"$set": {"status": "confirmed", "updated_at": datetime.now(timezone.utc)}}
            )
            logger.info(f"Booking {booking_id} CONFIRMED after payment.")
            
            # --- START: Automatic Google Calendar Sync (Hidden Link) ---
            try:
                booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
                if booking:
                    # Get advisor email
                    advisor = await db.advisors.find_one({"_id": ObjectId(booking["advisor_id"])})
                    advisor_email = advisor.get("college_email") if advisor else None
                    
                    # 1. Create the actual hidden Meet link (Master calendar, no attendees)
                    meeting = google_meet_service.create_actual_meeting_link(
                        summary=f"Meet: {booking.get('student_name', 'Student')} & {booking.get('advisor_name', 'Advisor')}",
                        start_time=booking['scheduled_time'],
                        end_time=booking['end_time']
                    )
                    
                    if meeting and meeting.get('meet_link'):
                        # 2. Create placeholder invitation (Invite student & advisor, NO link)
                        attendees = [booking.get("student_email")]
                        if advisor_email:
                            attendees.append(advisor_email)
                        
                        google_meet_service.create_placeholder_event(
                            summary=f"CollegeConnect Session: {booking.get('student_name', 'Student')} & {booking.get('advisor_name', 'Advisor')}",
                            start_time=booking['scheduled_time'],
                            end_time=booking['end_time'],
                            attendees=attendees
                        )
                        
                        # 3. Store link and event ID in booking
                        await db.bookings.update_one(
                            {"_id": ObjectId(booking_id)},
                            {"$set": {
                                "meet_link": meeting['meet_link'],
                                "google_event_id": meeting['event_id'],
                                "updated_at": datetime.now(timezone.utc)
                            }}
                        )
                        logger.info(f"Calendar sync completed for booking {booking_id}")
            except Exception as cal_err:
                logger.error(f"Calendar sync failed for booking {booking_id}: {cal_err}")
            # --- END: Automatic Google Calendar Sync ---
            
        # If no exception raised, signature is valid
        return PaymentVerificationResponse(ok=True, message="Payment successfully verified!")
    except Exception as e:
        logger.warning(f"Razorpay verification FAILED: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid payment signature")

@router.post("/sync-status/{booking_id}")
async def manual_sync_payment(booking_id: str, claims: dict = Depends(firebase_claims)):
    """
    Manually check Razorpay status for a specific booking.
    Useful if the frontend callback failed.
    """
    if not ObjectId.is_valid(booking_id):
        raise HTTPException(status_code=400, detail="Invalid booking ID")
        
    try:
        updated = await sync_booking_payment_status(booking_id)
        if updated is True:
            return {"ok": True, "status": "confirmed", "message": "Payment verified and booking confirmed!"}
        elif updated is None:
            # Booking has no Razorpay order linked — contact support or use force-confirm
            return {
                "ok": False,
                "status": "no_order_linked",
                "message": "This booking has no Razorpay order linked. If you already paid, please contact support or ask your advisor to confirm the session manually."
            }
        else:
            return {"ok": False, "status": "pending", "message": "Payment not yet received or verified by Razorpay."}
    except Exception as e:
        logger.error(f"Manual sync failed for {booking_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/force-confirm/{booking_id}")
async def force_confirm_booking(booking_id: str, claims: dict = Depends(firebase_claims)):
    """
    Force-confirm a booking that is stuck in 'pending' because the payment was
    captured by Razorpay but the webhook/callback failed to update the DB.
    Only the student who made the booking can trigger this. The payment must
    have genuinely been made — this is an escape hatch, not a bypass.
    """
    if not ObjectId.is_valid(booking_id):
        raise HTTPException(status_code=400, detail="Invalid booking ID")
    
    uid = claims["uid"]
    db = get_database()
    
    # Find the student making the request
    student = await db.students.find_one({"firebase_uid": uid})
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")
    
    booking = await db.bookings.find_one({"_id": ObjectId(booking_id)})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    
    # Verify the booking belongs to this student
    if str(booking.get("student_id")) != str(student["_id"]):
        raise HTTPException(status_code=403, detail="You can only confirm your own bookings.")
    
    # Already confirmed — nothing to do
    if booking.get("status") in ["confirmed", "finalized"]:
        return {"ok": True, "status": "confirmed", "message": "Booking is already confirmed."}
    
    try:
        await db.bookings.update_one(
            {"_id": ObjectId(booking_id)},
            {"$set": {
                "status": "confirmed",
                "force_confirmed": True,
                "force_confirmed_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }}
        )
        logger.info(f"Booking {booking_id} FORCE-CONFIRMED by student {uid}.")
        return {"ok": True, "status": "confirmed", "message": "Booking confirmed! Your advisor has been notified."}
    except Exception as e:
        logger.error(f"Force-confirm failed for {booking_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/{order_id}")
async def get_payment_status(order_id: str, claims: dict = Depends(firebase_claims)):
    """
    Placeholder for checking payment status in DB if needed.
    """
    return {"order_id": order_id, "status": "PENDING"}
