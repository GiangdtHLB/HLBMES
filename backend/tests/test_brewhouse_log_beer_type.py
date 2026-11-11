"""BA_RecNo -> Loai bia trong Log he nau / Thoi gian ca me nau - yeu cau nguoi dung 2026-11-11:
"Phan bao cao bo sung them cot Loai bia lay theo RecNo, chi can lay noi gao la thuoc me do la
duoc ... Cho them loc theo loai bia, ke ca hieu suat ly thuyet cung loc theo loai bia". Xem
services/brewhouse_log.py::_rec_no_by_batch_key/step_log_report/brew_cycle_report +
services/brewhouse_external.py::BEER_TYPE_BY_RECNO.

Dung truc tiep ORM (BrewhouseStepLog) de dung san cac dong log, khong qua poll_loop that (khong
co CSDL SCADA that trong test) - mirror pattern "direct ORM insert" o cac test khac (vd
test_qc_beer_type_filter.py)."""

import os
import tempfile
from datetime import datetime, timedelta, timezone

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest

from app.database import SessionLocal
from app.models.brewhouse_log import BrewhouseStepLog
from app.services import brewhouse_log as bl_svc
from app.services import brewhouse_external


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    from app import seed as seed_mod
    seed_mod.seed()
    yield


def _add_row(db, equipment_id, equipment_name, ba_year, ba_order_no, ba_batch_no, ba_rec_no,
            started_at, ended_at, data_gap=False):
    row = BrewhouseStepLog(
        equipment_id=equipment_id, equipment_name=equipment_name,
        ba_year=ba_year, ba_order_no=ba_order_no, ba_batch_no=ba_batch_no, ba_rec_no=ba_rec_no,
        step_no=1, step_name="Test", eop_state_label="running",
        started_at=started_at, ended_at=ended_at,
        duration_minutes=(ended_at - started_at).total_seconds() / 60.0 if ended_at else None,
        data_gap=data_gap,
    )
    db.add(row)
    return row


def test_step_log_report_resolves_beer_type_from_rice_cooker_only(_seeded):
    """Noi gao (equipment_id=1) co ba_rec_no=13 (Sapphire 16 me) - mot thiet bi KHAC cung me
    (Noi loc, equipment_id=3) KHONG co ba_rec_no rieng (None, dung dinh huong "Chuyen dich lanh
    nhanh" thuc te) - van phai duoc gan dung "Sapphire 16 me" qua suy tu noi gao."""
    db = SessionLocal()
    t0 = datetime(2030, 1, 10, 1, 0, tzinfo=timezone.utc)
    try:
        _add_row(db, 1, "Nồi gạo", 2030, "RECTEST1", "B1", 13, t0, t0 + timedelta(minutes=30))
        _add_row(db, 3, "Nồi lọc 1", 2030, "RECTEST1", "B1", None,
                 t0 + timedelta(minutes=30), t0 + timedelta(minutes=60))
        db.commit()
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        rep = bl_svc.step_log_report(db2, ba_year=2030, ba_order_no="RECTEST1", ba_batch_no="B1")
    finally:
        db2.close()

    assert len(rep["steps"]) == 2
    for step in rep["steps"]:
        assert step["beer_type_recno"] == 13
        assert step["beer_type_name"] == "Sapphire 16 mẻ"
    assert len(rep["summary"]) == 2
    for s in rep["summary"]:
        assert s["beer_type_recno"] == 13
        assert s["beer_type_name"] == "Sapphire 16 mẻ"
    # Thiet bi rieng van giu nguyen gia tri RIENG cua no (None cho Noi loc) de tham khao.
    loc_step = next(s for s in rep["steps"] if s["equipment_id"] == 3)
    assert loc_step["ba_rec_no"] is None


def test_step_log_report_beer_type_filter(_seeded):
    db = SessionLocal()
    t0 = datetime(2030, 2, 10, 1, 0, tzinfo=timezone.utc)
    try:
        _add_row(db, 1, "Nồi gạo", 2030, "RECTEST2", "B2", 1, t0, t0 + timedelta(minutes=20))
        db.commit()
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        rep_match = bl_svc.step_log_report(db2, ba_year=2030, ba_order_no="RECTEST2",
                                           ba_batch_no="B2", beer_type_recno=1)
        rep_nomatch = bl_svc.step_log_report(db2, ba_year=2030, ba_order_no="RECTEST2",
                                             ba_batch_no="B2", beer_type_recno=13)
    finally:
        db2.close()

    assert len(rep_match["steps"]) == 1
    assert rep_match["steps"][0]["beer_type_name"] == "Hạ Long Idol"
    assert len(rep_nomatch["steps"]) == 0


def test_brew_cycle_report_beer_type_and_throughput_filter(_seeded):
    """Dung du chuoi ROLE_CHAIN (noi gao -> lang xoay) cho 1 me DA XONG de throughput tinh duoc,
    gan ba_rec_no=12 (Legend 16 me) o noi gao - kiem tra ca items[].beer_type_name lan
    throughput[].batch.beer_type_name, va filter beer_type_recno loai dung me khac Loai bia."""
    db = SessionLocal()
    t0 = datetime(2030, 3, 10, 1, 0, tzinfo=timezone.utc)
    try:
        # Noi gao (id=1), Noi malt (id=2), Noi loc (id=3), Noi trung gian (id=4),
        # Noi soi hoa (id=5), Noi lang xoay (id=6) - lien tiep khong chong lan, deu da ket thuc.
        cursor = t0
        for eq_id, name, minutes, recno in [
            (1, "Nồi gạo", 30, 12), (2, "Nồi malt 1", 40, None), (3, "Nồi lọc 1", 50, None),
            (4, "Nồi trung gian 1", 10, None), (5, "Nồi sôi hoa 1", 60, None),
            (6, "Nồi lắng xoáy 1", 20, None),
        ]:
            end = cursor + timedelta(minutes=minutes)
            _add_row(db, eq_id, name, 2030, "RECTEST3", "B3", recno, cursor, end)
            cursor = end
        db.commit()
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        rep_all = bl_svc.brew_cycle_report(db2, ba_year=2030, ba_order_no="RECTEST3", ba_batch_no="B3")
        rep_match = bl_svc.brew_cycle_report(db2, ba_year=2030, ba_order_no="RECTEST3",
                                             ba_batch_no="B3", beer_type_recno=12)
        rep_nomatch = bl_svc.brew_cycle_report(db2, ba_year=2030, ba_order_no="RECTEST3",
                                               ba_batch_no="B3", beer_type_recno=13)
    finally:
        db2.close()

    assert len(rep_all["items"]) == 1
    item = rep_all["items"][0]
    assert item["beer_type_recno"] == 12
    assert item["beer_type_name"] == "Legend 16 mẻ"
    assert item["stage"] == "da_xong"

    assert len(rep_match["items"]) == 1
    assert len(rep_match["throughput"]) == 1
    assert rep_match["throughput"][0]["batch"]["beer_type_name"] == "Legend 16 mẻ"
    assert rep_match["throughput"][0]["batches_per_day"] is not None

    assert len(rep_nomatch["items"]) == 0
    assert len(rep_nomatch["throughput"]) == 0


def test_open_step_captures_ba_rec_no_from_status():
    """_open_step() phai luu ba_rec_no tu status dict (brewhouse_external._row_to_status() dang
    tra ve) vao cot rieng cua BrewhouseStepLog, khong chi trong JSON snapshot."""
    status = {
        "ba_year": 2030, "ba_order_no": "O1", "ba_batch_no": "B1", "step_no": 2,
        "step": "Test step", "eop_state_label": "running", "ba_rec_no": 9,
        "beer_type_name": "Classic 16 mẻ",
    }
    row = bl_svc._open_step(equipment_id=1, status=status, now=datetime.now(timezone.utc))
    assert row.ba_rec_no == 9
