"""Stage 3c: plausibilidad (A1) y confianza honesta (A2) sobre el plan de mapeo.

Se ejecuta sobre el plan ya validado, antes de filtrar lo descartado:
  * A1 descarta las asignaciones a textos que no son campos de captura (instrucciones, preguntas, opciones,
    celdas con marca de casilla, rótulos que ya traen el valor).
  * A2 reemplaza la confianza automática por un puntaje con evidencia; lo que solo respalda el LLM y no guarda
    relación con el campo se descarta, y lo dudoso queda marcado "Requiere revisión".

Es opcional y nunca debe impedir procesar el formulario: ante cualquier error el plan queda como estaba.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core.confianza_mapeo import evaluar_confianza, nivel_para
from core.plausibilidad import evaluar_plausibilidad
from pipeline.context import PipelineContext

UMBRAL_REVISION = 0.75  # por debajo, la asignación se marca "Requiere revisión"


def _indice_elementos(ctx: PipelineContext) -> Dict[Tuple[str, int, int], Dict[str, Any]]:
    elementos = ctx.elementos_clasificados or ctx.elementos_raw or []
    return {
        (str(e.get("hoja", "")), int(e.get("fila", 0) or 0), int(e.get("columna", 0) or 0)): e for e in elementos
    }


def _valor_destino(ctx: PipelineContext, item: Dict[str, Any]) -> Any:
    insp = ctx.inspeccion_excel
    if insp is None or not item.get("fila_destino") or not item.get("columna_destino"):
        return None
    try:
        return insp.obtener_valor_anterior(str(item.get("hoja") or ""), int(item["fila_destino"]), int(item["columna_destino"]))
    except Exception:
        return None


def _sin_valor(item: Dict[str, Any]) -> bool:
    return item.get("valor") in (None, "") and item.get("valor_a_escribir") in (None, "")


def _descartar(item: Dict[str, Any], motivo: str) -> None:
    item["estado"] = "DESCARTADO"
    item["motivo"] = motivo
    item["nivel_confianza"] = "SIN_COINCIDENCIA"
    item["confianza"] = 0.0
    item["confianza_score"] = 0.0


def _referencia_validada():
    """Consulta opcional a la biblioteca de referencias; None si no está disponible."""
    try:
        from reference_library.service import obtener_servicio

        servicio = obtener_servicio()
        if servicio is None or not servicio.listo:
            return None

        def _consulta(rotulo: str, campo: str) -> bool:
            if not rotulo:
                return False
            resultados = servicio.buscador.buscar(rotulo, top_k=1, solo_validados=True)
            return bool(resultados) and resultados[0].campo_maestro == campo and resultados[0].similitud >= 0.85

        return _consulta
    except Exception:
        return None


def refinar_plan(ctx: PipelineContext, plan: List[Dict[str, Any]], es_plantilla: bool = False) -> List[Dict[str, Any]]:
    """Aplica A1 (siempre) y A2 (salvo plantillas ya verificadas) al plan; devuelve el plan refinado."""
    if not plan:
        return plan
    try:
        elementos = _indice_elementos(ctx)
        descartados: List[Dict[str, Any]] = []
        en_revision: List[Dict[str, Any]] = []

        for item in plan:
            if str(item.get("estado", "")).upper() == "DESCARTADO" or item.get("sobrescribir_valor_previo"):
                continue
            if _sin_valor(item):
                continue  # el filtro final lo retirará: no cuenta ni se evalúa
            elemento = elementos.get(
                (str(item.get("hoja", "")), int(item.get("fila", 0) or 0), int(item.get("columna", 0) or 0)), {}
            )
            rotulo = item.get("rotulo_original") or item.get("rotulo")
            veredicto = evaluar_plausibilidad(rotulo, _valor_destino(ctx, item), str(elemento.get("tipo_clasificacion", "")))
            if not veredicto.plausible:
                _descartar(item, f"Plausibilidad [{veredicto.regla}]: {veredicto.motivo}")
                descartados.append({"rotulo": str(rotulo or ""), "campo": item.get("campo"), "regla": veredicto.regla})

        if not es_plantilla:
            vigentes = [
                i for i in plan
                if str(i.get("estado", "")).upper() != "DESCARTADO" and not i.get("sobrescribir_valor_previo") and not _sin_valor(i)
            ]
            evaluaciones = evaluar_confianza(vigentes, _referencia_validada())
            for item, evaluacion in zip(vigentes, evaluaciones):
                if evaluacion.descartar:
                    _descartar(item, f"Confianza: {evaluacion.motivo}")
                    descartados.append({"rotulo": str(item.get("rotulo") or ""), "campo": item.get("campo"), "regla": "A2"})
                    continue
                item["confianza_score"] = evaluacion.score
                item["confianza"] = evaluacion.score
                item["nivel_confianza"] = nivel_para(evaluacion.score)
                if evaluacion.score < UMBRAL_REVISION:
                    item["estado"] = "REVISION"
                    item["motivo"] = evaluacion.motivo
                    en_revision.append({"rotulo": str(item.get("rotulo") or ""), "campo": item.get("campo"), "score": evaluacion.score})

        ctx.metadatos["plausibilidad"] = {"descartados": descartados, "en_revision": en_revision}
        if descartados or en_revision:
            ctx.log(
                f"[Stage 3c - Plausibilidad] {len(descartados)} asignaciones descartadas por no ser campos o no tener "
                f"relación con el campo; {len(en_revision)} quedan en revisión."
            )
    except Exception as exc:  # una mejora opcional nunca debe impedir procesar el formulario
        ctx.log(f"[Stage 3c - Plausibilidad] Omitida: {type(exc).__name__}: {exc}")
    return plan
