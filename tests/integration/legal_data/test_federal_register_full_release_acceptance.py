"""Fail-closed LCR-071 Federal Register full-live acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.ops.legal_data.run_federal_register_full_release_acceptance as acceptance


def _copy_fixture_workspace(tmp_path: Path) -> Path:
    root = Path(acceptance.REPOSITORY_ROOT)
    workspace = tmp_path / "repo"
    for relpath in (
        acceptance.CANDIDATE_RELPATH,
        acceptance.INVENTORY_RELPATH,
        acceptance.FULLTEXT_RELPATH,
        acceptance.EVALUATION_RELPATH,
        acceptance.ADJACENCY_RELPATH,
    ):
        dest = workspace / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((root / relpath).read_bytes())
    return workspace


def test_current_fixture_candidate_cannot_satisfy_live_official(
    tmp_path: Path,
) -> None:
    workspace = _copy_fixture_workspace(tmp_path)
    with pytest.raises(acceptance.AcceptanceError) as exc:
        acceptance.inspect_production_readiness(
            require_live_official=True,
            require_production_candidate=True,
            repository_root=workspace,
        )
    message = str(exc.value)
    assert "compact recipe" in message or "fixture" in message or "sampled" in message


def test_inspect_without_live_flags_reports_blocked_not_authorizing() -> None:
    report = acceptance.inspect_production_readiness(
        require_live_official=False,
        require_production_candidate=False,
    )
    assert report["authorizing_for_publication"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["task_id"] == "LCR-071"
    assert report["fulltext_compact_recipe"] is True


def test_live_fulltext_exhaustion_does_not_authorize_fixture_candidate(
    tmp_path: Path,
) -> None:
    workspace = _copy_fixture_workspace(tmp_path)
    live_path = workspace / acceptance.LIVE_FULLTEXT_RELPATH
    live_path.parent.mkdir(parents=True, exist_ok=True)
    inventory = json.loads(
        (workspace / acceptance.INVENTORY_RELPATH).read_text(encoding="utf-8")
    )
    official_total = int(inventory["acceptance"]["official_total"])
    live_path.write_text(
        json.dumps(
            {
                "schema": "ipfs_datasets_py/federal-register-fulltext-live-coverage@1",
                "sample_identity": False,
                "compact_recipe": False,
                "classified": official_total,
                "full_text_admitted": official_total,
                "failed_final": 0,
                "authorizing_for_publication": False,
            }
        ),
        encoding="utf-8",
    )
    report = acceptance.inspect_production_readiness(
        require_live_official=False,
        require_production_candidate=False,
        repository_root=workspace,
    )
    assert report["live_fulltext_complete"] is True
    assert report["live_fulltext_admitted"] == report["inventory_official_total"]
    assert report["authorizing_for_publication"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["status"] == "blocked"
    joined = " ".join(report["reasons"]).lower()
    assert "fixture" in joined or "candidate" in joined


def test_cli_require_live_official_exits_nonzero_on_fixture_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _copy_fixture_workspace(tmp_path)
    monkeypatch.setattr(acceptance, "REPOSITORY_ROOT", workspace)
    assert (
        acceptance.main(
            [
                "--full",
                "--require-live-official",
                "--require-production-candidate",
                "--check",
            ]
        )
        == 1
    )


def test_missing_candidate_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acceptance, "REPOSITORY_ROOT", tmp_path)
    with pytest.raises(acceptance.AcceptanceError, match="required receipt is missing"):
        acceptance.inspect_production_readiness(
            require_live_official=True,
            require_production_candidate=True,
            repository_root=tmp_path,
        )


def test_sampled_fulltext_against_live_inventory_is_rejected() -> None:
    root = Path(acceptance.REPOSITORY_ROOT)
    candidate = json.loads((root / acceptance.CANDIDATE_RELPATH).read_text())
    inventory = json.loads((root / acceptance.INVENTORY_RELPATH).read_text())
    fulltext = json.loads((root / acceptance.FULLTEXT_RELPATH).read_text())
    assert candidate["candidate"]["kind"] == "fixture_descriptor_complete"
    assert inventory["acceptance"]["mode"] == "live"
    assert fulltext["compact_recipe"] is True
    assert int(fulltext["fixture"]["inventory_documents"]) < int(
        inventory["acceptance"]["official_total"]
    )


def test_live_identity_sample_checkpoint_cannot_satisfy_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(acceptance.REPOSITORY_ROOT)
    workspace = tmp_path / "repo"
    for relpath in (
        acceptance.CANDIDATE_RELPATH,
        acceptance.INVENTORY_RELPATH,
        acceptance.FULLTEXT_RELPATH,
        acceptance.EVALUATION_RELPATH,
        acceptance.ADJACENCY_RELPATH,
    ):
        dest = workspace / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((root / relpath).read_bytes())
    live_path = workspace / acceptance.LIVE_FULLTEXT_RELPATH
    live_path.parent.mkdir(parents=True, exist_ok=True)
    live_path.write_text(
        json.dumps(
            {
                "schema": "ipfs_datasets_py/federal-register-fulltext-live-checkpoint@1",
                "sample_identity": True,
                "compact_recipe": False,
                "classified": 12,
                "authorizing_for_publication": False,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(acceptance.AcceptanceError) as exc:
        acceptance.inspect_production_readiness(
            require_live_official=True,
            require_production_candidate=True,
            repository_root=workspace,
        )
    message = str(exc.value)
    assert "identity sample" in message or "compact recipe" in message or "fixture" in message


def test_live_receipts_satisfy_production_without_authorizing_hub(
    tmp_path: Path,
) -> None:
    workspace = _copy_fixture_workspace(tmp_path)
    inventory = json.loads(
        (workspace / acceptance.INVENTORY_RELPATH).read_text(encoding="utf-8")
    )
    official_total = int(inventory["acceptance"]["official_total"])
    (workspace / acceptance.LIVE_FULLTEXT_RELPATH).write_text(
        json.dumps(
            {
                "schema": "ipfs_datasets_py/federal-register-fulltext-live-coverage@1",
                "sample_identity": False,
                "compact_recipe": False,
                "classified": official_total,
                "full_text_admitted": official_total,
                "failed_final": 0,
                "authorizing_for_publication": False,
            }
        ),
        encoding="utf-8",
    )
    (workspace / acceptance.LIVE_CANDIDATE_RELPATH).write_text(
        json.dumps(
            {
                "authorizing_for_publication": False,
                "authorizing_hub_upload": False,
                "candidate": {"kind": "live_official_complete"},
                "fixture_only": False,
            }
        ),
        encoding="utf-8",
    )
    (workspace / acceptance.LIVE_EVALUATION_RELPATH).write_text(
        json.dumps(
            {
                "authorizing_for_publication": False,
                "authorizing_hub_upload": False,
                "fixture_only": False,
                "live_canary": False,
                "status": "passed",
                "vector": {"meets_declared_gates": True},
                "gold": {"meets_declared_gates": True},
            }
        ),
        encoding="utf-8",
    )
    (workspace / acceptance.LIVE_ADJACENCY_RELPATH).write_text(
        json.dumps(
            {
                "authorizing_for_publication": False,
                "authorizing_hub_upload": False,
                "fixture_only": False,
                "inversion_holds": True,
            }
        ),
        encoding="utf-8",
    )
    (workspace / acceptance.LIVE_VECTORS_RELPATH).write_text(
        json.dumps(
            {
                "authorizing_hub_upload": False,
                "backend": "sentence_transformers",
                "centroid_bounds_hold": True,
                "fixture_only": False,
                "status": "passed",
                "vector_count": official_total,
            }
        ),
        encoding="utf-8",
    )
    (workspace / acceptance.LIVE_GOLD_RELPATH).write_text(
        json.dumps(
            {
                "authorizing_hub_upload": False,
                "fixture_only": False,
                "status": "passed",
            }
        ),
        encoding="utf-8",
    )
    report = acceptance.inspect_production_readiness(
        require_live_official=True,
        require_production_candidate=True,
        repository_root=workspace,
    )
    assert report["status"] == "passed"
    assert report["candidate_kind"] == "live_official_complete"
    assert report["authorizing_for_publication"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["live_fulltext_complete"] is True
    assert "federal_candidate.live.json" in report["candidate_source"]
    assert "federal_evaluation.live.json" in report["evaluation_source"]
