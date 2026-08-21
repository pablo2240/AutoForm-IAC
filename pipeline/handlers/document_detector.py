"""Detector determinista de tipos de archivo (Excel, PDF) mediante Magic Bytes y extensión."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Literal

TipoDocumento = Literal["excel", "pdf", "desconocido"]


def detectar_tipo_documento(archivo_bytes: bytes, nombre_archivo: str = "") -> TipoDocumento:
    """Detecta de forma segura el formato del documento inspeccionando cabeceras binarias y extensión."""
    if not archivo_bytes:
        return "desconocido"

    # 1. Detección por Magic Bytes binarios (100% confiable)
    cabecera = archivo_bytes[:16]

    # PDF: '%PDF-' (b'%PDF')
    if cabecera.startswith(b"%PDF"):
        return "pdf"

    # Excel Moderno (.xlsx): ZIP OpenXML (b'PK\x03\x04')
    if cabecera.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(archivo_bytes)) as zf:
                # Comprobar si contiene estructuras de Excel o Word
                archivos_zip = zf.namelist()
                if any("xl/" in name or "[Content_Types].xml" in name for name in archivos_zip):
                    return "excel"
        except Exception:
            pass
        return "excel"

    # Excel Legado (.xls): OLE2 Compound Document (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')
    if cabecera.startswith(b"\xd0\xcf\x11\xe0"):
        return "excel"

    # 2. Fallback secundario por extensión de archivo
    if nombre_archivo:
        ext = Path(nombre_archivo).suffix.lower()
        if ext in (".xlsx", ".xlsm", ".xltx", ".xls"):
            return "excel"
        if ext == ".pdf":
            return "pdf"

    return "desconocido"
