# US Code Sparse GraphRAG Improvement Plan

Status: execution-ready supervisor plan  
Board namespace: `uscode-sparse-graphrag-v1`  
Task prefix: `USCIR-`  
Goal prefix: `USCIR-G`  
Target package: `ipfs_datasets_py`  
Target dataset: [`justicedao/ipfs_uscode`](https://huggingface.co/datasets/justicedao/ipfs_uscode)  
Baseline date: 2026-08-09  
Baseline dataset revision: `75cfc5982dc3a6808614cd4eb9b4238f8f9308b8`

## 1. Outcome

Deliver an additive, reproducible `publicus-ir-graphrag/v2` release of the U.S. Code that can be queried directly from a pinned Hugging Face revision without cloning the full repository. The release will provide:

1. a canonical, provenance-rich legal corpus;
2. a sorted BM25 inverted index and compact term-range routing indexes;
3. normalized, model-bound embeddings grouped by deterministic semantic centroids;
4. physical Parquet shards containing at most 4,096 rows;
5. a statutory/citation/provenance knowledge graph plus a BM25-backed lexical overlay;
6. compact incoming and outgoing graph adjacency indexes;
7. lexical, dense, hybrid, neighbor, bounded graph-walk, and embedding-guided graph-walk queries that fetch only routed artifacts from Hugging Face;
8. deterministic incremental rebuilds, signed/pinned release metadata, compatibility configurations for the current files, evaluation gates, and rollback instructions.

The package changes and dataset migration are one program, but publication is deliberately gated. Autonomous agents may implement, test, build, and stage a candidate release. They may not overwrite the public Hugging Face dataset, rotate credentials, or remove legacy artifacts without a human-approved publication seal.

## 2. Decisions that remove ambiguity

### 2.1 What “4,096 chunks” means

`4,096` is the maximum number of rows or pointers in a physical retrieval unit:

- corpus, BM25-document, and vector Parquet artifact: at most 4,096 rows;
- BM25 posting-list cell: at most 4,096 document pointers;
- BM25 term-range artifact: at most 4,096 term rows;
- graph adjacency page: at most 4,096 edge pointers;
- compact routing-index artifact: at most 4,096 routing rows unless its schema documents a stricter bound.

Text segmentation is a separate policy. It must preserve legal semantic boundaries (title/chapter/section/subsection), record character and token offsets, and use a configurable model-token ceiling. A 4,096-token text window is allowed only when the selected embedding model supports it; it must never be silently confused with the 4,096-row storage bound.

### 2.2 Sparse versus centroid routing

Centroids do not route BM25 postings. The system has two bounded retrieval paths:

- sparse lexical retrieval tokenizes the query and selects lexicographically sorted BM25 term shards from a term-range index;
- dense retrieval embeds the query, ranks vector centroids, downloads the selected centroid shards, and performs exact cosine scoring within those shards.

Hybrid retrieval late-fuses the independently normalized rankings. This preserves BM25 semantics while achieving the requested sparse remote I/O: only a small set of metadata and data shards is downloaded.

### 2.3 Graph use of BM25

The BM25 postings are the canonical lexical graph overlay. The release must not blindly materialize every term-document pair as a durable graph edge: the legacy US Code index contains 13,602,252 document-term pairs, so doing so would dominate the legal graph. Instead:

- term nodes are addressable through the BM25 vocabulary;
- term-to-document traversal resolves through posting shards;
- document-to-document lexical relationships may be materialized as a deterministic, scored, bounded `BM25_NEIGHBOR_OF` projection;
- the durable graph is reserved for legal structure, citations, authority, amendments, transfers, repeals, source lineage, and unresolved-reference evidence.

This supports the patent-style lexical graph contract without turning a sparse index into an unnecessarily large edge table.

### 2.4 Embedding compatibility

Vector dimensions alone do not make vector spaces compatible. The reference releases use different representations: the patent release uses a 256-dimensional hashed projection, CVEfixes uses a pinned 384-dimensional MiniLM model, and SkillCenter uses a 384-dimensional GTE model. The legacy US Code file is 384-dimensional but records no model or revision. Therefore:

- regenerate US Code embeddings with one selected, pinned model revision;
- record model, revision, pooling, normalization, input-field policy, input hash, and configuration CID;
- embed each query with the exact model named by the release manifest;
- late-fuse across releases unless all participating releases have explicitly declared the same vector-space identifier.

## 3. Evidence baseline

### 3.1 Current US Code dataset

At the pinned baseline revision, the repository has 556 files and is approximately 1.019 GB. It has no README or explicit dataset-card configurations, and Hugging Face Dataset Viewer cannot consistently infer a schema because heterogeneous recovery JSON is mixed with corpus artifacts.

The current artifacts are legacy monoliths:

| Artifact | Rows | Approximate size | Blocking issue |
|---|---:|---:|---|
| `laws.parquet` | 60,077 | 374.3 MB | 60,068 canonical rows plus 9 recovery rows without CIDs; one row group |
| `cid_index.parquet` | 60,068 | 6.1 MB | no release/control-plane contract |
| `laws_bm25.parquet` | 60,068 | 199.6 MB | document term arrays, not a sorted inverted index |
| `laws_embeddings.parquet` | 185,563 | 140.7 MB | positional `row-N` identity; unknown model/revision |
| KG entities | 180,257 | 9.7 MB | only title/document/section structure |
| KG relationships | 120,136 | 10.8 MB | only `IN_TITLE` and `HAS_SECTION` |

The 60,068 canonical records span Titles 1 through 52 and 54. Every canonical `date_modified` value is 2024 even though the repository was modified in 2026, so publication time is not a legal-currentness claim. The existing rows already expose more useful graph evidence—including 105,055 U.S.C. citation occurrences, 234,393 public-law occurrences, chapter information, subsections, and legislative history—but the current graph does not use it.

The existing BM25 table uses `k1=1.5`, `b=0.75`, and per-document term-frequency arrays. It has no tokenizer identity, title/body field separation, or term-range routing. The embeddings use 185,563 chunks with 1–454 chunks per document, but they cannot be trusted for migration because the model and normalization policy are absent and the join key is positional rather than content-addressed.

### 3.2 Reference implementations to reuse

| Release | What to reuse | What not to copy blindly |
|---|---|---|
| [`patent-legal-ir-graphrag`](https://huggingface.co/datasets/justicedao/patent-legal-ir-graphrag) @ `845669408081f1334c54519d2bb7df6bf780ccd5` | `publicus-ir-graphrag/v1` artifact families, term-range BM25, BM25 vocabulary exposed to the graph, dataset card configurations | its one-shard 256-d hashed vector layout does not demonstrate large-scale semantic clustering |
| [`cvefixes-security-ir-graphrag`](https://huggingface.co/datasets/Publicus/cvefixes-security-ir-graphrag) @ `6fd5918bed34f8851430e74a149502587a953fe2` | deterministic balanced spherical k-means, model pinning, 4,096-row vector shards, 8,192 rows/centroid, at most two shards/centroid, similarity sorting | its security-domain graph ontology |
| [`skillcenter-ir`](https://huggingface.co/datasets/Publicus/skillcenter-ir) @ `2cc11a73403d03c0679ffa909c893ef6a850048a` | direct-Hub resolver, descriptor verification, compact routing indexes, recursive clustering, bounded adjacency, fetch traces, semantic graph walk | its skill ontology and vector model without legal-domain evaluation |

Primary code archaeology targets in this repository are:

- `ipfs_datasets_py/logic/intent_ir/graphrag/skillcenter_hf_release.py`;
- `ipfs_datasets_py/logic/security_ir/cvefixes/hf_vector_layout.py`;
- `ipfs_datasets_py/logic/security_ir/cvefixes/hf_bm25.py`;
- `ipfs_datasets_py/logic/security_ir/cvefixes/hf_graph_layout.py`;
- `ipfs_datasets_py/logic/security_ir/cvefixes/hf_complete_source.py`;
- `scripts/ops/intent_ir/query_skillcenter_hf.py`;
- `scripts/ops/security_ir/query_cvefixes_security_ir.py`;
- the patent public-release builder and query implementation when it lands on the target branch.

The shared behavior should move into a domain-neutral remote GraphRAG substrate. US Code code should supply legal normalization, field weights, filters, ontology, and evaluation policy rather than copy thousands of lines from another domain.

## 4. Target release contract

### 4.1 Identity and provenance

Each admitted retrieval row must carry:

- `entry_cid`: content address of the canonical retrieval record and primary key;
- `legal_id`: stable citation-oriented identifier independent of content version;
- `source_cid`: content address of normalized source evidence;
- title, chapter, section, subsection, appendix/schedule/granule identifiers where present;
- official source URL, package/granule identifier, release point, source checksum, acquisition time, and verification result;
- effective/as-of and observed-at dates with explicit unknown values rather than inferred currentness;
- `document_index` only as a release-local optimization, never as durable identity;
- admission/exclusion status and reason.

Duplicate `(title, section)` values must not be collapsed. Appendix, note, edition, granule, and source identity participate in `legal_id` construction. The nine heterogeneous recovery records move to an explicit recovery/quarantine configuration and cannot enter canonical counts until normalized and assigned valid identities.

### 4.2 Official-source acquisition

Generalize the exact release-point and exclusion contracts already used by the Title 35 processor to all U.S. Code titles. A build must select one declared OLRC/GovInfo release point, record per-title receipts, fail closed on mixed unapproved vintages, checkpoint title acquisition, and support deterministic resume. “Latest” discovery may propose a release but cannot be the final provenance value.

The package must retain a distinction between the codified U.S. Code, uncodified public laws, legislative history, and proof/logic artifacts. Retrieval output is a research aid; the release metadata must not represent it as authoritative legal advice or a substitute for an official source.

### 4.3 Artifact layout

The target repository adds, rather than replaces, these v2 families:

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
indexes/corpus_chunks-*.parquet
indexes/bm25_document_chunks-*.parquet
indexes/bm25_keyword_shards-*.parquet
indexes/vector_chunks-*.parquet
indexes/graph_node_chunks-*.parquet
indexes/graph_edge_chunks-*.parquet
indexes/graph_out_adjacency-*.parquet
indexes/graph_in_adjacency-*.parquet
reports/admission.json
reports/quality.json
reports/reproducibility.json
recovery/...
```

Every descriptor in `manifest.json` records relative path, media type, row count, byte count, SHA-256, schema identifier, key range, and optional centroid/routing metadata. Paths must be normalized, relative, and confined to the release root. The manifest records the source revision, package version, build configuration CID, tokenizer, BM25 parameters, embedding vector-space identifier, graph ontology version, and all determinism seeds.

Legacy `uscode_parquet/*` remains available through explicitly named compatibility configurations for at least one deprecation cycle. The default configuration points only to a coherent v2 corpus and must pass Dataset Viewer schema checks.

### 4.4 BM25 index

The legal BM25 implementation will:

1. define a versioned NFKC/case-folding tokenizer with deterministic citation and section-symbol handling;
2. preserve field-specific lengths and term frequencies;
3. start evaluation with `k1=1.2`, `b=0.75`, and explicit weights for title, heading, citation, body, and notes rather than silently inheriting legacy values;
4. emit documents sorted by primary key and postings sorted by `(term, entry_cid)`;
5. split long posting lists into bounded 4,096-pointer rows;
6. emit term shards of at most 4,096 term rows and a compact inclusive term-range index;
7. expose explain data: tokenizer, fields, weights, document frequency, field score contributions, and routed shards;
8. validate exact scoring against an unsharded reference on fixed and randomized fixtures.

### 4.5 Vector index

The vector builder will:

1. create legal semantic chunks from headings, sections, and subsections with stable offsets and parent links;
2. recompute embeddings under a pinned model revision and normalize them for cosine similarity;
3. train deterministic balanced spherical k-means from a deterministic sample;
4. recursively split oversized clusters so each centroid has at most 8,192 rows and at most two physical shards;
5. store at most 4,096 rows per shard;
6. sort rows within each shard by descending cosine similarity to the shard centroid with a stable key tie-breaker;
7. store the normalized centroid, radius/score bounds, row count, shard descriptors, and vector-space identifier in the routing index;
8. prove row conservation, uniqueness, dimensional consistency, normalization tolerance, ordering, bounds, and determinism.

Default remote search probes four centroids, then performs exact cosine scoring over downloaded rows. Recall evaluation must choose the final default; the manifest cannot label an unmeasured default as production-ready.

### 4.6 Legal knowledge graph

The graph ontology includes:

- structural nodes: code, title, subtitle, chapter, subchapter, part, subpart, section, subsection, note;
- authority/provenance nodes: public law, Statutes-at-Large cite, source package/granule, release point, agency/office when supported;
- lexical overlay references: BM25 term and bounded BM25-neighbor relation;
- typed edges such as `CONTAINS`, `CODIFIES`, `CITES`, `AMENDS`, `REPEALS`, `TRANSFERS`, `DERIVED_FROM`, `HAS_SOURCE`, `HAS_VERSION`, and `BM25_NEIGHBOR_OF`;
- unresolved citation nodes/edges that preserve source text, parser version, and resolution status rather than inventing a target.

Node and edge CIDs are deterministic. Edges are sorted by stable keys. Both incoming and outgoing adjacency are paged, score/priority ordered where appropriate, and bounded at 4,096 pointers per row. The build validates referential integrity, duplicate IDs, inverse adjacency completeness, source evidence, and graph-count reconciliation.

Embedding-guided traversal uses a bounded semantic beam. It starts from lexical/dense/hybrid seeds, expands only routed adjacency pages, obtains candidate-node embeddings from centroid-selected shards, and ranks the frontier with a declared blend of semantic score, edge weight, and path penalty. Every query declares maximum depth, nodes, edges, centroid probes, data shards, bytes, and wall time. Budget exhaustion is a typed partial result, never silent truncation.

### 4.7 Direct Hugging Face query client

The client resolves an immutable revision first and downloads only:

1. manifest and release metadata;
2. compact routing indexes;
3. query-selected posting/vector/graph shards;
4. corpus shards needed to hydrate final hits.

It uses `hf_hub_download(..., revision=<sha>)`, validates relative paths, checks descriptor byte counts and SHA-256 before parsing, bounds decompression and row counts, and maintains a revision-scoped cache. It returns a `fetch_trace` containing selected routes, files, bytes, cache hits, timings, and verification state without leaking tokens or local sensitive paths.

Supported operations are `bm25_search`, `vector_search`, `hybrid_search`, `neighbors`, `graph_walk`, and `semantic_graph_walk`, exposed through a Python API and CLI. Filters include title, chapter, section, source, release point, date/effective interval where known, and node/edge type. Offline replay against a fully cached pinned revision must produce the same ordered result CIDs and explanations.

## 5. Goals, subgoals, and execution lanes

The machine-readable objective heap is in `uscode_sparse_graphrag.objectives.md`; the executable task board is in `uscode_sparse_graphrag.todo.md`.

| Goal | Outcome | Principal tasks |
|---|---|---|
| `USCIR-G010` | Freeze evidence, schemas, and authoritative-source policy | `USCIR-001`–`004` |
| `USCIR-G020` | Build canonical all-title corpus and recovery boundary | `USCIR-005`–`008` |
| `USCIR-G030` | Extract reusable 4,096-row artifact and secure Hub substrate | `USCIR-009`–`012` |
| `USCIR-G040` | Build and prove term-routed BM25 | `USCIR-013`–`016` |
| `USCIR-G050` | Regenerate, cluster, sort, and route vectors | `USCIR-017`–`020` |
| `USCIR-G060` | Build legal and BM25-backed graph layouts | `USCIR-021`–`024` |
| `USCIR-G070` | Query pinned Hugging Face artifacts directly | `USCIR-025`–`028` |
| `USCIR-G080` | Integrate legal APIs, incremental builds, and release packaging | `USCIR-029`–`032` |
| `USCIR-G090` | Prove quality, security, performance, and remote behavior | `USCIR-033`–`036` |
| `USCIR-G100` | Stage, document, canary, and manually seal publication | `USCIR-037`–`040` |

Strict lane ownership is `numeric task id modulo 4`:

| Lane | Initial task | Continuing specialty |
|---:|---|---|
| 0 | `USCIR-004` source authority contract | acquisition, release manifest, rollout |
| 1 | `USCIR-001` frozen baseline | corpus, BM25, package integration |
| 2 | `USCIR-002` shared schema ADR | shared layouts, graph, quality evaluation |
| 3 | `USCIR-003` retrieval gold set | vector/query, security, canary |

The first four tasks are file-disjoint and ready immediately. Cross-lane dependencies are explicit. Shared exports and package registries are touched only by late integration tasks after their producer tasks are complete. Publication is a review-only terminal task and is not schedulable by implementation agents.

## 6. Delivery stages and gates

### Stage A — contract and fixtures

Exit when the pinned remote baseline can be reproduced from an audit script, source/release authority is explicit, schemas are versioned, and fixed legal retrieval queries have relevance and graph-path expectations.

### Stage B — deterministic builders

Exit when corpus, BM25, vector, and graph builders produce descriptor-complete ≤4,096-row artifacts twice with identical logical records, counts, routes, and CIDs. Byte identity is required when the Parquet writer/runtime versions are pinned; otherwise byte drift must be explained while logical CIDs remain identical.

### Stage C — bounded remote query

Exit when every supported operation can query a pinned local fixture and a staged Hub revision while downloading only control-plane plus routed shards. Results must include a fetch trace and typed budget/verification failures.

### Stage D — migration candidate

Exit when all 60,068 baseline canonical records have an explicit admitted, replaced, or excluded disposition; the nine recovery rows are quarantined or normalized; all 185,563 legacy vector rows have a regeneration disposition; viewer configs pass; and compatibility configs are documented.

### Stage E — release

Exit when a staged immutable candidate passes quality/security/performance gates and a human signs a publication seal containing candidate revision, source release point, manifest digest, validation receipt digest, rollback target, and authorization identity. Only then may the live dataset be updated.

## 7. Acceptance thresholds

The release candidate must satisfy all of the following:

- 100% record accounting from the pinned source snapshot; no silent row loss;
- no canonical row without `entry_cid`, `legal_id`, source receipt, and admission status;
- zero duplicate primary keys and zero dangling durable graph edges;
- 100% inverse-adjacency reconciliation;
- every artifact respects its 4,096-row/pointer bound and every centroid respects the 8,192-row/two-shard bound;
- exact BM25 scoring parity with the reference scorer to tolerance on deterministic tests;
- centroid-routed recall measured against exhaustive vector search, with a documented threshold and chosen probe count before production labeling;
- hybrid and graph retrieval do not regress the frozen legal gold set relative to both BM25-only and vector-only baselines without an approved exception;
- malformed manifests, traversal paths, digest mismatches, oversized rows, decompression bombs, revision drift, and cache poisoning fail closed;
- remote integration test proves revision pinning and bounded shard fetch; no full-repository clone is required;
- Dataset Viewer validity succeeds for every advertised configuration and recovery artifacts cannot contaminate the default config;
- two clean rebuilds pass determinism checks;
- rollback rehearsal restores the prior advertised revision/config mapping without deleting legacy data.

Performance targets are recorded on a declared reference machine and network rather than treated as universal constants. The evaluation report must at minimum measure p50/p95 latency, bytes fetched, cache hit ratio, shards fetched, exhaustive recall, nDCG/MRR/Recall@k, graph budget utilization, peak memory, and build throughput.

## 8. Evaluation set

The frozen suite covers exact citation lookup, synonyms, cross-title questions, historical/version ambiguity, negative controls, and graph paths. It includes representative provisions from Titles 5, 11, 17, 18, 26, 28, 31, 35, 42, and 47—for example FOIA, automatic stay, fair use, federal-question jurisdiction, supplemental jurisdiction, removal, False Claims Act, patent eligibility/obviousness/specification, civil-rights and disability provisions, and Section 230.

Labels distinguish:

- exact section retrieval;
- relevant subsection/chunk;
- supporting citation path;
- authoritative source evidence;
- known ambiguity or abstention expectation;
- time-sensitive questions that must expose the release date rather than imply currentness.

The evaluation harness compares exhaustive and routed dense search, unsharded and sharded BM25, fusion policies, structural graph walks, and semantic graph walks. Tunable weights are selected on a development split and reported once on a sealed test split.

## 9. Incremental update strategy

An update begins by resolving and approving an official release point. It diffs stable legal identities and normalized content hashes, then regenerates only affected corpus chunks, postings, embeddings, citation resolution, graph edges, and routing metadata. Because document frequency and average length can affect global BM25 scores and vector cluster balance can affect routes, the planner must explicitly choose either a full deterministic rebuild or a delta release with a measured compaction/rebuild threshold. It cannot label a partially refreshed global index as equivalent to a full rebuild without proof.

Every update writes checkpoints and resumable receipts per title and per artifact family. A release candidate is immutable after its manifest digest is sealed. Subsequent changes create a new candidate/revision.

## 10. Security and privacy

- Hub credentials come only from the environment/keyring and never appear in argv, prompts, logs, manifests, or fetch traces.
- Remote paths are allow-listed by a verified manifest; absolute paths, `..`, links, device files, and descriptor mismatch are rejected.
- Dataset content is untrusted input. Parquet/JSON sizes, row counts, nesting, strings, and decompression ratios are bounded.
- Source-recovery metadata is scrubbed of historical absolute local paths before publication.
- Cache keys include repo ID, immutable revision, relative path, digest, and schema version.
- Network operations are disabled in ordinary unit tests and enabled only in marked integration/canary jobs.
- Agents cannot publish, delete, force-push, change visibility, or mutate dataset metadata without the terminal publication seal.

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| mixed official vintages masquerade as one current Code | exact all-title release manifest; per-title receipts; fail-closed admission |
| legacy positional embedding joins corrupt identity | recompute from canonical `entry_cid`; never repack unknown vectors as trusted |
| graph explodes from 13.6M lexical pairs | postings-backed virtual term edges plus bounded neighbor projection |
| centroids reduce recall | exhaustive comparison, probe tuning, radius diagnostics, configurable fallback |
| remote client downloads too much | compact routing indexes, strict byte/shard budgets, fetch-trace assertions |
| Dataset Viewer re-breaks due heterogeneous files | explicit card configs and separate recovery config |
| parallel agents collide | strict modulo lanes, exact predicted files, protected control plane, serialized merge queue |
| supervisor appears alive while workers are orphaned | exact process ownership, fresh heartbeat/progress checks, duplicate/orphan rejection |
| live dataset is overwritten prematurely | staged candidate plus unschedulable human publication seal |

## 12. Supervisor operating contract

The sealed scheduler uses four strict lanes, a clean feature branch, protected plan/control files, a serialized merge queue, bounded retries, implementation timeout, log-stall watchdog, and ordered providers: Grok `grok-4.5` primary with Codex `gpt-5.6-terra` fallback only on verified primary quota exhaustion.

Healthy means more than live PIDs. Two consecutive samples separated by at least one scheduler check interval must show:

- one matching scheduler master and one owned outer/managed process tree per configured lane;
- no duplicate or orphan process using this board namespace or state root;
- fresh status heartbeats and either task/commit/merge progress, an active bounded worker, or a typed provider-capacity backoff;
- no protected-path incident, stale active worker, restart storm, exhausted retry/quarantine, or unexplained ready-without-active state;
- active logs fresher than the configured log-stall threshold and task runtime below the hard maximum;
- zero untyped blocked tasks.

The runtime lives under the ignored project path `workspace/agent-supervisor/uscode-sparse-graphrag/`. Runtime receipts are operational evidence, not authority to edit the protected plan or publish the dataset.

## 13. Definition of done

This program is complete only when package code, tests, fixtures, documentation, release builders, remote query client, staged dataset candidate, and validation receipts satisfy this plan; the public dataset is either updated under a human publication seal or the task is explicitly closed at the staged-candidate boundary with the remaining external authorization recorded. A running supervisor or a generated set of files alone is not completion.
