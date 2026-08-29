"""Current-contract tests for LCR-043 and the read-only LCR-047 checker."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    canonical_no_self_field_digest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))
for _name in tuple(sys.modules):
    if _name == "scripts" or _name.startswith("scripts."):
        sys.modules.pop(_name, None)
publish = importlib.import_module("scripts.ops.legal_data.publish_state_laws_hf_release")
check = importlib.import_module("scripts.ops.legal_data.check_state_laws_public_release")


PARENT = publish.PRODUCTION_REVISION
STAGING = "2" * 40
PUBLIC = "3" * 40
CANDIDATE_DIGEST = "a" * 64
RELEASE_DIGEST = "b" * 64
PLAN_DIGEST = "c" * 64
PROOF_DIGEST = "d" * 64
FILE_BYTES = b"immutable public object\n"
FILE_DIGEST = hashlib.sha256(FILE_BYTES).hexdigest()
REMOTE_PATH = f"releases/sha256-{RELEASE_DIGEST}/manifest.json"


def _publication_receipt() -> dict:
    operation = {
        "operation": "add",
        "relative_path": "manifest.json",
        "remote_path": REMOTE_PATH,
        "sha256": FILE_DIGEST,
        "size_bytes": len(FILE_BYTES),
    }
    receipt = {
        "schema": publish.RECEIPT_SCHEMA,
        "receipt_kind": publish.RECEIPT_KIND,
        "task_id": publish.TASK_ID,
        "goal_id": publish.GOAL_ID,
        "program_id": publish.PROGRAM_ID,
        "producer": publish.PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": publish.DEFAULT_DATASET_REPO,
        "target": publish.DEFAULT_DATASET_REPO,
        "public_branch": "main",
        "audited_parent_commit": PARENT,
        "old_sha": PARENT,
        "previous_public_pin": PARENT,
        "rollback_target": PARENT,
        "staging_candidate_digest": "8" * 64,
        "staging_revision": STAGING,
        "staging_sha": STAGING,
        "public_revision": PUBLIC,
        "public_sha": PUBLIC,
        "final_manifest_digest": CANDIDATE_DIGEST,
        "release_manifest_digest": RELEASE_DIGEST,
        "plan_digest": PLAN_DIGEST,
        "policy_proof_digest": PROOF_DIGEST,
        "prepublication_seal_digest": "9" * 64,
        "main_mutation": {
            "approval_id": "main-approval",
            "method": "create_commit",
            "operation": publish.AUTHORIZED_OPERATION,
            "parent_commit": PARENT,
            "payload_digest": "e" * 64,
            "phase": publish.PUBLICATION_PHASE,
            "plan_digest": PLAN_DIGEST,
            "policy_proof_digest": PROOF_DIGEST,
            "release_manifest_digest": RELEASE_DIGEST,
            "repository_id": publish.DEFAULT_DATASET_REPO,
            "resulting_commit_sha": PUBLIC,
            "revision": "main",
            "runtime_authorized": True,
        },
        "operations": [operation],
        "uploaded": [
            {key: operation[key] for key in ("relative_path", "remote_path", "sha256", "size_bytes")}
        ],
        "skipped": [],
        "unexpected_operations": [],
        "additive_only": True,
        "legacy_paths_preserved": True,
        "remote_mutation_attempted": True,
        "remote_write_performed": True,
        "seal_verified_before_mutation": True,
        "gate_invoked_before_mutation": True,
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = publish.publication_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    return publish.check_canonical_publication_receipt(receipt)


def _viewer() -> dict:
    return {
        "passed": True,
        "dataset_viewer_api_passed": True,
        "default_config": check.DEFAULT_CONFIG_NAME,
        "ia_only": False,
        "jurisdictions": list(check.SORTED_JURISDICTIONS),
    }


def _key_sets() -> dict:
    digest = "f" * 64
    return {
        "passed": True,
        "canonical_keys_sha256": digest,
        "families": {
            name: digest for name in ("embeddings", "bm25", "vectors", "graph", "adjacency")
        },
    }


def _queries() -> dict:
    return {
        name: {"passed": True}
        for name in ("bm25", "vector", "hybrid", "graph", "filters", "cache")
    } | {"jurisdictions": list(check.SORTED_JURISDICTIONS)}


def _redownload() -> dict:
    return {
        "cache_empty_before_fetch": True,
        "downloaded": [
            {
                "relative_path": "manifest.json",
                "remote_path": REMOTE_PATH,
                "sha256": FILE_DIGEST,
                "size_bytes": len(FILE_BYTES),
            }
        ],
        "downloaded_bytes": len(FILE_BYTES),
        "downloaded_file_count": 1,
        "exact_descriptor_match": True,
        "public_revision": PUBLIC,
        "release_manifest_digest": RELEASE_DIGEST,
    }


def _canary() -> dict:
    return check.build_canonical_public_canary_receipt(
        publication_receipt=_publication_receipt(),
        redownload=_redownload(),
        viewer_probe=_viewer(),
        key_set_probe=_key_sets(),
        query_canaries=_queries(),
    )


def test_identity_help_and_read_only_source() -> None:
    assert check.TASK_ID == "LCR-043"
    assert check.main(["--help"]) == 0
    source = Path(check.__file__).read_text(encoding="utf-8")
    for forbidden in ("HfApi", "upload_folder", "authorize_and_mutate"):
        assert forbidden not in source
    assert "redownload_canonical_public_release" in source


def test_public_canary_binds_public_pin_viewer_keys_and_queries() -> None:
    receipt = _canary()
    assert check.check_canonical_public_canary_receipt(receipt) == receipt
    assert receipt["public_revision"] == PUBLIC
    assert receipt["viewer"]["default_config"] == check.DEFAULT_CONFIG_NAME
    assert receipt["viewer"]["ia_only"] is False
    assert receipt["jurisdiction_count"] == 51
    assert "DC" in receipt["jurisdictions"]
    assert receipt["read_only"] is True


def test_ia_only_viewer_and_derived_key_drift_fail_closed() -> None:
    viewer = _viewer()
    viewer["ia_only"] = True
    with pytest.raises(check.PublicViewerError):
        check.validate_canonical_viewer_probe(viewer)
    keys = _key_sets()
    keys["families"]["graph"] = "0" * 64
    with pytest.raises(check.PublicParityError):
        check.validate_canonical_key_set_probe(keys)


def test_public_receipt_tampering_fails_closed() -> None:
    changed = copy.deepcopy(_canary())
    changed["query_canaries"]["filters"]["passed"] = False
    with pytest.raises(check.PublicPinError, match="digest mismatch"):
        check.check_canonical_public_canary_receipt(changed)


def test_redownload_is_exact_and_requires_empty_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    source = tmp_path / "transport" / "manifest.json"

    def fetch(repo_id: str, revision: str, path: str, root: Path) -> Path:
        assert (repo_id, revision, path) == (
            publish.DEFAULT_DATASET_REPO,
            PUBLIC,
            REMOTE_PATH,
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(FILE_BYTES)
        return source

    monkeypatch.setattr(
        check,
        "verify_state_laws_local_release_manifest",
        lambda root: SimpleNamespace(manifest_digest=RELEASE_DIGEST),
    )
    measured = check.redownload_canonical_public_release(
        _publication_receipt(), cache_root=cache, fetch_to_path=fetch
    )
    assert measured["downloaded_file_count"] == 1
    assert measured["exact_descriptor_match"] is True
    with pytest.raises(check.PublicRemoteError, match="empty"):
        check.redownload_canonical_public_release(
            _publication_receipt(), cache_root=cache, fetch_to_path=fetch
        )


def test_check_cli_is_read_only(tmp_path: Path) -> None:
    target = tmp_path / "public_canary.json"
    target.write_text(json.dumps(_canary()), encoding="utf-8")
    before = target.read_bytes()
    assert check.main(
        ["--require-public-pin", "--check", "--canary-report", str(target)]
    ) == 0
    assert target.read_bytes() == before


def _install_final_dependency_stub(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, relative_path in check.FINAL_DEPENDENCY_RELPATHS.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"name": name}), encoding="utf-8")
        paths[name] = target

    publication = {
        "canonical_digest": "7" * 64,
        "final_manifest_digest": CANDIDATE_DIGEST,
        "previous_public_pin": PARENT,
        "public_revision": PUBLIC,
        "release_manifest_digest": RELEASE_DIGEST,
    }

    def load_dependencies(*, repo_root: Path):
        assert repo_root.resolve() == root.resolve()
        digests = {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in paths.items()
        }
        return {"publication": publication}, digests

    monkeypatch.setattr(check, "_load_final_dependency_snapshots", load_dependencies)
    return paths


def test_lcr047_generator_is_deterministic_and_binds_seal_and_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _install_final_dependency_stub(tmp_path, monkeypatch)
    first = check.build_state_final_release_receipt(repo_root=tmp_path)
    second = check.build_state_final_release_receipt(repo_root=tmp_path)
    assert first == second
    assert set(first["receipt_digests"]) == set(check.FINAL_DEPENDENCY_RELPATHS)
    assert "prepublication_seal" in first["receipt_digests"]
    assert first["acceptance"] == {
        "all_required_receipts_bound": True,
        "every_state_law_gate_at_public_sha": True,
        "no_unresolved_gap": True,
        "prepublication_seal_bound": True,
    }

    target = tmp_path / "state_final_release_receipt.json"
    check.write_state_final_release_receipt(
        first, path=target, repo_root=tmp_path
    )
    assert (
        check.check_state_final_release_receipt(target, repo_root=tmp_path)
        == first
    )

    paths["prepublication_seal"].write_text(
        json.dumps({"name": "prepublication_seal", "tampered": True}),
        encoding="utf-8",
    )
    with pytest.raises(check.PublicPinError, match="dependency bytes changed"):
        check.check_state_final_release_receipt(target, repo_root=tmp_path)


def test_lcr047_dependency_loader_cross_binds_every_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.ops.legal_data import audit_state_laws_post_publication as audit
    from scripts.ops.legal_data import benchmark_state_laws_public_release as benchmark
    from scripts.ops.legal_data import canary_state_laws_hf_release as staging_canary
    from scripts.ops.legal_data import rehearse_state_laws_release_rollback as rollback
    from scripts.ops.legal_data import seal_state_laws_prepublication as seal
    from scripts.ops.legal_data import stage_state_laws_hf_release as stage

    upload_digest = "1" * 64
    seal_digest = "2" * 64
    publication_digest = "3" * 64
    canary_digest = "4" * 64
    benchmark_digest = "5" * 64
    rollback_digest = "6" * 64
    plan_digest = "7" * 64
    proof_digest = "8" * 64
    payloads = {
        "staging_upload": {"canonical_digest": upload_digest},
        "staging_canary": {
            "release_manifest_digest": RELEASE_DIGEST,
            "staging_revision": STAGING,
            "staging_upload_digest": upload_digest,
        },
        "prepublication_seal": {
            "content_digest": seal_digest,
            "final_manifest_digest": CANDIDATE_DIGEST,
            "plan_digest": plan_digest,
            "policy_proof_digest": proof_digest,
            "release_manifest_digest": RELEASE_DIGEST,
            "staging_revision": STAGING,
        },
        "publication": {
            "canonical_digest": publication_digest,
            "final_manifest_digest": CANDIDATE_DIGEST,
            "plan_digest": plan_digest,
            "policy_proof_digest": proof_digest,
            "prepublication_seal_digest": seal_digest,
            "previous_public_pin": PARENT,
            "public_revision": PUBLIC,
            "release_manifest_digest": RELEASE_DIGEST,
            "staging_revision": STAGING,
        },
        "public_canary": {
            "canonical_digest": canary_digest,
            "final_manifest_digest": CANDIDATE_DIGEST,
            "previous_public_pin": PARENT,
            "publication_receipt_digest": publication_digest,
            "public_revision": PUBLIC,
            "release_manifest_digest": RELEASE_DIGEST,
        },
        "public_benchmark": {
            "canonical_digest": benchmark_digest,
            "final_manifest_digest": CANDIDATE_DIGEST,
            "previous_public_pin": PARENT,
            "public_canary_digest": canary_digest,
            "public_revision": PUBLIC,
            "release_manifest_digest": RELEASE_DIGEST,
        },
        "rollback_rehearsal": {
            "canonical_digest": rollback_digest,
            "final_manifest_digest": CANDIDATE_DIGEST,
            "previous_public_pin": PARENT,
            "publication_receipt_digest": publication_digest,
            "public_canary_digest": canary_digest,
            "public_revision": PUBLIC,
            "release_manifest_digest": RELEASE_DIGEST,
        },
        "post_publication_audit": {
            "final_manifest_digest": CANDIDATE_DIGEST,
            "previous_public_pin": PARENT,
            "public_benchmark_digest": benchmark_digest,
            "public_canary_digest": canary_digest,
            "public_revision": PUBLIC,
            "release_manifest_digest": RELEASE_DIGEST,
            "rollback_rehearsal_digest": rollback_digest,
        },
    }
    for name, relative_path in check.FINAL_DEPENDENCY_RELPATHS.items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payloads[name]), encoding="utf-8")

    monkeypatch.setattr(
        stage, "check_canonical_staging_receipt", lambda value, **_kwargs: value
    )
    monkeypatch.setattr(
        staging_canary,
        "check_canonical_staging_canary_receipt",
        lambda value: value,
    )
    monkeypatch.setattr(
        check, "check_canonical_publication_receipt", lambda value, **_kwargs: value
    )
    monkeypatch.setattr(
        check, "check_canonical_public_canary_receipt", lambda value: value
    )
    monkeypatch.setattr(
        benchmark, "check_canonical_public_benchmark_receipt", lambda value: value
    )
    monkeypatch.setattr(
        rollback, "check_canonical_rollback_rehearsal", lambda value: value
    )
    monkeypatch.setattr(
        audit, "check_canonical_post_publication_audit", lambda value: value
    )
    monkeypatch.setattr(
        seal, "check_state_prepublication_seal", lambda **_kwargs: {"ok": True}
    )
    loaded, digests = check._load_final_dependency_snapshots(repo_root=tmp_path)
    assert set(loaded) == set(check.FINAL_DEPENDENCY_RELPATHS)
    assert set(digests) == set(check.FINAL_DEPENDENCY_RELPATHS)

    payloads["post_publication_audit"]["public_benchmark_digest"] = "f" * 64
    (tmp_path / check.DEFAULT_POST_PUBLICATION_AUDIT_RELPATH).write_text(
        json.dumps(payloads["post_publication_audit"]), encoding="utf-8"
    )
    with pytest.raises(check.PublicPinError, match="digest/pin chain"):
        check._load_final_dependency_snapshots(repo_root=tmp_path)


def test_lcr047_checker_rejects_open_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_final_dependency_stub(tmp_path, monkeypatch)
    final = check.build_state_final_release_receipt(repo_root=tmp_path)
    final["unresolved_gaps"] = ["LCR-046"]
    final["canonical_digest"] = final["content_digest"] = (
        canonical_no_self_field_digest(final)
    )
    target = tmp_path / "final.json"
    target.write_text(json.dumps(final), encoding="utf-8")
    with pytest.raises(check.PublicPinError, match="not closed"):
        check.check_state_final_release_receipt(target, repo_root=tmp_path)


def test_lcr047_cli_generation_requires_explicit_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = {
        "task_id": "LCR-047",
        "receipt_digests": {},
    }
    writes: list[dict] = []
    monkeypatch.setattr(
        check, "build_state_final_release_receipt", lambda: generated
    )
    monkeypatch.setattr(
        check,
        "write_state_final_release_receipt",
        lambda receipt, **_kwargs: writes.append(dict(receipt)),
    )
    assert check.main(["--generate-final"]) == 0
    assert writes == []
    assert check.main(["--generate-final", "--write-final"]) == 0
    assert writes == [generated]
    assert check.main(["--write-final"]) == 2
