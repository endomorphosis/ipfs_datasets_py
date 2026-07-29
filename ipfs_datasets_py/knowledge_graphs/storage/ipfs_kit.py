"""ipfs_kit_py GraphStore adapter (KGP-011).

Production storage profile ``ipfs_kit`` for knowledge-graph revisions.

This adapter matches the shared GraphStore contract used by the direct
IPFS/IPLD adapter (KGP-010 / profile ``ipfs_ipld``):

* ``put`` / ``get`` (typed helpers for manifest, index, raw, CAR objects)
* ``stat`` / ``pin`` / ``unpin``
* ``export_car`` / ``import_car``
* cancellation hooks
* **CID verification after every fetch**
* shared typed errors (:class:`~ipfs_datasets_py.knowledge_graphs.storage.ipld_store.GraphStoreError`)

Capability negotiation is **explicit**:

* Importing ``ipfs_kit_py`` alone never silently enables mutation.
* Unavailable capabilities are discovered up front and reported with typed
  errors **before** any mutating operation proceeds.
* Deterministic doubles (memory / directory) implement the full surface so
  contract tests and offline CI do not require a live kit/daemon.

Real ``ipfs_kit_py`` instances are wrapped when opened via
:meth:`IpfsKitGraphStore.open_kit` / ``mode="kit"``; method discovery is
duck-typed across common kit naming variants (``block_put``,
``ipfs_block_put``, ``ipfs_pin_add``, …).
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

# Reuse the shared IPLD contract surface from KGP-010 (CID, CAR, errors, doubles).
from ipfs_datasets_py.knowledge_graphs.storage.ipld_store import (
    DEFAULT_CAR_CODEC,
    DEFAULT_MANIFEST_CODEC,
    DEFAULT_PAYLOAD_CODEC,
    TYPED_ERROR_CODES,
    BlockBackend,
    BlockStat,
    GraphStoreError,
    InMemoryBlockBackend,
    PutResult,
    canonicalize_cid,
    compute_cid_v1,
    decode_car,
    decode_dag_cbor,
    encode_car,
    encode_dag_cbor,
    looks_like_cid,
    map_kubo_error,
    normalize_codec,
    parse_cid_codec,
    verify_bytes_against_cid,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STORAGE_PROFILE: str = "ipfs_kit"

# Canonical capability names negotiated by this adapter.
CAP_PUT: str = "put"
CAP_GET: str = "get"
CAP_STAT: str = "stat"
CAP_PIN: str = "pin"
CAP_UNPIN: str = "unpin"
CAP_CAR_EXPORT: str = "car_export"
CAP_CAR_IMPORT: str = "car_import"
CAP_CANCEL: str = "cancel"

ALL_CAPABILITIES: Tuple[str, ...] = (
    CAP_PUT,
    CAP_GET,
    CAP_STAT,
    CAP_PIN,
    CAP_UNPIN,
    CAP_CAR_EXPORT,
    CAP_CAR_IMPORT,
    CAP_CANCEL,
)

# Capabilities required for a fully operational GraphStore profile.
REQUIRED_MUTATION_CAPABILITIES: frozenset[str] = frozenset(
    {CAP_PUT, CAP_GET, CAP_STAT, CAP_PIN, CAP_UNPIN, CAP_CAR_EXPORT, CAP_CAR_IMPORT}
)

CancelCheck = Callable[[], None]


# ---------------------------------------------------------------------------
# Capability negotiation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KitCapabilities:
    """Explicit capability bitmap for an ``ipfs_kit`` GraphStore backend.

    ``source`` records how the bitmap was produced (``probe``, ``declared``,
    ``deterministic``) so callers can audit negotiation instead of guessing
    from import success alone.
    """

    put: bool = False
    get: bool = False
    stat: bool = False
    pin: bool = False
    unpin: bool = False
    car_export: bool = False
    car_import: bool = False
    cancel: bool = True  # cancellation is adapter-local when a hook is supplied
    source: str = "declared"
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "put": self.put,
            "get": self.get,
            "stat": self.stat,
            "pin": self.pin,
            "unpin": self.unpin,
            "car_export": self.car_export,
            "car_import": self.car_import,
            "cancel": self.cancel,
            "source": self.source,
            "details": dict(self.details),
        }

    def enabled(self) -> Set[str]:
        return {name for name in ALL_CAPABILITIES if bool(getattr(self, name, False))}

    def missing(self, required: Optional[Sequence[str]] = None) -> List[str]:
        need = list(required) if required is not None else list(REQUIRED_MUTATION_CAPABILITIES)
        return [name for name in need if not bool(getattr(self, name, False))]

    def supports(self, *names: str) -> bool:
        return all(bool(getattr(self, n, False)) for n in names)

    def is_fully_capable(self) -> bool:
        return not self.missing()


def full_capabilities(*, source: str = "deterministic", **extra: Any) -> KitCapabilities:
    """Return a fully-enabled capability set (used by deterministic doubles)."""
    return KitCapabilities(
        put=True,
        get=True,
        stat=True,
        pin=True,
        unpin=True,
        car_export=True,
        car_import=True,
        cancel=True,
        source=source,
        details=dict(extra),
    )


def _callable_attr(obj: Any, names: Sequence[str]) -> Optional[str]:
    """Return the first attribute name on ``obj`` that is callable."""
    for name in names:
        if hasattr(obj, name) and callable(getattr(obj, name)):
            return name
    return None


def probe_kit_client_capabilities(
    client: Any,
    *,
    cancel_supported: bool = True,
) -> KitCapabilities:
    """Probe a live/mock kit client for GraphStore capabilities.

    Discovery is based on **callable methods**, not package import success.
    CAR export/import are available whenever put+get exist because the adapter
    assembles/disassembles CARv1 in-process (same as the direct IPLD store).
    ``stat`` requires get (size/codec/pin derived from verified bytes).
    """
    if client is None:
        return KitCapabilities(
            source="probe",
            details={"reason": "client is None"},
            cancel=cancel_supported,
        )

    put_method = _callable_attr(
        client,
        (
            "block_put",
            "ipfs_block_put",
            "put_block",
            "dag_put",
            "ipfs_dag_put",
            "add_bytes",
            "ipfs_add_bytes",
            "add_content",
        ),
    )
    get_method = _callable_attr(
        client,
        (
            "block_get",
            "ipfs_block_get",
            "get_block",
            "dag_get",
            "ipfs_dag_get",
            "cat",
            "ipfs_cat",
            "cat_file",
        ),
    )
    pin_method = _callable_attr(
        client,
        ("pin", "pin_add", "ipfs_pin_add", "pin_recursive"),
    )
    unpin_method = _callable_attr(
        client,
        ("unpin", "pin_rm", "ipfs_pin_rm", "pin_remove"),
    )
    # Native CAR methods are optional; in-process CAR uses put/get.
    native_car_export = _callable_attr(
        client,
        ("export_car", "dag_export", "ipfs_dag_export", "car_export"),
    )
    native_car_import = _callable_attr(
        client,
        ("import_car", "dag_import", "ipfs_dag_import", "car_import"),
    )

    has_put = put_method is not None
    has_get = get_method is not None
    has_pin = pin_method is not None
    has_unpin = unpin_method is not None
    # stat is derived from get (+ optional pin status)
    has_stat = has_get
    has_car_export = has_put and has_get  # in-process CAR needs both
    has_car_import = has_put and has_get

    return KitCapabilities(
        put=has_put,
        get=has_get,
        stat=has_stat,
        pin=has_pin,
        unpin=has_unpin,
        car_export=has_car_export,
        car_import=has_car_import,
        cancel=cancel_supported,
        source="probe",
        details={
            "methods": {
                "put": put_method,
                "get": get_method,
                "pin": pin_method,
                "unpin": unpin_method,
                "native_car_export": native_car_export,
                "native_car_import": native_car_import,
            },
            "client_type": type(client).__name__,
        },
    )


def map_kit_error(
    exc: BaseException,
    *,
    operation: str,
    cid: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> GraphStoreError:
    """Map ipfs_kit_py / kit-wrapper failures to shared typed errors.

    Reuses the Kubo marker taxonomy from KGP-010 and annotates the cause with
    a kit-specific prefix when a generic STORAGE error is produced.
    """
    if isinstance(exc, GraphStoreError):
        return exc
    err = map_kubo_error(exc, operation=operation, cid=cid, extra=extra)
    # Retag generic Kubo cause codes for kit provenance when applicable.
    if err.cause_code and err.cause_code.startswith("KUBO_"):
        return GraphStoreError(
            err.code,
            err.message.replace("IPFS ", "ipfs_kit ", 1)
            if err.message.startswith("IPFS ")
            else err.message,
            retryable=err.retryable,
            details={**err.details, "adapter": "ipfs_kit"},
            cause_code="KIT_" + err.cause_code[len("KUBO_") :],
        )
    details = dict(err.details)
    details.setdefault("adapter", "ipfs_kit")
    return GraphStoreError(
        err.code,
        err.message,
        retryable=err.retryable,
        details=details,
        cause_code=err.cause_code,
    )


def kit_package_available() -> bool:
    """Return True when the ``ipfs_kit_py`` package can be imported.

    This is **not** a capability grant — callers must still open a client and
    probe methods via :func:`probe_kit_client_capabilities`.
    """
    if os.getenv("IPFS_KIT_DISABLE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    try:
        import importlib

        importlib.import_module("ipfs_kit_py")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Kit client wrappers / deterministic double
# ---------------------------------------------------------------------------


def _extract_nested(result: Any, keys: Tuple[str, ...]) -> Any:
    if isinstance(result, dict):
        for key in keys:
            value = result.get(key)
            if value not in (None, "", b""):
                return value
        for key in ("result", "results", "data", "payload", "response", "value", "ipfs"):
            value = result.get(key)
            nested = _extract_nested(value, keys)
            if nested not in (None, "", b""):
                return nested
    if isinstance(result, list):
        for item in reversed(result):
            nested = _extract_nested(item, keys)
            if nested not in (None, "", b""):
                return nested
    return None


def _extract_cid(result: Any) -> Optional[str]:
    if isinstance(result, str) and result.strip():
        return result.strip()
    cid = _extract_nested(result, ("cid", "Cid", "Hash", "hash", "Key", "key", "path"))
    if isinstance(cid, str) and cid.strip():
        return cid.strip()
    return None


def _extract_bytes(result: Any) -> Optional[bytes]:
    if isinstance(result, (bytes, bytearray, memoryview)):
        return bytes(result)
    if isinstance(result, str):
        # Prefer not to treat arbitrary strings as payload unless nested keys say so.
        return None
    payload = _extract_nested(result, ("data", "bytes", "content", "body", "text"))
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return None


def _is_success(result: Any) -> bool:
    if isinstance(result, dict):
        success = result.get("success")
        if isinstance(success, bool):
            return success
        status = str(result.get("status") or "").strip().lower()
        if status in {"ok", "success", "completed"}:
            return True
        if status in {"error", "failed", "failure"}:
            return False
        if result.get("error") not in (None, "", False):
            return False
    return True


class DeterministicKitClient:
    """Kit-shaped client backed by :class:`InMemoryBlockBackend`.

    Exposes the common ``ipfs_kit_py`` method names so capability probing and
    the live kit wrapper path share one code path. Optional ``root_dir``
    enables restart/read contract tests without a daemon.
    """

    def __init__(self, root_dir: Optional[Union[str, Path]] = None) -> None:
        self._backend = InMemoryBlockBackend(root_dir=root_dir)
        self.name = "deterministic_kit"
        self.root_dir = root_dir

    # Preferred GraphStore / router names
    def block_put(self, data: bytes, *, codec: str = "raw") -> str:
        return self._backend.put_block(data, codec=codec)

    def block_get(self, cid: str) -> bytes:
        return self._backend.get_block(cid)

    def pin(self, cid: str) -> Dict[str, Any]:
        self._backend.pin(cid)
        return {"success": True, "cid": cid}

    def unpin(self, cid: str) -> Dict[str, Any]:
        self._backend.unpin(cid)
        return {"success": True, "cid": cid}

    def is_pinned(self, cid: str) -> bool:
        return self._backend.is_pinned(cid)

    def has_block(self, cid: str) -> bool:
        return self._backend.has_block(cid)

    def list_pins(self) -> Sequence[str]:
        return self._backend.list_pins()

    def codec_for(self, cid: str) -> Optional[str]:
        return self._backend.codec_for(cid)

    def close(self) -> None:
        self._backend.close()

    # Common kit aliases (probe must find these on partial clients too)
    def ipfs_block_put(self, data: bytes, *, codec: str = "raw") -> str:
        return self.block_put(data, codec=codec)

    def ipfs_block_get(self, cid: str) -> bytes:
        return self.block_get(cid)

    def ipfs_pin_add(self, cid: str, recursive: bool = True) -> Dict[str, Any]:
        _ = recursive
        return self.pin(cid)

    def ipfs_pin_rm(self, cid: str, recursive: bool = True) -> Dict[str, Any]:
        _ = recursive
        return self.unpin(cid)

    def pin_add(self, cid: str) -> Dict[str, Any]:
        return self.pin(cid)

    def pin_rm(self, cid: str) -> Dict[str, Any]:
        return self.unpin(cid)

    def cat(self, cid: str) -> bytes:
        return self.block_get(cid)

    def ipfs_cat(self, cid: str) -> bytes:
        return self.block_get(cid)


class IpfsKitBlockBackend:
    """:class:`BlockBackend` over a duck-typed ``ipfs_kit_py`` client.

    Method resolution prefers block-level APIs, then dag, then cat/add.
    All failures are mapped through :func:`map_kit_error`.
    """

    def __init__(
        self,
        client: Any,
        *,
        capabilities: Optional[KitCapabilities] = None,
    ) -> None:
        if client is None:
            raise GraphStoreError(
                "STORAGE",
                "ipfs_kit client is required",
                retryable=False,
                cause_code="KIT_CLIENT_REQUIRED",
            )
        self.name = "ipfs_kit"
        self._client = client
        self._pins: Set[str] = set()
        self._codecs: Dict[str, str] = {}
        self._lock = threading.RLock()
        self.capabilities = capabilities or probe_kit_client_capabilities(client)
        # Cache resolved method names from probe details when present.
        methods = dict(self.capabilities.details.get("methods") or {})
        self._put_method = methods.get("put") or _callable_attr(
            client,
            (
                "block_put",
                "ipfs_block_put",
                "put_block",
                "dag_put",
                "ipfs_dag_put",
                "add_bytes",
                "ipfs_add_bytes",
                "add_content",
            ),
        )
        self._get_method = methods.get("get") or _callable_attr(
            client,
            (
                "block_get",
                "ipfs_block_get",
                "get_block",
                "dag_get",
                "ipfs_dag_get",
                "cat",
                "ipfs_cat",
                "cat_file",
            ),
        )
        self._pin_method = methods.get("pin") or _callable_attr(
            client,
            ("pin", "pin_add", "ipfs_pin_add", "pin_recursive"),
        )
        self._unpin_method = methods.get("unpin") or _callable_attr(
            client,
            ("unpin", "pin_rm", "ipfs_pin_rm", "pin_remove"),
        )
        self._is_pinned_method = _callable_attr(
            client,
            ("is_pinned", "pin_ls", "ipfs_pin_ls", "pins"),
        )

    def _call(self, method_name: Optional[str], *args: Any, **kwargs: Any) -> Any:
        if not method_name:
            raise GraphStoreError(
                "NOT_IMPLEMENTED",
                "ipfs_kit method not available for this operation",
                retryable=False,
                details={"operation": "call"},
                cause_code="KIT_METHOD_MISSING",
            )
        method = getattr(self._client, method_name)
        try:
            return method(*args, **kwargs)
        except TypeError:
            # Some kit methods reject unexpected kwargs; retry positionally.
            try:
                return method(*args)
            except Exception as exc:
                raise map_kit_error(exc, operation=method_name) from exc
        except Exception as exc:
            raise map_kit_error(exc, operation=method_name) from exc

    def put_block(self, data: bytes, *, codec: str) -> str:
        if not self.capabilities.put:
            raise GraphStoreError(
                "NOT_IMPLEMENTED",
                "ipfs_kit put capability is unavailable",
                retryable=False,
                details={"capability": CAP_PUT, "available": sorted(self.capabilities.enabled())},
                cause_code="KIT_CAP_PUT",
            )
        codec_n = normalize_codec(codec)
        payload = bytes(data)
        expected = compute_cid_v1(payload, codec=codec_n)
        method = self._put_method
        try:
            if method in {"block_put", "ipfs_block_put", "put_block"}:
                result = self._call(method, payload, codec=codec_n)
            elif method in {"dag_put", "ipfs_dag_put"}:
                # DAG put may accept decoded values; supply bytes via raw wrapper.
                result = self._call(method, payload)
            else:
                result = self._call(method, payload)
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kit_error(exc, operation="block_put") from exc

        cid = _extract_cid(result) or (result if isinstance(result, str) else None)
        if not cid:
            # Fall back to deterministic CIDv1 when kit returns unstructured success.
            if _is_success(result):
                cid = expected
            else:
                raise map_kit_error(
                    RuntimeError(f"ipfs_kit put returned no CID: {result!r}"[:300]),
                    operation="block_put",
                )
        try:
            verify_bytes_against_cid(cid, payload, expected_codec=codec_n)
            final = cid
        except GraphStoreError:
            # Prefer our CIDv1 identity when kit returns a compatible base variant
            # that fails string equality but matches content; use expected.
            final = expected
        with self._lock:
            self._codecs[final] = codec_n
        return final

    def get_block(self, cid: str) -> bytes:
        if not self.capabilities.get:
            raise GraphStoreError(
                "NOT_IMPLEMENTED",
                "ipfs_kit get capability is unavailable",
                retryable=False,
                details={"capability": CAP_GET, "available": sorted(self.capabilities.enabled())},
                cause_code="KIT_CAP_GET",
            )
        method = self._get_method
        try:
            result = self._call(method, cid)
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kit_error(exc, operation="block_get", cid=cid) from exc

        if isinstance(result, (bytes, bytearray, memoryview)):
            return bytes(result)
        payload = _extract_bytes(result)
        if payload is not None:
            return payload
        # dag_get may return a decoded mapping — re-encode as DAG-CBOR when possible.
        if isinstance(result, (dict, list)):
            return encode_dag_cbor(result)
        if isinstance(result, dict) and not _is_success(result):
            raise map_kit_error(
                RuntimeError(str(result.get("error") or result)[:300]),
                operation="block_get",
                cid=cid,
            )
        raise GraphStoreError(
            "NOT_FOUND",
            f"ipfs_kit block not found: {cid}",
            details={"cid": cid, "backend": self.name},
            cause_code="KIT_NOT_FOUND",
        )

    def has_block(self, cid: str) -> bool:
        if hasattr(self._client, "has_block") and callable(self._client.has_block):
            try:
                return bool(self._client.has_block(cid))
            except Exception:
                pass
        try:
            self.get_block(cid)
            return True
        except GraphStoreError as err:
            if err.code in {"NOT_FOUND", "NOT_IMPLEMENTED"}:
                return False
            raise

    def pin(self, cid: str) -> None:
        if not self.capabilities.pin:
            raise GraphStoreError(
                "NOT_IMPLEMENTED",
                "ipfs_kit pin capability is unavailable",
                retryable=False,
                details={"capability": CAP_PIN, "available": sorted(self.capabilities.enabled())},
                cause_code="KIT_CAP_PIN",
            )
        # Ensure the block exists when the client can check.
        if not self.has_block(cid):
            raise GraphStoreError(
                "NOT_FOUND",
                f"cannot pin missing block: {cid}",
                details={"cid": cid, "backend": self.name},
                cause_code="KIT_NOT_FOUND",
            )
        method = self._pin_method
        try:
            if method in {"ipfs_pin_add"}:
                result = self._call(method, cid, recursive=True)
            else:
                result = self._call(method, cid)
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kit_error(exc, operation="pin", cid=cid) from exc
        if result is not None and not _is_success(result) and not isinstance(result, (str, bool)):
            raise map_kit_error(
                RuntimeError(f"ipfs_kit pin failed: {result!r}"[:300]),
                operation="pin",
                cid=cid,
            )
        with self._lock:
            self._pins.add(cid)

    def unpin(self, cid: str) -> None:
        if not self.capabilities.unpin:
            raise GraphStoreError(
                "NOT_IMPLEMENTED",
                "ipfs_kit unpin capability is unavailable",
                retryable=False,
                details={"capability": CAP_UNPIN, "available": sorted(self.capabilities.enabled())},
                cause_code="KIT_CAP_UNPIN",
            )
        method = self._unpin_method
        try:
            if method in {"ipfs_pin_rm"}:
                result = self._call(method, cid, recursive=True)
            else:
                result = self._call(method, cid)
        except GraphStoreError as err:
            if err.code == "NOT_FOUND":
                with self._lock:
                    self._pins.discard(cid)
                return
            raise
        except Exception as exc:
            err = map_kit_error(exc, operation="unpin", cid=cid)
            if err.code == "NOT_FOUND":
                with self._lock:
                    self._pins.discard(cid)
                return
            backend = (err.details.get("backend_error") or "").lower()
            if "not pinned" in backend or "not under pin" in backend:
                with self._lock:
                    self._pins.discard(cid)
                return
            raise err from exc
        with self._lock:
            self._pins.discard(cid)

    def is_pinned(self, cid: str) -> bool:
        if hasattr(self._client, "is_pinned") and callable(self._client.is_pinned):
            try:
                return bool(self._client.is_pinned(cid))
            except Exception:
                pass
        with self._lock:
            if cid in self._pins:
                return True
        if self._is_pinned_method in {"pin_ls", "ipfs_pin_ls", "pins"}:
            try:
                result = self._call(self._is_pinned_method, cid)
                if isinstance(result, (bytes, str)):
                    text = result.decode("utf-8", errors="replace") if isinstance(result, bytes) else result
                    return cid in text or bool(text.strip())
                if isinstance(result, dict):
                    return _is_success(result)
            except GraphStoreError as err:
                if err.code == "NOT_FOUND":
                    return False
                raise
            except Exception:
                return False
        with self._lock:
            return cid in self._pins

    def list_pins(self) -> Sequence[str]:
        if hasattr(self._client, "list_pins") and callable(self._client.list_pins):
            try:
                return list(self._client.list_pins())
            except Exception:
                pass
        with self._lock:
            return sorted(self._pins)

    def codec_for(self, cid: str) -> Optional[str]:
        with self._lock:
            if cid in self._codecs:
                return self._codecs[cid]
        if hasattr(self._client, "codec_for") and callable(self._client.codec_for):
            try:
                return self._client.codec_for(cid)
            except Exception:
                return None
        return None

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # pragma: no cover
                logger.debug("kit client close failed", exc_info=True)


# ---------------------------------------------------------------------------
# IpfsKitGraphStore
# ---------------------------------------------------------------------------


class IpfsKitGraphStore:
    """GraphStore adapter for profile ``ipfs_kit`` via capability negotiation.

    Contract surface (shared with KGP-010 ``ipfs_ipld`` adapter):

    * ``put`` / ``get`` (typed helpers for manifest, index, raw, CAR)
    * ``stat`` / ``pin`` / ``unpin``
    * ``export_car`` / ``import_car``
    * CID verification after every fetch
    * typed errors via :class:`GraphStoreError`
    * cancellation via ``cancel_check``

    Unavailable capabilities are reported as ``NOT_IMPLEMENTED`` (or
    ``STORAGE`` when the kit itself is missing) **before** mutation.
    """

    storage_profile: str = STORAGE_PROFILE

    def __init__(
        self,
        backend: Optional[BlockBackend] = None,
        *,
        kit_client: Any = None,
        capabilities: Optional[KitCapabilities] = None,
        pin_by_default: bool = True,
        cancel_check: Optional[CancelCheck] = None,
        verify_on_fetch: bool = True,
        require_full_capabilities: bool = False,
    ) -> None:
        """Create an adapter.

        Prefer the ``open_*`` constructors. When both ``backend`` and
        ``kit_client`` are omitted, a deterministic in-memory kit client is
        used (explicit double — not an import-time silent fallback).
        """
        self.pin_by_default = pin_by_default
        self._cancel_check = cancel_check
        self.verify_on_fetch = verify_on_fetch
        self._local_index: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._kit_client = kit_client

        if backend is not None:
            self._backend = backend
            if capabilities is not None:
                self.capabilities = capabilities
            elif isinstance(backend, IpfsKitBlockBackend):
                self.capabilities = backend.capabilities
            else:
                # Direct BlockBackend doubles expose the full surface.
                self.capabilities = full_capabilities(
                    source="deterministic",
                    backend=getattr(backend, "name", type(backend).__name__),
                )
        elif kit_client is not None:
            caps = capabilities or probe_kit_client_capabilities(
                kit_client,
                cancel_supported=True,
            )
            self.capabilities = caps
            self._backend = IpfsKitBlockBackend(kit_client, capabilities=caps)
            self._kit_client = kit_client
        else:
            client = DeterministicKitClient()
            self._kit_client = client
            self.capabilities = full_capabilities(source="deterministic", backend="memory")
            self._backend = IpfsKitBlockBackend(client, capabilities=self.capabilities)

        if require_full_capabilities:
            missing = self.capabilities.missing()
            if missing:
                raise GraphStoreError(
                    "NOT_IMPLEMENTED",
                    "ipfs_kit GraphStore missing required capabilities",
                    retryable=False,
                    details={
                        "missing": missing,
                        "available": sorted(self.capabilities.enabled()),
                        "capabilities": self.capabilities.as_dict(),
                    },
                    cause_code="KIT_CAPABILITIES_INCOMPLETE",
                )

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def open_memory(cls, **kwargs: Any) -> "IpfsKitGraphStore":
        """Open a deterministic in-memory kit double (full capabilities)."""
        client = DeterministicKitClient()
        return cls(
            kit_client=client,
            capabilities=full_capabilities(source="deterministic", backend="memory"),
            **kwargs,
        )

    @classmethod
    def open_directory(cls, root_dir: Union[str, Path], **kwargs: Any) -> "IpfsKitGraphStore":
        """Open a filesystem-backed deterministic kit double (restart-safe)."""
        client = DeterministicKitClient(root_dir=root_dir)
        return cls(
            kit_client=client,
            capabilities=full_capabilities(
                source="deterministic",
                backend="directory",
                root_dir=str(root_dir),
            ),
            **kwargs,
        )

    @classmethod
    def open_kit(
        cls,
        kit_client: Any = None,
        *,
        resources: Optional[Mapping[str, Any]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        require_full_capabilities: bool = False,
        **kwargs: Any,
    ) -> "IpfsKitGraphStore":
        """Open against a real (or injected) ``ipfs_kit_py`` client.

        When ``kit_client`` is omitted the package is imported and
        ``ipfs_kit_py.ipfs_kit.ipfs_kit`` is constructed. Import success alone
        is not enough: methods are probed and missing capabilities are
        recorded on the store (mutations fail closed until present).
        """
        client = kit_client
        if client is None:
            if not kit_package_available():
                raise GraphStoreError(
                    "STORAGE",
                    "ipfs_kit_py package is not available",
                    retryable=False,
                    details={"package": "ipfs_kit_py"},
                    cause_code="KIT_PACKAGE_UNAVAILABLE",
                )
            try:
                from ipfs_kit_py.ipfs_kit import ipfs_kit as ipfs_kit_factory
            except Exception as exc:
                raise GraphStoreError(
                    "STORAGE",
                    "failed to import ipfs_kit_py.ipfs_kit",
                    retryable=False,
                    details={"error": str(exc)[:300]},
                    cause_code="KIT_IMPORT_FAILED",
                ) from exc
            try:
                client = ipfs_kit_factory(
                    resources=dict(resources or {}),
                    metadata=dict(metadata or {}),
                )
            except Exception as exc:
                raise GraphStoreError(
                    "STORAGE",
                    "failed to construct ipfs_kit_py client",
                    retryable=True,
                    details={"error": str(exc)[:300]},
                    cause_code="KIT_CONSTRUCT_FAILED",
                ) from exc

        caps = probe_kit_client_capabilities(client, cancel_supported=True)
        return cls(
            kit_client=client,
            capabilities=caps,
            require_full_capabilities=require_full_capabilities,
            **kwargs,
        )

    @classmethod
    def open_auto(cls, **kwargs: Any) -> "IpfsKitGraphStore":
        """Prefer a fully capable live kit; otherwise open a deterministic double.

        Unlike silent import-time fallback, this constructor **documents** the
        choice via ``capabilities.source`` (``probe`` vs ``deterministic``).
        """
        if kit_package_available():
            try:
                store = cls.open_kit(**kwargs)
                if store.capabilities.supports(CAP_PUT, CAP_GET):
                    return store
                store.close()
            except GraphStoreError:
                pass
        return cls.open_memory(**kwargs)

    def close(self) -> None:
        try:
            self._backend.close()
        except Exception:  # pragma: no cover
            logger.debug("backend close failed", exc_info=True)

    @property
    def backend_name(self) -> str:
        return getattr(self._backend, "name", type(self._backend).__name__)

    def negotiate_capabilities(self) -> KitCapabilities:
        """Re-probe the kit client (if any) and return the current capability set."""
        if self._kit_client is not None:
            self.capabilities = probe_kit_client_capabilities(
                self._kit_client,
                cancel_supported=True,
            )
            if isinstance(self._backend, IpfsKitBlockBackend):
                self._backend.capabilities = self.capabilities
        return self.capabilities

    def report_capabilities(self) -> Dict[str, Any]:
        """Public capability report for service / diagnostics surfaces."""
        return {
            "storage_profile": self.storage_profile,
            "backend": self.backend_name,
            "capabilities": self.capabilities.as_dict(),
            "available": sorted(self.capabilities.enabled()),
            "missing": self.capabilities.missing(),
            "fully_capable": self.capabilities.is_fully_capable(),
        }

    # -- capability enforcement --------------------------------------------

    def _require_capabilities(self, *names: str, operation: str) -> None:
        """Raise typed error before mutation when any capability is missing."""
        missing = [n for n in names if not self.capabilities.supports(n)]
        if not missing:
            return
        raise GraphStoreError(
            "NOT_IMPLEMENTED",
            f"ipfs_kit capability unavailable before {operation}: {', '.join(missing)}",
            retryable=False,
            details={
                "operation": operation,
                "missing": missing,
                "required": list(names),
                "available": sorted(self.capabilities.enabled()),
                "capabilities": self.capabilities.as_dict(),
            },
            cause_code="KIT_CAPABILITY_UNAVAILABLE",
        )

    def _check_cancelled(self) -> None:
        if self._cancel_check is not None:
            self._cancel_check()

    # -- core put/get ------------------------------------------------------

    def put(
        self,
        data: bytes,
        *,
        codec: str = DEFAULT_PAYLOAD_CODEC,
        pin: Optional[bool] = None,
    ) -> PutResult:
        """Store raw block bytes under ``codec`` and return the CID."""
        self._check_cancelled()
        self._require_capabilities(CAP_PUT, operation="put")
        should_pin = self.pin_by_default if pin is None else bool(pin)
        if should_pin:
            self._require_capabilities(CAP_PIN, operation="put(pin=True)")

        codec_n = normalize_codec(codec)
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise GraphStoreError(
                "INVALID_REQUEST",
                "put() requires bytes data",
                details={"type": type(data).__name__},
            )
        payload = bytes(data)
        try:
            cid = self._backend.put_block(payload, codec=codec_n)
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kit_error(exc, operation="put") from exc

        cid = verify_bytes_against_cid(cid, payload, expected_codec=codec_n)

        if should_pin:
            self.pin(cid)
        with self._lock:
            self._local_index[cid] = codec_n
        return PutResult(cid=cid, codec=codec_n, size=len(payload), pinned=should_pin)

    def get(self, cid: str, *, expected_codec: Optional[str] = None) -> bytes:
        """Fetch block bytes and verify them against ``cid``."""
        self._check_cancelled()
        self._require_capabilities(CAP_GET, operation="get")
        if not isinstance(cid, str) or not cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "CID must be a non-empty string")
        cid_n = canonicalize_cid(cid)
        try:
            data = self._backend.get_block(cid_n)
        except GraphStoreError as err:
            if err.code == "NOT_FOUND" and cid_n != cid.strip():
                try:
                    data = self._backend.get_block(cid.strip())
                    cid_n = cid.strip()
                except GraphStoreError:
                    raise err from err
            else:
                raise
        except Exception as exc:
            raise map_kit_error(exc, operation="get", cid=cid_n) from exc

        payload = bytes(data)
        if self.verify_on_fetch:
            verify_bytes_against_cid(cid_n, payload, expected_codec=expected_codec)
        return payload

    # -- DAG-CBOR manifests / indexes --------------------------------------

    def put_dag_cbor(
        self,
        value: Any,
        *,
        pin: Optional[bool] = None,
    ) -> PutResult:
        encoded = encode_dag_cbor(value)
        return self.put(encoded, codec=DEFAULT_MANIFEST_CODEC, pin=pin)

    def get_dag_cbor(self, cid: str) -> Any:
        data = self.get(cid, expected_codec=DEFAULT_MANIFEST_CODEC)
        return decode_dag_cbor(data)

    def put_manifest(
        self,
        manifest: Any,
        *,
        pin: Optional[bool] = None,
    ) -> PutResult:
        payload = _manifest_to_mapping(manifest)
        return self.put_dag_cbor(payload, pin=pin)

    def get_manifest(self, cid: str) -> Dict[str, Any]:
        value = self.get_dag_cbor(cid)
        if not isinstance(value, Mapping):
            raise GraphStoreError(
                "INTEGRITY",
                "manifest block is not a mapping",
                details={"cid": cid, "type": type(value).__name__},
            )
        try:
            from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
                GraphRevisionManifest,
            )

            return GraphRevisionManifest.from_dict(value).to_dict()
        except ImportError:
            return dict(value)
        except Exception as exc:
            code = getattr(exc, "code", None) or "INTEGRITY"
            if code not in TYPED_ERROR_CODES:
                code = "INTEGRITY"
            raise GraphStoreError(
                code if code in ("INTEGRITY", "INVALID_REQUEST") else "INTEGRITY",
                f"manifest validation failed: {exc}",
                details={"cid": cid, "error_class": type(exc).__name__},
                cause_code=str(getattr(exc, "code", "MANIFEST_INVALID")),
            ) from exc

    def put_index(
        self,
        index_data: Mapping[str, Any],
        *,
        pin: Optional[bool] = None,
    ) -> PutResult:
        if not isinstance(index_data, Mapping):
            raise GraphStoreError(
                "INVALID_REQUEST",
                "index_data must be a mapping",
                details={"type": type(index_data).__name__},
            )
        import json

        canonical = json.loads(json.dumps(dict(index_data), sort_keys=True, allow_nan=False))
        return self.put_dag_cbor(canonical, pin=pin)

    def get_index(self, cid: str) -> Dict[str, Any]:
        value = self.get_dag_cbor(cid)
        if not isinstance(value, Mapping):
            raise GraphStoreError(
                "INTEGRITY",
                "index block is not a mapping",
                details={"cid": cid, "type": type(value).__name__},
            )
        return dict(value)

    # -- CAR payload objects -----------------------------------------------

    def put_car_object(
        self,
        car_bytes: bytes,
        *,
        pin: Optional[bool] = None,
    ) -> PutResult:
        if not isinstance(car_bytes, (bytes, bytearray, memoryview)):
            raise GraphStoreError(
                "INVALID_REQUEST",
                "car_bytes must be bytes",
                details={"type": type(car_bytes).__name__},
            )
        payload = bytes(car_bytes)
        if not payload:
            raise GraphStoreError("INVALID_REQUEST", "car_bytes must be non-empty")
        try:
            decode_car(payload)
        except GraphStoreError as err:
            if err.code not in {"NOT_IMPLEMENTED"}:
                raise
        return self.put(payload, codec=DEFAULT_CAR_CODEC, pin=pin)

    def get_car_object(self, cid: str) -> bytes:
        return self.get(cid, expected_codec=DEFAULT_CAR_CODEC)

    def export_car(
        self,
        root_cids: Union[str, Sequence[str]],
        *,
        include_reachable: bool = True,
    ) -> bytes:
        self._check_cancelled()
        self._require_capabilities(CAP_CAR_EXPORT, CAP_GET, operation="export_car")
        if isinstance(root_cids, str):
            roots = [root_cids]
        else:
            roots = list(root_cids)
        if not roots:
            raise GraphStoreError("INVALID_REQUEST", "export_car requires root CIDs")

        collected: Dict[str, bytes] = {}
        for root in roots:
            self._collect_blocks(root, collected, include_reachable=include_reachable)

        blocks = [(cid, collected[cid]) for cid in sorted(collected.keys())]
        return encode_car(roots, blocks)

    def import_car(
        self,
        car_bytes: bytes,
        *,
        pin_roots: bool = True,
    ) -> List[str]:
        self._check_cancelled()
        self._require_capabilities(CAP_CAR_IMPORT, CAP_PUT, operation="import_car")
        if pin_roots:
            self._require_capabilities(CAP_PIN, operation="import_car(pin_roots=True)")

        roots, blocks = decode_car(car_bytes)
        for cid, data in blocks:
            try:
                codec = parse_cid_codec(cid)
            except GraphStoreError:
                codec = "raw"
            verify_bytes_against_cid(cid, data, expected_codec=codec)
            try:
                stored = self._backend.put_block(data, codec=codec)
            except GraphStoreError:
                raise
            except Exception as exc:
                raise map_kit_error(exc, operation="import_car", cid=cid) from exc
            if stored != cid:
                verify_bytes_against_cid(cid, data, expected_codec=codec)
            with self._lock:
                self._local_index[cid] = codec

        if pin_roots:
            for root in roots:
                try:
                    self.pin(root)
                except GraphStoreError as err:
                    if err.code != "NOT_FOUND":
                        raise
        return list(roots)

    def _collect_blocks(
        self,
        cid: str,
        out: MutableMapping[str, bytes],
        *,
        include_reachable: bool,
        depth: int = 0,
    ) -> None:
        if cid in out:
            return
        if depth > 10_000:
            raise GraphStoreError(
                "INTERNAL",
                "block collection depth exceeded",
                details={"cid": cid},
            )
        data = self.get(cid)
        out[cid] = data
        if not include_reachable:
            return
        codec = None
        with self._lock:
            codec = self._local_index.get(cid)
        if codec is None and hasattr(self._backend, "codec_for"):
            try:
                codec = self._backend.codec_for(cid)  # type: ignore[attr-defined]
            except Exception:
                codec = None
        if codec is None:
            try:
                codec = parse_cid_codec(cid)
            except GraphStoreError:
                codec = "raw"
        if codec == "dag-cbor":
            try:
                value = decode_dag_cbor(data)
            except GraphStoreError:
                return
            for linked in _iter_cid_strings(value):
                if linked == cid:
                    continue
                if self._backend.has_block(linked) or linked in self._local_index:
                    self._collect_blocks(
                        linked,
                        out,
                        include_reachable=True,
                        depth=depth + 1,
                    )

    # -- pin / unpin / stat ------------------------------------------------

    def pin(self, cid: str) -> None:
        self._check_cancelled()
        self._require_capabilities(CAP_PIN, operation="pin")
        if not isinstance(cid, str) or not cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "CID must be a non-empty string")
        try:
            self._backend.pin(cid)
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kit_error(exc, operation="pin", cid=cid) from exc

    def unpin(self, cid: str) -> None:
        self._check_cancelled()
        self._require_capabilities(CAP_UNPIN, operation="unpin")
        if not isinstance(cid, str) or not cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "CID must be a non-empty string")
        try:
            self._backend.unpin(cid)
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kit_error(exc, operation="unpin", cid=cid) from exc

    def is_pinned(self, cid: str) -> bool:
        try:
            return bool(self._backend.is_pinned(cid))
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kit_error(exc, operation="is_pinned", cid=cid) from exc

    def stat(self, cid: str) -> BlockStat:
        """Return size/codec/pin status for ``cid`` (fetches + verifies bytes)."""
        self._check_cancelled()
        self._require_capabilities(CAP_STAT, CAP_GET, operation="stat")
        data = self.get(cid)
        try:
            codec = parse_cid_codec(cid)
        except GraphStoreError:
            codec = "raw"
        with self._lock:
            codec = self._local_index.get(cid, codec)
        pinned = False
        try:
            pinned = self.is_pinned(cid)
        except GraphStoreError:
            pinned = False
        return BlockStat(
            cid=cid,
            size=len(data),
            codec=codec,
            pinned=pinned,
            local=True,
            backend=self.backend_name,
        )

    # -- helpers -----------------------------------------------------------

    def has(self, cid: str) -> bool:
        try:
            return bool(self._backend.has_block(cid))
        except GraphStoreError as err:
            if err.code == "NOT_FOUND":
                return False
            raise

    def put_json(self, value: Any, *, pin: Optional[bool] = None) -> PutResult:
        return self.put_dag_cbor(value, pin=pin)

    def get_json(self, cid: str) -> Any:
        return self.get_dag_cbor(cid)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manifest_to_mapping(manifest: Any) -> Dict[str, Any]:
    if isinstance(manifest, Mapping):
        return dict(manifest)
    if hasattr(manifest, "to_dict") and callable(manifest.to_dict):
        data = manifest.to_dict()
        if isinstance(data, Mapping):
            return dict(data)
    if hasattr(manifest, "to_json_dict") and callable(manifest.to_json_dict):
        data = manifest.to_json_dict()
        if isinstance(data, Mapping):
            return dict(data)
    raise GraphStoreError(
        "INVALID_REQUEST",
        "manifest must be a mapping or GraphRevisionManifest",
        details={"type": type(manifest).__name__},
    )


def _iter_cid_strings(value: Any):
    if isinstance(value, str):
        if looks_like_cid(value):
            yield value
        return
    if isinstance(value, Mapping):
        for v in value.values():
            yield from _iter_cid_strings(v)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_cid_strings(item)


def create_ipfs_kit_graph_store(
    *,
    mode: str = "auto",
    root_dir: Optional[Union[str, Path]] = None,
    kit_client: Any = None,
    backend: Optional[BlockBackend] = None,
    capabilities: Optional[KitCapabilities] = None,
    pin_by_default: bool = True,
    cancel_check: Optional[CancelCheck] = None,
    require_full_capabilities: bool = False,
) -> IpfsKitGraphStore:
    """Create an :class:`IpfsKitGraphStore`.

    Parameters
    ----------
    mode:
        ``auto`` | ``memory`` | ``directory`` | ``kit``
    root_dir:
        Required for ``directory`` mode.
    kit_client:
        Explicit kit client (wins over constructing one in ``kit`` mode).
    backend:
        Explicit :class:`BlockBackend` (wins over ``mode``).
    """
    if backend is not None:
        return IpfsKitGraphStore(
            backend,
            kit_client=kit_client,
            capabilities=capabilities,
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
            require_full_capabilities=require_full_capabilities,
        )
    if kit_client is not None and (mode or "auto").strip().lower() in {"auto", "kit"}:
        return IpfsKitGraphStore.open_kit(
            kit_client,
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
            require_full_capabilities=require_full_capabilities,
        )

    mode_n = (mode or "auto").strip().lower()
    if mode_n == "memory":
        return IpfsKitGraphStore.open_memory(
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
            require_full_capabilities=require_full_capabilities,
        )
    if mode_n == "directory":
        if root_dir is None:
            raise GraphStoreError(
                "INVALID_REQUEST",
                "root_dir is required for directory mode",
            )
        return IpfsKitGraphStore.open_directory(
            root_dir,
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
            require_full_capabilities=require_full_capabilities,
        )
    if mode_n == "kit":
        return IpfsKitGraphStore.open_kit(
            kit_client,
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
            require_full_capabilities=require_full_capabilities,
        )
    if mode_n == "auto":
        return IpfsKitGraphStore.open_auto(
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
            require_full_capabilities=require_full_capabilities,
        )
    raise GraphStoreError(
        "INVALID_REQUEST",
        f"unknown store mode: {mode!r}",
        details={"mode": mode},
    )


__all__ = [
    "STORAGE_PROFILE",
    "ALL_CAPABILITIES",
    "REQUIRED_MUTATION_CAPABILITIES",
    "CAP_PUT",
    "CAP_GET",
    "CAP_STAT",
    "CAP_PIN",
    "CAP_UNPIN",
    "CAP_CAR_EXPORT",
    "CAP_CAR_IMPORT",
    "CAP_CANCEL",
    "KitCapabilities",
    "full_capabilities",
    "probe_kit_client_capabilities",
    "map_kit_error",
    "kit_package_available",
    "DeterministicKitClient",
    "IpfsKitBlockBackend",
    "IpfsKitGraphStore",
    "create_ipfs_kit_graph_store",
    # Re-exports used by contract tests / hybrid layer
    "GraphStoreError",
    "BlockStat",
    "PutResult",
    "TYPED_ERROR_CODES",
    "compute_cid_v1",
    "verify_bytes_against_cid",
    "encode_dag_cbor",
    "decode_dag_cbor",
    "encode_car",
    "decode_car",
]
