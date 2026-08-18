"""Módulo de Procesamiento de Formularios PDF (Motor Híbrido F-Optimizado).

Incluye:
- Profiling con time.perf_counter().
- Ray-casting bidireccional (derecha y abajo) para ubicar campos vacíos con precisión.
- Detección de casillas de verificación (checkboxes) y rótulos multilínea.
- Extracción e inyección nativa en AcroForms (widgets interactivos).
- Conversión de bounding boxes normalizadas (0-1000) para integración con IA Visual (Gemini/GPT Vision).
- Caché en disco por Hash MD5 del binario PDF en `config/pdf_cache/`.
- Posicionamiento, auto-scaling y truncado inteligente para evitar desbordamientos.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore
import pdfplumber

# Directorio de caché local para mapas de PDF
_CACHE_DIR = Path("config") / "pdf_cache"


def _obtener_hash_pdf(bytes_pdf: bytes) -> str:
    """Calcula el hash MD5 del PDF binario para usar como clave de caché en disco."""
    return hashlib.md5(bytes_pdf).hexdigest()


def _guardar_cache_mapa(pdf_hash: str, mapa: List[Dict[str, Any]]) -> None:
    """Guarda el mapa escaneado de un PDF en disco como JSON."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = _CACHE_DIR / f"{pdf_hash}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(mapa, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[AutoForm AI Perf] Error al guardar caché en disco: {e}")


def _cargar_cache_mapa(pdf_hash: str) -> List[Dict[str, Any]] | None:
    """Carga el mapa escaneado de un PDF desde la caché en disco si existe."""
    try:
        cache_file = _CACHE_DIR / f"{pdf_hash}.json"
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[AutoForm AI Perf] Error al leer caché desde disco: {e}")
    return None


def renderizar_paginas_png(bytes_pdf: bytes, max_paginas: int = 3, dpi: int = 150) -> List[bytes]:
    """Renderiza las páginas de un PDF como imágenes PNG en memoria con DPI configurable."""
    t0 = time.perf_counter()
    imagenes_png: List[bytes] = []
    try:
        doc = fitz.open(stream=bytes_pdf, filetype="pdf")
        total = min(len(doc), max_paginas)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        
        for i in range(total):
            pagina = doc.load_page(i)
            pix = pagina.get_pixmap(matrix=matrix)
            img_bytes = pix.tobytes("png")
            imagenes_png.append(img_bytes)
            
        doc.close()
    except Exception as e:
        print(f"[AutoForm AI] Error al renderizar PDF a PNG: {e}")
        
    t_total = time.perf_counter() - t0
    print(f"[AutoForm AI Perf] [PNG] Previsualización PNG ({len(imagenes_png)} pág) renderizada en {t_total:.3f}s")
    return imagenes_png


def convertir_bounding_box_vision(
    bbox_1000: List[float] | Tuple[float, float, float, float],
    ancho_pagina: float,
    alto_pagina: float,
) -> Tuple[float, float, float, float]:
    """Convierte una bounding box normalizada [ymin, xmin, ymax, xmax] en escala 0-1000
    a coordenadas físicas reales (x0, y0, x1, y1) en puntos PDF.
    """
    ymin, xmin, ymax, xmax = bbox_1000
    x0 = (float(xmin) / 1000.0) * ancho_pagina
    y0 = (float(ymin) / 1000.0) * alto_pagina
    x1 = (float(xmax) / 1000.0) * ancho_pagina
    y1 = (float(ymax) / 1000.0) * alto_pagina
    return (x0, y0, x1, y1)


def _calcular_target_rect_bidireccional(
    x0_inicial: float,
    x1_final: float,
    y_top: float,
    y_bottom: float,
    ancho_pagina: float,
    cajas_visuales: List[Dict[str, Any]],
    lineas_visuales: List[Dict[str, Any]],
) -> Tuple[Tuple[float, float, float, float], bool, bool]:
    """Ray-Casting Bidireccional: Determina el área de inyección escaneando a la derecha y ABAJO.

    Returns:
        Tuple: (target_rect, es_caja_cerrada, es_casilla_checkbox)
    """
    alto_fuente = max(8.0, y_bottom - y_top)

    # -------------------------------------------------------------------------
    # CAPA 1: Detección de Casillas de Verificación (Checkboxes pequeños)
    # -------------------------------------------------------------------------
    # Buscar recuadros cuadrados pequeños (8x8 a 20x20 px) muy cerca a la izquierda o derecha
    cajas_checkbox = [
        r for r in cajas_visuales
        if 6 <= (r["x1"] - r["x0"]) <= 22 and 6 <= (r["bottom"] - r["top"]) <= 22
        and abs(r["top"] - y_top) < 12
    ]
    if cajas_checkbox:
        # Priorizar casilla inmediatamente a la derecha o a la izquierda (< 35px)
        cajas_checkbox.sort(key=lambda r: min(abs(r["x0"] - x1_final), abs(x0_inicial - r["x1"])))
        caja_cb = cajas_checkbox[0]
        dist_derecha = caja_cb["x0"] - x1_final
        dist_izquierda = x0_inicial - caja_cb["x1"]
        
        if (-5 <= dist_derecha < 40) or (-5 <= dist_izquierda < 40):
            target_rect = (caja_cb["x0"] + 1, caja_cb["top"] + 1, caja_cb["x1"] - 1, caja_cb["bottom"] - 1)
            return target_rect, True, True

    # -------------------------------------------------------------------------
    # CAPA 2A: Escaneo Horizontal (Buscar caja a la DERECHA)
    # -------------------------------------------------------------------------
    cajas_derecha = [
        r for r in cajas_visuales
        if r["x0"] >= (x1_final - 3) and abs(r["top"] - y_top) < 15
        and (r["x1"] - r["x0"]) > 20
    ]
    if cajas_derecha:
        cajas_derecha.sort(key=lambda r: r["x0"])
        caja = cajas_derecha[0]
        if caja["x0"] - x1_final < 65:
            target_rect = (caja["x0"] + 2, caja["top"] + 1, caja["x1"] - 2, caja["bottom"] - 1)
            return target_rect, True, False

    # -------------------------------------------------------------------------
    # CAPA 2B: Escaneo Horizontal (Buscar línea horizontal a la DERECHA)
    # -------------------------------------------------------------------------
    lineas_derecha = [
        l for l in lineas_visuales
        if l["x0"] >= (x1_final - 3) and abs(l["top"] - y_bottom) < 12
        and (l["x1"] - l["x0"]) > 20
    ]
    if lineas_derecha:
        lineas_derecha.sort(key=lambda l: l["x0"])
        linea = lineas_derecha[0]
        if linea["x0"] - x1_final < 65:
            target_rect = (linea["x0"], linea["top"] - alto_fuente - 2, linea["x1"], linea["bottom"])
            return target_rect, False, False

    # -------------------------------------------------------------------------
    # CAPA 3A: Escaneo Vertical (Buscar caja ABAJO del rótulo)
    # -------------------------------------------------------------------------
    cajas_abajo = [
        r for r in cajas_visuales
        if r["top"] >= (y_bottom - 3) and (r["top"] - y_bottom) < 30
        and (r["x0"] <= (x0_inicial + 30) or abs(r["x0"] - x0_inicial) < 40)
        and (r["x1"] - r["x0"]) > 25
    ]
    if cajas_abajo:
        cajas_abajo.sort(key=lambda r: r["top"])
        caja = cajas_abajo[0]
        target_rect = (caja["x0"] + 2, caja["top"] + 1, caja["x1"] - 2, caja["bottom"] - 1)
        return target_rect, True, False

    # -------------------------------------------------------------------------
    # CAPA 3B: Escaneo Vertical (Buscar línea horizontal ABAJO del rótulo)
    # -------------------------------------------------------------------------
    lineas_abajo = [
        l for l in lineas_visuales
        if l["top"] >= (y_bottom - 2) and (l["top"] - y_bottom) < 25
        and (l["x0"] <= (x0_inicial + 30) or abs(l["x0"] - x0_inicial) < 40)
        and (l["x1"] - l["x0"]) > 25
    ]
    if lineas_abajo:
        lineas_abajo.sort(key=lambda l: l["top"])
        linea = lineas_abajo[0]
        target_rect = (linea["x0"], linea["top"] - alto_fuente - 2, linea["x1"], linea["bottom"])
        return target_rect, False, False

    # -------------------------------------------------------------------------
    # CAPA 4: Fallback Acotado a Margen Derecho de la Página
    # -------------------------------------------------------------------------
    x1_limite = min(x1_final + 280, ancho_pagina - 20)
    if x1_limite <= (x1_final + 10):
        x1_limite = min(x0_inicial + 200, ancho_pagina - 15)
        
    target_rect = (x1_final + 5, y_top, x1_limite, y_bottom + (alto_fuente * 0.25))
    return target_rect, False, False


def _consolidar_rotulos_multilineas(entradas_mapa: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Combina líneas consecutivas o fragmentos que corresponden a un mismo rótulo multilínea."""
    if not entradas_mapa:
        return []

    # Ordenar por página, fila y columna
    entradas_ordenadas = sorted(
        entradas_mapa, 
        key=lambda e: (e.get("_pdf_page", 0), e.get("fila", 0), e.get("columna", 0))
    )

    consolidados: List[Dict[str, Any]] = []
    actual: Optional[Dict[str, Any]] = None

    for item in entradas_ordenadas:
        if actual is None:
            actual = dict(item)
            continue

        mismo_page = (actual.get("_pdf_page") == item.get("_pdf_page"))
        dist_v = item.get("fila", 0) - actual.get("fila", 0)
        dist_h = abs(item.get("columna", 0) - actual.get("columna", 0))

        # Si el ítem siguiente está en la línea inmediatamente inferior (< 16px) y casi alineado horizontalmente (< 25px)
        # o si es una continuación en la misma línea
        es_multilinea = (mismo_page and 0 < dist_v <= 16 and dist_h < 25)

        if es_multilinea and not actual.get("_pdf_es_casilla") and not item.get("_pdf_es_casilla"):
            actual["valor"] = f"{actual['valor']} {item['valor']}".strip()
            # Expandir el bounding box combinado
            bbox_act = actual["_pdf_bbox"]
            bbox_item = item["_pdf_bbox"]
            actual["_pdf_bbox"] = (
                min(bbox_act[0], bbox_item[0]),
                min(bbox_act[1], bbox_item[1]),
                max(bbox_act[2], bbox_item[2]),
                max(bbox_act[3], bbox_item[3]),
            )
            # Conservar el target_rect del elemento inferior o el más específico
            if item.get("_pdf_es_caja") or not actual.get("_pdf_es_caja"):
                actual["_pdf_target_rect"] = item["_pdf_target_rect"]
                actual["_pdf_es_caja"] = item["_pdf_es_caja"]
        else:
            consolidados.append(actual)
            actual = dict(item)

    if actual is not None:
        consolidados.append(actual)

    return consolidados


def escanear_mapa_pdf(bytes_pdf: bytes) -> List[Dict[str, Any]]:
    """Extrae palabras, líneas visuales, AcroForms y áreas de inyección de un PDF."""
    t0 = time.perf_counter()
    pdf_hash = _obtener_hash_pdf(bytes_pdf)
    
    # 1. Comprobar Caché en Disco por MD5
    mapa_cached = _cargar_cache_mapa(pdf_hash)
    if mapa_cached is not None:
        t_cache = time.perf_counter() - t0
        print(f"[AutoForm AI Perf] [HIT] CACHE EN DISCO HIT (MD5: {pdf_hash[:10]}...) - Mapa cargado en {t_cache:.4f}s ($0 CPU)")
        return mapa_cached

    # 2. Escaneo en frío si no está en caché
    print(f"[AutoForm AI Perf] [SCAN] Escaneando PDF en frio con Ray-Casting Bidireccional (MD5: {pdf_hash[:10]}...)...")
    t_open_start = time.perf_counter()
    mapa_bruto: List[Dict[str, Any]] = []

    # 2A. Escaneo de AcroForms nativos (Widgets interactivos PyMuPDF)
    widgets_acroform: List[Dict[str, Any]] = []
    try:
        doc_fitz = fitz.open(stream=bytes_pdf, filetype="pdf")
        if doc_fitz.is_form_pdf:
            for n_pag in range(len(doc_fitz)):
                pag = doc_fitz.load_page(n_pag)
                for w in pag.widgets():
                    if w.field_name:
                        widgets_acroform.append({
                            "hoja": f"Pagina_{n_pag + 1}",
                            "fila": int(w.rect.y0),
                            "columna": int(w.rect.x0),
                            "valor": f"[Campo Formulario: {w.field_name}]",
                            "_pdf_page": n_pag,
                            "_pdf_bbox": (w.rect.x0, w.rect.y0, w.rect.x1, w.rect.y1),
                            "_pdf_target_rect": (w.rect.x0, w.rect.y0, w.rect.x1, w.rect.y1),
                            "_pdf_es_caja": True,
                            "_pdf_es_acroform": True,
                            "_pdf_widget_name": w.field_name,
                        })
        doc_fitz.close()
    except Exception as e:
        print(f"[AutoForm AI] Aviso al escanear AcroForms: {e}")

    # 2B. Escaneo espacial con pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(bytes_pdf)) as pdf:
            t_open = time.perf_counter() - t_open_start
            t_words_accum = 0.0

            for n_pag, pagina in enumerate(pdf.pages):
                t_page_start = time.perf_counter()

                palabras = pagina.extract_words(
                    x_tolerance=3,
                    y_tolerance=3,
                    keep_blank_chars=False,
                    use_text_flow=False,
                    extra_attrs=[],
                )
                lineas_visuales = pagina.lines
                cajas_visuales = pagina.rects
                ancho_pagina = pagina.width

                t_words_accum += (time.perf_counter() - t_page_start)

                lineas: Dict[int, List[Dict[str, Any]]] = {}
                for p in palabras:
                    y_key = round(p["top"] / 5) * 5
                    if y_key not in lineas:
                        lineas[y_key] = []
                    lineas[y_key].append(p)

                for y_key in sorted(lineas.keys()):
                    linea_palabras = sorted(lineas[y_key], key=lambda w: w["x0"])

                    frase_actual = ""
                    x0_inicial = None
                    y_top = None
                    y_bottom = None
                    x1_final = None

                    for w in linea_palabras:
                        if not frase_actual:
                            frase_actual = w["text"]
                            x0_inicial = float(w["x0"])
                            y_top = float(w["top"])
                            y_bottom = float(w["bottom"])
                            x1_final = float(w["x1"])
                        else:
                            distancia_x = float(w["x0"]) - x1_final
                            if distancia_x < 15:
                                frase_actual += " " + w["text"]
                                x1_final = float(w["x1"])
                                y_top = min(y_top, float(w["top"]))
                                y_bottom = max(y_bottom, float(w["bottom"]))
                            else:
                                target_rect, es_caja, es_cb = _calcular_target_rect_bidireccional(
                                    x0_inicial, x1_final, y_top, y_bottom, ancho_pagina, cajas_visuales, lineas_visuales
                                )

                                mapa_bruto.append({
                                    "hoja": f"Pagina_{n_pag + 1}",
                                    "fila": int(y_top),
                                    "columna": int(x0_inicial),
                                    "valor": frase_actual.strip(),
                                    "_pdf_page": n_pag,
                                    "_pdf_bbox": (x0_inicial, y_top, x1_final, y_bottom),
                                    "_pdf_target_rect": target_rect,
                                    "_pdf_es_caja": es_caja,
                                    "_pdf_es_casilla": es_cb,
                                })

                                frase_actual = w["text"]
                                x0_inicial = float(w["x0"])
                                y_top = float(w["top"])
                                y_bottom = float(w["bottom"])
                                x1_final = float(w["x1"])

                    if frase_actual:
                        target_rect, es_caja, es_cb = _calcular_target_rect_bidireccional(
                            x0_inicial, x1_final, y_top, y_bottom, ancho_pagina, cajas_visuales, lineas_visuales
                        )

                        mapa_bruto.append({
                            "hoja": f"Pagina_{n_pag + 1}",
                            "fila": int(y_top),
                            "columna": int(x0_inicial),
                            "valor": frase_actual.strip(),
                            "_pdf_page": n_pag,
                            "_pdf_bbox": (x0_inicial, y_top, x1_final, y_bottom),
                            "_pdf_target_rect": target_rect,
                            "_pdf_es_caja": es_caja,
                            "_pdf_es_casilla": es_cb,
                        })

    except Exception as e:
        print(f"[AutoForm AI] Error al escanear espacialmente el PDF: {e}")

    # 3. Consolidación multilínea de rótulos
    mapa_consolidado = _consolidar_rotulos_multilineas(mapa_bruto)

    # Combinar AcroForms al inicio si existen
    mapa_final = widgets_acroform + mapa_consolidado

    t_total = time.perf_counter() - t0
    print(
        f"[AutoForm AI Perf] [TIME] Escaneo completado: Total={t_total:.3f}s | "
        f"AcroForms={len(widgets_acroform)} | Rótulos={len(mapa_final)}"
    )

    if mapa_final:
        _guardar_cache_mapa(pdf_hash, mapa_final)

    return mapa_final


def construir_mapa_desde_vision(
    bytes_pdf: bytes,
    elementos_vision: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Construye un mapa de inyección en PDF a partir del resultado de Gemini Vision (o GPT Vision)
    donde cada elemento especifica `campo`, `bbox_1000` ([ymin, xmin, ymax, xmax]) y opcionalmente `pagina`.
    """
    mapa_vision: List[Dict[str, Any]] = []

    try:
        doc = fitz.open(stream=bytes_pdf, filetype="pdf")
        
        for idx, elem in enumerate(elementos_vision):
            n_pag = int(elem.get("pagina", 1)) - 1
            if n_pag < 0 or n_pag >= len(doc):
                n_pag = 0
                
            pagina = doc.load_page(n_pag)
            ancho_p = pagina.rect.width
            alto_p = pagina.rect.height

            bbox_1000 = elem.get("bbox_1000") or elem.get("bbox")
            if not bbox_1000 or len(bbox_1000) != 4:
                continue

            target_rect = convertir_bounding_box_vision(bbox_1000, ancho_p, alto_p)
            campo_nombre = elem.get("campo", f"campo_{idx}")

            mapa_vision.append({
                "hoja": f"Pagina_{n_pag + 1}",
                "fila": int(target_rect[1]),
                "columna": int(target_rect[0]),
                "valor": f"IA Vision: {campo_nombre}",
                "campo": campo_nombre,
                "_pdf_page": n_pag,
                "_pdf_bbox": target_rect,
                "_pdf_target_rect": target_rect,
                "_pdf_es_caja": True,
                "_pdf_es_vision": True,
            })
            
    except Exception as e:
        print(f"[AutoForm AI] Error al construir mapa desde Visión: {e}")

    return mapa_vision


def _calcular_rect_destino_fitz(
    pagina: fitz.Page,
    label_bbox: Tuple[float, float, float, float] | List[float],
    tipo_espacio: str = "derecha"
) -> Tuple[float, float, float, float]:
    """HITO 6: Calcula las coordenadas de destino exactas (x0, y0, x1, y1) en puntos PDF
    utilizando exclusivamente la librería nativa PyMuPDF (fitz).

    Ancla el inicio X al extremo derecho del texto de la etiqueta (x1 + 10pt) e inspecciona
    líneas vectoriales dibujadas con get_drawings() para alineación milimétrica.
    """
    x0, y0, x1, y1 = label_bbox
    ancho_pag = pagina.rect.width
    alto_linea = max(10.0, y1 - y0)

    # Detección de líneas vectoriales dibujadas a la derecha con get_drawings()
    linea_vectorial_x = None
    try:
        for dw in pagina.get_drawings():
            for item in dw.get("items", []):
                if item[0] in ("l", "re"):
                    p1, p2 = item[1], item[2]
                    if min(p1.y, p2.y) <= y1 + 4 and max(p1.y, p2.y) >= y0 - 4:
                        min_x = min(p1.x, p2.x)
                        if min_x >= x1 - 5 and min_x <= x1 + 150:
                            linea_vectorial_x = min_x
                            break
            if linea_vectorial_x:
                break
    except Exception:
        pass

    x0_dest = (linea_vectorial_x + 2.0) if linea_vectorial_x else (x1 + 10.0)

    # Redirección por Borde Derecho: Si no hay espacio a la derecha (x0_dest >= ancho_pag - 40pt)
    if x0_dest >= ancho_pag - 40.0 or tipo_espacio == "abajo":
        x0_dest = x0
        y0_dest = y1 + 3.0
        x1_dest = min(x0_dest + 250.0, ancho_pag - 15.0)
        y1_dest = y0_dest + alto_linea
    else:
        y0_dest = y0
        x1_dest = min(x0_dest + max(150.0, ancho_pag - x0_dest - 15.0), ancho_pag - 15.0)
        y1_dest = y1

    return (x0_dest, y0_dest, x1_dest, y1_dest)


# ---------------------------------------------------------------------------
# FASE 2: Text-Fit determinista (medir antes de escribir, nunca expandir el campo)
# ---------------------------------------------------------------------------

_SAFE_MARGIN_X = 2.0
_FONT_METRICAS = fitz.Font("helv")


def _medir_ancho_texto(texto: str, size: float) -> float:
    """Ancho real del texto en puntos usando métricas Helvetica (compatible con Arial)."""
    return _FONT_METRICAS.text_length(texto, fontsize=size)


def _calcular_font_size_fit(
    texto: str,
    rect: fitz.Rect,
    size_max: float,
    size_min: float,
) -> float | None:
    """Calcula el mayor tamaño de fuente cuyo ancho de texto cabe dentro del rectángulo."""
    ancho_disponible = max(1.0, rect.width - 2 * _SAFE_MARGIN_X)
    size = size_max
    while size >= size_min:
        if _medir_ancho_texto(texto, size) <= ancho_disponible:
            return size
        size -= 0.5
    return None


def _truncar_a_ancho(texto: str, rect: fitz.Rect, size: float) -> str:
    """Recorta el texto hasta que su ancho quepa en el rectángulo a un tamaño fijo."""
    ancho_disponible = max(1.0, rect.width - 2 * _SAFE_MARGIN_X)
    corto = texto
    while corto and _medir_ancho_texto(corto, size) > ancho_disponible:
        corto = corto[:-1]
    return corto


def _calcular_margen_vertical(rect: fitz.Rect, size: float) -> float:
    """Centrado vertical por métricas de fuente (ascender/descender), no empírico.

    La altura del bloque de una línea es ~size * (ascender - descender); se centra
    ese bloque dentro del rectángulo en lugar de usar factores mágicos como /3.5.
    """
    ratio_linea = _FONT_METRICAS.ascender - _FONT_METRICAS.descender
    bloque = size * max(ratio_linea, 1.0)
    return max(0.0, (rect.height - bloque) / 2.0)


def extraer_tipografia_dominante_pdf(pagina: fitz.Page) -> Tuple[str, str]:


    """HITO 4: Extrae la tipografía dominante y la variante (normal/negrita) de una página PDF.

    Analiza los spans de texto de la página y determina el código de fuente nativo de PyMuPDF:
    - 'helv' / 'hebo' (Helvetica / Sans-Serif)
    - 'tiro' / 'tibo' (Times-Roman / Serif)
    - 'cour' / 'cobo' (Courier / Monospace)

    Returns:
        Tuple[fontname_codigo, nombre_fuente_original]
    """
    try:
        text_page = pagina.get_text("dict")
        conteo_fuentes: Dict[str, int] = {}
        es_bold = False

        for block in text_page.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        fn = str(span.get("font", "")).strip()
                        txt = str(span.get("text", "")).strip()
                        if fn and txt:
                            conteo_fuentes[fn] = conteo_fuentes.get(fn, 0) + len(txt)

        if not conteo_fuentes:
            return ("helv", "Helvetica")

        fuente_top = max(conteo_fuentes, key=conteo_fuentes.get)
        fn_lower = fuente_top.lower()

        if any(b in fn_lower for b in ("bold", "black", "heavy", "medium")):
            es_bold = True

        if any(s in fn_lower for s in ("times", "serif", "cambria", "georgia", "garamond", "roman")):
            code = "tibo" if es_bold else "tiro"
        elif any(m in fn_lower for m in ("courier", "mono", "consolas", "code")):
            code = "cobo" if es_bold else "cour"
        else:
            code = "hebo" if es_bold else "helv"

        return (code, fuente_top)

    except Exception as exc:
        print(f"[AutoForm AI PDF] Error extrayendo tipografía de la página: {exc}")
        return ("helv", "Helvetica")


def _raiz_fuente(nombre: str) -> str:
    """Raíz alfabética de un nombre de fuente.

    'ArialMT' -> 'arial', 'Arial Regular' -> 'arial', 'ABCDEF+Arial-Bold' -> 'arial'.
    """
    nombre = str(nombre)
    if "+" in nombre:
        nombre = nombre.split("+")[-1]
    m = re.search(r"[a-z]+", nombre.lower())
    return m.group(0) if m else ""


def _obtener_fuente_nativa(doc: fitz.Document, pagina: fitz.Page) -> Tuple[str, Optional[bytes]]:
    """Extrae la fuente más usada de la página y devuelve (fontname, fontbuffer TTF/OTF).

    Permite inyectar texto con la tipografía real del documento (incluye ñ y acentos).
    Retorna (None, None) si no hay fuente embebible (se usa el fallback base-14).
    """
    try:
        conteo: Dict[str, int] = {}
        for block in pagina.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    fn = str(span.get("font", "")).strip()
                    txt = str(span.get("text", "")).strip()
                    if fn and txt:
                        conteo[fn] = conteo.get(fn, 0) + len(txt)

        if not conteo:
            return (None, None)

        fuente_top = max(conteo, key=conteo.get)
        raiz_top = _raiz_fuente(fuente_top)

        for xref, ext, ftype, basefont, name, _encoding, *_rest in pagina.get_fonts(full=True):
            candidato = basefont or name
            raiz_cand = _raiz_fuente(candidato)
            if not (raiz_top and raiz_cand):
                continue
            if raiz_top != raiz_cand and raiz_top not in raiz_cand and raiz_cand not in raiz_top:
                continue
            # FIX: las fuentes Type0/CID (Identity-H) no mapean glifos de texto nuevo al
            # registrarse via insert_font: "inyectan" pero el texto queda INVISIBLE y no
            # extraible. Solo se usan fuentes simples con cmap real (TrueType/Type1).
            if ftype == "Type0":
                continue
            try:
                _basename, fext, _ftype, content = doc.extract_font(xref)
                if content and fext in ("ttf", "otf", "ttf.0", "ttf.1", "otf.0"):
                    return (f"afrm{xref}", content)
            except Exception:
                continue

        return (None, None)
    except Exception as e:
        print(f"[AutoForm AI PDF Font] Error extrayendo fuente nativa: {e}")
        return (None, None)


def _insertar_con_fallback(
    pagina: fitz.Page,
    rect: fitz.Rect,
    texto: str,
    fontname: str,
    size: float,
    color: Tuple[float, float, float],
    align: int,
) -> int:
    """Inyecta texto con la fuente dada y reintenta con base-14 'helv' ante cualquier fallo.

    Devuelve el rc de insert_textbox (>= 0 = éxito) o -1 si ambas fallan.
    """
    try:
        return pagina.insert_textbox(
            rect, texto, fontsize=size, fontname=fontname, color=color, align=align
        )
    except Exception:
        try:
            return pagina.insert_textbox(
                rect, texto, fontsize=size, fontname="helv", color=color, align=align
            )
        except Exception:
            return -1


def rellenar_pdf(
    bytes_pdf: bytes, 
    plan_mapeo: List[Dict[str, Any]], 
    datos_empresa: Dict[str, Any]
) -> bytes:
    """Superpone los datos en el PDF ajustando automáticamente la tipografía nativa, tamaño y centrado."""
    t0 = time.perf_counter()
    try:
        doc = fitz.open(stream=bytes_pdf, filetype="pdf")
        es_acroform = doc.is_form_pdf
        inyectados = 0
        fuentes_paginas: Dict[int, str] = {}

        for item in plan_mapeo:
            campo = item.get("campo")
            if not campo or campo not in datos_empresa:
                continue

            valor_a_escribir = str(datos_empresa[campo]).strip()
            if not valor_a_escribir:
                continue

            pdf_page_idx = item.get("_pdf_page")
            if pdf_page_idx is None:
                hoja = item.get("hoja", "")
                if hoja.startswith("Pagina_"):
                    try:
                        pdf_page_idx = int(hoja.split("_")[1]) - 1
                    except ValueError:
                        continue
                else:
                    continue

            if pdf_page_idx < 0 or pdf_page_idx >= len(doc):
                continue

            pagina = doc.load_page(pdf_page_idx)

            # HITO 4: Extraer y aplicar la tipografía nativa detectada para la página
            if pdf_page_idx not in fuentes_paginas:
                font_code, font_orig = extraer_tipografia_dominante_pdf(pagina)
                # Motor PDF v2: preferir la fuente real del documento (TTF/OTF embebido)
                font_nativa = _obtener_fuente_nativa(doc, pagina)
                if font_nativa[1]:
                    try:
                        pagina.insert_font(fontname=font_nativa[0], fontbuffer=font_nativa[1])
                        fuentes_paginas[pdf_page_idx] = font_nativa[0]
                        print(f"[AutoForm AI PDF Font] Pág {pdf_page_idx + 1}: Fuente real embebida")
                    except Exception as e:
                        print(f"[AutoForm AI PDF Font] Fallback base-14 en Pág {pdf_page_idx + 1}: {e}")
                        fuentes_paginas[pdf_page_idx] = font_code
                else:
                    fuentes_paginas[pdf_page_idx] = font_code
                    print(f"[AutoForm AI PDF Font] Pág {pdf_page_idx + 1}: Tipografía nativa '{font_orig}' -> Código '{font_code}'")

            font_nativa_pagina = fuentes_paginas[pdf_page_idx]

            # Capa 1: AcroForms Nativo (Widgets Interactivos)
            inyectado_acroform = False
            widget_target_name = item.get("_pdf_widget_name")

            if es_acroform or widget_target_name:
                for widget in pagina.widgets():
                    rect_esperado = item.get("_pdf_target_rect")
                    match_name = (widget_target_name and widget.field_name == widget_target_name)
                    match_rect = (rect_esperado and fitz.Rect(rect_esperado).intersects(widget.rect))

                    if match_name or match_rect:
                        widget.field_value = valor_a_escribir
                        if len(valor_a_escribir) < 25:
                            widget.text_format = 1
                        widget.update()
                        inyectado_acroform = True
                        inyectados += 1
                        break

            if inyectado_acroform:
                continue

            # Capa 2: Inyección en Casillas de Verificación (Checkboxes)
            es_casilla = item.get("_pdf_es_casilla", False)
            if es_casilla or str(valor_a_escribir).upper() in ("X", "YES", "SI", "SÍ", "TRUE", "1"):
                target_rect_tuple = item.get("_pdf_target_rect")
                if target_rect_tuple:
                    rect_cb = fitz.Rect(target_rect_tuple)
                    # Forzar dibujado de 'X' centrada
                    val_cb = "X" if str(valor_a_escribir).upper() in ("X", "YES", "SI", "SÍ", "TRUE", "1") else valor_a_escribir[:2]
                    font_cb = min(10.0, max(6.0, rect_cb.height * 0.75))
                    _insertar_con_fallback(
                        pagina,
                        rect_cb,
                        val_cb,
                        font_nativa_pagina,
                        font_cb,
                        (0.0, 0.2, 0.5),
                        fitz.TEXT_ALIGN_CENTER,
                    )
                    inyectados += 1
                    continue

            # Capa 3: Inyección Visual General con Tipografía Nativa
            target_rect_tuple = item.get("_pdf_target_rect")
            es_caja = item.get("_pdf_es_caja", False)

            if not target_rect_tuple:
                label_bbox = item.get("_pdf_label_bbox") or item.get("_pdf_bbox")
                if label_bbox:
                    target_rect_tuple = _calcular_rect_destino_fitz(pagina, label_bbox, item.get("ubicacion", "derecha"))
                else:
                    x0 = float(item.get("columna", 50))
                    y_top = float(item.get("fila", 50))
                    target_rect_tuple = (x0 + 100, y_top, min(x0 + 300, pagina.rect.width - 15), y_top + 15)


            rect_original = fitz.Rect(target_rect_tuple)

            if rect_original.width < 10:
                rect_original.x1 = min(rect_original.x0 + 120, pagina.rect.width - 10)
            if rect_original.height < 5:
                rect_original.y1 = rect_original.y0 + 12

            font_size_ideal = min(10.5, max(8.0, rect_original.height * 0.78))
            font_min = 7.0

            if es_caja and len(valor_a_escribir) < 20:
                align_mode = fitz.TEXT_ALIGN_CENTER
            elif len(valor_a_escribir) <= 10:
                align_mode = fitz.TEXT_ALIGN_CENTER
            else:
                align_mode = fitz.TEXT_ALIGN_LEFT

            # ── FASE 2: Fit determinista — medir el texto ANTES de escribirlo ──
            size = _calcular_font_size_fit(
                valor_a_escribir, rect_original, font_size_ideal, font_min
            )
            if size is None:
                size = font_min
                texto_a_escribir = _truncar_a_ancho(valor_a_escribir, rect_original, size)
                if not texto_a_escribir:
                    texto_a_escribir = valor_a_escribir[:1]
            else:
                texto_a_escribir = valor_a_escribir

            # ── FASE 2: posicionamiento exacto con baseline calculado ─────────
            # insert_textbox exige altura >= lineheight y devuelve rc<0 en cajas
            # pequeñas (p. ej. 8.32pt); insert_text + métricas de fuente permite
            # escribir en cualquier caja SIN expandir jamás el rectángulo.
            ancho_texto = _medir_ancho_texto(texto_a_escribir, size)
            ancho_disponible = rect_original.width - 2 * _SAFE_MARGIN_X
            if align_mode == fitz.TEXT_ALIGN_CENTER:
                x0_texto = rect_original.x0 + _SAFE_MARGIN_X + max(0.0, (ancho_disponible - ancho_texto) / 2.0)
            else:
                x0_texto = rect_original.x0 + _SAFE_MARGIN_X
            if x0_texto + ancho_texto > rect_original.x1 - _SAFE_MARGIN_X:
                x0_texto = rect_original.x1 - _SAFE_MARGIN_X - ancho_texto

            top_margin = _calcular_margen_vertical(rect_original, size)
            baseline_y = rect_original.y0 + top_margin + size * _FONT_METRICAS.ascender

            try:
                pagina.insert_text(
                    fitz.Point(x0_texto, baseline_y),
                    texto_a_escribir,
                    fontsize=size,
                    fontname=font_nativa_pagina,
                    color=(0.05, 0.12, 0.20),
                )
            except Exception:
                pagina.insert_text(
                    fitz.Point(x0_texto, baseline_y),
                    texto_a_escribir,
                    fontsize=size,
                    fontname="helv",
                    color=(0.05, 0.12, 0.20),
                )
            inyectados += 1
            if top_margin <= 0.0:
                print(
                    f"[AutoForm AI WRITE] Overflow vertical: caja {rect_original.height:.1f}pt "
                    f"menor al bloque de linea ({size:.1f}pt). Texto anclado al borde superior."
                )

        output_pdf_stream = io.BytesIO()

        doc.save(output_pdf_stream)
        doc.close()

        t_total = time.perf_counter() - t0
        print(f"[AutoForm AI Perf] [WRITE] Inyección en PDF completada en {t_total:.3f}s ({inyectados} campos inyectados).")
        return output_pdf_stream.getvalue()

    except Exception as e:
        traceback.print_exc()
        print(f"[AutoForm AI] Error al rellenar PDF: {e}")
        return bytes_pdf
