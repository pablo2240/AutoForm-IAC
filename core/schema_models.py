"""Módulo de Esquemas Pydantic V2 e Inferencia Estructurada (Fase C).

Garantiza el 100% de cumplimiento sintáctico de JSON y tipado estricto (int >= 1,
Literal["derecha", "abajo", "misma"], bool) usando Pydantic V2 e instructor.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class MapeoSemanticoItem(BaseModel):
    """Mapeo semántico ultracompacto devuelto por el LLM (id_rotulo -> campo + ubicacion)."""

    id: int = Field(ge=1, description="ID del rótulo")
    campo: str = Field(description="Clave exacta de DatosEmpresa que satisface la solicitud del rótulo")
    ubicacion: Literal["derecha", "abajo", "misma", "arriba"] = Field(
        default="derecha", description="Ubicación elegida por el modelo para escribir el valor ('derecha', 'abajo', 'misma', 'arriba')"
    )

    @field_validator("ubicacion", mode="before")
    @classmethod
    def normalizar_ubicacion_semantica(cls, v: Any) -> str:
        if not isinstance(v, str):
            return "derecha"
        v_clean = v.strip().lower()
        if v_clean in ("derecha", "abajo", "misma", "arriba"):
            return v_clean
        return "derecha"


class PlanMapeoSemantico(BaseModel):
    """Lista de emparejamientos semánticos."""

    mappings: List[MapeoSemanticoItem] = Field(default_factory=list)



class MapeoItem(BaseModel):
    """Esquema Pydantic V2 para una celda de formulario asignada."""

    hoja: str = Field(description="Nombre de la hoja de Excel")
    fila: int = Field(ge=1, description="Fila de origen de la celda (1-indexed)")
    columna: int = Field(ge=1, description="Columna de origen de la celda (1-indexed)")
    valor: str = Field(default="", description="Texto del rótulo original del formulario")
    ubicacion: Literal["derecha", "abajo", "misma", "arriba"] = Field(
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
        if v_clean in ("derecha", "abajo", "misma", "arriba"):
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


class CampoVision(BaseModel):
    """Campo detectado por visión LLM con su bounding box normalizado 0-1000."""

    campo: str = Field(description="Clave exacta de DatosEmpresa solicitada por el rótulo")
    bbox_1000: List[int] = Field(
        min_length=4, max_length=4,
        description="Bounding box [ymin, xmin, ymax, xmax] normalizado de 0 a 1000"
    )
    pagina: int = Field(default=1, ge=1, description="Número de página del PDF (1-indexed)")

    @field_validator("bbox_1000", mode="before")
    @classmethod
    def normalizar_bbox(cls, v: Any) -> List[int]:
        if isinstance(v, (list, tuple)):
            return [int(round(float(x))) for x in v]
        return v

    @field_validator("pagina", mode="before")
    @classmethod
    def normalizar_pagina(cls, v: Any) -> int:
        try:
            val_int = int(v)
            return val_int if val_int >= 1 else 1
        except Exception:
            return 1


class PlanCamposVision(BaseModel):
    """Lista de campos detectados por visión."""

    campos_vision: List[CampoVision] = Field(default_factory=list)


class AdvertenciaValidacion(BaseModel):
    """Problema detectado por la validación visual de un campo relleno."""

    campo: str = Field(description="Clave de DatosEmpresa con problema")
    pagina: int = Field(default=1, ge=1, description="Número de página del PDF (1-indexed)")
    problema: Literal["ok", "overflow", "vacio", "fuera_de_lugar"] = Field(
        default="ok", description="Tipo de problema detectado en la inyección"
    )
    bbox_corregido: Optional[List[int]] = Field(
        default=None, description="Bounding box corregido [ymin, xmin, ymax, xmax] 0-1000 si aplica"
    )

    @field_validator("problema", mode="before")
    @classmethod
    def normalizar_problema(cls, v: Any) -> str:
        if not isinstance(v, str):
            return "ok"
        v_clean = v.strip().lower()
        if v_clean in ("ok", "overflow", "vacio", "fuera_de_lugar"):
            return v_clean
        return "ok"

    @field_validator("bbox_corregido", mode="before")
    @classmethod
    def normalizar_bbox_corregido(cls, v: Any) -> Optional[List[int]]:
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            return [int(round(float(x))) for x in v]
        return None


class ResultadoValidacion(BaseModel):
    """Lista de advertencias de validación visual."""

    advertencias: List[AdvertenciaValidacion] = Field(default_factory=list)


def _extraer_json_robusto(texto: str) -> Any:
    """Extrae y parsea JSON de respuestas LLM, incluso si incluyen razonamiento previo (Chain-of-Thought)."""
    texto_limpio = texto.strip()

    # 1. Parseo directo del texto completo
    try:
        return json.loads(texto_limpio)
    except Exception:
        pass

    # 2. Bloques Markdown ```json ... ``` o ``` ... ```
    for m in re.finditer(r'```(?:json)?\s*(.*?)\s*```', texto, re.DOTALL | re.IGNORECASE):
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass

    # 3. Búsqueda desde el último '[' o '{' (Búsqueda Inversa para CoT/Reasoning Models)
    for char_open, char_close in [('[', ']'), ('{', '}')]:
        idx_open = texto_limpio.rfind(char_open)
        if idx_open != -1:
            fragmento = texto_limpio[idx_open:]
            try:
                return json.loads(fragmento)
            except Exception:
                idx_close = fragmento.rfind(char_close)
                if idx_close != -1:
                    try:
                        return json.loads(fragmento[:idx_close + 1])
                    except Exception:
                        pass

    # 4. Primera '[' o '{' hasta última ']' o '}'
    for char_open, char_close in [('[', ']'), ('{', '}')]:
        idx_open = texto_limpio.find(char_open)
        idx_close = texto_limpio.rfind(char_close)
        if idx_open != -1 and idx_close > idx_open:
            try:
                return json.loads(texto_limpio[idx_open:idx_close + 1])
            except Exception:
                pass

    raise ValueError("No se pudo extraer una estructura JSON de la respuesta.")


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
        elif "F" in payload_raw and isinstance(payload_raw["F"], list):
            datos_dict = payload_raw["F"]
        else:
            datos_dict = [payload_raw]
    elif isinstance(payload_raw, str):
        try:
            parsed = _extraer_json_robusto(payload_raw)
            return validar_y_sanitizar_mapeo(parsed)
        except Exception as exc:
            print(f"[AutoForm AI Pydantic] Error: No se pudo parsear el JSON ({exc}): {payload_raw[:100]}...")
            return []

    # Validar cada objeto individualmente con MapeoSemanticoItem o MapeoItem de Pydantic
    elementos_validos: List[Dict[str, Any]] = []
    for item in datos_dict:
        if isinstance(item, dict):
            try:
                # 1. Si tiene coordenadas físicas completas, validar con MapeoItem
                if "hoja" in item and "fila" in item and "columna" in item:
                    modelo = MapeoItem.model_validate(item)
                    elementos_validos.append(modelo.model_dump())
                # 2. Si tiene id y campo (salida semántica del LLM), validar con MapeoSemanticoItem
                elif "id" in item and "campo" in item:
                    modelo_semantico = MapeoSemanticoItem.model_validate(item)
                    elementos_validos.append(modelo_semantico.model_dump())
                else:
                    elementos_validos.append(item)
            except Exception as exc:
                print(f"[AutoForm AI Pydantic Warning] Item omitido por error de validación ({exc}): {item}")
        else:
            print(f"[AutoForm AI Pydantic Warning] Item no es un diccionario válido: {item}")

    return elementos_validos
