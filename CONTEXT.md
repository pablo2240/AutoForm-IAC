# AutoForm AI — Context & Ubiquitous Language

This document defines the core domain model and vocabulary for **AutoForm AI**. All skills, agents, specifications, tests, and code reviews in this repository must use these exact terms.

---

## 1. Core Architecture: The 5-Stage Pipeline

AutoForm AI executes a deterministic 5-stage pipeline orchestrated by `PipelineOrchestrator`:

* **`Stage 1: Parser`** (`pipeline/stages/stage_1_parser.py`, `core/excel_parser.py`, `core/pdf_processor.py`):
  Scans uploaded files (`.xlsx`, `.xls`, `.pdf`), extracts raw visual labels, detects adjacent empty cells, cell borders, shading, merges, and AcroForm fields.
* **`Stage 2: Classifier`** (`pipeline/stages/stage_2_classifier.py`):
  Categorizes raw visual elements into `FIELD` (viable input fields), `SECTION_TITLE`, `DECORATIVE`, `INSTRUCTION`, `LEGAL_TEXT`, or `OPTION` (checkboxes/radios). Filters out ~46% of tokens before calling the LLM.
* **`Stage 2b: Spatial IR`** (`core/spatial_ir.py`):
  Builds an Intermediate Representation (`DocumentoIR`, `SeccionIR`, `FilaIR`, `ElementoIR`) capturing exact row/column geometry and section hierarchies.
* **`Stage 3: LLM Mapper`** (`pipeline/stages/stage_3_llm_mapper.py`, `core/llm_client.py`, `core/schema_models.py`):
  Divides the form into 4 parallel macro-batches (`MacroLote`), invokes OpenAI via `instructor` with strict Pydantic V2 schema validation (`PlanMapeoSemantico`), followed by the **Zero-Omission Triad** (Instructor Chunking + Python Diff Loop + Local Semantic Matcher).
* **`Stage 3b: Semantic Validator / HSP`** (`core/semantic_validator.py`):
  Deterministic audit pass that validates LLM assignments against Colombian legal rules (e.g. `representante_legal` vs `empresa`), applies auto-corrections, and computes confidence scores.
* **`Stage 5: Writer`** (`pipeline/stages/stage_5_writer.py`, `core/excel_writer.py`, `core/pdf_processor.py`):
  Injects values into the document with format preservation, font inheritance, borders, alignment, and native OpenXML serialization (strictly no raw ZIP/VML binary tampering).

---

## 2. Ubiquitous Vocabulary

| Term | Meaning & Constraints | Avoid Using |
| :--- | :--- | :--- |
| **`Rótulo` (Label)** | The text label in the form asking for information (e.g. *"Razón Social:"*, *"NIT o CC:"*). | "Prompt", "Pregunta", "Header" |
| **`Campo de Entrada` (Input Field)** | The physical target cell or coordinate where the value must be written. | "Hueco", "Casilla vacía" |
| **`Ubicación Física`** | Direction from the label to the input field: strictly `derecha`, `abajo`, or `misma`. | "arriba" (strictly forbidden) |
| **`DatosEmpresa`** | Enterprise profile dictionary (`config/datos_empresa.json`) containing canonical enterprise keys (`razon_social`, `nit`, `representante_legal`, `cedula`, etc.). | "JSON global", "Variables" |
| **`PlanMapeo`** | List of validated mapping directives linking a `Rótulo` coordinate to a canonical `DatosEmpresa` key and destination cell. | "Mapeador", "Lista de campos" |
| **`MacroLote`** | Balanced batch of 15–25 fields grouped by spatial section for parallel LLM inference via `ThreadPoolExecutor`. | "Micro-batch", "Chunk crudo" |
| **`Diff Loop`** | Pure-Python audit pass comparing viable fields against mapped fields to trigger immediate recovery before rendering. | "Filtro posterior" |
| **`Native OpenXML`** | Clean workbook generation strictly using `openpyxl.save(BytesIO)` without injecting raw VML/drawing parts. | "Zip patch", "Inyección VML" |

---

## 3. Architecture Decision Records (ADR) Index

* [`ADR-0001: Native OpenXML Serialization`](docs/adr/0001-openxml-native-serialization.md)
* [`ADR-0002: Deterministic Hybrid Spatial Pipeline (HSP)`](docs/adr/0002-deterministic-hybrid-pipeline-hsp.md)
* [`ADR-0003: Zero-Omission Triad (Chunking + Diff Loop + FastEmbed)`](docs/adr/0003-triad-zero-omission.md)
