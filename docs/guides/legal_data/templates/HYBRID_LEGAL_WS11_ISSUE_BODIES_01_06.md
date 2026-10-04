# Hybrid Legal WS11 Issue Bodies (01-06)

Use the sections below as copy/paste issue bodies for GitHub.

## HL-WS11-01: V3 IR Schema Lock + Validator

Title:
`HL-WS11-01: Lock V3 IR Schema and Deterministic ID Validator`

Body:

```markdown
## Summary
Implement and lock the V3 IR schema contract with deterministic ID validation and backward-compatible ingest behavior.

## Scope
- Implement/confirm V3 IR schema validation across entities, frames, norms, temporals, definitions, and sources.
- Enforce deterministic canonical ID policy (`ent`, `frm`, `tmp`, `nrm`, `src`).
- Add/confirm compatibility mapping from existing V2 payloads to V3 shape.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/models.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/serialization.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py`

## Acceptance Criteria
1. Validator rejects missing refs, orphan IDs, and invalid operators.
2. Canonical IDs are deterministic and replay-stable.
3. V2 payloads ingest via explicit compatibility mapping into valid V3 structures.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py -q`

## Notes
Keep validator errors machine-readable and stable for downstream automation.
```

## HL-WS11-02: CNL Grammar Hardening + Ambiguity Diagnostics

Title:
`HL-WS11-02: Harden CNL Grammar and Ambiguity Diagnostics for V3`

Body:

```markdown
## Summary
Enforce unambiguous CNL template parsing with stable diagnostics and explicit candidate traces for ambiguous inputs.

## Scope
- Ensure deterministic parsing for normative templates (`shall`, `shall not`, `may`).
- Ensure definition templates (`means`, `includes`) map to V3 definition objects.
- Return stable parse error codes with candidate diagnostics in strict mode.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/fixtures/cnl_parse_replay_v2_corpus.json`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py`

## Acceptance Criteria
1. Canonical templates parse deterministically in strict mode.
2. Definition templates emit explicit definition objects in IR.
3. Ambiguous inputs return stable machine-readable codes and candidate traces.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## Notes
Do not relax ambiguity checks to satisfy paraphrase convenience.
```

## HL-WS11-03: Temporal Constraint Normalization Pack

Title:
`HL-WS11-03: Normalize Temporal Constraints as External V3 Objects`

Body:

```markdown
## Summary
Normalize temporal clauses (`by`, `within`, `before`, `after`, `during`) as external temporal objects with deterministic anchor handling.

## Scope
- Keep temporal constructs external to predicate arguments.
- Normalize anchor resolution (event/time) deterministically.
- Expand fixture coverage for temporal normalization edge cases.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/fixtures/compiler_parity_v2_cases.json`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py`

## Acceptance Criteria
1. Temporal semantics are represented as attachable objects, not predicate arity expansion.
2. Anchors resolve deterministically across equivalent inputs.
3. Normalization behavior is stable across paraphrase variants.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## Notes
Preserve existing fixture IDs; append new IDs for temporal normalization coverage.
```

## HL-WS11-04: Compiler V3 Pass (IR -> DCEC)

Title:
`HL-WS11-04: Implement V3 DCEC Compiler Pass with FrameRef Deontic Wrapping`

Body:

```markdown
## Summary
Implement/confirm V3 DCEC compiler output where deontic operators wrap frame references and Event Calculus primitives cover dynamic behavior.

## Scope
- Deontic output wraps `FrameRef(...)` terms.
- Emit `Happens`, `Initiates`, `Terminates`, `HoldsAt` for dynamic cases.
- Apply temporal constraints as external guards.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py`

## Acceptance Criteria
1. Deontic wrappers never target raw slot predicates directly.
2. EC primitives are emitted where dynamics are present.
3. Compiler output is deterministic across replay runs.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## Notes
Do not introduce backend-specific formatting drift into canonical formula strings.
```

## HL-WS11-05: Compiler V3 Pass (IR -> Temporal Deontic FOL)

Title:
`HL-WS11-05: Implement V3 Temporal Deontic FOL Compiler Pass`

Body:

```markdown
## Summary
Implement/confirm V3 Temporal Deontic FOL output with deterministic quantifier discipline and parity with DCEC-level semantics.

## Scope
- Quantify free variables deterministically.
- Preserve frame-level deontic target semantics.
- Map temporal relations to explicit temporal predicates.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py`

## Acceptance Criteria
1. No free-variable leakage in emitted formulas.
2. Deontic target semantics match IR frame references.
3. Temporal relation mapping is deterministic and anchor-consistent.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## Notes
Keep normalization and emission layers separate to simplify regression triage.
```

## HL-WS11-06: Round-Trip CNL/NL Regeneration Contract

Title:
`HL-WS11-06: Add Deterministic V3 Round-Trip CNL/NL Regeneration Contract`

Body:

```markdown
## Summary
Add/confirm deterministic IR -> CNL/NL generation with strict semantics preservation and paraphrase safety.

## Scope
- Support deterministic strict-mode regeneration.
- Support paraphrase mode without modal/temporal scope changes.
- Validate proof-explanation text reconstructability from IR.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/fixtures/cnl_parse_paraphrase_equivalence_v2.json`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py`

## Acceptance Criteria
1. Round-trip output is deterministic for canonical templates.
2. Paraphrase mode preserves all semantic IDs and scope.
3. Generated NL is usable in proof explanation rendering paths.

## Test Gate
`PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## Notes
Favor deterministic clause ordering to prevent noisy diff churn.
```
