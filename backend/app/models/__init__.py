"""Tập hợp toàn bộ ORM model để metadata.create_all() nhìn thấy.

Mỗi nhóm file tương ứng một bounded context (tài liệu §6.2):
master, orders, recipes, batches, materials, quality, audit.
"""

from .audit import AuditLog
from .auth import User, UserSession
from .batches import BatchExecution
from .brewing import (
    BottleRecord,
    BrewRecord,
    FermentRecord,
    FilterRecord,
    MaterialReceipt,
    StageIndicator,
)
from .energy import EnergyArea, EnergyGroup, EnergyReading
from .historian import HistorianPoint
from .integration import ApiKey, Webhook
from .maintenance import Calibration, Equipment, Incident, MaintenancePlan, SparePart
from .master import Material, Product
from .materials import GenealogyEdge, MaterialLot
from .metrics import OEERecord, ProcessReading
from .orders import ProductionOrder
from .process import ChemicalUsage, YeastIssue, YeastLot
from .quality import Deviation, QualityResult
from .recipes import Recipe, RecipeVersion
from .signature import EBRSnapshot, Signature
from .warehouse import StockMovement
from .workorder import WorkOrder

__all__ = [
    "AuditLog",
    "BatchExecution",
    "BottleRecord",
    "BrewRecord",
    "FermentRecord",
    "FilterRecord",
    "MaterialReceipt",
    "StageIndicator",
    "EnergyArea",
    "EnergyGroup",
    "EnergyReading",
    "Calibration",
    "Equipment",
    "Incident",
    "MaintenancePlan",
    "SparePart",
    "Material",
    "Product",
    "GenealogyEdge",
    "MaterialLot",
    "OEERecord",
    "ProcessReading",
    "ProductionOrder",
    "ChemicalUsage",
    "YeastIssue",
    "YeastLot",
    "Deviation",
    "QualityResult",
    "Recipe",
    "RecipeVersion",
    "StockMovement",
]
