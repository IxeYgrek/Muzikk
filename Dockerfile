# syntax=docker/dockerfile:1

# ---------- Stage 1: build the React SPA ----------
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MUZIKK_CONFIG_DIR=/config \
    MUZIKK_STATIC_DIR=/app/static \
    MUZIKK_PORT=8383

# libchromaprint-tools provides fpcalc, used to identify an album by its audio.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      flac \
      ffmpeg \
      libchromaprint-tools \
      ca-certificates \
      curl \
      gosu \
      tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/ /app/
COPY --from=frontend /build/dist /app/static
COPY docker/entrypoint.sh /entrypoint.sh
# Guard against a checkout with CRLF endings, which would break the shebang.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

VOLUME ["/config"]
EXPOSE 8383

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${MUZIKK_PORT}/api/health" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "muzikk.main:app", "--host", "0.0.0.0", "--port", "8383", "--proxy-headers", "--forwarded-allow-ips", "*"]
