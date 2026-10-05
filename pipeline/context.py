"""Contexto global y estado compartido para el Pipeline Modular de AutoForm AI.

Define la estructura de datos `PipelineContext` que viaja a través de todas
las etapas del pipeline (Parser -> Classifier -> LLM Mapper -> Verifier -> Writer).
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple


TipoDocumento = Literal["excel", "desconocido"]


class OperacionEscritura(str, Enum):
    """Operaciones permitidas por el plan de Excel de Fase 1."""

    ESCRIBIR = "ESCRIBIR"
    OMITIR = "OMITIR"
    EXCEDENTE_NO_ASIGNADO = "EXCEDENTE_NO_ASIGNADO"


@dataclass(frozen=True)
class DestinoExcel:
    """Coordenada final previamente validada para una escritura."""

    hoja: str
    fila: int
    columna: int
    candidato_id: str
    tabla: Optional[str] = None


@dataclass(frozen=True)
class DirectivaEscrituraExcel:
    """Fuente única de verdad entre el mapeador, validador y writer."""

    operacion: OperacionEscritura
    destino: Optional[DestinoExcel]
    campo: str
    valor: Any
    motivo: str = ""
    confianza: float = 0.0


@dataclass
class PipelineContext:
    """Estado compartido y acumulativo del pipeline de llenado de formularios.
    
    Attributes:
        archivo_bytes: Contenido binario del archivo original subido por el usuario.
        nombre_archivo: Nombre del archivo original (ej. 'SAGRILAFT_2026.xlsx').
        tipo_documento: 'excel' o 'desconocido'.
        datos_empresa: Diccionario con los datos maestros del perfil empresarial.
        elementos_raw: Lista de rótulos y coordenadas físicas extraídas en Stage 1 (Parser).
        elementos_clasificados: Elementos con etiqueta semántica ('CAMPO_ENTRADA', 'TITULO_SECCION', etc.).
        plan_mapeo: Plan de mapeo inicial generado por LLM o plantilla previa.
        plan_verificado: Plan de mapeo final confirmado por el usuario tras la UI de verificación.
        archivo_resultado: Binario del archivo resultante con los datos inyectados.
        reporte_inyeccion: Registro de inyección por celda (OK, SKIP, NULL, ERROR, etc.).
        plantilla_id: Hash identificador de la plantilla (SHA-256 de 16 caracteres).
        es_plantilla_guardada: True si el formulario fue reconocido desde el Template Store.
        score_similitud: Porcentaje de coincidencia si fue cargado por similitud difusa (0-100).
        metadatos: Diccionario auxiliar para métricas de tiempo, tokens o versiones.
        logs_progreso: Historial de mensajes y estados de cada etapa del pipeline.
        tiempo_inicio: Marca de tiempo unix cuando inició la ejecución del pipeline.
    """

    archivo_bytes: bytes
    nombre_archivo: str = ""
    tipo_documento: TipoDocumento = "desconocido"
    datos_empresa: Dict[str, Any] = field(default_factory=dict)
    # Identidad inmutable del perfil que aportó el snapshot de datos. Estos campos
    # evitan que el pipeline consulte o dependa de un "perfil activo" global.
    profile_id: Optional[str] = None
    profile_nombre: str = ""
    profile_version: Optional[int] = None
    
    # Etapa 1: Parser & Inspección Estructurada
    elementos_raw: List[Dict[str, Any]] = field(default_factory=list)
    inspeccion_excel: Optional[Any] = None  # core.excel_inspector.InspeccionLibroExcel
    directivas_escritura: Tuple[DirectivaEscrituraExcel, ...] = ()
    
    # Etapa 2: Classifier
    elementos_clasificados: List[Dict[str, Any]] = field(default_factory=list)
    
    # Etapa 2b: Representación Intermedia Espacial (IR) — Fase 1 HSP
    documento_ir: Optional[Any] = None  # core.spatial_ir.DocumentoIR (lazy import)
    
    # Etapa 3: LLM Mapper / Template Match
    plan_mapeo: List[Dict[str, Any]] = field(default_factory=list)
    
    # Etapa 3b: Resumen de validación determinística — Fase 2 HSP
    resumen_validacion: Optional[Dict[str, Any]] = None
    
    # Etapa 4: Verifier UI
    plan_verificado: List[Dict[str, Any]] = field(default_factory=list)
    
    # Etapa 5: Writer & Verificador Posterior
    archivo_resultado: Optional[bytes] = None
    reporte_inyeccion: List[Dict[str, Any]] = field(default_factory=list)
    resultado_verificacion: Optional[Any] = None  # core.excel_verifier.ResultadoVerificacion

    
    # Persistencia y Caché
    plantilla_id: Optional[str] = None
    es_plantilla_guardada: bool = False
    score_similitud: float = 0.0
    
    # Métricas y observabilidad
    metadatos: Dict[str, Any] = field(default_factory=dict)
    logs_progreso: List[str] = field(default_factory=list)
    tiempo_inicio: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """Aísla los datos de cada ejecución frente a cambios posteriores de UI."""
        self.datos_empresa = deepcopy(self.datos_empresa)

    def log(self, mensaje: str, mostrar_consola: bool = True) -> None:
        """Registra un mensaje en el historial de progreso del contexto."""
        tiempo_transcurrido = time.time() - self.tiempo_inicio
        registro = f"[{tiempo_transcurrido:6.2f}s] {mensaje}"
        self.logs_progreso.append(registro)
        if mostrar_consola:
            try:
                print(f"[AutoForm Pipeline] {registro}")
            except UnicodeEncodeError:
                print(f"[AutoForm Pipeline] {registro.encode('ascii', errors='replace').decode('ascii')}")

    def obtener_plan_activo(self) -> List[Dict[str, Any]]:
        """Retorna el plan verificado si existe; de lo contrario el plan de mapeo inicial,
        filtrando estrictamente ítems con estado DESCARTADO."""
        plan = self.plan_verificado if self.plan_verificado else self.plan_mapeo
        return [
            item for item in (plan or [])
            if str(item.get("estado", "")).upper() != "DESCARTADO"
        ]

    def obtener_campos_mapeados(self) -> List[str]:
        """Retorna la lista de claves de empresa asignadas en el plan activo."""
        plan = self.obtener_plan_activo()
        return [str(item.get("campo")) for item in plan if item.get("campo")]

    def contar_por_estado_inyeccion(self) -> Dict[str, int]:
        """Retorna el conteo de celdas por estado de inyección (OK, SKIP, NULL, ERROR, etc.)."""
        conteos: Dict[str, int] = {"OK": 0, "SKIP": 0, "NULL": 0, "ERROR": 0, "PRESERVED": 0}
        for item in self.reporte_inyeccion:
            estado = str(item.get("estado", "OTHER")).upper()
            conteos[estado] = conteos.get(estado, 0) + 1
        return conteos

        return {
            "nombre_archivo": self.nombre_archivo,
            "tipo_documento": self.tipo_documento,
            "duracion_segundos": round(duracion, 2),
            "total_elementos_detectados": len(self.elementos_raw),
            "campos_mapeados": len(campos_asignados),
            "campos_unicos_empresa": len(set(campos_asignados)),
            "es_plantilla_guardada": self.es_plantilla_guardada,
            "plantilla_id": self.plantilla_id,
            "score_similitud": self.score_similitud,
            "inyeccion_ok": conteo_estados.get("OK", 0),
            "inyeccion_skip": conteo_estados.get("SKIP", 0),
            "inyeccion_error": conteo_estados.get("ERROR", 0),
        }

    def generar_reporte_auditoria(self) -> Dict[str, Any]:
        """Genera el reporte formal de auditoría de precisión requerido por los estándares institucionales.

        Estructura:
          - total_targets: Rótulos / campos candidatos evaluados
          - filled: Celdas efectivamente asignadas y escritas
          - skipped: Celdas omitidas deliberadamente (títulos, uso interno, N/A)
          - invalid: Celdas con violación de formato o bloqueadas por fórmula
          - low_confidence: Celdas con confianza < 0.6 o estado REVISION
          - detalles: Lista con el detalle de cada cambio propuesto
        """
        plan = self.obtener_plan_activo()
        total_targets = len(self.elementos_raw)
        filled = 0
        skipped = 0
        invalid = 0
        low_confidence = 0
        detalles = []

        for item in (self.plan_mapeo or []):
            est = str(item.get("estado", "")).upper()
            bloqueante = bool(item.get("bloqueante", False))
            raw_conf = item.get("confianza_score") if item.get("confianza_score") is not None else item.get("confianza", 0.8)
            try:
                conf = float(raw_conf)
            except (ValueError, TypeError):
                conf = 0.8

            if est == "DESCARTADO" or str(item.get("campo", "")).lower() in ("", "omitir"):
                skipped += 1
            elif bloqueante or est == "INVALID":
                invalid += 1
            else:
                filled += 1

            if conf < 0.6 or est == "REVISION":
                low_confidence += 1

            val_nuevo = item.get("valor_a_escribir") or item.get("valor_nuevo") or item.get("valor")

            detalles.append({
                "hoja": item.get("hoja", ""),
                "celda": item.get("celda") or f"R{item.get('fila')}C{item.get('columna')}",
                "campo": item.get("campo_final") or item.get("campo", ""),
                "valor_anterior": item.get("valor_anterior"),
                "valor_nuevo": val_nuevo,
                "confianza": round(conf, 2),
                "advertencias": item.get("advertencias", []),
                "bloqueante": bloqueante,
                "estado": est,
            })

        return {
            "profile_id": self.profile_id,
            "profile_nombre": self.profile_nombre,
            "profile_version": self.profile_version,
            "total_targets": total_targets,
            "filled": filled,
            "skipped": skipped,
            "invalid": invalid,
            "low_confidence": low_confidence,
            "detalles": detalles,
            "resultado_verificacion": getattr(self, "resultado_verificacion", None),
        }

