"""Admin Settings: users/roles, triage rules, fix limits, audit log."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.deps import AuthContext, require_admin
from app.models import AuditLog, OrgMembership, Role, User
from app.repo_service import write_audit
from app.triage.load_rules import RULES_PATH, clear_rules_cache, load_rules

router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])


class MemberOut(BaseModel):
    user_id: UUID
    github_login: str
    name: str | None = None
    role: Role
    is_you: bool = False
    last_active: datetime | None = None
    invite_pending: bool = False


class InviteIn(BaseModel):
    github_login: str
    role: Role = Role.developer


class RoleIn(BaseModel):
    role: Role


class FixLimitsOut(BaseModel):
    max_attempts: int = 3
    max_files_changed: int = 3


class TriageSettingsOut(BaseModel):
    setup_failed_enabled: bool = True
    missing_package_enabled: bool = True
    flaky_enabled: bool = True
    flaky_rerun_count: int = 2
    ignored_paths: list[str] = Field(default_factory=list)
    core_modules: list[str] = Field(default_factory=list)
    fix_limits: FixLimitsOut = Field(default_factory=FixLimitsOut)


class TriageSettingsIn(BaseModel):
    setup_failed_enabled: bool | None = None
    missing_package_enabled: bool | None = None
    flaky_enabled: bool | None = None
    flaky_rerun_count: int | None = None
    ignored_paths: list[str] | None = None
    core_modules: list[str] | None = None
    fix_limits: FixLimitsOut | None = None


class AuditRowOut(BaseModel):
    id: UUID
    created_at: datetime
    actor_login: str | None = None
    action: str
    detail: str | None = None


@router.get("/members", response_model=list[MemberOut])
def list_members(
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    rows = db.scalars(
        select(OrgMembership)
        .options(joinedload(OrgMembership.user))
        .where(OrgMembership.org_id == auth.org.id)
        .order_by(OrgMembership.created_at.asc())
    ).unique()
    out: list[MemberOut] = []
    for m in rows:
        u = m.user
        pending = (u.github_id or "").startswith("pending:")
        out.append(
            MemberOut(
                user_id=u.id,
                github_login=u.github_login,
                name=u.name,
                role=m.role,
                is_you=u.id == auth.user.id,
                last_active=u.updated_at,
                invite_pending=pending,
            )
        )
    return out


@router.post("/members/invite", response_model=MemberOut)
def invite_member(
    body: InviteIn,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MemberOut:
    login = body.github_login.strip().lstrip("@").lower()
    if not login:
        raise HTTPException(status_code=400, detail="github_login required")
    if body.role not in {Role.admin, Role.developer}:
        raise HTTPException(status_code=400, detail="Invalid role")

    existing = db.scalar(select(User).where(User.github_login == login))
    if existing is None:
        existing = User(
            github_id=f"pending:{login}:{uuid4().hex[:8]}",
            github_login=login,
            name=None,
            is_active=True,
        )
        db.add(existing)
        db.flush()
    mem = db.scalar(
        select(OrgMembership).where(
            OrgMembership.org_id == auth.org.id,
            OrgMembership.user_id == existing.id,
        )
    )
    if mem is not None:
        raise HTTPException(status_code=409, detail="User already in org")
    mem = OrgMembership(org_id=auth.org.id, user_id=existing.id, role=body.role)
    db.add(mem)
    write_audit(
        db,
        org_id=auth.org.id,
        actor_user_id=auth.user.id,
        action="user.invited",
        detail=f"{login} role={body.role.value}",
    )
    db.commit()
    return MemberOut(
        user_id=existing.id,
        github_login=existing.github_login,
        name=existing.name,
        role=body.role,
        is_you=False,
        last_active=existing.updated_at,
        invite_pending=True,
    )


@router.patch("/members/{user_id}/role", response_model=MemberOut)
def set_member_role(
    user_id: UUID,
    body: RoleIn,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MemberOut:
    mem = db.scalar(
        select(OrgMembership)
        .options(joinedload(OrgMembership.user))
        .where(
            OrgMembership.org_id == auth.org.id,
            OrgMembership.user_id == user_id,
        )
    )
    if mem is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if mem.user_id == auth.user.id and body.role != Role.admin:
        raise HTTPException(
            status_code=400, detail="Cannot demote yourself from Admin"
        )
    old = mem.role.value
    mem.role = body.role
    write_audit(
        db,
        org_id=auth.org.id,
        actor_user_id=auth.user.id,
        action="user.role_change",
        detail=f"{mem.user.github_login} {old} → {body.role.value}",
    )
    db.commit()
    return MemberOut(
        user_id=mem.user.id,
        github_login=mem.user.github_login,
        name=mem.user.name,
        role=mem.role,
        is_you=mem.user.id == auth.user.id,
        last_active=mem.user.updated_at,
        invite_pending=(mem.user.github_id or "").startswith("pending:"),
    )


def _settings_from_rules(data: dict) -> TriageSettingsOut:
    nab = data.get("not_a_code_bug") or {}
    limits = data.get("fix_limits") or {}
    return TriageSettingsOut(
        setup_failed_enabled=bool((nab.get("setup_failed") or {}).get("enabled", True)),
        missing_package_enabled=bool(
            (nab.get("missing_package") or {}).get("enabled", True)
        ),
        flaky_enabled=bool((nab.get("flaky") or {}).get("enabled", True)),
        flaky_rerun_count=int((nab.get("flaky") or {}).get("rerun_count") or 2),
        ignored_paths=list(data.get("ignored_paths") or []),
        core_modules=list(data.get("core_modules") or []),
        fix_limits=FixLimitsOut(
            max_attempts=int(limits.get("max_attempts") or 3),
            max_files_changed=int(limits.get("max_files_changed") or 3),
        ),
    )


@router.get("/triage", response_model=TriageSettingsOut)
def get_triage_settings(
    auth: AuthContext = Depends(require_admin),
) -> TriageSettingsOut:
    return _settings_from_rules(load_rules())


@router.put("/triage", response_model=TriageSettingsOut)
def put_triage_settings(
    body: TriageSettingsIn,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TriageSettingsOut:
    data = dict(load_rules())
    nab = dict(data.get("not_a_code_bug") or {})
    if body.setup_failed_enabled is not None:
        setup = dict(nab.get("setup_failed") or {})
        setup["enabled"] = body.setup_failed_enabled
        nab["setup_failed"] = setup
    if body.missing_package_enabled is not None:
        miss = dict(nab.get("missing_package") or {})
        miss["enabled"] = body.missing_package_enabled
        nab["missing_package"] = miss
    if body.flaky_enabled is not None or body.flaky_rerun_count is not None:
        flaky = dict(nab.get("flaky") or {})
        if body.flaky_enabled is not None:
            flaky["enabled"] = body.flaky_enabled
        if body.flaky_rerun_count is not None:
            flaky["rerun_count"] = max(1, int(body.flaky_rerun_count))
        nab["flaky"] = flaky
    data["not_a_code_bug"] = nab
    if body.ignored_paths is not None:
        data["ignored_paths"] = [p.strip() for p in body.ignored_paths if p.strip()]
    if body.core_modules is not None:
        data["core_modules"] = [p.strip() for p in body.core_modules if p.strip()]
        write_audit(
            db,
            org_id=auth.org.id,
            actor_user_id=auth.user.id,
            action="settings.core_modules",
            detail=", ".join(data["core_modules"]) or "(cleared)",
        )
    if body.fix_limits is not None:
        data["fix_limits"] = {
            "max_attempts": max(1, min(10, int(body.fix_limits.max_attempts))),
            "max_files_changed": max(
                1, min(10, int(body.fix_limits.max_files_changed))
            ),
        }
        write_audit(
            db,
            org_id=auth.org.id,
            actor_user_id=auth.user.id,
            action="settings.fix_limits",
            detail=str(data["fix_limits"]),
        )

    RULES_PATH.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    clear_rules_cache()
    write_audit(
        db,
        org_id=auth.org.id,
        actor_user_id=auth.user.id,
        action="settings.triage_saved",
        detail="rules.yaml updated",
    )
    db.commit()
    return _settings_from_rules(load_rules())


@router.get("/audit", response_model=list[AuditRowOut])
def list_audit(
    limit: int = Query(100, ge=1, le=500),
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AuditRowOut]:
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.org_id == auth.org.id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all()
    # Resolve actor logins
    user_ids = {r.actor_user_id for r in rows if r.actor_user_id}
    users = {}
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            users[u.id] = u.github_login
    return [
        AuditRowOut(
            id=r.id,
            created_at=r.created_at,
            actor_login=users.get(r.actor_user_id) if r.actor_user_id else None,
            action=r.action,
            detail=r.detail,
        )
        for r in rows
    ]
