from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    admin_repos,
    admin_settings,
    auth,
    findings,
    github_app_routes,
    health,
    me,
    performance,
    runs,
    testing,
)
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("rino")

settings = get_settings()

app = FastAPI(title="Rino API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url.rstrip("/")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(github_app_routes.router)
app.include_router(me.router)
app.include_router(admin_repos.router)
app.include_router(admin_settings.router)
app.include_router(runs.router)
app.include_router(findings.router)
app.include_router(testing.router)
app.include_router(performance.router)


@app.middleware("http")
async def require_session_cookie_on_api(request: Request, call_next):
    """Defense-in-depth: every /api/* call needs a session cookie.

    Handlers still enforce Admin/Developer via Depends(require_*).
    Public paths are /health and /auth/* only.
    """
    if request.url.path.startswith("/api/"):
        cookie_name = settings.session_cookie_name
        if not request.cookies.get(cookie_name):
            return JSONResponse(
                status_code=401, content={"detail": "Not authenticated"}
            )
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
