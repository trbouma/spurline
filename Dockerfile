# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm AS builder

ARG POETRY_VERSION=1.8.2

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1

# These packages support coincurve builds on platforms without a prebuilt wheel,
# including Linux ARM64 targets used by Raspberry Pi deployments.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        autoconf \
        automake \
        build-essential \
        libffi-dev \
        libtool \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install "poetry==${POETRY_VERSION}"

WORKDIR /app

COPY pyproject.toml poetry.lock README.md ./
COPY src /app/src
RUN poetry install --only main --no-ansi


FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SPURLINE_HOST=0.0.0.0 \
    SPURLINE_PORT=8080 \
    SPURLINE_DATABASE=/data/spurline.sqlite3 \
    SPURLINE_VERIFY_SIGNATURES=true

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 spurline \
    && useradd --uid 10001 --gid spurline --create-home --shell /usr/sbin/nologin spurline \
    && install -d -o spurline -g spurline /data

WORKDIR /app

COPY --from=builder --chown=spurline:spurline /app/.venv /app/.venv
COPY --from=builder --chown=spurline:spurline /app/src /app/src

USER spurline

EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()"]

# Spurline keeps live subscriptions in process memory and writes one SQLite
# database, so the container intentionally runs exactly one worker.
CMD ["uvicorn", "spurline.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
