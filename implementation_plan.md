# Plan de Implementación: Capa 1 — Chunking por SeccionIR con Instructor

## Objetivo
Implementar la **Capa 1 de la Tríada Zero-Omission**: procesar los formularios divididos por **secciones lógicas (`SeccionIR`) en lotes pequeños (3 a 15 campos)** utilizando la librería **`instructor`** con validación de esquemas Pydantic V2 (`PlanMapeoSemantico`) y reintentos automáticos, eliminando la omisión de campos intermedios por truncamiento de arrays (*Lost in the Middle*).

## User Review Required
> [!IMPORTANT]
> **Estrategia de Ejecución por Lotes:**
> 1. En lugar de enviar los 80 campos del formulario en un único prompt monolítico, el motor enviará lotes contextualizados de 3 a 15 campos según la jerarquía de `SeccionIR`.
> 2. Cada llamada usará `instructor.from_openai` para validar la respuesta con el modelo Pydantic `PlanMapeoSemantico`.
> 3. Si `instructor` o la llamada estructurada presentara alguna excepción, existe un *fallback* automático a la llamada estándar `invocar_llm`.

## Proposed Changes

### 1. Modelos de Esquema (`core/schema_models.py`)
- Afinar `PlanMapeoSemantico` y `MapeoSemanticoItem` para asegurar que el modelo Pydantic acepte e infiera de forma robusta `id`, `campo` y `ubicacion`.

### 2. Cliente LLM (`core/llm_client.py`)
- Crear `obtener_cliente_instructor()` que configura el cliente parcheado de `instructor` sobre `openai.OpenAI` o `openai.AzureOpenAI`.
- Implementar `consultar_llm_seccion_instructor(campos_seccion, taxonomia_d, titulo_seccion)` con `response_model=PlanMapeoSemantico` y `max_retries=2`.
- Mantener fallback transparente a `invocar_llm` en caso de fallos.

### 3. Stage 3 LLM Mapper (`pipeline/stages/stage_3_llm_mapper.py`)
- Implementar `_construir_lotes_secciones_desde_ir(ctx)` para agrupar campos viables por cada `SeccionIR` procesable manteniendo IDs globales únicos correlacionados.
- Iterar por secciones invocando `consultar_llm_seccion_instructor` y consolidar los mapeos.
- Fallback para documentos sin IR: chunking automático en paquetes de máximo 15 campos.
- Registro detallado de observabilidad por sección en `ctx.log`.

---

## Plan de Verificación

### 1. Pruebas Unitarias de Instructor y Esquemas
- Crear `scratch/test_instructor_chunking.py` para probar la inferencia por sección con `instructor` y validar que el resultado cumpla el esquema `PlanMapeoSemantico`.

### 2. Benchmark en Formularios Reales (`FMCA07J` y `GE.F.021`)
- Ejecutar `scratch/benchmark_baseline.py` con `forzar_ia=True` para medir la tasa de cobertura y verificar que ningún campo válido quede omitido.

### 3. Suite de Regresión Completa
- Ejecutar todos los tests unitarios (`test_spatial_ir.py`, `test_semantic_validator.py`, `test_stage_3_hsp.py`, `test_contextual_numero.py`, `test_shaded_backgrounds.py`, `test_user_form_e2e.py`).

### 4. Verificación de Sintaxis
- `python -m py_compile core/schema_models.py core/llm_client.py pipeline/stages/stage_3_llm_mapper.py`.
