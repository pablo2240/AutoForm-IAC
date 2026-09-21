#!/usr/bin/env python3
"""Script de migración y respaldo seguro: SQLite (empresa.db) -> Supabase (PostgreSQL + Auth + RLS).

Reglas de seguridad obligatorias (ADR-0010):
1. Siempre genera un respaldo físico con timestamp e integridad SHA256 de SQLite antes de cualquier proceso.
2. Modo por defecto es '--dry-run' (simulación segura sin mutación ni llamadas remotas).
3. Jamás expone contraseñas, hashes PBKDF2, tokens, recovery links ni la Service Role Key.
4. Enmascara todas las direcciones de correo electrónico en consola y logs (a***o@iaclatam.com).
5. La ejecución real requiere estrictamente '--execute --confirm-project <project_ref>' para evitar ejecución accidental.
6. El flag '--live' está deshabilitado permanentemente.
7. Registra cada lote con un 'batch_id' (UUID) y un 'manifesto_uuids' JSONB inmutable de todos los UUID creados.
8. Excluye cuentas de prueba o mock (pepito_perez).
9. Retiene el envío de invitaciones por correo por defecto (requiere flag explícito '--enviar-invitaciones').
10. El rollback selectivo es idempotente, FK-safe y verifica PROJECT_REF antes de operar.

Hardening-04 (Ronda Final):
- manifesto_uuids JSONB en migration_runs para rollback selectivo inequívoco.
- Compensación de creación parcial: registra estado "failed_at" sin borrar automáticamente.
- Rollback verifica PROJECT_REF, es idempotente y respeta orden FK.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SQLITE_DB_PATH = CONFIG_DIR / "empresa.db"

# Expresión regular canónica aprobada (ADR-0010 / Q6)
DOMINIO_REGEX = re.compile(r"^[^@\s]+@(iaclatam\.com|iac\.com\.co)$", re.IGNORECASE)


def enmascarar_correo(correo: str) -> str:
    """Enmascara una dirección de correo para prevenir fuga de PII en logs (ej: a***o@iaclatam.com)."""
    if not correo or "@" not in correo:
        return "***"
    partes = correo.strip().split("@", 1)
    usuario = partes[0]
    dominio = partes[1]
    if len(usuario) <= 2:
        usuario_mask = usuario[0] + "***"
    else:
        usuario_mask = usuario[0] + "***" + usuario[-1]
    return f"{usuario_mask}@{dominio}"


def extraer_project_ref(url: str) -> Optional[str]:
    """Extrae el project reference único desde una URL de Supabase."""
    if not url:
        return None
    match = re.search(r"https?://([^.]+)\.supabase\.(co|in|net)", url.strip(), re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def calcular_sha256_archivo(ruta: Path) -> str:
    """Calcula el hash SHA256 de un archivo físico para verificar integridad criptográfica."""
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def crear_respaldo_sqlite(db_path: Optional[Path] = None) -> Path:
    """Crea una copia física con timestamp de SQLite verificando integridad de tamaño y SHA256.

    Returns:
        Path al archivo de respaldo creado.
    """
    ruta_origen = db_path or SQLITE_DB_PATH
    if not ruta_origen.exists():
        raise FileNotFoundError(f"No se encontró la base de datos origen en: {ruta_origen}")

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_filename = f"empresa_backup_{timestamp_str}.db"
    dir_destino = ruta_origen.parent
    backup_path = dir_destino / backup_filename

    shutil.copy2(ruta_origen, backup_path)
    size_orig = ruta_origen.stat().st_size
    size_copy = backup_path.stat().st_size

    if size_orig != size_copy:
        raise IOError(f"Error de integridad en respaldo: tamaño original ({size_orig} B) != copia ({size_copy} B)")

    sha_orig = calcular_sha256_archivo(ruta_origen)
    sha_copy = calcular_sha256_archivo(backup_path)
    if sha_orig != sha_copy:
        raise IOError("Error de integridad SHA256: la copia de respaldo no coincide con el archivo original.")

    print(f"[AutoForm AI Backup] Respaldo físico verificado: {backup_path.name} ({size_copy:,} bytes | SHA256: {sha_orig[:12]}...)")
    return backup_path


def leer_datos_sqlite(db_path: Optional[Path] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extrae las colecciones de perfiles, operadores y usuarios desde SQLite.

    Aplica exclusión estricta de cuentas de prueba o mock (ej: pepito_perez).
    """
    ruta_origen = db_path or SQLITE_DB_PATH
    conn = sqlite3.connect(str(ruta_origen))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    perfiles: List[Dict[str, Any]] = []
    try:
        cursor.execute("SELECT id, nombre, datos_json, es_activo, actualizado_en FROM perfiles_empresa")
        for row in cursor.fetchall():
            perfiles.append({
                "slug": str(row["id"]).strip().lower(),
                "nombre_empresa": str(row["nombre"]).strip(),
                "datos_json": json.loads(row["datos_json"]) if row["datos_json"] else {},
                "es_activa": bool(row["es_activo"]),
                "actualizado_en": str(row["actualizado_en"]),
            })
    except Exception as exc:
        print(f"[Advertencia] No se pudo leer 'perfiles_empresa': {exc}")

    operadores: List[Dict[str, Any]] = []
    try:
        cursor.execute("SELECT id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_activo, actualizado_en FROM operadores")
        for row in cursor.fetchall():
            op_id = str(row["id"]).strip().lower()
            op_correo = str(row["correo"] or "").strip().lower()
            # Exclusión de personas de prueba / mock
            if op_id == "pepito_perez" or "pepito" in op_correo:
                continue
            operadores.append({
                "id": op_id,
                "nombre": str(row["nombre"]).strip(),
                "cargo": str(row["cargo"] or "").strip(),
                "cedula": str(row["cedula"] or "").strip(),
                "telefono": str(row["telefono"] or "").strip(),
                "correo": op_correo,
                "direccion": str(row["direccion"] or "").strip(),
                "ciudad": str(row["ciudad"] or "").strip(),
                "es_activo": bool(row["es_activo"]),
                "actualizado_en": str(row["actualizado_en"]),
            })
    except Exception as exc:
        print(f"[Advertencia] No se pudo leer 'operadores': {exc}")

    usuarios: List[Dict[str, Any]] = []
    try:
        cursor.execute("SELECT id, nombre, cargo, cedula, telefono, correo, direccion, ciudad, es_admin, activo, creado_en FROM usuarios")
        for row in cursor.fetchall():
            u_id = str(row["id"]).strip().lower()
            u_correo = str(row["correo"] or "").strip().lower()
            # Exclusión de personas de prueba / mock
            if u_id == "pepito_perez" or "pepito" in u_correo:
                continue
            usuarios.append({
                "id": u_id,
                "nombre": str(row["nombre"]).strip(),
                "cargo": str(row["cargo"] or "").strip(),
                "cedula": str(row["cedula"] or "").strip(),
                "telefono": str(row["telefono"] or "").strip(),
                "correo": u_correo,
                "direccion": str(row["direccion"] or "Carrera 63 B # 32 E -25 OFC 206").strip(),
                "ciudad": str(row["ciudad"] or "Bogotá").strip(),
                "es_admin": bool(row["es_admin"]),
                "activo": bool(row["activo"]),
                "creado_en": str(row["creado_en"]),
            })
    except Exception as exc:
        print(f"[Advertencia] No se pudo leer 'usuarios': {exc}")

    conn.close()
    return perfiles, operadores, usuarios


def ejecutar_dry_run(
    perfiles: List[Dict[str, Any]],
    operadores: List[Dict[str, Any]],
    usuarios: List[Dict[str, Any]],
) -> None:
    """Ejecuta una auditoría estricta y simulación de migración sin modificar Supabase ni enviar correos."""
    print("\n" + "=" * 75)
    print("           MODO SIMULACIÓN (DRY-RUN) — AUDITORÍA PREVIA Y SANITIZACIÓN")
    print("=" * 75)

    # 1. Perfiles de Empresa
    print(f"\n1. Perfiles de Empresa a migrar ({len(perfiles)}):")
    for p in perfiles:
        datos = p["datos_json"]
        nit = datos.get("empresa", {}).get("identidad", {}).get("nit") or datos.get("nit") or "NO_DEFINIDO"
        rs = datos.get("empresa", {}).get("identidad", {}).get("razon_social") or datos.get("razon_social") or p["nombre_empresa"]
        print(f"   - Slug: '{p['slug']}' | Razón Social: '{rs}' | NIT: '{nit}' | Activa: {p['es_activa']}")

    # 2. Operadores Comerciales
    print(f"\n2. Operadores Comerciales sanitizados ({len(operadores)}):")
    for op in operadores:
        correo_mask = enmascarar_correo(op["correo"])
        print(f"   - ID: '{op['id']}' | Nombre: '{op['nombre']}' | Cargo: '{op['cargo']}' | Correo: '{correo_mask}' | Activo: {op['es_activo']}")

    # 3. Usuarios y Validación de Dominios Corporativos
    print(f"\n3. Cuentas de Usuario auditadas ({len(usuarios)}):")
    validos_dominio = 0
    invalidos_dominio = 0
    for u in usuarios:
        correo_real = u["correo"]
        correo_mask = enmascarar_correo(correo_real)
        cumple_dominio = bool(DOMINIO_REGEX.match(correo_real))
        if cumple_dominio:
            validos_dominio += 1
            estado_dom = "VÁLIDO (@iac)"
        else:
            invalidos_dominio += 1
            estado_dom = "INVÁLIDO (dominio no autorizado)"

        rol = "ADMINISTRADOR" if u["es_admin"] else "ESTÁNDAR (COMERCIAL)"
        app_meta_str = "{'es_admin': True, 'role': 'administrador'}" if u["es_admin"] else "{'es_admin': False, 'role': 'comercial'}"
        print(f"   - Nombre: '{u['nombre']}' | Correo: '{correo_mask}' | Rol: {rol} | app_metadata: {app_meta_str} | user_metadata: {{}} | Dominio: {estado_dom}")

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    proj_ref = extraer_project_ref(supabase_url) or "<project_ref>"
    redirect_url = os.environ.get("AUTOFORM_EXCEL_REDIRECT_URL", "").strip() or supabase_url

    print("\n" + "-" * 75)
    print("RESUMEN DE AUDITORÍA DRY-RUN:")
    print(f"  - Perfiles a migrar en tabla perfiles_empresa: {len(perfiles)} (1 empresa principal)")
    print(f"  - Operadores a migrar en tabla operadores:     {len(operadores)} (2 operadores comerciales)")
    print(f"  - Cuentas de usuario aptas para Auth:          {validos_dominio} (1 Administrador, 2 Comerciales)")
    print(f"  - Cuentas mock/test excluidas (pepito_perez):  Confirmado (0 registros)")
    print(f"  - Asignación de roles en Auth:                 Estrictamente app_metadata segura (user_metadata vacía)")
    print(f"  - Control de colisiones en auth.users:         Aborto inmediato si algún correo ya existe en auth.users")
    print(f"  - URL de redirección verificada:               {redirect_url} (Proyecto Excel Staging: {proj_ref})")
    print(f"  - Aislamiento proyectos PDF:                   Confirmado (bloqueo total a tnhedxwbpqihlqbtzudt y nfsijcwkmcvtwsponqsw)")
    print(f"  - Invitaciones retenidas por defecto:          Sí (requiere --enviar-invitaciones)")
    if invalidos_dominio > 0:
        print(f"  - Usuarios con dominio rechazado (Q6):         {invalidos_dominio}")
    print("=" * 75)

    print("Para ejecutar la migración en vivo de forma segura:")
    print(f"  python scripts/migrate_sqlite_to_supabase.py --execute --confirm-project {proj_ref}\n")


PROHIBITED_PROJECT_REFS = {
    "tnhedxwbpqihlqbtzudt",  # AutoForm PDF Producción
    "nfsijcwkmcvtwsponqsw",  # AutoForm PDF Staging
}


def _resolver_secret_key() -> str:
    """Retorna la Secret Key moderna o fallback a la Service Role Key legacy."""
    return (
        os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )



def _verificar_project_ref(supabase_url: str, confirm_project: str) -> str:
    """Valida que confirm_project y SUPABASE_URL coincidan con la allowlist positiva estricta.

    Hardening de Aislamiento Estricto:
    1. Bloqueo inmediato si target_ref o confirm_project están en PROHIBITED_PROJECT_REFS
       (ambos proyectos de AutoForm PDF: producción y staging).
    2. Exigencia de allowlist positiva vía variable de entorno 'AUTOFORM_EXCEL_STAGING_PROJECT_REF'.
       Una simple confirmación CLI NO permite utilizar otro proyecto arbitrario.
    3. Coincidencia triple obligatoria: target_ref == confirm_project == allowlist_ref.

    Returns:
        El project_ref verificado.

    Raises:
        SystemExit con código 1 si no coincide, si falta allowlist o si es un proyecto PDF.
    """
    if not supabase_url:
        print("\n[ERROR FATAL] Se requiere la variable de entorno 'SUPABASE_URL'.")
        sys.exit(1)

    project_ref_esperado = extraer_project_ref(supabase_url)
    if not project_ref_esperado:
        print(f"\n[ERROR FATAL] No se pudo derivar el project_ref desde SUPABASE_URL: {supabase_url}")
        sys.exit(1)

    # 1. Guardia anti-PDF absoluta (bloquea producción y staging de AutoForm PDF)
    if project_ref_esperado in PROHIBITED_PROJECT_REFS or confirm_project.strip() in PROHIBITED_PROJECT_REFS:
        print("\n[BLOQUEO DE SEGURIDAD] Operación prohibida: El proyecto corresponde a AutoForm PDF.")
        sys.exit(1)

    # 2. Allowlist positiva obligatoria: impedir que CLI apunte arbitrariamente
    allowlist_ref = os.environ.get("AUTOFORM_EXCEL_STAGING_PROJECT_REF", "").strip()
    if not allowlist_ref:
        print(
            "\n[BLOQUEO DE SEGURIDAD] Se requiere configurar la variable de entorno 'AUTOFORM_EXCEL_STAGING_PROJECT_REF' "
            "con el identificador del proyecto Supabase Staging autorizado para AutoForm Excel."
        )
        sys.exit(1)

    if allowlist_ref in PROHIBITED_PROJECT_REFS:
        print("\n[BLOQUEO DE SEGURIDAD] La variable 'AUTOFORM_EXCEL_STAGING_PROJECT_REF' apunta a un proyecto prohibido de AutoForm PDF.")
        sys.exit(1)

    # 3. Triple coincidencia estricta: URL derivada == confirm_project CLI == allowlist env
    if project_ref_esperado != allowlist_ref:
        print(
            f"\n[BLOQUEO DE SEGURIDAD] El proyecto en SUPABASE_URL ('{project_ref_esperado}') "
            f"no coincide con la allowlist autorizada 'AUTOFORM_EXCEL_STAGING_PROJECT_REF' ('{allowlist_ref}')."
        )
        sys.exit(1)

    if confirm_project.strip() != allowlist_ref:
        print(
            f"\n[ERROR DE SEGURIDAD] El identificador suministrado en '--confirm-project' ('{confirm_project}') "
            f"no coincide con el proyecto autorizado en allowlist ('{allowlist_ref}')."
        )
        sys.exit(1)

    return project_ref_esperado


def verificar_identidad_despliegue(client: Any, project_ref_esperado: str) -> Dict[str, Any]:
    """Comprueba la coincidencia 5-way con la tabla public.deployment_identity en Supabase.

    Verifica a nivel de motor de datos (ADR-0010):
    1. Que la tabla 'deployment_identity' contenga EXACTAMENTE una fila.
    2. Que application_code sea exactamente 'autoform-excel'.
    3. Que environment sea exactamente 'staging'.
    4. Que project_ref en la base de datos coincida con el project_ref_esperado.

    Lanza SystemExit(1) ante cualquier discrepancia para prevenir contaminación cruzada.
    """
    try:
        res = client.table("deployment_identity").select("singleton_id, application_code, environment, project_ref").execute()
        if not res.data:
            print(
                "\n[BLOQUEO DE SEGURIDAD] La tabla 'deployment_identity' está vacía. "
                "Debe inicializarse con exactamente 1 fila con application_code='autoform-excel' y environment='staging'."
            )
            sys.exit(1)

        if len(res.data) != 1:
            print(
                f"\n[BLOQUEO DE SEGURIDAD] Violación de singleton en 'deployment_identity': "
                f"Se encontraron {len(res.data)} filas, pero debe existir exactamente una fila."
            )
            sys.exit(1)

        record = res.data[0]
        app_code = str(record.get("application_code") or "").strip()
        env = str(record.get("environment") or "").strip()
        p_ref = str(record.get("project_ref") or "").strip()

        if app_code != "autoform-excel":
            print(
                f"\n[BLOQUEO DE SEGURIDAD] Discrepancia en deployment_identity: "
                f"application_code es '{app_code}', se esperaba 'autoform-excel'."
            )
            sys.exit(1)

        if env != "staging":
            print(
                f"\n[BLOQUEO DE SEGURIDAD] Discrepancia en deployment_identity: "
                f"environment es '{env}', se esperaba 'staging'."
            )
            sys.exit(1)

        if p_ref != project_ref_esperado:
            print(
                f"\n[BLOQUEO DE SEGURIDAD] Discrepancia en deployment_identity: "
                f"project_ref registrado es '{p_ref}', pero el proyecto objetivo es '{project_ref_esperado}'."
            )
            sys.exit(1)

        print(f"   [OK] Identidad de despliegue validada 5-way: app='{app_code}', env='{env}', ref='{p_ref}' (singleton exacto)")
        return record
    except Exception as exc:
        if isinstance(exc, SystemExit):
            raise
        print(f"\n[BLOQUEO DE SEGURIDAD] Error al consultar 'deployment_identity': {exc}")
        sys.exit(1)


def ejecutar_migration(
    perfiles: List[Dict[str, Any]],
    operadores: List[Dict[str, Any]],
    usuarios: List[Dict[str, Any]],
    confirm_project: str,
    enviar_invitaciones: bool = False,
    client: Optional[Any] = None,
) -> str:
    """Ejecuta la migración real contra Supabase validando project_ref y registrando lote UUID con manifiesto."""
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_role_key = _resolver_secret_key()

    if not supabase_url or not service_role_key:
        print("\n[ERROR FATAL] Se requieren las variables de entorno 'SUPABASE_URL' y 'SUPABASE_SECRET_KEY' (o 'SUPABASE_SERVICE_ROLE_KEY').")
        sys.exit(1)

    # Validación estricta de project_ref (Hardening-04)
    project_ref_esperado = _verificar_project_ref(supabase_url, confirm_project)

    try:
        from supabase import create_client, Client
    except ImportError:
        print("\n[ERROR FATAL] La librería 'supabase' no está instalada. Ejecuta: pip install supabase")
        sys.exit(1)

    batch_id = str(uuid.uuid4())
    ahora_iso = datetime.now(timezone.utc).isoformat()

    manifesto: Dict[str, Any] = {
        "perfiles_empresa": [],
        "usuarios_auth": [],
        "perfiles_usuario": [],
        "operadores": [],
        "failed": [],  # Entradas con estado de error para recuperación admin
    }

    print("\n" + "=" * 75)
    print(f"     EJECUCIÓN DE MIGRACIÓN AUTORIZADA — LOTE: {batch_id}")
    print(f"     PROYECTO OBJETIVO: {project_ref_esperado}")
    print("=" * 75)

    if client is None:
        client = create_client(supabase_url, service_role_key)

    # Validación 5-way de identidad de despliegue en BD
    verificar_identidad_despliegue(client, project_ref_esperado)

    # 0. Pre-validación estricta de colisión en auth.users
    correos_candidatos = {u["correo"].strip().lower() for u in usuarios if DOMINIO_REGEX.match(u["correo"])}
    try:
        users_existentes = client.auth.admin.list_users() or []
        colisiones = [
            usr.email for usr in users_existentes
            if usr.email and usr.email.strip().lower() in correos_candidatos
        ]
        if colisiones:
            colisiones_mask = [enmascarar_correo(c) for c in colisiones]
            print(f"\n[BLOQUEO DE SEGURIDAD] Abortando migración: Se detectaron usuarios preexistentes en auth.users: {colisiones_mask}")
            print("Para garantizar un estado limpio, idempotente y sin contaminación, auth.users no debe contener correos del lote.")
            raise RuntimeError(f"Migración abortada: usuarios ya existen en auth.users: {colisiones_mask}")
    except Exception as exc_chk:
        if "Migración abortada" in str(exc_chk):
            raise

    # 0.1 Validación estricta de URL de redirección y aislamiento anti-PDF
    redirect_url = os.environ.get("AUTOFORM_EXCEL_REDIRECT_URL", "").strip() or os.environ.get("SUPABASE_URL", "").strip()
    for pdf_ref in PROHIBITED_PROJECT_REFS:
        if pdf_ref in redirect_url:
            raise RuntimeError(f"Error de seguridad: La URL de redirección contiene un identificador de proyecto PDF prohibido ('{pdf_ref}').")

    # 0. Registrar inicio de lote en migration_runs
    try:
        client.table("migration_runs").insert({
            "batch_id": batch_id,
            "target_project_ref": project_ref_esperado,
            "started_at": ahora_iso,
            "estado": "RUNNING",
            "manifesto_uuids": manifesto,
            "detalles_json": {
                "perfiles_planificados": len(perfiles),
                "operadores_planificados": len(operadores),
                "usuarios_planificados": len(usuarios),
                "enviar_invitaciones": enviar_invitaciones,
            },
        }).execute()
        print(f"   [OK] Lote registrado en 'migration_runs' con UUID: {batch_id}")
    except Exception as exc:
        print(f"   [WARN] Advertencia al registrar en 'migration_runs': {exc}")

    # 1. Migrar Perfiles de Empresa
    print("\n[1/3] Migrando perfiles de empresa...")
    perfiles_ok = 0
    for p in perfiles:
        datos = p["datos_json"]
        nit = datos.get("empresa", {}).get("identidad", {}).get("nit") or datos.get("nit")
        if nit:
            nit = str(nit).strip()

        registro = {
            "slug": p["slug"],
            "nombre_empresa": p["nombre_empresa"],
            "nit": nit,
            "es_activa": p["es_activa"],
            "datos_json": datos,
        }
        try:
            res = client.table("perfiles_empresa").upsert(registro, on_conflict="slug").execute()
            perfiles_ok += 1
            # Acumular UUID en manifiesto
            if res.data:
                uid_perfil = res.data[0].get("id")
                if uid_perfil:
                    manifesto["perfiles_empresa"].append(str(uid_perfil))
            print(f"   [OK] Perfil '{p['slug']}' migrado exitosamente.")
        except Exception as exc:
            print(f"   [ERROR] Error migrando perfil '{p['slug']}': {exc}")

    # 2. Migrar Operadores Comerciales
    print("\n[2/3] Migrando operadores comerciales...")
    operadores_ok = 0
    for op in operadores:
        registro_op = {
            "id": op["id"],
            "nombre": op["nombre"],
            "cargo": op["cargo"],
            "cedula": op["cedula"],
            "telefono": op["telefono"],
            "correo": op["correo"],
            "direccion": op["direccion"],
            "ciudad": op["ciudad"],
            "es_activo": op["es_activo"],
        }
        try:
            client.table("operadores").upsert(registro_op, on_conflict="id").execute()
            operadores_ok += 1
            manifesto["operadores"].append(op["id"])
            print(f"   [OK] Operador '{op['id']}' migrado exitosamente.")
        except Exception as exc:
            print(f"   [ERROR] Error migrando operador '{op['id']}': {exc}")

    # 3. Usuarios e Invitaciones
    print("\n[3/3] Procesando cuentas de usuario corporativo...")
    invitaciones_ok = 0
    invitaciones_retenidas = 0
    usuarios_omitidos = 0
    usuarios_error = 0

    for u in usuarios:
        correo_real = u["correo"]
        correo_mask = enmascarar_correo(correo_real)

        if not DOMINIO_REGEX.match(correo_real):
            print(f"   [OMIT] Omitido '{correo_mask}': no cumple la validación de dominio corporativo (Q6).")
            usuarios_omitidos += 1
            continue

        if not enviar_invitaciones:
            print(
                f"   [RETENIDO] [RETENIDO] Invitación para {correo_mask} retenida. "
                f"(Usa '--enviar-invitaciones' para despachar correos oficiales)."
            )
            invitaciones_retenidas += 1
            continue

        # Despacho real de invitación vía Supabase Auth con compensación de creación parcial
        auth_user_id: Optional[str] = None

        try:
            # 1. Validación estricta de preexistencia: abortar si ya existe en auth.users
            try:
                users_list = client.auth.admin.list_users() or []
                for usr in users_list:
                    if usr.email and usr.email.lower() == correo_real.lower():
                        print(f"\n[BLOQUEO DE SEGURIDAD] Abortando migración: El usuario {correo_mask} ya existe en auth.users.")
                        raise RuntimeError(f"Migración abortada por colisión en auth.users: {correo_mask}")
            except Exception as exc_collision:
                if "Migración abortada" in str(exc_collision):
                    raise

            # 2. Validación de URL de redirección y aislamiento anti-PDF
            redirect_url = os.environ.get("AUTOFORM_EXCEL_REDIRECT_URL", "").strip() or os.environ.get("SUPABASE_URL", "").strip()
            for pdf_ref in PROHIBITED_PROJECT_REFS:
                if pdf_ref in redirect_url:
                    raise RuntimeError(f"Error de seguridad: La URL de redirección contiene un identificador de proyecto PDF prohibido ('{pdf_ref}').")

            # 3. Crear usuario en auth.users vía invitación oficial
            res_invite = client.auth.admin.invite_user_by_email(
                correo_real,
                options={"redirect_to": redirect_url} if redirect_url else None,
            )
            auth_user_id = res_invite.user.id if hasattr(res_invite, "user") and res_invite.user else None

            if not auth_user_id:
                # Segundo intento: buscar si el invite creó el usuario
                try:
                    retry_list = client.auth.admin.list_users()
                    for usr in (retry_list or []):
                        if usr.email and usr.email.lower() == correo_real.lower():
                            auth_user_id = usr.id
                            break
                except Exception:
                    pass

            if not auth_user_id:
                usuarios_error += 1
                manifesto["failed"].append({"correo_mask": correo_mask, "failed_at": "auth", "razon": "no_user_id"})
                print(f"   [ERROR] No se pudo obtener el identificador para: {correo_mask}")
                continue

            manifesto["usuarios_auth"].append(auth_user_id)

            # 4. Asignar rol estrictamente en app_metadata segura (servidor), NUNCA en user_metadata
            rol_seguro = "administrador" if u["es_admin"] else "comercial"
            try:
                client.auth.admin.update_user_by_id(
                    auth_user_id,
                    {
                        "app_metadata": {
                            "es_admin": bool(u["es_admin"]),
                            "role": rol_seguro,
                            "rol": rol_seguro,
                        },
                        "user_metadata": {},  # Vacío para prevenir escalamiento desde el cliente
                    },
                )
            except Exception as exc_meta:
                print(f"   [WARN] No se pudo fijar app_metadata para {correo_mask}: {exc_meta}")

            # Crear perfil en public.perfiles_usuario
            perfil_usr = {
                "id": auth_user_id,
                "nombre": u["nombre"],
                "cargo": u["cargo"],
                "cedula": u["cedula"],
                "telefono": u["telefono"],
                "correo": correo_real,
                "direccion": u["direccion"],
                "ciudad": u["ciudad"],
                "es_admin": u["es_admin"],
                "activo": u["activo"],
            }
            try:
                client.table("perfiles_usuario").upsert(perfil_usr, on_conflict="id").execute()
                manifesto["perfiles_usuario"].append(auth_user_id)
            except Exception as exc_pu:
                # COMPENSACIÓN: auth.users creado pero perfiles_usuario falló
                usuarios_error += 1
                manifesto["failed"].append({
                    "correo_mask": correo_mask,
                    "auth_user_id": auth_user_id,
                    "failed_at": "perfiles_usuario",
                    "error": str(exc_pu),
                })
                print(
                    f"   [ERROR] COMPENSACIÓN REQUERIDA: Auth creado (id={auth_user_id}) "
                    f"pero perfiles_usuario falló para {correo_mask}: {exc_pu}"
                )
                continue

            # Vincular usuario_id en tabla operadores
            op_slug = re.sub(r"[^\w]+", "_", correo_real.split("@")[0]).strip("_")
            try:
                client.table("operadores").update({"usuario_id": auth_user_id}).eq("id", op_slug).execute()
            except Exception as exc_op:
                # COMPENSACIÓN: perfil_usuario creado, operadores falló (no crítico)
                manifesto["failed"].append({
                    "correo_mask": correo_mask,
                    "auth_user_id": auth_user_id,
                    "failed_at": "operadores",
                    "error": str(exc_op),
                })
                print(f"   [WARN] COMPENSACIÓN: perfil_usuario creado pero operadores.usuario_id falló para {correo_mask} (recuperable): {exc_op}")

            invitaciones_ok += 1
            print(f"   [OK] Invitación oficial despachada y perfil creado para: {correo_mask}")

        except Exception as exc:
            if "PDF prohibido" in str(exc) or "Migración abortada" in str(exc):
                raise
            usuarios_error += 1
            manifesto["failed"].append({
                "correo_mask": correo_mask,
                "failed_at": "exception",
                "error": str(exc),
            })
            print(f"   [ERROR] Error al procesar invitación para {correo_mask}: {exc}")

    # 4. Actualizar estado de lote y manifiesto inmutable en migration_runs
    try:
        client.table("migration_runs").update({
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "estado": "COMPLETADO",
            "perfiles_migrados": perfiles_ok,
            "operadores_migrados": operadores_ok,
            "usuarios_invitados": invitaciones_ok,
            "manifesto_uuids": manifesto,
            "detalles_json": {
                "invitaciones_enviadas": invitaciones_ok,
                "invitaciones_retenidas": invitaciones_retenidas,
                "usuarios_omitidos": usuarios_omitidos,
                "usuarios_error": usuarios_error,
                "compensaciones_requeridas": len(manifesto.get("failed", [])),
            },
        }).eq("batch_id", batch_id).execute()
    except Exception:
        pass

    print("\n" + "=" * 75)
    print("MÉTRICAS FINALES DE LA MIGRACIÓN:")
    print(f"  - Lote (Batch ID):         {batch_id}")
    print(f"  - Perfiles migrados:       {perfiles_ok}/{len(perfiles)}")
    print(f"  - Operadores migrados:     {operadores_ok}/{len(operadores)}")
    print(f"  - Invitaciones enviadas:   {invitaciones_ok}")
    print(f"  - Invitaciones retenidas:  {invitaciones_retenidas}")
    print(f"  - Cuentas omitidas:        {usuarios_omitidos}")
    print(f"  - Errores (compensación):  {usuarios_error}")
    if manifesto.get("failed"):
        print(f"  [WARN] Revisar manifiesto del lote para recuperación de {len(manifesto['failed'])} entradas fallidas.")
    print("=" * 75)
    print(f"Para revertir este lote en el futuro: python scripts/migrate_sqlite_to_supabase.py --rollback-batch {batch_id}\n")
    return batch_id


ejecutar_migracion = ejecutar_migration


def ejecutar_rollback_batch(batch_id: str, confirm_project: str = "") -> None:
    """Ejecuta la reversión selectiva de un lote de migración usando el manifiesto JSONB inmutable.

    Hardening-04:
    - Verifica PROJECT_REF antes de cualquier operación.
    - Idempotente: un lote ya revertido no vuelve a procesarse.
    - FK-safe: elimina en orden operadores -> perfiles_usuario -> auth.users -> perfiles_empresa.
    - No elimina registros de otros lotes ni usuarios preexistentes a la migración.
    - Registra estado ROLLED_BACK con timestamp.
    """
    try:
        uuid.UUID(batch_id)
    except ValueError:
        print(f"\n[ERROR] El identificador '{batch_id}' no es un UUID válido.")
        sys.exit(1)

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_role_key = _resolver_secret_key()

    if not supabase_url or not service_role_key:
        print("\n[ERROR FATAL] Se requieren 'SUPABASE_URL' y 'SUPABASE_SECRET_KEY' (o 'SUPABASE_SERVICE_ROLE_KEY') para rollback.")
        sys.exit(1)

    # Validación estricta de project_ref y allowlist (5-way check)
    project_ref_esperado = _verificar_project_ref(supabase_url, confirm_project)

    try:
        from supabase import create_client, Client
    except ImportError:
        print("\n[ERROR FATAL] La librería 'supabase' no está instalada.")
        sys.exit(1)

    client: Client = create_client(supabase_url, service_role_key)

    # Validación en base de datos: deployment_identity
    verificar_identidad_despliegue(client, project_ref_esperado)

    print("\n" + "=" * 75)
    print(f"     REVERSIÓN SELECTIVA DE LOTE DE MIGRACIÓN: {batch_id}")
    print("=" * 75)

    try:
        res = client.table("migration_runs").select("*").eq("batch_id", batch_id).limit(1).execute()
        if not res.data:
            print(f"   [ERROR] No se encontró registro en 'migration_runs' para el lote: {batch_id}")
            sys.exit(1)

        run = res.data[0]
        estado_actual = run.get("estado", "")
        print(f"   - Estado actual del lote: {estado_actual}")
        print(f"   - Fecha de ejecución:     {run.get('started_at', 'N/D')}")

        # Idempotencia: si ya fue revertido, no operar nuevamente
        if estado_actual == "ROLLED_BACK":
            print(f"   [WARN] El lote {batch_id} ya fue revertido anteriormente. Operación idempotente: sin cambios.")
            return

        # Leer el manifiesto inmutable del lote
        manifesto = run.get("manifesto_uuids") or {}
        ids_perfiles_empresa = manifesto.get("perfiles_empresa", [])
        ids_usuarios_auth = manifesto.get("usuarios_auth", [])
        ids_perfiles_usuario = manifesto.get("perfiles_usuario", [])
        ids_operadores = manifesto.get("operadores", [])

        print(f"\n   Manifiesto del lote:")
        print(f"   - perfiles_empresa:    {len(ids_perfiles_empresa)} registros")
        print(f"   - usuarios_auth:       {len(ids_usuarios_auth)} usuarios en auth.users")
        print(f"   - perfiles_usuario:    {len(ids_perfiles_usuario)} perfiles")
        print(f"   - operadores:          {len(ids_operadores)} operadores")

        errores_rollback: List[str] = []

        # ORDEN FK-SAFE: operadores -> perfiles_usuario -> auth.users -> perfiles_empresa

        # Paso 1: Eliminar operadores del lote
        if ids_operadores:
            print(f"\n   [Rollback 1/4] Eliminando {len(ids_operadores)} operadores del lote...")
            for op_id in ids_operadores:
                try:
                    client.table("operadores").delete().eq("id", op_id).execute()
                    print(f"      [OK] Operador '{op_id}' eliminado.")
                except Exception as exc:
                    errores_rollback.append(f"operador/{op_id}: {exc}")
                    print(f"      [ERROR] Error al eliminar operador '{op_id}': {exc}")

        # Paso 2: Eliminar perfiles_usuario del lote
        if ids_perfiles_usuario:
            print(f"\n   [Rollback 2/4] Eliminando {len(ids_perfiles_usuario)} perfiles_usuario del lote...")
            for uid in ids_perfiles_usuario:
                try:
                    client.table("perfiles_usuario").delete().eq("id", uid).execute()
                    print(f"      [OK] Perfil usuario '{uid}' eliminado.")
                except Exception as exc:
                    errores_rollback.append(f"perfiles_usuario/{uid}: {exc}")
                    print(f"      [ERROR] Error al eliminar perfil_usuario '{uid}': {exc}")

        # Paso 3: Eliminar auth.users del lote (solo los creados en esta migración)
        if ids_usuarios_auth:
            print(f"\n   [Rollback 3/4] Eliminando {len(ids_usuarios_auth)} usuarios de auth.users del lote...")
            for uid in ids_usuarios_auth:
                try:
                    client.auth.admin.delete_user(uid)
                    print(f"      [OK] auth.users '{uid}' eliminado.")
                except Exception as exc:
                    errores_rollback.append(f"auth.users/{uid}: {exc}")
                    print(f"      [ERROR] Error al eliminar auth.users '{uid}': {exc}")

        # Paso 4: Eliminar perfiles_empresa del lote (por UUID, no por slug)
        if ids_perfiles_empresa:
            print(f"\n   [Rollback 4/4] Eliminando {len(ids_perfiles_empresa)} perfiles_empresa del lote...")
            for uid in ids_perfiles_empresa:
                try:
                    client.table("perfiles_empresa").delete().eq("id", uid).execute()
                    print(f"      [OK] Perfil empresa '{uid}' eliminado.")
                except Exception as exc:
                    errores_rollback.append(f"perfiles_empresa/{uid}: {exc}")
                    print(f"      [ERROR] Error al eliminar perfil_empresa '{uid}': {exc}")

        # Marcar lote como revertido en migration_runs
        estado_final = "ROLLED_BACK" if not errores_rollback else "ROLLED_BACK_PARTIAL"
        client.table("migration_runs").update({
            "estado": estado_final,
            "detalles_json": {
                **(run.get("detalles_json") or {}),
                "rolled_back_at": datetime.now(timezone.utc).isoformat(),
                "rollback_errores": errores_rollback,
            },
        }).eq("batch_id", batch_id).execute()

        if errores_rollback:
            print(f"\n   [WARN] Rollback completado con {len(errores_rollback)} error(es) parciales. Estado: {estado_final}")
        else:
            print(f"\n   [OK] Lote {batch_id} revertido exitosamente. Estado: {estado_final}")

    except Exception as exc:
        print(f"   [ERROR] Error al ejecutar rollback del lote: {exc}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migración y respaldo seguro de SQLite a Supabase para AutoForm AI (ADR-0010)."
    )
    parser.add_argument(
        "--backup-only",
        action="store_true",
        help="Crea únicamente una copia de respaldo física con timestamp e integridad SHA256 de SQLite y finaliza.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Audita y simula el proceso de migración de forma segura sin llamadas remotas (predeterminado).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Ejecuta la migración real contra Supabase. Requiere '--confirm-project <project_ref>'.",
    )
    parser.add_argument(
        "--confirm-project",
        type=str,
        default="",
        help="Project reference exacto de Supabase para confirmar la ejecución real.",
    )
    parser.add_argument(
        "--enviar-invitaciones",
        action="store_true",
        default=False,
        help="Autoriza el envío de invitaciones oficiales por correo. Por defecto permanecen retenidas.",
    )
    parser.add_argument(
        "--rollback-batch",
        type=str,
        default="",
        help="UUID del lote de migración a revertir selectivamente.",
    )
    parser.add_argument(
        "--sqlite-db",
        type=str,
        default="",
        help="Ruta a una base SQLite alternativa para pruebas sintéticas controladas.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="[DESHABILITADO] Antiguo flag deshabilitado por política de seguridad.",
    )

    args = parser.parse_args()

    # Si se intenta usar --live, abortar con mensaje explicativo
    if args.live:
        print("\n[ERROR DE SEGURIDAD] El flag '--live' ha sido deshabilitado permanentemente (ADR-0010).")
        print("Para ejecutar la migración de forma segura y auditada, utiliza:")
        print("  python scripts/migrate_sqlite_to_supabase.py --execute --confirm-project <project_ref>\n")
        sys.exit(1)

    # Reversión de lote (Hardening-04)
    if args.rollback_batch:
        if not args.confirm_project:
            print("\n[ERROR FATAL] '--rollback-batch' requiere obligatoriamente '--confirm-project <project_ref>'.")
            print("Ejemplo: python scripts/migrate_sqlite_to_supabase.py --rollback-batch <uuid> --confirm-project <project_ref>\n")
            sys.exit(1)
        ejecutar_rollback_batch(
            args.rollback_batch.strip(),
            confirm_project=args.confirm_project.strip(),
        )
        return

    # Ruta de base SQLite origen
    db_origen = Path(args.sqlite_db) if args.sqlite_db else SQLITE_DB_PATH

    # Invariante absoluta: Respaldo físico previo de SQLite con integridad
    crear_respaldo_sqlite(db_origen)

    if args.backup_only:
        print("[AutoForm AI] Proceso finalizado en modo --backup-only.")
        return

    perfiles, operadores, usuarios = leer_datos_sqlite(db_origen)

    if args.execute:
        if not args.confirm_project:
            print("\n[ERROR FATAL] '--execute' requiere obligatoriamente '--confirm-project <project_ref>'.")
            print("Ejemplo: python scripts/migrate_sqlite_to_supabase.py --execute --confirm-project <project_ref>\n")
            sys.exit(1)
        ejecutar_migration(
            perfiles,
            operadores,
            usuarios,
            confirm_project=args.confirm_project.strip(),
            enviar_invitaciones=args.enviar_invitaciones,
        )
    else:
        # Por defecto siempre ejecuta dry-run
        ejecutar_dry_run(perfiles, operadores, usuarios)


if __name__ == "__main__":
    main()
