"""Componente de Verificación Visual con Dropdowns para AutoForm AI.

Permite al usuario revisar, ajustar y confirmar el plan de mapeo generado por la IA
mediante una tabla interactiva (`st.data_editor`) antes de la inyección física de datos.
Permite guardar plantillas permanentes para reutilización automática.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd
import streamlit as st

from pipeline.context import PipelineContext
from template_store.store import guardar_plantilla, calcular_hash_formulario


OPCION_OMITIR = "-- Omitir / Dejar vacío --"

CAMPOS_VIRTUALES = [
    "nit_sin_dv",
    "nit_dv",
    "representante_nombres",
    "representante_apellidos",
]


def _resolver_valor_campo(datos_empresa: Dict[str, Any], campo: str) -> str:
    """Resuelve el valor del campo empresarial, soportando campos virtuales y anidados."""
    if not campo or campo == OPCION_OMITIR:
        return ""

    if campo == "nit_sin_dv" and "nit" in datos_empresa:
        val = str(datos_empresa["nit"])
        return val.split("-")[0] if "-" in val else val

    if campo == "nit_dv" and "nit" in datos_empresa:
        val = str(datos_empresa["nit"])
        return val.split("-")[-1] if "-" in val else ""

    if campo == "representante_nombres":
        if "representante_nombres" in datos_empresa and datos_empresa["representante_nombres"]:
            return str(datos_empresa["representante_nombres"])
        rep_full = str(datos_empresa.get("representante_legal", "")).strip()
        if rep_full:
            partes = rep_full.split()
            return " ".join(partes[:-2]) if len(partes) > 2 else (partes[0] if partes else rep_full)

    if campo == "representante_apellidos":
        if "representante_apellidos" in datos_empresa and datos_empresa["representante_apellidos"]:
            return str(datos_empresa["representante_apellidos"])
        rep_full = str(datos_empresa.get("representante_legal", "")).strip()
        if rep_full:
            partes = rep_full.split()
            return " ".join(partes[-2:]) if len(partes) >= 2 else ""

    if campo in datos_empresa:
        val = datos_empresa[campo]
        return "" if val is None else str(val)

    # Búsqueda por ruta anidada "seccion.subcampo"
    valor = datos_empresa
    for parte in campo.split("."):
        if isinstance(valor, dict) and parte in valor:
            valor = valor[parte]
        else:
            valor = None
            break
    if valor is not None:
        return str(valor)

    return ""


def obtener_opciones_campos_empresa(datos_empresa: Dict[str, Any]) -> List[str]:
    """Construye la lista ordenada de opciones seleccionables en el dropdown."""
    claves = set(datos_empresa.keys()) | set(CAMPOS_VIRTUALES)
    # Ordenar alfabéticamente
    lista_ordenada = sorted(list(claves))
    # Colocar la opción de omitir al inicio
    return [OPCION_OMITIR] + lista_ordenada


def preparar_tabla_verificacion(
    plan_mapeo: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
    elementos_raw: Optional[List[Dict[str, Any]]] = None,
) -> pd.DataFrame:
    """Transforma el plan de mapeo en un DataFrame apto para edición interactiva con Dropdowns."""
    filas = []
    
    # Para incluir también rótulos detectados que el LLM no asignó
    mapeados_indices: Set[Tuple[str, int, int]] = set()
    
    for idx, item in enumerate(plan_mapeo):
        hoja = str(item.get("hoja", ""))
        fila = int(item.get("fila", 0) or 0)
        col = int(item.get("columna", 0) or 0)
        rotulo = str(item.get("valor") or item.get("rotulo") or "")
        campo = str(item.get("campo", "")).strip()
        ubicacion = str(item.get("ubicacion", "derecha")).lower()
        if ubicacion not in ("derecha", "abajo", "misma"):
            ubicacion = "derecha"
            
        campo_select = campo if (campo and campo in datos_empresa or campo in CAMPOS_VIRTUALES) else OPCION_OMITIR
        valor_real = _resolver_valor_campo(datos_empresa, campo_select)
        
        filas.append({
            "N°": idx + 1,
            "Rótulo en el Formulario": rotulo,
            "Ubicación": f"{hoja} (F{fila}:C{col})" if hoja else f"Fila {fila}, Col {col}",
            "Campo Asignado": campo_select,
            "Valor a Escribir": valor_real,
            "Dirección": ubicacion,
            "_hoja": hoja,
            "_fila": fila,
            "_columna": col,
            "_requiereMerge": bool(item.get("requiereMerge", False)),
            "_celdasAMergear": int(item.get("celdasAMergear", 1) or 1),
            "_anchoLinea": int(item.get("anchoLinea", 1) or 1),
            "_orig_idx": idx,
        })
        mapeados_indices.add((hoja, fila, col))

    df = pd.DataFrame(filas)
    return df


def aplicar_cambios_verificacion(
    df_editado: pd.DataFrame,
    plan_original: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Convierte el DataFrame editado por el usuario de vuelta en un plan de mapeo estructurado."""
    plan_resultado: List[Dict[str, Any]] = []

    for _, row in df_editado.iterrows():
        campo_seleccionado = str(row.get("Campo Asignado", "")).strip()
        
        # Si el usuario seleccionó omitir, no incluir en la inyección
        if not campo_seleccionado or campo_seleccionado == OPCION_OMITIR:
            continue

        direccion = str(row.get("Dirección", "derecha")).lower()
        if direccion not in ("derecha", "abajo", "misma"):
            direccion = "derecha"

        hoja = str(row.get("_hoja", ""))
        fila = int(row.get("_fila", 0))
        columna = int(row.get("_columna", 0))
        rotulo = str(row.get("Rótulo en el Formulario", ""))
        ancho_l = int(row.get("_anchoLinea", 1) or 1)
        req_merge = bool(row.get("_requiereMerge", False) or (ancho_l > 1 and direccion == "derecha"))

        item_final = {
            "hoja": hoja,
            "fila": fila,
            "columna": columna,
            "valor": rotulo,
            "ubicacion": direccion,
            "campo": campo_seleccionado,
            "requiereMerge": req_merge,
            "celdasAMergear": int(row.get("_celdasAMergear", ancho_l) or ancho_l),
            "anchoLinea": ancho_l,
        }

        # Preservar metadatos físicos de PDF si existían en el plan original
        orig_idx = row.get("_orig_idx")
        if orig_idx is not None and 0 <= int(orig_idx) < len(plan_original):
            orig_item = plan_original[int(orig_idx)]
            for k in ("_pdf_page", "_pdf_bbox", "_pdf_target_rect", "_pdf_es_caja", "_pdf_es_casilla", "_pdf_es_acroform", "_pdf_widget_name"):
                if k in orig_item:
                    item_final[k] = orig_item[k]

        plan_resultado.append(item_final)

    return plan_resultado


def render_pantalla_verificacion(
    ctx: PipelineContext,
    key_prefix: str = "verif_ui",
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Renderiza la interfaz de verificación visual interactiva en Streamlit.
    
    Returns:
        Tuple: (confirmado: bool, plan_verificado: List[Dict[str, Any]])
    """
    plan_activo = ctx.obtener_plan_activo()
    if not plan_activo:
        st.warning("⚠️ No se encontraron campos detectados para verificar en este formulario.")
        return False, []

    opciones_campos = obtener_opciones_campos_empresa(ctx.datos_empresa)

    st.markdown("### 📋 Verificación y Asignación de Campos")
    st.markdown(
        "Revisa y ajusta las asignaciones sugeridas por la IA con los menús desplegables (**Dropdowns**). "
        "Puedes cambiar qué dato de la empresa va en cada casilla o seleccionar *Omitir* para no rellenar celdas no deseadas."
    )

    # ── Métricas resumidas de la verificación ──
    col1, col2, col3, col4 = st.columns(4)
    total_rotulos = len(ctx.elementos_raw) if ctx.elementos_raw else len(plan_activo)
    mapeados_count = sum(1 for p in plan_activo if p.get("campo"))
    
    with col1:
        st.metric("📄 Formulario", ctx.nombre_archivo or "Documento")
    with col2:
        st.metric("🏷️ Campos Mapeados", f"{mapeados_count}")
    with col3:
        tipo_badge = ctx.tipo_documento.upper() if ctx.tipo_documento else "DESCONOCIDO"
        st.metric("📁 Tipo", tipo_badge)
    with col4:
        origen_txt = "💾 Plantilla Guardada" if ctx.es_plantilla_guardada else "🤖 Sugerencia IA"
        st.metric("Origen", origen_txt)

    # ── Preparar DataFrame para Streamlit Data Editor ──
    df_inicial = preparar_tabla_verificacion(plan_activo, ctx.datos_empresa, ctx.elementos_raw)

    # Configuración de columnas interactivas
    config_columnas = {
        "N°": st.column_config.NumberColumn("N°", width="small", disabled=True),
        "Rótulo en el Formulario": st.column_config.TextColumn("Rótulo Detectado", width="large", disabled=True),
        "Ubicación": st.column_config.TextColumn("Ubicación", width="medium", disabled=True),
        "Campo Asignado": st.column_config.SelectboxColumn(
            "Dato de la Empresa (Dropdown)",
            help="Selecciona qué dato de tu empresa debe inyectarse en este rótulo",
            width="large",
            options=opciones_campos,
            required=True,
        ),
        "Valor a Escribir": st.column_config.TextColumn("Valor Resultante", width="large", disabled=True),
        "Dirección": st.column_config.SelectboxColumn(
            "Dirección de Escritura",
            help="Hacia dónde se inyectará el dato respecto al rótulo",
            width="medium",
            options=["derecha", "abajo", "misma"],
            required=True,
        ),
        # Columnas ocultas de metadatos
        "_hoja": None,
        "_fila": None,
        "_columna": None,
        "_requiereMerge": None,
        "_celdasAMergear": None,
        "_anchoLinea": None,
        "_orig_idx": None,
    }

    # Render del editor de datos de Streamlit
    df_editado = st.data_editor(
        df_inicial,
        column_config=config_columnas,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        key=f"{key_prefix}_data_editor",
    )

    # Actualizar valores resultantes en tiempo real
    plan_actualizado = aplicar_cambios_verificacion(df_editado, plan_activo, ctx.datos_empresa)

    st.markdown("---")

    # ── Botonera de Acciones ──
    col_guardar, col_confirmar, col_reset = st.columns([1.5, 2, 1.2])

    with col_guardar:
        if st.button("💾 Guardar como Plantilla Permanente", key=f"{key_prefix}_btn_save", help="Guarda esta configuración para que futuros formularios iguales se llenen automáticamente."):
            plantilla_id = ctx.plantilla_id or calcular_hash_formulario(ctx.elementos_raw or plan_activo)
            ruta_guardada = guardar_plantilla(
                plantilla_id=plantilla_id,
                nombre_formulario=ctx.nombre_archivo or f"Formulario_{plantilla_id[:8]}",
                tipo_documento=ctx.tipo_documento or "excel",
                elementos_raw=ctx.elementos_raw or plan_activo,
                plan_mapeo=plan_actualizado,
                metadatos={"guardado_desde_ui": True},
            )
            ctx.plantilla_id = plantilla_id
            ctx.es_plantilla_guardada = True
            st.success(f"✅ ¡Plantilla guardada permanentemente! ({len(plan_actualizado)} campos registrados en `{ruta_guardada.name}`).")

    with col_confirmar:
        confirmar_click = st.button(
            "⚡ Confirmar y Rellenar Formulario",
            type="primary",
            key=f"{key_prefix}_btn_confirm",
            help="Inyecta los datos confirmados en el archivo original y genera la descarga.",
        )
        if confirmar_click:
            ctx.plan_verificado = plan_actualizado
            ctx.log(f"Plan de mapeo verificado y confirmado por el usuario ({len(plan_actualizado)} campos).")
            return True, plan_actualizado

    with col_reset:
        if st.button("🔄 Restablecer", key=f"{key_prefix}_btn_reset", help="Restaura las sugerencias iniciales de la IA"):
            ctx.plan_verificado = []
            st.rerun()

    return False, plan_actualizado
