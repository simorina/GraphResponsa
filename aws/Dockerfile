# Multi-stage Dockerfile per GraphResponsa
# Stage 1: Build del Frontend React (Vite + TypeScript + Tailwind)
FROM node:20-alpine AS frontend-builder
WORKDIR /build

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Runtime Python FastAPI + Claude Agent
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Installa dipendenze di sistema minime per pymupdf e compilazione
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Installa requisiti Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice sorgente
COPY src/ ./src/
COPY data/ ./data/

# Copia il frontend compilato dallo Stage 1 in frontend/dist per FastAPI
COPY --from=frontend-builder /build/dist ./frontend/dist

# Espone la porta del server FastAPI
EXPOSE 8000

# Healthcheck per container orchestrator (ECS/Docker)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/stato || exit 1

# Avvio del server FastAPI in produzione con Uvicorn
CMD ["python", "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
