"""Shared durable, pressure-capped graph projection for legal GraphRAG.

Open US Law, state-law, US Code, and Federal Register projectors use the
same in-process thread pool and JSONL work shards. Process pools are
refused. State-law corpora partition by jurisdiction so a query-by-state
graph never materializes interstate legal edges.
"""

from __future__ import annotations

import sys
from collections import ChainMap, defaultdict
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

from ipfs_datasets_py.processors.legal_data.lexical_neighbor_runtime import (
    PRESSURE_BATCH,
    PressureFn,
    map_documents_under_pressure,
    worker_limit,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_graph_work import (
    append_jsonl_part,
    iter_jsonl_parts,
    prepare_work_dir,
    write_manifest,
)

T = TypeVar("T")
NodeT = TypeVar("NodeT")
EdgeT = TypeVar("EdgeT")
RowWorker = Callable[[Any], tuple[Mapping[str, Any], Sequence[Any]]]


def row_jurisdiction_code(row: Any) -> str:
    """Return the jurisdiction code for a graph corpus row."""

    code = getattr(row, "jurisdiction_code", None)
    if not code:
        code = getattr(row, "jurisdiction", None)
    if not code and isinstance(row, Mapping):
        code = row.get("jurisdiction_code") or row.get("jurisdiction")
    return str(code or "").strip().upper()


def group_rows_by_jurisdiction(rows: Sequence[T]) -> dict[str, list[T]]:
    """Partition rows by jurisdiction. Empty codes sort last as ''."""

    groups: dict[str, list[T]] = defaultdict(list)
    for row in rows:
        groups[row_jurisdiction_code(row)].append(row)
    return {code: groups[code] for code in sorted(groups)}


def neighbors_for_legal_ids(
    neighbors: Sequence[Any] | None,
    legal_ids: set[str],
    *,
    source_attr: str = "source_legal_id",
    target_attr: str = "target_legal_id",
) -> list[Any]:
    """Keep similarity neighbors whose endpoints both live in *legal_ids*."""

    if not neighbors:
        return []
    kept: list[Any] = []
    for item in neighbors:
        if isinstance(item, Mapping):
            source = str(item.get(source_attr) or "")
            target = str(item.get(target_attr) or "")
        else:
            source = str(getattr(item, source_attr, "") or "")
            target = str(getattr(item, target_attr, "") or "")
        if source in legal_ids and target in legal_ids:
            kept.append(item)
    return kept


def same_jurisdiction_candidates(
    candidates: Mapping[str, Sequence[str]],
    *,
    source: Any,
    by_cid: Mapping[str, Any],
) -> dict[str, Sequence[str]]:
    """Drop BM25 neighbor candidates that are not the source's jurisdiction."""

    source_jurisdiction = row_jurisdiction_code(source)
    if not source_jurisdiction:
        filters = getattr(source, "filters", None) or {}
        source_jurisdiction = str(filters.get("jurisdiction") or "").strip().upper()
    if not source_jurisdiction:
        return dict(candidates)
    kept: dict[str, Sequence[str]] = {}
    for entry_cid, terms in candidates.items():
        document = by_cid.get(entry_cid)
        if document is None:
            continue
        other = row_jurisdiction_code(document)
        if not other:
            filters = getattr(document, "filters", None) or {}
            other = str(filters.get("jurisdiction") or "").strip().upper()
        if other == source_jurisdiction:
            kept[entry_cid] = terms
    return kept


def mutating_row_worker(
    fn: Callable[..., None],
    shared_nodes: MutableMapping[str, Any],
    **kwargs: Any,
) -> RowWorker:
    """Adapt a ``(nodes, edges, row)`` mutator into a local-map worker."""

    def worker(row: Any) -> tuple[dict[str, Any], list[Any]]:
        local_nodes: dict[str, Any] = {}
        local_edges: list[Any] = []
        view: ChainMap[str, Any] = ChainMap(local_nodes, shared_nodes)
        fn(view, local_edges, row, **kwargs)
        return local_nodes, local_edges

    return worker


def load_work_dir(
    work_root: Path,
    nodes: MutableMapping[str, Any],
    edges_by_cid: MutableMapping[str, Any],
    ingest_record: Callable[
        [Mapping[str, Any], MutableMapping[str, Any], MutableMapping[str, Any]],
        None,
    ],
) -> None:
    """Replay structure then citation JSONL parts into *nodes* / *edges_by_cid*."""

    for record in iter_jsonl_parts(work_root / "structure"):
        ingest_record(record, nodes, edges_by_cid)
    for record in iter_jsonl_parts(work_root / "citations"):
        ingest_record(record, nodes, edges_by_cid)


def ingest_graph_work_record(
    record: Mapping[str, Any],
    nodes: MutableMapping[str, Any],
    edges_by_cid: MutableMapping[str, Any],
    *,
    node_cls: Any,
    edge_cls: Any,
    source_span_cls: Any | None = None,
) -> None:
    """Rehydrate one JSONL work record using dataset node/edge classes."""

    kind = str(record.get("kind") or "")
    item = record.get("record")
    if not isinstance(item, Mapping):
        return
    if kind == "node":
        node_kwargs: dict[str, Any] = {
            "node_type": item.get("node_type"),
            "node_key": str(item.get("node_key") or ""),
            "label": str(item.get("label") or ""),
            "legal_id": item.get("legal_id"),
            "entry_cid": item.get("entry_cid"),
            "payload": dict(item.get("payload") or {}),
            "node_cid": str(item.get("node_cid") or ""),
        }
        if item.get("ontology_version"):
            node_kwargs["ontology_version"] = str(item.get("ontology_version"))
        if item.get("schema_version"):
            node_kwargs["schema_version"] = str(item.get("schema_version"))
        if "document_number" in item:
            node_kwargs["document_number"] = item.get("document_number")
        node = node_cls(**node_kwargs)
        if node.node_key not in nodes:
            nodes[node.node_key] = node
        return
    if kind == "edge":
        span_payload = item.get("source_span")
        source_span = None
        if (
            source_span_cls is not None
            and isinstance(span_payload, Mapping)
            and hasattr(source_span_cls, "from_mapping")
        ):
            source_span = source_span_cls.from_mapping(span_payload)
        edge_kwargs: dict[str, Any] = {
            "edge_type": item.get("edge_type"),
            "source_node_cid": str(item.get("source_node_cid") or ""),
            "target_node_cid": str(item.get("target_node_cid") or ""),
            "edge_class": item.get("edge_class"),
            "source_span": source_span,
            "resolution_status": item.get("resolution_status"),
            "weight": item.get("weight"),
            "payload": dict(item.get("payload") or {}),
            "edge_cid": str(item.get("edge_cid") or ""),
        }
        if item.get("ontology_version"):
            edge_kwargs["ontology_version"] = str(item.get("ontology_version"))
        if item.get("schema_version"):
            edge_kwargs["schema_version"] = str(item.get("schema_version"))
        try:
            edge = edge_cls(**edge_kwargs)
        except TypeError:
            edge_kwargs.pop("ontology_version", None)
            edge_kwargs.pop("schema_version", None)
            edge = edge_cls(**edge_kwargs)
        if edge.edge_cid not in edges_by_cid:
            edges_by_cid[edge.edge_cid] = edge


def run_projection_pass(
    admitted: Sequence[Any],
    *,
    start: int,
    worker: RowWorker,
    nodes: MutableMapping[str, Any],
    edges_by_cid: MutableMapping[str, Any],
    work_root: Path | None,
    manifest: dict[str, Any] | None,
    stage: str,
    max_workers: int | None,
    pressure: PressureFn | None,
    progress_label: str = "graph_progress",
    partition: str | None = None,
) -> None:
    """Run one structure or citation pass with optional JSONL spill."""

    total = len(admitted)
    offset = max(0, int(start))
    partition_note = f" partition={partition}" if partition else ""
    while offset < total:
        workers, reason = worker_limit(max_workers, pressure)
        batch_end = min(total, offset + PRESSURE_BATCH)
        batch = admitted[offset:batch_end]
        produced = map_documents_under_pressure(
            batch,
            worker,
            max_workers=workers,
            pressure=pressure,
            batch_size=len(batch) or 1,
        )
        delta_nodes: list[Any] = []
        delta_edges: list[Any] = []
        for local_nodes, local_edges in produced:
            for key, node in local_nodes.items():
                if key not in nodes:
                    nodes[key] = node
                    delta_nodes.append(node)
            for edge in local_edges:
                if edge.edge_cid not in edges_by_cid:
                    edges_by_cid[edge.edge_cid] = edge
                    delta_edges.append(edge)
        if work_root is not None and manifest is not None:
            part_key = "structure_parts" if stage == "structure" else "citation_parts"
            done_key = (
                "structure_rows_done" if stage == "structure" else "citation_rows_done"
            )
            part_index = int(manifest.get(part_key) or 0)
            records = [{"kind": "node", "record": node.to_dict()} for node in delta_nodes]
            records.extend(
                {"kind": "edge", "record": edge.to_dict()} for edge in delta_edges
            )
            append_jsonl_part(work_root / stage, part_index, records)
            manifest[part_key] = part_index + 1
            manifest[done_key] = batch_end
            manifest["node_count"] = len(nodes)
            manifest["edge_count"] = len(edges_by_cid)
            manifest["stage"] = stage
            if partition:
                manifest["jurisdiction_code"] = partition
            write_manifest(work_root, manifest)
        print(
            f"{progress_label} stage={stage}{partition_note} "
            f"documents={batch_end}/{total} workers={workers} reason={reason} "
            f"nodes={len(nodes)} edges={len(edges_by_cid)}",
            file=sys.stderr,
            flush=True,
        )
        offset = batch_end


def merge_graph_projections(
    parts: Sequence[Any],
    *,
    factory: Callable[..., Any],
    skipped_row_count: int = 0,
) -> Any:
    """Concatenate per-partition projections. First writer wins on key/CID."""

    nodes: dict[str, Any] = {}
    edges: dict[str, Any] = {}
    for part in parts:
        for node in getattr(part, "nodes", ()) or ():
            key = getattr(node, "node_key", "")
            if key and key not in nodes:
                nodes[key] = node
        for edge in getattr(part, "edges", ()) or ():
            cid = getattr(edge, "edge_cid", "")
            if cid and cid not in edges:
                edges[cid] = edge
    kwargs: dict[str, Any] = {
        "nodes": tuple(nodes.values()),
        "edges": tuple(edges.values()),
        "skipped_row_count": int(skipped_row_count),
    }
    try:
        return factory(**kwargs)
    except TypeError:
        kwargs.pop("skipped_row_count", None)
        return factory(**kwargs)


def prepare_partition_work_dir(
    checkpoint_dir: Path | None,
    *,
    corpus_digest: str,
    partition: str | None,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Create or resume a work dir, optionally namespaced by jurisdiction."""

    if checkpoint_dir is None:
        return None, None
    root = Path(checkpoint_dir)
    if partition:
        root = root / partition
    manifest = prepare_work_dir(root, corpus_digest)
    return root, manifest


__all__ = [
    "group_rows_by_jurisdiction",
    "ingest_graph_work_record",
    "load_work_dir",
    "merge_graph_projections",
    "mutating_row_worker",
    "neighbors_for_legal_ids",
    "prepare_partition_work_dir",
    "row_jurisdiction_code",
    "run_projection_pass",
    "same_jurisdiction_candidates",
]
