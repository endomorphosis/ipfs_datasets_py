"""LCR-073 no-mutate Federal Register prepublication seal tests."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

import scripts.ops.legal_data.seal_federal_register_prepublication as seal
from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (
    build_federal_register_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
)
from ipfs_datasets_py.processors.legal_data.federal_register_publication_package import (
    FederalRegisterCanonicalControlBundle,
    plan_federal_register_publication_dry_run,
    prepare_federal_register_publication_package,
)


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _candidate_digest(payload: dict) -> str:
    return sha256(
        _canonical(
            {key: value for key, value in payload.items() if key != "content_digest"}
        )
    ).hexdigest()


def _write_bound_fixture(root: Path) -> tuple[Path, dict[str, str]]:
    reports = root / "docs" / "reports" / "legal_corpora_reindex"
    reports.mkdir(parents=True)
    identities = {
        "plan": "1" * 64,
        "proof": "2" * 64,
        "release": "3" * 64,
        "revision": "4" * 40,
    }
    base = {
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "candidate": {
            "dataset_id": seal.TARGET_REPO,
            "manifest_digest": identities["release"],
        },
        "fixture_only": False,
        "hub_upload": False,
        "mode": "production",
        "publication_binding": None,
        "schema": "ipfs_datasets_py/legal-corpora-reindex-federal-candidate@1",
        "source_rights": {"receipt_digest": "5" * 64},
    }
    base["content_digest"] = _candidate_digest(base)
    staging_digest = base["content_digest"]
    candidate = dict(base)
    candidate["plan_digest"] = identities["plan"]
    candidate["policy_proof_digest"] = identities["proof"]
    candidate["publication_binding"] = {
        "plan_digest": identities["plan"],
        "policy_proof_digest": identities["proof"],
        "release_manifest_digest": identities["release"],
        "staging_candidate_digest": staging_digest,
    }
    candidate["content_digest"] = _candidate_digest(candidate)
    (reports / "federal_candidate.json").write_bytes(_canonical(candidate) + b"\n")
    canary = {
        "dataset_repo_id": seal.TARGET_REPO,
        "dirty": False,
        "final_manifest_digest": staging_digest,
        "fixture_only": False,
        "live_staging": True,
        "release_manifest_digest": identities["release"],
        "staging_revision": identities["revision"],
        "status": "passed",
    }
    (reports / "federal_staging_canary.json").write_bytes(
        _canonical(canary) + b"\n"
    )
    sealed = {
        "created_after_mutation": False,
        "dataset_repo_id": seal.TARGET_REPO,
        "dirty": False,
        "final_manifest_digest": candidate["content_digest"],
        "fixture_only": False,
        "manifest_digest": candidate["content_digest"],
        "mutation_executed": False,
        "network_mutation": False,
        "no_mutation": True,
        "operation": "additive_main_upload",
        "phase": "federal_main",
        "plan_digest": identities["plan"],
        "policy_proof_digest": identities["proof"],
        "post_hoc": False,
        "present": True,
        "previous_public_pin": seal.PREVIOUS_PUBLIC_PIN,
        "release_manifest_digest": identities["release"],
        "schema": seal.CANONICAL_SCHEMA,
        "staging_revision": identities["revision"],
        "status": "sealed",
        "task_id": seal.TASK_ID,
        "timing": "before_mutation",
    }
    sealed["content_digest"] = sha256(
        _canonical(
            {
                key: value
                for key, value in sealed.items()
                if key not in seal.SELF_DIGEST_FIELDS
            }
        )
    ).hexdigest()
    seal_path = reports / "federal_prepublication_seal.json"
    seal_path.write_bytes(_canonical(sealed) + b"\n")
    return seal_path, identities


def test_missing_no_mutate_fails_closed() -> None:
    with pytest.raises(seal.PrepublicationSealError, match="no-mutate"):
        seal.inspect_federal_prepublication_seal(
            require_live_staging_pin=True,
            no_mutate=False,
        )


def test_missing_live_staging_pin_fails_closed() -> None:
    with pytest.raises(seal.PrepublicationSealError, match="staging"):
        seal.inspect_federal_prepublication_seal(
            require_live_staging_pin=True,
            no_mutate=True,
        )


def test_cli_require_live_staging_exits_nonzero() -> None:
    assert (
        seal.main(["--require-live-staging-pin", "--no-mutate", "--check"]) == 1
    )


def test_strict_seal_binds_candidate_canary_and_is_read_only(tmp_path: Path) -> None:
    _write_bound_fixture(tmp_path)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    checked = seal.check_federal_prepublication_seal(repo_root=tmp_path)
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert checked["ok"] is True
    assert checked["live_staging"] is True
    assert before == after


def test_strict_seal_rejects_staging_identity_tamper(tmp_path: Path) -> None:
    _write_bound_fixture(tmp_path)
    canary_path = tmp_path / seal.STAGING_RELPATH
    canary = json.loads(canary_path.read_text(encoding="utf-8"))
    canary["final_manifest_digest"] = "9" * 64
    canary_path.write_bytes(_canonical(canary) + b"\n")
    with pytest.raises(seal.SealBindingError, match="candidate identity A"):
        seal.check_federal_prepublication_seal(repo_root=tmp_path)


def test_strict_seal_rejects_content_digest_tamper(tmp_path: Path) -> None:
    seal_path, _ = _write_bound_fixture(tmp_path)
    payload = json.loads(seal_path.read_text(encoding="utf-8"))
    payload["content_digest"] = "f" * 64
    seal_path.write_bytes(_canonical(payload) + b"\n")
    with pytest.raises(seal.SealBindingError, match="content digest"):
        seal.check_federal_prepublication_seal(repo_root=tmp_path)


def test_generation_api_materializes_then_checks_without_network(
    tmp_path: Path, monkeypatch
) -> None:
    release = build_federal_register_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
    )
    package = prepare_federal_register_publication_package(
        release,
        output_root=tmp_path / "release",
    )
    plan = plan_federal_register_publication_dry_run(
        package,
        audited_parent_commit=seal.PREVIOUS_PUBLIC_PIN,
        target_revision="main",
    )
    controls = FederalRegisterCanonicalControlBundle(
        phase="federal_main",
        candidate_manifest_digest="1" * 64,
        staging_candidate_digest="2" * 64,
        candidate_path=seal.CANDIDATE_RELPATH.as_posix(),
        dataset_card_path="README.md",
        dataset_card_sha256="3" * 64,
        release_manifest_digest=package.manifest_digest,
        plan_digest=plan.plan_digest,
        policy_proof_digest="4" * 64,
        source_rights_receipt_digest=package.source_rights_receipt_digest,
        staging_revision="5" * 40,
        seal_path=seal.SEAL_RELPATH.as_posix(),
        seal_content_digest="6" * 64,
    )
    calls = []

    def materialize(*args, **kwargs):
        calls.append((args, kwargs))
        return controls

    checked = {
        "final_manifest_digest": controls.candidate_manifest_digest,
        "plan_digest": controls.plan_digest,
        "policy_proof_digest": controls.policy_proof_digest,
        "release_manifest_digest": controls.release_manifest_digest,
        "staging_revision": controls.staging_revision,
    }
    monkeypatch.setattr(seal, "materialize_federal_register_main_controls", materialize)
    monkeypatch.setattr(
        seal,
        "check_federal_prepublication_seal",
        lambda **_kwargs: dict(checked),
    )
    generated, result = seal.generate_federal_prepublication_seal(
        package=package,
        plan=plan,
        staging_revision=controls.staging_revision,
        sealed_at="2026-08-29T12:00:00Z",
        repository_root=tmp_path,
        no_mutate=True,
    )
    assert generated is controls
    assert result == checked
    assert len(calls) == 1


def test_generation_api_requires_no_mutate(tmp_path: Path) -> None:
    with pytest.raises(seal.SealFederalRegisterError, match="no_mutate"):
        seal.generate_federal_prepublication_seal(
            package=object(),
            plan=object(),
            staging_revision="5" * 40,
            sealed_at="2026-08-29T12:00:00Z",
            repository_root=tmp_path,
            no_mutate=False,
        )
