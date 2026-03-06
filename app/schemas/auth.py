"""Authentication request/response schemas.

Matches the Identity Provider contract consumed by the Flutter frontend's
HttpBackendAdapter (POST /auth/login, /auth/refresh, /auth/logout, GET /auth/validate).
"""

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenPayload(BaseModel):
    """JWT claims embedded in the access token."""
    sub: str  # user id
    email: str
    role: str
    tenant_id: str | None = None
    scopes: list[str] = []


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
