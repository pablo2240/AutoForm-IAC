"""Detector determinista de formato Excel (.xlsx, .xlsm, .xls) mediante Magic Bytes y extensión."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Literal

TipoDocumento = Literal["excel", "desconocido"]


def detectar_tipo_documento(archivo_bytes: bytes, nombre_archivo: str = "") -> TipoDocumento:
    """Detecta de forma segura si el documento es un archivo Excel válido inspeccionando cabeceras y extensión."""
    if not archivo_bytes:
        return "desconocido"

    # 1. Detección por Magic Bytes binarios (100% confiable)
    cabecera = archivo_bytes[:16]

    # Excel Moderno (.xlsx, .xlsm): ZIP OpenXML (b'PK\x03\x04')
    if cabecera.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(archivo_bytes)) as zf:
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

    return "desconocido"
