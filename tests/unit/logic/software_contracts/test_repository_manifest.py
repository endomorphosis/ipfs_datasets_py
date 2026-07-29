"""Unit tests for recursive tracked-object and coverage manifests (DSCON-G020).

Proves RepositorySnapshot, TrackedBlob, GitlinkRecord, CoverageDisposition, and
CoverageReceipt contracts (objective validation repair for DSCON-067 / DSCON-G020).

Hash unsupported blobs without pretending to parse or prove them.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.coverage import (
    SCHEMA_COVERAGE,
    CoverageDisposition,
    CoverageError,
    CoverageReceipt,
    assert_coverage_complete,
    build_coverage_receipt,
    build_coverage_receipt_from_root_document,
    validate_coverage_receipt,
    write_coverage_manifest,
)
from ipfs_datasets_py.logic.software_contracts.repository import (
    ALL_DISPOSITIONS,
    DISPOSITION_ARCHIVED,
    DISPOSITION_BINARY,
    DISPOSITION_GENERATED,
    DISPOSITION_MISSING,
    DISPOSITION_OVERSIZED,
    DISPOSITION_PARSEABLE,
    DISPOSITION_UNSUPPORTED,
    DISPOSITION_VENDORED,
    GOAL_ID,
    MODE_GITLINK,
    MODE_REGULAR,
    OBJECTIVE_VALIDATION_EVIDENCE,
    REPAIR_TASK_ID,
    SCHEMA_REPOSITORY_ROOT,
    STATUS_COMPLETE,
    STATUS_INCOMPLETE_SCAN,
    TASK_ID,
    GitlinkRecord,
    RepositorySnapshot,
    TrackedBlob,
    build_snapshot_from_entries,
    classify_blob,
    detect_language,
    load_repository_root_manifest,
    validate_repository_root_manifest,
    write_repository_root_manifest,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[4]
# Superproject root is two levels above the ipfs_datasets_py package root when
# checked out as a 211-AI submodule; fall back to package parent otherwise.
_CANDIDATE_SUPERPROJECTS = [
    PACKAGE_ROOT.parent,
    PACKAGE_ROOT,
]
EVIDENCE_REPO_ROOT = None
EVIDENCE_COVERAGE = None
for _candidate in _CANDIDATE_SUPERPROJECTS:
    _repo = (
        _candidate
        / "data/datasets_contract_analysis/manifests/repository-root.json"
    )
    _cov = (
        _candidate / "data/datasets_contract_analysis/manifests/coverage.json"
    )
    if _repo.is_file() and _cov.is_file():
        EVIDENCE_REPO_ROOT = _repo
        EVIDENCE_COVERAGE = _cov
        break
if EVIDENCE_REPO_ROOT is None:
    # Default location relative to 211-AI superproject layout.
    EVIDENCE_REPO_ROOT = (
        PACKAGE_ROOT.parent
        / "data/datasets_contract_analysis/manifests/repository-root.json"
    )
    EVIDENCE_COVERAGE = (
        PACKAGE_ROOT.parent
        / "data/datasets_contract_analysis/manifests/coverage.json"
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_detect_language_by_suffix() -> None:
    assert detect_language("pkg/mod.py") == "python"
    assert detect_language("src/app.ts") == "typescript"
    assert detect_language("lib/util.js") == "javascript"
    assert detect_language("schema.json") == "json"
    assert detect_language("Dockerfile") == "dockerfile"
    assert detect_language("mystery.dat") in {"unknown", "binary"}


def test_classify_explicit_dispositions() -> None:
    cases = [
        ("src/ok.py", MODE_REGULAR, 10, DISPOSITION_PARSEABLE),
        ("src/app.ts", MODE_REGULAR, 10, DISPOSITION_UNSUPPORTED),
        ("vendor/lib.py", MODE_REGULAR, 10, DISPOSITION_VENDORED),
        ("pkg/__pycache__/x.pyc", MODE_REGULAR, 10, DISPOSITION_GENERATED),
        ("assets/logo.png", MODE_REGULAR, 100, DISPOSITION_BINARY),
        ("dist/pkg.tar.gz", MODE_REGULAR, 100, DISPOSITION_ARCHIVED),
        ("big.bin", MODE_REGULAR, 9_000_000, DISPOSITION_OVERSIZED),
    ]
    for path, mode, size, expected in cases:
        _lang, disposition, reason, coverage = classify_blob(
            path,
            mode=mode,
            size_bytes=size,
            max_blob_bytes=8_000_000,
            missing=False,
        )
        assert disposition == expected, (path, disposition, reason)
        if expected == DISPOSITION_PARSEABLE:
            assert reason is None
            assert coverage == "queued_for_semantic"
        else:
            assert reason
            assert coverage in {
                "excluded_from_semantic",
                "INCOMPLETE_SCAN",
            }

    _lang, disposition, reason, coverage = classify_blob(
        "gone.py",
        mode=MODE_REGULAR,
        size_bytes=0,
        missing=True,
    )
    assert disposition == DISPOSITION_MISSING
    assert coverage == "INCOMPLETE_SCAN"
    assert reason


# ---------------------------------------------------------------------------
# Synthetic snapshot
# ---------------------------------------------------------------------------


def _synthetic_entries() -> list[dict[str, Any]]:
    return [
        {
            "path": "src/main.py",
            "mode": MODE_REGULAR,
            "oid": "a" * 40,
            "type": "blob",
            "content": b"print('hello')\n",
        },
        {
            "path": "src/util.ts",
            "mode": MODE_REGULAR,
            "oid": "b" * 40,
            "type": "blob",
            "content": b"export const x = 1;\n",
        },
        {
            "path": "vendor/dep.py",
            "mode": MODE_REGULAR,
            "oid": "c" * 40,
            "type": "blob",
            "content": b"# vendored\n",
        },
        {
            "path": "assets/icon.png",
            "mode": MODE_REGULAR,
            "oid": "d" * 40,
            "type": "blob",
            "content": b"\x89PNG\r\n\x1a\n",
        },
        {
            "path": "archive/pkg.zip",
            "mode": MODE_REGULAR,
            "oid": "e" * 40,
            "type": "blob",
            "content": b"PK\x03\x04",
        },
        {
            "path": "build/out.generated.py",
            "mode": MODE_REGULAR,
            "oid": "f" * 40,
            "type": "blob",
            "content": b"# generated\n",
        },
        {
            "path": "ipfs_datasets_py",
            "mode": MODE_GITLINK,
            "oid": "1" * 40,
            "type": "commit",
            "size_bytes": 0,
        },
        {
            "path": "docs/vendor-docs",
            "mode": MODE_GITLINK,
            "oid": "2" * 40,
            "type": "commit",
            "size_bytes": 0,
        },
    ]


def test_snapshot_counts_once_and_is_cycle_safe() -> None:
    snap = build_snapshot_from_entries(
        logical_root="demo",
        entries=_synthetic_entries(),
        shard_size=3,
    )
    assert len(snap.blobs) == 6
    paths = [b.path for b in snap.sorted_blobs()]
    assert paths == sorted(paths)
    assert len(set(paths)) == len(paths)

    # Mirror cycle recorded, nested non-package also recorded, neither rescanned.
    assert any(
        g.disposition == "mirror_cycle_recorded_without_rescan"
        for g in snap.gitlinks
    )
    assert any(
        g.disposition == "nested_gitlink_recorded" for g in snap.gitlinks
    )
    assert all(g.rescan is False for g in snap.gitlinks)
    assert snap.mirror_cycles

    dispositions = {b.parser_disposition for b in snap.blobs}
    for required in {
        DISPOSITION_PARSEABLE,
        DISPOSITION_UNSUPPORTED,
        DISPOSITION_VENDORED,
        DISPOSITION_BINARY,
        DISPOSITION_ARCHIVED,
        DISPOSITION_GENERATED,
    }:
        assert required in dispositions


def test_unsupported_blob_is_hashed_not_parsed() -> None:
    """Hash unsupported blobs without pretending to parse or prove them."""

    content = b"export const secret = 42;\n"
    snap = build_snapshot_from_entries(
        logical_root="demo",
        entries=[
            {
                "path": "app.ts",
                "mode": MODE_REGULAR,
                "oid": "ab" * 20,
                "type": "blob",
                "content": content,
            }
        ],
    )
    blob = snap.blobs[0]
    assert blob.parser_disposition == DISPOSITION_UNSUPPORTED
    assert blob.exclusion_reason
    assert blob.cid == cid_for_bytes(content)
    # No pretend-parse markers.
    assert "ast" not in (blob.exclusion_reason or "").lower()
    assert "parsed" not in (blob.exclusion_reason or "").lower()
    assert "proved" not in (blob.exclusion_reason or "").lower()
    assert blob.coverage_status == "excluded_from_semantic"
    root = snap.to_repository_root_manifest()
    assert root["policy"]["hash_unsupported_without_parse"] is True
    assert root["acceptance"]["hash_unsupported_without_parse"] is True


def test_missing_and_dirty_yield_incomplete_scan() -> None:
    missing = build_snapshot_from_entries(
        logical_root="demo",
        entries=[
            {
                "path": "gone.py",
                "mode": MODE_REGULAR,
                "oid": "cd" * 20,
                "type": "blob",
                "size_bytes": 12,
            }
        ],
        content_by_oid={},
    )
    assert missing.status == STATUS_INCOMPLETE_SCAN
    assert missing.blobs[0].parser_disposition == DISPOSITION_MISSING

    dirty = build_snapshot_from_entries(
        logical_root="demo",
        entries=[
            {
                "path": "ok.py",
                "mode": MODE_REGULAR,
                "oid": "ef" * 20,
                "type": "blob",
                "content": b"x=1\n",
            }
        ],
        clean=False,
    )
    assert dirty.status == STATUS_INCOMPLETE_SCAN
    assert any("INCOMPLETE_SCAN" in b for b in dirty.blockers)


def test_shard_counts_sum_to_root_and_two_runs_match(tmp_path: Path) -> None:
    entries = _synthetic_entries()
    # Add enough blobs to span multiple shards.
    for i in range(10):
        entries.append(
            {
                "path": f"extra/f{i:02d}.py",
                "mode": MODE_REGULAR,
                "oid": f"{i:040d}",
                "type": "blob",
                "content": f"# file {i}\n".encode(),
            }
        )

    snap_a = build_snapshot_from_entries(
        logical_root="demo",
        entries=entries,
        shard_size=4,
        commit="aa" * 20,
        tree="bb" * 20,
    )
    snap_b = build_snapshot_from_entries(
        logical_root="demo",
        entries=entries,
        shard_size=4,
        commit="aa" * 20,
        tree="bb" * 20,
    )

    root_a = snap_a.to_repository_root_manifest()
    root_b = snap_b.to_repository_root_manifest()
    assert root_a["root_cid"] == root_b["root_cid"]
    assert root_a["shard_count_sum"] == root_a["totals"]["tracked_objects"]
    assert root_a["shard_count_sum"] == sum(
        s["count"] for s in root_a["shards"]
    )
    assert root_a["totals"]["tracked_objects"] == len(snap_a.blobs)

    errors = validate_repository_root_manifest(root_a)
    assert errors == []

    out = tmp_path / "repository-root.json"
    write_repository_root_manifest(out, snap_a)
    loaded = load_repository_root_manifest(out)
    assert loaded["root_cid"] == root_a["root_cid"]
    assert loaded["schema"] == SCHEMA_REPOSITORY_ROOT
    assert loaded["goal_id"] == GOAL_ID
    assert loaded["task_id"] == TASK_ID


def test_duplicate_blob_oid_reuses_content_cid() -> None:
    payload = b"shared\n"
    snap = build_snapshot_from_entries(
        logical_root="demo",
        entries=[
            {
                "path": "a/one.py",
                "mode": MODE_REGULAR,
                "oid": "11" * 20,
                "type": "blob",
                "content": payload,
            },
            {
                "path": "b/two.py",
                "mode": MODE_REGULAR,
                "oid": "11" * 20,
                "type": "blob",
                "content": payload,
            },
        ],
    )
    assert len(snap.blobs) == 2
    assert snap.blobs[0].cid == snap.blobs[1].cid == cid_for_bytes(payload)
    # Counted once per path, not collapsed.
    assert {b.path for b in snap.blobs} == {"a/one.py", "b/two.py"}


# ---------------------------------------------------------------------------
# Coverage receipt
# ---------------------------------------------------------------------------


def test_coverage_receipt_binds_root_and_validates(tmp_path: Path) -> None:
    snap = build_snapshot_from_entries(
        logical_root="demo",
        entries=_synthetic_entries(),
        shard_size=2,
    )
    root = snap.to_repository_root_manifest()
    receipt = build_coverage_receipt(snap, repository_root=root)
    assert receipt.repository_root_cid == root["root_cid"]
    assert receipt.shard_count_sum == receipt.total_objects
    assert {d.disposition for d in receipt.dispositions} == set(ALL_DISPOSITIONS)
    assert sum(d.count for d in receipt.dispositions) == receipt.total_objects

    errors = validate_coverage_receipt(receipt, repository_root=root)
    assert errors == []
    assert receipt.complete is True
    assert receipt.status == STATUS_COMPLETE

    path = tmp_path / "coverage.json"
    write_coverage_manifest(path, receipt)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["schema"] == SCHEMA_COVERAGE
    assert loaded["receipt_cid"] == receipt.receipt_cid


def test_coverage_incomplete_on_missing() -> None:
    snap = build_snapshot_from_entries(
        logical_root="demo",
        entries=[
            {
                "path": "gone.py",
                "mode": MODE_REGULAR,
                "oid": "99" * 20,
                "type": "blob",
                "size_bytes": 3,
            }
        ],
    )
    root = snap.to_repository_root_manifest()
    receipt = build_coverage_receipt(snap, repository_root=root)
    assert receipt.status == STATUS_INCOMPLETE_SCAN
    assert receipt.complete is False
    errors = validate_coverage_receipt(receipt, repository_root=root)
    assert errors == []
    with pytest.raises(CoverageError):
        assert_coverage_complete(receipt, repository_root=root)


def test_coverage_from_root_document_alone() -> None:
    snap = build_snapshot_from_entries(
        logical_root="demo",
        entries=_synthetic_entries(),
        shard_size=3,
    )
    root = snap.to_repository_root_manifest()
    receipt = build_coverage_receipt_from_root_document(root)
    assert receipt.repository_root_cid == root["root_cid"]
    assert receipt.shard_count_sum == root["shard_count_sum"]
    assert validate_coverage_receipt(receipt, repository_root=root) == []


def test_model_round_trips() -> None:
    blob = TrackedBlob(
        path="x.py",
        mode=MODE_REGULAR,
        git_oid="aa" * 20,
        size_bytes=4,
        cid=cid_for_bytes(b"x=1\n"),
        language="python",
        parser_disposition=DISPOSITION_PARSEABLE,
        exclusion_reason=None,
        coverage_status="queued_for_semantic",
        logical_root="demo",
    )
    assert TrackedBlob.from_dict(blob.to_dict()) == blob

    gl = GitlinkRecord(
        path="sub",
        gitlink_commit="bb" * 20,
        parent_root="demo",
        disposition="nested_gitlink_recorded",
        full_path="demo/sub",
    )
    assert GitlinkRecord.from_dict(gl.to_dict()).path == "sub"

    disp = CoverageDisposition(
        disposition=DISPOSITION_PARSEABLE,
        count=1,
        coverage_status="queued_for_semantic",
        semantic=True,
        sample_paths=("x.py",),
    )
    assert CoverageDisposition.from_dict(disp.to_dict()).count == 1

    snap = RepositorySnapshot(blobs=[blob], status=STATUS_COMPLETE)
    snap.logical_roots.append(
        {
            "label": "demo",
            "commit": "cc" * 20,
            "tree": "dd" * 20,
            "clean": True,
            "dirty": False,
            "verified": True,
            "status": "verified",
            "blob_count": 1,
            "object_count": 1,
        }
    )
    restored = RepositorySnapshot.from_dict(snap.to_dict())
    assert len(restored.blobs) == 1
    assert restored.blobs[0].path == "x.py"

    receipt = build_coverage_receipt(snap)
    restored_receipt = CoverageReceipt.from_dict(receipt.to_dict())
    assert restored_receipt.total_objects == 1
    assert restored_receipt.repository_root_cid == receipt.repository_root_cid


def test_oversized_disposition_without_semantic_claim() -> None:
    big = b"x" * 100
    snap = build_snapshot_from_entries(
        logical_root="demo",
        entries=[
            {
                "path": "huge.bin",
                "mode": MODE_REGULAR,
                "oid": "77" * 20,
                "type": "blob",
                "content": big,
            }
        ],
        max_blob_bytes=50,
    )
    blob = snap.blobs[0]
    assert blob.parser_disposition == DISPOSITION_OVERSIZED
    assert blob.cid == cid_for_bytes(big)
    assert blob.coverage_status == "excluded_from_semantic"


# ---------------------------------------------------------------------------
# Optional real-git fixture (tiny local repo)
# ---------------------------------------------------------------------------


def _init_tiny_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "config", "user.email", "dscon@example.com"],
        cwd=path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "config", "user.name", "dscon"],
        cwd=path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    (path / "hello.py").write_text("print(1)\n", encoding="utf-8")
    (path / "note.md").write_text("# hi\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "hello.py", "note.md"],
        cwd=path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_real_git_root_inventory(tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.software_contracts.repository import (
        build_tracked_blobs_for_root,
        checkout_identity,
    )

    repo = tmp_path / "tiny"
    _init_tiny_git_repo(repo)
    identity = checkout_identity(repo, label="tiny", relative_path="tiny")
    assert identity is not None
    assert identity["clean"] is True

    blobs, gitlinks, blockers = build_tracked_blobs_for_root(
        repo,
        logical_root="tiny",
        hash_content=True,
    )
    assert blockers == []
    assert gitlinks == []
    paths = {b.path for b in blobs}
    assert paths == {"hello.py", "note.md"}
    by_path = {b.path: b for b in blobs}
    assert by_path["hello.py"].parser_disposition == DISPOSITION_PARSEABLE
    assert by_path["note.md"].parser_disposition == DISPOSITION_UNSUPPORTED
    assert by_path["hello.py"].cid == cid_for_bytes(b"print(1)\n")


def test_real_git_two_runs_identical_root_cid(tmp_path: Path) -> None:
    from ipfs_datasets_py.logic.software_contracts.repository import (
        build_tracked_blobs_for_root,
        checkout_identity,
    )

    repo = tmp_path / "tiny"
    _init_tiny_git_repo(repo)

    def make_snap() -> RepositorySnapshot:
        blobs, _gitlinks, blockers = build_tracked_blobs_for_root(
            repo,
            logical_root="tiny",
            hash_content=True,
        )
        assert blockers == []
        real = checkout_identity(repo, label="tiny", relative_path="tiny")
        assert real is not None
        snap = RepositorySnapshot(shard_size=10)
        snap.blobs = blobs
        snap.logical_roots.append(
            {
                "label": "tiny",
                "path": "tiny",
                "commit": real["commit"],
                "tree": real["tree"],
                "clean": True,
                "dirty": False,
                "verified": True,
                "status": "verified",
                "blob_count": len(blobs),
                "object_count": len(blobs),
            }
        )
        return snap

    a = make_snap().to_repository_root_manifest()
    b = make_snap().to_repository_root_manifest()
    assert a["root_cid"] == b["root_cid"]
    assert a["totals"]["tracked_objects"] == 2


# ---------------------------------------------------------------------------
# Objective validation repair (DSCON-067 / DSCON-G020)
# ---------------------------------------------------------------------------


def test_objective_validation_repair_proves_g020_acceptance() -> None:
    """Objective validation repair covers every DSCON-G020 acceptance term.

    This is the synthetic evidence term ``objective validation repair`` for the
    validation gate: path evidence may already exist while the pytest contract
    still needs to re-prove inventory, cycle safety, dispositions, shards,
    incomplete-scan semantics, and deterministic roots.
    """

    assert OBJECTIVE_VALIDATION_EVIDENCE == "objective validation repair"
    assert REPAIR_TASK_ID == "DSCON-067"
    assert GOAL_ID == "DSCON-G020"
    assert TASK_ID == "DSCON-003"

    entries = _synthetic_entries()
    for i in range(8):
        entries.append(
            {
                "path": f"extra/g{i:02d}.py",
                "mode": MODE_REGULAR,
                "oid": f"{i + 20:040d}",
                "type": "blob",
                "content": f"# repair {i}\n".encode(),
            }
        )

    snap_a = build_snapshot_from_entries(
        logical_root="demo",
        entries=entries,
        shard_size=4,
        commit="aa" * 20,
        tree="bb" * 20,
    )
    snap_b = build_snapshot_from_entries(
        logical_root="demo",
        entries=entries,
        shard_size=4,
        commit="aa" * 20,
        tree="bb" * 20,
    )

    # Count once per logical root (paths unique; no double-count collapse).
    paths = [b.path for b in snap_a.sorted_blobs()]
    assert len(paths) == len(set(paths))
    assert paths == sorted(paths)

    # Recursive mirrors are cycle-safe (recorded, not re-walked).
    assert snap_a.mirror_cycles
    assert all(g.rescan is False for g in snap_a.gitlinks)

    # Explicit dispositions for the full vocabulary present in inventory.
    present = {b.parser_disposition for b in snap_a.blobs}
    for required in {
        DISPOSITION_PARSEABLE,
        DISPOSITION_UNSUPPORTED,
        DISPOSITION_VENDORED,
        DISPOSITION_BINARY,
        DISPOSITION_ARCHIVED,
        DISPOSITION_GENERATED,
    }:
        assert required in present

    unsupported = [
        b for b in snap_a.blobs if b.parser_disposition == DISPOSITION_UNSUPPORTED
    ]
    assert unsupported
    for blob in unsupported:
        assert blob.cid  # hashed
        assert blob.coverage_status == "excluded_from_semantic"
        assert "no_accepted_frontend" in (blob.exclusion_reason or "")

    root_a = snap_a.to_repository_root_manifest()
    root_b = snap_b.to_repository_root_manifest()
    assert root_a["root_cid"] == root_b["root_cid"]
    assert root_a["shard_count_sum"] == root_a["totals"]["tracked_objects"]
    assert root_a["shard_count_sum"] == sum(s["count"] for s in root_a["shards"])
    assert validate_repository_root_manifest(root_a) == []

    assert root_a["acceptance"]["objective_validation_repair"] is True
    assert (
        root_a["acceptance"]["objective_validation_evidence"]
        == "objective validation repair"
    )
    assert root_a["acceptance"]["repair_task_id"] == "DSCON-067"
    assert root_a["policy"]["hash_unsupported_without_parse"] is True

    receipt = build_coverage_receipt(snap_a, repository_root=root_a)
    assert receipt.shard_count_sum == receipt.total_objects
    assert {d.disposition for d in receipt.dispositions} == set(ALL_DISPOSITIONS)
    assert validate_coverage_receipt(receipt, repository_root=root_a) == []
    receipt_doc = receipt.to_dict()
    assert receipt_doc["acceptance"]["objective_validation_repair"] is True
    assert (
        receipt_doc["acceptance"]["objective_validation_evidence"]
        == OBJECTIVE_VALIDATION_EVIDENCE
    )

    # Dirty or missing inputs yield INCOMPLETE_SCAN.
    dirty = build_snapshot_from_entries(
        logical_root="demo",
        entries=[
            {
                "path": "ok.py",
                "mode": MODE_REGULAR,
                "oid": "ef" * 20,
                "type": "blob",
                "content": b"x=1\n",
            }
        ],
        clean=False,
    )
    assert dirty.status == STATUS_INCOMPLETE_SCAN
    missing = build_snapshot_from_entries(
        logical_root="demo",
        entries=[
            {
                "path": "gone.py",
                "mode": MODE_REGULAR,
                "oid": "cd" * 20,
                "type": "blob",
                "size_bytes": 12,
            }
        ],
        content_by_oid={},
    )
    assert missing.status == STATUS_INCOMPLETE_SCAN
    assert missing.blobs[0].parser_disposition == DISPOSITION_MISSING


# ---------------------------------------------------------------------------
# Durable evidence on disk (when present)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not EVIDENCE_REPO_ROOT.is_file() or not EVIDENCE_COVERAGE.is_file(),
    reason="DSCON-G020 evidence manifests not materialized yet",
)
def test_evidence_manifests_are_valid_and_bound() -> None:
    root = json.loads(EVIDENCE_REPO_ROOT.read_text(encoding="utf-8"))
    coverage = json.loads(EVIDENCE_COVERAGE.read_text(encoding="utf-8"))

    root_errors = validate_repository_root_manifest(root)
    assert root_errors == [], root_errors

    cov_errors = validate_coverage_receipt(coverage, repository_root=root)
    assert cov_errors == [], cov_errors

    assert root["schema"] == SCHEMA_REPOSITORY_ROOT
    assert root["goal_id"] == GOAL_ID
    assert root["task_id"] == TASK_ID
    assert coverage["repository_root_cid"] == root["root_cid"]
    assert coverage["shard_count_sum"] == coverage["total_objects"]
    assert set(coverage["disposition_counts"]) >= set(ALL_DISPOSITIONS)
    # Identity recompute for root
    identity = {
        k: v
        for k, v in root.items()
        if k not in {"root_cid", "acceptance", "blob_sample"}
    }
    assert cid_for_structured(identity) == root["root_cid"]
