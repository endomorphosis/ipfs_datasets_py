# Hybrid Legal Reasoning Operations Runbook

## WS11 Local Parity Commands

Use these commands to verify the WS11 V3 integration locally.

### Prerequisites

```bash
cd <repo_root>
pip install pytest
```

### Run All WS11 Reasoner Tests

```bash
python -m pytest ipfs_datasets_py/tests/reasoner/ -v --tb=short
```

Expected: 108 tests pass in < 5 seconds.

### Run Individual Test Gates

```bash
# HL-WS11-01 and HL-WS11-07: V3 IR schema + optimizer drift gate
python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py -v

# HL-WS11-02 and HL-WS11-06 and HL-WS11-11 (CNL side):
# CNL grammar + ambiguity + round-trip + transformation pack
python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py -v

# HL-WS11-03, HL-WS11-04, HL-WS11-05, HL-WS11-11 (compiler side):
# Temporal constraints + DCEC + TDFOL + transformation pack
python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -v

# HL-WS11-08: KG enrichment policy
python -m pytest ipfs_datasets_py/tests/reasoner/test_kg_enrichment_adapter.py -v

# HL-WS11-09: Prover certificate contract
python -m pytest ipfs_datasets_py/tests/reasoner/test_prover_backend_registry.py -v

# HL-WS11-10 and HL-WS11-12: V3 API semantics + 8-query proof matrix
python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py -v
```

### With PYTHONPATH (as specified in issue test gates)

```bash
PYTHONPATH=ipfs_datasets_py python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py -q
PYTHONPATH=ipfs_datasets_py python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py -q
PYTHONPATH=ipfs_datasets_py python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q
PYTHONPATH=ipfs_datasets_py python -m pytest ipfs_datasets_py/tests/reasoner/test_kg_enrichment_adapter.py -q
PYTHONPATH=ipfs_datasets_py python -m pytest ipfs_datasets_py/tests/reasoner/test_prover_backend_registry.py -q
PYTHONPATH=ipfs_datasets_py python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py -q
```

## Artifact Paths

| Artifact | Path |
|---|---|
| Test directory | `ipfs_datasets_py/tests/reasoner/` |
| CNL parse corpus fixture | `ipfs_datasets_py/tests/reasoner/fixtures/cnl_parse_replay_v2_corpus.json` |
| Compiler parity fixture | `ipfs_datasets_py/tests/reasoner/fixtures/compiler_parity_v2_cases.json` |
| Paraphrase equivalence fixture | `ipfs_datasets_py/tests/reasoner/fixtures/cnl_parse_paraphrase_equivalence_v2.json` |
| V3 transformation fixture | `ipfs_datasets_py/tests/reasoner/fixtures/cnl_v3_transformation_cases.json` |
| API + proof schema docs | `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md` |
| Reasoner source | `ipfs_datasets_py/processors/legal_data/reasoner/` |

## V3 Integration Module Reference

| Module | Purpose |
|---|---|
| `hybrid_v2_blueprint.py` | CNL parser, IR, DCEC/TDFOL compiler, query APIs |
| `serialization.py` | V3 IR schema, V2→V3 mapping, proof serialization |
| `kg_enrichment.py` | Additive KG enrichment with rollback |
| `optimizer_policy.py` | Semantic-drift gate, acceptance decisions |
| `prover_backends.py` | Backend registry, certificate normalization |
| `models.py` | ProofObject, ProofStep, ProofCertificate, IRReference |

## Quick Smoke Test

```python
import sys
sys.path.insert(0, 'ipfs_datasets_py/processors/legal_data')
from reasoner.hybrid_v2_blueprint import parse_cnl_to_ir, compile_ir_to_dcec, check_compliance, clear_v2_proof_store

clear_v2_proof_store()
ir = parse_cnl_to_ir('Contractor shall submit the report within 30 days')
dcec = compile_ir_to_dcec(ir)
assert 'O(' in dcec[-1]   # deontic operator wraps FrameRef
result = check_compliance({'ir': ir, 'facts': {}, 'events': []}, {})
assert result['status'] == 'non_compliant'  # obligation not met
print('Smoke test passed. Violations:', result['violations'])
```

## Debugging Test Failures

### Import errors
If you see `ModuleNotFoundError: No module named 'reasoner'`, ensure you are running from the repository root and the `conftest.py` at the root is active.

### `municipal_scrape_workspace` not found
The source files now use relative imports (`from .hybrid_legal_ir import ...`) with `municipal_scrape_workspace` as a fallback. This should never fail.

### Stale proof store
Call `clear_v2_proof_store()` at the start of each test function that uses `explain_proof`.

### Proof validation failures
All proof steps require non-empty `ir_refs` and `provenance`. Use `parse_cnl_to_ir()` to build the IR — it always sets `source_ref` on norms.
