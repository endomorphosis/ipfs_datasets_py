"""Compatibility alias for the canonical accelerator voice router."""

from __future__ import annotations

import sys as _sys

from ._router_alias import load_accelerator_router as _load_router


_canonical_router = _load_router("voice_router")
_sys.modules[__name__] = _canonical_router
