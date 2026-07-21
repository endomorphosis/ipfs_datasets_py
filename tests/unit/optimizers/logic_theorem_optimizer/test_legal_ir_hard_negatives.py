"""Tests for verified LegalIR hard-negative curricula."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import (
    SEMANTICS_CHANGING,
    TARGET_DETERMINISTIC_IR,
    TrustedNegativeCandidate,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hard_negatives import (
    DECOMPILER_HALLUCINATION,
    HARD_NEGATIVE_FAMILIES,
    LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION,
    LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION,
    SOURCE_COPY_SPAN,
    VERIFIED_COUNTEREXAMPLE,
    LegalIRHardNegativeConfig,
    build_legal_ir_hard_negative_curriculum,
    hard_negative_training_effect_gate,
    prove_hard_negatives_reduce_false_positive_semantic_equivalence,
)


LEGAL_TEXT = (
    "The agency shall provide notice unless emergency conditions exist "
    "within 30 days."
)


def _reference_ir() -> dict[str, object]:
    return {
        "citation": "5 U.S.C. 552",
        "rules": [
            {
                "actor": "agency",
                "action": "provide",
                "exception": "emergency conditions exist",
                "modality": "obligation",
                "object": "notice",
            }
        ],
        "temporal": "within 30 days",
    }


def _source_record() -> dict[str, object]:
    return {
        "citation": "5 U.S.C. 552",
        "reference_ir": _reference_ir(),
        "sample_id": "lir-hard-negative-source",
        "semantic_family": "deontic",
        "text": LEGAL_TEXT,
        "trusted": True,
        "verification": {
            "verified": True,
            "verified_by": ["hammer_positive_obligation", "deterministic_compiler"],
        },
    }


def _trusted_counterexample() -> TrustedNegativeCandidate:
    return TrustedNegativeCandidate(
        candidate_id="lir-hard-negative-counterexample",
        source_mutation_id="mutation-counterexample",
        target=TARGET_DETERMINISTIC_IR,
        relation=SEMANTICS_CHANGING,
        label="semantic_non_equivalence",
        minimal_counterexample={
            "rules": [
                {
                    "actor": "agency",
                    "action": "provide",
                    "modality": "permission",
                    "object": "notice",
                }
            ]
        },
        verification={
            "semantic_similarity": 0.42,
            "verified": True,
            "verified_by": ["metamorphic_metric_oracle", "hammer_obligation_delta"],
        },
        source_text_sha256="sha256-source",
        mutated_payload_sha256="sha256-mutated",
    )


def test_curriculum_builds_all_required_verified_hard_negative_families() -> None:
    curriculum = build_legal_ir_hard_negative_curriculum(
        verified_counterexamples=[_trusted_counterexample()],
        source_records=[_source_record()],
    )

    assert curriculum.schema_version == LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION
    assert curriculum.ready_for_training is True
    assert set(curriculum.covered_negative_families) == set(HARD_NEGATIVE_FAMILIES)
    assert curriculum.missing_negative_families == ()
    assert curriculum.rejected_count == 0
    assert curriculum.by_family(VERIFIED_COUNTEREXAMPLE)
    assert curriculum.by_family(SOURCE_COPY_SPAN)
    assert curriculum.by_family(DECOMPILER_HALLUCINATION)
    assert all(example.is_training_label for example in curriculum.examples)
    assert {
        example.training_partition for example in curriculum.examples
    } == {"trusted_hard_negative"}


def test_curriculum_schedules_negatives_by_family_difficulty() -> None:
    curriculum = build_legal_ir_hard_negative_curriculum(
        verified_counterexamples=[_trusted_counterexample()],
        source_records=[_source_record()],
        config=LegalIRHardNegativeConfig(stage_count=5),
    )

    scheduled = [
        example
        for stage in curriculum.stages
        for example in stage.examples
    ]
    assert {example.example_id for example in scheduled} == {
        example.example_id for example in curriculum.examples
    }
    difficulties = [example.difficulty for example in scheduled]
    assert difficulties == sorted(difficulties)
    assert [stage.stage_index for stage in curriculum.stages] == sorted(
        stage.stage_index for stage in curriculum.stages
    )
    assert curriculum.stages[0].max_difficulty <= curriculum.stages[-1].max_difficulty


def test_unverified_model_negatives_are_rejected_not_training_labels() -> None:
    curriculum = build_legal_ir_hard_negative_curriculum(
        verified_counterexamples=[_trusted_counterexample()],
        source_records=[_source_record()],
        model_negatives=[
            {
                "candidate_ir": {"rules": [{"modality": "permission"}]},
                "negative_family": VERIFIED_COUNTEREXAMPLE,
                "reference_ir": _reference_ir(),
                "sample_id": "unverified-model-negative",
                "trusted": False,
            }
        ],
    )

    assert any(
        rejected.reason == "unverified_model_negative_not_training_label"
        for rejected in curriculum.rejected_candidates
    )
    assert all(
        example.sample_id != "unverified-model-negative"
        for example in curriculum.examples
    )


def test_effect_report_proves_false_positive_reduction_without_positive_degradation() -> None:
    curriculum = build_legal_ir_hard_negative_curriculum(
        verified_counterexamples=[_trusted_counterexample()],
        source_records=[_source_record()],
        config=LegalIRHardNegativeConfig(
            minimum_false_positive_reduction=0.25,
            trusted_positive_obligation_tolerance=0.03,
        ),
    )
    baseline_scores = {example.example_id: 0.94 for example in curriculum.examples}
    trained_scores = {
        example.example_id: (0.25 if index % 2 == 0 else 0.35)
        for index, example in enumerate(curriculum.examples)
    }
    positives = [
        {
            "after_obligation_equivalence": 0.985,
            "before_obligation_equivalence": 1.0,
            "obligation_id": "trusted-positive-obligation",
            "trusted": True,
            "verification": {"proof_checked": True},
        }
    ]

    report = prove_hard_negatives_reduce_false_positive_semantic_equivalence(
        curriculum,
        baseline_scores=baseline_scores,
        trained_scores=trained_scores,
        trusted_positive_obligations=positives,
    )

    payload = report.to_dict()
    assert report.schema_version == LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION
    assert payload["accepted"] is True
    assert report.hard_negatives_reduce_false_positive_semantic_equivalence is True
    assert report.trusted_positive_obligations_within_tolerance is True
    assert report.baseline_false_positive_count == curriculum.accepted_count
    assert report.trained_false_positive_count == 0
    assert report.false_positive_reduction == 1.0
    assert payload["per_positive"]["trusted-positive-obligation"]["degradation"] == 0.015

    gate = hard_negative_training_effect_gate(
        curriculum,
        baseline_scores=baseline_scores,
        trained_scores=trained_scores,
        trusted_positive_obligations=positives,
    )
    assert gate["accepted"] is True
    assert gate["hard_negative_guard_passed"] is True


def test_effect_report_blocks_when_trusted_positive_obligations_degrade() -> None:
    curriculum = build_legal_ir_hard_negative_curriculum(
        verified_counterexamples=[_trusted_counterexample()],
        source_records=[_source_record()],
        config=LegalIRHardNegativeConfig(trusted_positive_obligation_tolerance=0.01),
    )
    baseline_scores = {example.example_id: 0.95 for example in curriculum.examples}
    trained_scores = {example.example_id: 0.10 for example in curriculum.examples}

    report = prove_hard_negatives_reduce_false_positive_semantic_equivalence(
        curriculum,
        baseline_scores=baseline_scores,
        trained_scores=trained_scores,
        trusted_positive_obligations=[
            {
                "after_obligation_equivalence": 0.94,
                "before_obligation_equivalence": 1.0,
                "obligation_id": "degraded-positive",
                "trusted": True,
                "verification": {"verified": True},
            }
        ],
    )

    assert report.accepted is False
    assert "trusted_positive_obligation_degraded_beyond_tolerance" in report.block_reasons
    assert report.hard_negative_guard_passed is True
    assert report.trusted_positive_guard_passed is False
