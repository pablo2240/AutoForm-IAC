# ADR 0001: Native OpenXML Serialization

## Context
When writing filled Excel files, an earlier implementation attempted to preserve VML controls (checkboxes) by opening the `.xlsx` as a ZIP archive and injecting raw XML snippets (`legacyDrawing`, `vmlDrawing1.vml`, `printerSettings1.bin`). This produced orphaned relationship IDs and invalid packaging namespaces, which caused Microsoft Excel to trigger a repair modal ("Microsoft Excel estaba intentando abrir y reparar el archivo").

## Decision
Serialize workbooks strictly using `openpyxl.save(BytesIO)` in native OpenXML format without any raw ZIP or binary XML injection.

## Consequences
- **Positive**: Generated `.xlsx` files open 100% cleanly in Microsoft Excel across all versions without repair warnings or broken file dialogs.
- **Positive**: Cell styles, fonts, borders, fills, and merged ranges are safely preserved.
- **Negative**: Legacy form controls (VML active controls) that openpyxl strips are not preserved. Modern forms use Unicode checkbox characters or native cell values instead.
