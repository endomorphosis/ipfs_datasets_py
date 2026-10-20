# U.S. Code training and native DuckDB repair queue

Status: integration under qualification. Do not infer that tasks were repaired
from a running process, a training receipt, or an exported taskboard.

This initiative belongs to the `ipfs_datasets_py` submodule. The producer uses
the accelerate `DatabaseTaskSource` API; the consumer uses the native configured
database implementation daemon and its Portal execution/validation bridge.
This is not an LLM emitting standalone Python files for direct import.

## Dependency and state ownership

Pass `--accelerate-root` explicitly. In the inspected workspace, the nested
checkout at revision `91a1253c24a023c2f113d4549fecbfa042666464` fails its schema
catalog check with duplicate migration versions. The sibling checkout
`/home/barberb/lift_coding/external/ipfs_accelerate` passed a native queue creation
and restart test. Do not disable the schema check or silently fall back to
another checkout; requalify the explicitly selected dependency when it changes.

The first live local consumer attempt exposed an additional incompatibility in
the sibling checkout: `DatabaseTaskSource.compare_and_set_status` forwards
`expected_control_receipt` but `IntentRepository.cas_task_status` does not accept
it. Queue CRUD tests passed; native claim admission did not. Startup now checks
this call contract before opening execution/coordination stores. **Do not remove
the receipt argument to force execution.** This shared checkout is not the
qualified execution dependency; use the reviewed private pin below.

A matching older dependency at `604fbaa4b9f276f2ed45c082d41cb6d5441bd249`
was subsequently frozen without implementation changes in
`workspace/autoformal-supervisor-20260925/accelerate-604fbaa4-qualified`.
It passed ten native claim/evidence guard tests, copied-queue checks and native
bridge initialization. This resolves the caller/callee mismatch, not every
execution prerequisite. Both shared accelerate checkouts remain untouched.

With explicit operator approval, a derived private copy at
`workspace/autoformal-supervisor-20260925/accelerate-sealed-validator-v1`
adds an opt-in sealed Python validator contract. It is not a generic Python or
shell exemption. The normal installed-package closure/interpreter probe still
runs after checking exact argv, native task CID, packet hash/schema, declared
edit outputs, immutable regression suite, and protected evaluator hashes.
Existing scoped pytest contracts retain their previous policy.

The qualified private revision is `ed44fb693c3eff458087480020d899075fb6536d`.
Its native suites passed 290 tests, with one Quack concurrency test deselected
because this pilot uses embedded single-owner authority. The results include
36 sealed-policy cases and a real installed-interpreter dependency probe;
`qualification-sealed-validator-final.xml` is the generated receipt. The fresh
v8 datasets snapshot passed 172 harness and regression tests. These results
qualify dependency admission, not acceptance of an agent's code patch.

The derived v2 execution profile is
`workspace/autoformal-supervisor-20260925/accelerate-retained-validator-v2`
at `891d90885bd8b4c28c7ed4edcdda5e8946683288`. It preserves the sealed validator
and adds explicit `--retain-worktree-artifacts`: no pool reuse, no attempt/merge
workspace removal, no generated-cache deletion, and no Git GC. Retention reports
`retained: true, cleaned: false`; it is not validation or completion. Submodule
editing is rejected in this profile until separately qualified. The v1 copy and
shared checkouts remain unchanged. The updated launcher requires the v2 flag.

The derived **private v3 retry-policy pin** is
`workspace/autoformal-supervisor-20260925/accelerate-consumed-budget-v3`
at `8fdedf2283ed88bed187be574dc41a400cc5b0cc`.
It adds a cross-pass consumed-provider budget: a failed attempt counts only
with explicit native consumed/dispatched booleans, a matching immutable failed
phase, and a durable provider-invocation record. Restart reconciliation uses
the existing fence and control CAS to block exhausted tasks, never complete
them or delete their retry evidence. Claim and resume dispatch stop after a
budget settlement so the caller can regenerate task-bound context. Preflight
and infrastructure deferrals retain their existing independent policies.

The final focused budget suite passed 23 tests; sealed-validator, dependency,
retention and context-note suites passed 170. Receipts are
`qualification-v3-consumed-budget-frozen.xml` and
`qualification-v3-sealed-policy-retention.xml` (the former filename denotes
the final tested source). The broader audit found 19 existing daemon failures,
all reproduced on unchanged v2, plus the initial new fixture's deferral-policy
expectation, fixed and covered by the final focused suite. See
`qualification-v2-native-audit-failure-comparison.xml` and the generated
`consumed-budget-v3-qualification.json`. The entire daemon suite is **not green**.
Qualification is limited to bounded embedded single-owner candidate/validation
retry settlement, not distributed Quack operation or changes to neutral-failure
quarantine/reopening. Existing neutral-failure behavior remains unchanged.
Native test-generated lock artifacts are retained; v3's private Git local exclude
lists only their three exact paths. Shared accelerate sources were not edited.

The v12 datasets snapshot, `repair-repository-v12`, is frozen at
`44aa13e81ed4adb762976a7fcf149d1f8bcdbcc3` on `autoformal-candidate-v12`.
It forks the prior predeployment source and overlays nine explicit protected
harness/test files, including checkpoint diagnostics and the two semantic-loss
guards. It does not copy concurrent compiler/model edits from the shared tree.
Its 214 harness tests and real sealed dependency preflight passed.

A bounded real feedback-coordinator pass, cycle
`cycle-a57c4f4d045f44a5944227e6e046eb5a`, exercised the native v3 settlement in
15.15 seconds. Queue revision 106 has **14 blocked, 5 ready**. The exhausted DOE
task is blocked, not repaired or completed. Execution attempts and provider
invocations both remain at five total; its own three attempts and old retry entry
remain intact. The candidate branch did not change. Generated evidence is
`bounded-v12-budget-settlement.json`. No provider, training, or publication ran,
and no repair or optimizer update was accepted. The bounded runner exited.

The next native-eligible task contains definitions, while two other ready tasks
contain policy declarations. Current canonical IR only supports deontic O/P/F
forms and explicitly abstains on definition/procedure/reference facets. An
operator decision is pending on a separate versioned compiler/decompiler IR
extension and newly scoped supervisor tasks; do not make these jobs pass by
discarding those facets, coercing their modality, or editing old sealed packets.

### Explicit ready-task selection

Both launchers accept the global option `--task-id AFTD-<20 lowercase hex digits>`.
Use it before the `preflight` or `supervise` subcommand in the supervisor CLI.
Selection scans at most 1,000 **native-ready** tasks; it does not change priority,
reopen a blocked task, bypass a dependency, or mark other tasks complete. A missing,
blocked, ambiguous, or out-of-window selection fails closed without falling back
to another task. The feedback coordinator also refuses to substitute training
when a selected task is unavailable. Each live dispatch, selected or not, binds
the native execution slice to the exact CID in its passing preflight receipt.

The v13 private datasets snapshot is `repair-repository-v13`, frozen at
`814a6615b327f2e6582d5cc59ab4f241d8ed1daa`. Its 230 harness tests passed, including
native task-CID claim isolation; the focused selection/coordinator suite passed
60 tests. See `qualification-datasets-v13.xml`,
`qualification-explicit-task-selection-qualified.xml`, and
`repair-repository-v13-source-snapshot.json`. These are qualification results,
not evidence of a successful compiler repair.

The landscape-parser task `AFTD-42a49d68a6ef27aea628` passed the real sealed
preflight on this snapshot. Its existing scope permits parser/compiler changes,
unlike the pending definition/policy IR extension. The remaining AIS qualifier
task `AFTD-03dfe0611271b3ef2e40` currently permits decompiler edits only, but
read-only replay found the missing condition absent from compiled rules. Do not
fabricate that condition in the renderer or silently widen its sealed task.
The diagnostic evidence is `remaining-v12-in-scope-replay-diagnostic.json`.

### Source-integrity gate audit and v14

The bounded selected run `cycle-fab0527c3de840afb7d1312e96da5127` claimed the
landscape task and launched its real provider. While the agent was analyzing,
an independent in-memory mutation (adding authorization phrases to the comma
regex) passed the old replay gate despite folding heading/temporal/consultation
text into the actor and losing numeric scope from the action object. This was
an **operator-generated diagnostic**, not an agent patch or an automatically
rejected candidate. The operator signalled only the identity-checked provider;
its worktree was clean, and the native owner settled the attempt without a merge.
The pass finished after 324.24 seconds. Queue revision 108 has **15 blocked,
4 ready**; no task was completed. Native execution attempts/provider-invocation
records increased from five to six each. The failure's consumed/dispatched fields
are `unknown`, so do not count it as qualified consumed-budget evidence. See
`bounded-v13-landscape-review.json` and `v13-landscape-operator-stop.json`.

The new private `repair-repository-v14` is frozen at
`5edd09e4a38a00c4335cb474b92e192468182b6b` and passed **245 tests** in
`qualification-datasets-v14.xml`. Its protected census adds parser-independent
numeric-identifier/multiplicity checks and conservative alarms for heading or
known conditional/temporal text in fresh compiled actor slots. Only case and
typographic dashes are normalized. Alternative numeric spellings and outline
labels may require review; these checks are necessary alarms, not proofs of
semantic equivalence, role alignment, or unit preservation. An operative first
line cannot be hidden merely by prefixing it with a section citation.

`v14-source-integrity-audit.json` reproduces the exact old passing mutation and
now rejects it. Four of seven prior preserve rows are also flagged. Do not weaken
the evaluator or rewrite old packets to restore their previous agreement count.
The v14 snapshot and regenerated validator seal do not change earlier frozen
snapshots, reopen blocked tasks, repair a compiler, or promote a model. The first
new guard test invocation accidentally loaded the incompatible nested accelerate
checkout (five schema failures); an explicit private module pin passed all 37
focused tests, and the final full private suite includes the additional heading
regression. Both receipts remain retained.
The real v14 dependency preflight also passed (`repair-repository-v14-dependency-preflight.json`)
without claiming a task or dispatching a provider; dependency admission is not
source-replay acceptance of the selected definitions task.

No repair or optimizer update has been accepted. A new operator decision is
required for versioned compiler/decompiler task scopes covering these baseline
losses and unsupported IR forms. Keep the existing immutable evidence and native
blocked statuses; do not reset attempt budgets or silently widen old tasks.

The subsequent read-only `v14-native-ready-scope-audit.json` checks **all four**
native-ready tasks, including strict/partial compiler diagnostics and every
sealed preserve row. All targets still fail; each task also has four or seven
failing preserve rows. Thus dependency admission alone cannot justify another
repair dispatch against these scopes. The audit leaves queue revision 108,
six execution attempts and six provider-invocation records unchanged. It does
not claim tasks, reclassify native readiness, or mark anything complete. Some
numeric alarms are deliberately conservative; failure counts are not a measure
of legal equivalence. Newly scoped repair work still requires operator approval.

### Approved versioned IR and repair-task fork

The operator subsequently approved both the versioned IR extension and new
compiler/decompiler repair tasks. `legal-surface-ir/v2` is opt-in and distinct
from the measured canonical v1 contracts. Its strict immutable statement kinds
are `definition`, `policy`, and `norm`; definitions/policy stances cannot be
encoded as O/P/F. Natural-language literal slots remain explicitly unproved.
This is structural IR, not completed autoformalization or kernel admission.

The native task envelope remains v1. Two **new failure keys** have separate edit
scopes: `extended_ir_v2` may edit only the new extended compiler/decompiler;
`roundtrip_repair_v2` may edit the existing compiler, decompiler and parser
together. Neither widens a historical key. New packets bind parent task CID,
parent packet digest and unchanged source bytes. Old tasks are not completed,
reopened or silently superseded. Joint baseline tasks preserve freshly passing
rows and disclose other unresolved sources; the original preserve lists remain
in their original packets.

The protected extension gate checks operator-sealed expected slots, public
counterexample probes, semantic-atom/numeric preservation, and recompilation.
Rendering uses a fresh interpreter with IR-only stdin, preventing reuse of a
compiler-populated memory cache. This is data-flow separation, **not an OS
filesystem/network sandbox**. A passing extension task is not legal equivalence
and does not complete its parent task.

`prepare_versioned_autoformal_tasks.py` defaults to planning and requires
`--apply` to append tasks through the native owner. It checks all existing
task records remain unchanged. Use a canonical absolute `--expected-ir` path
to an independently reviewed fixture; candidate-generated gold is forbidden.
The first materialization produced one policy task and 12 deduplicated baseline
repair tasks. Queue revision 135 has 15 blocked and 17 ready; all 19 original
records are unchanged. Evidence: `versioned-v15-task-materialization.json` and
`policy-19-3702-expected-ir-v2-review.json`. The expected policy keeps Congress,
the `supports` stance and all ten agenda items, without inventing a duty.

The v15 snapshot at `664bacb46cdc38f009aed4bbffee9cef8ebd8335` passed 265 harness
tests and real extension dependency preflight. Its compiler/decompiler are
initial abstention stubs: those tests qualify contracts, not a working parser.
The initial live launch stopped **before a claim** because the shared tree gained
a protected Constitution regression. That additional test passed an in-memory
probe against v15 (`v15-concurrent-regression-probe.json`); v16 retained it and
passed 266 tests. No frozen snapshot or old receipt was rewritten.

The bounded v16 policy attempt produced a patch, but no repair was merged.
Independent probes (`v16-policy-adversarial-probe.json`) found conjunction and
disjunction collapsed into the same IR, an operative first line discarded,
duplicate conditions overwritten, and an unpunctuated `vendor` truncated to
`vend`. These are observed semantic losses, not evidence of intentional gaming.
The operator stopped the attempt's LLM follow-up worker; native supervision
settled normally. Its actual validation failure was an additional infrastructure
issue: the absolute `/usr/bin/python3` command was rejected before source replay
by the sealed launcher. Do not credit the old gate with catching these losses.
Candidate v16 remained at `eab8b09db840f0468939a53e956eb33f954b8684`; queue
revision 138 had 15 blocked, 16 ready and one retrying task. No optimizer update
or proof admission resulted.

New task creation uses the native sealed `python3` launcher, not `sys.executable`.
Preflight checks the native runtime's shell-command grammar before provider
dispatch, in addition to dependency admission. Historical commands are not
rewritten: incompatible old tasks fail preflight until a separately versioned
task is prepared. Fresh validator deployments use the matching launcher name.

New extension packets use `autoformal-extended-repair/v3` (the structural IR is
still `legal-surface-ir/v2`). The old v2 acceptance probes remain unchanged.
The stronger v3 policy contract rejects unrepresented list disjunctions,
operative-heading loss, altered/duplicate outline labels and mixed permission
residue, and requires intact word endings and preservation of repeated
conditions. These public regression probes are not held-out legal benchmarks.
The focused contracts/queue/launcher suite passed 119 tests with an explicitly
imported private accelerate pin (`qualification-v3-policy-launcher-pinned-final.xml`).
An earlier environment-only pin loaded the incompatible nested checkout; that
failed receipt remains retained rather than being hidden or called a pass.

The new private v17 snapshot (`2e2091e97633214796f35fa7cbdd109c6474b31b`)
passed **278 tests**. `versioned-v17-task-materialization.json` records thirteen
new task revisions with the corrected launcher (one stronger policy task and
twelve joint baseline repairs); all 32 preexisting task records were unchanged.
Queue revision 165 contained 15 blocked, 29 ready and one retrying task. Earlier
task revisions remain evidence, not assumed completions or reset retry budgets.

`v17-policy-gate-regression-audit.json` replays the actual retained patch: all four
legacy cases pass, but all seven additional v3 cases fail. A real sealed-launcher
smoke check reaches the protected validator and correctly rejects the untouched
scaffold's missing task-owned regression (`v17-native-launcher-smoke-bound.json`).
The initial direct smoke invocation omitted the scheduler's runner-policy
binding; its failed receipt is also retained. Neither smoke check accepts a
repair or trains a model.

The next live dispatch stopped **before claim** because concurrent edits changed
the protected shared queue adapter after v17 qualification. The private snapshot
was not altered and the equality guard was not bypassed. See
`v17-concurrent-harness-drift-stop.json` for file hashes and queue state. Coordinate
a stable shared revision, review the new metadata merge and qualify a new frozen
snapshot before restarting. There is no continuously running supervisor after
this stop, and no accepted compiler repair or optimizer update is claimed.

Before each bounded native dispatch, the launcher generates a compact diagnostic
note with the candidate parser's actual element count and hashed AST code anchors.
Native context compilation binds its SHA-256, task CID and Git revision. The note
is read-only evidence, never edit authority, and grants no terminal tools. Wrong
task, stale revision, altered bytes and symlinks are rejected. Continuous operation
uses the feedback coordinator's fresh `--once` child per task, not one stale note
across a multi-task native invocation. The launcher rejects live calls without
`--once` before loading the dependency or opening a database. Its focused launch
and context tests passed 20 cases after adding this guard.

Qualification: 290 dependency-policy tests passed (one Quack case deselected);
71 retention/context/runner tests passed, with one preexisting order-sensitive
route test run separately and passing on both v1 and v2. The frozen v9 datasets
snapshot passed 186 tests. Native context tests verify that the note is rendered
without widening scope. These tests do not prove that the model will repair a task.

For a **new private snapshot**, `prepare_autoformal_validator_profile.py`
generates an `apply_patch` payload on stdout (JSON `patch` field):

```bash
python3 scripts/ops/legal_ir/prepare_autoformal_validator_profile.py \
  --repository-root workspace/autoformal-supervisor-20260925/repair-repository-next \
  --runtime-root workspace/autoformal-supervisor-20260925
```

Apply that generated patch, then repeat the command with `--seal`. The seal is
written exclusively beside the private repository, never into task authority.
Commit only the deployment configuration in the private snapshot before launch.
Both runners reject configuration/evaluator drift or a missing operator seal;
native protected paths also include `pyproject.toml`, `setup.py` and the sealed
validator dependencies. A new profile anchors the current `setup.py` bytes but
requires the existing reviewed extra's exact requirement-list digest. Existing
profiles are not silently refreshed. The current legacy setup-file hash is stale
after commit `3a89ebcd0` changed Python classifiers; its extra remains unchanged.

The fixed replay validator disables dependency auto-installation, inherited
pytest options, third-party plugin auto-loading and conftest hooks. It executes
the same four fixed regression files plus the task's new regression, freshly.
Dependency qualification is not evidence that a repair passes source replay.

The initial local topology is one embedded implementation owner, not a
multi-process Quack watchdog. The native watchdog rejects embedded authority;
use its supported in-process implementation loop for this new local queue.
A future distributed topology requires a real Quack owner and typed producer
admission. Never demote an existing Quack store to a direct-file writer.

`control.duckdb` is task lifecycle authority. `training.duckdb` holds native
training runs and private candidate versions. Sealed JSON evidence packets are
immutable artifacts, not JSONL task authority. HF Parquet/board/locator packages
remain optional exports; no live publication is performed by these commands.

## One real training/feedback cycle

Run from the submodule root. Supply a verified v6 job manifest with exact source
bytes, a frozen split index and native embedding-production evidence:

```bash
python3 scripts/ops/legal_ir/run_autoformal_training_cycle.py \
  --accelerate-root ../ipfs_accelerate \
  --job-template workspace/test-logs/federal-corpus-audits/native-embeddings-20260925-r2/job.json \
  --database workspace/autoformal-supervisor-20260925/control.duckdb \
  --runtime-root workspace/autoformal-supervisor-20260925 \
  --max-training-seconds 60
```

The example consumes an existing locally prepared U.S. Code corpus job. It does
not perform a new BM25 query or prove that all retrieved corpus records are
legally faithful. Acquisition/selection must be bound upstream; arbitrary hits
without verified source/embedding/split manifests are not training inputs.

The native worker evaluates and trains with sample memory disabled, preserves
cross-entropy/cosine guardrails, and records before/after metrics. The optimizer's
time budget is cooperative; input loading and final receipt/checkpoint work are
additional. Candidate completion does not promote the production checkpoint.
Use `--base-version` only for a prior private candidate in this same runtime.

Both runners now default to a 600-second training budget and allow all five
native update families (`--max-update-families 5`), with one bounded line-search
attempt per family. The former hard-coded cap of one selected only global IR
view logits: it could never update the family-classification or decoded-embedding
heads. Use `--max-update-families 1` explicitly for that narrower diagnostic.
`--max-line-search-attempts` accepts 1–6. These bounds affect exploration, not
objective weights, sample-memory policy, or regression tolerances. Native
profiling is enabled for future jobs. Allowing a head does not prove its update
was attempted or accepted; inspect the generated native epoch reports.

Baseline holdout evaluation and training-cache priming count toward the native
cooperative budget. The first 60-second run spent roughly 424 seconds there and
recorded **zero attempted updates**, not rejected gradient steps. A checkpoint
receipt by itself therefore cannot show that learning occurred.

The all-head pilot `cycle-4297d39a1d1e40aca09ccf0dca6523ac` finished in about
1,360 wall seconds: four attempted updates, zero accepted, and unchanged
checkpoint bytes and CE/cosine metrics. Its native stop reason was
`projection_timeout`; one projection operation alone exceeded the cooperative
600-second budget. This exposes a deadline-checking gap, not successful learning.
The enclosing 30-minute process bound held. All 19 compiler discrepancies remain.
See that cycle's generated `cycle-summary.json` for receipt-bound measurements.

After training, only training-partition source records enter compiler replay and
repair packets. Validation/canary text is not sent to the editing agent. Compiler
replay is an independent structural/lexical diagnostic, not learned semantic
equivalence and not legal admission. Model inference/training is recorded
separately; a generated task is not evidence that either model or compiler improved.

## Observe and consume the queue

```bash
python3 scripts/ops/legal_ir/run_autoformal_supervisor.py \
  --accelerate-root ../ipfs_accelerate \
  --database workspace/autoformal-supervisor-20260925/control.duckdb \
  --runtime-root workspace/autoformal-supervisor-20260925 status
```

Use `supervise` without `--implement` to validate and print the native launch
arguments without claiming tasks. With `--implement --once`, execute one native
backlog pass. For continuous operation, use `run_autoformal_feedback_loop.py`,
which regenerates the task-bound context between native passes. Direct live
multi-task calls are refused. Keep one owner for this local topology. Live worker qualification
must establish that isolated worktrees contain the intended current compiler and
protected validators; a dirty/untracked source tree is not captured by HEAD alone.

Use the read-only task preflight before another implementation attempt. It
generates the full receipt on disk instead of printing it in the conversation:

```bash
python3 scripts/ops/legal_ir/run_autoformal_supervisor.py \
  --accelerate-root workspace/autoformal-supervisor-20260925/accelerate-retained-validator-v2 \
  --database workspace/autoformal-supervisor-20260925/control.duckdb \
  --runtime-root workspace/autoformal-supervisor-20260925 preflight \
  --repository-root workspace/autoformal-supervisor-20260925/repair-repository-next \
  --receipt workspace/autoformal-supervisor-20260925/launch-preflight-next.json
```

The receipt path must be new. This diagnostic checks the next native-eligible
task's evidence, outputs, validation command and native dependency contract;
it neither claims work nor qualifies the entire queue. The native bridge still
rechecks dependencies in its actual execution worktree. The implementation
launcher and feedback coordinator now run this check before dispatch too.

Editorial-only headings are not automatically assigned a legal status. The
coordinator now routes sealed, unclaimed packets with that intake alarm to
native `blocked` review state before selecting eligible repairs. This retains
the failed observation, packet, previous task revisions and validation contract.
The transition is not completion or validation and cannot count toward a better
score. Other eligible repairs can proceed; once only unresolved tasks remain,
the coordinator stops instead of declaring the queue drained or training against
a fabricated success. Reobservation never reopens a blocked task automatically.

For an explicit owner-run preview, use `route-intake --receipt NEW_PATH` on
`run_autoformal_supervisor.py`; add `--apply` to perform the revision-checked
native transitions under the runtime owner lock. Source classification and any
later rearm remain separate, evidenced decisions; do not reset blocked tasks to
ready merely to resume dispatch.

The first real router-driven repair pilot exposed a second input alarm:
dangling references such as `under .` and `Except as provided in ,`. These are
flagged in both the failed row and preserved rows; the system must not invent
the missing reference or erase it to improve a lexical score. The pinned source
artifact itself contained the first missing citation (identity normalization),
so byte-integrity verification was not a source-completeness check.
Additional alarms cover dangling definition references (`has the meaning given
... in .`, `established in .`) and bracketed repeal/reservation headings. They
are review routing only, not a claim that every incomplete source is detected.
Present references and ordinary inch abbreviations are covered by negative tests.

That pilot's candidate removed the dangling reference and coerced a declarative
classification into an obligation. The operator stopped its owned provider
group before completion, retained the diff and intervention receipt, and let the
native supervisor record a blocked terminal attempt. The private candidate
branch was unchanged and no model trained on the rejected patch. New protected
regressions check that declarative classifications are not fabricated O/P/F
rules and unresolved reference facets cannot disappear during projection.

The native worktree pool reclaimed that failed scratch checkout despite merged
cleanup being disabled. Its diff was already saved and is recoverable. Future
launches explicitly disable pool reuse (`IPFS_ACCELERATE_AGENT_WORKTREE_POOL_ENABLED=0`).
This is necessary but **not sufficient** for retention: native interrupted-worktree
cleanup also calls removal for non-pooled attempts, independently of the merged
cleanup sweep limit. The v8 attempt was protected with an operator Git worktree
lock before termination. Unattended execution requires a qualified retain-all
path covering cleanup, generated files and initialized submodules; do not claim
the two existing switches alone provide that guarantee. The retained-storage
stop remains the limit. The rejected candidate is restored only for diagnostic
mutation tests, never as a training or merge seed.

Prepare a private candidate repository without changing the primary checkout's
index or branch (destination must be new; retained snapshots are never removed):

```bash
python3 scripts/ops/legal_ir/prepare_autoformal_repair_repository.py \
  --destination workspace/autoformal-supervisor-20260925/repair-repository-next \
  --runtime-root workspace/autoformal-supervisor-20260925
```

After fixing and qualifying the dependency contract, pass that path via
`supervise --repository-root ... --merge-target-branch autoformal-candidate`.
Protected harness files must match the launcher checkout exactly. If the harness
changes, prepare another snapshot; do not silently run an older validator.
Candidate merges stay in this private repository, not the shared dirty checkout.

Tasks now declare native output mappings and structured validation argv. The
first local batch preceded that fix; `upgrade-ready-outputs` explicitly upgraded
its 19 never-dispatched ready tasks, retaining lifecycle status and event history.
Ordinary enqueue still never rewrites an existing task. Each new repair must add
one task-specific regression alongside the fixed protected suite. The migration
refuses missing-output tasks that are no longer virgin/ready.

Repair packets bind source text, source/release identities, compiler/model
versions, named preserve/replace scope, full evidence hash and replay commands.
Repeated observation of the same packet cannot reset task status. Workers must
pass the protected exact-source replay and regression suite; editing the task
packager or asserting a receipt is not accepted as fixing the failed span.

Do not treat an empty ready queue as success if tasks are blocked, failed or
quarantined. Verify native completion evidence, the resulting code diff, fresh
source replay and measured regressions before claiming that the loop drained.
Retain caches/evidence and stop at the storage bound rather than deleting old
results. Live validated code changes and a demonstrated subsequent learning/
replay cycle remain required before claiming recursive improvement.

## Continuing feedback runner (recursive improvement not yet demonstrated)

`run_autoformal_feedback_loop.py` is the single-owner coordinator. It drains
ready tasks through the native `supervise --implement --once` path and, after
the queue has no unresolved work, runs training/replay in a fresh process when
the candidate Git revision, compiler files, corpus job or training budget changes.
It uses `feedback-loop.duckdb` for phase bookkeeping only: this journal cannot
complete a native repair task or promote a model. Repeated observations differing
only in checkpoint identity retain separate sealed evidence without minting new
tasks or resetting retries. Changed captures still produce distinct work.

Using the qualified private dependency, prepare and seal a **new** private
snapshot containing the current coordinator and protected harness, then pilot:

```bash
python3 scripts/ops/legal_ir/run_autoformal_feedback_loop.py \
  --accelerate-root workspace/autoformal-supervisor-20260925/accelerate-retained-validator-v2 \
  --repository-root workspace/autoformal-supervisor-20260925/repair-repository-next \
  --runtime-root workspace/autoformal-supervisor-20260925 \
  --database workspace/autoformal-supervisor-20260925/control.duckdb \
  --job-template workspace/test-logs/federal-corpus-audits/native-embeddings-20260925-r2/job.json \
  --max-training-seconds 600 --implementation-timeout 600 \
  --phase-wall-timeout 900 --max-phases 1 --implement
```

Omit `--max-phases` for continuous operation after qualification. Creating `STOP`
in the runtime requests shutdown; the runner observes its child until terminal.
Every phase retains its log. Unchanged clean input idles instead of retraining
indefinitely. Native eligibility, rather than status names, controls dispatch:
`retrying` and other pending states wait for native backoff/dependency admission.
Waiting is not successful draining or permission to retrain. A bounded pilot
returns a `waiting` receipt rather than waiting indefinitely. Failed/blocked/quarantined tasks, a native pass with no task/code
progress, or discrepancies remaining without a ready task stop the workflow
for inspection. Interrupted journal phases require actual process/receipt
reconciliation; a stale lock filename is never treated as a live process.

The runner reserves storage before each phase, checks usage while a child runs,
and never deletes caches to continue. This is a polling guard, not a filesystem
quota. Bounds remain at or below the requested 50,000,000,000-byte cap. Training's
projection budget and the overall phase wall timeout are separate.

The first actual pass with the frozen matching dependency exited normally but
deferred its task before provider dispatch: the scoped dependency contract only
accepts exact task-bound pytest commands, not our sealed replay validator.
Its native disposition is a retry with backoff, not a completed repair. The
controller then rejected the previously unhandled `retrying` status; that
controller bug is now fixed without resetting any native retry.

Before the private policy extension, queue revision 82 had 18 ready, one retrying,
and zero validated repairs from this loop. The historical generated
`launch-preflight-after-retry-fix.json` reproduces the dependency rejection
without another claim. It also flags an editorial-only `Omitted` heading: replay
currently labels all packet rows operative, so this task needs source intake
review, not a compiler patch that invents a norm. The heading alarm is only a
conservative review gate, not legal classification or a passing score.

That dependency rejection was subsequently resolved by the approved private
sealed-validator extension, without dropping replay or dependency checks. A
real router-driven attempt then produced the rejected semantic shortcut
described above. Use `status` and generated native receipts for current task
counts; do not treat historical observations as live state. Older candidate
snapshots must not be restarted with a stale protected harness or silently
refreshed operator seal.

The v8 bounded repair (`cycle-30deb119935d4af88e99dc670ab46b9d`) ran a real
provider attempt for about 633 seconds including startup and teardown. The
provider timed out (124), produced no code changes, and native admission refused
`no_change_completion_not_allowed`, recording a retry rather than success.
The locked worktree was retained. `bounded-repair-v8-review.json` records the
generated diagnostics; no validated repair or optimizer update resulted.
The agent's sealed tools intentionally exclude terminal execution. Improve
task context and gather independent diagnostic feedback without bypassing that
policy. This run predates the v2 retention implementation; the later v9 result
below verifies its real timeout cleanup path, not arbitrary submodule topologies.

The v9 bounded repair (`cycle-297821ce15ab417e997646d8b6d16998`) also timed out
(provider 124) without a patch. Its diagnostic note was present in the native
context, but 136 tool calls produced no validated repair; improved efficiency is
not demonstrated. Native authority recorded a retry. The coordinator rejected
unchanged task counts and compiler identity as no observable progress, so its
phase is failed, not a successful repair or drained queue.

Native v2 emitted `worktree_artifacts_retained` and the worktree, branch and
generated files remained without a manual Git lock. The candidate HEAD stayed
`8518532e0de995617190e337416ccbbe16a53dc0`, clean and unchanged. The generated
`bounded-repair-v9-review.json` records the evidence hashes, test results and
queue revision 102 (13 blocked, 5 ready, 1 retrying). Retained runtime storage
was 19,066,088,143 bytes, below the 50,000,000,000-byte stop. No continuous
runner remains active and no optimizer update or model promotion resulted.
Review the repeated no-change failure before another provider dispatch; do not
silently reset its native retry budget. The later single-task launcher guard
requires a fresh sealed candidate snapshot before using the updated harness.

The next context revision records a bounded executed-function trace on the failed
training row only: exact allowed source paths, function lines, call counts and
list-return sizes. It excludes source values, frame locals and holdouts, restores
the profiler on exceptions, and rejects source drift. This localized the DOE
case to `analyze_normative_sentence` returning no elements after segmentation;
it does not determine a legally correct replacement modality.

The original-source v10 snapshot stopped when concurrent work changed during
copying; its partial directory remains and must not be launched. The v11 pilot
instead derives from the tested v9 pre-deployment source revision, changing only
four harness/test files and the private deployment profile. Its frozen revision
is `7ab255cb0ca48c8f09fc076f58fdc573183a0020`, with 193 tests passing. The native
preflight passed at queue revision 102. Pilot
`cycle-5b47c014135145d89ffe21bedb98903e` uses a 1,200-second provider budget and
a 1,500-second enclosing wall limit. Its launch is not a successful repair;
inspect terminal native state and source replay before making an outcome claim.

That v11 attempt produced a patch and reached native validation. Operator probes
then showed that its new coverage helper silently discarded a distinct recipient
and an unresolved different-statute reference when their final tokens matched
represented text. The implementation provider had already exited. The operator
saved the patch, signalled only the identity-checked validation-runner process
group, and left the native owner to record `declared_validation_failed`.
This is operator rejection, not a claim that the old frozen tests detected it.
The candidate branch stayed unchanged; the rejected attempt commit
`a08d7f242a35ad7395196a7ea59e33c3c986e80a` and worktree were retained.

Two new protected projection tests pass on the baseline and fail on that exact
rejected candidate. `bounded-repair-v11-review.json`,
`rejected-8fdf-v11-intervention.json`, and
`mutation-rejected-v11-token-coverage.json` record the evidence. At queue revision
105 there are still 13 blocked, 5 ready and 1 retrying tasks. The native record
reports attempt 3 but does not report its retry budget exhausted: do not assume
the per-Portal `--max-task-attempts 3` bounds separate fresh database passes.
The coordinator's no-progress stop remains active. No loop is currently running.

The new `learned_feedback.py` adapter uses the native checkpoint resolver and
the verified v6 input contract to run `compiler_guidance_for_sample` on training
members only, with sample memory and causal counterfactual probes disabled.
It records the exact candidate identity, actual source hashes and any input
pipeline drift since training; vectors and teacher targets are not exported.
The training entry point now saves `learned-feedback.json` and attaches bounded
model hints to newly generated packets and native context notes. Independent
compiler replay still receives its original source-derived captures, not
invented learned triples. Changed numerical hints alone cannot reset retries or
create another task for an unchanged compiler failure.

The saved checkpoint produced 43 observations in 15.37 seconds without changing
its state. All nine family probabilities were uniform on every training member;
this is measured inference, not useful classification or evidence of improvement.
The probe identified parser drift since the worker run. Nineteen real paired
source replays gave identical results with and without the hints: all remained
failing, and a validation member was refused before feedback inference. Generated
receipts are `learned-feedback-training43-v1.json` and
`learned-feedback-replay-parity.json`. The integration suite passed 212 tests.

This adapter is not a symbolic text decoder or proof generator. It neither
changes cross-entropy/cosine acceptance guards nor admits law. It is wired in
the current source tree, but the stopped v11 repair snapshot remains frozen;
deploy it only through a freshly qualified snapshot, not by editing that run.

A same-checkpoint diagnostic found that the saved configuration sets feature and
semantic-slot family-logit multipliers to zero. On the 43 training records,
setting only the feature multiplier to 0.5 changed family-target cross-entropy
from 2.1972245773 to 2.1926282561, while cosine similarity stayed 0.1961161351.
The weights did not change, no optimizer update was accepted, and no validation
or canary qualification was performed. This motivates a separate, lineage-bound
configuration/training experiment; it is not a training gain or a new score.
See the generated `learned-feedback-head-scale-diagnostic.json` receipt.

## First real cycle evidence (2026-09-25)

`workspace/autoformal-supervisor-20260925/cycle-df6d861fa7dc4b1e8d3b219fd8be40ef/cycle.json`
records 43 training and 3 validation records, 450.53 seconds total, 19 queued
structural discrepancies, and **zero accepted optimizer updates**. The 60-second
cooperative projection budget expired. Cross-entropy remained 2.1972245773362196;
cosine loss remained 0.803883864861816. This is exercised infrastructure, not
demonstrated model improvement. Candidate checkpoints and all receipts remain
private and unpromoted. A frozen private source snapshot passed 61 baseline tests.

## Bounded training qualification (2026-09-25)

`cycle-fbc40dc01296476ba19612650a50a80c/cycle.json` records a second cycle on
the same frozen compiler and source corpus, continuing the prior private model
with a 600-second budget. It finished in about 449 seconds. This time one global
IR-logit update was attempted and rejected for LegalIR cross-entropy regressions;
the aggregate objective delta was -0.24570555131534766. Zero epochs were accepted.
The candidate checkpoint SHA-256 exactly equals its base checkpoint SHA-256.
No tasks were added and no native task status was reset. This is a demonstrated
guarded rejection, not successful learning or a compiler repair.

The updated datasets harness passed 127 tests with the frozen accelerate pin.
It enables a subsequent bounded all-heads experiment and records profiling;
these configuration tests alone do not demonstrate an accepted optimizer update.

## Compact evidence reports

Generate summaries from completed cycles rather than copying their embedding
arrays or full profiler event lists into prompts:

```bash
python3 scripts/ops/legal_ir/summarize_autoformal_cycle.py \
  workspace/autoformal-supervisor-20260925/cycle-fbc40dc01296476ba19612650a50a80c \
  --output workspace/autoformal-supervisor-20260925/cycle-fbc40dc01296476ba19612650a50a80c/summary-next.json
```

The generator binds cycle/worker receipts, hashes both checkpoint artifacts,
refuses conflicting execution identities and trust promotions, and retains the
full evidence. Existing outputs are never overwritten. Summaries contain no
source sentences, canary text or embedding arrays. Artifact-byte changes,
reported model-state changes, accepted optimizer updates and compiler gaps are
separate observations: none is interchangeable with a completed repair or a
legal proof. Profile stage durations are inclusive and overlap; do not add them
to estimate wall time. This is a diagnostic report, not a new admission gate.

## Opt-in pinned physical-row enqueue

`scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py` has a separate
`--source-ingest-profile raw-coordinates-v1` path for a bounded local Parquet
selection. The default legacy ingest and its historical span IDs are unchanged.
This profile captures exact decoded source text before the legacy record
adapter strips whitespace or supplies fallback text. It invokes the existing
`inventory_uscode_source_coordinates` and `validate_uscode_source_coordinates`
APIs, then persists the complete report and span bindings through
`SpanCache.enqueue_source_coordinates`.

Supply independent source pins from the retained source descriptor: the
lowercase 40-hex repository revision, canonical relative repository path,
whole-file SHA256 and exact byte count. `--source-release-id` is a required,
explicit identity for this source selection; the legacy default release ID is
not reused. A matching local file digest does not authenticate its claimed
repository revision, establish an official edition or verify legal meaning.
Hashing an arbitrary replacement and declaring its digest is not source review.

For example, after setting these variables from that descriptor, run from the
repository root with an approved local Python environment containing PyArrow
and DuckDB:

```bash
python scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py \
  --source-ingest-profile raw-coordinates-v1 \
  --parquet "$SOURCE_PARQUET" \
  --source-revision "$SOURCE_REVISION" \
  --source-path-in-repo "$SOURCE_PATH_IN_REPO" \
  --expected-source-sha256 "$SOURCE_SHA256" \
  --expected-source-bytes "$SOURCE_BYTES" \
  --source-release-id "$SOURCE_RELEASE_ID" \
  --source-row-offset 0 --limit 8 \
  --cache "$NEW_CACHE" --enqueue-only --no-resume
```

`NEW_CACHE` must be absent, with no existing `.wal` sidecar, in an existing
canonical directory. Existing files, symlinks and catalogs are refused before
opening a catalog; no historical row is backfilled or assigned a new identity.
After complete source and coordinate validation, the profile constructs a
private staging catalog, closes it and publishes it atomically without
overwriting a racing destination. The emitted `raw_coordinates_enqueued`
receipt includes the complete report's SHA256. Keep this pin independently
when subsequently reading the report with
`SpanCache.read_source_coordinate_report`.

`--source-row-offset` is a zero-based physical Parquet row ordinal, not the
legacy valid-document skip count. The complete requested selection must exist;
missing text or CID, whitespace-only text and out-of-range selections fail
instead of being filtered or replaced by citation text. The retained witness
binds each physical ordinal to the whole file and revision/path declaration,
the exact projected law-field metadata and selected-row digest. Exact decoded
text, including leading/trailing whitespace, CRLF and Unicode, is retained in
the coordinate report. Span coordinates are half-open Unicode-code-point and
UTF8 byte ranges within that decoded text. They are not byte positions inside
the compressed Parquet file or recovered raw HTML.

Span IDs follow the existing inventory API for the complete selected document
population, including its global span ordinal. This new profile does not
silently reuse the historical CLI's per-document ordinal reset. Different
selection windows are separate populations; joining them or retrofitting old
catalog identities requires an explicit transport/replay contract.

The profile enforces these fixed bounds:

- An explicit `--limit` of 1–128 physical rows; offset and file row count at
  most 10,000,000; the complete requested range must be present.
- A regular, nonsymlink local file of at most 1 GiB, held open while its pinned
  size, SHA256 and unchanged file identity are checked.
- At most 1 MiB of UTF8 text per row and 8 MiB across the selected rows;
  projected non-text row metadata is bounded to 48 KiB per row.
- A Parquet footer of at most 8 MiB, at most 128 schema columns and 8,192 row
  groups; selected row groups are at most 64 MiB each and 128 MiB in total.
- The existing coordinate API's complete-report, document metadata and span
  bounds also apply. These checks do not certify kernel-enforced resource
  isolation or a full-corpus execution budget.

This enqueue-only profile does not poll remote checkpoints, download sources,
upload, compile, dispatch workers, train, run Lean or change supervisor state.
Resume, compiler options, upload options and the separate `fenced-v1` runtime
are incompatible with it. Custody and geometry observations keep source
authority, legal meaning, formalization, admission and training authority false.

The first selected landing (`e9fc55927`) passed 116 cases and 348 test phases:
81 coordinate/cache/full-norm cases and 35 raw-ingest cases, including the
unchanged legacy record path and refusal to overwrite an existing catalog.
The new controls are in
`tests/unit/logic/test_uscode_raw_source_coordinate_ingest.py`. Both cohorts used
the existing native validation owner, authenticated candidate source imports,
and verified process cleanup and resource release. Retained requests, JUnit,
source/import readbacks and sealed results are under
`workspace/test-logs/federal-corpus-audits/legal-ir-selected-landing-20261020-01/`
(`attempt-coordinate-fullnorm-05` and `attempt-raw-source-05`). The tested storage
versions were DuckDB 1.4.3, PyArrow 25.0.1 and NumPy 2.1.3. Package startup
containers were isolated for these focused checks; this does not qualify a
wheel installation, a full-corpus run or legal meaning.

## Portable selected source occurrences

An explicit `uscode-paired-span-bundle/v3` manifest carries one complete source
report and a small occurrence index in the existing artifacts table. The three
Arrow tables retain their v2 row schemas; observation IDs and goal IDs remain
the same for matching explicit inputs. Default v1/v2 reading and v2 writing
remain unchanged; their rows do not acquire inferred
coordinates. The v3 namespace is `autoformal/uscode/paired-v3`.

Use `cache.export_source_coordinates(report_pin, source_span_ids=selected_ids)`
to obtain the complete report once and source/reference rows for the selected
live cache entries. Pass their existing `source_provenance_json` alongside the
actual source-bound observations to `build_paired_census`, with the explicit
`source_coordinate_report` and `expected_source_coordinate_report_sha256`
arguments. Set the producer's `release_id` to the report's declared release;
this label is not an independently authenticated statutory edition. The writer
and loader replay the complete original document population and occurrence
references, including unselected context. Subsetting documents before replay
would change global span identities and is refused.

The first profile supports one report and 1–128 selected observations per
bundle. The report artifact is capped at the existing 16 MiB artifact bound,
within the unchanged 64 MiB aggregate input bound. Its exact serialized-byte
SHA256, the complete-report pin and the report's embedded content seal are
distinct commitments. Nested raw metadata insertion order is preserved; none
of these hashes supplies source authority or legal meaning.

After retaining the complete repository layout locally, import into a new cache:

```bash
python scripts/ops/legal_ir/import_span_cache_exchange.py \
  --manifest "$RETAINED_REPOSITORY/$MANIFEST_IN_REPO" \
  --paired-repository-root "$RETAINED_REPOSITORY" \
  --repository-id justicedao/uscode-autoformal-span-cache \
  --revision "$SPAN_CACHE_COMMIT" \
  --expected-manifest-sha256 "$MANIFEST_SHA256" \
  --expected-coordinate-report-sha256 "$COMPLETE_REPORT_SHA256" \
  --enqueue-source-cache "$NEW_CACHE" --output "$IMPORT_RECEIPT_DIRECTORY"
```

Keep both expected hashes independently from the imported bundle. This local,
unsharded path retains the exact manifest and tables, validates the complete
report and all selected references, then uses the same fresh-cache writer as
raw ingest. Only selected spans become pending; unselected report spans do not
enter the queue. Original occurrence indices survive. Existing catalogs and
orphan WAL files are refused, including a racing destination. Compiler/model
statuses and repair goals remain observations: this operation neither seals
sources nor materializes supervisor work.

The retained bundle, cache and receipt have separate publication boundaries.
A later receipt failure may leave retained evidence and a published pending
catalog; the existing-catalog refusal also applies to that retry.

The durable feed uses the same existing stateless `load_paired_payload` reader.
V3 record identity additionally binds the report pin and original span index,
so identical normalized text under another physical context cannot silently
merge. Complete reports are returned once per pin outside individual records;
feed acknowledgement remains a separate explicit action.

Focused qualification passed **278 cases / 834 test phases**: 71 coordinate/cache
and raw-ingest regressions with unchanged executed source, plus 207 paired,
selection, feed and source-import controls. Requests, JUnit, source/import
readbacks and native release receipts are retained under
`workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-paired-transport-20261020-01/`
(`attempt-regressions-01` and `attempt-transport-03`). The tested storage versions
were DuckDB 1.4.3, PyArrow 25.0.1 and NumPy 2.1.3. The transport run used genuine
root, autoformal and deontic initializers with model/provider imports refused;
other package initializers remained isolated. This qualifies the focused local
transport, not a wheel installation or optional-provider execution. Training
data, competent source/meaning review, a source-context graph and a checked Lean
corpus retain their existing owners and review requirements.

## Source-context intake from portable occurrences

The existing compact source-context cache intake now has an explicit v2 profile
for the coordinate transport above. Reuse
`prepare_source_context_cache_intake_v2` and
`validate_source_context_cache_intake_v2` in
`logic/autoformal/legal_compact_source_context_cache_intake_v1.py`, with the
metadata companion's `legal-paired-manifest-inventory-request/v2` request and
the independently supplied `legal-compact-source-context-cache-bindings/v2`
association document. The original-bound source inventory remains a separate
input. The module's current guide documents all arguments and report fields.

This first intake profile admits one paired-v3 manifest and at most 64 declared
physical rows. It retains the exact complete report once, as an opaque UTF8
string in the existing payload report, plus each selected occurrence's original
global span index and canonical provenance reference. Exact artifact-byte,
complete-report and manifest pins keep their separate roles. Missing, corrupt
or unsupported bundles preserve all declared row slots and expected pins;
actual coordinate fields remain unavailable. Unexpected exceptions and changed
source/file witnesses still refuse the operation.

Coordinate replay does not choose an inventory occurrence. Associations remain
explicit caller declarations, and equal text is only a consistency observation.
Cached formal outputs and vectors stay outside source-context construction.
Inference views remain null, training/evaluation masks remain zero and source,
meaning, context-permission and Lean authority remain false. The existing v1
entrypoints retain the legacy paired-v1/v2 profile. Strict current producer pins
identify a fresh source compatibility generation; old receipt hashes are not
reissued as its qualification.

The dependency closure reuses the existing compact-content, lexical-context,
physical-inventory and shared-token owners and their owning tests. It also
includes the existing split guard's rejection of supplied items that resolve no
manifest member. No numerical kernel or model profile changed.

Fresh native qualification passed **594 cases / 1,782 test phases**: 385 pure
owner and split-membership controls, then 209 legacy and coordinate
metadata/payload/intake controls. Native requests bind 114 and 77 function
selectors; exact expanded case IDs, all phases and JUnit outcomes are verified
independently. The historical retained sixteen-row external integration case
was explicitly excluded, with no skip credit. Evidence, source/import manifests,
original native cleanup and storage release receipts are retained under
`workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-context-intake-20261020-01/`
(`attempt-pure-03`, `attempt-paired-03` and
`final-independent-qualification-v03.json`).

Two earlier wrapper attempts remain preserved and unqualified: one stopped on
missing import pins and one rejected a legitimate JUnit evidence property after
all 385 pytest cases passed. Both unused 128 MiB storage promises were released
through the existing recovery owner without deleting evidence. The final run
used the same product/test bytes. This qualification covers authored local
fixtures and actual storage codecs, with genuine deterministic compiler owners
and selected package startup isolation. It does not execute numerical engines,
providers, training or Lean, authenticate legal interpretation, or admit a
source-context graph or unified Lean corpus.

## Coordinate-bearing source/span/entity join

The existing `legal_source_span_entity_join_v1` owner now exposes the explicit
`prepare_source_span_entity_join_manifest_v2` and
`validate_source_span_entity_join_manifest_v2` APIs. They consume the qualified
paired-v3 coordinate reader, existing five-file source-package metadata intake
and existing twelve-field entity metadata contract. This port reuses the
source-package owner and owning tests; it introduces no second join registry,
entity scanner, graph builder or model path.

Use `legal-source-span-entity-join-request/v2` with the same closed argument
layout as v1 and a `legal-paired-manifest-inventory-request/v2` paired selection.
That selection independently pins the complete coordinate report as well as the
exact manifest bytes. V2 admits one complete bundle and 1–64 declared physical
rows. Both the report pin and row bounds are checked before source preparation
or payload-table I/O. The first coordinate profile requires empty legacy joins;
v1 keeps the historical candidate recipe and paired-v1/v2 selection.

The exact ordered report UTF8 string remains once in the embedded payload
intake, and each row reference retains its original global span index and
canonical provenance reference. Equal text does not collapse physical rows or
select an occurrence in another source namespace. Source-release correspondence
remains unverified, entity semantics remain unavailable, and graph, training and
Lean authority remain false. The separate existing entity-census companion is
not implicitly upgraded to this new join profile.

Bounded original metadata snapshots, selected source pins and physical file
witnesses are checked at closing. Every closing check is attempted on failure,
with secondary findings attached to the original exception. The validator also
checks the offered report after full replay. These are ordered custody checks;
they do not establish an atomic three-repository snapshot or legal meaning.

Fresh qualification passed **128 cases / 384 test phases**: 45 genuine
source-package metadata controls, 48 legacy orchestration controls with explicit
substituted delegates, and 35 genuine coordinate/custody controls. Native
requests use 51 function selectors and independently verify every expanded case,
phase and JUnit outcome. All 209 candidate pins and 233 total source pins were
verified; 45 imported/compiled source files were separately observed. The native
owner sealed 289 files / 3,686,009 bytes and completed original process,
resource/storage and source READ release. Evidence is retained under
`workspace/test-logs/federal-corpus-audits/legal-ir-coordinate-three-cache-join-20261020-01/`
(`attempt-join-02` and `final-independent-qualification-v02.json`).

The first attempt's 128 pytest passes receive no native qualification credit:
its wrapper expected one incorrect parameter label. The fresh corrected manifest
was independently checked before launch, with unchanged product/test bytes.
All 286 failed-attempt files / 3,650,855 bytes remain retained; only its unused
128 MiB promise was released through the existing recovery owner. No existing
entity census was repeated. Model, training, provider/network, statutory
meaning, graph admission and Lean execution remain separate work.
