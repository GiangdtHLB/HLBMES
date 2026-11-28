"""services/ai.py::llm_available() — MES_LLM_ENABLED="on" phải vẫn yêu cầu có API key, không
được coi là "bật cứng bất kể gì" (bug phát hiện qua audit 2026-11-03, cuongpx): thứ tự kiểm tra
cũ trả True ngay khi ENABLED=="on", TRƯỚC CẢ khi kiểm LLM_API_KEY — nếu key bị gỡ sau này mà quên
đổi ENABLED về "off", mọi lượt chat sẽ gọi thẳng Anthropic client với key=None, ném lỗi, rồi lộ
nguyên văn exception ra người dùng qua nhánh fallback. Test này khẳng định llm_available() trả
False khi thiếu key dù ENABLED="on".

CÁCH ĐẶT GIÁ TRỊ — đọc trước khi sửa: test gán THẲNG biến cấp module `ai.LLM_ENABLED` /
`ai.LLM_API_KEY` (đúng 2 tên mà llm_available() đọc), KHÔNG đặt biến môi trường rồi reload.

Bản đầu (2026-11-03) dùng os.environ + importlib.reload và ĐỎ ở môi trường cổng MSSQL: `config.py`
khai `SettingsConfigDict(env_file=...)` nên pydantic-settings đọc **cả file `.env` ở gốc repo**,
không chỉ os.environ. Máy nào có `.env` thật (máy triển khai, máy dev đã cấu hình) thì
`os.environ.pop("ANTHROPIC_API_KEY")` KHÔNG làm key biến mất — key vẫn vào từ file, llm_available()
trả True, 2 ca "không có key" fail. Tức test đỏ/xanh tuỳ máy có `.env` hay không, trong khi code
thì đúng (bỏ `.env` đi là 4/4 xanh).

Gán thẳng biến module tránh hẳn chuyện đó: cái cần kiểm ở đây là THỨ TỰ RẼ NHÁNH của
llm_available(), không phải cách pydantic gom cấu hình từ env/file."""

import pytest

from app.services import ai


@pytest.fixture(autouse=True)
def _restore_module_globals():
    """Trả lại giá trị thật sau mỗi ca — tránh rò sang test khác dùng chung tiến trình pytest."""
    saved = (ai.LLM_ENABLED, ai.LLM_API_KEY)
    yield
    ai.LLM_ENABLED, ai.LLM_API_KEY = saved


def _set(llm_enabled: str, llm_api_key: str):
    ai.LLM_ENABLED = llm_enabled
    ai.LLM_API_KEY = llm_api_key


def test_on_without_key_is_not_available():
    """Bug trước fix: ENABLED="on" trả True ngay cả khi KHÔNG có key — nguy hiểm vì gọi thật sẽ lỗi."""
    _set("on", "")
    assert ai.llm_available() is False


def test_on_with_key_is_available():
    _set("on", "sk-ant-test-fake-key-not-real")
    assert ai.llm_available() is True


def test_off_is_never_available_even_with_key():
    _set("off", "sk-ant-test-fake-key-not-real")
    assert ai.llm_available() is False


def test_auto_without_key_is_not_available():
    _set("auto", "")
    assert ai.llm_available() is False


def test_auto_with_key_is_available_when_sdk_installed():
    """"auto" = có key VÀ import được thư viện anthropic (đã nằm trong requirements)."""
    pytest.importorskip("anthropic")
    _set("auto", "sk-ant-test-fake-key-not-real")
    assert ai.llm_available() is True
