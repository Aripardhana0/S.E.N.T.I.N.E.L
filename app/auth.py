"""Dashboard authentication helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from app.config import config

COOKIE_NAME = "sentinel_session"
SESSION_TTL_SECONDS = 60 * 60 * 12
DEFAULT_PASSWORD_HASH = (
    "sha256$983515b6ea7cc3ef2bf502498e07dcd9f8f22a6dda475d36b2817df6b11275f0"
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _password_hash() -> str:
    return config.DASHBOARD_PASSWORD_HASH or DEFAULT_PASSWORD_HASH


def _session_secret() -> str:
    return (
        config.DASHBOARD_SESSION_SECRET
        or config.DASHBOARD_PASSWORD_HASH
        or DEFAULT_PASSWORD_HASH
    )


def verify_credentials(username: str, password: str) -> bool:
    expected_user = config.DASHBOARD_USERNAME
    if not hmac.compare_digest(str(username), expected_user):
        return False

    if config.DASHBOARD_PASSWORD:
        return hmac.compare_digest(str(password), config.DASHBOARD_PASSWORD)

    stored = _password_hash()
    if stored.startswith("sha256$"):
        expected_hash = stored.split("$", 1)[1]
        return hmac.compare_digest(_sha256(str(password)), expected_hash)
    return hmac.compare_digest(str(password), stored)


def create_session_token() -> str:
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    nonce = secrets.token_urlsafe(18)
    payload = f"{expires_at}:{nonce}"
    signature = hmac.new(
        _session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def verify_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        expires_at_raw, nonce, signature = token.split(":", 2)
        expires_at = int(expires_at_raw)
    except (TypeError, ValueError):
        return False
    if expires_at < int(time.time()):
        return False

    payload = f"{expires_at}:{nonce}"
    expected = hmac.new(
        _session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)
