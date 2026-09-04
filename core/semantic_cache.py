"""Módulo de Caché Semántico de Plantillas y Similaridad (Fase B).

Utiliza rapidfuzz para identificar formularios idénticos o estructuralmente similares (score >= 90%),
permitiendo reutilizar planes de mapeo semántico en < 0.05s y $0 costo de API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None  # type: ignore

try:
    from core.embedding_engine import similitud_semantica as _similitud_semantica
except ImportError:
    _similitud_semantica = None  # type: ignore


CACHE_FILE = Path("config") / "plantillas_cache.json"


def _asegurar_directorio_config() -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)


def generar_huella_formulario(mapa_purgado: List[Dict[str, Any]]) -> str:
    """Genera una huella digital canónica (fingerprint) basada en los rótulos ordenados del formulario."""
    rotulos = []
    for entrada in mapa_purgado:
        val = str(entrada.get("valor", "")).strip().lower()
        if val:
            rotulos.append(val)
    rotulos.sort()
    return " | ".join(rotulos)


def cargar_cache_plantillas() -> Dict[str, Any]:
    """Carga las plantillas en caché desde el archivo de disco config/plantillas_cache.json."""
    if not CACHE_FILE.exists():
        return {}
    try:
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            cache = json.load(f)
        # Auto-purga: eliminar entradas con plan_mapeo vacío o inválido
        limpias = {
            k: v for k, v in cache.items()
            if isinstance(v.get("plan_mapeo"), list) and len(v["plan_mapeo"]) > 0
            and any(p.get("hoja") and int(p.get("fila", 0) or 0) > 0 for p in v["plan_mapeo"])
        }
        if len(limpias) < len(cache):
            descartadas = len(cache) - len(limpias)
            print(f"[AutoForm AI Cache] {descartadas} entradas invalidas eliminadas del cache semantico.")
            guardar_cache_plantillas(limpias)
        return limpias
    except Exception as exc:
        print(f"[AutoForm AI] Error leyendo cache de plantillas ({exc}). Reiniciando cache...")
        return {}


def guardar_cache_plantillas(cache_data: Dict[str, Any]) -> None:
    """Guarda el diccionario de plantillas en config/plantillas_cache.json."""
    _asegurar_directorio_config()
    try:
        with CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"[AutoForm AI] Error guardando caché de plantillas: {exc}")


def buscar_plantilla_similar(
    huella_entrante: str,
    umbral: float = 82.0,
) -> Optional[Tuple[str, Dict[str, Any], float]]:
    """Busca en el caché de plantillas la huella más parecida a huella_entrante.

    Usa embeddings semánticos de OpenAI si están disponibles, o rapidfuzz como fallback.

    Args:
        huella_entrante: Cadena canónica del formulario actual.
        umbral: Porcentaje mínimo de similitud (0 a 100). Por defecto 82.0%.

    Returns:
        Tuple[id_plantilla, datos_plantilla, score] o None si no supera el umbral.
    """
    # Seleccionar motor de similitud: embeddings semánticos → rapidfuzz como fallback
    if _similitud_semantica is not None:
        _fn_similitud = _similitud_semantica
    elif fuzz is not None:
        _fn_similitud = fuzz.token_sort_ratio  # type: ignore
    else:
        print("[AutoForm AI Warning] Sin motor de similitud disponible. Omitiendo Caché Semántico.")
        return None

    if not huella_entrante.strip():
        return None

    cache = cargar_cache_plantillas()
    if not cache:
        return None

    mejor_id: Optional[str] = None
    mejor_plantilla: Optional[Dict[str, Any]] = None
    mejor_score: float = 0.0

    for id_plantilla, datos in cache.items():
        huella_guardada = str(datos.get("huella", ""))
        if not huella_guardada:
            continue

        # Similitud semántica real (embeddings) o léxica (rapidfuzz) según disponibilidad
        score = float(_fn_similitud(huella_entrante, huella_guardada))
        if score > mejor_score:
            mejor_score = score
            mejor_id = id_plantilla
            mejor_plantilla = datos

    if mejor_score >= umbral and mejor_plantilla is not None and mejor_id is not None:
        return mejor_id, mejor_plantilla, mejor_score

    return None


def adaptar_mapeo_plantilla(
    mapa_formularios_entrante: List[Dict[str, Any]],
    plantilla_guardada: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Adapta las coordenadas físicas (hoja, fila, columna) de una plantilla guardada al nuevo formulario."""
    plan_guardado: List[Dict[str, Any]] = plantilla_guardada.get("plan_mapeo", [])
    if not plan_guardado:
        return []

    # Índice rápido del formulario entrante por (hoja, valor_limpio)
    indice_entrante: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for elem in mapa_formularios_entrante:
        hoja = str(elem.get("hoja", ""))
        val = str(elem.get("valor", "")).strip().lower()
        if (hoja, val) not in indice_entrante:
            indice_entrante[(hoja, val)] = elem

    plan_adaptado: List[Dict[str, Any]] = []
    for item in plan_guardado:
        hoja = str(item.get("hoja", ""))
        valor_rotulo = str(item.get("valor", "")).strip().lower()

        # Buscar coincidencia exacta de hoja y rótulo en el documento entrante
        coincidencia = indice_entrante.get((hoja, valor_rotulo))

        # Si no hay exacta, buscar por similaridad en la misma hoja
        if coincidencia is None and fuzz is not None:
            mejor_cand = None
            mejor_score = 0.0
            for elem in mapa_formularios_entrante:
                if str(elem.get("hoja", "")) == hoja:
                    cand_val = str(elem.get("valor", "")).strip().lower()
                    score = fuzz.ratio(valor_rotulo, cand_val)
                    if score > 85.0 and score > mejor_score:
                        mejor_score = score
                        mejor_cand = elem
            coincidencia = mejor_cand

        nuevo_item = dict(item)
        if coincidencia is not None:
            # Re-asignar coordenadas físicas del formulario entrante
            nuevo_item["fila"] = coincidencia.get("fila", item.get("fila"))
            nuevo_item["columna"] = coincidencia.get("columna", item.get("columna"))
            nuevo_item["hoja"] = coincidencia.get("hoja", item.get("hoja"))

        plan_adaptado.append(nuevo_item)

    return plan_adaptado


def guardar_plantilla_en_cache(
    id_plantilla: str,
    mapa_purgado: List[Dict[str, Any]],
    plan_mapeo: List[Dict[str, Any]],
) -> None:
    """Registra o actualiza una plantilla procesada en el archivo config/plantillas_cache.json.
    
    Solo guarda si el plan tiene entradas físicas válidas (hoja + fila + campo).
    """
    plan_valido = [
        p for p in plan_mapeo
        if p.get("hoja") and int(p.get("fila", 0) or 0) > 0 and p.get("campo")
    ]
    if not plan_valido:
        print(f"[AutoForm AI Cache] Omitiendo guardado: plan vacio o invalido para {id_plantilla}.")
        return

    huella = generar_huella_formulario(mapa_purgado)
    cache = cargar_cache_plantillas()

    cache[id_plantilla] = {
        "id": id_plantilla,
        "huella": huella,
        "total_rotulos": len(mapa_purgado),
        "plan_mapeo": plan_valido,
    }

    guardar_cache_plantillas(cache)


def eliminar_plantilla(id_plantilla: str) -> None:
    """Elimina una entrada del caché semántico por su ID."""
    try:
        cache = cargar_cache_plantillas()
        if id_plantilla in cache:
            del cache[id_plantilla]
            guardar_cache_plantillas(cache)
            print(f"[AutoForm AI Cache] Plantilla '{id_plantilla}' eliminada del cache semantico.")
    except Exception as exc:
        print(f"[AutoForm AI Cache] Error eliminando plantilla {id_plantilla}: {exc}")
