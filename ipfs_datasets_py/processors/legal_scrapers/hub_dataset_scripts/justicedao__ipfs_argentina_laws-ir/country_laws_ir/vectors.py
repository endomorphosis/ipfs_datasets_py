"""thenlper/gte-small 384-d embeddings + centroid-sorted shards."""

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


def encode_corpus(corpus: pd.DataFrame, batch_size: int = 64, device: str = "cpu") -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    from .auth import configure_hf

    configure_hf()

    model = SentenceTransformer(MODEL_NAME, device=device)
    texts = []
    for rec in corpus.itertuples(index=False):
        title = rec.title or ""
        body = rec.body or ""
        # gte-small context is 512 tokens; keep title and a body prefix
        texts.append(f"{title}\n{body[:4000]}".strip() or title or rec.source_id)
    emb = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return np.asarray(emb, dtype=np.float32)


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
        # fallback equal split
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
                    "law_id": row["law_id"],
                    "title": row["title"],
                    "record_type": row["record_type"],
                    "source_type": row.get("source_type", ""),
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
        },
    }
