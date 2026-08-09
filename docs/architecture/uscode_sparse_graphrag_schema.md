# ADR: U.S. Code Sparse GraphRAG v2 schema and identity

| Field | Value |
| --- | --- |
| Interface | `UsCodeSparseGraphRagReleaseSchema@2` |
| Task | `USCIR-002` |
| Status | accepted |
| Date proposed | 2026-08-09 |
| Date accepted | 2026-08-09 |
| Decision owners | legal-ir / foundation |
| Consulted | US Code Sparse GraphRAG plan; content-identity ADR; source policy; identity module |
| Source of truth | `ipfs_datasets_py/processors/legal_data/uscode_release_schema.py` |
| Last verified | 2026-08-09 |
| Supersedes | none (additive over legacy `uscode_parquet/*`) |
| Superseded by | none |
| Origin | Sealed plan decisions for legal ID, entry CID, 4,096 physical bounds, and vector-space identity (`USCIR-G010`) |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

The pinned baseline dataset [`justicedao/ipfs_uscode`](https://huggingface.co/datasets/justicedao/ipfs_uscode)
@ `75cfc5982dc3a6808614cd4eb9b4238f8f9308b8` mixes heterogeneous recovery JSON
with monolithic corpus, BM25, and embedding Parquet files. Blocking identity
problems include:

1. **Positional durable identity.** Legacy embeddings join on `row-N` /
   release-local offsets rather than content-addressed keys. Rebuilds and
   reordering silently corrupt joins.
2. **Missing model and release pins.** Embeddings are 384-dimensional with no
   model id, revision, pooling, or normalization policy. “Latest” or branch
   names are not reproducible provenance.
3. **Ambiguous “4,096 chunks”.** The same integer is easy to misread as a
   model-token window, a chunking policy, or a storage bound. The sealed plan
   defines 4,096 as the **physical rows/pointers** bound for retrieval units.
4. **Unsafe paths and weak digests.** Absolute local paths, traversal, and
   non-hex digests must fail closed before any remote client trusts a
   descriptor.
5. **Incomplete admission and provenance.** Canonical rows need admission
   disposition plus official-source receipts; recovery rows must not enter
   default corpus / BM25 / vector / graph counts.

Downstream tasks (shared artifact writers, Hub resolver, corpus materializer)
depend on one versioned contract for record shapes and fail-closed validation.

## Decision

We adopt **`publicus-ir-graphrag/v2`** as the release profile and implement its
schema and identity rules in
`ipfs_datasets_py/processors/legal_data/uscode_release_schema.py`
(schema version `uscode-sparse-graphrag-release-schema-v2`).

### 1. Durable identity vs release-local indexes

| Field | Role | Durable? |
| --- | --- | --- |
| `entry_cid` | Content address of the canonical retrieval record; **primary key** | Yes |
| `legal_id` | Stable citation-oriented identifier (`usc:<jurisdiction>:…`) independent of content version | Yes |
| `source_cid` | Content address of normalized source evidence | Yes (provenance) |
| `document_index` | Release-local optimization for shard layout and Dataset Viewer | **No** |

**Hard rule:** Positional tokens such as `row-12`, `row-N`, or using
`document_index` / embedding row offsets as the only join key are **rejected**
as durable identity (`PositionalIdentityError`). Citation parsing and
qualifier disambiguation remain in `uscode_identity` (file-disjoint); this
schema only enforces shape and the durable/non-durable split.

Duplicate `(title, section)` values are not collapsed at the schema layer:
appendix, note, edition, granule, and related qualifiers participate in
`legal_id` (enforced by the identity module; required present here).

### 2. Physical bounds (what 4,096 means)

`4,096` is the maximum number of **rows or pointers** in a physical retrieval
unit—not a default token window:

| Bound | Maximum |
| --- | ---: |
| Corpus / BM25-document / vector Parquet shard rows | 4,096 |
| BM25 posting-list pointers per cell | 4,096 |
| BM25 term rows per term shard | 4,096 |
| Graph adjacency pointers per page | 4,096 |
| Compact routing-index rows (unless a stricter schema applies) | 4,096 |
| Rows per vector centroid | 8,192 |
| Physical shards per centroid | 2 |

Model-token ceilings use **separately named** fields (`model_token_ceiling`,
`max_token_window`, …) and must declare `bound_kind=model_tokens`. Attaching
the bare value `4096` to ambiguous names such as `chunk_size`, `window_size`,
or `max_tokens` **without** an explicit token kind is rejected
(`AmbiguousBoundError`).

### 3. Immutable model and release references

Manifests, vector rows, centroids, and receipts must pin:

- dataset / source **revision** as a git commit SHA, SHA-256 digest, or CIDv1;
- embedding **model_id** + **model_revision** the same way;
- official **release_point** as an exact OLRC/GovInfo pin (never `latest`).

Mutable tokens (`latest`, `main`, `master`, `HEAD`, branch-like refs) raise
`MutableReferenceError`. Vector spaces are identified by an explicit
`vector_space_id` that binds model + revision (+ config); dimension alone does
not imply compatibility across releases.

### 4. Artifact descriptors and paths

Every manifest descriptor records:

- relative path, media type, row count, byte count, SHA-256, schema identifier;
- optional key range and centroid/routing metadata.

Paths must be normalized POSIX paths **relative to the release root**. Absolute
paths, drive letters, UNC paths, backslashes, empty / `.` / `..` segments, and
cache/VCS components are rejected (`ArtifactPathError`).

Digests are lowercase 64-hex SHA-256 (optional `sha256:` prefix) or CIDv1
base32. Malformed digests raise `InvalidDigestError`.

### 5. Record families

The schema defines versioned records for:

| Family | Record type | Notes |
| --- | --- | --- |
| Corpus | `CorpusRecord` | Requires durable identity + admission/provenance when admitted |
| BM25 postings | `PostingRecord` | Sorted `(term, entry_cid)` cells; ≤4,096 pointers |
| Vectors | `VectorRecord` | Pinned model; join on `entry_cid` only |
| Centroids | `CentroidRecord` | ≤8,192 rows, ≤2 shards; relative shard descriptors |
| Graph | `GraphNodeRecord`, `GraphEdgeRecord` | Deterministic node/edge CIDs |
| Adjacency | `AdjacencyRecord` | In/out pages; ≤4,096 edge pointers |
| Locators | `LocatorRecord` | Compact routing rows with relative paths + digests |
| Manifest | `ReleaseManifest` | Profile, pins, bounds, artifact list |
| Receipts | `ReceiptRecord` | Build/acquisition receipts bound to digests |
| Recovery | `RecoveryRecord` | Quarantine only; never `admission_status=admitted` |

Target layout (additive; legacy paths remain only under explicit compatibility
configs):

```text
README.md
manifest.json
release_metadata.json
data/corpus/part-*.parquet
data/bm25/documents/part-*.parquet
data/bm25/postings/part-*.parquet
data/vectors/centroid-*-part-*.parquet
data/graph/nodes/part-*.parquet
data/graph/edges/part-*.parquet
data/graph/adjacency/out/part-*.parquet
data/graph/adjacency/in/part-*.parquet
indexes/*-chunks-*.parquet
reports/admission.json
recovery/...
```

### 6. Admission and provenance (fail-closed)

Admitted corpus rows **must** carry:

- `admission_status`, `admission_reason`;
- `source_cid`, `release_point`, `source_checksum`, `verification_result`,
  `acquisition_time`.

Missing fields raise `MissingAdmissionProvenanceError`. Acquisition and
publication timestamps are **not** legal-currentness claims. Recovery and
excluded rows remain outside canonical counts until normalized and admitted
under this contract.

Official-source acquisition policy (proposed latest vs approved exact, mixed
vintages, per-title receipts) is owned by `uscode_source_policy`; this ADR
requires those provenance fields to be present and well-formed on admitted
rows.

## Alternatives considered

| Alternative | Why not chosen |
| --- | --- |
| Keep positional embedding joins for migration speed | Corrupts identity under reordering; plan forbids repacking unknown vectors as trusted |
| Allow `latest` / default branch as model or dataset pin | Non-reproducible; fails audit and remote thin-client guarantees |
| Treat 4,096 as both token window and row bound | Silent policy confusion; chunking and storage must remain separate |
| Absolute paths in descriptors for local debug | Leaks operator layout; breaks Hub-relative fetch and cache keys |
| Soft-warn on missing admission fields | Violates fail-closed acceptance; recovery would contaminate defaults |

## Consequences

### Positive

- Writers, resolvers, and evaluation gates share one fail-closed contract.
- Physical bounds and token ceilings cannot be silently confused.
- Legacy positional and unpinned artifacts cannot be labeled v2-valid.
- Recovery remains quarantined until it satisfies identity and admission rules.

### Negative / accepted costs

- Rebuild of embeddings and indexes is required; legacy files stay compatibility-only.
- Call sites must supply exact pins and provenance even in fixtures.
- Schema module does not perform Parquet I/O or Hub access (those are later tasks).

### Follow-on work

- `USCIR-006` — full `legal_id` parser/normalizer and collision fixtures.
- `USCIR-009` — shared bounded artifact writers consuming these descriptors.
- `USCIR-008` — corpus materializer and admission ledger.
- Publication remains gated by a human seal; this schema alone does not authorize live Hub mutation.

## Validation

Authoritative unit suite:

```bash
python -m pytest tests/unit/logic/legal_ir/test_uscode_release_schema.py -q
```

The suite must prove rejection of: positional durable identity, mutable
model/release references, ambiguous 4,096 fields, absolute artifact paths,
invalid digests, and missing admission/provenance fields—and accept minimal
valid corpus, posting, vector, centroid, graph, adjacency, locator, manifest,
receipt, and recovery records.
