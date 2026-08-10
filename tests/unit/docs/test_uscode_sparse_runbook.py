"""Documentation and operator-command contract for USCIR-037.

Acceptance: a new operator can build and query fixtures, diagnose sparse
fetches, rehearse rollback, and distinguish publication date from legal
currentness using the commands documented in:

* docs/guides/USCODE_SPARSE_GRAPHRAG_RUNBOOK.md
* docs/guides/USCODE_SPARSE_GRAPHRAG_MIGRATION.md

All exercised commands are offline fixture / dry-run modes (no network, no
credentials on argv).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
RUNBOOK = REPO / "docs" / "guides" / "USCODE_SPARSE_GRAPHRAG_RUNBOOK.md"
MIGRATION = REPO / "docs" / "guides" / "USCODE_SPARSE_GRAPHRAG_MIGRATION.md"
BUILD_SCRIPT = REPO / "scripts" / "ops" / "legal_data" / "build_uscode_sparse_graphrag.py"
QUERY_SCRIPT = REPO / "scripts" / "ops" / "legal_data" / "query_uscode_hf.py"
STAGE_SCRIPT = REPO / "scripts" / "ops" / "legal_data" / "stage_uscode_sparse_graphrag.py"

PINNED_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
DATASET_REPO = "justicedao/ipfs_uscode"
RELEASE_POINT = "us/pl/118/45"
STAGING_BRANCH = "stage/uscode-sparse-graphrag-v2"
TASK_ID = "USCIR-037"


def _load_script(path: Path, module_name: str):
    assert path.is_file(), f"missing script: {path}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # Ensure repository root is importable for package imports inside scripts.
    root = str(REPO)
    if root not in sys.path:
        sys.path.insert(0, root)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_cli():
    return _load_script(BUILD_SCRIPT, "build_uscode_sparse_graphrag_uscir037")


@pytest.fixture(scope="module")
def query_cli():
    return _load_script(QUERY_SCRIPT, "query_uscode_hf_uscir037")


@pytest.fixture(scope="module")
def stage_cli():
    return _load_script(STAGE_SCRIPT, "stage_uscode_sparse_graphrag_uscir037")


@pytest.fixture(scope="module")
def runbook_text() -> str:
    assert RUNBOOK.is_file(), f"missing runbook: {RUNBOOK}"
    return RUNBOOK.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def migration_text() -> str:
    assert MIGRATION.is_file(), f"missing migration guide: {MIGRATION}"
    return MIGRATION.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Document surfaces
# ---------------------------------------------------------------------------


def test_expected_outputs_exist(runbook_text: str, migration_text: str) -> None:
    assert RUNBOOK.is_file()
    assert MIGRATION.is_file()
    assert TASK_ID in runbook_text
    assert TASK_ID in migration_text
    assert "USCIR-G100" in runbook_text


def test_runbook_documents_operator_capabilities(runbook_text: str) -> None:
    text = runbook_text.casefold()
    # Build / query fixtures
    assert "build_uscode_sparse_graphrag.py" in runbook_text
    assert "--fixture-only" in runbook_text
    assert "query_uscode_hf.py" in runbook_text
    assert "--local-root" in runbook_text
    assert "--trace" in runbook_text
    # Sparse fetch diagnosis
    assert "fetch_trace" in runbook_text
    assert "route_justified" in runbook_text
    assert "sparse" in text
    # Rollback rehearsal
    assert "rollback" in text
    assert "stage_uscode_sparse_graphrag.py" in runbook_text
    assert "--dry-run" in runbook_text
    assert "without deleting legacy data" in text
    # Legal currentness vs publication date
    assert "publication date" in text or "publication timestamps" in text
    assert "legal currentness" in text or "legal-currentness" in text
    assert "research aid" in text
    assert RELEASE_POINT in runbook_text
    assert PINNED_REVISION in runbook_text
    assert DATASET_REPO in runbook_text


def test_runbook_has_no_embedded_credentials(runbook_text: str) -> None:
    lowered = runbook_text.casefold()
    # Document may name env vars, but must not embed token values or argv secrets.
    assert "hf_token=" not in lowered
    assert "authorization: bearer" not in lowered
    assert "bearer hf_" not in lowered
    # No private key blocks.
    assert "-----begin" not in lowered


def test_runbook_documents_resource_sizing_and_provenance(runbook_text: str) -> None:
    text = runbook_text.casefold()
    assert "resource" in text
    assert "max-bytes" in runbook_text or "--max-bytes" in runbook_text
    assert "release_point" in runbook_text or "release point" in text
    assert "entry_cid" in runbook_text
    assert "admission" in text


def test_runbook_documents_failure_triage(runbook_text: str) -> None:
    text = runbook_text.casefold()
    assert "triage" in text or "symptom" in text
    assert "mutable" in text
    assert "digest" in text
    assert "budget" in text


def test_migration_documents_legacy_configs_and_client_path(
    migration_text: str,
) -> None:
    text = migration_text.casefold()
    assert "publicus-ir-graphrag/v2" in migration_text
    assert "legacy-uscode-parquet/v1" in migration_text
    assert "recovery-quarantine/v1" in migration_text
    assert "uscode_parquet" in migration_text
    assert "entry_cid" in migration_text
    assert "never delete" in text or "never deletes" in text
    assert "positional" in text
    assert DATASET_REPO in migration_text
    assert PINNED_REVISION in migration_text
    assert "query_uscode_hf.py" in migration_text
    assert "stage_uscode_sparse_graphrag.py" in migration_text
    assert "publication date" in text or "publication timestamps" in text
    assert "legal currentness" in text or "legal-currentness" in text
    assert STAGING_BRANCH in migration_text


def test_migration_rejects_mutable_revision_pattern(migration_text: str) -> None:
    text = migration_text.casefold()
    assert "main" in text
    assert "latest" in text
    assert "40-hex" in text or "immutable" in text


def test_docs_cross_link(runbook_text: str, migration_text: str) -> None:
    assert "USCODE_SPARSE_GRAPHRAG_MIGRATION.md" in runbook_text
    assert "USCODE_SPARSE_GRAPHRAG_RUNBOOK.md" in migration_text


def test_documented_commands_appear_as_fenced_blocks(runbook_text: str) -> None:
    """Key operator commands must appear in copy-pasteable fenced blocks."""
    fences = re.findall(r"```(?:bash|shell)?\n(.*?)```", runbook_text, flags=re.S)
    joined = "\n".join(fences)
    assert "build_uscode_sparse_graphrag.py" in joined
    assert "--fixture-only" in joined
    assert "--plan-only" in joined or "--validation-only" in joined
    assert "query_uscode_hf.py" in joined
    assert "--trace" in joined
    assert "stage_uscode_sparse_graphrag.py" in joined
    assert "--dry-run" in joined


# ---------------------------------------------------------------------------
# Tested operator commands (fixture / dry-run)
# ---------------------------------------------------------------------------


def test_operator_can_build_fixture_plan(build_cli, capsys) -> None:
    """Runbook §5.1 — plan-only fixture build."""
    rc = build_cli.main(
        [
            "--fixture-only",
            "--plan-only",
            "--titles",
            "1,35",
            "--mode",
            "full",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task_id"] == "USCIR-030"
    plan = payload["plan"]
    assert plan["mode"] == "full"
    assert plan.get("config_digest")
    assert int(plan.get("unit_count") or 0) > 0
    changed = list(plan.get("changed_titles") or [])
    assert "1" in changed
    assert "35" in changed


def test_operator_can_validation_only_fixture_build(
    build_cli, capsys, tmp_path: Path
) -> None:
    """Runbook §5.2 — validation-only fixture build (no sealed partial output)."""
    out = tmp_path / "uscode-build"
    rc = build_cli.main(
        [
            "--fixture-only",
            "--validation-only",
            "--titles",
            "1,35",
            "--mode",
            "full",
            "--output-dir",
            str(out),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task_id"] == "USCIR-030"
    assert payload["validation_only"] is True
    # Validation-only may compute an in-memory seal but must not persist paths.
    assert payload.get("checkpoint_path") in ("", None)
    assert payload.get("seal_path") in ("", None)
    assert not (out / ".checkpoints").exists()


def test_operator_can_query_fixture_and_diagnose_sparse_fetch(
    query_cli, tmp_path: Path, capsys
) -> None:
    """Runbook §6 + §7 — offline query with fetch_trace diagnosis."""
    from tests.unit.retrieval.hf_graphrag.test_query import build_mini_release

    release = tmp_path / "release"
    release.mkdir()
    build_mini_release(release)

    rc = query_cli.main(
        [
            "--local-root",
            str(release),
            "--revision",
            PINNED_REVISION,
            "--fixture-mode",
            "--json",
            "--trace",
            "bm25",
            "foia agency",
            "--top-k",
            "3",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("mode") == "bm25"
    assert "results" in payload

    trace = payload.get("fetch_trace")
    assert isinstance(trace, dict), "fetch_trace required for sparse-fetch diagnosis"
    # Diagnostic fields documented in the runbook.
    assert "files" in trace or "file_count" in trace or "total_file_bytes" in trace
    if "route_justified" in trace:
        assert trace["route_justified"] is True
    if "verification_state" in trace:
        assert trace["verification_state"] in {"verified", "empty"}
    # Credential safety: no tokens in operator-facing JSON.
    rendered = json.dumps(payload)
    assert "hf_token" not in rendered.casefold()
    assert "bearer " not in rendered.casefold()
    for env_name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        env_val = os.environ.get(env_name)
        if env_val:
            assert env_val not in rendered


def test_operator_can_rehearse_rollback_via_stage_dry_run(
    stage_cli, capsys
) -> None:
    """Runbook §8 — staging dry-run is the local rollback rehearsal basis."""
    rc = stage_cli.main(["--fixture-only", "--dry-run"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run_only"
    assert payload["dry_run"] is True
    assert payload["live_network"] is False
    assert payload["mutation_executed"] is False
    assert payload["remote_write_contacted"] is False
    assert payload["target_repo"] == DATASET_REPO
    assert payload["staging_branch"] == STAGING_BRANCH
    assert payload.get("manifest_digest")
    assert payload.get("plan_digest")
    # Nested plan carries rollback base revision and add-only operations.
    plan = payload.get("plan") or {}
    assert plan.get("base_revision") == PINNED_REVISION
    ops = plan.get("operations") or []
    assert "add_only_upload" in ops
    assert plan.get("legacy_files_deleted") is False
    assert payload.get("visibility_changed") is False
    rendered = json.dumps(payload)
    assert "hf_token" not in rendered.casefold()
    assert "access_token" not in rendered.casefold()


def test_stage_plan_fixture_check_supports_rehearsal(stage_cli) -> None:
    """Runbook §8.2 — sealed stage plan check remains green."""
    result = stage_cli.check_stage_plan_fixture()
    assert result["ok"] is True
    assert result["mismatches"] == []
    assert result["target_repo"] == DATASET_REPO
    assert result["staging_branch"] == STAGING_BRANCH


def test_rollback_target_is_prior_advertised_revision(
    stage_cli, runbook_text: str
) -> None:
    """Rollback rehearses restore of prior advertised pin without deletion."""
    plan = stage_cli.build_fixture_stage_plan()
    assert plan["base_revision"] == PINNED_REVISION
    assert plan["legacy_files_deleted"] is False
    forbidden = {str(x) for x in (plan.get("forbidden_operations") or [])}
    assert "delete" in forbidden or any("delete" in f for f in forbidden)
    assert "force_push" in forbidden or any("force" in f for f in forbidden)
    text = runbook_text.casefold()
    assert "prior advertised revision" in text or "rollback target" in text
    assert "without deleting legacy data" in text


def test_publication_date_distinct_from_legal_currentness(
    runbook_text: str, migration_text: str
) -> None:
    """Runbook §11 / migration §6 — operators must not conflate timestamps."""
    combined = f"{runbook_text}\n{migration_text}".casefold()
    assert "publication" in combined
    assert "legal currentness" in combined or "legal-currentness" in combined
    assert "not" in combined
    # Explicit research-aid caveat.
    assert "research aid" in combined
    assert "not a substitute" in combined
    # Release point is the authority operators should expose.
    assert RELEASE_POINT in runbook_text
    assert "release point" in combined or "release_point" in combined
    # Acquisition time is handling metadata, not currentness.
    assert "acquisition" in combined


def test_live_hub_mutable_revision_rejected(query_cli) -> None:
    """Documented fail-closed behavior for mutable pins."""
    ns = type(
        "NS",
        (),
        {
            "repo_id": DATASET_REPO,
            "revision": "main",
            "cache_dir": None,
            "local_root": None,
        },
    )()
    # CliError subclasses SystemExit (BaseException), not Exception.
    with pytest.raises(query_cli.CliError):
        query_cli._build_resolver(ns)


def test_scripts_referenced_by_docs_exist() -> None:
    assert BUILD_SCRIPT.is_file()
    assert QUERY_SCRIPT.is_file()
    assert STAGE_SCRIPT.is_file()
    card = REPO / "tests" / "fixtures" / "legal_ir" / "uscode_dataset_card.md"
    stage_plan = REPO / "tests" / "fixtures" / "legal_ir" / "uscode_stage_plan.json"
    assert card.is_file()
    assert stage_plan.is_file()
