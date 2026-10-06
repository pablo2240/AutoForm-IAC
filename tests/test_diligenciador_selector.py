"""Regresiones del selector 'Diligenciado por' y de la empresa fija."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import database, profile_manager
from ui.page_diligenciador_selector import (
    OPCION_MI_PERFIL,
    construir_operador_propio,
    operadores_guardados,
    resolver_diligenciador,
)


@pytest.fixture(autouse=True)
def _sqlite_temporal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("AUTOFORM_ADMIN_PASSWORD", "TestCatalogo!123")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "diligenciador.db")


USUARIO = {"id": "pablo", "nombre": "Pablo", "cargo": "Asesor", "cedula": "123", "telefono": "300", "correo": "pablo@iac.com.co"}


def test_crear_diligenciador_guarda_datos_fijos_sin_tocar_usuarios_ni_marca_global() -> None:
    antes = {o["id"]: o["es_activo"] for o in profile_manager.listar_operadores()}

    jose = profile_manager.crear_diligenciador(
        "José Pérez", cargo="Comercial", cedula="1001", telefono="3101234567", correo="jose@iac.com.co"
    )

    assert jose["id"] == "josé_pérez" or jose["id"].startswith("jos")
    guardado = database.obtener_operador_db(jose["id"])
    assert guardado["nombre"] == "José Pérez"
    assert guardado["cargo"] == "Comercial"
    assert guardado["cedula"] == "1001"
    assert guardado["telefono"] == "3101234567"
    assert guardado["correo"] == "jose@iac.com.co"
    assert guardado["es_activo"] is False
    despues = {o["id"]: o["es_activo"] for o in profile_manager.listar_operadores() if o["id"] in antes}
    assert despues == antes


def test_crear_diligenciador_rechaza_nombre_vacio_correo_invalido_y_duplicado() -> None:
    with pytest.raises(ValueError):
        profile_manager.crear_diligenciador("   ")
    with pytest.raises(ValueError):
        profile_manager.crear_diligenciador("Ana", correo="no-es-correo")
    profile_manager.crear_diligenciador("Ana", correo="ana@iac.com.co")
    with pytest.raises(ValueError):
        profile_manager.crear_diligenciador("Otra Ana", correo="ANA@iac.com.co")


def test_nombres_iguales_generan_ids_distintos() -> None:
    primero = profile_manager.crear_diligenciador("Luis Gómez")
    segundo = profile_manager.crear_diligenciador("Luis Gómez")
    assert primero["id"] != segundo["id"]


def test_resolver_mi_perfil_guardado_y_desconocido() -> None:
    jose = profile_manager.crear_diligenciador("José", cargo="Comercial", correo="jose@iac.com.co")
    guardados = operadores_guardados(USUARIO, profile_manager.listar_operadores())

    assert resolver_diligenciador(OPCION_MI_PERFIL, USUARIO, guardados)["nombre"] == "Pablo"
    assert resolver_diligenciador(jose["id"], USUARIO, guardados)["nombre"] == "José"
    assert resolver_diligenciador("no-existe", USUARIO, guardados)["nombre"] == "Pablo"


def test_operadores_guardados_excluye_la_propia_cuenta() -> None:
    operadores = [
        {"id": "pablo", "nombre": "Pablo", "correo": "x@y.co"},
        {"id": "otro", "nombre": "Otro", "correo": "PABLO@iac.com.co"},
        {"id": "jose", "nombre": "José", "correo": "jose@iac.com.co"},
    ]
    assert [o["id"] for o in operadores_guardados(USUARIO, operadores)] == ["jose"]


def test_fusion_completa_diligenciado_por_con_el_perfil_elegido_y_conserva_la_empresa() -> None:
    empresa = {"razon_social": "IAC Latam", "nit": "900"}
    jose = profile_manager.crear_diligenciador(
        "José", cargo="Comercial", cedula="1001", telefono="3101234567", correo="jose@iac.com.co"
    )

    datos = profile_manager.fusionar_operador_en_datos_empresa(empresa, operador=jose)

    assert datos["razon_social"] == "IAC Latam"
    assert datos["responsable_nombre"] == "José"
    assert datos["responsable_cargo"] == "Comercial"
    assert datos["responsable_cedula"] == "1001"
    assert datos["responsable_telefono"] == "3101234567"
    assert datos["responsable_correo"] == "jose@iac.com.co"


def test_construir_operador_propio_aplica_direccion_y_ciudad_por_defecto() -> None:
    propio = construir_operador_propio(USUARIO)
    assert propio["nombre"] == "Pablo"
    assert propio["ciudad"] == "Bogotá"
    assert propio["direccion"]


def test_empresa_fija_no_depende_del_catalogo_007() -> None:
    empresa = profile_manager.obtener_empresa_fija()
    assert empresa.id == profile_manager.EMPRESA_FIJA_ID
    assert empresa.tipo is profile_manager.TipoPerfil.EMPRESA
    assert empresa.datos


def test_guardar_operador_propio_reutiliza_la_fila_existente_por_correo() -> None:
    database.guardar_operador_db("pablo_reyes", "Pablo Reyes", correo="pablo@iac.com.co")
    usuario = {"id": "e3e64650-uuid", "correo": "pablo@iac.com.co"}

    assert profile_manager.guardar_operador_propio(usuario, "Pablo R.", cargo="Líder", telefono="3000000000")

    filas = [o for o in profile_manager.listar_operadores() if o["correo"] == "pablo@iac.com.co"]
    assert len(filas) == 1
    assert filas[0]["id"] == "pablo_reyes"
    assert filas[0]["cargo"] == "Líder"
