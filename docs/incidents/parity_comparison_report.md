# Reporte de Comparación Normalizada de Paridad: PDF Producción vs PDF Staging
- **Producción**: `tnhedxwbpqihlqbtzudt`
- **Staging**: `nfsijcwkmcvtwsponqsw`

## 1. Categoría: COLUMNS
- Total en Producción: 115
- Total en Staging:    115
✅ **Paridad 100% Exacta** en tablas, columnas, tipos, nullability y defaults.

## 1. Categoría: CONSTRAINTS
- Total en Producción: 40
- Total en Staging:    40
✅ **Paridad 100% Exacta** en PK, FK, UNIQUE y CHECK constraints.

## 1. Categoría: INDEXES
- Total en Producción: 32
- Total en Staging:    32
✅ **Paridad 100% Exacta** en todos los índices y definiciones.

## 1. Categoría: FUNCTIONS
- Total en Producción: 18
- Total en Staging:    18
✅ **Paridad 100% Exacta** en las 18 funciones mediante `pg_get_functiondef()`.

## 1. Categoría: TRIGGERS
- Total en Producción: 13
- Total en Staging:    13
✅ **Paridad 100% Exacta** en todos los triggers mediante `pg_get_triggerdef()`.

## 1. Categoría: POLICIES
- Total en Producción: 23
- Total en Staging:    23
✅ **Paridad 100% Exacta** en políticas RLS (incluyendo `qual` y `with_check` en public y storage.objects).

## 1. Categoría: GRANTS
- Total en Producción: 189
- Total en Staging:    101
❌ **Diferencias en grants:**
  - Solo en Prod: ('anon', 'companies', 'DELETE')
  - Solo en Prod: ('anon', 'companies', 'INSERT')
  - Solo en Prod: ('anon', 'companies', 'REFERENCES')
  - Solo en Prod: ('anon', 'companies', 'SELECT')
  - Solo en Prod: ('anon', 'companies', 'TRIGGER')
  - Solo en Prod: ('anon', 'companies', 'TRUNCATE')
  - Solo en Prod: ('anon', 'companies', 'UPDATE')
  - Solo en Prod: ('anon', 'company_bank_accounts', 'DELETE')
  - Solo en Prod: ('anon', 'company_bank_accounts', 'INSERT')
  - Solo en Prod: ('anon', 'company_bank_accounts', 'REFERENCES')
  - Solo en Prod: ('anon', 'company_bank_accounts', 'SELECT')
  - Solo en Prod: ('anon', 'company_bank_accounts', 'TRIGGER')
  - Solo en Prod: ('anon', 'company_bank_accounts', 'TRUNCATE')
  - Solo en Prod: ('anon', 'company_bank_accounts', 'UPDATE')
  - Solo en Prod: ('anon', 'form_fill_history', 'DELETE')
  - Solo en Prod: ('anon', 'form_fill_history', 'INSERT')
  - Solo en Prod: ('anon', 'form_fill_history', 'REFERENCES')
  - Solo en Prod: ('anon', 'form_fill_history', 'SELECT')
  - Solo en Prod: ('anon', 'form_fill_history', 'TRIGGER')
  - Solo en Prod: ('anon', 'form_fill_history', 'TRUNCATE')
  - Solo en Prod: ('anon', 'form_fill_history', 'UPDATE')
  - Solo en Prod: ('anon', 'legal_representatives', 'DELETE')
  - Solo en Prod: ('anon', 'legal_representatives', 'INSERT')
  - Solo en Prod: ('anon', 'legal_representatives', 'REFERENCES')
  - Solo en Prod: ('anon', 'legal_representatives', 'SELECT')
  - Solo en Prod: ('anon', 'legal_representatives', 'TRIGGER')
  - Solo en Prod: ('anon', 'legal_representatives', 'TRUNCATE')
  - Solo en Prod: ('anon', 'legal_representatives', 'UPDATE')
  - Solo en Prod: ('anon', 'pdf_mappings', 'DELETE')
  - Solo en Prod: ('anon', 'pdf_mappings', 'INSERT')
  - Solo en Prod: ('anon', 'pdf_mappings', 'REFERENCES')
  - Solo en Prod: ('anon', 'pdf_mappings', 'SELECT')
  - Solo en Prod: ('anon', 'pdf_mappings', 'TRIGGER')
  - Solo en Prod: ('anon', 'pdf_mappings', 'TRUNCATE')
  - Solo en Prod: ('anon', 'pdf_mappings', 'UPDATE')
  - Solo en Prod: ('anon', 'pdf_template_versions', 'DELETE')
  - Solo en Prod: ('anon', 'pdf_template_versions', 'INSERT')
  - Solo en Prod: ('anon', 'pdf_template_versions', 'REFERENCES')
  - Solo en Prod: ('anon', 'pdf_template_versions', 'SELECT')
  - Solo en Prod: ('anon', 'pdf_template_versions', 'TRIGGER')
  - Solo en Prod: ('anon', 'pdf_template_versions', 'TRUNCATE')
  - Solo en Prod: ('anon', 'pdf_template_versions', 'UPDATE')
  - Solo en Prod: ('anon', 'pdf_templates', 'DELETE')
  - Solo en Prod: ('anon', 'pdf_templates', 'INSERT')
  - Solo en Prod: ('anon', 'pdf_templates', 'REFERENCES')
  - Solo en Prod: ('anon', 'pdf_templates', 'SELECT')
  - Solo en Prod: ('anon', 'pdf_templates', 'TRIGGER')
  - Solo en Prod: ('anon', 'pdf_templates', 'TRUNCATE')
  - Solo en Prod: ('anon', 'pdf_templates', 'UPDATE')
  - Solo en Prod: ('anon', 'profiles', 'DELETE')
  - Solo en Prod: ('anon', 'profiles', 'INSERT')
  - Solo en Prod: ('anon', 'profiles', 'REFERENCES')
  - Solo en Prod: ('anon', 'profiles', 'SELECT')
  - Solo en Prod: ('anon', 'profiles', 'TRIGGER')
  - Solo en Prod: ('anon', 'profiles', 'TRUNCATE')
  - Solo en Prod: ('anon', 'profiles', 'UPDATE')
  - Solo en Prod: ('authenticated', 'companies', 'DELETE')
  - Solo en Prod: ('authenticated', 'companies', 'INSERT')
  - Solo en Prod: ('authenticated', 'companies', 'REFERENCES')
  - Solo en Prod: ('authenticated', 'companies', 'TRIGGER')
  - Solo en Prod: ('authenticated', 'companies', 'TRUNCATE')
  - Solo en Prod: ('authenticated', 'company_bank_accounts', 'REFERENCES')
  - Solo en Prod: ('authenticated', 'company_bank_accounts', 'TRIGGER')
  - Solo en Prod: ('authenticated', 'company_bank_accounts', 'TRUNCATE')
  - Solo en Prod: ('authenticated', 'form_fill_history', 'DELETE')
  - Solo en Prod: ('authenticated', 'form_fill_history', 'REFERENCES')
  - Solo en Prod: ('authenticated', 'form_fill_history', 'TRIGGER')
  - Solo en Prod: ('authenticated', 'form_fill_history', 'TRUNCATE')
  - Solo en Prod: ('authenticated', 'form_fill_history', 'UPDATE')
  - Solo en Prod: ('authenticated', 'legal_representatives', 'REFERENCES')
  - Solo en Prod: ('authenticated', 'legal_representatives', 'TRIGGER')
  - Solo en Prod: ('authenticated', 'legal_representatives', 'TRUNCATE')
  - Solo en Prod: ('authenticated', 'pdf_mappings', 'REFERENCES')
  - Solo en Prod: ('authenticated', 'pdf_mappings', 'TRIGGER')
  - Solo en Prod: ('authenticated', 'pdf_mappings', 'TRUNCATE')
  - Solo en Prod: ('authenticated', 'pdf_template_versions', 'DELETE')
  - Solo en Prod: ('authenticated', 'pdf_template_versions', 'REFERENCES')
  - Solo en Prod: ('authenticated', 'pdf_template_versions', 'TRIGGER')
  - Solo en Prod: ('authenticated', 'pdf_template_versions', 'TRUNCATE')
  - Solo en Prod: ('authenticated', 'pdf_template_versions', 'UPDATE')
  - Solo en Prod: ('authenticated', 'pdf_templates', 'REFERENCES')
  - Solo en Prod: ('authenticated', 'pdf_templates', 'TRIGGER')
  - Solo en Prod: ('authenticated', 'pdf_templates', 'TRUNCATE')
  - Solo en Prod: ('authenticated', 'profiles', 'DELETE')
  - Solo en Prod: ('authenticated', 'profiles', 'INSERT')
  - Solo en Prod: ('authenticated', 'profiles', 'REFERENCES')
  - Solo en Prod: ('authenticated', 'profiles', 'TRIGGER')
  - Solo en Prod: ('authenticated', 'profiles', 'TRUNCATE')

## Conclusión de Paridad
⚠️ Se encontraron discrepancias entre los entornos.