# ADR: State-law Sparse GraphRAG v2 schema and identity-bound release contract

| Field | Value |
| --- | --- |
| Interface | `StateLawsSparseGraphRagReleaseSchema@2` |
| Task | `LCR-004` |
| Status | accepted |
| Date proposed | 2026-08-10 |
| Date accepted | 2026-08-10 |
| Decision owners | legal-ir / foundation |
| Consulted | Legal Corpora Reindex plan; US Code v2 schema; content-identity ADR |
| Source of truth | `ipfs_datasets_py/processors/legal_data/state_laws_release_schema.py` |
| Last verified | 2026-08-10 |
| Supersedes | none (additive over legacy `justicedao/ipfs_state_laws` sample layout) |
| Superseded by | none |
| Origin | Sealed plan decisions for entry/legal/source identity, official provenance, physical 4,096 bounds, semantic-family closure, and immutable publication pins (`LCR-G010`) |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

The pinned baseline dataset [`justicedao/ipfs_state_laws`](https://huggingface.co/datasets/justicedao/ipfs_state_laws)
@ `42f0546acc7c6cd55627eaf51fb820d5613b9021` is not a production-grade sparse
GraphRAG release. Blocking identity and layout problems include:

1. **Positional and sample identity.** Viewer configs collapse to single-state
   samples; durable joins cannot depend on filenames, row offsets, or
   requested-scope completion flags.
2. **Missing official provenance.** Rows lack consistent `source_cid`, official
   URL, acquisition receipt, parser version, and exact release/as-of pins.
3. **Unsafe paths and weak pins.** Manifests may carry absolute local paths;
   model/dataset references may use mutable tokens (`latest`, `main`, `HEAD`).
4. **Incomplete semantic families.** A valid default release must close corpus,
   BM25 documents/postings, vectors, centroids, graph nodes/edges, in/out
   adjacency, locators, and the manifest itself—not a partial subset.
5. **Ambiguous 4,096.** Physical rows/pointers per retrieval unit must not be
   confused with model-token windows.

Downstream acquisition, materialization, evaluation, staging, and publication
tasks depend on one versioned, fail-closed contract for record shapes and
identity-bound release validation.

## Decision

We adopt **`state-laws-ir-graphrag/v2`** as the release profile and implement
its schema and identity rules in
`ipfs_datasets_py/processors/legal_data/state_laws_release_schema.py`
(schema version `state-laws-sparse-graphrag-release-schema-v2`).

The contract reuses the working US Code sparse GraphRAG method (bounded
Parquet families, term-routed BM25, pinned `thenlper/gte-small` embeddings,
centroid routing, legal/provenance graph, compact adjacency, immutable-Hub
pins) while specializing identity, jurisdiction partitioning, source receipts,
publication, and rollback for the 51-jurisdiction state-law corpus.

### 1. Durable identity vs release-local indexes

| Field | Role | Durable? |
| --- | --- | --- |
| `entry_cid` | Content address of the canonical retrieval record; **primary key** | Yes |
| `legal_id` | Stable citation-oriented identifier (`state:<jurisdiction>:<code_family>:<path…>`) independent of content version | Yes |
| `source_cid` | Content address of normalized official-source evidence | Yes (provenance) |
| `document_index` | Release-local optimization for shard layout and Dataset Viewer | **No** |

**Hard rule:** Positional tokens such as `row-12`, `row-N`, or using
`document_index` / embedding row offsets as the only join key are **rejected**
as durable identity (`PositionalIdentityError`).

`legal_id` jurisdiction segments must belong to the exact 51-code set
(50 postal state codes + `DC`). Duplicate citations are not collapsed across
editions, appendices, notes, code families, or source units.

### 2. Official provenance and admission

Admitted corpus rows **must** carry:

- `admission_status`, `admission_reason`;
- `source_cid`, `release_point`, `source_checksum`, `verification_result`,
  `acquisition_time`;
- `official_source_url`, `acquisition_receipt_id`, `parser_version`;
- `jurisdiction`, `code_family`;
- official `source_authority_class` (`official` or approved `exception`).

Secondary sources are quarantine evidence only. Missing fields raise
`MissingAdmissionProvenanceError` or `OfficialProvenanceError`. Acquisition and
publication timestamps are **not** legal-currentness claims.

Per-jurisdiction `SourceReceiptRecord` rows reconcile:

```text
discovered = fetched + excluded + quarantined + failed_final
```

with duplicates tracked separately. `frontier_closed=true` requires
`failed_final=0`. Receipt artifacts use release-relative paths under
`receipts/scrape/`.

### 3. Physical bounds (what 4,096 means)

`4,096` is the maximum number of **rows or pointers** in a physical retrieval
unit—not a default token window:

| Bound | Maximum |
| --- | ---: |
| Corpus / BM25-document / vector Parquet shard rows | 4,096 |
| BM25 posting-list pointers per cell | 4,096 |
| BM25 term rows per term shard | 4,096 |
| Graph adjacency pointers per page | 4,096 |
| Compact routing-index rows | 4,096 |
| Rows per vector centroid | 8,192 |
| Physical shards per centroid | 2 |

Model-token ceilings use **separately named** fields and must declare
`bound_kind=model_tokens`. Attaching bare `4096` to ambiguous names such as
`chunk_size` or `window_size` without an explicit token kind is rejected
(`AmbiguousBoundError`).

Default embedding contract:

- model_id: `thenlper/gte-small`
- model_revision: `17e1f347d17fe144873b1201da91788898c639cd`
- dimension: 384 (mean pooling, L2 normalization at build time)

### 4. Immutable model and release references

Manifests, vector rows, centroids, publication, and rollback receipts must pin:

- dataset / source **revision** as a git commit SHA, SHA-256 digest, or CIDv1;
- embedding **model_id** + **model_revision** the same way;
- official **release_point** as an exact edition/as-of pin (never `latest`).

Mutable tokens (`latest`, `main`, `master`, `HEAD`, branch-like refs) raise
`MutableReferenceError`. Vector spaces are identified by an explicit
`vector_space_id` that binds model + revision; dimension alone does not imply
compatibility across releases.

Previous public baseline pin retained for rollback:

`42f0546acc7c6cd55627eaf51fb820d5613b9021`.

### 5. Artifact descriptors and paths

Every manifest descriptor records:

- relative path, media type, row count, byte count, SHA-256, schema identifier;
- optional key range, jurisdiction, and centroid/routing metadata.

Paths must be normalized POSIX paths **relative to the release root**. Absolute
paths, drive letters, UNC paths, backslashes, empty / `.` / `..` segments, and
cache/VCS components are rejected (`ArtifactPathError`).

Target layout (additive; jurisdiction-partitioned corpus/BM25 documents):

```text
README.md
manifest.json
release_metadata.json
data/corpus/jurisdiction=XX/part-*.parquet
data/bm25/documents/jurisdiction=XX/part-*.parquet
data/bm25/postings/part-*.parquet
data/vectors/centroid-*-part-*.parquet
data/graph/nodes/part-*.parquet
data/graph/edges/part-*.parquet
data/graph/adjacency/out/part-*.parquet
data/graph/adjacency/in/part-*.parquet
indexes/*.parquet
receipts/scrape/jurisdiction-XX.json
reports/admission.json
reports/coverage.json
reports/quality.json
reports/reproducibility.json
recovery/...
```

### 6. Record families

| Family | Record type | Notes |
| --- | --- | --- |
| Corpus | `CorpusRecord` | Requires entry/legal/source identity + official provenance when admitted |
| Source receipt | `SourceReceiptRecord` | Per-jurisdiction frontier reconciliation |
| BM25 postings | `PostingRecord` | Sorted `(term, entry_cid)` cells; ≤4,096 pointers |
| Vectors | `VectorRecord` | Pinned model; join on `entry_cid` only |
| Centroids | `CentroidRecord` | ≤8,192 rows, ≤2 shards; relative shard descriptors |
| Graph | `GraphNodeRecord`, `GraphEdgeRecord` | Deterministic node/edge CIDs |
| Adjacency | `AdjacencyRecord` | In/out pages; ≤4,096 edge pointers |
| Locators | `LocatorRecord` | Compact routing rows with relative paths + digests |
| Descriptor | `ArtifactDescriptor` | Manifest entry binding path/digest/bounds |
| Manifest | `ReleaseManifest` | Profile, pins, bounds, artifact list, family closure |
| Build receipt | `ReceiptRecord` | Build/acquisition receipts bound to digests |
| Publication | `PublicationRecord` | Additive immutable public pin + prior pin |
| Rollback | `RollbackRecord` | Restore prior immutable pin without delete |
| Recovery | `RecoveryRecord` | Quarantine only; never `admission_status=admitted` |

### 7. Semantic-family closure

A default release is **closed** only when every required semantic family is
present in the manifest artifact list:

- `corpus`
- `bm25_documents`
- `bm25_postings`
- `vectors`
- `centroids`
- `graph_nodes`
- `graph_edges`
- `graph_adjacency_out`
- `graph_adjacency_in`
- `locator_index`
- `manifest`

Missing any required family raises `SemanticFamilyClosureError`. Recovery is
intentionally outside the default set and must not contaminate default Viewer
counts. Incoming and outgoing adjacency are both mandatory.

### 8. Publication and rollback (immutable pins)

Publication receipts bind:

- target dataset `justicedao/ipfs_state_laws` only;
- immutable `staging_revision` and `public_revision`;
- previous public pin;
- exact `manifest_digest`;
- `additive_only=true`.

Rollback receipts bind distinct immutable `from_revision` / `to_revision` pins
and the manifest digest of the restored candidate. Mutable branch names are
rejected. This schema alone does **not** authorize live Hub mutation;
authorization remains a separate operator seal.

## Alternatives considered

| Alternative | Why not chosen |
| --- | --- |
| Keep filename/`success`-registry completion | Baseline proves filenames and requested-scope success are not full coverage |
| Allow `latest` / default branch as model or dataset pin | Non-reproducible; fails audit and remote thin-client guarantees |
| Soft-warn on missing semantic families | Violates fail-closed acceptance; partial releases would look complete |
| Absolute paths in descriptors for local debug | Leaks operator layout; breaks Hub-relative fetch and cache keys |
| Reuse US Code `usc:` legal_id shape unchanged | State codes need jurisdiction/code-family/path identity and exact 51-set checks |
| Collapse secondary sources into admitted corpus | Plan requires official authority or documented exception only |

## Consequences

### Positive

- Writers, resolvers, evaluation gates, and publication/rollback receipts share
  one fail-closed contract.
- Physical bounds and token ceilings cannot be silently confused.
- Legacy sample, unpinned, or incomplete family layouts cannot be labeled
  v2-valid.
- Recovery and secondary sources remain quarantined until they satisfy identity
  and official-provenance rules.

### Negative / accepted costs

- Rebuild of embeddings, BM25, graph, and adjacency is required.
- Call sites must supply exact pins and official provenance even in fixtures.
- Schema module does not perform Parquet I/O, scraping, or Hub access (those
  are later tasks).

### Follow-on work

- Completeness oracle and frontier audits (`LCR-003`, `LCR-005`).
- Canonical corpus materializer and bounded artifact writers.
- Staging canary, authorized public upload, and dual-release verification.

## Validation

Authoritative unit suite:

```bash
python -m pytest tests/unit/processors/legal_data/test_state_laws_release_schema.py -q
```

The suite must prove acceptance of minimal valid corpus, source-receipt,
posting, vector, centroid, graph, adjacency, locator, descriptor, manifest,
publication, and rollback records—and rejection of: missing
`entry_cid`/`legal_id`/`source_cid`, non-official provenance on admitted rows,
mutable model/release references, absolute artifact paths, oversize
rows/pointers, incomplete semantic-family sets, and mutable publication pins.
