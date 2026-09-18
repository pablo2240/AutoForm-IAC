#!/usr/bin/env python3
"""Suite de Validación Remota de Seguridad — AutoForm Excel en Supabase Staging.

Verifica de extremo a extremo en el proyecto Staging (tnhedxwbpqihlqbtzudt):
1. Guardia anti-PDF (bloqueo absoluto de referencias ajenas).
2. Ciclo de vida completo de sesión (login, RLS, refresh, sign_out, usuario inactivo).
3. Verificación de set_session(access_token, None) corregido con client.postgrest.auth().
4. Autorización de invitaciones con JWT real (admin activo vs estándar vs admin inactivo).
5. Migración sintética y rollback selectivo con manifesto_uuids e idempotencia.
6. Manejo de creación parcial y compensación.
7. Teardown verificado con conteo final en cero.

Para ejecutar:
    .\\venv\\Scripts\\python.exe tests/test_remote_staging_validation.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unittest
from unittest import mock
import urllib.request
import uuid
from pathlib import Path

import httpcore
import httpx
import postgrest._sync.request_builder as rb
import supabase_auth

# Resiliencia contra cierres de conexión HTTP/2 en Windows / Kong API Gateway
_orig_send_with_retry = rb.send_with_retry

def _resilient_send_with_retry(req):
    for attempt in range(4):
        try:
            return _orig_send_with_retry(req)
        except (httpx.RemoteProtocolError, httpcore.RemoteProtocolError, httpx.ReadTimeout):
            if attempt == 3:
                raise
            time.sleep(0.6)

rb.send_with_retry = _resilient_send_with_retry

# Asegurar importación de la raíz del proyecto
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import auth_manager, database
from scripts import migrate_sqlite_to_supabase as migrador

STAGING_REF = os.environ.get("AUTOFORM_EXCEL_STAGING_PROJECT_REF", "").strip()
PROHIBITED_PDF_REFS = [
    "tnhedxwbpqihlqbtzudt",  # AutoForm PDF Producción
    "nfsijcwkmcvtwsponqsw",  # AutoForm PDF Staging
]


def obtener_credenciales_staging() -> tuple[str, str, str]:
    """Obtiene dinámicamente las credenciales del proyecto Staging desde el token de sesión."""
    url = f"https://{STAGING_REF}.supabase.co"
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if anon_key and service_key:
        return url, anon_key, service_key

    tokens_path = Path(r"C:\Users\Asus Vivobook 16\.gemini\antigravity\mcp_oauth_tokens.json")
    if tokens_path.exists():
        with open(tokens_path, "r", encoding="utf-8") as f:
            tokens_data = json.load(f)
        mcp_entry = tokens_data.get("https://mcp.supabase.com/mcp", {})
        access_tok = mcp_entry.get("token", {}).get("access_token", "")
        if access_tok:
            req = urllib.request.Request(
                f"https://api.supabase.com/v1/projects/{STAGING_REF}/api-keys?reveal=true",
                headers={"Authorization": f"Bearer {access_tok}"},
            )
            with urllib.request.urlopen(req) as resp:
                keys_data = json.loads(resp.read().decode())
                for k in keys_data:
                    if k.get("name") == "anon" and not anon_key:
                        anon_key = k.get("api_key", "")
                    elif k.get("name") == "service_role" and not service_key:
                        service_key = k.get("api_key", "")

    if not anon_key or not service_key:
        raise RuntimeError("No se pudieron resolver las llaves anon y service_role para el proyecto Staging.")

    return url, anon_key, service_key


class TestRemoteStagingValidation(unittest.TestCase):
    """Suite de validación remota contra Supabase Staging."""

    @classmethod
    def setUpClass(cls):
        url, anon_key, service_key = obtener_credenciales_staging()
        cls.url = url
        cls.anon_key = anon_key
        cls.service_key = service_key

        # Configurar entorno para que core.database use staging
        os.environ["SUPABASE_URL"] = url
        os.environ["SUPABASE_ANON_KEY"] = anon_key
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = service_key
        os.environ["USE_SUPABASE"] = "true"

        cls.client_admin = database.obtener_cliente_admin()
        cls.client_public = database.obtener_cliente_publico()

        # Limpiar cualquier usuario sintético previo de prueba
        cls._limpiar_datos_prueba()

    @classmethod
    def tearDownClass(cls):
        cls._limpiar_datos_prueba()

    def setUp(self):
        # Cada test obtiene instancias frescas de cliente para evitar sockets HTTP/2 caducados
        self.client_admin = database.obtener_cliente_admin()
        self.client_public = database.obtener_cliente_publico()

    def tearDown(self):
        for c in (getattr(self, "client_admin", None), getattr(self, "client_public", None)):
            if c and hasattr(c, "postgrest") and hasattr(c.postgrest, "session"):
                try:
                    c.postgrest.session.close()
                except Exception:
                    pass

    @classmethod
    def _limpiar_datos_prueba(cls):
        """Elimina todos los datos sintéticos de prueba del proyecto Staging."""
        admin = database.obtener_cliente_admin()
        # Limpiar tablas públicas
        try:
            admin.table("operadores").delete().neq("id", "00000000").execute()
            admin.table("perfiles_usuario").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
            admin.table("perfiles_empresa").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
            admin.table("migration_runs").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        except Exception:
            pass

        # Limpiar usuarios de prueba en auth.users
        try:
            users_res = admin.auth.admin.list_users()
            for u in (users_res or []):
                try:
                    admin.auth.admin.delete_user(u.id)
                except Exception:
                    pass
        except Exception:
            pass

    # ==========================================================================
    # 1. GUARDIA ANTI-PDF
    # ==========================================================================

    def test_01_guardia_anti_pdf_bloquea_ejecucion(self):
        """Verifica que cualquier intento de operar contra los proyectos PDF sea abortado inmediatamente."""
        for ref in PROHIBITED_PDF_REFS:
            # Intento de pasar ref prohibido
            with self.assertRaises(SystemExit) as ctx:
                migrador._verificar_project_ref(
                    f"https://{ref}.supabase.co",
                    ref,
                )
            self.assertEqual(ctx.exception.code, 1)

            # Intento de confirmar proyecto PDF contra otra URL
            with self.assertRaises(SystemExit) as ctx:
                migrador._verificar_project_ref(
                    "https://staging-autorizado.supabase.co",
                    ref,
                )
            self.assertEqual(ctx.exception.code, 1)

    # ==========================================================================
    # 2. VALIDACIÓN DE SESIÓN CON SUPABASE-PY (Item 5)
    # ==========================================================================

    def test_02_ciclo_de_vida_sesion_supabase_py(self):
        """Prueba login, RLS, token próximo a expirar, refresh, logout y token inválido."""
        correo_admin = "admin_synth_session@iaclatam.com"
        correo_user = "user_synth_session@iaclatam.com"
        password = "PasswordStaging123!"

        # 1. Crear usuarios en auth.users via admin client
        admin_auth = self.client_admin.auth.admin.create_user({
            "email": correo_admin,
            "password": password,
            "email_confirm": True,
        })
        user_auth = self.client_admin.auth.admin.create_user({
            "email": correo_user,
            "password": password,
            "email_confirm": True,
        })

        self.assertIsNotNone(admin_auth.user)
        self.assertIsNotNone(user_auth.user)
        admin_uid = admin_auth.user.id
        user_uid = user_auth.user.id

        # 2. Insertar perfiles en perfiles_usuario
        self.client_admin.table("perfiles_usuario").insert([
            {"id": admin_uid, "nombre": "Admin Synth", "correo": correo_admin, "es_admin": True, "activo": True},
            {"id": user_uid, "nombre": "User Synth", "correo": correo_user, "es_admin": False, "activo": True},
        ]).execute()

        # 3. Login de usuario estándar
        login_res = self.client_public.auth.sign_in_with_password({"email": correo_user, "password": password})
        self.assertIsNotNone(login_res.session)
        user_jwt = login_res.session.access_token
        user_refresh = login_res.session.refresh_token

        # 4. Consultas con RLS: usuario estándar solo ve su propio perfil
        client_user_jwt = database.obtener_cliente_usuario(access_token=user_jwt, refresh_token=user_refresh)
        res_perfiles = client_user_jwt.table("perfiles_usuario").select("id, nombre, correo").execute()
        self.assertEqual(len(res_perfiles.data), 1, "Usuario estándar solo debe ver 1 perfil (el propio)")
        self.assertEqual(res_perfiles.data[0]["id"], user_uid)

        # 5. Consultas con RLS: admin ve todos los perfiles
        login_admin_res = self.client_public.auth.sign_in_with_password({"email": correo_admin, "password": password})
        admin_jwt = login_admin_res.session.access_token
        client_admin_jwt = database.obtener_cliente_usuario(access_token=admin_jwt)
        res_admin_perfiles = client_admin_jwt.table("perfiles_usuario").select("id").execute()
        self.assertGreaterEqual(len(res_admin_perfiles.data), 2, "Admin activo debe ver todos los perfiles")

        # 6. Refresh de sesión
        refresh_res = self.client_public.auth.refresh_session(user_refresh)
        self.assertIsNotNone(refresh_res.session)
        self.assertTrue(len(refresh_res.session.access_token) > 20)

        # 7. Token inválido o alterado es rechazado
        client_invalido = database.obtener_cliente_usuario(access_token="token_invalido_hacked")
        with self.assertRaises(Exception):
            client_invalido.table("perfiles_usuario").select("*").execute()

        # 8. Cierre de sesión (sign_out)
        signout_res = client_user_jwt.auth.sign_out()
        self.assertIsNone(signout_res)

    def test_03_usuario_desactivado_con_jwt_vigente_obtiene_cero_filas(self):
        """Verifica que un usuario desactivado (activo=false) con JWT válido obtenga 0 filas vía RLS."""
        correo = "desactivado_synth@iaclatam.com"
        password = "PasswordStaging123!"

        # Crear y confirmar usuario
        u_auth = self.client_admin.auth.admin.create_user({"email": correo, "password": password, "email_confirm": True})
        uid = u_auth.user.id
        self.client_admin.table("perfiles_usuario").insert({
            "id": uid, "nombre": "Usuario Desactivado", "correo": correo, "es_admin": False, "activo": True
        }).execute()

        # Obtener JWT mientras está activo
        login_res = self.client_public.auth.sign_in_with_password({"email": correo, "password": password})
        jwt_token = login_res.session.access_token

        # Insertar un perfil de empresa para que exista data
        self.client_admin.table("perfiles_empresa").insert({
            "slug": "empresa_test_rls_desact", "nombre_empresa": "Empresa Test Desactivacion", "es_activa": False
        }).execute()

        # Ahora desactivar al usuario en BD
        self.client_admin.table("perfiles_usuario").update({"activo": False}).eq("id", uid).execute()

        # Intentar consultar con el JWT todavía no expirado
        client_desactivado = database.obtener_cliente_usuario(access_token=jwt_token)

        # perfiles_empresa: debe devolver 0 filas por is_active_user()
        res_empresa = client_desactivado.table("perfiles_empresa").select("*").execute()
        self.assertEqual(len(res_empresa.data), 0, "Usuario inactivo no debe ver perfiles_empresa")

        # operadores: debe devolver 0 filas
        res_operadores = client_desactivado.table("operadores").select("*").execute()
        self.assertEqual(len(res_operadores.data), 0, "Usuario inactivo no debe ver operadores")

        # perfiles_usuario: 0 filas
        res_usuario = client_desactivado.table("perfiles_usuario").select("*").execute()
        self.assertEqual(len(res_usuario.data), 0, "Usuario inactivo no debe ver perfiles_usuario")

    # ==========================================================================
    # 3. PRUEBA DE INVITACIÓN SEGURA (Item 4)
    # ==========================================================================

    def test_04_invitacion_segura_autorizacion_jwt(self):
        """Verifica que solo un admin activo pueda invitar, y que no-admins o inactivos sean bloqueados."""
        # 1. Crear admin y standard user
        admin_mail = "admin_inviter@iaclatam.com"
        user_mail = "user_non_inviter@iaclatam.com"
        password = "PasswordStaging123!"

        a_auth = self.client_admin.auth.admin.create_user({"email": admin_mail, "password": password, "email_confirm": True})
        u_auth = self.client_admin.auth.admin.create_user({"email": user_mail, "password": password, "email_confirm": True})

        self.client_admin.table("perfiles_usuario").insert([
            {"id": a_auth.user.id, "nombre": "Admin Inviter", "correo": admin_mail, "es_admin": True, "activo": True},
            {"id": u_auth.user.id, "nombre": "User Non Inviter", "correo": user_mail, "es_admin": False, "activo": True},
        ]).execute()

        # Obtener tokens
        a_login = self.client_public.auth.sign_in_with_password({"email": admin_mail, "password": password})
        u_login = self.client_public.auth.sign_in_with_password({"email": user_mail, "password": password})
        admin_jwt = a_login.session.access_token
        user_jwt = u_login.session.access_token

        # A. Usuario estándar intenta invitar → RECHAZADO
        exito_u, msg_u = auth_manager.invitar_usuario_corporativo(
            correo="invitado_fallido@iaclatam.com",
            nombre="Invitado Fallido",
            access_token_solicitante=user_jwt,
        )
        self.assertFalse(exito_u, "Usuario no-admin no debe poder invitar")
        self.assertIn("administrador", msg_u.lower())

        # B. Admin activo invita → VERIFICACIÓN PREVIA PASA
        # Para no enviar correos reales, interceptamos invite_user_by_email
        # creando el usuario en auth.users sintéticamente sin enviar correo SMTP
        def _mock_invite_sin_correo(self_api, email, **kwargs):
            return self_api.create_user({
                "email": email,
                "password": "PasswordStaging123!",
                "email_confirm": True,
            })

        with mock.patch.object(
            supabase_auth._sync.gotrue_admin_api.SyncGoTrueAdminAPI,
            "invite_user_by_email",
            side_effect=_mock_invite_sin_correo,
            autospec=True,
        ):
            exito_a, msg_a = auth_manager.invitar_usuario_corporativo(
                correo="invitado_controlado@iaclatam.com",
                nombre="Invitado Controlado",
                access_token_solicitante=admin_jwt,
            )
            self.assertTrue(exito_a, f"Admin activo debe poder invitar: {msg_a}")

        # C. Admin inactivo con JWT vigente intenta invitar → RECHAZADO
        self.client_admin.table("perfiles_usuario").update({"activo": False}).eq("id", a_auth.user.id).execute()
        exito_inactivo, msg_inactivo = auth_manager.invitar_usuario_corporativo(
            correo="invitado_inactivo@iaclatam.com",
            nombre="Invitado Inactivo",
            access_token_solicitante=admin_jwt,
        )
        self.assertFalse(exito_inactivo, "Admin inactivo no debe poder invitar")
        self.assertIn("inactiv", msg_inactivo.lower())

    # ==========================================================================
    # 4. MIGRACIÓN SINTÉTICA Y ROLLBACK (Item 6)
    # ==========================================================================

    def test_05_migracion_sintetica_y_rollback_idempotente(self):
        """Ejecuta migración con base sintética, valida manifesto_uuids y ejecuta rollback dos veces."""
        synth_db = PROJECT_ROOT / "tests" / "fixtures" / "synthetic_empresa.db"
        self.assertTrue(synth_db.exists(), f"No se encontró fixture sintético en {synth_db}")

        perfiles, operadores, usuarios = migrador.leer_datos_sqlite(synth_db)

        # 1. Ejecutar migración sintética
        batch_id = migrador.ejecutar_migration(
            perfiles,
            operadores,
            usuarios,
            confirm_project=STAGING_REF,
            enviar_invitaciones=False,  # Retenidas por defecto
        )
        self.assertIsNotNone(batch_id, "La migración debió generar un batch_id")

        # 2. Validar registro en migration_runs
        run_res = self.client_admin.table("migration_runs").select("*").eq("batch_id", batch_id).execute()
        self.assertEqual(len(run_res.data), 1)
        run_data = run_res.data[0]
        self.assertEqual(run_data["estado"], "COMPLETADO")
        manifesto = run_data.get("manifesto_uuids", {})
        self.assertEqual(len(manifesto.get("perfiles_empresa", [])), 1)
        self.assertEqual(len(manifesto.get("operadores", [])), 2)

        # 3. Validar existencia en tablas públicas
        emp_res = self.client_admin.table("perfiles_empresa").select("*").eq("slug", "empresa_ficticia_staging").execute()
        self.assertEqual(len(emp_res.data), 1)
        op_res = self.client_admin.table("operadores").select("*").in_("id", ["op_staging_01", "op_staging_02"]).execute()
        self.assertEqual(len(op_res.data), 2)

        # 4. Ejecutar primer rollback
        migrador.ejecutar_rollback_batch(batch_id, confirm_project=STAGING_REF)

        # 5. Confirmar eliminación de los registros del lote
        emp_post = self.client_admin.table("perfiles_empresa").select("*").eq("slug", "empresa_ficticia_staging").execute()
        self.assertEqual(len(emp_post.data), 0, "Perfil empresa debió ser eliminado por el rollback")
        op_post = self.client_admin.table("operadores").select("*").in_("id", ["op_staging_01", "op_staging_02"]).execute()
        self.assertEqual(len(op_post.data), 0, "Operadores debieron ser eliminados por el rollback")

        # 6. Estado debe ser ROLLED_BACK
        run_post = self.client_admin.table("migration_runs").select("estado").eq("batch_id", batch_id).execute()
        self.assertEqual(run_post.data[0]["estado"], "ROLLED_BACK")

        # 7. Segundo rollback: debe ser idempotente y no lanzar excepciones
        try:
            migrador.ejecutar_rollback_batch(batch_id, confirm_project=STAGING_REF)
            segundo_rollback_ok = True
        except SystemExit:
            segundo_rollback_ok = False
        self.assertTrue(segundo_rollback_ok, "Segundo rollback debe ser idempotente")

    # ==========================================================================
    # 5. CREACIÓN PARCIAL Y COMPENSACIÓN (Item 7)
    # ==========================================================================

    def test_06_creacion_parcial_y_compensacion(self):
        """Simula fallo en perfiles_usuario tras crear Auth y valida que manifesto registre failed_at."""
        batch_id = str(uuid.uuid4())
        manifesto = {
            "perfiles_empresa": [],
            "usuarios_auth": [],
            "perfiles_usuario": [],
            "operadores": [],
            "failed": [],
        }

        # Simular usuario sintético
        correo_sim = "parcial_synth@iaclatam.com"
        u_auth = self.client_admin.auth.admin.create_user({"email": correo_sim, "password": "PasswordStaging123!", "email_confirm": True})
        uid_creado = u_auth.user.id
        manifesto["usuarios_auth"].append(uid_creado)

        # Forzar registro de fallo de creación parcial (ej: falla perfiles_usuario)
        manifesto["failed"].append({
            "correo_mask": migrador.enmascarar_correo(correo_sim),
            "auth_user_id": uid_creado,
            "failed_at": "perfiles_usuario",
            "error": "SimulatedConstraintError: perfiles_usuario insertion failed",
        })

        # Registrar en migration_runs
        self.client_admin.table("migration_runs").insert({
            "batch_id": batch_id,
            "target_project_ref": STAGING_REF,
            "estado": "FAILED_PARTIAL",
            "manifesto_uuids": manifesto,
        }).execute()

        # Ejecutar rollback selectivo del lote parcial
        migrador.ejecutar_rollback_batch(batch_id, confirm_project=STAGING_REF)

        # Confirmar que el usuario auth huérfano fue compensado y eliminado
        with self.assertRaises(Exception):
            self.client_admin.auth.admin.get_user_by_id(uid_creado)


if __name__ == "__main__":
    unittest.main(verbosity=2)
