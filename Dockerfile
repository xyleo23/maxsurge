FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps: для playwright + sqlite3 backup + fonts for PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    fonts-dejavu-core \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Playwright browsers
RUN playwright install chromium --with-deps

COPY . .

RUN mkdir -p /app/logs /app/backups /app/sessions

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8090/health || exit 1

CMD ["python", "main.py"]
