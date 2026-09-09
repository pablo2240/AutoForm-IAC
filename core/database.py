"""Módulo de persistencia canónica en SQLite para AutoForm AI.

Define SQLite (`config/empresa.db`) como la Fuente Única de Verdad (Single Source of Truth)
para los perfiles empresariales, garantizando transacciones ACID y resiliencia ante reinicios.
"""

from __future__ import annotations

import json
import os
import re
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
    """Crea la estructura de tablas e índices si no existen y siembra datos iniciales."""
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

        # ADR-0007: Catálogo independiente de operadores/comerciales
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS operadores (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                cargo TEXT,
                cedula TEXT,
                telefono TEXT,
                correo TEXT,
                direccion TEXT DEFAULT '',
                ciudad TEXT DEFAULT '',
                es_activo INTEGER DEFAULT 0,
                actualizado_en TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_operadores_activo
            ON operadores (es_activo);
            """
        )

        # Migración dinámica de columnas direccion y ciudad si no existen en operadores
        cursor.execute("PRAGMA table_info(operadores)")
        cols_op = {row["name"] for row in cursor.fetchall()}
        if "direccion" not in cols_op:
            cursor.execute("ALTER TABLE operadores ADD COLUMN direccion TEXT DEFAULT ''")
        if "ciudad" not in cols_op:
            cursor.execute("ALTER TABLE operadores ADD COLUMN ciudad TEXT DEFAULT ''")

        # Sembrar operador predeterminado inicial si la tabla está vacía
        cursor.execute("SELECT COUNT(*) AS total FROM operadores")
        fila_count = cursor.fetchone()
        if fila_count and fila_count["total"] == 0:
            ahora = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT INTO operadores (id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_activo, actualizado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    "antonio_prieto",
                    "Antonio Prieto",
                    "Asesor Comercial / Aplicaciones",
                    "",
                    "",
                    "antonio.prieto@iaclatam.com",
                    "Carrera 63 B # 32 E -25 OFC 206",
                    "Bogotá",
                    ahora,
                ),
            )

        # ADR-0008: Tabla canónica de usuarios autenticados
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                cargo TEXT,
                cedula TEXT,
                telefono TEXT,
                correo TEXT UNIQUE NOT NULL,
                direccion TEXT DEFAULT '',
                ciudad TEXT DEFAULT '',
                password_hash TEXT NOT NULL,
                es_admin INTEGER DEFAULT 0,
                activo INTEGER DEFAULT 1,
                creado_en TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_usuarios_correo
            ON usuarios (correo);
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_usuarios_activo
            ON usuarios (activo);
            """
        )

        # Migración dinámica de columnas direccion y ciudad si no existen en usuarios
        cursor.execute("PRAGMA table_info(usuarios)")
        cols_usr = {row["name"] for row in cursor.fetchall()}
        if "direccion" not in cols_usr:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN direccion TEXT DEFAULT ''")
        if "ciudad" not in cols_usr:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN ciudad TEXT DEFAULT ''")

        # ADR-0008: Sembrar usuario administrador inicial si la tabla usuarios está vacía
        cursor.execute("SELECT COUNT(*) AS total FROM usuarios")
        fila_user_count = cursor.fetchone()
        if fila_user_count and fila_user_count["total"] == 0:
            from core.auth_manager import hashear_password
            admin_pwd = os.environ.get("AUTOFORM_ADMIN_PASSWORD", "IAC2026*")
            ahora = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT INTO usuarios (id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, password_hash, es_admin, activo, creado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?)
                """,
                (
                    "antonio_prieto",
                    "Antonio Prieto",
                    "Asesor Comercial / Aplicaciones",
                    "",
                    "",
                    "antonio.prieto@iaclatam.com",
                    "Carrera 63 B # 32 E -25 OFC 206",
                    "Bogotá",
                    hashear_password(admin_pwd),
                    ahora,
                ),
            )

        # Migración automática de semilla de Antonio Prieto a @iaclatam.com y asignación de dirección y ciudad por defecto
        cursor.execute("UPDATE operadores SET correo = 'antonio.prieto@iaclatam.com' WHERE id = 'antonio_prieto' AND correo = 'antonio.prieto@iac.com.co'")
        cursor.execute("UPDATE usuarios SET correo = 'antonio.prieto@iaclatam.com' WHERE id = 'antonio_prieto' AND correo = 'antonio.prieto@iac.com.co'")
        cursor.execute("UPDATE operadores SET direccion = 'Carrera 63 B # 32 E -25 OFC 206', ciudad = 'Bogotá' WHERE id = 'antonio_prieto' AND (direccion IS NULL OR direccion = '')")
        cursor.execute("UPDATE usuarios SET direccion = 'Carrera 63 B # 32 E -25 OFC 206', ciudad = 'Bogotá' WHERE id = 'antonio_prieto' AND (direccion IS NULL OR direccion = '')")

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


# ──────────────────────────────────────────────────────────────────────────────
# ADR-0007: GESTIÓN DE OPERADORES Y COMERCIALES (SQLITE CANÓNICO)
# ──────────────────────────────────────────────────────────────────────────────

def guardar_operador_db(
    id_operador: str,
    nombre: str,
    cargo: str = "",
    cedula: str = "",
    telefono: str = "",
    correo: str = "",
    direccion: str = "",
    ciudad: str = "",
    es_activo: Optional[bool] = None,
) -> bool:
    """Guarda o actualiza un operador comercial en SQLite.

    Args:
        id_operador: Slug único (ej. 'antonio_prieto').
        nombre: Nombre completo del operador.
        cargo: Cargo en la empresa (ej. 'Asesor Comercial').
        cedula: Documento de identidad del operador.
        telefono: Celular o teléfono directo.
        correo: Correo corporativo del operador.
        direccion: Dirección de contacto del operador.
        ciudad: Ciudad de ubicación del operador.
        es_activo: Si es True, marca este operador como el activo y desmarca los demás.
    """
    inicializar_db()
    id_limpio = id_operador.strip().lower()
    nombre_limpio = nombre.strip()
    ahora_iso = datetime.now(timezone.utc).isoformat()

    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()

            if es_activo is True:
                cursor.execute("UPDATE operadores SET es_activo = 0")
                activo_val = 1
            elif es_activo is False:
                activo_val = 0
            else:
                activo_val = None

            cursor.execute("SELECT id, es_activo FROM operadores WHERE id = ?", (id_limpio,))
            fila_existente = cursor.fetchone()

            if fila_existente:
                if activo_val is None:
                    activo_val = fila_existente["es_activo"]
                cursor.execute(
                    """
                    UPDATE operadores
                    SET nombre = ?, cargo = ?, cedula = ?, telefono = ?, correo = ?, direccion = ?, ciudad = ?, es_activo = ?, actualizado_en = ?
                    WHERE id = ?
                    """,
                    (nombre_limpio, cargo.strip(), cedula.strip(), telefono.strip(), correo.strip(), direccion.strip(), ciudad.strip(), activo_val, ahora_iso, id_limpio),
                )
            else:
                if activo_val is None:
                    # Si es el primer operador creado, activarlo por defecto
                    cursor.execute("SELECT COUNT(*) as total FROM operadores")
                    c_row = cursor.fetchone()
                    activo_val = 1 if (c_row and c_row["total"] == 0) else 0

                cursor.execute(
                    """
                    INSERT INTO operadores (id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_activo, actualizado_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (id_limpio, nombre_limpio, cargo.strip(), cedula.strip(), telefono.strip(), correo.strip(), direccion.strip(), ciudad.strip(), activo_val, ahora_iso),
                )

            # Sincronización bidireccional automática con la tabla usuarios si el operador tiene cuenta de usuario
            correo_limpio = correo.strip().lower()
            correo_alt = ""
            if correo_limpio.endswith("@iac.com.co"):
                correo_alt = correo_limpio.replace("@iac.com.co", "@iaclatam.com")
            elif correo_limpio.endswith("@iaclatam.com"):
                correo_alt = correo_limpio.replace("@iaclatam.com", "@iac.com.co")

            cursor.execute(
                """
                UPDATE usuarios
                SET nombre = ?, cargo = ?, cedula = ?, telefono = ?, correo = ?, direccion = ?, ciudad = ?
                WHERE id = ? OR LOWER(correo) = ? OR (LOWER(correo) = ? AND ? != '')
                """,
                (nombre_limpio, cargo.strip(), cedula.strip(), telefono.strip(), correo.strip(), direccion.strip(), ciudad.strip(), id_limpio, correo_limpio, correo_alt, correo_alt),
            )

            conn.commit()
            return True
    except Exception as exc:
        print(f"[AutoForm AI DB] Error guardando operador '{id_operador}' en SQLite: {exc}")
        return False


def listar_operadores_db() -> List[Dict[str, Any]]:
    """Devuelve la lista completa de operadores registrados en SQLite."""
    inicializar_db()
    operadores = []
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_activo, actualizado_en
                FROM operadores
                ORDER BY es_activo DESC, nombre ASC
                """
            )
            for row in cursor.fetchall():
                operadores.append({
                    "id": str(row["id"]),
                    "nombre": str(row["nombre"]),
                    "cargo": str(row["cargo"] or ""),
                    "cedula": str(row["cedula"] or ""),
                    "telefono": str(row["telefono"] or ""),
                    "correo": str(row["correo"] or ""),
                    "direccion": str(row["direccion"] or ""),
                    "ciudad": str(row["ciudad"] or ""),
                    "es_activo": bool(row["es_activo"]),
                    "actualizado_en": str(row["actualizado_en"]),
                })
    except Exception as exc:
        print(f"[AutoForm AI DB] Error listando operadores en SQLite: {exc}")
    return operadores


def obtener_operador_db(id_operador: str) -> Optional[Dict[str, Any]]:
    """Obtiene un operador específico por su identificador único."""
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_activo, actualizado_en
                FROM operadores
                WHERE id = ?
                """,
                (id_operador.strip().lower(),),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": str(row["id"]),
                    "nombre": str(row["nombre"]),
                    "cargo": str(row["cargo"] or ""),
                    "cedula": str(row["cedula"] or ""),
                    "telefono": str(row["telefono"] or ""),
                    "correo": str(row["correo"] or ""),
                    "direccion": str(row["direccion"] or ""),
                    "ciudad": str(row["ciudad"] or ""),
                    "es_activo": bool(row["es_activo"]),
                    "actualizado_en": str(row["actualizado_en"]),
                }
    except Exception as exc:
        print(f"[AutoForm AI DB] Error obteniendo operador '{id_operador}': {exc}")
    return None


def obtener_operador_activo_db() -> Optional[Dict[str, Any]]:
    """Devuelve el operador actualmente marcado como activo en SQLite."""
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_activo, actualizado_en
                FROM operadores
                WHERE es_activo = 1
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": str(row["id"]),
                    "nombre": str(row["nombre"]),
                    "cargo": str(row["cargo"] or ""),
                    "cedula": str(row["cedula"] or ""),
                    "telefono": str(row["telefono"] or ""),
                    "correo": str(row["correo"] or ""),
                    "direccion": str(row["direccion"] or ""),
                    "ciudad": str(row["ciudad"] or ""),
                    "es_activo": True,
                    "actualizado_en": str(row["actualizado_en"]),
                }
    except Exception as exc:
        print(f"[AutoForm AI DB] Error obteniendo operador activo: {exc}")
    return None


def activar_operador_db(id_operador: str) -> bool:
    """Marca un operador como activo y desmarca a los demás."""
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE operadores SET es_activo = 0")
            cursor.execute("UPDATE operadores SET es_activo = 1 WHERE id = ?", (id_operador.strip().lower(),))
            conn.commit()
            return cursor.rowcount > 0
    except Exception as exc:
        print(f"[AutoForm AI DB] Error activando operador '{id_operador}': {exc}")
        return False


def eliminar_operador_db(id_operador: str) -> bool:
    """Elimina un operador de SQLite."""
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM operadores WHERE id = ?", (id_operador.strip().lower(),))
            conn.commit()
            return True
    except Exception as exc:
        print(f"[AutoForm AI DB] Error eliminando operador '{id_operador}': {exc}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# ADR-0008: GESTIÓN DE USUARIOS Y AUTENTICACIÓN (SQLITE CANÓNICO)
# ──────────────────────────────────────────────────────────────────────────────

def crear_usuario_db(
    nombre: str,
    correo: str,
    password: str,
    cargo: str = "",
    cedula: str = "",
    telefono: str = "",
    direccion: str = "Carrera 63 B # 32 E -25 OFC 206",
    ciudad: str = "Bogotá",
    es_admin: int = 0,
) -> Tuple[bool, str]:
    """Registra un nuevo usuario en SQLite tras hashear su contraseña.

    Returns:
        Tuple[bool, str]: (exito, mensaje_o_id)
    """
    from core.auth_manager import hashear_password, validar_dominio_corporativo, validar_formato_correo

    inicializar_db()
    correo_limpio = correo.strip().lower()
    nombre_limpio = nombre.strip()

    if not nombre_limpio:
        return False, "El nombre completo es obligatorio."
    if not validar_formato_correo(correo_limpio):
        return False, "El formato de correo no es válido."
    if not validar_dominio_corporativo(correo_limpio):
        return False, "Registro no autorizado. Utiliza un correo corporativo de la empresa."
    if not password or len(password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."

    slug_id = re.sub(r"[^\w]+", "_", correo_limpio.split("@")[0]).strip("_")
    pwd_hash = hashear_password(password)
    ahora_iso = datetime.now(timezone.utc).isoformat()

    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO usuarios (id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, password_hash, es_admin, activo, creado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (slug_id, nombre_limpio, cargo.strip(), cedula.strip(), telefono.strip(), correo_limpio, direccion.strip(), ciudad.strip(), pwd_hash, int(es_admin), ahora_iso),
            )
            # También sincronizar en operadores para compatibilidad
            cursor.execute(
                """
                INSERT INTO operadores (id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_activo, actualizado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(id) DO UPDATE SET
                    nombre = excluded.nombre,
                    cargo = excluded.cargo,
                    cedula = excluded.cedula,
                    telefono = excluded.telefono,
                    correo = excluded.correo,
                    direccion = excluded.direccion,
                    ciudad = excluded.ciudad,
                    actualizado_en = excluded.actualizado_en
                """,
                (slug_id, nombre_limpio, cargo.strip(), cedula.strip(), telefono.strip(), correo_limpio, direccion.strip(), ciudad.strip(), ahora_iso),
            )
            conn.commit()
            return True, slug_id
    except sqlite3.IntegrityError:
        return False, "Ya existe una cuenta registrada con este correo electrónico."
    except Exception as exc:
        return False, f"Error al registrar usuario: {exc}"


def obtener_usuario_por_correo_db(correo: str) -> Optional[Dict[str, Any]]:
    """Obtiene un usuario por su correo electrónico (con soporte a variantes @iaclatam.com / @iac.com.co)."""
    inicializar_db()
    correo_limpio = correo.strip().lower()
    correo_alt = ""
    if correo_limpio.endswith("@iac.com.co"):
        correo_alt = correo_limpio.replace("@iac.com.co", "@iaclatam.com")
    elif correo_limpio.endswith("@iaclatam.com"):
        correo_alt = correo_limpio.replace("@iaclatam.com", "@iac.com.co")

    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, password_hash, es_admin, activo, creado_en
                FROM usuarios
                WHERE (LOWER(correo) = ? OR (LOWER(correo) = ? AND ? != '')) AND activo = 1
                LIMIT 1
                """,
                (correo_limpio, correo_alt, correo_alt),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": str(row["id"]),
                    "nombre": str(row["nombre"]),
                    "cargo": str(row["cargo"] or ""),
                    "cedula": str(row["cedula"] or ""),
                    "telefono": str(row["telefono"] or ""),
                    "correo": str(row["correo"]),
                    "direccion": str(row["direccion"] or "Carrera 63 B # 32 E -25 OFC 206"),
                    "ciudad": str(row["ciudad"] or "Bogotá"),
                    "password_hash": str(row["password_hash"]),
                    "es_admin": bool(row["es_admin"]),
                    "activo": bool(row["activo"]),
                    "creado_en": str(row["creado_en"]),
                }
    except Exception as exc:
        print(f"[AutoForm AI DB] Error al buscar usuario por correo '{correo}': {exc}")
    return None


def autenticar_usuario_db(correo: str, password: str) -> Optional[Dict[str, Any]]:
    """Verifica credenciales del usuario contra el hash en base de datos.

    Returns:
        Dict con los datos del usuario autenticado (sin el hash) o None si falla.
    """
    from core.auth_manager import verificar_password

    usuario = obtener_usuario_por_correo_db(correo)
    if not usuario:
        return None

    if verificar_password(password, usuario["password_hash"]):
        datos_seguros = dict(usuario)
        del datos_seguros["password_hash"]
        return datos_seguros

    return None


def listar_usuarios_db() -> List[Dict[str, Any]]:
    """Devuelve la lista de usuarios para administración."""
    inicializar_db()
    usuarios = []
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_admin, activo, creado_en
                FROM usuarios
                ORDER BY es_admin DESC, nombre ASC
                """
            )
            for row in cursor.fetchall():
                usuarios.append({
                    "id": str(row["id"]),
                    "nombre": str(row["nombre"]),
                    "cargo": str(row["cargo"] or ""),
                    "cedula": str(row["cedula"] or ""),
                    "telefono": str(row["telefono"] or ""),
                    "correo": str(row["correo"]),
                    "direccion": str(row["direccion"] or ""),
                    "ciudad": str(row["ciudad"] or ""),
                    "es_admin": bool(row["es_admin"]),
                    "activo": bool(row["activo"]),
                    "creado_en": str(row["creado_en"]),
                })
    except Exception as exc:
        print(f"[AutoForm AI DB] Error listando usuarios: {exc}")
    return usuarios


