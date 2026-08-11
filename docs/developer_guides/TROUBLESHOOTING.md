# Agent and developer troubleshooting

| Field | Value |
| --- | --- |
| Interface | `AgentTroubleshootingGuide@1` |
| Task | `IPFSDOC-073` |
| Status | `canonical` |
| Owner | developer-docs / agent-enablement |
| Source of truth | Live package import/packaging surfaces; [DEPENDENCY_AND_INITIALIZATION.md](../architecture/DEPENDENCY_AND_INITIALIZATION.md); [AGENT_SUPERVISOR_AND_TASKBOARDS.md](../architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md); [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md); sibling [FOR_AGENTS.md](FOR_AGENTS.md), [TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md), [REPOSITORY_MAP.md](REPOSITORY_MAP.md) |
| Last verified | 2026-08-03 |
| Measured at (UTC) | `2026-08-03T08:25:31Z` |
| Commit | `e6f99607d031c1f5539ed921c538b8ca6fe82ba7` |
| Measurement Python | `Python 3.12.3` |
| Audience | agent, developer, operator |
| Related | [FOR_AGENTS.md](FOR_AGENTS.md), [HANDOFF_CHECKLIST.md](HANDOFF_CHECKLIST.md), [VALIDATION_RUNBOOK.md](../maintenance/VALIDATION_RUNBOOK.md), [INTEGRATION_BOUNDARIES.md](../architecture/INTEGRATION_BOUNDARIES.md) |
| Review cadence | when common failure modes, install extras, or supervisor admission policy change |

## 1. Purpose

This guide turns common failures into **actionable diagnosis**: what you see,
what it usually means, what to check next, how to recover **safely**, and how to
classify the outcome for handoff.

It pairs with:

- [FOR_AGENTS.md](FOR_AGENTS.md) — invariants, exploration order, blocker classes
- [HANDOFF_CHECKLIST.md](HANDOFF_CHECKLIST.md) — how to report the outcome
- [TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md) — which gate to run next

### Authority

Prefer live errors, exact commands, and packaging/config over historical “works
on my machine” reports. When a failure involves trust (authz, proof, identity),
recover **fail-closed**—never by disabling checks to force green.

---

## 2. How to use this guide

1. Match the **family** (import, provider, prover, MCP, worktree, merge, tests,
   docs).
2. Run the **minimum reproduction** for that family.
3. Apply **safe recovery** only (no protected-path edits, no board status rewrite).
4. Label the outcome: fixed / **blocked** / **unavailable** / product defect /
   uncertainty.
5. Attach **evidence** (command, exit code, tree id) to the handoff.

### Global safe-recovery checklist

| Do | Do not |
| --- | --- |
| Stay inside the task allowlist | Edit protected plan/objectives/todo files |
| Revert your out-of-scope dirty files | `git reset --hard` shared branches or discard unrelated work |
| Re-run the nearest validation command | Claim full suite green without running it |
| Label missing deps **unavailable** | Treat missing dep as pass or as proof |
| Fail closed on trust errors | Soft-allow when validators are missing |
| Report blockers with evidence | Weaken acceptance criteria to hide failure |

---

## 3. Decision tree (first five minutes)

```text
Can you run: python3 --version && git rev-parse HEAD && git status -sb ?
  no → environment_blocked (fix shell/cwd/git first)
  yes ↓

Is the failure about "file not allowed" / protected path / dirty outside allowlist?
  yes → §8 worktree / admission
  no ↓

Is it ModuleNotFoundError / ImportError / wrong package version?
  yes → §4 import / packaging
  no ↓

Is it MCP tool missing, server crash on import, or tool auth?
  yes → §7 MCP
  no ↓

Is it solver / Z3 / CVC5 / proof / UNKNOWN / timeout?
  yes → §6 prover / formal
  no ↓

Is it provider patch rejected, empty model output, or over-budget proposal?
  yes → §5 provider
  no ↓

Is it merge queue / validation gate / conflict / stale heartbeat?
  yes → §9 merge / daemon
  no ↓

Is it pytest failure / skip / collection error?
  yes → §10 tests / evidence
  no ↓

Is it docs validation / links / metadata?
  yes → §11 documentation
  no → §12 catch-all + uncertainty handoff
```

---

## 4. Import and packaging failures

### 4.1 Symptoms

- `ModuleNotFoundError: No module named 'ipfs_datasets_py'`
- `ImportError` for optional libraries (faiss, z3, easyocr, …)
- Import hangs or pulls heavy stacks unexpectedly
- CLI entry point not found
- Tests collect against wrong tree or Python

### 4.2 Minimum checks

```bash
python3 --version                    # expect 3.12+
which python3
python3 -c "import sys; print(sys.executable); print(sys.path[:5])"
python3 -c "import ipfs_datasets_py; print(ipfs_datasets_py.__file__)"
git rev-parse --show-toplevel
```

### 4.3 Diagnosis table

| Observation | Likely cause | Recovery |
| --- | --- | --- |
| Package not found | Not installed editable / wrong venv | `pip install -e .` in repo root (or project-standard env); recheck `sys.path` |
| Optional name missing | Extra not installed | Install only needed extra from `pyproject.toml`; or mark path **unavailable** |
| Import loads GPU/LLM/solvers immediately | Eager optional import regression | Treat as **product defect** if default import path; do not “fix” by requiring extras for hermetic import |
| `setup.py` vs `pyproject.toml` confusion | Dual packaging surfaces | Prefer `pyproject.toml` for declared extras/scripts; document drift—do not invent a third packaging source |
| Works in one shell only | Multiple Pythons / residual `PYTHONPATH` | Unset accidental `PYTHONPATH`; use one venv; record `sys.executable` in evidence |
| Submodule import missing | Empty `ipfs_kit_py` / `ipfs_accelerate_py` | Availability issue: degrade feature or mark supervisor feature **unavailable**—do not document as product domain absence |

### 4.4 Optional extras quick map

Install only what the change needs (`pip install 'ipfs_datasets_py[<extra>]'`).
Names are declared in `pyproject.toml` (see [REPOSITORY_MAP.md](REPOSITORY_MAP.md)
§13). Common ones: `logic`, `theorem-provers`, `vectors`, `knowledge_graphs`,
`file_conversion`, `multimedia`, `ocr`, `ipld`, `api`, `test`.

**Rule:** missing extra on a **feature** path → structured degrade or skip with
**unavailable** receipt. Missing dependency on a **trust** path → fail closed
(no allow / no PROVED).

### 4.5 Hermetic import / env flags

If CI or local hermetic mode is intended:

```bash
export IPFS_DATASETS_PY_MINIMAL_IMPORTS=1
export IPFS_DATASETS_AUTO_INSTALL=0
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0
python3 -c "import ipfs_datasets_py"
```

Unexpected network installs or prover downloads during import are defects
relative to [DEPENDENCY_AND_INITIALIZATION.md](../architecture/DEPENDENCY_AND_INITIALIZATION.md).

---

## 5. Provider and LLM proposal failures

Applies to supervisor/provider loops that return patches or full-file proposals
(implementation daemons, proposal routers).

### 5.1 Symptoms

- Empty or truncated model output
- Proposal rejected: path not allowed, protected path, size budget
- Patch does not apply; unified diff context mismatch
- Provider offline / rate limited / auth error
- “Tests green” claimed without running task validation commands

### 5.2 Diagnosis table

| Observation | Likely cause | Recovery |
| --- | --- | --- |
| Admission reject: undeclared path | Model edited outside allowlist | Revert illegal paths; re-prompt with explicit allowlist; **must not** expand allowlist yourself |
| Admission reject: protected path | Touch of plan/objectives/todo or packet-protected list | Revert immediately; never retry by rewriting board status |
| Size budget exceeded | Oversize patch or single file | Split change, remove bulk golden dumps, prefer compact recipes |
| Diff does not apply | Stale base / concurrent edit | Refresh worktree base; re-read files; avoid force strategies |
| Provider 401/403/timeout | Credentials or network **unavailable** | Label **unavailable**; offline work if task allows; do not invent code from memory presented as verified |
| Provider returns prose without files | Prompt/tooling mismatch | Request explicit file writes; do not mark outputs complete |
| Partial files written | Interrupted attempt | Complete remaining declared outputs or hand off **partial** with file list |

### 5.3 Safe recovery pattern

```text
1. git status -sb
2. Identify paths outside allowlist → restore them
3. Confirm protected paths untouched
4. Re-run task validation commands only
5. If still failing after retry budget → blocked handoff (validation_failed or admission_blocked)
```

---

## 6. Prover and formal-path failures

### 6.1 Symptoms

- `z3` / `cvc5` / pysmt not found
- Solver **UNKNOWN** / timeout
- Tests skipped for `theorem-provers` extra
- Candidate proof treated as production **PROVED**
- Portfolio skips all routes

### 6.2 Diagnosis table

| Observation | Likely cause | Classification | Recovery |
| --- | --- | --- | --- |
| Binary missing | Native solver not on `PATH` | **unavailable** (feature/checker) | Install via operator docs / `ipfs-datasets-install-provers` if task owns it; else skip with receipt—**must not** claim proof |
| Python extra missing | `theorem-provers` / `logic` not installed | **unavailable** | Install extra or mock at unit layer only |
| UNKNOWN / timeout | Resource bound, inconclusive | Non-success (**UNKNOWN**) | Report UNKNOWN; never map to PROVED or allow |
| SAT/UNSAT without independent verify | Solver **candidate** only | candidate evidence | Label candidate; do not promote to proof |
| Encoding incomplete / obligation absent | **NOT_MODELED** | Non-success for coverage | Fail closed for blocking claims |
| Simulated ZKP / membership-only | Non-authoritative path | not production proof | Keep labeled; do not use for theorem authority |

### 6.3 Authority reminder

| Outcome | Trust effect |
| --- | --- |
| **unavailable** | No run → no invented proof/allow |
| **UNKNOWN** | Ran but inconclusive → non-success |
| **NOT_MODELED** | Outside model → not “vacuously secure” |
| **denied** / abstain | No guarded side effects |
| Solver candidate | Intermediate only until independent verify under policy |

See [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) and
[TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md) §4.

---

## 7. MCP failures

### 7.1 Symptoms

- Tool name not found / not registered
- Double-registration errors
- Server fails on import (eager optional deps)
- Auth/admissibility skipped “to debug”
- MCP tests fail only with live network

### 7.2 Minimum checks

```bash
# Prefer offline unit/MCP tests first
python -m pytest tests/mcp/ -q --tb=no -x   # narrow further to nearest file when known
python3 -c "import ipfs_datasets_py.mcp_server" 2>&1 | head -50
```

### 7.3 Diagnosis table

| Observation | Likely cause | Recovery |
| --- | --- | --- |
| Tool missing from registry | Not registered on canonical registrar | Follow [EXTENSION_RECIPES.md](EXTENSION_RECIPES.md) MCP recipe; fix domain tool + registration—not a parallel inventory file as authority |
| Double registration | Duplicate register call or dual catalogs | Remove duplicate; keep one registry per concern |
| Import-time crash | Eager heavy import in tool module | Lazy-import optional stacks; product defect if hermetic import breaks |
| Unauthorized tool call succeeds | Policy bypass | **Security defect**—fail closed; do not document as feature |
| Network-marked tests skipped | Default pytest skips network | Expected offline; label **unavailable** unless `--run-network` / env provisioned |
| Compat/legacy tools differ | Dual surfaces | Prefer canonical tools path; document legacy as compat |

### 7.4 Hot MCP files

Touch only if allowlisted: `mcp_server/server.py`, `tools/tool_registration.py`,
`tools/tool_wrapper.py`. Prefer domain packages for business logic; MCP tools
stay thin wrappers.

---

## 8. Worktree, allowlist, and dirty-tree failures

### 8.1 Symptoms

- Admission: path not allowed / protected path
- Daemon reports disallowed dirty paths after provider run
- Edits under wrong worktree or wrong namespace
- `..` or absolute path escape attempts
- Unrelated local changes present at start

### 8.2 Minimum checks

```bash
git rev-parse --show-toplevel
git status -sb
git diff --stat
# Compare changed paths to task allowed_edit_paths / expected_outputs
```

### 8.3 Diagnosis table

| Observation | Likely cause | Recovery |
| --- | --- | --- |
| Dirty file outside allowlist | Over-broad edit or tooling side effect | Restore that path; keep only declared outputs |
| Protected plan/todo dirty | Severe policy violation | Restore protected files immediately; report incident in handoff; **must not** commit them |
| Wrong worktree | Multiple checkouts | Confirm cwd is the assigned workspace; do not edit sibling worktrees |
| Namespace path mix-up | Shared state across programs | Stop; isolate roots—configuration defect |
| Leftover unrelated changes | Concurrent human/agent work | Do not revert others’ work; scope your diff; report uncertainty if blocked |
| Checkpoint missing/corrupt | Interrupted resumable task | Rebuild from sources if needed; do not invent completion from partial checkpoint |

### 8.4 Admission budgets (typical)

Budgets are configured per daemon/task. Independent of pytest:

- Patch size cap
- Provider output size cap
- Single file size cap

Exceeding budgets → **admission_blocked**, not “merge anyway.”

---

## 9. Merge, validation gate, and daemon failures

### 9.1 Symptoms

- Validation commands exit non-zero → no merge
- Merge conflict in queue
- Stale heartbeat / lane restart
- Accelerate supervisor import missing
- Task stuck `blocked` with recorded reason

### 9.2 Diagnosis table

| Observation | Likely cause | Recovery |
| --- | --- | --- |
| Validation gate fail | Declared command failed | Fix within allowlist; re-run **exact** commands; after budget → **validation_failed** handoff |
| Merge conflict | Parallel branches touched same lines | Use daemon merge/repair path; do not force-push; do not delete others’ commits |
| Stale heartbeat | Process hung | Watchdog restarts process only—**must not** invent completed tasks |
| Empty accelerate submodule | Supervisor feature **unavailable** | Document unavailable; do not fake merge receipts |
| Auth bridge abstain/reject | Fail-closed pre-invocation | No side-effect delegate; report **authority_denied** |
| Blocked strategy list | Explicit skip | Do not clear strategy lists to hide failure; operator/repair task only |

### 9.3 Authority reminder

| Artifact | Proves | Does not prove |
| --- | --- | --- |
| Validation exit 0 | That command set passed | Full release / proof |
| Merge receipt | Daemon integrated admitted change | Theorem or policy approval |
| Heartbeat fresh | Process alive | Correctness |
| Board checkbox complete | Board metadata (if operator set) | Worker may not set this on protected boards |

Workers **must not** rewrite queue status to hide failure. Recovery is repair
tasks, operator strategy edits, or successful validation + daemon merge.

---

## 10. Test and evidence failures

### 10.1 Symptoms

- Assertion failures on nearest unit path
- Collection errors / import errors during pytest
- Unexpected skips for llm/network/heavy
- “Full suite” attempted as first gate and times out
- Confusion between skip, xfail, fail, and unavailable

### 10.2 Safe first gates

Prefer nearest path ([TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md)):

```bash
# Examples — replace with the nearest path for your change
python -m pytest path/to/test_file.py -q
python -m pytest tests/unit/<domain>/ -q
python -m pytest tests/mcp/test_specific.py -q
```

Do **not** start with blank `pytest` or full `tests/` as the primary local gate
for a focused change.

### 10.3 Diagnosis table

| Observation | Likely cause | Recovery |
| --- | --- | --- |
| Fail on nearest unit | Real regression or wrong fixture | Fix code/tests in allowlist; keep negative cases |
| Collection import error | Package/env issue | §4 first |
| Skipped llm/network/heavy | Default markers | Label **unavailable** unless flags/env provisioned |
| Pass unit, fail integration | Cross-domain contract | Add integration only if change spans it; do not claim integration from unit alone |
| Goldens huge / brittle | Bulk envelope dumps | Prefer compact recipes/generators |
| Evidence class overclaim | Handoff language | Downgrade claim to actual class (test ≠ proof) |

### 10.4 Negative and unavailable paths

Every non-trivial change should document at least one **negative** path
(rejected input, missing optional, deny policy) **or** state why none applies.
Skipped optional gates are **unavailable**, not silent passes.

---

## 11. Documentation task failures

### 11.1 Symptoms

- `test -s` fails (empty or missing file)
- `rg` keyword coverage missing
- Stale claims vs code
- Temptation to edit protected plans to “align status”
- Product bug found while writing docs

### 11.2 Recovery

| Issue | Action |
| --- | --- |
| Missing declared output | Create complete page—no stub placeholders |
| Keyword validation fail | Add substantive sections (not keyword stuffing alone) |
| Docs vs code conflict | Prefer code/tests for current behavior; record defect/drift |
| Product defect found | Handoff as **product_defect**; do not change production code unless task owns it |
| Urge to mark todo complete | **Forbidden** on protected boards—daemon/operator only |

Doc validation helpers may include
[VALIDATION_RUNBOOK.md](../maintenance/VALIDATION_RUNBOOK.md) and
`python docs/maintenance/check_docs.py` when present—use when the task cites them.

---

## 12. Catch-all: uncertainty and multi-cause failures

When multiple families apply:

1. Fix **environment** and **admission** first (otherwise evidence is noise).
2. Then **import**, then domain-specific (MCP/prover/provider).
3. Re-run the **task’s** validation commands last as the integration gate for
   the attempt.
4. If still ambiguous, hand off with:
   - hypotheses ranked,
   - commands already run,
   - what was **not** run (**unavailable**/**deferred**),
   - fail-closed choice taken.

**Must not** pick the hypothesis that makes the task look complete without
evidence.

---

## 13. Quick command kit

```bash
# Identity
date -u +%Y-%m-%dT%H:%M:%SZ
git rev-parse HEAD
git status -sb
python3 --version

# Hermetic import smoke
python3 -c "import ipfs_datasets_py; print('ok', ipfs_datasets_py.__file__)"

# Submodules (availability)
git submodule status

# Nearest tests (example)
python -m pytest tests/unit/ -q --collect-only -q 2>/dev/null | tail -5

# Agent guide bundle validation (IPFSDOC-073)
test -s docs/developer_guides/FOR_AGENTS.md \
  && test -s docs/developer_guides/TROUBLESHOOTING.md \
  && test -s docs/developer_guides/HANDOFF_CHECKLIST.md \
  && rg -n 'must not|blocked|unavailable|evidence|handoff' docs/developer_guides/FOR_AGENTS.md
```

---

## 14. Mapping symptoms → blocker class

| Symptom family | Primary class (FOR_AGENTS §8) |
| --- | --- |
| Allowlist / protected path | `admission_blocked` |
| Missing extra/binary/submodule/network | `dependency_unavailable` |
| Broken Python/git/tools | `environment_blocked` |
| Declared validation non-zero | `validation_failed` |
| Merge queue conflict | `merge_conflict` |
| Policy deny/abstain | `authority_denied` |
| Code wrong vs required behavior | `product_defect` |
| Fix needs out-of-scope files | `scope_conflict` |
| Unmet depends_on | `upstream_blocked` |
| Cannot decide safely | `uncertainty` |
| Retries used up | `retry_exhausted` |

---

## 15. Related documents

- [FOR_AGENTS.md](FOR_AGENTS.md) — invariants and blocker policy
- [HANDOFF_CHECKLIST.md](HANDOFF_CHECKLIST.md) — handoff templates
- [TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md) — gate selection
- [DEPENDENCY_AND_INITIALIZATION.md](../architecture/DEPENDENCY_AND_INITIALIZATION.md)
- [AGENT_SUPERVISOR_AND_TASKBOARDS.md](../architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md)
- [INTEGRATION_BOUNDARIES.md](../architecture/INTEGRATION_BOUNDARIES.md)
- [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)

---

## 16. Non-goals

- Full runbooks for every processor format or cloud backend.
- Replacing operator deploy troubleshooting under `docs/guides/operations/`.
- Authorizing fail-open recovery for trust failures.
- Editing protected documentation-refresh plan inputs.

---

## 17. Change log (this page)

| Date (UTC) | Change |
| --- | --- |
| 2026-08-03 | Initial `AgentTroubleshootingGuide@1` for IPFSDOC-073 at commit `e6f99607d`. |
