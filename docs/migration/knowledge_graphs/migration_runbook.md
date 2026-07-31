# Knowledge Graphs — Migration Phase Runbook

**Task:** `KGP-034`  
**Code:** `ipfs_datasets_py.knowledge_graphs.migration` (shadow, canary),
`ipfs_datasets_py.knowledge_graphs.operations` (backup/restore),
`ipfs_datasets_py.knowledge_graphs.compat` (phase gates)

## Phase order

Forward phases (must complete in order):

1. **prerequisites** — producer sign-off + environment readiness  
2. **backup** — immutable catalog backup + verify  
3. **dry_run** — schema/integrity checks without mutating heads  
4. **shadow** — dual-read; caller always sees primary  
5. **canary** — allowlisted graph IDs on candidate heads  
6. **cutover** — promote remaining traffic after evidence  

**rollback** is always available at any time after a verified head is recorded
(catalog CAS; no data conversion).

```python
from ipfs_datasets_py.knowledge_graphs.compat import can_enter_phase, FORWARD_PHASES

assert can_enter_phase("backup", completed_phases=["prerequisites"])
assert not can_enter_phase("shadow", completed_phases=["prerequisites", "backup"])
# dry_run missing
assert can_enter_phase(
    "cutover",
    completed_phases=list(FORWARD_PHASES[:-1]),
    producer_id="skillcenter_ir_graphrag",
    evidence=[
        "schema_v2_v3_compat",
        "graph_vector_bm25_parity",
        "differential_reader_parity",
        "backup_restore_proof",
    ],
)
```

---

## 1. Prerequisites

See [producers.md](./producers.md) for corpus-specific evidence.

Shared checklist:

| Check | Pass criteria |
| --- | --- |
| Control plane | Catalog open; `GraphService` healthy (`/healthz`, `/readyz`) |
| Identity | Every request names a `GraphTarget` (`kg://tenant/graph…`) |
| UCAN (if enforced) | Allow + negative (deny/expiry/revocation) proofs on environment |
| Observability | Ops telemetry exporting; alert catalog loaded |
| SLOs | Labelled baseline present for environment (see SLOs doc) |
| Producer | Owner sign-off recorded; fixture-only producers not treated as canonical code |
| Policy | `assert_policy_invariants()` green |

Do **not** start backup of a degraded catalog: capture diagnostics first
(`run_diagnostics`).

---

## 2. Backup

Use the immutable backup path from the operations runbook. Cutover and
rollback both depend on a **verified** backup digest in the change ticket.

```python
from pathlib import Path
from ipfs_datasets_py.knowledge_graphs.catalog import open_catalog
from ipfs_datasets_py.knowledge_graphs.operations import (
    create_backup,
    verify_backup,
    run_diagnostics,
)

catalog = open_catalog("/var/lib/kg/catalog.sqlite")
diag = run_diagnostics(catalog=catalog, tenant="acme")
assert diag.overall_status != "critical"

backup = create_backup(catalog, Path("/var/backups/kg"), tenant="acme")
ok, issues = verify_backup(backup.path)
assert ok, issues
# Record backup.manifest.backup_digest and backup_id in the change ticket
```

| Rule | Detail |
| --- | --- |
| Immutability | Backup files chmod read-only after write |
| Scope | Prefer tenant-scoped backups for multi-tenant hosts |
| Proof later | Restore uses revision ids, checksums, and query vectors |

Full disaster-recovery steps:
`docs/operations/knowledge_graphs_runbook.md` § Backup and restore.

---

## 3. Dry-run

Dry-run validates schema, integrity, and repair **plans** without moving
branch heads or converting data.

```python
from ipfs_datasets_py.knowledge_graphs.operations import (
    scrub_catalog_manifests,
    preview_repair,
    apply_repair_plan,
)
from ipfs_datasets_py.knowledge_graphs.migration import SchemaChecker

# Catalog scrub (no mutation)
scrub = scrub_catalog_manifests(catalog, tenant="acme", graph_id="skills")
plan = preview_repair(catalog, tenant="acme", graph_id="skills")
assert plan.dry_run is True
# Still a no-op:
apply_repair_plan(catalog, plan, confirm=False)

# Optional: export / schema compatibility against a staging artifact
checker = SchemaChecker()
# is_compatible, issues = checker.check_compatibility("export.json")
```

| Allowed | Forbidden |
| --- | --- |
| Scrub, preview repair, schema check, differential offline compare | `cas_set_head` to candidate without canary allowlist |
| Staging import into a **new** graph id | In-place overwrite of live revision payloads |
| GC **dry-run** only | GC execute on unpinned live heads |

---

## 4. Shadow

Shadow dual-reads primary (legacy / production) and secondary (candidate)
paths. **Caller always receives the primary result.**

```python
from ipfs_datasets_py.knowledge_graphs.migration.shadow import (
    ShadowConfig,
    ShadowReader,
)

config = ShadowConfig(
    label="skillcenter",
    max_mismatch_rate=0.05,
    max_absolute_mismatches=50,
    max_latency_ratio=3.0,
    max_shadow_error_rate=0.10,
    allow_dual_write=False,  # dual-write is opt-in only
    security_stop_immediate=True,
)
shadow = ShadowReader(config)

def primary_read():
    return baseline_client.query(target, query)

def candidate_read():
    return candidate_client.query(target, query)

outcome = shadow.read(
    primary=primary_read,
    shadow=candidate_read,
    operation="query",
    graph_id=target.graph_id,
)
# outcome.result is always the primary value
metrics = shadow.metrics.snapshot()
```

### Automatic stop

Shadow stops dual comparison (and refuses dual-write) when thresholds trip:

| Reason | Default threshold |
| --- | --- |
| mismatch_rate | > 5% (after min samples) |
| absolute_mismatches | > 50 |
| latency_ratio | shadow/primary > 3.0 |
| shadow_error_rate | > 10% |
| security | immediate stop |

Mismatch evidence is **bounded** (item count + byte size). Dual-write
requires `allow_dual_write=True` **and** an idempotency key; dual-write is
refused when stopped (`ShadowStoppedError`).

### Exit criteria for shadow

- Mismatch rate under threshold for the producer soak window  
- No security stop events  
- Latency ratio within bound (or documented environment explanation)  
- Metrics exported / retained for the release ticket  

---

## 5. Canary

Canary routes **allowlisted** `(tenant, graph_id)` pairs to the candidate
stack. All other graphs stay on baseline (optionally with shadow dual-read).

```python
from ipfs_datasets_py.knowledge_graphs.migration.canary import (
    CanaryConfig,
    CanaryController,
    RollbackReason,
)

canary_cfg = CanaryConfig(
    allowlist=frozenset({("acme", "skills-canary")}),
    enabled=True,
    auto_rollback_on_security=True,
    auto_rollback_on_correctness=True,
    auto_disable_on_shadow_stop=True,
    label="skillcenter",
    shadow_non_canary=True,
)
controller = CanaryController(catalog, config=canary_cfg, shadow_reader=shadow)

# Record pre-canary head before promotion (also done inside promote)
controller.record_verified_head(
    "acme", "skills-canary", revision_id=current_head, source="pre_canary"
)

promo = controller.promote(
    "acme",
    "skills-canary",
    canary_revision=candidate_revision_id,
    idempotency_key="canary-skills-2026-07-30",
)
assert promo.ok
```

| Rule | Detail |
| --- | --- |
| Allowlist only | Non-listed graphs never receive canary heads |
| Verified head | Promotion stores prior head as rollback target |
| Immutability | Candidate revision must already exist in catalog |
| No conversion | Payloads are never rewritten in place |

### Canary observability

- Route counters: baseline / canary / shadow (`CanaryMetrics`)  
- Shadow metrics on dual-read graphs  
- Alert: readiness fail, error-rate high, p95 regression (ops runbook)  

---

## 6. Cutover

Cutover expands canary allowlist (or promotes remaining graphs) only when:

1. All forward phases through **canary** completed for the producer.  
2. Producer `required_evidence` present (see [producers.md](./producers.md)).  
3. Last verified backup digest is recorded.  
4. No open critical ops alerts on the target environment.  
5. Compatibility / deprecation windows for any removed shims satisfy
   `removal_allowed` (if a release also drops public names).

```python
from ipfs_datasets_py.knowledge_graphs.compat import can_enter_phase

assert can_enter_phase(
    "cutover",
    completed_phases=[
        "prerequisites", "backup", "dry_run", "shadow", "canary"
    ],
    producer_id="skillcenter_ir_graphrag",
    evidence=[
        "schema_v2_v3_compat",
        "graph_vector_bm25_parity",
        "differential_reader_parity",
        "backup_restore_proof",
    ],
)
```

After cutover:

- Re-run readiness + golden query sample.  
- Schedule a fresh immutable backup from the new primary.  
- File producer sign-off on the release ticket (see release doc).  

---

## 7. Rollback

Rollback **never** converts or deletes legacy data. It moves the catalog
branch head back to the last **verified immutable** revision via CAS.

```python
result = controller.rollback(
    "acme",
    "skills-canary",
    reason=RollbackReason.OPERATOR,
    remove_from_allowlist=True,
    idempotency_key="rollback-skills-2026-07-30",
)
assert result.ok
assert result.to_revision == result.verified_head.revision_id
```

| Trigger | Action |
| --- | --- |
| Security threshold / UCAN incident | Auto-rollback when configured; page on-call |
| Correctness / mismatch threshold | Disable canary; rollback allowlisted graphs |
| Shadow stopped | Auto-disable canary when `auto_disable_on_shadow_stop` |
| Operator judgment | Manual rollback; leave allowlist cleared |
| Restore proof failed | Do **not** serve restored path; pick prior verified backup |

If CAS conflicts (`ROLLBACK_CONFLICT`): re-read current head, confirm
verified head still valid, retry with a new idempotency key, or halt writers
and escalate.

### Rollback validation

1. `result.ok is True`  
2. Branch head matches verified revision  
3. Readiness green  
4. Golden queries match pre-canary fingerprints (from backup query vectors)  
5. Incident ticket records `from_revision`, `to_revision`, reason  

---

## Operator timeline (example)

| T+ | Action |
| --- | --- |
| T+0 | Prerequisites + diagnostics |
| T+1h | Immutable backup + verify |
| T+2h | Dry-run scrub / schema / staging import |
| T+1d | Shadow on sample traffic (soak) |
| T+3d | Canary allowlist (1–N graph ids) |
| T+7d | Expand canary / cutover if evidence green |
| any | Rollback via CAS if thresholds trip |

---

## Related

- [compatibility.md](./compatibility.md) — tiers and windows  
- [producers.md](./producers.md) — corpus prerequisites  
- [schema_storage_ucan.md](./schema_storage_ucan.md) — schema, storage, UCAN  
- [knowledge_graphs_release.md](../../operations/knowledge_graphs_release.md)  
- [knowledge_graphs_runbook.md](../../operations/knowledge_graphs_runbook.md)  
