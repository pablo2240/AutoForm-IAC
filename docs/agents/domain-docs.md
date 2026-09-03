# Domain Docs

How the engineering skills consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root: Contains the project's ubiquitous language and core domain glossary.
- **`docs/adr/`**: Read ADRs that touch the area you are about to work in.

If any of these files do not exist, proceed silently. The `/domain-modeling` skill (reached via `/grill-with-docs`) updates them when terms or decisions get resolved.

## File structure

Single-context repo:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-openxml-native-serialization.md
│   ├── 0002-deterministic-hybrid-pipeline-hsp.md
│   └── 0003-triad-zero-omission.md
├── core/
├── pipeline/
└── ui/
```

## Use the glossary's vocabulary

When naming domain concepts (in issue titles, refactor proposals, hypotheses, test names), use the terms defined in `CONTEXT.md`. Do not drift to synonyms the glossary explicitly avoids.

## Flag ADR conflicts

If your proposed change contradicts an existing ADR, surface it explicitly:
> _Contradicts ADR-XXXX (...), but worth reopening because…_
