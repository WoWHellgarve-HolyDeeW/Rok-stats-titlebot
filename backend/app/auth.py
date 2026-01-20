"""
Authentication module for kingdom-based login.
Each kingdom has a unique password that grants access to the dashboard.
"""
import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .database import get_db
from .models import Kingdom

# Simple JWT-like token (for simplicity, using signed tokens)
SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "rok-stats-hub-secret-key-change-in-production")
TOKEN_EXPIRE_HOURS = 24 * 7  # 7 days

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a password using SHA256 with salt."""
    salted = f"{SECRET_KEY}:{password}"
    return hashlib.sha256(salted.encode()).hexdigest()


def generate_password() -> str:
    """Generate a random password for a kingdom."""
    return secrets.token_urlsafe(12)


def create_token(kingdom_number: int) -> str:
    """Create a simple signed token for a kingdom."""
    expires = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = f"{kingdom_number}:{expires.timestamp()}"
    signature = hashlib.sha256(f"{payload}:{SECRET_KEY}".encode()).hexdigest()[:16]
    return f"{payload}:{signature}"


def verify_token(token: str) -> Optional[int]:
    """Verify a token and return the kingdom number if valid."""
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        kingdom_number = int(parts[0])
        expires = float(parts[1])
        signature = parts[2]
        
        # Check expiration
        if datetime.utcnow().timestamp() > expires:
            return None
        
        # Verify signature
        payload = f"{kingdom_number}:{expires}"
        expected_sig = hashlib.sha256(f"{payload}:{SECRET_KEY}".encode()).hexdigest()[:16]
        if signature != expected_sig:
            return None
        
        return kingdom_number
    except (ValueError, IndexError):
        return None


def get_current_kingdom(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[int]:
    """Extract kingdom number from Bearer token."""
    if not credentials:
        return None
    return verify_token(credentials.credentials)


def require_kingdom_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> int:
    """Require valid authentication, raise 401 if not authenticated."""
    kingdom = get_current_kingdom(credentials)
    if kingdom is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return kingdom


def require_kingdom_access(kingdom_number: int):
    """Dependency that checks if the user has access to a specific kingdom."""
    def checker(current_kingdom: int = Depends(require_kingdom_auth)) -> int:
        if current_kingdom != kingdom_number:
            raise HTTPException(status_code=403, detail="Access denied to this kingdom")
        return current_kingdom
    return checker
