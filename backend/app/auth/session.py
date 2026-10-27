from __future__ import annotations

from typing import Any
from uuid import UUID

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        settings.session_secret, salt="rino-session-v1"
    )


def issue_session_token(
    settings: Settings,
    *,
    user_id: UUID,
    org_id: UUID,
    role: str,
) -> str:
    payload = {
        "uid": str(user_id),
        "oid": str(org_id),
        "role": role,
    }
    return _serializer(settings).dumps(payload)


def read_session_token(settings: Settings, token: str) -> dict[str, Any] | None:
    try:
        data = _serializer(settings).loads(
            token, max_age=settings.session_max_age_seconds
        )
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("uid") or not data.get("oid") or not data.get("role"):
        return None
    return data
