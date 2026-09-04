"""Stage 1: Parser de Formularios Excel (Pipeline AutoForm AI).

Detecta y valida el formato Excel (.xlsx, .xlsm, .xls) y delega la extracción estructural
al ExcelHandler, unificando los rótulos y coordenadas físicas.
"""

from __future__ import annotations

import time
from pipeline.context import PipelineContext
from pipeline.handlers import detectar_tipo_documento, ExcelHandler


def ejecutar_stage_1_parser(ctx: PipelineContext) -> PipelineContext:
    """Ejecuta la etapa de escaneo y extracción del formulario Excel."""
    t0 = time.time()
    
    # 1. Detectar tipo de documento si no está definido
    if not ctx.tipo_documento or ctx.tipo_documento == "desconocido":
        ctx.tipo_documento = detectar_tipo_documento(ctx.archivo_bytes, ctx.nombre_archivo)

    ctx.log(f"[Stage 1 - Parser] Iniciando escaneo de formato '{ctx.tipo_documento.upper()}' ({ctx.nombre_archivo})...")

    # 2. Validar formato y delegar escaneo al ExcelHandler
    if ctx.tipo_documento == "excel":
        elementos = ExcelHandler.escanear(ctx.archivo_bytes)
    else:
        raise ValueError(
            f"Formato no soportado para el archivo '{ctx.nombre_archivo}'. "
            f"AutoForm AI se especializa exclusivamente en hojas de cálculo Excel (.xlsx, .xlsm, .xls)."
        )

    ctx.elementos_raw = elementos
    duracion = time.time() - t0
    ctx.log(f"[Stage 1 - Parser] Escaneo completado: {len(elementos)} elementos detectados en {duracion:.2f}s.")

    return ctx
