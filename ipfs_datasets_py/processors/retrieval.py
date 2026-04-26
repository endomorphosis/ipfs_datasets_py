"""Reusable retrieval primitives for lexical and dense search."""

from __future__ import annotations

from collections import Counter
import hashlib
import math
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize_lexical_text(text: str) -> List[str]:
    """Return lowercase lexical tokens for retrieval."""

    return [match.group(0).lower() for match in _TOKEN_RE.finditer(str(text or ""))]


def hashed_term_projection(text: str, *, dimension: int) -> List[float]:
    """Project text into a deterministic normalized vector space."""

    size = max(8, int(dimension or 32))
    values = [0.0] * size
    counts = Counter(tokenize_lexical_text(text))
    if not counts:
        return values

    for token, raw_frequency in counts.items():
        weight = 1.0 + math.log(float(raw_frequency))
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % size
        sign = 1.0 if (digest[4] % 2 == 0) else -1.0
        values[bucket] += sign * weight

    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        return values
    return [value / norm for value in values]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = str(raw).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_batch_size(batch_size: int | None) -> int:
    env_override = _env_int("IPFS_DATASETS_PY_EMBEDDINGS_BATCH_SIZE", 0)
    if env_override > 0:
        return max(1, env_override)
    if batch_size is None:
        return 128
    return max(1, int(batch_size))


def _resolve_parallel_batches(parallel_batches: int | None) -> int:
    if parallel_batches is not None:
        return max(1, int(parallel_batches))
    env_override = _env_int("IPFS_DATASETS_PY_EMBEDDINGS_BATCH_WORKERS", 1)
    return max(1, int(env_override))


def _resolve_embeddings_device(device: str | None) -> str | None:
    if device:
        return device
    auto_flag = str(os.getenv("IPFS_DATASETS_PY_AUTO_CUDA") or "").strip().lower()
    if auto_flag in {"1", "true", "yes", "on"}:
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            return device
    return device


def _ensure_requested_cuda_available(device: str | None) -> None:
    if not str(device or "").strip().lower().startswith("cuda"):
        return
    try:
        import torch
    except Exception as exc:
        raise RuntimeError("CUDA embeddings were requested, but torch is not importable") from exc
    if not torch.backends.cuda.is_built() or not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA embeddings were requested, but the active torch build cannot use CUDA "
            f"(torch={getattr(torch, '__version__', 'unknown')}, torch.version.cuda={torch.version.cuda!r})"
        )


def embed_texts_with_router_or_local(
    texts: Sequence[str],
    *,
    fallback_dimension: int,
    provider: str | None = None,
    model_name: str | None = None,
    device: str | None = None,
    batch_size: int = 128,
    parallel_batches: int | None = None,
) -> tuple[List[List[float]], Dict[str, Any]]:
    """Embed texts with `embeddings_router`, falling back to local projection."""

    items = [str(text or "") for text in list(texts)]
    if not items:
        return [], {
            "backend": "local_hashed_term_projection",
            "provider": "local",
            "model_name": "",
            "is_mock": False,
        }

    resolved_batch_size = _resolve_batch_size(batch_size)
    resolved_parallel_batches = _resolve_parallel_batches(parallel_batches)
    resolved_device = _resolve_embeddings_device(device)
    _ensure_requested_cuda_available(resolved_device)

    try:
        from ..embeddings_router import embed_texts_batched as router_embed_texts_batched

        vectors = router_embed_texts_batched(
            items,
            batch_size=resolved_batch_size,
            provider=provider,
            model_name=model_name,
            device=resolved_device,
            parallel_batches=resolved_parallel_batches,
        )
        normalized = [[float(value) for value in list(vector or [])] for vector in list(vectors or [])]
        if len(normalized) == len(items) and all(vector for vector in normalized):
            return normalized, {
                "backend": "embeddings_router",
                "provider": provider or "auto",
                "model_name": model_name or "",
                "device": resolved_device or "",
                "batch_size": int(resolved_batch_size),
                "parallel_batches": int(resolved_parallel_batches),
                "is_mock": False,
            }
    except Exception:
        if str(resolved_device or "").strip().lower().startswith("cuda"):
            raise
        pass

    return (
        [hashed_term_projection(text, dimension=fallback_dimension) for text in items],
        {
            "backend": "local_hashed_term_projection",
            "provider": "local",
            "model_name": "",
            "device": resolved_device or device or "",
            "is_mock": False,
        },
    )


def _simple_chunk_text(text: str, *, chunk_size: int, chunk_overlap: int) -> List[str]:
    if not text:
        return []
    size = max(1, int(chunk_size or 512))
    overlap = max(0, int(chunk_overlap or 0))
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
        if start >= end:
            start = end
    return chunks


def embed_texts_with_router_or_local_chunked(
    texts: Sequence[str],
    *,
    fallback_dimension: int,
    provider: str | None = None,
    model_name: str | None = None,
    device: str | None = None,
    batch_size: int = 128,
    parallel_batches: int | None = None,
    chunking_strategy: str | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> tuple[List[List[float]], Dict[str, Any]]:
    """Embed texts with embeddings_router + chunking; fallback to hashed vectors."""

    items = [str(text or "") for text in list(texts)]
    if not items:
        return [], {
            "backend": "local_hashed_term_projection",
            "provider": "local",
            "model_name": "",
            "is_mock": False,
        }

    resolved_batch_size = _resolve_batch_size(batch_size)
    resolved_parallel_batches = _resolve_parallel_batches(parallel_batches)
    resolved_device = _resolve_embeddings_device(device)

    strategy = str(chunking_strategy or "").strip().lower()
    if strategy in {"", "none", "off"}:
        return embed_texts_with_router_or_local(
            items,
            fallback_dimension=fallback_dimension,
            provider=provider,
            model_name=model_name,
            device=resolved_device,
            batch_size=resolved_batch_size,
            parallel_batches=resolved_parallel_batches,
        )

    chunks_by_doc: List[List[str]] = []
    try:
        from ..ml.embeddings.chunker import Chunker

        chunker = Chunker(
            metadata={
                "chunking_strategy": strategy,
                "chunk_size": int(chunk_size or 512),
                "chunk_overlap": int(chunk_overlap or 0),
                "models": [model_name] if model_name else [],
                "device": resolved_device or "cpu",
            }
        )
        for text in items:
            try:
                chunks = [chunk.content for chunk in chunker.chunk_text(text) if str(chunk.content or "").strip()]
            except Exception:
                chunks = []
            if not chunks:
                chunks = _simple_chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            chunks_by_doc.append(chunks or [text])
    except Exception:
        for text in items:
            chunks = _simple_chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            chunks_by_doc.append(chunks or [text])

    flat_chunks = [chunk for chunks in chunks_by_doc for chunk in chunks]
    router_error: str | None = None
    try:
        from ..embeddings_router import embed_texts_batched as router_embed_texts_batched
        import concurrent.futures

        timeout_raw = str(os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_TIMEOUT_SECONDS", "0")).strip()
        try:
            timeout_seconds = max(0.0, float(timeout_raw))
        except Exception:
            timeout_seconds = 0.0
        if timeout_seconds:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    router_embed_texts_batched,
                    flat_chunks,
                    batch_size=resolved_batch_size,
                    provider=provider,
                    model_name=model_name,
                    device=resolved_device,
                    parallel_batches=resolved_parallel_batches,
                )
                try:
                    vectors = future.result(timeout=timeout_seconds)
                except concurrent.futures.TimeoutError:
                    raise TimeoutError(f"embeddings_router timed out after {timeout_seconds:.1f}s")
        else:
            vectors = router_embed_texts_batched(
                flat_chunks,
                batch_size=resolved_batch_size,
                provider=provider,
                model_name=model_name,
                device=resolved_device,
                parallel_batches=resolved_parallel_batches,
            )
        normalized = [[float(value) for value in list(vector or [])] for vector in list(vectors or [])]
        if len(normalized) == len(flat_chunks) and all(vector for vector in normalized):
            per_doc_vectors: List[List[float]] = []
            offset = 0
            for chunks in chunks_by_doc:
                if not chunks:
                    per_doc_vectors.append(hashed_term_projection("", dimension=fallback_dimension))
                    continue
                chunk_vecs = normalized[offset : offset + len(chunks)]
                offset += len(chunks)
                dimension = len(chunk_vecs[0]) if chunk_vecs else fallback_dimension
                averaged = [0.0] * dimension
                for vec in chunk_vecs:
                    for i, value in enumerate(vec):
                        averaged[i] += float(value)
                count = max(1, len(chunk_vecs))
                per_doc_vectors.append([value / count for value in averaged])
            return per_doc_vectors, {
                "backend": "embeddings_router",
                "provider": provider or "auto",
                "model_name": model_name or "",
                "device": resolved_device or "",
                "chunking_strategy": strategy,
                "chunk_size": int(chunk_size or 0),
                "chunk_overlap": int(chunk_overlap or 0),
                "chunk_counts": [len(chunks) for chunks in chunks_by_doc],
                "batch_size": int(resolved_batch_size),
                "parallel_batches": int(resolved_parallel_batches),
                "is_mock": False,
            }
    except Exception as exc:
        router_error = str(exc)

    per_doc_vectors = []
    for chunks in chunks_by_doc:
        chunk_vectors = [hashed_term_projection(chunk, dimension=fallback_dimension) for chunk in chunks]
        if not chunk_vectors:
            per_doc_vectors.append(hashed_term_projection("", dimension=fallback_dimension))
            continue
        averaged = [0.0] * len(chunk_vectors[0])
        for vec in chunk_vectors:
            for i, value in enumerate(vec):
                averaged[i] += float(value)
        count = max(1, len(chunk_vectors))
        per_doc_vectors.append([value / count for value in averaged])
    return per_doc_vectors, {
        "backend": "local_hashed_term_projection",
        "provider": "local",
        "model_name": "",
        "device": resolved_device or device or "",
        "chunking_strategy": strategy,
        "chunk_size": int(chunk_size or 0),
        "chunk_overlap": int(chunk_overlap or 0),
        "chunk_counts": [len(chunks) for chunks in chunks_by_doc],
        "fallback_reason": router_error,
        "is_mock": False,
    }


def embed_query_for_backend(
    text: str,
    *,
    backend: str,
    dimension: int,
    provider: str | None = None,
    model_name: str | None = None,
    device: str | None = None,
) -> List[float]:
    """Embed a query using the declared backend, falling back safely."""

    if str(backend or "").strip() == "embeddings_router":
        vectors, metadata = embed_texts_with_router_or_local(
            [text],
            fallback_dimension=dimension,
            provider=provider,
            model_name=model_name,
            device=device,
        )
        if vectors and metadata.get("backend") == "embeddings_router":
            return vectors[0]
    return hashed_term_projection(text, dimension=dimension)


def vector_dot(left: Iterable[float], right: Iterable[float]) -> float:
    """Return dot product between two vectors."""

    return sum(float(a) * float(b) for a, b in zip(left, right))


def bm25_search_documents(
    query: str,
    documents: Sequence[Mapping[str, Any]],
    *,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """Rank *documents* using a local BM25 lexical scorer."""

    query_terms = tokenize_lexical_text(query)
    if not query_terms:
        return []

    prepared_rows: List[Dict[str, Any]] = []
    document_frequency: Counter[str] = Counter()
    total_length = 0

    for index, document in enumerate(documents, start=1):
        metadata = dict(document.get("metadata") or {})
        title = str(document.get("title") or metadata.get("title") or "")
        text = str(document.get("text") or "")
        term_counts = _document_term_counts(document, title=title, text=text)
        if not term_counts:
            continue
        document_length = _document_length(document, term_counts)
        total_length += document_length
        prepared_rows.append(
            {
                "id": document.get("id") or document.get("document_id") or f"doc_{index}",
                "document_id": document.get("document_id") or document.get("id") or f"doc_{index}",
                "title": title,
                "text": text,
                "metadata": metadata,
                "document_length": document_length,
                "term_counts": term_counts,
            }
        )
        document_frequency.update(term_counts.keys())

    total_documents = len(prepared_rows)
    if total_documents <= 0:
        return []
    average_length = total_length / max(1, total_documents)

    scored: List[Dict[str, Any]] = []
    for row in prepared_rows:
        score = _bm25_score(
            query_terms,
            row["term_counts"],
            int(row["document_length"]),
            document_frequency=document_frequency,
            total_documents=total_documents,
            average_length=average_length,
        )
        if score <= 0:
            continue
        matched_terms = sorted({term for term in query_terms if term in row["term_counts"]})
        scored.append(
            {
                "id": row["id"],
                "document_id": row["document_id"],
                "title": row["title"],
                "text": row["text"],
                "metadata": row["metadata"],
                "score": score,
                "matched_terms": matched_terms,
                "backend": "local_bm25",
            }
        )

    scored.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return scored[:top_k]


def build_bm25_index(documents: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build a reusable local BM25 index payload for *documents*."""

    normalized_documents: List[Dict[str, Any]] = []
    total_token_count = 0
    document_frequency: Counter[str] = Counter()
    k1 = 1.5
    b = 0.75

    for index, document in enumerate(documents, start=1):
        metadata = dict(document.get("metadata") or {})
        title = str(document.get("title") or metadata.get("title") or "")
        text = str(document.get("text") or "")
        title_tokens = tokenize_lexical_text(title)
        body_tokens = tokenize_lexical_text(text)
        combined_tokens = list(title_tokens) + list(title_tokens) + list(body_tokens)
        if not combined_tokens:
            continue
        term_counts = Counter(combined_tokens)
        document_length = len(combined_tokens)
        total_token_count += document_length
        document_frequency.update(term_counts.keys())
        normalized_documents.append(
            {
                "id": document.get("id") or document.get("document_id") or f"doc_{index}",
                "document_id": document.get("document_id") or document.get("id") or f"doc_{index}",
                "title": title,
                "text": text,
                "metadata": metadata,
                "document_length": document_length,
                "unique_term_count": len(term_counts),
                "terms": sorted(term_counts.keys()),
                "term_frequencies": [
                    {"term": term, "tf": int(frequency)}
                    for term, frequency in sorted(term_counts.items())
                ],
            }
        )

    document_count = len(normalized_documents)
    average_document_tokens = total_token_count / max(1, document_count)
    for row in normalized_documents:
        row["bm25_k1"] = k1
        row["bm25_b"] = b
        row["bm25_avgdl"] = average_document_tokens
        row["bm25_document_count"] = document_count
    return {
        "backend": "local_bm25",
        "document_count": document_count,
        "documents": normalized_documents,
        "stats": {
            "average_document_tokens": average_document_tokens,
            "unique_term_count": len(document_frequency),
            "k1": k1,
            "b": b,
        },
    }


def search_bm25_index(
    query: str,
    bm25_index: Mapping[str, Any],
    *,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """Search a local BM25 index payload produced by :func:`build_bm25_index`."""

    return bm25_search_documents(query, list(bm25_index.get("documents") or []), top_k=top_k)


def _document_term_counts(document: Mapping[str, Any], *, title: str, text: str) -> Counter[str]:
    """Return precomputed document term counts, falling back to tokenization."""

    raw_term_frequencies = document.get("term_frequencies")
    counts: Counter[str] = Counter()
    if isinstance(raw_term_frequencies, Mapping):
        for term, frequency in raw_term_frequencies.items():
            normalized = str(term or "").strip().lower()
            if not normalized:
                continue
            try:
                value = int(frequency)
            except Exception:
                value = 0
            if value > 0:
                counts[normalized] = value
        if counts:
            return counts

    if isinstance(raw_term_frequencies, Sequence) and not isinstance(raw_term_frequencies, (str, bytes, bytearray)):
        for item in raw_term_frequencies:
            if not isinstance(item, Mapping):
                continue
            normalized = str(item.get("term") or "").strip().lower()
            if not normalized:
                continue
            try:
                value = int(item.get("tf") or item.get("frequency") or 0)
            except Exception:
                value = 0
            if value > 0:
                counts[normalized] += value
        if counts:
            return counts

    title_tokens = tokenize_lexical_text(title)
    body_tokens = tokenize_lexical_text(text)
    return Counter(list(title_tokens) + list(title_tokens) + list(body_tokens))


def _document_length(document: Mapping[str, Any], term_counts: Mapping[str, int]) -> int:
    """Return precomputed BM25 document length, falling back to summed TF."""

    try:
        document_length = int(document.get("document_length") or document.get("doc_length") or 0)
    except Exception:
        document_length = 0
    if document_length > 0:
        return document_length
    return int(sum(int(value) for value in term_counts.values()))


def _bm25_score(
    query_terms: Sequence[str],
    term_counts: Mapping[str, int],
    document_length: int,
    *,
    document_frequency: Mapping[str, int],
    total_documents: int,
    average_length: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    score = 0.0
    for term in query_terms:
        frequency = int(term_counts.get(term) or 0)
        if frequency <= 0:
            continue
        df = max(1, int(document_frequency.get(term) or 0))
        idf = math.log(1.0 + ((total_documents - df + 0.5) / (df + 0.5)))
        normalization = frequency + k1 * (1.0 - b + b * (document_length / max(1.0, average_length)))
        score += idf * ((frequency * (k1 + 1.0)) / max(1e-9, normalization))
    return score
