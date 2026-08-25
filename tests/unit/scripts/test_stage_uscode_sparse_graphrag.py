"""Unit tests for safe US Code candidate staging dry-run packaging (USCIR-032)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "ops" / "legal_data" / "stage_uscode_sparse_graphrag.py"
FIXTURE = REPO / "tests" / "fixtures" / "legal_ir" / "uscode_stage_plan.json"


def _load_cli():
    assert SCRIPT.is_file(), f"missing staging CLI: {SCRIPT}"
    spec = importlib.util.spec_from_file_location(
        "stage_uscode_sparse_graphrag_uscir032", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_cli()


# ---------------------------------------------------------------------------
# Surfaces exist
# ---------------------------------------------------------------------------


def test_script_and_fixture_exist() -> None:
    assert SCRIPT.is_file()
    assert FIXTURE.is_file()
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["schema"] == "ipfs_datasets_py/uscode-sparse-graphrag-stage-plan@1"
    assert payload["task_id"] == "USCIR-032"
    assert payload["goal_id"] == "USCIR-G080"
    assert payload["target_repo"] == "justicedao/ipfs_uscode"
    assert payload["staging_branch"] == "stage/uscode-sparse-graphrag-v2"
    assert payload["base_revision"] == "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
    assert payload["legacy_files_deleted"] is False
    assert payload["visibility_change_allowed"] is False
    assert payload["operations"] == ["add_only_upload"]
    acceptance = payload["acceptance"]
    assert acceptance["deletion_impossible"] is True
    assert acceptance["force_push_impossible"] is True
    assert acceptance["visibility_change_impossible"] is True
    assert acceptance["credentials_environment_only"] is True
    assert acceptance["mutation_requires_authorization"] is True
    assert "delete" in payload["forbidden_operations"]
    assert "force_push" in payload["forbidden_operations"]
    assert "visibility_change" in payload["forbidden_operations"]


def test_help_exits_zero(cli) -> None:
    assert cli.main(["--help"]) == 0


# ---------------------------------------------------------------------------
# Deterministic fixture dry-run
# ---------------------------------------------------------------------------


def test_fixture_stage_plan_is_deterministic(cli) -> None:
    a = cli.build_fixture_stage_plan()
    b = cli.build_fixture_stage_plan()
    assert a["plan_digest"] == b["plan_digest"]
    assert a["manifest_digest"] == b["manifest_digest"]
    assert a["staged_diff_digest"] == b["staged_diff_digest"]
    assert a["release_root_cid"] == b["release_root_cid"]
    assert a["upload_file_count"] == b["upload_file_count"]
    assert a["upload_bytes"] == b["upload_bytes"]
    # Byte-identical canonical serialization of the binding surface.
    assert a["artifacts"] == b["artifacts"]


def test_fixture_dry_run_receipt_is_deterministic(cli) -> None:
    a = cli.run_fixture_dry_run(check_sealed=True)
    b = cli.run_fixture_dry_run(check_sealed=True)
    assert a["plan_digest"] == b["plan_digest"]
    assert a["manifest_digest"] == b["manifest_digest"]
    assert a["status"] == "dry_run_only"
    assert a["dry_run"] is True
    assert a["live_network"] is False
    assert a["remote_write_contacted"] is False
    assert a["mutation_executed"] is False
    assert a["tokens_used"] is False
    assert a["sealed_fixture_matched"] is True


def test_fixture_plan_has_explicit_target_revision_manifest(cli) -> None:
    plan = cli.build_fixture_stage_plan()
    assert plan["target_repo"] == "justicedao/ipfs_uscode"
    assert plan["staging_branch"] == "stage/uscode-sparse-graphrag-v2"
    assert plan["base_revision"] == cli.PRODUCTION_REVISION
    assert plan["manifest_digest"]
    assert len(plan["manifest_digest"]) == 64
    assert plan["plan_digest"]
    assert plan["release_root_cid"]
    assert plan["manifest_path"] == "manifest.json"
    assert plan["operations"] == ["add_only_upload"]
    assert plan["legacy_files_deleted"] is False
    for art in plan["artifacts"]:
        assert art["operation"] == "add_only_upload"
        assert not str(art["relative_path"]).startswith("/")
        assert ".." not in Path(art["relative_path"]).parts


def test_check_stage_plan_fixture(cli) -> None:
    result = cli.check_stage_plan_fixture()
    assert result["ok"] is True
    assert result["mismatches"] == []
    assert result["target_repo"] == "justicedao/ipfs_uscode"
    assert result["staging_branch"] == "stage/uscode-sparse-graphrag-v2"


def test_main_fixture_only_dry_run(cli, capsys) -> None:
    rc = cli.main(["--fixture-only", "--dry-run"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run_only"
    assert payload["dry_run"] is True
    assert payload["task_id"] == "USCIR-032"
    assert payload["target_repo"] == "justicedao/ipfs_uscode"
    assert payload["staging_branch"] == "stage/uscode-sparse-graphrag-v2"
    assert payload["manifest_digest"]
    assert payload["plan_digest"]
    assert payload["live_network"] is False
    assert payload["mutation_executed"] is False
    assert payload["remote_write_contacted"] is False
    assert payload["visibility_changed"] is False
    assert payload["sealed_fixture_matched"] is True
    # Redacted: no credential keys or env secret values.
    rendered = json.dumps(payload)
    assert "hf_token" not in rendered.casefold()
    assert "access_token" not in rendered.casefold()
    assert "bearer " not in rendered.casefold()
    for env_name in cli.SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val:
            assert env_val not in rendered


# ---------------------------------------------------------------------------
# Safety: deletion / force / visibility impossible
# ---------------------------------------------------------------------------


def test_forbidden_operations_rejected(cli) -> None:
    for op in (
        "delete",
        "force_push",
        "force-push",
        "visibility_change",
        "make_private",
        "direct_main_upload",
    ):
        with pytest.raises(cli.StageSafetyError):
            cli._assert_operations_add_only([op])


def test_plan_rejects_delete_operation_on_artifact(cli) -> None:
    plan = cli.build_fixture_stage_plan()
    plan["artifacts"][0] = dict(plan["artifacts"][0])
    plan["artifacts"][0]["operation"] = "delete"
    with pytest.raises(cli.StageSafetyError):
        cli.assert_safe_stage_plan(plan)


def test_visibility_change_rejected(cli) -> None:
    plan = cli.build_fixture_stage_plan()
    plan["visibility_change_allowed"] = True
    with pytest.raises(cli.StageSafetyError):
        cli.assert_safe_stage_plan(plan)
    plan = cli.build_fixture_stage_plan()
    plan["visibility"] = "private"
    with pytest.raises(cli.StageSafetyError):
        cli.assert_safe_stage_plan(plan)


def test_legacy_delete_flag_rejected(cli) -> None:
    plan = cli.build_fixture_stage_plan()
    plan["legacy_files_deleted"] = True
    with pytest.raises(cli.StageSafetyError):
        cli.assert_safe_stage_plan(plan)


# ---------------------------------------------------------------------------
# Production targets rejected without seal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "branch",
    ["main", "master", "refs/heads/main", "production", "prod", "live"],
)
def test_production_staging_branch_rejected(cli, branch: str) -> None:
    with pytest.raises(cli.StageProductionTargetError):
        cli.assert_non_production_staging_branch(branch)


def test_production_revision_as_branch_rejected(cli) -> None:
    with pytest.raises(cli.StageProductionTargetError):
        cli.assert_non_production_staging_branch(cli.PRODUCTION_REVISION)


def test_production_branch_allowed_only_with_publication_seal(cli) -> None:
    branch = cli.assert_non_production_staging_branch(
        "main", publication_seal="human-seal-fixture-uscir-032"
    )
    assert branch == "main"


def test_plan_from_release_rejects_main_without_seal(cli) -> None:
    release = cli.build_fixture_candidate()
    with pytest.raises(cli.StageProductionTargetError):
        cli.plan_stage_from_release(release, staging_branch="main")


# ---------------------------------------------------------------------------
# Credentials environment-only; no mutation without opt-in
# ---------------------------------------------------------------------------


def test_secrets_on_argv_rejected(cli) -> None:
    with pytest.raises(cli.StageSafetyError):
        cli.reject_secrets_in_argv(["--hf_token=hf_secretvalue1234567890", "--dry-run"])
    with pytest.raises(cli.StageSafetyError):
        cli.reject_secrets_in_argv(["Authorization: Bearer abc", "--fixture-only"])


def test_credentials_in_payload_rejected(cli) -> None:
    with pytest.raises(cli.StageSafetyError):
        cli.reject_credentials_in_payload(
            {"plan_digest": "x", "hf_token": "hf_should_not_appear_here_12345"},
            label="test",
        )


def test_mutation_without_authorization_refused(cli) -> None:
    result = cli.refuse_mutation_without_authorization(authorize_mutation=False)
    assert result["mutation_authorized"] is False
    assert result["mutation_executed"] is False
    assert result["remote_write_contacted"] is False
    assert result["status"] == "mutation_refused"


def test_mutation_requires_env_authorization(cli, monkeypatch) -> None:
    monkeypatch.delenv(cli.AUTHORIZATION_ENV, raising=False)
    with pytest.raises(cli.StageAuthorizationError):
        cli.assert_mutation_authorized(authorize_mutation=True)
    result = cli.refuse_mutation_without_authorization(authorize_mutation=True)
    assert result["mutation_authorized"] is False
    assert result["mutation_executed"] is False


def test_authorized_mutation_still_does_not_execute(cli, monkeypatch) -> None:
    monkeypatch.setenv(cli.AUTHORIZATION_ENV, "operator-staging-auth-fixture")
    result = cli.refuse_mutation_without_authorization(authorize_mutation=True)
    assert result["mutation_authorized"] is True
    assert result["mutation_executed"] is False
    assert result["remote_write_contacted"] is False
    assert result["status"] == "authorized_but_not_executed"


def test_main_mutation_without_auth_is_recorded_not_executed(
    cli, capsys, monkeypatch
) -> None:
    monkeypatch.delenv(cli.AUTHORIZATION_ENV, raising=False)
    rc = cli.main(["--fixture-only", "--dry-run", "--authorize-mutation"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mutation_executed"] is False
    assert payload["remote_write_contacted"] is False
    assert payload["mutation"]["mutation_executed"] is False
    # Authorization value must never appear even when later set.
    monkeypatch.setenv(cli.AUTHORIZATION_ENV, "super-secret-auth-value-xyz")
    rc = cli.main(["--fixture-only", "--dry-run", "--authorize-mutation"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "super-secret-auth-value-xyz" not in out


def test_receipt_has_no_absolute_local_paths(cli) -> None:
    receipt = cli.run_fixture_dry_run(check_sealed=True)
    rendered = json.dumps(receipt)
    assert "/home/" not in rendered
    assert "file://" not in rendered
    # Sealed path is repository-relative.
    assert receipt.get("sealed_fixture_path") == str(cli.DEFAULT_STAGE_PLAN_RELPATH)


def test_main_check_mode(cli, capsys) -> None:
    rc = cli.main(["--fixture-only", "--check"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["mismatches"] == []


def test_main_rejects_production_branch(cli, capsys) -> None:
    rc = cli.main(
        [
            "--fixture-only",
            "--dry-run",
            "--staging-branch",
            "main",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err.casefold()
    assert "production" in err or "main" in err


def test_plan_digest_binds_manifest_and_target(cli) -> None:
    plan = cli.build_fixture_stage_plan()
    other = cli.build_fixture_stage_plan(
        staging_branch="stage/uscode-sparse-graphrag-alt"
    )
    assert plan["plan_digest"] != other["plan_digest"]
    assert plan["manifest_digest"] == other["manifest_digest"]
