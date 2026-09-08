"""Write country-laws-ir-graphrag/v1 thin-client layout (SkillCenter / publicus-ir family)."""

from __future__ import annotations

import os

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from . import LAYOUT_FAMILY, MAX_ROWS_PER_FILE, SCHEMA_VERSION, __version__
from .catalog import target_repo
from .cidutil import file_descriptor
from .parquet_io import write_parquet, write_sharded

ADJ_POINTERS_PER_ROW = 4096
ADJ_POINTERS_PER_SHARD = 8192


def _index_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def package_release(
    out: Path,
    corpus: pd.DataFrame,
    bm25: dict[str, Any],
    graph: dict[str, Any],
    vectors: dict[str, Any],
    source_meta: dict[str, Any],
    country: dict[str, Any],
    code_root: Path,
    normalization_report: dict[str, Any] | None = None,
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
    posting_idx = write_sharded(
        postings,
        out / "data" / "bm25" / "postings",
        "data/bm25/postings",
        kind="bm25_postings",
        key_col="term",
    )
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
    # Drop null embeddings for stub releases so parquet stays typed; keep rows when present.
    if "embedding" in vectors_df.columns and vectors_df["embedding"].isna().all():
        vectors_write = vectors_df.drop(columns=["embedding"])
        vectors_write["embedding_status"] = "stub_missing"
    else:
        vectors_write = vectors_df
    vec_idx = write_sharded(
        vectors_write,
        out / "data" / "vectors",
        "data/vectors",
        kind="vectors",
        key_col="entry_cid",
        index_col="document_index",
    )
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
        if m.get("stub"):
            r["stub"] = True
            r["stub_reason"] = m.get("stub_reason", "")
    write_parquet(indexes_dir / "vector_chunks.parquet", _index_df(vec_idx))

    # Bundle package + scripts into the release
    pkg_src = Path(__file__).resolve().parent
    dest_pkg = out / "country_laws_ir"
    shutil.copytree(
        pkg_src,
        dest_pkg,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"),
    )
    scripts_dir = out / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    for name in (
        "build_country_laws_ir.py",
        "normalize_country_laws.py",
        "query_country_laws_hf.py",
        "query_country_laws_ir.py",
        "generate_country_laws_ir.py",
    ):
        src = code_root / "scripts" / name
        if src.exists():
            shutil.copy2(src, scripts_dir / name)
    shutil.copy2(pkg_src / "normalize.py", out / "normalize.py")
    shutil.copy2(pkg_src / "query.py", out / "query.py")
    shutil.copy2(pkg_src / "build.py", out / "build.py")
    _write_skill(out, country, hub_id=target_repo(country["slug"]))

    reports_dir = out / "reports"
    reports_dir.mkdir(exist_ok=True)
    if normalization_report is not None:
        payload = json.dumps(normalization_report, indent=2, ensure_ascii=False) + "\n"
        (out / "normalization_report.json").write_text(payload, encoding="utf-8")
        (reports_dir / "normalization.json").write_text(payload, encoding="utf-8")

    n_laws = int((corpus["record_type"] == "law").sum()) if "record_type" in corpus else 0
    n_articles = int((corpus["record_type"] == "article").sum()) if "record_type" in corpus else 0
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
        "n_laws": n_laws,
        "n_articles": n_articles,
    }

    def idx_desc(name: str) -> dict[str, Any]:
        path = indexes_dir / name
        return file_descriptor(path, f"indexes/{name}")

    hub_id = target_repo(country["slug"])
    edge_types = graph["stats"].get("edge_types") or [
        "HAS_JURISDICTION",
        "HAS_LANGUAGE",
        "BELONGS_TO_LAW",
        "HAS_ARTICLE",
        "BM25_NEIGHBOR_OF",
    ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "layout_family": LAYOUT_FAMILY,
        "packager_version": __version__,
        "primary_key": "entry_cid",
        "dataset_id": source_meta["source_dataset"],
        "dataset_repo_id": hub_id,
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
            "edge_types": edge_types,
        },
        "vector": vectors["stats"],
        "canonical_fields": [
            "entry_cid",
            "law_cid",
            "record_type",
            "jurisdiction",
            "language",
            "instrument_id",
            "instrument_title",
            "article_number",
            "article_title",
            "title",
            "body",
            "source_url",
            "snapshot_date",
            "coverage",
            "license",
            "collector",
            "source_dataset",
            "source_revision",
        ],
        "input_sha256": {
            "laws.parquet": source_meta.get("laws_sha256"),
            "articles.parquet": source_meta.get("articles_sha256"),
        },
        "model_id": (vectors.get("stats") or {}).get("model_name", "thenlper/gte-small"),
        "cid": {
            "codec": "raw",
            "hash": "sha2-256",
            "multibase": "base32",
            "payload": "json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')",
        },
        "normalization": normalization_report or {},
        "schema_mapping": {
            "laws": {
                "id": "instrument_id",
                "title": "instrument_title",
                "text": "body",
                "article_count_dtype_source": source_meta.get("article_count_dtype"),
            },
            "articles": {
                "id": "source_id / article identity",
                "law_id": "instrument_id",
                "title": "article_title",
                "text": "body",
            },
            "unit_policy": "prefer articles; fall back to law-level when articles empty",
            "required_law_columns": ["id", "title", "text"],
            "required_article_columns": ["id", "law_id", "title", "text"],
            "fail_closed": True,
            "notes": (
                "Malta and Germany share the same column names. Drift: Malta article_count "
                "is int64, Germany article_count is int32; Germany eli is often null. "
                "Identifiers are never invented. Layout matches SkillCenter HF release / publicus-ir family."
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
    _write_readme(out, country, source_meta, counts, bm25["stats"], graph["stats"], vectors["stats"], hub_id)
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
    hub_id: str,
) -> None:
    slug = country["slug"]
    name = country["name"]
    src = source_meta["source_dataset"]
    rev = source_meta["source_revision"]
    vec_status = vector_stats.get("status", "embedded")
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
- {slug}
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

Research retrieval release of `{src}` (revision `{rev}`) packaged as
`{SCHEMA_VERSION}` (layout family `{LAYOUT_FAMILY}` / publicus-ir).

**Not legal advice.** This is a research snapshot. The official gazette /
authentic source of {name} prevails over this corpus. Retrieved documents
and graph edges are retrieval evidence only. No legal text was invented.

Primary key: `entry_cid` (CIDv1 raw sha2-256 of a canonical identity record).
Integer `document_index` values are compact shard pointers, not identities.

Target Hub id (packaging metadata only): `{hub_id}`.

## Counts

| Field | Value |
| --- | --- |
| Laws (corpus units) | {counts['n_laws']} |
| Articles (corpus units) | {counts['n_articles']} |
| Canonical docs | {counts['corpus_rows']} |
| BM25 terms | {counts['bm25_terms']} |
| BM25 postings | {counts['bm25_postings']} |
| Graph nodes | {counts['graph_nodes']} |
| Graph edges | {counts['graph_edges']} |
| Vectors | {counts['vector_rows']} × {vector_stats['dimension']}-d `{vector_stats['model_name']}` ({vec_status}) |

## Canonical fields

`entry_cid`, `law_cid`, `record_type`, `jurisdiction`, `language`,
`instrument_id`, `instrument_title`, `article_number`, `article_title`,
`title`, `body`, `source_url`, `snapshot_date`, `coverage`, `license`,
`collector`, `source_dataset`, `source_revision`.

Unit policy: prefer article/section rows; fall back to law-level when
`articles.parquet` is empty.

## Index layout

Zstandard parquet shards with at most 4,096 rows.

- `indexes/bm25_keyword_shards.parquet` — lexical term ranges → BM25 posting shards
- `indexes/vector_chunks.parquet` — semantic routing centroids (rows sorted by cosine to shard centroid)
- `indexes/corpus_chunks.parquet` — document ranges → corpus shards
- `data/graph/nodes` / `data/graph/edges` — property graph
- `data/graph/adjacency/{{incoming,outgoing}}` — score-ordered neighbor pages

BM25: Okapi k1=1.2, b=0.75, title_weight=5, body_weight=1 (FTS5 unicode61-style tokenizer).

Graph: one node per `entry_cid` plus facet nodes (`_facet_cid(kind, value)` for
jurisdiction, language, instrument, source, status). Neighbor edges
`BM25_NEIGHBOR_OF` (k=8) carry score and matched terms. Structural edges:
`ARTICLE_OF` (article → parent law) when articles exist, plus `IDENTIFIED_BY_ELI`
/ `IDENTIFIED_BY` only when those identifiers are present in the source.

## Query

```
python scripts/query_country_laws_hf.py --local-dir . bm25 "constitution" --top-k 10
python scripts/query_country_laws_hf.py --local-dir . vector "money laundering" --top-k 10
python scripts/query_country_laws_hf.py --local-dir . graph neighbors <entry_cid>
```

## Publish later (operator)

```
export HF_TOKEN=...   # never commit
hf upload-large-folder {hub_id} . \\
  --repo-type dataset --no-private --num-workers 8 \\
  --exclude "**/__pycache__/**" --exclude "**/*.pyc"
```

## Provenance

Packaged by country-laws-ir. Upstream collector and official license remain those
of `{src}`. CIDs identify local content; they do not prove public IPFS pinning.
"""
    (out / "README.md").write_text(text, encoding="utf-8")


def _write_skill(out: Path, country: dict[str, Any], hub_id: str) -> None:
    skill_dir = out / "skill" / "query-country-laws-hf"
    skill_dir.mkdir(parents=True, exist_ok=True)
    name = country.get("name") or country.get("slug")
    slug = country.get("slug")
    text = f"""---
name: query-country-laws-hf
description: Query a local or Hub country-laws-ir GraphRAG release (BM25, vectors, graph neighbors). Research retrieval only — not legal advice.
---

# Query country-laws-ir (SkillCenter-style sparse GraphRAG)

Thin client for `{hub_id}` / local release roots that follow
`country-laws-ir-graphrag/v1` (layout family `skillcenter-huggingface-release/v3`).

**Not legal advice.** Official gazettes prevail. Retrieved hits are context only.

## Local

```bash
python scripts/query_country_laws_hf.py --local-dir . bm25 "constitution" --top-k 5
python scripts/query_country_laws_hf.py --local-dir . vector "money laundering" --top-k 5
python scripts/query_country_laws_hf.py --local-dir . graph neighbors <entry_cid>
```

Or:

```bash
python -m country_laws_ir query --local-dir /workspace/country-laws-ir/releases/ipfs_{slug}_laws_ir -- bm25 "constitution"
```

## Method

- Primary key `entry_cid` (CIDv1 raw sha2-256). `document_index` is a shard pointer.
- BM25 Okapi k1=1.2 b=0.75, title_weight=5, body_weight=1, FTS5-style tokenizer.
- Vectors `thenlper/gte-small` 384-d, mean-pool, L2, centroid-sorted shards.
- Graph: facets + `BM25_NEIGHBOR_OF` (k=8, score + matched terms) + `ARTICLE_OF`.

Do not treat retrieval as proof. Do not invent citations.
"""
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
