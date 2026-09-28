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

## Census handoff and landed repairs

The producer writes the autoencoder-versus-compiler census and the supervisor
goals to `justicedao/uscode-autoformal-span-cache`. It does not append those
goals to a local supervisor database. The bundle layout, publication command,
and later import command are in
`docs/implementation/reports/SPAN_CENSUS_DATASET_HANDOFF_20260928.md`.
`admitted` and `formalized` stay false. A repeated fingerprint is not uploaded
again. `sealed-spans.parquet` and `resume-checkpoint.parquet` are not replaced.

A later machine imports that bundle into its own supervisor. Import creates
review records. It does not run the repair commands or admit the statute.

On 2026-09-28 two parallel lanes finished repairs that the sealed validation
launcher could previously not start. Validation ran
`scripts/ops/legal_ir/validate_autoformal_repair.py`. Both receipts passed the
gate `source_replay_not_legal_equivalence` with `admitted` false and
`formalized` false.

- `AFTD-817b9bac3966fbc1e819` keeps a comparative "when compared with" phrase
  on the duty. The parser, formula builder, compiler, and both decompilers
  changed, with `tests/unit/logic/autoformal_repairs/test_817b9bac3966fbc1e819.py`.
- `AFTD-e3b018a00ef13c0c927c` changes the same five sources for its
  strict-roundtrip failure, with
  `tests/unit/logic/autoformal_repairs/test_e3b018a00ef13c0c927c.py`.
  Its regression suite was 133 tests.

Those edits were validated in an isolated snapshot and are the copies on this
tree. They are not a `lake build Legal` admit of either statute. The parenthetical
sunset repair remains covered by
`tests/unit/logic/autoformal_repairs/test_d662f265f37447dd4b36.py`.

`scripts/ops/legal_ir/run_autoformal_supervisor.py` can run one task per strict
shard. `--task-id` belongs before the `supervise` subcommand. Shard flags belong
after it. A rearmed failure is status `retrying` and is preferred over a fresh
ready task. The sealed Python launcher fix is accelerate commit `7adfbfc54`.
Portal repairs also keep the operator note bound to the DuckDB task cid, attach
a Docker `create` container before reading its output, and treat the exact
autoformal validator command as dependency-neutral.

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
