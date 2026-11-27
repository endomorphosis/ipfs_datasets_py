"""Unit tests for US Code human publication-seal request (USCIR-040).

Acceptance:

* Pending seal validates as a complete authorization request with --allow-pending.
* Approved seal requires external human identity/signature and exact digests.
* No token is present; agents cannot self-authorize or publish.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "check_uscode_publication_seal.py"
)
_SEAL_PATH = _REPO_ROOT / "docs" / "reports" / "uscode_publication_seal.json"
_RELEASE_CANDIDATE_PATH = (
    _REPO_ROOT / "docs" / "reports" / "uscode_release_candidate.json"
)
_STAGING_CANARY_PATH = _REPO_ROOT / "docs" / "reports" / "uscode_staging_canary.json"


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing seal script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "check_uscode_publication_seal_uscir040",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.name is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seal_mod() -> ModuleType:
    return _load_module()


@pytest.fixture(scope="module")
def pending_seal(seal_mod: ModuleType) -> dict[str, Any]:
    """Deterministic pending seal (also materializes docs/reports/...)."""

    payload, path = seal_mod.materialize_default_seal()
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["task_id"] == payload["task_id"]
    assert on_disk["status"] == "pending"
    assert on_disk["seal_sha256"] == payload["seal_sha256"]
    return payload


def _approve_seal(
    seal_mod: ModuleType,
    pending: MappingLike,
    *,
    identity: str = "release-operator@example.com",
    approved_at: str = "2026-08-10T00:00:00Z",
) -> dict[str, Any]:
    """Construct an approved seal from a pending request for unit tests."""

    seal = copy.deepcopy(dict(pending))
    digests = dict(seal.get("digests") or {})
    production = dict(seal.get("production") or {})
    candidate = dict(seal.get("candidate") or {})
    signature = seal_mod.compute_approval_signature(
        digests=digests,
        candidate_revision=str(candidate.get("revision")),
        production_repo=str(production.get("dataset_id")),
        production_branch=str(production.get("branch")),
        identity=identity,
    )
    seal["status"] = "approved"
    seal["publication_authorized"] = True
    seal["main_published"] = False
    seal["approver"] = {
        "approved_at": approved_at,
        "identity": identity,
        "kind": "external_human",
        "signature": signature,
        "status": "approved",
    }
    seal["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in seal.items() if k != "seal_sha256"}
    )
    return seal


# typing helper without importing Mapping at module level for deepcopy clarity
MappingLike = dict[str, Any]


# ---------------------------------------------------------------------------
# Surfaces exist
# ---------------------------------------------------------------------------


def test_script_and_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    assert _RELEASE_CANDIDATE_PATH.is_file()
    assert _STAGING_CANARY_PATH.is_file()


def test_help_exits_zero(seal_mod: ModuleType) -> None:
    assert seal_mod.main(["--help"]) == 0


# ---------------------------------------------------------------------------
# Pending seal acceptance
# ---------------------------------------------------------------------------


def test_pending_seal_acceptance(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    seal_mod.assert_seal_structure(pending_seal)
    seal_mod.assert_pending_seal(pending_seal)
    result = seal_mod.check_seal(pending_seal, allow_pending=True)
    assert result["ok"] is True
    assert result["task_id"] == "USCIR-040"
    assert result["goal_id"] == "USCIR-G100"
    assert result["status"] == "pending"
    assert result["publication_authorized"] is False
    assert result["main_published"] is False
    assert result["network_required"] is False
    assert result["mismatches"] == []
    assert result["seal_sha256"]
    assert len(result["seal_sha256"]) == 64
    assert result["production_repo"] == "justicedao/ipfs_uscode"
    assert result["production_branch"] == "main"
    assert len(result["candidate_revision"]) == 40
    assert len(result["manifest_digest"]) == 64
    assert len(result["validation_receipt_digest"]) == 64
    assert len(result["rollback_revision"]) == 40


def test_pending_seal_required_fields(pending_seal: dict[str, Any]) -> None:
    assert pending_seal["schema"] == (
        "ipfs_datasets_py/uscode-sparse-graphrag-publication-seal@1"
    )
    assert pending_seal["schema_version"] == "uscode-publication-seal/v1"
    assert pending_seal["task_id"] == "USCIR-040"
    assert pending_seal["goal_id"] == "USCIR-G100"
    assert pending_seal["program_id"] == "uscode-sparse-graphrag-v1"
    assert pending_seal["producer"] == "check_uscode_publication_seal.py"
    assert pending_seal["status"] == "pending"
    assert pending_seal["publication_authorized"] is False
    assert pending_seal["main_published"] is False
    assert pending_seal["network_required"] is False
    assert pending_seal["depends_on"] == ["USCIR-039"]
    assert pending_seal["currentness_disclaimer"]
    assert pending_seal["fixture_id"] == "uscode-publication-seal-v1"

    production = pending_seal["production"]
    assert production["dataset_id"] == "justicedao/ipfs_uscode"
    assert production["branch"] == "main"
    assert production["default_config"] == "publicus-ir-graphrag/v2"
    assert production["publication_requires_human_seal"] is True

    candidate = pending_seal["candidate"]
    assert candidate["dataset_id"] == "justicedao/ipfs_uscode"
    assert len(candidate["revision"]) == 40
    assert len(candidate["manifest_digest"]) == 64
    assert candidate["release_root_cid"]
    assert candidate["release_point"]
    assert candidate["staging_branch"] == "stage/uscode-sparse-graphrag-v2"
    assert candidate["staging_branch"] not in {"main", "master"}

    rollback = pending_seal["rollback"]
    assert len(rollback["revision"]) == 40
    assert rollback["default_config"] == "publicus-ir-graphrag/v2"
    assert rollback["legacy_files_deleted"] is False

    digests = pending_seal["digests"]
    assert digests["manifest"] == candidate["manifest_digest"]
    assert len(digests["validation_receipt"]) == 64

    mutations = pending_seal["requested_mutations"]
    assert isinstance(mutations, list) and mutations
    ops = {m["operation"] for m in mutations}
    assert "advertise_revision" in ops
    assert not ops & {
        "delete",
        "force_push",
        "visibility_change",
        "rotate_credentials",
    }

    approver = pending_seal["approver"]
    assert approver["identity"] is None
    assert approver["signature"] is None
    assert approver["status"] == "pending"
    assert approver["kind"] == "external_human"

    acceptance = pending_seal["acceptance"]
    assert acceptance["complete_authorization_request"] is True
    assert acceptance["pending_valid_as_request"] is True
    assert acceptance["human_approval_required"] is True
    assert acceptance["no_agent_self_authorization"] is True
    assert acceptance["main_not_mutated_by_this_tool"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["exact_digests_bound"] is True
    assert acceptance["legacy_rollback_mapping_named"] is True
    assert acceptance["production_repo_branch_named"] is True
    assert acceptance["requested_mutations_enumerated"] is True


def test_sealed_report_on_disk_matches_pending(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    assert _SEAL_PATH.is_file()
    on_disk = json.loads(_SEAL_PATH.read_text(encoding="utf-8"))
    mismatches = seal_mod.compare_seals(pending_seal, on_disk)
    assert mismatches == []


def test_cli_allow_pending_exits_zero(seal_mod: ModuleType, pending_seal: dict[str, Any]) -> None:
    assert pending_seal["status"] == "pending"
    code = seal_mod.main(
        [
            "--seal",
            str(_SEAL_PATH),
            "--allow-pending",
        ]
    )
    assert code == 0


def test_pending_without_allow_pending_fails(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    with pytest.raises(seal_mod.SealStateError, match="allow-pending"):
        seal_mod.check_seal(pending_seal, allow_pending=False)


def test_cli_pending_without_flag_exits_nonzero(seal_mod: ModuleType) -> None:
    code = seal_mod.main(["--seal", str(_SEAL_PATH)])
    assert code != 0


# ---------------------------------------------------------------------------
# Approved seal policy
# ---------------------------------------------------------------------------


def test_approved_seal_requires_human_identity_and_signature(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    approved = _approve_seal(seal_mod, pending_seal)
    seal_mod.assert_seal_structure(approved)
    seal_mod.assert_approved_seal(approved)
    result = seal_mod.check_seal(
        approved, allow_pending=False, require_fixture_match=False,
        pending_request=pending_seal,
        expected_pending_request_sha256=pending_seal["seal_sha256"],
    )
    assert result["ok"] is True
    assert result["status"] == "approved"
    assert result["approval_request_matched"] is True
    assert result["publication_authorized"] is True
    assert result["main_published"] is False


def test_approved_seal_rejects_agent_identity(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    with pytest.raises(seal_mod.ApprovalError, match="agent|supervisor|human"):
        _approve_seal(seal_mod, pending_seal, identity="implementation-supervisor")


@pytest.mark.parametrize(
    "identity",
    [
        "agent-lane-3",
        "USCIR supervisor",
        "codex-worker",
        "grok-4.5",
        "github-actions",
        "ci-runner-7",
    ],
)
def test_agent_identities_rejected(
    pending_seal: dict[str, Any], seal_mod: ModuleType, identity: str
) -> None:
    with pytest.raises(seal_mod.ApprovalError):
        seal_mod.assert_human_identity(identity)


def test_approved_seal_rejects_wrong_signature(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    approved = _approve_seal(seal_mod, pending_seal)
    approved["approver"]["signature"] = "0" * 64
    approved["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in approved.items() if k != "seal_sha256"}
    )
    with pytest.raises(seal_mod.ApprovalError, match="signature"):
        seal_mod.assert_approved_seal(approved)


def test_approved_seal_rejects_digest_tamper(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    approved = _approve_seal(seal_mod, pending_seal)
    # Tamper manifest after signing — signature no longer matches digests.
    approved["digests"]["manifest"] = "a" * 64
    approved["candidate"]["manifest_digest"] = "a" * 64
    approved["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in approved.items() if k != "seal_sha256"}
    )
    with pytest.raises(seal_mod.ApprovalError, match="signature"):
        seal_mod.assert_approved_seal(approved)


def test_approved_without_approved_at_fails(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    approved = _approve_seal(seal_mod, pending_seal)
    approved["approver"]["approved_at"] = None
    approved["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in approved.items() if k != "seal_sha256"}
    )
    with pytest.raises(seal_mod.ApprovalError, match="approved_at"):
        seal_mod.assert_approved_seal(approved)


# ---------------------------------------------------------------------------
# Safety: secrets, paths, forbidden mutations, self-auth
# ---------------------------------------------------------------------------


def test_rejects_credential_material(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    dirty = copy.deepcopy(pending_seal)
    dirty["hf_token"] = "hf_abcdefghijklmnopqrstuv"
    dirty["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in dirty.items() if k != "seal_sha256"}
    )
    with pytest.raises(seal_mod.SecretLeakError):
        seal_mod.assert_seal_structure(dirty)


def test_rejects_absolute_path_leak(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    dirty = copy.deepcopy(pending_seal)
    dirty["notes"] = "built under /home/operator/secrets/out"
    dirty["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in dirty.items() if k != "seal_sha256"}
    )
    with pytest.raises(seal_mod.PathLeakError):
        seal_mod.assert_seal_structure(dirty)


def test_rejects_forbidden_mutation(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    dirty = copy.deepcopy(pending_seal)
    dirty["requested_mutations"] = [
        {"operation": "delete", "target_repo": "justicedao/ipfs_uscode"}
    ]
    dirty["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in dirty.items() if k != "seal_sha256"}
    )
    with pytest.raises(seal_mod.MismatchError, match="forbids|delete"):
        seal_mod.assert_seal_structure(dirty)


def test_rejects_unpinned_candidate_revision(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    dirty = copy.deepcopy(pending_seal)
    dirty["candidate"]["revision"] = "main"
    dirty["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in dirty.items() if k != "seal_sha256"}
    )
    with pytest.raises(Exception):
        seal_mod.assert_seal_structure(dirty)


def test_rejects_main_as_staging_branch(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    dirty = copy.deepcopy(pending_seal)
    dirty["candidate"]["staging_branch"] = "main"
    dirty["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in dirty.items() if k != "seal_sha256"}
    )
    with pytest.raises(seal_mod.MismatchError, match="staging_branch"):
        seal_mod.assert_seal_structure(dirty)


def test_pending_cannot_claim_publication_authorized(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    dirty = copy.deepcopy(pending_seal)
    dirty["publication_authorized"] = True
    dirty["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in dirty.items() if k != "seal_sha256"}
    )
    with pytest.raises(seal_mod.SealStateError, match="publication_authorized"):
        seal_mod.assert_pending_seal(dirty)


def test_tool_never_claims_main_published(
    pending_seal: dict[str, Any], seal_mod: ModuleType
) -> None:
    dirty = copy.deepcopy(pending_seal)
    dirty["main_published"] = True
    dirty["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in dirty.items() if k != "seal_sha256"}
    )
    with pytest.raises(seal_mod.MismatchError, match="main_published"):
        seal_mod.assert_seal_structure(dirty)


def test_argv_secrets_rejected(seal_mod: ModuleType) -> None:
    with pytest.raises(seal_mod.SecretLeakError):
        seal_mod.reject_secrets_in_argv(["--seal", "x", "hf_token=hf_abc"])


def test_independent_pending_builds_match(seal_mod: ModuleType) -> None:
    a = seal_mod.build_pending_seal()
    b = seal_mod.build_pending_seal()
    assert a["seal_sha256"] == b["seal_sha256"]
    assert seal_mod.compare_seals(a, b) == []


def test_requested_mutations_must_match_declared_cutover(pending_seal, seal_mod):
    pending = copy.deepcopy(pending_seal)
    pending["requested_mutations"][0]["to_default_config"] = "other"
    pending["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in pending.items() if k != "seal_sha256"}
    )
    with pytest.raises(seal_mod.MismatchError, match="requested_mutations.*cutover"):
        seal_mod.assert_seal_structure(pending)


def test_approved_shape_without_original_request_has_no_checked_authorization(pending_seal, seal_mod):
    approved = _approve_seal(seal_mod, pending_seal)
    result = seal_mod.check_seal(approved, require_fixture_match=False)
    assert result["status"] == "approved"
    assert result["record_declares_publication_authorized"] is True
    assert result["approval_request_matched"] is False
    assert result["publication_authorized"] is False


def test_historical_approval_matches_its_original_request(seal_mod):
    approved = seal_mod.REPOSITORY_ROOT / "docs/reports/uscode_publication_seal_approved.json"
    result = seal_mod.check_seal(seal_path=approved)
    assert result["approval_request_matched"] is True
    assert result["publication_authorized"] is True
    assert result["main_published"] is False


def test_approved_request_rejects_different_rollback_and_wrong_pin(pending_seal, seal_mod):
    approved = _approve_seal(seal_mod, pending_seal)
    with pytest.raises(seal_mod.ApprovalError, match="selected pending request"):
        seal_mod.check_seal(
            approved, require_fixture_match=False, pending_request=pending_seal,
            expected_pending_request_sha256="0" * 64,
        )

    approved["rollback"]["default_config"] = "other"
    approved["requested_mutations"] = seal_mod._requested_mutations(
        production_repo=approved["production"]["dataset_id"],
        production_branch=approved["production"]["branch"],
        candidate=approved["candidate"],
        rollback=approved["rollback"],
    )
    approved["seal_sha256"] = seal_mod.digest_mapping(
        {k: v for k, v in approved.items() if k != "seal_sha256"}
    )
    seal_mod.assert_seal_structure(approved)
    with pytest.raises(seal_mod.ApprovalError, match="selected pending request"):
        seal_mod.check_seal(
            approved, require_fixture_match=False, pending_request=pending_seal,
            expected_pending_request_sha256=pending_seal["seal_sha256"],
        )


def test_cli_checks_custom_approved_seal_against_its_original_request(
    tmp_path, pending_seal, seal_mod, monkeypatch
):
    monkeypatch.setattr(seal_mod, "REPOSITORY_ROOT", tmp_path)
    approved = _approve_seal(seal_mod, pending_seal)
    request_path = tmp_path / "pending.json"
    seal_path = tmp_path / "approved.json"
    receipt_path = tmp_path / "checked.json"
    request_path.write_text(json.dumps(pending_seal), encoding="utf-8")
    seal_path.write_text(json.dumps(approved), encoding="utf-8")

    assert seal_mod.main([
        "--seal", str(seal_path), "--pending-request", str(request_path),
        "--pending-request-sha256", pending_seal["seal_sha256"],
        "--output", str(receipt_path),
    ]) == 0
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["approval_request_matched"] is True
    assert receipt["main_published"] is False
