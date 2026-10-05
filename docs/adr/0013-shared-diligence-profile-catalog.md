# ADR 0013: Catálogo compartido de perfiles de diligenciamiento

**Estado:** Aprobado
**Fecha:** 2026-10-05

## Contexto

Una cuenta corporativa debe poder diligenciar formularios con datos fijos de
distintas personas, empresas o contratistas. El modelo anterior marcaba un
único perfil global (`es_activa` y `perfil_activo.txt`), lo que permitía que la
selección de una persona afectara a las demás sesiones.

## Decisión

`perfiles_empresa` evoluciona a catálogo compartido de
`PerfilDiligenciamiento`, identificado por UUID, con tipo, estado y versión.
Todos los usuarios corporativos activos pueden leer, crear y editar perfiles;
solo administradores activos pueden archivarlos. El archivado es reversible y
es la alternativa aprobada al borrado físico normal.

Cada cuenta conserva su preferencia en `preferencias_perfil_usuario`. La UI
guarda la elección actual únicamente en `st.session_state`. Al comenzar el
procesamiento, `PipelineContext` recibe un snapshot del diccionario junto con
`profile_id`, nombre y versión. Cambiar de perfil elimina resultados pendientes
del perfil anterior.

## Consecuencias

- `es_activa` y `perfil_activo.txt` quedan deprecados y no deciden el flujo
  productivo.
- El control optimista de versión evita sobrescrituras silenciosas.
- Las mutaciones dejan registro de auditoría y las políticas RLS protegen las
  operaciones de acuerdo con la cuenta autenticada.
- No se incorporan RAG, OCR, carga documental, RUT ni Cámara de Comercio.
- El cambio no modifica las garantías ni el alcance de la Fase 1 de Excel.
