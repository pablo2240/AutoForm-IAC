"""Handler especializado para lectura y escritura en hojas de cálculo Excel (.xlsx)."""

from __future__ import annotations

import io
from typing import Any, Dict, List, Tuple, Union
import openpyxl
from core.excel_parser import escanear_mapa_formularios
from core.excel_writer import rellenar_formulario_excel


class ExcelHandler:
    """Maneja el escaneo y la inyección nativa de datos en archivos Excel."""

    @staticmethod
    def escanear(archivo_o_bytes: Union[bytes, io.BytesIO, openpyxl.Workbook]) -> List[Dict[str, Any]]:
        """Extrae el mapa estructural completo de celdas, merges y áreas de escritura."""
        if isinstance(archivo_o_bytes, openpyxl.Workbook):
            libro = archivo_o_bytes
        elif isinstance(archivo_o_bytes, (bytes, bytearray)):
            libro = openpyxl.load_workbook(filename=io.BytesIO(archivo_o_bytes), data_only=False)
        elif hasattr(archivo_o_bytes, "read"):
            archivo_o_bytes.seek(0)
            libro = openpyxl.load_workbook(filename=archivo_o_bytes, data_only=False)
        else:
            raise TypeError(f"Tipo no soportado para escanear Excel: {type(archivo_o_bytes)}")

        return escanear_mapa_formularios(libro)

    @staticmethod
    def inyectar(
        archivo_bytes: bytes,
        plan_mapeo: List[Dict[str, Any]],
        datos_empresa: Dict[str, Any],
    ) -> Tuple[bytes, List[Dict[str, Any]]]:
        """Escribe el plan de mapeo en el Excel preservando estilos, combinaciones y fuentes."""
        return rellenar_formulario_excel(
            bytes_excel=archivo_bytes,
            plan_mapeo=plan_mapeo,
            datos_empresa=datos_empresa,
        )
