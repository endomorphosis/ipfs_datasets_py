"""Hermetic controls for Federal Register staging and its canary (LCR-064)."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    DEFAULT_OBSERVATION_CUTOFF,
    PREVIOUS_PUBLIC_PIN,
    required_semantic_families,
)


STAGE_MODULE = "scripts.ops.legal_data.stage_federal_register_hf_release"
CANARY_MODULE = "scripts.ops.legal_data.canary_federal_register_hf_release"


@pytest.fixture(scope="module")
def stage():
    return importlib.import_module(STAGE_MODULE)


@pytest.fixture(scope="module")
def canary():
    return importlib.import_module(CANARY_MODULE)


@pytest.fixture(scope="module")
def bundle(stage):
    release = stage.build_fixture_release()
    candidate = {
        "dataset_repo_id": stage.DEFAULT_DATASET_REPO,
        "manifest_digest": release.manifest_digest,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "release_point": "federal-register/v2/test",
        "release_profile": "federal-register-ir-graphrag/v2",
        "release_root_cid": release.release_root_cid,
        "required_semantic_families": list(required_semantic_families()),
    }
    plan = stage.plan_stage_from_candidate(
        candidate,
        release=release,
        dry_run=False,
    )
    candidate["descriptors"] = [dict(item) for item in plan["artifacts"]]
    inventory = {
        "acceptance": {"failed_final": 0},
        "counts": {"failed_final": 0, "official_total": 2},
        "dataset_repo_id": stage.DEFAULT_DATASET_REPO,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
    }
    return {
        "candidate": candidate,
        "files": stage.release_file_bytes(release),
        "inventory": inventory,
        "plan": plan,
        "release": release,
    }


def test_help_and_identity(stage, canary) -> None:
    assert stage.main(["--help"]) == 0
    assert canary.main(["--help"]) == 0
    assert stage.TASK_ID == canary.TASK_ID == "LCR-064"
    assert stage.DEFAULT_DATASET_REPO == "justicedao/ipfs_federal_register"
    assert stage.DEFAULT_STAGING_BRANCH.startswith("stage/")


def test_source_has_no_direct_protected_hub_writer(stage) -> None:
    source = Path(stage.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "HfApi",
        "upload_folder",
        "upload_file(",
        "invoke_protected_hf_write",
        "authorize_and_mutate(",
    ):
        assert forbidden not in source
    assert "execute_canonical_legal_corpora_mutation" in source


def test_stage_plan_is_deterministic_add_only_and_safe(stage, bundle) -> None:
    first = stage.plan_stage_from_candidate(
        bundle["candidate"], release=bundle["release"], dry_run=False
    )
    second = stage.plan_stage_from_candidate(
        bundle["candidate"], release=bundle["release"], dry_run=False
    )
    assert first == second
    assert first["manifest_digest"] == bundle["release"].manifest_digest
    assert first["operations"] == ["add_only_upload"]
    assert first["upload_file_count"] == len(first["artifacts"])
    assert all(not item["relative_path"].startswith("/") for item in first["artifacts"])
    with pytest.raises(stage.StageProductionTargetError):
        stage.plan_stage_from_candidate(
            bundle["candidate"],
            release=bundle["release"],
            staging_branch="main",
        )


def test_canonical_stage_plan_uses_shared_publication_package(
    stage, bundle, tmp_path
) -> None:
    package, publisher, plan = stage.build_canonical_staging_plan(
        release=bundle["release"],
        output_root=tmp_path / "release",
        candidate=bundle["candidate"],
    )
    assert package.manifest_digest == bundle["release"].manifest_digest
    assert publisher.repository_id == stage.DEFAULT_DATASET_REPO
    assert plan.repository_id == stage.DEFAULT_DATASET_REPO
    assert plan.target_revision == stage.DEFAULT_STAGING_BRANCH
    assert plan.audited_parent_commit == stage.PRODUCTION_REVISION
    assert plan.remote_write_contacted is False
    assert all(item.operation == "add" for item in plan.operations)


def test_branch_and_commit_are_separately_runtime_authorized(stage) -> None:
    class Recorder:
        def __init__(self) -> None:
            self.calls = []

        def execute_canonical_legal_corpora_mutation(self, plan, **kwargs):
            self.calls.append((plan, kwargs))
            return kwargs["mutation_method"]

    publisher = Recorder()
    common = {
        "approval": object(),
        "local_root": ".",
        "policy_proof_digest": "a" * 64,
    }
    branch_plan = object()
    commit_plan = object()
    assert (
        stage.create_canonical_federal_staging_branch(
            publisher, branch_plan, **common
        )
        == "create_branch"
    )
    assert (
        stage.commit_canonical_federal_staging_candidate(
            publisher, commit_plan, commit_message="stage candidate", **common
        )
        == "create_commit"
    )
    assert [item[1]["mutation_method"] for item in publisher.calls] == [
        "create_branch",
        "create_commit",
    ]
    assert publisher.calls[0][0] is branch_plan
    assert publisher.calls[1][0] is commit_plan


def test_missing_canonical_runtime_fails_closed(stage) -> None:
    with pytest.raises(stage.StageAuthorizationError):
        stage.create_canonical_federal_staging_branch(
            object(),
            object(),
            approval=object(),
            local_root=".",
            policy_proof_digest="a" * 64,
        )


def test_fixture_transport_is_explicitly_non_live(stage, bundle) -> None:
    receipt = stage.execute_stage(
        bundle["plan"],
        release=bundle["release"],
        hub=stage.FakeFederalRegisterHub(),
        authorize_mutation=True,
        dry_run=False,
        environ={stage.AUTHORIZATION_ENV: "test-only-fixture"},
    )
    assert receipt["fixture_only"] is True
    assert receipt["live_network"] is False
    assert receipt["remote_write_contacted"] is False
    assert receipt["transport"] == "in_memory_fixture_staging"
    assert receipt["mutation_executed"] is True


def test_fixture_canary_is_honest_and_cannot_replace_live_evidence(
    canary, bundle, tmp_path
) -> None:
    loop = canary.run_live_staging_loop(
        candidate=bundle["candidate"],
        inventory=bundle["inventory"],
        fulltext={},
    )
    report = canary.build_federal_staging_canary_report(loop=loop)
    assert report["fixture_only"] is True
    assert report["live_staging"] is False
    assert report["live_network"] is False
    assert report["mutation_executed"] is False
    assert report["transport"] == "in_memory_fixture_staging"
    with pytest.raises(canary.CanaryLiveStagingError):
        canary.assert_live_staging_contract(report)
    with pytest.raises(canary.CanaryLiveStagingError):
        canary.write_canary_report(report, repo_root=tmp_path)
    explicit = tmp_path / "fixture-canary.json"
    assert canary.write_canary_report(report, path=explicit) == explicit


def _live_staging_receipt(canary, bundle, revision: str, gate) -> dict:
    return {
        "base_revision": bundle["plan"]["base_revision"],
        "candidate_manifest_digest": bundle["plan"]["manifest_digest"],
        "fixture_only": False,
        "gate": dict(gate),
        "live_network": True,
        "manifest_digest": bundle["plan"]["manifest_digest"],
        "mutation_executed": True,
        "plan_digest": "b" * 64,
        "policy_proof_digest": "c" * 64,
        "release_manifest_digest": bundle["plan"]["manifest_digest"],
        "staged_diff_digest": bundle["plan"]["staged_diff_digest"],
        "staging_branch": bundle["plan"]["staging_branch"],
        "staging_candidate_digest": bundle["plan"]["manifest_digest"],
        "staging_revision": revision,
        "target_repo": canary.DEFAULT_DATASET_REPO,
    }


def test_remote_canary_rehashes_bounded_live_bytes(canary, bundle) -> None:
    fixture_loop = canary.run_live_staging_loop(
        candidate=bundle["candidate"],
        inventory=bundle["inventory"],
        fulltext={},
    )
    revision = "d" * 40
    receipt = _live_staging_receipt(
        canary, bundle, revision, fixture_loop["gate"]
    )

    def fetch(repo_id: str, pin: str, path: str) -> bytes:
        assert repo_id == canary.DEFAULT_DATASET_REPO
        assert pin == revision
        return bundle["files"][path]

    report = canary.run_remote_canary(
        repo_id=canary.DEFAULT_DATASET_REPO,
        revision=revision,
        staging_receipt=receipt,
        candidate=bundle["candidate"],
        artifact_descriptors=bundle["plan"]["artifacts"],
        remote_descriptors=bundle["plan"]["artifacts"],
        fetch_file=fetch,
        inventory=bundle["inventory"],
        fulltext={},
    )
    assert report["fixture_only"] is False
    assert report["live_staging"] is True
    assert report["live_network"] is True
    assert report["transport"] == "immutable_hub_read_only"
    assert report["staging_revision"] == revision
    assert report["canary"]["within_budget"] is True
    canary.assert_live_staging_contract(report)


def test_remote_canary_rejects_tamper_mutable_pins_and_missing_receipt(
    canary, bundle
) -> None:
    with pytest.raises(canary.CanaryRemoteError):
        canary.run_remote_canary(
            repo_id=canary.DEFAULT_DATASET_REPO,
            revision="main",
        )
    with pytest.raises(canary.CanaryRemoteError):
        canary.run_remote_canary(
            repo_id=canary.DEFAULT_DATASET_REPO,
            revision="d" * 40,
        )
    descriptors = [dict(item) for item in bundle["plan"]["artifacts"]]
    descriptors[0]["sha256"] = hashlib.sha256(b"tampered").hexdigest()
    receipt = {
        "fixture_only": False,
        "live_network": True,
        "mutation_executed": True,
        "staging_revision": "d" * 40,
        "target_repo": canary.DEFAULT_DATASET_REPO,
    }
    with pytest.raises(canary.CanaryParityError):
        canary.run_remote_canary(
            repo_id=canary.DEFAULT_DATASET_REPO,
            revision="d" * 40,
            staging_receipt=receipt,
            candidate=bundle["candidate"],
            artifact_descriptors=bundle["plan"]["artifacts"],
            remote_descriptors=descriptors,
            fetch_file=lambda *_: b"",
            inventory=bundle["inventory"],
            fulltext={},
        )


def test_network_entrypoint_wires_injected_live_evidence(
    canary, bundle, monkeypatch
) -> None:
    revision = "e" * 40
    sentinel = {
        "fixture_only": False,
        "status": "passed",
        "staging_revision": revision,
    }
    captured = {}

    def run_remote_canary(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(canary, "run_remote_canary", run_remote_canary)
    monkeypatch.setattr(canary, "write_json", lambda *_args, **_kwargs: None)
    receipt = {"fixture_only": False}
    descriptors = bundle["plan"]["artifacts"]
    fetch = lambda *_args: b""
    assert canary.main(
        [
            "--network",
            "--repo-id",
            canary.DEFAULT_DATASET_REPO,
            "--revision",
            revision,
        ],
        staging_receipt=receipt,
        candidate=bundle["candidate"],
        artifact_descriptors=descriptors,
        remote_descriptors=descriptors,
        fetch_file=fetch,
        inventory=bundle["inventory"],
        fulltext={},
    ) == 0
    assert captured["staging_receipt"] is receipt
    assert captured["artifact_descriptors"] is descriptors
    assert captured["remote_descriptors"] is descriptors
    assert captured["fetch_file"] is fetch


def test_secret_and_path_guards(stage) -> None:
    with pytest.raises(stage.StageSafetyError):
        stage.reject_secrets_in_argv(["--hf_token=hf_abcdefghijklmnopqrstuvwxyz"])
    with pytest.raises(stage.StageSafetyError):
        stage.reject_credentials_in_payload(
            {"path": "/home/operator/private"}, label="test"
        )
