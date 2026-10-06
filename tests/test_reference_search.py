"""Embeddings y búsqueda semántica sobre la base de conocimiento de referencias."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Sequence

import numpy as np
import pytest

from reference_library import ReferenceLibrary, ReferenceStore
from reference_library.embeddings import HashingProvider, obtener_proveedor
from reference_library.search import BuscadorSemantico
from reference_library.vector_index import IndiceNumpy
from referencias_helpers import DATOS_EMPRESA, _diligenciado, _libro


class ProveedorConceptual:
    """Proveedor de prueba: rótulos del mismo concepto comparten dirección aunque no compartan palabras."""

    nombre = "prueba:conceptual"
    CONCEPTOS = {
        "nit": ("nit", "identificacion fiscal", "numero tributario"),
        "razon": ("razon social", "nombre legal de la empresa"),
    }

    def embed(self, textos: Sequence[str]) -> np.ndarray:
        matriz = np.zeros((len(textos), len(self.CONCEPTOS) + 1), dtype=np.float32)
        for fila, texto in enumerate(textos):
            normal = str(texto).lower().strip()
            for columna, sinonimos in enumerate(self.CONCEPTOS.values()):
                if normal in sinonimos:
                    matriz[fila, columna] = 1.0
            if not matriz[fila].any():
                matriz[fila, -1] = 1.0
        return matriz


@pytest.fixture
def entorno(tmp_path: Path) -> Dict[str, Any]:
    directorio = tmp_path / "referencias"
    directorio.mkdir()
    store = ReferenceStore(tmp_path / "conocimiento.db")
    biblioteca = ReferenceLibrary(directorio, store, datos_empresa=DATOS_EMPRESA)
    return {"dir": directorio, "lib": biblioteca, "store": store}


def _poblar(entorno: Dict[str, Any]) -> None:
    (entorno["dir"] / "proveedor").mkdir()
    (entorno["dir"] / "proveedor" / "uno.xlsx").write_bytes(_diligenciado())
    (entorno["dir"] / "cliente").mkdir()
    (entorno["dir"] / "cliente" / "dos.xlsx").write_bytes(
        _libro([["Identificación fiscal"], ["Nombre legal de la empresa"], ["Observaciones adicionales"]])
    )
    entorno["lib"].sincronizar()


def test_indice_numpy_devuelve_los_mas_similares_y_respeta_filtros() -> None:
    indice = IndiceNumpy(
        np.array([10, 20, 30]),
        np.array([[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]], dtype=np.float32),
    )

    assert [i for i, _ in indice.buscar(np.array([1.0, 0.0]), 2)] == [10, 20]
    permitidos = np.array([False, True, True])
    assert [i for i, _ in indice.buscar(np.array([1.0, 0.0]), 2, permitidos)] == [20, 30]
    assert indice.buscar(np.array([1.0, 0.0]), 0) == []


def test_el_proveedor_hash_es_determinista_y_normalizado() -> None:
    a = HashingProvider().embed(["Razón social", "Razón social"])

    assert np.allclose(a[0], a[1])
    assert np.isclose(np.linalg.norm(a[0]), 1.0)


def test_un_proveedor_desconocido_se_rechaza_y_uno_no_disponible_cae_al_respaldo(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        obtener_proveedor("inexistente")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("core.embedding_engine._cargar_api_key", lambda: None)

    assert isinstance(obtener_proveedor("openai"), HashingProvider)


def test_la_indexacion_es_incremental_y_se_limpia_al_eliminar_documentos(entorno: Dict[str, Any]) -> None:
    _poblar(entorno)
    buscador = BuscadorSemantico(entorno["store"], HashingProvider())

    creados = buscador.reindexar()
    assert creados == entorno["store"].estadisticas()["campos"] > 0
    assert buscador.reindexar() == 0

    doc_id = next(d.doc_id for d in entorno["lib"].listar() if d.nombre == "uno.xlsx")
    entorno["lib"].eliminar(doc_id)

    assert buscador.buscar("nit", top_k=10, excluir_doc_ids=[]) is not None
    assert all(r.documento != "uno.xlsx" for r in buscador.buscar("razón social", top_k=10))


def test_la_busqueda_devuelve_campo_documento_ubicacion_similitud_y_contexto(entorno: Dict[str, Any]) -> None:
    _poblar(entorno)
    buscador = BuscadorSemantico(entorno["store"], HashingProvider())

    mejor = buscador.buscar("NIT", top_k=3)[0]

    assert mejor.etiqueta == "NIT"
    assert mejor.campo_maestro == "nit"
    assert mejor.documento == "uno.xlsx" and mejor.familia == "proveedor"
    assert mejor.coordenada and mejor.hoja == "Formulario"
    assert mejor.similitud == 1.0
    assert mejor.fuente_campo and mejor.confianza_campo > 0
    assert mejor.validado


def test_los_embeddings_relacionan_conceptos_con_palabras_distintas(entorno: Dict[str, Any]) -> None:
    _poblar(entorno)
    buscador = BuscadorSemantico(entorno["store"], ProveedorConceptual(), peso_embedding=1.0)

    resultados = buscador.buscar("Número tributario", top_k=3, solo_con_campo_maestro=True)

    assert resultados[0].campo_maestro == "nit"
    assert resultados[0].sim_embedding == pytest.approx(1.0)
    assert resultados[0].sim_lexica < 1.0


def test_filtros_por_validacion_familia_y_documento_excluido(entorno: Dict[str, Any]) -> None:
    _poblar(entorno)
    buscador = BuscadorSemantico(entorno["store"], HashingProvider())
    doc_uno = next(d.doc_id for d in entorno["lib"].listar() if d.nombre == "uno.xlsx")

    assert all(r.validado for r in buscador.buscar("nit", top_k=10, solo_validados=True))
    assert {r.familia for r in buscador.buscar("nit", top_k=10, familia="cliente")} == {"cliente"}
    assert all(r.doc_id != doc_uno for r in buscador.buscar("nit", top_k=10, excluir_doc_ids=[doc_uno]))
    assert buscador.buscar("nit", familia="no-existe") == []


def test_rotulos_iguales_de_varios_documentos_se_agrupan(tmp_path: Path) -> None:
    carpeta = tmp_path / "referencias"
    carpeta.mkdir()
    for nombre in ("a.xlsx", "b.xlsx"):
        (carpeta / nombre).write_bytes(_diligenciado())
    store = ReferenceStore(tmp_path / "c.db")
    ReferenceLibrary(carpeta, store, datos_empresa=DATOS_EMPRESA).sincronizar()

    resultados = BuscadorSemantico(store, HashingProvider()).buscar("NIT", top_k=5)

    nits = [r for r in resultados if r.campo_maestro == "nit"]
    assert len(nits) == 1
    assert nits[0].documentos == ["a.xlsx", "b.xlsx"]


def test_cambiar_de_proveedor_reindexa_sin_mezclar_espacios_vectoriales(entorno: Dict[str, Any]) -> None:
    _poblar(entorno)
    BuscadorSemantico(entorno["store"], HashingProvider()).reindexar()

    otro = BuscadorSemantico(entorno["store"], ProveedorConceptual())

    assert otro.reindexar() == entorno["store"].estadisticas()["campos"]
    assert len(entorno["store"].campos_sin_vector(HashingProvider.nombre)) == 0


def test_busqueda_sobre_base_vacia_devuelve_listas_vacias(tmp_path: Path) -> None:
    buscador = BuscadorSemantico(ReferenceStore(tmp_path / "vacia.db"), HashingProvider())

    assert buscador.buscar("nit") == []
    assert buscador.buscar_lote(["a", "b"]) == [[], []]
