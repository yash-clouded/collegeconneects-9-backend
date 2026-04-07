import logging
import asyncio
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.database import get_database
from app.services.google_meet import google_meet_service
from bson import ObjectId

logger = logging.getLogger(__name__)

async def create_meet_links_task():
    """Find bookings starting in 10-15 minutes and create Meet links."""
    db = get_database()
    now = datetime.now(timezone.utc)
    # Window: 10 to 16 minutes from now
    start_window = now + timedelta(minutes=9)
    end_window = now + timedelta(minutes=16)
    
    # Find bookings in the window that don't have a meet_link yet
    cursor = db.bookings.find({
        "scheduled_time": {"$gte": start_window, "$lte": end_window},
        "meet_link": {"$exists": False}
    })
    
    async for booking in cursor:
        try:
            # 0. Check if booking is confirmed
            if booking.get("status") != "confirmed":
                continue

            # 1. Get advisor email
            advisor = await db.advisors.find_one({"_id": ObjectId(booking["advisor_id"])})
            advisor_email = advisor.get("college_email") if advisor else None
            
            loop = asyncio.get_event_loop()
            
            # 2. Create actual hidden Meet link
            meeting = await loop.run_in_executor(
                None, 
                lambda: google_meet_service.create_actual_meeting_link(
                    summary=f"Meet: {booking.get('student_name', 'Student')} & {booking.get('advisor_name', 'Advisor')}",
                    start_time=booking['scheduled_time'],
                    end_time=booking['end_time']
                )
            )
            
            if meeting and meeting.get('meet_link'):
                # 3. Create placeholder invitation (Invite student & advisor, NO link)
                attendees = [booking.get("student_email")]
                if advisor_email:
                    attendees.append(advisor_email)
                
                await loop.run_in_executor(
                    None,
                    lambda: google_meet_service.create_placeholder_event(
                        summary=f"CollegeConnect Session: {booking.get('student_name', 'Student')} & {booking.get('advisor_name', 'Advisor')}",
                        start_time=booking['scheduled_time'],
                        end_time=booking['end_time'],
                        attendees=attendees
                    )
                )

                # 4. Update booking
                await db.bookings.update_one(
                    {"_id": booking["_id"]},
                    {"$set": {
                        "meet_link": meeting['meet_link'],
                        "google_event_id": meeting['event_id'],
                        "updated_at": datetime.now(timezone.utc)
                    }}
                )
                logger.info(f"Scheduled Meet link sync completed for booking {booking['_id']}")
        except Exception as e:
            logger.error(f"Error in scheduled Meet creation for {booking['_id']}: {e}")

async def verify_stuck_payments_task():
    """
    Find pending bookings that have a Razorpay Order ID and check if they've been paid.
    This handles cases where the user closed the window or the sync failed.
    """
    from app.routers.payments import sync_booking_payment_status
    db = get_database()
    
    # Check sessions from the last 24 hours, but older than 5 mins
    now = datetime.now(timezone.utc)
    five_mins_ago = now - timedelta(minutes=5)
    one_day_ago = now - timedelta(hours=24)
    
    cursor = db.bookings.find({
        "status": "pending",
        "razorpay_order_id": {"$exists": True, "$ne": None},
        "created_at": {"$gte": one_day_ago, "$lte": five_mins_ago}
    }).sort("created_at", -1).limit(50)
    
    async for booking in cursor:
        try:
            await sync_booking_payment_status(str(booking["_id"]))
        except Exception as e:
            logger.error(f"Error in scheduled payment sync for {booking['_id']}: {e}")

# Use AsyncIOScheduler instead of BackgroundScheduler
scheduler = AsyncIOScheduler()

def start_scheduler():
    if not scheduler.running:
        # Avoid double adding the job if it reloads
        if not scheduler.get_job('create_meet_links'):
            scheduler.add_job(create_meet_links_task, 'interval', minutes=1, id='create_meet_links')
        if not scheduler.get_job('verify_stuck_payments'):
            scheduler.add_job(verify_stuck_payments_task, 'interval', minutes=10, id='verify_stuck_payments')
        scheduler.start()
        logger.info("Async Background scheduler started.")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Background scheduler stopped.")
