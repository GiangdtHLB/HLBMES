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

    # --- Logging ---
    log_level: str = "INFO"                # MES_LOG_LEVEL
    log_json: bool = False                 # MES_LOG_JSON (log JSON cho thu thập tập trung)


settings = Settings()

# ---- Hằng module-level (tương thích ngược) ----
APP_NAME = "MES Nhà máy Bia — MVP P0"
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

LOG_LEVEL = settings.log_level
LOG_JSON = settings.log_json
