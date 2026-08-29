"""PCCE-061 typed/structured shard integrity and leakage-boundary tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from ipfs_datasets_py.proof_context.benchmarks import specification as spec

DATASETS_ROOT = Path(__file__).resolve().parents[3]
CORPUS_MANIFEST_PATH = DATASETS_ROOT / "benchmarks/proof_context/corpus_manifest.json"
SHARD_ROOT = DATASETS_ROOT / "benchmarks/proof_context/corpus/typed_structured"
VISIBLE_PATH = SHARD_ROOT / "visible_manifest.json"
EVALUATOR_PATH = SHARD_ROOT / "evaluator_manifest.json"
SHARD_PATH = SHARD_ROOT / "shard_manifest.json"
LICENSE_PATH = SHARD_ROOT / "LICENSE"
FROZEN_MANIFEST_SHA256 = "6169887fabea6829253edcccc35d5a98f7500f6032f2ea373a51536fc2da0db4"
SOURCE_COMMIT = "3dca08ce5bbe673d7df25f44f3dda92505d1043d"
SOURCE_TREE = "2f143c350d12dc394f3320a2d4e259dda86874d7"
SOURCE_PIN_ID = "python-attrs-attrs-25.3.0"


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
    for path, value in (
        (VISIBLE_PATH, visible),
        (EVALUATOR_PATH, evaluator),
        (SHARD_PATH, shard),
    ):
        assert path.read_bytes() == _canonical_bytes(value)

    for name, path, value in (
        ("visible", VISIBLE_PATH, visible),
        ("evaluator", EVALUATOR_PATH, evaluator),
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


def test_exact_source_pin_and_license_are_preserved_without_network_claims() -> None:
    frozen = _load(CORPUS_MANIFEST_PATH)
    shard = _load(SHARD_PATH)
    pin = next(item for item in frozen["source_pins"] if item["pin_id"] == SOURCE_PIN_ID)
    assert shard["source_pin"] == pin
    assert pin["commit"] == SOURCE_COMMIT
    assert pin["tree"] == SOURCE_TREE
    assert pin["archive"] == {
        "sha256": "61aae3bc10caff0a26598c38bcfa1270ae3d67914a8e4b89e8074f5a0323c568",
        "size": 812534,
        "url": (
            "https://codeload.github.com/python-attrs/attrs/tar.gz/"
            "3dca08ce5bbe673d7df25f44f3dda92505d1043d"
        ),
    }
    assert pin["license"]["spdx"] == "MIT"

    license_payload = LICENSE_PATH.read_bytes()
    license_record = shard["license"]
    assert license_record["path"] == "LICENSE"
    assert license_record["size"] == len(license_payload) == 1109
    assert license_record["sha256"] == hashlib.sha256(license_payload).hexdigest()
    assert license_record["sha256"] == pin["license"]["sha256"]
    assert license_record["bytes_cid"] == spec.raw_bytes_cid(license_payload)

    source = shard["source_materialization"]
    assert source == {
        "archive_present": False,
        "archive_sha256": pin["archive"]["sha256"],
        "archive_size": pin["archive"]["size"],
        "fetch_permit": None,
        "historical_answer_present": False,
        "network_used": False,
        "reason": "no-explicit-corpus-fetch-permit-and-no-exact-local-source-archive",
        "state": "source_materialization_unavailable",
    }


def test_task_population_covers_all_kinds_and_required_mutants() -> None:
    visible = _load(VISIBLE_PATH)
    evaluator = _load(EVALUATOR_PATH)
    shard = _load(SHARD_PATH)
    assert shard["task_count"] == 6
    assert (
        [entry["task_id"] for entry in visible["tasks"]]
        == [entry["task_id"] for entry in evaluator["tasks"]]
        == [entry["task_id"] for entry in shard["tasks"]]
    )
    assert {entry["task_kind"] for entry in shard["tasks"]} == set(spec.TASK_KINDS)
    assert {entry["case_class"] for entry in shard["tasks"]} >= {
        "controlled-synthetic-type-edge",
        "historical-source-unavailable",
        "omission",
        "vacuity",
        "context-expansion",
        "negative-human-review",
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
        assert control["repository_class"] == "typed_structured"
        assert control["eligible_configurations"] == ["A", "B", "C", "D"]
        assert agent_view == spec.project_task_agent_view(control)
        assert "sealed_evaluator_root_cid" not in agent_view

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


def test_visible_partition_contains_no_hidden_or_answer_bytes() -> None:
    visible_bytes = VISIBLE_PATH.read_bytes()
    evaluator = _load(EVALUATOR_PATH)
    assert b"sealed_evaluator_root_cid" not in visible_bytes
    assert b"evaluator_root_cid" not in visible_bytes
    assert b"expected_outcome" not in visible_bytes
    for entry in evaluator["tasks"]:
        evaluator_cid = entry["evaluator_root_cid"].encode()
        assert evaluator_cid not in visible_bytes
        for hidden in entry["evaluator"]["hidden_files"]:
            assert _assert_content_record(hidden) not in visible_bytes
        answer = entry["evaluator"]["answer"]
        if answer is not None:
            assert _assert_content_record(answer) not in visible_bytes


def test_access_policy_denies_evaluator_until_terminal_patch() -> None:
    shard = _load(SHARD_PATH)
    assert shard["access_policy"] == {
        "agent_mounts": ["visible_manifest.json", "LICENSE"],
        "control_mounts": ["shard_manifest.json"],
        "evaluator_mounts_after_terminal_patch": ["evaluator_manifest.json"],
        "hardlinks": "denied",
        "path_escape": "denied",
        "symlinks": "denied",
    }
    assert {path.name for path in SHARD_ROOT.iterdir()} == {
        "LICENSE",
        "evaluator_manifest.json",
        "shard_manifest.json",
        "visible_manifest.json",
    }
    assert all(path.is_file() and not path.is_symlink() for path in SHARD_ROOT.iterdir())


def test_historical_and_negative_cases_fail_closed() -> None:
    evaluator = _by_task(_load(EVALUATOR_PATH))
    historical = evaluator["typed-historical-001"]["evaluator"]
    assert historical["answer"] is None
    assert historical["expected_outcome"]["terminal_status"] == "unavailable"
    assert historical["expected_outcome"]["source_materialization"] == (
        "source_materialization_unavailable"
    )
    negative = evaluator["typed-negative-review-001"]["evaluator"]
    assert negative["answer"] is None
    assert negative["expected_outcome"]["terminal_status"] == "human_review_required"
    assert negative["expected_outcome"]["critical_failure"] == (
        "autonomous-strict-validation-weakening"
    )


def _write_record(root: Path, record: dict[str, Any]) -> Path:
    target = root / record["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_assert_content_record(record))
    return target


def _run_pytest(root: Path, targets: list[Path]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
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
        "typed-synthetic-001",
        "typed-assurance-omission-001",
        "typed-assurance-vacuity-001",
        "typed-assurance-context-expansion-001",
    ],
)
def test_frozen_synthetic_answers_kill_their_hidden_mutants(task_id: str, tmp_path: Path) -> None:
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


def test_context_expansion_case_binds_the_model_outside_owned_paths() -> None:
    visible = _by_task(_load(VISIBLE_PATH))["typed-assurance-context-expansion-001"]
    evaluator = _by_task(_load(EVALUATOR_PATH))["typed-assurance-context-expansion-001"]
    assert visible["agent_view"]["owned_paths"] == ["src/typed_fixture/render.py"]
    assert {record["path"] for record in visible["projection"]["files"]} >= {
        "src/typed_fixture/model.py",
        "src/typed_fixture/render.py",
    }
    assert evaluator["evaluator"]["expected_outcome"]["context_expansion_required"] == (
        "src/typed_fixture/model.py"
    )
