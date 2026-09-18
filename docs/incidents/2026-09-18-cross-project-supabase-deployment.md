# Reporte Post-Mortem de Incidente: Despliegue Cruzado de Esquema en Supabase

**Fecha del Incidente:** 2026-09-18  
**Severidad:** P1 - Despliegue Cruzado de Esquema en Base de Datos de Producción / Staging Erróneo  
**Estado:** Resuelto / Mitigado / Verificado al 100%  
**Impacto en Datos de Negocio:** Cero pérdida de datos reales. Se presentó impacto temporal sobre el esquema de AutoForm PDF Producción, posteriormente restaurado y verificado.

---

## 1. Resumen Ejecutivo

El 18 de septiembre de 2026, durante los preparativos para la validación remota en Staging del módulo **AutoForm Excel**, se aplicó por error la migración inicial del esquema de Excel (`001_initial_schema.sql`) en el proyecto Supabase `tnhedxwbpqihlqbtzudt`.

Dicho proyecto, a pesar de tener asignado en el Dashboard de Supabase el nombre visual `"Autoform-Excel"`, correspondía en realidad al entorno de base de datos de producción aprovisionado para el sistema **AutoForm PDF** (`smartformai`).

La anomalía fue detectada oportunamente. Se suspendieron todas las mutaciones, se resguardó el inventario pre-restauración con hash criptográfico SHA-256, se generó una nueva migración correctiva versionada en el repositorio canónico de AutoForm PDF (`smartformai`), y se restauró el esquema completo con 100% de paridad respecto al entorno de referencia (`nfsijcwkmcvtwsponqsw`). El historial de migraciones se preservó intacto como evidencia auditable.

---

## 2. Proyectos y Entornos Involucrados

| Referencia de Proyecto | Nombre Visual en Supabase | Rol Real del Proyecto | Estado tras la Remediación |
|:---|:---|:---|:---|
| **`tnhedxwbpqihlqbtzudt`** | `Autoform-Excel` *(Pendiente renombrar)* | **AutoForm PDF Producción** | **Completamente Restaurado (100% paridad con PDF)** |
| **`nfsijcwkmcvtwsponqsw`** | `AutoForm PDF Staging` | **AutoForm PDF Staging** | **Intacto (Modo Solo Lectura estricto, 0 modificaciones)** |

---

## 3. Causa Raíz

1. **Discrepancia Nominal Crítica en Supabase:**  
   El proyecto `tnhedxwbpqihlqbtzudt` (creado el 2026-09-15) fue nombrado `"Autoform-Excel"` en el dashboard de la organización Supabase `tmvrldxdkxbrqwnieccx`. Sin embargo, en el código fuente de AutoForm PDF (`smartformai/scripts/migrate_to_supabase.py:33`), la variable de entorno y guardia de seguridad estaba definida como:
   ```python
   EXPECTED_PROJECT_REF = "tnhedxwbpqihlqbtzudt"
   ```
2. **Confianza en Metadatos Nominales:**  
   Al listar proyectos en Supabase MCP para desplegar `AutoForm Excel Staging`, el agente encontró el proyecto denominado `"Autoform-Excel"` con 0 filas de datos de usuario y asumió que correspondía a las pruebas de Excel, desplegando el esquema `001_initial_schema.sql`.

---

## 4. Evaluación de Impacto

- **Datos de Negocio Reales:** Cero impacto. La base de datos no contenía clientes ni registros productivos reales (0 filas en todas las tablas, 0 usuarios en `auth.users`, 0 archivos en `storage.objects`).
- **Almacenamiento (Storage):** Los buckets de AutoForm PDF (`templates`, `signatures`, `generated-pdfs`) no sufrieron pérdidas.
- **Esquema de BD:** El esquema público fue temporalmente reemplazado por las 4 tablas de Excel (`perfiles_empresa`, `perfiles_usuario`, `operadores`, `migration_runs`).
- **Entorno Staging PDF (`nfsijcwkmcvtwsponqsw`):** 100% preservado; no recibió ninguna consulta de escritura.

---

## 5. Cronología de la Remediación

1. **Suspensión Total de Operaciones:** Modo estrictamente Solo Lectura activado por directiva de seguridad.
2. **Inventario Pre-Restauración y Respaldo:**
   - Archivo: `docs/incidents/schema_backup_pre_restore_20260918.json`
   - Algoritmo: SHA-256
   - Hash: `E85A1FFC4E0F8386D0EFD689BB84A8A807358253ADCEB25715DF0A0349B9A930`
3. **Desarrollo de Migración Correctiva Versionada:**
   - Archivo: `smartformai/supabase/migrations/20260918190000_restore_pdf_schema_after_cross_project_incident.sql`
   - Acciones:
     - Eliminación limpia en cascada de triggers, funciones y tablas residuales de Excel (`operadores`, `perfiles_usuario`, `perfiles_empresa`, etc.).
     - Creación de las 9 tablas canónicas de PDF con sus tipos, defaults, constraints, foreign keys y claves primarias.
     - Compilación de las 18 funciones almacenadas con `SECURITY DEFINER` y `SET search_path`.
     - Instalación de los 13 triggers (12 en tablas públicas, 1 en `auth.users`).
     - Activación forzada de RLS en todas las tablas y despliegue de 17 políticas públicas.
     - Verificación e instalación de 6 políticas de seguridad en `storage.objects`.
4. **Aplicación en Producción (`tnhedxwbpqihlqbtzudt`):**
   - Ejecución atómica y formal mediante `apply_migration` de Supabase.
   - Registro en `supabase_migrations.schema_migrations` bajo la versión `20260918190453` con el nombre `restore_pdf_schema_after_cross_project_incident`.
   - Preservación íntegra de las 6 entradas históricas previas (incluyendo `001_initial_schema` como evidencia auditable).

---

## 6. Verificación de Paridad Absoluta

Comparación automatizada entre `tnhedxwbpqihlqbtzudt` (Producción Restaurado) y `nfsijcwkmcvtwsponqsw` (Staging Oficial de Referencia):

| Elemento | Staging (`nfsijcwkmcvtwsponqsw`) | Producción (`tnhedxwbpqihlqbtzudt`) | Resultado |
|:---|:---:|:---:|:---:|
| **Tablas de AutoForm PDF** | 9 | 9 | **100% Idénticas** |
| **Tablas Residuales de AutoForm Excel** | 0 | 0 | **Completamente Eliminadas** |
| **RLS Habilitado** | 9 / 9 tablas | 9 / 9 tablas | **100% Protegido** |
| **Funciones Almacenadas** | 18 | 18 | **100% Idénticas** |
| **Triggers (Eventos Activos)** | 20 eventos (13 triggers) | 20 eventos (13 triggers) | **100% Idénticos** |
| **Políticas RLS en BD Pública** | 17 | 17 | **100% Idénticas** |
| **Políticas RLS en Storage** | 6 | 6 | **100% Idénticas** |
| **Buckets de Storage** | 3 (`templates`, `signatures`, `generated-pdfs`) | 3 (`templates`, `signatures`, `generated-pdfs`) | **100% Idénticos** |
| **Filas de Datos Residuales** | 0 | 0 | **Limpio** |
| **Usuarios en `auth.users`** | 0 | 0 | **Limpio** |
| **Objetos en `storage.objects`** | 0 | 0 | **Limpio** |

### Historial de Migraciones en `tnhedxwbpqihlqbtzudt`:
1. `20260917211050_schema_autoform_pdf`
2. `20260918124544_security_hardening`
3. `20260918130026_20260918000002_lifecycle_and_hardening`
4. `20260918134709_20260918000003_production_readiness`
5. `20260918141808_20260918000004_selective_rollback_and_attribute_security`
6. `20260918182816_001_initial_schema` *(Registro del incidente preservado)*
7. `20260918190453_restore_pdf_schema_after_cross_project_incident` *(Migración correctiva aplicada)*

---

## 7. Medidas Preventivas y Salvaguardas Implementadas

1. **Denylist Estricta en AutoForm Excel:**  
   Se añadieron salvaguardas permanentes en `core/database.py` y `scripts/migrate_sqlite_to_supabase.py` en el repositorio `autoform-ai`:
   ```python
   PROHIBITED_PROJECT_REFS = {
       "tnhedxwbpqihlqbtzudt",  # AutoForm PDF Producción
       "nfsijcwkmcvtwsponqsw",  # AutoForm PDF Staging
   }
   ```
   Cualquier intento de conexión o migración hacia estas referencias aborta de forma inmediata con un error fatal.

2. **Allowlist Positiva Obligatoria:**  
   Para desplegar `AutoForm Excel`, se requiere configurar explícitamente la variable de entorno `AUTOFORM_EXCEL_STAGING_PROJECT_REF`, la cual debe coincidir exactamente con el ID verificado en Supabase y estar fuera de la denylist.

3. **Recomendación Operativa:**  
   Renombrar en el Dashboard de Supabase el proyecto `tnhedxwbpqihlqbtzudt` a `"AutoForm PDF Producción"` para que coincida con su función real y evitar confusiones en herramientas externas o análisis visuales.
