# Especificación de Diseño Técnico: Detección de Casillas de Verificación en Excel

- **Fecha**: 2026-08-06
- **Estrategia Seleccionada**: Enfoque Híbrido Geométrico + Semántico (Bordes 3/4 + Vecino Opción Corta)
- **Módulos Afectados**: [`core/excel_parser.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/excel_parser.py), [`core/mapper.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/mapper.py), [`core/llm_client.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/llm_client.py)

---

## 🎯 Objetivo

Identificar automáticamente celdas de Excel que funcionan como casillas de verificación (checkboxes/cajas de selección para `X`) marcándolas con el atributo `"esCasillaVerificacion": True` en el mapa JSON del formulario.

---

## 🏗️ Criterios de Clasificación Híbrida

Una celda se clasifica como `esCasillaVerificacion = True` si cumple simultáneamente la **Condición Física** y la **Condición Semántica**:

### 1. Condición Física (Geometría del Excel)
- `es_vacia`: La celda no contiene valor (`celda.value is None or ""`).
- `lados_con_borde >= 3`: Al menos 3 de los 4 bordes (`top`, `bottom`, `left`, `right`) están activos.
- `anchoLinea == 1`: Es una celda individual de 1 sola columna.
- `es_merge == False`: No pertenece a un rango combinado largo.

### 2. Condición Semántica (Contexto Vecino)
Se evalúa la celda inmediatamente a la **izquierda** `(fila, col - 1)` o a la **derecha** `(fila, col + 1)`:
- Su texto vecino tiene una longitud reducida (`len(texto_vecino) <= 20`).
- O coincide con patrones conocidos de opción: `r"^\s*(S[ÍI]|NO|C\.?C\.?|C\.?E\.?|PASAPORTE|NIT|OTRO|AUTORRETENEDOR|GRAN CONTRIBUYENTE|MEDIANA|PEQUEÑA|GRAN EMPRESA)\b"`.

---

## 🔧 Cambios en el Código

### 1. [`core/excel_parser.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/excel_parser.py)
- Añadir la función `_es_casilla_verificacion(hoja, fila, col, vacia, es_merge, bordes, ancho_linea)`.
- Incluir la clave `"esCasillaVerificacion"` en cada elemento retornado por `extraer_mapa_formularios`.

### 2. [`core/mapper.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/mapper.py)
- Preservar `"esCasillaVerificacion"` en `_CLAVES_LLM` para que se envíe al modelo en el payload de la IA.

### 3. [`core/llm_client.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/llm_client.py)
- Actualizar `STRICT_SYSTEM_PROMPT` (BLOQUE 1) indicando:
  - `esCasillaVerificacion`: `True` si la celda es una casilla de selección. Si la opción aplica, el campo `valor` a asignar debe ser `"X"`.

---

## 🧪 Plan de Verificación

1. **Prueba Unitaria Automatizada**:
   - Crear `scratch/test_casillas_verificacion.py` creando celdas cuadradas con bordes de 1x1 asociadas a rótulos `"C.C."` y `"SÍ"`.
   - Confirmar que `extraer_mapa_formularios` asigna `esCasillaVerificacion: True`.

2. **Verificación Integrada**:
   - Ejecutar el parser en el formulario `FORMATO SAGRILAFT PROVEEDORES`.
