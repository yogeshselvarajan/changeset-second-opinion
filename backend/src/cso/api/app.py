"""Wiring: every v1 router under `/api/v1`, `/readyz` at the root, problem+json for all errors."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from cso.api.auth import router as auth_router
from cso.api.auth_osm import router as osm_router
from cso.api.inventory import API_PREFIX
from cso.api.problems import install_problem_handlers
from cso.api.routing import make_router
from cso.api.security import install_security
from cso.api.v1 import actions, cases, config, decisions, health, receipts, records, workspace


def create_api_router() -> APIRouter:
    """All routers of the contract; auth routes (`/auth/*`, `/me`) come from the auth package."""
    root = make_router()
    root.include_router(health.router)  # /readyz at the application root
    root.include_router(workspace.root_router)  # /site.webmanifest at the application root
    v1 = make_router(prefix=API_PREFIX)
    for module in (cases, actions, records, decisions, config, receipts, workspace):
        v1.include_router(module.router)
    v1.include_router(auth_router)  # /auth/login, /auth/logout, /me
    v1.include_router(osm_router)  # /auth/osm/start, /auth/osm/callback
    root.include_router(v1)
    return root


def mount_api(app: FastAPI) -> None:
    """Install problem+json, the security middleware and the API router (called by `create_app`)."""
    install_problem_handlers(app)
    install_security(app)  # the lifespan sets app.state.auth_config once settings validate
    app.include_router(create_api_router())
