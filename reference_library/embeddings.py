"""Proveedores de embeddings intercambiables para la búsqueda semántica de referencias.

La biblioteca no depende de un proveedor concreto: cualquiera que cumpla ``ProveedorEmbeddings``
sirve. Por defecto se usa el modelo local multilingüe de FastEmbed (ya presente en el proyecto,
sin costo ni llamadas de red); OpenAI es opcional y ``hash`` es un respaldo léxico que nunca falla.

Selección: variable ``AUTOFORM_EMBEDDING_PROVIDER`` = ``fastembed`` | ``openai`` | ``hash``.
Cada vector se guarda junto con el nombre del proveedor, de modo que cambiar de proveedor
reindexa en vez de mezclar espacios vectoriales distintos.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import List, Optional, Protocol, Sequence

import numpy as np


class ProveedorNoDisponible(RuntimeError):
    """El proveedor no puede generar embeddings en este entorno."""


class ProveedorEmbeddings(Protocol):
    """Contrato mínimo de un proveedor: nombre estable y vectores normalizados (L2)."""

    nombre: str

    def embed(self, textos: Sequence[str]) -> np.ndarray:
        """Devuelve una matriz (n, dim) float32 con cada fila normalizada."""
        ...


def _normalizar_filas(matriz: np.ndarray) -> np.ndarray:
    matriz = np.asarray(matriz, dtype=np.float32)
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return matriz / normas


class FastEmbedProvider:
    """Modelo local multilingüe (CPU), reutilizando el singleton del rescate vectorial existente."""

    nombre = "fastembed:paraphrase-multilingual-MiniLM-L12-v2"

    def embed(self, textos: Sequence[str]) -> np.ndarray:
        from core.fastembed_matcher import _obtener_modelo

        modelo = _obtener_modelo()
        if modelo is None:
            raise ProveedorNoDisponible("No se pudo cargar el modelo FastEmbed.")
        if not textos:
            return np.zeros((0, 384), dtype=np.float32)
        return _normalizar_filas(np.array(list(modelo.embed(list(textos)))))


class OpenAIProvider:
    """Embeddings de OpenAI mediante el motor existente (con su caché en disco)."""

    nombre = "openai:text-embedding-3-small"

    def embed(self, textos: Sequence[str]) -> np.ndarray:
        from core.embedding_engine import embeddings_disponibles, get_embedding

        if not embeddings_disponibles():
            raise ProveedorNoDisponible("OpenAI no está configurado (OPENAI_API_KEY).")
        vectores = []
        for texto in textos:
            vector = get_embedding(texto)
            if vector is None:
                raise ProveedorNoDisponible("OpenAI no devolvió un embedding.")
            vectores.append(vector)
        return _normalizar_filas(np.array(vectores)) if vectores else np.zeros((0, 1536), dtype=np.float32)


class HashingProvider:
    """Embedding léxico determinista por n-gramas de caracteres; sin modelo ni red."""

    DIMENSION = 512
    nombre = f"hash-ngram-{DIMENSION}"

    def embed(self, textos: Sequence[str]) -> np.ndarray:
        matriz = np.zeros((len(textos), self.DIMENSION), dtype=np.float32)
        for fila, texto in enumerate(textos):
            limpio = re.sub(r"\s+", " ", f" {str(texto).lower().strip()} ")
            for n in (3, 4):
                for i in range(len(limpio) - n + 1):
                    digest = hashlib.md5(limpio[i:i + n].encode("utf-8")).digest()
                    matriz[fila, int.from_bytes(digest[:4], "little") % self.DIMENSION] += 1.0
        return _normalizar_filas(matriz)


_PROVEEDORES = {
    "fastembed": FastEmbedProvider,
    "openai": OpenAIProvider,
    "hash": HashingProvider,
}


def obtener_proveedor(nombre: Optional[str] = None) -> ProveedorEmbeddings:
    """Proveedor configurado; si el elegido no está disponible cae al respaldo léxico con aviso."""
    elegido = (nombre or os.getenv("AUTOFORM_EMBEDDING_PROVIDER", "fastembed")).strip().lower()
    clase = _PROVEEDORES.get(elegido)
    if clase is None:
        raise ValueError(f"Proveedor de embeddings desconocido: '{elegido}'. Opciones: {', '.join(_PROVEEDORES)}.")
    proveedor = clase()
    if elegido == "hash":
        return proveedor
    try:
        proveedor.embed(["prueba"])
        return proveedor
    except ProveedorNoDisponible as exc:
        print(f"[ReferenceLibrary] Proveedor '{elegido}' no disponible ({exc}); se usa respaldo léxico 'hash'.")
        return HashingProvider()
