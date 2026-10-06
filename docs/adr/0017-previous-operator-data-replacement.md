# ADR 0017: Reemplazo de datos de un diligenciador anterior y mapeo reproducible

**Estado:** Aprobado
**Fecha:** 2026-10-06
**Complementa:** ADR-0007, ADR-0014

## Contexto

Al cambiar el selector "Diligenciado por" de una persona a otra (p. ej. de Pablo Reyes a José), el
formulario seguía mostrando los datos de la primera. Dos causas, reproducidas con los formularios de ejemplo:

1. Un formulario ya diligenciado antes (una salida de la app, o una plantilla con el contacto escrito) trae
   los datos del diligenciador anterior en celdas **ya llenas**. El escritor las respeta (ADR-0012: nunca
   sobrescribe información existente) y el escáner descarta los rótulos cuyas celdas vecinas ya están
   ocupadas, de modo que esos campos nunca llegaban a recibir los datos del perfil activo.
2. La llamada al LLM por Instructor no fijaba `temperature` ni `seed` (las demás sí): el mismo formulario
   producía mapeos distintos entre ejecuciones (p. ej. 57 y 58 campos), lo que parecía una pérdida de
   precisión respecto de la prueba anterior.

## Decisión

- **Etapa 3d** (`stage_3d_diligenciador_previo`, `core/diligenciador_previo`): reconoce **por valor** las
  celdas que contienen el nombre, correo, cédula o teléfono de un diligenciador conocido distinto del activo
  (catálogo `operadores`, cuentas visibles y la propia) y agrega al plan su reemplazo por el dato del perfil
  activo, con `sobrescribir_valor_previo`. Cargo, dirección y ciudad se reemplazan solo junto a una celda de
  identidad del mismo diligenciador anterior. Si el perfil activo no tiene un dato, el anterior se retira.
- **Precisión sobre cobertura:** se excluyen los valores que también son datos fijos de la empresa o del
  representante legal; un nombre completo basta, pero un correo, cédula o teléfono solos exigen otra celda
  de identidad del mismo diligenciador a pocas filas (un correo de facturación de la plantilla no se toca).
  No se infiere nada por posición o rótulo.
- **Escritor:** solo respeta la excepción para campos `responsable_*` marcados por la etapa 3d; los datos de
  la empresa siguen protegidos por la regla de ADR-0012. La marca sobrevive a la tabla de verificación y la
  pantalla de descarga informa cuántas celdas se reemplazaron.
- **Reproducibilidad:** la llamada por Instructor usa `temperature=0` y `seed=42`, igual que el resto.

## Consecuencias

- Cambiar de diligenciador sobre un formulario ya diligenciado reemplaza sus datos en el mismo lugar y con
  el mismo formato.
- Un diligenciador anterior que no esté registrado (como "Antonio Prieto" en algunas plantillas) no se
  reconoce: basta crearlo en el selector para que sus datos también se reemplacen.
- El mismo formulario produce el mismo mapeo en cada ejecución.
