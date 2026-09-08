"""PCCE-012: datasets-owned semantic-outcome comparison."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.proof_context.context_pack import build_context_pack
from ipfs_datasets_py.proof_context.contracts import StaleContextError
from ipfs_datasets_py.proof_context.semantic_outcome import (
    SemanticOutcomeError,
    compare_context_packs,
    require_sufficient,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _pack(**overrides: object):
    fields: dict[str, object] = {
        "repository_state_cid": _cid("repo-state"),
        "task_id": "PCCE-012",
        "target_source_cid": _cid("target"),
        "surrounding_source_cid": _cid("surround"),
        "test_source_cid": _cid("test"),
        "scanned_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "source_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
    }
    fields.update(overrides)
    return build_context_pack(**fields)


def test_equal_packs_compare_equal() -> None:
    left = _pack()
    right = _pack()
    result = compare_context_packs(left, right)
    assert result["equal"] is True
    assert result["left_pack_cid"] == left.pack_cid


def test_different_sources_compare_unequal() -> None:
    left = _pack()
    right = _pack(target_source_cid=_cid("other-target"))
    result = compare_context_packs(left, right)
    assert result["equal"] is False


def test_simulated_cannot_be_promoted() -> None:
    live = _pack().identity_payload()
    live["provenance"] = "live"
    fake = dict(live)
    fake["provenance"] = "simulated"
    with pytest.raises(SemanticOutcomeError):
        compare_context_packs(live, fake)


def test_stale_comparison_fails_closed() -> None:
    live = _pack().identity_payload()
    stale = dict(live)
    stale["freshness"] = "stale"
    with pytest.raises(StaleContextError):
        compare_context_packs(live, stale)


def test_require_sufficient_uses_expansion_flag() -> None:
    record = _pack()
    if record.expansion_required:
        with pytest.raises(Exception):
            require_sufficient(record)
    else:
        require_sufficient(record)
