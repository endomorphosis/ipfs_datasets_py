# Crypto Exchange Verification Plan

This framework positions Python as the proof-producing plane for exchange security claims.

- Taskboard: `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md`
- Extract exchange-relevant models from source code, APIs, policies, and logs into a canonical security IR.
- Reuse the same projected feature-loop bundle across code auto-ingestion, proof generation, and proof-regression tests so assumptions stay aligned.
- Canonicalize and content-address the IR so later TypeScript/WASM components can consume stable artifacts.
- Compile selected claims to the implemented Z3 backend first; additional prover families can be integrated later once they execute end-to-end as real verifier backends.
- Emit proof reports, counterexample reports, and proof receipts that future runtime enforcement can verify.
- Keep production fail-closed by exposing only implemented prover surfaces in this package.
- Apply the default release policy with `prove_all --release-gate` so blocking/high claims fail closed on `DISPROVED`, `UNKNOWN`, `NOT_MODELED`, missing required assumptions, or unreviewed production-critical evidence.
- Apply the assumption registry with `prove_all --require-current-assumptions` so consumed assumptions fail closed when owners, evidence, or freshness metadata are missing or stale.

## Soundness boundary

- The Python proof-producing plane validates only the claims that are explicitly modeled and compiled to the implemented Z3 backend.
- `PROVED` means the current backend established a bounded property of this IR under the listed assumptions; it does not mean the whole production system is secure in the absolute.
- Autoformalized code facts now carry evidence references and review status so heuristic extraction cannot silently become a blocking proof.
- Proof consumers must explicitly accept report assumptions and must treat `UNKNOWN`, `NOT_MODELED`, and blocking proofs backed only by unreviewed evidence as non-secure.
- The release-policy summary is not a whole-system security proof; it states whether the current proof reports satisfy the configured claim gates for the modeled IR.
- The assumption-registry summary is not theorem-prover evidence; it records whether operational facts supporting the proof boundary are owned, evidenced, accepted, and current.
- Additional prover families stay future work until an end-to-end compiler and runner is added; disabled families are planning targets only.
