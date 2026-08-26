"""Clasificador estricto de resultados de Benchmark contra Ground Truth."""

from typing import Any, Dict, List, Set, Tuple
from benchmarks.models import (
    CategoriaResultado,
    GroundTruthItem,
    BenchmarkResult,
)


class ResultClassifier:
    """Clasifica los resultados del pipeline en las 6 categorías de evaluación."""

    @staticmethod
    def _clave_espacial(hoja: str, fila: int, col: int) -> str:
        return f"{str(hoja).strip()}_{int(fila)}_{int(col)}"

    def classify(
        self,
        gt_items: List[GroundTruthItem],
        pipeline_items: List[Dict[str, Any]],
    ) -> List[BenchmarkResult]:
        """Compara la salida del pipeline contra el Ground Truth y clasifica cada elemento.

        Args:
            gt_items: Lista de elementos de referencia Ground Truth.
            pipeline_items: Lista de asignaciones generadas por el pipeline (plan_mapeo).

        Returns:
            Lista de BenchmarkResult con la categoría y motivo exactos.
        """
        # Indexar pipeline_items por clave espacial
        pipeline_map: Dict[str, Dict[str, Any]] = {}
        for p in pipeline_items:
            h = str(p.get("hoja", "")).strip()
            f = int(p.get("fila", 0))
            c = int(p.get("columna", 0))
            pipeline_map[self._clave_espacial(h, f, c)] = p

        resultados: List[BenchmarkResult] = []
        elementos_gt_procesados: Set[str] = set()

        for gt in gt_items:
            key = gt.key
            elementos_gt_procesados.add(key)
            pipe_item = pipeline_map.get(key)

            if gt.is_field:
                # ── Universo 1: Campos Reales ──────────────────────────────
                if pipe_item is None:
                    # No llegó al plan de mapeo
                    resultados.append(
                        BenchmarkResult(
                            gt_item=gt,
                            pipeline_item=None,
                            categoria=CategoriaResultado.NO_DETECTADO,
                            motivo_clasificacion="Campo real omitido: no apareció en el plan de salida del pipeline.",
                        )
                    )
                else:
                    campo_asignado = str(pipe_item.get("campo", "")).strip()
                    estado = str(pipe_item.get("estado", "APROBADO")).strip().upper()

                    if estado == "DESCARTADO" or not campo_asignado or campo_asignado == "-- Omitir / Dejar vacío --":
                        resultados.append(
                            BenchmarkResult(
                                gt_item=gt,
                                pipeline_item=pipe_item,
                                categoria=CategoriaResultado.NO_DETECTADO,
                                motivo_clasificacion=f"Campo real marcado como DESCARTADO/vacío por el pipeline (Motivo: {pipe_item.get('motivo', '')}).",
                            )
                        )
                    elif estado == "REVISION":
                        # Seguridad activa: el sistema dudó y pidió revisión
                        resultados.append(
                            BenchmarkResult(
                                gt_item=gt,
                                pipeline_item=pipe_item,
                                categoria=CategoriaResultado.CORRECTO_REVISION,
                                motivo_clasificacion=f"Seguridad activa: campo ambiguo o no exacto enviado a revisión preventiva ({pipe_item.get('motivo', '')}).",
                            )
                        )
                    elif estado == "APROBADO":
                        if campo_asignado == gt.expected_campo:
                            resultados.append(
                                BenchmarkResult(
                                    gt_item=gt,
                                    pipeline_item=pipe_item,
                                    categoria=CategoriaResultado.CORRECTO_AUTO,
                                    motivo_clasificacion=f"Asignación exacta y segura a '{campo_asignado}' con alta confianza.",
                                )
                            )
                        else:
                            # ERROR CRÍTICO: Asignó dato erróneo con estado APROBADO
                            resultados.append(
                                BenchmarkResult(
                                    gt_item=gt,
                                    pipeline_item=pipe_item,
                                    categoria=CategoriaResultado.INCORRECTO,
                                    motivo_clasificacion=(
                                        f"¡ERROR CRÍTICO! Asignó '{campo_asignado}' con confianza pero se esperaba '{gt.expected_campo}'."
                                    ),
                                )
                            )
                    else:
                        # Estado desconocido o por defecto
                        if campo_asignado == gt.expected_campo:
                            resultados.append(
                                BenchmarkResult(
                                    gt_item=gt,
                                    pipeline_item=pipe_item,
                                    categoria=CategoriaResultado.CORRECTO_AUTO,
                                    motivo_clasificacion=f"Asignado a '{campo_asignado}'.",
                                )
                            )
                        else:
                            resultados.append(
                                BenchmarkResult(
                                    gt_item=gt,
                                    pipeline_item=pipe_item,
                                    categoria=CategoriaResultado.INCORRECTO,
                                    motivo_clasificacion=f"Asignó '{campo_asignado}' vs esperado '{gt.expected_campo}'.",
                                )
                            )

            else:
                # ── Universo 2: No-Campos (SI/NO, títulos, legal, etc.) ────
                if pipe_item is None:
                    # Descartado pre-LLM o no mapeado -> ÉXITO
                    resultados.append(
                        BenchmarkResult(
                            gt_item=gt,
                            pipeline_item=None,
                            categoria=CategoriaResultado.OMITIDO_CORRECTAMENTE,
                            motivo_clasificacion="Elemento no-campo descartado correctamente (no llegó al plan).",
                        )
                    )
                else:
                    campo_asignado = str(pipe_item.get("campo", "")).strip()
                    estado = str(pipe_item.get("estado", "")).strip().upper()

                    if estado == "DESCARTADO" or not campo_asignado or campo_asignado == "-- Omitir / Dejar vacío --":
                        resultados.append(
                            BenchmarkResult(
                                gt_item=gt,
                                pipeline_item=pipe_item,
                                categoria=CategoriaResultado.OMITIDO_CORRECTAMENTE,
                                motivo_clasificacion="Elemento no-campo identificado y descartado por el validador.",
                            )
                        )
                    else:
                        # FALSO POSITIVO: Asignó un campo a algo que NO es un campo
                        resultados.append(
                            BenchmarkResult(
                                gt_item=gt,
                                pipeline_item=pipe_item,
                                categoria=CategoriaResultado.FALSO_POSITIVO,
                                motivo_clasificacion=(
                                    f"Falso Positivo: se intentó llenar el no-campo '{gt.rotulo_original}' con '{campo_asignado}'."
                                ),
                            )
                        )

        # Verificar si hubo elementos en el pipeline que no estaban en el Ground Truth
        for key, p in pipeline_map.items():
            if key not in elementos_gt_procesados:
                campo_asig = str(p.get("campo", "")).strip()
                if campo_asig and p.get("estado") != "DESCARTADO":
                    resultados.append(
                        BenchmarkResult(
                            gt_item=None,
                            pipeline_item=p,
                            categoria=CategoriaResultado.FALSO_POSITIVO,
                            motivo_clasificacion=f"Elemento no registrado en GT fue asignado a '{campo_asig}'.",
                        )
                    )

        return resultados
