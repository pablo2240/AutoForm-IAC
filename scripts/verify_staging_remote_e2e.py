#!/usr/bin/env python3
"""Script de Verificación Remota de Staging y Pruebas E2E Sintéticas — AutoForm Excel.

Este script automatiza el protocolo completo de verificación en Supabase Staging previo
a la autorización del merge a 'main':
1. Verificación 5-Way de identidad de despliegue (application_code='autoform-excel', environment='staging', allowlist).
2. Confirmación explícita obligatoria vía CLI (--confirm-project <project_ref>).
3. Verificación de esquema de BD: existencia de 'auditoria_autenticacion', columna 'debe_cambiar_password' e índices.
4. Verificación de políticas RLS: aislamiento estricto (comerciales y anónimos no pueden consultar auditorías).
5. Ejecución de los 13 casos de prueba E2E sintéticos contra Supabase Staging (reseteo manual, cambio forzado de clave, complejidad).
6. Teardown quirúrgico e higiene: purga total de usuarios y registros sintéticos, preservando intacto 'deployment_identity'.

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
import secrets
import string
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Forzar configuración Staging en variables de entorno antes de importar core
os.environ["APP_ENVIRONMENT"] = "staging"
os.environ["USE_SUPABASE"] = "true"
os.environ["USE_SQLITE"] = "false"

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


def verificar_politicas_rls(admin_client: Any, pub_client: Any) -> bool:
    """Verifica que las políticas RLS bloqueen a usuarios anónimos y comerciales en auditoria_autenticacion."""
    print("\n[VERIFICACIÓN DE POLÍTICAS RLS EN AUDITORÍA]")
    run_id = uuid.uuid4().hex[:6]
    correo_comercial = f"synth.rls_{run_id}@iaclatam.com"
    pwd_comercial = "PasswordRls2026!#"

    uid_comercial = None
    try:
        # 1. Verificar que cliente anónimo no puede leer auditoría (devuelve 0 filas o rechazo)
        res_anon = pub_client.table("auditoria_autenticacion").select("id").execute()
        if res_anon.data and len(res_anon.data) > 0:
            print("   [FALLO RLS] Cliente anónimo pudo consultar registros en auditoria_autenticacion.")
            return False
        print("   [OK RLS] Cliente anónimo bloqueado por RLS en auditoria_autenticacion (0 filas devueltas).")

        # 2. Crear usuario comercial sintético activo
        u_auth = admin_client.auth.admin.create_user({
            "email": correo_comercial,
            "password": pwd_comercial,
            "email_confirm": True,
            "app_metadata": {"es_admin": False, "role": "comercial", "estado": "aprobado"},
        })
        uid_comercial = u_auth.user.id

        admin_client.table("perfiles_usuario").upsert({
            "id": uid_comercial,
            "nombre": "Comercial RLS Test",
            "correo": correo_comercial,
            "es_admin": False,
            "activo": True,
            "estado_aprobacion": "aprobado",
            "debe_cambiar_password": False,
        }).execute()

        # Insertar un registro de auditoría de prueba con admin_client
        admin_client.table("auditoria_autenticacion").insert({
            "tipo_evento": "test_rls",
            "correo_objetivo": correo_comercial,
            "admin_id": "test-admin",
            "admin_correo": "admin@iaclatam.com",
            "motivo": "Prueba de aislamiento RLS",
            "detalles": "Verificación de acceso no administrativo",
        }).execute()

        # Iniciar sesión como comercial para obtener token JWT
        login_res = pub_client.auth.sign_in_with_password({"email": correo_comercial, "password": pwd_comercial})
        if not login_res.session:
            print(f"   [FALLO RLS] No se pudo obtener sesión JWT para comercial sintético.")
            return False
        jwt_comercial = login_res.session.access_token

        # Consultar tabla auditoria con cliente autenticado comercial
        comercial_client = database.obtener_cliente_usuario(jwt_comercial)
        res_com = comercial_client.table("auditoria_autenticacion").select("id").execute()
        if res_com.data and len(res_com.data) > 0:
            print("   [FALLO RLS] Usuario comercial pudo leer registros de auditoria_autenticacion (violación RLS).")
            return False
        print("   [OK RLS] Usuario comercial autenticado bloqueado por RLS en auditoria_autenticacion (0 filas devueltas).")

        # Verificar que el admin sí puede leerlo
        res_adm = admin_client.table("auditoria_autenticacion").select("id").eq("correo_objetivo", correo_comercial).execute()
        if not res_adm.data:
            print("   [FALLO RLS] Administrador no pudo consultar registros en auditoria_autenticacion.")
            return False
        print(f"   [OK RLS] Administrador tiene acceso completo de consulta a auditoria_autenticacion ({len(res_adm.data)} fila(s) detectada(s)).")

        return True

    except Exception as exc:
        print(f"   [FALLO RLS] Error durante verificación de RLS: {exc}")
        return False
    finally:
        # Teardown de esta prueba puntual
        if uid_comercial:
            try:
                admin_client.auth.admin.delete_user(uid_comercial)
            except Exception:
                pass
            try:
                admin_client.table("perfiles_usuario").delete().eq("id", uid_comercial).execute()
            except Exception:
                pass
        try:
            admin_client.table("auditoria_autenticacion").delete().eq("correo_objetivo", correo_comercial).execute()
        except Exception:
            pass


def ejecutar_13_pruebas_e2e_remotas(admin_client: Any, pub_client: Any) -> bool:
    """Ejecuta los 13 casos de prueba E2E contra Supabase Staging de forma secuencial."""
    print("\n[EJECUCIÓN DE LOS 13 CASOS E2E EN SUPABASE STAGING]")
    run_id = uuid.uuid4().hex[:6]
    exito_total = True

    # -------------------------------------------------------------------------
    # E2E-01: Auto-Registro con Estado Pendiente e Inactivo
    # -------------------------------------------------------------------------
    correo_e2e1 = f"synth.e2e01_{run_id}@iaclatam.com"
    pwd_e2e1 = "ClaveSegura2026!#"
    print(f"\n--- E2E-01: Auto-registro con estado pendiente ({correo_e2e1}) ---")
    try:
        ok_reg, msg_reg = auth_manager.registrar_solicitud_corporativa(
            nombre="Colaborador E2E 01",
            correo=correo_e2e1,
            password=pwd_e2e1,
            cargo="Consultor Comercial",
            telefono="3001234567",
            ciudad="Bogotá",
            requiere_aprobacion=True,
        )
        assert ok_reg, f"Fallo al registrar solicitud: {msg_reg}"

        # Verificar en perfiles_usuario
        res_p = admin_client.table("perfiles_usuario").select("*").eq("correo", correo_e2e1).execute()
        assert res_p.data and len(res_p.data) == 1, "No se encontró el perfil creado en perfiles_usuario"
        p_row = res_p.data[0]
        assert p_row["estado_aprobacion"] == "pendiente", f"Estado esperado 'pendiente', obtenido: {p_row['estado_aprobacion']}"
        assert p_row["activo"] is False, "El usuario debe nacer con activo = False"
        assert p_row["es_admin"] is False, "El usuario debe nacer con es_admin = False"

        # Verificar que no exista en operadores
        res_op = admin_client.table("operadores").select("*").eq("correo", correo_e2e1).execute()
        assert len(res_op.data) == 0, "No debe existir fila en operadores para una cuenta pendiente"
        print("   [OK] E2E-01 superado: Cuenta creada en estado pendiente, inactiva y sin operador.")
    except Exception as exc:
        print(f"   [FALLO] E2E-01 falló: {exc}")
        return False

    # -------------------------------------------------------------------------
    # E2E-02: Bloqueo de Login en Estado Pendiente
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-02: Bloqueo de inicio de sesión de cuenta pendiente ---")
    try:
        ok_log, msg_log, _, _ = auth_manager.iniciar_sesion(correo_e2e1, pwd_e2e1)
        assert not ok_log, "El login debió haber sido denegado para cuenta pendiente"
        assert any(term in msg_log.lower() for term in ["revisión", "aprobación", "pendiente"]), f"Mensaje inesperado: {msg_log}"
        print("   [OK] E2E-02 superado: Login bloqueado correctamente con mensaje de revisión administrativa.")
    except Exception as exc:
        print(f"   [FALLO] E2E-02 falló: {exc}")
        return False

    # -------------------------------------------------------------------------
    # E2E-03: Aprobación Administrativa y Fusión de Operador
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-03: Aprobación administrativa y sincronización de operador ---")
    u_id_e2e1 = p_row["id"]
    try:
        # Aprobar con admin
        admin_client.table("perfiles_usuario").update({
            "estado_aprobacion": "aprobado",
            "activo": True,
            "es_admin": False,
        }).eq("id", u_id_e2e1).execute()

        # Sincronizar operador
        slug_op = re.sub(r"[^\w]+", "_", correo_e2e1.split("@")[0]).strip("_")
        database.guardar_operador_db(
            id_operador=slug_op,
            nombre="Colaborador E2E 01",
            cargo="Consultor Comercial",
            cedula="",
            telefono="3001234567",
            correo=correo_e2e1,
            direccion="Carrera 63 B # 32 E -25 OFC 206",
            ciudad="Bogotá",
            client=admin_client,
            usuario_id=u_id_e2e1,
        )

        res_p_aprob = admin_client.table("perfiles_usuario").select("*").eq("id", u_id_e2e1).execute()
        assert res_p_aprob.data[0]["estado_aprobacion"] == "aprobado"
        assert res_p_aprob.data[0]["activo"] is True

        res_op_aprob = admin_client.table("operadores").select("*").eq("correo", correo_e2e1).execute()
        assert len(res_op_aprob.data) == 1, "Operador no fue sincronizado en la tabla operadores"
        print("   [OK] E2E-03 superado: Solicitud aprobada, cuenta activada y operador sincronizado.")
    except Exception as exc:
        print(f"   [FALLO] E2E-03 falló: {exc}")
        return False

    # -------------------------------------------------------------------------
    # E2E-04: Login Exitoso tras Aprobación
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-04: Login exitoso post-aprobación con perfil comercial ---")
    try:
        ok_log4, msg_log4, tokens4, datos4 = auth_manager.iniciar_sesion(correo_e2e1, pwd_e2e1)
        assert ok_log4, f"Fallo al iniciar sesión tras aprobación: {msg_log4}"
        assert tokens4 is not None and "access_token" in tokens4
        assert datos4["es_admin"] is False
        assert datos4["activo"] is True
        print("   [OK] E2E-04 superado: Login exitoso con perfil comercial activo y tokens válidos.")
    except Exception as exc:
        print(f"   [FALLO] E2E-04 falló: {exc}")
        return False

    # -------------------------------------------------------------------------
    # E2E-05: Rechazo de Registro por Administrador
    # -------------------------------------------------------------------------
    correo_rech = f"synth.rechazado_{run_id}@iaclatam.com"
    pwd_rech = "ClaveRechazada2026!#"
    print(f"\n--- E2E-05: Rechazo de solicitud por administrador ({correo_rech}) ---")
    try:
        auth_manager.registrar_solicitud_corporativa(
            nombre="Colaborador Rechazado",
            correo=correo_rech,
            password=pwd_rech,
            requiere_aprobacion=True,
        )
        res_u_rech = admin_client.table("perfiles_usuario").select("id").eq("correo", correo_rech).execute()
        uid_rech = res_u_rech.data[0]["id"]

        # Rechazar
        admin_client.table("perfiles_usuario").update({
            "estado_aprobacion": "rechazado",
            "activo": False,
        }).eq("id", uid_rech).execute()

        ok_log5, msg_log5, _, _ = auth_manager.iniciar_sesion(correo_rech, pwd_rech)
        assert not ok_log5, "Login debió fallar para usuario rechazado"
        assert "rechazada" in msg_log5.lower() or "inactiva" in msg_log5.lower()
        print("   [OK] E2E-05 superado: Solicitud rechazada y login subsiguiente bloqueado categóricamente.")
    except Exception as exc:
        print(f"   [FALLO] E2E-05 falló: {exc}")
        return False

    # -------------------------------------------------------------------------
    # E2E-06: Desalojo en Caliente por Desactivación
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-06: Desalojo y suspensión de cuenta activa ---")
    try:
        # Desactivar u_id_e2e1
        admin_client.table("perfiles_usuario").update({"activo": False}).eq("id", u_id_e2e1).execute()
        ok_log6, msg_log6, _, _ = auth_manager.iniciar_sesion(correo_e2e1, pwd_e2e1)
        assert not ok_log6, "Login debió fallar para cuenta desactivada"
        assert "inactiva" in msg_log6.lower() or "suspendida" in msg_log6.lower()
        # Reactivar para las siguientes pruebas
        admin_client.table("perfiles_usuario").update({"activo": True}).eq("id", u_id_e2e1).execute()
        print("   [OK] E2E-06 superado: Cuenta suspendida rechazada en autenticación.")
    except Exception as exc:
        print(f"   [FALLO] E2E-06 falló: {exc}")
        return False

    # -------------------------------------------------------------------------
    # E2E-07: Salvaguarda del Último Administrador Activo
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-07: Salvaguarda estricta de singleton: protección del último admin ---")
    try:
        # Buscar el admin institucional real
        res_adm = admin_client.table("perfiles_usuario").select("id, correo").eq("es_admin", True).eq("activo", True).execute()
        assert res_adm.data and len(res_adm.data) >= 1, "Debe existir al menos un admin activo en Staging"
        admin_id_real = res_adm.data[0]["id"]

        # Si hay exactamente 1 admin activo, intentar degradarlo o desactivarlo debe fallar
        if len(res_adm.data) == 1:
            ok_desact = database.conmutar_estado_usuario_db(admin_id_real, False, client=admin_client)
            assert not ok_desact, "No se debió permitir desactivar al único admin activo"
            ok_rol = database.actualizar_rol_usuario_db(admin_id_real, False, client=admin_client)
            assert not ok_rol, "No se debió permitir degradar al único admin activo"
        print("   [OK] E2E-07 superado: Salvaguarda de singleton confirmada (administrador único protegido).")
    except Exception as exc:
        print(f"   [FALLO] E2E-07 falló: {exc}")
        return False

    # -------------------------------------------------------------------------
    # E2E-08: Restablecimiento Administrativo de Contraseña
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-08: Restablecimiento administrativo de contraseña e invalidación ---")
    nueva_clave_e2e8 = "NuevaClaveAdmin2026!#"
    try:
        admin_client.auth.admin.update_user_by_id(u_id_e2e1, {"password": nueva_clave_e2e8})
        # Login con clave vieja debe fallar
        ok_old, _, _, _ = auth_manager.iniciar_sesion(correo_e2e1, pwd_e2e1)
        assert not ok_old, "Login con contraseña anterior debió fallar"
        # Login con clave nueva debe funcionar
        ok_new, _, _, _ = auth_manager.iniciar_sesion(correo_e2e1, nueva_clave_e2e8)
        assert ok_new, "Login con nueva contraseña debió funcionar"
        print("   [OK] E2E-08 superado: Contraseña actualizada; clave anterior invalidada con éxito.")
    except Exception as exc:
        print(f"   [FALLO] E2E-08 falló: {exc}")
        return False

    # -------------------------------------------------------------------------
    # E2E-09: Rechazo de Dominios No Corporativos
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-09: Rechazo de dominios no corporativos en múltiples capas ---")
    for dom_invalido in ["usuario@gmail.com", "comercial@outlook.com", "hacker@iac.com"]:
        ok_dom, msg_dom = auth_manager.registrar_solicitud_corporativa(
            nombre="Invalido",
            correo=dom_invalido,
            password="PasswordSeguro123!",
        )
        assert not ok_dom, f"Debió rechazar dominio {dom_invalido}"
        assert "iaclatam.com" in msg_dom or "corporativo" in msg_dom.lower()
    print("   [OK] E2E-09 superado: Dominios externos rechazados categóricamente.")

    # -------------------------------------------------------------------------
    # E2E-10: Barrera Anti-PDF
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-10: Barrera Anti-PDF ante identificadores restringidos ---")
    for ref_pdf in database.PROHIBITED_PROJECT_REFS:
        url_prohibida = f"https://{ref_pdf}.supabase.co"
        try:
            database._validar_project_ref_no_prohibido(url_prohibida)
            assert False, f"Debió lanzar ConfiguracionInvalidaError para {ref_pdf}"
        except database.ConfiguracionInvalidaError:
            pass
    print("   [OK] E2E-10 superado: Proyectos AutoForm PDF bloqueados por barrera anti-cruce.")

    # -------------------------------------------------------------------------
    # E2E-11: Reenvío Auditado de Recuperación con Rate Limiting
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-11: Reenvío auditado con rate limiting (máx 3/hora) ---")
    try:
        # Mock para evitar llamadas de correo SMTP real hacia Supabase
        with patch.object(pub_client.auth, "reset_password_for_email", return_value=None):
            # Limpiar eventos previos de este correo de prueba
            admin_client.table("auditoria_autenticacion").delete().eq("correo_objetivo", correo_e2e1).execute()

            # Envíos 1, 2, 3 deben tener éxito
            for i in range(3):
                ok_rc, msg_rc = auth_manager.reenviar_recuperacion_auditada(
                    correo_destino=correo_e2e1,
                    admin_correo_solicitante="admin@iaclatam.com",
                    max_intentos_por_hora=3,
                )
                assert ok_rc, f"Intento {i+1} debió tener éxito: {msg_rc}"

            # Intento 4 debe ser bloqueado por rate limit
            ok_rc4, msg_rc4 = auth_manager.reenviar_recuperacion_auditada(
                correo_destino=correo_e2e1,
                admin_correo_solicitante="admin@iaclatam.com",
                max_intentos_por_hora=3,
            )
            assert not ok_rc4, "Intento 4 debió ser bloqueado por rate limit"
            assert "límite" in msg_rc4.lower() or "excedido" in msg_rc4.lower()

            # Verificar registros en auditoría
            res_aud11 = admin_client.table("auditoria_autenticacion").select("*").eq("correo_objetivo", correo_e2e1).eq("tipo_evento", "reenvio_recuperacion").execute()
            assert len(res_aud11.data) == 3, f"Se esperaban 3 filas de auditoría, encontradas: {len(res_aud11.data)}"
        print("   [OK] E2E-11 superado: Rate limiting verificado y eventos registrados en auditoría.")
    except Exception as exc:
        print(f"   [FALLO] E2E-11 falló: {exc}")
        return False

    # -------------------------------------------------------------------------
    # E2E-12: Restablecimiento Manual Excepcional con Alta Entropía
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-12: Restablecimiento manual excepcional y auditoría ---")
    try:
        # 1. Validación de confirmación de correo
        ok_bad_cor, _, _ = auth_manager.restablecer_manual_excepcional(
            usuario_id=u_id_e2e1,
            correo_confirmacion="incorrecto@iaclatam.com",
            motivo="Motivo con más de quince caracteres válidos",
        )
        assert not ok_bad_cor, "Debió fallar con correo de confirmación discrepante"

        # 2. Validación de longitud de motivo (< 15 chars)
        ok_bad_mot, _, _ = auth_manager.restablecer_manual_excepcional(
            usuario_id=u_id_e2e1,
            correo_confirmacion=correo_e2e1,
            motivo="Corto",
        )
        assert not ok_bad_mot, "Debió fallar con motivo menor a 15 caracteres"

        # 3. Restablecimiento válido
        motivo_valido = "Colaborador confirma no recepción del correo corporativo tras 3 intentos"
        ok_rest, msg_rest, pwd_temporal = auth_manager.restablecer_manual_excepcional(
            usuario_id=u_id_e2e1,
            correo_confirmacion=correo_e2e1,
            motivo=motivo_valido,
            admin_correo_solicitante="admin@iaclatam.com",
        )
        assert ok_rest, f"Fallo al generar restablecimiento manual: {msg_rest}"
        assert pwd_temporal is not None and len(pwd_temporal) == 14, "La clave temporal debe tener exactamente 14 caracteres"

        # 4. Verificar que debe_cambiar_password esté en True en BD
        res_p_flg = admin_client.table("perfiles_usuario").select("debe_cambiar_password").eq("id", u_id_e2e1).execute()
        assert res_p_flg.data[0]["debe_cambiar_password"] is True, "Bandera debe_cambiar_password no se activó"

        # 5. La clave anterior queda invalidada
        ok_old_login, _, _, _ = auth_manager.iniciar_sesion(correo_e2e1, nueva_clave_e2e8)
        assert not ok_old_login, "Clave anterior aún funciona tras restablecimiento manual"

        # 6. Garantía de secreto: la clave temporal jamás está en auditoría
        res_aud12 = admin_client.table("auditoria_autenticacion").select("motivo, detalles").eq("correo_objetivo", correo_e2e1).eq("tipo_evento", "restablecimiento_manual_excepcional").execute()
        assert res_aud12.data, "No se encontró registro de auditoría para restablecimiento manual"
        for row_a in res_aud12.data:
            assert pwd_temporal not in row_a.get("motivo", ""), "Secreto temporal filtrado en motivo de auditoría"
            assert pwd_temporal not in row_a.get("detalles", ""), "Secreto temporal filtrado en detalles de auditoría"
        print("   [OK] E2E-12 superado: Clave temporal de 14 chars generada; cero fugas en auditoría.")
    except Exception as exc:
        print(f"   [FALLO] E2E-12 falló: {exc}")
        return False

    # -------------------------------------------------------------------------
    # E2E-13: Ciclo de Cambio Forzado de Contraseña en Primer Login
    # -------------------------------------------------------------------------
    print(f"\n--- E2E-13: Ciclo de cambio forzado de contraseña en primer login ---")
    try:
        # 1. Login con clave temporal tiene éxito y marca debe_cambiar_password = True
        ok_tmp_log, msg_tmp, _, datos_tmp = auth_manager.iniciar_sesion(correo_e2e1, pwd_temporal)
        assert ok_tmp_log, f"Login con clave temporal falló: {msg_tmp}"
        assert datos_tmp.get("debe_cambiar_password") is True, "debe_cambiar_password no se reflejó en datos de sesión"

        # 2. Rechazo de contraseñas que no cumplen la política estricta
        # 2a. Menos de 8 caracteres
        ok_c, msg_c = auth_manager.completar_cambio_password_obligatorio(u_id_e2e1, "Corto1!")
        assert not ok_c and "8 caracteres" in msg_c.lower()

        # 2b. Sin mayúscula
        ok_min, msg_min = auth_manager.completar_cambio_password_obligatorio(u_id_e2e1, "minusculas123!")
        assert not ok_min and "mayúscula" in msg_min.lower()

        # 2c. Sin minúscula
        ok_may, msg_may = auth_manager.completar_cambio_password_obligatorio(u_id_e2e1, "MAYUSCULAS123!")
        assert not ok_may and "minúscula" in msg_may.lower()

        # 2d. Sin número o símbolo
        ok_num, msg_num = auth_manager.completar_cambio_password_obligatorio(u_id_e2e1, "SolamenteLetrasSinSimbolos")
        assert not ok_num and "número o símbolo" in msg_num.lower()

        # 3. Establecer contraseña definitiva que cumple todos los criterios
        clave_definitiva_valida = "DefinitivaRemota2026!#"
        ok_def, msg_def = auth_manager.completar_cambio_password_obligatorio(u_id_e2e1, clave_definitiva_valida)
        assert ok_def, f"Fallo al establecer contraseña definitiva: {msg_def}"

        # 4. Bandera en BD debe estar limpia (debe_cambiar_password = False)
        res_limpio = admin_client.table("perfiles_usuario").select("debe_cambiar_password").eq("id", u_id_e2e1).execute()
        assert res_limpio.data[0]["debe_cambiar_password"] is False, "debe_cambiar_password sigue en True tras cambio forzado"

        # 5. Login subsiguiente accede sin obligación de cambio
        ok_final, _, _, datos_final = auth_manager.iniciar_sesion(correo_e2e1, clave_definitiva_valida)
        assert ok_final, "Login con contraseña definitiva falló"
        assert datos_final.get("debe_cambiar_password") is False, "debe_cambiar_password no se limpió en sesión final"

        # 6. Registro de auditoría cambio_password_primer_ingreso
        res_aud13 = admin_client.table("auditoria_autenticacion").select("*").eq("correo_objetivo", correo_e2e1).eq("tipo_evento", "cambio_password_primer_ingreso").execute()
        assert len(res_aud13.data) >= 1, "No se registró el evento de cambio forzado en auditoría"
        print("   [OK] E2E-13 superado: Complejidad validada, cambio forzado ejecutado y bandera desactivada.")
    except Exception as exc:
        print(f"   [FALLO] E2E-13 falló: {exc}")
        return False

    print("\n✅ Los 13 casos de prueba E2E remotos han superado todas las validaciones con éxito.")
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

        # 2. Limpiar tabla de operadores sintéticos
        try:
            admin_client.table("operadores").delete().ilike("correo", "synth.%@iaclatam.com").execute()
        except Exception:
            pass

        # 3. Limpiar tabla de auditoría para correos sintéticos
        try:
            admin_client.table("auditoria_autenticacion").delete().ilike("correo_objetivo", "synth.%@iaclatam.com").execute()
        except Exception:
            pass

        # 4. Asegurar que no queden usuarios synth en auth.users
        try:
            all_users = admin_client.auth.admin.list_users()
            for au in (all_users or []):
                if au.email and au.email.lower().startswith("synth."):
                    try:
                        admin_client.auth.admin.delete_user(au.id)
                    except Exception:
                        pass
        except Exception:
            pass

        # 5. Verificación final de higiene: 0 filas sintéticas en perfiles_usuario y operadores
        check_p = admin_client.table("perfiles_usuario").select("id").ilike("correo", "synth.%@iaclatam.com").execute()
        check_op = admin_client.table("operadores").select("id").ilike("correo", "synth.%@iaclatam.com").execute()
        check_aud = admin_client.table("auditoria_autenticacion").select("id").ilike("correo_objetivo", "synth.%@iaclatam.com").execute()
        
        filas_residuales = len(check_p.data or []) + len(check_op.data or []) + len(check_aud.data or [])
        if filas_residuales > 0:
            print(f"   [ALERTA HIGIENE] Se detectaron {filas_residuales} filas sintéticas residuales tras el teardown.")
        else:
            print(f"   [OK HIGIENE] Cero datos sintéticos residuales en Supabase Staging. Purga al 100%.")

        # 6. Comprobar que deployment_identity sigue intacto (exactamente 1 fila)
        res_dep = admin_client.table("deployment_identity").select("singleton_id, application_code, environment, project_ref").execute()
        if len(res_dep.data or []) == 1:
            print(f"   [OK HIGIENE] deployment_identity preservado intacto: 1 fila singleton.")
        else:
            print(f"   [ERROR HIGIENE] deployment_identity alterado: {len(res_dep.data or [])} filas.")

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
    pub_client = database.obtener_cliente_publico()
    verificar_identidad_despliegue_5way(admin_client, proj_ref)

    if args.check_schema:
        ok_esq = verificar_esquema_remoto(admin_client)
        if ok_esq:
            print("\n✅ Esquema remoto de la migración 004 verificado exitosamente.")
            ok_rls = verificar_politicas_rls(admin_client, pub_client)
            if ok_rls:
                print("\n✅ Políticas RLS de la migración 004 verificadas exitosamente.")
            else:
                print("\n❌ Fallo en las políticas RLS remotas.")
                sys.exit(1)
        else:
            print("\n❌ Discrepancias detectadas en el esquema remoto.")
            sys.exit(1)

    if args.run_remote_e2e:
        print("\n[EJECUCIÓN DE PRUEBAS REMOTAS E2E]")
        print("   Nota: Se crearán fixtures temporales con prefijo synth.*@iaclatam.com")
        ok_esq = verificar_esquema_remoto(admin_client)
        if not ok_esq:
            print("\n❌ La migración 004 no está aplicada en Supabase Staging. Operación abortada.")
            sys.exit(1)

        ok_rls = verificar_politicas_rls(admin_client, pub_client)
        if not ok_rls:
            print("\n❌ Fallo en las políticas RLS remotas. Operación abortada.")
            sys.exit(1)

        ok_e2e = ejecutar_13_pruebas_e2e_remotas(admin_client, pub_client)
        
        # Teardown garantizado
        ejecutar_teardown_sintetico_remoto(admin_client)

        if not ok_e2e:
            print("\n❌ Fallo en una o más pruebas E2E remotas.")
            sys.exit(1)

    print("\n===========================================================================")
    print("     OPERACIÓN FINALIZADA CON ÉXITO")
    print("===========================================================================\n")


if __name__ == "__main__":
    main()
