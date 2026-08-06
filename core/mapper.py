"""Orquestador de la Fase 2 y Fase 3 de AutoForm AI.

Recibe el mapa visual del formulario, genera el plan de mapeo y extiende el plan
para permitir la escritura física nativa en Excel.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

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
        "representante_legal":   ["representante", "firma", "legal"],
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
    """Extrae, valida y estructura la lista de elementos mapeados desde una respuesta textual del LLM."""
    if not respuesta or not isinstance(respuesta, str):
        raise RuntimeError("La respuesta del LLM no es un texto válido.")

    resultado = _extraer_json(respuesta)

    # Robustez si el LLM devolvió un diccionario en lugar de una lista pura
    if isinstance(resultado, dict):
        lista_extraida = None
        for _, valor in resultado.items():
            if isinstance(valor, list):
                lista_extraida = valor
                break
        if lista_extraida is not None:
            resultado = lista_extraida
        else:
            valores_dict = list(resultado.values())
            if valores_dict and all(isinstance(v, dict) and ("fila" in v or "hoja" in v) for v in valores_dict if v):
                resultado = [v for v in valores_dict if v]
            else:
                raise RuntimeError(f"JSON del LLM no contiene lista de mapeos: {resultado}")

    if not isinstance(resultado, list):
        raise RuntimeError(f"El LLM debe retornar un arreglo JSON: {resultado}")

    elementos_validos: List[Dict[str, Any]] = []
    for item in resultado:
        try:
            elemento = _validar_item(item)
            if elemento["campo"] == "":
                continue
            if elemento["requiereMerge"] is False and _necesita_merge(
                elemento["valor"], elemento["campo"]
            ):
                elemento["requiereMerge"] = True
                elemento["celdasAMergear"] = max(3, elemento["celdasAMergear"])
            elementos_validos.append(elemento)
        except (ValueError, TypeError, KeyError) as e:
            print(f"[AutoForm AI Warning] Omitiendo fila de mapeo inválida: {e}. Elemento: {item}")
            continue

    return elementos_validos


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

    # 1. Llamada Principal al LLM
    prompt_principal = construir_prompt(mapa_formularios, datos_empresa)
    respuesta_principal = invocar_llm(prompt_principal)
    mapeos_iniciales = _procesar_resultado_llm(respuesta_principal)

    # 2. Auditoría de Cobertura en Python (Fase 2 - Enfoque 1)
    mapa_purgado = _purgar_mapa(mapa_formularios)
    datos_filtrados = _filtrar_datos_empresa(mapa_purgado, datos_empresa)
    campos_faltantes = _evaluar_cobertura_campos(datos_filtrados, mapeos_iniciales)

    if not campos_faltantes:
        print("[AutoForm AI Coverage] Cobertura 100%: Todos los campos de DatosEmpresa fueron mapeados.")
        return mapeos_iniciales

    # 3. Re-consulta Focalizada (solo si hubo campos omitidos)
    print(f"[AutoForm AI Coverage] Omisión detectada: Faltan {len(campos_faltantes)} campos por mapear: {campos_faltantes}. Ejecutando re-mapeo focalizado...")
    try:
        prompt_focalizado = _construir_prompt_focalizado(
            mapa_formularios, mapeos_iniciales, datos_empresa, campos_faltantes
        )
        respuesta_complementaria = invocar_llm(prompt_focalizado)
        mapeos_complementarios = _procesar_resultado_llm(respuesta_complementaria)

        plano_final = _fusionar_mapeos(mapeos_iniciales, mapeos_complementarios)
        campos_recuperados = len(plano_final) - len(mapeos_iniciales)
        print(f"[AutoForm AI Coverage] Re-mapeo exitoso: Se recuperaron {campos_recuperados} campos adicionales.")
        return plano_final
    except Exception as exc:
        print(f"[AutoForm AI Warning] La re-consulta de cobertura falló ({exc}). Retornando mapeo inicial.")
        return mapeos_iniciales

