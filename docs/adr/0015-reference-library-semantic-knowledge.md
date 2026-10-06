# ADR 0015: Biblioteca de referencias, búsqueda semántica, familias y few-shot dinámico

**Estado:** Aprobado
**Fecha:** 2026-10-06

## Contexto

El motor mapea cada formulario nuevo con reglas deterministas y un LLM. No aprovechaba los
formularios ya conocidos: cada formulario desconocido arrancaba de cero. Se quiere que cinco (y luego
cientos o miles de) formularios de ejemplo se conviertan en conocimiento consultable, sin enviar
documentos completos al LLM, sin duplicar lo existente (Template Store, alias deterministas, rescate
con FastEmbed, validadores) y sin depender de un proveedor de IA concreto.

## Decisión

Un paquete `reference_library/` agrega solo lo que faltaba y se conecta al pipeline existente:

```
docs/referencias/**/*.xlsx  ->  extractor (stage 1-2 + IR existentes, sin LLM)
   -> base SQLite (config/referencias.db) con el documento de origen de cada conocimiento
   -> embeddings (proveedor intercambiable) -> índice vectorial (numpy)
   -> búsqueda semántica híbrida -> clasificación de familia -> few-shot dinámico
   -> consultar_llm_seccion_instructor (existente) -> validación determinista (sin cambios)
```

- **Fuente de verdad = la carpeta** `docs/referencias` (NO se versiona: el repositorio es público y los
  formularios traen datos reales; ver Consecuencias). La primera
  subcarpeta es la *familia*; `referencias.json` opcional fija familia/fuente/confianza). La base SQLite
  es derivada y se reconstruye sola: `sincronizar()` compara el hash de cada archivo y solo reprocesa lo
  que cambió, retira lo borrado y reprocesa si cambian los datos de la empresa o la versión del extractor.
  El disco de Streamlit Cloud es efímero, así que en la nube las referencias deben cargarse desde el panel
  o desde un almacenamiento persistente (ver Consecuencias).
- **Extracción** (`extractor.py`): por cada rótulo guarda hoja, coordenada, sección, contexto de fila,
  vecinos, ubicación de escritura, ejemplo de valor y campo maestro con su **procedencia y confianza**:
  `plantilla_verificada` (0.95, plan guardado por usuarios), `valor_ejemplo` (valor diligenciado que
  coincide con el perfil, solo si el alias lo confirma o el valor identifica una única clave) y `alias`
  (0.85, resolver determinista existente). Se prioriza precisión: un valor ambiguo o que contradice al
  alias no asigna campo. A diferencia de la etapa 1, una referencia con controles VML se lee igual (no se
  escribe nunca).
- **Vectores**: numpy en memoria detrás de `IndiceVectorial`, con metadatos en SQLite. Para decenas de
  miles de vectores un producto matricial exacto responde en milisegundos, sin dependencias nativas ni
  servicios. FAISS/Chroma/Qdrant se descartan por peso o costo a esta escala; pgvector (Supabase) es la
  salida natural si la biblioteca debe compartirse entre despliegues o supera ese tamaño: bastaría otra
  implementación de la interfaz.
- **Embeddings** (`embeddings.py`): `AUTOFORM_EMBEDDING_PROVIDER` = `fastembed` (por defecto, local,
  multilingüe, reutiliza el singleton de `fastembed_matcher`) | `openai` (reutiliza `embedding_engine` y su
  caché) | `hash` (respaldo léxico). Cada vector guarda el nombre del proveedor: cambiar de proveedor
  reindexa, nunca mezcla espacios.
- **Búsqueda** (`search.py`): similitud = 0.5·coseno + 0.5·léxica estricta (Jaccard + orden de tokens;
  se descartó `token_set_ratio` porque iguala "Nombre" con "Nombre legal de la empresa"), más 15 % de
  similitud de sección cuando se conoce. Devuelve campo, documento, ubicación, similitud, contexto e
  información asociada. Es una señal, no la única fuente de verdad.
- **Familias** (`families.py`): sin lista en código (subcarpetas = familias). Puntaje = 0.60 rótulos
  (cobertura + similitud) + 0.25 secciones + 0.15 estructura; probabilidades por softmax. Se asigna una
  familia solo con puntaje >= 0.60, probabilidad >= 0.60 y margen >= 0.05; si no, el formulario es
  desconocido y se usa la búsqueda general. No usa el nombre del archivo.
- **Few-shot** (`fewshot.py`): por lote de rótulos, como máximo `top_k` ejemplos
  (`AUTOFORM_FEWSHOT_TOP_K`, por defecto 5; 0 lo desactiva; `AUTOFORM_FEWSHOT_UMBRAL`, por defecto 0.6),
  priorizando la familia detectada. Solo se usan correspondencias con evidencia real
  (`valor_ejemplo`, `plantilla_verificada`), solo campos que el perfil de la empresa tiene, y se excluyen
  `responsable_*` (reglas propias de ADR-0007/0009). El LLM recibe `"E"` con ejemplos compactos y una nota
  que dice que son guía, no obligación, y que nunca aportan valores ni anulan el aislamiento de dominios.
- **Integración**: etapa 2c del orquestador (clasificación, `ctx.familia_formulario`) y llamada del
  stage 3 al LLM. Ambas son opcionales: con la biblioteca desactivada (`AUTOFORM_REFERENCES_ENABLED=0`),
  vacía o con cualquier fallo el pipeline funciona exactamente como antes. La sincronización corre en un
  hilo al abrir la app.
- **Administración**: panel `ui/page_reference_library.py` (todos ven el estado; solo administradores
  agregan, eliminan y reprocesan) y CLI `python -m reference_library {sync,list,stats,add,remove,reprocess,search,classify}`.

## Consecuencias

- El conocimiento crece agregando archivos a `docs/referencias`, sin tocar código.
- Reconstruir la base al arrancar cuesta tiempo proporcional al número de referencias nuevas (el escáner
  existente tarda unos segundos por formulario grande); por eso corre en segundo plano y es incremental.
- Los formularios de referencia contienen datos reales de la empresa y el repositorio es público: están
  en `.gitignore` y viven solo en la máquina de quien los administra. En la nube la biblioteca arranca
  vacía (el pipeline funciona igual) y se llena desde el panel de administradores, perdiéndose al
  reiniciar. Para persistirla sin exponer datos, el siguiente paso es guardar los archivos o el
  conocimiento en Supabase (Storage/tabla con RLS) detrás de la misma interfaz.
- Limitación conocida: el escáner de celdas descarta rótulos cuyos vecinos derecho y abajo ya están
  llenos, así que en formularios diligenciados parte de los rótulos no se indexa. Un formulario en blanco
  (o una plantilla verificada) rinde más que uno completo.
- Pendiente a futuro: ingerir directamente las plantillas verificadas de `template_store` como
  conocimiento, para que cada formulario verificado en producción enriquezca la biblioteca.
