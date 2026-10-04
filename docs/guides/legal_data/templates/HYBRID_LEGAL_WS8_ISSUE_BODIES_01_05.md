# Hybrid Legal WS8 Issue Bodies (01-05)

Use the sections below as copy/paste issue bodies for GitHub.

## HL-WS8-01: Contract Snapshot Lockfile

Title:
`HL-WS8-01: Contract Snapshot Lockfile for V2 Query/Proof Envelopes`

Body:

```markdown
## Summary
Add a machine-readable lockfile snapshot for Hybrid V2 query/proof response envelopes to detect unintended contract drift.

## Scope
- Capture stable key/type shape for:
1. `check_compliance`
2. `find_violations`
3. `explain_proof`
- Add fixture-backed test that fails on envelope schema drift.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `tests/reasoner/fixtures/hybrid_v2_api_schema_snapshot.json`

## Acceptance Criteria
1. Snapshot fixture includes all three API envelope schemas.
2. Test fails when keys or value types drift unexpectedly.
3. Existing query matrix behavior remains backward-compatible.

## Test Gate
`pytest tests/reasoner/test_hybrid_v2_query_api_matrix.py -q`

## Notes
Use deterministic ordering/serialization in snapshot generation to avoid flaky diffs.
```

## HL-WS8-02: IR Contract Error Code Registry

Title:
`HL-WS8-02: Standardize V2 IR Contract Error Code Registry`

Body:

```markdown
## Summary
Introduce stable error codes for IR contract validation and expose them consistently for strict-mode failures.

## Scope
- Add a canonical error code registry for contract validation failures.
- Preserve human-readable error messages while making codes machine-consumable.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `docs/guides/legal_data/HYBRID_LEGAL_MASTER_INTEGRATION_PLAN.md`
- `tests/reasoner/test_hybrid_v2_blueprint.py`

## Acceptance Criteria
1. Contract validator emits structured, stable error codes.
2. Existing strict/non-strict behavior remains unchanged.
3. Docs list the supported code set and intended usage.

## Test Gate
`pytest tests/reasoner/test_hybrid_v2_blueprint.py -q`

## Notes
Focus on additive compatibility; existing callers that parse error text should not break.
```

## HL-WS8-03: Parser Paraphrase Equivalence Corpus

Title:
`HL-WS8-03: Add Paraphrase Equivalence Corpus for V2 Parser`

Body:

```markdown
## Summary
Add a curated CNL paraphrase equivalence corpus to validate semantic equivalence across wording variants.

## Scope
- Add fixture corpus of equivalent/non-equivalent paraphrase pairs.
- Assert equivalent pairs normalize to matching semantic IR targets.

## Target Files
- `tests/reasoner/fixtures/cnl_parse_paraphrase_equivalence_v2.json`
- `tests/reasoner/test_hybrid_v2_parse_replay.py`

## Acceptance Criteria
1. Equivalent paraphrases produce matching norm operator and target-frame semantics.
2. Temporal relation and activation/exception semantics remain equivalent where declared.
3. Non-equivalent pairs are explicitly asserted as non-equivalent.

## Test Gate
`pytest tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## Notes
Keep fixture examples deterministic and small enough for fast CI execution.
```

## HL-WS8-04: Temporal Guard Conformance Expansion

Title:
`HL-WS8-04: Expand Temporal Guard Conformance and Parity Cases`

Body:

```markdown
## Summary
Expand compiler parity conformance for temporal guard handling to improve boundary coverage.

## Scope
- Extend parity fixtures for `within`, `by`, `before`, `after`, `during`.
- Add boundary and mixed-condition temporal cases.

## Target Files
- `tests/reasoner/fixtures/compiler_parity_v2_cases.json`
- `tests/reasoner/test_hybrid_v2_compiler_parity.py`

## Acceptance Criteria
1. At least two additional cases per temporal relation class.
2. Parity report remains inconsistency-free for expected-good fixtures.
3. Negative mismatch tests remain effective and deterministic.

## Test Gate
`pytest tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## Notes
Preserve existing fixture IDs; append new IDs for clean historical diffs.
```

## HL-WS8-05: Optimizer Rejection Telemetry Envelope

Title:
`HL-WS8-05: Normalize Optimizer Rejection Telemetry Envelope`

Body:

```markdown
## Summary
Add a stable optimizer telemetry envelope for policy decisions and rejection diagnostics.

## Scope
- Normalize optimizer decision telemetry fields.
- Ensure rejection reason codes are deterministic and complete.

## Target Files
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/test_hybrid_v2_blueprint.py`

## Acceptance Criteria
1. `optimizer_report` includes stable telemetry fields (`decision_id`, `rejected_reason_codes`, `failure_count`).
2. Boundary behavior (`drift == threshold`) is explicitly tested.
3. Rejection and acceptance payload shapes are stable and documented in tests.

## Test Gate
`pytest tests/reasoner/test_hybrid_v2_blueprint.py -q`

## Notes
Avoid introducing non-deterministic fields (timestamps/random IDs) in telemetry payloads.
```
