# Manual de Operación, Mantenimiento y Soporte — DocumentForge

> **DocumentForge (AutoForm AI — IAC Latam)**  
> **Versión:** 1.0 (Staging / Pre-Producción)  
> **Clasificación:** Documentación Técnica Operativa  
> **Área Responsable:** Operaciones de TI, Soporte Técnico e Ingeniería de Software  

---

## 1. Descripción General del Sistema y Arquitectura

**DocumentForge** (conocido en el repositorio como **AutoForm AI / AutoForm Excel**) es una plataforma de alta precisión diseñada para automatizar el diligenciamiento de formularios corporativos complejos en formato Microsoft Excel (`.xlsx`, `.xlsm`, `.xls`), garantizando la preservación total de estilos visuales, fórmulas matemáticas, bordes, celdas combinadas y controles interactivos originales.

La solución resuelve la fricción operativa en procesos de vinculación de proveedores, clientes, formatos bancarios, entidades aseguradoras y registros tributarios corporativos.

```
+---------------------------------------------------------------------------------------------------+
|                                 ARQUITECTURA GENERAL DEL SISTEMA                                  |
+---------------------------------------------------------------------------------------------------+
                                                                                                     
 [ Usuario / Asesor ]                                                                                
          │                                                                                          
          ▼                                                                                          
 ┌────────────────────────────────────────────────────────┐                                          
 │ Gatekeeper & Capa Web (Streamlit: app1.py)            │                                          
 │ - Validación de dominios (@iaclatam.com, @iac.com.co)  │                                          
 │ - Control de sesión basada en JWT (Supabase Auth)      │                                          
 │ - Panel administrativo y verificación interactiva     │                                          
 └───────────────────────────┬────────────────────────────┘                                          
                             │                                                                       
                             ▼                                                                       
 ┌────────────────────────────────────────────────────────────────────────────────────────┐          
 │ PIPELINE DETERMINISTA DE DILIGENCIAMIENTO (PipelineOrchestrator)                       │          
 │                                                                                        │          
 │  [Stage 1: Parser]        ───► [Stage 2: Classifier & Spatial IR]                      │          
 │  core/excel_parser.py          core/spatial_ir.py                                      │          
 │  - Escaneo de celdas/bordes    - Segmentación por Secciones / Filas                    │          
 │  - Ray-casting a subrayado     - Clasificación (FIELD vs TITLE/OPTION)                 │          
 │                                - Safe Passivity (PEP y Beneficiarios)                  │          
 │                                                                                        │          
 │  [Stage 3: LLM Mapper]    ───► [Stage 4: Verifier UI]      ───► [Stage 5: Writer]      │          
 │  core/llm_client.py            ui/page_verify.py                core/excel_writer.py   │          
 │  - MacroLotes paralelos        - Revisión visual humana         - Escritura OpenXML    │          
 │  - Instructor + Pydantic V2    - Ajuste de confianza            - Reserva de celdas    │          
 │  - Validador Semántico/HSP     - Edición en caliente            - Preservación estilos │          
 │  - Caché difuso (RapidFuzz)                                     - Inyección numérica   │          
 └───────────────────────────┬────────────────────────────────────────────────────────────┘          
                             │                                                                       
                             ▼                                                                       
 ┌────────────────────────────────────────────────────────────────────────────────────────┐          
 │ CAPA DE DATOS Y SEGURIDAD                                                              │          
 │ - Supabase PostgreSQL: Fuente única de verdad (perfiles_empresa, perfiles_usuario)     │          
 │ - Row Level Security (RLS): Aislamiento criptográfico por token de usuario            │          
 │ - Auditoría Inmutable: public.auditoria_autenticacion (solo lectura para admin)        │          
 │ - SQLite Local: Fallback exclusivo para desarrollo offline (empresa.db)                │          
 └────────────────────────────────────────────────────────────────────────────────────────┘          
```

### 1.1 Fases del Pipeline Modular

1. **Stage 1 — Parser (`core/excel_parser.py`):**
   Inspecciona la hoja de cálculo celda por celda. Detecta coordenadas, colores de fondo, bordes inferiores (`bottom_border`), celdas combinadas (*merged ranges*) y direcciones de llenado candidatas.
2. **Stage 2 — Classifier & Spatial IR (`pipeline/stages/stage_2_classifier.py`, `core/spatial_ir.py`):**
   Construye la Representación Intermedia Espacial (`DocumentoIR`). Discrimina títulos de sección, textos informativos y campos de entrada. Aplica **Safe Passivity** (omisión segura de bloques PEP, opciones genéricas `SI/NO` y matrices de referencias comerciales de terceros para prevenir contaminación).
3. **Stage 3 — LLM Mapper & Semantic Cache (`pipeline/stages/stage_3_llm_mapper.py`, `core/llm_client.py`):**
   Agrupa campos en macro-lotes espaciales y consulta la API de OpenAI estructurada con `instructor` y validación Pydantic V2. Utiliza una memoria caché difusa (`core/semantic_cache.py`) basada en RapidFuzz para reutilizar plantillas idénticas a costo cero. Ejecuta el Validador Semántico determinista (`core/semantic_validator.py`) aplicando reglas de aislamiento de dominios (datos bancarios vs representante legal).
4. **Stage 4 — Verifier UI (`ui/page_verify.py`):**
   Interfaz reactiva donde el usuario puede previsualizar las asignaciones, editar valores o cambiar campos de mapeo antes de la escritura definitiva.
5. **Stage 5 — Safe Excel Writer (`core/excel_writer.py`):**
   Inyecta los valores en las celdas destino mediante serialización nativa OpenXML, manteniendo intactos formatos numéricos, fórmulas y controles de formulario sin recurrir a manipulación binaria cruda.

---

## 2. Tecnologías, Dependencias y Ejecución de Pruebas

### 2.1 Stack Tecnológico Implementado

| Componente | Tecnología | Versión | Propósito en el Sistema |
|---|---|---|---|
| **Lenguaje Base** | Python | `>= 3.10` | Lógica de negocio, orquestación y manipulación de datos. |
| **Interfaz de Usuario** | Streamlit | `>= 1.36.0` | Frontend web reactivo, interactivo y autenticación Gatekeeper. |
| **Motor de Hojas de Cálculo** | OpenPyXL | `>= 3.1.2` | Lectura espacial, cálculo de bordes, merges y escritura segura. |
| **Inferencia Semántica** | OpenAI API | `>= 0.27.0` | Mapeo semántico de campos contextuales (`gpt-4.1-mini`). |
| **Validación Estructurada** | Instructor + Pydantic V2 | `>= 1.3.0` / `>= 2.7.0` | Esquemas tipados y salidas estructuradas tipo JSON garantizadas. |
| **Caché Semántico** | RapidFuzz | `>= 3.9.0` | Búsqueda difusa para coincidencia de rótulos y plantillas memorizadas. |
| **Base de Datos y Auth** | Supabase Python SDK | `>= 2.0.0` | Gestión de usuarios, perfiles corporativos y auditoría RLS. |
| **Criptografía Local** | `hashlib` / `hmac` | Estándar Python | Fallback PBKDF2-HMAC-SHA256 para entornos locales de desarrollo. |

### 2.2 Ejecución de Pruebas y Validaciones

Antes de cualquier despliegue o entrega operativa, es obligatorio ejecutar la suite de verificación automatizada:

```bash
# 1. Compilación y chequeo de sintaxis en frío
.\venv\Scripts\python.exe -m py_compile app1.py core/auth_manager.py core/database.py core/excel_parser.py core/excel_writer.py

# 2. Suite canónica de seguridad, RLS y remediación (69 pruebas)
.\venv\Scripts\python.exe tests/test_security_remediation.py

# 3. Suite E2E de flujos sintéticos de staging (14 pruebas)
.\venv\Scripts\python.exe tests/test_synthetic_e2e_staging.py

# 4. Verificación de formato y espacios en blanco de Git
git diff --check
```

---

## 3. Guía de Mantenimiento del Sistema

### 3.1 Monitoreo de Salud de la Aplicación

El equipo de mantenimiento debe vigilar de forma continua tres dimensiones operativas:

1. **Disponibilidad del Frontend (Streamlit):**
   - Verificar que el proceso `streamlit run app1.py` permanezca en ejecución y responda en su puerto configurado (por defecto `8501`).
   - Monitorear el consumo de memoria RAM del servidor; en procesos con formularios extensos (más de 300 celdas), OpenPyXL requiere memoria transitoria en memoria antes de la escritura.
2. **Conectividad y Salud de Supabase:**
   - Supervisar la latencia de respuesta hacia el endpoint `SUPABASE_URL`.
   - Comprobar que el pool de conexiones de PostgreSQL no se encuentre saturado.
   - Confirmar que la tabla `public.deployment_identity` conserve exactamente una fila válida para el entorno en curso (`autoform-excel`).
3. **Consumo y Estado de la API de OpenAI:**
   - Supervisar los límites de cuota (*rate limits* de TPM - Tokens por Minuto y RPM - Solicitudes por Minuto) en la consola de OpenAI.
   - Revisar que el modelo configurado (`OPENAI_MODEL`) se mantenga disponible y sin avisos de depreciación.

### 3.2 Política de Logs: Permitidos vs Estrictamente Prohibidos

> [!CAUTION]
> **POLÍTICA DE PRIVACIDAD Y HABEAS DATA (LEY 1581 DE COLOMBIA / GDPR)**  
> Queda terminantemente prohibido imprimir en consola, registrar en archivos de log o persistir en herramientas de telemetría cualquier documento Excel subido por usuarios, datos personales de clientes o respuestas crudas de IA que contengan información sensible.

```
┌──────────────────────────────────────────────┐  ┌──────────────────────────────────────────────┐
│           LOGS PERMITIDOS (AUDITABLES)       │  │        LOGS ESTRICTAMENTE PROHIBIDOS         │
├──────────────────────────────────────────────┤  ├──────────────────────────────────────────────┤
│ - Timestamps UTC de operaciones.             │  │ - Contenidos de celdas de clientes.         │
│ - Códigos de estado HTTP y UUIDs de lote.    │  │ - Nombres, cédulas o teléfonos de terceros.  │
│ - Correo de usuario autenticado (@iaclatam). │  │ - Números de cuenta o información financiera.│
│ - Cantidad de campos procesados por etapa.   │  │ - Respuestas completas del LLM con datos.    │
│ - Latencia en milisegundos por macro-lote.   │  │ - Tokens JWT (access_token / refresh_token). │
│ - Tipo de evento de auditoría institucional. │  │ - Contraseñas o hashes en texto plano.       │
└──────────────────────────────────────────────┘  └──────────────────────────────────────────────┘
```

### 3.3 Respaldos Físicos y Lógicos

1. **Bases de Datos Supabase (PostgreSQL):**
   - Los respaldos diarios automáticos son gestionados por la plataforma Supabase.
   - Antes de aplicar cualquier migración de esquema (`001_...` a `006_...`), se debe comprobar la existencia del último punto de restauración (*Point-in-Time Recovery*).
2. **Respaldo Local SQLite (`config/empresa.db`):**
   - El sistema ejecuta un respaldo físico automático con cálculo de SHA-256 (`empresa_backup_YYYYMMDD_HHMMSS.db`) al detectar mutaciones administrativas en modo local.
   - Almacenar los respaldos fuera del repositorio Git (la carpeta `config/*.db` y los archivos de respaldo están excluidos vía `.gitignore`).
3. **Plantilla de Perfil Corporativo (`config/datos_empresa.json`):**
   - Representa el perfil canónico institucional. Ante cambios estatutarios, se debe exportar una copia cifrada a almacenamiento seguro.

### 3.4 Actualizaciones y Verificación Posterior a Cambios

Al implementar parches, mejoras o actualizaciones:
1. Realizar los cambios en una rama de características o en `project`.
2. Validar que no se hayan introducido sentencias DDL descontroladas sin preflight de identidad ni postflight.
3. Ejecutar las dos suites de pruebas locales (`test_security_remediation.py` y `test_synthetic_e2e_staging.py`).
4. Ejecutar `git diff --check` para confirmar que no existan errores de formato ni espacios residuales.
5. Aplicar cambios a `staging` únicamente mediante avance rápido (*fast-forward*).

---

## 4. Guía de Soporte y Diagnóstico de Incidentes

### 4.1 Problemas Frecuentes y Acciones de Mitigación

#### A. Colaborador no puede ingresar: "Tu solicitud de acceso está en proceso de revisión"
* **Causa:** El usuario completó el auto-registro pero su cuenta permanece con `estado_aprobacion = 'pendiente'` y `activo = false`.
* **Solución:** Un administrador con rol activo debe ingresar a DocumentForge, acceder a la pestaña **👥 Gestión de Usuarios > Solicitudes Pendientes** y presionar **[Aprobar]**. Esto activará la cuenta y sincronizará su ficha en el catálogo de operadores.

#### B. Bloqueo de seguridad: "Discrepancia en deployment_identity"
* **Causa:** La base de datos conectada no corresponde al proyecto de AutoForm Excel (ej. intento accidental de conexión a bases de AutoForm PDF).
* **Solución:** Verificar inmediatamente la variable `AUTOFORM_EXCEL_STAGING_PROJECT_REF` y `SUPABASE_URL`. La tabla `deployment_identity` previene de forma fail-closed la ejecución sobre entornos no autorizados.

#### C. Error 429 de OpenAI: "RateLimitError / Insufficient Quota"
* **Causa:** Se superó el límite de tokens por minuto o el saldo prepagado en la cuenta de OpenAI.
* **Solución:** Verificar en la consola de facturación de OpenAI el balance de créditos y las cuotas de organización. DocumentForge utiliza paralelización por macro-lotes; si el formulario es masivo, esperar 60 segundos antes de reintentar.

#### D. Desalojo repentino de sesión de un usuario
* **Causa:** El usuario fue suspendido por un administrador (`activo = false`). El mecanismo de guarda de `app1.py` comprueba el estado en cada ciclo y destruye la sesión activa para evitar accesos no autorizados en caliente.

#### E. Bloqueo al intentar desactivar un administrador: "No es posible desactivar al único administrador activo"
* **Causa:** El sistema incorpora una protección estricta en el motor (`PERFORM pg_catalog.pg_advisory_xact_lock(9052026)` y trigger `trigger_proteger_columnas_perfil_usuario`) que impide dejar la plataforma acéfala.
* **Solución:** Asignar previamente el rol de administrador (`es_admin = true`) a otro colaborador activo antes de desactivar o degradar al titular.

### 4.2 Información que el Personal de Soporte DEBE Recopilar

Al recibir un ticket de soporte, solicitar exclusivamente:
1. Correo corporativo del colaborador afectado (`usuario@iaclatam.com`).
2. Marca de tiempo exacta (fecha y hora en zona horaria local).
3. Texto exacto del mensaje de alerta visual en pantalla.
4. Tipo de archivo Excel (`.xlsx` o `.xlsm`) y número aproximado de filas de la hoja.
5. Código de error retornado por la API si aparece en pantalla.

### 4.3 Matriz de Severidad y Escalamiento

```
+------------+-----------------------------------+--------------------+----------------------------+
| Severidad  | Descripción                       | Tiempo de Atención | Escalamiento               |
+------------+-----------------------------------+--------------------+----------------------------+
| SEV-1      | Caída total de la aplicación o     | Inmediato (< 1h)   | Líder de Arquitectura y    |
| (Crítica)  | incidente de seguridad reportado.  |                    | Oficial de Seguridad       |
+------------+-----------------------------------+--------------------+----------------------------+
| SEV-2      | Fallo general del LLM o base de    | < 4 horas          | Equipo DevOps / Backend    |
| (Alta)     | datos Supabase inaccesible.       |                    |                            |
+------------+-----------------------------------+--------------------+----------------------------+
| SEV-3      | Error puntual en mapeo de un      | < 24 horas         | Desarrollador de Soporte   |
| (Media)    | formulario Excel específico.      |                    |                            |
+------------+-----------------------------------+--------------------+----------------------------+
| SEV-4      | Consulta de usuario, solicitud de | < 48 horas         | Administrador Operativo    |
| (Baja)     | acceso o actualización de perfil. |                    | L1                         |
+------------+-----------------------------------+--------------------+----------------------------+
```

---

## 5. Checklists Operativos Estandarizados

### 5.1 Checklist de Operación Antes de Despliegue a Producción

- [ ] **1. Integridad de Código:** Rama `staging` sincronizada con `project` mediante fast-forward limpio sin commits de mezcla no autorizados.
- [ ] **2. Pruebas de Seguridad:** Ejecución exitosa de los 69 tests canónicos en `test_security_remediation.py` con 0 fallos.
- [ ] **3. Pruebas E2E:** Ejecución exitosa de los 14 tests de `test_synthetic_e2e_staging.py` con 0 fallos.
- [ ] **4. Validación de Limpieza:** `git diff --check` ejecutado con cero advertencias de espacios en blanco o saltos de línea.
- [ ] **5. Aislamiento de Base de Datos:** Verificación de singleton en `public.deployment_identity` en el proyecto destino.
- [ ] **6. Verificación de RLS:** Tabla `public.auditoria_autenticacion` protegida con RLS activo, política SELECT administrativa exclusiva y trigger de inmutabilidad funcional.
- [ ] **7. Verificación de Trigger de Perfiles:** Trigger `trigger_proteger_columnas_perfil_usuario` activo, validando inmutabilidad de `id`, restricción de `correo` a backend y protección de último admin.
- [ ] **8. Variables de Entorno:** Todas las credenciales configuradas en el almacén seguro de producción; archivo `.env` ausente del repositorio.
- [ ] **9. Cero Registros Sintéticos:** Confirmación de que no existan usuarios ni filas de prueba con prefijo `synth.%` en el entorno productivo.
- [ ] **10. Conectividad OpenAI:** API Key de producción con saldo activo y modelo asignado correctamente.

### 5.2 Checklist para Respuesta ante Incidentes de Seguridad

- [ ] **Paso 1 — Contención Inmediata:** Si se detecta comportamiento anómalo en una cuenta, desactivar el usuario de inmediato desde el Panel de Administración (`activo = false`). El Gatekeeper lo desalojará automáticamente.
- [ ] **Paso 2 — Preservación de Evidencias:** No reiniciar ni eliminar bases de datos. La tabla `public.auditoria_autenticacion` es inmutable ante sentencias UPDATE y DELETE de usuarios; sus registros proporcionan la traza forense.
- [ ] **Paso 3 — Aislamiento de Llaves:** Si se sospecha compromiso de credenciales maestras (`SUPABASE_SECRET_KEY` u `OPENAI_API_KEY`), revocarlas de inmediato en la consola del proveedor y generar nuevas llaves.
- [ ] **Paso 4 — Auditoría de Consultas:** Revisar las consultas ejecutadas en Supabase verificando la ausencia de intentos de inyección SQL o elevación de privilegios.
- [ ] **Paso 5 — Notificación:** Informar al Oficial de Seguridad de la Información y registrar el reporte formal del incidente.
- [ ] **Paso 6 — Restauración Controlada:** Desplegar credenciales renovadas en el gestor de secretos seguro y reactivar el servicio tras validar el checklist de pre-producción.
