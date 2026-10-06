"""Regresiones del catálogo compartido y aislamiento de perfiles por ejecución."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core import database, profile_manager
from pipeline.context import PipelineContext
from ui.page_profile_selector import invalidar_resultado_por_cambio_perfil


@pytest.fixture(autouse=True)
def _sqlite_temporal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Aísla el catálogo de pruebas de la base de desarrollo del usuario."""
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("AUTOFORM_ADMIN_PASSWORD", "TestCatalogo!123")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "catalogo.db")


def _datos(nombre: str, nit: str) -> dict:
    return {
        "razon_social": nombre,
        "nit": nit,
        "direccion": f"Dirección de {nombre}",
        "ciudad": "Bogotá",
        "correo": f"{nit}@example.test",
    }


def test_perfiles_compartidos_seleccionados_no_mezclan_datos() -> None:
    jose = profile_manager.crear_perfil_diligenciamiento(
        "José (Comerciante)", profile_manager.TipoPerfil.PERSONA, _datos("José", "1001"), "pablo"
    )
    empresa = profile_manager.crear_perfil_diligenciamiento(
        "Empresa X", profile_manager.TipoPerfil.EMPRESA, _datos("Empresa X", "9002"), "pablo"
    )

    perfil_jose = profile_manager.obtener_perfil_diligenciamiento(jose.id)
    perfil_empresa = profile_manager.obtener_perfil_diligenciamiento(empresa.id)

    assert perfil_jose.datos["razon_social"] == "José"
    assert perfil_jose.datos["nit"] == "1001"
    assert perfil_empresa.datos["razon_social"] == "Empresa X"
    assert perfil_empresa.datos["nit"] == "9002"


def test_preferencias_son_individuales_y_no_cambian_el_catalogo_global() -> None:
    primero = profile_manager.crear_perfil_diligenciamiento(
        "Perfil Pablo", profile_manager.TipoPerfil.EMPRESA, _datos("Pablo S.A.S.", "1010"), "pablo"
    )
    segundo = profile_manager.crear_perfil_diligenciamiento(
        "Perfil Laura", profile_manager.TipoPerfil.CONTRATISTA, _datos("Laura", "2020"), "laura"
    )

    profile_manager.guardar_preferencia_perfil("pablo", primero.id, "pablo")
    profile_manager.guardar_preferencia_perfil("laura", segundo.id, "laura")

    assert profile_manager.obtener_preferencia_perfil("pablo") == primero.id
    assert profile_manager.obtener_preferencia_perfil("laura") == segundo.id
    ids_visibles = {perfil.id for perfil in profile_manager.listar_perfiles_diligenciamiento()}
    assert {primero.id, segundo.id}.issubset(ids_visibles)


def test_edicion_usa_version_y_archivado_es_reversible_solo_admin() -> None:
    perfil = profile_manager.crear_perfil_diligenciamiento(
        "Contratista Y", profile_manager.TipoPerfil.CONTRATISTA, _datos("Contratista Y", "3030"), "pablo"
    )
    actualizado = profile_manager.actualizar_perfil_diligenciamiento(
        perfil.id,
        "Contratista Y actualizado",
        perfil.tipo,
        {**perfil.datos, "telefono": "3000000000"},
        perfil.version,
        "laura",
    )
    assert actualizado.version == perfil.version + 1
    assert actualizado.datos["telefono"] == "3000000000"

    with pytest.raises(database.ConflictoVersionPerfilError):
        profile_manager.actualizar_perfil_diligenciamiento(
            perfil.id, perfil.nombre, perfil.tipo, perfil.datos, perfil.version, "pablo"
        )
    with pytest.raises(PermissionError):
        profile_manager.archivar_perfil_diligenciamiento(perfil.id, actualizado.version, "pablo", es_admin=False)

    assert profile_manager.archivar_perfil_diligenciamiento(perfil.id, actualizado.version, "admin", es_admin=True)
    assert perfil.id not in {p.id for p in profile_manager.listar_perfiles_diligenciamiento()}
    with pytest.raises(profile_manager.PerfilNoDisponibleError):
        profile_manager.obtener_perfil_diligenciamiento(perfil.id)


def test_pipeline_congela_snapshot_del_perfil_y_cambio_limpia_resultados() -> None:
    datos_origen = _datos("Empresa A", "4040")
    contexto = PipelineContext(
        archivo_bytes=b"plantilla",
        nombre_archivo="formulario.xlsx",
        datos_empresa=datos_origen,
        profile_id="perfil-a",
        profile_nombre="Empresa A",
        profile_version=7,
    )
    datos_origen["razon_social"] = "Empresa B"

    assert contexto.profile_id == "perfil-a"
    assert contexto.profile_version == 7
    assert contexto.datos_empresa["razon_social"] == "Empresa A"

    estado = {"pipeline_ctx": contexto, "processed_file_id": "archivo-a", "otro": "conservar"}
    invalidar_resultado_por_cambio_perfil(estado)
    assert "pipeline_ctx" not in estado
    assert "processed_file_id" not in estado
    assert estado["otro"] == "conservar"


def test_migracion_declara_catalogo_preferencias_y_sin_perfil_global() -> None:
    migration = (Path(__file__).parents[1] / "supabase" / "migrations" / "007_shared_profile_catalog.sql").read_text(encoding="utf-8")
    assert "preferencias_perfil_usuario" in migration
    assert "auditoria_perfiles" in migration
    assert "DROP INDEX IF EXISTS public.idx_un_perfil_activo" in migration
    assert "estado IN ('ACTIVO', 'ARCHIVADO')" in migration
    assert "Solo un administrador puede archivar" in migration


def test_catalogo_remoto_pre_migracion_permite_seleccionar_perfiles_existentes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La UI no debe caer mientras el entorno remoto aún aplica la migración 007."""
    class TablaPerfilesPre007:
        def select(self, columnas: str):
            if "tipo_perfil" in columnas:
                raise AttributeError("columna tipo_perfil no disponible")
            return self

        def order(self, _campo: str):
            return self

        def execute(self):
            return SimpleNamespace(data=[{
                "id": "uuid-principal",
                "slug": "principal",
                "nombre_empresa": "IAC Latam",
                "datos_json": {"razon_social": "IAC Latam", "nit": "900000001"},
                "es_activa": True,
                "updated_at": "2026-10-05T00:00:00Z",
            }])

    class ClientePre007:
        def table(self, nombre: str):
            assert nombre == "perfiles_empresa"
            return TablaPerfilesPre007()

    monkeypatch.setattr(database, "usar_supabase", lambda: True)
    monkeypatch.setattr(database, "_obtener_cliente_activo", lambda _client=None: ClientePre007())
    perfiles = profile_manager.listar_perfiles_diligenciamiento()

    assert [(perfil.id, perfil.nombre, perfil.tipo, perfil.version) for perfil in perfiles] == [
        ("uuid-principal", "IAC Latam", profile_manager.TipoPerfil.EMPRESA, 1)
    ]
