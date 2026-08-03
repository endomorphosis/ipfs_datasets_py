# Software-verification rollout policy

Interface: `LogicFormalVerificationRelease@1`

This document is the operator and implementation contract for promoting
software-verification property/provider pairs through `declared`, `shadow`,
`canary`, and `enforced` states. It is the rollout evidence artifact for
objective `LFV-G083` and is bound by
`docs/architecture/logic_formal_verification_expansion_completion_receipt.json`.

Executable companions:

| Artifact | Role |
| --- | --- |
| `ipfs_datasets_py/tests/fixtures/logic/software_verification/capability_matrix.json` | Capability census maturity (`LogicCapabilityMatrix@1`) |
| `ipfs_datasets_py/docs/security_verification/prover_matrix.md` | Documentation-only prover catalog reconciled to executable definitions |
| `ipfs_datasets_py/tests/integration/benchmarks/logic_pipeline/test_software_verification_matrix.py` | Generates the property/provider matrix from current executable evidence and reports semantic/resource distributions without timing-ratio correctness gates |
| `test/api/test_logic_formal_verification_completion.py` | Validates the program completion receipt |

## Program invariants

- Imports and declaration discovery perform no install, network, process,
  environment, or write side effects.
- Result authorities are typed and non-interchangeable. Advisor output, exact
  cache hits, finite monitors, bounded checks, policy decisions, and simulated
  ZKP attestations never become theorem or kernel authority.
- External tools remain optional. Absence is reported explicitly; it is never
  silent success and never fabricated as installed.
- There is no global “provider enabled” switch. Promotion is always
  property-specific and provider-specific.
- Every stage is reversible. Rollback/quarantine returns a pair to `shadow` or
  `declared` without deleting historical receipts.

## Rollout stages

Stages are strictly ordered and fail closed:

| Stage | Meaning | May affect authoritative results? | Default for new pairs |
| --- | --- | --- | --- |
| `declared` | The property/provider pair is listed in the capability census or prover catalog. | No | Yes |
| `shadow` | The pair may run observationally; results are advisory only. | No | After declaration and smoke evidence |
| `canary` | An explicitly bounded, opt-in diagnostic route may emit health or cohort metrics. | No (cannot claim proof success) | After shadow gates pass |
| `enforced` | The pair may contribute its declared authority class only for the reviewed fragment. | Yes, only for its closed authority list | After canary gates and zero authority-boundary violations |

Unknown stage values fail to `declared`. There is no automatic transition.
Operators must record a promotion decision that names the exact property id,
provider id, stage, assurance ceiling, resource class, and evidence identities.

### Stage transition rules

1. `declared → shadow` requires a checked-in declaration path, a smoke-test
   path, and explicit non-authority labeling for learned or untrusted surfaces.
2. `shadow → canary` requires translation or adapter conformance when the pair
   claims source-bound lowering, explicit resource bounds, and no unresolved
   semantic disagreement in the conformance corpus.
3. `canary → enforced` requires:
   - all mandatory contract and adversarial tests for the pair passing;
   - zero authority-boundary violations for the pair;
   - a documented assurance ceiling and supported fragment;
   - reproducible current-tree receipts for the property fixture set;
   - explicit rollback instructions.
4. Any stage may roll back to `shadow` or `declared` when tools disappear,
   identities change, witnesses disagree, authority is mislabeled, or resource
   bounds are exceeded.

## Property-specific policy

The property vocabulary is
`ipfs_datasets_py.logic.software_verification.properties.PropertyKind`. Each
property kind carries its own default primary providers and maximum authority:

| Property kind | Primary provider families | Maximum authority when enforced | Default stage when tools optional |
| --- | --- | --- | --- |
| `contract` | SMT (Z3/CVC5), kernel reconstruction | `bounded_solver_outcome` / `kernel_checked_proof` | `shadow` until smoke + conformance |
| `invariant` | SMT, TLA+/Apalache | `bounded_solver_outcome` / `bounded_state_machine` | `shadow` |
| `heap_safety` | SMT + separation IR | `bounded_solver_outcome` | `shadow` |
| `data_race_freedom` | concurrency IR + SMT/TLA | `bounded_solver_outcome` / `bounded_state_machine` | `shadow` |
| `liveness` | TLA+/Apalache, runtime MTL | `bounded_state_machine` / monitor only | `canary` for monitors |
| `reachability` | SMT, protocol, TLA | family-specific | `shadow` |
| `authorization` | Datalog/SecPAL | `authorization_policy` | `shadow` |
| `authentication` | protocol backends | `protocol_trace_property` | `shadow` |
| `secrecy` | protocol backends | `protocol_reachability` / secrecy fragment | `shadow` |
| `noninterference` | hyperproperty backends | hyperproperty satisfaction | `declared` until tool smoke |
| `hyperproperty` | HyperLTL/AutoHyper/MCHyper | hyperproperty satisfaction | `declared` until tool smoke |
| `refinement` | refinement IR + SMT/TLA | `bounded_solver_outcome` / state | `shadow` |
| `safety` | SMT, TLA, monitors | family-specific, never upgraded | `shadow` |
| `termination` | SMT/ATP with bounds | `bounded_solver_outcome` only | `shadow` |
| `satisfiability` | SMT/ATP | `bounded_solver_outcome` | `shadow` |
| `validity` | ATP/kernel | `first_order_theorem` / `kernel_checked_proof` | `shadow` |
| `theorem` | ATP/kernel/Hammer reconstruction | theorem or kernel after reconstruction | `shadow` |
| `trace_conformance` | runtime MTL | monitor satisfaction only | `canary` by default |

Learned advisors (`provider.learned_proposals`, Leanstral, SymAI, autoencoder)
remain permanently in `shadow` for every property. They may never transition to
`enforced`.

## Provider authority ceiling

Authority is closed and non-substitutable:

| Authority claim | May be established by | Must never authorize |
| --- | --- | --- |
| `capability_health` | probes, canaries | proof success, completion, mutation |
| `source_translation` | typed adapters/compilers | solver or kernel truth |
| `bounded_solver_outcome` | Z3/CVC5/ATP under exact bounds | kernel-checked proof |
| `kernel_checked_proof` | Lean/Rocq/Isabelle after exact check | unreconstructed hammer search |
| `authorization_policy` | Datalog/SecPAL backends | ambient trust of tool presence |
| `protocol_trace_property` | Tamarin/ProVerif | network deployment success |
| `attestation_binding` | ZKP over an existing receipt | truth of upstream translation |
| `conformance_result` | named executable suite | unrelated tool installation |
| `api_compatibility` | frozen public API suite | semantic proof |

Adapters, transports, caches, and attestations preserve authority; they never
increase it. Cache replay inherits exactly the cached receipt’s authority.

## Promotion and rollback gates

### Hard-zero gates (any positive count blocks promotion and forces quarantine)

- `authority_boundary_violations`
- `false_proof_count`
- `false_completion_count`
- `secret_or_witness_leakage_count`
- `unresolved_cross_provider_disagreement_count`

### Mandatory non-timing gates

Benchmarks and promotion reports may record wall-clock, CPU, memory, process,
and output-byte distributions for capacity planning. Timing ratios must never
be correctness gates. Correctness is decided only by:

- semantic agreement with golden fixtures and mutations;
- explicit unavailable/timeout/malformed/unsupported terminal states;
- reconstruction success under bound identities;
- zero hard-zero gate counts;
- resource-bound compliance (hard limits, not relative speed).

### Resource classes

Each enforced pair must declare a resource class compatible with
`ipfs_datasets_py/ipfs_datasets_py/logic/backends/toolchains.py` and the
bounded process lifecycle. Exceeding CPU, memory, wall-clock, process-count, or
output-byte bounds yields an explicit non-success status and cannot be promoted
as success via cache or advisor fallback.

## Per-property shadow / canary / enforcement checklist

For every property/provider pair before `enforced`:

1. **Declared** in capability matrix or prover catalog with sorted evidence paths.
2. **Smoke** path exists and does not install tools.
3. **Shadow** run emits only advisory envelopes; authoritative_for is empty when
   `shadow` is true.
4. **Canary** is opt-in, cohort-bounded, and limited to `capability_health` or
   non-proof diagnostics.
5. **Enforcement** records assurance ceiling, fragment, resource class, and
   rollback command.
6. **Receipt** binds tree identity, tool identities (or explicit unavailable),
   translation receipt ids, and authority class.

## Reversibility

Rollback is a first-class operation:

| Trigger | Action |
| --- | --- |
| Tool identity change | Invalidate warm cache keys; demote to `shadow` |
| Missing optional tool | Report `unavailable`; keep declaration; never fabricate |
| Authority mislabel | Quarantine pair; demote to `declared`; open defect |
| Semantic disagreement | Prefer fail-closed quarantine over majority vote |
| Resource-bound breach | Terminal non-success; do not promote partial results |
| Operator request | Explicit demotion with reason code and timestamp |

Historical receipts remain immutable. Demotion does not rewrite past evidence;
it changes only the live policy stage for new work.

## Benchmark reporting contract

The release matrix benchmark
(`test_software_verification_matrix.py`) must:

- generate the property/provider matrix from current executable evidence
  (capability matrix rows, property vocabulary, prover definitions, and
  documentation claims);
- report outcome-class distributions (success, unknown, timeout, unsupported,
  malformed, unavailable) without requiring live external tools;
- report resource-bound and cache cold/warm identity fields without treating
  timing ratios as pass/fail;
- reconcile `prover_matrix.md` documentation rows with
  `DEFAULT_PROVER_DEFINITIONS` labels;
- refuse to mark external-tool pairs as enforced when only documentation claims
  exist.

## Completion receipt binding

Program completion for `LFV-G000` requires
`docs/architecture/logic_formal_verification_expansion_completion_receipt.json`
to bind:

- parent and `ipfs_datasets_py` commits or current-tree content identities;
- all 41 child goals (`LFV-G005` … `LFV-G083`);
- capability matrix, prover matrix, rollout policy, conformance population,
  benchmark report summary, and external-tool identity policy;
- `authority_boundary_violations: 0`.

The receipt is evidence of a reviewed current tree. It does not authorize
future work after the tree changes; a later reconciliation must re-validate.

## Keeping the policy current

1. Change implementation and executable evidence first.
2. Update capability matrix maturity flags and this document together.
3. Reconcile `prover_matrix.md` documentation labels with prover definitions.
4. Run
   `python -m pytest ipfs_datasets_py/tests/integration/benchmarks/logic_pipeline/test_software_verification_matrix.py test/api/test_logic_formal_verification_completion.py -q`.
5. Refresh the completion receipt only when the binding set and hard-zero gates
   still hold.

Never refresh documentation solely to silence a failing inventory or authority
test.
