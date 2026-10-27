from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import jwt

from app.config import Settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def build_app_jwt(settings: Settings) -> str:
    private_key = settings.resolve_github_app_private_key()
    if not settings.github_app_id or not private_key:
        raise RuntimeError("GitHub App credentials are not configured")
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 9 * 60,
        "iss": settings.github_app_id,
    }
    # Never log the private key or JWT.
    return jwt.encode(payload, private_key, algorithm="RS256")


def create_installation_token_sync(
    settings: Settings, installation_id: int
) -> str:
    app_jwt = build_app_jwt(settings)
    url = f"{GITHUB_API}/app/installations/{installation_id}/access_tokens"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            url,
            headers={**API_HEADERS, "Authorization": f"Bearer {app_jwt}"},
        )
        if resp.status_code >= 400:
            logger.warning(
                "Failed to create installation token: status=%s", resp.status_code
            )
            resp.raise_for_status()
        token = resp.json().get("token")
    if not token:
        raise RuntimeError("GitHub did not return an installation token")
    return str(token)


async def create_installation_token(
    settings: Settings, installation_id: int
) -> str:
    return create_installation_token_sync(settings, installation_id)


async def get_installation(
    settings: Settings, installation_id: int
) -> dict[str, Any]:
    app_jwt = build_app_jwt(settings)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{GITHUB_API}/app/installations/{installation_id}",
            headers={**API_HEADERS, "Authorization": f"Bearer {app_jwt}"},
        )
        resp.raise_for_status()
        return resp.json()


async def list_installation_repositories(
    settings: Settings, installation_id: int
) -> list[dict[str, Any]]:
    token = await create_installation_token(settings, installation_id)
    repos: list[dict[str, Any]] = []
    page = 1
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                resp = await client.get(
                    f"{GITHUB_API}/installation/repositories",
                    headers={
                        **API_HEADERS,
                        "Authorization": f"Bearer {token}",
                    },
                    params={"per_page": 100, "page": page},
                )
                resp.raise_for_status()
                payload = resp.json()
                batch = payload.get("repositories") or []
                repos.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
    finally:
        del token
    return repos


async def get_repo_file(
    settings: Settings,
    installation_id: int,
    full_name: str,
    path: str,
    ref: str | None = None,
) -> dict[str, Any] | None:
    token = await create_installation_token(settings, installation_id)
    params = {"ref": ref} if ref else None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{full_name}/contents/{path.lstrip('/')}",
                headers={**API_HEADERS, "Authorization": f"Bearer {token}"},
                params=params,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
    finally:
        del token


async def list_repo_workflows(
    settings: Settings, installation_id: int, full_name: str
) -> list[dict[str, Any]]:
    token = await create_installation_token(settings, installation_id)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{full_name}/actions/workflows",
                headers={**API_HEADERS, "Authorization": f"Bearer {token}"},
                params={"per_page": 100},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return list(resp.json().get("workflows") or [])
    finally:
        del token


async def list_repo_runners(
    settings: Settings, installation_id: int, full_name: str
) -> list[dict[str, Any]]:
    token = await create_installation_token(settings, installation_id)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{full_name}/actions/runners",
                headers={**API_HEADERS, "Authorization": f"Bearer {token}"},
                params={"per_page": 100},
            )
            if resp.status_code in {404, 403}:
                return []
            resp.raise_for_status()
            return list(resp.json().get("runners") or [])
    finally:
        del token
