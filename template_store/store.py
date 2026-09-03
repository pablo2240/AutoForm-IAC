"""Gestor de persistencia de plantillas de formularios (Template Store).

Almacena y recupera plantillas de formularios verificadas en formato JSON en `config/templates/`.
Permite que el sistema reconozca formularios previamente diligenciados o similares
sin requerir llamadas al LLM (0 latencia y 0 costo de API).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime
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


DEFAULT_TEMPLATES_DIR = Path("config") / "templates"
LEGACY_CACHE_FILE = Path("config") / "plantillas_cache.json"
CURRENT_ADR_VERSION = "0004"


def _normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparación y hashing insensible a acentos, mayúsculas y espacios."""
    if not texto:
        return ""
    # Quitar diacríticos/acentos
    nfd = "".join(
        c for c in unicodedata.normalize("NFD", str(texto).lower())
        if unicodedata.category(c) != "Mn"
    )
    # Reemplazar múltiples espacios o caracteres no alfanuméricos por un espacio
    limpio = re.sub(r"[\s_\.\:\-\;\,\(\)\[\]\/\\]+", " ", nfd).strip()
    return limpio


def calcular_hash_formulario(elementos: List[Dict[str, Any]]) -> str:
    """Genera un hash SHA-256 determinista de 16 caracteres para un conjunto de rótulos.
    
    Toma en cuenta la hoja, fila, columna y el texto normalizado de cada rótulo detectado.
    """
    if not elementos:
        return "empty_form_0000"

    items_para_hash = []
    for elem in elementos:
        hoja = str(elem.get("hoja", "")).strip().lower()
        fila = int(elem.get("fila", 0) or 0)
        col = int(elem.get("columna", 0) or 0)
        rotulo = _normalizar_texto(str(elem.get("valor") or elem.get("rotulo") or ""))
        if rotulo:
            items_para_hash.append(f"{hoja}:{fila}:{col}:{rotulo}")

    items_para_hash.sort()
    cadena_unida = "|".join(items_para_hash)
    hash_full = hashlib.sha256(cadena_unida.encode("utf-8")).hexdigest()
    return hash_full[:16]


def generar_huella_formulario(elementos: List[Dict[str, Any]]) -> str:
    """Construye una huella textual representativa de los rótulos principales del formulario.
    
    Se utiliza para búsqueda por similitud difusa (Fuzzy Matching).
    """
    rotulos = []
    for elem in elementos:
        txt = _normalizar_texto(str(elem.get("valor") or elem.get("rotulo") or ""))
        if txt and len(txt) > 2:
            rotulos.append(txt)
    return " ".join(rotulos)


def guardar_plantilla(
    plantilla_id: str,
    nombre_formulario: str,
    tipo_documento: str,
    elementos_raw: List[Dict[str, Any]],
    plan_mapeo: List[Dict[str, Any]],
    metadatos: Optional[Dict[str, Any]] = None,
    directorio: Path = DEFAULT_TEMPLATES_DIR,
) -> Path:
    """Guarda una plantilla de formulario verificada en el almacenamiento JSON en disco.
    
    Args:
        plantilla_id: Hash identificador de 16 caracteres.
        nombre_formulario: Nombre legible del archivo o formato.
        tipo_documento: 'excel' o 'pdf'.
        elementos_raw: Lista completa de elementos detectados en el formulario.
        plan_mapeo: Lista de diccionarios con el mapeo verificado (rotulo -> campo, fila, col, etc.).
        metadatos: Datos adicionales opcionales (autor, empresa, versión).
        directorio: Directorio de destino para los archivos JSON.
        
    Returns:
        Path del archivo JSON guardado.
    """
    directorio.mkdir(parents=True, exist_ok=True)
    archivo_json = directorio / f"{plantilla_id}.json"

    fecha_actual = datetime.utcnow().isoformat() + "Z"

    # Preservar fecha de creación si ya existía
    fecha_creacion = fecha_actual
    if archivo_json.exists():
        try:
            with open(archivo_json, "r", encoding="utf-8") as f:
                previo = json.load(f)
                fecha_creacion = previo.get("fecha_creacion", fecha_actual)
        except Exception:
            pass

    huella = generar_huella_formulario(elementos_raw)
    
    datos_plantilla = {
        "plantilla_id": plantilla_id,
        "adr_version": CURRENT_ADR_VERSION,
        "nombre_formulario": nombre_formulario,
        "tipo_documento": tipo_documento,
        "version": "1.0",
        "fecha_creacion": fecha_creacion,
        "fecha_actualizacion": fecha_actual,
        "huella": huella,
        "total_elementos": len(elementos_raw),
        "total_campos_mapeados": len(plan_mapeo),
        "plan_mapeo": plan_mapeo,
        "metadatos": metadatos or {},
    }

    with open(archivo_json, "w", encoding="utf-8") as f:
        json.dump(datos_plantilla, f, ensure_ascii=False, indent=2)

    return archivo_json


def cargar_plantilla(
    plantilla_id: str,
    directorio: Path = DEFAULT_TEMPLATES_DIR,
) -> Optional[Dict[str, Any]]:
    """Carga una plantilla específica desde el disco si existe y cumple con la versión de ADR."""
    archivo_json = directorio / f"{plantilla_id}.json"
    if not archivo_json.exists():
        return None

    try:
        with open(archivo_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Invalidación por versión de ADR (ADR-0004): descarta plantillas con mapeos obsoletos
            if str(data.get("adr_version", "")) < CURRENT_ADR_VERSION:
                print(f"[TemplateStore] ⚠️ Plantilla '{plantilla_id}' obsoleta (ADR < {CURRENT_ADR_VERSION}). Se re-procesará con IA.")
                return None
            return data
    except Exception as e:
        print(f"[TemplateStore] Error al leer plantilla '{plantilla_id}': {e}")
        return None


def buscar_plantilla_por_similitud(
    elementos_actuales: List[Dict[str, Any]],
    umbral: float = 85.0,
    directorio: Path = DEFAULT_TEMPLATES_DIR,
) -> Optional[Tuple[str, Dict[str, Any], float]]:
    """Busca en el almacén de plantillas una cuya huella tenga similitud semántica >= umbral.

    Usa embeddings de OpenAI (text-embedding-3-small) para comparar huellas.
    Si la API no está disponible, cae a rapidfuzz.token_sort_ratio automáticamente.

    Returns:
        Tuple: (plantilla_id, datos_plantilla, score_similitud) o None si no supera el umbral.
    """
    if not elementos_actuales:
        return None

    if not directorio.exists():
        return None

    huella_actual = generar_huella_formulario(elementos_actuales)
    if not huella_actual:
        return None

    # Seleccionar motor de similitud: embeddings semánticos → rapidfuzz como fallback
    if _similitud_semantica is not None:
        _fn_similitud = _similitud_semantica
    elif fuzz is not None:
        _fn_similitud = fuzz.token_sort_ratio  # type: ignore
    else:
        return None

    mejor_match: Optional[Tuple[str, Dict[str, Any], float]] = None
    mejor_score = 0.0

    for archivo in directorio.glob("*.json"):
        try:
            with open(archivo, "r", encoding="utf-8") as f:
                plantilla = json.load(f)

            # Invalidación por versión de ADR (ADR-0004)
            if str(plantilla.get("adr_version", "")) < CURRENT_ADR_VERSION:
                continue

            huella_guardada = plantilla.get("huella", "")
            if not huella_guardada:
                continue

            # Similitud semántica real (embeddings) o léxica (rapidfuzz) según disponibilidad
            score = float(_fn_similitud(huella_actual, huella_guardada))
            if score >= umbral and score > mejor_score:
                mejor_score = score
                mejor_match = (plantilla.get("plantilla_id", archivo.stem), plantilla, score)
        except Exception:
            continue

    return mejor_match


def adaptar_plan_a_formulario(
    elementos_actuales: List[Dict[str, Any]],
    plantilla_guardada: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Adapta las coordenadas del plan de la plantilla a las posiciones del formulario actual.
    
    Permite reutilizar plantillas incluso si el formulario tiene filas o columnas ligeramente desplazadas.
    """
    plan_base: List[Dict[str, Any]] = plantilla_guardada.get("plan_mapeo", [])
    if not plan_base:
        return []

    # Índice de búsqueda rápida por (hoja, rotulo_normalizado)
    indice_rotulos: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for elem in elementos_actuales:
        hoja = str(elem.get("hoja", "")).strip().lower()
        rot_norm = _normalizar_texto(str(elem.get("valor") or elem.get("rotulo") or ""))
        if rot_norm:
            indice_rotulos[(hoja, rot_norm)] = elem

    plan_adaptado: List[Dict[str, Any]] = []

    for item in plan_base:
        campo = item.get("campo")
        if not campo:
            continue

        hoja_orig = str(item.get("hoja", "")).strip().lower()
        rot_orig_norm = _normalizar_texto(str(item.get("valor") or item.get("rotulo") or ""))

        # 1. Búsqueda exacta en la misma hoja
        elem_encontrado = indice_rotulos.get((hoja_orig, rot_orig_norm))

        # 2. Si no coincide hoja exacta, buscar el rótulo en cualquier hoja
        if elem_encontrado is None:
            for (h, r), elem_cand in indice_rotulos.items():
                if r == rot_orig_norm:
                    elem_encontrado = elem_cand
                    break

        if elem_encontrado is not None:
            # Usar coordenadas físicas reales del nuevo formulario
            item_nuevo = dict(item)
            item_nuevo["hoja"] = elem_encontrado.get("hoja", item.get("hoja"))
            item_nuevo["fila"] = elem_encontrado.get("fila", item.get("fila"))
            item_nuevo["columna"] = elem_encontrado.get("columna", item.get("columna"))
            item_nuevo["valor"] = elem_encontrado.get("valor", item.get("valor"))
            if "anchoLinea" in elem_encontrado:
                item_nuevo["anchoLinea"] = elem_encontrado["anchoLinea"]
            plan_adaptado.append(item_nuevo)
        else:
            # Mantener las coordenadas originales de la plantilla si no se halló un desplazamiento
            plan_adaptado.append(dict(item))

    return plan_adaptado


def listar_plantillas(directorio: Path = DEFAULT_TEMPLATES_DIR) -> List[Dict[str, Any]]:
    """Retorna una lista con la metadata de todas las plantillas almacenadas."""
    if not directorio.exists():
        return []

    plantillas = []
    for archivo in sorted(directorio.glob("*.json")):
        try:
            with open(archivo, "r", encoding="utf-8") as f:
                data = json.load(f)
                plantillas.append({
                    "plantilla_id": data.get("plantilla_id", archivo.stem),
                    "nombre_formulario": data.get("nombre_formulario", "Sin nombre"),
                    "tipo_documento": data.get("tipo_documento", "desconocido"),
                    "fecha_creacion": data.get("fecha_creacion", ""),
                    "fecha_actualizacion": data.get("fecha_actualizacion", ""),
                    "total_campos_mapeados": data.get("total_campos_mapeados", len(data.get("plan_mapeo", []))),
                    "total_elementos": data.get("total_elementos", 0),
                    "ruta": str(archivo),
                })
        except Exception:
            continue

    return plantillas


def eliminar_plantilla(
    plantilla_id: str,
    directorio: Path = DEFAULT_TEMPLATES_DIR,
) -> bool:
    """Elimina una plantilla específica del disco."""
    archivo_json = directorio / f"{plantilla_id}.json"
    if archivo_json.exists():
        try:
            archivo_json.unlink()
            return True
        except Exception as e:
            print(f"[TemplateStore] Error al eliminar plantilla '{plantilla_id}': {e}")
            return False
    return False


def migrar_cache_legacy(
    archivo_legacy: Path = LEGACY_CACHE_FILE,
    directorio_destino: Path = DEFAULT_TEMPLATES_DIR,
) -> int:
    """Migra plantillas almacenadas en el archivo legacy `config/plantillas_cache.json`
    hacia archivos individuales en `config/templates/{id}.json`.
    
    Returns:
        Número de plantillas migradas exitosamente.
    """
    if not archivo_legacy.exists():
        return 0

    directorio_destino.mkdir(parents=True, exist_ok=True)
    migradas = 0

    try:
        with open(archivo_legacy, "r", encoding="utf-8") as f:
            contenido = json.load(f)

        if not isinstance(contenido, dict):
            return 0

        for pid, data in contenido.items():
            if not isinstance(data, dict):
                continue
            
            dest_file = directorio_destino / f"{pid}.json"
            if not dest_file.exists():
                plan_mapeo = data.get("plan_mapeo", [])
                nombre = data.get("nombre_formulario") or f"Formulario_{pid[:8]}"
                tipo = data.get("tipo_documento") or "excel"
                huella = data.get("huella", "")
                
                plantilla_export = {
                    "plantilla_id": pid,
                    "nombre_formulario": nombre,
                    "tipo_documento": tipo,
                    "version": "1.0",
                    "fecha_creacion": datetime.utcnow().isoformat() + "Z",
                    "fecha_actualizacion": datetime.utcnow().isoformat() + "Z",
                    "huella": huella,
                    "total_elementos": data.get("total_rotulos", len(plan_mapeo)),
                    "total_campos_mapeados": len(plan_mapeo),
                    "plan_mapeo": plan_mapeo,
                    "metadatos": {"migrado_de_legacy": True},
                }

                with open(dest_file, "w", encoding="utf-8") as out:
                    json.dump(plantilla_export, out, ensure_ascii=False, indent=2)
                migradas += 1

        if migradas > 0:
            print(f"[TemplateStore] Migradas {migradas} plantillas desde caché legacy hacia '{directorio_destino}'.")

    except Exception as e:
        print(f"[TemplateStore] Error durante la migración de caché legacy: {e}")

    return migradas


class TemplateStore:
    """Clase orientada a objetos para interactuar con el almacén de plantillas."""

    def __init__(self, directorio: Path = DEFAULT_TEMPLATES_DIR):
        self.directorio = Path(directorio)
        self.directorio.mkdir(parents=True, exist_ok=True)
        # Intentar migración de caché anterior de forma transparente
        migrar_cache_legacy(directorio_destino=self.directorio)

    def hash(self, elementos: List[Dict[str, Any]]) -> str:
        return calcular_hash_formulario(elementos)

    def guardar(
        self,
        plantilla_id: str,
        nombre_formulario: str,
        tipo_documento: str,
        elementos_raw: List[Dict[str, Any]],
        plan_mapeo: List[Dict[str, Any]],
        metadatos: Optional[Dict[str, Any]] = None,
    ) -> Path:
        return guardar_plantilla(
            plantilla_id=plantilla_id,
            nombre_formulario=nombre_formulario,
            tipo_documento=tipo_documento,
            elementos_raw=elementos_raw,
            plan_mapeo=plan_mapeo,
            metadatos=metadatos,
            directorio=self.directorio,
        )

    def cargar(self, plantilla_id: str) -> Optional[Dict[str, Any]]:
        return cargar_plantilla(plantilla_id=plantilla_id, directorio=self.directorio)

    def buscar_similar(
        self,
        elementos_actuales: List[Dict[str, Any]],
        umbral: float = 90.0,
    ) -> Optional[Tuple[str, Dict[str, Any], float]]:
        return buscar_plantilla_por_similitud(
            elementos_actuales=elementos_actuales,
            umbral=umbral,
            directorio=self.directorio,
        )

    def adaptar(
        self,
        elementos_actuales: List[Dict[str, Any]],
        plantilla: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        return adaptar_plan_a_formulario(elementos_actuales, plantilla)

    def listar(self) -> List[Dict[str, Any]]:
        return listar_plantillas(directorio=self.directorio)

    def eliminar(self, plantilla_id: str) -> bool:
        return eliminar_plantilla(plantilla_id=plantilla_id, directorio=self.directorio)
