# ==============================================================================
# Dam Break Decision Support System - Production Container Image
# ==============================================================================
# UNVERIFIED TEMPLATE: Docker is not installed in the local validation environment.
# This template is provided for production cloud/container deployment guidance.
# ==============================================================================

# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Runtime API & Static File Serving
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SIH_RUNTIME_DIR=/app/data/runtime \
    CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

WORKDIR /app

# Install system geospatial libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python backend dependencies
COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend source code
COPY backend/ /app/backend/

# Copy built frontend assets for reverse-proxy / static mounting
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Ensure runtime directories exist
RUN mkdir -p /app/data/raw /app/data/runtime

EXPOSE 8000

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
