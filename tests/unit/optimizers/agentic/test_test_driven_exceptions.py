"""Typed-exception regression tests for TestDrivenOptimizer."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import Mock

import pytest

from ipfs_datasets_py.optimizers.agentic.base import OptimizationTask
from ipfs_datasets_py.optimizers.agentic.methods.test_driven import TestDrivenOptimizer
from ipfs_datasets_py.optimizers.agentic.base import OptimizationMethod


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


def test_generate_tests_passes_optimization_method(optimizer, task):
    optimizer.llm_router.generate.return_value = "def test_generated():\n    assert True\n"
    result = optimizer._generate_tests(task, analysis={})

    assert result["success"] is True
    assert optimizer.llm_router.generate.call_args.kwargs["method"] == OptimizationMethod.TEST_DRIVEN


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


def test_generate_optimizations_keeps_raw_preview_for_invalid_full_file_response(optimizer, task):
    optimizer.llm_router.generate.return_value = "not valid python("

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})

    assert result == {}
    assert optimizer._last_generation_diagnostics[0]["raw_response_preview"] == "not valid python("


def test_generate_optimizations_keeps_raw_preview_for_symbol_indentation_error(tmp_path):
    router = Mock()
    router.generate.return_value = "    def target_method(self):\nreturn 'patched'\n"
    optimizer = TestDrivenOptimizer(agent_id="td-symbol-indent-error", llm_router=router)

    target = tmp_path / "generic_module.py"
    target.write_text(
        "class Example:\n"
        "    def target_method(self):\n"
        "        return 'original'\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-symbol-indent-error",
        target_files=[target],
        description="Optimize symbol target",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["target_method"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})

    assert result == {}
    assert optimizer._last_generation_diagnostics == [
        {
            "file": str(target),
            "status": "error",
            "mode": "symbol_level",
            "target_symbols": ["target_method"],
            "error_type": "ValueError",
            "error_message": f"Symbol optimization response for {target} returned invalid code for target_method: expected an indented block after function definition on line 1 (<unknown>, line 2)",
            "raw_response_preview": "    def target_method(self):\nreturn 'patched'\n",
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


def test_generate_optimizations_extracts_indented_symbol_response_after_preamble(tmp_path):
    router = Mock()
    router.generate.return_value = """
Here are the requested replacements.

    def _is_intake_complete(self) -> bool:
        data = self.phase_data[ComplaintPhase.INTAKE]
        return bool(data.get("knowledge_graph"))

    def _get_intake_action(self) -> Dict[str, Any]:
        return {"action": "complete_intake"}
"""
    optimizer = TestDrivenOptimizer(agent_id="td-symbols-preamble", llm_router=router)

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
        task_id="task-symbols-preamble",
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


def test_action_policy_renderer_preserves_graph_presence_checks():
    optimizer = TestDrivenOptimizer(agent_id="td-action-policy", llm_router=Mock())

    rendered = optimizer._render_get_intake_action_from_policy(
        {
            "remaining_gaps_threshold": 1,
            "address_gaps_before_denoising": True,
            "require_convergence_for_completion": True,
            "complete_when_iteration_cap_hit": False,
            "prefer_current_gaps_key": True,
        }
    )

    assert "if 'knowledge_graph' not in data:" in rendered
    assert "if 'dependency_graph' not in data:" in rendered
    assert "if not data.get('knowledge_graph')" not in rendered


def test_answer_policy_renderer_preserves_process_answer_contract():
    optimizer = TestDrivenOptimizer(agent_id="td-answer-policy", llm_router=Mock())

    rendered = optimizer._render_process_answer_from_policy(
        {
            "timeline_enrichment_types": ["timeline", "evidence", "impact"],
            "responsible_party_enrichment_types": ["relationship", "responsible_party", "timeline"],
            "fallback_timeline_fact_types": ["timeline", "evidence"],
        }
    )

    assert "def process_answer(self, question: Dict[str, Any], answer: str," in rendered
    assert "'entities_updated': 0" in rendered
    assert "'relationships_added': 0" in rendered
    assert "'requirements_satisfied': 0" in rendered
    assert "req_node.satisfied = True" in rendered
    assert "self._update_responsible_parties_from_answer(answer_text, knowledge_graph, updates)" in rendered
    assert "_apply_timeline_enrichment()" in rendered
    ast.parse(rendered)


def test_answer_policy_response_normalization_rejects_unknown_question_types():
    optimizer = TestDrivenOptimizer(agent_id="td-answer-policy-invalid", llm_router=Mock())

    with pytest.raises(ValueError, match="unsupported question type"):
        optimizer._normalize_answer_policy_response(
            response='{"timeline_enrichment_types":["bogus"],"responsible_party_enrichment_types":[],"fallback_timeline_fact_types":[]}',
            file_path=Path("denoiser.py"),
        )


def test_standard_intake_policy_renderer_preserves_method_contract():
    optimizer = TestDrivenOptimizer(agent_id="td-standard-intake", llm_router=Mock())

    rendered = optimizer._render_standard_intake_questions_from_policy(
        {
            "timeline_prompt_style": "actor_notice_timeline",
            "impact_prompt_style": "impact_with_documents",
            "include_notice_question": True,
        }
    )

    assert "def _ensure_standard_intake_questions(self, questions: List[Dict[str, Any]], max_questions: int) -> List[Dict[str, Any]]:" in rendered
    assert "if len(questions) >= max_questions:" in rendered
    assert "self._already_asked(timeline_text)" in rendered
    assert "self._already_asked(impact_text)" in rendered
    assert "question_type='timeline'" in rendered
    assert "question_type='impact'" in rendered
    assert "question_type='evidence'" in rendered
    assert "notice, letter, email, or message" in rendered
    ast.parse(rendered)


def test_standard_intake_policy_response_normalization_rejects_unknown_styles():
    optimizer = TestDrivenOptimizer(agent_id="td-standard-intake-invalid", llm_router=Mock())

    with pytest.raises(ValueError, match="unsupported timeline_prompt_style"):
        optimizer._normalize_standard_intake_policy_response(
            response='{"timeline_prompt_style":"bogus","impact_prompt_style":"baseline","include_notice_question":false}',
            file_path=Path("denoiser.py"),
        )


def test_action_policy_renderer_uses_plain_default_gap_threshold_when_not_looser():
    optimizer = TestDrivenOptimizer(agent_id="td-action-policy-threshold", llm_router=Mock())

    rendered = optimizer._render_get_intake_action_from_policy(
        {
            "remaining_gaps_threshold": 2,
            "address_gaps_before_denoising": True,
            "require_convergence_for_completion": True,
            "complete_when_iteration_cap_hit": False,
            "prefer_current_gaps_key": True,
        }
    )

    assert "gap_threshold = _INTAKE_GAPS_THRESHOLD" in rendered
    assert "configured_gap_threshold" not in rendered
    assert "max(_INTAKE_GAPS_THRESHOLD, configured_gap_threshold)" not in rendered


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


def test_generate_optimizations_can_use_action_policy_mode(tmp_path):
    router = Mock()
    router.generate.return_value = """{
  "remaining_gaps_threshold": 1,
  "address_gaps_before_denoising": true,
  "require_convergence_for_completion": true,
  "complete_when_iteration_cap_hit": false,
  "prefer_current_gaps_key": true
}"""
    optimizer = TestDrivenOptimizer(agent_id="td-action-policy", llm_router=router)

    target = tmp_path / "phase_manager.py"
    target.write_text(
        "from typing import Dict, Any\n\n"
        "class ComplaintPhase:\n"
        "    INTAKE = 'intake'\n\n"
        "_DENOISING_MAX_ITERATIONS = 5\n\n"
        "class PhaseManager:\n"
        "    def __init__(self):\n"
        "        self.iteration_count = 0\n"
        "        self.phase_data = {ComplaintPhase.INTAKE: {}}\n\n"
        "    def _get_intake_action(self) -> Dict[str, Any]:\n"
        "        return {'action': 'continue_denoising'}\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-action-policy",
        target_files=[target],
        description="Optimize one symbol",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["_get_intake_action"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "readiness = self.get_intake_readiness()" in updated
    assert "remaining_gaps" in updated
    assert "address_gaps" in updated
    assert "complete_intake" in updated
    assert "intake_readiness_score" in updated
    assert "intake_blockers" in updated
    assert "semantic_blockers" in updated
    assert "if (True)" not in updated
    assert "_INTAKE_GAPS_THRESHOLD" in updated
    assert "gap_threshold" in updated
    assert "data.get('denoising_converged', False)" in updated
    assert "if 'knowledge_graph' not in data" in updated
    assert "if 'dependency_graph' not in data" in updated
    ast.parse(updated)


def test_select_candidates_policy_renderer_preserves_selector_contract():
    optimizer = TestDrivenOptimizer(agent_id="td-select-policy", llm_router=Mock())

    rendered = optimizer._render_select_question_candidates_from_policy(
        {
            "dedupe_selected_candidates": True,
            "dedupe_fallback_candidates": True,
            "selector_mode": "honor_nonempty",
        }
    )

    assert "def select_question_candidates(" in rendered
    assert "selected = selector(normalized_candidates, max_questions=max_questions)" in rendered
    assert "except TypeError:" in rendered
    assert "self._normalize_question_text" in rendered
    assert "normalized_candidates.sort(key=self._default_candidate_sort_key)" in rendered
    assert "return _finalize(normalized_candidates, dedupe=True)" in rendered
    ast.parse(rendered)


def test_select_candidates_policy_response_normalization_rejects_unknown_selector_mode():
    optimizer = TestDrivenOptimizer(agent_id="td-select-policy-invalid", llm_router=Mock())

    with pytest.raises(ValueError, match="unsupported selector_mode"):
        optimizer._normalize_select_candidates_policy_response(
            response='{"dedupe_selected_candidates":true,"dedupe_fallback_candidates":true,"selector_mode":"bogus"}',
            file_path=Path("denoiser.py"),
        )


def test_generate_optimizations_can_use_select_candidates_policy_mode(tmp_path):
    router = Mock()
    router.generate.return_value = """{
  "dedupe_selected_candidates": true,
  "dedupe_fallback_candidates": true,
  "selector_mode": "honor_nonempty"
}"""
    optimizer = TestDrivenOptimizer(agent_id="td-select-policy-generate", llm_router=router)

    target = tmp_path / "denoiser.py"
    target.write_text(
        "from typing import Any, Dict, List\n\n"
        "class ComplaintDenoiser:\n"
        "    def _normalize_question_text(self, text: str) -> str:\n"
        "        return text.strip().lower()\n\n"
        "    def _default_candidate_sort_key(self, candidate: Dict[str, Any]):\n"
        "        return (0, 0)\n\n"
        "    def select_question_candidates(self, candidates: List[Dict[str, Any]], *, max_questions: int = 10, selector: Any = None) -> List[Dict[str, Any]]:\n"
        "        return candidates[:max_questions]\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-select-policy",
        target_files=[target],
        description="Optimize select_question_candidates",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["select_question_candidates"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "def select_question_candidates(" in updated
    assert "self._normalize_question_text" in updated
    assert "_finalize" in updated
    assert "normalized_candidates.sort(key=self._default_candidate_sort_key)" in updated
    ast.parse(updated)
