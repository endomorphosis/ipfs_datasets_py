# ADR: Federal Register Sparse GraphRAG v2 schema and identity-bound release contract

| Field | Value |
| --- | --- |
| Interface | `FederalRegisterSparseGraphRagReleaseSchema@2` |
| Task | `LCR-050` |
| Status | accepted |
| Date proposed | 2026-08-10 |
| Date accepted | 2026-08-10 |
| Decision owners | legal-ir / federal-foundation-schema |
| Consulted | Legal Corpora Reindex plan; US Code v2 schema; state-law v2 schema; content-identity ADR |
| Source of truth | `ipfs_datasets_py/processors/legal_data/federal_register_release_schema.py` |
| Last verified | 2026-08-10 |
| Supersedes | none (additive over legacy `justicedao/ipfs_federal_register` sample layout) |
| Superseded by | none |
| Origin | Sealed plan decisions for document-number identity, publication/correction identity, official URLs/hashes, text availability, physical 4,096 bounds, semantic-family closure, and immutable publication pins (`LCR-G100`) |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

The pinned baseline dataset [`justicedao/ipfs_federal_register`](https://huggingface.co/datasets/justicedao/ipfs_federal_register)
@ `720668ae016cc400916dda884c9005e03618edfa` is not a production-grade sparse
GraphRAG release. Blocking identity and layout problems include:

1. **Missing document-number / publication identity.** Legacy rows lack a
   stable `legal_id` that binds Federal Register document number and
   publication date independent of content version; correction and withdrawal
   relationships are not first-class.
2. **Empty or mismatched official URLs and hashes.** Baseline Parquet
   `source_url` fields are empty; JSON-LD conversion mismatched `url` /
   `sourceUrl`; official content hashes are absent.
3. **Text availability not dispositioned.** Hundreds of thousands of rows have
   empty text or abstract-only snippets while still appearing as full-text
   candidates. Metadata-only items must never masquerade as body text.
4. **Unsafe paths and weak pins.** Manifests may carry absolute local paths;
   model/dataset references may use mutable tokens (`latest`, `main`, `HEAD`).
5. **Incomplete semantic families.** A valid default release must close corpus,
   BM25 documents/postings, vectors, centroids, graph nodes/edges, in/out
   adjacency, locators, and the manifest itself—not a partial subset.
6. **Ambiguous 4,096.** Physical rows/pointers per retrieval unit must not be
   confused with model-token windows.

Downstream acquisition, materialization, evaluation, staging, and publication
tasks depend on one versioned, fail-closed contract for record shapes and
identity-bound release validation.

## Decision

We adopt **`federal-register-ir-graphrag/v2`** as the release profile and
implement its schema and identity rules in
`ipfs_datasets_py/processors/legal_data/federal_register_release_schema.py`
(schema version `federal-register-sparse-graphrag-release-schema-v2`).

The contract reuses the working US Code / state-law sparse GraphRAG method
(bounded Parquet families, term-routed BM25, pinned `thenlper/gte-small`
embeddings, centroid routing, legal/provenance graph, compact adjacency,
immutable-Hub pins) while specializing identity, date-partition layout, source
receipts, publication, and rollback for the cutoff-bound Federal Register
corpus.

### 1. Durable identity vs release-local indexes

| Field | Role | Durable? |
| --- | --- | --- |
| `entry_cid` | Content address of the canonical retrieval record; **primary key** | Yes |
| `legal_id` | Stable publication identity (`fr:<document_number>:<publication_date>[:qualifier…]`) independent of content version | Yes |
| `source_cid` | Content address of normalized official-source evidence | Yes (provenance) |
| `document_number` | Federal Register document number (`YYYY-NNNNN`) | Yes (publication identity) |
| `publication_date` | Official publication calendar date (`YYYY-MM-DD`) | Yes (publication identity) |
| `document_index` | Release-local optimization for shard layout and Dataset Viewer | **No** |

**Hard rule:** Positional tokens such as `row-12`, `row-N`, or using
`document_index` / embedding row offsets as the only join key are **rejected**
as durable identity (`PositionalIdentityError`).

`legal_id` document-number and publication-date segments must match the
corresponding corpus fields. Duplicate document numbers across content versions
are not collapsed: qualifiers (e.g. correction linkage) participate in
`legal_id` when needed.

### 2. Publication and correction identity

Publication identity binds:

- `document_number` (`YYYY-NNNNN`);
- `publication_date` (`YYYY-MM-DD`);
- `document_type` (`rule`, `proposed_rule`, `notice`, `presidential_document`,
  `correction`, `sunshine_act_meeting`, …);
- optional `year_month` partition key (`YYYY-MM`, derived from publication date
  when omitted).

Correction / withdrawal identity is explicit via:

| Field | Meaning |
| --- | --- |
| `correction_relation` | `none`, `corrects`, `corrected_by`, `withdraws`, `withdrawn_by`, `supersedes`, `superseded_by` |
| `related_document_number` | Target document number when relation is non-`none` |

Rules:

- non-`none` relations **require** `related_document_number`;
- `document_type=correction` **requires** a non-`none` relation;
- related document numbers without a relation are rejected.

Neither identity is collapsed into the other: a correcting document and the
corrected document remain separately addressable rows.

### 3. Official provenance, URLs, and hashes

Admitted corpus rows **must** carry:

- `admission_status`, `admission_reason`;
- `source_cid`, `release_point`, `source_checksum`, `verification_result`,
  `acquisition_time`;
- `official_source_url` (absolute http(s) on `federalregister.gov` or
  `govinfo.gov`);
- optional `official_html_url`, `official_pdf_url`, `official_xml_url` (same
  host allowlist);
- optional `official_content_hash` (SHA-256 of official body bytes);
- `acquisition_receipt_id`, `parser_version`;
- `document_number`, `publication_date`, `document_type`, `text_availability`;
- official `source_authority_class` (`official` or approved `exception`).

Secondary sources are quarantine evidence only. Missing fields raise
`MissingAdmissionProvenanceError` or `OfficialProvenanceError`. Acquisition and
publication timestamps are **not** legal-currentness claims.

### 4. Text availability

`text_availability` is a typed disposition, not a boolean:

| Value | Meaning |
| --- | --- |
| `full_text` / `html_body` / `xml_body` / `pdf_body` / `govinfo_body` | Usable official body present |
| `abstract_only` | Abstract only; not full body |
| `metadata_only` | Metadata admitted without body after attempt ledger |
| `unavailable` | Official alternatives lack usable body |
| `failed_final` | Body acquisition failed; **not** publication-success |

Rules for admitted rows:

- body-bearing dispositions require non-empty `text`;
- `failed_final` cannot be admitted;
- `metadata_only` must not carry long body text masquerading as full text.

A non-body disposition is allowed only after the attempt ledger proves every
official alternative has no usable body. Exclusion or quarantine cannot turn
an unresolved body failure into publication success.

### 5. Physical bounds (what 4,096 means)

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

### 6. Immutable model and release references

Manifests, vector rows, centroids, publication, and rollback receipts must pin:

- dataset / source **revision** as a git commit SHA, SHA-256 digest, or CIDv1;
- embedding **model_id** + **model_revision** the same way;
- official **release_point** as an exact edition/as-of pin (never `latest`);
- optional **observation_cutoff** UTC pin for cutoff-relative completeness.

Mutable tokens (`latest`, `main`, `master`, `HEAD`, branch-like refs) raise
`MutableReferenceError`. Vector spaces are identified by an explicit
`vector_space_id` that binds model + revision; dimension alone does not imply
compatibility across releases.

Previous public baseline pin retained for rollback:

`720668ae016cc400916dda884c9005e03618edfa`.

### 7. Artifact descriptors and paths

Every manifest descriptor records:

- relative path, media type, row count, byte count, SHA-256, schema identifier;
- optional key range, year/month, document type, and centroid/routing metadata.

Paths must be normalized POSIX paths **relative to the release root**. Absolute
paths, drive letters, UNC paths, backslashes, empty / `.` / `..` segments, and
cache/VCS components are rejected (`ArtifactPathError`).

Target layout (additive; year/month + document-type partitioned corpus):

```text
README.md
manifest.json
release_metadata.json
data/corpus/year_month=YYYY-MM/document_type=TYPE/part-*.parquet
data/bm25/documents/year_month=YYYY-MM/document_type=TYPE/part-*.parquet
data/bm25/postings/part-*.parquet
data/vectors/centroid-*-part-*.parquet
data/graph/nodes/part-*.parquet
data/graph/edges/part-*.parquet
data/graph/adjacency/out/part-*.parquet
data/graph/adjacency/in/part-*.parquet
indexes/*.parquet
receipts/acquire/year_month-YYYY-MM.json
reports/admission.json
reports/coverage.json
reports/quality.json
reports/reproducibility.json
recovery/...
```

Document-number locators and per-date-partition acquisition receipts are
mandatory companions. State-law jurisdiction partitions are intentionally not
used here.

### 8. Source receipts (date partitions)

Per-date-partition `SourceReceiptRecord` rows reconcile:

```text
enumerated = fetched + duplicate + excluded + quarantined + failed_final
```

with API totals, page cursors, response hashes, document-number lists, and
body-text disposition counts. `frontier_closed=true` requires `failed_final=0`.
Receipt artifacts use release-relative paths under `receipts/acquire/`.

Federal completeness is cutoff-relative: the observation cutoff is recorded on
receipts and the release manifest. Completeness is not a claim that a changing
daily register is permanently current.

### 9. Record families

| Family | Record type | Notes |
| --- | --- | --- |
| Corpus | `CorpusRecord` | Requires entry/legal/source identity + document-number/publication + official provenance + text availability when admitted |
| Source receipt | `SourceReceiptRecord` | Per-date-partition frontier reconciliation |
| BM25 postings | `PostingRecord` | Sorted `(term, entry_cid)` cells; ≤4,096 pointers |
| Vectors | `VectorRecord` | Pinned model; join on `entry_cid` only |
| Centroids | `CentroidRecord` | ≤8,192 rows, ≤2 shards; relative shard descriptors |
| Graph | `GraphNodeRecord`, `GraphEdgeRecord` | Deterministic node/edge CIDs; correction edges |
| Adjacency | `AdjacencyRecord` | In/out pages; ≤4,096 edge pointers |
| Locators | `LocatorRecord` | Compact routing rows with relative paths + digests + document-number |
| Descriptor | `ArtifactDescriptor` | Manifest entry binding path/digest/bounds |
| Manifest | `ReleaseManifest` | Profile, pins, bounds, artifact list, family closure |
| Build receipt | `ReceiptRecord` | Build/acquisition receipts bound to digests |
| Publication | `PublicationRecord` | Additive immutable public pin + prior pin |
| Rollback | `RollbackRecord` | Restore prior immutable pin without delete |
| Recovery | `RecoveryRecord` | Quarantine only; never `admission_status=admitted` |

### 10. Semantic-family closure

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

### 11. Publication and rollback (immutable pins)

Publication receipts bind:

- target dataset `justicedao/ipfs_federal_register` only;
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
| Trust old date-range registry / metadata.json counts | Baseline proves advertised and materialized counts disagree; full-text claims are false |
| Allow `latest` / default branch as model or dataset pin | Non-reproducible; fails audit and remote thin-client guarantees |
| Soft-warn on missing semantic families | Violates fail-closed acceptance; partial releases would look complete |
| Absolute paths in descriptors for local debug | Leaks operator layout; breaks Hub-relative fetch and cache keys |
| Reuse state-law `state:` legal_id shape | Federal Register needs document-number/publication identity and correction linkage |
| Treat abstract-only or empty body as full text | Plan forbids metadata-only masquerading as full text |
| Collapse corrections into corrected document rows | Loses independent publication identity and graph edges |

## Consequences

### Positive

- Writers, resolvers, evaluation gates, and publication/rollback receipts share
  one fail-closed contract specialized for Federal Register identity.
- Document number, publication/correction identity, official URLs/hashes, and
  text availability are schema-enforced rather than advisory.
- Physical bounds and token ceilings cannot be silently confused.
- Legacy unpinned, incomplete-family, or abstract-as-full-text layouts cannot
  be labeled v2-valid.
- Recovery and secondary sources remain quarantined until they satisfy identity
  and official-provenance rules.

### Negative / accepted costs

- Rebuild of embeddings, BM25, graph, and adjacency is required from a fresh
  official inventory rather than the old baseline.
- Call sites must supply exact pins, official URLs/hashes, and text
  dispositions even in fixtures.
- Schema module does not perform Parquet I/O, API acquisition, or Hub access
  (those are later tasks: `LCR-052`–`LCR-065`).

### Follow-on work

- Official inventory and completeness ledger (`LCR-048`, `LCR-049`).
- Gold set sealing (`LCR-051`).
- Cutoff-bound acquisition and identity normalization (`LCR-052`–`LCR-055`).
- BM25, vectors, graph, query, build, canary, and publication (`LCR-056`–`LCR-065`).

## Validation

Authoritative unit suite:

```bash
python -m pytest tests/unit/processors/legal_data/test_federal_register_release_schema.py -q
```

The suite must prove acceptance of minimal valid corpus (including correction),
source-receipt, posting, vector, centroid, graph, adjacency, locator,
descriptor, manifest, publication, and rollback records—and rejection of:
missing `entry_cid`/`legal_id`/`source_cid`, invalid document-number or
publication identity, non-official URLs, missing text-availability consistency,
mutable model/release references, absolute artifact paths, oversize
rows/pointers, incomplete semantic-family sets, and mutable publication pins.
