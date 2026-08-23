from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from ipfs_datasets_py.analysis import external_agent_source_state as source_state
from ipfs_datasets_py.analysis.external_agent_source_state import (
    PLANNING_FOREST_ROOT,
    REPOSITORIES,
    SCHEMA,
    SURFACE_PATHS,
    build_source_state_root,
    canonical_cid,
    load_source_forest,
    verify_source_state_root,
)

_FROZEN_IDENTITIES = {
    "ipfs_accelerate_py": {
        "commit": "0085dc719686bf4cd077c8099170bdd55fa2cf99",
        "tree": "4298f4b06fa753a60ff8f95ffead39be9a83092c",
    },
    "ipfs_datasets_py": {
        "commit": "41533721c5559ad68cecfe226fa6ba5f76f8a15d",
        "tree": "d88b10b706d91c37e4be346366ff06bb58d1e8a3",
    },
    "ipfs_kit_py": {
        "commit": "2564aea1ae35061f2165872aff91e8a40801ab7e",
        "tree": "98ab8d00f79ec542032dbbb21a1ea416b983a845",
    },
    "Mcp-Plus-Plus": {
        "commit": "5bf87beba3acf18d705c5c8ee3174e5e16ab5e04",
        "tree": "9459e5a6695771e284142577da00aac07370fde8",
    },
}


@pytest.fixture
def four_repository_forest(
    tmp_path: Path,
) -> tuple[dict[str, object], Path, dict[str, Path]]:
    payload = {
        "schema": "ExternalAgentSourceForest@1",
        "repositories": copy.deepcopy(_FROZEN_IDENTITIES),
    }
    assert canonical_cid(payload) == PLANNING_FOREST_ROOT
    source: dict[str, object] = {
        "schema": "SourceReconciliationManifest@1",
        "source_forest_payload": payload,
        "source_forest_root": PLANNING_FOREST_ROOT,
        "selected_integration_roots": copy.deepcopy(_FROZEN_IDENTITIES),
    }
    manifest_path = tmp_path / "source_reconciliation_manifest.json"
    manifest_path.write_text(json.dumps(source), encoding="utf-8")

    roots: dict[str, Path] = {}
    for name in REPOSITORIES:
        root = tmp_path / "repositories" / name
        roots[name] = root
        for relative in SURFACE_PATHS[name]:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".py":
                path.write_text(
                    f'REPOSITORY_SURFACE = "{name}:{relative}"\n',
                    encoding="utf-8",
                )
            else:
                path.write_text(f"{name}:{relative}\n", encoding="utf-8")
    return source, manifest_path, roots


def test_source_state_root_covers_exact_four_repository_forest(
    four_repository_forest: tuple[dict[str, object], Path, dict[str, Path]],
) -> None:
    expected_source, manifest_path, repository_roots = four_repository_forest
    source = load_source_forest(manifest_path)
    assert source == expected_source
    bundle = build_source_state_root(source, repository_roots=repository_roots)
    assert bundle["schema"] == SCHEMA
    assert bundle["record"]["planning_source_forest_root"] == PLANNING_FOREST_ROOT
    assert set(bundle["record"]["source_forest_payload"]["repositories"]) == set(REPOSITORIES)
    assert set(bundle["record"]["selected_integration_roots"]) == set(REPOSITORIES)
    assert set(bundle["record"]["surface_inventory"]) == set(REPOSITORIES)
    for name in REPOSITORIES:
        assert bundle["record"]["surface_inventory"][name]
        for row in bundle["record"]["surface_inventory"][name]:
            assert row["content_cid"].startswith("sha256:")
            if row["path"].endswith(".py"):
                assert row["ast_cid"].startswith("sha256:")


def test_source_state_root_is_independently_verifiable_and_fail_closed(
    four_repository_forest: tuple[dict[str, object], Path, dict[str, Path]],
) -> None:
    _, manifest_path, repository_roots = four_repository_forest
    bundle = build_source_state_root(
        manifest_path=manifest_path,
        repository_roots=repository_roots,
    )
    verified = verify_source_state_root(bundle)
    assert verified["verified"] is True
    assert verified["source_state_root"] == bundle["source_state_root"]
    assert verified["plan_r2_admitted"] is False
    assert bundle["record"]["plan_r2_admitted"] is False
    assert bundle["record"]["ducklake_authoritative"] is False
    assert bundle["delta"]["post_reconciliation_root"] == bundle["source_state_root"]
    assert canonical_cid(bundle["record"]) == bundle["source_state_root"]
    assert bundle["delta"]["planning_source_forest_root"] == PLANNING_FOREST_ROOT

    tampered = copy.deepcopy(bundle)
    tampered["delta"]["changed"] = not tampered["delta"]["changed"]
    with pytest.raises(ValueError, match="delta"):
        verify_source_state_root(tampered)


def test_missing_default_forest_and_incomplete_identity_fail_closed(
    four_repository_forest: tuple[dict[str, object], Path, dict[str, Path]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source, _, repository_roots = four_repository_forest
    missing_manifest = tmp_path / "missing" / "source_reconciliation_manifest.json"
    monkeypatch.setattr(source_state, "_SOURCE_MANIFEST", missing_manifest)
    with pytest.raises(FileNotFoundError, match="manifest_path explicitly"):
        load_source_forest()

    incomplete_source = copy.deepcopy(source)
    del incomplete_source["source_forest_payload"]["repositories"]["Mcp-Plus-Plus"]
    with pytest.raises(ValueError, match="exactly the four"):
        build_source_state_root(
            incomplete_source,
            repository_roots=repository_roots,
        )

    incomplete_roots = dict(repository_roots)
    del incomplete_roots["ipfs_kit_py"]
    with pytest.raises(ValueError, match="exactly the four"):
        build_source_state_root(source, repository_roots=incomplete_roots)
