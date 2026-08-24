"""Stage 3: LLM Mapper y Búsqueda en Template Store (Pipeline AutoForm AI).

Orquesta el mapeo semántico de campos de dos maneras:
1. Ruta Rápida (Template Store): Si el formulario o uno muy similar ya fue verificado,
   reutiliza la plantilla guardada (0 costo, 0 latencia).
2. Inferencia IA (OpenAI LLM): Si es nuevo, envía únicamente los campos de entrada
   viables (previamente filtrados en Stage 2) junto con su contexto de sección para
   un emparejamiento semántico limpio y sin hard-gates.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from core.llm_client import invocar_llm
from pipeline.context import PipelineContext
from template_store.store import (
    calcular_hash_formulario,
    cargar_plantilla,
    buscar_plantilla_por_similitud,
    adaptar_plan_a_formulario,
)


def _extraer_json_respuesta(texto: str) -> List[Dict[str, Any]]:
    """Extrae la lista JSON de asignaciones {id, campo, ubicacion} de la respuesta del LLM."""
    t_clean = str(texto or "").strip()
    
    # 1. Parseo directo
    try:
        data = json.loads(t_clean)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("mappings") or data.get("resultado") or [data]
    except Exception:
        pass

    # 2. Bloques markdown ```json ... ```
    m = re.search(r'```(?:json)?\s*(.*?)\s*```', t_clean, re.DOTALL | re.IGNORECASE)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("mappings") or [data]
        except Exception:
            pass

    # 3. Buscar entre '[' y ']'
    i_start = t_clean.find('[')
    i_end = t_clean.rfind(']')
    if i_start != -1 and i_end != -1 and i_end > i_start:
        try:
            data = json.loads(t_clean[i_start:i_end + 1])
            if isinstance(data, list):
                return data
        except Exception:
            pass

    return []


def _deduplicar_destinos(mapeos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Evita que dos campos colisionen en la misma celda de destino."""
    destinos_ocupados = set()
    resultado = []
    
    for item in mapeos:
        hoja = str(item.get("hoja", ""))
        fila = int(item.get("fila", 0) or 0)
        col = int(item.get("columna", 0) or 0)
        ubic = str(item.get("ubicacion", "derecha")).lower()
        
        if ubic == "abajo":
            coord_dest = (hoja, fila + 1, col)
        elif ubic == "misma":
            coord_dest = (hoja, fila, col)
        else:
            coord_dest = (hoja, fila, col + 1)

        if coord_dest in destinos_ocupados:
            continue

        destinos_ocupados.add(coord_dest)
        resultado.append(item)

    return resultado


def ejecutar_stage_3_mapper(
    ctx: PipelineContext,
    umbral_similitud: float = 90.0,
    forzar_ia: bool = False,
) -> PipelineContext:
    """Ejecuta la etapa de mapeo semántico mediante Template Store o LLM."""
    t0 = time.time()
    elementos = ctx.elementos_raw
    
    # ── RUTA 1: Comprobar Template Store (si no se fuerza IA) ──
    if not forzar_ia:
        hash_form = calcular_hash_formulario(elementos)
        ctx.plantilla_id = hash_form

        # 1A. Coincidencia Exacta por Hash
        plantilla_exacta = cargar_plantilla(hash_form)
        if plantilla_exacta and plantilla_exacta.get("plan_mapeo"):
            ctx.plan_mapeo = plantilla_exacta["plan_mapeo"]
            ctx.es_plantilla_guardada = True
            ctx.score_similitud = 100.0
            ctx.log(f"[Stage 3 - Mapper] ¡Plantilla exacta encontrada en disco! ({len(ctx.plan_mapeo)} campos mapeados a 0 costo).")
            return ctx

        # 1B. Coincidencia Difusa (Fuzzy Matching)
        match_similar = buscar_plantilla_por_similitud(elementos, umbral=umbral_similitud)
        if match_similar is not None:
            pid, pdata, score = match_similar
            plan_adaptado = adaptar_plan_a_formulario(elementos, pdata)
            if plan_adaptado:
                ctx.plan_mapeo = plan_adaptado
                ctx.plantilla_id = pid
                ctx.es_plantilla_guardada = True
                ctx.score_similitud = score
                ctx.log(f"[Stage 3 - Mapper] ¡Plantilla similar encontrada! (Score: {score:.1f}%, ID: {pid}).")
                return ctx

    # ── RUTA 2: Inferencia con IA (LLM) ──
    ctx.log("[Stage 3 - Mapper] Consultando modelo de lenguaje (OpenAI)...")
    
    # Filtrar solo campos viables clasificados en Stage 2
    campos_viables = [
        {
            "id": idx + 1,
            "rotulo": str(elem.get("valor") or elem.get("rotulo") or "").strip(),
            "seccion": str(elem.get("seccion_padre", "INFORMACIÓN GENERAL")),
            "tipoEspacioEscritura": str(elem.get("tipoEspacioEscritura", "derecha")),
            "_elem_orig": elem,
        }
        for idx, elem in enumerate(ctx.elementos_clasificados)
        if elem.get("es_campo_viable", True)
    ]

    if not campos_viables:
        # Fallback a elementos crudos si no se ejecutó Stage 2 previamente
        campos_viables = [
            {
                "id": idx + 1,
                "rotulo": str(elem.get("valor") or elem.get("rotulo") or "").strip(),
                "seccion": "INFORMACIÓN GENERAL",
                "tipoEspacioEscritura": str(elem.get("tipoEspacioEscritura", "derecha")),
                "_elem_orig": elem,
            }
            for idx, elem in enumerate(elementos)
        ]

    from core.profile_manager import estructurar_perfil_taxonomia

    # Construir payload compacto estructurado con Taxonomía Semántica
    taxonomia_d = estructurar_perfil_taxonomia(ctx.datos_empresa)
    payload = {
        "F": [{"id": c["id"], "rotulo": c["rotulo"], "seccion": c["seccion"]} for c in campos_viables],
        "D": taxonomia_d,
    }
    
    prompt_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    respuesta_llm = invocar_llm(prompt_str)
    asignaciones_raw = _extraer_json_respuesta(respuesta_llm)

    # Reconstruir coordenadas físicas
    indice_campos = {c["id"]: c for c in campos_viables}
    plan_reconstruido: List[Dict[str, Any]] = []

    for item in asignaciones_raw:
        item_id = item.get("id")
        campo_empresa = str(item.get("campo") or "").strip()
        if "." in campo_empresa:
            campo_terminal = campo_empresa.split(".")[-1]
            if campo_terminal in ctx.datos_empresa or campo_terminal in ("razon_social", "nit", "cedula", "lugar_expedicion", "expedicion", "direccion", "telefono", "correo", "representante_legal", "representante_nombres", "representante_apellidos", "banco", "numero_cuenta", "tipo_cuenta", "sucursal", "ciudad", "departamento", "pais"):
                campo_empresa = campo_terminal
        
        # Normalizar expedicion a lugar_expedicion
        if campo_empresa == "expedicion":
            campo_empresa = "lugar_expedicion"

        if item_id in indice_campos and campo_empresa:
            c_info = indice_campos[item_id]
            elem_orig = c_info["_elem_orig"]
            rotulo_clean = str(c_info.get("rotulo", "")).strip().lower()

            # Normalizar rótulos compuestos de identificación (ej: CC/CE/PAS/NIT) a 'nit'
            if campo_empresa == "tipo_documento" and re.search(r"\bcc[\s/]*ce[\s/]*pas[\s/]*nit\b|\bcc[\s/]*ce[\s/]*nit\b|\bcc[\s/]*nit\b|\bnit[\s/]*cc\b", rotulo_clean):
                campo_empresa = "nit"

            # En la sección del Representante Legal, 'telefono' corresponde al celular/móvil
            sec_padre = str(elem_orig.get("seccion_padre") or c_info.get("seccion") or "").lower()
            if campo_empresa == "telefono" and any(k in sec_padre for k in ("representante", "apoderado", "persona natural")):
                campo_empresa = "celular"

            # Barrera de seguridad: NUNCA asignar lugar_expedicion a rótulos de FECHA
            if campo_empresa in ("lugar_expedicion", "expedicion") and re.search(r"\bfecha\b", rotulo_clean):
                print(f"[AutoForm Stage 3 Mapper Safety] Omitida asignación de '{campo_empresa}' al rótulo de fecha: '{c_info.get('rotulo')}'")
                continue

            ancho_l = int(elem_orig.get("anchoLinea", 1) or 1)
            ubic = str(item.get("ubicacion") or elem_orig.get("tipoEspacioEscritura") or "derecha").lower()
            if ubic not in ("derecha", "abajo", "misma"):
                ubic = "derecha"

            plan_item = {
                "hoja": str(elem_orig.get("hoja", "Hoja1")),
                "fila": int(elem_orig.get("fila", 1) or 1),
                "columna": int(elem_orig.get("columna", 1) or 1),
                "valor": c_info["rotulo"],
                "ubicacion": ubic,
                "campo": campo_empresa,
                "requiereMerge": bool(ancho_l > 1 and ubic == "derecha"),
                "celdasAMergear": ancho_l,
                "anchoLinea": ancho_l,
            }

            # Preservar metadatos de PDF
            for k in ("_pdf_page", "_pdf_bbox", "_pdf_target_rect", "_pdf_es_caja", "_pdf_es_casilla", "_pdf_es_acroform", "_pdf_widget_name"):
                if k in elem_orig:
                    plan_item[k] = elem_orig[k]

            plan_reconstruido.append(plan_item)

    # Deduplicar
    plan_final = _deduplicar_destinos(plan_reconstruido)
    ctx.plan_mapeo = plan_final

    duracion = time.time() - t0
    ctx.log(f"[Stage 3 - Mapper] Mapeo completado por IA: {len(plan_final)} campos asignados en {duracion:.2f}s.")
    return ctx
