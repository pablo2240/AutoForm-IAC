# Walkthrough: Implementación de Capa 1 (Chunking por SeccionIR con Instructor) y Capa 2 (Diff Loop / Auditoría)

Implementación exitosa de las dos primeras capas de la **Tríada Zero-Omission** en AutoForm AI para eliminar la omisión de campos intermedios por límites de tokens y garantizar una cobertura del 100% de datos en formularios complejos.

---

## 1. Modificaciones Realizadas

### A. [`core/llm_client.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/llm_client.py) (Capa 1)
* **Integración Nativa de Instructor**:
  * `obtener_cliente_instructor()`: Parchea el cliente oficial de `openai.OpenAI` o `openai.AzureOpenAI` con `instructor.from_openai`.
* **Inferencia Estructurada por Lotes**:
  * `consultar_llm_seccion_instructor(campos_seccion, taxonomia_d, titulo_seccion)`: Envía el lote específico de la sección (3 a 15 campos), valida contra el esquema Pydantic V2 `PlanMapeoSemantico` y aplica `max_retries=2` con reintentos automáticos transparentes si el LLM devuelve un formato erróneo.
  * Fallback automático a `invocar_llm` en caso de error.

### B. [`pipeline/stages/stage_3_llm_mapper.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/pipeline/stages/stage_3_llm_mapper.py) (Capa 1 & Capa 2)
* **`_construir_lotes_secciones_desde_ir(ctx)` (Capa 1)**:
  * Agrupa los campos viables por cada `SeccionIR` procesable manteniendo IDs globales correlacionados continuos.
* **`_ejecutar_diff_loop_seccion(...)` (Capa 2)**:
  * Bucle de auditoría y reconciliación en Python puro ($0 costo API).
  * Calcula: $\text{Omitidos} = \text{Campos Viables de Sección} - \text{Campos Mapeados por LLM}$.
  * Si la empresa tiene datos disponibles en el dominio de la sección y hay campos viables omitidos, ejecuta rescate determinista inmediato.
* **`ejecutar_stage_3_mapper(ctx)`**:
  * Orquesta la ejecución sección por sección con registro de observabilidad detallada.
  * Fallback con chunking de seguridad en paquetes de 15 campos para documentos planos sin IR.

---

## 2. Pruebas y Verificación

1. **Test Específico de Capa 1 y Capa 2 ([`scratch/test_instructor_chunking_diff_loop.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/scratch/test_instructor_chunking_diff_loop.py)):**
   * ✅ **Test 1:** Cliente Instructor inicializado exitosamente sobre OpenAI.
   * ✅ **Test 2:** Construcción de 16 lotes limpios por `SeccionIR` sobre `FMCA07J` (IDs 1..88, lotes de 1 a 21 campos).
   * ✅ **Test 3:** Diff Loop: Detección de 2 campos omitidos y rescate exitoso de `nit` y `direccion` por auditoría.

2. **Suite Completa de Regresión:**
   * `test_spatial_ir.py` $\rightarrow$ **35/35 OK** 🟢
   * `test_semantic_validator.py` $\rightarrow$ **48/48 OK** 🟢
   * `test_stage_3_hsp.py` $\rightarrow$ **21/21 OK** 🟢
   * `test_contextual_numero.py` $\rightarrow$ **13/13 OK** 🟢
   * `test_section_title_defense.py` $\rightarrow$ **100% OK** 🟢
   * `test_shaded_backgrounds.py` $\rightarrow$ **100% OK** 🟢
   * `test_user_form_e2e.py` $\rightarrow$ **100% OK** 🟢
   * `test_instructor_chunking_diff_loop.py` $\rightarrow$ **100% OK** 🟢

3. **Verificación de Sintaxis:**
   * `python -m py_compile core/schema_models.py core/llm_client.py pipeline/stages/stage_3_llm_mapper.py core/coverage_engine.py` $\rightarrow$ **0 errores**.
