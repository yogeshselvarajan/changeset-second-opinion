# syntax=docker/dockerfile:1
# Backend image for the API, the worker, migrations and the seed command (one image, four commands).
# Build context is the repository root (see docker-compose.yml): the image carries the backend
# source plus config/ and the replay fixtures, so nothing outside the image is needed at runtime.
#
# Base images are pinned by tag and digest. To refresh: pick the new tag on Docker Hub, copy the
# index digest, change both here. Last checked 2026-10-20 (python 3.13.16, uv 0.12.1).

FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

# Build stage: resolves and installs the locked dependencies into /opt/venv. It never ships.
FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Dependencies first, so a source change does not reinstall them.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
COPY backend/alembic.ini ./alembic.ini
# The package metadata names these files (readme, licence) and the demo fixtures it bundles.
COPY backend/README.md backend/LICENSE ./
COPY backend/fixtures/demo ./fixtures/demo
COPY backend/fixtures/schema.md ./fixtures/schema.md
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Runtime stage: Python, the virtual environment and the application files. No uv, no build tools.
FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS runtime
LABEL org.opencontainers.image.title="cso-backend" \
      org.opencontainers.image.description="Changeset Second Opinion: API, worker and CLI" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/yogeshselvarajan/changeset-second-opinion"
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CSO_COMMUNITY_CONFIG=/app/config/communities/default.yaml \
    CSO_FIXTURES_DIR=/app/fixtures/demo
# Fixed uid and gid 10001: the AWS bootstrap script chowns the host data folder to it.
# /data is the only place the process writes (the SQLite file, its journal files).
RUN groupadd --system --gid 10001 cso \
    && useradd --system --uid 10001 --gid cso --no-create-home --home-dir /nonexistent \
       --shell /usr/sbin/nologin cso \
    && install -d -o cso -g cso -m 0750 /data
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
COPY config /app/config
COPY backend/fixtures /app/fixtures
USER 10001:10001
EXPOSE 8000
VOLUME ["/data"]
STOPSIGNAL SIGTERM
ENTRYPOINT ["cso"]
CMD ["api", "--host", "127.0.0.1"]
