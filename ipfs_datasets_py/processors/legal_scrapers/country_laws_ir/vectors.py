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
# Above this, a DataFrame of Python floats (and the CID float cache) does not
# fit in host RAM. Spain's 332k release stayed on the in-memory layout.
STREAM_LAYOUT_MIN_ROWS = 200_000
# Above this, a second contiguous copy of the embedding matrix does not fit
# beside the corpus frame. Shards are consecutive row windows, not k-means.
SEQUENTIAL_LAYOUT_MIN_ROWS = 2_000_000


def _l2_normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(n, eps)


def _l2_normalize_inplace(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    np.maximum(norms, eps, out=norms)
    x /= norms
    return x


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


def encode_lock_path(device: str):
    """One file lock per CUDA device so two GPUs can encode at the same time."""

    import os
    from pathlib import Path

    name = str(device or "cpu").strip().lower()
    if name.startswith("cuda"):
        index = name.split(":", 1)[1] if ":" in name else "0"
        filename = f"cuda.encode.{index}.lock" if index.isdigit() else "cuda.encode.0.lock"
    else:
        filename = "cpu.encode.lock"
    root = Path(
        os.environ.get(
            "COUNTRY_LAWS_IR_ROOT",
            str(Path.home() / ".ipfs_datasets" / "country-laws-ir"),
        )
    )
    return root / filename


def corpus_cid_fingerprint(corpus: pd.DataFrame) -> str:
    """Stable id for a row-aligned corpus. Used to reuse finished layouts."""
    import hashlib

    digest = hashlib.sha256()
    digest.update(str(len(corpus)).encode("ascii"))
    digest.update(b"\n")
    for value in corpus["entry_cid"]:
        digest.update(str(value).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def load_complete_checkpoint(checkpoint_path: str | None, n: int) -> np.ndarray | None:
    """Return a finished (n, 384) float32 matrix, or None if encode must resume.

    This reads the checkpoint before any corpus text is materialized. A partial
    file (fewer rows than *n*) stays on the encoder path.
    """
    import json
    from pathlib import Path

    if not checkpoint_path or n <= 0:
        return None
    # np.array(..., copy=True) below is a second (n, 384) matrix. At the
    # American municipal size that copy is 41 GiB and the kernel SIGKILL'd
    # the encode. Large corpora resume through the on-disk memmap instead.
    if n >= SEQUENTIAL_LAYOUT_MIN_ROWS:
        return None
    ckpt = Path(checkpoint_path)
    if not ckpt.is_file():
        return None
    meta_path = ckpt.with_suffix(".json")
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        meta_n = meta.get("n")
        meta_done = meta.get("done")
        if meta_n is not None and int(meta_n) != n:
            return None
        if meta_done is not None and int(meta_done) < n:
            return None
    try:
        cached = np.load(ckpt, mmap_mode="r")
    except (OSError, ValueError):
        return None
    try:
        if getattr(cached, "shape", None) != (n, DIMENSION):
            return None
        # A read-only memmap is not writable. Later in-place L2 normalize
        # must not fall through to the stub layout.
        return np.array(cached, dtype=np.float32, copy=True, order="C")
    finally:
        del cached


def _open_resumable_matrix(ckpt: Path, meta_n: int | None, n: int) -> tuple[np.memmap, int]:
    """Full-shape memmap. A partial ``.npy`` is copied in row chunks, not into RAM.

    Anonymous ``np.zeros((26_785_250, 384))`` is 38 GiB. With the slim corpus
    frame that exceeded the memory the kernel would leave free. The JSON
    ``done`` field, not the file shape, says how many rows are encoded.
    """
    import json

    meta_done: int | None = None
    meta_path = ckpt.with_suffix(".json")
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("done") is not None:
                meta_done = int(meta["done"])
        except (OSError, ValueError):
            meta_done = None
    cached = np.load(ckpt, mmap_mode="r") if ckpt.is_file() else None
    try:
        same = cached is not None and (meta_n is None or int(meta_n) == n)
        usable = (
            same
            and cached is not None
            and cached.ndim == 2
            and cached.shape[1] == DIMENSION
            and 0 < cached.shape[0] <= n
        )
        if usable and cached is not None and cached.shape[0] == n:
            done = n if meta_done is None else min(int(meta_done), n)
            return np.load(ckpt, mmap_mode="r+"), done
        done = int(cached.shape[0]) if usable and cached is not None else 0
        tmp = ckpt.with_name(ckpt.name + ".full.npy")
        if tmp.exists():
            tmp.unlink()
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        out = np.lib.format.open_memmap(
            tmp, mode="w+", dtype=np.float32, shape=(n, DIMENSION)
        )
        if usable and cached is not None and done:
            step = 65_536
            for start in range(0, done, step):
                stop = min(start + step, done)
                out[start:stop] = cached[start:stop]
            out.flush()
        del out
    finally:
        if cached is not None:
            del cached
    tmp.replace(ckpt)
    return np.load(ckpt, mmap_mode="r+"), done


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

    finished = load_complete_checkpoint(checkpoint_path, len(corpus))
    if finished is not None:
        encode_corpus.last_checkpoint_hit = True
        return finished
    encode_corpus.last_checkpoint_hit = False
    large = len(corpus) >= STREAM_LAYOUT_MIN_ROWS
    if large and checkpoint_path and len(corpus) >= SEQUENTIAL_LAYOUT_MIN_ROWS:
        # A finished matrix is already (n, 384) on disk. Return that memmap
        # before importing the encoder, and do not copy it into RAM.
        early_ckpt = _Path(checkpoint_path)
        early_meta_n = None
        early_meta = early_ckpt.with_suffix(".json")
        if early_meta.is_file():
            try:
                early_value = json.loads(early_meta.read_text(encoding="utf-8")).get("n")
                early_meta_n = None if early_value is None else int(early_value)
            except (OSError, ValueError):
                early_meta_n = None
        early_out, early_done = _open_resumable_matrix(early_ckpt, early_meta_n, len(corpus))
        if early_done >= len(corpus):
            encode_corpus.last_checkpoint_hit = True
            return early_out
        del early_out

    if not ensure_embedding_stack():
        raise RuntimeError(
            "sentence-transformers is required for production GTE embeddings; "
            "lazy install failed (python -m ipfs_datasets_py.auto_installer)"
        )
    from sentence_transformers import SentenceTransformer

    from .auth import configure_hf

    configure_hf()
    device, _fallback = select_device(device)

    def _chunk_texts(start: int, end: int) -> list[str]:
        rows = corpus.iloc[start:end] if large else None
        source = rows.itertuples(index=False) if large else ()
        if not large:
            return texts[start:end]
        coded: list[str] = []
        for rec in source:
            title = getattr(rec, "title", None) or getattr(rec, "instrument_title", "") or ""
            body = getattr(rec, "body", "") or ""
            sid = getattr(rec, "source_id", "") or getattr(rec, "instrument_id", "")
            coded.append(f"{title}\n{str(body)[:4000]}".strip() or str(title) or str(sid))
        return coded

    texts: list[str] = []
    if not large:
        for rec in corpus.itertuples(index=False):
            title = getattr(rec, "title", None) or getattr(rec, "instrument_title", "") or ""
            body = getattr(rec, "body", "") or ""
            sid = getattr(rec, "source_id", "") or getattr(rec, "instrument_id", "")
            texts.append(f"{title}\n{body[:4000]}".strip() or title or sid)
    n = len(corpus) if large else len(texts)
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
    if large and ckpt is not None:
        out, done = _open_resumable_matrix(ckpt, meta_n, n)
        if done >= n:
            return out
    else:
        import gc

        gc.collect()
        out = np.zeros((n, DIMENSION), dtype=np.float32)
        done = 0
        if ckpt is not None and ckpt.exists():
            cached = np.load(ckpt, mmap_mode="r")
            same_corpus = meta_n is None or int(meta_n) == n
            if (
                same_corpus
                and cached.ndim == 2
                and cached.shape[1] == DIMENSION
                and 0 < cached.shape[0] <= n
            ):
                done = int(cached.shape[0])
                out[:done] = cached
            del cached
            if done >= n:
                return out

    lock_fh = None
    if device.startswith("cuda") or device == "cpu":
        import fcntl

        lock_path = encode_lock_path(device)
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
        def _save_checkpoint() -> None:
            if ckpt is None:
                return
            ckpt.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(out, np.memmap):
                out.flush()
            else:
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
            print(f"embedding checkpoint done={done} n={n}", flush=True)

        # Rewriting the whole prefix every 4096 rows turned a 27M encode into
        # tens of terabytes of checkpoint IO. Keep a resume point about every
        # half million rows, and always save the finished matrix.
        last_saved = done
        checkpoint_every = 524_288

        def _maybe_save(force: bool = False) -> None:
            nonlocal last_saved
            if done == last_saved:
                return
            if not force and (done - last_saved) < checkpoint_every:
                return
            _save_checkpoint()
            last_saved = done

        body_path = ""
        if large and "body" not in getattr(corpus, "columns", []):
            body_path = str((getattr(corpus, "attrs", None) or {}).get("body_parquet") or "")
        if body_path:
            import pyarrow.parquet as pq

            parquet = pq.ParquetFile(body_path)
            names = set(parquet.schema_arrow.names)
            columns = [
                name
                for name in (
                    "title",
                    "instrument_title",
                    "body",
                    "source_id",
                    "instrument_id",
                )
                if name in names
            ]
            cursor = 0
            for batch in parquet.iter_batches(batch_size=int(chunk_size), columns=columns):
                width = int(batch.num_rows)
                if cursor + width <= done:
                    cursor += width
                    continue
                frame = batch.to_pandas()
                if cursor < done:
                    frame = frame.iloc[done - cursor :]
                coded: list[str] = []
                for rec in frame.itertuples(index=False):
                    title = getattr(rec, "title", None) or getattr(rec, "instrument_title", "") or ""
                    body = getattr(rec, "body", "") or ""
                    sid = getattr(rec, "source_id", "") or getattr(rec, "instrument_id", "")
                    coded.append(f"{title}\n{str(body)[:4000]}".strip() or str(title) or str(sid))
                if not coded:
                    cursor += width
                    continue
                encoded = model.encode(
                    coded,
                    batch_size=batch_size,
                    show_progress_bar=True,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
                start = done
                done = start + len(coded)
                out[start:done] = np.asarray(encoded, dtype=np.float32)
                cursor += width
                _maybe_save(force=done >= n)
            _maybe_save(force=True)
            return out

        while done < n:
            j = min(done + int(chunk_size), n)
            chunk = model.encode(
                _chunk_texts(done, j),
                batch_size=batch_size,
                show_progress_bar=True,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            out[done:j] = np.asarray(chunk, dtype=np.float32)
            done = j
            _maybe_save(force=done >= n)
        _maybe_save(force=True)
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


def _masked_mean(x: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Mean of selected rows without copying a large boolean slice of ``x``."""
    acc = np.zeros(x.shape[1], dtype=np.float64)
    count = 0
    step = 262_144
    for start in range(0, len(x), step):
        stop = min(start + step, len(x))
        part_mask = mask[start:stop]
        if not part_mask.any():
            continue
        block = x[start:stop][part_mask]
        acc += block.sum(axis=0, dtype=np.float64)
        count += int(block.shape[0])
    if count == 0:
        raise RuntimeError("masked mean of no rows")
    return acc / count


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
                new.append(_l2_normalize(_masked_mean(x, mask)))
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
        # Fancy-indexing the full matrix copies every embedding. The first
        # split is the whole array, which is already in row order.
        block = x if len(idx) == len(x) and int(idx[0]) == 0 and int(idx[-1]) == len(x) - 1 else x[idx]
        labels = _spherical_kmeans(block, k=2)
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


def _missing_cell(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _cell_str(column: np.ndarray | None, index: int, default: str = "") -> str:
    if column is None:
        return default
    value = column[index]
    if _missing_cell(value):
        return default
    return str(value)


def _column(corpus: pd.DataFrame, name: str) -> np.ndarray | None:
    if name not in corpus.columns:
        return None
    return corpus[name].to_numpy(copy=False)


def _embedding_list_array(block: np.ndarray):
    import pyarrow as pa

    flat = np.ascontiguousarray(block, dtype=np.float64).reshape(-1)
    offsets = np.arange(0, (block.shape[0] + 1) * DIMENSION, DIMENSION, dtype=np.int32)
    return pa.ListArray.from_arrays(
        pa.array(offsets, type=pa.int32()),
        pa.array(flat, type=pa.float64()),
    )


def _vector_table(rows: dict[str, list], embeddings: np.ndarray):
    import pyarrow as pa

    n = embeddings.shape[0]
    return pa.table(
        {
            "chunk_id": pa.array(rows["chunk_id"], type=pa.string()),
            "cluster_id": pa.array(rows["cluster_id"], type=pa.int64()),
            "entry_cid": pa.array(rows["entry_cid"], type=pa.string()),
            "faiss_id": pa.array(rows["faiss_id"], type=pa.int64()),
            "document_index": pa.array(rows["document_index"], type=pa.int64()),
            "corpus_chunk_id": pa.array(rows["corpus_chunk_id"], type=pa.int64()),
            "corpus_row_offset": pa.array(rows["corpus_row_offset"], type=pa.int64()),
            "law_cid": pa.array(rows["law_cid"], type=pa.string()),
            "instrument_id": pa.array(rows["instrument_id"], type=pa.string()),
            "law_id": pa.array(rows["law_id"], type=pa.string()),
            "title": pa.array(rows["title"], type=pa.string()),
            "record_type": pa.array(rows["record_type"], type=pa.string()),
            "language": pa.array(rows["language"], type=pa.string()),
            "jurisdiction": pa.array(rows["jurisdiction"], type=pa.string()),
            "embedding": _embedding_list_array(embeddings),
            "schema_version": pa.array([SCHEMA_VERSION] * n, type=pa.string()),
        }
    )


def _write_vector_shard(path, table) -> None:
    import pyarrow.parquet as pq

    from .parquet_io import COMPRESSION, COMPRESSION_LEVEL

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        path,
        compression=COMPRESSION,
        compression_level=COMPRESSION_LEVEL,
        row_group_size=max(table.num_rows, 1),
        use_dictionary=True,
    )


def _layout_manifest_path(out_dir) -> "Path":
    from pathlib import Path

    return Path(out_dir) / "layout.json"


def try_load_streamed_layout(corpus: pd.DataFrame, out_dir) -> dict[str, Any] | None:
    """Reuse vector shards already written for this corpus fingerprint."""
    import json
    from pathlib import Path

    out_dir = Path(out_dir)
    manifest_path = _layout_manifest_path(out_dir)
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("fingerprint") != corpus_cid_fingerprint(corpus):
        return None
    if int(payload.get("n_vectors") or 0) != len(corpus):
        return None
    rows = payload.get("vector_index_rows") or []
    if not rows:
        return None
    for row in rows:
        name = Path(row["relative_path"]).name
        path = out_dir / name
        if not path.is_file() or path.stat().st_size != int(row["size_bytes"]):
            return None
    payload["prewritten_dir"] = str(out_dir)
    payload.pop("fingerprint", None)
    return payload


_SEQUENTIAL_META_COLUMNS = (
    "law_cid",
    "instrument_id",
    "law_id",
    "title",
    "instrument_title",
    "record_type",
    "language",
    "jurisdiction",
)


class _ParquetRowSource:
    """Yield corpus rows in file order without reading a whole string column."""

    def __init__(self, path: str, columns: list[str], batch_size: int) -> None:
        import pyarrow.parquet as pq

        self._batches = pq.ParquetFile(path).iter_batches(
            batch_size=max(int(batch_size), 1),
            columns=columns,
        )
        self._frame: pd.DataFrame | None = None
        self._offset = 0

    def take(self, n: int) -> pd.DataFrame:
        parts: list[pd.DataFrame] = []
        left = int(n)
        while left:
            if self._frame is None or self._offset >= len(self._frame):
                try:
                    batch = next(self._batches)
                except StopIteration as exc:
                    raise RuntimeError(
                        f"corpus parquet ended {n - left} rows short of a {n}-row window"
                    ) from exc
                self._frame = batch.to_pandas()
                self._offset = 0
            avail = len(self._frame) - self._offset
            take_n = min(left, avail)
            parts.append(self._frame.iloc[self._offset : self._offset + take_n])
            self._offset += take_n
            left -= take_n
        if len(parts) == 1:
            return parts[0].reset_index(drop=True)
        return pd.concat(parts, ignore_index=True)

    def finished(self) -> bool:
        if self._frame is not None and self._offset < len(self._frame):
            return False
        try:
            batch = next(self._batches)
        except StopIteration:
            return True
        self._frame = batch.to_pandas()
        self._offset = 0
        return len(self._frame) == 0


def _layout_vectors_sequential(
    corpus: pd.DataFrame,
    embeddings: np.ndarray,
    out_dir,
    fingerprint: str,
    log=None,
) -> dict[str, Any]:
    """Write consecutive row shards from a memmap. Do not copy the matrix.

    Semantic k-means needs a contiguous ``(n, 384)`` matrix. At a few million
    rows that copy, plus a fancy-index of a half, no longer fits. Each shard
    is one ``MAX_ROWS_PER_FILE`` window, L2-normalized and centroid-sorted on
    its own copy of a few thousand rows. String columns that are not on the
    slim frame are read from ``corpus.attrs['body_parquet']`` for that window.
    """
    import json
    from pathlib import Path

    from .cidutil import file_descriptor

    out_dir = Path(out_dir)
    n = len(corpus)
    if int(getattr(embeddings, "shape", (0,))[0]) != n:
        raise ValueError("sequential layout requires one embedding row per corpus row")
    entry_cid = _column(corpus, "entry_cid")
    if entry_cid is None:
        raise ValueError("sequential layout requires entry_cid on the corpus frame")
    document_index = _column(corpus, "document_index")
    present = {
        name: column
        for name in _SEQUENTIAL_META_COLUMNS
        if (column := _column(corpus, name)) is not None
    }
    missing = [name for name in _SEQUENTIAL_META_COLUMNS if name not in present]
    body_path = str((getattr(corpus, "attrs", None) or {}).get("body_parquet") or "")
    source = None
    if missing:
        if not body_path:
            raise ValueError(
                "sequential layout is missing "
                + ",".join(missing)
                + " and corpus.attrs['body_parquet']"
            )
        source = _ParquetRowSource(body_path, missing, MAX_ROWS_PER_FILE)
    if log:
        log(
            f"sequential vector layout n={n} shard_rows={MAX_ROWS_PER_FILE} "
            f"frame_columns={','.join(map(str, corpus.columns))}"
        )
    shard_rows = max(int(MAX_ROWS_PER_FILE), 1)
    centroid_acc = np.zeros(DIMENSION, dtype=np.float64)
    chunk_meta: list[dict[str, Any]] = []
    vector_index_rows: list[dict[str, Any]] = []
    n_written = 0
    cluster_id = 0
    start = 0
    while start < n:
        stop = min(start + shard_rows, n)
        block = np.array(embeddings[start:stop], dtype=np.float32, copy=True)
        _l2_normalize_inplace(block)
        centroid_acc += block.sum(axis=0, dtype=np.float64)
        shard_centroid = _l2_normalize(block.mean(axis=0))
        order = np.argsort(-(block @ shard_centroid))
        block = block[order]
        width = stop - start
        positions = np.arange(start, stop, dtype=np.int64)[order]
        window = pd.DataFrame(
            {
                "entry_cid": np.asarray(entry_cid[start:stop])[order],
                "document_index": (
                    np.asarray(document_index[start:stop])[order]
                    if document_index is not None
                    else positions
                ),
            }
        )
        for name, column in present.items():
            window[name] = np.asarray(column[start:stop])[order]
        if source is not None:
            piece = source.take(width).iloc[np.asarray(order)].reset_index(drop=True)
            for name in missing:
                if name in piece.columns:
                    window[name] = piece[name].to_numpy(copy=False)
        window = window.reset_index(drop=True)
        columns = {name: window[name].to_numpy(copy=False) for name in window.columns}
        n_rows = int(width)
        chunk_id = f"vec-{cluster_id:06d}"
        rows: dict[str, list] = {
            "chunk_id": [chunk_id] * n_rows,
            "cluster_id": [int(cluster_id)] * n_rows,
            "entry_cid": [],
            "faiss_id": [],
            "document_index": [],
            "corpus_chunk_id": [],
            "corpus_row_offset": [],
            "law_cid": [],
            "instrument_id": [],
            "law_id": [],
            "title": [],
            "record_type": [],
            "language": [],
            "jurisdiction": [],
        }
        for local_i in range(n_rows):
            pos = int(positions[local_i])
            doc_index = (
                int(columns["document_index"][local_i])
                if "document_index" in columns
                else pos
            )
            inst = _cell_str(
                columns.get("instrument_id"),
                local_i,
                _cell_str(columns.get("law_id"), local_i, ""),
            )
            law = _cell_str(columns.get("law_id"), local_i, inst)
            rows["entry_cid"].append(_cell_str(columns.get("entry_cid"), local_i, ""))
            rows["faiss_id"].append(pos)
            rows["document_index"].append(doc_index)
            rows["corpus_chunk_id"].append(int(doc_index // shard_rows))
            rows["corpus_row_offset"].append(int(doc_index % shard_rows))
            rows["law_cid"].append(_cell_str(columns.get("law_cid"), local_i, ""))
            rows["instrument_id"].append(inst)
            rows["law_id"].append(law)
            rows["title"].append(
                _cell_str(
                    columns.get("title"),
                    local_i,
                    _cell_str(columns.get("instrument_title"), local_i, ""),
                )
            )
            rows["record_type"].append(_cell_str(columns.get("record_type"), local_i, ""))
            rows["language"].append(_cell_str(columns.get("language"), local_i, ""))
            rows["jurisdiction"].append(_cell_str(columns.get("jurisdiction"), local_i, ""))
        name = f"part-{cluster_id:06d}.parquet"
        path = out_dir / name
        _write_vector_shard(path, _vector_table(rows, block))
        first_key = rows["entry_cid"][0] if n_rows else ""
        last_key = rows["entry_cid"][-1] if n_rows else ""
        vector_index_rows.append(
            file_descriptor(
                path,
                f"data/vectors/{name}",
                extra={
                    "shard_id": int(cluster_id),
                    "kind": "vectors",
                    "row_count": n_rows,
                    "first_key": first_key,
                    "last_key": last_key,
                    "start_document_index": int(rows["document_index"][0]) if n_rows else 0,
                    "end_document_index": int(rows["document_index"][-1]) if n_rows else 0,
                    "schema_version": SCHEMA_VERSION,
                },
            )
        )
        centroid = shard_centroid.tolist()
        sims = block @ shard_centroid
        chunk_meta.append(
            {
                "cluster_id": int(cluster_id),
                "chunk_id": chunk_id,
                "centroid": centroid,
                "shard_centroid": centroid,
                "centroid_min_score": float(sims.min()) if n_rows else 0.0,
                "centroid_shard_count": 1,
                "chunk_in_cluster": 0,
                "dimension": DIMENSION,
                "model_name": MODEL_NAME,
                "row_count": n_rows,
                "first_key": first_key,
                "last_key": last_key,
            }
        )
        n_written += n_rows
        if log and (cluster_id % 100 == 0 or stop == n):
            log(f"vector shards written {cluster_id + 1} rows={n_written}")
        del block, rows, window
        cluster_id += 1
        start = stop
    if source is not None and not source.finished():
        raise RuntimeError("corpus parquet has more rows than the embedding matrix")
    global_centroid = _l2_normalize(
        np.asarray(centroid_acc / max(n_written, 1), dtype=np.float32)
    ).tolist()
    result = {
        "prewritten_dir": str(out_dir),
        "vector_index_rows": vector_index_rows,
        "chunk_meta": chunk_meta,
        "global_centroid": global_centroid,
        "stats": {
            "model_name": MODEL_NAME,
            "dimension": DIMENSION,
            "similarity": "cosine",
            "assignment": "sequential_row_chunks",
            "layout": "sequential_row_chunks",
            "rows_sorted_by": "cosine_similarity_to_shard_centroid_desc",
            "max_rows_per_chunk": shard_rows,
            "max_rows_per_centroid": MAX_ROWS_PER_CENTROID,
            "max_shards_per_centroid": MAX_SHARDS_PER_CENTROID,
            "default_probe_centroids": min(4, max(1, len(chunk_meta))),
            "centroid_count": len(chunk_meta),
            "shard_count": len(chunk_meta),
            "n_vectors": int(n_written),
            "status": "embedded",
        },
    }
    manifest = dict(result)
    manifest["fingerprint"] = fingerprint
    manifest["n_vectors"] = int(n_written)
    _layout_manifest_path(out_dir).write_text(
        json.dumps(manifest, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return result


def layout_vectors_streaming(
    corpus: pd.DataFrame,
    embeddings: np.ndarray | None,
    out_dir,
    log=None,
) -> dict[str, Any]:
    """Write centroid-sorted vector shards without a Python-float DataFrame.

    A finished ``layout.json`` for this corpus is returned as-is, so a restart
    after the embedding checkpoint does not cluster or re-encode.
    """
    import json
    import shutil
    from pathlib import Path

    from .cidutil import file_descriptor

    out_dir = Path(out_dir)
    cached = try_load_streamed_layout(corpus, out_dir)
    if cached is not None:
        if log:
            log(
                f"reused vector shards {out_dir} "
                f"n={cached['stats']['n_vectors']} shards={cached['stats']['shard_count']}"
            )
        return cached
    if embeddings is None:
        raise ValueError("vector layout cache miss requires an embedding matrix")

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = corpus_cid_fingerprint(corpus)
    if len(corpus) >= SEQUENTIAL_LAYOUT_MIN_ROWS:
        return _layout_vectors_sequential(corpus, embeddings, out_dir, fingerprint, log)
    x = np.ascontiguousarray(embeddings, dtype=np.float32)
    _l2_normalize_inplace(x)
    if log:
        log(f"clustering {len(corpus)} vectors into shards of {MAX_ROWS_PER_FILE}")
    clusters = _recursive_clusters(x, max_size=MAX_ROWS_PER_FILE)
    if log:
        log(f"vector clusters={len(clusters)}")
    global_centroid = _l2_normalize(x.mean(axis=0)).tolist()

    entry_cid = _column(corpus, "entry_cid")
    document_index = _column(corpus, "document_index")
    law_cid = _column(corpus, "law_cid")
    instrument_id = _column(corpus, "instrument_id")
    law_id = _column(corpus, "law_id")
    title = _column(corpus, "title")
    instrument_title = _column(corpus, "instrument_title")
    record_type = _column(corpus, "record_type")
    language = _column(corpus, "language")
    jurisdiction = _column(corpus, "jurisdiction")

    chunk_meta: list[dict[str, Any]] = []
    vector_index_rows: list[dict[str, Any]] = []
    n_written = 0
    for cluster_id, members in enumerate(clusters):
        members = np.asarray(members, dtype=np.int64)
        block = x[members]
        shard_centroid = _l2_normalize(block.mean(axis=0))
        sims = block @ shard_centroid
        order = np.argsort(-sims)
        members = members[order]
        block = block[order]
        sims = sims[order]
        chunk_id = f"vec-{cluster_id:06d}"
        n_rows = int(len(members))
        rows: dict[str, list] = {
            "chunk_id": [chunk_id] * n_rows,
            "cluster_id": [int(cluster_id)] * n_rows,
            "entry_cid": [],
            "faiss_id": [],
            "document_index": [],
            "corpus_chunk_id": [],
            "corpus_row_offset": [],
            "law_cid": [],
            "instrument_id": [],
            "law_id": [],
            "title": [],
            "record_type": [],
            "language": [],
            "jurisdiction": [],
        }
        for doc_i in members:
            pos = int(doc_i)
            doc_index = int(document_index[pos]) if document_index is not None else pos
            inst = _cell_str(instrument_id, pos, _cell_str(law_id, pos, ""))
            law = _cell_str(law_id, pos, inst)
            rows["entry_cid"].append(_cell_str(entry_cid, pos, ""))
            rows["faiss_id"].append(pos)
            rows["document_index"].append(doc_index)
            rows["corpus_chunk_id"].append(int(doc_index // MAX_ROWS_PER_FILE))
            rows["corpus_row_offset"].append(int(doc_index % MAX_ROWS_PER_FILE))
            rows["law_cid"].append(_cell_str(law_cid, pos, ""))
            rows["instrument_id"].append(inst)
            rows["law_id"].append(law)
            rows["title"].append(_cell_str(title, pos, _cell_str(instrument_title, pos, "")))
            rows["record_type"].append(_cell_str(record_type, pos, ""))
            rows["language"].append(_cell_str(language, pos, ""))
            rows["jurisdiction"].append(_cell_str(jurisdiction, pos, ""))
        name = f"part-{cluster_id:06d}.parquet"
        path = out_dir / name
        _write_vector_shard(path, _vector_table(rows, block))
        first_key = rows["entry_cid"][0] if n_rows else ""
        last_key = rows["entry_cid"][-1] if n_rows else ""
        vector_index_rows.append(
            file_descriptor(
                path,
                f"data/vectors/{name}",
                extra={
                    "shard_id": int(cluster_id),
                    "kind": "vectors",
                    "row_count": n_rows,
                    "first_key": first_key,
                    "last_key": last_key,
                    "start_document_index": int(rows["document_index"][0]) if n_rows else 0,
                    "end_document_index": int(rows["document_index"][-1]) if n_rows else 0,
                    "schema_version": SCHEMA_VERSION,
                },
            )
        )
        centroid = shard_centroid.tolist()
        chunk_meta.append(
            {
                "cluster_id": int(cluster_id),
                "chunk_id": chunk_id,
                "centroid": centroid,
                "shard_centroid": centroid,
                "centroid_min_score": float(sims.min()) if n_rows else 0.0,
                "centroid_shard_count": 1,
                "chunk_in_cluster": 0,
                "dimension": DIMENSION,
                "model_name": MODEL_NAME,
                "row_count": n_rows,
                "first_key": first_key,
                "last_key": last_key,
            }
        )
        n_written += n_rows
        if log and (cluster_id % 100 == 0 or cluster_id + 1 == len(clusters)):
            log(f"vector shards written {cluster_id + 1}/{len(clusters)} rows={n_written}")

    result = {
        "prewritten_dir": str(out_dir),
        "vector_index_rows": vector_index_rows,
        "chunk_meta": chunk_meta,
        "global_centroid": global_centroid,
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
            "n_vectors": int(n_written),
            "status": "embedded",
        },
    }
    manifest = dict(result)
    manifest["fingerprint"] = fingerprint
    manifest["n_vectors"] = int(n_written)
    _layout_manifest_path(out_dir).write_text(
        json.dumps(manifest, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    del x
    return result


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
    prior = prior_by_cid or {}
    resolved, fallback = select_device(device)
    if n and not prior and encode_missing:
        encoded = encode_corpus(
            corpus,
            batch_size=batch_size,
            device=resolved,
            checkpoint_path=checkpoint_path,
        )
        report = {
            "n_docs": n,
            "n_reused": 0,
            "n_encoded": n,
            "n_missing": 0,
            "model_name": MODEL_NAME,
            "model_revision": MODEL_REVISION,
            "dimension": DIMENSION,
            "status": "checkpoint" if encode_corpus.last_checkpoint_hit else "encoded",
            "device": resolved,
            "device_fallback": fallback,
        }
        return encoded, report

    out = np.zeros((n, DIMENSION), dtype=np.float32)
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
