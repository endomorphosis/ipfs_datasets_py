"""CIDv1 (raw + sha2-256) helpers. Produces bafkrei... identifiers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


_B32 = "abcdefghijklmnopqrstuvwxyz234567"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _b32encode(data: bytes) -> str:
    bits = 0
    value = 0
    out = []
    for byte in data:
        value = (value << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(_B32[(value >> bits) & 31])
    if bits:
        out.append(_B32[(value << (5 - bits)) & 31])
    return "".join(out)


def cid_v1_raw_sha256(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    cid_bytes = bytes([0x01, 0x55, 0x12, 0x20]) + digest
    return "b" + _b32encode(cid_bytes)


def cid_of_json(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return cid_v1_raw_sha256(payload)


def cid_of_text(*parts: str) -> str:
    blob = "\n".join("" if p is None else str(p) for p in parts).encode("utf-8")
    return cid_v1_raw_sha256(blob)


def file_descriptor(path: Path, relative_path: str, extra: dict | None = None) -> dict:
    data = path.read_bytes()
    desc = {
        "cid": cid_v1_raw_sha256(data),
        "sha256": sha256_hex(data),
        "size_bytes": len(data),
        "relative_path": relative_path,
    }
    if extra:
        desc.update(extra)
    return desc
