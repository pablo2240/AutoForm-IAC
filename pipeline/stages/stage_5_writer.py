"""Stage 5: Writer de Formularios Excel (Pipeline AutoForm AI).

Inyecta físicamente los valores del perfil empresarial en las coordenadas verificadas
del documento Excel original, preservando fuentes, combinaciones y estilos.
"""

from __future__ import annotations

import time
from pipeline.context import PipelineContext
from pipeline.handlers import ExcelHandler


def ejecutar_stage_5_writer(ctx: PipelineContext) -> PipelineContext:
    """Ejecuta la etapa de inyección física y generación del archivo Excel de salida."""
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

        # ── VERIFICACIÓN POSTERIOR DE INTEGRIDAD (ROUND-TRIP VERIFICATION) ──
        try:
            from core.excel_verifier import verificar_integridad_excel
            from core.excel_inspector import inspeccionar_libro_excel
            insp = ctx.inspeccion_excel
            if insp is None:
                insp = inspeccionar_libro_excel(ctx.archivo_bytes)
                ctx.inspeccion_excel = insp

            res_verif = verificar_integridad_excel(
                archivo_original_bytes=ctx.archivo_bytes,
                archivo_generado_bytes=archivo_resultado,
                plan_mapeo=plan_final,
                inspeccion_original=insp,
            )
            ctx.resultado_verificacion = res_verif
            ctx.log(
                f"[Stage 5 - Verificador] Verificación posterior: válido={res_verif.es_valido} | "
                f"{res_verif.exitosos}/{res_verif.total_verificados} valores confirmados | "
                f"{res_verif.formulas_preservadas} fórmulas preservadas intactas."
            )
            if not res_verif.es_valido:
                errores = "; ".join(res_verif.errores_bloqueantes)
                raise RuntimeError(f"Fallo controlado de integridad estructural: {errores}")
        except Exception as exc_verif:
            if "Fallo controlado" in str(exc_verif):
                raise
            ctx.log(f"[Stage 5 - Verificador] Advertencia durante verificación: {exc_verif}")
    else:
        raise ValueError(f"Tipo de documento '{ctx.tipo_documento}' no soportado para escritura. AutoForm AI solo escribe en Excel.")

    ctx.archivo_resultado = archivo_resultado
    ctx.reporte_inyeccion = reporte

    duracion = time.time() - t0
    conteos = ctx.contar_por_estado_inyeccion()
    ctx.log(
        f"[Stage 5 - Writer] Inyección finalizada en {duracion:.2f}s | "
        f"OK: {conteos.get('OK', 0)} | SKIP: {conteos.get('SKIP', 0)} | ERROR: {conteos.get('ERROR', 0)}"
    )

    return ctx

