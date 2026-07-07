# Prover Matrix

| Prover | Access path | Primary fit |
| --- | --- | --- |
| Z3/CVC5 | Python accessible | SMT checks and resource invariants |
| TLA+/TLC/Apalache | External JVM tools | Distributed workflow and state-machine checking |
| Datalog/SecPAL style | Python or external | Authorization and delegation reasoning |
| Tamarin/ProVerif | External tools | Cryptographic protocol verification |
| HyperLTL/AutoHyper/MCHyper | External tools | Information-flow and hyperproperties |
| Lean/Coq | Proof checking kernels | Frontend/WASM-compatible proof validation |
| Runtime MTL | Python now, TypeScript later | Online temporal trace monitoring |

## Soundness boundary

- `z3` is the only implemented prover in this package today.
- Other prover families remain planning targets and are intentionally excluded from the proof-producing surface until they execute end-to-end.
- Proof reports separate deterministic payload content from timestamped envelopes so consumers can audit what was actually checked.

