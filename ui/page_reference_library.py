"""Panel de la biblioteca de formularios de referencia (administración y resumen por ejecución)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

from reference_library.service import ServicioReferencias, obtener_servicio, referencias_habilitadas


def render_resumen_referencias(ctx: Any) -> None:
    """Una línea con la familia detectada y los ejemplos de referencias usados en esta ejecución."""
    clasificacion: Optional[Dict[str, Any]] = (getattr(ctx, "metadatos", None) or {}).get("clasificacion_formulario")
    lotes = (getattr(ctx, "metadatos", None) or {}).get("fewshot") or []
    if not clasificacion and not lotes:
        return
    partes = []
    if clasificacion:
        familia = clasificacion.get("familia")
        if familia:
            probabilidad = clasificacion.get("probabilidades", {}).get(familia, 0.0)
            partes.append(f"familia detectada: **{familia}** ({probabilidad * 100:.0f}%)")
        else:
            partes.append("formulario no reconocido en ninguna familia (se usó la búsqueda general)")
    if lotes:
        total = sum(len(lote["ejemplos"]) for lote in lotes)
        partes.append(f"{total} ejemplos de referencias enviados al modelo")
    st.caption("📚 " + " · ".join(partes))


def _tabla_documentos(servicio: ServicioReferencias) -> pd.DataFrame:
    filas = [
        {
            "Documento": d.nombre,
            "Familia": d.familia or "—",
            "Origen": d.fuente,
            "Campos": d.total_campos,
            "Con campo maestro": d.estructura.get("campos_con_campo_maestro", 0),
            "Estado": "ok" if d.estado == "ok" else f"error: {d.error}",
        }
        for d in servicio.biblioteca.listar()
    ]
    return pd.DataFrame(filas)


def render_biblioteca_referencias(es_admin: bool, datos_empresa: Dict[str, Any]) -> None:
    """Estado de la biblioteca para todos; agregar, eliminar y reprocesar solo para administradores."""
    if not referencias_habilitadas():
        return
    servicio = obtener_servicio()
    if servicio is None:
        return

    with st.expander("📚 Biblioteca de referencias", expanded=False):
        estadisticas = servicio.biblioteca.estadisticas()
        columnas = st.columns(3)
        columnas[0].metric("Formularios", estadisticas["documentos"])
        columnas[1].metric("Rótulos", estadisticas["campos"])
        columnas[2].metric("Con campo maestro", estadisticas["campos_con_campo_maestro"])
        if estadisticas["familias"]:
            st.caption("Familias: " + ", ".join(estadisticas["familias"]))
        else:
            st.caption("Sin familias definidas: usa subcarpetas dentro de docs/referencias para crearlas.")

        tabla = _tabla_documentos(servicio)
        if not tabla.empty:
            st.dataframe(tabla, hide_index=True, use_container_width=True)

        if not es_admin:
            st.caption("Solo un administrador puede agregar, eliminar o reprocesar referencias.")
            return

        st.warning(
            "En Streamlit Cloud los archivos agregados desde aquí se pierden al reiniciar la app. "
            "Para conservarlos, súbelos al repositorio dentro de `docs/referencias`."
        )
        with st.form("form_agregar_referencia", clear_on_submit=True):
            archivo = st.file_uploader("Agregar formulario de referencia", type=["xlsx", "xlsm"])
            familia = st.text_input("Familia (opcional)", placeholder="proveedor, cliente, ...")
            if st.form_submit_button("Agregar y procesar", use_container_width=True) and archivo is not None:
                try:
                    with st.spinner("Analizando el formulario..."):
                        servicio.biblioteca.agregar(
                            archivo.getvalue(), nombre=archivo.name, familia=familia.strip(),
                            datos_empresa=datos_empresa,
                        )
                        servicio.buscador.reindexar()
                    st.success(f"«{archivo.name}» agregado a la biblioteca.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        documentos = servicio.biblioteca.listar()
        if not documentos:
            return
        elegido = st.selectbox(
            "Documento", options=[d.doc_id for d in documentos],
            format_func=lambda doc_id: next(d.nombre for d in documentos if d.doc_id == doc_id),
            key="ref_doc_seleccionado",
        )
        acciones = st.columns(3)
        if acciones[0].button("Reprocesar", key="ref_btn_reprocesar", use_container_width=True):
            reporte = servicio.biblioteca.reprocesar(elegido, datos_empresa=datos_empresa)
            servicio.buscador.reindexar()
            st.success("Reprocesado.") if not reporte.errores else st.error(str(reporte.errores))
        if acciones[1].button("Sincronizar todo", key="ref_btn_sync", use_container_width=True):
            reporte = servicio.biblioteca.sincronizar(datos_empresa=datos_empresa)
            servicio.buscador.reindexar()
            st.info(reporte.resumen())
        confirmar = st.checkbox("Confirmo que quiero eliminar este formulario", key="ref_confirmar_eliminar")
        if acciones[2].button("Eliminar", key="ref_btn_eliminar", use_container_width=True, disabled=not confirmar):
            servicio.biblioteca.eliminar(elegido)
            servicio.buscador.reindexar()
            st.success("Referencia eliminada.")
            st.rerun()
