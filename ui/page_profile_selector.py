"""Selector de sesión para el catálogo compartido de perfiles de diligenciamiento."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import streamlit as st

from core import profile_manager


CLAVE_PERFIL_ACTIVO = "active_profile_id"
CLAVE_PERFIL_NOMBRE = "active_profile_name"
CLAVE_PERFIL_VERSION = "active_profile_version"
OPCION_CREAR = "__crear_perfil_diligenciamiento__"


def invalidar_resultado_por_cambio_perfil(estado_sesion: Dict[str, Any]) -> None:
    """Elimina resultados que pertenecían al snapshot del perfil anterior."""
    for clave in (
        "pipeline_ctx",
        "processed_file_id",
        "plan_verificado",
        "resultado_mapeo",
    ):
        estado_sesion.pop(clave, None)


def _aplicar_perfil(perfil: profile_manager.PerfilDiligenciamiento) -> None:
    """Actualiza solamente la sesión actual y descarta trabajo de otro perfil."""
    cambio = st.session_state.get(CLAVE_PERFIL_ACTIVO) != perfil.id
    st.session_state[CLAVE_PERFIL_ACTIVO] = perfil.id
    st.session_state[CLAVE_PERFIL_NOMBRE] = perfil.nombre
    st.session_state[CLAVE_PERFIL_VERSION] = perfil.version
    if cambio:
        invalidar_resultado_por_cambio_perfil(st.session_state)


def obtener_perfil_activo_sesion() -> Optional[profile_manager.PerfilDiligenciamiento]:
    """Resuelve el perfil elegido y lo invalida si fue archivado entre recargas."""
    profile_id = st.session_state.get(CLAVE_PERFIL_ACTIVO)
    if not profile_id:
        return None
    try:
        perfil = profile_manager.obtener_perfil_diligenciamiento(str(profile_id))
    except profile_manager.PerfilNoDisponibleError:
        invalidar_resultado_por_cambio_perfil(st.session_state)
        st.session_state.pop(CLAVE_PERFIL_ACTIVO, None)
        st.session_state.pop(CLAVE_PERFIL_NOMBRE, None)
        st.session_state.pop(CLAVE_PERFIL_VERSION, None)
        return None
    _aplicar_perfil(perfil)
    return perfil


def render_selector_perfil(
    usuario: Dict[str, Any],
    on_crear: Optional[Callable[[], None]] = None,
) -> Optional[profile_manager.PerfilDiligenciamiento]:
    """Renderiza el selector de perfil y persiste sólo la preferencia del usuario."""
    perfiles = profile_manager.listar_perfiles_diligenciamiento()
    if not perfiles:
        st.warning("Aún no hay perfiles activos. Crea uno para comenzar a diligenciar formularios.")
        if st.button("Crear nuevo perfil", key="crear_primer_perfil") and on_crear:
            on_crear()
        return None

    ids = [perfil.id for perfil in perfiles]
    preferido = profile_manager.obtener_preferencia_perfil(str(usuario["id"]))
    seleccionado = st.session_state.get(CLAVE_PERFIL_ACTIVO)
    if seleccionado not in ids:
        seleccionado = preferido if preferido in ids else ids[0]

    opciones = ids + [OPCION_CREAR]
    etiquetas = {perfil.id: f"{perfil.nombre} · {perfil.tipo.value.title()}" for perfil in perfiles}
    etiquetas[OPCION_CREAR] = "+ Crear nuevo perfil"
    indice = opciones.index(seleccionado) if seleccionado in opciones else 0
    opcion = st.selectbox(
        "Perfil para diligenciar",
        options=opciones,
        index=indice,
        format_func=lambda value: etiquetas[value],
        key="selector_perfil_diligenciamiento",
        help="Cada formulario se llena exclusivamente con los datos del perfil seleccionado.",
    )

    if opcion == OPCION_CREAR:
        if on_crear:
            on_crear()
        return obtener_perfil_activo_sesion()

    perfil = profile_manager.obtener_perfil_diligenciamiento(opcion)
    _aplicar_perfil(perfil)
    if perfil.id == preferido:
        st.caption("Perfil predeterminado de esta cuenta.")
    elif st.button("Usar como mi perfil predeterminado", key="guardar_preferencia_perfil"):
        profile_manager.guardar_preferencia_perfil(str(usuario["id"]), perfil.id, str(usuario["id"]))
        st.success("Perfil predeterminado actualizado para tu cuenta.")
    return perfil
