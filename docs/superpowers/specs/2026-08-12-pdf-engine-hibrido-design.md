# Especificación de Diseño: Motor de Procesamiento Híbrido de PDF para AutoForm AI

**Fecha:** 2026-08-12  
**Estado:** Aprobado por el usuario  
**Módulo:** `core/pdf_processor.py`, `core/llm_client.py`, `app1.py`  

---

## 1. Contexto y Objetivos

### 1.1 Problema
Al diligenciar formularios PDF en la versión actual de AutoForm AI, se presentan tres fallas críticas descritas por los usuarios:
1. **Desalineación visual ("llena los datos fuera de las casillas"):** El escáner actual busca espacios de escritura únicamente hacia la derecha en una ventana fija de 15px. Si el espacio de escritura está situado debajo del rótulo (común en tablas o cajas) o desplazado verticalmente, la detección falla y se aplica un rectángulo genérico de 300px que dibuja el texto sobre zonas arbitrarias del documento.
2. **Duplicación de datos ("repite mucho los datos"):** Las palabras o fragmentos de rótulos multilínea se procesan como etiquetas independientes. Esto provoca que el LLM empareje la misma clave corporativa (ej. `razon_social`) a múltiples fragmentos de un mismo campo.
3. **Desbordamiento de plantilla ("se sale de las plantillas del PDF"):** Los rectángulos de fallback genéricos o de dimensiones imprecisas hacen que el texto supere los bordes de las casillas originales.

### 1.2 Objetivos
- Diseñar e implementar un **Motor de PDF Híbrido** que soporte PDFs interactivos (AcroForms), PDFs vectoriales planos y PDFs escaneados (imágenes).
- Implementar **Ray-Casting Bidireccional** (derecha y abajo) y consolidación de rótulos multilínea en el motor local.
- Introducir soporte nativo para **Campos AcroForm** interactivos de PyMuPDF (`widgets`).
- Incorporar **Detección Espacial Visual mediante Gemini Vision** para PDFs escaneados o layouts donde el análisis de fuentes de texto nativas resulte insuficiente.
- Integrar la selección de motores y diagnóstico en la interfaz de Streamlit (`app1.py`).

---

## 2. Arquitectura General del Motor Híbrido

```
                          ┌──────────────────────────┐
                          │   Archivo PDF Cargado    │
                          └────────────┬─────────────┘
                                       │
                                       ▼
                       ┌──────────────────────────────┐
                       │ ¿Contiene texto vectorial o  │
                       │    AcroForms interactivos?   │
                       └───────┬──────────────┬───────┘
                               │              │
                     Sí        │              │ No (Escaneado o
                               ▼              │     Forzado Vision)
           ┌──────────────────────────────┐   │
           │  MÓDULO 1: Motor Local       │   │
           │  (pdfplumber + PyMuPDF)      │   │
           └──────────────┬───────────────┘   │
                          │                   ▼
                          │         ┌──────────────────┐
                          │         │  MÓDULO 2: Motor │
                          │         │  Gemini Vision   │
                          │         └─────────┬────────┘
                          │                   │
                          └─────────┬─────────┘
                                    │
                                    ▼
                       ┌──────────────────────────┐
                       │ MÓDULO 3: Inyector de    │
                       │ Precisión PyMuPDF        │
                       └────────────┬─────────────┘
                                    │
                                    ▼
                       ┌──────────────────────────┐
                       │  PDF Final Diligenciado  │
                       └──────────────────────────┘
```

---

## 3. Especificación Detallada por Módulos

### 3.1 Módulo 1: Motor Local de Detección Espacial Heurística (`core/pdf_processor.py`)

#### A. Consolidación Multilínea y Deduplicación de Rótulos
- **Agrupamiento Geométrico**: Se agruparán palabras adyacentes horizontalmente (distancia $< 12\text{px}$) y verticalmente (distancia $< 10\text{px}$) cuando formen parte de una frase descriptiva continua.
- **Normalización**: Se removerán rótulos duplicados o fragmentados antes de construir la carga útil (*payload*) para la IA, eliminando la sobre-asignación de datos repetidos.

#### B. Ray-Casting Bidireccional (`_calcular_target_rect_bidireccional`)
Dado un rótulo consolidado $(x_0, y_{\text{top}}, x_1, y_{\text{bottom}})$:
1. **Pase 1 - Escaneo Horizontal (Derecha)**:
   - Se buscan rectángulos (`rects`) o líneas horizontales (`lines`) en el rango $y_{\text{top}} \pm 10\text{px}$ a la derecha de $x_1$.
2. **Pase 2 - Escaneo Vertical (Abajo)**:
   - Si no se detecta una caja a la derecha, se proyecta un rayo hacia abajo en la franja $[x_0 - 5\text{px}, x_1 + 50\text{px}]$.
   - Se busca el rectángulo o línea horizontal más cercana situada a menos de $25\text{px}$ abajo del rótulo.
3. **Pase 3 - Acotamiento y Margen de Seguridad**:
   - Si se encuentra una caja o línea, el área de destino se calcula estrictamente dentro de sus límites respetando $2\text{px}$ de margen interno (*padding*).
   - En caso de fallback, la anchura máxima se acota determinísticamente a la distancia al borde de la página o a la siguiente celda visual adyacente.

#### C. Detección de Casillas de Verificación (Checkboxes)
- Se identificarán objetos `rect` cuadrados pequeños ($8\text{px} \times 8\text{px}$ a $18\text{px} \times 18\text{px}$) asociados a textos de opción (ej. *"Sí"*, *"No"*, *"Masculino"*, *"Femenino"*).
- En el mapa se registrarán con la bandera `_pdf_es_casilla: True` y sus coordenadas $(x_0, y_0, x_1, y_1)$ exactas para inyectar un carácter de marca centrada (*"X"* o *"✓"*).

#### D. Soporte Nativo de AcroForms
- Para PDFs interactivos, se iterará sobre los `widgets` de la página (`page.widgets()`).
- Se extraerá una lista de campos AcroForm que incluirá `field_name`, `field_type`, `rect` y `field_value`.
- El plan de mapeo se ejecutará rellenando los campos interactivos nativos (`widget.field_value = val; widget.update()`), lo que garantiza que los datos se ajusten automáticamente al formato nativo del visor de PDF sin desbordamientos.

---

### 3.2 Módulo 2: Motor de IA Visual con Gemini Vision (`core/llm_client.py` & `core/pdf_processor.py`)

#### A. Disparador del Motor de Visión
El motor de visión se activará automáticamente si:
1. El número total de palabras extraídas por `pdfplumber` es $< 15$ en todo el documento (PDF escaneado / imagen).
2. El usuario selecciona explícitamente el modo *"IA Visual - Gemini Vision"* en la interfaz.

#### B. Pipeline Multimodal
1. **Renderizado de Alta Resolución**: La página del PDF se renderizará a PNG a 200 DPI (`Matrix(2.77, 2.77)`).
2. **Inyección en Gemini Vision**: Se enviará el binario PNG junto con la estructura de `DatosEmpresa` y un sistema de prompt especializado.
3. **Bounding Boxes Normalizadas ($0-1000$)**:
   - El prompt exigirá que el LLM responda un JSON estructurado con coordenadas en escala $0-1000$: `[ymin, xmin, ymax, xmax]`.
4. **Desnormalización de Coordenadas**:
   $$\text{x}_0 = \frac{\text{xmin} \cdot \text{ancho\_página}}{1000}, \quad \text{y}_0 = \frac{\text{ymin} \cdot \text{alto\_página}}{1000}$$
   $$\text{x}_1 = \frac{\text{xmax} \cdot \text{ancho\_página}}{1000}, \quad \text{y}_1 = \frac{\text{ymax} \cdot \text{alto\_página}}{1000}$$

---

### 3.3 Módulo 3: Inyector de Precisión PyMuPDF y UI (`app1.py` & `core/pdf_processor.py`)

#### A. Auto-Scaling Proactivo y Truncado Inteligente
- Antes de invocar `insert_textbox`, se calculará el ancho estimado del texto vs. el ancho del `target_rect`.
- Si el texto excede la capacidad a tamaño de fuente mínimo ($5.5\text{pt}$), se aplicará truncado inteligente con elipses (`...`) o se eliminarán caracteres no esenciales (ej. prefijos en teléfonos o extensiones en nombres) únicamente para la capa visual, preservando la integridad de los datos.

#### B. Integración en Streamlit (`app1.py`)
- Se agregará un selector de modo en la interfaz:
  - `Autodetectar (Híbrido - Recomendado)`
  - `Heurístico Local (Rápido)`
  - `IA Visual - Gemini Vision (Máxima Precisión)`
- Se enriquecerá el panel de Debug para mostrar qué motor procesó el PDF, cuántas casillas/AcroForms se detectaron y la cobertura de inyección.

---

## 4. Plan de Verificación y Pruebas

### 4.1 Pruebas Unitarias Sintéticas (`scratch/test_pdf_engine.py`)
1. **Prueba de Ray-Casting Bidireccional**: Verificar que etiquetas con campos debajo ubiquen el `target_rect` inferior en lugar del fallback derecho.
2. **Prueba de AcroForm Nativo**: Verificar que los campos interactivos de un PDF de prueba reciban los valores y no generen desbordamiento visual.
3. **Prueba de Visión (Mock / Live)**: Verificar la desnormalización de coordenadas de $0-1000$ a puntos reales del PDF.

### 4.2 Verificación de Sintaxis y Compilación
- Ejecutar `python -m py_compile core/pdf_processor.py`, `core/llm_client.py`, `core/mapper.py` y `app1.py`.
- Ejecutar el frontend local `streamlit run app1.py` si es requerido para probar la interfaz.
