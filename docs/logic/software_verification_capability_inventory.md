# Software-verification capability inventory

This document describes `LogicCapabilityMatrix@1`. Its executable source of
truth is
`tests/fixtures/logic/software_verification/capability_matrix.json`, using
schema `logic-capability-matrix/v1`; the matching unit test rejects incomplete
categories, missing reviewed families, stale repository paths, stale public
symbols, undocumented rows, and inconsistent maturity or authority metadata.

## Contract and scope

The census covers the reviewed logic surface that exists across the
`ipfs_datasets_py` checkout and its agent-supervisor integration. It inventories
logic families, compilers, providers, installers, probes, adapters, conformance
suites, authority roles, and public access paths. A row is a durable repository
declaration, not a claim about the machine running the test.

Paths in the fixture are POSIX paths relative to the superproject root. Every
source and evidence path must name a checked-in file. The matrix deliberately
uses grouped rows when several files implement one capability—for example the
Lean, Coq/Rocq, and Isabelle reconstructors—while keeping materially different
trust or rollout roles in separate rows.

The v1 reviewed family set is:

| Matrix row | Family surface |
| --- | --- |
| `family.cec_dcec` | CEC/DCEC event calculus and native inference |
| `family.deontic` | deontic and temporal-deontic logic |
| `family.flogic` | Frame Logic and optional ErgoAI execution |
| `family.fol` | first-order logic |
| `family.intent_ir` | source-bound Intent IR |
| `family.legal_ir` | Legal/modal IR |
| `family.modal` | deterministic modal logic plus separate learned proposals |
| `family.security_ir` | Security IR assumptions, policies, and claims |
| `family.tdfol` | temporal deontic first-order logic |

ZKP, caches, bridges, learned selectors, and health checks are supporting
surfaces, not additional logic families. A later taxonomy version may add a
family only through an explicit fixture, test, and documentation update.

## Maturity states

Every row records every state; absence is never overloaded to mean false.

| Field | Meaning |
| --- | --- |
| `declared` | This versioned matrix intentionally contains the row. |
| `discoverable` | A registry, import, probe, or public route can locate it without installing it. |
| `installed` | `not_applicable`, `declared_only`, `runtime_probed`, or `installed`; environment-dependent dependencies normally use `runtime_probed`. |
| `smoke_tested` | A checked-in test exercises the named surface, with paths in `evidence.smoke_tests`. |
| `translation_conformant` | A checked-in suite exercises a typed/source-bound or cross-family translation contract. |
| `reconstruction_capable` | The surface can request independent reconstruction; it does not assert that a kernel is installed or that a check succeeded. |
| `shadow` | Output is observational/advisory and cannot affect an authoritative result. |
| `canary` | An explicitly bounded, opt-in diagnostic route exists and cannot claim proof success. |
| `authoritative_for` | Closed list of direct evidence claims; an empty list means no authority. |

`smoke_tested`, `translation_conformant`, and `reconstruction_capable` must
agree exactly with their corresponding evidence lists. `shadow` rows must have
an empty `authoritative_for` list. A `canary` may report
`capability_health`, but cannot claim source translation, solver, or
kernel-proof authority.

## Capability census

The compiler and adapter rows identify where declarations become other
representations or provider requests:

| Kind | Matrix rows |
| --- | --- |
| Compilers | `compiler.backend_smt`, `compiler.formalization`, `compiler.hammer_translation`, `compiler.legacy_family_converters`, `compiler.modal` |
| Domain and cross-logic adapters | `adapter.cross_logic_bridges`, `adapter.domain_formalization` |
| External-tool and kernel adapters | `adapter.external_atp_smt`, `adapter.itp_frontends` |
| Cross-repository adapters | `adapter.supervisor_ipfs_datasets`, `adapter.supervisor_program_ast` |

`compiler.backend_smt` compiles shared bounded requests for Z3 and CVC5 without
claiming that either executable is installed. `compiler.hammer_translation`
records typed TPTP/SMT-LIB translation and reconstruction evidence.
`compiler.formalization` and `adapter.domain_formalization` share the
source-grounded Legal, Security, and Intent contract. The legacy family and
modal rows are smoke-tested compatibility surfaces but are not marked
translation-conformant without the newer cross-family evidence.

Providers remain separate from their installation and authority:

| Matrix row | Provider role |
| --- | --- |
| `provider.backend_registry` | immutable declarations plus explicit bounded execution |
| `provider.cec_tdfol_native` | in-repository CEC/DCEC and TDFOL inference |
| `provider.external_router` | deterministic routing among discovered external provers |
| `provider.flogic` | Frame Logic with explicit optional/simulation behavior |
| `provider.hammer` | typed portfolio producing candidates and reconstruction requests |
| `provider.itp_kernels` | Lean, Coq/Rocq, and Isabelle reconstruction providers |
| `provider.knowledge_graphs` | supporting graph projection and reasoning without theorem authority |
| `provider.learned_proposals` | Leanstral, SymbolicAI, and learned-selector candidates in shadow mode |
| `provider.supervisor_protocol` | versioned in-process/subprocess provider transport |
| `provider.zkp_backends` | simulated, Groth16, and ProveKit attestation bindings |

The executable suites that support the maturity claims are:

| Matrix row | Contract covered |
| --- | --- |
| `conformance.api_v1` | public imports and payloads, CLI/MCP, optional absence, and authority meanings |
| `conformance.capability_probes` | complete bounded discovery and explicit unavailable/degraded results |
| `conformance.hammer` | translation, portfolio, end-to-end execution, and reconstruction |
| `conformance.ir_families` | Legal, Security, and Intent shared formalization |
| `conformance.provider_protocol` | provider operations, isolation, limits, cancellation, and fail-closed errors |

A conformance suite is authoritative only for its own
`conformance_result`. Passing one suite cannot infer tool installation,
translation conformance, or reconstruction for an unrelated row.

## Runtime probes and installation

Repository presence and runtime availability are independent. The matrix uses
`runtime_probed` for packages, models, circuits, or executables whose
installation varies by environment. No inventory test imports optional
providers, invokes a solver, accesses the network, or installs software.

The discovery mechanisms are:

| Matrix row | Probe behavior |
| --- | --- |
| `probe.hammer_environment` | offline filesystem/executable census; optional bounded version metadata only |
| `probe.logic_pipeline` | immutable provider records with requested/effective identity and provenance |
| `probe.mcp_capabilities` | public capability/health envelope with explicit unavailability |
| `probe.supervisor` | bounded cached discovery plus a disabled-by-default inference canary |

The two installer surfaces are intentionally separate:
`installer.lazy_external_provers` is opt-in and disabled by default, while
`installer.prover_cli` is the explicit operator command. Neither is called by
any probe or inventory test. A declared adapter plus a bare executable is not
silently reported as a verified provider; the relevant probe records each
dimension independently.

## Proof authority

The closed authority vocabulary prevents vague labels such as “verified” from
collapsing distinct evidence:

| Claim | Meaning |
| --- | --- |
| `api_compatibility` | exact reviewed behavior at the named public surface |
| `attestation_binding` | binding to the exact statement/receipt, not truth of prior translation |
| `bounded_solver_outcome` | outcome for exact formula, assumptions, tool identity, and bounds |
| `capability_health` | discovery and health metadata only; never proof success |
| `conformance_result` | pass/fail result for the named executable suite |
| `kernel_checked_proof` | exact proof artifact accepted by the named trusted kernel and environment |
| `source_translation` | deterministic source-bound translation for the supported fragment |

The role rows make the trust boundary explicit:

| Matrix row | Authority rule |
| --- | --- |
| `authority.attestation` | may establish only `attestation_binding`; the compatibility ZKP surface is simulated |
| `authority.capability_health` | may establish only `capability_health` |
| `authority.kernel_reconstruction` | may establish `kernel_checked_proof` only after a successful exact check |
| `authority.proposal_candidate` | shadow/advisory, with no authority |
| `authority.solver_evidence` | may establish a `bounded_solver_outcome`, not kernel reconstruction |

Adapters and transports preserve authority; they do not increase it. Cache
replay inherits exactly the cached receipt’s authority. A learned proposal,
canary response, available dependency, transport success, solver candidate, or
attestation cannot authorize repository mutation or supervisor completion.

## Public access paths

Public transport success is not domain success. Each route points to a
statically checked symbol so the inventory test can detect drift without
importing optional providers:

| Matrix row | Channel | Reviewed route |
| --- | --- | --- |
| `public.python_logic_api` | Python | `ipfs_datasets_py.logic.api` |
| `public.cli_logic` | CLI | `ipfs-datasets logic` parser/runner |
| `public.mcp_logic` | MCP | exported logic capability, health, conversion, and proof tools |
| `public.cli_prover_installer` | CLI | explicit `ipfs-datasets-install-provers` operator action |
| `public.supervisor_provider` | provider protocol | supervisor provider protocol and entry-point registry |

The Python, logic CLI, and MCP surfaces are also frozen by
`conformance.api_v1`. The supervisor route is exercised by
`conformance.provider_protocol`. Optional absence must remain different from a
negative result, unknown proof, timeout, malformed request, or success.

## Keeping the census current

Change this contract deliberately:

1. add, remove, or revise the implementation;
2. update the corresponding sorted matrix row and evidence paths;
3. add executable smoke, translation, or reconstruction evidence before
   setting that maturity flag;
4. update this document with every new row identifier and trust consequence;
5. run
   `python -m pytest ipfs_datasets_py/tests/unit/logic/software_verification/test_capability_inventory.py -q`;
6. review any authority change independently—never refresh metadata merely to
   make a failing test green.

The test also mutates representative rows to prove that shadow authority,
missing conformance evidence, and stale paths fail closed. Runtime reprobes may
change a deployment report without changing this repository contract; a
repository path, public symbol, maturity claim, or authority role requires a
reviewed matrix change.
