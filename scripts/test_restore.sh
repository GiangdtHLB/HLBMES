#!/usr/bin/env bash
# Kiểm thử KHÔI PHỤC backup (3-2-1: "backup chưa test = chưa có backup").
# Dump DB 'mes' → nạp vào DB scratch tách biệt → verify (đếm bảng + audit hash-chain),
# rồi xoá scratch. KHÔNG đụng dữ liệu prod. Chạy định kỳ (cron) để chắc backup phục hồi được.
#
# Dùng (khi stack docker compose đang chạy):  scripts/test_restore.sh
# Lập lịch hằng tuần:   0 3 * * 0  /đường/dẫn/scripts/test_restore.sh >> /var/log/mes-restore.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

PW="${POSTGRES_PASSWORD:-mes_secret}"
STAMP=$(date +%Y%m%d-%H%M%S)
DUMP="/tmp/mes-restoretest-${STAMP}.sql.gz"
SCRATCH="mes_restore_test"

echo "→ [1/5] Dump DB 'mes' → ${DUMP}"
docker compose exec -T db pg_dump -U mes -d mes | gzip > "${DUMP}"

echo "→ [2/5] Tạo DB scratch '${SCRATCH}'"
docker compose exec -T db psql -U mes -d postgres -c "DROP DATABASE IF EXISTS ${SCRATCH};" >/dev/null
docker compose exec -T db psql -U mes -d postgres -c "CREATE DATABASE ${SCRATCH};" >/dev/null

echo "→ [3/5] Nạp dump vào scratch"
gunzip -c "${DUMP}" | docker compose exec -T db psql -U mes -d "${SCRATCH}" >/dev/null

echo "→ [4/5] Verify: đếm bản ghi + kiểm tra audit hash-chain"
docker compose exec -T db psql -U mes -d "${SCRATCH}" -tAc \
  "SELECT 'app_user='||count(*) FROM app_user UNION ALL SELECT 'audit_log='||count(*) FROM audit_log;"
docker compose exec -T \
  -e MES_DATABASE_URL="postgresql+psycopg://mes:${PW}@db:5432/${SCRATCH}" app \
  sh -c 'cd backend && python -c "from app.database import SessionLocal; from app.audit import verify_chain; db=SessionLocal(); r=verify_chain(db); db.close(); import sys; print(\"audit_chain:\", r); sys.exit(0 if r[\"intact\"] else 1)"'

echo "→ [5/5] Dọn dẹp scratch + dump tạm"
docker compose exec -T db psql -U mes -d postgres -c "DROP DATABASE IF EXISTS ${SCRATCH};" >/dev/null
rm -f "${DUMP}"
echo "✓ RESTORE TEST PASS — backup phục hồi được & audit chain toàn vẹn."
