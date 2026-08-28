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


def aplanar_perfil(datos: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte un perfil con taxonomía jerárquica a un diccionario plano con claves estándar."""
    plano: Dict[str, Any] = {}

    def _extraer(d: Any, prefijo: str = "") -> None:
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, dict):
                    _extraer(v, prefijo)
                else:
                    plano[k] = v
                    if prefijo:
                        plano[f"{prefijo}.{k}"] = v

    # Extraer datos de las 3 ramas principales
    if "empresa" in datos or "representante_legal" in datos or "financiero" in datos:
        if "empresa" in datos:
            _extraer(datos["empresa"], "empresa")
        if "representante_legal" in datos:
            _extraer(datos["representante_legal"], "representante_legal")
        if "financiero" in datos:
            _extraer(datos["financiero"], "financiero")
        # Mantener claves adicionales que puedan estar en la raíz
        for k, v in datos.items():
            if k not in ("empresa", "representante_legal", "financiero") and not isinstance(v, dict):
                plano[k] = v
    else:
        # Ya es plano
        plano = dict(datos)

    # Generación dinámica de representante_legal, nombres y apellidos
    rep_full = str(plano.get("representante_legal", "")).strip()
    rep_nom = str(plano.get("representante_nombres", "")).strip()
    rep_ape = str(plano.get("representante_apellidos", "")).strip()

    if not rep_full and (rep_nom or rep_ape):
        plano["representante_legal"] = f"{rep_nom} {rep_ape}".strip()
    elif rep_full:
        partes = rep_full.split()
        if not rep_nom:
            plano["representante_nombres"] = " ".join(partes[:-2]) if len(partes) > 2 else (partes[0] if partes else rep_full)
        if not rep_ape:
            plano["representante_apellidos"] = " ".join(partes[-2:]) if len(partes) >= 2 else ""

    # Compatibilidad bidireccional lugar_expedicion <-> expedicion
    if "lugar_expedicion" in plano and plano["lugar_expedicion"]:
        plano["expedicion"] = plano["lugar_expedicion"]
    elif "expedicion" in plano and plano["expedicion"]:
        plano["lugar_expedicion"] = plano["expedicion"]

    # Generación compuesta ciudad_departamento ("Ciudad/Departamento", ej. "Medellin/Antioquia")
    c_val = str(plano.get("ciudad", "")).strip()
    d_val = str(plano.get("departamento", "")).strip()
    if c_val and d_val:
        plano["ciudad_departamento"] = f"{c_val}/{d_val}"
    elif c_val:
        plano["ciudad_departamento"] = c_val
    elif d_val:
        plano["ciudad_departamento"] = d_val

    return plano


def estructurar_perfil_taxonomia(datos: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte un perfil plano o semiestructurado en la taxonomía semántica estándar de 3 niveles."""
    plano = aplanar_perfil(datos)

    return {
        "empresa": {
            "identidad": {
                "razon_social": str(plano.get("razon_social", "")),
                "nit": str(plano.get("nit", "")),
                "tipo_sociedad": str(plano.get("tipo_sociedad", "S.A.S")),
            },
            "ubicacion": {
                "direccion": str(plano.get("direccion", "")),
                "ciudad": str(plano.get("ciudad", "")),
                "departamento": str(plano.get("departamento", "")),
                "pais": str(plano.get("pais", "Colombia")),
            },
            "contacto": {
                "telefono": str(plano.get("telefono", "")),
                "pagina_web": str(plano.get("pagina_web", "")),
            }
        },
        "representante_legal": {
            "identidad": {
                "representante_legal": str(plano.get("representante_legal", "")),
                "representante_nombres": str(plano.get("representante_nombres", "")),
                "representante_apellidos": str(plano.get("representante_apellidos", "")),
                "tipo_documento": str(plano.get("tipo_documento", "C.C.")),
                "cedula": str(plano.get("cedula", "")),
                "lugar_expedicion": str(plano.get("lugar_expedicion") or plano.get("expedicion", "")),
            },
            "contacto": {
                "correo": str(plano.get("correo_representante") or plano.get("correo", "")),
                "telefono": str(plano.get("telefono_representante") or plano.get("telefono", "")),
                "celular": str(plano.get("celular") or plano.get("celular_representante", "")),
            }
        },
        "financiero": {
            "banco": {
                "banco": str(plano.get("banco", "")),
                "sucursal": str(plano.get("sucursal", "")),
            },
            "cuenta": {
                "numero_cuenta": str(plano.get("numero_cuenta", "")),
                "tipo_cuenta": str(plano.get("tipo_cuenta", "AHORROS")),
            }
        }
    }


def cargar_perfil(ruta: Union[Path, str]) -> Dict[str, Any]:
    """Carga los datos JSON del perfil especificado (aplana o estructura según necesidad)."""
    ruta = Path(ruta)
    if not ruta.exists():
        return _obtener_plantilla_vacia()
    
    try:
        with ruta.open("r", encoding="utf-8-sig") as f:
            datos_raw = json.load(f)
        return aplanar_perfil(datos_raw)
    except Exception as exc:
        print(f"[AutoForm AI] Error cargando perfil {ruta}: {exc}")
        return _obtener_plantilla_vacia()


def guardar_perfil(ruta: Path, datos: Dict[str, Any]) -> bool:
    """Guarda los datos empresariales estructurados en taxonomía semántica en el archivo JSON."""
    asegurar_directorio_config()
    try:
        taxonomia = estructurar_perfil_taxonomia(datos)
        with ruta.open("w", encoding="utf-8") as f:
            json.dump(taxonomia, f, indent=2, ensure_ascii=False)
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
        "tipo_documento": "C.C.",
        "cedula": "",
        "lugar_expedicion": "",
        "expedicion": "",
        "ciudad": "",
        "departamento": "",
        "pagina_web": "",
        "representante_legal": "",
        "representante_nombres": "",
        "representante_apellidos": "",
        "celular": "",
        "pais": "Colombia",
        "banco": "",
        "numero_cuenta": "",
        "tipo_cuenta": "AHORROS",
        "sucursal": "",
    }
