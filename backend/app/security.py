
import hmac

from fastapi import Header, HTTPException, status

from app.config import settings


def require_admin(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    configured_key = settings.admin_api_key

    # Fail closed if the admin key is not configured.
    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured.",
        )

    # Reject missing or incorrect admin keys.
    if not x_admin_key or not hmac.compare_digest(
        x_admin_key,
        configured_key,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin key.",
        )
