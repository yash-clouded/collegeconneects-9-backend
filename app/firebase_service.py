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
    """Load service account JSON from FIREBASE_SERVICE_ACCOUNT_PATH or GOOGLE_APPLICATION_CREDENTIALS."""
    path, env_was_set = _service_account_json_path()
    if path is None:
        if not env_was_set:
            _logger.warning(
                "Set FIREBASE_SERVICE_ACCOUNT_PATH or GOOGLE_APPLICATION_CREDENTIALS in backend/.env "
                "(path to Firebase service account JSON). POST /api/students and /api/advisors need it."
            )
        return
    try:
        get_app()
    except ValueError:
        cred = credentials.Certificate(str(path))
        initialize_app(cred)
        _logger.info("Firebase Admin initialized")
        print("Firebase Admin initialized with service account successfully!")


def verify_id_token(id_token: str) -> dict:
    from firebase_admin import auth

    # Allow minor client/server clock drift (common on Windows) to avoid
    # false "Token used too early" failures by a second or two.
    return auth.verify_id_token(id_token, clock_skew_seconds=60)
