"""EAAEF-062: federate existing engines, no duplicate index."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.retrieval.agent_work_federation import ENGINES, FederationError, federate


def test_federates_known_engines() -> None:
    report = federate(({"engine": "ast"}, {"engine": "bm25"}, {"engine": "proof"}))
    assert report["duplicate_index_system"] is False
    assert set(report["engines"]) <= ENGINES


def test_unknown_engine_fails() -> None:
    with pytest.raises(FederationError, match="unknown"):
        federate(({"engine": "mystery"},))
