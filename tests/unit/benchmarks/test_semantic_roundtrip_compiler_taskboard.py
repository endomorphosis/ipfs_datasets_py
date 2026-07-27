"""Supervisor-ingestion contract for the semantic round-trip taskboard."""

from __future__ import annotations

import json
from pathlib import Path
import re

from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
    parse_task_file,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
TASKBOARD = (
    REPO_ROOT
    / "docs"
    / "implementation"
    / "plans"
    / "semantic_roundtrip_compiler.taskboard.todo.md"
)
TASK_PREFIX = "## SRT-"
REQUIRED_METADATA = {
    "status",
    "completion",
    "priority",
    "track",
    "depends on",
    "outputs",
    "validation",
    "acceptance",
    "board namespace",
    "bundle",
    "parallel lane",
    "resource class",
    "predicted files",
    "interfaces",
    "conflict policy",
}
SUPPORTED_RESOURCE_CLASSES = {
    "cpu-small",
    "cpu-medium",
    "llm-proof-draft",
}
MODEL_RESOURCE_CLASS = "llm-proof-draft"
LEANSTRAL_PROVIDER_ID = "leanstral-local"


def _assert_acyclic(dependencies: dict[str, tuple[str, ...]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        assert task_id not in visiting, f"dependency cycle through {task_id}"
        visiting.add(task_id)
        for dependency in dependencies[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in dependencies:
        visit(task_id)


def test_semantic_roundtrip_taskboard_is_supervisor_compatible() -> None:
    assert TASKBOARD.is_file()
    tasks = parse_task_file(TASKBOARD, TASK_PREFIX)
    assert len(tasks) >= 12

    task_ids = [task.task_id for task in tasks]
    assert len(task_ids) == len(set(task_ids))
    known = set(task_ids)

    for task in tasks:
        assert re.fullmatch(r"SRT-\d{3}", task.task_id)
        assert task.status in {"todo", "in_progress", "blocked", "completed"}
        assert task.completion == "manual"
        assert task.priority in {"P0", "P1", "P2", "P3"}
        assert task.track
        assert task.outputs
        assert task.validation
        assert task.acceptance
        assert REQUIRED_METADATA <= set(task.metadata)
        assert set(task.depends_on) <= known
        assert task.task_id not in task.depends_on
        assert task.board_namespace == task.metadata["board namespace"]
        assert task.metadata["bundle"]
        assert task.metadata["parallel lane"]
        assert task.metadata["resource class"] in SUPPORTED_RESOURCE_CLASSES
        assert task.metadata["predicted files"]
        assert task.metadata["interfaces"]
        assert task.metadata["conflict policy"]
        if task.metadata["resource class"] == MODEL_RESOURCE_CLASS:
            assert task.metadata["resource stage"] == "inference"
            assert task.metadata["provider id"] == LEANSTRAL_PROVIDER_ID
            assert task.metadata["requires provider"] == "true"
        else:
            assert "provider id" not in task.metadata

    dependencies = {
        task.task_id: tuple(task.depends_on)
        for task in tasks
    }
    _assert_acyclic(dependencies)

    completed = {
        task.task_id
        for task in tasks
        if task.status == "completed"
    }
    ready = [
        task
        for task in tasks
        if task.status == "todo"
        and set(task.depends_on) <= completed
    ]
    assert ready, "the supervisor needs at least one initially claimable task"
    assert {"SRT-001", "SRT-002", "SRT-020"} <= completed
    assert {
        "SRT-003",
        "SRT-004",
        "SRT-005",
        "SRT-006",
    } == {task.task_id for task in ready}
    assert len({task.metadata["parallel lane"] for task in ready}) >= 2
    ready_outputs = [
        output
        for task in ready
        for output in task.outputs
    ]
    assert len(ready_outputs) == len(set(ready_outputs))

    tracks = {task.track for task in tasks}
    assert "benchmark" in tracks
    assert "compiler" in tracks
    assert "decompiler" in tracks
    assert len({task.metadata["parallel lane"] for task in tasks}) >= 3
    assert len({task.metadata["bundle"] for task in tasks}) == len(tasks)


def test_downstream_canonical_tasks_own_shared_contracts_and_validators() -> None:
    tasks = {
        task.task_id: task
        for task in parse_task_file(TASKBOARD, TASK_PREFIX)
    }

    srt015 = tasks["SRT-015"]
    assert set(
        (
            "docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json",
            "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
            "setup.py",
            "pyproject.toml",
            "MANIFEST.in",
        )
    ) <= set(srt015.outputs)
    assert "cid_for_dag_json" in srt015.acceptance
    assert "noninferiority margin" in srt015.acceptance
    assert "leave SRT-015 incomplete" in srt015.metadata["preconditions"]
    assert srt015.metadata["implementation timeout seconds"] == "7200"
    assert "CanonicalDesignGate@1" in srt015.metadata["preconditions"]
    assert "frozen 30-arm preregistration" in srt015.metadata["preconditions"]
    assert "without consuming an implementation attempt" in (
        srt015.metadata["preconditions"]
    )
    assert "replacement report" in srt015.metadata["preconditions"]
    assert "replacement report and gate CIDs" in srt015.acceptance
    assert "tie representative is semantically superior" in srt015.acceptance
    assert srt015.depends_on == ["SRT-027"]

    assert tasks["SRT-016"].depends_on == ["SRT-015"]
    assert tasks["SRT-017"].depends_on == ["SRT-015"]
    assert "implementation timeout seconds" not in tasks["SRT-016"].metadata
    assert "implementation timeout seconds" not in tasks["SRT-017"].metadata

    srt018 = tasks["SRT-018"]
    assert "ipfs_datasets_py/logic/legal_ir/__init__.py" in srt018.outputs
    assert "exact canonical DAG-JSON parity-policy CID" in (
        srt018.metadata["preconditions"]
    )
    assert set(srt018.depends_on) == {"SRT-016", "SRT-017"}
    assert srt018.metadata["implementation timeout seconds"] == "14400"

    srt019 = tasks["SRT-019"]
    assert {
        "benchmarks/semantic_roundtrip/canonical_decision.py",
        "benchmarks/bench_semantic_roundtrip_compositions.py",
        (
            "tests/unit/benchmarks/semantic_roundtrip/"
            "test_canonical_decision.py"
        ),
    } <= set(srt019.outputs)
    assert len(srt019.validation) == 2
    assert "test_canonical_decision.py" in srt019.validation[0]
    assert "--validate-canonical-decision" in srt019.validation[1]
    assert srt019.depends_on == ["SRT-018"]
    assert srt019.metadata["implementation timeout seconds"] == "7200"
    assert "explicit declined decision" in srt019.metadata["preconditions"]


def test_no_eligible_remediation_dag_is_bounded_and_file_disjoint() -> None:
    tasks = {
        task.task_id: task
        for task in parse_task_file(TASKBOARD, TASK_PREFIX)
    }
    remediation_ids = {
        "SRT-021",
        "SRT-022",
        "SRT-023",
        "SRT-024",
        "SRT-025",
        "SRT-026",
        "SRT-027",
    }
    assert remediation_ids <= set(tasks)
    assert tasks["SRT-021"].depends_on == ["SRT-014"]
    assert tasks["SRT-021"].metadata["implementation timeout seconds"] == "3600"
    assert {
        task_id: tasks[task_id].depends_on
        for task_id in ("SRT-022", "SRT-023", "SRT-024")
    } == {
        "SRT-022": ["SRT-021"],
        "SRT-023": ["SRT-021"],
        "SRT-024": ["SRT-021"],
    }
    assert tasks["SRT-022"].metadata["implementation timeout seconds"] == "3600"
    assert tasks["SRT-024"].metadata["implementation timeout seconds"] == "7200"
    assert set(tasks["SRT-025"].depends_on) == {
        "SRT-022",
        "SRT-023",
        "SRT-024",
    }
    assert tasks["SRT-026"].depends_on == ["SRT-025"]
    assert tasks["SRT-027"].depends_on == ["SRT-026"]

    predicted = {
        task_id: {
            value.strip()
            for value in tasks[task_id].metadata["predicted files"].split(",")
            if value.strip()
        }
        for task_id in remediation_ids
    }
    for task_id, paths in predicted.items():
        assert paths == set(tasks[task_id].outputs)
        assert paths
        for other_id, other_paths in predicted.items():
            if task_id < other_id:
                assert paths.isdisjoint(other_paths)
    immutable_originals = {
        (
            "docs/performance_snapshots/"
            "2026-07-26_semantic_roundtrip_composition_pilot.json"
        ),
        "docs/benchmarks/semantic_roundtrip_composition_results.md",
        (
            "workspace/benchmarks/semantic-roundtrip-compositions/"
            "run_manifest.json"
        ),
        "docs/benchmarks/semantic_roundtrip_composition_protocol.md",
    }
    assert all(
        paths.isdisjoint(immutable_originals)
        for paths in predicted.values()
    )
    assert len(
        {
            tasks[task_id].metadata["parallel lane"]
            for task_id in ("SRT-022", "SRT-023", "SRT-024")
        }
    ) == 3
    assert "unavailable_no_reviewed_causal_l1_adapter" in (
        tasks["SRT-024"].acceptance
    )
    assert "mean primary loss `0.0883333334`" in tasks["SRT-022"].acceptance
    assert "manifest-gate" in tasks["SRT-021"].validation[0]
    assert (
        tasks["SRT-023"].metadata["implementation timeout seconds"] == "7200"
    )
    assert "do not require every arm to be selection-eligible" in (
        tasks["SRT-025"].acceptance
    )
    assert (
        tasks["SRT-025"].metadata["implementation timeout seconds"] == "7200"
    )
    assert "670 total terminal observations" in tasks["SRT-026"].acceptance
    assert (
        tasks["SRT-026"].metadata["implementation timeout seconds"] == "21600"
    )
    artifact_envelope = json.loads(
        tasks["SRT-026"].metadata["proposal artifact envelope"]
    )
    assert artifact_envelope == {
        "schema": (
            "ipfs_accelerate_py/agent-supervisor/"
            "task-artifact-envelope@1"
        ),
        "paths": tasks["SRT-026"].outputs,
        "max_file_bytes": 12_000_000,
        "max_patch_bytes": 14_000_000,
        "max_output_bytes": 24_000_000,
    }
    assert artifact_envelope["paths"] == sorted(
        predicted["SRT-026"],
        key=artifact_envelope["paths"].index,
    )
    assert all(
        "proposal artifact envelope" not in task.metadata
        for task_id, task in tasks.items()
        if task_id != "SRT-026"
    )
    assert tasks["SRT-027"].metadata["implementation timeout seconds"] == "3600"
    assert "--require-authorized" in tasks["SRT-027"].validation[0]
    assert "--validate-artifact" in tasks["SRT-027"].validation[0]
