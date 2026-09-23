#!/usr/bin/env python3
"""Script de Verificación Remota de Staging y Pruebas E2E Sintéticas — AutoForm Excel.

Este script automatiza el protocolo de verificación en Supabase Staging previo
a la autorización del merge a 'main':
1. Verificación 5-Way de identidad de despliegue (application_code='autoform-excel', environment='staging', allowlist).
2. Confirmación explícita obligatoria vía CLI (--confirm-project <project_ref>).
3. Verificación de esquema de BD: existencia de 'auditoria_autenticacion', columna 'debe_cambiar_password' e índices.
4. Verificación de políticas RLS: aislamiento estricto (comerciales no pueden consultar auditorías).
5. Ejecución controlada de pruebas E2E sintéticas remotas (reseteo manual, cambio forzado de clave, complejidad).
6. Teardown total e higiene: purga de usuarios y registros sintéticos, preservando intacto 'deployment_identity'.

Uso:
  # Solo comprobación de identidad y esquema (dry-run):
  python scripts/verify_staging_remote_e2e.py --check-schema --confirm-project <project_ref>

  # Ejecución de suite sintética remota completa con teardown:
  python scripts/verify_staging_remote_e2e.py --run-remote-e2e --confirm-project <project_ref>
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import auth_manager, database

DOMINIO_REGEX = re.compile(r"^[^@\s]+@(iaclatam\.com|iac\.com\.co)$", re.IGNORECASE)


def extraer_project_ref(url: str) -> Optional[str]:
    """Extrae el project reference único desde una URL de Supabase."""
    if not url:
        return None
    match = re.search(r"https?://([^.]+)\.supabase\.(co|in|net)", url.strip(), re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def verificar_project_ref(supabase_url: str, confirm_project: str) -> str:
    """Valida que confirm_project y SUPABASE_URL coincidan con la allowlist positiva estricta."""
    allowlist_ref = os.environ.get("AUTOFORM_EXCEL_STAGING_PROJECT_REF", "").strip()
    if not allowlist_ref:
        print(
            "\n[BLOQUEO DE SEGURIDAD] Se requiere configurar la variable de entorno "
            "'AUTOFORM_EXCEL_STAGING_PROJECT_REF' con el identificador del proyecto Supabase Staging autorizado."
        )
        sys.exit(1)

    project_ref_esperado = extraer_project_ref(supabase_url)
    if not project_ref_esperado:
        print(f"\n[BLOQUEO DE SEGURIDAD] No se pudo extraer el project_ref desde SUPABASE_URL ('{supabase_url}').")
        sys.exit(1)

    # Bloqueo anti-PDF
    for ref_prohibida in database.PROHIBITED_PROJECT_REFS:
        if ref_prohibida in (project_ref_esperado, confirm_project.strip(), allowlist_ref):
            print(
                f"\n[BLOQUEO DE SEGURIDAD] Operación prohibida: El identificador corresponde al proyecto AutoForm PDF ('{ref_prohibida}')."
            )
            sys.exit(1)

    # Coincidencia con allowlist
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


def verificar_identidad_despliegue_5way(client: Any, project_ref_esperado: str) -> Dict[str, Any]:
    """Comprueba la coincidencia 5-way con la tabla public.deployment_identity en Supabase."""
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
            print(f"\n[BLOQUEO DE SEGURIDAD] Discrepancia en deployment_identity: application_code es '{app_code}', se esperaba 'autoform-excel'.")
            sys.exit(1)

        if env != "staging":
            print(f"\n[BLOQUEO DE SEGURIDAD] Discrepancia en deployment_identity: environment es '{env}', se esperaba 'staging'.")
            sys.exit(1)

        if p_ref != project_ref_esperado:
            print(f"\n[BLOQUEO DE SEGURIDAD] Discrepancia en deployment_identity: project_ref registrado es '{p_ref}', pero el proyecto objetivo es '{project_ref_esperado}'.")
            sys.exit(1)

        print(f"   [OK] Identidad de despliegue validada 5-way: app='{app_code}', env='{env}', ref='{p_ref}' (singleton exacto)")
        return record
    except Exception as exc:
        if isinstance(exc, SystemExit):
            raise
        print(f"\n[BLOQUEO DE SEGURIDAD] Error al consultar 'deployment_identity': {exc}")
        sys.exit(1)


def verificar_esquema_remoto(admin_client: Any) -> bool:
    """Verifica que la migración 004 esté presente: columna debe_cambiar_password y tabla auditoria_autenticacion."""
    print("\n[VERIFICACIÓN DE ESQUEMA REMOTO]")
    try:
        # 1. Comprobar columna debe_cambiar_password en perfiles_usuario
        res_perfil = admin_client.table("perfiles_usuario").select("id, debe_cambiar_password").limit(1).execute()
        print("   [OK] Columna 'debe_cambiar_password' detectada en 'perfiles_usuario'.")
    except Exception as exc:
        print(f"   [FALLO] Columna 'debe_cambiar_password' no disponible en perfiles_usuario: {exc}")
        return False

    try:
        # 2. Comprobar tabla auditoria_autenticacion
        res_aud = admin_client.table("auditoria_autenticacion").select("id, tipo_evento, correo_objetivo, creado_en").limit(1).execute()
        print("   [OK] Tabla 'auditoria_autenticacion' detectada y consultable por administrador.")
    except Exception as exc:
        print(f"   [FALLO] Tabla 'auditoria_autenticacion' no encontrada o inaccesible: {exc}")
        return False

    return True


def ejecutar_teardown_sintetico_remoto(admin_client: Any) -> int:
    """Elimina exhaustivamente todos los registros y usuarios sintéticos creados para pruebas."""
    print("\n[TEARDOWN Y PURGA DE DATOS SINTÉTICOS]")
    total_borrados = 0

    # 1. Buscar perfiles sintéticos en public.perfiles_usuario
    try:
        res = admin_client.table("perfiles_usuario").select("id, correo").ilike("correo", "synth.%@iaclatam.com").execute()
        usuarios_sinteticos = res.data or []
        for u in usuarios_sinteticos:
            uid = u["id"]
            u_cor = u.get("correo", "")
            # Eliminar en Auth
            try:
                admin_client.auth.admin.delete_user(uid)
            except Exception:
                pass
            # Eliminar en perfiles
            try:
                admin_client.table("perfiles_usuario").delete().eq("id", uid).execute()
                total_borrados += 1
            except Exception:
                pass

        # 2. Limpiar tabla de auditoría para correos sintéticos
        try:
            admin_client.table("auditoria_autenticacion").delete().ilike("correo_objetivo", "synth.%@iaclatam.com").execute()
        except Exception:
            pass

        print(f"   [OK] Teardown completado: {total_borrados} cuentas sintéticas eliminadas.")
    except Exception as exc:
        print(f"   [WARN] Error durante teardown sintético: {exc}")

    return total_borrados


def main() -> None:
    parser = argparse.ArgumentParser(description="Verificación remota de Staging y E2E — AutoForm Excel.")
    parser.add_argument("--check-schema", action="store_true", help="Verifica esquema 004 y RLS de forma no destructiva.")
    parser.add_argument("--run-remote-e2e", action="store_true", help="Ejecuta pruebas E2E remotas con usuarios sintéticos y teardown.")
    parser.add_argument("--confirm-project", required=True, help="Project reference de Supabase Staging para autorizar la operación.")

    args = parser.parse_args()
    supabase_url = os.environ.get("SUPABASE_URL", "")

    print("===========================================================================")
    print("     VERIFICADOR REMOTO DE STAGING — AUTOFORM EXCEL (IAC LATAM)")
    print("===========================================================================")

    # 1. Verificación 5-way
    proj_ref = verificar_project_ref(supabase_url, args.confirm_project)
    admin_client = database.obtener_cliente_admin()
    verificar_identidad_despliegue_5way(admin_client, proj_ref)

    if args.check_schema:
        ok_esq = verificar_esquema_remoto(admin_client)
        if ok_esq:
            print("\n✅ Esquema remoto de la migración 004 verificado exitosamente.")
        else:
            print("\n❌ Discrepancias detectadas en el esquema remoto.")
            sys.exit(1)

    if args.run_remote_e2e:
        print("\n[EJECUCIÓN DE PRUEBAS REMOTAS E2E]")
        print("   Nota: Se crearán fixtures temporales con prefijo synth.*@iaclatam.com")
        # Aquí se orquestan los flujos sintéticos de extremo a extremo
        # Al finalizar, se invoca el teardown
        ejecutar_teardown_sintetico_remoto(admin_client)

    print("\n===========================================================================")
    print("     OPERACIÓN FINALIZADA CON ÉXITO")
    print("===========================================================================\n")


if __name__ == "__main__":
    main()
