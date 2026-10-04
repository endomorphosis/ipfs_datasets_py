"""ASEH-031: Datasets sole semantic pack builder."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.proof_context.context_pack import (
    AUTHORITY,
    INTERFACE,
    ContextPackConstructionError,
    DatasetsContextPackAuthority,
    SEMANTIC_BUILDER_ID,
    build_context_pack,
    build_minimal_semantic_pack,
    get_authority,
)
from ipfs_datasets_py.proof_context.provider import get_provider


TREE_OID = "16ef68abe8a35a3033dfaf1ed4e8d6132600df8f"


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _kwargs(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "repository_state_cid": _cid("repo-state"),
        "task_id": "ASEH-031",
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
        "symbol": "helper",
        "cid": _cid("helper"),
        "path": "helper.py",
        "meaning": "pure helper used by target",
    }
    item.update(overrides)
    return item


def test_minimality_excludes_unreferenced_capsules() -> None:
    helper = _cid("helper")
    unused = _cid("unused-whole-repo")
    record = build_minimal_semantic_pack(
        **_kwargs(
            dependencies=[_helper_dep()],
            capsule_cids=(helper, unused),
        )
    )
    payload = record.canonical_payload()
    assert helper in record.capsule_cids
    assert unused not in record.capsule_cids
    assert payload["scope"]["dependency_cone"] == ["helper"]
    assert "unused-whole-repo" not in payload["scope"]["affected_files"]
    identity = build_context_pack(
        **_kwargs(capsule_cids=(helper, unused))
    )
    assert record.pack_cid != identity.pack_cid


def test_source_lineage_binds_required_sources_and_dependencies() -> None:
    helper = _cid("helper")
    record = build_minimal_semantic_pack(
        **_kwargs(dependencies=[_helper_dep()])
    )
    payload = record.canonical_payload()
    identities = payload["freshness_bindings"]["file_and_symbol_identities"]
    assert record.required_source_cids["target_source"] == _cid("target")
    assert record.required_source_cids["surrounding_source"] == _cid("surround")
    assert record.required_source_cids["test_source"] == _cid("test")
    assert any(
        item.startswith("target.py:target@") and item.endswith(_cid("target"))
        for item in identities
    )
    assert any(
        item.startswith("helper.py:helper@") and item.endswith(helper)
        for item in identities
    )
    assert "helper:pure helper used by target" in payload["contracts"][
        "assumptions_and_guarantees"
    ]


def test_deterministic_cid() -> None:
    kwargs = _kwargs(
        dependencies=[_helper_dep()],
        obligations=["cid-round-trip"],
    )
    a = build_minimal_semantic_pack(**kwargs)
    b = build_minimal_semantic_pack(**kwargs)
    authority = DatasetsContextPackAuthority()
    c = authority.build_minimal(**kwargs)
    assert a.pack_cid == b.pack_cid == c.pack_cid
    assert a.verify_identity() == a.pack_cid
    assert a.producer == AUTHORITY
    assert a.canonical_payload()["interface"] == INTERFACE


def test_fixture_live_separation() -> None:
    live = build_minimal_semantic_pack(**_kwargs(dependencies=[_helper_dep()]))
    fixture = build_minimal_semantic_pack(
        **_kwargs(
            dependencies=[_helper_dep()],
            identity_kind="fixture",
            evidence_kind="fixture",
            execution_mode="simulated",
        )
    )
    synthetic = build_minimal_semantic_pack(
        **_kwargs(
            dependencies=[_helper_dep()],
            identity_kind="synthetic",
            evidence_kind="synthetic",
            execution_mode="simulated",
        )
    )
    assert len({live.pack_cid, fixture.pack_cid, synthetic.pack_cid}) == 3
    assert live.canonical_payload()["identity_kind"] == "live"
    assert live.canonical_payload()["evidence_kind"] == "real"
    assert live.canonical_payload()["execution_mode"] == "live"
    assert fixture.canonical_payload()["execution_mode"] == "simulated"
    with pytest.raises(ContextPackConstructionError, match="fixture/live"):
        build_minimal_semantic_pack(
            **_kwargs(
                identity_kind="fixture",
                evidence_kind="fixture",
                execution_mode="live",
            )
        )


def test_completeness_witness_rejects_silent_missing_evidence() -> None:
    witness = _cid("complete")
    complete = build_minimal_semantic_pack(
        **_kwargs(
            dependencies=[_helper_dep()],
            completeness_witness=witness,
        )
    )
    assert complete.canonical_payload()["questions"]["completeness_witness"] == witness
    assert complete.canonical_payload()["questions"]["missing_evidence"] == []
    with pytest.raises(ContextPackConstructionError, match="silent completeness"):
        build_minimal_semantic_pack(
            **_kwargs(
                dependencies=[_helper_dep()],
                missing_evidence=["proof-cid"],
                completeness_witness=witness,
            )
        )
    with pytest.raises(ContextPackConstructionError, match="synthetic identity"):
        build_minimal_semantic_pack(
            **_kwargs(
                identity_kind="synthetic",
                evidence_kind="synthetic",
                execution_mode="simulated",
                completeness_witness=witness,
            )
        )


def test_missing_reference_fails_closed() -> None:
    with pytest.raises(ContextPackConstructionError, match="missing reference"):
        build_minimal_semantic_pack(
            **_kwargs(
                dependencies=[
                    {
                        "symbol": "ghost",
                        "cid": None,
                        "path": "ghost.py",
                        "meaning": "unresolved helper",
                    }
                ]
            )
        )
    named = build_minimal_semantic_pack(
        **_kwargs(
            dependencies=[
                {
                    "symbol": "ghost",
                    "cid": None,
                    "path": "ghost.py",
                    "meaning": "unresolved helper",
                }
            ],
            missing_evidence=["ghost"],
            expansion_references=["ghost"],
        )
    )
    assert named.canonical_payload()["questions"]["missing_evidence"] == ["ghost"]
    assert named.canonical_payload()["questions"]["completeness_witness"] is None
    with pytest.raises(ContextPackConstructionError, match="missing reference"):
        build_minimal_semantic_pack(
            **_kwargs(
                missing_evidence=["ghost"],
                expansion_references=["unnamed-obligation"],
            )
        )
    with pytest.raises(ContextPackConstructionError, match="missing reference"):
        build_minimal_semantic_pack(
            **_kwargs(
                lineage=[
                    {
                        "path": "target.py",
                        "symbol": "target",
                        "cid": _cid("target"),
                        "kind": "target_source",
                    },
                    {
                        "path": "surrounding.py",
                        "symbol": "surrounding",
                        "cid": _cid("surround"),
                        "kind": "surrounding_source",
                    },
                    {
                        "path": "test_target.py",
                        "symbol": "test",
                        "cid": _cid("test"),
                        "kind": "test_source",
                    },
                    {
                        "path": "missing.py",
                        "symbol": "missing",
                        "cid": _cid("not-in-pack"),
                        "kind": "dependency",
                    },
                ]
            )
        )


def test_unknown_field_fails_closed() -> None:
    with pytest.raises(ContextPackConstructionError, match="unknown field"):
        build_minimal_semantic_pack(
            **_kwargs(dependencies=[{**_helper_dep(), "unexpected": "nope"}])
        )
    with pytest.raises(ContextPackConstructionError, match="unknown field"):
        build_minimal_semantic_pack(**_kwargs(unexpected=True))
    with pytest.raises(ContextPackConstructionError, match="unknown field"):
        build_minimal_semantic_pack(
            **_kwargs(
                lineage=[
                    {
                        "path": "target.py",
                        "symbol": "target",
                        "cid": _cid("target"),
                        "kind": "target_source",
                        "extra": True,
                    }
                ]
            )
        )


def test_numeric_bound_fails_closed() -> None:
    complete_budgets = {
        "maximum_bytes": None,
        "maximum_tokens": None,
        "maximum_retrieval_operations": None,
        "maximum_model_class": None,
        "maximum_wall_time": None,
        "validation_reserve_models_cannot_consume": True,
    }
    with pytest.raises(ContextPackConstructionError, match="JSON-safe integer bound"):
        build_minimal_semantic_pack(
            **_kwargs(
                budgets={**complete_budgets, "maximum_tokens": 9_007_199_254_740_992}
            )
        )
    with pytest.raises(ContextPackConstructionError, match="nonnegative integer"):
        build_minimal_semantic_pack(
            **_kwargs(budgets={**complete_budgets, "maximum_tokens": -1})
        )
    with pytest.raises(ContextPackConstructionError, match="nonnegative integer"):
        build_minimal_semantic_pack(
            **_kwargs(budgets={**complete_budgets, "maximum_bytes": 1.25})
        )
    bounded = build_minimal_semantic_pack(
        **_kwargs(
            dependencies=[_helper_dep()],
            budgets={**complete_budgets, "maximum_tokens": 1},
        )
    )
    assert _cid("helper") in bounded.capsule_cids
    assert bounded.canonical_payload()["budgets"]["maximum_tokens"] == 1


def test_execution_mode_is_truthful_not_hardcoded_live() -> None:
    replay = build_minimal_semantic_pack(
        **_kwargs(dependencies=[_helper_dep()], execution_mode="replay")
    )
    simulated = build_minimal_semantic_pack(
        **_kwargs(
            dependencies=[_helper_dep()],
            identity_kind="fixture",
            evidence_kind="fixture",
            execution_mode="simulated",
        )
    )
    assert replay.canonical_payload()["execution_mode"] == "replay"
    assert simulated.canonical_payload()["execution_mode"] == "simulated"
    assert replay.canonical_payload()["execution_mode"] != "live"


def test_budgets_do_not_truncate_or_admit_reuse() -> None:
    with pytest.raises(ContextPackConstructionError, match="Accelerator-owned"):
        build_minimal_semantic_pack(**_kwargs(admit_proof_reuse=True))
    with pytest.raises(ContextPackConstructionError, match="Accelerator-owned"):
        build_minimal_semantic_pack(
            **_kwargs(
                budgets={
                    "maximum_bytes": None,
                    "maximum_tokens": 1,
                    "maximum_retrieval_operations": None,
                    "maximum_model_class": None,
                    "maximum_wall_time": None,
                    "validation_reserve_models_cannot_consume": True,
                    "truncate_to_budget": True,
                }
            )
        )


def test_placeholder_cids_fail_closed() -> None:
    with pytest.raises(ContextPackConstructionError, match="placeholder CID"):
        build_minimal_semantic_pack(**_kwargs(target_source_cid="placeholder-cid"))
    with pytest.raises(ContextPackConstructionError, match="placeholder CID"):
        build_minimal_semantic_pack(
            **_kwargs(dependencies=[_helper_dep(cid="todo-pending-cid")])
        )


def test_provider_is_sole_datasets_builder() -> None:
    provider = get_provider()
    kwargs = _kwargs(dependencies=[_helper_dep()], obligations=["cid-round-trip"])
    via_provider = provider.build_minimal_semantic_pack(**kwargs)
    via_alias = provider.build_context_pack(**kwargs)
    via_module = build_minimal_semantic_pack(**kwargs)
    authority = provider.context_pack_authority()
    via_authority = authority.build_minimal(**kwargs)
    assert via_provider.pack_cid == via_alias.pack_cid == via_module.pack_cid
    assert via_authority.pack_cid == via_module.pack_cid
    assert provider.context_pack_construction_owner == AUTHORITY
    assert provider.semantic_pack_builder.endswith("build_minimal_semantic_pack")
    assert SEMANTIC_BUILDER_ID == "datasets_v01_minimal_semantic_pack"
    assert isinstance(authority, DatasetsContextPackAuthority)
    assert get_authority().interface == INTERFACE
    assert not hasattr(provider, "SupervisorContextPack")
    payload = via_provider.canonical_payload()
    assert payload["identity"]["builder_identity"] == INTERFACE
    assert payload["validation"]["proof_obligations"] == ["cid-round-trip"]
