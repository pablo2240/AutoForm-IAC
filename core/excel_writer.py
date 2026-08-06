"""Módulo de modificación y combinación en Excel.

Este módulo implementa la escritura nativa en Excel usando openpyxl y evita
borrar fórmulas o estilos no mapeados.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List, Optional

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Side
from openpyxl.worksheet.worksheet import Worksheet
import re


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


def _copiar_borde_inferior(origen: Worksheet, fila: int, columna: int) -> Optional[Border]:
    celda = origen.cell(row=fila, column=columna)
    if celda.border and celda.border.bottom and celda.border.bottom.style:
        return Border(bottom=Side(style=celda.border.bottom.style, color=celda.border.bottom.color))
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
    if valor_actual is not None and isinstance(valor_actual, str):
        # Buscar patrones de marcadores de posición como underscores (__) o puntos (...)
        patron_placeholder = r'_{2,}|\.{3,}'
        if re.search(patron_placeholder, valor_actual):
            try:
                celda.value = re.sub(patron_placeholder, str(valor), valor_actual, count=1)
            except AttributeError:
                pass
            return

        # Jamás invadimos o concatenamos sobre una celda de enunciado pura
        if es_misma_celda:
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
            if item.get("columnaEscritura") and int(item["columnaEscritura"]) > 0:
                columna_destino = int(item["columnaEscritura"])
            elif rango_origen_merge is not None:
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
        celdas_a_mergear = int(item.get("celdasAMergear", 1))
        valor = _obtener_valor_datos(datos_empresa, str(item.get("campo", "")))

        # WRITER-05: Si el valor es None (campo no presente en datos_empresa), continuar de forma silenciosa
        if valor is None:
            continue

        rango_preexistente = _celda_en_merge(ws, fila_destino, columna_destino)

        rango_combinado = None
        if requiere_merge and celdas_a_mergear > 1 and ubicacion == "derecha" and rango_preexistente is None:
            # Si la celda destino es simple y requiere merge, creamos el rango combinado
            columna_final = columna_destino + celdas_a_mergear - 1
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

        if type(celda_destino).__name__ != "MergedCell":
            celda_destino.alignment = Alignment(vertical="center", wrap_text=True)

            borde_inferior = _copiar_borde_inferior(ws, fila_origen, columna_origen)
            if borde_inferior is not None:
                celda_destino.border = borde_inferior

        if rango_combinado is not None:
            borde_inferior = _copiar_borde_inferior(ws, fila_origen, columna_origen)
            _, inicio_col, _, fin_col = rango_combinado
            for col in range(inicio_col, fin_col + 1):
                c_item = _obtener_celda_escribible(ws, fila_destino, col)
                if type(c_item).__name__ != "MergedCell":
                    c_item.alignment = Alignment(vertical="center", wrap_text=True)
                    if borde_inferior is not None:
                        c_item.border = borde_inferior

    salida = BytesIO()
    workbook.save(salida)
    salida.seek(0)
    return salida.getvalue()
