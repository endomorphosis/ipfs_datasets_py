# Knowledge Graphs — Compatibility, Migration, and Deprecation Runbooks

**Program:** `KGP`  
**Task:** `KGP-034`  
**Policy:** `kg-compatibility/v1` (executable:
`ipfs_datasets_py.knowledge_graphs.compat`)  
**Goal:** `KGP-G100` (adoption)

## Purpose

This directory is the operator-facing publication of:

1. **Versioned compatibility tiers** (`T0`–`T3`) and adopt / adapt / deprecate
   dispositions for legacy graph classes and paths.
2. **Warning and removal windows** (package minor-release floor + calendar).
3. **Producer-specific prerequisites** before any corpus moves.
4. **Migration phases:** backup → dry-run → shadow → canary → cutover, with
   always-available **rollback**.
5. **Schema evolution**, **storage selection**, **UCAN setup**, and pointers
   to **on-call** procedures.

Existing producers remain authoritative until stage-6 corpus evidence passes.
No destructive in-place conversion of corpus artifacts.

## Document map

| Document | Contents |
| --- | --- |
| [compatibility.md](./compatibility.md) | Tiers, legacy map, warn/remove windows |
| [migration_runbook.md](./migration_runbook.md) | End-to-end phase runbook (backup → cutover/rollback) |
| [producers.md](./producers.md) | Producer-specific prerequisites and evidence |
| [schema_storage_ucan.md](./schema_storage_ucan.md) | Schema evolution, storage profiles, UCAN setup |
| [../../operations/knowledge_graphs_release.md](../../operations/knowledge_graphs_release.md) | Release, sign-off, on-call during cutover |
| [../../operations/knowledge_graphs_runbook.md](../../operations/knowledge_graphs_runbook.md) | Day-2 ops, backup/restore, alerts |
| [../../architecture/knowledge_graphs_compatibility.md](../../architecture/knowledge_graphs_compatibility.md) | Normative ADR (KGP-003) |

## Machine-readable policy

```python
from ipfs_datasets_py.knowledge_graphs.compat import (
    POLICY_VERSION,
    policy_dict,
    assert_policy_invariants,
    LEGACY_MAP,
    PRODUCER_MAP,
    removal_allowed,
    warn_legacy,
)

assert POLICY_VERSION == "kg-compatibility/v1"
assert_policy_invariants()
policy = policy_dict()  # JSON-serializable
```

Validation:

```bash
python -m pytest -q tests/unit/knowledge_graphs/test_compatibility_policy.py
```

## Non-negotiable rules

| ID | Rule |
| --- | --- |
| `MIG-1` | No producer or consumer migrates before stage-6 evidence for its corpus. |
| `MIG-2` | No in-place destructive conversion of corpus artifacts. |
| `MIG-3` | Caller-visible shadow results always come from the primary (legacy) path. |
| `MIG-4` | Rollback is catalog-head CAS to the last verified immutable revision. |
| `MIG-5` | Do **not** remove an import or data reader in the same release that first warns about it. |
| `MIG-6` | Minimum public-name warn period: **one minor release** (unless security receipt). |
| `MIG-7` | Production traffic uses `GraphService` + `GraphTarget` only (one-service rule). |
| `MIG-8` | Nested lift checkouts are fixture-only, never implementation source of truth. |

## Related code

| Area | Module |
| --- | --- |
| Compatibility policy | `ipfs_datasets_py.knowledge_graphs.compat` |
| Shadow dual-read | `ipfs_datasets_py.knowledge_graphs.migration.shadow` |
| Canary / rollback | `ipfs_datasets_py.knowledge_graphs.migration.canary` |
| Backup / restore / alerts | `ipfs_datasets_py.knowledge_graphs.operations` |
| UCAN contracts / enforcement | `ipfs_datasets_py.knowledge_graphs.auth` |
| Graph service | `ipfs_datasets_py.knowledge_graphs.service` |
