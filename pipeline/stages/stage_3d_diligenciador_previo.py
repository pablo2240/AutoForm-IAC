"""Stage 3d: reemplazo de datos de un diligenciador anterior ya escritos en el formulario.

Un formulario generado antes con otro diligenciador (o preparado a mano) trae sus datos en las celdas del
bloque "Diligenciado por / Contacto comercial". Como esas celdas ya están llenas, el escritor las respeta y
cambiar de perfil no tendría efecto. Esta etapa las reconoce por su valor (ver ``core.diligenciador_previo``)
y agrega al plan la sobrescritura con los datos del perfil activo, de modo que el formulario conserva su
estructura y formato y solo cambia el diligenciador.

Es una etapa opcional: sin diligenciador activo o sin diligenciadores conocidos no hace nada.
"""

from __future__ import annotations

from core.diligenciador_previo import aplicar_al_plan, detectar_reemplazos
from pipeline.context import PipelineContext


def ejecutar_stage_3d_diligenciador_previo(ctx: PipelineContext) -> PipelineContext:
    """Marca en el plan las celdas con datos de otro diligenciador para que se reemplacen."""
    datos = ctx.datos_empresa or {}
    if not datos.get("responsable_nombre") and not datos.get("responsable_correo"):
        return ctx  # sin diligenciador activo rige la pasividad segura (ADR-0007)
    if not ctx.operadores_conocidos or ctx.tipo_documento != "excel":
        return ctx

    try:
        reemplazos = detectar_reemplazos(ctx.archivo_bytes, datos, ctx.operadores_conocidos, datos)
    except Exception as exc:  # la etapa es una mejora: un fallo nunca debe impedir procesar el formulario
        ctx.log(f"[Stage 3d - Diligenciador previo] Omitida: {type(exc).__name__}: {exc}")
        return ctx
    if not reemplazos:
        return ctx

    plan, aplicados = aplicar_al_plan(ctx.plan_mapeo, reemplazos)
    ctx.plan_mapeo = plan
    previos = sorted({r.operador_previo for r in reemplazos})
    ctx.metadatos["diligenciador_previo"] = {
        "operadores": previos,
        "celdas": [
            {"hoja": r.hoja, "fila": r.fila, "columna": r.columna, "campo": r.campo,
             "anterior": r.valor_anterior, "nuevo": r.valor_nuevo}
            for r in reemplazos
        ],
    }
    ctx.log(
        f"[Stage 3d - Diligenciador previo] {aplicados} celdas con datos de {', '.join(previos)} "
        f"se reemplazan por los del perfil activo."
    )
    return ctx
