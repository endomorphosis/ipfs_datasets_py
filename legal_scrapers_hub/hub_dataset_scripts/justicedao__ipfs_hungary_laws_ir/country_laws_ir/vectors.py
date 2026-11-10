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
DIMENSION = 384
MAX_ROWS_PER_CENTROID = 8192
MAX_SHARDS_PER_CENTROID = 2


def _l2_normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(n, eps)


def embeddings_available() -> bool:
    try:
        import torch  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401

        return True
    except Exception:
        return False


def encode_corpus(
    corpus: pd.DataFrame,
    batch_size: int = 64,
    device: str = "cpu",
    checkpoint_path: str | None = None,
    chunk_size: int = 4096,
) -> np.ndarray:
    """Encode corpus texts with gte-small in chunks; persist checkpoints when given."""
    import json
    import os
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    from sentence_transformers import SentenceTransformer

    from .auth import configure_hf

    configure_hf()
    cache_root = _Path("/workspace/country-laws-ir/cache/hf")
    os.environ.setdefault("HF_HOME", str(cache_root))
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    os.environ.setdefault(
        "SENTENCE_TRANSFORMERS_HOME",
        str(cache_root / "sentence-transformers"),
    )
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
    meta_n = None
    if meta_path is not None and meta_path.exists():
        try:
            meta_n = json.loads(meta_path.read_text(encoding="utf-8")).get("n")
        except Exception:
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
            print(f"embeddings resume {done}/{n} from {ckpt}", flush=True)
        else:
            print(
                f"embeddings checkpoint shape {getattr(cached, 'shape', None)} "
                f"meta_n={meta_n} incompatible with {(n, DIMENSION)}; restarting",
                flush=True,
            )
    if done >= n:
        return out
    model = SentenceTransformer(MODEL_NAME, device=device)
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
        print(f"embeddings checkpoint {done}/{n}", flush=True)
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
    n = len(x)
    idx = np.arange(n)
    if n <= max_size:
        return [idx]
    labels = _spherical_kmeans(x, k=2)
    clusters = []
    for lab in (0, 1):
        members = idx[labels == lab]
        if len(members) == 0:
            continue
        if len(members) <= max_size:
            clusters.append(members)
        else:
            sub = _recursive_clusters(x[members], max_size=max_size)
            clusters.extend([members[s] for s in sub])
    if not clusters:
        mid = n // 2
        return [idx[:mid], idx[mid:]]
    return clusters


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
