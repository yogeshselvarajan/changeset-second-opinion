"""Router factory and the role dependencies shared by every v1 router."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from cso.api.deps import Principal, Role, require_role


def unique_operation_id(route: APIRoute) -> str:
    """Operation id = the endpoint function name, so the generated client has stable names."""
    return route.name


def make_router(**kwargs: Any) -> APIRouter:
    """An `APIRouter` whose operations get stable ids."""
    return APIRouter(generate_unique_id_function=unique_operation_id, **kwargs)


_require_reviewer = require_role(Role.REVIEWER)

Viewer = Annotated[Principal, Depends(require_role(Role.VIEWER))]
Reviewer = Annotated[Principal, Depends(_require_reviewer)]
# First in a route's `dependencies`, so the role check runs before quotas take tokens (F-L9).
# It is the same callable as `Reviewer`, so FastAPI resolves it once per request.
ReviewerFirst = Depends(_require_reviewer)
Admin = Annotated[Principal, Depends(require_role(Role.ADMIN))]


def actor_of(principal: Principal) -> str:
    """Audit actor for a caller: `reviewer:<name>`, `admin:<name>` or `anonymous`."""
    if principal.anonymous:
        return "anonymous"
    return f"{principal.role.value}:{principal.display_name or principal.id}"
