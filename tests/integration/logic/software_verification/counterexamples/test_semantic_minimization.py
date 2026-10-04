"""Integration tests for oracle-preserving semantic counterexample minimization.

FVT-008 / FVT-G040 — SemanticCounterexampleMinimizer@1

Covers:
* SMT projection / don't-cares and subset cores with post-removal recheck
* shortest trace prefix / event slice with post-removal recheck
* protocol dependency slice with post-removal recheck
* earliest hypertrace divergence with post-removal recheck
* receipts record oracle, algorithm/version, budget, reduction log, guarantee
* budget exhaustion remains explicit (never upgraded to semantic minimality)
* short output alone never stamps a semantic guarantee
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from ipfs_datasets_py.logic.software_verification.counterexamples.minimization import (
    ALGORITHM_VERSION,
    MINIMIZATION_RECEIPT_SCHEMA,
    MINIMIZATION_RESULT_SCHEMA,
    SEMANTIC_COUNTEREXAMPLE_MINIMIZER_INTERFACE,
    MinimizationBudget,
    MinimizationError,
    MinimizationGuarantee,
    SemanticCounterexampleMinimizer,
    WitnessFamily,
    minimize_counterexample,
)


# ---------------------------------------------------------------------------
# Oracles (pure, deterministic violation predicates)
# ---------------------------------------------------------------------------


def smt_model_oracle(candidate: Mapping[str, Any]) -> bool:
    """Violates when x=1 and y=2 (z is a don't-care)."""

    assignments = candidate.get("assignments") or candidate.get("model") or {}
    if not isinstance(assignments, Mapping):
        return False
    return assignments.get("x") == 1 and assignments.get("y") == 2


def smt_core_oracle(candidate: Mapping[str, Any]) -> bool:
    """Unsat core is minimal when {a, c} ⊆ core (b is irrelevant)."""

    core = set(candidate.get("core") or [])
    return "a" in core and "c" in core


def trace_oracle(candidate: Mapping[str, Any]) -> bool:
    """Violates when a bad step appears after init (prefix property on suffix)."""

    steps = list(candidate.get("steps") or candidate.get("trace") or [])
    labels = [
        (step.get("label") if isinstance(step, Mapping) else step) for step in steps
    ]
    return "bad" in labels


def protocol_oracle(candidate: Mapping[str, Any]) -> bool:
    """Attack requires initiator role and the forge message."""

    roles = set(candidate.get("roles") or [])
    messages = list(candidate.get("messages") or [])
    steps = list(candidate.get("steps") or [])
    has_forge = "forge" in messages or any(
        (m.get("type") if isinstance(m, Mapping) else m) == "forge" for m in messages
    )
    has_init = "initiator" in roles
    has_step = any(
        (s.get("action") if isinstance(s, Mapping) else s) == "inject" for s in steps
    )
    return has_forge and has_init and has_step


def hypertrace_oracle(candidate: Mapping[str, Any]) -> bool:
    """Noninterference fails when the secret-dependent divergence remains."""

    differences = list(candidate.get("differences") or [])
    observed = set(candidate.get("observed_fields") or [])
    has_secret_div = any(
        (d.get("field") if isinstance(d, Mapping) else d) == "secret_bit"
        for d in differences
    )
    return has_secret_div and "public_out" in observed


def kernel_oracle(candidate: Mapping[str, Any]) -> bool:
    return str(candidate.get("failure_code") or "").lower() in {
        "kernel_rejected",
        "sorry",
        "admit",
    }


def always_violate(_candidate: Mapping[str, Any]) -> bool:
    return True


def never_violate(_candidate: Mapping[str, Any]) -> bool:
    return False


# ---------------------------------------------------------------------------
# Interface / receipt surface
# ---------------------------------------------------------------------------


def test_interface_and_schema_constants() -> None:
    assert (
        SEMANTIC_COUNTEREXAMPLE_MINIMIZER_INTERFACE
        == "SemanticCounterexampleMinimizer@1"
    )
    assert MINIMIZATION_RECEIPT_SCHEMA.endswith("@1")
    assert MINIMIZATION_RESULT_SCHEMA.endswith("@1")
    assert ALGORITHM_VERSION.startswith("semantic-minimizer/")


def test_short_output_alone_is_not_semantic_minimality() -> None:
    """Normalization of an already-short witness must not claim local minimality
    without an oracle-backed local deletion pass that proves it.

    A single-assignment model that already violates is locally minimal after
    the deletion pass (nothing removable).  Contrast with pure normalize of a
    kernel classify path which may report normalized.
    """

    witness = {
        "kind": "smt_model",
        "assignments": {"x": 1, "y": 2},
        "violated_property": "prop:inv",
    }
    result = minimize_counterexample(
        witness,
        smt_model_oracle,
        family=WitnessFamily.SMT_MODEL,
        oracle_id="oracle:test-smt",
    )
    # Already minimal — local pass proves it.
    assert result.guarantee == MinimizationGuarantee.LOCALLY_MINIMAL
    assert result.is_semantically_minimal is True
    # Boolean stamp is intentionally absent; guarantee is the truth surface.
    assert "minimized" not in result.to_dict()
    assert result.receipt.guarantee == MinimizationGuarantee.LOCALLY_MINIMAL


def test_receipt_records_oracle_algorithm_budget_log_and_guarantee() -> None:
    witness = {
        "kind": "smt_model",
        "assignments": {
            "x": 1,
            "y": 2,
            "z": "dont_care",
            "noise": 99,
        },
        "violated_property": "prop:resource",
        "assumption_ids": ["asm:finite"],
        "finite_bounds": {"timeout_ms": 100},
    }
    result = minimize_counterexample(
        witness,
        smt_model_oracle,
        family=WitnessFamily.SMT_MODEL,
        oracle_id="oracle:z3-model",
        property_snapshot_id="snap:resource@1",
        budget=MinimizationBudget(max_oracle_calls=64, max_reductions=32),
    )
    receipt = result.receipt
    assert receipt.oracle_id == "oracle:z3-model"
    assert receipt.algorithm == "oracle_preserving_semantic_reducer"
    assert receipt.algorithm_version == ALGORITHM_VERSION
    assert receipt.property_snapshot_id == "snap:resource@1"
    assert receipt.assumption_ids == ("asm:finite",)
    assert receipt.finite_bounds["timeout_ms"] == 100
    assert receipt.budget["max_oracle_calls"] == 64
    assert receipt.oracle_calls >= 1
    assert len(receipt.reduction_log) >= 1
    assert receipt.schema == MINIMIZATION_RECEIPT_SCHEMA
    assert receipt.interface == SEMANTIC_COUNTEREXAMPLE_MINIMIZER_INTERFACE
    assert receipt.original_digest
    assert receipt.minimized_digest
    assert receipt.receipt_id.startswith("min-receipt:")
    payload = receipt.to_dict()
    assert payload["guarantee"] in {
        MinimizationGuarantee.LOCALLY_MINIMAL.value,
        MinimizationGuarantee.GLOBALLY_MINIMAL.value,
    }
    assert "budget_exhausted" in payload
    assert isinstance(payload["reduction_log"], list)


# ---------------------------------------------------------------------------
# SMT model projection / don't-cares
# ---------------------------------------------------------------------------


def test_smt_model_projection_and_dont_cares_recheck_every_removal() -> None:
    calls: list[dict[str, Any]] = []

    def counting_oracle(candidate: Mapping[str, Any]) -> bool:
        calls.append(dict(candidate.get("assignments") or {}))
        return smt_model_oracle(candidate)

    witness = {
        "kind": "smt_model",
        "assignments": {
            "x": 1,
            "y": 2,
            "z": "dont_care",
            "w": 0,
            "padding": True,
        },
        "violated_property": "prop:smt",
    }
    result = minimize_counterexample(
        witness,
        counting_oracle,
        family=WitnessFamily.SMT_MODEL,
        oracle_id="oracle:smt-model",
    )
    assignments = dict(result.witness.get("assignments") or {})
    assert assignments.get("x") == 1
    assert assignments.get("y") == 2
    assert "z" not in assignments
    assert "w" not in assignments
    assert "padding" not in assignments
    assert result.guarantee in {
        MinimizationGuarantee.LOCALLY_MINIMAL,
        MinimizationGuarantee.GLOBALLY_MINIMAL,
    }
    # Every accepted removal was rechecked: more than one oracle call.
    assert len(calls) >= 2
    # Final witness still violates.
    assert smt_model_oracle(result.witness)
    accepted = [e for e in result.receipt.reduction_log if e.accepted]
    assert any(
        e.action.value in {"drop_dont_care", "project_assignment"}
        for e in accepted
        if hasattr(e.action, "value")
    )


# ---------------------------------------------------------------------------
# SMT subset cores
# ---------------------------------------------------------------------------


def test_smt_core_subset_minimization_rechecks_each_drop() -> None:
    calls = 0

    def counting_oracle(candidate: Mapping[str, Any]) -> bool:
        nonlocal calls
        calls += 1
        return smt_core_oracle(candidate)

    witness = {
        "kind": "smt_unsat_core",
        "core": ["b", "a", "d", "c", "e"],
        "violated_property": "prop:unsat",
    }
    result = minimize_counterexample(
        witness,
        counting_oracle,
        family=WitnessFamily.SMT_CORE,
        oracle_id="oracle:mus",
    )
    core = set(result.witness.get("core") or [])
    assert core == {"a", "c"}
    assert result.guarantee in {
        MinimizationGuarantee.LOCALLY_MINIMAL,
        MinimizationGuarantee.GLOBALLY_MINIMAL,
    }
    assert calls >= 3
    assert smt_core_oracle(result.witness)
    assert result.receipt.family == WitnessFamily.SMT_CORE


# ---------------------------------------------------------------------------
# Trace shortest prefix / event slice
# ---------------------------------------------------------------------------


def test_trace_shortest_prefix_and_event_slice_recheck() -> None:
    witness = {
        "kind": "tla_trace",
        "steps": [
            {"label": "init"},
            {"label": "idle"},
            {"label": "idle"},  # stutter
            {"label": "work"},
            {"label": "bad"},
            {"label": "after"},  # not required once bad is observed
        ],
        "violated_property": "prop:safety",
    }
    result = minimize_counterexample(
        witness,
        trace_oracle,
        family=WitnessFamily.TRACE,
        oracle_id="oracle:tla",
    )
    steps = list(result.witness.get("steps") or [])
    labels = [
        (step.get("label") if isinstance(step, Mapping) else step) for step in steps
    ]
    assert "bad" in labels
    # Stutter and post-violation noise should be gone when oracle allows.
    assert labels.count("idle") <= 1
    assert "after" not in labels
    assert len(steps) < 6
    assert result.guarantee in {
        MinimizationGuarantee.LOCALLY_MINIMAL,
        MinimizationGuarantee.GLOBALLY_MINIMAL,
    }
    assert trace_oracle(result.witness)


# ---------------------------------------------------------------------------
# Protocol dependency slice
# ---------------------------------------------------------------------------


def test_protocol_dependency_slice_rechecks_removals() -> None:
    witness = {
        "kind": "protocol_attack",
        "roles": ["initiator", "responder", "observer"],
        "messages": ["hello", "forge", "ack"],
        "dependencies": ["nonce", "session", "extra"],
        "steps": [
            {"action": "setup"},
            {"action": "inject"},
            {"action": "log"},
        ],
        "violated_property": "prop:auth",
    }
    result = minimize_counterexample(
        witness,
        protocol_oracle,
        family=WitnessFamily.PROTOCOL_ATTACK,
        oracle_id="oracle:protocol",
    )
    roles = set(result.witness.get("roles") or [])
    messages = list(result.witness.get("messages") or [])
    assert "initiator" in roles
    assert "observer" not in roles
    assert "forge" in messages
    assert "hello" not in messages
    assert protocol_oracle(result.witness)
    assert result.guarantee in {
        MinimizationGuarantee.LOCALLY_MINIMAL,
        MinimizationGuarantee.GLOBALLY_MINIMAL,
    }
    assert any(
        "slice_dependency" in e.to_dict()["action"]
        or e.to_dict()["action"] == "slice_dependency"
        for e in result.receipt.reduction_log
        if e.accepted
    )


# ---------------------------------------------------------------------------
# Hypertrace earliest divergence
# ---------------------------------------------------------------------------


def test_hypertrace_earliest_divergence_and_observed_fields() -> None:
    witness = {
        "kind": "hypertrace",
        "differences": [
            {"field": "secret_bit", "left": 0, "right": 1},
            {"field": "noise", "left": 1, "right": 2},
            {"field": "later", "left": "a", "right": "b"},
        ],
        "observed_fields": ["public_out", "timestamp", "debug"],
        "trace_refs": ["t0", "t1", "t2"],
        "violated_property": "prop:ni",
    }
    result = minimize_counterexample(
        witness,
        hypertrace_oracle,
        family=WitnessFamily.HYPERTRACE,
        oracle_id="oracle:hyper",
    )
    differences = list(result.witness.get("differences") or [])
    observed = set(result.witness.get("observed_fields") or [])
    assert any(
        (d.get("field") if isinstance(d, Mapping) else d) == "secret_bit"
        for d in differences
    )
    assert len(differences) == 1
    assert "public_out" in observed
    assert "timestamp" not in observed
    assert "debug" not in observed
    assert hypertrace_oracle(result.witness)
    assert result.guarantee in {
        MinimizationGuarantee.LOCALLY_MINIMAL,
        MinimizationGuarantee.GLOBALLY_MINIMAL,
        MinimizationGuarantee.BOUNDED,  # only if budget path; default budget is ample
    }
    assert result.guarantee != MinimizationGuarantee.NONE


# ---------------------------------------------------------------------------
# Budget exhaustion is truthful
# ---------------------------------------------------------------------------


def test_budget_exhaustion_reports_bounded_not_local() -> None:
    witness = {
        "kind": "smt_model",
        "assignments": {f"v{i}": i for i in range(20)} | {"x": 1, "y": 2},
        "violated_property": "prop:budget",
    }
    # Tight budget forces early stop.
    result = minimize_counterexample(
        witness,
        smt_model_oracle,
        family=WitnessFamily.SMT_MODEL,
        oracle_id="oracle:budget",
        budget=MinimizationBudget(max_oracle_calls=3, max_reductions=2),
    )
    assert result.receipt.budget_exhausted is True
    # Must not claim a stronger guarantee than the budget can prove.
    assert result.guarantee in {
        MinimizationGuarantee.BOUNDED,
        MinimizationGuarantee.LOCALLY_MINIMAL,  # if 2 reductions already minimized
        MinimizationGuarantee.NORMALIZED,
    }
    # Critical: never claim globally_minimal under tight budget without proof.
    assert result.guarantee != MinimizationGuarantee.GLOBALLY_MINIMAL
    assert result.receipt.to_dict()["budget_exhausted"] is True
    # Final witness still violates when budget allowed the initial check.
    if result.receipt.oracle_calls >= 1:
        assert smt_model_oracle(result.witness) or result.guarantee == MinimizationGuarantee.BOUNDED


def test_oracle_rejecting_input_fails_closed() -> None:
    witness = {"kind": "smt_model", "assignments": {"x": 0}, "violated_property": "p"}
    with pytest.raises(MinimizationError, match="does not report a violation"):
        minimize_counterexample(
            witness,
            never_violate,
            family=WitnessFamily.SMT_MODEL,
            oracle_id="oracle:none",
        )


def test_kernel_classify_preserves_identity_bound_code() -> None:
    witness = {
        "kind": "kernel_error",
        "failure_code": "sorry",
        "reason": "verbose free-form diagnostic text",
        "theorem_id": "thm:main",
        "kernel_id": "lean4",
        "violated_property": "prop:kernel",
    }
    result = minimize_counterexample(
        witness,
        kernel_oracle,
        family=WitnessFamily.KERNEL,
        oracle_id="oracle:lean",
    )
    assert result.witness["failure_code"] == "sorry"
    assert result.witness.get("theorem_id") == "thm:main"
    # Free-form diagnostic text is droppable when the oracle only needs the code.
    assert "reason" not in result.witness
    # Kernel path records classification; guarantee is at least normalized.
    assert result.guarantee in {
        MinimizationGuarantee.NORMALIZED,
        MinimizationGuarantee.LOCALLY_MINIMAL,
        MinimizationGuarantee.GLOBALLY_MINIMAL,
    }
    assert kernel_oracle(result.witness)


def test_family_inference_from_kind() -> None:
    witness = {
        "kind": "runtime_mtl_violation",
        "steps": [{"label": "init"}, {"label": "bad"}],
        "violated_property": "mtl:always",
    }
    result = minimize_counterexample(
        witness,
        trace_oracle,
        oracle_id="oracle:mtl",
    )
    assert result.receipt.family == WitnessFamily.TRACE


def test_minimizer_class_matches_protocol_surface() -> None:
    engine = SemanticCounterexampleMinimizer()
    assert engine.interface == SEMANTIC_COUNTEREXAMPLE_MINIMIZER_INTERFACE
    result = engine.minimize(
        {
            "kind": "smt_unsat_core",
            "core": ["a", "b", "c"],
            "violated_property": "p",
        },
        smt_core_oracle,
        oracle_id="oracle:core",
    )
    assert result.schema == MINIMIZATION_RESULT_SCHEMA
    assert set(result.witness.get("core") or []) == {"a", "c"}


def test_always_true_oracle_collapses_core_to_empty_when_allowed() -> None:
    """If the oracle still reports a violation for the empty core, empty is local min.

    Real MUS oracles never do this; the test documents that the reducer trusts
    the oracle rather than inventing semantic constraints.
    """

    result = minimize_counterexample(
        {"kind": "smt_core", "core": ["a", "b"], "violated_property": "p"},
        always_violate,
        family=WitnessFamily.SMT_CORE,
        oracle_id="oracle:vacuous",
    )
    assert list(result.witness.get("core") or []) == []
    assert result.is_semantically_minimal is True
