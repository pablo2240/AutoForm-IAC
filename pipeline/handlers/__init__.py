"""Módulo de handlers especializados para hojas de cálculo Excel."""

from pipeline.handlers.document_detector import detectar_tipo_documento
from pipeline.handlers.excel_handler import ExcelHandler

__all__ = [
    "detectar_tipo_documento",
    "ExcelHandler",
]
