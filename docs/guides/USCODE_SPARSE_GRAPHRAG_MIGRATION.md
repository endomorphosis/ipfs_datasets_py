# US Code Sparse GraphRAG Migration Guide (USCIR-037)

Migrate clients and operators from the legacy `uscode_parquet/` monolith layout
to the sealed sparse GraphRAG profile `publicus-ir-graphrag/v2` without losing
compatibility, provenance, or rollback capability.

Operations daybook: [USCODE_SPARSE_GRAPHRAG_RUNBOOK.md](USCODE_SPARSE_GRAPHRAG_RUNBOOK.md).

---

## 1. Why migrate

The pinned baseline (`75cfc5982dc3a6808614cd4eb9b4238f8f9308b8` on
`justicedao/ipfs_uscode`) mixes heterogeneous recovery JSON with corpus
artifacts, lacks explicit Dataset Viewer configs, and stores embeddings with
positional joins and missing model identity. The v2 program:

- content-addresses rows by `entry_cid`;
- shards BM25, vectors, and graph under a 4,096-row bound;
- routes remote queries so only control-plane + selected shards download;
- quarantines recovery JSON away from the default viewer config;
- retains legacy files for a deprecation cycle (never deletes them on package).

Publication of the public dataset still requires a human seal. This guide covers
**client and packaging migration**, not autonomous Hub overwrite.

---

## 2. Profile and configuration map

| Config name | Role | Primary key | Default viewer? |
|---|---|---|---|
| `publicus-ir-graphrag/v2` | Sparse GraphRAG release | `entry_cid` | **Yes** |
| `legacy-uscode-parquet/v1` | Compatibility with monolith parquet | `ipfs_cid` | No |
| `recovery-quarantine/v1` | Quarantined recovery JSON | `recovery_id` | No |

Default Dataset Viewer must never include recovery paths or legacy monoliths.
Legacy and recovery remain **named** configs only.

### 2.1 Artifact layout (v2)

```text
README.md
manifest.json
release_metadata.json
dataset_configs.json
dataset_infos.json
data/corpus/part-*.parquet
data/bm25/documents/part-*.parquet
data/bm25/postings/part-*.parquet
data/vectors/centroid-*-part-*.parquet
data/graph/nodes/part-*.parquet
data/graph/edges/part-*.parquet
data/graph/adjacency/out/part-*.parquet
data/graph/adjacency/in/part-*.parquet
indexes/*
reports/admission.json
reports/quality.json
reports/reproducibility.json
reports/lineage.json          # verbose; not control plane
recovery/...                 # recovery-quarantine/v1 only
uscode_parquet/...           # legacy-uscode-parquet/v1 only
```

### 2.2 Legacy monolith paths (retained)

```text
uscode_parquet/laws.parquet
uscode_parquet/cid_index.parquet
uscode_parquet/laws_bm25.parquet
uscode_parquet/laws_embeddings.parquet
uscode_parquet/laws_knowledge_graph_entities.parquet
uscode_parquet/laws_knowledge_graph_relationships.parquet
```

Packaging **never deletes** these files. Migration is additive.

---

## 3. Identity and join-key migration

| Concern | Legacy | v2 requirement |
|---|---|---|
| Primary document key | Often `ipfs_cid` / positional row | `entry_cid` (content-addressed) |
| Embedding join | Positional index into embedding table | Join only on `entry_cid` + model identity |
| BM25 identity | Document index in monolith table | Document descriptors + postings with `entry_cid` |
| Graph nodes/edges | Monolith entity/relationship tables | Sharded nodes/edges/adjacency with durable IDs |
| Model pin | Frequently absent | Exact model id + revision + vector_space_id |
| Release authority | Implicit / mixed | Exact `release_point` (e.g. `us/pl/118/45`) |

**Hard rule:** never repack unknown legacy vectors as trusted v2 embeddings.
Regenerate from canonical text under a pinned model, or mark an explicit
regeneration disposition.

---

## 4. Client migration

### 4.1 Preferred: sealed query CLI / client

```bash
# Offline fixture root (no network)
python scripts/ops/legal_data/query_uscode_hf.py \
  --local-root /path/to/v2-release \
  --revision 75cfc5982dc3a6808614cd4eb9b4238f8f9308b8 \
  --fixture-mode \
  --json --trace \
  bm25 "5 U.S.C. § 552"
```

Python API surface (package):

```python
from ipfs_datasets_py.processors.legal_data.uscode_query import (
    UscodeQueryClient,
    LegalFilters,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    LocalRootTransport,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import QueryLimits

resolver = ImmutableHubResolver(
    repo_id="justicedao/ipfs_uscode",
    revision="75cfc5982dc3a6808614cd4eb9b4238f8f9308b8",
    transport=LocalRootTransport(root="/path/to/v2-release"),
)
client = UscodeQueryClient(resolver=resolver, limits=QueryLimits())
result = client.bm25_search("foia agency records", top_k=5)
# Always inspect result.fetch_trace for sparse-fetch proof
```

### 4.2 Stop doing these

| Anti-pattern | Replacement |
|---|---|
| `revision="main"` / `"latest"` | Immutable 40-hex SHA |
| Full Hub `snapshot_download` for one query | Sparse resolver + budgets |
| Positional embedding row join | `entry_cid` + vector_space_id |
| Reading recovery JSON as canonical law | Quarantine until admitted |
| Treating Hub upload time as “current law” | Bind and display `release_point` |
| Passing `HF_TOKEN=...` on argv | Environment / keyring only |

### 4.3 Filter and citation clients

Legal filters (`title`, `section`, `citation`, `version`, `legal_id`) are
first-class on the query CLI. Prefer `legal_id` / `entry_cid` for durable
identity; use citation strings for human-facing lookup only.

---

## 5. Builder and packaging migration

### 5.1 Build orchestration

```bash
python scripts/ops/legal_data/build_uscode_sparse_graphrag.py \
  --fixture-only \
  --plan-only \
  --titles 1,35 \
  --mode full \
  --json
```

Production title sets still require an approved release point pin
(`--release-point us/pl/118/45` by default). Delta mode needs prior/current
snapshots and explicit global BM25/cluster rebuild decisions.

### 5.2 HF release packaging

The additive packager (`ipfs_datasets_py.processors.legal_data.uscode_hf_release`)
emits:

- compact `manifest.json` + `release_metadata.json`;
- explicit viewer configs (default v2, legacy, recovery);
- descriptors for every artifact;
- admission / quality / reproducibility reports;
- verbose lineage **separate** from the control plane.

Legacy paths are listed for compatibility configs and are not deleted.

### 5.3 Staging (add-only)

```bash
python scripts/ops/legal_data/stage_uscode_sparse_graphrag.py \
  --fixture-only \
  --dry-run
```

Staging targets `stage/uscode-sparse-graphrag-v2` forked from the production
baseline revision. Forbidden: delete, force-push, visibility change, direct
`main` upload without a separate human publication seal.

---

## 6. Provenance fields required on admitted rows

Missing any of the following fails closed (`MissingAdmissionProvenanceError`
or equivalent admission rejection):

- `admission_status`, `admission_reason`
- `source_cid`, `release_point`, `source_checksum`
- `verification_result`, `acquisition_time`

`acquisition_time` and Hub publication timestamps record **package handling**.
They are **not** legal-currentness claims. See runbook §11.

---

## 7. Dataset Viewer migration

1. Advertise `publicus-ir-graphrag/v2` as the **only** default config.
2. Keep `legacy-uscode-parquet/v1` for one deprecation cycle of monolith
   consumers.
3. Keep `recovery-quarantine/v1` for heterogeneous recovery JSON.
4. Validate viewer configs offline with the sealed card fixture:
   `tests/fixtures/legal_ir/uscode_dataset_card.md`.
5. Reject any packaging change that reintroduces recovery JSON into the default
   config.

---

## 8. Rollback and dual-read strategy

During migration, operators may dual-read:

1. **v2 default** for new sparse GraphRAG clients.
2. **legacy config** for not-yet-migrated monolith consumers.
3. **baseline revision pin** as the rollback target if a candidate fails canary.

Rollback procedure summary (detail in the runbook):

1. Keep the failed candidate artifacts (do not delete).
2. Re-advertise the previous immutable revision + default config mapping.
3. Re-query offline; confirm fetch traces still verify.
4. Record rollback digests in the release-candidate / handoff receipts.

Legacy files remain on the branch for forensic and compatibility use.

---

## 9. Compatibility matrix

| Consumer | Before | After migration |
|---|---|---|
| Monolith parquet loaders | `uscode_parquet/*.parquet` | Use `legacy-uscode-parquet/v1` or migrate to v2 shards |
| Full-repo clone scripts | Entire Hub tree | Prefer sparse query client |
| Positional embedding pipelines | Row index join | Blocked as trusted v2; regenerate |
| Graph entity dump readers | Monolith KG tables | v2 graph shards + adjacency pages |
| “Latest law” dashboards | Upload timestamp | Must display `release_point` / edition |

---

## 10. Migration checklist

- [ ] Pin Hub revision to 40-hex; reject `main`/`latest`
- [ ] Switch primary key consumers to `entry_cid`
- [ ] Bind embedding model id + revision + normalization
- [ ] Route queries through budgets + fetch traces
- [ ] Confirm default viewer config excludes recovery and legacy monoliths
- [ ] Retain legacy paths; do not delete on package
- [ ] Run fixture build + query + stage dry-run from the runbook
- [ ] Document rollback target revision before any promotion request
- [ ] Treat publication date ≠ legal currentness in all user-facing copy

---

## 11. Validation

```bash
# Documentation contract (this task)
python -m pytest tests/unit/docs/test_uscode_sparse_runbook.py -q

# Packaging / stage / query unit gates
python -m pytest tests/unit/processors/legal_data/test_uscode_hf_release.py -q
python -m pytest tests/unit/scripts/test_stage_uscode_sparse_graphrag.py -q
python -m pytest tests/unit/scripts/test_query_uscode_hf.py -q
```

---

## 12. Related artifacts

| Artifact | Path |
|---|---|
| Dataset card fixture | `tests/fixtures/legal_ir/uscode_dataset_card.md` |
| Stage plan fixture | `tests/fixtures/legal_ir/uscode_stage_plan.json` |
| Manifest fixture | `tests/fixtures/legal_ir/uscode_manifest.json` |
| Gold set rationale | `docs/reports/uscode_goldset_rationale.md` |
| Baseline audit report | `docs/reports/uscode_sparse_graphrag_baseline.json` |
| Query CLI guide | `docs/guides/USCODE_SPARSE_QUERY_CLI.md` |
