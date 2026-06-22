#!/usr/bin/env bash
# Khôi phục DB MES từ file backup .sql.gz.
# Dùng: scripts/restore.sh backups/mes-YYYYmmdd-HHMMSS.sql.gz
set -euo pipefail
cd "$(dirname "$0")/.."
FILE="${1:?Cần đường dẫn file backup .sql.gz}"
echo "⚠️  Khôi phục từ ${FILE} — sẽ GHI ĐÈ dữ liệu hiện tại của DB 'mes'."
read -r -p "Gõ 'yes' để tiếp tục: " ok; [ "$ok" = "yes" ] || { echo "Hủy."; exit 1; }
gunzip -c "${FILE}" | docker compose exec -T db psql -U mes -d mes
echo "✓ Khôi phục xong. Hãy kiểm tra /api/health và /api/audit/verify-chain."
