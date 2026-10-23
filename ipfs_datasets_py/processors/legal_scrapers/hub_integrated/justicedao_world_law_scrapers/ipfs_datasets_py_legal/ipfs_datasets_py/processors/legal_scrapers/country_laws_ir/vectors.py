"""thenlper/gte-small 384-d embeddings + centroid-sorted shards.

If sentence-transformers/torch cannot embed, layout_stub_vectors() documents the
expected schema so corpus/BM25/graph releases remain complete.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import MAX_ROWS_PER_FILE, SCHEMA_VERSION

MODEL_NAME = "thenlper/gte-small"
MODEL_REVISION = "17e1f347d17fe144873b1201da91788898c639cd"
DIMENSION = 384
MAX_SEQ_LENGTH = 512
DEFAULT_DEVICE = "cuda"
SUPPORTED_DEVICES = frozenset({"cpu", "cuda", "cuda:0", "mps", "auto"})
MAX_ROWS_PER_CENTROID = 8192
MAX_SHARDS_PER_CENTROID = 2


def _l2_normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(n, eps)


def device_is_available(device: str) -> bool:
    """Probe accelerator availability without loading a model."""
    name = str(device or "").strip().lower()
    if not name or name == "cpu":
        return True
    try:
        import torch
    except Exception:
        return False
    if name.startswith("cuda"):
        return bool(
            getattr(torch, "cuda", None)
            and torch.backends.cuda.is_built()
            and torch.cuda.is_available()
        )
    if name == "mps":
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        return bool(mps is not None and mps.is_available())
    return False


def select_device(requested: str = DEFAULT_DEVICE) -> tuple[str, bool]:
    """Prefer CUDA like US Code / Open US Law; fall back to CPU."""
    req = str(requested or DEFAULT_DEVICE).strip().lower() or DEFAULT_DEVICE
    if req == "auto":
        req = "cuda"
    if req not in SUPPORTED_DEVICES and not req.startswith("cuda:"):
        raise ValueError(f"unsupported embedding device: {requested!r}")
    if device_is_available(req):
        return req, False
    return "cpu", True


def ensure_embedding_stack() -> bool:
    """Lazy-import / lazy-install transformers + sentence-transformers.

    Matches ``ipfs_datasets_py.auto_installer.ensure_module`` used by other
    GraphRAG producers. Importing this module must not pip-install; first
    encode may.
    """
    import os

    os.environ.setdefault("TRANSFORMERS_NO_TORCHVISION", "1")
    try:
        import sentence_transformers  # noqa: F401
        import transformers  # noqa: F401

        return True
    except Exception:
        pass
    try:
        from ipfs_datasets_py.auto_installer import ensure_module, install_for_component

        install_for_component("graphrag")
        ensure_module("torchvision", "torchvision")
        ensure_module("transformers", "transformers")
        module = ensure_module("sentence_transformers", "sentence-transformers")
        return module is not None
    except Exception:
        return False


def embeddings_available() -> bool:
    return ensure_embedding_stack()


def _is_real_vector(vec: object) -> bool:
    try:
        arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    except Exception:
        return False
    if arr.shape[0] != DIMENSION:
        return False
    if not np.isfinite(arr).all():
        return False
    return float(np.linalg.norm(arr)) > 1e-6


def encode_corpus(
    corpus: pd.DataFrame,
    batch_size: int = 64,
    device: str = DEFAULT_DEVICE,
    checkpoint_path: str | None = None,
    chunk_size: int = 4096,
) -> np.ndarray:
    """Encode corpus texts with pinned gte-small on CUDA when available."""
    import json
    import os
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    if not ensure_embedding_stack():
        raise RuntimeError(
            "sentence-transformers is required for production GTE embeddings; "
            "lazy install failed (python -m ipfs_datasets_py.auto_installer)"
        )
    from sentence_transformers import SentenceTransformer

    from .auth import configure_hf

    configure_hf()
    device, _fallback = select_device(device)
    texts = []
    for rec in corpus.itertuples(index=False):
        title = getattr(rec, "title", None) or getattr(rec, "instrument_title", "") or ""
        body = getattr(rec, "body", "") or ""
        sid = getattr(rec, "source_id", "") or getattr(rec, "instrument_id", "")
        texts.append(f"{title}\n{body[:4000]}".strip() or title or sid)
    n = len(texts)
    out = np.zeros((n, DIMENSION), dtype=np.float32)
    done = 0
    ckpt = _Path(checkpoint_path) if checkpoint_path else None
    meta_path = ckpt.with_suffix(".json") if ckpt else None
    cache_root = _Path(
        os.environ.get(
            "COUNTRY_LAWS_IR_ROOT",
            str(_Path.home() / ".ipfs_datasets" / "country-laws-ir"),
        )
    ) / "cache" / "hf"
    os.environ.setdefault("HF_HOME", str(cache_root))
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(cache_root / "sentence-transformers"))
    if meta_path is not None and meta_path.exists():
        try:
            meta_n = json.loads(meta_path.read_text(encoding="utf-8")).get("n")
        except Exception:
            meta_n = None
    else:
        meta_n = None
    if ckpt is not None and ckpt.exists():
        cached = np.load(ckpt)
        same_corpus = meta_n is None or int(meta_n) == n
        if (
            same_corpus
            and cached.ndim == 2
            and cached.shape[1] == DIMENSION
            and 0 < cached.shape[0] <= n
        ):
            done = int(cached.shape[0])
            out[:done] = cached.astype(np.float32, copy=False)
        if done >= n:
            return out

    lock_fh = None
    if device.startswith("cuda"):
        import fcntl

        lock_path = _Path(
            os.environ.get(
                "COUNTRY_LAWS_IR_ROOT",
                str(_Path.home() / ".ipfs_datasets" / "country-laws-ir"),
            )
        ) / "cuda.encode.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fh = open(lock_path, "a", encoding="utf-8")
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
    try:
        model = SentenceTransformer(
            MODEL_NAME,
            revision=MODEL_REVISION,
            device=device,
        )
        try:
            model.max_seq_length = MAX_SEQ_LENGTH
        except Exception:
            pass
        while done < n:
            j = min(done + int(chunk_size), n)
            chunk = model.encode(
                texts[done:j],
                batch_size=batch_size,
                show_progress_bar=True,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            out[done:j] = np.asarray(chunk, dtype=np.float32)
            done = j
            if ckpt is not None:
                ckpt.parent.mkdir(parents=True, exist_ok=True)
                tmp = ckpt.with_name(ckpt.name + ".tmp.npy")
                np.save(tmp, out[:done])
                tmp.replace(ckpt)
                if meta_path is not None:
                    meta_path.write_text(
                        json.dumps(
                            {
                                "n": n,
                                "done": done,
                                "dimension": DIMENSION,
                                "model_name": MODEL_NAME,
                                "ts": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        + "\n",
                        encoding="utf-8",
                    )
        return out
    finally:
        if lock_fh is not None:
            import fcntl as _fcntl

            _fcntl.flock(lock_fh.fileno(), _fcntl.LOCK_UN)
            lock_fh.close()
        try:
            import torch as _torch

            if _torch.cuda.is_available():
                _torch.cuda.empty_cache()
        except Exception:
            pass


def _spherical_kmeans(x: np.ndarray, k: int, iters: int = 12, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(x)
    k = min(k, n)
    centers = x[rng.choice(n, size=k, replace=False)].copy()
    labels = np.zeros(n, dtype=np.int32)
    for _ in range(iters):
        sim = x @ centers.T
        labels = sim.argmax(axis=1).astype(np.int32)
        new = []
        for j in range(k):
            mask = labels == j
            if not mask.any():
                new.append(x[rng.integers(0, n)])
            else:
                new.append(_l2_normalize(x[mask].mean(axis=0)))
        centers = np.stack(new).astype(np.float32)
    return labels


def _recursive_clusters(x: np.ndarray, max_size: int = MAX_ROWS_PER_FILE) -> list[np.ndarray]:
    """Split vectors into shards of at most *max_size* without unbounded recursion.

    Spherical k-means can fail to split (all points one label). In that case
    fall back to an even index split so layout cannot recurse forever.
    """
    n = len(x)
    if n == 0:
        return []
    pending: list[np.ndarray] = [np.arange(n)]
    clusters: list[np.ndarray] = []
    while pending:
        idx = pending.pop()
        if len(idx) <= max_size:
            clusters.append(idx)
            continue
        labels = _spherical_kmeans(x[idx], k=2)
        parts = [idx[labels == lab] for lab in (0, 1)]
        parts = [p for p in parts if len(p)]
        if len(parts) < 2 or max(len(p) for p in parts) == len(idx):
            mid = len(idx) // 2
            parts = [idx[:mid], idx[mid:]]
        pending.extend(parts)
    return clusters or [np.arange(n)]


def layout_vectors(corpus: pd.DataFrame, embeddings: np.ndarray) -> dict[str, Any]:
    x = _l2_normalize(np.asarray(embeddings, dtype=np.float32))
    clusters = _recursive_clusters(x, max_size=MAX_ROWS_PER_FILE)
    vector_rows = []
    chunk_meta = []
    global_centroid = _l2_normalize(x.mean(axis=0))
    for cluster_id, members in enumerate(clusters):
        shard_centroid = _l2_normalize(x[members].mean(axis=0))
        sims = x[members] @ shard_centroid
        order = np.argsort(-sims)
        members = members[order]
        sims = sims[order]
        chunk_id = f"vec-{cluster_id:06d}"
        for local_i, doc_i in enumerate(members):
            row = corpus.iloc[int(doc_i)]
            vector_rows.append(
                {
                    "chunk_id": chunk_id,
                    "cluster_id": int(cluster_id),
                    "entry_cid": row["entry_cid"],
                    "faiss_id": int(doc_i),
                    "document_index": int(row["document_index"]),
                    "corpus_chunk_id": int(row["document_index"] // MAX_ROWS_PER_FILE),
                    "corpus_row_offset": int(row["document_index"] % MAX_ROWS_PER_FILE),
                    "law_cid": row.get("law_cid", ""),
                    "instrument_id": row.get("instrument_id", row.get("law_id", "")),
                    "law_id": row.get("law_id", row.get("instrument_id", "")),
                    "title": row.get("title", row.get("instrument_title", "")),
                    "record_type": row["record_type"],
                    "language": row.get("language", ""),
                    "jurisdiction": row.get("jurisdiction", ""),
                    "embedding": x[int(doc_i)].tolist(),
                    "schema_version": SCHEMA_VERSION,
                }
            )
        chunk_meta.append(
            {
                "cluster_id": int(cluster_id),
                "chunk_id": chunk_id,
                "centroid": shard_centroid.tolist(),
                "shard_centroid": shard_centroid.tolist(),
                "centroid_min_score": float(sims.min()) if len(sims) else 0.0,
                "centroid_shard_count": 1,
                "chunk_in_cluster": 0,
                "dimension": DIMENSION,
                "model_name": MODEL_NAME,
                "row_count": int(len(members)),
                "first_key": corpus.iloc[int(members[0])]["entry_cid"] if len(members) else "",
                "last_key": corpus.iloc[int(members[-1])]["entry_cid"] if len(members) else "",
            }
        )
    vectors_df = pd.DataFrame(vector_rows)
    return {
        "vectors": vectors_df,
        "chunk_meta": chunk_meta,
        "global_centroid": global_centroid.tolist(),
        "stats": {
            "model_name": MODEL_NAME,
            "dimension": DIMENSION,
            "similarity": "cosine",
            "assignment": "recursive_spherical_kmeans",
            "layout": "semantic_centroid_groups",
            "rows_sorted_by": "cosine_similarity_to_shard_centroid_desc",
            "max_rows_per_chunk": MAX_ROWS_PER_FILE,
            "max_rows_per_centroid": MAX_ROWS_PER_CENTROID,
            "max_shards_per_centroid": MAX_SHARDS_PER_CENTROID,
            "default_probe_centroids": min(4, max(1, len(clusters))),
            "centroid_count": len(clusters),
            "shard_count": len(clusters),
            "n_vectors": int(len(vectors_df)),
            "status": "embedded",
        },
    }


def layout_stub_vectors(corpus: pd.DataFrame, reason: str) -> dict[str, Any]:
    """Document expected vector schema when embeddings cannot be produced."""
    rows = []
    for _, row in corpus.iterrows():
        rows.append(
            {
                "chunk_id": "vec-stub-000000",
                "cluster_id": 0,
                "entry_cid": row["entry_cid"],
                "faiss_id": int(row["document_index"]),
                "document_index": int(row["document_index"]),
                "corpus_chunk_id": int(row["document_index"] // MAX_ROWS_PER_FILE),
                "corpus_row_offset": int(row["document_index"] % MAX_ROWS_PER_FILE),
                "law_cid": row.get("law_cid", ""),
                "instrument_id": row.get("instrument_id", ""),
                "law_id": row.get("law_id", ""),
                "title": row.get("title", ""),
                "record_type": row["record_type"],
                "language": row.get("language", ""),
                "jurisdiction": row.get("jurisdiction", ""),
                "embedding": None,
                "schema_version": SCHEMA_VERSION,
            }
        )
    vectors_df = pd.DataFrame(rows)
    zero = [0.0] * DIMENSION
    chunk_meta = [
        {
            "cluster_id": 0,
            "chunk_id": "vec-stub-000000",
            "centroid": zero,
            "shard_centroid": zero,
            "centroid_min_score": 0.0,
            "centroid_shard_count": 1,
            "chunk_in_cluster": 0,
            "dimension": DIMENSION,
            "model_name": MODEL_NAME,
            "row_count": int(len(vectors_df)),
            "first_key": vectors_df.iloc[0]["entry_cid"] if len(vectors_df) else "",
            "last_key": vectors_df.iloc[-1]["entry_cid"] if len(vectors_df) else "",
            "stub": True,
            "stub_reason": reason,
        }
    ]
    return {
        "vectors": vectors_df,
        "chunk_meta": chunk_meta,
        "global_centroid": zero,
        "stats": {
            "model_name": MODEL_NAME,
            "dimension": DIMENSION,
            "similarity": "cosine",
            "assignment": "stub",
            "layout": "semantic_centroid_groups",
            "rows_sorted_by": "document_index",
            "max_rows_per_chunk": MAX_ROWS_PER_FILE,
            "max_rows_per_centroid": MAX_ROWS_PER_CENTROID,
            "max_shards_per_centroid": MAX_SHARDS_PER_CENTROID,
            "default_probe_centroids": 1,
            "centroid_count": 1 if len(vectors_df) else 0,
            "shard_count": 1 if len(vectors_df) else 0,
            "n_vectors": 0,
            "status": "stub",
            "stub_reason": reason,
            "expected_columns": [
                "entry_cid",
                "document_index",
                "embedding",
                "law_cid",
                "instrument_id",
                "title",
                "record_type",
                "language",
                "jurisdiction",
            ],
        },
    }


def assemble_embeddings(
    corpus: pd.DataFrame,
    prior_by_cid: dict[str, list[float]] | None = None,
    *,
    encode_missing: bool = True,
    batch_size: int = 64,
    device: str = DEFAULT_DEVICE,
    checkpoint_path: str | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Align a (n, 384) matrix to *corpus* row order.

    Reuse is CID-keyed and only accepts real GTE vectors (finite, 384-d,
    non-zero). Stub/zero priors are treated as missing and re-encoded on
    CUDA when available — the US Code / Open US Law contract.
    """
    n = int(len(corpus))
    out = np.zeros((n, DIMENSION), dtype=np.float32)
    prior = prior_by_cid or {}
    reused_idx: list[int] = []
    missing_idx: list[int] = []
    cids = corpus["entry_cid"].astype(str).tolist() if n else []
    for i, cid in enumerate(cids):
        vec = prior.get(cid)
        if not _is_real_vector(vec):
            missing_idx.append(i)
            continue
        out[i] = np.asarray(vec, dtype=np.float32).reshape(-1)
        reused_idx.append(i)

    report: dict[str, Any] = {
        "n_docs": n,
        "n_reused": len(reused_idx),
        "n_encoded": 0,
        "n_missing": len(missing_idx),
        "model_name": MODEL_NAME,
        "model_revision": MODEL_REVISION,
        "dimension": DIMENSION,
        "status": "reused" if not missing_idx else "partial",
    }
    resolved, fallback = select_device(device)
    report["device"] = resolved
    report["device_fallback"] = fallback
    if not missing_idx:
        report["status"] = "reused"
        return _l2_normalize(out) if n else out, report
    if not encode_missing:
        report["status"] = "incomplete"
        return out, report
    if not ensure_embedding_stack():
        report["status"] = "stub_missing_encoder"
        report["reason"] = "sentence-transformers/transformers lazy install failed"
        return out, report

    missing = corpus.iloc[missing_idx].reset_index(drop=True)
    encoded = encode_corpus(
        missing,
        batch_size=batch_size,
        device=resolved,
        checkpoint_path=checkpoint_path,
    )
    for local_i, corpus_i in enumerate(missing_idx):
        out[corpus_i] = encoded[local_i]
    report["n_encoded"] = int(len(missing_idx))
    report["n_missing"] = 0
    report["status"] = "merged"
    return _l2_normalize(out), report


def embeddings_by_cid(corpus: pd.DataFrame, matrix: np.ndarray) -> dict[str, list[float]]:
    """Project a row-aligned embedding matrix back to a CID map."""
    out: dict[str, list[float]] = {}
    if corpus is None or corpus.empty:
        return out
    x = np.asarray(matrix, dtype=np.float32)
    cids = corpus["entry_cid"].astype(str).tolist()
    for i, cid in enumerate(cids):
        if i >= len(x):
            break
        out[cid] = x[i].astype(np.float32).tolist()
    return out
