# ADR-0009: Commercial Contact Section Detection, Grids Safe Passivity and Deterministic HSP Remapping

## Status
Aprobado (Consensuado vía `/grill-with-docs`)

## Contexto
En los formularios corporativos oficiales y formatos de vinculación en Colombia (e.g., SAGRILAFT, compras, proveedores), existen bloques específicos dedicados a capturar la información del contacto comercial o asesor que gestiona la cuenta (`OperadorActivo`: `responsable_nombre`, `responsable_cargo`, `responsable_telefono`, `responsable_correo`, `responsable_cedula`).

Anteriormente:
1. Bajo **ADR-0004**, cualquier sección cuyo título contuviera `"contacto comercial"` o `"referencias comerciales"` era clasificada en `core/spatial_ir.py` como `PertinenciaSeccion.OMITIR_TERCEROS`, abortando su procesamiento en `stage_3_llm_mapper` y `semantic_validator`.
2. Como consecuencia, las casillas de contacto comercial quedaban vacías o, si se enviaban al LLM sin aislamiento de sección, existía el riesgo crítico de que el LLM asignara los datos del **Representante Legal** (`representante_legal`, `cedula`, `correo`) o los teléfonos institucionales de la empresa (`empresa.telefono`) en casillas comerciales, violando la integridad jurídica.
3. Además, coexisten secciones tituladas `"Referencias Comerciales"`, las cuales en Colombia constituyen grillas de 2 a 3 empresas externas (clientes o proveedores) para validación crediticia. Inyectar al asesor comercial en dichas grillas corrompería la información de terceros.

## Decisiones de Diseño

### 1. Nueva Pertinencia en Spatial IR: `PertinenciaSeccion.CONTACTO_COMERCIAL`
Se introduce una categoría formal en el Intermediate Representation (`core/spatial_ir.py`):
```python
class PertinenciaSeccion(str, Enum):
    PROCESAR = "PROCESAR"
    OMITIR_TERCEROS = "OMITIR_TERCEROS"
    OMITIR_USO_INTERNO = "OMITIR_USO_INTERNO"
    OMITIR_LEGAL = "OMITIR_LEGAL"
    CONTACTO_COMERCIAL = "CONTACTO_COMERCIAL"
```
- Si la sección es `CONTACTO_COMERCIAL` y existe un `OperadorActivo` en sesión, la sección se procesa de forma activa restringiendo los candidatos semánticos exclusivamente al catálogo `responsable_*`.
- Si la sección es `CONTACTO_COMERCIAL` pero el usuario no ha configurado o seleccionado un operador (`⚪ Ninguno`), la sección se omite en `stage_3_llm_mapper` con 0 consumo de tokens de LLM (Safe Passivity).

### 2. Detección Estructural y Categórica: Contacto vs. Grilla de Referencias
Se adopta la regla de doble filtro:
- **Catálogo de Contacto (`TOKENS_CONTACTO_COMERCIAL`)**:
  `{"contacto", "personal de contacto", "informacion de contacto", "información de contacto", "datos de contacto", "contacto comercial", "asesor comercial", "asesor", "responsable del diligenciamiento", "diligenciado por", "funcionario que diligencia", "ejecutivo de cuenta", "atencion comercial", "atención comercial", "contacto de verificación"}`.
- **Catálogo de Referencias Externas (`TOKENS_REFERENCIAS_EXCLUIDAS`)**:
  `{"referencias comerciales", "referencia comercial", "referencias de clientes"}` -> Se clasifican directamente como `OMITIR_TERCEROS` (Safe Passivity) para no inyectar al asesor en casillas de terceros.
- **Caso Mixto / Ambiguo ("Contacto y Referencias")**: Se evalúa estructuralmente si la sección contiene filas repetitivas con encabezados como `"razón social"` o `"empresa"`; de ser así, se clasifica como `OMITIR_TERCEROS`, de lo contrario como `CONTACTO_COMERCIAL`.

### 3. Resolución Incondicional de Rótulos Bare (`BARE_LABELS_CONTACTO_COMERCIAL`)
Dentro de una sección clasificada como `CONTACTO_COMERCIAL`, los rótulos ambiguos o genéricos (*Nombre, Cargo, Teléfono, Celular, Correo, Cédula*) se resuelven **100% de manera determinista hacia el asesor comercial**:
```python
BARE_LABELS_CONTACTO_COMERCIAL = {
    "nombre": "responsable_nombre",
    "nombre completo": "responsable_nombre",
    "cargo": "responsable_cargo",
    "telefono": "responsable_telefono",
    "teléfono": "responsable_telefono",
    "celular": "responsable_telefono",
    "correo": "responsable_correo",
    "correo electronico": "responsable_correo",
    "correo electrónico": "responsable_correo",
    "email": "responsable_correo",
    "cedula": "responsable_cedula",
    "cédula": "responsable_cedula",
    "identificacion": "responsable_cedula",
    "identificación": "responsable_cedula",
}
```
**Regla de Oro**: Ningún rótulo `Nombre` dentro de un bloque `CONTACTO_COMERCIAL` puede asignarse a `razon_social` o `representante_legal`. Ningún rótulo `Correo` puede asignarse a `empresa.correo` o `representante_legal.correo`.

### 4. Re-mapeo Determinista en el Validador Semántico (HSP)
En `core/semantic_validator.py`, si el LLM Mapper propone un campo del dominio de Representante Legal o de Empresa general dentro de una sección `CONTACTO_COMERCIAL`:
- Se aplica auto-corrección determinista inmediata hacia su contraparte `responsable_*` si hay un `OperadorActivo`.
- Si no hay `OperadorActivo`, el campo se marca incondicionalmente como `""` (`DESCARTADO`).
- Todo campo propuesto que no pertenezca a `CAMPOS_RESPONSABLE_COMERCIAL` dentro de este bloque es descartado.

## Consecuencias
- **Positivas**: 
  - 100% de cobertura determinista en bloques de contacto comercial sin importar si los rótulos son bare (`Nombre`, `Teléfono`, `Correo`).
  - Protección absoluta del Representante Legal (cero contaminación cruzada).
  - Protección de tablas de referencias comerciales de clientes externos (se preservan limpias para diligenciamiento manual o futuro catálogo de referencias).
  - Cero costo de tokens de LLM cuando el usuario no selecciona un operador comercial.
- **Compromisos**:
  - Las tablas de "Referencias Comerciales" de clientes externos no se diligencian automáticamente con el asesor (requiere a futuro un almacén de referencias de clientes si se desea automatizar).
