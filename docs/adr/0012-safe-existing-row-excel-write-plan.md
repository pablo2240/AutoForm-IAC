# ADR 0012: Plan de escritura Excel con filas existentes

**Estado:** Aprobado
**Fecha:** 2026-10-02

## Decisión

El pipeline resuelve y valida la coordenada final de cada escritura antes de
ejecutarla. El writer es un ejecutor estricto: no recalcula direcciones, no
aplica fallbacks y no crea, elimina o recompone rangos combinados.

Para tablas repetitivas se usan solamente filas preexistentes, vacías y
estructuralmente delimitadas por una tabla formal. Las listas societarias se
asignan en orden hasta agotar estas filas. Los registros restantes se reportan
como `EXCEDENTE_NO_ASIGNADO`; nunca se insertan filas en esta fase.

## Restricciones de integridad

- No se sobrescriben fórmulas, celdas protegidas ni valores existentes.
- Fórmulas, validaciones, merges, tablas y estado de hojas se comparan con la
  instantánea original después de guardar; cualquier divergencia bloquea la
  entrega.
- Se aceptan `.xlsx` y `.xlsm` con macros preservadas mediante `keep_vba`.
  Los `.xls` y archivos con controles VML no preservables se rechazan antes de
  escribir, conforme a ADR-0001.

## Consecuencias

La inserción de filas y la expansión de tablas quedan explícitamente fuera de
alcance. Requerirán un ADR posterior, autorización por plan y pruebas de
fórmulas relativas, validaciones y referencias de tabla.
