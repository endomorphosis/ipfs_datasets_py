"""Typed-exception regression tests for TestDrivenOptimizer."""

from __future__ import annotations

import ast
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
    assert optimizer._last_generation_diagnostics == [
        {
            "file": str(task.target_files[0]),
            "status": "error",
            "mode": "full_file",
            "target_symbols": [],
            "error_type": "ValueError",
            "error_message": "llm unavailable",
            "raw_response_preview": "",
        }
    ]


def test_generate_optimizations_propagates_base_exception(optimizer, task):
    optimizer.llm_router.generate.side_effect = KeyboardInterrupt("stop")
    with pytest.raises(KeyboardInterrupt):
        optimizer._generate_optimizations(task, analysis={}, baseline={})


def test_optimize_failed_result_includes_generation_diagnostics(optimizer, task, monkeypatch):
    monkeypatch.setattr(optimizer, "_analyze_targets", lambda _targets: {})
    monkeypatch.setattr(optimizer, "_generate_tests", lambda _task, analysis: {"success": True})
    monkeypatch.setattr(
        optimizer,
        "_generate_optimizations",
        lambda _task, analysis, baseline: (
            optimizer._last_generation_diagnostics.append(
                {
                    "file": str(task.target_files[0]),
                    "status": "error",
                    "error_type": "ValueError",
                    "error_message": "codex exec timed out after 60s",
                }
            )
            or {}
        ),
    )

    result = optimizer.optimize(task)

    assert result.success is False
    assert "No changes found in worktree" in (result.error_message or "")
    assert result.metadata["generation_diagnostics"][0]["error_message"] == "codex exec timed out after 60s"


def test_generate_optimizations_can_patch_target_symbols(tmp_path):
    router = Mock()
    router.generate.return_value = """
def _is_intake_complete(self) -> bool:
    data = self.phase_data[ComplaintPhase.INTAKE]
    return bool(data.get("knowledge_graph")) and bool(data.get("dependency_graph")) and data.get("remaining_gaps", 99) <= 2

def _get_intake_action(self) -> Dict[str, Any]:
    data = self.phase_data[ComplaintPhase.INTAKE]
    if not data.get("knowledge_graph"):
        return {"action": "build_knowledge_graph"}
    if not data.get("dependency_graph"):
        return {"action": "build_dependency_graph"}
    if data.get("current_gaps"):
        return {"action": "address_gaps", "gaps": data.get("current_gaps")}
    return {"action": "complete_intake"}
"""
    optimizer = TestDrivenOptimizer(agent_id="td-symbols", llm_router=router)

    target = tmp_path / "phase_manager.py"
    target.write_text(
        "from typing import Dict, Any\n\n"
        "class ComplaintPhase:\n"
        "    INTAKE = 'intake'\n\n"
        "class PhaseManager:\n"
        "    def __init__(self):\n"
        "        self.phase_data = {ComplaintPhase.INTAKE: {}}\n\n"
        "    def _is_intake_complete(self) -> bool:\n"
        "        return False\n\n"
        "    def _get_intake_action(self) -> Dict[str, Any]:\n"
        "        return {'action': 'continue_denoising'}\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-symbols",
        target_files=[target],
        description="Optimize symbol targets",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["_is_intake_complete", "_get_intake_action"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "_is_intake_complete" in updated
    assert "_get_intake_action" in updated
    assert "return False" not in updated
    assert "continue_denoising" not in updated
    assert optimizer._last_generation_diagnostics[0]["mode"] == "symbol_level"
    ast.parse(updated)


def test_generate_optimizations_normalizes_indented_symbol_response(tmp_path):
    router = Mock()
    router.generate.return_value = """
    def _is_intake_complete(self) -> bool:
        data = self.phase_data[ComplaintPhase.INTAKE]
        return bool(data.get("knowledge_graph"))

    def _get_intake_action(self) -> Dict[str, Any]:
        return {"action": "complete_intake"}
"""
    optimizer = TestDrivenOptimizer(agent_id="td-symbols-indented", llm_router=router)

    target = tmp_path / "phase_manager.py"
    target.write_text(
        "from typing import Dict, Any\n\n"
        "class ComplaintPhase:\n"
        "    INTAKE = 'intake'\n\n"
        "class PhaseManager:\n"
        "    def __init__(self):\n"
        "        self.phase_data = {ComplaintPhase.INTAKE: {}}\n\n"
        "    def _is_intake_complete(self) -> bool:\n"
        "        return False\n\n"
        "    def _get_intake_action(self) -> Dict[str, Any]:\n"
        "        return {'action': 'continue_denoising'}\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-symbols-indented",
        target_files=[target],
        description="Optimize symbol targets",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["_is_intake_complete", "_get_intake_action"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "complete_intake" in updated
    ast.parse(updated)


def test_generate_optimizations_records_raw_symbol_response_on_error(tmp_path):
    router = Mock()
    router.generate.return_value = """
def _get_intake_action(self) -> Dict[str, Any]:
    return {"action": "broken"
"""
    optimizer = TestDrivenOptimizer(agent_id="td-symbols-error", llm_router=router)

    target = tmp_path / "phase_manager.py"
    target.write_text(
        "from typing import Dict, Any\n\n"
        "class PhaseManager:\n"
        "    def _get_intake_action(self) -> Dict[str, Any]:\n"
        "        return {'action': 'continue_denoising'}\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-symbols-error",
        target_files=[target],
        description="Optimize one symbol",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["_get_intake_action"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})

    assert result == {}
    assert optimizer._last_generation_diagnostics[0]["mode"] == "symbol_level"
    assert "raw_response_preview" in optimizer._last_generation_diagnostics[0]
    assert "_get_intake_action" in optimizer._last_generation_diagnostics[0]["raw_response_preview"]
