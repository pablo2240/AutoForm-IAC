"""Stage 2: Clasificador Determinista de Campos vs Títulos (Pipeline AutoForm AI).

Analiza los rótulos crudos extraídos en Stage 1 y los clasifica en:
  - CAMPO_ENTRADA: Campos reales que esperan recibir datos de la empresa.
  - TITULO_SECCION: Encabezados decorativos (no se escriben, pero proporcionan contexto jerárquico).
  - TABLA_CABECERA: Columnas de tablas tabulares (banco, cuentas, socios) con escritura hacia abajo.
  - USO_EXCLUSIVO: Áreas reservadas para la empresa receptora / auditores (descartadas).
  - CONTROL_DOCUMENTAL: Metadatos de control como códigos de versión o paginación (descartadas).
  - FIRMA_ESPACIO: Recuadros de firma física.

Asigna a cada campo su `seccion_padre` para que el LLM reciba contexto semántico puro
sin necesidad de hard-gates embebidos en el código.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class ClasificacionElemento(str, Enum):
    CAMPO_ENTRADA = "CAMPO_ENTRADA"
    OPCION_SELECCION = "OPCION_SELECCION"
    PREGUNTA_CERRADA = "PREGUNTA_CERRADA"
    TITULO_SECCION = "TITULO_SECCION"
    TABLA_CABECERA = "TABLA_CABECERA"
    INSTRUCCION_TEXTO = "INSTRUCCION_TEXTO"
    TEXTO_LEGAL = "TEXTO_LEGAL"
    CONTROL_DOCUMENTAL = "CONTROL_DOCUMENTAL"
    USO_EXCLUSIVO = "USO_EXCLUSIVO"
    FIRMA_ESPACIO = "FIRMA_ESPACIO"
    NO_APLICA = "NO_APLICA"


# ── Patrones de Clasificación ──

_PATRON_CONTROL_DOCUMENTAL = re.compile(
    r"^\s*(?:versi[oó]n\s*:?|c[oó]digo\s*:?|p[aá]gina\s+\d+\s+de\s+\d+|vigencia\s*:?|fecha\s+de\s+aprobaci[oó]n|fo-[a-z0-9\-]+)\b",
    re.IGNORECASE
)

_PATRON_USO_EXCLUSIVO = re.compile(
    r"espacio\s+exclusivo|uso\s+exclusivo|uso\s+interno|espacio\s+reservado|reservado\s+para\s+la\s+empresa|verificaci[oó]n\s+de\s+informaci[oó]n\s*/\s*observaciones|para\s+uso\s+de\s+la\s+entidad|auditor[ií]a",
    re.IGNORECASE
)

_PATRON_FIRMAS = re.compile(
    r"^\s*(?:firma\s+del\s+representante|firma\s+autorizada|firma\s+y\s+huella|firma\s*:?|signature|huella\s+dactilar|sello\s+y\s+firma)\b",
    re.IGNORECASE
)

_PATRON_INSTRUCCIONES_ANEXOS = re.compile(
    r"^\s*(?:diligencie|llene|marque|se[ñn]ale|adjuntar|adjunte|anexar|anexo|copia\s+de|fotocopia\s+de|nota\s*:|importante\s*:|instrucciones|requisitos|favor|recuerde|certificaci[oó]n|documentos?\s+a\s+(?:presentar|adjuntar))\b",
    re.IGNORECASE
)

_PATRON_OPCIONES_SELECCION = re.compile(
    r"^\s*(?:si|no|s|n|ahorros|corriente|ahorro|corrientes|masculino|femenino|m|f|persona\s+natural|persona\s+jur[ií]dica|urbano|rural|propia|arrendada|familiar|otro|otra|n/a|na|principal|sucursal|privada|p[uú]blica|mixta|simplificado|com[uú]n)\s*$",
    re.IGNORECASE
)

_PATRON_TEXTO_LEGAL = re.compile(
    r"(?:autorizo\s+a|declaro\s+bajo|certifico\s+que|en\s+cumplimiento\s+de|manifiesto\s+que|bajo\s+la\s+gravedad|habeas\s+data|tratamiento\s+de\s+datos|pol[ií]tica\s+de\s+privacidad|sagrilaft|lavado\s+de\s+activos|financiamiento\s+del\s+terrorismo|origen\s+de\s+fondos|origen\s+de\s+bienes|cl[aá]usula|autorizaci[oó]n\s+para)",
    re.IGNORECASE
)

_PATRON_PREGUNTAS_CERRADAS = re.compile(
    r"^\s*¿.*?\?\s*$|^\s*(?:es\s+usted|declara\s+usted|autoriza\s+a|tiene\s+v[ií]nculo|es\s+pep|es\s+sujeto|obliga|responsable\s+de\s+iva|gran\s+contribuyente|autorretenedor|r[eé]gimen\s+com[uú]n|declarante\s+de\s+renta)\b",
    re.IGNORECASE
)

_TERMINOS_CABECERA_SECCION = re.compile(
    r"^(?:datos|informaci[oó]n|documentaci[oó]n|proponente|oferente|titulo|secci[oó]n|bloque|cap[ií]tulo|numeral|anexo|composici[oó]n|declaraci[oó]n|referencias)\b",
    re.IGNORECASE
)

_TERMINOS_CAMPO_CORTO = re.compile(
    r"\b(nit|rut|c\.?c\.?|c\.?e\.?|cedula|raz[oó]n\s+social|nombre|tel[eé]fono|celular|direcci[oó]n|"
    r"correo|email|ciudad|municipio|departamento|pa[ií]s|cargo|banco|cuenta|"
    r"representante|p[aá]gina|web|objeto|actividad|expedici[oó]n|matr[ií]cula|"
    r"sucursal|dv|d[ií]gito|establecimiento|domicilio|sede)\b",
    re.IGNORECASE
)

_PATRON_CABECERAS_TABLA = re.compile(
    r"^\s*(?:banco|sucursal|n[o°\.]?\s*cuenta|tipo\s+de\s+cuenta|tipo\s+cuenta|"
    r"nombre\s+socio|identificaci[oó]n\s*/?\s*tipo\s+id|"
    r"porcentaje|%\s*participaci[oó]n|valor|parentesco|vinculo)\s*$",
    re.IGNORECASE
)


def _normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    nfd = "".join(c for c in unicodedata.normalize("NFD", str(texto).lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[\s_\.\:\-\;\,\(\)\[\]\/\\]+", " ", nfd).strip()


def es_titulo_seccion(texto: str) -> bool:
    """Determina si un rótulo es un título decorativo de sección y no un campo de entrada."""
    t_clean = str(texto or "").strip()
    if not t_clean:
        return False

    # Rótulos que terminan en dos puntos o guiones bajos son campos directos
    if t_clean.endswith(":") or re.search(r"_{2,}|\.{3,}", t_clean):
        return False

    # Si empieza con número + punto (ej. "1. DATOS DEL REPRESENTANTE" vs "1. NIT")
    m_num = re.match(r"^\s*(?:\d+[\.]|[I|V|X]+\.?)\s+(.+)$", t_clean)
    if m_num:
        resto = m_num.group(1).strip()
        # Si el texto tras el número empieza con palabra de sección -> es título
        if _TERMINOS_CABECERA_SECCION.search(resto):
            return True
        # Si es un campo corto con término directo -> no es título (es campo)
        if len(resto.split()) <= 4 and _TERMINOS_CAMPO_CORTO.search(resto):
            return False

    # 1. Empieza con encabezado de sección explícito
    if re.search(r"^\s*(?:\d+[\.]|[I|V|X]+\.?)\s*(?:DATOS|INFORMACI[OÓ]N|DOCUMENTACI[OÓ]N|PROPONENTE|OFERENTE|TITULO|SECCI[OÓ]N|BLOQUE|CAP[IÍ]TULO|NUMERAL|ANEXO|COMPOSICI[OÓ]N|DECLARACI[OÓ]N|REFERENCIAS)", t_clean, re.IGNORECASE):
        return True

    # 2. Mayúsculas sostenidas típicas de títulos
    t_norm = _normalizar_texto(t_clean)
    titulos_tipicos_norm = [
        r"^representante\s+(?:legal|juridico)(?:\s*\(.*?\))?$",
        r"^datos\s+(?:de\s+la\s+empresa|generales|del\s+proponente|del\s+oferente|del\s+proveedor|de\s+la\s+sociedad)(?:\s*\(.*?\))?$",
        r"^datos\s+del\s+representante\s+(?:legal|juridico)?(?:\s*\(.*?\))?$",
        r"^informacion\s+(?:general|basica|financiera|tributaria|bancaria|legal|del\s+representante(?:\s+legal)?|de\s+la\s+empresa)(?:\s*\(.*?\))?$",
        r"^referencias\s+bancarias(?:\s*\(.*?\))?$",
        r"^composicion\s+accionaria(?:\s*\(.*?\))?$",
        r"^declaracion\s+de\s+origen\s+de\s+(?:fondos|bienes|recursos)(?:\s*\(.*?\))?$",
        r"^confirmacion\s+de\s+datos(?:\s*\(.*?\))?$",
    ]
    for pat in titulos_tipicos_norm:
        if re.match(pat, t_norm, re.IGNORECASE):
            return True

    return False


def clasificar_rotulo_individual(rotulo: str, propiedades_celda: Optional[Dict[str, Any]] = None) -> ClasificacionElemento:
    """Clasifica un rótulo individual según sus características semánticas y funcionales."""
    txt = str(rotulo or "").strip()
    if not txt:
        return ClasificacionElemento.NO_APLICA

    # 1. Control documental
    if _PATRON_CONTROL_DOCUMENTAL.search(txt):
        return ClasificacionElemento.CONTROL_DOCUMENTAL

    # 2. Uso exclusivo
    if _PATRON_USO_EXCLUSIVO.search(txt):
        return ClasificacionElemento.USO_EXCLUSIVO

    # 3. Firmas
    if _PATRON_FIRMAS.search(txt):
        return ClasificacionElemento.FIRMA_ESPACIO

    # 4. Opciones de selección directa (SI, NO, Ahorros, Corriente, etc.)
    if _PATRON_OPCIONES_SELECCION.match(txt):
        return ClasificacionElemento.OPCION_SELECCION

    # 5. Texto legal extenso o autorizaciones (SAGRILAFT, Habeas Data, etc.)
    if _PATRON_TEXTO_LEGAL.search(txt) or (len(txt) > 75 and not txt.endswith(":") and not re.search(r"_{2,}|\.{3,}", txt)):
        return ClasificacionElemento.TEXTO_LEGAL

    # 6. Instrucciones de diligenciamiento o anexos
    if _PATRON_INSTRUCCIONES_ANEXOS.search(txt):
        return ClasificacionElemento.INSTRUCCION_TEXTO

    # 7. Preguntas cerradas (¿...? o Gran Contribuyente, PEP, etc.)
    if _PATRON_PREGUNTAS_CERRADAS.search(txt):
        return ClasificacionElemento.PREGUNTA_CERRADA

    # 8. Títulos de sección
    if es_titulo_seccion(txt):
        return ClasificacionElemento.TITULO_SECCION

    # 9. Cabeceras de tabla
    if _PATRON_CABECERAS_TABLA.match(txt):
        return ClasificacionElemento.TABLA_CABECERA

    # Por defecto es un campo de entrada viable
    return ClasificacionElemento.CAMPO_ENTRADA


def clasificar_elementos_formulario(
    elementos_raw: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Clasifica todos los elementos del formulario y asigna jerarquía de secciones.
    
    Args:
        elementos_raw: Lista de elementos extraídos en Stage 1 por el Parser.
        
    Returns:
        Tuple: (todos_clasificados, campos_viables_para_llm)
    """
    todos_clasificados: List[Dict[str, Any]] = []
    campos_viables: List[Dict[str, Any]] = []

    # Agrupar por hoja para mantener jerarquía de secciones independiente por pestaña
    elementos_por_hoja: Dict[str, List[Dict[str, Any]]] = {}
    for idx, elem in enumerate(elementos_raw):
        hoja = str(elem.get("hoja", "Hoja1"))
        if hoja not in elementos_por_hoja:
            elementos_por_hoja[hoja] = []
        elem_copia = dict(elem)
        elem_copia["_id_original"] = idx + 1
        elementos_por_hoja[hoja].append(elem_copia)

    # Procesar hoja por hoja en orden de filas
    for hoja, elems in elementos_por_hoja.items():
        elems_ordenados = sorted(elems, key=lambda e: (int(e.get("fila", 0) or 0), int(e.get("columna", 0) or 0)))
        
        seccion_actual = "INFORMACIÓN GENERAL"
        rango_uso_exclusivo_activo = False
        fila_inicio_exclusivo = -1

        for elem in elems_ordenados:
            rotulo = str(elem.get("valor") or elem.get("rotulo") or "").strip()
            fila = int(elem.get("fila", 0) or 0)
            tipo_clasif = clasificar_rotulo_individual(rotulo, elem)

            # Manejo de secciones de uso exclusivo
            if tipo_clasif == ClasificacionElemento.USO_EXCLUSIVO:
                rango_uso_exclusivo_activo = True
                fila_inicio_exclusivo = fila

            if rango_uso_exclusivo_activo:
                if fila > fila_inicio_exclusivo + 15 or (tipo_clasif == ClasificacionElemento.TITULO_SECCION and tipo_clasif != ClasificacionElemento.USO_EXCLUSIVO):
                    rango_uso_exclusivo_activo = False
                else:
                    tipo_clasif = ClasificacionElemento.USO_EXCLUSIVO

            # Actualizar sección activa si encontramos un título
            if tipo_clasif == ClasificacionElemento.TITULO_SECCION:
                seccion_actual = rotulo

            # Determinar dirección de escritura recomendada con PRIORIDAD a la física real de la celda
            derecha_vacia = bool(elem.get("derechaVacia", False))
            abajo_vacia = bool(elem.get("abajoVacia", False))

            if derecha_vacia and not abajo_vacia:
                ubicacion_sugerida = "derecha"
                if tipo_clasif == ClasificacionElemento.TABLA_CABECERA:
                    tipo_clasif = ClasificacionElemento.CAMPO_ENTRADA
            elif abajo_vacia and not derecha_vacia:
                ubicacion_sugerida = "abajo"
            else:
                ubicacion_sugerida = str(elem.get("tipoEspacioEscritura", "derecha")).lower()
                if ubicacion_sugerida not in ("derecha", "abajo", "misma"):
                    ubicacion_sugerida = "derecha"
                if tipo_clasif == ClasificacionElemento.TABLA_CABECERA:
                    ubicacion_sugerida = "abajo"

            elem_clasificado = {
                **elem,
                "tipo_clasificacion": tipo_clasif.value,
                "seccion_padre": seccion_actual,
                "tipoEspacioEscritura": ubicacion_sugerida,
                "es_campo_viable": tipo_clasif in (ClasificacionElemento.CAMPO_ENTRADA, ClasificacionElemento.TABLA_CABECERA),
            }

            todos_clasificados.append(elem_clasificado)

            # Si es un campo viable, agregarlo a la lista de entrada para el LLM / Verifier
            if elem_clasificado["es_campo_viable"]:
                campos_viables.append({
                    "id": elem_clasificado["_id_original"],
                    "rotulo": rotulo,
                    "seccion": seccion_actual,
                    "hoja": hoja,
                    "fila": fila,
                    "columna": int(elem.get("columna", 0) or 0),
                    "tipoEspacioEscritura": ubicacion_sugerida,
                    "anchoLinea": int(elem.get("anchoLinea", 1) or 1),
                })

    return todos_clasificados, campos_viables
