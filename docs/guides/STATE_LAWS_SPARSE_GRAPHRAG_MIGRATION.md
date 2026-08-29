# State Laws Sparse GraphRAG Migration Guide (LCR-045)

Migrate clients and operators from the legacy `STATE-*.parquet` /
`state_laws.parquet` monolith layout to the sealed sparse GraphRAG profile
`state-laws-ir-graphrag/v2` without losing compatibility, provenance, or
rollback capability.

Both the new public pin and the previous public pin remain independently
queryable. Legacy configuration is **explicit** (a named Dataset Viewer
config, never the default). Rollback is a bounded pointer move and is
reversible.

Operations daybook: [STATE_LAWS_SPARSE_GRAPHRAG_RUNBOOK.md](STATE_LAWS_SPARSE_GRAPHRAG_RUNBOOK.md).

---

## 1. Why migrate

The pinned previous public revision
(`42f0546acc7c6cd55627eaf51fb820d5613b9021` on `justicedao/ipfs_state_laws`)
is the frozen Hugging Face / local baseline (LCR-001):

- the default Dataset Viewer canonical config is **Iowa-only**, not the
  exact 51-jurisdiction set;
- Viewer embeddings are a stale sparse sample with **zero CID overlap**
  against the canonical table;
- per-state Parquet totals 212,103 rows with documented truncations;
- CA and DC summaries are missing;
- embeddings frequently lack model identity and join positionally;
- recovery / mixed artifacts can leak into the default viewer.

The v2 program:

- content-addresses rows by `entry_cid`;
- admits exactly 50 postal state codes plus `DC`;
- shards BM25, vectors, and graph under a 4,096-row bound;
- routes remote queries so only control-plane + selected shards download;
- quarantines recovery JSON away from the default viewer config;
- retains legacy files for a deprecation cycle (never deletes them on package);
- advertises `state-laws-ir-graphrag/v2` as the only default config.

Publication of the public dataset still requires a human seal. This guide
covers **client and packaging migration**, not autonomous Hub overwrite.

---

## 2. Profile and configuration map

Legacy configuration is explicit. It is a **named** Viewer config, never
the default, and it is retained for one deprecation cycle.

| Config name | Role | Primary key | Default viewer? |
|---|---|---|---|
| `state-laws-ir-graphrag/v2` | Sparse GraphRAG release (all 51 including DC) | `entry_cid` | **Yes** |
| `legacy-state-laws-parquet/v1` | Compatibility with `STATE-*.parquet` / `state_laws.parquet` monoliths | `ipfs_cid` | **No** (explicit, named only) |
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
data/corpus/jurisdiction=*/part-*.parquet
data/bm25/documents/jurisdiction=*/part-*.parquet
data/bm25/postings/part-*.parquet
data/vectors/centroid-*-part-*.parquet
data/vectors/centroids/part-*.parquet
data/graph/nodes/part-*.parquet
data/graph/edges/part-*.parquet
data/graph/adjacency/out/part-*.parquet
data/graph/adjacency/in/part-*.parquet
indexes/locators/part-*.parquet
reports/admission.json
reports/quality.json
reports/reproducibility.json
reports/lineage.json          # verbose; not control plane
recovery/...                 # recovery-quarantine/v1 only
STATE-*.parquet              # legacy-state-laws-parquet/v1 only
state_laws.parquet           # legacy-state-laws-parquet/v1 only
```

### 2.2 Legacy monolith paths (retained)

```text
STATE-AL.parquet … STATE-WY.parquet
STATE-DC.parquet
state_laws.parquet
```

Packaging **never deletes** these files. Migration is additive and proceeds
without deleting legacy data. The legacy config advertises the globs
`STATE-*.parquet` and `state_laws.parquet` and the path prefix `STATE-`.

### 2.3 Dual pins (both remain queryable)

| Role | Immutable revision | Default config at that pin |
|---|---|---|
| Previous public pin (rollback target) | `42f0546acc7c6cd55627eaf51fb820d5613b9021` | Baseline Viewer (IA-only canonical; use only as rollback / forensic pin) |
| New public pin (current advertisement) | Checked LCR-042 `public_revision` | `state-laws-ir-graphrag/v2` (exact 51, including DC) |

Clients that have not yet migrated keep reading the previous pin **or** the
named `legacy-state-laws-parquet/v1` config on the new pin. New clients pin
the new SHA and the v2 config. Neither tree is deleted when advertisement
moves.

---

## 3. Identity and join-key migration

| Concern | Legacy | v2 requirement |
|---|---|---|
| Primary document key | Often `ipfs_cid` / positional row / filename | `entry_cid` (content-addressed) |
| Jurisdiction identity | `state` field; DC often opt-in or omitted | Exact 51 including `DC`; no extra/missing codes |
| Embedding join | Positional index into embedding table | Join only on `entry_cid` + model identity |
| BM25 identity | Document index in monolith table | Document descriptors + postings with `entry_cid` |
| Graph nodes/edges | Monolith entity/relationship tables (when present) | Sharded nodes/edges/adjacency with durable IDs |
| Model pin | Frequently absent | Exact model id + revision + vector_space_id |
| Combined table | `state_laws.parquet` built from the requested subset | Combined default config equals the deduped 51-jurisdiction union |
| Release authority | Implicit / mixed / Hub upload time | Exact `release_point` (`state-laws/v2/2026-08-10`) |

**Hard rule:** never repack unknown legacy vectors as trusted v2 embeddings.
Regenerate from canonical text under a pinned model, or mark an explicit
regeneration disposition. Never treat a one-state overwrite as the combined
release.

---

## 4. Client migration

### 4.1 Preferred: sealed query CLI / client

```bash
# Offline fixture root (no network)
python scripts/ops/legal_data/query_state_laws_hf.py \
  --local-root /path/to/v2-release \
  --revision "$STATE_LAWS_PUBLIC_SHA" \
  --fixture-mode \
  --json --trace \
  bm25 "disclosure" \
  --jurisdiction DC
```

Query the previous pin without switching clients:

```bash
python scripts/ops/legal_data/query_state_laws_hf.py \
  --repo-id justicedao/ipfs_state_laws \
  --revision 42f0546acc7c6cd55627eaf51fb820d5613b9021 \
  --json --trace \
  bm25 "disclosure"
```

Python API surface (package):

```python
from ipfs_datasets_py.processors.legal_data.state_laws_query import (
    StateLawsQueryClient,
    StateLawsFilters,
    open_state_laws_query_client,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    LocalRootTransport,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import QueryLimits

public_revision = "<40-hex public_revision from checked LCR-042 receipt>"
resolver = ImmutableHubResolver(
    repo_id="justicedao/ipfs_state_laws",
    revision=public_revision,
    transport=LocalRootTransport(root="/path/to/v2-release"),
)
client = StateLawsQueryClient(resolver=resolver, limits=QueryLimits(), fixture_only=True)
result = client.bm25_search(
    "disclosure",
    top_k=5,
    filters=StateLawsFilters.from_mapping({"jurisdiction": "DC"}),
)
# Always inspect result.fetch_trace for sparse-fetch proof
```

### 4.2 Stop doing these

| Anti-pattern | Replacement |
|---|---|
| `revision="main"` / `"latest"` | Immutable 40-hex SHA (new or previous pin) |
| Full Hub `snapshot_download` for one query | Sparse resolver + budgets |
| Positional embedding row join | `entry_cid` + vector_space_id |
| Reading recovery JSON as canonical law | Quarantine until admitted |
| Treating Hub upload time as “current law” | Bind and display `release_point` |
| Passing a Hub token on argv | Environment / keyring only |
| Loading `state_laws.parquet` as the default 51-set | Use `state-laws-ir-graphrag/v2` or the named legacy config on purpose |
| Defining `all` as 50 states with DC opt-in | Exact 51 including DC |

### 4.3 Filter and citation clients

Legal filters (`jurisdiction`, `code`, `citation`, `legal_id`, `title`,
`chapter`, `section`, `edition`, `kind`) are first-class on the query CLI.
Prefer `legal_id` / `entry_cid` for durable identity; use citation strings
for human-facing lookup only. Always include DC when the consumer claims
“all jurisdictions”.

---

## 5. Builder and packaging migration

### 5.1 Build orchestration

```bash
python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py \
  --validation-only \
  --check
```

Production title/jurisdiction sets still require the approved release point
pin (`state-laws/v2/2026-08-10`). Partial checkpoints cannot promote.

### 5.2 HF release packaging

The additive packager (`ipfs_datasets_py.processors.legal_data.state_laws_hf_release`)
emits:

- compact `manifest.json` + `release_metadata.json`;
- explicit viewer configs (default v2, **legacy**, recovery);
- descriptors for every artifact;
- admission / quality / reproducibility reports;
- verbose lineage **separate** from the control plane.

Legacy paths are listed for the compatibility config and are not deleted.
`include_legacy_config=True` is the sealed default.

### 5.3 Staging (add-only)

```bash
python scripts/ops/legal_data/stage_state_laws_hf_release.py \
  --dry-run --release-root "$STATE_LAWS_RELEASE_ROOT"
python scripts/ops/legal_data/stage_state_laws_hf_release.py --check-receipt
```

Staging targets `stage/state-laws-sparse-graphrag-v2` forked from the
previous public pin. Forbidden: delete, force-push, visibility change,
direct `main` upload without a separate human publication seal.
Branch creation and the staging commit use two distinct approvals and two
canonical runtime authorizations. Neither approval can be reused for the
other write. The live LCR-041 canary then redownloads the returned immutable
staging revision into an empty cache and measures BM25, vector, hybrid, graph,
filter, and cache probes before a main seal can be assembled.

---

## 6. Provenance fields required on admitted rows

Missing any of the following fails closed (`MissingAdmissionProvenanceError`
or equivalent admission rejection):

- `admission_status`, `admission_reason`
- `source_cid`, `release_point`, `source_checksum`
- `verification_result`, `acquisition_time`

`acquisition_time` and Hub publication timestamps record **package handling**.
They are **not** legal-currentness claims. See runbook §14.

---

## 7. Dataset Viewer migration

1. Advertise `state-laws-ir-graphrag/v2` as the **only** default config.
2. Keep `legacy-state-laws-parquet/v1` for one deprecation cycle of monolith
   consumers. This is the explicit legacy configuration.
3. Keep `recovery-quarantine/v1` for heterogeneous recovery JSON.
4. Reject any packaging change that reintroduces recovery JSON or
   `STATE-*.parquet` into the default config.
5. Confirm the default combined config contains all 51 jurisdictions
   (including DC), not an Iowa-only overwrite.

---

## 8. Rollback and dual-read strategy

During migration, operators may dual-read:

1. **v2 default** on the new pin for sparse GraphRAG clients.
2. **legacy config** (`legacy-state-laws-parquet/v1`) for not-yet-migrated
   monolith consumers on the new pin.
3. **previous public pin** as the rollback / forensic target.

Rollback procedure summary (detail in the runbook):

1. Keep the new (or failed-candidate) artifacts (do not delete).
2. Re-advertise the previous immutable revision + documented config mapping.
3. Re-query **both** pins offline or via pinned Hub revision; confirm fetch
   traces still verify.
4. Recover by re-advertising the new pin. Rollback is the reverse pointer
   move — bounded and recoverable.
5. Record both pins and the forbidden operation set in
   `docs/reports/legal_corpora_reindex/rollback_rehearsal.json`.

Legacy files remain on the branch for forensic and compatibility use.

Offline rehearsal:

```bash
python scripts/ops/legal_data/rehearse_state_laws_release_rollback.py --check
```

---

## 9. Compatibility matrix

| Consumer | Before | After migration |
|---|---|---|
| Monolith parquet loaders | `STATE-*.parquet` / `state_laws.parquet` | Use `legacy-state-laws-parquet/v1` or migrate to v2 shards |
| Full-repo clone scripts | Entire Hub tree | Prefer sparse query client |
| Positional embedding pipelines | Row index join | Blocked as trusted v2; regenerate |
| “All states” dashboards that omit DC | 50 codes / opt-in DC | Exact 51 including DC |
| Iowa-only Viewer consumers | Baseline default config | Must pin v2 default on the new SHA, or keep the previous pin on purpose |
| “Latest law” dashboards | Upload timestamp | Must display `release_point` / edition |

---

## 10. Migration checklist

- [ ] Pin Hub revision to 40-hex; reject `main`/`latest`
- [ ] Confirm both the new pin and the previous pin remain queryable
- [ ] Switch primary key consumers to `entry_cid`
- [ ] Bind embedding model id + revision + normalization
- [ ] Route queries through budgets + fetch traces
- [ ] Confirm default viewer config excludes recovery and legacy monoliths
- [ ] Confirm `legacy-state-laws-parquet/v1` is advertised and is **not** default
- [ ] Retain legacy paths; do not delete on package
- [ ] Confirm default combined config is all 51 including DC, not IA only
- [ ] Run fixture build + query + rollback rehearsal from the runbook
- [ ] Document rollback target revision before any promotion request
- [ ] Treat publication date ≠ legal currentness in all user-facing copy

---

## 11. Validation

```bash
# Rollback / dual-pin / legacy-config / board-diagnostic contract (this task)
python scripts/ops/legal_data/rehearse_state_laws_release_rollback.py --check

# Public pin + Viewer (dependency LCR-043)
python scripts/ops/legal_data/check_state_laws_public_release.py --require-public-pin --check
```

---

## 12. Related artifacts

| Artifact | Path |
|---|---|
| Operations runbook | `docs/guides/STATE_LAWS_SPARSE_GRAPHRAG_RUNBOOK.md` |
| Rollback rehearsal receipt | `docs/reports/legal_corpora_reindex/rollback_rehearsal.json` |
| Publication receipt | `docs/reports/legal_corpora_reindex/publication_receipt.json` |
| Public canary | `docs/reports/legal_corpora_reindex/public_canary.json` |
| Baseline audit | `docs/reports/legal_corpora_reindex/baseline.json` |
| Query contract | `docs/reports/legal_corpora_reindex/query_contract.json` |
| Dataset card fixture | `tests/fixtures/legal_ir/state_laws_dataset_card.md` |
