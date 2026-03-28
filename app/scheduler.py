import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from app.database import get_database
from app.services.google_meet import google_meet_service

logger = logging.getLogger(__name__)

def create_meet_links_task():
    """Find bookings starting in 10-15 minutes and create Meet links."""
    import asyncio
    
    async def run():
        db = get_database()
        now = datetime.now(timezone.utc)
        start_window = now + timedelta(minutes=9)
        end_window = now + timedelta(minutes=16)
        
        # Find bookings in the window that don't have a meet_link yet
        cursor = db.bookings.find({
            "scheduled_time": {"$gte": start_window, "$lte": end_window},
            "meet_link": {"$exists": False}
        })
        
        async for booking in cursor:
            try:
                meeting = google_meet_service.create_meeting(
                    summary=f"CollegeConnect: {booking['student_name']} & {booking['advisor_name']}",
                    start_time=booking['scheduled_time'],
                    end_time=booking['end_time'],
                    attendees=[booking['student_email']] # Add advisor email if needed
                )
                if meeting:
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

    # Run the async loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(run())
        else:
            loop.run_until_complete(run())
    except Exception as e:
        logger.error(f"Scheduler task failed: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(create_meet_links_task, 'interval', minutes=1)

def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Background scheduler started.")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Background scheduler stopped.")
