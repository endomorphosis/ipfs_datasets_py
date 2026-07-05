# Crypto Exchange Security Verification

This package adds a language-neutral security verification layer for wallet and exchange systems.

- Python is the proof-producing plane for model extraction, prover orchestration, proof search, and counterexample discovery.
- TypeScript/WASM is the planned proof-consuming plane for deterministic validation, capability enforcement, receipt checking, and runtime monitoring.
- The shared artifact is a canonical CID-addressed security IR.

The current implementation surface is intentionally limited to the pieces that execute end-to-end today: a minimal exchange model, Z3-backed claims, runtime temporal monitors, proof/disproof reports, source-code autoformalization, and deterministic TypeScript schema emission for downstream consumers.

Default proof artifacts record bounded assumption IDs (`A1`-`A10`), and the CLI can fail closed when a model declares simulated F-logic/ZKP dependencies.

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
- `run_security_ir_tests.sh` runs the focused test suite plus the fail-closed proof/disproof smoke paths.
