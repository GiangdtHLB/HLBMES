# MES Nhà máy Bia — image backend (FastAPI + frontend tĩnh)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Phụ thuộc hệ thống: libpq5 (psycopg/PostgreSQL), curl (healthcheck),
# msodbcsql18 + unixodbc (pyodbc/Microsoft SQL Server). Giữ cả hai để chạy được
# cả Postgres lẫn SQL Server tuỳ MES_DATABASE_URL.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl gnupg apt-transport-https ca-certificates \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
# requirements.txt đã có pyodbc (SQL Server); psycopg[binary] thêm riêng cho PostgreSQL.
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]==3.2.1"

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# Chạy uvicorn; --app-dir backend để 'app.main:app' import được; frontend cạnh backend.
WORKDIR /app
EXPOSE 8077
HEALTHCHECK --interval=30s --timeout=4s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8077/api/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8077"]
