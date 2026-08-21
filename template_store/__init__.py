"""Módulo de persistencia y gestión de plantillas de formularios aprendidas."""

from template_store.store import (
    TemplateStore,
    calcular_hash_formulario,
    guardar_plantilla,
    cargar_plantilla,
    buscar_plantilla_por_similitud,
    listar_plantillas,
    eliminar_plantilla,
    adaptar_plan_a_formulario,
)

__all__ = [
    "TemplateStore",
    "calcular_hash_formulario",
    "guardar_plantilla",
    "cargar_plantilla",
    "buscar_plantilla_por_similitud",
    "listar_plantillas",
    "eliminar_plantilla",
    "adaptar_plan_a_formulario",
]
