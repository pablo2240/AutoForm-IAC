# Plan de Corrección: Optimización de Latencia (15x) y Reparación de Integridad XML

## 1. Diagnóstico del Problema

### A. Causa de la Latencia (~48 segundos en Stage 3)
* En documentos con múltiples subtítulos como `FMCA07J`, el motor `_construir_lotes_secciones_desde_ir` generaba **16 secciones separadas** (muchas con 1 o 2 campos).
* El pipeline ejecutaba **16 llamadas HTTP secuenciales** a la API de OpenAI, acumulando $16 \times 3\text{s} = \mathbf{47.43\text{s}}$.

### B. Causa de Archivos Rotos / Dañados al Descargar
* En `core/excel_writer.py`, la inyección de `<legacyDrawing>` y `<controls>` se realizaba directamente antes de `</worksheet>`.
* El estándar ECMA-376 (SpreadsheetML) impone un orden estricto de etiquetas hijas. Colocar `<legacyDrawing>` o `<controls>` después de `<tableParts>` o `<extLst>` corrompe la estructura XML, haciendo que Microsoft Excel muestre la alerta *"Excel ha detectado contenido que no se puede leer... ¿Desea recuperar el contenido de este libro?"*.

---

## 2. Cambios Propuestos

### 🚀 Optimización de Rendimiento (`pipeline/stages/stage_3_llm_mapper.py`)
1. **Agrupación en Macro-Lotes (Máx. 3–4 bloques por formulario):**
   * Fusionar secciones contiguas pequeñas en bloques coherentes de 12 a 25 campos para no saturar con micro-peticiones.
2. **Ejecución Concurrente con `ThreadPoolExecutor`:**
   * Enviar los 3–4 macro-lotes a OpenAI en paralelo mediante hilos concurrentes.
   * Reducir el tiempo total de Stage 3 de **47.4s a ~3.0s (15x más rápido)**.

---

### 🛡️ Reparación de Integridad XML (`core/excel_writer.py`)
1. **Inserción Canónica según ECMA-376:**
   * Ubicar `<legacyDrawing>` inmediatamente después de `<drawing>` (o después de `<pageSetup>` / `<headerFooter>`).
   * Ubicar `<controls>` inmediatamente después de `<legacyDrawing>` y estrictamente **antes** de `<tableParts>` y `<extLst>`.
2. **Validación de Relaciones (`.rels`):**
   * Garantizar identificadores únicos `rId` para que los controles VML (checkboxes / radio buttons) no colisionen con las relaciones generadas por OpenPyXL.

---

### 🧠 Optimización de Memoria en FastEmbed (`core/fastembed_matcher.py`)
1. Pre-cargar el modelo de forma limpia suprimiendo advertencias de HuggingFace/symlinks en Windows y cacheando los vectores de taxonomía en memoria.

---

## 3. Plan de Verificación

### 1. Medición Comparativa de Latencia
- Ejecutar `scratch/diag_xml_and_latency.py` con `forzar_ia=True` antes y después:
  * **Meta:** Reducir tiempo de Stage 3 de **47.4s a menos de 4.0s**.

### 2. Validación Estricta de XML OpenXML
- Validar que `sheet1.xml` cumpla el orden canónico de elementos y que no haya advertencias al abrir el archivo descargado.

### 3. Suite de Regresión Completa
- Ejecutar todas las pruebas existentes:
  * `test_spatial_ir.py`
  * `test_semantic_validator.py`
  * `test_stage_3_hsp.py`
  * `test_contextual_numero.py`
  * `test_shaded_backgrounds.py`
  * `test_fastembed_rescue.py`
  * `test_instructor_chunking_diff_loop.py`
  * `test_user_form_e2e.py`
