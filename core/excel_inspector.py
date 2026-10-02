"""Módulo de Inspección Estructurada Profunda de Archivos Excel (.xlsx / .xlsm).

Parte de la Suite de Precisión de AutoForm AI.
Inspecciona un libro openpyxl extrayendo:
  1. Hojas disponibles y su visibilidad.
  2. Tablas formales (ws.tables) y rangos tabulares detectados con su fila de encabezados y columnas.
  3. Rangos con nombre (wb.defined_names).
  4. Celdas calculadas con fórmulas (=SUM, =BUSCARV, data_type='f') para garantizar su protección absoluta.
  5. Validaciones de datos (ws.data_validations) como listas desplegables, rangos numéricos y fechas.
  6. Celdas protegidas/bloqueadas.
  7. Valores preexistentes para evitar sobreescritura accidental sin confirmación.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import openpyxl
from openpyxl.utils import range_boundaries, coordinate_to_tuple
from openpyxl.worksheet.worksheet import Worksheet


@dataclass
class ColumnaTabla:
    """Información de una columna en una tabla estructurada."""
    indice_col: int
    nombre: str
    letra_col: str = ""


@dataclass
class TablaExcel:
    """Información de una tabla (formal openpyxl o tabular heurística)."""
    nombre: str
    hoja: str
    rango_ref: str
    fila_encabezados: int
    fila_inicio_datos: int
    fila_fin_datos: int
    col_inicio: int
    col_fin: int
    columnas: List[ColumnaTabla] = field(default_factory=list)
    es_tabla_formal: bool = True

    def obtener_columna_por_nombre(self, nombre_col: str) -> Optional[ColumnaTabla]:
        n_clean = nombre_col.strip().lower()
        for col in self.columnas:
            if col.nombre.strip().lower() == n_clean:
                return col
        return None


@dataclass
class ReglaValidacionCelda:
    """Regla de validación de datos (p. ej. lista desplegable) aplicable a una celda."""
    tipo: str  # 'list', 'whole', 'decimal', 'date', 'textLength', etc.
    opciones_permitidas: List[str] = field(default_factory=list)
    formula1: Optional[str] = None
    formula2: Optional[str] = None
    permite_blanco: bool = True
    mensaje_error: Optional[str] = None


@dataclass
class InspeccionLibroExcel:
    """Resultado integral de la inspección estructurada de un libro Excel."""
    hojas: List[str] = field(default_factory=list)
    hojas_ocultas: List[str] = field(default_factory=list)
    tablas: List[TablaExcel] = field(default_factory=list)
    rangos_con_nombre: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Celdas que contienen fórmulas: {(hoja, fila, col): formula_str}
    celdas_con_formula: Dict[Tuple[str, int, int], str] = field(default_factory=dict)
    
    # Celdas con validaciones (dropdowns, etc): {(hoja, fila, col): ReglaValidacionCelda}
    validaciones_por_celda: Dict[Tuple[str, int, int], ReglaValidacionCelda] = field(default_factory=dict)
    
    # Celdas protegidas: {(hoja, fila, col): True}
    celdas_protegidas: Set[Tuple[str, int, int]] = field(default_factory=set)
    
    # Valores existentes (no vacíos y no fórmulas): {(hoja, fila, col): valor_str}
    valores_existentes: Dict[Tuple[str, int, int], Any] = field(default_factory=dict)
    
    # Celdas combinadas por hoja: {hoja: [(min_r, max_r, min_c, max_c)]}
    celdas_combinadas: Dict[str, List[Tuple[int, int, int, int]]] = field(default_factory=dict)
    formulas_firma: Dict[Tuple[str, int, int], str] = field(default_factory=dict)
    estilos_firma: Dict[Tuple[str, int, int], int] = field(default_factory=dict)
    validaciones_firma: Dict[str, Tuple[Tuple[str, str, str], ...]] = field(default_factory=dict)
    tablas_firma: Dict[str, Tuple[Tuple[str, str], ...]] = field(default_factory=dict)
    hojas_firma: Dict[str, str] = field(default_factory=dict)
    tiene_controles_vml: bool = False

    def es_celda_formula(self, hoja: str, fila: int, col: int) -> bool:
        return (hoja, fila, col) in self.celdas_con_formula

    def tiene_validacion(self, hoja: str, fila: int, col: int) -> bool:
        return (hoja, fila, col) in self.validaciones_por_celda

    def obtener_validacion(self, hoja: str, fila: int, col: int) -> Optional[ReglaValidacionCelda]:
        return self.validaciones_por_celda.get((hoja, fila, col))

    def es_celda_protegida(self, hoja: str, fila: int, col: int) -> bool:
        return (hoja, fila, col) in self.celdas_protegidas

    def obtener_valor_anterior(self, hoja: str, fila: int, col: int) -> Any:
        return self.valores_existentes.get((hoja, fila, col))

    def obtener_tabla(self, nombre_o_hoja: str, fila: Optional[int] = None, col: Optional[int] = None) -> Optional[TablaExcel]:
        for t in self.tablas:
            if t.nombre.lower() == nombre_o_hoja.lower():
                return t
            if fila is not None and col is not None and t.hoja.lower() == nombre_o_hoja.lower():
                if t.fila_encabezados <= fila <= t.fila_fin_datos and t.col_inicio <= col <= t.col_fin:
                    return t
        return None


def inspeccionar_libro_excel(
    archivo_o_libro: Union[bytes, bytearray, io.BytesIO, openpyxl.Workbook]
) -> InspeccionLibroExcel:
    """Inspecciona un archivo Excel extrayendo toda su topología estructural, fórmulas y restricciones."""
    bytes_original: Optional[bytes] = None
    if isinstance(archivo_o_libro, openpyxl.Workbook):
        wb = archivo_o_libro
    elif isinstance(archivo_o_libro, (bytes, bytearray)):
        bytes_original = bytes(archivo_o_libro)
        wb = openpyxl.load_workbook(filename=io.BytesIO(bytes_original), data_only=False, keep_vba=True)
    elif hasattr(archivo_o_libro, "read"):
        archivo_o_libro.seek(0)
        wb = openpyxl.load_workbook(filename=archivo_o_libro, data_only=False)
    else:
        raise TypeError(f"Tipo no soportado para inspeccionar Excel: {type(archivo_o_libro)}")

    resultado = InspeccionLibroExcel()
    if bytes_original:
        try:
            with zipfile.ZipFile(io.BytesIO(bytes_original)) as paquete:
                resultado.tiene_controles_vml = any(n.startswith("xl/ctrlProps/") for n in paquete.namelist())
        except zipfile.BadZipFile:
            pass
    resultado.hojas = list(wb.sheetnames)

    # 1. Hojas y estados de visibilidad
    for sheetname in wb.sheetnames:
        ws = wb[sheetname]
        if ws.sheet_state != "visible":
            resultado.hojas_ocultas.append(sheetname)

    # 2. Rangos con nombre (Defined Names)
    try:
        for name, def_name in wb.defined_names.items():
            destinos = []
            try:
                for dest_sheet, dest_coord in def_name.destinations:
                    destinos.append({"hoja": dest_sheet, "coord": dest_coord})
            except Exception:
                pass
            resultado.rangos_con_nombre[name] = {
                "nombre": name,
                "destinos": destinos,
                "valor": getattr(def_name, "value", ""),
            }
    except Exception:
        pass

    # 3. Inspección por hoja
    for nombre_hoja in wb.sheetnames:
        ws = wb[nombre_hoja]
        max_f = ws.max_row or 0
        max_c = ws.max_column or 0
        hoja_protegida = bool(getattr(ws.protection, "sheet", False))

        # 3.1 Celdas combinadas
        merges_hoja = []
        for rng in ws.merged_cells.ranges:
            merges_hoja.append((rng.min_row, rng.max_row, rng.min_col, rng.max_col))
        resultado.celdas_combinadas[nombre_hoja] = merges_hoja
        resultado.hojas_firma[nombre_hoja] = ws.sheet_state

        # 3.2 Tablas formales (ws.tables)
        if hasattr(ws, "tables") and ws.tables:
            for tbl_name, tbl_val in ws.tables.items():
                ref = None
                if hasattr(tbl_val, "ref"):
                    ref = tbl_val.ref
                elif isinstance(tbl_val, str) and ":" in tbl_val:
                    ref = tbl_val
                elif tbl_name in ws.tables:
                    try:
                        table_obj = ws.tables[tbl_name]
                        ref = getattr(table_obj, "ref", None)
                    except Exception:
                        pass

                if ref and ":" in str(ref):
                    try:
                        min_col, min_row, max_col, max_row = range_boundaries(str(ref))
                        columnas_tbl = []
                        # Leer fila de encabezados
                        for c_idx in range(min_col, max_col + 1):
                            val_h = ws.cell(row=min_row, column=c_idx).value
                            nom_col = str(val_h or f"Columna_{c_idx}").strip()
                            columnas_tbl.append(ColumnaTabla(indice_col=c_idx, nombre=nom_col))

                        tabla_obj = TablaExcel(
                            nombre=str(tbl_name),
                            hoja=nombre_hoja,
                            rango_ref=str(ref),
                            fila_encabezados=min_row,
                            fila_inicio_datos=min_row + 1,
                            fila_fin_datos=max_row,
                            col_inicio=min_col,
                            col_fin=max_col,
                            columnas=columnas_tbl,
                            es_tabla_formal=True,
                        )
                        resultado.tablas.append(tabla_obj)
                    except Exception:
                        pass


        # 3.3 Validaciones de datos (ws.data_validations)
        if hasattr(ws, "data_validations") and ws.data_validations:
            for dv in ws.data_validations.dataValidation:
                tipo_dv = dv.type or "custom"
                opciones = []
                f1 = dv.formula1
                f2 = dv.formula2

                # Si es lista tipo "Opcion1,Opcion2"
                if tipo_dv == "list" and f1:
                    clean_f1 = str(f1).strip()
                    if clean_f1.startswith('"') and clean_f1.endswith('"'):
                        clean_f1 = clean_f1[1:-1]
                    opciones = [opt.strip() for opt in clean_f1.split(",") if opt.strip()]

                regla = ReglaValidacionCelda(
                    tipo=tipo_dv,
                    opciones_permitidas=opciones,
                    formula1=f1,
                    formula2=f2,
                    permite_blanco=bool(dv.allow_blank),
                    mensaje_error=dv.error,
                )

                # Mapear cada celda cubierta por el sqref
                for sq in dv.sqref.ranges:
                    for r_val in range(sq.min_row, sq.max_row + 1):
                        for c_val in range(sq.min_col, sq.max_col + 1):
                            resultado.validaciones_por_celda[(nombre_hoja, r_val, c_val)] = regla
            resultado.validaciones_firma[nombre_hoja] = tuple(sorted(
                (str(dv.type or "custom"), str(dv.formula1 or ""), str(dv.sqref or ""))
                for dv in ws.data_validations.dataValidation
            ))

        # 3.4 Celdas: Fórmulas, Valores existentes y Protección
        for row in ws.iter_rows():
            for cell in row:
                r_idx = cell.row
                c_idx = cell.column
                v = cell.value
                if cell.has_style:
                    resultado.estilos_firma[(nombre_hoja, r_idx, c_idx)] = int(cell.style_id)

                # A. Detección de Fórmulas
                es_formula = (
                    cell.data_type == "f" or 
                    (v is not None and isinstance(v, str) and v.startswith("="))
                )
                if es_formula:
                    resultado.celdas_con_formula[(nombre_hoja, r_idx, c_idx)] = str(v)
                    resultado.formulas_firma[(nombre_hoja, r_idx, c_idx)] = str(v)

                # B. Valores existentes no-fórmula
                if v is not None and not es_formula:
                    v_str = str(v).strip()
                    if v_str != "":
                        resultado.valores_existentes[(nombre_hoja, r_idx, c_idx)] = v

                # C. Celdas protegidas/bloqueadas
                if hoja_protegida:
                    # En Excel protegido, las celdas son bloqueadas por defecto salvo que cell.protection.locked sea False
                    if cell.protection is None or cell.protection.locked:
                        resultado.celdas_protegidas.add((nombre_hoja, r_idx, c_idx))

        resultado.tablas_firma[nombre_hoja] = tuple(sorted(
            (str(nombre), str(getattr(tabla, "ref", tabla))) for nombre, tabla in ws.tables.items()
        ))
    return resultado
