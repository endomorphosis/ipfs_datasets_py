"""Shared pressure-aware neighbor materialization for legal GraphRAG.

Process pools are refused: they would duplicate a multi-tens-of-GiB BM25
index. Threads may share a frozen index. Default worker count comes from
:func:`host_worker_pressure` (unused cores, RAM / 2GiB, half the machine)
and is recapped every 4096 documents. Combined RAM+CPU+swap heat
collapses to 1; swap alone does not.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from ipfs_datasets_py.processors.legal_data.host_worker_budget import (
    host_worker_pressure,
)

PRESSURE_BATCH = 4096

T = TypeVar("T")
R = TypeVar("R")
PressureFn = Callable[[], tuple[int, str]]
ProgressFn = Callable[[int, int, int, str, Sequence[R]], None]


def documents_by_cid(documents: Sequence[T]) -> dict[str, T]:
    """Build the CID→document map once. Scoring must not rebuild this per source."""

    mapping: dict[str, T] = {}
    for document in documents:
        entry_cid = getattr(document, "entry_cid", None)
        if entry_cid:
            mapping[str(entry_cid)] = document
        chunk_cid = getattr(document, "chunk_cid", None)
        if chunk_cid and str(chunk_cid) not in mapping:
            mapping[str(chunk_cid)] = document
    return mapping


def invert_document_terms(documents: Sequence[T]) -> dict[str, tuple[T, ...]]:
    """Build a term→documents map so neighbor scoring can skip non-overlapping docs."""

    inverted: dict[str, list[T]] = {}
    for document in documents:
        seen: set[str] = set()
        fields = getattr(document, "fields", None) or {}
        for stream in fields.values():
            for term in getattr(stream, "terms", ()):
                if not term or term in seen:
                    continue
                seen.add(term)
                inverted.setdefault(term, []).append(document)
    return {term: tuple(docs) for term, docs in inverted.items()}


def candidate_documents_for_terms(
    inverted: Mapping[str, Sequence[T]],
    query_terms: Sequence[str],
    *,
    exclude_entry_cid: str,
) -> list[T]:
    """Return unique documents that share at least one query term."""

    found: dict[str, T] = {}
    exclude = str(exclude_entry_cid)
    for term in query_terms:
        for document in inverted.get(term, ()):
            cid = str(getattr(document, "entry_cid", ""))
            if not cid or cid == exclude or cid in found:
                continue
            found[cid] = document
    return list(found.values())


def worker_limit(
    requested: int | None,
    pressure: PressureFn | None = None,
) -> tuple[int, str]:
    """Cap thread workers against live host pressure. Always at least 1.

    ``requested=None`` uses the heuristic admission unchanged.
    """

    pressure_fn = pressure or host_worker_pressure
    admitted, reason = pressure_fn()
    if requested is None:
        return max(1, admitted), reason
    return max(1, min(int(requested), admitted)), reason


def log_neighbor_progress(
    *,
    processed: int,
    total: int,
    workers: int,
    reason: str,
    edges: int,
    label: str = "neighbor_progress",
) -> None:
    print(
        f"{label} documents={processed}/{total} "
        f"workers={workers} reason={reason} edges={edges}",
        file=sys.stderr,
        flush=True,
    )


def map_documents_under_pressure(
    documents: Sequence[T],
    fn: Callable[[T], R],
    *,
    max_workers: int | None = None,
    pressure: PressureFn | None = None,
    progress: ProgressFn | None = None,
    batch_size: int = PRESSURE_BATCH,
) -> list[R]:
    """Map *fn* over *documents* with a pressure-capped in-process thread pool.

    Results stay in document order. ``fn`` must only read shared frozen
    state. Worker count is resampled at each batch so swap/RAM/CPU
    heat collapses the pool to 1.
    """

    total = len(documents)
    if total == 0:
        return []
    size = max(1, int(batch_size))
    pressure_fn = pressure or host_worker_pressure
    out: list[R] = []
    offset = 0
    while offset < total:
        workers, reason = worker_limit(max_workers, pressure_fn)
        if progress is not None and offset == 0:
            progress(0, total, workers, reason, out)
        batch_end = min(total, offset + size)
        batch = documents[offset:batch_end]
        if workers <= 1:
            rows = [fn(document) for document in batch]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                rows = list(pool.map(fn, batch, chunksize=min(32, len(batch))))
        out.extend(rows)
        offset = batch_end
        if progress is not None:
            progress(offset, total, workers, reason, out)
    return out
