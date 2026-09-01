"""Motor de Cobertura y Exhaustividad Semántica (Coverage Engine).

Detecta sistemáticamente campos, rótulos y enunciados que hayan quedado sin asignar
(por truncamiento de LLM, cese a mitad de formulario o secciones repetidas) y los
empareja determinísticamente con el valor correspondiente de la empresa según el contexto
de la sección y la taxonomía empresarial, garantizando 0 campos válidos dejados en blanco.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from core.semantic_validator import (
    validar_item_mapeo,
    EstadoMapeo,
    _normalizar,
    _aplanar_datos_empresa,
)

# ──────────────────────────────────────────────────────────────────────────────
# 1. PATRONES DE DETECCIÓN Y DOMINIOS DE SECCIÓN
# ──────────────────────────────────────────────────────────────────────────────

PAT_SECCION_REP_LEGAL = re.compile(
    r"\b(?:representante|apoderado|gerente|persona\s+natural)\b",
    re.IGNORECASE,
)
PAT_SECCION_FINANCIERO = re.compile(
    r"\b(?:financier[ao]|bancari[ao]|cuenta|banco|pagos?|transferencia)\b",
    re.IGNORECASE,
)
PAT_SECCION_JUNTA_COMP = re.compile(
    r"\b(?:junta\s+directiva|composici[oó]n|accionistas?|socios?|beneficiarios?\s+finales?|administraci[oó]n)\b",
    re.IGNORECASE,
)
PAT_SECCION_EMPRESA = re.compile(
    r"\b(?:empresa|proponente|solicitante|proveedor|cliente|identificaci[oó]n|general|b[aá]sica|datos\s+generales)\b",
    re.IGNORECASE,
)

# Lista exhaustiva de tuplas: (patron_seccion, patron_rotulo, campo_empresa, direccion_fallback)
PATRONES_SWEEP: List[Tuple[re.Pattern, re.Pattern, str, str]] = [
    # ── Dominio 1: Representante Legal / Persona Natural ──
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:id|identificaci[oó]n|c\.?c\.?|cedula|n[uú]mero\s+id|no\.?\s*doc(?:umento)?|no\.?\s*de\s+identificaci[oó]n)\s*$", re.IGNORECASE),
        "cedula",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:nombre\s*/?\s*apellidos?|nombres?\s+y\s+apellidos?|nombre\s+completo|representante\s+legal|raz[oó]n\s+social\s+o\s+nombres\s+y\s+apellidos)\s*$", re.IGNORECASE),
        "representante_legal",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*nombres?\s*$", re.IGNORECASE),
        "representante_nombres",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*apellidos?\s*$", re.IGNORECASE),
        "representante_apellidos",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:tel[eé]fono|celular|m[oó]vil|tel[\s/]*cel|tel[eé]fono[\s/]*celular)\s*$", re.IGNORECASE),
        "celular",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:email|correo|correo\s+electr[oó]nico)\s*$", re.IGNORECASE),
        "correo",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:tipo\s+id|tipo\s+doc(?:umento)?|tipo\s+de\s+identificaci[oó]n(?:\s*\(.*?\))?)\s*$", re.IGNORECASE),
        "tipo_documento",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:lugar\s+(?:de\s+)?expedici[oó]n|ciudad\s+(?:de\s+)?expedici[oó]n|expedici[oó]n)\s*$", re.IGNORECASE),
        "lugar_expedicion",
        "derecha",
    ),

    # ── Dominio 2: Información Financiera y Bancaria ──
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*(?:banco|entidad\s+bancaria|nombre\s+(?:del\s+)?banco|instituci[oó]n|entidad\s+financiera)\s*$", re.IGNORECASE),
        "banco",
        "derecha",
    ),
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*(?:n[uú]mero\s+de\s+cuenta|no\.?\s*cuenta|cuenta\s+no\.?|n[uú]mero\s+cuenta|cuenta)\s*$", re.IGNORECASE),
        "numero_cuenta",
        "derecha",
    ),
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*(?:tipo\s+(?:de\s+)?cuenta)\s*$", re.IGNORECASE),
        "tipo_cuenta",
        "derecha",
    ),
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*sucursal(?:\s+bancaria)?\s*$", re.IGNORECASE),
        "sucursal",
        "derecha",
    ),

    # ── Dominio 3: Junta Directiva y Composición Accionaria (Tabla Vertical) ──
    (
        PAT_SECCION_JUNTA_COMP,
        re.compile(r"^\s*(?:nombre\s*/?\s*razon\s+social|nombres?\s+y\s+apellidos?|nombre\s+completo|accionista|socios?)\s*$", re.IGNORECASE),
        "representante_legal",
        "abajo",
    ),
    (
        PAT_SECCION_JUNTA_COMP,
        re.compile(r"^\s*nombres?\s*$", re.IGNORECASE),
        "representante_nombres",
        "abajo",
    ),
    (
        PAT_SECCION_JUNTA_COMP,
        re.compile(r"^\s*apellidos?\s*$", re.IGNORECASE),
        "representante_apellidos",
        "abajo",
    ),
    (
        PAT_SECCION_JUNTA_COMP,
        re.compile(r"^\s*(?:tipo\s+id|tipo\s+doc(?:umento)?)\s*$", re.IGNORECASE),
        "tipo_documento",
        "abajo",
    ),
    (
        PAT_SECCION_JUNTA_COMP,
        re.compile(r"^\s*(?:n[uú]mero|n[uú]mero\s+id|no\.?\s*id|id|c\.?c\.?|cedula)\s*$", re.IGNORECASE),
        "cedula",
        "abajo",
    ),

    # ── Dominio 4: Datos de la Empresa (General) ──
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*(?:raz[oó]n\s+social|nombre\s*/?\s*razon\s+social|nombre\s+o\s+raz[oó]n\s+social|nombre\s+comercial|nombre\s+de\s+la\s+empresa|denominaci[oó]n\s+social)\s*$", re.IGNORECASE),
        "razon_social",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*(?:nit(?:\s+o\s+cc)?|nit\s*/\s*tax\s*id|tax\s*id|cc\s*/\s*ce\s*/\s*pas\s*/\s*nit|rut|identificaci[oó]n\s+tributaria(?:\s+no\.?)?|nit\s+o\s+identificaci[oó]n\s+tributaria)\s*$", re.IGNORECASE),
        "nit",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*(?:direcci[oó]n(?:\s+principal|\s+domicilio\s+principal)?|domicilio(?:\s+principal)?|sede\s+principal)\s*$", re.IGNORECASE),
        "direccion",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*(?:ciudad|municipio)\s*$", re.IGNORECASE),
        "ciudad",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*departamento\s*$", re.IGNORECASE),
        "departamento",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*pa[ií]s\s*$", re.IGNORECASE),
        "pais",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*(?:ciudad\s*/\s*departamento|ciudad[\s-]+depto|municipio\s*/\s*departamento)\s*$", re.IGNORECASE),
        "ciudad_departamento",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*(?:tel[eé]fono(?:\s+pbx)?|pbx|tel[eé]fono\s+principal)\s*$", re.IGNORECASE),
        "telefono",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*(?:email|correo(?:\s+electr[oó]nico)?(?:\s+notificaciones)?(?:\s+institucional)?)\s*$", re.IGNORECASE),
        "correo",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*(?:p[aá]gina\s*web|sitio\s*web|web)\s*$", re.IGNORECASE),
        "pagina_web",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*(?:tipo\s+de\s+sociedad|tipo\s+sociedad)\s*$", re.IGNORECASE),
        "tipo_sociedad",
        "derecha",
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# 2. FUNCIÓN PRINCIPAL DE BARRIDO Y LLENADO EXHAUSTIVO
# ──────────────────────────────────────────────────────────────────────────────

def ejecutar_pase_cobertura_exhaustiva(
    plan_mapeo: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
    documento_ir: Optional[Any] = None,
    elementos_raw: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Escanea y asigna todos los campos válidos no cubiertos por el LLM.

    Args:
        plan_mapeo: Plan de mapeo inicial (proveniente de LLM o Template Store).
        datos_empresa: Perfil empresarial (jerárquico o plano).
        documento_ir: Árbol de representación espacial jerárquica (DocumentoIR).
        elementos_raw: Lista plana de elementos escaneados por el parser.

    Returns:
        Plan de mapeo enriquecido y completado al 100% de cobertura viable.
    """
    datos_planos = _aplanar_datos_empresa(datos_empresa)
    plan_resultado = list(plan_mapeo or [])

    # Registrar coordenadas de origen y destino ya ocupadas
    coords_origen_ocupadas: Set[Tuple[str, int, int]] = set()
    coords_destino_ocupadas: Set[Tuple[str, int, int]] = set()

    for item in plan_resultado:
        if item.get("estado") != EstadoMapeo.DESCARTADO:
            h = str(item.get("hoja", "Hoja1"))
            f = int(item.get("fila", 0))
            c = int(item.get("columna", 0))
            coords_origen_ocupadas.add((h, f, c))

            ubic = str(item.get("ubicacion", "derecha")).lower()
            if ubic == "abajo":
                coords_destino_ocupadas.add((h, f + 1, c))
            elif ubic == "misma":
                coords_destino_ocupadas.add((h, f, c))
            else:
                coords_destino_ocupadas.add((h, f, c + 1))

    # Recopilar candidatos no mapeados desde el IR o desde elementos_raw
    candidatos: List[Dict[str, Any]] = []

    if documento_ir is not None and hasattr(documento_ir, "secciones_procesables"):
        for seccion in documento_ir.secciones_procesables():
            sec_titulo = seccion.titulo or "INFORMACIÓN GENERAL"
            for fila in seccion.filas:
                for elem in fila.elementos:
                    coord = (seccion.hoja, elem.fila, elem.columna)
                    if coord in coords_origen_ocupadas:
                        continue
                    if elem.tipo_elemento.value in ("INSTRUCTION", "LEGAL_TEXT", "OPTION", "DECORATIVE"):
                        continue

                    candidatos.append({
                        "hoja": seccion.hoja,
                        "fila": elem.fila,
                        "columna": elem.columna,
                        "texto": elem.texto,
                        "seccion": sec_titulo,
                        "tipo_elemento": elem.tipo_elemento.value,
                        "direccion_sugerida": elem.direccion_escritura,
                        "ancho_linea": elem.ancho_linea,
                        "propiedades_raw": elem.propiedades_raw or {},
                    })
    elif elementos_raw:
        for elem in elementos_raw:
            h = str(elem.get("hoja", "Hoja1"))
            f = int(elem.get("fila", 0))
            c = int(elem.get("columna", 0))
            coord = (h, f, c)
            if coord in coords_origen_ocupadas:
                continue

            txt = str(elem.get("valor") or elem.get("rotulo") or "").strip()
            if not txt:
                continue

            sec_titulo = str(elem.get("seccion_padre") or "INFORMACIÓN GENERAL")
            candidatos.append({
                "hoja": h,
                "fila": f,
                "columna": c,
                "texto": txt,
                "seccion": sec_titulo,
                "tipo_elemento": "FIELD",
                "direccion_sugerida": str(elem.get("tipoEspacioEscritura", "derecha")),
                "ancho_linea": int(elem.get("anchoLinea", 1) or 1),
                "propiedades_raw": elem,
            })

    # Evaluar cada candidato contra los patrones de cobertura
    nuevos_mapeos: List[Dict[str, Any]] = []

    for cand in candidatos:
        txt = cand["texto"].strip()
        if not txt or len(txt) > 90:
            continue

        sec_titulo = cand["seccion"]
        h = cand["hoja"]
        f = cand["fila"]
        c = cand["columna"]
        coord_orig = (h, f, c)

        for pat_sec, pat_rot, campo_sug, dir_fallback in PATRONES_SWEEP:
            # 1. Comprobar pertinencia de sección y texto de rótulo
            aplica_sec = bool(pat_sec.search(sec_titulo)) or pat_sec == PAT_SECCION_EMPRESA
            if not aplica_sec:
                continue

            if not pat_rot.search(txt):
                continue

            # 2. Comprobar que el campo tenga valor no vacío en la empresa
            val_emp = datos_planos.get(campo_sug)
            if not val_emp or not str(val_emp).strip():
                continue

            # 3. Determinar ubicación espacial de escritura
            dir_espacial = cand["direccion_sugerida"]
            ubicacion = dir_espacial if dir_espacial in ("derecha", "abajo", "misma") else dir_fallback

            # Calcular celda destino física
            if ubicacion == "abajo":
                coord_dest = (h, f + 1, c)
            elif ubicacion == "misma":
                coord_dest = (h, f, c)
            else:
                coord_dest = (h, f, c + 1)

            # Evitar colisiones en destino
            if coord_dest in coords_destino_ocupadas:
                continue

            elem_raw = cand["propiedades_raw"]
            ancho_l = int(cand.get("ancho_linea", 1) or elem_raw.get("anchoLinea", 1) or 1)

            nuevo_item = {
                "hoja": h,
                "fila": f,
                "columna": c,
                "valor": txt,
                "ubicacion": ubicacion,
                "campo": campo_sug,
                "requiereMerge": bool(ancho_l > 1 and ubicacion == "derecha"),
                "celdasAMergear": ancho_l,
                "anchoLinea": ancho_l,
                "seccion": sec_titulo,
                "tipo_elemento": cand.get("tipo_elemento", "FIELD"),
            }

            # Preservar metadatos de PDF si existen
            for k in ("_pdf_page", "_pdf_bbox", "_pdf_target_rect", "_pdf_es_caja", "_pdf_es_casilla", "_pdf_es_acroform", "_pdf_widget_name"):
                if k in elem_raw:
                    nuevo_item[k] = elem_raw[k]

            # Validar con el Validador Determinístico
            item_validado = validar_item_mapeo(nuevo_item, datos_empresa, datos_planos=datos_planos)

            if item_validado.get("estado") == EstadoMapeo.APROBADO:
                nuevos_mapeos.append(item_validado)
                coords_origen_ocupadas.add(coord_orig)
                coords_destino_ocupadas.add(coord_dest)
                break

    if nuevos_mapeos:
        print(f"[AutoForm AI CoverageEngine] ✨ Pase de Cobertura: {len(nuevos_mapeos)} campos adicionales recuperados con éxito.")

    return plan_resultado + nuevos_mapeos
