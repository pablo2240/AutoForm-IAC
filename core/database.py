"""Módulo de persistencia canónica en SQLite para AutoForm AI.

Define SQLite (`config/empresa.db`) como la Fuente Única de Verdad (Single Source of Truth)
para los perfiles empresariales, garantizando transacciones ACID y resiliencia ante reinicios.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DB_PATH = CONFIG_DIR / "empresa.db"


def _asegurar_config_dir() -> None:
    """Garantiza la existencia del directorio config/."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def obtener_conexion() -> sqlite3.Connection:
    """Abre y devuelve una conexión a la base de datos SQLite corporativa."""
    _asegurar_config_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_db() -> None:
    """Crea la estructura de tablas e índices si no existen."""
    with obtener_conexion() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS perfiles_empresa (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                datos_json TEXT NOT NULL,
                es_activo INTEGER DEFAULT 0,
                actualizado_en TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_perfiles_activo
            ON perfiles_empresa (es_activo);
            """
        )
        conn.commit()


def guardar_perfil_db(
    id_perfil: str,
    nombre: str,
    datos: Dict[str, Any],
    es_activo: Optional[bool] = None,
) -> bool:
    """Guarda o actualiza de forma canónica un perfil empresarial en SQLite.

    Args:
        id_perfil: Slug único identificador (ej. 'principal', 'bogota').
        nombre: Etiqueta visible en la interfaz (ej. '🏢 Principal (IAC Latam)').
        datos: Diccionario de datos de la empresa (plano o estructurado).
        es_activo: Si es True, marca este perfil como activo y desmarca los demás.

    Returns:
        bool: True si la transacción SQLite se completó exitosamente.
    """
    inicializar_db()
    id_limpio = id_perfil.strip().lower()
    nombre_limpio = nombre.strip()
    datos_serializados = json.dumps(datos, ensure_ascii=False, indent=2)
    ahora_iso = datetime.now(timezone.utc).isoformat()

    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()

            if es_activo is True:
                cursor.execute("UPDATE perfiles_empresa SET es_activo = 0")
                activo_val = 1
            elif es_activo is False:
                activo_val = 0
            else:
                activo_val = None

            if activo_val is not None:
                cursor.execute(
                    """
                    INSERT INTO perfiles_empresa (id, nombre, datos_json, es_activo, actualizado_en)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        nombre = excluded.nombre,
                        datos_json = excluded.datos_json,
                        es_activo = excluded.es_activo,
                        actualizado_en = excluded.actualizado_en;
                    """,
                    (id_limpio, nombre_limpio, datos_serializados, activo_val, ahora_iso),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO perfiles_empresa (id, nombre, datos_json, es_activo, actualizado_en)
                    VALUES (?, ?, ?, 0, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        nombre = excluded.nombre,
                        datos_json = excluded.datos_json,
                        actualizado_en = excluded.actualizado_en;
                    """,
                    (id_limpio, nombre_limpio, datos_serializados, ahora_iso),
                )

            conn.commit()
            return True
    except Exception as exc:
        print(f"[AutoForm AI DB] Error fatal al guardar en SQLite perfil '{id_perfil}': {exc}")
        return False


def obtener_perfil_db(id_perfil: str) -> Optional[Dict[str, Any]]:
    """Recupera los datos de un perfil desde SQLite por su ID/slug."""
    inicializar_db()
    id_limpio = id_perfil.strip().lower()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT datos_json FROM perfiles_empresa WHERE id = ?",
                (id_limpio,),
            )
            row = cursor.fetchone()
            if row and row["datos_json"]:
                return json.loads(row["datos_json"])
    except Exception as exc:
        print(f"[AutoForm AI DB] Error al leer perfil '{id_perfil}' desde SQLite: {exc}")
    return None


def obtener_perfil_activo_db() -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Recupera el perfil marcado como activo en SQLite.

    Returns:
        Optional[Tuple[id, nombre, datos]]: Datos del perfil activo o None si no hay perfiles.
    """
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, nombre, datos_json FROM perfiles_empresa
                WHERE es_activo = 1
                ORDER BY actualizado_en DESC LIMIT 1
                """
            )
            row = cursor.fetchone()
            if not row:
                # Si ninguno está marcado con es_activo=1, tomar el más recientemente actualizado
                cursor.execute(
                    """
                    SELECT id, nombre, datos_json FROM perfiles_empresa
                    ORDER BY actualizado_en DESC LIMIT 1
                    """
                    )
                row = cursor.fetchone()

            if row:
                datos = json.loads(row["datos_json"]) if row["datos_json"] else {}
                return str(row["id"]), str(row["nombre"]), datos
    except Exception as exc:
        print(f"[AutoForm AI DB] Error al obtener perfil activo de SQLite: {exc}")
    return None


def establecer_perfil_activo_db(id_o_nombre: str) -> bool:
    """Marca un perfil como activo en SQLite desmarcando los demás."""
    inicializar_db()
    criterio = id_o_nombre.strip()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE perfiles_empresa SET es_activo = 0")
            cursor.execute(
                """
                UPDATE perfiles_empresa
                SET es_activo = 1
                WHERE id = ? OR nombre = ?
                """,
                (criterio.lower(), criterio),
            )
            conn.commit()
            return cursor.rowcount > 0
    except Exception as exc:
        print(f"[AutoForm AI DB] Error al establecer perfil activo '{id_o_nombre}': {exc}")
        return False


def listar_perfiles_db() -> List[Dict[str, Any]]:
    """Devuelve la lista completa de perfiles registrados en SQLite."""
    inicializar_db()
    perfiles = []
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, nombre, datos_json, es_activo, actualizado_en
                FROM perfiles_empresa
                ORDER BY (id = 'principal') DESC, nombre ASC
                """
            )
            for row in cursor.fetchall():
                perfiles.append({
                    "id": str(row["id"]),
                    "nombre": str(row["nombre"]),
                    "datos": json.loads(row["datos_json"]) if row["datos_json"] else {},
                    "es_activo": bool(row["es_activo"]),
                    "actualizado_en": str(row["actualizado_en"]),
                })
    except Exception as exc:
        print(f"[AutoForm AI DB] Error al listar perfiles desde SQLite: {exc}")
    return perfiles


def eliminar_perfil_db(id_perfil: str) -> bool:
    """Elimina un perfil secundario de SQLite (el perfil 'principal' no puede eliminarse)."""
    if id_perfil.lower().strip() == "principal":
        return False
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM perfiles_empresa WHERE id = ?", (id_perfil.lower().strip(),))
            conn.commit()
            return True
    except Exception as exc:
        print(f"[AutoForm AI DB] Error eliminando perfil '{id_perfil}' en SQLite: {exc}")
        return False
