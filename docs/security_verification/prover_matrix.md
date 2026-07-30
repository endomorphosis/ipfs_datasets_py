# Prover Matrix

Documentation catalog for formal verification provers used by the software
verification expansion. Rows are documentation claims only. Runtime maturity
states (`absent`, `discovered`, `versioned`, `smoke_tested`,
`translation_conformant`, `reconstruction_capable`, `authoritative_for`) are
produced by executable probes and self-test receipts in
`ipfs_accelerate_py.agent_supervisor.proof.prover_matrix_registry` and by the
capability census in
`ipfs_datasets_py/tests/fixtures/logic/software_verification/capability_matrix.json`.

Interface: `LogicFormalVerificationRelease@1` (documentation surface)
Executable probe schema: `ipfs_accelerate_py/agent-supervisor/prover-matrix@1`

| Prover | Access path | Primary fit |
| --- | --- | --- |
| Z3 | Python package / `z3` executable | SMT checks, VCs, resource invariants |
| CVC5 | Python package / `cvc5` executable | SMT differential lane with Z3 |
| TLA+/TLC | External JVM tools (`tlc`, `tlc2`) | Finite state-machine and workflow checking |
| Apalache | External JVM tool (`apalache-mc`) | Bounded symbolic state-machine checking |
| Datalog/SecPAL | Python or external (`souffle`, `pyDatalog`) | Authorization and delegation decisions |
| Tamarin | External tool (`tamarin-prover`) | Cryptographic protocol trace properties |
| ProVerif | External tool (`proverif`) | Protocol secrecy and authentication queries |
| HyperLTL/AutoHyper/MCHyper | External hyperproperty tools | Information-flow and multi-trace properties |
| Lean | Kernel frontend / Lean executable | Independent kernel proof checking |
| Coq | Kernel frontend (`coqc` / Rocq) | Independent kernel proof checking |
| Runtime MTL | Python now (`rtamt`), TypeScript parity package | Online temporal trace monitoring |
| DCEC | In-repository CEC/DCEC surface | Event-calculus and deontic reasoning |
| TDFOL | In-repository TDFOL surface | Temporal deontic first-order reasoning |
| Hammer | In-repository hammer portfolio | Candidate search plus reconstruction requests |
| Vampire | External ATP (`vampire`) | First-order theorem proving |
| E prover | External ATP (`eprover`) | First-order theorem proving |
| Isabelle | Kernel / Isabelle executable | Kernel checking and hammer reconstruction |
| ShadowProver | Optional modal bridge | Modal/deontic candidates without kernel authority |
| Leanstral | Untrusted model assistant | Proposal/advisor candidates only (shadow) |
| ZKP backends | Attestation bindings | Bind existing receipts; never raise semantic authority |

## Soundness boundary

- Documentation rows never establish runtime proof authority by themselves.
- A declared adapter plus a discoverable executable is not sufficient for
  `smoke_tested`, `translation_conformant`, `reconstruction_capable`, or
  `authoritative_for`; those states require bounded self-test receipts with
  bound identities.
- Tool absence is an explicit non-success state. Tests and rollout policy must
  never fabricate unavailable external-tool evidence.
- Advisors (Leanstral, SymAI, autoencoder), exact-cache hits, finite monitors,
  bounded checks, policy decisions, and simulated ZKP attestations cannot be
  represented as stronger authority than their declared class.
- Proof reports separate deterministic payload content from timestamped
  envelopes so consumers can audit what was actually checked.
- Property-specific promotion uses
  `ipfs_datasets_py/docs/logic/software_verification_rollout.md` (`declared` →
  `shadow` → `canary` → `enforced`) and never a global provider switch.

## Reconciliation sources

| Source | What it contributes |
| --- | --- |
| `DEFAULT_PROVER_DEFINITIONS` in `prover_matrix_registry.py` | Canonical prover ids, families, fixtures, documentation labels |
| `capability_matrix.json` | Discoverable/smoke/translation/authority maturity for families and providers |
| Rollout policy | Per-property stage and reversible quarantine rules |
| Release matrix benchmark | Semantic and resource distributions without timing-ratio correctness gates |

When this table drifts from executable definitions, update the Markdown labels
to match definitions—not the reverse for unavailable tools.
