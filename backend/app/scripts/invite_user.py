"""Invite a GitHub user into the default org with a role.

Usage:
  python -m app.scripts.invite_user --login octocat --role developer
  python -m app.scripts.invite_user --login octocat --role admin --github-id 583231
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Org, OrgMembership, Role, User


async def resolve_github_id(login: str) -> str:
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json"}
    # Prefer unauthenticated public lookup; optionally use OAuth app credentials
    # only as Basic for rate limit — never log secrets.
    auth = None
    if settings.github_client_id and settings.github_client_secret:
        auth = (settings.github_client_id, settings.github_client_secret)
    async with httpx.AsyncClient(timeout=20.0, auth=auth) as client:
        resp = await client.get(f"https://api.github.com/users/{login}", headers=headers)
        resp.raise_for_status()
        return str(resp.json()["id"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Invite a GitHub user to Rino")
    parser.add_argument("--login", required=True, help="GitHub username")
    parser.add_argument(
        "--role",
        choices=["admin", "developer"],
        default="developer",
    )
    parser.add_argument("--github-id", default=None, help="Numeric GitHub user id")
    parser.add_argument(
        "--org-slug",
        default=None,
        help="Org slug (default: DEFAULT_ORG_SLUG)",
    )
    args = parser.parse_args()
    settings = get_settings()
    slug = args.org_slug or settings.default_org_slug
    role = Role(args.role)

    github_id = args.github_id
    if not github_id:
        try:
            github_id = asyncio.run(resolve_github_id(args.login))
        except Exception as exc:
            print(f"Could not resolve GitHub id for {args.login}: {exc}", file=sys.stderr)
            sys.exit(1)

    db = SessionLocal()
    try:
        org = db.scalar(select(Org).where(Org.slug == slug))
        if org is None:
            org = Org(name=settings.default_org_name, slug=slug)
            db.add(org)
            db.flush()

        user = db.scalar(select(User).where(User.github_id == str(github_id)))
        if user is None:
            user = User(
                github_id=str(github_id),
                github_login=args.login,
                is_active=True,
            )
            db.add(user)
            db.flush()
        else:
            user.github_login = args.login
            user.is_active = True

        membership = db.scalar(
            select(OrgMembership).where(
                OrgMembership.org_id == org.id,
                OrgMembership.user_id == user.id,
            )
        )
        if membership is None:
            membership = OrgMembership(org_id=org.id, user_id=user.id, role=role)
            db.add(membership)
        else:
            membership.role = role

        db.commit()
        print(f"OK: {args.login} is {role.value} in org '{org.slug}'")
    finally:
        db.close()


if __name__ == "__main__":
    main()
