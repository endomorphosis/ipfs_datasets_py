"""Serial-safe document projection helpers for US Code GraphRAG builds.

Process pools are disabled here because admitted corpus rows may contain
``mappingproxy`` objects that cannot be pickled across process boundaries
under Python 3.13 on this host. Projection is therefore always serial.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, TypeVar

T = TypeVar("T")

MIN_PARALLEL_ITEMS = 10_000_000  # effectively force serial on this host


def chunk_items(items: Sequence[T], *, size: int) -> list[list[T]]:
    if size < 1:
        raise ValueError("size must be >= 1")
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def ordered_process_map(
    func: Callable[[Any], Any],
    chunks: Sequence[Any],
    *,
    workers: int = 1,
    plan: Any = None,
) -> list[Any]:
    """Always serial: apply ``func`` to each chunk in order."""
    return [func(chunk) for chunk in chunks]


def project_documents_parallel(
    documents: Sequence[Mapping[str, Any]],
    *,
    project_fn: Callable[[Mapping[str, Any]], Any],
    config: Any = None,
) -> list[Any]:
    """Project documents serially (pickle-safe)."""
    return [project_fn(doc) for doc in documents]


def tokenize_indexable_batch(batch: Sequence[Any], *, tokenize_fn: Callable[[Any], Any]) -> list[Any]:
    return [tokenize_fn(item) for item in batch]


def iter_as_list(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return list(rows)
