# ADR 0006: Financial Balance Fields, Raw Numeric Injection & Strict Financial Domain Isolation

## Context
Corporate vendor onboarding, client verification, and SAGRILAFT compliance forms (e.g. `SC-COM-02-25`, `FORMATO VINCULACION`) consistently require enterprise financial figures alongside banking details:
- **Total Activos** (Assets)
- **Total Pasivos** (Liabilities)
- **Total Patrimonio** (Equity)
- **Total Ingresos Mensuales** (Monthly Income)
- **Total Egresos Mensuales** (Monthly Expenses)
- *(Optional)* **Total Ingresos Anuales / Total Egresos Anuales** (Annual Statements)

Prior to this decision, the financial domain in `DatosEmpresa` was strictly limited to bank account credentials (`banco`, `sucursal`, `numero_cuenta`, `tipo_cuenta`). Integrating financial balance amounts required resolving three architectural risks:
1. **Formula Invalidation by Text Formatting**: Corporate Excel forms frequently contain arithmetic check formulas (e.g. `=Activos - Pasivos` or `=SUM(Ingresos)`). Injecting formatted text strings (such as `"$ 16.151.175.009"` or `"16.151.175.009"`) causes immediate `#¡VALOR!` runtime errors in Excel formulas.
2. **Domain Isolation & Cross-Domain Collisions**: Without distinct category isolation, semantic matchers or LLMs could confuse monetary figures with generic numeric labels (e.g. "Número", "Valor", "Monto") in commercial, operational, or legal sections.
3. **Periodicity Mismatches (Monthly vs. Annual)**: In commercial accounting, attempting to guess annual turnover by multiplying monthly figures by 12 (x 12) introduces untruthful financial declarations that conflict with official DIAN tax returns (*Declaración de Renta*).

---

## Decisions

### 1. `DatosEmpresa` Taxonomy: Hierarchical `financiero.balance` & Bidirectional Aliases
- In `config/datos_empresa.json` and SQLite (`config/empresa.db`), the financial domain is extended with the `balance` subgroup:
  `json
  "financiero": {
    "banco": {
      "banco": "BANCOLOMBIA",
      "sucursal": "Medellin"
    },
    "cuenta": {
      "numero_cuenta": "00300833888",
      "tipo_cuenta": "AHORROS"
    },
    "balance": {
      "total_activos": "16151175009",
      "total_pasivos": "8831977528",
      "total_patrimonio": "7319197482",
      "total_ingresos_mensuales": "1110748257",
      "total_egresos_mensuales": "975086377",
      "total_ingresos_anuales": "",
      "total_egresos_anuales": ""
    }
  }
  `
- In `core/profile_manager.py`, canonical keys (`total_activos`, `total_pasivos`, etc.) are enriched with bidirectional short aliases (`activos`, `pasivos`, `patrimonio`, `ingresos_mensuales`, `egresos_mensuales`, `ingresos_anuales`, `egresos_anuales`) upon flattening, guaranteeing zero-friction mapping whether forms prefix "Total" or not.

### 2. Raw Numeric Injection in Native OpenXML
- Financial figures are stored and written as clean numeric digits (`int`/`float`).
- In `core/excel_writer.py`, if a field belongs to `CAMPOS_FINANCIEROS_BALANCE`, the writer inyects the raw integer/float into `cell.value`.
- Excel's native cell style (Accounting `$ #,##0` or Number formatting) determines display appearance. Formulas computing balance equations operate seamlessly without `#¡VALOR!` errors.

### 3. Dedicated Category `CAMPOS_FINANCIEROS_BALANCE` & Strict Domain Isolation
- In `core/domain_constants.py`:
  `python
  CAMPOS_FINANCIEROS_BALANCE: Set[str] = {
      "total_activos", "total_pasivos", "total_patrimonio",
      "total_ingresos_mensuales", "total_egresos_mensuales",
      "total_ingresos_anuales", "total_egresos_anuales",
      "activos", "pasivos", "patrimonio",
      "ingresos_mensuales", "egresos_mensuales",
      "ingresos_anuales", "egresos_anuales",
  }

  TOKENS_BALANCE_SECCION: Set[str] = {
      "financier", "balance", "contab", "cifras",
      "econom", "económic", "estado de resultado", "situacion financiera"
  }
  `
- In `core/semantic_validator.py`, balance fields are permitted **ONLY** if both the section header and the cell label explicitly belong to the accounting/balance domain. If matched in a generic or commercial section, the directive is discarded (`DESCARTADO`).

### 4. Safe Passivity on Periodicity Disparities (Monthly vs. Annual)
- The pipeline strictly prohibits heuristic extrapolation (e.g. monthly x 12).
- If a form requests annual figures ("Ingresos Anuales", "Ventas Anuales del Último Ejercicio") and `total_ingresos_anuales` is empty in `DatosEmpresa`, the label is discarded (`DESCARTADO` / `Safe Passivity`) for manual entry by authorized financial personnel.

### 5. UI Ergonomics in `app1.py`
- In the `🏦 Financiero` sidebar tab, an ergonomic third block is introduced:
  `##### 📊 Balance y Cifras Financieras`
- Connected to real-time auto-saving (`on_change=_al_cambiar_campo`), ensuring immediate persistence to canonical SQLite and mirror JSON.

---

## Consequences
- **Positive**: Direct compatibility with arithmetic spreadsheet formulas (= Activos - Pasivos).
- **Positive**: Strict isolation prevents financial balance amounts from polluting general questionnaire numbers.
- **Positive**: Full compliance with Colombian accounting and tax standards by forbidding unverified annual extrapolations.