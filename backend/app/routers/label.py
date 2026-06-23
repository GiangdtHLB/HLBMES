"""Sinh tem mã (QR) cho pallet/case/lô — bổ sung cho Code39 (render JS phía client).

QR dựng bằng segno (thuần Python). Đầu đọc cầm tay quét được cả Code39 lẫn QR
(giải mã ở phần cứng → text → /api/scan), nên đây chỉ là phần IN/hiển thị tem.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ..errors import DomainError
from ..security import User, get_current_user

router = APIRouter(prefix="/api/label", tags=["label"])


@router.get("/qr")
def qr(data: str, scale: int = 4, user: User = Depends(get_current_user)):
    """Trả SVG mã QR cho chuỗi `data` (vd mã pallet/case)."""
    data = (data or "").strip()
    if not data:
        raise DomainError("Thiếu dữ liệu để sinh QR.")
    import segno
    qr = segno.make(data, error="m")
    svg = qr.svg_inline(scale=max(1, min(scale, 12)), border=2, dark="#000", light="#fff")
    return Response(content=svg, media_type="image/svg+xml")
