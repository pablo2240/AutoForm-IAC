"""Módulo de Gestión de Tablas Estructuradas y Filas Dinámicas en Excel.

Parte de la Suite de Precisión de AutoForm AI.
Provee:
  1. Identificación de filas existentes por clave única (NIT, código, contrato, correo).
  2. Detección de ambigüedad ante duplicados o claves insuficientes.
  3. Inserción segura de nuevas filas replicando estilos, bordes, formatos de celda y fórmulas relativas.
  4. Actualización del rango de la tabla formal (openpyxl ws.tables).
"""

from __future__ import annotations

import re
from copy import copy
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

from core.excel_inspector import ColumnaTabla, TablaExcel


def normalizar_valor_clave(valor: Any) -> str:
    """Normaliza un valor para comparación de clave única (sin espacios ni separadores superfluos)."""
    if valor is None:
        return ""
    v_str = str(valor).replace("\xa0", " ").strip()
    # Si es puramente numérico (ej. NIT o Cédula), extraer solo dígitos para comparación robusta
    digitos = re.sub(r"[^\d]", "", v_str)
    if len(digitos) >= 5:
        return digitos
    return v_str.lower()


def buscar_fila_por_clave(
    ws: Worksheet,
    tabla: TablaExcel,
    nombre_col_clave: str,
    valor_clave_busqueda: Any,
) -> Tuple[Optional[int], str]:
    """Busca la fila en la tabla donde la columna clave coincide con el valor buscado.

    Returns:
        Tuple[fila_encontrada, estado]:
          - estado: "ENCONTRADA" | "NO_ENCONTRADA" | "AMBIGUA_DUPLICADOS" | "COLUMNA_NO_EXISTE"
    """
    col_obj = tabla.obtener_columna_por_nombre(nombre_col_clave)
    if not col_obj:
        return None, "COLUMNA_NO_EXISTE"

    c_idx = col_obj.indice_col
    val_norm = normalizar_valor_clave(valor_clave_busqueda)
    if not val_norm:
        return None, "CLAVE_BUSQUEDA_VACIA"

    filas_coincidentes = []

    for r in range(tabla.fila_inicio_datos, tabla.fila_fin_datos + 1):
        val_celda = ws.cell(row=r, column=c_idx).value
        if val_celda is not None:
            if normalizar_valor_clave(val_celda) == val_norm:
                filas_coincidentes.append(r)

    if len(filas_coincidentes) == 1:
        return filas_coincidentes[0], "ENCONTRADA"
    elif len(filas_coincidentes) > 1:
        return None, f"AMBIGUA_DUPLICADOS: Coincide en filas {filas_coincidentes}"
    else:
        return None, "NO_ENCONTRADA"


def ajustar_formula_fila(formula_str: str, desplazamiento_filas: int) -> str:
    """Ajusta referencias relativas de fila en una fórmula de Excel (ej: A2*B2 -> A3*B3)."""
    if not formula_str or not formula_str.startswith("="):
        return formula_str

    def _reemplazar_coord(match):
        col_letra = match.group(1)
        es_fila_absoluta = match.group(2) == "$"
        fila_num = int(match.group(3))
        if es_fila_absoluta or desplazamiento_filas == 0:
            return match.group(0)
        nueva_fila = max(1, fila_num + desplazamiento_filas)
        return f"{col_letra}{nueva_fila}"

    # Patrón: Columna (A-Z) + posible '$' + Fila (\d+)
    patron = re.compile(r"([A-Za-z]+)(\$?)(\d+)")
    return patron.sub(_reemplazar_coord, formula_str)


def obtener_o_crear_fila_tabla(
    ws: Worksheet,
    tabla: TablaExcel,
    nombre_col_clave: str,
    valor_clave: Any,
) -> Tuple[int, bool, str]:
    """Obtiene la fila existente o agrega una nueva al final de la tabla conservando formatos y fórmulas.

    Returns:
        Tuple[fila_destino, es_nueva_fila, estado_o_advertencia]
    """
    fila_existente, estado = buscar_fila_por_clave(ws, tabla, nombre_col_clave, valor_clave)

    if estado == "ENCONTRADA" and fila_existente is not None:
        return fila_existente, False, "FILA_EXISTENTE"
    elif "AMBIGUA" in estado:
        return -1, False, f"Atención requerida: {estado}"

    # 1. Comprobar si la última fila actual de la tabla está completamente vacía
    ultima_fila = tabla.fila_fin_datos
    fila_vacia = True
    for c in range(tabla.col_inicio, tabla.col_fin + 1):
        cell_val = ws.cell(row=ultima_fila, column=c).value
        # Si tiene fórmula no la consideramos vacía
        if cell_val is not None and str(cell_val).strip() != "":
            fila_vacia = False
            break

    if fila_vacia and ultima_fila >= tabla.fila_inicio_datos:
        # Reutilizar la fila vacía existente
        return ultima_fila, True, "FILA_VACIA_REUTILIZADA"

    # 2. Agregar una fila nueva inmediatamente después de tabla.fila_fin_datos
    nueva_fila_idx = tabla.fila_fin_datos + 1
    ws.insert_rows(nueva_fila_idx, 1)

    fila_plantilla = tabla.fila_fin_datos
    desplazamiento = nueva_fila_idx - fila_plantilla

    # 3. Replicar formato, estilos y fórmulas de la fila anterior
    for c in range(tabla.col_inicio, tabla.col_fin + 1):
        celda_origen = ws.cell(row=fila_plantilla, column=c)
        celda_destino = ws.cell(row=nueva_fila_idx, column=c)

        if celda_origen.has_style:
            celda_destino.font = copy(celda_origen.font)
            celda_destino.border = copy(celda_origen.border)
            celda_destino.fill = copy(celda_origen.fill)
            celda_destino.number_format = celda_origen.number_format
            celda_destino.protection = copy(celda_origen.protection)
            celda_destino.alignment = copy(celda_origen.alignment)

        # Si la celda origen contenía fórmula, replicarla ajustando el índice de fila
        if celda_origen.data_type == "f" or (
            isinstance(celda_origen.value, str) and celda_origen.value.startswith("=")
        ):
            nueva_formula = ajustar_formula_fila(str(celda_origen.value), desplazamiento)
            celda_destino.value = nueva_formula

    # 4. Actualizar rango en la metadata de la tabla
    tabla.fila_fin_datos = nueva_fila_idx
    col_ini_letra = get_column_letter(tabla.col_inicio)
    col_fin_letra = get_column_letter(tabla.col_fin)
    tabla.rango_ref = f"{col_ini_letra}{tabla.fila_encabezados}:{col_fin_letra}{tabla.fila_fin_datos}"

    # Si es tabla formal en ws.tables, actualizar su referencia en openpyxl
    if tabla.es_tabla_formal and hasattr(ws, "tables") and tabla.nombre in ws.tables:
        ws.tables[tabla.nombre].ref = tabla.rango_ref

    return nueva_fila_idx, True, "NUEVA_FILA_AGREGADA"
