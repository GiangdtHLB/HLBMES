"""Cấu hình tập trung qua pydantic-settings (validate kiểu + nguồn env/.env).

Mọi biến môi trường gom về một class Settings để dễ kiểm tra & tài liệu hoá.
Giữ các tên hằng module-level (DATABASE_URL, APP_NAME, ...) để code hiện có
`from .config import X` không phải đổi.
"""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent          # .../backend
_ENV_FILE = str(BASE_DIR.parent / ".env")                  # .env ở gốc repo


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MES_", env_file=_ENV_FILE, extra="ignore", case_sensitive=False
    )

    # --- Database ---
    database_url: str = ""        # MES_DATABASE_URL; rỗng → SQLite dev (tính bên dưới)
    # Tự tạo bảng bằng create_all. SQLite luôn tự tạo (dev/test); Postgres/SQL Server
    # CHỈ tạo khi bật cờ này — production dùng Alembic làm nguồn schema duy nhất.
    auto_create: bool = False     # MES_AUTO_CREATE
    db_pool_size: int = 10        # MES_DB_POOL_SIZE (Postgres/MSSQL)
    db_max_overflow: int = 20     # MES_DB_MAX_OVERFLOW

    # --- AI (advisory; §1.1) ---
    # ANTHROPIC_API_KEY không có tiền tố MES_ → dùng alias.
    llm_api_key: str = Field(default="", validation_alias=AliasChoices("ANTHROPIC_API_KEY"))
    llm_model: str = "claude-opus-4-8"     # MES_LLM_MODEL
    llm_enabled: str = "auto"              # MES_LLM_ENABLED: auto | on | off

    # --- Bảo mật / phiên ---
    dev_header_auth: bool = False          # MES_DEV_HEADER_AUTH (CHỈ dev)
    session_hours: int = 12                # MES_SESSION_HOURS
    admin_password: str = ""               # MES_ADMIN_PASSWORD (rỗng → mặc định + buộc đổi)

    # --- Seed ---
    seed_demo: bool = True                 # MES_SEED_DEMO: tạo tài khoản/API key/dữ liệu demo

    # --- Rate-limit / quota ---
    rl_enabled: bool = True                # MES_RL_ENABLED
    rl_login_per_min: int = 10             # MES_RL_LOGIN_PER_MIN
    rl_ai_per_min: int = 20                # MES_RL_AI_PER_MIN
    rl_ai_daily_quota: int = 300           # MES_AI_DAILY_QUOTA (chat AI/ngày/phiên)
    redis_url: str = ""                    # MES_REDIS_URL: bật backend Redis cho rate-limit (nhiều worker)

    # --- Logging ---
    log_level: str = "INFO"                # MES_LOG_LEVEL
    log_json: bool = False                 # MES_LOG_JSON (log JSON cho thu thập tập trung)

    # --- Web hardening ---
    cors_origins: str = ""                 # MES_CORS_ORIGINS: csv origin được phép (rỗng = same-origin, không bật CORS)
    trusted_proxy: bool = False            # MES_TRUSTED_PROXY: chỉ tin X-Forwarded-For khi chạy sau reverse proxy tin cậy
    hsts: bool = False                     # MES_HSTS: gửi Strict-Transport-Security (bật khi đã có HTTPS)


settings = Settings()

# ---- Hằng module-level (tương thích ngược) ----
APP_NAME = "MES Bia Hạ Long - Nhà Máy Đông Mai"
FRONTEND_DIR = BASE_DIR.parent / "frontend"
DATABASE_URL = settings.database_url or f"sqlite:///{BASE_DIR / 'mes.db'}"

LLM_API_KEY = settings.llm_api_key
LLM_MODEL = settings.llm_model
LLM_ENABLED = settings.llm_enabled

DEV_HEADER_AUTH = settings.dev_header_auth
SESSION_HOURS = settings.session_hours
ADMIN_PASSWORD = settings.admin_password
SEED_DEMO = settings.seed_demo

RL_ENABLED = settings.rl_enabled
RL_LOGIN_PER_MIN = settings.rl_login_per_min
RL_AI_PER_MIN = settings.rl_ai_per_min
RL_AI_DAILY_QUOTA = settings.rl_ai_daily_quota
REDIS_URL = settings.redis_url

LOG_LEVEL = settings.log_level
LOG_JSON = settings.log_json

AUTO_CREATE = settings.auto_create
DB_POOL_SIZE = settings.db_pool_size
DB_MAX_OVERFLOW = settings.db_max_overflow
CORS_ORIGINS = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
TRUSTED_PROXY = settings.trusted_proxy
HSTS = settings.hsts

# Loại CSDL suy ra từ URL (sqlite | postgresql | mssql | ...). Dùng cho nhánh dialect.
DB_DIALECT = (DATABASE_URL.split(":", 1)[0].split("+", 1)[0] or "sqlite").lower()
