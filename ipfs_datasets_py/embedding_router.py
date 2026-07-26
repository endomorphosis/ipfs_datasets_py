"""Singular compatibility alias for the canonical embeddings router."""

from __future__ import annotations

import sys as _sys

from ._router_alias import load_accelerator_router as _load_router


_canonical_router = _load_router("embeddings_router")
_sys.modules[__name__] = _canonical_router
