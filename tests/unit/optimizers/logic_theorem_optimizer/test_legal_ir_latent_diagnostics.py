"""Latent diagnostics, calibration instrumentation, and collapse triggers."""

from __future__ import annotations

import math

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_evaluation_artifacts import (
    LEGAL_IR_ARTIFACT_NODE_ORDER,
    LEGAL_IR_LATENT_DIAGNOSTIC_KEY,
    TRIGGER_DUPLICATE_MEMORIZATION,
    TRIGGER_FALSE_NEIGHBORHOODS,
    TRIGGER_HIDDEN_TEST_SPLIT,
    TRIGGER_HIGH_ANISOTROPY,
    TRIGGER_HIGH_ECE,
    TRIGGER_LOW_EFFECTIVE_RANK,
    TRIGGER_UNKNOWN_DENOMINATOR,
    CollapseTriggerConfig,
    LegalIRArtifactGraphBuildPlan,
    LegalIRArtifactGraphStore,
    attach_latent_diagnostics,
    legal_ir_evaluation_artifact_from_compilation,
    materialize_latent_diagnostic_report,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_evaluation_cache import (
    LegalIREvaluationCacheKey,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_family_evaluator import (
    evaluate_latent_clustering_strata,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_metric_lineage import (
    LATENT_DIAGNOSTIC_METRIC_SCHEMA,
    LEARNED_IR_METRIC_PATH,
    build_latent_diagnostic_metric_lineage,
    material_lineage_delta,
    metric_lineage_from_block,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
    GOLDEN_ANISOTROPY_METRIC_VECTOR,
    GOLDEN_CALIBRATION_METRIC_VECTOR,
    GOLDEN_COLLAPSE_METRIC_VECTOR,
    GOLDEN_ORTHOGONAL_METRIC_VECTOR,
    LatentRepresentationRecord,
    evaluate_latent_diagnostics,
    evaluate_legal_ir_semantic_equivalence,
    synthetic_anisotropy_fixture,
    synthetic_calibration_fixture,
    synthetic_collapse_fixture,
    synthetic_false_neighborhood_fixture,
    synthetic_memorization_fixture,
    synthetic_orthogonal_fixture,
    synthetic_unknown_denominator_fixture,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_uncertainty import (
    evaluate_legal_ir_calibration,
)


def _approx_vector(actual: dict[str, float], expected: dict[str, float]) -> None:
    for name, value in expected.items():
        assert name in actual, name
        assert actual[name] == pytest.approx(value, abs=1e-9), name


def test_collapse_fixture_matches_golden_singular_spectrum() -> None:
    report = evaluate_latent_diagnostics(synthetic_collapse_fixture())
    vector = report.metric_vector()

    _approx_vector(vector, dict(GOLDEN_COLLAPSE_METRIC_VECTOR))
    assert report.spectrum.unknown_denominators == ()
    assert report.spectrum.effective_rank == pytest.approx(1.0)
    assert report.spectrum.spectral_anisotropy == pytest.approx(1.0)


def test_orthogonal_fixture_matches_golden_rank_and_anisotropy() -> None:
    report = evaluate_latent_diagnostics(synthetic_orthogonal_fixture())
    vector = report.metric_vector()

    _approx_vector(vector, dict(GOLDEN_ORTHOGONAL_METRIC_VECTOR))
    assert report.false_neighborhoods.latent_similarity_is_not_equivalence is True


def test_anisotropy_fixture_matches_hand_computed_spectrum() -> None:
    report = evaluate_latent_diagnostics(synthetic_anisotropy_fixture())
    vector = report.metric_vector()

    _approx_vector(vector, dict(GOLDEN_ANISOTROPY_METRIC_VECTOR))
    assert vector["spectral_anisotropy"] > 0.99


def test_identical_family_copies_are_not_false_neighborhoods() -> None:
    records = []
    for family, vector in (
        ("deontic", (1.0, 0.0, 0.0)),
        ("frame_logic", (0.0, 1.0, 0.0)),
        ("tdfol", (0.0, 0.0, 1.0)),
    ):
        for copy in range(2):
            records.append(
                LatentRepresentationRecord(
                    sample_id=f"{family}-{copy}",
                    vector=vector,
                    family=family,
                    split="development",
                    semantic_class=family,
                )
            )
    report = evaluate_latent_diagnostics(records, neighbor_k=1)
    assert report.false_neighborhoods.false_neighborhood_rate == pytest.approx(0.0)


def test_false_neighborhoods_do_not_count_as_equivalence() -> None:
    report = evaluate_latent_diagnostics(
        synthetic_false_neighborhood_fixture(),
        neighbor_k=1,
    )

    assert report.false_neighborhoods.pair_count == 4
    assert report.false_neighborhoods.false_neighborhood_count == 4
    assert report.false_neighborhoods.false_neighborhood_rate == pytest.approx(1.0)
    assert report.to_dict()["latent_similarity_is_not_equivalence"] is True


def test_unknown_denominators_are_explicit_for_degenerate_batch() -> None:
    report = evaluate_latent_diagnostics(synthetic_unknown_denominator_fixture())

    assert report.spectrum.effective_rank is None
    assert report.spectrum.latent_use_rate == pytest.approx(0.0)
    assert "effective_rank" in report.spectrum.unknown_denominators
    assert "spectrum:centered_matrix_is_zero" in report.spectrum.unknown_denominators
    assert report.false_neighborhoods.false_neighborhood_rate is None
    assert "false_neighborhoods:sample_count_below_two" in (
        report.false_neighborhoods.unknown_denominators
    )


def test_family_domain_length_jurisdiction_and_ood_strata() -> None:
    records = list(synthetic_orthogonal_fixture()) + [
        LatentRepresentationRecord(
            sample_id="ood-1",
            vector=(0.2, 0.3, 0.9),
            family="cec",
            domain="foreign",
            jurisdiction="eu",
            length_bin="long",
            length=200.0,
            duplicate_group="ood",
            split="calibration",
            ood=True,
            success=False,
            confidence=0.4,
        )
    ]
    strata = evaluate_latent_clustering_strata(
        records,
        required_families=("deontic", "frame_logic", "tdfol", "cec"),
    )

    assert strata.family_balanced is True
    assert strata.missing_families == ()
    assert strata.axes["domain"].group_counts["deontic"] == 2
    assert strata.axes["domain"].group_counts["foreign"] == 1
    assert strata.axes["jurisdiction"].group_counts["us-federal"] == 6
    assert strata.axes["length"].group_counts["medium"] == 6
    assert strata.ood.group_counts["ood"] == 1
    assert strata.to_dict()["latent_similarity_is_not_equivalence"] is True


def test_duplicate_clustering_separates_memorized_groups() -> None:
    strata = evaluate_latent_clustering_strata(synthetic_memorization_fixture())

    assert strata.axes["duplicate"].intra_cosine == pytest.approx(1.0)
    assert strata.axes["duplicate"].inter_cosine == pytest.approx(0.0)
    assert strata.axes["family"].intra_cosine == pytest.approx(1.0)


def test_calibration_golden_vector_ece_brier_and_success_conditioned() -> None:
    report = evaluate_legal_ir_calibration(synthetic_calibration_fixture(), bin_count=10)
    vector = report.metric_vector()

    _approx_vector(vector, dict(GOLDEN_CALIBRATION_METRIC_VECTOR))
    assert report.labeled_count == 10
    assert report.confidence_is_not_authority is True
    assert report.to_dict()["authority"] == "diagnostic_only"
    occupied = [item for item in report.reliability_bins if item.count]
    assert [item.index for item in occupied] == [1, 9]
    assert occupied[0].accuracy == pytest.approx(0.0)
    assert occupied[1].accuracy == pytest.approx(1.0)


def test_calibration_keeps_unknown_success_labels_out_of_the_denominator() -> None:
    records = list(synthetic_calibration_fixture()) + [
        LatentRepresentationRecord(
            sample_id="unlabeled",
            vector=(0.5, 0.5),
            family="deontic",
            split="calibration",
            success=None,
            confidence=0.95,
        )
    ]
    report = evaluate_legal_ir_calibration(records, bin_count=10)

    assert report.labeled_count == 10
    assert report.unlabeled_count == 1
    assert "calibration:unknown_success_labels" in report.unknown_denominators
    assert report.brier_score == pytest.approx(0.01)


def test_lineage_is_deterministic_and_moves_with_representation_content() -> None:
    first = build_latent_diagnostic_metric_lineage(
        synthetic_collapse_fixture(),
        checkpoint_identity="pgir-030-fixture-a",
    )
    second = build_latent_diagnostic_metric_lineage(
        synthetic_collapse_fixture(),
        checkpoint_identity="pgir-030-fixture-a",
    )
    shifted = build_latent_diagnostic_metric_lineage(
        synthetic_orthogonal_fixture(),
        checkpoint_identity="pgir-030-fixture-b",
    )

    assert first.digest == second.digest
    assert first.path == LEARNED_IR_METRIC_PATH
    assert first.metric_schema == LATENT_DIAGNOSTIC_METRIC_SCHEMA
    assert first.digest != shifted.digest
    assert material_lineage_delta(first, shifted)


def test_materialized_report_triggers_collapse_anisotropy_and_memorization() -> None:
    collapse = materialize_latent_diagnostic_report(synthetic_collapse_fixture())
    anisotropy = materialize_latent_diagnostic_report(synthetic_anisotropy_fixture())
    memorized = materialize_latent_diagnostic_report(synthetic_memorization_fixture())
    mixed = materialize_latent_diagnostic_report(
        synthetic_false_neighborhood_fixture(),
        config=CollapseTriggerConfig(max_false_neighborhood_rate=0.2, neighbor_k=1),
    )

    assert collapse.collapsed is True
    assert any(item.trigger_id == TRIGGER_LOW_EFFECTIVE_RANK for item in collapse.collapse_triggers)
    assert any(item.trigger_id == TRIGGER_HIGH_ANISOTROPY for item in anisotropy.collapse_triggers)
    assert any(
        item.trigger_id == TRIGGER_DUPLICATE_MEMORIZATION for item in memorized.collapse_triggers
    )
    assert any(item.trigger_id == TRIGGER_FALSE_NEIGHBORHOODS for item in mixed.collapse_triggers)
    assert collapse.digest == materialize_latent_diagnostic_report(synthetic_collapse_fixture()).digest
    assert collapse.to_dict()["confidence_is_not_authority"] is True
    assert collapse.to_dict()["latent_similarity_is_not_equivalence"] is True
    observed = metric_lineage_from_block({"metric_lineage": collapse.metric_lineage})
    assert observed.metric_schema == LATENT_DIAGNOSTIC_METRIC_SCHEMA


def test_hidden_test_split_is_rejected_and_does_not_tune_calibration() -> None:
    leaked = [
        LatentRepresentationRecord(
            sample_id="hidden-1",
            vector=(1.0, 0.0),
            family="deontic",
            split="hidden_test",
            success=True,
            confidence=0.99,
        )
    ]
    report = materialize_latent_diagnostic_report(leaked)

    assert report.prohibited_split_count == 1
    assert any(item.trigger_id == TRIGGER_HIDDEN_TEST_SPLIT for item in report.collapse_triggers)
    assert report.calibration["labeled_count"] == 0


def test_unknown_denominator_trigger_is_explicit_when_ece_cannot_be_formed() -> None:
    report = materialize_latent_diagnostic_report(synthetic_unknown_denominator_fixture())

    assert any(item.trigger_id == TRIGGER_UNKNOWN_DENOMINATOR for item in report.collapse_triggers)
    assert any(item.unknown_denominator for item in report.collapse_triggers)
    assert "effective_rank" in report.unknown_denominators


def test_calibration_fixture_report_emits_ece_trigger_without_treating_confidence_as_authority() -> (
    None
):
    report = materialize_latent_diagnostic_report(
        synthetic_calibration_fixture(),
        required_families=("deontic", "tdfol"),
    )

    assert any(item.trigger_id == TRIGGER_HIGH_ECE for item in report.collapse_triggers)
    assert report.calibration["confidence_is_not_authority"] is True
    _approx_vector(
        {
            "brier_score": report.metric_vector()["brier_score"],
            "expected_calibration_error": report.metric_vector()["expected_calibration_error"],
            "success_conditioned_confidence": report.metric_vector()[
                "success_conditioned_confidence"
            ],
            "failure_conditioned_confidence": report.metric_vector()[
                "failure_conditioned_confidence"
            ],
        },
        dict(GOLDEN_CALIBRATION_METRIC_VECTOR),
    )


def test_diagnostic_report_attaches_to_artifact_without_changing_required_dag() -> None:
    key = LegalIREvaluationCacheKey(
        sample_hash="sample-sha",
        compiler_commit="compiler-sha",
        state_hash="state-a",
        metric_schema="metric-schema-a",
        config_hash="config-sha",
    )
    artifact = legal_ir_evaluation_artifact_from_compilation(
        key,
        sample={"sample_id": "sample-1", "text": "The agency shall provide notice.", "embedding_vector": [0.25, 0.75]},
        compilation_result=type(
            "Compiled",
            (),
            {
                "decoded_modal_text": "O(provide_notice)",
                "frame_candidates": ("frame",),
                "kg_triples": (),
                "losses": {"cross_entropy_loss": 0.2},
                "metadata": {"legal_ir_view_families": ["deontic"]},
                "modal_ir": type("Modal", (), {"formulas": ("formula",)})(),
            },
        )(),
    )
    report = materialize_latent_diagnostic_report(synthetic_orthogonal_fixture())
    attached = attach_latent_diagnostics(artifact, report)
    store = LegalIRArtifactGraphStore()
    bundle = store.get_or_materialize(
        key,
        LegalIRArtifactGraphBuildPlan(
            sample={"sample_id": "sample-1", "text": "The agency shall provide notice."},
            compile=lambda: type(
                "Compiled",
                (),
                {
                    "decoded_modal_text": "O(provide_notice)",
                    "frame_candidates": (),
                    "kg_triples": (),
                    "losses": {},
                    "metadata": {},
                    "modal_ir": type("Modal", (), {"formulas": ()})(),
                },
            )(),
        ),
    )

    assert LEGAL_IR_LATENT_DIAGNOSTIC_KEY in attached.compiler_artifact
    assert attached.metadata["latent_diagnostic_digest"] == report.digest
    assert attached.metrics["metric_lineage"]["metric_schema"] == LATENT_DIAGNOSTIC_METRIC_SCHEMA
    assert tuple(bundle.nodes) == LEGAL_IR_ARTIFACT_NODE_ORDER


def test_semantic_equivalence_gate_is_unchanged_by_latent_instrumentation() -> None:
    left = {
        "rules": [
            {
                "modality": "obligation",
                "subject": "Agency",
                "action": "provide notice",
                "proof_obligation_ids": ["po-notice"],
            }
        ]
    }
    result = evaluate_legal_ir_semantic_equivalence(left, left, family="deontic")
    assert result.complete is True
    assert result.scores["obligation_equivalence"] == pytest.approx(1.0)
