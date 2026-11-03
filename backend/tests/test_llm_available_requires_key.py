"""services/ai.py::llm_available() — MES_LLM_ENABLED="on" phải vẫn yêu cầu có API key, không
được coi là "bật cứng bất kể gì" (bug phát hiện qua audit 2026-11-03, cuongpx): thứ tự kiểm tra
cũ trả True ngay khi ENABLED=="on", TRƯỚC CẢ khi kiểm LLM_API_KEY — nếu key bị gỡ sau này mà quên
đổi ENABLED về "off", mọi lượt chat sẽ gọi thẳng Anthropic client với key=None, ném lỗi, rồi lộ
nguyên văn exception ra người dùng qua nhánh fallback. Test này khẳng định llm_available() trả
False khi thiếu key dù ENABLED="on"."""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"

import importlib


def _reload_ai_with(llm_enabled: str, llm_api_key: str | None):
    os.environ["MES_LLM_ENABLED"] = llm_enabled
    if llm_api_key is None:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    else:
        os.environ["ANTHROPIC_API_KEY"] = llm_api_key
    import app.config as config_mod
    import app.services.ai as ai_mod
    importlib.reload(config_mod)
    importlib.reload(ai_mod)
    return ai_mod


def test_on_without_key_is_not_available():
    """Bug trước fix: ENABLED="on" trả True ngay cả khi KHÔNG có key — nguy hiểm vì gọi thật sẽ lỗi."""
    ai_mod = _reload_ai_with("on", None)
    assert ai_mod.llm_available() is False


def test_on_with_key_is_available():
    ai_mod = _reload_ai_with("on", "sk-ant-test-fake-key-not-real")
    assert ai_mod.llm_available() is True


def test_off_is_never_available_even_with_key():
    ai_mod = _reload_ai_with("off", "sk-ant-test-fake-key-not-real")
    assert ai_mod.llm_available() is False


def test_auto_without_key_is_not_available():
    ai_mod = _reload_ai_with("auto", None)
    assert ai_mod.llm_available() is False
