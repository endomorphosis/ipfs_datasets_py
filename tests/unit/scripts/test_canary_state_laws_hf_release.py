"""Current-contract tests for the immutable live LCR-041 staging canary."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))
for _name in tuple(sys.modules):
    if _name == "scripts" or _name.startswith("scripts."):
        sys.modules.pop(_name, None)
stage = importlib.import_module("scripts.ops.legal_data.stage_state_laws_hf_release")
canary = importlib.import_module("scripts.ops.legal_data.canary_state_laws_hf_release")


PARENT = "1" * 40
STAGING = "2" * 40
CANDIDATE_DIGEST = "a" * 64
RELEASE_DIGEST = "b" * 64
PLAN_DIGEST = "c" * 64
PROOF_DIGEST = "d" * 64
FILE_BYTES = b"sealed staging object\n"
FILE_DIGEST = hashlib.sha256(FILE_BYTES).hexdigest()
REMOTE_PATH = f"releases/sha256-{RELEASE_DIGEST}/manifest.json"


def _staging_receipt() -> dict:
    operation = {
        "operation": "add",
        "relative_path": "manifest.json",
        "remote_path": REMOTE_PATH,
        "sha256": FILE_DIGEST,
        "size_bytes": len(FILE_BYTES),
    }
    common = {
        "operation": stage.AUTHORIZED_OPERATION,
        "parent_commit": PARENT,
        "phase": stage.PUBLICATION_PHASE,
        "plan_digest": PLAN_DIGEST,
        "policy_proof_digest": PROOF_DIGEST,
        "release_manifest_digest": RELEASE_DIGEST,
        "repository_id": stage.DEFAULT_DATASET_REPO,
        "revision": stage.DEFAULT_STAGING_BRANCH,
        "runtime_authorized": True,
        "payload_digest": "e" * 64,
    }
    receipt = {
        "schema": stage.REPORT_SCHEMA,
        "receipt_kind": stage.RECEIPT_KIND,
        "task_id": stage.TASK_ID,
        "goal_id": stage.GOAL_ID,
        "program_id": stage.PROGRAM_ID,
        "producer": stage.PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": stage.DEFAULT_DATASET_REPO,
        "target": stage.DEFAULT_DATASET_REPO,
        "staging_branch": stage.DEFAULT_STAGING_BRANCH,
        "audited_parent_commit": PARENT,
        "base_pin": PARENT,
        "staging_revision": STAGING,
        "staging_sha": STAGING,
        "final_manifest_digest": CANDIDATE_DIGEST,
        "release_manifest_digest": RELEASE_DIGEST,
        "plan_digest": PLAN_DIGEST,
        "policy_proof_digest": PROOF_DIGEST,
        "branch_mutation": {
            **common,
            "method": "create_branch",
            "resulting_commit_sha": PARENT,
            "approval_id": "branch-approval",
        },
        "commit_mutation": {
            **common,
            "method": "create_commit",
            "resulting_commit_sha": STAGING,
            "approval_id": "commit-approval",
        },
        "operations": [operation],
        "uploaded": [
            {key: operation[key] for key in ("relative_path", "remote_path", "sha256", "size_bytes")}
        ],
        "skipped": [],
        "unexpected_operations": [],
        "remote_mutation_attempted": True,
        "remote_write_performed": True,
        "gate_invoked_before_mutation": True,
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = stage.publication_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    return stage.check_canonical_staging_receipt(receipt)


def _queries() -> dict:
    return {
        name: {"passed": True, "trace_count": 1}
        for name in ("bm25", "vector", "hybrid", "graph", "filters", "cache")
    } | {"jurisdictions": list(canary.SORTED_JURISDICTIONS)}


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
        "release_manifest_digest": RELEASE_DIGEST,
        "staging_revision": STAGING,
    }


def _canary_receipt() -> dict:
    return canary.build_canonical_staging_canary_receipt(
        staging_receipt=_staging_receipt(),
        redownload=_redownload(),
        query_canaries=_queries(),
    )


def test_identity_help_and_read_only_source() -> None:
    assert canary.TASK_ID == "LCR-041"
    assert canary.main(["--help"]) == 0
    source = Path(canary.__file__).read_text(encoding="utf-8")
    for forbidden in ("HfApi", "upload_folder", "authorize_and_mutate"):
        assert forbidden not in source
    assert "hf_hub_download" in source


def test_live_canary_binds_exact_staging_pin_and_exact_51() -> None:
    receipt = _canary_receipt()
    assert receipt["live_staging"] is True
    assert receipt["staging_revision"] == STAGING
    assert receipt["staging_sha"] == STAGING
    assert receipt["final_manifest_digest"] == CANDIDATE_DIGEST
    assert receipt["release_manifest_digest"] == RELEASE_DIGEST
    assert receipt["jurisdictions"] == list(canary.SORTED_JURISDICTIONS)
    assert "DC" in receipt["jurisdictions"]
    assert receipt["remote_mutation_attempted"] is False


def test_query_modes_and_missing_dc_fail_closed() -> None:
    missing_mode = _queries()
    del missing_mode["graph"]
    with pytest.raises(canary.CanaryReceiptError, match="graph"):
        canary.validate_canonical_query_canaries(missing_mode)
    missing_dc = _queries()
    missing_dc["jurisdictions"].remove("DC")
    with pytest.raises(canary.CanaryReceiptError, match="exact-51"):
        canary.validate_canonical_query_canaries(missing_dc)


def test_fixture_dirty_or_tampered_receipts_fail_closed() -> None:
    for field, value in (
        ("fixture_only", True),
        ("dirty", True),
        ("live_staging", False),
        ("unexpected_operations", ["repair"]),
    ):
        changed = copy.deepcopy(_canary_receipt())
        changed[field] = value
        with pytest.raises(canary.CanaryReceiptError):
            canary.check_canonical_staging_canary_receipt(changed)


def test_redownload_reads_every_exact_descriptor_from_empty_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    source = tmp_path / "transport" / "manifest.json"

    def fetch(repo_id: str, revision: str, path: str, cache_root: Path) -> Path:
        assert repo_id == stage.DEFAULT_DATASET_REPO
        assert revision == STAGING
        assert path == REMOTE_PATH
        assert cache_root == cache.resolve()
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(FILE_BYTES)
        return source

    monkeypatch.setattr(
        canary,
        "verify_state_laws_local_release_manifest",
        lambda root: SimpleNamespace(manifest_digest=RELEASE_DIGEST),
    )
    measured = canary.redownload_canonical_staging(
        _staging_receipt(), cache_root=cache, fetch_to_path=fetch
    )
    assert measured["exact_descriptor_match"] is True
    assert measured["downloaded_file_count"] == 1
    assert (cache / "manifest.json").read_bytes() == FILE_BYTES


def test_nonempty_cache_or_hash_drift_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "old").write_text("not empty", encoding="utf-8")
    with pytest.raises(canary.CanaryStateLawsError, match="empty"):
        canary.redownload_canonical_staging(
            _staging_receipt(), cache_root=cache, fetch_to_path=lambda *_: cache / "old"
        )


def test_check_cli_is_read_only(tmp_path: Path) -> None:
    target = tmp_path / "canary.json"
    target.write_text(json.dumps(_canary_receipt()), encoding="utf-8")
    before = target.read_bytes()
    assert canary.main(
        ["--require-live-staging", "--check", "--report", str(target)]
    ) == 0
    assert target.read_bytes() == before
    assert canary.main(["--check", "--report", str(target)]) == 1
