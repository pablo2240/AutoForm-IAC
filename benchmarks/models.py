"""Modelos de datos para el Benchmark Engine (Fase 5)."""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from enum import Enum


class CategoriaResultado(Enum):
    CORRECTO_AUTO = "🟢 Correcto Automáticamente"
    CORRECTO_REVISION = "🟡 Correcto tras Revisión"
    INCORRECTO = "🔴 Incorrecto (Error Crítico)"
    NO_DETECTADO = "🟣 No Detectado"
    OMITIDO_CORRECTAMENTE = "⚪ Omitido Correctamente"
    FALSO_POSITIVO = "🟠 Falso Positivo"


@dataclass
class GroundTruthItem:
    hoja: str
    fila: int
    columna: int
    rotulo_original: str
    is_field: bool
    expected_campo: str
    
    @property
    def key(self) -> str:
        return f"{self.hoja}_{self.fila}_{self.columna}"


@dataclass
class BenchmarkResult:
    gt_item: Optional[GroundTruthItem]
    pipeline_item: Optional[Dict[str, Any]]
    categoria: CategoriaResultado
    motivo_clasificacion: str


@dataclass
class BenchmarkMetrics:
    total_campos_reales: int
    total_no_campos: int
    
    # Conteos por categoría
    cnt_correcto_auto: int = 0
    cnt_correcto_revision: int = 0
    cnt_incorrecto: int = 0
    cnt_no_detectado: int = 0
    cnt_omitido_correcto: int = 0
    cnt_falso_positivo: int = 0
    
    # KPIs de Negocio
    unsafe_automation_rate: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    ir_filtering_rate: float = 0.0
    safety_score: float = 0.0
    
    # Performance
    execution_time_seconds: float = 0.0
