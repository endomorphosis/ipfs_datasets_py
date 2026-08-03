"""Chaos suite fixtures (KGP-031).

Fault injection always uses isolated temporary stores (pytest tmp_path)
and disposable in-memory IPFS namespaces — never shared production data.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def chaos_tenant() -> str:
    return "tenant-chaos"


@pytest.fixture
def chaos_graph_id() -> str:
    return "graph-chaos-00"
