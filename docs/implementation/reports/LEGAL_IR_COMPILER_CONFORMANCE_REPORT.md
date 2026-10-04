# LegalIR Compiler Conformance Report

Task: PORTAL-LIR-HAMMER-099  
Track: compiler-validation  
Status: implemented  
Validation command: `/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/conformance/legal_ir/test_legal_ir_compiler_conformance.py -q`

## Scope

This report defines the end-to-end release gate for the LegalIR compiler as a productized compiler/decompiler/proof system. The conformance suite is `tests/conformance/legal_ir/test_legal_ir_compiler_conformance.py` and runs only deterministic in-repository fixtures plus synthetic trusted proof receipts. It does not require live external provers, training jobs, or daemon internals.

## Required Capabilities

| Capability | Status | Evidence |
| --- | --- | --- |
| compile | required | Public API and CLI compile a legal source into stable LegalIR output, proof obligations, pass order, diagnostics, and source maps. |
| proof-carrying artifacts | required | A compiled artifact is packaged with guidance, translation records, reconstruction receipts, route results, source maps, and a build manifest, then validated and exported through the public API. |
| decompile | required | Decompiled text round-trips the compiled source without loss for the supported source subset. |
| semantic diff | required | API and CLI semantic diff classify changed obligations and emit `legal-ir-semantic-diff-v1`. |
| diagnostics | required | Diagnostics include structured families, severity, source-map attachment, LSP conversion, fail-closed validation, and proof-readiness errors. |
| reproducibility | required | Repeated API and CLI compiles produce the same compile digest, deterministic pass order, and compiled payload. |
| external benchmark isolation | required | External expert packets stay in the external test split, are allowed only for external evaluation, and are rejected for training or hyperparameter selection. |
| hard negatives | required | Verified hard-negative curricula cover all required negative families, reject unverified model negatives, and prove false-positive reduction without trusted positive degradation. |
| source maps | required | Compiler output carries `legal-ir-source-map-v1`; source-map validation and proof source traceability are enforced. |
| backend conformance | required | All canonical backend targets and features are covered; silent obligation drops and shared semantic divergence block promotion. |
| CLI/API behavior | required | The daemon-free CLI emits the same JSON contract as the in-process API for compile, validate, and diff. |

## Optional Capabilities

| Capability | Status | Evidence |
| --- | --- | --- |
| learned-guidance activation | optional | Public compiler options support explicit learned guidance with artifact evidence; production default remains inactive. |
| interchange profiles | optional | Legal JSON, Legal XML, RDF/OWL, KG JSON, proof JSON, and decompiler JSON have separate unit-level interoperability gates with explicit loss markers. |
| benchmark timing metrics | optional | The compiler API exposes deterministic benchmark envelopes with last compile digest and compile metrics. |
| incremental work avoidance | optional | The default compile path emits incremental snapshots and deterministic pass records that downstream gates can compare. |

## Unsupported Capabilities

| Capability | Status | Reason |
| --- | --- | --- |
| live external solver execution in conformance | unsupported | The suite uses synthetic trusted receipts to keep the release gate deterministic and hermetic. Live solver health remains covered by hammer/backend-specific tests. |
| external benchmark use for training or hyperparameter selection | unsupported | External expert packets are evaluation-only by policy and fail closed for training operations. |
| unverified model-generated negatives as training labels | unsupported | Hard-negative curriculum construction rejects unverified model negatives instead of silently admitting them. |
| silent backend obligation drops | unsupported | Backend conformance treats silent drops as promotion blockers; only typed unsupported diagnostics may waive an unsupported backend feature. |
| lossless conversion for inherently lossy interchange subsets | unsupported | Legal XML, proof JSON, and decompiler JSON mark unsupported fields explicitly instead of claiming lossless support. |

## Failed Capabilities

No failed capabilities are recorded for this conformance suite. A future failure must be added here with the failing capability, owning component, validation output, and rollback or repair path before promotion.

## Release Gate

The suite is a hard release gate for compiler-system promotion. It must pass before PORTAL-LIR-HAMMER-100 can promote the LegalIR compiler system. Required capabilities are treated as promotion blockers. Optional capabilities may regress only if their dedicated unit gates mark the regression as explicitly unsupported or intentionally deprecated.

## Related Evidence

- `tests/unit/logic/integration/test_legal_ir_compiler_api.py`
- `tests/unit/logic/integration/test_legal_ir_proof_carrying_artifacts.py`
- `tests/unit/logic/integration/test_legal_ir_backend_conformance.py`
- `tests/unit/logic/integration/test_legal_ir_diagnostics.py`
- `tests/unit/logic/integration/test_legal_ir_source_maps.py`
- `tests/unit/logic/integration/test_legal_ir_semantic_diff.py`
- `tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_external_benchmark.py`
- `tests/unit/optimizers/logic_theorem_optimizer/test_legal_ir_hard_negatives.py`
