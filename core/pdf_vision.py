"""Motor PDF v2: Visión LLM, OCR ligero, detección de tipo y validación visual.

Complementa `pdf_processor.py` con:
- `detectar_tipo_pdf`: clasifica el PDF como 'digital', 'escaneado' o 'mixto'.
- `detectar_campos_vision_llm`: localiza campos con visión LLM página por página.
- `construir_mapa_desde_ocr`: genera un mapa de inyección para escaneados con OCR ligero.
- `validar_relleno_vision`: valida el PDF relleno con visión LLM y auto-corrige bboxes.
"""

from __future__ import annotations

import copy
import io
import json
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore

from core import pdf_processor
from core.llm_client import consultar_llm_vision, invocar_llm_vision
from core.schema_models import AdvertenciaValidacion, CampoVision

_OCR_ENGINE: Any = None


# ---------------------------------------------------------------------------
# Detección de tipo de PDF
# ---------------------------------------------------------------------------
def detectar_tipo_pdf(bytes_pdf: bytes) -> Dict[str, Any]:
    """Clasifica un PDF como 'digital', 'escaneado' o 'mixto'.

    Se considera página digital si tiene >= 50 caracteres de texto seleccionable;
    las páginas sin texto con imágenes se consideran escaneadas.
    """
    try:
        doc = fitz.open(stream=bytes_pdf, filetype="pdf")
        paginas: List[Dict[str, Any]] = []
        n_digital = 0
        n_escaneada = 0

        for n in range(len(doc)):
            page = doc.load_page(n)
            chars = len(page.get_text("text").strip())
            tiene_imagenes = len(page.get_images(full=True)) > 0
            digital = chars >= 20
            paginas.append({
                "pagina": n + 1,
                "chars": chars,
                "imagenes": tiene_imagenes,
                "digital": digital,
            })
            if digital:
                n_digital += 1
            else:
                n_escaneada += 1

        es_form = doc.is_form_pdf
        total = len(paginas)
        doc.close()

        if total == 0 or n_escaneada == 0:
            tipo = "digital"
        elif n_digital == 0:
            tipo = "escaneado"
        else:
            tipo = "mixto"

        return {
            "tipo": tipo,
            "total_paginas": total,
            "paginas": paginas,
            "es_acroform": es_form,
        }
    except Exception as e:
        print(f"[AutoForm AI Vision] Error al detectar tipo de PDF: {e}")
        return {"tipo": "digital", "total_paginas": 0, "paginas": [], "es_acroform": False}


# ---------------------------------------------------------------------------
# Helpers de renderizado y coordenadas
# ---------------------------------------------------------------------------
def _renderizar_pagina_png(bytes_pdf: bytes, page_idx: int, dpi: int = 150) -> Optional[bytes]:
    """Renderiza una página específica del PDF como PNG en memoria."""
    try:
        doc = fitz.open(stream=bytes_pdf, filetype="pdf")
        if page_idx < 0 or page_idx >= len(doc):
            doc.close()
            return None
        page = doc.load_page(page_idx)
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img_bytes = pix.tobytes("png")
        doc.close()
        return img_bytes
    except Exception as e:
        print(f"[AutoForm AI Vision] Error al renderizar página {page_idx}: {e}")
        return None


def _rect_a_bbox1000(rect: Tuple[float, float, float, float], ancho: float, alto: float) -> List[int]:
    """Convierte un rect físico (x0, y0, x1, y1) a bbox normalizado [ymin, xmin, ymax, xmax] 0-1000."""
    x0, y0, x1, y1 = rect
    return [
        int(round((y0 / alto) * 1000)),
        int(round((x0 / ancho) * 1000)),
        int(round((y1 / alto) * 1000)),
        int(round((x1 / ancho) * 1000)),
    ]


# ---------------------------------------------------------------------------
# OCR ligero (RapidOCR, import opcional)
# ---------------------------------------------------------------------------
def _intentar_cargar_ocr() -> bool:
    """Carga el motor RapidOCR de forma perezosa. Retorna False si no está disponible."""
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return True
    try:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
        return True
    except Exception as e:
        print(f"[AutoForm AI OCR] No se pudo cargar RapidOCR (flujo de respaldo: visión LLM): {e}")
        return False


def _ocr_pagina_png(img_bytes: bytes) -> List[Dict[str, Any]]:
    """Ejecuta OCR sobre un PNG y devuelve palabras con cajas (en píxeles de la imagen)."""
    global _OCR_ENGINE
    if _OCR_ENGINE is None and not _intentar_cargar_ocr():
        return []

    try:
        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        arr = np.array(img)
        result, _ = _OCR_ENGINE(arr)
        palabras: List[Dict[str, Any]] = []
        if result:
            for box, text, conf in result:
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                palabras.append({
                    "text": str(text),
                    "x0": float(min(xs)),
                    "y0": float(min(ys)),
                    "x1": float(max(xs)),
                    "y1": float(max(ys)),
                    "conf": float(conf),
                })
        return palabras
    except Exception as e:
        print(f"[AutoForm AI OCR] Error en OCR de página: {e}")
        return []


def _append_item_ocr(
    mapa: List[Dict[str, Any]],
    n_pag: int,
    frase: str,
    x0_i: float,
    y_top: float,
    x1_f: float,
    y_bot: float,
    ancho_pts: float,
) -> None:
    """Construye una entrada de mapa con formato compatible con `escanear_mapa_pdf`."""
    alto_fuente = max(8.0, y_bot - y_top)
    x1_limite = min(x1_f + 280, ancho_pts - 20)
    if x1_limite <= (x1_f + 10):
        x1_limite = min(x0_i + 200, ancho_pts - 15)

    target_rect = (x1_f + 5, y_top, x1_limite, y_bot + (alto_fuente * 0.25))

    mapa.append({
        "hoja": f"Pagina_{n_pag + 1}",
        "fila": int(y_top),
        "columna": int(x0_i),
        "valor": frase.strip(),
        "_pdf_page": n_pag,
        "_pdf_bbox": (x0_i, y_top, x1_f, y_bot),
        "_pdf_target_rect": target_rect,
        "_pdf_es_caja": False,
        "_pdf_es_casilla": False,
    })


def construir_mapa_desde_ocr(bytes_pdf: bytes, dpi: int = 200) -> List[Dict[str, Any]]:
    """Genera un mapa de inyección para PDFs escaneados usando OCR ligero (RapidOCR).

    Produce entradas con el mismo formato que `escanear_mapa_pdf` para que el flujo de
    mapeo semántico y relleno funcione igual. Si RapidOCR no está instalado, retorna
    lista vacía (el flujo debe caer en visión LLM).
    """
    t0 = time.perf_counter()
    mapa_bruto: List[Dict[str, Any]] = []

    if _OCR_ENGINE is None and not _intentar_cargar_ocr():
        print("[AutoForm AI OCR] RapidOCR no disponible; saltando OCR.")
        return []

    try:
        doc = fitz.open(stream=bytes_pdf, filetype="pdf")
        for n_pag in range(len(doc)):
            page = doc.load_page(n_pag)
            ancho_pts = page.rect.width

            img = _renderizar_pagina_png(bytes_pdf, n_pag, dpi=dpi)
            if not img:
                continue

            palabras_px = _ocr_pagina_png(img)
            if not palabras_px:
                continue

            escala = 72.0 / dpi
            palabras = [
                {
                    "text": w["text"],
                    "x0": w["x0"] * escala,
                    "y0": w["y0"] * escala,
                    "x1": w["x1"] * escala,
                    "y1": w["y1"] * escala,
                }
                for w in palabras_px
            ]

            # Agrupar palabras en líneas por posición vertical
            lineas: Dict[int, List[Dict[str, Any]]] = {}
            for p in palabras:
                y_key = round(p["y0"] / 5) * 5
                lineas.setdefault(y_key, []).append(p)

            for y_key in sorted(lineas.keys()):
                linea = sorted(lineas[y_key], key=lambda w: w["x0"])
                frase = ""
                x0_i = None
                y_top = None
                y_bot = None
                x1_f = None

                for w in linea:
                    if not frase:
                        frase = w["text"]
                        x0_i = w["x0"]
                        y_top = w["y0"]
                        y_bot = w["y1"]
                        x1_f = w["x1"]
                    elif (w["x0"] - x1_f) < 15:
                        frase += " " + w["text"]
                        x1_f = w["x1"]
                        y_top = min(y_top, w["y0"])
                        y_bot = max(y_bot, w["y1"])
                    else:
                        _append_item_ocr(mapa_bruto, n_pag, frase, x0_i, y_top, x1_f, y_bot, ancho_pts)
                        frase = w["text"]
                        x0_i = w["x0"]
                        y_top = w["y0"]
                        y_bot = w["y1"]
                        x1_f = w["x1"]

                if frase:
                    _append_item_ocr(mapa_bruto, n_pag, frase, x0_i, y_top, x1_f, y_bot, ancho_pts)

        doc.close()
    except Exception as e:
        print(f"[AutoForm AI OCR] Error construyendo mapa OCR: {e}")

    t_total = time.perf_counter() - t0
    print(f"[AutoForm AI OCR] Mapa OCR construido en {t_total:.3f}s ({len(mapa_bruto)} rótulos)")
    return mapa_bruto


# ---------------------------------------------------------------------------
# Detección de campos con visión LLM (página por página)
# ---------------------------------------------------------------------------
def detectar_campos_vision_llm(
    bytes_pdf: bytes,
    datos_empresa: Dict[str, Any],
    max_paginas: int = 5,
) -> List[Dict[str, Any]]:
    """Localiza campos mediante visión LLM, página por página, validando con Pydantic."""
    campos: List[Dict[str, Any]] = []

    try:
        doc = fitz.open(stream=bytes_pdf, filetype="pdf")
        total = min(len(doc), max_paginas)
        doc.close()
    except Exception as e:
        print(f"[AutoForm AI Vision] Error abriendo PDF: {e}")
        return []

    for n in range(total):
        img = _renderizar_pagina_png(bytes_pdf, n)
        if not img:
            continue

        elems = invocar_llm_vision([img], datos_empresa)
        for e in elems:
            try:
                cv = CampoVision.model_validate(e)
                d = cv.model_dump()
                d["pagina"] = n + 1
                campos.append(d)
            except Exception as exc:
                print(f"[AutoForm AI Vision] Campo vision omitido por validación ({exc}): {e}")

    print(f"[AutoForm AI Vision] {len(campos)} campos detectados por visión en {total} página(s)")
    return campos


# ---------------------------------------------------------------------------
# Validación visual post-llenado con auto-corrección
# ---------------------------------------------------------------------------
def _validar_pagina_vision(img_bytes: bytes, campos_esperados: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pide al LLM validar visualmente una página rellena y devolver problemas + bbox corregido."""
    prompt = (
        "Eres un control de calidad visual de formularios PDF ya diligenciados.\n"
        "Se te muestra una página de un formulario en el que se inyectaron datos de una empresa.\n\n"
        f"CAMPOS ESPERADOS (campo, pagina, bbox_1000 = [ymin, xmin, ymax, xmax] en escala 0-1000):\n"
        f"{json.dumps(campos_esperados, ensure_ascii=False)}\n\n"
        "Para CADA campo compara el bbox_1000 esperado con lo que ves dibujado en la imagen y determina:\n"
        "- 'ok': el texto está dentro de su casilla y no se sale.\n"
        "- 'overflow': el texto se sale de la casilla (se corta o desborda).\n"
        "- 'vacio': la casilla quedó vacía aunque debía contener el dato.\n"
        "- 'fuera_de_lugar': el texto se escribió en un lugar incorrecto.\n\n"
        "RESPONDE ÚNICAMENTE JSON:\n"
        '{"advertencias": [{"campo": "...", "pagina": N, "problema": "overflow|vacio|fuera_de_lugar", '
        '"bbox_corregido": [ymin, xmin, ymax, xmax]}]}\n'
        "- NO incluyas campos con problema 'ok'.\n"
        "- Incluye 'bbox_corregido' SOLO si el texto debería ir en otra casilla (fuera_de_lugar) "
        "o necesita una casilla más amplia (overflow); siempre en escala 0-1000.\n"
        "- Si solo falta el dato (vacio) y no sabes dónde va, omite 'bbox_corregido'."
    )

    advs = consultar_llm_vision([img_bytes], prompt, "advertencias")
    validos: List[Dict[str, Any]] = []
    for adv in advs:
        try:
            modelo = AdvertenciaValidacion.model_validate(adv)
            validos.append(modelo.model_dump())
        except Exception as exc:
            print(f"[AutoForm AI Validación] Advertencia omitida por validación ({exc}): {adv}")
    return validos


def validar_relleno_vision(
    bytes_pdf_original: bytes,
    bytes_pdf_relleno: bytes,
    plan_mapeo: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
    max_iter: int = 2,
) -> Tuple[bytes, List[Dict[str, Any]]]:
    """Valida visualmente el PDF relleno y auto-corrige bounding boxes con visión LLM.

    En cada iteración valida las páginas con campos, recolecta correcciones y re-llena
    desde el PDF original aplicándolas. Retorna (bytes_final, advertencias_ui).
    """
    bytes_actual = bytes_pdf_relleno
    advertencias_todas: List[Dict[str, Any]] = []

    try:
        doc = fitz.open(stream=bytes_pdf_original, filetype="pdf")
        dims: Dict[int, Tuple[float, float]] = {
            n: (doc.load_page(n).rect.width, doc.load_page(n).rect.height)
            for n in range(len(doc))
        }
        n_paginas = len(doc)
        doc.close()
    except Exception as e:
        print(f"[AutoForm AI Validación] Error abriendo PDF para validación: {e}")
        return bytes_pdf_relleno, []

    plan_actual = copy.deepcopy(plan_mapeo)

    # FIX: deduplicar por campo antes de cada iteración de validación
    # (evita re-escribir el mismo campo en múltiples posiciones)
    def _deduplicar_por_campo_local(items):
        vistos = set()
        unicos = []
        for it in items:
            campo = it.get("campo")
            if campo and campo not in vistos:
                vistos.add(campo)
                unicos.append(it)
            elif campo:
                print(f"[AutoForm AI Validación] Deduplicado campo repetido: {campo}")
        return unicos

    plan_actual = _deduplicar_por_campo_local(plan_actual)

    for _ in range(max_iter):
        por_pagina: Dict[int, List[Dict[str, Any]]] = {}

        for item in plan_actual:
            if not item.get("campo"):
                continue
            pg = item.get("_pdf_page")
            if pg is None:
                hoja = item.get("hoja", "")
                if not hoja.startswith("Pagina_"):
                    continue
                try:
                    pg = int(hoja.split("_")[1]) - 1
                except ValueError:
                    continue
            pg = int(pg)
            if pg < 0 or pg >= n_paginas:
                continue
            rect = item.get("_pdf_target_rect")
            if not rect:
                continue
            por_pagina.setdefault(pg, []).append(item)

        if not por_pagina:
            break

        correcciones: List[Dict[str, Any]] = []

        for pg, items in por_pagina.items():
            ancho, alto = dims.get(pg, (0, 0))
            if not ancho:
                continue
            esperados = [
                {
                    "campo": it["campo"],
                    "pagina": pg + 1,
                    "bbox_1000": _rect_a_bbox1000(it["_pdf_target_rect"], ancho, alto),
                }
                for it in items
            ]
            img = _renderizar_pagina_png(bytes_actual, pg)
            if not img:
                continue

            for adv in _validar_pagina_vision(img, esperados):
                adv["_pagina_idx"] = pg
                advertencias_todas.append(adv)
                if adv.get("bbox_corregido"):
                    correcciones.append(adv)

        if not correcciones:
            break

        for adv in correcciones:
            pg = adv.get("_pagina_idx")
            ancho, alto = dims.get(pg, (0, 0))
            if not ancho:
                continue
            rect_corregido = pdf_processor.convertir_bounding_box_vision(adv["bbox_corregido"], ancho, alto)
            for item in plan_actual:
                if item.get("campo") == adv.get("campo") and int(item.get("_pdf_page", -1)) == pg:
                    item["_pdf_target_rect"] = rect_corregido

        # FIX: deduplicar por campo antes de re-llenar (correcciones pueden duplicar)
        plan_actual = _deduplicar_por_campo_local(plan_actual)

        bytes_actual = pdf_processor.rellenar_pdf(bytes_pdf_original, plan_actual, datos_empresa)

    advertencias_ui = [
        {
            "campo": a.get("campo", ""),
            "pagina": int(a.get("_pagina_idx", 0)) + 1,
            "problema": a.get("problema", "ok"),
        }
        for a in advertencias_todas
    ]
    return bytes_actual, advertencias_ui
