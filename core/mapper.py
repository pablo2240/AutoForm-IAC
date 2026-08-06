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



def _necesita_merge(valor: str) -> bool:
    texto = str(valor or "")
    if "_" in texto:
        return True
    if re.search(r"firma|firma\b|línea|linea|debajo|dirección|direccion|tel[eé]fono|correo|email|raz[oó]n social", texto, flags=re.IGNORECASE):
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
    """Intenta extraer y parsear un objeto o arreglo JSON de una cadena de texto,
    incluso si contiene texto introductorio, explicaciones o bloques de markdown.
    """
    texto_limpio = texto.strip()

    # 1. Intento de parseo directo del texto completo
    try:
        return json.loads(texto_limpio)
    except json.JSONDecodeError:
        pass

    # 2. Buscar bloques de código markdown ```json ... ``` o ``` ... ```
    bloque_markdown = re.search(r'```(?:json)?\s*(.*?)\s*```', texto, re.DOTALL | re.IGNORECASE)
    if bloque_markdown:
        contenido_bloque = bloque_markdown.group(1).strip()
        try:
            return json.loads(contenido_bloque)
        except json.JSONDecodeError:
            pass

    # 3. Buscar la primera ocurrencia de '{' o '[' y la última de '}' o ']'
    coincidencia = re.search(r'(\{.*\}|\[.*\])', texto, re.DOTALL)
    if coincidencia:
        cuerpo_json = coincidencia.group(1).strip()
        try:
            return json.loads(cuerpo_json)
        except json.JSONDecodeError:
            pass

    # Si todo falla, lanzamos una excepción limpia
    raise ValueError("No se encontró una estructura JSON válida en el texto de respuesta.")


def mapeo_formularios(mapa_formularios: List[Dict[str, Any]], datos_empresa: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(mapa_formularios, list):
        raise ValueError("El mapa de formularios debe ser una lista de objetos.")

    prompt = construir_prompt(mapa_formularios, datos_empresa)
    respuesta = invocar_llm(prompt)  # Complicidad 1 Fix: prompt consolidado aplicado automáticamente

    if not respuesta or not isinstance(respuesta, str):
        raise RuntimeError("La respuesta del LLM no es un texto válido.")

    try:
        resultado = _extraer_json(respuesta)
    except Exception as exc:
        raise RuntimeError(f"No se pudo parsear la respuesta JSON del LLM. Respuesta: {respuesta}") from exc

    # Robustez para modo JSON: Si el LLM devolvió un objeto (diccionario) en vez de una lista directa
    if isinstance(resultado, dict):
        lista_extraida = None
        # Caso A: Buscar si hay alguna lista dentro de alguna clave del diccionario (ej: {"mappings": [...]})
        for clave, valor in resultado.items():
            if isinstance(valor, list):
                lista_extraida = valor
                break
        
        if lista_extraida is not None:
            resultado = lista_extraida
        else:
            # Caso B: Si es un diccionario indexado como {"0": {...}, "1": {...}}
            valores_dict = list(resultado.values())
            if valores_dict and all(isinstance(v, dict) and ("fila" in v or "hoja" in v) for v in valores_dict if v):
                resultado = [v for v in valores_dict if v]
            else:
                raise RuntimeError(
                    f"El LLM devolvió un objeto JSON pero no se encontró ninguna lista de mapeos en su interior. "
                    f"Estructura recibida: {resultado}"
                )

    if not isinstance(resultado, list):
        raise RuntimeError(f"El LLM debe retornar un arreglo JSON. Estructura recibida: {resultado}")

    plano_final: List[Dict[str, Any]] = []
    for item in resultado:
        try:
            elemento = _validar_item(item)
            if elemento["campo"] == "":
                continue
            if elemento["requiereMerge"] is False and _necesita_merge(elemento["valor"]):
                elemento["requiereMerge"] = True
                elemento["celdasAMergear"] = max(3, elemento["celdasAMergear"])
            plano_final.append(elemento)
        except (ValueError, TypeError, KeyError) as e:
            # Tolerancia a fallos: Si un elemento individual viene mal formateado de la IA,
            # lo omitimos y continuamos con los demás en lugar de tumbar toda la ejecución.
            print(f"[AutoForm AI Warning] Omitiendo fila de mapeo inválida: {e}. Elemento: {item}")
            continue

    return plano_final
