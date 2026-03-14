"""
Shared FastAPI dependencies — authentication, database session, tenant isolation.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User, UserRole
from ..services.auth_service import verify_firebase_token

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Verify the Firebase ID token, then load the User from the database."""
    token = credentials.credentials
    firebase_claims = verify_firebase_token(token)
    if firebase_claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Firebase token",
        )

    email = (firebase_claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase token missing email claim",
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def require_role(*roles: str):
    """Dependency factory: require user to have one of the specified roles."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' not in {roles}",
            )
        return user

    return _check


def require_tenant(tenant_id: str):
    """Dependency factory: require user.tenant_id == tenant_id."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant isolation violation",
            )
        return user

    return _check
