"""Generador de reportes de Benchmark en consola, Markdown y JSON."""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from benchmarks.models import BenchmarkMetrics, BenchmarkResult, CategoriaResultado


class ReportGenerator:
    """Genera reportes legibles en consola, archivos Markdown y JSON estructurados."""

    def __init__(self, reports_dir: Optional[Path] = None):
        if reports_dir is None:
            self.reports_dir = Path(__file__).resolve().parent / "reports"
        else:
            self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def print_console_report(
        self,
        document_id: str,
        metrics: BenchmarkMetrics,
        regression_passed: bool,
        regression_msgs: List[str],
        deltas: Dict[str, float],
        resultados: Optional[List[BenchmarkResult]] = None,
    ):
        """Imprime un reporte visual formateado en la terminal."""
        print("\n" + "=" * 80)
        print(f"📊 AUTOFORM AI — REPORTE DE BENCHMARK & AUDITORÍA (HSP)")
        print(f"📄 Documento / Dataset: {document_id}")
        print(f"⏱️ Tiempo de ejecución: {metrics.execution_time_seconds:.2f}s")
        print("=" * 80)

        print("\n📦 DESGLOSE POR CATEGORÍA DE RESULTADO:")
        print(f"  🟢 Correctos Automáticamente:    {metrics.cnt_correcto_auto:3d}  ({metrics.recall:5.1f}% de campos reales)")
        print(f"  🟡 Correctos tras Revisión:       {metrics.cnt_correcto_revision:3d}  (Seguridad activa preventoria)")
        print(f"  ⚪ Omitidos Correctamente:        {metrics.cnt_omitido_correcto:3d}  ({metrics.ir_filtering_rate:5.1f}% de no-campos)")
        print(f"  🔴 Incorrectos (Error Crítico):   {metrics.cnt_incorrecto:3d}  ({metrics.unsafe_automation_rate:5.1f}% Unsafe Rate)")
        print(f"  🟠 Falsos Positivos:              {metrics.cnt_falso_positivo:3d}  (No-campos llenados indebidamente)")
        print(f"  🟣 No Detectados / Omitidos:      {metrics.cnt_no_detectado:3d}  (Campos reales no encontrados)")

        print("\n🎯 KPIS DE SEGURIDAD Y RENDIMIENTO:")
        print(f"  • Unsafe Automation Rate (🔴):    {metrics.unsafe_automation_rate:5.1f}%   (Meta: 0.0%)")
        print(f"  • Safety Score (🟢+🟡):           {metrics.safety_score:5.1f}%   (Campos manejados de forma segura)")
        print(f"  • Precision:                      {metrics.precision:5.1f}%   (Exactitud de automatización)")
        print(f"  • Recall (Cobertura):             {metrics.recall:5.1f}%   (Campos resueltos sin intervención)")
        print(f"  • IR Filtering Rate:              {metrics.ir_filtering_rate:5.1f}%   (Elementos no-campo descartados pre-LLM)")

        if deltas:
            print("\n📈 COMPARATIVA CONTRA BASELINE:")
            for k, v in deltas.items():
                signo = "+" if v >= 0 else ""
                print(f"  • {k}: {signo}{v:.2f}%")

        if regression_msgs:
            print("\n🔍 MENSAJES DE ANÁLISIS DE REGRESIÓN:")
            for m in regression_msgs:
                print(f"  {m}")

        # Listado detallado si hubo errores críticos o revisiones
        if resultados:
            errores = [r for r in resultados if r.categoria == CategoriaResultado.INCORRECTO]
            if errores:
                print("\n🚨 DETALLE DE ERRORES CRÍTICOS (🔴):")
                for err in errores:
                    rot = err.gt_item.rotulo_original if err.gt_item else "Desconocido"
                    exp = err.gt_item.expected_campo if err.gt_item else "?"
                    asig = err.pipeline_item.get("campo", "") if err.pipeline_item else "?"
                    print(f"  ❌ Rótulo: '{rot}' | Esperado: '{exp}' | Asignado: '{asig}' | {err.motivo_clasificacion}")

        print("\n" + "=" * 80)
        if regression_passed:
            print("✅ ESTADO GLOBAL: BENCHMARK PASSED (Cumple con estándares de seguridad)")
        else:
            print("❌ ESTADO GLOBAL: BENCHMARK FAILED (Se detectaron violaciones a los umbrales de seguridad)")
        print("=" * 80 + "\n")

    def save_json_report(
        self,
        document_id: str,
        metrics: BenchmarkMetrics,
        regression_passed: bool,
        deltas: Dict[str, float],
    ) -> Path:
        """Guarda un reporte estructurado en JSON con timestamp."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.reports_dir / f"benchmark_{document_id}_{ts}.json"
        
        data = {
            "document_id": document_id,
            "timestamp": datetime.now().isoformat(),
            "passed": regression_passed,
            "metrics": asdict(metrics),
            "deltas_vs_baseline": deltas,
        }
        report_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return report_path
