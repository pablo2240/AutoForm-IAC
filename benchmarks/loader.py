"""Cargador de datasets dorados de referencia (Ground Truth) para Benchmark."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from benchmarks.models import GroundTruthItem


class GroundTruthLoader:
    """Carga y valida los datasets de referencia espacial (Ground Truth)."""

    def __init__(self, ground_truth_dir: Optional[Path] = None):
        if ground_truth_dir is None:
            self.ground_truth_dir = Path(__file__).resolve().parent / "ground_truth"
        else:
            self.ground_truth_dir = Path(ground_truth_dir)

    def load_ground_truth(self, file_name_or_id: str) -> Tuple[List[GroundTruthItem], Dict[str, GroundTruthItem]]:
        """Carga el dataset de Ground Truth por nombre de archivo o ID.

        Returns:
            Tuple con (lista_de_items, mapa_por_clave_espacial).
        """
        # Si no tiene extensión .json, buscar por ID
        if not file_name_or_id.endswith(".json"):
            posible_path = self.ground_truth_dir / f"{file_name_or_id}_gt.json"
            if not posible_path.exists():
                posible_path = self.ground_truth_dir / f"{file_name_or_id}.json"
        else:
            posible_path = self.ground_truth_dir / file_name_or_id

        if not posible_path.exists():
            raise FileNotFoundError(f"No se encontró el dataset Ground Truth: {posible_path}")

        data = json.loads(posible_path.read_text(encoding="utf-8"))
        raw_elements = data.get("expected_elements", [])

        items: List[GroundTruthItem] = []
        mapa_espacial: Dict[str, GroundTruthItem] = {}

        for elem in raw_elements:
            gt_item = GroundTruthItem(
                hoja=str(elem.get("hoja", "")).strip(),
                fila=int(elem.get("fila", 0)),
                columna=int(elem.get("columna", 0)),
                rotulo_original=str(elem.get("rotulo_original") or elem.get("rotulo", "")).strip(),
                is_field=bool(elem.get("is_field", True)),
                expected_campo=str(elem.get("expected_campo", "")).strip(),
            )
            items.append(gt_item)
            mapa_espacial[gt_item.key] = gt_item

        return items, mapa_espacial
