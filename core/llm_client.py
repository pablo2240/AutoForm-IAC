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

# Soporte automÃ¡tico para Streamlit Community Cloud Secrets (st.secrets)
try:
    import streamlit as st
    if hasattr(st, "secrets"):
        for k, v in st.secrets.items():
            if isinstance(v, str) and k not in os.environ:
                os.environ[k] = v
except Exception:
    pass

# OpenAI Configuration (Motor EstÃ¡ndar)
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
   - `contacto`: `telefono` (PBX institucional), `pagina_web`.
2. `representante_legal`:
   - `identidad`: `representante_legal` (Nombre completo del apoderado), `representante_nombres` (Primer y segundo nombre), `representante_apellidos` (Primer y segundo apellido), `tipo_documento` (Tipo de documento de identidad, ej. C.C.), `cedula` (Número de documento de la persona natural), `lugar_expedicion` (Ciudad/Lugar donde se expidió la cédula, ej. "Envigado").
   - `contacto`: `correo`, `telefono`, `celular` (Teléfono móvil / Celular del representante).
3. `financiero`:
   - `banco`: `banco` (Nombre de la entidad financiera), `sucursal`.
   - `cuenta`: `numero_cuenta` (Número de cuenta bancaria), `tipo_cuenta` (Ahorros / Corriente).

## CONTEXTO Y ENTRADAS
Recibes un objeto JSON con:
1. "F": Arreglo de rótulos o preguntas extraídos del formulario. Cada elemento incluye:
   - "id": Identificador numérico único.
   - "rotulo": Texto original detectado.
   - "seccion": Título o encabezado contextual de la sección donde reside el rótulo.
   - "contexto_fila": Texto completo de la fila física actual donde se encuentra el rótulo (elementos adyacentes en la misma fila).
   - "vecino_abajo": Texto del elemento situado inmediatamente debajo en la siguiente fila (si existe).
2. "D": Objeto con la Taxonomía Maestra de la empresa descrita arriba.

## REGLA DE PRIORIDAD CONTEXTUAL (IMPORTANTE)
- Utiliza `contexto_fila` y `vecino_abajo` ÚNICAMENTE cuando el `rotulo` sea ambiguo o genérico (ej. 'Número', 'No.', 'N°', 'ID', 'Nombre', 'Valor', 'Código', 'Fecha').
- Si el `rotulo` es inequívoco y claro por sí solo (ej. 'NIT:', 'Correo electrónico:', 'Dirección:', 'Banco:', 'Teléfono:', 'Representante Legal:'), ignora el contexto adicional para evitar confundirte o distraerte con información redundante o campos vecinos de la misma fila.

## PRINCIPIOS DE INFERENCIA SEMÁNTICA POR CATEGORÍA (CATEGORY-FIRST MATCHING)

### ETAPA 1: ASIGNACIÓN SEGÚN EL DOMINIO DE LA SECCIÓN
- Si la sección o el rótulo hace referencia a la EMPRESA / PROPONENTE / SOLICITANTE / PERSONA JURÍDICA:
  * Rótulos que soliciten nombre de la empresa, denominación social, solicitante, "Nombre Comercial", "Razón Social / Nombre Comercial" -> "razon_social"
  * Rótulos de NIT, RUT, "NIT / TAX ID", "TAX ID", Identificación Tributaria, o listas de tipos como "CC/CE/PAS/NIT", "CC/NIT", "NIT/CC" -> "nit" (la empresa es persona jurídica y su número de identificación tributaria es el NIT).
  * Rótulos de Domicilio, Sede Principal, Dirección -> "direccion"
  * Rótulos de Municipio, Ciudad de domicilio -> "ciudad"
  * Rótulos combinados de "Ciudad / Departamento", "Ciudad/Depto", "Municipio / Departamento" -> "ciudad_departamento"
  * Rótulos de Teléfono corporativo, PBX -> "telefono"
  * Rótulos de Email institucional -> "correo"

- Si la sección o el rótulo hace referencia al REPRESENTANTE LEGAL / PERSONA NATURAL / APODERADO:
  * Rótulos de Nombre del Representante, Representante Legal, o "Razón social o Nombres y Apellidos" -> "representante_legal"
  * Rótulos específicos de Primer/Segundo Nombre -> "representante_nombres"
  * Rótulos específicos de Primer/Segundo Apellido -> "representante_apellidos"
  * Rótulos explícitos del Tipo de Documento, como "Tipo de Identificación (CC-Pasaporte-CE)", "Tipo Doc", "Tipo ID" -> "tipo_documento" (inscribirá C.C.)
  * Rótulos de C.C., Cédula, "Identificación", "Número de Identificación", "Nro de Identificación", "No de Documento" -> "cedula"
  * Rótulos de Lugar o Ciudad de Expedición del documento -> "lugar_expedicion" (ciudad/lugar, ej. "Envigado").
  * Rótulos de Teléfono, Celular, "Teléfono Celular", "Teléfono/Celular", "Tel/Cel", Teléfono Móvil, Móvil, No. Celular -> "celular" (prioridad siempre a celular móvil).

- Si la sección o el rótulo hace referencia a INFORMACIÓN BANCARIA / FINANCIERA:
  * Rótulos de Banco, Entidad Financiera, Nombre de la Entidad Financiera, Institución Bancaria -> "banco"
  * Rótulos de Número de Cuenta, No. Cuenta -> "numero_cuenta"
  * Rótulos de Tipo de Cuenta (Ahorros/Corriente) -> "tipo_cuenta"
  * Rótulos de Sucursal Bancaria -> "sucursal"

- REGLA DE DESAMBIGUACIÓN CONTEXTUAL DE RÓTULOS GENÉRICOS ("Número", "No.", "N°", "Identificación"):
  * Si el rótulo dice "Número", "No.", "N°", "No:", "Num.", "Documento", "Identificación", "No. Identificación" y viene en el contexto o fila del REPRESENTANTE LEGAL / PERSONA NATURAL / GUILLERMO (tras el nombre de la persona) -> asigna "cedula".
  * Si el rótulo dice "Número", "No.", "N°", "No:", "Num.", "Identificación", "No. Identificación", "Identificación Tributaria" y viene en el contexto o fila de la EMPRESA / RAZÓN SOCIAL / PERSONA JURÍDICA (tras el nombre de la empresa) -> asigna "nit".
  * Si el rótulo dice "Número", "No.", "No. de Cuenta" y está en la sección de INFORMACIÓN BANCARIA / CUENTA -> asigna "numero_cuenta".

### ETAPA 2: BARRERAS SEMÁNTICAS NEGATIVAS (ANTI-CONFUSIÓN ESTRICTO)
- NUNCA asignes datos a TÍTULOS DE SECCIÓN, CAPÍTULOS O ENCABEZADOS DE GRUPO:
  * Ejemplos: "1. INFORMACIÓN GENERAL", "2. INFORMACIÓN TRIBUTARIA", "3. COMPOSICIÓN ACCIONARIA", "DATOS DE LA EMPRESA", "Tipo de Solicitud", "Contraparte", "Tipo de Persona", "IDENTIFICACIÓN", "INSTRUCCIONES", "DECLARACIÓN".
  * Los títulos de sección son meros separadores estructurales del documento, NO casillas de llenado. OMITE COMPLETAMENTE SU ID (no lo incluyas en el JSON).
- NUNCA cruces dominios:
  * NO asignes "razon_social" a "Nombre de la Entidad Financiera" o "Entidad Bancaria" (corresponde exclusivamente a "banco").
  * NO asignes "cedula" ni "nit" a "Actividad Económica", "Código CIIU" o "Sector Económico" (omite el id).
  * REGLA DE RÓTULOS COMPUESTOS (CC/CE/PAS/NIT vs Tipo): Si el rótulo pide el número combinado como "CC/CE/PAS/NIT" o "NIT/TAX ID", asigna "nit". Si el rótulo pide explícitamente el tipo ("Tipo de Identificación (CC-Pasaporte-CE)"), asigna "tipo_documento".
  * NO asignes "cedula" a rótulos de NIT de la empresa.
  * NO asignes "nit" a casillas de cédula del representante.
  * NO asignes "razon_social" a casillas de representante legal persona natural.
  * REGLA CRÍTICA DE FECHAS: NUNCA asignes "lugar_expedicion" (ni ningún otro campo) a rótulos que pidan FECHA de expedición (día/mes/año), 'FECHA EXPEDICIÓN ID', 'FECHA DOC', etc. El perfil empresarial NO contiene fechas de expedición, solo contiene el lugar/ciudad ('lugar_expedicion'). Si el formulario pide una FECHA de expedición, OMITE ESE RÓTULO (no incluyas su id).
  * NO asignes datos a porcentajes de participación accionaria (% de acciones).
  * NO asignes datos a instrucciones de anexos, textos legales o preguntas de SI/NO / Gran Contribuyente.

### ETAPA 3: TEXTOS DECLARATIVOS INLINE Y CASILLAS
- Si el rótulo contiene marcadores inline como `____` dentro de un texto declarativo (ej: 'Yo, _____ identificado con documento _____ expedido en _____'):
  * Asigna en orden secuencial: "representante_legal" -> "cedula" -> "lugar_expedicion".
- Si el formulario tiene casillas de verificación para Tipo de Documento (ej. C.C. [ ], C.E. [ ], NIT [ ]):
  * Marca como true o 'X' la casilla correspondiente a 'C.C.'.

### ETAPA 4: AUDITORÍA DE CERO ALUCINACIÓN Y UNICIDAD
- Si el formulario solicita un dato que no existe en "D" (ej. Matrícula Mercantil, CIIU, Sector Económico, Gran Contribuyente, Autorretenedor), OMITE ESE RÓTULO (no incluyas su id).
- UNICIDAD: Cada campo de "D" debe asignarse a un único id para evitar sobreescrituras repetidas.

## FORMATO DE SALIDA (ESTRICTO JSON)
Tu única tarea es emparejar rótulos con claves del perfil de empresa.
La ubicación física de escritura la calcula el sistema Python automáticamente.
Responde ÚNICAMENTE con un objeto JSON válido con la clave "mappings":
{
  "mappings": [
    {"id": 1, "campo": "razon_social"},
    {"id": 2, "campo": "nit"},
    {"id": 3, "campo": "representante_legal"},
    {"id": 4, "campo": "tipo_documento"},
    {"id": 5, "campo": "cedula"},
    {"id": 6, "campo": "celular"}
  ]
}"""


def consultar_llm(
    prompt_usuario: str,
    sistema: Optional[str] = None,
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    """Consulta al modelo de OpenAI o Azure OpenAI configurado en .env."""
    if sistema is None:
        sistema = STRICT_SYSTEM_PROMPT

    usar_azure = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY)
    if not usar_azure and not OPENAI_API_KEY:
        raise RuntimeError("Configura tus credenciales de Azure OpenAI u OPENAI_API_KEY en tu archivo .env para ejecutar la IA.")

    mensajes: List[Dict[str, str]] = []
    if sistema:
        mensajes.append({"role": "system", "content": sistema})
    mensajes.append({"role": "user", "content": prompt_usuario})

    es_modelo_razonamiento = any(x in str(AZURE_OPENAI_DEPLOYMENT_NAME if usar_azure else OPENAI_MODEL).lower() for x in ["gpt-5", "o1", "o3", "luna", "reasoning"])

    if usar_azure:
        endpoint_limpio = AZURE_OPENAI_ENDPOINT.rstrip("/")
        url_target = f"{endpoint_limpio}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"
        headers = {
            "api-key": AZURE_OPENAI_API_KEY,
            "Content-Type": "application/json",
        }
        body: Dict[str, Any] = {
            "messages": mensajes,
        }
        if not es_modelo_razonamiento:
            body["temperature"] = 0.0
            body["seed"] = 42
        if json_mode:
            body["response_format"] = {"type": "json_object"}
    else:
        url_target = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": OPENAI_MODEL if OPENAI_MODEL else "gpt-4o-mini",
            "messages": mensajes,
        }
        if not es_modelo_razonamiento:
            body["temperature"] = 0.0
            body["seed"] = 42
        if json_mode:
            body["response_format"] = {"type": "json_object"}

    MAX_REINTENTOS = 3
    ultimo_error: Exception = RuntimeError("Error desconocido al consultar el LLM")

    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            res_http = requests.post(url_target, json=body, headers=headers, timeout=timeout)
            if res_http.status_code >= 400:
                detalle_error = f"Error HTTP {res_http.status_code} del servidor LLM: {res_http.text}"
                print(f"[AutoForm AI LLM Error] {detalle_error}")
                if res_http.status_code >= 500 and intento < MAX_REINTENTOS:
                    time.sleep(2 ** (intento - 1))
                    continue
                raise RuntimeError(detalle_error)
            datos = res_http.json()
            if "choices" in datos and datos["choices"]:
                contenido = datos["choices"][0].get("message", {}).get("content")
                if contenido is not None:
                    return str(contenido).strip()
            raise RuntimeError(f"Respuesta vacía o sin elecciones del LLM: {datos}")
        except Exception as exc:
            ultimo_error = exc
            if intento < MAX_REINTENTOS:
                time.sleep(2 ** (intento - 1))
                continue
            raise ultimo_error

    raise ultimo_error


def invocar_llm(prompt: str, sistema: str = "", timeout: int = 60) -> str:
    sistema_completo = STRICT_SYSTEM_PROMPT
    if sistema:
        sistema_completo = f"{sistema}\n\n{sistema_completo}"
    return consultar_llm(prompt, sistema=sistema_completo, json_mode=True, timeout=timeout)


def obtener_cliente_instructor():
    """Retorna un cliente Instructor configurado sobre OpenAI o Azure OpenAI."""
    if instructor is None or openai is None:
        return None
    
    usar_azure = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY)
    if usar_azure:
        try:
            raw_client = openai.AzureOpenAI(
                api_key=AZURE_OPENAI_API_KEY,
                api_version=AZURE_OPENAI_API_VERSION,
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
            )
            return instructor.from_openai(raw_client)
        except Exception as exc:
            print(f"[AutoForm AI LLM] Error al inicializar Azure OpenAI Instructor: {exc}")
            return None
    
    if OPENAI_API_KEY:
        try:
            raw_client = openai.OpenAI(api_key=OPENAI_API_KEY)
            return instructor.from_openai(raw_client)
        except Exception as exc:
            print(f"[AutoForm AI LLM] Error al inicializar OpenAI Instructor: {exc}")
            return None
            
    return None


def consultar_llm_seccion_instructor(
    campos_seccion: List[Dict[str, Any]],
    taxonomia_d: Dict[str, Any],
    titulo_seccion: str = "GENERAL",
    timeout: int = 45,
) -> List[Dict[str, Any]]:
    """Capa 1: Inferencia estructurada por sección usando Instructor + Pydantic V2.
    
    Valida la salida contra PlanMapeoSemantico y reintenta automáticamente en caso de
    inconsistencias o campos faltantes.
    """
    if not campos_seccion:
        return []

    client = obtener_cliente_instructor()
    
    payload = {
        "F": [
            {
                "id": c["id"],
                "rotulo": c["rotulo"],
                "seccion": c.get("seccion", titulo_seccion),
                "contexto_fila": c.get("contexto_fila", ""),
                "vecino_abajo": c.get("vecino_abajo", ""),
            }
            for c in campos_seccion
        ],
        "D": taxonomia_d,
        "seccion_actual": titulo_seccion,
    }
    
    prompt_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    
    if client is not None:
        modelo = AZURE_OPENAI_DEPLOYMENT_NAME if (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY) else (OPENAI_MODEL or "gpt-4o-mini")
        try:
            plan_validado = client.chat.completions.create(
                model=modelo,
                response_model=PlanMapeoSemantico,
                max_retries=2,
                messages=[
                    {"role": "system", "content": STRICT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt_str},
                ],
            )
            # Convertir Pydantic a lista de diccionarios
            return [
                {"id": item.id, "campo": item.campo, "ubicacion": item.ubicacion}
                for item in plan_validado.mappings
            ]
        except Exception as exc:
            print(f"[AutoForm AI Instructor] Aviso: reintentando vía JSON mode estándar ({exc})")
    
    # Fallback transparente a invocar_llm si instructor no está disponible o falla
    resp_raw = invocar_llm(prompt_str, timeout=timeout)
    
    try:
        import re
        texto_limpio = resp_raw.strip()
        if "```" in texto_limpio:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", texto_limpio)
            if match:
                texto_limpio = match.group(1).strip()
        data = json.loads(texto_limpio)
        if isinstance(data, dict) and "mappings" in data:
            return data["mappings"]
        if isinstance(data, list):
            return data
    except Exception as exc:
        print(f"[AutoForm AI LLM] Error al parsear JSON en fallback: {exc}")
        
    return []


def consultar_llm_semantico(
    intenciones: List[Any],
    datos_empresa: Dict[str, Any],
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    """Inferencia semÃ¡ntica desacoplada (OpenAI GPT-4o-mini)."""
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
        "Eres AutoForm AI Master Cognitive Engine. Tu tarea es realizar el emparejamiento semÃ¡ntico "
        "entre la lista de rÃ³tulos 'F' y los datos maestros de la empresa 'D'.\n\n"
        "INSTRUCCIONES DE SALIDA (ESTRICTO JSON):\n"
        "Responde ÃNICAMENTE con la lista de coincidencias:\n"
        "{\"mappings\": [{\"id\": 1, \"campo\": \"razon_social\"}, {\"id\": 2, \"campo\": \"banco\"}]}\n\n"
        "- Si la informaciÃ³n solicitada en el rÃ³tulo no existe en 'D', omite ese id.\n"
        "- NUNCA inventes campos ni valores que no existan en 'D'.\n"
        "- Responde Ãºnicamente el objeto JSON sin texto Markdown adicional."
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
        print(f"[AutoForm AI LLM] Error al parsear JSON semÃ¡ntico: {exc}")

    return []


def invocar_llm_vision(
    imagenes_png: List[bytes],
    datos_empresa: Dict[str, Any],
    timeout: int = 90,
) -> List[Dict[str, Any]]:
    """Analiza visualmente pÃ¡ginas PDF (imÃ¡genes PNG) y extrae las coordenadas de las casillas
    (bounding boxes normalizadas 0-1000) usando Azure OpenAI / OpenAI GPT-4o Vision (Base64).
    """
    if not imagenes_png:
        return []

    usar_azure = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY)
    if not usar_azure and not OPENAI_API_KEY:
        raise RuntimeError("No se configurÃ³ AZURE_OPENAI_API_KEY ni OPENAI_API_KEY en .env para motor de VisiÃ³n")

    datos_json = json.dumps(datos_empresa, ensure_ascii=False, indent=2)

    prompt_vision = (
        "Eres un motor de visiÃ³n por computadora experto en analizar formularios PDF y documentos escaneados.\n"
        "Tu tarea es analizar visualmente la pÃ¡gina suministrada e identificar las coordenadas exactas "
        "(bounding boxes) de las casillas o lÃ­neas vacÃ­as donde debe escribirse cada dato maestro de la empresa.\n\n"
        f"DATOS MAESTROS DE LA EMPRESA:\n{datos_json}\n\n"
        "INSTRUCCIONES DE SALIDA (ESTRICTO JSON):\n"
        "Responde ÃNICAMENTE con una estructura JSON con la clave \"campos_vision\":\n"
        "{\n"
        "  \"campos_vision\": [\n"
        "    {\"campo\": \"razon_social\", \"bbox_1000\": [120, 300, 145, 750], \"pagina\": 1},\n"
        "    {\"campo\": \"nit\", \"bbox_1000\": [160, 300, 185, 550], \"pagina\": 1}\n"
        "  ]\n"
        "}\n\n"
        "REGLAS DE BOUNDING BOX (escalas de 0 a 1000):\n"
        "1. `bbox_1000` contiene 4 enteros normalizados de 0 a 1000: [ymin, xmin, ymax, xmax].\n"
        "   - ymin: Coordenada vertical superior de la casilla receptora vacÃ­a.\n"
        "   - xmin: Coordenada horizontal izquierda de la casilla receptora vacÃ­a.\n"
        "   - ymax: Coordenada vertical inferior de la casilla receptora vacÃ­a.\n"
        "   - xmax: Coordenada horizontal derecha de la casilla receptora vacÃ­a.\n"
        "2. La bounding box debe ser la CASILLA VACÃA O LÃNEA DE ENTRADA del dato, NUNCA el texto de la etiqueta.\n"
        "3. Mapea Ãºnicamente los campos disponibles en la empresa que estÃ©n solicitados en el formulario."
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

        es_modelo_razonamiento = any(x in str(AZURE_OPENAI_DEPLOYMENT_NAME if usar_azure else OPENAI_MODEL).lower() for x in ["gpt-5", "o1", "o3", "luna", "reasoning"])

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
            }
            if not es_modelo_razonamiento:
                body["temperature"] = 0.0
                body["seed"] = 42
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
            }
            if not es_modelo_razonamiento:
                body["temperature"] = 0.0
                body["seed"] = 42

        res_http = requests.post(url_target, json=body, headers=headers, timeout=timeout)
        if res_http.status_code >= 400:
            print(f"[AutoForm AI Vision Error] Error HTTP {res_http.status_code}: {res_http.text}")
            raise RuntimeError(f"Error HTTP {res_http.status_code} desde Azure/OpenAI Vision: {res_http.text}")
        text_out = res_http.json()["choices"][0]["message"]["content"]

        if text_out:
            res_json = json.loads(text_out)
            if isinstance(res_json, dict) and "campos_vision" in res_json:
                return res_json["campos_vision"]
            if isinstance(res_json, list):
                return res_json

    except Exception as exc:
        print(f"[AutoForm AI Vision Error] FallÃ³ visiÃ³n con LLM: {exc}")

    return []


def consultar_llm_vision(
    imagenes_png: List[bytes],
    prompt_usuario: str,
    clave_resultado: str,
    timeout: int = 90,
) -> List[Dict[str, Any]]:
    """InvocaciÃ³n genÃ©rica a Vision (Base64) con soporte para Azure OpenAI y OpenAI nativo."""
    if not imagenes_png:
        return []

    usar_azure = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY)
    if not usar_azure and not OPENAI_API_KEY:
        raise RuntimeError("No se configurÃ³ AZURE_OPENAI_API_KEY ni OPENAI_API_KEY en .env para motor de VisiÃ³n")

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
        print(f"[AutoForm AI Vision Error] FallÃ³ consulta genÃ©rica de visiÃ³n con LLM: {exc}")

    return []
