"""Componente UI para descarga y reporte de resultados (AutoForm AI)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
import streamlit as st

from pipeline.context import PipelineContext


def render_pantalla_descarga(ctx: PipelineContext, key_prefix: str = "download_ui") -> None:
    """Renderiza el resumen de inyección, métricas de éxito y el botón de descarga."""
    st.markdown("### 🎉 ¡Formulario Diligenciado con Éxito!")
    
    if not ctx.archivo_resultado:
        st.error("No se encontró el archivo generado para descargar.")
        return

    # Determinar extensión y MIME type
    nombre_base = Path(ctx.nombre_archivo).stem if ctx.nombre_archivo else "Formulario_Rellenado"
    if ctx.tipo_documento == "excel":
        nombre_descarga = f"{nombre_base}_AutoForm.xlsx"
        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        nombre_descarga = f"{nombre_base}_AutoForm.pdf"
        mime_type = "application/pdf"

    # ── Botón Principal de Descarga ──
    col_dl, _ = st.columns([2, 1])
    with col_dl:
        st.download_button(
            label=f"⬇️ Descargar Documento Final ({nombre_descarga})",
            data=ctx.archivo_resultado,
            file_name=nombre_descarga,
            mime=mime_type,
            type="primary",
            width="stretch",
            key=f"{key_prefix}_btn_download",
        )

    st.markdown("---")

    # ── Resumen de Métricas de Inyección ──
    conteos = ctx.contar_por_estado_inyeccion()
    resumen = ctx.resumen_ejecucion()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("✅ Celdas Escritas", f"{conteos.get('OK', 0)}")
    with col2:
        st.metric("⏭️ Celdas Omitidas", f"{conteos.get('SKIP', 0)}")
    with col3:
        st.metric("⚡ Tiempo Total", f"{resumen.get('duracion_segundos', 0)}s")
    with col4:
        st.metric("📁 Formato", ctx.tipo_documento.upper())

    # ── Reporte Detallado por Campo ──
    with st.expander("📊 Ver Reporte de Inyección Detallado por Celda", expanded=True):
        if ctx.reporte_inyeccion:
            df_reporte = pd.DataFrame(ctx.reporte_inyeccion)
            # Renombrar columnas para visualización clara
            columnas_mostrar = {
                "estado": "Estado",
                "campo": "Campo Empresa",
                "valor_intentado": "Valor Inyectado",
                "hoja": "Hoja / Página",
                "fila_destino": "Fila Destino",
                "columna_destino": "Col Destino",
                "motivo": "Observaciones",
            }
            cols_existentes = {k: v for k, v in columnas_mostrar.items() if k in df_reporte.columns}
            df_view = df_reporte[list(cols_existentes.keys())].rename(columns=cols_existentes)
            st.dataframe(df_view, width="stretch", hide_index=True)
        else:
            st.info("No hay registros de inyección detallados disponibles.")
