# Third-party notices

Code in this repository is licensed under Apache-2.0 (see [`LICENSE`](LICENSE)). It depends on the
third-party software below. Nothing here is vendored except the two font files and their licence
texts under `web/src/fonts/`.

Generated on 2026-10-17 and updated by hand on 2026-10-23 to remove `osmcha` and the five packages
that only it required. Python: runtime packages from `backend/uv.lock`
(`uv export --frozen --no-dev --no-emit-project --no-hashes`), licences read with
`pip-licenses --from=mixed` from the project environment. JavaScript: production packages from
`web/package-lock.json` (`npx license-checker --production --json`). Licence names come from package
metadata and have **not** been audited by a lawyer; where a package declares more than one licence the
text is copied as declared. Regenerate with those commands after any lockfile change.

## Removed GPL dependency

Earlier versions depended on `osmcha` 0.9.2, which is GPL-3.0-or-later. It has been removed from
`backend/pyproject.toml` and `backend/uv.lock`, together with `requests`, `numpy`, `shapely` and
`charset-normalizer`, which only it required. The eight stage-1 flags are now computed by
`backend/src/cso/adapters/osm/flags.py`, which is original code under Apache-2.0. Its suspect word
list, `backend/src/cso/adapters/osm/suspect_words.txt`, was written for this project and is not
derived from the word data of any other tool. The element-count thresholds in that module are this
project's own choices. A test fails if any module under `backend/src` imports `osmcha`.

## Items that need a human decision or attention

| Item | Declared licence | Why it matters |
|---|---|---|
| `psycopg`, `psycopg-binary`, `psycopg-pool` 3.3.x (runtime, Python) | LGPL-3.0-only | Stays LGPL and is used unmodified through normal imports for the optional Postgres path (SQLite is the default). Distributing an image that contains them carries LGPL notice obligations. |
| `certifi` (runtime, Python) | MPL-2.0 | Unmodified; file-level copyleft only. |
| `lightningcss` 1.32 and 1.33 (JavaScript) | MPL-2.0 | Build-time CSS compiler pulled in by Tailwind. Not part of the shipped bundle. |
| `uvloop` (runtime, Python, Linux and macOS only) | not checked here | Not installed on the Windows generation environment, so its licence was not read. PyPI lists a permissive dual licence; verify before relying on it. |

## Curated entries

| Component | Licence | Where |
|---|---|---|
| Inter (variable, latin subset) | SIL OFL 1.1 | `web/src/fonts/inter-latin-wght-normal.woff2`, licence text `web/src/fonts/Inter-OFL.txt` |
| JetBrains Mono (variable, latin subset) | SIL OFL 1.1 | `web/src/fonts/jetbrains-mono-latin-wght-normal.woff2`, licence text `web/src/fonts/JetBrainsMono-OFL.txt` |
| Fraunces (variable, latin subset, from @fontsource-variable/fraunces 5.3.0) | SIL OFL 1.1 | `web/src/fonts/fraunces-latin-wght-normal.woff2`, licence text `web/src/fonts/Fraunces-OFL.txt` |
| MapLibre GL JS 6.14.0 | BSD-3-Clause | loaded only when a reviewer opens the optional map |
| React Aria Components 1.22.1 | Apache-2.0 | UI primitives |
| Strands Agents SDK 1.61.1 | Apache-2.0 | drafting agent and gate hook |
| Strands Decider 0.1.0 (Python package) | Apache-2.0 per the repository documentation; not re-checked here | separate server process |
| Decider model `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610` | Apache-2.0 (model card read via the Hugging Face API on 2026-10-17); base model `Qwen/Qwen3.5-2B-Base` (licence not checked here) | weights are downloaded at runtime and are not in this repository |
| Amazon Bedrock models (Claude Haiku 4.5) | AWS service terms and the model provider's terms | optional, guarded; see README |

## Data

- OpenStreetMap data and anything derived from it (recorded fixtures, changeset ids and statistics in
  `evaluation/`, the optional map): © OpenStreetMap contributors, available under the
  [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/). See
  <https://www.openstreetmap.org/copyright>.
- Synthetic fixtures (changeset ids from 900000000000): CC0 1.0 (`backend/fixtures/README.md`).
- Map tiles for the optional map come from OpenFreeMap, which carries its own attribution, shown in the
  map. Not audited here.

## Python runtime packages (76)

| Package | Version | Licence | URL |
|---|---|---|---|
| aiosqlite | 0.22.1 | MIT | https://aiosqlite.omnilib.dev |
| alembic | 1.20.0 | MIT | https://alembic.sqlalchemy.org |
| annotated-doc | 0.0.5 | MIT | https://github.com/fastapi/annotated-doc |
| annotated-types | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.15.1 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| argon2-cffi | 25.1.0 | MIT | https://github.com/hynek/argon2-cffi/blob/main/CHANGELOG.md |
| argon2-cffi-bindings | 26.1.0 | MIT | https://github.com/hynek/argon2-cffi-bindings/blob/main/CHANGELOG.md |
| attrs | 26.1.0 | MIT | https://www.attrs.org/en/stable/changelog.html |
| boto3 | 1.43.114 | Apache-2.0 | https://github.com/boto/boto3 |
| botocore | 1.43.114 | Apache-2.0 | https://github.com/boto/botocore |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi | 2.1.1 | MIT-0 | https://cffi.readthedocs.io/en/latest/whatsnew.html |
| click | 8.5.0 | BSD-3-Clause | https://github.com/pallets/click/ |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| defusedxml | 0.7.1 | PSF-2.0 | https://github.com/tiran/defusedxml |
| docstring_parser | 0.18.0 | MIT | https://github.com/rr-/docstring_parser |
| fastapi | 0.143.3 | MIT | https://github.com/fastapi/fastapi |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | https://greenlet.readthedocs.io |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| h2 | 4.4.1 | MIT | https://github.com/python-hyper/h2/ |
| hpack | 4.2.0 | MIT | https://github.com/python-hyper/hpack/ |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httptools | 0.9.0 | MIT | https://github.com/MagicStack/httptools |
| httpx | 0.28.1 | BSD (see package) | https://github.com/encode/httpx |
| httpx-sse | 0.4.3 | MIT | https://github.com/florimondmanca/httpx-sse |
| hyperframe | 6.1.0 | MIT | https://github.com/python-hyper/hyperframe/ |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| jmespath | 1.1.0 | MIT | https://github.com/jmespath/jmespath.py |
| jsonschema | 4.26.0 | MIT | https://github.com/python-jsonschema/jsonschema |
| jsonschema-specifications | 2025.9.1 | MIT | https://github.com/python-jsonschema/jsonschema-specifications |
| Mako | 1.4.3 | MIT | https://www.makotemplates.org/ |
| MarkupSafe | 3.0.4 | BSD-3-Clause | https://github.com/pallets/markupsafe/ |
| mcp | 1.30.0 | MIT | https://modelcontextprotocol.io |
| opentelemetry-api | 1.45.1 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api |
| opentelemetry-instrumentation | 0.66b1 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/opentelemetry-instrumentation |
| opentelemetry-instrumentation-threading | 0.66b1 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python-contrib/instrumentation/opentelemetry-instrumentation-threading |
| opentelemetry-sdk | 1.45.1 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-sdk |
| opentelemetry-semantic-conventions | 0.66b1 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-semantic-conventions |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| psycopg | 3.3.6 | LGPL-3.0-only | https://psycopg.org/ |
| psycopg-binary | 3.3.6 | LGPL-3.0-only | https://psycopg.org/ |
| psycopg-pool | 3.3.3 | LGPL-3.0-only | https://psycopg.org/ |
| pycparser | 3.11 | BSD-3-Clause | https://github.com/eliben/pycparser |
| pydantic | 2.14.1 | MIT | https://github.com/pydantic/pydantic |
| pydantic_core | 2.50.1 | MIT | https://github.com/pydantic |
| pydantic-settings | 2.16.0 | MIT | https://github.com/pydantic/pydantic-settings |
| PyJWT | 2.15.1 | MIT | https://github.com/jpadilla/pyjwt |
| python-dateutil | 2.9.0.post0 | Apache Software License; BSD License | https://github.com/dateutil/dateutil |
| python-dotenv | 1.2.4 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| python-multipart | 0.0.32 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| pywin32 | 312 | PSF-2.0 | https://github.com/mhammond/pywin32 |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org/ |
| referencing | 0.37.0 | MIT | https://github.com/python-jsonschema/referencing |
| rpds-py | 2026.9.1 | MIT | https://github.com/crate-py/rpds |
| s3transfer | 0.19.2 | Apache-2.0 | https://github.com/boto/s3transfer |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| SQLAlchemy | 2.0.55 | MIT | https://www.sqlalchemy.org |
| sse-starlette | 3.5.0 | BSD-3-Clause | https://github.com/sysid/sse-starlette |
| starlette | 1.8.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| strands-agents | 1.61.1 | Apache-2.0 | https://github.com/strands-agents/harness-sdk |
| structlog | 26.1.0 | MIT OR Apache-2.0 | https://github.com/hynek/structlog/blob/main/CHANGELOG.md |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| typing-inspection | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection |
| tzdata | 2026.5 | Apache-2.0 | https://github.com/python/tzdata |
| urllib3 | 2.8.0 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| uvicorn | 0.54.0 | BSD-3-Clause | https://uvicorn.dev/ |
| uvloop | 0.23.0 | not checked here (not installed on the generation platform) | |
| watchdog | 6.0.0 | Apache-2.0 | https://github.com/gorakhargosh/watchdog |
| watchfiles | 1.3.0 | MIT | https://github.com/samuelcolvin/watchfiles |
| websockets | 17.2 | BSD-3-Clause | https://github.com/python-websockets/websockets |
| wrapt | 2.5.1 | BSD-2-Clause | https://github.com/GrahamDumpleton/wrapt |

## JavaScript production packages (86)

| Package | Licence | Repository |
|---|---|---|
| @internationalized/date@3.12.4 | Apache-2.0 | https://github.com/adobe/react-spectrum/tree/main/packages/@internationalized/date |
| @internationalized/number@3.6.9 | Apache-2.0 | https://github.com/adobe/react-spectrum |
| @internationalized/string@3.2.10 | Apache-2.0 | https://github.com/adobe/react-spectrum |
| @jridgewell/gen-mapping@0.3.13 | MIT | https://github.com/jridgewell/sourcemaps |
| @jridgewell/remapping@2.3.5 | MIT | https://github.com/jridgewell/sourcemaps |
| @jridgewell/resolve-uri@3.1.2 | MIT | https://github.com/jridgewell/resolve-uri |
| @jridgewell/sourcemap-codec@1.6.0 | MIT | https://github.com/jridgewell/sourcemaps |
| @jridgewell/trace-mapping@0.3.31 | MIT | https://github.com/jridgewell/sourcemaps |
| @mapbox/jsonlint-lines-primitives@2.0.3 | MIT | https://github.com/mapbox/jsonlint |
| @mapbox/point-geometry@1.1.0 | ISC | https://github.com/mapbox/point-geometry |
| @mapbox/tiny-sdf@2.3.0 | BSD-2-Clause | https://github.com/mapbox/tiny-sdf |
| @mapbox/unitbezier@1.0.0 | BSD-2-Clause | https://github.com/mapbox/unitbezier |
| @mapbox/vector-tile@3.0.0 | BSD-3-Clause | https://github.com/mapbox/vector-tile-js |
| @maplibre/geojson-vt@6.3.0 | ISC | https://github.com/maplibre/geojson-vt |
| @maplibre/maplibre-gl-style-spec@26.4.4 | ISC | https://github.com/maplibre/maplibre-style-spec |
| @maplibre/mlt@1.3.0 | (MIT OR Apache-2.0) | https://github.com/maplibre/maplibre-tile-spec |
| @maplibre/vt-pbf@4.3.2 | MIT | https://github.com/maplibre/vt-pbf |
| @oxc-project/types@0.154.0 | MIT | https://github.com/oxc-project/oxc |
| @react-types/shared@3.37.0 | Apache-2.0 | https://github.com/adobe/react-spectrum |
| @rolldown/binding-win32-x64-msvc@1.2.14 | MIT | https://github.com/rolldown/rolldown |
| @rolldown/pluginutils@1.0.1 | MIT | https://github.com/rolldown/plugins |
| @swc/helpers@0.5.23 | Apache-2.0 | https://github.com/swc-project/swc |
| @tailwindcss/node@4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |
| @tailwindcss/oxide-win32-x64-msvc@4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |
| @tailwindcss/oxide@4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |
| @tailwindcss/vite@4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |
| @tanstack/history@1.162.5 | MIT | https://github.com/TanStack/router |
| @tanstack/query-core@5.104.3 | MIT | https://github.com/TanStack/query |
| @tanstack/react-query@5.104.3 | MIT | https://github.com/TanStack/query |
| @tanstack/react-router@1.170.45 | MIT | https://github.com/TanStack/router |
| @tanstack/react-store@0.11.2 | MIT | https://github.com/TanStack/store |
| @tanstack/router-core@1.171.38 | MIT | https://github.com/TanStack/router |
| @tanstack/store@0.11.2 | MIT | https://github.com/TanStack/store |
| @types/geojson@7946.0.16 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/node@26.6.5 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| aria-hidden@1.2.6 | MIT | https://github.com/theKashey/aria-hidden |
| bidi-js@1.1.0 | MIT | https://github.com/lojjic/bidi-js |
| client-only@0.0.1 | MIT |  |
| clsx@2.1.1 | MIT | https://github.com/lukeed/clsx |
| cookie-es@3.1.1 | MIT | https://github.com/unjs/cookie-es |
| detect-libc@2.1.2 | Apache-2.0 | https://github.com/lovell/detect-libc |
| earcut@3.2.4 | ISC | https://github.com/mapbox/earcut |
| enhanced-resolve@5.26.0 | MIT | https://github.com/webpack/enhanced-resolve |
| fdir@6.5.0 | MIT | https://github.com/thecodrr/fdir |
| gl-matrix@3.4.4 | MIT | https://github.com/toji/gl-matrix |
| graceful-fs@4.2.11 | ISC | https://github.com/isaacs/node-graceful-fs |
| isbot@5.2.2 | Unlicense | https://github.com/omrilotan/isbot |
| jiti@2.7.0 | MIT | https://github.com/unjs/jiti |
| json-stringify-pretty-compact@4.0.0 | MIT | https://github.com/lydell/json-stringify-pretty-compact |
| kdbush@4.1.0 | ISC | https://github.com/mourner/kdbush |
| lightningcss-win32-x64-msvc@1.32.0 | MPL-2.0 | https://github.com/parcel-bundler/lightningcss |
| lightningcss-win32-x64-msvc@1.33.0 | MPL-2.0 | https://github.com/parcel-bundler/lightningcss |
| lightningcss@1.32.0 | MPL-2.0 | https://github.com/parcel-bundler/lightningcss |
| lightningcss@1.33.0 | MPL-2.0 | https://github.com/parcel-bundler/lightningcss |
| magic-string@0.30.21 | MIT | https://github.com/Rich-Harris/magic-string |
| maplibre-gl@6.14.0 | BSD-3-Clause | https://github.com/maplibre/maplibre-gl-js |
| minimist@1.2.8 | MIT | https://github.com/minimistjs/minimist |
| murmurhash-js@1.0.0 | MIT | https://github.com/mikolalysenko/murmurhash-js |
| nanoid@3.3.20 | MIT | https://github.com/ai/nanoid |
| pbf@5.1.2 | BSD-3-Clause | https://github.com/mapbox/pbf |
| picocolors@1.1.1 | ISC | https://github.com/alexeyraspopov/picocolors |
| picomatch@4.0.7 | MIT | https://github.com/micromatch/picomatch |
| postcss@8.5.30 | MIT | https://github.com/postcss/postcss |
| potpack@2.1.0 | ISC | https://github.com/mapbox/potpack |
| protocol-buffers-schema@3.6.1 | MIT | https://github.com/mafintosh/protocol-buffers-schema |
| quickselect@3.0.0 | ISC | https://github.com/mourner/quickselect |
| react-aria-components@1.22.1 | Apache-2.0 | https://github.com/adobe/react-spectrum |
| react-aria@3.53.1 | Apache-2.0 | https://github.com/adobe/react-spectrum |
| react-dom@19.3.1 | MIT | https://github.com/react/react |
| react-stately@3.51.0 | Apache-2.0 | https://github.com/adobe/react-spectrum |
| react@19.3.1 | MIT | https://github.com/react/react |
| require-from-string@2.0.2 | MIT | https://github.com/floatdrop/require-from-string |
| resolve-protobuf-schema@2.1.0 | MIT | https://github.com/mafintosh/resolve-protobuf-schema |
| rolldown@1.2.14 | MIT | https://github.com/rolldown/rolldown |
| scheduler@0.28.0 | MIT | https://github.com/react/react |
| seroval-plugins@1.6.9 | MIT | https://github.com/lxsmnsyc/seroval |
| seroval@1.6.9 | MIT | https://github.com/lxsmnsyc/seroval |
| source-map-js@1.2.2 | BSD-3-Clause | https://github.com/7rulnik/source-map-js |
| tailwindcss@4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |
| tapable@2.3.3 | MIT | https://github.com/webpack/tapable |
| tinyglobby@0.2.17 | MIT | https://github.com/SuperchupuDev/tinyglobby |
| tinyqueue@3.0.0 | ISC | https://github.com/mourner/tinyqueue |
| tslib@2.8.1 | 0BSD | https://github.com/Microsoft/tslib |
| undici-types@8.9.0 | MIT | https://github.com/nodejs/undici |
| use-sync-external-store@1.7.0 | MIT | https://github.com/react/react |
| vite@8.3.4 | MIT | https://github.com/vitejs/vite |
