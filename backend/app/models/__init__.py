"""Tập hợp toàn bộ ORM model để metadata.create_all() nhìn thấy.

Mỗi nhóm file tương ứng một bounded context (tài liệu §6.2):
master, orders, recipes, batches, materials, quality, audit.
"""

from .audit import AuditLog
from .auth import User, UserSession
from .batches import BatchExecution
from .cip import CipEquipment, CipFormType, CipLink, CipRecord
from .brewing import (
    BottleRecord,
    BrewBatch,
    BrewMaterialUsage,
    BrewProcessLog,
    BrewProcessStep,
    BrewRecord,
    FermentBrewLink,
    FermentDailyReading,
    FermentProcessLog,
    FermentRecord,
    FilterRecord,
    MaterialReceipt,
    OpsSetting,
    StageIndicator,
)
from .energy import EnergyArea, EnergyGroup, EnergyReading
from .historian import HistorianPoint
from .integration import ApiKey, SqlConnection, Webhook
from .maintenance import Calibration, Equipment, Incident, MaintenancePlan, SparePart
from .master import BeerType, FinishedProduct, Material, Product
from .materials import GenealogyEdge, MaterialLot, Supplier
from .metrics import OEERecord, ProcessReading
from .orders import ProductionOrder
from .process import ChemicalUsage, YeastIssue, YeastLot
from .quality import Deviation, QualityResult
from .recipes import Recipe, RecipeVersion
from .recipe_ext import BatchYieldActual, RecipeChange
from .signature import EBRSnapshot, Signature
from .warehouse import MaterialRequest, MaterialRequestLine, StockMovement
from .workorder import WorkOrder
from .materials_ext import Dispense, DispenseLine, MaterialQcGroup
from .quality_ext import CAPA, QCParameter, QCParameterGroup, QCParameterGroupItem, Sample, StageQcGroup
from .oee_ext import DowntimeEvent
from .ai_memory import AiConversation, AiMessage
from .jobs import Job
from .isa88 import BatchPhaseRun
from .scheduling import ScheduleSlot
from .wms import FinishedGoodsUnit, WmsLocation
from .lines import ProductionLine
from .packaging import PackagingMove, PackagingType
from .integration_import import (  # noqa: F401
    IntegrationColumnMapping,
    IntegrationImportError,
    IntegrationImportFile,
    IntegrationImportRun,
    IntegrationMappingProfile,
)
from .custom_fields import CustomFieldDefinition, CustomFieldValue  # noqa: F401

__all__ = [
    "AuditLog",
    "BatchExecution",
    "CipEquipment",
    "CipFormType",
    "CipLink",
    "CipRecord",
    "BottleRecord",
    "BrewBatch",
    "BrewMaterialUsage",
    "BrewProcessLog",
    "BrewProcessStep",
    "BrewRecord",
    "FermentBrewLink",
    "FermentDailyReading",
    "FermentProcessLog",
    "FermentRecord",
    "FilterRecord",
    "MaterialReceipt",
    "OpsSetting",
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
    "BeerType",
    "FinishedProduct",
    "GenealogyEdge",
    "MaterialLot",
    "Supplier",
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
    "BatchYieldActual",
    "RecipeChange",
    "StockMovement",
    "MaterialRequest",
    "MaterialRequestLine",
    "WorkOrder",
    "Dispense",
    "DispenseLine",
    "QCParameter",
    "QCParameterGroup",
    "QCParameterGroupItem",
    "MaterialQcGroup",
    "CAPA",
    "Sample",
    "StageQcGroup",
    "DowntimeEvent",
    "AiConversation",
    "AiMessage",
    "Job",
    "BatchPhaseRun",
    "ScheduleSlot",
    "WmsLocation",
    "FinishedGoodsUnit",
    "ProductionLine",
    "PackagingType",
    "PackagingMove",
]
