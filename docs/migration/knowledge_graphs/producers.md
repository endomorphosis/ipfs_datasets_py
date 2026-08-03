# Producer-Specific Migration Prerequisites

**Task:** `KGP-034`  
**Inventory:** `docs/architecture/knowledge_graphs_inventory.md`  
**Executable:** `ipfs_datasets_py.knowledge_graphs.compat.PRODUCER_MAP`

No existing producer or consumer migrates before stage-6 evidence passes for
its corpus. Nested lift checkouts and non-canonical CVE producer trees are
**fixture-only**.

## Shared prerequisites (all producers)

| Gate | Requirement |
| --- | --- |
| Stage 6 | Differential + representative workload receipts on labelled environment |
| Identity | Explicit `GraphTarget`; no ambient empty graphs |
| Backup | Verified immutable backup digest on the change ticket |
| Security | UCAN allow + deny/expiry/revocation/replay negative proofs when enforcement is on |
| Surfaces | Python / CLI / MCP / MCP++ vectors green for the storage profile in use |
| Policy | Deprecation windows respected if the release removes public shims |

```python
from ipfs_datasets_py.knowledge_graphs.compat import get_producer, list_producer_ids

for pid in list_producer_ids():
    p = get_producer(pid)
    print(pid, p.migration_risk, p.required_evidence)
```

---

## `cvefixes_security_ir_graphrag`

| Field | Value |
| --- | --- |
| Display name | CVEfixes Security IR GraphRAG |
| Owner | lift_coding (artifacts); nested CVE producer code is **fixture-only** |
| Migration risk | **high** |
| Default storage profile | `hybrid` |
| Fixture-only producer | **yes** |

### Required evidence

- `differential_reader_parity`
- `shard_index_integrity`
- `backup_restore_proof`
- `load_soak_chaos_receipts`
- `ucan_negative_proof`

### Operator notes

- Multi-GB artifacts (`release-with-original-v2` ~1.5G, source Parquet ~1.2G).
- Prefer staged import into a new `graph_id` under a lab tenant before canary.
- Do not promote nested producer modules as the implementation source of truth;
  port to the canonical tree after control-plane readiness.
- Shadow label: `cvefixes`. Canary allowlist should start with a single
  non-production graph id.

---

## `skillcenter_ir_graphrag`

| Field | Value |
| --- | --- |
| Display name | SkillCenter Intent IR GraphRAG |
| Owner | canonical `ipfs_datasets_py` (`logic/intent_ir/graphrag`) |
| Migration risk | **medium** |
| Default storage profile | `hybrid` |

### Required evidence

- `schema_v2_v3_compat`
- `graph_vector_bm25_parity`
- `differential_reader_parity`
- `backup_restore_proof`

### Operator notes

- Release schema v3 with v2 read compatibility must stay green during canary.
- Hybrid layout: CID-keyed Parquet + BM25 + optional FAISS.
- Cutover only after graph/vector/BM25 parity receipts are bound to the current
  tree.

---

## `two11_retrieval_package`

| Field | Value |
| --- | --- |
| Display name | 211-AI retrieval package knowledge graph |
| Owner | `211-AI` |
| Migration risk | **medium** |
| Default storage profile | `hybrid` |

### Required evidence

- `manifest_cid_alignment`
- `differential_reader_parity`
- `traversal_community_workloads`
- `backup_restore_proof`

### Operator notes

- Counts: 48,851 nodes / 648,958 edges; 22,638 documents/embeddings.
- Manifest CID must remain the identity anchor for package consumers.
- Coordinate browser GraphRAG projection cutover separately (see below).

---

## `two11_browser_graphrag`

| Field | Value |
| --- | --- |
| Display name | 211-AI browser GraphRAG export |
| Owner | `211-AI` |
| Migration risk | **low** |
| Default storage profile | `parquet` |

### Required evidence

- `cid_alignment_with_retrieval_package`
- `smoke_shard_parity`

### Operator notes

- Small projection; must stay CID-aligned with the retrieval package build.
- Prefer canary after retrieval package shadow is green, not before.

---

## `supervisor_objective_graph`

| Field | Value |
| --- | --- |
| Display name | Agent supervisor objective graph |
| Owner | `ipfs_accelerate_py` |
| Migration risk | **low** |
| Default storage profile | `parquet` |

### Required evidence

- `kind_extensibility`
- `provenance_roundtrip`

### Operator notes

- Supervisor remains authoritative for objective identity.
- Rapid incremental changes: prefer short canary windows and frequent
  verified-head refresh.

---

## `supervisor_code_evidence_graph`

| Field | Value |
| --- | --- |
| Display name | Supervisor code-evidence / AST graphs |
| Owner | `ipfs_accelerate_py` |
| Migration risk | **low** |
| Default storage profile | `parquet` |

### Required evidence

- `blob_immutability`
- `path_projection_parity`

### Operator notes

- Content-addressed blobs; rollback is head CAS only.
- AST index schema version must be recorded on the revision manifest.

---

## Sign-off template

Record on the release / change ticket:

```text
Producer: <producer_id>
Owner: <owner>
Storage profile: <parquet|ipfs_ipld|ipfs_kit|hybrid>
Backup id / digest: <...>
Completed phases: prerequisites, backup, dry_run, shadow, canary
Evidence ids: <list>
Shadow metrics snapshot: <cid or path>
Canary allowlist: <tenant/graph_id,...>
Verified heads: <revision_id,...>
UCAN negative proof: <receipt_cid or N/A>
Cutover approved by: <name> @ <timestamp>
```

Machine check for cutover readiness:

```python
from ipfs_datasets_py.knowledge_graphs.compat import can_enter_phase

ok = can_enter_phase(
    "cutover",
    completed_phases=["prerequisites", "backup", "dry_run", "shadow", "canary"],
    producer_id="skillcenter_ir_graphrag",
    evidence=[
        "schema_v2_v3_compat",
        "graph_vector_bm25_parity",
        "differential_reader_parity",
        "backup_restore_proof",
    ],
)
assert ok
```
