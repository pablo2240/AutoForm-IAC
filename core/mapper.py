"""Orquestador de la Fase 2 y Fase 3 de AutoForm AI.

Recibe el mapa visual del formulario, genera el plan de mapeo y extiende el plan
para permitir la escritura física nativa en Excel.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from core import semantic_cache
from core.llm_client import invocar_llm, STRICT_SYSTEM_PROMPT

# Complicidad 1 Fix: Se eliminó el SYSTEM_PROMPT local redundante.
# El prompt del sistema está consolidado en core.llm_client.STRICT_SYSTEM_PROMPT.
# invocar_llm() ya lo aplica automáticamente; no es necesario pasarlo como argumento.



# Claves del parser que necesita la IA para decidir semánticamente la ubicación.
# Los demás campos son internos y no aportan valor al LLM (solo aumentan tokens).
_CLAVES_LLM = {
    "hoja", "fila", "columna", "valor",
    "tipoEspacioEscritura", "anchoLinea", "anchoMergeVecino",
    "derechaVacia", "abajoVacia", "derechaEsMerge", "esMergePrincipal",
    "esCasillaVerificacion",
}

# Campos que no pertenecen a DatosEmpresa directamente pero que siempre
# deben estar disponibles como sinónimos o campos virtuales.
_CAMPOS_VIRTUALES = {"nit_sin_dv", "nit_dv"}


# ──────────────────────────────────────────────────────────────────────────────
# LLM-04: Caché en memoria por hash del mapa de formularios
# ──────────────────────────────────────────────────────────────────────────────

# Caché global de sesión: {hash_mapa: List[Dict]} y {hash_mapa: str (prompt_debug)}
_cache_mapeos: Dict[str, List[Dict[str, Any]]] = {}
_cache_debug: Dict[str, Dict[str, Any]] = {}


def _hash_mapa(mapa_purgado: List[Dict[str, Any]]) -> str:
    """Genera un hash SHA-256 determinísta del mapa purgado para identificar formularios identicos."""
    contenido = json.dumps(mapa_purgado, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()


def get_debug_info(hash_form: str) -> Optional[Dict[str, Any]]:
    """Retorna la información de debug (prompt + respuesta) almacenada para el hash dado."""
    return _cache_debug.get(hash_form)


def _purgar_mapa(mapa: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Elimina claves internas del parser que no aportan al mapeo semántico."""
    return [{k: v for k, v in entrada.items() if k in _CLAVES_LLM} for entrada in mapa]


def _filtrar_datos_empresa(mapa_purgo: List[Dict[str, Any]], datos: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve solo los campos de DatosEmpresa que podrían ser relevantes
    según el vocabulario del formulario actual.  Reduce tokens ~40-60%.
    
    Estrategia: extraer todas las palabras del formulario, luego retener
    solo las claves de DatosEmpresa cuyos sinónimos conocidos aparecen en
    ese vocabulario. Si no hay coincidencia, se incluye la clave igual
    (safe-fallback) para no perder campos por falsos negativos.
    """
    # Sinónimos inversos: campo → indicios textuales que sugieren presencia
    _INDICIOS: Dict[str, List[str]] = {
        "razon_social":          ["nombre", "razon", "empresa", "proveedor", "social"],
        "nit":                   ["nit", "rut", "identificacion", "cc/ce/pas"],
        "cedula":                ["cedula", "c.c", "documento", "identidad", "id"],
        "direccion":             ["direccion", "domicilio", "direccion principal"],
        "ciudad":                ["ciudad", "municipio"],
        "departamento":          ["departamento", "dpto"],
        "telefono":              ["telefono", "tel", "celular", "contacto telefonico"],
        "correo":                ["correo", "email", "e-mail"],
        "pagina_web":            ["web", "pagina", "url", "sitio"],
        "representante_legal":   ["representante", "legal"],
        "representante_nombres": ["nombres"],
        "representante_apellidos": ["apellidos"],
        "pais":                  ["pais", "nacionalidad"],
        "banco":                 ["banco", "bancaria", "financiera"],
        "numero_cuenta":         ["cuenta", "nro cuenta"],
        "tipo_cuenta":           ["tipo cuenta", "tipo de cuenta"],
        "sucursal":              ["sucursal"],
    }

    # Vocabulario del formulario (texto de rótulos, todo en minúsculas)
    vocabulario = " ".join(
        str(e.get("valor", "")).lower() for e in mapa_purgo
    )

    resultado: Dict[str, Any] = {}
    for campo, valor in datos.items():
        indicios = _INDICIOS.get(campo)
        if indicios is None:
            # Clave desconocida en el diccionario de indicios → incluir por seguridad
            resultado[campo] = valor
        elif any(indicio in vocabulario for indicio in indicios):
            resultado[campo] = valor
        # Si no hay coincidencia, se excluye del payload → ahorro de tokens

    return resultado


def construir_prompt(mapa_formularios: List[Dict[str, Any]], datos_empresa: Dict[str, Any]) -> str:
    """Construye el payload JSON compacto para el LLM.
    
    Complicidad 2 Fix:
    - Purga los 6 campos internos del parser (derechaConBorde*, abajoConBorde*, coordMerge, abajoEsMerge).
    - Filtra DatosEmpresa a solo los campos relevantes para el formulario actual.
    - Serializa sin indent ni espacios extra (separators=(',',':')), reduciendo ~60% de tokens.
    """
    mapa_purgado = _purgar_mapa(mapa_formularios)
    datos_filtrados = _filtrar_datos_empresa(mapa_purgado, datos_empresa)

    payload = {
        "F": mapa_purgado,       # MapaFormularios (abreviado para reducir tokens)
        "D": datos_filtrados,    # DatosEmpresa filtrado
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))



# Campos canónicos que siempre requieren espacio amplio (merge o línea larga).
# Se evalúan contra elemento["campo"] (clave canónica) para la heurística de merge.
_CAMPOS_REQUIEREN_MERGE = {
    "razon_social", "direccion", "representante_legal",
    "representante_nombres", "representante_apellidos",
    "correo", "pagina_web", "objeto_social", "actividad_economica",
}

# Indicios textuales en la etiqueta del formulario que sugieren campo extenso.
_PATRON_ETIQUETA_MERGE = re.compile(
    r"firma|\bdirecci[oó]n\b|\bdomicilio\b|\brazon\b|social|nombre\s+completo"
    r"|tel[eé]fono|correo|email|p[aá]gina\s*web|objeto|actividad",
    flags=re.IGNORECASE,
)


def _necesita_merge(etiqueta: str, campo: str) -> bool:
    """Complicidad 3 Fix: evalúa la ETIQUETA del formulario y la CLAVE CANÓNICA
    del campo, NO el valor que se va a escribir.

    Args:
        etiqueta: Texto del rótulo original del formulario (elemento["valor"]).
        campo:    Clave canónica asignada por la IA (elemento["campo"]).

    Returns:
        True si el campo necesita un espacio de escritura amplio (merge).
    """
    # 1. La clave canónica está en el conjunto de campos que requieren merge
    if campo in _CAMPOS_REQUIEREN_MERGE:
        return True
    # 2. El rótulo del formulario tiene indicios de campo extenso
    if _PATRON_ETIQUETA_MERGE.search(str(etiqueta or "")):
        return True
    # 3. La etiqueta contiene guiones de relleno (línea de captura larga inline)
    if "_" in str(etiqueta or ""):
        return True
    return False


def _validar_item(item: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Cada elemento del resultado debe ser un objeto JSON.")

    campo = str(item.get("campo", "")).strip()
    # Si el campo está vacío, la IA decidió no mapear este elemento. Devolvemos vacío sin validar ubicación.
    if not campo:
        return {
            "hoja": str(item.get("hoja", "")),
            "fila": int(item.get("fila", 0) or 0),
            "columna": int(item.get("columna", 0) or 0),
            "valor": str(item.get("valor", "")),
            "ubicacion": "",
            "campo": "",
            "requiereMerge": False,
            "celdasAMergear": 1,
        }

    ubicacion = str(item.get("ubicacion", "")).lower().strip()
    if ubicacion not in {"derecha", "abajo", "misma"}:
        raise ValueError(
            f"Ubicación inválida en el resultado del LLM: {ubicacion!r}. Solo se admite 'derecha', 'abajo' o 'misma'."
        )

    requiere_merge = bool(item.get("requiereMerge", False))
    celdas_a_mergear = int(item.get("celdasAMergear", 1) or 1)
    if celdas_a_mergear < 1:
        celdas_a_mergear = 1

    if requiere_merge and celdas_a_mergear == 1:
        celdas_a_mergear = 3

    return {
        "hoja": str(item.get("hoja", "")),
        "fila": int(item.get("fila", 0) or 0),
        "columna": int(item.get("columna", 0) or 0),
        "valor": str(item.get("valor", "")),
        "ubicacion": ubicacion,
        "campo": campo,
        "requiereMerge": requiere_merge,
        "celdasAMergear": celdas_a_mergear,
    }


def _extraer_json(texto: str) -> Any:
    """Extrae y parsea JSON de la respuesta del LLM.

    Estrategia de 6 pasos ordenados de mayor a menor certeza.
    Paso clave (5): búsqueda inversa desde el último '[' o '{',
    necesaria para modelos de razonamiento que emiten análisis
    en texto plano ANTES del JSON final.
    """
    texto_limpio = texto.strip()

    # 1. Parseo directo del texto completo
    try:
        return json.loads(texto_limpio)
    except json.JSONDecodeError:
        pass

    # 2. Bloques de código markdown ```json ... ``` o ``` ... ```
    bloque_markdown = re.search(r'```(?:json)?\s*(.*?)\s*```', texto, re.DOTALL | re.IGNORECASE)
    if bloque_markdown:
        try:
            return json.loads(bloque_markdown.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Primera '{' hasta última '}' o primera '[' hasta última ']'
    for patron in (r'(\[.*\])', r'(\{.*\})'):
        m = re.search(patron, texto, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

    # 4. Búsqueda INVERSA desde el último '[' — clave para modelos de razonamiento.
    # Estos modelos emiten 1000+ líneas de análisis y colocan el JSON AL FINAL.
    ultimo_corchete = texto_limpio.rfind('[')
    if ultimo_corchete != -1:
        fragmento = texto_limpio[ultimo_corchete:]
        # 4a. Fragmento tal cual
        try:
            return json.loads(fragmento)
        except json.JSONDecodeError:
            pass
        # 4b. Reparar si está truncado: cerrar el último objeto y el array
        pos_ultimo_obj = fragmento.rfind('}')
        if pos_ultimo_obj != -1:
            fragmento_reparado = fragmento[:pos_ultimo_obj + 1].rstrip().rstrip(',') + '\n]'
            try:
                return json.loads(fragmento_reparado)
            except json.JSONDecodeError:
                pass

    # 5. Reparación genérica de array truncado (busca primer '[' en todo el texto)
    try:
        pos_ultimo_obj = texto_limpio.rfind('}')
        if pos_ultimo_obj != -1:
            texto_recortado = texto_limpio[:pos_ultimo_obj + 1].strip()
            if not texto_recortado.endswith(']'):
                texto_recortado += '\n]'
            pos_inicio = texto_recortado.find('[')
            if pos_inicio != -1:
                return json.loads(texto_recortado[pos_inicio:])
    except json.JSONDecodeError:
        pass

    raise ValueError("No se encontró una estructura JSON válida en el texto de respuesta.")


def _procesar_resultado_llm(respuesta: str) -> List[Dict[str, Any]]:
    """FASE C: Extrae y sanitiza la lista de elementos mapeados usando el validador estricto de Pydantic V2."""
    from core import schema_models
    return schema_models.validar_y_sanitizar_mapeo(respuesta)


def _evaluar_cobertura_campos(
    datos_empresa_filtrados: Dict[str, Any],
    mapeos_realizados: List[Dict[str, Any]]
) -> List[str]:
    """Compara las claves esperadas de DatosEmpresa contra las claves realmente asignadas por el LLM.

    Returns:
        Lista de nombres de campos que no fueron asignados a ninguna celda.
    """
    esperados = set(datos_empresa_filtrados.keys())
    asignados = {item["campo"] for item in mapeos_realizados if item.get("campo")}
    faltantes = sorted(list(esperados - asignados))
    return faltantes


def _construir_prompt_focalizado(
    mapa_formularios: List[Dict[str, Any]],
    mapeos_realizados: List[Dict[str, Any]],
    datos_empresa: Dict[str, Any],
    campos_faltantes: List[str]
) -> str:
    """Construye un payload ultra-compacto enviando solo los campos omitidos y las celdas aún no ocupadas."""
    celdas_ocupadas = {
        (item["hoja"], item["fila"], item["columna"])
        for item in mapeos_realizados
    }

    mapa_purgado = _purgar_mapa(mapa_formularios)
    rotulos_libres = [
        elem for elem in mapa_purgado
        if (elem.get("hoja"), elem.get("fila"), elem.get("columna")) not in celdas_ocupadas
    ]

    datos_faltantes = {
        k: datos_empresa[k]
        for k in campos_faltantes
        if k in datos_empresa
    }

    payload = {
        "F": rotulos_libres,
        "D": datos_faltantes,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _fusionar_mapeos(
    mapeos_iniciales: List[Dict[str, Any]],
    mapeos_complementarios: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Combina los mapeos de la llamada principal y la llamada de cobertura sin colisiones de celdas."""
    celdas_existentes = {
        (item["hoja"], item["fila"], item["columna"])
        for item in mapeos_iniciales
    }
    resultado_final = list(mapeos_iniciales)

    for item in mapeos_complementarios:
        clave_celda = (item["hoja"], item["fila"], item["columna"])
        if clave_celda not in celdas_existentes:
            resultado_final.append(item)
            celdas_existentes.add(clave_celda)

    return resultado_final


def mapeo_formularios(mapa_formularios: List[Dict[str, Any]], datos_empresa: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(mapa_formularios, list):
        raise ValueError("El mapa de formularios debe ser una lista de objetos.")

    # LLM-04: Calcular hash del mapa purgado para usar como clave de caché
    mapa_purgado_pre = _purgar_mapa(mapa_formularios)
    form_hash = _hash_mapa(mapa_purgado_pre)

    if form_hash in _cache_mapeos:
        print(f"[AutoForm AI LLM-04] ■ Cache HIT Exacto: Formulario ya procesado (hash {form_hash[:12]}...). Devolviendo resultado en caché.")
        return _cache_mapeos[form_hash]

    # ── FASE B: Caché Semántico Fuzzy (Similaridad de Plantillas con rapidfuzz) ──
    huella_entrante = semantic_cache.generar_huella_formulario(mapa_purgado_pre)
    res_fuzzy = semantic_cache.buscar_plantilla_similar(huella_entrante, umbral=90.0)

    if res_fuzzy is not None:
        id_plantilla, plantilla_guardada, score_similaridad = res_fuzzy
        print(
            f"[AutoForm AI FASE B] ⚡ Caché Semántico HIT (Score: {score_similaridad:.1f}% - Plantilla: {id_plantilla}). "
            f"Adaptando mapeo sin llamar a la API..."
        )
        plan_adaptado = semantic_cache.adaptar_mapeo_plantilla(mapa_formularios, plantilla_guardada)
        _cache_mapeos[form_hash] = plan_adaptado
        _cache_debug[form_hash] = {
            "hash": form_hash,
            "tipo_cache": "SEMANTIC_FUZZY_HIT",
            "score_similaridad": round(score_similaridad, 1),
            "plantilla_coincidente": id_plantilla,
            "rotulos_enviados": len(mapa_purgado_pre),
            "prompt_payload": f"[Caché Semántico Fuzzy {score_similaridad:.1f}% con plantilla {id_plantilla}]",
            "respuesta_llm": json.dumps(plan_adaptado, ensure_ascii=False),
            "campos_mapeados": len(plan_adaptado),
            "campos_faltantes_detectados": [],
        }
        return plan_adaptado

    print(f"[AutoForm AI LLM-04] □ Cache MISS (hash {form_hash[:12]}...). Procesando con LLM...")

    # 1. Llamada Principal al LLM
    prompt_principal = construir_prompt(mapa_formularios, datos_empresa)
    respuesta_principal = invocar_llm(prompt_principal)
    mapeos_iniciales = _procesar_resultado_llm(respuesta_principal)

    # 2. Auditoría de Cobertura en Python (Fase 2 - Enfoque 1)
    mapa_purgado = _purgar_mapa(mapa_formularios)
    datos_filtrados = _filtrar_datos_empresa(mapa_purgado, datos_empresa)
    campos_faltantes = _evaluar_cobertura_campos(datos_filtrados, mapeos_iniciales)

    resultado_final: List[Dict[str, Any]]

    if not campos_faltantes:
        print("[AutoForm AI Coverage] Cobertura 100%: Todos los campos de DatosEmpresa fueron mapeados.")
        resultado_final = mapeos_iniciales
    else:
        # 3. Re-consulta Focalizada (solo si hubo campos omitidos)
        print(f"[AutoForm AI Coverage] Omisión detectada: Faltan {len(campos_faltantes)} campos por mapear: {campos_faltantes}. Ejecutando re-mapeo focalizado...")
        try:
            prompt_focalizado = _construir_prompt_focalizado(
                mapa_formularios, mapeos_iniciales, datos_empresa, campos_faltantes
            )
            respuesta_complementaria = invocar_llm(prompt_focalizado)
            mapeos_complementarios = _procesar_resultado_llm(respuesta_complementaria)

            resultado_final = _fusionar_mapeos(mapeos_iniciales, mapeos_complementarios)
            campos_recuperados = len(resultado_final) - len(mapeos_iniciales)
            print(f"[AutoForm AI Coverage] Re-mapeo exitoso: Se recuperaron {campos_recuperados} campos adicionales.")
        except Exception as exc:
            print(f"[AutoForm AI Warning] La re-consulta de cobertura falló ({exc}). Retornando mapeo inicial.")
            resultado_final = mapeos_iniciales

    # LLM-04: Guardar resultado en caché de sesión
    _cache_mapeos[form_hash] = resultado_final

    # FASE B: Persistir plantilla en el Caché Semántico en disco (config/plantillas_cache.json)
    try:
        semantic_cache.guardar_plantilla_en_cache(form_hash[:16], mapa_purgado_pre, resultado_final)
    except Exception as exc:
        print(f"[AutoForm AI Warning] No se pudo guardar la plantilla en el Caché Semántico: {exc}")

    # LLM-05: Guardar información de debug (prompt + mapa + respuesta)
    _cache_debug[form_hash] = {
        "hash": form_hash,
        "tipo_cache": "LLM_GENERATED",
        "rotulos_enviados": len(mapa_purgado_pre),
        "prompt_payload": prompt_principal,
        "respuesta_llm": respuesta_principal,
        "campos_mapeados": len(resultado_final),
        "campos_faltantes_detectados": campos_faltantes if campos_faltantes else [],
    }

    return resultado_final
