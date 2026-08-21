"""Paquete central del Pipeline Modular de AutoForm AI."""

from pipeline.context import PipelineContext
from pipeline.orchestrator import (
    PipelineOrchestrator,
    ejecutar_analisis_formulario,
    ejecutar_inyeccion_formulario,
)

__all__ = [
    "PipelineContext",
    "PipelineOrchestrator",
    "ejecutar_analisis_formulario",
    "ejecutar_inyeccion_formulario",
]
