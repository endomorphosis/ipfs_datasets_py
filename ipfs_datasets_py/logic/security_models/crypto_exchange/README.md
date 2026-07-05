# Crypto Exchange Security Verification

This package adds a language-neutral security verification layer for wallet and exchange systems.

- Python is the proof-producing plane for model extraction, prover orchestration, proof search, and counterexample discovery.
- TypeScript/WASM is the planned proof-consuming plane for deterministic validation, capability enforcement, receipt checking, and runtime monitoring.
- The shared artifact is a canonical CID-addressed security IR.

The initial vertical slice centers on a minimal exchange model, Z3-backed claims for withdrawals, balance reservation, and capability revocation, runtime temporal monitors, external prover stubs, and proof reports.
