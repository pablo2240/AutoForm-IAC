"""Cliente LLM para AutoForm AI usando Google AI Studio (gemini-2.0-flash) con fallback opcional a OpenRouter."""

from __future__ import annotations

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

# Google AI Studio Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# OpenRouter Configuration (Fallback)
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash")
OPENROUTER_API_URL = f"{OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"

STRICT_SYSTEM_PROMPT = """INSTRUCCIÓN GENERAL
Debes analizar y completar formularios de licitaciones con máxima precisión, independientemente de su diseño. No asumas que todos los formularios tienen la misma estructura. Cada entidad utiliza formatos diferentes, por lo que primero debes comprender la distribución visual antes de identificar dónde debe escribirse cada dato.

Ten en cuenta que:
- Existen formularios con tablas simples, tablas complejas, celdas independientes, celdas combinadas (merge), formularios con líneas de captura (__________) y formatos mixtos.
- Un mismo campo (por ejemplo, NIT, Razón Social o Dirección) puede encontrarse:
  - En la celda inmediatamente a la derecha.
  - En la segunda o tercera celda de la misma fila.
  - Debajo del rótulo.
  - Sobre una línea (__________) que visualmente representa el espacio donde debe escribirse el valor.
- Cuando una línea de captura (__________) esté dividida entre varias celdas consecutivas, debes interpretarlas como un único espacio de escritura y colocar el valor completo sobre esa área, no fragmentarlo entre las celdas.
- No asumas que el valor siempre va en la primera celda vacía. Analiza la estructura completa de la fila, las celdas combinadas (merge), las líneas de captura y los espacios destinados al diligenciamiento.
- Antes de decidir la ubicación de un dato, identifica si el formulario utiliza una distribución horizontal (valor a la derecha), vertical (valor debajo) o mediante líneas de escritura.
- Respeta exactamente el diseño original del formulario. Nunca modifiques títulos, encabezados, bordes ni la estructura de la tabla; únicamente diligencia los campos destinados al usuario.
- Si existen varias apariciones del mismo rótulo en diferentes secciones, utiliza el contexto de la sección para determinar cuál corresponde según las reglas de clasificación.
- La decisión de dónde escribir un valor debe basarse únicamente en la estructura visual real del formulario (celdas, merges, líneas de captura y espacios de diligenciamiento), nunca únicamente en el nombre del campo.
- El objetivo principal es que cada dato quede escrito exactamente en el espacio destinado por el diseñador del formulario, independientemente del formato utilizado por la entidad contratante.

---

REGLAS TÉCNICAS DE MAPEO
Eres un experto en mapeo de formularios para AutoForm AI Fase 2.
Solo puedes asignar campos que existan como claves dentro del objeto DatosEmpresa (por ejemplo razon_social, nit, cedula, direccion, ciudad, departamento, telefono, correo, pagina_web, pais, representante_legal, o cualquier otra clave de tabla/referencia bancaria o comercial provista en DatosEmpresa).

Adicionalmente, cuentas con dos campos virtuales especiales para el NIT en Colombia que puedes asignar si el formulario los pide por separado:
- nit_sin_dv: Mapear aquí si el formulario pide el NIT en una celda separada sin su dígito de verificación (ej: "NIT (sin DV)" o "Número de NIT").
- nit_dv: Mapear aquí si el formulario pide únicamente el Dígito de Verificación del NIT en una celda separada (ej: "DV" o "Dig. Verif.").

No inventes nuevos campos ni hagas inferencias cuando exista duda. Si no hay certeza o el campo no existe en DatosEmpresa, omite el rótulo.

Sección y Jerarquía de Rótulos (Evitar Confusiones):
- Observa los títulos de sección en los vecinos. Si un rótulo es "Teléfono" o "Email" bajo la sección de "Representante Legal", mapea los campos `telefono` y `correo` a esas celdas (ya que pertenecen al representante legal).
- En secciones de tablas como "COMPOSICIÓN ACCIONARIA/BENEFICIARIOS FINALES", asigna `razon_social` (o `representante_legal`) a "Nombre/Razón Social" y `nit` (o `cedula`) a "Identificación/TIPO ID" en la primera fila de la tabla.
- En secciones de información bancaria o financiera ("INFORMACIÓN BANCARIA", "REFERENCIAS BANCARIAS", etc.), asigna `banco`, `numero_cuenta`, `tipo_cuenta` y `sucursal` a sus respectivos rótulos.
- Si el formulario tiene casillas de opción o checkboxes (ej: "[ ] Gran Contribuyente", "[ ] Auto-retenedor", o casillas de "SI / NO"), puedes asociar el rótulo respectivo a un campo booleano de DatosEmpresa. Si el valor es verdadero (True), el sistema escribirá automáticamente una 'X' en la casilla vacía.

Puedes mapear campos de cualquier sección o tabla (incluyendo referencias comerciales, bancarias, junta directiva, accionistas, contactos, etc.) siempre y cuando la información correspondiente exista dentro del objeto DatosEmpresa. No dejes de mapear tablas si el formulario tiene rótulos para ellas y posees los datos de la empresa para rellenarlos.

Reglas de mapeo de campos en secciones válidas:
- razon_social: NOMBRE, NOMBRE / RAZON SOCIAL, NOMBRE EMPRESA, NOMBRE DEL PROVEEDOR, RAZON SOCIAL, EMPRESA.
- nit: NIT, NIT:, IDENTIFICACION NIT, NÚMERO DE NIT, CC/CE/PAS/NIT. (Usa nit_sin_dv y nit_dv si están separados).
- cedula: C.C., CÉDULA, CEDULA, DOCUMENTO, DOCUMENTO DE IDENTIDAD, IDENTIFICACION, NÚMERO DE IDENTIFICACIÓN, ID.
- direccion: DIRECCION, DIRECCIÓN, DOMICILIO, DIRECCIÓN PRINCIPAL.
- ciudad: CIUDAD, MUNICIPIO.
- departamento: DEPARTAMENTO, DPTO.
- telefono: TEL, TELÉFONO, TELEFONOS, CELULAR, CONTACTO TELEFONICO.
- correo: CORREO, CORREO ELECTRONICO, EMAIL, E-MAIL.
- pagina_web: PAGINA WEB, PÁGINA WEB, WEB, SITIO WEB, URL.
- pais: PAIS, PAÍS, NACIONALIDAD.
- banco: BANCO, ENTIDAD BANCARIA, ENTIDAD FINANCIERA, NOMBRE DEL BANCO.
- numero_cuenta: NÚMERO DE CUENTA, NO. CUENTA, NUMERO DE CUENTA, CUENTA NO., NRO CUENTA.
- tipo_cuenta: TIPO DE CUENTA, TIPO CUENTA, TIPO DE CUENTA (AHORROS/CORRIENTE).
- sucursal: SUCURSAL, SUCURSAL BANCARIA, CIUDAD SUCURSAL.

Responde únicamente con JSON válido. Devuelve un arreglo JSON de objetos, o bien envuelve el arreglo dentro de un objeto JSON bajo la clave "mappings" (por ejemplo: {"mappings": [...]}).
Cada elemento del listado de mapeo debe tener las siguientes claves:
- hoja
- fila
- columna
- valor
- ubicacion
- campo
- requiereMerge
- celdasAMergear

Si no corresponde ningún elemento, responde con [] (o {"mappings": []}) y no incluyas explicaciones."""


def _consultar_gemini_studio(
    prompt_usuario: str,
    sistema: str = "",
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY no configurada en .env")

    # Opción A: Usar la SDK oficial google-genai si está disponible
    if genai is not None and types is not None:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            config_kwargs: Dict[str, Any] = {}
            if sistema:
                config_kwargs["system_instruction"] = sistema
            if json_mode:
                config_kwargs["response_mime_type"] = "application/json"

            config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

            MAX_REINTENTOS = 3
            for intento in range(1, MAX_REINTENTOS + 1):
                try:
                    respuesta = client.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=prompt_usuario,
                        config=config,
                    )
                    if respuesta and respuesta.text:
                        return respuesta.text
                    raise RuntimeError("Respuesta vacía de Google AI Studio.")
                except Exception as exc:
                    if intento < MAX_REINTENTOS:
                        time.sleep(2 ** (intento - 1))
                        continue
                    raise exc
        except Exception as exc_sdk:
            print(f"[AutoForm AI Warning] La SDK google-genai devolvió error ({exc_sdk}). Intentando API REST nativa...")

    # Opción B: Usar la API REST de Google AI Studio como respaldo nativo ultrarrápido
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    cuerpo: Dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt_usuario}]
            }
        ]
    }
    if sistema:
        cuerpo["systemInstruction"] = {
            "parts": [{"text": sistema}]
        }
    if json_mode:
        cuerpo["generationConfig"] = {
            "responseMimeType": "application/json"
        }

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

    modelo_openrouter = LLM_MODEL or "inclusionai/ling-3.0-flash:free"
    if "/" not in modelo_openrouter:
        modelo_openrouter = "inclusionai/ling-3.0-flash:free"

    cuerpo: Dict[str, Any] = {
        "model": modelo_openrouter,
        "messages": mensajes,
    }
    # ling-3.0-flash no acepta la clave response_format en el JSON del payload (devuelve 400)
    if json_mode and "ling-3.0-flash" not in modelo_openrouter:
        cuerpo["response_format"] = {"type": "json_object"}

    MAX_REINTENTOS = 3
    ultimo_error: Exception = RuntimeError("Error desconocido")

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
        except requests.Timeout as exc:
            ultimo_error = RuntimeError(
                f"OpenRouter no respondió en {timeout}s (intento {intento}/{MAX_REINTENTOS})."
            )
            if intento < MAX_REINTENTOS:
                time.sleep(2 ** (intento - 1))
                continue
            raise ultimo_error from exc
        except requests.ConnectionError as exc:
            ultimo_error = RuntimeError(
                f"No se pudo conectar a OpenRouter (intento {intento}/{MAX_REINTENTOS})."
            )
            if intento < MAX_REINTENTOS:
                time.sleep(2 ** (intento - 1))
                continue
            raise ultimo_error from exc

        if respuesta.status_code >= 500:
            ultimo_error = RuntimeError(
                f"OpenRouter devolvio {respuesta.status_code} (intento {intento}/{MAX_REINTENTOS})."
            )
            if intento < MAX_REINTENTOS:
                time.sleep(2 ** (intento - 1))
                continue
            raise ultimo_error

        try:
            respuesta.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Error al invocar OpenRouter/LLM: {respuesta.status_code} {respuesta.text}"
            ) from exc

        datos = respuesta.json()
        if not datos:
            raise RuntimeError("Respuesta vacía de OpenRouter.")

        if "error" in datos:
            error_msg = datos["error"].get("message", str(datos["error"]))
            if "522" in error_msg or "502" in error_msg or "503" in error_msg or "timeout" in error_msg.lower():
                ultimo_error = RuntimeError(f"Error de OpenRouter: {error_msg} (intento {intento}/{MAX_REINTENTOS})")
                if intento < MAX_REINTENTOS:
                    time.sleep(2 ** (intento - 1))
                    continue
            raise RuntimeError(f"Error de OpenRouter: {error_msg}")

        if "choices" not in datos or not datos["choices"]:
            raise RuntimeError(f"Respuesta inválida de OpenRouter. Payload: {datos}")

        contenido = datos["choices"][0].get("message", {}).get("content")
        if contenido is None:
            raise RuntimeError("La respuesta del LLM no incluye contenido.")

        return contenido

    raise ultimo_error


def consultar_llm(
    prompt_usuario: str,
    sistema: Optional[str] = None,
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    if sistema is None:
        sistema = "Eres el asistente inteligente de AutoForm AI, impulsado por el modelo Google Gemini 2.0 Flash."

    # 1. Intentar primero la API nativa de Google AI Studio con gemini-2.0-flash
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
    sistema_completo = STRICT_SYSTEM_PROMPT
    if sistema:
        sistema_completo = f"{sistema}\n\n{sistema_completo}"
    return consultar_llm(prompt, sistema=sistema_completo, json_mode=True, timeout=timeout)

