# Implementation agent guide

| Field | Value |
| --- | --- |
| Interface | `ImplementationAgentGuide@1` |
| Task | `IPFSDOC-073` |
| Status | `canonical` |
| Owner | developer-docs / agent-enablement |
| Source of truth | Live architecture leaves under `docs/architecture/`; [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md); [AGENT_SUPERVISOR_AND_TASKBOARDS.md](../architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md); ADRs 002–005; sibling [REPOSITORY_MAP.md](REPOSITORY_MAP.md), [EXTENSION_RECIPES.md](EXTENSION_RECIPES.md), [TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md); package import and packaging surfaces |
| Last verified | 2026-08-03 |
| Measured at (UTC) | `2026-08-03T08:25:31Z` |
| Commit | `e6f99607d031c1f5539ed921c538b8ca6fe82ba7` |
| Measurement Python | `Python 3.12.3` |
| Audience | agent, developer, operator, maintainer |
| Related | [TROUBLESHOOTING.md](TROUBLESHOOTING.md), [HANDOFF_CHECKLIST.md](HANDOFF_CHECKLIST.md), [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md), [ADR-003-LAYERED-AUTHORITY.md](../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004-FAIL-CLOSED-DEGRADATION.md](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Review cadence | when supervisor edit policy, protected path lists, or core identity/authority invariants change |

## 1. Purpose

This page is the **decision-rich contract** for implementation agents (and humans
running the same workflows). It defines:

1. **Minimum context** and a **safe exploration order** before edits.
2. **Protected and hot files** that must not be casually rewritten.
3. **Hard invariants** for identity, authority, optional dependencies, and
   security.
4. How to distinguish **current** behavior from **desired** behavior.
5. How to classify **blockers**, recover safely, report **uncertainty**, and
   produce honest **handoffs** with **evidence**.

Companions:

| Page | Owns |
| --- | --- |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Symptom → diagnosis for import, provider, prover, MCP, worktree, and merge failures |
| [HANDOFF_CHECKLIST.md](HANDOFF_CHECKLIST.md) | Templates for success, partial, unavailable, product-defect, and blocked handoffs |
| [TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md) | Evidence classes and proportional gates |
| [REPOSITORY_MAP.md](REPOSITORY_MAP.md) | Layout, ownership, hot files inventory |
| [EXTENSION_RECIPES.md](EXTENSION_RECIPES.md) | How to extend processors, backends, MCP, logic, policy, docs |

### Authority

When this guide disagrees with session summaries, completion reports, or model
memory, prefer:

1. Live tests and implementation under `ipfs_datasets_py/` and `tests/`
2. Packaging and config (`pyproject.toml`, `pytest.ini`, env contracts)
3. Accepted ADRs and architecture leaves
4. This guide and its siblings under `docs/developer_guides/`
5. Historical plans and reports (lowest authority for product claims)

Program **intent** lives in protected plan inputs (read-only). **Product truth**
still follows [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md).

---

## 2. Absolute agent rules (must not)

Agents **must not**:

| Rule | Why |
| --- | --- |
| **Weaken the task** | Narrowing acceptance criteria, skipping declared outputs, or inventing a smaller “done” definition to hide incomplete work is a contract violation. |
| **Rewrite queue / board status to hide failure** | Marking tasks complete, clearing `blocked`, or editing protected todo/objectives/plan files to look successful is forbidden. Only the operator/daemon owns board metadata and merge authority. |
| **Edit protected paths** | Operator-protected plan inputs and any path outside the task allowlist are read-only. Admission is fail-closed. |
| **Invent success from partial evidence** | Green unit tests, heartbeat freshness, placement rank, or discovery of a module **must not** be promoted to proof, policy allow, merge, or release readiness. |
| **Bypass trust for convenience** | Skipping admissibility, policy, identity checks, or fail-closed defaults “to make the demo work” is a security defect. |
| **Eagerly import optional stacks** | Hermetic package import and lazy optional capabilities are invariants ([ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)). |
| **Duplicate registries or public exports casually** | One registry per concern; new public symbols need deliberate export and tests ([ADR-005](../architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md)). |
| **Change production code to make stale docs true** | Doc and agent tasks record **product defects**; they do not silently “fix” behavior unless the task explicitly owns the code path. |
| **Revert unrelated local changes** | Leave sibling worktree or concurrent edits alone. |
| **Fill missing gates with silence** | If a gate is **unavailable** or deferred, say so with reason—do not omit it so the report looks clean. |

Agents **must**:

- Implement **every** declared output without stubs or placeholders when the
  task is schedulable and dependencies are available.
- Run listed validation commands when practical and record exact receipts.
- Preserve identity, authority layering, optional-dependency, and security
  invariants listed below.
- Prefer existing repository patterns and nearest tests over inventing new
  frameworks.
- Report blockers with **evidence**, not with rewritten criteria.

---

## 3. Minimum context packet

Before the first edit, assemble at least this **minimum context**. Skip only
items the task packet already inlines completely.

### 3.1 Always read (task-scoped)

1. **Task packet / board row** — `task_id`, title, priority, `depends_on`,
   `expected_outputs` / allowed edit paths, validation commands, acceptance
   criteria, protected paths, resource class, checkpoint directory.
2. **Declared outputs** — exact file or directory trees in scope (admission is
   fail-closed for undeclared paths).
3. **Edit policy** — allowlist, protected paths, size budgets, operator
   directives.
4. **`git status` and recent diff in the worktree** — avoid stomping concurrent
   or leftover changes.
5. **Nearest owner architecture leaf** for the domain you will touch (see
   exploration order).

### 3.2 Usually read (first session on a domain)

| Concern | Start here |
| --- | --- |
| Where code lives | [REPOSITORY_MAP.md](REPOSITORY_MAP.md) |
| Who owns the change | [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md) |
| Import / optional deps | [DEPENDENCY_AND_INITIALIZATION.md](../architecture/DEPENDENCY_AND_INITIALIZATION.md) |
| Entry points / processes | [RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md) |
| Cross-repo / submodules | [INTEGRATION_BOUNDARIES.md](../architecture/INTEGRATION_BOUNDARIES.md) |
| Supervisor / worktrees / merge | [AGENT_SUPERVISOR_AND_TASKBOARDS.md](../architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md) |
| Authority ranks / claim kinds | [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) |
| Fail-closed outcomes | [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Evidence selection | [TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md) |
| Extension workflow | [EXTENSION_RECIPES.md](EXTENSION_RECIPES.md) |

### 3.3 Read only when the change touches them

| Touch | Read |
| --- | --- |
| MCP tools / server | `docs/architecture/mcp/*`, package MCP ADRs under `ipfs_datasets_py/mcp_server/docs/adr/` |
| Logic / IR / provers | `docs/architecture/logic/*`, proof attestation guide |
| Wallet / privacy / auth | [WALLET_TRUST_AND_PRIVACY.md](../architecture/WALLET_TRUST_AND_PRIVACY.md) |
| Profile G planning | [PROFILE_G_PLANNING_AND_EVIDENCE.md](../architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md) |
| Docs placement / lifecycle | [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md), information architecture |
| Packaging / extras | `pyproject.toml` `[project.optional-dependencies]` |

### 3.4 Do not load by default

- Entire multi-thousand-file test suite inventory
- `docs/archive/**` completion reports as product authority
- Full historical session summaries
- Every root `docs/*.md` status report
- Generated stubs and Sphinx/MkDocs build trees as design truth

---

## 4. Safe exploration order

Follow this order unless the task packet is self-contained and outputs are pure
docs with no domain ambiguity.

```text
1. Task packet + allowlist + protected paths + validation commands
2. git status / worktree cleanliness / checkpoint dir (if resumable)
3. REPOSITORY_MAP + DOMAIN_MAP → owner tree
4. Owner architecture leaf + relevant ADR(s)
5. Canonical implementation module(s) and registry entry points
6. Nearest tests (REPOSITORY_MAP §7 / TESTING_AND_EVIDENCE tables)
7. Optional: packaging, fixtures, sibling docs already in the same bundle
8. Only then: historical docs or plans for intent (never over tests/code)
9. Edit only allowlisted paths
10. Validate → handoff with evidence
```

### 4.1 Checkpoint reuse (resumable work)

If the task declares a checkpoint directory (or
`$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR`):

1. **Inspect** existing checkpoints before rerunning completed steps.
2. **Reuse** valid coordinate / partial artifacts when still consistent with
   the current tree and allowlist.
3. **Write** new checkpoints **atomically** (temp file + rename).
4. Do **not** treat a checkpoint as merge authority or board completion.

### 4.2 Breadth discipline

- Prefer **depth in the owning domain** over scanning unrelated domains.
- Prefer **nearest unit path** over full-tree pytest as the first gate
  ([TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md)).
- Prefer **compact recipes/generators** over bulk golden dumps that re-emit full
  envelopes per case.

---

## 5. Protected paths and hot files

### 5.1 Operator-protected program inputs (never edit)

Workers may **read** these as program intent. They **must not** create, modify,
rename, delete, replace, or regenerate them—even to “fix” status or authority:

- `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH_PLAN_2026_08_03.md`
- `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH.objectives.md`
- `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH.todo.md`

Additional protected paths may appear in the active task packet; treat the
packet list as authoritative for that attempt.

### 5.2 Task allowlist (only edit these)

Admission is **fail-closed**:

- Declared outputs may be **files or directory trees**.
- Descendants of a directory output are in scope.
- Undeclared paths outside those trees are **not** in scope.
- Proposal size budgets (patch / provider output / single file) apply
  **independently** of pytest green.
- Generated artifacts (`site/`, build trees) and shared dependency paths are
  left alone unless the task explicitly owns them.

### 5.3 Hot / shared files (touch carefully)

Coordinate with architecture and nearest tests before changing these. Many
paths import or configure through them ([REPOSITORY_MAP.md](REPOSITORY_MAP.md)
§12):

| File | Risk if careless |
| --- | --- |
| `ipfs_datasets_py/__init__.py` | Breaks hermetic import, `initialize()`, public exports |
| `ipfs_datasets_py/ipfs_datasets.py` | Large shared dataset API surface |
| `ipfs_datasets_py/router_deps.py` and `*_router.py` | Process-wide backend selection |
| `dependency_catalog.py` / `lazy_dependencies.py` / `auto_installer.py` | Optional dependency resolution and install policy |
| `logic/submodule_registry.py` | Cross-logic family authority |
| `mcp_server/server.py`, `__main__.py` | MCP process entry |
| `mcp_server/tools/tool_registration.py`, `tool_wrapper.py` | Shared tool registration |
| `pyproject.toml` / `setup.py` | Packaging, extras, console scripts |
| `pytest.ini`, `tests/conftest.py`, root `conftest.py` | Discovery and shared fixtures |
| `requirements*.txt`, `mkdocs.yml`, `config/*`, `.gitmodules` | Install matrices, docs nav, runtime samples, submodules |

**Rule:** if the task does not list a hot file in its allowlist, do not “drive-by”
edit it to fix an adjacent symptom—file a **product defect** or blocker instead.

---

## 6. Hard invariants

These are **fail-closed product policy**. Green tests on a narrow case do not
authorize violating them.

### 6.1 Identity invariants

| Invariant | Meaning |
| --- | --- |
| Content identity is explicit | Digests, CIDs, and schema-bound envelopes are integrity facts—not optional decoration. Mismatch ⇒ reject / error. |
| Canonical path vs alias | Prefer domain-canonical modules over compat facades and star-import side effects. Document aliases; do not invent a second identity for the same artifact. |
| Registry uniqueness | One registry per concern (names, schemas, selection). Deprecation shims may re-export only ([ADR-005](../architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md)). |
| Package identity | Product package is `ipfs_datasets_py`, Python **3.12+** per packaging. |
| Do not fake empty submodules | Empty `ipfs_kit_py` / `ipfs_accelerate_py` checkouts are **availability** issues, not domain absence. |

### 6.2 Authority invariants ([ADR-003](../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md))

| Layer | Answers | Must not be treated as |
| --- | --- | --- |
| Discovery | Importable / registered / listed | Capability or authorization |
| Availability | Dep / backend present | Proof or allow |
| Capability | Probe or operation succeeded | Policy grant |
| Syntax validity | Parses | Semantic / policy validity |
| Semantic / policy validity | Meaning and admission hold | Proof |
| Proof | Prover / attestation under declared authority | Authorization / dispatch rights |
| Authorization | Side effects allowed | Automatic from tests or UI |
| Merge / lease (supervisor) | Daemon-gated integration | Board checkbox alone |

**Hard separations (must preserve):**

- Discovery ≠ capability ≠ authorization.
- Syntax ≠ semantics.
- Model output ≠ proof.
- Proof ≠ authorization.
- Monitoring / heartbeat ≠ correctness.
- UI visibility ≠ execution authority.
- Placement / priority ≠ execution lease.
- Pytest green ≠ path admission or merge authority.

### 6.3 Optional-dependency invariants ([ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md))

| Rule | Practice |
| --- | --- |
| Hermetic import | Package import stays light unless opt-in flags enable heavy stacks. |
| Lazy first use | Heavy stacks (FAISS, Qdrant, solvers, OCR, FastMCP, LLM, GPU) load on demand or behind env flags. |
| No eager optional imports at package top level | Guard optional imports; do not pull optional extras into default `import ipfs_datasets_py`. |
| Extras are not guarantees | Missing extra ⇒ feature **unavailable** or structured degrade—not silent success. |
| Native provers are separate | Python extras do not install every native solver binary; mark prover paths **unavailable** when binaries are missing. |
| Feature degrade vs trust | Soft-disable optional **features**; never soft-allow **trust** ([ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)). |

### 6.4 Security and trust invariants

| Rule | Practice |
| --- | --- |
| Fail closed on trust | Missing validator, UNKNOWN, NOT_MODELED (blocking), abstain, deny, integrity error ⇒ no allow / no PROVED / no guarded side effect. |
| No policy bypass | Do not skip dispatch pipeline, admissibility, or constraint checks “for convenience.” |
| Secrets | Never log, commit, or fixture real credentials, private keys, or production tokens. |
| Simulated attestation | Simulation / membership-only paths are non-authoritative; must not satisfy theorem authority alone. |
| Product defects stay labeled | Found security or contract bugs are reported as defects, not papered over in docs-only tasks. |
| Default deny for production side effects | Profiles that default off stay off unless configuration explicitly enables them. |

### 6.5 Supervisor and edit-policy invariants

| Rule | Practice |
| --- | --- |
| Allowlist only | Edits outside declared trees fail admission. |
| Protected paths never writable | Plan / objectives / todo status rewriting by workers is forbidden. |
| Daemon owns merge | Workers produce patches/commits in worktrees; they do not force-merge or rewrite strategy lists to hide failure. |
| Blocked is honest | `blocked`, retry budgets, and repair tasks are legitimate outcomes—not embarrassment to erase. |
| Namespace isolation | Do not share state/worktree roots across board namespaces. |
| Checkpoint honesty | Checkpoints resume work; they do not mint success. |

---

## 7. Current behavior vs desired behavior

Agents constantly mix three timelines. Keep them labeled.

| Label | Source of truth | Use for |
| --- | --- | --- |
| **Current (shipped)** | Implementation + tests + packaging at `git rev-parse HEAD` | What the product does **now** |
| **Desired (program / task)** | Protected plan, objectives, task acceptance, ADRs marked Accepted for future intent | What this change should deliver |
| **Historical** | `docs/archive/**`, old completion reports, session summaries | Context only—never override current |

### 7.1 Decision procedure when they disagree

1. State the claim precisely (import path, command, count, contract).
2. Collect sources by rank ([SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md)).
3. **Current** wins for “what happens if I run it today.”
4. **Desired** wins for “what this task must produce,” subject to allowlist and
   invariants.
5. If desired requires production code outside task ownership, record a
   **product defect** or **blocked** handoff—do not silently expand scope or
   weaken acceptance.
6. If docs claim current behavior that tests refute, update docs (when allowed)
   or file drift—do **not** change code solely to match stale prose unless the
   task owns that code.

### 7.2 Language agents must use

| Prefer | Avoid |
| --- | --- |
| “At commit `abc…`, tests show …” | “The system is production-complete” without scope |
| “Desired: recipe requires X; current: X missing → unavailable” | Quietly dropping X from acceptance |
| “Product defect: registry returns Y; docs said Z” | Editing protected boards to mark complete |
| “Validation deferred: no GPU host” | “All tests passed” when heavy tests were skipped |

---

## 8. Blocker classification

Use one primary class per failure. Secondary labels are allowed but do not
replace the primary.

| Class | When | Agent action |
| --- | --- | --- |
| **admission_blocked** | Path outside allowlist, protected path touch, size budget exceeded | Stop; do not force edit; report paths and policy |
| **dependency_unavailable** | Missing extra, native binary, submodule, network, GPU, LLM | Degrade feature or skip gate; label **unavailable**; do not invent pass |
| **environment_blocked** | Wrong Python, broken venv, missing tools (`rg`, git), disk/quota | Fix env if cheap and allowed; else hand off blocked with setup evidence |
| **validation_failed** | Declared validation command non-zero | Repair within allowlist/retry budget; else blocked with command receipt |
| **merge_conflict** | Daemon/worktree merge failure | Leave to merge/repair path; do not force-push or rewrite history |
| **authority_denied** | Admissibility/policy deny, abstain, expired claim | Fail closed; no side effects; report decision |
| **product_defect** | Current code/tests contradict required correct behavior | Document with paths/tests; do not “fix” via docs-only lies or board rewrite |
| **scope_conflict** | Correct fix needs files outside allowlist or protected inputs | Stop; request scope expansion or follow-on task—do not sneak edits |
| **upstream_blocked** | Unmet `depends_on`, missing sibling artifact | Do not fake dependency outputs; report missing inputs |
| **uncertainty** | Insufficient evidence to choose among safe options | Prefer fail-closed; ask via handoff; do not guess on trust paths |
| **retry_exhausted** | Retry budget consumed | Leave blocked/repair task; do not clear budgets |

**Honesty rule:** classifying a failure as `blocked` or `unavailable` with
evidence is **success of the agent protocol**. Hiding the same failure by
weakening the task or rewriting queue status is a **protocol defect**.

---

## 9. Safe recovery

### 9.1 Allowed recovery steps

1. Re-read allowlist and protected paths.
2. Revert **your** uncommitted out-of-scope edits (`git checkout -- <path>` only
   for paths you introduced outside policy—never discard unrelated work).
3. Re-run the **nearest** failing validation with exact command and cwd.
4. Fix within allowlist; re-validate.
5. Write an atomic checkpoint of durable intermediate state when the task is
   long-running.
6. If still failing: emit a **blocked / partial / product-defect** handoff
   ([HANDOFF_CHECKLIST.md](HANDOFF_CHECKLIST.md)).

### 9.2 Forbidden recovery steps

| Forbidden | Why |
| --- | --- |
| Edit protected plan / objectives / todo status | Operator authority only |
| Clear `blocked` / strategy lists to reselect work | Hides failure |
| Force-push, `reset --hard` on shared branches, or rewrite published history | Destructive; not agent authority |
| Expand allowlist yourself | Admission is external |
| Disable security checks or fail-open trust defaults | Invariant break |
| Mark complete without declared outputs and validation | False completion |
| Copy archive docs over canonical pages to “restore green narrative” | Authority inversion |

### 9.3 Dependency unavailable recovery

```text
missing optional stack
  → confirm feature vs trust path
  → feature: structured degrade / skip with unavailable receipt
  → trust: fail closed (no allow / no PROVED)
  → document exact missing package/binary/env
  → do not install unrelated heavy stacks “just in case”
```

---

## 10. Uncertainty reporting

When evidence is incomplete, say so **explicitly**. Uncertainty is a first-class
handoff field, not a footnote.

| Situation | Report |
| --- | --- |
| Gate not run | `unavailable` or `deferred` + reason + what would unlock it |
| Ambiguous owner tree | Candidates + which map/ADR was consulted + default fail-closed choice |
| Docs vs code conflict | Both citations; current wins for behavior; defect or drift entry for desired |
| Flaky or environment-dependent test | Exact command, seed/env if known, pass/fail counts—not “sometimes green so ignore” |
| Model-suggested API not found in tree | “Unverified suggestion”; search results; do not invent modules |

**Must not:** convert uncertainty into silent omission, invented counts, or a
stronger evidence class than was established
([TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md) §4).

---

## 11. Evidence requirements for handoffs

Every terminal handoff (success, partial, blocked, unavailable, product defect)
must include:

1. **Task id** and declared outputs status (each: written / not written / out of
   scope).
2. **Tree identity** — `git rev-parse HEAD` (and dirty summary if any).
3. **Exact validation commands**, cwd (repo root unless stated), exit codes.
4. **Evidence class labels** — test / metrics / solver candidate / proof /
   policy / runtime / release (do not promote).
5. **Negative or unavailable paths** — at least one, or why none applies.
6. **Invariants touched** — identity, authority, optional-deps, security, edit
   policy (pass / not exercised / risk).
7. **Blocker class** if not full success.
8. **Follow-ups** — concrete next task or operator action (not vague “more work”).

Full templates: [HANDOFF_CHECKLIST.md](HANDOFF_CHECKLIST.md).

---

## 12. Common failure families (index)

Detailed diagnosis lives in [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Agents
should recognize these families early:

| Family | Typical signals |
| --- | --- |
| **Import / packaging** | `ModuleNotFoundError`, wrong Python, dual `setup.py`/`pyproject` drift, hermetic import pulling heavy deps |
| **Provider / LLM** | Empty responses, over-budget proposals, path-violating patches, offline provider |
| **Prover / formal** | Missing Z3/CVC5 binary, UNKNOWN timeout, candidate treated as proof |
| **MCP** | Tool not registered, double registration, server import side effects, auth skip |
| **Worktree / allowlist** | Dirty disallowed paths, `..` escapes, edits outside declared trees |
| **Merge / daemon** | Validation gate fail, merge conflict, stale heartbeat, namespace collision |

---

## 13. Success criteria for agent conduct

An implementation attempt is **protocol-successful** when:

- All declared outputs exist and meet acceptance **or** an honest non-success
  handoff explains blockers with evidence;
- No protected paths were modified;
- No undeclared paths were modified (or they were reverted before handoff);
- Validation commands were run when practical and receipts recorded;
- Invariants in §6 were preserved;
- Task criteria were not weakened and board status was not rewritten to hide
  failure.

An attempt that “looks green” by deleting acceptance criteria, marking the board
complete, or skipping unavailable gates without labeling them is a **protocol
failure** even if some files were written.

---

## 14. Validation for this guide

```bash
test -s docs/developer_guides/FOR_AGENTS.md \
  && test -s docs/developer_guides/TROUBLESHOOTING.md \
  && test -s docs/developer_guides/HANDOFF_CHECKLIST.md \
  && rg -n 'must not|blocked|unavailable|evidence|handoff' docs/developer_guides/FOR_AGENTS.md
```

---

## 15. Related documents

- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — diagnostics and recovery trees
- [HANDOFF_CHECKLIST.md](HANDOFF_CHECKLIST.md) — handoff templates
- [REPOSITORY_MAP.md](REPOSITORY_MAP.md) — layout and hot files
- [EXTENSION_RECIPES.md](EXTENSION_RECIPES.md) — extension workflows
- [TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md) — gates and evidence classes
- [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md) — docs IA contract
- [AGENT_SUPERVISOR_AND_TASKBOARDS.md](../architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md)
- [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md)
- [ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md),
  [ADR-003](../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md),
  [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md),
  [ADR-005](../architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md)

---

## 16. Non-goals

- Replacing the agent supervisor implementation in `ipfs_accelerate_py`.
- Granting execution leases, merge authority, or board write access to workers.
- Exhaustive per-tool MCP or prover catalogs (see domain leaves).
- Promising that full-tree pytest is the first local gate for every change.
- Editing protected documentation-refresh plan inputs.

---

## 17. Change log (this page)

| Date (UTC) | Change |
| --- | --- |
| 2026-08-03 | Initial `ImplementationAgentGuide@1` for IPFSDOC-073 at commit `e6f99607d`. |
