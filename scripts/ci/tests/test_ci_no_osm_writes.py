from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import check_no_osm_writes as check

Write = Callable[[str, str], Path]
SRC = "backend/src/cso/"


def messages(root: Path) -> list[str]:
    return [str(f) for f in check.check(root)]


def test_the_real_repository_passes(repo_root: Path) -> None:
    assert check.check(repo_root) == []


def test_http_post_to_osm_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        SRC + "bad.py",
        "import httpx\n"
        "async def go():\n"
        "    async with httpx.AsyncClient() as c:\n"
        "        await c.post('https://api.openstreetmap.org/api/0.6/changeset/create')\n",
    )
    found = messages(tmp_path)
    assert any("HTTP write call" in m and "bad.py:4" in m for m in found)
    assert any("OSM write endpoint" in m for m in found)


def test_put_patch_delete_are_flagged(tmp_path: Path, write: Write) -> None:
    for i, verb in enumerate(["put", "patch", "delete"]):
        write(SRC + f"w{i}.py", f"import requests\nrequests.{verb}('https://x.test/a')\n")
    found = messages(tmp_path)
    assert sum("HTTP write call" in m for m in found) == 3


def test_non_get_method_literal_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        SRC + "m.py",
        "import httpx\nc = httpx.Client()\nc.request('DELETE', 'https://x.test')\n",
    )
    assert any("non-GET method 'DELETE'" in m for m in messages(tmp_path))


def test_non_literal_method_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        SRC + "m.py",
        "import httpx\nc = httpx.Client()\nverb = 'GET'\nc.request(verb, 'u')\n",
    )
    assert any("non-literal method" in m for m in messages(tmp_path))


def test_request_with_a_body_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        SRC + "u.py",
        "import urllib.request\nurllib.request.urlopen(urllib.request.Request('u', data=b'x'))\n",
    )
    assert any("sends a body" in m for m in messages(tmp_path))


def test_oauth_write_scope_is_flagged_even_in_a_string(tmp_path: Path, write: Write) -> None:
    write(SRC + "s.py", "SCOPES = ['read_prefs', 'write_api']\n")
    assert any("OAuth write scope" in m for m in messages(tmp_path))


def test_decider_may_post_but_not_name_an_osm_host(tmp_path: Path, write: Write) -> None:
    write(
        SRC + "adapters/decider/client.py",
        "import httpx\nc = httpx.Client()\nc.post('http://127.0.0.1:8099/v1/systemone')\n",
    )
    assert messages(tmp_path) == []
    write(
        SRC + "adapters/decider/leak.py",
        "URL = 'https://api.openstreetmap.org/api/0.6/map'\n",
    )
    assert any("must not name an OSM host" in m for m in messages(tmp_path))


def test_get_requests_router_decorators_and_caches_are_not_flagged(
    tmp_path: Path, write: Write
) -> None:
    write(
        SRC + "adapters/osm/client.py",  # a module that may own a client (F-M10)
        "import httpx\n"
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.post('/cases')\n"
        "async def create():\n"
        "    return 1\n"
        "@router.delete('/x')\n"
        "async def remove():\n"
        "    return 1\n"
        "class Cache:\n"
        "    def put(self, k, v):\n"
        "        return None\n"
        "cache = Cache()\n"
        "cache.put('a', 1)\n"
        "c = httpx.Client()\n"
        "c.get('https://api.openstreetmap.org/api/0.6/map')\n"
        "c.request('GET', 'https://api.openstreetmap.org/api/0.6/map')\n",
    )
    assert messages(tmp_path) == []


def test_a_missing_source_tree_is_not_an_error(tmp_path: Path) -> None:
    assert check.check(tmp_path) == []


def test_main_exit_codes(tmp_path: Path, write: Write) -> None:
    assert check.main(["--root", str(tmp_path)]) == 0
    write(SRC + "bad.py", "import requests\nrequests.post('u')\n")
    assert check.main(["--root", str(tmp_path)]) == 1


# ------------------------------------------------ review F-M10: evasions that used to pass


def test_send_of_a_hand_built_post_request_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        SRC + "e1.py",
        "import httpx\n"
        "async def go(c):\n"
        "    await c.send(\n"
        "        httpx.Request('POST', 'https://api.openstreetmap.org/x', content=b'y'))\n",
    )
    found = messages(tmp_path)
    assert any(".send(" in m for m in found)
    assert any("Request(...)" in m and "non-GET method 'POST'" in m for m in found)


def test_a_write_call_on_an_attribute_receiver_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        SRC + "e2.py",
        "import httpx\nclass A:\n    def __init__(self, c):\n        self._c = c\n"
        "    async def go(self):\n        await self._c.post('https://x.test')\n",
    )
    assert any("HTTP write call" in m and "self._c.post" in m for m in messages(tmp_path))


def test_getattr_that_builds_the_write_method_name_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        SRC + "e3.py",
        "import httpx\nasync def go(c):\n    await getattr(c, 'po' + 'st')('https://x.test')\n",
    )
    assert any("getattr" in m for m in messages(tmp_path))
    write(SRC + "e4.py", "import httpx\nasync def go(c):\n    getattr(c, 'post')('u')\n")
    assert any("e4.py" in m and "getattr" in m for m in messages(tmp_path))


def test_a_client_created_outside_the_owning_modules_is_flagged(
    tmp_path: Path, write: Write
) -> None:
    write(SRC + "e5.py", "import httpx as h\nc = h.AsyncClient()\n")
    assert any("e5.py" in m and "created outside" in m for m in messages(tmp_path))
    write(SRC + "e6.py", "from httpx import Client\nc = Client()\n")
    assert any("e6.py" in m and "created outside" in m for m in messages(tmp_path))
    # the same creation inside the OSM client module is the sanctioned place
    write(SRC + "adapters/osm/client.py", "import httpx\nc = httpx.AsyncClient()\n")
    assert not any("adapters/osm/client.py" in m for m in messages(tmp_path))


def test_settings_driven_allowed_hosts_are_flagged(tmp_path: Path, write: Write) -> None:
    write(
        SRC + "adapters/osm/other.py",
        "class C:\n    def __init__(self, settings):\n"
        "        super().__init__(allowed_hosts=frozenset({settings.osm_host}))\n",
    )
    assert any("allowed_hosts" in m for m in messages(tmp_path))
    write(
        SRC + "adapters/osm/fine.py",
        "HOST = 'api.openstreetmap.org'\nclass C:\n    def __init__(self):\n"
        "        super().__init__(allowed_hosts=frozenset({HOST}))\n",
    )
    assert not any("fine.py" in m for m in messages(tmp_path))


def test_get_only_requests_and_the_safe_client_pattern_are_not_flagged(
    tmp_path: Path, write: Write
) -> None:
    write(
        SRC + "adapters/osm/client.py",
        "import httpx\nclass SafeGetClient:\n    def __init__(self):\n"
        "        self._http = httpx.AsyncClient()\n"
        "    async def go(self):\n"
        "        req = httpx.Request('GET', 'https://api.openstreetmap.org/api/0.6/map')\n"
        "        return await self._http.send(req)\n",
    )
    assert messages(tmp_path) == []


def test_a_write_call_on_a_function_parameter_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        SRC + "e7.py", "import httpx\nasync def go(client_like):\n    await client_like.put('u')\n"
    )
    assert any("e7.py" in m and "HTTP write call" in m for m in messages(tmp_path))


OAUTH = SRC + "adapters/osm/oauth.py"
TOKEN_LITERAL = "https://www.openstreetmap.org/oauth2/token"  # noqa: S105 (a URL)
OAUTH_HEAD = (
    "import httpx\n"
    f"TOKEN_URL = '{TOKEN_LITERAL}'\n"
    "USER_URL = 'https://api.openstreetmap.org/api/0.6/user/details.json'\n"
    "class OsmTokenClient:\n"
    "    def __init__(self):\n"
    "        self._http = httpx.AsyncClient()\n"
)


def test_the_token_exchange_is_the_one_allowed_post(tmp_path: Path, write: Write) -> None:
    write(
        OAUTH,
        OAUTH_HEAD
        + "    async def exchange(self, code):\n"
        + "        await self._http.post(TOKEN_URL, data={'code': code})\n"
        + "        return await self._http.get(USER_URL)\n",
    )
    assert messages(tmp_path) == []


def test_a_second_token_post_is_flagged(tmp_path: Path, write: Write) -> None:
    write(
        OAUTH,
        OAUTH_HEAD
        + "    async def exchange(self, code):\n"
        + "        await self._http.post(TOKEN_URL, data={'code': code})\n"
        + "        await self._http.post(TOKEN_URL, data={'code': code})\n",
    )
    assert any("second POST to the OSM token endpoint" in m for m in messages(tmp_path))


def test_any_other_post_in_the_oauth_module_is_flagged(tmp_path: Path, write: Write) -> None:
    for call in [
        "self._http.post(USER_URL, data={})",
        "self._http.post('https://api.openstreetmap.org/api/0.6/changeset/create')",
        "self._http.put(TOKEN_URL)",
        "self._http.delete(TOKEN_URL)",
        "self._http.patch(TOKEN_URL)",
        "self._http.post(url)",
    ]:
        write(OAUTH, OAUTH_HEAD + f"    async def go(self, url):\n        await {call}\n")
        assert any("HTTP write call" in m for m in messages(tmp_path)), call


def test_a_post_through_another_receiver_in_the_oauth_module_is_flagged(
    tmp_path: Path, write: Write
) -> None:
    write(
        OAUTH,
        OAUTH_HEAD
        + "    async def go(self):\n"
        + "        other = httpx.AsyncClient()\n"
        + "        await other.post(TOKEN_URL)\n",
    )
    assert any("HTTP write call" in m for m in messages(tmp_path))


def test_a_method_picked_at_run_time_in_the_oauth_module_is_flagged(
    tmp_path: Path, write: Write
) -> None:
    write(
        OAUTH,
        OAUTH_HEAD
        + "    async def go(self, verb):\n"
        + "        await self._http.request(verb, TOKEN_URL)\n"
        + "        await self._http.request('POST', TOKEN_URL)\n",
    )
    found = messages(tmp_path)
    assert any("non-literal method" in m for m in found)
    assert any("non-GET method 'POST'" in m for m in found)


def test_the_token_constant_must_stay_the_token_endpoint(tmp_path: Path, write: Write) -> None:
    write(
        OAUTH,
        OAUTH_HEAD.replace(TOKEN_LITERAL, "https://api.openstreetmap.org/api/0.6/changeset/create")
        + "    async def go(self):\n        await self._http.post(TOKEN_URL)\n",
    )
    assert any("must be the OSM token endpoint" in m for m in messages(tmp_path))
    write(
        OAUTH,
        OAUTH_HEAD
        + "    async def go(self):\n        await self._http.post(TOKEN_URL)\n"
        + "TOKEN_URL = 'https://www.openstreetmap.org/oauth2/other'\n",
    )
    assert any("assigned exactly once" in m for m in messages(tmp_path))


def test_the_token_endpoint_cannot_be_named_in_any_other_file(tmp_path: Path, write: Write) -> None:
    write(SRC + "api/elsewhere.py", f"URL = '{TOKEN_LITERAL}'\n")
    assert any("named outside oauth.py" in m for m in messages(tmp_path))


def test_the_exception_does_not_extend_to_the_decider_or_the_get_client(
    tmp_path: Path, write: Write
) -> None:
    write(
        SRC + "adapters/osm/client.py",
        "import httpx\nTOKEN_URL = 'x'\nclass C:\n    def __init__(self):\n"
        "        self._http = httpx.AsyncClient()\n    async def go(self):\n"
        "        await self._http.post(TOKEN_URL)\n",
    )
    assert any("HTTP write call" in m for m in messages(tmp_path))
