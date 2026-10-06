"""Few-shot dinámico y su integración opcional con el mapeo del pipeline."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from core import llm_client
from pipeline.stages.stage_3_llm_mapper import _ejemplos_referencia
from reference_library import ReferenceLibrary, ReferenceStore
from reference_library.embeddings import HashingProvider
from reference_library.fewshot import GeneradorFewShot, top_k_configurado
from reference_library.search import BuscadorSemantico
from reference_library.service import (
    clasificar_formulario_ctx,
    construir_servicio,
    ejemplos_fewshot_para_lote,
    reiniciar_servicio,
)
from referencias_helpers import DATOS_EMPRESA, _diligenciado, _libro


@pytest.fixture(autouse=True)
def _limpiar_servicio():
    yield
    reiniciar_servicio(None)


@pytest.fixture
def servicio(tmp_path: Path):
    directorio = tmp_path / "referencias"
    (directorio / "proveedor").mkdir(parents=True)
    (directorio / "proveedor" / "uno.xlsx").write_bytes(_diligenciado())
    store = ReferenceStore(tmp_path / "c.db")
    biblioteca = ReferenceLibrary(directorio, store, datos_empresa=DATOS_EMPRESA)
    biblioteca.sincronizar()
    buscador = BuscadorSemantico(store, HashingProvider())
    servicio = construir_servicio(biblioteca, buscador)
    servicio.fewshot.umbral = 0.3  # el proveedor léxico de prueba da similitudes más bajas que los embeddings
    reiniciar_servicio(servicio)
    return servicio


def _lote(*rotulos: str) -> List[Dict[str, Any]]:
    return [{"id": i, "rotulo": r, "seccion": "DATOS"} for i, r in enumerate(rotulos, start=1)]


def test_recupera_ejemplos_de_referencias_similares_para_un_rotulo_nuevo(servicio) -> None:
    ejemplos = servicio.fewshot.ejemplos_para_lote(_lote("Número de NIT"), top_k=5)

    assert ejemplos
    assert ejemplos[0].campo == "nit"
    assert ejemplos[0].documento == "uno.xlsx"
    assert ejemplos[0].similitud >= servicio.fewshot.umbral


def test_top_k_limita_el_numero_de_ejemplos(servicio) -> None:
    lote = _lote("Razón social del proveedor", "NIT del proveedor", "Dirección del proveedor", "Correo electrónico")

    assert len(servicio.fewshot.ejemplos_para_lote(lote, top_k=2)) == 2
    assert len(servicio.fewshot.ejemplos_para_lote(lote, top_k=10)) <= 10
    assert servicio.fewshot.ejemplos_para_lote(lote, top_k=0) == []


def test_solo_se_proponen_campos_validos_del_perfil(servicio) -> None:
    lote = _lote("NIT", "Dirección")

    ejemplos = servicio.fewshot.ejemplos_para_lote(lote, campos_validos={"direccion"}, top_k=5)

    assert ejemplos and {e.campo for e in ejemplos} == {"direccion"}


def test_el_prompt_lleva_solo_informacion_compacta(servicio) -> None:
    ejemplo = servicio.fewshot.ejemplos_para_lote(_lote("NIT"), top_k=1)[0]

    assert set(ejemplo.para_prompt()) <= {"rotulo_ref", "campo", "similitud", "seccion_ref"}
    assert "documento" not in ejemplo.para_prompt()
    assert "documento" in ejemplo.para_registro()


def test_la_familia_detectada_tiene_prioridad(tmp_path: Path) -> None:
    directorio = tmp_path / "referencias"
    for familia in ("proveedor", "cliente"):
        (directorio / familia).mkdir(parents=True)
        (directorio / familia / f"{familia}.xlsx").write_bytes(_diligenciado())
    store = ReferenceStore(tmp_path / "c.db")
    ReferenceLibrary(directorio, store, datos_empresa=DATOS_EMPRESA).sincronizar()
    generador = GeneradorFewShot(BuscadorSemantico(store, HashingProvider()), top_k=1)

    ejemplos = generador.ejemplos_para_lote(_lote("NIT"), familia="cliente")

    assert [e.familia for e in ejemplos] == ["cliente"]


def test_top_k_configurable_por_variable_de_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOFORM_FEWSHOT_TOP_K", "3")
    assert top_k_configurado() == 3
    monkeypatch.setenv("AUTOFORM_FEWSHOT_TOP_K", "0")
    assert top_k_configurado() == 0
    monkeypatch.setenv("AUTOFORM_FEWSHOT_TOP_K", "abc")
    assert top_k_configurado() == 5


class _ClienteFalso:
    """Cliente Instructor de prueba que registra los mensajes enviados al LLM."""

    def __init__(self) -> None:
        self.mensajes: List[Dict[str, str]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._crear))

    def _crear(self, **kwargs: Any) -> Any:
        self.mensajes = kwargs["messages"]
        return SimpleNamespace(mappings=[])


def test_el_llm_recibe_ejemplos_solo_cuando_los_hay(monkeypatch: pytest.MonkeyPatch) -> None:
    cliente = _ClienteFalso()
    monkeypatch.setattr(llm_client, "obtener_cliente_instructor", lambda: cliente)
    campos = [{"id": 1, "rotulo": "Identificación fiscal"}]

    llm_client.consultar_llm_seccion_instructor(campos, {"empresa": {}}, "GENERAL")
    assert '"E"' not in cliente.mensajes[1]["content"]
    assert cliente.mensajes[0]["content"] == llm_client.STRICT_SYSTEM_PROMPT

    llm_client.consultar_llm_seccion_instructor(
        campos, {"empresa": {}}, "GENERAL", ejemplos=[{"rotulo_ref": "NIT", "campo": "nit", "similitud": 0.9}]
    )
    assert '"E":[{"rotulo_ref":"NIT"' in cliente.mensajes[1]["content"]
    assert llm_client.NOTA_EJEMPLOS_REFERENCIA in cliente.mensajes[0]["content"]


def test_el_stage_3_obtiene_ejemplos_y_los_registra_en_el_contexto(servicio) -> None:
    ctx = SimpleNamespace(
        datos_empresa=dict(DATOS_EMPRESA), metadatos={}, familia_formulario="proveedor", log=lambda *_a, **_k: None
    )

    ejemplos = _ejemplos_referencia(ctx, _lote("Identificación NIT"), "DATOS")

    assert ejemplos and ejemplos[0]["campo"] == "nit"
    assert ctx.metadatos["fewshot"][0]["lote"] == "DATOS"
    assert ctx.metadatos["fewshot"][0]["ejemplos"][0]["documento"] == "uno.xlsx"


def test_sin_biblioteca_el_pipeline_sigue_igual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOFORM_REFERENCES_ENABLED", "0")
    ctx = SimpleNamespace(
        datos_empresa=dict(DATOS_EMPRESA), metadatos={}, familia_formulario=None, elementos_clasificados=[],
        log=lambda *_a, **_k: None,
    )

    assert ejemplos_fewshot_para_lote(ctx, _lote("NIT"), "DATOS") == []
    assert _ejemplos_referencia(ctx, _lote("NIT"), "DATOS") == []
    assert clasificar_formulario_ctx(ctx) is None
    assert ctx.metadatos == {}


def test_una_biblioteca_vacia_no_genera_ejemplos_ni_clasificacion(tmp_path: Path) -> None:
    servicio_vacio = construir_servicio(
        ReferenceLibrary(tmp_path / "referencias", ReferenceStore(tmp_path / "vacia.db"), datos_empresa={}),
        BuscadorSemantico(ReferenceStore(tmp_path / "vacia.db"), HashingProvider()),
    )
    reiniciar_servicio(servicio_vacio)
    ctx = SimpleNamespace(metadatos={}, familia_formulario=None, elementos_clasificados=[], log=lambda *_a, **_k: None)

    assert ejemplos_fewshot_para_lote(ctx, _lote("NIT"), "DATOS") == []
    assert clasificar_formulario_ctx(ctx) is None
