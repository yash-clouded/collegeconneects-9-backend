from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class BookingBase(BaseModel):
    advisor_id: str
    student_id: str
    scheduled_time: datetime
    end_time: datetime
    selected_slot: str
    session_price: str

class BookingCreate(BookingBase):
    advisor_name: str
    student_name: str
    student_email: str

class BookingResponse(BookingBase):
    id: str
    advisor_name: str
    student_name: str
    student_email: str
    status: Literal["pending", "confirmed", "cancelled", "finalized"] = "pending"
    google_event_id: str | None = None
    meet_link: str | None = None
    student_joined: bool = False
    advisor_joined: bool = False
    created_at: datetime
    updated_at: datetime

class BookingUpdate(BaseModel):
    status: Literal["pending", "confirmed", "cancelled", "finalized"] | None = None
    scheduled_time: datetime | None = None
    end_time: datetime | None = None
    student_joined: bool | None = None
    advisor_joined: bool | None = None
    meet_link: str | None = None
    google_event_id: str | None = None
