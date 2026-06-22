"""Cấu hình ứng dụng. Mặc định SQLite để chạy ngay; đặt MES_DATABASE_URL
để chuyển sang PostgreSQL (vd: postgresql+psycopg://user:pass@host/db)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # .../backend

# Mặc định SQLite trong thư mục backend để không cần cài Postgres.
# Tài liệu khuyến nghị PostgreSQL cho transactional — chỉ cần đổi biến môi trường.
DATABASE_URL = os.environ.get(
    "MES_DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'mes.db'}",
)

# Múi giờ lưu trữ: luôn UTC (tài liệu §8.3). Hiển thị cục bộ do client lo.
APP_NAME = "MES Nhà máy Bia — MVP P0"
FRONTEND_DIR = BASE_DIR.parent / "frontend"

# ---- Lớp AI (tài liệu §1.1: AI chỉ tư vấn, human-in-the-loop) ----
# Nếu có ANTHROPIC_API_KEY và cài 'anthropic', trợ lý dùng Claude thật (claude-opus-4-8);
# nếu không, dùng engine luật nội bộ để vẫn chạy offline.
LLM_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("MES_LLM_MODEL", "claude-opus-4-8")
LLM_ENABLED = os.environ.get("MES_LLM_ENABLED", "auto")  # auto | on | off

# Cho phép xác thực dự phòng bằng header X-User/X-Role (CHỈ để test/dev /docs).
# MẶC ĐỊNH TẮT — nếu bật sẽ cho bỏ qua đăng nhập, không dùng ở production.
DEV_HEADER_AUTH = os.environ.get("MES_DEV_HEADER_AUTH", "").lower() in ("1", "true", "on")
