# Guía de Integración con Microsoft 365 — DocumentForge

> **DocumentForge (AutoForm AI — IAC Latam)**  
> **Área:** Arquitectura de Integraciones y Cloud Services  
> **Servicios Objeto:** Microsoft Graph API v1.0, SharePoint Online y OneDrive for Business  
> **Estándar:** OAuth 2.0 / Microsoft Entra ID (Azure AD)  

---

## 1. Introducción y Casos de Uso

La integración de **DocumentForge** con el ecosistema Microsoft 365 permite conectar el flujo automatizado de diligenciamiento de formularios con las bibliotecas corporativas de documentos de **IAC Latam**. Esto habilita:

1. **Ingesta Automatizada de Formatos:** Lectura de plantillas Excel en blanco depositadas por equipos comerciales en bibliotecas designadas de SharePoint o carpetas de OneDrive.
2. **Despacho Centralizado:** Almacenamiento directo del archivo `.xlsx` completado en la carpeta del cliente correspondiente, conservando el historial de versiones institucional.
3. **Sincronización Desatendida:** Detección de nuevos formularios mediante consultas de cambio incremental (*Delta Queries*), sin necesidad de subir archivos manualmente a través de la interfaz web.

Todas las interacciones se realizan exclusivamente mediante las **APIs oficiales de Microsoft Graph v1.0**, rechazando cualquier método legacy (WebDAV, APIs de SharePoint 2013 o raspado web).

---

## 2. Arquitectura de Autenticación y Autorización (OAuth 2.0)

La seguridad de la integración se fundamenta en **Microsoft Entra ID** (anteriormente Azure Active Directory), implementando flujos basados en el estándar **OAuth 2.0**.

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                           FLUJO DE AUTENTICACIÓN CON MICROSOFT GRAPH                              |
+───────────────────────────────────────────────────────────────────────────────────────────────────+

  DocumentForge (Backend)               Microsoft Entra ID (Token Endpoint)       Microsoft Graph API
           │                                             │                                  │
           │  1. Solicita Token (OAuth 2.0)              │                                  │
           │     - Client ID                             │                                  │
           │     - Client Secret / Certificado           │                                  │
           │     - Scope: https://graph.microsoft.com/.default                              │
           │────────────────────────────────────────────►│                                  │
           │                                             │                                  │
           │  2. Valida credenciales y permisos          │                                  │
           │     Retorna Access Token (JWT, exp: 60-90m) │                                  │
           │◄────────────────────────────────────────────│                                  │
           │                                                                                │
           │  3. Invoca API con Bearer Token                                                │
           │     GET /v1.0/sites/{site-id}/drives/{drive-id}/root/delta                     │
           │───────────────────────────────────────────────────────────────────────────────►│
           │                                                                                │
           │  4. Retorna metadatos de archivos / stream de contenido                        │
           │◄───────────────────────────────────────────────────────────────────────────────│
```

### 2.1 Modalidades de Conexión Soportadas

1. **Flujo de Credenciales de Cliente (*Client Credentials Grant* — Aplicación Desatendida):**
   - **Uso:** Procesos automáticos, sincronizaciones programadas o demonios en segundo plano sin intervención humana.
   - **Mecanismo:** La aplicación se autentica directamente con su propio `CLIENT_ID` y `CLIENT_SECRET` (o certificado digital X.509).
   - **Alcance:** Opera a nivel de servicio institucional; los permisos se asignan a la aplicación y requieren consentimiento previo del Administrador Global de Microsoft 365.
2. **Flujo de Código de Autorización con PKCE (*Authorization Code with PKCE* — Delegado):**
   - **Uso:** Acciones iniciadas por el usuario interactivo en la interfaz de Streamlit.
   - **Mecanismo:** El asesor comercial inicia sesión con su cuenta corporativa (`@iaclatam.com`) y DocumentForge actúa en su nombre.
   - **Alcance:** La aplicación sólo puede acceder a los archivos a los que el usuario firmante tenga permisos efectivos en SharePoint o OneDrive.

---

## 3. Catálogo de Permisos Mínimos Requeridos (Principio PoLP)

Para salvaguardar la confidencialidad de la información corporativa, se aplica con rigor el **Principio de Menor Privilegio (Principle of Least Privilege - PoLP)**. Queda prohibido solicitar permisos con alcance sobre todo el directorio.

### 3.1 Permisos de Aplicación (Recomendados para el Demonio de Sincronización)

| Permiso de Graph | Tipo | Justificación Operativa | Nivel de Riesgo |
|---|---|---|---|
| `Sites.Selected` | Aplicación | **Permiso preferido.** Permite restringir el acceso de DocumentForge a **únicamente** la colección de sitios y bibliotecas de formularios aprobadas, impidiendo el acceso a otros sitios corporativos. | 🟢 Bajo (Controlado) |
| `Files.ReadWrite.All` | Aplicación | Permite leer y escribir archivos en todas las unidades compartidas de la organización. *Solo utilizar si `Sites.Selected` no está disponible en la suscripción del tenant.* | 🟡 Medio |

> [!IMPORTANT]
> **Configuración de `Sites.Selected`:**
> Tras otorgar `Sites.Selected` en el registro de la aplicación de Azure, el Administrador del Tenant debe ejecutar un comando de PowerShell o una llamada administrativa en Graph para conceder explícitamente derechos `read` o `write` sobre el sitio específico de vinculación documental:
> `POST /v1.0/sites/{site-id}/permissions`

### 3.2 Permisos Delegados (Flujo Interactivo)

| Permiso de Graph | Tipo | Justificación Operativa |
|---|---|---|
| `Files.ReadWrite` | Delegado | Lectura y guardado de formularios en el OneDrive o SharePoint del usuario conectado. |
| `Sites.Read.All` | Delegado | Localización de bibliotecas de documentos en los sitios de trabajo donde el usuario colabora. |
| `offline_access` | Delegado | Permite recibir un `refresh_token` para mantener activa la sesión sin solicitar credenciales continuamente. |

### 3.3 Permisos Categóricamente Prohibidos

Los siguientes permisos **no deben solicitarse jamás** para DocumentForge:
- ❌ `Directory.ReadWrite.All` (acceso destructivo a todo el directorio activo).
- ❌ `User.ReadWrite.All` (modificación de identidades de usuarios).
- ❌ `RoleManagement.ReadWrite.Directory` (escalación de privilegios administrativos).
- ❌ `Files.ReadWrite.All` con consentimiento desmedido sin justificación formal.

---

## 4. Operaciones con SharePoint y OneDrive vía Graph API v1.0

### 4.1 Identificación de Recursos Institucionales

Para operar sobre un sitio de SharePoint, primero se deben resolver sus identificadores únicos canónicos:

```http
# Obtener Site ID por URL relativa
GET https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{nombre-sitio}
Authorization: Bearer <access_token>

# Obtener las bibliotecas de documentos (Drives) del sitio
GET https://graph.microsoft.com/v1.0/sites/{site-id}/drives
Authorization: Bearer <access_token>
```

### 4.2 Descarga Segura de Plantillas

```http
# Descarga de contenido binario del archivo Excel (.xlsx)
GET https://graph.microsoft.com/v1.0/drives/{drive-id}/items/{item-id}/content
Authorization: Bearer <access_token>
```
El archivo se recibe en memoria en un búfer binario (`io.BytesIO`) para su procesamiento inmediato en el Stage 1 (`core/excel_parser.py`), sin escribir archivos temporales en discos no cifrados.

### 4.3 Carga y Versionamiento del Documento Diligenciado

#### Archivos Menores a 4 MB (Carga Directa):
```http
PUT https://graph.microsoft.com/v1.0/drives/{drive-id}/items/{parent-folder-id}:/{nombre-archivo-completado}.xlsx:/content
Authorization: Bearer <access_token>
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet

<Contenido binario OpenXML>
```

#### Archivos Mayores a 4 MB (Sesión de Carga por Fragmentos — *Upload Session*):
Para formularios con imágenes pesadas o catálogos anexos:
1. Crear la sesión: `POST /v1.0/drives/{drive-id}/items/{parent-id}:/{nombre-archivo}.xlsx:/createUploadSession`
2. Enviar fragmentos consecutivos de entre 5 MB y 10 MB mediante `PUT` con encabezados `Content-Range`.

---

## 5. Sincronización Incremental mediante Delta Queries

Para evitar la sobrecarga de consultar repetidamente todos los archivos del repositorio, DocumentForge implementa la sincronización incremental de Microsoft Graph.

```
       Inicio / Primera Pasada                             Sincronizaciones Posteriores
       ───────────────────────                             ────────────────────────────
 GET /drives/{id}/root/delta                               GET {deltaLink}
           │                                                     │
           ▼                                                     ▼
 Retorna todos los archivos                              Retorna ÚNICAMENTE los archivos
           │                                             creados, editados o eliminados
           ▼                                             desde la última consulta
 Entrega: @odata.deltaLink ───► Guardar Cursor Seguro            │
                                                                 ▼
                                                        Entrega nuevo @odata.deltaLink
```

### 5.1 Protocolo de Ejecución del Cursor Delta

1. **Consulta Inicial:**
   ```http
   GET https://graph.microsoft.com/v1.0/drives/{drive-id}/root/delta
   Authorization: Bearer <access_token>
   ```
2. **Paginación (`@odata.nextLink`):** Si la biblioteca contiene múltiples elementos, Graph responde con una URL de siguiente página. Debe seguirse hasta recibir `@odata.deltaLink`.
3. **Persistencia del Cursor:** El valor `@odata.deltaLink` contiene una firma temporal opaca de estado. Se debe almacenar en la base de datos de configuración de la integración.
4. **Consultas Siguientes:** Invocar periódicamente la URL de `@odata.deltaLink`. Si no hubo cambios, Graph responde con un arreglo vacío de cambios en menos de 200 ms.

---

## 6. Gestión, Caché y Renovación de Tokens con MSAL

La integración debe implementarse utilizando la librería oficial **MSAL (Microsoft Authentication Library)** para Python (`msal`).

### 6.1 Buenas Prácticas de Ciclo de Vida del Token

- **Vigencia:** Los tokens de acceso emitidos por Entra ID tienen una vigencia por defecto de entre 60 y 90 minutos.
- **Caché en Memoria:** No solicitar un token a Entra ID antes de cada solicitud HTTP. Utilizar el método `acquire_token_silent` de MSAL, el cual reutiliza el token vigente en memoria y lo renueva de forma desatendida cuando faltan pocos minutos para su expiración.
- **Manejo de Refresh Tokens (Flujo Delegado):** El token de actualización (*refresh token*) debe almacenarse de forma estrictamente cifrada (AES-256) en la base de datos, protegido por variables de entorno del servidor.

```python
# Ejemplo conceptual del patrón estándar de obtención segura con MSAL:
# app = ConfidentialClientApplication(client_id, authority=authority, client_credential=secret)
# result = app.acquire_token_silent(scopes=["https://graph.microsoft.com/.default"], account=None)
# if not result:
#     result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
```

---

## 7. Matriz de Errores Frecuentes, Códigos HTTP y Resiliencia

| Código HTTP | Error Graph | Causa Frecuente | Estrategia de Mitigación en DocumentForge |
|---|---|---|---|
| **`401`** | `InvalidAuthenticationToken` | Token expirado, firma corrupta o clock skew en servidor. | Invalidar caché de MSAL y solicitar nuevo token de inmediato. |
| **`403`** | `AccessDenied` | La app no tiene permisos en el sitio de SharePoint o falta el consentimiento del administrador. | Registrar alerta operativa para el administrador de M365. No reintentar en bucle. |
| **`404`** | `ItemNotFound` | El archivo o carpeta fue movido, renombrado o eliminado en SharePoint. | Descartar el elemento del pipeline y registrar evento en auditoría. |
| **`409`** | `NameAlreadyExists` / `EditConflict` | Conflicto de versión por guardado concurrente o archivo abierto en co-autoría en Excel Online. | Aplicar sufijo de versión único al archivo diligenciado (ej. `_completado_20260928_103000.xlsx`). |
| **`423`** | `Locked` | El archivo está bloqueado exclusivamente por un usuario que lo tiene abierto en Excel Desktop. | Reintentar hasta 3 veces con intervalo de 30 segundos; si persiste, notificar al operador. |
| **`429`** | `TooManyRequests` | **Throttling de Graph:** Se excedió la cuota de peticiones por segundo en el tenant. | **Obligatorio:** Leer el encabezado `Retry-After` de la respuesta, suspender peticiones por los segundos indicados y reintentar con *exponential backoff con jitter*. |
| **`503` / `504`** | `ServiceUnavailable` / `GatewayTimeout` | Falla transitoria en los servidores de Microsoft Cloud. | Aplicar hasta 3 reintentos automáticos espaciados (2s, 4s, 8s). |

---

## 8. Advertencias de Seguridad, Privacidad y Cumplimiento

> [!CAUTION]
> **PROTECCIÓN DE ACTIVOS INSTITUCIONALES EN INTEGRACIONES CLOUD**
> 1. **Prohibición de Credenciales Quemadas:** `CLIENT_ID`, `CLIENT_SECRET` o claves privadas jamás deben escribirse en el código fuente, archivos `.py`, notebooks ni archivos de configuración locales.
> 2. **Cero Datos en Logs:** Nunca registrar los cuerpos de las respuestas de Graph que contengan listados de carpetas personales de colaboradores ni previsualizaciones de documentos.
> 3. **Aislamiento por Carpetas:** Configurar la sincronización de DocumentForge exclusivamente sobre carpetas designadas para vinculación corporativa. La aplicación no debe tener visibilidad de carpetas privadas de empleados ni de directorios de nómina o contabilidad general.
