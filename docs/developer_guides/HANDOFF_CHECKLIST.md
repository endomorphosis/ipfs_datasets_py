# Agent handoff checklist

| Field | Value |
| --- | --- |
| Interface | `AgentHandoffContract@1` |
| Task | `IPFSDOC-073` |
| Status | `canonical` |
| Owner | developer-docs / agent-enablement |
| Source of truth | [FOR_AGENTS.md](FOR_AGENTS.md); [TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md); [AGENT_SUPERVISOR_AND_TASKBOARDS.md](../architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md); [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) |
| Last verified | 2026-08-03 |
| Measured at (UTC) | `2026-08-03T08:25:31Z` |
| Commit | `e6f99607d031c1f5539ed921c538b8ca6fe82ba7` |
| Measurement Python | `Python 3.12.3` |
| Audience | agent, developer, operator, maintainer |
| Related | [FOR_AGENTS.md](FOR_AGENTS.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md), [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md) |
| Review cadence | when handoff fields, evidence classes, or supervisor completion contracts change |

## 1. Purpose

This page is the **handoff contract**: what an implementation agent (or human
running the same workflow) must include when ending an attempt—whether the work
fully succeeded, partially landed, hit **unavailable** dependencies, found a
**product defect**, or is **blocked**.

Handoffs exist so the next agent, operator, or daemon can **resume without
guessing** and without hidden failures.

### Non-negotiable rules

Agents **must not**:

- Weaken task acceptance criteria to manufacture “success.”
- Rewrite queue / board / protected todo status to hide failure.
- Omit **unavailable** or deferred gates so the report looks clean.
- Promote evidence classes (e.g. unit tests → proof, heartbeat → merge).
- Claim merge or release authority from a local worktree alone.

Agents **must**:

- List every declared output and its status.
- Attach exact validation **evidence** (commands, exit codes, tree id).
- Classify non-success with a primary blocker class from
  [FOR_AGENTS.md](FOR_AGENTS.md) §8.
- Preserve fail-closed language for trust failures.

---

## 2. When to hand off

| Situation | Handoff type |
| --- | --- |
| All declared outputs done; validation green; invariants held | **Success** |
| Some outputs done; remainder blocked or deferred with evidence | **Partial** |
| Required dependency/tooling not present; work cannot complete gates | **Unavailable** |
| Current code/tests wrong relative to required correct behavior | **Product defect** |
| Cannot proceed without policy/scope/operator action | **Blocked** |
| Attempt crashed mid-flight with recoverable checkpoint | **Partial** (+ checkpoint pointer) |
| Retry budget exhausted | **Blocked** (`retry_exhausted`) |

Multiple types may combine (e.g. partial + product defect). Lead with the
**strictest** outcome that affects merge eligibility.

---

## 3. Universal checklist (every handoff)

Copy this block and fill every field. Use `n/a` only with a one-line reason.

```markdown
## Handoff — <TASK_ID> — <success|partial|unavailable|product_defect|blocked>

### Identity
- Task id:
- Title:
- Attempt / worktree:
- Tree (`git rev-parse HEAD`):
- Dirty summary (`git status -sb`): clean | <paths>
- Checkpoint dir (if any):
- Timestamp (UTC):

### Scope
- Declared outputs:
  - path → written | not_written | out_of_scope_reverted
- Allowed paths respected: yes | no (if no, list violations and reverts)
- Protected paths untouched: yes | no (if no, list and restore status)

### Outcome
- Primary result: success | partial | unavailable | product_defect | blocked
- Blocker class (if not success): admission_blocked | dependency_unavailable |
  environment_blocked | validation_failed | merge_conflict | authority_denied |
  product_defect | scope_conflict | upstream_blocked | uncertainty | retry_exhausted
- One-paragraph summary (current vs desired if they differ):

### Validation evidence
- Commands run (cwd = repo root unless noted):
  1. `...` → exit <code>
  2. `...` → exit <code>
- Commands not run (unavailable/deferred + reason):
- Evidence classes used: test | metrics | solver_candidate | proof | policy |
  runtime | release
- Negative path exercised or why none:

### Invariants
- Identity: pass | not_exercised | risk (<note>)
- Authority layering: pass | not_exercised | risk
- Optional dependencies: pass | not_exercised | risk | unavailable
- Security / fail-closed: pass | not_exercised | risk
- Edit policy / allowlist: pass | violated_and_reverted | violated

### Follow-ups
- Next concrete actions (operator / next task / repair kind):
- Files a human should review first:
- Do not: (anti-patterns for the next agent)
```

---

## 4. Success handoff

Use when **all** declared outputs exist, acceptance criteria are met **without
weakening**, validation commands exit 0 (or explicitly n/a with justification),
and no protected/allowlist violations remain.

### Extra fields

```markdown
### Success details
- Acceptance criteria mapping (criterion → how satisfied):
- Key paths changed (complete list):
- Invariants preserved (note any hot files touched and why):
- Residual risks / known limitations (honest; empty only if none):
- Merge readiness note: local validation only | awaiting daemon gate | n/a
```

### Success example (abbreviated)

```markdown
## Handoff — IPFSDOC-073 — success

### Identity
- Task id: IPFSDOC-073
- Title: Write agent invariants troubleshooting and handoff guides
- Tree: e6f99607d031c1f5539ed921c538b8ca6fe82ba7 (+ local doc writes)
- Dirty summary: docs/developer_guides/{FOR_AGENTS,TROUBLESHOOTING,HANDOFF_CHECKLIST}.md
- Timestamp (UTC): 2026-08-03T08:25:31Z

### Scope
- Declared outputs:
  - docs/developer_guides/FOR_AGENTS.md → written
  - docs/developer_guides/TROUBLESHOOTING.md → written
  - docs/developer_guides/HANDOFF_CHECKLIST.md → written
- Allowed paths respected: yes
- Protected paths untouched: yes

### Outcome
- Primary result: success
- Summary: Agent guide bundle documents minimum context, invariants, blockers,
  troubleshooting families, and handoff templates without editing protected plans.

### Validation evidence
- Commands:
  1. test -s …FOR_AGENTS.md && test -s …TROUBLESHOOTING.md && test -s …HANDOFF_CHECKLIST.md
     && rg -n 'must not|blocked|unavailable|evidence|handoff' …FOR_AGENTS.md → exit 0
- Commands not run: full pytest (doc-only task; not required)
- Evidence classes: test (shell validation only)
- Negative path: protected plan paths not modified; allowlist-only edit check

### Invariants
- Edit policy: pass
- Authority: pass (docs do not grant leases/merge)
- Optional deps: not_exercised
- Security: pass (fail-closed language preserved)

### Follow-ups
- Daemon merge after its validation gate
- Do not: mark IPFSDOC-073 complete in protected todo.md from the worker
```

---

## 5. Partial progress handoff

Use when some declared outputs are complete and valuable, but the attempt cannot
finish without further input, time, or dependencies—and the incomplete part is
**honestly** labeled.

### Extra fields

```markdown
### Partial details
- Completed outputs (paths + what they provide):
- Incomplete outputs (paths + what's missing):
- Safe to merge as-is?: no | yes_with_limitations (explain)
- Checkpoint / resume coordinates:
- Estimated remaining work:
- What the next agent should read first:
```

### Rules

- Do **not** describe partial work as full success.
- Do **not** delete incomplete acceptance criteria from the narrative.
- Leave incomplete files either absent, clearly stub-free incomplete **only if
  the task allows partial artifacts**, or complete sections with explicit
  “remaining” notes—never silent placeholders that look finished.
- Prefer committing only allowlisted complete files when partial merge is useful;
  otherwise keep incomplete work in the worktree and point the checkpoint.

### Partial example (abbreviated)

```markdown
## Handoff — EXAMPLE-012 — partial

### Outcome
- Primary result: partial
- Blocker class: dependency_unavailable
- Summary: MCP tool registration docs written; live FastMCP smoke not run
  (extra `api` + server not provisioned). Desired: full smoke. Current: offline
  unit path only.

### Partial details
- Completed: docs/.../MCP_TOOL_X.md sections 1–4
- Incomplete: section 5 runtime evidence table
- Checkpoint: $IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR/mcp-tool-x-outline.json
- Next: provision `api` extra, run declared smoke, fill section 5
```

---

## 6. Unavailable dependency handoff

Use when required tooling, extras, binaries, submodules, network, GPU, LLM, or
operator secrets are missing so gates cannot be completed.

### Extra fields

```markdown
### Unavailable details
- Missing dependency (name / extra / binary / submodule / network / GPU / LLM):
- Feature path vs trust path: feature | trust
- Degradation applied (if feature): <what callers see>
- Fail-closed applied (if trust): no allow / no PROVED / no side effect
- Exact probe commands and errors:
- What becomes possible once provisioned:
- What must not be claimed until then:
```

### Rules

| Path type | Correct labeling |
| --- | --- |
| Feature | **unavailable** or structured degrade; do not claim capability complete |
| Trust / proof / authz | Fail closed; **must not** invent allow or PROVED |
| Skipped pytest optional | **unavailable**, not pass |

### Unavailable example (abbreviated)

```markdown
## Handoff — EXAMPLE-044 — unavailable

### Outcome
- Primary result: unavailable
- Blocker class: dependency_unavailable
- Summary: theorem-prover integration tests not run — `cvc5` binary missing.
  Unit mocks green; proof evidence not established.

### Unavailable details
- Missing: cvc5 on PATH
- Path type: trust-adjacent (proof gate)
- Fail-closed: no PROVED claim; solver candidate section marked n/a
- Probe: `command -v cvc5` → exit 1
- Do not claim: production proof or release formal gate
```

---

## 7. Product defect handoff

Use when documentation or implementation work discovers that **current shipped
behavior** is wrong relative to tests, ADRs, or required safe behavior—and the
active task does **not** own fixing it (or cannot within allowlist).

### Extra fields

```markdown
### Product defect details
- Defect summary (one sentence):
- Expected (desired/correct) behavior:
- Actual (current) behavior:
- Evidence (file:line, test node id, command):
- Severity: blocker | high | medium | low
- Security/trust impact: none | integrity | authz | proof | privacy | other
- Allowlist can fix now?: yes | no
- If no: out-of-scope paths required:
- Suggested follow-up task title/outputs:
- Drift matrix / receipt path to update (if any):
```

### Rules

- Do **not** silently change production code on a docs-only allowlist.
- Do **not** rewrite docs to pretend the defect is intended unless evidence shows
  it is intended and documented as such.
- Do **not** mark the originating board task complete by editing protected
  status.
- Prefer citations to tests and implementation over narrative blame.

### Product defect example (abbreviated)

```markdown
## Handoff — EXAMPLE-070 — product_defect

### Outcome
- Primary result: product_defect
- Blocker class: product_defect
- Summary: Desired docs claim hermetic import; current
  `ipfs_datasets_py/some_module.py` imports optional stack at module top level.

### Product defect details
- Expected: lazy optional import per ADR-002
- Actual: top-level import of heavy dependency
- Evidence: `python -c "import ipfs_datasets_py"` pulls <module>; see file:line
- Severity: high
- Allowlist can fix now?: no (production module outside doc task outputs)
- Follow-up: code task to lazy-import + unit test for hermetic import
```

---

## 8. Blocked handoff

Use when progress requires operator action, scope expansion, merge repair,
authority decision, or retry budget reset—and continuing would violate policy.

### Extra fields

```markdown
### Blocked details
- Blocker class:
- What was tried (commands + outcomes):
- Why continuing is unsafe or forbidden:
- Unblock conditions (explicit, testable):
- Owner: operator | daemon | next_task | human_review
- Related strategy / retry / repair ids (if known):
```

### Common blocked patterns

| Pattern | Unblock condition |
| --- | --- |
| `admission_blocked` | Allowlist expansion or redesign within existing paths |
| `scope_conflict` | New task owning required paths |
| `authority_denied` | Valid allow decision / non-expired claim |
| `merge_conflict` | Daemon merge resolver / human conflict resolution |
| `upstream_blocked` | Dependency task outputs merged and visible |
| `retry_exhausted` | Budget reset or repair task |
| `uncertainty` on trust path | Human decision; fail closed until then |

### Blocked example (abbreviated)

```markdown
## Handoff — EXAMPLE-099 — blocked

### Outcome
- Primary result: blocked
- Blocker class: scope_conflict
- Summary: Fix requires `ipfs_datasets_py/__init__.py` but allowlist is
  docs-only. Stopping rather than drive-by edit of a hot file.

### Blocked details
- Tried: documented workaround; validation for docs paths green
- Unsafe to continue: would violate admission and hot-file policy
- Unblock: schedule code task owning __init__.py + hermetic import tests
- Owner: operator / planner
```

---

## 9. Evidence quality bar

| Good evidence | Insufficient |
| --- | --- |
| Exact command + cwd + exit code | “tests passed” |
| `git rev-parse HEAD` + dirty list | No tree identity |
| Named evidence class | Implied proof from unit tests |
| Explicit **unavailable** skips | Silent omission of heavy gates |
| File paths for defects | Vague “something wrong in logic” |
| Blocker class from FOR_AGENTS §8 | “it failed” |

Receipts are **layer-labeled**. A successful handoff at the implementation layer
does not upgrade into Profile C proof or Profile D policy approval
([ADR-003](../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md)).

---

## 10. Pre-handoff self audit

Run mentally or as a checklist before sending:

1. Did I implement every declared output **or** name each missing one?
2. Did I avoid protected paths and revert any accidental out-of-scope edits?
3. Did I run validation commands when practical and record exits?
4. Did I label unavailable/deferred gates?
5. Did I keep current vs desired language honest?
6. Did I avoid weakening acceptance criteria?
7. Did I avoid rewriting board/queue status?
8. Did I preserve identity, authority, optional-dep, and security invariants?
9. Can the next agent resume from this text alone + the worktree?
10. If trust was involved, did I fail closed?

If any answer is “no,” fix the handoff or the tree before claiming success.

---

## 11. Coordination with daemon and operators

| Actor | May do | Must not do (worker) |
| --- | --- | --- |
| Implementation agent | Edit allowlist, validate, hand off, write checkpoints | Merge authority, board status rewrite, protected plan edits |
| Daemon / supervisor | Admit proposals, run gates, merge, set strategy | Invent success without gates |
| Operator | Expand scope, reset budgets, edit protected inputs | Expect agents to mute failures |

When the board is operator-protected (e.g. documentation refresh todo),
**completion status is not the worker’s artifact**. The worker’s artifact is
declared outputs + handoff evidence; the daemon commits/merges after its gate.

---

## 12. Related documents

- [FOR_AGENTS.md](FOR_AGENTS.md) — full agent contract and blocker classes
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — diagnosis before handoff
- [TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md) — evidence classes
- [AGENT_SUPERVISOR_AND_TASKBOARDS.md](../architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md)
- [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md)

---

## 13. Validation for this guide

```bash
test -s docs/developer_guides/FOR_AGENTS.md \
  && test -s docs/developer_guides/TROUBLESHOOTING.md \
  && test -s docs/developer_guides/HANDOFF_CHECKLIST.md \
  && rg -n 'must not|blocked|unavailable|evidence|handoff' docs/developer_guides/FOR_AGENTS.md
```

---

## 14. Non-goals

- Replacing daemon-internal receipt schemas.
- Automated enforcement of markdown handoffs (this is the human/agent contract).
- Authorizing workers to mark protected board tasks complete.
- Exhaustive ticket templates for every external tracker.

---

## 15. Change log (this page)

| Date (UTC) | Change |
| --- | --- |
| 2026-08-03 | Initial `AgentHandoffContract@1` for IPFSDOC-073 at commit `e6f99607d`. |
