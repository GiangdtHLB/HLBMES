"""Test Phase 5 — EBR neo ở lô thành phẩm (BatchPackLot, blueprint mới): gộp audit/QC/deviation
của TOÀN BỘ cây genealogy ngược (lô TP -> lô lọc -> tank -> mẻ nấu) vào 1 hồ sơ, ký điện tử +
khóa hồ sơ (snapshot bất biến). Đường EBR cũ (scope "batch" của BatchExecution gốc,
services/ebr.py::assemble/sign/lock) không đổi gì — xem test_batch_stage_qc.py/test_batch_pipeline.py
cho các phần khác của pipeline mới.
"""

import os
import tempfile

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["MES_DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["MES_DEV_HEADER_AUTH"] = "0"
os.environ["MES_RL_ENABLED"] = "0"
os.environ["MES_ADMIN_PASSWORD"] = "AdminTest123"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed as seed_mod


@pytest.fixture(scope="module", autouse=True)
def _seeded():
    seed_mod.seed()
    yield


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture(scope="module")
def admin_h(client):
    return _login(client, "admin", "AdminTest123")


def _make_batch(client, admin_h, batch_code):
    rid = client.get("/api/recipes", headers=admin_h).json()[0]["recipe_id"]
    vers = client.get(f"/api/recipes/{rid}/versions", headers=admin_h).json()
    v = next(v for v in vers if v["state"] == "effective")
    oid = client.get("/api/brewing/orders", headers=admin_h).json()[0]["brew_order_id"]
    b = client.post("/api/batches", headers=admin_h,
                    json={"order_id": oid, "recipe_version_id": v["version_id"],
                          "batch_code": batch_code, "planned_qty": 1000, "allow_shortage": True})
    assert b.status_code == 201, b.text
    return b.json()["batch_id"]


def _run_batch_to_completed(client, admin_h, batch_id, actual_qty=None):
    for target in ("ready", "running"):
        r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": target})
        assert r.status_code == 200, r.text
    if actual_qty is None:
        actual_qty = client.get(f"/api/batches/{batch_id}", headers=admin_h).json()["planned_qty"]
    aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": actual_qty})
    assert aq.status_code == 200, aq.text
    fin = client.post(f"/api/batches/{batch_id}/finish", headers=admin_h, json={})
    assert fin.status_code == 200, fin.text
    r = client.post(f"/api/batches/{batch_id}/transition", headers=admin_h, json={"target": "completed"})
    assert r.status_code == 200, r.text
    return r.json()


def _build_chain(client, admin_h, suffix):
    """mẻ nấu (chạy xong -> completed) -> tank -> lô lọc (đã kết thúc) -> lô TP, trả về
    (batch_id, tank_id, filter_lot_id, pack_lot_id)."""
    batch_id = _make_batch(client, admin_h, None)
    _run_batch_to_completed(client, admin_h, batch_id)
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-EBR-{suffix}"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-EBR-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-EBR-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}],
                          "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": 500, "pack_lot_code": f"PKG-EBR-{suffix}", "lot_no": f"LOT-EBR-{suffix}"})
    assert pack.status_code == 201, pack.text
    return batch_id, tank_id, filter_lot_id, pack.json()["pack_lot_id"]


def test_ebr_assembles_whole_upstream_tree(client, admin_h):
    batch_id, tank_id, filter_lot_id, pack_lot_id = _build_chain(client, admin_h, "TREE1")

    ebr = client.get(f"/api/batch-pack-lots/{pack_lot_id}/ebr", headers=admin_h)
    assert ebr.status_code == 200, ebr.text
    data = ebr.json()
    node_ids = {n["id"] for n in data["core"]["nodes"]}
    assert pack_lot_id in node_ids
    assert filter_lot_id in node_ids
    assert tank_id in node_ids
    assert batch_id in node_ids
    assert data["locked"] is False
    assert data["snapshot"] is None
    # bước tạo mẻ/tank/lô lọc/lô TP đều xuất hiện trong step-by-step gộp
    actions = {s["action"] for s in data["core"]["steps"]}
    assert "create" in actions


def test_ebr_includes_qc_from_every_node_in_tree(client, admin_h):
    param = client.post("/api/qc/parameters", headers=admin_h,
                        json={"code": "CT_EBRTREE", "name": "Chỉ tiêu EBR tree", "lsl": 1, "usl": 10})
    assert param.status_code == 201, param.text
    param_id = param.json()["param_id"]
    group = client.post("/api/qc/groups", headers=admin_h, json={"code": "GRP_EBRTREE", "name": "Nhóm EBR tree"})
    group_id = group.json()["group_id"]
    client.post(f"/api/qc/groups/{group_id}/items", headers=admin_h, json={"param_id": param_id, "mandatory": True})
    link = client.post("/api/qc/stage-groups", headers=admin_h,
                       json={"stage": "loc", "group_id": group_id, "mandatory": True})
    assert link.status_code == 201, link.text

    batch_id, tank_id, filter_lot_id, pack_lot_id = _build_chain(client, admin_h, "TREE2")
    rec = client.post("/api/brewing/qc-results", headers=admin_h,
                      json={"stage": "loc", "scope_type": "batch_filter_lot", "scope_id": filter_lot_id,
                            "parameter": "CT_EBRTREE", "value": 5, "lower_limit": 1, "upper_limit": 10})
    assert rec.status_code == 201, rec.text

    ebr = client.get(f"/api/batch-pack-lots/{pack_lot_id}/ebr", headers=admin_h).json()
    qc_rows = [q for q in ebr["core"]["quality"] if q["node_id"] == filter_lot_id]
    assert len(qc_rows) == 1 and qc_rows[0]["parameter"] == "CT_EBRTREE"

    client.delete(f"/api/qc/stage-groups/{link.json()['link_id']}", headers=admin_h)


def test_ebr_sign_and_lock_snapshot(client, admin_h):
    _batch_id, _tank_id, _filter_lot_id, pack_lot_id = _build_chain(client, admin_h, "SIGN1")

    sign = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/sign", headers=admin_h,
                       json={"password": "AdminTest123", "meaning": "Xác nhận thực thi"})
    assert sign.status_code == 200, sign.text
    assert sign.json()["signed"] is True

    wrong_pw = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/sign", headers=admin_h,
                           json={"password": "wrong", "meaning": "x"})
    assert wrong_pw.status_code == 403, wrong_pw.text

    lock = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "Phê duyệt release"})
    assert lock.status_code == 200, lock.text
    assert lock.json()["locked"] is True and lock.json()["snapshot_version"] == 1

    ebr_after = client.get(f"/api/batch-pack-lots/{pack_lot_id}/ebr", headers=admin_h).json()
    assert ebr_after["locked"] is True
    assert ebr_after["snapshot"]["version"] == 1
    assert ebr_after["snapshot"]["hash"] == ebr_after["current_hash"]
    assert len(ebr_after["signatures"]) == 1

    dup_lock = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/lock", headers=admin_h,
                           json={"password": "AdminTest123", "reason": "again"})
    assert dup_lock.status_code == 409, dup_lock.text

    diff = client.get(f"/api/batch-pack-lots/{pack_lot_id}/ebr/diff", headers=admin_h).json()
    assert diff["matches"] is True
    assert diff["changes"] == []


def test_ebr_diff_reports_exactly_what_changed_after_lock(client, admin_h):
    """"Toàn vẹn" chỉ báo hash lệch, không cho biết đã đổi gì — /ebr/diff phải chỉ đúng bước
    audit MỚI phát sinh sau khóa (ai/lúc nào/hành động gì), mirror đúng cách đã tra thủ công cho
    PKG-934995 (yêu cầu người dùng 2026-09-01: "cho tôi cách nào đó để tra lại nếu nó khác thì
    khác vì lý do gì"). Giả lập 1 thay đổi ngoài luồng (ghi thẳng audit log, đúng kịch bản đã xảy
    ra thật khi lock_pack_lot còn chưa cascade khóa — nay không còn tái diễn được qua API nữa vì
    mọi endpoint sửa đều đã bị chặn, xem test_lock_cascades_immutability_to_whole_chain)."""
    _batch_id, _tank_id, _filter_lot_id, pack_lot_id = _build_chain(client, admin_h, "DIFF1")
    lock = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "test"})
    assert lock.status_code == 200, lock.text

    from app.audit import record_audit
    from app.database import SessionLocal
    from app.security import User as SecurityUser
    db2 = SessionLocal()
    record_audit(db2, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="test_out_of_band",
                actor=SecurityUser(username="admin", role="admin"), after={"x": 1})
    db2.commit()
    db2.close()

    diff = client.get(f"/api/batch-pack-lots/{pack_lot_id}/ebr/diff", headers=admin_h).json()
    assert diff["matches"] is False
    added = [c for c in diff["changes"] if c["kind"] == "step_added"]
    assert any(c["step"]["action"] == "test_out_of_band" and c["step"]["by"] == "admin" for c in added)


def test_ebr_diff_material_and_qty_steps_carry_full_before_after_detail(client, admin_h):
    """Trước đây "material_delete" không ghi before/after gì cả (chỉ có tên hành động, không rõ
    xóa vật tư gì/lô nào/bao nhiêu), và "set_actual_qty" chỉ có giá trị SAU chứ không có giá trị
    TRƯỚC — /ebr/diff phải trả đủ để người dùng biết chính xác đã đổi gì (yêu cầu người dùng
    2026-09-01: "chưa rõ delete gì, mã vật tư gì, tên vật tư gì, nếu sửa thì sửa gì, trước là bao
    nhiêu, sau sửa là bao nhiêu, công đoạn nào")."""
    batch_id, _tank_id, filter_lot_id, pack_lot_id = _build_chain(client, admin_h, "DIFF2")

    add = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                      json={"material_name": "CO2 test diff", "quantity": 3, "uom": "kg"})
    assert add.status_code == 201, add.text
    usage_id = add.json()["usage_id"]

    lock = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "test"})
    assert lock.status_code == 200, lock.text

    # Mô phỏng đúng kịch bản đã xảy ra thật (xóa NVL + sửa SL thực tế SAU khi đã khóa) bằng cách
    # ghi thẳng DB — gọi qua API/service thật sẽ tự chặn đúng (đã có test riêng ở
    # test_lock_cascades_immutability_to_whole_chain), nên phải bypass y hệt cách lỗi cũ đã lọt
    # qua để tạo dữ liệu giả lập cho test này.
    from app.audit import record_audit
    from app.database import SessionLocal
    from app.models.batch_pipeline import BatchPackLotMaterialUsage
    from app.models.batches import BatchExecution
    from app.security import User as SecurityUser
    db2 = SessionLocal()
    fake_user = SecurityUser(username="admin", role="admin")
    u = db2.get(BatchPackLotMaterialUsage, usage_id)
    mat_before = {"material_name": u.material_name, "lot_pm": u.lot_pm, "quantity": u.quantity, "uom": u.uom}
    db2.delete(u)
    record_audit(db2, entity_type="batch_pack_lot", entity_id=pack_lot_id, action="material_delete",
                actor=fake_user, before=mat_before)
    batch = db2.get(BatchExecution, batch_id)
    before_qty = batch.actual_qty
    batch.actual_qty = 42.0
    record_audit(db2, entity_type="batch", entity_id=batch_id, action="set_actual_qty",
                actor=fake_user, before={"actual_qty": before_qty}, after={"actual_qty": 42.0})
    db2.commit()
    db2.close()

    diff = client.get(f"/api/batch-pack-lots/{pack_lot_id}/ebr/diff", headers=admin_h).json()
    steps = {c["step"]["action"]: c["step"] for c in diff["changes"] if c["kind"] == "step_added"}

    mat_step = steps["material_delete"]
    assert mat_step["node_type"] == "batch_pack_lot"
    assert mat_step["stage_label"] == "Thành phẩm"
    assert mat_step["before"] == {"material_name": "CO2 test diff", "lot_pm": None, "quantity": 3.0, "uom": "kg"}

    qty_step = steps["set_actual_qty"]
    assert qty_step["node_type"] == "batch"
    assert qty_step["stage_label"] == "Nấu"
    assert qty_step["before"]["actual_qty"] == 1000.0
    assert qty_step["detail"]["actual_qty"] == 42.0


def test_lock_cascades_immutability_to_whole_chain(client, admin_h):
    """Khóa hồ sơ EBR ở lô thành phẩm phải khóa BẤT BIẾN cả cây genealogy ngược (mẻ nấu -> tank
    lên men -> lô lọc -> lô thành phẩm) — trước đây lock_pack_lot CHỈ tạo EBRSnapshot, không đụng
    cột `.locked`/`.ebr_locked` của từng bản ghi nên mọi cổng chặn sửa có sẵn (xóa/thêm NVL/sửa
    SL/ghi chỉ tiêu...) không bao giờ được kích hoạt — sửa được cả sau khi "đã khóa" (yêu cầu
    người dùng 2026-09-01)."""
    batch_id, tank_id, filter_lot_id, pack_lot_id = _build_chain(client, admin_h, "LOCKCASCADE1")

    # Trước khi khóa: các thao tác này đều phải chạy được (baseline, tránh false positive).
    ok_mat = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                         json={"material_name": "NVL trước khóa", "quantity": 1, "uom": "kg"})
    assert ok_mat.status_code == 201, ok_mat.text
    client.delete(f"/api/batch-filter-lots/materials/{ok_mat.json()['usage_id']}", headers=admin_h)

    lock = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "test cascade"})
    assert lock.status_code == 200, lock.text

    # Lô thành phẩm: sửa SL/NVL bị chặn.
    blocked_qty = client.put(f"/api/batch-pack-lots/{pack_lot_id}/qty", headers=admin_h, json={"qty": 999})
    assert blocked_qty.status_code == 409, blocked_qty.text
    blocked_pk_mat = client.post(f"/api/batch-pack-lots/{pack_lot_id}/materials", headers=admin_h,
                                 json={"material_name": "sau khóa", "quantity": 1, "uom": "kg"})
    assert blocked_pk_mat.status_code == 409, blocked_pk_mat.text

    # Lô lọc: thêm NVL bị chặn.
    blocked_fl_mat = client.post(f"/api/batch-filter-lots/{filter_lot_id}/materials", headers=admin_h,
                                 json={"material_name": "sau khóa", "quantity": 1, "uom": "kg"})
    assert blocked_fl_mat.status_code == 409, blocked_fl_mat.text

    # Tank lên men: sửa SL thực tế của mẻ nấu đã gộp vào tank bị chặn.
    blocked_aq = client.post(f"/api/batches/{batch_id}/actual-qty", headers=admin_h, json={"actual_qty": 123})
    assert blocked_aq.status_code == 409, blocked_aq.text

    # Tank lên men: ghi chép lên men (bảng theo ngày) bị chặn.
    blocked_reading = client.put(f"/api/batch-tanks/{tank_id}/process-log/readings", headers=admin_h,
                                 json={"readings": [{"day_no": 1, "nhiet_do_c": 10}]})
    assert blocked_reading.status_code == 409, blocked_reading.text

    # Ghi chỉ tiêu QC cho tank (len_men_chinh) bị chặn.
    blocked_qc_tank = client.post("/api/brewing/qc-results", headers=admin_h,
                                  json={"stage": "len_men_chinh", "scope_type": "batch_tank",
                                        "scope_id": f"{tank_id}__len_men_chinh",
                                        "parameter": "X", "value": 1})
    assert blocked_qc_tank.status_code == 409, blocked_qc_tank.text

    # Ghi chỉ tiêu QC cho lô lọc/lô thành phẩm cũng bị chặn.
    blocked_qc_fl = client.post("/api/brewing/qc-results", headers=admin_h,
                                json={"stage": "loc", "scope_type": "batch_filter_lot",
                                      "scope_id": filter_lot_id, "parameter": "X", "value": 1})
    assert blocked_qc_fl.status_code == 409, blocked_qc_fl.text
    blocked_qc_pk = client.post("/api/brewing/qc-results", headers=admin_h,
                                json={"stage": "thanh_pham", "scope_type": "batch_pack_lot",
                                      "scope_id": pack_lot_id, "parameter": "X", "value": 1})
    assert blocked_qc_pk.status_code == 409, blocked_qc_pk.text


def test_empty_tank_and_filter_lot_allowed_after_ebr_lock(client, admin_h):
    """"Làm rỗng tank" (tank lên men VÀ tank BBT/lô lọc, thao tác ở màn Lô thành phẩm) phải vẫn
    làm được dù hồ sơ EBR đã khóa — CỐ Ý không theo quy tắc bất biến chung, vì sai số đo lường
    lúc lọc/chiết khiến tồn không bao giờ về đúng 0.0 tuyệt đối (yêu cầu người dùng 2026-09-01).
    Vẫn phải tôn trọng ngưỡng dung sai cấu hình — residual > ngưỡng vẫn bị chặn dù không khóa."""
    suffix = "EMPTYAFTERLOCK1"
    batch_id = _make_batch(client, admin_h, None)
    _run_batch_to_completed(client, admin_h, batch_id, actual_qty=901)  # tank on_hand sẽ còn dư nhỏ
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-EBR-{suffix}"})
    assert tank.status_code == 201, tank.text
    tank_id = tank.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-EBR-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    assert bbt.status_code == 201, bbt.text
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-EBR-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw.status_code == 201, draw.text
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    # Rút 900 hl -> tank còn dư 1 hl (trong ngưỡng mặc định 2.0 hl).
    fin = client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
                     json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}],
                          "nuoc_bai_khi_hl": 0})
    assert fin.status_code == 200, fin.text
    tank_after_draw = client.get(f"/api/batch-tanks/{tank_id}", headers=admin_h).json()
    assert abs(tank_after_draw["on_hand"] - 1.0) < 1e-6

    # volume_hl lô lọc = 900 hl (đã rút) -> tách lô TP 89895 lít (898.95 hl) để còn dư 1.05 hl
    # (trong ngưỡng mặc định 2.0 hl).
    pack = client.post(f"/api/batch-filter-lots/{filter_lot_id}/pack-lots", headers=admin_h,
                       json={"qty": 89895, "pack_lot_code": f"PKG-EBR-{suffix}", "lot_no": f"LOT-EBR-{suffix}"})
    assert pack.status_code == 201, pack.text
    pack_lot_id = pack.json()["pack_lot_id"]
    fl_after_split = client.get(f"/api/batch-filter-lots/{filter_lot_id}", headers=admin_h).json()
    assert abs(fl_after_split["on_hand"] - 1.05) < 1e-6

    lock = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "test empty-after-lock"})
    assert lock.status_code == 200, lock.text

    # Vẫn "làm rỗng" được dù đã khóa — vì trong ngưỡng dung sai.
    empty_tank = client.post(f"/api/batch-tanks/{tank_id}/empty", headers=admin_h)
    assert empty_tank.status_code == 200, empty_tank.text
    assert empty_tank.json()["on_hand"] == 0.0
    empty_fl = client.post(f"/api/batch-filter-lots/{filter_lot_id}/empty", headers=admin_h)
    assert empty_fl.status_code == 200, empty_fl.text
    assert empty_fl.json()["on_hand"] == 0.0

    # Nhưng thao tác thực chất khác (sửa SL) vẫn bị chặn như bình thường — chỉ "làm rỗng" mới
    # được miễn trừ.
    blocked_qty = client.put(f"/api/batch-pack-lots/{pack_lot_id}/qty", headers=admin_h, json={"qty": 999})
    assert blocked_qty.status_code == 409, blocked_qty.text


def test_empty_filter_lot_rejects_residual_beyond_tolerance(client, admin_h):
    suffix = "EMPTYTOLBREACH1"
    batch_id = _make_batch(client, admin_h, None)
    _run_batch_to_completed(client, admin_h, batch_id, actual_qty=1000)
    tank = client.post("/api/batch-tanks", headers=admin_h,
                       json={"batch_ids": [batch_id], "tank_code": f"TANK-EBR-{suffix}"})
    tank_id = tank.json()["tank_id"]
    bbt = client.post("/api/lines", headers=admin_h,
                      json={"code": f"BBT-EBR-{suffix}", "name": f"Tank thành phẩm {suffix}", "kind": "tank_bbt"})
    draw = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": f"FLOT-EBR-{suffix}", "to_bbt": bbt.json()["code"],
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    filter_lot_id = draw.json()["filter_lot_id"]
    src = client.get(f"/api/batch-filter-lots/{filter_lot_id}/sources", headers=admin_h).json()[0]
    batches = client.get(f"/api/batch-filter-lots/{filter_lot_id}/batches", headers=admin_h).json()
    client.put(f"/api/batch-filter-lots/batches/{batches[0]['batch_link_id']}/finish", headers=admin_h,
              json={"draws": [{"source_link_id": src["link_id"], "dich_nha_hl": 900}], "nuoc_bai_khi_hl": 0})
    # Chưa tách lô TP nào -> lô lọc còn dư nguyên 900 hl, vượt xa ngưỡng mặc định 2.0 hl.
    over = client.post(f"/api/batch-filter-lots/{filter_lot_id}/empty", headers=admin_h)
    assert over.status_code == 409, over.text
    assert "vượt ngưỡng" in over.json()["detail"]


def test_lock_pack_lot_also_creates_standalone_batch_snapshot(client, admin_h):
    """Khóa hồ sơ EBR ở lô thành phẩm phải kích hoạt LUÔN khóa EBR (snapshot RIÊNG, có version/
    hash/locked_by, không chỉ cờ ebr_locked=True suông) cho từng mẻ nấu (BatchExecution) trong
    cây genealogy ngược — trước đây _cascade_lock chỉ set cờ, GET .../batches/{id}/ebr báo "đã
    khóa" nhưng "snapshot" luôn null (yêu cầu người dùng 2026-09-02: "khóa ở chiết thì mặc định
    khóa EBR ở mẻ sản xuất được kích hoạt để lấy snapshot")."""
    batch_id, tank_id, filter_lot_id, pack_lot_id = _build_chain(client, admin_h, "BATCHSNAP1")

    before = client.get(f"/api/batches/{batch_id}/ebr", headers=admin_h).json()
    assert before["locked"] is False
    assert before["snapshot"] is None

    lock = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "test batch snapshot cascade"})
    assert lock.status_code == 200, lock.text

    after = client.get(f"/api/batches/{batch_id}/ebr", headers=admin_h).json()
    assert after["locked"] is True
    assert after["snapshot"] is not None
    assert after["snapshot"]["version"] == 1
    assert after["snapshot"]["locked_by"] == "admin"

    # Đã có snapshot riêng rồi thì không được double-lock qua đường batch-scope cũ nữa.
    dup = client.post(f"/api/batches/{batch_id}/ebr/lock", headers=admin_h,
                      json={"password": "AdminTest123", "reason": "dup"})
    assert dup.status_code == 409, dup.text


def test_lock_pack_lot_also_creates_tank_and_filter_lot_snapshots(client, admin_h):
    """Khóa hồ sơ EBR ở lô thành phẩm phải kích hoạt LUÔN snapshot RIÊNG cho Tank lên men VÀ Lô
    lọc trong cây (không chỉ set cờ `.locked` suông) — mirror mẻ nấu (yêu cầu người dùng
    2026-09-02: "khóa ở chiết thì mặc định mẻ sản xuất, lên men, lọc, chiết sẽ snapshot phải
    không"). Rút THÊM từ tank/lô lọc đã khóa (cho lô thành phẩm/lô lọc KHÁC sau đó) vẫn phải làm
    được bình thường — không bị chặn, và KHÔNG tạo thêm snapshot thứ 2 (core không gồm on_hand,
    chỉ tạo đúng 1 lần — yêu cầu người dùng 2026-09-02: "nhiều snapshot quá sẽ gây nhiễu", và
    "tank chưa rút hết dịch... có tạo được lô lọc khác, rút tiếp được không")."""
    from app.database import SessionLocal
    from app.models.batch_pipeline import BatchFilterLot, BatchTank
    from app.models.signature import EBRSnapshot

    batch_id, tank_id, filter_lot_id, pack_lot_id = _build_chain(client, admin_h, "TANKFLSNAP1")
    lock = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "test tank/filter_lot snapshot"})
    assert lock.status_code == 200, lock.text

    db2 = SessionLocal()
    tank = db2.get(BatchTank, tank_id)
    fl = db2.get(BatchFilterLot, filter_lot_id)
    assert tank.locked is True and tank.locked_by == "admin" and tank.locked_at is not None
    assert fl.locked is True and fl.locked_by == "admin" and fl.locked_at is not None
    tank_snaps = db2.query(EBRSnapshot).filter(EBRSnapshot.batch_id == tank_id).all()
    fl_snaps = db2.query(EBRSnapshot).filter(EBRSnapshot.batch_id == filter_lot_id).all()
    assert len(tank_snaps) == 1
    assert tank_snaps[0].snapshot_version == 1
    assert "on_hand" not in tank_snaps[0].content
    assert len(fl_snaps) == 1
    assert fl_snaps[0].snapshot_version == 1
    assert "on_hand" not in fl_snaps[0].content
    db2.close()

    # Tank vẫn còn dư dịch (chưa rút hết) -> tạo được lô lọc KHÁC, rút tiếp bình thường dù tank
    # đã bị khóa từ lô thành phẩm trước.
    bbt2 = client.post("/api/lines", headers=admin_h,
                       json={"code": "BBT-TANKFLSNAP1-2", "name": "BBT snap2", "kind": "tank_bbt"})
    assert bbt2.status_code == 201, bbt2.text
    draw2 = client.post("/api/batch-filter-lots", headers=admin_h, json={
        "filter_lot_code": "FLOT-TANKFLSNAP1-2", "to_bbt": "BBT-TANKFLSNAP1-2",
        "sources": [{"source_type": "tank", "source_tank_id": tank_id}],
    })
    assert draw2.status_code == 201, draw2.text
    filter_lot_id2 = draw2.json()["filter_lot_id"]
    src2 = client.get(f"/api/batch-filter-lots/{filter_lot_id2}/sources", headers=admin_h).json()[0]
    batches2 = client.get(f"/api/batch-filter-lots/{filter_lot_id2}/batches", headers=admin_h).json()
    fin2 = client.put(f"/api/batch-filter-lots/batches/{batches2[0]['batch_link_id']}/finish", headers=admin_h,
                      json={"draws": [{"source_link_id": src2["link_id"], "dich_nha_hl": 50}],
                           "nuoc_bai_khi_hl": 0})
    assert fin2.status_code == 200, fin2.text

    # Vẫn đúng 1 snapshot duy nhất cho tank — không nhân bản dù đã dùng thêm sau khi khóa.
    db3 = SessionLocal()
    tank_snaps2 = db3.query(EBRSnapshot).filter(EBRSnapshot.batch_id == tank_id).all()
    assert len(tank_snaps2) == 1
    db3.close()


def test_tank_and_filter_lot_ebr_endpoints(client, admin_h):
    """GET /batch-tanks/{id}/ebr và GET /batch-filter-lots/{id}/ebr (yêu cầu người dùng
    2026-09-02: "có bổ sung cho tôi" — nút Hồ sơ EBR cho Lên men/Lọc) — trước khi khóa báo
    "chưa khóa"/snapshot=null; sau khi khóa (qua cascade từ Chiết) báo "đã khóa" kèm snapshot,
    hash khớp với hash hiện tại (core live vẫn khớp bản đã chốt vì chưa sửa gì thêm)."""
    batch_id, tank_id, filter_lot_id, pack_lot_id = _build_chain(client, admin_h, "TANKFLENDPOINT1")

    before_tank = client.get(f"/api/batch-tanks/{tank_id}/ebr", headers=admin_h).json()
    assert before_tank["locked"] is False
    assert before_tank["snapshot"] is None
    before_fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}/ebr", headers=admin_h).json()
    assert before_fl["locked"] is False
    assert before_fl["snapshot"] is None

    lock = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/lock", headers=admin_h,
                       json={"password": "AdminTest123", "reason": "test endpoints"})
    assert lock.status_code == 200, lock.text

    after_tank = client.get(f"/api/batch-tanks/{tank_id}/ebr", headers=admin_h).json()
    assert after_tank["locked"] is True
    assert after_tank["snapshot"]["version"] == 1
    assert after_tank["snapshot"]["locked_by"] == "admin"
    assert after_tank["snapshot"]["hash"] == after_tank["current_hash"]
    assert after_tank["core"]["tank_code"]

    after_fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}/ebr", headers=admin_h).json()
    assert after_fl["locked"] is True
    assert after_fl["snapshot"]["version"] == 1
    assert after_fl["snapshot"]["hash"] == after_fl["current_hash"]
    assert after_fl["core"]["filter_lot_code"]


def test_manual_sign_and_lock_tank_and_filter_lot(client, admin_h):
    """Tank lên men VÀ Lô lọc phải tự Ký/Khóa hồ sơ EBR riêng được (không cần đợi Chiết cascade)
    — yêu cầu người dùng 2026-09-02: "có cần ký" (có). Ký chỉ lưu chữ ký (không khóa/không tạo
    snapshot); Khóa mới tạo snapshot thật + set .locked. Khóa lần 2 phải bị chặn (409, mirror
    lock()/lock_pack_lot())."""
    batch_id, tank_id, filter_lot_id, pack_lot_id = _build_chain(client, admin_h, "MANUALSIGN1")

    sign_tank = client.post(f"/api/batch-tanks/{tank_id}/ebr/sign", headers=admin_h,
                            json={"password": "AdminTest123", "meaning": "Xác nhận lên men đạt", "reason": ""})
    assert sign_tank.status_code == 200, sign_tank.text
    assert sign_tank.json()["signed"] is True
    # Ký xong vẫn CHƯA khóa — không tạo snapshot.
    still_unlocked = client.get(f"/api/batch-tanks/{tank_id}/ebr", headers=admin_h).json()
    assert still_unlocked["locked"] is False
    assert still_unlocked["snapshot"] is None

    lock_tank = client.post(f"/api/batch-tanks/{tank_id}/ebr/lock", headers=admin_h,
                           json={"password": "AdminTest123", "reason": "Lên men hoàn tất"})
    assert lock_tank.status_code == 200, lock_tank.text
    assert lock_tank.json()["locked"] is True
    assert lock_tank.json()["snapshot_version"] == 1

    locked_tank = client.get(f"/api/batch-tanks/{tank_id}/ebr", headers=admin_h).json()
    assert locked_tank["locked"] is True
    assert locked_tank["snapshot"]["version"] == 1
    assert locked_tank["snapshot"]["hash"] == locked_tank["current_hash"]

    dup_tank = client.post(f"/api/batch-tanks/{tank_id}/ebr/lock", headers=admin_h,
                           json={"password": "AdminTest123", "reason": "dup"})
    assert dup_tank.status_code == 409, dup_tank.text

    # Mirror cho Lô lọc.
    sign_fl = client.post(f"/api/batch-filter-lots/{filter_lot_id}/ebr/sign", headers=admin_h,
                          json={"password": "AdminTest123", "meaning": "Xác nhận lọc đạt", "reason": ""})
    assert sign_fl.status_code == 200, sign_fl.text
    lock_fl = client.post(f"/api/batch-filter-lots/{filter_lot_id}/ebr/lock", headers=admin_h,
                         json={"password": "AdminTest123", "reason": "Lọc hoàn tất"})
    assert lock_fl.status_code == 200, lock_fl.text
    locked_fl = client.get(f"/api/batch-filter-lots/{filter_lot_id}/ebr", headers=admin_h).json()
    assert locked_fl["locked"] is True
    assert locked_fl["snapshot"]["version"] == 1
    dup_fl = client.post(f"/api/batch-filter-lots/{filter_lot_id}/ebr/lock", headers=admin_h,
                        json={"password": "AdminTest123", "reason": "dup"})
    assert dup_fl.status_code == 409, dup_fl.text

    # Khóa thủ công RỒI khóa lô thành phẩm (Chiết) SAU đó — cascade phải tự bỏ qua tank/lô lọc
    # đã khóa thủ công (không tạo snapshot thứ 2, không raise lỗi gì).
    lock_pack = client.post(f"/api/batch-pack-lots/{pack_lot_id}/ebr/lock", headers=admin_h,
                           json={"password": "AdminTest123", "reason": "test cascade after manual lock"})
    assert lock_pack.status_code == 200, lock_pack.text
    from app.database import SessionLocal
    from app.models.signature import EBRSnapshot
    db2 = SessionLocal()
    tank_snaps = db2.query(EBRSnapshot).filter(EBRSnapshot.batch_id == tank_id).all()
    fl_snaps = db2.query(EBRSnapshot).filter(EBRSnapshot.batch_id == filter_lot_id).all()
    assert len(tank_snaps) == 1
    assert len(fl_snaps) == 1
    db2.close()


def test_tank_ebr_reports_locked_without_snapshot_for_legacy_data(client, admin_h):
    """Dữ liệu ĐÃ khóa (`.locked=True`) qua cascade TRƯỚC khi tính năng snapshot riêng cho tank
    được xây (2026-09-02) sẽ không có EBRSnapshot đứng tên nó — assemble_tank phải trả về
    locked=True, snapshot=None (KHÔNG được coi là "chưa khóa"), để frontend hiện đúng ghi chú
    "đã khóa nhưng không có snapshot" thay vì báo mâu thuẫn "ĐÃ KHÓA" lẫn "Chưa khóa" cùng lúc
    (phát hiện qua kiểm tra trực tiếp trên trình duyệt với dữ liệu cũ có sẵn)."""
    from app.database import SessionLocal
    from app.models.batch_pipeline import BatchTank

    batch_id, tank_id, _filter_lot_id, _pack_lot_id = _build_chain(client, admin_h, "LEGACYLOCK1")
    db2 = SessionLocal()
    tank = db2.get(BatchTank, tank_id)
    tank.locked = True  # mô phỏng cascade CŨ (trước bản vá) — chỉ set cờ, không tạo snapshot
    db2.commit()
    db2.close()

    ebr = client.get(f"/api/batch-tanks/{tank_id}/ebr", headers=admin_h)
    assert ebr.status_code == 200, ebr.text
    assert ebr.json()["locked"] is True
    assert ebr.json()["snapshot"] is None


def test_old_batch_scoped_ebr_untouched(client, admin_h):
    """Đường EBR cũ (BatchExecution gốc, scope 'batch') vẫn hoạt động y hệt, không bị ảnh
    hưởng bởi phần mới thêm cho scope 'batch_pack_lot'."""
    batch_id = _make_batch(client, admin_h, "1")
    ebr = client.get(f"/api/batches/{batch_id}/ebr", headers=admin_h)
    assert ebr.status_code == 200, ebr.text
    assert ebr.json()["core"]["batch_code"] == "1"
    assert ebr.json()["locked"] is False
