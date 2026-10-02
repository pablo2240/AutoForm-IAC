# ADR-0011 – Aislamiento de Identidades por Rol, Zona PEP Negativa y Datos Societarios

**Estado:** Aprobado  
**Fecha:** 2026-10-02  
**Contexto:** Pipeline de llenado automático de formularios Excel (AutoForm AI)  
**Relacionado con:** Issues Q1, Q2, Q4 – detectados al probar FMCA07J, 01 SC-COM-02-25 y GE.F.021_5.5

---

## Contexto

Al ejecutar el pipeline sobre tres formularios de clientes/proveedores se detectaron cuatro categorías de errores:

| ID | Síntoma observado |
|----|-------------------|
| Q1 | El contacto comercial (Antonio Prieto) aparecía en secciones de representante legal y firma |
| Q2 | Cuando PEP = NO, los sub-campos positivos del PEP se llenaban con datos del perfil |
| Q4 | Encabezados cortos como `SUCURSAL`, `ÁREA`, `IDENTIFICACIÓN` se descontextualizaban de su sección padre |
| Q5 | La sección de composición accionaria/beneficiarios finales se dejaba en blanco porque el modelo de datos no tenía entrada explícita de accionistas |

---

## Decisión

### 1. Aislamiento estricto de identidades por rol

Los campos del **contacto comercial** (`responsable_nombre`, `responsable_cargo`, `responsable_correo`, `responsable_celular`, `responsable_area`) **nunca pueden asignarse** a ítems cuya sección sea:
- Representante legal
- Firma / declaración
- Societario / junta directiva / beneficiarios finales
- Bloque PEP

La barrera se implementó en:
- `core/semantic_validator.py` → función `_aplicar_regla_aislamiento_roles()`
- `pipeline/stages/stage_3_llm_mapper.py` → guardia post-LLM antes de insertar el item

### 2. Zona PEP condicional negativa

Cuando la respuesta PEP es explícitamente **"NO"**, todos los sub-campos de la sub-sección *"En caso de que su respuesta haya sido positiva…"* se marcan como `OMITIR_LEGAL` en la representación intermedia (IR).

El mecanismo es **estructural, no interpretativo**:
- `core/spatial_ir.py` detecta el patrón `PATRON_PEP_CONDICIONAL_POSITIVO` y marca la sección con `pertinencia = OMITIR_LEGAL`.
- `core/semantic_validator.py` descarta automáticamente cualquier ítem bajo esa pertinencia sin delegarlo al LLM.

Si la respuesta PEP **no está definida**, el campo se marca `REVISION` (nunca se inventa "NO").

### 3. Encabezados con contexto de sección padre

Los encabezados cortos (`IDENTIFICACIÓN`, `NOMBRE`, `DIRECCIÓN`, `SUCURSAL`, `ÁREA`) tienen longitud ≤ 3 palabras. El IR aplica la siguiente lógica:

- Si el encabezado tiene ≤ 3 tokens Y está en una fila sin celdas de escritura adyacentes → se clasifica como **encabezado de columna**, hereda la pertinencia de la sección padre.
- `SUCURSAL` **no** se añade a `_PATRON_OPCIONES` (lista de checkboxes) para evitar que se descarte como opción de selección.
- `ÁREA` se añade explícitamente a los tokens de atributos del contacto comercial en `validar_plan_mapeo`.
- La condición de contigüidad comercial se amplió a `0 ≤ (f - fc) ≤ 2` para capturar encabezados en la misma fila que la etiqueta de contacto (`f == fc`).

### 4. Modelo explícito de accionistas y beneficiarios finales

`config/datos_empresa.json` incorpora la clave `societario`:

```json
"societario": {
  "accionistas": [
    {
      "nombre": "Guillermo Humberto Cañón Sarria",
      "tipo_identificacion": "C.C",
      "identificacion": "98555384",
      "porcentaje_participacion": 100
    }
  ],
  "beneficiarios_finales": [...]
}
```

`core/profile_manager.py → aplanar_perfil()` extrae el primer accionista y el primer beneficiario final como claves planas (`accionista_nombre`, `accionista_tipo_id`, `accionista_identificacion`, `accionista_porcentaje`). Solo se llenan estas secciones cuando los datos provienen de este perfil validado.

### 5. Preservación de `rotulo_original`

En `pipeline/stages/stage_3_llm_mapper.py`, antes de asignar `item["valor"]` con el valor del perfil, se guarda `item["rotulo_original"] = item.get("rotulo") or item.get("valor")`. Esto garantiza que en el segundo pase de validación (`validar_item_mapeo`) el rótulo no se confunda con el valor inyectado.

---

## Consecuencias

### Positivas
- Separación nítida entre los cuatro roles: empresa, representante legal, contacto comercial y societario.
- Los formularios legales ya no contaminan datos del contacto comercial.
- El campo `SUCURSAL` bancaria se llena correctamente sin ser tratado como checkbox.
- El campo `ÁREA` del contacto comercial se llena en tablas con encabezados en la misma fila.
- La sección de accionistas/beneficiarios finales se llena desde el perfil societario explícito.

### Limitaciones conocidas
- Si una celda de porcentaje accionario ya contiene un valor pre-existente en el template (p. ej. `1`), el writer la omite por la política de no-sobreescritura. Necesita revisión humana.
- Los encabezados compuestos (`Identificación / TIPO ID` en una sola celda fusionada) solo se pueden mapear a un campo; el pipeline elige `tipo_id` (valor más discriminante) sobre el número de identificación.
- Sólo se soporta el primer accionista y el primer beneficiario final de las listas.

---

## Archivos modificados

| Archivo | Cambio principal |
|---------|-----------------|
| `config/datos_empresa.json` | Añadido `societario` con accionistas y beneficiarios |
| `core/profile_manager.py` | `aplanar_perfil()` extrae claves societarias planas |
| `core/domain_constants.py` | Separados `TOKENS_PEP_SECCION` / `TOKENS_SOCIETARIO_SECCION`; aliases societarios |
| `core/spatial_ir.py` | Guard longitud ≤ 3; `OMITIR_LEGAL` para PEP condicional positivo; `sucursal` fuera de opciones |
| `core/coverage_engine.py` | Sweeps `responsable_area` y `accionista_*`; `PAT_SECCION_JUNTA_COMP` |
| `core/semantic_validator.py` | `aplanar_perfil` delegado; `rotulo_original` preservado; barrera de roles |
| `pipeline/stages/stage_2_classifier.py` | Guard longitud ≤ 3 en `es_titulo_seccion` |
| `pipeline/stages/stage_3_llm_mapper.py` | `rotulo_original` guardado antes de sobreescribir `valor`; barrera societario |

---

## Pruebas de regresión

`tests/test_three_examples_regression.py` cubre 16 afirmaciones sobre los tres formularios verificando cada uno de los puntos anteriores.
