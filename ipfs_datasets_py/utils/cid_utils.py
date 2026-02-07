from __future__ import annotations

import json
from typing import Any


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
