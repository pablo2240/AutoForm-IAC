"""Componente de Verificación Visual con Dropdowns para AutoForm AI (Fase 4 HSP).

Muestra TODOS los rótulos detectados en el formulario estructurados con la jerarquía
de secciones, semáforos de confianza (🟢/🟡/⚪), y motivos de validación determinística.
Permite búsqueda, filtrado por sección y estado, edición interactiva y guardado de plantillas.
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
    "ciudad_departamento",
    "representante_nombres",
    "representante_apellidos",
]

# Sinónimos robustos para sugerir coincidencias parciales
_SINONIMOS_RAPIDOS = {
    "razon_social": [
        "razon social", "empresa", "proveedor", "denominacion social", "sociedad", "solicitante",
        "nombre comercial", "nombre o razon social", "razon social / nombre comercial",
        "razon social o nombre comercial", "razon social nombre comercial",
    ],
    "nit": [
        "nit", "rut", "identificacion tributaria", "registro fiscal", "numero de identificacion tributaria",
        "nit tax id", "tax id", "tax id nit", "tax identification number", "nit/tax id", "tax id/nit",
        "cc ce pas nit", "cc ce nit", "cc nit", "nit cc", "cc nit rut",
    ],
    "tipo_documento": [
        "tipo de documento", "tipo documento", "tipo id", "tipo de id", "tipo identificacion",
        "tipo de identificacion", "clase de documento", "tipo doc",
        "tipo de identificacion (cc-pasaporte-ce)", "tipo de identificacion cc pasaporte ce",
        "tipo de identificacion cc ce pasaporte", "tipo de documento cc ce pasaporte",
    ],
    "cedula": [
        "cedula", "cedula de ciudadania", "documento de identidad", "documento de identificacion",
        "no de documento", "numero de documento", "identificacion del representante", "identificacion",
        "numero de identificacion", "nro de identificacion", "no de identificacion", "no identificacion",
        "identificacion no", "numero identificacion", "nro identificacion",
    ],
    "representante_legal": [
        "representante legal", "apoderado", "director general", "nombre del representante",
        "razon social o nombres y apellidos", "razon social o nombres y apellidos del representante",
        "nombres y apellidos", "nombre y apellidos",
    ],
    "representante_nombres": ["nombres del representante", "primer nombre", "segundo nombre"],
    "representante_apellidos": ["apellidos del representante", "primer apellido", "segundo apellido"],
    "direccion": ["direccion", "domicilio principal", "sede principal", "direccion fiscal", "direccion de notificacion"],
    "telefono": ["telefono", "telefono fijo", "pbx institucional", "telefono corporativo"],
    "celular": [
        "celular", "telefono movil", "celular del representante", "numero de celular",
        "telefono celular", "telefono / celular", "telefono/celular", "tel/cel", "tel celular", "movil",
    ],
    "correo": ["correo", "email", "e-mail", "correo electronico", "correo institucional"],
    "pagina_web": ["pagina web", "sitio web", "portal web", "url institucional"],
    "banco": ["banco", "entidad bancaria", "institucion financiera", "nombre de la entidad financiera", "entidad financiera"],
    "numero_cuenta": ["numero de cuenta", "no de cuenta", "nro cuenta", "cuenta bancaria"],
    "tipo_cuenta": ["tipo de cuenta", "tipo cuenta", "modalidad de cuenta"],
    "sucursal": ["sucursal", "agencia bancaria", "oficina bancaria", "sucursal bancaria"],
    "ciudad": ["ciudad", "municipio", "ciudad fiscal", "ciudad de domicilio"],
    "departamento": ["departamento", "provincia"],
    "ciudad_departamento": [
        "ciudad departamento", "ciudad / departamento", "ciudad/departamento",
        "ciudad depto", "ciudad / depto", "ciudad y departamento",
        "municipio departamento", "municipio / departamento", "municipio/departamento",
    ],
    "pais": ["pais", "nacionalidad"],
    "lugar_expedicion": ["lugar de expedicion", "ciudad de expedicion", "expedida en", "municipio de expedicion", "lugar expedicion", "expedida"],
    "expedicion": ["lugar de expedicion", "ciudad de expedicion", "expedida en", "municipio de expedicion", "lugar expedicion"],
}


def _normalizar(txt: str) -> str:
    if not txt:
        return ""
    nfd = "".join(c for c in unicodedata.normalize("NFD", str(txt).lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s_\.\:\-\;\,\(\)\[\]\/\\]+", " ", nfd).strip()


def _sugerir_campo_para_rotulo(rotulo: str, campos_disponibles: List[str], seccion_padre: str = "") -> Optional[str]:
    """Intenta sugerir una coincidencia parcial para un rótulo no asignado usando tokenización de palabra completa."""
    r_norm = _normalizar(rotulo)
    if not r_norm or len(r_norm) < 3:
        return None

    # Omitir palabras reservadas de opciones o preguntas
    if r_norm in ("si", "no", "s", "n", "m", "f", "ahorros", "corriente", "otro", "otra", "na", "n a"):
        return None

    # Si el rótulo solicita una FECHA (día/mes/año), NUNCA sugerir 'lugar_expedicion' ni 'expedicion'
    if "fecha" in r_norm:
        return None

    # 1. Teléfono Celular o Teléfono/Celular -> Prioridad a CELULAR
    if re.search(r"\btel[eé]fono[\s/]*celular\b|\btel[\s/]*cel\b|\bcelular\b|\bmovil\b|\bm[oó]vil\b", r_norm):
        return "celular"

    # 2. Ciudad / Departamento combinado -> ciudad_departamento ("Medellin/Antioquia")
    if re.search(r"\bciudad[\s/]+departamento\b|\bciudad[\s/]+depto\b|\bmunicipio[\s/]+departamento\b", r_norm):
        return "ciudad_departamento"

    # 3. Razón Social o Nombres y Apellidos -> representante_legal
    if "razon social" in r_norm and ("nombres" in r_norm or "apellidos" in r_norm):
        return "representante_legal"

    # 4. Nombre Comercial -> razon_social
    if "nombre comercial" in r_norm:
        return "razon_social"

    # 5. Tipo de Identificación (CC-Pasaporte-CE) -> tipo_documento
    if "tipo" in r_norm and any(k in r_norm for k in ("documento", "identificacion", "id")):
        return "tipo_documento"

    # 6. NIT / TAX ID o rótulos compuestos con NIT (CC/CE/PAS/NIT) -> 'nit'
    if re.search(r"\bnit[\s/]*tax\s*id\b|\btax\s*id\b|\bcc[\s/]*ce[\s/]*pas[\s/]*nit\b|\bcc[\s/]*ce[\s/]*nit\b|\bcc[\s/]*nit\b|\bnit[\s/]*cc\b", r_norm):
        return "nit"

    # 7. Identificación / Número de Identificación / Nro de Identificación -> 'cedula'
    if re.search(r"\bnumero\s+de\s+identificacion\b|\bnro\s+de\s+identificacion\b|\bno\s+de\s+identificacion\b|\bno\s+identificacion\b|\bidentificacion\s+no\b|\bidentificacion\b|\bdocumento\s+de\s+identidad\b", r_norm):
        if "nit" in r_norm or "tributaria" in r_norm:
            return "nit"
        return "cedula"

    # 8. En la sección del Representante Legal, teléfono / celular corresponde al móvil ('celular')
    if seccion_padre and any(k in seccion_padre.lower() for k in ("representante", "apoderado", "persona natural")):
        if re.search(r"\btel[eé]fono\b|\bcelular\b|\bmovil\b|\bcel\b|\bno\.?\s*celular\b", r_norm):
            return "celular"

    # 9. Búsqueda por sinónimos de coincidencia exacta o frase completa
    for campo, sinonimos in _SINONIMOS_RAPIDOS.items():
        if campo in campos_disponibles or campo in CAMPOS_VIRTUALES:
            for s in sinonimos:
                if s == r_norm:
                    return campo
                if len(s) >= 4 and re.search(r"\b" + re.escape(s) + r"\b", r_norm):
                    return campo

    # 10. Búsqueda difusa estricta con rapidfuzz (token_sort_ratio >= 88)
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

    if campo in ("ciudad_departamento", "ciudad/departamento", "ciudad_depto"):
        c = str(plano.get("ciudad", "")).strip()
        d = str(plano.get("departamento", "")).strip()
        if c and d:
            return f"{c}/{d}"
        return c or d

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
    
    claves_limpias = {k for k in plano.keys() if "." not in k and not isinstance(plano[k], dict)}
    claves = claves_limpias | set(CAMPOS_VIRTUALES)
    lista_ordenada = sorted(list(claves))
    return [OPCION_OMITIR] + lista_ordenada


def _formatear_badge_estado(
    estado_raw: str,
    confianza_raw: str,
    campo_select: str,
    motivo: str = "",
) -> str:
    """Convierte el estado y confianza técnicos en un badge visual intuitivo para el usuario."""
    if not campo_select or campo_select == OPCION_OMITIR:
        if estado_raw == "DESCARTADO":
            return "⚪ Omitido"
        return "⚪ Sin asignar"

    estado_upper = str(estado_raw or "").upper()
    confianza_upper = str(confianza_raw or "").upper()

    if estado_upper == "APROBADO":
        if confianza_upper == "EXACTA":
            return "🟢 Exacta"
        if "autocorr" in motivo.lower() or "corregido" in motivo.lower():
            return "🟢 Alta (Autocorr.)"
        if confianza_upper == "ALTA":
            return "🟢 Alta"
        if confianza_upper == "PARCIAL":
            return "🟡 Parcial"
        return "🟢 Aprobado"

    if estado_upper == "REVISION":
        return "🟡 Requiere Revisión"

    if estado_upper == "DESCARTADO":
        return "⚪ Omitido"

    return "✅ Sugerido por IA"


def preparar_tabla_verificacion(
    plan_mapeo: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
    elementos_raw: Optional[List[Dict[str, Any]]] = None,
) -> pd.DataFrame:
    """Transforma el plan de mapeo enriquecido en un DataFrame interactivo con soporte de jerarquía y validación."""
    from pipeline.stages.stage_2_classifier import clasificar_rotulo_individual, ClasificacionElemento

    from core.profile_manager import aplanar_perfil
    plano = aplanar_perfil(datos_empresa)
    claves_disponibles = set(plano.keys()) | set(CAMPOS_VIRTUALES)
    
    filas: List[Dict[str, Any]] = []
    # Índice de celdas ya presentes en plan_mapeo
    coordenadas_mapeadas: Set[Tuple[str, int, int]] = set()

    # 1. Agregar primero los campos mapeados (enriquecidos por Fase 2 y 3)
    for idx, item in enumerate(plan_mapeo):
        hoja = str(item.get("hoja", ""))
        fila = int(item.get("fila", 0) or 0)
        col = int(item.get("columna", 0) or 0)
        rotulo = str(item.get("valor") or item.get("rotulo") or "").strip()
        campo = str(item.get("campo", "")).strip()
        seccion = str(item.get("seccion") or item.get("seccion_padre") or "INFORMACIÓN GENERAL").strip()
        
        estado_raw = str(item.get("estado", "APROBADO")).strip()
        confianza_raw = str(item.get("nivel_confianza", "ALTA")).strip()
        motivo = str(item.get("motivo", "")).strip()
        tipo_elem = str(item.get("tipo_elemento", "FIELD")).strip()

        ubicacion = str(item.get("ubicacion", "derecha")).lower()
        if ubicacion not in ("derecha", "abajo", "misma"):
            ubicacion = "derecha"

        campo_select = campo if (campo and (campo in claves_disponibles or campo in datos_empresa or "." in campo)) else OPCION_OMITIR
        valor_real = _resolver_valor_campo(datos_empresa, campo_select)
        
        # Badge visual
        badge = _formatear_badge_estado(estado_raw, confianza_raw, campo_select, motivo)

        # Motivo legible para el usuario
        motivo_display = motivo
        if not motivo_display:
            if badge == "🟢 Exacta":
                motivo_display = "Coincidencia directa con datos maestros"
            elif badge.startswith("🟢"):
                motivo_display = "Emparejamiento contextual validado"

        filas.append({
            "N°": idx + 1,
            "Sección": seccion,
            "Rótulo en el Formulario": rotulo,
            "Ubicación": f"{hoja} (F{fila}:C{col})" if hoja else f"Fila {fila}, Col {col}",
            "Confianza / Estado": badge,
            "Campo Asignado": campo_select,
            "Valor a Escribir": valor_real,
            "Motivo / Observación": motivo_display,
            "Dirección": ubicacion,
            "_hoja": hoja,
            "_fila": fila,
            "_columna": col,
            "_requiereMerge": bool(item.get("requiereMerge", False)),
            "_celdasAMergear": int(item.get("celdasAMergear", 1) or 1),
            "_anchoLinea": int(item.get("anchoLinea", 1) or 1),
            "_orig_idx": idx,
            "_seccion": seccion,
            "_tipo_elemento": tipo_elem,
            "_estado_raw": estado_raw,
            "_confianza_raw": confianza_raw,
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
            sec_e = str(elem.get("seccion_padre") or elem.get("seccion") or "INFORMACIÓN GENERAL").strip()

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
                ClasificacionElemento.TITULO_SECCION.value,
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
                badge = "⚫ No es un campo"
                motivo_desc = f"Descartado: clasificado como {tipo_clasif}"

            elif r_norm in ("identificacion", "id", "documento", "identificacion no", "no identificacion") and not elem.get("seccion_padre"):
                campo_final = OPCION_OMITIR
                valor_final = ""
                badge = "🟡 Requiere Revisión"
                motivo_desc = "Rótulo ambiguo sin sección específica asignada"

            else:
                sugerido = _sugerir_campo_para_rotulo(rot_e, claves_disponibles, seccion_padre=sec_e)
                if sugerido:
                    campo_final = sugerido
                    valor_final = _resolver_valor_campo(datos_empresa, campo_final)
                    badge = "🟡 Coincidencia parcial"
                    motivo_desc = "Sugerencia por similitud léxica"
                else:
                    campo_final = OPCION_OMITIR
                    valor_final = ""
                    badge = "⚪ Sin asignar"
                    motivo_desc = "No se encontró dato correspondiente en el perfil"

            ancho_l = int(elem.get("anchoLinea", 1) or 1)
            ubic = str(elem.get("tipoEspacioEscritura", "derecha")).lower()
            if ubic not in ("derecha", "abajo", "misma", "arriba"):
                ubic = "derecha"

            fila_dict = {
                "N°": n_extra,
                "Sección": sec_e,
                "Rótulo en el Formulario": rot_e,
                "Ubicación": f"{hoja_e} (F{fila_e}:C{col_e})" if hoja_e else f"Fila {fila_e}, Col {col_e}",
                "Confianza / Estado": badge,
                "Campo Asignado": campo_final,
                "Valor a Escribir": valor_final,
                "Motivo / Observación": motivo_desc,
                "Dirección": ubic,
                "_hoja": hoja_e,
                "_fila": fila_e,
                "_columna": col_e,
                "_requiereMerge": bool(ancho_l > 1),
                "_celdasAMergear": ancho_l,
                "_anchoLinea": ancho_l,
                "_orig_idx": None,
                "_seccion": sec_e,
                "_tipo_elemento": tipo_clasif,
                "_estado_raw": "EXTRA",
                "_confianza_raw": "SIN_COINCIDENCIA",
            }
            # Preservar metadatos físicos de PDF si existen
            for k in ("_pdf_page", "_pdf_bbox", "_pdf_target_rect", "_pdf_es_caja", "_pdf_es_casilla", "_pdf_es_acroform", "_pdf_widget_name"):
                if k in elem:
                    fila_dict[k] = elem[k]
            filas.append(fila_dict)
            coordenadas_mapeadas.add((hoja_e, fila_e, col_e))
            n_extra += 1

    df = pd.DataFrame(filas)
    if not df.empty:
        df["N°"] = df["N°"].fillna(0).astype(int)
        df["Sección"] = df["Sección"].fillna("INFORMACIÓN GENERAL").astype(str)
        df["Rótulo en el Formulario"] = df["Rótulo en el Formulario"].fillna("").astype(str)
        df["Ubicación"] = df["Ubicación"].fillna("").astype(str)
        df["Confianza / Estado"] = df["Confianza / Estado"].fillna("⚪ Sin asignar").astype(str)
        df["Campo Asignado"] = df["Campo Asignado"].fillna(OPCION_OMITIR).astype(str)
        df["Valor a Escribir"] = df["Valor a Escribir"].fillna("").astype(str)
        df["Motivo / Observación"] = df["Motivo / Observación"].fillna("").astype(str)
        df["Dirección"] = df["Dirección"].fillna("derecha").astype(str)
        df["_hoja"] = df["_hoja"].fillna("").astype(str)
        df["_fila"] = df["_fila"].fillna(0).astype(int)
        df["_columna"] = df["_columna"].fillna(0).astype(int)
        df["_requiereMerge"] = df["_requiereMerge"].fillna(False).astype(bool)
        df["_celdasAMergear"] = df["_celdasAMergear"].fillna(1).astype(int)
        df["_anchoLinea"] = df["_anchoLinea"].fillna(1).astype(int)
        df["_orig_idx"] = df["_orig_idx"].fillna(-1).astype(int)
        df["_seccion"] = df["_seccion"].fillna("").astype(str)
        df["_tipo_elemento"] = df["_tipo_elemento"].fillna("FIELD").astype(str)
        df["_estado_raw"] = df["_estado_raw"].fillna("").astype(str)
        df["_confianza_raw"] = df["_confianza_raw"].fillna("").astype(str)
        for k in ("_pdf_page", "_pdf_bbox", "_pdf_target_rect", "_pdf_es_caja", "_pdf_es_casilla", "_pdf_es_acroform", "_pdf_widget_name"):
            if k in df.columns:
                df[k] = df[k].apply(lambda v: json.dumps(v) if isinstance(v, (list, tuple, dict)) else ("" if v is None else str(v)))
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
        seccion = str(row.get("Sección", row.get("_seccion", "")))

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
            "seccion": seccion,
        }

        # Preservar metadatos físicos de PDF si existían
        orig_idx = row.get("_orig_idx")
        if orig_idx is not None and not pd.isna(orig_idx) and int(orig_idx) >= 0:
            idx_int = int(orig_idx)
            if 0 <= idx_int < len(plan_original):
                orig_item = plan_original[idx_int]
                for k in ("_pdf_page", "_pdf_bbox", "_pdf_target_rect", "_pdf_es_caja", "_pdf_es_casilla", "_pdf_es_acroform", "_pdf_widget_name"):
                    if k in orig_item:
                        item_final[k] = orig_item[k]
        else:
            for k in ("_pdf_page", "_pdf_bbox", "_pdf_target_rect", "_pdf_es_caja", "_pdf_es_casilla", "_pdf_es_acroform", "_pdf_widget_name"):
                if k in row and not pd.isna(row.get(k)):
                    item_final[k] = row[k]

        plan_resultado.append(item_final)

    return plan_resultado


def render_pantalla_verificacion(
    ctx: PipelineContext,
    key_prefix: str = "verif_ui",
) -> Tuple[bool, List[Dict[str, Any]]]:
    """Renderiza la interfaz de verificación visual interactiva enriquecida con HSP en Streamlit."""
    plan_activo = ctx.obtener_plan_activo()
    elementos_todos = ctx.elementos_clasificados if ctx.elementos_clasificados else ctx.elementos_raw

    if not plan_activo and not elementos_todos:
        st.warning("⚠️ No se encontraron campos detectados para verificar en este formulario.")
        return False, []

    opciones_campos = obtener_opciones_campos_empresa(ctx.datos_empresa)

    st.markdown("### 📋 Verificación y Auditoría Semántica de Campos")
    st.markdown(
        "Revisa y confirma la asignación de datos para cada campo detectado. "
        "El sistema ha validado la jerarquía de secciones y la coherencia lógica de los datos maestros."
    )

    # ── Gestión de Estado Maestro en Session State (Aislado por Documento) ──
    import hashlib
    doc_hash = hashlib.md5(f"{ctx.nombre_archivo}_{len(ctx.archivo_bytes or b'')}".encode("utf-8", errors="ignore")).hexdigest()[:10]
    master_key = f"{key_prefix}_master_df_{doc_hash}"
    editor_key = f"{key_prefix}_data_editor_{doc_hash}"

    if master_key not in st.session_state or st.session_state[master_key] is None:
        st.session_state[master_key] = preparar_tabla_verificacion(plan_activo, ctx.datos_empresa, elementos_todos)

    master_df: pd.DataFrame = st.session_state[master_key]

    # Conteo de métricas cuantitativas
    total_detectados = len(master_df)
    total_asignados = sum(1 for c in master_df["Campo Asignado"] if c != OPCION_OMITIR)
    total_alta_confianza = sum(1 for _, r in master_df.iterrows() if str(r["Confianza / Estado"]).startswith("🟢") and r["Campo Asignado"] != OPCION_OMITIR)
    total_revision = sum(1 for _, r in master_df.iterrows() if str(r["Confianza / Estado"]).startswith("🟡") or (r["Campo Asignado"] == OPCION_OMITIR and str(r["Confianza / Estado"]) not in ("⚫ No es un campo", "⚪ Omitido")))
    total_editados = sum(1 for _, r in master_df.iterrows() if str(r["Confianza / Estado"]).startswith("✏️"))

    # ── Tarjetas Métricas Resumidas ──
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📄 Formulario", ctx.nombre_archivo or "Documento", help=f"Total elementos analizados: {total_detectados}")
    with col2:
        st.metric("🟢 Alta Confianza", f"{total_alta_confianza}", help="Campos validados y aprobados automáticamente")
    with col3:
        st.metric("🟡 Requieren Revisión", f"{total_revision}", help="Campos con sugerencia parcial o pendientes de asignar")
    with col4:
        st.metric("✏️ Asignados / Editados", f"{total_asignados}", delta=f"{total_editados} manuales" if total_editados > 0 else None)

    # ── Filtros y Búsqueda Avanzada ──
    col_search, col_sec_filter, col_filter = st.columns([2, 1.5, 1.5])
    
    with col_search:
        filtro_texto = st.text_input(
            "🔍 Buscar rótulo, sección o campo...",
            key=f"{key_prefix}_search_input_{doc_hash}",
            placeholder="Ej: Representante, Cuenta, NIT, Banco...",
        ).strip().lower()

    # Obtener lista única de secciones
    secciones_disponibles = sorted(list({str(s) for s in master_df["Sección"].dropna().unique() if str(s).strip()}))
    
    with col_sec_filter:
        filtro_seccion = st.selectbox(
            "Filtrar por Sección:",
            ["Todas las secciones"] + secciones_disponibles,
            key=f"{key_prefix}_sec_filter_{doc_hash}",
        )

    with col_filter:
        vista_filtro = st.selectbox(
            "Filtrar por Estado:",
            ["Todos", "🟢 Solo Alta Confianza", "🟡 Solo Requieren Revisión", "✏️ Solo Editados", "⚪ Sin Asignar", "⚫ Omitidos (No campo)"],
            key=f"{key_prefix}_vista_filter_{doc_hash}",
        )

    # Aplicar filtrado al DataFrame visual desde master_df
    df_filtrado = master_df.copy()
    
    if filtro_texto:
        df_filtrado = df_filtrado[
            df_filtrado["Rótulo en el Formulario"].astype(str).str.lower().str.contains(filtro_texto) |
            df_filtrado["Sección"].astype(str).str.lower().str.contains(filtro_texto) |
            df_filtrado["Campo Asignado"].astype(str).str.lower().str.contains(filtro_texto) |
            df_filtrado["Motivo / Observación"].astype(str).str.lower().str.contains(filtro_texto)
        ]

    if filtro_seccion != "Todas las secciones":
        df_filtrado = df_filtrado[df_filtrado["Sección"] == filtro_seccion]

    if vista_filtro == "🟢 Solo Alta Confianza":
        df_filtrado = df_filtrado[df_filtrado["Confianza / Estado"].astype(str).str.startswith("🟢")]
    elif vista_filtro == "🟡 Solo Requieren Revisión":
        df_filtrado = df_filtrado[
            df_filtrado["Confianza / Estado"].astype(str).str.startswith("🟡") |
            ((df_filtrado["Campo Asignado"] == OPCION_OMITIR) & (~df_filtrado["Confianza / Estado"].astype(str).isin(["⚫ No es un campo", "⚪ Omitido"])))
        ]
    elif vista_filtro == "✏️ Solo Editados":
        df_filtrado = df_filtrado[df_filtrado["Confianza / Estado"].astype(str).str.startswith("✏️")]
    elif vista_filtro == "⚪ Sin Asignar":
        df_filtrado = df_filtrado[df_filtrado["Campo Asignado"] == OPCION_OMITIR]
    elif vista_filtro == "⚫ Omitidos (No campo)":
        df_filtrado = df_filtrado[df_filtrado["Confianza / Estado"].astype(str).isin(["⚫ No es un campo", "⚪ Omitido"])]

    # Configuración de columnas interactivas para st.data_editor
    config_columnas = {
        "N°": st.column_config.NumberColumn("N°", width="small", disabled=True),
        "Sección": st.column_config.TextColumn("Sección / Bloque", width="medium", disabled=True),
        "Rótulo en el Formulario": st.column_config.TextColumn("Rótulo en Formulario", width="large", disabled=True),
        "Ubicación": st.column_config.TextColumn("Ubicación", width="small", disabled=True),
        "Confianza / Estado": st.column_config.TextColumn("Estado", width="medium", disabled=True),
        "Campo Asignado": st.column_config.SelectboxColumn(
            "Dato de la Empresa",
            help="Selecciona qué dato de tu perfil empresarial debe inyectarse aquí",
            width="large",
            options=opciones_campos,
            required=True,
        ),
        "Valor a Escribir": st.column_config.TextColumn("Valor a Escribir", width="large", disabled=True),
        "Motivo / Observación": st.column_config.TextColumn("Motivo / Auditoría", width="large", disabled=True),
        "Dirección": st.column_config.SelectboxColumn(
            "Dirección",
            help="Hacia dónde se inyectará el dato respecto al rótulo",
            width="small",
            options=["derecha", "abajo", "misma", "arriba"],
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
        "_seccion": None,
        "_tipo_elemento": None,
        "_estado_raw": None,
        "_confianza_raw": None,
        "_pdf_page": None,
        "_pdf_bbox": None,
        "_pdf_target_rect": None,
        "_pdf_es_caja": None,
        "_pdf_es_casilla": None,
        "_pdf_es_acroform": None,
        "_pdf_widget_name": None,
    }

    # Render del editor de datos de Streamlit
    df_editado = st.data_editor(
        df_filtrado,
        column_config=config_columnas,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        key=editor_key,
    )

    # ── Sincronizar ediciones del usuario hacia master_df ──
    hubo_cambios = False
    if df_editado is not None and not df_editado.empty:
        for _, edit_row in df_editado.iterrows():
            num_item = edit_row["N°"]
            match_idx = master_df[master_df["N°"] == num_item].index
            if not match_idx.empty:
                idx = match_idx[0]
                campo_nuevo = str(edit_row.get("Campo Asignado", "")).strip()
                dir_nueva = str(edit_row.get("Dirección", "derecha")).lower()
                
                campo_antiguo = str(master_df.at[idx, "Campo Asignado"]).strip()
                dir_antigua = str(master_df.at[idx, "Dirección"]).lower()

                if campo_nuevo != campo_antiguo or dir_nueva != dir_antigua:
                    hubo_cambios = True
                    master_df.at[idx, "Campo Asignado"] = campo_nuevo
                    master_df.at[idx, "Dirección"] = dir_nueva
                    if campo_nuevo and campo_nuevo != OPCION_OMITIR:
                        master_df.at[idx, "Valor a Escribir"] = _resolver_valor_campo(ctx.datos_empresa, campo_nuevo)
                        master_df.at[idx, "Confianza / Estado"] = "✏️ Asignado por Usuario"
                        master_df.at[idx, "Motivo / Observación"] = "Asignación manual del usuario"
                    else:
                        master_df.at[idx, "Valor a Escribir"] = ""
                        estado_prev = str(master_df.at[idx, "Confianza / Estado"])
                        if estado_prev != "⚫ No es un campo":
                            master_df.at[idx, "Confianza / Estado"] = "⚪ Sin asignar"
                            master_df.at[idx, "Motivo / Observación"] = "Omitido por el usuario"

        if hubo_cambios:
            st.session_state[master_key] = master_df

    plan_actualizado = aplicar_cambios_verificacion(master_df, plan_activo, ctx.datos_empresa)

    st.markdown("---")

    # ── Botonera de Acciones ──
    col_guardar, col_confirmar, col_reset = st.columns([1.5, 2, 1.2])

    with col_guardar:
        if st.button("💾 Guardar como Plantilla Permanente", key=f"{key_prefix}_btn_save", help="Guarda esta configuración para que futuros formularios iguales se llenen automáticamente."):
            plan_actualizado = aplicar_cambios_verificacion(master_df, plan_activo, ctx.datos_empresa)
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
            plan_actualizado = aplicar_cambios_verificacion(master_df, plan_activo, ctx.datos_empresa)
            ctx.plan_verificado = plan_actualizado
            ctx.log(f"Plan de mapeo verificado y confirmado por el usuario ({len(plan_actualizado)} campos).")
            return True, plan_actualizado

    with col_reset:
        if st.button("🔄 Restablecer", key=f"{key_prefix}_btn_reset", help="Restaura las sugerencias iniciales de la IA"):
            if master_key in st.session_state:
                del st.session_state[master_key]
            ctx.plan_verificado = []
            st.rerun()

    return False, plan_actualizado
