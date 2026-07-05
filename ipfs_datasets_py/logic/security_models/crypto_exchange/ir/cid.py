"""Content addressing helpers for security IR artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from ipfs_datasets_py.utils.cid_utils import cid_for_bytes

from .canonicalize import canonicalize_ir
from .schema import SecurityModelIR


def calculate_artifact_cid(payload: Any) -> str:
    """Return a deterministic CID or SHA-256 label for a JSON-like payload."""

    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    try:
        return cid_for_bytes(encoded)
    except Exception:
        return f'sha256:{hashlib.sha256(encoded).hexdigest()}'


def calculate_model_cid(model: SecurityModelIR | Mapping[str, Any]) -> str:
    """Return a deterministic CID for *model*.

    Falls back to ``sha256:<hex>`` when CID dependencies are unavailable.
    TODO: remove the fallback once multiformats is a guaranteed dependency for
    this verification profile.
    """

    payload = canonicalize_ir(model)
    try:
        return cid_for_bytes(payload)
    except Exception:
        return f'sha256:{hashlib.sha256(payload).hexdigest()}'
