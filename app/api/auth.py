"""
Auth routes — POST /auth/firebase, GET /auth/validate.

Authentication is handled by Firebase. The client sends a Firebase ID token,
and the backend verifies it and returns the local user record.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..schemas.auth import (
    FirebaseLoginRequest,
    AuthResponse,
    UserResponse,
)
from ..services.auth_service import (
    verify_firebase_token,
    get_or_create_firebase_user,
    user_to_response_dict,
)
from ..api.deps import get_current_user
from ..models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


@router.post("/firebase", response_model=AuthResponse)
async def firebase_login(
    body: FirebaseLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with a Firebase ID token. Returns the token back + user object.

    The Flutter app signs in via Firebase Auth (Google, email/password, etc.)
    and sends the Firebase ID token here. The backend verifies it, creates or
    looks up the local user, and returns the user data.

    The client continues to use the same Firebase ID token for subsequent
    API calls (verified in deps.get_current_user).
    """
    firebase_claims = verify_firebase_token(body.id_token)
    if firebase_claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase identity token",
        )

    user = await get_or_create_firebase_user(db, firebase_claims)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not resolve Firebase user",
        )

    return AuthResponse(
        token=body.id_token,
        user=UserResponse(**user_to_response_dict(user)),
    )


@router.get("/validate")
async def validate_token(user: User = Depends(get_current_user)):
    """Validate the current Firebase token and return user claims."""
    return {
        "valid": True,
        "user": user_to_response_dict(user),
    }
