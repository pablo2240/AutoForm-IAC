"""Clasificación de formularios en familias de referencias, sin depender del nombre del archivo."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from pipeline.handlers import ExcelHandler
from pipeline.stages.stage_2_classifier import clasificar_elementos_formulario
from reference_library import ReferenceLibrary, ReferenceStore
from reference_library.embeddings import HashingProvider
from reference_library.families import ClasificadorFamilias, caracteristicas_estructurales
from reference_library.search import BuscadorSemantico
from referencias_helpers import _libro


PROVEEDOR_A = [["Razón social"], ["NIT"], ["Banco"], ["Número de cuenta"], ["Representante legal"], ["Teléfono"]]
PROVEEDOR_B = [["Nombre o razón social"], ["NIT"], ["Entidad bancaria"], ["Número de cuenta"], ["Dirección"], ["Correo electrónico"]]
CLIENTE_A = [["Nombre del cliente"], ["Cupo de crédito"], ["Plazo de pago"], ["Dirección de entrega"], ["Vendedor asignado"], ["Zona de ventas"]]
CLIENTE_B = [["Cliente"], ["Cupo de crédito solicitado"], ["Plazo de pago en días"], ["Lista de precios"], ["Vendedor asignado"], ["Ciudad de entrega"]]


@pytest.fixture
def clasificador(tmp_path: Path) -> ClasificadorFamilias:
    directorio = tmp_path / "referencias"
    for familia, titulo, libros in (
        ("proveedor", "DATOS DEL PROVEEDOR", (PROVEEDOR_A, PROVEEDOR_B)),
        ("cliente", "DATOS DEL CLIENTE", (CLIENTE_A, CLIENTE_B)),
    ):
        (directorio / familia).mkdir(parents=True)
        for numero, filas in enumerate(libros):
            (directorio / familia / f"{familia}_{numero}.xlsx").write_bytes(_libro(filas, titulo))
    store = ReferenceStore(tmp_path / "c.db")
    ReferenceLibrary(directorio, store, datos_empresa={}).sincronizar()
    return ClasificadorFamilias(store, BuscadorSemantico(store, HashingProvider()))


def _clasificar(clasificador: ClasificadorFamilias, filas: List[List[str]], titulo: str) -> Any:
    elementos = ExcelHandler.escanear(_libro(filas, titulo))
    clasificados, _ = clasificar_elementos_formulario(elementos, datos_empresa={})
    return clasificador.clasificar(clasificados)


def test_un_formulario_nuevo_se_asigna_a_la_familia_mas_parecida(clasificador: ClasificadorFamilias) -> None:
    nuevo = [["Razón social del proveedor"], ["NIT"], ["Entidad bancaria"], ["Número de cuenta"], ["Representante legal"], ["Teléfono"]]

    resultado = _clasificar(clasificador, nuevo, "INFORMACIÓN DEL PROVEEDOR")

    assert resultado.familia == "proveedor"
    assert resultado.probabilidades["proveedor"] > resultado.probabilidades["cliente"]
    assert resultado.puntaje_principal >= clasificador.umbral_puntaje
    assert abs(sum(resultado.probabilidades.values()) - 1.0) < 1e-6


def test_un_formulario_distinto_se_trata_como_desconocido(clasificador: ClasificadorFamilias) -> None:
    ajeno = [["Placa del vehículo"], ["Marca y modelo"], ["Kilometraje actual"], ["Fecha de revisión técnica"], ["Conductor autorizado"]]

    resultado = _clasificar(clasificador, ajeno, "INSPECCIÓN DE FLOTA")

    assert resultado.es_desconocido
    assert resultado.familia is None
    assert "desconocido" in resultado.resumen()


def test_la_clasificacion_no_depende_del_nombre_del_archivo(clasificador: ClasificadorFamilias) -> None:
    nuevo = [["Nombre del cliente"], ["Cupo de crédito"], ["Plazo de pago"], ["Vendedor asignado"], ["Zona de ventas"]]

    resultado = _clasificar(clasificador, nuevo, "FORMATO PROVEEDOR")

    assert resultado.familia == "cliente"


def test_una_biblioteca_sin_familias_clasifica_todo_como_desconocido(tmp_path: Path) -> None:
    directorio = tmp_path / "referencias"
    directorio.mkdir()
    (directorio / "suelto.xlsx").write_bytes(_libro(PROVEEDOR_A))
    store = ReferenceStore(tmp_path / "c.db")
    ReferenceLibrary(directorio, store, datos_empresa={}).sincronizar()
    clasificador = ClasificadorFamilias(store, BuscadorSemantico(store, HashingProvider()))

    resultado = _clasificar(clasificador, PROVEEDOR_A, "DATOS")

    assert resultado.es_desconocido
    assert "familias" in resultado.motivo


def test_agregar_una_familia_nueva_no_requiere_cambios_de_codigo(clasificador: ClasificadorFamilias, tmp_path: Path) -> None:
    carpeta = tmp_path / "referencias" / "empleado"
    carpeta.mkdir(parents=True)
    filas = [["Nombres y apellidos"], ["Cargo"], ["Fecha de ingreso"], ["EPS"], ["Fondo de pensiones"], ["Contacto de emergencia"]]
    (carpeta / "empleado_0.xlsx").write_bytes(_libro(filas, "DATOS DEL EMPLEADO"))
    ReferenceLibrary(tmp_path / "referencias", clasificador.store, datos_empresa={}).sincronizar()

    resultado = _clasificar(clasificador, [["Nombres y apellidos"], ["Cargo"], ["Fecha de ingreso"], ["EPS"], ["Fondo de pensiones"]], "EMPLEADO")

    assert resultado.familia == "empleado"
    assert set(resultado.probabilidades) == {"proveedor", "cliente", "empleado"}


def test_las_caracteristicas_estructurales_son_estables() -> None:
    a = caracteristicas_estructurales(50, 5, 1, 2)
    assert a.shape == (4,) and (a >= 0).all()
