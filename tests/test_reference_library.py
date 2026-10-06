"""Biblioteca de referencias: extracción, base de conocimiento y ciclo de vida de los documentos."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

import pytest
from reference_library import ReferenceLibrary, ReferenceStore, extraer_conocimiento
from reference_library.extractor import FUENTE_ALIAS, FUENTE_VALOR, normalizar_etiqueta
from referencias_helpers import DATOS_EMPRESA, _diligenciado, _en_blanco, _libro


@pytest.fixture
def entorno(tmp_path: Path) -> Dict[str, Any]:
    directorio = tmp_path / "referencias"
    directorio.mkdir()
    biblioteca = ReferenceLibrary(
        directorio=directorio,
        store=ReferenceStore(tmp_path / "conocimiento.db"),
        datos_empresa=DATOS_EMPRESA,
    )
    return {"dir": directorio, "lib": biblioteca}


def test_normalizar_etiqueta_ignora_tildes_y_puntuacion() -> None:
    assert normalizar_etiqueta("  Razón  Social: ") == "razon social"


def test_extrae_campo_maestro_desde_valores_de_ejemplo() -> None:
    campos = {c.etiqueta_norm: c for c in extraer_conocimiento(_diligenciado(), "f.xlsx", DATOS_EMPRESA).campos}

    assert campos["nit"].campo_maestro == "nit"
    assert campos["nit"].fuente_campo == FUENTE_VALOR
    assert campos["nit"].ejemplo_valor == "900123456"
    assert campos["razon social"].campo_maestro == "razon_social"
    assert campos["direccion"].campo_maestro == "direccion"
    assert campos["telefono"].coordenada == "A9"


def test_formulario_en_blanco_usa_alias_y_deja_sin_campo_lo_desconocido() -> None:
    campos = {c.etiqueta_norm: c for c in extraer_conocimiento(_en_blanco(), "f.xlsx", {}).campos}

    assert campos["nit"].campo_maestro == "nit"
    assert campos["nit"].fuente_campo == FUENTE_ALIAS
    assert campos["observaciones adicionales"].campo_maestro is None
    assert campos["observaciones adicionales"].confianza == 0.0


def test_la_estructura_resume_hojas_y_secciones() -> None:
    estructura = extraer_conocimiento(_diligenciado(), "f.xlsx", DATOS_EMPRESA).estructura

    assert estructura["hojas"] == ["Formulario"]
    assert estructura["total_campos"] >= 5
    assert estructura["campos_con_campo_maestro"] >= 4


def test_un_libro_con_controles_vml_se_puede_leer_como_referencia() -> None:
    entrada = BytesIO(_diligenciado())
    salida = BytesIO()
    with zipfile.ZipFile(entrada) as origen, zipfile.ZipFile(salida, "w") as destino:
        for nombre in origen.namelist():
            destino.writestr(nombre, origen.read(nombre))
        destino.writestr("xl/ctrlProps/ctrlProp1.xml", b"<ctrlProp/>")

    extraccion = extraer_conocimiento(salida.getvalue(), "vml.xlsx", DATOS_EMPRESA)

    assert any(c.campo_maestro == "nit" for c in extraccion.campos)


def test_sincronizar_agrega_omite_sin_cambios_actualiza_y_elimina(entorno: Dict[str, Any]) -> None:
    carpeta, biblioteca = entorno["dir"], entorno["lib"]
    (carpeta / "uno.xlsx").write_bytes(_diligenciado())
    (carpeta / "dos.xlsx").write_bytes(_en_blanco())

    primera = biblioteca.sincronizar()
    assert sorted(primera.agregados) == ["dos.xlsx", "uno.xlsx"]

    segunda = biblioteca.sincronizar()
    assert not segunda.hubo_cambios
    assert sorted(segunda.sin_cambios) == ["dos.xlsx", "uno.xlsx"]

    (carpeta / "dos.xlsx").write_bytes(_libro([["Correo electrónico"]]))
    tercera = biblioteca.sincronizar()
    assert tercera.actualizados == ["dos.xlsx"]
    assert {c["etiqueta_norm"] for c in biblioteca.store.listar_campos()
            if c["documento"] == "dos.xlsx"} == {"correo electronico"}

    (carpeta / "uno.xlsx").unlink()
    cuarta = biblioteca.sincronizar()
    assert cuarta.eliminados == ["uno.xlsx"]
    assert [d.nombre for d in biblioteca.listar()] == ["dos.xlsx"]


def test_todo_el_conocimiento_indica_de_que_documento_proviene(entorno: Dict[str, Any]) -> None:
    (entorno["dir"] / "uno.xlsx").write_bytes(_diligenciado())
    biblioteca = entorno["lib"]
    biblioteca.sincronizar()

    campos = biblioteca.store.listar_campos(solo_con_campo_maestro=True)

    assert campos
    assert {c["documento"] for c in campos} == {"uno.xlsx"}
    assert all(c["doc_id"] and c["coordenada"] and c["fuente_campo"] for c in campos)


def test_cambiar_los_datos_de_la_empresa_reprocesa_los_documentos(tmp_path: Path) -> None:
    carpeta = tmp_path / "referencias"
    carpeta.mkdir()
    (carpeta / "uno.xlsx").write_bytes(_diligenciado())
    store = ReferenceStore(tmp_path / "c.db")
    ReferenceLibrary(carpeta, store, datos_empresa={}).sincronizar()

    reporte = ReferenceLibrary(carpeta, store, datos_empresa=DATOS_EMPRESA).sincronizar()

    assert reporte.actualizados == ["uno.xlsx"]


def test_agregar_y_eliminar_desde_la_api(entorno: Dict[str, Any]) -> None:
    biblioteca, carpeta = entorno["lib"], entorno["dir"]

    doc_id = biblioteca.agregar(_diligenciado(), nombre="nuevo.xlsx", familia="proveedor")

    assert (carpeta / "proveedor" / "nuevo.xlsx").exists()
    documento = biblioteca.store.obtener_documento(doc_id)
    assert documento is not None and documento.familia == "proveedor"

    assert biblioteca.eliminar(doc_id) is True
    assert not (carpeta / "proveedor" / "nuevo.xlsx").exists()
    assert biblioteca.store.listar_campos(doc_id=doc_id) == []
    assert biblioteca.eliminar(doc_id) is False


def test_agregar_rechaza_formatos_no_soportados(entorno: Dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        entorno["lib"].agregar(b"texto", nombre="notas.txt")


def test_un_archivo_corrupto_se_registra_como_error_sin_romper_el_resto(entorno: Dict[str, Any]) -> None:
    (entorno["dir"] / "roto.xlsx").write_bytes(b"esto no es un excel")
    (entorno["dir"] / "bueno.xlsx").write_bytes(_diligenciado())

    reporte = entorno["lib"].sincronizar()

    assert "roto.xlsx" in reporte.errores
    assert reporte.agregados == ["bueno.xlsx"]
    assert entorno["lib"].estadisticas()["documentos_con_error"] == 1


def test_familia_fuente_y_confianza_por_carpeta_nombre_y_manifiesto(entorno: Dict[str, Any]) -> None:
    carpeta, biblioteca = entorno["dir"], entorno["lib"]
    (carpeta / "cliente").mkdir()
    (carpeta / "cliente" / "FORM_Completo.xlsx").write_bytes(_diligenciado())
    (carpeta / "FORM_AutoForm (1).xlsx").write_bytes(_diligenciado())
    (carpeta / "libre.xlsx").write_bytes(_en_blanco())
    (carpeta / "referencias.json").write_text(
        json.dumps({"libre.xlsx": {"familia": "empresa", "confianza": 0.5}}), encoding="utf-8"
    )

    biblioteca.sincronizar()
    por_nombre = {d.nombre: d for d in biblioteca.listar()}

    assert por_nombre["FORM_Completo.xlsx"].familia == "cliente"
    assert por_nombre["FORM_Completo.xlsx"].fuente == "diligenciado_verificado"
    assert por_nombre["FORM_AutoForm (1).xlsx"].fuente == "generado_autoform"
    assert por_nombre["libre.xlsx"].familia == "empresa"
    assert por_nombre["libre.xlsx"].confianza == 0.5


def test_reprocesar_un_documento_ignora_el_hash(entorno: Dict[str, Any]) -> None:
    (entorno["dir"] / "uno.xlsx").write_bytes(_diligenciado())
    biblioteca = entorno["lib"]
    biblioteca.sincronizar()
    doc_id = biblioteca.listar()[0].doc_id

    reporte = biblioteca.reprocesar(doc_id)

    assert reporte.actualizados == ["uno.xlsx"]
    assert not reporte.errores


def test_la_biblioteca_crece_sin_cambios_de_codigo(entorno: Dict[str, Any]) -> None:
    for numero in range(30):
        (entorno["dir"] / f"form_{numero:02d}.xlsx").write_bytes(
            _libro([["Razón social", f"Empresa {numero} SAS"], ["NIT", str(900000000 + numero)]])
        )

    reporte = entorno["lib"].sincronizar()

    assert len(reporte.agregados) == 30
    assert entorno["lib"].estadisticas()["documentos"] == 30
