# AGENTS.md - Guía para Agentes IA (AutoForm AI)

Guía compacta para trabajar en **AutoForm AI** (IAC Latam): llenado automático de formularios corporativos en Excel (.xlsx, .xlsm, .xls) mapeando un perfil de empresa (`config/datos_empresa.json`) vía LLM, conservando estilos y formato original.

## Punto de entrada y flujo

- La app Streamlit es **`app1.py`** (NO `app.py`). El `README.md` está desactualizado (dice `app.py` y "Gemini vía OpenRouter"); confía en el código real.
- Flujo: usuario sube `.xlsx` → `excel_parser.py` escanea campos vacíos → `mapper.py` invoca el LLM para el mapeo semántico → `excel_writer.py` escribe conservando formato → descarga.
- `app1.py` recarga al inicio algunos módulos de `core/` vía `importlib.reload` (líneas ~19-21) para el hot-reload de Streamlit.

## Arquitectura (`core/`)

- `excel_parser.py`: escaneo de celdas/vecinos, ray-casting, casillas de verificación, `_calcular_ubicacion_fisica`.
- `excel_writer.py`: escritura segura en Excel preservando estilos y celdas combinadas.
- `field_detection_engine.py`: motor de detección de campos y coordenadas físicas (dataclass `FormFieldIntent`, clasificador de patrones). **No lo importa ningún otro módulo** todavía; módulo independiente.
- `mapper.py`: orquestador del plan de mapeo; usa `semantic_cache` (similitud difusa con rapidfuzz) para reutilizar plantillas ya mapeadas.
- `llm_client.py`: cliente LLM y `STRICT_SYSTEM_PROMPT`. Salidas validadas con Pydantic V2 en `schema_models.py` (`instructor`).
- `database.py`: motor SQLite canónico (`config/empresa.db`) con transacciones ACID para perfiles empresariales.
- `profile_manager.py`: orquestador de perfiles empresariales (lectura/escritura canónica en SQLite con espejo resiliente en JSON).

## Variables de entorno (¡clave!)

- El LLM real usa la **API de OpenAI**, no OpenRouter: `OPENAI_API_KEY` y `OPENAI_MODEL` (default `gpt-4.1-mini`) en `core/llm_client.py:56-57`. El README que menciona `OPENROUTER_API_KEY` está obsoleto.
- No existe `.env.example` en el repo (el README lo referencia, pero no está). Se crea `.env` a partir de `.env` local/copias manuales.
- `.env` está en `.gitignore`; **nunca** leerlo en busca de valores ni subir/commitear su contenido. Lee claves solo por `os.getenv`.

## Dependencias y entorno

- Sí hay venv (`venv/`, en `.gitignore`). Usa `.\venv\Scripts\python.exe` / `.\venv\Scripts\streamlit.exe` (Windows).

## Comandos

- Ejecutar app: `streamlit run app1.py`
- Pruebas: no hay framework de tests; los scripts de prueba viven en `scratch/` (gitignored) como Python puro, p. ej. `python scratch/test_sc_com_run.py`. Esos scripts insertan la raíz en `sys.path` para importar `core/`.
- Verificación de sintaxis: `python -m py_compile app1.py` y cada archivo de `core/` editado.

## Convenciones de código

- Type hints en todas las funciones; `snake_case` (privadas con prefijo `_`), clases `PascalCase`, constantes `UPPER_SNAKE_CASE`.
- Docstrings descriptivos en funciones complejas; no suprimir excepciones en silencio (manejar `ValueError`/`AttributeError` en flujos de archivos).

## Flujo de trabajo

- Investigar antes de proponer código: leer los módulos reales de `core/`; usar las skills de `.agents/skills/` (p. ej. `brainstorming`, `grill-with-docs`) ante ambigüedad.
- Cambios grandes/rediseño: generar primero un plan, esperar aprobación del usuario antes de editar.
- Cambios pequeños: aplicar directo.
- Al terminar un turno con cambios: reportar archivos modificados, propósito y si se corrió `py_compile`/tests (y resultado).

## Agent Skills (Matt Pocock & Custom)

El proyecto cuenta con la suite de skills de ingeniería y productividad de Matt Pocock (`.agents/skills/`):
- **Alineación & Diseño**: `/grill-with-docs`, `/grill-me`, `/brainstorming`, `/domain-modeling` (lee `CONTEXT.md` y `docs/adr/`).
- **Desarrollo & Calidad**: `/tdd` (Red-Green-Refactor), `/diagnosing-bugs`, `/implement`, `/code-review`.
- **Arquitectura & Tareas**: `/improve-codebase-architecture`, `/to-spec`, `/to-tickets`, `/wayfinder`, `/triage`.
- **Configuración & Dominio**: Consulta `CONTEXT.md` para el vocabulario ubicuo y `docs/agents/` para las convenciones de issue tracking.
