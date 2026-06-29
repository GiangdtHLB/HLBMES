"""Master data: Product, Material. SoR là ERP/PLM trong thực tế; ở MVP
ta giữ bản sao có version/effective date (tài liệu §5.2, §8.1)."""

from typing import Optional

from sqlalchemy import Text, String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id
from ..database import Base


class Product(Base):
    __tablename__ = "product"

    product_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    uom: Mapped[str] = mapped_column(String(255), default="L")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Material(Base):
    __tablename__ = "material"

    material_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    uom: Mapped[str] = mapped_column(String(255), default="kg")
    category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # malt/hop/yeast/packaging...
