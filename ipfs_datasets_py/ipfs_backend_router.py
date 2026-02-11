"""IPFS backend router.

This module provides a stable entrypoint for basic IPFS operations with a
pluggable backend strategy:
- Optional providers (ipfs_accelerate_py, ipfs_kit_py) when explicitly enabled.
- Default fallback to local Kubo via the `ipfs` CLI.

Design goals:
- Avoid importing ipfs_kit_py at module import time.
- Keep behavior predictable in benchmarks/CI.

Environment variables:
- `IPFS_DATASETS_PY_IPFS_BACKEND`: force backend name (registered provider)
- `IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE`: enable ipfs_accelerate_py backend (best-effort)
- `IPFS_DATASETS_PY_ENABLE_IPFS_KIT`: enable ipfs_kit_py backend (best-effort)
- `IPFS_DATASETS_PY_KUBO_CMD`: override ipfs CLI command (default: "ipfs")
"""

from __future__ import annotations

import os
import importlib
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Dict, Optional, Protocol, runtime_checkable

from .router_deps import RouterDeps, get_default_router_deps


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _cache_enabled() -> bool:
    return os.environ.get("IPFS_DATASETS_PY_ROUTER_CACHE", "1").strip() != "0"


_DEFAULT_BACKEND_OVERRIDE: IPFSBackend | None = None


def set_default_ipfs_backend(backend: IPFSBackend | None) -> None:
    """Inject a process-global backend instance.

    If set, all router calls will use this backend unless an explicit backend
    is passed at call time.
    """

    global _DEFAULT_BACKEND_OVERRIDE
    _DEFAULT_BACKEND_OVERRIDE = backend


def _backend_cache_key() -> tuple:
    return (
        os.getenv("IPFS_DATASETS_PY_IPFS_BACKEND", "").strip(),
        os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_KIT", "").strip(),
        os.getenv("IPFS_KIT_DISABLE", "").strip(),
        os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_HTTPAPI", "").strip(),
        os.getenv("IPFS_HOST", "").strip(),
        os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE", "").strip(),
        os.getenv("IPFS_DATASETS_PY_KUBO_CMD", "").strip(),
        os.getenv("IPFS_DATASETS_PY_IPFS_CACHE_DIR", "").strip(),
    )


@runtime_checkable
class IPFSBackend(Protocol):
    def add_bytes(self, data: bytes, *, pin: bool = True) -> str: ...

    def cat(self, cid: str) -> bytes: ...

    def pin(self, cid: str) -> None: ...

    def unpin(self, cid: str) -> None: ...

    def block_put(self, data: bytes, *, codec: str = "raw") -> str: ...

    def block_get(self, cid: str) -> bytes: ...

    def add_path(
        self,
        path: str,
        *,
        recursive: bool = True,
        pin: bool = True,
        chunker: Optional[str] = None,
    ) -> str: ...

    def get_to_path(self, cid: str, *, output_path: str) -> None: ...

    def ls(self, cid: str) -> list[str]: ...

    def dag_export(self, cid: str) -> bytes: ...


ProviderFactory = Callable[[], IPFSBackend]


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    factory: ProviderFactory


_PROVIDER_REGISTRY: Dict[str, ProviderInfo] = {}


def register_ipfs_backend(name: str, factory: ProviderFactory) -> None:
    if not name or not name.strip():
        raise ValueError("Backend name must be non-empty")
    _PROVIDER_REGISTRY[name] = ProviderInfo(name=name, factory=factory)


class KuboCLIBackend:
    def __init__(self, cmd: Optional[str] = None) -> None:
        self._cmd = cmd or os.getenv("IPFS_DATASETS_PY_KUBO_CMD", "ipfs")

    def _run(self, args: list[str], *, input_bytes: Optional[bytes] = None) -> bytes:
        proc = subprocess.run(
            [self._cmd, *args],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            msg = proc.stderr.decode("utf-8", errors="replace").strip() or "ipfs command failed"
            raise RuntimeError(msg)
        return proc.stdout

    def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
        pin_flag = "true" if pin else "false"
        # `ipfs add` can read from stdin.
        # Kubo treats `--pin` as a boolean flag; pass as `--pin=true/false`.
        out = self._run(["add", "-Q", f"--pin={pin_flag}", "--stdin-name", "data.bin"], input_bytes=data)
        return out.decode("utf-8", errors="replace").strip()

    def cat(self, cid: str) -> bytes:
        return self._run(["cat", cid])

    def pin(self, cid: str) -> None:
        self._run(["pin", "add", cid])

    def unpin(self, cid: str) -> None:
        self._run(["pin", "rm", cid])

    def block_put(self, data: bytes, *, codec: str = "raw") -> str:
        # `ipfs block put` reads from a file.
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(data)
            handle.flush()
            try:
                out = self._run(["block", "put", "--cid-version", "1", "--format", str(codec), handle.name])
            except RuntimeError as e:
                # Some IPFS CLIs don't support these flags; retry with a minimal invocation.
                msg = str(e)
                if "unknown option" in msg or "flag provided but not defined" in msg:
                    out = self._run(["block", "put", "--format", str(codec), handle.name])
                else:
                    raise
        return out.decode("utf-8", errors="replace").strip()

    def block_get(self, cid: str) -> bytes:
        return self._run(["block", "get", cid])

    def add_path(
        self,
        path: str,
        *,
        recursive: bool = True,
        pin: bool = True,
        chunker: Optional[str] = None,
    ) -> str:
        pin_flag = "true" if pin else "false"
        args: list[str] = ["add", "-Q", f"--pin={pin_flag}"]
        if recursive:
            args.append("-r")
        if chunker:
            args.extend(["--chunker", str(chunker)])
        args.append(path)
        out = self._run(args)
        return out.decode("utf-8", errors="replace").strip()

    def get_to_path(self, cid: str, *, output_path: str) -> None:
        self._run(["get", cid, "-o", output_path])

    def ls(self, cid: str) -> list[str]:
        out = self._run(["ls", cid]).decode("utf-8", errors="replace")
        names: list[str] = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            # Expected: <hash> <size> <name>
            parts = line.split()
            if len(parts) >= 3:
                names.append(" ".join(parts[2:]))
        return names

    def dag_export(self, cid: str) -> bytes:
        return self._run(["dag", "export", cid])

    # ---- Optional: IPNS + pubsub (best-effort) ----

    def name_publish(self, cid: str, *, key: Optional[str] = None, allow_offline: bool = True) -> str:
        args: list[str] = ["name", "publish"]
        if allow_offline:
            args.append("--allow-offline")
        if key:
            args.extend(["--key", str(key)])
        args.append(f"/ipfs/{cid}")
        out = self._run(args)
        return out.decode("utf-8", errors="replace").strip()

    def name_resolve(self, name: str, *, timeout_s: float = 10.0) -> str:
        # Kubo expects durations like "10s".
        timeout_s = float(timeout_s)
        out = self._run(["name", "resolve", f"--timeout={timeout_s:.3f}s", str(name)])
        return out.decode("utf-8", errors="replace").strip()

    def pubsub_pub(self, topic: str, data: str) -> None:
        _ = self._run(["pubsub", "pub", str(topic), str(data)])

    def pubsub_sub_process(self, topic: str) -> subprocess.Popen:
        return subprocess.Popen(
            [self._cmd, "pubsub", "sub", str(topic)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


def _get_httpapi_backend() -> Optional[IPFSBackend]:
    if not _truthy(os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_HTTPAPI")):
        return None

    try:
        import ipfshttpclient

        ipfs_host = os.environ.get("IPFS_HOST", "/ip4/127.0.0.1/tcp/5001")
        client = ipfshttpclient.connect(ipfs_host)

        class _HTTPAPIBackend:
            def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
                cid = client.add_bytes(data)
                if pin:
                    client.pin.add(cid)
                return str(cid)

            def cat(self, cid: str) -> bytes:
                out = client.cat(cid)
                return out if isinstance(out, (bytes, bytearray)) else bytes(out)

            def pin(self, cid: str) -> None:
                client.pin.add(cid)

            def unpin(self, cid: str) -> None:
                client.pin.rm(cid)

            def block_put(self, data: bytes, *, codec: str = "raw") -> str:
                # ipfshttpclient expects `format`.
                res = client.block.put(data, format=str(codec))
                return str(res.get("Key") or res.get("Cid") or res.get("Hash"))

            def block_get(self, cid: str) -> bytes:
                out = client.block.get(cid)
                return out if isinstance(out, (bytes, bytearray)) else bytes(out)

            def add_path(
                self,
                path: str,
                *,
                recursive: bool = True,
                pin: bool = True,
                chunker: Optional[str] = None,
            ) -> str:
                kwargs: dict = {"recursive": bool(recursive), "pin": bool(pin)}
                if chunker:
                    kwargs["chunker"] = str(chunker)
                res = client.add(path, **kwargs)
                if isinstance(res, list):
                    last = res[-1] if res else {}
                    return str(last.get("Hash") or last.get("Cid") or last.get("Key"))
                if isinstance(res, dict):
                    return str(res.get("Hash") or res.get("Cid") or res.get("Key"))
                return str(res)

            def get_to_path(self, cid: str, *, output_path: str) -> None:
                # ipfshttpclient writes into a target directory; emulate ipfs get -o by choosing parent.
                import os

                target_dir = os.path.dirname(output_path) or "."
                client.get(cid, target=target_dir)

            def ls(self, cid: str) -> list[str]:
                listing = client.ls(cid)
                if not isinstance(listing, dict):
                    return []
                objs = listing.get("Objects") or []
                if not objs:
                    return []
                links = objs[0].get("Links") or []
                names: list[str] = []
                for link in links:
                    name = link.get("Name")
                    if name:
                        names.append(str(name))
                return names

            def dag_export(self, cid: str) -> bytes:
                return client.dag.export(cid)

            # Optional: IPNS + pubsub (best-effort)

            def name_publish(self, cid: str, *, key: Optional[str] = None, allow_offline: bool = True) -> str:
                kwargs: dict = {"allow_offline": bool(allow_offline)}
                if key:
                    kwargs["key"] = str(key)
                res = client.name.publish(f"/ipfs/{cid}", **kwargs)
                if isinstance(res, dict):
                    return str(res.get("Name") or res.get("name") or res)
                return str(res)

            def name_resolve(self, name: str, *, timeout_s: float = 10.0) -> str:
                _ = timeout_s
                res = client.name.resolve(str(name))
                if isinstance(res, dict):
                    return str(res.get("Path") or res.get("path") or res)
                return str(res)

            def pubsub_pub(self, topic: str, data: str) -> None:
                client.pubsub.pub(str(topic), str(data))

            def pubsub_sub_process(self, topic: str):
                # ipfshttpclient returns an iterator-like subscription in some versions.
                return client.pubsub.sub(str(topic))

        return _HTTPAPIBackend()
    except Exception:
        return None


def _get_accelerate_backend() -> Optional[IPFSBackend]:
    if not _truthy(os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE")):
        return None

    try:
        module = importlib.import_module("ipfs_accelerate_py.datasets_integration.filesystem")
        FilesystemHandler = getattr(module, "FilesystemHandler")

        handler = FilesystemHandler(cache_dir=os.getenv("IPFS_DATASETS_PY_IPFS_CACHE_DIR"))

        class _AccelerateBackend:
            def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
                with tempfile.NamedTemporaryFile(delete=False) as handle:
                    handle.write(data)
                    handle.flush()
                    cid = handler.add_file(handle.name, pin=pin)
                if cid:
                    return str(cid)
                # ipfs_accelerate_py FilesystemHandler returns None when IPFS is
                # unavailable and it falls back to local caching.
                # In that case, return a deterministic simulated CID so callers
                # can still proceed in local/CI environments.
                import hashlib

                return f"Qm{hashlib.sha256(data).hexdigest()[:44]}"

            def cat(self, cid: str) -> bytes:
                data = handler.cat(cid)
                if data is None:
                    raise RuntimeError("ipfs_accelerate_py could not cat CID")
                return data

            def pin(self, cid: str) -> None:
                ok = handler.pin(cid)
                if not ok:
                    raise RuntimeError("ipfs_accelerate_py could not pin CID")

            def unpin(self, cid: str) -> None:
                if hasattr(handler, "unpin"):
                    ok = handler.unpin(cid)
                    if not ok:
                        raise RuntimeError("ipfs_accelerate_py could not unpin CID")
                    return
                raise RuntimeError("ipfs_accelerate_py unpin not available")

            def block_put(self, data: bytes, *, codec: str = "raw") -> str:
                _ = codec
                raise RuntimeError("ipfs_accelerate_py block_put not available")

            def block_get(self, cid: str) -> bytes:
                raise RuntimeError("ipfs_accelerate_py block_get not available")

            def add_path(
                self,
                path: str,
                *,
                recursive: bool = True,
                pin: bool = True,
                chunker: Optional[str] = None,
            ) -> str:
                _ = (path, recursive, pin, chunker)
                raise RuntimeError("ipfs_accelerate_py add_path not available")

            def get_to_path(self, cid: str, *, output_path: str) -> None:
                _ = (cid, output_path)
                raise RuntimeError("ipfs_accelerate_py get_to_path not available")

            def ls(self, cid: str) -> list[str]:
                _ = cid
                raise RuntimeError("ipfs_accelerate_py ls not available")

            def dag_export(self, cid: str) -> bytes:
                _ = cid
                raise RuntimeError("ipfs_accelerate_py dag_export not available")

        return _AccelerateBackend()
    except Exception:
        return None


def _get_ipfs_kit_backend() -> Optional[IPFSBackend]:
    if not _truthy(os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_KIT")):
        return None
    if _truthy(os.getenv("IPFS_KIT_DISABLE")):
        return None

    try:
        # This import is intentionally delayed and opt-in.
        from ipfs_kit_py.ipfs_kit import ipfs_kit as ipfs_kit_factory

        # Reuse a previously created kit instance when available.
        deps = get_default_router_deps()
        kit = None
        try:
            kit = deps.get_cached("ipfs_kit_py::kit_instance")
        except Exception:
            kit = None
        if kit is None:
            kit = ipfs_kit_factory(resources={"deps": deps}, metadata={"deps": deps})
            try:
                deps.set_cached("ipfs_kit_py::kit_instance", kit)
            except Exception:
                pass

        class _IPFSKitBackend:
            def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
                # Best-effort: ipfs_kit APIs vary; support common method names.
                if hasattr(kit, "add_content"):
                    result = kit.add_content(data, pin=pin)
                elif hasattr(kit, "add_bytes"):
                    result = kit.add_bytes(data, pin=pin)
                else:
                    # Fallback: write a temp file and add.
                    with tempfile.NamedTemporaryFile(delete=False) as handle:
                        handle.write(data)
                        handle.flush()
                        result = kit.add_file(handle.name, pin=pin)
                if isinstance(result, dict):
                    cid = result.get("cid") or result.get("Hash")
                    if cid:
                        return str(cid)
                if isinstance(result, str) and result:
                    return result
                raise RuntimeError("ipfs_kit_py did not return a CID")

            def cat(self, cid: str) -> bytes:
                if hasattr(kit, "cat"):
                    out = kit.cat(cid)
                elif hasattr(kit, "cat_file"):
                    out = kit.cat_file(cid)
                else:
                    out = None
                if isinstance(out, bytes):
                    return out
                if isinstance(out, str):
                    return out.encode("utf-8")
                if isinstance(out, dict) and "data" in out:
                    data = out["data"]
                    if isinstance(data, bytes):
                        return data
                    if isinstance(data, str):
                        return data.encode("utf-8")
                raise RuntimeError("ipfs_kit_py could not cat CID")

            def pin(self, cid: str) -> None:
                if hasattr(kit, "pin"):
                    kit.pin(cid)
                    return
                raise RuntimeError("ipfs_kit_py pin not available")

            def unpin(self, cid: str) -> None:
                if hasattr(kit, "unpin"):
                    kit.unpin(cid)
                    return
                if hasattr(kit, "pin_rm"):
                    kit.pin_rm(cid)
                    return
                raise RuntimeError("ipfs_kit_py unpin not available")

            def block_put(self, data: bytes, *, codec: str = "raw") -> str:
                if hasattr(kit, "block_put"):
                    return str(kit.block_put(data, codec=codec))
                raise RuntimeError("ipfs_kit_py block_put not available")

            def block_get(self, cid: str) -> bytes:
                if hasattr(kit, "block_get"):
                    out = kit.block_get(cid)
                    return out if isinstance(out, bytes) else bytes(out)
                raise RuntimeError("ipfs_kit_py block_get not available")

            def add_path(
                self,
                path: str,
                *,
                recursive: bool = True,
                pin: bool = True,
                chunker: Optional[str] = None,
            ) -> str:
                _ = (recursive, chunker)
                if hasattr(kit, "add_file") and os.path.isfile(path):
                    res = kit.add_file(path, pin=pin)
                elif hasattr(kit, "add_directory") and os.path.isdir(path):
                    res = kit.add_directory(path, pin=pin)
                else:
                    raise RuntimeError("ipfs_kit_py add_path not available")
                return str(res.get("cid") or res.get("Hash") or res)

            def get_to_path(self, cid: str, *, output_path: str) -> None:
                _ = (cid, output_path)
                raise RuntimeError("ipfs_kit_py get_to_path not available")

            def ls(self, cid: str) -> list[str]:
                _ = cid
                raise RuntimeError("ipfs_kit_py ls not available")

            def dag_export(self, cid: str) -> bytes:
                _ = cid
                raise RuntimeError("ipfs_kit_py dag_export not available")

        return _IPFSKitBackend()
    except Exception:
        return None


def _resolve_backend(preferred: Optional[str] = None) -> IPFSBackend:
    # Allow explicit injection.
    if _DEFAULT_BACKEND_OVERRIDE is not None and not preferred:
        return _DEFAULT_BACKEND_OVERRIDE

    if preferred:
        info = _PROVIDER_REGISTRY.get(preferred)
        if info is None:
            raise ValueError(f"Unknown IPFS backend: {preferred}")
        return info.factory()

    forced = os.getenv("IPFS_DATASETS_PY_IPFS_BACKEND", "").strip()
    if forced:
        info = _PROVIDER_REGISTRY.get(forced)
        if info is None:
            raise ValueError(f"Unknown IPFS backend: {forced}")
        return info.factory()

    kit = _get_ipfs_kit_backend()
    if kit is not None:
        return kit

    httpapi = _get_httpapi_backend()
    if httpapi is not None:
        return httpapi

    accel = _get_accelerate_backend()
    if accel is not None:
        return accel

    return KuboCLIBackend()


@lru_cache(maxsize=16)
def _resolve_backend_cached(preferred: Optional[str], cache_key: tuple) -> IPFSBackend:
    _ = cache_key
    return _resolve_backend(preferred)


def get_ipfs_backend(
    preferred: Optional[str] = None,
    *,
    deps: Optional[RouterDeps] = None,
    use_cache: Optional[bool] = None,
) -> IPFSBackend:
    """Resolve an IPFS backend.

    ``deps`` can be used to inject/share a backend instance across routers.
    """

    # Allow tests/hosts to inject a process-global backend instance.
    # This must take precedence over cached resolution, but should not
    # override explicit backend selection.
    if preferred is None and _DEFAULT_BACKEND_OVERRIDE is not None:
        if deps is not None and getattr(deps, "ipfs_backend", None) is None:
            deps.ipfs_backend = _DEFAULT_BACKEND_OVERRIDE
        return _DEFAULT_BACKEND_OVERRIDE

    if deps is not None and getattr(deps, "ipfs_backend", None) is not None and preferred is None:
        return deps.ipfs_backend
    if deps is None:
        deps = get_default_router_deps()
        if getattr(deps, "ipfs_backend", None) is not None and preferred is None:
            return deps.ipfs_backend

    cache_ok = _cache_enabled() if use_cache is None else bool(use_cache)
    if cache_ok:
        backend = _resolve_backend_cached(preferred, _backend_cache_key())
    else:
        backend = _resolve_backend(preferred)

    # Store on deps for reuse if this is the default resolution.
    if deps is not None and preferred is None and getattr(deps, "ipfs_backend", None) is None:
        deps.ipfs_backend = backend
    return backend


def add_bytes(
    data: bytes,
    *,
    pin: bool = True,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> str:
    return (backend_instance or get_ipfs_backend(backend, deps=deps)).add_bytes(data, pin=pin)


def cat(
    cid: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> bytes:
    return (backend_instance or get_ipfs_backend(backend, deps=deps)).cat(cid)


def pin(
    cid: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> None:
    return (backend_instance or get_ipfs_backend(backend, deps=deps)).pin(cid)


def unpin(
    cid: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> None:
    return (backend_instance or get_ipfs_backend(backend, deps=deps)).unpin(cid)


def block_put(
    data: bytes,
    *,
    codec: str = "raw",
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> str:
    return (backend_instance or get_ipfs_backend(backend, deps=deps)).block_put(data, codec=codec)


def block_get(
    cid: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> bytes:
    return (backend_instance or get_ipfs_backend(backend, deps=deps)).block_get(cid)


def add_path(
    path: str,
    *,
    recursive: bool = True,
    pin: bool = True,
    chunker: Optional[str] = None,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> str:
    return (backend_instance or get_ipfs_backend(backend, deps=deps)).add_path(
        path, recursive=recursive, pin=pin, chunker=chunker
    )


def get_to_path(
    cid: str,
    *,
    output_path: str,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> None:
    return (backend_instance or get_ipfs_backend(backend, deps=deps)).get_to_path(cid, output_path=output_path)


def ls(
    cid: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> list[str]:
    return (backend_instance or get_ipfs_backend(backend, deps=deps)).ls(cid)


def dag_export(
    cid: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> bytes:
    return (backend_instance or get_ipfs_backend(backend, deps=deps)).dag_export(cid)


def clear_ipfs_backend_router_caches() -> None:
    _resolve_backend_cached.cache_clear()


def name_publish(
    cid: str,
    *,
    key: Optional[str] = None,
    allow_offline: bool = True,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> str:
    b = backend_instance or get_ipfs_backend(backend, deps=deps)
    fn = getattr(b, "name_publish", None)
    if callable(fn):
        return str(fn(cid, key=key, allow_offline=allow_offline))

    # Fallback: attempt using local Kubo CLI even if the chosen backend lacks IPNS.
    cmd = os.getenv("IPFS_DATASETS_PY_KUBO_CMD", "ipfs")
    args: list[str] = [cmd, "name", "publish"]
    if allow_offline:
        args.append("--allow-offline")
    if key:
        args.extend(["--key", str(key)])
    args.append(f"/ipfs/{cid}")
    out = subprocess.check_output(args, stderr=subprocess.STDOUT)
    return out.decode("utf-8", errors="replace").strip()


def name_resolve(
    name: str,
    *,
    timeout_s: float = 10.0,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> str:
    b = backend_instance or get_ipfs_backend(backend, deps=deps)
    fn = getattr(b, "name_resolve", None)
    if callable(fn):
        return str(fn(name, timeout_s=timeout_s))

    cmd = os.getenv("IPFS_DATASETS_PY_KUBO_CMD", "ipfs")
    out = subprocess.check_output(
        [cmd, "name", "resolve", f"--timeout={float(timeout_s):.3f}s", str(name)],
        stderr=subprocess.STDOUT,
    )
    return out.decode("utf-8", errors="replace").strip()


def pubsub_pub(
    topic: str,
    data: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
) -> None:
    b = backend_instance or get_ipfs_backend(backend, deps=deps)
    fn = getattr(b, "pubsub_pub", None)
    if callable(fn):
        fn(topic, data)
        return

    cmd = os.getenv("IPFS_DATASETS_PY_KUBO_CMD", "ipfs")
    subprocess.check_output([cmd, "pubsub", "pub", str(topic), str(data)], stderr=subprocess.STDOUT)


def pubsub_sub_process(
    topic: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[IPFSBackend] = None,
    deps: Optional[RouterDeps] = None,
):
    b = backend_instance or get_ipfs_backend(backend, deps=deps)
    fn = getattr(b, "pubsub_sub_process", None)
    if callable(fn):
        return fn(topic)
    cmd = os.getenv("IPFS_DATASETS_PY_KUBO_CMD", "ipfs")
    return subprocess.Popen(
        [cmd, "pubsub", "sub", str(topic)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
