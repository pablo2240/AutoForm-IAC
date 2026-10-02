# Política de Seguridad y Gestión de Secretos — DocumentForge

> **DocumentForge (AutoForm AI — IAC Latam)**  
> **Área:** Ciberseguridad, DevOps y Cumplimiento Normativo  
> **Clasificación:** Confidencial / Uso Interno  
> **Alcance:** Entornos de Desarrollo Local, Staging y Producción  

---

## 1. Principios Rectores de Seguridad

DocumentForge implementa una arquitectura defensiva en profundidad sustentada en cuatro principios fundamentales:

1. **Confianza Cero (*Zero Trust*):** Ningún componente, usuario ni cliente web se considera confiable por defecto. Toda petición a la capa de datos debe estar firmada por un JWT válido y sujeta a políticas de **Row Level Security (RLS)** en el motor de base de datos.
2. **Privilegio Mínimo (*Principle of Least Privilege*):** Los clientes frontend operan exclusivamente con llaves anónimas/públicas (`SUPABASE_PUBLISHABLE_KEY`). Las llaves maestras con facultades de superusuario (`SUPABASE_SECRET_KEY`) residen exclusivamente en entornos seguros de backend.
3. **Diseño Fail-Closed (Falla Segura):** Ante cualquier ambigüedad en variables de entorno, discrepancia de identidad de base de datos o caída del servicio de autenticación, el sistema aborta inmediatamente la ejecución impidiendo el acceso o la mutación de registros.
4. **Inmutabilidad y Trazabilidad:** Todo evento de autenticación crítico (recuperaciones, cambios forzados, restablecimientos) se registra en una tabla de auditoría inmutable (`public.auditoria_autenticacion`) que prohíbe sentencias de modificación (`UPDATE`) o borrado (`DELETE`) a usuarios autenticados.

---

## 2. Inventario Canónico de Variables de Entorno

> [!IMPORTANT]
> **POLÍTICA DE CONFIDENCIALIDAD ESTRICTA**  
> La siguiente tabla documenta la definición técnica de las variables requeridas por DocumentForge. **Bajo ninguna circunstancia se deben plasmar valores reales, contraseñas, hashes ni llaves activas en este documento ni en ningún archivo versionado en Git.**

| Variable | Propósito Operativo | Entornos Aplicables | Responsable / Custodio | Dónde Debe Configurarse | Obligatoria |
|---|---|---|---|---|:---:|
| `APP_ENVIRONMENT` | Define el entorno de ejecución (`development`, `staging`, `production`). Controla si se permite SQLite o se exige Supabase. | Dev / Staging / Prod | DevOps / Tech Lead | Configuración del Servicio / Secrets | Sí |
| `SUPABASE_URL` | Endpoint HTTPS canónico del proyecto Supabase asignado a AutoForm Excel. | Dev / Staging / Prod | Administrador Supabase | Almacén Seguro de Variables | Sí |
| `SUPABASE_PUBLISHABLE_KEY` | Llave pública moderna (`sb_publishable_...`) utilizada por el cliente para autenticación y consultas evaluadas con RLS. | Dev / Staging / Prod | DevOps | Almacén Seguro / Secrets | Sí |
| `SUPABASE_SECRET_KEY` | Llave secreta de servicio (`sb_secret_...`). Posee bypass de RLS. **Uso exclusivo en backend de servidor** para tareas de administración y migraciones. | Staging / Prod | Oficial de Seguridad | Almacén de Secretos (Bóveda Cloud) | Sí |
| `AUTOFORM_EXCEL_STAGING_PROJECT_REF` | Identificador de proyecto autorizado (*allowlist*) para evitar ejecuciones accidentales contra proyectos de AutoForm PDF. | Staging | DevOps / QA Lead | Almacén Seguro de Variables | Sí |
| `OPENAI_API_KEY` | Clave de acceso a la API de OpenAI para el motor de inferencia y mapeo semántico del Stage 3. | Dev / Staging / Prod | Gerencia de TI / Finanzas | Almacén de Secretos (Bóveda Cloud) | Sí |
| `OPENAI_MODEL` | Nombre del modelo de lenguaje aprobado para producción (ej. `gpt-4.1-mini`). | Dev / Staging / Prod | Arquitecto de IA | Configuración del Servicio / Secrets | Sí |
| `ADMIN_CORPORATIVO_NOMINAL` | Correo institucional del administrador responsable principal de la plataforma. | Dev / Staging / Prod | Dirección de TI | Configuración del Servicio | Sí |
| `USE_SQLITE` | Bandera booleana (`true`/`false`) para habilitar persistencia en SQLite local exclusivamente en `development`. En staging/prod se ignora y fuerza Supabase. | Dev | Desarrollador Local | Archivo `.env` local (gitignored) | No |
| `AUTOFORM_ADMIN_PASSWORD` | Contraseña temporal para sembrar el admin local en SQLite durante desarrollo offline. Prohibida en staging y prod. | Dev | Desarrollador Local | Archivo `.env` local (gitignored) | No |
| `AZURE_TENANT_ID` | Identificador de inquilino de Microsoft Entra ID para integraciones con SharePoint y OneDrive. | Staging / Prod | Administrador M365 | Almacén de Secretos (Bóveda Cloud) | Condicional |
| `AZURE_CLIENT_ID` | Application (Client) ID registrado en Entra ID para la aplicación DocumentForge. | Staging / Prod | Administrador M365 | Almacén Seguro de Variables | Condicional |
| `AZURE_CLIENT_SECRET` | Clave secreta de la aplicación Entra ID para el flujo OAuth 2.0 Client Credentials. | Staging / Prod | Oficial de Seguridad | Almacén de Secretos (Bóveda Cloud) | Condicional |

---

## 3. Seguridad de Credenciales Administrativas y Secretos

### 3.1 Prohibiciones Categóricas

1. **Cero Hardcoding en Código:** Ninguna credencial, token, contraseña, API key o correo personal debe escribirse directamente en archivos `.py`, `.json`, `.sql`, `.sh`, `.yml` ni notebooks.
2. **Cero Secretos en el Control de Versiones:** El archivo `.env` está declarado en `.gitignore`. Queda terminantemente prohibido forzar su subida (`git add -f .env`), desactivar la regla o compartir credenciales en comentarios de commits o Pull Requests.
3. **Prohibición de Canales Inseguros:** Las claves API y contraseñas maestras nunca deben compartirse a través de plataformas de mensajería (Slack, Teams, WhatsApp) ni correo electrónico no cifrado.

### 3.2 Almacenamiento Seguro Aprobado

- **Entornos Productivos y Staging:** Las variables sensibles deben provisionarse a través de un **Gestor de Secretos Corporativo** aprobado (Azure Key Vault, AWS Secrets Manager o el módulo cifrado de Secrets en Streamlit Cloud).
- **Acceso Restringido:** El acceso a los secretos en producción se otorga únicamente al personal con rol de Administrador de Infraestructura y requiere autenticación multifactor (MFA) obligatoria.
- **Entornos de Desarrollo:** Los desarrolladores deben utilizar su propio archivo `.env` local generado a partir de `.env.example`, sin utilizar claves con privilegios de producción.

---

## 4. Ciclo de Vida de Accesos y Procedimientos de Gestión

```
   ┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
   │ 1. SOLICITUD     │  ───►  │ 2. ROTACIÓN      │  ───►  │ 3. REVOCACIÓN    │  ───►  │ 4. CONTINGENCIA  │
   │    Y ASIGNACIÓN  │        │    PROGRAMADA    │        │    INMEDIATA     │        │    (BREAK-GLASS) │
   └──────────────────┘        └──────────────────┘        └──────────────────┘        └──────────────────┘
```

### 4.1 Procedimiento de Solicitud de Privilegios Administrativos

1. **Requerimiento Formal:** El colaborador solicita el rol administrativo a través del sistema de tickets interno, justificando la necesidad técnica o funcional.
2. **Aprobación de Sponsor:** La solicitud requiere la aprobación explícita del Líder Técnico o Director de TI de IAC Latam.
3. **Asignación en Base de Datos:**
   - Un administrador activo existente ingresa a la pestaña **👥 Gestión de Usuarios > Directorio de Colaboradores**.
   - Cambia el rol a Administrador (`es_admin = true`).
   - La operación queda auditada en el motor y sincronizada con el perfil relacional.

### 4.2 Procedimiento de Rotación de Credenciales

#### A. Rotación Programada (Cada 90 días):
1. **OpenAI API Key:**
   - Generar una nueva clave API en la consola de OpenAI con restricción por proyecto.
   - Actualizar el valor en la bóveda de secretos de Staging y verificar el funcionamiento de las pruebas de regresión.
   - Actualizar la bóveda de Producción.
   - Eliminar la clave anterior en la consola de OpenAI tras confirmar 24 horas de operación estable.
2. **Secretos de Microsoft Entra ID:**
   - Crear un nuevo Client Secret en Azure Portal con caducidad establecida.
   - Desplegar el nuevo secreto en DocumentForge.
   - Revocar el Client Secret anterior.

#### B. Rotación de Emergencia (Ante Sospecha de Filtración o Compromiso):
1. Revocar la clave comprometida de forma inmediata en la consola del proveedor (OpenAI, Supabase o Azure).
2. Generar y desplegar la clave sustituta en el gestor de secretos.
3. Desalojar todas las sesiones activas en Supabase Auth (`auth.admin.sign_out`).
4. Iniciar una auditoría forense revisando la tabla `public.auditoria_autenticacion` y los registros de llamadas a la API.

### 4.3 Procedimiento de Revocación de Accesos

Ante la desvinculación laboral, cambio de área o suspensión preventiva de un colaborador:
1. **Desactivación Inmediata:** El administrador marca la cuenta como suspendida (`activo = false`) en el Panel de Usuarios.
2. **Desalojo en Caliente:** El Gatekeeper de DocumentForge comprueba en cada interacción la validez y el estado del usuario; si la cuenta está inactiva, la sesión se destruye en caliente y se bloquea el acceso a cualquier archivo o perfil.
3. **Revocación en Directorio Central:** Si la autenticación se sincroniza con Microsoft Entra ID, bloquear el usuario en el portal de Azure AD.

### 4.4 Procedimiento de Recuperación de Emergencia (*Break-Glass*)

Si por una falla catastrófica no existiera acceso a las cuentas administrativas nominales:
1. **Acceso a la Bóveda de Custodia:** Dos custodios autorizados (ej. Director de TI y Oficial de Ciberseguridad) acceden a la caja fuerte digital corporativa (procedimiento de control dual).
2. **Invocación Segura por Backend:** Utilizando un script de mantenimiento ejecutado exclusivamente desde una terminal interna protegida y autenticado con `SUPABASE_SECRET_KEY`, se restablece el acceso del Administrador Corporativo Nominal (`ADMIN_CORPORATIVO_NOMINAL`).
3. **Registro Obligatorio:** Toda activación del protocolo Break-Glass debe generar un acta formal de incidente y motivar una rotación inmediata de las credenciales de servicio utilizadas.

---

## 5. Salvaguardas en el Motor de Base de Datos

DocumentForge delega la protección de última línea al motor PostgreSQL de Supabase mediante restricciones inviolables:

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                           CAPAS DE BLINDAJE EN EL MOTOR POSTGRESQL                                |
+───────────────────────────────────────────────────────────────────────────────────────────────────+

  1. Preflight de Identidad   ──► Valida exactamente 1 singleton en deployment_identity
                                  (app='autoform-excel', env='staging', ref='nfaxkncrpfrsvzfgczny').
                                  Si hay discrepancia, aborta de forma fail-closed.

  2. Row Level Security (RLS) ──► public.auditoria_autenticacion:
                                  - SELECT: Exclusivo para administradores activos autenticados.
                                  - INSERT/UPDATE/DELETE: Prohibido para clientes authenticated y anon.
                                  - Escritura exclusiva para el backend autorizado (service_role).

  3. Inmutabilidad Estricta   ──► trg_proteger_inmutabilidad_auditoria:
                                  - UPDATE: Denegado categóricamente (excepción inmediata).
                                  - DELETE: Bloqueado; solo admite purga sintética (synth.%) por service_role.
                                  - Definido SIN elevación de privilegios (prosecdef=false) y SET search_path=''.

  4. Protección de Perfiles   ──► trigger_proteger_columnas_perfil_usuario:
                                  - id: Absolutamente inmutable para cualquier rol.
                                  - correo: Modificable únicamente por backend autorizado (service_role).
                                  - debe_cambiar_password: Modificable únicamente por service_role.
                                  - Último Administrador: Bloqueo transaccional pg_advisory_xact_lock(9052026)
                                    que prohíbe desactivar o degradar al único administrador activo.
```

---

## 6. Política de Privacidad de Datos y Cero Residuos

> [!CAUTION]
> **COMPROMISO INSTITUCIONAL DE CONFIDENCIALIDAD**  
> DocumentForge procesa información financiera y jurídica de alta sensibilidad para IAC Latam y sus aliados comerciales. 
> 
> - **Cero Retención de Documentos:** Los archivos Excel subidos por usuarios se procesan estrictamente en memoria RAM volátil. Una vez generado y descargado el archivo completado, los búferes se liberan.
> - **Cero Datos de Terceros en Repositorio:** Ninguna hoja de cálculo de un cliente real debe ser utilizada como caso de prueba o guardarse en la carpeta `example/` o `scratch/`.
> - **Aislamiento de Fixtures:** Todas las pruebas automatizadas deben ejecutarse contra usuarios sintéticos aislados con el prefijo canónico `synth.*@iaclatam.com` y ser purgadas al finalizar.
