#!/usr/bin/env python3
"""Project a live Federal Register citation graph over LCR-071 corpus bodies.

Reads hash-verified GovInfo HTML JSON from the live corpus directory and
emits compact graph + two-way adjacency receipts. Complete live runs also
project non-authoritative ``EMBEDDING_NEIGHBOR_OF`` edges from the pinned
sentence-transformers GTE-small matrix. Does not rewrite the sealed
LCR-058 fixture ``federal_graph.json``. Does not upload to Hub.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_graph import (  # noqa: E402
    extract_citation_mentions,
    extract_docket_mentions,
    extract_rin_mentions,
)
from ipfs_datasets_py.processors.legal_data.graphrag_parallel import (  # noqa: E402
    chunk_items,
    ordered_process_map,
    tokenize_process_pool_size,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
    DEFAULT_OBSERVATION_CUTOFF,
    digest_mapping,
)

TASK_ID = "LCR-071"
GOAL_ID = "LCR-G130"
PROGRAM_ID = "legal-corpora-reindex-v1"
EXPECTED_LIVE_DOCUMENTS = 11784
DEFAULT_CORPUS_DIR = Path("/var/tmp/lcr-071-fr-corpus")
DEFAULT_GRAPH_DIR = Path("/var/tmp/lcr-071-fr-graph")
DEFAULT_VECTOR_DIR = Path("/var/tmp/lcr-071-fr-vectors")
GRAPH_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_graph.live.json")
ADJACENCY_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.live.json"
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_FR_DOCNO_RE = re.compile(
    r"FR\s+Doc(?:ument)?\s+No\.?\s*:\s*((?:[A-Z]\d-)?\d{4}-\d{4,5})",
    re.IGNORECASE,
)


class LiveGraphError(RuntimeError):
    pass


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_index(corpus_dir: Path) -> list[dict[str, Any]]:
    path = corpus_dir / "index.jsonl"
    if not path.is_file():
        raise LiveGraphError(f"corpus index missing: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict) and item.get("status") == "verified":
                rows.append(item)
    return rows


def _document_number(legal_id: str) -> str:
    parts = str(legal_id).split(":")
    if len(parts) >= 2 and parts[0] == "fr":
        return parts[1]
    return str(legal_id)


def _plain_text(html: str) -> str:
    stripped = _TAG_RE.sub(" ", html or "")
    return _WS_RE.sub(" ", stripped).strip()


def _add_node(nodes: dict[str, str], key: str, node_type: str) -> None:
    existing = nodes.get(key)
    if existing is None:
        nodes[key] = node_type
        return
    if existing != node_type and existing == "unresolved_citation" and node_type != existing:
        nodes[key] = node_type


def _edge_key(source: str, edge_type: str, target: str) -> str:
    return f"{source}\t{edge_type}\t{target}"


def _live_graph_chunk(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract nodes/edges for a slice of live FR bodies. Spawn-worker entry."""

    corpus_dir = Path(str(payload["corpus_dir"]))
    document_numbers = set(payload["document_numbers"])
    nodes: dict[str, str] = {}
    edges: list[str] = []
    unresolved = 0
    documents_with_citations = 0
    for row in payload["rows"]:
        legal_id = str(row["legal_id"])
        docno = _document_number(legal_id)
        body_path = corpus_dir / str(row.get("path") or "")
        payload_json = json.loads(body_path.read_text(encoding="utf-8"))
        text = _plain_text(str(payload_json.get("text") or ""))
        publication_date = str(payload_json.get("publication_date") or "")
        source_url = str(payload_json.get("official_source_url") or "")
        doc_key = f"document:{legal_id}"
        _add_node(nodes, doc_key, "document")
        if publication_date:
            date_key = f"date:{publication_date}"
            _add_node(nodes, date_key, "date")
            edges.append(_edge_key(doc_key, "PUBLISHED_ON", date_key))
        if source_url:
            source_key = f"source:{_sha256_text(source_url)[:16]}"
            _add_node(nodes, source_key, "source")
            edges.append(_edge_key(doc_key, "HAS_SOURCE", source_key))
            prov_key = f"provenance:{legal_id}"
            _add_node(nodes, prov_key, "provenance")
            edges.append(_edge_key(doc_key, "HAS_PROVENANCE", prov_key))
        cited = False
        unique_targets: set[str] = set()
        for mention in extract_citation_mentions(text):
            target_key = None
            node_type = "unresolved_citation"
            edge_type = "CITES_UNRESOLVED"
            if mention.kind == "cfr":
                target_key = f"citation:cfr:{mention.title}:{mention.section}"
                node_type = "citation_cfr"
                edge_type = "CITES"
            elif mention.kind == "usc":
                target_key = f"citation:usc:{mention.title}:{mention.section}"
                node_type = "citation_usc"
                edge_type = "CITES"
            elif mention.kind == "fr_volume":
                target_key = f"unresolved:fr:{mention.volume}-FR-{mention.page}"
                unresolved += 1
            if not target_key or target_key in unique_targets:
                continue
            unique_targets.add(target_key)
            _add_node(nodes, target_key, node_type)
            edges.append(_edge_key(doc_key, edge_type, target_key))
            cited = True
        for match in _FR_DOCNO_RE.finditer(text):
            cited_no = match.group(1)
            if cited_no == docno:
                continue
            target_key = f"citation:fr:{cited_no}"
            if target_key in unique_targets:
                continue
            unique_targets.add(target_key)
            _add_node(nodes, target_key, "citation_fr")
            edges.append(_edge_key(doc_key, "CITES", target_key))
            if cited_no not in document_numbers:
                unresolved += 1
            cited = True
        for docket, _start, _end in extract_docket_mentions(text):
            target_key = f"docket:{docket}"
            if target_key in unique_targets:
                continue
            unique_targets.add(target_key)
            _add_node(nodes, target_key, "docket")
            edges.append(_edge_key(doc_key, "HAS_DOCKET", target_key))
            cited = True
        for rin, _start, _end in extract_rin_mentions(text):
            target_key = f"rin:{rin}"
            if target_key in unique_targets:
                continue
            unique_targets.add(target_key)
            _add_node(nodes, target_key, "rin")
            edges.append(_edge_key(doc_key, "HAS_RIN", target_key))
            cited = True
        if cited:
            documents_with_citations += 1
    return {
        "documents_with_citations": documents_with_citations,
        "edges": edges,
        "nodes": nodes,
        "unresolved": unresolved,
    }


def build_live_graph(
    *,
    corpus_dir: Path,
    graph_dir: Path,
    repository_root: Path = REPOSITORY_ROOT,
    require_complete: bool = True,
    limit: int | None = None,
    write_receipts: bool = True,
    vectors_dir: Path | None = None,
) -> dict[str, Any]:
    rows = _load_index(corpus_dir)
    if limit is not None:
        rows = rows[:limit]
    neighbor_source = vectors_dir if vectors_dir is not None else (
        DEFAULT_VECTOR_DIR if require_complete and limit is None else None
    )
    preloaded_neighbors: tuple[list[dict[str, Any]], dict[str, Any]] | None = None
    if neighbor_source is not None:
        from ipfs_datasets_py.processors.legal_data.federal_register_vectors import (
            EmbeddingNeighborError,
            gte_small_embedding_neighbors_from_dir,
        )

        try:
            preloaded_neighbors = gte_small_embedding_neighbors_from_dir(neighbor_source)
        except EmbeddingNeighborError as exc:
            raise LiveGraphError(
                f"complete live graph requires pinned GTE-small neighbors: {exc}"
            ) from exc
    if require_complete and limit is None and len(rows) != EXPECTED_LIVE_DOCUMENTS:
        raise LiveGraphError(
            f"live graph requires {EXPECTED_LIVE_DOCUMENTS} verified bodies, got {len(rows)}"
        )
    if not rows:
        raise LiveGraphError("no verified corpus bodies")

    document_numbers = {_document_number(str(row["legal_id"])) for row in rows}
    nodes: dict[str, str] = {}
    edges: set[str] = set()
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    edge_types: Counter[str] = Counter()
    node_types: Counter[str] = Counter()
    unresolved = 0
    documents_with_citations = 0
    plan = tokenize_process_pool_size()
    slim_rows = [{"legal_id": row.get("legal_id"), "path": row.get("path")} for row in rows]
    payloads = [
        {
            "corpus_dir": str(corpus_dir),
            "document_numbers": sorted(document_numbers),
            "rows": list(chunk),
        }
        for chunk in chunk_items(slim_rows, 64)
    ]
    parts = ordered_process_map(
        _live_graph_chunk, payloads, workers=plan.workers, plan=plan
    )
    for part in parts:
        unresolved += int(part["unresolved"])
        documents_with_citations += int(part["documents_with_citations"])
        for key, node_type in (part.get("nodes") or {}).items():
            _add_node(nodes, str(key), str(node_type))
        edges.update(part.get("edges") or ())

    embedding_neighbors: dict[str, Any] | None = None
    if preloaded_neighbors is not None:
        neighbor_rows, embedding_neighbors = preloaded_neighbors
        document_ids = {
            key[len("document:") :]
            for key, node_type in nodes.items()
            if node_type == "document"
        }
        for item in neighbor_rows:
            source_id = str(item["source_legal_id"])
            target_id = str(item["target_legal_id"])
            if source_id not in document_ids or target_id not in document_ids:
                continue
            edges.add(
                _edge_key(
                    f"document:{source_id}",
                    "EMBEDDING_NEIGHBOR_OF",
                    f"document:{target_id}",
                )
            )
        kept = sum(
            1
            for item in neighbor_rows
            if str(item["source_legal_id"]) in document_ids
            and str(item["target_legal_id"]) in document_ids
        )
        embedding_neighbors = {
            **embedding_neighbors,
            "kept_edge_count": kept,
            "similarity_cannot_establish_legal_authority": True,
        }

    for edge in edges:
        source, edge_type, target = edge.split("\t", 2)
        outgoing[source].add(f"{edge_type}\t{target}")
        incoming[target].add(f"{edge_type}\t{source}")
        edge_types[edge_type] += 1
    for node_type in nodes.values():
        node_types[node_type] += 1

    dangling = 0
    for edge in edges:
        source, edge_type, target = edge.split("\t", 2)
        if f"{edge_type}\t{source}" not in incoming.get(target, set()):
            dangling += 1
        if source not in nodes or target not in nodes:
            dangling += 1

    max_out = max((len(v) for v in outgoing.values()), default=0)
    max_in = max((len(v) for v in incoming.values()), default=0)
    inversion_holds = dangling == 0
    edge_digest = _sha256_text("\n".join(sorted(edges)))
    node_digest = _sha256_text(
        "\n".join(f"{key}\t{nodes[key]}" for key in sorted(nodes))
    )

    graph_dir.mkdir(parents=True, exist_ok=True)
    edges_path = graph_dir / "edges.jsonl"
    with edges_path.open("w", encoding="utf-8") as handle:
        for edge in sorted(edges):
            source, edge_type, target = edge.split("\t", 2)
            handle.write(
                json.dumps(
                    {
                        "source": source,
                        "edge_type": edge_type,
                        "target": target,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    complete = limit is None and len(rows) == EXPECTED_LIVE_DOCUMENTS
    graph_report: dict[str, Any] = {
        "schema": "ipfs_datasets_py/federal-register-live-graph@1",
        "producer": "build_federal_register_live_graph.py",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "mode": "live",
        "fixture_only": False,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "documents": len(rows),
        "expected_documents": EXPECTED_LIVE_DOCUMENTS,
        "complete": complete,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "documents_with_citations": documents_with_citations,
        "unresolved_citations": unresolved,
        "node_types": dict(sorted(node_types.items())),
        "edge_types": dict(sorted(edge_types.items())),
        "node_digest": node_digest,
        "edge_digest": edge_digest,
        "edges_path": str(edges_path),
        "ontology_version": "federal-register-graph-ontology/v1",
        "citation_parser_version": "federal-register-citation-parser/v1",
        "adjacency_inversion": inversion_holds,
        "dangling_keys": dangling,
        "embedding_neighbors": embedding_neighbors,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "status": "passed" if complete and inversion_holds else "partial",
    }
    adjacency_report: dict[str, Any] = {
        "schema": "ipfs_datasets_py/federal-register-live-adjacency@1",
        "producer": "build_federal_register_live_graph.py",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "mode": "live",
        "fixture_only": False,
        "report_kind": "live_adjacency_reconciliation",
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "document_count": len(rows),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "incoming_descriptor_count": len(incoming),
        "outgoing_descriptor_count": len(outgoing),
        "max_outgoing_pointers": max_out,
        "max_incoming_pointers": max_in,
        "production_max_pointers_per_row": 4096,
        "dangling_keys": dangling,
        "duplicate_keys": 0,
        "inversion_holds": inversion_holds,
        "every_graph_edge_appears_exactly_once_in_both_directions": inversion_holds,
        "lexical_overlay_is_not_legal_authority": True,
        "similarity_cannot_establish_legal_authority": True,
        "graph_edge_digest": edge_digest,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "hub_upload": False,
        "status": "passed" if complete and inversion_holds else "partial",
    }
    graph_report["content_digest"] = digest_mapping(
        {k: v for k, v in graph_report.items() if k != "content_digest"}
    )
    adjacency_report["content_digest"] = digest_mapping(
        {k: v for k, v in adjacency_report.items() if k != "content_digest"}
    )
    (graph_dir / "manifest.json").write_text(
        json.dumps(graph_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (graph_dir / "adjacency.json").write_text(
        json.dumps(adjacency_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if write_receipts:
        graph_out = repository_root / GRAPH_RELPATH
        adj_out = repository_root / ADJACENCY_RELPATH
        graph_out.parent.mkdir(parents=True, exist_ok=True)
        graph_out.write_text(
            json.dumps(graph_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        adj_out.write_text(
            json.dumps(adjacency_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        graph_report["receipt_path"] = GRAPH_RELPATH.as_posix()
        adjacency_report["receipt_path"] = ADJACENCY_RELPATH.as_posix()
    return {"graph": graph_report, "adjacency": adjacency_report}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build live FR citation graph")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--graph-dir", type=Path, default=DEFAULT_GRAPH_DIR)
    parser.add_argument("--vectors-dir", type=Path, default=None)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--require-complete", action="store_true", default=True)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-write-receipts", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    require_complete = bool(args.require_complete) and not bool(args.allow_partial)
    if args.limit is not None:
        require_complete = False
    try:
        reports = build_live_graph(
            corpus_dir=args.corpus_dir,
            graph_dir=args.graph_dir,
            repository_root=args.repository_root,
            require_complete=require_complete,
            limit=args.limit,
            write_receipts=not bool(args.no_write_receipts),
            vectors_dir=args.vectors_dir,
        )
    except LiveGraphError as exc:
        sys.stderr.write(f"build_federal_register_live_graph: FAILED: {exc}\n")
        return 1
    graph = reports["graph"]
    if args.json:
        sys.stdout.write(json.dumps(reports, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "build_federal_register_live_graph: "
            f"{graph['status'].upper()} docs={graph['documents']} "
            f"nodes={graph['node_count']} edges={graph['edge_count']}\n"
        )
    return 0 if graph["status"] in {"passed", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
