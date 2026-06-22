#!/usr/bin/env bash
# Sao lưu DB PostgreSQL của MES (chạy cùng docker compose).
# Dùng: scripts/backup.sh   → tạo backups/mes-YYYYmmdd-HHMMSS.sql.gz
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="backups/mes-${STAMP}.sql.gz"
echo "→ Sao lưu sang ${OUT}"
docker compose exec -T db pg_dump -U mes -d mes | gzip > "${OUT}"
echo "✓ Xong. Danh sách backup:"
ls -lh backups/ | tail -5
echo "Khuyến nghị: giữ ≥1 bản offline/immutable (3-2-1), kiểm thử restore định kỳ (tài liệu §8.4)."
