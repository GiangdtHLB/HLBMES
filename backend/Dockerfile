# MES Nhà máy Bia — image backend (FastAPI + frontend tĩnh)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Phụ thuộc hệ thống tối thiểu (libpq cho psycopg, curl cho healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
# psycopg[binary] để chạy PostgreSQL ở production (không bắt buộc cho SQLite dev)
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]==3.2.1"

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# Chạy uvicorn; --app-dir backend để 'app.main:app' import được; frontend cạnh backend.
WORKDIR /app
EXPOSE 8077
HEALTHCHECK --interval=30s --timeout=4s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8077/api/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8077"]
