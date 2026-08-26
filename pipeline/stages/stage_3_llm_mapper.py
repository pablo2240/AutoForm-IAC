"""Stage 3: LLM Mapper y Búsqueda en Template Store (Pipeline AutoForm AI).

Orquesta el mapeo semántico de campos de dos maneras:
1. Ruta Rápida (Template Store): Si el formulario o uno muy similar ya fue verificado,
   reutiliza la plantilla guardada (0 costo, 0 latencia).
2. Inferencia IA (OpenAI LLM): Si es nuevo, envía únicamente los campos de entrada
   viables (previamente filtrados en Stage 2) junto con su contexto de sección para
   un emparejamiento semántico limpio y sin hard-gates.

HSP Fase 3 — Integración:
  - Pre-LLM: Si la IR está disponible, filtra elementos por tipo (solo FIELD/UNKNOWN)
    y agrupa por sección procesable. Reduce tokens y elimina falsos positivos.
  - Post-LLM: Pasa la respuesta completa por el Validador Determinístico (semantic_validator)
    que aplica autocorrecciones (CC/CE→nit, telefono→celular en Rep. Legal),
    bloquea contradicciones (lugar_expedicion→fecha), y asigna nivel de confianza.
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


# ──────────────────────────────────────────────────────────────────────────────
# HSP Fase 3: Filtro Pre-LLM basado en IR
# ──────────────────────────────────────────────────────────────────────────────

def _construir_campos_viables_desde_ir(
    ctx: PipelineContext,
) -> Optional[List[Dict[str, Any]]]:
    """Si la IR está disponible, filtra elementos por tipo y sección.

    Retorna solo los elementos clasificados como FIELD o UNKNOWN dentro
    de secciones procesables. OPTION, SECTION_TITLE, DECORATIVE,
    INSTRUCTION y LEGAL_TEXT son descartados pre-LLM.

    Returns:
        Lista de campos viables enriquecidos con sección, o None si la IR no está disponible.
    """
    if ctx.documento_ir is None:
        return None

    try:
        from core.spatial_ir import TipoElemento, PertinenciaSeccion
    except ImportError:
        return None

    campos: List[Dict[str, Any]] = []
    id_counter = 0
    tipos_viables = {TipoElemento.FIELD, TipoElemento.UNKNOWN}

    for seccion in ctx.documento_ir.secciones:
        # Short-circuit: secciones marcadas OMITIR_* se saltan completamente
        if seccion.pertinencia in (
            PertinenciaSeccion.OMITIR_TERCEROS,
            PertinenciaSeccion.OMITIR_USO_INTERNO,
            PertinenciaSeccion.OMITIR_LEGAL,
        ):
            continue

        for fila in seccion.filas:
            for elem in fila.elementos:
                # Solo enviar al LLM los elementos clasificados como FIELD o UNKNOWN
                if elem.tipo_elemento not in tipos_viables:
                    continue

                id_counter += 1

                # Buscar el elemento raw original para preservar coordenadas
                elem_orig = elem.propiedades_raw or {}

                campos.append({
                    "id": id_counter,
                    "rotulo": elem.texto,
                    "seccion": seccion.titulo,
                    "tipoEspacioEscritura": elem.direccion_escritura,
                    "tipo_elemento": elem.tipo_elemento.value,
                    "_elem_orig": elem_orig,
                    "_seccion_titulo": seccion.titulo,
                })

    return campos if campos else None


# ──────────────────────────────────────────────────────────────────────────────
# HSP Fase 3: Post-Validación Determinística
# ──────────────────────────────────────────────────────────────────────────────

def _aplicar_validacion_deterministica(
    plan_mapeo: List[Dict[str, Any]],
    ctx: PipelineContext,
) -> List[Dict[str, Any]]:
    """Pasa el plan_mapeo por el Validador Determinístico (semantic_validator).

    Aplica autocorrecciones, estados y niveles de confianza.
    No descarta ítems del plan: solo los enriquece con metadatos de validación
    para que la UI pueda mostrar semáforos y filtros.

    Returns:
        Plan enriquecido con estado, motivo, nivel_confianza y campo_final.
    """
    try:
        from core.semantic_validator import (
            validar_plan_mapeo,
            generar_resumen_validacion,
            EstadoMapeo,
        )
    except ImportError:
        # Si el validador no está disponible, retornar el plan sin cambios
        return plan_mapeo

    # Ejecutar validación completa
    plan_validado = validar_plan_mapeo(
        plan_mapeo,
        ctx.datos_empresa,
        documento_ir=ctx.documento_ir,
    )

    # Generar resumen para observabilidad
    resumen = generar_resumen_validacion(plan_validado)
    ctx.resumen_validacion = resumen

    # Log de resultados
    aprobados = resumen["por_estado"].get("APROBADO", 0)
    revisiones = resumen["por_estado"].get("REVISION", 0)
    descartados = resumen["por_estado"].get("DESCARTADO", 0)
    ctx.log(
        f"[Stage 3b - Validador] Resultado: "
        f"{aprobados} APROBADOS, {revisiones} REVISION, {descartados} DESCARTADOS "
        f"(tasa aprobación: {resumen['tasa_aprobacion']}%)"
    )

    if resumen["autocorrecciones"]:
        for ac in resumen["autocorrecciones"]:
            ctx.log(
                f"[Stage 3b - Validador] Autocorrección: '{ac['rotulo']}' "
                f"→ {ac['original']} → {ac['corregido']}"
            )

    return plan_validado


# ──────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL: ejecutar_stage_3_mapper
# ──────────────────────────────────────────────────────────────────────────────

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
            # Validar incluso plantillas guardadas (pueden tener autocorrecciones pendientes)
            ctx.plan_mapeo = _aplicar_validacion_deterministica(ctx.plan_mapeo, ctx)
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
                # Validar incluso plantillas difusas
                ctx.plan_mapeo = _aplicar_validacion_deterministica(ctx.plan_mapeo, ctx)
                return ctx

    # ── RUTA 2: Inferencia con IA (LLM) ──
    ctx.log("[Stage 3 - Mapper] Consultando modelo de lenguaje (OpenAI)...")
    
    # HSP Fase 3: Intentar filtro inteligente desde la IR
    campos_viables_ir = _construir_campos_viables_desde_ir(ctx)
    
    if campos_viables_ir is not None:
        # Ruta HSP: campos pre-filtrados por tipo de elemento desde la IR
        campos_viables = campos_viables_ir
        total_raw = len(ctx.elementos_raw)
        total_filtrado = len(campos_viables)
        ctx.log(
            f"[Stage 3 - Pre-LLM] Filtro IR aplicado: {total_raw} elementos → "
            f"{total_filtrado} campos viables ({total_raw - total_filtrado} descartados pre-LLM: "
            f"OPTION, DECORATIVE, LEGAL_TEXT, SECTION_TITLE)."
        )
    else:
        # Fallback: usar clasificación de Stage 2 (flujo existente)
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
            # Fallback último: elementos crudos
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
                # HSP: preservar contexto de sección y tipo para el validador
                "seccion": c_info.get("_seccion_titulo") or c_info.get("seccion", ""),
                "tipo_elemento": c_info.get("tipo_elemento", "FIELD"),
            }

            # Preservar metadatos de PDF
            for k in ("_pdf_page", "_pdf_bbox", "_pdf_target_rect", "_pdf_es_caja", "_pdf_es_casilla", "_pdf_es_acroform", "_pdf_widget_name"):
                if k in elem_orig:
                    plan_item[k] = elem_orig[k]

            plan_reconstruido.append(plan_item)

    # Deduplicar
    plan_final = _deduplicar_destinos(plan_reconstruido)

    # ── HSP Fase 3: Post-Validación Determinística ──
    plan_final = _aplicar_validacion_deterministica(plan_final, ctx)

    ctx.plan_mapeo = plan_final

    duracion = time.time() - t0
    ctx.log(f"[Stage 3 - Mapper] Mapeo completado por IA: {len(plan_final)} campos asignados en {duracion:.2f}s.")
    return ctx
