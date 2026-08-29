"""Current-contract tests for the canonical LCR-040 staging uploader."""

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
    StateLawsStagingControlBundle,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))
for _name in tuple(sys.modules):
    if _name == "scripts" or _name.startswith("scripts."):
        sys.modules.pop(_name, None)
stage = importlib.import_module("scripts.ops.legal_data.stage_state_laws_hf_release")


PARENT = "1" * 40
STAGING = "2" * 40
CANDIDATE_DIGEST = "a" * 64
RELEASE_DIGEST = "b" * 64
PROOF_DIGEST = "c" * 64
PAYLOAD_DIGEST = "d" * 64


def _plan() -> PublicationPlan:
    release_id = f"sha256-{RELEASE_DIGEST}"
    return PublicationPlan(
        schema_version=STATE_LAWS_PLAN_SCHEMA,
        repository_id=stage.DEFAULT_DATASET_REPO,
        repository_type="dataset",
        release_id=release_id,
        release_prefix=f"releases/{release_id}",
        release_sha256=RELEASE_DIGEST,
        operations=(
            PublicationFilePlan(
                relative_path="manifest.json",
                remote_path=f"releases/{release_id}/manifest.json",
                size_bytes=7,
                sha256="e" * 64,
            ),
        ),
        cost_receipt={"currency": "USD", "estimated_cost_usd": 0.0},
        audited_parent_commit=PARENT,
        target_revision=stage.DEFAULT_STAGING_BRANCH,
        prohibited_operations=BASE_PROHIBITED_OPERATIONS,
    )


def _candidate() -> dict[str, str]:
    return {
        "report_digest_sha256": CANDIDATE_DIGEST,
        "manifest_digest": RELEASE_DIGEST,
    }


def _mutation(
    plan: PublicationPlan, *, method: str, result: str, approval_id: str
) -> CanonicalLegalCorporaMutationReceipt:
    return CanonicalLegalCorporaMutationReceipt(
        phase=stage.PUBLICATION_PHASE,
        method=method,
        operation=stage.AUTHORIZED_OPERATION,
        repository_id=stage.DEFAULT_DATASET_REPO,
        revision=stage.DEFAULT_STAGING_BRANCH,
        parent_commit=PARENT,
        resulting_commit_sha=result,
        plan_digest=plan.plan_digest,
        release_manifest_digest=RELEASE_DIGEST,
        policy_proof_digest=PROOF_DIGEST,
        payload_digest=PAYLOAD_DIGEST,
        approval_id=approval_id,
    )


def _live_receipt() -> dict:
    plan = _plan()
    controls = StateLawsStagingControlBundle(
        candidate_manifest_digest=CANDIDATE_DIGEST,
        candidate_path="docs/reports/legal_corpora_reindex/release_candidate.json",
        dataset_card_path="README.md",
        dataset_card_sha256="f" * 64,
        plan_digest=plan.plan_digest,
        policy_proof_digest=PROOF_DIGEST,
        release_manifest_digest=RELEASE_DIGEST,
        source_rights_receipt_digest="9" * 64,
        staging_branch=stage.DEFAULT_STAGING_BRANCH,
    )
    return stage.build_canonical_staging_live_receipt(
        candidate=_candidate(),
        plan=plan,
        control_bundle=controls,
        branch_receipt=_mutation(
            plan, method="create_branch", result=PARENT, approval_id="branch-approval"
        ),
        commit_receipt=_mutation(
            plan, method="create_commit", result=STAGING, approval_id="commit-approval"
        ),
    )


def test_identity_help_and_no_alternate_protected_writer() -> None:
    assert stage.TASK_ID == "LCR-040"
    assert stage.PUBLICATION_PHASE == "state_staging"
    assert stage.main(["--help"]) == 0
    source = Path(stage.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "HfApi",
        "upload_folder",
        "authorize_and_mutate",
        "invoke_protected_hf_write",
    ):
        assert forbidden not in source
    assert "execute_canonical_legal_corpora_mutation" in source


def test_canonical_dry_run_is_non_authorizing_and_manifest_bound() -> None:
    receipt = stage.build_canonical_staging_dry_run_receipt(
        candidate=_candidate(), plan=_plan()
    )
    assert receipt["status"] == "dry_run_only"
    assert receipt["final_manifest_digest"] == CANDIDATE_DIGEST
    assert receipt["release_manifest_digest"] == RELEASE_DIGEST
    assert receipt["remote_mutation_attempted"] is False
    assert receipt["uploaded"] == []
    assert len(receipt["operations"]) == 1


def test_live_receipt_binds_two_distinct_one_shot_mutations() -> None:
    receipt = _live_receipt()
    assert stage.check_canonical_staging_receipt(receipt)["staging_sha"] == STAGING
    assert receipt["branch_mutation"]["method"] == "create_branch"
    assert receipt["commit_mutation"]["method"] == "create_commit"
    assert receipt["branch_mutation"]["approval_id"] != receipt["commit_mutation"][
        "approval_id"
    ]
    assert receipt["uploaded"] == [
        {
            key: receipt["operations"][0][key]
            for key in ("relative_path", "remote_path", "sha256", "size_bytes")
        }
    ]


def test_same_authorization_cannot_cover_branch_and_commit() -> None:
    plan = _plan()
    controls = StateLawsStagingControlBundle(
        CANDIDATE_DIGEST,
        "docs/reports/legal_corpora_reindex/release_candidate.json",
        "README.md",
        "f" * 64,
        plan.plan_digest,
        PROOF_DIGEST,
        RELEASE_DIGEST,
        "9" * 64,
        stage.DEFAULT_STAGING_BRANCH,
    )
    with pytest.raises(stage.StageReceiptError, match="distinct one-shot"):
        stage.build_canonical_staging_live_receipt(
            candidate=_candidate(),
            plan=plan,
            control_bundle=controls,
            branch_receipt=_mutation(
                plan, method="create_branch", result=PARENT, approval_id="same"
            ),
            commit_receipt=_mutation(
                plan, method="create_commit", result=STAGING, approval_id="same"
            ),
        )


def test_tampering_fails_closed() -> None:
    tampered = copy.deepcopy(_live_receipt())
    tampered["operations"][0]["sha256"] = "0" * 64
    with pytest.raises(stage.StageReceiptError, match="digest mismatch"):
        stage.check_canonical_staging_receipt(tampered)


def test_executor_wrapper_delegates_only_to_canonical_runtime(tmp_path: Path) -> None:
    calls: list[tuple] = []

    class Publisher:
        def execute_canonical_legal_corpora_mutation(self, *args, **kwargs):
            calls.append((args, kwargs))
            return "receipt"

    result = stage.execute_staging_mutation(
        publisher=Publisher(),
        plan="plan",
        approval="approval",
        local_root=tmp_path,
        mutation_method="create_branch",
        policy_proof_digest=PROOF_DIGEST,
    )
    assert result == "receipt"
    assert calls[0][1]["publication_phase"] == "state_staging"
    assert calls[0][1]["mutation_method"] == "create_branch"
    with pytest.raises(stage.StageSafetyError):
        stage.execute_staging_mutation(
            publisher=Publisher(),
            plan="plan",
            approval="approval",
            local_root=tmp_path,
            mutation_method="upload_folder",
            policy_proof_digest=PROOF_DIGEST,
        )


def test_check_cli_is_read_only_and_detects_tampering(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    target.write_text(json.dumps(_live_receipt()), encoding="utf-8")
    before = target.read_bytes()
    assert stage.main(["--check-receipt", "--receipt", str(target)]) == 0
    assert target.read_bytes() == before
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["unexpected_operations"] = ["delete"]
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert stage.main(["--check-receipt", "--receipt", str(target)]) == 1
