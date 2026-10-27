from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings
from app.models import Org, OrgMembership, Role, User

logger = logging.getLogger(__name__)


def get_membership_for_github_user(
    db: Session, github_id: str, github_login: str | None = None
) -> OrgMembership | None:
    user = db.scalar(select(User).where(User.github_id == github_id))
    # Claim pending invite created by Admin Settings (github_id pending:…)
    if user is None and github_login:
        login = github_login.strip().lower()
        pending = db.scalar(
            select(User).where(
                User.github_login == login,
                User.github_id.like("pending:%"),
            )
        )
        if pending is not None:
            pending.github_id = str(github_id)
            db.add(pending)
            db.flush()
            user = pending
    if user is None or not user.is_active:
        return None
    return db.scalar(
        select(OrgMembership)
        .options(joinedload(OrgMembership.user), joinedload(OrgMembership.org))
        .where(OrgMembership.user_id == user.id)
        .order_by(OrgMembership.created_at.asc())
    )


def ensure_bootstrap_admin(
    db: Session,
    settings: Settings,
    profile: dict[str, Any],
) -> OrgMembership | None:
    login = str(profile["github_login"]).lower()
    if login not in settings.bootstrap_admins:
        return None

    existing = get_membership_for_github_user(db, str(profile["github_id"]))
    if existing is not None:
        if existing.role != Role.admin:
            existing.role = Role.admin
            db.commit()
            db.refresh(existing)
        return existing

    org = db.scalar(select(Org).where(Org.slug == settings.default_org_slug))
    if org is None:
        org = Org(name=settings.default_org_name, slug=settings.default_org_slug)
        db.add(org)
        db.flush()

    user = User(
        github_id=str(profile["github_id"]),
        github_login=profile["github_login"],
        name=profile.get("name"),
        email=profile.get("email"),
        avatar_url=profile.get("avatar_url"),
        is_active=True,
    )
    db.add(user)
    db.flush()

    membership = OrgMembership(org_id=org.id, user_id=user.id, role=Role.admin)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    # Reload relationships
    return get_membership_for_github_user(db, str(profile["github_id"]))


def refresh_user_profile(db: Session, user: User, profile: dict[str, Any]) -> User:
    user.github_login = profile["github_login"]
    user.name = profile.get("name") or user.name
    user.email = profile.get("email") or user.email
    user.avatar_url = profile.get("avatar_url") or user.avatar_url
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
