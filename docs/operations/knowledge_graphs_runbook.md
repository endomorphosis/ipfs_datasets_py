# Knowledge Graphs — Operations & Disaster-Recovery Runbook

**Status:** active  
**Task:** `KGP-032`  
**Contract:** `kg-operations/v1`  
**Code:** `ipfs_datasets_py.knowledge_graphs.operations`

## Purpose

This runbook covers production operability for the knowledge-graph control
plane: structured observability, health probes, diagnostics, manifest repair
previews, immutable backup/restore, and on-call alert response.

Non-negotiable rules:

1. **Telemetry is redacted by default.** Graph property values, raw queries,
   UCAN tokens, signatures, and secrets never leave the process in logs,
   metrics labels, or diagnostic payloads.
2. **Repair never mutates without an explicit bounded plan.**  
   `apply_repair_plan(..., confirm=False)` is always a no-op. Applying requires
   `confirm=True` and a matching `plan_digest`. Catalog revision rows remain
   immutable; field-level fixes are journaled for restore/republish.
3. **Restore must prove identity.** A restore is successful only when
   revision ids, checksums, and query vectors match the backup manifest
   (`RestoreProof.ok is True`).

## Quick reference (Python)

```python
from pathlib import Path
from ipfs_datasets_py.knowledge_graphs.catalog import open_catalog
from ipfs_datasets_py.knowledge_graphs.operations import (
    build_default_health,
    run_diagnostics,
    create_backup,
    verify_backup,
    restore_backup,
    scrub_catalog_manifests,
    preview_repair,
    apply_repair_plan,
    get_default_telemetry,
    alert_catalog,
    log_ops_event,
)

catalog = open_catalog("/var/lib/kg/catalog.sqlite")

# Health
health = build_default_health(catalog=catalog, catalog_path=catalog.path)
assert health.liveness().alive
assert health.readiness().ready

# Diagnostics (catalog / WAL / shard / pin / cache)
report = run_diagnostics(catalog=catalog, tenant="acme")
print(report.overall_status, [s.to_dict() for s in report.sections])

# Manifest scrub + repair preview (no mutation)
scrub = scrub_catalog_manifests(catalog, tenant="acme")
plan = preview_repair(catalog, tenant="acme")
# Refused without confirm:
apply_repair_plan(catalog, plan, confirm=False)

# Immutable backup
backup = create_backup(catalog, Path("/var/backups/kg"), tenant="acme")
ok, issues = verify_backup(backup.path)
assert ok, issues

# Restore into a new catalog path and prove vectors
result = restore_backup(backup.path, Path("/var/lib/kg/catalog-restored.sqlite"))
assert result.ok and result.proof.ok
```

Validation command:

```bash
python -m pytest -q tests/integration/knowledge_graphs/test_operations.py
```

---

## Observability

### Structured logs

- Schema: `kg-ops-log/v1`
- Logger helper: `get_ops_logger()`, `log_ops_event()`, `OpsLogContext`
- Formatter: `OpsJSONFormatter` (single-line JSON)
- Correlation fields: `request_id`, `trace_id`, `span_id`, `tenant`,
  `graph_id`, `revision_id`, `operation`
- **Scrubbed by default:** keys in `REDACT_KEYS` (tokens, UCANs, query text,
  properties, payloads, secrets, …)

### Metrics and traces

- Schema: `kg-ops-telemetry/v1`
- In-process registry: `OpsMetrics` / `OpsTracer` via `OpsTelemetry`
- Prometheus text: `telemetry.metrics.export_prometheus()`
- Core series:
  - `kg_ops_operations_total{operation,status}`
  - `kg_ops_operation_duration_ms` (histogram; p50/p95/p99 in snapshot)
  - `kg_ops_liveness`, `kg_ops_readiness`
- Optional bridge to the OpenTelemetry SDK when installed; otherwise the
  in-process tracer still records spans for tests and local export.
- Labels are passed through `safe_labels()` (redacted + length-bounded).

### Recommended dashboards

| Panel | Signal |
| --- | --- |
| Availability | `kg_ops_liveness`, `kg_ops_readiness` |
| Ops error rate | `rate(kg_ops_operations_total{status="error"})` |
| Latency | p95 of `kg_ops_operation_duration_ms` by `operation` |
| Integrity | diagnostics findings (`missing_checksums`, unpinned heads) |
| DR | time since last `backup.create` success |

---

## Liveness and readiness

| Probe | Meaning | Failure action |
| --- | --- | --- |
| **Liveness** | Process running, not draining | Restart after capturing logs; do not loop-kill without diagnostics |
| **Readiness** | Catalog reachable, paths readable, optional cache OK | Remove from load balancer; fix underlying probe |

Wire probes with `build_default_health(catalog=..., catalog_path=..., hybrid_store=...)`.

HTTP mapping (when exposed by a service wrapper):

- `GET /healthz` → `registry.liveness().to_dict()`
- `GET /readyz` → `registry.readiness().to_dict()`

---

## Diagnostics

`run_diagnostics()` returns five sections:

| Section | Contents |
| --- | --- |
| `catalog` | Graph/revision/branch counts, missing checksums / pin roots |
| `pin` | Pin coverage for active branch heads |
| `shard` | Shard descriptor checksum/CID coverage from manifests |
| `wal` | WAL head presence, bounds, optional path size |
| `cache` | Hybrid/verified cache stats |

Capture a diagnostics report before any restart, GC execute, or restore.

```python
report = run_diagnostics(catalog=catalog, tenant="acme", wal=wal, hybrid_store=store)
Path("/tmp/kg-diagnostics.json").write_text(
    __import__("json").dumps(report.to_dict(), indent=2)
)
```

---

## Manifest scrub / verify / repair

### Scrub and verify

```python
from ipfs_datasets_py.knowledge_graphs.operations import (
    scrub_catalog_manifests,
    verify_manifest,
)

report = scrub_catalog_manifests(catalog, tenant="acme", graph_id="orders")
# report.ok, report.findings
```

`verify_manifest(dict)` validates a single revision manifest against
`GraphRevisionManifest` rules and optional expected revision/checksum.

### Repair preview (always dry-run)

```python
plan = preview_repair(catalog, tenant="acme", graph_id="orders")
assert plan.dry_run is True
print(plan.plan_id, plan.plan_digest, plan.to_dict()["action_count"])
```

Plans are bounded (`MAX_PLAN_ACTIONS`, default 1024) and content-addressed
via `plan_digest`.

### Apply (gated)

```python
# No-op — catalog untouched
apply_repair_plan(catalog, plan, confirm=False)

# Authorized apply: pin adds may land live; field fixes are journaled only
result = apply_repair_plan(
    catalog,
    plan,
    confirm=True,
    expected_plan_digest=plan.plan_digest,
    journal_path="/var/lib/kg/repair-journal.json",
)
```

**Do not** hand-edit SQLite revision rows. Revisions are immutable; journaled
corrections are applied by publishing a new revision or by restore from a
verified backup.

---

## Backup and restore

### RPO / RTO guidance

| Objective | Default guidance |
| --- | --- |
| RPO | ≤ 24h (alert `kg-ops-backup-stale`); tighter for multi-writer tenants |
| RTO | Restore + proof to a standby path, then atomic catalog swap / head CAS |

### Create an immutable backup

```python
backup = create_backup(catalog, "/var/backups/kg", tenant="acme")
ok, issues = verify_backup(backup.path)
assert ok, issues
# Record backup.manifest.backup_digest in the change ticket
```

Layout:

```text
<destination>/<backup_id>/
  backup_manifest.json   # digests + revision/checksum inventories
  catalog_export.json    # control-plane snapshot
  query_vectors.json     # per-branch revision/checksum/query fingerprints
```

Files are chmod'd read-only after write (best-effort local immutability).

### Restore and proof

```python
result = restore_backup(
    backup.path,
    "/var/lib/kg/catalog-restored.sqlite",
    replace_existing=False,
)
assert result.ok
assert result.proof.ok
assert result.proof.mismatches == []
# proof compares:
#   - revision_ids
#   - checksums
#   - query_vectors_digest and per-branch fingerprints
```

**Traffic cutover only after `RestoreProof.ok`.** Point production at the
restored catalog (or CAS branch heads to the verified revisions) and re-run
readiness + a golden query sample.

### Disaster recovery procedure

1. **Declare** the incident; freeze non-essential writers if integrity is in doubt.
2. **Capture** `run_diagnostics()` and recent structured logs (already redacted).
3. **Select** the newest backup with `verify_backup(path) == (True, [])`.
4. **Restore** to a *new* path (`replace_existing=False` first).
5. **Require** `result.proof.ok` — same revision ids, checksums, query vectors.
6. **Validate** readiness probes and a representative query set.
7. **Cut over** by swapping the catalog path / service config (or CAS heads).
8. **Record** `backup_id`, `backup_digest`, and proof in the incident ticket.
9. **Schedule** a post-incident backup from the recovered primary.

If proof fails (`kg-ops-restore-proof-failed`): **do not** serve traffic from
the restored path; try the previous verified backup.

---

## Pin / GC interaction

- GC defaults to dry-run and only collects abandoned staged objects
  (see `storage/gc.py`).
- Unpinned live heads fire `kg-ops-unpinned-heads`.
- Before any GC execute: run `diagnose_pins`, restore missing pins from
  revision `pin_root` / `manifest_cid`, and keep a verified backup.

---

## WAL / crash recovery

- Multi-phase WAL: INTENT → PREPARE → PUBLISH → COMPLETE (see transactions).
- On crash, recovery follows the phase matrix; incomplete publish must not
  expose partial heads.
- `diagnose_wal` reports head presence and bounds. Missing head under write
  traffic fires `kg-ops-wal-head-missing`.

---

## Alert response

### Severity handling

| Severity | Response |
| --- | --- |
| critical | Page on-call; remove instance from LB if readiness fails; freeze risky mutators |
| warning | Ticket within business hours; schedule repair/backup |
| info | Track in dashboard; no page |

### Alert catalog (machine-aligned)

These rules are defined in
`ipfs_datasets_py.knowledge_graphs.operations.alerts` and must stay
in sync with on-call dashboards.

#### `kg-ops-liveness-down` — KnowledgeGraphLivenessDown

- **Severity:** critical
- **Metric:** `kg_ops_liveness`
- **Condition:** `kg_ops_liveness == 0` (for 1m)
- **Impact:** All graph APIs unavailable from this instance.
- **Runbook section:** Liveness failure
- **Description:** Process liveness probe failed; service may be wedged or dead.
- **Recommended actions:**
  - Check process status and recent structured logs for fatal errors
  - Confirm no shutdown drain is in progress
  - Restart instance only after capturing diagnostics snapshot

#### `kg-ops-readiness-fail` — KnowledgeGraphReadinessFailed

- **Severity:** critical
- **Metric:** `kg_ops_readiness`
- **Condition:** `kg_ops_readiness == 0` (for 2m)
- **Impact:** Instance cannot safely serve traffic; catalog/cache/WAL may be unhealthy.
- **Runbook section:** Readiness failure
- **Description:** Readiness probes failed; instance should be removed from load balancers.
- **Recommended actions:**
  - Inspect readiness probe details (catalog, cache, path)
  - Run run_diagnostics() and capture the report
  - Do not promote canary traffic until ready==true

#### `kg-ops-catalog-checksum-drift` — KnowledgeGraphCatalogChecksumDrift

- **Severity:** critical
- **Metric:** `kg_ops_diagnostics`
- **Condition:** `diagnostics.catalog.missing_checksums > 0 OR finding CATALOG_CHECKSUM_DRIFT` (for 5m)
- **Impact:** Readers may disagree on revision identity; queries can return inconsistent vectors.
- **Runbook section:** Manifest integrity / repair
- **Description:** Catalog revision checksums diverge from manifest identity.
- **Recommended actions:**
  - Run scrub_catalog_manifests and preview_repair (dry-run)
  - Never apply repair without confirm=True and matching plan_digest
  - Prefer restore from last verified immutable backup if drift is widespread

#### `kg-ops-unpinned-heads` — KnowledgeGraphUnpinnedHeads

- **Severity:** warning
- **Metric:** `diagnostics.pin.heads_without_pin`
- **Condition:** `heads_without_pin > 0` (for 15m)
- **Impact:** GC dry-run may flag live data; risk of data loss if GC forced.
- **Runbook section:** Pin / GC diagnostics
- **Description:** Active branch heads lack pin roots and may be GC-eligible incorrectly.
- **Recommended actions:**
  - Run diagnose_pins and re-pin heads from revision pin_root/manifest_cid
  - Confirm GC remains dry-run until pins restored

#### `kg-ops-wal-head-missing` — KnowledgeGraphWALHeadMissing

- **Severity:** warning
- **Metric:** `diagnostics.wal`
- **Condition:** `wal_head_cid_present == false AND write_traffic > 0` (for 10m)
- **Impact:** Crash recovery may be incomplete; recent transactions at risk.
- **Runbook section:** WAL / crash recovery
- **Description:** WAL head empty or path missing after writes expected.
- **Recommended actions:**
  - Inspect diagnose_wal section
  - Halt writers if publish phase incomplete
  - Follow multi-phase recovery matrix (INTENT/PREPARE/PUBLISH/COMPLETE)

#### `kg-ops-backup-stale` — KnowledgeGraphBackupStale

- **Severity:** warning
- **Metric:** `kg_ops_operations_total{operation="backup.create",status="ok"}`
- **Condition:** `time since last successful backup > RPO` (for 1h)
- **Impact:** Disaster recovery may exceed RPO; data loss window expands.
- **Runbook section:** Backup and restore
- **Description:** No successful immutable backup within the configured RPO window.
- **Recommended actions:**
  - Run create_backup against the primary catalog
  - verify_backup on the artifact
  - Store backup off-box with the backup_digest recorded in the change ticket

#### `kg-ops-restore-proof-failed` — KnowledgeGraphRestoreProofFailed

- **Severity:** critical
- **Metric:** `kg_ops_operations_total{operation="backup.restore",status="error"}`
- **Condition:** `restore proof.ok == false` (for 0m)
- **Impact:** Restored catalog is not safe for traffic; identity drift possible.
- **Runbook section:** Backup and restore
- **Description:** Restore completed but revision/checksum/query vector proof failed.
- **Recommended actions:**
  - Do not point production at the restored catalog
  - Compare RestoreProof mismatches
  - Retry restore from a different verified backup_digest

#### `kg-ops-error-rate-high` — KnowledgeGraphOpsErrorRateHigh

- **Severity:** warning
- **Metric:** `kg_ops_operations_total`
- **Condition:** `rate(errors) / rate(total) > 0.05` (for 10m)
- **Impact:** Degraded caller experience; possible partial outage.
- **Runbook section:** Alert response
- **Description:** Elevated error rate on operational or query path.
- **Recommended actions:**
  - Inspect structured logs (redacted) for error_code spikes
  - Correlate with OTel spans (operation duration p95)
  - Check readiness and diagnostics before scaling out

#### `kg-ops-p95-latency-regression` — KnowledgeGraphP95LatencyRegression

- **Severity:** warning
- **Metric:** `kg_ops_operation_duration_ms`
- **Condition:** `p95 > baseline_p95 * 1.10` (for 30m)
- **Impact:** Release gate risk; sustained regression blocks promotion.
- **Runbook section:** Alert response
- **Description:** p95 operation latency regresses more than 10% vs baseline.
- **Recommended actions:**
  - Compare histogram snapshot against labelled baseline
  - Check cache hit rate and shard routing diagnostics
  - Hold release if unexplained >10% p95 regression

Export the machine-readable catalog:

```python
from ipfs_datasets_py.knowledge_graphs.operations import alert_catalog
catalog = alert_catalog()  # schema kg-ops-alerts/v1
```

---

## Security notes

- Never paste UCAN tokens, raw Cypher/SPARQL, or node property bags into tickets.
- Prefer `receipt_cid` / digests from the auth audit module (KGP-022).
- Backup artifacts contain control-plane metadata (revision ids, checksums,
  manifest JSON). Protect backup storage with the same tenant isolation as the
  primary catalog; do not commit backups to git.

---

## Related components

| Area | Module |
| --- | --- |
| Catalog | `ipfs_datasets_py.knowledge_graphs.catalog` |
| Manifests | `ipfs_datasets_py.knowledge_graphs.contracts.manifest` |
| WAL / MVCC | `ipfs_datasets_py.knowledge_graphs.transactions` |
| Hybrid cache / GC | `ipfs_datasets_py.knowledge_graphs.storage.hybrid`, `.gc` |
| Auth audit | `ipfs_datasets_py.knowledge_graphs.audit` |
| Operations | `ipfs_datasets_py.knowledge_graphs.operations` |
