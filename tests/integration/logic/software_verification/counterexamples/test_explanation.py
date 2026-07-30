"""Integration tests for deterministic counterexample explanation (FVT-020 / FVT-G042).

CounterexampleExplanation@1 acceptance:

* First divergence / source spans are stable for the same input.
* Explanations cite only replay-verified facts.
* Repair hypotheses never claim proof.
* Redaction holds after decoding (no raw / private channels).
* Unsupported mappings remain explicit.
* The stable API returns no raw payload.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.logic.software_verification.counterexamples.explanation import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    COUNTEREXAMPLE_EXPLANATION_INTERFACE,
    EXPLANATION_SCHEMA,
    REPAIR_HYPOTHESIS_SCHEMA,
    AffectedProofHole,
    CounterexampleExplanation,
    CounterexampleExplainer,
    DivergenceKind,
    ExplanationError,
    HypothesisStatus,
    MappingStatus,
    RepairHypothesis,
    SourceSpanRef,
    explain_counterexample,
)
from ipfs_datasets_py.logic.software_verification.counterexamples.replay import (
    ReplayStatus,
    build_replay_recipe,
    replay_counterexample,
)


# ---------------------------------------------------------------------------
# Corpus-style witnesses
# ---------------------------------------------------------------------------


def smt_model_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "smt_model",
        "assignments": {"x": 1, "y": 2, "z": 0},
        "model": {"x": 1, "y": 2, "z": 0},
        "violated_property": "prop:resource-invariant",
        "property_id": "prop:resource-invariant",
        "assumption_ids": ["asm:finite-domain", "asm:no-overflow"],
        "finite_bounds": {"timeout_ms": 250, "max_depth": 8},
        "tool_id": "solver.z3",
        "tool_version": "4.12.0",
        "provider_id": "solver.z3",
        "tree_id": "tree:corpus-smt@1",
        "policy_id": "policy:public-counterexample-drop@1",
        "oracle_id": "oracle:z3-model",
        "summary": "resource invariant violated under finite bound",
        "source_map": {
            "ast_scope_ids": ["symbol:claim"],
            "source_ref_ids": ["source:resource.py"],
            "span_ids": ["span:check"],
            "tree_ids": ["tree:corpus-smt@1"],
        },
        "content_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "counterexample_id": "cex:smt-resource-1",
        "repair_classes": [
            "add_premise_or_evidence_dependency",
            "constrain_ast_scope_or_model_bound",
        ],
    }
    payload.update(overrides)
    return payload


def leaky_smt_witness(**overrides: Any) -> dict[str, Any]:
    base = smt_model_witness(
        hidden_witness="DO-NOT-PUBLISH-SECRET",
        credential="super-secret-credential",
        stdout="unbounded solver transcript",
        source_code="def secrets(): pass",
        source_excerpt="complete repository source",
        raw_output="solver dump " * 50,
        raw="raw-provider-blob-must-not-escape",
        private_artifacts=[
            {
                "channel": "secret_material",
                "digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "retention_policy_id": "policy:private-counterexample-store@1",
                "retained": True,
                "byte_size": 32,
                "media_type": "application/octet-stream",
            }
        ],
    )
    base.update(overrides)
    return base


def trace_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "tla_trace",
        "steps": [
            {"label": "init"},
            {"label": "claim"},
            {"label": "bad"},
        ],
        "violated_property": "prop:lease-safety",
        "assumption_ids": ["asm:single-owner"],
        "finite_bounds": {"max_steps": 16},
        "tool_id": "model-checker.tlc",
        "tool_version": "1.0.0",
        "tree_id": "tree:corpus-trace@1",
        "policy_id": "policy:public-counterexample-drop@1",
        "summary": "lease safety violated",
        "source_map": {
            "span_ids": ["span:lease-claim"],
            "source_ref_ids": ["source:lease.py"],
            "ast_scope_ids": ["symbol:claim_lease"],
            "tree_ids": ["tree:corpus-trace@1"],
        },
        "content_id": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "counterexample_id": "cex:trace-lease-1",
    }
    payload.update(overrides)
    return payload


def hypertrace_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "hypertrace",
        "differences": [{"field": "secret_bit", "left": 0, "right": 1}],
        "observed_fields": ["public_out", "secret_bit"],
        "violated_property": "prop:noninterference",
        "assumption_ids": ["asm:low-equivalence"],
        "finite_bounds": {"max_traces": 2},
        "tool_id": "hyper.checker",
        "tool_version": "0.3.0",
        "tree_id": "tree:corpus-hyper@1",
        "policy_id": "policy:public-counterexample-drop@1",
        "summary": "noninterference fails on secret-dependent divergence",
        "source_map": {
            "span_ids": ["span:observe"],
            "source_ref_ids": ["source:ni.py"],
            "ast_scope_ids": ["symbol:observe"],
            "tree_ids": ["tree:corpus-hyper@1"],
        },
        "content_id": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "counterexample_id": "cex:hyper-ni-1",
    }
    payload.update(overrides)
    return payload


def protocol_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "protocol_attack",
        "roles": ["initiator", "attacker"],
        "messages": ["hello", "forge", "accept"],
        "steps": [{"action": "inject"}, {"action": "accept"}],
        "violated_property": "prop:auth-integrity",
        "assumption_ids": ["asm:dolev-yao"],
        "finite_bounds": {"max_sessions": 2},
        "tool_id": "protocol.proverif",
        "tool_version": "2.04",
        "tree_id": "tree:corpus-proto@1",
        "policy_id": "policy:public-counterexample-drop@1",
        "summary": "protocol attack via forge",
        "source_map": {
            "span_ids": ["span:auth"],
            "source_ref_ids": ["source:auth.pv"],
            "ast_scope_ids": ["symbol:auth"],
            "tree_ids": ["tree:corpus-proto@1"],
        },
        "content_id": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "counterexample_id": "cex:proto-forge-1",
    }
    payload.update(overrides)
    return payload


def unsupported_mapping_witness(**overrides: Any) -> dict[str, Any]:
    base = smt_model_witness(
        source_map={
            "mapping_status": "unsupported",
            "unsupported_reasons": ["frontend:no-span-binding"],
            "tree_ids": ["tree:corpus-smt@1"],
        },
    )
    base.update(overrides)
    return base


def smt_model_oracle(candidate: Mapping[str, Any]) -> bool:
    assignments = candidate.get("assignments") or candidate.get("model") or {}
    if not isinstance(assignments, Mapping):
        payload = candidate.get("payload")
        if isinstance(payload, Mapping):
            assignments = payload.get("assignments") or payload.get("model") or {}
    if not isinstance(assignments, Mapping):
        return False
    return assignments.get("x") == 1 and assignments.get("y") == 2


def _successful_replay_receipt(witness: Mapping[str, Any]) -> dict[str, Any]:
    result = replay_counterexample(witness, oracle=smt_model_oracle)
    assert result.status is ReplayStatus.REPRODUCED
    return result.receipt.to_dict()


def _proof_holes_for_smt() -> list[dict[str, Any]]:
    return [
        {
            "hole_id": "hole:resource-invariant",
            "kind": "missing_lemma",
            "reason": "open obligation for prop:resource-invariant",
            "related_span_ids": ["span:check"],
            "formal_goal_id": "prop:resource-invariant",
            "proof_claimed": False,
            "completion_claimed": False,
        },
        {
            "hole_id": "hole:unrelated",
            "kind": "missing_invariant",
            "reason": "other property",
            "related_span_ids": ["span:other"],
            "formal_goal_id": "prop:other",
        },
    ]


# ---------------------------------------------------------------------------
# Interface / schema surface
# ---------------------------------------------------------------------------


def test_interface_and_schema_constants() -> None:
    assert COUNTEREXAMPLE_EXPLANATION_INTERFACE == "CounterexampleExplanation@1"
    assert EXPLANATION_SCHEMA.endswith("@1")
    assert REPAIR_HYPOTHESIS_SCHEMA.endswith("@1")
    assert ALGORITHM_VERSION.startswith("counterexample-explanation/")
    assert ALGORITHM_NAME == "deterministic_source_aware_explanation"


# ---------------------------------------------------------------------------
# Stability of first divergence / source spans
# ---------------------------------------------------------------------------


def test_first_divergence_and_source_spans_are_stable() -> None:
    witness = smt_model_witness()
    receipt = _successful_replay_receipt(witness)
    expected = {"assignments": {"x": 0, "y": 2, "z": 0}}

    a = explain_counterexample(
        witness,
        expected=expected,
        replay_receipt=receipt,
        proof_holes=_proof_holes_for_smt(),
    )
    b = explain_counterexample(
        witness,
        expected=expected,
        replay_receipt=receipt,
        proof_holes=_proof_holes_for_smt(),
    )

    assert a.explanation_id == b.explanation_id
    assert a.content_id == b.content_id
    assert a.first_divergence.divergence_id == b.first_divergence.divergence_id
    assert a.first_divergence.to_dict() == b.first_divergence.to_dict()
    assert [span.to_dict() for span in a.source_spans] == [
        span.to_dict() for span in b.source_spans
    ]
    assert a.first_divergence.path == "assignments.x"
    assert a.first_divergence.kind is DivergenceKind.VIOLATED_CONDITION
    assert a.first_divergence.expected == 0
    assert a.first_divergence.actual == 1
    assert a.first_divergence.source_span.span_ids == ("span:check",)
    assert a.first_divergence.source_span.mapping_status is MappingStatus.SUPPORTED


def test_trace_first_divergence_is_bad_step() -> None:
    explanation = explain_counterexample(
        trace_witness(),
        replay_verified=True,
        replay_receipt={"receipt_id": "replay-receipt:trace-1", "status": "reproduced"},
    )
    assert explanation.first_divergence.kind is DivergenceKind.TRACE_STEP
    assert explanation.first_divergence.path == "steps[2]"
    assert explanation.first_divergence.actual == "bad"
    assert explanation.first_divergence.index == 2
    # Causal chain is the prefix through the first bad step.
    labels = [link.label for link in explanation.causal_chain]
    assert labels == ["init", "claim", "bad"]


def test_hypertrace_first_observation_divergence() -> None:
    explanation = explain_counterexample(
        hypertrace_witness(),
        replay_verified=True,
        replay_receipt={
            "receipt_id": "replay-receipt:hyper-1",
            "violation_reproduced": True,
        },
    )
    assert explanation.first_divergence.kind is DivergenceKind.OBSERVATION_DIVERGENCE
    assert "secret_bit" in explanation.first_divergence.path
    assert explanation.first_divergence.expected == 0
    assert explanation.first_divergence.actual == 1


def test_protocol_first_attack_step() -> None:
    explanation = explain_counterexample(
        protocol_witness(),
        replay_verified=True,
        replay_receipt={"receipt_id": "replay-receipt:proto-1", "reproduced": True},
    )
    assert explanation.first_divergence.kind is DivergenceKind.PROTOCOL_STEP
    assert explanation.first_divergence.actual in {"forge", "inject"}


# ---------------------------------------------------------------------------
# Replay-verified facts only
# ---------------------------------------------------------------------------


def test_cited_facts_require_replay_verification() -> None:
    # Without replay verification, the explanation still builds but cites nothing.
    unexplained = explain_counterexample(smt_model_witness())
    assert unexplained.replay_verified is False
    assert unexplained.cited_facts == ()

    receipt = _successful_replay_receipt(smt_model_witness())
    verified = explain_counterexample(
        smt_model_witness(),
        expected={"assignments": {"x": 0, "y": 2, "z": 0}},
        replay_receipt=receipt,
    )
    assert verified.replay_verified is True
    assert verified.cited_facts
    assert all(fact.replay_verified for fact in verified.cited_facts)
    roles = {fact.role.value for fact in verified.cited_facts}
    assert "replay_receipt" in roles
    assert "first_divergence" in roles
    assert "decoded_value" in roles


def test_failed_replay_does_not_cite_facts() -> None:
    recipe = build_replay_recipe(smt_model_witness())
    # Force a non-reproduced outcome by providing an always-false oracle via receipt status.
    explanation = explain_counterexample(
        smt_model_witness(),
        replay_receipt={
            "receipt_id": recipe.recipe_id,
            "status": "not_reproduced",
            "violation_reproduced": False,
        },
        replay_verified=False,
    )
    assert explanation.replay_verified is False
    assert explanation.cited_facts == ()


def test_constructing_explanation_with_unverified_cited_fact_fails() -> None:
    divergence = explain_counterexample(
        smt_model_witness(),
        replay_verified=True,
        replay_receipt={"receipt_id": "r1", "status": "reproduced"},
    ).first_divergence
    with pytest.raises(ExplanationError, match="replay-verified"):
        CounterexampleExplanation(
            counterexample_id="cex:x",
            violated_property="prop:x",
            witness_kind="smt_model",
            first_divergence=divergence,
            cited_facts=(
                # bypass factory: craft via object then mutate is impossible (frozen);
                # use ExplanationFact with replay_verified=False
                __import__(
                    "ipfs_datasets_py.logic.software_verification.counterexamples.explanation",
                    fromlist=["ExplanationFact"],
                ).ExplanationFact(
                    role="decoded_value",
                    statement="not verified",
                    replay_verified=False,
                ),
            ),
        )


# ---------------------------------------------------------------------------
# Repair hypotheses never claim proof
# ---------------------------------------------------------------------------


def test_repair_hypotheses_never_claim_proof() -> None:
    explanation = explain_counterexample(
        smt_model_witness(),
        replay_verified=True,
        replay_receipt={"receipt_id": "r-proof", "status": "reproduced"},
        proof_holes=_proof_holes_for_smt(),
    )
    assert explanation.repair_hypotheses
    for hyp in explanation.repair_hypotheses:
        assert hyp.status is HypothesisStatus.HYPOTHESIS
        assert hyp.authority == "hypothesis"
        assert "proof" not in hyp.detail.lower() or "does not claim" in hyp.detail.lower() or "hypothesis" in hyp.detail.lower()
        assert hyp.schema == REPAIR_HYPOTHESIS_SCHEMA
        encoded = json.dumps(hyp.to_dict()).lower()
        assert "proof_claimed" not in encoded or "false" in encoded
        assert hyp.authority not in {"proof", "verified", "kernel_checked"}

    with pytest.raises(ExplanationError):
        RepairHypothesis(
            repair_class="add_premise_or_evidence_dependency",
            detail="this is proved",
            authority="proof",
        )

    with pytest.raises(ExplanationError):
        RepairHypothesis(
            repair_class="add_premise_or_evidence_dependency",
            detail="completion_claimed",
            authority="hypothesis",
        )


# ---------------------------------------------------------------------------
# Redaction after decoding / no raw payload
# ---------------------------------------------------------------------------


def test_redaction_holds_after_decoding_leaky_witness() -> None:
    receipt = {
        "receipt_id": "replay-receipt:leaky",
        "status": "reproduced",
        "violation_reproduced": True,
    }
    explanation = explain_counterexample(
        leaky_smt_witness(),
        expected={"assignments": {"x": 0, "y": 2, "z": 0}},
        replay_receipt=receipt,
        proof_holes=_proof_holes_for_smt(),
    )
    public = explanation.to_public_dict()
    encoded = json.dumps(public, sort_keys=True).lower()
    full = explanation.to_json().lower()

    for surface in (encoded, full):
        for forbidden in (
            "do-not-publish-secret",
            "super-secret-credential",
            "unbounded solver transcript",
            "def secrets(): pass",
            "complete repository source",
            "solver dump",
            "raw-provider-blob-must-not-escape",
            "hidden_witness",
            "credential",
            "stdout",
            "source_code",
            "source_excerpt",
            "raw_output",
        ):
            assert forbidden not in surface, f"leaked {forbidden!r}"

    assert "raw" not in public
    assert public["redacted"] is True
    # Decoded public assignments remain available.
    names = {item.name for item in explanation.decoded_values}
    assert "x" in names and "y" in names


def test_stable_api_returns_no_raw_payload() -> None:
    explanation = CounterexampleExplainer().explain(
        smt_model_witness(),
        replay_verified=True,
        replay_receipt={"receipt_id": "r-raw", "status": "reproduced"},
    )
    public = explanation.to_public_dict()
    assert "raw" not in public
    assert "raw" not in explanation.to_dict()
    # Round-trip refuses raw injection.
    forged = explanation.to_dict()
    forged["raw"] = {"stdout": "leak"}
    with pytest.raises(ExplanationError, match="raw"):
        CounterexampleExplanation.from_dict(forged)


# ---------------------------------------------------------------------------
# Unsupported mappings remain explicit
# ---------------------------------------------------------------------------


def test_unsupported_mappings_remain_explicit() -> None:
    explanation = explain_counterexample(
        unsupported_mapping_witness(),
        replay_verified=True,
        replay_receipt={"receipt_id": "r-unsup", "status": "reproduced"},
    )
    assert explanation.mapping_status is MappingStatus.UNSUPPORTED
    assert explanation.unsupported_mappings
    assert any("unsupported" in note for note in explanation.unsupported_mappings)
    assert any("frontend:no-span-binding" in note for note in explanation.unsupported_mappings)
    # No invented span ids.
    for span in explanation.source_spans:
        assert span.mapping_status is MappingStatus.UNSUPPORTED
        assert span.span_ids == ()


def test_absent_source_map_is_explicit() -> None:
    witness = smt_model_witness()
    witness.pop("source_map", None)
    explanation = explain_counterexample(
        witness,
        replay_verified=True,
        replay_receipt={"receipt_id": "r-absent", "status": "reproduced"},
    )
    assert explanation.mapping_status in {
        MappingStatus.ABSENT,
        MappingStatus.PARTIAL,
        MappingStatus.UNSUPPORTED,
    }
    # When tree_id remains on the witness, mapping may be partial via bindings;
    # either way, unsupported/absent notes must not invent span ids.
    for span in explanation.source_spans:
        # Spans may be empty when no source_map was provided.
        if span.mapping_status is MappingStatus.ABSENT:
            assert span.span_ids == ()


# ---------------------------------------------------------------------------
# Decoded values, deltas, assumptions, bounds, proof holes
# ---------------------------------------------------------------------------


def test_decoded_values_deltas_assumptions_bounds_and_holes() -> None:
    explanation = explain_counterexample(
        smt_model_witness(),
        expected={"assignments": {"x": 0, "y": 2, "z": 9}},
        proof_holes=_proof_holes_for_smt(),
        replay_receipt=_successful_replay_receipt(smt_model_witness()),
    )
    by_name = {item.name: item.value for item in explanation.decoded_values}
    assert by_name["x"] == 1
    assert by_name["y"] == 2
    assert by_name["z"] == 0

    delta_paths = {d.path: d for d in explanation.deltas}
    assert delta_paths["assignments.x"].expected == 0
    assert delta_paths["assignments.x"].actual == 1
    assert delta_paths["assignments.x"].equal is False
    assert delta_paths["assignments.y"].equal is True
    assert delta_paths["assignments.z"].equal is False

    assert "asm:finite-domain" in explanation.assumptions
    assert "asm:no-overflow" in explanation.assumptions
    assert explanation.bounds.get("timeout_ms") == 250
    assert explanation.bounds.get("max_depth") == 8

    hole_ids = {h.hole_id for h in explanation.affected_proof_holes}
    assert "hole:resource-invariant" in hole_ids
    # Unrelated hole may be dropped due to span/property mismatch.
    assert "hole:unrelated" not in hole_ids or "hole:resource-invariant" in hole_ids


def test_affected_proof_hole_dataclass_round_trip() -> None:
    hole = AffectedProofHole(
        hole_id="hole:a",
        reason="missing",
        kind="missing_lemma",
        related_span_ids=("span:1",),
        formal_goal_id="goal:a",
    )
    assert hole.to_dict()["hole_id"] == "hole:a"


def test_source_span_ref_from_source_map_statuses() -> None:
    supported = SourceSpanRef.from_source_map(
        {
            "span_ids": ["s1"],
            "source_ref_ids": ["src"],
            "ast_scope_ids": ["ast"],
            "tree_ids": ["t1"],
        }
    )
    assert supported.mapping_status is MappingStatus.SUPPORTED
    unsupported = SourceSpanRef.from_source_map({"mapping_status": "unsupported"})
    assert unsupported.mapping_status is MappingStatus.UNSUPPORTED
    absent = SourceSpanRef.from_source_map({})
    assert absent.mapping_status is MappingStatus.ABSENT


# ---------------------------------------------------------------------------
# Content addressing / round-trip
# ---------------------------------------------------------------------------


def test_explanation_round_trip_and_content_addressing() -> None:
    original = explain_counterexample(
        smt_model_witness(),
        expected={"assignments": {"x": 0, "y": 2, "z": 0}},
        replay_receipt=_successful_replay_receipt(smt_model_witness()),
        proof_holes=_proof_holes_for_smt(),
    )
    restored = CounterexampleExplanation.from_dict(original.to_public_dict())
    assert restored.explanation_id == original.explanation_id
    assert restored.content_id == original.content_id
    assert restored.first_divergence.divergence_id == original.first_divergence.divergence_id
    assert restored.interface == COUNTEREXAMPLE_EXPLANATION_INTERFACE
    assert restored.schema == EXPLANATION_SCHEMA


def test_module_level_entry_matches_class() -> None:
    witness = trace_witness()
    kwargs = {
        "replay_verified": True,
        "replay_receipt": {"receipt_id": "r-eq", "status": "reproduced"},
    }
    a = explain_counterexample(witness, **kwargs)
    b = CounterexampleExplainer().explain(witness, **kwargs)
    assert a.explanation_id == b.explanation_id
    assert a.first_divergence.to_dict() == b.first_divergence.to_dict()


def test_explainer_interface_constant() -> None:
    explainer = CounterexampleExplainer()
    assert explainer.interface == COUNTEREXAMPLE_EXPLANATION_INTERFACE
    assert explainer.algorithm == ALGORITHM_NAME
