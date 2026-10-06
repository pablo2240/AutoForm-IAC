# ADR 0014: Empresa fija y selector de diligenciador

**Estado:** Aprobado
**Fecha:** 2026-10-06
**Reemplaza parcialmente:** ADR-0013 (la parte de selección de perfiles de empresa en la UI).

## Contexto

Los datos de la empresa son fijos y no deben elegirse en cada ejecución. Lo que
cambia entre ejecuciones es quién diligencia el formulario (comercial, asesor o
persona que lo tramita, p. ej. «José - Comercial»), que alimenta la sección
«Diligenciado por / Contacto comercial» (ADR-0007).

## Decisión

- **Empresa fija:** `profile_manager.obtener_empresa_fija()` entrega siempre el
  perfil `principal` (o `config/datos_empresa.json` como respaldo). La UI ya no
  muestra selector, creador ni editor de perfiles de empresa. El catálogo de
  ADR-0013 y la migración 007 quedan en el código sin uso en la UI.
- **Selector «Diligenciado por»** (`ui/page_diligenciador_selector.py`) con tres
  opciones: *Mi perfil* (cuenta en sesión, por defecto), un diligenciador
  guardado de la tabla `operadores`, o *Crear nuevo* (nombre, cédula, cargo,
  teléfono, correo).
- La elección vive solo en `st.session_state`; `es_activo` deja de ser decisión
  global. Cambiar de diligenciador descarta resultados ya procesados.
- Al procesar, `fusionar_operador_en_datos_empresa` completa los campos
  `responsable_*` sobre los datos fijos de la empresa; el pipeline no cambia.
- Crear un diligenciador (`crear_diligenciador_db`) solo inserta en `operadores`:
  no modifica cuentas de usuario ni marcas globales.
- **Migración 008:** cualquier usuario activo puede crear diligenciadores y
  editar los que no pertenecen a una cuenta; borrar sigue siendo solo de admin.

## Consecuencias

- La página no depende de la migración 007 para abrir.
- Crear diligenciadores desde la app requiere aplicar la migración 008.
