"""Configuración de la biblioteca de formularios de referencia."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Cambiar cuando cambie el formato del conocimiento extraído: fuerza el reprocesamiento.
EXTRACTOR_VERSION = "1"
EXTENSIONES_SOPORTADAS = (".xlsx", ".xlsm")
NOMBRE_MANIFIESTO = "referencias.json"


def directorio_referencias() -> Path:
    """Carpeta que contiene los formularios de referencia (subcarpeta = familia)."""
    valor = os.getenv("AUTOFORM_REFERENCES_DIR", "").strip()
    return Path(valor) if valor else PROJECT_ROOT / "docs" / "referencias"


def ruta_base_conocimiento() -> Path:
    """Archivo SQLite derivado de la carpeta de referencias; puede reconstruirse en cualquier momento."""
    valor = os.getenv("AUTOFORM_REFERENCES_DB", "").strip()
    return Path(valor) if valor else PROJECT_ROOT / "config" / "referencias.db"
