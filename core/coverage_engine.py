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
from core.domain_constants import (
    es_seccion_o_campo_pep,
    ROTULOS_GENERICOS_BLOQUEADOS,
    PATRON_CONTACTO_COMERCIAL,
    CAMPOS_RESPONSABLE_COMERCIAL,
    limpiar_rotulo,
)

# ──────────────────────────────────────────────────────────────────────────────
# 1. PATRONES DE DETECCIÓN Y DOMINIOS DE SECCIÓN
# ──────────────────────────────────────────────────────────────────────────────

PAT_SECCION_REP_LEGAL = re.compile(
    r"\b(?:representante|apoderado|gerente|persona\s+natural|firmante|firma|declaraci[oó]n)\b",
    re.IGNORECASE,
)
PAT_SECCION_FINANCIERO = re.compile(
    r"\b(?:financier[ao]|bancari[ao]|cuenta|banco|pagos?|transferencia)\b",
    re.IGNORECASE,
)
PAT_SECCION_JUNTA_COMP = re.compile(
    r"\b(?:junta\s+directiva|composici[oó]n|accionistas?|socios?|administraci[oó]n)\b",
    re.IGNORECASE,
)
PAT_SECCION_CONTACTO_COMERCIAL = re.compile(
    r"\b(?:contacto|asesor|comercial|ejecutivo|operativo|responsable|diligenciado|verificacion|verificación)\b",
    re.IGNORECASE,
)
PAT_SECCION_EMPRESA = re.compile(
    r"\b(?:empresa|proponente|solicitante|proveedor|cliente|identificaci[oó]n|general|b[aá]sica|datos\s+generales)\b",
    re.IGNORECASE,
)

# Lista exhaustiva de tuplas: (patron_seccion, patron_rotulo, campo_empresa, direccion_fallback)
PATRONES_SWEEP: List[Tuple[re.Pattern, re.Pattern, str, str]] = [
    # ── Dominio 1: Representante Legal / Persona Natural / Firma ──
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:id|identificaci[oó]n|c\.?c\.?|cedula|n[uú]mero\s+id|no\.?\s*doc(?:umento)?|no\.?\s*de\s+identificaci[oó]n|identificado\s+con\s+(?:el\s+)?(?:documento|c[eé]dula|c\.?c\.?|doc)?(?:\s+de\s+identidad)?)\s*:?\s*$", re.IGNORECASE),
        "cedula",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:nombre\s*/?\s*apellidos?|nombres?\s+y\s+apellidos?|nombre\s+completo|representante\s+legal|raz[oó]n\s+social\s+o\s+nombres\s+y\s+apellidos|nombre|yo)\s*:?,?\s*$", re.IGNORECASE),
        "representante_legal",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:primer\s+nombre|1er\s+nombre|1°\s*nombre|primer\s+nombre\s+del\s+representante)\s*:?\s*$", re.IGNORECASE),
        "primer_nombre",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:segundo\s+nombre|2do\s+nombre|2°\s*nombre|segundo\s+nombre\s+del\s+representante|otros?\s+nombres?)\s*:?\s*$", re.IGNORECASE),
        "segundo_nombre",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:primer\s+apellido|1er\s+apellido|1°\s*apellido|primer\s+apellido\s+del\s+representante)\s*:?\s*$", re.IGNORECASE),
        "primer_apellido",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:segundo\s+apellido|2do\s+apellido|2°\s*apellido|segundo\s+apellido\s+del\s+representante)\s*:?\s*$", re.IGNORECASE),
        "segundo_apellido",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*nombres?\s*:?\s*$", re.IGNORECASE),
        "representante_nombres",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*apellidos?\s*:?\s*$", re.IGNORECASE),
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
        re.compile(r"^\s*(?:lugar\s+(?:de\s+)?expedici[oó]n|ciudad\s+(?:de\s+)?expedici[oó]n|expedici[oó]n|expedid[ao]\s+en)\s*:?\s*$", re.IGNORECASE),
        "lugar_expedicion",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:lugar\s+(?:de\s+)?nacimiento|ciudad\s+(?:de\s+)?nacimiento|municipio\s+(?:de\s+)?nacimiento|nacido\s+en|nacimiento)\s*:?\s*$", re.IGNORECASE),
        "lugar_nacimiento",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:ciudad\s+(?:de\s+)?residencia|municipio\s+(?:de\s+)?residencia|ciudad\s+(?:de\s+)?domicilio|lugar\s+(?:de\s+)?residencia|domicilio\s+(?:del\s+)?representante|ciudad\s+residencia|municipio\s+residencia|residencia)\s*:?\s*$", re.IGNORECASE),
        "ciudad_residencia",
        "derecha",
    ),
    (
        PAT_SECCION_REP_LEGAL,
        re.compile(r"^\s*(?:departamento\s+(?:de\s+)?residencia|depto\s+(?:de\s+)?residencia|departamento\s+residencia)\s*:?\s*$", re.IGNORECASE),
        "departamento_residencia",
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
    # ── Dominio 2b: Cifras de Balance y Estados Financieros (ADR-0006) ──
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*(?:total\s+activos?|activos?\s+totales|activos?)\s*$", re.IGNORECASE),
        "total_activos",
        "derecha",
    ),
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*(?:total\s+pasivos?|pasivos?\s+totales|pasivos?)\s*$", re.IGNORECASE),
        "total_pasivos",
        "derecha",
    ),
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*(?:total\s+patrimonio|patrimonio(?:\s+neto|\s+l[ií]quido|\s+total)?|capital\s+social)\s*$", re.IGNORECASE),
        "total_patrimonio",
        "derecha",
    ),
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*(?:total\s+ingresos\s+mensuales|ingresos\s+mensuales|ingresos\s+operacionales\s+mensuales|ingresos\s+promedio\s+mensual(?:es)?)\s*$", re.IGNORECASE),
        "total_ingresos_mensuales",
        "derecha",
    ),
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*(?:total\s+egresos\s+mensuales|egresos\s+mensuales|gastos\s+mensuales|total\s+gastos\s+mensuales)\s*$", re.IGNORECASE),
        "total_egresos_mensuales",
        "derecha",
    ),
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*(?:total\s+ingresos\s+anuales|ingresos\s+anuales|ventas\s+anuales)\s*$", re.IGNORECASE),
        "total_ingresos_anuales",
        "derecha",
    ),
    (
        PAT_SECCION_FINANCIERO,
        re.compile(r"^\s*(?:total\s+egresos\s+anuales|egresos\s+anuales|gastos\s+anuales)\s*$", re.IGNORECASE),
        "total_egresos_anuales",
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
        re.compile(r"^\s*(?:c\.?c\.?|c[eé]dula|c\.?c\.?\s*:?)\s*$", re.IGNORECASE),
        "cedula",
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
        re.compile(r"^\s*(?:ciudad|municipio|ciudad\s*/\s*municipio|municipio\s*/\s*ciudad)\s*$", re.IGNORECASE),
        "ciudad",
        "derecha",
    ),
    (
        PAT_SECCION_EMPRESA,
        re.compile(r"^\s*(?:departamento|depto)\s*$", re.IGNORECASE),
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
        re.compile(r"^\s*(?:ciudad\s*/\s*departamento|ciudad[\s-]+depto|municipio\s*/\s*departamento|departamento\s*/\s*ciudad|departamento\s*/\s*municipio)\s*$", re.IGNORECASE),
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

    # ── Dominio 5: Contacto Comercial / Responsable del Diligenciamiento (ADR-0007 / ADR-0009) ──
    (
        PAT_SECCION_CONTACTO_COMERCIAL,
        re.compile(r"^\s*(?:nombre\s*(?:del?\s*)?(?:contacto|asesor|comercial|responsable|funcionario)|asesor\s+comercial|contacto\s+comercial|diligenciado\s+por|persona\s+de\s+contacto|nombre\s+completo|nombres?\s+y\s+apellidos?|nombre)\s*$", re.IGNORECASE),
        "responsable_nombre",
        "derecha",
    ),
    (
        PAT_SECCION_CONTACTO_COMERCIAL,
        re.compile(r"^\s*(?:cargo|posici[oó]n|rol)(?:\s*(?:del?\s*)?(?:contacto|asesor|comercial|responsable))?\s*$", re.IGNORECASE),
        "responsable_cargo",
        "derecha",
    ),
    (
        PAT_SECCION_CONTACTO_COMERCIAL,
        re.compile(r"^\s*(?:c[eé]dula|c\.?c\.?|identificaci[oó]n|documento|no\.?\s*doc(?:umento)?)(?:\s*(?:del?\s*)?(?:contacto|asesor|comercial|responsable))?\s*$", re.IGNORECASE),
        "responsable_cedula",
        "derecha",
    ),
    (
        PAT_SECCION_CONTACTO_COMERCIAL,
        re.compile(r"^\s*(?:tel[eé]fono|celular|m[oó]vil|tel[\s/]*cel|tel)(?:\s*(?:del?\s*)?(?:contacto|asesor|comercial|responsable))?\s*$", re.IGNORECASE),
        "responsable_telefono",
        "derecha",
    ),
    (
        PAT_SECCION_CONTACTO_COMERCIAL,
        re.compile(r"^\s*(?:email|e-mail|correo|correo\s+electr[oó]nico)(?:\s*(?:del?\s*)?(?:contacto|asesor|comercial|responsable))?\s*$", re.IGNORECASE),
        "responsable_correo",
        "derecha",
    ),
    (
        PAT_SECCION_CONTACTO_COMERCIAL,
        re.compile(r"^\s*(?:direcci[oó]n(?:\s+de\s+contacto|\s+comercial|\s+oficina)?|domicilio)\s*$", re.IGNORECASE),
        "responsable_direccion",
        "derecha",
    ),
    (
        PAT_SECCION_CONTACTO_COMERCIAL,
        re.compile(r"^\s*(?:ciudad|municipio)(?:\s+de\s+contacto|\s+comercial)?\s*$", re.IGNORECASE),
        "responsable_ciudad",
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

    # Bloquear filas que contengan o estén bajo preguntas/bloques de PEP o Beneficiario Final (ADR-0005)
    filas_bloqueadas_pep: Set[Tuple[str, int]] = set()
    if documento_ir is not None and hasattr(documento_ir, "secciones"):
        for sec in documento_ir.secciones:
            if es_seccion_o_campo_pep(sec.titulo):
                for f_num in range(sec.fila_inicio, sec.fila_fin + 1):
                    filas_bloqueadas_pep.add((sec.hoja, f_num))
            for fila in sec.filas:
                for elem in fila.elementos:
                    if es_seccion_o_campo_pep("", elem.texto):
                        for off in range(0, 8):
                            filas_bloqueadas_pep.add((sec.hoja, fila.numero_fila + off))
    elif elementos_raw:
        for elem in elementos_raw:
            txt_e = str(elem.get("valor") or elem.get("rotulo") or "")
            if es_seccion_o_campo_pep("", txt_e):
                h_e = str(elem.get("hoja", "Hoja1"))
                f_e = int(elem.get("fila", 0))
                for off in range(0, 8):
                    filas_bloqueadas_pep.add((h_e, f_e + off))

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
        # Safe Passivity (ADR-0005): Descartar totalmente secciones, filas o campos de PEP / Beneficiario Final
        if (cand["hoja"], cand["fila"]) in filas_bloqueadas_pep:
            continue
        if es_seccion_o_campo_pep(sec_titulo, txt):
            continue

        # Safe Passivity & Operadores (ADR-0004 / ADR-0007): Descartar rótulos genéricos o contacto sin operador
        txt_limpio = limpiar_rotulo(txt)
        if txt_limpio in ROTULOS_GENERICOS_BLOQUEADOS:
            continue
        tiene_datos_op = bool(datos_planos.get("responsable_nombre") or datos_planos.get("responsable_correo"))
        es_rot_contacto = bool(PATRON_CONTACTO_COMERCIAL.search(txt) or PAT_SECCION_CONTACTO_COMERCIAL.search(sec_titulo))
        if es_rot_contacto and not tiene_datos_op:
            continue

        h = cand["hoja"]
        f = cand["fila"]
        c = cand["columna"]
        coord_orig = (h, f, c)

        for pat_sec, pat_rot, campo_sug, dir_fallback in PATRONES_SWEEP:
            # Domain Isolation (ADR-0007): campos de responsable comercial SOLO aplican a contacto comercial
            es_campo_resp = campo_sug in CAMPOS_RESPONSABLE_COMERCIAL
            if es_campo_resp and not es_rot_contacto:
                continue
            if not es_campo_resp and es_rot_contacto:
                continue

            # 1. Comprobar pertinencia de sección y texto de rótulo
            aplica_sec = bool(pat_sec.search(sec_titulo)) or (pat_sec == PAT_SECCION_EMPRESA and not es_rot_contacto)
            if not aplica_sec:
                continue

            if not pat_rot.search(txt):
                continue

            # Unicidad de Sección (ADR-0005): Si el campo ya fue asignado en esta sección, no duplicar
            campos_en_seccion = {
                m.get("campo") for m in plan_resultado + nuevos_mapeos
                if (m.get("seccion") == sec_titulo or m.get("seccion_padre") == sec_titulo)
                and m.get("estado") != EstadoMapeo.DESCARTADO
            }
            if campo_sug in campos_en_seccion:
                continue

            # 2. Comprobar que el campo tenga valor no vacío en la empresa
            val_emp = datos_planos.get(campo_sug)
            if not val_emp or not str(val_emp).strip():
                continue

            # 3. Determinar ubicación espacial de escritura
            dir_espacial = cand["direccion_sugerida"]
            elem_raw = cand.get("propiedades_raw") or {}
            der_vacia = bool(elem_raw.get("derechaVacia", False))
            ab_vacia = bool(elem_raw.get("abajoVacia", False))

            if dir_fallback == "abajo" or (not der_vacia and ab_vacia) or pat_sec == PAT_SECCION_JUNTA_COMP:
                ubicacion = "abajo"
            else:
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
        print(f"[AutoForm AI CoverageEngine] [*] Pase de Cobertura: {len(nuevos_mapeos)} campos adicionales recuperados con exito.")

    return plan_resultado + nuevos_mapeos
