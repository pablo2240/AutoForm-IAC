"""Cliente LLM para AutoForm AI usando Google AI Studio (gemini-2.0-flash) con fallback opcional a OpenRouter."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None  # type: ignore
    types = None  # type: ignore

try:
    import openai
except ImportError:
    openai = None  # type: ignore

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

# OpenAI Configuration (Prioridad #1)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# Google AI Studio Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# OpenRouter Configuration (Fallback)
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "inclusionai/ling-3.0-tiny:free")
OPENROUTER_API_URL = f"{OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"


STRICT_SYSTEM_PROMPT = """## ROL Y PERSONA
Eres AutoForm AI Master Cognitive Engine, el modelo de inteligencia artificial experto en la interpretación semántica y contextual de licitaciones, pliegos de condiciones y formularios corporativos oficiales de Colombia e Hispanoamérica.

## CONTEXTO Y ENTRADAS
Recibes un objeto JSON con dos componentes principales:
1. "F": Arreglo de rótulos o enunciados extraídos del formulario. Cada elemento incluye:
   - "id": Identificador único incremental.
   - "rotulo": Texto original detectado (etiqueta corta, pregunta larga, enunciado declarativo o título de sección).
   - "seccion": Título o encabezado contextual del bloque donde se ubica la celda.
2. "D": Objeto con los datos maestros de la empresa (razon_social, nit, cedula, expedicion, direccion, telefono, correo, representante_legal, banco, numero_cuenta, tipo_cuenta, sucursal, ciudad, departamento, pais).

## PRINCIPIOS DE INFERENCIA SEMÁNTICA AVANZADA (SIN DEPENDER DE ETIQUETAS EXACTAS)

### ETAPA 1: RECONOCIMIENTO CONTEXTUAL Y ENUNCIADOS LARGOS
- No busques coincidencias literales de texto. Interpreta la intencionalidad del enunciado o pregunta.
- Si el rótulo o la sección hace referencia al proponente, solicitante, oferente, sociedad o empresa contratista:
  * Rótulos como '1. DATOS DEL PROPONENTE', 'Nombre de la persona jurídica o empresa que presenta la propuesta', 'Identificación del oferente', 'Datos de la firma proveedora', 'Información de la entidad' -> razon_social
  * Rótulos como 'Número de NIT', 'Identificación del oferente', 'Registro tributario', 'CC/CE/PAS/NIT' -> nit
  * Rótulos como 'Nombre del representante', 'Nombre de quien suscribe el documento', 'Apoderado autorizado', 'Nombre del declarante' -> representante_legal
  * Rótulos como 'Lugar de expedición', 'Expedida en', 'Ciudad de expedición' -> expedicion
  * Rótulos como 'Domicilio principal', 'Dirección de notificación', 'Dirección fiscal' -> direccion
  * Rótulos como 'Canal de contacto electrónico', 'Correo institucional', 'Email notificación' -> correo
  * Rótulos como 'Entidad financiera para transferencias', 'Banco donde tiene la cuenta' -> banco
  * Rótulos como 'Número de cuenta para pagos', 'No. de cuenta corriente o ahorros' -> numero_cuenta

### ETAPA 2: ASIGNACIÓN DE CAMPOS DECLARATIVOS E INLINE
- Si el rótulo contiene marcadores inline como `____` o `...` dentro de un texto declarativo (ej: 'Yo, _____ identificado con documento _____ expedido en _____'):
  * Asigna en orden secuencial: representante_legal -> cedula -> expedicion.

### ETAPA 3: DISTINCIÓN ENTRE DATOS MAESTROS Y TERCEROS/FIRMAS
- DILIGENCIAR: Únicamente información referente a la empresa o su representante legal principal contenidos en 'D'.
- OMITIR (NO DILIGENCIAR):
  * Casillas para firma física manuscrita, huella o sello.
  * Secciones exclusivas para diligenciamiento del cliente / entidad licitante (ej. 'Uso exclusivo de la empresa', 'Aprobado por').
  * Referencias comerciales de terceros o juntas directivas secundarias no presentes en 'D'.

### ETAPA 4: CASILLAS DE VERIFICACIÓN (CHECKBOXES)
- Si el rótulo solicita seleccionar una opción (ej: 'Tipo de Cuenta: Ahorros [ ] Corriente [ ]') y el dato en 'D' coincide exactamente:
  * Mapear la casilla correspondiente asignando el valor true o "X".

### ETAPA 5: AUDITORÍA DE CERO INVENCIÓN Y VERIFICACIÓN FINAL (HARD GATE)
- Cero Alucinación: Si la información solicitada no existe en 'D', DEBES OMITIR ese id.
- Realiza un pase de verificación final: Comprueba que ningún dato disponible en 'D' haya sido omitido si existe una pregunta o enunciado que lo solicite.

## FORMATO DE SALIDA (ESTRICTO JSON)
Responde ÚNICAMENTE con un objeto JSON válido con la clave "mappings":
{
  "mappings": [
    {"id": 1, "campo": "razon_social"},
    {"id": 2, "campo": "nit"}
  ]
}"""


def _consultar_gemini_studio(
    prompt_usuario: str,
    sistema: str = "",
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY no configurada en .env")

    # Lista de modelos Gemini conocidos en orden de preferencia por si el del .env está obsoleto
    modelos_gemini = [GEMINI_MODEL, "gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash-exp"]
    # Quitar duplicados y Nones
    modelos_gemini_unicos = [m for idx, m in enumerate(modelos_gemini) if m and m not in modelos_gemini[:idx]]

    ultimo_exc = None
    for mod_gemini in modelos_gemini_unicos:
        # Opción A: Usar la SDK oficial google-genai si está disponible
        if genai is not None and types is not None:
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                config_kwargs: Dict[str, Any] = {}
                if sistema:
                    config_kwargs["system_instruction"] = sistema
                if json_mode:
                    config_kwargs["response_mime_type"] = "application/json"
                config_kwargs["max_output_tokens"] = 30000

                config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

                MAX_REINTENTOS = 2
                for intento in range(1, MAX_REINTENTOS + 1):
                    try:
                        respuesta = client.models.generate_content(
                            model=mod_gemini,
                            contents=prompt_usuario,
                            config=config,
                        )
                        if respuesta and respuesta.text:
                            return respuesta.text
                        raise RuntimeError("Respuesta vacía de Google AI Studio.")
                    except Exception as exc:
                        if "404" in str(exc) or "NOT_FOUND" in str(exc):
                            print(f"[AutoForm AI Warning] Modelo {mod_gemini} dio 404 en Google AI Studio. Probando alternativo...")
                            break
                        if intento < MAX_REINTENTOS:
                            time.sleep(2 ** (intento - 1))
                            continue
                        raise exc
            except Exception as exc_sdk:
                ultimo_exc = exc_sdk

        # Opción B: Usar la API REST de Google AI Studio como respaldo nativo ultrarrápido
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod_gemini}:generateContent?key={GEMINI_API_KEY}"
        
        cuerpo: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt_usuario}]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 30000
            }
        }
        if sistema:
            cuerpo["systemInstruction"] = {
                "parts": [{"text": sistema}]
            }
        if json_mode:
            cuerpo["generationConfig"]["responseMimeType"] = "application/json"

        try:
            res_rest = requests.post(url, json=cuerpo, timeout=timeout)
            if res_rest.status_code == 404:
                print(f"[AutoForm AI Warning] Modelo REST {mod_gemini} dio 404. Probando alternativo...")
                continue
            res_rest.raise_for_status()
            datos_rest = res_rest.json()
            candidatos = datos_rest.get("candidates", [])
            if candidatos:
                parts = candidatos[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
        except Exception as exc_rest:
            ultimo_exc = exc_rest
            continue

    if ultimo_exc:
        raise ultimo_exc
    raise RuntimeError("Todos los modelos de Gemini dieron 404 en Google AI Studio.")

    headers = {"Content-Type": "application/json"}
    MAX_REINTENTOS = 3
    ultimo_error: Exception = RuntimeError("Error desconocido")

    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            resp = requests.post(url, headers=headers, json=cuerpo, timeout=timeout)
            if resp.status_code >= 500:
                ultimo_error = RuntimeError(f"Error de Google AI Studio REST {resp.status_code}: {resp.text}")
                if intento < MAX_REINTENTOS:
                    time.sleep(2 ** (intento - 1))
                    continue
                raise ultimo_error
            resp.raise_for_status()
            datos = resp.json()
            candidates = datos.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts and "text" in parts[0]:
                    return parts[0]["text"]
            raise RuntimeError(f"Respuesta sin texto de Google AI Studio: {datos}")
        except Exception as exc:
            ultimo_error = exc
            if intento < MAX_REINTENTOS:
                time.sleep(2 ** (intento - 1))
                continue
            raise ultimo_error

    raise ultimo_error


def _consultar_llm_requests(
    prompt_usuario: str,
    sistema: str = "",
    json_mode: bool = False,
    timeout: int = 60
) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY no configurada. Revisa tu .env")

    mensajes: List[Dict[str, str]] = []
    if sistema:
        mensajes.append({"role": "system", "content": sistema})
    mensajes.append({"role": "user", "content": prompt_usuario})

    # Cascade de modelos en OpenRouter.
    # - "openrouter/free": router automático de OR que elige el mejor gratuito disponible en tiempo real.
    #   Es la opción más resiliente porque nunca da 404 por modelo retirado.
    # - Los siguientes son modelos Gemini gratuitos conocidos por respetar json_mode
    #   sin emitir razonamiento inline.
    # EXCLUIDO: ling-3.0-flash, qwen/qwen-2.5-72b-instruct — emiten chain-of-thought
    #           o dejaron de ser gratuitos.
    modelo_env = LLM_MODEL if (LLM_MODEL and "/" in LLM_MODEL) else None
    modelos_candidatos_raw = [
        modelo_env,                                           # 1. Config del .env (si aplica)
        "inclusionai/ling-3.0-tiny:free",                     # 2. Ling 3.0 Tiny Free (¡Activo en OpenRouter!)
        "nvidia/nemotron-3.5-lightning:free",                 # 3. Nemotron 3.5 Lightning Free
        "openrouter/auto",                                    # 4. Router automático de OpenRouter (gratuito)
        "google/gemma-4-31b-it:free",                         # 5. Gemma 4 31B Free
        "poolside/laguna-s-2.1:free",                          # 6. Laguna S 2.1 Free
    ]
    # Quitar Nones y duplicados preservando el orden
    modelos_unicos: List[str] = []
    for m in modelos_candidatos_raw:
        if m and m not in modelos_unicos:
            modelos_unicos.append(m)

    ultimo_error: Exception = RuntimeError("Todos los modelos de OpenRouter fallaron.")

    for modelo in modelos_unicos:
        cuerpo: Dict[str, Any] = {
            "model": modelo,
            "messages": mensajes,
            "max_tokens": 30000,
        }
        # json_mode solo en modelos que lo soportan (excluir thinking models y auto)
        if json_mode and not any(x in modelo for x in ("ling", "auto")):
            cuerpo["response_format"] = {"type": "json_object"}

        MAX_REINTENTOS = 2
        modelo_fallido = False
        for intento in range(1, MAX_REINTENTOS + 1):
            try:
                respuesta = requests.post(
                    OPENROUTER_API_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://localhost:8501",
                        "X-Title": "AutoForm AI",
                    },
                    json=cuerpo,
                    timeout=timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                backoff = min(2 ** intento, 16)
                ultimo_error = RuntimeError(f"Error de red con {modelo} (intento {intento}/{MAX_REINTENTOS}): {exc}")
                if intento < MAX_REINTENTOS:
                    print(f"[AutoForm AI] Error de red con {modelo}. Reintentando en {backoff}s...")
                    time.sleep(backoff)
                    continue
                modelo_fallido = True
                break

            # 404/403: modelo no disponible → saltar sin reintentar
            if respuesta.status_code in (404, 403):
                print(f"[AutoForm AI] Modelo {modelo} no disponible ({respuesta.status_code}). Probando siguiente...")
                ultimo_error = RuntimeError(f"Modelo {modelo} no disponible en OpenRouter ({respuesta.status_code}).")
                modelo_fallido = True
                break

            # 429 Rate Limit: esperar el tiempo indicado por el servidor y reintentar
            if respuesta.status_code == 429:
                retry_after = int(respuesta.headers.get("Retry-After", 0))
                espera = retry_after if retry_after > 0 else min(4 ** intento, 30)
                print(f"[AutoForm AI] Rate limit en OpenRouter {modelo} (429). Esperando {espera}s antes del intento {intento + 1}...")
                ultimo_error = RuntimeError(f"OpenRouter {modelo} devolvio 429 Rate Limit.")
                if intento < MAX_REINTENTOS:
                    time.sleep(espera)
                    continue
                modelo_fallido = True
                break

            if respuesta.status_code >= 500:
                backoff = min(2 ** intento, 16)
                ultimo_error = RuntimeError(f"OpenRouter {modelo} devolvio status {respuesta.status_code}.")
                if intento < MAX_REINTENTOS:
                    print(f"[AutoForm AI] Error {respuesta.status_code} en OpenRouter {modelo}. Reintentando en {backoff}s (intento {intento + 1}/{MAX_REINTENTOS})...")
                    time.sleep(backoff)
                    continue
                modelo_fallido = True
                break

            try:
                respuesta.raise_for_status()
            except requests.HTTPError as exc:
                ultimo_error = RuntimeError(f"Error HTTP OpenRouter {modelo}: {respuesta.status_code} {respuesta.text}")
                modelo_fallido = True
                break

            datos = respuesta.json()
            if not datos or "error" in datos:
                error_msg = datos.get("error", {}).get("message", str(datos)) if isinstance(datos, dict) else str(datos)
                ultimo_error = RuntimeError(f"Error en respuesta OpenRouter {modelo}: {error_msg}")
                modelo_fallido = True
                break

            choices = datos.get("choices", [])
            if not choices:
                ultimo_error = RuntimeError(f"Payload sin choices en OpenRouter {modelo}: {datos}")
                modelo_fallido = True
                break

            choice_obj = choices[0]
            message_obj = choice_obj.get("message", {}) if isinstance(choice_obj, dict) else {}

            # Extraer contenido soportando diferentes esquemas de modelos de OpenRouter
            contenido = None
            if isinstance(message_obj, dict):
                contenido = message_obj.get("content") or message_obj.get("reasoning") or message_obj.get("text")
            if not contenido and isinstance(choice_obj, dict):
                contenido = choice_obj.get("text")

            if contenido and str(contenido).strip():
                return str(contenido).strip()

            ultimo_error = RuntimeError(f"El modelo {modelo} devolvió contenido vacío.")
            modelo_fallido = True
            break

        if modelo_fallido:
            continue  # Siguiente modelo del cascade

    raise ultimo_error



def _consultar_openai(
    prompt_usuario: str,
    sistema: str = "",
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    """Invocación directa a la API oficial de OpenAI (gpt-4o-mini por defecto)."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY no configurada en .env")

    mensajes: List[Dict[str, str]] = []
    if sistema:
        mensajes.append({"role": "system", "content": sistema})
    mensajes.append({"role": "user", "content": prompt_usuario})

    cuerpo: Dict[str, Any] = {
        "model": OPENAI_MODEL,
        "messages": mensajes,
        "temperature": 0.1,
    }
    if json_mode:
        cuerpo["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    MAX_REINTENTOS = 2
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            respuesta = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=cuerpo,
                timeout=timeout,
            )
            respuesta.raise_for_status()
            datos = respuesta.json()
            choices = datos.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content", "").strip()
                if content:
                    return content
            raise RuntimeError(f"Respuesta vacía de OpenAI API: {datos}")
        except Exception as exc:
            if intento < MAX_REINTENTOS:
                time.sleep(1.5)
                continue
            raise RuntimeError(f"Error en OpenAI API ({OPENAI_MODEL}): {exc}")


def consultar_llm(
    prompt_usuario: str,
    sistema: Optional[str] = None,
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    if sistema is None:
        sistema = f"Eres el asistente inteligente de AutoForm AI, impulsado por OpenAI {OPENAI_MODEL}. Responde únicamente en formato JSON válido."

    # 1. Prioridad #1: OpenAI API oficial (gpt-4o-mini)
    if OPENAI_API_KEY:
        try:
            return _consultar_openai(
                prompt_usuario, sistema=sistema, json_mode=json_mode, timeout=timeout
            )
        except Exception as exc:
            print(f"[AutoForm AI Warning] Falló OpenAI API ({exc}). Intentando fallback a Google AI Studio / OpenRouter...")

    # 2. Prioridad #2: Google AI Studio con Gemini
    if GEMINI_API_KEY:
        try:
            return _consultar_gemini_studio(
                prompt_usuario, sistema=sistema, json_mode=json_mode, timeout=timeout
            )
        except Exception as exc:
            print(f"[AutoForm AI Warning] Falló Google AI Studio ({exc}). Intentando fallback a OpenRouter...")

    # 2. Fallback a OpenRouter
    if OPENROUTER_API_KEY:
        return _consultar_llm_requests(prompt_usuario, sistema=sistema, json_mode=json_mode, timeout=timeout)

    raise RuntimeError("No se configuró ninguna clave de API válida (GEMINI_API_KEY u OPENROUTER_API_KEY) en el archivo .env")


def invocar_llm(prompt: str, sistema: str = "", timeout: int = 60) -> str:
    # Complicidad 1 Fix: siempre se usa el prompt consolidado único.
    # El argumento `sistema` ya no se concatena para evitar conflictos de reglas.
    return consultar_llm(prompt, sistema=STRICT_SYSTEM_PROMPT, json_mode=True, timeout=timeout)


def consultar_llm_semantico(
    intenciones: List[Any],
    datos_empresa: Dict[str, Any],
    timeout: int = 60,
) -> List[Dict[str, Any]]:
    """Inferencia semántica desacoplada (GPT-4.1-mini / Gemini).

    Envía únicamente los rótulos compactos y la empresa maestro.
    El LLM responde únicamente: [{"id": 1, "campo": "razon_social"}].
    """
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
        "entre la lista de rótulos 'F' y los datos maestros de la empresa 'D', determinando además "
        "la ubicación precisa donde debe colocarse el valor ('derecha', 'abajo', 'misma').\n\n"
        "REGLAS DE UBICACIÓN:\n"
        "- `ubicacion: \"derecha\"` -> Por defecto para rótulos individuales con espacio de respuesta a la derecha.\n"
        "- `ubicacion: \"abajo\"` -> Para encabezados de tabla (ej. BANCO, SUCURSAL, No CUENTA) donde el dato se escribe en la fila inferior.\n"
        "- `ubicacion: \"misma\"` -> Para enunciados o párrafos declarativos con marcadores inline `_____` dentro del texto.\n\n"
        "REGLAS DE EMPAREJAMIENTO DE ALTA COBERTURA:\n"
        "- `nit` → Rótulos como 'NIT', 'RUT', 'CC/CE/PAS/NIT', 'Número de Identificación', 'Identificación Tributaria'.\n"
        "- `cedula` → Rótulos como 'C.C.', 'Cédula', 'Documento de Identidad', 'No. Identificación', 'ID'.\n"
        "- `expedicion` → Rótulos como 'Lugar de Expedición', 'Expedida en', 'Ciudad de Expedición', 'Expedición', 'Fecha Expedición ID'.\n"
        "- `razon_social` → Rótulos como 'Nombre / Razón Social', 'Razón Social', 'Nombre de la Empresa', 'Proveedor', 'Firma / Nombre Comercial'.\n"
        "- `direccion` → Rótulos como 'Dirección', 'Domicilio Principal', 'Dirección Fiscal'.\n"
        "- `telefono` → Rótulos como 'Teléfono', 'Tel', 'Celular', 'Contacto Telefónico'.\n"
        "- `correo` → Rótulos como 'Correo', 'Email', 'E-mail', 'Correo Notificación'.\n"
        "- `pagina_web` → Rótulos como 'Página Web', 'Sitio Web', 'Web', 'URL', 'Portal Web', 'Página'.\n"
        "- `representante_legal` → Rótulos como 'Representante Legal', 'Nombre Representante', 'Firmante', 'Nombre del Declarante', 'Nombres y Apellidos'.\n"
        "- `representante_nombres` → Rótulos como 'Nombres', 'Primer Nombre', 'Nombres del Representante'.\n"
        "- `representante_apellidos` → Rótulos como 'Apellidos', 'Primer Apellido', 'Segundo Apellido'.\n"
        "- `banco` → Rótulos como 'Banco', 'Entidad Bancaria', 'Financiera'.\n"
        "- `numero_cuenta` → Rótulos como 'Número de Cuenta', 'No. Cuenta', 'Nro Cuenta', 'Cuenta No.'.\n"
        "- `tipo_cuenta` → Rótulos como 'Tipo de Cuenta', 'Tipo Cuenta' (Ahorros / Corriente).\n"
        "- `sucursal` → Rótulos como 'Sucursal', 'Sucursal Bancaria'.\n"
        "- `pais` → Rótulos como 'País', 'Pais', 'Nacionalidad', 'País de Origen'.\n"
        "- `ciudad`, `departamento` → Rótulos de ubicación geográfica.\n\n"
        "INSTRUCCIONES DE SALIDA (ESTRICTO JSON):\n"
        "Responde ÚNICAMENTE con la lista de coincidencias:\n"
        "{\"mappings\": [{\"id\": 1, \"campo\": \"razon_social\", \"ubicacion\": \"derecha\"}, {\"id\": 2, \"campo\": \"banco\", \"ubicacion\": \"abajo\"}]}\n\n"
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
    (bounding boxes normalizadas 0-1000) usando Gemini Vision u OpenAI/OpenRouter Vision.

    Returns:
        List[Dict[str, Any]]: Lista de dicts con keys: 'campo', 'bbox_1000' ([ymin, xmin, ymax, xmax]), 'pagina'.
    """
    if not imagenes_png:
        return []

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

    # -------------------------------------------------------------------------
    # Opción 1: Gemini Vision (google-genai SDK o Gemini API)
    # -------------------------------------------------------------------------
    if GEMINI_API_KEY and genai is not None and types is not None:
        try:
            print("[AutoForm AI Vision] Procesando imagen PDF con Gemini Vision...")
            client = genai.Client(api_key=GEMINI_API_KEY)
            
            # Construir partes del mensaje (imágenes PNG + prompt)
            contents: List[Any] = []
            for idx, img_bytes in enumerate(imagenes_png[:3]):
                part_img = types.Part.from_bytes(data=img_bytes, mime_type="image/png")
                contents.append(part_img)

            contents.append(prompt_vision)

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=8000,
            )

            mod_gemini = GEMINI_MODEL if GEMINI_MODEL else "gemini-2.5-flash"
            response = client.models.generate_content(
                model=mod_gemini,
                contents=contents,
                config=config,
            )

            if response and response.text:
                res_json = json.loads(response.text)
                if isinstance(res_json, dict) and "campos_vision" in res_json:
                    return res_json["campos_vision"]
                if isinstance(res_json, list):
                    return res_json

        except Exception as exc:
            print(f"[AutoForm AI Vision Warning] Falló Gemini Vision ({exc}). Intentando fallback a OpenAI/OpenRouter...")

    # -------------------------------------------------------------------------
    # Opción 2: OpenAI / OpenRouter Vision (Base64)
    # -------------------------------------------------------------------------
    if OPENAI_API_KEY or OPENROUTER_API_KEY:
        try:
            import base64
            print("[AutoForm AI Vision] Procesando imagen PDF con OpenAI / OpenRouter Vision (Base64)...")

            content_parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt_vision}]

            for img_bytes in imagenes_png[:3]:
                b64_img = base64.b64encode(img_bytes).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_img}"}
                })

            if OPENAI_API_KEY and openai is not None:
                client_oai = openai.OpenAI(api_key=OPENAI_API_KEY)
                resp = client_oai.chat.completions.create(
                    model=OPENAI_MODEL if "gpt" in OPENAI_MODEL else "gpt-4o-mini",
                    messages=[{"role": "user", "content": content_parts}],
                    response_format={"type": "json_object"},
                    max_tokens=4000,
                )
                text_out = resp.choices[0].message.content or ""
            else:
                headers = {
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                }
                body = {
                    "model": LLM_MODEL if LLM_MODEL else "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": content_parts}],
                    "response_format": {"type": "json_object"},
                }
                res_http = requests.post(OPENROUTER_API_URL, json=body, headers=headers, timeout=timeout)
                res_http.raise_for_status()
                text_out = res_http.json()["choices"][0]["message"]["content"]

            if text_out:
                res_json = json.loads(text_out)
                if isinstance(res_json, dict) and "campos_vision" in res_json:
                    return res_json["campos_vision"]
                if isinstance(res_json, list):
                    return res_json

        except Exception as exc:
            print(f"[AutoForm AI Vision Error] Falló visión con OpenAI/OpenRouter: {exc}")

    return []


