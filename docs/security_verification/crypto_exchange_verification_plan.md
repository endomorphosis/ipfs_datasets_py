# Crypto Exchange Verification Plan

This framework positions Python as the proof-producing plane for exchange security claims.

- Extract exchange-relevant models from source code, APIs, policies, and logs into a canonical security IR.
- Reuse the same projected feature-loop bundle across code auto-ingestion, proof generation, and proof-regression tests so assumptions stay aligned.
- Canonicalize and content-address the IR so later TypeScript/WASM components can consume stable artifacts.
- Compile selected claims to the implemented Z3 backend first; additional prover families can be integrated later once they execute end-to-end as real verifier backends.
- Emit proof reports, counterexample reports, and proof receipts that future runtime enforcement can verify.
- Keep production fail-closed by exposing only implemented prover surfaces in this package.

## Soundness boundary

- The Python proof-producing plane validates only the claims that are explicitly modeled and compiled to the implemented Z3 backend.
- Autoformalized code facts now carry evidence references and review status so heuristic extraction cannot silently become a blocking proof.
- Proof consumers must treat `UNKNOWN`, `NOT_MODELED`, and heuristic-only blocking proofs as non-secure until reviewed.
- Additional prover families stay future work until an end-to-end compiler and runner is added.

