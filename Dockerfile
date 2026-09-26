# Multi-stage or slim Python image optimized for Google Cloud Run
FROM python:3.11-slim

# Set environment variables for performance and unbuffered container logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/app \
    PORT=8080

WORKDIR /app

# Install minimal build tools for C-extensions (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for Docker caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and line UX assets
COPY . .

# Cloud Run injects $PORT (default 8080)
EXPOSE 8080

# Gunicorn: 1 worker, 8 threads, and a hard 240s per-request cap with worker
# recycling. WORKER TIMEOUT + SIGKILL (kills in-flight background analysis)
# happens when a request blocks longer than the timeout — max-requests
# recycles leaky workers and graceful-timeout lets them finish cleanly.
CMD exec gunicorn --bind :${PORT:-8080} --workers 1 --threads 8 \
    --timeout 240 --graceful-timeout 30 --max-requests 200 --max-requests-jitter 50 \
    src.app:app
