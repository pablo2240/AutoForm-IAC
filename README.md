# 📄 AutoForm AI — Llenado Automático de Formularios Corporativos

<p align="center">
  <img src="assets/logo.png" alt="AutoForm AI Logo" width="220" />
</p>

<p align="center">
  <strong>Solución inteligente de alta precisión para el diligenciamiento automático de formularios corporativos (Excel y PDF) preservando el 100% de formatos, estilos, celdas combinadas y controles interactivos.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/Framework-Streamlit-FF4B4B?logo=streamlit&logoColor=white" alt="Streamlit" />
  <img src="https://img.shields.io/badge/AI%20Engine-OpenAI%20API-412991?logo=openai&logoColor=white" alt="OpenAI" />
  <img src="https://img.shields.io/badge/Excel%20Engine-OpenPyXL-217346?logo=microsoft-excel&logoColor=white" alt="OpenPyXL" />
  <img src="https://img.shields.io/badge/PDF%20Engine-PyMuPDF%20%2F%20pdfplumber-E01E5A?logo=adobe-acrobat-reader&logoColor=white" alt="PyMuPDF" />
  <img src="https://img.shields.io/badge/Validation-Pydantic%20V2-E92063?logo=pydantic&logoColor=white" alt="Pydantic V2" />
</p>

---

## 🎯 ¿Qué es AutoForm AI?

**AutoForm AI** (desarrollado para **IAC Latam**) automatiza la tarea repetitiva de completar formularios de proveedores, clientes, entidades financieras y entidades gubernamentales. Mediante una arquitectura híbrida de **Representación Intermedia Espacial (IR)** combinada con **Modelos de Lenguaje (OpenAI)**, la plataforma interpreta la estructura visual del documento, mapea la información corporativa y genera el archivo final listo para descarga sin alterar la maquetación original.

---

## 🛠️ Stack Tecnológico y Herramientas

| Herramienta / Librería | Icono | Versión | Rol en el Sistema |
| :--- | :---: | :---: | :--- |
| **Python** | 🐍 | `>= 3.10` | Entorno de ejecución principal y lógica de negocio. |
| **Streamlit** | 🎈 | `>= 1.36.0` | Interfaz gráfica web reactiva, moderna y accesible. |
| **OpenAI API** | 🤖 | `>= 0.27.0` | Inferencia semántica y mapeo inteligente (`gpt-4.1-mini`, `gpt-4o-mini`, etc.). |
| **OpenPyXL** | 📊 | `>= 3.1.2` | Motor de lectura, análisis espacial, cálculo de bordes, combinación de celdas y escritura en Excel. |
| **PyMuPDF (`fitz`)** | 📑 | `>= 1.24.0` | Motor PDF de alto rendimiento para renderizado e inyección de datos. |
| **pdfplumber** | 🔍 | `>= 0.11.0` | Extracción precisa de geometrías, tablas y texto en documentos PDF. |
| **Pydantic V2** | 📐 | `>= 2.7.0` | Modelado estricto de datos y validación de esquemas de taxonomía. |
| **Instructor** | 🎯 | `>= 1.3.0` | Salidas estructuradas tipo JSON garantizadas desde el LLM. |
| **RapidFuzz** | ⚡ | `>= 3.9.0` | Similitud difusa (*fuzzy matching*) y caché semántico de plantillas a costo $0. |
| **Pillow (PIL)** | 🖼️ | `>= 10.0.0` | Procesamiento visual de imágenes y logos corporativos. |
| **RapidOCR** | 👁️ | `>= 1.3.0` | Reconocimiento óptico de caracteres para PDFs escaneados o imágenes. |

---

## 🏗️ Arquitectura del Pipeline Modular (5 Etapas)

El sistema procesa los documentos a través de una canalización determinista y desacoplada:

```mermaid
flowchart LR
    A[📂 Archivo .xlsx / .pdf] --> S1[Stage 1: Parser]
    S1 --> S2[Stage 2: Classifier & Spatial IR]
    S2 --> S3[Stage 3: LLM Mapper & Cache]
    S3 --> S4[Stage 4: Verifier UI]
    S4 --> S5[Stage 5: Safe Writer]
    S5 --> B[📥 Archivo Final Completado]
```

### 1. 🔍 Stage 1: Parser Unificado (`core/excel_parser.py` / `core/pdf_processor.py`)
* Detecta el tipo de documento (Excel o PDF).
* Escanea celdas, textos, combinaciones (*merges*), fondos sombreados, bordes visuales y coordenadas físicas.

### 2. 🗺️ Stage 2: Classifier & Spatial IR (`pipeline/stages/stage_2_classifier.py` / `core/spatial_ir.py`)
* Construye la **Representación Intermedia Espacial (IR)**: particiona el documento en Secciones $\rightarrow$ Filas $\rightarrow$ Elementos.
* Discrimina títulos de sección, instrucciones, casillas de verificación y campos de entrada rellenables.
* Determina la dirección física de llenado (`derecha`, `abajo`, `arriba`, `misma`).

### 3. 🧠 Stage 3: LLM Mapper & Template Store (`pipeline/stages/stage_3_llm_mapper.py` / `core/llm_client.py`)
* **Memoria de Plantillas:** Si el formulario ya fue procesado antes, reutiliza el mapeo guardado a costo $0 y tiempo récord.
* **Inferencia LLM:** Si es un formulario nuevo, consulta al modelo de OpenAI utilizando la Taxonomía Maestra de la empresa.
* **Validador Semántico (`core/semantic_validator.py`):** Autocorrige inconsistencias mediante reglas deterministas de negocio.
* **Motor de Cobertura (`core/coverage_engine.py`):** Recupera campos omitidos mediante escaneo exhaustivo.

### 4. 🎛️ Stage 4: Verifier UI (`ui/page_verify.py`)
* Pantalla interactiva en Streamlit donde el usuario visualiza los campos emparejados.
* Permite ajustar valores, cambiar asignaciones mediante dropdowns inteligentes y filtrar por nivel de confianza.

### 5. ✍️ Stage 5: Safe Writer (`core/excel_writer.py` / `core/pdf_processor.py`)
* Inyecta los valores en las celdas/capas exactas.
* Preserva estilos originales, bordes, fórmulas, combinaciones y controles de formulario interactivos (**VML Drawings / Checkboxes**).

---

## 🌟 Capacidades y Características Destacadas

* 🛡️ **Protección de Fondos Sombreados:** Las celdas de encabezado o rótulos con fondo gris/color nunca son sobreescritas; el sistema detecta el estilo y escribe en la celda de entrada contigua (a la derecha o abajo).
* 👁️ **Lectura Contextual por Filas:** El LLM recibe el contexto de la fila completa (`contexto_fila`) y del vecino inferior (`vecino_abajo`), resolviendo ambigüedades espaciales con total precisión.
* 🔀 **Desambiguación Contextual Inteligente:** Resuelve automáticamente rótulos genéricos como *"Número"* o *"No."* según la sección (Cédula en Representante Legal, NIT en Empresa, No. de Cuenta en Información Bancaria).
* 📦 **Preservación Total de Controles Excel:** Mantiene intactos botones de opción, casillas de verificación VML y macros originales sin pérdida de interactividad.
* 🏢 **Gestión Multi-Perfil:** Administrador integrado para crear, editar y cambiar entre múltiples perfiles de empresas filiales o subsidiarias.

---

## 🗂️ Estructura del Proyecto

```text
autoform-ai/
├── app1.py                             # 🎈 Punto de entrada principal de Streamlit
├── requirements.txt                    # 📦 Lista de dependencias de Python
├── .env                                # 🔑 Variables de entorno (API Keys - gitignored)
├── assets/                             # 🖼️ Logos, isotipos e imágenes de UI
├── config/
│   ├── datos_empresa.json              # 🏢 Perfil maestro de datos empresariales
│   └── pdf_cache/                      # 💾 Caché en disco para análisis de PDFs
├── core/
│   ├── excel_parser.py                 # 📊 Escaneo de celdas, bordes y estilos en Excel
│   ├── excel_writer.py                 # ✍️ Escritura segura y preservación de VML/estilos
│   ├── pdf_processor.py                # 📑 Motor híbrido de procesamiento PDF
│   ├── spatial_ir.py                   # 🗺️ Representación Intermedia Espacial (IR)
│   ├── llm_client.py                   # 🤖 Cliente OpenAI y Prompt Estricto
│   ├── semantic_validator.py           # 🛡️ Validador determinista post-LLM
│   ├── semantic_cache.py               # ⚡ Almacén de plantillas y Fuzzy Matching
│   ├── coverage_engine.py              # ✨ Recuperador de cobertura exhaustiva
│   ├── profile_manager.py              # 🏢 Carga, guardado y taxonomía de perfiles
│   └── schema_models.py                # 📐 Modelos Pydantic V2 para salidas estructuradas
├── pipeline/
│   ├── context.py                      # 🔄 Contexto compartido del pipeline (PipelineContext)
│   ├── orchestrator.py                 # 🎼 Orquestador central del flujo
│   └── stages/                         # 🏗️ Etapas desacopladas del pipeline (1 a 5)
├── ui/
│   ├── page_verify.py                  # 🎛️ Vista de verificación y edición de mapeos
│   └── components/                     # 🧩 Componentes visuales y tablas interactivas
├── template_store/                     # 💾 Base de datos local de plantillas memorizadas
└── scratch/                            # 🧪 Scripts de pruebas y validación determinista
```

---

## 🚀 Instalación y Puesta en Marcha

### 1. Clonar el repositorio
```bash
git clone https://github.com/pablo2240/AutoForm-IAC.git
cd autoform-ai
```

### 2. Crear y activar entorno virtual
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno
Crea un archivo `.env` en la raíz del proyecto con tus credenciales de OpenAI:
```env
OPENAI_API_KEY=tu_api_key_de_openai_aqui
OPENAI_MODEL=gpt-4.1-mini
```

### 5. Ejecutar la aplicación
```bash
streamlit run app1.py
```

Abre tu navegador en la dirección local indicada (usualmente `http://localhost:8501`).

---

## 🏢 Configuración del Perfil Empresarial

Los datos de la empresa se configuran desde la pestaña **"🏢 Perfiles"** en la interfaz web de Streamlit o directamente en `config/datos_empresa.json`:

```json
{
  "razon_social": "Ingeniería Asistida Por Computador S.A.S",
  "nit": "811004721",
  "tipo_sociedad": "S.A.S",
  "representante_legal": "Guillermo Humberto Cañón Sarria",
  "cedula": "98555384",
  "lugar_expedicion": "Envigado",
  "direccion": "Carrera 63 B # 32 E -25 OFC 206",
  "ciudad": "Medellin",
  "departamento": "Antioquia",
  "pais": "Colombia",
  "telefono": "6042656868",
  "celular": "3148889900",
  "correo": "contacto@iac.com.co",
  "pagina_web": "www.iac.com.co",
  "banco": "Bancolombia",
  "numero_cuenta": "00300833888",
  "tipo_cuenta": "Ahorros"
}
```

---

## 🧪 Pruebas y Control de Calidad

Para ejecutar la suite de pruebas unitarias y de regresión determinista:
```bash
# Validación de Sintaxis
python -m py_compile app1.py core/excel_parser.py core/excel_writer.py pipeline/stages/stage_3_llm_mapper.py

# Pruebas de Regresión Espacial y Semántica
python scratch/test_spatial_ir.py
python scratch/test_semantic_validator.py
python scratch/test_contextual_numero.py
python scratch/test_shaded_backgrounds.py
python scratch/test_user_form_e2e.py
```

---

<p align="center">
  Desarrollado con ❤️ para <strong>IAC Latam</strong> — Automatización inteligente de formularios corporativos.
</p>
