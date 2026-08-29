"""Current-contract tests for the canonical LCR-042 public publisher."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.publisher import (
    CanonicalLegalCorporaMutationReceipt,
    PublicationFilePlan,
    PublicationPlan,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_package import (
    BASE_PROHIBITED_OPERATIONS,
    STATE_LAWS_PLAN_SCHEMA,
    StateLawsCanonicalControlBundle,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))
for _name in tuple(sys.modules):
    if _name == "scripts" or _name.startswith("scripts."):
        sys.modules.pop(_name, None)
publish = importlib.import_module("scripts.ops.legal_data.publish_state_laws_hf_release")


PARENT = publish.PRODUCTION_REVISION
STAGING = "2" * 40
PUBLIC = "3" * 40
CANDIDATE_DIGEST = "a" * 64
STAGING_CANDIDATE_DIGEST = "8" * 64
RELEASE_DIGEST = "b" * 64
PROOF_DIGEST = "c" * 64
SEAL_DIGEST = "d" * 64


def _candidate() -> dict:
    return {
        "report_digest_sha256": CANDIDATE_DIGEST,
        "manifest_digest": RELEASE_DIGEST,
        "publication_binding": {
            "plan_digest": _plan().plan_digest,
            "policy_proof_digest": PROOF_DIGEST,
            "release_manifest_digest": RELEASE_DIGEST,
            "staging_candidate_digest": STAGING_CANDIDATE_DIGEST,
            "staging_revision": STAGING,
        },
    }


def _plan() -> PublicationPlan:
    release_id = f"sha256-{RELEASE_DIGEST}"
    return PublicationPlan(
        schema_version=STATE_LAWS_PLAN_SCHEMA,
        repository_id=publish.DEFAULT_DATASET_REPO,
        repository_type="dataset",
        release_id=release_id,
        release_prefix=f"releases/{release_id}",
        release_sha256=RELEASE_DIGEST,
        operations=(
            PublicationFilePlan(
                relative_path="manifest.json",
                remote_path=f"releases/{release_id}/manifest.json",
                size_bytes=9,
                sha256="e" * 64,
            ),
        ),
        cost_receipt={"currency": "USD", "estimated_cost_usd": 0.0},
        audited_parent_commit=PARENT,
        target_revision="main",
        prohibited_operations=BASE_PROHIBITED_OPERATIONS,
    )


def _controls() -> StateLawsCanonicalControlBundle:
    return StateLawsCanonicalControlBundle(
        candidate_path="docs/reports/legal_corpora_reindex/release_candidate.json",
        candidate_manifest_digest=CANDIDATE_DIGEST,
        candidate_file_sha256="4" * 64,
        dataset_card_path="README.md",
        dataset_card_sha256="5" * 64,
        release_manifest_digest=RELEASE_DIGEST,
        seal_path="docs/reports/legal_corpora_reindex/state_prepublication_seal.json",
        seal_content_digest=SEAL_DIGEST,
        seal_file_sha256="6" * 64,
        source_rights_receipt_digest="7" * 64,
        staging_candidate_digest=STAGING_CANDIDATE_DIGEST,
        staging_revision=STAGING,
    )


def _mutation() -> CanonicalLegalCorporaMutationReceipt:
    plan = _plan()
    return CanonicalLegalCorporaMutationReceipt(
        phase=publish.PUBLICATION_PHASE,
        method="create_commit",
        operation=publish.AUTHORIZED_OPERATION,
        repository_id=publish.DEFAULT_DATASET_REPO,
        revision="main",
        parent_commit=PARENT,
        resulting_commit_sha=PUBLIC,
        plan_digest=plan.plan_digest,
        release_manifest_digest=RELEASE_DIGEST,
        policy_proof_digest=PROOF_DIGEST,
        payload_digest="f" * 64,
        approval_id="main-approval",
    )


def _receipt() -> dict:
    return publish.build_canonical_publication_receipt(
        candidate=_candidate(),
        plan=_plan(),
        controls=_controls(),
        mutation_receipt=_mutation(),
    )


def test_identity_help_and_single_canonical_protected_writer() -> None:
    assert publish.TASK_ID == "LCR-042"
    assert publish.PUBLICATION_PHASE == "state_main"
    assert publish.main(["--help"]) == 0
    source = Path(publish.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "HfApi",
        "upload_folder",
        "authorize_and_mutate",
        "invoke_protected_hf_write",
    ):
        assert forbidden not in source
    assert "execute_canonical_legal_corpora_mutation" in source
    assert "check_state_prepublication_seal" in source


def test_dry_run_is_add_only_and_non_authorizing() -> None:
    receipt = publish.build_canonical_publication_dry_run_receipt(
        candidate=_candidate(), plan=_plan()
    )
    assert receipt["status"] == "dry_run_only"
    assert receipt["remote_mutation_attempted"] is False
    assert receipt["seal_verified_before_mutation"] is False
    assert receipt["operations"][0]["operation"] == "add"
    assert receipt["previous_public_pin"] == PARENT


def test_live_receipt_binds_seal_staging_old_and_public_pins() -> None:
    receipt = _receipt()
    checked = publish.check_canonical_publication_receipt(receipt)
    assert checked["previous_public_pin"] == PARENT
    assert checked["rollback_target"] == PARENT
    assert checked["staging_revision"] == STAGING
    assert checked["public_revision"] == PUBLIC
    assert checked["prepublication_seal_digest"] == SEAL_DIGEST
    assert checked["main_mutation"]["runtime_authorized"] is True
    assert checked["legacy_paths_preserved"] is True


def test_tampering_or_non_additive_operation_fails_closed() -> None:
    changed = copy.deepcopy(_receipt())
    changed["main_mutation"]["resulting_commit_sha"] = "4" * 40
    with pytest.raises(publish.PublishReceiptError, match="digest mismatch"):
        publish.check_canonical_publication_receipt(changed)
    changed = copy.deepcopy(_receipt())
    changed["operations"][0]["operation"] = "delete"
    digest = publish.publication_digest(changed)
    changed["canonical_digest"] = changed["content_digest"] = digest
    with pytest.raises(publish.PublishSafetyError, match="add-only"):
        publish.check_canonical_publication_receipt(changed)


def test_main_executor_passes_live_proof_to_canonical_runtime(tmp_path: Path) -> None:
    calls: list[tuple] = []

    class Publisher:
        def execute_canonical_legal_corpora_mutation(self, *args, **kwargs):
            calls.append((args, kwargs))
            return "receipt"

    proof = object()
    result = publish.authorize_state_main_upload(
        publisher=Publisher(),
        plan="plan",
        approval="approval",
        local_root=tmp_path,
        policy_proof_digest=PROOF_DIGEST,
        live_policy_proof=proof,
    )
    assert result == "receipt"
    assert calls[0][1]["publication_phase"] == "state_main"
    assert calls[0][1]["mutation_method"] == "create_commit"
    assert calls[0][1]["live_policy_proof"] is proof


def test_check_cli_is_read_only(tmp_path: Path) -> None:
    target = tmp_path / "publication.json"
    target.write_text(json.dumps(_receipt()), encoding="utf-8")
    before = target.read_bytes()
    assert publish.main(["--check-receipt", "--receipt", str(target)]) == 0
    assert target.read_bytes() == before
    assert publish.main(
        ["--check-receipt", "--receipt", str(target), "--write-receipt"]
    ) != 0


def test_production_cli_rejects_fake_transport() -> None:
    assert publish.main(["--fake-hub"]) != 0
