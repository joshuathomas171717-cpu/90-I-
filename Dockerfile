# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# NINETY+ — two stages, so the runtime image carries no build tooling and the
# dependency layer is cached until requirements.txt actually changes.
#
# The build pre-warms the model artifact cache (P3.1). That means a deployed
# container answers /api/baseline from memory immediately instead of spending
# its first seconds training — the 7.3s cold start is paid once, at build time.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS deps

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    NT90_PRELOAD=1 \
    NT90_REFRESH_SECONDS=21600

WORKDIR /app

# dependencies first (cached layer), then the app source
COPY --from=deps /install /usr/local
COPY . .

# Pre-warm the artifact cache inside the image, then drop privileges to a
# non-root user that owns nothing but the app directory.
RUN python3 ml_engine.py > /dev/null \
 && useradd --create-home --shell /usr/sbin/nologin app \
 && chown -R app:app /app
USER app

EXPOSE 8000

# Liveness only: a slow or failed warm-up must never trigger a restart loop.
# Readiness (which does depend on the model) is /readyz, and the platform config
# in fly.toml / render.yaml gates traffic on that instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python3 -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status==200 else 1)"

CMD ["python3", "server.py", "--preload"]
