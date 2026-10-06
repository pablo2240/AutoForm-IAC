"""Compuerta de plausibilidad (A1): descarta asignaciones de datos a textos que no son campos de captura.

Un LLM puede proponer un campo para cualquier texto del formulario. Antes de aceptarlo (o de sugerirlo en
la vista de verificación) se aplican reglas deterministas y baratas que detectan lo que NO puede ser un
campo de captura de datos de la empresa:

  R1  instrucciones o textos largos (más de ``MAX_PALABRAS`` palabras o ``MAX_CARACTERES`` caracteres)
  R2  preguntas cerradas ("¿Pertenece a algún gremio?")
  R3  instrucciones ("Por favor indicar…", "Marque…", "Seleccione…")
  R4  rótulos que ya traen el valor embebido ("…cumplimiento de su SG-SST:95.0%")
  R5  celdas destino que contienen una marca de casilla ("X", "✓")
  R6  opciones de un grupo de selección (clasificadas por la etapa 2)

Es una puerta de entrada, no un clasificador: ante la duda deja pasar y la confianza (A2) hace el resto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_PALABRAS = 12
MAX_CARACTERES = 100
MARCAS_DE_CASILLA = frozenset({"x", "xx", "✓", "✔", "☑", "☒", "■", "●", "√"})

_PATRON_INSTRUCCION = re.compile(
    r"^\s*(?:por\s+favor|favor\b|nota\b|importante\b|tenga\s+en\s+cuenta|marque|seleccione|diligencie|adjunte|anexe)",
    re.IGNORECASE,
)
_PATRON_VALOR_EMBEBIDO = re.compile(r"\w[^:]{2,}:\s*[\$\(]?\d[\d.,/%\-)]*\s*$")


@dataclass(frozen=True)
class Veredicto:
    """Resultado de evaluar si un rótulo puede recibir un dato de la empresa."""

    plausible: bool
    regla: str = ""
    motivo: str = ""


_PLAUSIBLE = Veredicto(True)


def evaluar_plausibilidad(
    rotulo: Any,
    valor_destino_actual: Any = None,
    tipo_clasificacion: str = "",
) -> Veredicto:
    """Aplica las reglas R1-R6; devuelve el primer motivo por el que NO es un campo de captura."""
    texto = " ".join(str(rotulo or "").split())
    if not texto:
        return _PLAUSIBLE

    if len(texto.split()) > MAX_PALABRAS or len(texto) > MAX_CARACTERES:
        return Veredicto(False, "R1", "Texto largo o instrucción: no es un campo de captura")
    if texto.startswith("¿") or texto.endswith("?"):
        return Veredicto(False, "R2", "Pregunta cerrada: no es un campo de captura de datos")
    if _PATRON_INSTRUCCION.search(texto):
        return Veredicto(False, "R3", "Instrucción del formulario: no es un campo de captura")
    if _PATRON_VALOR_EMBEBIDO.search(texto):
        return Veredicto(False, "R4", "El rótulo ya incluye el valor; no hay nada que diligenciar")
    if str(valor_destino_actual or "").strip().lower() in MARCAS_DE_CASILLA:
        return Veredicto(False, "R5", "La celda destino contiene una marca de casilla de verificación")
    if str(tipo_clasificacion or "").upper() == "OPCION_SELECCION":
        return Veredicto(False, "R6", "Opción de un grupo de selección: no recibe datos de la empresa")
    return _PLAUSIBLE
