# Profile G planning, risk, and evidence

| Field | Value |
| --- | --- |
| Interface | `ProfileGDatasetProvider@1` |
| Task | `IPFSDOC-017` |
| Status | `canonical` |
| Owner | architecture; implementation owner `ipfs_datasets_py.logic.profile_g` |
| Source of truth | `ipfs_datasets_py/logic/profile_g.py`; package facade `ipfs_datasets_py/profile_g.py`; MCP service `ipfs_datasets_py/mcp_server/profile_g_service.py`; tests `tests/unit_tests/logic/test_profile_g.py`, `tests/mcp_server/test_profile_g_transport.py`; [docs/profile_g_datasets_provider.md](../../profile_g_datasets_provider.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, MCP integrator, agent |
| Related | [AGENT_SUPERVISOR_AND_TASKBOARDS.md](AGENT_SUPERVISOR_AND_TASKBOARDS.md), [DOMAIN_MAP.md](../DOMAIN_MAP.md), [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) |
| Review cadence | when Profile G schemas, risk algorithm, or MCP method surface change |

## 1. Purpose

This guide answers: what **MCP++ Profile G** (`mcp++/risk-scheduling` version
**1.0**) means in **this** repository — **canonical DAG-JSON / CID** identity,
**Goal / Subgoal / PlanBranch / PlanSelection / TaskSpec** planning, **risk**
models and evidence, neighborhood placement confidence, and schedule claim
artifacts — and how those relate to (but do not replace) the agent supervisor.

**Normative product rule:** *Planning and placement are advisory. Execution
leases and side-effect authority remain external and fail closed.* A valid
`PlanBranch`, ranked `ScheduleProposal`, or neighborhood attestation never
becomes an execution permit by itself.

## 2. Audience

- **Primary:** developers and agents integrating Profile G stores, validators,
  or MCP methods.
- **Secondary:** operators configuring durable SQLite paths and injected
  Profile C/D validators; supervisor authors consuming CIDs as planning input.

## 3. Scope and non-goals

### In scope

- Datasets-owned Profile G package-import provider and MCP service boundary.
- Canonical encoding (`canonical_profile_g_bytes`) and CIDv1 DAG-JSON/sha2-256
  (`profile_g_cid`).
- Artifact kinds: Goal through TaskReceipt (schemas and contextual links).
- `GoalPlanValidator` readiness rules for selection and actionable tasks.
- Integer-only `weighted-saturated-sum-v1` risk evaluation.
- Risk evidence store, classification/redaction, signed neighborhood material.
- Advisory placement vs external leases / claims / resolutions.
- Fail-closed behavior when authority/policy validators are missing.

### Non-goals

- Agent-supervisor worktree/merge loop details (see
  [AGENT_SUPERVISOR_AND_TASKBOARDS.md](AGENT_SUPERVISOR_AND_TASKBOARDS.md)).
- Profile C (authority) and Profile D (policy) full protocols — only injection
  points and fail-closed defaults.
- Transport framing beyond the datasets MCP service method list.
- Replacing Git taskboards with Profile G as the only backlog format.

## 4. Context

MCP++ Profile G standardizes **risk-aware scheduling artifacts** as content-
addressed JSON. This package implements the **datasets portion** (section 10
package-import provider): strict validation, CID generation, contextual goal
planning checks, risk scoring, durable evidence history, and neighborhood
attestation helpers.

The agent supervisor (accelerate) may *reference* these CIDs when coordinating
work, but the **canonical artifact logic lives here**. Conversely, Git merge
authority and markdown board selection live in accelerate — not in Profile G.

```text
  Goal ──► Subgoal ──► PlanBranch (advisory candidates)
                │            │
                │            ▼
                │      PlanSelection (requires Profile C/D when actionable)
                │            │
                └──────────► TaskSpec ──► risk assess ──► ScheduleProposal
                                                      │
                                      placement confidence (neighborhood)
                                                      │
                              external executor ◄──── claim / lease / resolve
                                   (fail closed if validators/lease missing)
```

## 5. Ownership and boundaries

| This package **owns** | Does **not** own |
| --- | --- |
| `logic.profile_g` schemas, canonicalization, CIDs, `GoalPlanValidator`, `RiskEvidenceStore`, risk evaluation | Agent-supervisor taskboard parse, worktrees, Git merge queue |
| MCP `ProfileGService` method dispatch and REST bindings | Profile C/D implementations (injected callables) |
| Ed25519 artifact signing helpers used for evidence/neighborhood | Execution host scheduling outside negotiated claim/lease APIs |
| Fail-closed defaults when validators absent | Silent allow for network mutations without authority/policy |

**Canonical import path:** `ipfs_datasets_py.logic.profile_g`  
**Public facade:** `ipfs_datasets_py.profile_g` (re-exports)  
**MCP:** `ipfs_datasets_py.mcp_server.profile_g_service.ProfileGService`

**Inbound:** library callers, MCP JSON-RPC/REST/native dispatch, tests.  
**Outbound:** optional cryptography for Ed25519; SQLite; injected Profile C/D
and record-policy filters; multiformats CID/multihash.

Capability string: `PROFILE_G_CAPABILITY = "mcp++/risk-scheduling"`.  
Version: `PROFILE_G_VERSION = "1.0"`.

## 6. Canonical DAG-JSON and CID identity

### 6.1 Canonical bytes

`canonical_profile_g_bytes(value)` produces deterministic UTF-8 JSON:

- Object keys sorted; separators compact (`","`, `":"`).
- `ensure_ascii=False`, `allow_nan=False`.
- **No floats** — floating point is non-canonical and rejected.
- Integers must lie in the JSON safe range
  (`±9_007_199_254_740_991`).
- Only JSON-representable types (null, bool, str, int, list, dict with string
  keys).

Any violation raises `ProfileGError` (`G_INVALID_ARTIFACT` or related codes).

### 6.2 CID computation

`profile_g_cid(value)`:

1. Canonicalize with `canonical_profile_g_bytes`.
2. Multihash **sha2-256**.
3. CIDv1, codec **dag-json**, multibase **base32** (canonical lowercase).

Linked fields that are CIDs are validated as canonical CIDv1/sha2-256 forms.
Mismatched declared CIDs vs recomputed content fail with `G_CID_MISMATCH`.

### 6.3 Artifact validation entry points

| API | Role |
| --- | --- |
| `validate_profile_g_artifact(kind, artifact, limits=…)` | Strict field/schema validation; returns canonical CID |
| `validate_artifact(artifact, limits=…)` | Kind detection + validation |
| `artifact_kind(artifact)` | Map schema to kind name |
| `validate_cid` / `validate_did` | Link and identity string checks |

Default size/depth limits (`DEFAULT_LIMITS`) bound artifact bytes, parents,
dependencies, evidence lists, neighbors, history depth, and lease duration
windows (`min_lease_ms` / `max_lease_ms`).

## 7. Planning artifacts: Goal → TaskSpec

Schemas are fixed field sets (see `_FIELDS` / `_SCHEMAS` in
`logic/profile_g.py`). Below is the architectural meaning, not a full JSON
schema dump.

### 7.1 Goal

A **Goal** binds an owner DID, objective CID, policy CID, parent goal CIDs, and
labels. Parent links must resolve to Goals without cycles (bounded by
`max_history_depth`).

### 7.2 Subgoal

A **Subgoal** belongs to exactly one `goal_cid`, optional parent subgoal,
objective CID, decomposition method/decomposer CIDs, and optional
`selection_cid`.

**Decomposition rule:** new Subgoals created in a decomposition batch must
remain **unselected** (`selection_cid is null`) until a later PlanSelection.

### 7.3 PlanBranch (advisory)

A **PlanBranch** proposes candidate inputs, task templates, evaluator CID,
score (millionths), and explanation CID for a subgoal.

**A PlanBranch is always advisory.** It is never treated as actionable work by
`GoalPlanValidator` until a matching **PlanSelection** exists and authority +
policy validators accept it.

### 7.4 PlanSelection

A **PlanSelection** chooses one `plan_branch_cid` for a `subgoal_cid` with
selector DID, `proof_cid`, `policy_decision_cid`, and reason CID.

Contextual checks:

- Branch’s subgoal must match selection’s subgoal.
- Subgoal must not already hold a **different** selection (`G_CLAIM_CONFLICT`).
- When decisions are checked, Profile C (`authority_validator`) and Profile D
  (`policy_validator`) must both return true — otherwise
  `G_AUTHORITY_DENIED` / `G_POLICY_DENIED`.

### 7.5 TaskSpec

A **TaskSpec** is the schedulable task description: subgoal, plan branch,
selection, interface/input CIDs, tool name, dependency task CIDs, idempotency
key, resource class, deadline, expected value, max attempts, execution mode.

`GoalPlanValidator.validate_task(..., require_actionable=True)` requires:

- Branch and selection agree with the task’s subgoal and each other.
- Selection’s Profile C/D decisions validate (when `require_actionable`).
- Dependencies exist as TaskSpecs; no self-dependency.

**TaskSpec acceptance is still not an execution lease.** It is a validated
planning artifact the scheduler may rank and propose.

### 7.6 Atomic decomposition

`validate_decomposition(artifacts, goal_cid)` stages Subgoal/PlanBranch
members only, checks linkage within the staged set + resolver, and returns
CIDs **without publishing** — atomic all-or-nothing validation.

## 8. Risk model, evidence, and assessment

### 8.1 RiskModel

Integer-only model with:

- `factor_names`, per-factor `weight_millionths` and `saturation_millionths`
- `algorithm`: currently **`weighted-saturated-sum-v1` only**
- `missing_evidence` policy, `max_history_events`, `risk_buckets` thresholds

### 8.2 evaluate_risk_model

`evaluate_risk_model(model, factors) -> (score_millionths, bucket_index)`:

- Factor keys must **exactly** match the model.
- Each factor is saturated: `min(1e6, factor * 1e6 // saturation)`.
- Weighted sum divided by total weight; score capped at 1_000_000.
- Bucket is the first risk_buckets threshold ≥ score.

No floating point; no silent default factors.

### 8.3 RiskEvidence

Observed, optionally signed evidence rows:

- Types include `policy-denial`, `authority-failure`, `obligation-overdue`,
  `execution-failure`, `timeout`, `resource-overrun`, `dispute`, `rollback`,
  `archive-inclusion`, `capacity-health`.
- Classifications: `public`, `trust-domain`, `confidential`, `restricted`
  (redaction path via `redacted_cid` / store policy).

Invalid signatures or policy-denied disclosure yield evidence errors
(`G_EVIDENCE_INVALID`, `G_REDACTED`) — fail closed for consumers that require
verified evidence.

### 8.4 RiskAssessment

Binds `task_cid`, subject DID, model CID, evidence CIDs, factor map, score,
confidence, **action** (`allow` / `challenge` / `review` / `deny`), and
time/expiry windows.

Risk **action** feeds priority (see below). `deny` / incomplete evidence must
not be coerced to schedule success.

### 8.5 RiskEvidenceStore

Thread-safe SQLite (or `:memory:`) store for artifacts and history:

- Bounded pages and history depth from `DEFAULT_LIMITS`.
- Optional `signature_verifier` for signed kinds.
- Durable path for servers: env **`IPFS_DATASETS_PROFILE_G_DB`** (see package
  provider doc); default in-memory is for tests/dev only.

## 9. Neighborhood, proposals, claims, and receipts

### 9.1 NeighborhoodRecord / NeighborhoodAttestation

Peers advertise interfaces, resource classes, capacity, health evidence, trust
domain, reachable artifacts, validity windows, and signatures.

**Neighborhood support is placement confidence only.** It must never be
converted into execution authority or a Git merge permit.

`NeighborhoodAttestationEngine` evaluates attestations against proposals under
policy filters and optional distinct-DID quorum rules. Quorum failure →
`G_QUORUM_UNAVAILABLE` (fail closed).

### 9.2 ScheduleProposal

Ranks **candidates** for a task with risk assessment CID, selection policy,
policy decision, logical epoch, and **priority_tuple**.

Candidates must appear in **canonical ranked order** (capability fit, finish
estimate, peer DID, record CID keys). Out-of-order candidates fail validation.

### 9.3 Priority tuple

`derive_priority_tuple(...)` builds a deterministic list:

1. ready flag (ready first)
2. deadline class
3. risk action rank (`allow` < `challenge` < `review` < `deny`)
4. age bucket (newer preferred via negation)
5. expected value / resource fit (higher preferred via negation)
6. `retry_not_before_ms`
7. `task_cid` tie-break

Priority is **advisory ordering** for frontiers — not a lease.

### 9.4 TaskClaim, ClaimResolution, TaskReceipt

| Kind | Role |
| --- | --- |
| **TaskClaim** | Claimant DID requests a lease (`requested_lease_ms` within min/max), binds proposal/epoch/attempt, optional proof/policy |
| **ClaimResolution** | Resolver accepts/conflicts/releases/expires/completes; may emit fencing token + `lease_expires_at_ms` + coordination receipt |
| **TaskReceipt** | Execution outcome record: status, failure class, resource use, provider identity, next_state |

Lease fields are **validated as data**. Minting or honoring a lease in a live
cluster is an **external coordination** concern. Missing resolver authority,
expired leases (`G_LEASE_EXPIRED`), or claim conflicts (`G_CLAIM_CONFLICT`)
fail closed.

Receipt `next_state` values include `complete`, `ready`, `blocked`,
`compensation-required` — again evidence, not Git board mutation.

## 10. MCP service boundary

`ProfileGService` exposes methods such as:

- Goals: create/get/list/decompose/select  
- Tasks: create/get/list/ready  
- Risk: profile/assess/evidence/history  
- Neighborhood: query/attest  
- Schedule: frontier/status/propose/claim/renew/release/resolve/reconcile  

Wire error numbers map Profile G codes (`G_INVALID_ARTIFACT`,
`G_AUTHORITY_DENIED`, `G_POLICY_DENIED`, `G_NOT_READY`, `G_LEASE_EXPIRED`, …).

**Construction policy:**

- Network servers **must** inject `authority_validator`, `policy_validator`,
  and attestation signer as required.
- `trusted_local=True` is allowed only for already-authenticated in-process
  callers.
- Mutations **fail closed** unless Profile C and Profile D validators are
  configured (see service docstring and provider guide).

## 11. Relationship to the agent supervisor

| Concern | Profile G (datasets) | Agent supervisor (accelerate) |
| --- | --- | --- |
| Task identity | Content-addressed TaskSpec CID | Markdown `IPFSDOC-*` / checkbox task |
| Goal graph | Goal/Subgoal CIDs | ObjectiveGoal heap / board Goal id |
| Isolation | Artifact store + DID/epoch | Git worktrees + board namespace |
| Placement | ScheduleProposal / neighborhood | Lane selection, resource class, priority |
| Execution lease | ClaimResolution fencing/lease fields (data + external honor) | Worktree claim + merge queue authority |
| Evidence | RiskEvidence / TaskReceipt CIDs | Validation command logs, merge receipts |
| Fail closed | Missing C/D, bad CID, lease rules | Admission budgets, blocked tasks, no merge |

Supervisors may **consume** Profile G CIDs as structured planning input. They
must not treat Profile G placement scores as merge authority. Datasets must not
reimplement supervisor worktrees inside `logic.profile_g`.

See [AGENT_SUPERVISOR_AND_TASKBOARDS.md](AGENT_SUPERVISOR_AND_TASKBOARDS.md) for
taskboards, heartbeats, merge receipts, and namespace isolation.

## 12. Fail-closed and advisory placement (normative)

1. **Placement is advisory.** PlanBranch scores, neighborhood capacity, and
   priority tuples order candidates only.
2. **Execution and leases remain external.** Honoring a claim requires an
   external resolver/executor that still enforces fencing tokens, expiry, and
   policy — Profile G validates shapes and optional signatures; it does not
   replace that control plane.
3. **Missing Profile C/D validators fail closed** on actionable selection/task
   paths and service mutations.
4. **Incomplete, redacted, or invalid evidence** cannot be upgraded to `allow`
   risk action or successful receipt by documentation or UI.
5. **UNKNOWN / unavailable dependencies** degrade features; they never mint
   proof or lease success ([ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).

```text
  PlanBranch score     ──X──►  execution right
  Neighborhood quorum  ──X──►  policy approval (Profile D)
  Risk action allow    ──X──►  Git merge authority
  TaskReceipt complete ──X──►  objective heap rewrite
```

## 13. Invariants

1. Canonical DAG-JSON encoding is the only CID preimage.
2. Floats and non-safe integers never enter artifacts.
3. PlanBranch remains non-actionable without PlanSelection + validators.
4. TaskSpec actionable path re-checks selection authority/policy.
5. Risk algorithm is integer-only `weighted-saturated-sum-v1`.
6. Neighborhood is placement confidence only.
7. Lease/claim fields are bounded and conflict-checked; honor is external.
8. **Placement is advisory; execution/leases remain external and fail closed.**

## 14. Failure modes

| Condition | Code / outcome |
| --- | --- |
| Schema/field/canonical violation | `G_INVALID_ARTIFACT` |
| CID link mismatch or missing parent | `G_CID_MISMATCH` |
| Authority validator false/absent | `G_AUTHORITY_DENIED` |
| Policy validator false/absent | `G_POLICY_DENIED` |
| Selection/task not ready | `G_NOT_READY` |
| Competing selection/claim | `G_CLAIM_CONFLICT` |
| Lease outside bounds or expired | `G_LIMIT_EXCEEDED` / `G_LEASE_EXPIRED` |
| Quorum not met | `G_QUORUM_UNAVAILABLE` |
| Bad evidence / redaction | `G_EVIDENCE_INVALID` / `G_REDACTED` |
| Limit exceeded (size/depth) | `G_LIMIT_EXCEEDED` |

## 15. Extension guidance

- New artifact fields require versioned schema discipline and golden tests —
  do not widen validation silently.
- New risk algorithms need explicit `algorithm` enum entries and tests; do not
  overload `weighted-saturated-sum-v1`.
- Transports should reuse `ProfileGService` rather than re-validating ad hoc.
- Keep package import free of MCP server side effects; service stays in
  `mcp_server`.

## 16. Validation and verification

```bash
test -s docs/architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md
rg -n 'worktree|heartbeat|merge|blocked|Goal|TaskSpec|fail closed' \
  docs/architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md
```

Code-level checks (when environment allows):

```bash
python -m pytest tests/unit_tests/logic/test_profile_g.py -q
# optional transport suite
python -m pytest tests/mcp_server/test_profile_g_transport.py -q
```

## 17. Related documents

- [AGENT_SUPERVISOR_AND_TASKBOARDS.md](AGENT_SUPERVISOR_AND_TASKBOARDS.md) —
  supervisor ownership, worktrees, heartbeat, merge, namespace isolation.
- [docs/profile_g_datasets_provider.md](../../profile_g_datasets_provider.md) —
  short provider setup and env `IPFS_DATASETS_PROFILE_G_DB`.
- [DOMAIN_MAP.md](../DOMAIN_MAP.md) — Profile G facade vs `logic.profile_g`.
- [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) — non-interchangeable
  authority layers.
- [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) — trust vs feature
  degradation.
