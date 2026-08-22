from __future__ import annotations

from ipfs_datasets_py.analysis.external_agent_source_state import (
    PLANNING_FOREST_ROOT,
    REPOSITORIES,
    SCHEMA,
    build_source_state_root,
    canonical_cid,
    load_source_forest,
    verify_source_state_root,
)


def test_source_state_root_covers_four_repository_forest() -> None:
    source = load_source_forest()
    bundle = build_source_state_root(source)
    assert bundle["schema"] == SCHEMA
    assert bundle["record"]["planning_source_forest_root"] == PLANNING_FOREST_ROOT
    assert set(bundle["record"]["source_forest_payload"]["repositories"]) == set(
        REPOSITORIES
    )
    assert set(bundle["record"]["selected_integration_roots"]) == set(REPOSITORIES)
    assert set(bundle["record"]["surface_inventory"]) == set(REPOSITORIES)
    for name in REPOSITORIES:
        assert bundle["record"]["surface_inventory"][name]
        for row in bundle["record"]["surface_inventory"][name]:
            assert row["content_cid"].startswith("sha256:")
            if row["path"].endswith(".py"):
                assert row["ast_cid"].startswith("sha256:")


def test_source_state_root_is_independently_verifiable_and_fail_closed() -> None:
    bundle = build_source_state_root()
    verified = verify_source_state_root(bundle)
    assert verified["verified"] is True
    assert verified["source_state_root"] == bundle["source_state_root"]
    assert verified["plan_r2_admitted"] is False
    assert bundle["record"]["plan_r2_admitted"] is False
    assert bundle["record"]["ducklake_authoritative"] is False
    assert bundle["delta"]["post_reconciliation_root"] == bundle["source_state_root"]
    assert canonical_cid(bundle["record"]) == bundle["source_state_root"]
    assert bundle["delta"]["planning_source_forest_root"] == PLANNING_FOREST_ROOT
