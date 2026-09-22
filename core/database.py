"""Módulo de persistencia canónica para AutoForm AI (ADR-0010).

En producción (APP_ENVIRONMENT=production), Supabase (PostgreSQL + Auth + RLS) es la Fuente
Única de Verdad (Single Source of Truth).
En desarrollo local (APP_ENVIRONMENT=development), se permite el uso de SQLite (config/empresa.db)
como respaldo de transición cuando USE_SQLITE=true.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = Any  # type: ignore

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DB_PATH = CONFIG_DIR / "empresa.db"


class ConfiguracionInvalidaError(Exception):
    """Excepción lanzada cuando faltan variables requeridas o la configuración es inválida."""
    pass


class SesionNoAutenticadaError(Exception):
    """Excepción lanzada cuando una operación protegida se ejecuta en producción sin sesión JWT."""
    pass


# ── DETECCIÓN DE ENTORNO Y FACTORÍA DE CLIENTES SUPABASE (ADR-0010 / Q2 / Q3 / Q4) ─

def es_modo_produccion() -> bool:
    """Indica si la aplicación se ejecuta en entorno de producción."""
    env = os.environ.get("APP_ENVIRONMENT", "production").strip().lower()
    return env == "production"


def es_modo_staging() -> bool:
    """Indica si la aplicación se ejecuta en entorno explícito de staging."""
    env = os.environ.get("APP_ENVIRONMENT", "").strip().lower()
    return env == "staging"


def es_entorno_estricto() -> bool:
    """Indica si el entorno exige Supabase estricto sin SQLite (production o staging)."""
    env = os.environ.get("APP_ENVIRONMENT", "production").strip().lower()
    return env in ("production", "staging")


def _resolver_publishable_key() -> str:
    """Retorna la Publishable Key moderna o fallback a la Anon Key legacy."""
    return (
        os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
        or os.environ.get("SUPABASE_ANON_KEY", "").strip()
    )


def _resolver_secret_key() -> str:
    """Retorna la Secret Key moderna o fallback a la Service Role Key legacy."""
    return (
        os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )


def usar_supabase() -> bool:
    """Determina si la capa de persistencia activa es Supabase o SQLite.

    En producción y staging (APP_ENVIRONMENT=production | staging), Supabase es obligatorio y fail-closed (Q4).
    En desarrollo (APP_ENVIRONMENT=development), se permite SQLite si USE_SQLITE=true.
    """
    url = os.environ.get("SUPABASE_URL", "").strip()
    pub_key = _resolver_publishable_key()

    if es_entorno_estricto():
        if not url or not pub_key:
            env_nombre = "staging" if es_modo_staging() else "producción"
            raise ConfiguracionInvalidaError(
                f"AutoForm AI está configurado en {env_nombre} (APP_ENVIRONMENT={os.environ.get('APP_ENVIRONMENT')}), "
                f"pero no se encontraron SUPABASE_URL o SUPABASE_PUBLISHABLE_KEY / SUPABASE_ANON_KEY en las variables de entorno. "
                f"Por política de seguridad (ADR-0010), el fallback automático a SQLite está prohibido en {env_nombre}."
            )
        return True

    # Entorno development
    use_sqlite = os.environ.get("USE_SQLITE", "false").strip().lower() in ("true", "1", "yes")
    return bool(url and pub_key and not use_sqlite)


PROHIBITED_PROJECT_REFS = {
    "tnhedxwbpqihlqbtzudt",  # AutoForm PDF Producción
    "nfsijcwkmcvtwsponqsw",  # AutoForm PDF Staging
}


def _validar_project_ref_no_prohibido(url: str) -> None:
    """Verifica que la URL de Supabase no apunte a ningún proyecto perteneciente a AutoForm PDF."""
    if not url:
        return
    for ref in PROHIBITED_PROJECT_REFS:
        if ref in url:
            raise ConfiguracionInvalidaError(
                f"[BLOQUEO DE SEGURIDAD] Operación prohibida: La URL '{url}' contiene un PROJECT_REF "
                f"perteneciente a AutoForm PDF ('{ref}'). Conexión cancelada para proteger el aislamiento de proyectos."
            )


def obtener_cliente_publico() -> Client:
    """Retorna un cliente Supabase con la Publishable Key (o Anon Key legacy) sin sesión de usuario (Q3).

    Utilizado exclusivamente para autenticación pública (login, reset de contraseña).
    Row Level Security (RLS) deniega cualquier acceso a datos protegidos con este cliente.
    """
    if create_client is None:
        raise ImportError("La librería 'supabase' no está instalada en el entorno. Ejecuta: pip install supabase")

    url = os.environ.get("SUPABASE_URL", "").strip()
    pub_key = _resolver_publishable_key()
    if not url or not pub_key:
        raise ConfiguracionInvalidaError(
            "Se requieren SUPABASE_URL y SUPABASE_PUBLISHABLE_KEY (o SUPABASE_ANON_KEY) para inicializar el cliente público."
        )
    _validar_project_ref_no_prohibido(url)
    return create_client(url, pub_key)


def obtener_cliente_admin() -> Client:
    """Retorna un cliente Supabase con la Secret Key (o Service Role Key legacy) para operaciones del servidor (Q3).

    REGLA DE SEGURIDAD ABSOLUTA: Uso exclusivo en el backend para migraciones, seeding e invitaciones
    oficiales por correo. Jamás debe exponerse al frontend, navegador ni logs.
    """
    if create_client is None:
        raise ImportError("La librería 'supabase' no está instalada en el entorno. Ejecuta: pip install supabase")

    url = os.environ.get("SUPABASE_URL", "").strip()
    secret_key = _resolver_secret_key()
    if not url or not secret_key:
        raise ConfiguracionInvalidaError(
            "Se requieren SUPABASE_URL y SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY) para inicializar el cliente administrativo."
        )
    _validar_project_ref_no_prohibido(url)
    return create_client(url, secret_key)


def obtener_cliente_usuario(
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
) -> Client:
    """Retorna una instancia efímera de cliente Supabase para la sesión activa del usuario (Q3).

    Configurada con el JWT del usuario para que todas las operaciones respeten Row Level Security (RLS).
    No se almacena en caché global ni se comparte entre sesiones.
    """
    if create_client is None:
        raise ImportError("La librería 'supabase' no está instalada en el entorno. Ejecuta: pip install supabase")

    url = os.environ.get("SUPABASE_URL", "").strip()
    pub_key = _resolver_publishable_key()
    if not url or not pub_key:
        raise ConfiguracionInvalidaError(
            "Se requieren SUPABASE_URL y SUPABASE_PUBLISHABLE_KEY (o SUPABASE_ANON_KEY) para inicializar el cliente de usuario."
        )
    _validar_project_ref_no_prohibido(url)
    client: Client = create_client(url, pub_key)
    if access_token:
        # Inyectar el token JWT en el cliente PostgREST para que todas las consultas
        # a tablas respeten las políticas de Row Level Security (RLS)
        client.postgrest.auth(access_token)
        if refresh_token:
            try:
                client.auth.set_session(access_token, refresh_token)
            except Exception as exc:
                print(f"[AutoForm AI DB] Advertencia al inyectar sesión JWT en cliente usuario: {exc}")
    return client


def _obtener_cliente_activo(cliente_provisto: Optional[Client] = None) -> Client:
    """Resuelve el cliente Supabase adecuado según el contexto de ejecución.

    REGLA DE SEGURIDAD ABSOLUTA (Auditoría C-01):
    1. Si se proporciona un cliente explícito, se utiliza directamente.
    2. Si existe sesión JWT en st.session_state, se utiliza obtener_cliente_usuario().
    3. JAMÁS hace fallback automático a obtener_cliente_admin(). Ninguna función de UI
       ni operación de datos puede obtener privilegios de service_role implícitamente.
    4. En producción (APP_ENVIRONMENT=production), la ausencia de un cliente autenticado
       lanza obligatoriamente SesionNoAutenticadaError (Fail-Closed).
    """
    if cliente_provisto is not None:
        return cliente_provisto

    # Intentar obtener tokens desde la sesión web de Streamlit si está activa
    try:
        import streamlit as st
        if hasattr(st, "session_state") and "supabase_session" in st.session_state:
            ses = st.session_state["supabase_session"]
            if isinstance(ses, dict):
                acc = ses.get("access_token")
                ref = ses.get("refresh_token")
                if acc and ref:
                    return obtener_cliente_usuario(acc, ref)
    except Exception:
        pass

    # Si estamos en producción o staging y no hay cliente autenticado ni provisto: fail-closed
    if es_entorno_estricto():
        env_nombre = "staging" if es_modo_staging() else "producción"
        raise SesionNoAutenticadaError(
            f"Acceso protegido denegado: Se requiere una sesión autenticada con JWT válido en entorno de {env_nombre}. "
            "El acceso anónimo o administrativo implícito está estrictamente prohibido."
        )

    # Entorno development: retornar cliente público (RLS denegará accesos no permitidos)
    return obtener_cliente_publico()


def validar_identidad_despliegue(
    client: Optional[Client] = None,
    entorno_esperado: str = "staging",
) -> Dict[str, Any]:
    """Valida la identidad canónica del despliegue en Supabase contra deployment_identity.

    Verificaciones estrictas de aislamiento (ADR-0010):
    1. Bloqueo inmediato si SUPABASE_URL apunta a proyectos PDF prohibidos.
    2. Existencia de exactamente una fila en public.deployment_identity (violación de singleton).
    3. application_code == 'autoform-excel'.
    4. environment == entorno_esperado (por defecto 'staging').
    5. Si AUTOFORM_EXCEL_STAGING_PROJECT_REF está configurada, debe coincidir con project_ref.
    """
    url = os.environ.get("SUPABASE_URL", "").strip()
    _validar_project_ref_no_prohibido(url)

    if client is None:
        client = obtener_cliente_publico()

    try:
        res = client.table("deployment_identity").select("singleton_id, application_code, environment, project_ref").execute()
    except Exception as exc:
        raise ConfiguracionInvalidaError(f"[BLOQUEO DE SEGURIDAD] Error al consultar 'deployment_identity': {exc}")

    if not res.data:
        raise ConfiguracionInvalidaError(
            "[BLOQUEO DE SEGURIDAD] La tabla 'deployment_identity' está vacía. "
            f"Debe inicializarse con exactamente 1 fila con application_code='autoform-excel' y environment='{entorno_esperado}'."
        )

    if len(res.data) != 1:
        raise ConfiguracionInvalidaError(
            f"[BLOQUEO DE SEGURIDAD] Violación de singleton en 'deployment_identity': "
            f"Se encontraron {len(res.data)} filas, pero debe existir exactamente una fila."
        )

    record = res.data[0]
    app_code = str(record.get("application_code") or "").strip()
    env = str(record.get("environment") or "").strip()
    p_ref = str(record.get("project_ref") or "").strip()

    if app_code != "autoform-excel":
        raise ConfiguracionInvalidaError(
            f"[BLOQUEO DE SEGURIDAD] Discrepancia en deployment_identity: "
            f"application_code es '{app_code}', se esperaba 'autoform-excel'."
        )

    if env != entorno_esperado:
        raise ConfiguracionInvalidaError(
            f"[BLOQUEO DE SEGURIDAD] Discrepancia en deployment_identity: "
            f"environment es '{env}', se esperaba '{entorno_esperado}'."
        )

    staging_ref_cfg = os.environ.get("AUTOFORM_EXCEL_STAGING_PROJECT_REF", "").strip()
    if staging_ref_cfg and p_ref != staging_ref_cfg:
        raise ConfiguracionInvalidaError(
            f"[BLOQUEO DE SEGURIDAD] Discrepancia en deployment_identity: "
            f"project_ref registrado es '{p_ref}', pero la allowlist espera '{staging_ref_cfg}'."
        )

    return record


# ── SQLite: RESPALDO LOCAL PARA DESARROLLO (APP_ENVIRONMENT=development) ──────────

def _asegurar_config_dir() -> None:
    """Garantiza la existencia del directorio config/."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def obtener_conexion() -> sqlite3.Connection:
    """Abre y devuelve una conexión a la base de datos SQLite corporativa local."""
    if es_entorno_estricto():
        env_nombre = os.environ.get("APP_ENVIRONMENT", "production").strip()
        raise ConfiguracionInvalidaError(
            f"[BLOQUEO DE SEGURIDAD] SQLite está completamente bloqueado en el entorno '{env_nombre}'. "
            "En producción y staging, Supabase es la única fuente de verdad y el fallback a SQLite está prohibido."
        )
    _asegurar_config_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_db() -> None:
    """Crea la estructura de tablas e índices en SQLite para desarrollo local si no existen."""
    if usar_supabase():
        return

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

        cursor.execute("PRAGMA table_info(operadores)")
        cols_op = {row["name"] for row in cursor.fetchall()}
        if "direccion" not in cols_op:
            cursor.execute("ALTER TABLE operadores ADD COLUMN direccion TEXT DEFAULT ''")
        if "ciudad" not in cols_op:
            cursor.execute("ALTER TABLE operadores ADD COLUMN ciudad TEXT DEFAULT ''")

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
                    "Director Comercial Senior",
                    "99887766",
                    "3001122334",
                    "antonio.prieto@iaclatam.com",
                    "Carrera 63 B # 32 E -25 OFC 206",
                    "Bogotá",
                    ahora,
                ),
            )

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
                estado_aprobacion TEXT DEFAULT 'aprobado',
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

        cursor.execute("PRAGMA table_info(usuarios)")
        cols_usr = {row["name"] for row in cursor.fetchall()}
        if "direccion" not in cols_usr:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN direccion TEXT DEFAULT ''")
        if "ciudad" not in cols_usr:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN ciudad TEXT DEFAULT ''")
        if "estado_aprobacion" not in cols_usr:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN estado_aprobacion TEXT DEFAULT 'aprobado'")

        cursor.execute("SELECT COUNT(*) AS total FROM usuarios")
        total_usuarios = cursor.fetchone()["total"]
        if total_usuarios == 0:
            from core.auth_manager import hashear_password
            admin_pwd = os.environ.get("AUTOFORM_ADMIN_PASSWORD", "").strip()
            if not admin_pwd:
                raise RuntimeError(
                    "Error de configuración: La variable de entorno 'AUTOFORM_ADMIN_PASSWORD' "
                    "no está definida. Debe configurarse explícitamente para inicializar la cuenta administrativa de AutoForm Excel en SQLite."
                )
            ahora = datetime.now(timezone.utc).isoformat()
            # 1. Administrador nominal del sistema (Guillermo Cañón)
            cursor.execute(
                """
                INSERT INTO usuarios (id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, password_hash, es_admin, activo, creado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?)
                """,
                (
                    "guillermo_canon",
                    "Guillermo Humberto Cañón Sarria",
                    "Representante Legal / Gerente General",
                    "98555384",
                    "2656868",
                    "guillermo.canon@iaclatam.com",
                    "Carrera 63 B # 32 E -25 OFC 206",
                    "Medellin",
                    hashear_password(admin_pwd),
                    ahora,
                ),
            )
            # 2. Operador comercial estándar (Antonio Prieto)
            cursor.execute(
                """
                INSERT INTO usuarios (id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, password_hash, es_admin, activo, creado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?)
                """,
                (
                    "antonio_prieto",
                    "Antonio Prieto",
                    "Director Comercial Senior",
                    "99887766",
                    "3001122334",
                    "antonio.prieto@iaclatam.com",
                    "Carrera 63 B # 32 E -25 OFC 206",
                    "Bogotá",
                    hashear_password(admin_pwd),
                    ahora,
                ),
            )

        conn.commit()


# ── GESTIÓN DE PERFILES DE EMPRESA (Q1: HÍBRIDO RELACIONAL + JSONB) ──────────────

def guardar_perfil_db(
    id_perfil: str,
    nombre: str,
    datos: Dict[str, Any],
    es_activo: Optional[bool] = None,
    client: Optional[Client] = None,
) -> bool:
    """Guarda o actualiza canónicamente un perfil empresarial en la base de datos activa."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            slug_limpio = id_perfil.strip().lower()
            nombre_limpio = nombre.strip()

            nit = None
            if isinstance(datos, dict):
                nit = datos.get("empresa", {}).get("identidad", {}).get("nit") or datos.get("nit")
                if nit:
                    nit = str(nit).strip()

            if es_activo is True:
                # Desmarcar los demás perfiles para respetar el índice único parcial
                cli.table("perfiles_empresa").update({"es_activa": False}).neq("slug", slug_limpio).execute()
                activo_val = True
            elif es_activo is False:
                activo_val = False
            else:
                activo_val = None

            registro: Dict[str, Any] = {
                "slug": slug_limpio,
                "nombre_empresa": nombre_limpio,
                "nit": nit,
                "datos_json": datos,
            }
            if activo_val is not None:
                registro["es_activa"] = activo_val

            cli.table("perfiles_empresa").upsert(registro, on_conflict="slug").execute()
            return True
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error al guardar perfil en Supabase '{id_perfil}': {exc}")
            return False

    # Modo SQLite (Desarrollo local)
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
                activo_val_sql = 1
            elif es_activo is False:
                activo_val_sql = 0
            else:
                activo_val_sql = None

            if activo_val_sql is not None:
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
                    (id_limpio, nombre_limpio, datos_serializados, activo_val_sql, ahora_iso),
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
        print(f"[AutoForm AI DB] Error al guardar perfil en SQLite '{id_perfil}': {exc}")
        return False


def obtener_perfil_db(id_perfil: str, client: Optional[Client] = None) -> Optional[Dict[str, Any]]:
    """Recupera los datos de un perfil por su slug/identificador."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            slug_limpio = id_perfil.strip().lower()
            res = cli.table("perfiles_empresa").select("datos_json").eq("slug", slug_limpio).limit(1).execute()
            if res.data and len(res.data) > 0:
                return res.data[0].get("datos_json")
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error al leer perfil '{id_perfil}' desde Supabase: {exc}")
        return None

    # Modo SQLite
    inicializar_db()
    id_limpio = id_perfil.strip().lower()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT datos_json FROM perfiles_empresa WHERE id = ?", (id_limpio,))
            row = cursor.fetchone()
            if row and row["datos_json"]:
                return json.loads(row["datos_json"])
    except Exception as exc:
        print(f"[AutoForm AI DB] Error al leer perfil '{id_perfil}' desde SQLite: {exc}")
    return None


def obtener_perfil_activo_db(client: Optional[Client] = None) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """Recupera el perfil marcado como activo. Retorna (slug, nombre, datos)."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            res = cli.table("perfiles_empresa").select("slug, nombre_empresa, datos_json").eq("es_activa", True).order("updated_at", desc=True).limit(1).execute()
            if not res.data:
                res = cli.table("perfiles_empresa").select("slug, nombre_empresa, datos_json").order("updated_at", desc=True).limit(1).execute()
            if res.data and len(res.data) > 0:
                fila = res.data[0]
                return str(fila.get("slug")), str(fila.get("nombre_empresa")), fila.get("datos_json", {})
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error al obtener perfil activo de Supabase: {exc}")
        return None

    # Modo SQLite
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


def establecer_perfil_activo_db(id_o_nombre: str, client: Optional[Client] = None) -> bool:
    """Marca un perfil como activo y desmarca a los demás."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            criterio = id_o_nombre.strip()
            slug = criterio.lower()
            cli.table("perfiles_empresa").update({"es_activa": False}).execute()
            res = cli.table("perfiles_empresa").update({"es_activa": True}).or_(f"slug.eq.{slug},nombre_empresa.eq.{criterio}").execute()
            return bool(res.data and len(res.data) > 0)
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error al activar perfil '{id_o_nombre}' en Supabase: {exc}")
            return False

    # Modo SQLite
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
        print(f"[AutoForm AI DB] Error al activar perfil '{id_o_nombre}' en SQLite: {exc}")
        return False


def listar_perfiles_db(client: Optional[Client] = None) -> List[Dict[str, Any]]:
    """Devuelve la lista de perfiles registrados."""
    if usar_supabase():
        perfiles = []
        try:
            cli = _obtener_cliente_activo(client)
            res = cli.table("perfiles_empresa").select("slug, nombre_empresa, datos_json, es_activa, updated_at").order("slug", desc=False).execute()
            filas = sorted(res.data or [], key=lambda r: (0 if r.get("slug") == "principal" else 1, r.get("nombre_empresa", "")))
            for fila in filas:
                perfiles.append({
                    "id": str(fila.get("slug")),
                    "nombre": str(fila.get("nombre_empresa")),
                    "datos": fila.get("datos_json") or {},
                    "es_activo": bool(fila.get("es_activa")),
                    "actualizado_en": str(fila.get("updated_at")),
                })
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error al listar perfiles desde Supabase: {exc}")
        return perfiles

    # Modo SQLite
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


def eliminar_perfil_db(id_perfil: str, client: Optional[Client] = None) -> bool:
    """Elimina un perfil secundario (el perfil 'principal' está protegido)."""
    slug = id_perfil.lower().strip()
    if slug == "principal":
        return False

    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            cli.table("perfiles_empresa").delete().eq("slug", slug).execute()
            return True
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error eliminando perfil '{id_perfil}' en Supabase: {exc}")
            return False

    # Modo SQLite
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM perfiles_empresa WHERE id = ?", (slug,))
            conn.commit()
            return True
    except Exception as exc:
        print(f"[AutoForm AI DB] Error eliminando perfil '{id_perfil}' en SQLite: {exc}")
        return False


# ── GESTIÓN DE OPERADORES Y COMERCIALES (ADR-0007 / ADR-0010) ────────────────────

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
    client: Optional[Client] = None,
    usuario_id: Optional[str] = None,
) -> bool:
    """Guarda o actualiza un operador en la base de datos activa."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            id_limpio = id_operador.strip().lower()
            nombre_limpio = nombre.strip()

            if es_activo is True:
                cli.table("operadores").update({"es_activo": False}).neq("id", id_limpio).execute()
                activo_val = True
            elif es_activo is False:
                activo_val = False
            else:
                activo_val = None

            registro: Dict[str, Any] = {
                "id": id_limpio,
                "nombre": nombre_limpio,
                "cargo": cargo.strip(),
                "cedula": cedula.strip(),
                "telefono": telefono.strip(),
                "correo": correo.strip().lower(),
                "direccion": direccion.strip(),
                "ciudad": ciudad.strip(),
            }
            if usuario_id:
                registro["usuario_id"] = usuario_id
            if activo_val is not None:
                registro["es_activo"] = activo_val

            cli.table("operadores").upsert(registro, on_conflict="id").execute()

            # Sincronizar con perfiles_usuario si existe
            correo_limpio = correo.strip().lower()
            if correo_limpio:
                cli.table("perfiles_usuario").update({
                    "nombre": nombre_limpio,
                    "cargo": cargo.strip(),
                    "cedula": cedula.strip(),
                    "telefono": telefono.strip(),
                    "direccion": direccion.strip(),
                    "ciudad": ciudad.strip(),
                }).eq("correo", correo_limpio).execute()
            return True
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error guardando operador en Supabase '{id_operador}': {exc}")
            return False

    # Modo SQLite
    inicializar_db()
    id_limpio = id_operador.strip().lower()
    nombre_limpio = nombre.strip()
    ahora_iso = datetime.now(timezone.utc).isoformat()

    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            if es_activo is True:
                cursor.execute("UPDATE operadores SET es_activo = 0")
                activo_val_sql = 1
            elif es_activo is False:
                activo_val_sql = 0
            else:
                activo_val_sql = None

            cursor.execute("SELECT id, es_activo FROM operadores WHERE id = ?", (id_limpio,))
            fila_existente = cursor.fetchone()

            if fila_existente:
                if activo_val_sql is None:
                    activo_val_sql = fila_existente["es_activo"]
                cursor.execute(
                    """
                    UPDATE operadores
                    SET nombre = ?, cargo = ?, cedula = ?, telefono = ?, correo = ?, direccion = ?, ciudad = ?, es_activo = ?, actualizado_en = ?
                    WHERE id = ?
                    """,
                    (nombre_limpio, cargo.strip(), cedula.strip(), telefono.strip(), correo.strip(), direccion.strip(), ciudad.strip(), activo_val_sql, ahora_iso, id_limpio),
                )
            else:
                if activo_val_sql is None:
                    cursor.execute("SELECT COUNT(*) as total FROM operadores")
                    c_row = cursor.fetchone()
                    activo_val_sql = 1 if (c_row and c_row["total"] == 0) else 0

                cursor.execute(
                    """
                    INSERT INTO operadores (id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_activo, actualizado_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (id_limpio, nombre_limpio, cargo.strip(), cedula.strip(), telefono.strip(), correo.strip(), direccion.strip(), ciudad.strip(), activo_val_sql, ahora_iso),
                )

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
        print(f"[AutoForm AI DB] Error guardando operador en SQLite '{id_operador}': {exc}")
        return False


def listar_operadores_db(client: Optional[Client] = None) -> List[Dict[str, Any]]:
    """Devuelve la lista de operadores registrados."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            res = cli.table("operadores").select("*").order("es_activo", desc=True).order("nombre", desc=False).execute()
            ops = []
            for row in (res.data or []):
                ops.append({
                    "id": str(row.get("id")),
                    "nombre": str(row.get("nombre")),
                    "cargo": str(row.get("cargo") or ""),
                    "cedula": str(row.get("cedula") or ""),
                    "telefono": str(row.get("telefono") or ""),
                    "correo": str(row.get("correo") or ""),
                    "direccion": str(row.get("direccion") or ""),
                    "ciudad": str(row.get("ciudad") or ""),
                    "es_activo": bool(row.get("es_activo")),
                    "actualizado_en": str(row.get("updated_at")),
                })
            return ops
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error listando operadores en Supabase: {exc}")
            return []

    # Modo SQLite
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


def obtener_operador_db(id_operador: str, client: Optional[Client] = None) -> Optional[Dict[str, Any]]:
    """Obtiene un operador por su identificador único."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            res = cli.table("operadores").select("*").eq("id", id_operador.strip().lower()).limit(1).execute()
            if res.data and len(res.data) > 0:
                row = res.data[0]
                return {
                    "id": str(row.get("id")),
                    "nombre": str(row.get("nombre")),
                    "cargo": str(row.get("cargo") or ""),
                    "cedula": str(row.get("cedula") or ""),
                    "telefono": str(row.get("telefono") or ""),
                    "correo": str(row.get("correo") or ""),
                    "direccion": str(row.get("direccion") or ""),
                    "ciudad": str(row.get("ciudad") or ""),
                    "es_activo": bool(row.get("es_activo")),
                    "actualizado_en": str(row.get("updated_at")),
                }
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error obteniendo operador '{id_operador}' en Supabase: {exc}")
        return None

    # Modo SQLite
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
        print(f"[AutoForm AI DB] Error obteniendo operador '{id_operador}' en SQLite: {exc}")
    return None


def obtener_operador_activo_db(client: Optional[Client] = None) -> Optional[Dict[str, Any]]:
    """Devuelve el operador marcado como activo."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            res = cli.table("operadores").select("*").eq("es_activo", True).limit(1).execute()
            if res.data and len(res.data) > 0:
                row = res.data[0]
                return {
                    "id": str(row.get("id")),
                    "nombre": str(row.get("nombre")),
                    "cargo": str(row.get("cargo") or ""),
                    "cedula": str(row.get("cedula") or ""),
                    "telefono": str(row.get("telefono") or ""),
                    "correo": str(row.get("correo") or ""),
                    "direccion": str(row.get("direccion") or ""),
                    "ciudad": str(row.get("ciudad") or ""),
                    "es_activo": True,
                    "actualizado_en": str(row.get("updated_at")),
                }
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error obteniendo operador activo en Supabase: {exc}")
        return None

    # Modo SQLite
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
        print(f"[AutoForm AI DB] Error obteniendo operador activo en SQLite: {exc}")
    return None


def activar_operador_db(id_operador: str, client: Optional[Client] = None) -> bool:
    """Marca un operador como activo y desmarca a los demás."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            id_limpio = id_operador.strip().lower()
            cli.table("operadores").update({"es_activo": False}).execute()
            res = cli.table("operadores").update({"es_activo": True}).eq("id", id_limpio).execute()
            return bool(res.data and len(res.data) > 0)
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error activando operador '{id_operador}' en Supabase: {exc}")
            return False

    # Modo SQLite
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE operadores SET es_activo = 0")
            cursor.execute("UPDATE operadores SET es_activo = 1 WHERE id = ?", (id_operador.strip().lower(),))
            conn.commit()
            return cursor.rowcount > 0
    except Exception as exc:
        print(f"[AutoForm AI DB] Error activando operador '{id_operador}' en SQLite: {exc}")
        return False


def eliminar_operador_db(id_operador: str, client: Optional[Client] = None) -> bool:
    """Elimina un operador."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            cli.table("operadores").delete().eq("id", id_operador.strip().lower()).execute()
            return True
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error eliminando operador '{id_operador}' en Supabase: {exc}")
            return False

    # Modo SQLite
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM operadores WHERE id = ?", (id_operador.strip().lower(),))
            conn.commit()
            return True
    except Exception as exc:
        print(f"[AutoForm AI DB] Error eliminando operador '{id_operador}' en SQLite: {exc}")
        return False


# ── GESTIÓN DE USUARIOS Y AUTENTICACIÓN (ADR-0008 / ADR-0010) ───────────────────

def obtener_usuario_por_correo_db(correo: str, client: Optional[Client] = None) -> Optional[Dict[str, Any]]:
    """Obtiene un usuario por su correo electrónico (con soporte para @iaclatam.com y @iac.com.co)."""
    correo_limpio = correo.strip().lower()
    correo_alt = ""
    if correo_limpio.endswith("@iac.com.co"):
        correo_alt = correo_limpio.replace("@iac.com.co", "@iaclatam.com")
    elif correo_limpio.endswith("@iaclatam.com"):
        correo_alt = correo_limpio.replace("@iaclatam.com", "@iac.com.co")

    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            res = cli.table("perfiles_usuario").select("*").eq("correo", correo_limpio).limit(1).execute()
            if not res.data and correo_alt:
                res = cli.table("perfiles_usuario").select("*").eq("correo", correo_alt).limit(1).execute()

            if res.data and len(res.data) > 0:
                row = res.data[0]
                return {
                    "id": str(row.get("id")),
                    "nombre": str(row.get("nombre")),
                    "cargo": str(row.get("cargo") or ""),
                    "cedula": str(row.get("cedula") or ""),
                    "telefono": str(row.get("telefono") or ""),
                    "correo": str(row.get("correo")),
                    "direccion": str(row.get("direccion") or "Carrera 63 B # 32 E -25 OFC 206"),
                    "ciudad": str(row.get("ciudad") or "Bogotá"),
                    "es_admin": bool(row.get("es_admin")),
                    "activo": bool(row.get("activo")),
                    "estado_aprobacion": str(row.get("estado_aprobacion") or "aprobado"),
                    "creado_en": str(row.get("created_at")),
                }
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error al buscar usuario por correo en Supabase: {exc}")
        return None

    # Modo SQLite
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, password_hash, es_admin, activo, estado_aprobacion, creado_en
                FROM usuarios
                WHERE (LOWER(correo) = ? OR (LOWER(correo) = ? AND ? != ''))
                LIMIT 1
                """,
                (correo_limpio, correo_alt, correo_alt),
            )
            row = cursor.fetchone()
            if row:
                cols = row.keys() if hasattr(row, "keys") else []
                est_ap = str(row["estado_aprobacion"]) if "estado_aprobacion" in cols else "aprobado"
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
                    "estado_aprobacion": est_ap,
                    "creado_en": str(row["creado_en"]),
                }
    except Exception as exc:
        print(f"[AutoForm AI DB] Error al buscar usuario por correo en SQLite: {exc}")
    return None


def autenticar_usuario_db(correo: str, password: str) -> Optional[Dict[str, Any]]:
    """Autentica un usuario contra el almacén de credenciales activo."""
    if usar_supabase():
        # En Supabase, la autenticación se gestiona vía core.auth_manager.iniciar_sesion()
        from core import auth_manager
        ok, user_dict, _, _ = auth_manager.iniciar_sesion(correo, password)
        return user_dict if ok else None

    # Modo SQLite (Desarrollo local con PBKDF2)
    from core.auth_manager import verificar_password
    usuario = obtener_usuario_por_correo_db(correo)
    if not usuario:
        return None

    if verificar_password(password, usuario.get("password_hash", "")):
        datos_seguros = dict(usuario)
        datos_seguros.pop("password_hash", None)
        return datos_seguros

    return None


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
    """Registra un usuario en la base de datos activa."""
    from core.auth_manager import validar_dominio_corporativo, validar_formato_correo

    correo_limpio = correo.strip().lower()
    nombre_limpio = nombre.strip()

    if not nombre_limpio:
        return False, "El nombre completo es obligatorio."
    if not validar_formato_correo(correo_limpio):
        return False, "El formato de correo no es válido."
    if not validar_dominio_corporativo(correo_limpio):
        return False, "Registro no autorizado. Utiliza un correo corporativo de la empresa (@iaclatam.com o @iac.com.co)."

    if usar_supabase():
        # En producción con Supabase, las cuentas se crean exclusivamente por invitación oficial (Q5)
        from core import auth_manager
        return auth_manager.invitar_usuario_corporativo(
            correo=correo_limpio,
            nombre=nombre_limpio,
            cargo=cargo,
            cedula=cedula,
            telefono=telefono,
            direccion=direccion,
            ciudad=ciudad,
            es_admin=bool(es_admin),
        )

    # Modo SQLite
    inicializar_db()
    if not password or len(password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."

    from core.auth_manager import hashear_password
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
            if not es_admin:
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
        return False, f"Error al registrar usuario en SQLite: {exc}"


def listar_usuarios_db(client: Optional[Client] = None) -> List[Dict[str, Any]]:
    """Devuelve la lista de usuarios para administración."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            res = cli.table("perfiles_usuario").select("*").order("es_admin", desc=True).order("nombre", desc=False).execute()
            users = []
            for row in (res.data or []):
                users.append({
                    "id": str(row.get("id")),
                    "nombre": str(row.get("nombre")),
                    "cargo": str(row.get("cargo") or ""),
                    "cedula": str(row.get("cedula") or ""),
                    "telefono": str(row.get("telefono") or ""),
                    "correo": str(row.get("correo")),
                    "direccion": str(row.get("direccion") or ""),
                    "ciudad": str(row.get("ciudad") or ""),
                    "es_admin": bool(row.get("es_admin")),
                    "activo": bool(row.get("activo")),
                    "estado_aprobacion": str(row.get("estado_aprobacion") or "aprobado"),
                    "creado_en": str(row.get("created_at")),
                })
            return users
        except SesionNoAutenticadaError:
            raise
        except Exception as exc:
            print(f"[AutoForm AI DB] Error listando usuarios en Supabase: {exc}")
            return []

    # Modo SQLite
    inicializar_db()
    usuarios = []
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_admin, activo, estado_aprobacion, creado_en
                FROM usuarios
                ORDER BY es_admin DESC, nombre ASC
                """
            )
            for row in cursor.fetchall():
                cols = row.keys() if hasattr(row, "keys") else []
                est_ap = str(row["estado_aprobacion"]) if "estado_aprobacion" in cols else "aprobado"
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
                    "estado_aprobacion": est_ap,
                    "creado_en": str(row["creado_en"]),
                })
    except Exception as exc:
        print(f"[AutoForm AI DB] Error listando usuarios en SQLite: {exc}")
    return usuarios


def actualizar_estado_usuario_db(
    usuario_id: str,
    nuevo_estado: str,
    nuevo_activo: bool,
    client: Optional[Client] = None,
) -> bool:
    """Actualiza el estado de aprobación y activación de un usuario en la BD."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            res = (
                cli.table("perfiles_usuario")
                .update({"estado_aprobacion": nuevo_estado, "activo": nuevo_activo})
                .eq("id", usuario_id)
                .execute()
            )
            return bool(res.data)
        except Exception as exc:
            print(f"[AutoForm AI DB] Error actualizando estado de usuario en Supabase: {exc}")
            return False

    # Modo SQLite
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE usuarios
                SET estado_aprobacion = ?, activo = ?
                WHERE id = ?
                """,
                (nuevo_estado, 1 if nuevo_activo else 0, usuario_id),
            )
            conn.commit()
            return cursor.rowcount > 0
    except Exception as exc:
        print(f"[AutoForm AI DB] Error actualizando estado de usuario en SQLite: {exc}")
        return False


def actualizar_rol_usuario_db(
    usuario_id: str,
    es_admin: bool,
    client: Optional[Client] = None,
) -> bool:
    """Actualiza el rol administrativo de un usuario en la BD."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            res = (
                cli.table("perfiles_usuario")
                .update({"es_admin": es_admin})
                .eq("id", usuario_id)
                .execute()
            )
            return bool(res.data)
        except Exception as exc:
            print(f"[AutoForm AI DB] Error actualizando rol de usuario en Supabase: {exc}")
            return False

    # Modo SQLite
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE usuarios
                SET es_admin = ?
                WHERE id = ?
                """,
                (1 if es_admin else 0, usuario_id),
            )
            conn.commit()
            return cursor.rowcount > 0
    except Exception as exc:
        print(f"[AutoForm AI DB] Error actualizando rol de usuario en SQLite: {exc}")
        return False


def contar_administradores_activos_db(client: Optional[Client] = None) -> int:
    """Retorna el número de administradores que se encuentran activos."""
    if usar_supabase():
        try:
            cli = _obtener_cliente_activo(client)
            res = (
                cli.table("perfiles_usuario")
                .select("id", count="exact")
                .eq("es_admin", True)
                .eq("activo", True)
                .execute()
            )
            if hasattr(res, "count") and res.count is not None:
                return int(res.count)
            return len(res.data or [])
        except Exception as exc:
            print(f"[AutoForm AI DB] Error contando administradores activos en Supabase: {exc}")
            return 1

    # Modo SQLite
    inicializar_db()
    try:
        with obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM usuarios
                WHERE es_admin = 1 AND activo = 1
                """
            )
            row = cursor.fetchone()
            return int(row["total"]) if row else 0
    except Exception as exc:
        print(f"[AutoForm AI DB] Error contando administradores activos en SQLite: {exc}")
        return 1
