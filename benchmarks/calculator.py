"""Calculador de métricas y KPIs estrictos de Benchmark (HSP Fase 5)."""

from typing import List
from benchmarks.models import (
    CategoriaResultado,
    BenchmarkResult,
    BenchmarkMetrics,
)


class MetricsCalculator:
    """Calcula las métricas de rendimiento y seguridad separando universos."""

    def calculate(
        self,
        resultados: List[BenchmarkResult],
        execution_time_seconds: float = 0.0,
    ) -> BenchmarkMetrics:
        """Calcula los KPIs a partir de la lista de BenchmarkResult clasificados."""
        total_campos_reales = 0
        total_no_campos = 0

        cnt_correcto_auto = 0
        cnt_correcto_revision = 0
        cnt_incorrecto = 0
        cnt_no_detectado = 0
        cnt_omitido_correcto = 0
        cnt_falso_positivo = 0

        for r in resultados:
            cat = r.categoria

            if cat == CategoriaResultado.CORRECTO_AUTO:
                cnt_correcto_auto += 1
                total_campos_reales += 1
            elif cat == CategoriaResultado.CORRECTO_REVISION:
                cnt_correcto_revision += 1
                total_campos_reales += 1
            elif cat == CategoriaResultado.INCORRECTO:
                cnt_incorrecto += 1
                total_campos_reales += 1
            elif cat == CategoriaResultado.NO_DETECTADO:
                cnt_no_detectado += 1
                total_campos_reales += 1
            elif cat == CategoriaResultado.OMITIDO_CORRECTAMENTE:
                cnt_omitido_correcto += 1
                total_no_campos += 1
            elif cat == CategoriaResultado.FALSO_POSITIVO:
                cnt_falso_positivo += 1
                if r.gt_item and not r.gt_item.is_field:
                    total_no_campos += 1
                elif r.gt_item is None:
                    total_no_campos += 1

        # ── KPIs de Negocio y Seguridad ──────────────────────────────────────
        
        # 1. Unsafe Automation Rate (Tasa de Automatización Insegura) -> DEBE SER 0.0%
        # Porcentaje de campos reales donde el sistema colocó un dato erróneo con confianza
        unsafe_automation_rate = (cnt_incorrecto / max(1, total_campos_reales)) * 100.0

        # 2. Precision (Precisión de Automatización)
        # De todos los campos que el sistema intentó llenar, cuántos fueron correctos
        total_intentos_llenado = cnt_correcto_auto + cnt_incorrecto + cnt_falso_positivo
        precision = (cnt_correcto_auto / max(1, total_intentos_llenado)) * 100.0

        # 3. Recall (Cobertura de Automatización)
        # De todos los campos reales, cuántos se llenaron automáticamente sin intervención
        recall = (cnt_correcto_auto / max(1, total_campos_reales)) * 100.0

        # 4. IR Filtering Rate (Efectividad del Filtro IR)
        # De todos los elementos no-campo (SI/NO, títulos, etc.), cuántos se descartaron limpiamente
        ir_filtering_rate = (cnt_omitido_correcto / max(1, total_no_campos)) * 100.0

        # 5. Safety Score (Índice de Seguridad Global)
        # Porcentaje de campos reales manejados con seguridad (aciertos automáticos + casos enviados a revisión)
        safety_score = ((cnt_correcto_auto + cnt_correcto_revision) / max(1, total_campos_reales)) * 100.0

        return BenchmarkMetrics(
            total_campos_reales=total_campos_reales,
            total_no_campos=total_no_campos,
            cnt_correcto_auto=cnt_correcto_auto,
            cnt_correcto_revision=cnt_correcto_revision,
            cnt_incorrecto=cnt_incorrecto,
            cnt_no_detectado=cnt_no_detectado,
            cnt_omitido_correcto=cnt_omitido_correcto,
            cnt_falso_positivo=cnt_falso_positivo,
            unsafe_automation_rate=round(unsafe_automation_rate, 2),
            precision=round(precision, 2),
            recall=round(recall, 2),
            ir_filtering_rate=round(ir_filtering_rate, 2),
            safety_score=round(safety_score, 2),
            execution_time_seconds=round(execution_time_seconds, 2),
        )
