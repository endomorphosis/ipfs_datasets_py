# Knowledge Graphs — Release, Deprecation, and Cutover Operations

**Status:** active  
**Task:** `KGP-034` (runbooks); successor gate `KGP-035` (release evidence)  
**Policy:** `kg-compatibility/v1`  
**Code:** `ipfs_datasets_py.knowledge_graphs.compat`  
**Companion ops:** `docs/operations/knowledge_graphs_runbook.md`,
`docs/operations/knowledge_graphs_slos.md`  
**Migration:** `docs/migration/knowledge_graphs/`

## Purpose

This document is the **release-facing** runbook for knowledge-graph adoption:

- publishing and enforcing **compatibility tiers** and **deprecation windows**;
- coordinating **producer cutover** (shadow → canary → promote);
- **on-call** procedures during release and rollback;
- what evidence a future release gate (`KGP-035`) must collect.

It does **not** claim the platform is production-ready until the release
evidence gate passes with fresh receipts for child goals KGP-G010–G090 and
root definition-of-done clauses.

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

## Evidence retained for KGP-035 (release gate)

The next task formalizes fail-closed evidence. Operators should already retain:

| Evidence class | Example artifact |
| --- | --- |
| Compatibility policy | CI log: `test_compatibility_policy.py` |
| Corpus differential | Receipt bound to tree + producer_id |
| Shadow metrics | Snapshot path/CID + stop_reason=`none` |
| Canary / rollback drill | Promotion + rollback result dicts |
| Backup / restore proof | `backup_digest` + `RestoreProof.ok` |
| UCAN negative | Audit receipt digests |
| Load / soak / chaos | Labelled harness runs (SLOs doc) |
| Producer sign-off | Ticket section from producers.md template |

Missing, stale, foreign-tree, skipped, partial, or contradicted evidence
**fails closed** under KGP-035.

---

## Related components

| Area | Module / doc |
| --- | --- |
| Policy | `ipfs_datasets_py.knowledge_graphs.compat` |
| Shadow | `…migration.shadow` |
| Canary / rollback | `…migration.canary` |
| Backup / alerts | `…operations` |
| Auth | `…auth` |
| SLOs | `docs/operations/knowledge_graphs_slos.md` |
| Day-2 runbook | `docs/operations/knowledge_graphs_runbook.md` |
