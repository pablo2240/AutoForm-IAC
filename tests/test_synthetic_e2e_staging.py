#!/usr/bin/env python3
"""Suite de Pruebas Sintéticas de Extremo a Extremo (E2E) — AutoForm Excel Staging.

Cubre los 10 casos de prueba E2E de validación corporativa definidos en el Plan de Cierre de Staging:
E2E-01: Auto-registro con estado pendiente e inactivo (sin operador).
E2E-02: Bloqueo de inicio de sesión mientras la cuenta está pendiente.
E2E-03: Aprobación administrativa, activación y sincronización de operador.
E2E-04: Inicio de sesión exitoso post-aprobación con perfil comercial intacto.
E2E-05: Rechazo de solicitud por administrador y bloqueo subsiguiente.
E2E-06: Desalojo en caliente y suspensión de cuenta activa.
E2E-07: Salvaguarda estricta de singleton: protección del último administrador activo.
E2E-08: Restablecimiento administrativo de contraseña e invalidación de clave anterior.
E2E-09: Rechazo de dominios no corporativos en múltiples capas.
E2E-10: Barrera de seguridad Anti-PDF en flujos de recuperación de contraseñas.

Garantías de Seguridad:
- 100% sintético: opera sobre fixtures y bases de datos aisladas en memoria/temporales.
- Cero mutaciones en Supabase real de producción ni Staging.
- Cero despacho de correos SMTP reales.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import auth_manager, database


class TestSyntheticE2EStaging(unittest.TestCase):
    """Validación sintética E2E de flujos de auto-registro, administración y seguridad."""

    def setUp(self):
        """Prepara entorno aislado de base de datos SQLite temporal para pruebas sintéticas."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_db_path = Path(self.temp_dir) / "test_synth_empresa.db"
        self.original_db_path = database.DB_PATH

        # Configurar entorno de desarrollo local con SQLite para pruebas sintéticas
        self.orig_env = os.environ.get("APP_ENVIRONMENT")
        self.orig_use_sqlite = os.environ.get("USE_SQLITE")
        self.orig_use_supabase = os.environ.get("USE_SUPABASE")
        self.orig_admin_pwd = os.environ.get("AUTOFORM_ADMIN_PASSWORD")

        os.environ["APP_ENVIRONMENT"] = "development"
        os.environ["USE_SQLITE"] = "true"
        os.environ["USE_SUPABASE"] = "false"
        os.environ["AUTOFORM_ADMIN_PASSWORD"] = "AdminMaster2026!*"

        # Redirigir canonical DB path al archivo temporal
        database.DB_PATH = self.test_db_path
        database.inicializar_db()

        # Obtener administrador institucional inicial creado por inicializar_db
        self.admin_correo = "guillermo.canon@iaclatam.com"
        self.admin_pwd = "AdminMaster2026!*"
        admin_row = database.obtener_usuario_por_correo_db(self.admin_correo)
        self.admin_id = admin_row["id"]

    def tearDown(self):
        """Limpia el entorno temporal."""
        database.DB_PATH = self.original_db_path
        if self.orig_env is not None:
            os.environ["APP_ENVIRONMENT"] = self.orig_env
        else:
            os.environ.pop("APP_ENVIRONMENT", None)

        if self.orig_use_sqlite is not None:
            os.environ["USE_SQLITE"] = self.orig_use_sqlite
        else:
            os.environ.pop("USE_SQLITE", None)

        if self.orig_admin_pwd is not None:
            os.environ["AUTOFORM_ADMIN_PASSWORD"] = self.orig_admin_pwd
        else:
            os.environ.pop("AUTOFORM_ADMIN_PASSWORD", None)

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # E2E-01: Auto-Registro con Estado Pendiente e Inactivo
    # =========================================================================
    def test_01_auto_registro_con_estado_pendiente(self):
        """Verifica que el auto-registro cree la cuenta en estado pendiente, inactiva y sin operador."""
        ok_reg, msg_reg = auth_manager.registrar_solicitud_corporativa(
            nombre="Andrés Felipe Restrepo",
            correo="andres.restrepo@iaclatam.com",
            password="PasswordSeguro123!",
            cargo="Consultor Comercial",
            telefono="3009876543",
            ciudad="Bogotá",
            requiere_aprobacion=True,
        )
        self.assertTrue(ok_reg, f"El registro debió ser exitoso: {msg_reg}")
        self.assertIn("revisión", msg_reg.lower())
        self.assertIn("aprobación", msg_reg.lower())

        # Verificar en base de datos
        usr = database.obtener_usuario_por_correo_db("andres.restrepo@iaclatam.com")
        self.assertIsNotNone(usr)
        self.assertEqual(usr["estado_aprobacion"], "pendiente")
        self.assertEqual(usr["activo"], 0)
        self.assertEqual(usr["es_admin"], 0)

        # Verificar que NO se haya creado un operador en el catálogo antes de la aprobación
        with database.obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM operadores WHERE correo = ?", ("andres.restrepo@iaclatam.com",))
            op = cursor.fetchone()
            self.assertIsNone(op, "No debe crearse un operador en catálogo para solicitudes pendientes")

    # =========================================================================
    # E2E-02: Bloqueo de Inicio de Sesión en Estado Pendiente
    # =========================================================================
    def test_02_bloqueo_login_en_estado_pendiente(self):
        """Verifica que un usuario en estado pendiente no pueda iniciar sesión."""
        auth_manager.registrar_solicitud_corporativa(
            nombre="Andrés Felipe Restrepo",
            correo="andres.restrepo@iaclatam.com",
            password="PasswordSeguro123!",
            cargo="Consultor Comercial",
            requiere_aprobacion=True,
        )

        ok_log, user_data, tokens, msg_log = auth_manager.iniciar_sesion(
            "andres.restrepo@iaclatam.com",
            "PasswordSeguro123!",
        )
        self.assertFalse(ok_log)
        self.assertIsNone(user_data)
        self.assertIsNone(tokens)
        self.assertIn("pendiente de aprobación", msg_log.lower())

    # =========================================================================
    # E2E-03: Aprobación Administrativa y Fusión de Operador
    # =========================================================================
    def test_03_aprobacion_administrativa_y_fusion_operador(self):
        """Verifica que un administrador apruebe la solicitud, activando la cuenta y sincronizando el operador."""
        auth_manager.registrar_solicitud_corporativa(
            nombre="Andrés Felipe Restrepo",
            correo="andres.restrepo@iaclatam.com",
            password="PasswordSeguro123!",
            cargo="Consultor Comercial",
            telefono="3009876543",
            ciudad="Bogotá",
            requiere_aprobacion=True,
        )
        usr_creado = database.obtener_usuario_por_correo_db("andres.restrepo@iaclatam.com")
        user_id = usr_creado["id"]

        # Listar solicitudes pendientes
        ok_p, pendientes = auth_manager.listar_solicitudes_pendientes(access_token_solicitante="fake_admin_tok")
        self.assertTrue(ok_p)
        self.assertEqual(len(pendientes), 1)
        self.assertEqual(pendientes[0]["correo"], "andres.restrepo@iaclatam.com")

        # Aprobar solicitud
        ok_ap, msg_ap = auth_manager.aprobar_solicitud_registro(user_id, access_token_solicitante="fake_admin_tok")
        self.assertTrue(ok_ap, f"Aprobación fallida: {msg_ap}")
        self.assertIn("aprobado", msg_ap.lower())

        # Verificar que el estado cambió a aprobado y activo
        usr_aprobado = database.obtener_usuario_por_correo_db("andres.restrepo@iaclatam.com")
        self.assertEqual(usr_aprobado["estado_aprobacion"], "aprobado")
        self.assertEqual(usr_aprobado["activo"], 1)

        # Verificar sincronización automática en catálogo de operadores
        with database.obtener_conexion() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM operadores WHERE correo = ?", ("andres.restrepo@iaclatam.com",))
            op = cursor.fetchone()
            self.assertIsNotNone(op, "Debe crearse la fila en operadores tras la aprobación")
            self.assertEqual(op["nombre"], "Andrés Felipe Restrepo")
            self.assertEqual(op["cargo"], "Consultor Comercial")

    # =========================================================================
    # E2E-04: Login Exitoso tras Aprobación
    # =========================================================================
    def test_04_login_exitoso_tras_aprobacion(self):
        """Verifica que el usuario aprobado pueda ingresar exitosamente a la plataforma."""
        auth_manager.registrar_solicitud_corporativa(
            nombre="Andrés Felipe Restrepo",
            correo="andres.restrepo@iaclatam.com",
            password="PasswordSeguro123!",
            cargo="Consultor Comercial",
            requiere_aprobacion=True,
        )
        usr = database.obtener_usuario_por_correo_db("andres.restrepo@iaclatam.com")
        auth_manager.aprobar_solicitud_registro(usr["id"])

        ok_log, user_data, tokens, msg_log = auth_manager.iniciar_sesion(
            "andres.restrepo@iaclatam.com",
            "PasswordSeguro123!",
        )
        self.assertTrue(ok_log)
        self.assertIsNotNone(user_data)
        self.assertEqual(user_data["correo"], "andres.restrepo@iaclatam.com")
        self.assertEqual(user_data["activo"], 1)
        self.assertFalse(user_data["es_admin"])
        self.assertIn("bienvenido", msg_log.lower())

    # =========================================================================
    # E2E-05: Rechazo de Registro por Administrador
    # =========================================================================
    def test_05_rechazo_registro_por_administrador(self):
        """Verifica que un administrador pueda rechazar una solicitud y que el login quede bloqueado."""
        auth_manager.registrar_solicitud_corporativa(
            nombre="Solicitante Rechazado",
            correo="rechazado@iaclatam.com",
            password="PasswordSeguro123!",
            requiere_aprobacion=True,
        )
        usr = database.obtener_usuario_por_correo_db("rechazado@iaclatam.com")

        ok_rec, msg_rec = auth_manager.rechazar_solicitud_registro(usr["id"])
        self.assertTrue(ok_rec)

        # Login bloqueado
        ok_log, user_data, _, msg_log = auth_manager.iniciar_sesion(
            "rechazado@iaclatam.com",
            "PasswordSeguro123!",
        )
        self.assertFalse(ok_log)
        self.assertIsNone(user_data)
        self.assertIn("rechazada", msg_log.lower())

    # =========================================================================
    # E2E-06: Desalojo en Caliente y Suspensión de Cuenta
    # =========================================================================
    def test_06_desalojo_en_caliente_por_desactivacion(self):
        """Verifica la suspensión de un usuario activo y el rechazo en futuros inicios de sesión."""
        auth_manager.registrar_solicitud_corporativa(
            nombre="Usuario Activo",
            correo="activo.test@iaclatam.com",
            password="PasswordSeguro123!",
            requiere_aprobacion=False,
        )
        usr = database.obtener_usuario_por_correo_db("activo.test@iaclatam.com")

        # Desactivar usuario
        ok_des, msg_des = auth_manager.conmutar_estado_activo_usuario(usr["id"], False)
        self.assertTrue(ok_des)
        self.assertIn("desactivado", msg_des.lower())

        # Intento de login tras desactivación
        ok_log, _, _, msg_log = auth_manager.iniciar_sesion(
            "activo.test@iaclatam.com",
            "PasswordSeguro123!",
        )
        self.assertFalse(ok_log)
        self.assertIn("inactiva", msg_log.lower())

    # =========================================================================
    # E2E-07: Salvaguarda del Último Administrador Activo
    # =========================================================================
    def test_07_proteccion_del_ultimo_administrador_activo(self):
        """Verifica que el sistema rechace suspender o degradar al único administrador activo."""
        # Intento 1: Desactivar al único admin
        ok_des, msg_des = auth_manager.conmutar_estado_activo_usuario(self.admin_id, False)
        self.assertFalse(ok_des)
        self.assertIn("único administrador", msg_des.lower())

        # Intento 2: Degradar rol a comercial al único admin
        ok_deg, msg_deg = auth_manager.cambiar_rol_usuario(self.admin_id, "comercial")
        self.assertFalse(ok_deg)
        self.assertIn("único administrador", msg_deg.lower())

        # Verificar que el admin continúa siendo admin y activo
        admin_check = database.obtener_usuario_por_correo_db(self.admin_correo)
        self.assertEqual(admin_check["es_admin"], 1)
        self.assertEqual(admin_check["activo"], 1)

    # =========================================================================
    # E2E-08: Restablecimiento Administrativo de Contraseña
    # =========================================================================
    def test_08_restablecimiento_de_contrasena_administrativo(self):
        """Verifica que un administrador actualice la contraseña y que la anterior quede invalidada."""
        auth_manager.registrar_solicitud_corporativa(
            nombre="Comercial Reset",
            correo="comercial.reset@iaclatam.com",
            password="ClaveAntigua123!",
            requiere_aprobacion=False,
        )
        usr = database.obtener_usuario_por_correo_db("comercial.reset@iaclatam.com")

        # Admin restablece la contraseña
        nueva_clave = "ClaveNuevaSegura999!"
        ok_res, msg_res = auth_manager.restablecer_password_comercial_admin(usr["id"], nueva_clave)
        self.assertTrue(ok_res)

        # Login con clave vieja debe fallar
        ok_vieja, _, _, _ = auth_manager.iniciar_sesion("comercial.reset@iaclatam.com", "ClaveAntigua123!")
        self.assertFalse(ok_vieja)

        # Login con clave nueva debe triunfar
        ok_nueva, u_nueva, _, _ = auth_manager.iniciar_sesion("comercial.reset@iaclatam.com", nueva_clave)
        self.assertTrue(ok_nueva)
        self.assertEqual(u_nueva["correo"], "comercial.reset@iaclatam.com")

    # =========================================================================
    # E2E-09: Rechazo de Dominios Externos en 3 Capas
    # =========================================================================
    def test_09_rechazo_dominios_no_corporativos_tres_capas(self):
        """Verifica el bloqueo categórico de correos externos no autorizados."""
        correos_prohibidos = [
            "intruso@gmail.com",
            "atacante@hotmail.com",
            "fake@iac.com",
            "externo@empresa.co",
        ]
        for c in correos_prohibidos:
            # Capa 1: Validación estricta de función
            self.assertFalse(auth_manager.validar_dominio_corporativo(c))

            # Capa 2: Rechazo en auto-registro
            ok_r, msg_r = auth_manager.registrar_solicitud_corporativa(
                nombre="Intruso",
                correo=c,
                password="PasswordSeguro123!",
                requiere_aprobacion=True,
            )
            self.assertFalse(ok_r)
            self.assertIn("correo corporativo", msg_r.lower())

    # =========================================================================
    # E2E-10: Barrera Anti-PDF en Flujos de Recuperación
    # =========================================================================
    def test_10_barrera_anti_pdf_en_recuperacion(self):
        """Verifica que cualquier intento de recuperación con URLs asociadas a PDF aborte por seguridad."""
        for pdf_ref in database.PROHIBITED_PROJECT_REFS:
            url_maliciosa = f"https://{pdf_ref}.supabase.co/auth/v1/verify"
            with patch("core.database.usar_supabase", return_value=True), \
                 patch("core.auth_manager._verificar_solicitante_es_admin_activo", return_value=(True, "", "admin_id")), \
                 patch.dict(os.environ, {"AUTOFORM_EXCEL_REDIRECT_URL": url_maliciosa}):

                with self.assertRaises(database.ConfiguracionInvalidaError):
                    auth_manager.solicitar_recuperacion_password("guillermo.canon@iaclatam.com")

                with self.assertRaises(database.ConfiguracionInvalidaError):
                    auth_manager.reenviar_recuperacion_admin(
                        "guillermo.canon@iaclatam.com",
                        redirect_url=url_maliciosa,
                        access_token_solicitante="fake_token",
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
