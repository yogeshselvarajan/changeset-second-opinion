# syntax=docker/dockerfile:1
# Edge image: the built SPA and the docs site, served by Caddy with the rate-limit module (stock
# Caddy has no rate limiter). Build context is the repository root. No Python is needed.
#
# Base images are pinned by tag and digest (index digests). Last checked 2026-10-20:
# node 22.23.3 (maintenance LTS line), caddy 2.11.7.

# Stage 1: build the SPA and, through web's build script, the docs site (site/) into dist/docs.
# The output is plain files, so this stage always runs on the machine that builds (BUILDPLATFORM)
# and never under emulation, even when the image is built for arm64 on an x86 machine.
FROM --platform=$BUILDPLATFORM node:22.23.3-alpine3.24@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY web/ ./
# The docs site reads the committed OpenAPI file one level up (../backend/openapi/v1.json). The
# generated reference pages are committed. build-docs.mjs finds node_modules here and skips its
# own install.
COPY site/package.json site/package-lock.json /site/
RUN --mount=type=cache,target=/root/.npm npm --prefix /site ci --no-audit --no-fund
COPY site/ /site/
COPY backend/openapi/v1.json /backend/openapi/v1.json
# The home page quotes figures computed at build time from the committed evaluation files.
COPY evaluation/labels/dev.jsonl evaluation/labels/dev.adjudicated.jsonl /evaluation/labels/
COPY evaluation/results/spike-2026-10-17.json /evaluation/results/
# ... and from the recorded demo cases (only each expected.json is in the build context).
COPY backend/fixtures/demo/cases /backend/fixtures/demo/cases
# The address the site is served from (canonical links, sitemap) and the project's repository.
ARG CSO_PUBLIC_ORIGIN=http://localhost
ARG CSO_REPO_URL=https://github.com/yogeshselvarajan/changeset-second-opinion
ENV CSO_PUBLIC_ORIGIN=${CSO_PUBLIC_ORIGIN} CSO_REPO_URL=${CSO_REPO_URL}
RUN npm run build

# Stage 2: Caddy with the rate-limit module, pinned to a commit (HEAD on 2026-10-17, committed
# 2026-06-12); the latest tag, v0.1.0, is from 2024-08. The Caddy version matches the runtime base.
# It cross-compiles for TARGETARCH on the build machine, so an arm64 image needs no emulation.
FROM --platform=$BUILDPLATFORM caddy:2.11.7-builder@sha256:d842facfd63b960922e57444ff76fd8f0793a66dfdcf481af8026e1f4e6a39b4 AS builder
ARG TARGETOS
ARG TARGETARCH
RUN GOOS=${TARGETOS} GOARCH=${TARGETARCH} xcaddy build v2.11.7 --with github.com/mholt/caddy-ratelimit@5625512f24f6f59d6f64fb3aafe5eecff0b286db

# Stage 3: runtime. Runs as an unprivileged user; binding port 80 or 443 needs no privilege because
# the compose file sets net.ipv4.ip_unprivileged_port_start=0 on the shared network namespace.
FROM caddy:2.11.7-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f AS runtime
LABEL org.opencontainers.image.title="cso-web" \
      org.opencontainers.image.description="Changeset Second Opinion: web app, docs site and Caddy edge" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/yogeshselvarajan/changeset-second-opinion"
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
# The base image gives the caddy file the cap_net_bind_service capability. With every capability
# dropped by compose that makes the start fail ("operation not permitted"), and it is not needed
# here, so it is removed.
RUN setcap -r /usr/bin/caddy \
    && addgroup -S -g 10003 caddy \
    && adduser -S -u 10003 -G caddy -H -h /nonexistent -s /sbin/nologin caddy \
    && install -d -o caddy -g caddy -m 0700 /data /config
COPY --from=web /web/dist /srv
USER 10003:10003
EXPOSE 80 443
