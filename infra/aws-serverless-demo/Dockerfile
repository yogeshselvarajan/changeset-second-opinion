# syntax=docker/dockerfile:1
# SPIKE. Replay-only demo API for AWS Lambda behind the Lambda Web Adapter (arm64 or amd64).
# Build context is the repository root:
#   docker build -f infra/aws-serverless-demo/Dockerfile -t cso-lwa-api:local .
#   docker buildx build --platform linux/arm64 -f infra/aws-serverless-demo/Dockerfile -t cso-lwa-api:arm64 --load .
#
# Same base images and digests as infra/compose/backend.Dockerfile. Differences:
#   - the Lambda Web Adapter is copied in as a Lambda extension (one line);
#   - the demo database is migrated and seeded at BUILD time (cso db upgrade, cso seed), then shipped
#     read-only under /var/task/data. run.sh copies it to /tmp when an instance starts, because SQLite
#     in WAL mode needs a writable folder next to the file;
#   - no worker (CSO_JOBS_WORKER_ENABLED=false), no Decider, no Bedrock, no sign-in settings.
# Lambda runs the image as its own unprivileged user and ignores USER; files are world readable.

FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

# Lambda Web Adapter 1.1.0: multi-arch image (x86_64 and arm64); Docker picks the right one.
FROM public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 AS lwa

FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
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
# Migrate and seed the 15 demo cases into a database file that ships inside the image.
COPY backend/fixtures /app/fixtures
COPY config /app/config
ENV CSO_MODE=replay \
    CSO_DATABASE_URL=sqlite+aiosqlite:////build/cso.db \
    CSO_COMMUNITY_CONFIG=/app/config/communities/default.yaml
RUN mkdir /build \
    && /opt/venv/bin/cso db upgrade \
    && /opt/venv/bin/cso seed --fixtures /app/fixtures/demo \
    && /opt/venv/bin/python -c "import sqlite3; c=sqlite3.connect('/build/cso.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.execute('PRAGMA journal_mode=DELETE'); c.close()" \
    && rm -f /build/cso.db-wal /build/cso.db-shm \
    && chmod 0444 /build/cso.db

FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS runtime
LABEL org.opencontainers.image.title="cso-lwa-api" \
      org.opencontainers.image.description="Changeset Second Opinion replay demo API on Lambda Web Adapter (spike)" \
      org.opencontainers.image.licenses="Apache-2.0"
COPY --from=lwa /lambda-adapter /opt/extensions/lambda-adapter
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    CSO_MODE=replay \
    CSO_JOBS_WORKER_ENABLED=false \
    CSO_DATABASE_URL=sqlite+aiosqlite:////tmp/cso.db \
    CSO_COMMUNITY_CONFIG=/app/config/communities/default.yaml \
    CSO_FIXTURES_DIR=/app/fixtures/demo \
    CSO_TRUST_PROXY=true \
    CSO_LOG_FORMAT=json \
    AWS_LWA_PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/healthz \
    AWS_LWA_INVOKE_MODE=buffered \
    AWS_LWA_ASYNC_INIT=true
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
COPY --from=builder /build/cso.db /app/data/cso.db
USER 10001:10001
EXPOSE 8080
# Start of one Lambda instance (or one local container): copy the read-only demo database to /tmp
# (SQLite in WAL mode needs a writable folder), then run the API on loopback. The adapter waits
# for /healthz, then forwards requests.
ENTRYPOINT ["/bin/sh", "-c", "install -m 0600 /app/data/cso.db /tmp/cso.db && exec python -m uvicorn cso.main:app --host 127.0.0.1 --port ${AWS_LWA_PORT} --no-access-log"]
