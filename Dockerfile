# RuleMemory Cloud -- Cloud Run container.
# Single-process FastAPI app served by uvicorn on $PORT (Cloud Run injects PORT).

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App source.
COPY src ./src
COPY seed ./seed

ENV PYTHONPATH=/app/src

EXPOSE 8080

# Cloud Run sends SIGTERM; uvicorn handles graceful shutdown.
# Use shell form so $PORT expands at runtime.
CMD exec uvicorn rulememory.app:app --host 0.0.0.0 --port ${PORT}
