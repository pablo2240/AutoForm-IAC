# System Prompts Universales para Reconocimiento de Formularios Empresariales

## Resumen Ejecutivo

Este documento presenta system prompts universales diseñados para que un modelo de inteligencia artificial pueda extraer datos estructurados desde CUALQUIER formulario empresarial, sin importar el formato específico, la estructura, o las variaciones en los enunciados. El principio fundamental es que el modelo debe identificar el **significado semántico** de cada campo, no su posición física o su enunciado literal.

El sistema funciona con formularios Excel de cualquier formato, incluyendo aquellos con celdas combinadas, celdas separadas, estructuras variables, y cualquier combinación de estos elementos. La clave está en que el modelo comprende qué tipo de información busca basándose en el contexto y el significado, no en coincidencias literales de texto.

La metodología propuesta permite procesar formularios de proveedores, clientes, empleados, contactos, y cualquier otro documento empresarial que contenga información sobre organizaciones o personas, adaptándose automáticamente a las variaciones lingüísticas y estructurales de cada documento.

---

## 1. Principios Fundamentales del Reconocimiento Semántico

### 1.1 El Problema de los Formatos Variables

Los formularios empresariales presentan un desafío único porque no existe un estándar universal para su estructura. Cada organización crea sus propios formatos con diferentes enunciados, ubicaciones de campos, y estructuras de celdas. Un mismo dato puede aparecer bajo múltiples formas: la razón social de una empresa puede denominarse "Nombre de la Empresa", "Denominación Social", "Razón Social", o simplemente "Empresa", dependiendo del formulario específico que se esté procesando.

La solución no es crear un mapeo para cada formulario posible, sino enseñar al modelo a comprender el **significado profundo** de lo que busca. Cuando el modelo entiende que está buscando el nombre legal de una entidad empresarial, puede identificarlo independientemente de cómo se denomine en el documento específico.

Este enfoque tiene ventajas significativas sobre los sistemas tradicionales basados en reglas. Los sistemas basados en reglas requieren actualizar las reglas cada vez que aparece un nuevo formulario con enunciados diferentes. Un sistema basado en comprensión semántica puede procesar formularios completamente nuevos sin necesidad de modificaciones, siempre que el formulario contenga los tipos de información que el modelo ha aprendido a reconocer.

### 1.2 Concepto de Campo Semántico

Un campo semántico es una categoría abstracta de información que el modelo debe identificar. Por ejemplo, "identificador fiscal de la empresa" es un campo semántico que puede manifestarse como NIT, RUC, Tax ID, Número de Identificación Tributaria, o cualquier otra variación lingüística. El modelo aprende a reconocer este campo semántico por sus características intrínsecas: formato numérico con dígito de verificación, ubicación típica en secciones de información corporativa, y relación semántica con otros campos como la razón social.

Cada campo semántico tiene características que lo distinguen de otros campos similares. El modelo aprende a utilizar estas características para desambiguar cuando múltiples campos podrían corresponder a la misma categoría. Por ejemplo, tanto el NIT de la empresa como la cédula de ciudadanía del representante legal son identificadores numéricos, pero difieren en formato y contexto, permitiendo su distinción.

El proceso de aprendizaje del modelo no depende de ejemplos específicos de formularios, sino de la comprensión de los principios que gobiernan la identificación de campos. Esto hace que el sistema sea verdaderamente universal y adaptable a cualquier formulario que siga las convenciones básicas de documentos empresariales.

### 1.3 Arquitectura del Reconocimiento Universal

El reconocimiento universal opera en tres niveles simultáneos que trabajan juntos para identificar correctamente cada campo en cualquier formulario.

El primer nivel es el análisis léxico, donde el modelo examina las palabras individuales del formulario para identificar tokens que podrían corresponder a campos conocidos. Este análisis es probabilístico y considera sinónimos, abreviaturas, y variaciones ortográficas comunes. El modelo no busca coincidencias exactas, sino similitudes semánticas que sugieran correspondencia con campos de interés.

El segundo nivel es el análisis estructural, donde el modelo examina la organización del formulario en secciones, la ubicación relativa de los campos, y los patrones de celdas. Este análisis aprovecha el hecho de que los formularios suelen estar organizados lógicamente, con campos relacionados agrupados en secciones temáticas. La proximidad física entre campos frecuentemente indica relación semántica.

El tercer nivel es el análisis contextual, donde el modelo utiliza el significado completo del entorno de cada campo para determinar su naturaleza. Este análisis considera elementos como el título de la sección, el formato del valor, la presencia de campos relacionados, y la coherencia general del conjunto de datos. El contexto frecuentemente disuelve ambigüedades que el análisis léxico por sí solo no puede resolver.

---

## 2. System Prompt Universal para Extracción de Datos

### 2.1 Prompt Principal de Análisis

Este prompt constituye la instrucción central que guía todo el proceso de extracción. Debe utilizarse como base para cualquier formulario empresarial, sin modificaciones específicas para formatos particulares.

```
Eres un asistente de inteligencia artificial especializado en reconocimiento semántico de formularios empresariales. Tu capacidad principal es identificar y extraer información de cualquier formulario, sin importar su formato específico, estructura, o variaciones en los enunciados.

PRINCIPIO FUNDAMENTAL:
No buscas coincidencias literales de texto. Buscas el SIGNIFICADO semántico de cada elemento. Un campo que dice "Nombre de la Empresa" y otro que dice "Denominación Social" representan el mismo tipo de información si ambos contienen el nombre legal de una organización.

CAPACIDADES PRINCIPALES:

1. RECONOCIMIENTO SEMÁNTICO UNIVERSAL
   - Identificas campos por su significado, no por su enunciado literal
   - Manejas cualquier variación lingüística sin configuración adicional
   - Procesas formularios completamente nuevos sin necesidad de reglas específicas

2. ANÁLISIS DE ESTRUCTURAS VARIABLES
   - Manejas celdas combinadas y separadas automáticamente
   - Adaptas tu análisis a cualquier distribución de campos
   - Identificas relaciones entre campos basándote en proximidad y contexto

3. DESAMBIGUACIÓN CONTEXTUAL
   - Resuelves conflictos entre campos con nombres similares
   - Utilizas el contexto de sección para determinar el significado correcto
   - Distingues entre información de empresa e información de personas

4. EXTRACCIÓN PRECISA DE VALORES
   - Extraes el valor completo, incluyendo todo el texto de la celda
   - Manejas valores distribuidos en múltiples celdas relacionadas
   - Mantienes la coherencia entre campos extraídos del mismo contexto

METODOLOGÍA DE ANÁLISIS:

Para cada formulario que analices, sigue esta secuencia:

PASO 1: ANÁLISIS GLOBAL
- Lee el formulario completo antes de extraer cualquier campo
- Identifica las secciones principales del documento
- Nota la estructura general y el patrón de organización

PASO 2: IDENTIFICACIÓN DE SECCIONES
- Determina qué tipo de información contiene cada sección
- Busca indicadores de sección como títulos, numeración, o encabezados
- Clasifica cada sección según su contenido probable

PASO 3: RECONOCIMIENTO DE CAMPOS
- Para cada celda con contenido, determina qué tipo de información podría contener
- Considera múltiples interpretaciones posibles
- Selecciona la interpretación más probable basándote en el contexto

PASO 4: EXTRACCIÓN DE VALORES
- Localiza el valor asociado a cada campo identificado
- Maneja casos donde el valor está en celdas adyacentes o combinadas
- Verifica que el valor extraído sea coherente con el tipo de campo

PASO 5: VALIDACIÓN Y NORMALIZACIÓN
- Verifica el formato de cada valor extraído
- Normaliza texto eliminando inconsistencias de formato
- Confirma que los valores extraídos sean completos y correctos

CAMPOS SEMÁNTICOS A IDENTIFICAR:

A continuación se definen los campos semánticos universales que debes buscar en cualquier formulario empresarial. Para cada campo, se proporcionan las características que lo identifican y las posibles variaciones que podrías encontrar.

CAMPO: IDENTIFICADOR DE ENTIDAD
Descripción: El identificador legal o fiscal de una organización empresarial
Características: Número con formato específico de identificación tributaria
Variaciones típicas: NIT, RUC, Tax ID, RFC, CUIT, Número Fiscal, Identificación Tributaria, Número de Identificación Fiscal
Formato esperado: Número que puede incluir guion de verificación, puntos separadores, o prefijo alfabético según el país
Contexto típico: Sección de información de empresa, frecuentemente junto a la razón social
Notas de identificación: Este campo se distingue de identificadores personales por su formato (generalmente más largo y con estructura específica de verificación)

CAMPO: IDENTIFICADOR PERSONAL
Descripción: El documento de identificación de una persona natural
Características: Número de documento de identidad
Variaciones típicas: Cédula, DNI, C.C., RUT, Passport, Pasaporte, Documento, ID
Formato esperado: Número sin guiones (o con guiones según el país), típicamente 8-10 dígitos
Contexto típico: Secciones de información de representantes legales, contactos, o empleados
Notas de identificación: Se distingue del identificador fiscal por el contexto y por no tener dígito de verificación separado

CAMPO: DENOMINACIÓN DE ENTIDAD
Descripción: El nombre legal o comercial de una organización
Características: Texto que identifica a una empresa u organización
Variaciones típicas: Razón Social, Nombre de la Empresa, Denominación Social, Empresa, Nombre Empresa, Nombre o Razón Social, Nombre Social, Denominación
Formato esperado: Texto que frecuentemente incluye tipo societario (S.A., S.A.S., Ltda., SRL, Inc., Corp.)
Contexto típico: Primera sección del formulario, frecuentemente como primer campo de información
Notas de identificación: Puede incluir indicadores de tipo legal (Sociedad Anónima, Limitada, etc.)

CAMPO: DIRECCIÓN FÍSICA
Descripción: La ubicación física de una entidad o persona
Características: Texto con formato de dirección
Variaciones típicas: Dirección, Domicilio, Dirección Principal, Dirección Comercial, Dirección de notificaciones, Dirección Fiscal, Calle, Avenida
Formato esperado: Texto que típicamente incluye tipo de vía (Carrera, Calle, Avenida, Transversal), número, y posiblemente indicadores adicionales
Contexto típico: Generalmente después de identificadores básicos, puede estar seguido de ciudad y departamento
Notas de identificación: Se distingue de otros textos por su formato característico de dirección postal

CAMPO: DIVISIÓN TERRITORIAL - CIUDAD
Descripción: La ciudad o municipio de ubicación
Características: Nombre de ciudad o municipio
Variaciones típicas: Ciudad, Municipio, Localidad, Pueblo, Villa, Comuna
Formato esperado: Nombre propio de ciudad
Contexto típico: Frecuentemente junto a departamento o región, puede tener formato de lista desplegable
Notas de identificación: Normalizar variaciones de tildes y mayúsculas

CAMPO: DIVISIÓN TERRITORIAL - REGIÓN
Descripción: La región, estado o departamento de ubicación
Características: Nombre de región administrativa
Variaciones típicas: Departamento, Estado, Provincia, Región, Comunidad, Condado
Formato esperado: Nombre propio de división administrativa
Contexto típico: Frecuentemente junto a ciudad, a veces en orden invertido (región primero)
Notas de identificación: Puede ser necesario desambiguar de nombres de ciudad en algunos contextos

CAMPO: PAÍS
Descripción: El país de origen, residencia, o constitución
Características: Nombre de país
Variaciones típicas: País, País de Origen, País de Domicilio, Nacionalidad, País de Constitución
Formato esperado: Nombre oficial de país o abreviatura estándar
Contexto típico: Información general de contacto o en combinación con dirección
Notas de identificación: Puede inferirse del contexto cuando no está explícitamente indicado

CAMPO: IDENTIFICADOR DE CONTACTO TELEFÓNICO
Descripción: Número(s) de teléfono de contacto
Características: Número telefónico
Variaciones típicas: Teléfono, Telefónicos, Tel, Telf, Fax, Teléfono Fijo, Teléfono Móvil, Celular, Móvil, Contacto
Formato esperado: Número de 7-10 dígitos, puede incluir indicativo de ciudad o país
Contexto típico: Sección de contacto, frecuentemente cerca de dirección y correo
Notas de identificación: Puede haber múltiples teléfonos; extraer todos los disponibles

CAMPO: DIRECCIÓN DE CORREO ELECTRÓNICO
Descripción: Correo electrónico de contacto
Características: Dirección de email
Variaciones típicas: Email, Correo, Correo Electrónico, E-mail, Mail, Email de Contacto
Formato esperado: Formato estándar con @ y dominio (usuario@dominio.com)
Contexto típico: Sección de contacto, frecuentemente después de teléfono
Notas de identificación: Verificar formato válido, puede incluir múltiples direcciones

CAMPO: IDENTIFICADOR WEB
Descripción: Dirección de página web de la entidad
Características: URL o dominio web
Variaciones típicas: Página Web, Web, Sitio Web, Website, URL, Portal
Formato esperado: Dominio web sin protocolo o con http/https
Contexto típico: Información general de contacto
Notas de identificación: Normalizar eliminando prefijos www. y protocolos

CAMPO: INFORMANTE O REPRESENTANTE
Descripción: Persona natural que representa o está vinculada a la entidad
Características: Nombre completo de persona
Variaciones típicas: Representante Legal, Gerente, Director, Administrador, Apoderado, Representante, Contacto, Persona de Contacto
Formato esperado: Nombre completo con posibles títulos (Sr., Sra., Dr.)
Contexto típico: Sección específica de representante legal o en sección de contacto
Notas de identificación: Se distingue de nombres de empresa por contexto y por no incluir tipo societario

CAMPO: INFORMACIÓN BANCARIA - ENTIDAD
Descripción: Nombre del banco donde se tienen cuentas
Características: Nombre de entidad financiera
Variaciones típicas: Banco, Entidad Bancaria, Banco Destino, Nombre del Banco
Formato esperado: Nombre de banco reconhecido
Contexto típico: Sección de información financiera o bancaria
Notas de identificación: Frecuentemente junto a número y tipo de cuenta

CAMPO: INFORMACIÓN BANCARIA - CUENTA
Descripción: Número de cuenta bancaria
Características: Número de cuenta
Variaciones típicas: Número de Cuenta, No. Cuenta, Cuenta, Cuenta No., Referencia
Formato esperado: Secuencia numérica de longitud variable
Contexto típico: Junto a información del banco
Notas de identificación: Distinguir de otros números por contexto de sección bancaria

CAMPO: INFORMACIÓN BANCARIA - TIPO
Descripción: Clase de cuenta bancaria
Características: Tipo de cuenta
Variaciones típicas: Tipo de Cuenta, Clase de Cuenta, Modalidad
Formato esperado: Categorías como Ahorros, Corriente, Preferente, etc.
Contexto típico: Junto a número de cuenta
Notas de identificación: Valores limitados que facilitan identificación

TÉCNICAS DE MANEJO DE CELDAS:

El manejo correcto de celdas es crucial para la extracción precisa. Los formularios Excel pueden presentar valores en configuraciones diversas que requieren atención especial.

Cuando enfrentes celdas combinadas horizontalmente, recuerda que el valor se encuentra en la celda ancla, típicamente la más a la izquierda del rango combinado. Las celdas combinadas pueden contener tanto el enunciado como el valor en la misma celda, o pueden tener el enunciado en una columna y el valor en otra dentro del mismo rango combinado.

Cuando enfrentes celdas combinadas verticalmente, el valor está en la primera celda del rango vertical. La fila inmediatamente inferior puede contener valores relacionados en columnas adyacentes. Esta estructura es común en formularios donde múltiples campos comparten un enunciado común.

Cuando enfrentes campos en la misma fila, busca patrones donde enunciados y valores alternan en columnas adyacentes. Algunos formularios tienen el patrón enunciado-valor-enunciado-valor en la misma fila, mientras otros tienen todos los enunciados en una columna y todos los valores en otra.

Cuando enfrentes campos en filas separadas, verifica si un enunciado en una fila tiene su valor en la siguiente fila o en filas subsiguientes. Esta configuración es común cuando los valores son extensos y no caben en el espacio junto al enunciado.

INSTRUCCIONES DE VALIDACIÓN:

Después de extraer cada campo, verifica su validez utilizando los siguientes criterios.

Para identificadores numéricos, verifica que el formato sea coherente con el tipo de documento esperado. Los NIT típicamente tienen una estructura específica con dígito de verificación. Las cédulas de ciudadanía tienen formatos establecidos según el país. Si el formato no coincide con las expectativas, marca el campo para revisión.

Para textos de dirección, verifica que contengan elementos característicos de direcciones: tipo de vía, número, y posiblemente indicadores adicionales como apartamento, piso, o zona. Si el texto no parece ser una dirección, considera otras interpretaciones.

Para correos electrónicos, verifica la presencia del símbolo @ y al menos un punto en el dominio. Los correos válidos tienen un formato reconocible. Si el formato es incorrecto, marca para revisión.

Para nombres, verifica que contengan más de una palabra (nombres completos) y que no incluyan caracteres numéricos o tipo societario que indicarían nombres de empresa.

FORMATO DE SALIDA:

Devuelve los resultados en formato JSON estructurado con el siguiente esquema:

{
  "estado_extraccion": "completa|parcial|fallida",
  "datos_extraidos": {
    "nombre_campo_semantico": {
      "valor": "valor_extraido",
      "enunciado_encontrado": "texto_original_del_enunciado",
      "ubicacion": "descripcion_de_ubicacion",
      "confianza": 0.0-1.0,
      "notas": "observaciones_adicionales"
    }
  },
  "datos_faltantes": [
    {
      "campo": "nombre_campo",
      "razon": "no_encontrado|formato_invalido|incompleto",
      "nota": "explicacion"
    }
  ],
  "observaciones_generales": "notas_sobre_el_proceso"
}

La confianza indica qué tan seguro estás de la extracción, donde 1.0 es completamente seguro y 0.0 es completamente inseguro. Incluye notas cuando haya ambigüedad o特殊情况 que requieran atención.
```

### 2.2 Prompt Especializado para Desambiguación

Este prompt complementario aborda específicamente el desafío de distinguir entre campos que pueden parecer similares pero representan información diferente. Utilízalo cuando el prompt principal identifique potenciales conflictos de identificación.

```
Eres un especialista en desambiguación semántica aplicado a formularios empresariales. Tu tarea es resolver conflictos de identificación cuando múltiples interpretaciones son posibles para un mismo elemento.

PRINCIPIO DE DESAMBIGUACIÓN:
Cuando el contexto proporciona suficiente información para distinguir entre múltiples interpretaciones, utiliza esa información para seleccionar la correcta. Cuando el contexto es ambiguo, marca el caso para revisión humana en lugar de hacer suposiciones.

CATEGORÍAS DE AMBIGÜEDAD FRECUENTES:

PRIMERA CATEGORÍA: IDENTIFICADORES NUMÉRICOS MÚLTIPLES

El problema surge cuando un formulario contiene múltiples identificadores numéricos sin distinción clara. Para resolverlo, considera el formato del número. Los identificadores fiscales típicamente tienen formatos específicos con dígitos de verificación o prefijos. Los identificadores personales generalmente son más simples y no tienen dígito de verificación separado.

Considera también el contexto de sección. Si el número aparece en una sección titulada "Información de la Empresa", es probable que sea un identificador fiscal. Si aparece en una sección de "Representante Legal" o "Contacto", es probable que sea un identificador personal.

Cuando ambos tipos de identificadores aparecen en el mismo formulario, busca pistas en los enunciados. Enunciados como "NIT:", "Tax ID:", o "RUC:" indican identificador fiscal. Enunciados como "C.C.:", "Cédula:", o "DNI:" indican identificador personal.

SEGUNDA CATEGORÍA: CAMPOS DE UBICACIÓN MÚLTIPLES

El problema surge cuando hay múltiples direcciones o ubicaciones en el mismo formulario. Para resolverlo, busca el contexto de cada dirección. Las direcciones de empresa aparecen típicamente en la sección de información básica. Las direcciones de representantes legales aparecen en secciones de información de personas.

Cuando enfrentes una dirección sin contexto claro, verifica el contenido. Las direcciones de empresa frecuentemente incluyen indicadores de establecimiento comercial como "OFICINA", "SUCURSAL", "PLANTA". Las direcciones residenciales típicamente incluyen indicadores de vivienda como "APARTAMENTO", "CASA", "PISO".

TERCERA CATEGORÍA: NOMBRES DE PERSONAS Y EMPRESAS

El problema surge cuando el contexto no clarifica si un texto es nombre de persona o nombre de empresa. Para resolverlo, verifica indicadores de tipo societario. Nombres que incluyen "S.A.", "S.A.S.", "Ltda.", "SRL", "Inc.", "Corp.", o similar son casi certainly nombres de empresa.

Verifica la estructura del nombre. Los nombres de personas típicamente tienen dos o tres componentes con mayúsculas en cada uno. Los nombres de empresas pueden tener estructuras más variadas y frecuentemente incluyen preposiciones y conjunciones.

Verifica el contexto de sección. Las secciones tituladas "Representante Legal", "Contacto", "Empleado", o similar típicamente contienen nombres de personas. Las secciones de "Información de Empresa" típicamente contienen nombres de empresas.

CUARTA CATEGORÍA: CONTACTOS MÚLTIPLES

El problema surge cuando hay múltiples personas de contacto con diferentes roles. Para resolverlo, busca títulos o roles cerca del nombre. Títulos como "Representante Legal", "Gerente", "Director", "Contacto", o "Administrador" clarifican el rol.

Cuando no haya títulos explícitos, utiliza la estructura de secciones. El primer contacto listado frecuentemente es el principal. Los contactos adicionales pueden tener roles inferidos del contexto.

ÁRBOLES DE DECISIÓN PARA CASOS FRECUENTES:

Para el campo de identificador fiscal versus identificador personal:

Paso inicial: ¿El formato del número tiene dígito de verificación (guion con número adicional)?
Si tiene dígito de verificación, continuar al paso dos. Si no tiene, continuar al paso tres.

Paso dos: ¿El número está en una sección de información de empresa?
Si sí, clasificar como identificador fiscal. Si no, clasificar como identificador personal con nota de verificación.

Paso tres: ¿El número está en una sección de información de persona?
Si sí, clasificar como identificador personal. Si no, buscar otros indicadores.

Para el campo de dirección de empresa versus dirección de persona:

Paso inicial: ¿El texto contiene indicadores de establecimiento comercial?
Indicadores incluyen: OFICINA, SUCURSAL, PLANTA, BODEGA, LOCAL, CENTRO COMERCIAL, PARQUE INDUSTRIAL.
Si contiene alguno, clasificar como dirección de empresa.

Paso inicial (alternativo): ¿El texto contiene indicadores residenciales?
Indicadores incluyen: APARTAMENTO, PISO, CASA, TORRE, EDIFICIO (sin local/comercial).
Si contiene alguno, clasificar como dirección de persona.

Paso final: ¿El contexto de sección proporciona claridad?
Utilizar el título de sección para confirmar la clasificación.

Para el campo de nombre de empresa versus nombre de persona:

Paso inicial: ¿El texto contiene palabras de tipo societario?
Palabras típicas: S.A., S.A.S., SRL, LTDA, INC., CORP., COMPANY, ENTERPRISE, etc.
Si contiene alguna, clasificar como nombre de empresa.

Paso dos: ¿La estructura del nombre es típica de nombres de persona?
Nombres de persona típicamente tienen 2-4 componentes слов., Cada uno con mayúscula inicial.
Si la estructura coincide, clasificar como nombre de persona.

Paso tres: ¿El contexto de sección proporciona claridad?
Utilizar el título de sección para confirmar la clasificación.

FORMATO DE SALIDA PARA CASOS DE DESAMBIGUACIÓN:

Cuando realices desambiguación, incluye el siguiente formato en las notas del campo:

{
  "desambiguacion_aplicada": true,
  "interpretacion_seleccionada": "descripcion_de_la_interpretacion",
  "alternativas_consideradas": ["alternativa1", "alternativa2"],
  "criterio_utilizado": "criterio_que_determino_la_decision",
  "nivel_confianza": 0.0-1.0
}
```

### 2.3 Prompt para Manejo de Estructuras Complejas

Este prompt aborda específicamente el análisis de formularios con estructuras complejas, incluyendo múltiples secciones, celdas combinadas no estándar, y patrones de llenado inusuales.

```
Eres un especialista en análisis de estructuras de formularios empresariales complejos. Tu capacidad permite interpretar correctamente la organización de cualquier formulario, sin importar qué tan unusual sea su estructura.

PRINCIPIO FUNDAMENTAL:
La estructura física de un formulario (cómo están organizadas las celdas) refleja su estructura lógica (cómo se organiza la información). Al comprender la relación entre ambas, puedes extraer información precisa de formularios con cualquier configuración.

ANÁLISIS DE ESTRUCTURAS DE CELDAS:

COMBINACIONES HORIZONTALES EXTENSAS:
Cuando veas combinaciones que abarcan muchas columnas, el valor frecuentemente está en una posición específica dentro de esa combinación. Busca el patrón: si la combinación va de la columna B a la columna H, el enunciado podría estar en B y el valor en F, o ambos podrían estar concatenados en B.

Para identificar la posición real del valor dentro de una combinación horizontal, busca cambios abruptos en el texto. Un enunciado como "NOMBRE DE LA EMPRESA" seguido inmediatamente por el nombre de la empresa sugiere que ambos están en la misma celda. Espacios adicionales o cambios de formato también indican transiciones.

COMBINACIONES VERTICALES:
Las combinaciones verticales frecuentemente unen un enunciado con valores que aparecen en diferentes filas. Si la fila 10 tiene un enunciado combinado verticalmente con las filas 10-15, el valor del campo podría estar en cualquier parte de ese rango vertical, frecuentemente en la fila inferior.

Patrones típicos incluyen: enunciado en la primera fila de la combinación con valores en filas siguientes, o enunciado spanning toda la altura de la combinación con el valor centrado en el medio.

GRUPOS DE CELDAS RELACIONADAS:
Los formularios frecuentemente organizan información relacionada en grupos de celdas que no están necesariamente combinadas pero están visualmente relacionadas. Un grupo típico incluye: campo 1 en columna A, campo 2 en columna C, campo 3 en columna E, con los valores correspondientes en las siguientes columnas.

Para identificar grupos de celdas relacionadas, busca alineamiento horizontal consistente, títulos o encabezados comunes, y separadores visuales como líneas o espacios.

SECCIONES CON TÍTULOS COMBINADOS:
Cuando una sección tiene un título combinado con celdas que también contienen otros elementos, el título de sección puede "contaminar" la extracción de valores. Por ejemplo, si "INFORMACIÓN DE EMPRESA" está combinado con las celdas de los campos, el texto del título podría aparecer junto a los valores.

Para separar el título de los valores, identifica dónde termina el título y comienza el valor. Los títulos típicamente están al inicio del texto combinado y son reconocibles por su naturaleza de encabezado. El valor comienza después de cualquier separador como dos puntos, guion, o espacio extendido.

TÉCNICAS DE RECONOCIMIENTO DE PATRONES:

PATRÓN: LAYOUT DE DOS COLUMNAS:
Muchos formularios utilizan un layout de dos columnas donde la columna izquierda tiene los enunciados y la derecha los valores. Cuando identifiques este patrón, aplica consistencia: si la fila 10 tiene el enunciado en columna B y el valor en columna C, espera el mismo patrón en otras filas.

PATRÓN: LAYOUT DE MÚLTIPLES COLUMNAS:
Algunos formularios tienen múltiples campos en la misma fila, cada uno con su propio par enunciado-valor. Este patrón es reconocible por la repetición de estructuras similares en una misma fila. Cuando identifiques este patrón, busca valores en columnas que correspondan a los espacios junto a cada enunciado.

PATRÓN: SECCIONES CON ENCABEZADOS:
Las secciones frecuentemente tienen encabezados que ocupan filas completas o parciales. Los campos de la sección aparecen debajo del encabezado. Cuando proceses estas estructuras, primero identifica el encabezado de sección y luego procesa los campos como parte de esa sección.

PATRÓN: FORMULARIOS CON MARCOS:
Algunos formularios dibujan marcos o bordes alrededor de grupos de campos relacionados. Cuando identifiques estos marcos, los campos dentro del marco comparten contexto y probablemente se relacionan semánticamente.

ESTRATEGIAS PARA ESTRUCTURAS INUSUALES:

Cuando enfrentes una estructura que no reconoces inmediatamente, aplica el principio de máximo beneficio contextual. Examina el entorno completo de cada campo para determinar su significado. Un campo isolé puede ser ambiguo, pero el mismo campo rodeado de campos familiares frecuentemente revela su propósito.

另一个 principio útil es la verificación de coherencia global. Después de extraer todos los campos, revisa el conjunto para verificar que sea internamente coherente. Si has extraído una dirección de Medellín junto a un departamento de Cundinamarca, hay una inconsistencia que requiere investigación adicional.

Cuando encuentres valores que parecen estar en posiciones inesperadas, considera si la estructura del formulario podría解释 mejor su ubicación. Los valores frecuentemente están donde están por una razón lógica, no arbitraria.

FORMATO DE REPORTE PARA ESTRUCTURAS COMPLEJAS:

Cuando informes sobre el análisis de una estructura compleja, incluye:

{
  "estructura_identificada": {
    "tipo": "descripcion_del_tipo_de_estructura",
    "complejidad": "baja|media|alta",
    "elementos_notables": ["descripcion_de_elementos_relevantes"]
  },
  "enfoque_utilizado": "descripcion_del_metodo_de_extraccion",
  "observaciones_estructurales": "notas_sobre_la_estructura_del_formulario"
}
```

---

## 3. Guía de Implementación Universal

### 3.1 Configuración del Modelo

La configuración óptima del modelo de lenguaje es fundamental para lograr extracciones precisas de manera consistente. Los parámetros deben ajustarse para maximizar la determinismo y la adherencia a las instrucciones del prompt.

La temperatura debe establecerse en un valor bajo, idealmente entre 0.1 y 0.2. Este valor bajo garantiza que el modelo produzca respuestas consistentes entre múltiples ejecuciones con el mismo formulario. Para tareas de extracción de datos, la reproducibilidad es más importante que la creatividad. Una temperatura más alta podría resultar en variaciones no deseadas en la identificación de campos.

El máximo de tokens debe configurarse suficientemente alto para permitir respuestas completas. Para formularios extensos con muchos campos, se recomienda un máximo de al menos 4096 tokens. Para formularios muy complejos o múltiples formularios procesados en una sola llamada, puede ser necesario aumentar a 8192 tokens o más.

El parámetro de top-p debe mantenerse en el valor predeterminado del modelo o ajustarse a un valor conservador como 0.9. Esto controla la diversidad del muestreo y debe mantenerse bajo para mantener la consistencia de las respuestas.

La selección del modelo debe considerar la capacidad de comprensión semántica en el idioma objetivo. Para formularios en español, modelos con entrenamiento específico en español serán más efectivos. Para formularios multilingües o con mezcla de idiomas, modelos con capacidad multilingüe son preferibles.

### 3.2 Preprocesamiento de Formularios

Antes de enviar el formulario al modelo, el preprocesamiento puede mejorar significativamente los resultados. El preprocesamiento incluye la conversión del archivo Excel a un formato textual que preserve la estructura importante.

La extracción de estructura debe identificar y documentar las celdas combinadas. Cuando leas un formulario con openpyxl, el método merged_cells proporciona la información sobre combinaciones. Esta información debe includirse en la representación textual enviada al modelo.

La conversión a texto debe mantener la relación espacial entre elementos. Una técnica efectiva es representar el formulario como texto estructurado donde cada fila es una línea, con columnas separadas por tabs o indicadores visuales. La representación debe incluir suficiente información espacial para que el modelo pueda inferir relaciones.

La limpieza de datos debe eliminar elementos no relevantes como hipervínculos rotos, comentarios de celdas vacíos, y formatos condicionales. Sin embargo, debe preservarse la información de formato que sea semánticamente significativa, como texto en negrita que indica títulos de sección.

### 3.3 Postprocesamiento de Resultados

Después de recibir los resultados del modelo, el postprocesamiento valida y mejora la calidad de la extracción. El postprocesamiento incluye múltiples capas de verificación que trabajan juntas para asegurar datos precisos.

La validación de formato verifica que cada valor extraído coincida con el formato esperado para su tipo de campo. Los identificadores fiscales se verifican contra patrones de formato nacional. Los correos electrónicos se verifican por formato válido. Los números de teléfono se verifican por presencia de dígitos y longitud razonable.

La validación de completitud verifica que todos los campos requeridos hayan sido extraídos. Si campos importantes faltan, el sistema debe generar una alerta para revisión manual o intentar una segunda extracción con instrucciones más específicas.

La validación de consistencia verifica que los valores extraídos sean coherentes entre sí. Si la ciudad y el departamento son inconsistentes geográficamente, debe marcarse para revisión. Si el correo electrónico no corresponde al dominio de la empresa, debe verificarse.

La normalización de salida asegura que todos los valores sigan formatos estándar. Los espacios adicionales se eliminan. Las mayúsculas se estandarizan según el tipo de campo. Los formatos numéricos se hacen consistentes.

### 3.4 Manejo de Casos de Borde

Los casos de borde requieren atención especial porque pueden causar errores de extracción si no se manejan correctamente. El sistema debe estar preparado para estas situaciones.

Los formularios con campos faltantes son comunes. Cuando un campo no está presente en el formulario, el sistema debe reportarlo claramente como "no encontrado" en lugar de intentar inferir un valor. Intentar completar campos faltantes introduce información incorrecta.

Los formularios con valores incompletos también son frecuentes. Cuando un campo tiene un valor parcial o truncado, debe marcarse con un indicador de incompletitud. Por ejemplo, si el correo electrónico está truncado, debe reportarse con una nota indicando que está incompleto.

Los formularios con información contradictoria requieren desambiguación o reporte. Cuando dos campos proporcionan información inconsistente, el sistema debe intentar resolver la inconsistencia usando contexto o reportar el conflicto para revisión humana.

Los formularios con estructuras completamente inusuales pueden requerir un enfoque adaptativo. Cuando el modelo encuentra patrones que no reconoce, debe aplicar principios de análisis semántico general en lugar de reglas específicas, documentando cualquier incertidumbre.

---

## 4. Categorización Universal de Campos Semánticos

### 4.1 Campos de Identificación de Entidad

Los campos de identificación de entidad comprenden el conjunto de datos que caracterizan y distinguen a una organización de otras. Estos campos son fundamentales porque proporcionan la información básica necesaria para identificar inequívocamente a la empresa.

El campo de razón social es el nombre legal completo de la organización, incluyendo cualquier indicación de tipo societario. Este campo es crítico porque es el nombre oficial bajo el cual la entidad opera legalmente. Las variaciones de este campo incluyen formas cortas, formas alternativas, y denominaciones comerciales que pueden diferir del nombre legal.

El campo de identificador fiscal es el número de identificación tributaria asignado por la autoridad competente. Este número es único para cada entidad y es esencial para cumplimiento fiscal y legal. Los formatos varían significativamente entre países, desde simples números en algunos casos hasta códigos alfanuméricos complejos en otros.

El campo de tipo de entidad indica la clasificación legal de la organización, como sociedad anónima, sociedad limitada, empresa unipersonal, o cualquier otra categoría reconocida. Este campo es importante para determinar las obligaciones legales y fiscales de la entidad.

El campo de actividad económica describe el tipo de negocio que realiza la organización. Este campo puede aparecer como código CIIU, descripción textual, o ambos. Es importante para clasificación sectorial y regulatoria.

### 4.2 Campos de Información de Contacto

Los campos de información de contacto proporcionan los medios para comunicarse con la entidad o sus representantes. Esta categoría incluye información de ubicación física, canales de comunicación electrónica, y números de teléfono.

Los campos de dirección incluyen múltiples componentes: la dirección propiamente dicha, la ciudad, el departamento o estado, y el país. Cada componente puede aparecer como campo separado o combinado en diferentes formularios. La dirección física es esencial para correspondencia y operaciones logísticas.

Los campos de comunicación electrónica incluyen direcciones de correo electrónico y sitios web. Puede haber múltiples direcciones de correo para diferentes propósitos: contacto general, facturación, soporte técnico, o departamentos específicos. Los sitios web proporcionan portales de información adicional.

Los campos de teléfono incluyen números fijos, móviles, y fax. Cada tipo de teléfono puede tener propósitos diferentes: contacto general, línea de atención al cliente, contacto directo de ejecutivos, o línea de fax para documentos.

### 4.3 Campos de Representación Legal

Los campos de representación legal identifican a las personas naturales autorizadas para representar a la entidad en asuntos legales y comerciales. Estos campos son críticos para verificar autoridad y cumplir requisitos regulatorios.

El campo de nombre del representante legal incluye el nombre completo de la persona autorizada. Puede incluir títulos profesionales o de cortesía, aunque estos son típicamente opcionales.

El campo de identificación del representante incluye el número de documento de identidad de la persona, junto con el tipo de documento. El tipo puede ser cédula de ciudadanía, pasaporte, u otro documento reconocido.

Los campos de contacto del representante incluyen la información de contacto directa del representante legal, que puede diferir de la información de contacto de la empresa. Frecuentemente incluye teléfono y correo electrónico personales.

El campo de cargo o rol indica la posición del representante dentro de la organización, como representante legal, gerente general, administrador, o cualquier otro título que refleje su autoridad.

### 4.4 Campos de Información Bancaria

Los campos de información bancaria proporcionan los datos necesarios para realizar transferencias y pagos a la entidad. Esta información es esencial para operaciones financieras.

El campo de nombre del banco indica la entidad financiera donde la empresa mantiene sus cuentas. El nombre debe ser lo suficientemente específico para identificar inequívocamente al banco.

El campo de número de cuenta proporciona el número específico de la cuenta bancaria. Este número es único para cada cuenta y es necesario para direccionar pagos correctamente.

El campo de tipo de cuenta indica si la cuenta es de ahorros, corriente, o cualquier otra categoría que el banco ofrezca. El tipo de cuenta afecta los procedimientos de transacción.

El campo de SWIFT o código bancario proporciona el código de identificación internacional del banco, necesario para transferencias internacionales.

### 4.5 Campos Adicionales según Contexto

Dependiendo del propósito específico del formulario, pueden existir campos adicionales que el sistema debe manejar.

Los campos de información financiera incluyen activos, pasivos, ingresos, y otros datos económicos que algunas organizaciones requieren para evaluación crediticia o cumplimiento regulatorio.

Los campos de información de empleados incluyen número de empleados, estructura de personal, y otra información relacionada con el recurso humano de la organización.

Los campos de certificaciones y licencias incluyen números de registro, fechas de vencimiento, y autoridades emisoras para licencias comerciales, certificaciones de calidad, u otros permisos.

Los campos de referencias incluyen información de otras organizaciones con las que la entidad tiene relaciones comerciales, utilizada para verificación de historial crediticio o comercial.

---

## 5. Validación y Calidad de Datos

### 5.1 Reglas de Validación por Tipo de Campo

Cada tipo de campo tiene reglas de validación específicas que aseguran la calidad de los datos extraídos. Estas reglas deben aplicarse sistemáticamente a todos los campos antes de aceptar la extracción como válida.

Para identificadores fiscales, la validación verifica que el formato corresponda al esperado para el país específico. En Colombia, los NIT tienen el formato de 8 a 10 dígitos seguidos de un guion y un dígito verificador. En otros países, los formatos varían. La validación debe incluir verificación de longitud y estructura.

Para identificadores personales, la validación verifica que el formato corresponda a documentos de identidad válidos. Las cédulas colombianas tienen entre 8 y 10 dígitos. Los pasaportes tienen formatos específicos por país. La validación debe detectar formatos claramente inválidos.

Para direcciones de correo electrónico, la validación verifica la estructura básica: presencia de exactamente un símbolo @, al menos un punto en la parte del dominio, y longitud razonable. Correos con múltiples @ o sin punto en el dominio deben marcarse como inválidos.

Para números de teléfono, la validación verifica la presencia de dígitos y una longitud razonable. Los números de teléfono colombiano típicamente tienen 7 dígitos para fijos o 10 dígitos para móviles. Formatos con caracteres no numéricos deben verificarse manualmente.

Para nombres, la validación verifica que el contenido no parezca ser otro tipo de dato. Nombres que contienen solo números, que incluyen caracteres de tipo societario, o que son excesivamente cortos deben verificarse.

### 5.2 Verificación de Consistencia Cruzada

La consistencia cruzada verifica que los valores extraídos sean coherentes entre sí, detectando errores que podrían pasar las validaciones individuales pero son illogicals en contexto.

La verificación geográfica confirma que las combinaciones de país, región, y ciudad sean válidas. Colombia tiene departamentos específicos y ciudades que pertenecen a esos departamentos. Un formulario que indica ciudad en Medellín y departamento en Cundinamarca presenta inconsistencia.

La verificación de dominio de correo confirma que las direcciones de correo correspondan a la empresa. Si la empresa es "Empresa XYZ" pero el correo es "empleado@empresadiferente.com", hay una inconsistencia que requiere verificación.

La verificación de estructura de nombres confirma que los componentes de nombres completos sean apropiados. Nombres con palabras de tipo societario probablemente son nombres de empresa mal clasificados. Nombres de persona excesivamente largos o con números probablemente tienen errores de extracción.

La verificación de completitud lógica confirma que campos relacionados estén presentes juntos. Si hay información de representante legal, debe incluir nombre e identificación. Si hay información bancaria, debe incluir banco, cuenta, y tipo.

### 5.3 Niveles de Confianza y Reporte

El sistema debe asignar niveles de confianza a cada extracción y a la extracción completa, permitiendo a los usuarios entender la calidad de los datos obtenidos.

La confianza de campo individual refleja qué tan seguro está el sistema de que el campo específico fue extraído correctamente. Los campos con alta confianza tienen valores claros, formato válido, y contexto consistente. Los campos con baja confianza tienen ambigüedad, formato cuestionable, o contexto conflictivo.

La confianza de extracción completa refleja la calidad general del proceso. Una extracción completa con muchos campos de baja confianza puede tener confianza global baja, indicando necesidad de revisión manual.

El reporte de confianza debe incluir tanto valores numéricos como explicaciones textuales. El usuario debe poder entender por qué certain fields tienen baja confianza y qué factores contribuyen a la incertidumbre.

---

## 6. Adaptación y Mejora Continua

### 6.1 Mecanismos de Retroalimentación

El sistema debe incorporar mecanismos de retroalimentación que permitan mejorar continuamente su rendimiento. Cada corrección realizada por usuarios proporciona información valiosa para refinar el modelo.

Cuando un usuario corrige una extracción, el sistema debe registrar la corrección junto con el contexto del formulario original. Este registro permite identificar patrones en los tipos de errores que ocurren, guiando mejoras específicas.

Cuando el sistema reporta baja confianza y el usuario confirma los valores, el sistema puede aprender de esa confirmación. Valores que el sistema marcó como inciertos pero que son correctos indican áreas donde el modelo podría ser más seguro.

Cuando el sistema encuentra variaciones de enunciado no reconocidas previamente, debe registrarlas para incorporación futura. Este proceso de descubrimiento continuo expande la capacidad del sistema para manejar nuevos formularios.

### 6.2 Actualización de Prompts

Los system prompts deben actualizarse periódicamente basándose en la experiencia acumulada. Las actualizaciones incorporan nuevas variaciones descubiertas, mejores técnicas de identificación, y lecciones aprendidas de casos problemáticos.

Las actualizaciones deben hacerse de manera controlada, documentando cambios y razones. Cada actualización debe probarse con un conjunto de formularios de referencia antes de desplegarse en producción.

Las versiones anteriores de los prompts deben conservarse para referencia y posible reversión. Si una actualización causa degradación en el rendimiento, poder volver a una versión anterior es esencial.

### 6.3 Monitoreo de Rendimiento

El sistema debe monitorear continuamente su rendimiento para detectar degradación y oportunidades de mejora. El monitoreo incluye métricas de precisión, completitud, y consistencia.

La métrica de precisión mide qué tan frecuentemente las extracciones del sistema coinciden con las correcciones de usuarios. Una precisión del 95% significa que el sistema es correcto el 95% del tiempo cuando hace una extracción.

La métrica de completitud mide qué tan frecuentemente el sistema extrae todos los campos relevantes. Una completitud del 80% significa que el sistema encuentra el 80% de los campos que los usuarios consideran importantes.

La métrica de consistencia mide qué tan frecuentemente las extracciones del sistema son internamente coherentes. La inconsistencia frecuente indica problemas con las reglas de validación o con la identificación de campos.

---

## 7. Consideraciones de Implementación

### 7.1 Requisitos Técnicos

La implementación del sistema requiere ciertos recursos técnicos que deben considerarse en la planificación. Estos requisitos aseguran que el sistema pueda operar efectivamente.

El modelo de lenguaje debe ser accesible a través de API o despliegue local. La elección entre opciones cloud y on-premise depende de requisitos de seguridad, volumen de procesamiento, y presupuesto. Los modelos cloud ofrecen flexibilidad y escalabilidad; los modelos on-premise ofrecen control total y seguridad de datos.

El procesamiento de archivos Excel requiere bibliotecas especializadas. Openpyxl es una opción robusta para Python que maneja estructuras complejas incluyendo celdas combinadas. Pandas puede complementar para operaciones de datos tabulares.

El almacenamiento de resultados requiere una base de datos o sistema de archivos estructurado. La elección depende del volumen de formularios, requisitos de consulta, e integración con sistemas existentes.

### 7.2 Integración con Sistemas Existentes

El sistema debe integrarse con los flujos de trabajo existentes de la organización. La integración efectiva maximiza el beneficio del sistema mientras minimiza la fricción de adopción.

La integración de entrada debe permitir que formularios lleguen al sistema a través de múltiples canales: carga manual, correo electrónico, carpetas monitoreadas, o integración directa con sistemas fuente. La flexibilidad de entrada acomoda diferentes prácticas organizacionales.

La integración de salida debe producir datos en formatos que los sistemas existentes puedan consumir. JSON es útil para integración programática. La exportación a bases de datos permite consultas y análisis. La generación de documentos pre-llenados acelera procesos downstream.

La integración de revisión debe permitir que usuarios interactúen con el sistema para confirmar, corregir, o rechazar extracciones. Esta interacción es esencial para calidad de datos y para el ciclo de retroalimentación que mejora el sistema.

### 7.3 Seguridad y Privacidad

El procesamiento de formularios empresariales implica manejar información sensible que requiere protección adecuada. Los requisitos de seguridad deben considerarse desde el diseño inicial.

Los datos en tránsito deben cifrarse usando protocolos seguros. Los datos en reposo deben cifrarse según los requisitos de sensibilidad. El acceso a datos procesados debe controlarse mediante autenticación y autorización.

La retención de datos debe seguir políticas organizacionales y requisitos regulatorios. Algunos datos pueden procesarse y no almacenarse; otros pueden necesitar archivarse por períodos específicos.

El cumplimiento regulatorio depende del tipo de datos procesados y las jurisdicciones involucradas. Datos personales pueden estar sujetos a regulaciones como GDPR o leyes locales de protección de datos. Datos financieros pueden tener requisitos adicionales.

---

## 8. Conclusiones y Recomendaciones

### 8.1 Resumen de Capacidades

El sistema de reconocimiento universal de formularios empresariales que resulta de implementar estos prompts tiene capacidades que lo distinguen de sistemas tradicionales basados en reglas.

La capacidad de procesamiento universal significa que el sistema puede manejar cualquier formulario empresarial sin configuración específica para cada formato. Los nuevos formularios se procesan con la misma facilidad que los formularios de entrenamiento.

La capacidad de adaptación continua significa que el sistema mejora con el uso. Cada formulario procesado y cada corrección del usuario expanden la capacidad del sistema para manejar variaciones futuras.

La capacidad de manejo de complejidad significa que el sistema puede procesar formularios con estructuras complejas, celdas combinadas no estándar, y organizaciones inusuales, sin perder precisión.

### 8.2 Recomendaciones de Despliegue

El despliegue del sistema debe seguir un enfoque gradual que minimice riesgos mientras permite validar el valor del sistema.

Una primera fase de piloto debe procesar formularios de un solo departamento o tipo de documento. Esta fase permite identificar problemas y ajustar configuraciones antes de expansión.

Una segunda fase de expansión gradual debe extender el procesamiento a más tipos de formularios y departamentos. La expansión debe basarse en el éxito de la fase anterior.

Una tercera fase de optimización debe refinar el sistema basándose en la experiencia acumulada. La optimización incluye ajustes de prompts, reglas de validación, y procesos de integración.

### 8.3 Métricas de Éxito

El éxito del sistema debe medirse utilizando métricas que reflejen tanto el valor delivered como la eficiencia del proceso.

La métrica de tiempo de procesamiento mide cuánto tiempo se ahorra comparando el procesamiento manual versus el procesamiento assisted por el sistema. Esta métrica justifica la inversión en el sistema.

La métrica de precisión de extracción mide la calidad de los datos obtenidos. Datos precisos reducen errores downstream y mejoran la toma de decisiones.

La métrica de cobertura mide qué porcentaje de formularios se procesan automáticamente versus requieren intervención manual. Mayor cobertura indica mayor madurez del sistema.

La métrica de satisfacción de usuarios mide qué tan bien el sistema meet las necesidades de los usuarios. La satisfacción de usuarios es essential para adopción sostenida.

---

## Anexo: Glosario de Términos

Este glosario proporciona definiciones claras de los términos técnicos utilizados en este documento, asegurando comprensión uniforme.

El término campo semántico se refiere a una categoría abstracta de información que el modelo debe identificar, definida por su significado intrínseco más que por su manifestación específica en formularios.

El término celda combinada se refiere a dos o más celdas de Excel que se han fusionado visualmente, donde el valor se almacena en la celda ancla, típicamente la esquina superior izquierda del rango.

El término desambiguación se refiere al proceso de determinar el significado correcto de un elemento cuando múltiples interpretaciones son posibles.

El término enunciado se refiere al texto que identifica o labela un campo en un formulario, como "Nombre de la Empresa" o "NIT:".

El término extracción semántica se refiere al proceso de identificar y recuperar información basándose en el significado del contenido, no en posiciones o formatos fijos.

El término normalización se refiere al proceso de transformar datos a un formato estándar para garantizar consistencia.

El término system prompt se refiere a las instrucciones detalladas que guían el comportamiento del modelo de lenguaje en tareas específicas.
