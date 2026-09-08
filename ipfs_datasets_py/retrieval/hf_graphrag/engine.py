"""Consumer-facing GraphRAG search-engine methods.

Domain builders import from here, then overlay schema-specific columns.
This consolidates the SkillCenter thin-client contract (compact Parquet
locators, nested BM25 cells, ``entry_cid`` + ``document_index``, centroid
probe index, digest manifest, viewer configs) with patent extras that are
safe to share (``contains_term`` graph, field-weighted BM25, FTS5 IDF).

Query-time walks stay serial. Pack and repair use
:func:`graphrag_process_pool_plan` (resource-aware spawn). This module
owns no domain ontology.
"""

from __future__ import annotations

import json
import math
import re
import shutil
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.identity import cid_v1, cid_v1_from_digest

from .artifacts import (
    ArtifactWriterConfig,
    describe_file,
    write_bounded_shards,
    write_zstd_parquet,
)
from .bm25 import (
    BM25_POSTING_SCHEMA_VERSION,
    DEFAULT_B,
    DEFAULT_BODY_WEIGHT,
    DEFAULT_K1,
    DEFAULT_POSTINGS_PER_ROW,
    DEFAULT_TITLE_WEIGHT,
    fts5_idf,
)
from .graph import GraphEdge, GraphNode
from .schema import (
    COMPACT_INDEX_SCHEMA_VERSION,
    MAX_POINTERS_PER_ROW,
    MAX_ROUTING_ROWS_PER_INDEX,
    ArtifactFamily,
    CompactIndexRow,
    HfGraphragSchemaError,
    normalize_relative_artifact_path,
)

ENGINE_SCHEMA_VERSION: Final = "hf-graphrag-engine/v1"
PRIMARY_KEY: Final = "entry_cid"
CONTAINS_TERM_EDGE: Final = "contains_term"
BM25_TERM_NODE: Final = "bm25_term"

SIMILARITY_EDGE_TYPES: Final = frozenset(
    {
        "BM25_NEIGHBOR_OF",
        "EMBEDDING_NEIGHBOR_OF",
        "SIMILAR_TO",
        CONTAINS_TERM_EDGE,
    }
)

STANDARD_VIEWER_CONFIGS: Final = {
    "corpus": "data/corpus/*.parquet",
    "bm25_documents": "data/bm25/documents/*.parquet",
    "bm25_postings": "data/bm25/postings/**/*.parquet",
    "graph_nodes": "data/graph/nodes/*.parquet",
    "graph_edges": "data/graph/edges/*.parquet",
    "graph_outgoing_adjacency": "data/graph/adjacency/outgoing/*.parquet",
    "graph_incoming_adjacency": "data/graph/adjacency/incoming/*.parquet",
    "vectors": "data/vectors/*.parquet",
    "corpus_chunk_index": "indexes/corpus_chunks.parquet",
    "bm25_keyword_index": "indexes/bm25_keyword_shards.parquet",
    "bm25_document_chunk_index": "indexes/bm25_document_chunks.parquet",
    "vector_meta_index": "indexes/vector_chunks.parquet",
    "graph_node_chunk_index": "indexes/graph_node_chunks.parquet",
    "graph_edge_chunk_index": "indexes/graph_edge_chunks.parquet",
    "graph_outgoing_adjacency_index": "indexes/graph_outgoing_adjacency.parquet",
    "graph_incoming_adjacency_index": "indexes/graph_incoming_adjacency.parquet",
}

STANDARD_INDEX_PATHS: Final = {
    "corpus": ("data/corpus", "indexes/corpus_chunks.parquet", ("entry_cid", "node_cid", "legal_id")),
    "bm25_documents": (
        "data/bm25/documents",
        "indexes/bm25_document_chunks.parquet",
        ("entry_cid", "legal_id"),
    ),
    "bm25_postings": (
        "data/bm25/postings",
        "indexes/bm25_keyword_shards.parquet",
        ("term", "first_key"),
    ),
    "graph_nodes": (
        "data/graph/nodes",
        "indexes/graph_node_chunks.parquet",
        ("node_cid", "entry_cid"),
    ),
    "graph_edges": (
        "data/graph/edges",
        "indexes/graph_edge_chunks.parquet",
        ("edge_cid", "src"),
    ),
    "graph_outgoing_adjacency": (
        "data/graph/adjacency/outgoing",
        "indexes/graph_outgoing_adjacency.parquet",
        ("node_cid", "first_key"),
    ),
    "graph_incoming_adjacency": (
        "data/graph/adjacency/incoming",
        "indexes/graph_incoming_adjacency.parquet",
        ("node_cid", "first_key"),
    ),
    "vectors": (
        "data/vectors",
        "indexes/vector_chunks.parquet",
        ("entry_cid", "first_key"),
    ),
}

# Compact indexes for these families are probed with
# ``first_key <= key <= last_key``. Shards must be internally sorted and
# ranges must be disjoint. Vectors are centroid-routed; graph edges are
# walked via adjacency.
RANGE_ROUTED_FAMILIES: Final = frozenset(
    {
        "corpus",
        "bm25_documents",
        "bm25_postings",
        "graph_nodes",
        "graph_outgoing_adjacency",
        "graph_incoming_adjacency",
    }
)


class GraphragEngineError(HfGraphragSchemaError):
    """Raised when a shared GraphRAG engine helper cannot complete."""


_SHA256_KEY_RE = re.compile(
    r"^(?:sha256:)?([0-9a-f]{64})(.*)$", re.IGNORECASE
)
CIDV1_PREFIX = "bafkrei"


def is_cidv1_key(value: Any) -> bool:
    """Return True when *value* is a CIDv1 raw/sha2-256 (``bafkrei…``) key."""

    text = str(value or "").strip()
    return text.startswith(CIDV1_PREFIX) and len(text) >= 50


def sha256_key_to_cidv1(value: Any) -> str:
    """Convert a SHA-256 hex / ``sha256:`` routing key to CIDv1.

    Bare 64-hex, ``sha256:<hex>``, and ``<hex>:<suffix>`` keys become
    ``bafkrei…`` (suffix preserved). Values that are already CIDv1, or
    that are not SHA-256 keys, are returned unchanged. File-integrity
    ``sha256`` columns are not routing keys and should not be passed here.
    """

    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if is_cidv1_key(text):
        return text
    match = _SHA256_KEY_RE.match(text)
    if match is None:
        return text
    digest = bytes.fromhex(match.group(1))
    suffix = match.group(2) or ""
    return cid_v1_from_digest(digest) + suffix


def remap_sha256_identity_fields(
    payload: Any, *, fields: Sequence[str] | None = None
) -> Any:
    """Recursively rewrite SHA-256 identity strings in mappings/lists."""

    names = tuple(fields) if fields is not None else (
        "entry_cid",
        "node_cid",
        "edge_cid",
        "source_node_cid",
        "target_node_cid",
        "neighbor_node_cid",
        "chunk_cid",
        "text_cid",
        "content_cid",
        "first_key",
        "last_key",
    )
    named = frozenset(names)

    def _walk(item: Any, *, field: str | None) -> Any:
        if isinstance(item, Mapping):
            return {
                key: _walk(value, field=str(key))
                for key, value in item.items()
            }
        if isinstance(item, list):
            return [_walk(value, field=field) for value in item]
        if isinstance(item, str) and (
            field in named or (field or "").endswith("_cid") or item.startswith("sha256:")
        ):
            if field in {"record_sha256", "sha256", "body_hash", "text_hash"}:
                return item
            return sha256_key_to_cidv1(item)
        return item

    return _walk(payload, field=None)


def retrieval_method_for_edge_type(edge_type: str) -> str:
    """Map an edge type to SkillCenter ``retrieval_methods`` tokens."""

    text = str(edge_type or "").strip()
    if text in {"BM25_NEIGHBOR_OF", CONTAINS_TERM_EDGE}:
        return "bm25"
    if text in {"EMBEDDING_NEIGHBOR_OF", "SIMILAR_TO"}:
        return "embedding"
    return "graph"


def edge_establishes_legal_authority(edge_type: str) -> bool:
    """Similarity / term-containment edges never establish legal authority."""

    return str(edge_type or "").strip() not in SIMILARITY_EDGE_TYPES


def assign_document_identities(
    rows: Sequence[Mapping[str, Any]],
    *,
    digest_field: str = "content_sha256",
    cid_field: str = PRIMARY_KEY,
    index_field: str = "document_index",
    start_index: int = 0,
) -> list[dict[str, Any]]:
    """Attach dense ``document_index`` and CIDv1 ``entry_cid`` to corpus rows.

    Consumers may already have ``entry_cid``; the digest is used only when
    the CID is missing. ``legal_id`` and other domain columns are preserved.
    """

    if start_index < 0:
        raise GraphragEngineError("start_index must be >= 0")
    assigned: list[dict[str, Any]] = []
    for offset, row in enumerate(rows):
        payload = dict(row)
        cid = str(payload.get(cid_field) or "").strip()
        if cid and not is_cidv1_key(cid):
            converted = sha256_key_to_cidv1(cid)
            if is_cidv1_key(converted):
                cid = converted
        if not cid:
            digest = str(payload.get(digest_field) or "").strip()
            digest = digest.removeprefix("sha256:")
            if len(digest) == 64:
                cid = cid_v1_from_digest(bytes.fromhex(digest))
            else:
                raise GraphragEngineError(
                    f"row {offset} is missing {cid_field} and {digest_field}"
                )
        payload[cid_field] = cid
        payload[index_field] = start_index + offset
        assigned.append(payload)
    return assigned


def nest_exploded_postings(
    hits: Sequence[Mapping[str, Any]],
    *,
    document_count: int,
    document_lengths: Mapping[int, int] | None = None,
    postings_per_row: int = DEFAULT_POSTINGS_PER_ROW,
    k1: float = DEFAULT_K1,
    b: float = DEFAULT_B,
    title_weight: float = DEFAULT_TITLE_WEIGHT,
    body_weight: float = DEFAULT_BODY_WEIGHT,
) -> list[dict[str, Any]]:
    """Convert exploded ``(term, document_index, tf)`` hits into nested cells.

    Title/body frequencies default to ``tf`` / 0 when a consumer only has a
    single field. Cells are bounded to *postings_per_row* pointers.
    """

    if postings_per_row < 1 or postings_per_row > MAX_POINTERS_PER_ROW:
        raise GraphragEngineError("postings_per_row exceeds the 4,096 pointer bound")
    grouped: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for hit in hits:
        term = str(hit.get("term") or "").strip()
        if not term:
            raise GraphragEngineError("posting hit is missing term")
        raw_indices = hit.get("document_indices")
        if raw_indices:
            pairs = [(int(index), hit) for index in raw_indices]
        elif hit.get("document_index") is not None:
            pairs = [(int(hit.get("document_index")), hit)]
        else:
            continue
        title_list = list(hit.get("title_frequencies") or ())
        body_list = list(hit.get("body_frequencies") or ())
        for offset, (index, source) in enumerate(pairs):
            title_tf = int(source.get("title_tf", source.get("title_frequency", 0)) or 0)
            body_tf = int(source.get("body_tf", source.get("body_frequency", source.get("tf", 0))) or 0)
            if offset < len(title_list):
                title_tf = int(title_list[offset] or 0)
            if offset < len(body_list):
                body_tf = int(body_list[offset] or 0)
            if title_tf == 0 and body_tf == 0:
                body_tf = int(source.get("tf") or 0) or 1
            grouped[term].append((index, title_tf, body_tf))
    lengths = document_lengths or {}
    rows: list[dict[str, Any]] = []
    for term in sorted(grouped):
        values = sorted(grouped[term], key=lambda item: item[0])
        df = len(values)
        corpus_frequency = sum(title + body for _, title, body in values)
        chunk_count = max(1, math.ceil(df / postings_per_row))
        for chunk_index, start in enumerate(range(0, df, postings_per_row)):
            selected = values[start : start + postings_per_row]
            indices = [item[0] for item in selected]
            rows.append(
                {
                    "b": float(b),
                    "body_frequencies": [item[2] for item in selected],
                    "body_weight": float(body_weight),
                    "corpus_frequency": corpus_frequency,
                    "document_frequency": df,
                    "document_indices": indices,
                    "document_lengths": [int(lengths.get(index, 0)) for index in indices],
                    "idf": fts5_idf(document_count, df),
                    "k1": float(k1),
                    "posting_chunk_count": chunk_count,
                    "posting_chunk_index": chunk_index,
                    "schema_version": BM25_POSTING_SCHEMA_VERSION,
                    "term": term,
                    "title_frequencies": [item[1] for item in selected],
                    "title_weight": float(title_weight),
                }
            )
    return rows


def build_contains_term_graph(
    term_to_documents: Mapping[str, Sequence[tuple[str, float]]],
    *,
    kind: str = "hf_graphrag_bm25_term",
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Patent-style BM25 vocabulary on the graph: term nodes + ``contains_term``.

    *term_to_documents* maps a term to ``(document_node_cid, score)`` pairs.
    Consumers supply already-CID document endpoints.
    """

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    for term in sorted(term_to_documents):
        term_cid = cid_v1(
            json.dumps(
                {"kind": kind, "term": term},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        nodes.append(
            GraphNode(
                node_cid=term_cid,
                node_type=BM25_TERM_NODE,
                label=term,
            )
        )
        for document_cid, score in term_to_documents[term]:
            document_cid = str(document_cid)
            edge_cid = cid_v1(f"{document_cid}\t{CONTAINS_TERM_EDGE}\t{term_cid}".encode("utf-8"))
            edges.append(
                GraphEdge(
                    edge_cid=edge_cid,
                    edge_type=CONTAINS_TERM_EDGE,
                    source_node_cid=document_cid,
                    target_node_cid=term_cid,
                    score=float(score),
                    retrieval_method="bm25",
                )
            )
    return nodes, edges


def dataset_card_configs(
    *,
    extra: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Hugging Face dataset-card ``configs:`` block. Consumers may overlay paths."""

    mapping = dict(STANDARD_VIEWER_CONFIGS)
    if extra:
        mapping.update({str(key): str(value) for key, value in extra.items()})
    return [
        {
            "config_name": name,
            "data_files": [{"split": "train", "path": path}],
        }
        for name, path in mapping.items()
    ]


def build_digest_manifest(
    *,
    dataset_repo_id: str,
    schema_version: str,
    counts: Mapping[str, Any],
    indexes: Mapping[str, Mapping[str, Any]] | None = None,
    bm25: Mapping[str, Any] | None = None,
    vector: Mapping[str, Any] | None = None,
    graph: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Thin-client manifest: primary key, shard catalog, BM25/vector/graph facts."""

    payload: dict[str, Any] = {
        "counts": dict(counts),
        "dataset_repo_id": str(dataset_repo_id),
        "engine_schema_version": ENGINE_SCHEMA_VERSION,
        "indexes": {key: dict(value) for key, value in (indexes or {}).items()},
        "primary_key": PRIMARY_KEY,
        "schema_version": str(schema_version),
        "viewer_configs": dict(STANDARD_VIEWER_CONFIGS),
    }
    if bm25:
        payload["bm25"] = dict(bm25)
    if vector:
        payload["vector"] = dict(vector)
    if graph:
        payload["graph"] = dict(graph)
    if extra:
        for key, value in extra.items():
            payload[str(key)] = value
    return payload


def write_hub_search_pack(
    release_root: str | Path,
    *,
    repo_id: str,
    pretty_name: str,
    query_script: str | Path | None = None,
    semantic_traversal: str | Path | None = None,
    skill_name: str = "query-hf-graphrag",
    domain_notes: str = "",
) -> dict[str, str]:
    """Write Hub search scripts plus an agent skill so consumers can query.

    Layout matches SkillCenter:

    * ``scripts/query_hf_graphrag.py`` standalone thin client
    * ``scripts/semantic_traversal.py`` when supplied
    * ``skill/<skill_name>/SKILL.md`` with BM25 / vector / graph recipes
    """

    root = Path(release_root).expanduser().resolve()
    copied = _copy_search_scripts(
        root,
        query_script=query_script or _default_query_script(),
        semantic_traversal=semantic_traversal,
    )
    skill_root = root / "skill" / skill_name
    if skill_root.exists():
        shutil.rmtree(skill_root)
    (skill_root / "scripts").mkdir(parents=True)
    (skill_root / "agents").mkdir(parents=True)
    (skill_root / "references").mkdir(parents=True)
    script_name = Path(copied.get("query_script") or "query_hf_graphrag.py").name
    (skill_root / "SKILL.md").write_text(
        _skill_markdown(
            skill_name=skill_name,
            repo_id=repo_id,
            pretty_name=pretty_name,
            script_name=script_name,
            domain_notes=domain_notes,
        ),
        encoding="utf-8",
    )
    (skill_root / "agents" / "openai.yaml").write_text(
        "interface:\n"
        f'  display_name: "Query {pretty_name}"\n'
        '  short_description: "Search the remote GraphRAG release"\n'
        f'  default_prompt: "Use ${skill_name} to search this Hugging Face '
        'GraphRAG release with BM25, vectors, or a bounded graph walk."\n',
        encoding="utf-8",
    )
    (skill_root / "references" / "schema.md").write_text(_schema_markdown(), encoding="utf-8")
    wrapper = skill_root / "scripts" / "query_hf_graphrag.py"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import runpy\n"
        "ROOT = Path(__file__).resolve().parents[3]\n"
        "for candidate in (\n"
        f'    ROOT / "scripts" / "{script_name}",\n'
        '    ROOT / "scripts" / "query_hf_graphrag.py",\n'
        "):\n"
        "    if candidate.is_file():\n"
        '        runpy.run_path(str(candidate), run_name="__main__")\n'
        "        break\n"
        "else:\n"
        '    raise SystemExit("GraphRAG query client is missing from this release")\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    copied["skill"] = skill_root.relative_to(root).as_posix()
    return copied


def _default_query_script() -> Path:
    return Path(__file__).with_name("query_hf_graphrag.py")


def _skill_markdown(
    *,
    skill_name: str,
    repo_id: str,
    pretty_name: str,
    script_name: str,
    domain_notes: str,
) -> str:
    notes = domain_notes.strip()
    extra = f"\n{notes}\n" if notes else ""
    return f"""---
name: {skill_name}
description: Query the CID-keyed {pretty_name} GraphRAG release on Hugging Face with bounded BM25, centroid-routed vectors, adjacency neighbors, and graph walks. Use when an agent must retrieve lexical, semantic, or graph context without downloading the full corpus.
---

# Query {pretty_name} on Hugging Face

Use the bundled search script. It fetches only the manifest, compact locators,
matching posting/vector/adjacency shards, and corpus rows for final hits.

Repository: `{repo_id}`. Primary key is `entry_cid`. Integer `document_index`
is a compact pointer, not an identity.
{extra}
## Choose retrieval

- `bm25` for citations, docket numbers, quoted terms, and exact names.
- `vector` for paraphrases and topical similarity.
- `neighbors` / `walk` after you have a `node_cid`.
- Merge BM25 and vector hits on `entry_cid`. Similarity edges (`BM25_NEIGHBOR_OF`, `EMBEDDING_NEIGHBOR_OF`, `contains_term`) are retrieval proposals only.

## BM25

```bash
python scripts/{script_name} \\
  --repo-id {repo_id} \\
  --revision <pinned-commit> \\
  bm25 "clean air act section 111" --top-k 10
```

Local checkout:

```bash
python scripts/{script_name} --local-root . bm25 "clean air act section 111"
```

Install `pyarrow` and `huggingface_hub`. Set `HF_TOKEN` for private datasets.
Always pin `--revision` for remote queries; never use `main`.

## Neighbors and walks

```bash
python scripts/{script_name} --local-root . neighbors <node-cid> --direction both --limit 25
python scripts/{script_name} --local-root . walk <node-cid> --max-depth 2 --max-nodes 100
```

Inspect `fetch_trace`. A budget stop is a partial walk, not proof that no
further path exists. Treat hits as `context_only`.

Read [references/schema.md](references/schema.md) for locator and posting
contracts.
"""


def _schema_markdown() -> str:
    return """# GraphRAG remote release schema

`manifest.json` declares `primary_key` (`entry_cid`), BM25 constants, vector
layout, and compact index descriptors. Verify `sha256` / `cid` before parsing
a shard.

## Identity

- `entry_cid`: CIDv1 primary identity.
- `document_index`: dense `0..N-1` pointer used only inside postings.
- Data shards are Zstandard Parquet with at most 4,096 rows.

## BM25

`indexes/bm25_keyword_shards.parquet` maps inclusive `first_key`/`last_key`
term ranges to posting shards. Nested posting rows contain `term` plus aligned
`document_indices`, `document_lengths`, `title_frequencies`, `body_frequencies`,
and `idf`. Posting shards must be globally sorted by term with disjoint
ranges; a term never spans two shards. In-memory cells: `write_term_sorted_posting_shards`.
Already-dumped shards (any consumer): `pack_range_routed_family` at build time
or `repair_graphrag_range_routing` on a release root. Both use the same
resource-aware process pool. Exploded `(term, legal_id, tf)` shards remain readable.

## Vectors

`indexes/vector_chunks.parquet` maps centroid groups to at most two physical
shards of 4,096 rows. Probe a few centroids, then exact-score inside those
shards.

## Graph

`indexes/graph_outgoing_adjacency.parquet` and
`indexes/graph_incoming_adjacency.parquet` map `node_cid` ranges to paged
adjacency. Each page holds at most 4,096 pointers. Similarity neighbors cannot
establish legal authority.
"""


def _copy_search_scripts(
    root: Path,
    *,
    query_script: str | Path | None,
    semantic_traversal: str | Path | None,
) -> dict[str, str]:
    copied: dict[str, str] = {}
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    generic = _default_query_script()
    dest_generic = root / "scripts" / generic.name
    shutil.copy2(generic, dest_generic)
    copied["query_script_generic"] = dest_generic.relative_to(root).as_posix()
    if query_script is not None:
        dest = root / "scripts" / Path(query_script).name
        shutil.copy2(query_script, dest)
        copied["query_script"] = dest.relative_to(root).as_posix()
    else:
        copied["query_script"] = copied["query_script_generic"]
    if semantic_traversal is not None:
        dest = root / "scripts" / Path(semantic_traversal).name
        shutil.copy2(semantic_traversal, dest)
        copied["semantic_traversal"] = dest.relative_to(root).as_posix()
    return copied


def bundle_query_assets(
    release_root: str | Path,
    *,
    query_script: str | Path | None = None,
    semantic_traversal: str | Path | None = None,
    skill_dir: str | Path | None = None,
    repo_id: str = "",
    pretty_name: str = "",
    domain_notes: str = "",
) -> dict[str, str]:
    """Copy search scripts and write a Hub skill pack when one is not supplied."""

    root = Path(release_root).expanduser().resolve()
    if skill_dir is not None:
        copied = _copy_search_scripts(
            root,
            query_script=query_script,
            semantic_traversal=semantic_traversal,
        )
        dest = root / "skill" / Path(skill_dir).name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(
            skill_dir,
            dest,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        copied["skill"] = dest.relative_to(root).as_posix()
        return copied
    return write_hub_search_pack(
        root,
        repo_id=repo_id or "local/graphrag-release",
        pretty_name=pretty_name or "GraphRAG",
        query_script=query_script,
        semantic_traversal=semantic_traversal,
        domain_notes=domain_notes,
    )


def _parquet_key_ends(
    path: Path,
    key_fields: Sequence[str],
    *,
    require_sorted: bool = False,
) -> tuple[str, str, int] | None:
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    names = set(parquet.schema_arrow.names)
    column = next((name for name in key_fields if name in names), None)
    if column is None:
        return None
    table = pq.read_table(path, columns=[column])
    if table.num_rows == 0:
        raise GraphragEngineError(f"{path} is empty")
    values = [
        "" if value is None else str(value) for value in table.column(0).to_pylist()
    ]
    first, last = values[0], values[-1]
    if require_sorted:
        unsorted = first > last or any(
            values[index] > values[index + 1] for index in range(len(values) - 1)
        )
        if unsorted:
            raise GraphragEngineError(
                f"{path} key column {column!r} is not sorted "
                f"(first={first!r}, last={last!r}). "
                "Call repair_graphrag_range_routing() to globally sort shards."
            )
    else:
        first, last = min(values), max(values)
    return first, last, int(table.num_rows)


def _assert_disjoint_compact_rows(
    compact: Sequence[CompactIndexRow], *, family: str
) -> None:
    ordered = sorted(
        compact, key=lambda row: (row.first_key, row.shard_id, row.relative_path)
    )
    previous: CompactIndexRow | None = None
    for row in ordered:
        if previous is not None and previous.last_key >= row.first_key:
            raise GraphragEngineError(
                f"{family} locator ranges overlap or are not ordered: "
                f"[{previous.first_key!r}, {previous.last_key!r}] vs "
                f"[{row.first_key!r}, {row.last_key!r}] "
                f"({previous.relative_path} / {row.relative_path}). "
                "Call repair_graphrag_range_routing() to globally sort shards."
            )
        previous = row


def index_parquet_family(
    root: str | Path,
    *,
    data_dir: str,
    index_path: str,
    key_fields: Sequence[str],
    kind: str,
    glob: str = "**/*.parquet",
    validate: bool = True,
) -> CompactIndexWriteResult:
    """Build a CID+SHA-256 compact locator over existing Parquet shards.

    When the family has more than 4,096 shards the compact index itself is
    sharded (hierarchical route pages) so every physical file stays bounded.
    """

    from .repair import RANGE_ROUTED_FAMILIES as routed
    from .repair import describe_family_files_parallel, list_family_parquet_files

    release_root = Path(root).expanduser().resolve()
    family_dir = release_root / data_dir
    if not family_dir.is_dir():
        raise GraphragEngineError(f"missing data directory: {family_dir}")
    files = list_family_parquet_files(release_root, data_dir, glob=glob)
    if not files:
        raise GraphragEngineError(f"no parquet shards under {family_dir}")

    require_sorted = bool(validate) and kind in routed
    described = describe_family_files_parallel(
        files,
        root=release_root,
        key_fields=key_fields,
        require_sorted=require_sorted,
    )
    compact: list[CompactIndexRow] = []
    for shard_id, item in enumerate(described):
        try:
            compact.append(
                CompactIndexRow(
                    relative_path=str(item["relative_path"]),
                    sha256=str(item["sha256"]),
                    size_bytes=int(item["size_bytes"]),
                    row_count=int(item["row_count"]),
                    shard_id=shard_id,
                    first_key=str(item["first_key"]),
                    last_key=str(item["last_key"]),
                    kind=kind,
                    content_cid=item.get("content_cid"),
                )
            )
        except HfGraphragSchemaError as exc:
            raise GraphragEngineError(
                f"{item.get('relative_path')} locator range is invalid ({exc}). "
                "Call repair_graphrag_range_routing() to globally sort shards."
            ) from exc
    if not compact:
        raise GraphragEngineError(
            f"no locator-keyed parquet shards under {family_dir}"
        )
    if require_sorted:
        _assert_disjoint_compact_rows(compact, family=kind)
    index_relative = normalize_relative_artifact_path(index_path)
    if len(compact) <= MAX_ROUTING_ROWS_PER_INDEX:
        target = release_root / index_relative
        write_zstd_parquet(
            target,
            [row.to_dict() for row in compact],
            max_rows=MAX_ROUTING_ROWS_PER_INDEX,
            config=ArtifactWriterConfig(max_rows_per_shard=MAX_ROUTING_ROWS_PER_INDEX),
        )
        index_descriptor = describe_file(
            target,
            root=release_root,
            row_count=len(compact),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=COMPACT_INDEX_SCHEMA_VERSION,
        )
        return CompactIndexWriteResult(
            index_path=index_relative,
            row_count=len(compact),
            shard_count=1,
            descriptor=index_descriptor.to_dict(),
            hierarchical=False,
        )
    stem = index_relative.rsplit(".", 1)[0]
    result = write_bounded_shards(
        [row.to_dict() for row in compact],
        root=release_root,
        data_dir=stem,
        index_path=index_relative,
        family=ArtifactFamily.ROUTING_INDEX,
        kind=kind,
        primary_keys=("first_key",),
        tie_breakers=("shard_id",),
        document_index_field=None,
        sort=False,
        schema_id=COMPACT_INDEX_SCHEMA_VERSION,
    )
    return CompactIndexWriteResult(
        index_path=index_relative,
        row_count=len(compact),
        shard_count=len(result.data_descriptors),
        descriptor=(
            result.compact_index_descriptor.to_dict()
            if result.compact_index_descriptor is not None
            else {}
        ),
        hierarchical=True,
    )


@dataclass(frozen=True, slots=True)
class CompactIndexWriteResult:
    index_path: str
    row_count: int
    shard_count: int
    descriptor: dict[str, Any]
    hierarchical: bool


def write_standard_compact_indexes(
    root: str | Path,
    *,
    families: Sequence[str] | None = None,
    validate: bool = True,
    repair: bool = False,
) -> dict[str, CompactIndexWriteResult]:
    """Write SkillCenter/patent locator tables for every present data family.

    Range-routed families (BM25 keywords, CID/node locators, adjacency)
    must have internally sorted shards and disjoint ``[first_key, last_key]``
    ranges. Set *repair* to rewrite those families in place before indexing.
    """

    release_root = Path(root).expanduser().resolve()
    selected = tuple(families) if families is not None else tuple(STANDARD_INDEX_PATHS)
    if repair:
        from .repair import RANGE_ROUTED_FAMILIES as routed
        from .repair import repair_graphrag_range_routing

        repairable = tuple(
            family
            for family in selected
            if family in routed and (release_root / STANDARD_INDEX_PATHS[family][0]).is_dir()
        )
        if repairable:
            repair_graphrag_range_routing(release_root, families=repairable)
    written: dict[str, CompactIndexWriteResult] = {}
    for family in selected:
        data_dir, index_path, key_fields = STANDARD_INDEX_PATHS[family]
        family_dir = release_root / data_dir
        if not family_dir.is_dir():
            continue
        try:
            written[family] = index_parquet_family(
                release_root,
                data_dir=data_dir,
                index_path=index_path,
                key_fields=key_fields,
                kind=family,
                validate=validate,
            )
        except GraphragEngineError as exc:
            if "empty" in str(exc).lower() or "no locator-keyed" in str(exc) or "no parquet shards" in str(exc):
                print(f"  skip {family}: {exc}", flush=True)
                continue
            raise
    if written:
        from .repair import _update_manifest_indexes

        _update_manifest_indexes(release_root, written)
    return written


def convert_json_routing_to_parquet(
    root: str | Path,
    json_path: str,
    *,
    index_path: str,
    kind: str,
    key_fields: Sequence[str] = ("first_key",),
) -> CompactIndexWriteResult:
    """Upgrade a JSON routing map to a digest-backed compact Parquet index."""

    release_root = Path(root).expanduser().resolve()
    payload = json.loads((release_root / json_path).read_text(encoding="utf-8"))
    entries = payload.get("routing") if isinstance(payload, Mapping) else payload
    if isinstance(payload, Mapping) and "shards" in payload and not entries:
        entries = payload["shards"]
    if not isinstance(entries, Sequence):
        raise GraphragEngineError(f"{json_path} has no routing/shards list")
    compact: list[CompactIndexRow] = []
    for shard_id, item in enumerate(entries):
        relative = normalize_relative_artifact_path(str(item["relative_path"]))
        target = release_root / relative
        first_key = str(item.get("first_key") or "")
        last_key = str(item.get("last_key") or "")
        row_count = int(item.get("row_count") or 0)
        if not first_key or not last_key or row_count <= 0:
            ends = _parquet_key_ends(target, key_fields)
            if ends is None:
                raise GraphragEngineError(
                    f"{target} has none of the locator key columns {tuple(key_fields)}"
                )
            first_key, last_key, row_count = ends
        descriptor = describe_file(
            target,
            root=release_root,
            row_count=row_count,
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=COMPACT_INDEX_SCHEMA_VERSION,
            first_key=first_key,
            last_key=last_key,
            shard_id=int(item.get("shard_id", shard_id)),
        )
        compact.append(
            CompactIndexRow(
                relative_path=relative,
                sha256=descriptor.sha256,
                size_bytes=descriptor.size_bytes,
                row_count=row_count,
                shard_id=int(item.get("shard_id", shard_id)),
                first_key=first_key,
                last_key=last_key,
                kind=kind,
                content_cid=descriptor.content_cid,
            )
        )
    if kind in RANGE_ROUTED_FAMILIES:
        _assert_disjoint_compact_rows(compact, family=kind)
    return _write_compact_rows(release_root, compact, index_path=index_path, kind=kind)


def _write_compact_rows(
    release_root: Path,
    compact: Sequence[CompactIndexRow],
    *,
    index_path: str,
    kind: str,
) -> CompactIndexWriteResult:
    index_relative = normalize_relative_artifact_path(index_path)
    if len(compact) <= MAX_ROUTING_ROWS_PER_INDEX:
        target = release_root / index_relative
        write_zstd_parquet(
            target,
            [row.to_dict() for row in compact],
            max_rows=MAX_ROUTING_ROWS_PER_INDEX,
            config=ArtifactWriterConfig(max_rows_per_shard=MAX_ROUTING_ROWS_PER_INDEX),
        )
        descriptor = describe_file(
            target,
            root=release_root,
            row_count=len(compact),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=COMPACT_INDEX_SCHEMA_VERSION,
        )
        return CompactIndexWriteResult(
            index_path=index_relative,
            row_count=len(compact),
            shard_count=1,
            descriptor=descriptor.to_dict(),
            hierarchical=False,
        )
    stem = index_relative.rsplit(".", 1)[0]
    result = write_bounded_shards(
        [row.to_dict() for row in compact],
        root=release_root,
        data_dir=stem,
        index_path=index_relative,
        family=ArtifactFamily.ROUTING_INDEX,
        kind=kind,
        primary_keys=("first_key",),
        tie_breakers=("shard_id",),
        document_index_field=None,
        sort=False,
        schema_id=COMPACT_INDEX_SCHEMA_VERSION,
    )
    return CompactIndexWriteResult(
        index_path=index_relative,
        row_count=len(compact),
        shard_count=len(result.data_descriptors),
        descriptor=(
            result.compact_index_descriptor.to_dict()
            if result.compact_index_descriptor is not None
            else {}
        ),
        hierarchical=True,
    )


from .repair import (
    GRAPHRAG_BYTES_PER_WORKER,
    RANGE_ROUTED_FAMILIES as _REPAIR_RANGE_ROUTED_FAMILIES,
    RangeRepairResult,
    RangeRoutingDiagnosis,
    covering_locator_rows,
    diagnose_range_routing,
    graphrag_process_pool_plan,
    list_family_parquet_files,
    pack_range_routed_family,
    posting_cell_sort_key,
    repair_graphrag_range_routing,
    rewrite_range_routed_family,
    write_term_sorted_posting_shards,
)

# repair.py keeps a copy for CLI defaults; fail closed if they drift.
if _REPAIR_RANGE_ROUTED_FAMILIES != RANGE_ROUTED_FAMILIES:
    raise GraphragEngineError("RANGE_ROUTED_FAMILIES drifted between engine and repair")

__all__ = [
    "BM25_TERM_NODE",
    "CONTAINS_TERM_EDGE",
    "ENGINE_SCHEMA_VERSION",
    "GRAPHRAG_BYTES_PER_WORKER",
    "PRIMARY_KEY",
    "RANGE_ROUTED_FAMILIES",
    "SIMILARITY_EDGE_TYPES",
    "STANDARD_VIEWER_CONFIGS",
    "CompactIndexWriteResult",
    "GraphragEngineError",
    "RangeRepairResult",
    "RangeRoutingDiagnosis",
    "assign_document_identities",
    "build_contains_term_graph",
    "build_digest_manifest",
    "bundle_query_assets",
    "convert_json_routing_to_parquet",
    "covering_locator_rows",
    "dataset_card_configs",
    "diagnose_range_routing",
    "edge_establishes_legal_authority",
    "graphrag_process_pool_plan",
    "index_parquet_family",
    "is_cidv1_key",
    "list_family_parquet_files",
    "nest_exploded_postings",
    "pack_range_routed_family",
    "posting_cell_sort_key",
    "remap_sha256_identity_fields",
    "repair_graphrag_range_routing",
    "retrieval_method_for_edge_type",
    "sha256_key_to_cidv1",
    "rewrite_range_routed_family",
    "write_hub_search_pack",
    "write_standard_compact_indexes",
    "write_term_sorted_posting_shards",
]
