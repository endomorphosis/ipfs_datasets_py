# Proof Tactician Migration Guide

**Interface:** `FormalVerificationTacticianDocumentation@1`  
**Compatibility baseline:** `LogicAPICompatibility@1`  
**Stable verification API:** `LogicVerificationAPI@1`  
**Goal tactician API:** `GoalTacticianAPI@1`  
**CLI/MCP parity:** `GoalTacticianCLIMCP@1`

This guide migrates consumers from legacy logic, legal, and ad-hoc proof helpers
to the goal-directed formal verification tactician without breaking reviewed
public names. Product guide:
`docs/formal_verification_tactician.md`. Operations:
`docs/operations/formal_verification_tactician_runbook.md`.

---

## 1. Migration principles

1. **Additive first.** New goal-tactician operations are additive; legacy
   `logic.api`, family modules, CLI, and MCP tools remain available.
2. **Authority never upgrades** when routing through a new surface. Caches,
   advisors, monitors, and attestations preserve prior authority only.
3. **Compatibility aliases are documented**, not silent semantic merges.
4. **Legal evidence routing stays separate** from formal proof planning.
5. **Implementation completeness ≠ deployment certification.** Migrating code
   does not certify toolchains on every host.
6. **Unsupported tools stay disclosed** as `unavailable` / `unsupported`.

---

## 2. Surface map (legacy → current)

| Legacy / existing surface | Current recommended surface | Notes |
| --- | --- | --- |
| `ipfs_datasets_py.logic.api` | Keep for v1 families; use `logic.verification_api` for software-verification + goal tactician | v1 import order frozen in `logic_api_v1_compatibility.md` |
| Family CLI (`convert-fol`, `convert-deontic`, …) | Unchanged | Goal commands use `goal-*` prefix |
| MCP `logic_tools` | Unchanged for v1; goal tools use `goal_tactician_*` | Transport success ≠ proof success |
| Ad-hoc “prove this string” helpers | `check` / `run_portfolio` with explicit bounds and assumptions | Require property + authority inspection |
| LegalIR / legal constraint helpers | `legal_constraint_adapter` (supervisor) or legal IR paths | **Not** `formalize_goal` / `plan_proof` |
| Injected counterexample fixtures | `replay_counterexample` + generation pipelines | Fixtures are not live authority |
| Simulated ZKP as “proved” | `attest_receipt` after a trusted receipt | Attestation does not raise proof class |
| Supervisor private modules imported from datasets clients | Public `GoalTacticianAPI` only | Supervisor-only controls rejected |

---

## 3. Compatibility aliases

### 3.1 Python packages

| Alias / stable name | Resolves to | Migration action |
| --- | --- | --- |
| `ipfs_datasets_py.logic.api` | Frozen v1 exports | Keep for FOL/deontic/modal/CEC/TDFOL/FLogic clients |
| `ipfs_datasets_py.logic.verification_api` | `LogicVerificationAPI` + goal tactician ops | Prefer for new software-verification work |
| `logic.tools` (deprecated) | Compatibility shim | Plan removal only under a versioned break; do not use in new code |
| Module functions `check`, `advise`, `formalize_goal`, … | Module-level facades over `get_verification_api()` | Preferred for scripts and tests |

### 3.2 Goal tactician channel aliases

| Operation | CLI alias | MCP tool alias |
| --- | --- | --- |
| `formalize_goal` | `goal-formalize` | `goal_tactician_formalize_goal` |
| `compare_interpretations` | `goal-compare-interpretations` | `goal_tactician_compare_interpretations` |
| `discover_missing_proofs` | `goal-discover-missing-proofs` | `goal_tactician_discover_missing_proofs` |
| `plan_proof` | `goal-plan-proof` | `goal_tactician_plan_proof` |
| `validate_proof_candidate` | `goal-validate-candidate` | `goal_tactician_validate_proof_candidate` |
| `execute_proof_plan` | `goal-execute-plan` | `goal_tactician_execute_proof_plan` |
| `proof_status` | `goal-proof-status` | `goal_tactician_proof_status` |
| `minimize_counterexample` | `goal-minimize-counterexample` | `goal_tactician_minimize_counterexample` |
| `explain_counterexample_causal` | `goal-explain-counterexample` | `goal_tactician_explain_counterexample_causal` |
| `replay_counterexample` | `goal-replay-counterexample` | `goal_tactician_replay_counterexample` |
| `list_goal_tactician_operations` | `goal-list-operations` | `goal_tactician_list_operations` |

`GOAL_TACTICIAN_OPERATIONS` is intentionally **not** merged into legacy
`STABLE_OPERATIONS` so LogicVerificationMCP legacy mappings stay intact.

### 3.3 Result vocabulary aliases

| Historical wording | Current interpretation |
| --- | --- |
| “Verified” (ambiguous) | Read typed `authority` + `status`; never collapse |
| “Proved” from optional tool missing | Must be `unavailable` / non-success, not soft prove |
| Cache hit “success” | Authority of the **cached** receipt only |
| Monitor “ok” | `monitor` authority, not theorem |
| Legal “permitted” | Constraint / applicability — not formal software proof |
| Advisor “proof” | Proposal / candidate only |
| ZKP “proved” | Attestation binding unless a separate kernel receipt exists |

---

## 4. Distinctions preserved during migration

Migrating clients must keep these axes explicit (same contract as the product
guide):

| Distinction | Incorrect migration | Correct migration |
| --- | --- | --- |
| Legal evidence routing vs formal proof planning | Call `plan_proof` for LegalIR norms | Use legal constraint adapter / legal IR; formal plan only for software obligations |
| Proposals vs proofs | Treat `advise` / `formalize_goal` as done | Require independent validation + fresh check |
| Bounded checks vs theorem proof | Map SMT `sat`/`unsat` to theorem | Preserve `bounded` / `satisfiability` authority |
| Implementation completeness vs deployment certification | Ship because fixtures pass | Require readiness baseline + hermetic cert for production claims |
| Assumptions vs obligations | Drop empty assumptions field | Always list assumptions; open holes remain obligations |
| Failure/rollback states | Retry until silence looks green | Preserve `unavailable`, `unsupported`, `partial`, quarantine |

---

## 5. Step-by-step client migration

### 5.1 Scripts using only `logic.api`

1. Keep existing imports for family conversion and theorem boards.
2. Add:

```python
from ipfs_datasets_py.logic.verification_api import (
    check,
    formalize_goal,
    list_goal_tactician_operations,
)
```

3. For new software properties, call `check` / goal ops instead of inventing
   parallel prover wrappers.
4. Inspect `response.authority` on every success path.

### 5.2 MCP integrations

1. Continue advertising legacy tools from the v1 manifest.
2. Add `goal_tactician_*` tools from `goal_tactician_tool_schemas()` /
   `GOAL_TACTICIAN_TOOL_NAMES`.
3. Do not map tool HTTP 200 to theorem success.
4. Reject payloads that include supervisor-only control keys.

### 5.3 CLI integrations

1. Retain existing `ipfs-datasets logic` family subcommands.
2. Add `goal-*` commands mapped by `GOAL_TACTICIAN_CLI_TO_OPERATION`.
3. Prefer `--json` envelopes that include `status` and `authority`.

### 5.4 Counterexample consumers

1. Stop treating hand-injected witnesses as sole authority.
2. Prefer generation + `explain_counterexample` /
   `explain_counterexample_causal` + `replay_counterexample`.
3. Strip private fields before public logging.

### 5.5 Supervisor / orchestration callers

1. Prefer `GoalDirectedProofTactician` and
   `GoalTacticianSupervisorLifecycle` inside the accelerate package.
2. Datasets clients must not import private supervisor mutation paths.
3. Use public goal API for cross-package work; lifecycle remains supervisor-side.

---

## 6. Executable migration smoke tests

These snippets are intended to run in a developer checkout. Optional tools may
report non-success.

```python
"""Migration smoke: legacy discovery + new goal surface coexist."""

from ipfs_datasets_py.logic import api as logic_api_v1  # legacy stable surface
from ipfs_datasets_py.logic.verification_api import (
    GOAL_TACTICIAN_CLI_TO_OPERATION,
    GOAL_TACTICIAN_OPERATIONS,
    GOAL_TACTICIAN_TOOL_TO_OPERATION,
    LogicVerificationAPI,
    formalize_goal,
    list_goal_tactician_operations,
)

# 1) Legacy module still importable
assert logic_api_v1 is not None

# 2) New operations are additive and listed
ops = list_goal_tactician_operations()
assert ops.status.value == "declarative"
for name in GOAL_TACTICIAN_OPERATIONS:
    assert name in ops.result["operations"]

# 3) Channel aliases cover every operation (except list may be present on both)
assert set(GOAL_TACTICIAN_TOOL_TO_OPERATION.values()) <= set(GOAL_TACTICIAN_OPERATIONS)
assert set(GOAL_TACTICIAN_CLI_TO_OPERATION.values()) <= set(GOAL_TACTICIAN_OPERATIONS)

# 4) Formalize remains a proposal
resp = formalize_goal(
    {
        "prose": "No held lease after completion.",
        "source_binding": {"path": "migrated_module.py", "language": "python"},
        "bounds": {"timeout_seconds": 2},
    }
)
assert resp.result.get("admitted") is not True
assert resp.authority.value != "theorem"

# 5) Declarative provider listing does not install
providers = LogicVerificationAPI().list_providers()
assert providers.status.value == "declarative"
print("migration smoke ok", len(GOAL_TACTICIAN_OPERATIONS), providers.status)
```

```bash
# Documentation + contract validation
python scripts/docs/check_agent_supervisor_docs.py
python -m pytest test/api/test_formal_verification_tactician_docs.py -q
python -m pytest test/api/test_goal_tactician_cli_mcp_parity.py -q
```

---

## 7. Failure-mode migration checklist

When porting error handling:

| Legacy behavior to retire | Required behavior |
| --- | --- |
| Missing prover → empty success | `unavailable` with diagnostics |
| Timeout → retry until “works” without bounds | `partial` / control `timed_out`; explicit bound change |
| Advisor text → mark proved | Keep `advisory` / `candidate` |
| Drop assumptions on rewrite | Carry assumptions into every receipt |
| Collapse legal + software success | Separate lanes and authorities |
| Treat fixture-green as production-certified | Consult readiness baseline + certificates |

---

## 8. Deprecation policy

| Item | Status | Guidance |
| --- | --- | --- |
| `logic.api` v1 names | Supported | Frozen behavioral contract |
| `logic.tools` alias | Deprecated shim | Do not expand; migrate to `logic.api` or `verification_api` |
| Private datasets imports from supervisor | Unsupported for external clients | Use public API |
| Undocumented “prove” wrappers | Do not add | Use typed operations |
| Goal ops inside `STABLE_OPERATIONS` | Intentionally excluded | Use `GOAL_TACTICIAN_OPERATIONS` |

Breaking changes require a versioned interface bump (`@2`) and an update to this
migration document plus `logic_api_v1_compatibility.md` when v1 is affected.

---

## 9. Related evidence

| Artifact | Role |
| --- | --- |
| `ipfs_datasets_py/docs/logic/logic_api_v1_compatibility.md` | Frozen v1 compatibility |
| `ipfs_datasets_py/docs/logic/software_verification_rollout.md` | Property/provider stages |
| `docs/formal_verification_tactician.md` | Architecture and authority |
| `docs/operations/formal_verification_tactician_runbook.md` | Operations and rollback |
| `test/api/test_formal_verification_tactician_docs.py` | Documentation contract |
| `test/api/test_goal_tactician_cli_mcp_parity.py` | Channel alias parity |
