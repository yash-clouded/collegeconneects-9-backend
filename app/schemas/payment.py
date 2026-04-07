from pydantic import BaseModel
from typing import Optional


class PaymentOrderCreate(BaseModel):
    amount: int  # in paise (e.g., 50000 for ₹500.00)
    currency: str = "INR"
    receipt: Optional[str] = None
    booking_id: Optional[str] = None



class PaymentOrderResponse(BaseModel):
    id: str # Razorpay Order ID
    amount: int
    currency: str
    status: str
    key: Optional[str] = None # Return the public key to the frontend client

class PaymentVerificationRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

class PaymentVerificationResponse(BaseModel):
    ok: bool = True
    message: str = "Payment verified successfully"

