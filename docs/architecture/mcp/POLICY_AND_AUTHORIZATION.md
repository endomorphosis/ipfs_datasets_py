# MCP policy and authorization gates

| Field | Value |
| --- | --- |
| Interface | `MCPPolicyArchitecture@1` |
| Task | `IPFSDOC-052` |
| Status | `canonical` |
| Owner | architecture; mcp-security |
| Source of truth | `ipfs_datasets_py/mcp_server/dispatch_pipeline.py`; `compliance_checker.py`; `risk_scorer.py`; `ucan_delegation.py`; `temporal_policy.py`; `nl_ucan_policy.py`; `cid_artifacts.py`; `policy_audit_log.py`; `server.py` (policy store / delegation init); [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md); [GOVERNED_AUTHORIZATION.md](../logic/GOVERNED_AUTHORIZATION.md); [ADR-003-LAYERED-AUTHORITY.md](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004-FAIL-CLOSED-DEGRADATION.md](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, security reviewer, operator |
| Related | [AUDIT_EVENTS_AND_OBSERVABILITY.md](AUDIT_EVENTS_AND_OBSERVABILITY.md); [INTERFACES_AND_TRANSPORTS.md](INTERFACES_AND_TRANSPORTS.md); [LEGAL_AND_SECURITY_CONSTRAINTS.md](../logic/LEGAL_AND_SECURITY_CONSTRAINTS.md) |
| Review cadence | after pipeline stage, UCAN, risk, or temporal-policy contract changes |

## 1. Purpose

This guide answers: **how optional MCP pre-dispatch policy gates evaluate an
intent before tool execution, what compliance / risk / UCAN-delegation /
temporal-deontic / NL-UCAN stages decide, how deny and soft-skip outcomes
prevent or permit execution, and how those gates relate to (but never replace)
governed intent authorization and proof authority.**

**Invariant:** monitoring, health probes, metrics, and event-DAG visibility
**never substitute** for a policy allow, a verified proof, or a successful
dispatch. A green dashboard does not authorize a tool call.

Facts prefer: tests and schemas → current implementation → packaging → ADRs →
maintained guides ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## 2. Audience

| Audience | Use |
| --- | --- |
| **Architect / agent** | Place pipeline stages without collapsing policy into dispatch success |
| **Security / policy reviewer** | Confirm deny-overrides, soft-skip vs hard-fail, and non-execution paths |
| **MCP host author** | Attach `DispatchPipeline` correctly; honor deny without tool invocation |
| **Operator** | Interpret stage skip reasons and optional subsystem absence |

## 3. Scope and non-goals

### In scope

- Optional `DispatchPipeline` attach point and stage constants
- Integrated MCP++ stages: compliance, risk, delegation (UCAN), temporal
  policy (Profile D), NL-UCAN gate
- Legacy ordered `PipelineStage` handlers
- Intent CIDs, `DecisionObject` verdicts, non-execution outcomes
- Soft-degrade when subsystems are missing vs hard deny when configured stages
  evaluate and reject
- Boundary vs governed authorization (`logic.admissibility`) and proof layers

### Non-goals

- Full Event DAG compaction, Prometheus scrape layout, OpenTelemetry wiring —
  [AUDIT_EVENTS_AND_OBSERVABILITY.md](AUDIT_EVENTS_AND_OBSERVABILITY.md)
- Hierarchical discovery / meta-tools — [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md)
- Deep Legal/Security constraint catalogs —
  [LEGAL_AND_SECURITY_CONSTRAINTS.md](../logic/LEGAL_AND_SECURITY_CONSTRAINTS.md)
- Side-effect-free intent authorization portfolio and one-time capability
  consumption — [GOVERNED_AUTHORIZATION.md](../logic/GOVERNED_AUTHORIZATION.md)
- Operator runbooks (IPFSDOC-053)

## 4. Mental model

```text
  MCP client / tools_dispatch / HTTP flat call / P2P adapter
           │
           ▼
  Host builds intent (tool, actor, params) ──► PipelineIntent (intent_cid)
           │
           │  optional: server.set_pipeline(DispatchPipeline)
           ▼
  ┌─────────────────────────────────────────────────────────┐
  │  DispatchPipeline.check / run                           │
  │    COMPLIANCE → RISK → DELEGATION → POLICY → NL_UCAN    │
  │    (enabled flags / handlers only)                      │
  └─────────────────────────────────────────────────────────┘
           │
     allowed? ──no──► return error / PipelineResult(deny)
           │                 ** tool body not executed **
          yes
           │
           ▼
  HierarchicalToolManager.dispatch / tool callable
           │
           ▼
  optional record_execution → ReceiptObject + EventNode
```

Default server construction has **no pipeline** (pass-through). Policy is
opt-in via `IPFSDatasetsMCPServer.set_pipeline` or host composition. Absence of
a pipeline is **not** an allow decision from any profile; it is simply “no
MCP++ pre-dispatch gate attached.”

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Pre-dispatch stage orchestration on MCP hosts | Domain algorithms inside tools |
| Stage verdicts → `PipelineResult` / `DecisionObject` | Independent proof verification algebra |
| Optional policy store / UCAN `DelegationManager` lifecycle hooks | Agent-supervisor leases |
| Soft-skip semantics when stage subsystems are unconfigured | Production legal advice |

**Inbound:** canonical server hosts that honor `set_pipeline`; FastAPI policy
evaluate routes; meta-tools `policy_*` / `compliance_*` when registered.

**Outbound:** compliance rules, risk scorer, UCAN evaluator, temporal
`PolicyEvaluator`, NL-UCAN compiler, optional audit log sink.

**Authority notes:**

- Pipeline **allow** means “no attached stage denied this intent under current
  config.” It is **not** a Legal hard-filter proof or a theorem.
- Governed `IntentAuthorizationService@1` allow + one-time capability is a
  **separate** authority stack; hosts may compose both, but neither invents
  allow from metrics or discovery.
- Tool listing / schema discovery never implies policy allow.

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| `DispatchPipeline` | `dispatch_pipeline.py` | Legacy stage list or integrated MCP++ gates |
| `PipelineConfig` | same | Flags + injected checkers / scorers / evaluators |
| `PipelineIntent` | same | Stable `intent_cid` from tool/actor/params |
| `PipelineResult` | same | `allowed`, stage outcomes, `denied_by`, optional decision |
| `ComplianceChecker` | `compliance_checker.py` | Rule-based compliance report on intent |
| `RiskScorer` / `RiskScoringPolicy` | `risk_scorer.py` | Numeric risk, level, acceptability gate |
| UCAN / `DelegationEvaluator` / `DelegationManager` | `ucan_delegation.py` | Capability chains, expiry, revocation hooks |
| `PolicyObject` / `PolicyEvaluator` | `temporal_policy.py` | Profile D temporal-deontic evaluation |
| `UCANPolicyGate` / NL compiler | `nl_ucan_policy.py` | NL → deontic policy → gate |
| `IntentObject` / `DecisionObject` | `cid_artifacts.py` | CID-native intent and verdict artifacts |
| `PolicyAuditLog` | `policy_audit_log.py` | Optional structured evaluation trail |
| Policy / compliance meta-tools | `server.py` register path | Operator-facing manage/evaluate tools |
| Policy store init | `server._initialize_policy_store` | Optional `IPFS_POLICY_STORE_PATH` |
| Delegation init | `server._initialize_delegation_manager` | Optional UCAN delegation state |

```text
PipelineConfig flags
  enable_compliance ──► ComplianceChecker.check
  enable_risk       ──► RiskScorer.score_intent
  enable_delegation ──► DelegationEvaluator.can_invoke
  enable_policy     ──► PolicyEvaluator.evaluate (PolicyObject)
  enable_nl_ucan_gate ──► UCANPolicyGate.evaluate
         │
         ▼
  DecisionObject(decision=allow|deny|…)
  PipelineResult.allowed
```

## 7. Pipeline modes

### 7.1 Legacy stage list

Construct with `DispatchPipeline()` or `DispatchPipeline(stages=[...])`:

- Ordered `PipelineStage` handlers return `{"allowed": bool, ...}`.
- `fail_open` on handler exception defaults **True** (exception → allow with
  error metadata) unless the stage is built otherwise.
- `short_circuit=True` (default) stops remaining stages after the first deny.
- `PipelineMetricsRecorder` records stage durations, skips, and denials;
  optional audit log records per-stage allow/deny.

Helpers:

| Helper | Behavior |
| --- | --- |
| `make_default_pipeline` | Minimal tool-name + actor pass-through checks |
| `make_full_pipeline` | Handlers for compliance, risk, UCAN leaf check, policy, NL gate stubs |

### 7.2 Integrated MCP++ mode

Construct with `DispatchPipeline(config=PipelineConfig(...))` (or pass
`PipelineConfig` as the first positional arg):

| Flag | Stage constant | Default | Behavior when enabled |
| --- | --- | --- | --- |
| `enable_compliance` | `COMPLIANCE` | `False` | `ComplianceChecker` summary must be `"pass"` |
| `enable_risk` | `RISK` | `False` | `RiskScorer` assessment `is_acceptable` |
| `enable_delegation` | `DELEGATION` | `False` | `DelegationEvaluator.can_invoke` with leaf CID |
| `enable_policy` | `POLICY` | `False` | Temporal `PolicyEvaluator` against `policy_object` |
| `enable_nl_ucan_gate` | `NL_UCAN_GATE` | `False` | `UCANPolicyGate.evaluate` |

Stage order is fixed: compliance → risk → delegation → policy → NL-UCAN.
First failed stage returns deny (short-circuit). If no flags are enabled, a
synthetic `PASS` outcome records pass-through.

### 7.3 Soft-skip vs hard deny (critical)

| Situation | Integrated outcome | Meaning |
| --- | --- | --- |
| Stage flag **off** | Stage not run | Not an evaluation |
| Flag **on**, subsystem missing / import error | Stage **passes** with skip reason | Soft degrade — **not** a positive policy decision |
| Flag **on**, evaluator runs, verdict deny | Stage **fails**, pipeline deny | Hard non-execution |
| Flag **on**, no `policy_object` / no `delegation_leaf_cid` | Skip with allow reason | Unconfigured dependency treated as skip |
| Handler exception in legacy with `fail_open=True` | Allow + error metadata | Soft degrade |
| Host never attaches pipeline | No gate | Execution proceeds unless other hosts add gates |

Operators must not treat soft-skip as “policy approved.” For production
fail-closed deployments, inject real checkers, set required flags, and treat
missing dependencies as configuration errors outside the pipeline (or use
legacy stages with `fail_open=False` handlers).

## 8. Gate semantics

### 8.1 Compliance

- **Module:** `compliance_checker.py`
- **Input:** intent dict / `PipelineIntent.__dict__`
- **Output:** report with summary (`pass` / non-pass) and optional violations
- **Deny:** summary ≠ `"pass"` → pipeline blocked; tool not executed
- **Meta-tools (optional):** `compliance_add_rule`, `compliance_list_rules`,
  `compliance_remove_rule`, `compliance_check_intent`,
  `compliance_register_interface`

Compliance here is **MCP++ rule evaluation**, not a substitute for Legal hard
applicability in the logic-policy stack.

### 8.2 Risk

- **Module:** `risk_scorer.py`
- **Artifacts:** `RiskLevel` (negligible → critical), `RiskScore` /
  `RiskAssessment`, `RiskScoringPolicy`
- **Score factors:** tool base risk (overrides or default ~0.3), actor trust,
  param complexity penalty
- **Gate:** `is_acceptable` when score ≤ `max_acceptable_risk` (default 0.75)
- **Deny:** unacceptable risk → non-execution
- **Related:** `risk_score_from_dag` can derive risk signals from event history
  for analytics — **still not** an authorization grant by itself

Risk scores are advisory gates when enabled; they do not prove Legal
compliance or UCAN validity.

### 8.3 Delegation / UCAN (Profile C)

- **Module:** `ucan_delegation.py`
- **Primitives:** `Capability(resource, ability)`, `Delegation` /
  `DelegationToken`, `DelegationChain`, `DelegationEvaluator`,
  `RevocationList`, `DelegationManager`
- **Runtime check:** `can_invoke(leaf_cid, resource, ability, actor)` validates
  chain existence, capability match, expiry, and optional revocation
- **Integrated stage:** requires `delegation_leaf_cid` on config; empty leaf →
  soft skip
- **Server lifecycle:** optional `_initialize_delegation_manager` + save on
  shutdown

UCAN-style delegation is **capability attenuation**, not proof of dataset
integrity. Root/issuer trust remains an operator configuration problem.

### 8.4 Temporal-deontic policy (Profile D)

- **Module:** `temporal_policy.py`
- **Clauses:** `permission` | `prohibition` | `obligation` with optional
  `valid_from` / `valid_until` / `obligation_deadline`
- **Policy identity:** content-addressed `policy_cid` via `artifact_cid`
- **Evaluator algorithm (`PolicyEvaluator.evaluate`):**
  1. Match temporally valid clauses to actor/action/resource.
  2. Any matching **prohibition** → **`deny`** (obligations cleared).
  3. Matching **permission** + obligations → **`allow_with_obligations`**.
  4. Matching **permission** only → **`allow`**.
  5. No permission → **`deny`** (default deny for explicit evaluation).

Pipeline integrated stage treats `allow` and `allow_with_obligations` as
passed; `deny` blocks execution.

**Obligations do not auto-execute.** `allow_with_obligations` is still a
pre-dispatch allow with residual duties recorded on the decision artifact;
hosts must track obligations separately.

### 8.5 NL-UCAN gate

- **Module:** `nl_ucan_policy.py`
- **Role:** compile natural-language policy text into `PolicyObject` (logic
  `DeonticConverter` when available; pure-Python fallback otherwise)
- **Open-by-default for unregistered coverage:** tools not covered by a
  registered NL policy remain allowed by design of the gate
- **CID-validated recompilation:** source NL text hashed; mutation triggers
  recompile before evaluate
- **Integrated stage:** `UCANPolicyGate.evaluate` → same allow/deny family as
  Profile D decisions

Do not confuse “open by default when no NL policy registered” with global
security policy. Production hosts that need closed-world access must register
covering policies or enable other hard stages.

### 8.6 CID-native decision artifacts

| Artifact | Role |
| --- | --- |
| `IntentObject` / `PipelineIntent.intent_cid` | What is proposed (tool + bindings) |
| `DecisionObject` | Verdict: `allow` \| `deny` \| `allow_with_obligations` + justification, proofs_checked, obligations |
| `ReceiptObject` | Post-execution attestation (intent/decision/output CIDs) — **not** an allow token |
| `ExecutionEnvelope` | Bundle of pre/post CIDs for a call |
| `EventNode` | DAG link among intent/decision/receipt/output |

Verdict constants: `ALLOW`, `DENY`, `ALLOW_WITH_OBLIGATIONS` in
`cid_artifacts.py`. `DecisionObject.is_allowed` is true only for allow
families.

## 9. Non-execution outcomes

When a pipeline is attached and `check` returns `allowed=False`:

1. Hosts that honor the pipeline **must not** invoke the tool body.
2. Typical hierarchical / HTTP error surfaces return an error dict / MCP error
   without side-effecting domain code.
3. `PipelineResult` carries `denied_by`, stage outcomes, and a synthetic
   `DecisionObject` with `decision="deny"`.
4. Optional audit / metrics record the **deny** (observability only).

| Outcome | Tool runs? | Typical signal |
| --- | --- | --- |
| Pipeline deny (compliance / risk / UCAN / policy / NL) | **No** | `status=error` or structured deny; `denied_by` stage |
| Soft-skip all stages | Yes (if host proceeds) | Stage reasons mention unavailable/skipping |
| No pipeline | Yes (subject to other gates) | Pass-through |
| Circuit open / shutdown / missing tool | No | Server/dispatch errors unrelated to policy |
| Governed pre-dispatch reject (if composed) | No | Capability/receipt rejection — separate stack |

**Deny is success of the control plane’s safety function**, not a transport
failure. Do not “retry until green metrics” after a policy deny without
changing actor, capability, or policy roots.

## 10. Extended meta-tools and HTTP evaluate

When `_enable_extended_meta_tools` is true (default on full server init),
registration **attempts**:

| Group | Examples |
| --- | --- |
| Policy management | `policy_register`, `policy_list`, `policy_remove`, `policy_evaluate`, `interface_register`, `interface_list` |
| Compliance rules | `compliance_add_rule`, `compliance_list_rules`, `compliance_remove_rule`, `compliance_check_intent`, `compliance_register_interface` |

Import failure leaves the four hierarchical meta-tools intact.

HTTP surface (when FastAPI host is used) includes
`POST /mcp/policy/evaluate` and related Profile D helpers. Evaluation endpoints
produce decisions; they **do not** by themselves dispatch tools.

## 11. Relation to governed authorization and layered authority

| Layer (concept) | MCP pipeline role | Governed stack role |
| --- | --- | --- |
| Discovery / schema | Lists tools | N/A |
| Compliance / risk / UCAN / temporal | Optional pre-dispatch filters | May feed or follow intent evaluation |
| Proof / attestation | May appear in `proofs_checked` | Independent verification required |
| Decision receipt / one-time capability | Not the same as `ReceiptObject` execution receipt | `DecisionReceipt@1` + `AuthorizationCapability@1` |
| Dispatch observation | Tool ran | Separate from authorization |

[ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md): proof ≠ policy allow ≠
dispatch success. [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md):
prefer fail-closed for security-critical paths; document soft-skip honestly
where the MCP++ integrated pipeline degrades.

Cross-link: [GOVERNED_AUTHORIZATION.md](../logic/GOVERNED_AUTHORIZATION.md)
for side-effect-free evaluate → capability consume → separate dispatch.

## 12. Failure modes and discrepancies

| Observation | Guidance |
| --- | --- |
| Integrated stages soft-skip on import / missing config | Do not document as fail-closed allow; configure injectors for production |
| Default `PipelineConfig` all flags false | Pipeline in integrated mode with empty config is pass-through |
| `allow_with_obligations` passes pipeline | Residual duties remain operator/process concerns |
| UCAN signatures may be opaque / mock-compatible in tests | Production trust requires real key material and verification policy |
| Policy meta-tools optional | Absence does not remove hierarchical tools |
| Soft-skip on missing subsystems | Soft degrade; not a positive security proof |

## 13. Extension checklist

1. Attach `DispatchPipeline` only when pre-dispatch gates are required.
2. Prefer integrated mode with explicit `PipelineConfig` flags and injected
   checkers for production; avoid relying on soft-skip for compliance.
3. For hard deny on missing subsystems, wrap stages or fail host startup when
   required modules are absent.
4. Record denials to `PolicyAuditLog` / metrics without treating counters as
   authorization.
5. Keep secrets out of intent params that enter CIDs; use commitments or
   vault references where possible.
6. Compose governed pre-dispatch enforcement when one-time capabilities are
   required — do not reimplement attenuation inside ad-hoc tool code.
7. Never map “health ready” or “Prometheus scrape success” to pipeline allow.

## 14. Validation

```bash
test -s docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md
test -s docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md
rg -n 'risk|UCAN|deny|redact|event DAG|receipt|trace|metric|health' \
  docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md \
  docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md

# Optional live smoke (package installed)
python -c "from ipfs_datasets_py.mcp_server.dispatch_pipeline import DispatchPipeline, PipelineConfig, PipelineIntent; r=DispatchPipeline(config=PipelineConfig()).check(PipelineIntent('demo')); print(r.verdict, r.allowed)"
```

## 15. Related documents

| Document | Relationship |
| --- | --- |
| [AUDIT_EVENTS_AND_OBSERVABILITY.md](AUDIT_EVENTS_AND_OBSERVABILITY.md) | Event DAG, audit correlation, metrics, health, P2P states |
| [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md) | Server lifecycle, attach point, result envelopes |
| [INTERFACES_AND_TRANSPORTS.md](INTERFACES_AND_TRANSPORTS.md) | Profile B artifacts, transport matrix |
| [GOVERNED_AUTHORIZATION.md](../logic/GOVERNED_AUTHORIZATION.md) | Side-effect-free intent authorization |
| [RESULT_AUTHORITY.md](../logic/RESULT_AUTHORITY.md) | Non-substitution of authority kinds |
| [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) / [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Product authority and degradation rules |
