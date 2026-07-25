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
and stop. HSSL-G200 owns a new content-addressed, label-blind semantic
projection, prompt/schema, scoreability calibration, and non-vacuous quality
gate. HSSL-G210 owns equal A0/candidate kernel exposure and causal
optional-component rescue accounting. Because those changes alter metrics,
prompts, producer contracts, routes, and eligibility behavior, they require a
new protocol/registry identity and a fresh complete pilot/development matrix;
revision 1 receipts must not be relabelled.

The combined fixture layout also does not provide an adequate confidentiality
boundary for a future blinded evaluation. No holdout backend execution
occurred in the repaired run, but the current holdout is retired from future
selection claims. HSSL-G220 requires an independently authored replacement
outside the tuning worktree, sealed only after HSSL-G200 and HSSL-G210 are
frozen, with append-only access receipts. HSSL-G230 then owns the fresh
revision-2 matrix and exact pilot authorization. Revision-1 HSSL-G150 and its
old holdout must never be reused for the new claim; a revision-2 successor
requires the new protocol, replacement seal, and exact fresh HSSL-G230
authorization. Until then, do not execute any holdout, publish a replacement
HSSL-G170 decision, or infer production responsibility.

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

```bash
git rev-parse --show-toplevel
git rev-parse --verify HEAD
git status --short
git submodule status --recursive
```

Choose a unique run ID and an operations root outside this checkout and its
Git common directory. Do not use the default in-repository benchmark root for
worktree preparation.

```bash
export HSSL_RUN_ID=hssl-reproduce-20260724T000000Z
export HSSL_OPERATIONS_ROOT=/var/tmp/hssl-benchmark-operations
export HSSL_SOURCE_ROOT="$PWD"
export HSSL_BASE_REVISION="$(git rev-parse --verify HEAD)"
test ! -e "$HSSL_OPERATIONS_ROOT/$HSSL_RUN_ID"
```

Create the detached worktree and its safety receipt:

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

Capability probing is read-only: it does not import optional backend parents,
install software, start services, or make inference calls. It emits a record
for spaCy, SyMAI, `llm_router`, Hammer solvers, Leanstral, Lean/Lake, cache,
and the resource scheduler. The implementation and trust boundary live in
`benchmarks/logic_pipeline/capabilities.py`.

```bash
python - <<'PY'
import os
from pathlib import Path
from benchmarks.logic_pipeline import RunPaths
from benchmarks.logic_pipeline.capabilities import (
    capability_inventory_sha256,
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
print(capability_inventory_sha256(inventory))
for record in inventory.capabilities:
    print(record.kind.value, record.status.value, record.reason or "")
PY
```

Do not install a missing capability during a run. Close the run as explicit
missingness, provision or repair the service in a separate approved window,
and begin a new run ID with a new probe. A capability identity, version,
model, solver, kernel, source commit, or environment change invalidates
comparison with the earlier inventory.

Before execution, validate the dependency-free contracts:

```bash
python -m pytest tests/unit/benchmarks/logic_pipeline -q
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
validation boundary is `benchmarks/logic_pipeline/objective_ingestion.py`; it
drives the repository supervisor shown below and must preserve the same
run-scoped graph, discovery, bundle, and todo-vector identities.

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
  --task-prefix HSSL-BENCH- \
  --max-findings 64 \
  --surplus-findings-per-goal 1 \
  --no-reconcile-goal-completion \
  --no-generate-bounded-work
```

The absence of `--submit-bundles` is intentional. Inspect the todo board,
objective graph, discovery receipts, bundle index, and
`objective_bundles/todo_vector_index.json`. HSSL-G170 must remain downstream
of HSSL-G160, which must retain its HSSL-G150 and HSSL-G140 source chain. Each
of the future HSSL-G180 repair-revision and HSSL-G190 legacy-S1 goals must
remain downstream of HSSL-G170 without becoming a prerequisite that
retroactively changes the frozen v2 publication. Each generated task must stay
in its bundle shard, and evidence terms must
reconcile from validated outputs rather than descriptive prose. Do not
manually mark generated backlog tasks complete. If a genuine gap is too large,
refine the objective heap into bounded child goals, rerun ingestion, and
preserve the parent/child phase edge; do not split merely to bypass a failed
gate.

## Baseline and ablation execution

Validate the frozen A0 manifest before any comparative run:

```bash
python benchmarks/logic_pipeline/runner.py \
  --variant A0 --split pilot --validate-only
```

The validator's canonical manifest digest must match the published value.
This content address is computed from the strict manifest payload; it is not
the raw-file SHA-256 of JSON that contains its own artifact identity. A source
file or submodule-gitlink drift is a validation failure. Normal A0 execution
is permitted only into a new empty run-scoped result root:

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
- the receipt explicitly sets holdout authorization for that exact nonempty
  shortlist.

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
receipt is passed, authorizes access, and freezes an exact nonempty shortlist.
Use A0 and only those exact arms, identical manifests, separate cold/warm
caches, alternating frozen arm order, and the same resource ceilings. The
generic ablation executor must reject unauthorized holdout work before any
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
