"""PCCE-012: datasets-owned ContextPack construction."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.proof_context.context_pack import (
    AUTHORITY,
    build_context_pack,
)
from ipfs_datasets_py.proof_context.contracts import (
    OpaqueSourceRequiredError,
    StaleContextError,
    UnavailableContextError,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _kwargs(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "repository_state_cid": _cid("repo-state"),
        "task_id": "PCCE-012",
        "target_source_cid": _cid("target"),
        "surrounding_source_cid": _cid("surround"),
        "test_source_cid": _cid("test"),
        "scanned_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "source_tree_oid": "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f",
        "capsule_cids": (_cid("capsule"),),
    }
    fields.update(overrides)
    return fields


def test_identical_inputs_yield_identical_pack_cid() -> None:
    a = build_context_pack(**_kwargs())
    b = build_context_pack(**_kwargs())
    assert a.pack_cid == b.pack_cid
    assert a.producer == AUTHORITY
    assert a.view.context_pack_cid == a.pack_cid
    assert a.required_source_cids["target_source"] == _cid("target")


def test_stale_fails_closed() -> None:
    with pytest.raises(StaleContextError):
        build_context_pack(**_kwargs(freshness="stale"))


def test_unavailable_fails_closed() -> None:
    with pytest.raises(UnavailableContextError):
        build_context_pack(**_kwargs(unavailable=True))


def test_opaque_requires_exact_scanned_tree() -> None:
    with pytest.raises(OpaqueSourceRequiredError):
        build_context_pack(**_kwargs(opaque=True, source_tree_oid="deadbeef"))
    record = build_context_pack(**_kwargs(opaque=True))
    assert record.pack_cid


def test_expansion_flag_is_explicit() -> None:
    record = build_context_pack(**_kwargs())
    assert isinstance(record.expansion_required, bool)
    assert record.sufficiency_state
