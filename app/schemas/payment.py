from pydantic import BaseModel
from typing import Optional


class RazorpayOrderCreate(BaseModel):
    amount: int  # in paise (e.g., 50000 for ₹500.00)
    currency: str = "INR"
    receipt: Optional[str] = None


class RazorpayOrderResponse(BaseModel):
    id: str
    entity: str
    amount: int
    amount_paid: int
    amount_due: int
    currency: str
    receipt: Optional[str] = None
    status: str
    created_at: int


class RazorpayPaymentVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
