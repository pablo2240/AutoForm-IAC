"""Orquestador principal del Benchmark Engine para AutoForm AI (HSP Fase 5)."""

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from benchmarks.loader import GroundTruthLoader
from benchmarks.classifier import ResultClassifier
from benchmarks.calculator import MetricsCalculator
from benchmarks.regression import RegressionAnalyzer
from benchmarks.reporter import ReportGenerator
from benchmarks.models import BenchmarkMetrics, BenchmarkResult


class BenchmarkEngine:
    """Orquestador modular de pruebas de rendimiento, seguridad y regresión."""

    def __init__(
        self,
        ground_truth_dir: Optional[Path] = None,
        reports_dir: Optional[Path] = None,
    ):
        self.loader = GroundTruthLoader(ground_truth_dir)
        self.classifier = ResultClassifier()
        self.calculator = MetricsCalculator()
        self.regression = RegressionAnalyzer(reports_dir)
        self.reporter = ReportGenerator(reports_dir)

    def run_evaluation(
        self,
        document_id: str,
        pipeline_items: List[Dict[str, Any]],
        execution_time_seconds: float = 0.0,
        save_as_baseline: bool = False,
        show_console: bool = True,
    ) -> Tuple[bool, BenchmarkMetrics, List[BenchmarkResult]]:
        """Ejecuta la evaluación de una lista de resultados de mapeo contra el Ground Truth.

        Args:
            document_id: Identificador del dataset (ej: 'FMCA07J').
            pipeline_items: Lista de asignaciones generadas por el pipeline.
            execution_time_seconds: Tiempo total transcurrido.
            save_as_baseline: Si True, guarda la corrida como nueva referencia baseline.
            show_console: Si True, imprime el reporte formateado en terminal.

        Returns:
            Tuple con (passed: bool, metrics: BenchmarkMetrics, results: List[BenchmarkResult]).
        """
        # 1. Cargar Ground Truth
        gt_items, _ = self.loader.load_ground_truth(document_id)

        # 2. Clasificar cada elemento en las 6 categorías
        resultados = self.classifier.classify(gt_items, pipeline_items)

        # 3. Calcular KPIs y métricas de seguridad
        metrics = self.calculator.calculate(resultados, execution_time_seconds=execution_time_seconds)

        # 4. Análisis de regresión contra Baseline
        passed, mensajes, deltas = self.regression.analyze(metrics)

        # 5. Guardar como baseline si fue solicitado
        if save_as_baseline and passed:
            self.regression.save_as_baseline(metrics, document_id)

        # 6. Generar reportes
        if show_console:
            self.reporter.print_console_report(
                document_id=document_id,
                metrics=metrics,
                regression_passed=passed,
                regression_msgs=mensajes,
                deltas=deltas,
                resultados=resultados,
            )

        self.reporter.save_json_report(document_id, metrics, passed, deltas)

        return passed, metrics, resultados
