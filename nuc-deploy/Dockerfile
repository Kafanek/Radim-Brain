# ============================================
# RADIM BRAIN - NUC Docker Image
# Python 3.11 + Flask + Gunicorn + Eventlet
# ============================================
# Build context = /opt/radim/ (where docker-compose.yml is)
# App code is in /opt/radim/app/

FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app user (non-root)
RUN useradd -m -s /bin/bash radim
WORKDIR /app

# Install Python dependencies first (better Docker cache layer)
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code from app/ subdirectory
COPY app/ .

# Create directories for logs and data
RUN mkdir -p /app/logs /app/data && chown -R radim:radim /app

USER radim

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Start with gunicorn + eventlet
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", \
     "--bind", "0.0.0.0:8000", "--timeout", "120", \
     "--access-logfile", "/app/logs/access.log", \
     "--error-logfile", "/app/logs/error.log", \
     "--log-level", "info", \
     "app:app"]
