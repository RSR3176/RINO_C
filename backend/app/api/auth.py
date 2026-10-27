from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.auth.github import (
    build_authorize_url,
    exchange_code_for_token,
    fetch_github_user,
)
from app.auth.session import issue_session_token
from app.config import Settings, get_settings
from app.database import get_db
from app.deps import AuthContext, get_current_auth
from app.services import (
    ensure_bootstrap_admin,
    get_membership_for_github_user,
    refresh_user_profile,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _oauth_state_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="rino-oauth-state-v1")


def _frontend(settings: Settings, path: str, **params: str) -> str:
    base = settings.frontend_url.rstrip("/")
    if params:
        return f"{base}{path}?{urlencode(params)}"
    return f"{base}{path}"


@router.get("/github/login")
def github_login(
    role_hint: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth is not configured",
        )
    nonce = secrets.token_urlsafe(24)
    hint = role_hint if role_hint in {"admin", "developer"} else "developer"
    state = _oauth_state_serializer(settings).dumps({"n": nonce, "role_hint": hint})
    url = build_authorize_url(settings, state=state)
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/github/callback")
async def github_callback(
    response: Response,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error:
        logger.warning("GitHub OAuth error: %s", error)
        return RedirectResponse(
            _frontend(settings, "/", error="oauth_denied"),
            status_code=status.HTTP_302_FOUND,
        )
    if not code or not state:
        return RedirectResponse(
            _frontend(settings, "/", error="oauth_invalid"),
            status_code=status.HTTP_302_FOUND,
        )

    try:
        _oauth_state_serializer(settings).loads(state, max_age=600)
    except (BadSignature, SignatureExpired):
        return RedirectResponse(
            _frontend(settings, "/", error="oauth_state"),
            status_code=status.HTTP_302_FOUND,
        )

    try:
        access_token = await exchange_code_for_token(settings, code)
        profile = await fetch_github_user(access_token)
    except Exception:
        logger.exception("GitHub OAuth callback failed")
        return RedirectResponse(
            _frontend(settings, "/", error="oauth_failed"),
            status_code=status.HTTP_302_FOUND,
        )
    # Do not log or persist the OAuth access token.
    del access_token

    membership = get_membership_for_github_user(
        db,
        str(profile["github_id"]),
        github_login=str(profile.get("github_login") or ""),
    )
    if membership is None:
        membership = ensure_bootstrap_admin(db, settings, profile)

    if membership is None:
        logger.info(
            "Unknown GitHub user attempted login: login=%s",
            profile.get("github_login"),
        )
        return RedirectResponse(
            _frontend(settings, "/no-access"),
            status_code=status.HTTP_302_FOUND,
        )

    refresh_user_profile(db, membership.user, profile)
    try:
        from app.repo_service import write_audit

        write_audit(
            db,
            org_id=membership.org_id,
            actor_user_id=membership.user_id,
            action="auth.login",
            detail="GitHub OAuth",
        )
        db.commit()
    except Exception:
        logger.exception("Failed to write login audit")
        db.rollback()

    token = issue_session_token(
        settings,
        user_id=membership.user_id,
        org_id=membership.org_id,
        role=membership.role.value,
    )
    redirect_path = "/admin" if membership.role.value == "admin" else "/app"
    redirect = RedirectResponse(
        _frontend(settings, redirect_path),
        status_code=status.HTTP_302_FOUND,
    )
    redirect.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.session_max_age_seconds,
        path="/",
    )
    return redirect


@router.post("/logout")
def logout(
    settings: Settings = Depends(get_settings),
    _auth: AuthContext = Depends(get_current_auth),
) -> Response:
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    resp.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
    )
    return resp


@router.post("/logout-public")
def logout_public(settings: Settings = Depends(get_settings)) -> Response:
    """Clear cookie even when session is already invalid."""
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    resp.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
    )
    return resp
