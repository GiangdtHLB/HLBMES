"""MES Bia Hạ Long - Nhà Máy Đông Mai — backend package.

Modular monolith theo khuyến nghị tài liệu MES-ARCH-002:
mỗi bounded context là một module models/routers/services riêng,
không truy cập trực tiếp database của module khác (qua service layer).
"""

__version__ = "0.1.0-mvp"
