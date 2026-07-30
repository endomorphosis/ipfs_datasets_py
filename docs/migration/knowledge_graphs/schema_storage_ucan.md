# Schema Evolution, Storage Selection, and UCAN Setup

**Task:** `KGP-034`  
**Related contracts:** `kg-service-contract/v1`, `kg-ucan-contract/v1`,
manifest / shard schemas under `ipfs_datasets_py.knowledge_graphs.contracts`

## Schema evolution

### Principles

1. **Revisions are immutable.** Field-level corrections are journaled and
   applied by publishing a **new** revision (or restore from verified backup).
2. **Readers stay backward-compatible for one published schema generation**
   where the inventory declares compat (e.g. SkillCenter release v3 reads v2).
3. **Writers emit the newest ratified schema version** for the graph kind.
4. **No silent up-conversion of live heads** during canary; conversion, if any,
   produces a new revision under a new or allowlisted graph id.
5. **v1 sharded-CAR remains readable** while v2 manifests land
   (`search_graph_data_sharded_car` adopt/adapt).

### Evolution checklist

| Step | Action |
| --- | --- |
| 1 | Document the schema id + version on the revision manifest |
| 2 | Add golden fixtures for old and new shapes |
| 3 | Prove dual-read parity (shadow) on a sample corpus |
| 4 | Canary a single graph id on the new schema revision |
| 5 | Expand only after differential receipts |
| 6 | Deprecate old **writer** paths under `kg-compatibility/v1` windows |

### Compatibility matrix (informative)

| Area | Compat expectation |
| --- | --- |
| GraphTarget / lifecycle envelopes | Exact `kg-service-contract/v1` |
| SkillCenter HF release | v3 primary; v2 read path retained until removal window |
| CVEfixes release / graph / ontology | versioned per inventory; no mix-and-match shards |
| Sharded CAR | v1 hash-modulo readable; v2 rendezvous additive |
| Browser GraphRAG | `schemaVersion: 1` aligned with retrieval package CID |

### Repair vs evolution

- **Repair** (ops): `preview_repair` / gated `apply_repair_plan` — does not
  invent a new graph schema; journals field fixes for republish.
- **Evolution**: explicit new schema version + new revision publication.

---

## Storage selection

Closed set (must match `GraphTarget` / catalog / manifests):

| Profile | Use when | Notes |
| --- | --- | --- |
| `parquet` | Analytical corpora, local/lab reproducibility, HF-style shards | **Default** (`DEFAULT_STORAGE_PROFILE`) |
| `ipfs_ipld` | Content-addressed block graphs with direct IPLD DAGs | CID-native linking |
| `ipfs_kit` | Production pin/fetch via `ipfs_kit_py` cluster integration | Requires kit availability |
| `hybrid` | Parquet + vector/BM25 + sharded CAR/IPFS (SkillCenter, CVE, 211) | Typical GraphRAG producers |

```python
from ipfs_datasets_py.knowledge_graphs.compat import (
    STORAGE_PROFILES,
    DEFAULT_STORAGE_PROFILE,
    resolve_storage_profile,
    validate_storage_profile,
    STORAGE_PROFILE_GUIDANCE,
    get_producer,
)

assert "hybrid" in STORAGE_PROFILES
assert resolve_storage_profile(None) == DEFAULT_STORAGE_PROFILE == "parquet"
validate_storage_profile("ipfs_kit")

producer = get_producer("skillcenter_ir_graphrag")
profile = producer.storage_profile_default  # "hybrid"
print(STORAGE_PROFILE_GUIDANCE[profile])
```

### Selection rules

| Rule | Statement |
| --- | --- |
| `STOR-1` | Record `storage_profile` on graph create / open when non-default. |
| `STOR-2` | Do not change profile on a live head without a new revision + evidence. |
| `STOR-3` | All four profiles must pass the same contract suite for T0 certification. |
| `STOR-4` | Canary graphs should use the producer default profile unless A/B testing
  profiles with explicit dual-run evidence. |
| `STOR-5` | Ambient MCP/CLI defaults must not select T3 fixture paths as storage. |

### Profile on GraphTarget

```text
kg://acme/skills/branches/main          # profile from catalog / create params
storage_profile="hybrid"                # explicit on GraphTarget / open
```

---

## UCAN setup

**Contract:** `kg-ucan-contract/v1`  
**Modules:** `ipfs_datasets_py.knowledge_graphs.auth.contracts`,
`ipfs_datasets_py.knowledge_graphs.auth.service`  
**Enforcement:** `GraphAuthorizationService` injected as
`GraphService(authorizer=...)` (Python and CLI share the same policy).

### Abilities (closed set)

```text
graph/list | graph/read | graph/query | graph/write
graph/admin | graph/pin | graph/delegate
```

### Resource grammar

```text
kg://<tenant>/<graph_id>
kg://<tenant>/<graph_id>/branches/<branch>
kg://<tenant>/<graph_id>/revisions/<revision>
```

### Caveats (closed keys)

```text
branch | revision | query | property | row | byte | depth
time | audience | count
```

Plus storage-profile / mutation-count caveats when issued via MCP++ Profile C
shapes (see plan § MCP++ and UCAN). Every link must satisfy resource
containment, ability attenuation, and monotonic caveat attenuation.

### Setup checklist (environment)

| Step | Action |
| --- | --- |
| 1 | Install / configure MCP++ UCAN delegation or wallet grants used by the host |
| 2 | Construct `GraphAuthorizationService` with revocation set + replay store |
| 3 | Inject as `authorizer=` on `GraphService` / `Client` open path |
| 4 | Issue least-privilege chains: prefer `graph/query` + branch/row/byte bounds for readers |
| 5 | Bind audience and expiry; never mint unbounded admin tokens for canary |
| 6 | Run allow path + negative suite: deny, expiry, revocation, replay, attenuation break |
| 7 | Confirm audit receipts are redacted (no raw UCAN, properties, or query text) |
| 8 | Store `receipt_cid` / digests on the change ticket — not tokens |

### Minimal Python wiring

```python
from ipfs_datasets_py.knowledge_graphs.service import GraphService
from ipfs_datasets_py.knowledge_graphs.auth.service import GraphAuthorizationService

authorizer = GraphAuthorizationService(
    # revocation_store=..., replay_store=..., audit_emitter=...
)
service = GraphService.open(catalog_path, authorizer=authorizer)
# All lifecycle ops fail closed before catalog lookup when tokens are invalid.
```

### Canary / cutover UCAN notes

- Canary traffic uses the **same** authorizer as baseline; do not disable UCAN
  to “make canary green.”
- Rollback does not require re-issuing tokens if resource URIs are unchanged;
  still re-check expiry before resuming writers.
- Shadow comparison must not log UCAN material (ops redaction defaults).

### Negative proof evidence (release)

Required for producers that list `ucan_negative_proof` (e.g. CVEfixes):

| Case | Expected |
| --- | --- |
| Missing token (when required) | deny + audit receipt |
| Expired | deny |
| Revoked proof CID | deny |
| Replay / reused nonce | deny |
| Ability escalation attempt | deny |
| Cross-tenant resource | deny |

---

## On-call pointer

Day-2 alerts, backup RPO/RTO, and incident steps live in:

- `docs/operations/knowledge_graphs_runbook.md`
- `docs/operations/knowledge_graphs_release.md` § On-call during cutover

During migration windows, treat `kg-ops-readiness-fail`,
`kg-ops-restore-proof-failed`, and security/correctness canary stops as
**page-worthy** even if baseline severity is warning.
