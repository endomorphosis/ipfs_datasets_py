# Agent supervisor, taskboards, and worktrees

| Field | Value |
| --- | --- |
| Interface | `AgentSupervisorExecutionContract@1` |
| Task | `IPFSDOC-017` |
| Status | `canonical` |
| Owner | architecture (datasets docs); runtime implementation owner is `ipfs_accelerate_py` |
| Source of truth | `ipfs_accelerate_py.agent_supervisor` (submodule / sibling package when present); `todo_daemon` task parsing and worktrees; admissibility bridges under `ipfs_accelerate_py.agent_supervisor` + tests in `test/api/test_agent_supervisor_*.py`; [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) §7.2; [ADR-004-FAIL-CLOSED-DEGRADATION.md](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md); program boards such as `docs/implementation/plans/*.todo.md` |
| Last verified | 2026-08-03 |
| Audience | architect, developer, operator, agent |
| Related | [PROFILE_G_PLANNING_AND_EVIDENCE.md](PROFILE_G_PLANNING_AND_EVIDENCE.md), [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md), [DOMAIN_MAP.md](../DOMAIN_MAP.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md), [ADR-003-LAYERED-AUTHORITY.md](../decisions/ADR-003-LAYERED-AUTHORITY.md) |
| Review cadence | when agent-supervisor APIs, board contracts, or merge/lease policy change |

## 1. Purpose

This guide answers: **who owns the agent supervisor runtime**, how markdown
**taskboards** become executable work, how **goals / subgoals**, **isolated
worktrees**, **proposal validation**, **retries / blockers**,
**watchdog / heartbeat**, **merge authority and receipts**, and **namespace
isolation** fit together — and what this repository must **not** invent.

It documents the model used by programs such as the IPFS Datasets documentation
refresh (`board namespace: ipfs-datasets-documentation-v1`) and adjacent
objective boards. Placement advice (which worker or lane should take a task)
is **advisory**. **Execution leases, claim resolution, and side-effect
authorization remain external or fail closed** — they are never implied by
board text, discovery, or a green unit test alone.

## 2. Audience

- **Primary:** architects and operators launching implementation / objective
  daemons; agents executing board tasks without rewriting queue status.
- **Secondary:** developers adding bridges (admissibility, IR registry) that
  must import without heavy provers; documentation authors placing runtime
  guides under `docs/architecture/runtime/`.

## 3. Scope and non-goals

### In scope

- Canonical ownership split: **`ipfs_accelerate_py.agent_supervisor`** versus
  **reusable / compatibility code** in `ipfs_datasets_py`.
- Taskboard parsing, task status marks, goal/subgoal scheduling packets.
- Isolated Git worktrees, edit allowlists, dirty-path admission.
- Proposal validation and admission budgets (path allowlists, size limits).
- Retries, blocked tasks, strategy lists, retry-budget repair tasks.
- Watchdog and heartbeat liveness for multi-lane supervisors.
- Merge queue, merge resolver, merge receipts / checkpoints.
- Namespace isolation of state, worktrees, discovery, and env prefixes.
- Fail-closed rules for execution, leases, and unvalidated proposals.

### Non-goals

- Full Profile G artifact schemas and risk math (see
  [PROFILE_G_PLANNING_AND_EVIDENCE.md](PROFILE_G_PLANNING_AND_EVIDENCE.md)).
- MCP tool catalogs or transport design (`docs/architecture/mcp/` leaves).
- Replacing or rewriting protected program inputs (human plan, objectives
  heap, todo board metadata status).
- Owning accelerate hardware backends or LLM router internals.

## 4. Context

Long-running programs decompose into **objective goals**, **board tasks**, and
**implementation attempts**. Parallel workers need:

1. A shared, human-readable **taskboard** (often Markdown with metadata).
2. **Isolated Git worktrees** so concurrent patches do not stomp each other.
3. A **daemon** that selects work, invokes providers, validates proposals,
   commits only after gates pass, and **merges** under exclusive authority.
4. **Namespace isolation** so IR-family, legal-gate, documentation, and other
   boards never share state roots or claim the same leases by accident.
5. **Liveness** (heartbeat / watchdog) so hung lanes are restarted without
   inventing success.

`ipfs_datasets_py` contributes **dataset / logic / MCP** primitives and thin
bridges. The **agent supervisor execution loop** lives in
`ipfs_accelerate_py`.

```text
  Protected plan + objectives + todo board (operator inputs)
            |
            v
  ┌─────────────────────────────────────────────────────────┐
  │  ipfs_accelerate_py.agent_supervisor (CANONICAL runtime) │
  │  objective graph · taskboard parse · worktrees · merge  │
  │  proposal admission · heartbeat · namespace state        │
  └───────────────────────────┬─────────────────────────────┘
                              |
         optional bridges     |     optional Profile G
         (admissibility, IR)  |     planning/evidence
                              v
  ┌─────────────────────────────────────────────────────────┐
  │  ipfs_datasets_py (reusable / compat provider code)      │
  │  logic.admissibility · logic.profile_g · MCP tools       │
  └─────────────────────────────────────────────────────────┘
```

## 5. Ownership and boundaries

| Owns (canonical) | Does **not** own |
| --- | --- |
| **`ipfs_accelerate_py.agent_supervisor`** — taskboard daemons, worktree lifecycle, merge queue/resolver, multi-lane runners, watchdog, namespace path layout, objective graph scheduling | Dataset domain algorithms, IR identity, proof corpus contents |
| Implementation / objective / bundle supervisor processes and their state under `data/agent_supervisor/<namespace>/` (or equivalent configured roots) | Operator-protected plan files and board *status rewriting* by workers |
| Merge authority for admitted implementation branches after validation gates | Silent promotion of placement or neighborhood confidence into execution leases |
| Retry budgets, blocked-task strategy, merge reconciliation | Profile C/D authority and policy decisions (injected validators; see Profile G) |

| This repository (`ipfs_datasets_py`) **owns** | Compatibility / adjacency only |
| --- | --- |
| `logic.profile_g` canonical DAG-JSON/CID planning and risk-evidence primitives | Root `profile_g.py` facade re-export |
| Admissibility / Intent IR surfaces consumed by supervisor bridges | `ipfs_accelerate_py.agent_supervisor.admissibility_*` adapters (live in accelerate when present) |
| MCP Profile G service transport wrappers (`mcp_server/profile_g_service.py`) | Supervisor leases, claim resolution, fencing tokens |
| Documentation of the split (this page) | Changing accelerate release trains or daemon CLIs |

**Inbound:** operators, multi-supervisor launchers, CI that runs namespace
daemons, MCP/agent workers under daemon control.

**Outbound:** Git, LLM providers, optional datasets auth/admissibility, optional
Profile G store, external validation commands declared per task.

**Rule:** discoverability of `agent_supervisor` imports, empty submodule
directories, or unit-test green on a bridge **does not** grant merge authority
or execution leases ([ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).

## 6. Canonical vs reusable / compatibility code

### 6.1 Accelerate is the execution authority

When the `ipfs_accelerate_py` checkout is present, treat these as **source of
truth** for runtime behavior:

| Area | Typical modules (accelerate) |
| --- | --- |
| Package surface | `agent_supervisor.__init__` (objective graph, trackers, vector index) |
| Markdown taskboard parse / select | `todo_daemon.engine`, `todo_daemon.task_board`, `todo_daemon.plans` |
| Implementation loop | `todo_daemon.implementation_daemon`, `todo_daemon.implementation_supervisor` |
| Worktrees | `todo_daemon.worktrees`, git helpers |
| Merge | `merge_queue`, `merge_resolver`, `merge_checkpoint`, `merge_conflict_repair` |
| Multi-lane / namespace | `multi_supervisor_runner`, `wrapper_utils.agent_supervisor_namespace_paths` |
| Liveness | `supervisor_watchdog`, daemon `heartbeat_at` status fields |
| Proposals | `task_proposal_router` |
| Objective planning | `objective_graph`, `objective_tracker`, `objective_daemon` |

### 6.2 Datasets reusable / compat surfaces

| Surface | Role |
| --- | --- |
| `logic.profile_g` / `profile_g.py` | Canonical **planning and evidence** provider for MCP++ Profile G — not the supervisor loop |
| `logic.admissibility` | Authorization composition; supervisor may **bridge** but must fail closed without allow |
| `mcp_server` tools | Thin RPC/REST exposure; no automatic lease minting |
| Router aliases (`*_router.py`) | Compat aliases into accelerate routers — unrelated to taskboards except as optional tools |
| Tests under `test/api/test_agent_supervisor_*.py` | Contract tests that import accelerate bridges **without** requiring heavy provers |

Do **not** re-implement taskboard parsing, worktree ownership, or merge queues
inside `ipfs_datasets_py`. Prefer documenting and bridging.

## 7. Taskboards and task parsing

### 7.1 Board document

A **taskboard** is usually Markdown under `docs/implementation/plans/` (or a
generated projection) with:

- A **board namespace** (e.g. `ipfs-datasets-documentation-v1`) isolating the
  program from other boards.
- A **task prefix** (e.g. `IPFSDOC-`) and often a **goal** prefix.
- Per-task sections: id, status, priority, track, depends-on, outputs,
  validation commands, acceptance criteria, conflict policy, resource class.

Operator-protected boards may be **read-only** for workers: agents implement
declared outputs but must not mark backlog metadata complete unless the task
explicitly requires it.

### 7.2 Checkbox / status marks

Legacy and daemon parsers recognize checkbox marks mapped to statuses such as:

| Mark / status | Meaning |
| --- | --- |
| needed / open | Eligible for selection |
| in-progress | Claimed or mid-flight |
| complete | Finished at board level (does not alone prove merge or lease) |
| blocked | Not selectable unless `revisit_blocked` and not protected |

`todo_daemon.engine.parse_markdown_tasks` / `select_task` pick the first
needed or in-progress task; optionally revisit **blocked** tasks excluding
protected checkbox ids. Empty or invalid metadata can force **blocked** with a
recorded blocked reason (fail closed on empty task metadata).

### 7.3 Structured fields used at runtime

Implementation packets typically carry:

- `task_id`, title, priority, track, `depends_on`
- `expected_outputs` / allowed edit paths
- `validation` commands
- `protected_paths` and admission budgets
- checkpoint directory / env (e.g. `IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR`)
- optional goal / objective ids and merge-fate objective keys

Missing required structure must not be filled with invented success — mark
**blocked** or refuse selection.

## 8. Goals and subgoals

### 8.1 Objective-layer goals (supervisor)

Accelerate’s objective stack (`ObjectiveGoal`, goal heap, objective graph)
schedules **program goals** separately from checkbox tasks:

- Goals are ordered (e.g. heap / priority / Fibonacci priority helpers).
- Goals decompose into **subgoal packets** and bundle tasks
  (`assign_goal_subgoal_packets`, bundle writers).
- Janitors may **block** or **deprioritize** tasks that fight critical goals
  (e.g. non-mission worktree cleanup backlog) and emit **janitor receipts**.

Board task `Goal id` fields (e.g. `IPFSDOC-G082`) link documentation tasks to
objective completion tracking without giving workers authority to rewrite the
objective heap.

### 8.2 Profile G Goal / Subgoal (datasets)

Profile G defines content-addressed **`Goal`**, **`Subgoal`**, **`PlanBranch`**,
**`PlanSelection`**, and **`TaskSpec`** artifacts with CID links. Those are
**planning graphs**, not automatic supervisor board rows. See
[PROFILE_G_PLANNING_AND_EVIDENCE.md](PROFILE_G_PLANNING_AND_EVIDENCE.md).

Do not confuse:

| Concept | Home | Actionability |
| --- | --- | --- |
| Markdown board task `IPFSDOC-017` | Supervisor taskboard | Executable under daemon + allowlist |
| Objective `Goal id` | Objective graph / heap | Scheduling evidence |
| Profile G `Goal` / `Subgoal` CID | `logic.profile_g` | Advisory until selection + external lease |

## 9. Isolated worktrees

### 9.1 Why worktrees

Each implementation attempt typically receives a **dedicated Git worktree**
under a namespace worktree root (for example
`data/agent_supervisor/<namespace>/worktrees/` or a shard path such as
`…/shards/<n>/worktrees/workspace-<id>`). Isolation prevents concurrent agents
from editing the same index and enables clean discard on failure.

### 9.2 Ownership helpers

`todo_daemon.worktrees` provides:

- Path normalization and **allowlist** checks (`worktree_path_allowed`,
  `resolve_worktree_file_edit_path` — rejects `..`, absolute escapes, paths
  outside prefixes).
- Detection of **disallowed dirty paths** after provider runs.
- Worktree registration / cleanup relative to Git porcelain lists.
- Owner liveness hooks so abandoned worktrees can be reclaimed only when the
  owner PID is dead (paired with heartbeat policy).

### 9.3 Edit policy

Tasks declare **allowed edit paths** (files or directory trees). Admission is
**fail closed**:

- Descendants of declared directory outputs are in scope.
- Undeclared paths outside those trees are not.
- Protected operator paths (plan / objectives / todo metadata) are never
  writable by workers even if a model proposes them.
- Size budgets (patch, provider output, single file) apply independently of
  pytest green.

Dirty trees outside the allowlist **block merge** and typically mark the
attempt failed or the task **blocked**, not complete.

## 10. Proposal validation

Providers return patches or full-file proposals. The daemon admits them only
when **all** gates pass (illustrative, aligned with current daemons):

1. **Path admission** — every changed path is allowed; no protected paths.
2. **Size admission** — patch / output / file byte budgets.
3. **Semantic / contract checks** — task-specific validation commands.
4. **Optional auth bridges** — pre-invocation admissibility must **allow**;
   abstain / reject / error / expired / replayed receipts **deny** and must not
   call the side-effect delegate ([ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)
   layers; enforcement tests under `test/api/`).
5. **Idempotency** — duplicate merge-resolve events are suppressed via
   fingerprints / resolved-event records.

`task_proposal_router` builds project-framed proposal prompts and artifact
paths under an **artifact namespace**. A written proposal is evidence of intent,
not a lease and not a merge receipt.

**Fail closed:** invalid, incomplete, or over-budget proposals are rejected;
the daemon does not “best effort” merge them.

## 11. Retries and blockers

| Mechanism | Role |
| --- | --- |
| **blocked** status | Task not selected; may record blocked reason |
| Strategy `blocked_tasks` | Daemon-level skip list for selection and merge reconciliation |
| **Retry budget** | Caps repeated validation/implementation/merge failures |
| Generated **retry-budget repair** tasks | Explicit repair work for a source task id and failure kind (`validation` / `implementation` / `merge`) |
| Transient merge deferrals | Temporary skip without permanent complete |
| Unresolved merge failures | Keep tasks out of success sets until repaired |
| Janitor deprioritize | Soft-block non-mission backlog (e.g. dirty backlogged worktrees) |

Workers must not clear `blocked` or strategy lists to hide failure. Recovery is
via declared repair tasks, operator strategy edits, or successful validation +
merge under daemon authority.

## 12. Watchdog and heartbeat

### 12.1 Daemon heartbeat

Implementation / multi-supervisor runtimes refresh **heartbeat** fields (e.g.
`heartbeat_at` on status payloads) and phase events such as
`daemon_phase_heartbeat`. Heartbeat proves process liveness and progress
metadata; it is **not** proof of task correctness or merge success.

### 12.2 Outer watchdog

`supervisor_watchdog` is a second fault-tolerance layer for long-running multi-
lane operation:

- Reads a **lane manifest** (commands, pid paths, log paths, state dirs).
- Checks **PID alive** and **status file mtime** against
  `WATCHDOG_LANE_TIMEOUT_SECONDS` (heartbeat timeout → stale).
- Restarts dead/stale lanes with backoff after
  `WATCHDOG_MAX_CONSECUTIVE_RESTARTS`.
- Optionally aggregates per-lane logs.

Env knobs include `WATCHDOG_CHECK_INTERVAL_SECONDS` and log aggregation dir.
Watchdog restart restores **process** availability only; it must not invent
completed tasks or merge receipts.

## 13. Merge authority and receipts

### 13.1 Who may merge

**Only the supervisor/daemon merge path** (merge queue + configured merge
resolver, under the namespace state dir) holds **merge authority** for agent
worktrees. Individual workers:

- Edit only inside their worktree + allowlist.
- Produce commits or patches as instructed.
- **Do not** push/merge to the program integration branch except through the
  daemon after the **validation gate** passes.

### 13.2 Merge pipeline (conceptual)

```text
  worktree changes
       |
       v
  proposal admission + validation commands
       |
       v  (fail → retry budget / blocked / repair task)
  enqueue MergeRequest
       |
       v
  merge queue (exclusive processing)
       |
       v
  merge attempt → success receipt / fail + requeue or repair
       |
       v
  optional merge-conflict repair / LLM merge resolver (still gated)
       |
       v
  checkpoint + cleanup of merged worktrees
```

### 13.3 Receipts and checkpoints

| Artifact | Meaning | Not a substitute for |
| --- | --- | --- |
| Merge queue complete/fail records | Queue lifecycle | Theorem proof or policy allow |
| Merge event log / resolve attempt records | Idempotent conflict resolution history | Board checkbox alone |
| `MergeCheckpoint` | Durable progress for resume | Lease fencing token |
| Janitor receipts | Explicit block/deprioritize actions | Operator plan edits |
| Task validation command exit 0 | Gate evidence for *that* command set | Full product release authority |
| Profile G `TaskReceipt` / `ClaimResolution` | Content-addressed schedule completion (when used) | Automatic Git merge |

Receipts are **layer-labeled evidence** ([ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)).
A merge receipt does not upgrade into Profile C proof or Profile D policy
approval.

## 14. Namespace isolation

Namespaces prevent cross-program interference.

### 14.1 Path layout

`wrapper_utils.agent_supervisor_namespace_paths` (accelerate) conventionally
yields:

| Field | Typical path under data root |
| --- | --- |
| `namespace` | e.g. `ipfs-datasets-documentation-v1`, `logic-intent-legal-gate-v1` |
| `namespace_root` | `data/<namespace>/` or `data/agent_supervisor/<program>/` |
| `state_dir` | `…/state` (status, pid, merge events, strategy) |
| `worktree_root` | `…/worktrees` |
| `discovery_dir` | discovery / gap scans |
| objective bundles / datasets / graph | program-specific subdirs |

Shard layouts (`shards/$SHARD/state`, `shards/$SHARD/worktrees`) further isolate
parallel supervisors reading the same locked board.

### 14.2 Isolation rules

- **One live board namespace** per program unless multi-track configs explicitly
  enumerate separate namespaces.
- Do not share state or worktree roots across IR-family, legal-gate, semantic-
  roundtrip, and documentation programs.
- Env prefixes and bootstrap callbacks are namespace-scoped so heartbeats and
  merge resolvers cannot attach to the wrong tree.
- Artifact namespaces for proposal routers keep LLM outputs out of foreign
  program dirs.

Crossing namespaces without an explicit bridge is a configuration defect;
daemons should fail closed rather than “helpfully” reuse another program’s
leases or merge queue.

## 15. Fail-closed execution and external leases

**Normative statements for this product:**

1. **Placement is advisory.** Scheduler ranking, neighborhood confidence,
   resource-class fit, and board priority suggest order only.
2. **Execution and leases remain external** to pure planning artifacts. A
   Profile G `ScheduleProposal` or markdown priority does not mint a lease.
3. **Missing validators, expired claims, authority/policy denial, and admission
   failures fail closed** — no side-effect grant, no silent complete, no merge.
4. **Feature unavailability** (accelerate submodule empty, provider offline)
   degrades the *runtime feature*; it must not be reported as successful task
   completion ([ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).

```text
  advisory placement  ──X──►  execution lease
  board checkbox done ──X──►  merge authority
  pytest green        ──X──►  path admission bypass
  heartbeat fresh     ──X──►  correctness proof
```

## 16. End-to-end control flow (documentation program example)

1. Operator freezes plan, objectives, and todo board (protected paths).
2. Namespace daemon starts with `state_dir` + `worktree_root` for
   `ipfs-datasets-documentation-v1` (or shard equivalent).
3. Parser loads tasks; selects a schedulable `IPFSDOC-*` with dependencies met
   and not strategy-blocked.
4. Daemon creates/uses an isolated worktree; writes checkpoint dir if configured.
5. Provider implements **only** declared outputs under edit policy.
6. Validation commands run; on failure, retry budget or **blocked** / repair.
7. On success, merge queue processes the branch; merge receipts/checkpoints
   update; board completion is daemon-mediated when policy allows.
8. Watchdog keeps lanes alive; heartbeats update status JSON.

## 17. Components (summary inventory)

| Component | Location (owner) | Responsibility |
| --- | --- | --- |
| Agent supervisor package | `ipfs_accelerate_py.agent_supervisor` | Canonical runtime |
| Todo daemon | `…/todo_daemon/*` | Parse, implement, commit helpers |
| Worktrees | `todo_daemon.worktrees` | Isolation + allowlists |
| Merge queue / resolver | `merge_queue`, `merge_resolver` | Exclusive merge authority path |
| Watchdog | `supervisor_watchdog` | Outer liveness |
| Multi-supervisor | `multi_supervisor_runner` | Parallel tracks + heartbeats |
| Namespace paths | `wrapper_utils` | Isolation layout |
| Admissibility bridge | accelerate bridge + datasets auth | Fail-closed pre-invocation |
| Profile G | `ipfs_datasets_py.logic.profile_g` | Planning/risk/evidence CIDs |
| Architecture docs | `docs/architecture/runtime/*` | This contract |

## 18. Invariants

1. Accelerate owns supervisor **execution**; datasets owns **planning evidence**
   and domain gates — not interchangeable.
2. Task selection never requires inventing missing metadata.
3. Worktree edits outside allowlists cannot merge.
4. Validation gate failure blocks merge authority.
5. **Blocked** and retry budgets are honest failure states.
6. Heartbeat/watchdog restore processes, not truth claims.
7. Namespaces do not share state or leases.
8. Placement is advisory; **execution/leases remain external and fail closed**.

## 19. Failure modes

| Failure | Expected behavior |
| --- | --- |
| Accelerate submodule empty | Supervisor feature unavailable; do not fake completion |
| Invalid board metadata | Task **blocked** or unselectable |
| Provider touches protected path | Admission reject; fail closed |
| Validation command non-zero | Retry / repair / block — no merge |
| Merge conflict | Queue fail + resolver/repair path; not silent force |
| Stale heartbeat | Watchdog marks lane stale; restart with backoff |
| Namespace collision | Configuration error; isolate roots before continuing |
| Auth bridge abstain/reject | No delegate call; no lease |

## 20. Extension guidance

- New programs: allocate a **new namespace**, state root, worktree root, and
  board prefix; copy multi-supervisor track specs rather than sharing dirs.
- New bridges: keep accelerate imports free of optional heavy provers; inject
  datasets auth surfaces lazily.
- New docs: put runtime leaves under `docs/architecture/runtime/`; do not fork
  a second supervisor design into `ipfs_datasets_py`.
- Never document board text as sufficient for production side effects.

## 21. Validation and verification

Focused checks for this guide’s tree presence and keyword coverage:

```bash
test -s docs/architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md
rg -n 'worktree|heartbeat|merge|blocked|Goal|TaskSpec|fail closed' \
  docs/architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md
```

When accelerate is checked out, deeper verification may include importing
`ipfs_accelerate_py.agent_supervisor` and running
`test/api/test_agent_supervisor_*.py` without enabling heavy prover stacks.

## 22. Related documents

- [PROFILE_G_PLANNING_AND_EVIDENCE.md](PROFILE_G_PLANNING_AND_EVIDENCE.md) —
  DAG-JSON/CID Goal/TaskSpec/risk evidence; advisory placement.
- [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) — accelerate/kit
  ownership.
- [docs/profile_g_datasets_provider.md](../../profile_g_datasets_provider.md) —
  package-import Profile G summary.
- [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) /
  [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) — authority layers
  and fail-closed trust.
- Program plans under `docs/implementation/plans/` (protected operator inputs;
  not task outputs).
