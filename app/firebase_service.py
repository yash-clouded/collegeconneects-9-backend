"""Firebase Admin: verify ID tokens from the web client."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from firebase_admin import credentials, initialize_app, get_app
from app.config import settings

_logger = logging.getLogger(__name__)


def _service_account_json_path() -> tuple[Path | None, bool]:
    """Returns (resolved path or None, whether any credential env var was set)."""
    raw = (
        (settings.firebase_service_account_path or "").strip()
        or (settings.google_application_credentials or "").strip()
        or os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH", "").strip()
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    )
    if not raw:
        return None, False
    path = Path(raw)
    if not path.is_absolute():
        backend_root = Path(__file__).resolve().parent.parent
        path = backend_root / path
    if not path.is_file():
        _logger.error("Service account JSON not found: %s", path)
        return None, True
    return path, True


def init_firebase_admin() -> None:
    """Load service account JSON from FIREBASE_SERVICE_ACCOUNT_JSON,
    FIREBASE_SERVICE_ACCOUNT_PATH or GOOGLE_APPLICATION_CREDENTIALS.
    """
    import json
    from firebase_admin import credentials, initialize_app, get_app

    try:
        get_app()
        return  # Already initialized
    except ValueError:
        pass  # Need to initialize

    # 1. Try JSON string from environment variable
    raw_json = (settings.firebase_service_account_json or "").strip()
    if raw_json:
        try:
            info = json.loads(raw_json)
            cred = credentials.Certificate(info)
            initialize_app(cred)
            _logger.info("Firebase Admin initialized from JSON string")
            print("Firebase Admin initialized from environment variable successfully!")
            return
        except Exception as e:
            _logger.error("Failed to initialize Firebase from FIREBASE_SERVICE_ACCOUNT_JSON: %s", e)

    # 2. Fall back to file path
    path, env_was_set = _service_account_json_path()
    if path:
        try:
            cred = credentials.Certificate(str(path))
            initialize_app(cred)
            _logger.info("Firebase Admin initialized from path: %s", path)
            print(f"Firebase Admin initialized from path {path} successfully!")
            return
        except Exception as e:
            _logger.error("Failed to initialize Firebase from path %s: %s", path, e)

    # 3. If nothing worked, log warning
    if not env_was_set and not raw_json:
        _logger.warning(
            "Set FIREBASE_SERVICE_ACCOUNT_JSON, FIREBASE_SERVICE_ACCOUNT_PATH or GOOGLE_APPLICATION_CREDENTIALS "
            "in backend/.env. POST /api/students and /api/advisors need it."
        )


def verify_id_token(id_token: str) -> dict:
    from firebase_admin import auth

    # Allow minor client/server clock drift (common on Windows) to avoid
    # false "Token used too early" failures by a second or two.
    return auth.verify_id_token(id_token, clock_skew_seconds=60)
