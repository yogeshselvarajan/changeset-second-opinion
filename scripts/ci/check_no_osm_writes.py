#!/usr/bin/env python3
"""Invariant 1: no code path writes to OpenStreetMap.

Static scan of `backend/src` (Python AST plus string search). It fails on:
  * a write-method call (`post`, `put`, `patch`, `delete`) on an HTTP client, in any file that
    imports an HTTP library or whose receiver looks like a client, except the Decider adapter,
    which POSTs to the loopback model server and must never mention an OSM host;
  * `request`, `build_request` or `stream` with a method that is not a literal GET/HEAD/OPTIONS;
  * `urlopen` or `Request` carrying a body (`data=`), which makes a POST;
  * `send(...)` on a client, and `Request(...)` objects with a non-GET or non-literal method
    (`client.send(httpx.Request("POST", ...))` bypasses the method checks above);
  * a write-method call on ANY receiver (`self._c.post(...)`) in a file that imports an HTTP
    library;
  * `getattr` that can pick a write method (a literal write name, or a non-literal name) in such a
    file (`getattr(c, "po" + "st")`);
  * an HTTP client created outside the few modules that own one (`CLIENT_MODULES`), so only the
    `SafeGetClient` family (exact host allowlist, GET only) can ever reach an OSM host;
  * an `allowed_hosts=` argument that is not made of literal host constants (settings-driven hosts);
  * an OSM OAuth write scope string, or an OSM write endpoint, anywhere in the source.
One narrow exception (ADR-011, sign in with OpenStreetMap): `adapters/osm/oauth.py` may make
exactly one `self._http.post(TOKEN_URL, ...)` where `TOKEN_URL` is assigned once to the OSM token
endpoint; any other write call in it, a second token POST, or the token path in another file fails.
FastAPI route decorators (`@router.post(...)`) are not HTTP clients and are ignored.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from common import Finding, iter_files, rel, run_main

HTTP_MODULES = frozenset(
    {
        "httpx",
        "requests",
        "urllib",
        "urllib3",
        "aiohttp",
        "http",
        "pycurl",
        "websockets",
    }
)
WRITE_METHODS = frozenset({"post", "put", "patch", "delete"})
REQUEST_METHODS = frozenset({"request", "build_request", "stream"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The Decider adapter POSTs to the local model server; it is allowed to, and only to.
POST_ALLOWED_PREFIXES = ("backend/src/cso/adapters/decider/",)
# Sign in with OpenStreetMap (ADR-011): this one module may make exactly one POST, to the OSM
# token endpoint, with the scope `read_prefs`. It is not in POST_ALLOWED_PREFIXES because those
# files may not name an OSM host; this one has to. Everything else in it is checked as usual.
OAUTH_MODULE = "backend/src/cso/adapters/osm/oauth.py"
OAUTH_TOKEN_URL = "https://www.openstreetmap.org/oauth2/token"  # noqa: S105 (a URL)
OAUTH_TOKEN_CONSTANT = "TOKEN_URL"  # noqa: S105 (a name)
OAUTH_TOKEN_PATH = "/oauth2/token"  # noqa: S105 (a path)
# Modules that may create an HTTP client: the GET-only OSM client family (which enforces the host
# allowlist), the loopback Decider client, and two health probes that only GET.
CLIENT_MODULES = frozenset(
    {
        "backend/src/cso/adapters/osm/client.py",
        OAUTH_MODULE,
        "backend/src/cso/adapters/decider/client.py",
        "backend/src/cso/main.py",
        "backend/src/cso/observability/readiness.py",
    }
)
CLIENT_FACTORIES = frozenset(
    {"AsyncClient", "Client", "Session", "ClientSession", "PoolManager", "HTTPConnection",
     "HTTPSConnection", "AsyncHTTPTransport", "HTTPTransport"}
)  # fmt: skip
DISPATCH_METHODS = frozenset({"send"}) | WRITE_METHODS | REQUEST_METHODS
CLIENT_RECEIVER = re.compile(r"http|client|requests|httpx|osm|aiohttp", re.IGNORECASE)
OSM_HOST = re.compile(r"(?:openstreetmap\.org|maproulette\.org|\bosm\.org)", re.IGNORECASE)
OAUTH_WRITE_SCOPES = re.compile(
    r"\b(write_api|write_notes|write_prefs|write_diary|write_gpx|write_redactions)\b"
)
OSM_WRITE_ENDPOINT = re.compile(
    r"/api/0\.6/(?:changeset/create|changeset/\d+/(?:upload|close|comment|subscribe|unsubscribe)"
    r"|(?:node|way|relation)/create|user/preferences|gpx/create)"
)


def _imports_http(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in HTTP_MODULES for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in HTTP_MODULES:
                return True
    return False


def _root_name(node: ast.AST) -> str:
    """Leftmost identifier of an expression such as `await httpx.AsyncClient().post(...)`."""
    while True:
        if isinstance(node, ast.Await):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Attribute):
            node = node.value
        else:
            break
    return node.id if isinstance(node, ast.Name) else ""


def _http_names(tree: ast.AST) -> set[str]:
    """Module aliases, imported classes and variables bound from them (`c = httpx.Client()`)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name.split(".")[0]
                for alias in node.names
                if alias.name.split(".")[0] in HTTP_MODULES
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in HTTP_MODULES:
                names.update(alias.asname or alias.name for alias in node.names)
    for _ in range(2):  # two passes cover one level of aliasing
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and _root_name(node.value) in names:
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                if _root_name(node.value) in names and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
            elif isinstance(node, ast.With | ast.AsyncWith):
                for item in node.items:
                    if _root_name(item.context_expr) in names and isinstance(
                        item.optional_vars, ast.Name
                    ):
                        names.add(item.optional_vars.id)
    return names


def _decorator_calls(tree: ast.AST) -> set[int]:
    """ids of Call nodes used as decorators (FastAPI `@router.post(...)`)."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    ids.add(id(decorator))
    return ids


def _receiver_text(func: ast.Attribute) -> str:
    try:
        return ast.unparse(func.value)
    except Exception:  # pragma: no cover - unparse failing is not worth a crash
        return ""


def _method_argument(call: ast.Call) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == "method":
            return keyword.value
    return call.args[0] if call.args else None


def _is_constant_host(node: ast.AST) -> bool:
    """A literal host, a CONSTANT_NAME, or a set/tuple/list/frozenset of those."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.Name):
        return node.id.isupper()
    if isinstance(node, ast.Set | ast.Tuple | ast.List):
        return all(_is_constant_host(e) for e in node.elts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in {"frozenset", "set", "tuple"} and all(
            _is_constant_host(a) for a in node.args
        )
    return False


def _method_problem(method: ast.expr | None) -> str | None:
    if isinstance(method, ast.Constant) and isinstance(method.value, str):
        return (
            None
            if method.value.upper() in SAFE_METHODS
            else f"non-GET method {method.value!r} sent"
        )
    return None if method is None else "a non-literal method"


def _is_token_post(node: ast.Call, receiver: str) -> bool:
    """`self._http.post(TOKEN_URL, ...)`: the one POST the sign-in module may make."""
    first = node.args[0] if node.args else None
    return (
        receiver == "self._http"
        and isinstance(first, ast.Name)
        and first.id == OAUTH_TOKEN_CONSTANT
    )


def _check_token_constant(tree: ast.AST, path: str) -> list[Finding]:
    """In the sign-in module `TOKEN_URL` is assigned once, to the OSM token endpoint literal."""
    assigned: list[ast.stmt] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == OAUTH_TOKEN_CONSTANT for t in targets):
            assigned.append(node)  # type: ignore[arg-type]
    if len(assigned) != 1:
        line = assigned[1].lineno if len(assigned) > 1 else 1
        return [Finding(path, line, f"`{OAUTH_TOKEN_CONSTANT}` must be assigned exactly once")]
    stmt = assigned[0]
    value = getattr(stmt, "value", None)
    if not (
        isinstance(stmt, ast.Assign | ast.AnnAssign)
        and isinstance(value, ast.Constant)
        and value.value == OAUTH_TOKEN_URL
    ):
        return [
            Finding(path, stmt.lineno, f"`{OAUTH_TOKEN_CONSTANT}` must be the OSM token endpoint")
        ]
    return []


def _scan_calls(
    tree: ast.AST,
    path: str,
    imports_http: bool,
    allowed: bool,
    *,
    client_module: bool = False,
    oauth_module: bool = False,
) -> list[Finding]:
    findings: list[Finding] = []
    token_posts = 0
    skip = _decorator_calls(tree)
    http_names = _http_names(tree)
    params = {
        a.arg
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
        for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
        if a.arg not in {"self", "cls"}
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in skip:
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            receiver = _receiver_text(func)
            clientish = _root_name(func) in http_names or bool(CLIENT_RECEIVER.search(receiver))
            # once the file talks HTTP, attribute receivers (`self._c.post(...)`) and function
            # parameters (`def go(c): c.post(...)`) count as clients; a plain local name does not
            # (`cache.put(...)`)
            opaque = isinstance(func.value, ast.Attribute) or _root_name(func) in params
            writer = clientish or (imports_http and opaque)
            if func.attr in WRITE_METHODS and writer and not allowed:
                if oauth_module and func.attr == "post" and _is_token_post(node, receiver):
                    token_posts += 1
                    if token_posts > 1:
                        findings.append(
                            Finding(path, node.lineno, "a second POST to the OSM token endpoint")
                        )
                else:
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            f"HTTP write call `{receiver}.{func.attr}(...)`",
                        )
                    )
            if func.attr == "send" and (clientish or imports_http) and not allowed:
                if not client_module:
                    findings.append(
                        Finding(path, node.lineno, f"`{receiver}.send(...)` can send any request")
                    )
            if func.attr in REQUEST_METHODS and clientish and not allowed:
                method = _method_argument(node)
                problem = _method_problem(method)
                if problem is not None:
                    detail = (
                        problem
                        if problem.startswith("non-GET")
                        else f"`{func.attr}` with {problem}"
                    )
                    findings.append(Finding(path, node.lineno, detail))
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in {"urlopen", "Request"} and imports_http and not allowed:
            if any(k.arg == "data" for k in node.keywords):
                findings.append(Finding(path, node.lineno, f"`{name}(data=...)` sends a body"))
        if name == "Request" and imports_http and not allowed:
            # httpx.Request(method, url, ...) takes the method first; urllib's takes `method=`
            keyword = next((k.value for k in node.keywords if k.arg == "method"), None)
            httpx_style = _root_name(func) == "httpx" or name in http_names
            method = (
                keyword
                if keyword is not None
                else (node.args[0] if httpx_style and node.args else None)
            )
            problem = _method_problem(method)
            if problem is not None:
                findings.append(Finding(path, node.lineno, f"`Request(...)` with {problem}"))
        if name == "getattr" and imports_http and not allowed and len(node.args) >= 2:
            attr = node.args[1]
            literal = isinstance(attr, ast.Constant) and isinstance(attr.value, str)
            if (literal and attr.value in DISPATCH_METHODS) or not literal:  # type: ignore[attr-defined]
                findings.append(
                    Finding(path, node.lineno, "`getattr` can pick an HTTP write method")
                )
        if name in CLIENT_FACTORIES and imports_http and not client_module:
            if _root_name(func) in http_names:
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        f"HTTP client `{name}` created outside the modules that own one "
                        "(use SafeGetClient)",
                    )
                )
        for keyword in node.keywords:
            if keyword.arg == "allowed_hosts" and not _is_constant_host(keyword.value):
                findings.append(
                    Finding(path, node.lineno, "`allowed_hosts` must be literal host constants")
                )
    return findings


def _scan_strings(text: str, path: str, allowed: bool) -> list[Finding]:
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if OAUTH_WRITE_SCOPES.search(line):
            findings.append(Finding(path, number, "OSM OAuth write scope"))
        if OSM_WRITE_ENDPOINT.search(line):
            findings.append(Finding(path, number, "OSM write endpoint"))
        if allowed and OSM_HOST.search(line):
            findings.append(Finding(path, number, "the Decider adapter must not name an OSM host"))
        if OAUTH_TOKEN_PATH in line and path != OAUTH_MODULE:
            findings.append(
                Finding(path, number, "the OSM token endpoint is named outside oauth.py")
            )
    return findings


def check(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for file in iter_files(root / "backend" / "src", (".py",)):
        path = rel(file, root)
        text = file.read_text(encoding="utf-8")
        allowed = path.startswith(POST_ALLOWED_PREFIXES)
        findings.extend(_scan_strings(text, path, allowed))
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as exc:
            findings.append(Finding(path, exc.lineno or 1, "file does not parse"))
            continue
        findings.extend(
            _scan_calls(
                tree,
                path,
                _imports_http(tree),
                allowed,
                client_module=path in CLIENT_MODULES,
                oauth_module=path == OAUTH_MODULE,
            )
        )
        if path == OAUTH_MODULE:
            findings.extend(_check_token_constant(tree, path))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    return run_main("check_no_osm_writes", check, sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
