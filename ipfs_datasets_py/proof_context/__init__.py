"""Datasets-owned Proof-Carrying Context Engine v0.1 port.

Cold import is inert: no files, sockets, processes, or sibling packages.
Canonical implementations resolve lazily through :mod:`.provider`.
"""

from __future__ import annotations

SCHEMA = "ipfs-datasets.proof-context.v0.1"

__all__ = ["SCHEMA"]
