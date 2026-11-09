import hmac
import logging
from typing import Optional

from fastapi import Header, HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)


def require_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> None:
    """Protege os endpoints administrativos. Configure ADMIN_API_KEY no .env."""
    if not settings.ADMIN_API_KEY:
        return  # modo desenvolvimento
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-API-Key inválida ou ausente")
