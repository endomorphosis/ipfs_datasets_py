# HSSL-BENCH-027 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-027
Goal: HSSL-G031 — Integrate spaCy as reproducible linguistic evidence
Missing evidence: HSSLEV0310F79
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-027-objective-gap-151e32e07a58.md`
Source fingerprint: `151e32e07a5886edfe4333ac7a137e0a6cc1d173`

## Evidence

- `benchmarks.logic_pipeline.adapters.HSSLEV0310F79` is the stable AST
  evidence symbol for the reproducible spaCy linguistic-evidence objective.
- `SPACY_EVIDENCE_SCHEMA`, `SpacyAdapterMode`, `SpacyAdapterConfig`, and the
  configured `SpacyAdapter` expose the existing legal modal encoder,
  semantic-role extractor, and regex/legal parser through the shared versioned
  stage boundary without changing production compiler or routing behavior.
- Successful evidence has pinned `schema`, `document`, `tokens`, `sentences`,
  `dependencies`, `entities`, `semantic_roles`, `modal_cues`, `modal_ir`,
  `execution`, and `assurance` sections. The payload is bounded and
  content-addressed by the enclosing stage record.
- Requested and effective identities remain distinct. The evidence identifies
  the pinned `full_model`, `blank_model`, or `regex_legal` execution mode,
  package/model versions, pipeline components, and a model-metadata digest.
- An unavailable requested full model produces an explicit unavailable stage;
  spaCy's implicit blank fallback is refused, and the stage never silently
  succeeds with blank-model or regex output. Blank and regex controls must be
  deliberately selected benchmark modes, not implicit substitutes.
- Evidence serialization is deterministic for fixed input and effective
  pipeline. Volatile identifiers from upstream SRL records are excluded from
  the normalized payload, and extracted collections retain a canonical order.
- Linguistic annotations and fallback/control observations remain descriptive
  evidence only. The spaCy stage cannot set kernel acceptance, issue a semantic
  proof receipt, or make a verification-authority claim.

## Validation

Command:

```text
python -m pytest tests/unit/benchmarks/logic_pipeline/test_spacy_adapter.py -q
```

Focused coverage exercises full-model evidence, deterministic blank-model and
regex/legal-parser controls, stable round trips and digests, all required
linguistic fields, explicit missing-model behavior, requested/effective
identity preservation, and the no-proof-authority boundary.

## Backlog alignment

HSSL-G031 is already a cohesive bounded child of HSSL-G030. The adapter,
focused test output, objective-heap contract, and this supervisor discovery
record cover HSSLEV0310F79 without a smaller child goal. Generated todo-vector
and task status remain supervisor-owned and were not edited manually.
