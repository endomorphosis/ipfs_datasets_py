"""Supervisor-ingestion contract for the semantic round-trip taskboard."""

from __future__ import annotations

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

    assert tasks["SRT-016"].depends_on == ["SRT-015"]
    assert tasks["SRT-017"].depends_on == ["SRT-015"]

    srt018 = tasks["SRT-018"]
    assert "ipfs_datasets_py/logic/legal_ir/__init__.py" in srt018.outputs
    assert "exact canonical DAG-JSON parity-policy CID" in (
        srt018.metadata["preconditions"]
    )
    assert set(srt018.depends_on) == {"SRT-016", "SRT-017"}

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
    assert "explicit declined decision" in srt019.metadata["preconditions"]
