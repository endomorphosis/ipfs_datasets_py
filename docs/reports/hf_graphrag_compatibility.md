# HF GraphRAG Shared-Substrate Compatibility Report (USCIR-012)

## Purpose

This report records intentional **shared-substrate compatibility** between the
domain-neutral Hugging Face GraphRAG package
(`ipfs_datasets_py/retrieval/hf_graphrag/`) and three pinned reference layouts:

| Domain | Hub dataset | Immutable revision |
|---|---|---|
| Patent | `justicedao/patent-legal-ir-graphrag` | `845669408081f1334c54519d2bb7df6bf780ccd5` |
| CVEfixes | `Publicus/cvefixes-security-ir-graphrag` | `6fd5918bed34f8851430e74a149502587a953fe2` |
| SkillCenter | `Publicus/skillcenter-ir` | `2cc11a73403d03c0679ffa909c893ef6a850048a` |

Evidence lives in:

| Artifact | Path |
|---|---|
| Compact reference recipes | `tests/fixtures/hf_graphrag/reference_manifests.json` |
| Compatibility unit tests | `tests/unit/retrieval/hf_graphrag/test_reference_compatibility.py` |
| Shared substrate | `ipfs_datasets_py/retrieval/hf_graphrag/{schema,artifacts,resolver,locators}.py` |

Validation command:

```bash
python -m pytest tests/unit/retrieval/hf_graphrag/test_reference_compatibility.py -q
```

## Decision summary

1. **Adopt** the shared physical contract: 4,096 rows/pointers per retrieval
   unit, ZSTD Parquet shards, relative confined paths, row/byte/hash
   descriptors, compact routing indexes, and immutable Hub revisions.
2. **Adopt** the shared artifact-family vocabulary (`corpus`, `bm25_*`,
   `vectors`, `centroids`, `graph_*`, locators/routing, manifest/receipt/report).
3. **Do not interchange** vector spaces across domains. Vector identity is an
   explicit `vector_space_id` binding model + revision + pooling +
   normalization (+ dimension). Matching dimension alone never implies
   compatibility (plan §2.4).
4. **Do not interchange** domain graph ontologies. Layout families
   (`graph_nodes`, `graph_edges`, adjacency in/out) are shared; node/edge
   vocabularies remain domain-private.
5. Domain release schema tokens must be **explicitly admitted** to the
   resolver. Ambient defaults reject unregistered schemas with
   `SchemaMismatchError`.

## What the shared substrate reuses

| Reference | Reuse on the shared substrate | Do not copy blindly |
|---|---|---|
| Patent (`publicus-ir-graphrag/v1`) | Artifact family layout; term-range BM25; primary key `entry_cid` | Single-shard 256-d hashed vectors as a large-scale clustering template; patent claim ontology |
| CVEfixes | Deterministic spherical k-means; pinned model revision; 4,096-row vector shards; ≤8,192 rows/centroid; ≤2 shards/centroid; cosine sort + stable ties | Security node/edge vocabulary as a legal ontology |
| SkillCenter | Direct-Hub immutable resolver pattern; descriptor verification before parse; compact routing indexes; recursive clustering; bounded adjacency; fetch traces | Skill/intent ontology; GTE vector space without legal evaluation |

US Code builders should supply legal normalization, field weights, filters,
ontology, and evaluation policy on top of this substrate rather than forking
thousands of domain lines.

## Physical bounds (authoritative)

| Bound | Value | Notes |
|---|---:|---|
| Rows per physical data shard | 4,096 | Corpus, BM25 docs/postings, vectors, graph pages |
| Pointers per BM25/adjacency cell | 4,096 | Never reuse as a model-token ceiling |
| Term rows per BM25 term shard | 4,096 | Compact term-range routing |
| Routing-index rows | 4,096 | Compact control plane |
| Rows per vector centroid | 8,192 | At most two physical shards per centroid |
| Physical shards per centroid | 2 | CVEfixes/SkillCenter clustering contract |

Every reference recipe in `reference_manifests.json` declares these bounds.
Oversize row/pointer counts raise `PhysicalBoundError`.

## Artifact families

All three references exercise the shared `ArtifactFamily` vocabulary:

- data: `corpus`, `bm25_documents`, `bm25_postings`, `vectors`, `centroids`
- graph: `graph_nodes`, `graph_edges`, `graph_adjacency_out`, `graph_adjacency_in`
- control plane: `routing_index`, `locator_index` (SkillCenter), `manifest`

Domain path aliases (for example CVEfixes/SkillCenter
`data/graph/adjacency/outgoing|incoming` versus the US Code target
`.../out|in`) remain **release-relative POSIX paths** accepted by the shared
path normalizer. They do not create a second family vocabulary.

Unknown private families (for example `skill_blob`) raise
`HfGraphragSchemaError`.

## Immutable resolution

Each reference pin is a 40-hex Hub commit SHA. The shared
`ImmutableHubResolver`:

- rejects mutable tokens (`main`, `latest`, `HEAD`, …) with
  `MutableRevisionError`;
- verifies size + SHA-256 (+ optional CID) before callers parse bytes;
- stores revision-scoped cache entries and fails closed on collisions;
- emits credential-free fetch traces.

Domain schemas (`publicus-ir-graphrag/v1`,
`cvefixes-security-ir-hf-release/v1`,
`skillcenter-huggingface-release/v3`) are admitted only when listed in
`supported_schemas`. Loading SkillCenter under ambient defaults raises
`SchemaMismatchError` — intentional fail-closed behavior, not an invitation to
widen defaults without review.

## Vector-space identity (non-interchangeable)

| Domain | `vector_space_id` (fixture) | Dim | Model |
|---|---|---:|---|
| Patent | `patent-hashed-projection@84566940…:d256:pool=hash:norm=l2` | 256 | hashed projection |
| CVEfixes | `all-minilm-l6-v2@c9745ed1…:d384:pool=mean:norm=l2` | 384 | `sentence-transformers/all-MiniLM-L6-v2` |
| SkillCenter | `gte-small@2cc11a73…:d384:pool=mean:norm=l2` | 384 | `thenlper/gte-small` |

**Critical regression covered by tests:** CVEfixes and SkillCenter both use
384-dimensional embeddings, yet their `vector_space_id` values differ. Late
fusion or direct cosine comparison across those releases raises
`VectorSpaceIncompatibilityError`. Dimension equality is never a compatibility
proof.

Query-time rule (downstream of this task):

1. Embed each query with the exact model named by the release manifest.
2. Late-fuse across releases **only** when every participant declares the same
   `vector_space_id`.
3. Otherwise keep rankings independent and fuse scores at the result layer.

## Graph variations

| Domain | Ontology version | Representative node types | Representative edge types |
|---|---|---|---|
| Patent | `patent-legal-graph-ontology/v1` | application, claim, publication | HAS_CLAIM, CITES, CLASSIFIED_AS |
| CVEfixes | `cvefixes-graphrag-ontology/v1` | cve, cwe, commit, file | AFFECTS, HAS_CWE, FIXES |
| SkillCenter | `intent-corpus-ontology/v1` | skill, intent, tool, effect | DERIVED_FROM, INVOKES, HAS_EFFECT |

Shared layout (nodes/edges/adjacency pages ≤ 4,096) is compatible.
Cross-domain ontology merge raises `GraphOntologyIncompatibilityError`.
US Code must define its own legal ontology (structure, citations, authority,
amendments, transfers, repeals, lineage) rather than importing security or
skill vocabularies.

## Incompatible assumptions → typed errors

| Assumption | Typed error |
|---|---|
| Fuse MiniLM ↔ GTE because both are 384-d | `VectorSpaceIncompatibilityError` |
| Fuse patent hashed 256-d ↔ any 384-d space | `VectorSpaceIncompatibilityError` |
| Merge patent/CVE/skill graph ontologies | `GraphOntologyIncompatibilityError` |
| Pin revision `main` / `latest` | `MutableRevisionError` |
| Shard or pointer cell with 4,097 rows/pointers | `PhysicalBoundError` |
| Unknown artifact family | `HfGraphragSchemaError` |
| Unregistered domain release schema | `SchemaMismatchError` |
| Absolute / traversal artifact paths | `ArtifactPathError` / `UnsafePathError` |

## US Code implications

The US Code sparse GraphRAG release (`publicus-ir-graphrag/v2`) should:

1. Keep the shared 4,096 physical contract and family layout.
2. Regenerate embeddings under one pinned legal model revision and record a
   single explicit `vector_space_id` (never inherit the legacy unpinned 384-d
   file).
3. Own a legal graph ontology separate from patent/CVE/skill vocabularies.
4. Late-fuse only with releases that declare the same vector-space identifier.
5. Register its release schema with the shared resolver rather than relying on
   ambient SkillCenter/CVEfixes tokens.

## Status

| Criterion | Status |
|---|---|
| Fixtures exercise artifact families | Covered |
| Fixtures exercise 4,096 bounds | Covered |
| Fixtures exercise immutable resolution | Covered |
| Fixtures exercise vector-space IDs | Covered |
| Fixtures exercise graph variations | Covered |
| Incompatible assumptions raise typed errors | Covered |
| Vector spaces remain non-interchangeable | Covered |

This task is a **test/report** gate over the completed writer, resolver, and
locator substrate (USCIR-009–011). It does not modify reference domain
implementations.
