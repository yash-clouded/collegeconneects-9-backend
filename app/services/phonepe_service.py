import hashlib
import base64
import json
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

class PhonePeService:
    def __init__(self):
        self.merchant_id = settings.phonepe_merchant_id
        self.salt_key = settings.phonepe_salt_key
        self.salt_index = settings.phonepe_salt_index
        self.env = settings.phonepe_env.upper()

        if self.env == "PROD":
            self.base_url = "https://api.phonepe.com/apis/hermes"
        else:
            self.base_url = "https://api-preprod.phonepe.com/apis/pg-sandbox"

    def _generate_x_verify(self, base64_payload: str, endpoint: str) -> str:
        """
        X-VERIFY = SHA256(base64_payload + endpoint + salt_key) + "###" + salt_index
        """
        main_string = base64_payload + endpoint + self.salt_key
        sha256_hash = hashlib.sha256(main_string.encode('utf-8')).hexdigest()
        return f"{sha256_hash}###{self.salt_index}"

    async def initiate_payment(
        self, 
        transaction_id: str, 
        user_id: str, 
        amount_paise: int, 
        redirect_url: str,
        callback_url: str,
        mobile_number: str = None
    ) -> str:
        """
        Initiates a payment and returns the redirect URL for the user.
        """
        endpoint = "/pg/v1/pay"
        
        payload = {
            "merchantId": self.merchant_id,
            "merchantTransactionId": transaction_id,
            "merchantUserId": user_id,
            "amount": amount_paise,
            "redirectUrl": redirect_url,
            "redirectMode": "REDIRECT",
            "callbackUrl": callback_url,
            "paymentInstrument": {
                "type": "PAY_PAGE"
            }
        }
        
        if mobile_number:
            payload["mobileNumber"] = mobile_number

        # 1. Base64 encode the payload
        json_payload = json.dumps(payload)
        base64_payload = base64.b64encode(json_payload.encode('utf-8')).decode('utf-8')

        # 2. Generate X-VERIFY header
        x_verify = self._generate_x_verify(base64_payload, endpoint)

        # 3. Make the API request
        request_body = {"request": base64_payload}
        headers = {
            "Content-Type": "application/json",
            "X-VERIFY": x_verify,
            "accept": "application/json"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}{endpoint}", 
                    json=request_body, 
                    headers=headers,
                    timeout=30.0
                )
                response_data = response.json()
                
                if response_data.get("success"):
                    # Success returns a redirect URL in data.instrumentResponse.redirectInfo.url
                    return response_data["data"]["instrumentResponse"]["redirectInfo"]["url"]
                else:
                    error_msg = response_data.get("message", "Unknown error from PhonePe")
                    logger.error(f"PhonePe payment initiation failed: {error_msg}")
                    raise Exception(f"PhonePe Error: {error_msg}")
            except Exception as e:
                logger.error(f"Error calling PhonePe API: {e}")
                raise

    def verify_callback(self, base64_payload: str, x_verify: str) -> dict:
        """
        Verifies the checksum from a server-to-server callback.
        """
        # The callback DOES NOT have an endpoint in the hash calculation string
        # X-VERIFY = SHA256(base64_payload + salt_key) + "###" + salt_index
        main_string = base64_payload + self.salt_key
        sha256_hash = hashlib.sha256(main_string.encode('utf-8')).hexdigest()
        calculated_verify = f"{sha256_hash}###{self.salt_index}"
        
        if calculated_verify != x_verify:
            raise Exception("Invalid Checksum in PhonePe callback")
            
        # Decode data
        decoded_data = base64.b64decode(base64_payload).decode('utf-8')
        return json.loads(decoded_data)

phonepe_service = PhonePeService()
