"""Integration tests for semantic witness equivalence (FVT-022 / FVT-G043).

CounterexampleSemanticEquivalence@1 acceptance:

* Syntactic variants of one witness deduplicate only under a reviewed semantic
  relation (never by bare content hash alone).
* Materially different causal paths remain diverse under coverage selection.
* Cross-provider disagreement is retained with both receipts and cannot raise
  authority or be reported as consensus.
* Contradictory evidence is never discarded.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.software_verification.counterexamples.equivalence import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE,
    DIFFERENTIAL_COMPARISON_SCHEMA,
    DISAGREEMENT_QUARANTINE_SCHEMA,
    DIVERSITY_SELECTION_SCHEMA,
    EQUIVALENCE_REPORT_SCHEMA,
    CoverageDimension,
    CounterexampleSemanticEquivalence,
    DifferentialStatus,
    EquivalenceError,
    EquivalenceRelationKind,
    EquivalenceVerdict,
    ProviderObservation,
    ProviderOutcome,
    WitnessFamily,
    are_semantically_equivalent,
    deduplicate_witnesses,
    differential_compare_providers,
    project_witness,
    quarantine_provider_disagreement,
    select_diverse_witnesses,
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
        "summary": "resource invariant violated under finite bound",
        "content_id": (
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ),
        "counterexample_id": "cex:smt-resource-1",
        "authority": "satisfiability",
    }
    payload.update(overrides)
    return payload


def syntactic_variant_of_smt(base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Same semantic witness with different syntactic presentation.

    Different counterexample_id, content_id, tool metadata, key order, and
    summary — must still collapse under the reviewed semantic relation.
    """

    src = dict(base or smt_model_witness())
    # Re-order / re-wrap assignments without changing meaning.
    assignments = dict(src.get("assignments") or {})
    reordered = {k: assignments[k] for k in sorted(assignments.keys(), reverse=True)}
    return smt_model_witness(
        assignments=reordered,
        model=dict(reordered),
        counterexample_id="cex:smt-resource-1-syn-variant",
        content_id=(
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        ),
        tool_id="solver.cvc5",
        tool_version="1.0.5",
        provider_id="solver.cvc5",
        summary="alternate packaging of the same model",
        # Same property / assumptions / bounds / assignments.
        property_id=src["property_id"],
        violated_property=src["violated_property"],
        assumption_ids=list(src["assumption_ids"]),
        finite_bounds=dict(src["finite_bounds"]),
    )


def different_causal_smt() -> dict[str, Any]:
    """Materially different causal path: different assignment values."""

    return smt_model_witness(
        assignments={"x": 9, "y": 9, "z": 0},
        model={"x": 9, "y": 9, "z": 0},
        counterexample_id="cex:smt-resource-other-path",
        content_id=(
            "sha256:cccccccccccccccccccccccccccccccc"
            "cccccccccccccccccccccccccccccccc"
        ),
    )


def different_property_smt() -> dict[str, Any]:
    return smt_model_witness(
        property_id="prop:other-invariant",
        violated_property="prop:other-invariant",
        counterexample_id="cex:smt-other-prop",
        content_id=(
            "sha256:dddddddddddddddddddddddddddddddd"
            "dddddddddddddddddddddddddddddddd"
        ),
    )


def trace_witness(steps: list[Any] | None = None, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "tla_trace",
        "steps": steps
        or [
            {"label": "init"},
            {"label": "claim"},
            {"label": "bad"},
        ],
        "violated_property": "prop:lease-safety",
        "property_id": "prop:lease-safety",
        "assumption_ids": ["asm:single-owner"],
        "finite_bounds": {"max_steps": 16},
        "tool_id": "model-checker.tlc",
        "tool_version": "1.0.0",
        "tree_id": "tree:corpus-trace@1",
        "content_id": (
            "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
            "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        ),
        "counterexample_id": "cex:trace-lease-1",
    }
    payload.update(overrides)
    return payload


def hypertrace_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "hypertrace",
        "differences": [{"field": "secret_bit", "left": 0, "right": 1}],
        "observed_fields": ["public_out"],
        "property_id": "prop:noninterference",
        "violated_property": "prop:noninterference",
        "assumption_ids": ["asm:low-equiv"],
        "finite_bounds": {"traces": 2},
        "tool_id": "hyper.checker",
        "counterexample_id": "cex:hyper-1",
        "content_id": (
            "sha256:ffffffffffffffffffffffffffffffff"
            "ffffffffffffffffffffffffffffffff"
        ),
    }
    payload.update(overrides)
    return payload


def protocol_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "protocol_attack",
        "roles": ["initiator", "attacker"],
        "messages": [{"type": "forge"}, {"type": "accept"}],
        "steps": [{"action": "inject"}, {"action": "complete"}],
        "property_id": "prop:auth-agreement",
        "violated_property": "prop:auth-agreement",
        "assumption_ids": ["asm:dy-adversary"],
        "finite_bounds": {"sessions": 2},
        "counterexample_id": "cex:proto-1",
        "content_id": (
            "sha256:11111111111111111111111111111111"
            "11111111111111111111111111111111"
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Interface / schema surface
# ---------------------------------------------------------------------------


def test_interface_and_schema_constants() -> None:
    assert (
        COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE
        == "CounterexampleSemanticEquivalence@1"
    )
    assert EQUIVALENCE_REPORT_SCHEMA.endswith("@1")
    assert DIVERSITY_SELECTION_SCHEMA.endswith("@1")
    assert DIFFERENTIAL_COMPARISON_SCHEMA.endswith("@1")
    assert DISAGREEMENT_QUARANTINE_SCHEMA.endswith("@1")
    assert ALGORITHM_VERSION.startswith("counterexample-semantic-equivalence/")
    assert ALGORITHM_NAME


def test_engine_exposes_stable_interface() -> None:
    engine = CounterexampleSemanticEquivalence()
    assert engine.interface == COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE
    assert engine.algorithm == ALGORITHM_NAME
    assert engine.algorithm_version == ALGORITHM_VERSION


# ---------------------------------------------------------------------------
# Reviewed semantic relation — not bare hashes
# ---------------------------------------------------------------------------


def test_projection_never_uses_content_hash_alone() -> None:
    witness = smt_model_witness()
    projection = project_witness(witness)
    assert projection.relation_reviewed is True
    assert projection.uses_content_hash_alone is False
    payload = projection.to_dict()
    assert payload["relation_reviewed"] is True
    assert payload["uses_content_hash_alone"] is False
    # Semantic key is derived from the projection core, not content_id.
    assert projection.semantic_key().startswith("sem:")
    assert witness["content_id"] not in projection.semantic_key()
    assert witness["counterexample_id"] not in projection.semantic_key()


def test_syntactic_variants_deduplicate_under_reviewed_relation() -> None:
    a = smt_model_witness()
    b = syntactic_variant_of_smt(a)
    # Different raw identities.
    assert a["content_id"] != b["content_id"]
    assert a["counterexample_id"] != b["counterexample_id"]
    assert a["tool_id"] != b["tool_id"]

    pair = are_semantically_equivalent(a, b)
    assert pair.verdict == EquivalenceVerdict.EQUIVALENT
    assert pair.equivalent is True
    assert pair.used_content_hash_alone is False
    assert pair.left_semantic_key == pair.right_semantic_key
    assert pair.relation == EquivalenceRelationKind.REVIEWED_PROJECTION

    report = deduplicate_witnesses([a, b, a])
    assert report.input_count == 3
    assert report.unique_count == 1
    assert report.duplicate_count == 2
    assert report.used_content_hash_alone is False
    assert len(report.clusters) == 1
    assert len(report.clusters[0].member_indices) == 3
    assert report.clusters[0].to_dict()["size"] == 3
    assert report.algorithm_version == ALGORITHM_VERSION
    assert report.report_id.startswith("eq-report:")


def test_bare_content_id_equality_is_not_semantic_equivalence() -> None:
    """Same content_id with different causal payload must NOT collapse.

    Conflict policy: do not use hashes alone as semantic equivalence.
    """

    left = smt_model_witness(
        content_id="sha256:" + "a" * 64,
        assignments={"x": 1, "y": 2},
        model={"x": 1, "y": 2},
    )
    right = smt_model_witness(
        content_id="sha256:" + "a" * 64,  # same hash label
        counterexample_id="cex:different-path",
        assignments={"x": 7, "y": 8},
        model={"x": 7, "y": 8},
    )
    assert left["content_id"] == right["content_id"]
    pair = are_semantically_equivalent(left, right)
    assert pair.verdict == EquivalenceVerdict.DISTINCT
    assert pair.equivalent is False
    assert pair.used_content_hash_alone is False


def test_different_property_ids_are_distinct() -> None:
    pair = are_semantically_equivalent(smt_model_witness(), different_property_smt())
    assert pair.verdict == EquivalenceVerdict.DISTINCT
    assert "property_id" in pair.detail


def test_different_families_are_incomparable() -> None:
    pair = are_semantically_equivalent(smt_model_witness(), trace_witness())
    assert pair.verdict == EquivalenceVerdict.INCOMPARABLE
    assert "famil" in pair.detail.lower()


# ---------------------------------------------------------------------------
# Causal path diversity / coverage selection
# ---------------------------------------------------------------------------


def test_materially_different_causal_paths_remain_diverse() -> None:
    path_a = smt_model_witness()
    path_b = different_causal_smt()
    path_c = syntactic_variant_of_smt(path_a)

    pair = are_semantically_equivalent(path_a, path_b)
    assert pair.verdict == EquivalenceVerdict.DISTINCT

    selection = select_diverse_witnesses([path_a, path_c, path_b])
    # Syntactic variant of path_a collapses; path_b is a distinct causal path.
    assert selection.input_count == 3
    assert selection.selected_count == 2
    assert set(selection.selected_indices) == {0, 2}
    assert selection.selection_id.startswith("eq-diversity:")
    assert CoverageDimension.CAUSAL_PATH.value in selection.dimensions
    # Coverage keys themselves are distinct.
    assert len(set(selection.coverage_keys)) == 2


def test_trace_causal_paths_cover_distinct_step_sequences() -> None:
    t1 = trace_witness(
        steps=[{"label": "init"}, {"label": "claim"}, {"label": "bad"}],
        counterexample_id="cex:trace-a",
    )
    t2 = trace_witness(
        steps=[{"label": "init"}, {"label": "claim"}, {"label": "bad"}],
        counterexample_id="cex:trace-a-variant",
        content_id="sha256:" + "2" * 64,
        tool_id="model-checker.other",
    )
    t3 = trace_witness(
        steps=[{"label": "init"}, {"label": "renew"}, {"label": "expire"}],
        counterexample_id="cex:trace-b",
        content_id="sha256:" + "3" * 64,
    )

    report = deduplicate_witnesses([t1, t2, t3])
    assert report.unique_count == 2
    assert report.duplicate_count == 1

    selection = select_diverse_witnesses(
        [t1, t2, t3],
        dimensions=[
            CoverageDimension.PROPERTY_ID,
            CoverageDimension.CAUSAL_PATH,
            CoverageDimension.FAMILY,
        ],
    )
    assert selection.selected_count == 2
    ids = set(selection.selected_ids)
    assert "cex:trace-a" in ids or "cex:trace-a-variant" in ids
    assert "cex:trace-b" in ids


def test_hypertrace_and_protocol_projections_are_family_specific() -> None:
    h1 = hypertrace_witness()
    h2 = hypertrace_witness(
        differences=[{"field": "other_secret", "left": 0, "right": 1}],
        counterexample_id="cex:hyper-2",
        content_id="sha256:" + "4" * 64,
    )
    p1 = protocol_witness()
    p2 = protocol_witness(
        messages=[{"type": "replay"}, {"type": "accept"}],
        counterexample_id="cex:proto-2",
        content_id="sha256:" + "5" * 64,
    )

    assert are_semantically_equivalent(h1, h2).verdict == EquivalenceVerdict.DISTINCT
    assert are_semantically_equivalent(p1, p2).verdict == EquivalenceVerdict.DISTINCT
    assert project_witness(h1).family == WitnessFamily.HYPERTRACE
    assert project_witness(p1).family == WitnessFamily.PROTOCOL_ATTACK

    selection = select_diverse_witnesses([h1, h2, p1, p2])
    assert selection.selected_count == 4


def test_max_select_bounds_diversity() -> None:
    witnesses = [
        different_causal_smt(),
        different_property_smt(),
        trace_witness(),
        hypertrace_witness(),
    ]
    selection = select_diverse_witnesses(witnesses, max_select=2)
    assert selection.selected_count == 2
    assert len(selection.selected_indices) == 2


# ---------------------------------------------------------------------------
# Cross-provider differential + quarantine
# ---------------------------------------------------------------------------


def test_cross_provider_agreement_can_claim_consensus_without_raising_authority() -> None:
    observations = [
        ProviderObservation(
            provider_id="solver.z3",
            outcome=ProviderOutcome.VIOLATION,
            receipt_id="receipt:z3-1",
            authority="satisfiability",
        ),
        ProviderObservation(
            provider_id="solver.cvc5",
            outcome=ProviderOutcome.SAT,
            receipt_id="receipt:cvc5-1",
            authority="satisfiability",
        ),
    ]
    comparison = differential_compare_providers(
        observations, witness=smt_model_witness()
    )
    assert comparison.status == DifferentialStatus.AGREEMENT
    assert comparison.agreed is True
    assert comparison.is_consensus is True
    assert comparison.consensus_claimed is True
    assert comparison.requires_quarantine is False
    assert set(comparison.retained_receipt_ids) == {"receipt:z3-1", "receipt:cvc5-1"}
    # Ceiling is min of inputs — not elevated.
    assert comparison.authority_ceiling == "satisfiability"
    assert comparison.comparison_id.startswith("eq-diff:")


def test_cross_provider_disagreement_retains_both_receipts_and_blocks_consensus() -> None:
    observations = [
        {
            "provider_id": "solver.z3",
            "outcome": "violation",
            "receipt_id": "receipt:z3-yes",
            "authority": "theorem",
        },
        {
            "provider_id": "solver.cvc5",
            "outcome": "unsat",
            "receipt_id": "receipt:cvc5-no",
            "authority": "theorem",
        },
    ]
    comparison = differential_compare_providers(observations)
    assert comparison.status == DifferentialStatus.DISAGREEMENT
    assert comparison.agreed is False
    assert comparison.is_consensus is False
    assert comparison.consensus_claimed is False
    assert comparison.requires_quarantine is True
    # Both receipts retained — contradictory evidence not discarded.
    assert set(comparison.retained_receipt_ids) == {
        "receipt:z3-yes",
        "receipt:cvc5-no",
    }
    assert set(comparison.disagreeing_provider_ids) == {
        "solver.z3",
        "solver.cvc5",
    }
    # Authority cannot rise above the disagreement cap.
    assert comparison.authority_ceiling in {"none", "advisory"}
    payload = comparison.to_dict()
    assert payload["is_consensus"] is False
    assert payload["consensus_claimed"] is False
    assert payload["requires_quarantine"] is True


def test_quarantine_refuses_authority_raise_and_keeps_all_receipts() -> None:
    comparison = differential_compare_providers(
        [
            ProviderObservation(
                provider_id="solver.z3",
                outcome=ProviderOutcome.VIOLATION,
                receipt_id="receipt:z3",
                authority="bounded",
            ),
            ProviderObservation(
                provider_id="solver.cvc5",
                outcome=ProviderOutcome.NO_VIOLATION,
                receipt_id="receipt:cvc5",
                authority="bounded",
            ),
        ]
    )
    assert comparison.requires_quarantine

    quarantine = quarantine_provider_disagreement(
        comparison, requested_authority="theorem"
    )
    assert quarantine.status == "quarantined"
    assert quarantine.authority_raised is False
    assert quarantine.is_consensus is False
    assert quarantine.consensus_claimed is False
    assert quarantine.discarded_evidence is False
    assert set(quarantine.retained_receipt_ids) == {"receipt:z3", "receipt:cvc5"}
    assert set(quarantine.provider_ids) == {"solver.z3", "solver.cvc5"}
    # Requested theorem authority must not stick.
    assert quarantine.authority_ceiling in {"none", "advisory"}
    assert _authority_rank_local(quarantine.authority_ceiling) <= _authority_rank_local(
        "advisory"
    )
    assert quarantine.quarantine_id.startswith("eq-quarantine:")
    body = quarantine.to_dict()
    assert body["authority_raised"] is False
    assert body["consensus_claimed"] is False
    assert body["discarded_evidence"] is False
    assert body["is_consensus"] is False
    assert len(body["observations"]) == 2
    assert body["schema"] == DISAGREEMENT_QUARANTINE_SCHEMA


def _authority_rank_local(value: str) -> int:
    ranks = {
        "none": 0,
        "advisory": 1,
        "bounded": 2,
        "satisfiability": 3,
        "theorem": 5,
    }
    return ranks.get(value, 0)


def test_quarantine_requires_disagreement() -> None:
    comparison = differential_compare_providers(
        [
            ProviderObservation(
                provider_id="solver.z3",
                outcome=ProviderOutcome.VIOLATION,
                receipt_id="r1",
            ),
            ProviderObservation(
                provider_id="solver.cvc5",
                outcome=ProviderOutcome.VIOLATION,
                receipt_id="r2",
            ),
        ]
    )
    assert comparison.status == DifferentialStatus.AGREEMENT
    with pytest.raises(EquivalenceError, match="disagreement"):
        quarantine_provider_disagreement(comparison)


def test_partial_and_inconclusive_never_claim_consensus() -> None:
    partial = differential_compare_providers(
        [
            ProviderObservation(
                provider_id="solver.z3",
                outcome=ProviderOutcome.VIOLATION,
                receipt_id="r-z3",
            ),
            ProviderObservation(
                provider_id="solver.timeout",
                outcome=ProviderOutcome.TIMEOUT,
                receipt_id="r-to",
            ),
        ]
    )
    assert partial.status == DifferentialStatus.PARTIAL
    assert partial.is_consensus is False
    assert partial.consensus_claimed is False
    assert set(partial.retained_receipt_ids) == {"r-z3", "r-to"}

    inconclusive = differential_compare_providers(
        [
            ProviderObservation(
                provider_id="a",
                outcome=ProviderOutcome.TIMEOUT,
                receipt_id="r-a",
            ),
            ProviderObservation(
                provider_id="b",
                outcome=ProviderOutcome.UNAVAILABLE,
                receipt_id="r-b",
            ),
        ]
    )
    assert inconclusive.status == DifferentialStatus.INCONCLUSIVE
    assert inconclusive.is_consensus is False
    assert inconclusive.consensus_claimed is False


def test_single_provider_is_not_consensus() -> None:
    comparison = differential_compare_providers(
        [
            ProviderObservation(
                provider_id="solver.z3",
                outcome=ProviderOutcome.VIOLATION,
                receipt_id="r1",
                authority="satisfiability",
            )
        ]
    )
    assert comparison.status == DifferentialStatus.SINGLE_PROVIDER
    assert comparison.is_consensus is False
    assert comparison.consensus_claimed is False


def test_duplicate_provider_ids_fail_closed() -> None:
    with pytest.raises(EquivalenceError, match="unique"):
        differential_compare_providers(
            [
                ProviderObservation(
                    provider_id="solver.z3",
                    outcome=ProviderOutcome.VIOLATION,
                    receipt_id="r1",
                ),
                ProviderObservation(
                    provider_id="solver.z3",
                    outcome=ProviderOutcome.NO_VIOLATION,
                    receipt_id="r2",
                ),
            ]
        )


# ---------------------------------------------------------------------------
# End-to-end cohesion: dedup → diversity → differential quarantine
# ---------------------------------------------------------------------------


def test_end_to_end_dedup_diversity_and_quarantine_pipeline() -> None:
    engine = CounterexampleSemanticEquivalence()
    corpus = [
        smt_model_witness(),
        syntactic_variant_of_smt(),
        different_causal_smt(),
        trace_witness(),
        trace_witness(
            steps=[{"label": "init"}, {"label": "other"}, {"label": "bad"}],
            counterexample_id="cex:trace-other",
            content_id="sha256:" + "9" * 64,
        ),
    ]

    report = engine.deduplicate(corpus)
    # Two SMT semantic classes (variant collapses) + two trace paths = 4.
    assert report.unique_count == 4
    assert report.duplicate_count == 1
    assert report.used_content_hash_alone is False

    diverse = engine.select_diverse(corpus)
    assert diverse.selected_count == 4
    assert set(diverse.selected_indices) == set(report.representatives)

    comparison = engine.differential_compare(
        [
            {
                "provider_id": "solver.z3",
                "outcome": "sat",
                "receipt_id": "receipt:z3-corpus",
                "authority": "satisfiability",
            },
            {
                "provider_id": "solver.cvc5",
                "outcome": "no_violation",
                "receipt_id": "receipt:cvc5-corpus",
                "authority": "satisfiability",
            },
        ],
        witness=corpus[0],
    )
    assert comparison.status == DifferentialStatus.DISAGREEMENT
    quarantine = engine.quarantine_disagreement(comparison)
    assert quarantine.discarded_evidence is False
    assert len(quarantine.retained_receipt_ids) == 2
    assert quarantine.authority_raised is False
    assert quarantine.consensus_claimed is False

    # Serializations are content-addressed and stable.
    assert report.to_dict()["report_id"] == report.report_id
    assert diverse.to_dict()["selection_id"] == diverse.selection_id
    assert comparison.to_dict()["comparison_id"] == comparison.comparison_id
    assert quarantine.to_dict()["quarantine_id"] == quarantine.quarantine_id


def test_pair_result_and_cluster_are_content_addressed() -> None:
    pair = are_semantically_equivalent(smt_model_witness(), syntactic_variant_of_smt())
    again = are_semantically_equivalent(smt_model_witness(), syntactic_variant_of_smt())
    assert pair.pair_id == again.pair_id
    assert pair.pair_id.startswith("eq-pair:")

    report = deduplicate_witnesses([smt_model_witness(), syntactic_variant_of_smt()])
    assert report.clusters[0].cluster_id.startswith("eq-cluster:")


def test_malformed_inputs_fail_closed() -> None:
    with pytest.raises(EquivalenceError):
        project_witness("not-a-mapping")  # type: ignore[arg-type]
    with pytest.raises(EquivalenceError):
        deduplicate_witnesses("nope")  # type: ignore[arg-type]
    with pytest.raises(EquivalenceError):
        select_diverse_witnesses([smt_model_witness()], max_select=-1)
    with pytest.raises(EquivalenceError):
        differential_compare_providers([])
