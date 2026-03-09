"""Authentication service — local and Google-backed identity flows."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.user import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Simple in-memory token blacklist. In production use Redis or DB.
_blacklisted_tokens: set[str] = set()
_google_request = google_requests.Request()
_google_issuers = {"accounts.google.com", "https://accounts.google.com"}


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


def verify_google_id_token(token: str) -> dict[str, Any] | None:
    """Verify a Google ID token and return its claims."""
    try:
        claims = google_id_token.verify_oauth2_token(
            token,
            _google_request,
            settings.google_oauth_client_id or None,
        )
    except Exception:
        return None

    if claims.get("iss") not in _google_issuers:
        return None
    if not claims.get("email") or not claims.get("email_verified"):
        return None
    return claims


async def authenticate_google_user(
    db: AsyncSession, id_token: str
) -> User | None:
    """Verify Google identity and map it to a local platform user."""
    claims = verify_google_id_token(id_token)
    if claims is None:
        return None

    email = str(claims["email"]).strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        name = str(claims.get("name") or email.split("@")[0])
        user = User(
            email=email,
            name=name,
            hashed_password=hash_password(uuid.uuid4().hex),
            role=UserRole.occupant,
            tenant_id=None,
            claims={
                "scopes": ["vote", "view_dashboard"],
                "auth_provider": "google",
                "google_sub": claims.get("sub"),
            },
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    if not user.is_active:
        return None

    updated = False
    if claims.get("name") and user.name != claims["name"]:
        user.name = str(claims["name"])
        updated = True

    existing_claims = dict(user.claims or {})
    google_sub = claims.get("sub")
    if google_sub:
        if existing_claims.get("google_sub") not in (None, google_sub):
            return None
        if existing_claims.get("google_sub") != google_sub:
            existing_claims["google_sub"] = google_sub
            updated = True

    if existing_claims.get("auth_provider") != "google":
        existing_claims["auth_provider"] = "google"
        updated = True

    if updated:
        user.claims = existing_claims
        await db.commit()
        await db.refresh(user)

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
