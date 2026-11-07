# syntax=docker/dockerfile:1
# Local-only images for the forge-voice Compose stack. No secrets are baked in;
# LiveKit keys, the optional Groq key and profile flags arrive from .env.local.

FROM python:3.12-slim AS base
ARG FORGE_UID=1000
ARG FORGE_GID=1000
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --gid "${FORGE_GID}" forge \
    && useradd --uid "${FORGE_UID}" --gid forge --create-home --shell /usr/sbin/nologin forge
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY fixtures ./fixtures
COPY scenarios ./scenarios
COPY tenants ./tenants

# Browser page, token endpoint, dashboard, admin and /health.
FROM base AS web
USER forge
ENV FORGE_VOICE_WEB_HOST=127.0.0.1 \
    FORGE_VOICE_WEB_PORT=8000 \
    FORGE_VOICE_DATA_DIR=/app/data
EXPOSE 8000
# The Compose path uses Linux host networking; bind loopback only.
CMD ["python", "-m", "uvicorn", "forge_voice.web.app:create_app_from_env", "--factory", "--host", "127.0.0.1", "--port", "8000", "--log-level", "info"]

# LiveKit Agents worker. The host LFM3 service is reached through
# host.docker.internal:8082; no GPU or model is inside the image.
FROM base AS agent
RUN pip install --no-cache-dir ".[demo]"
USER forge
ENV FORGE_VOICE_DATA_DIR=/app/data
EXPOSE 8081
CMD ["python", "-m", "forge_voice.runtime.livekit_agent", "start"]
