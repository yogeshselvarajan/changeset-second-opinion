"""The endpoint inventory agrees with the exported OpenAPI file and is internally consistent."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cso.api.deps import Role
from cso.api.inventory import (
    API_PREFIX,
    INVENTORY,
    ROOT_PATHS,
    inventory_keys,
    route_key,
)

CONTRACT = Path(__file__).parents[2] / "openapi" / "v1.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def test_inventory_size() -> None:
    assert len(INVENTORY) == 40


def test_no_duplicate_routes() -> None:
    keys = [(e.method, e.path) for e in INVENTORY]
    assert len(keys) == len(set(keys))


def test_paths_are_well_formed() -> None:
    for endpoint in INVENTORY:
        assert endpoint.path.startswith("/")
        assert not endpoint.path.endswith("/") or endpoint.path == "/"
        params = re.findall(r"\{([^}]+)\}", endpoint.path)
        assert params in ([], ["id"]), endpoint.path  # one parameter, always named `id`
        assert endpoint.method in {"GET", "POST", "PUT"}


def test_statuses_are_plausible() -> None:
    for endpoint in INVENTORY:
        assert endpoint.success, endpoint
        assert all(200 <= s < 400 for s in endpoint.success)  # the sign-in routes redirect
        assert all(400 <= s < 600 for s in endpoint.errors)
        assert len(set(endpoint.errors)) == len(endpoint.errors)


def test_roles_follow_the_contract() -> None:
    by_key = {(e.method, e.path): e for e in INVENTORY}
    assert by_key["GET", "/healthz"].role is None
    assert by_key["POST", "/auth/login"].role is None
    assert by_key["GET", "/decisions/export.csv"].role is Role.ADMIN
    assert by_key["GET", "/config/versions"].role is Role.ADMIN
    mutations = [e for e in INVENTORY if e.method in {"POST", "PUT"} and e.path.startswith("/")]
    exempt = {"/auth/login", "/auth/logout"}
    admin_only = {
        "/config/packs/{id}/activate",
        "/config/calibrate",
        "/settings",
        "/invites",
        "/invites/{id}/revoke",
    }
    assert all(e.role is Role.ADMIN for e in mutations if e.path in admin_only)
    assert all(e.role is Role.REVIEWER for e in mutations if e.path not in exempt | admin_only)
    reads = [e for e in INVENTORY if e.method == "GET" and e.role is Role.VIEWER]
    assert len(reads) >= 10


def test_mount_paths() -> None:
    health = next(e for e in INVENTORY if e.path == "/healthz")
    cases = next(e for e in INVENTORY if e.path == "/cases")
    assert health.full_path == "/healthz"
    assert cases.full_path == f"{API_PREFIX}/cases"
    assert ROOT_PATHS == {"/healthz", "/readyz", "/site.webmanifest"}


def test_route_key_ignores_parameter_names_and_prefix() -> None:
    assert route_key("get", "/api/v1/cases/{case_id}") == route_key("GET", "/cases/{id}")
    assert route_key("POST", "/cases/{id}/drafts") == ("POST", "/cases/{}/drafts")
    assert route_key("GET", "/healthz") == ("GET", "/healthz")


@pytest.mark.skipif(not CONTRACT.exists(), reason="openapi/v1.json not present")
def test_inventory_matches_the_contract_document() -> None:
    spec = json.loads(CONTRACT.read_text(encoding="utf-8"))
    documented = {
        route_key(method, path)
        for path, operations in spec["paths"].items()
        for method in operations
        if method in HTTP_METHODS
    }
    assert documented, "no operations found in openapi/v1.json"
    assert inventory_keys() == documented
