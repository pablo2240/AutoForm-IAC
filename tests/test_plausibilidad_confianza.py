"""Compuerta de plausibilidad (A1) y confianza honesta (A2) sobre las asignaciones del mapeo."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from core import confianza_mapeo
from core.confianza_mapeo import evaluar_confianza, nivel_para
from core.plausibilidad import evaluar_plausibilidad
from pipeline.stages.stage_3c_plausibilidad import refinar_plan


# ── A1: compuerta de plausibilidad ──────────────────────────────────────────

@pytest.mark.parametrize("rotulo,regla", [
    ("Por f+B61avor indicar el porcentaje de cumplimiento de su SG-SST:95.0%", "R4"),
    ("Por favor indicar el porcentaje de cumplimiento de su SG-SST", "R3"),
    ("Certificación expedida por la ARL del cumplimiento del SG-SST (jurídica o natural) vigente", "R1"),
    ("¿Pertenece a algún gremio o asociación?", "R2"),
    ("Pertenece a algún gremio o asociación?", "R2"),
    ("Cumplimiento del SG-SST:95.0%", "R4"),
    ("Tarifa por mil: 9,66", "R4"),
])
def test_rechaza_instrucciones_preguntas_y_rotulos_con_valor_embebido(rotulo: str, regla: str) -> None:
    veredicto = evaluar_plausibilidad(rotulo)

    assert not veredicto.plausible and veredicto.regla == regla


def test_rechaza_celdas_con_marca_de_casilla_y_opciones_de_seleccion() -> None:
    assert evaluar_plausibilidad("Activación", valor_destino_actual="X").regla == "R5"
    assert evaluar_plausibilidad("Activación", valor_destino_actual=" ✓ ").regla == "R5"
    assert evaluar_plausibilidad("Activación y actualización", tipo_clasificacion="OPCION_SELECCION").regla == "R6"


@pytest.mark.parametrize("rotulo", [
    "Nombre o Razón Social", "NIT", "Número de Cuenta", "E-mail de Contacto", "Fecha de constitución:",
    "Dirección de notificación judicial", "Nombre del representante legal", "Teléfono / Celular:", "",
])
def test_no_toca_los_rotulos_de_campos_reales(rotulo: str) -> None:
    assert evaluar_plausibilidad(rotulo, valor_destino_actual=None).plausible


# ── A2: confianza con evidencia ─────────────────────────────────────────────

def _item(rotulo: str, campo: str, **extra: Any) -> Dict[str, Any]:
    return {"rotulo": rotulo, "rotulo_original": rotulo, "campo": campo, "seccion": "INFORMACIÓN GENERAL", "valor": "dato", **extra}


def _con_similitud(monkeypatch: pytest.MonkeyPatch, valores: List[Any]) -> None:
    monkeypatch.setattr(confianza_mapeo, "similitudes_semanticas", lambda rotulos, campos: list(valores)[: len(rotulos)])


def test_la_evidencia_fuerte_no_depende_de_la_similitud_semantica(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_similitud(monkeypatch, [0.05, 0.05, 0.05, 0.05])
    items = [
        _item("NIT", "nit"),                                              # alias determinista
        _item("Dato raro", "banco", fuente="determinista_alias"),          # regla determinista
        _item("Lo que sea", "telefono", nivel_confianza="EXACTA"),         # el rótulo contiene el campo
        _item("Otro", "cedula", motivo="Context-First (ADR-0009): remap"),  # validador de contexto
    ]

    evaluaciones = evaluar_confianza(items)

    assert [e.descartar for e in evaluaciones] == [False] * 4
    assert min(e.score for e in evaluaciones) >= 0.90


def test_una_asignacion_solo_del_llm_sin_relacion_con_el_campo_se_descarta(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_similitud(monkeypatch, [0.12, 0.35, 0.72])
    items = [_item("Activación", "razon_social"), _item("Tarifa", "razon_social"), _item("Detalle adicional", "banco")]

    sin_relacion, moderada, alta = evaluar_confianza(items)

    assert sin_relacion.descartar and sin_relacion.nivel == "SIN_COINCIDENCIA" and sin_relacion.score < 0.5
    assert not moderada.descartar and moderada.nivel == "PARCIAL" and 0.5 <= moderada.score < 0.75
    assert not alta.descartar and alta.nivel == "ALTA" and alta.score >= 0.75


def test_sin_modelo_de_embeddings_nunca_se_descarta_por_similitud(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_similitud(monkeypatch, [None])

    evaluacion = evaluar_confianza([_item("Activación", "razon_social")])[0]

    assert not evaluacion.descartar and evaluacion.nivel == "PARCIAL"


def test_una_referencia_validada_eleva_la_confianza(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_similitud(monkeypatch, [0.05])

    evaluacion = evaluar_confianza([_item("Rótulo particular", "banco")], lambda rotulo, campo: campo == "banco")[0]

    assert not evaluacion.descartar and evaluacion.score == pytest.approx(0.90)


def test_los_niveles_siguen_los_puntajes() -> None:
    assert [nivel_para(s) for s in (1.0, 0.95, 0.80, 0.60, 0.30)] == ["EXACTA", "EXACTA", "ALTA", "PARCIAL", "SIN_COINCIDENCIA"]


# ── Etapa 3c ────────────────────────────────────────────────────────────────

def _ctx(valores_previos: Dict[Any, Any] | None = None) -> Any:
    registro: List[str] = []
    inspeccion = SimpleNamespace(obtener_valor_anterior=lambda hoja, fila, col: (valores_previos or {}).get((fila, col)))
    return SimpleNamespace(
        elementos_clasificados=[], elementos_raw=[], inspeccion_excel=inspeccion, metadatos={},
        log=lambda m, *_a, **_k: registro.append(m), registro=registro,
    )


def test_la_etapa_descarta_lo_implausible_y_marca_en_revision_lo_dudoso(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_similitud(monkeypatch, [0.40])
    plan = [
        _item("NIT", "nit", hoja="H", fila=1, columna=1, fila_destino=1, columna_destino=2, estado="APROBADO"),
        _item("Activación", "razon_social", hoja="H", fila=92, columna=6, fila_destino=92, columna_destino=9, estado="APROBADO"),
        _item("Detalle", "banco", hoja="H", fila=3, columna=1, fila_destino=3, columna_destino=2, estado="APROBADO"),
        _item("¿Pertenece a algún gremio?", "razon_social", hoja="H", fila=71, columna=2, fila_destino=71, columna_destino=4, estado="APROBADO"),
    ]

    refinado = refinar_plan(_ctx({(92, 9): "X"}), plan)

    por_rotulo = {i["rotulo"]: i for i in refinado}
    assert por_rotulo["NIT"]["estado"] == "APROBADO" and por_rotulo["NIT"]["confianza_score"] >= 0.9
    assert por_rotulo["Activación"]["estado"] == "DESCARTADO" and "R5" in por_rotulo["Activación"]["motivo"]
    assert por_rotulo["Detalle"]["estado"] == "REVISION" and por_rotulo["Detalle"]["confianza_score"] == pytest.approx(0.60)
    assert por_rotulo["¿Pertenece a algún gremio?"]["estado"] == "DESCARTADO"


def test_las_plantillas_verificadas_solo_pasan_por_la_compuerta_a1(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_similitud(monkeypatch, [0.01])
    plan = [_item("Detalle", "banco", hoja="H", fila=3, columna=1, estado="APROBADO")]

    refinado = refinar_plan(_ctx(), plan, es_plantilla=True)

    assert refinado[0]["estado"] == "APROBADO" and "confianza_score" not in refinado[0]


def test_la_etapa_respeta_los_reemplazos_del_diligenciador_y_nunca_rompe_el_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = [_item("Nombre", "responsable_nombre", hoja="H", fila=3, columna=2, sobrescribir_valor_previo=True, estado="APROBADO")]
    assert refinar_plan(_ctx(), plan)[0]["estado"] == "APROBADO"

    def _explota(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr("pipeline.stages.stage_3c_plausibilidad.evaluar_confianza", _explota)
    ctx = _ctx()
    original = [_item("NIT", "nit", hoja="H", fila=1, columna=1, estado="APROBADO")]

    assert refinar_plan(ctx, original) == original
    assert any("Omitida" in m for m in ctx.registro)


def test_las_formulas_de_declaracion_del_representante_no_se_descartan(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_similitud(monkeypatch, [0.14, 0.28])
    items = [
        _item("Yo,", "representante_legal", seccion="8. DECLARACION DE ORIGEN DE LOS BIENES Y FONDOS"),
        _item("expedido en:", "lugar_expedicion", seccion="8. DECLARACION DE ORIGEN DE LOS BIENES Y FONDOS"),
    ]

    yo, expedido = evaluar_confianza(items)

    assert not yo.descartar and yo.score == pytest.approx(0.85)
    assert not expedido.descartar and expedido.score == pytest.approx(0.85)


def test_baja_similitud_en_la_seccion_del_dominio_se_revisa_pero_no_se_descarta(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_similitud(monkeypatch, [0.10, 0.10])
    en_dominio = _item("Detalle", "numero_cuenta", seccion="7. INFORMACION FINANCIERA Y BANCARIA")
    fuera_de_dominio = _item("Detalle", "numero_cuenta", seccion="2. BIEN Y/O SERVICIO OFRECIDO")

    revisar, descartar = evaluar_confianza([en_dominio, fuera_de_dominio])

    assert not revisar.descartar and revisar.nivel == "PARCIAL" and revisar.score == pytest.approx(0.65)
    assert descartar.descartar


def test_los_items_sin_valor_no_se_evaluan_ni_cuentan(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_similitud(monkeypatch, [0.01])
    plan = [_item("Detalle", "banco", hoja="H", fila=3, columna=1, valor=None, estado="APROBADO")]
    ctx = _ctx()

    refinado = refinar_plan(ctx, plan)

    assert refinado[0]["estado"] == "APROBADO" and ctx.metadatos["plausibilidad"] == {"descartados": [], "en_revision": []}
