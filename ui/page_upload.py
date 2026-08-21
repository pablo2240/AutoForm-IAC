"""Componente UI para carga de archivos y gestión de perfil empresarial (AutoForm AI)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import streamlit as st


def render_pantalla_carga(
    perfil_empresa_actual: Dict[str, Any],
    key_prefix: str = "upload_ui",
) -> Tuple[Optional[bytes], str, Dict[str, Any]]:
    """Renderiza la zona de carga de archivos (Excel / PDF) y gestión de datos de empresa.
    
    Returns:
        Tuple: (archivo_bytes: Optional[bytes], nombre_archivo: str, datos_empresa: Dict[str, Any])
    """
    st.markdown("### 📤 Cargar Formulario a Diligenciar")
    st.markdown("Sube tu formato en blanco en formato **Excel (.xlsx)** o **PDF (.pdf)**:")

    uploaded_file = st.file_uploader(
        "Arrastra o selecciona el formulario:",
        type=["xlsx", "pdf", "xlsm"],
        key=f"{key_prefix}_uploader",
        help="Formatos soportados: Excel (.xlsx, .xlsm) y PDF (.pdf)",
    )

    archivo_bytes: Optional[bytes] = None
    nombre_archivo: str = ""

    if uploaded_file is not None:
        archivo_bytes = uploaded_file.getvalue()
        nombre_archivo = uploaded_file.name
        st.success(f"📁 Documento cargado: **{nombre_archivo}** ({len(archivo_bytes) / 1024:.1f} KB)")

    # ── Gestión de Datos de la Empresa en Sidebar o Expander ──
    with st.expander("🏢 Ver y Editar Perfil de la Empresa Activo", expanded=False):
        st.caption("Estos son los datos maestros que AutoForm AI inyectará en los formularios:")
        datos_editados = {}
        cols = st.columns(2)
        
        for idx, (campo, valor) in enumerate(perfil_empresa_actual.items()):
            col = cols[idx % 2]
            with col:
                nuevo_val = st.text_input(
                    label=campo.replace("_", " ").title(),
                    value=str(valor or ""),
                    key=f"{key_prefix}_emp_{campo}",
                )
                datos_editados[campo] = nuevo_val

        if st.button("💾 Guardar Cambios en Perfil de Empresa", key=f"{key_prefix}_save_profile"):
            ruta_cfg = Path("config") / "datos_empresa.json"
            with open(ruta_cfg, "w", encoding="utf-8") as f:
                json.dump(datos_editados, f, ensure_ascii=False, indent=2)
            st.success("✅ Perfil de empresa actualizado exitosamente.")
            perfil_empresa_actual = datos_editados

    return archivo_bytes, nombre_archivo, perfil_empresa_actual
