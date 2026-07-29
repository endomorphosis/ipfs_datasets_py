"""Direct IPFS/IPLD GraphStore (KGP-010).

Production storage profile ``ipfs_ipld`` for knowledge-graph revisions:

* Canonical **DAG-CBOR** blocks for revision manifests and index pages
* **CAR** payload objects (raw blocks of CAR bytes) plus multi-block CAR
  export/import for offline round trips
* **CID verification after every fetch** (codec + multihash)
* **pin / unpin / stat** capabilities
* Kubo / backend failures mapped to the shared service-contract typed
  error codes (``STORAGE``, ``INTEGRITY``, ``NOT_FOUND``, …)
* Deterministic in-memory / filesystem doubles for tests, plus an optional
  real Kubo daemon backend when ``ipfs`` is available

This module is the direct adapter; ``ipfs_kit_py`` is a separate adapter
(KGP-011) that must match the same contract surface.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Union,
    runtime_checkable,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STORAGE_PROFILE: str = "ipfs_ipld"
DEFAULT_MANIFEST_CODEC: str = "dag-cbor"
DEFAULT_INDEX_CODEC: str = "dag-cbor"
DEFAULT_CAR_CODEC: str = "raw"
DEFAULT_PAYLOAD_CODEC: str = "raw"

# Multicodec codes used for CIDv1 construction when multiformats is absent.
_CODEC_CODES: Dict[str, int] = {
    "raw": 0x55,
    "dag-pb": 0x70,
    "dag-cbor": 0x71,
    "dag-json": 0x0129,
}
_CODE_TO_CODEC: Dict[int, str] = {v: k for k, v in _CODEC_CODES.items()}

# Shared typed-error vocabulary (kg-service-contract/v1 §6.2).
TYPED_ERROR_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "INVALID_TARGET",
        "NOT_FOUND",
        "ALREADY_EXISTS",
        "CONFLICT",
        "FENCED",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "BUDGET_EXCEEDED",
        "QUERY_PARSE",
        "QUERY_EXECUTION",
        "STORAGE",
        "INTEGRITY",
        "NOT_IMPLEMENTED",
        "INTERNAL",
    }
)

_CID_TEXT_RE = re.compile(
    r"^(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{50,120}|bagu[a-z2-7]{50,120})$"
)

CancelCheck = Callable[[], None]


# ---------------------------------------------------------------------------
# Optional dependencies
# ---------------------------------------------------------------------------

try:
    import dag_cbor as _dag_cbor  # type: ignore[import]

    _HAVE_DAG_CBOR = True
except Exception:  # pragma: no cover - optional at import time
    _dag_cbor = None  # type: ignore[assignment]
    _HAVE_DAG_CBOR = False

try:
    from multiformats import CID as _MF_CID  # type: ignore[import]
    from multiformats import multihash as _MF_MULTIHASH  # type: ignore[import]

    _HAVE_MULTIFORMATS = True
except Exception:  # pragma: no cover
    _MF_CID = None  # type: ignore[assignment]
    _MF_MULTIHASH = None  # type: ignore[assignment]
    _HAVE_MULTIFORMATS = False

try:
    import ipld_car as _ipld_car  # type: ignore[import]

    _HAVE_IPLD_CAR = True
except Exception:  # pragma: no cover
    _ipld_car = None  # type: ignore[assignment]
    _HAVE_IPLD_CAR = False


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class GraphStoreError(Exception):
    """Storage adapter error with a shared service-contract ``code``.

    Surfaces map this object via :meth:`to_typed_dict` into the LifecycleResult
    / TypedError envelope without leaking backend secrets.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Optional[Mapping[str, Any]] = None,
        cause_code: Optional[str] = None,
    ) -> None:
        if code not in TYPED_ERROR_CODES:
            raise ValueError(f"unknown typed error code: {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = bool(retryable)
        self.details: Dict[str, Any] = dict(details or {})
        self.cause_code = cause_code

    def to_typed_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
            "cause_code": self.cause_code,
        }

    def __str__(self) -> str:
        if self.details:
            extra = ", ".join(f"{k}={v!r}" for k, v in self.details.items())
            return f"[{self.code}] {self.message} ({extra})"
        return f"[{self.code}] {self.message}"


def map_kubo_error(
    exc: BaseException,
    *,
    operation: str,
    cid: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> GraphStoreError:
    """Map Kubo CLI / HTTP / generic backend failures to typed errors."""
    if isinstance(exc, GraphStoreError):
        return exc

    raw = str(exc) or type(exc).__name__
    msg = raw.lower()
    details: Dict[str, Any] = {"operation": operation, "backend_error": raw[:500]}
    if cid is not None:
        details["cid"] = cid
    if extra:
        details.update(extra)

    not_found_markers = (
        "not found",
        "block was not found",
        "no such file",
        "path not found",
        "does not exist",
        "merkledag: not found",
        "ipld: could not find",
        "no link named",
        "key not found",
        "cid not found",
    )
    if any(m in msg for m in not_found_markers):
        return GraphStoreError(
            "NOT_FOUND",
            f"IPFS object not found during {operation}",
            retryable=False,
            details=details,
            cause_code="KUBO_NOT_FOUND",
        )

    integrity_markers = (
        "cid mismatch",
        "checksum",
        "corrupt",
        "integrity",
        "hash mismatch",
        "invalid multihash",
        "unexpected cid",
    )
    if any(m in msg for m in integrity_markers):
        return GraphStoreError(
            "INTEGRITY",
            f"IPFS integrity failure during {operation}",
            retryable=False,
            details=details,
            cause_code="KUBO_INTEGRITY",
        )

    invalid_markers = (
        "invalid",
        "malformed",
        "bad request",
        "unknown codec",
        "unsupported",
        "illegal",
        "parse error",
    )
    if any(m in msg for m in invalid_markers):
        return GraphStoreError(
            "INVALID_REQUEST",
            f"Invalid IPFS request during {operation}",
            retryable=False,
            details=details,
            cause_code="KUBO_INVALID",
        )

    transient_markers = (
        "timeout",
        "timed out",
        "connection refused",
        "connection reset",
        "temporarily unavailable",
        "context deadline",
        "i/o timeout",
        "network is unreachable",
        "broken pipe",
        "try again",
        "resource temporarily",
        "503",
        "502",
        "504",
    )
    if isinstance(exc, (TimeoutError, ConnectionError, BrokenPipeError, OSError)) or any(
        m in msg for m in transient_markers
    ):
        return GraphStoreError(
            "STORAGE",
            f"IPFS storage backend unavailable during {operation}",
            retryable=True,
            details=details,
            cause_code="KUBO_TRANSIENT",
        )

    return GraphStoreError(
        "STORAGE",
        f"IPFS storage operation failed: {operation}",
        retryable=True,
        details=details,
        cause_code="KUBO_ERROR",
    )


# ---------------------------------------------------------------------------
# CID / codec helpers
# ---------------------------------------------------------------------------


def _unsigned_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint cannot be negative")
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _codec_code(codec: str) -> int:
    key = codec.strip().lower()
    if key not in _CODEC_CODES:
        raise GraphStoreError(
            "INVALID_REQUEST",
            f"unsupported IPLD codec: {codec!r}",
            details={"codec": codec},
        )
    return _CODEC_CODES[key]


def normalize_codec(codec: str) -> str:
    key = (codec or "").strip().lower()
    if key not in _CODEC_CODES:
        raise GraphStoreError(
            "INVALID_REQUEST",
            f"unsupported IPLD codec: {codec!r}",
            details={"codec": codec},
        )
    return key


def compute_cid_v1(data: bytes, *, codec: str = "raw") -> str:
    """Compute CIDv1 base32 (unpadded) for ``data`` under ``codec``/sha2-256."""
    codec_n = normalize_codec(codec)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise GraphStoreError(
            "INVALID_REQUEST",
            "block data must be bytes-like",
            details={"type": type(data).__name__},
        )
    payload = bytes(data)

    if _HAVE_MULTIFORMATS:
        digest = _MF_MULTIHASH.digest(payload, "sha2-256")
        return str(_MF_CID("base32", 1, codec_n, digest))

    # Pure-Python fallback: CIDv1 / multicodec / sha2-256 multihash / base32.
    digest = hashlib.sha256(payload).digest()
    multihash = bytes([0x12, 32]) + digest
    cid_bytes = bytes([0x01]) + _unsigned_varint(_codec_code(codec_n)) + multihash
    encoded = base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")
    return "b" + encoded


def parse_cid_codec(cid: str) -> str:
    """Best-effort codec name for a CID string (defaults to ``raw``)."""
    text = (cid or "").strip()
    if not text:
        raise GraphStoreError("INVALID_REQUEST", "CID must be a non-empty string")

    if _HAVE_MULTIFORMATS:
        try:
            obj = _MF_CID.decode(text)
            codec = obj.codec
            name = getattr(codec, "name", None) or str(codec)
            return normalize_codec(str(name))
        except Exception:
            pass

    # Heuristic for CIDv1 base32 without multiformats: decode and read codec varint.
    if text.startswith("b") and len(text) > 2:
        try:
            pad = (-(len(text) - 1)) % 8
            raw = base64.b32decode(text[1:].upper() + ("=" * pad))
            # version (varint) then codec (varint)
            if raw and raw[0] == 0x01:
                # simple single-byte codecs we care about
                if len(raw) > 1:
                    code = raw[1]
                    if code in _CODE_TO_CODEC:
                        return _CODE_TO_CODEC[code]
                    # dag-json is multi-byte 0x0129 → first byte after version may be 0x80+…
        except Exception:
            pass
    return "raw"


def verify_bytes_against_cid(cid: str, data: bytes, *, expected_codec: Optional[str] = None) -> str:
    """Recompute CID for ``data`` and raise ``INTEGRITY`` on mismatch.

    Returns the normalized expected CID (string form of ``cid``) on success.
    """
    if not isinstance(cid, str) or not cid.strip():
        raise GraphStoreError("INVALID_REQUEST", "CID must be a non-empty string")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise GraphStoreError(
            "INVALID_REQUEST",
            "block data must be bytes-like",
            details={"type": type(data).__name__},
        )
    payload = bytes(data)
    codec = expected_codec or parse_cid_codec(cid)
    try:
        expected = compute_cid_v1(payload, codec=codec)
    except GraphStoreError:
        raise
    except Exception as exc:  # pragma: no cover
        raise GraphStoreError(
            "INTEGRITY",
            "failed to compute CID for verification",
            details={"cid": cid, "error": str(exc)[:300]},
        ) from exc

    # Compare binary forms when multiformats is available to accept base variants.
    if _HAVE_MULTIFORMATS:
        try:
            if bytes(_MF_CID.decode(cid.strip())) == bytes(_MF_CID.decode(expected)):
                return str(_MF_CID.decode(cid.strip()))
        except Exception:
            pass

    if cid.strip() != expected and cid.strip().lower() != expected.lower():
        raise GraphStoreError(
            "INTEGRITY",
            "fetched block bytes do not match CID",
            retryable=False,
            details={
                "cid": cid,
                "expected_cid": expected,
                "codec": codec,
                "size": len(payload),
            },
            cause_code="CID_MISMATCH",
        )
    return expected


def looks_like_cid(value: str) -> bool:
    return bool(isinstance(value, str) and _CID_TEXT_RE.fullmatch(value))


# ---------------------------------------------------------------------------
# DAG-CBOR encode/decode (with pure fallback for maps/lists/scalars)
# ---------------------------------------------------------------------------


def _fallback_cbor_encode(value: Any) -> bytes:
    """Minimal deterministic CBOR for JSON-like values (maps, lists, scalars)."""

    def enc(item: Any) -> bytes:
        if item is None:
            return b"\xf6"
        if item is False:
            return b"\xf4"
        if item is True:
            return b"\xf5"
        if isinstance(item, int) and not isinstance(item, bool):
            if item >= 0:
                return _cbor_uint(0, item)
            return _cbor_uint(1, -1 - item)
        if isinstance(item, float):
            # Encode as 64-bit float.
            import struct

            return b"\xfb" + struct.pack(">d", item)
        if isinstance(item, str):
            raw = item.encode("utf-8")
            return _cbor_uint(3, len(raw)) + raw
        if isinstance(item, (bytes, bytearray)):
            raw = bytes(item)
            return _cbor_uint(2, len(raw)) + raw
        if isinstance(item, list):
            body = b"".join(enc(v) for v in item)
            return _cbor_uint(4, len(item)) + body
        if isinstance(item, dict):
            # DAG-CBOR requires sorted keys by encoded form; we sort by UTF-8 key.
            items = []
            for k, v in item.items():
                if not isinstance(k, str):
                    raise TypeError(f"map keys must be strings, got {type(k).__name__}")
                items.append((enc(k), enc(v)))
            items.sort(key=lambda kv: kv[0])
            body = b"".join(k + v for k, v in items)
            return _cbor_uint(5, len(items)) + body
        raise TypeError(f"unsupported type for DAG-CBOR: {type(item).__name__}")

    return enc(value)


def _cbor_uint(major: int, value: int) -> bytes:
    if value < 0:
        raise ValueError("cbor length cannot be negative")
    if value < 24:
        return bytes([(major << 5) | value])
    if value < 256:
        return bytes([(major << 5) | 24, value])
    if value < 65536:
        return bytes([(major << 5) | 25]) + value.to_bytes(2, "big")
    if value < 2**32:
        return bytes([(major << 5) | 26]) + value.to_bytes(4, "big")
    return bytes([(major << 5) | 27]) + value.to_bytes(8, "big")


def encode_dag_cbor(value: Any) -> bytes:
    """Encode a JSON-like value as canonical DAG-CBOR bytes."""
    try:
        if _HAVE_DAG_CBOR:
            return bytes(_dag_cbor.encode(value))
        return _fallback_cbor_encode(value)
    except GraphStoreError:
        raise
    except Exception as exc:
        raise GraphStoreError(
            "INVALID_REQUEST",
            f"failed to encode DAG-CBOR: {exc}",
            details={"error_class": type(exc).__name__},
        ) from exc


def decode_dag_cbor(data: bytes) -> Any:
    """Decode DAG-CBOR bytes to a Python value."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise GraphStoreError(
            "INVALID_REQUEST",
            "DAG-CBOR input must be bytes",
            details={"type": type(data).__name__},
        )
    payload = bytes(data)
    try:
        if _HAVE_DAG_CBOR:
            return _dag_cbor.decode(payload)
        return _fallback_cbor_decode(payload)
    except GraphStoreError:
        raise
    except Exception as exc:
        raise GraphStoreError(
            "INTEGRITY",
            f"failed to decode DAG-CBOR: {exc}",
            details={"error_class": type(exc).__name__, "size": len(payload)},
            cause_code="DAG_CBOR_DECODE",
        ) from exc


def _fallback_cbor_decode(data: bytes) -> Any:
    value, offset = _fallback_cbor_decode_value(data, 0)
    if offset != len(data):
        raise ValueError("DAG-CBOR contains trailing bytes")
    return value


def _fallback_cbor_decode_value(data: bytes, offset: int) -> Tuple[Any, int]:
    if offset >= len(data):
        raise ValueError("unexpected end of CBOR data")
    initial = data[offset]
    offset += 1
    major = initial >> 5
    info = initial & 0x1F

    def read_len(ai: int, off: int) -> Tuple[int, int]:
        if ai < 24:
            return ai, off
        if ai == 24:
            return data[off], off + 1
        if ai == 25:
            return int.from_bytes(data[off : off + 2], "big"), off + 2
        if ai == 26:
            return int.from_bytes(data[off : off + 4], "big"), off + 4
        if ai == 27:
            return int.from_bytes(data[off : off + 8], "big"), off + 8
        raise ValueError(f"unsupported CBOR additional info {ai}")

    if major == 0:
        n, offset = read_len(info, offset)
        return n, offset
    if major == 1:
        n, offset = read_len(info, offset)
        return -1 - n, offset
    if major == 2:
        n, offset = read_len(info, offset)
        return bytes(data[offset : offset + n]), offset + n
    if major == 3:
        n, offset = read_len(info, offset)
        return data[offset : offset + n].decode("utf-8"), offset + n
    if major == 4:
        n, offset = read_len(info, offset)
        items = []
        for _ in range(n):
            item, offset = _fallback_cbor_decode_value(data, offset)
            items.append(item)
        return items, offset
    if major == 5:
        n, offset = read_len(info, offset)
        mapping: Dict[Any, Any] = {}
        for _ in range(n):
            key, offset = _fallback_cbor_decode_value(data, offset)
            val, offset = _fallback_cbor_decode_value(data, offset)
            mapping[key] = val
        return mapping, offset
    if major == 7:
        if info == 20:
            return False, offset
        if info == 21:
            return True, offset
        if info == 22:
            return None, offset
        if info == 27:
            import struct

            return struct.unpack(">d", data[offset : offset + 8])[0], offset + 8
        raise ValueError(f"unsupported simple/float CBOR info {info}")
    raise ValueError(f"unsupported CBOR major type {major}")


# ---------------------------------------------------------------------------
# CAR encode/decode helpers
# ---------------------------------------------------------------------------


def encode_car(roots: Sequence[str], blocks: Sequence[Tuple[str, bytes]]) -> bytes:
    """Encode a CARv1 archive from root CIDs and (cid, bytes) blocks."""
    if not roots:
        raise GraphStoreError("INVALID_REQUEST", "CAR export requires at least one root CID")
    if _HAVE_IPLD_CAR and _HAVE_MULTIFORMATS:
        root_objs = [_MF_CID.decode(r) for r in roots]
        block_objs = [(_MF_CID.decode(c), b) for c, b in blocks]
        return bytes(_ipld_car.encode(root_objs, block_objs))

    # Minimal CARv1 writer without ipld-car (header + length-prefixed blocks).
    header = encode_dag_cbor({"version": 1, "roots": list(roots)})
    # Note: without multiformats CID objects, we store root strings; Kubo may
    # not accept this CAR. Prefer ipld-car when available (declared dependency).
    out = bytearray()
    out += _unsigned_varint(len(header))
    out += header
    for cid_str, block in blocks:
        if _HAVE_MULTIFORMATS:
            cid_bytes = bytes(_MF_CID.decode(cid_str))
        else:
            # Encode CID text as raw bytes (offline-only interchange).
            cid_bytes = cid_str.encode("utf-8")
        section = cid_bytes + block
        out += _unsigned_varint(len(section))
        out += section
    return bytes(out)


def decode_car(car_bytes: bytes) -> Tuple[List[str], List[Tuple[str, bytes]]]:
    """Decode a CARv1 archive into root CID strings and blocks.

    CID strings are canonicalized to base32 when multiformats is available so
    export/import round trips share one string identity.
    """
    if not isinstance(car_bytes, (bytes, bytearray, memoryview)):
        raise GraphStoreError(
            "INVALID_REQUEST",
            "CAR input must be bytes",
            details={"type": type(car_bytes).__name__},
        )
    payload = bytes(car_bytes)
    if not payload:
        raise GraphStoreError("INVALID_REQUEST", "CAR input is empty")

    if _HAVE_IPLD_CAR:
        try:
            roots_obj, blocks_obj = _ipld_car.decode(payload)
            roots = [canonicalize_cid(r) for r in roots_obj]
            blocks = [(canonicalize_cid(c), bytes(b)) for c, b in blocks_obj]
            return roots, blocks
        except GraphStoreError:
            raise
        except Exception as exc:
            raise GraphStoreError(
                "INTEGRITY",
                f"failed to decode CAR: {exc}",
                details={"error_class": type(exc).__name__},
                cause_code="CAR_DECODE",
            ) from exc

    raise GraphStoreError(
        "NOT_IMPLEMENTED",
        "ipld-car is required to decode CAR archives",
        details={"dependency": "ipld-car"},
    )


def canonicalize_cid(cid: Union[str, Any]) -> str:
    """Normalize a CID to CIDv1 base32 text when multiformats is available."""
    if _HAVE_MULTIFORMATS:
        try:
            if isinstance(cid, str):
                obj = _MF_CID.decode(cid.strip())
            else:
                obj = cid if hasattr(cid, "encode") else _MF_CID.decode(str(cid))
            # Prefer base32 for stable string identity across CAR libraries.
            try:
                return obj.encode("base32")
            except Exception:
                return str(obj)
        except Exception:
            if isinstance(cid, str):
                return cid.strip()
            return str(cid)
    if isinstance(cid, str):
        return cid.strip()
    return str(cid)


def _cid_to_str(cid_obj: Any) -> str:
    return canonicalize_cid(cid_obj)


# ---------------------------------------------------------------------------
# Block stats + backend protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BlockStat:
    """Stat information for a stored block / pin root."""

    cid: str
    size: int
    codec: str
    pinned: bool
    local: bool = True
    backend: str = "memory"
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cid": self.cid,
            "size": self.size,
            "codec": self.codec,
            "pinned": self.pinned,
            "local": self.local,
            "backend": self.backend,
            "extra": dict(self.extra),
        }


@runtime_checkable
class BlockBackend(Protocol):
    """Minimal block + pin surface used by :class:`IPLDGraphStore`."""

    name: str

    def put_block(self, data: bytes, *, codec: str) -> str: ...

    def get_block(self, cid: str) -> bytes: ...

    def has_block(self, cid: str) -> bool: ...

    def pin(self, cid: str) -> None: ...

    def unpin(self, cid: str) -> None: ...

    def is_pinned(self, cid: str) -> bool: ...

    def list_pins(self) -> Sequence[str]: ...

    def close(self) -> None: ...


class InMemoryBlockBackend:
    """Deterministic double: content-addressed map with pin set.

    Optionally persists to ``root_dir`` so a new instance can re-open the same
    blocks after process restart (contract restart/read tests).
    """

    def __init__(self, root_dir: Optional[Union[str, Path]] = None) -> None:
        self.name = "memory"
        self._lock = threading.RLock()
        self._blocks: Dict[str, bytes] = {}
        self._codecs: Dict[str, str] = {}
        self._pins: set[str] = set()
        self._root: Optional[Path] = Path(root_dir) if root_dir is not None else None
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
            self._load()

    # -- persistence -------------------------------------------------------

    def _blocks_dir(self) -> Path:
        assert self._root is not None
        d = self._root / "blocks"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _pins_path(self) -> Path:
        assert self._root is not None
        return self._root / "pins.json"

    def _meta_path(self, cid: str) -> Path:
        return self._blocks_dir() / f"{cid}.meta.json"

    def _block_path(self, cid: str) -> Path:
        return self._blocks_dir() / f"{cid}.bin"

    def _load(self) -> None:
        if self._root is None:
            return
        blocks_dir = self._blocks_dir()
        for path in blocks_dir.glob("*.bin"):
            cid = path.name[: -len(".bin")]
            data = path.read_bytes()
            codec = "raw"
            meta = self._meta_path(cid)
            if meta.is_file():
                try:
                    codec = json.loads(meta.read_text(encoding="utf-8")).get("codec", "raw")
                except Exception:
                    codec = "raw"
            self._blocks[cid] = data
            self._codecs[cid] = codec
        pins_path = self._pins_path()
        if pins_path.is_file():
            try:
                pins = json.loads(pins_path.read_text(encoding="utf-8"))
                if isinstance(pins, list):
                    self._pins = {str(p) for p in pins}
            except Exception:
                self._pins = set()

    def _persist_block(self, cid: str, data: bytes, codec: str) -> None:
        if self._root is None:
            return
        path = self._block_path(cid)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        meta = self._meta_path(cid)
        meta_tmp = meta.with_suffix(".tmp")
        meta_tmp.write_text(json.dumps({"codec": codec}, sort_keys=True), encoding="utf-8")
        os.replace(meta_tmp, meta)

    def _persist_pins(self) -> None:
        if self._root is None:
            return
        path = self._pins_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(self._pins)), encoding="utf-8")
        os.replace(tmp, path)

    # -- BlockBackend ------------------------------------------------------

    def put_block(self, data: bytes, *, codec: str) -> str:
        codec_n = normalize_codec(codec)
        payload = bytes(data)
        cid = compute_cid_v1(payload, codec=codec_n)
        with self._lock:
            self._blocks[cid] = payload
            self._codecs[cid] = codec_n
            self._persist_block(cid, payload, codec_n)
        return cid

    def _resolve_key(self, cid: str) -> Optional[str]:
        """Return the storage key for ``cid``, accepting base variants."""
        if cid in self._blocks:
            return cid
        canon = canonicalize_cid(cid)
        if canon in self._blocks:
            return canon
        # Linear scan for equivalent binary CIDs (rare; small stores / tests).
        if _HAVE_MULTIFORMATS:
            try:
                target = bytes(_MF_CID.decode(cid))
            except Exception:
                return None
            for key in self._blocks:
                try:
                    if bytes(_MF_CID.decode(key)) == target:
                        return key
                except Exception:
                    continue
        return None

    def get_block(self, cid: str) -> bytes:
        with self._lock:
            key = self._resolve_key(cid)
            if key is None:
                raise GraphStoreError(
                    "NOT_FOUND",
                    f"block not found: {cid}",
                    details={"cid": cid, "backend": self.name},
                    cause_code="MEMORY_NOT_FOUND",
                )
            return self._blocks[key]

    def has_block(self, cid: str) -> bool:
        with self._lock:
            return self._resolve_key(cid) is not None

    def pin(self, cid: str) -> None:
        with self._lock:
            key = self._resolve_key(cid)
            if key is None:
                raise GraphStoreError(
                    "NOT_FOUND",
                    f"cannot pin missing block: {cid}",
                    details={"cid": cid},
                )
            self._pins.add(key)
            self._persist_pins()

    def unpin(self, cid: str) -> None:
        with self._lock:
            key = self._resolve_key(cid) or canonicalize_cid(cid)
            self._pins.discard(key)
            self._pins.discard(cid)
            self._persist_pins()

    def is_pinned(self, cid: str) -> bool:
        with self._lock:
            key = self._resolve_key(cid)
            if key is not None and key in self._pins:
                return True
            return cid in self._pins

    def list_pins(self) -> Sequence[str]:
        with self._lock:
            return sorted(self._pins)

    def close(self) -> None:
        return None

    def snapshot_blocks(self) -> Dict[str, bytes]:
        with self._lock:
            return dict(self._blocks)

    def known_cids(self) -> Sequence[str]:
        with self._lock:
            return list(self._blocks.keys())

    def codec_for(self, cid: str) -> Optional[str]:
        with self._lock:
            return self._codecs.get(cid)


class KuboBlockBackend:
    """Kubo CLI backend (``ipfs block put/get``, ``ipfs pin``).

    Used when a real daemon is available. Errors are raised as
    :class:`GraphStoreError` via :func:`map_kubo_error`.
    """

    def __init__(self, cmd: Optional[str] = None) -> None:
        self.name = "kubo"
        self._cmd = cmd or os.getenv("IPFS_DATASETS_PY_KUBO_CMD", "ipfs")
        self._pins: set[str] = set()  # local bookkeeping; Kubo is source of truth

    def _run(self, args: Sequence[str], *, input_bytes: Optional[bytes] = None) -> bytes:
        try:
            proc = subprocess.run(
                [self._cmd, *args],
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GraphStoreError(
                "STORAGE",
                f"ipfs CLI not found: {self._cmd}",
                retryable=False,
                details={"cmd": self._cmd},
                cause_code="KUBO_MISSING",
            ) from exc
        except Exception as exc:
            raise map_kubo_error(exc, operation=" ".join(args)) from exc

        if proc.returncode != 0:
            msg = proc.stderr.decode("utf-8", errors="replace").strip() or "ipfs command failed"
            raise map_kubo_error(RuntimeError(msg), operation=" ".join(args))
        return proc.stdout

    def put_block(self, data: bytes, *, codec: str) -> str:
        codec_n = normalize_codec(codec)
        payload = bytes(data)
        expected = compute_cid_v1(payload, codec=codec_n)
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(payload)
            handle.flush()
            path = handle.name
        try:
            try:
                out = self._run(
                    [
                        "block",
                        "put",
                        "--cid-version",
                        "1",
                        "--format",
                        codec_n,
                        path,
                    ]
                )
            except GraphStoreError as err:
                # Older CLIs may lack flags.
                if "unknown option" in err.message.lower() or "flag provided" in (
                    err.details.get("backend_error") or ""
                ).lower():
                    out = self._run(["block", "put", "--format", codec_n, path])
                else:
                    raise
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        cid = out.decode("utf-8", errors="replace").strip()
        if not cid:
            raise GraphStoreError(
                "STORAGE",
                "kubo block put returned empty CID",
                details={"codec": codec_n},
            )
        # Prefer our deterministic CID if Kubo returns a compatible form.
        try:
            verify_bytes_against_cid(cid, payload, expected_codec=codec_n)
            return cid
        except GraphStoreError:
            # Some Kubo builds may return CIDv0 for raw; keep computed CIDv1
            # as the contract identity when bytes match expected.
            return expected

    def get_block(self, cid: str) -> bytes:
        try:
            return self._run(["block", "get", cid])
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kubo_error(exc, operation="block_get", cid=cid) from exc

    def has_block(self, cid: str) -> bool:
        try:
            self.get_block(cid)
            return True
        except GraphStoreError as err:
            if err.code == "NOT_FOUND":
                return False
            raise

    def pin(self, cid: str) -> None:
        self._run(["pin", "add", cid])
        self._pins.add(cid)

    def unpin(self, cid: str) -> None:
        try:
            self._run(["pin", "rm", cid])
        except GraphStoreError as err:
            # Idempotent unpin: missing pin is not fatal.
            if err.code == "NOT_FOUND":
                self._pins.discard(cid)
                return
            backend = (err.details.get("backend_error") or "").lower()
            if "not pinned" in backend or "not under pin" in backend:
                self._pins.discard(cid)
                return
            raise
        self._pins.discard(cid)

    def is_pinned(self, cid: str) -> bool:
        try:
            out = self._run(["pin", "ls", "--type=recursive", cid])
            text = out.decode("utf-8", errors="replace")
            return cid in text or bool(text.strip())
        except GraphStoreError as err:
            if err.code == "NOT_FOUND":
                return False
            raise

    def list_pins(self) -> Sequence[str]:
        out = self._run(["pin", "ls", "--type=recursive", "--quiet"])
        lines = [ln.strip() for ln in out.decode("utf-8", errors="replace").splitlines() if ln.strip()]
        return lines

    def close(self) -> None:
        return None


def kubo_available(cmd: Optional[str] = None) -> bool:
    """Return True when the Kubo CLI can talk to a running daemon."""
    binary = cmd or os.getenv("IPFS_DATASETS_PY_KUBO_CMD", "ipfs")
    if shutil.which(binary) is None:
        return False
    try:
        proc = subprocess.run(
            [binary, "id"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
        return proc.returncode == 0
    except Exception:
        return False


class RouterBlockBackend:
    """Adapter over :mod:`ipfs_datasets_py.ipfs_backend_router` when present."""

    def __init__(self, backend: Any = None) -> None:
        self.name = "router"
        self._backend = backend
        self._pins: set[str] = set()
        if self._backend is None:
            try:
                from ipfs_datasets_py.ipfs_backend_router import get_ipfs_backend

                self._backend = get_ipfs_backend()
            except Exception as exc:
                raise GraphStoreError(
                    "STORAGE",
                    "ipfs_backend_router unavailable",
                    retryable=False,
                    details={"error": str(exc)[:300]},
                    cause_code="ROUTER_UNAVAILABLE",
                ) from exc

    def put_block(self, data: bytes, *, codec: str) -> str:
        codec_n = normalize_codec(codec)
        payload = bytes(data)
        expected = compute_cid_v1(payload, codec=codec_n)
        try:
            cid = str(self._backend.block_put(payload, codec=codec_n))
        except Exception as exc:
            raise map_kubo_error(exc, operation="block_put") from exc
        try:
            verify_bytes_against_cid(cid, payload, expected_codec=codec_n)
            return cid
        except GraphStoreError:
            return expected

    def get_block(self, cid: str) -> bytes:
        try:
            data = self._backend.block_get(cid)
            return bytes(data)
        except Exception as exc:
            raise map_kubo_error(exc, operation="block_get", cid=cid) from exc

    def has_block(self, cid: str) -> bool:
        try:
            self.get_block(cid)
            return True
        except GraphStoreError as err:
            if err.code == "NOT_FOUND":
                return False
            raise

    def pin(self, cid: str) -> None:
        try:
            self._backend.pin(cid)
        except Exception as exc:
            raise map_kubo_error(exc, operation="pin", cid=cid) from exc
        self._pins.add(cid)

    def unpin(self, cid: str) -> None:
        try:
            self._backend.unpin(cid)
        except Exception as exc:
            err = map_kubo_error(exc, operation="unpin", cid=cid)
            if err.code == "NOT_FOUND":
                self._pins.discard(cid)
                return
            raise err from exc
        self._pins.discard(cid)

    def is_pinned(self, cid: str) -> bool:
        return cid in self._pins

    def list_pins(self) -> Sequence[str]:
        return sorted(self._pins)

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# IPLDGraphStore
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PutResult:
    """Result of a put operation."""

    cid: str
    codec: str
    size: int
    pinned: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cid": self.cid,
            "codec": self.codec,
            "size": self.size,
            "pinned": self.pinned,
        }


class IPLDGraphStore:
    """Direct IPFS/IPLD GraphStore for profile ``ipfs_ipld``.

    Contract surface (shared with KGP-011 ``ipfs_kit`` adapter):

    * ``put`` / ``get`` (typed helpers for manifest, index, raw, CAR)
    * ``stat`` / ``pin`` / ``unpin``
    * ``export_car`` / ``import_car``
    * CID verification after every fetch
    * typed errors via :class:`GraphStoreError`
    """

    storage_profile: str = STORAGE_PROFILE

    def __init__(
        self,
        backend: Optional[BlockBackend] = None,
        *,
        pin_by_default: bool = True,
        cancel_check: Optional[CancelCheck] = None,
        verify_on_fetch: bool = True,
    ) -> None:
        self._backend: BlockBackend = backend if backend is not None else InMemoryBlockBackend()
        self.pin_by_default = pin_by_default
        self._cancel_check = cancel_check
        self.verify_on_fetch = verify_on_fetch
        # Local index of CIDs we authored (aids offline CAR walks).
        self._local_index: Dict[str, str] = {}  # cid -> codec
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def open_memory(cls, **kwargs: Any) -> "IPLDGraphStore":
        return cls(InMemoryBlockBackend(), **kwargs)

    @classmethod
    def open_directory(cls, root_dir: Union[str, Path], **kwargs: Any) -> "IPLDGraphStore":
        """Open a filesystem-backed deterministic store (restart-safe)."""
        return cls(InMemoryBlockBackend(root_dir=root_dir), **kwargs)

    @classmethod
    def open_kubo(cls, cmd: Optional[str] = None, **kwargs: Any) -> "IPLDGraphStore":
        if not kubo_available(cmd):
            raise GraphStoreError(
                "STORAGE",
                "Kubo daemon is not available",
                retryable=True,
                details={"cmd": cmd or "ipfs"},
                cause_code="KUBO_UNAVAILABLE",
            )
        return cls(KuboBlockBackend(cmd=cmd), **kwargs)

    @classmethod
    def open_auto(cls, **kwargs: Any) -> "IPLDGraphStore":
        """Prefer Kubo when available; otherwise deterministic memory backend."""
        if kubo_available():
            try:
                return cls.open_kubo(**kwargs)
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

    # -- cancellation ------------------------------------------------------

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
            raise map_kubo_error(exc, operation="put") from exc

        # Ensure the returned identity matches content addressing.
        cid = verify_bytes_against_cid(cid, payload, expected_codec=codec_n)

        should_pin = self.pin_by_default if pin is None else bool(pin)
        if should_pin:
            self.pin(cid)
        with self._lock:
            self._local_index[cid] = codec_n
        return PutResult(cid=cid, codec=codec_n, size=len(payload), pinned=should_pin)

    def get(self, cid: str, *, expected_codec: Optional[str] = None) -> bytes:
        """Fetch block bytes and verify them against ``cid``."""
        self._check_cancelled()
        if not isinstance(cid, str) or not cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "CID must be a non-empty string")
        cid_n = canonicalize_cid(cid)
        try:
            data = self._backend.get_block(cid_n)
        except GraphStoreError as err:
            # Retry original form if backends stored a non-canonical string.
            if err.code == "NOT_FOUND" and cid_n != cid.strip():
                try:
                    data = self._backend.get_block(cid.strip())
                    cid_n = cid.strip()
                except GraphStoreError:
                    raise err from err
            else:
                raise
        except Exception as exc:
            raise map_kubo_error(exc, operation="get", cid=cid_n) from exc

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
        """Encode ``value`` as DAG-CBOR and store it."""
        encoded = encode_dag_cbor(value)
        return self.put(encoded, codec=DEFAULT_MANIFEST_CODEC, pin=pin)

    def get_dag_cbor(self, cid: str) -> Any:
        """Fetch and decode a DAG-CBOR block (CID-verified)."""
        data = self.get(cid, expected_codec=DEFAULT_MANIFEST_CODEC)
        return decode_dag_cbor(data)

    def put_manifest(
        self,
        manifest: Any,
        *,
        pin: Optional[bool] = None,
    ) -> PutResult:
        """Store a :class:`GraphRevisionManifest` (or mapping) as DAG-CBOR."""
        payload = _manifest_to_mapping(manifest)
        # Force storage profile consistency when present.
        if payload.get("storage_profile") not in (None, STORAGE_PROFILE, "ipfs_ipld", "hybrid"):
            # Allow hybrid roots that point at IPLD payloads; still store as-is.
            pass
        return self.put_dag_cbor(payload, pin=pin)

    def get_manifest(self, cid: str) -> Dict[str, Any]:
        """Fetch a DAG-CBOR manifest and return a plain dict."""
        value = self.get_dag_cbor(cid)
        if not isinstance(value, Mapping):
            raise GraphStoreError(
                "INTEGRITY",
                "manifest block is not a mapping",
                details={"cid": cid, "type": type(value).__name__},
            )
        # Re-validate through the KGP-004 contract when available.
        try:
            from ipfs_datasets_py.knowledge_graphs.contracts.manifest import (
                GraphRevisionManifest,
            )

            return GraphRevisionManifest.from_dict(value).to_dict()
        except ImportError:
            return dict(value)
        except Exception as exc:
            # Integrity/validation failures from the manifest contract.
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
        """Store a canonical index page / descriptor as DAG-CBOR."""
        if not isinstance(index_data, Mapping):
            raise GraphStoreError(
                "INVALID_REQUEST",
                "index_data must be a mapping",
                details={"type": type(index_data).__name__},
            )
        # Canonicalize key order for stable CID identity.
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
        """Store CAR file bytes as a raw content-addressed payload object."""
        if not isinstance(car_bytes, (bytes, bytearray, memoryview)):
            raise GraphStoreError(
                "INVALID_REQUEST",
                "car_bytes must be bytes",
                details={"type": type(car_bytes).__name__},
            )
        payload = bytes(car_bytes)
        if not payload:
            raise GraphStoreError("INVALID_REQUEST", "car_bytes must be non-empty")
        # Validate CAR structure early when decoder is available.
        if _HAVE_IPLD_CAR:
            try:
                decode_car(payload)
            except GraphStoreError as err:
                if err.code == "NOT_IMPLEMENTED":
                    pass
                else:
                    raise
        return self.put(payload, codec=DEFAULT_CAR_CODEC, pin=pin)

    def get_car_object(self, cid: str) -> bytes:
        """Fetch a CAR payload object (CID-verified raw block)."""
        return self.get(cid, expected_codec=DEFAULT_CAR_CODEC)

    def export_car(
        self,
        root_cids: Union[str, Sequence[str]],
        *,
        include_reachable: bool = True,
    ) -> bytes:
        """Export one or more roots (and optionally reachable local blocks) as CAR.

        Offline-capable: walks the local backend / authored index for CID-shaped
        strings inside DAG-CBOR values.
        """
        self._check_cancelled()
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
        """Import a CARv1 archive into the backend; return root CIDs."""
        self._check_cancelled()
        roots, blocks = decode_car(car_bytes)
        for cid, data in blocks:
            # Infer codec from CID when possible.
            try:
                codec = parse_cid_codec(cid)
            except GraphStoreError:
                codec = "raw"
            # Verify block identity before accepting.
            verify_bytes_against_cid(cid, data, expected_codec=codec)
            try:
                stored = self._backend.put_block(data, codec=codec)
            except GraphStoreError:
                raise
            except Exception as exc:
                raise map_kubo_error(exc, operation="import_car", cid=cid) from exc
            # Ensure stored under the CAR's CID identity when possible.
            if stored != cid:
                # Some backends recompute; re-verify under our CID form.
                verify_bytes_against_cid(cid, data, expected_codec=codec)
            with self._lock:
                self._local_index[cid] = codec

        if pin_roots:
            for root in roots:
                try:
                    self.pin(root)
                except GraphStoreError as err:
                    # Root may be a composite CID not present as a single block
                    # in exotic CARs; surface NOT_FOUND, ignore only if block missing
                    # after import (should not happen for well-formed CARs).
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
        try:
            data = self.get(cid)
        except GraphStoreError:
            raise
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
                # Only follow links present locally (offline-safe).
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
        if not isinstance(cid, str) or not cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "CID must be a non-empty string")
        try:
            self._backend.pin(cid)
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kubo_error(exc, operation="pin", cid=cid) from exc

    def unpin(self, cid: str) -> None:
        self._check_cancelled()
        if not isinstance(cid, str) or not cid.strip():
            raise GraphStoreError("INVALID_REQUEST", "CID must be a non-empty string")
        try:
            self._backend.unpin(cid)
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kubo_error(exc, operation="unpin", cid=cid) from exc

    def is_pinned(self, cid: str) -> bool:
        try:
            return bool(self._backend.is_pinned(cid))
        except GraphStoreError:
            raise
        except Exception as exc:
            raise map_kubo_error(exc, operation="is_pinned", cid=cid) from exc

    def stat(self, cid: str) -> BlockStat:
        """Return size/codec/pin status for ``cid`` (fetches + verifies bytes)."""
        self._check_cancelled()
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

    # -- helpers for tests / hybrid layer ----------------------------------

    def has(self, cid: str) -> bool:
        try:
            return bool(self._backend.has_block(cid))
        except GraphStoreError as err:
            if err.code == "NOT_FOUND":
                return False
            raise

    def put_json(
        self,
        value: Any,
        *,
        pin: Optional[bool] = None,
    ) -> PutResult:
        """Store a JSON-serializable value as DAG-CBOR (canonical for IPLD)."""
        return self.put_dag_cbor(value, pin=pin)

    def get_json(self, cid: str) -> Any:
        return self.get_dag_cbor(cid)


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


def _iter_cid_strings(value: Any) -> Iterable[str]:
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


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def create_ipld_graph_store(
    *,
    mode: str = "auto",
    root_dir: Optional[Union[str, Path]] = None,
    backend: Optional[BlockBackend] = None,
    pin_by_default: bool = True,
    cancel_check: Optional[CancelCheck] = None,
) -> IPLDGraphStore:
    """Create an :class:`IPLDGraphStore`.

    Parameters
    ----------
    mode:
        ``auto`` | ``memory`` | ``directory`` | ``kubo`` | ``router``
    root_dir:
        Required for ``directory`` mode; ignored otherwise.
    backend:
        Explicit backend instance (wins over ``mode``).
    """
    if backend is not None:
        return IPLDGraphStore(
            backend,
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
        )
    mode_n = (mode or "auto").strip().lower()
    if mode_n == "memory":
        return IPLDGraphStore.open_memory(
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
        )
    if mode_n == "directory":
        if root_dir is None:
            raise GraphStoreError(
                "INVALID_REQUEST",
                "root_dir is required for directory mode",
            )
        return IPLDGraphStore.open_directory(
            root_dir,
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
        )
    if mode_n == "kubo":
        return IPLDGraphStore.open_kubo(
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
        )
    if mode_n == "router":
        return IPLDGraphStore(
            RouterBlockBackend(),
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
        )
    if mode_n == "auto":
        return IPLDGraphStore.open_auto(
            pin_by_default=pin_by_default,
            cancel_check=cancel_check,
        )
    raise GraphStoreError(
        "INVALID_REQUEST",
        f"unknown store mode: {mode!r}",
        details={"mode": mode},
    )


__all__ = [
    "STORAGE_PROFILE",
    "TYPED_ERROR_CODES",
    "GraphStoreError",
    "BlockStat",
    "PutResult",
    "BlockBackend",
    "InMemoryBlockBackend",
    "KuboBlockBackend",
    "RouterBlockBackend",
    "IPLDGraphStore",
    "compute_cid_v1",
    "canonicalize_cid",
    "verify_bytes_against_cid",
    "encode_dag_cbor",
    "decode_dag_cbor",
    "encode_car",
    "decode_car",
    "map_kubo_error",
    "kubo_available",
    "create_ipld_graph_store",
]
