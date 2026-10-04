"""Bounded source inference using the existing pinned GTE-small producer assets."""
from __future__ import annotations

from collections import OrderedDict
import os
import threading


_MODEL_CACHE = OrderedDict()
_MODEL_LOCK = threading.RLock()
_MAX_CACHED_MODELS = 2


def clear_embedding_cache():
    """Release the private encoder models retained by source inference."""
    with _MODEL_LOCK:
        _MODEL_CACHE.clear()


def _cached_model(snapshot, device, torch, producer, asset_manifest=None):
    # Never use a parent's loaded CUDA model after a process fork, or mix
    # encoders on different current CUDA devices. Keep GPU retention bounded.
    process = os.getpid()
    for key in list(_MODEL_CACHE):
        if key[0] != process:
            del _MODEL_CACHE[key]
    key = (process, str(snapshot), device)
    if key in _MODEL_CACHE:
        _MODEL_CACHE.move_to_end(key)
        return _MODEL_CACHE[key]

    from sentence_transformers import SentenceTransformer
    with torch.random.fork_rng(devices=[]):
        model = SentenceTransformer(str(snapshot), local_files_only=True, trust_remote_code=False, device="cpu")
    model.eval()
    producer._validate_model(model, torch)
    # The receipt validator checks CPU float32 assets. Validate before moving
    # this private model; receipt production retains its existing CPU contract.
    if device != "cpu":
        model.to(device)
    if asset_manifest is not None:
        _, loaded_manifest = producer._snapshot_assets(snapshot)
        if loaded_manifest != asset_manifest:
            raise producer.EmbeddingRuntimeError("model assets changed while loading encoder")
    _MODEL_CACHE[key] = model
    while len(_MODEL_CACHE) > _MAX_CACHED_MODELS:
        _MODEL_CACHE.popitem(last=False)
    return model


def embed_texts(texts, *, snapshot_path=None):
    """Return real normalized 384D vectors; reject overlong input before encoding.

    Uses CUDA when available, otherwise CPU, with float32 model weights.
    Reuses a private encoder while verifying pinned assets on every call.
    Uses the already cached, hash-verified producer checkpoint. Does not silently
    truncate text, substitute embeddings, download weights, or invoke an LLM.
    """
    from ....optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    if type(texts) not in (list, tuple) or not 1 <= len(texts) <= 128 or any(
            type(text) is not str or not text.strip() or len(text) > 32768 for text in texts):
        raise ValueError("bounded nonempty source texts required")
    snapshot, manifest = producer._snapshot_assets(snapshot_path or producer.DEFAULT_SNAPSHOT_PATH)
    import torch
    device = "cuda:" + str(torch.cuda.current_device()) if torch.cuda.is_available() else "cpu"
    # Tokenizer/model state is private and used by one caller at a time.
    with _MODEL_LOCK:
        model = _cached_model(snapshot, device, torch, producer, manifest)
        for text in texts:
            tokens = model.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"]
            if len(tokens) > producer.MAX_TOKENS:
                raise ValueError("source exceeds GTE-small's 512-token limit; chunk it before inference")
        with torch.inference_mode():
            return model.encode(list(texts), batch_size=producer.MAX_BATCH_SIZE,
                                convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False).tolist()
