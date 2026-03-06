"""
Authentication service — JWT token creation, password hashing, token blacklist.

Maps to the C4 'Identity Provider' container in backend.puml.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Simple in-memory token blacklist. In production use Redis or DB.
_blacklisted_tokens: set[str] = set()


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user: User) -> str:
    """Create a JWT access token embedding user claims."""
    scopes = (user.claims or {}).get("scopes", [])
    payload: dict[str, Any] = {
        "sub": user.id,
        "email": user.email,
        "role": user.role.value,
        "tenant_id": user.tenant_id,  # may be None for independent users
        "scopes": scopes,
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": datetime.now(timezone.utc),
    }
    # Strip None values so JWT stays compact
    return jwt.encode(
        {k: v for k, v in payload.items() if v is not None},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def create_refresh_token(user: User) -> str:
    """Create a longer-lived refresh token."""
    payload: dict[str, Any] = {
        "sub": user.id,
        "type": "refresh",
        "exp": datetime.now(timezone.utc)
        + timedelta(days=settings.refresh_token_expire_days),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT. Returns claims or None."""
    if token in _blacklisted_tokens:
        return None
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except Exception:
        return None


def blacklist_token(token: str) -> None:
    _blacklisted_tokens.add(token)


async def authenticate_user(
    db: AsyncSession, email: str, password: str
) -> User | None:
    """Verify email + password and return the User, or None."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return user


def user_to_response_dict(user: User) -> dict:
    """Convert a User ORM object to the JSON shape expected by the Flutter app."""
    building_access = []
    if hasattr(user, "building_accesses") and user.building_accesses:
        building_access = [
            ba.to_api_dict()
            for ba in user.building_accesses
            if ba.is_active
        ]
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "tenantId": user.tenant_id,
        "buildingAccess": building_access,
        "claims": user.claims or {},
    }
