"""Datasets-owned Proof-Carrying Context Engine v0.1 provider.

This module deliberately exposes only immutable metadata at import time.  The
provider implementation is loaded when a caller asks for it, keeping the
package's proof-context entry point independent of optional datasets backends,
sibling checkouts, and installation side effects.
"""

from __future__ import annotations

SCHEMA = "ipfs-datasets.proof-context.v0.1"
INTERFACE = "DatasetsProofContextProvider@0.1"
PRODUCER = "endomorphosis/ipfs_datasets_py"

__all__ = [
    "SCHEMA",
    "INTERFACE",
    "PRODUCER",
    "DatasetsProofContextProvider",
    "get_provider",
    "load_capability",
]


def __getattr__(name: str):
    """Resolve runtime provider symbols only on explicit access."""

    if name in {"DatasetsProofContextProvider", "get_provider", "load_capability"}:
        from . import provider

        return getattr(provider, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
