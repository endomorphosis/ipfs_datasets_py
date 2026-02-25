"""Typed-exception regression tests for TestDrivenOptimizer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from ipfs_datasets_py.optimizers.agentic.base import OptimizationTask
from ipfs_datasets_py.optimizers.agentic.methods.test_driven import TestDrivenOptimizer


@pytest.fixture
def optimizer():
    router = Mock()
    router.generate.return_value = "def optimized():\n    return 1\n"
    return TestDrivenOptimizer(agent_id="td-1", llm_router=router)


@pytest.fixture
def task(tmp_path):
    target = tmp_path / "target.py"
    target.write_text("def f():\n    return 1\n")
    return OptimizationTask(
        task_id="task-td-1",
        target_files=[target],
        description="Optimize target",
        priority=50,
    )


def test_optimize_returns_failed_result_on_typed_error(optimizer, task, monkeypatch):
    def _raise_value_error(_targets):
        raise ValueError("bad analysis input")

    monkeypatch.setattr(optimizer, "_analyze_targets", _raise_value_error)
    result = optimizer.optimize(task)
    assert result.success is False
    assert "bad analysis input" in (result.error_message or "")


def test_optimize_propagates_base_exception(optimizer, task, monkeypatch):
    def _raise_interrupt(_targets):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr(optimizer, "_analyze_targets", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        optimizer.optimize(task)


def test_analyze_targets_handles_typed_file_error(optimizer, tmp_path, monkeypatch):
    target = tmp_path / "broken.py"
    target.write_text("def g():\n    return 2\n")
    real_open = open

    def _patched_open(path, *args, **kwargs):
        if Path(path) == target:
            raise OSError("read failed")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _patched_open)
    analysis = optimizer._analyze_targets([target])
    assert isinstance(analysis, dict)
    assert "functions" in analysis


def test_analyze_targets_propagates_base_exception(optimizer, tmp_path, monkeypatch):
    target = tmp_path / "interrupt.py"
    target.write_text("def h():\n    return 3\n")
    real_open = open

    def _patched_open(path, *args, **kwargs):
        if Path(path) == target:
            raise KeyboardInterrupt("stop")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _patched_open)
    with pytest.raises(KeyboardInterrupt):
        optimizer._analyze_targets([target])


def test_generate_tests_returns_failed_result_on_typed_llm_error(optimizer, task):
    optimizer.llm_router.generate.side_effect = ValueError("llm unavailable")
    result = optimizer._generate_tests(task, analysis={})
    assert result["success"] is False
    assert "llm unavailable" in result["error"]


def test_generate_tests_propagates_base_exception(optimizer, task):
    optimizer.llm_router.generate.side_effect = KeyboardInterrupt("stop")
    with pytest.raises(KeyboardInterrupt):
        optimizer._generate_tests(task, analysis={})


def test_generate_optimizations_skips_file_on_typed_llm_error(optimizer, task):
    optimizer.llm_router.generate.side_effect = ValueError("llm unavailable")
    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    assert result == {}


def test_generate_optimizations_propagates_base_exception(optimizer, task):
    optimizer.llm_router.generate.side_effect = KeyboardInterrupt("stop")
    with pytest.raises(KeyboardInterrupt):
        optimizer._generate_optimizations(task, analysis={}, baseline={})
