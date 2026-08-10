"""Unit tests for US Code immutable staging/rollback handoff rehearsal (USCIR-039).

Acceptance:

* Rehearsal proves both promotion and rollback without deletion.
* Optional real staging evidence is recorded when authorized.
* Absent staging credentials produce a typed pending-external field rather
  than blocking local completion.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "rehearse_uscode_release_handoff.py"
)
_REPORT_PATH = _REPO_ROOT / "docs" / "reports" / "uscode_staging_canary.json"
_RELEASE_CANDIDATE_PATH = (
    _REPO_ROOT / "docs" / "reports" / "uscode_release_candidate.json"
)
_STAGE_PLAN_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_stage_plan.json"
)
_CANARY_FIXTURE_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_remote_canary.json"
)


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing handoff script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "rehearse_uscode_release_handoff_uscir039",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.name is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rh() -> ModuleType:
    return _load_module()


@pytest.fixture(scope="module")
def recipe(rh: ModuleType) -> dict[str, Any]:
    """Sealed compact recipe (also materializes docs/reports/...)."""

    payload, path = rh.materialize_default_report(sealed_recipe=True)
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["task_id"] == payload["task_id"]
    assert on_disk["real_staging"]["kind"] == "pending_external"
    return payload


@pytest.fixture(scope="module")
def handoff(rh: ModuleType) -> dict[str, Any]:
    """Expanded fixture handoff (promotion + rollback + stage + canary)."""

    try:
        return rh.build_fixture_handoff(run_live_canary=True)
    except Exception:
        # Offline policy path still proves promotion/rollback without deletion.
        return rh.build_fixture_handoff(run_live_canary=False)


# ---------------------------------------------------------------------------
# Surfaces exist
# ---------------------------------------------------------------------------


def test_script_and_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    assert _RELEASE_CANDIDATE_PATH.is_file()
    assert _STAGE_PLAN_PATH.is_file()
    assert _CANARY_FIXTURE_PATH.is_file()


def test_help_exits_zero(rh: ModuleType) -> None:
    assert rh.main(["--help"]) == 0


# ---------------------------------------------------------------------------
# Sealed recipe acceptance
# ---------------------------------------------------------------------------


def test_sealed_recipe_acceptance(recipe: dict[str, Any], rh: ModuleType) -> None:
    rh.assert_handoff_safe(recipe)
    assert recipe["task_id"] == "USCIR-039"
    assert recipe["goal_id"] == "USCIR-G100"
    assert recipe["program_id"] == "uscode-sparse-graphrag-v1"
    assert recipe["producer"] == "rehearse_uscode_release_handoff.py"
    assert recipe["schema"] == (
        "ipfs_datasets_py/uscode-sparse-graphrag-staging-canary@1"
    )
    assert recipe["schema_version"] == "uscode-staging-canary/v1"
    assert recipe["fixture_id"] == "uscode-staging-canary-v1"
    assert recipe["publication_authorized"] is False
    assert recipe["network_required"] is False
    assert recipe["dry_run"] is True
    assert recipe["digest_sealed"] is False
    assert recipe["depends_on"] == ["USCIR-038"]
    assert "handoff" in recipe["generators"]
    assert recipe["currentness_disclaimer"]

    acceptance = recipe["acceptance"]
    assert acceptance["promotion_rehearsed"] is True
    assert acceptance["rollback_rehearsed"] is True
    assert acceptance["no_deletion"] is True
    assert acceptance["add_only_upload_planned"] is True
    assert acceptance["immutable_redownload_ok"] is True
    assert acceptance["sparse_canary_ok"] is True
    assert acceptance["compatibility_mapping_switch_ok"] is True
    assert acceptance["prior_mapping_restored"] is True
    assert acceptance["local_completion_not_blocked_by_missing_credentials"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["release_candidate_bound"] is True
    assert acceptance["real_staging_typed"] is True


def test_sealed_report_on_disk_matches_recipe(
    recipe: dict[str, Any], rh: ModuleType
) -> None:
    assert _REPORT_PATH.is_file()
    on_disk = json.loads(_REPORT_PATH.read_text(encoding="utf-8"))
    mismatches = rh.compare_handoffs(recipe, on_disk, recipe_mode=True)
    assert mismatches == []
    result = rh.check_sealed_recipe()
    assert result["ok"] is True
    assert result["mismatches"] == []


# ---------------------------------------------------------------------------
# Expanded handoff: promotion + rollback without deletion
# ---------------------------------------------------------------------------


def test_fixture_handoff_acceptance(handoff: dict[str, Any], rh: ModuleType) -> None:
    rh.assert_handoff_safe(handoff)
    assert handoff["task_id"] == "USCIR-039"
    assert handoff["publication_authorized"] is False
    assert handoff["network_required"] is False
    assert handoff["dry_run"] is True
    assert handoff["receipt_sha256"]
    assert len(handoff["receipt_sha256"]) == 64

    acceptance = handoff["acceptance"]
    assert acceptance["promotion_rehearsed"] is True
    assert acceptance["rollback_rehearsed"] is True
    assert acceptance["no_deletion"] is True
    assert acceptance["add_only_upload_planned"] is True
    assert acceptance["local_completion_not_blocked_by_missing_credentials"] is True
    assert acceptance["real_staging_typed"] is True


def test_promotion_and_rollback_without_deletion(handoff: dict[str, Any]) -> None:
    promotion = handoff["promotion"]
    rollback = handoff["rollback"]

    assert promotion["path"] == "promotion"
    assert promotion["status"] == "rehearsed"
    assert promotion["ok"] is True
    assert promotion["deletion_performed"] is False
    assert promotion["legacy_files_deleted"] is False
    assert promotion["force_push_performed"] is False
    assert promotion["visibility_changed"] is False
    assert promotion["publication_authorized"] is False
    assert promotion["candidate_tree_retained"] is True
    mapping = promotion["advertised_mapping"]
    assert mapping["staging_branch"] == "stage/uscode-sparse-graphrag-v2"
    assert len(mapping["advertised_revision"]) == 40
    assert mapping["default_config"] == "publicus-ir-graphrag/v2"

    assert rollback["path"] == "rollback"
    assert rollback["status"] == "rehearsed"
    assert rollback["ok"] is True
    assert rollback["deletion_performed"] is False
    assert rollback["legacy_files_deleted"] is False
    assert rollback["candidate_tree_retained"] is True
    assert rollback["staging_branch_retained"] is True
    assert rollback["force_push_performed"] is False
    assert rollback["visibility_changed"] is False
    assert len(rollback["prior_advertised_revision"]) == 40
    assert rollback["prior_default_config"] == "publicus-ir-graphrag/v2"
    restored = rollback["restored_mapping"]
    assert restored["advertised_revision"] == rollback["prior_advertised_revision"]
    assert restored["default_config"] == rollback["prior_default_config"]

    switch = handoff["mapping_switch"]
    assert switch["switch_rehearsed"] is True
    assert switch["restore_rehearsed"] is True
    assert switch["no_deletion"] is True


def test_stage_plan_is_add_only(handoff: dict[str, Any]) -> None:
    plan = handoff["stage_plan"]
    assert plan["ok"] is True
    assert plan["operations"] == ["add_only_upload"]
    assert plan["legacy_files_deleted"] is False
    assert plan["visibility_change_allowed"] is False
    assert plan["mutation_executed"] is False
    assert plan["remote_write_contacted"] is False
    assert plan["dry_run"] is True
    assert plan["target_repo"] == "justicedao/ipfs_uscode"
    assert plan["staging_branch"] == "stage/uscode-sparse-graphrag-v2"
    assert plan["manifest_digest"]
    assert len(plan["manifest_digest"]) == 64
    assert plan["plan_digest"]
    assert len(plan["plan_digest"]) == 64
    assert "delete" in plan["forbidden_operations"]
    assert "force_push" in plan["forbidden_operations"]
    assert "visibility_change" in plan["forbidden_operations"]


def test_canary_surface(handoff: dict[str, Any]) -> None:
    canary = handoff["canary"]
    assert canary["ok"] is True
    assert canary["mode"] == "fixture"
    assert canary["network_required"] is False
    assert canary["network_invoked"] is False
    assert canary["immutable_redownload"] is True
    assert canary["sparse_canary"] is True
    assert len(canary["staging_revision"]) == 40
    assert canary["target_repo"] == "justicedao/ipfs_uscode"
    assert canary["path"] == "tests/fixtures/legal_ir/uscode_remote_canary.json"


def test_release_candidate_bound(handoff: dict[str, Any]) -> None:
    rc = handoff["release_candidate"]
    assert rc["task_id"] == "USCIR-038"
    assert rc["path"] == "docs/reports/uscode_release_candidate.json"
    assert rc["receipt_sha256"]
    assert len(rc["rollback_revision"]) == 40
    candidate = handoff["candidate"]
    assert candidate["dataset_id"] == "justicedao/ipfs_uscode"
    assert candidate["manifest_digest"]
    assert len(candidate["revision"]) == 40


def test_expanded_matches_sealed_policy(
    handoff: dict[str, Any], recipe: dict[str, Any], rh: ModuleType
) -> None:
    mismatches = rh.compare_handoffs(handoff, recipe, recipe_mode=True)
    assert mismatches == []


# ---------------------------------------------------------------------------
# pending_external vs authorized evidence
# ---------------------------------------------------------------------------


def test_absent_credentials_yield_pending_external(
    recipe: dict[str, Any],
    handoff: dict[str, Any],
    rh: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for surface in (recipe, handoff):
        real = surface["real_staging"]
        assert real["kind"] == "pending_external"
        assert real["status"] == "pending_external"
        assert real["authorized"] is False
        assert real["mutation_executed"] is False
        assert real["remote_write_contacted"] is False
        assert real["main_published"] is False
        assert real["blocks_local_completion"] is False

    monkeypatch.delenv(rh.AUTHORIZATION_ENV, raising=False)
    for name in rh.SECRET_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    disposition = rh.resolve_real_staging_disposition(authorize_real_staging=False)
    assert disposition["kind"] == rh.PENDING_EXTERNAL_KIND
    assert disposition["blocks_local_completion"] is False
    assert disposition["mutation_executed"] is False


def test_authorized_real_staging_records_evidence(
    rh: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(rh.AUTHORIZATION_ENV, "operator-staging-auth-fixture-uscir-039")
    disposition = rh.resolve_real_staging_disposition(
        authorize_real_staging=True,
        stage_plan={
            "target_repo": "justicedao/ipfs_uscode",
            "staging_branch": "stage/uscode-sparse-graphrag-v2",
            "plan_digest": "a" * 64,
            "manifest_digest": "b" * 64,
        },
    )
    assert disposition["kind"] == rh.AUTHORIZED_EVIDENCE_KIND
    assert disposition["authorized"] is True
    assert disposition["status"] == "authorized_not_executed"
    assert disposition["mutation_executed"] is False
    assert disposition["remote_write_contacted"] is False
    assert disposition["main_published"] is False
    assert disposition["blocks_local_completion"] is False
    assert disposition["staging_branch"] == "stage/uscode-sparse-graphrag-v2"
    rendered = json.dumps(disposition)
    assert "operator-staging-auth-fixture-uscir-039" not in rendered


def test_authorize_without_credentials_fails(
    rh: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(rh.AUTHORIZATION_ENV, raising=False)
    with pytest.raises(rh.HandoffAuthorizationError):
        rh.resolve_real_staging_disposition(authorize_real_staging=True)


def test_external_evidence_injection(rh: ModuleType) -> None:
    disposition = rh.resolve_real_staging_disposition(
        external_evidence={
            "status": "staging_branch_uploaded",
            "mutation_executed": False,
            "remote_write_contacted": True,
            "target_repo": "justicedao/ipfs_uscode",
            "staging_branch": "stage/uscode-sparse-graphrag-v2",
            "staging_revision": "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8",
        }
    )
    assert disposition["kind"] == rh.AUTHORIZED_EVIDENCE_KIND
    assert disposition["remote_write_contacted"] is True
    assert disposition["main_published"] is False
    assert disposition["blocks_local_completion"] is False


def test_pending_external_does_not_block_local_build(
    rh: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(rh.AUTHORIZATION_ENV, raising=False)
    report = rh.build_fixture_handoff(
        run_live_canary=False,
        authorize_real_staging=False,
    )
    assert report["real_staging"]["kind"] == "pending_external"
    assert report["acceptance"]["local_completion_not_blocked_by_missing_credentials"]
    assert report["acceptance"]["promotion_rehearsed"] is True
    assert report["acceptance"]["rollback_rehearsed"] is True
    rh.assert_handoff_safe(report)


# ---------------------------------------------------------------------------
# No secret / path leaks
# ---------------------------------------------------------------------------


def test_report_has_no_secret_or_path_leak(
    recipe: dict[str, Any], handoff: dict[str, Any], rh: ModuleType
) -> None:
    for surface in (recipe, handoff):
        rh.reject_credentials_in_payload(surface, label="test_handoff")
        rh.reject_path_leaks(surface, label="test_handoff")

        rendered = json.dumps(surface)
        assert "hf_token" not in rendered.casefold()
        assert "access_token" not in rendered.casefold()
        assert "bearer " not in rendered.casefold()
        assert "/home/" not in rendered
        assert "file://" not in rendered.casefold()
        assert "C:\\Users" not in rendered
        assert str(_REPO_ROOT) not in rendered

        for env_name in rh.SECRET_ENV_NAMES:
            env_val = os.environ.get(env_name)
            if env_val:
                assert env_val not in rendered

    assert not handoff["release_candidate"]["path"].startswith("/")
    assert not handoff["canary"]["path"].startswith("/")
    assert not handoff["stage_plan"]["path"].startswith("/")


def test_path_leak_rejected(rh: ModuleType) -> None:
    with pytest.raises(rh.HandoffSafetyError):
        rh.reject_path_leaks(
            {"candidate": {"root_label": "/home/operator/secret-tree"}},
            label="test",
        )


def test_credentials_in_payload_rejected(rh: ModuleType) -> None:
    with pytest.raises(rh.HandoffSafetyError):
        rh.reject_credentials_in_payload(
            {"plan_digest": "x", "hf_token": "hf_should_not_appear_here_12345"},
            label="test",
        )


def test_secrets_on_argv_rejected(rh: ModuleType) -> None:
    with pytest.raises(rh.HandoffSafetyError):
        rh.reject_secrets_in_argv(
            ["--hf_token=hf_secretvalue1234567890", "--fixture-only"]
        )
    with pytest.raises(rh.HandoffSafetyError):
        rh.reject_secrets_in_argv(["Authorization: Bearer abc", "--fixture-only"])


# ---------------------------------------------------------------------------
# Fail closed
# ---------------------------------------------------------------------------


def test_promotion_rejects_production_branch(rh: ModuleType) -> None:
    with pytest.raises(rh.HandoffSafetyError):
        rh.rehearse_promotion(
            candidate={
                "revision": "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8",
                "default_config": "publicus-ir-graphrag/v2",
                "staging_branch": "main",
                "dataset_id": "justicedao/ipfs_uscode",
                "manifest_digest": "a" * 64,
            },
            stage_plan={
                "staging_branch": "main",
                "target_repo": "justicedao/ipfs_uscode",
            },
        )


def test_rollback_rejects_legacy_deletion(rh: ModuleType) -> None:
    with pytest.raises(rh.HandoffSafetyError):
        rh.rehearse_rollback(
            candidate={
                "revision": "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8",
                "dataset_id": "justicedao/ipfs_uscode",
            },
            rollback={
                "revision": "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8",
                "default_config": "publicus-ir-graphrag/v2",
                "legacy_files_deleted": True,
            },
        )


def test_tampered_receipt_sha_fails(handoff: dict[str, Any], rh: ModuleType) -> None:
    bad = copy.deepcopy(handoff)
    bad["receipt_sha256"] = "c" * 64
    with pytest.raises(rh.HandoffMismatchError):
        rh.assert_handoff_safe(bad)


def test_publication_authorized_rejected(
    handoff: dict[str, Any], rh: ModuleType
) -> None:
    bad = copy.deepcopy(handoff)
    bad["publication_authorized"] = True
    bad["receipt_sha256"] = rh.digest_mapping(
        {k: v for k, v in bad.items() if k != "receipt_sha256"}
    )
    with pytest.raises(rh.HandoffMismatchError):
        rh.assert_handoff_safe(bad)


def test_missing_release_candidate_fails(rh: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(rh.HandoffMissingInputError):
        rh.load_release_candidate(repo_root=tmp_path)


# ---------------------------------------------------------------------------
# Independent reproducibility
# ---------------------------------------------------------------------------


def test_fixture_handoff_independently_reproducible(rh: ModuleType) -> None:
    a = rh.build_fixture_handoff(run_live_canary=False)
    b = rh.build_fixture_handoff(run_live_canary=False)
    assert a["receipt_sha256"] == b["receipt_sha256"]
    assert a["candidate"]["manifest_digest"] == b["candidate"]["manifest_digest"]
    assert a["stage_plan"]["plan_digest"] == b["stage_plan"]["plan_digest"]
    assert a["promotion"]["status"] == b["promotion"]["status"]
    assert a["rollback"]["status"] == b["rollback"]["status"]
    assert a["real_staging"]["kind"] == b["real_staging"]["kind"] == "pending_external"


def test_sealed_recipe_independently_reproducible(rh: ModuleType) -> None:
    a = rh.build_sealed_canary_recipe()
    b = rh.build_sealed_canary_recipe()
    assert a == b
    assert a["real_staging"]["kind"] == "pending_external"
    assert a["promotion"]["deletion_performed"] is False
    assert a["rollback"]["deletion_performed"] is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_main_fixture_only_dry_run(rh: ModuleType, capsys: Any) -> None:
    rc = rh.main(["--fixture-only", "--dry-run", "--skip-live-canary"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["task_id"] == "USCIR-039"
    assert payload["dry_run"] is True
    assert payload["publication_authorized"] is False
    assert payload["promotion"]["status"] == "rehearsed"
    assert payload["rollback"]["status"] == "rehearsed"
    assert payload["real_staging"]["kind"] == "pending_external"
    assert payload["stage_plan"]["operations"] == ["add_only_upload"]
    assert payload["acceptance"]["no_deletion"] is True
    assert payload["receipt_sha256"]
    rendered = json.dumps(payload)
    assert "hf_token" not in rendered.casefold()
    assert "/home/" not in rendered


def test_main_without_fixture_only_fails(rh: ModuleType) -> None:
    rc = rh.main(["--dry-run"])
    assert rc == 1


def test_main_write_refreshes_recipe(
    rh: ModuleType, tmp_path: Path, capsys: Any
) -> None:
    out_path = tmp_path / "uscode_staging_canary.json"
    rc = rh.main(
        [
            "--fixture-only",
            "--write",
            "--skip-live-canary",
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.is_file()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["task_id"] == "USCIR-039"
    assert payload["digest_sealed"] is False
    assert payload["real_staging"]["kind"] == "pending_external"
    assert payload["generators"]["handoff"] == "build_fixture_handoff()"
    err = capsys.readouterr().err
    assert "wrote staging canary recipe" in err
