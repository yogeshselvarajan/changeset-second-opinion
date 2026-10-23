"""Suite-wide fixtures."""

from __future__ import annotations

import pytest

from cso.settings import get_settings


@pytest.fixture(autouse=True)
def _no_ambient_osm_signin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's `backend/.env` may hold real OpenStreetMap sign-in settings; tests must not
    pick them up. Tests that exercise the feature override the settings dependency instead."""
    for name in (
        "CSO_OSM_OAUTH_CLIENT_ID",
        "CSO_OSM_OAUTH_CLIENT_SECRET",
        "CSO_OSM_OAUTH_REDIRECT_URL",
        "CSO_OSM_SIGNIN_ALLOWED_UIDS",
        "CSO_WEB_BASE_URL",
    ):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
