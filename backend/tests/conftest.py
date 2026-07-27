"""Cô lập DB giữa các test file.

Mỗi file test tự tạo tempfile DB riêng và set MES_DATABASE_URL trước khi
`from app.main import app` (xem đầu mỗi file test_stage_*.py, test_smoke.py...),
với ý định mỗi file có 1 DB độc lập. Nhưng có 2 lớp cache khiến ý định đó không
thành hiện thực khi chạy `pytest` cho cả thư mục (dù từng file riêng lẻ vẫn pass):

1. pytest import mỗi module test đúng 1 lần rồi cache trong sys.modules. File
   test chạy sau vẫn thấy `app.main`/`app.database`... đã bị file chạy TRƯỚC
   import xong — os.environ["MES_DATABASE_URL"] mới của nó không còn tác dụng gì,
   engine/SessionLocal vẫn là bản cũ trỏ vào DB của file đầu tiên.
   → Xoá sạch `app.*` khỏi sys.modules trước khi mỗi file test được import
     (pytest_collectstart) để mỗi file thật sự import lại từ đầu, đọc đúng
     MES_DATABASE_URL của chính nó.

2. pytest collect xong TOÀN BỘ (import hết mọi file) rồi mới chạy test (2 pha
   collect → run). Một số chỗ trong app (vd. `get_current_user` trong
   app/security.py) cố tình import `.database` NGAY TRONG THÂN HÀM (lazy import)
   thay vì ở đầu module — khi hàm đó chạy (lúc xử lý request, tức pha RUN), nó
   tra `sys.modules["app.database"]` tại THỜI ĐIỂM GỌI, chứ không phải bản đã
   bind lúc file test được import ở pha COLLECT. Vì pha collect đã hoàn tất
   trước khi pha run bắt đầu, sys.modules["app.database"] lúc đó luôn là bản
   của file test collect SAU CÙNG — khiến mọi file test khác (chạy sớm hơn
   trong pha run) vô tình dùng nhầm DB/engine của file collect cuối cùng.
   → Ghi nhớ (snapshot) toàn bộ sys.modules["app*"] ngay sau khi mỗi file test
     collect xong; trước khi chạy từng test, khôi phục đúng snapshot của FILE
     đang chứa test đó, để mọi lazy-import trong app luôn thấy đúng bản
     app.database/app.models... mà file test đó đã dùng lúc collect.
"""

import sys

import pytest


def _is_app_module(name: str) -> bool:
    return name == "app" or name.startswith("app.")


def _purge_app_modules() -> None:
    for name in list(sys.modules):
        if _is_app_module(name):
            del sys.modules[name]


def _snapshot_app_modules() -> dict:
    return {k: v for k, v in sys.modules.items() if _is_app_module(k)}


# path file test (resolved) -> snapshot sys.modules["app*"] ngay sau khi file đó collect xong.
_snapshots: dict = {}
_last_path = None


@pytest.hookimpl
def pytest_collectstart(collector):
    global _last_path
    if isinstance(collector, pytest.Module):
        if _last_path is not None:
            _snapshots[_last_path] = _snapshot_app_modules()
        _purge_app_modules()
        _last_path = str(collector.path.resolve())


@pytest.hookimpl
def pytest_collection_finish(session):
    global _last_path
    if _last_path is not None:
        _snapshots[_last_path] = _snapshot_app_modules()
        _last_path = None


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    snap = _snapshots.get(str(item.path.resolve()))
    if snap is not None:
        _purge_app_modules()
        sys.modules.update(snap)
