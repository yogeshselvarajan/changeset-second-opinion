from __future__ import annotations

from pathlib import Path

import pytest

import validate_caddy as caddy


def test_the_real_caddyfile_strips_to_something_stock_caddy_accepts(repo_root: Path) -> None:
    text = (repo_root / "infra" / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    stripped = caddy.strip_rate_limit(text)
    directives = [
        line.strip() for line in stripped.splitlines() if not line.lstrip().startswith("#")
    ]
    assert not any(line.startswith("order rate_limit") for line in directives)
    assert "rate_limit {" not in directives
    assert stripped.count("{") == stripped.count("}")
    assert "import cso_rate_auth" in stripped and "import cso_rate_api" in stripped


def test_only_the_module_directives_are_removed() -> None:
    text = (
        "{\n\torder rate_limit before basicauth\n\tadmin off\n}\n"
        "(snip) {\n\trate_limit {\n\t\tzone z {\n\t\t\tevents 1\n\t\t}\n\t}\n}\n"
        "site {\n\timport snip\n\tencode gzip\n}\n"
    )
    out = caddy.strip_rate_limit(text)
    assert out == "{\n\tadmin off\n}\n(snip) {\n}\nsite {\n\timport snip\n\tencode gzip\n}\n"


def test_an_unbalanced_block_is_an_error_not_a_silent_truncation() -> None:
    with pytest.raises(ValueError, match="unbalanced"):
        caddy.strip_rate_limit("rate_limit {\n\tzone z {\n")


def test_the_real_caddyfile_keeps_the_rules_the_audit_asked_for(repo_root: Path) -> None:
    text = (repo_root / "infra" / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    for needle in (
        "@static path /favicon.ico /favicon.svg",
        "/robots.txt /sitemap.xml /og.png",
        "handle /site.webmanifest {",  # answered by the API so it follows the workspace name
        'Cache-Control "public, max-age=31536000, immutable"',
        '?Cache-Control "no-cache"',
        'Cross-Origin-Opener-Policy "same-origin"',
        'Cross-Origin-Resource-Policy "same-origin"',
        "max_size 64KB",
        "max_size 1MB",
        "events 1\n",
        "events 10\n",
        "'unsafe-inline' on purpose",
        "try_files {path} {path}/index.html /_shell.html",
        "rewrite * /404.html",
    ):
        assert needle in text, needle
    # the rate limit lives only in the API handlers, never on the static or fallback handlers
    static_part = text[text.index("handle /assets/*") :]
    assert "cso_rate_" not in static_part
