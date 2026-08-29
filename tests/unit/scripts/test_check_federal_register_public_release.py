"""Hermetic public-revision verification controls for LCR-066."""

from __future__ import annotations

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    DEFAULT_OBSERVATION_CUTOFF,
    required_semantic_families,
)


MODULE = "scripts.ops.legal_data.check_federal_register_public_release"


@pytest.fixture(scope="module")
def check():
    return importlib.import_module(MODULE)


@pytest.fixture(scope="module")
def bundle(check):
    release = check.build_fixture_release()
    candidate = {
        "dataset_repo_id": check.DEFAULT_DATASET_REPO,
        "manifest_digest": release.manifest_digest,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "release_point": "federal-register/v2/test",
        "release_profile": "federal-register-ir-graphrag/v2",
        "release_root_cid": release.release_root_cid,
        "required_semantic_families": list(required_semantic_families()),
    }
    plan = check.plan_public_from_candidate(
        candidate,
        release=release,
        staging_revision="a" * 40,
        publication_seal=(
            "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json"
        ),
        dry_run=False,
    )
    candidate["descriptors"] = [dict(item) for item in plan["artifacts"]]
    files = check.release_file_bytes(release)
    receipt = {
        "final_manifest_digest": plan["manifest_digest"],
        "fixture_only": False,
        "live_network": True,
        "manifest_digest": plan["manifest_digest"],
        "mutation_executed": True,
        "old_sha": check.PRODUCTION_REVISION,
        "plan_digest": "b" * 64,
        "public_revision": "c" * 40,
        "public_sha": "c" * 40,
        "remote_write_contacted": True,
        "schema": (
            "ipfs_datasets_py/legal-corpora-reindex-federal-publication-receipt@1"
        ),
        "staging_revision": "a" * 40,
        "staging_sha": "a" * 40,
        "status": "published",
        "target_repo": check.DEFAULT_DATASET_REPO,
        "task_id": "LCR-065",
    }
    inventory = {
        "acceptance": {"failed_final": 0},
        "counts": {"failed_final": 0, "official_total": 2},
        "dataset_repo_id": check.DEFAULT_DATASET_REPO,
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
        "previous_public_pin": check.PRODUCTION_REVISION,
    }
    admission = {
        "acceptance": {
            "admission_recovery_reconciled": True,
            "failed_final": 0,
            "failed_final_zero": True,
            "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
            "one_disposition_per_input": True,
        },
        "admission_recovery_ledger": {"coverage_dispositions": {}},
        "observation_cutoff": DEFAULT_OBSERVATION_CUTOFF,
    }
    return {
        "admission": admission,
        "candidate": candidate,
        "files": files,
        "inventory": inventory,
        "plan": plan,
        "receipt": receipt,
        "release": release,
    }


def _live_report(check, bundle) -> dict:
    def fetch(repo_id: str, revision: str, path: str) -> bytes:
        assert repo_id == check.DEFAULT_DATASET_REPO
        assert revision == bundle["receipt"]["public_sha"]
        return bundle["files"][path]

    return check.run_remote_canary(
        repo_id=check.DEFAULT_DATASET_REPO,
        revision=bundle["receipt"]["public_sha"],
        publication_receipt=bundle["receipt"],
        candidate=bundle["candidate"],
        artifact_descriptors=bundle["plan"]["artifacts"],
        remote_descriptors=bundle["plan"]["artifacts"],
        fetch_file=fetch,
        inventory=bundle["inventory"],
        admission=bundle["admission"],
        fulltext={},
    )


def test_help_identity_and_read_only_source(check) -> None:
    assert check.main(["--help"]) == 0
    assert check.TASK_ID == "LCR-066"
    assert check.DEFAULT_DATASET_REPO == "justicedao/ipfs_federal_register"
    source = Path(check.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "HfApi",
        "upload_folder",
        "invoke_protected_hf_write",
        "authorize_and_mutate(",
    ):
        assert forbidden not in source
    assert "fetch_file" in source
    assert "immutable_hub_read_only" in source


def test_remote_canary_binds_complete_descriptors_and_bounded_bytes(
    check, bundle
) -> None:
    report = _live_report(check, bundle)
    assert report["fixture_only"] is False
    assert report["live_public"] is True
    assert report["live_network"] is True
    assert report["read_only"] is True
    assert report["mutation_executed"] is False
    assert report["remote_write_contacted"] is False
    assert report["transport"] == "immutable_hub_read_only"
    assert report["public_sha"] == bundle["receipt"]["public_sha"]
    assert report["manifest_parity"]["exact_match"] is True
    assert report["canary"]["within_budget"] is True
    check.assert_public_pin_contract(report)


def test_fixture_or_offline_report_never_satisfies_public_contract(check, bundle) -> None:
    report = _live_report(check, bundle)
    for field, value in (
        ("fixture_only", True),
        ("live_network", False),
        ("transport", "in_memory_fixture_public"),
        ("operations", ["upload"]),
    ):
        tampered = {**report, field: value}
        with pytest.raises(check.PublicPinError):
            check.assert_public_pin_contract(tampered)


def test_remote_canary_rejects_mutable_missing_and_fixture_receipts(
    check, bundle
) -> None:
    with pytest.raises(check.PublicRemoteError):
        check.run_remote_canary(repo_id=check.DEFAULT_DATASET_REPO, revision="main")
    with pytest.raises(check.PublicRemoteError):
        check.run_remote_canary(
            repo_id=check.DEFAULT_DATASET_REPO,
            revision="c" * 40,
        )
    fixture_receipt = {**bundle["receipt"], "fixture_only": True}
    with pytest.raises(check.PublicRemoteError, match="fixture"):
        check.run_remote_canary(
            repo_id=check.DEFAULT_DATASET_REPO,
            revision="c" * 40,
            publication_receipt=fixture_receipt,
        )


def test_remote_descriptor_and_byte_tamper_fail_closed(check, bundle) -> None:
    descriptors = [dict(item) for item in bundle["plan"]["artifacts"]]
    descriptors[0]["sha256"] = "0" * 64
    with pytest.raises(check.PublicParityError):
        check.run_remote_canary(
            repo_id=check.DEFAULT_DATASET_REPO,
            revision="c" * 40,
            publication_receipt=bundle["receipt"],
            candidate=bundle["candidate"],
            artifact_descriptors=bundle["plan"]["artifacts"],
            remote_descriptors=descriptors,
            fetch_file=lambda *_: b"",
            inventory=bundle["inventory"],
            admission=bundle["admission"],
            fulltext={},
        )

    target = next(iter(bundle["files"]))

    def tampered_fetch(_repo: str, _revision: str, path: str) -> bytes:
        if path == target:
            return b"tampered"
        return bundle["files"][path]

    with pytest.raises(check.PublicParityError):
        check.run_remote_canary(
            repo_id=check.DEFAULT_DATASET_REPO,
            revision="c" * 40,
            publication_receipt=bundle["receipt"],
            candidate=bundle["candidate"],
            artifact_descriptors=bundle["plan"]["artifacts"],
            remote_descriptors=bundle["plan"]["artifacts"],
            fetch_file=tampered_fetch,
            inventory=bundle["inventory"],
            admission=bundle["admission"],
            fulltext={},
        )


def test_fixture_report_cannot_replace_canonical_evidence(check, bundle, tmp_path) -> None:
    fixture = deepcopy(_live_report(check, bundle))
    fixture["fixture_only"] = True
    fixture["live_network"] = False
    fixture["live_public"] = False
    fixture = check.seal_report(fixture)
    with pytest.raises(check.PublicPinError):
        check.write_canary_report(fixture, repo_root=tmp_path)
    explicit = tmp_path / "fixture-public-canary.json"
    assert check.write_canary_report(fixture, path=explicit) == explicit


def test_sealed_live_check_does_not_rebuild_fakehub(
    check, bundle, tmp_path, monkeypatch
) -> None:
    report = _live_report(check, bundle)
    report_path = tmp_path / check.DEFAULT_REPORT_RELPATH
    receipt_path = tmp_path / check.DEFAULT_RECEIPT_RELPATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    receipt_path.write_text(json.dumps(bundle["receipt"]), encoding="utf-8")
    monkeypatch.setattr(
        check,
        "check_publication_receipt",
        lambda *_args, **_kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        check,
        "build_federal_public_canary_report",
        lambda **_kwargs: pytest.fail("live check must not rebuild fixture evidence"),
    )
    result = check.check_federal_public_release(
        path=report_path,
        repo_root=tmp_path,
        require_public_pin=True,
    )
    assert result["ok"] is True
    assert result["fixture_only"] is False
    assert result["public_sha"] == bundle["receipt"]["public_sha"]


def test_publication_receipt_loader_rejects_mutable_or_equal_pins(
    check, bundle, tmp_path
) -> None:
    path = tmp_path / "receipt.json"
    bad = {**bundle["receipt"], "public_sha": "main", "public_revision": "main"}
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises((check.PublicPinError, check.PublishFederalRegisterError)):
        check.load_publication_receipt(path)
    equal = {
        **bundle["receipt"],
        "public_sha": bundle["receipt"]["old_sha"],
        "public_revision": bundle["receipt"]["old_sha"],
    }
    path.write_text(json.dumps(equal), encoding="utf-8")
    with pytest.raises(check.PublicPinError):
        check.load_publication_receipt(path)


def test_network_cli_without_injected_reader_fails_closed(check) -> None:
    assert check.main(
        [
            "--network",
            "--repo-id",
            check.DEFAULT_DATASET_REPO,
            "--revision",
            "c" * 40,
        ]
    ) == 2


def test_secret_guards(check) -> None:
    with pytest.raises(check.PublishSafetyError):
        check.reject_secrets_in_argv(["--hf_token=hf_abcdefghijklmnopqrstuvwxyz"])
    with pytest.raises(check.PublishSafetyError):
        check.reject_credentials_in_payload(
            {"path": "/home/operator/private"}, label="test"
        )
