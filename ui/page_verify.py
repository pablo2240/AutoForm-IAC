"""Componente de Verificación Visual con Dropdowns para AutoForm AI (Versión Completa).

Muestra TODOS los rótulos detectados en el formulario (tanto los asignados por IA como
los candidatos viables pendientes) para que el usuario tenga control total de asignación.
Permite búsqueda, filtrado por estado, edición con Dropdowns y guardado de plantillas permanentes.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd
import streamlit as st

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

from pipeline.context import PipelineContext
from template_store.store import guardar_plantilla, calcular_hash_formulario


OPCION_OMITIR = "-- Omitir / Dejar vacío --"

CAMPOS_VIRTUALES = [
    "nit_sin_dv",
    "nit_dv",
    "representante_nombres",
    "representante_apellidos",
]

# Sinónimos robustos para sugerir coincidencias parciales (solo palabras significativas >= 3 letras)
_SINONIMOS_RAPIDOS = {
    "razon_social": ["razon social", "empresa", "proveedor", "denominacion social", "sociedad", "solicitante"],
    "nit": ["nit", "rut", "identificacion tributaria", "registro fiscal", "numero de identificacion tributaria"],
    "nit_sin_dv": ["nit sin dv", "nit base"],
    "nit_dv": ["digito de verificacion", "digito verificacion"],
    "tipo_documento": ["tipo de documento", "tipo documento", "tipo id", "tipo de id", "tipo identificacion", "tipo de identificacion", "clase de documento", "tipo doc"],
    "cedula": ["cedula", "cedula de ciudadania", "documento de identidad", "documento de identificacion", "no de documento", "identificacion del representante"],
    "representante_legal": ["representante legal", "apoderado", "director general"],
    "representante_nombres": ["nombres del representante", "primer nombre", "segundo nombre"],
    "representante_apellidos": ["apellidos del representante", "primer apellido", "segundo apellido"],
    "direccion": ["direccion", "domicilio principal", "sede principal", "direccion fiscal", "direccion de notificacion"],
    "telefono": ["telefono", "telefono fijo", "pbx institucional", "telefono corporativo"],
    "celular": ["celular", "telefono movil", "celular del representante", "numero de celular"],
    "correo": ["correo", "email", "e-mail", "correo electronico", "correo institucional"],
    "pagina_web": ["pagina web", "sitio web", "portal web", "url institucional"],
    "banco": ["banco", "entidad bancaria", "institucion financiera", "nombre de la entidad financiera", "entidad financiera"],
    "numero_cuenta": ["numero de cuenta", "no de cuenta", "nro cuenta", "cuenta bancaria"],
    "tipo_cuenta": ["tipo de cuenta", "tipo cuenta", "modalidad de cuenta"],
    "sucursal": ["sucursal", "agencia bancaria", "oficina bancaria", "sucursal bancaria"],
    "ciudad": ["ciudad", "municipio", "ciudad fiscal", "ciudad de domicilio"],
    "departamento": ["departamento", "provincia"],
    "pais": ["pais", "nacionalidad"],
    "expedicion": ["lugar de expedicion", "ciudad de expedicion", "expedida en", "municipio de expedicion", "lugar expedicion"],
}


def _normalizar(txt: str) -> str:
    if not txt:
        return ""
    nfd = "".join(c for c in unicodedata.normalize("NFD", str(txt).lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s_\.\:\-\;\,\(\)\[\]\/\\]+", " ", nfd).strip()


def _sugerir_campo_para_rotulo(rotulo: str, campos_disponibles: List[str]) -> Optional[str]:
    """Intenta sugerir una coincidencia parcial para un rótulo no asignado usando tokenización de palabra completa."""
    r_norm = _normalizar(rotulo)
    if not r_norm or len(r_norm) < 3:
        return None

    # Omitir palabras reservadas de opciones o preguntas
    if r_norm in ("si", "no", "s", "n", "m", "f", "ahorros", "corriente", "otro", "otra", "na", "n a"):
        return None

    # Si el rótulo solicita una FECHA (día/mes/año), NUNCA sugerir 'expedicion' (que es ciudad/lugar)
    if "fecha" in r_norm:
        return None

    # 1. Búsqueda por sinónimos de coincidencia exacta o frase completa
    for campo, sinonimos in _SINONIMOS_RAPIDOS.items():
        if campo in campos_disponibles or campo in CAMPOS_VIRTUALES:
            for s in sinonimos:
                if s == r_norm:
                    return campo
                # Si el sinónimo tiene más de 3 letras, verificar coincidencia con límites de palabra (\b)
                if len(s) >= 4 and re.search(r"\b" + re.escape(s) + r"\b", r_norm):
                    return campo

    # 2. Búsqueda difusa estricta con rapidfuzz (token_sort_ratio >= 88)
    if fuzz is not None and len(r_norm) >= 4:
        mejor_campo = None
        mejor_score = 0.0
        for campo in campos_disponibles:
            c_norm = _normalizar(campo)
            score = float(fuzz.token_sort_ratio(r_norm, c_norm))
            if score >= 88.0 and score > mejor_score:
                mejor_score = score
                mejor_campo = campo
        if mejor_campo:
            return mejor_campo

    return None


def _resolver_valor_campo(datos_empresa: Dict[str, Any], campo: str) -> str:
    """Resuelve el valor del campo empresarial, soportando campos virtuales y anidados."""
    if not campo or campo == OPCION_OMITIR:
        return ""

    from core.profile_manager import aplanar_perfil
    plano = aplanar_perfil(datos_empresa)

    if campo == "nit_sin_dv" and "nit" in plano:
        val = str(plano["nit"])
        return val.split("-")[0] if "-" in val else val

    if campo == "nit_dv" and "nit" in plano:
        val = str(plano["nit"])
        return val.split("-")[-1] if "-" in val else ""

    if campo == "representante_nombres":
        if "representante_nombres" in plano and plano["representante_nombres"]:
            return str(plano["representante_nombres"])
        rep_full = str(plano.get("representante_legal", "")).strip()
        if rep_full:
            partes = rep_full.split()
            return " ".join(partes[:-2]) if len(partes) > 2 else (partes[0] if partes else rep_full)

    if campo == "representante_apellidos":
        if "representante_apellidos" in plano and plano["representante_apellidos"]:
            return str(plano["representante_apellidos"])
        rep_full = str(plano.get("representante_legal", "")).strip()
        if rep_full:
            partes = rep_full.split()
            return " ".join(partes[-2:]) if len(partes) >= 2 else ""

    if campo in plano:
        val = plano[campo]
        if not isinstance(val, dict):
            return "" if val is None else str(val)

    return ""


def obtener_opciones_campos_empresa(datos_empresa: Dict[str, Any]) -> List[str]:
    """Construye la lista ordenada de opciones seleccionables en el dropdown."""
    from core.profile_manager import aplanar_perfil
    plano = aplanar_perfil(datos_empresa)
    
    # Filtrar solo claves no compuestas (sin punto) para una lista limpia y legible
    claves_limpias = {k for k in plano.keys() if "." not in k and not isinstance(plano[k], dict)}
    claves = claves_limpias | set(CAMPOS_VIRTUALES)
    lista_ordenada = sorted(list(claves))
    return [OPCION_OMITIR] + lista_ordenada


def preparar_tabla_verificacion(
    plan_mapeo: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
    elementos_raw: Optional[List[Dict[str, Any]]] = None,
) -> pd.DataFrame:
    """Transforma el plan de mapeo y TODOS los rótulos detectados en un DataFrame interactivo con estados funcionales."""
    from pipeline.stages.stage_2_classifier import clasificar_rotulo_individual, ClasificacionElemento

    filas = []
    claves_disponibles = list(datos_empresa.keys()) + CAMPOS_VIRTUALES
    
    # Índice de celdas ya presentes en plan_mapeo
    coordenadas_mapeadas: Set[Tuple[str, int, int]] = set()

    # 1. Agregar primero los campos asignados por IA o Plantilla
    for idx, item in enumerate(plan_mapeo):
        hoja = str(item.get("hoja", ""))
        fila = int(item.get("fila", 0) or 0)
        col = int(item.get("columna", 0) or 0)
        rotulo = str(item.get("valor") or item.get("rotulo") or "").strip()
        campo = str(item.get("campo", "")).strip()
        ubicacion = str(item.get("ubicacion", "derecha")).lower()
        if ubicacion not in ("derecha", "abajo", "misma"):
            ubicacion = "derecha"

        campo_select = campo if (campo and (campo in datos_empresa or campo in CAMPOS_VIRTUALES)) else OPCION_OMITIR
        valor_real = _resolver_valor_campo(datos_empresa, campo_select)
        
        estado = "✅ Sugerido por IA" if campo_select != OPCION_OMITIR else "⚪ Sin asignar"

        filas.append({
            "N°": idx + 1,
            "Rótulo en el Formulario": rotulo,
            "Ubicación": f"{hoja} (F{fila}:C{col})" if hoja else f"Fila {fila}, Col {col}",
            "Estado": estado,
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
        coordenadas_mapeadas.add((hoja, fila, col))

    # 2. Agregar todos los demás elementos detectados en elementos_raw con su rol funcional
    if elementos_raw:
        n_extra = len(filas) + 1
        for elem in elementos_raw:
            hoja_e = str(elem.get("hoja", ""))
            fila_e = int(elem.get("fila", 0) or 0)
            col_e = int(elem.get("columna", 0) or 0)
            rot_e = str(elem.get("valor") or elem.get("rotulo") or "").strip()

            # Evitar duplicar celdas ya mapeadas o rótulos vacíos
            if (hoja_e, fila_e, col_e) in coordenadas_mapeadas or not rot_e:
                continue

            tipo_clasif = elem.get("tipo_clasificacion")
            if not tipo_clasif:
                tipo_clasif_enum = clasificar_rotulo_individual(rot_e, elem)
                tipo_clasif = tipo_clasif_enum.value

            r_norm = _normalizar(rot_e)

            # Clasificación y asignación según el rol funcional
            if tipo_clasif in (
                ClasificacionElemento.OPCION_SELECCION.value,
                ClasificacionElemento.TEXTO_LEGAL.value,
                ClasificacionElemento.INSTRUCCION_TEXTO.value,
                ClasificacionElemento.CONTROL_DOCUMENTAL.value,
                ClasificacionElemento.USO_EXCLUSIVO.value,
                ClasificacionElemento.FIRMA_ESPACIO.value,
                ClasificacionElemento.NO_APLICA.value,
            ):
                campo_final = OPCION_OMITIR
                valor_final = ""
                estado = "⚫ No es un campo"

            elif r_norm in ("identificacion", "id", "documento", "identificacion no", "no identificacion") and not elem.get("seccion_padre"):
                campo_final = OPCION_OMITIR
                valor_final = ""
                estado = "⚠️ Requiere revisión"

            else:
                sugerido = _sugerir_campo_para_rotulo(rot_e, claves_disponibles)
                if sugerido:
                    # Coincidencias parciales nacen como sugerencia visual en -- Omitir -- para revisión manual
                    campo_final = OPCION_OMITIR
                    valor_final = ""
                    estado = f"🟡 Coincidencia parcial (Sugerido: {sugerido})"
                else:
                    campo_final = OPCION_OMITIR
                    valor_final = ""
                    estado = "⚪ Sin asignar"

            ancho_l = int(elem.get("anchoLinea", 1) or 1)
            ubic = str(elem.get("tipoEspacioEscritura", "derecha")).lower()
            if ubic not in ("derecha", "abajo", "misma"):
                ubic = "derecha"

            filas.append({
                "N°": n_extra,
                "Rótulo en el Formulario": rot_e,
                "Ubicación": f"{hoja_e} (F{fila_e}:C{col_e})" if hoja_e else f"Fila {fila_e}, Col {col_e}",
                "Estado": estado,
                "Campo Asignado": campo_final,
                "Valor a Escribir": valor_final,
                "Dirección": ubic,
                "_hoja": hoja_e,
                "_fila": fila_e,
                "_columna": col_e,
                "_requiereMerge": bool(ancho_l > 1),
                "_celdasAMergear": ancho_l,
                "_anchoLinea": ancho_l,
                "_orig_idx": -1,
            })
            coordenadas_mapeadas.add((hoja_e, fila_e, col_e))
            n_extra += 1

    df = pd.DataFrame(filas)
    if not df.empty:
        df["N°"] = df["N°"].astype(int)
        df["Rótulo en el Formulario"] = df["Rótulo en el Formulario"].astype(str)
        df["Ubicación"] = df["Ubicación"].astype(str)
        df["Estado"] = df["Estado"].astype(str)
        df["Campo Asignado"] = df["Campo Asignado"].astype(str)
        df["Valor a Escribir"] = df["Valor a Escribir"].astype(str)
        df["Dirección"] = df["Dirección"].astype(str)
        df["_hoja"] = df["_hoja"].astype(str)
        df["_fila"] = df["_fila"].astype(int)
        df["_columna"] = df["_columna"].astype(int)
        df["_requiereMerge"] = df["_requiereMerge"].astype(bool)
        df["_celdasAMergear"] = df["_celdasAMergear"].astype(int)
        df["_anchoLinea"] = df["_anchoLinea"].astype(int)
        df["_orig_idx"] = df["_orig_idx"].astype(int)

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

        # Preservar metadatos físicos de PDF si existían
        orig_idx = row.get("_orig_idx")
        if orig_idx is not None and not pd.isna(orig_idx):
            idx_int = int(orig_idx)
            if 0 <= idx_int < len(plan_original):
                orig_item = plan_original[idx_int]
                for k in ("_pdf_page", "_pdf_bbox", "_pdf_target_rect", "_pdf_es_caja", "_pdf_es_casilla", "_pdf_es_acroform", "_pdf_widget_name"):
                    if k in orig_item:
                        item_final[k] = orig_item[k]

        plan_resultado.append(item_final)

    return plan_resultado


def render_pantalla_verificacion(
    ctx: PipelineContext,
    key_prefix: str = "verif_ui",
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Renderiza la interfaz de verificación visual interactiva en Streamlit."""
    plan_activo = ctx.obtener_plan_activo()
    elementos_todos = ctx.elementos_clasificados if ctx.elementos_clasificados else ctx.elementos_raw

    if not plan_activo and not elementos_todos:
        st.warning("⚠️ No se encontraron campos detectados para verificar en este formulario.")
        return False, []

    opciones_campos = obtener_opciones_campos_empresa(ctx.datos_empresa)

    st.markdown("### 📋 Verificación y Asignación de Campos")
    st.markdown(
        "A continuación se muestran los **elementos y campos detectados** en el formulario clasificados por rol funcional. "
        "Los campos sugeridos por la IA ya vienen pre-seleccionados. Puedes asignar datos a los candidatos viables o cambiar cualquier selector."
    )

    # ── Preparar DataFrame Completo con Clasificación Funcional ──
    df_inicial = preparar_tabla_verificacion(plan_activo, ctx.datos_empresa, elementos_todos)

    total_detectados = len(df_inicial)
    total_asignados = sum(1 for c in df_inicial["Campo Asignado"] if c != OPCION_OMITIR)
    total_pendientes = sum(1 for _, r in df_inicial.iterrows() if r["Campo Asignado"] == OPCION_OMITIR and r["Estado"] != "⚫ No es un campo")
    total_no_campos = sum(1 for e in df_inicial["Estado"] if e == "⚫ No es un campo")

    # ── Métricas Resumidas ──
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📄 Formulario", ctx.nombre_archivo or "Documento")
    with col2:
        st.metric("🏷️ Total Detectados", f"{total_detectados}")
    with col3:
        st.metric("✅ Campos Asignados", f"{total_asignados}")
    with col4:
        st.metric("⚪ Pendientes / Revisión", f"{total_pendientes}")

    # ── Barra de Búsqueda y Filtros ──
    col_search, col_filter = st.columns([2, 2])
    with col_search:
        filtro_texto = st.text_input("🔍 Buscar rótulo o campo...", key=f"{key_prefix}_search_input", placeholder="Ej: Representante, Cuenta, NIT, Banco...").strip().lower()
    with col_filter:
        vista_filtro = st.radio(
            "Ver:",
            ["Todos", "Solo Asignados", "Solo Pendientes / Revisión", "Omitidos (No campo)"],
            horizontal=True,
            key=f"{key_prefix}_vista_filter",
        )

    # Aplicar filtrado al DataFrame visual
    df_filtrado = df_inicial.copy()
    if filtro_texto:
        df_filtrado = df_filtrado[
            df_filtrado["Rótulo en el Formulario"].str.lower().str.contains(filtro_texto) |
            df_filtrado["Campo Asignado"].str.lower().str.contains(filtro_texto)
        ]

    if vista_filtro == "Solo Asignados":
        df_filtrado = df_filtrado[df_filtrado["Campo Asignado"] != OPCION_OMITIR]
    elif vista_filtro == "Solo Pendientes / Revisión":
        df_filtrado = df_filtrado[(df_filtrado["Campo Asignado"] == OPCION_OMITIR) & (df_filtrado["Estado"] != "⚫ No es un campo")]
    elif vista_filtro == "Omitidos (No campo)":
        df_filtrado = df_filtrado[df_filtrado["Estado"] == "⚫ No es un campo"]

    # Configuración de columnas interactivas
    config_columnas = {
        "N°": st.column_config.NumberColumn("N°", width="small", disabled=True),
        "Rótulo en el Formulario": st.column_config.TextColumn("Rótulo Detectado en el Formato", width="large", disabled=True),
        "Ubicación": st.column_config.TextColumn("Ubicación", width="medium", disabled=True),
        "Estado": st.column_config.TextColumn("Confianza / Estado", width="medium", disabled=True),
        "Campo Asignado": st.column_config.SelectboxColumn(
            "Dato de la Empresa (Dropdown)",
            help="Selecciona qué dato de tu empresa debe inyectarse en este rótulo",
            width="large",
            options=opciones_campos,
            required=True,
        ),
        "Valor a Escribir": st.column_config.TextColumn("Valor Resultante", width="large", disabled=True),
        "Dirección": st.column_config.SelectboxColumn(
            "Dirección",
            help="Hacia dónde se inyectará el dato respecto al rótulo",
            width="small",
            options=["derecha", "abajo", "misma"],
            required=True,
        ),
        # Columnas internas ocultas
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
        df_filtrado,
        column_config=config_columnas,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key=f"{key_prefix}_data_editor",
    )

    # Actualizar valores resultantes en el plan completo
    # Si hubo filtro, fusionar con las filas no visibles para no perder datos
    if len(df_filtrado) < len(df_inicial):
        indices_editados = set(df_editado["N°"])
        df_no_editadas = df_inicial[~df_inicial["N°"].isin(indices_editados)]
        df_consolidado = pd.concat([df_editado, df_no_editadas]).sort_values("N°")
    else:
        df_consolidado = df_editado

    plan_actualizado = aplicar_cambios_verificacion(df_consolidado, plan_activo, ctx.datos_empresa)

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
