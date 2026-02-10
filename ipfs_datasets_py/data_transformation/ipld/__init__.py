"""Canonical IPLD (InterPlanetary Linked Data) API surface.

This package is the canonical import location for IPLD primitives and helpers.

Compatibility note:
Higher-level components (vector store, knowledge graph) are implemented in
their domain packages and are re-exported here opportunistically to preserve
older import paths.
"""

from __future__ import annotations

from .storage import *  # noqa: F403
from .dag_pb import *  # noqa: F403
from .optimized_codec import *  # noqa: F403

# Optional components: keep package import-safe if heavy deps are missing.
try:
    from .vector_store import *  # noqa: F403
except Exception:  # pragma: no cover
    pass

try:
    from .knowledge_graph import *  # noqa: F403
except Exception:  # pragma: no cover
    pass

__all__ = [name for name in globals().keys() if not name.startswith("_")]
