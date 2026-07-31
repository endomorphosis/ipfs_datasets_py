"""Contract tests for DualRoundTripMetrics@1 (CE/cosine + structural bridge)."""

from __future__ import annotations

import math

import pytest

from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRule,
    CanonicalRuleIR,
    ContractError,
)
from benchmarks.semantic_roundtrip.dual_metrics import (
    CE_COSINE_MAY_SUBSTITUTE_FOR_PROMOTION,
    DUAL_ROUND_TRIP_METRICS_INTERFACE,
    DUAL_ROUND_TRIP_METRICS_SCHEMA,
    METRIC_MODE_DUAL,
    METRIC_MODE_STRUCTURAL_ONLY,
    PROMOTION_POLICY_NOTE,
    PROMOTION_PRIMARY_METRIC,
    RESIDUAL_ROW_DUAL_METRICS_FIELD,
    CallableEmbeddingBackend,
    DualMetricMode,
    DualRoundTripMetrics,
    EmbeddingPairMetrics,
    UnavailableEmbeddingBackend,
    attach_dual_metrics_to_residual_row,
    compute_dual_metrics,
    cosine_similarity,
    cross_entropy_from_distributions,
    dual_metrics_from_structural,
)
from benchmarks.semantic_roundtrip.metrics import (
    RoundTripLosses,
    round_trip_losses,
)


def _rule(
    *,
    modality: str = "O",
    actor: str = "agency",
    action: str = "file",
    object_atom: str = "notice",
    conditions: tuple[str, ...] = (),
    exceptions: tuple[str, ...] = ("emergency",),
    temporal: tuple[str, ...] = ("within_10_days",),
) -> CanonicalRule:
    return CanonicalRule(
        modality=modality,
        actor=actor,
        action=action,
        object=object_atom,
        conditions=conditions,
        exceptions=exceptions,
        temporal=temporal,
    )


def _gold() -> CanonicalRuleIR:
    return CanonicalRuleIR((_rule(),))


def _identical_l1_l2() -> tuple[CanonicalRuleIR, str, CanonicalRuleIR]:
    ir = _gold()
    return ir, "Agency shall file notice within 10 days except emergency.", ir


def _constant_backend(
    pair: EmbeddingPairMetrics,
    *,
    identity: str = "test-embed@1",
    available: bool = True,
) -> CallableEmbeddingBackend:
    return CallableEmbeddingBackend(
        identity=identity,
        scorer=lambda _ref, _cand: pair,
        is_available=available,
    )


def test_interface_and_promotion_policy_are_frozen() -> None:
    assert DUAL_ROUND_TRIP_METRICS_INTERFACE == "DualRoundTripMetrics@1"
    assert DUAL_ROUND_TRIP_METRICS_SCHEMA.startswith("ipfs-datasets.")
    assert PROMOTION_PRIMARY_METRIC == "structural_end_to_end"
    assert CE_COSINE_MAY_SUBSTITUTE_FOR_PROMOTION is False
    assert DualMetricMode.STRUCTURAL_ONLY.value == METRIC_MODE_STRUCTURAL_ONLY
    assert DualMetricMode.DUAL.value == METRIC_MODE_DUAL
    assert "structural" in PROMOTION_POLICY_NOTE.lower()
    assert "never" in PROMOTION_POLICY_NOTE.lower()


def test_structural_always_reported_without_backend() -> None:
    gold = _gold()
    l1, reconstruction, l2 = _identical_l1_l2()
    expected = round_trip_losses(gold, l1, reconstruction, l2)

    metrics = compute_dual_metrics(gold, l1, reconstruction, l2)

    assert metrics.metric_mode is DualMetricMode.STRUCTURAL_ONLY
    assert metrics.is_structural_only is True
    assert metrics.is_dual is False
    assert metrics.embedding_backend_present is False
    assert metrics.embedding_backend_id is None
    assert metrics.structural_forward == expected.forward
    assert metrics.structural_cycle == expected.cycle
    assert metrics.structural_end_to_end == expected.end_to_end
    assert metrics.structural.forward == expected.forward
    assert metrics.cross_entropy_forward is None
    assert metrics.cross_entropy_cycle is None
    assert metrics.cross_entropy_end_to_end is None
    assert metrics.cosine_forward is None
    assert metrics.cosine_cycle is None
    assert metrics.cosine_end_to_end is None
    assert metrics.promotion_primary_metric == PROMOTION_PRIMARY_METRIC
    assert metrics.ce_cosine_may_substitute_for_promotion is False
    assert metrics.silent_metric_substitution is False


def test_missing_artifacts_fail_closed_structurally_without_inventing_ce() -> None:
    gold = _gold()
    metrics = compute_dual_metrics(gold, None, None, None)

    assert metrics.structural_forward == 1.0
    assert metrics.structural_cycle == 1.0
    assert metrics.structural_end_to_end == 1.0
    assert metrics.metric_mode is DualMetricMode.STRUCTURAL_ONLY
    assert metrics.cross_entropy_forward is None
    assert metrics.cosine_end_to_end is None


def test_unavailable_backend_fails_closed_to_structural_only() -> None:
    gold = _gold()
    l1, reconstruction, l2 = _identical_l1_l2()
    backend = UnavailableEmbeddingBackend(identity="offline-ae")

    metrics = compute_dual_metrics(
        gold, l1, reconstruction, l2, embedding_backend=backend
    )

    assert metrics.embedding_backend_present is True
    assert metrics.embedding_backend_id == "offline-ae"
    assert metrics.metric_mode is DualMetricMode.STRUCTURAL_ONLY
    assert metrics.cross_entropy_forward is None
    assert metrics.cosine_forward is None
    # Structural scores still present and correct.
    assert 0.0 <= metrics.structural_end_to_end <= 1.0


def test_available_flag_false_does_not_invent_scores() -> None:
    gold = _gold()
    l1, reconstruction, l2 = _identical_l1_l2()
    backend = _constant_backend(
        EmbeddingPairMetrics(0.1, 0.9), available=False
    )

    metrics = compute_dual_metrics(
        gold, l1, reconstruction, l2, embedding_backend=backend
    )

    assert metrics.metric_mode is DualMetricMode.STRUCTURAL_ONLY
    assert metrics.cross_entropy_forward is None
    assert metrics.cosine_forward is None


def test_backend_present_attaches_ce_and_cosine_on_every_leg() -> None:
    gold = _gold()
    l1, reconstruction, l2 = _identical_l1_l2()
    pair = EmbeddingPairMetrics(cross_entropy=0.25, cosine_similarity=0.875)
    backend = _constant_backend(pair, identity="fixture-embed@1")
    structural = round_trip_losses(gold, l1, reconstruction, l2)

    metrics = compute_dual_metrics(
        gold, l1, reconstruction, l2, embedding_backend=backend
    )
    payload = metrics.to_dict()

    assert metrics.metric_mode is DualMetricMode.DUAL
    assert metrics.embedding_backend_present is True
    assert metrics.embedding_backend_id == "fixture-embed@1"
    assert metrics.structural_forward == structural.forward
    assert metrics.structural_cycle == structural.cycle
    assert metrics.structural_end_to_end == structural.end_to_end
    assert metrics.cross_entropy_forward == 0.25
    assert metrics.cross_entropy_cycle == 0.25
    assert metrics.cross_entropy_end_to_end == 0.25
    assert metrics.cosine_forward == 0.875
    assert metrics.cosine_cycle == 0.875
    assert metrics.cosine_end_to_end == 0.875
    assert payload["interface"] == DUAL_ROUND_TRIP_METRICS_INTERFACE
    assert payload["schema"] == DUAL_ROUND_TRIP_METRICS_SCHEMA
    assert payload["metric_mode"] == METRIC_MODE_DUAL
    assert payload["promotion_primary_metric"] == PROMOTION_PRIMARY_METRIC
    assert payload["ce_cosine_may_substitute_for_promotion"] is False
    assert payload["silent_metric_substitution"] is False


def test_partial_backend_scores_fail_closed_without_partial_ce() -> None:
    gold = _gold()
    l1, reconstruction, l2 = _identical_l1_l2()
    calls: list[tuple[str, str]] = []

    def scorer(
        reference: CanonicalRuleIR, candidate: CanonicalRuleIR
    ) -> EmbeddingPairMetrics | None:
        # Succeed only on the first call; later legs fail closed.
        calls.append((reference.rules[0].actor, candidate.rules[0].actor))
        if len(calls) == 1:
            return EmbeddingPairMetrics(0.1, 0.9)
        return None

    backend = CallableEmbeddingBackend(identity="partial@1", scorer=scorer)
    metrics = compute_dual_metrics(
        gold, l1, reconstruction, l2, embedding_backend=backend
    )

    assert metrics.metric_mode is DualMetricMode.STRUCTURAL_ONLY
    assert metrics.embedding_backend_present is True
    assert metrics.cross_entropy_forward is None
    assert metrics.cosine_cycle is None
    assert len(calls) >= 2


def test_backend_exception_fails_closed() -> None:
    gold = _gold()
    l1, reconstruction, l2 = _identical_l1_l2()

    def boom(
        _reference: CanonicalRuleIR, _candidate: CanonicalRuleIR
    ) -> EmbeddingPairMetrics:
        raise RuntimeError("embedding service down")

    backend = CallableEmbeddingBackend(identity="explode@1", scorer=boom)
    metrics = compute_dual_metrics(
        gold, l1, reconstruction, l2, embedding_backend=backend
    )

    assert metrics.metric_mode is DualMetricMode.STRUCTURAL_ONLY
    assert metrics.cross_entropy_end_to_end is None
    assert metrics.cosine_end_to_end is None


def test_structural_mismatch_losses_match_protocol_helpers() -> None:
    gold = CanonicalRuleIR((_rule(modality="O"),))
    l1 = CanonicalRuleIR((_rule(modality="F"),))
    reconstruction = "Prohibited text."
    l2 = CanonicalRuleIR((_rule(modality="P"),))
    expected = round_trip_losses(gold, l1, reconstruction, l2)

    metrics = compute_dual_metrics(gold, l1, reconstruction, l2)

    assert metrics.structural_forward == expected.forward
    assert metrics.structural_cycle == expected.cycle
    assert metrics.structural_end_to_end == expected.end_to_end
    assert metrics.structural_forward > 0.0


def test_attach_dual_metrics_to_residual_row_is_additive() -> None:
    gold = _gold()
    l1, reconstruction, l2 = _identical_l1_l2()
    pair = EmbeddingPairMetrics(0.05, 0.99)
    metrics = compute_dual_metrics(
        gold,
        l1,
        reconstruction,
        l2,
        embedding_backend=_constant_backend(pair),
    )
    row = {
        "case_id": "exception_with_window",
        "field_path": "rules[0].exceptions",
        "structural_end_to_end": metrics.structural_end_to_end,
    }

    attached = attach_dual_metrics_to_residual_row(row, metrics)

    assert RESIDUAL_ROW_DUAL_METRICS_FIELD in attached
    assert attached["case_id"] == "exception_with_window"
    assert attached["structural_end_to_end"] == metrics.structural_end_to_end
    dual = attached[RESIDUAL_ROW_DUAL_METRICS_FIELD]
    assert isinstance(dual, dict)
    assert dual["metric_mode"] == METRIC_MODE_DUAL
    assert dual["cross_entropy_forward"] == 0.05
    assert dual["cosine_forward"] == 0.99
    # Input row not mutated.
    assert RESIDUAL_ROW_DUAL_METRICS_FIELD not in row


def test_attach_structural_only_row_keeps_null_ce_cosine() -> None:
    gold = _gold()
    l1, reconstruction, l2 = _identical_l1_l2()
    metrics = compute_dual_metrics(gold, l1, reconstruction, l2)
    attached = attach_dual_metrics_to_residual_row(
        {"case_id": "corp_policy_1"}, metrics
    )
    dual = attached[RESIDUAL_ROW_DUAL_METRICS_FIELD]
    assert dual["metric_mode"] == METRIC_MODE_STRUCTURAL_ONLY
    assert dual["cross_entropy_forward"] is None
    assert dual["cosine_end_to_end"] is None


def test_dual_metrics_from_structural_with_pairs() -> None:
    losses = RoundTripLosses(0.1, 0.2, 0.3)
    pair = EmbeddingPairMetrics(0.4, 0.5)
    backend = UnavailableEmbeddingBackend(identity="precomputed@1")
    # available() is False → structural only even with pairs.
    metrics = dual_metrics_from_structural(
        losses,
        embedding_backend=backend,
        forward_pair=pair,
        cycle_pair=pair,
        end_to_end_pair=pair,
    )
    assert metrics.metric_mode is DualMetricMode.STRUCTURAL_ONLY

    available = _constant_backend(pair, identity="precomputed@1")
    dual = dual_metrics_from_structural(
        {"forward": 0.1, "cycle": 0.2, "end_to_end": 0.3},
        embedding_backend=available,
        forward_pair=pair,
        cycle_pair=pair,
        end_to_end_pair=pair,
    )
    assert dual.metric_mode is DualMetricMode.DUAL
    assert dual.structural_end_to_end == 0.3
    assert dual.cross_entropy_cycle == 0.4
    assert dual.cosine_end_to_end == 0.5


def test_dual_metrics_from_structural_rejects_pairs_without_backend() -> None:
    losses = RoundTripLosses(0.0, 0.0, 0.0)
    pair = EmbeddingPairMetrics(0.1, 0.9)
    with pytest.raises(ContractError, match="embedding_backend"):
        dual_metrics_from_structural(
            losses,
            forward_pair=pair,
            cycle_pair=pair,
            end_to_end_pair=pair,
        )


def test_record_rejects_invented_ce_in_structural_only_mode() -> None:
    with pytest.raises(ContractError, match="forbids CE/cosine"):
        DualRoundTripMetrics(
            structural_forward=0.0,
            structural_cycle=0.0,
            structural_end_to_end=0.0,
            metric_mode=DualMetricMode.STRUCTURAL_ONLY,
            embedding_backend_present=False,
            embedding_backend_id=None,
            cross_entropy_forward=0.0,  # invented
            cross_entropy_cycle=None,
            cross_entropy_end_to_end=None,
            cosine_forward=None,
            cosine_cycle=None,
            cosine_end_to_end=None,
        )


def test_record_rejects_promotion_primary_rewrite() -> None:
    with pytest.raises(ContractError, match="promotion_primary_metric"):
        DualRoundTripMetrics(
            structural_forward=0.0,
            structural_cycle=0.0,
            structural_end_to_end=0.0,
            metric_mode=DualMetricMode.STRUCTURAL_ONLY,
            embedding_backend_present=False,
            embedding_backend_id=None,
            cross_entropy_forward=None,
            cross_entropy_cycle=None,
            cross_entropy_end_to_end=None,
            cosine_forward=None,
            cosine_cycle=None,
            cosine_end_to_end=None,
            promotion_primary_metric="cross_entropy_end_to_end",
        )


def test_record_rejects_ce_cosine_promotion_authority() -> None:
    with pytest.raises(
        ContractError, match="ce_cosine_may_substitute_for_promotion"
    ):
        DualRoundTripMetrics(
            structural_forward=0.0,
            structural_cycle=0.0,
            structural_end_to_end=0.0,
            metric_mode=DualMetricMode.STRUCTURAL_ONLY,
            embedding_backend_present=False,
            embedding_backend_id=None,
            cross_entropy_forward=None,
            cross_entropy_cycle=None,
            cross_entropy_end_to_end=None,
            cosine_forward=None,
            cosine_cycle=None,
            cosine_end_to_end=None,
            ce_cosine_may_substitute_for_promotion=True,
        )


def test_record_rejects_silent_substitution_flag() -> None:
    with pytest.raises(ContractError, match="silent_metric_substitution"):
        DualRoundTripMetrics(
            structural_forward=0.0,
            structural_cycle=0.0,
            structural_end_to_end=0.0,
            metric_mode=DualMetricMode.STRUCTURAL_ONLY,
            embedding_backend_present=False,
            embedding_backend_id=None,
            cross_entropy_forward=None,
            cross_entropy_cycle=None,
            cross_entropy_end_to_end=None,
            cosine_forward=None,
            cosine_cycle=None,
            cosine_end_to_end=None,
            silent_metric_substitution=True,
        )


def test_dual_mode_requires_complete_optional_scores() -> None:
    with pytest.raises(ContractError, match="dual mode requires CE"):
        DualRoundTripMetrics(
            structural_forward=0.0,
            structural_cycle=0.0,
            structural_end_to_end=0.0,
            metric_mode=DualMetricMode.DUAL,
            embedding_backend_present=True,
            embedding_backend_id="x",
            cross_entropy_forward=0.1,
            cross_entropy_cycle=None,
            cross_entropy_end_to_end=0.1,
            cosine_forward=0.9,
            cosine_cycle=0.9,
            cosine_end_to_end=0.9,
        )


def test_embedding_pair_metrics_bounds() -> None:
    with pytest.raises(ContractError, match="cross_entropy"):
        EmbeddingPairMetrics(cross_entropy=-0.1, cosine_similarity=0.0)
    with pytest.raises(ContractError, match="cosine_similarity"):
        EmbeddingPairMetrics(cross_entropy=0.0, cosine_similarity=1.5)
    ok = EmbeddingPairMetrics(0.0, -1.0)
    assert ok.to_dict() == {"cross_entropy": 0.0, "cosine_similarity": -1.0}


def test_cosine_similarity_and_cross_entropy_helpers() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert cosine_similarity([], []) == 0.0
    with pytest.raises(ContractError, match="equal length"):
        cosine_similarity([1.0], [1.0, 2.0])

    ce = cross_entropy_from_distributions(
        {"a": 0.8, "b": 0.2},
        {"a": 1.0, "b": 0.0},
    )
    assert ce == pytest.approx(-math.log(0.8))
    assert cross_entropy_from_distributions({}, {}) == 0.0


def test_callable_backend_identity_and_unavailable() -> None:
    with pytest.raises(ContractError, match="identity"):
        CallableEmbeddingBackend(identity="  ", scorer=lambda a, b: None)
    backend = CallableEmbeddingBackend(
        identity="  named@1  ",
        scorer=lambda _a, _b: EmbeddingPairMetrics(0.0, 1.0),
        is_available=False,
    )
    assert backend.identity == "named@1"
    assert backend.available() is False
    assert backend.pair_metrics(_gold(), _gold()) is None


def test_gold_ir_required() -> None:
    with pytest.raises(ContractError, match="gold_ir"):
        compute_dual_metrics(None, None, None, None)  # type: ignore[arg-type]


def test_failed_flag_forces_structural_one_without_ce() -> None:
    gold = _gold()
    l1, reconstruction, l2 = _identical_l1_l2()
    pair = EmbeddingPairMetrics(0.0, 1.0)
    # failed=True forces structural 1.0; backend may still score dual CE if
    # IRs are present — dual is allowed when backend succeeds. Structural
    # remains fail-closed at 1.0.
    metrics = compute_dual_metrics(
        gold,
        l1,
        reconstruction,
        l2,
        failed=True,
        embedding_backend=_constant_backend(pair),
    )
    assert metrics.structural_forward == 1.0
    assert metrics.structural_cycle == 1.0
    assert metrics.structural_end_to_end == 1.0
    assert metrics.metric_mode is DualMetricMode.DUAL
    assert metrics.cross_entropy_forward == 0.0
