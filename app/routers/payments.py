from fastapi import APIRouter, Depends, HTTPException
from app.schemas.payment import RazorpayOrderCreate, RazorpayOrderResponse, RazorpayPaymentVerify
from app.services.razorpay_service import razorpay_service
from app.deps import firebase_claims

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("/create-order", response_model=RazorpayOrderResponse)
async def create_payment_order(order_data: RazorpayOrderCreate, claims: dict = Depends(firebase_claims)):
    """
    Create a Razorpay order.
    Requires authentication.
    """
    order = razorpay_service.create_order(
        amount=order_data.amount,
        currency=order_data.currency,
        receipt=order_data.receipt
    )
    return order

@router.post("/verify-payment")
async def verify_payment(payment_data: RazorpayPaymentVerify, claims: dict = Depends(firebase_claims)):
    """
    Verify Razorpay payment signature.
    Requires authentication.
    """
    is_valid = razorpay_service.verify_payment(
        razorpay_order_id=payment_data.razorpay_order_id,
        razorpay_payment_id=payment_data.razorpay_payment_id,
        razorpay_signature=payment_data.razorpay_signature
    )
    
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    
    return {"status": "success", "message": "Payment verified successfully"}
