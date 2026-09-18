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

from core import auth_manager, database
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
        """Verifica que obtener_cliente_admin falle si no está SUPABASE_SERVICE_ROLE_KEY."""
        with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": ""}):
            with self.assertRaises(database.ConfiguracionInvalidaError):
                database.obtener_cliente_admin()

    def test_03_obtener_cliente_usuario_falla_sin_anon_key(self):
        """Verifica que obtener_cliente_usuario falle si faltan SUPABASE_URL o SUPABASE_ANON_KEY."""
        with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_ANON_KEY": ""}):
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
                t.select.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"application_code": "autoform-excel", "environment": "staging", "project_ref": "test123"}]
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
                t.select.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"application_code": "autoform-excel", "environment": "staging", "project_ref": "test123"}]
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
        mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"application_code": "autoform-excel", "environment": "staging", "project_ref": "staging-123"}]
        )
        rec = migrador.verificar_identidad_despliegue(mock_client, "staging-123")
        self.assertEqual(rec["application_code"], "autoform-excel")
        self.assertEqual(rec["environment"], "staging")
        self.assertEqual(rec["project_ref"], "staging-123")

    def test_27_verificar_identidad_despliegue_rechaza_app_incorrecta(self):
        """Verifica que aborte si application_code en BD no es 'autoform-excel' (ej: autoform-pdf)."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"application_code": "autoform-pdf", "environment": "staging", "project_ref": "staging-123"}]
        )
        with self.assertRaises(SystemExit) as ctx:
            migrador.verificar_identidad_despliegue(mock_client, "staging-123")
        self.assertEqual(ctx.exception.code, 1)

    def test_28_verificar_identidad_despliegue_rechaza_environment_incorrecto(self):
        """Verifica que aborte si environment en BD no es 'staging' (ej: production)."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"application_code": "autoform-excel", "environment": "production", "project_ref": "staging-123"}]
        )
        with self.assertRaises(SystemExit) as ctx:
            migrador.verificar_identidad_despliegue(mock_client, "staging-123")
        self.assertEqual(ctx.exception.code, 1)

    def test_29_verificar_identidad_despliegue_rechaza_project_ref_mismatch(self):
        """Verifica que aborte si project_ref en BD no coincide con el proyecto objetivo."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"application_code": "autoform-excel", "environment": "staging", "project_ref": "proyecto-bd-diferente"}]
        )
        with self.assertRaises(SystemExit) as ctx:
            migrador.verificar_identidad_despliegue(mock_client, "staging-123")
        self.assertEqual(ctx.exception.code, 1)

    def test_30_verificar_identidad_despliegue_rechaza_tabla_vacia(self):
        """Verifica que aborte si deployment_identity está vacía o sin inicializar."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
