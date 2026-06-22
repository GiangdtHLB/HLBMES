"""Master data: Product, Material. SoR là ERP/PLM trong thực tế; ở MVP
ta giữ bản sao có version/effective date (tài liệu §5.2, §8.1)."""

from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ..common import new_id
from ..database import Base


class Product(Base):
    __tablename__ = "product"

    product_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    uom: Mapped[str] = mapped_column(String, default="L")
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class Material(Base):
    __tablename__ = "material"

    material_id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    uom: Mapped[str] = mapped_column(String, default="kg")
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # malt/hop/yeast/packaging...
