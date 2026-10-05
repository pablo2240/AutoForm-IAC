"""Formularios de creación, edición y archivado de perfiles de diligenciamiento."""

from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from core import database, profile_manager


def _campos(datos: Dict[str, Any], prefijo: str) -> Dict[str, Any]:
    """Renderiza los datos fijos mínimos y reutilizables para persona o empresa."""
    columnas = st.columns(2)
    definiciones = (
        ("razon_social", "Nombre o razón social"),
        ("nit", "NIT o identificación"),
        ("direccion", "Dirección"),
        ("ciudad", "Ciudad"),
        ("departamento", "Departamento"),
        ("telefono", "Teléfono"),
        ("correo", "Correo de contacto"),
        ("representante_legal", "Representante legal"),
        ("cedula", "Documento del representante"),
        ("banco", "Banco"),
        ("numero_cuenta", "Número de cuenta"),
    )
    resultado = dict(datos)
    for indice, (clave, etiqueta) in enumerate(definiciones):
        with columnas[indice % 2]:
            resultado[clave] = st.text_input(etiqueta, value=str(datos.get(clave) or ""), key=f"{prefijo}_{clave}")
    return resultado


def render_creador_perfil(usuario: Dict[str, Any]) -> Optional[profile_manager.PerfilDiligenciamiento]:
    """Crea un perfil y permite usarlo inmediatamente sin tocar preferencias globales."""
    with st.expander("Crear nuevo perfil", expanded=True):
        with st.form("form_crear_perfil_diligenciamiento", clear_on_submit=True):
            nombre = st.text_input("Nombre visible", placeholder="Ej.: José (Comerciante) o Empresa X")
            tipo = st.selectbox("Tipo", options=list(profile_manager.TipoPerfil), format_func=lambda item: item.value.title())
            datos = _campos({}, "crear_perfil")
            guardar_y_usar = st.checkbox("Usar este perfil ahora", value=True)
            enviado = st.form_submit_button("Guardar perfil")
        if enviado:
            try:
                perfil = profile_manager.crear_perfil_diligenciamiento(nombre, tipo, datos, str(usuario["id"]))
            except (ValueError, database.ConflictoVersionPerfilError) as exc:
                st.error(str(exc))
                return None
            st.success(f"Perfil «{perfil.nombre}» creado.")
            if guardar_y_usar:
                st.session_state["active_profile_id"] = perfil.id
                st.session_state["active_profile_name"] = perfil.nombre
                st.session_state["active_profile_version"] = perfil.version
            return perfil
    return None


def render_editor_perfil(usuario: Dict[str, Any], perfil: profile_manager.PerfilDiligenciamiento) -> Optional[profile_manager.PerfilDiligenciamiento]:
    """Edita el perfil seleccionado con versión esperada y archivado reversible de admin."""
    with st.expander("Gestionar perfil seleccionado", expanded=False):
        with st.form(f"form_editar_perfil_{perfil.id}"):
            nombre = st.text_input("Nombre visible", value=perfil.nombre)
            tipo = st.selectbox(
                "Tipo",
                options=list(profile_manager.TipoPerfil),
                index=list(profile_manager.TipoPerfil).index(perfil.tipo),
                format_func=lambda item: item.value.title(),
            )
            datos = _campos(perfil.datos, f"editar_{perfil.id}")
            guardar = st.form_submit_button("Guardar cambios")
        if guardar:
            try:
                actualizado = profile_manager.actualizar_perfil_diligenciamiento(
                    perfil.id, nombre, tipo, datos, perfil.version, str(usuario["id"])
                )
            except database.ConflictoVersionPerfilError:
                st.error("El perfil fue modificado por otra persona. Recarga y revisa antes de guardar.")
                return None
            except ValueError as exc:
                st.error(str(exc))
                return None
            st.session_state["active_profile_version"] = actualizado.version
            st.session_state["active_profile_name"] = actualizado.nombre
            st.success("Datos del perfil actualizados.")
            return actualizado

        if bool(usuario.get("es_admin")):
            st.divider()
            st.warning("Archivar lo retirará del selector, sin eliminar sus datos ni auditoría.")
            if st.button("Archivar perfil", key=f"archivar_{perfil.id}"):
                try:
                    ok = profile_manager.archivar_perfil_diligenciamiento(
                        perfil.id, perfil.version, str(usuario["id"]), es_admin=True
                    )
                except (PermissionError, database.ConflictoVersionPerfilError) as exc:
                    st.error(str(exc))
                    return None
                if ok:
                    st.session_state.pop("active_profile_id", None)
                    st.success("Perfil archivado de forma reversible.")
    return None
