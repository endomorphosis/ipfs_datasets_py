# Crypto Exchange Security Verification

This package adds a language-neutral security verification layer for wallet and exchange systems.

- Python is the proof-producing plane for model extraction, prover orchestration, proof search, and counterexample discovery.
- TypeScript/WASM is the planned proof-consuming plane for deterministic validation, capability enforcement, receipt checking, and runtime monitoring.
- The shared artifact is a canonical CID-addressed security IR.

The current implementation surface is intentionally limited to the pieces that execute end-to-end today: a minimal exchange model, Z3-backed claims, runtime temporal monitors, proof/disproof reports, source-code autoformalization, and deterministic TypeScript schema emission for downstream consumers.

This is a v1 bounded `SecurityModelIR`/Z3/proof-report/proof-receipt/TypeScript-consumer slice. It does not prove a production exchange secure: `PROVED` means a modeled finite-IR property holds under the listed assumptions, while `UNKNOWN` and `NOT_MODELED` remain fail-closed, non-secure outcomes. TLA+, Tamarin, ProVerif, HyperLTL, Lean, and Coq execution stay documented future work until they run end-to-end with tests.

Default proof artifacts record bounded assumption IDs (`A1`-`A10`), and the default IR now attaches owner, evidence, review timestamp, and expiry timestamp metadata to those assumptions. The CLI can fail closed when a model declares simulated F-logic/ZKP dependencies or when consumed assumptions lack current operational evidence.

The default release policy maps the current eight claims into blocking, high, and medium release gates. `prove_all` always emits `release_gate` and `assumption_registry` summaries. `--release-gate` exits non-zero unless configured blocking/high claims are accepted, required assumptions are present, and production-critical evidence is reviewed. `--require-current-assumptions` exits non-zero when consumed assumptions have missing owner/evidence/expiry metadata or stale evidence. The audit-linkage claim is medium severity: concrete `DISPROVED` audit gaps block release, while `UNKNOWN` or `NOT_MODELED` audit coverage is triaged with the broader required-domain checks.

The extractor surface now supports seed autoformalization of Python plus popular source languages (JavaScript, TypeScript, Go, Java, and Rust) into `SecurityModelIR`, reusing lightweight natural-language-to-FOL helpers to capture security-relevant comments and docstring obligations as reviewable invariants.

The same autoformalized IR can now be projected into a small Codex-facing feature-loop bundle so code ingestion, proof generation, and regression tests all share the same explicit policy/invariant assumptions.

Install the implemented prover surface with either:

- `python -m pip install z3-solver`
- `ipfs-datasets-install-provers --z3 --yes`

Utility scripts for the PR surface live under `scripts/ops/security_verification/`:

- `autoformalize_security_ir.py` emits canonical security IR JSON from supported codebases.
- `project_security_ir_feature_loop.py` emits the projected feature-loop bundle for synthesis/testing.
- `emit_security_typescript_schema.py` emits the deterministic TypeScript/WASM schema module and runtime guard.
- `run_security_ir_proof_suite.py` wraps the proof CLI for ops automation.
- `run_security_ir_disproof_suite.py` applies deterministic attack tactics plus bounded mutation fuzzing to hunt for counterexamples.
- `run_security_ir_assurance_baseline.py` runs proof, release-gate, and disproof checks into a single markdown summary.
- `run_security_ir_tests.sh` runs the focused test suite plus the fail-closed proof/disproof smoke paths.
