"""Log trang thai may chiet 30K (1=dang chiet, 2=dang CIP, 3=may dung) - yeu cau nguoi dung
2026-11-13: "may chay running va (Trang nuoc nong hoac Duoi CO2 dang chay) thi la Dang CIP may,
trang thai bang 2, Neu chi co trang thai may dang Running va (Trang nuoc nong va Duoi CO2 dang
dung) thi trang thai may la 1 ... tren bieu do day chuyen 30k the hien nhu vay". Bo sung cung
ngay (sau khi xem demo thay co khoang trong giua cac thanh): "cac khe ho phai lien mach, neu
Trang thai may la dung va ca duoi CO2 va duoi nuoc nong deu dung thi la trang thai 3, may dung,
de 1 mau khac" - LUON co dung 1 trang thai tai moi thoi diem, khong con khoang trong.

Goi thang process_tick() voi dict trang thai gia lap (khong qua SCADA that trong test) - mirror
pattern cac test brewhouse_log khac."""

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
from app.models.filling_log import FillingStatusLog
from app.services import filling_log as fl_svc


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    from app import seed as seed_mod
    seed_mod.seed()
    yield


def _status(machine_running, clean_flushing=False, rins_return_gas_channel=False):
    return {"available": True, "machine_running": machine_running,
            "clean_flushing": clean_flushing, "rins_return_gas_channel": rins_return_gas_channel}


def _open_row(db):
    return db.execute(
        __import__("sqlalchemy").select(FillingStatusLog).where(FillingStatusLog.ended_at.is_(None))
    ).scalars().first()


def test_status_of_running_vs_cip_vs_stopped():
    assert fl_svc._status_of(_status(True)) == fl_svc.STATUS_RUNNING
    assert fl_svc._status_of(_status(True, clean_flushing=True)) == fl_svc.STATUS_CIP
    assert fl_svc._status_of(_status(True, rins_return_gas_channel=True)) == fl_svc.STATUS_CIP
    assert fl_svc._status_of(_status(True, clean_flushing=True, rins_return_gas_channel=True)) == fl_svc.STATUS_CIP
    assert fl_svc._status_of(_status(False)) == fl_svc.STATUS_STOPPED
    # CIP tinh TRUOC machine_running - van la CIP (2) ke ca khi may chinh dang dung.
    assert fl_svc._status_of(_status(False, clean_flushing=True)) == fl_svc.STATUS_CIP
    assert fl_svc._status_of(_status(False, rins_return_gas_channel=True)) == fl_svc.STATUS_CIP


def test_process_tick_opens_row_on_first_running_tick():
    db = SessionLocal()
    try:
        db.query(FillingStatusLog).delete()
        db.commit()
        fl_svc.process_tick(db, _status(True))
        db.commit()
        row = _open_row(db)
        assert row is not None
        assert row.status == fl_svc.STATUS_RUNNING
        assert row.ended_at is None
    finally:
        db.close()


def test_process_tick_transitions_running_to_cip_closes_and_opens():
    db = SessionLocal()
    try:
        db.query(FillingStatusLog).delete()
        db.commit()
        fl_svc.process_tick(db, _status(True))
        db.commit()
        running_row_id = _open_row(db).log_id

        fl_svc.process_tick(db, _status(True, clean_flushing=True))
        db.commit()

        closed = db.get(FillingStatusLog, running_row_id)
        assert closed.ended_at is not None
        assert closed.status == fl_svc.STATUS_RUNNING

        cip_row = _open_row(db)
        assert cip_row is not None
        assert cip_row.status == fl_svc.STATUS_CIP
        assert cip_row.log_id != running_row_id
    finally:
        db.close()


def test_process_tick_machine_stopped_closes_running_and_opens_stopped():
    """Khac voi truoc 2026-11-13 (khi dung khong mo dong moi, gay khoang trong tren bieu do) -
    gio LUON mo dong moi cho trang thai 3 (may dung), khong con khoang trong."""
    db = SessionLocal()
    try:
        db.query(FillingStatusLog).delete()
        db.commit()
        fl_svc.process_tick(db, _status(True))
        db.commit()
        running_row_id = _open_row(db).log_id

        fl_svc.process_tick(db, _status(False))
        db.commit()

        closed = db.get(FillingStatusLog, running_row_id)
        assert closed.ended_at is not None
        assert closed.status == fl_svc.STATUS_RUNNING

        stopped_row = _open_row(db)
        assert stopped_row is not None
        assert stopped_row.status == fl_svc.STATUS_STOPPED
        assert stopped_row.log_id != running_row_id
        all_rows = db.execute(__import__("sqlalchemy").select(FillingStatusLog)).scalars().all()
        assert len(all_rows) == 2
    finally:
        db.close()


def test_process_tick_same_status_does_not_reopen_row():
    db = SessionLocal()
    try:
        db.query(FillingStatusLog).delete()
        db.commit()
        fl_svc.process_tick(db, _status(True))
        db.commit()
        first_id = _open_row(db).log_id

        fl_svc.process_tick(db, _status(True))
        db.commit()

        row = _open_row(db)
        assert row.log_id == first_id
        all_rows = db.execute(__import__("sqlalchemy").select(FillingStatusLog)).scalars().all()
        assert len(all_rows) == 1
    finally:
        db.close()


def test_filling_status_log_report_segments_and_hours():
    db = SessionLocal()
    t0 = datetime(2031, 2, 1, 1, 0, tzinfo=timezone.utc)
    try:
        db.query(FillingStatusLog).delete()
        db.add(FillingStatusLog(status=fl_svc.STATUS_RUNNING, machine_running=True,
                                clean_flushing=False, rins_return_gas_channel=False,
                                started_at=t0, ended_at=t0 + timedelta(hours=2),
                                duration_minutes=120.0, data_gap=False))
        db.add(FillingStatusLog(status=fl_svc.STATUS_CIP, machine_running=True,
                                clean_flushing=True, rins_return_gas_channel=False,
                                started_at=t0 + timedelta(hours=2), ended_at=t0 + timedelta(hours=2, minutes=30),
                                duration_minutes=30.0, data_gap=False))
        # Dong data_gap=True -> phai bi loai khoi report
        db.add(FillingStatusLog(status=fl_svc.STATUS_RUNNING, machine_running=True,
                                clean_flushing=False, rins_return_gas_channel=False,
                                started_at=t0 + timedelta(hours=3), ended_at=t0 + timedelta(hours=4),
                                duration_minutes=60.0, data_gap=True))
        db.commit()
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        rep = fl_svc.filling_status_log_report(
            db2, date_from_str="2031-01-25", date_to_str="2031-02-05")
    finally:
        db2.close()

    assert len(rep["segments"]) == 2
    assert rep["running_hours"] == 2.0
    assert rep["cip_hours"] == 0.5
    assert rep["stopped_hours"] == 0.0


def test_process_tick_sequence_has_no_gaps():
    """Mo phong 1 chuoi tick thuc te (chay -> dung -> CIP -> chay) roi doc lai bang
    filling_status_log_report() - moi doan phai noi lien nhau (end_at doan truoc == start_at
    doan sau), khong con khoang trong nhu truoc khi co trang thai 3."""
    db = SessionLocal()
    try:
        db.query(FillingStatusLog).delete()
        db.commit()
        fl_svc.process_tick(db, _status(True)); db.commit()
        fl_svc.process_tick(db, _status(False)); db.commit()
        fl_svc.process_tick(db, _status(False, clean_flushing=True)); db.commit()
        fl_svc.process_tick(db, _status(True)); db.commit()

        rows = db.execute(
            __import__("sqlalchemy").select(FillingStatusLog).order_by(FillingStatusLog.started_at)
        ).scalars().all()
        assert [r.status for r in rows] == [
            fl_svc.STATUS_RUNNING, fl_svc.STATUS_STOPPED, fl_svc.STATUS_CIP, fl_svc.STATUS_RUNNING]
        for prev, cur in zip(rows, rows[1:]):
            assert prev.ended_at == cur.started_at
    finally:
        db.close()
