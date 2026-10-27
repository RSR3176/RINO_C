from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth.session import read_session_token
from app.config import Settings, get_settings
from app.database import get_db
from app.models import Org, OrgMembership, Role, User


@dataclass
class AuthContext:
    user: User
    org: Org
    membership: OrgMembership
    role: Role


def require_session_payload(
    settings: Settings = Depends(get_settings),
    rino_session: str | None = Cookie(default=None, alias="rino_session"),
) -> dict:
    if not rino_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = read_session_token(settings, rino_session)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    return payload


def get_current_auth(
    payload: dict = Depends(require_session_payload),
    db: Session = Depends(get_db),
) -> AuthContext:
    try:
        user_id = UUID(payload["uid"])
        org_id = UUID(payload["oid"])
        role = Role(payload["role"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session payload",
        ) from exc

    membership = db.scalar(
        select(OrgMembership)
        .options(joinedload(OrgMembership.user), joinedload(OrgMembership.org))
        .where(
            OrgMembership.user_id == user_id,
            OrgMembership.org_id == org_id,
        )
    )
    if membership is None or not membership.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ask your Admin for access",
        )
    if membership.role != role:
        # Prefer DB role if cookie is stale.
        role = membership.role

    return AuthContext(
        user=membership.user,
        org=membership.org,
        membership=membership,
        role=role,
    )


def require_roles(*allowed: Role):
    allowed_set = set(allowed)

    def _dep(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if auth.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return auth

    return _dep


require_admin = require_roles(Role.admin)
require_developer = require_roles(Role.developer, Role.admin)
require_any_role = require_roles(Role.admin, Role.developer)
