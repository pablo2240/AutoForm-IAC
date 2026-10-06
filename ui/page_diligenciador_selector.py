"""Selector exclusivo de 'Diligenciado por' (comercial, asesor o persona que tramita el formulario)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from core import profile_manager
from ui.page_profile_selector import invalidar_resultado_por_cambio_perfil


CLAVE_SELECTOR = "selector_diligenciador"
CLAVE_ACTIVO = "diligenciador_activo_id"
CLAVE_PENDIENTE = "_diligenciador_pendiente"
OPCION_MI_PERFIL = "__mi_perfil__"
OPCION_CREAR = "__crear_diligenciador__"

DIRECCION_POR_DEFECTO = "Carrera 63 B # 32 E -25 OFC 206"
CIUDAD_POR_DEFECTO = "Bogotá"


def construir_operador_propio(usuario: Dict[str, Any]) -> Dict[str, Any]:
    """Arma el diligenciador a partir de la cuenta en sesión (opción 'Mi perfil')."""
    return {
        "id": str(usuario.get("id") or ""),
        "nombre": str(usuario.get("nombre") or ""),
        "cargo": str(usuario.get("cargo") or ""),
        "cedula": str(usuario.get("cedula") or ""),
        "telefono": str(usuario.get("telefono") or ""),
        "correo": str(usuario.get("correo") or ""),
        "direccion": str(usuario.get("direccion") or DIRECCION_POR_DEFECTO),
        "ciudad": str(usuario.get("ciudad") or CIUDAD_POR_DEFECTO),
    }


def operadores_guardados(usuario: Dict[str, Any], operadores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Operadores del catálogo sin el registro de la propia cuenta (ya cubierto por 'Mi perfil')."""
    propio_id = str(usuario.get("id") or "").lower()
    propio_correo = str(usuario.get("correo") or "").lower()
    return [
        o for o in operadores
        if str(o.get("id") or "").lower() != propio_id
        and not (propio_correo and str(o.get("correo") or "").lower() == propio_correo)
    ]


def resolver_diligenciador(
    seleccion: str,
    usuario: Dict[str, Any],
    guardados: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resuelve la opción elegida a un diligenciador; ante un id desconocido usa 'Mi perfil'."""
    if seleccion != OPCION_MI_PERFIL:
        for operador in guardados:
            if str(operador.get("id")) == seleccion:
                return dict(operador)
    return construir_operador_propio(usuario)


def _etiqueta(operador: Dict[str, Any]) -> str:
    cargo = str(operador.get("cargo") or "").strip()
    return f"{operador['nombre']} - {cargo}" if cargo else str(operador["nombre"])


def _render_formulario_creacion(usuario: Dict[str, Any]) -> None:
    """Formulario de datos fijos de un diligenciador nuevo; lo deja seleccionado al guardarlo."""
    with st.form("form_crear_diligenciador", clear_on_submit=True):
        nombre = st.text_input("Nombre completo", placeholder="Ej.: José Pérez")
        cedula = st.text_input("Cédula")
        cargo = st.text_input("Cargo", placeholder="Ej.: Comercial")
        telefono = st.text_input("Teléfono / celular")
        correo = st.text_input("Correo")
        enviado = st.form_submit_button("Guardar y usar", use_container_width=True)
    if not enviado:
        return
    try:
        nuevo = profile_manager.crear_diligenciador(
            nombre=nombre,
            cargo=cargo,
            cedula=cedula,
            telefono=telefono,
            correo=correo,
            direccion=DIRECCION_POR_DEFECTO,
            ciudad=CIUDAD_POR_DEFECTO,
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    st.session_state[CLAVE_PENDIENTE] = str(nuevo["id"])
    st.rerun()


def render_selector_diligenciador(usuario: Dict[str, Any]) -> Dict[str, Any]:
    """Renderiza el selector y devuelve el diligenciador elegido para esta sesión.

    La elección vive solo en ``st.session_state``; no modifica ninguna marca global.
    """
    guardados = operadores_guardados(usuario, profile_manager.listar_operadores())

    pendiente = st.session_state.pop(CLAVE_PENDIENTE, None)
    if pendiente:
        st.session_state[CLAVE_SELECTOR] = pendiente

    ids_guardados = [str(o["id"]) for o in guardados]
    opciones = [OPCION_MI_PERFIL] + ids_guardados + [OPCION_CREAR]
    if st.session_state.get(CLAVE_SELECTOR) not in opciones:
        st.session_state[CLAVE_SELECTOR] = OPCION_MI_PERFIL

    etiquetas = {OPCION_MI_PERFIL: f"Mi perfil · {usuario.get('nombre') or 'mi cuenta'}", OPCION_CREAR: "+ Crear nuevo perfil de diligenciador"}
    etiquetas.update({str(o["id"]): _etiqueta(o) for o in guardados})

    seleccion = st.selectbox(
        "¿Quién diligencia este formulario?",
        options=opciones,
        format_func=lambda valor: etiquetas[valor],
        key=CLAVE_SELECTOR,
        help="Sus datos se usan en 'Diligenciado por / Contacto comercial'. Los datos de la empresa son fijos.",
    )

    if seleccion == OPCION_CREAR:
        _render_formulario_creacion(usuario)
        seleccion = st.session_state.get(CLAVE_ACTIVO, OPCION_MI_PERFIL)
        if seleccion not in opciones:
            seleccion = OPCION_MI_PERFIL

    operador = resolver_diligenciador(seleccion, usuario, guardados)
    anterior = st.session_state.get(CLAVE_ACTIVO)
    if anterior is not None and anterior != seleccion:
        invalidar_resultado_por_cambio_perfil(st.session_state)
    st.session_state[CLAVE_ACTIVO] = seleccion
    return operador
