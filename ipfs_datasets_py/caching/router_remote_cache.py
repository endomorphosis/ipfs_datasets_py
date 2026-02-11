from __future__ import annotations

import inspect
import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

import anyio
import sniffio

from ipfs_datasets_py.ipfs_backend_router import get_ipfs_backend
from ipfs_datasets_py.router_deps import RouterDeps


def _p2p_cache_enabled() -> bool:
    return _truthy(os.environ.get("IPFS_DATASETS_PY_REMOTE_CACHE_P2P_TASKS"))


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def canonical_json_bytes(obj: Any) -> bytes:
    """Deterministically serialize an object to JSON bytes.

    This is intentionally resilient (uses `default=repr`) so router kwargs or
    provider outputs that contain non-JSON types won't crash caching.
    """

    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=repr,
    ).encode("utf-8")


def _run_async_from_sync(async_fn, *args, **kwargs):
    """Run an async callable from sync code.

    - If called from an AnyIO worker thread, uses `anyio.from_thread.run`.
    - If called from plain sync code, uses `anyio.run`.
    - If called while an async library is running in this thread, runs the
      call in a dedicated helper thread.
    """

    try:
        lib = sniffio.current_async_library()
    except Exception:
        lib = None

    if lib is None:
        return anyio.run(async_fn, *args, **kwargs)

    # If we're already in AnyIO context, use from_thread.
    if lib == "anyio":
        try:
            return anyio.from_thread.run(async_fn, *args, **kwargs)
        except Exception:
            pass

    result: list[Any] = []
    error: list[BaseException] = []

    def _thread_main() -> None:
        try:
            result.append(anyio.run(async_fn, *args, **kwargs))
        except BaseException as exc:  # pragma: no cover
            error.append(exc)

    t = threading.Thread(target=_thread_main, daemon=True)
    t.start()
    t.join()
    if error:
        raise error[0]
    return result[0] if result else None


def maybe_start_mapping_cache_networking(mapping_cache: Any, *, enabled: bool | None = None) -> bool:
    """Start mapping-cache networking if supported and enabled.

    This is intentionally best-effort and opt-in to keep tests/benchmarks stable.

    Enable via:
    - `enabled=True`, or
    - env `IPFS_DATASETS_PY_REMOTE_CACHE_NETWORK=1`
    """

    if mapping_cache is None:
        return False

    if enabled is None:
        enabled = _truthy(os.environ.get("IPFS_DATASETS_PY_REMOTE_CACHE_NETWORK"))
    if not enabled:
        return False

    starter = getattr(mapping_cache, "start", None)
    if not callable(starter):
        return False

    try:
        res = starter()
    except Exception:
        return False

    if inspect.isawaitable(res):
        async def _await_it(awaitable):
            return await awaitable

        try:
            _run_async_from_sync(_await_it, res)
        except Exception:
            return False
    return True


def maybe_stop_mapping_cache_networking(mapping_cache: Any) -> bool:
    """Stop mapping-cache networking if supported (best-effort)."""

    if mapping_cache is None:
        return False
    stopper = getattr(mapping_cache, "stop", None)
    if not callable(stopper):
        return False

    try:
        res = stopper()
    except Exception:
        return False

    if inspect.isawaitable(res):
        async def _await_it(awaitable):
            return await awaitable

        try:
            _run_async_from_sync(_await_it, res)
        except Exception:
            return False
    return True


class IPFSBackedRemoteCache:
    """A RouterDeps-compatible remote cache backed by IPFS + a mapping cache.

    This implements a simple, distributed-friendly pattern:

    - Cache key: the router cache key (often a request-derived CID string)
    - Mapping cache value: a small JSON-serializable dict like
      `{ "value_cid": "...", "encoding": "json" }`
    - Actual cached payload: stored in IPFS (Kubo / httpapi / ipfs_kit_py),
      retrievable by `value_cid`.

    Why the mapping exists
    ----------------------
    If the key is a CID derived from the *request*, it cannot also be the CID
    of the *response bytes* (IPFS CIDs are content hashes). So we store the
    response under its own CID and store a small "pointer" record under the
    request-key in a mapping cache.

    The mapping cache can be:
    - local-only (dict-like)
    - distributed (e.g. `DistributedGitHubCache`) to gossip pointers across peers
    """

    def __init__(
        self,
        *,
        mapping_cache: Any,
        deps: RouterDeps | None = None,
        ipfs_backend=None,
        pin: bool = False,
        ttl_seconds: int | None = None,
        broadcast: bool = True,
    ) -> None:
        self.mapping_cache = mapping_cache
        self.deps = deps
        self.ipfs_backend = ipfs_backend
        self.pin = bool(pin)
        self.ttl_seconds = ttl_seconds
        self.broadcast = bool(broadcast)

    def _get_ipfs(self):
        if self.ipfs_backend is not None:
            return self.ipfs_backend
        # Respect a backend cached on deps.
        if self.deps is not None and getattr(self.deps, "ipfs_backend", None) is not None:
            return self.deps.ipfs_backend
        return get_ipfs_backend(deps=self.deps)

    def _mapping_get(self, key: str) -> Any | None:
        getter = getattr(self.mapping_cache, "get", None)
        if not callable(getter):
            return None
        try:
            return getter(key)
        except Exception:
            return None

    def _mapping_set(self, key: str, value: Any) -> None:
        setter = getattr(self.mapping_cache, "set", None)
        if not callable(setter):
            return

        try:
            res = setter(
                key,
                value,
                ttl=self.ttl_seconds,
                broadcast=self.broadcast,
            )
        except TypeError:
            # Fallback for mapping caches that only accept (key, value).
            res = setter(key, value)
        except Exception:
            return

        if inspect.isawaitable(res):
            async def _await_it(awaitable):
                return await awaitable

            try:
                _run_async_from_sync(_await_it, res)
            except Exception:
                return

    def get(self, key: str) -> Any | None:
        if not key:
            return None

        mapping = self._mapping_get(key)
        if not isinstance(mapping, dict):
            return None

        value_cid = mapping.get("value_cid") or mapping.get("cid")
        if not value_cid:
            return None

        try:
            raw = self._get_ipfs().cat(str(value_cid))
        except Exception:
            return None

        encoding = str(mapping.get("encoding") or "json")
        if encoding != "json":
            return None

        try:
            text = raw.decode("utf-8", errors="strict")
            return json.loads(text)
        except Exception:
            return None

    def set(self, key: str, value: Any) -> Any:
        if not key:
            return value

        # Serialize payload deterministically.
        payload = canonical_json_bytes(value)

        try:
            value_cid = self._get_ipfs().add_bytes(payload, pin=self.pin)
        except Exception:
            # If IPFS isn't available, don't fail the router call.
            return value

        mapping = {"value_cid": str(value_cid), "encoding": "json"}
        self._mapping_set(key, mapping)
        return value


class P2PTaskRemoteCache:
    """A RouterDeps-compatible remote cache backed by accelerate's libp2p task service.

    This is a simple JSON key/value cache accessed over libp2p RPC ops:
    - cache.get
    - cache.set

    It is best-effort and safe to use in CI/minimal contexts.
    """

    def __init__(
        self,
        *,
        remote_peer_id: str = "",
        remote_multiaddr: str = "",
        timeout_s: float = 10.0,
        default_ttl_s: float | None = None,
    ) -> None:
        self.remote_peer_id = str(remote_peer_id or "").strip()
        self.remote_multiaddr = str(remote_multiaddr or "").strip()
        self.timeout_s = float(timeout_s)
        self.default_ttl_s = float(default_ttl_s) if default_ttl_s is not None else None

    def _remote(self):
        from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import RemoteQueue

        return RemoteQueue(peer_id=self.remote_peer_id, multiaddr=self.remote_multiaddr)

    def get(self, key: str) -> Any | None:
        if not key:
            return None
        try:
            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import cache_get_sync

            resp = cache_get_sync(remote=self._remote(), key=str(key), timeout_s=float(self.timeout_s))
            if not isinstance(resp, dict) or not resp.get("ok"):
                return None
            if not resp.get("hit"):
                return None
            return resp.get("value")
        except Exception:
            return None

    def set(self, key: str, value: Any) -> Any:
        if not key:
            return value
        try:
            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import cache_set_sync

            cache_set_sync(
                remote=self._remote(),
                key=str(key),
                value=value,
                ttl_s=self.default_ttl_s,
                timeout_s=float(self.timeout_s),
            )
        except Exception:
            pass
        return value


class DistributedMappingCache:
    """Small adapter around DistributedGitHubCache for use as a mapping cache.

    - Provides a sync `get(key)`.
    - Provides an async-friendly `set(key, value, ttl=..., broadcast=...)`.

    Note: the underlying distributed cache only becomes truly peer-to-peer after
    you start it (async `start()`), which is intentionally opt-in.
    """

    def __init__(self, cache, *, default_ttl: int | None = None, broadcast: bool = True) -> None:
        self._cache = cache
        self._default_ttl = default_ttl
        self._broadcast = bool(broadcast)

    def get(self, key: str) -> Any | None:
        return self._cache.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None, broadcast: bool = True) -> Any:
        ttl_value = int(ttl) if ttl is not None else self._default_ttl
        return await self._cache.set(key, value, ttl=ttl_value, broadcast=bool(broadcast) and self._broadcast)

    async def start(self) -> None:
        starter = getattr(self._cache, "start", None)
        if callable(starter):
            await starter()

    async def stop(self) -> None:
        stopper = getattr(self._cache, "stop", None)
        if callable(stopper):
            await stopper()


def make_distributed_mapping_cache(
    *,
    deps: RouterDeps | None = None,
    cache_dir: str | Path | None = None,
    listen_port: int | None = None,
    bootstrap_peers: list[str] | None = None,
    default_ttl: int = 24 * 3600,
    broadcast: bool = True,
):
    """Create a DistributedGitHubCache-backed mapping cache.

    This is a pragmatic default pointer-store for remote router caches:
    it works local-only without starting networking, and can be upgraded to a
    gossip cache by calling `await mapping_cache.start()`.
    """

    from ipfs_datasets_py.caching.distributed_cache import DistributedGitHubCache

    resolved_dir = Path(cache_dir) if cache_dir is not None else None
    resolved_port = int(listen_port) if listen_port is not None else int(os.getenv("IPFS_DATASETS_PY_REMOTE_CACHE_PORT", "9000"))
    resolved_bootstrap = bootstrap_peers
    if resolved_bootstrap is None:
        env_peers = os.getenv("IPFS_DATASETS_PY_REMOTE_CACHE_BOOTSTRAP", "").strip()
        resolved_bootstrap = [p for p in env_peers.split(",") if p.strip()] if env_peers else []

    cache = DistributedGitHubCache(
        cache_dir=resolved_dir,
        listen_port=resolved_port,
        bootstrap_peers=resolved_bootstrap,
        default_ttl=int(default_ttl),
        deps=deps,
    )
    mapping_cache = DistributedMappingCache(cache, default_ttl=int(default_ttl), broadcast=broadcast)
    maybe_start_mapping_cache_networking(mapping_cache)
    return mapping_cache


def make_ipfs_remote_cache(
    *,
    deps: RouterDeps | None = None,
    mapping_cache: Any | None = None,
    ipfs_backend=None,
    pin: bool = False,
    ttl_seconds: int | None = None,
    broadcast: bool = True,
) -> IPFSBackedRemoteCache:
    """Create an IPFS-backed remote cache with a sensible default mapping cache.

    If `mapping_cache` is not provided, this uses a `DistributedGitHubCache`-backed
    mapping cache (local-only unless started).
    """

    if mapping_cache is None:
        mapping_cache = make_distributed_mapping_cache(
            deps=deps,
            default_ttl=int(ttl_seconds) if ttl_seconds is not None else 24 * 3600,
            broadcast=broadcast,
        )
    else:
        # If the caller provides a mapping cache, still allow env-gated startup.
        maybe_start_mapping_cache_networking(mapping_cache)
    return IPFSBackedRemoteCache(
        mapping_cache=mapping_cache,
        deps=deps,
        ipfs_backend=ipfs_backend,
        pin=pin,
        ttl_seconds=ttl_seconds,
        broadcast=broadcast,
    )


def make_p2p_task_remote_cache(
    *,
    timeout_s: float = 10.0,
    default_ttl_s: float | None = None,
) -> P2PTaskRemoteCache | None:
    """Create a libp2p task-service-backed remote cache (env-configured).

    Uses the same remote peer env vars as `llm_router`:
    - IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR / IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_MULTIADDR
    - IPFS_DATASETS_PY_TASK_P2P_REMOTE_PEER_ID / IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_PEER_ID

    Opt-in via `IPFS_DATASETS_PY_REMOTE_CACHE_P2P_TASKS=1`.
    """

    if not _p2p_cache_enabled():
        return None

    remote_peer_id = (
        os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_PEER_ID")
        or os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_PEER_ID")
        or ""
    ).strip()
    remote_multiaddr = (
        os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR")
        or os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_MULTIADDR")
        or ""
    ).strip()

    if not remote_peer_id and not remote_multiaddr:
        return None

    return P2PTaskRemoteCache(
        remote_peer_id=remote_peer_id,
        remote_multiaddr=remote_multiaddr,
        timeout_s=float(timeout_s),
        default_ttl_s=default_ttl_s,
    )
