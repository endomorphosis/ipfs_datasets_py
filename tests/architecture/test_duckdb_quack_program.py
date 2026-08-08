from __future__ import annotations

import json
from pathlib import Path

import pytest


duckdb = pytest.importorskip("duckdb")

from scripts.ops import ipfs_datasets_duckdb_quack_program as program


@pytest.fixture()
def task_source(tmp_path: Path):
    DuckDBTaskSource, _providers = program._accelerate_imports()
    repository_tree = "tree:git:test-fixture"
    source = DuckDBTaskSource(tmp_path / "control.duckdb")
    source.materialize(
        program.formal_source(repository_tree),
        repository_tree_id=repository_tree,
        expected_absent=True,
    )
    return source


def test_program_is_acyclic_and_materializes_losslessly(task_source) -> None:
    program.validate_program()

    snapshot = task_source.snapshot()
    integrity = task_source.validate_integrity()
    recompiled = task_source.recompile_formal_plan()

    assert len(program.GOALS) == snapshot.goal_count == 12
    assert len(program.TASKS) == snapshot.task_count == 55
    assert snapshot.dependency_count == 150
    assert integrity.valid
    assert recompiled.status.value == "compiled"
    assert [item.task_id for item in task_source.ready_tasks(limit=1000).tasks] == [
        "DQK-001",
        "DQK-002",
        "DQK-007",
    ]


def test_markdown_and_json_are_deterministic_database_exports(task_source) -> None:
    first_markdown = program.render_markdown(task_source)
    second_markdown = program.render_markdown(task_source)
    first_json = program.database_projection(task_source)
    second_json = program.database_projection(task_source)

    assert first_markdown == second_markdown
    assert first_json == second_json
    assert "Generated projection only" in first_markdown
    assert "Quack is deliberately only the remote SQL transport" in first_markdown
    assert "DQK-055" in first_markdown
    assert first_json["export_digest"].startswith("sha256:")
    json.dumps(first_json, sort_keys=True)


def test_launcher_binds_duckdb_roots_and_disables_markdown_mutators(
    task_source,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(program, "DATABASE_PATH", task_source.database_path)
    monkeypatch.setattr(program, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(program, "WORKTREE_ROOT", tmp_path / "worktrees")
    monkeypatch.setattr(program, "MERGE_QUEUE_ROOT", tmp_path / "merge-queue")
    monkeypatch.setattr(program, "MASTER_ROOT", tmp_path / "master")
    monkeypatch.setattr(program, "MASTER_LOG", tmp_path / "master/supervisor.log")
    monkeypatch.setattr(program, "MASTER_PID", tmp_path / "master/supervisor.pid")

    command = program.supervisor_command(lanes=2, duration_seconds=3600, detach=True)
    joined = "\n".join(command)
    snapshot = task_source.snapshot()

    assert "--implementation-supervisor-lanes-per-track\n2" in joined
    assert "--common-arg=--task-source-kind" in command
    assert "--common-arg=duckdb" in command
    assert f"--common-arg={snapshot.plan_root_cid}" in command
    assert f"--common-arg={snapshot.repository_tree_id}" in command
    assert "--common-arg=--no-retry-budget-guardrail" in command
    assert "--common-arg=--no-dependency-guardrail" in command
    assert "--common-arg=--no-reconciliation-guardrail" in command
    assert "--common-arg=--no-objective-task-janitor" in command
    assert "--implementation-supervisor-defaults" not in command
    assert command[-1] == "--detach"
