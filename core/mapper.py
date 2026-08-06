"""Orquestador de la Fase 2 y Fase 3 de AutoForm AI.

Recibe el mapa visual del formulario, genera el plan de mapeo y extiende el plan
para permitir la escritura física nativa en Excel.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from core.llm_client import invocar_llm


SYSTEM_PROMPT = """Eres un experto en mapeo de formularios Excel. Recibes un arreglo llamado MapaFormularios y un objeto DatosEmpresa. Para cada rótulo de formulario, debes determinar el campo canónico más cercano de DatosEmpresa y proponer la ubicación exacta de escritura.

Cada entrada del MapaFormularios incluye los siguientes campos de contexto visual:
- `tipoEspacioEscritura`: clasifica visualmente el espacio disponible en la celda vecina:
    - "subrayado" → celda vacía con borde inferior (línea de captura _____). Escribe a la DERECHA o ABAJO dependiendo de dónde esté ese subrayado.
    - "cuadro"    → celda vacía con bordes completos (caja de tabla). Prioridad alta para escritura.
    - "merge"     → celda pertenece a un rango combinado (espacio amplio). Escribe SIEMPRE a la derecha o abajo según corresponda.
    - "vacio"     → celda vacía sin bordes. Puede usarse si no hay mejor opción.
    - "ocupado"   → celda ya tiene contenido. NUNCA escribas en esta dirección.
- `anchoLinea`: número de columnas consecutivas que forman la línea de captura a la derecha del rótulo.
    Si anchoLinea > 1, hay múltiples celdas con borde inferior para un solo valor.
- `anchoMergeVecino`: si el vecino derecho es un rango combinado (merge) preexistente en la plantilla, este valor es su ancho físico total en columnas (ej: C3:H3 → anchoMergeVecino=6). Si no hay merge, vale 1.
- `esMergePrincipal`: True si la etiqueta (rótulo) misma ocupa un rango combinado en la plantilla (ej: la celda «NOMBRE/RAZÓN SOCIAL» abarca las columnas A1:C1). Cuando es True, la columna de escritura ya fue corregida automáticamente por el parser para apuntar después del merge. No requiere ajuste adicional de tu parte.
- `coordMerge`: coordenadas del rango del merge de la etiqueta (ej: "A1:C1"). Vacío si la etiqueta es una celda simple.

Reglas estrictas de ubicación (en orden de prioridad):
1. EXCLUSIÓN SUPLENTE: Si el campo pertenece al "Representante Legal Suplente" (y no hay un suplente diferente en DatosEmpresa), OMITIR por completo (no duplicar el Principal).
2. TIPO DE ID [ CC | CE | PAS ]: En casillas de opciones de tipo de documento, asigna una 'X' a la casilla de la opción respectiva ("CC"). NUNCA escribas el número de cédula/NIT dentro de las casillas de opciones.
3. PERSONA CONTACTO EXTERNA: Rótulos como "Nombre y Cargo persona contacto", "Correo persona contacto" corresponden a terceros. OMITIR (no llenar con datos del representante principal ni de la empresa).
4. SECCIÓN PEP: En preguntas PEP ("Goza de reconocimiento...", "Administra recursos...", "PEP Extranjera"), responder "NO". La sub-tabla de detalle PEP ("Nombres y Apellidos", "Entidad Pública", "Cargo", "Fecha vinculación") debe OMITIRSE por completo (no mapear al representante legal ni a nadie en esa sub-tabla).
5. TABLAS / ENCABEZADOS EN FILA: Si la fila actual contiene varios encabezados de tabla seguidos (ej: [Nombre/Razón Social | ID | % Participación]), la ubicación de escritura es SIEMPRE "abajo" (en la fila de datos inmediatamente inferior). NUNCA uses "derecha" sobre un encabezado vecino.
6. Si tipoEspacioEscritura es "subrayado", "cuadro" o "merge" en la derecha y no es un encabezado de tabla → usa "derecha".
7. Si la derecha está "ocupado" (por otro texto o título) pero abajo está libre → usa "abajo".
8. Si derechaVacia es True (y no hay otro título a la derecha) → usa "derecha".
9. Si derechaVacia es False y abajoVacia es True → usa "abajo".
10. Si ambas direcciones están "ocupado" → OMITIR el campo para no sobreescribir etiquetas.

Además, agrega para cada elemento los campos:
- requiereMerge: True si tipoEspacioEscritura es "subrayado" o "merge" Y (anchoLinea > 1 O anchoMergeVecino > 1).
- celdasAMergear: prioridad de valores en este orden:
    1. Si derechaEsMerge es True → usar `anchoMergeVecino` (dimensión física exacta del merge de la plantilla).
    2. Si anchoLinea > 1 → usar `anchoLinea` (línea de captura con celdas simples).
    3. Si requiereMerge es True y ambos valen 1 → usar 3 como mínimo por defecto.

Responde únicamente con JSON válido. Devuelve un arreglo de objetos o bien envuélvelo en un objeto JSON bajo la clave "mappings" (ejemplo: {"mappings": [...]}).
Cada objeto del listado debe tener este formato:
{
  "hoja": "Hoja1",
  "fila": 1,
  "columna": 1,
  "valor": "Razón Social",
  "ubicacion": "derecha",
  "campo": "razon_social",
  "requiereMerge": false,
  "celdasAMergear": 1
}

Solo incluye objetos que tienen ubicacion "derecha" o "abajo".
"""


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
    respuesta = invocar_llm(prompt, sistema=SYSTEM_PROMPT)

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
