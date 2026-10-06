# ADR 0018: Plausibilidad, confianza honesta y árbitro de dirección

**Estado:** Aprobado
**Fecha:** 2026-10-06
**Complementa:** ADR-0002, ADR-0004, ADR-0005

## Contexto

En la vista de cambios propuestos aparecían dos problemas sobre `01 SC-COM-02-25.xlsx`:

1. Textos que no son campos ("Activación", una casilla con "X", la instrucción
   "Por favor indicar el porcentaje de cumplimiento de su SG-SST:95.0%") asignados a `razon_social` con
   confianza "Alta" (0.85). `_calcular_nivel_confianza` marcaba ALTA a toda asignación del LLM cuyo campo
   tuviera valor en el perfil, sin comparar el rótulo con el campo.
2. "Número de Cuenta" y "E-mail de Contacto" escribían a la derecha, en una celda vacía **fuera de la tabla**,
   cuando la celda de captura es la de abajo (mismo ancho combinado, con bordes). El escáner elige "derecha"
   en cuanto la celda vecina está vacía; los demás encabezados de la misma fila sí iban "abajo".

## Decisión

- **A1 — compuerta de plausibilidad** (`core/plausibilidad.py`, etapa 3c): descarta la asignación cuando el
  rótulo es largo (> 12 palabras o > 100 caracteres), una pregunta, una instrucción ("Por favor…", "Marque…"),
  ya trae el valor ("…SG-SST:95.0%"), la celda destino contiene una marca de casilla ("X", "✓") o el elemento es
  una opción de un grupo de selección. También filtra las sugerencias de la vista de verificación.
- **A2 — confianza honesta** (`core/confianza_mapeo.py`): el puntaje sale de evidencia. Fuerte (0.90-0.95):
  alias determinista, regla determinista, nombre del campo en el rótulo, validador de contexto, fórmula de
  declaración del representante o coincidencia con un formulario de referencia. Solo-LLM: similitud
  semántica rótulo-campo con el modelo FastEmbed local (>= 0.50 -> 0.80 "Alta"; 0.30-0.50 -> 0.60 "Requiere
  revisión"; < 0.30 -> descartada, salvo que la sección sea del dominio del campo: entonces 0.65 en revisión).
  Sin modelo de embeddings nunca se descarta por esta vía. Las plantillas verificadas solo pasan por A1.
  Calibración: la similitud mediana de un par correcto es 0.52 (al azar, 0.25); 5 de 6 asignaciones absurdas
  conocidas quedan bajo 0.30. Los pares correctos de baja similitud ("C.C" -> cédula) son de evidencia
  fuerte, por eso la similitud solo se usa cuando no la hay.
- **B — árbitro de dirección** (`core/arbitro_direccion.py`, etapa 1): solo evalúa casos ambiguos (derecha y
  abajo vacías) y solo cambia "derecha" por "abajo", y únicamente si la celda de abajo tiene el mismo ancho
  que el rótulo **y** es una caja con bordes en al menos tres lados, con ventaja de puntaje (celda de la
  derecha fuera de la tabla, relleno de captura, rótulos vecinos que escriben hacia abajo). El resultado
  (`direccionArbitrada`) lo respetan la etapa 2, la IR y, por tanto, el plan.
- **Ceros a la izquierda:** el escritor fuerza formato de texto (`@`) en identificadores numéricos con ceros
  iniciales (cuentas, códigos) para que Excel no los convierta a número.
- La fuente del mapeo (`fuente_mapeo`) se propaga al plan (alias determinista, rescate por patrón, cobertura,
  inferencia del LLM).

## Verificación

Comparación antes/después sobre los 7 formularios de `example/`, con las respuestas del LLM grabadas con el
código anterior y reproducidas con el nuevo (0 llamadas reales), para aislar el efecto del código del ruido del
modelo (el LLM, aun con `temperature=0` y `seed`, varía algo entre ejecuciones). Resultado:

- `GE.F.021_5.5`: 0 diferencias en la salida.
- Asignaciones retiradas (9): `¿Pertenece a algún gremio…?`, `RESPONSABLE DE IVA` (escribía el nombre del
  diligenciador), un texto largo asignado a `correo`, valores ya impresos usados como rótulo (`CD`,
  `Cra 63 B Nº 32 E 25`, `CC/CE/PAS`) y `No Responsable`.
- Destinos corregidos a "abajo" (16), todos verificados contra la cuadrícula del formulario (encabezado
  combinado con caja de captura del mismo ancho debajo y celda de la derecha fuera de la tabla), entre ellos
  `Número de Cuenta` y `E-mail de Contacto` de `01 SC-COM-02-25`.
- Ningún valor cambia de contenido: lo que se mueve, se mueve de celda.

## Consecuencias

- Lo que solo respalda el LLM y no guarda relación con el campo ya no se escribe; lo dudoso queda marcado
  "Requiere revisión".
- Los encabezados de tabla con caja de captura debajo escriben en esa caja.
- Limitación conocida: A2 no entiende rótulos cuyo campo lo fija el contexto y no el significado (p. ej. "Yo,");
  esos casos dependen de las señales de declaración y de dominio de sección.
