# ADR 0005: Cell Reservation, Section Uniqueness & PEP/Beneficiario Final Isolation

## Context
Analysis of corporate supplier registration forms (e.g. `SC-COM-02-25` / `FORMATO VINCULACION`) revealed two critical issues:
1. **Cell Collision & Redundant Multi-Mapping**:
   - Multiple labels within the same section (e.g. `Tipo de Identificación: NIT`, `No. de identificación: ______`) were mapped to the same profile key (`nit`), resulting in duplicated writes.
   - Worse, multiple mapping directives targeted the exact same physical destination cell (e.g. `R17C3` targeted by both `nit` and `direccion`), causing `SKIP: Celda no escribible o ya contiene contenido` and visual disorder.
2. **SAGRILAFT / SARLAFT PEP & Beneficiario Final Pollution**:
   - Compliance forms contain dedicated sections asking questions such as:
     - *"¿Es usted una PEP Nacional, Extranjero o de Organizaciones Internacionales?"*
     - *"7. IDENTIFICACIÓN DEL BENEFICIARIO FINAL Y PEP'S"*
   - Inside these sections, table columns and labels prompt for:
     - `Nombre Completo`
     - `Tipo de Identificación`
     - `Número de Identificación`
     - `País de Domicilio`
   - Secondary sweep algorithms and vector matchers mistakenly mapped the company's `representante_legal`, `nit`, or `razon_social` into these PEP / Beneficiario Final fields.
   - Auto-filling or auto-answering "NO" in PEP declarations poses compliance and legal liabilities during audit.

## Decisions

### 1. Unique Physical Cell Reservation (`celdas_ocupadas`)
- In `core/excel_writer.py`, an in-memory registry of reserved target cells (`celdas_ocupadas: Set[Tuple[str, int, int]]`) is maintained during workbook rendering.
- Before writing to any coordinate `(sheet, row, col)`:
  - If the coordinate is already in `celdas_ocupadas`, the write operation is skipped immediately with status `SKIP` and log message:
    `[AutoForm Writer] CELL_ALREADY_RESERVED: Celda (R{fila}C{col}) ya fue reservada por una directiva anterior. SKIP.`
  - If available, the cell is written and permanently registered in `celdas_ocupadas`.

### 2. Section Field Uniqueness (`asignados_por_seccion`)
- In `core/semantic_validator.py` and `pipeline/stages/stage_3_llm_mapper.py`, a single section can only receive **one assignment per canonical profile key** (`nit`, `razon_social`, `direccion`, `representante_legal`, `cedula`).
- If an additional label in the same section attempts to bind to an already assigned key, it is marked as `DESCARTADO` with reason:
  `"Unicidad de Sección (ADR-0005): El campo '{campo}' ya fue asignado previamente en la sección '{seccion}'."`

### 3. Strict PEP & Beneficiario Final Isolation (Safe Passivity)
- A dedicated trigger blacklist is added to `core/domain_constants.py`:
  ```python
  TOKENS_PEP_BENEFICIARIOS_SECCION = {
      "pep", "peps", "persona expuesta", "politicamente expuesta", "politicamente expuesto",
      "beneficiario final", "beneficiarios finales", "beneficiario real", "beneficiarios reales"
  }
  ```
- **Early Stage 2 Pruning**: Any element inside a section matching these triggers, or with a label matching PEP/Beneficiario Final patterns, is classified as `ClasificacionElemento.NO_APLICA`.
- **Semantic Validator & LLM Mapper Hard Gate**: Any mapping directive inside a PEP or Beneficiario Final section is discarded (`DESCARTADO`) unconditionally. No company, legal representative, or banking data may enter these sections.
- **Closed Questions (SI / NO)**: PEP checkboxes remain completely empty / unchecked (`Safe Passivity`), leaving declaration to human compliance officers.

## Consequences
- **Positive**: Zero cell collisions (`SKIP: Celda no escribible` caused by multiple directives targeting the same cell is eliminated).
- **Positive**: Clean non-redundant forms where `nit` is filled once on its dedicated line rather than duplicated.
- **Positive**: Strict regulatory compliance with Colombian SAGRILAFT/SARLAFT standards, avoiding false statements on politically exposed persons.
