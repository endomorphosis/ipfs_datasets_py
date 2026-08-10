"""Unit tests for US Code release-candidate receipt verification (USCIR-038).

Acceptance:

* Verifier fails on any missing / mismatched / stale input.
* Receipt contains no secret or absolute path leak.
* A valid fixture candidate is independently reproducible.
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
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "verify_uscode_release_candidate.py"
)
_RECEIPT_PATH = _REPO_ROOT / "docs" / "reports" / "uscode_release_candidate.json"

_PRODUCER_PATHS = (
    _REPO_ROOT / "docs" / "reports" / "uscode_sparse_graphrag_evaluation.json",
    _REPO_ROOT / "docs" / "reports" / "uscode_release_security.json",
    _REPO_ROOT / "docs" / "reports" / "uscode_e2e_local.json",
    _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_remote_canary.json",
    _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_stage_plan.json",
    _REPO_ROOT / "docs" / "guides" / "USCODE_SPARSE_GRAPHRAG_RUNBOOK.md",
    _REPO_ROOT / "docs" / "guides" / "USCODE_SPARSE_GRAPHRAG_MIGRATION.md",
)


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing verifier script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "verify_uscode_release_candidate_uscir038",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.name is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def vr() -> ModuleType:
    return _load_module()


@pytest.fixture(scope="module")
def receipt(vr: ModuleType) -> dict[str, Any]:
    """Deterministic fixture receipt (also materializes the sealed report)."""

    payload, path = vr.materialize_default_receipt()
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["task_id"] == payload["task_id"]
    assert on_disk["receipt_sha256"] == payload["receipt_sha256"]
    assert on_disk["candidate"]["manifest_digest"] == payload["candidate"]["manifest_digest"]
    return payload


# ---------------------------------------------------------------------------
# Surfaces exist
# ---------------------------------------------------------------------------


def test_script_and_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    for path in _PRODUCER_PATHS:
        assert path.is_file(), f"missing producer input: {path}"


def test_help_exits_zero(vr: ModuleType) -> None:
    assert vr.main(["--help"]) == 0


# ---------------------------------------------------------------------------
# Fixture receipt acceptance
# ---------------------------------------------------------------------------


def test_fixture_receipt_acceptance(receipt: dict[str, Any], vr: ModuleType) -> None:
    result = vr.verify_receipt(receipt, require_fixture_match=True)
    assert result["ok"] is True
    assert result["task_id"] == "USCIR-038"
    assert result["goal_id"] == "USCIR-G100"
    assert result["fixture_independently_reproducible"] is True
    assert result["publication_authorized"] is False
    assert result["network_required"] is False
    assert result["mismatches"] == []
    assert result["receipt_sha256"]
    assert len(result["receipt_sha256"]) == 64
    assert result["manifest_digest"]
    assert result["rollback_revision"]
    assert len(result["rollback_revision"]) == 40

    acceptance = receipt["acceptance"]
    assert acceptance["all_inputs_present"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["fixture_independently_reproducible"] is True
    assert acceptance["evaluation_gate_pass"] is True
    assert acceptance["security_gate_pass"] is True
    assert acceptance["canary_gate_pass"] is True
    assert acceptance["determinism_gate_pass"] is True
    assert acceptance["viewer_gate_pass"] is True
    assert acceptance["rollback_target_named"] is True
    assert acceptance["publication_not_authorized"] is True


def test_receipt_binds_required_surfaces(receipt: dict[str, Any]) -> None:
    assert receipt["schema"] == (
        "ipfs_datasets_py/uscode-sparse-graphrag-release-candidate@1"
    )
    assert receipt["schema_version"] == "uscode-release-candidate/v1"
    assert receipt["task_id"] == "USCIR-038"
    assert receipt["goal_id"] == "USCIR-G100"
    assert receipt["program_id"] == "uscode-sparse-graphrag-v1"
    assert receipt["producer"] == "verify_uscode_release_candidate.py"
    assert receipt["release_point"]
    assert receipt["release_profile"] == "publicus-ir-graphrag/v2"
    assert receipt["publication_authorized"] is False
    assert receipt["network_required"] is False
    assert receipt["currentness_disclaimer"]

    candidate = receipt["candidate"]
    assert candidate["kind"] == "fixture_local"
    assert candidate["root_label"] == "fixture://uscode-hf-release-candidate"
    assert candidate["dataset_id"] == "justicedao/ipfs_uscode"
    assert len(candidate["revision"]) == 40
    assert len(candidate["manifest_digest"]) == 64
    assert candidate["release_root_cid"]
    assert candidate["default_config"] == "publicus-ir-graphrag/v2"
    assert candidate["staging_branch"] == "stage/uscode-sparse-graphrag-v2"

    rollback = receipt["rollback"]
    assert len(rollback["revision"]) == 40
    assert rollback["default_config"] == "publicus-ir-graphrag/v2"
    assert rollback["legacy_files_deleted"] is False

    digests = receipt["digests"]
    for key in ("manifest", "config", "code", "model"):
        assert digests[key]
        assert len(digests[key]) == 64

    evidence = receipt["evidence"]
    for key in (
        "evaluation",
        "security",
        "e2e",
        "canary",
        "stage_plan",
        "runbook",
        "migration",
        "determinism",
        "viewer",
    ):
        assert key in evidence
        assert evidence[key]["ok"] is True

    assert isinstance(receipt["exception_dispositions"], list)
    assert any(
        d.get("kind") == "production_searchable_disposition"
        for d in receipt["exception_dispositions"]
    )
    assert receipt["counts"]["reconciled"] is True


def test_sealed_receipt_on_disk_matches_fixture(receipt: dict[str, Any], vr: ModuleType) -> None:
    assert _RECEIPT_PATH.is_file()
    on_disk = json.loads(_RECEIPT_PATH.read_text(encoding="utf-8"))
    mismatches = vr.compare_receipts(receipt, on_disk)
    assert mismatches == []


# ---------------------------------------------------------------------------
# Independent reproducibility
# ---------------------------------------------------------------------------


def test_fixture_receipt_independently_reproducible(vr: ModuleType) -> None:
    a = vr.build_fixture_receipt()
    b = vr.build_fixture_receipt()
    assert a["receipt_sha256"] == b["receipt_sha256"]
    assert a["candidate"]["manifest_digest"] == b["candidate"]["manifest_digest"]
    assert a["candidate"]["release_root_cid"] == b["candidate"]["release_root_cid"]
    assert a["digests"] == b["digests"]
    assert a["evidence"]["evaluation"]["sha256"] == b["evidence"]["evaluation"]["sha256"]
    assert a["exception_dispositions"] == b["exception_dispositions"]

    release_a = vr.build_fixture_candidate()
    release_b = vr.build_fixture_candidate()
    assert release_a.manifest_digest == release_b.manifest_digest
    assert release_a.release_root_cid == release_b.release_root_cid


# ---------------------------------------------------------------------------
# No secret / path leaks
# ---------------------------------------------------------------------------


def test_receipt_has_no_secret_or_path_leak(receipt: dict[str, Any], vr: ModuleType) -> None:
    vr.reject_credentials_in_payload(receipt, label="test_receipt")
    vr.reject_path_leaks(receipt, label="test_receipt")

    rendered = json.dumps(receipt)
    assert "hf_token" not in rendered.casefold()
    assert "access_token" not in rendered.casefold()
    assert "bearer " not in rendered.casefold()
    assert "/home/" not in rendered
    assert "file://" not in rendered.casefold()
    assert "C:\\Users" not in rendered
    assert str(_REPO_ROOT) not in rendered

    for env_name in vr.SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val:
            assert env_val not in rendered

    # Evidence paths must be repo-relative.
    for key in ("evaluation", "security", "e2e", "canary", "stage_plan", "runbook", "migration"):
        path = receipt["evidence"][key]["path"]
        assert not path.startswith("/")
        assert ".." not in Path(path).parts


def test_path_leak_rejected(vr: ModuleType) -> None:
    with pytest.raises(vr.PathLeakError):
        vr.reject_path_leaks(
            {"candidate": {"root_label": "/home/operator/secret-tree"}},
            label="test",
        )
    with pytest.raises(vr.PathLeakError):
        vr.reject_path_leaks(
            {"evidence": {"evaluation": {"path": "/tmp/eval.json"}}},
            label="test",
        )


def test_credentials_in_payload_rejected(vr: ModuleType) -> None:
    with pytest.raises(vr.SecretLeakError):
        vr.reject_credentials_in_payload(
            {"plan_digest": "x", "hf_token": "hf_should_not_appear_here_12345"},
            label="test",
        )


def test_secrets_on_argv_rejected(vr: ModuleType) -> None:
    with pytest.raises(vr.SecretLeakError):
        vr.reject_secrets_in_argv(["--hf_token=hf_secretvalue1234567890", "--fixture-only"])
    with pytest.raises(vr.SecretLeakError):
        vr.reject_secrets_in_argv(["Authorization: Bearer abc", "--fixture-only"])


# ---------------------------------------------------------------------------
# Fail closed: missing / mismatched / stale
# ---------------------------------------------------------------------------


def test_missing_evidence_binding_fails(receipt: dict[str, Any], vr: ModuleType) -> None:
    bad = copy.deepcopy(receipt)
    del bad["evidence"]["evaluation"]
    # Drop receipt_sha256 so structural check hits missing evidence first.
    bad.pop("receipt_sha256", None)
    with pytest.raises((vr.MissingInputError, vr.MismatchError)):
        vr.assert_receipt_safe(bad)


def test_mismatched_manifest_digest_fails(receipt: dict[str, Any], vr: ModuleType) -> None:
    bad = copy.deepcopy(receipt)
    bad["candidate"]["manifest_digest"] = "0" * 64
    bad["digests"]["manifest"] = "0" * 64
    bad["receipt_sha256"] = vr.digest_mapping(
        {k: v for k, v in bad.items() if k != "receipt_sha256"}
    )
    with pytest.raises(vr.MismatchError):
        vr.verify_receipt(bad, require_fixture_match=True)


def test_stale_evidence_digest_fails(receipt: dict[str, Any], vr: ModuleType) -> None:
    bad = copy.deepcopy(receipt)
    bad["evidence"]["evaluation"]["sha256"] = "a" * 64
    bad["receipt_sha256"] = vr.digest_mapping(
        {k: v for k, v in bad.items() if k != "receipt_sha256"}
    )
    with pytest.raises(vr.StaleInputError):
        vr.assert_evidence_not_stale(bad)


def test_missing_producer_file_fails(vr: ModuleType, tmp_path: Path) -> None:
    # Point repo_root at an empty tree so required inputs are absent.
    with pytest.raises(vr.MissingInputError):
        vr.load_producer_evidence(repo_root=tmp_path)


def test_receipt_sha256_tamper_fails(receipt: dict[str, Any], vr: ModuleType) -> None:
    bad = copy.deepcopy(receipt)
    bad["receipt_sha256"] = "b" * 64
    with pytest.raises(vr.MismatchError):
        vr.assert_receipt_safe(bad)


def test_mutable_revision_rejected(receipt: dict[str, Any], vr: ModuleType) -> None:
    bad = copy.deepcopy(receipt)
    bad["candidate"]["revision"] = "main"
    bad["receipt_sha256"] = vr.digest_mapping(
        {k: v for k, v in bad.items() if k != "receipt_sha256"}
    )
    with pytest.raises((vr.MismatchError, vr.ReleaseCandidateError, Exception)):
        vr.assert_receipt_safe(bad)


def test_publication_authorized_rejected(receipt: dict[str, Any], vr: ModuleType) -> None:
    bad = copy.deepcopy(receipt)
    bad["publication_authorized"] = True
    bad["receipt_sha256"] = vr.digest_mapping(
        {k: v for k, v in bad.items() if k != "receipt_sha256"}
    )
    with pytest.raises(vr.MismatchError):
        vr.assert_receipt_safe(bad)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_main_fixture_only_verifies_sealed_receipt(vr: ModuleType, capsys: Any) -> None:
    # Ensure sealed receipt is present and current.
    vr.materialize_default_receipt()
    rc = vr.main(
        [
            "--receipt",
            str(_RECEIPT_PATH),
            "--fixture-only",
        ]
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "ok=True" in err or "ok=true" in err.casefold()
    assert "USCIR-038" in err or "task_id=USCIR-038" in err


def test_main_without_fixture_only_fails(vr: ModuleType) -> None:
    rc = vr.main(["--receipt", str(_RECEIPT_PATH)])
    assert rc == 1


def test_main_print_json(vr: ModuleType, capsys: Any) -> None:
    vr.materialize_default_receipt()
    rc = vr.main(
        [
            "--receipt",
            str(_RECEIPT_PATH),
            "--fixture-only",
            "--print-json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["task_id"] == "USCIR-038"
