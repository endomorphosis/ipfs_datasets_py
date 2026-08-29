"""LCR-072 no-mutate state prepublication seal tests."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

import scripts.ops.legal_data.seal_state_laws_prepublication as seal


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _write_bound_fixture(root: Path) -> tuple[Path, dict[str, str]]:
    reports = root / "docs" / "reports" / "legal_corpora_reindex"
    reports.mkdir(parents=True)
    identities = {
        "plan": "1" * 64,
        "proof": "2" * 64,
        "release": "3" * 64,
        "staging": "4" * 64,
        "revision": "5" * 40,
    }
    candidate = {
        "authorizing_for_publication": False,
        "dataset_repo_id": seal.TARGET_REPO,
        "manifest_digest": identities["release"],
        "publication_binding": {
            "plan_digest": identities["plan"],
            "policy_proof_digest": identities["proof"],
            "release_manifest_digest": identities["release"],
            "staging_candidate_digest": identities["staging"],
        },
        "report_digest_sha256": "0" * 64,
        "schema": "ipfs_datasets_py/legal-corpora-reindex-release-candidate@2",
    }
    candidate["report_digest_sha256"] = sha256(
        _canonical(
            {
                key: value
                for key, value in candidate.items()
                if key != "report_digest_sha256"
            }
        )
    ).hexdigest()
    (reports / "release_candidate.json").write_bytes(_canonical(candidate) + b"\n")
    canary = {
        "dataset_repo_id": seal.TARGET_REPO,
        "dirty": False,
        "final_manifest_digest": identities["staging"],
        "fixture_only": False,
        "live_staging": True,
        "release_manifest_digest": identities["release"],
        "staging_revision": identities["revision"],
        "status": "passed",
    }
    (reports / "staging_canary.json").write_bytes(_canonical(canary) + b"\n")
    sealed = {
        "created_after_mutation": False,
        "dataset_repo_id": seal.TARGET_REPO,
        "dirty": False,
        "final_manifest_digest": candidate["report_digest_sha256"],
        "fixture_only": False,
        "manifest_digest": candidate["report_digest_sha256"],
        "mutation_executed": False,
        "network_mutation": False,
        "no_mutation": True,
        "operation": "additive_main_upload",
        "phase": "state_main",
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
    seal_path = reports / "state_prepublication_seal.json"
    seal_path.write_bytes(_canonical(sealed) + b"\n")
    return seal_path, identities


def test_missing_no_mutate_fails_closed() -> None:
    with pytest.raises(seal.PrepublicationSealError, match="no-mutate"):
        seal.inspect_state_prepublication_seal(
            require_live_staging_pin=True,
            no_mutate=False,
        )


def test_missing_live_staging_pin_fails_closed() -> None:
    with pytest.raises(seal.PrepublicationSealError, match="staging"):
        seal.inspect_state_prepublication_seal(
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
    checked = seal.check_state_prepublication_seal(repo_root=tmp_path)
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert checked["ok"] is True
    assert checked["live_staging"] is True
    assert before == after


def test_strict_seal_rejects_candidate_binding_tamper(tmp_path: Path) -> None:
    _write_bound_fixture(tmp_path)
    candidate_path = tmp_path / seal.CANDIDATE_RELPATH
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["publication_binding"]["plan_digest"] = "9" * 64
    candidate["report_digest_sha256"] = sha256(
        _canonical(
            {
                key: value
                for key, value in candidate.items()
                if key != "report_digest_sha256"
            }
        )
    ).hexdigest()
    candidate_path.write_bytes(_canonical(candidate) + b"\n")
    with pytest.raises(seal.SealBindingError, match="candidate binding|stale"):
        seal.check_state_prepublication_seal(repo_root=tmp_path)


def test_strict_seal_rejects_content_digest_tamper(tmp_path: Path) -> None:
    seal_path, _ = _write_bound_fixture(tmp_path)
    payload = json.loads(seal_path.read_text(encoding="utf-8"))
    payload["content_digest"] = "f" * 64
    seal_path.write_bytes(_canonical(payload) + b"\n")
    with pytest.raises(seal.SealBindingError, match="content digest"):
        seal.check_state_prepublication_seal(repo_root=tmp_path)
