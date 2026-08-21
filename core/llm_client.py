"""Cliente LLM para AutoForm AI usando OpenAI API (gpt-4o / gpt-4o-mini)."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import openai
except ImportError:
    openai = None  # type: ignore

try:
    import instructor
except ImportError:
    instructor = None  # type: ignore

from core.schema_models import PlanMapeoSemantico
import requests


try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _manual_load_dotenv(dotenv_path: str = ".env") -> None:
    path = Path(dotenv_path)
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            content = line.strip()
            if not content or content.startswith("#"):
                continue
            if "=" not in content:
                continue
            key, value = content.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

if load_dotenv is not None:
    load_dotenv()
else:
    _manual_load_dotenv()

# Soporte automático para Streamlit Community Cloud Secrets (st.secrets)
try:
    import streamlit as st
    if hasattr(st, "secrets"):
        for k, v in st.secrets.items():
            if isinstance(v, str) and k not in os.environ:
                os.environ[k] = v
except Exception:
    pass

# OpenAI Configuration (Motor Estándar)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# Azure OpenAI Configuration (Motor Corporativo)
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1-mini")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")



STRICT_SYSTEM_PROMPT = """## ROL Y PERSONA
Eres AutoForm AI Master Cognitive Engine, el modelo de inteligencia artificial experto en la interpretación semántica y contextual de licitaciones, pliegos de condiciones y formularios corporativos oficiales de Colombia e Hispanoamérica.

## TAXONOMÍA MAESTRA DE DATOS ("D")
Los datos maestros de la empresa se organizan en 3 dominios taxonómicos jerárquicos:
1. `empresa`:
   - `identidad`: `razon_social` (Nombre/Razón Social de la persona jurídica), `nit` (Número de Identificación Tributaria), `tipo_sociedad` (S.A.S, S.A., Ltda).
   - `ubicacion`: `direccion` (Domicilio principal), `ciudad` (Municipio/Ciudad fiscal), `departamento`, `pais`.
   - `contacto`: `telefono` (PBX institucional), `correo` (Email institucional/notificaciones), `pagina_web`.
2. `representante_legal`:
   - `identidad`: `representante_legal` (Nombre completo del apoderado), `representante_nombres` (Primer y segundo nombre), `representante_apellidos` (Primer y segundo apellido), `tipo_documento` (C.C.), `cedula` (Número de documento de la persona natural), `expedicion` (Ciudad/Lugar donde se expidió la cédula).
   - `contacto`: `correo`, `telefono`.
3. `financiero`:
   - `banco`: `banco` (Nombre de la entidad financiera), `sucursal`.
   - `cuenta`: `numero_cuenta` (Número de cuenta bancaria), `tipo_cuenta` (Ahorros / Corriente).

## CONTEXTO Y ENTRADAS
Recibes un objeto JSON con:
1. "F": Arreglo de rótulos o preguntas extraídos del formulario. Cada elemento incluye:
   - "id": Identificador numérico único.
   - "rotulo": Texto original detectado.
   - "seccion": Título o encabezado contextual de la sección donde reside el rótulo.
2. "D": Objeto con la Taxonomía Maestra de la empresa descrita arriba.

## PRINCIPIOS DE INFERENCIA SEMÁNTICA POR CATEGORÍA (CATEGORY-FIRST MATCHING)

### ETAPA 1: ASIGNACIÓN SEGÚN EL DOMINIO DE LA SECCIÓN
- Si la sección o el rótulo hace referencia a la EMPRESA / PROPONENTE / SOLICITANTE / PERSONA JURÍDICA:
  * Rótulos que soliciten nombre de la empresa, denominación social, solicitante -> "razon_social"
  * Rótulos de NIT, RUT, Identificación Tributaria -> "nit"
  * Rótulos de Domicilio, Sede Principal, Dirección -> "direccion"
  * Rótulos de Municipio, Ciudad de domicilio -> "ciudad"
  * Rótulos de Teléfono corporativo, PBX -> "telefono"
  * Rótulos de Email institucional -> "correo"

- Si la sección o el rótulo hace referencia al REPRESENTANTE LEGAL / PERSONA NATURAL / APODERADO:
  * Rótulos de Nombre del Representante, Representante Legal -> "representante_legal"
  * Rótulos específicos de Primer/Segundo Nombre -> "representante_nombres"
  * Rótulos específicos de Primer/Segundo Apellido -> "representante_apellidos"
  * Rótulos de C.C., Cédula, Documento de Identidad, No. de Documento del Representante -> "cedula"
  * Rótulos de Lugar o Ciudad de Expedición del documento -> "expedicion" (ciudad/lugar, ej. "Envigado").

- Si la sección o el rótulo hace referencia a INFORMACIÓN BANCARIA / FINANCIERA:
  * Rótulos de Banco, Entidad Financiera -> "banco"
  * Rótulos de Número de Cuenta, No. Cuenta -> "numero_cuenta"
  * Rótulos de Tipo de Cuenta (Ahorros/Corriente) -> "tipo_cuenta"

### ETAPA 2: BARRERAS SEMÁNTICAS NEGATIVAS (ANTI-CONFUSIÓN ESTRICTO)
- NUNCA cruces dominios:
  * NO asignes "cedula" a rótulos de NIT de la empresa.
  * NO asignes "nit" a casillas de cédula del representante.
  * NO asignes "razon_social" a casillas de representante legal persona natural.
  * NO asignes "expedicion" a rótulos que pidan FECHA de expedición (día/mes/año). 'expedicion' contiene exclusivamente la CIUDAD o LUGAR.
  * NO asignes datos a porcentajes de participación accionaria (% de acciones).
  * NO asignes datos a instrucciones de anexos o copias de documentos (ej. 'Adjuntar copia del RUT', 'Fotocopia de cédula').

### ETAPA 3: TEXTOS DECLARATIVOS INLINE Y CASILLAS
- Si el rótulo contiene marcadores inline como `____` dentro de un texto declarativo (ej: 'Yo, _____ identificado con documento _____ expedido en _____'):
  * Asigna en orden secuencial: "representante_legal" → "cedula" → "expedicion".

### ETAPA 4: AUDITORÍA DE CERO ALUCINACIÓN Y UNICIDAD
- Si el formulario solicita un dato que no existe en "D" (ej. Matrícula Mercantil, CIIU, Sector Económico), OMITE ESE RÓTULO (no incluyas su id).
- UNICIDAD: Cada campo de "D" debe asignarse a un único id para evitar sobreescrituras repetidas.

## FORMATO DE SALIDA (ESTRICTO JSON)
Responde ÚNICAMENTE con un objeto JSON válido con la clave "mappings":
{
  "mappings": [
    {"id": 1, "campo": "razon_social"},
    {"id": 2, "campo": "nit"},
    {"id": 3, "campo": "representante_legal"},
    {"id": 4, "campo": "cedula"}
  ]
}

## EJEMPLOS FEW-SHOT EN CONTEXTO (FORMULARIOS COLOMBIANOS)

Ejemplo 1 (Datos Básicos del Proponente):
Rótulo: {"id": 1, "rotulo": "1. DATOS GENERALES DE LA SOCIEDAD SOLICITANTE / RAZÓN SOCIAL:", "seccion": "INFORMACIÓN DE VINCULACIÓN"}
Asignación: {"id": 1, "campo": "razon_social"}

Ejemplo 2 (Texto Declarativo Inline con Guiones):
Rótulo: {"id": 5, "rotulo": "Yo, _____ identificado con C.C. No. _____ expedida en _____", "seccion": "DECLARACIÓN JURAMENTADA"}
Asignación: {"id": 5, "campo": "representante_legal"}

Ejemplo 3 (Cédula de Ciudadanía / C.C.):
Rótulo: {"id": 8, "rotulo": "C.C. No. / Documento de Identidad:", "seccion": "DATOS DEL REPRESENTANTE LEGAL"}
Asignación: {"id": 8, "campo": "cedula"}

Ejemplo 4 (NIT Empresa):
Rótulo: {"id": 9, "rotulo": "NIT / Identificación Tributaria No.:", "seccion": "DATOS TRIBUTARIOS EMPRESA"}
Asignación: {"id": 9, "campo": "nit"}

## FORMATO DE SALIDA (ESTRICTO JSON — SIN UBICACION)
Tu única tarea es emparejar rótulos con claves del perfil de empresa.
La ubicación física de escritura la calcula el sistema Python automáticamente.
Responde ÚNICAMENTE con un objeto JSON válido con la clave "mappings":
{
  "mappings": [
    {"id": 1, "campo": "razon_social"},
    {"id": 2, "campo": "nit"},
    {"id": 3, "campo": "cedula"}
  ]
}"""


def _consultar_openai(
    prompt_usuario: str,
    sistema: str = "",
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    """Invocación optimizada a la API oficial de OpenAI (gpt-4o-mini / gpt-4o)."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY no configurada en .env")

    # Modelos candidatos para OpenAI
    modelos_openai = [OPENAI_MODEL, "gpt-4.1-mini", "gpt-4o-mini", "gpt-4o"]

    modelos_unicos = [m for idx, m in enumerate(modelos_openai) if m and m not in modelos_openai[:idx]]

    ultimo_exc_openai: Exception = RuntimeError("Fallaron todos los intentos con OpenAI API.")

    for mod_openai in modelos_unicos:
        # Opción A: Usar la librería 'instructor' si está disponible
        if instructor is not None and openai is not None:
            try:
                raw_client = openai.OpenAI(api_key=OPENAI_API_KEY)
                client = instructor.from_openai(raw_client)
                mensajes_inst = []
                if sistema:
                    mensajes_inst.append({"role": "system", "content": sistema})
                mensajes_inst.append({"role": "user", "content": prompt_usuario})

                res_pydantic: PlanMapeoSemantico = client.chat.completions.create(
                    model=mod_openai,
                    response_model=PlanMapeoSemantico,
                    max_retries=2,
                    messages=mensajes_inst,
                    temperature=0.0,
                    seed=42,
                )
                if res_pydantic and res_pydantic.mappings:
                    return res_pydantic.model_dump_json()
            except Exception:
                pass

        # Opción B: Usar REST API nativa con fallback de response_format
        mensajes: List[Dict[str, str]] = []
        if sistema:
            mensajes.append({"role": "system", "content": sistema})
        mensajes.append({"role": "user", "content": prompt_usuario})

        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        formatos_resp = [{"type": "json_object"}] if json_mode else [None]

        for fmt in formatos_resp:
            cuerpo: Dict[str, Any] = {
                "model": mod_openai,
                "messages": mensajes,
                "temperature": 0.0,
                "seed": 42,
            }

            if fmt:
                cuerpo["response_format"] = fmt

            try:
                respuesta = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=cuerpo,
                    timeout=timeout,
                )
                if respuesta.status_code == 400:
                    ultimo_exc_openai = RuntimeError(f"Error 400 en OpenAI API ({mod_openai}): {respuesta.text}")
                    continue
                respuesta.raise_for_status()
                datos = respuesta.json()
                choices = datos.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    content = msg.get("content", "").strip()
                    if content:
                        return content
            except Exception as exc:
                ultimo_exc_openai = exc
                continue

    raise ultimo_exc_openai


def _consultar_azure_openai(
    prompt_usuario: str,
    sistema: str = "",
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    """Invocación optimizada a Azure OpenAI Service con instructor y REST fallback."""
    if not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_API_KEY:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT o AZURE_OPENAI_API_KEY no configuradas en .env")

    # Opción A: Usar 'instructor' con cliente AzureOpenAI
    if instructor is not None and openai is not None and hasattr(openai, "AzureOpenAI"):
        try:
            raw_client = openai.AzureOpenAI(
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_key=AZURE_OPENAI_API_KEY,
                api_version=AZURE_OPENAI_API_VERSION,
            )
            client = instructor.from_openai(raw_client)
            mensajes_inst = []
            if sistema:
                mensajes_inst.append({"role": "system", "content": sistema})
            mensajes_inst.append({"role": "user", "content": prompt_usuario})

            res_pydantic: PlanMapeoSemantico = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT_NAME,
                response_model=PlanMapeoSemantico,
                max_retries=2,
                messages=mensajes_inst,
                temperature=0.0,
                seed=42,
            )
            if res_pydantic and res_pydantic.mappings:
                return res_pydantic.model_dump_json()
        except Exception as exc:
            print(f"[AutoForm AI Azure Warning] Instructor Azure falló ({exc}). Intentando REST directo...")

    # Opción B: Usar REST API nativa de Azure OpenAI
    mensajes: List[Dict[str, str]] = []
    if sistema:
        mensajes.append({"role": "system", "content": sistema})
    mensajes.append({"role": "user", "content": prompt_usuario})

    endpoint_limpio = AZURE_OPENAI_ENDPOINT.rstrip("/")
    url_azure = f"{endpoint_limpio}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"

    headers = {
        "api-key": AZURE_OPENAI_API_KEY,
        "Content-Type": "application/json",
    }

    cuerpo: Dict[str, Any] = {
        "messages": mensajes,
        "temperature": 0.0,
        "seed": 42,
    }
    if json_mode:
        cuerpo["response_format"] = {"type": "json_object"}

    try:
        respuesta = requests.post(url_azure, headers=headers, json=cuerpo, timeout=timeout)
        respuesta.raise_for_status()
        datos = respuesta.json()
        choices = datos.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "").strip()
            if content:
                return content
    except Exception as exc:
        raise RuntimeError(f"Error en llamada a Azure OpenAI ({AZURE_OPENAI_DEPLOYMENT_NAME}): {exc}")

    raise RuntimeError("Azure OpenAI no devolvió ninguna respuesta válida.")


def consultar_llm(
    prompt_usuario: str,
    sistema: Optional[str] = None,
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    modelo_nombre = AZURE_OPENAI_DEPLOYMENT_NAME if (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY) else OPENAI_MODEL
    if sistema is None:
        sistema = f"Eres el asistente inteligente de AutoForm AI, impulsado por {modelo_nombre}. Responde únicamente en formato JSON válido."

    # 1. Prioridad: Azure OpenAI Corporativo
    if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY:
        try:
            return _consultar_azure_openai(
                prompt_usuario, sistema=sistema, json_mode=json_mode, timeout=timeout
            )
        except Exception as exc_azure:
            print(f"[AutoForm AI Warning] Falló Azure OpenAI ({exc_azure}). Probando fallback...")

    # 2. Respaldo: OpenAI API directa
    if OPENAI_API_KEY:
        return _consultar_openai(
            prompt_usuario, sistema=sistema, json_mode=json_mode, timeout=timeout
        )

    raise RuntimeError(
        "No se configuró ninguna clave de IA válida. "
        "Verifica AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT o OPENAI_API_KEY en tu archivo .env"
    )


def invocar_llm(prompt: str, sistema: str = "", timeout: int = 60) -> str:
    return consultar_llm(prompt, sistema=STRICT_SYSTEM_PROMPT, json_mode=True, timeout=timeout)


def consultar_llm_semantico(
    intenciones: List[Any],
    datos_empresa: Dict[str, Any],
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    """Inferencia semántica desacoplada (OpenAI GPT-4o-mini)."""
    rotulos_compactos = [
        {
            "id": getattr(item, "id_rotulo", idx + 1),
            "rotulo": getattr(item, "rotulo_texto", str(item.get("valor", ""))),
            "seccion": getattr(item, "seccion_titulo", "GENERAL"),
            "ubicacion_sugerida": getattr(item, "dest_ubicacion", item.get("ubicacion", "derecha")),
        }
        for idx, item in enumerate(intenciones)
    ]

    payload = {
        "F": rotulos_compactos,
        "D": datos_empresa,
    }

    sistema_semantico = (
        "Eres AutoForm AI Master Cognitive Engine. Tu tarea es realizar el emparejamiento semántico "
        "entre la lista de rótulos 'F' y los datos maestros de la empresa 'D'.\n\n"
        "INSTRUCCIONES DE SALIDA (ESTRICTO JSON):\n"
        "Responde ÚNICAMENTE con la lista de coincidencias:\n"
        "{\"mappings\": [{\"id\": 1, \"campo\": \"razon_social\"}, {\"id\": 2, \"campo\": \"banco\"}]}\n\n"
        "- Si la información solicitada en el rótulo no existe en 'D', omite ese id.\n"
        "- NUNCA inventes campos ni valores que no existan en 'D'.\n"
        "- Responde únicamente el objeto JSON sin texto Markdown adicional."
    )

    prompt_json = json.dumps(payload, ensure_ascii=False)
    raw_res = consultar_llm(prompt_json, sistema=sistema_semantico, json_mode=True, timeout=timeout)

    try:
        data = json.loads(raw_res)
        if isinstance(data, dict) and "mappings" in data:
            return data["mappings"]
        if isinstance(data, list):
            return data
    except Exception as exc:
        print(f"[AutoForm AI LLM] Error al parsear JSON semántico: {exc}")

    return []


def invocar_llm_vision(
    imagenes_png: List[bytes],
    datos_empresa: Dict[str, Any],
    timeout: int = 90,
) -> List[Dict[str, Any]]:
    """Analiza visualmente páginas PDF (imágenes PNG) y extrae las coordenadas de las casillas
    (bounding boxes normalizadas 0-1000) usando Azure OpenAI / OpenAI GPT-4o Vision (Base64).
    """
    if not imagenes_png:
        return []

    usar_azure = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY)
    if not usar_azure and not OPENAI_API_KEY:
        raise RuntimeError("No se configuró AZURE_OPENAI_API_KEY ni OPENAI_API_KEY en .env para motor de Visión")

    datos_json = json.dumps(datos_empresa, ensure_ascii=False, indent=2)

    prompt_vision = (
        "Eres un motor de visión por computadora experto en analizar formularios PDF y documentos escaneados.\n"
        "Tu tarea es analizar visualmente la página suministrada e identificar las coordenadas exactas "
        "(bounding boxes) de las casillas o líneas vacías donde debe escribirse cada dato maestro de la empresa.\n\n"
        f"DATOS MAESTROS DE LA EMPRESA:\n{datos_json}\n\n"
        "INSTRUCCIONES DE SALIDA (ESTRICTO JSON):\n"
        "Responde ÚNICAMENTE con una estructura JSON con la clave \"campos_vision\":\n"
        "{\n"
        "  \"campos_vision\": [\n"
        "    {\"campo\": \"razon_social\", \"bbox_1000\": [120, 300, 145, 750], \"pagina\": 1},\n"
        "    {\"campo\": \"nit\", \"bbox_1000\": [160, 300, 185, 550], \"pagina\": 1}\n"
        "  ]\n"
        "}\n\n"
        "REGLAS DE BOUNDING BOX (escalas de 0 a 1000):\n"
        "1. `bbox_1000` contiene 4 enteros normalizados de 0 a 1000: [ymin, xmin, ymax, xmax].\n"
        "   - ymin: Coordenada vertical superior de la casilla receptora vacía.\n"
        "   - xmin: Coordenada horizontal izquierda de la casilla receptora vacía.\n"
        "   - ymax: Coordenada vertical inferior de la casilla receptora vacía.\n"
        "   - xmax: Coordenada horizontal derecha de la casilla receptora vacía.\n"
        "2. La bounding box debe ser la CASILLA VACÍA O LÍNEA DE ENTRADA del dato, NUNCA el texto de la etiqueta.\n"
        "3. Mapea únicamente los campos disponibles en la empresa que estén solicitados en el formulario."
    )

    try:
        print("[AutoForm AI Vision] Procesando imagen PDF con GPT-4o Vision (Base64)...")

        content_parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt_vision}]

        for img_bytes in imagenes_png[:3]:
            b64_img = base64.b64encode(img_bytes).decode("utf-8")
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64_img}"}
            })

        if usar_azure:
            endpoint_limpio = AZURE_OPENAI_ENDPOINT.rstrip("/")
            url_target = f"{endpoint_limpio}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"
            headers = {
                "api-key": AZURE_OPENAI_API_KEY,
                "Content-Type": "application/json",
            }
            body = {
                "messages": [{"role": "user", "content": content_parts}],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
                "seed": 42,
            }
        else:
            url_target = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            }
            body = {
                "model": OPENAI_MODEL if OPENAI_MODEL else "gpt-4o-mini",
                "messages": [{"role": "user", "content": content_parts}],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
                "seed": 42,
            }

        res_http = requests.post(url_target, json=body, headers=headers, timeout=timeout)
        res_http.raise_for_status()
        text_out = res_http.json()["choices"][0]["message"]["content"]

        if text_out:
            res_json = json.loads(text_out)
            if isinstance(res_json, dict) and "campos_vision" in res_json:
                return res_json["campos_vision"]
            if isinstance(res_json, list):
                return res_json

    except Exception as exc:
        print(f"[AutoForm AI Vision Error] Falló visión con LLM: {exc}")

    return []


def consultar_llm_vision(
    imagenes_png: List[bytes],
    prompt_usuario: str,
    clave_resultado: str,
    timeout: int = 90,
) -> List[Dict[str, Any]]:
    """Invocación genérica a Vision (Base64) con soporte para Azure OpenAI y OpenAI nativo."""
    if not imagenes_png:
        return []

    usar_azure = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY)
    if not usar_azure and not OPENAI_API_KEY:
        raise RuntimeError("No se configuró AZURE_OPENAI_API_KEY ni OPENAI_API_KEY en .env para motor de Visión")

    try:
        content_parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt_usuario}]

        for img_bytes in imagenes_png[:3]:
            b64_img = base64.b64encode(img_bytes).decode("utf-8")
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64_img}"}
            })

        if usar_azure:
            endpoint_limpio = AZURE_OPENAI_ENDPOINT.rstrip("/")
            url_target = f"{endpoint_limpio}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"
            headers = {
                "api-key": AZURE_OPENAI_API_KEY,
                "Content-Type": "application/json",
            }
            body = {
                "messages": [{"role": "user", "content": content_parts}],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
                "seed": 42,
            }
        else:
            url_target = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            }
            body = {
                "model": OPENAI_MODEL if OPENAI_MODEL else "gpt-4o-mini",
                "messages": [{"role": "user", "content": content_parts}],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
                "seed": 42,
            }

        res_http = requests.post(url_target, json=body, headers=headers, timeout=timeout)
        res_http.raise_for_status()
        text_out = res_http.json()["choices"][0]["message"]["content"]

        if text_out:
            res_json = json.loads(text_out)
            if isinstance(res_json, dict) and clave_resultado in res_json:
                return res_json[clave_resultado]
            if isinstance(res_json, list):
                return res_json

    except Exception as exc:
        print(f"[AutoForm AI Vision Error] Falló consulta genérica de visión con LLM: {exc}")

    return []
