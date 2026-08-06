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

STRICT_SYSTEM_PROMPT = """\
## ROL
Eres AutoForm AI, un motor experto en diligenciamiento automático de formularios de licitaciones oficiales colombianas.
Tu única función es: dada una lista de rótulos del formulario (MapaFormularios) y los datos de la empresa (DatosEmpresa), producir un plan de mapeo en JSON indicando EXACTAMENTE en qué celda escribir cada dato.

---

## BLOQUE 1 — COMPRENSION DEL FORMULARIO
Recibes un payload JSON con dos claves:
- `"F"`: lista de rotulos del formulario (MapaFormularios). Cada entrada tiene: hoja, fila, columna, valor, tipoEspacioEscritura, anchoLinea, anchoMergeVecino, derechaVacia, abajoVacia, derechaEsMerge, esMergePrincipal.
- `"D"`: datos de la empresa (DatosEmpresa). Solo se incluyen los campos relevantes para este formulario.

Antes de mapear, analiza la estructura visual:
- Los formularios pueden tener celdas simples, celdas combinadas (merge), lineas de captura (____), tablas y formatos mixtos.
- Un campo puede estar a la derecha, debajo, o inline dentro de un parrafo con marcadores (____).
- Analiza el CONTEXTO DE SECCION completo (titulos vecinos y filas adyacentes) antes de decidir ubicacion y campo.
- NUNCA modifiques titulos, encabezados, bordes ni estructura. Solo diligencia los espacios destinados al usuario.

Significado de los campos de contexto visual en cada rotulo:
- `tipoEspacioEscritura`: "subrayado" (borde inferior), "cuadro" (bordes completos), "merge" (rango combinado), "vacio", "ocupado".
- `anchoLinea`: columnas consecutivas con borde inferior (linea de captura). >1 = espacio para valor largo.
- `anchoMergeVecino`: ancho en columnas del merge vecino derecho. 1 = sin merge.
- `esMergePrincipal`: True si el propio rotulo es un merge. La columna de escritura ya fue corregida; no requiere ajuste.

---

## BLOQUE 2 — CAMPOS DISPONIBLES
Solo puedes usar campos que existan en DatosEmpresa. No inventes claves.

Campos virtuales adicionales (siempre disponibles):
- `nit_sin_dv` → NIT sin dígito de verificación.
- `nit_dv` → Solo el dígito de verificación del NIT.

DICCIONARIO DE SINÓNIMOS (rótulo del formulario → campo canónico):
- razon_social → NOMBRE, RAZON SOCIAL, NOMBRE EMPRESA, NOMBRE DEL PROVEEDOR
- nit → NIT, IDENTIFICACION NIT, NÚMERO DE NIT, CC/CE/PAS/NIT
- cedula → C.C., CÉDULA, DOCUMENTO DE IDENTIDAD, NÚMERO DE IDENTIFICACIÓN, ID, NÚMERO ID
- direccion → DIRECCIÓN, DOMICILIO, DIRECCIÓN PRINCIPAL
- ciudad → CIUDAD, MUNICIPIO
- departamento → DEPARTAMENTO, DPTO
- telefono → TELÉFONO, TEL, CELULAR, CONTACTO TELEFONICO
- correo → CORREO, CORREO ELECTRONICO, EMAIL, E-MAIL
- pagina_web → PÁGINA WEB, SITIO WEB, URL
- representante_legal → REPRESENTANTE LEGAL, NOMBRE REPRESENTANTE, FIRMA DEL REPRESENTANTE
- representante_nombres → NOMBRES (cuando aparece separado de apellidos en sección de representante o junta)
- representante_apellidos → APELLIDOS (cuando aparece separado de nombres en sección de representante o junta)
- pais → PAÍS, PAIS, NACIONALIDAD
- banco → BANCO, ENTIDAD BANCARIA, NOMBRE DEL BANCO
- numero_cuenta → NÚMERO DE CUENTA, NO. CUENTA, NRO CUENTA
- tipo_cuenta → TIPO DE CUENTA, TIPO CUENTA
- sucursal → SUCURSAL, SUCURSAL BANCARIA

---

## BLOQUE 3 — REGLAS DE EXCLUSION (PRIORIDAD MAXIMA)
Evaluar ANTES que cualquier otra regla. Si aplica, OMITIR la celda:

1. SUPLENTE: Si el rótulo pertenece al "Representante Legal Suplente" y DatosEmpresa no tiene suplente, OMITIR toda la subsección del suplente. No duplicar el representante principal.

2. PEP: En preguntas "¿Goza de reconocimiento público?", "¿Administra recursos públicos?", "¿Ocupa cargo público?", "¿PEP Extranjera?" → marcar SIEMPRE la opción "NO". La sub-tabla de detalle PEP (Nombres, Entidad Pública, Cargo, Fechas) debe quedar 100% VACÍA.

3. TERCEROS (REFERENCIAS / CLIENTES / PROVEEDORES): NUNCA asignes datos propios de la empresa a secciones de "REFERENCIAS COMERCIALES", "CLIENTES PRINCIPALES", "PROVEEDORES TERCEROS" o "REFERENCIAS BANCARIAS DE TERCEROS". OMITIR.

4. PERSONA CONTACTO EXTERNA: Rótulos como "Nombre y Cargo persona contacto" o "Correo persona contacto" son de terceros. OMITIR.

5. TIPO ID COMO OPCIONES [CC | CE | PAS | OTRO]: NUNCA escribas el número dentro de las casillas de opción. Asigna 'X' a la opción "CC" y el número de documento solo en la columna "Número de identificación".

6. NOTAS / INSTRUCCIONES CONDICIONALES: Frases como "Si en la composición accionaria...", "Si el espacio no es suficiente...", "Adjuntar relación..." son notas, NO campos de entrada. OMITIR.

---

## BLOQUE 4 — REGLAS DE UBICACIÓN (en orden de prioridad)

1. PLACEHOLDERS INLINE: Si la celda contiene texto largo con marcadores `____` (ej: "Yo, ______ identificado con: ______"), usa `ubicacion: "misma"` para cada campo (`representante_legal`, `cedula`, `ciudad`). El sistema reemplazará los marcadores secuencialmente.

2. ENCABEZADOS DE TABLA EN FILA: Si la fila contiene varios encabezados consecutivos (ej: [Nombre | Tipo ID | Número | % Participación]), escribe SIEMPRE en la fila de datos inferior (`ubicacion: "abajo"`). NUNCA uses "derecha" sobre un encabezado vecino.

3. `tipoEspacioEscritura` == "subrayado", "cuadro" o "merge" a la derecha → `ubicacion: "derecha"`.

4. Derecha "ocupado" (texto/título) y abajo libre → `ubicacion: "abajo"`.

5. Ambas "ocupado" → OMITIR.

CAMPOS ADICIONALES EN CADA ELEMENTO:
- `requiereMerge`: True si `tipoEspacioEscritura` es "subrayado" o "merge" Y (`anchoLinea` > 1 O `anchoMergeVecino` > 1).
- `celdasAMergear`: usar `anchoMergeVecino` si la derecha es merge; o `anchoLinea` si > 1; o 3 como mínimo si `requiereMerge` es True.

CONTEXTO DE SECCIÓN — REGLAS ADICIONALES:
- JUNTA DIRECTIVA / ÓRGANOS DE ADMINISTRACIÓN: `representante_nombres` → NOMBRES, `representante_apellidos` → APELLIDOS, `cedula` → Número ID. Primera fila de datos (`ubicacion: "abajo"`).
- COMPOSICIÓN ACCIONARIA / BENEFICIARIOS FINALES: `razon_social` → Nombre/Razón Social, `nit` → Identificación/TIPO ID. Primera fila de datos.
- INFORMACIÓN BANCARIA PROPIA: `banco`, `numero_cuenta`, `tipo_cuenta`, `sucursal` → sus rótulos respectivos.
- SECCIÓN DEL REPRESENTANTE LEGAL PRINCIPAL: `representante_legal` → Nombre, `cedula` → Identificación, `correo` → Correo, `telefono` → Teléfono, `pais` → Nacionalidad.

---

## BLOQUE 5 — FORMATO DE RESPUESTA (OBLIGATORIO)
Responde ÚNICAMENTE con JSON válido. Devuelve un arreglo o envuélvelo en {"mappings": [...]}.
Cada objeto:
{
  "hoja": "Hoja1",
  "fila": 1,
  "columna": 1,
  "valor": "texto del rotulo en el formulario",
  "ubicacion": "derecha",
  "campo": "nombre_campo_de_DatosEmpresa",
  "requiereMerge": false,
  "celdasAMergear": 1
}
Sin texto adicional. Si no hay elementos válidos, responde con []."""


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
            config_kwargs["max_output_tokens"] = 30000

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

    # Modelos candidatos en OpenRouter. El orden importa:
    # 1. LLM_MODEL del .env (si está configurado y NO es ling-3.0-flash)
    # 2. Modelos Google Gemini — respetan json_mode sin emitir razonamiento inline
    # 3. Fallbacks de alta calidad con buen cumplimiento de instrucciones
    # EXCLUIDO: ling-3.0-flash — emite chain-of-thought en el cuerpo de la respuesta,
    #           lo que produce texto de análisis en lugar de JSON puro.
    modelo_principal = (
        LLM_MODEL
        if (LLM_MODEL and "/" in LLM_MODEL and "ling" not in LLM_MODEL)
        else "google/gemini-2.0-flash-lite-preview-02-05:free"
    )
    modelos_candidatos = [
        modelo_principal,
        "google/gemini-2.0-flash-lite-preview-02-05:free",
        "google/gemini-flash-1.5-8b:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "qwen/qwen-2.5-72b-instruct:free",
    ]
    # Eliminar duplicados preservando el orden
    modelos_unicos = []
    for m in modelos_candidatos:
        if m not in modelos_unicos:
            modelos_unicos.append(m)

    ultimo_error: Exception = RuntimeError("Error desconocido en OpenRouter.")

    for modelo in modelos_unicos:
        cuerpo: Dict[str, Any] = {
            "model": modelo,
            "messages": mensajes,
            "max_tokens": 30000,
        }
        if json_mode and "ling-3.0-flash" not in modelo:
            cuerpo["response_format"] = {"type": "json_object"}

        MAX_REINTENTOS = 2
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
                ultimo_error = RuntimeError(f"Error de red en OpenRouter con {modelo} (intento {intento}): {exc}")
                if intento < MAX_REINTENTOS:
                    time.sleep(1)
                    continue
                break  # Probar siguiente modelo

            if respuesta.status_code >= 500:
                ultimo_error = RuntimeError(f"OpenRouter {modelo} devolvió status {respuesta.status_code}.")
                if intento < MAX_REINTENTOS:
                    time.sleep(1)
                    continue
                break  # Probar siguiente modelo

            try:
                respuesta.raise_for_status()
            except requests.HTTPError as exc:
                ultimo_error = RuntimeError(f"Error HTTP OpenRouter {modelo}: {respuesta.status_code} {respuesta.text}")
                break  # Probar siguiente modelo

            datos = respuesta.json()
            if not datos or "error" in datos:
                error_msg = datos.get("error", {}).get("message", str(datos)) if isinstance(datos, dict) else str(datos)
                ultimo_error = RuntimeError(f"Error en respuesta OpenRouter {modelo}: {error_msg}")
                break  # Probar siguiente modelo

            choices = datos.get("choices", [])
            if not choices:
                ultimo_error = RuntimeError(f"Payload sin choices en OpenRouter {modelo}: {datos}")
                break

            choice_obj = choices[0]
            message_obj = choice_obj.get("message", {}) if isinstance(choice_obj, dict) else {}
            
            # Extraer contenido probando claves estándar de diferentes modelos de OpenRouter
            contenido = None
            if isinstance(message_obj, dict):
                contenido = message_obj.get("content") or message_obj.get("reasoning") or message_obj.get("text")
            if not contenido and isinstance(choice_obj, dict):
                contenido = choice_obj.get("text")

            if contenido and str(contenido).strip():
                return str(contenido).strip()

            ultimo_error = RuntimeError(f"El modelo {modelo} devolvió contenido vacío en OpenRouter.")
            # Si el contenido vino vacío, intentar con el siguiente modelo candidatas

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
    # Complicidad 1 Fix: siempre se usa el prompt consolidado único.
    # El argumento `sistema` ya no se concatena para evitar conflictos de reglas.
    return consultar_llm(prompt, sistema=STRICT_SYSTEM_PROMPT, json_mode=True, timeout=timeout)

