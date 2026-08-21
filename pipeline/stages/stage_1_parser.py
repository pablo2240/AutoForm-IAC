"""Stage 1: Parser Unificado de Formularios (Pipeline AutoForm AI).

Detecta el tipo de documento (Excel vs PDF) y delega la extracción estructural
al Handler especializado correspondiente, unificando los rótulos y coordenadas.
"""

from __future__ import annotations

import time
from pipeline.context import PipelineContext
from pipeline.handlers import detectar_tipo_documento, ExcelHandler, PdfHandler


def ejecutar_stage_1_parser(ctx: PipelineContext) -> PipelineContext:
    """Ejecuta la etapa de escaneo y extracción del formulario."""
    t0 = time.time()
    
    # 1. Detectar tipo de documento si no está definido
    if not ctx.tipo_documento or ctx.tipo_documento == "desconocido":
        ctx.tipo_documento = detectar_tipo_documento(ctx.archivo_bytes, ctx.nombre_archivo)

    ctx.log(f"[Stage 1 - Parser] Iniciando escaneo de formato '{ctx.tipo_documento.upper()}' ({ctx.nombre_archivo})...")

    # 2. Delegar escaneo al Handler correspondiente
    if ctx.tipo_documento == "excel":
        elementos = ExcelHandler.escanear(ctx.archivo_bytes)
    elif ctx.tipo_documento == "pdf":
        elementos = PdfHandler.escanear(ctx.archivo_bytes)
    else:
        raise ValueError(
            f"Formato no soportado para el archivo '{ctx.nombre_archivo}'. "
            f"Solo se admiten documentos Excel (.xlsx) y PDF (.pdf)."
        )

    ctx.elementos_raw = elementos
    duracion = time.time() - t0
    ctx.log(f"[Stage 1 - Parser] Escaneo completado: {len(elementos)} elementos detectados en {duracion:.2f}s.")

    return ctx
