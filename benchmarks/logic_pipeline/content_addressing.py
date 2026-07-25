"""Side-effect-free CID primitives for the isolated benchmark protocol.

The byte contract intentionally matches
``ipfs_datasets_py.utils.cid_utils.canonical_dag_json_bytes``.  This benchmark
package cannot import that module at runtime because importing the
``ipfs_datasets_py`` package root enables its application-level installer
bootstrap.  Keeping this small bridge local preserves the benchmark's
no-import-side-effects boundary while using the same multiformats standard:
CIDv1, lowercase base32, ``sha2-256`` multihash, ``dag-json`` for structured
objects, and ``raw`` for exact bytes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from typing import Any, Iterable


_CODEC_CODES = {
    "raw": 0x55,
    "dag-json": 0x0129,
}
_SHA2_256_CODE = 0x12
_SHA2_256_SIZE = 32


def _encode_uvarint(value: int) -> bytes:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("unsigned varint value must be a nonnegative integer")
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _decode_uvarint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    start = offset
    while offset < len(data) and shift <= 63:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            if data[start:offset] != _encode_uvarint(value):
                raise ValueError("CID contains a noncanonical varint")
            return value, offset
        shift += 7
    raise ValueError("CID contains a truncated or oversized varint")


def _fallback_cid_for_bytes(data: bytes, *, codec: str) -> str:
    try:
        codec_code = _CODEC_CODES[codec]
    except KeyError as exc:
        raise ValueError(f"unsupported CID codec: {codec!r}") from exc
    digest = hashlib.sha256(data).digest()
    binary = b"".join(
        (
            _encode_uvarint(1),
            _encode_uvarint(codec_code),
            _encode_uvarint(_SHA2_256_CODE),
            _encode_uvarint(len(digest)),
            digest,
        )
    )
    return "b" + base64.b32encode(binary).decode("ascii").rstrip("=").lower()


def _fallback_validate_cid(value: str, *, codecs: Iterable[str]) -> str:
    if not value.startswith("b"):
        raise ValueError("CID must use canonical lowercase base32")
    payload = value[1:]
    if not payload:
        raise ValueError("CID base32 payload is empty")
    padding = "=" * ((8 - len(payload) % 8) % 8)
    try:
        binary = base64.b32decode(
            (payload.upper() + padding).encode("ascii"),
            casefold=False,
        )
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError("CID base32 payload is invalid") from exc
    offset = 0
    parsed_version, offset = _decode_uvarint(binary, offset)
    codec_code, offset = _decode_uvarint(binary, offset)
    hash_code, offset = _decode_uvarint(binary, offset)
    digest_size, offset = _decode_uvarint(binary, offset)
    allowed_codes = {
        _CODEC_CODES[item]
        for item in codecs
        if item in _CODEC_CODES
    }
    if (
        parsed_version != 1
        or codec_code not in allowed_codes
        or hash_code != _SHA2_256_CODE
        or digest_size != _SHA2_256_SIZE
        or len(binary) - offset != digest_size
    ):
        raise ValueError(
            "CID must use the frozen CIDv1/base32/codec/sha2-256 profile"
        )
    canonical_binary = b"".join(
        (
            _encode_uvarint(parsed_version),
            _encode_uvarint(codec_code),
            _encode_uvarint(hash_code),
            _encode_uvarint(digest_size),
            binary[offset:],
        )
    )
    canonical = (
        "b"
        + base64.b32encode(canonical_binary)
        .decode("ascii")
        .rstrip("=")
        .lower()
    )
    if canonical != value:
        raise ValueError("CID is not canonically encoded")
    return value


def canonical_dag_json_bytes(value: Any) -> bytes:
    """Return the strict deterministic DAG-JSON bytes used by semantic v2."""

    _validate_dag_json_value(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _validate_dag_json_value(value: Any, *, path: str = "$") -> None:
    """Require one unambiguous JSON/IPLD data-model value recursively."""

    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(
                f"{path} is not JSON compliant: non-finite number"
            )
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_dag_json_value(item, path=f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(
                    f"{path} contains a non-string DAG-JSON map key"
                )
            _validate_dag_json_value(
                item,
                path=f"{path}.{key}",
            )
        return
    raise TypeError(
        f"{path} is not JSON serializable as DAG-JSON: "
        f"{type(value).__name__}"
    )


def cid_for_bytes(
    data: bytes,
    *,
    base: str = "base32",
    codec: str = "raw",
    mh_type: str = "sha2-256",
    version: int = 1,
) -> str:
    """Return one self-describing CID for exact bytes."""

    if not isinstance(data, bytes):
        raise TypeError("CID input must be bytes")
    if (
        base != "base32"
        or mh_type != "sha2-256"
        or version != 1
        or codec not in _CODEC_CODES
    ):
        raise ValueError(
            "benchmark CID bridge supports only CIDv1/base32, "
            "raw or dag-json, and sha2-256"
        )
    try:
        from multiformats import CID, multihash
    except ImportError:
        return _fallback_cid_for_bytes(data, codec=codec)

    return str(
        CID(
            base,
            version,
            codec,
            multihash.digest(data, mh_type),
        )
    )


def cid_for_dag_json(
    value: Any,
    *,
    base: str = "base32",
    mh_type: str = "sha2-256",
    version: int = 1,
) -> str:
    """Return one CID for the canonical DAG-JSON encoding of ``value``."""

    return cid_for_bytes(
        canonical_dag_json_bytes(value),
        base=base,
        codec="dag-json",
        mh_type=mh_type,
        version=version,
    )


def validate_cid(
    value: Any,
    *,
    codecs: Iterable[str] = ("raw", "dag-json"),
    mh_type: str = "sha2-256",
    version: int = 1,
    base: str = "base32",
) -> str:
    """Return a canonical CID string or reject the wrong multiformats profile."""

    if not isinstance(value, str) or not value or value != value.lower():
        raise ValueError("CID must be a nonempty lowercase string")

    if (
        version != 1
        or base != "base32"
        or mh_type != "sha2-256"
    ):
        raise ValueError(
            "benchmark CID bridge supports only CIDv1/base32/sha2-256"
        )
    accepted_codecs = tuple(codecs)
    if (
        not accepted_codecs
        or any(codec not in _CODEC_CODES for codec in accepted_codecs)
    ):
        raise ValueError("benchmark CID bridge received an unsupported codec")
    try:
        from multiformats import CID, multihash
    except ImportError:
        return _fallback_validate_cid(value, codecs=accepted_codecs)

    try:
        parsed = CID.decode(value)
    except Exception as exc:
        raise ValueError("CID is not decodable") from exc
    expected_digest_size = multihash.get(mh_type).max_digest_size
    if (
        parsed.version != version
        or parsed.codec.name not in frozenset(accepted_codecs)
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


def sha256_digest_for_cid(
    value: Any,
    *,
    codecs: Iterable[str] = ("raw", "dag-json"),
) -> str:
    """Return the SHA-256 multihash digest carried by a validated CID.

    This is a compatibility bridge for frozen receipt schemas that still use
    a bare SHA-256 field.  New identities should retain the full CID because
    it also commits to version, codec, and multihash algorithm.
    """

    canonical = validate_cid(value, codecs=codecs)
    try:
        from multiformats import CID
    except ImportError:
        payload = canonical[1:]
        padding = "=" * ((8 - len(payload) % 8) % 8)
        binary = base64.b32decode(
            (payload.upper() + padding).encode("ascii"),
            casefold=False,
        )
        offset = 0
        _version, offset = _decode_uvarint(binary, offset)
        _codec, offset = _decode_uvarint(binary, offset)
        _hash_code, offset = _decode_uvarint(binary, offset)
        digest_size, offset = _decode_uvarint(binary, offset)
        digest = binary[offset:]
        if len(digest) != digest_size:
            raise ValueError("CID multihash digest length changed")
        return digest.hex()

    return CID.decode(canonical).raw_digest.hex()


__all__ = [
    "canonical_dag_json_bytes",
    "cid_for_bytes",
    "cid_for_dag_json",
    "sha256_digest_for_cid",
    "validate_cid",
]
