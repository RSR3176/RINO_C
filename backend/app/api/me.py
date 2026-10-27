from fastapi import APIRouter, Depends

from app.deps import AuthContext, require_admin, require_any_role, require_developer
from app.schemas import OrgOut, UserOut

router = APIRouter(prefix="/api", tags=["api"])


def _user_out(auth: AuthContext) -> UserOut:
    return UserOut(
        id=auth.user.id,
        github_login=auth.user.github_login,
        name=auth.user.name,
        email=auth.user.email,
        avatar_url=auth.user.avatar_url,
        role=auth.role,
        org=OrgOut.model_validate(auth.org),
    )


@router.get("/me", response_model=UserOut)
def me(auth: AuthContext = Depends(require_any_role)) -> UserOut:
    return _user_out(auth)


@router.get("/admin/ping", response_model=dict)
def admin_ping(auth: AuthContext = Depends(require_admin)) -> dict:
    return {"ok": True, "role": auth.role.value, "login": auth.user.github_login}


@router.get("/developer/ping", response_model=dict)
def developer_ping(auth: AuthContext = Depends(require_developer)) -> dict:
    return {"ok": True, "role": auth.role.value, "login": auth.user.github_login}
