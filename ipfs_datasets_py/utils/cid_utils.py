from __future__ import annotations

import json
import math
from typing import Any, Iterable


def canonical_json_bytes(obj: Any) -> bytes:
    """Serialize an object into deterministic JSON bytes.

    Notes:
    - Uses sorted keys and compact separators for stable hashing.
    - Assumes `obj` is JSON-serializable.
    """

    text = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=repr,
    )
    return text.encode("utf-8")


def canonical_dag_json_bytes(obj: Any) -> bytes:
    """Serialize strict, deterministic JSON bytes suitable for ``dag-json``.

    Unlike :func:`canonical_json_bytes`, this fail-closed contract does not
    stringify unsupported Python objects and rejects NaN/infinity. It is the
    preferred encoding for new content-addressed protocol artifacts.
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
    """Compute a CID for the given bytes.

    Uses the `multiformats` library (CID + multihash).
    """

    from multiformats import CID, multihash

    mh = multihash.digest(data, mh_type)
    cid = CID(base, version, codec, mh)
    return str(cid)


def cid_for_obj(
    obj: Any,
    *,
    base: str = "base32",
    codec: str = "raw",
    mh_type: str = "sha2-256",
    version: int = 1,
) -> str:
    """Compute a CID for a JSON-serializable object."""

    return cid_for_bytes(
        canonical_json_bytes(obj),
        base=base,
        codec=codec,
        mh_type=mh_type,
        version=version,
    )


def cid_for_dag_json(
    obj: Any,
    *,
    base: str = "base32",
    mh_type: str = "sha2-256",
    version: int = 1,
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
    mh_type: str = "sha2-256",
    version: int = 1,
    base: str = "base32",
) -> str:
    """Validate and return one canonical lowercase CID string."""

    if not isinstance(value, str) or not value or value != value.lower():
        raise ValueError("CID must be a nonempty lowercase string")
    from multiformats import CID, multihash

    try:
        parsed = CID.decode(value)
    except Exception as exc:
        raise ValueError("CID is not decodable") from exc
    allowed_codecs = frozenset(codecs)
    expected_digest_size = multihash.get(mh_type).max_digest_size
    if (
        parsed.version != version
        or parsed.codec.name not in allowed_codecs
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


__all__ = [
    "canonical_dag_json_bytes",
    "canonical_json_bytes",
    "cid_for_bytes",
    "cid_for_dag_json",
    "cid_for_obj",
    "validate_cid",
]
