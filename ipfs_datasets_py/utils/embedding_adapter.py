"""Embedding adapter for local HF models or Gemini CLI.

Codex does not provide embeddings. This helper chooses an embeddings backend
with a safe fallback order:
- Gemini CLI (if installed and enabled)
- Local HuggingFace transformers with mean pooling
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from typing import Any, Iterable, List, Optional

from ipfs_datasets_py.deps_resolver import resolve_module

_HF_RUNTIME_CACHE: dict[tuple[str, str, int, int], tuple[Any, Any, Any]] = {}
_HF_RUNTIME_CACHE_LOCK = threading.Lock()


def _get_or_create_hf_runtime(
    *,
    model_name: str,
    device: str,
    torch: Any,
    transformers: Any,
) -> tuple[Any, Any, Any]:
    """Return cached (torch, tokenizer, model) runtime for HF embeddings."""

    AutoTokenizer = getattr(transformers, "AutoTokenizer", None)
    AutoModel = getattr(transformers, "AutoModel", None)
    if AutoTokenizer is None or AutoModel is None:
        raise RuntimeError("transformers missing AutoTokenizer/AutoModel")

    cache_key = (str(model_name), str(device), id(torch), id(transformers))
    with _HF_RUNTIME_CACHE_LOCK:
        cached = _HF_RUNTIME_CACHE.get(cache_key)
        if cached is None:
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModel.from_pretrained(model_name)
            model.to(device)
            model.eval()
            cached = (torch, tokenizer, model)
            _HF_RUNTIME_CACHE[cache_key] = cached
    return cached
def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _gemini_available() -> bool:
    return shutil.which("gemini") is not None


def _select_backend() -> str:
    forced = os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_BACKEND", "").strip().lower()
    if forced:
        return forced
    if _truthy(os.getenv("IPFS_DATASETS_PY_USE_GEMINI_FOR_EMBEDDINGS")) and _gemini_available():
        return "gemini"
    if _gemini_available():
        return "gemini"
    return "hf"


def _gemini_embed(texts: List[str]) -> List[List[float]]:
    """Attempt embeddings via Gemini CLI; fall back upstream on failure."""
    cmd = os.getenv("IPFS_DATASETS_PY_GEMINI_EMBEDDINGS_CMD", "gemini embeddings --json").split()
    results: List[List[float]] = []

    for text in texts:
        try:
            proc = subprocess.run(
                cmd,
                input=text,
                text=True,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Gemini CLI not found") from exc

        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "Gemini embeddings command failed")

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Gemini embeddings output was not valid JSON") from exc

        embedding = payload.get("embedding")
        if not isinstance(embedding, list):
            raise RuntimeError("Gemini embeddings response missing 'embedding' list")
        results.append([float(x) for x in embedding])

    return results


def _hf_embed(
    texts: List[str],
    model_name: str,
    device: str,
    *,
    embedding_batch_size: int = 32,
    embedding_num_workers: int = 0,
    deps: object | None = None,
    torch_module: Any | None = None,
    transformers_module: Any | None = None,
) -> List[List[float]]:
    torch = resolve_module("torch", deps=deps, module_override=torch_module, cache_key="pip::torch")
    transformers = resolve_module(
        "transformers",
        deps=deps,
        module_override=transformers_module,
        cache_key="pip::transformers",
    )

    if torch is None or transformers is None:
        raise RuntimeError("transformers/torch not available for HF embeddings")

    torch, tokenizer, model = _get_or_create_hf_runtime(
        model_name=model_name,
        device=device,
        torch=torch,
        transformers=transformers,
    )

    if str(device).startswith("cuda"):
        try:
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA requested but torch.cuda.is_available() is False")
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

    batch_size = max(1, int(embedding_batch_size))
    num_workers = max(0, int(embedding_num_workers))

    embeddings: List[List[float]] = []
    with torch.no_grad():
        tokenizer_limit = getattr(tokenizer, "model_max_length", None)
        model_limit = getattr(getattr(model, "config", None), "max_position_embeddings", None)

        candidate_limits = []
        for lim in (tokenizer_limit, model_limit, 512):
            try:
                v = int(lim)
            except Exception:
                continue
            if v > 0 and v < 1_000_000:
                candidate_limits.append(v)
        max_len = min(candidate_limits) if candidate_limits else 512

        for start in range(0, len(texts), batch_size):
            text_batch = texts[start : start + batch_size]
            inputs = tokenizer(
                text_batch,
                padding=True,
                truncation=True,
                max_length=max_len,
                return_tensors="pt",
                **({"num_workers": num_workers} if num_workers > 0 else {}),
            )
            inputs = {k: v.to(device, non_blocking=True) for k, v in inputs.items()}
            outputs = model(**inputs)
            last_hidden = outputs.last_hidden_state
            mask = inputs.get("attention_mask")
            if mask is None:
                pooled = last_hidden.mean(dim=1)
            else:
                mask = mask.unsqueeze(-1).expand(last_hidden.size())
                masked = last_hidden * mask
                pooled = masked.sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            pooled_cpu = pooled.detach().cpu()
            for row in pooled_cpu:
                embeddings.append(row.tolist())

    return embeddings


def embed_texts(
    texts: Iterable[str],
    *,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    embedding_batch_size: int = 32,
    embedding_num_workers: int = 0,
    deps: object | None = None,
    torch_module: Any | None = None,
    transformers_module: Any | None = None,
    **kwargs: Any,
) -> List[List[float]]:
    """Embed texts using the selected backend."""
    text_list = [t for t in texts]
    backend = _select_backend()

    if backend == "gemini":
        try:
            return _gemini_embed(text_list)
        except Exception:
            # Fall back to HF if Gemini is unavailable or misconfigured.
            backend = "hf"

    if backend == "hf":
        model = model_name or os.getenv(
            "IPFS_DATASETS_PY_EMBEDDINGS_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        )
        env_batch_size = os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_BATCH_SIZE")
        env_num_workers = os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_NUM_WORKERS")
        runtime_batch_size = kwargs.get("batch_size") or kwargs.get("embedding_batch_size") or embedding_batch_size
        runtime_num_workers = kwargs.get("embedding_num_workers") or embedding_num_workers
        if env_batch_size and str(runtime_batch_size).strip() in {"", "0"}:
            runtime_batch_size = env_batch_size
        if env_num_workers and str(runtime_num_workers).strip() in {"", "0"}:
            runtime_num_workers = env_num_workers

        device_name = device or os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_DEVICE")
        if not device_name:
            torch = resolve_module("torch", deps=deps, module_override=torch_module, cache_key="pip::torch")
            try:
                device_name = "cuda" if (torch is not None and torch.cuda.is_available()) else "cpu"
            except Exception:
                device_name = "cpu"
        return _hf_embed(
            text_list,
            model,
            device_name,
            embedding_batch_size=max(1, int(runtime_batch_size)),
            embedding_num_workers=max(0, int(runtime_num_workers)),
            deps=deps,
            torch_module=torch_module,
            transformers_module=transformers_module,
        )

    raise RuntimeError(f"Unknown embeddings backend: {backend}")


def embed_text(
    text: str,
    *,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    deps: object | None = None,
    torch_module: Any | None = None,
    transformers_module: Any | None = None,
) -> List[float]:
    """Embed a single text string."""
    return embed_texts(
        [text],
        model_name=model_name,
        device=device,
        deps=deps,
        torch_module=torch_module,
        transformers_module=transformers_module,
    )[0]
