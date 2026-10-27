from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def build_authorize_url(settings: Settings, *, state: str) -> str:
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": f"{settings.backend_url.rstrip('/')}/auth/github/callback",
        "scope": "read:user user:email",
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_token(settings: Settings, code: str) -> str:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": f"{settings.backend_url.rstrip('/')}/auth/github/callback",
            },
        )
        resp.raise_for_status()
        payload = resp.json()

    # Never log the token or client secret.
    access_token = payload.get("access_token")
    if not access_token:
        error = payload.get("error", "unknown_error")
        logger.warning("GitHub token exchange failed: %s", error)
        raise RuntimeError("GitHub OAuth token exchange failed")
    return str(access_token)


async def fetch_github_user(access_token: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        user_resp = await client.get(GITHUB_USER_URL, headers=headers)
        user_resp.raise_for_status()
        user = user_resp.json()

        email = user.get("email")
        if not email:
            emails_resp = await client.get(GITHUB_EMAILS_URL, headers=headers)
            if emails_resp.status_code == 200:
                emails = emails_resp.json()
                primary = next(
                    (e for e in emails if e.get("primary") and e.get("verified")),
                    None,
                )
                email = (primary or (emails[0] if emails else {})).get("email")

    return {
        "github_id": str(user["id"]),
        "github_login": user["login"],
        "name": user.get("name"),
        "email": email,
        "avatar_url": user.get("avatar_url"),
    }
