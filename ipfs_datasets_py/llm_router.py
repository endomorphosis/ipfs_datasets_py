"""Compatibility alias for the canonical accelerator LLM router.

All implementation and mutable router state live in
``ipfs_accelerate_py.llm_router``. Importing this historical datasets path
returns that same module object.
"""

from __future__ import annotations

import sys as _sys

from ._router_alias import load_accelerator_router as _load_router


_canonical_router = _load_router("llm_router")
_sys.modules[__name__] = _canonical_router
