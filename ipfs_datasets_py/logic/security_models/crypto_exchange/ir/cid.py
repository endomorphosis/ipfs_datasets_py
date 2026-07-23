"""Content addressing helpers for security IR artifacts."""

from __future__ import annotations

import hashlib
import json
from importlib import import_module
from typing import Any, Callable, Mapping

from .canonicalize import canonicalize_ir
from .schema import SecurityModelIR


CIDFunction = Callable[[bytes], str]



def _sha256_label(payload: bytes) -> str:
    return f'sha256:{hashlib.sha256(payload).hexdigest()}'



def _load_cid_for_bytes() -> CIDFunction | None:
    """Return ``cid_for_bytes`` when its optional dependencies are importable."""

    try:
        module = import_module('ipfs_datasets_py.utils.cid_utils')
        function = getattr(module, 'cid_for_bytes')
    except (ImportError, AttributeError):
        return None
    return function if callable(function) else None



def _calculate_content_address(payload: bytes) -> str:
    cid_for_bytes = _load_cid_for_bytes()
    if cid_for_bytes is None:
        return _sha256_label(payload)
    try:
        return cid_for_bytes(payload)
    except (ImportError, AttributeError, ModuleNotFoundError, ValueError, TypeError):
        return _sha256_label(payload)



def calculate_artifact_cid(payload: Any) -> str:
    """Return a deterministic CID or SHA-256 label for a JSON-like payload."""

    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    return _calculate_content_address(encoded)



def calculate_model_cid(model: SecurityModelIR | Mapping[str, Any]) -> str:
    """Return a deterministic CID for *model*.

    Falls back to ``sha256:<hex>`` when CID dependencies are unavailable.
    """

    return _calculate_content_address(canonicalize_ir(model))
