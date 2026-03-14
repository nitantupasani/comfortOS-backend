"""Authentication request/response schemas.

Matches the Identity Provider contract consumed by the Flutter frontend's
HttpBackendAdapter (POST /auth/firebase, GET /auth/validate).

Firebase handles all token issuance; the backend only verifies tokens.
"""

from pydantic import BaseModel, ConfigDict, Field


class FirebaseLoginRequest(BaseModel):
    """Client sends a Firebase ID token for backend verification."""
    model_config = ConfigDict(populate_by_name=True)

    id_token: str = Field(alias="idToken", min_length=1)


class UserResponse(BaseModel):
    """User object returned alongside a token — matches Dart User.fromJson."""
    id: str
    email: str
    name: str
    role: str
    tenantId: str | None = None
    buildingAccess: list[dict] = []
    claims: dict = {}


class AuthResponse(BaseModel):
    """Token + user response — matches the shape expected by ApiClient.login()."""
    token: str
    user: UserResponse


class TokenValidation(BaseModel):
    """Returned by GET /auth/validate."""
    valid: bool
    user: UserResponse | None = None
