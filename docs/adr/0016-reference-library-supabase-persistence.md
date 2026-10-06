# ADR 0016: Persistencia de la biblioteca de referencias en Supabase

**Estado:** Aprobado
**Fecha:** 2026-10-06
**Complementa:** ADR-0015

## Contexto

Los formularios de referencia contienen datos reales de la empresa y el repositorio es público, así que
no pueden versionarse. El disco de Streamlit Cloud es efímero, por lo que sin otra persistencia la
biblioteca arrancaba vacía en cada reinicio.

## Decisión

Supabase es el almacenamiento persistente de la biblioteca en la nube (migración `009`):

- **Archivos:** bucket privado `referencias` en Storage. Los objetos se nombran por hash de la clave
  (`ruta_de_almacenamiento`): los nombres reales (tildes, espacios, paréntesis) viven en el catálogo.
- **Catálogo:** tabla `referencias_catalogo` con metadatos y la **instantánea JSONB del conocimiento ya
  extraído**. Reconstruir la base local tras un reinicio es importar instantáneas: no se descargan ni se
  vuelven a escanear los Excel (el paso lento). El archivo solo se descarga y reanaliza si la instantánea
  no sirve (cambió `EXTRACTOR_VERSION` o los datos de la empresa), y entonces un administrador la actualiza.
- **Permisos (RLS, verificados con roles reales):** leen los usuarios activos (el pipeline lo necesita en
  todas las sesiones); escriben solo administradores activos, tanto en la tabla como en `storage.objects`.
  Anónimos no ven nada. Todas las operaciones usan el JWT del usuario; nunca la clave de servicio.
- **Dos orígenes en la base local** (`ref_documentos.origen`): `local` (carpeta `docs/referencias`, para
  desarrollo) y `nube` (importados del catálogo). Cada sincronización solo retira documentos de su propio
  origen, de modo que un equipo de desarrollo con Supabase configurado nunca pierde sus archivos locales.
- **Interfaz `RepositorioRemoto`** (`remote.py`) con `RepositorioSupabase` como implementación; la
  lógica de sincronización (`SincronizadorNube`) se prueba contra un repositorio en memoria que imita RLS.
- **Sincronización:** en segundo plano al abrir la app, con intervalo mínimo
  (`AUTOFORM_REFERENCES_SYNC_TTL_S`, 600 s) para que una sesión nueva recoja lo publicado por un
  administrador. El panel permite subir, eliminar, reprocesar y **publicar en la nube** los formularios
  que un administrador tenga en su equipo.

## Consecuencias

- La biblioteca persiste entre reinicios sin exponer datos en el repositorio.
- Una referencia sube una sola vez; todos los despliegues y sesiones la comparten.
- Las instantáneas contienen valores de ejemplo de la propia empresa: tienen la misma sensibilidad que
  `perfiles_empresa` y se protegen con la misma política (usuario activo).
- Si la biblioteca crece a miles de documentos, importar todas las instantáneas en cada reinicio será
  lento; el siguiente paso sería persistir también los vectores (pgvector) detrás de `IndiceVectorial`.
