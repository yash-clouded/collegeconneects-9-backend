from pydantic import BaseModel
from typing import Optional


class PaymentOrderCreate(BaseModel):
    amount: int  # in paise (e.g., 50000 for ₹500.00)
    currency: str = "INR"
    receipt: Optional[str] = None


class PaymentOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    status: str
    redirect_url: str  # URL to redirect the user for payment
