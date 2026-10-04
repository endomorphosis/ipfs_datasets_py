# Hammer, SyMAI, spaCy, and Leanstral Benchmark Decision Runbook

Runbook ID: HSSL-BENCH-043
Goal ID: HSSL-G170
Evidence: HSSLEV1703E61
Evidence marker: source-bound replacement architecture decision, immutable v1 preservation, measured delegation dispositions, and worktree-safe reassessment reproduction runbook
Protocol revision: 1
Decision artifact: docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision_v2.json
Objective heap: docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md

## Purpose and authority

This is the operator runbook for reproducing and maintaining the replacement
Hammer/SyMAI/spaCy/Leanstral architecture decision. It is an evidence
procedure, not a production deployment procedure. Nothing in this runbook
authorizes a production route change, service installation, model download,
automatic merge, holdout access, or production promotion.

The machine-readable v2 final-decision artifact is authoritative for the
current disposition. It is valid only when its exact HSSL-G140 pilot,
HSSL-G150 holdout, and HSSL-G160 replay/report sources revalidate. The
immutable v1 decision remains the historical predecessor and is linked by
both byte and semantic digest; v2 does not overwrite or reinterpret it. The
objective heap records the dependency graph. Canonical benchmark result files
and their dated performance snapshots provide the phase receipts. If prose
conflicts with a source-validated canonical receipt, stop and use the receipt.
Never edit a receipt to make the prose agree.

The independent native kernel is the only proof authority. Hammer solver
evidence, Leanstral drafts, SyMAI output, spaCy annotations, reconstruction
records, model confidence, and legacy S1 predictions are non-authoritative.

## Revision-2 operational status: NO-GO

> **NO-GO — 2026-07-26.** HSSL-G231 and HSSL-G240 now have bounded local
> implementation markers backed by source-safe integration and adversarial
> tests. Those markers do not satisfy an operational gate. HSSL-G201,
> HSSL-G202, HSSL-G203, HSSL-G212, HSSL-G220, HSSL-G232, HSSL-G241,
> HSSL-G242, and HSSL-G243 still require separately governed external
> operational receipts. Do not run a revision-2 pilot/development
> matrix, open any benchmark source, label, manifest body, proof obligation, or
> replacement holdout, or publish a replacement decision. The work currently
> allowed is implementation-source review, explicitly source-safe synthetic
> testing, non-corpus capability smokes, and a no-submit supervisor dry run.

The `Protocol revision: 1` header and the published artifact commands below
describe the immutable historical decision. They are not revision-2 execution
instructions and cannot be relabelled as revision-2 evidence. Command blocks
are therefore identified as one of:

- **SOURCE-SAFE NOW** — permitted while this NO-GO remains active;
- **HISTORICAL REVISION 1 ONLY** — retained only to reproduce or validate the
  immutable predecessor and not to be run by the revision-2 readiness lane; or
- **FUTURE AUTHORIZED** — prohibited until the named external gate explicitly
  authorizes that exact operation.

## Published decision

The 2026-07-24 replacement decision is **no architecture promotion**:

- Keep the current effective A0 route unchanged.
- Select `gather_more_evidence` as the architecture outcome.
- Do not add full-model spaCy, SyMAI, Hammer, or Leanstral to the production
  route on the basis of this benchmark capture.
- Do not select P0, P1, P2, or P3 for production.
- Keep the holdout sealed and unopened.

This is a source-validated blocked-evidence decision, not a finding that the
optional components are ineffective or that A0 won. The repaired-runtime
reassessment executed all 560 pilot/development coordinates for A0-A12 and S1
across cold and warm modes. It produced 520 non-missing proof-efficacy
observations, zero independent-native-kernel acceptances, and no independent
reviewed semantic-quality receipt. All 56 invalid-control coordinates had
zero kernel-verified false positives, but that alone cannot establish
candidate quality or authorize a shortlist.

The source-valid HSSL-G140 pilot gate is therefore `incomplete`, its frozen
nonbaseline shortlist is empty, and holdout access is unauthorized. The
HSSL-G150 holdout gate is correspondingly `blocked` and `sealed_unopened`,
with no writes, backend calls, scheduled or observed pairs, or inspected
outcomes. HSSL-G160 truthfully selects an empty replay population and sets
`replay_claimed=false`; its pilot/development statistics remain measured,
while every holdout-only value is
`not_applicable_before_authorization` and null. Structural validation, a
zero-population replay accounting flag, or an observed zero must never be
presented as paired holdout efficacy, zero holdout cost, or replay success.

### Later immutable diagnostic matrix

The completed 2026-07-25 run
`hssl-matrix-20260725T040701Z-21c385c72` is later diagnostic evidence, not a
replacement for any canonical v2 publication receipt. It ran in the external
root
`~/.local/share/ipfs_accelerate_py/benchmarks/hssl-repaired-runs/` from clean
detached source commit `21c385c72f699f2f6963af489cdd49176204f569` after all
eight required capability identities passed their freeze. Its canonical
matrix `artifact_sha256` is
`6e02f487c85285ff1bff56a593a270c2d90fbf5b50ae38cb37da26f2c071ac57`.
The immutable matrix-index bytes have SHA-256
`24f2b86469e8a24ffc74b37ec231c2d3f34856a9396277804076a5bd7ea840fc`;
the immutable public-snapshot bytes have SHA-256
`03e80dfc48e3822433c7c22665ca19bfd1db0e1da9cedcf0176a2142111108ae`.
Do not edit, resume, delete, reuse its run namespace, copy it over
`matrix-execution-v2.json`, or treat its completion as a pilot authorization.

The immutable diagnostic counts are:

| Diagnostic domain | Observed result |
|---|---|
| Matrix coverage | 560 of 560 A0-A12/S1 pilot/development cold/warm coordinates |
| Stage/resource accounting | 1,826 invoked stages and 1,826 released leases |
| Independent kernel | 348 invocations and 216 accepted terminal receipts |
| Pilot outcomes | 113 verified, 140 not verified, 7 rejected, 20 unavailable |
| Development outcomes | 91 verified, 164 not verified, 5 rejected, 20 unavailable |
| Invalid controls | 56 coordinates, zero kernel-accepted false positives |
| Typed failures | 12 combined Leanstral failures and 40 S1 capability-unavailable outcomes |
| Repair | Zero `repair_attempts: 1` records; every Leanstral invocation was one-pass synthesis |
| Safety | `holdout_accessed=false`, zero holdout coordinates, no fallback, and no production-routing change |

Those counts exposed execution and accounting defects that invalidate efficacy
interpretation of this run:

- all 12 top-level rejected cases nevertheless carried an accepted terminal
  kernel receipt, yielding 216 raw acceptances but only 204 top-level verified
  results;
- A9 called Leanstral on 18 compiler-native successes (10 pilot and 8
  development) because its index-zero deterministic-first suppression was
  skipped;
- the 12 combined Leanstral failures exposed an implicit provider prompt
  cache and operational cache metadata leaking into the semantic projection;
- warm SyMAI execution recorded zero cache hits because the frozen matrix did
  not perform a source-bound prime, so it did not establish a cold/warm cache
  comparison;
- the subsequently integrated strict split cache-isolation validator rejects
  this diagnostic rather than grandfathering it: pilot contains six and
  development contains four cold/warm effective-route disagreements. Eight are
  Leanstral success-versus-typed-provider-failure pairs whose failure receipts
  omit the resolved provider/model identity, and the two A6 disagreements
  include conditional Hammer fallback after a warm Leanstral failure (each A6
  coordinate contributes both a Leanstral and Hammer disagreement). Requested
  arm identities and registered stage sequences remain equal, but these
  outcome-dependent execution paths cannot be attributed solely to cache mode;
- all 40 S1 cells intentionally used
  `legacy_symbolicai_identity_not_in_repaired_freeze`, proving typed
  missingness rather than legacy SymbolicAI behavior; and
- protocol revision 1 has no post-kernel feedback edge or reviewed
  repair-trigger population, so zero repair attempts say nothing about repair
  efficacy.

Repair the implementation outside this immutable namespace, freeze a new
capability/source identity, and rerun the unchanged pilot/development matrix
under a new run ID. Keep the holdout sealed. HSSL-G180 owns a future
append-only protocol/corpus revision for an actual one-repair comparison;
HSSL-G190 owns a distinct legacy SymbolicAI S1 capability and bridge. Neither
future goal can rewrite revision 1 evidence or authorize production.

### Repaired-path diagnostic and semantic-calibration stop

The later external run
`hssl-matrix-20260725T092337Z-3aeabda93` repaired the execution, cache,
identity, and result-envelope defects above and completed from clean detached
source commit `3aeabda93edbd0154d1e5f4cf02749a428cf7982`. Its immutable matrix
index has byte SHA-256
`5c993212327921904b032dea310ed515562e0efa1372d60ccb38c89bafff47ab`
and semantic SHA-256
`cd48e1013337c6cf47c754eb1196403a9bb1ca5ec232c0463333ece6d8a5d7ae`.
It is diagnostic evidence only and is not a replacement pilot decision.

The repaired run established:

| Diagnostic domain | Observed result |
|---|---|
| Matrix coverage | 560 of 560 exact pilot/development coordinates |
| Stage/resource accounting | 1,812 invoked stages and exactly 1,812 released leases |
| Independent kernel | 348 invocations and 216 accepted receipts |
| Candidate outcomes | Every A1-A12 arm had the identical 18 of 40 verified coordinate set |
| Invalid controls | 56 coordinates and zero kernel-verified false positives |
| SyMAI warm cache | 110 source-bound prime misses followed by 110 measured hits and zero measured-hit model calls |
| Leanstral | 24 unselected drafts and 12 typed output-limit failures; zero selected proof candidates |
| Holdout/production | No holdout execution and no production-routing change |

Every accepted receipt selected the compiler candidate. Hammer made 168
successful solver calls, but all 168 proof texts were identical to the
compiler certificate and added no coverage. Direct Leanstral ran only in A6
and A12; its drafts were never selected. The optional arms therefore do not
yet have causal proof-efficacy evidence. A0 also omitted the kernel while
candidates invoked it, so its apparent paired gain is confounded by unequal
verification exposure.

Post-execution semantic validation then exposed a separate protocol defect.
All 240 scoped front-end receipts were initially scored incorrect, but the
result is not an identifiable all-model quality estimate:

- production ModalIR records semantics as nested `operator.family` and
  `predicate.name`, while the scorer searches incompatible generic
  `logic`/`target` keys;
- compiler/spaCy exact-match code compares the hash of a complete ModalIR
  document with the hash of a differently shaped two-field expected IR;
- the strict SyMAI response schema permits only
  `candidate_ir.propositions`, while the scorer expects logic, target, and
  class fields; and
- a vacuous successful SyMAI candidate can replace richer spaCy evidence.

Consequently, no pilot report from this run may authorize holdout. Treat the
semantic phase as `semantic_schema_incompatible`, mint no selection artifact,
and stop. HSSL-G200 owns the new content-addressed, label-blind semantic
projection and fail-closed calibration scaffold; HSSL-G201 owns its real
source-replayed scoreability calibration and non-vacuous quality gate.
HSSL-G210 owns equal A0/candidate kernel exposure and causal
optional-component rescue accounting at the data-free single-case runtime
boundary. HSSL-G211 owns authoritative persistence of each full
`CausalRuntimeEvidenceV2` into the G210 matrix, and HSSL-G212 owns execution
and independent revalidation of the real reviewed rescue population. Because
those changes alter metrics, prompts, producer contracts, routes, and
eligibility behavior, they require a new protocol/registry identity and a
fresh complete pilot/development matrix; revision 1 receipts must not be
relabelled.

The combined fixture layout also does not provide an adequate confidentiality
boundary for a future blinded evaluation. No holdout backend execution
occurred in the repaired run, but the current holdout is retired from future
selection claims. HSSL-G220 requires an independently authored replacement
outside the tuning worktree, sealed after the final source/run freeze but
before pilot/development outcomes can influence its authorship, with
append-only access receipts. HSSL-G230 owns the negative-only authorization
scaffold. HSSL-G234 through HSSL-G238 implement independent positive
validator families in parallel; local HSSL-G231 composes and tests those
validator implementations. HSSL-G239 makes external operational completion
authoritative rather than evidence-marker text. Local HSSL-G240 implements
the pinned, confined source executor and binds actual runtime environment,
cache, process, state, output, and replay namespaces to canonical
preregistered preimages.
HSSL-G203 repairs and independently validates the user-requested Leanstral P2P
topology. HSSL-G202 then freezes the final clean source, complete run plan,
and live capabilities. HSSL-G220 must then create the independently governed
replacement seal before HSSL-G201 may reveal any pilot/development outcome.
HSSL-G201 executes the semantic submatrix once and HSSL-G212 continues that
same persisted run through the causal submatrix. External HSSL-G243 validates
the actual source-execution/namespace/replay population; external HSSL-G242
then applies the HSSL-G231 validators to that exact population. HSSL-G232
only joins those externally validated receipts before freezing an exact
proposed pilot authorization. HSSL-G241 is the separate externally governed
join that source-recomputes that proposal and the complete upstream identity
chain before a custodian may release the replacement holdout. Revision-1
HSSL-G150 and its old holdout must never be reused for the new claim. Until
all of those gates close, do not execute any holdout, publish a replacement
HSSL-G170 decision, or infer production responsibility.

### Revision-2 implementation boundary

The HSSL-G200, HSSL-G210, HSSL-G211, HSSL-G230, HSSL-G234 through
HSSL-G240, local HSSL-G231, and the source-safe HSSL-G241 custodian adapter
are additive, data-free implementation work. HSSL-G203, HSSL-G202,
HSSL-G220, HSSL-G201, HSSL-G212, HSSL-G243, HSSL-G242, HSSL-G232, and
HSSL-G241 still require independently controlled operational evidence. None
of these goal records means that the revised benchmark has run, that any
candidate has passed, or that a custodian may release holdout access:

- HSSL-G200 defines the source-only semantic protocol, producer contracts, and
  validator scaffold. Its marker and synthetic tests do not establish that
  reviewed calibration sources were executed.
- HSSL-G201 owns the complete persisted 20-case/100-coordinate
  pilot/development calibration source replay and independent validation. A
  caller-supplied report CID is not authority: a CID proves byte integrity,
  not independent review or truth.
- HSSL-G210 defines compiler-first causal selection, raw-CID certificate
  identity, duplicate suppression, native-kernel sidecars, explicit
  denominators, and component cost/rate receipts. The live
  `execute_causal_runtime_case_v2` bridge now emits one shared A0 compiler
  exposure, immutable source-only frontend records, proof-context-isolated
  candidate attempts, candidate-specific native-kernel checks, CaseResult,
  telemetry/resource receipts, and causal metrics as one
  `CausalRuntimeEvidenceV2`. Build the shared exposure with
  `CompilerReferenceExposureV2.from_compiler_record(...)`; the paired
  `validate_causal_runtime_evidence_v2` entry point replays its source,
  protocol, artifact, selection, kernel, and accounting bindings. The executor
  accepts either the exact optional-plus-kernel adapter subset or the exact
  per-variant adapter mapping, for example
  `live_runtime.adapters[semantic_result.variant_id]`; in both forms it
  consumes the shared frontend evidence without re-invoking frontend
  adapters. Enum-safe DAG-JSON
  identities, CID-multihash joins to frozen legacy native-receipt SHA fields,
  exactly one targeted native attempt per candidate, and typed optional-failure
  replay close the live receipt boundary. An accepted
  candidate after a Leanstral model failure remains a terminal proof
  continuation with zero rescue credit. Synthetic tests validate this live
  bridge, but that is implementation evidence, not a benchmark result:
  operational execution still requires the real reviewed rescue population
  and a complete source-replayed matrix. `HSSLEV2108F34` proves only this
  single-case scaffold; it is not evidence that the batch or benchmark ran.
- HSSL-G211 now provides the authoritative batch/persistence bridge in
  `causal_batch.py`. It replays all supplied `CausalRuntimeEvidenceV2` values
  before the first write, derives the shared compiler-exposure population and
  causal aggregates, persists canonical per-coordinate envelopes with
  race-safe immutable resume, and rejects foreign or reduced evidence. The
  `G210RuntimeReceiptMatrixV2` join then replays pilot and development batches,
  requires the complete A0-A12/cold-warm Cartesian, and binds every full
  runtime receipt back to its reduced aggregate. Its output root must be an
  absolute private directory outside every Git repository/worktree; relative,
  symlinked, non-directory, or group/other-accessible roots fail before a
  receipt write, and created state/result/lock directories are mode 0700.
  G211 now also validates, persists, rereads, and CID-binds the matching G240
  runtime-namespace and source-orchestration evidence sets. The compatibility
  path may omit those sets for older synthetic callers, but G231 rejects that
  path: an operational positive bundle requires both G211 batches to carry
  complete live G240 evidence and private source-validation inputs. This is
  source-safe implementation evidence; it does not manufacture the real G201
  results or execute the G212 matrix.
- HSSL-G212 owns the real reviewed pilot/development rescue execution. It
  continues the exact frozen G201 run from its persisted source-only
  front-end records and cannot re-invoke those front ends. It cannot start
  until the real G201 source replay passes and the HSSL-G211 bridge validates;
  synthetic runtime tests cannot satisfy this goal.
- HSSL-G220 defines only the external-seal and custody mechanics. The seal
  commits to the raw replacement-manifest CID, protocol/attestation CIDs,
  public counts/strata, and one canonical access-ledger authority. Premature,
  mismatched, dangling, or post-crash access invalidates or blocks that seal.
  Independent authorship, review, custodian-owned append-only storage (or
  signed checkpoints), storage ACLs, and the actual replacement manifest
  remain external work; a tuning principal with direct same-path write access
  is outside the current local ledger's trust model.
- HSSL-G230 uses public revision-2 schemas and synthetic identities only to
  prove a persistable negative decision. It is intentionally incapable of
  minting a shortlist or replacement-holdout authorization;
  `HSSLEV2309D46` proves only that fail-closed scaffold.
- HSSL-G234 through HSSL-G238 independently own full-runtime
  efficacy/reliability/routing, semantic quality, reviewed-control safety,
  resource/cost/statistics/Pareto, and detached replay validation. These
  source-safe validator implementations are present, but their operational
  evidence has not been produced. The G238 replay population is
  source-derived: replay every success and the
  lexicographically lowest source-record CID in every nonempty
  split/cache/variant failure stratum. Each selected target requires a unique
  detached worktree, actual bounded process-group execution, replay run,
  process namespace, private state/output roots, and per-stage cache
  namespaces. Its private validation sources must re-open the live worktree,
  recompute the command and tracked entrypoint against the G202-frozen
  `G240SourceExecutorContractV2`, and reproduce exact semantic, terminal
  native-kernel, status, and independent-resource identities. Receipt-only,
  precomputed, partial, attached, source-stale, shared-namespace, auto-merge,
  or holdout-touching evidence is incomplete. The G238 operational path exists
  in `replay.py` and `replay_gate.py`; its local parent integration and
  source-safe regressions are complete, but no real G201/G212 record has been
  replayed.
- HSSL-G240 now implements canonical namespace policies, runtime namespace
  evidence sets, frozen source-executor contracts, actual bounded source-job
  process execution, private validation sources, source-orchestration evidence
  sets, and the detached replay bridge. Its source layout is
  explicit: `namespace_provenance.py` defines canonical runtime/replay
  preimages; `runtime_confinement.py` defines the Landlock policy and
  path-free receipt; `source_bootstrap_contract.py` freezes the two-stage
  profile and private-policy transport; `source_bootstrap.py` is the directly
  launched minimal stage that applies confinement before stage two;
  `source_bound_import.py` resolves exact pinned submodule modules without
  repeating Git after confinement; `source_executor.py` owns authenticated
  stage-two preflight and one-job execution; `source_orchestration.py` owns
  the parent-held allowlist, bounded child, receipt pipe, and evidence join;
  and `replay.py`/`replay_gate.py` consume the same contract from a different
  detached namespace. G211 persists both G240 evidence-set families, and G238
  consumes the operational replay side. `HSSLEV2405D72` marks this bounded
  local implementation after 87 source/worktree/detached-replay tests,
  21 source-reconciliation tests, 15 adversarial materialization tests, and
  four independent transport/materialization replays passed. It is not an
  operational G243 receipt.
- Before a worktree or submodule checkout, preparatory Git resolves an
  absolute non-group/world-writable system executable, requires Git 2.40 or
  newer, discards inherited Git/config/loader state, disables hooks and
  fsmonitor, rejects effective clean/smudge/process filters, rejects local or
  worktree URL rewrites and protocol overrides, and installs from an owned
  empty template. All protocols default to denied; only the exact
  already-provisioned local `file` source is enabled for the pinned
  `--checkout --no-fetch` operation. No remote-helper or network fallback is
  permitted. The executed G240 runtime then authenticates its separately
  frozen Git executable by raw CID.
- G240 confinement has four distinct authority layers. First, the parent
  source-binds the clean outer tree, recursive gitlinks, pinned interpreter
  and runtime artifacts, exact tracked bootstrap command, and private
  filesystem/port policy. Second, the single-threaded bootstrap accepts only
  standard input/output/error plus one dedicated one-shot receipt pipe,
  authenticates the source observations before confinement, and launches with
  `close_fds` rather than an unsafe Python `preexec_fn`. Third, the child sets
  `no_new_privs` and applies the exact Landlock ABI 6/7 profile: all reviewed
  filesystem rights through device `ioctl`, TCP bind/connect, abstract UNIX
  socket scope, and signal scope are handled; read/write access is restricted
  to exact job state/output/cache roots and TCP connect is granted only for
  destination port 8080. Fourth, the parent joins the canonical pipe receipt
  to the actual bounded/reaped process, and G211/G238 plus external G243 must
  source-replay its public CIDs against the private paths and process
  observations.
- Landlock is not a container or endpoint-authentication authority. Its TCP
  rule authenticates a destination **port**, not an IP address; it does not
  restrict UDP or pathname UNIX sockets, and it cannot revoke a descriptor
  opened before confinement. Those residuals are handled by the minimal
  bootstrap, zero inherited sockets, exact descriptor inspection,
  `close_fds`, the fixed child environment, endpoint-identity checks, and
  external negative tests. Unsupported/newer ABIs, broader paths, an extra
  inherited descriptor/socket, or any alternate TCP port fail closed. Port
  8080 is the G240 child's outbound connection to the already-running local
  HTTP model API. Port 19001 is the separately operated G203 P2P listener; the
  benchmark child neither binds nor receives a Landlock grant for 19001.
  These confinement and checkout-mode/umask claims are Linux/POSIX-specific,
  and production fails closed without the required Landlock ABI. Inspecting
  the host `landlock.h` constants only confirmed that ABI; the header is not a
  project dependency. The reviewed repository/configuration threat model is
  static and non-root. Concurrent same-user mutation between Git preflight
  and use remains a documented TOCTOU residual controlled by frozen exclusive
  worktrees; generic preparation Git is path/mode/version authenticated, while
  the runtime Git in the G240 contract is separately CID-authenticated.
- HSSL-G231 now composes the positive validator families and additionally
  requires both persisted G211 split batches, their live G240 runtime
  namespace/source-orchestration evidence, and operational G238 private replay
  sources. It source-recomputes those inputs instead of accepting their CIDs as
  assertions. `HSSLEV2312F74` marks the bounded local composite after its exact
  51-test source-safe suite and the final G240 trust-chain regressions passed.
  No operational positive bundle exists; external G242 remains unfulfilled.
- HSSL-G239 owns typed external-completion authority. Marker discovery remains
  useful for locating implemented code, but operational completion requires a
  source-bound external receipt that binds the clean commit/tree, recursive
  gitlinks, run plan, parent ledger, artifact CIDs, and an independent
  validator CID. Every operational goal declares
  `Completion authority: external`, which makes it fail closed before the
  first authority file is supplied; a same-named source marker cannot
  bootstrap completion. Nested supervisor commit `2696e5ca` adds four
  defense-in-depth corrections: wrapped objective fields and field rewrites
  retain the complete text; persisted AST rows are never evidence/cache
  authority and every current source/symbol/token/embedding/AST field is
  recomputed; declarations, aliases, durable authority CIDs, and typed
  `external_operational_completion` evidence use one sticky fence; and
  duplicate task CIDs merge only for semantically equivalent work, while
  conflicting identities remain invalid even if one copy claims success.
  Sensitive bytes remain outside the repository. The local supervisor
  validates canonical structure and current Git identity; retrieval of CID
  payloads and validator-signature verification belong to the separately
  governed authority trust root.
- HSSL-G203 owns the intended Leanstral P2P repair and live topology receipt.
  It must use the existing shared service, custom port 19001, every
  policy-approved active local address, configured bootstrap/rendezvous peers,
  pubsub/floodsub policy, and an independently successful dial. Port 8000,
  one container-only address, an HTTP-only substitution, or a duplicate model
  server cannot satisfy this goal. An inference-free diagnostic collection
  from submodule source `5d969f284b0c0b5dbf2091ec0abc2696d6a2a441`
  now passes all four canonical bootstrap dials, same-service rendezvous, an
  independent client-process dial, and direct-model-manager/MCP model-list
  agreement. It advertises `10.10.0.14`, `10.8.0.99`, and `172.30.4.2` on
  port 19001 from a wildcard listener; diagnostic receipt CID
  `bafkreiacx2qd2ftem6cuyvx2m3eyp7ll4uhk5xs3erxn5cioydxs72wwwy`.
  This is not the final source-bound G203 receipt because the outer source
  freeze still follows it, and the persistent user service remains on its
  older deployment until the reviewed submodule source is promoted.
- HSSL-G202's implementation now constructs its G201 and G210 preflight plans
  from source-only targets, cases, and canonical `AblationPlan` values before
  any outcome exists. Its frozen run input binds the preregistered G240
  executor-contract policy, and its runtime identity projection binds adapter,
  canonical adapter module, full observed source provenance, environment, and
  coordinate identities without deriving a preflight input from results.
  This fixes the former circular preflight/provenance boundary; it is not an
  external completion. The final G202 operation still runs only after all
  implementation and validator code is clean and committed, and it still
  requires a detached source/gitlink receipt, immutable 520-coordinate
  A0-A12 pilot/development plan, live capability freeze, resource policy,
  disjoint namespaces, independently authorized bounded non-corpus component
  smokes, and a fresh HSSL-G203 P2P receipt. Leanstral evidence must
  distinguish the logical `leanstral_local` route from `llamacpp` transport.
- HSSL-G243 is the external operational half of local HSSL-G240. Only after
  G201 and G212 exist may an independent validator source-recompute their
  complete process, environment, confinement, physical cache, state, output,
  and detached-replay population. Synthetic namespace receipts or the local
  G240 implementation marker cannot satisfy it.
- HSSL-G242 is the external operational half of local HSSL-G231. It applies
  the frozen positive-validator implementation to the exact
  G201/G212/G220/G243 source graph without re-invoking a measured component.
  Missing or negative evidence remains an explicit negative bundle and cannot
  be converted into a positive CID by a local task, marker, or merge receipt.
- HSSL-G232 never invokes a producer, solver, model, or native kernel. It joins
  the already persisted G201/G212 evidence, HSSL-G220 seal identity, G202
  freeze, externally validated G243 runtime population, and the exact G242
  application of the HSSL-G231 gates. Only a complete nonempty pass can
  propose an exact replacement-holdout authorization. Constructing that
  object, even with one to four canonical arm IDs, does not release holdout
  access and does not authorize production.
- HSSL-G241 is the sole custodian-release boundary. It reparses the complete
  positive G231 implementation through the exact G242 bundle and validates the
  G202/G201/G211/G212/G220/G243/G232 identity chain, then requires a current
  HSSL-G239-governed external receipt with independent decision, validation,
  custody, and execution authorities. The released arms must equal the
  deterministic source-derived shortlist; arbitrary one-to-four arm lists,
  canonical-CID-only constructors, booleans, source markers, or
  self-authorization fail closed. The source-safe gate is implemented in
  `custodian_release.py`, including exact G232 proposal replay, out-of-band
  G239 and custodian trust roots, and append-only private-ledger checks. No
  G241 implementation marker, external release receipt, or holdout access
  exists. The G239 external validator and the holdout custodian are distinct
  authorities: an external-completion receipt does not itself grant custody,
  and the custodian does not manufacture the receipt it is required to
  verify. G241 records no holdout activity and cannot authorize production.

### G241 operational custody and rollback boundary

The G241 source implementation is hardened, but it does not create the
independent operational authorities that it requires:

- The externally pinned custody trust root names a canonical absolute Git
  executable path and a CID that binds both that path and the executable's raw
  CID. G241 opens that regular, executable, non-symlink file with no-follow
  descriptors and executes the already-open inode, not an ambient `git`.
  Subprocesses receive a minimal fixed environment; ambient `PATH`, `GIT_*`,
  `PYTHON*`, and `LD_*` injection is discarded. Every invocation overrides
  repository configuration to disable fsmonitor, the untracked cache, and
  hooks. Source inspection also disables replacement refs, rejects
  source-affecting local worktree/symlink/case/sparse/attribute/exclude
  indirection and assume-unchanged or skip-worktree entries, requires the
  stage-zero index to equal the pinned `HEAD` tree, and hashes every live
  tracked blob and executable mode. Ignored importable, executable, symlink,
  or native-library files fail closed.
- A consuming caller must use the lock-scoped G241 custody transaction. It
  holds the cooperating source, access-ledger, and release-ledger locks from
  validation through custody. It fsyncs the single-use `access_granted`
  receipt and then a typed release-ledger consumption tombstone before
  resolving the sealed path or calling the custodian. The tombstone binds the
  release and grant CIDs, both ledger file identities, purpose, executor,
  custodian, trust root, and external monotonic-store policy. Success or
  failure then receives one terminal access receipt under the same locks.
  First creation fsyncs both each ledger inode and its containing directory.
  No property or callback on the custodian object is evaluated until the
  grant and tombstone are durable. Read-only receipt inspection is deliberately
  not an access authority.
- The release-ledger tombstone makes the consumed release cease to be the
  current head. Consequently, truncating only the access ledger back to empty
  on the same inode cannot replay that release. Conversely, if only the
  tombstone is truncated, the intact access ledger remains fail-closed.
  Device/inode anchors also detect unlink, rename, and replacement-file
  substitution.
- Local `flock` locks are advisory, and local mutable files cannot prove
  monotonicity against a same-UID adversary that rolls **both** ledgers back to
  their exact earlier byte states on their original inodes. Nor can a local
  lock prevent a noncooperating source writer. Operational G241 therefore
  requires the release-ledger authority named by the trust root to be backed
  by an independently governed, queried monotonic append-only store, and the
  source/custody namespace to be externally enforced read-only for the
  transaction. If those controls are absent, G241 must remain blocked.
  Synthetic test identities exercise joins and failure behavior only; they
  are not production custody or monotonic-store authority.

The compatibility bridge from an IPFS CID to a frozen legacy SHA-256 receipt
field extracts the CID's `sha2-256` multihash digest. New structured and raw
identities retain their complete CIDv1/base32 codec identity rather than
introducing new bare hashes.

Safe implementation validation does not load benchmark fixtures or holdout
content:

**SOURCE-SAFE NOW — implementation tests only; no operational receipt:**

```bash
python -m pytest -q \
  tests/integration/benchmarks/logic_pipeline/test_causal_proof_ablation.py \
  tests/integration/benchmarks/logic_pipeline/test_causal_rescue_manifest.py \
  tests/integration/benchmarks/logic_pipeline/test_causal_rescue_metrics.py \
  tests/integration/benchmarks/logic_pipeline/test_causal_runtime.py \
  tests/integration/benchmarks/logic_pipeline/test_causal_runtime_batch.py \
  tests/integration/benchmarks/logic_pipeline/test_runtime_confinement.py \
  tests/integration/benchmarks/logic_pipeline/test_source_orchestration.py \
  tests/integration/benchmarks/logic_pipeline/test_fresh_replay_gate.py \
  tests/integration/benchmarks/logic_pipeline/test_fresh_worktree_replay.py \
  tests/integration/benchmarks/logic_pipeline/test_positive_gate_bundle.py \
  tests/integration/benchmarks/logic_pipeline/test_g231_operational_conformance.py \
  tests/integration/benchmarks/logic_pipeline/test_custodian_release.py \
  tests/integration/benchmarks/logic_pipeline/test_replacement_holdout_seal.py \
  tests/integration/benchmarks/logic_pipeline/test_revised_pilot_authorization.py \
  tests/integration/benchmarks/logic_pipeline/test_revised_pilot_positive_gates.py \
  tests/unit/benchmarks/logic_pipeline/test_statistics.py
```

The synthetic causal-runtime and focused revision-2 suites must pass together
with the broader safely selected live/runtime/kernel regressions. These tests
establish implementation coverage only and do not include a reviewed
benchmark run; report exact counts from the current commit rather than
preserving counts from an earlier revision in this runbook.

Do not operationally complete HSSL-G202 until every implementation lane passes
from a clean committed source and typed external-completion reconciliation is
available. Its source-only preflight objects are implementation prerequisites,
not a live freeze or external receipt. After G202, independent G220 custody
must complete before G201 may reveal pilot/development outcomes. Do not
advance to HSSL-G212 until the real G201 source replay passes and the
HSSL-G211 bridge validates. After G212, require HSSL-G243 to externally
recompute the complete G240 source-execution/namespace/replay population, then
require HSSL-G242 to externally apply every local HSSL-G231 validator to that
exact population. Do not advance to HSSL-G232 until both external joins pass
and G220 authorship/review/custody and append-only storage remain valid. Do
not advance to HSSL-G241 until G232 produces a nonempty exact proposal and
every upstream identity can be source-recomputed under the same clean run. Do
not advance to replacement-holdout access until an independent custodian
validates the externally governed G241 release receipt; no such receipt
currently exists.

The immutable predecessor decision is:

```text
docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision.json
byte SHA-256     0e53798d3f1deaab040cf99f10034644f421ffd51f15090a948aa7085041a84e
semantic SHA-256 80823442e5115b2f499a2e77a11817dff555494ca0ecccfc79e59cbf423b7cce
disposition      gather_more_evidence / no production promotion
```

The v2 publication preserves that object byte-for-byte and links it as its
predecessor. A timestamp, replacement filename, or structurally valid
reassessment cannot supersede the predecessor unless all named source
artifacts and the predecessor itself match their recorded identities.

Every experimental arm has an explicit evidence disposition:

| Arm | Reassessment evidence | Replacement decision |
|---|---|---|
| A0 | Frozen current route; measured reference coordinates | Retain unchanged as reference only; not promoted or declared superior |
| A1 | Full-spaCy deterministic core; zero kernel acceptances and no semantic-quality receipt | Not selected |
| A2 | A1 plus deterministic Hammer; no kernel-verified marginal gain | Not selected |
| A3 | Hammer-first and bounded Leanstral fallback; observed nondominated only on an ineligible frontier | Not selected |
| A4 | A3 plus ambiguity-gated SyMAI; no eligible quality result | Not selected |
| A5 | A4 with SyMAI always on; measured calls without eligible benefit | Not selected |
| A6 | Leanstral before Hammer; proof-order benefit not established | Not selected |
| A7 | A4 with regex/legal parser; observed nondominated only on an ineligible frontier | Not selected |
| A8 | A4 with forced spaCy blank fallback; no eligible full-model/fallback comparison | Not selected |
| A9 | A4 without Hammer; no eligible Hammer marginal-value result | Not selected |
| A10 | A4 with pinned learned Hammer selector; no eligible selector benefit | Not selected |
| A11 | A4 with SyMAI/LLM premise ranking; no eligible ranking benefit | Not selected |
| A12 | Always-on duplicated-work stress arm; measured work does not establish benefit | Not selected |
| S1 | Legacy SymbolicAI/kernel-truth diagnostic; typed unavailable coordinates retained | Diagnostic only; never candidate-eligible |

The measured and missing tradeoffs remain separate:

| Domain | Reassessment result | Decision use |
|---|---|---|
| Quality | 520 non-missing proof-efficacy observations, zero kernel acceptances; independent semantic-quality rate null with a reason | No arm satisfies the frozen quality gate |
| Safety | 56 invalid-control coordinates and zero kernel-verified false positives | Required containment evidence, but not sufficient efficacy evidence |
| Latency | 433009.90631 ms total and 773.231976 ms mean per coordinate across the complete matrix | Retained as measured pilot/development cost; no holdout latency claim |
| Resources | 748 model calls, 120 solver processes, 1580 stage/resource leases, and 360 retries | Retained as measured cost; never recast as benefit |
| Reliability and routing | All 560 coordinates terminal; 96 kernel invocations, zero acceptances, no arm substitution or fallback | Supports completeness and trust-boundary checks, not promotion |
| Complexity/Pareto | A1, A3, and A7 observed nondominated; no eligible nondominated candidate | No ranking or truncation; ineligible frontier cannot select an arm |
| Holdout and replay | Zero authorized pairs and an empty replay population | All holdout-only values remain null; no efficacy or replay claim |

The immutable baseline manifest is:

```text
workspace/benchmarks/hammer-symai-spacy-leanstral/a0-baseline-v1/state/baseline-manifest.json
SHA-256 6b37a6493d6328102b558258843218128ad0bf6f8cc7be13f8d0c2e0bb61e156
source commit 2a1be00b1b76e6652c25d418752affbf0f85d176
```

The canonical reassessment holdout phase receipt is:

```text
workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/holdout-evaluation-v2.json
byte SHA-256     9e712b9ed1fb67c80115d12e3bc92850f23da601543fa59a4cbd700a54b0df9d
semantic SHA-256 e408d7364209dde32ff4f987ba2845306ab226c2f442c0a3d4abfb18521ee44d
state blocked / sealed_unopened
```

The reviewed corpus manifest and frozen holdout split identities are:

```text
corpus manifest 58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26
holdout split   c7b969ed19a1248143740068e2853ca6132ba3d65dfeec4133e37fad55dbab4a
```

## Ownership and delegation matrix

“Allowed benchmark responsibility” describes an experimental boundary, not
production authorization.

| Component or policy | Operational owner | Allowed benchmark responsibility | Authority and fallback | Current disposition |
|---|---|---|---|---|
| A0 current route | Logic-pipeline maintainer | Frozen current codec, including the recorded `spacy.blank:en` fallback | Existing deterministic validators; no experimental escalation | Retain unchanged as reference; not selected as a measured winner |
| Full-model spaCy | NLP adapter owner | Tokens, sentences, lemmas, dependencies, entities, SRL features, and modal cues | Linguistic evidence only; unavailable full model stays unavailable and never becomes blank/regex success | No expanded production role; semantic quality and paired holdout value are unavailable |
| SyMAI | Model-routing owner | Bounded structured semantic candidate or contract repair through the existing `llm_router` | Canonical schema/parser validates; no recursive routing or second model manager | No production role; measured calls produced no eligible candidate and paired holdout value is unavailable |
| Legacy SymbolicAI S1 | Diagnostic owner | A future source-bound prediction/kernel-truth comparison only if its historical identity can be recovered | Distinct capability and bridge; modern SyMAI is never a substitute; prediction is non-authoritative | Revision 1 remains typed unavailable; HSSL-G190 is future pilot/development work only |
| Hammer | Proof-search owner | Premise selection, translation, bounded solver portfolio, normalization, and native reconstruction | Solver/reconstruction evidence is untrusted until a separate native-kernel receipt accepts it | No production role; no kernel-verified gain or paired holdout tradeoff |
| Leanstral | Model-service owner | One bounded revision 1 Lean draft; adapter transport can accept one reviewed repair request only in a separately revised graph | Draft only; no `sorry`, `admit`, obligation rebinding, or model proof claim; kernel checks independently | No production role; revision 1 repair efficacy is unassessed and HSSL-G180 owns any future comparison |
| Native kernel | Kernel/toolchain owner | Check the exact terminal obligation and emit the accepted receipt | Sole verification authority; no fallback authority | Mandatory for every proof claim |
| P0 always-on | Benchmark decision owner | Comparison policy only | Same resource limits and kernel boundary as every policy | Rejected for production at this revision |
| P1 deterministic-first | Benchmark decision owner | Comparison policy only | At most one bounded cross-family fallback | Rejected for production at this revision |
| P2 proof-family | Benchmark decision owner | Pre-outcome deterministic family routing | Family signal cannot alter budgets or proof authority | Rejected for production at this revision |
| P3 bounded learned | Benchmark decision owner | Development-trained selector with frozen provenance and thresholds | Development-only training; thresholds frozen before holdout; bounded routes only | Rejected for production at this revision |
| Objective supervisor | Benchmark coordinator | Compile the heap, discovery receipts, bundles, graph, and todo-vector index | Planning only unless bundle submission/start is separately approved | Local ingestion only |
| Production route | Service owner plus change approver | Review a future passed decision | Separate change, rollout, canary, and rollback approval required | No change authorized |

The person who operates a backend must not self-approve its proof claims. The
benchmark coordinator validates artifacts and missingness. The kernel owner
controls verification identity. The production owner decides whether a later
passed benchmark justifies a separately reviewed rollout.

## Trust boundaries and invariants

Every run must preserve all of these invariants:

1. Use a detached worktree at a full commit. Put all mutable state outside the
   active checkout and outside its Git common directory.
2. Never clean, reset, stash, switch, merge, or overwrite the active checkout.
   `prepare_isolated_worktree` uses the safe `git worktree` boundary, creates
   no branch, and records `auto_merge=false`.
3. Keep protocol, run, variant, split, and cold/warm cache namespaces distinct.
   Resume only an exact canonical job identity.
4. Record requested and effective capabilities. Missing or degraded backends
   remain typed missingness; never substitute another arm.
5. Keep model, solver, kernel, validation, and CPU resource lanes separate.
   SyMAI and Leanstral may reference only the one pinned shared model service.
6. Use bounded process groups and retain timeout/cancellation results. An
   orphaned child, cache contamination, holdout leak, invalid-control false
   positive, or corrupt provenance chain is an immediate stop.
7. Count a proof only when a native-kernel accepted receipt binds the case,
   route, environment, stage digests, and terminal outcome.
8. Keep S1 outside primary metrics. It is a non-authoritative safety
   diagnostic. Preserve revision 1 typed-unavailable behavior unless a
   distinct historical `legacy_symbolicai` identity is source-bound; never
   substitute modern SyMAI.
9. Do not inspect holdout semantic targets or outcomes before an exact passed
   pilot receipt authorizes an exact nonempty shortlist.
10. Do not tune prompts, policies, identities, thresholds, or resources after
    holdout access.
11. Do not promote production automatically. A passed benchmark is evidence
    for a separate production change, never the change itself.

## Clean-worktree operating flow

Run commands from the repository root unless a step explicitly changes into
the detached worktree. First record the source state:

**SOURCE-SAFE NOW:**

```bash
git rev-parse --show-toplevel
git rev-parse --verify HEAD
git status --short
git submodule status --recursive
```

Choose a unique run ID and an operations root outside this checkout and its
Git common directory. Do not use the default in-repository benchmark root for
worktree preparation.

**SOURCE-SAFE NOW:**

```bash
export HSSL_RUN_ID=hssl-reproduce-20260724T000000Z
export HSSL_OPERATIONS_ROOT=/var/tmp/hssl-benchmark-operations
export HSSL_SOURCE_ROOT="$PWD"
export HSSL_BASE_REVISION="$(git rev-parse --verify HEAD)"
test ! -e "$HSSL_OPERATIONS_ROOT/$HSSL_RUN_ID"
```

Create the detached worktree and its safety receipt:

**SOURCE-SAFE NOW:**

```bash
python - <<'PY'
import os
from pathlib import Path
from benchmarks.logic_pipeline import RunPaths
from benchmarks.logic_pipeline.capabilities import prepare_isolated_worktree

paths = RunPaths.for_run(
    os.environ["HSSL_RUN_ID"],
    benchmark_root=Path(os.environ["HSSL_OPERATIONS_ROOT"]),
)
receipt = prepare_isolated_worktree(
    Path(os.environ["HSSL_SOURCE_ROOT"]),
    run_paths=paths,
    base_revision=os.environ["HSSL_BASE_REVISION"],
)
print(receipt.worktree_root)
print(paths.receipts / "worktree-safety.json")
PY
```

The command must fail rather than continue if the state root overlaps the
source checkout, the target exists, the revision is not a full commit, the
worktree is attached to a branch, or source HEAD/branch/status changes. Review
the receipt and set the worktree path only after it passes:

**SOURCE-SAFE NOW:**

```bash
export HSSL_WORKTREE="$HSSL_OPERATIONS_ROOT/$HSSL_RUN_ID/worktrees/source"
cd "$HSSL_WORKTREE"
if git symbolic-ref --quiet HEAD; then
  echo "benchmark worktree is not detached" >&2
  exit 1
fi
git rev-parse --verify HEAD
git status --short
```

Keep the original status output. At handoff, compare it with a new status from
the original checkout; any change is an incident.

## Preflight and capability probe

The basic capability inventory below is read-only: it does not import optional
backend parents, install software, start services, or make inference calls. It
emits a diagnostic record for spaCy, SyMAI, `llm_router`, Hammer solvers,
Leanstral, Lean/Lake, cache, and the resource scheduler. It is necessary but
does not by itself satisfy the final HSSL-G202 live eligibility freeze. That
freeze separately requires an approved window for bounded, non-corpus
component smokes, including exact model-manager/MCP discovery and the frozen
Leanstral transport scope. The implementation and basic trust boundary live
in `benchmarks/logic_pipeline/capabilities.py`.

The 2026-07-26 pre-freeze diagnostic run
`hssl-20260726T014546Z` repaired and exercised the requested runtime without
opening benchmark sources:

- spaCy 3.8.14 loaded `en_core_web_sm` 3.8.0 with parser, lemmatizer, NER,
  sentence, tag, dependency, and lemma annotations present and no blank-model
  fallback;
- SymbolicAI/SyMAI 1.14.0 used requested and effective provider
  `ipfs_accelerate_py` and model `Leanstral-119B`; its inner router resolved
  exactly to `leanstral_local` and
  `Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4` on the already running
  `http://127.0.0.1:8080/v1` service, with one call, zero retries, no fallback,
  no recursive routing, and a valid structured result;
- Hammer/cvc5, Lean, Lake, the exact Leanstral service, cache backend, and
  resource scheduler also probed available, so all eight requested capability
  classes were present; and
- the SyMAI smoke exposed and repaired an eager import of the optional Copilot
  CLI/cache stack on the Leanstral-only route. It also proved that SyMAI creates
  writable configuration/log files, so an operational child must copy the
  pinned configuration into its own state-scoped prefix and must never share
  the provisioned environment's prefix.

These observations are diagnostics from uncommitted source. They show that the
dependencies and route can work, but they are neither a clean-source
capability freeze nor an HSSL-G202 completion receipt. Repeat every probe and
bounded smoke from the final clean detached recursive worktree; a differing
package, module, route, model, endpoint, configuration, or source identity
starts a new run rather than inheriting this result.

**SOURCE-SAFE NOW — read-only/non-corpus inventory only:**

```bash
python - <<'PY'
import os
from pathlib import Path
from benchmarks.logic_pipeline import RunPaths
from benchmarks.logic_pipeline.capabilities import (
    capability_inventory_cid,
    probe_runtime_capabilities,
    write_capability_inventory,
)

paths = RunPaths.for_run(
    os.environ["HSSL_RUN_ID"],
    benchmark_root=Path(os.environ["HSSL_OPERATIONS_ROOT"]),
)
inventory = probe_runtime_capabilities(
    os.environ["HSSL_RUN_ID"],
    paths,
    source_commit=os.environ["HSSL_BASE_REVISION"],
)
destination = paths.receipts / "capability-inventory.json"
write_capability_inventory(inventory, destination)
print(destination)
print(capability_inventory_cid(inventory))
for record in inventory.capabilities:
    print(record.kind.value, record.status.value, record.reason or "")
PY
```

Do not install a missing capability during a run. Close the run as explicit
missingness, provision or repair the service in a separate approved window,
and begin a new run ID with a new probe. A capability identity, version,
model, solver, kernel, source commit, or environment change invalidates
comparison with the earlier inventory.

Record Leanstral networking truthfully. The revision-2 model lock and
submodule source request wildcard P2P on custom port 19001, policy-selected
local-address advertisement, canonical bootstrap peers, and same-service-peer
rendezvous. Pubsub and floodsub remain explicitly disabled because no router
is wired into the current node. This is the separately supervised G203 P2P
service listener; it is not the G240 benchmark child's network allowance.
G240 may connect outward only to the existing HTTP model API's TCP destination
port 8080, and Landlock's port-only rule does not authenticate the peer IP.
The child may neither bind nor connect to port 19001. The live diagnostic
exposed two real
transport defects after the initial source-safe implementation: the installed
Trio API requires captured output rather than `stdout=subprocess.PIPE`, and
py-libp2p TCP requires canonical `/dnsaddr/` bootstrap peers to be resolved to
same-peer plain-TCP descendants before dialing. Submodule commits `f631db4c`
and `5d969f28` fix those boundaries; the configured DNSADDR identity remains
in the public policy and attempt evidence. The focused topology suite passes
32 tests, and the inference-free diagnostic receipt
`bafkreiacx2qd2ftem6cuyvx2m3eyp7ll4uhk5xs3erxn5cioydxs72wwwy` exercises
bootstrap, rendezvous, independent dialing, model-manager discovery, and MCP
model listing. This still is not operational completion: repeat the collector
after the final clean outer commit and obtain independent external authority
before HSSL-G202. Do not silently substitute the HTTP endpoint or port 8000,
reuse the serving process as the purported independent client, or treat a
source-side synthetic or pre-freeze diagnostic receipt as completion.

Before execution, validate the dependency-free contracts:

**SOURCE-SAFE NOW — dependency-free unit contract only:**

```bash
python -m pytest tests/unit/benchmarks/logic_pipeline -q
```

The following runner and report commands may load the historical benchmark
package. They are retained only to reproduce revision 1 and are prohibited in
the revision-2 readiness lane.

**HISTORICAL REVISION 1 ONLY:**

```bash
python benchmarks/logic_pipeline/runner.py \
  --variant A0 --split pilot --validate-only
python benchmarks/logic_pipeline/report.py --section frontend --validate
python benchmarks/logic_pipeline/report.py --section proof --validate
python benchmarks/logic_pipeline/report.py --section efficiency --validate
```

These report validations may truthfully validate explicit missingness. They do
not by themselves establish an efficacy pass.

## Objective ingestion and backlog alignment

Copy the seed into the run-specific operations state. Never write generated
task state back into the seed or objective heap. The benchmark-facing
ingestion boundary is the repository's
`ipfs_accelerate_py.agent_supervisor.objective_daemon` flow shown below; it
must preserve the same run-scoped graph, discovery, bundle, and todo-vector
identities.

**SOURCE-SAFE NOW — no reconciliation, generation, or submission:**

The benchmark worktree initializes every recorded gitlink so source identity
can be verified without moving any pin. Objective discovery must not treat
those dependency and reference repositories as implementation evidence. The
explicit exclusions below retain the two in-scope codebases—the root
`ipfs_datasets_py` tree and `ipfs_accelerate_py`—while fencing their initialized
dependencies. The source-safe pass also disables the optional persistent AST
dataset. Direct tracked-source evidence scanning remains enabled, but the
nomination-only integrated analysis cache cannot materialize or reread an
unbounded multi-gigabyte snapshot during task-board bootstrap.

```bash
export HSSL_SUPERVISOR_ROOT="$HSSL_OPERATIONS_ROOT/$HSSL_RUN_ID/supervisor"
export HSSL_OBJECTIVE_PATH="$HSSL_WORKTREE/docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md"
export HSSL_TODO_PATH="$HSSL_SUPERVISOR_ROOT/benchmark.todo.md"
mkdir -p "$HSSL_SUPERVISOR_ROOT"
cp docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark.todo.seed.md \
  "$HSSL_TODO_PATH"

PYTHONPATH=ipfs_accelerate_py python -m \
  ipfs_accelerate_py.agent_supervisor.objective_daemon \
  --repo-root "$HSSL_WORKTREE" \
  --objective-path "$HSSL_OBJECTIVE_PATH" \
  --todo-path "$HSSL_TODO_PATH" \
  --discovery-dir "$HSSL_SUPERVISOR_ROOT/discovery" \
  --bundle-dir "$HSSL_SUPERVISOR_ROOT/objective_bundles" \
  --dataset-dir "$HSSL_SUPERVISOR_ROOT/objective_datasets" \
  --graph-path "$HSSL_SUPERVISOR_ROOT/objective_graph.json" \
  --todo-vector-index-path "$HSSL_SUPERVISOR_ROOT/objective_bundles/todo_vector_index.json" \
  --plan-evaluation-path "$HSSL_SUPERVISOR_ROOT/plan_evaluations.json" \
  --analysis-escalation-path "$HSSL_SUPERVISOR_ROOT/analysis_escalation.json" \
  --objective-generation-path "$HSSL_SUPERVISOR_ROOT/objective_generation.json" \
  --scan-exclude-path tests/fixtures \
  --scan-exclude-path tests/reasoner/fixtures \
  --scan-exclude-path tests/mcplusplus_profile_h/fixtures \
  --scan-exclude-path tests/unit/optimizers/graphrag/fixtures \
  --scan-exclude-path ipfs_datasets_py/tests/reasoner/fixtures \
  --scan-exclude-path workspace/benchmarks \
  --scan-exclude-path workspace/leanstral-smoke \
  --scan-exclude-path security_ir_artifacts/corpora \
  --scan-exclude-path data/agent_supervisor \
  --scan-exclude-path docs/performance_snapshots \
  --scan-exclude-path .tools/ipfs_kit_py \
  --scan-exclude-path ipfs_kit_py \
  --scan-exclude-path ipfs_datasets_py/logic/CEC/DCEC_Library \
  --scan-exclude-path ipfs_datasets_py/logic/CEC/Eng-DCEC \
  --scan-exclude-path ipfs_datasets_py/logic/CEC/ShadowProver \
  --scan-exclude-path ipfs_datasets_py/logic/CEC/Talos \
  --scan-exclude-path ipfs_datasets_py/multimedia/convert_to_txt_based_on_mime_type \
  --scan-exclude-path ipfs_datasets_py/multimedia/omni_converter_mk2 \
  --scan-exclude-path ipfs_datasets_py/processors/web_archiving/common_crawl_search_engine \
  --scan-exclude-path ipfs_accelerate_py/docs/fastmcp \
  --scan-exclude-path ipfs_accelerate_py/docs/mcp-python-sdk \
  --scan-exclude-path ipfs_accelerate_py/ipfs_accelerate_py/mcplusplus \
  --scan-exclude-path ipfs_accelerate_py/ipfs_datasets_py \
  --scan-exclude-path ipfs_accelerate_py/ipfs_kit_py \
  --scan-exclude-path ipfs_accelerate_py/ipfs_model_manager_py \
  --scan-exclude-path ipfs_accelerate_py/ipfs_transformers_py \
  --scan-exclude-path ipfs_accelerate_py/test/doc-builder \
  --scan-exclude-path ipfs_accelerate_py/test/huggingface_doc_builder \
  --scan-exclude-path ipfs_accelerate_py/test/huggingface_transformers \
  --task-prefix HSSL-BENCH- \
  --max-findings 64 \
  --surplus-findings-per-goal 1 \
  --no-reconcile-goal-completion \
  --no-generate-bounded-work \
  --no-persist-ast-dataset
```

The first ingestion has no external authority and therefore omits the
completion-receipt option. A separately governed receipt producer and an
independent external validator—not the local supervisor, and not the holdout
custodian merely by virtue of being custodian—must produce and validate the
identity-only authority JSON outside the repository. Only after that authority
exists may an operator repeat the same command, remove
`--no-reconcile-goal-completion`, and add:

**FUTURE AUTHORIZED — exact typed external authority required:**

```bash
--objective-external-completion-receipt-path \
  "$HSSL_EXTERNAL_COMPLETION_AUTHORITY"
```

That file must contain only the typed source, gitlink, parent-ledger, run-plan,
artifact-CID, producer, and independent-validator identities defined by the
supervisor schema. It must not contain paths, source text, labels, expected IR,
proof obligations, manifests, holdout bytes, model output, or secrets.

The absence of `--submit-bundles` is intentional. Every writable supervisor
output above is run-scoped outside the source tree. Exclusions are resolved
against the repository root and must remain in the scan receipt; they prevent
content inspection, cached-AST reuse, and generated metadata from crossing
the benchmark confidentiality boundary. Inspect the todo board, objective
graph, discovery receipts, bundle index, and todo-vector index before any
submission.

The supervisor also enforces a mandatory source-protection policy independently
of the repeated CLI exclusions. It rejects protected path components such as
fixtures, corpora, holdouts, workspaces, security IR artifacts, and performance
snapshots; the `data/agent_supervisor` pair; symlinks; and resolved paths outside
the repository. The same component policy applies beneath initialized
immediate submodules. This source-safe command creates no persistent AST
dataset. If a later bounded diagnostic run enables that optional dataset,
persisted rows remain untrusted history, not source, symbol, embedding, or
AST-cache authority: every current tracked candidate must be recomputed from
the current file after the mandatory path policy passes. Prior rows may
contribute only bounded deletion/rename diagnostics, and a poisoned row that
claims a benign current path and Git blob cannot satisfy an objective.

External completion is a scheduler fence, not merely a reconciliation hint.
The generic completion-authority fields and the revision-2 operational goal
identities fence each external goal and its unfinished descendants from local
task generation, successful-status shortcuts, merge receipts, and duplicate
task-CID aliases. Reconciliation evaluates external gates before descendants,
so a stale or reopened gate cannot let a child advance in the same pass.
`--no-reconcile-goal-completion` deliberately trusts no recorded external
completion: it fences those gates and descendants while leaving independent
local implementation goals eligible for bounded work and capacity. Focused
completion/graph tests and daemon/refill integration tests must pass before
using this behavior to restart the board.

HSSL-G170 must remain downstream of HSSL-G160, which must retain its HSSL-G150
and HSSL-G140 source chain. Future HSSL-G180 repair-revision and HSSL-G190
legacy-S1 work stays downstream of HSSL-G170 without retroactively changing
the frozen v2 publication. For revision 2, verify these exact edges:

- HSSL-G211 is a child of HSSL-G210 and HSSL-G230 is a child of HSSL-G211.
- HSSL-G234 through HSSL-G239 are independent children of HSSL-G230.
- HSSL-G231 joins HSSL-G234 through HSSL-G238.
- HSSL-G203 joins HSSL-G112 and HSSL-G239.
- HSSL-G240 joins HSSL-G211 and HSSL-G230.
- HSSL-G202 joins HSSL-G200, HSSL-G203, HSSL-G211, HSSL-G231, HSSL-G239,
  and HSSL-G240.
- HSSL-G220 is a child of HSSL-G202 and must externally complete before G201
  can reveal any measured outcome.
- HSSL-G201 joins HSSL-G202 and HSSL-G220.
- HSSL-G212 retains HSSL-G201, HSSL-G211, and HSSL-G202.
- HSSL-G243 joins HSSL-G201, HSSL-G202, HSSL-G212, HSSL-G239, and the local
  HSSL-G240 implementation, and externally validates the actual runtime
  population.
- HSSL-G242 joins HSSL-G201, HSSL-G202, HSSL-G212, HSSL-G220, the local
  HSSL-G231 implementation, HSSL-G239, and HSSL-G243, and externally
  recomputes the complete positive bundle.
- HSSL-G232 retains HSSL-G201, HSSL-G212, HSSL-G220, HSSL-G202, HSSL-G242,
  and HSSL-G243.
- HSSL-G241 joins HSSL-G201, HSSL-G202, HSSL-G211, HSSL-G212, HSSL-G220,
  HSSL-G231, HSSL-G232, HSSL-G239, HSSL-G242, and HSSL-G243, and is the only
  edge to custodian release.

Run ingestion only from a clean committed detached source with exact recursive
gitlinks. Marker scanning is implementation-coverage discovery, not completion
authority. Operational goals reconcile only from typed external receipts;
descriptive prose, a generated task, or an evidence term found in source must
never close them. Each generated task must stay in its bundle shard. Do not
manually mark generated backlog tasks complete. If a genuine gap is too large,
refine the objective heap into bounded child goals, rerun ingestion, and
preserve the parent/child phase edge; do not split merely to bypass a failed
gate.

## Baseline and ablation execution

Validate the frozen A0 manifest before any comparative run:

**HISTORICAL REVISION 1 ONLY:**

```bash
python benchmarks/logic_pipeline/runner.py \
  --variant A0 --split pilot --validate-only
```

The validator's canonical manifest digest must match the published value.
This content address is computed from the strict manifest payload; it is not
the raw-file SHA-256 of JSON that contains its own artifact identity. A source
file or submodule-gitlink drift is a validation failure. Normal A0 execution
is permitted only into a new empty run-scoped result root:

**HISTORICAL REVISION 1 ONLY:**

```bash
python benchmarks/logic_pipeline/runner.py \
  --variant A0 \
  --split pilot \
  --cache-mode both \
  --output-root "$HSSL_OPERATIONS_ROOT/$HSSL_RUN_ID/results/a0"
```

Use the programmatic `build_ablation_plan` and `execute_ablation` boundary for
A0–A12 and S1. The plan must bind the reviewed corpus, protocol digest,
variant registry, requested/effective capability identities, fixed resource
limits, operator seed, and separate cold/warm cache scopes before execution.
Persist the plan before the first backend call. Resume only through
`execute_ablation`; never delete or rewrite a partial result to force a retry.
Unavailable arms remain scheduled with explicit unavailable results.

Cold/warm comparison does not require byte-identical effective identities:
cache namespace, key, hit state, prime/setup receipts, and their dependent
provenance digests differ by design. `validate_cache_isolation` instead
requires exact requested identities and routes, then compares effective
identities after removing only the allowlisted cache-operational fields.
Provider, model, endpoint/backend revision, solver, implementation, and every
unrecognized identity field remain exact and fail closed on drift. Each warm
SyMAI measurement must bind a source-bound prime miss to the subsequent
semantically identical measured hit. Include the separately receipted setup
telemetry in latency, model-call, retry, memory, and resource totals; a cache
hit does not make its setup free. Direct Leanstral generation and the inner
SyMAI-to-Leanstral provider request must both record `cache_prompt=false`.

Pilot/development analysis must retain every requested case/arm/cache
coordinate and all disagreements. It must report semantic quality, ambiguity,
latency, model and solver calls, native-kernel completion, reconstruction,
repair, unnecessary calls, infrastructure failures, and complexity dimensions
separately. Safety is a hard constraint, not a weighted score.

Protocol revision 1 is a one-pass proof-synthesis experiment. A scheduled
Leanstral stage runs before the independent kernel and the frozen graph has no
edge that returns a failed draft plus reviewed kernel diagnostic to the model.
The HSSL-G034 adapter-level `repair_attempt: 1` transport is therefore an
upper-bound contract exercised by focused tests, not a revision 1 matrix
route. Record revision 1 repair attempts as structurally zero and repair
efficacy as unassessed. Do not call zero attempts a successful repair rate or
evidence against repair. HSSL-G180 requires a new preregistered protocol,
registry, prompt, reviewed repair-trigger corpus, and run identity before such
a comparison can be made.

## Pilot and shortlist gate

Run the canonical pilot gate:

**HISTORICAL REVISION 1 ONLY:**

```bash
python benchmarks/logic_pipeline/report.py \
  --gate pilot-shortlist \
  --artifact workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/pilot-shortlist-v2.json
```

The command's `artifact_sha256` must be
`2d146c1cb75eb8c2261a3e1be68ba98bf8b2a4996a1839fb36e26f9bd7f37acb`.
The source-bound matrix has semantic SHA-256
`437961214b97fadd495f65d4a006406b27086e6aeb9f46d8cd27e36df1ed39bb`
and contains 560 coordinates: fourteen arms, ten cases in each of pilot and
development, and cold/warm modes. A future shortlist may contain at most four
nonbaseline arms and may pass only when:

- every coordinate has a terminal measured or typed-missing outcome;
- invalid controls have zero native-kernel false positives;
- safety, provenance, cache, resource, and robustness gates pass;
- quality materiality and noninferiority thresholds pass from paired
  pilot/development evidence;
- failures and exclusions are retained;
- prompts, policies, backend identities, thresholds, and resource policy are
  frozen before holdout; and
- the G232 proposal records that exact nonempty shortlist, after which a
  separate G241 source replay and externally governed custodian receipt must
  authorize release.

For the published reassessment the decision is `incomplete`, the shortlist is
frozen empty, and holdout is unauthorized. All coordinates are terminal and
the proof, latency, resource, routing, and complexity measurements are
source-bound, but there are zero kernel acceptances and the independent
semantic-quality measurement is unavailable. The observed nondominated
candidate IDs A1, A3, and A7 are not eligible candidates and are not a
ranking. Stop here. An operator must not interpret zero invalid-control false
positives, zero proof completion, or Pareto nondominance as an authorization.

Remediation occurs outside this frozen run, in order: repair reviewed
obligation and proof-candidate generation for A1/A2; supply the registered
nonempty Leanstral prompt/context boundary for A3; repair the frozen SyMAI
router invocation for A4-A12 without substitution; and publish independent
reviewed semantic-quality receipts for A1-A12. Any repair requires a new run
ID, a new capability inventory, and full pilot/development reassessment before
another shortlist decision.

## Holdout gate

Validate the unopened seal without executing a holdout:

**HISTORICAL REVISION 1 ONLY — validation of the sealed predecessor, never
revision-2 holdout access:**

```bash
python benchmarks/logic_pipeline/report.py \
  --gate holdout \
  --artifact workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/holdout-evaluation-v2.json
```

The command's `artifact_sha256` must be
`e408d7364209dde32ff4f987ba2845306ab226c2f442c0a3d4abfb18521ee44d`.
The expected published state is `blocked` and `sealed_unopened`.

The authorization audit must fail at `before_holdout_activity`. The blocked
receipt must have no reviewed-input access, execution or cache namespace,
write, backend call, scheduled pair, observed pair, case result, kernel
success, failure, or non-null holdout metric. These zero activity counts prove
containment only; they are not efficacy, safety, latency, or resource values.

A future holdout execution is allowed only when the source-validated pilot
proposal is passed and freezes an exact nonempty shortlist, and an independent
custodian has validated the G241 release receipt for that exact source,
identity chain, seal, and shortlist. Use A0 and only those exact arms,
identical manifests, separate cold/warm caches, alternating frozen arm order,
and the same resource ceilings. The generic ablation executor must reject
missing, mismatched, self-authorized, or synthetic G241 releases before any
filesystem or backend activity. Never run A0 alone as a substitute for a
paired holdout.

After holdout access, any prompt, policy, threshold, model, solver, kernel,
corpus, resource, or route change ends the evaluation. Seal the run as invalid
and return to a new pilot; do not “repair” the holdout run in place.

## Replay and reporting

For a future authorized measured holdout, replay every kernel-verified success
and the frozen sample of failures. Each replay must:

- start in a new detached worktree at the recorded source commit;
- use a new run ID and a new cold cache namespace;
- retain the same frozen requested configuration and environment identity;
- reproduce stable case, route, adapter, input, output, kernel, reconstruction,
  and terminal-outcome identities; and
- bind its own worktree-safety and native-kernel receipts.

Use `benchmarks.logic_pipeline.report.validate_replay` to join the original
and replayed `CaseResultRecord`, both `RunContract` records, the pinned
environment digest, and the new `WorktreeSafetyReceipt`. Same-run replay,
warm-cache replay, same-cache reuse, backend drift, stale receipts, or a source
commit mismatch fails closed.

For the canonical reassessment, the source-validated holdout contains no
success or failure population to replay. The canonical replay index at
`workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/replay/replay-index.json`
must therefore retain zero required and completed replays, no replay
worktree/process/cache/receipt activity, and `replay_claimed=false`. Its
semantic SHA-256 is
`6248b875566afb7e9706c4f39d28e3a2eea680bd04dfd11f5fee6a5883af27d2`.
`all_observed_successes_replayed=true` is only zero-population accounting and
must never be described as replay success.

The current zero-population builder does not make a future nonempty replay
path executable. Before a later authorized holdout can advance beyond this
phase, G160 must provide an orchestrator or typed ingestion API that runs every
selected success and sampled failure through `run_detached_replay`, validates
the returned receipts, and publishes their completed counts. It must also
accept and source-bind independently measured quality, latency, resource,
safety, and routing receipts. Until those APIs exist and pass, the nonempty
replay/report gate remains blocked and G170 must not publish a replacement
decision.

Validate every report from canonical case-level evidence:

**HISTORICAL REVISION 1 ONLY:**

```bash
python benchmarks/logic_pipeline/report.py --section frontend --validate
python benchmarks/logic_pipeline/report.py --section proof --validate
python benchmarks/logic_pipeline/report.py --section efficiency --validate
python benchmarks/logic_pipeline/report.py \
  --gate pilot-shortlist \
  --artifact workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/pilot-shortlist-v2.json
python benchmarks/logic_pipeline/report.py \
  --gate holdout \
  --artifact workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/holdout-evaluation-v2.json
python benchmarks/logic_pipeline/report.py \
  --section statistics \
  --validate \
  --results-path workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/statistics.json
python benchmarks/logic_pipeline/report.py \
  --validate-final-decision \
  --artifact docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision_v2.json
python benchmarks/logic_pipeline/report.py --validate-runbook
```

For a new measured statistics report, supply its new run-scoped canonical
JSON:

**FUTURE AUTHORIZED — only after the complete G202 → G220 → G201/G212 →
G243 → G242 → G232 → G241 chain authorizes the corresponding phase:**

```bash
python benchmarks/logic_pipeline/report.py \
  --section statistics \
  --validate \
  --results-path "$HSSL_OPERATIONS_ROOT/$HSSL_RUN_ID/results/statistics.json"
```

The v2 decision must source-validate the HSSL-G160 report, which in turn binds
the exact matrix, pilot, holdout, replay index, statistics, and case receipts.
It must report quality, safety, latency, resources, routing, reliability,
marginal escalation value, unnecessary-call burden, and the complexity Pareto
frontier; select or reject A0-A12, S1, and P0-P3 explicitly; and assign only
bounded component responsibilities. Missing dimensions make a candidate
ineligible; they do not become favorable zeroes.

## Phase gates

| Gate | Required evidence | Pass action | Failure action |
|---|---|---|---|
| Protocol | Frozen protocol/corpus, worktree receipt, capability inventory, dependency-free tests | Permit pilot planning | Close run; repair outside it |
| Pilot execution | Complete paired coordinates, typed missingness, no corrupt receipts | Permit analysis only | Retain failures; no substitution |
| Shortlist | Safety plus preregistered quality/resource gates; at most four exact arms | Freeze and explicitly authorize holdout | Keep holdout sealed |
| Holdout | Passed authorization, exact pairs, frozen resources/order, kernel receipts | Permit replay only | Seal invalid/blocked; no tuning |
| Replay | All successes and sampled failures pass in fresh worktrees/caches | Permit final analysis | Reject affected claims |
| Replacement decision | Every arm, policy, and component disposed; predecessor and all v2 sources validated | Publish evidence; request separate production review | Keep A0 and no promotion |
| Production | Separately approved rollout, canary, monitoring, rollback owner | Change only the approved route | Roll back production change |

## Evidence inventory and freshness

The minimum publication set is:

| Evidence | Canonical location |
|---|---|
| Objective heap | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` |
| Baseline manifest | `workspace/benchmarks/hammer-symai-spacy-leanstral/a0-baseline-v1/state/baseline-manifest.json` |
| Immutable v1 predecessor | `docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` |
| Reassessment matrix | `workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/matrix-execution-v2.json` |
| Reassessment pilot gate | `workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/pilot-shortlist-v2.json` |
| Reassessment holdout gate | `workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/holdout-evaluation-v2.json` |
| Reassessment replay index | `workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/replay/replay-index.json` |
| Reassessment statistics | `workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/statistics.json` |
| Reassessment report snapshot | `docs/performance_snapshots/2026-07-24_hssl_reassessment_reports.json` |
| Replacement final decision | `docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision_v2.json` |
| Operator procedure | `docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md` |
| Supervisor reconciliation | `data/agent_supervisor/discovery/2026-07-24-hssl-bench-043-objective-gap-f4c6a8ab86c9.md` |

The publication chain is content-addressed:

| Artifact | Byte SHA-256 | Semantic SHA-256 |
|---|---|---|
| Immutable v1 decision | `0e53798d3f1deaab040cf99f10034644f421ffd51f15090a948aa7085041a84e` | `80823442e5115b2f499a2e77a11817dff555494ca0ecccfc79e59cbf423b7cce` |
| Reassessment matrix | `ad76be697eb084517354a9d2b82bf48378f33d820b6f6014a13d5a08bb105ac9` | `437961214b97fadd495f65d4a006406b27086e6aeb9f46d8cd27e36df1ed39bb` |
| Reassessment pilot | `21713e069e063db32763f563f0184a7d7123a5e559527d54618fadc98d286a48` | `2d146c1cb75eb8c2261a3e1be68ba98bf8b2a4996a1839fb36e26f9bd7f37acb` |
| Reassessment holdout | `9e712b9ed1fb67c80115d12e3bc92850f23da601543fa59a4cbd700a54b0df9d` | `e408d7364209dde32ff4f987ba2845306ab226c2f442c0a3d4abfb18521ee44d` |
| Reassessment replay | `3fc20f5526b1ed9fe81eed52e3cd0bd17084b0a46361c37e25b6bc7236401649` | `6248b875566afb7e9706c4f39d28e3a2eea680bd04dfd11f5fee6a5883af27d2` |
| Reassessment statistics | `6cf420232c0ae432ac9f2471670916d93d7f440fc144b9adfea4509ca41a4e92` | `857bae66f9b336de82c6506b469b864f6bcfb1862a67142ba858695e85781b3d` |
| Reassessment report snapshot | `1008b759bce54f22010316d408f7fc162a88204bf69bd18b8953119ff657d689` | Source graph validated by HSSLEV1605D50 |

Evidence is fresh only when all referenced bytes match their recorded SHA-256,
strict validators pass, the source/submodule commits and complete capability
identities match, and every parent phase receipt is the exact receipt named by
its child. A newer timestamp does not supersede a digest. A copied artifact is
not fresh merely because its path is current.

Treat evidence as stale and stop comparison when any of these occurs:

- source, submodule, corpus, protocol, split, prompt, route, threshold, model,
  solver, kernel, or resource-policy identity changes;
- canonical validation, content digest, or receipt linkage fails;
- a capability changes status, requested identity, or cache-insensitive
  effective backend identity—including provider, model, or solver—during a
  run;
- cold/warm namespaces collide or measured execution order differs;
- a parent phase receipt differs from the exact blocked/incomplete/valid state
  represented by its child, or is missing, invalid, or replaced;
- the v1 predecessor bytes or semantic identity change;
- an objective graph omits HSSL-G170’s HSSL-G160 prerequisite or any
  HSSL-G160-to-HSSL-G150-to-HSSL-G140 source edge; or
- the active checkout differs from the recorded before/after snapshot.

Refresh by opening a new run ID, re-probing, and rerunning from the earliest
affected phase. Never refresh by changing a digest in place.

## Incident response

Preserve the run root read-only for diagnosis and record the stable failure
code. Do not erase partial evidence.

| Incident | Immediate containment | Required recovery |
|---|---|---|
| Invalid control kernel-verified | Stop all arms and prevent shortlist/holdout | Investigate trust boundary; new pilot from a new run |
| Holdout accessed without authorization or tuned afterward | Stop execution; seal access as invalid | New frozen pilot and a newly authorized holdout namespace |
| Cache contamination or result overwrite attempt | Stop the affected run | New run and cache roots; replay uncompromised receipts |
| Receipt/provenance corruption or backend drift | Reject the claim and dependent reports | Restore pinned environment; fresh worktree replay |
| Orphaned solver/model/validation child | Stop the run; terminate the recorded process group using the bounded-process owner | Verify all children reaped; new run |
| Two consecutive OOMs | Stop the affected arm/run | Diagnose outside the run; do not expand frozen limits |
| Three consecutive infrastructure failures | Stop the benchmark run | Repair infrastructure and begin a new capability inventory |
| Capability missing/degraded | Record typed missingness; do not install mid-run | Separate provisioning window, then new run |
| Active checkout changed | Stop immediately and preserve both status snapshots | Repository owner reconciles; discard the benchmark run as unsafe |
| Model output contains forbidden proof construct or malformed contract | Reject that stage/case; no proof credit | Retain raw bounded evidence; fix only before a new run |

Escalate security-relevant prompt injection, secret exposure, path escape, or
unbounded process behavior to the repository security owner as well as the
benchmark coordinator. Logs and model traces may contain sensitive input;
keep run directories private and publish only reviewed canonical receipts.

## Rollback and fallback

The current rollback is simple because no benchmark promotion is authorized:
keep or restore the A0 production route, disable experimental routing, stop
benchmark workers/services through their owning process supervisor, and retain
the run artifacts for audit. Do not delete generated evidence as a rollback
mechanism.

For a future separately approved production rollout:

1. Set the approved feature/routing mode to its previous A0 value through the
   production owner’s configuration mechanism.
2. Stop new SyMAI, Hammer, and Leanstral dispatch before draining bounded
   in-flight work.
3. Leave native-kernel verification enabled.
4. Stop any benchmark-owned model or solver processes using their recorded
   process groups; do not use a broad name-based kill.
5. Verify the production route and health checks match the pre-rollout A0
   receipt.
6. Preserve logs, route decisions, kernel receipts, and configuration
   identities, then open a new incident and benchmark run.

Safe fallbacks are typed outcomes:

- unavailable full spaCy means the full-spaCy arm is unavailable, not silently
  successful blank spaCy;
- unavailable SyMAI/Leanstral/Hammer means that requested arm is unavailable,
  not rerouted to A0;
- Hammer timeout or failed reconstruction is a failed/inconclusive proof
  stage, never a verified result;
- Leanstral timeout, malformed schema, or forbidden construct is rejected,
  never repaired more than once;
- a failed kernel check is not verified even if every upstream component
  agrees; and
- an incomplete pilot means sealed holdout and no production selection.

## Handoff checklist

- [ ] Source and submodule commits recorded; active checkout unchanged.
- [ ] Detached worktree and run root are disjoint from source/Git state.
- [ ] Worktree-safety and capability inventory receipts validated.
- [ ] Objective graph, todo, bundles, and todo-vector index reviewed locally.
- [ ] Frozen baseline and reviewed corpus digests match.
- [ ] Immutable v1 decision byte and semantic digests match and its file was
      not overwritten.
- [ ] HSSL-G140, HSSL-G150, and HSSL-G160 artifacts pass their exact
      source-bound validators before the v2 decision is loaded.
- [ ] Cold and warm caches are distinct and order/resource policies are fixed.
- [ ] Pilot matrix is complete; exclusions and infrastructure failures remain.
- [ ] Shortlist is at most four exact nonbaseline arms and explicitly passed,
      or is truthfully frozen empty with the holdout sealed.
- [ ] Holdout access is explicitly authorized, or remains sealed and unopened.
- [ ] Every proof claim has a native-kernel receipt.
- [ ] Every success and required failure sample is replayed in a fresh cold
      run, or the validated empty population explicitly makes no replay claim.
- [ ] Quality, safety, latency, resource, routing, reliability, and complexity
      dimensions are reported without missing-as-zero coercion.
- [ ] A0-A12 and S1 each have an explicit evidence disposition.
- [ ] P0, P1, P2, and P3 each have an explicit evidence disposition.
- [ ] The v2 final-decision validator with its exact `--artifact` and the
      runbook validator pass.
- [ ] No production promotion, merge, or active-checkout mutation occurred.

## HSSLEV1703E61 traceability

HSSLEV1703E61 is the stable evidence symbol for the **source-bound replacement
architecture decision, immutable v1 preservation, measured delegation
dispositions, and worktree-safe reassessment reproduction runbook**. It is
satisfied by the combined, fail-closed contract below:

| Acceptance term | Runbook evidence |
|---|---|
| Create only from a validated paired-holdout and replay/report chain | Holdout and replay/report sections validate the exact G140/G150/G160 chain and preserve its blocked, empty-population outcome without inventing activity |
| Preserve and link immutable v1 | Published decision and evidence inventory name the exact predecessor path, byte digest, semantic digest, and unchanged disposition |
| Select or reject A0-A12 and S1 | Published-decision arm matrix gives all fourteen arms an explicit, evidence-specific disposition |
| Select or reject every delegation policy | Ownership matrix explicitly rejects P0-P3 for production at this revision |
| Assign bounded component responsibilities | Ownership matrix limits spaCy, SyMAI, Hammer, and Leanstral to non-authoritative experimental boundaries and grants no new production role |
| Count only kernel-verified proofs | Trust boundaries, delegation matrix, replay, and invariants assign sole authority to independent native-kernel receipts |
| Report quality, resource, and complexity tradeoffs | Published decision records measured pilot/development values, typed holdout nulls, and the safety-constrained ineligible Pareto frontier |
| Reproduce capability probing | Read-only preflight command writes a canonical run-scoped inventory |
| Reproduce objective ingestion | Local objective-daemon command writes run-scoped graph, bundles, discovery, and todo-vector state without submission |
| Reproduce pilot and shortlist | Exact reassessment artifact command plus matrix, safety, semantic-quality, threshold, and freeze requirements |
| Reproduce untouched holdout | Exact reassessment holdout command validates the unopened seal and defines the only permitted future authorization |
| Reproduce replay and reporting | Fresh-worktree/cold-cache replay contract, empty-population semantics, statistics path, and all canonical validators are listed |
| Protect active progress | Detached worktree, disjoint state root, before/after source status, no auto-merge, and no destructive Git operation |
| Prevent automatic production promotion | Purpose, every phase gate, published decision, and rollback require a separate production approval |
| Preserve supervisor/objective alignment | Objective ingestion keeps HSSL-G170 downstream of HSSL-G160 and forbids manual generated-status edits |

This runbook and the v2 final-decision artifact are one publication boundary.
Validation of either must fail if the predecessor, source paths and digests,
arm or policy dispositions, component boundaries, missingness semantics, or
the no-promotion decision diverge. A valid replacement decision may be
published as evidence for a separate production review; it is never that
review and never changes routing itself.
