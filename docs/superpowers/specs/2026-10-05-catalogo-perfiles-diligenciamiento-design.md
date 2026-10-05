# Catálogo compartido de perfiles de diligenciamiento

**Estado:** Implementado en código; pendiente de aplicar la migración 007 en el entorno que corresponda.

## Propósito

AutoForm AI debe permitir que una cuenta corporativa elija la identidad cuyos
datos fijos diligencian un formulario. Una misma cuenta puede usar su perfil
predeterminado, un perfil guardado como *José (Comerciante)* o *Empresa X*, o
crear uno nuevo. No se incluye recuperación documental, RAG, OCR, lectura de
RUT ni Cámara de Comercio.

## Lenguaje de dominio

- **Cuenta corporativa:** la identidad autenticada que utiliza la plataforma.
- **PerfilDiligenciamiento:** identidad con datos fijos que se usa para llenar
  un formulario. Puede representar una persona, empresa o contratista.
- **OperadorActivo:** asesor o responsable que diligencia el formulario; no es
  sinónimo de PerfilDiligenciamiento.
- **Perfil predeterminado:** preferencia individual de una cuenta corporativa,
  no un estado global del catálogo.

El nombre de interfaz puede ser “Perfiles comerciales”, pero el código usará
`PerfilDiligenciamiento` para no confundirlo con `ContactoComercialDomain`.

## Decisiones

1. Los perfiles son compartidos entre todos los usuarios corporativos activos.
   Nunca se exponen a usuarios anónimos o inactivos.
2. Cualquier usuario activo puede crear y editar perfiles. Solo un administrador
   activo puede archivarlos o eliminarlos.
3. El perfil seleccionado se guarda en la sesión y se inmoviliza como una
   instantánea en cada `PipelineContext`; no existirá un perfil activo global.
4. El pipeline continúa consumiendo el diccionario existente `datos_empresa`.
   La selección de `profile_id` es el único origen permitido de ese diccionario.
5. Cambiar de perfil invalida análisis, plan de mapeo, archivo generado y datos
   temporales asociados al formulario anterior.

## Persistencia

Se evoluciona la tabla existente `perfiles_empresa` en lugar de crear un
sistema documental nuevo. El registro representa un PerfilDiligenciamiento y
conserva `datos_json` como estructura flexible de datos fijos.

Campos nuevos previstos:

| Campo | Uso |
|---|---|
| `tipo_perfil` | `PERSONA`, `EMPRESA` o `CONTRATISTA`. |
| `estado` | `ACTIVO` o `ARCHIVADO`. |
| `version` | Control optimista de concurrencia. |
| `creado_por` | Cuenta corporativa creadora. |
| `actualizado_por` | Última cuenta editora. |

La clave primaria `id` es el `profile_id` canónico. `slug` continúa como
identificador legible único. La columna `es_activa` y el archivo
`perfil_activo.txt` se deprecian y dejan de gobernar el flujo.

Se añadirá `preferencias_perfil_usuario`:

| Campo | Uso |
|---|---|
| `usuario_id` | Clave primaria; referencia a `perfiles_usuario`. |
| `perfil_predeterminado_id` | Referencia a `perfiles_empresa.id`. |
| `updated_at` | Trazabilidad de preferencia. |

El perfil actual `principal` se migra sin pérdida de datos y se configura como
preferencia inicial de cada usuario corporativo existente.

## Seguridad

Las políticas RLS permiten a usuarios corporativos activos leer, crear y
actualizar perfiles activos. El archivado y borrado se reservan a administradores
activos. Cada mutación registra actor, versión y marca de tiempo.

Una actualización incluye `version` esperada; si no coincide con la versión
actual se rechaza y la interfaz solicita recargar, evitando sobrescrituras
silenciosas entre usuarios.

## Módulos y seams

`core/profile_manager.py` será el módulo de catálogo. Su interfaz concentra
listado, carga, creación, edición, archivado y preferencias por usuario; la UI
no conoce SQLite, Supabase, rutas JSON ni `slug`.

`core/database.py` funciona como adaptador de persistencia. `pipeline/context.py`
incorpora `profile_id`, `profile_nombre` y `profile_version`. `app1.py` coordina
el flujo; `ui/page_profile_selector.py` y `ui/page_profile_editor.py` separan
selector y edición de la carga de archivos.

## Flujo de interfaz

Antes de cargar un formulario se muestra:

```text
Perfil para diligenciar: [ Mi perfil predeterminado: IAC Latam v ]
                         [ Gestionar perfiles ]
```

El menú contiene el predeterminado, perfiles activos compartidos y “Crear nuevo
perfil”. La creación recopila nombre visible, tipo y datos fijos básicos; al
guardar, el usuario decide explícitamente “Guardar y usar ahora”.

Al elegir un perfil, la interfaz muestra una confirmación con nombre y tipo. Al
confirmar, guarda `active_profile_id` exclusivamente en `st.session_state`,
carga la instantánea de datos y limpia el estado del procesamiento anterior.

## Flujo de pipeline

```text
Sesión autenticada -> profile_id seleccionado -> PerfilDiligenciamiento activo
-> snapshot de datos_json + versión -> PipelineContext
-> Parser / Clasificador / Mapper / Writer -> resultado
```

El Mapper y Writer no hacen consultas por “perfil activo”. Trabajan solamente
con el snapshot de `datos_empresa` recibido en el contexto. Por ello un perfil
no puede aportar datos a otro procesamiento.

## Fuera de alcance

- RAG, vectores, OCR y documentos adjuntos.
- RUT, Cámara de Comercio y estados financieros como fuentes automáticas.
- Compartición externa, perfiles privados y permisos por perfil.
- Cambios a Fase 2A de expansión estructural de Excel.

## Fases de implementación

1. Migración de catálogo, preferencias y RLS.
2. Refactor de `profile_manager` y adaptador de base de datos.
3. Selector de sesión y editor de perfiles.
4. Propagación de `profile_id` y snapshot al pipeline.
5. Migración del perfil principal, pruebas y regresiones de plantillas.

## Criterios de aceptación

- Un usuario puede crear un perfil con datos fijos y seleccionarlo de inmediato.
- Dos usuarios pueden mantener perfiles predeterminados distintos.
- Cada ejecución de formulario lleva un `profile_id` y versión verificables.
- Cambiar de perfil descarta todo resultado pendiente del perfil previo.
- Usuarios activos pueden crear/editar; administradores archivan/eliminan.
- Usuarios anónimos o inactivos no pueden acceder al catálogo.
- Las tres plantillas reales se llenan exclusivamente con el perfil elegido.
- La suite completa no presenta regresiones.
