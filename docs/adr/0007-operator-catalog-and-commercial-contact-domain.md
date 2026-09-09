# ADR 0007: Operator Catalog, Runtime Fusion & Commercial Contact Domain Isolation

## Context
Corporate vendor onboarding, client registration, and compliance forms (e.g. `01 SC-COM-02-25`, `GE.F.021_5.5`) frequently contain dedicated sections requesting the information of the person completing the document or managing the account:
- *"Información de Contacto Comercial"* (Commercial Contact)
- *"Asesor de Cuenta / Ejecutivo"* (Account Executive)
- *"Persona Responsable del Diligenciamiento"* (Form Diligence Responsible)
- *"Contacto de Verificación"* (Verification Contact)
- *"Diligenciado por:"* (Completed by)

Under **ADR-0004**, AutoForm AI instituted an unconditional *Safe Passivity* rule (`PATRON_CONTACTO_COMERCIAL` -> `NO_APLICA` / `DESCARTADO`), discarding these fields so they remained blank. This was necessary because the system only possessed enterprise data (`IAC Latam`) and the Legal Representative's personal data (`Guillermo Humberto Cañón Sarria`). Allowing commercial fields to map was causing the Legal Representative's identity to contaminate sales and operational slots.

However, IAC Latam employs multiple sales executives and administrators (e.g., Antonio Prieto, technical sales engineers) who regularly complete these forms. Forcing manual entry of the commercial contact on every single form introduces friction and defeats full automation.

Three architectural challenges arose:
1. **Dynamic Personas vs. Static Enterprise**: Enterprise identity and legal representation are static and institutional. The human operator completing the form is dynamic and variable across teams.
2. **Avoiding Parallel Pipeline Overhead**: Introducing a separate data pipeline specifically for operators would require refactoring all stages (`Spatial IR`, `Classifier`, `LLM Mapper`, `Coverage Engine`, and `Excel Writer`).
3. **Legal Integrity & Zero Cross-Contamination**: Commercial sales agents must never sign as Legal Representatives, sit on the Board of Directors, or certify PEP/SAGRILAFT affidavits.

---

## Decisions

### 1. Dedicated SQLite Operator Catalog (`operadores`)
In `config/empresa.db`, an independent canonical table is established:
```sql
CREATE TABLE IF NOT EXISTS operadores (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    cargo TEXT,
    cedula TEXT,
    telefono TEXT,
    correo TEXT,
    es_activo INTEGER DEFAULT 0,
    actualizado_en TEXT NOT NULL
);
```
- A default initial seed is created for production: `"antonio_prieto"`, with name `"Antonio Prieto"`, role `"Asesor Comercial / Aplicaciones"`, and email `"antonio.prieto@iac.com.co"`.

### 2. Canonical Quintet of Operator Fields
The system establishes 5 standard canonical keys for the operator domain:
1. `responsable_nombre` (Full name of diligence operator / commercial agent)
2. `responsable_cargo` (Job title / position)
3. `responsable_cedula` (National ID / Document number)
4. `responsable_telefono` / `responsable_celular` (Direct phone / mobile contact)
5. `responsable_correo` (Direct corporate email)

### 3. Non-Invasive Runtime Fusion into `datos_empresa`
Instead of creating a secondary `ctx.datos_operador` channel, the active operator's fields are merged directly into the `datos_empresa` payload at runtime in `app1.py`:
- In the hierarchical taxonomy for the LLM (`taxonomia_d`):
  ```json
  "responsable": {
    "nombre": "Antonio Prieto",
    "cargo": "Asesor Comercial / Aplicaciones",
    "cedula": "",
    "telefono": "",
    "correo": "antonio.prieto@iac.com.co"
  }
  ```
- In the flat dictionary for the Validator, Coverage Engine, and Writer:
  `responsable_nombre`, `responsable_cargo`, `responsable_cedula`, `responsable_telefono`, `responsable_correo`.
This reuses 100% of existing pipeline stages without breaking contracts.

### 4. Conditional Mapping with Safe Passivity as Fallback
- If the active operator contains non-empty values, commercial and diligence sections are **actively mapped** and physically injected into the form.
- If no operator is active or the fields are blank, the engine falls back to **Safe Passivity** (`DESCARTADO`), leaving cells blank for manual completion.
- Under NO circumstance are the Legal Representative's credentials injected into commercial slots.

### 5. Strict Domain Isolation & Context-First Disambiguation
- **Permitted Targets for `RESPONSABLE_COMERCIAL`**:
  `"contacto comercial"`, `"asesor"`, `"diligenciado por"`, `"persona responsable"`, `"contacto operativo"`, `"contacto de verificación"`, `"asesor de cuenta"`.
- **Strictly Prohibited Targets for `RESPONSABLE_COMERCIAL`**:
  `"representante legal"`, `"junta directiva"`, `"firma legal"`, `"declaración juramentada"`, `"certificación sagrilaft"`, `"órganos de administración"`, `"pep"`, `"beneficiarios finales"`.
- **Context-First Resolution of Ambiguous Labels (`EMAIL`, `TELÉFONO`, `NOMBRE`)**:
  - Section Enterprise / General -> `correo` / `telefono` (corporate PBX).
  - Section Legal Representative -> `correo` / `celular` of Representative.
  - Section Commercial / Verification / Diligence -> `responsable_correo` / `responsable_telefono` / `responsable_nombre`.

### 6. UI Ergonomics
- Top-level operator selector in `app1.py`: `👤 Diligenciado por: [ Antonio Prieto ▼ ]`.
- Dedicated `👤 Operadores` management tab within the Profile Settings modal to add, edit, or remove operators with immediate SQLite ACID persistence.

---

## Consequences

### Positive
- **Full Automation of Commercial Sections**: Corporate compliance forms with commercial contact blocks (e.g. R11 in `GE.F.021` or Section 3 in `SC-COM`) are now completed automatically.
- **Multi-User Scalability**: Any team member (sales engineers, administrative staff) can select or register their profile in seconds.
- **Architectural Preservation**: Zero modifications required to the core OpenXML physical writer or AST pipeline structures; everything operates via taxonomy and domain expansion.
- **Legal Compliance Protected**: Absolute isolation guarantees that commercial agents never supplant legal signatories.

### Negative / Trade-offs
- An additional table (`operadores`) and migration check must run during database initialization in `core/database.py`.
- Form sections with ambiguous headers require precise contextual token matching to prevent confusing corporate email with sales agent email.