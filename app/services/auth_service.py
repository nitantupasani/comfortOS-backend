"""Authentication service — Firebase-backed identity verification.

All token issuance and password management is delegated to Firebase Auth.
This service verifies Firebase ID tokens and maps them to local User records.
"""

import uuid

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials as firebase_creds
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.user import User, UserRole

# ── Firebase Admin SDK initialization ────────────────────────────────────

_cred = firebase_creds.Certificate(settings.firebase_service_account_key_path)
_firebase_app = firebase_admin.initialize_app(
    _cred,
    {"projectId": settings.firebase_project_id},
)


def verify_firebase_token(id_token: str) -> dict | None:
    """Verify a Firebase ID token and return its decoded claims, or None."""
    try:
        decoded = firebase_auth.verify_id_token(id_token, app=_firebase_app)
        return decoded
    except Exception:
        return None


async def get_or_create_firebase_user(
    db: AsyncSession, firebase_claims: dict
) -> User | None:
    """Look up or create a local User from verified Firebase claims."""
    email = firebase_claims.get("email", "").strip().lower()
    firebase_uid = firebase_claims.get("uid", "")

    if not email:
        return None

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        # Auto-create new user from Firebase identity
        name = firebase_claims.get("name") or email.split("@")[0]
        auth_provider = firebase_claims.get("firebase", {}).get("sign_in_provider", "unknown")
        user = User(
            id=f"usr-{uuid.uuid4().hex[:8]}",
            email=email,
            name=name,
            hashed_password="FIREBASE_MANAGED",
            role=UserRole.occupant,
            tenant_id=None,
            claims={
                "scopes": ["vote", "view_dashboard"],
                "auth_provider": auth_provider,
                "firebase_uid": firebase_uid,
            },
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    if not user.is_active:
        return None

    # Update claims with Firebase UID if needed
    existing_claims = dict(user.claims or {})
    updated = False
    if existing_claims.get("firebase_uid") != firebase_uid:
        existing_claims["firebase_uid"] = firebase_uid
        updated = True
    if firebase_claims.get("name") and user.name != firebase_claims["name"]:
        user.name = firebase_claims["name"]
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
