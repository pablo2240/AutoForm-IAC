"""Índice vectorial en memoria (numpy) detrás de una interfaz pequeña y reemplazable.

Con decenas de miles de vectores de 384 dimensiones, un producto matricial exacto responde en
milisegundos, sin dependencias nativas, sin servicios externos y sin costo. Si la biblioteca
crece más allá de eso (o debe compartirse entre despliegues), basta otra implementación de
``IndiceVectorial`` (por ejemplo pgvector en Supabase) sin tocar la búsqueda ni el few-shot.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, Tuple

import numpy as np


class IndiceVectorial(Protocol):
    """Contrato de un índice de vectores normalizados identificados por un entero."""

    def __len__(self) -> int: ...

    def buscar(
        self,
        consulta: np.ndarray,
        top_k: int,
        permitidos: Optional[np.ndarray] = None,
    ) -> List[Tuple[int, float]]:
        """Los ``top_k`` ids más similares (coseno) a ``consulta``, de mayor a menor."""
        ...


class IndiceNumpy:
    """Búsqueda exacta por producto punto sobre una matriz de vectores ya normalizados."""

    def __init__(self, ids: np.ndarray, matriz: np.ndarray) -> None:
        if len(ids) != len(matriz):
            raise ValueError("ids y matriz deben tener la misma longitud.")
        self.ids = np.asarray(ids, dtype=np.int64)
        self.matriz = np.asarray(matriz, dtype=np.float32)

    def __len__(self) -> int:
        return len(self.ids)

    @classmethod
    def vacio(cls) -> "IndiceNumpy":
        return cls(np.zeros(0, dtype=np.int64), np.zeros((0, 1), dtype=np.float32))

    def buscar(
        self,
        consulta: np.ndarray,
        top_k: int,
        permitidos: Optional[np.ndarray] = None,
    ) -> List[Tuple[int, float]]:
        if len(self.ids) == 0 or top_k <= 0:
            return []
        similitudes = self.matriz @ np.asarray(consulta, dtype=np.float32)
        if permitidos is not None:
            similitudes = np.where(permitidos, similitudes, -np.inf)
        k = min(top_k, len(similitudes))
        candidatos = np.argpartition(-similitudes, k - 1)[:k]
        ordenados = candidatos[np.argsort(-similitudes[candidatos])]
        return [(int(self.ids[i]), float(similitudes[i])) for i in ordenados if np.isfinite(similitudes[i])]
