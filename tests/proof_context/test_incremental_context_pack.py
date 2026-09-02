"""ASEH-034: incremental delta and affected-suffix ContextPack expansion."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.proof_context.context_pack import (
    AUTHORITY,
    INCREMENTAL_BUILDER_ID,
    INTERFACE,
    NAMED_MISSING_KINDS,
    TREE_CHANGE_TRIGGER,
    CompletenessFailure,
    ContextPackConstructionError,
    CriticalOmissionError,
    DatasetsContextPackAuthority,
    UnboundParentError,
    build_incremental_semantic_pack,
    build_minimal_semantic_pack,
    compute_incremental_delta_cid,
    get_authority,
)
from ipfs_datasets_py.proof_context.contracts import StaleContextError
from ipfs_datasets_py.proof_context.incremental_context import (
    MissingReferenceError,
    expand_incremental_pack,
    expand_named_missing,
    require_parent_current_tree,
)


TREE_OID = "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f"
CHANGED_TREE = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _kwargs(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "repository_state_cid": _cid("repo-state"),
        "task_id": "ASEH-034",
        "target_source_cid": _cid("target"),
        "surrounding_source_cid": _cid("surround"),
        "test_source_cid": _cid("test"),
        "scanned_tree_oid": TREE_OID,
        "source_tree_oid": TREE_OID,
    }
    fields.update(overrides)
    return fields


def _helper_dep(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "kind": "symbol",
        "name": "helper",
        "cid": _cid("helper"),
        "path": "helper.py",
        "meaning": "pure helper used by target",
    }
    item.update(overrides)
    return item


def _unused_dep() -> dict[str, object]:
    return {
        "kind": "symbol",
        "name": "unused-whole-repo",
        "cid": _cid("unused-whole-repo"),
        "path": "unused.py",
        "meaning": "unreferenced whole-repository member",
    }


def _parent_pack(**overrides: object):
    return build_minimal_semantic_pack(
        **_kwargs(
            dependencies=[
                {
                    "symbol": "prefix_helper",
                    "cid": _cid("prefix-helper"),
                    "path": "a.py",
                    "meaning": "unaffected prefix helper",
                }
            ],
            **overrides,
        )
    )


def test_parent_binding() -> None:
    parent = _parent_pack()
    result = expand_incremental_pack(
        parent=parent,
        scanned_tree_oid=TREE_OID,
        named_missing=["symbol:helper"],
        catalog=[_helper_dep()],
    )
    payload = result.pack.canonical_payload()
    assert result.parent_pack_cid == parent.pack_cid
    assert payload["parent"]["parent_context_pack_cid"] == parent.pack_cid
    assert payload["identity"]["parent_context_pack_cid"] == parent.pack_cid
    assert payload["delta"]["incremental"] is True
    assert payload["delta"]["delta_cid"] == result.delta_cid
    assert payload["delta"]["named_missing"] == ["symbol:helper"]
    assert result.pack_kind == "delta"
    assert result.parent_invalidated is False
    assert result.pack.verify_identity() == result.pack.pack_cid
    via_authority = get_authority().expand_incremental(
        parent=parent,
        scanned_tree_oid=TREE_OID,
        named_missing=[{"kind": "symbol", "name": "helper"}],
        catalog=[_helper_dep()],
    )
    assert via_authority.pack.pack_cid == result.pack.pack_cid
    with pytest.raises(UnboundParentError, match="unbound parent"):
        expand_incremental_pack(
            parent=None,
            scanned_tree_oid=TREE_OID,
            named_missing=["symbol:helper"],
            catalog=[_helper_dep()],
        )
    with pytest.raises((UnboundParentError, ContextPackConstructionError)):
        build_incremental_semantic_pack(
            **_kwargs(
                parent_context_pack_cid="",
                named_missing=["symbol:helper"],
                dependencies=[
                    {
                        "symbol": "helper",
                        "cid": _cid("helper"),
                        "path": "helper.py",
                        "meaning": "pure helper used by target",
                    }
                ],
            )
        )


def test_changed_tree_invalidation() -> None:
    parent = _parent_pack()
    require_parent_current_tree(parent, TREE_OID)
    with pytest.raises(StaleContextError, match="changed tree invalidates"):
        require_parent_current_tree(parent, CHANGED_TREE)
    result = expand_incremental_pack(
        parent=parent,
        scanned_tree_oid=CHANGED_TREE,
        changed_files=["c.py"],
        ordered_files=["a.py", "b.py", "c.py", "d.py"],
        named_missing=["symbol:helper"],
        catalog=[_helper_dep()],
    )
    payload = result.pack.canonical_payload()
    assert result.parent_invalidated is True
    assert result.pack_kind == "affected_suffix"
    assert TREE_CHANGE_TRIGGER in result.invalidation_triggers
    assert TREE_CHANGE_TRIGGER in payload["invalidation"]["invalidation_triggers"]
    assert payload["scanned_tree_oid"] == CHANGED_TREE
    assert payload["parent"]["parent_context_pack_cid"] == parent.pack_cid
    assert parent.pack_cid in payload["history"]["stale_or_invalidated_receipts"]
    assert result.preserved_prefix == ("a.py", "b.py")
    assert result.affected_suffix == ("c.py", "d.py")
    assert "a.py" in payload["scope"]["explicitly_excluded_paths"]
    assert "b.py" in payload["scope"]["explicitly_excluded_paths"]
    assert result.pack.pack_cid != parent.pack_cid
    with pytest.raises(CompletenessFailure, match="whole-repository"):
        expand_incremental_pack(
            parent=parent,
            scanned_tree_oid=CHANGED_TREE,
        )


def test_expansion_precision_and_recall() -> None:
    parent = _parent_pack()
    catalog = [_helper_dep(), _unused_dep()]
    result = expand_incremental_pack(
        parent=parent,
        scanned_tree_oid=TREE_OID,
        named_missing=["symbol:helper"],
        catalog=catalog,
    )
    payload = result.pack.canonical_payload()
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.retrieved == ("symbol:helper",)
    assert result.relevant == ("symbol:helper",)
    assert _cid("helper") in result.pack.capsule_cids
    assert _cid("unused-whole-repo") not in result.pack.capsule_cids
    assert "unused-whole-repo" not in payload["scope"]["dependency_cone"]
    assert "unused.py" not in payload["scope"]["affected_files"]
    assert "helper" in payload["scope"]["dependency_cone"]
    by_kind = {
        kind: expand_named_missing(
            parent,
            [f"{kind}:named-{kind}"],
            [
                {
                    "kind": kind,
                    "name": f"named-{kind}",
                    "cid": _cid(f"named-{kind}"),
                    "path": f"{kind}/{kind}",
                    "meaning": f"named missing {kind}",
                }
            ],
        )
        for kind in NAMED_MISSING_KINDS
        if kind != "cid"
    }
    cid_result = expand_named_missing(
        parent,
        [f"cid:{_cid('named-cid')}"],
        [
            {
                "kind": "cid",
                "name": _cid("named-cid"),
                "cid": _cid("named-cid"),
                "path": "named-cid.py",
                "meaning": "named missing cid",
            }
        ],
    )
    assert cid_result.precision == 1.0 and cid_result.recall == 1.0
    assert all(item.precision == 1.0 and item.recall == 1.0 for item in by_kind.values())
    contract_pack = by_kind["contract"].pack.canonical_payload()
    assert "named-contract" in contract_pack["contracts"]["applicable_api_contracts"]
    test_pack = by_kind["test"].pack.canonical_payload()
    assert "named-test" in test_pack["validation"]["selected_tests"]
    counter_pack = by_kind["counterexample"].pack.canonical_payload()
    assert "named-counterexample" in counter_pack["history"]["relevant_counterexamples"]
    obligation_pack = by_kind["obligation"].pack.canonical_payload()
    assert "named-obligation" in obligation_pack["validation"]["proof_obligations"]


def test_missing_reference() -> None:
    parent = _parent_pack()
    with pytest.raises(MissingReferenceError, match="missing reference"):
        expand_incremental_pack(
            parent=parent,
            scanned_tree_oid=TREE_OID,
            named_missing=["symbol:ghost"],
            catalog=[_helper_dep()],
        )
    with pytest.raises(ContextPackConstructionError, match="missing reference"):
        expand_incremental_pack(
            parent=parent,
            scanned_tree_oid=TREE_OID,
            named_missing=["ghost"],
            catalog=[_helper_dep()],
        )
    with pytest.raises(ContextPackConstructionError, match="missing reference"):
        expand_incremental_pack(
            parent=parent,
            scanned_tree_oid=TREE_OID,
            named_missing=["file:helper.py"],
            catalog=[_helper_dep()],
        )
    with pytest.raises(ContextPackConstructionError, match="unknown field"):
        expand_incremental_pack(
            parent=parent,
            scanned_tree_oid=TREE_OID,
            named_missing=["symbol:helper"],
            catalog=[{**_helper_dep(), "unexpected": "nope"}],
        )
    result = expand_incremental_pack(
        parent=parent,
        scanned_tree_oid=TREE_OID,
        named_missing=["symbol:helper"],
        catalog=[_helper_dep(), _unused_dep()],
    )
    assert "symbol:unused-whole-repo" not in result.retrieved
    assert _cid("unused-whole-repo") not in result.pack.capsule_cids


def test_critical_omission() -> None:
    parent = _parent_pack()
    with pytest.raises(CriticalOmissionError, match="critical omission"):
        expand_incremental_pack(
            parent=parent,
            scanned_tree_oid=CHANGED_TREE,
            changed_files=["c.py"],
            ordered_files=["a.py", "b.py", "c.py", "d.py"],
            catalog=[_helper_dep()],
            critical_dependencies=["helper"],
        )
    result = expand_incremental_pack(
        parent=parent,
        scanned_tree_oid=CHANGED_TREE,
        changed_files=["c.py"],
        ordered_files=["a.py", "b.py", "c.py", "d.py"],
        named_missing=["symbol:helper"],
        catalog=[_helper_dep()],
        critical_dependencies=["helper"],
    )
    assert "symbol:helper" in result.named_missing
    assert result.recall == 1.0
    assert _cid("helper") in result.pack.capsule_cids
    with pytest.raises(CompletenessFailure, match="whole-repository"):
        expand_incremental_pack(
            parent=parent,
            scanned_tree_oid=TREE_OID,
            named_missing=["symbol:helper"],
            catalog=[_helper_dep()],
            whole_repository=True,
        )
    with pytest.raises(CompletenessFailure, match="whole-repository"):
        expand_incremental_pack(
            parent=parent,
            scanned_tree_oid=TREE_OID,
            named_missing=["symbol:whole-repository"],
            catalog=[
                {
                    "kind": "symbol",
                    "name": "whole-repository",
                    "cid": _cid("whole-repository"),
                    "path": "repo.py",
                    "meaning": "illegal whole-repo expansion",
                }
            ],
        )


def test_deterministic_cid() -> None:
    parent = _parent_pack()
    catalog = [_helper_dep(), _unused_dep()]
    kwargs = {
        "parent": parent,
        "scanned_tree_oid": TREE_OID,
        "named_missing": ["symbol:helper"],
        "catalog": catalog,
    }
    a = expand_incremental_pack(**kwargs)
    b = expand_incremental_pack(**kwargs)
    c = expand_incremental_pack(
        parent=parent,
        scanned_tree_oid=TREE_OID,
        named_missing=[{"kind": "symbol", "name": "helper"}],
        catalog=list(reversed(catalog)),
    )
    d = DatasetsContextPackAuthority().expand_incremental(**kwargs)
    assert a.pack.pack_cid == b.pack.pack_cid == c.pack.pack_cid == d.pack.pack_cid
    assert a.delta_cid == b.delta_cid == c.delta_cid
    assert a.pack.producer == AUTHORITY
    assert a.pack.canonical_payload()["interface"] == INTERFACE
    assert a.builder_identity == INCREMENTAL_BUILDER_ID
    derived = compute_incremental_delta_cid(
        parent_context_pack_cid=parent.pack_cid,
        scanned_tree_oid=TREE_OID,
        named_missing=["symbol:helper"],
        pack_kind="delta",
    )
    assert a.delta_cid == derived
    changed = expand_incremental_pack(
        parent=parent,
        scanned_tree_oid=CHANGED_TREE,
        changed_files=["c.py"],
        ordered_files=["a.py", "b.py", "c.py", "d.py"],
        named_missing=["symbol:helper"],
        catalog=[_helper_dep()],
    )
    assert changed.pack.pack_cid != a.pack.pack_cid
    replay = expand_incremental_pack(
        parent=parent.to_dict(),
        scanned_tree_oid=CHANGED_TREE,
        changed_files=["c.py"],
        ordered_files=["a.py", "b.py", "c.py", "d.py"],
        named_missing=["symbol:helper"],
        catalog=[_helper_dep()],
    )
    assert replay.pack.pack_cid == changed.pack.pack_cid
    assert replay.pack.verify_identity() == changed.pack.pack_cid
