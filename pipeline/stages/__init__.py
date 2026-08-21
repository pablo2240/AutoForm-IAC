"""Módulo de etapas del Pipeline Modular de AutoForm AI."""

from pipeline.stages.stage_2_classifier import clasificar_elementos_formulario, ClasificacionElemento

__all__ = [
    "clasificar_elementos_formulario",
    "ClasificacionElemento",
]
