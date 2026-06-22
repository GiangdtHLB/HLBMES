"""Lỗi nghiệp vụ -> ánh xạ sang HTTP ở tầng router."""


class DomainError(Exception):
    """Lỗi quy tắc nghiệp vụ (HTTP 409/400)."""


class NotFoundError(Exception):
    """Không tìm thấy entity (HTTP 404)."""


class PermissionError_(Exception):
    """Vi phạm quyền/segregation of duties (HTTP 403)."""
