import razorpay
from fastapi import HTTPException
from app.config import settings

class RazorpayService:
    def __init__(self):
        # We check both Razorpay key and secret to initialize the client.
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            self.client = None
        else:
            self.client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))

    def create_order(self, amount: int, currency: str = "INR", receipt: str | None = None):
        """
        Creates a Razorpay order.
        Amount should be in the smallest currency unit (e.g., paise for INR).
        """
        if not self.client:
            raise HTTPException(status_code=500, detail="Razorpay NOT configured on backend (missing keys).")
            
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

    def get_order(self, order_id: str):
        """
        Fetches an order from Razorpay by its ID.
        """
        if not self.client:
            raise HTTPException(status_code=500, detail="Razorpay NOT configured.")
            
        try:
            return self.client.order.fetch(order_id)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error fetching Razorpay order: {str(e)}")

    def verify_payment_signature(self, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str):
        """
        Verifies the HMAC signature from Razorpay.
        """
        if not self.client:
            raise HTTPException(status_code=500, detail="Razorpay NOT configured on backend.")
            
        try:
            params_dict = {
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            }
            # verify_payment_signature returns None if successful, otherwise raises an error.
            return self.client.utility.verify_payment_signature(params_dict)
        except Exception:
            return False

razorpay_service = RazorpayService()
