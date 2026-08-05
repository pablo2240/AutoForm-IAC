# 📄 AutoForm AI — Llenado Automático de Formularios Corporativos

**AutoForm AI** es una solución web que permite automatizar el diligenciamiento de formularios de proveedores (Excel y PDF). A través del análisis de estructura y el uso de **LLMs (Gemini vía OpenRouter)**, la aplicación identifica celdas y campos vacíos, mapea las etiquetas canónicas de la empresa y genera el archivo final completado conservando el formato original.

## 🎯 Objetivos del Proyecto

- **Eliminar el trabajo manual:** Evitar la copia y pega repetitiva de datos corporativos (NIT, Razón Social, Cuentas, Representante Legal, etc.) en formularios de terceros.
- **Respetar la maquetación original:** Escribir directamente en celdas de Excel o capas de PDF sin alterar estilos, bordes o combinaciones preexistentes.
- **Uso sin barreras técnicas:** Proveer una interfaz sencilla en la web donde cualquier persona del equipo pueda subir el archivo y descargarlo terminado en segundos.
- **Inferencia Inteligente:** Emplear modelos avanzados como **Google Gemini 2.0 / 2.5 Flash** mediante **OpenRouter** para interpretar la disposición espacial (*reglas de contigüidad, vecinos y jerarquía visual*) de los rótulos.

## 🗂️ Estructura del Proyecto

```text
autoform-ai/
├── .env.example                # Plantilla de variables de entorno (API Keys)
├── .gitignore                  # Archivos excluidos de Git
├── README.md                   # Documentación principal del proyecto
├── requirements.txt            # Dependencias de Python
├── config/
│   └── datos_empresa.json      # Base de conocimiento fija de la empresa
├── core/
│   ├── __init__.py
│   ├── excel_parser.py         # Módulo de lectura de celdas/vecinos (openpyxl)
│   ├── excel_writer.py         # Módulo de escritura segura en Excel
│   ├── pdf_processor.py        # Módulo de extracción y superposición en PDF
│   └── llm_client.py           # Cliente OpenRouter para invocar Gemini
└── app.py                      # Interfaz gráfica principal en Streamlit
```

## 🚀 Puesta en Marcha

1. Clona el repositorio y entra en la carpeta:
   ```bash
   cd autoform-ai
   ```

2. Crea y activa un entorno virtual:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate   # Windows
   source venv/bin/activate  # macOS/Linux
   ```

3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

4. Configura las variables de entorno:
   ```bash
   copy .env.example .env   # Windows
   # cp .env.example .env   # macOS/Linux
   ```
   Edita `.env` y coloca tu `OPENROUTER_API_KEY`.

5. Ejecuta la aplicación:
   ```bash
   streamlit run app.py
   ```

6. Abre la URL que muestra Streamlit (normalmente `http://localhost:8501`).

## 🧠 Flujo Interno

1. **Carga:** El usuario sube un archivo `.xlsx` o `.pdf`.
2. **Análisis:** `core/excel_parser.py` escanea celdas vacías y sus vecinos; `core/pdf_processor.py` extrae posiciones del PDF.
3. **Inferencia:** `core/llm_client.py` envía la estructura al LLM (Gemini vía OpenRouter) que mapea las etiquetas canónicas de `config/datos_empresa.json`.
4. **Escritura:** `core/excel_writer.py` / `core/pdf_processor.py` escriben los valores conservando el formato original.
5. **Descarga:** El archivo completado se ofrece para descarga.

## 🛠️ Personalización

Edita `config/datos_empresa.json` con los datos fijos de tu empresa y sus etiquetas canónicas (NIT, Razón Social, Representante Legal, cuentas bancarias, etc.).

---

Documentación principal del proyecto **AutoForm AI**.
