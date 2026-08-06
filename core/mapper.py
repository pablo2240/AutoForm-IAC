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


def construir_prompt(mapa_formularios: List[Dict[str, Any]], datos_empresa: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "MapaFormularios": mapa_formularios,
            "DatosEmpresa": datos_empresa,
            "Instrucciones": (
                "Mapea cada etiqueta de formulario con un campo existente en DatosEmpresa. "
                "Usa las reglas de ubicación estrictas descritas en el sistema. "
                "Devuelve solo un arreglo JSON de objetos con hoja, fila, columna, valor, ubicación, campo, requiereMerge y celdasAMergear."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


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
