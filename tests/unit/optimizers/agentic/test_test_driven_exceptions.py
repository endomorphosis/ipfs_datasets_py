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


def test_generate_tests_skips_llm_for_symbol_scoped_task(optimizer, tmp_path):
    target = tmp_path / "target.py"
    target.write_text("def f():\n    return 1\n")
    scoped_task = OptimizationTask(
        task_id="task-td-skip-tests",
        target_files=[target],
        description="Optimize target",
        priority=50,
        constraints={"target_symbols": {str(target): ["f"]}},
    )

    result = optimizer._generate_tests(scoped_task, analysis={})

    assert result["success"] is False
    assert result["skipped"] is True
    optimizer.llm_router.generate.assert_not_called()


def test_build_test_generation_prompt_prefers_target_symbols(optimizer, tmp_path):
    phase_manager = tmp_path / "phase_manager.py"
    inquiries = tmp_path / "inquiries.py"
    task = OptimizationTask(
        task_id="task-td-targeted-tests",
        target_files=[phase_manager, inquiries],
        description="Optimize question flow",
        priority=50,
        constraints={
            "target_symbols": {
                str(phase_manager): ["_get_intake_action"],
                str(inquiries): ["get_next", "merge_legal_questions"],
            }
        },
    )
    analysis = {
        "functions": [
            {"name": "_get_intake_action", "file": str(phase_manager), "lineno": 10},
            {"name": "advance_to_phase", "file": str(phase_manager), "lineno": 20},
            {"name": "get_next", "file": str(inquiries), "lineno": 30},
            {"name": "merge_legal_questions", "file": str(inquiries), "lineno": 40},
            {"name": "generate", "file": str(inquiries), "lineno": 50},
        ]
    }

    prompt = optimizer._build_test_generation_prompt(task, analysis)

    assert "_get_intake_action" in prompt
    assert "get_next" in prompt
    assert "merge_legal_questions" in prompt
    assert "advance_to_phase" not in prompt
    assert "generate in" not in prompt


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


def test_generate_optimizations_falls_back_when_action_policy_json_is_invalid(tmp_path):
    router = Mock()
    router.generate.return_value = "not valid json"
    optimizer = TestDrivenOptimizer(agent_id="td-action-fallback", llm_router=router)

    target = tmp_path / "phase_manager.py"
    target.write_text(
        "from typing import Dict, Any\n\n"
        "_INTAKE_GAPS_THRESHOLD = 3\n"
        "_DENOISING_MAX_ITERATIONS = 20\n\n"
        "class ComplaintPhase:\n"
        "    INTAKE = 'intake'\n\n"
        "class PhaseManager:\n"
        "    def __init__(self):\n"
        "        self.phase_data = {ComplaintPhase.INTAKE: {}}\n"
        "        self.iteration_count = 0\n"
        "    def get_intake_readiness(self):\n"
        "        return {'score': 0.5, 'blockers': []}\n"
        "    def _get_intake_action(self) -> Dict[str, Any]:\n"
        "        return {'action': 'continue_denoising'}\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-action-fallback",
        target_files=[target],
        description="Optimize action policy",
        constraints={"target_symbols": {str(target.resolve()): ["_get_intake_action"]}},
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "build_knowledge_graph" in updated
    assert "complete_intake" in updated
    ast.parse(updated)


def test_generate_optimizations_falls_back_when_session_injection_policy_json_is_invalid(tmp_path):
    router = Mock()
    router.generate.return_value = "not valid json"
    optimizer = TestDrivenOptimizer(agent_id="td-session-fallback", llm_router=router)

    target = tmp_path / "session.py"
    target.write_text(
        "from typing import Any, Dict, List, Sequence, Set\n\n"
        "class AdversarialSession:\n"
        "    @classmethod\n"
        "    def _extract_actor_critic_intake_context(cls, seed_complaint):\n"
        "        return {}\n"
        "    @classmethod\n"
        "    def _extract_intake_prompt_candidates(cls, seed_complaint):\n"
        "        return [('When did it happen?', 'timeline')]\n"
        "    @classmethod\n"
        "    def _candidate_matches_intake_objective(cls, question, objective):\n"
        "        return False\n"
        "    @classmethod\n"
        "    def _question_dedupe_key(cls, text):\n"
        "        return str(text).lower()\n"
        "    @classmethod\n"
        "    def _extract_question_text(cls, question):\n"
        "        return str(question.get('question', '')) if isinstance(question, dict) else str(question)\n"
        "    @classmethod\n"
        "    def _questions_substantially_overlap(cls, a, b):\n"
        "        return False\n"
        "    @classmethod\n"
        "    def _inject_intake_prompt_questions(cls, seed_complaint: Dict[str, Any], questions: Sequence[Any]) -> List[Any]:\n"
        "        return list(questions or [])\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-session-fallback",
        target_files=[target],
        description="Optimize session injection policy",
        constraints={"target_symbols": {str(target.resolve()): ["_inject_intake_prompt_questions"]}},
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "stability_recovery_mode" in updated
    assert "synthetic_intake_prompt" in updated
    ast.parse(updated)


def test_generate_optimizations_falls_back_when_complainant_guidance_policy_json_is_invalid(tmp_path):
    router = Mock()
    router.generate.return_value = "not valid json"
    optimizer = TestDrivenOptimizer(agent_id="td-complainant-guidance-fallback", llm_router=router)

    target = tmp_path / "complainant.py"
    target.write_text(
        "from typing import Any, Dict, List\n\n"
        "_ACTOR_CRITIC_PHASE_FOCUS_ORDER = ['graph_analysis', 'document_generation', 'intake_questioning']\n"
        "_EMPATHY_HEAVY_STATES = {'distressed'}\n"
        "_CHRONOLOGY_TERMS = ('when', 'date')\n"
        "_DECISION_MAKER_TERMS = ('who', 'manager')\n"
        "_DOCUMENT_ARTIFACT_TERMS = ('document', 'notice')\n\n"
        "class ComplaintContext:\n"
        "    def __init__(self, complaint_type='unknown', key_facts=None):\n"
        "        self.complaint_type = complaint_type\n"
        "        self.key_facts = key_facts or {}\n"
        "        self.workflow_phase_priorities = []\n"
        "        self.blocker_objectives = []\n"
        "        self.emotional_state = 'distressed'\n\n"
        "def _ordered_workflow_phases(values, explicit_phase_order=None):\n"
        "    return explicit_phase_order or list(values or [])\n\n"
        "def _extract_confirmation_placeholders(_payload):\n"
        "    return []\n\n"
        "def _order_objectives_for_actor_critic(values, phase_focus_order=None):\n"
        "    return list(values or [])\n\n"
        "def _objective_follow_up_prompt(value):\n"
        "    return f'Follow up on {value}'\n\n"
        "class Complainant:\n"
        "    def __init__(self):\n"
        "        self.context = ComplaintContext()\n"
        "    def _build_actor_critic_guidance(self, question: str) -> str:\n"
        "        return question\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-complainant-guidance-fallback",
        target_files=[target],
        description="Optimize complainant guidance policy",
        constraints={"target_symbols": {str(target.resolve()): ["_build_actor_critic_guidance"]}},
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "still needs confirmation" in updated
    assert "Phase focus order:" in updated
    ast.parse(updated)


def test_generate_optimizations_falls_back_when_merge_seed_with_grounding_policy_json_is_invalid(tmp_path):
    router = Mock()
    router.generate.return_value = "not valid json"
    optimizer = TestDrivenOptimizer(agent_id="td-merge-seed-fallback", llm_router=router)

    target = tmp_path / "synthesize_hacc_complaint.py"
    target.write_text(
        "from typing import Any, Dict, List\n"
        "import ast\n"
        "import re\n\n"
        "def _refresh_seed_source_snippets(seed):\n"
        "    return dict(seed or {})\n"
        "def _normalize_intake_objective(value):\n"
        "    return str(value or '').strip().lower()\n"
        "def _to_sentence(value):\n"
        "    return str(value or '').strip()\n"
        "def _safe_float(value, default=0.0):\n"
        "    return float(value or default)\n"
        "INTAKE_OBJECTIVE_PRIORITY = {}\n"
        "def _merge_seed_with_grounding(seed: Dict[str, Any], grounding_bundle: Dict[str, Any]) -> Dict[str, Any]:\n"
        "    merged = _refresh_seed_source_snippets(dict(seed or {}))\n"
        "    key_facts = dict(merged.get('key_facts') or {})\n"
        "    anchor_passages = [dict(item) for item in list(key_facts.get('anchor_passages') or []) if isinstance(item, dict)]\n"
        "    for passage in anchor_passages[:4]:\n"
        "        pass\n"
        "    for evidence in [dict(item) for item in list(merged.get(\"hacc_evidence\") or []) if isinstance(item, dict)][:6]:\n"
        "        pass\n"
        "    blocker_handoff_raw_answers = []\n"
        "    for answer in blocker_handoff_raw_answers[:8]:\n"
        "        pass\n"
        "    prioritized = []\n"
        "    for objective in prioritized[:4]:\n"
        "        pass\n"
        "    return merged\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-merge-seed-fallback",
        target_files=[target],
        description="Optimize merge_seed_with_grounding policy",
        constraints={"target_symbols": {str(target.resolve()): ["_merge_seed_with_grounding"]}},
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "anchor_passages[:5]" in updated
    assert "hacc_evidence\") or []) if isinstance(item, dict)][:8]" in updated
    assert "blocker_handoff_raw_answers[:6]" in updated
    assert "prioritized[:3]" in updated
    ast.parse(updated)


def test_generate_optimizations_falls_back_when_inquiries_policy_json_is_invalid(tmp_path):
    router = Mock()
    router.generate.return_value = "not valid json"
    optimizer = TestDrivenOptimizer(agent_id="td-inquiries-fallback", llm_router=router)

    target = tmp_path / "inquiries.py"
    target.write_text(
        "from typing import Any, Dict, List\n\n"
        "class Inquiries:\n"
        "    def _state_inquiries(self):\n"
        "        return []\n"
        "    def _index_for(self, inquiries):\n"
        "        return {}\n"
        "    def _build_gap_context(self):\n"
        "        return {}\n"
        "    def _normalize_question(self, text):\n"
        "        return text.lower()\n"
        "    def _priority_rank(self, value):\n"
        "        return 0\n"
        "    def get_next(self):\n"
        "        return None\n"
        "    def merge_legal_questions(self, questions: List[Dict[str, Any]]) -> int:\n"
        "        return 0\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-inquiries-fallback",
        target_files=[target],
        description="Optimize inquiries policy",
        constraints={"target_symbols": {str(target.resolve()): ["get_next", "merge_legal_questions"]}},
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "dependency_gap_targeted" in updated
    assert "legal_question" in updated
    ast.parse(updated)


def test_replace_symbols_in_source_preserves_tab_indentation(tmp_path):
    router = Mock()
    router.generate.return_value = "not valid json"
    optimizer = TestDrivenOptimizer(agent_id="td-tabs", llm_router=router)

    target = tmp_path / "inquiries.py"
    target.write_text(
        "from typing import Any, Dict, List\n\n"
        "class Inquiries:\n"
        "\tdef _state_inquiries(self):\n"
        "\t\treturn []\n"
        "\tdef _index_for(self, inquiries):\n"
        "\t\treturn {}\n"
        "\tdef _build_gap_context(self):\n"
        "\t\treturn {}\n"
        "\tdef _normalize_question(self, text):\n"
        "\t\treturn text.lower()\n"
        "\tdef _priority_rank(self, value):\n"
        "\t\treturn 0\n"
        "\tdef get_next(self):\n"
        "\t\treturn None\n"
        "\tdef merge_legal_questions(self, questions: List[Dict[str, Any]]) -> int:\n"
        "\t\treturn 0\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-tabs",
        target_files=[target],
        description="Optimize inquiries policy",
        constraints={"target_symbols": {str(target.resolve()): ["get_next", "merge_legal_questions"]}},
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "\tdef get_next(self):" in updated
    assert "\tdef merge_legal_questions(self, questions: List[Dict[str, Any]]) -> int:" in updated
    ast.parse(updated)


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


def test_dependency_readiness_policy_renderer_preserves_return_contract():
    optimizer = TestDrivenOptimizer(agent_id="td-dependency-readiness", llm_router=Mock())

    rendered = optimizer._render_get_claim_readiness_from_policy(
        {
            "prioritize_blocking_gaps": True,
            "prioritize_structured_gaps": True,
            "promote_deterministic_gap_targets": True,
            "boost_weak_claim_types": True,
            "boost_weak_evidence_modalities": True,
            "gap_stall_action_threshold": 2,
        }
    )

    assert "def get_claim_readiness(self) -> Dict[str, Any]:" in rendered
    assert "recommended_next_gaps.sort(" in rendered
    assert "deterministic_update_key" in rendered
    assert "gap_stall_sessions" in rendered
    assert "'recommended_actions': recommended_actions" in rendered
    assert "'actor_critic': {" in rendered
    assert "'graph_analysis': {" in rendered
    ast.parse(rendered)


def test_dependency_readiness_policy_response_normalization_rejects_out_of_range_threshold():
    optimizer = TestDrivenOptimizer(agent_id="td-dependency-readiness-invalid", llm_router=Mock())

    with pytest.raises(ValueError, match="out-of-range gap_stall_action_threshold"):
        optimizer._normalize_dependency_readiness_policy_response(
            response='{"prioritize_blocking_gaps":true,"prioritize_structured_gaps":true,"promote_deterministic_gap_targets":true,"boost_weak_claim_types":true,"boost_weak_evidence_modalities":true,"gap_stall_action_threshold":9}',
            file_path=Path("dependency_graph.py"),
        )


def test_document_workflow_targeting_policy_renderer_preserves_return_contract():
    optimizer = TestDrivenOptimizer(agent_id="td-document-workflow-targeting", llm_router=Mock())

    rendered = optimizer._render_document_workflow_targeting_from_policy(
        {
            "graph_blocker_weight": 0.08,
            "document_blocker_weight": 0.06,
            "intake_objective_weight": 0.05,
            "boost_document_for_notice_chain": True,
            "preserve_graph_priority_when_factual_pressure_high": True,
        }
    )

    assert "def _build_workflow_phase_targeting(" in rendered
    assert "'graph_analysis': _clamp(" in rendered
    assert "'document_generation': _clamp(" in rendered
    assert "'intake_questioning': _clamp(" in rendered
    assert "self._select_phase_target_section(" in rendered
    assert "'phase_focus_order': phase_focus_order" in rendered
    ast.parse(rendered)


def test_knowledge_graph_build_policy_renderer_preserves_return_contract():
    optimizer = TestDrivenOptimizer(agent_id="td-knowledge-graph-build", llm_router=Mock())

    rendered = optimizer._render_knowledge_graph_build_from_text_from_policy(
        {
            "normalize_whitespace_input": True,
            "record_source_text_char_count": True,
            "record_extraction_counts": True,
            "mark_empty_input_graph": True,
            "preserve_actor_critic_metadata": True,
        }
    )

    assert "def build_from_text(self, text: str) -> KnowledgeGraph:" in rendered
    assert "normalized_text = ' '.join(source_text.split())" in rendered
    assert "graph.metadata['source_text_char_count'] = len(normalized_text)" in rendered
    assert "graph.metadata['build_status'] = 'empty_input'" in rendered
    assert "graph.metadata['extracted_entity_candidates'] = len(entities)" in rendered
    assert "graph.metadata[\"actor_critic\"] = {" in rendered
    assert "self._built_graphs.append(graph)" in rendered
    ast.parse(rendered)


def test_complainant_guidance_policy_renderer_preserves_return_contract():
    optimizer = TestDrivenOptimizer(agent_id="td-complainant-guidance", llm_router=Mock())

    rendered = optimizer._render_complainant_guidance_from_policy(
        {
            "unresolved_objective_limit": 2,
            "include_follow_up_prompt_examples": True,
            "encourage_empathy_opening": True,
            "include_document_precision_guidance": True,
            "include_phase_focus_line": True,
        }
    )

    assert "def _build_actor_critic_guidance(self, question: str) -> str:" in rendered
    assert "ComplaintContext(complaint_type='unknown', key_facts={})" in rendered
    assert "still needs confirmation" in rendered
    assert "Suggested high-yield follow-up prompts" in rendered
    assert "Phase focus order:" in rendered
    ast.parse(rendered)


def test_merge_seed_with_grounding_policy_transform_preserves_function_shape():
    optimizer = TestDrivenOptimizer(agent_id="td-merge-seed-policy", llm_router=Mock())
    source = (
        "def _merge_seed_with_grounding(seed, grounding_bundle):\n"
        "    anchor_passages = []\n"
        "    for passage in anchor_passages[:4]:\n"
        "        pass\n"
        "    merged = {}\n"
        "    for evidence in [dict(item) for item in list(merged.get(\"hacc_evidence\") or []) if isinstance(item, dict)][:6]:\n"
        "        pass\n"
        "    blocker_handoff_raw_answers = []\n"
        "    for answer in blocker_handoff_raw_answers[:8]:\n"
        "        pass\n"
        "    prioritized = []\n"
        "    for objective in prioritized[:4]:\n"
        "        pass\n"
        "    return merged\n"
    )

    rendered = optimizer._apply_merge_seed_with_grounding_policy_to_source(
        source,
        {
            "anchor_passage_limit": 6,
            "evidence_item_limit": 7,
            "blocker_answer_limit": 5,
            "unresolved_objective_limit": 2,
        },
    )

    assert "anchor_passages[:6]" in rendered
    assert "[:7]:" in rendered
    assert "blocker_handoff_raw_answers[:5]" in rendered
    assert "prioritized[:2]" in rendered
    ast.parse(rendered)


def test_formal_document_render_policy_transform_preserves_function_shape():
    optimizer = TestDrivenOptimizer(agent_id="td-formal-document-render-policy", llm_router=Mock())
    source = (
        "def render_text(self, draft):\n"
        "    chronology_lines = []\n"
        "    for index, chronology_line in enumerate(chronology_lines, 1):\n"
        "        pass\n"
        "    supporting_facts = []\n"
        "    for fact in supporting_facts:\n"
        "        pass\n"
        "    exhibits = []\n"
        "    for exhibit in exhibits:\n"
        "        pass\n"
        "    affidavit = {}\n"
        "    for index, fact in enumerate(_listify(affidavit.get(\"facts\")), 1):\n"
        "        pass\n"
        "    return ''\n"
    )

    rendered = optimizer._apply_formal_document_render_policy_to_source(
        source,
        {
            "chronology_line_limit": 4,
            "supporting_fact_limit": 3,
            "exhibit_limit": 6,
            "affidavit_fact_limit": 5,
        },
    )

    assert "chronology_lines[:4]" in rendered
    assert "supporting_facts[:3]" in rendered
    assert "exhibits[:6]" in rendered
    assert "affidavit.get(\"facts\"))[:5]" in rendered
    ast.parse(rendered)


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
def target_method(self):
    return {"action": "broken"
"""
    optimizer = TestDrivenOptimizer(agent_id="td-symbols-error", llm_router=router)

    target = tmp_path / "generic_module.py"
    target.write_text(
        "class Example:\n"
        "    def target_method(self):\n"
        "        return {'action': 'continue_denoising'}\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-symbols-error",
        target_files=[target],
        description="Optimize one symbol",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["target_method"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})

    assert result == {}
    assert optimizer._last_generation_diagnostics[0]["mode"] == "symbol_level"
    assert "raw_response_preview" in optimizer._last_generation_diagnostics[0]
    assert "target_method" in optimizer._last_generation_diagnostics[0]["raw_response_preview"]


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


def test_generate_optimizations_can_use_dependency_readiness_policy_mode(tmp_path):
    router = Mock()
    router.generate.return_value = """{
  "prioritize_blocking_gaps": true,
  "prioritize_structured_gaps": true,
  "promote_deterministic_gap_targets": true,
  "boost_weak_claim_types": true,
  "boost_weak_evidence_modalities": true,
  "gap_stall_action_threshold": 2
}"""
    optimizer = TestDrivenOptimizer(agent_id="td-dependency-readiness-generate", llm_router=router)

    target = tmp_path / "dependency_graph.py"
    target.write_text(
        "import re\n"
        "from typing import Any, Dict, List, Optional\n\n"
        "_ACTOR_CRITIC_PHASE_FOCUS_ORDER = ('graph_analysis',)\n"
        "_ACTOR_CRITIC_PRIORITY = 70\n"
        "_ACTOR_CRITIC_FOCUS_METRICS = {'information_extraction': 0.72}\n"
        "_ACTOR_CRITIC_WEAK_CLAIM_TYPES = {'housing_discrimination'}\n"
        "_ACTOR_CRITIC_WEAK_EVIDENCE_MODALITIES = {'policy_document'}\n\n"
        "def _utc_now_isoformat():\n"
        "    return '2026-03-21T00:00:00+00:00'\n\n"
        "class NodeType:\n"
        "    CLAIM = 'claim'\n"
        "    REQUIREMENT = 'requirement'\n"
        "    LEGAL_ELEMENT = 'legal_element'\n\n"
        "class DependencyNode:\n"
        "    pass\n\n"
        "class Dependency:\n"
        "    pass\n\n"
        "class DependencyGraph:\n"
        "    def get_nodes_by_type(self, node_type):\n"
        "        return []\n\n"
        "    def get_node(self, node_id):\n"
        "        return None\n\n"
        "    def get_claim_readiness(self) -> Dict[str, Any]:\n"
        "        return {'overall_readiness': 0.0}\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-dependency-readiness",
        target_files=[target],
        description="Optimize get_claim_readiness",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["get_claim_readiness"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "def get_claim_readiness(self) -> Dict[str, Any]:" in updated
    assert "recommended_next_gaps.sort(" in updated
    assert "deterministic_update_key" in updated
    assert "'weak_claim_gap_count': weak_claim_gap_count" in updated
    assert "'weak_evidence_modalities': sorted(_ACTOR_CRITIC_WEAK_EVIDENCE_MODALITIES)" in updated
    ast.parse(updated)


def test_generate_optimizations_can_use_document_workflow_targeting_policy_mode(tmp_path):
    router = Mock()
    router.generate.return_value = """{
  "graph_blocker_weight": 0.08,
  "document_blocker_weight": 0.06,
  "intake_objective_weight": 0.05,
  "boost_document_for_notice_chain": true,
  "preserve_graph_priority_when_factual_pressure_high": true
}"""
    optimizer = TestDrivenOptimizer(agent_id="td-document-workflow-generate", llm_router=router)

    target = tmp_path / "document_optimization.py"
    target.write_text(
        "from typing import Any, Dict\n\n"
        "def _normalize_intake_objective(value):\n"
        "    return str(value or '').strip().lower()\n\n"
        "def _clamp(value, minimum=0.0, maximum=1.0):\n"
        "    return max(minimum, min(maximum, float(value)))\n\n"
        "class AgenticDocumentOptimizer:\n"
        "    WORKFLOW_PHASE_FOCUS_ORDER = ('graph_analysis', 'document_generation', 'intake_questioning')\n\n"
        "    def _select_phase_target_section(self, *, phase_name, section_scores, unresolved_objectives, chronology_context_active=False):\n"
        "        return 'factual_allegations'\n\n"
        "    def _build_workflow_phase_targeting(self, *, section_scores: Dict[str, float], support_context: Dict[str, Any]) -> Dict[str, Any]:\n"
        "        return {'phase_scores': {}, 'phase_focus_order': [], 'phase_target_sections': {}}\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-document-workflow-targeting",
        target_files=[target],
        description="Optimize document workflow targeting",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["_build_workflow_phase_targeting"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "def _build_workflow_phase_targeting(" in updated
    assert "'document_generation': _clamp(" in updated
    assert "self._select_phase_target_section(" in updated
    ast.parse(updated)


def test_generate_optimizations_can_use_knowledge_graph_build_policy_mode(tmp_path):
    router = Mock()
    router.generate.return_value = """{
  "normalize_whitespace_input": true,
  "record_source_text_char_count": true,
  "record_extraction_counts": true,
  "mark_empty_input_graph": true,
  "preserve_actor_critic_metadata": true
}"""
    optimizer = TestDrivenOptimizer(agent_id="td-knowledge-graph-build-generate", llm_router=router)

    target = tmp_path / "knowledge_graph.py"
    target.write_text(
        "from typing import Any, Dict\n\n"
        "class KnowledgeGraph:\n"
        "    def __init__(self):\n"
        "        self.entities = {}\n"
        "        self.relationships = {}\n"
        "        self.metadata = {}\n\n"
        "    def add_entity(self, entity):\n"
        "        self.entities[entity.id] = entity\n\n"
        "    def add_relationship(self, relationship):\n"
        "        self.relationships[relationship.id] = relationship\n\n"
        "    def summary(self):\n"
        "        return {'total_entities': len(self.entities), 'total_relationships': len(self.relationships)}\n\n"
        "class Entity:\n"
        "    def __init__(self, id, type, name, attributes, confidence, source):\n"
        "        self.id = id\n"
        "        self.type = type\n"
        "        self.name = name\n"
        "        self.attributes = attributes\n"
        "        self.confidence = confidence\n"
        "        self.source = source\n\n"
        "class Relationship:\n"
        "    def __init__(self, id, source_id, target_id, relation_type, attributes, confidence, source):\n"
        "        self.id = id\n"
        "        self.source_id = source_id\n"
        "        self.target_id = target_id\n"
        "        self.relation_type = relation_type\n"
        "        self.attributes = attributes\n"
        "        self.confidence = confidence\n"
        "        self.source = source\n\n"
        "class Logger:\n"
        "    def info(self, message):\n"
        "        return None\n\n"
        "logger = Logger()\n\n"
        "class KnowledgeGraphBuilder:\n"
        "    def __init__(self):\n"
        "        self._built_graphs = []\n"
        "        self._text_processed_count = 0\n"
        "        self.actor_critic_enabled = True\n"
        "        self.min_entity_actor_critic_score = -0.3\n"
        "        self.min_relationship_actor_critic_score = -0.1\n\n"
        "    def _get_entity_id(self):\n"
        "        return 'entity-1'\n\n"
        "    def _get_relationship_id(self):\n"
        "        return 'rel-1'\n\n"
        "    def _extract_entities(self, text):\n"
        "        return []\n\n"
        "    def _extract_relationships(self, text, graph):\n"
        "        return []\n\n"
        "    def build_from_text(self, text: str) -> KnowledgeGraph:\n"
        "        graph = KnowledgeGraph()\n"
        "        return graph\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-knowledge-graph-build",
        target_files=[target],
        description="Optimize knowledge graph build_from_text",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["build_from_text"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "def build_from_text(self, text: str) -> KnowledgeGraph:" in updated
    assert "normalized_text = ' '.join(source_text.split())" in updated
    assert "graph.metadata['source_text_char_count'] = len(normalized_text)" in updated
    assert "graph.metadata['extracted_entity_candidates'] = len(entities)" in updated
    assert "graph.metadata[\"actor_critic\"] = {" in updated
    ast.parse(updated)


def test_generate_optimizations_can_use_formal_document_render_policy_mode(tmp_path):
    router = Mock()
    router.generate.return_value = """{
  "chronology_line_limit": 4,
  "supporting_fact_limit": 3,
  "exhibit_limit": 6,
  "affidavit_fact_limit": 5
}"""
    optimizer = TestDrivenOptimizer(agent_id="td-formal-document-render-generate", llm_router=router)

    target = tmp_path / "formal_document.py"
    target.write_text(
        "from typing import Any, Dict, List\n\n"
        "def _clean_sentence(value):\n"
        "    return str(value or '').strip()\n\n"
        "def _clean_text(value):\n"
        "    return str(value or '').strip()\n\n"
        "def _listify(value):\n"
        "    if isinstance(value, list):\n"
        "        return value\n"
        "    if value is None:\n"
        "        return []\n"
        "    return [value]\n\n"
        "class ComplaintDocumentBuilder:\n"
        "    def _signature_block_lines(self, signature_block):\n"
        "        return []\n\n"
        "    def render_text(self, draft: Dict[str, Any]) -> str:\n"
        "        lines: List[str] = []\n"
        "        chronology_lines = [_clean_sentence(item) for item in _listify(draft.get('anchored_chronology_summary')) if _clean_text(item)]\n"
        "        if chronology_lines:\n"
        "            for index, chronology_line in enumerate(chronology_lines, 1):\n"
        "                lines.append(f'{index}. {chronology_line}')\n"
        "        claims = _listify(draft.get('legal_claims'))\n"
        "        for claim in claims:\n"
        "            supporting_facts = _listify(claim.get('supporting_facts'))\n"
        "            for fact in supporting_facts:\n"
        "                lines.append(f'- {_clean_sentence(fact)}')\n"
        "        exhibits = _listify(draft.get('exhibits'))\n"
        "        for exhibit in exhibits:\n"
        "            lines.append(str(exhibit))\n"
        "        affidavit = draft.get('affidavit', {}) if isinstance(draft.get('affidavit'), dict) else {}\n"
        "        for index, fact in enumerate(_listify(affidavit.get(\"facts\")), 1):\n"
        "            lines.append(f'{index}. {_clean_sentence(fact)}')\n"
        "        lines.extend(self._signature_block_lines({}))\n"
        "        return '\\n'.join(line for line in lines if line is not None)\n",
        encoding="utf-8",
    )
    task = OptimizationTask(
        task_id="task-formal-document-render",
        target_files=[target],
        description="Optimize formal document render_text",
        constraints={
            "target_symbols": {
                str(target.resolve()): ["render_text"],
            }
        },
    )

    result = optimizer._generate_optimizations(task, analysis={}, baseline={})
    updated = result[str(target)]

    assert "enumerate(chronology_lines[:4], 1)" in updated
    assert "for fact in supporting_facts[:3]:" in updated
    assert "for exhibit in exhibits[:6]:" in updated
    assert "_listify(affidavit.get(\"facts\"))[:5]" in updated
    ast.parse(updated)
