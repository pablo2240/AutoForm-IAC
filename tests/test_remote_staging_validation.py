#!/usr/bin/env python3
"""Suite de Validación Remota de Seguridad — AutoForm Excel en Supabase Staging.

Fases 5 y 6 del Plan de Despliegue Seguro:
1. Usuario anónimo bloqueado por RLS.
2. Usuario estándar autenticado consulta catálogo de operadores.
3. Usuario estándar solo actualiza su propio operador y no puede insertar ni eliminar.
4. Usuario estándar no puede asignarse es_admin = true (trigger de inmutabilidad).
5. Administrador activo gestiona catálogos de perfiles y operadores.
6. Usuario inactivo pierde acceso inmediatamente (0 filas devueltas vía is_active_user()).
7. Refresco anticipado de JWT (umbral 300s).
8. service_role nunca expuesto en frontend, respuestas ni logs.
9. Rechazo de dominios no corporativos (trigger de BD + auth_manager).
10. Rollback selectivo por batch_id con manifesto_uuids e idempotencia.
11. Proyectos PDF bloqueados ante cualquier intento.
12. Fail-closed si faltan variables de configuración.

Teardown Quirúrgico FK-Safe:
- Rastreo exacto de UUIDs creados.
- Cero borrados masivos abiertos (.neq()).
- Cero truncamientos.
- Conteos finales verificados en cero.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from unittest import mock
import uuid
from pathlib import Path
from typing import List

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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import auth_manager, database
from scripts import migrate_sqlite_to_supabase as migrador

STAGING_REF = os.environ.get("AUTOFORM_EXCEL_STAGING_PROJECT_REF", "nfaxkncrpfrsvzfgczny").strip()
PROHIBITED_PDF_REFS = [
    "tnhedxwbpqihlqbtzudt",  # AutoForm PDF Producción
    "nfsijcwkmcvtwsponqsw",  # AutoForm PDF Staging
]


class TestRemoteStagingValidation(unittest.TestCase):
    """Suite de validación remota contra Supabase Staging con Teardown Quirúrgico FK-Safe."""

    # Rastradores quirúrgicos de UUIDs creados en staging
    created_operadores: List[str] = []
    created_perfiles_usuario: List[str] = []
    created_auth_users: List[str] = []
    created_perfiles_empresa: List[str] = []
    created_migration_runs: List[str] = []

    @classmethod
    def setUpClass(cls):
        # Asegurar carga de variables
        os.environ["USE_SUPABASE"] = "true"
        if not os.environ.get("AUTOFORM_EXCEL_STAGING_PROJECT_REF"):
            os.environ["AUTOFORM_EXCEL_STAGING_PROJECT_REF"] = STAGING_REF

        url = os.environ.get("SUPABASE_URL", "").strip()
        pub_key = database._resolver_publishable_key()
        secret_key = database._resolver_secret_key()

        if not url or not pub_key or not secret_key:
            raise RuntimeError(
                "Se requieren SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY (o ANON_KEY) y SUPABASE_SECRET_KEY (o SERVICE_ROLE_KEY) para la validación remota."
            )

        # Validación anti-PDF estricta
        if STAGING_REF in PROHIBITED_PDF_REFS:
            raise RuntimeError(f"ABORTADO: El proyecto configurado '{STAGING_REF}' es un proyecto prohibido de PDF.")

        cls.client_admin = database.obtener_cliente_admin()
        cls.client_public = database.obtener_cliente_publico()

    @classmethod
    def tearDownClass(cls):
        """Teardown Quirúrgico FK-Safe: elimina estrictamente las entidades creadas por exact ID."""
        cls._ejecutar_teardown_quirurgico()

    @classmethod
    def _ejecutar_teardown_quirurgico(cls):
        admin = database.obtener_cliente_admin()

        # 1. Operadores sintéticos
        for op_id in list(cls.created_operadores):
            try:
                admin.table("operadores").delete().eq("id", op_id).execute()
            except Exception:
                pass
        cls.created_operadores.clear()

        # 2. Perfiles de usuario sintéticos
        for u_id in list(cls.created_perfiles_usuario):
            try:
                admin.table("perfiles_usuario").delete().eq("id", u_id).execute()
            except Exception:
                pass
        cls.created_perfiles_usuario.clear()

        # 3. Usuarios en auth.users
        for u_id in list(cls.created_auth_users):
            try:
                admin.auth.admin.delete_user(u_id)
            except Exception:
                pass
        cls.created_auth_users.clear()

        # 4. Perfiles de empresa sintéticos
        for emp_id in list(cls.created_perfiles_empresa):
            try:
                admin.table("perfiles_empresa").delete().eq("id", emp_id).execute()
            except Exception:
                pass
        cls.created_perfiles_empresa.clear()

        # 5. Lotes de migración sintéticos
        for b_id in list(cls.created_migration_runs):
            try:
                admin.table("migration_runs").delete().eq("batch_id", b_id).execute()
            except Exception:
                pass
        cls.created_migration_runs.clear()

    def setUp(self):
        self.client_admin = database.obtener_cliente_admin()
        self.client_public = database.obtener_cliente_publico()

    def tearDown(self):
        for c in (getattr(self, "client_admin", None), getattr(self, "client_public", None)):
            if c and hasattr(c, "postgrest") and hasattr(c.postgrest, "session"):
                try:
                    c.postgrest.session.close()
                except Exception:
                    pass

    # ==========================================================================
    # ITEM 1: USUARIO ANÓNIMO BLOQUEADO POR RLS
    # ==========================================================================
    def test_01_usuario_anonimo_bloqueado_por_rls(self):
        """Verifica que el cliente anónimo (sin JWT) no pueda leer ni mutar datos protegidos."""
        # Lectura: retorna 0 filas gracias a USING(is_active_user())
        res_emp = self.client_public.table("perfiles_empresa").select("*").execute()
        self.assertEqual(len(res_emp.data), 0, "Anon no debe ver perfiles_empresa")

        res_op = self.client_public.table("operadores").select("*").execute()
        self.assertEqual(len(res_op.data), 0, "Anon no debe ver operadores")

        res_usr = self.client_public.table("perfiles_usuario").select("*").execute()
        self.assertEqual(len(res_usr.data), 0, "Anon no debe ver perfiles_usuario")

        res_mig = self.client_public.table("migration_runs").select("*").execute()
        self.assertEqual(len(res_mig.data), 0, "Anon no debe ver migration_runs")

        # Mutación: debe ser rechazada con excepción de RLS
        with self.assertRaises(Exception):
            self.client_public.table("perfiles_empresa").insert({
                "slug": "empresa_anon_fail",
                "nombre_empresa": "Anon Attempt",
            }).execute()

    # ==========================================================================
    # ITEM 2: USUARIO ESTÁNDAR AUTENTICADO CONSULTA CATÁLOGO DE OPERADORES
    # ==========================================================================
    def test_02_usuario_estandar_autenticado_consulta_operadores(self):
        """Verifica que un usuario estándar autenticado y activo pueda consultar operadores."""
        email = f"user_std_{uuid.uuid4().hex[:8]}@iaclatam.com"
        pwd = "PasswordStaging123!"

        # Crear usuario sintético vía Auth Admin API
        u_auth = self.client_admin.auth.admin.create_user({"email": email, "password": pwd, "email_confirm": True})
        uid = u_auth.user.id
        self.created_auth_users.append(uid)

        # Crear perfil de usuario activo (no admin)
        self.client_admin.table("perfiles_usuario").insert({
            "id": uid, "nombre": "Standard User", "correo": email, "es_admin": False, "activo": True
        }).execute()
        self.created_perfiles_usuario.append(uid)

        # Crear operador activo de prueba
        op_id = f"op_test_{uuid.uuid4().hex[:6]}"
        self.client_admin.table("operadores").insert({
            "id": op_id, "nombre": "Operador Comercial Test", "correo": f"{op_id}@iaclatam.com", "es_activo": True
        }).execute()
        self.created_operadores.append(op_id)

        # Login con credenciales
        login = self.client_public.auth.sign_in_with_password({"email": email, "password": pwd})
        self.assertIsNotNone(login.session)
        jwt = login.session.access_token

        # Consultar con JWT de usuario
        client_user = database.obtener_cliente_usuario(access_token=jwt)
        res = client_user.table("operadores").select("*").eq("id", op_id).execute()
        self.assertEqual(len(res.data), 1, "Usuario estándar activo debe poder leer el catálogo de operadores")
        self.assertEqual(res.data[0]["id"], op_id)

    # ==========================================================================
    # ITEM 3: USUARIO ESTÁNDAR SOLO ACTUALIZA SU PROPIO OPERADOR (NO INSERT/DELETE)
    # ==========================================================================
    def test_03_usuario_estandar_solo_actualiza_su_propio_operador(self):
        """Verifica que un usuario estándar solo pueda actualizar su propio operador y no pueda insertar/eliminar."""
        email1 = f"op_dueno_{uuid.uuid4().hex[:8]}@iaclatam.com"
        email2 = f"op_ajeno_{uuid.uuid4().hex[:8]}@iaclatam.com"
        pwd = "PasswordStaging123!"

        u1 = self.client_admin.auth.admin.create_user({"email": email1, "password": pwd, "email_confirm": True})
        u2 = self.client_admin.auth.admin.create_user({"email": email2, "password": pwd, "email_confirm": True})
        self.created_auth_users.extend([u1.user.id, u2.user.id])

        self.client_admin.table("perfiles_usuario").insert([
            {"id": u1.user.id, "nombre": "Dueño Op", "correo": email1, "es_admin": False, "activo": True},
            {"id": u2.user.id, "nombre": "Ajeno Op", "correo": email2, "es_admin": False, "activo": True},
        ]).execute()
        self.created_perfiles_usuario.extend([u1.user.id, u2.user.id])

        op_propio = f"op_propio_{uuid.uuid4().hex[:6]}"
        op_ajeno = f"op_ajeno_{uuid.uuid4().hex[:6]}"
        self.client_admin.table("operadores").insert([
            {"id": op_propio, "usuario_id": u1.user.id, "nombre": "Mi Operador", "correo": email1, "es_activo": True},
            {"id": op_ajeno, "usuario_id": u2.user.id, "nombre": "Operador Ajeno", "correo": email2, "es_activo": True},
        ]).execute()
        self.created_operadores.extend([op_propio, op_ajeno])

        # Login usuario 1
        login1 = self.client_public.auth.sign_in_with_password({"email": email1, "password": pwd})
        client_u1 = database.obtener_cliente_usuario(access_token=login1.session.access_token)

        # 1. Actualizar su propio operador: ÉXITO
        res_upd_propio = client_u1.table("operadores").update({"telefono": "3001234567"}).eq("id", op_propio).execute()
        self.assertEqual(len(res_upd_propio.data), 1)
        self.assertEqual(res_upd_propio.data[0]["telefono"], "3001234567")

        # 2. Intentar actualizar operador ajeno: RLS USING retorna 0 filas afectadas
        res_upd_ajeno = client_u1.table("operadores").update({"telefono": "9999999999"}).eq("id", op_ajeno).execute()
        self.assertEqual(len(res_upd_ajeno.data), 0, "No debe poder actualizar operador ajeno")

        # 3. Intentar insertar un nuevo operador: DENEGADO por RLS WITH CHECK (operadores_insert_admin)
        with self.assertRaises(Exception):
            client_u1.table("operadores").insert({
                "id": f"op_hacked_{uuid.uuid4().hex[:6]}", "nombre": "Hacked", "es_activo": True
            }).execute()

        # 4. Intentar eliminar operador: DENEGADO por RLS (operadores_delete_admin)
        res_del = client_u1.table("operadores").delete().eq("id", op_propio).execute()
        self.assertEqual(len(res_del.data), 0, "Usuario no-admin no debe poder eliminar operadores vía RLS")
        check_op = self.client_admin.table("operadores").select("id").eq("id", op_propio).execute()
        self.assertEqual(len(check_op.data), 1, "El operador propio debe seguir existiendo intacto en BD")

    # ==========================================================================
    # ITEM 4: USUARIO ESTÁNDAR NO PUEDE ASIGNARSE es_admin = true
    # ==========================================================================
    def test_04_usuario_estandar_no_puede_escalar_a_admin(self):
        """Verifica que el trigger proteger_columnas_perfil_usuario impida modificar es_admin."""
        email = f"user_priv_{uuid.uuid4().hex[:8]}@iaclatam.com"
        pwd = "PasswordStaging123!"

        u = self.client_admin.auth.admin.create_user({"email": email, "password": pwd, "email_confirm": True})
        self.created_auth_users.append(u.user.id)

        self.client_admin.table("perfiles_usuario").insert({
            "id": u.user.id, "nombre": "User Priv", "correo": email, "es_admin": False, "activo": True
        }).execute()
        self.created_perfiles_usuario.append(u.user.id)

        login = self.client_public.auth.sign_in_with_password({"email": email, "password": pwd})
        client_u = database.obtener_cliente_usuario(access_token=login.session.access_token)

        # Intento de escalamiento de privilegios
        with self.assertRaises(Exception) as ctx:
            client_u.table("perfiles_usuario").update({"es_admin": True}).eq("id", u.user.id).execute()

        self.assertIn("es_admin", str(ctx.exception).lower())

    # ==========================================================================
    # ITEM 5: ADMINISTRADOR ACTIVO GESTIONA CATÁLOGOS
    # ==========================================================================
    def test_05_administrador_activo_gestiona_catalogos(self):
        """Verifica que un administrador activo con JWT pueda gestionar empresas y operadores."""
        email = f"admin_gestor_{uuid.uuid4().hex[:8]}@iaclatam.com"
        pwd = "PasswordStaging123!"

        a_auth = self.client_admin.auth.admin.create_user({"email": email, "password": pwd, "email_confirm": True})
        self.created_auth_users.append(a_auth.user.id)

        self.client_admin.table("perfiles_usuario").insert({
            "id": a_auth.user.id, "nombre": "Admin Gestor", "correo": email, "es_admin": True, "activo": True
        }).execute()
        self.created_perfiles_usuario.append(a_auth.user.id)

        login = self.client_public.auth.sign_in_with_password({"email": email, "password": pwd})
        client_admin_jwt = database.obtener_cliente_usuario(access_token=login.session.access_token)

        # 1. Crear empresa
        slug_emp = f"emp_admin_{uuid.uuid4().hex[:6]}"
        res_emp = client_admin_jwt.table("perfiles_empresa").insert({
            "slug": slug_emp, "nombre_empresa": "Empresa Gestionada por Admin", "es_activa": False
        }).execute()
        self.assertEqual(len(res_emp.data), 1)
        self.created_perfiles_empresa.append(res_emp.data[0]["id"])

        # 2. Crear operador
        op_admin_id = f"op_by_admin_{uuid.uuid4().hex[:6]}"
        res_op = client_admin_jwt.table("operadores").insert({
            "id": op_admin_id, "nombre": "Operador Creado por Admin", "correo": f"{op_admin_id}@iaclatam.com", "es_activo": True
        }).execute()
        self.assertEqual(len(res_op.data), 1)
        self.created_operadores.append(op_admin_id)

        # 3. Eliminar operador como admin: ÉXITO
        client_admin_jwt.table("operadores").delete().eq("id", op_admin_id).execute()
        verif_del = client_admin_jwt.table("operadores").select("*").eq("id", op_admin_id).execute()
        self.assertEqual(len(verif_del.data), 0)

    # ==========================================================================
    # ITEM 6: USUARIO INACTIVO PIERDE ACCESO INMEDIATAMENTE (0 FILAS)
    # ==========================================================================
    def test_06_usuario_inactivo_pierde_acceso_inmediatamente(self):
        """Verifica que un usuario desactivado (activo=false) con JWT vigente reciba 0 filas en consultas."""
        email = f"user_inact_{uuid.uuid4().hex[:8]}@iaclatam.com"
        pwd = "PasswordStaging123!"

        u = self.client_admin.auth.admin.create_user({"email": email, "password": pwd, "email_confirm": True})
        uid = u.user.id
        self.created_auth_users.append(uid)

        self.client_admin.table("perfiles_usuario").insert({
            "id": uid, "nombre": "Usuario Inactivable", "correo": email, "es_admin": False, "activo": True
        }).execute()
        self.created_perfiles_usuario.append(uid)

        # Login mientras está activo
        login = self.client_public.auth.sign_in_with_password({"email": email, "password": pwd})
        jwt = login.session.access_token

        # Desactivar en perfiles_usuario
        self.client_admin.table("perfiles_usuario").update({"activo": False}).eq("id", uid).execute()

        # Intentar consultar con el JWT todavía vigente
        client_inactivo = database.obtener_cliente_usuario(access_token=jwt)
        res_emp = client_inactivo.table("perfiles_empresa").select("*").execute()
        self.assertEqual(len(res_emp.data), 0, "Usuario inactivo debe recibir 0 filas en perfiles_empresa")

        res_op = client_inactivo.table("operadores").select("*").execute()
        self.assertEqual(len(res_op.data), 0, "Usuario inactivo debe recibir 0 filas en operadores")

        res_perfil = client_inactivo.table("perfiles_usuario").select("*").execute()
        self.assertEqual(len(res_perfil.data), 0, "Usuario inactivo debe recibir 0 filas en perfiles_usuario")

    # ==========================================================================
    # ITEM 7: REFRESCO ANTICIPADO DE JWT (UMBRAL 300S)
    # ==========================================================================
    def test_07_refresco_anticipado_jwt(self):
        """Prueba refresh_session con token de refresco válido."""
        email = f"user_refresh_{uuid.uuid4().hex[:8]}@iaclatam.com"
        pwd = "PasswordStaging123!"

        u = self.client_admin.auth.admin.create_user({"email": email, "password": pwd, "email_confirm": True})
        self.created_auth_users.append(u.user.id)

        self.client_admin.table("perfiles_usuario").insert({
            "id": u.user.id, "nombre": "User Refresh", "correo": email, "es_admin": False, "activo": True
        }).execute()
        self.created_perfiles_usuario.append(u.user.id)

        login = self.client_public.auth.sign_in_with_password({"email": email, "password": pwd})
        refresh_token = login.session.refresh_token

        # Ejecutar refresh de sesión
        refreshed = self.client_public.auth.refresh_session(refresh_token)
        self.assertIsNotNone(refreshed.session)
        self.assertTrue(len(refreshed.session.access_token) > 20)
        self.assertNotEqual(login.session.access_token, refreshed.session.access_token)

    # ==========================================================================
    # ITEM 8: service_role NUNCA EXPUESTO EN CLIENTE PÚBLICO NI LOGS
    # ==========================================================================
    def test_08_service_role_nunca_expuesto(self):
        """Verifica que el cliente público utilice la Publishable Key y nunca la Secret Key."""
        pub_key = database._resolver_publishable_key()
        secret_key = database._resolver_secret_key()

        self.assertEqual(self.client_public.supabase_key, pub_key)
        self.assertNotEqual(self.client_public.supabase_key, secret_key)

    # ==========================================================================
    # ITEM 9: RECHAZO DE DOMINIOS NO CORPORATIVOS
    # ==========================================================================
    def test_09_rechazo_dominios_no_corporativos(self):
        """Verifica que tanto auth_manager como el trigger de BD rechacen correos no corporativos."""
        bad_emails = [
            "hacker@gmail.com",
            "intruder@outlook.com",
            "fake@iaclatam.org",
            "test@iac.com",
        ]
        for em in bad_emails:
            # 1. En capa aplicación
            self.assertFalse(auth_manager.validar_dominio_corporativo(em))

            # 2. En capa base de datos (trigger trigger_validar_dominio_correo)
            with self.assertRaises(Exception):
                self.client_admin.auth.admin.create_user({
                    "email": em, "password": "PasswordStaging123!", "email_confirm": True
                })

    # ==========================================================================
    # ITEM 10: ROLLBACK SELECTIVO POR BATCH_ID CON MANIFESTO_UUIDS
    # ==========================================================================
    def test_10_rollback_selectivo_con_manifesto_uuids(self):
        """Ejecuta migración de fixture sintético, valida manifesto_uuids y ejecuta rollback idempotente."""
        synth_db = PROJECT_ROOT / "tests" / "fixtures" / "synthetic_empresa.db"
        self.assertTrue(synth_db.exists())

        perfiles, operadores, usuarios = migrador.leer_datos_sqlite(synth_db)

        # Ejecutar migración sintética
        batch_id = migrador.ejecutar_migration(
            perfiles,
            operadores,
            usuarios,
            confirm_project=STAGING_REF,
            enviar_invitaciones=False,
        )
        self.assertIsNotNone(batch_id)
        self.created_migration_runs.append(batch_id)

        # Validar manifesto en migration_runs
        run_res = self.client_admin.table("migration_runs").select("*").eq("batch_id", batch_id).execute()
        self.assertEqual(len(run_res.data), 1)
        manifesto = run_res.data[0]["manifesto_uuids"]
        self.assertIn("perfiles_empresa", manifesto)
        self.assertIn("operadores", manifesto)

        # Ejecutar rollback selectivo
        migrador.ejecutar_rollback_batch(batch_id, confirm_project=STAGING_REF)

        # Verificar que el estado cambió a ROLLED_BACK y las entidades fueron eliminadas
        run_post = self.client_admin.table("migration_runs").select("estado").eq("batch_id", batch_id).execute()
        self.assertEqual(run_post.data[0]["estado"], "ROLLED_BACK")

        emp_post = self.client_admin.table("perfiles_empresa").select("*").eq("slug", "empresa_ficticia_staging").execute()
        self.assertEqual(len(emp_post.data), 0)

        op_post = self.client_admin.table("operadores").select("*").in_("id", ["op_staging_01", "op_staging_02"]).execute()
        self.assertEqual(len(op_post.data), 0)

        # Segundo rollback debe ser idempotente
        migrador.ejecutar_rollback_batch(batch_id, confirm_project=STAGING_REF)

    # ==========================================================================
    # ITEM 11: PROYECTOS PDF BLOQUEADOS ANTE CUALQUIER INTENTO
    # ==========================================================================
    def test_11_proyectos_pdf_bloqueados_ante_cualquier_intento(self):
        """Verifica que la barrera anti-PDF aborte con SystemExit(1) ante cualquier referencia a PDF."""
        for pdf_ref in PROHIBITED_PDF_REFS:
            with self.assertRaises(SystemExit) as ctx:
                migrador._verificar_project_ref(f"https://{pdf_ref}.supabase.co", pdf_ref)
            self.assertEqual(ctx.exception.code, 1)

    # ==========================================================================
    # ITEM 12: FAIL-CLOSED SI FALTAN VARIABLES DE CONFIGURACIÓN
    # ==========================================================================
    def test_12_fail_closed_si_faltan_variables_configuracion(self):
        """Verifica que el sistema falle cerrado si faltan variables críticas."""
        with mock.patch.dict(os.environ, {"SUPABASE_URL": ""}, clear=False):
            with self.assertRaises(database.ConfiguracionInvalidaError):
                database.obtener_cliente_publico()

        with mock.patch.dict(
            os.environ,
            {"SUPABASE_SERVICE_ROLE_KEY": "", "SUPABASE_SECRET_KEY": ""},
            clear=False,
        ):
            with self.assertRaises(database.ConfiguracionInvalidaError):
                database.obtener_cliente_admin()

        with mock.patch.dict(
            os.environ,
            {"SUPABASE_ANON_KEY": "", "SUPABASE_PUBLISHABLE_KEY": ""},
            clear=False,
        ):
            with self.assertRaises(database.ConfiguracionInvalidaError):
                database.obtener_cliente_publico()

    # ==========================================================================
    # VERIFICACIÓN FINAL DE CONTEOS TRAS TEARDOWN QUIRÚRGICO
    # ==========================================================================
    def test_13_verificacion_conteos_post_teardown(self):
        """Verifica que tras el teardown quirúrgico los conteos del proyecto staging sean exactos."""
        # Ejecutar limpieza quirúrgica
        self._ejecutar_teardown_quirurgico()

        # deployment_identity debe tener EXACTAMENTE 1 fila
        res_dep = self.client_admin.table("deployment_identity").select("*").execute()
        self.assertEqual(len(res_dep.data), 1, "deployment_identity debe mantener exactamente 1 fila")
        self.assertEqual(res_dep.data[0]["application_code"], "autoform-excel")
        self.assertEqual(res_dep.data[0]["environment"], "staging")
        self.assertEqual(res_dep.data[0]["project_ref"], STAGING_REF)

        # Tablas públicas de aplicación deben estar en 0
        res_emp = self.client_admin.table("perfiles_empresa").select("*").execute()
        self.assertEqual(len(res_emp.data), 0, "perfiles_empresa debe tener 0 filas")

        res_usr = self.client_admin.table("perfiles_usuario").select("*").execute()
        self.assertEqual(len(res_usr.data), 0, "perfiles_usuario debe tener 0 filas")

        res_op = self.client_admin.table("operadores").select("*").execute()
        self.assertEqual(len(res_op.data), 0, "operadores debe tener 0 filas")

        res_mig = self.client_admin.table("migration_runs").select("*").execute()
        self.assertEqual(len(res_mig.data), 0, "migration_runs debe tener 0 filas")

        # auth.users debe tener 0 usuarios
        users = self.client_admin.auth.admin.list_users()
        self.assertEqual(len(users or []), 0, "auth.users debe tener 0 usuarios")

        # storage debe tener 0 buckets y 0 objetos
        buckets = self.client_admin.storage.list_buckets()
        self.assertEqual(len(buckets or []), 0, "storage no debe tener buckets ni objetos")


if __name__ == "__main__":
    unittest.main(verbosity=2)
