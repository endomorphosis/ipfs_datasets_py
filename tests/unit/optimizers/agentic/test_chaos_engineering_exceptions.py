"""Typed-exception regression tests for ChaosEngineeringOptimizer paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from ipfs_datasets_py.optimizers.agentic.base import OptimizationTask
from ipfs_datasets_py.optimizers.agentic.methods.chaos import ChaosEngineeringOptimizer


@pytest.fixture
def optimizer():
    router = Mock()
    router.generate.return_value = "ok"
    return ChaosEngineeringOptimizer(agent_id="chaos-top", llm_router=router)


@pytest.fixture
def task(tmp_path):
    target = tmp_path / "target.py"
    target.write_text("def f():\n    return 1\n")
    return OptimizationTask(
        task_id="task-chaos-top",
        target_files=[target],
        description="Improve resilience",
        priority=50,
    )


def test_optimize_returns_failed_result_on_typed_error(optimizer, task, monkeypatch):
    def _raise_value_error(_targets):
        raise ValueError("bad analysis input")

    monkeypatch.setattr(optimizer, "_analyze_vulnerabilities", _raise_value_error)
    result = optimizer.optimize(task)
    assert result.success is False
    assert "bad analysis input" in (result.error_message or "")


def test_optimize_propagates_base_exception(optimizer, task, monkeypatch):
    def _raise_interrupt(_targets):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr(optimizer, "_analyze_vulnerabilities", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        optimizer.optimize(task)


def test_analyze_vulnerabilities_handles_typed_file_error(optimizer, tmp_path, monkeypatch):
    target = tmp_path / "broken.py"
    target.write_text("def g():\n    return 2\n")
    real_open = open

    def _patched_open(path, *args, **kwargs):
        if Path(path) == target:
            raise OSError("read failed")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _patched_open)
    findings = optimizer._analyze_vulnerabilities([target])
    assert isinstance(findings, dict)
    assert "network_calls" in findings


def test_analyze_vulnerabilities_propagates_base_exception(optimizer, tmp_path, monkeypatch):
    target = tmp_path / "interrupt.py"
    target.write_text("def h():\n    return 3\n")
    real_open = open

    def _patched_open(path, *args, **kwargs):
        if Path(path) == target:
            raise KeyboardInterrupt("stop")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _patched_open)
    with pytest.raises(KeyboardInterrupt):
        optimizer._analyze_vulnerabilities([target])


def test_create_patch_returns_none_tuple_on_typed_error(optimizer, task, monkeypatch):
    def _raise_value_error(_fixes):
        raise ValueError("cannot format")

    monkeypatch.setattr(optimizer, "_format_fixes", _raise_value_error)
    patch_path, patch_cid = optimizer._create_patch([], task)
    assert patch_path is None
    assert patch_cid is None


def test_create_patch_propagates_base_exception(optimizer, task, monkeypatch):
    def _raise_interrupt(_fixes):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr(optimizer, "_format_fixes", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        optimizer._create_patch([], task)
