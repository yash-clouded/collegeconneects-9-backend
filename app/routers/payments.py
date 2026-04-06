from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.schemas.payment import PaymentOrderCreate, PaymentOrderResponse
from app.services.phonepe_service import phonepe_service
from app.deps import firebase_claims
from app.config import settings
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("/create-order", response_model=PaymentOrderResponse)
async def create_payment_order(order_data: PaymentOrderCreate, claims: dict = Depends(firebase_claims)):
    """
    Create a PhonePe payment session and return its redirect URL.
    Requires authentication.
    """
    transaction_id = f"T{uuid.uuid4().hex[:12].upper()}"
    user_id = claims.get("user_id", "GUEST")
    
    # Callback URL for PhonePe server-to-server notification
    callback_url = f"{settings.base_url}/api/payments/phonepe-callback"
    # Redirect URL for user after payment (Frontend)
    # We return them to a success page or dashboard
    redirect_url = f"{settings.base_url}/payment-status"

    try:
        pay_url = await phonepe_service.initiate_payment(
            transaction_id=transaction_id,
            user_id=user_id,
            amount_paise=order_data.amount,
            redirect_url=redirect_url,
            callback_url=callback_url
        )
        
        return PaymentOrderResponse(
            order_id=transaction_id,
            amount=order_data.amount,
            currency="INR",
            status="CREATED",
            redirect_url=pay_url
        )
    except Exception as e:
        logger.error(f"Failed to initiate PhonePe payment: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/phonepe-callback")
async def phonepe_callback(request: Request):
    """
    Server-to-server callback from PhonePe.
    Verifies the payment status in the database.
    """
    try:
        # 1. Capture the X-VERIFY header and the request body
        x_verify = request.headers.get("X-VERIFY")
        body = await request.json()
        base64_payload = body.get("request")
        
        if not x_verify or not base64_payload:
            return Response(status_code=400, content="Missing callback data")
            
        # 2. Verify and decode
        data = phonepe_service.verify_callback(base64_payload, x_verify)
        
        # 3. Process the results (e.g., update DB)
        # responseCode "SUCCESS" indicates successful payment
        if data.get("success") and data.get("code") == "PAYMENT_SUCCESS":
            transaction_id = data.get("data", {}).get("merchantTransactionId")
            amount = data.get("data", {}).get("amount")
            # Update booking status in database here
            logger.info(f"Payment SUCCESS for {transaction_id}, amount: {amount}")
        else:
            logger.warning(f"Payment FAILED or PENDING: {data.get('message')}")
            
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Callback processing error: {e}")
        return Response(status_code=500, content="Internal error")

@router.get("/status/{transaction_id}")
async def get_payment_status(transaction_id: str, claims: dict = Depends(firebase_claims)):
    """
    Allow frontend to pull status if needed.
    """
    # Simply return generic success/failure or fetch from DB
    return {"transaction_id": transaction_id, "status": "PENDING"}
