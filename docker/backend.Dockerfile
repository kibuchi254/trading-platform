# ATLAS Backend image — Python 3.13 + uv
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# uv for fast dependency install
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install deps first (cache layer)
COPY pyproject.toml README.md ./
RUN uv pip install --system -e ".[dev]"

# Copy source
COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY mql5/ ./mql5/

EXPOSE 8000 9000

CMD ["uvicorn", "platform.main:app", "--host", "0.0.0.0", "--port", "8000"]
