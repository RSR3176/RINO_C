from __future__ import annotations

import json
import logging
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import github_app as ghapp
from app.auth.session import read_session_token
from app.config import Settings, get_settings
from app.database import get_db
from app.deps import AuthContext, require_admin
from app.models import GithubInstallation, OrgMembership
from app import repo_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["github-app"])


def _state_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        settings.session_secret, salt="rino-ghapp-install-v1"
    )


def _frontend(settings: Settings, path: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}{path}"


def get_current_auth_optional(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    rino_session: str | None = Cookie(default=None, alias="rino_session"),
) -> AuthContext | None:
    if not rino_session:
        return None
    payload = read_session_token(settings, rino_session)
    if not payload:
        return None
    try:
        user_id = UUID(payload["uid"])
        org_id = UUID(payload["oid"])
    except (KeyError, ValueError):
        return None
    membership = db.scalar(
        select(OrgMembership)
        .options(joinedload(OrgMembership.user), joinedload(OrgMembership.org))
        .where(
            OrgMembership.user_id == user_id,
            OrgMembership.org_id == org_id,
        )
    )
    if membership is None or not membership.user.is_active:
        return None
    return AuthContext(
        user=membership.user,
        org=membership.org,
        membership=membership,
        role=membership.role,
    )


@router.get("/auth/github-app/install")
def start_install(
    auth: AuthContext = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Admin-only redirect into the GitHub App install flow."""
    if not settings.github_app_slug:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GITHUB_APP_SLUG is not configured",
        )
    state = _state_serializer(settings).dumps(
        {"org": str(auth.org.id), "uid": str(auth.user.id)}
    )
    url = settings.github_app_install_url(state=state)
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/auth/github-app/callback")
@router.get("/auth/github-app/setup")
async def github_app_setup_callback(
    installation_id: int | None = Query(default=None),
    setup_action: str | None = Query(default=None),
    state: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    auth: AuthContext | None = Depends(get_current_auth_optional),
) -> RedirectResponse:
    """GitHub redirects here after App install / update (Setup URL)."""
    if not installation_id:
        return RedirectResponse(
            _frontend(settings, "/admin?error=missing_installation"),
            status_code=status.HTTP_302_FOUND,
        )

    org_id: UUID | None = None
    actor_id: UUID | None = None
    if state:
        try:
            payload = _state_serializer(settings).loads(state, max_age=3600)
            org_id = UUID(payload["org"])
            actor_id = UUID(payload["uid"])
        except (BadSignature, SignatureExpired, KeyError, ValueError):
            logger.warning("Invalid GitHub App install state")

    if org_id is None and auth is not None:
        org_id = auth.org.id
        actor_id = auth.user.id

    if org_id is None:
        return RedirectResponse(
            _frontend(settings, "/admin?error=install_session"),
            status_code=status.HTTP_302_FOUND,
        )

    if not settings.github_app_configured():
        return RedirectResponse(
            _frontend(settings, "/admin?error=app_not_configured"),
            status_code=status.HTTP_302_FOUND,
        )

    try:
        installation = await ghapp.get_installation(settings, installation_id)
    except Exception:
        logger.exception("Failed to fetch GitHub App installation")
        return RedirectResponse(
            _frontend(settings, "/admin?error=install_lookup"),
            status_code=status.HTTP_302_FOUND,
        )

    account = installation.get("account") or {}
    suspended = bool(
        installation.get("suspended_at") or installation.get("suspended_by")
    )
    repo_service.upsert_installation(
        db,
        org_id=org_id,
        installation_id=int(installation["id"]),
        account_login=account.get("login") or "unknown",
        account_type=account.get("type") or "Organization",
        account_id=str(account["id"]) if account.get("id") is not None else None,
        suspended=suspended,
    )
    repo_service.write_audit(
        db,
        org_id=org_id,
        actor_user_id=actor_id,
        action="github_app.installed",
        detail=(
            f"installation_id={installation_id} "
            f"account={account.get('login')} action={setup_action or 'install'}"
        ),
    )
    db.commit()

    return RedirectResponse(
        _frontend(settings, "/admin?installed=1"),
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict:
    """GitHub App webhooks: installation + workflow_run (Step 8).

    Signature required when ``GITHUB_APP_WEBHOOK_SECRET`` is set. For local
    development, expose the backend with ngrok and point the App's webhook URL
    at ``https://<ngrok>/webhooks/github``.
    """
    from app.git.webhooks import WorkflowRunEvent, parse_webhook, verify_github_signature
    from app.models import AnalysisRun

    body = await request.body()
    secret = (settings.github_app_webhook_secret or "").strip()
    if secret:
        if not verify_github_signature(body, x_hub_signature_256, secret):
            raise HTTPException(status_code=401, detail="Invalid signature")
    elif settings.github_app_configured():
        # Soft warn — allow unsigned only when secret unset (local/dev)
        logger.warning("GITHUB_APP_WEBHOOK_SECRET unset; accepting unsigned webhook")

    event = x_github_event or "unknown"
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    parsed = parse_webhook(event, payload)

    if event == "ping":
        return {"ok": True, "pong": True}

    if event == "installation":
        action = payload.get("action")
        installation = payload.get("installation") or {}
        installation_id = installation.get("id")
        account = installation.get("account") or {}
        logger.info(
            "GitHub webhook installation action=%s installation_id=%s account=%s",
            action,
            installation_id,
            account.get("login"),
        )
        if installation_id:
            row = db.scalar(
                select(GithubInstallation).where(
                    GithubInstallation.installation_id == int(installation_id)
                )
            )
            if row is not None:
                if action == "deleted":
                    for repo in repo_service.list_connected_repos(db, row.org_id):
                        repo_service.apply_status(
                            repo, repo.test_config, accessible=False
                        )
                    db.delete(row)
                elif action == "suspend":
                    row.suspended = True
                elif action == "unsuspend":
                    row.suspended = False
                db.commit()
        return {"ok": True, "event": event}

    if isinstance(parsed, WorkflowRunEvent):
        # Publish to Redis so GitHubActionsRunner polling can short-circuit
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            key = f"rino:workflow_run:{parsed.run_id}"
            client.hset(
                key,
                mapping={
                    "status": parsed.status,
                    "conclusion": parsed.conclusion or "",
                    "head_branch": parsed.head_branch,
                    "head_sha": parsed.head_sha,
                    "repository": parsed.repository_full_name,
                    "action": parsed.action,
                },
            )
            client.expire(key, 3600)
        except Exception:
            logger.exception("Failed to cache workflow_run in Redis")

        # Correlate to an in-flight AnalysisRun when we know the run id
        if parsed.status == "completed" and parsed.run_id:
            arun = db.scalar(
                select(AnalysisRun).where(
                    AnalysisRun.github_workflow_run_id == parsed.run_id
                )
            )
            if arun is not None:
                logger.info(
                    "workflow_run completed for analysis_run=%s gh_run=%s conclusion=%s",
                    arun.id,
                    parsed.run_id,
                    parsed.conclusion,
                )

        return {
            "ok": True,
            "event": event,
            "workflow_run_id": parsed.run_id,
            "status": parsed.status,
            "conclusion": parsed.conclusion,
        }

    return {"ok": True, "event": event}
