# ADR 0002: Deterministic Hybrid Spatial Pipeline (HSP)

## Context
Form processing previously relied on sending all cells directly to the LLM in a single monolithic prompt, which resulted in high token costs, hallucinations, omissions, and frequent misplacements (e.g. confusing legal representative data with company data, or writing into headers).

## Decision
Adopt a 5-stage modular pipeline (`PipelineOrchestrator`):
1. `Stage 1: Parser` (Raw spatial cell and AcroForm extraction)
2. `Stage 2: Classifier` (Pre-LLM filtering of decorative/legal/option elements)
3. `Stage 2b: Spatial IR` (`DocumentoIR` intermediate representation)
4. `Stage 3: LLM Mapper` (Batch mapping with strict Pydantic V2 schema)
5. `Stage 3b: Semantic Validator` (Deterministic Colombian legal rules and auto-corrections)
6. `Stage 5: Writer` (Physical injection preserving cell format)

## Consequences
- **Positive**: 46% pre-LLM token reduction by filtering non-input elements.
- **Positive**: Complete domain safety: legal representative fields and company fields are never cross-assigned.
- **Positive**: Zero upward writing: physical write directions are restricted to `derecha`, `abajo`, and `misma`.
