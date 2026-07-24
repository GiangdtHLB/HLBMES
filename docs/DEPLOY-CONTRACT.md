# DEPLOY CONTRACT — Migration phải chạy sạch trên SQL Server (production dialect)

> Mục tiêu: bên phát triển push code → bên vận hành `git pull` + deploy **không lỗi**.
> Production DB là **Microsoft SQL Server** (`mssql+pyodbc`, ODBC Driver 18). Dev/test hay
> dùng SQLite. **SQLite pass KHÔNG bảo đảm MSSQL pass** — nhiều lỗi chỉ lộ trên SQL Server.

## 0. Cổng bắt buộc trước khi merge vào `main`
Mỗi đợt migration mới PHẢI chạy thật trên SQL Server, không chỉ SQLite:

```
alembic upgrade <head-đang-chạy-trên-prod>   # đưa DB test tới đúng điểm prod
alembic upgrade head                          # áp toàn bộ migration mới
```

- Bên vận hành có sẵn harness: container SQL Server 2022 (`mssqltest`), DB `HLBMESTEST`.
- Nếu bên phát triển không có Docker/SQL Server: push lên **branch** (đừng push `main`),
  bên vận hành chạy cổng MSSQL rồi mới merge. FAIL → trả đúng migration + dòng lỗi.
- Giữ **1 head duy nhất**, không đổi `revision`/`down_revision` của migration đã deploy.
- KHÔNG gộp/tái sinh migration (audit trail 21 CFR Part 11 — giữ từng file).

## 1. Kiểu dữ liệu (bắt buộc)
| Dùng | Không dùng | Vì sao |
|------|-----------|--------|
| `sa.Unicode(length=N)` | `sa.String` | MSSQL `VARCHAR` mất dấu tiếng Việt ("QC đạt"→"QC dat") → vỡ hash-chain audit. `Unicode`→`NVARCHAR`. |
| `sa.UnicodeText` | `sa.Text` | Như trên cho cột dài. |
| luôn có `length=` cho cột PK/index/unique | `Unicode()` không length | MSSQL không PK/index được `NVARCHAR(MAX)`. |
| cột thời gian: `sa.DateTime(timezone=True)` | `sa.DateTime()` trần | Model dùng `UTCDateTime` (tz-aware) + app ghi `utcnow()` tz-aware. `DateTime()` trần → MSSQL tạo `DATETIME` (không offset); ghi tz-aware → 500 "Conversion failed converting date/time from character string". `timezone=True` → `DATETIMEOFFSET`. Xem migration `51e5e329b0d1`. |

## 2. Năm lớp lỗi MSSQL đã gặp & cách xử lý

**(A) SQL chỉ có ở SQLite.** `randomblob`, `hex()`, `strftime` không tồn tại trên MSSQL.
Sinh biểu thức theo dialect:
```python
_d = op.get_bind().dialect.name
_id  = {"sqlite":"lower(hex(randomblob(16)))",
        "postgresql":"replace(cast(gen_random_uuid() as text),'-','')"}.get(_d,
        "lower(replace(convert(varchar(36), newid()),'-',''))")   # mssql
_yr  = ("CAST(strftime('%Y', col) AS INTEGER)" if _d=="sqlite"
        else "EXTRACT(YEAR FROM col)" if _d=="postgresql" else "YEAR(col)")
```

**(B) DROP COLUMN vướng FK/DEFAULT.** MSSQL từ chối drop cột còn ràng buộc `FK__`/`DF__`
tự sinh. Gọi helper trước khi drop (no-op trên sqlite/postgres):
```python
from app.alembic_mssql import prep_drop_columns
prep_drop_columns(op.get_bind(), "table", ("col1", "col2"))
op.drop_column("table", "col1")
```

**(C) `alter_column(nullable=...)` thiếu `existing_type`.** MSSQL bắt buộc:
```python
batch_op.alter_column("col", existing_type=sa.Integer(), nullable=False)
```

**(D) ALTER COLUMN đổi kiểu trên cột có DEFAULT** → MSSQL error 5074. Gỡ DEFAULT →
đổi kiểu → gắn lại (dialect-aware; sqlite/postgres giữ `batch_alter_table`). Xem
`e1f2a3b4c5d8_aging_thresholds_float.py` làm mẫu.

**(E) `batch_alter_table(recreate='always')`** vỡ trên MSSQL với bảng được FK tham chiếu.
Dùng `recreate='auto'`.

## 3. Điều kiện DỮ LIỆU (cổng MSSQL trên DB rỗng KHÔNG bắt được)
Migration tạo `UNIQUE`/`NOT NULL`/`FK` chạy sạch trên DB test rỗng nhưng **fail trên prod
có sẵn dữ liệu vi phạm**. VD `create unique index recipe(product_id)` fail vì prod có 2
công thức cùng 1 product → xử lý dữ liệu (không sửa migration, không tự ý xoá data thật):
báo bên vận hành, thống nhất cách làm sạch/tách dữ liệu **trước** khi áp migration.
Nếu migration mới đặt ràng buộc chặt hơn dữ liệu hiện có, ghi rõ trong mô tả migration.

## 3b. Lỗi dialect TẦNG ỨNG DỤNG (query runtime — gate migration KHÔNG bắt được)
Không chỉ migration; **code truy vấn** cũng phải chạy trên MSSQL. Đã gặp:

- **`Column.is_(True)` / `.is_(False)` trên cột Boolean** → SQLAlchemy render `col IS 1`.
  MSSQL chỉ cho `IS NULL` → 500 `Incorrect syntax near '1'`. SQLite/Postgres thì chạy.
  **Dùng `Column == true()` / `== false()`** (`from sqlalchemy import true, false`) → render
  `col = 1`, chạy mọi dialect, sạch ruff E712. KHÔNG dùng `== True` (E712).
- **Ghi datetime tz-aware vào cột `DATETIME`** → 500 `Conversion failed when converting date
  and/or time from character string`. Gốc: migration tạo cột bằng `sa.DateTime()` trần (xem
  mục 1) → MSSQL ra `DATETIME` không nhận offset, trong khi app luôn ghi `utcnow()` tz-aware.
  Cột thời gian PHẢI `sa.DateTime(timezone=True)` → `DATETIMEOFFSET`. Vỡ ở đường GHI (POST/PUT
  "Thêm mẻ", "Lưu ngưỡng"…), GET không bắt được.
- Tránh raw SQL đặc thù dialect trong service: `LIMIT`/`OFFSET` thô (MSSQL: `TOP`/`OFFSET
  FETCH` — ưu tiên `.limit()`/`.offset()` của ORM), `strftime`/`randomblob`/`hex()`/`ilike`.
  Dùng `extract("year"/"month", col)` của SQLAlchemy (tự render `DATEPART` trên MSSQL) — OK.

Cách bắt (LÀM CẢ 2, vì bug ẩn ở cả đọc lẫn ghi):
1. **Smoke GET**: enumerate `/openapi.json`, gọi mọi route không path-param với token admin,
   gom HTTP 500. (Đợt trước quét 143 GET bắt trọn lớp `.is_(True)`.)
2. **Smoke GHI (POST/PUT)**: với các form chính (tạo mẻ, lưu cài đặt, nhập kho, tạo lệnh…)
   tạo 1 bản ghi thật trên DB test rồi xoá — lớp datetime→DATETIME CHỈ lộ ở đường ghi.

## 4. `alembic.ini` / URL
Mật khẩu SA test **không dùng ký tự đặc biệt** (`% @ ! /`) — ConfigParser của alembic.ini
nội suy `%` gây lỗi. File `.env`/`docker-compose.override.yml` (chứa secret) **không commit**.

## 5. Helper dùng chung
`backend/app/alembic_mssql.py` (KHÔNG đặt trong `alembic/versions/` vì Alembic quét mọi
`*.py` ở đó như 1 migration). Chứa `prep_drop_columns(conn, table, cols)`.

## 6. CHECKLIST tự kiểm trước khi push (bên phát triển)
Chạy hết list này rồi mới push branch — mỗi mục là 1 lỗi thực tế đã làm vỡ prod:

- [ ] Cột chuỗi: `Unicode(length=N)` / `UnicodeText`, KHÔNG `String`/`Text` (mục 1).
- [ ] Cột thời gian: `sa.DateTime(timezone=True)`, KHÔNG `sa.DateTime()` trần (mục 1 + 3b).
- [ ] Không SQL SQLite-only trong migration: `randomblob`/`strftime`/`hex` → dialect-aware (2A).
- [ ] `drop_column` cột có FK/DEFAULT → gọi `prep_drop_columns` trước (2B).
- [ ] `alter_column(nullable=...)` có `existing_type=` (2C); đổi kiểu cột có DEFAULT → mẫu 2D.
- [ ] `batch_alter_table` dùng `recreate='auto'`, không `'always'` (2E).
- [ ] Query code: `Column == true()/false()`, KHÔNG `.is_(True/False)` trên Boolean (3b).
- [ ] 1 head duy nhất; không sửa migration đã deploy; không gộp migration (mục 0).
- [ ] Migration đặt ràng buộc chặt hơn dữ liệu hiện có → ghi rõ trong docstring (mục 3).
- [ ] Không commit `.env` / `docker-compose.override.yml` / secret (mục 4).
- [ ] Nếu chạy được MSSQL: `alembic upgrade <head-prod> → head` + smoke GET & GHI (3b).
      Nếu KHÔNG có MSSQL: push branch, báo bên vận hành chạy cổng giúp.
