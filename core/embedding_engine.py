"""Motor de Embeddings Semánticos para AutoForm AI.

Responsabilidad ÚNICA: calcular similitud semántica real entre textos usando
embeddings vectoriales de OpenAI (text-embedding-3-small), con caché en disco
y fallback graceful a rapidfuzz cuando la API no está disponible.

Ventaja clave sobre rapidfuzz:
  - "Entidad Financiera para Pagos" ↔ "banco" → similitud ALTA (significado)
  - "NIT/TAX ID" ↔ "nit" → similitud ALTA (mismo concepto)
  - rapidfuzz daría score bajo en ambos casos (palabras diferentes)

Uso:
    from core.embedding_engine import similitud_semantica

    score = similitud_semantica("Razón Social", "razon_social / nombre empresa")
    # → 0.0 a 100.0
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import List, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Dependencias opcionales: numpy + openai (ya en requirements.txt)
# ──────────────────────────────────────────────────────────────────────────────

try:
    import numpy as np
    _NUMPY_OK = True
except ImportError:
    np = None  # type: ignore
    _NUMPY_OK = False

try:
    import openai as _openai_lib
    _OPENAI_OK = True
except ImportError:
    _openai_lib = None  # type: ignore
    _OPENAI_OK = False

try:
    from rapidfuzz import fuzz as _fuzz
    _FUZZ_OK = True
except ImportError:
    _fuzz = None  # type: ignore
    _FUZZ_OK = False


# ──────────────────────────────────────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────────────────────────────────────

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_CACHE_FILE = Path("config") / "embedding_cache.json"

# Caché en memoria para la sesión actual (evita IO de disco repetida)
_cache_memoria: dict[str, List[float]] = {}
_cache_disco_cargado = False


def _cargar_api_key() -> Optional[str]:
    """Lee OPENAI_API_KEY desde entorno (o .env si está disponible)."""
    key = os.getenv("OPENAI_API_KEY", "")
    if key:
        return key
    # Intento manual de .env si python-dotenv no lo cargó
    env_path = Path(".env")
    if env_path.exists():
        try:
            with env_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("OPENAI_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Caché en disco
# ──────────────────────────────────────────────────────────────────────────────

def _hash_texto(texto: str) -> str:
    """SHA-256 de 16 caracteres del texto normalizado — clave de caché."""
    return hashlib.sha256(texto.lower().strip().encode("utf-8")).hexdigest()[:16]


def _asegurar_carga_disco() -> None:
    """Carga el caché de disco a memoria una sola vez por sesión."""
    global _cache_disco_cargado
    if _cache_disco_cargado:
        return
    _cache_disco_cargado = True
    if not _EMBEDDING_CACHE_FILE.exists():
        return
    try:
        with _EMBEDDING_CACHE_FILE.open("r", encoding="utf-8") as f:
            datos = json.load(f)
        for h, vec in datos.items():
            if isinstance(vec, list):
                _cache_memoria[h] = vec
    except Exception as e:
        print(f"[EmbeddingEngine] Aviso: no se pudo leer caché de disco ({e}).")


def _guardar_en_disco(hash_k: str, vector: List[float]) -> None:
    """Persiste un embedding nuevo en el caché de disco."""
    _EMBEDDING_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    datos: dict = {}
    if _EMBEDDING_CACHE_FILE.exists():
        try:
            with _EMBEDDING_CACHE_FILE.open("r", encoding="utf-8") as f:
                datos = json.load(f)
        except Exception:
            datos = {}
    datos[hash_k] = vector
    try:
        with _EMBEDDING_CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(datos, f, separators=(",", ":"), ensure_ascii=False)
    except Exception as e:
        print(f"[EmbeddingEngine] Aviso: no se pudo escribir caché de disco ({e}).")


# ──────────────────────────────────────────────────────────────────────────────
# Obtención de embeddings
# ──────────────────────────────────────────────────────────────────────────────

def get_embedding(texto: str) -> Optional[List[float]]:
    """Obtiene el vector de embedding para `texto`.

    1. Consulta caché en memoria (instantáneo).
    2. Consulta caché en disco (evita costo de API entre sesiones).
    3. Llama a OpenAI text-embedding-3-small (solo si no está en caché).
    4. Retorna None si todo falla (activa fallback a rapidfuzz).

    Args:
        texto: Texto a embedir. Puede ser una huella de formulario o un rótulo corto.

    Returns:
        Lista de floats (vector) o None si no está disponible.
    """
    if not texto or not texto.strip():
        return None

    _asegurar_carga_disco()
    hash_k = _hash_texto(texto)

    # 1. Caché en memoria
    if hash_k in _cache_memoria:
        return _cache_memoria[hash_k]

    # 2. Si no hay librerías o API key, abortar
    if not _OPENAI_OK or not _NUMPY_OK:
        return None

    api_key = _cargar_api_key()
    if not api_key:
        return None

    # 3. Llamada a OpenAI
    try:
        client = _openai_lib.OpenAI(api_key=api_key)
        respuesta = client.embeddings.create(
            model=_EMBEDDING_MODEL,
            input=texto.strip(),
        )
        vector: List[float] = respuesta.data[0].embedding

        # Guardar en ambos cachés
        _cache_memoria[hash_k] = vector
        _guardar_en_disco(hash_k, vector)
        return vector

    except Exception as e:
        print(f"[EmbeddingEngine] Error al obtener embedding (fallback a rapidfuzz): {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Similitud coseno
# ──────────────────────────────────────────────────────────────────────────────

def similitud_coseno(v1: List[float], v2: List[float]) -> float:
    """Similitud coseno entre dos vectores. Retorna valor entre 0.0 y 1.0."""
    if not _NUMPY_OK:
        return 0.0
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ──────────────────────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────────────────────

def similitud_semantica(texto_a: str, texto_b: str) -> float:
    """Calcula la similitud semántica entre dos textos en escala 0-100.

    Usa embeddings de OpenAI (text-embedding-3-small) cuando están disponibles.
    Cae automáticamente a rapidfuzz.token_sort_ratio si la API no responde
    o si las dependencias no están instaladas.

    Esta función es el reemplazo directo de:
        fuzz.token_sort_ratio(texto_a, texto_b)

    Args:
        texto_a: Primer texto (ej. huella del formulario entrante).
        texto_b: Segundo texto (ej. huella de una plantilla guardada).

    Returns:
        Score de similitud entre 0.0 y 100.0.
    """
    if not texto_a or not texto_b:
        return 0.0

    # Intentar embeddings semánticos
    vec_a = get_embedding(texto_a)
    vec_b = get_embedding(texto_b)

    if vec_a is not None and vec_b is not None:
        # Coseno está en [-1, 1]; text-embedding-3-small normaliza bien, típico [0, 1]
        cos = similitud_coseno(vec_a, vec_b)
        # Convertir a escala 0-100 (clipear al rango positivo)
        return max(0.0, min(100.0, cos * 100.0))

    # Fallback graceful a rapidfuzz
    if _FUZZ_OK and _fuzz is not None:
        return float(_fuzz.token_sort_ratio(texto_a, texto_b))

    # Último recurso: sin similitud
    return 0.0


def embeddings_disponibles() -> bool:
    """Retorna True si el motor de embeddings está operativo (API key + numpy + openai)."""
    if not _OPENAI_OK or not _NUMPY_OK:
        return False
    return bool(_cargar_api_key())
