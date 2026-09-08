"""Resource-aware process-pool tokenization for GraphRAG BM25 builds.

Thread pools cannot beat the GIL on ``tokenize_legal_text``. Process pools
are safe here because workers tokenize source text *before* an inverted
index exists. Do not use this helper to mutate a live in-memory index.

Query tokenization stays serial: one query is not worth a spawn.
"""

from __future__ import annotations

import multiprocessing as mp
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from importlib import import_module
from typing import Any, TypeVar

from ipfs_datasets_py.processors.legal_data.host_worker_budget import (
    TOKENIZE_BYTES_PER_WORKER,
    TokenizePoolPlan,
    tokenize_process_pool_size,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import (
    tokenize_legal_text,
)

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_CHUNK_SIZE = 64
MIN_PARALLEL_ITEMS = 32

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "MIN_PARALLEL_ITEMS",
    "chunk_items",
    "iter_as_list",
    "ordered_process_map",
    "project_documents_parallel",
    "tokenize_indexable_batch",
]


def chunk_items(items: Sequence[T], size: int) -> list[Sequence[T]]:
    """Split *items* into contiguous chunks of at most *size*."""

    width = max(1, int(size))
    return [items[i : i + width] for i in range(0, len(items), width)]


def ordered_process_map(
    func: Callable[[T], R],
    chunks: Sequence[T],
    *,
    workers: int | None = None,
    per_task_budget: int = TOKENIZE_BYTES_PER_WORKER,
    plan: TokenizePoolPlan | None = None,
) -> list[R]:
    """Map *func* over *chunks* with spawn workers, preserving order.

    Falls back to in-process ``map`` when the host admits only one worker
    or there is a single chunk. *func* must be a top-level picklable
    callable.
    """

    if not chunks:
        return []
    if plan is None:
        plan = tokenize_process_pool_size(
            per_task_budget=per_task_budget,
            requested=workers,
        )
    count = max(1, int(plan.workers if workers is None else workers))
    if count <= 1 or len(chunks) <= 1:
        return [func(chunk) for chunk in chunks]
    ctx = mp.get_context(plan.start_method)
    with ProcessPoolExecutor(max_workers=count, mp_context=ctx) as pool:
        return list(pool.map(func, chunks))


def _tokenize_text_chunk(payload: tuple[Sequence[str], bool]) -> list[tuple[str, ...]]:
    texts, drop_stopwords = payload
    return [
        tokenize_legal_text(str(text or ""), drop_stopwords=drop_stopwords).indexable_terms
        for text in texts
    ]


def tokenize_indexable_batch(
    texts: Sequence[str],
    *,
    drop_stopwords: bool = True,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    workers: int | None = None,
) -> list[tuple[str, ...]]:
    """Tokenize many documents with the sealed legal tokenizer."""

    if not texts:
        return []
    plan = tokenize_process_pool_size(requested=workers)
    if plan.workers <= 1 or len(texts) < MIN_PARALLEL_ITEMS:
        return _tokenize_text_chunk((texts, drop_stopwords))
    payloads = [
        (chunk, drop_stopwords) for chunk in chunk_items(texts, chunk_size)
    ]
    parts = ordered_process_map(
        _tokenize_text_chunk, payloads, workers=plan.workers, plan=plan
    )
    out: list[tuple[str, ...]] = []
    for part in parts:
        out.extend(part)
    return out


def _apply_named_project(
    payload: tuple[str, list[tuple[int, Mapping[str, Any]]], Any],
) -> list[Any]:
    dotted, pairs, config = payload
    module_name, _, attr = dotted.rpartition(".")
    fn = getattr(import_module(module_name), attr)
    return [fn(row, document_index=index, config=config) for index, row in pairs]


def project_documents_parallel(
    rows: Sequence[Mapping[str, Any]],
    *,
    project_fn: Callable[..., Any],
    config: Any,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    min_items: int = MIN_PARALLEL_ITEMS,
    workers: int | None = None,
) -> list[Any]:
    """Project admitted BM25 rows, process-pooling tokenize when it pays off.

    *project_fn* must be a top-level ``project_legal_document(row, *,
    document_index, config)``. Document indexes follow input order so
    later sort/receipt identity stays stable.
    """

    if not rows:
        return []
    plan = tokenize_process_pool_size(requested=workers)
    if plan.workers <= 1 or len(rows) < min_items:
        return [
            project_fn(row, document_index=index, config=config)
            for index, row in enumerate(rows)
        ]
    dotted = f"{project_fn.__module__}.{project_fn.__name__}"
    payloads: list[tuple[str, list[tuple[int, Mapping[str, Any]]], Any]] = []
    for start in range(0, len(rows), max(1, int(chunk_size))):
        pairs = [
            (start + offset, rows[start + offset])
            for offset in range(min(chunk_size, len(rows) - start))
        ]
        payloads.append((dotted, pairs, config))
    documents: list[Any] = []
    for part in ordered_process_map(
        _apply_named_project, payloads, workers=plan.workers, plan=plan
    ):
        documents.extend(part)
    return documents


def iter_as_list(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Materialize a row iterable (including generators) without copying strings twice."""

    if isinstance(rows, list):
        return rows
    if isinstance(rows, tuple):
        return list(rows)
    return list(rows)
