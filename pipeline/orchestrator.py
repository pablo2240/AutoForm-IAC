"""Orquestador Central del Pipeline Modular de AutoForm AI.

Coordina de forma secuencial y desacoplada las 5 etapas del pipeline:
  1. Stage 1: Parser (Extracción estructural de Excel/PDF)
  2. Stage 2: Classifier (Separación de Campos vs Títulos decorativos)
  3. Stage 3: LLM Mapper / Template Store (Mapeo semántico)
  4. Stage 4: Verifier UI (Verificación interactiva con Dropdowns)
  5. Stage 5: Writer (Inyección física y preservación de estilos)
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from pipeline.context import PipelineContext
from pipeline.stages.stage_1_parser import ejecutar_stage_1_parser
from pipeline.stages.stage_2_classifier import clasificar_elementos_formulario
from pipeline.stages.stage_3_llm_mapper import ejecutar_stage_3_mapper
from pipeline.stages.stage_5_writer import ejecutar_stage_5_writer


class PipelineOrchestrator:
    """Orquestador de ejecución del Pipeline."""

    @classmethod
    def analizar_formulario(
        cls,
        ctx: PipelineContext,
        on_progress: Optional[Callable[[str, float], None]] = None,
    ) -> PipelineContext:
        """Ejecuta las etapas de análisis (Stage 1 -> Stage 2 -> Stage 3) previas a la verificación.
        
        Args:
            ctx: Contexto del pipeline inicializado con archivo_bytes y datos_empresa.
            on_progress: Callback opcional (mensaje: str, progreso: float 0..1).
            
        Returns:
            PipelineContext enriquecido con elementos_raw, elementos_clasificados y plan_mapeo.
        """
        # Etapa 1: Parser (0% -> 33%)
        if on_progress:
            on_progress("Escaneando estructura y rótulos del archivo...", 0.15)
        ctx = ejecutar_stage_1_parser(ctx)

        # Etapa 2: Classifier (33% -> 66%)
        if on_progress:
            on_progress("Clasificando campos de entrada y jerarquía de secciones...", 0.45)
        todos_clasif, viables = clasificar_elementos_formulario(ctx.elementos_raw)
        ctx.elementos_clasificados = todos_clasif

        # Etapa 3: LLM Mapper / Template Store (66% -> 100%)
        if on_progress:
            on_progress("Emparejando datos con el perfil empresarial...", 0.75)
        ctx = ejecutar_stage_3_mapper(ctx)

        if on_progress:
            on_progress("¡Análisis completado! Listo para verificación.", 1.0)

        return ctx

    @classmethod
    def rellenar_formulario(
        cls,
        ctx: PipelineContext,
        on_progress: Optional[Callable[[str, float], None]] = None,
    ) -> PipelineContext:
        """Ejecuta la etapa de inyección física (Stage 5: Writer) tras la confirmación del usuario.
        
        Args:
            ctx: Contexto del pipeline con plan_verificado confirmado.
            on_progress: Callback opcional.
            
        Returns:
            PipelineContext con archivo_resultado y reporte_inyeccion generados.
        """
        if on_progress:
            on_progress("Inyectando datos en el documento y preservando formato...", 0.5)

        ctx = ejecutar_stage_5_writer(ctx)

        if on_progress:
            on_progress("¡Documento completado con éxito!", 1.0)

        return ctx


def ejecutar_analisis_formulario(
    archivo_bytes: bytes,
    nombre_archivo: str,
    datos_empresa: Dict[str, Any],
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> PipelineContext:
    """Función de conveniencia para crear contexto y ejecutar análisis inicial."""
    ctx = PipelineContext(
        archivo_bytes=archivo_bytes,
        nombre_archivo=nombre_archivo,
        datos_empresa=datos_empresa,
    )
    return PipelineOrchestrator.analizar_formulario(ctx, on_progress=on_progress)


def ejecutar_inyeccion_formulario(
    ctx: PipelineContext,
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> PipelineContext:
    """Función de conveniencia para ejecutar la inyección tras verificación."""
    return PipelineOrchestrator.rellenar_formulario(ctx, on_progress=on_progress)
