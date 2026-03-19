# ── Build stage ────────────────────────────────────────────
FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies first (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Ensure data directory exists (overridden by volume at runtime)
RUN mkdir -p /data

# Runtime environment – all values can be overridden via docker-compose or -e flags
ENV DATA_DIR=/data \
    METUBE_URL=http://localhost:8081 \
    CHECK_INTERVAL=60 \
    JELLYFIN_URL="" \
    JELLYFIN_API_KEY="" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
