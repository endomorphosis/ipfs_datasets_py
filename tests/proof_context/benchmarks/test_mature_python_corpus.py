"""PCCE-063 mature-Python shard integrity and leakage-boundary tests."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import posixpath
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from ipfs_datasets_py.proof_context.benchmarks import specification as spec

DATASETS_ROOT = Path(__file__).resolve().parents[3]
CORPUS_MANIFEST_PATH = DATASETS_ROOT / "benchmarks/proof_context/corpus_manifest.json"
SHARD_ROOT = DATASETS_ROOT / "benchmarks/proof_context/corpus/mature_python"
VISIBLE_PATH = SHARD_ROOT / "visible_manifest.json"
EVALUATOR_PATH = SHARD_ROOT / "evaluator_manifest.json"
SHARD_PATH = SHARD_ROOT / "shard_manifest.json"
SOURCE_VERIFICATION_PATH = SHARD_ROOT / "source_verification.json"
SOURCE_ARCHIVE_PATH = SHARD_ROOT / "source/django-5.2.5-a3b1107.tar.gz"
LICENSE_PATH = SHARD_ROOT / "LICENSE.django-5.2.5"
ASGIREF_WHEEL_PATH = SHARD_ROOT / "dependencies/asgiref-3.8.1-py3-none-any.whl"
SQLPARSE_WHEEL_PATH = SHARD_ROOT / "dependencies/sqlparse-0.5.3-py3-none-any.whl"
FROZEN_MANIFEST_SHA256 = "6169887fabea6829253edcccc35d5a98f7500f6032f2ea373a51536fc2da0db4"
SOURCE_COMMIT = "a3b1107a4955bdd994908efb4c6e1d03c281e69f"
SOURCE_TREE = "0d45857fbbe288b56ddd4d8e124a1657421f9c48"
SOURCE_PIN_ID = "django-django-5.2.5"
ARCHIVE_SHA256 = "600a460db656899969c7dd4b1c70ce268eada7c49fa0b57e942da79030faa7af"
LICENSE_SHA256 = "b846415d1b514e9c1dff14a22deb906d794bc546ca6129f950a18cd091e2a669"
ASGIREF_SHA256 = "3e1e3ecc849832fe52ccf2cb6686b7a55f82bb1d6aee72a58826471390335e47"
SQLPARSE_SHA256 = "cf2196ed3418f3ba5de6af7e82c694a9fbdbfecccdfc72e281548517081f16ca"


def _load(path: Path) -> dict[str, Any]:
    value = spec.strict_json_loads(path.read_bytes())
    assert isinstance(value, dict)
    return value


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _assert_content_record(record: dict[str, Any]) -> bytes:
    assert set(record) == {"bytes_cid", "path", "sha256", "size", "utf8"}
    path = PurePosixPath(record["path"])
    assert not path.is_absolute()
    assert ".." not in path.parts
    assert ".git" not in path.parts
    assert "\\" not in record["path"]
    payload = record["utf8"].encode()
    assert record["size"] == len(payload)
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()
    assert record["bytes_cid"] == spec.raw_bytes_cid(payload)
    return payload


def _by_task(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["task_id"]: entry for entry in manifest["tasks"]}


def _raw_cid_from_sha256(value: str) -> str:
    binary = b"\x01\x55\x12\x20" + bytes.fromhex(value)
    return "b" + base64.b32encode(binary).decode().lower().rstrip("=")


def test_frozen_pcce060_manifest_remains_exact_and_bound() -> None:
    payload = CORPUS_MANIFEST_PATH.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == FROZEN_MANIFEST_SHA256
    manifest = spec.strict_json_loads(payload)
    assert isinstance(manifest, dict)
    assert spec.corpus_manifest_cid(manifest) == (
        "baguqeeraedh4m4sadrllnzrp7zi4bherd2dbp5injbvv7myzybjjnju3mlwa"
    )


def test_all_json_is_canonical_and_partition_identities_recompute() -> None:
    visible = _load(VISIBLE_PATH)
    evaluator = _load(EVALUATOR_PATH)
    shard = _load(SHARD_PATH)
    source_verification = _load(SOURCE_VERIFICATION_PATH)
    for path, value in (
        (VISIBLE_PATH, visible),
        (EVALUATOR_PATH, evaluator),
        (SHARD_PATH, shard),
        (SOURCE_VERIFICATION_PATH, source_verification),
    ):
        assert path.read_bytes() == _canonical_bytes(value)

    for name, path, value in (
        ("visible", VISIBLE_PATH, visible),
        ("evaluator", EVALUATOR_PATH, evaluator),
        ("source_verification", SOURCE_VERIFICATION_PATH, source_verification),
    ):
        identity = shard["partitions"][name]
        payload = path.read_bytes()
        assert identity == {
            "bytes_cid": spec.raw_bytes_cid(payload),
            "path": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "structured_cid": spec.structured_cid(value),
        }


def test_exact_django_pin_and_expected_license_identity_are_preserved() -> None:
    frozen = _load(CORPUS_MANIFEST_PATH)
    shard = _load(SHARD_PATH)
    pin = next(item for item in frozen["source_pins"] if item["pin_id"] == SOURCE_PIN_ID)
    assert shard["source_pin"] == pin
    assert pin["commit"] == SOURCE_COMMIT
    assert pin["tree"] == SOURCE_TREE
    assert pin["archive"] == {
        "sha256": ARCHIVE_SHA256,
        "size": 10551627,
        "url": (
            "https://codeload.github.com/django/django/tar.gz/"
            "a3b1107a4955bdd994908efb4c6e1d03c281e69f"
        ),
    }
    assert pin["license"] == {
        "path": "LICENSE",
        "sha256": LICENSE_SHA256,
        "spdx": "BSD-3-Clause",
    }
    assert shard["license"] == {
        "bytes_present": True,
        "expected_bytes_cid": _raw_cid_from_sha256(LICENSE_SHA256),
        "path": "LICENSE",
        "shard_path": "LICENSE.django-5.2.5",
        "sha256": LICENSE_SHA256,
        "spdx": "BSD-3-Clause",
    }
    assert (
        spec.validate_cid(shard["license"]["expected_bytes_cid"], codecs=("raw",))
        == shard["license"]["expected_bytes_cid"]
    )


def test_source_license_and_full_baseline_are_materialized_and_verified() -> None:
    shard = _load(SHARD_PATH)
    assert shard["source_materialization"] == {
        "archive_bytes_cid": _raw_cid_from_sha256(ARCHIVE_SHA256),
        "archive_path": "source/django-5.2.5-a3b1107.tar.gz",
        "archive_present": True,
        "archive_sha256": ARCHIVE_SHA256,
        "archive_size": 10551627,
        "fetch_permit": "operator-confirmed-exact-pin-only",
        "historical_answer_present": False,
        "network_used_during_construction": True,
        "network_used_during_task_execution": False,
        "reconstructed_tree": SOURCE_TREE,
        "state": "source_materialization_verified",
    }
    assert shard["license_materialization"] == {
        "bytes_present": True,
        "exact_local_source": "LICENSE.django-5.2.5",
        "fetch_permit": "operator-confirmed-exact-pin-only",
        "network_used_during_construction": True,
        "network_used_during_task_execution": False,
        "state": "license_materialization_verified",
    }
    assert shard["baseline_full_test"] == {
        "command": "python3.12 -P tests/runtests.py --parallel 4 --verbosity 1",
        "discovered_tests": 18098,
        "expected_failures": 5,
        "passed": True,
        "ran_tests": 18096,
        "receipt_path": "source_verification.json",
        "skipped": 1912,
        "state": "baseline_full_test_passed",
        "tests_executed": True,
    }


def test_materialized_archive_dependencies_license_and_tree_are_exact(tmp_path: Path) -> None:
    verification = _load(SOURCE_VERIFICATION_PATH)
    visible = _by_task(_load(VISIBLE_PATH))

    archive = SOURCE_ARCHIVE_PATH.read_bytes()
    assert len(archive) == 10551627
    assert hashlib.sha256(archive).hexdigest() == ARCHIVE_SHA256
    assert spec.raw_bytes_cid(archive) == verification["archive"]["bytes_cid"]
    assert visible["mature-historical-001"]["projection"]["source_archive"] == {
        "bytes_cid": spec.raw_bytes_cid(archive),
        "path": "source/django-5.2.5-a3b1107.tar.gz",
        "sha256": ARCHIVE_SHA256,
        "size": len(archive),
    }

    for path, expected_sha256, expected_cid in (
        (LICENSE_PATH, LICENSE_SHA256, verification["license"]["bytes_cid"]),
        (ASGIREF_WHEEL_PATH, ASGIREF_SHA256, verification["dependencies"][0]["bytes_cid"]),
        (SQLPARSE_WHEEL_PATH, SQLPARSE_SHA256, verification["dependencies"][1]["bytes_cid"]),
    ):
        payload = path.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == expected_sha256
        assert spec.raw_bytes_cid(payload) == expected_cid

    with tarfile.open(SOURCE_ARCHIVE_PATH, "r:gz") as source_tar:
        members = source_tar.getmembers()
        assert members
        top = PurePosixPath(members[0].name).parts[0]
        assert top == f"django-{SOURCE_COMMIT}"
        for member in members:
            member_path = PurePosixPath(member.name)
            assert not member_path.is_absolute()
            assert member_path.parts[0] == top
            assert ".." not in member_path.parts
            assert member.isfile() or member.isdir() or member.issym()
            if member.issym():
                target = PurePosixPath(member.linkname)
                assert not target.is_absolute()
                resolved = PurePosixPath(posixpath.normpath(str(member_path.parent / target)))
                assert resolved.parts[0] == top
        source_tar.extractall(tmp_path, filter="data")

    source_root = tmp_path / top
    assert (source_root / "LICENSE").read_bytes() == LICENSE_PATH.read_bytes()
    subprocess.run(["git", "init", "-q"], cwd=source_root, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=source_root, check=True)
    subprocess.run(["git", "add", "-f", "."], cwd=source_root, check=True)
    tree = subprocess.run(
        ["git", "write-tree"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tree == SOURCE_TREE
    assert verification["reconstructed_repository"] == {
        "commit": SOURCE_COMMIT,
        "method": "archive-root-git-add-force-write-tree",
        "tree": SOURCE_TREE,
        "verified": True,
    }


def test_baseline_receipt_is_exact_and_does_not_upgrade_live_qualification() -> None:
    verification = _load(SOURCE_VERIFICATION_PATH)
    assert verification["baseline_full_test"] == {
        "command": "python3.12 -P tests/runtests.py --parallel 4 --verbosity 1",
        "discovered_tests": 18098,
        "duration_milliseconds": 98182,
        "errors": 0,
        "expected_failures": 5,
        "failures": 0,
        "network_used": False,
        "passed": True,
        "ran_tests": 18096,
        "skipped": 1912,
        "source_edits": False,
    }
    assert verification["historical_cutoff"] == {
        "future_commits_or_pr_patches_accessed": False,
        "network_during_task_execution": False,
    }
    assert verification["limitations"] == {
        "historical_answer_materialized": False,
        "historical_task_disposition": "unavailable-no-future-patch-access",
        "live_provider_qualification": False,
    }
    assert verification["runtime"]["purpose"] == "isolated-historical-replay-baseline-only"
    assert verification["verification_result"] == "passed"


def test_task_population_covers_mature_synthetic_assurance_and_policy_cases() -> None:
    visible = _load(VISIBLE_PATH)
    evaluator = _load(EVALUATOR_PATH)
    shard = _load(SHARD_PATH)
    assert shard["task_count"] == 8
    assert (
        [entry["task_id"] for entry in visible["tasks"]]
        == [entry["task_id"] for entry in evaluator["tasks"]]
        == [entry["task_id"] for entry in shard["tasks"]]
    )
    assert {entry["task_kind"] for entry in shard["tasks"]} == set(spec.TASK_KINDS)
    assert {entry["case_class"] for entry in shard["tasks"]} == {
        "controlled-synthetic-middleware-order",
        "controlled-synthetic-model-registry",
        "context-expansion-contract-reuse",
        "historical-cutoff-enforcement",
        "historical-answer-unavailable-at-cutoff",
        "negative-human-review",
        "operation-omission",
        "vacuity",
    }


def test_task_controls_agent_views_and_all_nested_identities_recompute() -> None:
    visible = _by_task(_load(VISIBLE_PATH))
    evaluator = _by_task(_load(EVALUATOR_PATH))
    shard = _by_task(_load(SHARD_PATH))
    for task_id in visible:
        visible_entry = visible[task_id]
        evaluator_entry = evaluator[task_id]
        top_entry = shard[task_id]
        projection = visible_entry["projection"]
        agent_view = spec.validate_task_agent_view(visible_entry["agent_view"])
        evaluator_payload = evaluator_entry["evaluator"]
        control = spec.validate_task_control(evaluator_entry["control"])
        answer = evaluator_payload["answer"]

        assert control["task_id"] == task_id
        assert control["base_commit"] == SOURCE_COMMIT
        assert control["base_tree"] == SOURCE_TREE
        assert control["source_pin_id"] == SOURCE_PIN_ID
        assert control["repository_class"] == "mature_python"
        assert control["eligible_configurations"] == ["A", "B", "C", "D"]
        assert agent_view == spec.project_task_agent_view(control)
        assert "sealed_evaluator_root_cid" not in agent_view
        assert projection["historical_cutoff"] == {
            "base_commit": SOURCE_COMMIT,
            "base_tree": SOURCE_TREE,
            "future_commit_or_patch_access": "denied",
        }
        assert evaluator_payload["patch_scope"] == {
            "allowed_paths": control["owned_paths"],
            "out_of_scope_disposition": "reject-before-hidden-evaluation",
        }

        assert visible_entry["projection_cid"] == spec.structured_cid(projection)
        assert visible_entry["agent_view_cid"] == spec.structured_cid(agent_view)
        assert evaluator_entry["evaluator_root_cid"] == spec.structured_cid(evaluator_payload)
        assert evaluator_entry["control_cid"] == spec.structured_cid(control)
        assert evaluator_entry["expected_outcome_cid"] == spec.structured_cid(
            evaluator_payload["expected_outcome"]
        )
        assert evaluator_entry["answer_bytes_cid"] == (
            None if answer is None else answer["bytes_cid"]
        )
        assert control["visible_projection_cid"] == visible_entry["projection_cid"]
        assert control["sealed_evaluator_root_cid"] == evaluator_entry["evaluator_root_cid"]
        assert top_entry == {
            "agent_view_cid": visible_entry["agent_view_cid"],
            "answer_bytes_cid": evaluator_entry["answer_bytes_cid"],
            "case_class": evaluator_payload["case_class"],
            "control_cid": evaluator_entry["control_cid"],
            "evaluator_root_cid": evaluator_entry["evaluator_root_cid"],
            "expected_outcome_cid": evaluator_entry["expected_outcome_cid"],
            "projection_cid": visible_entry["projection_cid"],
            "task_id": task_id,
            "task_kind": control["task_kind"],
        }


def test_every_embedded_file_has_exact_raw_identity_and_safe_path() -> None:
    visible = _load(VISIBLE_PATH)
    evaluator = _load(EVALUATOR_PATH)
    seen: set[tuple[str, str]] = set()
    for entry in visible["tasks"]:
        for record in entry["projection"]["files"]:
            _assert_content_record(record)
            assert (entry["task_id"], record["path"]) not in seen
            seen.add((entry["task_id"], record["path"]))
    for entry in evaluator["tasks"]:
        evaluator_payload = entry["evaluator"]
        for record in evaluator_payload["hidden_files"]:
            _assert_content_record(record)
            assert (entry["task_id"], record["path"]) not in seen
            seen.add((entry["task_id"], record["path"]))
        answer = evaluator_payload["answer"]
        if answer is not None:
            _assert_content_record(answer)
            assert (entry["task_id"], answer["path"]) not in seen
            seen.add((entry["task_id"], answer["path"]))
    assert len(seen) == 28


def test_visible_partition_contains_no_hidden_answer_or_future_patch_bytes() -> None:
    visible_bytes = VISIBLE_PATH.read_bytes()
    visible = _load(VISIBLE_PATH)
    evaluator = _load(EVALUATOR_PATH)
    assert b"sealed_evaluator_root_cid" not in visible_bytes
    assert b"evaluator_root_cid" not in visible_bytes
    assert b"expected_outcome" not in visible_bytes
    assert b"ffffffffffffffffffffffffffffffffffffffff" not in visible_bytes
    visible_paths = {
        record["path"] for entry in visible["tasks"] for record in entry["projection"]["files"]
    }
    evaluator_paths: set[str] = set()
    for entry in evaluator["tasks"]:
        assert entry["evaluator_root_cid"].encode() not in visible_bytes
        for hidden in entry["evaluator"]["hidden_files"]:
            evaluator_paths.add(hidden["path"])
            assert _assert_content_record(hidden) not in visible_bytes
        answer = entry["evaluator"]["answer"]
        if answer is not None:
            evaluator_paths.add(answer["path"])
            assert _assert_content_record(answer) not in visible_bytes
    assert visible_paths.isdisjoint(evaluator_paths)
    assert all(path.encode() not in visible_bytes for path in evaluator_paths)


def test_access_policy_denies_network_and_evaluator_before_terminal_patch() -> None:
    shard = _load(SHARD_PATH)
    assert shard["access_policy"] == {
        "agent_mounts": [
            "visible_manifest.json",
            "source/django-5.2.5-a3b1107.tar.gz",
        ],
        "control_mounts": ["shard_manifest.json", "source_verification.json"],
        "evaluator_mounts_after_terminal_patch": ["evaluator_manifest.json"],
        "hardlinks": "denied",
        "network_during_task_execution": "denied",
        "path_escape": "denied",
        "symlinks": "denied",
    }
    assert {path.name for path in SHARD_ROOT.iterdir()} == {
        "LICENSE.django-5.2.5",
        "dependencies",
        "evaluator_manifest.json",
        "shard_manifest.json",
        "source",
        "source_verification.json",
        "visible_manifest.json",
    }
    assert all(not path.is_symlink() for path in SHARD_ROOT.rglob("*"))
    assert all(path.is_file() for path in (*SHARD_ROOT.glob("*.json"), LICENSE_PATH))


def test_historical_answer_and_negative_cases_fail_closed_without_live_claims() -> None:
    evaluator = _by_task(_load(EVALUATOR_PATH))
    shard = _load(SHARD_PATH)
    historical = evaluator["mature-historical-001"]["evaluator"]
    assert historical["answer"] is None
    assert historical["expected_outcome"]["terminal_status"] == "unavailable"
    assert historical["expected_outcome"]["baseline_full_test_available"] is True
    assert historical["expected_outcome"]["source_materialization"] == (
        "source_materialization_verified"
    )
    negative = evaluator["mature-negative-review-001"]["evaluator"]
    assert negative["answer"] is None
    assert negative["expected_outcome"]["terminal_status"] == "human_review_required"
    assert negative["expected_outcome"]["critical_failure"] == (
        "later-upstream-commit-or-pr-patch-accessed"
    )
    assert shard["validation_state"] == {
        "ground_truth_scope": "exact-source-baseline-controlled-synthetic-and-policy-cases",
        "live_execution_eligible": False,
        "reason": "PCCE-056-no-go-and-historical-answer-unavailable-without-future-access",
        "synthetic_answers_locally_executable": True,
    }


def test_frozen_answers_modify_only_their_declared_owned_paths() -> None:
    evaluator = _load(EVALUATOR_PATH)
    for entry in evaluator["tasks"]:
        answer = entry["evaluator"]["answer"]
        if answer is None:
            continue
        changed = {
            line.removeprefix("+++ b/")
            for line in answer["utf8"].splitlines()
            if line.startswith("+++ b/")
        }
        assert changed
        assert changed <= set(entry["control"]["owned_paths"])


def _write_record(root: Path, record: dict[str, Any]) -> Path:
    target = root / record["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_assert_content_record(record))
    return target


def _run_pytest(root: Path, targets: list[Path]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *(str(path) for path in targets)],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "task_id",
    [
        "mature-synthetic-model-registry-001",
        "mature-synthetic-middleware-order-001",
        "mature-assurance-omission-001",
        "mature-assurance-vacuity-001",
        "mature-assurance-context-expansion-001",
        "mature-assurance-cutoff-001",
    ],
)
def test_frozen_synthetic_answers_kill_hidden_mutants(task_id: str, tmp_path: Path) -> None:
    visible = _by_task(_load(VISIBLE_PATH))[task_id]["projection"]
    evaluator = _by_task(_load(EVALUATOR_PATH))[task_id]["evaluator"]
    public_paths = [
        _write_record(tmp_path, record)
        for record in visible["files"]
        if record["path"].startswith("tests/")
    ]
    for record in visible["files"]:
        if not record["path"].startswith("tests/"):
            _write_record(tmp_path, record)
    hidden_paths = [_write_record(tmp_path, record) for record in evaluator["hidden_files"]]

    public_before = _run_pytest(tmp_path, public_paths)
    assert public_before.returncode == 0, public_before.stdout + public_before.stderr
    hidden_before = _run_pytest(tmp_path, hidden_paths)
    assert hidden_before.returncode != 0, "mutant unexpectedly passed hidden evaluation"

    answer = evaluator["answer"]
    assert answer is not None
    answer_path = _write_record(tmp_path, answer)
    check = subprocess.run(
        ["git", "apply", "--check", str(answer_path)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    subprocess.run(["git", "apply", str(answer_path)], cwd=tmp_path, check=True)

    after = _run_pytest(tmp_path, [*public_paths, *hidden_paths])
    assert after.returncode == 0, after.stdout + after.stderr


def test_historical_cutoff_and_context_expansion_ground_truth_is_frozen() -> None:
    visible = _by_task(_load(VISIBLE_PATH))
    evaluator = _by_task(_load(EVALUATOR_PATH))
    shard = _load(SHARD_PATH)
    assert shard["historical_cutoff"] == {
        "agent_source_view": "exact-pinned-tree-visible-projection-only",
        "base_commit": SOURCE_COMMIT,
        "base_tree": SOURCE_TREE,
        "commit_time": "2025-08-06T08:04:41Z",
        "future_commits_or_pr_patches": "denied",
        "network_during_task_execution": "denied",
    }
    cutoff = evaluator["mature-assurance-cutoff-001"]["evaluator"]
    assert cutoff["expected_outcome"]["acceptance"] == "exact-commit-and-tree-only"

    task_id = "mature-assurance-context-expansion-001"
    context_visible = visible[task_id]
    context_evaluator = evaluator[task_id]
    assert context_visible["agent_view"]["owned_paths"] == ["src/mature_fixture/routing.py"]
    assert {record["path"] for record in context_visible["projection"]["files"]} >= {
        "src/mature_fixture/contracts.py",
        "src/mature_fixture/routing.py",
    }
    assert (
        context_evaluator["evaluator"]["expected_outcome"]["context_expansion_required"]
        == "src/mature_fixture/contracts.py"
    )
