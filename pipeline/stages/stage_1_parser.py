"""Stage 1: validación y extracción estructurada de formularios Excel."""

from __future__ import annotations

import time
from pathlib import Path

from pipeline.context import PipelineContext
from pipeline.handlers import ExcelHandler, detectar_tipo_documento

MENSAJE_CONTROLES_VML = (
    "El formulario contiene controles de formulario (casillas de verificación o listas desplegables "
    "insertadas como objetos). Se diligenciaron los campos de texto, pero la copia no conserva esos "
    "controles: revisa y marca esas opciones manualmente en el archivo final."
)


def ejecutar_stage_1_parser(ctx: PipelineContext) -> PipelineContext:
    """Escanea una plantilla Excel y rechaza formatos no preservables de forma segura."""
    inicio = time.time()
    if not ctx.tipo_documento or ctx.tipo_documento == "desconocido":
        ctx.tipo_documento = detectar_tipo_documento(ctx.archivo_bytes, ctx.nombre_archivo)

    ctx.log(
        f"[Stage 1 - Parser] Iniciando escaneo de formato "
        f"'{ctx.tipo_documento.upper()}' ({ctx.nombre_archivo})..."
    )
    if ctx.tipo_documento != "excel":
        raise ValueError(
            f"Formato no soportado para el archivo '{ctx.nombre_archivo}'. "
            "AutoForm AI se especializa exclusivamente en hojas de cálculo Excel (.xlsx, .xlsm, .xls)."
        )
    if Path(ctx.nombre_archivo).suffix.lower() == ".xls":
        raise ValueError(
            "Los archivos .xls no están soportados de forma segura. "
            "Convierte la plantilla a .xlsx o .xlsm."
        )

    elementos = ExcelHandler.escanear(ctx.archivo_bytes)
    try:
        from core.excel_inspector import inspeccionar_libro_excel

        ctx.inspeccion_excel = inspeccionar_libro_excel(ctx.archivo_bytes)
        if ctx.inspeccion_excel.tiene_controles_vml:
            # No se bloquea el procesamiento: la copia se genera en OpenXML nativo (apertura limpia en
            # Excel), que no conserva los controles de formulario. Se avisa para no perderlos en silencio.
            ctx.metadatos["advertencia_controles_vml"] = MENSAJE_CONTROLES_VML
            ctx.log(f"[Stage 1 - Parser] Advertencia: {MENSAJE_CONTROLES_VML}")
        ctx.log(
            f"[Stage 1 - Parser] Inspección estructurada: {len(ctx.inspeccion_excel.hojas)} hojas, "
            f"{len(ctx.inspeccion_excel.tablas)} tablas, "
            f"{len(ctx.inspeccion_excel.celdas_con_formula)} fórmulas protegidas, "
            f"{len(ctx.inspeccion_excel.validaciones_por_celda)} celdas con validación."
        )
    except Exception as exc_insp:
        ctx.log(f"[Stage 1 - Parser] Advertencia en inspección estructurada: {exc_insp}")

    ctx.elementos_raw = elementos
    ctx.log(
        f"[Stage 1 - Parser] Escaneo completado: {len(elementos)} elementos detectados "
        f"en {time.time() - inicio:.2f}s."
    )
    return ctx
