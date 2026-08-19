"""Orquestador de la Fase 2 y Fase 3 de AutoForm AI.

Recibe el mapa visual del formulario, genera el plan de mapeo y extiende el plan
para permitir la escritura física nativa en Excel.

Cambios v2:
  - Fix: import Tuple desde typing (corrige NameError en _calcular_celda_destino).
  - Fix: _filtrar_datos_empresa ahora usa modo PERMISIVO como fallback para evitar
    descartar campos legítimos por sinónimos no previstos.
  - Nuevo: _generar_reporte_cobertura() emite un log estructurado de qué campo
    se mapeó, cuál fue excluido en el filtro, y cuál el LLM no asignó.
  - Nuevo: _enriquecer_con_ancholinea() copia anchoLinea desde el mapa original
    hacia cada ítem del plan de mapeo, necesario para que el writer combine
    líneas de captura correctamente.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple   # ← FIX: Tuple estaba ausente

from core import semantic_cache
from core.llm_client import invocar_llm, STRICT_SYSTEM_PROMPT
from core.excel_parser import _calcular_ubicacion_fisica



# ---------------------------------------------------------------------------
# Claves físicas PDF que el relleno/validación necesitan (página, rect exacto,
# cajas, widgets). Deben propagarse del mapa original al plan de mapeo final.
# ---------------------------------------------------------------------------
_CLAVES_PDF = (
    "_pdf_page",
    "_pdf_bbox",
    "_pdf_target_rect",
    "_pdf_es_caja",
    "_pdf_es_casilla",
    "_pdf_es_acroform",
    "_pdf_widget_name",
    "_pdf_es_vision",
)


# ---------------------------------------------------------------------------
# Claves del parser que necesita la IA para decidir semánticamente la
# ubicación. Los demás campos son internos y sólo aumentan tokens.
# ---------------------------------------------------------------------------
_CLAVES_LLM = {
    "hoja", "fila", "columna", "valor",
    "tipoEspacioEscritura", "anchoLinea", "anchoMergeVecino",
    "derechaVacia", "abajoVacia", "derechaEsMerge", "esMergePrincipal",
    "esCasillaVerificacion",
}

_CAMPOS_VIRTUALES = {"nit_sin_dv", "nit_dv"}


# ---------------------------------------------------------------------------
# LLM-04: Caché en memoria por hash del mapa de formularios
# ---------------------------------------------------------------------------
_cache_mapeos: Dict[str, List[Dict[str, Any]]] = {}
_cache_debug: Dict[str, Dict[str, Any]] = {}


def _hash_mapa(mapa_purgado: List[Dict[str, Any]]) -> str:
    """Genera un hash SHA-256 determinísta del mapa purgado."""
    contenido = json.dumps(mapa_purgado, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()


def get_debug_info(hash_form: str) -> Optional[Dict[str, Any]]:
    """Retorna la información de debug almacenada para el hash dado."""
    return _cache_debug.get(hash_form)


_PATRON_DOCUMENTOS_ANEXAR = re.compile(
    r"^\s*(?:\d+[\.)\-]\s*)?(?:copia|adjuntar|fotocopia|anexo|certificado|certificaci[oó]n|documentos?\s+a\s+(?:presentar|adjuntar)|requisitos?|rut|c[aá]mara\s+de\s+comercio|declaraci[oó]n|antecedentes)\b",
    re.IGNORECASE
)


# FIX-4 (módulo): Términos que identifican campos de formulario reales (no títulos de sección)
_TERMINOS_CAMPO_REAL_TITULO = re.compile(
    r"\b(nit|rut|c\.?c\.?|c\.?e\.?|cedula|raz[oó]n\s+social|nombre|tel[eé]fono|celular|direcci[oó]n|"
    r"correo|email|ciudad|municipio|departamento|pa[ií]s|cargo|firma|banco|cuenta|"
    r"representante|p[aá]gina|web|objeto|actividad|expedici[oó]n|matr[ií]cula|"
    r"sucursal|dv|d[ií]gito|establecimiento|domicilio|sede)\b",
    re.IGNORECASE
)


def _es_titulo_seccion(texto: str) -> bool:
    """Determina si un rótulo es un título decorativo de sección y no un campo de entrada."""
    t_clean = texto.strip()
    if not t_clean:
        return False

    # Rótulos que terminan en dos puntos son indicaciones directas de entrada
    if t_clean.endswith(":"):
        return False

    # FIX-4: Rótulos con número+término corto de campo conocido NO son títulos decorativos.
    # Ejemplo: "1. NIT:", "2. Razón social:", "3. Teléfono:" — son campos reales del formulario.
    m_num = re.match(r"^\s*\d+[\.]\s+(.+)$", t_clean)
    if m_num:
        texto_tras_num = m_num.group(1).strip()
        # Si el texto tras el número es corto (≤5 palabras) y contiene un término de campo → NO es título
        if len(texto_tras_num.split()) <= 5 and _TERMINOS_CAMPO_REAL_TITULO.search(texto_tras_num):
            return False

    # 1. Empieza con número o número romano + punto/paréntesis + texto de título (ej. "3. REPRESENTANTE LEGAL (aplica para personas jurídicas)")
    if re.search(r"^\s*\d+[\.]\s*(?:REPRESENTANTE|DATOS|INFORMACI[OÓ]N|DOCUMENTACI[OÓ]N|PROPONENTE|OFERENTE|TITULO|SECCI[OÓ]N|BLOQUE|CAP[IÍ]TULO|NUMERAL|ANEXO)", t_clean, re.IGNORECASE):
        return True

    if re.search(r"^\s*\d+[\.]\s*[A-ZÁÉÍÓÚÑ\s\/\,\;\:\-\(\)\w]{4,}$", t_clean):
        if not re.search(r"_{2,}|\.{3,}|\[\s*\]|\(\s*\)", t_clean):
            # FIX-4: Si el texto completo es corto (≤ 4 palabras) o contiene término de campo → no es título
            palabras = [w for w in t_clean.split() if not re.match(r"^\d+[\.)]?$", w)]
            if len(palabras) <= 4 or _TERMINOS_CAMPO_REAL_TITULO.search(t_clean):
                return False
            return True

    if re.search(r"^\s*(?:I|II|III|IV|V|VI|VII|VIII|IX|X)+\.?\s+", t_clean, re.IGNORECASE):
        if not re.search(r"_{2,}|\.{3,}|\[\s*\]|\(\s*\)", t_clean):
            return True

    # 2. Enunciados en mayúsculas sostenidas que son títulos típicos de bloque (incluso con texto explicativo entre paréntesis)
    titulos_tipicos = [
        r"^\s*REPRESENTANTE\s+(?:LEGAL|JUR[IÍ]DICO)(?:\s*\(.*?\))?\s*$",
        r"^\s*DATOS\s+DE\s+LA\s+EMPRESA(?:\s*\(.*?\))?\s*$",
        r"^\s*DATOS\s+DEL\s+REPRESENTANTE\s+(?:LEGAL|JUR[IÍ]DICO)?(?:\s*\(.*?\))?\s*$",
        r"^\s*DATOS\s+GENERALES(?:\s*\(.*?\))?\s*$",
        r"^\s*INFORMACI[OÓ]N\s+GENERAL(?:\s*\(.*?\))?\s*$",
        r"^\s*INFORMACI[OÓ]N\s+B[AÁ]SICA(?:\s*\(.*?\))?\s*$",
        r"^\s*INFORMACI[OÓ]N\s+FINANCIERA(?:\s*\(.*?\))?\s*$",
        r"^\s*REFERENCIAS\s+BANCARIAS(?:\s*\(.*?\))?\s*$",
        r"^\s*DATOS\s+TRIBUTARIOS(?:\s*\(.*?\))?\s*$",
    ]
    for pat in titulos_tipicos:
        if re.match(pat, t_clean, re.IGNORECASE):
            return True

    # 3. Frases en mayúsculas de tipo "DATOS..."
    if re.match(r"^\s*(?:DATOS|INFORMACI[OÓ]N|DOCUMENTACI[OÓ]N)\s+(?:GENERALES|B[AÁ]SICOS|DE|DEL|DE\s+LA)\s+", t_clean, re.IGNORECASE):
        if not t_clean.endswith(":") and not re.search(r"_{2,}|\.{3,}", t_clean):
            return True

    return False



_PATRON_PREGUNTAS_CONDICIONALES = re.compile(
    r"^\s*(?:en\s+caso\s+(?:afirmativo|de)|si\s+la\s+respuesta\s+es|favor\s+indicar|conflicto\s+de\s+inter[eé]s)\b",
    re.IGNORECASE
)


_PATRON_CAMPOS_FIRMA = re.compile(
    r"^\s*(?:firma|firmas|signature)\b",
    re.IGNORECASE
)


_PATRON_SECCION_USO_EXCLUSIVO = re.compile(
    r"espacio\s+exclusivo|uso\s+exclusivo|uso\s+interno|espacio\s+reservado|reservado\s+para\s+la\s+empresa|verificaci[oó]n\s+de\s+informaci[oó]n\s*/\s*observaciones",
    re.IGNORECASE
)


def _obtener_rangos_uso_exclusivo(mapa: List[Dict[str, Any]]) -> Set[Tuple[str, int]]:
    """Identifica todas las coordenadas (hoja, fila) pertenecientes a secciones
    de 'USO EXCLUSIVO / USO INTERNO / ESPACIO RESERVADO PARA LA EMPRESA'.

    Estas secciones son para diligenciamiento interno por parte de auditores o líderes
    de proceso de la empresa receptora y NUNCA deben rellenarse con datos del proveedor.
    """
    celdas_exclusivas: Set[Tuple[str, int]] = set()

    cabeceras_exclusivas = []
    for elem in mapa:
        txt = str(elem.get("valor", "")).strip()
        if _PATRON_SECCION_USO_EXCLUSIVO.search(txt):
            cabeceras_exclusivas.append((str(elem.get("hoja", "")), int(elem.get("fila", 0))))

    if not cabeceras_exclusivas:
        return celdas_exclusivas

    for hoja_exc, fila_exc in cabeceras_exclusivas:
        fila_fin = fila_exc + 15
        for elem in mapa:
            if str(elem.get("hoja", "")) != hoja_exc:
                continue
            f = int(elem.get("fila", 0))
            if f > fila_exc:
                txt = str(elem.get("valor", "")).strip()
                if _es_titulo_seccion(txt) and not _PATRON_SECCION_USO_EXCLUSIVO.search(txt):
                    fila_fin = min(fila_fin, f - 1)
                    break

        for r in range(fila_exc, fila_fin + 1):
            celdas_exclusivas.add((hoja_exc, r))

    return celdas_exclusivas


def _purgar_mapa(mapa: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Genera una representación limpia y estructurada para el LLM con ID incremental explícito (1..N).

    Filtra automáticamente enunciados que correspondan a listas de requisitos o títulos decorativos.
    """
    purgado = []
    rangos_uso_exclusivo = _obtener_rangos_uso_exclusivo(mapa)

    for idx, entrada in enumerate(mapa):
        txt_rotulo = str(entrada.get("valor", "")).strip()
        hoja_elem = str(entrada.get("hoja", ""))
        fila_elem = int(entrada.get("fila", 0))

        # Omitir celdas dentro de secciones de USO EXCLUSIVO / USO INTERNO
        if (hoja_elem, fila_elem) in rangos_uso_exclusivo:
            print(f"[AutoForm AI Mapper Filter] Omitido campo de sección interna (USO EXCLUSIVO): '{txt_rotulo}' F{fila_elem}")
            continue

        # Omitir códigos de control de calidad/documental (ej. "Versión: 00", "Código: GE.F.021", "Página 1 de 2")
        if re.search(r"^\s*(?:versi[oó]n|c[oó]digo|p[aá]gina)\b", txt_rotulo, re.IGNORECASE):
            print(f"[AutoForm AI Mapper Filter] Omitido código de control documental: '{txt_rotulo}'")
            continue

        # Omitir recuadros de firma física/digital (no se inyectan textos en campos de firma)
        if _PATRON_CAMPOS_FIRMA.search(txt_rotulo):
            print(f"[AutoForm AI Mapper Filter] Omitido recuadro de firma física: '{txt_rotulo}'")
            continue

        # Omitir rótulos que sean instrucciones de anexos o listas de documentos a presentar
        if _PATRON_DOCUMENTOS_ANEXAR.search(txt_rotulo):
            continue
        if re.search(r"^\s*\d+[\.\)]\s*(?:copia\s+de|fotocopia\s+de|adjuntar|anexo|certificado|certificaci[oó]n)", txt_rotulo, re.IGNORECASE):
            continue

        # Omitir preguntas condicionales opcionales (ej. "En caso afirmativo favor indicar nombre...")
        if _PATRON_PREGUNTAS_CONDICIONALES.search(txt_rotulo):
            print(f"[AutoForm AI Mapper Filter] Omitida pregunta condicional opcional: '{txt_rotulo}'")
            continue

        # Omitir títulos decorativos de sección (ej. "3. DATOS DEL REPRESENTANTE LEGAL")
        if _es_titulo_seccion(txt_rotulo):
            print(f"[AutoForm AI Mapper Filter] Omitido título decorativo de sección: '{txt_rotulo}'")
            continue

        purgado.append({
            "id": idx + 1,
            "rotulo": txt_rotulo,
            "hoja": str(entrada.get("hoja", "")),
            "fila": entrada.get("fila"),
            "columna": entrada.get("columna"),
            "tipoEspacioEscritura": str(entrada.get("tipoEspacioEscritura", "derecha")).lower(),
            "anchoLinea": entrada.get("anchoLinea", 1),
        })
    return purgado





# ---------------------------------------------------------------------------
# FIX PRINCIPAL: _filtrar_datos_empresa con modo PERMISIVO como fallback
# ---------------------------------------------------------------------------

#: Sinónimos de cada campo canónico tal como pueden aparecer en formularios.
_INDICIOS: Dict[str, List[str]] = {
    "razon_social":              ["nombre", "razon", "empresa", "proveedor", "social", "denominacion", "entidad"],
    "nit":                       ["nit", "rut", "identificacion", "cc/ce/pas", "fiscal", "tributaria", "registro"],
    "cedula":                    ["cedula", "c.c", "documento", "identidad", "id", "dni", "pasaporte"],
    "direccion":                 ["direccion", "domicilio", "domicilo", "residencia", "ubicacion", "sede", "principal"],
    "ciudad":                    ["ciudad", "municipio", "localidad", "poblacion"],
    "departamento":              ["departamento", "dpto", "estado", "provincia", "region"],
    "telefono":                  ["telefono", "tel", "celular", "contacto", "fono", "movil", "fax"],
    "correo":                    ["correo", "email", "e-mail", "mail", "electronico"],
    "pagina_web":                ["web", "pagina", "url", "sitio", "portal", "http"],
    "representante_legal":       ["representante", "legal", "gerente", "director", "administrador", "apoderado"],
    "representante_nombres":     ["nombres", "primer nombre", "segundo nombre"],
    "representante_apellidos":   ["apellidos", "primer apellido", "segundo apellido"],
    "pais":                      ["pais", "nacionalidad", "origen", "country"],
    "banco":                     ["banco", "bancaria", "financiera", "entidad bancaria", "institucion"],
    "numero_cuenta":             ["cuenta", "nro cuenta", "no. cuenta", "numero cuenta", "n° cuenta"],
    "tipo_cuenta":               ["tipo cuenta", "tipo de cuenta", "modalidad", "clase cuenta"],
    "sucursal":                  ["sucursal", "agencia", "oficina bancaria"],
    # FIX-3: Campos frecuentes en formularios colombianos que antes carecían de indicios
    "objeto_social":             ["objeto social", "objeto", "actividad", "giro", "naturaleza", "razon de ser"],
    "actividad_economica":       ["actividad economica", "actividad principal", "ciiu", "codigo actividad", "giro negocio", "sector economico"],
    "tipo_identificacion":       ["tipo de documento", "tipo identificacion", "clase de documento", "tipo de id", "clase id", "tipo doc"],
    "expedicion":                ["expedicion", "expedida", "lugar de expedicion", "ciudad de expedicion", "expedida en"],
    "cargo_representante":       ["cargo", "calidad", "calidad en que actua", "en calidad de", "titulo cargo"],
    "fecha_expedicion":          ["fecha de expedicion", "fecha expedicion", "fecha doc"],
    "actividad_ciiu":            ["ciiu", "codigo ciiu", "clasificacion", "actividad economica"],
    "ciudad_correspondencia":    ["ciudad correspondencia", "ciudad para notificaciones", "ciudad notificacion"],
    "numero_matricula":          ["matricula mercantil", "matricula", "camara de comercio", "no matricula"],
    "fecha_constitucion":        ["fecha constitucion", "fecha de constitucion", "constituida", "fundada"],
    "tipo_empresa":              ["tipo de empresa", "tipo sociedad", "naturaleza juridica", "razon juridica"],
}


import unicodedata


def _quitar_acentos(texto: str) -> str:
    """Normaliza texto removiendo diacríticos y acentos (ej. PAÍS -> pais)."""
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or "").lower()) if unicodedata.category(c) != "Mn")


def _filtrar_datos_empresa(
    mapa_purgo: List[Dict[str, Any]],
    datos: Dict[str, Any],
    modo_permisivo: bool = False,
) -> Dict[str, Any]:
    """Devuelve los campos de DatosEmpresa relevantes para el formulario actual.

    Estrategia:
    1. Primer pase ESTRICTO: retener sólo campos cuyos sinónimos aparecen en el
       vocabulario de rótulos del formulario.
    2. Si el resultado estricto cubre < 50 % de las claves disponibles, activar
       modo PERMISIVO: devolver todos los campos (safe-fallback que garantiza
       que el LLM recibe la información completa y decide él qué usar).

    Args:
        mapa_purgo:    Lista de entradas purgadas del parser.
        datos:         Diccionario completo de datos de la empresa.
        modo_permisivo: Si True, fuerza devolución de todos los campos sin filtro.
    """
    if modo_permisivo:
        return dict(datos)

    vocabulario_norm = _quitar_acentos(" ".join(str(e.get("rotulo") or e.get("valor") or "").lower() for e in mapa_purgo))

    resultado: Dict[str, Any] = {}
    for campo, valor in datos.items():
        indicios = _INDICIOS.get(campo)
        if indicios is None:
            # Clave desconocida → incluir por seguridad
            resultado[campo] = valor
        elif any(_quitar_acentos(indicio) in vocabulario_norm for indicio in indicios):
            resultado[campo] = valor

    # ── FIX: Fallback permisivo si el filtro estricto dejó menos de la mitad ──
    total_campos = len(datos)
    campos_retenidos = len(resultado)
    if total_campos > 0 and campos_retenidos < max(1, total_campos // 2):
        print(
            f"[AutoForm AI] [WARNING] Filtro estricto retuvo solo {campos_retenidos}/{total_campos} campos. "
            f"Activando modo PERMISIVO para garantizar cobertura completa."
        )
        return dict(datos)

    return resultado


# ---------------------------------------------------------------------------
# Construcción del prompt
# ---------------------------------------------------------------------------

def construir_prompt(mapa_formularios: List[Dict[str, Any]], datos_empresa: Dict[str, Any]) -> str:
    """Construye el payload JSON compacto para el LLM."""
    mapa_purgado = _purgar_mapa(mapa_formularios)
    datos_filtrados = _filtrar_datos_empresa(mapa_purgado, datos_empresa)

    payload = {
        "F": mapa_purgado,
        "D": datos_filtrados,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Enriquecimiento: propagar anchoLinea desde el mapa original al plan de mapeo
# ---------------------------------------------------------------------------

def _enriquecer_con_ancholinea(
    plan_mapeo: List[Dict[str, Any]],
    mapa_formularios: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Copia anchoLinea y anchoMergeVecino desde el mapa original hacia cada
    ítem del plan de mapeo usando la clave (hoja, fila, columna) como índice.

    El writer usa anchoLinea para saber cuántas celdas contiguas combinar
    cuando rellena una línea de captura dividida (WRITER-03). Sin este paso,
    celdasAMergear siempre queda en 1 y el valor se escribe en una sola celda.
    """
    # Índice O(1): (hoja, fila, columna) → entrada del parser
    indice_mapa: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
    for entrada in mapa_formularios:
        clave = (
            str(entrada.get("hoja", "")),
            int(entrada.get("fila", 0) or 0),
            int(entrada.get("columna", 0) or 0),
        )
        indice_mapa[clave] = entrada

    enriquecidos: List[Dict[str, Any]] = []
    for item in plan_mapeo:
        clave = (
            str(item.get("hoja", "")),
            int(item.get("fila", 0) or 0),
            int(item.get("columna", 0) or 0),
        )
        entrada_original = indice_mapa.get(clave)
        item_enriquecido = dict(item)

        if entrada_original is not None:
            ancho_linea = int(entrada_original.get("anchoLinea", 1) or 1)
            ancho_merge = int(entrada_original.get("anchoMergeVecino", 1) or 1)

            # Propagar anchoLinea al plan de mapeo para que el writer lo use
            item_enriquecido["anchoLinea"] = ancho_linea

            # Si el LLM no calculó celdasAMergear correctamente, usar el valor
            # del parser que es más preciso (basado en escaneo visual real).
            celdas_llm = int(item.get("celdasAMergear", 1) or 1)
            if celdas_llm <= 1 and (ancho_linea > 1 or ancho_merge > 1):
                item_enriquecido["celdasAMergear"] = max(ancho_linea, ancho_merge)
                item_enriquecido["requiereMerge"] = True

        enriquecidos.append(item_enriquecido)

    return enriquecidos


# ---------------------------------------------------------------------------
# Reporte de cobertura estructurado
# ---------------------------------------------------------------------------

def _generar_reporte_cobertura(
    datos_empresa: Dict[str, Any],
    datos_filtrados: Dict[str, Any],
    plan_final: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Genera un reporte detallado con el estado de cada campo del perfil.

    Returns:
        Dict con listas: mapeados, excluidos_por_filtro, no_asignados_por_llm.
    """
    todos_campos = set(datos_empresa.keys()) | _CAMPOS_VIRTUALES
    en_filtrado = set(datos_filtrados.keys())
    asignados = {item["campo"] for item in plan_final if item.get("campo")}

    excluidos_por_filtro = sorted(todos_campos - en_filtrado - _CAMPOS_VIRTUALES)
    no_asignados_llm = sorted(en_filtrado - asignados)
    mapeados = sorted(asignados)

    reporte = {
        "total_campos_perfil": len(todos_campos),
        "campos_mapeados": mapeados,
        "excluidos_por_filtro": excluidos_por_filtro,
        "no_asignados_por_llm": no_asignados_llm,
        "cobertura_pct": round(len(mapeados) / max(len(en_filtrado), 1) * 100, 1),
    }

    # Log estructurado para diagnóstico
    print("\n" + "=" * 60)
    print("REPORTE DE COBERTURA AutoForm AI")
    print("=" * 60)
    print(f"  [OK] Mapeados ({len(mapeados)}):           {mapeados}")
    print(f"  [EXCLUDED] Excluidos por filtro ({len(excluidos_por_filtro)}): {excluidos_por_filtro}")
    print(f"  [UNASSIGNED] No asignados LLM ({len(no_asignados_llm)}):    {no_asignados_llm}")
    print(f"  [STATS] Cobertura: {reporte['cobertura_pct']}%")
    print("=" * 60 + "\n")

    return reporte


# ---------------------------------------------------------------------------
# Helpers de validación e inferencia
# ---------------------------------------------------------------------------

_CAMPOS_REQUIEREN_MERGE = {
    "razon_social", "direccion", "representante_legal",
    "representante_nombres", "representante_apellidos",
    "correo", "pagina_web", "objeto_social", "actividad_economica",
}

_PATRON_ETIQUETA_MERGE = re.compile(
    r"firma|\bdirecci[oó]n\b|\bdomicilio\b|\brazon\b|social|nombre\s+completo"
    r"|tel[eé]fono|correo|email|p[aá]gina\s*web|objeto|actividad",
    flags=re.IGNORECASE,
)


def _necesita_merge(etiqueta: str, campo: str) -> bool:
    if campo in _CAMPOS_REQUIEREN_MERGE:
        return True
    if _PATRON_ETIQUETA_MERGE.search(str(etiqueta or "")):
        return True
    if "_" in str(etiqueta or ""):
        return True
    return False


def _validar_item(item: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Cada elemento del resultado debe ser un objeto JSON.")

    campo = str(item.get("campo", "")).strip()
    if not campo:
        return {
            "hoja": str(item.get("hoja", "")),
            "fila": int(item.get("fila", 0) or 0),
            "columna": int(item.get("columna", 0) or 0),
            "valor": str(item.get("valor", "")),
            "ubicacion": "",
            "campo": "",
            "requiereMerge": False,
            "celdasAMergear": 1,
        }

    ubicacion = str(item.get("ubicacion", "")).lower().strip()
    if ubicacion not in {"derecha", "abajo", "misma"}:
        raise ValueError(
            f"Ubicación inválida: {ubicacion!r}. Solo se admite 'derecha', 'abajo' o 'misma'."
        )

    requiere_merge = bool(item.get("requiereMerge", False))
    celdas_a_mergear = int(item.get("celdasAMergear", 1) or 1)
    if celdas_a_mergear < 1:
        celdas_a_mergear = 1
    if requiere_merge and celdas_a_mergear == 1:
        celdas_a_mergear = 3

    return {
        "hoja": str(item.get("hoja", "")),
        "fila": int(item.get("fila", 0) or 0),
        "columna": int(item.get("columna", 0) or 0),
        "valor": str(item.get("valor", "")),
        "ubicacion": ubicacion,
        "campo": campo,
        "requiereMerge": requiere_merge,
        "celdasAMergear": celdas_a_mergear,
    }


def _extraer_json(texto: str) -> Any:
    """Extrae y parsea JSON de la respuesta del LLM (6 estrategias en cascada)."""
    texto_limpio = texto.strip()

    # 1. Parseo directo
    try:
        return json.loads(texto_limpio)
    except json.JSONDecodeError:
        pass

    # 2. Bloques markdown ```json ... ```
    bloque = re.search(r'```(?:json)?\s*(.*?)\s*```', texto, re.DOTALL | re.IGNORECASE)
    if bloque:
        try:
            return json.loads(bloque.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Primera '[' hasta última ']' o '{' hasta '}'
    for patron in (r'(\[.*\])', r'(\{.*\})'):
        m = re.search(patron, texto, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

    # 4. Búsqueda inversa desde el último '[' (para modelos de razonamiento)
    ultimo_corchete = texto_limpio.rfind('[')
    if ultimo_corchete != -1:
        fragmento = texto_limpio[ultimo_corchete:]
        try:
            return json.loads(fragmento)
        except json.JSONDecodeError:
            pass
        pos = fragmento.rfind('}')
        if pos != -1:
            reparado = fragmento[:pos + 1].rstrip().rstrip(',') + '\n]'
            try:
                return json.loads(reparado)
            except json.JSONDecodeError:
                pass

    # 5. Reparación genérica de array truncado
    try:
        pos_ultimo = texto_limpio.rfind('}')
        if pos_ultimo != -1:
            recortado = texto_limpio[:pos_ultimo + 1].strip()
            if not recortado.endswith(']'):
                recortado += '\n]'
            pos_inicio = recortado.find('[')
            if pos_inicio != -1:
                return json.loads(recortado[pos_inicio:])
    except json.JSONDecodeError:
        pass

    raise ValueError("No se encontró una estructura JSON válida en la respuesta del LLM.")


def _procesar_resultado_llm(respuesta: str) -> List[Dict[str, Any]]:
    """Extrae y parsea la lista de emparejamientos compactos {id, campo, ubicacion} del LLM.

    NO usa Pydantic MapeoItem (que requiere hoja/fila/columna). La conversión a
    coordenadas físicas ocurre en _reconstruir_mapeo_fisico().
    """
    datos_raw: Any = None
    texto = str(respuesta).strip()

    # 1. Parseo directo
    try:
        datos_raw = json.loads(texto)
    except json.JSONDecodeError:
        pass

    # 2. Bloques markdown ```json ... ```
    if datos_raw is None:
        for m in re.finditer(r'```(?:json)?\s*(.*?)\s*```', texto, re.DOTALL | re.IGNORECASE):
            try:
                datos_raw = json.loads(m.group(1).strip())
                break
            except json.JSONDecodeError:
                pass

    # 3. Buscar desde último '[' o '{'
    if datos_raw is None:
        for ch_o, ch_c in [('[', ']'), ('{', '}')]:
            idx = texto.rfind(ch_o)
            if idx != -1:
                try:
                    datos_raw = json.loads(texto[idx:])
                    break
                except json.JSONDecodeError:
                    try:
                        fragmento = texto[idx:]
                        idx_c = fragmento.rfind(ch_c)
                        if idx_c != -1:
                            datos_raw = json.loads(fragmento[:idx_c + 1])
                            break
                    except json.JSONDecodeError:
                        pass

    if datos_raw is None:
        print(f"[AutoForm AI Pydantic] Error: No se pudo parsear JSON de respuesta LLM")
        return []

    # Normalizar a lista
    if isinstance(datos_raw, dict):
        if "mappings" in datos_raw and isinstance(datos_raw["mappings"], list):
            datos_raw = datos_raw["mappings"]
        elif "resultado" in datos_raw and isinstance(datos_raw["resultado"], list):
            datos_raw = datos_raw["resultado"]
        else:
            datos_raw = [datos_raw]

    if not isinstance(datos_raw, list):
        return []

    # Retornar solo items con id/campo o con hoja/fila/columna — sin validación Pydantic
    resultado: List[Dict[str, Any]] = []
    for item in datos_raw:
        if not isinstance(item, dict):
            continue
        tiene_compacto = "id" in item and "campo" in item
        tiene_fisico = "hoja" in item and "fila" in item and "columna" in item and "campo" in item
        if tiene_compacto or tiene_fisico:
            resultado.append(item)
    return resultado


# ---------------------------------------------------------------------------
# Auditoría de cobertura y re-consulta focalizada
# ---------------------------------------------------------------------------

def _evaluar_cobertura_campos(
    datos_empresa_filtrados: Dict[str, Any],
    mapeos_realizados: List[Dict[str, Any]],
) -> List[str]:
    """Devuelve los campos de DatosEmpresa que el LLM no asignó a ninguna celda."""
    esperados = set(datos_empresa_filtrados.keys())
    asignados = {item["campo"] for item in mapeos_realizados if item.get("campo")}

    # Si representante_legal fue asignado, considerar cubiertos representante_nombres y representante_apellidos
    if "representante_legal" in asignados:
        asignados.add("representante_nombres")
        asignados.add("representante_apellidos")

    return sorted(list(esperados - asignados))


_INDICIOS_CAMPOS_RECURSIVOS = {
    "banco": [r"banco", r"entidad\s+financiera", r"corporaci[oó]n"],
    "numero_cuenta": [r"cuenta", r"cta", r"n[uú]mero\s+de\s+cuenta"],
    "tipo_cuenta": [r"tipo\s+de\s+cuenta", r"ahorros", r"corriente"],
    "pagina_web": [r"web", r"sitio", r"url", r"p[aá]gina"],
    "sucursal": [r"sucursal", r"agencia", r"filial", r"oficina"],
    "expedicion": [r"expedici[oó]n", r"expedida"],
    "departamento": [r"dpto", r"departamento"],
    "pais": [r"pa[ií]s"],
    "cedula": [r"c\.?c\.?", r"c[eé]dula", r"identificaci[oó]n", r"documento"],
}


def _filtrar_campos_faltantes_candidatos(
    campos_faltantes: List[str],
    mapa_formularios: List[Dict[str, Any]],
    mapeos_realizados: List[Dict[str, Any]],
) -> List[str]:
    """HITO 8: Filtra la lista de campos faltantes para incluir únicamente aquellos
    que posean al menos un indicio o palabra clave en los rótulos libres del formulario.

    Si el formulario no contiene preguntas sobre 'banco' o 'página web', no se fuerza
    el re-mapeo, concluyendo el proceso sin invocaciones innecesarias a la IA.
    """
    if not campos_faltantes:
        return []

    celdas_ocupadas = {
        (item["hoja"], item["fila"], item["columna"])
        for item in mapeos_realizados
    }
    mapa_purgado = _purgar_mapa(mapa_formularios)
    rotulos_libres_txt = [
        str(elem.get("rotulo") or elem.get("valor") or "").strip().lower()
        for elem in mapa_purgado
        if (elem.get("hoja"), elem.get("fila"), elem.get("columna")) not in celdas_ocupadas
    ]

    campos_validos = []
    for campo in campos_faltantes:
        pats = _INDICIOS_CAMPOS_RECURSIVOS.get(campo)
        if not pats:
            campos_validos.append(campo)
            continue

        tiene_indicio = False
        for txt in rotulos_libres_txt:
            if any(re.search(pat, txt, re.IGNORECASE) for pat in pats):
                tiene_indicio = True
                break

        if tiene_indicio:
            campos_validos.append(campo)
        else:
            print(f"[AutoForm AI Coverage] Campo '{campo}' omitido del re-mapeo (no es solicitado por la plantilla).")

    return campos_validos




def _construir_prompt_focalizado(
    mapa_formularios: List[Dict[str, Any]],
    mapeos_realizados: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
    campos_faltantes: List[str],
) -> str:
    """Payload ultra-compacto para la re-consulta de cobertura con exclusión de pie de página."""
    celdas_ocupadas = {
        (item["hoja"], item["fila"], item["columna"])
        for item in mapeos_realizados
    }
    mapa_purgado = _purgar_mapa(mapa_formularios)
    rotulos_libres = [
        elem for elem in mapa_purgado
        if (elem.get("hoja"), elem.get("fila"), elem.get("columna")) not in celdas_ocupadas
    ]

    # Filtro de Exclusión Espacial: Ignorar pies de página (Y > 440pt) y textos legales/paginación
    rotulos_validos = []
    for elem in rotulos_libres:
        txt = str(elem.get("valor", "")).strip()
        bbox = elem.get("_pdf_bbox") or elem.get("_pdf_target_rect")
        if bbox and isinstance(bbox, (list, tuple)) and len(bbox) >= 2 and bbox[1] > 440:
            continue
        if re.search(r"p[aá]gina\s+\d+\s+de\s+\d+|derechos\s+reservados|formulario\s+gratuito|ccb|c[aá]mara\s+de\s+comercio|impresi[oó]n", txt, re.IGNORECASE):
            continue
        rotulos_validos.append(elem)

    datos_faltantes = {k: datos_empresa[k] for k in campos_faltantes if k in datos_empresa}
    payload = {
        "INSTRUCCION": f"ESTRICTO: Mapear UNICAMENTE los campos faltantes: {campos_faltantes}. PROHIBIDO re-asignar otros campos.",
        "F": rotulos_validos,
        "D": datos_faltantes
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))



# ---------------------------------------------------------------------------
# LLM-03: Deduplicación de coordenadas destino
# ---------------------------------------------------------------------------

def _calcular_celda_destino(item: Dict[str, Any]) -> Tuple[str, int, int]:
    """Calcula la coordenada de destino final (hoja, fila_destino, col_destino)."""
    hoja = str(item.get("hoja", ""))
    fila = int(item.get("fila", 0) or 0)
    col  = int(item.get("columna", 0) or 0)
    ubicacion = str(item.get("ubicacion", "")).lower()

    if ubicacion == "misma":
        return (hoja, fila, col)
    elif ubicacion == "abajo":
        return (hoja, fila + 1, col)
    else:
        return (hoja, fila, col + 1)


def deduplicar_coordenadas_destino(mapeos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Conserva sólo la primera asignación a cada celda de destino."""
    destinos_ocupados: set = set()
    resultado: List[Dict[str, Any]] = []
    for item in mapeos:
        coord = _calcular_celda_destino(item)
        if coord in destinos_ocupados:
            print(
                f"[AutoForm AI LLM-03] Deduplicación: campo '{item.get('campo')}' "
                f"omitido (celda destino {coord} ya ocupada)."
            )
            continue
        destinos_ocupados.add(coord)
        resultado.append(item)
    return resultado


# ---------------------------------------------------------------------------
# FASE 1: Selección del mejor mapeo por campo (anti-sobremappeo)
# ---------------------------------------------------------------------------

def _puntaje_afinidad_rotulo(item: Dict[str, Any]) -> Tuple[float, int, float, float]:
    """Score de afinidad de un ítem de mapeo con su rótulo.

    Devuelve una tupla comparable (mayor = mejor):
      1. Número de sinónimos (_INDICIOS) presentes en el rótulo.
      2. Preferencia por cajas PDF reales (+1) y AcroForms (+2); penaliza casillas (-1).
      3. Orden de lectura: menor (fila, columna) — negado para que el máximo sea el primero.
    """
    campo = str(item.get("campo", ""))
    rotulo = str(item.get("valor", "")).lower()

    coincidencias = 0
    for indicio in _INDICIOS.get(campo, []):
        if indicio in rotulo:
            coincidencias += 1

    fisico = 0
    if item.get("_pdf_es_caja"):
        fisico += 1
    if item.get("_pdf_es_acroform"):
        fisico += 2
    if item.get("_pdf_es_casilla"):
        fisico -= 1

    fila = float(item.get("fila", 0) or 0)
    col = float(item.get("columna", 0) or 0)
    return (coincidencias, fisico, -fila, -col)


def _seleccionar_mejor_mapeo_por_campo(mapeos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Conserva una sola asignación por campo, eligiendo la de mayor afinidad con el rótulo.

    Motivo: el LLM puede asignar un mismo campo a varios rótulos (sobremappeo) y la
    deduplicación previa conservaba el primero en el orden arbitrario del modelo. Aquí
    prevalece el criterio semántico/geométrico:
      1) coincidencias de sinónimos con el rótulo,
      2) preferencia por cajas PDF reales / AcroForms,
      3) desempate por orden de lectura (fila, columna).
    """
    mejores: Dict[str, Dict[str, Any]] = {}
    orden: List[str] = []
    for item in mapeos:
        campo = str(item.get("campo", ""))
        if not campo:
            continue
        score = _puntaje_afinidad_rotulo(item)
        previo = mejores.get(campo)
        if previo is None or score > _puntaje_afinidad_rotulo(previo):
            mejores[campo] = item
            if campo not in orden:
                orden.append(campo)

    total_in = sum(1 for m in mapeos if m.get("campo"))
    if total_in > len(mejores):
        print(
            f"[AutoForm AI FASE-1] Selección por campo: {len(mejores)} campos conservados "
            f"(descartadas {total_in - len(mejores)} asignaciones duplicadas del LLM)."
        )
    return [mejores[campo] for campo in orden]


def _validar_hard_gates_mapeo(
    resultado_mapeo: List[Dict[str, Any]],
    mapa_formularios: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Hard-Gate Validador: Garantiza que la Razón Social y el NIT no sean omitidos.

    Si el formulario tiene una celda para 'Razón Social' o 'NIT' y existe el dato en
    datos_empresa, se fuerza su asignación si el LLM por error lo dejó fuera.
    """
    campos_mapeados = {m.get("campo") for m in resultado_mapeo if m.get("campo")}
    mapeo_resultado = list(resultado_mapeo)

    # Regla 1: Razón Social
    if "razon_social" not in campos_mapeados and datos_empresa.get("razon_social"):
        for elem in mapa_formularios:
            val_str = str(elem.get("valor", "")).strip().lower()
            if re.search(r"r[aá]z[oó]n\s+social|nombre\s+(?:de\s+la\s+)?empresa|proponente|oferente|sociedad", val_str):
                mapeo_resultado.append({
                    "hoja": elem.get("hoja", ""),
                    "fila": int(elem.get("fila", 1)),
                    "columna": int(elem.get("columna", 1)),
                    "valor": elem.get("valor", ""),
                    "ubicacion": "derecha",
                    "campo": "razon_social",
                    "requiereMerge": True,
                    "celdasAMergear": int(elem.get("anchoLinea", 3) or 3),
                    "anchoLinea": int(elem.get("anchoLinea", 3) or 3),
                })
                print(f"[AutoForm AI Hard-Gate] Razón Social recuperada automáticamente para el rótulo '{elem.get('valor')}'")
                break

    # Regla 2: NIT
    if "nit" not in campos_mapeados and datos_empresa.get("nit"):
        for elem in mapa_formularios:
            val_str = str(elem.get("valor", "")).strip().lower()
            if re.search(r"\bnit\b|n\.i\.t|identificaci[oó]n\s+tributaria|r\.u\.t", val_str):
                mapeo_resultado.append({
                    "hoja": elem.get("hoja", ""),
                    "fila": int(elem.get("fila", 1)),
                    "columna": int(elem.get("columna", 1)),
                    "valor": elem.get("valor", ""),
                    "ubicacion": "derecha",
                    "campo": "nit",
                    "requiereMerge": False,
                    "celdasAMergear": 1,
                    "anchoLinea": 1,
                })
                print(f"[AutoForm AI Hard-Gate] NIT recuperado automáticamente para el rótulo '{elem.get('valor')}'")
                break

    # Regla 3: Cédula / C.C.
    if "cedula" not in campos_mapeados and datos_empresa.get("cedula"):
        for elem in mapa_formularios:
            val_str = str(elem.get("valor", "")).strip().lower()
            if re.search(r"\bc\.?c\.?\b|c[eé]dula|doc(?:umento)?\s+(?:de\s+)?identida[dn]|no\.\s*c\.?c\.?|identificaci[oó]n\s+(?:del\s+)?representante|no\.\s*(?:de\s+)?identificaci[oó]n|\bidentificaci[oó]n\b", val_str):
                mapeo_resultado.append({
                    "hoja": elem.get("hoja", ""),
                    "fila": int(elem.get("fila", 1)),
                    "columna": int(elem.get("columna", 1)),
                    "valor": elem.get("valor", ""),
                    "ubicacion": _calcular_ubicacion_fisica(
                        val_rotulo=elem.get("valor", ""),
                        derecha_vacia=bool(elem.get("derechaVacia", True)),
                        abajo_vacia=bool(elem.get("abajoVacia", False)),
                        derecha_es_merge=bool(elem.get("derechaEsMerge", False)),
                        tipo_espacio=str(elem.get("tipoEspacioEscritura", "derecha")).lower(),
                    ),
                    "campo": "cedula",
                    "requiereMerge": False,
                    "celdasAMergear": 1,
                    "anchoLinea": 1,
                })
                print(f"[AutoForm AI Hard-Gate] Cédula / C.C. recuperada automáticamente para el rótulo '{elem.get('valor')}'")
                break

    # Regla 4: Expedición de Cédula (Lugar / Ciudad — Excluir fechas)
    if "expedicion" not in campos_mapeados and datos_empresa.get("expedicion"):
        for elem in mapa_formularios:
            val_str = str(elem.get("valor", "")).strip().lower()
            # Omitir si el rótulo solicita la FECHA de expedición
            if re.search(r"fecha|dia|d[ií]a|mes|a[ñn]o|dd|mm|aaaa|yy", val_str):
                continue
            if re.search(r"expedida\s+en|lugar\s+de\s+expedici[oó]n|ciudad\s+de\s+expedici[oó]n|\bexpedici[oó]n\b", val_str):

                mapeo_resultado.append({
                    "hoja": elem.get("hoja", ""),
                    "fila": int(elem.get("fila", 1)),
                    "columna": int(elem.get("columna", 1)),
                    "valor": elem.get("valor", ""),
                    "ubicacion": _calcular_ubicacion_fisica(
                        val_rotulo=elem.get("valor", ""),
                        derecha_vacia=bool(elem.get("derechaVacia", True)),
                        abajo_vacia=bool(elem.get("abajoVacia", False)),
                        derecha_es_merge=bool(elem.get("derechaEsMerge", False)),
                        tipo_espacio=str(elem.get("tipoEspacioEscritura", "derecha")).lower(),
                    ),
                    "campo": "expedicion",
                    "requiereMerge": False,
                    "celdasAMergear": 1,
                    "anchoLinea": 1,
                })
                print(f"[AutoForm AI Hard-Gate] Expedición de Cédula recuperada automáticamente para el rótulo '{elem.get('valor')}'")
                break

    # Regla 5: Representante Legal
    if "representante_legal" not in campos_mapeados and datos_empresa.get("representante_legal"):
        for elem in mapa_formularios:
            val_str = str(elem.get("valor", "")).strip().lower()
            if re.search(r"en\s+caso\s+afirmativo|favor\s+indicar|conflicto|v[ií]nculo|^firma|firmas", val_str):
                continue
            if re.search(r"representante\s+legal|nombre\s+(?:del\s+)?representante|apoderado|gerente\s+general", val_str):
                mapeo_resultado.append({
                    "hoja": elem.get("hoja", ""),
                    "fila": int(elem.get("fila", 1)),
                    "columna": int(elem.get("columna", 1)),
                    "valor": elem.get("valor", ""),
                    "ubicacion": _calcular_ubicacion_fisica(
                        val_rotulo=elem.get("valor", ""),
                        derecha_vacia=bool(elem.get("derechaVacia", True)),
                        abajo_vacia=bool(elem.get("abajoVacia", False)),
                        derecha_es_merge=bool(elem.get("derechaEsMerge", False)),
                        tipo_espacio=str(elem.get("tipoEspacioEscritura", "derecha")).lower(),
                    ),
                    "campo": "representante_legal",
                    "requiereMerge": False,
                    "celdasAMergear": 1,
                    "anchoLinea": 1,
                })
                print(f"[AutoForm AI Hard-Gate] Representante Legal recuperado automáticamente para el rótulo '{elem.get('valor')}'")
                break

    # Filtro de Seguridad Final para Expedición:
    # No permitir la inyección del lugar de expedición en rótulos que soliciten la FECHA de expedición
    mapeo_limpio = []
    for item in mapeo_resultado:
        if item.get("campo") == "expedicion":
            val_rotulo = str(item.get("valor", "")).strip().lower()
            if re.search(r"fecha|dia|d[ií]a|mes|a[ñn]o|dd|mm|aaaa|yy", val_rotulo):
                print(f"[AutoForm AI Mapper Safety] Omitida asignación de 'expedicion' (lugar/ciudad 'Envigado') al rótulo de fecha: '{item.get('valor')}'")
                continue
        mapeo_limpio.append(item)

    return mapeo_limpio


# ---------------------------------------------------------------------------
# Hard-Gate Representante: campos repetidos en la sección del Representante Legal
# ---------------------------------------------------------------------------

# Patrones que identifican rótulos propios de la sección del Representante Legal
_PAT_SECCION_RL = re.compile(
    r"representante\s+legal|representante\s+jur[ií]dico|datos\s+del\s+representante",
    re.IGNORECASE
)

# Mapeo: patrón de rótulo → campo canónico a inyectar en esa posición
_ROTULOS_SECCION_RL: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*(?:nombre\s*/\s*apellidos|nombres?\s+y\s+apellidos?|nombre\s+completo)\s*$", re.IGNORECASE), "representante_legal"),
    (re.compile(r"^\s*(?:id|c\.?c\.?|cedula|identificaci[oó]n)\s*$", re.IGNORECASE), "cedula"),
    (re.compile(r"\btel[eé]fono\b|\bcelular\b|\bmovil\b|\bfono\b", re.IGNORECASE),    "telefono"),
    (re.compile(r"\bemail\b|\bcorreo\b|\be-mail\b|\bmail\b",          re.IGNORECASE),    "correo"),
    (re.compile(r"^\s*(?:direcci[oó]n|domicilio)\s*$",                re.IGNORECASE),    "direccion"),
    (re.compile(r"^\s*nombres?\s*$",                                    re.IGNORECASE),    "representante_nombres"),
    (re.compile(r"^\s*apellidos?\s*$",                                  re.IGNORECASE),    "representante_apellidos"),
]


# ---------------------------------------------------------------------------
# Hard-Gate Declaración de Origen / SAGRILAFT: "Yo, ____ identificado con ____ expedido en ____"
# ---------------------------------------------------------------------------

_PAT_SECCION_DECLARACION_ORIGEN = re.compile(
    r"declaraci[oó]n\s+de\s+origen|fuente\s+de\s+(?:fondos|recursos)|^\s*yo,?\s*$",
    re.IGNORECASE
)

_ROTULOS_SECCION_DECLARACION: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*yo,?\s*$", re.IGNORECASE), "representante_legal"),
    (re.compile(r"identificad[oa]\s+con|documento\s+de\s+identidad|c\.?c\.?", re.IGNORECASE), "cedula"),
    (re.compile(r"expedid[oa]\s+en|lugar\s+de\s+expedici[oó]n", re.IGNORECASE), "expedicion"),
]


def _mapear_campos_seccion_declaracion_origen(
    resultado_mapeo: List[Dict[str, Any]],
    mapa_formularios: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Hard-Gate: Rellena automáticamente los campos inline de la cláusula de Declaración de Origen.

    Ejemplo en formularios SAGRILAFT/SARLAFT colombianos:
      'Yo, [Nombre], identificado con el documento de identidad: [Cédula] expedido en: [Ciudad]'
    """
    fila_declaracion = None
    hoja_dec = None
    for elem in mapa_formularios:
        if _PAT_SECCION_DECLARACION_ORIGEN.search(str(elem.get("valor", ""))):
            fila_declaracion = int(elem.get("fila", 0))
            hoja_dec = str(elem.get("hoja", ""))
            break

    if fila_declaracion is None:
        return resultado_mapeo

    VENTANA = 6
    nuevos: List[Dict[str, Any]] = []
    for elem in mapa_formularios:
        if str(elem.get("hoja", "")) != hoja_dec:
            continue
        fila_elem = int(elem.get("fila", 0))
        if fila_elem < fila_declaracion or fila_elem > fila_declaracion + VENTANA:
            continue

        rotulo_txt = str(elem.get("valor", "")).strip()
        col_elem = int(elem.get("columna", 0))

        for patron, campo in _ROTULOS_SECCION_DECLARACION:
            if not patron.search(rotulo_txt):
                continue
            val_emp = datos_empresa.get(campo)
            if not val_emp:
                if campo == "representante_legal":
                    val_emp = datos_empresa.get("representante_nombres")
                if not val_emp:
                    continue

            # Remover mapeos erróneos en esta coordenada para inyectar el campo correcto
            resultado_mapeo = [
                m for m in resultado_mapeo
                if not (m.get("hoja") == hoja_dec and int(m.get("fila", 0)) == fila_elem and int(m.get("columna", 0)) == col_elem)
            ]

            derecha_es_merge = bool(elem.get("derechaEsMerge", False))
            ubicacion_calc = _calcular_ubicacion_fisica(
                val_rotulo=rotulo_txt,
                derecha_vacia=bool(elem.get("derechaVacia", True)),
                abajo_vacia=bool(elem.get("abajoVacia", False)),
                derecha_es_merge=derecha_es_merge,
                tipo_espacio=str(elem.get("tipoEspacioEscritura", "derecha")).lower(),
            )
            ancho_l = int(elem.get("anchoLinea", 1) or 1)
            nuevos.append({
                "hoja": hoja_dec,
                "fila": fila_elem,
                "columna": col_elem,
                "valor": rotulo_txt,
                "ubicacion": ubicacion_calc,
                "campo": campo,
                "requiereMerge": ancho_l > 1,
                "celdasAMergear": ancho_l,
                "anchoLinea": ancho_l,
            })
            print(
                f"[AutoForm AI Declaracion-Gate] Campo '{campo}' inyectado en Declaración de Origen "
                f"-> rótulo '{rotulo_txt}' F{fila_elem}C{col_elem}"
            )
            break

    return resultado_mapeo + nuevos


# ---------------------------------------------------------------------------
# Hard-Gate Referencias Bancarias: BANCO, SUCURSAL, N° CUENTA, TIPO DE CUENTA
# ---------------------------------------------------------------------------

_PAT_SECCION_BANCO = re.compile(
    r"referencia[s]?\s+bancaria[s]?|datos\s+bancarios|informaci[oó]n\s+bancaria",
    re.IGNORECASE
)

_ROTULOS_SECCION_BANCO: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*banco\s*$", re.IGNORECASE), "banco"),
    (re.compile(r"^\s*sucursal\s*$", re.IGNORECASE), "sucursal"),
    (re.compile(r"n[o°\.]?\s*cuenta\b|\bcuenta\s+no\b", re.IGNORECASE), "numero_cuenta"),
    (re.compile(r"tipo\s+de\s+cuenta\b|\btipo\s+cuenta\b", re.IGNORECASE), "tipo_cuenta"),
]


def _mapear_campos_seccion_banco(
    resultado_mapeo: List[Dict[str, Any]],
    mapa_formularios: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Hard-Gate: Garantiza la inyección precisa de datos en la tabla de Referencias Bancarias."""
    fila_banco = None
    hoja_banco = None
    for elem in mapa_formularios:
        if _PAT_SECCION_BANCO.search(str(elem.get("valor", ""))):
            fila_banco = int(elem.get("fila", 0))
            hoja_banco = str(elem.get("hoja", ""))
            break

    if fila_banco is None:
        return resultado_mapeo

    VENTANA = 6
    nuevos: List[Dict[str, Any]] = []
    for elem in mapa_formularios:
        if str(elem.get("hoja", "")) != hoja_banco:
            continue
        fila_elem = int(elem.get("fila", 0))
        if fila_elem < fila_banco or fila_elem > fila_banco + VENTANA:
            continue

        rotulo_txt = str(elem.get("valor", "")).strip()
        col_elem = int(elem.get("columna", 0))

        for patron, campo in _ROTULOS_SECCION_BANCO:
            if not patron.search(rotulo_txt):
                continue
            val_emp = datos_empresa.get(campo)
            if not val_emp:
                continue

            # Remover mapeos erróneos en esta coordenada para inyectar el campo bancario correcto
            resultado_mapeo = [
                m for m in resultado_mapeo
                if not (m.get("hoja") == hoja_banco and int(m.get("fila", 0)) == fila_elem and int(m.get("columna", 0)) == col_elem)
                and m.get("campo") != campo
            ]

            derecha_es_merge = bool(elem.get("derechaEsMerge", False))
            rotulos_en_fila = sum(1 for e in mapa_formularios if e.get("hoja") == hoja_banco and e.get("fila") == fila_elem)
            if rotulos_en_fila > 1 and not derecha_es_merge:
                ubicacion_calc = "abajo"
            else:
                ubicacion_calc = _calcular_ubicacion_fisica(
                    val_rotulo=rotulo_txt,
                    derecha_vacia=bool(elem.get("derechaVacia", True)),
                    abajo_vacia=bool(elem.get("abajoVacia", False)),
                    derecha_es_merge=derecha_es_merge,
                    tipo_espacio=str(elem.get("tipoEspacioEscritura", "derecha")).lower(),
                )
            ancho_l = int(elem.get("anchoLinea", 1) or 1)
            nuevos.append({
                "hoja": hoja_banco,
                "fila": fila_elem,
                "columna": col_elem,
                "valor": rotulo_txt,
                "ubicacion": ubicacion_calc,
                "campo": campo,
                "requiereMerge": ancho_l > 1,
                "celdasAMergear": ancho_l,
                "anchoLinea": ancho_l,
            })
            print(
                f"[AutoForm AI Banco-Gate] Campo '{campo}' inyectado en Sección Bancaria "
                f"-> rótulo '{rotulo_txt}' F{fila_elem}C{col_elem}"
            )
            break

    return resultado_mapeo + nuevos


def _mapear_campos_seccion_representante(
    resultado_mapeo: List[Dict[str, Any]],
    mapa_formularios: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Hard-Gate: Detecta y rellena campos repetidos en la sección del Representante Legal.

    Muchos formularios colombianos repiten campos como ID, Teléfono y email dos veces:
    una para los datos de la empresa y otra específicamente para el Representante Legal.
    El LLM solo mapea la primera ocurrencia y la deduplicación elimina la segunda.

    Esta función localiza la fila del rótulo 'Representante Legal' en el formulario y
    busca hacia abajo (ventana de 8 filas) los rótulos repetidos para inyectarlos.
    """
    # Coordenadas ya ocupadas para no colisionar
    coords_existentes = {
        (item.get("hoja", ""), int(item.get("fila", 0)), int(item.get("columna", 0)))
        for item in resultado_mapeo
    }
    nuevos: List[Dict[str, Any]] = []

    # 1. Encontrar la fila del rótulo "Representante Legal" en el mapa
    fila_seccion_rl = None
    hoja_rl = None
    for elem in mapa_formularios:
        if _PAT_SECCION_RL.search(str(elem.get("valor", ""))):
            fila_seccion_rl = int(elem.get("fila", 0))
            hoja_rl = str(elem.get("hoja", ""))
            break

    if fila_seccion_rl is None:
        return resultado_mapeo  # El formulario no tiene sección de Representante Legal

    # 2. Buscar en una ventana de filas desde la sección RL hasta la siguiente sección grande
    VENTANA = 10
    for elem in mapa_formularios:
        if str(elem.get("hoja", "")) != hoja_rl:
            continue
        fila_elem = int(elem.get("fila", 0))
        if fila_elem <= fila_seccion_rl or fila_elem > fila_seccion_rl + VENTANA:
            continue

        rotulo_txt = str(elem.get("valor", "")).strip()
        col_elem = int(elem.get("columna", 0))

        for patron, campo in _ROTULOS_SECCION_RL:
            if not patron.search(rotulo_txt):
                continue
            if not datos_empresa.get(campo):
                continue

            coord_origen = (hoja_rl, fila_elem, col_elem)
            # Remover mapeos erróneos en esta coordenada para inyectar el campo correcto de RL
            resultado_mapeo = [
                m for m in resultado_mapeo
                if not (m.get("hoja") == hoja_rl and int(m.get("fila", 0)) == fila_elem and int(m.get("columna", 0)) == col_elem)
            ]

            derecha_es_merge = bool(elem.get("derechaEsMerge", False))
            val_up = rotulo_txt.strip().upper()
            if val_up in ("NOMBRES", "APELLIDOS"):
                ubicacion_calc = "abajo"
            else:
                ubicacion_calc = _calcular_ubicacion_fisica(
                    val_rotulo=rotulo_txt,
                    derecha_vacia=bool(elem.get("derechaVacia", True)),
                    abajo_vacia=bool(elem.get("abajoVacia", False)),
                    derecha_es_merge=derecha_es_merge,
                    tipo_espacio=str(elem.get("tipoEspacioEscritura", "derecha")).lower(),
                )
            ancho_l = int(elem.get("anchoLinea", 1) or 1)
            nuevos.append({
                "hoja": hoja_rl,
                "fila": fila_elem,
                "columna": col_elem,
                "valor": rotulo_txt,
                "ubicacion": ubicacion_calc,
                "campo": campo,
                "requiereMerge": ancho_l > 1,
                "celdasAMergear": ancho_l,
                "anchoLinea": ancho_l,
            })
            coords_existentes.add(coord_origen)
            print(
                f"[AutoForm AI RL-Gate] Campo '{campo}' inyectado en sección Representante Legal "
                f"-> rótulo '{rotulo_txt}' F{fila_elem}C{col_elem}"
            )
            break  # un campo por rótulo

    return resultado_mapeo + nuevos




def _fusionar_mapeos(
    mapeos_iniciales: List[Dict[str, Any]],
    mapeos_complementarios: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Combina mapeos sin colisiones de celdas origen."""
    celdas_existentes = {
        (item["hoja"], item["fila"], item["columna"]) for item in mapeos_iniciales
    }
    resultado = list(mapeos_iniciales)
    for item in mapeos_complementarios:
        clave = (item["hoja"], item["fila"], item["columna"])
        if clave not in celdas_existentes:
            resultado.append(item)
            celdas_existentes.add(clave)
    return resultado


def _fusionar_mapeos_incrementales(
    mapeo_anterior: List[Dict[str, Any]],
    mapeo_nuevo: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Funde dos mapeos garantizando progreso monotónicamente creciente.

    Algoritmo:
      - Preserva TODOS los items del mapeo anterior que ya fueron diligenciados (estado OK).
      - Agrega items nuevos del mapeo_nuevo que no colisionen con coordenadas ya cubiertas.
      - Nunca elimina un campo ya mapeado correctamente.

    Resultado: el sistema NUNCA pierde campos entre ejecuciones (13→17→18→19→20).
    """
    # Índice del mapeo anterior por coordenada destino
    celdas_cubiertas: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
    for item in mapeo_anterior:
        clave = (item.get("hoja", ""), int(item.get("fila", 0)), int(item.get("columna", 0)))
        celdas_cubiertas[clave] = item

    # Agregar items nuevos solo si su coordenada no está ya cubierta
    resultado = list(mapeo_anterior)
    for item in mapeo_nuevo:
        clave = (item.get("hoja", ""), int(item.get("fila", 0)), int(item.get("columna", 0)))
        if clave not in celdas_cubiertas:
            resultado.append(item)
            celdas_cubiertas[clave] = item

    return resultado

def _reconstruir_mapeo_fisico(
    coincidencias_semanticas: List[Dict[str, Any]],
    mapa_formularios: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Transforma respuestas compactas del LLM (id -> campo) en objetos físicos con hoja, fila, columna.

    ARQUITECTURA HÍBRIDA: La ubicación de escritura es calculada por Python
    mediante _calcular_ubicacion_fisica(), NO por el LLM. El LLM solo resuelve
    el emparejamiento semántico (id_rotulo -> clave_empresa).
    """
    dict_mapa = {idx + 1: elem for idx, elem in enumerate(mapa_formularios)}
    resultado = []

    for match in coincidencias_semanticas:
        item_id = match.get("id")
        campo = match.get("campo")

        if item_id in dict_mapa and campo and campo in datos_empresa:
            elem = dict_mapa[item_id]
            val_str = str(elem.get("valor", "")).strip()

            # ── MURO DE CONTENCIÓN: Python calcula la ubicación (no el LLM) ──
            ubicacion_calc = _calcular_ubicacion_fisica(
                val_rotulo=val_str,
                derecha_vacia=bool(elem.get("derechaVacia", True)),
                abajo_vacia=bool(elem.get("abajoVacia", False)),
                derecha_es_merge=bool(elem.get("derechaEsMerge", False)),
                tipo_espacio=str(elem.get("tipoEspacioEscritura", "derecha")).lower(),
            )

            ancho_l = int(elem.get("anchoLinea", 1) or 1)
            item_plan = {
                "hoja": elem.get("hoja", ""),
                "fila": int(elem.get("fila", 1)),
                "columna": int(elem.get("columna", 1)),
                "inicioLineaCol": int(elem.get("inicioLineaCol") or elem.get("columna", 1)),
                "finLineaCol": int(elem.get("finLineaCol") or elem.get("columna", 1)),
                "valor": val_str,
                "ubicacion": ubicacion_calc,
                "campo": campo,
                "requiereMerge": bool(ancho_l > 1 and ubicacion_calc == "derecha"),
                "celdasAMergear": ancho_l,
                "anchoLinea": ancho_l,
            }
            # FIX: conservar coordenadas físicas PDF del mapa original para que el
            # relleno use el rect exacto y la validación visual realmente se ejecute.
            for clave in _CLAVES_PDF:
                if clave in elem:
                    item_plan[clave] = elem[clave]
            resultado.append(item_plan)
    return resultado


# ---------------------------------------------------------------------------
# Orquestador principal
# ---------------------------------------------------------------------------

# Variable global para pausar/activar el caché (HABILITADO POR DEFECTO PARA DETERMINISMO ABSOLUTO)
CACHE_HABILITADO: bool = True



def deshabilitar_cache() -> None:
    """Pone en pausa completamente el sistema de caché."""
    global CACHE_HABILITADO
    CACHE_HABILITADO = False
    print("[AutoForm AI Cache] Caché pausado / deshabilitado.")


def habilitar_cache() -> None:
    """Activa el sistema de caché."""
    global CACHE_HABILITADO
    CACHE_HABILITADO = True
    print("[AutoForm AI Cache] Caché activado.")


def mapeo_formularios(
    mapa_formularios: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Genera el plan de mapeo completo para un formulario Excel.

    Flujo:
    1. Caché exacto (hash SHA-256) → retorno inmediato (si CACHE_HABILITADO).
    2. Caché semántico fuzzy (rapidfuzz ≥ 90 %) → adaptar coordenadas (si CACHE_HABILITADO).
    3. Llamada principal al LLM.
    4. Auditoría de cobertura + re-consulta focalizada si hay omisiones.
    5. Deduplicación de coordenadas destino.
    6. Enriquecimiento con anchoLinea del parser (WRITER-03).
    7. Persistencia en caché de sesión y en disco (si CACHE_HABILITADO).
    """
    if not isinstance(mapa_formularios, list):
        raise ValueError("El mapa de formularios debe ser una lista de objetos.")

    mapa_purgado_pre = _purgar_mapa(mapa_formularios)
    form_hash = _hash_mapa(mapa_purgado_pre)

    if CACHE_HABILITADO:
        # ── 1. Caché exacto ───────────────────────────────────────────────────
        if form_hash in _cache_mapeos:
            print(f"[AutoForm AI LLM-04] Cache HIT Exacto (hash {form_hash[:12]}...).")
            return _cache_mapeos[form_hash]

        # ── 2. Caché semántico fuzzy ──────────────────────────────────────────
        huella = semantic_cache.generar_huella_formulario(mapa_purgado_pre)
        res_fuzzy = semantic_cache.buscar_plantilla_similar(huella, umbral=90.0)

        if res_fuzzy is not None:
            id_plantilla, plantilla_guardada, score = res_fuzzy
            plan_adaptado = semantic_cache.adaptar_mapeo_plantilla(mapa_formularios, plantilla_guardada)
            plan_adaptado = _enriquecer_con_ancholinea(plan_adaptado, mapa_formularios)

            plan_valido = [
                p for p in plan_adaptado
                if p.get("hoja") and int(p.get("fila", 0) or 0) > 0 and p.get("campo")
            ]
            # FASE-1: también depura planes provenientes de cachés antiguos con duplicados
            plan_valido = _seleccionar_mejor_mapeo_por_campo(plan_valido)

            if plan_valido:
                print(
                    f"[AutoForm AI FASE B] Cache Semantico HIT "
                    f"(Score: {score:.1f}% - Plantilla: {id_plantilla})."
                )
                _cache_mapeos[form_hash] = plan_valido
                _cache_debug[form_hash] = {
                    "hash": form_hash,
                    "tipo_cache": "SEMANTIC_FUZZY_HIT",
                    "score_similaridad": round(score, 1),
                    "plantilla_coincidente": id_plantilla,
                    "rotulos_enviados": len(mapa_purgado_pre),
                    "prompt_payload": f"[Caché Semántico Fuzzy {score:.1f}% — plantilla {id_plantilla}]",
                    "respuesta_llm": json.dumps(plan_valido, ensure_ascii=False),
                    "campos_mapeados": len(plan_valido),
                    "campos_faltantes_detectados": [],
                }
                return plan_valido
            else:
                print(
                    f"[AutoForm AI FASE B] Cache Semantico HIT invalido (plan vacio) "
                    f"para {id_plantilla}. Forzando Cache MISS..."
                )
                try:
                    semantic_cache.eliminar_plantilla(id_plantilla)
                except Exception:
                    pass
    else:
        print("[AutoForm AI Cache] Caché desactivado. Procesando dinámicamente con IA (LLM)...")

    print(f"[AutoForm AI LLM-04] Cache MISS (hash {form_hash[:12]}...). Invocando LLM...")

    # ── 3. Llamada principal al LLM ───────────────────────────────────────
    mapa_purgado = _purgar_mapa(mapa_formularios)
    datos_filtrados = _filtrar_datos_empresa(mapa_purgado, datos_empresa, modo_permisivo=False)

    prompt_principal = json.dumps(
        {"F": mapa_purgado, "D": datos_filtrados},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    respuesta_principal = invocar_llm(prompt_principal)
    coincidencias_raw = _procesar_resultado_llm(respuesta_principal)
    mapeos_iniciales = _reconstruir_mapeo_fisico(coincidencias_raw, mapa_formularios, datos_empresa)

    # ── 4. Auditoría de cobertura ─────────────────────────────────────────
    campos_faltantes_brutos = _evaluar_cobertura_campos(datos_filtrados, mapeos_iniciales)
    campos_faltantes = _filtrar_campos_faltantes_candidatos(
        campos_faltantes_brutos, mapa_formularios, mapeos_iniciales
    )
    resultado_final: List[Dict[str, Any]]

    if not campos_faltantes:
        print("[AutoForm AI Coverage] [OK] Cobertura 100 % (todos los campos solicitados por la plantilla fueron mapeados).")
        resultado_final = mapeos_iniciales
    else:
        print(
            f"[AutoForm AI Coverage] [WARNING] Faltan {len(campos_faltantes)} campos con indicios en la plantilla: "
            f"{campos_faltantes}. Ejecutando re-mapeo focalizado..."
        )
        try:
            prompt_focalizado = _construir_prompt_focalizado(
                mapa_formularios, mapeos_iniciales, datos_empresa, campos_faltantes
            )
            respuesta_comp = invocar_llm(prompt_focalizado)
            coincidencias_comp_raw = _procesar_resultado_llm(respuesta_comp)
            # Filtrado de Seguridad: autorizar únicamente campos verdaderamente faltantes
            coincidencias_comp_raw = [
                m for m in coincidencias_comp_raw if m.get("campo") in campos_faltantes
            ]
            mapeos_comp = _reconstruir_mapeo_fisico(coincidencias_comp_raw, mapa_formularios, datos_empresa)
            resultado_final = _fusionar_mapeos(mapeos_iniciales, mapeos_comp)


            print(
                f"[AutoForm AI Coverage] Re-mapeo: +{len(resultado_final) - len(mapeos_iniciales)} "
                f"campos recuperados."
            )
        except Exception as exc:
            print(f"[AutoForm AI Warning] Re-consulta de cobertura falló ({exc}). Usando mapeo inicial.")
            resultado_final = mapeos_iniciales

    # ── 5. Hard Gates Validador (Garantizar campos críticos Razón Social y NIT) ──
    resultado_final = _validar_hard_gates_mapeo(resultado_final, mapa_formularios, datos_empresa)

    # ── 5.5 Selección del mejor mapeo por campo (FASE-1: anti-sobremappeo) ──────
    resultado_final = _seleccionar_mejor_mapeo_por_campo(resultado_final)

    # ── 6. Deduplicación ──────────────────────────────────────────────────
    resultado_final = deduplicar_coordenadas_destino(resultado_final)

    # ── 6.5 Hard-Gate Representante Legal: inyectar campos repetidos en la sección RL ──
    # Se ejecuta DESPUÉS de la deduplicación para que campos como cedula/telefono/correo
    # puedan ser inyectados en la sección del representante sin conflicto con la sección principal.
    resultado_final = _mapear_campos_seccion_representante(resultado_final, mapa_formularios, datos_empresa)

    # ── 6.6 Hard-Gate Declaración de Origen / SAGRILAFT (Yo, ..., identificado con ..., expedido en ...) ──
    resultado_final = _mapear_campos_seccion_declaracion_origen(resultado_final, mapa_formularios, datos_empresa)

    # ── 6.7 Hard-Gate Referencias Bancarias (BANCO, SUCURSAL, N° CUENTA, TIPO DE CUENTA) ──
    resultado_final = _mapear_campos_seccion_banco(resultado_final, mapa_formularios, datos_empresa)

    # ── 6.8 Muro de Seguridad final de Ubicación: NOMBRES / APELLIDOS en cabeceras ──
    for item in resultado_final:
        v_upper = str(item.get("valor", "")).strip().upper()
        if v_upper in ("NOMBRES", "APELLIDOS"):
            item["ubicacion"] = "abajo"


    # ── 7. Enriquecimiento con anchoLinea del parser (WRITER-03) ──────────
    resultado_final = _enriquecer_con_ancholinea(resultado_final, mapa_formularios)

    # ── 8. Reporte de cobertura en consola ────────────────────────────────
    _generar_reporte_cobertura(datos_empresa, datos_filtrados, resultado_final)


    # ── 8. Persistencia (solo si el caché está activo) ───────────────────────
    if CACHE_HABILITADO:
        _cache_mapeos[form_hash] = resultado_final
        try:
            semantic_cache.guardar_plantilla_en_cache(form_hash[:16], mapa_purgado_pre, resultado_final)
        except Exception as exc:
            print(f"[AutoForm AI Warning] No se pudo guardar en Caché Semántico: {exc}")

    _cache_debug[form_hash] = {
        "hash": form_hash,
        "tipo_cache": "LLM_GENERATED",
        "rotulos_enviados": len(mapa_purgado_pre),
        "prompt_payload": prompt_principal,
        "respuesta_llm": respuesta_principal,
        "campos_mapeados": len(resultado_final),
        "campos_faltantes_detectados": campos_faltantes if campos_faltantes else [],
    }

    return resultado_final