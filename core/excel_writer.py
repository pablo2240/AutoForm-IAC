"""Módulo de modificación y combinación en Excel.

Este módulo implementa la escritura nativa en Excel usando openpyxl y evita
borrar fórmulas o estilos no mapeados.
"""

from copy import copy
from io import BytesIO
from typing import Any, Dict, List, Optional
import re

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet


def _celda_en_merge(hoja: Worksheet, fila: int, columna: int) -> Optional[Any]:
    for rango in hoja.merged_cells.ranges:
        if rango.min_row <= fila <= rango.max_row and rango.min_col <= columna <= rango.max_col:
            return rango
    return None


def _buscar_campo_anidado(obj: Any, campo: str) -> Any:
    if isinstance(obj, dict):
        if campo in obj:
            return obj[campo]
        for value in obj.values():
            resultado = _buscar_campo_anidado(value, campo)
            if resultado is not None:
                return resultado
    return None


def _obtener_valor_datos(datos_empresa: Dict[str, Any], campo: str) -> Any:
    # Soporte para separar el NIT en Colombia (NIT sin DV y Dígito de Verificación)
    if campo == "nit_sin_dv" and "nit" in datos_empresa:
        nit_val = str(datos_empresa["nit"])
        if "-" in nit_val:
            return nit_val.split("-")[0]
        return nit_val
        
    if campo == "nit_dv" and "nit" in datos_empresa:
        nit_val = str(datos_empresa["nit"])
        if "-" in nit_val:
            return nit_val.split("-")[-1]
        return ""

    if campo in datos_empresa:
        return datos_empresa[campo]

    valor = datos_empresa
    for parte in campo.split("."):
        if isinstance(valor, dict) and parte in valor:
            valor = valor[parte]
        else:
            valor = None
            break
    if valor is not None:
        return valor

    return _buscar_campo_anidado(datos_empresa, campo)


def _obtener_relleno_preservado(celda_origen, celda_destino) -> Optional[PatternFill]:
    """WRITER-01: Preserva el PatternFill de la celda destino u origen."""
    for c in (celda_destino, celda_origen):
        if c and hasattr(c, "fill") and c.fill and getattr(c.fill, "fill_type", None):
            return copy(c.fill)
    return None


def _obtener_fuente_preservada(celda_origen, celda_destino) -> Optional[Font]:
    """WRITER-02: Preserva la Font de la celda destino u origen."""
    for c in (celda_destino, celda_origen):
        if c and hasattr(c, "font") and c.font and (c.font.name or c.font.size or c.font.bold or c.font.color):
            return copy(c.font)
    return None


def _obtener_borde_completo(celda_origen, celda_destino) -> Optional[Border]:
    """WRITER-04: Copia los bordes relevantes (top, bottom, left, right) combinando celda_destino y celda_origen."""
    b_dest = celda_destino.border if celda_destino and hasattr(celda_destino, "border") else None
    b_orig = celda_origen.border if celda_origen and hasattr(celda_origen, "border") else None

    sides = {}
    for lado in ("top", "bottom", "left", "right"):
        side_dest = getattr(b_dest, lado, None) if b_dest else None
        side_orig = getattr(b_orig, lado, None) if b_orig else None

        if side_dest and side_dest.style and side_dest.style != "none":
            sides[lado] = Side(style=side_dest.style, color=side_dest.color)
        elif side_orig and side_orig.style and side_orig.style != "none":
            sides[lado] = Side(style=side_orig.style, color=side_orig.color)

    if sides:
        return Border(**sides)
    return None


def _obtener_celda_escribible(hoja: Worksheet, fila: int, columna: int) -> Any:
    """Garantiza retornar un objeto Cell escribible (no MergedCell).

    Si la celda indicada cae dentro de un rango combinado, retorna la celda superior izquierda
    (min_row, min_col) del rango.
    """
    for rango in hoja.merged_cells.ranges:
        if rango.min_row <= fila <= rango.max_row and rango.min_col <= columna <= rango.max_col:
            celda_top = hoja.cell(row=rango.min_row, column=rango.min_col)
            if type(celda_top).__name__ != "MergedCell":
                return celda_top

    celda = hoja.cell(row=fila, column=columna)
    if type(celda).__name__ == "MergedCell":
        for rango in hoja.merged_cells.ranges:
            if rango.min_row <= fila <= rango.max_row and rango.min_col <= columna <= rango.max_col:
                return hoja.cell(row=rango.min_row, column=rango.min_col)
    return celda


def _escribir_valor_en_celda(celda, valor, es_misma_celda: bool, hoja: Optional[Worksheet] = None):
    # Si celda es un objeto MergedCell de openpyxl (solo lectura), redirigir a celda principal
    if type(celda).__name__ == "MergedCell":
        if hoja is not None:
            celda = _obtener_celda_escribible(hoja, celda.row, celda.column)
            if type(celda).__name__ == "MergedCell":
                return  # Si aun así no es escribible, evitar crash
        else:
            return

    # Si el valor es booleano (True/False), lo representamos como una 'X' para casillas de verificación
    if isinstance(valor, bool):
        valor = "X" if valor else ""

    valor_actual = celda.value
    if valor_actual is not None and isinstance(valor_actual, str) and str(valor_actual).strip():
        # Buscar patrones de marcadores de posición como underscores (__) o puntos (...)
        patron_placeholder = r'_{2,}|\.{3,}'
        if re.search(patron_placeholder, valor_actual):
            try:
                celda.value = re.sub(patron_placeholder, str(valor), valor_actual, count=1)
            except AttributeError:
                pass
            return

        # Jamás invadimos ni sobreescribimos una celda que ya contiene un rótulo o enunciado
        return

    try:
        celda.value = valor
    except AttributeError:
        pass


def rellenar_formulario_excel(bytes_excel: bytes, plan_mapeo: List[Dict[str, Any]], datos_empresa: Dict[str, Any]) -> bytes:
    workbook = load_workbook(filename=BytesIO(bytes_excel), data_only=False)
    for item in plan_mapeo:
        hoja_nombre = str(item.get("hoja", ""))
        if hoja_nombre not in workbook.sheetnames:
            raise ValueError(f"La hoja '{hoja_nombre}' no existe en el archivo Excel.")

        ws = workbook[hoja_nombre]
        fila_origen = int(item.get("fila", 0))
        columna_origen = int(item.get("columna", 0))
        ubicacion = str(item.get("ubicacion", "")).lower()
        rango_origen_merge = _celda_en_merge(ws, fila_origen, columna_origen)

        if ubicacion == "misma":
            fila_destino = fila_origen
            columna_destino = columna_origen
        elif ubicacion == "derecha":
            fila_destino = fila_origen
            if rango_origen_merge is not None:
                columna_destino = rango_origen_merge.max_col + 1
            else:
                columna_destino = columna_origen + 1
        elif ubicacion == "abajo":
            if rango_origen_merge is not None:
                fila_destino = rango_origen_merge.max_row + 1
            else:
                fila_destino = fila_origen + 1
            columna_destino = columna_origen
        else:
            raise ValueError(f"Ubicación inválida en plan de mapeo: {ubicacion}")

        requiere_merge = bool(item.get("requiereMerge", False))
        celdas_a_mergear = int(item.get("celdasAMergear", 1) or 1)
        ancho_linea = int(item.get("anchoLinea", 1) or 1)

        # WRITER-07: Validación de coordenadas fuera de rango — saltar silenciosamente
        max_fila = ws.max_row or 0
        max_col  = ws.max_column or 0
        if fila_destino < 1 or columna_destino < 1 or fila_destino > max_fila or columna_destino > max_col:
            print(
                f"[AutoForm AI WRITER-07] Coordenada fuera de rango omitida: "
                f"hoja='{hoja_nombre}' fila={fila_destino} col={columna_destino} "
                f"(max_fila={max_fila}, max_col={max_col})"
            )
            continue

        # WRITER-03: Determinar cantidad de columnas a combinar por merge o por línea de captura dividida
        cant_cols_merge = 1
        if requiere_merge and celdas_a_mergear > 1:
            cant_cols_merge = celdas_a_mergear
        if ancho_linea > 1:
            cant_cols_merge = max(cant_cols_merge, ancho_linea)

        # PROTECCIÓN ANTI-INVASIÓN DE RÓTULOS: Verificar cuántas celdas consecutivas hacia la derecha
        # están realmente VACÍAS para jamás destruir u ocultar rótulos vecinos (ej. PAÍS, DEPARTAMENTO).
        if cant_cols_merge > 1:
            max_cols_libres = 1
            for col_chk in range(columna_destino + 1, min(columna_destino + cant_cols_merge, max_col + 1)):
                val_chk = ws.cell(row=fila_destino, column=col_chk).value
                if val_chk is not None and str(val_chk).strip() != "":
                    # Se encontró un rótulo o celda con contenido (ej. 'PAÍS') -> Detener el merge aquí
                    break
                max_cols_libres += 1
            cant_cols_merge = max_cols_libres

        valor = _obtener_valor_datos(datos_empresa, str(item.get("campo", "")))

        # WRITER-05: Si el valor es None (campo no presente en datos_empresa), continuar de forma silenciosa
        if valor is None:
            continue

        rango_preexistente = _celda_en_merge(ws, fila_destino, columna_destino)

        rango_combinado = None
        if cant_cols_merge > 1 and ubicacion == "derecha" and rango_preexistente is None:
            columna_final = columna_destino + cant_cols_merge - 1
            rango_combinado = (fila_destino, columna_destino, fila_destino, columna_final)
            ws.merge_cells(
                start_row=fila_destino,
                start_column=columna_destino,
                end_row=fila_destino,
                end_column=columna_final,
            )

        celda_destino = _obtener_celda_escribible(ws, fila_destino, columna_destino)
        celda_origen = _obtener_celda_escribible(ws, fila_origen, columna_origen)

        es_misma_celda = (celda_destino.coordinate == celda_origen.coordinate)
        _escribir_valor_en_celda(celda_destino, valor, es_misma_celda, hoja=ws)

        # WRITER-01, WRITER-02, WRITER-04: Aplicación y preservación de fondo (PatternFill), fuente (Font) y bordes (Border)
        relleno = _obtener_relleno_preservado(celda_origen, celda_destino)
        fuente = _obtener_fuente_preservada(celda_origen, celda_destino)
        borde_completo = _obtener_borde_completo(celda_origen, celda_destino)

        if rango_combinado is not None:
            _, inicio_col, _, fin_col = rango_combinado
            for col in range(inicio_col, fin_col + 1):
                c_item = _obtener_celda_escribible(ws, fila_destino, col)
                if type(c_item).__name__ != "MergedCell":
                    c_item.alignment = Alignment(vertical="center", wrap_text=True)
                    if relleno is not None:
                        c_item.fill = copy(relleno)
                    if fuente is not None:
                        c_item.font = copy(fuente)

                    if borde_completo is not None:
                        borde_celda = Border(
                            top=copy(borde_completo.top) if borde_completo.top else None,
                            bottom=copy(borde_completo.bottom) if borde_completo.bottom else None,
                            left=copy(borde_completo.left) if col == inicio_col and borde_completo.left else None,
                            right=copy(borde_completo.right) if col == fin_col and borde_completo.right else None,
                        )
                        c_item.border = borde_celda
        else:
            if type(celda_destino).__name__ != "MergedCell":
                celda_destino.alignment = Alignment(vertical="center", wrap_text=True)
                if relleno is not None:
                    celda_destino.fill = relleno
                if fuente is not None:
                    celda_destino.font = fuente
                if borde_completo is not None:
                    celda_destino.border = borde_completo

    salida = BytesIO()
    workbook.save(salida)
    salida.seek(0)
    return salida.getvalue()

