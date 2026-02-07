"""Embeddings router.

This module provides a stable, reusable entrypoint for generating embeddings.

Design goals:
- Avoid import-time side effects (no heavy imports at module import).
- Allow optional hooks/providers (ipfs_accelerate_py, custom remote endpoints).
- Provide a reliable local fallback (Gemini CLI -> HF transformers) via
  `ipfs_datasets_py.utils.embedding_adapter`.

Environment variables:
- `IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE`: enable ipfs_accelerate_py provider (best-effort)
- `IPFS_DATASETS_PY_EMBEDDINGS_BACKEND`: force backend for local adapter (e.g. "gemini" or "hf")
- `IPFS_DATASETS_PY_EMBEDDINGS_MODEL`: HF model name for local adapter
- `IPFS_DATASETS_PY_EMBEDDINGS_DEVICE`: device for local adapter (cpu/cuda)

Additional optional providers (opt-in by selecting provider):
- `openrouter`: OpenRouter embeddings endpoint
    - `OPENROUTER_API_KEY` or `IPFS_DATASETS_PY_OPENROUTER_API_KEY`
    - `IPFS_DATASETS_PY_OPENROUTER_EMBEDDINGS_MODEL`
    - `IPFS_DATASETS_PY_OPENROUTER_BASE_URL` (default: https://openrouter.ai/api/v1)
- `gemini_cli`: Gemini CLI embeddings command (same as embedding_adapter)
    - `IPFS_DATASETS_PY_GEMINI_EMBEDDINGS_CMD` (default: "gemini embeddings --json")
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from typing import Callable, Dict, Iterable, List, Optional, Protocol, runtime_checkable

from .router_deps import RouterDeps, get_default_router_deps


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _cache_enabled() -> bool:
    return os.environ.get("IPFS_DATASETS_PY_ROUTER_CACHE", "1").strip() != "0"


def _response_cache_enabled() -> bool:
    value = os.environ.get("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE")
    if value is None:
        return _truthy(os.environ.get("IPFS_DATASETS_PY_BENCHMARK"))
    return str(value).strip() != "0"


def _response_cache_key_strategy() -> str:
    return os.environ.get("IPFS_DATASETS_PY_ROUTER_CACHE_KEY", "sha256").strip().lower() or "sha256"


def _response_cache_cid_base() -> str:
    return os.environ.get("IPFS_DATASETS_PY_ROUTER_CACHE_CID_BASE", "base32").strip() or "base32"


def _stable_kwargs_digest(kwargs: Dict[str, object]) -> str:
    if not kwargs:
        return ""
    try:
        payload = json.dumps(kwargs, sort_keys=True, default=repr, ensure_ascii=False)
    except Exception:
        payload = repr(sorted(kwargs.items(), key=lambda x: str(x[0])))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _text_digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _effective_model_key(*, provider_key: str, model_name: Optional[str], kwargs: Dict[str, object]) -> str:
    """Best-effort model identifier for caching.

    Embeddings callers sometimes pass model via kwargs (e.g. ``model=...``), and
    the local adapter uses env defaults. Cache keys must include the effective
    model to avoid cross-model collisions.
    """

    direct = (model_name or "").strip()
    if direct:
        return direct

    for key in ("model", "model_name", "model_id"):
        try:
            value = kwargs.get(key)
        except Exception:
            value = None
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text

    pk = (provider_key or "auto").strip().lower()
    if pk == "openrouter":
        return (
            os.getenv("IPFS_DATASETS_PY_OPENROUTER_EMBEDDINGS_MODEL")
            or os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_MODEL")
            or ""
        ).strip()

    # Local adapter / default.
    return (os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_MODEL", "") or "").strip()


def _response_cache_key(
    *,
    provider: Optional[str],
    model_name: Optional[str],
    device: Optional[str],
    text: str,
    kwargs: Dict[str, object],
) -> str:
    provider_key = (provider or "auto").strip().lower()
    model_key = _effective_model_key(provider_key=provider_key, model_name=model_name, kwargs=kwargs)
    device_key = (device or "").strip().lower()

    strategy = _response_cache_key_strategy()
    if strategy == "cid":
        from .utils.cid_utils import cid_for_obj

        payload = {
            "type": "embeddings_response",
            "provider": provider_key,
            "model": model_key,
            "device": device_key,
            "text": text or "",
            "kwargs": kwargs or {},
        }
        cid = cid_for_obj(payload, base=_response_cache_cid_base())
        return f"embeddings_response_cid::{cid}"

    kw_digest = _stable_kwargs_digest(kwargs)
    return f"embeddings_response::{provider_key}::{model_key}::{device_key}::{_text_digest(text)}::{kw_digest}"


@runtime_checkable
class EmbeddingsProvider(Protocol):
    """Provider interface for embedding generation."""

    def embed_texts(
        self,
        texts: Iterable[str],
        *,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        **kwargs: object,
    ) -> List[List[float]]: ...


ProviderFactory = Callable[[], EmbeddingsProvider]


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    factory: ProviderFactory


_PROVIDER_REGISTRY: Dict[str, ProviderInfo] = {}


def register_embeddings_provider(name: str, factory: ProviderFactory) -> None:
    """Register a custom embeddings provider."""

    if not name or not name.strip():
        raise ValueError("Provider name must be non-empty")
    _PROVIDER_REGISTRY[name] = ProviderInfo(name=name, factory=factory)


def _coalesce_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _get_openrouter_provider() -> Optional[EmbeddingsProvider]:
    api_key = _coalesce_env("IPFS_DATASETS_PY_OPENROUTER_API_KEY", "OPENROUTER_API_KEY")
    if not api_key:
        return None

    base_url = os.getenv("IPFS_DATASETS_PY_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")

    class _OpenRouterEmbeddingsProvider:
        def embed_texts(
            self,
            texts: Iterable[str],
            *,
            model_name: Optional[str] = None,
            device: Optional[str] = None,
            **kwargs: object,
        ) -> List[List[float]]:
            _ = device
            model = (
                model_name
                or os.getenv("IPFS_DATASETS_PY_OPENROUTER_EMBEDDINGS_MODEL")
                or os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_MODEL")
                or "text-embedding-3-small"
            )
            inputs = list(texts)
            payload = {"model": model, "input": inputs}

            req = urllib.request.Request(
                f"{base_url}/embeddings",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    **({"HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER")} if os.getenv("OPENROUTER_HTTP_REFERER") else {}),
                    **({"X-Title": os.getenv("OPENROUTER_APP_TITLE")} if os.getenv("OPENROUTER_APP_TITLE") else {}),
                },
            )

            try:
                with urllib.request.urlopen(req, timeout=float(kwargs.get("timeout", 120))) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail or exc.reason}") from exc
            except Exception as exc:
                raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

            try:
                data = json.loads(raw)
            except Exception as exc:
                raise RuntimeError("OpenRouter returned invalid JSON") from exc

            items = data.get("data")
            if not isinstance(items, list):
                raise RuntimeError("OpenRouter embeddings response missing data")
            embeddings: List[List[float]] = []
            for item in items:
                if not isinstance(item, dict) or "embedding" not in item:
                    raise RuntimeError("OpenRouter embeddings item missing embedding")
                vec = item["embedding"]
                if not isinstance(vec, list):
                    raise RuntimeError("OpenRouter embedding must be a list")
                embeddings.append([float(x) for x in vec])
            if len(embeddings) != len(inputs):
                # Best-effort: still return what we got if non-empty.
                if embeddings:
                    return embeddings
                raise RuntimeError("OpenRouter returned no embeddings")
            return embeddings

    return _OpenRouterEmbeddingsProvider()


def _get_gemini_cli_provider() -> Optional[EmbeddingsProvider]:
    command = os.getenv("IPFS_DATASETS_PY_GEMINI_EMBEDDINGS_CMD", "gemini embeddings --json")
    parts = shlex.split(command)
    if not parts:
        return None
    if parts[0] != "npx" and shutil.which(parts[0]) is None:
        return None

    class _GeminiCLIEmbeddingsProvider:
        def embed_texts(
            self,
            texts: Iterable[str],
            *,
            model_name: Optional[str] = None,
            device: Optional[str] = None,
            **kwargs: object,
        ) -> List[List[float]]:
            _ = model_name
            _ = device
            payload = {"texts": list(texts)}
            proc = subprocess.run(
                parts,
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
                timeout=float(kwargs.get("timeout", 120)),
                env=os.environ.copy(),
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or "Gemini embeddings command failed")
            try:
                data = json.loads(proc.stdout)
            except Exception as exc:
                raise RuntimeError("Gemini embeddings output was not valid JSON") from exc
            if not isinstance(data, dict) or "embeddings" not in data:
                raise RuntimeError("Gemini embeddings response missing 'embeddings'")
            raw_embeddings = data["embeddings"]
            if not isinstance(raw_embeddings, list):
                raise RuntimeError("Gemini embeddings must be a list")
            out: List[List[float]] = []
            for item in raw_embeddings:
                if isinstance(item, dict) and isinstance(item.get("embedding"), list):
                    out.append([float(x) for x in item["embedding"]])
                elif isinstance(item, list):
                    out.append([float(x) for x in item])
                else:
                    raise RuntimeError("Gemini embeddings item missing embedding")
            return out

    return _GeminiCLIEmbeddingsProvider()


def _builtin_provider_by_name(name: str, *, deps: RouterDeps) -> Optional[EmbeddingsProvider]:
    key = (name or "").strip().lower()
    if not key:
        return None
    if key == "openrouter":
        return _get_openrouter_provider()
    if key in {"gemini", "gemini_cli"}:
        return _get_gemini_cli_provider()
    if key in {"adapter", "local", "local_adapter"}:
        return _get_local_adapter_provider(deps=deps)
    return None


def _get_accelerate_provider(deps: RouterDeps) -> Optional[EmbeddingsProvider]:
    if not _truthy(os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE")):
        return None

    try:
        manager = deps.get_accelerate_manager(
            purpose="embeddings_router",
            enable_distributed=True,
            resources={"purpose": "embeddings_router"},
        )
        if manager is None:
            return None

        class _AccelerateEmbeddingsProvider:
            def embed_texts(
                self,
                texts: Iterable[str],
                *,
                model_name: Optional[str] = None,
                device: Optional[str] = None,
                **kwargs: object,
            ) -> List[List[float]]:
                # NOTE: AccelerateManager.run_inference is currently a best-effort wrapper.
                # We keep this provider as a hook point; if accelerate can't produce real
                # embeddings, we fail so the router can fall back.
                payload = {"texts": list(texts), "device": device, **kwargs}
                result = manager.run_inference(
                    model_name or os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_MODEL", ""),
                    payload,
                    task_type="embedding",
                )
                embedded = result.get("embeddings")
                if isinstance(embedded, list):
                    return [[float(x) for x in row] for row in embedded]
                raise RuntimeError("ipfs_accelerate_py provider did not return embeddings")

        return _AccelerateEmbeddingsProvider()
    except Exception:
        return None


def _provider_cache_key() -> tuple:
    return (
        os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_PROVIDER", "").strip(),
        os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE", "").strip(),
        os.getenv("IPFS_DATASETS_PY_OPENROUTER_API_KEY", "").strip(),
        os.getenv("OPENROUTER_API_KEY", "").strip(),
        os.getenv("IPFS_DATASETS_PY_OPENROUTER_EMBEDDINGS_MODEL", "").strip(),
        os.getenv("IPFS_DATASETS_PY_OPENROUTER_BASE_URL", "").strip(),
        os.getenv("IPFS_DATASETS_PY_GEMINI_EMBEDDINGS_CMD", "").strip(),
        os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_BACKEND", "").strip(),
        os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_MODEL", "").strip(),
        os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_DEVICE", "").strip(),
    )


def _deps_provider_cache_key(preferred: Optional[str], cache_key: tuple) -> str:
    digest = hashlib.sha256(repr(cache_key).encode("utf-8")).hexdigest()[:16]
    return f"embeddings_provider::{(preferred or '').strip().lower()}::{digest}"


@lru_cache(maxsize=32)
def _resolve_provider_cached(preferred: Optional[str], cache_key: tuple) -> EmbeddingsProvider:
    _ = cache_key
    return _resolve_provider_uncached(preferred, deps=get_default_router_deps())


def _get_local_adapter_provider(*, deps: Optional[RouterDeps] = None) -> EmbeddingsProvider:
    from ipfs_datasets_py.utils.embedding_adapter import embed_texts as _embed_texts

    class _LocalAdapterProvider:
        def embed_texts(
            self,
            texts: Iterable[str],
            *,
            model_name: Optional[str] = None,
            device: Optional[str] = None,
            **kwargs: object,
        ) -> List[List[float]]:
            _ = kwargs
            return _embed_texts(texts, model_name=model_name, device=device, deps=deps)

    return _LocalAdapterProvider()


def _resolve_provider_uncached(preferred: Optional[str], *, deps: RouterDeps) -> EmbeddingsProvider:
    if preferred:
        info = _PROVIDER_REGISTRY.get(preferred)
        if info is not None:
            return info.factory()
        builtin = _builtin_provider_by_name(preferred, deps=deps)
        if builtin is not None:
            return builtin
        raise ValueError(f"Unknown embeddings provider: {preferred}")

    # 1) Registered providers can opt-in via env ordering if desired.
    preferred_env = os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_PROVIDER", "").strip()
    if preferred_env:
        info = _PROVIDER_REGISTRY.get(preferred_env)
        if info is not None:
            return info.factory()
        builtin = _builtin_provider_by_name(preferred_env, deps=deps)
        if builtin is not None:
            return builtin

    # 2) Optional accelerate provider.
    accelerate_provider = _get_accelerate_provider(deps)
    if accelerate_provider is not None:
        return accelerate_provider

    # Try optional providers if available.
    for name in ["openrouter", "gemini_cli"]:
        candidate = _builtin_provider_by_name(name, deps=deps)
        if candidate is not None:
            return candidate

    # 3) Local adapter fallback (Gemini CLI -> HF transformers).
    return _get_local_adapter_provider(deps=deps)


def get_embeddings_provider(
    provider: Optional[str] = None,
    *,
    deps: Optional[RouterDeps] = None,
    use_cache: Optional[bool] = None,
) -> EmbeddingsProvider:
    """Resolve an embeddings provider with optional dependency injection."""

    resolved_deps = deps or get_default_router_deps()
    cache_ok = _cache_enabled() if use_cache is None else bool(use_cache)

    if not cache_ok:
        return _resolve_provider_uncached(provider, deps=resolved_deps)

    if deps is not None:
        cache_key = _provider_cache_key()
        deps_key = _deps_provider_cache_key(provider, cache_key)
        cached = resolved_deps.get_cached(deps_key)
        if cached is not None:
            return cached
        return resolved_deps.set_cached(deps_key, _resolve_provider_uncached(provider, deps=resolved_deps))

    return _resolve_provider_cached(provider, _provider_cache_key())


def embed_texts(
    texts: Iterable[str],
    *,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    provider: Optional[str] = None,
    provider_instance: Optional[EmbeddingsProvider] = None,
    deps: Optional[RouterDeps] = None,
    **kwargs: object,
) -> List[List[float]]:
    """Generate embeddings for multiple texts."""

    resolved_deps = deps or get_default_router_deps()
    inputs = list(texts)

    if _response_cache_enabled() and inputs:
        try:
            cached_vectors: list[list[float] | None] = [None] * len(inputs)
            missing_texts: list[str] = []
            missing_indices: list[int] = []

            for idx, text in enumerate(inputs):
                cache_key = _response_cache_key(
                    provider=provider,
                    model_name=model_name,
                    device=device,
                    text=text,
                    kwargs=dict(kwargs),
                )
                getter = getattr(resolved_deps, "get_cached_or_remote", None)
                cached = getter(cache_key) if callable(getter) else resolved_deps.get_cached(cache_key)
                if isinstance(cached, list) and all(isinstance(x, (int, float)) for x in cached):
                    cached_vectors[idx] = [float(x) for x in cached]
                else:
                    missing_indices.append(idx)
                    missing_texts.append(text)

            if not missing_texts:
                return [v if v is not None else [] for v in cached_vectors]

            backend = provider_instance or get_embeddings_provider(provider, deps=resolved_deps)
            generated = backend.embed_texts(missing_texts, model_name=model_name, device=device, **kwargs)
            for out_idx, vec in enumerate(generated):
                input_idx = missing_indices[out_idx]
                cached_vectors[input_idx] = vec
                try:
                    cache_key = _response_cache_key(
                        provider=provider,
                        model_name=model_name,
                        device=device,
                        text=inputs[input_idx],
                        kwargs=dict(kwargs),
                    )
                    setter = getattr(resolved_deps, "set_cached_and_remote", None)
                    if callable(setter):
                        setter(cache_key, vec)
                    else:
                        resolved_deps.set_cached(cache_key, vec)
                except Exception:
                    pass

            return [v if v is not None else [] for v in cached_vectors]
        except Exception:
            pass

    backend = provider_instance or get_embeddings_provider(provider, deps=resolved_deps)
    try:
        result = backend.embed_texts(inputs, model_name=model_name, device=device, **kwargs)
        if _response_cache_enabled() and inputs:
            for text, vec in zip(inputs, result):
                try:
                    cache_key = _response_cache_key(
                        provider=provider,
                        model_name=model_name,
                        device=device,
                        text=text,
                        kwargs=dict(kwargs),
                    )
                    setter = getattr(resolved_deps, "set_cached_and_remote", None)
                    if callable(setter):
                        setter(cache_key, vec)
                    else:
                        resolved_deps.set_cached(cache_key, vec)
                except Exception:
                    pass
        return result
    except Exception:
        # If an optional provider fails, fall back to local adapter.
        if provider is None and backend is not _get_local_adapter_provider(deps=resolved_deps):
            result = _get_local_adapter_provider(deps=resolved_deps).embed_texts(inputs, model_name=model_name, device=device)
            if _response_cache_enabled() and inputs:
                for text, vec in zip(inputs, result):
                    try:
                        cache_key = _response_cache_key(
                            provider=provider,
                            model_name=model_name,
                            device=device,
                            text=text,
                            kwargs=dict(kwargs),
                        )
                        setter = getattr(resolved_deps, "set_cached_and_remote", None)
                        if callable(setter):
                            setter(cache_key, vec)
                        else:
                            resolved_deps.set_cached(cache_key, vec)
                    except Exception:
                        pass
            return result
        raise


def clear_embeddings_router_caches() -> None:
    _resolve_provider_cached.cache_clear()


def embed_text(
    text: str,
    *,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    provider: Optional[str] = None,
    **kwargs: object,
) -> List[float]:
    """Generate an embedding for a single text."""

    return embed_texts([text], model_name=model_name, device=device, provider=provider, **kwargs)[0]
