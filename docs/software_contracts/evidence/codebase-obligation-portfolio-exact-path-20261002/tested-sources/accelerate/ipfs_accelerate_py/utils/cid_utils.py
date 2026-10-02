"""Dependency-free helpers for the supervisor's closed CIDv1 profile.

The launch-time control plane cannot depend on user-site packages.  This
module therefore owns the complete wire implementation for the two admitted
CID codecs instead of importing :mod:`multiformats`:

* CIDv1 encoded as canonical lowercase, unpadded base32 multibase;
* ``raw`` (multicodec ``0x55``) or ``dag-json`` (``0x0129``);
* one ``sha2-256`` multihash (code ``0x12``) with a 32-byte digest.

Decoding is deliberately strict.  Non-minimal or overflowing uvarints,
non-canonical base32, trailing bytes, and every profile deviation fail closed.
The historical generic public API is retained: requests outside that closed
profile lazily delegate to :mod:`multiformats` when it is installed.  The
supervisor never makes such a request, so an external package can neither
approve nor deny sealed execution.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

_CID_VERSION = 1
_CID_BASE = "base32"
_MH_TYPE = "sha2-256"
_MH_CODE = 0x12
_DIGEST_SIZE = 32
_MAX_UVARINT_BYTES = 10
_CODEC_CODES = {"raw": 0x55, "dag-json": 0x0129}
_CODEC_NAMES = {value: key for key, value in _CODEC_CODES.items()}
_LOWER_BASE32_RE = re.compile(r"^[a-z2-7]+$")


@dataclass(frozen=True)
class _DecodedCID:
    version: int
    codec: str
    multihash_type: str
    digest: bytes


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a value into stable legacy JSON bytes.

    This compatibility helper intentionally retains its historical
    ``default=repr`` behavior.  CID-bearing DAG-JSON identities must instead
    use :func:`canonical_dag_json_bytes`, which rejects unsupported objects.
    """

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=repr,
    ).encode("utf-8")


def _validate_dag_json_value(value: Any, *, path: str = "$") -> None:
    """Require one unambiguous JSON/IPLD data-model value recursively."""

    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} is not JSON compliant: non-finite number")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_dag_json_value(item, path=f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"{path} contains a non-string DAG-JSON map key")
            _validate_dag_json_value(item, path=f"{path}.{key}")
        return
    raise TypeError(
        f"{path} is not JSON serializable as DAG-JSON: {type(value).__name__}"
    )


def canonical_dag_json_bytes(obj: Any) -> bytes:
    """Serialize strict, deterministic JSON bytes suitable for ``dag-json``.

    Unlike :func:`canonical_json_bytes`, this fail-closed contract does not
    stringify unsupported Python objects and rejects NaN/infinity.
    """

    _validate_dag_json_value(obj)
    text = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return text.encode("utf-8")


def _encode_uvarint(value: int) -> bytes:
    """Encode one unsigned integer in canonical unsigned LEB128 form."""

    if type(value) is not int or value < 0 or value > (1 << 64) - 1:
        raise ValueError("uvarint value is outside the uint64 domain")
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _decode_uvarint(data: bytes, offset: int) -> tuple[int, int]:
    """Decode exactly one minimal uint64 uvarint starting at ``offset``."""

    if type(data) is not bytes or type(offset) is not int or offset < 0:
        raise ValueError("uvarint input is invalid")
    start = offset
    result = 0
    shift = 0
    for index in range(_MAX_UVARINT_BYTES):
        if offset >= len(data):
            raise ValueError("uvarint is truncated")
        octet = data[offset]
        offset += 1
        if index == _MAX_UVARINT_BYTES - 1 and octet > 0x01:
            raise ValueError("uvarint overflows uint64")
        result |= (octet & 0x7F) << shift
        if octet & 0x80 == 0:
            if data[start:offset] != _encode_uvarint(result):
                raise ValueError("uvarint is not minimally encoded")
            return result, offset
        shift += 7
    raise ValueError("uvarint overflows uint64")


def _base32_multibase_encode(payload: bytes) -> str:
    if type(payload) is not bytes or not payload:
        raise ValueError("CID binary payload must be nonempty bytes")
    encoded = base64.b32encode(payload).decode("ascii").lower().rstrip("=")
    return "b" + encoded


def _base32_multibase_decode(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("CID must be a nonempty lowercase string")
    if value != value.lower():
        raise ValueError("CID must use canonical lowercase base32")
    if not value.startswith("b"):
        raise ValueError("CID must use lowercase base32 multibase")
    payload = value[1:]
    if not payload or _LOWER_BASE32_RE.fullmatch(payload) is None:
        raise ValueError("CID base32 payload is invalid")
    # RFC 4648 unpadded base32 cannot have 1, 3, or 6 residual characters.
    if len(payload) % 8 in {1, 3, 6}:
        raise ValueError("CID base32 payload is truncated")
    padded = payload.upper() + "=" * ((-len(payload)) % 8)
    try:
        decoded = base64.b32decode(padded, casefold=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("CID base32 payload is invalid") from exc
    # Re-encoding catches padding-bit aliases, including nonzero trailing bits.
    if _base32_multibase_encode(decoded) != value:
        raise ValueError("CID base32 payload is not canonical")
    return decoded


def _decode_cid(value: Any) -> _DecodedCID:
    binary = _base32_multibase_decode(value)
    offset = 0
    version, offset = _decode_uvarint(binary, offset)
    codec_code, offset = _decode_uvarint(binary, offset)
    mh_code, offset = _decode_uvarint(binary, offset)
    digest_size, offset = _decode_uvarint(binary, offset)
    digest = binary[offset:]
    codec = _CODEC_NAMES.get(codec_code)
    if version != _CID_VERSION:
        raise ValueError("CID version is not CIDv1")
    if codec is None:
        raise ValueError("CID codec is outside the admitted profile")
    if mh_code != _MH_CODE:
        raise ValueError("CID multihash is not sha2-256")
    if digest_size != _DIGEST_SIZE or len(digest) != _DIGEST_SIZE:
        raise ValueError("CID sha2-256 digest must be exactly 32 bytes")
    # A fixed digest consumes every remaining byte; this also rejects suffixes.
    if offset + digest_size != len(binary):
        raise ValueError("CID contains trailing or truncated digest bytes")
    return _DecodedCID(
        version=version,
        codec=codec,
        multihash_type=_MH_TYPE,
        digest=digest,
    )


def _cid_from_digest(digest: bytes, *, codec: str) -> str:
    if type(digest) is not bytes:
        raise TypeError("sha2-256 digest must be exact bytes")
    if len(digest) != _DIGEST_SIZE:
        raise ValueError("sha2-256 digest must be exactly 32 bytes")
    try:
        codec_code = _CODEC_CODES[codec]
    except (KeyError, TypeError) as exc:
        raise ValueError("codec must be raw or dag-json") from exc
    binary = b"".join(
        (
            _encode_uvarint(_CID_VERSION),
            _encode_uvarint(codec_code),
            _encode_uvarint(_MH_CODE),
            _encode_uvarint(_DIGEST_SIZE),
            digest,
        )
    )
    return _base32_multibase_encode(binary)


def _byteslike_payload(data: bytes | bytearray | memoryview) -> bytes:
    """Normalize the bytes-like domain historically accepted by multihash."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("CID input must be bytes, bytearray, or memoryview")
    return bytes(data)


def _closed_profile(
    *,
    base: str,
    codec: str,
    mh_type: str,
    version: int,
) -> bool:
    return (
        base == _CID_BASE
        and codec in _CODEC_CODES
        and mh_type == _MH_TYPE
        and type(version) is int
        and version == _CID_VERSION
    )


def _external_cid_for_bytes(
    data: bytes | bytearray | memoryview,
    *,
    base: str,
    codec: str,
    mh_type: str,
    version: int,
) -> str:
    """Use the historical generic implementation only outside the seal."""

    from multiformats import CID, multihash

    digest = multihash.digest(data, mh_type)
    return str(CID(base, version, codec, digest))


def cid_for_bytes(
    data: bytes | bytearray | memoryview,
    *,
    base: str = _CID_BASE,
    codec: str = "raw",
    mh_type: str = _MH_TYPE,
    version: int = _CID_VERSION,
) -> str:
    """Compute a CID while keeping the sealed profile dependency-free.

    The exact supervisor profile uses the in-tree fast path.  All other
    profiles retain the original lazy :mod:`multiformats` behavior and its
    exception types.
    """

    if _closed_profile(
        base=base,
        codec=codec,
        mh_type=mh_type,
        version=version,
    ):
        payload = _byteslike_payload(data)
        return _cid_from_digest(hashlib.sha256(payload).digest(), codec=codec)
    return _external_cid_for_bytes(
        data,
        base=base,
        codec=codec,
        mh_type=mh_type,
        version=version,
    )


def cid_from_sha256_digest(
    digest: bytes | bytearray | memoryview,
    *,
    codec: str = "raw",
) -> str:
    """Wrap one already-computed sha2-256 digest without hashing it again."""

    return _cid_from_digest(_byteslike_payload(digest), codec=codec)


def cid_for_obj(
    value: Any,
    *,
    base: str = _CID_BASE,
    codec: str = "raw",
    mh_type: str = _MH_TYPE,
    version: int = _CID_VERSION,
) -> str:
    """Compute a CID for the legacy deterministic JSON representation."""

    return cid_for_bytes(
        canonical_json_bytes(value),
        base=base,
        codec=codec,
        mh_type=mh_type,
        version=version,
    )


def cid_for_dag_json(
    obj: Any,
    *,
    base: str = _CID_BASE,
    mh_type: str = _MH_TYPE,
    version: int = _CID_VERSION,
) -> str:
    """Return a canonical CID for strict deterministic DAG-JSON bytes."""

    return cid_for_bytes(
        canonical_dag_json_bytes(obj),
        base=base,
        codec="dag-json",
        mh_type=mh_type,
        version=version,
    )


def validate_cid(
    value: Any,
    *,
    codecs: Iterable[str] = ("raw", "dag-json"),
    mh_type: str = _MH_TYPE,
    version: int = _CID_VERSION,
    base: str = _CID_BASE,
) -> str:
    """Validate a canonical CID through the closed or generic profile."""

    if not isinstance(value, str) or not value:
        raise ValueError("CID must be a nonempty string")
    allowed = frozenset(codecs)
    closed = (
        mh_type == _MH_TYPE
        and type(version) is int
        and version == _CID_VERSION
        and base == _CID_BASE
        and bool(allowed)
        and allowed.issubset(_CODEC_CODES)
    )
    if closed:
        if value != value.lower():
            raise ValueError("CID must use canonical lowercase base32")
        decoded = _decode_cid(value)
        if decoded.codec not in allowed:
            raise ValueError("CID codec is outside the requested profile")
        return value

    from multiformats import CID, multihash

    try:
        parsed = CID.decode(value)
    except Exception as exc:
        raise ValueError("CID is not decodable") from exc
    expected_digest_size = multihash.get(mh_type).max_digest_size
    if (
        parsed.version != version
        or parsed.codec.name not in allowed
        or parsed.hashfun.name != mh_type
        or (
            expected_digest_size is not None
            and len(parsed.raw_digest) != expected_digest_size
        )
        or parsed.base.name != base
        or str(parsed) != value
    ):
        raise ValueError(
            "CID must use the requested canonical version/base/codec/multihash"
        )
    return value


def digest_bytes_from_cid(
    value: Any,
    *,
    codecs: Iterable[str] = ("raw", "dag-json"),
) -> bytes:
    """Extract the exact digest from a validated admitted CID."""

    validate_cid(value, codecs=codecs)
    return _decode_cid(value).digest


def digest_hex_from_cid(
    value: Any,
    *,
    codecs: Iterable[str] = ("raw", "dag-json"),
) -> str:
    """Extract lowercase sha2-256 hex from a validated admitted CID."""

    return digest_bytes_from_cid(value, codecs=codecs).hex()


__all__ = [
    "canonical_dag_json_bytes",
    "canonical_json_bytes",
    "cid_for_bytes",
    "cid_for_dag_json",
    "cid_for_obj",
    "cid_from_sha256_digest",
    "digest_bytes_from_cid",
    "digest_hex_from_cid",
    "validate_cid",
]
