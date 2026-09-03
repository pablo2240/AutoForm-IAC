# ADR 0004: Domain Isolation, Underline Ray-Casting & Safe Passivity

## Context
Analysis of filled corporate forms (e.g. SAGRILAFT / SARLAFT supplier forms) revealed two critical failure modes:
1. **Spatial destruction**: Labels like `Dirección`, `Teléfono`, `Ciudad`, and `País` were injected into the label cell itself (`misma`), squishing label and value together and leaving the adjacent cells with underline (`______`) or merged ranges completely empty.
2. **Semantic pollution & hallucinations**: Secondary rescue algorithms (Diff Loop and Vector Matcher) force-fed unassigned profile keys into generic labels, causing *"Cliente"* to receive bank account numbers, *"Vinculación"* to receive personal emails, and *"Otros"* to receive account types (`AHORROS`). Additionally, company contacts (`contacto_comercial`) were colliding with and being overwritten by the legal representative (`representante_legal`).

## Decisions
1. **Underline Ray-Casting & Prohibition of `misma`**:
   - Writing into `misma` is strictly forbidden for standard form labels.
   - `misma` is only permissible if the label text itself contains an explicit inline fill pattern (e.g. `Nombre: _________`).
   - If the cell to the right has a bottom border (`bottom_border`) or belongs to a merged range, the value MUST always be written to the right, expanding across the full underline width.
   - The fallback in `excel_writer.py` that wrote into the label cell when right was perceived as occupied is completely removed.

2. **Strict Domain Isolation by Section**:
   - Access keys are strictly gated by section category:
     - **`datos_bancarios`** (`banco`, `numero_cuenta`, `tipo_cuenta`, `sucursal`): ONLY allowed in sections matching `banco`, `pago`, `referencia_bancaria`, `financiero`, `contabilidad`. Strictly forbidden in general identification or client sections.
     - **`representante_legal`** (`representante_legal`, `cedula`, `lugar_expedicion`): ONLY in `representante_legal`, `firmante`, `declaracion`, `legal`. Strictly forbidden in commercial contact sections.
     - **`empresa`** (`razon_social`, `nit`, `direccion`, `ciudad`, `departamento`, `pais`, `telefono`): In general identification and company info sections.
   - Cross-section assignment is prohibited regardless of lexical similarity scores.

3. **Safe Passivity (Descartar y Dejar Vacío para Contactos Comerciales y Opciones)**:
   - Los campos de contacto comercial o asesor (ej. *"Nombre del Contacto"*, *"Cargo"*, *"Asesor Comercial"*) deben ser **ignorados y dejados en blanco** (`DESCARTADO`), ya que cada ejecutivo comercial diligencia manualmente sus propios datos en el formulario.
   - Queda terminantemente prohibido inyectar los datos del Representante Legal (Guillermo) o de la empresa en los campos del contacto comercial.
   - Si un rótulo es una opción de selección (`OPTION`), checkbox o término genérico (`Vinculación`, `Otros`, `PEP`, `SI`, `NO`), se clasifica como `DESCARTADO` y queda en blanco para revisión humana.

4. **Entidades Oficiales Exclusivas**:
   - `DatosEmpresa` gestiona exclusivamente las entidades corporativas institucionales: `empresa` (datos generales y tributarios), `representante_legal` (firmante autorizado) y `financiero` (datos bancarios y contables). No se agregan comerciales al perfil institucional.

## Consequences
- **Positive**: Clean visual alignment matching corporate form standards (Image 2), with values centered on the underline lines.
- **Positive**: Zero cross-contamination between banking, legal, and operational contact domains.
- **Positive**: Strict compliance with Colombian compliance and compliance audit standards (SAGRILAFT/SARLAFT).
