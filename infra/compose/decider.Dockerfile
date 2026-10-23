# syntax=docker/dockerfile:1
# Strands Decider server. Build context is infra/compose. The model weights are not in the image:
# they download into the cache volume on first start (about 5 GB).
#
# TORCH_INDEX selects the PyTorch wheel source. Empty uses PyPI, whose Linux wheels carry CUDA
# libraries (GPU hosts). The CPU compose file passes https://download.pytorch.org/whl/cpu, which is
# several GB smaller. Base image pinned by tag and digest, last checked 2026-10-20 (python 3.13.16).

FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS builder
ARG STRANDS_DECIDER_VERSION=0.1.0
ARG TORCH_INDEX=
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Torch first from the chosen index, then the Decider (which finds torch already satisfied).
RUN if [ -n "$TORCH_INDEX" ]; then pip install --index-url "$TORCH_INDEX" "torch>=2.7"; fi
RUN pip install "strands-decider==${STRANDS_DECIDER_VERSION}"

FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS runtime
LABEL org.opencontainers.image.title="cso-decider" \
      org.opencontainers.image.description="Strands Decider 2B server for Changeset Second Opinion" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/decider \
    HF_HOME=/home/decider/.cache/huggingface
# Fixed uid and gid 10002: the AWS bootstrap script chowns the host model folder to it.
RUN groupadd --system --gid 10002 decider \
    && useradd --system --uid 10002 --gid decider --create-home --shell /usr/sbin/nologin decider \
    && install -d -o decider -g decider -m 0750 /home/decider/.cache/huggingface
COPY --from=builder /opt/venv /opt/venv
USER 10002:10002
VOLUME ["/home/decider/.cache/huggingface"]
ENTRYPOINT ["strands-decider"]
