"""Tests for the hammer-style ITP/ATP bridge."""

from __future__ import annotations

import time

import pytest

from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    CallableHammerBackendRunner,
    HammerBackendResult,
    HammerBackendStatus,
    HammerGoal,
    HammerLogicTranslator,
    HammerPipeline,
    HammerPremise,
    HammerStatus,
    HammerVerification,
    HeuristicPremiseSelector,
    hammer_prove,
)
from ipfs_datasets_py.logic.integration.reasoning.hammer_backends import (
    PythonZ3HammerBackendRunner,
)


def _proved_backend(name: str = "z3", problem_format: str = "smt-lib"):
    def _run(translation, timeout_seconds):
        return HammerBackendResult(
            backend=name,
            status=HammerBackendStatus.PROVED,
            proved=True,
            elapsed_seconds=min(0.01, timeout_seconds),
            translation_format=translation.target_format,
            proof_trace="unsat",
            raw_output="unsat",
        )

    return CallableHammerBackendRunner(name, problem_format, _run)


def _unknown_backend(name: str = "e_prover", problem_format: str = "tptp-fof"):
    def _run(translation, timeout_seconds):
        return HammerBackendResult(
            backend=name,
            status=HammerBackendStatus.UNKNOWN,
            proved=False,
            elapsed_seconds=min(0.01, timeout_seconds),
            translation_format=translation.target_format,
            raw_output="SZS status Unknown",
        )

    return CallableHammerBackendRunner(name, problem_format, _run)


def test_premise_selector_filters_relevant_legal_theorems() -> None:
    selector = HeuristicPremiseSelector()
    goal = HammerGoal(
        "The agency must provide notice before terminating benefits.",
        metadata={"modal_family": "deontic", "program_synthesis_scope": "deontic"},
    )
    premises = [
        HammerPremise(
            "notice_obligation",
            "If an agency terminates benefits, the agency must provide notice.",
            metadata={"modal_family": "deontic", "program_synthesis_scope": "deontic"},
        ),
        HammerPremise("parks_definition", "A park may include trails and trees."),
        HammerPremise("tax_rate", "The tax rate is adjusted annually."),
    ]

    selection = selector.select(goal, premises, max_premises=1)

    assert [premise.name for premise in selection.selected] == ["notice_obligation"]
    assert selection.scores["notice_obligation"] > 0.0


def test_hammer_pipeline_translates_searches_and_reconstructs_lean_script() -> None:
    goal = HammerGoal(
        "P",
        itp_system="lean",
        name="notice_obligation_goal",
        metadata={"itp_statement": "True", "lean_imports": ""},
    )
    premises = [HammerPremise("premise_true", "True")]

    result = hammer_prove(
        goal,
        premises,
        backends=[_proved_backend()],
        max_premises=4,
        timeout_seconds=1,
    )

    assert result.status == HammerStatus.PROVED
    assert result.reconstruction is not None
    assert "theorem notice_obligation_goal" in result.reconstruction.proof_script
    assert "aesop" in result.reconstruction.proof_script
    assert result.translations["smt-lib"].problem.endswith("(check-sat)\n")


def test_hammer_pipeline_verifies_reconstruction_with_injected_kernel() -> None:
    calls = []

    def _verifier(itp_system, proof_script, goal, selected_premises):
        calls.append((itp_system, proof_script, goal.name, len(selected_premises)))
        return HammerVerification(
            verified="aesop" in proof_script,
            checker="fake-lean-kernel",
            output="ok",
        )

    result = hammer_prove(
        HammerGoal("P", itp_system="lean", metadata={"itp_statement": "True"}),
        [HammerPremise("p", "P")],
        backends=[_proved_backend()],
        verify_reconstruction=True,
        kernel_verifier=_verifier,
    )

    assert result.status == HammerStatus.PROVED
    assert result.reconstruction is not None
    assert result.reconstruction.verified is True
    assert result.reconstruction.verification is not None
    assert result.reconstruction.verification.checker == "fake-lean-kernel"
    assert calls


def test_hammer_pipeline_fails_closed_when_kernel_rejects_reconstruction() -> None:
    def _verifier(itp_system, proof_script, goal, selected_premises):
        return HammerVerification(
            verified=False,
            checker="fake-lean-kernel",
            error="type mismatch",
        )

    result = hammer_prove(
        HammerGoal("P", itp_system="lean", metadata={"itp_statement": "False"}),
        [HammerPremise("p", "P")],
        backends=[_proved_backend()],
        verify_reconstruction=True,
        kernel_verifier=_verifier,
    )

    assert result.status == HammerStatus.RECONSTRUCTION_FAILED
    assert result.reconstruction is not None
    assert result.reconstruction.error == "type mismatch"
    assert any(item.startswith("hammer_failed:reconstruction_failed") for item in result.fallback_plan)


def test_hammer_pipeline_reports_fallback_when_no_backend_proves() -> None:
    result = hammer_prove(
        "The agency must notify the person; the person may appeal.",
        ["A generic unrelated premise."],
        backends=[_unknown_backend()],
    )

    assert result.status == HammerStatus.UNPROVED
    assert result.reconstruction is None
    assert result.fallback_plan[0] == "hammer_failed:no_backend_proof"
    assert any(item.startswith("subgoal_") for item in result.fallback_plan)


def test_hammer_pipeline_runs_backend_search_in_parallel() -> None:
    def _slow_unknown(translation, timeout_seconds):
        time.sleep(0.15)
        return HammerBackendResult(
            backend="slow",
            status=HammerBackendStatus.UNKNOWN,
            proved=False,
            elapsed_seconds=0.15,
            translation_format=translation.target_format,
        )

    def _fast_proved(translation, timeout_seconds):
        time.sleep(0.01)
        return HammerBackendResult(
            backend="fast",
            status=HammerBackendStatus.PROVED,
            proved=True,
            elapsed_seconds=0.01,
            translation_format=translation.target_format,
            proof_trace="proof",
        )

    pipeline = HammerPipeline(
        backends=[
            CallableHammerBackendRunner("slow", "smt-lib", _slow_unknown),
            CallableHammerBackendRunner("fast", "smt-lib", _fast_proved),
        ],
        parallel_workers=2,
        timeout_seconds=1,
    )

    started = time.time()
    result = pipeline.prove("P", ["P implies P"])

    assert result.status == HammerStatus.PROVED
    assert result.backend_results[0].backend == "fast"
    assert time.time() - started < 0.25


def test_tptp_backend_gets_tptp_translation() -> None:
    captured = {}

    def _run(translation, timeout_seconds):
        captured["format"] = translation.target_format
        captured["problem"] = translation.problem
        return HammerBackendResult(
            backend="vampire",
            status=HammerBackendStatus.PROVED,
            proved=True,
            elapsed_seconds=0.01,
            translation_format=translation.target_format,
            proof_trace="SZS status Theorem",
        )

    result = hammer_prove(
        HammerGoal("Goal"),
        [HammerPremise("lemma_one", "Goal")],
        backends=[CallableHammerBackendRunner("vampire", "tptp-fof", _run)],
    )

    assert result.status == HammerStatus.PROVED
    assert captured["format"] == "tptp-fof"
    assert "fof(lemma_one, axiom" in captured["problem"]
    assert "fof(hammer_generated_goal, conjecture" in captured["problem"]


def test_typed_legal_ir_conjunct_is_not_lowered_as_an_opaque_goal() -> None:
    pytest.importorskip("z3")
    translator = HammerLogicTranslator()
    translation = translator.translate(
        HammerGoal(
            "temporal_anchor(event:e1, time:t1)",
            name="typed_tdfol_candidate",
        ),
        [
            HammerPremise(
                "typed_contract",
                "temporal_anchor(event:e1, time:t1) "
                "and event_order(before:e1, after:e2)",
            )
        ],
        target_format="smt-lib",
    )

    result = PythonZ3HammerBackendRunner().run(translation, timeout_seconds=1.0)

    assert "(assert (and " in translation.problem
    assert result.status is HammerBackendStatus.PROVED
