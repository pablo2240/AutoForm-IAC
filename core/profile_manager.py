"""Módulo de gestión de perfiles empresariales (Fase 2 UI/UX).

Permite listar, cargar, crear y editar perfiles de datos empresariales JSON desde la interfaz de usuario.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


CONFIG_DIR = Path("config")
PROFILE_DEFAULT_PATH = CONFIG_DIR / "datos_empresa.json"


def asegurar_directorio_config() -> None:
    """Garantiza que la carpeta config/ exista."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(texto: str) -> str:
    """Convierte un nombre de perfil a un identificador seguro para nombre de archivo."""
    texto_limpio = texto.lower().strip()
    texto_limpio = re.sub(r"[^\w\s-]", "", texto_limpio)
    return re.sub(r"[-\s]+", "_", texto_limpio)


def listar_perfiles() -> Dict[str, Path]:
    """Escanea la carpeta config/ y devuelve un diccionario de perfiles {NombrePerfil: Path}."""
    asegurar_directorio_config()
    perfiles: Dict[str, Path] = {}

    # 1. Perfil Principal
    if PROFILE_DEFAULT_PATH.exists():
        perfiles["🏢 Principal (IAC Latam)"] = PROFILE_DEFAULT_PATH

    # 2. Perfiles Secundarios (config/datos_empresa_*.json)
    for archivo in CONFIG_DIR.glob("datos_empresa_*.json"):
        nombre_base = archivo.stem.replace("datos_empresa_", "").replace("_", " ").title()
        etiqueta = f"🏢 {nombre_base}"
        perfiles[etiqueta] = archivo

    # Fallback si no existe ninguno
    if not perfiles:
        perfiles["🏢 Principal (IAC Latam)"] = PROFILE_DEFAULT_PATH

    return perfiles


def cargar_perfil(ruta: Path) -> Dict[str, Any]:
    """Carga los datos JSON del perfil especificado."""
    if not ruta.exists():
        return _obtener_plantilla_vacia()

    try:
        with ruta.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[AutoForm AI] Error cargando perfil {ruta}: {exc}")
        return _obtener_plantilla_vacia()


def guardar_perfil(ruta: Path, datos: Dict[str, Any]) -> bool:
    """Guarda los datos empresariales en el archivo JSON indicado."""
    asegurar_directorio_config()
    try:
        with ruta.open("w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        return True
    except Exception as exc:
        print(f"[AutoForm AI] Error guardando perfil {ruta}: {exc}")
        return False


def crear_nuevo_perfil(nombre_perfil: str, datos: Dict[str, Any]) -> Tuple[bool, Path, str]:
    """Crea un nuevo perfil empresarial con el nombre dado.

    Returns:
        Tuple[exito, ruta_creada, etiqueta_perfil]
    """
    slug = _slugify(nombre_perfil)
    if not slug:
        slug = "secundario"

    nombre_archivo = f"datos_empresa_{slug}.json"
    ruta_nueva = CONFIG_DIR / nombre_archivo
    etiqueta = f"🏢 {nombre_perfil.strip()}"

    exito = guardar_perfil(ruta_nueva, datos)
    return exito, ruta_nueva, etiqueta


def _obtener_plantilla_vacia() -> Dict[str, Any]:
    """Devuelve un diccionario estructurado vacío para nuevos perfiles."""
    return {
        "razon_social": "",
        "nit": "",
        "direccion": "",
        "telefono": "",
        "correo": "",
        "cedula": "",
        "ciudad": "",
        "departamento": "",
        "pagina_web": "",
        "representante_legal": "",
        "representante_nombres": "",
        "representante_apellidos": "",
        "pais": "Colombia",
        "banco": "",
        "numero_cuenta": "",
        "tipo_cuenta": "AHORROS",
        "sucursal": "",
    }
