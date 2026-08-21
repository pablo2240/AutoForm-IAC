"""Módulo de handlers especializados por formato de documento (Excel, PDF)."""

from pipeline.handlers.document_detector import detectar_tipo_documento
from pipeline.handlers.excel_handler import ExcelHandler
from pipeline.handlers.pdf_handler import PdfHandler

__all__ = [
    "detectar_tipo_documento",
    "ExcelHandler",
    "PdfHandler",
]
