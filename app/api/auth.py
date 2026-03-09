"""
Auth routes — POST /auth/login, /auth/refresh, /auth/logout, GET /auth/validate.

Maps to the C4 'Identity Provider' container.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..schemas.auth import (
    LoginRequest,
    GoogleLoginRequest,
    AuthResponse,
    UserResponse,
)
from ..services.auth_service import (
    authenticate_user,
    authenticate_google_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    blacklist_token,
    user_to_response_dict,
)
from ..api.deps import get_current_user
from ..models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with email/password. Returns JWT + user object."""
    user = await authenticate_user(db, body.email, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    token = create_access_token(user)
    return AuthResponse(
        token=token,
        user=UserResponse(**user_to_response_dict(user)),
    )


@router.post("/google", response_model=AuthResponse)
async def google_login(
    body: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with a verified Google ID token and return a platform JWT."""
    user = await authenticate_google_user(db, body.id_token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google identity token",
        )

    token = create_access_token(user)
    return AuthResponse(
        token=token,
        user=UserResponse(**user_to_response_dict(user)),
    )


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Refresh an access token. Accepts current token in Authorization header."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing token")

    claims = decode_token(credentials.credentials)
    if claims is None:
        raise HTTPException(status_code=401, detail="Token expired or invalid")

    # Blacklist old token
    blacklist_token(credentials.credentials)

    from sqlalchemy import select
    from ..models.user import User as UserModel

    result = await db.execute(
        select(UserModel).where(UserModel.id == claims["sub"])
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    new_token = create_access_token(user)
    return AuthResponse(
        token=new_token,
        user=UserResponse(**user_to_response_dict(user)),
    )


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
):
    """Invalidate the current token."""
    if credentials:
        blacklist_token(credentials.credentials)
    return {"status": "ok"}


@router.get("/validate")
async def validate_token(user: User = Depends(get_current_user)):
    """Validate the current token and return user claims."""
    return {
        "valid": True,
        "user": user_to_response_dict(user),
    }
