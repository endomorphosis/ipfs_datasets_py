"""Write SkillCenter-huggingface-release/v3 thin-client layout."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from . import MAX_ROWS_PER_FILE, SCHEMA_VERSION, __version__
from .cidutil import file_descriptor, sha256_file
from .parquet_io import write_parquet, write_sharded

ADJ_POINTERS_PER_ROW = 4096
ADJ_POINTERS_PER_SHARD = 8192


def _index_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _write_index(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    df = _index_df(rows)
    write_parquet(path, df)
    rel = str(path).split("/releases/")[-1]
    # relative_path from release root
    return file_descriptor(path, path.name if path.parent.name == "indexes" else str(path))


def package_release(
    out: Path,
    corpus: pd.DataFrame,
    bm25: dict[str, Any],
    graph: dict[str, Any],
    vectors: dict[str, Any],
    source_meta: dict[str, Any],
    country: dict[str, Any],
    code_root: Path,
) -> dict[str, Any]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    indexes_dir = out / "indexes"
    indexes_dir.mkdir(parents=True, exist_ok=True)

    corpus_idx = write_sharded(
        corpus,
        out / "data" / "corpus",
        "data/corpus",
        kind="corpus",
        key_col="entry_cid",
        index_col="document_index",
    )
    write_parquet(indexes_dir / "corpus_chunks.parquet", _index_df(corpus_idx))

    bm25_doc_idx = write_sharded(
        bm25["documents"],
        out / "data" / "bm25" / "documents",
        "data/bm25/documents",
        kind="bm25_documents",
        key_col="entry_cid",
        index_col="document_index",
    )
    write_parquet(indexes_dir / "bm25_document_chunks.parquet", _index_df(bm25_doc_idx))

    postings = bm25["postings"]
    # shard postings by term ranges, 4096 terms (posting rows) per shard
    posting_idx = write_sharded(
        postings,
        out / "data" / "bm25" / "postings",
        "data/bm25/postings",
        kind="bm25_postings",
        key_col="term",
    )
    # enrich keyword shard index
    for row, part_start in zip(posting_idx, range(len(posting_idx))):
        shard_df = postings.iloc[part_start * MAX_ROWS_PER_FILE : (part_start + 1) * MAX_ROWS_PER_FILE]
        row["term_count"] = int(shard_df["term"].nunique()) if not shard_df.empty else 0
        row["posting_count"] = int(shard_df["document_indices"].map(len).sum()) if not shard_df.empty else 0
        row["token_instance_count"] = row["posting_count"]
    write_parquet(indexes_dir / "bm25_keyword_shards.parquet", _index_df(posting_idx))

    node_idx = write_sharded(
        graph["nodes"],
        out / "data" / "graph" / "nodes",
        "data/graph/nodes",
        kind="graph_nodes",
        key_col="node_cid",
    )
    write_parquet(indexes_dir / "graph_node_chunks.parquet", _index_df(node_idx))

    edge_idx = write_sharded(
        graph["edges"],
        out / "data" / "graph" / "edges",
        "data/graph/edges",
        kind="graph_edges",
        key_col="edge_cid",
    )
    write_parquet(indexes_dir / "graph_edge_chunks.parquet", _index_df(edge_idx))

    incoming = graph["incoming"]
    outgoing = graph["outgoing"]
    in_idx = write_sharded(
        incoming if incoming is not None and not incoming.empty else pd.DataFrame(
            columns=["node_cid", "page_index", "direction"]
        ),
        out / "data" / "graph" / "adjacency" / "incoming",
        "data/graph/adjacency/incoming",
        kind="graph_incoming_adjacency",
        key_col="node_cid",
    )
    out_idx = write_sharded(
        outgoing if outgoing is not None and not outgoing.empty else pd.DataFrame(
            columns=["node_cid", "page_index", "direction"]
        ),
        out / "data" / "graph" / "adjacency" / "outgoing",
        "data/graph/adjacency/outgoing",
        kind="graph_outgoing_adjacency",
        key_col="node_cid",
    )
    for rows, direction in ((in_idx, "incoming"), (out_idx, "outgoing")):
        for r in rows:
            r["direction"] = direction
            r["adjacency_count"] = r.get("row_count", 0)
            r["node_count"] = r.get("row_count", 0)
            r["first_page_index"] = 0
            r["last_page_index"] = 0
    write_parquet(indexes_dir / "graph_incoming_adjacency.parquet", _index_df(in_idx))
    write_parquet(indexes_dir / "graph_outgoing_adjacency.parquet", _index_df(out_idx))

    vectors_df = vectors["vectors"]
    vec_idx = write_sharded(
        vectors_df,
        out / "data" / "vectors",
        "data/vectors",
        kind="vectors",
        key_col="entry_cid",
        index_col="document_index",
    )
    # attach centroids from chunk_meta (one shard per cluster)
    meta_by_cluster = {m["cluster_id"]: m for m in vectors["chunk_meta"]}
    for r in vec_idx:
        m = meta_by_cluster.get(r["shard_id"], {})
        r["centroid"] = m.get("centroid", [])
        r["shard_centroid"] = m.get("shard_centroid", [])
        r["centroid_min_score"] = m.get("centroid_min_score", 0.0)
        r["centroid_shard_count"] = m.get("centroid_shard_count", 1)
        r["chunk_in_cluster"] = m.get("chunk_in_cluster", 0)
        r["cluster_id"] = m.get("cluster_id", r["shard_id"])
        r["dimension"] = 384
        r["model_name"] = "thenlper/gte-small"
    write_parquet(indexes_dir / "vector_chunks.parquet", _index_df(vec_idx))

    # copy generation + query scripts into the release
    pkg_src = Path(__file__).resolve().parent
    dest_pkg = out / "country_laws_ir"
    shutil.copytree(pkg_src, dest_pkg, dirs_exist_ok=True)
    scripts_dir = out / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    query_src = pkg_src / "query.py"
    shutil.copy2(query_src, scripts_dir / "query_country_laws_hf.py")
    gen_src = pkg_src.parent / "scripts" / "generate_country_laws_ir.py"
    if gen_src.exists():
        shutil.copy2(gen_src, scripts_dir / "generate_country_laws_ir.py")

    counts = {
        "bm25_document_chunks": len(bm25_doc_idx),
        "bm25_documents": int(len(bm25["documents"])),
        "bm25_keyword_shards": len(posting_idx),
        "bm25_posting_rows": int(len(postings)),
        "bm25_postings": int(bm25["stats"]["n_postings"]),
        "bm25_terms": int(bm25["stats"]["n_terms"]),
        "corpus_chunks": len(corpus_idx),
        "corpus_rows": int(len(corpus)),
        "graph_edge_chunks": len(edge_idx),
        "graph_edges": int(len(graph["edges"])),
        "graph_incoming_adjacency_edges": int(len(graph["edges"])),
        "graph_incoming_adjacency_rows": int(len(incoming)) if incoming is not None else 0,
        "graph_incoming_adjacency_shards": len(in_idx),
        "graph_node_chunks": len(node_idx),
        "graph_nodes": int(len(graph["nodes"])),
        "graph_outgoing_adjacency_edges": int(len(graph["edges"])),
        "graph_outgoing_adjacency_rows": int(len(outgoing)) if outgoing is not None else 0,
        "graph_outgoing_adjacency_shards": len(out_idx),
        "vector_chunks": len(vec_idx),
        "vector_rows": int(len(vectors_df)),
        "n_laws": int((corpus["record_type"] == "law").sum()),
        "n_articles": int((corpus["record_type"] == "article").sum()),
    }

    def idx_desc(name: str) -> dict[str, Any]:
        path = indexes_dir / name
        return file_descriptor(path, f"indexes/{name}")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "packager_version": __version__,
        "primary_key": "entry_cid",
        "dataset_id": source_meta["source_dataset"],
        "dataset_repo_id": f"justicedao/ipfs_{country['slug']}_laws-ir",
        "dataset_revision": source_meta["source_revision"],
        "country": country,
        "disclaimer": "Research snapshot. Not legal advice. The official gazette / authentic source prevails.",
        "bm25": {k: bm25["stats"][k] for k in (
            "k1", "b", "title_weight", "body_weight", "average_document_length",
            "tokenizer", "max_query_terms", "posting_rows_per_record", "terms_per_shard",
        )},
        "counts": counts,
        "parquet": {
            "compression": "zstd",
            "compression_level": 6,
            "max_rows_per_file": MAX_ROWS_PER_FILE,
            "row_group_size": MAX_ROWS_PER_FILE,
        },
        "graph": {
            "adjacency_pointers_per_row": ADJ_POINTERS_PER_ROW,
            "adjacency_pointers_per_shard": ADJ_POINTERS_PER_SHARD,
            "directions": ["incoming", "outgoing"],
            "max_remote_walk_depth": 8,
            "ordering": "score_desc_nulls_last",
            "edge_types": ["HAS_JURISDICTION", "HAS_LAW_ID", "HAS_LANGUAGE", "HAS_SOURCE", "BM25_NEIGHBOR_OF", "CONTAINED_IN"],
        },
        "vector": vectors["stats"],
        "schema_mapping": {
            "laws": {
                "id": "source_id / law_id",
                "title": "title",
                "text": "body",
                "article_count_dtype_source": source_meta.get("article_count_dtype"),
            },
            "articles": {
                "id": "source_id / article_id",
                "law_id": "law_id / parent_law_id",
                "title": "title",
                "text": "body",
            },
            "required_law_columns": ["id", "title", "text"],
            "required_article_columns": ["id", "law_id", "title", "text"],
            "fail_closed": True,
            "notes": (
                "Malta and Germany share the same column names. Drift: Malta article_count "
                "is int64, Germany article_count is int32; Germany eli is often null. "
                "Identifiers are never invented."
            ),
        },
        "indexes": {
            "bm25_document_chunks": idx_desc("bm25_document_chunks.parquet"),
            "bm25_keyword_shards": idx_desc("bm25_keyword_shards.parquet"),
            "corpus_chunks": idx_desc("corpus_chunks.parquet"),
            "graph_edge_chunks": idx_desc("graph_edge_chunks.parquet"),
            "graph_incoming_adjacency": idx_desc("graph_incoming_adjacency.parquet"),
            "graph_node_chunks": idx_desc("graph_node_chunks.parquet"),
            "graph_outgoing_adjacency": idx_desc("graph_outgoing_adjacency.parquet"),
            "vector_chunks": idx_desc("vector_chunks.parquet"),
        },
        "source": source_meta,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_readme(out, country, source_meta, counts, bm25["stats"], graph["stats"], vectors["stats"])
    _write_gitattributes(out)
    return manifest


def _write_gitattributes(out: Path) -> None:
    (out / ".gitattributes").write_text(
        "*.parquet filter=lfs diff=lfs merge=lfs -text\n"
        "*.bin filter=lfs diff=lfs merge=lfs -text\n",
        encoding="utf-8",
    )


def _write_readme(
    out: Path,
    country: dict[str, Any],
    source_meta: dict[str, Any],
    counts: dict[str, Any],
    bm25_stats: dict[str, Any],
    graph_stats: dict[str, Any],
    vector_stats: dict[str, Any],
) -> None:
    slug = country["slug"]
    name = country["name"]
    src = source_meta["source_dataset"]
    rev = source_meta["source_revision"]
    text = f"""---
license: other
task_categories:
- text-retrieval
tags:
- legal
- law
- graphrag
- bm25
- research
- not-legal-advice
pretty_name: {name} laws IR (CID-keyed GraphRAG)
configs:
- config_name: corpus
  data_files:
  - split: train
    path: data/corpus/*.parquet
- config_name: bm25_documents
  data_files:
  - split: train
    path: data/bm25/documents/*.parquet
- config_name: bm25_postings
  data_files:
  - split: train
    path: data/bm25/postings/*.parquet
- config_name: bm25_keyword_index
  data_files:
  - split: train
    path: indexes/bm25_keyword_shards.parquet
- config_name: vectors
  data_files:
  - split: train
    path: data/vectors/*.parquet
- config_name: vector_meta_index
  data_files:
  - split: train
    path: indexes/vector_chunks.parquet
- config_name: graph_nodes
  data_files:
  - split: train
    path: data/graph/nodes/*.parquet
- config_name: graph_edges
  data_files:
  - split: train
    path: data/graph/edges/*.parquet
- config_name: graph_outgoing_adjacency
  data_files:
  - split: train
    path: data/graph/adjacency/outgoing/*.parquet
- config_name: graph_incoming_adjacency
  data_files:
  - split: train
    path: data/graph/adjacency/incoming/*.parquet
---

# {name} legislation IR (CID-keyed sparse GraphRAG)

Research retrieval release of `{src}` (revision `{rev}`) packaged in the
`skillcenter-huggingface-release/v3` thin-client layout.

**Not legal advice.** This is a research snapshot. The official gazette /
authentic source of {name} prevails over this corpus. Retrieved documents
and graph edges are retrieval evidence only.

Primary key: `entry_cid` (CIDv1 raw sha2-256 of a canonical identity record).
Integer `document_index` values are compact shard pointers, not identities.

## Counts

| Field | Value |
| --- | --- |
| Laws | {counts['n_laws']} |
| Articles | {counts['n_articles']} |
| Canonical docs | {counts['corpus_rows']} |
| BM25 terms | {counts['bm25_terms']} |
| BM25 postings | {counts['bm25_postings']} |
| Graph nodes | {counts['graph_nodes']} |
| Graph edges | {counts['graph_edges']} |
| Vectors | {counts['vector_rows']} × {vector_stats['dimension']}-d `{vector_stats['model_name']}` |

## Schema mapping

Source tables `data/laws.parquet` + `data/articles.parquet`. Required identifiers
(`laws.id`, `articles.id`, `articles.law_id`) are **fail-closed**: the packager
refuses to invent missing ids.

| Source | Canonical |
| --- | --- |
| laws.id | source_id, law_id |
| laws.title | title |
| laws.text | body |
| articles.id | source_id, article_id |
| articles.law_id | law_id, parent_law_id |
| articles.title / text | title / body |

Column-name drift check (Malta vs Germany): same names; `article_count` is
int64 on Malta and int32 on Germany; Germany `eli` is often null.

## Index layout

Zstandard parquet shards with at most 4,096 rows.

- `indexes/bm25_keyword_shards.parquet` maps lexical term ranges to BM25 posting shards.
- `indexes/vector_chunks.parquet` stores semantic routing centroids; rows inside each shard are sorted by decreasing cosine to the shard centroid.
- `indexes/corpus_chunks.parquet` maps document ranges to canonical corpus shards.
- `data/graph/nodes` and `data/graph/edges` are the property graph.
- `data/graph/adjacency/{{incoming,outgoing}}` stores score-ordered neighbor pages.

BM25: Okapi k1=1.2, b=0.75, title_weight=5, body_weight=1.

Graph: one node per `entry_cid`, facet nodes for jurisdiction / law_id / language / source,
`BM25_NEIGHBOR_OF` edges (k=8), and article `CONTAINED_IN` law edges when articles exist.

## Query

```
python -m pip install pyarrow pandas numpy huggingface_hub sentence-transformers
python scripts/query_country_laws_hf.py --local-dir . bm25 "constitution" --top-k 10
python scripts/query_country_laws_hf.py --local-dir . vector "money laundering" --top-k 10
python scripts/query_country_laws_hf.py --local-dir . graph neighbors <entry_cid>
```

Remote:

```
python scripts/query_country_laws_hf.py --repo-id justicedao/ipfs_{slug}_laws-ir bm25 "constitution"
```

Normalize + generation code lives in `country_laws_ir/` in this dataset repo.

## Exclusions

`ipfs_belgium_laws`, `ipfs_portugal_laws`, and `ipfs_lithuania_laws` are incomplete
Wayback harvests and are excluded from this indexing pipeline.

## Provenance

Packaged by country-laws-ir. Upstream collector and official license remain those
of `{src}`. CIDs identify local content; they do not prove public IPFS pinning.
"""
    (out / "README.md").write_text(text, encoding="utf-8")
