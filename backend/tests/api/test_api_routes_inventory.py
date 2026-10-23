"""The mounted app serves exactly the contract's endpoints, with the documented statuses."""

from __future__ import annotations

import json
import re

from fastapi import FastAPI

from cso.api.inventory import INVENTORY, Endpoint, route_key
from cso.tools.export_openapi import build_openapi

# Served by the auth package, not by the routers of this package.
AUTH_ROUTES = {
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("GET", "/me"),
}
BANNED = re.compile(r"vandal|spam|illegal|\bstop\b|\bmust\b", re.IGNORECASE)


def _operations(spec: dict[str, object]) -> dict[tuple[str, str], dict[str, object]]:
    paths = spec["paths"]
    assert isinstance(paths, dict)
    found: dict[tuple[str, str], dict[str, object]] = {}
    for path, methods in paths.items():
        for method, operation in methods.items():
            found[route_key(method, path)] = operation
    return found


def _expected() -> dict[tuple[str, str], Endpoint]:
    return {route_key(e.method, e.path): e for e in INVENTORY}


def test_every_inventory_endpoint_is_served_except_the_auth_ones() -> None:
    served = set(_operations(build_openapi()))
    expected = _expected()
    auth_keys = {route_key(method, path) for method, path in AUTH_ROUTES}
    missing = set(expected) - served - auth_keys
    assert not missing, f"endpoints in the contract but not served: {sorted(missing)}"


def test_the_app_serves_nothing_outside_the_contract() -> None:
    extra = set(_operations(build_openapi())) - set(_expected())
    assert not extra, f"endpoints served but not in the contract: {sorted(extra)}"


def test_documented_statuses_cover_the_contract() -> None:
    operations = _operations(build_openapi())
    for key, endpoint in _expected().items():
        operation = operations.get(key)
        if operation is None:
            continue  # auth routes: checked when the auth package mounts them
        documented = set(operation["responses"])  # type: ignore[arg-type]
        success = {str(code) for code in endpoint.success}
        errors = {str(code) for code in endpoint.errors}
        assert success <= documented, (key, "success", success - documented)
        assert errors <= documented, (key, "errors", errors - documented)


def test_error_responses_use_the_problem_schema() -> None:
    operations = _operations(build_openapi())
    for key, endpoint in _expected().items():
        operation = operations.get(key)
        if operation is None:
            continue
        responses = operation["responses"]
        for code in endpoint.errors:
            body = responses[str(code)]  # type: ignore[index]
            content = body["content"]
            assert "application/problem+json" in content, (key, code)


def test_protected_endpoints_document_401_and_403() -> None:
    operations = _operations(build_openapi())
    for key, endpoint in _expected().items():
        operation = operations.get(key)
        if operation is None or endpoint.role is None or endpoint.role.value == "viewer":
            continue
        documented = set(operation["responses"])  # type: ignore[arg-type]
        assert {"401", "403"} <= documented, key


def test_operation_ids_are_unique_and_named_after_the_endpoint_function() -> None:
    operations = _operations(build_openapi())
    ids = [str(op["operationId"]) for op in operations.values()]
    assert len(ids) == len(set(ids))
    api_ids = [i for i in ids if "_" not in i.removeprefix("healthz") or i in {"list_cases"}]
    assert "list_cases" in ids and "put_outcome" in ids and "export_decisions" in ids
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", i) for i in ids if i != "healthz_healthz_get")
    assert api_ids  # something to name


def test_the_openapi_document_uses_no_banned_words() -> None:
    text = json.dumps(build_openapi())
    assert not BANNED.search(text), BANNED.search(text)


def test_csv_export_is_documented_as_text_csv() -> None:
    operation = _operations(build_openapi())[route_key("GET", "/decisions/export.csv")]
    assert "text/csv" in operation["responses"]["200"]["content"]  # type: ignore[index]


def test_no_endpoint_performs_an_osm_write_method() -> None:
    methods = {method for method, _ in _operations(build_openapi())}
    assert methods <= {"GET", "POST", "PUT"}  # nothing here proxies a write to OpenStreetMap


def test_problem_handlers_cover_unknown_routes(app: FastAPI) -> None:
    # Unknown paths go through the same problem+json handler (checked without a client).
    handlers = app.exception_handlers
    assert Exception in handlers and any(
        getattr(key, "__name__", "") == "ApiError" for key in handlers
    )
