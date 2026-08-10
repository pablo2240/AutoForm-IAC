# AGENTS.md - Guía para Agentes IA (AutoForm AI)

Bienvenido, Agente IA. Este documento contiene el contexto, estructura y las reglas estrictas que **DEBES** seguir al trabajar en el proyecto **AutoForm AI**.

---

## 🎯 1. Objetivo y Contexto del Proyecto
**AutoForm AI** es una plataforma inteligente desarrollada para IAC Latam. Su objetivo es el diligenciamiento automático de formularios oficiales corporativos (ej. formatos de vinculación, SAGRILAFT, formatos bancarios en Excel) a partir de un perfil de empresa centralizado.
El sistema lee la plantilla de Excel, extrae su estructura, envía los datos a un modelo de IA (LLM como Gemini/OpenAI) para que haga el mapeo cognitivo, y luego inyecta los datos de vuelta en el Excel conservando estrictamente los estilos, fórmulas y diseño original.

---

## 📁 2. Estructura Principal de Carpetas
El proyecto sigue una arquitectura modular separando el frontend web de la lógica de procesamiento central:

- `app1.py`: Punto de entrada de la aplicación Frontend interactiva construida con Streamlit.
- `core/`: Contiene toda la lógica de negocio y procesamiento interno.
  - `excel_parser.py`: Escaneo y lectura de plantillas Excel (celdas, ubicaciones, casillas de verificación, ray-casting).
  - `excel_writer.py`: Escritura segura de datos en Excel protegiendo estilos y mitigando daños en celdas combinadas.
  - `mapper.py`: Lógica de integración, validaciones, caché semántico y heurísticas para unir los datos con las coordenadas.
  - `llm_client.py`: Clientes de IA, inyección de prompts y reglas estrictas del sistema (STRICT_SYSTEM_PROMPT).
  - `schema_models.py`: Modelos Pydantic V2 para la validación estricta de las salidas del LLM.
  - `semantic_cache.py`: Sistema de caché usando similaridad difusa (rapidfuzz) para evitar llamadas redundantes a la API.
  - `profile_manager.py`: Gestión y carga de perfiles empresariales desde JSON.
- `config/`: Almacenamiento local (ej. base de datos en JSON de perfiles y caché semántico).
- `docs/` y `doc/`: Especificaciones de diseño, guías de arquitectura y documentación técnica.
- `.agents/`: Almacén de skills (habilidades) instaladas para los agentes IA (ej. brainstorming, code-optimizer).

---

## 🛠️ 3. Tecnologías y Versiones Utilizadas
- **Lenguaje:** Python 3 (preferiblemente 3.10+)
- **Frontend UI:** `streamlit` (>=1.36.0)
- **Manipulación de Excel:** `openpyxl` (>=3.1.2)
- **Validación y Tipado:** `pydantic` (>=2.7.0, versión V2)
- **Modelos IA / LLM:** `google-genai` (>=2.0.0), `openai`
- **Utilidades Adicionales:** `python-dotenv`, `rapidfuzz` (para caché semántico)

---

## 💻 4. Convenciones de Código
- **Tipado estricto:** Usa *Type Hints* en todas las definiciones de funciones y métodos (ej. `def funcion(param: str) -> List[Dict[str, Any]]:`).
- **Nomenclatura:**
  - Variables y funciones: `snake_case`.
  - Funciones internas/privadas de un módulo deben empezar con un guion bajo: `_funcion_privada()`.
  - Clases: `PascalCase`.
  - Constantes: `UPPER_SNAKE_CASE` (ej. `_CAMPOS_REQUIEREN_MERGE`).
- **Documentación:** Agrega `docstrings` descriptivos a funciones complejas explicando el propósito de la lógica.
- **Manejo de Errores:** Evita supresiones silenciosas. En flujos críticos de archivos (Excel), asegura el manejo adecuado de excepciones como `ValueError` o `AttributeError`.

---

## ⚠️ 5. Reglas de Seguridad (¡CRÍTICO!)
- 🚫 **NUNCA** modifiques, expongas ni subas al repositorio los archivos que contengan secretos, contraseñas o tokens (ej. el archivo `.env`, archivos de configuración locales que contengan API Keys).
- 🚫 **NO MODIFIQUES** los archivos con credenciales bajo ninguna circunstancia a menos que se te indique crear una plantilla base (ej. `.env.example`).
- Evita dejar credenciales "harcodeadas" (en texto plano) en el código fuente. Lee siempre desde variables de entorno.

---

## 🤖 6. Reglas de Comportamiento del Agente IA (Flujo de Trabajo)

1. **Investigar antes de actuar:** No asumas cómo funciona algo; lee los archivos reales, busca en las clases y comprende la lógica antes de proponer código. Usa habilidades como `brainstorming` cuando haya ambigüedad.
2. **Planes para cambios grandes:** Si la solicitud del usuario implica un rediseño de arquitectura o un cambio de lógica profundo (Planning Mode), **PRIMERO** genera un plan (`implementation_plan.md`), explica el enfoque y **ESPERA** la confirmación/aprobación del usuario antes de empezar a escribir código o modificar archivos.
3. **Cambios pequeños directos:** Para arreglos sintácticos, bugs aislados o tareas obvias y pequeñas, puedes ejecutar el cambio directamente sin crear un plan.
4. **Reporte posterior al cambio:** Cada vez que termines un turno modificando código, debes indicarle claramente al usuario:
   - Los archivos que modificaste.
   - El propósito de los cambios.
   - Si corriste algún test o prueba de compilación de sintaxis (y si el resultado fue exitoso).
5. **Verificación local:** Siempre que edites código en Python, ejecuta comandos de validación (por ejemplo, `python -m py_compile archivo.py` o scripts unitarios simples si existen) para asegurar que no hayas introducido errores de sintaxis o indentación antes de reportar el éxito al usuario.

---

## 🚀 7. Cómo Ejecutar el Proyecto y las Pruebas
- **Entorno Virtual:** Asegúrate de correr los comandos usando el entorno virtual de Python activo (ej. `.\venv\Scripts\python.exe` en Windows).
- **Ejecutar Frontend:**
  ```bash
  streamlit run app1.py
  ```
- **Pruebas y Scripts Temporales:** Históricamente, las pruebas unitarias y comprobaciones aisladas del proyecto se ejecutan directamente en la carpeta `scratch/` usando Python puro.
  ```bash
  python scratch/test_alguna_funcionalidad.py
  ```
