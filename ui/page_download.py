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

    # ── Verificación Posterior de Integridad Estructural (Round-Trip) ──
    res_verif = getattr(ctx, "resultado_verificacion", None)
    if res_verif is not None:
        if not res_verif.es_valido:
            st.error(
                f"⛔ **Fallo de Integridad Estructural**: No se superó la verificación en memoria "
                f"({len(res_verif.errores_bloqueantes)} errores detectados). "
                "El archivo no es seguro para la entrega."
            )
            with st.expander("Ver detalles del fallo de integridad", expanded=True):
                for err in res_verif.errores_bloqueantes:
                    st.write(f"- ❌ {err}")
            return
        else:
            st.success(
                f"🛡️ **Integridad Estructural Certificada**: 100% de fórmulas preexistentes preservadas "
                f"({res_verif.formulas_preservadas} fórmulas intactas) y {res_verif.exitosos} celdas verificadas con éxito en memoria."
            )

    # Determinar extensión y MIME type (Excel OpenXML)
    nombre_base = Path(ctx.nombre_archivo).stem if ctx.nombre_archivo else "Formulario_Rellenado"
    nombre_descarga = f"{nombre_base}_AutoForm.xlsx"
    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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

    # ── Reporte de Auditoría Numérica Estructurada (Pilar 7) ──
    audit = ctx.generar_reporte_auditoria()
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("🎯 Total Objetivos", f"{audit.get('total_targets', 0)}")
    with col2:
        st.metric("✅ Diligenciados", f"{audit.get('filled', 0)}")
    with col3:
        st.metric("⏭️ Omitidos", f"{audit.get('skipped', 0)}")
    with col4:
        st.metric("🚫 Inválidos / Errores", f"{audit.get('invalid', 0)}")
    with col5:
        st.metric("🟡 Baja Confianza", f"{audit.get('low_confidence', 0)}")

    # ── Reporte Detallado por Campo ──
    with st.expander("📊 Ver Reporte de Inyección Detallado por Celda", expanded=False):
        if ctx.reporte_inyeccion:
            df_reporte = pd.DataFrame(ctx.reporte_inyeccion)
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
            df_view = df_reporte[list(cols_existentes.keys())].rename(columns=cols_existentes).copy()
            for col in df_view.columns:
                if col in ("Fila Destino", "Col Destino"):
                    df_view[col] = pd.to_numeric(df_view[col], errors="coerce").fillna(0).astype(int)
                else:
                    df_view[col] = df_view[col].fillna("").astype(str)
            st.dataframe(df_view, width="stretch", hide_index=True)
        else:
            st.info("No hay registros de inyección detallados disponibles.")
