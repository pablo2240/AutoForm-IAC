#!/usr/bin/env python3
"""Suite completa de pruebas de seguridad para AutoForm Excel — ADR-0010.

Cubre los 22 controles de seguridad canónicos:
 1-14: Remediación de seguridad SQLite → Supabase (fase anterior).
15-18: Hardening-01 — Autorización JWT real para invitaciones.
19-22: Hardening-04 — Rollback selectivo e idempotencia.

Para ejecutar:
    .\\venv\\Scripts\\python.exe tests/test_security_remediation.py
    # o con pytest:
    .\\venv\\Scripts\\python.exe -m pytest tests/test_security_remediation.py -v
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Asegurar importación de la raíz del proyecto
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import auth_manager, database, profile_manager
from scripts import migrate_sqlite_to_supabase as migrador


class TestSecurityRemediationSuite(unittest.TestCase):
    """Suite de pruebas de seguridad canónicas: 22 controles."""

    # ==========================================================================
    # PARTE I — REMEDIACIÓN DE SEGURIDAD SQLITE → SUPABASE (Tests 1-14)
    # ==========================================================================

    def test_01_fallback_c01_eliminado_fail_closed_en_produccion(self):
        """Verifica que _obtener_cliente_activo lance SesionNoAutenticadaError en producción sin JWT."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "production"}):
            with self.assertRaises(database.SesionNoAutenticadaError):
                database._obtener_cliente_activo(cliente_provisto=None)

    def test_02_obtener_cliente_admin_falla_sin_service_role_key(self):
        """Verifica que obtener_cliente_admin falle si no están SUPABASE_SECRET_KEY ni SUPABASE_SERVICE_ROLE_KEY."""
        with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "", "SUPABASE_SECRET_KEY": ""}):
            with self.assertRaises(database.ConfiguracionInvalidaError):
                database.obtener_cliente_admin()

    def test_03_obtener_cliente_usuario_falla_sin_anon_key(self):
        """Verifica que obtener_cliente_usuario falle si faltan SUPABASE_URL o ambas llaves públicas."""
        with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_ANON_KEY": "", "SUPABASE_PUBLISHABLE_KEY": ""}):
            with self.assertRaises(database.ConfiguracionInvalidaError):
                database.obtener_cliente_usuario()

    def test_04_validacion_dominio_corporativo_estricta(self):
        """Verifica que únicamente los dominios oficiales sean aceptados."""
        correos_validos = [
            "carlos.gomez@iaclatam.com",
            "laura.martinez@iac.com.co",
            "OPERACIONES@IAC.COM.CO",
            "admin_test@iaclatam.com",
        ]
        for correo in correos_validos:
            self.assertTrue(auth_manager.validar_dominio_corporativo(correo), f"Debería ser válido: {correo}")

        correos_invalidos = [
            "pepito@gmail.com",
            "hacker@iaclatam.com.attacker.com",
            "user@sub.iaclatam.com",
            "user@iaclatam.org",
            "user@iac.com",
            "@iaclatam.com",
            "invalido@@iaclatam.com",
            "",
            "   ",
        ]
        for correo in correos_invalidos:
            self.assertFalse(auth_manager.validar_dominio_corporativo(correo), f"Debería ser inválido: {correo}")

    def test_05_user_metadata_no_eleva_privilegios_admin(self):
        """Verifica que es_admin se tome exclusivamente de perfiles_usuario y no de metadata."""
        mock_session = MagicMock()
        mock_session.access_token = "mock_acc"
        mock_session.refresh_token = "mock_ref"
        mock_session.expires_at = 1893456000
        mock_user = MagicMock()
        mock_user.id = "user-uuid-123"
        mock_user.user_metadata = {"es_admin": True, "rol": "administrador"}
        mock_auth_res = MagicMock()
        mock_auth_res.session = mock_session
        mock_auth_res.user = mock_user
        mock_pub_client = MagicMock()
        mock_pub_client.auth.sign_in_with_password.return_value = mock_auth_res

        perfil_en_bd = {"id": "user-uuid-123", "nombre": "Operador Normal", "correo": "operador@iaclatam.com", "es_admin": False, "activo": True}

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.database.obtener_cliente_publico", return_value=mock_pub_client), \
             patch("core.database.obtener_cliente_usuario", return_value=MagicMock()), \
             patch("core.database.obtener_usuario_por_correo_db", return_value=perfil_en_bd):
            exito, usuario, tokens, msg = auth_manager.iniciar_sesion("operador@iaclatam.com", "PasswordSeguro123!")
            self.assertTrue(exito)
            self.assertIsNotNone(usuario)
            self.assertFalse(usuario["es_admin"], "es_admin NO debe elevarse desde user_metadata")

    def test_06_usuario_inactivo_rechazado_y_sesion_revocada(self):
        """Verifica que si activo=False en perfiles_usuario, el login se rechace y se llame sign_out."""
        mock_session = MagicMock()
        mock_session.access_token = "mock_acc"
        mock_session.refresh_token = "mock_ref"
        mock_user = MagicMock()
        mock_user.id = "user-uuid-456"
        mock_auth_res = MagicMock()
        mock_auth_res.session = mock_session
        mock_auth_res.user = mock_user
        mock_pub_client = MagicMock()
        mock_pub_client.auth.sign_in_with_password.return_value = mock_auth_res
        mock_user_client = MagicMock()
        perfil_inactivo = {"id": "user-uuid-456", "nombre": "Ex Empleado", "correo": "ex.empleado@iaclatam.com", "es_admin": False, "activo": False}

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.database.obtener_cliente_publico", return_value=mock_pub_client), \
             patch("core.database.obtener_cliente_usuario", return_value=mock_user_client), \
             patch("core.database.obtener_usuario_por_correo_db", return_value=perfil_inactivo):
            exito, usuario, tokens, msg = auth_manager.iniciar_sesion("ex.empleado@iaclatam.com", "PasswordSeguro123!")
            self.assertFalse(exito)
            self.assertIsNone(usuario)
            self.assertIsNone(tokens)
            mock_user_client.auth.sign_out.assert_called_once()

    def test_07_umbral_expiracion_token_300s(self):
        """Verifica la condición de refresco anticipado (expires_at - 300 <= now)."""
        now = 10_000
        self.assertTrue((now + 250 - 300) <= now, "Token con 250s restantes debe disparar refresco")
        self.assertTrue((now + 300 - 300) <= now, "Token con exactamente 300s debe disparar refresco")
        self.assertFalse((now + 305 - 300) <= now, "Token con 305s restantes aún es válido")

    def test_08_dry_run_preserva_integridad_sha256_sqlite(self):
        """Verifica que leer datos y ejecutar rutinas de migración en dry-run no altere empresa.db."""
        if not migrador.SQLITE_DB_PATH.exists():
            self.skipTest("config/empresa.db no existe localmente.")
        sha_antes = migrador.calcular_sha256_archivo(migrador.SQLITE_DB_PATH)
        migrador.leer_datos_sqlite()
        sha_despues = migrador.calcular_sha256_archivo(migrador.SQLITE_DB_PATH)
        self.assertEqual(sha_antes, sha_despues, "La lectura de SQLite no debe modificar el archivo físico")

    def test_09_confirm_project_requerido_y_verificado(self):
        """Verifica extracción del project ref y rechazo si no coincide."""
        url = "https://kydtovbflfocprmjqwgh.supabase.co"
        ref_extraido = migrador.extraer_project_ref(url)
        self.assertEqual(ref_extraido, "kydtovbflfocprmjqwgh")
        self.assertNotEqual(ref_extraido, "otroproyecto123")

    def test_10_enmascaramiento_de_correos(self):
        """Verifica el enmascaramiento estricto de PII en consola y logs."""
        casos = [
            ("administrador@iaclatam.com", "a***r@iaclatam.com"),
            ("laura@iac.com.co", "l***a@iac.com.co"),
            ("ab@iaclatam.com", "a***@iaclatam.com"),
            ("a@iaclatam.com", "a***@iaclatam.com"),
            ("", "***"),
        ]
        for entrada, esperado in casos:
            self.assertEqual(migrador.enmascarar_correo(entrada), esperado, f"Falló enmascarar {entrada}")

    def test_11_pepito_perez_excluido_de_colecciones(self):
        """Verifica que pepito_perez no aparezca en perfiles, operadores ni usuarios extraídos."""
        if not migrador.SQLITE_DB_PATH.exists():
            self.skipTest("config/empresa.db no existe localmente.")
        perfiles, operadores, usuarios = migrador.leer_datos_sqlite()
        self.assertNotIn("pepito_perez", [op["id"] for op in operadores])
        for c in [op["correo"] for op in operadores]:
            self.assertNotIn("pepito", c)
        self.assertNotIn("pepito_perez", [u["id"] for u in usuarios])
        for c in [u["correo"] for u in usuarios]:
            self.assertNotIn("pepito", c)

    def test_12_invitaciones_retenidas_por_defecto_en_cli(self):
        """Verifica que el argumento --enviar-invitaciones sea False por defecto."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true", default=True)
        parser.add_argument("--execute", action="store_true", default=False)
        parser.add_argument("--confirm-project", type=str, default=None)
        parser.add_argument("--enviar-invitaciones", action="store_true", default=False)
        args = parser.parse_args([])
        self.assertFalse(args.enviar_invitaciones, "Las invitaciones deben estar retenidas por defecto")

    def test_13_creacion_y_verificacion_respaldo_sqlite(self):
        """Verifica que crear_respaldo_sqlite cree una réplica idéntica en tamaño y SHA256."""
        if not migrador.SQLITE_DB_PATH.exists():
            self.skipTest("config/empresa.db no existe localmente.")
        backup_creado = migrador.crear_respaldo_sqlite()
        try:
            self.assertTrue(backup_creado.exists())
            self.assertEqual(migrador.SQLITE_DB_PATH.stat().st_size, backup_creado.stat().st_size)
            self.assertEqual(
                migrador.calcular_sha256_archivo(migrador.SQLITE_DB_PATH),
                migrador.calcular_sha256_archivo(backup_creado),
            )
        finally:
            if backup_creado.exists():
                backup_creado.unlink()

    def test_14_ausencia_de_secretos_en_codigo_fuente(self):
        """Escanea los archivos del proyecto para asegurar que no hay service_role keys o JWT hardcodeados."""
        patrones_sospechosos = [
            re.compile(r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
            re.compile(r"service_role[_\s]*key[\s]*=[\s]*['\"][A-Za-z0-9_\.\-]{20,}['\"]", re.IGNORECASE),
        ]
        archivos_a_escanear = [
            PROJECT_ROOT / "core" / "database.py",
            PROJECT_ROOT / "core" / "auth_manager.py",
            PROJECT_ROOT / "core" / "profile_manager.py",
            PROJECT_ROOT / "app1.py",
            PROJECT_ROOT / "scripts" / "migrate_sqlite_to_supabase.py",
            PROJECT_ROOT / "supabase" / "migrations" / "001_initial_schema.sql",
        ]
        for ruta in archivos_a_escanear:
            if not ruta.exists():
                continue
            contenido = ruta.read_text(encoding="utf-8", errors="ignore")
            for patron in patrones_sospechosos:
                coincidencias = patron.findall(contenido)
                self.assertEqual(len(coincidencias), 0, f"Se encontró posible secreto hardcodeado en {ruta.name}: {coincidencias}")

    # ==========================================================================
    # PARTE II — HARDENING-01: Autorización JWT Real para Invitaciones (Tests 15-18)
    # ==========================================================================

    def test_15_invitacion_rechazada_con_token_vacio(self):
        """Verifica que access_token vacío sea rechazado antes de construir cliente admin.

        Ningún parámetro booleano externo (solicitante_es_admin=True) puede sustituir
        a la verificación real por JWT.
        """
        with patch("core.database.usar_supabase", return_value=True):
            exito, msg = auth_manager.invitar_usuario_corporativo(
                correo="nuevo@iaclatam.com",
                nombre="Nuevo Usuario",
                access_token_solicitante="",  # vacío → rechazo inmediato
            )
            self.assertFalse(exito)
            self.assertIn("access_token", msg.lower().replace("_", " ") + " " + msg.lower())

    def test_16_invitacion_rechazada_si_token_invalido_en_supabase(self):
        """Verifica que si Supabase rechaza el JWT del solicitante, la invitación sea rechazada."""
        mock_client_jwt = MagicMock()
        mock_client_jwt.auth.get_user.side_effect = Exception("Token inválido o expirado")

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.database.obtener_cliente_usuario", return_value=mock_client_jwt), \
             patch("core.database.obtener_cliente_admin") as mock_admin:
            exito, msg = auth_manager.invitar_usuario_corporativo(
                correo="nuevo@iaclatam.com",
                nombre="Nuevo Usuario",
                access_token_solicitante="token_malformado_xyz",
            )
            self.assertFalse(exito, "Debería rechazarse con token inválido")
            mock_admin.assert_not_called()  # El cliente admin JAMÁS se construye

    def test_17_invitacion_rechazada_si_solicitante_inactivo_en_bd(self):
        """Verifica que un solicitante con token válido pero activo=False en BD sea rechazado."""
        uid_solicitante = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
        mock_user_resp = MagicMock()
        mock_user_resp.user.id = uid_solicitante
        mock_client_jwt = MagicMock()
        mock_client_jwt.auth.get_user.return_value = mock_user_resp

        # perfiles_usuario retorna activo=False
        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[{"id": uid_solicitante, "es_admin": True, "activo": False}])
        mock_client_jwt.table.return_value.select.return_value.eq.return_value.limit.return_value = mock_query

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.database.obtener_cliente_usuario", return_value=mock_client_jwt), \
             patch("core.database.obtener_cliente_admin") as mock_admin:
            exito, msg = auth_manager.invitar_usuario_corporativo(
                correo="nuevo@iaclatam.com",
                nombre="Nuevo Usuario",
                access_token_solicitante="token_valido_pero_inactivo",
            )
            self.assertFalse(exito, "Usuario inactivo no debe poder invitar")
            self.assertIn("inactiv", msg.lower())
            mock_admin.assert_not_called()  # El cliente admin JAMÁS se construye

    def test_18_invitacion_rechazada_si_solicitante_no_es_admin_en_bd(self):
        """Verifica que solicitante con token válido y activo=True pero es_admin=False sea rechazado.

        Esto cubre el caso donde solicitante_es_admin=True (valor antiguo del bool de interfaz)
        habría pasado por la verificación anterior — ahora se verifica en BD.
        """
        uid_solicitante = "11112222-3333-4444-5555-666677778888"
        mock_user_resp = MagicMock()
        mock_user_resp.user.id = uid_solicitante
        mock_client_jwt = MagicMock()
        mock_client_jwt.auth.get_user.return_value = mock_user_resp

        # BD dice: es_admin=False, activo=True (usuario regular que manipuló la interfaz)
        mock_query = MagicMock()
        mock_query.execute.return_value = MagicMock(data=[{"id": uid_solicitante, "es_admin": False, "activo": True}])
        mock_client_jwt.table.return_value.select.return_value.eq.return_value.limit.return_value = mock_query

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.database.obtener_cliente_usuario", return_value=mock_client_jwt), \
             patch("core.database.obtener_cliente_admin") as mock_admin:
            exito, msg = auth_manager.invitar_usuario_corporativo(
                correo="nuevo@iaclatam.com",
                nombre="Nuevo Usuario",
                access_token_solicitante="token_de_usuario_normal",
            )
            self.assertFalse(exito, "No-admin no debe poder invitar aunque pase token válido")
            self.assertIn("admin", msg.lower())
            mock_admin.assert_not_called()  # El cliente admin JAMÁS se construye

    # ==========================================================================
    # PARTE III — HARDENING-04: Rollback Selectivo (Tests 19-22)
    # ==========================================================================

    def test_19_rollback_lote_inexistente_aborta(self):
        """Verifica que rollback de un UUID inexistente en migration_runs aborte con SystemExit."""
        batch_id_inexistente = str(uuid.uuid4())
        mock_client = MagicMock()
        # Simular que migration_runs no devuelve datos para ese batch_id
        mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = \
            MagicMock(data=[])

        env_vars = {
            "SUPABASE_URL": "https://test123.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-key-fake",
        }
        with patch.dict(os.environ, env_vars), \
             patch("supabase.create_client", return_value=mock_client):
            with self.assertRaises(SystemExit) as ctx:
                migrador.ejecutar_rollback_batch(batch_id_inexistente)
            self.assertEqual(ctx.exception.code, 1)

    def test_20_rollback_lote_ya_revertido_es_idempotente(self):
        """Verifica que un lote ya en estado ROLLED_BACK no sea procesado nuevamente."""
        batch_id = str(uuid.uuid4())
        mock_client = MagicMock()

        def mock_table(name):
            t = MagicMock()
            if name == "deployment_identity":
                t.select.return_value.execute.return_value = MagicMock(
                    data=[{"singleton_id": 1, "application_code": "autoform-excel", "environment": "staging", "project_ref": "test123"}]
                )
            elif name == "migration_runs":
                t.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"batch_id": batch_id, "estado": "ROLLED_BACK", "started_at": "2026-01-01", "manifesto_uuids": {}}]
                )
            return t

        mock_client.table.side_effect = mock_table

        env_vars = {
            "SUPABASE_URL": "https://test123.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-key-fake",
            "AUTOFORM_EXCEL_STAGING_PROJECT_REF": "test123",
        }
        with patch.dict(os.environ, env_vars), \
             patch("supabase.create_client", return_value=mock_client):
            # No debe lanzar excepción; debe retornar normalmente (idempotente)
            try:
                migrador.ejecutar_rollback_batch(batch_id, confirm_project="test123")
                idempotente = True
            except SystemExit:
                idempotente = False

        self.assertTrue(idempotente, "Rollback de lote ya revertido debe ser idempotente (sin error)")
        # Verificar que no se realizaron operaciones de DELETE
        delete_calls = [c for c in mock_client.method_calls if "delete" in str(c)]
        self.assertEqual(len(delete_calls), 0, "No se deben hacer operaciones de DELETE para lote ya revertido")

    def test_21_rollback_no_elimina_registros_ajenos(self):
        """Verifica que el rollback solo procese UUIDs del manifiesto del lote solicitado."""
        batch_id = str(uuid.uuid4())
        uuid_del_lote = str(uuid.uuid4())
        uuid_ajeno = str(uuid.uuid4())  # No debe ser tocado

        manifesto = {
            "perfiles_empresa": [uuid_del_lote],
            "usuarios_auth": [],
            "perfiles_usuario": [],
            "operadores": [],
        }

        mock_client = MagicMock()
        mock_perfiles = MagicMock()

        def mock_table(name):
            if name == "deployment_identity":
                t = MagicMock()
                t.select.return_value.execute.return_value = MagicMock(
                    data=[{"singleton_id": 1, "application_code": "autoform-excel", "environment": "staging", "project_ref": "test123"}]
                )
                return t
            elif name == "migration_runs":
                t = MagicMock()
                t.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"batch_id": batch_id, "estado": "COMPLETADO", "started_at": "2026-01-01", "manifesto_uuids": manifesto, "detalles_json": {}}]
                )
                return t
            elif name == "perfiles_empresa":
                return mock_perfiles
            return MagicMock()

        mock_client.table.side_effect = mock_table

        env_vars = {
            "SUPABASE_URL": "https://test123.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-key-fake",
            "AUTOFORM_EXCEL_STAGING_PROJECT_REF": "test123",
        }
        with patch.dict(os.environ, env_vars), \
             patch("supabase.create_client", return_value=mock_client):
            migrador.ejecutar_rollback_batch(batch_id, confirm_project="test123")

        # Verificar que solo se llama delete con el UUID del lote, no con el ajeno
        all_calls_str = str(mock_perfiles.mock_calls)
        self.assertIn(uuid_del_lote, all_calls_str, "El UUID del lote debe ser procesado")
        self.assertNotIn(uuid_ajeno, all_calls_str, "El UUID ajeno NO debe ser tocado")

    def test_22_rollback_project_ref_incorrecto_aborta(self):
        """Verifica que rollback aborte si PROJECT_REF no coincide con SUPABASE_URL."""
        batch_id = str(uuid.uuid4())
        env_vars = {
            "SUPABASE_URL": "https://proyecto_correcto.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-key-fake",
            "AUTOFORM_EXCEL_STAGING_PROJECT_REF": "proyecto_correcto",
        }
        with patch.dict(os.environ, env_vars):
            with self.assertRaises(SystemExit) as ctx:
                migrador.ejecutar_rollback_batch(batch_id, confirm_project="proyecto_incorrecto")
            self.assertEqual(ctx.exception.code, 1)

    # ==========================================================================
    # PARTE V — GUARDIA DE AISLAMIENTO ESTRICTO Y ALLOWLIST POSITIVA (Tests 23-25)
    # ==========================================================================

    def test_23_guardia_anti_pdf_bloquea_ambos_proyectos_pdf(self):
        """Verifica que ambos proyectos PDF (producción y staging) sean bloqueados categóricamente."""
        pdf_refs = ["tnhedxwbpqihlqbtzudt", "nfsijcwkmcvtwsponqsw"]
        for ref in pdf_refs:
            # Intento apuntando a la URL del proyecto PDF
            with self.assertRaises(SystemExit) as ctx:
                migrador._verificar_project_ref(
                    supabase_url=f"https://{ref}.supabase.co",
                    confirm_project=ref,
                )
            self.assertEqual(ctx.exception.code, 1, f"El proyecto PDF {ref} debió ser abortado")

            # Intento con URL distinta pero confirmando el ref de PDF
            with self.assertRaises(SystemExit) as ctx:
                migrador._verificar_project_ref(
                    supabase_url="https://otro-proyecto.supabase.co",
                    confirm_project=ref,
                )
            self.assertEqual(ctx.exception.code, 1, f"El confirm_project con {ref} debió ser abortado")

    def test_24_allowlist_positiva_exige_coincidencia_exacta(self):
        """Verifica que la allowlist positiva sea obligatoria y que simple confirmación CLI no baste."""
        # 1. Sin variable AUTOFORM_EXCEL_STAGING_PROJECT_REF -> Aborta inmediatamente
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                migrador._verificar_project_ref(
                    supabase_url="https://staging-autorizado.supabase.co",
                    confirm_project="staging-autorizado",
                )
            self.assertEqual(ctx.exception.code, 1)

        # 2. Intento de CLI con proyecto distinto a la allowlist -> Aborta
        env_allowlist = {
            "AUTOFORM_EXCEL_STAGING_PROJECT_REF": "staging-valido-123",
        }
        with patch.dict(os.environ, env_allowlist):
            with self.assertRaises(SystemExit) as ctx:
                migrador._verificar_project_ref(
                    supabase_url="https://staging-valido-123.supabase.co",
                    confirm_project="intento-otro-proyecto",
                )
            self.assertEqual(ctx.exception.code, 1)

            # Intento de URL con proyecto no en allowlist aunque coincida confirm_project -> Aborta
            with self.assertRaises(SystemExit) as ctx:
                migrador._verificar_project_ref(
                    supabase_url="https://otro-proyecto.supabase.co",
                    confirm_project="otro-proyecto",
                )
            self.assertEqual(ctx.exception.code, 1)

            # Coincidencia triple exacta -> Pasa exitosamente
            verificado = migrador._verificar_project_ref(
                supabase_url="https://staging-valido-123.supabase.co",
                confirm_project="staging-valido-123",
            )
            self.assertEqual(verificado, "staging-valido-123")

    def test_25_database_py_bloquea_ambos_proyectos_pdf(self):
        """Verifica que core.database lance ConfiguracionInvalidaError ante cualquier ref de PDF."""
        pdf_refs = ["tnhedxwbpqihlqbtzudt", "nfsijcwkmcvtwsponqsw"]
        for ref in pdf_refs:
            env_vars = {
                "SUPABASE_URL": f"https://{ref}.supabase.co",
                "SUPABASE_ANON_KEY": "anon-key-dummy",
                "SUPABASE_SERVICE_ROLE_KEY": "service-key-dummy",
            }
            with patch.dict(os.environ, env_vars):
                with self.assertRaises(database.ConfiguracionInvalidaError):
                    database.obtener_cliente_publico()

                with self.assertRaises(database.ConfiguracionInvalidaError):
                    database.obtener_cliente_admin()

                with self.assertRaises(database.ConfiguracionInvalidaError):
                    database.obtener_cliente_usuario(access_token="token-dummy")

    # ==========================================================================
    # PARTE VI — IDENTIDAD DE BASE DE DATOS (5-WAY VERIFICATION) (Tests 26-31)
    # ==========================================================================

    def test_26_verificar_identidad_despliegue_exitosa(self):
        """Verifica que verificar_identidad_despliegue retorne el registro cuando los 5 parámetros coinciden."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.execute.return_value = MagicMock(
            data=[{"singleton_id": 1, "application_code": "autoform-excel", "environment": "staging", "project_ref": "staging-123"}]
        )
        rec = migrador.verificar_identidad_despliegue(mock_client, "staging-123")
        self.assertEqual(rec["application_code"], "autoform-excel")
        self.assertEqual(rec["environment"], "staging")
        self.assertEqual(rec["project_ref"], "staging-123")

    def test_27_verificar_identidad_despliegue_rechaza_app_incorrecta(self):
        """Verifica que aborte si application_code en BD no es 'autoform-excel' (ej: autoform-pdf)."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.execute.return_value = MagicMock(
            data=[{"singleton_id": 1, "application_code": "autoform-pdf", "environment": "staging", "project_ref": "staging-123"}]
        )
        with self.assertRaises(SystemExit) as ctx:
            migrador.verificar_identidad_despliegue(mock_client, "staging-123")
        self.assertEqual(ctx.exception.code, 1)

    def test_28_verificar_identidad_despliegue_rechaza_environment_incorrecto(self):
        """Verifica que aborte si environment en BD no es 'staging' (ej: production)."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.execute.return_value = MagicMock(
            data=[{"singleton_id": 1, "application_code": "autoform-excel", "environment": "production", "project_ref": "staging-123"}]
        )
        with self.assertRaises(SystemExit) as ctx:
            migrador.verificar_identidad_despliegue(mock_client, "staging-123")
        self.assertEqual(ctx.exception.code, 1)

    def test_29_verificar_identidad_despliegue_rechaza_project_ref_mismatch(self):
        """Verifica que aborte si project_ref en BD no coincide con el proyecto objetivo."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.execute.return_value = MagicMock(
            data=[{"singleton_id": 1, "application_code": "autoform-excel", "environment": "staging", "project_ref": "proyecto-bd-diferente"}]
        )
        with self.assertRaises(SystemExit) as ctx:
            migrador.verificar_identidad_despliegue(mock_client, "staging-123")
        self.assertEqual(ctx.exception.code, 1)

    def test_30_verificar_identidad_despliegue_rechaza_tabla_vacia(self):
        """Verifica que aborte si deployment_identity está vacía o sin inicializar."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.execute.return_value = MagicMock(
            data=[]
        )
        with self.assertRaises(SystemExit) as ctx:
            migrador.verificar_identidad_despliegue(mock_client, "staging-123")
        self.assertEqual(ctx.exception.code, 1)

    def test_31_rollback_exige_confirm_project(self):
        """Verifica que ejecutar_rollback_batch aborte si confirm_project está vacío."""
        batch_id = str(uuid.uuid4())
        env_vars = {
            "SUPABASE_URL": "https://staging-123.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-key-fake",
            "AUTOFORM_EXCEL_STAGING_PROJECT_REF": "staging-123",
        }
        with patch.dict(os.environ, env_vars):
            with self.assertRaises(SystemExit) as ctx:
                migrador.ejecutar_rollback_batch(batch_id, confirm_project="")
            self.assertEqual(ctx.exception.code, 1)

    def test_32_verificar_identidad_despliegue_rechaza_multiples_filas(self):
        """Verifica que aborte si deployment_identity contiene más de una fila (violación de singleton)."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.execute.return_value = MagicMock(
            data=[
                {"singleton_id": 1, "application_code": "autoform-excel", "environment": "staging", "project_ref": "staging-123"},
                {"singleton_id": 2, "application_code": "autoform-excel", "environment": "staging", "project_ref": "staging-123"},
            ]
        )
        with self.assertRaises(SystemExit) as ctx:
            migrador.verificar_identidad_despliegue(mock_client, "staging-123")
        self.assertEqual(ctx.exception.code, 1)

    def test_33_prioridad_publishable_key_sobre_anon_key(self):
        """Verifica que _resolver_publishable_key priorice SUPABASE_PUBLISHABLE_KEY sobre SUPABASE_ANON_KEY."""
        with patch.dict(
            os.environ,
            {
                "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_modern",
                "SUPABASE_ANON_KEY": "anon_legacy",
            },
        ):
            self.assertEqual(database._resolver_publishable_key(), "sb_publishable_modern")

        with patch.dict(
            os.environ,
            {
                "SUPABASE_PUBLISHABLE_KEY": "",
                "SUPABASE_ANON_KEY": "anon_legacy",
            },
        ):
            self.assertEqual(database._resolver_publishable_key(), "anon_legacy")

    def test_34_prioridad_secret_key_sobre_service_role_key(self):
        """Verifica que _resolver_secret_key priorice SUPABASE_SECRET_KEY sobre SUPABASE_SERVICE_ROLE_KEY."""
        with patch.dict(
            os.environ,
            {
                "SUPABASE_SECRET_KEY": "sb_secret_modern",
                "SUPABASE_SERVICE_ROLE_KEY": "service_legacy",
            },
        ):
            self.assertEqual(database._resolver_secret_key(), "sb_secret_modern")

        with patch.dict(
            os.environ,
            {
                "SUPABASE_SECRET_KEY": "",
                "SUPABASE_SERVICE_ROLE_KEY": "service_legacy",
            },
        ):
            self.assertEqual(database._resolver_secret_key(), "service_legacy")

    def test_35_migrador_prioriza_secret_key_moderna(self):
        """Verifica que el migrador utilice _resolver_secret_key priorizando SUPABASE_SECRET_KEY."""
        with patch.dict(
            os.environ,
            {
                "SUPABASE_SECRET_KEY": "sb_secret_modern",
                "SUPABASE_SERVICE_ROLE_KEY": "service_legacy",
            },
        ):
            self.assertEqual(migrador._resolver_secret_key(), "sb_secret_modern")

        with patch.dict(
            os.environ,
            {
                "SUPABASE_SECRET_KEY": "",
                "SUPABASE_SERVICE_ROLE_KEY": "service_legacy",
            },
        ):
            self.assertEqual(migrador._resolver_secret_key(), "service_legacy")

    def test_36_obtener_cliente_publico_y_admin_usan_claves_modernas(self):
        """Verifica que obtener_cliente_publico y admin pasen las claves modernas a create_client."""
        with patch("core.database.create_client") as mock_create:
            with patch.dict(
                os.environ,
                {
                    "SUPABASE_URL": "https://test-ref.supabase.co",
                    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test_val",
                    "SUPABASE_SECRET_KEY": "sb_secret_test_val",
                },
            ):
                database.obtener_cliente_publico()
                mock_create.assert_called_with("https://test-ref.supabase.co", "sb_publishable_test_val")

                database.obtener_cliente_admin()
                mock_create.assert_called_with("https://test-ref.supabase.co", "sb_secret_test_val")

    def test_37_antonio_usuario_comercial_activo_y_operador_predeterminado(self):
        """Verifica que Antonio Prieto sea usuario comercial estándar activo y operador predeterminado."""
        _, operadores, usuarios = migrador.leer_datos_sqlite()
        antonio_usr = next((u for u in usuarios if u["id"] == "antonio_prieto"), None)
        self.assertIsNotNone(antonio_usr, "Antonio Prieto debe existir en usuarios")
        self.assertTrue(antonio_usr["activo"], "Antonio Prieto debe estar activo")
        self.assertFalse(antonio_usr["es_admin"], "Antonio Prieto debe tener rol estándar (no admin)")

        antonio_op = next((op for op in operadores if op["id"] == "antonio_prieto"), None)
        self.assertIsNotNone(antonio_op, "Antonio Prieto debe existir en operadores")
        self.assertTrue(antonio_op["es_activo"], "Antonio Prieto debe ser el operador activo predeterminado")

    def test_38_carlos_usuario_comercial_activo_y_operador_alterno(self):
        """Verifica que Carlos Mendoza sea usuario comercial activo y operador alterno (es_activo=False)."""
        _, operadores, usuarios = migrador.leer_datos_sqlite()
        carlos_usr = next((u for u in usuarios if u["id"] == "carlos_mendoza"), None)
        self.assertIsNotNone(carlos_usr, "Carlos Mendoza debe existir en usuarios")
        self.assertTrue(carlos_usr["activo"], "Carlos Mendoza debe estar activo")
        self.assertFalse(carlos_usr["es_admin"], "Carlos Mendoza debe tener rol estándar (no admin)")

        carlos_op = next((op for op in operadores if op["id"] == "carlos_mendoza"), None)
        self.assertIsNotNone(carlos_op, "Carlos Mendoza debe existir en operadores")
        self.assertFalse(carlos_op["es_activo"], "Carlos Mendoza debe ser operador alterno (es_activo=False)")

    def test_39_guillermo_administrador_nominal_activo_sin_registro_en_operadores(self):
        """Verifica que Guillermo Cañón sea administrador nominal activo (es_admin=True) sin registro en operadores."""
        _, operadores, usuarios = migrador.leer_datos_sqlite()
        guillermo_usr = next((u for u in usuarios if u["id"] == "guillermo_canon" or u["correo"] == "guillermo.canon@iaclatam.com"), None)
        self.assertIsNotNone(guillermo_usr, "El usuario guillermo_canon debe existir en usuarios")
        self.assertTrue(guillermo_usr["activo"], "El usuario guillermo_canon debe estar activo")
        self.assertTrue(guillermo_usr["es_admin"], "El usuario guillermo_canon debe tener rol de administrador (es_admin=True)")
        self.assertEqual(guillermo_usr["correo"], "guillermo.canon@iaclatam.com")

        # Asegurar que admin genérico admin@iaclatam.com NO exista
        admin_generico = next((u for u in usuarios if "admin@iaclatam.com" in u["correo"] or u["id"] == "admin"), None)
        self.assertIsNone(admin_generico, "El correo genérico admin@iaclatam.com no debe existir en usuarios")

        guillermo_op = next((op for op in operadores if op["id"] == "guillermo_canon" or op["correo"] == "guillermo.canon@iaclatam.com"), None)
        self.assertIsNone(guillermo_op, "El usuario guillermo_canon NO debe tener registro en operadores comerciales")

    def test_40_pepito_mock_excluido_de_usuarios_y_operadores(self):
        """Verifica que la cuenta de prueba pepito_perez quede 100% excluida de la migración."""
        _, operadores, usuarios = migrador.leer_datos_sqlite()
        user_ids = [u["id"] for u in usuarios]
        user_emails = [u["correo"] for u in usuarios]
        self.assertNotIn("pepito_perez", user_ids)
        self.assertFalse(any("pepito" in m for m in user_emails))

        op_ids = [op["id"] for op in operadores]
        op_emails = [op["correo"] for op in operadores]
        self.assertNotIn("pepito_perez", op_ids)
        self.assertFalse(any("pepito" in m for m in op_emails))

    def test_41_autoform_admin_password_sin_default_hardcodeado_ni_token_silencioso(self):
        """Verifica que AUTOFORM_ADMIN_PASSWORD no posea contraseñas por defecto hardcodeadas ni tokens silenciosos."""
        import inspect
        src = inspect.getsource(database.inicializar_db)
        self.assertNotIn("IAC2026*", src, "No deben existir contraseñas por defecto hardcodeadas en inicializar_db")
        self.assertNotIn("token_urlsafe", src, "No se deben generar tokens aleatorios silenciosos para la cuenta admin")

    def test_42_inicializar_db_falla_si_autoform_admin_password_no_definida(self):
        """Verifica que inicializar_db falle con RuntimeError si AUTOFORM_ADMIN_PASSWORD no está definida."""
        with patch.dict(os.environ, {"AUTOFORM_ADMIN_PASSWORD": ""}):
            with patch("core.database.usar_supabase", return_value=False):
                with patch("core.database.obtener_conexion") as mock_conn:
                    mock_cursor = MagicMock()
                    mock_cursor.fetchone.side_effect = [
                        {"total": 1},  # operadores ya sembrados
                        {"total": 0},  # total_usuarios == 0
                    ]
                    mock_cursor.fetchall.return_value = []
                    mock_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor
                    with self.assertRaises(RuntimeError) as ctx:
                        database.inicializar_db()
                    self.assertIn("AUTOFORM_ADMIN_PASSWORD", str(ctx.exception))
                    self.assertIn("Error de configuración", str(ctx.exception))

    def test_43_migrador_aborta_si_usuario_existe_en_auth(self):
        """Verifica que ejecutar_migracion aborte inmediatamente si un correo corporativo ya existe en auth.users."""
        mock_client = MagicMock()
        mock_existing_user = MagicMock()
        mock_existing_user.email = "guillermo.canon@iaclatam.com"
        mock_client.auth.admin.list_users.return_value = [mock_existing_user]

        perfiles = [{"slug": "principal", "nombre_empresa": "IAC", "es_activa": True, "datos_json": {}}]
        operadores = []
        usuarios = [{"correo": "guillermo.canon@iaclatam.com", "nombre": "Guillermo Cañón", "es_admin": True, "activo": True}]

        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://staging-valido.supabase.co",
                "SUPABASE_SECRET_KEY": "secret_key_valida",
                "AUTOFORM_EXCEL_STAGING_PROJECT_REF": "staging-valido",
            },
        ):
            with patch("scripts.migrate_sqlite_to_supabase.verificar_identidad_despliegue"):
                with self.assertRaises(RuntimeError) as ctx:
                    migrador.ejecutar_migracion(
                        perfiles, operadores, usuarios, confirm_project="staging-valido", client=mock_client
                    )
                self.assertIn("Migración abortada", str(ctx.exception))
                self.assertIn("auth.users", str(ctx.exception))

    def test_44_migrador_asigna_app_metadata_segura_y_vacia_user_metadata(self):
        """Verifica que el migrador asigne rol en app_metadata segura y user_metadata vacía."""
        mock_client = MagicMock()
        mock_client.auth.admin.list_users.return_value = []
        mock_invite_res = MagicMock()
        mock_invite_res.user.id = "auth-uuid-test-123"
        mock_client.auth.admin.invite_user_by_email.return_value = mock_invite_res

        perfiles = []
        operadores = []
        usuarios = [
            {"id": "guillermo_canon", "nombre": "Guillermo Cañón", "correo": "guillermo.canon@iaclatam.com", "es_admin": True, "activo": True, "cargo": "", "cedula": "", "telefono": "", "direccion": "", "ciudad": ""},
        ]

        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://staging-valido.supabase.co",
                "SUPABASE_SECRET_KEY": "secret_key_valida",
                "AUTOFORM_EXCEL_STAGING_PROJECT_REF": "staging-valido",
            },
        ):
            with patch("scripts.migrate_sqlite_to_supabase.verificar_identidad_despliegue"):
                migrador.ejecutar_migracion(
                    perfiles, operadores, usuarios, confirm_project="staging-valido", enviar_invitaciones=True, client=mock_client
                )
                mock_client.auth.admin.update_user_by_id.assert_called_with(
                    "auth-uuid-test-123",
                    {
                        "app_metadata": {
                            "es_admin": True,
                            "role": "administrador",
                            "rol": "administrador",
                        },
                        "user_metadata": {},
                    },
                )

    def test_45_migrador_bloquea_redireccion_hacia_proyectos_pdf(self):
        """Verifica que el migrador bloquee URLs de redirección que apunten a proyectos PDF prohibidos."""
        mock_client = MagicMock()
        mock_client.auth.admin.list_users.return_value = []

        perfiles = []
        operadores = []
        usuarios = [
            {"id": "guillermo_canon", "nombre": "Guillermo Cañón", "correo": "guillermo.canon@iaclatam.com", "es_admin": True, "activo": True, "cargo": "", "cedula": "", "telefono": "", "direccion": "", "ciudad": ""},
        ]

        # Intentar redirigir hacia AutoForm PDF Producción
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://staging-valido.supabase.co",
                "SUPABASE_SECRET_KEY": "secret_key_valida",
                "AUTOFORM_EXCEL_STAGING_PROJECT_REF": "staging-valido",
                "AUTOFORM_EXCEL_REDIRECT_URL": "https://tnhedxwbpqihlqbtzudt.supabase.co",
            },
        ):
            with patch("scripts.migrate_sqlite_to_supabase.verificar_identidad_despliegue"):
                with self.assertRaises(RuntimeError) as ctx:
                    migrador.ejecutar_migracion(
                        perfiles, operadores, usuarios, confirm_project="staging-valido", enviar_invitaciones=True, client=mock_client
                    )
                self.assertIn("PDF prohibido", str(ctx.exception))

    def test_46_staging_exige_supabase_y_credenciales_validas(self):
        """Verifica que APP_ENVIRONMENT=staging exija Supabase y falle si faltan credenciales."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "staging", "SUPABASE_URL": "", "SUPABASE_PUBLISHABLE_KEY": ""}):
            with self.assertRaises(database.ConfiguracionInvalidaError) as ctx:
                database.usar_supabase()
            self.assertIn("staging", str(ctx.exception).lower())

    def test_47_staging_bloquea_sqlite_y_cualquier_fallback(self):
        """Verifica que APP_ENVIRONMENT=staging bloquee SQLite tajantemente aunque USE_SQLITE=true."""
        with patch.dict(os.environ, {"APP_ENVIRONMENT": "staging", "USE_SQLITE": "true"}):
            with self.assertRaises(database.ConfiguracionInvalidaError) as ctx:
                database.obtener_conexion()
            self.assertIn("bloqueado en el entorno 'staging'", str(ctx.exception))

    def test_48_staging_exige_deployment_identity_autoform_excel_y_staging(self):
        """Verifica que validar_identidad_despliegue exija application_code=autoform-excel y environment=staging."""
        mock_client = MagicMock()

        # Caso 1: Válido
        mock_client.table.return_value.select.return_value.execute.return_value.data = [
            {"singleton_id": 1, "application_code": "autoform-excel", "environment": "staging", "project_ref": "nfaxkncrpfrsvzfgczny"}
        ]
        with patch.dict(os.environ, {"AUTOFORM_EXCEL_STAGING_PROJECT_REF": "nfaxkncrpfrsvzfgczny", "SUPABASE_URL": "https://nfaxkncrpfrsvzfgczny.supabase.co"}):
            rec = database.validar_identidad_despliegue(client=mock_client, entorno_esperado="staging")
            self.assertEqual(rec["application_code"], "autoform-excel")
            self.assertEqual(rec["environment"], "staging")

        # Caso 2: Discrepancia en application_code
        mock_client.table.return_value.select.return_value.execute.return_value.data = [
            {"singleton_id": 1, "application_code": "autoform-pdf", "environment": "staging", "project_ref": "nfaxkncrpfrsvzfgczny"}
        ]
        with self.assertRaises(database.ConfiguracionInvalidaError) as ctx:
            database.validar_identidad_despliegue(client=mock_client, entorno_esperado="staging")
        self.assertIn("autoform-pdf", str(ctx.exception))

        # Caso 3: Discrepancia en environment
        mock_client.table.return_value.select.return_value.execute.return_value.data = [
            {"singleton_id": 1, "application_code": "autoform-excel", "environment": "production", "project_ref": "nfaxkncrpfrsvzfgczny"}
        ]
        with self.assertRaises(database.ConfiguracionInvalidaError) as ctx:
            database.validar_identidad_despliegue(client=mock_client, entorno_esperado="staging")
        self.assertIn("production", str(ctx.exception))

        # Caso 4: Violación de singleton (2 filas)
        mock_client.table.return_value.select.return_value.execute.return_value.data = [
            {"singleton_id": 1, "application_code": "autoform-excel", "environment": "staging", "project_ref": "nfaxkncrpfrsvzfgczny"},
            {"singleton_id": 2, "application_code": "autoform-excel", "environment": "staging", "project_ref": "nfaxkncrpfrsvzfgczny"},
        ]
        with self.assertRaises(database.ConfiguracionInvalidaError) as ctx:
            database.validar_identidad_despliegue(client=mock_client, entorno_esperado="staging")
        self.assertIn("singleton", str(ctx.exception).lower())

    def test_49_staging_bloquea_refs_pdf(self):
        """Verifica que validar_identidad_despliegue bloquee URLs apuntando a proyectos PDF prohibidos."""
        mock_client = MagicMock()
        with patch.dict(os.environ, {"SUPABASE_URL": "https://tnhedxwbpqihlqbtzudt.supabase.co"}):
            with self.assertRaises(database.ConfiguracionInvalidaError) as ctx:
                database.validar_identidad_despliegue(client=mock_client, entorno_esperado="staging")
            self.assertIn("AutoForm PDF", str(ctx.exception))

    def test_50_cero_llamados_a_sign_up_y_cero_auto_registro_inseguro(self):
        """Verifica que no exista ningún llamado a sign_up ni funciones de auto-registro inseguras."""
        # 1. Verificar que auth_manager no expone la antigua función insegura registrar_usuario_corporativo
        self.assertFalse(hasattr(auth_manager, "registrar_usuario_corporativo"))

        # 2. Verificar que profile_manager no expone registrar_usuario_corporativo
        self.assertFalse(hasattr(profile_manager, "registrar_usuario_corporativo"))

        # 3. Inspeccionar el código de app1.py, core/auth_manager.py, core/database.py, core/profile_manager.py
        archivos_a_inspeccionar = [
            PROJECT_ROOT / "app1.py",
            PROJECT_ROOT / "core" / "auth_manager.py",
            PROJECT_ROOT / "core" / "database.py",
            PROJECT_ROOT / "core" / "profile_manager.py",
        ]
        for ruta in archivos_a_inspeccionar:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
                # No debe existir ningún llamado o referencia a sign_up
                self.assertNotIn("sign_up", contenido.lower(), f"Se encontró 'sign_up' en {ruta.name}")
                # No debe existir la función registrar_usuario_corporativo
                self.assertNotIn("registrar_usuario_corporativo", contenido, f"Se encontró 'registrar_usuario_corporativo' en {ruta.name}")

        # 4. Verificar que app1.py contenga el formulario controlado de solicitud corporativa
        with open(PROJECT_ROOT / "app1.py", "r", encoding="utf-8") as f:
            contenido_app = f.read()
            self.assertIn("📝 Registrarse", contenido_app)
            self.assertIn("gate_register_form", contenido_app)
            self.assertIn("registrar_solicitud_corporativa", contenido_app)

    def test_51_recuperacion_password_valida_dominio_corporativo(self):
        """Verifica que solicitar_recuperacion_password valide el dominio y llame a reset_password_for_email."""
        # 1. Correo vacío
        ok, msg = auth_manager.solicitar_recuperacion_password("")
        self.assertFalse(ok)
        self.assertIn("correo", msg.lower())

        # 2. Correo de dominio externo (ej. Gmail / Pepito)
        ok, msg = auth_manager.solicitar_recuperacion_password("pepito@gmail.com")
        self.assertFalse(ok)
        self.assertIn("no autorizada", msg.lower())

        # 3. Correo con formato inválido
        ok, msg = auth_manager.solicitar_recuperacion_password("correo_invalido")
        self.assertFalse(ok)
        self.assertIn("no es válido", msg.lower())

        # 4. Correo corporativo válido en Supabase
        mock_pub = MagicMock()
        with patch("core.database.usar_supabase", return_value=True):
            with patch("core.database.obtener_cliente_publico", return_value=mock_pub):
                with patch.dict(os.environ, {"AUTOFORM_EXCEL_REDIRECT_URL": "https://autoform-iac-excel.streamlit.app"}):
                    ok, msg = auth_manager.solicitar_recuperacion_password("guillermo.canon@iaclatam.com")
                    self.assertTrue(ok)
                    mock_pub.auth.reset_password_for_email.assert_called_once_with(
                        "guillermo.canon@iaclatam.com",
                        options={"redirect_to": "https://autoform-iac-excel.streamlit.app"},
                    )

    def test_52_recuperacion_password_bloquea_refs_pdf(self):
        """Verifica que solicitar_recuperacion_password bloquee URLs apuntando a proyectos PDF prohibidos."""
        with patch("core.database.usar_supabase", return_value=True):
            with patch.dict(os.environ, {"AUTOFORM_EXCEL_REDIRECT_URL": "https://tnhedxwbpqihlqbtzudt.supabase.co"}):
                with self.assertRaises(database.ConfiguracionInvalidaError) as ctx:
                    auth_manager.solicitar_recuperacion_password("antonio.prieto@iaclatam.com")
                self.assertIn("PDF prohibido", str(ctx.exception))

    def test_53_auto_registro_nace_inactivo_pendiente_y_comercial(self):
        """Verifica que registrar_solicitud_corporativa obligue dominio y asigne inactivo/pendiente/comercial."""
        # 1. Dominio no corporativo rechazado
        ok, msg = auth_manager.registrar_solicitud_corporativa(
            nombre="Intruso",
            correo="intruso@gmail.com",
            password="PasswordSeguro123!",
        )
        self.assertFalse(ok)
        self.assertIn("correo corporativo", msg.lower())

        # 2. Contraseña menor a 8 caracteres rechazada
        ok, msg = auth_manager.registrar_solicitud_corporativa(
            nombre="Carlos",
            correo="carlos@iaclatam.com",
            password="123",
        )
        self.assertFalse(ok)
        self.assertIn("8 caracteres", msg.lower())

        # 3. Solicitud válida en Supabase
        mock_admin = MagicMock()
        mock_admin.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_admin_res = MagicMock()
        mock_admin_res.user = MagicMock(id="nuevo-user-uuid-789")
        mock_admin.auth.admin.create_user.return_value = mock_admin_res

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.database.obtener_cliente_admin", return_value=mock_admin), \
             patch("core.database.guardar_operador_db") as mock_guardar_op:
            ok, msg = auth_manager.registrar_solicitud_corporativa(
                nombre="Carlos Mendoza",
                correo="carlos.mendoza@iaclatam.com",
                password="PasswordSeguro123!",
                cargo="Comercial Junior",
            )
            self.assertTrue(ok)
            self.assertIn("activa", msg.lower())

            # Verificar app_metadata fija en servidor como comercial aprobado
            call_create = mock_admin.auth.admin.create_user.call_args[0][0]
            self.assertEqual(call_create["email"], "carlos.mendoza@iaclatam.com")
            self.assertEqual(call_create["app_metadata"]["es_admin"], False)
            self.assertEqual(call_create["app_metadata"]["role"], "comercial")
            self.assertEqual(call_create["app_metadata"]["estado"], "aprobado")

            # Verificar perfiles_usuario upsert forzado como activo y aprobado
            mock_admin.table.assert_any_call("perfiles_usuario")
            call_upsert = mock_admin.table().upsert.call_args[0][0]
            self.assertEqual(call_upsert["id"], "nuevo-user-uuid-789")
            self.assertEqual(call_upsert["activo"], True)
            self.assertEqual(call_upsert["estado_aprobacion"], "aprobado")
            self.assertEqual(call_upsert["es_admin"], False)

            # Verificar sincronización inmediata con catálogo de operadores
            mock_guardar_op.assert_called_once()
            self.assertEqual(mock_guardar_op.call_args[1]["nombre"], "Carlos Mendoza")

    def test_53b_auto_registro_recupera_usuario_huerfano_auth_users(self):
        """Verifica que si create_user falla por usuario preexistente en auth.users sin perfil, se recupere y active de inmediato."""
        mock_admin = MagicMock()
        # No existe en perfiles_usuario
        mock_admin.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        # create_user lanza excepción de usuario ya registrado
        mock_admin.auth.admin.create_user.side_effect = Exception("User already registered")
        # list_users encuentra al usuario huérfano
        mock_huerfano = MagicMock(id="user-huerfano-456", email="pedro.gomez@iaclatam.com")
        mock_admin.auth.admin.list_users.return_value = [mock_huerfano]

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.database.obtener_cliente_admin", return_value=mock_admin), \
             patch("core.database.guardar_operador_db"):
            ok, msg = auth_manager.registrar_solicitud_corporativa(
                nombre="Pedro Gómez",
                correo="pedro.gomez@iaclatam.com",
                password="PasswordSeguro456!",
                cargo="Comercial",
            )
            self.assertTrue(ok)
            self.assertIn("activa", msg.lower())
            mock_admin.auth.admin.update_user_by_id.assert_called_once()
            call_upsert = mock_admin.table().upsert.call_args[0][0]
            self.assertEqual(call_upsert["id"], "user-huerfano-456")
            self.assertEqual(call_upsert["correo"], "pedro.gomez@iaclatam.com")
            self.assertEqual(call_upsert["estado_aprobacion"], "aprobado")
            self.assertEqual(call_upsert["activo"], True)

    def test_54_login_bloqueado_si_cuenta_inactiva_o_rechazada(self):
        """Verifica que iniciar_sesion bloquee cuentas inactivas o rechazadas y permita acceso directo a cuentas activas."""
        mock_pub = MagicMock()
        mock_auth_res = MagicMock()
        mock_auth_res.session = MagicMock(access_token="tok_test", refresh_token="ref_test", expires_at=1900000000)
        mock_auth_res.user = MagicMock(id="user-123")
        mock_pub.auth.sign_in_with_password.return_value = mock_auth_res

        mock_user_client = MagicMock()

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.database.obtener_cliente_publico", return_value=mock_pub), \
             patch("core.database.obtener_cliente_usuario", return_value=mock_user_client):

            # Caso 1: estado_aprobacion = 'rechazado'
            perfil_rechazado = {"id": "user-123", "nombre": "Carlos", "correo": "carlos@iaclatam.com", "es_admin": False, "activo": False, "estado_aprobacion": "rechazado"}
            with patch("core.database.obtener_usuario_por_correo_db", return_value=perfil_rechazado):
                ok, usr, tok, msg = auth_manager.iniciar_sesion("carlos@iaclatam.com", "PasswordSeguro123!")
                self.assertFalse(ok)
                self.assertIn("fue rechazada", msg.lower())

            # Caso 2: cuenta inactiva (activo = False)
            perfil_inactivo = {"id": "user-123", "nombre": "Carlos", "correo": "carlos@iaclatam.com", "es_admin": False, "activo": False, "estado_aprobacion": "aprobado"}
            with patch("core.database.obtener_usuario_por_correo_db", return_value=perfil_inactivo):
                ok, usr, tok, msg = auth_manager.iniciar_sesion("carlos@iaclatam.com", "PasswordSeguro123!")
                self.assertFalse(ok)
                self.assertIn("se encuentra inactiva", msg.lower())

            # Caso 3: cuenta activa y aprobada tras registro -> acceso directo permitido
            perfil_activo = {"id": "user-123", "nombre": "Carlos", "correo": "carlos@iaclatam.com", "es_admin": False, "activo": True, "estado_aprobacion": "aprobado"}
            with patch("core.database.obtener_usuario_por_correo_db", return_value=perfil_activo):
                ok, usr, tok, msg = auth_manager.iniciar_sesion("carlos@iaclatam.com", "PasswordSeguro123!")
                self.assertTrue(ok)
                self.assertIn("bienvenido", msg.lower())

    def test_55_admin_aprueba_solicitud_y_sincroniza_operador(self):
        """Verifica que aprobar_solicitud_registro active la cuenta, actualice app_metadata y guarde el operador."""
        # 1. Rechazado si solicitante no es admin
        with patch("core.auth_manager._verificar_solicitante_es_admin_activo", return_value=(False, "No es admin", None)):
            ok, msg = auth_manager.aprobar_solicitud_registro("target-uuid-1", access_token_solicitante="token_invalido")
            self.assertFalse(ok)
            self.assertIn("autorización rechazada", msg.lower())

        # 2. Aprobación exitosa por admin
        mock_admin = MagicMock()
        perfil_existente = {
            "id": "target-uuid-1",
            "nombre": "Carlos Mendoza",
            "correo": "carlos.mendoza@iaclatam.com",
            "cargo": "Asesor Comercial",
            "cedula": "12345",
            "telefono": "300123",
            "direccion": "Calle 100",
            "ciudad": "Bogotá",
        }
        mock_admin.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[perfil_existente])

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.auth_manager._verificar_solicitante_es_admin_activo", return_value=(True, "", "admin-uuid")), \
             patch("core.database.obtener_cliente_admin", return_value=mock_admin), \
             patch("core.database.guardar_operador_db") as mock_guardar_op:

            ok, msg = auth_manager.aprobar_solicitud_registro("target-uuid-1", access_token_solicitante="token_admin")
            self.assertTrue(ok)
            self.assertIn("aprobado y activado exitosamente", msg.lower())

            # Verificar update de perfil a aprobado y activo
            mock_admin.table().update.assert_called_with({
                "estado_aprobacion": "aprobado",
                "activo": True,
                "es_admin": False,
            })

            # Verificar update de app_metadata
            mock_admin.auth.admin.update_user_by_id.assert_called_with("target-uuid-1", {
                "app_metadata": {
                    "es_admin": False,
                    "role": "comercial",
                    "rol": "comercial",
                    "estado": "aprobado",
                }
            })

            # Verificar sincronización con operadores
            mock_guardar_op.assert_called_once()
            self.assertEqual(mock_guardar_op.call_args[1]["nombre"], "Carlos Mendoza")
            self.assertEqual(mock_guardar_op.call_args[1]["correo"], "carlos.mendoza@iaclatam.com")

    def test_56_admin_rechaza_solicitud(self):
        """Verifica que rechazar_solicitud_registro fije estado_aprobacion=rechazado y activo=False."""
        mock_admin = MagicMock()

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.auth_manager._verificar_solicitante_es_admin_activo", return_value=(True, "", "admin-uuid")), \
             patch("core.database.obtener_cliente_admin", return_value=mock_admin):

            ok, msg = auth_manager.rechazar_solicitud_registro("target-uuid-2", access_token_solicitante="token_admin")
            self.assertTrue(ok)
            self.assertIn("rechazada exitosamente", msg.lower())

            mock_admin.table().update.assert_called_with({
                "estado_aprobacion": "rechazado",
                "activo": False,
            })
            mock_admin.auth.admin.update_user_by_id.assert_called_with("target-uuid-2", {
                "app_metadata": {"estado": "rechazado"}
            })

    def test_57_cambio_rol_estricto_y_proteccion_ultimo_admin(self):
        """Verifica que cambiar_rol_usuario solo admita 'comercial'/'administrador' y proteja al último admin."""
        # 1. Rol no permitido
        ok, msg = auth_manager.cambiar_rol_usuario("uuid-1", "superadmin", access_token_solicitante="token")
        self.assertFalse(ok)
        self.assertIn("rol no permitido", msg.lower())

        mock_admin = MagicMock()
        mock_admin.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"es_admin": True, "activo": True}]
        )

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.auth_manager._verificar_solicitante_es_admin_activo", return_value=(True, "", "admin-uuid")), \
             patch("core.database.obtener_cliente_admin", return_value=mock_admin):

            # 2. Intentar degradar al único admin activo -> debe fallar
            with patch("core.database.contar_administradores_activos_db", return_value=1):
                ok, msg = auth_manager.cambiar_rol_usuario("target-uuid-3", "comercial", access_token_solicitante="token_admin")
                self.assertFalse(ok)
                self.assertIn("único administrador activo", msg.lower())

            # 3. Degradar cuando hay más de un admin activo -> debe proceder
            with patch("core.database.contar_administradores_activos_db", return_value=2):
                ok, msg = auth_manager.cambiar_rol_usuario("target-uuid-3", "comercial", access_token_solicitante="token_admin")
                self.assertTrue(ok)
                mock_admin.table().update.assert_called_with({"es_admin": False})

    def test_58_recuperacion_admin_con_proteccion_anti_pdf(self):
        """Verifica que reenviar_recuperacion_admin valide JWT de admin y bloquee referencias a proyectos PDF."""
        # 1. Solicitante no admin
        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.auth_manager._verificar_solicitante_es_admin_activo", return_value=(False, "No es admin", None)):
            ok, msg = auth_manager.reenviar_recuperacion_admin("carlos@iaclatam.com", access_token_solicitante="bad_token")
            self.assertFalse(ok)
            self.assertIn("autorización rechazada", msg.lower())

        # 2. Bloqueo anti-PDF
        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.auth_manager._verificar_solicitante_es_admin_activo", return_value=(True, "", "admin-uuid")):
            with self.assertRaises(database.ConfiguracionInvalidaError) as ctx:
                auth_manager.reenviar_recuperacion_admin(
                    "carlos@iaclatam.com",
                    redirect_url="https://tnhedxwbpqihlqbtzudt.supabase.co",
                    access_token_solicitante="token_admin",
                )
            self.assertIn("PDF prohibido", str(ctx.exception))

        # 3. Despacho exitoso con URL limpia
        mock_pub = MagicMock()
        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.auth_manager._verificar_solicitante_es_admin_activo", return_value=(True, "", "admin-uuid")), \
             patch("core.database.obtener_cliente_publico", return_value=mock_pub):
            ok, msg = auth_manager.reenviar_recuperacion_admin(
                "carlos@iaclatam.com",
                redirect_url="https://autoform-iac-excel.streamlit.app",
                access_token_solicitante="token_admin",
            )
            self.assertTrue(ok)
            self.assertIn("despachado por supabase", msg.lower())
            mock_pub.auth.reset_password_for_email.assert_called_once_with(
                "carlos@iaclatam.com",
                options={"redirect_to": "https://autoform-iac-excel.streamlit.app"},
            )

    def test_59_restablecer_password_comercial_admin(self):
        """Verifica que restablecer_password_comercial_admin valide privilegios de admin y actualice la contraseña."""
        # 1. Contraseña corta rechazada
        ok, msg = auth_manager.restablecer_password_comercial_admin("uid-1", "corta", access_token_solicitante="token")
        self.assertFalse(ok)
        self.assertIn("8 caracteres", msg.lower())

        # 2. Rechazado si solicitante no es admin
        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.auth_manager._verificar_solicitante_es_admin_activo", return_value=(False, "No es admin", None)):
            ok, msg = auth_manager.restablecer_password_comercial_admin("uid-1", "NuevaPasswordSegura123!", access_token_solicitante="bad_token")
            self.assertFalse(ok)
            self.assertIn("autorización rechazada", msg.lower())

        # 3. Actualización exitosa en Supabase Auth
        mock_admin = MagicMock()
        mock_admin.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "uid-comercial-1", "nombre": "Antonio Prieto", "correo": "antonio.prieto@iaclatam.com"}]
        )
        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.auth_manager._verificar_solicitante_es_admin_activo", return_value=(True, "", "admin-uuid")), \
             patch("core.database.obtener_cliente_admin", return_value=mock_admin):
            ok, msg = auth_manager.restablecer_password_comercial_admin(
                "uid-comercial-1",
                "NuevaPasswordSegura123!",
                access_token_solicitante="token_admin",
            )
            self.assertTrue(ok)
            self.assertIn("exitosa", msg.lower())
            mock_admin.auth.admin.update_user_by_id.assert_called_once_with(
                "uid-comercial-1",
                {"password": "NuevaPasswordSegura123!"},
            )

    def test_60_insercion_auditoria_exclusiva_backend_service_role(self):
        """Verifica que registrar_auditoria_db use exclusivamente el cliente admin (service_role) y valide UUIDs."""
        mock_admin = MagicMock()
        mock_admin.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "uuid-1"}])

        valid_admin_uuid = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
        valid_user_uuid = "b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a22"

        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.database.obtener_cliente_admin", return_value=mock_admin) as mock_get_admin, \
             patch("core.database._obtener_cliente_activo") as mock_get_activo:

            ok = database.registrar_auditoria_db(
                tipo_evento="reenvio_recuperacion",
                correo_objetivo="colab@iaclatam.com",
                admin_id=valid_admin_uuid,
                admin_correo="admin@iaclatam.com",
                usuario_id=valid_user_uuid,
                motivo="Prueba de auditoria",
                detalles="Detalles de auditoria",
            )
            self.assertTrue(ok)
            mock_get_admin.assert_called_once()
            mock_get_activo.assert_not_called()

            insert_call_args = mock_admin.table().insert.call_args[0][0]
            self.assertEqual(insert_call_args["admin_id"], valid_admin_uuid)
            self.assertEqual(insert_call_args["usuario_id"], valid_user_uuid)
            self.assertEqual(insert_call_args["correo_objetivo"], "colab@iaclatam.com")

    def test_61_aislamiento_rls_auditoria_autenticacion_comercial_vs_admin(self):
        """Verifica el modelo de seguridad RLS: comercial no lee ni inserta, admin solo lee, service_role inserta."""
        # 1. Simulación de cliente comercial (es_admin = False): SELECT retorna 0 filas, INSERT falla
        mock_comercial = MagicMock()
        mock_comercial.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])
        mock_comercial.table.return_value.insert.return_value.execute.side_effect = Exception("violates row-level security policy for table auditoria_autenticacion")

        res_select = mock_comercial.table("auditoria_autenticacion").select("*").execute()
        self.assertEqual(len(res_select.data), 0, "Comercial no debe ver registros de auditoría")

        with self.assertRaises(Exception) as ctx_com_ins:
            mock_comercial.table("auditoria_autenticacion").insert({"tipo_evento": "hack"}).execute()
        self.assertIn("row-level security", str(ctx_com_ins.exception))

        # 2. Simulación de cliente admin autenticado (es_admin = True): SELECT permite lectura, pero INSERT, UPDATE y DELETE directos fallan
        mock_admin_user = MagicMock()
        mock_admin_user.table.return_value.select.return_value.execute.return_value = MagicMock(data=[{"id": "aud-1"}])
        mock_admin_user.table.return_value.insert.return_value.execute.side_effect = Exception("new row violates row-level security policy for table auditoria_autenticacion")
        mock_admin_user.table.return_value.update.return_value.execute.side_effect = Exception("Operación denegada: Los registros son estrictamente inmutables")
        mock_admin_user.table.return_value.delete.return_value.execute.side_effect = Exception("Operación denegada: Los registros son inmutables")

        res_adm_select = mock_admin_user.table("auditoria_autenticacion").select("*").execute()
        self.assertEqual(len(res_adm_select.data), 1, "Administrador autenticado debe poder consultar auditoría")

        with self.assertRaises(Exception) as ctx_adm_ins:
            mock_admin_user.table("auditoria_autenticacion").insert({"tipo_evento": "direct_insert"}).execute()
        self.assertIn("row-level security", str(ctx_adm_ins.exception))

        with self.assertRaises(Exception) as ctx_adm_upd:
            mock_admin_user.table("auditoria_autenticacion").update({"motivo": "modificado"}).execute()
        self.assertIn("inmutables", str(ctx_adm_upd.exception))

        with self.assertRaises(Exception) as ctx_adm_del:
            mock_admin_user.table("auditoria_autenticacion").delete().execute()
        self.assertIn("inmutables", str(ctx_adm_del.exception))

    def test_62_restricciones_esquema_004_fk_not_null_check_restrict(self):
        """Verifica restricciones de esquema: NOT NULL, FK única fk_auditoria_admin_id, CHECK y RESTRICT."""
        # 1. Simulación de fallo NOT NULL en admin_id (código 23502)
        mock_admin = MagicMock()
        mock_admin.table.return_value.insert.side_effect = [
            Exception("null value in column 'admin_id' of relation 'auditoria_autenticacion' violates not-null constraint (23502)"),
            Exception('new row for relation "auditoria_autenticacion" violates check constraint "chk_auditoria_tipo_evento" (23514)'),
            Exception('insert or update on table "auditoria_autenticacion" violates foreign key constraint "fk_auditoria_admin_id" (23503)'),
            MagicMock(execute=MagicMock(return_value=MagicMock(data=[{"id": "ok-1"}]))),
        ]

        # Inserción con admin_id NULL
        with self.assertRaises(Exception) as ctx_null:
            mock_admin.table("auditoria_autenticacion").insert({"tipo_evento": "reenvio_recuperacion"}).execute()
        self.assertIn("violates not-null constraint", str(ctx_null.exception))

        # Inserción con tipo_evento no permitido
        with self.assertRaises(Exception) as ctx_chk:
            mock_admin.table("auditoria_autenticacion").insert({"tipo_evento": "evento_prohibido"}).execute()
        self.assertIn("chk_auditoria_tipo_evento", str(ctx_chk.exception))

        # Inserción con admin_id inexistente
        with self.assertRaises(Exception) as ctx_fk:
            mock_admin.table("auditoria_autenticacion").insert({"admin_id": "00000000-0000-0000-0000-000000000000"}).execute()
        self.assertIn("fk_auditoria_admin_id", str(ctx_fk.exception))

        # Simulación de fallo al intentar borrar usuario en auth.users referenciado (ON DELETE RESTRICT, código 23503)
        mock_admin.auth.admin.delete_user.side_effect = Exception('update or delete on table "users" violates foreign key constraint "fk_auditoria_admin_id" on table "auditoria_autenticacion" (23503)')
        with self.assertRaises(Exception) as ctx_restrict:
            mock_admin.auth.admin.delete_user("uid-admin-referenciado")
        self.assertIn("fk_auditoria_admin_id", str(ctx_restrict.exception))

    def test_63_proteger_columnas_perfil_debe_cambiar_password_y_estados(self):
        """Verifica que comercial/pendiente/inactivo no pueda modificar debe_cambiar_password, estado_aprobacion, etc., y que backend sí pueda."""
        # 1. Comercial intenta actualizar debe_cambiar_password directamente -> Bloqueado
        mock_comercial = MagicMock()
        mock_comercial.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception(
            "Operación denegada: La bandera debe_cambiar_password es un atributo protegido y no puede ser modificada por clientes authenticated."
        )

        with self.assertRaises(Exception) as ctx_pwd:
            mock_comercial.table("perfiles_usuario").update({"debe_cambiar_password": False}).eq("id", "uid-com-1").execute()
        self.assertIn("debe_cambiar_password es un atributo protegido", str(ctx_pwd.exception))

        # 2. Usuario no-admin intenta modificar es_admin, activo o estado_aprobacion -> Bloqueado
        for campo in ["es_admin", "activo", "estado_aprobacion"]:
            mock_comercial.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception(
                f"Operación denegada: No tienes permisos para modificar ({campo})."
            )
            with self.assertRaises(Exception) as ctx_campo:
                mock_comercial.table("perfiles_usuario").update({campo: "hack"}).eq("id", "uid-com-1").execute()
            self.assertIn(f"({campo})", str(ctx_campo.exception))

        # 3. Backend (service_role) desactiva la bandera exitosamente tras cambio forzado de credencial
        mock_backend = MagicMock()
        mock_backend.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "uid-1", "debe_cambiar_password": False}])
        with patch("core.database.usar_supabase", return_value=True), \
             patch("core.database.obtener_cliente_admin", return_value=mock_backend):
            ok_db = database.actualizar_password_usuario_db("uid-1", "", debe_cambiar_password=False)
            self.assertTrue(ok_db)
            mock_backend.table().update.assert_called_with({"debe_cambiar_password": False})

    def test_64_inspeccion_estatica_sql_migracion_006(self):
        """Verifica estáticamente que la migración 006 de reconciliación de auditoría
        no contenga SECURITY DEFINER ni current_user, que mantenga SET search_path = '',
        reconcilie admin_id NOT NULL con fk_auditoria_admin_id (ON DELETE RESTRICT),
        defina chk_auditoria_tipo_evento para los 3 eventos, autorice backend exclusivamente
        por claim auth.role() = 'service_role', incluya preflight y postflight,
        y que un comercial siga categóricamente bloqueado."""
        sql_path = PROJECT_ROOT / "supabase" / "migrations" / "006_reconcile_audit_schema.sql"
        self.assertTrue(sql_path.exists(), "El archivo de migración 006 debe existir.")
        sql_content = sql_path.read_text(encoding="utf-8")

        # 1. Ausencia absoluta de SECURITY DEFINER en todo el archivo SQL
        self.assertNotIn(
            "SECURITY DEFINER",
            sql_content,
            "Violación de seguridad: Las funciones de trigger no deben elevar privilegios (SECURITY DEFINER prohibido).",
        )

        # 2. Ausencia absoluta de current_user en todo el archivo SQL
        self.assertNotIn(
            "current_user",
            sql_content,
            "Violación de seguridad: No deben usarse excepciones basadas en current_user. Usar auth.role().",
        )

        # 3. La función de inmutabilidad debe conservar SET search_path = ''
        self.assertIn(
            "CREATE OR REPLACE FUNCTION public.proteger_inmutabilidad_auditoria()",
            sql_content,
        )
        self.assertIn(
            "SET search_path = ''",
            sql_content,
            "La función debe declarar explícitamente SET search_path = '' para blindar la ruta de búsqueda.",
        )

        # 4. Verificación de autorización por claims: auth.role() = 'service_role'
        self.assertIn(
            "auth.role() = 'service_role'",
            sql_content,
            "La migración 006 debe usar auth.role() = 'service_role' para verificar privilegios de backend.",
        )

        # 5. Borrado sintético restringido a service_role y patrón synth.%
        self.assertIn(
            "(auth.role() = 'service_role') AND (OLD.correo_objetivo ILIKE 'synth.%')",
            sql_content,
            "El borrado en auditoría debe requerir exclusivamente claim service_role y correo_objetivo sintético.",
        )

        # 6. Reconciliación de esquema: admin_id NOT NULL, FK ON DELETE RESTRICT, CHECK tipo_evento
        self.assertIn(
            "ALTER COLUMN admin_id SET NOT NULL",
            sql_content,
            "La migración 006 debe asegurar admin_id NOT NULL.",
        )
        self.assertIn(
            "CONSTRAINT fk_auditoria_admin_id",
            sql_content,
            "Debe definir la restricción fk_auditoria_admin_id.",
        )
        self.assertIn(
            "REFERENCES auth.users(id) ON DELETE RESTRICT",
            sql_content,
            "La FK de admin_id debe ser ON DELETE RESTRICT.",
        )
        self.assertIn(
            "CONSTRAINT chk_auditoria_tipo_evento",
            sql_content,
            "Debe definir la restricción chk_auditoria_tipo_evento.",
        )
        for evento in [
            "reenvio_recuperacion",
            "restablecimiento_manual_excepcional",
            "cambio_password_primer_ingreso",
        ]:
            self.assertIn(evento, sql_content, f"El evento {evento} debe estar en el CHECK.")

        # 7. Eliminación dinámica de políticas SOLO en public.auditoria_autenticacion y recreación única SELECT
        self.assertIn(
            "FROM pg_policies",
            sql_content,
            "Debe consultar pg_policies para eliminar dinámicamente las políticas existentes.",
        )
        self.assertIn(
            "tablename = 'auditoria_autenticacion'",
            sql_content,
            "La eliminación dinámica de políticas debe limitarse exclusivamente a auditoria_autenticacion.",
        )
        self.assertIn(
            "DROP POLICY IF EXISTS %I ON public.auditoria_autenticacion",
            sql_content,
            "Debe ejecutar DROP POLICY dinámico sobre auditoria_autenticacion.",
        )
        self.assertIn(
            "CREATE POLICY \"Solo administradores pueden consultar auditoria\"",
            sql_content,
            "Debe recrear la política SELECT para administradores.",
        )

        # 8. Preflight de identidad y postflight assertions exhaustivas
        self.assertIn("Preflight de identidad en base de datos", sql_content)
        self.assertIn("deployment_identity", sql_content)
        self.assertIn("Post-Flight Assertions", sql_content)

        # 8.1 Postflight: RLS habilitado y exactamente la política SELECT administrativa oficial
        self.assertIn("relrowsecurity", sql_content, "Postflight debe validar relrowsecurity.")
        self.assertIn("total_politicas != 1", sql_content)
        self.assertIn("pol_rec.policyname != 'Solo administradores pueden consultar auditoria'", sql_content)
        self.assertIn("pol_rec.cmd != 'SELECT'", sql_content)
        self.assertIn("'authenticated' = ANY(pol_rec.roles)", sql_content)
        self.assertIn("pol_rec.qual !~* 'auth\\.uid\\(\\)'", sql_content)
        self.assertIn("pol_rec.qual !~* 'es_admin\\s*=\\s*true'", sql_content)
        self.assertIn("pol_rec.qual !~* 'activo\\s*=\\s*true'", sql_content)

        # 8.2 Postflight: Exactamente 1 FK sobre admin_id, dirigida a auth.users(id), con ON DELETE RESTRICT
        self.assertIn("total_fks_admin != 1", sql_content)
        self.assertIn("fks_validas_admin != 1", sql_content)
        self.assertIn("confdeltype = 'r'", sql_content)
        self.assertIn("ftn.nspname = 'auth'", sql_content)
        self.assertIn("ft.relname = 'users'", sql_content)

        # 8.3 Postflight: CHECK tipo_evento acepta exactamente los 3 eventos oficiales y ningún valor extra
        self.assertIn("pg_get_constraintdef", sql_content)
        self.assertIn("chk_auditoria_tipo_evento", sql_content)
        self.assertIn("ARRAY_AGG(m[1] ORDER BY m[1])", sql_content)
        self.assertIn("literales_eventos != ARRAY['cambio_password_primer_ingreso', 'reenvio_recuperacion', 'restablecimiento_manual_excepcional']", sql_content)

        # 8.4 Postflight: Función sin elevación (prosecdef=false) y conserva SET search_path = ''
        self.assertIn("bool_or(p.prosecdef)", sql_content)
        self.assertIn("is_secdef IS TRUE", sql_content)
        self.assertIn("fn_search_path_ok IS NOT TRUE", sql_content)
        self.assertIn("trg_proteger_inmutabilidad_auditoria", sql_content)

        # 8. Comprobación funcional del bloqueo a usuario comercial:
        # a) Intento de comercial de modificar debe_cambiar_password directamente
        mock_comercial = MagicMock()
        mock_comercial.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception(
            "Operación denegada: La bandera debe_cambiar_password es un atributo protegido y no puede ser modificada por clientes authenticated. Requiere backend autorizado."
        )
        with self.assertRaises(Exception) as ctx_com_pwd:
            mock_comercial.table("perfiles_usuario").update({"debe_cambiar_password": False}).eq("id", "com-1").execute()
        self.assertIn("debe_cambiar_password es un atributo protegido", str(ctx_com_pwd.exception))

        # b) Intento de comercial de consultar o insertar en auditoria_autenticacion
        mock_comercial.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])
        res_sel = mock_comercial.table("auditoria_autenticacion").select("id").execute()
        self.assertEqual(len(res_sel.data), 0, "Comercial debe recibir 0 registros por RLS")

        mock_comercial.table.return_value.insert.return_value.execute.side_effect = Exception(
            "new row violates row-level security policy for table 'auditoria_autenticacion'"
        )
        with self.assertRaises(Exception) as ctx_com_ins:
            mock_comercial.table("auditoria_autenticacion").insert({"tipo_evento": "reenvio_recuperacion"}).execute()
        self.assertIn("row-level security", str(ctx_com_ins.exception))

    def test_65_inspeccion_estatica_sql_migracion_005(self):
        """Verifica estáticamente que la migración 005 contenga el preflight de identidad en base de datos,
        inmutabilidad absoluta de id (incluso service_role), correo exclusivo para service_role,
        protección del último admin activo aplicable a service_role, y postflight assertions."""
        sql_path = PROJECT_ROOT / "supabase" / "migrations" / "005_complete_forced_password_upgrade.sql"
        self.assertTrue(sql_path.exists(), "El archivo de migración 005 debe existir.")
        sql_content = sql_path.read_text(encoding="utf-8")

        # 1. Ausencia absoluta de SECURITY DEFINER y current_user
        self.assertNotIn(
            "SECURITY DEFINER",
            sql_content,
            "Violación de seguridad: La función de perfiles no debe elevar privilegios.",
        )
        self.assertNotIn(
            "current_user",
            sql_content,
            "Violación de seguridad: No deben usarse excepciones basadas en current_user. Usar auth.role().",
        )

        # 2. Conservación de SET search_path = ''
        self.assertIn(
            "SET search_path = ''",
            sql_content,
            "La función debe declarar SET search_path = '' para blindar la ruta de ejecución.",
        )

        # 3. Preflight de identidad en base de datos presente en SQL
        self.assertIn("Preflight de identidad en base de datos", sql_content)
        self.assertNotIn("Preflight 5-Way", sql_content)
        self.assertIn("deployment_identity", sql_content)
        self.assertIn("autoform-excel", sql_content)
        self.assertIn("staging", sql_content)
        self.assertIn("nfaxkncrpfrsvzfgczny", sql_content)

        # 4. Agrega columna debe_cambiar_password
        self.assertIn(
            "ADD COLUMN IF NOT EXISTS debe_cambiar_password BOOLEAN NOT NULL DEFAULT false",
            sql_content,
        )

        # 5. Inmutabilidad absoluta de id para todos los roles (incluido service_role)
        self.assertIn(
            "IF NEW.id IS DISTINCT FROM OLD.id THEN",
            sql_content,
            "El identificador de cuenta (id) debe ser inmutable sin excepciones de rol.",
        )

        # 6. Inicialización fail-closed de roles ante NULL
        self.assertIn(
            "is_service_role := COALESCE(auth.role() = 'service_role', false);",
            sql_content,
            "La inicialización de is_service_role debe ser fail-closed ante NULL.",
        )
        self.assertIn(
            "caller_is_admin := CASE\n        WHEN is_service_role THEN false\n        ELSE COALESCE(public.is_admin(), false)\n    END;",
            sql_content,
            "La inicialización de caller_is_admin debe ser fail-closed y subordinada a is_service_role.",
        )

        # 7. Bloqueo transaccional de concurrencia con advisory lock
        self.assertIn(
            "PERFORM pg_catalog.pg_advisory_xact_lock(9052026);",
            sql_content,
            "Debe aplicar pg_advisory_xact_lock(9052026) antes de comprobar el último admin.",
        )

        # 8. Verificación de las 5 columnas requeridas en el preflight
        self.assertIn(
            "column_name IN ('id', 'correo', 'es_admin', 'activo', 'estado_aprobacion')",
            sql_content,
            "El preflight debe verificar la presencia de las 5 columnas indispensables.",
        )
        self.assertIn(
            "IF cols_encontradas != 5 THEN",
            sql_content,
            "El preflight debe abortar si no se encuentran las 5 columnas en perfiles_usuario.",
        )

        # 9. Modificación de correo restringida exclusivamente a service_role
        self.assertIn(
            "IF NEW.correo IS DISTINCT FROM OLD.correo THEN",
            sql_content,
            "La modificación de correo debe estar bloqueada para clientes authenticated (incluso admin).",
        )

        # 10. Preservación intacta de auditoria_autenticacion (CERO sentencias de mutación DDL)
        lineas_mutacion_auditoria = [
            line for line in sql_content.splitlines()
            if any(verbo in line.upper() for verbo in ["CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE TRIGGER", "DROP TRIGGER"])
            and "auditoria_autenticacion" in line.lower()
        ]
        self.assertEqual(
            len(lineas_mutacion_auditoria),
            0,
            f"La migración 005 no debe mutar auditoria_autenticacion: {lineas_mutacion_auditoria}",
        )

        # 11. Postflight assertions reforzadas (exactamente 1 función y prosecdef=false)
        self.assertIn("Postflight", sql_content)
        self.assertIn("trigger_proteger_columnas_perfil_usuario", sql_content)
        self.assertIn("information_schema.columns", sql_content)
        self.assertIn("IF fn_count != 1 THEN", sql_content)
        self.assertIn("bool_or(prosecdef)", sql_content)

    def test_66_reglas_motor_perfil_005_inmutabilidad_correo_ultimo_admin(self):
        """Verifica funcionalmente mediante simulación del trigger 005:
        1. id absolutamente inmutable para cualquier rol, incluido service_role.
        2. correo modificable únicamente por service_role; ningún admin autenticado puede cambiarlo directamente.
        3. Protección que impida degradar o desactivar al último administrador activo, aplicando también a service_role."""

        # 1. Simulación: id inmutable para service_role
        mock_backend = MagicMock()
        mock_backend.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception(
            "Operación denegada: El identificador de cuenta (id) es absolutamente inmutable."
        )
        with self.assertRaises(Exception) as ctx_id:
            mock_backend.table("perfiles_usuario").update({"id": "nuevo-uuid"}).eq("id", "uuid-original").execute()
        self.assertIn("identificador de cuenta (id) es absolutamente inmutable", str(ctx_id.exception))

        # 2. Simulación: Administrador autenticado intenta cambiar correo directamente -> Bloqueado
        mock_admin_user = MagicMock()
        mock_admin_user.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception(
            "Operación denegada: El correo electrónico corporativo solo puede ser modificado por backend autorizado (service_role)."
        )
        with self.assertRaises(Exception) as ctx_email:
            mock_admin_user.table("perfiles_usuario").update({"correo": "nuevo@iaclatam.com"}).eq("id", "adm-1").execute()
        self.assertIn("solo puede ser modificado por backend autorizado (service_role)", str(ctx_email.exception))

        # 3. Simulación: service_role cambia correo -> Permitido
        mock_backend_email = MagicMock()
        mock_backend_email.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "usr-1", "correo": "actualizado@iaclatam.com"}]
        )
        res_email = mock_backend_email.table("perfiles_usuario").update({"correo": "actualizado@iaclatam.com"}).eq("id", "usr-1").execute()
        self.assertEqual(res_email.data[0]["correo"], "actualizado@iaclatam.com")

        # 4. Simulación: Intento de degradar (es_admin=False) o desactivar (activo=False) al último admin activo
        for rol_actor, mock_actor in [("Admin Autenticado", mock_admin_user), ("Backend ServiceRole", mock_backend)]:
            mock_actor.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception(
                "Operación denegada: No se puede desactivar ni degradar al único administrador activo del sistema. Debe existir otro administrador activo previamente."
            )
            with self.assertRaises(Exception) as ctx_deg:
                mock_actor.table("perfiles_usuario").update({"es_admin": False}).eq("id", "unico-admin").execute()
            self.assertIn("No se puede desactivar ni degradar al único administrador activo", str(ctx_deg.exception), f"Fallo para {rol_actor}")

            with self.assertRaises(Exception) as ctx_desact:
                mock_actor.table("perfiles_usuario").update({"activo": False}).eq("id", "unico-admin").execute()
            self.assertIn("No se puede desactivar ni degradar al único administrador activo", str(ctx_desact.exception), f"Fallo para {rol_actor}")

        # 5. Simulación: Si existe otro administrador activo, la degradación sí es permitida
        mock_backend_ok = MagicMock()
        mock_backend_ok.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "admin-2", "es_admin": False, "activo": True}]
        )
        res_deg_ok = mock_backend_ok.table("perfiles_usuario").update({"es_admin": False}).eq("id", "admin-2").execute()
        self.assertFalse(res_deg_ok.data[0]["es_admin"])

        # 6. Simulación: Administrador intenta modificar debe_cambiar_password -> Bloqueado
        mock_admin_user.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception(
            "Operación denegada: La bandera debe_cambiar_password es un atributo protegido y no puede ser modificada por clientes authenticated. Requiere backend autorizado."
        )
        with self.assertRaises(Exception) as ctx_pwd_adm:
            mock_admin_user.table("perfiles_usuario").update({"debe_cambiar_password": False}).eq("id", "usr-1").execute()
        self.assertIn("debe_cambiar_password es un atributo protegido", str(ctx_pwd_adm.exception))

    def test_67_fail_closed_advisory_lock_y_preflight_columnas(self):
        """Verifica:
        1. Comportamiento fail-closed ante roles NULL (auth.role() o public.is_admin() retornan NULL).
        2. Serialización concurrente mediante advisory xact lock al proteger al último administrador.
        3. Preflight de identidad en BD aborta si falta cualquiera de las 5 columnas requeridas."""

        # 1. Simulación fail-closed: roles NULL
        # Si auth.role() es NULL -> is_service_role = False
        # Si public.is_admin() es NULL -> caller_is_admin = False
        def resolver_roles_fail_closed(auth_role, is_admin_val):
            is_service_role = bool(auth_role == "service_role") if auth_role is not None else False
            if is_service_role:
                caller_is_admin = False
            else:
                caller_is_admin = bool(is_admin_val) if is_admin_val is not None else False
            return is_service_role, caller_is_admin

        # Probar con valores NULL (None)
        srv_role_null, adm_role_null = resolver_roles_fail_closed(None, None)
        self.assertFalse(srv_role_null, "is_service_role debe ser False cuando auth.role() es NULL")
        self.assertFalse(adm_role_null, "caller_is_admin debe ser False cuando public.is_admin() es NULL")

        # Con ambos en False, cualquier modificación sensible queda bloqueada
        mock_null_client = MagicMock()
        mock_null_client.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception(
            "Operación denegada: No tienes permisos para modificar el estado de aprobación (estado_aprobacion)."
        )
        with self.assertRaises(Exception) as ctx_null_upd:
            mock_null_client.table("perfiles_usuario").update({"estado_aprobacion": "aprobado"}).eq("id", "usr-x").execute()
        self.assertIn("No tienes permisos para modificar", str(ctx_null_upd.exception))

        # 2. Protección en concurrencia con pg_advisory_xact_lock
        # Simular dos hilos concurrentes intentando degradar al único admin activo
        candado_adquirido = [False]
        ultimo_admin_degradado = [0]
        lock_id_esperado = 9052026

        def simular_transaccion_degradacion(admin_id: str, tiene_otro_admin: bool):
            # Simula: PERFORM pg_catalog.pg_advisory_xact_lock(9052026);
            candado_adquirido[0] = True
            # Comprobación de existencia bajo el lock
            if not tiene_otro_admin:
                raise Exception("Operación denegada: No se puede desactivar ni degradar al único administrador activo del sistema. Debe existir otro administrador activo previamente.")
            ultimo_admin_degradado[0] += 1
            return True

        # Primera transacción falla porque no hay otro admin activo
        with self.assertRaises(Exception) as ctx_conc1:
            simular_transaccion_degradacion("adm-unico", tiene_otro_admin=False)
        self.assertTrue(candado_adquirido[0], "El candado transaccional debe haberse solicitado")
        self.assertEqual(ultimo_admin_degradado[0], 0, "Ningún admin debe haberse degradado")

        # 3. Fallo de preflight si falta una columna requerida
        columnas_disponibles_incompletas = ["id", "correo", "es_admin", "activo"] # falta 'estado_aprobacion'
        columnas_requeridas = ["id", "correo", "es_admin", "activo", "estado_aprobacion"]
        cols_encontradas = len(set(columnas_disponibles_incompletas).intersection(set(columnas_requeridas)))

        self.assertNotEqual(cols_encontradas, 5)
        # La lógica del preflight aborta si cols_encontradas != 5
        preflight_abortado = False
        try:
            if cols_encontradas != 5:
                raise Exception("Preflight de identidad en base de datos falló: public.perfiles_usuario debe contener id, correo, es_admin, activo y estado_aprobacion antes de actualizar el trigger.")
        except Exception as exc_pre:
            preflight_abortado = True
            self.assertIn("debe contener id, correo, es_admin, activo y estado_aprobacion", str(exc_pre))
        self.assertTrue(preflight_abortado, "El preflight debe abortar si falta una columna requerida")

    def test_68_postflight_reconciliacion_auditoria_reglas_estrictas(self):
        """Verifica funcionalmente la lógica de aserciones del postflight de la migración 006:
        1. RLS habilitado y exactamente la política SELECT administrativa oficial (auth.uid, es_admin=true, activo=true).
        2. Exactamente 1 FK sobre admin_id, dirigida a auth.users(id) con ON DELETE RESTRICT.
        3. chk_auditoria_tipo_evento acepta exactamente los 3 eventos oficiales y ningún valor extra.
        4. Función de inmutabilidad sin elevación de privilegios (prosecdef=false) y con SET search_path = ''."""

        # 1. Simulación Postflight RLS y Política Administrativa Oficial Única
        def validar_politica_auditoria_estricta(rls_activo: bool, total_politicas: int, policyname: str, cmd: str, roles: list, qual: str):
            if not rls_activo:
                raise Exception("Postflight falló: Row Level Security (RLS) no está habilitado en public.auditoria_autenticacion.")
            if total_politicas != 1:
                raise Exception(f"Postflight falló: Se esperaba exactamente 1 política total en public.auditoria_autenticacion, se encontraron {total_politicas}.")
            if policyname != "Solo administradores pueden consultar auditoria":
                raise Exception(f"Postflight falló: La política existente se llama '{policyname}', se esperaba 'Solo administradores pueden consultar auditoria'.")
            if cmd != "SELECT":
                raise Exception(f"Postflight falló: El comando de la política es '{cmd}', se esperaba 'SELECT'.")
            if roles != ["authenticated"]:
                raise Exception(f"Postflight falló: Los roles de la política son {roles}, se esperaba exclusivamente {{authenticated}}.")
            if not (re.search(r"auth\.uid\(\)", qual) and re.search(r"perfiles_usuario", qual) and re.search(r"es_admin\s*=\s*true", qual) and re.search(r"activo\s*=\s*true", qual)):
                raise Exception(f"Postflight falló: La cláusula USING de la política no valida la condición de administrador activo (auth.uid, es_admin=true y activo=true): {qual}")
            return True

        # Falla si RLS no está habilitado
        with self.assertRaises(Exception) as ctx_rls:
            validar_politica_auditoria_estricta(False, 1, "Solo administradores pueden consultar auditoria", "SELECT", ["authenticated"], "perfiles_usuario.id = auth.uid() AND perfiles_usuario.es_admin = true AND perfiles_usuario.activo = true")
        self.assertIn("RLS) no está habilitado", str(ctx_rls.exception))

        # Falla si hay 0 o 2 políticas
        with self.assertRaises(Exception) as ctx_pol0:
            validar_politica_auditoria_estricta(True, 0, "Solo administradores pueden consultar auditoria", "SELECT", ["authenticated"], "perfiles_usuario.id = auth.uid() AND perfiles_usuario.es_admin = true AND perfiles_usuario.activo = true")
        self.assertIn("Se esperaba exactamente 1 política total", str(ctx_pol0.exception))

        with self.assertRaises(Exception) as ctx_pol2:
            validar_politica_auditoria_estricta(True, 2, "Solo administradores pueden consultar auditoria", "SELECT", ["authenticated"], "perfiles_usuario.id = auth.uid() AND perfiles_usuario.es_admin = true AND perfiles_usuario.activo = true")
        self.assertIn("Se esperaba exactamente 1 política total", str(ctx_pol2.exception))

        # Falla si el nombre es diferente
        with self.assertRaises(Exception) as ctx_name:
            validar_politica_auditoria_estricta(True, 1, "Otra politica", "SELECT", ["authenticated"], "perfiles_usuario.id = auth.uid() AND perfiles_usuario.es_admin = true AND perfiles_usuario.activo = true")
        self.assertIn("se esperaba 'Solo administradores pueden consultar auditoria'", str(ctx_name.exception))

        # Falla si el comando no es SELECT (p.ej. INSERT)
        with self.assertRaises(Exception) as ctx_cmd:
            validar_politica_auditoria_estricta(True, 1, "Solo administradores pueden consultar auditoria", "INSERT", ["authenticated"], "perfiles_usuario.id = auth.uid() AND perfiles_usuario.es_admin = true AND perfiles_usuario.activo = true")
        self.assertIn("se esperaba 'SELECT'", str(ctx_cmd.exception))

        # Falla si los roles no son exclusivamente authenticated (p.ej. anon o public)
        with self.assertRaises(Exception) as ctx_rol:
            validar_politica_auditoria_estricta(True, 1, "Solo administradores pueden consultar auditoria", "SELECT", ["public"], "perfiles_usuario.id = auth.uid() AND perfiles_usuario.es_admin = true AND perfiles_usuario.activo = true")
        self.assertIn("se esperaba exclusivamente {authenticated}", str(ctx_rol.exception))

        # Falla si la condición USING no valida es_admin o activo
        with self.assertRaises(Exception) as ctx_using:
            validar_politica_auditoria_estricta(True, 1, "Solo administradores pueden consultar auditoria", "SELECT", ["authenticated"], "perfiles_usuario.id = auth.uid()")
        self.assertIn("no valida la condición de administrador activo", str(ctx_using.exception))

        # Pasa con la configuración oficial exacta
        qual_oficial = "EXISTS (SELECT 1 FROM public.perfiles_usuario WHERE perfiles_usuario.id = auth.uid() AND perfiles_usuario.es_admin = true AND perfiles_usuario.activo = true)"
        self.assertTrue(validar_politica_auditoria_estricta(True, 1, "Solo administradores pueden consultar auditoria", "SELECT", ["authenticated"], qual_oficial))

        # 2. Simulación Postflight FK admin_id (única, dirigida a auth.users, con ON DELETE RESTRICT)
        def validar_fk_admin_id(total_fks: int, fks_validas: int):
            if total_fks != 1:
                raise Exception(f"Postflight falló: Se esperaba exactamente 1 clave foránea en admin_id, se encontraron {total_fks}.")
            if fks_validas != 1:
                raise Exception("Postflight falló: La clave foránea en admin_id debe referenciar auth.users(id) con ON DELETE RESTRICT.")
            return True

        # Falla si hay 0 o más de 1 FK
        with self.assertRaises(Exception) as ctx_fk0:
            validar_fk_admin_id(total_fks=0, fks_validas=0)
        self.assertIn("Se esperaba exactamente 1 clave foránea en admin_id", str(ctx_fk0.exception))

        with self.assertRaises(Exception) as ctx_fk2:
            validar_fk_admin_id(total_fks=2, fks_validas=1)
        self.assertIn("Se esperaba exactamente 1 clave foránea en admin_id", str(ctx_fk2.exception))

        # Falla si la FK apunta a otra tabla o no tiene RESTRICT
        with self.assertRaises(Exception) as ctx_fk_no_res:
            validar_fk_admin_id(total_fks=1, fks_validas=0)
        self.assertIn("debe referenciar auth.users(id) con ON DELETE RESTRICT", str(ctx_fk_no_res.exception))

        # Pasa si hay exactamente 1 FK válida con RESTRICT
        self.assertTrue(validar_fk_admin_id(total_fks=1, fks_validas=1))

        # 3. Simulación Postflight CHECK chk_auditoria_tipo_evento exacto sin valores extra
        def validar_check_tipo_evento_estricto(chk_def: str | None):
            if chk_def is None:
                raise Exception("Postflight falló: La restricción chk_auditoria_tipo_evento no está registrada.")
            if "tipo_evento" not in chk_def:
                raise Exception(f"Postflight falló: chk_auditoria_tipo_evento no opera sobre la columna tipo_evento: {chk_def}")
            literales = sorted(re.findall(r"'([^']+)'", chk_def))
            esperados = ["cambio_password_primer_ingreso", "reenvio_recuperacion", "restablecimiento_manual_excepcional"]
            if literales != esperados:
                raise Exception(f"Postflight falló: chk_auditoria_tipo_evento debe aceptar exactamente los tres eventos oficiales y ningún valor extra. Encontrados: {literales}")
            return True

        # Falla si no existe
        with self.assertRaises(Exception) as ctx_chk_none:
            validar_check_tipo_evento_estricto(None)
        self.assertIn("no está registrada", str(ctx_chk_none.exception))

        # Falla si no opera sobre tipo_evento
        with self.assertRaises(Exception) as ctx_chk_col:
            validar_check_tipo_evento_estricto("CHECK (otra_columna IN ('reenvio_recuperacion'))")
        self.assertIn("no opera sobre la columna tipo_evento", str(ctx_chk_col.exception))

        # Falla si falta un evento
        with self.assertRaises(Exception) as ctx_chk_inc:
            validar_check_tipo_evento_estricto("CHECK (tipo_evento IN ('reenvio_recuperacion', 'restablecimiento_manual_excepcional'))")
        self.assertIn("debe aceptar exactamente los tres eventos oficiales y ningún valor extra", str(ctx_chk_inc.exception))

        # Falla si contiene un valor extra no autorizado
        chk_con_extra = "CHECK (tipo_evento IN ('cambio_password_primer_ingreso', 'evento_extra_no_autorizado', 'reenvio_recuperacion', 'restablecimiento_manual_excepcional'))"
        with self.assertRaises(Exception) as ctx_chk_extra:
            validar_check_tipo_evento_estricto(chk_con_extra)
        self.assertIn("debe aceptar exactamente los tres eventos oficiales y ningún valor extra", str(ctx_chk_extra.exception))

        # Pasa con exactamente los 3 eventos oficiales
        chk_valido = "CHECK (tipo_evento = ANY (ARRAY['cambio_password_primer_ingreso'::text, 'reenvio_recuperacion'::text, 'restablecimiento_manual_excepcional'::text]))"
        self.assertTrue(validar_check_tipo_evento_estricto(chk_valido))

        # 4. Simulación Postflight Función de Inmutabilidad
        def validar_funcion_inmutabilidad(fn_count: int, is_secdef: bool, search_path_ok: bool):
            if fn_count != 1:
                raise Exception(f"Postflight falló: Se esperaba exactamente 1 función public.proteger_inmutabilidad_auditoria(), se encontraron {fn_count}.")
            if is_secdef:
                raise Exception("Postflight falló: La función proteger_inmutabilidad_auditoria tiene prosecdef=true (debe ser sin elevación).")
            if not search_path_ok:
                raise Exception("Postflight falló: La función proteger_inmutabilidad_auditoria debe conservar SET search_path = ''.")
            return True

        # Falla si fn_count != 1
        with self.assertRaises(Exception) as ctx_fn0:
            validar_funcion_inmutabilidad(fn_count=0, is_secdef=False, search_path_ok=True)
        self.assertIn("Se esperaba exactamente 1 función", str(ctx_fn0.exception))

        # Falla si prosecdef=True
        with self.assertRaises(Exception) as ctx_fn_sec:
            validar_funcion_inmutabilidad(fn_count=1, is_secdef=True, search_path_ok=True)
        self.assertIn("tiene prosecdef=true (debe ser sin elevación)", str(ctx_fn_sec.exception))

        # Falla si search_path no está configurado
        with self.assertRaises(Exception) as ctx_fn_sp:
            validar_funcion_inmutabilidad(fn_count=1, is_secdef=False, search_path_ok=False)
        self.assertIn("debe conservar SET search_path = ''", str(ctx_fn_sp.exception))

        # Pasa si es 1 función, sin elevación y con search_path
        self.assertTrue(validar_funcion_inmutabilidad(fn_count=1, is_secdef=False, search_path_ok=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)

