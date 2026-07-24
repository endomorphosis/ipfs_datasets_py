# Hammer, SyMAI, spaCy, and Leanstral Benchmark Decision Runbook

Runbook ID: HSSL-BENCH-026  
Goal ID: HSSL-G100  
Evidence: HSSLEV1006B8A  
Evidence marker: evidence-bound final architecture decision, delegation matrix, and worktree-safe reproduction runbook  
Protocol revision: 1  
Decision artifact: docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision.json  
Objective heap: docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md

## Purpose and authority

This is the operator runbook for reproducing and maintaining the final
Hammer/SyMAI/spaCy/Leanstral architecture decision. It is an evidence
procedure, not a production deployment procedure. Nothing in this runbook
authorizes a production route change, service installation, model download,
automatic merge, holdout access, or promotion.

The machine-readable final-decision artifact is authoritative for the current
disposition. The objective heap records the dependency graph. Canonical
benchmark result files and their dated performance snapshots provide the phase
receipts. If prose conflicts with a source-validated canonical receipt, stop
and use the receipt. Never edit a receipt to make the prose agree.

The independent native kernel is the only proof authority. Hammer solver
evidence, Leanstral drafts, SyMAI output, spaCy annotations, reconstruction
records, model confidence, and legacy S1 predictions are non-authoritative.

## Published decision

The 2026-07-24 decision is **no architecture promotion**:

- Keep the current effective A0 route unchanged.
- Do not add full-model spaCy, SyMAI, Hammer, or Leanstral to the production
  route on the basis of this benchmark capture.
- Do not select P0, P1, P2, or P3 for production.
- Keep the holdout sealed and unopened.

This is a blocked-evidence decision, not a finding that the optional
components are ineffective. The capability capture found the requested full
spaCy pipeline and Leanstral service unavailable, SyMAI/router identities
degraded, and no complete paired efficacy observations. The pilot gate is
therefore `incomplete`, its nonbaseline shortlist is empty, and holdout access
is unauthorized. The holdout gate is correspondingly `blocked` and
`sealed_unopened`. Null or unavailable measurements must never be presented as
zero cost, zero failures, or an efficacy result.

The immutable baseline manifest is:

```text
workspace/benchmarks/hammer-symai-spacy-leanstral/a0-baseline-v1/state/baseline-manifest.json
SHA-256 6b37a6493d6328102b558258843218128ad0bf6f8cc7be13f8d0c2e0bb61e156
source commit 2a1be00b1b76e6652c25d418752affbf0f85d176
```

The canonical holdout phase receipt is:

```text
workspace/benchmarks/hammer-symai-spacy-leanstral/results/holdout-evaluation-v1.json
SHA-256 7d064c5fe82c25ad93c01fd13d4350ae2457f93d3bd32b9cf9a9365b1836c2cd
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
| A0 current route | Logic-pipeline maintainer | Frozen current codec, including the recorded `spacy.blank:en` fallback | Existing deterministic validators; no experimental escalation | Retain unchanged |
| Full-model spaCy | NLP adapter owner | Tokens, sentences, lemmas, dependencies, entities, SRL features, and modal cues | Linguistic evidence only; unavailable full model stays unavailable and never becomes blank/regex success | Withheld; no paired holdout evidence |
| SyMAI | Model-routing owner | Bounded structured semantic candidate or contract repair through the existing `llm_router` | Canonical schema/parser validates; no recursive routing or second model manager | Withheld; no paired holdout evidence |
| Hammer | Proof-search owner | Premise selection, translation, bounded solver portfolio, normalization, and native reconstruction | Solver/reconstruction evidence is untrusted until a separate native-kernel receipt accepts it | Withheld; no paired holdout evidence |
| Leanstral | Model-service owner | One bounded Lean draft and at most one reviewed repair for a fixed obligation | Draft only; no `sorry`, `admit`, obligation rebinding, or model proof claim; kernel checks independently | Withheld; no paired holdout evidence |
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
   diagnostic.
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
`objective_bundles/todo_vector_index.json`. HSSL-G100 must remain downstream
of HSSL-G090, each generated task must stay in its bundle shard, and evidence
terms must reconcile from validated outputs rather than descriptive prose.
Do not manually mark generated backlog tasks complete. If a genuine gap is too
large, refine the objective heap into bounded child goals, rerun ingestion,
and preserve the parent/child phase edge; do not split merely to bypass a
failed gate.

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

Pilot/development analysis must retain every requested case/arm/cache
coordinate and all disagreements. It must report semantic quality, ambiguity,
latency, model and solver calls, native-kernel completion, reconstruction,
repair, unnecessary calls, infrastructure failures, and complexity dimensions
separately. Safety is a hard constraint, not a weighted score.

## Pilot and shortlist gate

Run the canonical pilot gate:

```bash
python benchmarks/logic_pipeline/report.py --gate pilot-shortlist
```

The command's `artifact_sha256` must be
`5be9bff6e4f0abf9c096e007b3c3230d09eab943d7ccd58f5fd6d7ab31c746fa`.
Its complete matrix contains 280 coordinates: fourteen arms, ten pilot cases,
and cold/warm modes. A future shortlist may contain at most four nonbaseline
arms and may pass only when:

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

For the published capture the decision is `incomplete`, the shortlist is
empty, and holdout is unauthorized. Stop here. An operator must not interpret
“zero observed invalid-control false positives” under missing measurements as
a safety pass.

## Holdout gate

Validate the unopened seal without executing a holdout:

```bash
python benchmarks/logic_pipeline/report.py --gate holdout
```

The command's `artifact_sha256` must be
`7d064c5fe82c25ad93c01fd13d4350ae2457f93d3bd32b9cf9a9365b1836c2cd`.
The expected published state is `blocked` and `sealed_unopened`.

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

Validate every report from canonical case-level evidence:

```bash
python benchmarks/logic_pipeline/report.py --section frontend --validate
python benchmarks/logic_pipeline/report.py --section proof --validate
python benchmarks/logic_pipeline/report.py --section efficiency --validate
python benchmarks/logic_pipeline/report.py --gate pilot-shortlist
python benchmarks/logic_pipeline/report.py --gate holdout
python benchmarks/logic_pipeline/report.py --validate-final-decision
python benchmarks/logic_pipeline/report.py --validate-runbook
```

For a measured statistics report, also supply its run-scoped canonical JSON:

```bash
python benchmarks/logic_pipeline/report.py \
  --section statistics \
  --validate \
  --results-path "$HSSL_OPERATIONS_ROOT/$HSSL_RUN_ID/results/statistics.json"
```

The final decision must recompute quality, safety, latency, resources, routing,
reliability, marginal escalation value, unnecessary-call burden, and the
complexity Pareto frontier from source receipts. It must select or reject all
four policies explicitly. Missing dimensions make a candidate ineligible;
they do not become favorable zeroes.

## Phase gates

| Gate | Required evidence | Pass action | Failure action |
|---|---|---|---|
| Protocol | Frozen protocol/corpus, worktree receipt, capability inventory, dependency-free tests | Permit pilot planning | Close run; repair outside it |
| Pilot execution | Complete paired coordinates, typed missingness, no corrupt receipts | Permit analysis only | Retain failures; no substitution |
| Shortlist | Safety plus preregistered quality/resource gates; at most four exact arms | Freeze and explicitly authorize holdout | Keep holdout sealed |
| Holdout | Passed authorization, exact pairs, frozen resources/order, kernel receipts | Permit replay only | Seal invalid/blocked; no tuning |
| Replay | All successes and sampled failures pass in fresh worktrees/caches | Permit final analysis | Reject affected claims |
| Final decision | Every policy/component disposed; all domains and receipts validated | Publish evidence; request separate production review | Keep A0 and no promotion |
| Production | Separately approved rollout, canary, monitoring, rollback owner | Change only the approved route | Roll back production change |

## Evidence inventory and freshness

The minimum publication set is:

| Evidence | Canonical location |
|---|---|
| Objective heap | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` |
| Baseline manifest | `workspace/benchmarks/hammer-symai-spacy-leanstral/a0-baseline-v1/state/baseline-manifest.json` |
| Front-end analysis | `workspace/benchmarks/hammer-symai-spacy-leanstral/results/frontend-overlap-v1.json` |
| Proof analysis | `workspace/benchmarks/hammer-symai-spacy-leanstral/results/proof-overlap-ordering-v1.json` |
| Pilot receipt | `workspace/benchmarks/hammer-symai-spacy-leanstral/results/pilot-shortlist-v1.json` |
| Holdout receipt | `workspace/benchmarks/hammer-symai-spacy-leanstral/results/holdout-evaluation-v1.json` |
| Final decision | `docs/performance_snapshots/2026-07-24_hammer_symai_spacy_leanstral_final_decision.json` |
| Operator procedure | `docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md` |
| Supervisor reconciliation | `data/agent_supervisor/discovery/` |

Evidence is fresh only when all referenced bytes match their recorded SHA-256,
strict validators pass, the source/submodule commits and complete capability
identities match, and every parent phase receipt is the exact receipt named by
its child. A newer timestamp does not supersede a digest. A copied artifact is
not fresh merely because its path is current.

Treat evidence as stale and stop comparison when any of these occurs:

- source, submodule, corpus, protocol, split, prompt, route, threshold, model,
  solver, kernel, or resource-policy identity changes;
- canonical validation, content digest, or receipt linkage fails;
- a capability changes status or effective identity during a run;
- cold/warm namespaces collide or measured execution order differs;
- a parent phase receipt is missing, blocked, incomplete, invalid, or replaced;
- an objective graph omits HSSL-G100’s HSSL-G090 prerequisite; or
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
- [ ] Cold and warm caches are distinct and order/resource policies are fixed.
- [ ] Pilot matrix is complete; exclusions and infrastructure failures remain.
- [ ] Shortlist is at most four exact nonbaseline arms and explicitly passed.
- [ ] Holdout access is explicitly authorized, or remains sealed and unopened.
- [ ] Every proof claim has a native-kernel receipt.
- [ ] Every success and required failure sample replayed in a fresh cold run.
- [ ] Quality, safety, latency, resource, routing, reliability, and complexity
      dimensions are reported without missing-as-zero coercion.
- [ ] P0, P1, P2, and P3 each have an explicit evidence disposition.
- [ ] Final-decision and runbook validators pass.
- [ ] No production promotion, merge, or active-checkout mutation occurred.

## HSSLEV1006B8A traceability

HSSLEV1006B8A is the stable evidence symbol for the **evidence-bound final
architecture decision, delegation matrix, and worktree-safe reproduction
runbook**. It is satisfied by the combined, fail-closed contract below:

| Acceptance term | Runbook evidence |
|---|---|
| Cite immutable baseline and holdout manifests | Published decision and evidence inventory name exact paths and digests |
| Count only kernel-verified proofs | Trust boundaries, delegation matrix, replay, and invariants assign sole authority to native-kernel receipts |
| Report quality, resource, and complexity tradeoffs | Baseline/ablation and reporting sections require separate paired domains and a hard-safety Pareto frontier |
| Select or reject every delegation policy | Published decision and matrix explicitly reject P0–P3 for production at this revision |
| Reproduce capability probing | Read-only preflight command writes a canonical run-scoped inventory |
| Reproduce objective ingestion | Local objective-daemon command writes run-scoped graph, bundles, discovery, and todo-vector state without submission |
| Reproduce pilot and shortlist | Pilot gate command plus explicit matrix, safety, threshold, and freeze requirements |
| Reproduce untouched holdout | Holdout section validates the current unopened seal and defines the only permitted future authorization |
| Reproduce replay and reporting | Fresh-worktree/cold-cache replay contract and all canonical report validators are listed |
| Protect active progress | Detached worktree, disjoint state root, before/after source status, no auto-merge, and no destructive Git operation |
| Prevent automatic production promotion | Purpose, every phase gate, published decision, and rollback require a separate production approval |
| Preserve supervisor/objective alignment | Objective ingestion keeps HSSL-G100 downstream of HSSL-G090 and forbids manual generated-status edits |

This runbook and the final-decision artifact are one publication boundary:
validation of either must fail if paths, dispositions, evidence identity, or
the no-promotion decision diverge.
