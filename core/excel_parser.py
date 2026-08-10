"""Módulo de lectura de celdas y vecinos (openpyxl)."""

from __future__ import annotations

import io
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet


def cargar_libro(ruta_o_buffer: Any):
    """Carga un libro de Excel conservando el formato original."""
    if hasattr(ruta_o_buffer, "read"):
        ruta_o_buffer.seek(0)
        return load_workbook(ruta_o_buffer, data_only=False)
    return load_workbook(ruta_o_buffer, data_only=False)


def leer_celda(hoja: Worksheet, fila: int, col: int) -> Any:
    """Devuelve el valor de una celda (sin recalcular fórmulas)."""
    return hoja.cell(row=fila, column=col).value


def _es_celda_en_merge(hoja: Worksheet, fila: int, col: int) -> bool:
    """Determina si una celda pertenece a un rango combinado (fallback)."""
    for rango in hoja.merged_cells.ranges:
        if rango.min_row <= fila <= rango.max_row and rango.min_col <= col <= rango.max_col:
            return True
    return False


def _celda_vacia(hoja: Worksheet, fila: int, col: int) -> bool:
    """Verifica si una celda está vacía o no existe en la hoja."""
    if fila < 1 or col < 1:
        return True
    
    # Intentamos obtener la celda sin instanciarla si está fuera de las dimensiones existentes
    if fila > (hoja.max_row or 0) or col > (hoja.max_column or 0):
        return True
        
    celda = hoja.cell(row=fila, column=col)
    return celda.value is None or str(celda.value).strip() == ""


# ──────────────────────────────────────────────────────────────────────────────
# PARSER-01: Detección de bordes visuales de celdas
# ──────────────────────────────────────────────────────────────────────────────

def _tiene_borde(celda, lado: str) -> bool:
    """Devuelve True si la celda tiene un borde definido en el lado indicado.

    Args:
        celda: Objeto celda de openpyxl.
        lado: Uno de 'top', 'bottom', 'left', 'right'.
    """
    try:
        borde_lado = getattr(celda.border, lado, None)
        return borde_lado is not None and borde_lado.style is not None and borde_lado.style != "none"
    except Exception:
        return False


def _analizar_bordes_celda(hoja: Worksheet, fila: int, col: int) -> Dict[str, bool]:
    """Analiza los cuatro bordes de una celda y devuelve un diccionario con sus estados.

    Returns:
        Dict con claves: 'top', 'bottom', 'left', 'right'.
    """
    if fila < 1 or col < 1 or fila > (hoja.max_row or 0) or col > (hoja.max_column or 0):
        return {"top": False, "bottom": False, "left": False, "right": False}
    celda = hoja.cell(row=fila, column=col)
    return {
        "top":    _tiene_borde(celda, "top"),
        "bottom": _tiene_borde(celda, "bottom"),
        "left":   _tiene_borde(celda, "left"),
        "right":  _tiene_borde(celda, "right"),
    }


def _calcular_tipo_espacio(
    vacia: bool,
    es_merge: bool,
    bordes: Dict[str, bool],
) -> str:
    """Clasifica el tipo de espacio disponible para escritura basado en estado visual.

    Jerarquía de clasificación:
      - "merge"     → celda pertenece a un rango combinado (independiente del contenido)
      - "subrayado" → celda vacía con borde inferior (línea de captura _____)
      - "cuadro"    → celda vacía con todos sus bordes (caja de tabla)
      - "vacio"     → celda vacía sin bordes relevantes
      - "ocupado"   → celda no vacía (ya tiene contenido, no apta para escritura)

    Returns:
        str: "merge" | "subrayado" | "cuadro" | "vacio" | "ocupado"
    """
    if es_merge:
        return "merge"
    if not vacia:
        return "ocupado"
    tiene_bottom = bordes.get("bottom", False)
    tiene_top    = bordes.get("top", False)
    tiene_left   = bordes.get("left", False)
    tiene_right  = bordes.get("right", False)
    # Cuadro cerrado: al menos 3 de los 4 lados tienen borde
    lados_con_borde = sum([tiene_bottom, tiene_top, tiene_left, tiene_right])
    if lados_con_borde >= 3:
        return "cuadro"
    # Subrayado: solo el borde inferior (línea de captura)
    if tiene_bottom and lados_con_borde == 1:
        return "subrayado"
    # Subrayado laxo: bottom presente aunque haya algún lado adicional
    if tiene_bottom:
        return "subrayado"
    return "vacio"


# ──────────────────────────────────────────────────────────────────────────────
# PARSER-02: Detección de líneas de captura divididas entre celdas consecutivas
# ──────────────────────────────────────────────────────────────────────────────

def _calcular_ancho_linea_captura(
    hoja: Worksheet,
    fila: int,
    col_inicio: int,
    mapa_merges: Dict[Tuple[int, int], Any],
) -> int:
    """Escanea hacia la derecha desde col_inicio contando celdas que forman
    una línea de captura continua (vacías con borde inferior, o merge vacío).

    Escanea sin límite de ancho arbitrario para cubrir 100% de la línea de captura,
    deteniéndose de forma eficiente (break) tan pronto como termina la casilla.
    """
    max_col = hoja.max_column or 1
    ancho   = 0
    col     = col_inicio

    while col <= max_col:
        es_vacia = _celda_vacia(hoja, fila, col)
        rango = mapa_merges.get((fila, col))

        if not es_vacia:
            break  # Celda con contenido: fin de la línea

        if rango is not None:
            ancho += rango.max_col - col + 1
            break  # Un merge siempre es el espacio completo; detenerse aquí

        # Celda vacía normal: debe tener borde inferior para contar como captura
        bordes = _analizar_bordes_celda(hoja, fila, col)
        if bordes["bottom"]:
            ancho += 1
            col   += 1
        else:
            break  # Sin borde inferior: fin de la línea de captura

    return max(1, ancho)


import re

_PATRON_OPCION_CASILLA = re.compile(
    r"^\s*(S[ÍI]|NO|C\.?C\.?|C\.?E\.?|PASAPORTE|NIT|OTRO|AUTORRETENEDOR|GRAN CONTRIBUYENTE|MEDIANA|PEQUEÑA|GRAN EMPRESA|IMPORTADOR|EXPORTADOR|FABRICANTE|DISTRIBUIDOR)\b",
    re.IGNORECASE,
)


def _es_casilla_verificacion(
    vacia: bool,
    es_merge: bool,
    bordes: Dict[str, bool],
    ancho_linea: int,
    texto_rotulo: str = "",
) -> bool:
    """Determina si una celda de destino actúa como casilla de verificación (checkbox 1x1).

    Criterio Híbrido:
      - Condición Física: celda vacía, no es merge, ancho <= 1, lados_con_borde >= 3.
      - Condición Semántica: el rótulo vecino es corto (<= 20 chars) o coincide
        con patrones de opción explícitos (SÍ, NO, CC, CE, etc.).
    """
    if not vacia or es_merge or ancho_linea > 1:
        return False

    lados_con_borde = sum(1 for v in bordes.values() if v)
    if lados_con_borde < 3:
        return False

    if texto_rotulo:
        texto_limpio = str(texto_rotulo).strip()
        if len(texto_limpio) <= 20 or _PATRON_OPCION_CASILLA.search(texto_limpio):
            return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# PARSER-03: Extracción del color de fondo (fill.fgColor)
# ──────────────────────────────────────────────────────────────────────────────

def _extraer_color_fondo(celda) -> str:
    """Extrae el color de fondo de una celda como string hex (ej. 'FFFF00') o '' si no tiene.

    Soporta colores de tipo 'rgb', 'indexed' y 'theme'.
    Retorna cadena vacía si la celda no tiene relleno significativo.
    """
    try:
        fill = celda.fill
        if fill is None:
            return ""
        # Solo PatternFill con fill_type definido indica color real
        if not getattr(fill, "fill_type", None) or fill.fill_type in (None, "none"):
            return ""
        fg = getattr(fill, "fgColor", None)
        if fg is None:
            return ""
        color_type = getattr(fg, "type", None)
        if color_type == "rgb":
            rgb = getattr(fg, "rgb", "") or ""
            # Ignorar blanco puro y transparente (00000000, FFFFFFFF, 00FFFFFF)
            if rgb in ("", "00000000", "FFFFFFFF", "00FFFFFF", "FF000000"):
                return ""
            # Quitar prefijo de alpha (los 2 primeros chars) si son 8 dígitos
            return rgb[-6:] if len(rgb) == 8 else rgb
        if color_type == "indexed":
            return f"indexed:{getattr(fg, 'indexed', '')}"
        if color_type == "theme":
            return f"theme:{getattr(fg, 'theme', '')}"
    except Exception:
        pass
    return ""


def escanear_mapa_formularios(libro) -> List[Dict[str, Any]]:
    """Recorre todas las hojas y extrae el mapa visual/espacial de los rótulos con texto.

    Optimizado con indexación de rangos combinados O(1) y escaneo de baja latencia.
    """
    formulario: List[Dict[str, Any]] = []
    for hoja in libro.worksheets:
        # 1. Crear un diccionario O(1) de celdas combinadas -> objeto CellRange
        mapa_merges: Dict[Tuple[int, int], Any] = {}
        for rango in hoja.merged_cells.ranges:
            for r in range(rango.min_row, rango.max_row + 1):
                for c in range(rango.min_col, rango.max_col + 1):
                    mapa_merges[(r, c)] = rango

        # 2. Recorrer únicamente las celdas que realmente contienen datos
        for row in hoja.iter_rows():
            for cell in row:
                valor = cell.value
                if valor is None:
                    continue

                # Omitir tipos de datos numéricos o booleanos (no son etiquetas de formulario)
                if isinstance(valor, (int, float, bool)):
                    continue

                texto = str(valor).strip()
                # Omitir textos vacíos o demasiado cortos (menor a 2)
                if not texto or len(texto) < 2 or len(texto) > 120:
                    continue

                fila = cell.row
                columna = cell.column

                # ── PARSER-05: Merge propio de la etiqueta ─────────────────────
                merge_propio = mapa_merges.get((fila, columna))
                if merge_propio is not None:
                    es_celda_principal = (
                        merge_propio.min_row == fila and merge_propio.min_col == columna
                    )
                    if not es_celda_principal:
                        # Sub-celda de un merge ya registrado → saltar para evitar duplicados
                        continue
                    derecha_fila    = fila
                    derecha_columna = merge_propio.max_col + 1
                    es_merge_principal = True
                    coord_merge = str(merge_propio)
                else:
                    derecha_fila    = fila
                    derecha_columna = columna + 1
                    es_merge_principal = False
                    coord_merge = ""
                # ────────────────────────────────────────────────────────────

                abajo_fila   = fila + 1
                abajo_columna = columna

                # 3. Estado de vecinos: vacío / combinado (consultas O(1))
                derecha_vacia   = _celda_vacia(hoja, derecha_fila, derecha_columna)
                abajo_vacia     = _celda_vacia(hoja, abajo_fila, abajo_columna)
                rango_derecha   = mapa_merges.get((derecha_fila, derecha_columna))
                rango_abajo     = mapa_merges.get((abajo_fila, abajo_columna))
                derecha_es_merge = rango_derecha is not None
                abajo_es_merge   = rango_abajo is not None

                # Optimización: si ambos vecinos tienen contenido Y ninguno es merge, descartar.
                if not derecha_vacia and not abajo_vacia and not derecha_es_merge and not abajo_es_merge:
                    continue

                # ── PARSER-01: Análisis de bordes visuales ──────────────────
                bordes_derecha = _analizar_bordes_celda(hoja, derecha_fila, derecha_columna)
                bordes_abajo   = _analizar_bordes_celda(hoja, abajo_fila, abajo_columna)

                derecha_con_borde_inferior = bordes_derecha["bottom"]
                derecha_con_borde_todo     = all(bordes_derecha.values())
                abajo_con_borde_inferior   = bordes_abajo["bottom"]
                abajo_con_borde_todo       = all(bordes_abajo.values())

                tipo_derecha = _calcular_tipo_espacio(derecha_vacia, derecha_es_merge, bordes_derecha)
                tipo_abajo   = _calcular_tipo_espacio(abajo_vacia,   abajo_es_merge,   bordes_abajo)

                # El tipoEspacioEscritura representa el espacio preferido (derecha primero, luego abajo)
                if tipo_derecha in ("merge", "subrayado", "cuadro", "vacio"):
                    tipo_espacio_escritura = tipo_derecha
                else:
                    tipo_espacio_escritura = tipo_abajo

                # ── PARSER-02: Ancho real de la línea de captura ────────────
                if tipo_derecha in ("subrayado", "cuadro", "merge", "vacio"):
                    ancho_linea = _calcular_ancho_linea_captura(
                        hoja, fila, derecha_columna, mapa_merges
                    )
                else:
                    ancho_linea = 1

                # ── PARSER-04: Ancho del rango combinado del vecino derecho ───
                if rango_derecha is not None:
                    ancho_merge_vecino = rango_derecha.max_col - rango_derecha.min_col + 1
                else:
                    ancho_merge_vecino = 1
                # ────────────────────────────────────────────────────────────

                # ── Detección Híbrida de Casillas de Verificación (Checkbox 1x1) ──
                es_casilla = _es_casilla_verificacion(
                    derecha_vacia, derecha_es_merge, bordes_derecha, ancho_linea, texto
                ) or _es_casilla_verificacion(
                    abajo_vacia, abajo_es_merge, bordes_abajo, 1, texto
                )

                # ── PARSER-03: Color de fondo del rótulo ─────────────────────
                color_fondo = _extraer_color_fondo(cell)
                # ────────────────────────────────────────────────────────────

                formulario.append(
                    {
                        "hoja": hoja.title,
                        "fila": fila,
                        "columna": columna,
                        "valor": texto,
                        "derechaVacia":   derecha_vacia,
                        "abajoVacia":     abajo_vacia,
                        "derechaEsMerge": derecha_es_merge,
                        "abajoEsMerge":   abajo_es_merge,
                        "derechaConBordeInferior": derecha_con_borde_inferior,
                        "derechaConBordeTodo":     derecha_con_borde_todo,
                        "abajoConBordeInferior":   abajo_con_borde_inferior,
                        "abajoConBordeTodo":       abajo_con_borde_todo,
                        "tipoEspacioEscritura": tipo_espacio_escritura,
                        "anchoLinea": ancho_linea,
                        "anchoMergeVecino": ancho_merge_vecino,
                        "esMergePrincipal": es_merge_principal,
                        "coordMerge":       coord_merge,
                        "esCasillaVerificacion": es_casilla,
                        "colorFondo": color_fondo,
                    }
                )
    return formulario


