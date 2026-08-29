"""Hermetic publication controls for the Federal Register main release (LCR-065)."""

from __future__ import annotations

import importlib
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    DEFAULT_OBSERVATION_CUTOFF,
)


MODULE = "scripts.ops.legal_data.publish_federal_register_hf_release"


@pytest.fixture(scope="module")
def publish():
    return importlib.import_module(MODULE)


@pytest.fixture(scope="module")
def bundle(publish):
    release = publish.build_fixture_release()
    candidate = {
        "dataset_repo_id": publish.DEFAULT_DATASET_REPO,
        "manifest_digest": release.manifest_digest,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "release_point": "federal-register/v2/test",
        "release_profile": "federal-register-ir-graphrag/v2",
        "release_root_cid": release.release_root_cid,
    }
    plan = publish.plan_public_from_candidate(
        candidate,
        release=release,
        staging_revision="a" * 40,
        publication_seal=publish.DEFAULT_SEAL_RELPATH.as_posix(),
        dry_run=False,
    )
    return {"candidate": candidate, "plan": plan, "release": release}


def _seal(publish, plan) -> dict:
    return {
        "dataset_repo_id": publish.DEFAULT_DATASET_REPO,
        "final_manifest_digest": plan["manifest_digest"],
        "manifest_digest": plan["manifest_digest"],
        "path": publish.DEFAULT_SEAL_RELPATH.as_posix(),
        "present": True,
        "previous_public_pin": plan["old_sha"],
        "staging_revision": plan["staging_revision"],
        "task_id": publish.SEAL_TASK_ID,
        "timing": "before_mutation",
        "verified_before_first_mutation": True,
    }


def _gate(publish) -> dict:
    return {
        "authorized": True,
        "dataset_repo_id": publish.DEFAULT_DATASET_REPO,
        "invoked_before_first_mutation": True,
        "network_mutation_permitted": False,
        "operation": publish.AUTHORIZED_OPERATION,
        "passed_gates": ["fixture_contract"],
        "phase": publish.PUBLICATION_PHASE,
        "previous_public_pin": publish.PRODUCTION_REVISION,
        "task_id": publish.GATE_TASK_ID,
    }


def _fixture_receipt(publish, bundle) -> dict:
    hub = publish.FakeFederalRegisterPublicHub()
    upload = hub.upload_files(
        publish.release_file_bytes(bundle["release"]),
        repo_id=publish.DEFAULT_DATASET_REPO,
        branch=publish.PUBLIC_BRANCH,
        base_revision=publish.PRODUCTION_REVISION,
    )
    return publish.build_publication_receipt(
        bundle["plan"],
        seal=_seal(publish, bundle["plan"]),
        gate=_gate(publish),
        dry_run=False,
        mutation_executed=True,
        live_network=False,
        public_revision=upload["public_revision"],
        uploaded=upload["uploaded"],
        skipped=upload["skipped"],
        operations=upload["operations"],
        responses=upload["responses"],
        hub=hub,
    )


def test_help_identity_and_no_direct_writer(publish) -> None:
    assert publish.main(["--help"]) == 0
    assert publish.TASK_ID == "LCR-065"
    assert publish.PUBLICATION_PHASE == "federal_main"
    assert publish.DEFAULT_DATASET_REPO == "justicedao/ipfs_federal_register"
    source = Path(publish.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "HfApi",
        "upload_folder",
        "upload_file(",
        "invoke_protected_hf_write",
        "authorize_and_mutate(",
    ):
        assert forbidden not in source
    assert "execute_canonical_legal_corpora_mutation" in source


def test_public_plan_is_deterministic_additive_and_exact(publish, bundle) -> None:
    first = publish.plan_public_from_candidate(
        bundle["candidate"],
        release=bundle["release"],
        staging_revision="a" * 40,
        publication_seal=publish.DEFAULT_SEAL_RELPATH.as_posix(),
        dry_run=False,
    )
    assert first == bundle["plan"]
    assert first["old_sha"] == publish.PRODUCTION_REVISION
    assert first["public_branch"] == "main"
    assert first["operations"] == ["add_only_upload"]
    assert first["legacy_files_deleted"] is False
    with pytest.raises(publish.PublishTargetError):
        publish.plan_public_from_candidate(
            bundle["candidate"],
            release=bundle["release"],
            public_branch="dev",
            staging_revision="a" * 40,
        )


def test_canonical_main_plan_uses_shared_publication_package(
    publish, bundle, tmp_path
) -> None:
    package, publisher, plan = publish.build_canonical_main_plan(
        release=bundle["release"],
        output_root=tmp_path / "release",
        candidate=bundle["candidate"],
    )
    assert package.manifest_digest == bundle["release"].manifest_digest
    assert publisher.repository_id == publish.DEFAULT_DATASET_REPO
    assert plan.repository_id == publish.DEFAULT_DATASET_REPO
    assert plan.target_revision == publish.PUBLIC_BRANCH
    assert plan.audited_parent_commit == publish.PRODUCTION_REVISION
    assert plan.remote_write_contacted is False
    assert all(item.operation == "add" for item in plan.operations)


def test_main_commit_dispatches_only_to_canonical_runtime(publish) -> None:
    class Recorder:
        def __init__(self) -> None:
            self.calls = []

        def execute_canonical_legal_corpora_mutation(self, plan, **kwargs):
            self.calls.append((plan, kwargs))
            return "receipt"

    publisher = Recorder()
    plan = object()
    result = publish.execute_canonical_federal_publication(
        publisher,
        plan,
        approval=object(),
        local_root=".",
        policy_proof_digest="b" * 64,
        commit_message="publish Federal release",
    )
    assert result == "receipt"
    assert len(publisher.calls) == 1
    assert publisher.calls[0][0] is plan
    kwargs = publisher.calls[0][1]
    assert kwargs["publication_phase"] == "federal_main"
    assert kwargs["mutation_method"] == "create_commit"


def test_missing_canonical_runtime_fails_closed(publish) -> None:
    with pytest.raises(publish.PublishAuthorizationError):
        publish.execute_canonical_federal_publication(
            object(),
            object(),
            approval=object(),
            local_root=".",
            policy_proof_digest="b" * 64,
        )


def test_fixture_receipt_is_non_live_and_self_consistent(publish, bundle) -> None:
    receipt = _fixture_receipt(publish, bundle)
    assert receipt["fixture_only"] is True
    assert receipt["live_network"] is False
    assert receipt["live_publication"] is False
    assert receipt["remote_write_contacted"] is False
    assert receipt["status"] == "fixture_published"
    assert receipt["transport"] == "in_memory_fixture_public"
    result = publish.check_publication_receipt(receipt, require_live=False)
    assert result["ok"] is True
    assert result["require_live"] is False


def test_fixture_receipt_cannot_replace_canonical_evidence(
    publish, bundle, tmp_path
) -> None:
    receipt = _fixture_receipt(publish, bundle)
    with pytest.raises(publish.PublishReceiptError):
        publish.write_publication_receipt(receipt, repo_root=tmp_path)
    explicit = tmp_path / "fixture-publication.json"
    assert publish.write_publication_receipt(receipt, path=explicit) == explicit


def test_receipt_tamper_and_live_requirement_fail_closed(publish, bundle) -> None:
    receipt = _fixture_receipt(publish, bundle)
    tampered = deepcopy(receipt)
    tampered["upload_responses"][0]["sha256"] = "0" * 64
    with pytest.raises(publish.PublishReceiptError, match="content_digest"):
        publish.check_publication_receipt(tampered, require_live=False)
    with pytest.raises((publish.PublishReceiptError, publish.PublishSealError)):
        publish.check_publication_receipt(receipt, require_live=True)


def test_seal_contract_rejects_fixture_post_hoc_and_wrong_target(publish, bundle) -> None:
    base = {
        "dataset_repo_id": publish.DEFAULT_DATASET_REPO,
        "dirty": False,
        "final_manifest_digest": bundle["plan"]["manifest_digest"],
        "fixture_only": False,
        "manifest_digest": bundle["plan"]["manifest_digest"],
        "mutation_executed": False,
        "network_mutation": False,
        "no_mutation": True,
        "phase": publish.PUBLICATION_PHASE,
        "present": True,
        "previous_public_pin": publish.PRODUCTION_REVISION,
        "staging_revision": "a" * 40,
        "status": "sealed",
        "task_id": publish.SEAL_TASK_ID,
        "timing": "before_mutation",
    }
    assert publish.assert_seal_precedes_mutation(base)["staging_revision"] == "a" * 40
    for field, value in (
        ("fixture_only", True),
        ("timing", "after_mutation"),
        ("dataset_repo_id", "someone/else"),
    ):
        bad = {**base, field: value}
        with pytest.raises(publish.PublishFederalRegisterError):
            publish.assert_seal_precedes_mutation(bad)


def test_cli_live_mutation_without_runtime_fails_closed(publish) -> None:
    assert publish.main(["--authorize-mutation"]) == 2


def test_secret_guards(publish) -> None:
    with pytest.raises(publish.PublishSafetyError):
        publish.reject_secrets_in_argv(["--hf_token=hf_abcdefghijklmnopqrstuvwxyz"])
    with pytest.raises(publish.PublishSafetyError):
        publish.reject_credentials_in_payload(
            {"path": "/home/operator/private"}, label="test"
        )
