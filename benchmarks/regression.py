"""Analizador de regresiones para comparar ejecuciones contra el Baseline."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from benchmarks.models import BenchmarkMetrics


class RegressionAnalyzer:
    """Detecta degradaciones de seguridad o calidad respecto a una línea base guardada."""

    def __init__(self, reports_dir: Optional[Path] = None):
        if reports_dir is None:
            self.reports_dir = Path(__file__).resolve().parent / "reports"
        else:
            self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.baseline_path = self.reports_dir / "baseline.json"

    def load_baseline(self) -> Optional[Dict[str, Any]]:
        """Carga los datos del baseline guardado si existe."""
        if not self.baseline_path.exists():
            return None
        try:
            return json.loads(self.baseline_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_as_baseline(self, metrics: BenchmarkMetrics, document_id: str):
        """Guarda las métricas actuales como nuevo baseline de referencia."""
        data = {
            "document_id": document_id,
            "metrics": asdict(metrics),
        }
        self.baseline_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def analyze(
        self,
        current_metrics: BenchmarkMetrics,
    ) -> Tuple[bool, List[str], Dict[str, float]]:
        """Compara las métricas actuales contra el baseline y aplica las reglas de tolerancia.

        Reglas estrictas:
          - Regla 0 (Universal): Si cnt_incorrecto > 0 -> FALLA INMEDIATA (Unsafe Automation > 0%).
          - Regla 1 (Seguridad): Si unsafe_automation_rate aumentó -> FALLA.
          - Regla 2 (Precisión): Si precision cae > 2.0% -> FALLA.
          - Regla 3 (Cobertura): Si recall cae > 5.0% -> ADVERTENCIA.

        Returns:
            Tuple con (passed: bool, mensajes_error_o_warning: List[str], deltas: Dict[str, float]).
        """
        passed = True
        mensajes: List[str] = []
        deltas: Dict[str, float] = {}

        # ── REGLA CRÍTICA UNIVERSAL: Tolerancia Cero al Error Crítico ────────
        if current_metrics.cnt_incorrecto > 0:
            passed = False
            mensajes.append(
                f"🚨 FALLO CRÍTICO: Se detectaron {current_metrics.cnt_incorrecto} asignaciones incorrectas con alta confianza. "
                f"Unsafe Automation Rate = {current_metrics.unsafe_automation_rate}% (Meta: 0.0%)."
            )

        baseline_data = self.load_baseline()
        if baseline_data is None:
            mensajes.append("ℹ️ No existe baseline previo. Esta ejecución servirá de referencia inicial.")
            return passed, mensajes, deltas

        base_metrics = baseline_data.get("metrics", {})

        # Calcular deltas
        deltas["delta_unsafe_rate"] = current_metrics.unsafe_automation_rate - base_metrics.get("unsafe_automation_rate", 0.0)
        deltas["delta_precision"] = current_metrics.precision - base_metrics.get("precision", 0.0)
        deltas["delta_recall"] = current_metrics.recall - base_metrics.get("recall", 0.0)
        deltas["delta_ir_filtering"] = current_metrics.ir_filtering_rate - base_metrics.get("ir_filtering_rate", 0.0)
        deltas["delta_safety"] = current_metrics.safety_score - base_metrics.get("safety_score", 0.0)

        # Evaluar regresiones
        if deltas["delta_unsafe_rate"] > 0:
            passed = False
            mensajes.append(
                f"❌ REGRESIÓN DE SEGURIDAD: Unsafe Automation Rate aumentó de "
                f"{base_metrics.get('unsafe_automation_rate')}% a {current_metrics.unsafe_automation_rate}% (+{deltas['delta_unsafe_rate']:.2f}%)."
            )

        if deltas["delta_precision"] < -2.0:
            passed = False
            mensajes.append(
                f"❌ REGRESIÓN DE PRECISIÓN: Precision cayó de "
                f"{base_metrics.get('precision')}% a {current_metrics.precision}% ({deltas['delta_precision']:.2f}%)."
            )

        if deltas["delta_recall"] < -5.0:
            mensajes.append(
                f"⚠️ ADVERTENCIA DE COBERTURA: Recall cayó de "
                f"{base_metrics.get('recall')}% a {current_metrics.recall}% ({deltas['delta_recall']:.2f}%)."
            )

        if deltas["delta_ir_filtering"] < -5.0:
            mensajes.append(
                f"⚠️ ADVERTENCIA DE FILTRADO: IR Filtering Rate cayó de "
                f"{base_metrics.get('ir_filtering_rate')}% a {current_metrics.ir_filtering_rate}% ({deltas['delta_ir_filtering']:.2f}%)."
            )

        return passed, mensajes, deltas
