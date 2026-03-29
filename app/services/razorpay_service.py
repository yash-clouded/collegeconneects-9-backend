import razorpay
from app.config import settings
from fastapi import HTTPException

class RazorpayService:
    def __init__(self):
        self.client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))

    def create_order(self, amount: int, currency: str = "INR", receipt: str | None = None):
        """
        Amount should be in the smallest currency unit (e.g., paise for INR).
        """
        try:
            data = {
                "amount": amount,
                "currency": currency,
                "receipt": receipt,
                "payment_capture": 1 # Auto capture
            }
            order = self.client.order.create(data=data)
            return order
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error creating Razorpay order: {str(e)}")

    def verify_payment(self, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str):
        try:
            params_dict = {
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            }
            return self.client.utility.verify_payment_signature(params_dict)
        except Exception:
            return False

razorpay_service = RazorpayService()
