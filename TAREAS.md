# 📋 TAREAS.md — Backlog Técnico AutoForm AI

> **Rol:** Arquitecto de Software / Lead Developer
> **Fecha de análisis:** 2026-08-05
> **Versión del proyecto analizada:** Fase 3 activa (Excel). PDF en construcción.

---

## 🟢 Prioridad Alta — Esenciales para la Precisión de Inyección en Excel

### FASE 1 — Extracción (`excel_parser.py`)

- [x] **[PARSER-01]** Agregar detección de **bordes visuales** (`border.bottom`, `border.top`, `border.left`, `border.right`) para cada celda candidata y sus vecinas. Exportar como `derechaConBordeInferior`, `abajoConBordeInferior`, `tipoEspacioEscritura` (`subrayado` | `cuadro` | `merge` | `vacio`) para enriquecer el contexto enviado al LLM.
- [x] **[PARSER-02]** Detectar **líneas de captura divididas entre celdas consecutivas** (`______` en B10, C10, D10 todas con borde inferior y vacías). Calcular `anchoLinea` automáticamente y exportarlo para que el escritor las combine antes de escribir.
- [x] **[PARSER-03]** Detectar **relleno de fondo de celda** (`fill.fgColor`) de la celda y sus vecinas, exportar como `colorFondo` (hex). Permite al LLM identificar secciones resaltadas y al escritor preservar el color al rellenar.
- [x] **[PARSER-04]** Agregar detección del **ancho real del rango combinado** al que pertenece la celda contigua (`anchoMergeVecino`), para que el escritor sepa exactamente cuántas columnas abarca el espacio de entrada y no lo subestime al hacer `merge_cells`.
- [x] **[PARSER-05]** Detectar y exportar si la **celda actual pertenece a un rango combinado** (`esMergePrincipal`, `coordMerge`), para que el mapeador pueda saltar sub-celdas de un merge ya procesado y evitar duplicados en el mapa.

---

### FASE 3 — Inyección en Excel (`excel_writer.py`)

- [x] **[WRITER-01]** Implementar **preservación de color de fondo** (`PatternFill`) al escribir en celdas destino. Actualmente se sobreescribe el color con blanco al asignar `Alignment`, destruyendo el diseño visual del formulario.
- [x] **[WRITER-02]** Implementar **preservación de fuente original** (`Font`) de la celda destino. Al escribir el valor, respetar `font.name`, `font.size`, `font.bold` y `font.color` de la celda de captura original.
- [x] **[WRITER-03]** Implementar **llenado automático de líneas de captura divididas**. Si `anchoLinea > 1`, detectar celdas consecutivas con borde inferior y vacías, combinarlas en un rango y escribir el valor una sola vez sin fragmentarlo.
- [x] **[WRITER-04]** Mejorar `_copiar_borde_inferior` para copiar **todos los bordes relevantes** (`top`, `left`, `right`, `bottom`) de la celda origen a la destino, no solo el inferior, conservando el aspecto visual completo.
- [x] **[WRITER-05]** Manejar `valor is None` de forma **silenciosa (skip)** en lugar de lanzar `ValueError`. Si el campo no está en `datos_empresa.json`, ignorar ese elemento del plan de mapeo y continuar sin interrumpir el proceso.

---

### FASE 2 — Inferencia LLM (`llm_client.py`, `mapper.py`)

- [x] **[LLM-01]** Enriquecer el `SYSTEM_PROMPT` en `mapper.py` con las nuevas claves del mapa (`tipoEspacioEscritura`, `derechaConBordeInferior`, `anchoMergeVecino`), instruyendo al LLM a priorizar `tipoEspacioEscritura: "subrayado"` como espacio de escritura.
- [x] **[LLM-02]** Implementar **retry automático** en `_consultar_llm_requests` con backoff exponencial (1–3 intentos) ante errores `5xx` de OpenRouter.

---

## 🟡 Prioridad Media — Optimizaciones de Proceso y Filtros

### FASE 1 — Extracción (`excel_parser.py`)

- [ ] **[PARSER-06]** Implementar **detección de tipo de celda de entrada** combinando heurísticas: celda vacía + borde inferior = `subrayado`; celda vacía + todos los bordes = `cuadro`; celda vacía + merge = `espacio_merge`. Exportar `tipoEntrada`.
- [x] **[PARSER-07]** Agregar soporte para **filtrar hojas por nombre** desde la UI. Descartar hojas como `"Instrucciones"`, `"Portada"` o `"Referencias"` que no contienen formularios rellenables.
- [x] **[PARSER-08]** Mejorar filtrado de ruido: omitir celdas cuyo texto sea una **fecha, código CIIU, número con formato de texto o solo caracteres de puntuación**, que pasan el filtro de longitud y llegan al LLM innecesariamente.

---

### FASE 2 — Inferencia LLM (`mapper.py`, `llm_client.py`)

- [ ] **[LLM-03]** Implementar **deduplicación de coordenadas destino** en el plan de mapeo. Si dos entradas apuntan a la misma celda `(hoja, fila_destino, columna_destino)`, conservar solo la primera y descartar las duplicadas.
- [x] **[LLM-04]** Implementar **caché de respuestas del LLM** basada en hash del mapa de formularios. Si el mismo formulario ya fue procesado en la sesión, devolver el resultado en caché sin repetir la llamada a la API.
- [x] **[LLM-05]** Agregar un **panel de debug visible en la UI** (sección expandible en `app1.py`) con el mapa enviado al LLM y el JSON de respuesta, para diagnosticar campos no mapeados.

---

### FASE 3 — Inyección en Excel (`excel_writer.py`)

- [ ] **[WRITER-06]** Implementar **soporte para merge vertical** en dirección `abajo`. Si el formulario tiene casillas de entrada en filas combinadas verticalmente, el escritor debe soportar combinarlas verticalmente.
- [x] **[WRITER-07]** Agregar **validación de coordenadas fuera de rango** antes de escribir. Si la fila o columna destino excede `ws.max_row` / `ws.max_column`, saltarla silenciosamente.

---

## 🔵 Prioridad Baja — Calidad, Resiliencia y Futuro

### FASE 1 — Extracción

- [ ] **[PARSER-09]** Agregar soporte para **tablas definidas como `Table` de Excel** (`openpyxl.worksheet.table`). Detectarlas y exportar sus rangos como contexto adicional al LLM.
- [ ] **[PARSER-10]** Implementar **módulo de inspección de PDF** (`pdf_processor.py`) con extracción de texto con coordenadas `(x, y, ancho, alto)`, usando `pdfplumber`, para la Fase 2 de soporte PDF.

---

### FASE 2 — Inferencia LLM

- [ ] **[LLM-06]** Implementar **soporte para múltiples modelos LLM** configurable desde la UI (Gemini Flash, GPT-4o Mini, Llama 3 vía OpenRouter).
- [ ] **[LLM-07]** Construir **módulo de evaluación de precisión** (`core/evaluator.py`) que compare el formulario original vs. el diligenciado, calculando score de cobertura (campos rellenados / campos esperados).
- [ ] **[LLM-08]** Implementar **prompts parametrizados por sección** (`config/prompts/`) donde cada tipo de sección tenga un prompt especializado cargado dinámicamente.

---

### FASE 3 — Inyección en Excel

- [ ] **[WRITER-08]** Implementar **modo "track-changes"**: Guardar snapshot de cada celda antes de modificarla. Al finalizar, mostrar en la UI una tabla de cambios con hoja, coordenada, valor anterior y valor nuevo.
- [ ] **[WRITER-09]** Agregar soporte para **formatos de número** (`number_format`). Si la celda destino tiene un formato numérico (ej. `#,##0.00`), aplicar el valor correctamente en lugar de forzarlo como string.
- [ ] **[WRITER-10]** Implementar **validación de datos** (`DataValidation`). Si la celda destino tiene una lista desplegable de Excel, verificar que el valor sea compatible antes de escribirlo, y emitir advertencia si no lo es.

---

### Infraestructura General (`app1.py`, `config/`)

- [x] **[APP-01]** Agregar **editor visual de `datos_empresa.json`** en la barra lateral de Streamlit para agregar, editar y eliminar campos corporativos directamente desde la UI.
- [x] **[APP-02]** Implementar **soporte para múltiples perfiles de empresa** (`datos_empresa_*.json`). Permitir al usuario seleccionar el perfil activo desde la UI antes de procesar.
- [ ] **[APP-03]** Agregar **autenticación básica por contraseña** en Streamlit para proteger el acceso a la aplicación y a las claves API configuradas en `.env`.

---

> **Total de tareas identificadas:** 28
> 🟢 Alta: 9 | 🟡 Media: 8 | 🔵 Baja: 11
