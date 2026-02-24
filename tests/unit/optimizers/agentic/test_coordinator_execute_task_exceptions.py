"""Regression tests for typed exception handling in AgentCoordinator.execute_task."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.agentic.base import (
    OptimizationMethod,
    OptimizationResult,
    OptimizationTask,
    ValidationResult,
)
from ipfs_datasets_py.optimizers.agentic.coordinator import (
    AgentCoordinator,
    AgentState,
    AgentStatus,
)


def _make_coordinator(tmp_path: Path) -> AgentCoordinator:
    return AgentCoordinator(
        repo_path=tmp_path,
        ipfs_client=SimpleNamespace(),
        enable_cache=False,
    )


def _register_state(
    coordinator: AgentCoordinator,
    optimizer: object,
    task_id: str = "task-1",
) -> AgentState:
    task = OptimizationTask(task_id=task_id, description="optimize test module")
    state = AgentState(
        agent_id="agent-1",
        optimizer=optimizer,  # type: ignore[arg-type]
        status=AgentStatus.WORKING,
        current_task=task,
    )
    coordinator.agents[state.agent_id] = state
    return state


def _patch_run_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run_sync(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.agentic.coordinator.anyio.to_thread.run_sync",
        _run_sync,
    )


@pytest.mark.asyncio
async def test_execute_task_success_updates_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_run_sync(monkeypatch)
    result = OptimizationResult(
        task_id="task-1",
        success=True,
        method=OptimizationMethod.TEST_DRIVEN,
        changes="small optimization",
    )
    optimizer = SimpleNamespace(
        optimize=lambda _task: result,
        validate=lambda _res: ValidationResult(passed=True),
    )
    coordinator = _make_coordinator(tmp_path)
    state = _register_state(coordinator, optimizer)

    returned = await coordinator.execute_task("agent-1")

    assert returned is result
    assert returned.validation is not None
    assert returned.validation.passed is True
    assert state.status == AgentStatus.WAITING_APPROVAL
    assert state.completed_tasks == ["task-1"]
    assert state.failed_tasks == []


@pytest.mark.asyncio
async def test_execute_task_wraps_typed_optimizer_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_run_sync(monkeypatch)
    optimizer = SimpleNamespace(
        optimize=lambda _task: (_ for _ in ()).throw(ValueError("bad task payload")),
        validate=lambda _res: ValidationResult(passed=True),
    )
    coordinator = _make_coordinator(tmp_path)
    state = _register_state(coordinator, optimizer)

    with pytest.raises(RuntimeError, match="Task execution failed: bad task payload"):
        await coordinator.execute_task("agent-1")

    assert state.status == AgentStatus.ERROR
    assert state.failed_tasks == ["task-1"]


@pytest.mark.asyncio
async def test_execute_task_propagates_base_exceptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_run_sync(monkeypatch)
    optimizer = SimpleNamespace(
        optimize=lambda _task: (_ for _ in ()).throw(KeyboardInterrupt()),
        validate=lambda _res: ValidationResult(passed=True),
    )
    coordinator = _make_coordinator(tmp_path)
    state = _register_state(coordinator, optimizer)

    with pytest.raises(KeyboardInterrupt):
        await coordinator.execute_task("agent-1")

    assert state.status == AgentStatus.WORKING
    assert state.failed_tasks == []
