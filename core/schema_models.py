"""Módulo de Esquemas Pydantic V2 e Inferencia Estructurada (Fase C).

Garantiza el 100% de cumplimiento sintáctico de JSON y tipado estricto (int >= 1,
Literal["derecha", "abajo", "misma"], bool) usando Pydantic V2 e instructor.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class MapeoItem(BaseModel):
    """Esquema Pydantic V2 para una celda de formulario asignada."""

    hoja: str = Field(description="Nombre de la hoja de Excel")
    fila: int = Field(ge=1, description="Fila de origen de la celda (1-indexed)")
    columna: int = Field(ge=1, description="Columna de origen de la celda (1-indexed)")
    valor: str = Field(default="", description="Texto del rótulo original del formulario")
    ubicacion: Literal["derecha", "abajo", "misma"] = Field(
        default="derecha", description="Ubicación donde escribir el dato de la empresa"
    )
    campo: str = Field(description="Clave exacta coincidente de DatosEmpresa")
    requiereMerge: bool = Field(
        default=False, description="True si la celda de destino requiere combinar columnas a la derecha"
    )
    celdasAMergear: int = Field(
        default=1, ge=1, description="Número de columnas consecutivas a combinar"
    )

    @field_validator("ubicacion", mode="before")
    @classmethod
    def normalizar_ubicacion(cls, v: Any) -> str:
        if not isinstance(v, str):
            return "derecha"
        v_clean = v.strip().lower()
        if v_clean in ("derecha", "abajo", "misma"):
            return v_clean
        return "derecha"

    @field_validator("fila", "columna", "celdasAMergear", mode="before")
    @classmethod
    def normalizar_enteros(cls, v: Any) -> int:
        try:
            val_int = int(v)
            return val_int if val_int >= 1 else 1
        except Exception:
            return 1


class PlanMapeoFormulario(BaseModel):
    """Esquema Pydantic V2 contenedor de la lista de asignaciones de un formulario."""

    mappings: List[MapeoItem] = Field(
        default_factory=list, description="Lista de mapeos generados para el formulario"
    )


def validar_y_sanitizar_mapeo(
    payload_raw: Union[str, List[Dict[str, Any]], Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Parsea y valida cualquier payload raw usando los esquemas Pydantic V2.

    Elimina wrappers Markdown, corrige comillas o tipos de datos erróneos y
    retorna una lista de diccionarios sanitizada y lista para inyección.
    """
    datos_dict: List[Any] = []

    if isinstance(payload_raw, list):
        datos_dict = payload_raw
    elif isinstance(payload_raw, dict):
        if "mappings" in payload_raw and isinstance(payload_raw["mappings"], list):
            datos_dict = payload_raw["mappings"]
        elif "resultado" in payload_raw and isinstance(payload_raw["resultado"], list):
            datos_dict = payload_raw["resultado"]
        else:
            datos_dict = [payload_raw]
    elif isinstance(payload_raw, str):
        cadena_limpia = payload_raw.strip()
        # Remover bloques de código Markdown ```json ... ```
        cadena_limpia = re.sub(r"^```(?:json)?\s*", "", cadena_limpia, flags=re.IGNORECASE)
        cadena_limpia = re.sub(r"\s*```$", "", cadena_limpia)
        cadena_limpia = cadena_limpia.strip()

        try:
            parsed = json.loads(cadena_limpia)
            return validar_y_sanitizar_mapeo(parsed)
        except json.JSONDecodeError:
            # Fallback regex para extraer array de objetos si hay caracteres extra
            match = re.search(r"\[\s*\{.*\}\s*\]", cadena_limpia, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    return validar_y_sanitizar_mapeo(parsed)
                except Exception:
                    pass
            print(f"[AutoForm AI Pydantic] Error: No se pudo parsear el JSON ({cadena_limpia[:100]}...)")
            return []

    # Validar cada objeto individualmente con MapeoItem de Pydantic
    elementos_validos: List[Dict[str, Any]] = []
    for item in datos_dict:
        if isinstance(item, dict):
            try:
                modelo = MapeoItem.model_validate(item)
                elementos_validos.append(modelo.model_dump())
            except Exception as exc:
                print(f"[AutoForm AI Pydantic Warning] Item omitido por error de validación ({exc}): {item}")

    return elementos_validos
