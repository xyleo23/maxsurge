# ─────────────────────────────────────────────────
# Stage 1: builder — compiles wheels + installs deps
# ─────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────
# Stage 2: runtime — slim, no build tools
# ─────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv

# Install playwright browsers + system deps as root
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd --system --create-home --shell /bin/bash maxsurge \
    && mkdir -p /app /opt/playwright \
    && chown -R maxsurge:maxsurge /app /opt/playwright

USER maxsurge
WORKDIR /app

# App code last so cache survives code-only changes
COPY --chown=maxsurge:maxsurge . .

RUN mkdir -p /app/logs /app/backups /app/sessions

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fs http://localhost:8090/health || exit 1

CMD ["python", "main.py"]
