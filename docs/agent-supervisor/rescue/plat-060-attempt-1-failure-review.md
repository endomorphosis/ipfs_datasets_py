# Implementation failure review

- Decision: `guide_rescue`
- Reason codes: `empty_or_no_change`, `proposal_gate_failed`, `environment_validation_unavailable`
- Finding codes: `empty_patch`, `missing_required_field`

## Follow-up guidance

Do **not** widen scope casually. Stay inside the task contract.

### Declared task outputs (exact edit authority)
- `benchmarks/semantic_roundtrip/constructors/causal_autoencoder_guidance.py`
- `tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py`
- `workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json`

### Missing or unfinished expected outputs
Implement **every** declared output before finishing the attempt:
- create/update `benchmarks/semantic_roundtrip/constructors/causal_autoencoder_guidance.py`
- create/update `tests/unit/benchmarks/semantic_roundtrip/test_causal_autoencoder_guidance.py`
- create/update `workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json`

### Environment
Validation could not import or execute the test runner. Fix the hermetic validation environment (pytest on PYTHONPATH) rather than changing product code around the tool failure.

### Next attempt checklist
1. Touch only declared Outputs / Predicted files (plus justified companions).
2. Deliver every listed expected output file.
3. Keep validation commands passing.
4. Avoid renames, submodule edits, and undeclared new modules.
