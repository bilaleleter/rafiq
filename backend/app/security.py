"""Admin guard for demo / simulation / write-anything endpoints.
No ADMIN_TOKEN set (local testing) -> open. ADMIN_TOKEN set -> header X-Admin-Token must match."""
import hmac

from fastapi import Header, HTTPException

from app import config


def require_admin(x_admin_token: str | None = Header(None)) -> None:
    if not config.ADMIN_TOKEN:
        return
    if not x_admin_token or not hmac.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(403, "admin token required")
