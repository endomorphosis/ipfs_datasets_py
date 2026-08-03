# JusticeDAO Patent/Legal Hub Layout (v2)

Status: layout contract for PATLAW-156 / PATLAW-G181  
Module: `ipfs_datasets_py/processors/domains/patent/hf_layout_v2.py`  
Schema: `patent-legal-hf-layout/v2`

## Purpose

Define **Viewer-compatible** Hugging Face repository identities, configs, root
Parquet patterns, dataset cards, JSON-LD/manifests, version tags, coverage
disclosures, and **non-destructive** migration pointers for JusticeDAO
patent/legal public releases.

This document describes layout **contracts only**. Deterministic shard
construction is PATLAW-157; DLP/Viewer admission gates are PATLAW-158;
authenticated staged publication is PATLAW-159/160.

## Non-goals

- No Hub authentication, upload, rename, or delete.
- No private, mixed, or unknown disclosure configs.
- No claim that a layout package is a published release.
- No hard-coded “latest” year; cutoffs and current-through values are explicit.

## Lowercase identities

All **new** organization and repository identities are entirely lowercase:

| Role | Dataset ID |
|------|------------|
| corpus | `justicedao/patent-legal-corpus` |
| vectors | `justicedao/patent-legal-vectors` |
| bm25 | `justicedao/patent-legal-bm25` |
| knowledge_graph | `justicedao/patent-legal-knowledge-graph` |

The historical v1 monorepo id `JusticeDAO/patent-legal-public` (and its
lowercase form `justicedao/patent-legal-public`) remains in the **legacy
inventory** solely so operators can attach forward migration pointers. New
layout packages never emit mixed-case org/repo strings as canonical targets.

## Multi-repository, multi-config pattern

JusticeDAO’s established pattern (see EU law families such as
`justicedao/ipfs_netherlands_laws` + `_bm25_index` + `_knowledge_graph`) is
preserved:

1. **Corpus repository** holds official-law and public patent row configs.
2. **Vectors**, **BM25**, and **knowledge-graph** each live in a **separate**
   repository so Viewer configs stay focused and thin clients can fetch only
   the index family they need.
3. Within each repository, every config exposes a **root Parquet
   `data_files` pattern** that Dataset Viewer can resolve.

### Corpus configs (`justicedao/patent-legal-corpus`)

| Config | Pattern |
|--------|---------|
| `usc` | `data/usc/*.parquet` |
| `cfr` | `data/cfr/*.parquet` |
| `public_law` | `data/public_law/*.parquet` |
| `federal_register` | `data/federal_register/*.parquet` |
| `projected_rules` | `data/projected_rules/*.parquet` |
| `applications` | `data/applications/*.parquet` |
| `claims` | `data/claims/*.parquet` |
| `events` | `data/events/*.parquet` |
| `office_actions` | `data/office_actions/*.parquet` |
| `citations` | `data/citations/*.parquet` |

### Vector configs (`justicedao/patent-legal-vectors`)

| Config | Pattern |
|--------|---------|
| `vectors` | `data/vectors/*.parquet` |
| `vector_chunk_index` | `indexes/vector_chunks.parquet` |

### BM25 configs (`justicedao/patent-legal-bm25`)

| Config | Pattern |
|--------|---------|
| `bm25_documents` | `data/bm25/documents/*.parquet` |
| `bm25_postings` | `data/bm25/postings/*.parquet` |

### Knowledge-graph configs (`justicedao/patent-legal-knowledge-graph`)

| Config | Pattern |
|--------|---------|
| `graph_nodes` | `data/graph/nodes/*.parquet` |
| `graph_edges` | `data/graph/edges/*.parquet` |
| `graph_node_chunk_index` | `indexes/graph_node_chunks.parquet` |
| `graph_edge_chunk_index` | `indexes/graph_edge_chunks.parquet` |

## Generated support artifacts

Each repository layout package includes:

| File | Role |
|------|------|
| `README.md` | Dataset card (YAML front matter + human disclosures) |
| `dataset_configs.json` | Machine-readable configs and `data_files` patterns |
| `dataset_infos.json` | Split/feature summary for Viewer discovery |
| `manifest.jsonld` | JSON-LD identity, configs, sources, CID join fields |
| `coverage.json` | Sources, licenses, cutoffs, freshness, gaps, tool versions |
| `layout-manifest.json` | Layout contract binding for the package |
| `migration-pointer.json` | Optional; present when legacy forward pointers are attached |

## Dataset card disclosures (required)

Generated cards and `coverage.json` **must** enumerate:

1. **Sources** — stable `source_id` values with optional URI/revision/CID  
2. **Licenses** — SPDX-like or public-domain expressions per source  
3. **Official-edition cutoffs** — per-source edition boundary  
4. **Freshness / current-through** — per-source watermark (never “latest”)  
5. **Gaps** — known omissions and out-of-scope material  
6. **Parser versions** — bound parser/extractor identities  
7. **Model versions** — embedding/tokenizer (or other model) revisions  
8. **Responsible use** — public-only, non-advice, non-filing, no private reconstruction  

Cards also list every config with its Viewer path pattern and join fields.

## CID joins

Public rows and index entries join through:

- `source_cid` — content id of the admitted public source artifact  
- `record_id` — stable public record identity  
- index/graph routing tables additionally bind shard `cid` / `sha256` /
  `relative_path`

JSON-LD (`manifest.jsonld`) restates join fields per config so release and
Viewer gates can verify referential integrity without scraping the card prose.

## Version tags

Layout packages carry a version tag matching:

```text
patent-legal-v2[.N[.N[.N]]][+metadata]
```

Default: `patent-legal-v2.0.0`.  
Tags bind the layout contract revision for migration pointers and release
promotion; they are not Hub commit SHAs.

## Migration pointers (no data deletion)

Legacy repositories **point forward** by adding additive metadata:

```json
{
  "legacy_dataset_id": "JusticeDAO/patent-legal-public",
  "target_dataset_id": "justicedao/patent-legal-corpus",
  "target_version_tag": "patent-legal-v2.0.0",
  "preserves_legacy_data": true,
  "deletion_allowed": false
}
```

Invariants:

- `preserves_legacy_data` is always `true`  
- `deletion_allowed` is always `false`  
- Pointer construction fails closed if either invariant is violated  
- Historical shards and commit history remain; operators do not rename/delete
  legacy Hub repositories as part of this layout task  

The corpus package may include pointers for both
`JusticeDAO/patent-legal-public` and `justicedao/patent-legal-public`.

## Private configs cannot be declared

Fail-closed rules in `PatentHubLayoutV2` / `HubConfigSpec`:

- `visibility` must be `"public"`  
- Config names must not contain private/confidential/privileged/restricted/
  secret/credential/mixed/unknown/internal/matter/work-product tokens  
- `validate_no_private_configs` rejects any attempted declaration before a
  card or `dataset_configs.json` is emitted  

Private matter data remains outside Hub publication (see release policy and
PATLAW-158).

## Viewer pattern resolution

Given a staged inventory of relative paths, `resolve_viewer_patterns`:

1. Matches each path with `fnmatch` against every config’s
   `data_files_pattern`  
2. Requires every declared config to hit **at least one** path when the
   inventory is non-empty  
3. Raises `ViewerPatternError` if any config fails to resolve  

Empty inventories only syntax-validate patterns (used for pure metadata
builds before shards exist).

## API surface

Primary types and entry points:

- `PatentHubLayoutV2` — builder/validator  
- `HubRepositoryIdentity`, `HubConfigSpec`  
- `SourceDisclosure`, `CoverageMetadata`  
- `MigrationPointer`  
- `RepositoryLayoutPackage`, `PatentHubLayoutBundle`  
- `build_default_layout_bundle()` — four-repo package with default public coverage  
- `default_public_coverage()` — deterministic disclosure fixture  

## Relationship to v1 release packaging

v1 (`hf_release.py`) stages a **single** privacy-reviewed monorepo
(`JusticeDAO/patent-legal-public`) with multi-kind parquet shards under
`data/{kind}/`. v2 **splits** corpus, vectors, BM25, and knowledge graph into
separate lowercase repositories, strengthens card disclosures (edition cutoffs,
freshness, gaps, parser/model versions, responsible use), and standardizes
Viewer root patterns and migration pointers. v1 data is retained; v2 points
forward.

## Validation

```bash
python -m pytest tests/unit/processors/patent/test_hf_layout_v2.py -q
```

## Operator notes

- Layout generation is local and deterministic; it does not contact the Hub.  
- Attaching a migration pointer to a **legacy** repository is a separate
  reviewed publication action.  
- Downstream release builders must keep join fields populated so Viewer and
  integrity gates can prove every index/graph row binds a public source CID.
