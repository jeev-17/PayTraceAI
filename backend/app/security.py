
import hmac

from fastapi import Header, HTTPException, status

from app.config import settings


def require_admin(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    configured_keys = [
        key
        for key in (
            settings.admin_api_key,
            settings.demo_admin_api_key,
        )
        if key
    ]

    # Fail closed if no admin keys are configured.
    if not configured_keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured.",
        )

    # Reject missing or incorrect admin keys.
    if not x_admin_key or not any(
        hmac.compare_digest(x_admin_key, key)
        for key in configured_keys
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin key.",
        )
