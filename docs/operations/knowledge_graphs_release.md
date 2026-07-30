# Knowledge Graphs — Release, Deprecation, and Cutover Operations

**Status:** active  
**Tasks:** `KGP-034` (runbooks); `KGP-035` (release evidence gate)  
**Policies:** `kg-compatibility/v1`, `kg-release-evidence/v1`  
**Code:** `ipfs_datasets_py.knowledge_graphs.compat`,
`ipfs_datasets_py.knowledge_graphs.release_gate`  
**Companion ops:** `docs/operations/knowledge_graphs_runbook.md`,
`docs/operations/knowledge_graphs_slos.md`  
**Migration:** `docs/migration/knowledge_graphs/`

## Purpose

This document is the **release-facing** runbook for knowledge-graph adoption:

- publishing and enforcing **compatibility tiers** and **deprecation windows**;
- coordinating **producer cutover** (shadow → canary → promote);
- **on-call** procedures during release and rollback;
- running the **production release evidence gate** (`KGP-035`).

The platform is **not production ready** until
`GraphReleaseGate` / `evaluate_release_evidence` emits a signed,
content-addressed decision with `production_ready=True`. Task status,
coverage, prose, optional-dependency skips, sample-only corpus runs, absent
soak/chaos, missing UCAN negative proof, or unknown environments are **never**
accepted as substitutes for exact fresh passing receipts.

## Quick links

| Topic | Location |
| --- | --- |
| Compatibility tiers & windows | `docs/migration/knowledge_graphs/compatibility.md` |
| Phase runbook (backup…rollback) | `docs/migration/knowledge_graphs/migration_runbook.md` |
| Producer prerequisites | `docs/migration/knowledge_graphs/producers.md` |
| Schema / storage / UCAN | `docs/migration/knowledge_graphs/schema_storage_ucan.md` |
| Day-2 ops & DR | `docs/operations/knowledge_graphs_runbook.md` |
| SLOs & performance gates | `docs/operations/knowledge_graphs_slos.md` |
| Executable policy | `ipfs_datasets_py.knowledge_graphs.compat` |

```python
from ipfs_datasets_py.knowledge_graphs.compat import (
    POLICY_VERSION,
    policy_dict,
    assert_policy_invariants,
    removal_allowed,
    can_enter_phase,
)

assert POLICY_VERSION == "kg-compatibility/v1"
assert_policy_invariants()
```

Validation:

```bash
python -m pytest -q tests/unit/knowledge_graphs/test_compatibility_policy.py
```

---

## Compatibility publication (release checklist)

Before tagging a release that touches knowledge graphs:

| # | Check | Pass |
| --- | --- | --- |
| 1 | `assert_policy_invariants()` passes in CI | ☐ |
| 2 | `policy_dict()["policy_version"]` is `kg-compatibility/v1` | ☐ |
| 3 | Mandatory five legacy ids present with ADR dispositions | ☐ |
| 4 | Any **new** public API is tier T0 (`GraphService` / `Client`) | ☐ |
| 5 | Any **new** T2 shim emits `DeprecationWarning` citing replacement | ☐ |
| 6 | No public name is **removed** in the same release that first warns (`MIG-5`) | ☐ |
| 7 | Removals satisfy `removal_allowed(legacy_id, package_version=..., calendar_date=...)` | ☐ |
| 8 | Migration + ops docs updated if windows or producer evidence change | ☐ |

```python
from ipfs_datasets_py.knowledge_graphs.compat import (
    same_release_warn_remove_forbidden,
    removal_allowed,
)

# Conflict policy: warn and remove must not share a version.
assert same_release_warn_remove_forbidden("0.1.0", "0.1.0") is True
assert not removal_allowed("knowledge_graph_manager", package_version="0.1.0")
```

### Deprecation announcement template

```text
Component: <legacy_id / import path>
Tier: T2
Disposition: deprecate
Replacement: GraphService Client/AsyncClient (or specific T0 API)
Warn since: package <warn_since_version>
Remove no earlier than: package <remove_after_version> / calendar <removal_earliest>
Security fast-path: only with receipt_cid <...>
```

---

## Release train phases (operator view)

Aligns with migration phases; owners sign each gate.

```text
prerequisites → backup → dry_run → shadow → canary → cutover
                                              ↘ rollback (any time)
```

| Phase | Release artifact | On-call posture |
| --- | --- | --- |
| prerequisites | Producer sign-off sheet | Normal |
| backup | `backup_id` + `backup_digest` | Normal |
| dry_run | Scrub/repair plan digests (confirm=False) | Normal |
| shadow | Metrics snapshot; auto-stop config | Elevated watch |
| canary | Allowlist + verified heads | **Page-ready** |
| cutover | Expanded allowlist / promoted heads | **Page-ready** |
| rollback | CAS result + re-verify | Incident |

Detailed commands:
`docs/migration/knowledge_graphs/migration_runbook.md`.

### Cutover go / no-go

**Go** only if:

1. `can_enter_phase("cutover", completed_phases=..., producer_id=..., evidence=...)`  
2. Latest backup verified; restore proof exercised on a **standby** path in lab  
3. Shadow mismatch / security thresholds not exceeded  
4. Canary graphs stable for agreed soak (default ≥ 24h for medium/high risk)  
5. Zero open **critical** ops alerts on the target environment  
6. UCAN negative proofs present when enforcement is enabled for that producer  
7. No unexplained p95/throughput regression > 10% vs labelled baseline (SLOs)  

**No-go** examples: missing evidence id, restore proof failed, shadow stopped
for security, canary CAS promote failures, readiness red.

---

## On-call procedures (cutover window)

### Roles

| Role | Responsibility |
| --- | --- |
| Release captain | Phase gates, go/no-go, ticket hygiene |
| On-call engineer | Alert response, rollback execution, diagnostics capture |
| Producer owner | Corpus evidence, sign-off, query sample validation |
| Security (as needed) | UCAN incidents, revocation storms |

### Page-worthy during canary / cutover

Treat as **critical** even if the standing alert severity is warning:

| Signal | Immediate action |
| --- | --- |
| `kg-ops-liveness-down` / `kg-ops-readiness-fail` | Remove from LB; diagnostics; do not expand canary |
| Canary security stop / UCAN deny spike | Disable canary; rollback allowlisted graphs; revoke suspect tokens |
| Shadow correctness stop / mismatch threshold | Stop dual-write; hold cutover; capture metrics |
| `kg-ops-restore-proof-failed` | Do not point production at restore path |
| `kg-ops-catalog-checksum-drift` | Freeze writers; scrub; prefer backup restore if widespread |
| Unexplained p95 regression > 10% | Hold release; compare labelled baselines |

### Rollback drill (on-call)

```python
from ipfs_datasets_py.knowledge_graphs.migration.canary import (
    CanaryController,
    RollbackReason,
)

# controller already bound to catalog + verified heads from canary setup
result = controller.rollback(
    tenant,
    graph_id,
    reason=RollbackReason.OPERATOR,  # or SECURITY / CORRECTNESS
    remove_from_allowlist=True,
)
assert result.ok
```

Then:

1. Confirm branch head == verified revision.  
2. `build_default_health(...).readiness().ready`  
3. Run golden query sample / query vectors from backup.  
4. Capture redacted diagnostics JSON + rollback result dict on the incident.  
5. Schedule post-incident backup from recovered primary.  

Full DR:
`docs/operations/knowledge_graphs_runbook.md` § Disaster recovery procedure.

### Communications

- Never paste UCAN tokens, raw Cypher/SPARQL, or property bags into tickets.  
- Prefer `receipt_cid`, `backup_digest`, revision ids, and redacted ops logs.  
- State clearly whether traffic is baseline, shadow, canary, or rolled back.

---

## Storage profile selection at release

| Producer class | Typical profile |
| --- | --- |
| SkillCenter / CVEfixes / 211 retrieval | `hybrid` |
| Browser projection / supervisor graphs | `parquet` |
| Pin-heavy multi-region | `ipfs_kit` |
| Pure IPLD DAG demos | `ipfs_ipld` |

Validate with `compat.validate_storage_profile` / producer defaults. Do not
swap profile mid-canary without a new revision and dual-run evidence.

---

## UCAN setup at release

1. Enforce with `GraphAuthorizationService` on all production surfaces.  
2. Confirm abilities, caveats, and resource containment for the cutover tenant.  
3. Retain allow **and** deny audit receipts (content-addressed, redacted).  
4. Negative suite required for high-risk producers (`ucan_negative_proof`).  

Details: `docs/migration/knowledge_graphs/schema_storage_ucan.md`.

---

## Production release evidence gate (KGP-035)

**Executable module:** `ipfs_datasets_py.knowledge_graphs.release_gate`  
**Policy id:** `kg-release-evidence/v1`  
**Schemas:** `kg-release-gate/v1`, `kg-release-evidence-bundle/v1`,
`kg-release-decision/v1`  
**Validation:**

```bash
python -m pytest -q tests/integration/knowledge_graphs/test_release_gate.py
```

### Standing rule

Until the gate passes, treat the platform as **not production ready**. There is
no partial credit: missing, stale, foreign-tree, skipped, partial, or
contradicted evidence **fails closed**.

```python
from ipfs_datasets_py.knowledge_graphs.release_gate import (
    GraphReleaseGate,
    build_passing_bundle,  # test / dry-run helper only
    evaluate_release_evidence,
    is_production_ready,
    policy_dict,
)

assert policy_dict()["policy_id"] == "kg-release-evidence/v1"
assert is_production_ready(None) is False

gate = GraphReleaseGate(
    expected_tree_id="<current-tree-id>",
    signing_key=b"<operator-hmac-key>",
)
decision = gate.standing_decision()
assert decision.production_ready is False
assert decision.decision_cid.startswith("kg-rel1-")
assert decision.signature  # content-addressed or hmac-sha256:
```

### Required evidence (exact)

| Class | Requirement |
| --- | --- |
| Child goals | Exact fresh **passing** receipts for `KGP-G010` … `KGP-G090` |
| Root DoD | Every root definition-of-done clause receipt (see below) |
| Corpus sign-off | Full-mode sign-off for `cvefixes`, `skillcenter`, `two_eleven`, `code_evidence` |
| UCAN negative | ≥1 deny audit receipt CID bound to the current tree |
| Soak + chaos | Non-empty soak **and** chaos receipt digests |
| Environment | Labelled environment id (not `unknown` / empty) |
| Tree binding | Every artifact `tree_id` equals the evaluation tree |

### Root definition-of-done clauses

| `clause_id` | Meaning |
| --- | --- |
| `concurrent_identity_durability` | ≥16 concurrent graph IDs; no identity confusion / lost updates / cross-tenant leakage |
| `storage_profiles_contract` | Parquet, IPFS/IPLD, `ipfs_kit_py` pass shared contract + restart/crash recovery |
| `four_surface_parity` | Python, CLI, MCP, MCP++ share operation/query/error vectors |
| `ucan_fail_closed` | Allow, attenuation, expiry, revocation, replay, denial + fail-closed audit |
| `sharded_integrity` | v1/v2 sharded integrity and cross-shard traversal |
| `corpora_differential` | CVEfixes, SkillCenter, 211-AI, code/evidence differentials + workloads |
| `load_soak_chaos_ops` | Load, soak, chaos, backup/restore, observability, resource bounds on a **labelled** environment |
| `migration_reversible` | Runbooks, rollback, compatibility, deprecation; no legacy moved early |

### Rejected substitutes (always fail)

| Offered as “proof” | Gate code |
| --- | --- |
| Task / backlog status | `rejected_substitute` |
| Coverage percentages | `rejected_substitute` |
| Prose / narrative claims | `rejected_substitute` |
| Optional-dependency skip / xfail | `skipped_receipt` / `rejected_substitute` |
| Sample-only corpus runs | `sample_only_corpus` |
| Absent soak or chaos | `absent_soak` / `absent_chaos` |
| Missing UCAN deny proof | `missing_ucan_negative_proof` |
| Unknown / unlabelled environment | `unknown_environment` |
| Stale receipt | `stale_receipt` |
| Foreign tree | `foreign_tree` |
| Digest mismatch | `contradicted_evidence` |

### Operator evaluation flow

1. Collect real validation receipts from child-goal harnesses (not
   `build_passing_bundle`, which is for tests/dry-runs only).
2. Bind every receipt to the **current** repository `tree_id`.
3. Attach full-mode corpus sign-offs, UCAN deny receipt CIDs, soak/chaos
   digests, and a labelled environment.
4. Evaluate:

```python
from ipfs_datasets_py.knowledge_graphs.release_gate import (
    GraphReleaseGate,
    ReleaseEvidenceBundle,
    ReleaseGateFailClosed,
)

gate = GraphReleaseGate(
    expected_tree_id=tree_id,
    signing_key=signing_key,
    package_version=package_version,
)
try:
    decision = gate.evaluate_or_raise(bundle)
except ReleaseGateFailClosed as exc:
    # Platform remains not production ready.
    decision = exc.decision
    for blocker in decision.blockers:
        print(blocker.code, blocker.subject, blocker.message)

assert decision.production_ready  # only on full pass
# Retain decision.decision_cid + decision.signature on the release ticket.
```

5. Publish the decision dict (`decision.to_dict()`) on the release record.
   Prefer `decision_cid`, `bundle_digest`, and blocker codes over raw tokens
   or query text.

### Evidence retained (checklist)

| Evidence class | Example artifact |
| --- | --- |
| Child goal receipts | `GoalReceipt` per `KGP-G010`…`KGP-G090` |
| Root DoD receipts | `DodClauseReceipt` per clause_id |
| Compatibility policy | CI log: `test_compatibility_policy.py` |
| Corpus differential | Receipt bound to tree + producer_id |
| Corpus sign-off | Full-mode `CorpusSignOff` per required corpus |
| Shadow metrics | Snapshot path/CID + stop_reason=`none` |
| Canary / rollback drill | Promotion + rollback result dicts |
| Backup / restore proof | `backup_digest` + `RestoreProof.ok` |
| UCAN negative | `UCANNegativeProof.deny_receipt_cids` |
| Load / soak / chaos | Labelled harness digests (SLOs doc) |
| Environment binding | Non-unknown `EnvironmentBinding` |
| Release decision | Signed `ReleaseDecision` (`decision_cid`) |

---

## Related components

| Area | Module / doc |
| --- | --- |
| Release gate | `ipfs_datasets_py.knowledge_graphs.release_gate` |
| Policy | `ipfs_datasets_py.knowledge_graphs.compat` |
| Shadow | `…migration.shadow` |
| Canary / rollback | `…migration.canary` |
| Backup / alerts | `…operations` |
| Auth | `…auth` |
| SLOs | `docs/operations/knowledge_graphs_slos.md` |
| Day-2 runbook | `docs/operations/knowledge_graphs_runbook.md` |
