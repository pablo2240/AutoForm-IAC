"""Contexto global y estado compartido para el Pipeline Modular de AutoForm AI.

Define la estructura de datos `PipelineContext` que viaja a través de todas
las etapas del pipeline (Parser -> Classifier -> LLM Mapper -> Verifier -> Writer).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


TipoDocumento = Literal["excel", "pdf", "desconocido"]


@dataclass
class PipelineContext:
    """Estado compartido y acumulativo del pipeline de llenado de formularios.
    
    Attributes:
        archivo_bytes: Contenido binario del archivo original subido por el usuario.
        nombre_archivo: Nombre del archivo original (ej. 'SAGRILAFT_2026.xlsx').
        tipo_documento: 'excel', 'pdf' o 'desconocido'.
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
    
    # Etapa 1: Parser
    elementos_raw: List[Dict[str, Any]] = field(default_factory=list)
    
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
    
    # Etapa 5: Writer
    archivo_resultado: Optional[bytes] = None
    reporte_inyeccion: List[Dict[str, Any]] = field(default_factory=list)
    
    # Persistencia y Caché
    plantilla_id: Optional[str] = None
    es_plantilla_guardada: bool = False
    score_similitud: float = 0.0
    
    # Métricas y observabilidad
    metadatos: Dict[str, Any] = field(default_factory=dict)
    logs_progreso: List[str] = field(default_factory=list)
    tiempo_inicio: float = field(default_factory=time.time)

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
        """Retorna el plan verificado si existe; de lo contrario el plan de mapeo inicial."""
        return self.plan_verificado if self.plan_verificado else self.plan_mapeo

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

    def resumen_ejecucion(self) -> Dict[str, Any]:
        """Genera un resumen cuantitativo del procesamiento del formulario."""
        duracion = time.time() - self.tiempo_inicio
        campos_asignados = self.obtener_campos_mapeados()
        conteo_estados = self.contar_por_estado_inyeccion()

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
