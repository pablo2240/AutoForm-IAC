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

from core.llm_client import consultar_llm_seccion_instructor, invocar_llm
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
        elif ubic == "arriba":
            coord_dest = (hoja, max(1, fila - 1), col)
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
# HSP Fase 3 & Capa 1: Chunking por SeccionIR y Diff Loop (Auditoría)
# ──────────────────────────────────────────────────────────────────────────────

def _construir_lotes_secciones_desde_ir(
    ctx: PipelineContext,
) -> Optional[List[Tuple[str, List[Dict[str, Any]]]]]:
    """Si la IR está disponible, filtra elementos por tipo y los agrupa por sección.

    Retorna una lista de tuplas (titulo_seccion, campos_viables_seccion) donde
    cada campo contiene un ID numérico global continuo.
    """
    if ctx.documento_ir is None:
        return None

    try:
        from core.spatial_ir import TipoElemento, PertinenciaSeccion
    except ImportError:
        return None

    lotes: List[Tuple[str, List[Dict[str, Any]]]] = []
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

        campos_seccion: List[Dict[str, Any]] = []
        for fila in seccion.filas:
            textos_fila = [e.texto.strip() for e in fila.elementos if e.texto and e.texto.strip()]
            contexto_fila = " | ".join(textos_fila)

            for elem in fila.elementos:
                if elem.tipo_elemento not in tipos_viables:
                    continue

                id_counter += 1
                elem_orig = elem.propiedades_raw or {}
                vecino_abajo = str(elem.vecino_abajo_texto or elem_orig.get("vecino_abajo_texto") or elem_orig.get("vecino_abajo") or "").strip()

                campos_seccion.append({
                    "id": id_counter,
                    "rotulo": elem.texto,
                    "seccion": seccion.titulo,
                    "contexto_fila": contexto_fila,
                    "vecino_abajo": vecino_abajo,
                    "tipoEspacioEscritura": elem.direccion_escritura,
                    "tipo_elemento": elem.tipo_elemento.value,
                    "_elem_orig": elem_orig,
                    "_seccion_titulo": seccion.titulo,
                })

        if campos_seccion:
            lotes.append((seccion.titulo, campos_seccion))

    return lotes if lotes else None


def _agrupar_en_macro_lotes(
    lotes_secciones: List[Tuple[str, List[Dict[str, Any]]]],
    tamano_objetivo: int = 18,
    max_lotes: int = 4,
) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Agrupa secciones pequeñas contiguas en macro-lotes óptimos (12 a 25 campos).
    
    Reduce drásticamente el número de peticiones HTTP al LLM, permitiendo
    procesar formularios complejos en paralelo en <3 segundos.
    """
    if not lotes_secciones:
        return []

    if len(lotes_secciones) <= max_lotes and max(len(c) for _, c in lotes_secciones) <= 25:
        return lotes_secciones

    macro_lotes: List[Tuple[str, List[Dict[str, Any]]]] = []
    titulos_acum: List[str] = []
    campos_acum: List[Dict[str, Any]] = []

    for titulo_sec, campos_sec in lotes_secciones:
        titulos_acum.append(titulo_sec)
        campos_acum.extend(campos_sec)

        if len(campos_acum) >= tamano_objetivo:
            titulo_combinado = " / ".join(titulos_acum[:2])
            if len(titulos_acum) > 2:
                titulo_combinado += f" (+{len(titulos_acum)-2} subsecciones)"
            macro_lotes.append((titulo_combinado, list(campos_acum)))
            titulos_acum = []
            campos_acum = []

    if campos_acum:
        if macro_lotes and len(campos_acum) < 6:
            prev_tit, prev_cam = macro_lotes[-1]
            macro_lotes[-1] = (prev_tit, prev_cam + campos_acum)
        else:
            titulo_combinado = " / ".join(titulos_acum[:2])
            if len(titulos_acum) > 2:
                titulo_combinado += f" (+{len(titulos_acum)-2} subsecciones)"
            macro_lotes.append((titulo_combinado, list(campos_acum)))

    return macro_lotes


def _ejecutar_diff_loop_seccion(
    campos_seccion: List[Dict[str, Any]],
    mapeos_seccion: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
    titulo_seccion: str,
    ctx: PipelineContext,
) -> List[Dict[str, Any]]:
    """Capa 2: Diff Loop de Auditoría y Reconciliación en Python ($0 costo API).

    Calcula: campos_omitidos = campos_viables_seccion - campos_mapeados_exitosamente.
    Si hay campos omitidos y la empresa tiene datos disponibles en este dominio,
    ejecuta rescate determinista inmediato.
    """
    ids_viables = {c["id"]: c for c in campos_seccion}
    ids_mapeados = {m["id"] for m in mapeos_seccion if m.get("campo")}
    ids_omitidos = set(ids_viables.keys()) - ids_mapeados

    if not ids_omitidos:
        return mapeos_seccion

    try:
        from core.coverage_engine import (
            PAT_SECCION_REP_LEGAL,
            PAT_SECCION_FINANCIERO,
            PAT_SECCION_EMPRESA,
            PATRONES_SWEEP,
        )
    except ImportError:
        return mapeos_seccion

    titulo_norm = titulo_seccion.lower()
    campos_asignados = {m["campo"] for m in mapeos_seccion}
    mapeos_rescatados = list(mapeos_seccion)
    rescates_count = 0

    for id_omitido in sorted(ids_omitidos):
        c_info = ids_viables[id_omitido]
        rotulo_txt = c_info["rotulo"]
        rotulo_limpio = re.sub(r"[:：_\.\s]+$", "", rotulo_txt).strip()

        for pat_sec, pat_rot, campo_dest, dir_fall in PATRONES_SWEEP:
            # Si el patrón de sección o el contexto aplican
            if (pat_sec.search(titulo_norm) or not (PAT_SECCION_REP_LEGAL.search(titulo_norm) or PAT_SECCION_FINANCIERO.search(titulo_norm))):
                if pat_rot.search(rotulo_txt) or pat_rot.search(rotulo_limpio):
                    if campo_dest not in campos_asignados and datos_empresa.get(campo_dest):
                        mapeos_rescatados.append({
                            "id": id_omitido,
                            "campo": campo_dest,
                            "ubicacion": c_info.get("tipoEspacioEscritura", dir_fall),
                        })
                        campos_asignados.add(campo_dest)
                        rescates_count += 1
                        break

    # ── Capa 3: Rescate Semántico Vectorial Local (FastEmbed) ──
    ids_pendientes = set(ids_omitidos) - {m["id"] for m in mapeos_rescatados}
    if ids_pendientes:
        try:
            from core.fastembed_matcher import buscar_rescate_vectorial
            candidatos_disponibles = [
                k for k in datos_empresa.keys()
                if k not in campos_asignados and datos_empresa.get(k)
            ]
            for id_pend in sorted(ids_pendientes):
                c_info = ids_viables[id_pend]
                rot_txt = c_info["rotulo"]
                res_vector = buscar_rescate_vectorial(rot_txt, candidatos_disponibles, umbral=0.68)
                if res_vector is not None:
                    campo_res, score = res_vector
                    mapeos_rescatados.append({
                        "id": id_pend,
                        "campo": campo_res,
                        "ubicacion": c_info.get("tipoEspacioEscritura", "derecha"),
                    })
                    campos_asignados.add(campo_res)
                    if campo_res in candidatos_disponibles:
                        candidatos_disponibles.remove(campo_res)
                    rescates_count += 1
                    ctx.log(
                        f"[Stage 3 - FastEmbed] 🧠 Rescate vectorial: '{rot_txt}' → '{campo_res}' (Score: {score*100:.1f}%)"
                    )
        except Exception:
            pass

    if rescates_count > 0:
        ctx.log(
            f"[Stage 3 - Diff Loop] ⚡ Sección '{titulo_seccion}': {len(ids_omitidos)} omitidos detectados → "
            f"{rescates_count} rescatados exitosamente por auditoría y vectores."
        )

    return mapeos_rescatados


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
            try:
                from core.coverage_engine import ejecutar_pase_cobertura_exhaustiva
                ctx.plan_mapeo = ejecutar_pase_cobertura_exhaustiva(
                    ctx.plan_mapeo, ctx.datos_empresa, documento_ir=ctx.documento_ir, elementos_raw=ctx.elementos_raw
                )
            except ImportError:
                pass
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
                try:
                    from core.coverage_engine import ejecutar_pase_cobertura_exhaustiva
                    ctx.plan_mapeo = ejecutar_pase_cobertura_exhaustiva(
                        ctx.plan_mapeo, ctx.datos_empresa, documento_ir=ctx.documento_ir, elementos_raw=ctx.elementos_raw
                    )
                except ImportError:
                    pass
                return ctx

    # ── RUTA 2: Inferencia con IA (OpenAI + Instructor) ──
    ctx.log("[Stage 3 - Mapper] Consultando modelo de lenguaje con Chunking por SeccionIR...")
    
    from core.profile_manager import estructurar_perfil_taxonomia
    taxonomia_d = estructurar_perfil_taxonomia(ctx.datos_empresa)

    lotes_secciones_raw = _construir_lotes_secciones_desde_ir(ctx)
    asignaciones_raw: List[Dict[str, Any]] = []
    todos_campos_viables: List[Dict[str, Any]] = []

    if lotes_secciones_raw is not None:
        macro_lotes = _agrupar_en_macro_lotes(lotes_secciones_raw)
        total_macro = len(macro_lotes)
        total_campos = sum(len(campos) for _, campos in macro_lotes)
        total_raw = len(ctx.elementos_raw)
        ctx.log(
            f"[Stage 3 - Pre-LLM] Filtro IR aplicado: {total_raw} elementos crudos → "
            f"{total_campos} campos viables en {total_macro} macro-lotes concurrentes."
        )

        import concurrent.futures

        def _procesar_lote_concurrente(idx: int, titulo_lote: str, campos_lote: List[Dict[str, Any]]):
            ctx.log(f"[Stage 3 - Chunking] Procesando Lote ({idx}/{total_macro}): '{titulo_lote}' ({len(campos_lote)} campos)...")
            mapeos = consultar_llm_seccion_instructor(campos_lote, taxonomia_d, titulo_lote)
            mapeos = _ejecutar_diff_loop_seccion(campos_lote, mapeos, ctx.datos_empresa, titulo_lote, ctx)
            return mapeos

        max_workers = min(4, total_macro)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futuros = [
                executor.submit(_procesar_lote_concurrente, idx, tit, campos)
                for idx, (tit, campos) in enumerate(macro_lotes, 1)
            ]
            for fut, (_, campos) in zip(futuros, macro_lotes):
                res_lote = fut.result()
                asignaciones_raw.extend(res_lote)
                todos_campos_viables.extend(campos)
    else:
        # Fallback sin IR: usar clasificación de Stage 2
        filas_map: Dict[Tuple[str, int], List[str]] = {}
        for elem in ctx.elementos_clasificados:
            h = str(elem.get("hoja", ""))
            f = int(elem.get("fila", 0) or 0)
            txt = str(elem.get("valor") or elem.get("rotulo") or "").strip()
            if txt:
                filas_map.setdefault((h, f), []).append(txt)

        campos_viables = [
            {
                "id": idx + 1,
                "rotulo": str(elem.get("valor") or elem.get("rotulo") or "").strip(),
                "seccion": str(elem.get("seccion_padre", "INFORMACIÓN GENERAL")),
                "contexto_fila": " | ".join(filas_map.get((str(elem.get("hoja", "")), int(elem.get("fila", 0) or 0)), [str(elem.get("valor") or elem.get("rotulo") or "").strip()])),
                "vecino_abajo": str(elem.get("vecino_abajo_texto") or elem.get("vecino_abajo") or "").strip(),
                "tipoEspacioEscritura": str(elem.get("tipoEspacioEscritura", "derecha")),
                "_elem_orig": elem,
            }
            for idx, elem in enumerate(ctx.elementos_clasificados)
            if elem.get("es_campo_viable", True)
        ]

        if not campos_viables:
            campos_viables = [
                {
                    "id": idx + 1,
                    "rotulo": str(elem.get("valor") or elem.get("rotulo") or "").strip(),
                    "seccion": "INFORMACIÓN GENERAL",
                    "contexto_fila": str(elem.get("valor") or elem.get("rotulo") or "").strip(),
                    "vecino_abajo": str(elem.get("vecino_abajo_texto") or elem.get("vecino_abajo") or "").strip(),
                    "tipoEspacioEscritura": str(elem.get("tipoEspacioEscritura", "derecha")),
                    "_elem_orig": elem,
                }
                for idx, elem in enumerate(ctx.elementos_raw or [])
            ]

        # Chunking de seguridad de 15 en 15 campos
        CHUNK_SIZE = 15
        for i in range(0, len(campos_viables), CHUNK_SIZE):
            chunk = campos_viables[i:i + CHUNK_SIZE]
            mapeos_chunk = consultar_llm_seccion_instructor(chunk, taxonomia_d, "GENERAL")
            mapeos_chunk = _ejecutar_diff_loop_seccion(chunk, mapeos_chunk, ctx.datos_empresa, "GENERAL", ctx)
            asignaciones_raw.extend(mapeos_chunk)

        todos_campos_viables = campos_viables

    # Reconstruir coordenadas físicas
    indice_campos = {c["id"]: c for c in todos_campos_viables}
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
            if ubic not in ("derecha", "abajo", "misma", "arriba"):
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

    # ── Stage 3c: Pase de Cobertura y Exhaustividad Semántica (Coverage Engine) ──
    try:
        from core.coverage_engine import ejecutar_pase_cobertura_exhaustiva
        plan_final = ejecutar_pase_cobertura_exhaustiva(
            plan_final,
            ctx.datos_empresa,
            documento_ir=ctx.documento_ir,
            elementos_raw=ctx.elementos_raw,
        )
    except ImportError:
        pass

    ctx.plan_mapeo = plan_final

    duracion = time.time() - t0
    ctx.log(f"[Stage 3 - Mapper] Mapeo completado por IA + Cobertura: {len(plan_final)} campos asignados en {duracion:.2f}s.")
    return ctx
