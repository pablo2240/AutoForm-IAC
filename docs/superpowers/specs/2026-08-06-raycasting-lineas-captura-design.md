# Especificación de Diseño Técnico: Ray-Casting Horizontal para Líneas de Captura (`border.bottom`)

- **Fecha**: 2026-08-06
- **Estrategia Seleccionada**: Opción 2 — Ray-Casting Horizontal y Vinculación Explícita de `columnaEscritura`
- **Módulos Afectados**: [`core/excel_parser.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/excel_parser.py), [`core/mapper.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/mapper.py), [`core/excel_writer.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/excel_writer.py)

---

## 🎯 Objetivo

Garantizar la asociación precisa entre rótulos de formulario (ej: `"Yo,"`, `"identificado con:"`, `"expedido en:"`) y sus celdas de destino con línea de captura (`border.bottom`), escaneando horizontalmente en la misma fila y registrando la coordenada exacta de escritura `columnaEscritura`.

---

## 🏗️ Diseño Técnico

### 1. Escaneo Ray-Casting Horizontal en Fase 1 ([`core/excel_parser.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/excel_parser.py))

Al procesar una celda con etiqueta en `(fila, columna)`:
- En lugar de asumir únicamente la celda contigua `columna + 1`, el parser realiza un escaneo horizontal desde `col = columna + 1` hasta encontrar:
  1. La **primera celda vacía con `border.bottom == True`** o primera celda con `tipoEspacioEscritura in ("subrayado", "cuadro", "merge")`.
  2. Si encuentra dicha celda en `col_destino`, se guarda `columnaEscritura = col_destino`.
  3. Si encuentra otro rótulo con texto antes de hallar un borde, se detiene y reporta `columnaEscritura = columna + 1` (fallback estándar).

### 2. Preservación en Mapeo ([`core/mapper.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/mapper.py))
- La clave `"columnaEscritura"` se incluye en `_CLAVES_LLM` para ser preservada durante la purga del mapa y transferida al plan de mapeo devuelto por la IA.

### 3. Escritura Exacta en Fase 3 ([`core/excel_writer.py`](file:///c:/Users/Asus%20Vivobook%2016/Documents/GitHub/autoform-ai/core/excel_writer.py))
- En `rellenar_formulario_excel`:
  - Si el item del plan de mapeo incluye `"columnaEscritura"` y `ubicacion == "derecha"`, se utiliza `columna_destino = item["columnaEscritura"]` de forma prioritaria, garantizando que el texto se escriba exactamente en la celda que posee el borde inferior.

---

## 🧪 Plan de Verificación

1. **Prueba Unitaria Automatizada**:
   - Crear `scratch/test_raycasting_lineas.py` con una hoja de Excel donde la etiqueta `"Yo,"` está en la Columna 2, hay celdas vacías sin borde en Columnas 3 y 4, y la celda con `border.bottom` está en Columna 5.
   - Verificar que el parser reporta `columnaEscritura: 5`.
   - Ejecutar la escritura física y confirmar que el valor se escribe exactamente en la Columna 5 (manteniendo el borde inferior).

2. **Verificación Integrada**:
   - Ejecutar la prueba completa en `app1.py` con formularios que contengan párrafos inline.
