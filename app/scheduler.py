import logging
import asyncio
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.database import get_database
from app.services.google_meet import google_meet_service

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
            # We assume google_meet_service is also adjusted for async if it's used here, 
            # otherwise we wrap it in a thread if it's sync.
            # Assuming google_meet_service.create_meeting is a sync call from a library:
            loop = asyncio.get_event_loop()
            meeting = await loop.run_in_executor(
                None, 
                lambda: google_meet_service.create_meeting(
                    summary=f"CollegeConnect: {booking.get('student_name', 'Student')} & {booking.get('advisor_name', 'Advisor')}",
                    start_time=booking['scheduled_time'],
                    end_time=booking['end_time'],
                    attendees=[booking['student_email']]
                )
            )
            
            if meeting and meeting.get('meet_link'):
                await db.bookings.update_one(
                    {"_id": booking["_id"]},
                    {"$set": {
                        "meet_link": meeting['meet_link'],
                        "google_event_id": meeting['event_id'],
                        "updated_at": datetime.now(timezone.utc)
                    }}
                )
                logger.info(f"Created Meet link for booking {booking['_id']}")
        except Exception as e:
            logger.error(f"Error creating Meet link for {booking['_id']}: {e}")

# Use AsyncIOScheduler instead of BackgroundScheduler
scheduler = AsyncIOScheduler()

def start_scheduler():
    if not scheduler.running:
        # Avoid double adding the job if it reloads
        if not scheduler.get_job('create_meet_links'):
            scheduler.add_job(create_meet_links_task, 'interval', minutes=1, id='create_meet_links')
        scheduler.start()
        logger.info("Async Background scheduler started.")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Background scheduler stopped.")
