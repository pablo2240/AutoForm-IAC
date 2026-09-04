"""Módulo de gestión de perfiles empresariales (Fase 2 UI/UX).

Permite listar, cargar, crear y editar perfiles de datos empresariales JSON desde la interfaz de usuario.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
PROFILE_DEFAULT_PATH = CONFIG_DIR / "datos_empresa.json"
ACTIVE_PROFILE_FILE = CONFIG_DIR / "perfil_activo.txt"


from core import database


def asegurar_directorio_config() -> None:
    """Garantiza que la carpeta config/ exista."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def sincronizar_db_con_archivos() -> None:
    """Garantiza la consistencia inicial entre SQLite (fuente canónica) y los archivos JSON en config/."""
    asegurar_directorio_config()
    database.inicializar_db()

    perfiles_db = database.listar_perfiles_db()
    ids_db = {p["id"] for p in perfiles_db}

    # 1. Si la base de datos no tiene el perfil principal, sembrar desde config/datos_empresa.json
    if "principal" not in ids_db:
        if PROFILE_DEFAULT_PATH.exists():
            try:
                with PROFILE_DEFAULT_PATH.open("r", encoding="utf-8-sig") as f:
                    datos_raw = json.load(f)
                taxonomia = estructurar_perfil_taxonomia(datos_raw)
                database.guardar_perfil_db("principal", "🏢 Principal (IAC Latam)", taxonomia, es_activo=True)
            except Exception as exc:
                print(f"[AutoForm AI] Error sembrando datos iniciales en SQLite: {exc}")
        else:
            plantilla = _obtener_plantilla_vacia()
            taxonomia = estructurar_perfil_taxonomia(plantilla)
            database.guardar_perfil_db("principal", "🏢 Principal (IAC Latam)", taxonomia, es_activo=True)
            try:
                with PROFILE_DEFAULT_PATH.open("w", encoding="utf-8") as f:
                    json.dump(taxonomia, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    # 2. Sembrar perfiles secundarios JSON que no existan en SQLite
    for archivo in CONFIG_DIR.glob("datos_empresa_*.json"):
        slug = archivo.stem.replace("datos_empresa_", "").lower().strip()
        if slug and slug not in ids_db:
            try:
                nombre_base = slug.replace("_", " ").title()
                etiqueta = f"🏢 {nombre_base}"
                with archivo.open("r", encoding="utf-8-sig") as f:
                    datos_raw = json.load(f)
                taxonomia = estructurar_perfil_taxonomia(datos_raw)
                database.guardar_perfil_db(slug, etiqueta, taxonomia, es_activo=False)
            except Exception as exc:
                print(f"[AutoForm AI] Error migrando archivo {archivo} a SQLite: {exc}")

    # 3. Si SQLite tiene perfiles cuyos archivos JSON espejo no existen en disco, generarlos
    for p in database.listar_perfiles_db():
        pid = p["id"]
        ruta_esperada = PROFILE_DEFAULT_PATH if pid == "principal" else CONFIG_DIR / f"datos_empresa_{pid}.json"
        if not ruta_esperada.exists():
            try:
                taxonomia = estructurar_perfil_taxonomia(p["datos"])
                with ruta_esperada.open("w", encoding="utf-8") as f:
                    json.dump(taxonomia, f, indent=2, ensure_ascii=False)
            except Exception as exc:
                print(f"[AutoForm AI Warning] No se pudo crear archivo espejo {ruta_esperada}: {exc}")


def obtener_perfil_activo_guardado() -> str:
    """Lee el nombre del último perfil activo desde SQLite o config/perfil_activo.txt."""
    sincronizar_db_con_archivos()
    perfil_db = database.obtener_perfil_activo_db()
    if perfil_db:
        return perfil_db[1]  # nombre
    if ACTIVE_PROFILE_FILE.exists():
        try:
            nombre = ACTIVE_PROFILE_FILE.read_text(encoding="utf-8").strip()
            if nombre:
                return nombre
        except Exception:
            pass
    return "🏢 Principal (IAC Latam)"


def guardar_perfil_activo_seleccionado(nombre_etiqueta: str) -> None:
    """Persiste en SQLite y en perfil_activo.txt el perfil actualmente activo."""
    asegurar_directorio_config()
    database.establecer_perfil_activo_db(nombre_etiqueta)
    try:
        ACTIVE_PROFILE_FILE.write_text(nombre_etiqueta.strip(), encoding="utf-8")
    except Exception as exc:
        print(f"[AutoForm AI Warning] Error guardando perfil activo en txt: {exc}")


def _slugify(texto: str) -> str:
    """Convierte un nombre de perfil a un identificador seguro para nombre de archivo."""
    texto_limpio = texto.lower().strip()
    texto_limpio = re.sub(r"[^\w\s-]", "", texto_limpio)
    return re.sub(r"[-\s]+", "_", texto_limpio)


def listar_perfiles() -> Dict[str, Path]:
    """Devuelve diccionario {NombrePerfil: Path} garantizando consistencia con SQLite y JSON."""
    sincronizar_db_con_archivos()
    perfiles: Dict[str, Path] = {}

    for p in database.listar_perfiles_db():
        pid = p["id"]
        nombre = p["nombre"]
        ruta = PROFILE_DEFAULT_PATH if pid == "principal" else CONFIG_DIR / f"datos_empresa_{pid}.json"
        perfiles[nombre] = ruta

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

    # Extraer datos de las 3 ramas principales si son diccionarios anidados
    es_jerarquico = any(
        isinstance(datos.get(k), dict)
        for k in ("empresa", "representante_legal", "financiero")
    )
    if es_jerarquico:
        if isinstance(datos.get("empresa"), dict):
            _extraer(datos["empresa"], "empresa")
        if isinstance(datos.get("representante_legal"), dict):
            _extraer(datos["representante_legal"], "representante_legal")
        if isinstance(datos.get("financiero"), dict):
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


def _extraer_slug_y_ruta(ruta_o_id: Union[Path, str], nombre_sugerido: str = "") -> Tuple[str, Path, str]:
    """Determina el slug, la ruta de archivo espejo y el nombre legible del perfil."""
    slug = "principal"
    ruta_archivo = PROFILE_DEFAULT_PATH
    nombre = nombre_sugerido.strip() if nombre_sugerido else ""

    if isinstance(ruta_o_id, Path) or ("/" in str(ruta_o_id) or "\\" in str(ruta_o_id)):
        ruta_archivo = Path(ruta_o_id)
        stem = ruta_archivo.stem.lower()
        if stem == "datos_empresa":
            slug = "principal"
            if not nombre:
                nombre = "🏢 Principal (IAC Latam)"
        elif stem.startswith("datos_empresa_"):
            slug = stem.replace("datos_empresa_", "")
            if not nombre:
                nombre = f"🏢 {slug.replace('_', ' ').title()}"
        else:
            slug = _slugify(stem)
            if not nombre:
                nombre = f"🏢 {slug.replace('_', ' ').title()}"
    else:
        str_val = str(ruta_o_id).strip()
        slug = _slugify(str_val.replace("🏢", "").strip())
        if not slug or slug in ("principal", "iac_latam"):
            slug = "principal"
            ruta_archivo = PROFILE_DEFAULT_PATH
            if not nombre:
                nombre = "🏢 Principal (IAC Latam)"
        else:
            ruta_archivo = CONFIG_DIR / f"datos_empresa_{slug}.json"
            if not nombre:
                nombre = f"🏢 {slug.replace('_', ' ').title()}"

    if not nombre:
        nombre = "🏢 Principal (IAC Latam)" if slug == "principal" else f"🏢 {slug.replace('_', ' ').title()}"

    return slug, ruta_archivo, nombre


def cargar_perfil(ruta_o_id: Union[Path, str]) -> Dict[str, Any]:
    """Carga los datos del perfil desde SQLite (fuente canónica) con fallback a JSON."""
    sincronizar_db_con_archivos()
    slug, ruta_archivo, nombre = _extraer_slug_y_ruta(ruta_o_id)

    # 1. Leer de SQLite (fuente canónica primaria)
    datos_db = database.obtener_perfil_db(slug)
    if datos_db is not None:
        return aplanar_perfil(datos_db)

    # 2. Fallback a archivo JSON espejo si SQLite no lo tiene
    if ruta_archivo.exists():
        try:
            with ruta_archivo.open("r", encoding="utf-8-sig") as f:
                datos_raw = json.load(f)
            datos_planos = aplanar_perfil(datos_raw)
            taxonomia = estructurar_perfil_taxonomia(datos_planos)
            database.guardar_perfil_db(slug, nombre, taxonomia)
            return datos_planos
        except Exception as exc:
            print(f"[AutoForm AI] Error cargando perfil espejo {ruta_archivo}: {exc}")

    return _obtener_plantilla_vacia()


def guardar_perfil(ruta_o_id: Union[Path, str], datos: Dict[str, Any], nombre_visible: str = "") -> bool:
    """Guarda canónicamente en SQLite y proyecta el espejo en el archivo JSON.

    Protocolo estricto:
    1. Escribir en SQLite (fuente canónica). Si falla -> return False.
    2. Si SQLite OK -> escribir en archivo JSON espejo.
    3. Si JSON falla (bloqueo en Windows, permisos) -> log WARNING, pero NO revertir SQLite; return True.
    """
    asegurar_directorio_config()
    database.inicializar_db()
    slug, ruta_archivo, nombre = _extraer_slug_y_ruta(ruta_o_id, nombre_sugerido=nombre_visible)

    taxonomia = estructurar_perfil_taxonomia(datos)

    # 1. CANÓNICO: Escribir en SQLite (transaccional ACID)
    ok_sqlite = database.guardar_perfil_db(slug, nombre, taxonomia)
    if not ok_sqlite:
        print(f"[AutoForm AI] Error fatal: Falló la escritura canónica en SQLite para '{slug}'.")
        return False

    # 2 & 3. ESPEJO: Escribir en JSON con tolerancia a fallos de Windows
    try:
        with ruta_archivo.open("w", encoding="utf-8") as f:
            json.dump(taxonomia, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"[AutoForm AI Warning] Error al actualizar archivo espejo JSON '{ruta_archivo}': {exc}. SQLite permanece como fuente canónica.")

    return True


def auto_guardar_campo(
    ruta_o_id: Union[Path, str],
    campo: str,
    valor: Any,
    nombre_visible: str = "",
) -> bool:
    """Actualiza atómicamente un campo individual en SQLite y en el archivo espejo JSON."""
    datos_actuales = cargar_perfil(ruta_o_id)
    val_str = str(valor or "").strip()
    datos_actuales[campo] = val_str

    # Sincronizar campos simétricos
    if campo == "lugar_expedicion":
        datos_actuales["expedicion"] = val_str
    elif campo == "expedicion":
        datos_actuales["lugar_expedicion"] = val_str

    return guardar_perfil(ruta_o_id, datos_actuales, nombre_visible=nombre_visible)


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

    exito = guardar_perfil(ruta_nueva, datos, nombre_visible=etiqueta)
    if exito:
        guardar_perfil_activo_seleccionado(etiqueta)
    return exito, ruta_nueva, etiqueta


def importar_perfil_json(contenido_str: str, nombre_sugerido: str = "") -> Tuple[bool, Path, str]:
    """Importa un archivo JSON (plano o jerárquico) como perfil empresarial persistente.

    Returns:
        Tuple[exito, ruta_creada, etiqueta_perfil]
    """
    try:
        datos_cargados = json.loads(contenido_str)
        if not isinstance(datos_cargados, dict):
            return False, PROFILE_DEFAULT_PATH, ""
        
        datos_planos = aplanar_perfil(datos_cargados)
        nombre = nombre_sugerido.strip()
        if not nombre:
            nombre = str(datos_planos.get("razon_social") or "Importado").strip()
            if len(nombre) > 40:
                nombre = nombre[:40].strip()

        slug = _slugify(nombre)
        if not slug or slug == "principal":
            ruta_destino = PROFILE_DEFAULT_PATH
            etiqueta = "🏢 Principal (IAC Latam)"
        else:
            ruta_destino = CONFIG_DIR / f"datos_empresa_{slug}.json"
            etiqueta = f"🏢 {nombre.title()}"

        exito = guardar_perfil(ruta_destino, datos_planos, nombre_visible=etiqueta)
        if exito:
            guardar_perfil_activo_seleccionado(etiqueta)
        return exito, ruta_destino, etiqueta
    except Exception as exc:
        print(f"[AutoForm AI] Error importando perfil JSON: {exc}")
        return False, PROFILE_DEFAULT_PATH, ""


def obtener_perfil_para_descarga(ruta: Union[Path, str]) -> str:
    """Devuelve el contenido JSON formateado listo para descarga de respaldo."""
    ruta = Path(ruta)
    if ruta.exists():
        try:
            return ruta.read_text(encoding="utf-8")
        except Exception:
            pass
    datos = cargar_perfil(ruta)
    return json.dumps(estructurar_perfil_taxonomia(datos), indent=2, ensure_ascii=False)


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
