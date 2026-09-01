"""Representación Intermedia Espacial (IR) para AutoForm AI.

Transforma la lista plana de elementos crudos (elementos_raw) producida por
core/excel_parser.py en un árbol jerárquico:

    DocumentoIR
        └─ SeccionIR  (título, pertinencia, rango de filas)
              └─ FilaIR  (número de fila, lista de elementos)
                    └─ ElementoIR  (texto, coordenadas, tipo, vecinos)

Este módulo NO realiza mapeo semántico ni escribe en Excel.
Su responsabilidad es únicamente la representación estructural fiel
del formulario para consumo posterior por el LLM y el validador.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# 1. Enumeraciones de Clasificación
# ──────────────────────────────────────────────────────────────────────────────

class TipoElemento(str, Enum):
    """Clasificación funcional de un elemento detectado en el formulario."""
    SECTION_TITLE = "SECTION_TITLE"
    FIELD = "FIELD"
    OPTION = "OPTION"
    EXISTING_VALUE = "EXISTING_VALUE"
    INSTRUCTION = "INSTRUCTION"
    LEGAL_TEXT = "LEGAL_TEXT"
    DECORATIVE = "DECORATIVE"
    UNKNOWN = "UNKNOWN"


class PertinenciaSeccion(str, Enum):
    """Clasificación de aplicabilidad de una sección para diligenciamiento."""
    PENDIENTE = "PENDIENTE"
    PROCESAR = "PROCESAR"
    OMITIR_TERCEROS = "OMITIR_TERCEROS"
    OMITIR_USO_INTERNO = "OMITIR_USO_INTERNO"
    OMITIR_LEGAL = "OMITIR_LEGAL"
    MIXTA = "MIXTA"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Modelos de Datos IR (Dataclasses)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ElementoIR:
    """Un elemento individual detectado en una celda del formulario."""
    id: int
    texto: str
    tipo_elemento: TipoElemento
    hoja: str
    fila: int
    columna: int
    direccion_escritura: str = "derecha"
    ancho_linea: int = 1
    es_casilla: bool = False
    coordenada_excel: str = ""
    rango_merge: Optional[str] = None
    vecino_derecha_texto: str = ""
    vecino_abajo_texto: str = ""
    color_fondo: str = ""
    propiedades_raw: Optional[Dict[str, Any]] = field(default=None, repr=False)


@dataclass
class FilaIR:
    """Agrupa los elementos que comparten la misma fila física en la hoja."""
    numero_fila: int
    elementos: List[ElementoIR] = field(default_factory=list)


@dataclass
class SeccionIR:
    """Representa una sección del formulario delimitada por títulos."""
    id_seccion: str
    titulo: str
    fila_inicio: int
    fila_fin: int
    hoja: str
    pertinencia: PertinenciaSeccion = PertinenciaSeccion.PENDIENTE
    motivo_pertinencia: str = ""
    filas: List[FilaIR] = field(default_factory=list)

    @property
    def total_elementos(self) -> int:
        return sum(len(f.elementos) for f in self.filas)

    @property
    def elementos_campo(self) -> List[ElementoIR]:
        return [e for f in self.filas for e in f.elementos
                if e.tipo_elemento == TipoElemento.FIELD]


@dataclass
class DocumentoIR:
    """Representación intermedia completa de un documento formulario."""
    nombre_archivo: str
    tipo_documento: str
    secciones: List[SeccionIR] = field(default_factory=list)

    @property
    def total_secciones(self) -> int:
        return len(self.secciones)

    @property
    def total_elementos(self) -> int:
        return sum(s.total_elementos for s in self.secciones)

    def secciones_procesables(self) -> List[SeccionIR]:
        """Retorna solo las secciones con pertinencia PROCESAR, MIXTA o PENDIENTE."""
        return [s for s in self.secciones
                if s.pertinencia in (PertinenciaSeccion.PROCESAR,
                                     PertinenciaSeccion.MIXTA,
                                     PertinenciaSeccion.PENDIENTE)]

    def secciones_omitidas(self) -> List[SeccionIR]:
        """Retorna las secciones marcadas como no aplicables."""
        return [s for s in self.secciones
                if s.pertinencia in (PertinenciaSeccion.OMITIR_TERCEROS,
                                     PertinenciaSeccion.OMITIR_USO_INTERNO,
                                     PertinenciaSeccion.OMITIR_LEGAL)]

    def to_dict(self) -> Dict[str, Any]:
        """Serializa la IR completa a un diccionario para debug o envío al LLM."""
        return {
            "documento": self.nombre_archivo,
            "tipo": self.tipo_documento,
            "total_secciones": self.total_secciones,
            "total_elementos": self.total_elementos,
            "secciones": [
                {
                    "id_seccion": s.id_seccion,
                    "titulo": s.titulo,
                    "hoja": s.hoja,
                    "fila_inicio": s.fila_inicio,
                    "fila_fin": s.fila_fin,
                    "pertinencia": s.pertinencia.value,
                    "motivo_pertinencia": s.motivo_pertinencia,
                    "total_elementos": s.total_elementos,
                    "filas": [
                        {
                            "fila": f.numero_fila,
                            "elementos": [
                                {
                                    "id": e.id,
                                    "texto": e.texto,
                                    "tipo": e.tipo_elemento.value,
                                    "columna": e.columna,
                                    "coordenada": e.coordenada_excel,
                                    "direccion": e.direccion_escritura,
                                    "ancho_linea": e.ancho_linea,
                                    "es_casilla": e.es_casilla,
                                    "rango_merge": e.rango_merge,
                                    "vecino_derecha": e.vecino_derecha_texto,
                                    "vecino_abajo": e.vecino_abajo_texto,
                                }
                                for e in f.elementos
                            ],
                        }
                        for f in s.filas
                    ],
                }
                for s in self.secciones
            ],
        }


# ──────────────────────────────────────────────────────────────────────────────
# 3. Patrones Auxiliares para Clasificación de Tipo de Elemento
# ──────────────────────────────────────────────────────────────────────────────

def _normalizar(txt: str) -> str:
    """Normaliza texto: sin acentos, minúsculas, sin puntuación excesiva."""
    if not txt:
        return ""
    nfd = "".join(
        c for c in unicodedata.normalize("NFD", str(txt).lower())
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[\s_\.\:\-\;\,\(\)\[\]\/\\]+", " ", nfd).strip()


_PATRON_OPCIONES = re.compile(
    r"^\s*(?:si|no|s|n|x|ahorros|corriente|ahorro|corrientes|"
    r"masculino|femenino|m|f|persona\s+natural|persona\s+jur[ií]dica|"
    r"urbano|rural|propia|arrendada|familiar|otro|otra|n/a|na|"
    r"principal|sucursal|privada|p[uú]blica|mixta|simplificado|"
    r"com[uú]n|grande|peque[ñn]o|mediano|no\s+aplica)\s*$",
    re.IGNORECASE,
)

_PATRON_INSTRUCCIONES = re.compile(
    r"^\s*(?:diligencie|llene|marque|se[ñn]ale|adjuntar|adjunte|"
    r"anexar|anexo|copia\s+de|fotocopia\s+de|nota\s*:|importante\s*:|"
    r"instrucciones|requisitos|favor|recuerde|certificaci[oó]n|"
    r"documentos?\s+a\s+(?:presentar|adjuntar)|por\s+favor\s+anexar)\b",
    re.IGNORECASE,
)

_PATRON_TEXTO_LEGAL = re.compile(
    r"(?:autorizo\s+a|declaro\s+bajo|certifico\s+que|"
    r"en\s+cumplimiento\s+de|manifiesto\s+que|bajo\s+la\s+gravedad|"
    r"habeas\s+data|tratamiento\s+de\s+datos|"
    r"pol[ií]tica\s+de\s+privacidad|sagrilaft|"
    r"lavado\s+de\s+activos|financiamiento\s+del\s+terrorismo|"
    r"origen\s+de\s+fondos|cl[aá]usula|autorizaci[oó]n\s+para)",
    re.IGNORECASE,
)

_PATRON_CONTROL_DOCUMENTAL = re.compile(
    r"^\s*(?:versi[oó]n\s*:?|c[oó]digo\s*:?|"
    r"p[aá]gina\s+\d+\s+de\s+\d+|vigencia\s*:|"
    r"fecha\s+de\s+aprobaci[oó]n|fo-[a-z0-9\-]+)\b",
    re.IGNORECASE,
)

_PATRON_USO_EXCLUSIVO = re.compile(
    r"espacio\s+exclusivo|uso\s+exclusivo|uso\s+interno|"
    r"espacio\s+reservado|reservado\s+para\s+la\s+empresa|"
    r"verificaci[oó]n\s+de\s+informaci[oó]n\s*/\s*observaciones|"
    r"para\s+uso\s+de\s+la\s+entidad|auditor[ií]a\s+interna|"
    r"observaciones\s+del\s+l[ií]der",
    re.IGNORECASE,
)

_PATRON_FIRMAS = re.compile(
    r"^\s*(?:firma\s+del\s+representante|firma\s+autorizada|"
    r"firma\s+y\s+huella|firma\s*:?|signature|"
    r"huella\s+dactilar|sello\s+y\s+firma)\b",
    re.IGNORECASE,
)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Función de Detección de Título de Sección (Reutilizable)
# ──────────────────────────────────────────────────────────────────────────────

_TERMINOS_CABECERA = re.compile(
    r"^(?:datos|informaci[oó]n|documentaci[oó]n|proponente|oferente|"
    r"titulo|secci[oó]n|bloque|cap[ií]tulo|numeral|anexo|"
    r"composici[oó]n|declaraci[oó]n|referencias|representante|"
    r"[oó]rganos|conflicto|autorizaci[oó]n|cumplimiento)\b",
    re.IGNORECASE,
)

_TERMINOS_CAMPO_CORTO = re.compile(
    r"\b(nit|rut|c\.?c\.?|c\.?e\.?|cedula|raz[oó]n\s+social|nombre|"
    r"tel[eé]fono|celular|direcci[oó]n|correo|email|ciudad|municipio|"
    r"departamento|pa[ií]s|cargo|banco|cuenta|p[aá]gina|web|objeto|"
    r"actividad|lugar_expedici[oó]n|expedici[oó]n|matr[ií]cula|"
    r"sucursal|dv|d[ií]gito|establecimiento|domicilio|sede|n[uú]mero|nro|no|num|identificaci[oó]n|documento)\b",
    re.IGNORECASE,
)


def _es_titulo_seccion(texto: str, propiedades: Optional[Dict[str, Any]] = None) -> bool:
    """Determina si un texto es un título de sección del formulario,
    combinando análisis léxico, jerarquía y características visuales (color de fondo y merge).
    """
    t_clean = str(texto or "").strip()
    if not t_clean:
        return False

    # Campos directos con indicadores inline nunca son títulos de sección
    if t_clean.endswith(":") or re.search(r"_{2,}|\.{3,}", t_clean):
        return False

    # Numeración explícita: "3. REPRESENTANTE LEGAL" o "4.2 COMPOSICIÓN"
    m_num = re.match(r"^\s*(?:\d+(?:\.\d+)*[\.]?|[I|V|X]+\.?)\s+(.+)$", t_clean)
    if m_num:
        resto = m_num.group(1).strip()
        if _TERMINOS_CABECERA.search(resto):
            return True
        if len(resto.split()) <= 3 and _TERMINOS_CAMPO_CORTO.search(resto):
            return False
        return True

    # Encabezados en mayúsculas
    if re.search(
        r"^\s*(?:\d+(?:\.\d+)*[\.]\s*)?(?:DATOS|INFORMACI[OÓ]N|DOCUMENTACI[OÓ]N|"
        r"PROPONENTE|OFERENTE|TITULO|SECCI[OÓ]N|BLOQUE|CAP[IÍ]TULO|"
        r"NUMERAL|ANEXO|COMPOSICI[OÓ]N|DECLARACI[OÓ]N|REFERENCIAS|"
        r"REPRESENTANTE|[OÓ]RGANOS|CONFLICTO|AUTORIZACI[OÓ]N|CUMPLIMIENTO)",
        t_clean,
        re.IGNORECASE,
    ):
        return True

    # Títulos típicos normalizados
    t_norm = _normalizar(t_clean)
    titulos_norm = [
        r"^representante\s+(?:legal|juridico)(?:\s*\(.*?\))?$",
        r"^datos\s+(?:de\s+la\s+empresa|generales|del\s+proponente|del\s+oferente|del\s+proveedor|de\s+la\s+sociedad)(?:\s*\(.*?\))?$",
        r"^datos\s+del\s+representante\s+(?:legal|juridico)?(?:\s*\(.*?\))?$",
        r"^informacion\s+(?:general|basica|financiera|tributaria|bancaria|legal|del\s+representante(?:\s+legal)?|de\s+la\s+empresa)(?:\s*\(.*?\))?$",
        r"^referencias?\s+bancarias?(?:\s*\(.*?\))?$",
        r"^composicion\s+accionaria(?:\s*\(.*?\))?$",
        r"^declaracion\s+de\s+origen\s+de\s+(?:fondos|bienes|recursos)(?:\s*\(.*?\))?$",
        r"^confirmacion\s+de\s+datos(?:\s*\(.*?\))?$",
    ]
    for pat in titulos_norm:
        if re.match(pat, t_norm, re.IGNORECASE):
            return True

    # ── Reglas Visuales y Físicas de Encabezado / Banner ──
    if propiedades:
        color_fondo = str(propiedades.get("colorFondo") or "").strip()
        coord_merge = str(propiedades.get("coordMerge") or "").strip()
        col_actual = int(propiedades.get("columna", 1) or 1)
        es_merge = bool(propiedades.get("esMergePrincipal", False) or coord_merge)
        der_vacia = bool(propiedades.get("derechaVacia", False))
        ab_vacia = bool(propiedades.get("abajoVacia", False))
        der_merge = bool(propiedades.get("derechaEsMerge", False))
        tipo_espacio = str(propiedades.get("tipoEspacioEscritura", "derecha")).lower()

        # Calcular extensión física del merge (cuántas columnas abarca)
        min_col, max_col, span_merge = col_actual, col_actual, 1
        if coord_merge:
            try:
                from openpyxl.utils import range_boundaries
                min_c, _, max_c, _ = range_boundaries(coord_merge)
                if min_c and max_c:
                    min_col, max_col, span_merge = min_c, max_c, max_c - min_c + 1
            except Exception:
                pass

        tiene_espacio_llenado = der_vacia or der_merge or ab_vacia

        # 1. Banner de Ancho Completo (Ocupa desde el inicio de la celda hasta el final del formulario):
        # Si la celda combinada inicia cerca del margen izquierdo (columna <= 3) y se extiende
        # a través de múltiples columnas (span >= 5 o llega hasta col >= 10)
        es_franja_ancho_completo = (
            es_merge and min_col <= 3 and (span_merge >= 5 or max_col >= 10)
        )
        if es_franja_ancho_completo:
            if len(t_clean) >= 3 and not _TERMINOS_CAMPO_CORTO.search(t_clean):
                return True

        # 2. Franja divisoria con color de fondo (banner con relleno):
        if color_fondo:
            # Si tiene fondo sombreado y abarca merge (span >= 2) o no tiene celda de llenado contigua
            if es_merge or span_merge >= 2 or not tiene_espacio_llenado:
                if len(t_clean) >= 3 and not _TERMINOS_CAMPO_CORTO.search(t_clean):
                    return True
            # Si el texto es descriptivo en mayúsculas o título con fondo
            if len(t_clean) >= 6 and (t_clean.isupper() or t_clean.istitle()) and not _TERMINOS_CAMPO_CORTO.search(t_clean):
                return True

        # 3. Celda combinada ancha (span >= 4) sin celda de captura a la derecha:
        if es_merge and span_merge >= 4 and not der_vacia and not der_merge and tipo_espacio != "misma":
            if len(t_clean) >= 6 and not _TERMINOS_CAMPO_CORTO.search(t_clean):
                return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# 5. Función de Clasificación de Tipo de Elemento (Fase 1: ¿Qué es?)
# ──────────────────────────────────────────────────────────────────────────────

def clasificar_tipo_elemento(texto: str, propiedades: Optional[Dict[str, Any]] = None) -> TipoElemento:
    """Clasifica QUÉ TIPO de elemento es un texto, sin intentar mapearlo a datos maestros.

    Flujo de decisión:
      1. ¿Es un título de sección (léxico o visual con fondo)? → SECTION_TITLE
      2. ¿Es un texto de control documental?                   → DECORATIVE
      3. ¿Es una zona de uso exclusivo?                        → INSTRUCTION
      4. ¿Es una firma?                                       → DECORATIVE
      5. ¿Es una opción de selección?                          → OPTION
      6. ¿Es texto legal extenso?                              → LEGAL_TEXT
      7. ¿Es una instrucción de llenado?                       → INSTRUCTION
      8. ¿Es un campo de entrada viable?                       → FIELD
      9. Default                                               → UNKNOWN
    """
    txt = str(texto or "").strip()
    if not txt:
        return TipoElemento.UNKNOWN

    # 1. Título de sección (evaluación combinada léxica + visual con fondo)
    if _es_titulo_seccion(txt, propiedades):
        return TipoElemento.SECTION_TITLE

    # 2. Control documental (versión, código, paginación)
    if _PATRON_CONTROL_DOCUMENTAL.search(txt):
        return TipoElemento.DECORATIVE

    # 3. Uso exclusivo
    if _PATRON_USO_EXCLUSIVO.search(txt):
        return TipoElemento.INSTRUCTION

    # 4. Firmas
    if _PATRON_FIRMAS.search(txt):
        return TipoElemento.DECORATIVE

    # 5. Opciones de selección (SI, NO, Ahorros, Corriente, etc.)
    if _PATRON_OPCIONES.match(txt):
        return TipoElemento.OPTION

    # 6. Texto legal extenso
    if _PATRON_TEXTO_LEGAL.search(txt):
        return TipoElemento.LEGAL_TEXT
    if len(txt) > 75 and not txt.endswith(":") and not re.search(r"_{2,}|\.{3,}", txt):
        return TipoElemento.LEGAL_TEXT

    # 7. Instrucciones de diligenciamiento
    if _PATRON_INSTRUCCIONES.search(txt):
        return TipoElemento.INSTRUCTION

    # 8. Campo de entrada viable
    return TipoElemento.FIELD


# ──────────────────────────────────────────────────────────────────────────────
# 6. Constructor Principal: elementos_raw → DocumentoIR
# ──────────────────────────────────────────────────────────────────────────────

def _coord_excel(fila: int, columna: int) -> str:
    """Convierte fila y columna numéricas a coordenada Excel (ej: B19)."""
    try:
        from openpyxl.utils import get_column_letter
        return f"{get_column_letter(columna)}{fila}"
    except (ImportError, ValueError):
        return f"R{fila}C{columna}"


def construir_ir(
    elementos_raw: List[Dict[str, Any]],
    nombre_archivo: str = "documento.xlsx",
    tipo_documento: str = "excel",
) -> DocumentoIR:
    """Transforma la lista plana de elementos crudos del Parser en un DocumentoIR jerárquico.

    Pasos del constructor:
      1. Agrupar elementos por hoja.
      2. Ordenar por posición (fila, columna).
      3. Detectar títulos de sección y particionar en bloques.
      4. Clasificar el tipo de cada elemento (Fase 1: ¿Qué es?).
      5. Agrupar elementos dentro de cada sección por número de fila.
      6. Enriquecer con coordenadas Excel legibles y textos de vecinos.

    Args:
        elementos_raw: Lista de diccionarios del Parser (core/excel_parser.py).
        nombre_archivo: Nombre del archivo original.
        tipo_documento: "excel" o "pdf".

    Returns:
        DocumentoIR con la jerarquía completa: Secciones → Filas → Elementos.
    """
    doc = DocumentoIR(
        nombre_archivo=nombre_archivo,
        tipo_documento=tipo_documento,
    )

    if not elementos_raw:
        return doc

    # ── Paso 1: Agrupar por hoja ──
    por_hoja: Dict[str, List[Dict[str, Any]]] = {}
    for elem in elementos_raw:
        hoja = str(elem.get("hoja", "Hoja1"))
        por_hoja.setdefault(hoja, []).append(elem)

    id_global = 0
    sec_counter = 0

    for hoja_nombre, elems_hoja in por_hoja.items():

        # ── Paso 2: Ordenar por posición espacial ──
        elems_sorted = sorted(
            elems_hoja,
            key=lambda e: (int(e.get("fila", 0) or 0), int(e.get("columna", 0) or 0)),
        )

        # Construir índice rápido de vecinos por (fila, columna) para lookup de textos
        mapa_textos: Dict[Tuple[int, int], str] = {}
        for e in elems_sorted:
            f = int(e.get("fila", 0) or 0)
            c = int(e.get("columna", 0) or 0)
            mapa_textos[(f, c)] = str(e.get("valor") or "").strip()

        # ── Paso 3: Particionar en secciones por títulos detectados ──
        # Primero, identificar todos los índices de títulos de sección
        titulo_indices: List[int] = []
        for i, elem in enumerate(elems_sorted):
            texto = str(elem.get("valor") or "").strip()
            if _es_titulo_seccion(texto, elem):
                titulo_indices.append(i)

        # Crear particiones: cada sección va desde un título hasta el siguiente
        particiones: List[Tuple[int, int, str]] = []  # (idx_inicio, idx_fin, título)

        if not titulo_indices:
            # Sin títulos detectados: todo pertenece a una sección genérica
            particiones.append((0, len(elems_sorted) - 1, "INFORMACIÓN GENERAL"))
        else:
            # Elementos antes del primer título
            if titulo_indices[0] > 0:
                particiones.append((0, titulo_indices[0] - 1, "INFORMACIÓN GENERAL"))

            for ti_pos, ti_idx in enumerate(titulo_indices):
                titulo_texto = str(elems_sorted[ti_idx].get("valor") or "").strip()
                if ti_pos + 1 < len(titulo_indices):
                    fin_idx = titulo_indices[ti_pos + 1] - 1
                else:
                    fin_idx = len(elems_sorted) - 1
                particiones.append((ti_idx, fin_idx, titulo_texto))

        # ── Paso 4 y 5: Clasificar elementos y construir FilaIR por sección ──
        for (p_inicio, p_fin, titulo_sec) in particiones:
            sec_counter += 1
            sec_id = f"SEC_{sec_counter}"

            filas_mapa: Dict[int, FilaIR] = {}
            fila_min = 999999
            fila_max = 0

            for idx in range(p_inicio, p_fin + 1):
                elem = elems_sorted[idx]
                texto = str(elem.get("valor") or "").strip()
                fila = int(elem.get("fila", 0) or 0)
                col = int(elem.get("columna", 0) or 0)

                if fila < fila_min:
                    fila_min = fila
                if fila > fila_max:
                    fila_max = fila

                id_global += 1

                # Clasificación de tipo (Fase 1: ¿Qué es?)
                tipo = clasificar_tipo_elemento(texto, elem)

                # Coordenada Excel legible
                coord = _coord_excel(fila, col)

                # Rango merge
                rango_merge_str = str(elem.get("coordMerge", "")) or None
                if rango_merge_str == "":
                    rango_merge_str = None

                # Color de fondo
                color = str(elem.get("colorFondo", ""))

                # Dirección de escritura heredada del parser
                dir_esc = str(elem.get("tipoEspacioEscritura", "derecha")).lower()
                if dir_esc not in ("derecha", "abajo", "misma"):
                    dir_esc = "derecha"
                if color and dir_esc == "misma" and not re.search(r"_{2,}|\.{3,}", texto):
                    dir_esc = "derecha"

                # Ancho de línea de captura y casilla
                ancho = int(elem.get("anchoLinea", 1) or 1)
                es_casilla = bool(elem.get("esCasillaVerificacion", False))

                # Textos de vecinos
                # El vecino derecha está a (fila, col + ancho) o (fila, col + 1)
                col_derecha = col + max(1, ancho)
                vecino_der = mapa_textos.get((fila, col_derecha), "")
                if not vecino_der:
                    # Intentar con col + 1 si ancho era > 1 pero no hay texto allí
                    vecino_der = mapa_textos.get((fila, col + 1), "")
                vecino_abajo = mapa_textos.get((fila + 1, col), "")

                elemento_ir = ElementoIR(
                    id=id_global,
                    texto=texto,
                    tipo_elemento=tipo,
                    hoja=hoja_nombre,
                    fila=fila,
                    columna=col,
                    direccion_escritura=dir_esc,
                    ancho_linea=ancho,
                    es_casilla=es_casilla,
                    coordenada_excel=coord,
                    rango_merge=rango_merge_str,
                    vecino_derecha_texto=vecino_der,
                    vecino_abajo_texto=vecino_abajo,
                    color_fondo=color,
                    propiedades_raw=elem,
                )

                if fila not in filas_mapa:
                    filas_mapa[fila] = FilaIR(numero_fila=fila)
                filas_mapa[fila].elementos.append(elemento_ir)

            # Ordenar filas por número
            filas_ordenadas = [filas_mapa[k] for k in sorted(filas_mapa.keys())]

            seccion = SeccionIR(
                id_seccion=sec_id,
                titulo=titulo_sec,
                fila_inicio=fila_min if fila_min < 999999 else 0,
                fila_fin=fila_max,
                hoja=hoja_nombre,
                filas=filas_ordenadas,
            )

            doc.secciones.append(seccion)

    return doc
