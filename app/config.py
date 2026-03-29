from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load backend/.env even when uvicorn is started from the repo root (fixes wrong cluster / local default).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongodb_uri: str = "mongodb://localhost:27017"
    database_name: str = "collegeconnect"
    google_application_credentials: str = ""
    google_impersonate_user: str = ""
    firebase_service_account_path: str = "firebase-adminsdk.json"
    firebase_service_account_json: str = ""
    # Session booking emails (Resend): https://resend.com/docs
    resend_api_key: str = ""
    # e.g. "CollegeConnect <bookings@yourdomain.com>" (must be a verified sender in Resend)
    resend_from: str = ""

    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # AWS S3 — college ID card uploads (presigned PUT from browser)
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = ""
    s3_bucket: str = ""
    # Object key prefix, no leading/trailing slashes
    s3_college_ids_prefix: str = "college-ids"
    s3_profile_pictures_prefix: str = "profile-pictures"

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""


settings = Settings()
