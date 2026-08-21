"""Stage 5: Writer Unificado de Formularios (Pipeline AutoForm AI).

Inyecta físicamente los valores del perfil empresarial en las coordenadas verificadas
del documento original (Excel o PDF), preservando fuentes, combinaciones y estilos.
"""

from __future__ import annotations

import time
from pipeline.context import PipelineContext
from pipeline.handlers import ExcelHandler, PdfHandler


def ejecutar_stage_5_writer(ctx: PipelineContext) -> PipelineContext:
    """Ejecuta la etapa de inyección física y generación del archivo de salida."""
    t0 = time.time()
    plan_final = ctx.obtener_plan_activo()

    if not plan_final:
        raise ValueError("No se puede ejecutar la inyección: el plan de mapeo está vacío.")

    ctx.log(f"[Stage 5 - Writer] Iniciando inyección física de {len(plan_final)} campos en '{ctx.tipo_documento.upper()}'...")

    if ctx.tipo_documento == "excel":
        archivo_resultado, reporte = ExcelHandler.inyectar(
            archivo_bytes=ctx.archivo_bytes,
            plan_mapeo=plan_final,
            datos_empresa=ctx.datos_empresa,
        )
    elif ctx.tipo_documento == "pdf":
        archivo_resultado, reporte = PdfHandler.inyectar(
            archivo_bytes=ctx.archivo_bytes,
            plan_mapeo=plan_final,
            datos_empresa=ctx.datos_empresa,
        )
    else:
        raise ValueError(f"Tipo de documento '{ctx.tipo_documento}' no soportado para escritura.")

    ctx.archivo_resultado = archivo_resultado
    ctx.reporte_inyeccion = reporte

    duracion = time.time() - t0
    conteos = ctx.contar_por_estado_inyeccion()
    ctx.log(
        f"[Stage 5 - Writer] Inyección finalizada en {duracion:.2f}s | "
        f"OK: {conteos.get('OK', 0)} | SKIP: {conteos.get('SKIP', 0)} | ERROR: {conteos.get('ERROR', 0)}"
    )

    return ctx
