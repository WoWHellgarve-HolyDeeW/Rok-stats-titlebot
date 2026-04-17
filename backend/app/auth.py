"""
Authentication module for kingdom-based login.
Each kingdom has a unique password that grants access to the dashboard.
"""
import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import NamedTuple, Optional
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .database import get_db
from .models import Kingdom

# Simple JWT-like token (for simplicity, using signed tokens)
SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change-me-replace-with-long-random-string")
TOKEN_EXPIRE_HOURS = 24 * 7  # 7 days

security = HTTPBearer(auto_error=False)
TOKEN_ROLE_OWNER = "owner"
TOKEN_ROLE_SHARED = "shared"


class KingdomAuth(NamedTuple):
    kingdom_number: int
    is_owner: bool


def hash_password(password: str) -> str:
    """Hash a password using SHA256 with salt."""
    salted = f"{SECRET_KEY}:{password}"
    return hashlib.sha256(salted.encode()).hexdigest()


def generate_password() -> str:
    """Generate a random password for a kingdom."""
    return secrets.token_urlsafe(12)


def _sign_payload(payload: str) -> str:
    return hashlib.sha256(f"{payload}:{SECRET_KEY}".encode()).hexdigest()[:16]


def create_token(kingdom_number: int, is_owner: bool = True) -> str:
    """Create a simple signed token for a kingdom."""
    expires = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    role = TOKEN_ROLE_OWNER if is_owner else TOKEN_ROLE_SHARED
    payload = f"{kingdom_number}:{role}:{expires.timestamp()}"
    signature = _sign_payload(payload)
    return f"{payload}:{signature}"


def verify_token(token: str) -> Optional[KingdomAuth]:
    """Verify a token and return kingdom auth info if valid."""
    try:
        parts = token.split(":")
        if len(parts) == 4:
            kingdom_number = int(parts[0])
            role = parts[1]
            expires = float(parts[2])
            signature = parts[3]
            if role not in {TOKEN_ROLE_OWNER, TOKEN_ROLE_SHARED}:
                return None

            if datetime.utcnow().timestamp() > expires:
                return None

            payload = f"{kingdom_number}:{role}:{expires}"
            if signature != _sign_payload(payload):
                return None

            return KingdomAuth(
                kingdom_number=kingdom_number,
                is_owner=(role == TOKEN_ROLE_OWNER),
            )

        if len(parts) == 3:
            kingdom_number = int(parts[0])
            expires = float(parts[1])
            signature = parts[2]

            if datetime.utcnow().timestamp() > expires:
                return None

            payload = f"{kingdom_number}:{expires}"
            if signature != _sign_payload(payload):
                return None

            # Legacy tokens are treated as shared/read-only until the user logs in again.
            return KingdomAuth(kingdom_number=kingdom_number, is_owner=False)

        return None
    except (ValueError, IndexError):
        return None


def get_current_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[KingdomAuth]:
    """Extract kingdom auth info from Bearer token."""
    if not credentials:
        return None
    return verify_token(credentials.credentials)


def get_current_kingdom(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[int]:
    """Extract kingdom number from Bearer token."""
    auth = get_current_auth(credentials)
    if auth is None:
        return None
    return auth.kingdom_number


def require_kingdom_auth_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> KingdomAuth:
    """Require valid authentication and return kingdom auth context."""
    auth = get_current_auth(credentials)
    if auth is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return auth


def require_kingdom_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> int:
    """Require valid authentication, raise 401 if not authenticated."""
    return require_kingdom_auth_context(credentials).kingdom_number


def require_owner_kingdom_auth(
    current_auth: KingdomAuth = Depends(require_kingdom_auth_context),
) -> int:
    """Require owner access for a kingdom token."""
    if not current_auth.is_owner:
        raise HTTPException(status_code=403, detail="Owner access required")
    return current_auth.kingdom_number


def require_kingdom_access(kingdom_number: int):
    """Dependency that checks if the user has access to a specific kingdom."""
    def checker(current_kingdom: int = Depends(require_kingdom_auth)) -> int:
        if current_kingdom != kingdom_number:
            raise HTTPException(status_code=403, detail="Access denied to this kingdom")
        return current_kingdom
    return checker
