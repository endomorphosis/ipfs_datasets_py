"""Tests for verified LegalIR hard-negative curricula and IRHardNegative@1 mining."""

from __future__ import annotations

from dataclasses import replace

from ipfs_datasets_py.logic.formalization.training_contracts import (
    EvidenceStatus,
    ExampleDisposition,
    IRHardNegative,
    LabelAuthority,
    MutationClass,
    NegativeDisposition,
    SemanticRelationship,
    StatementAuthority,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import (
    MINIMAL_MUTATION_CLASSES,
    SEMANTICS_CHANGING,
    SOLVER_TIMED_OUT,
    SOLVER_UNAVAILABLE,
    TARGET_DETERMINISTIC_IR,
    TrustedNegativeCandidate,
    generate_minimal_semantic_mutations,
    parse_and_typecheck_typed_ir,
    seeded_unavailable_solver_mutation,
    seeded_unknown_solver_mutation,
    validate_all_minimal_mutation_classes,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hard_negatives import (
    DECOMPILER_HALLUCINATION,
    HARD_NEGATIVE_FAMILIES,
    IR_HARD_NEGATIVE_INTERFACE,
    IR_HARD_NEGATIVE_MINER_VERSION,
    LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION,
    LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION,
    SOURCE_COPY_SPAN,
    VERIFIED_COUNTEREXAMPLE,
    HardNegativeCandidate,
    HardNegativeRejection,
    LegalIRHardNegativeConfig,
    build_legal_ir_hard_negative_curriculum,
    candidate_from_recipe_case,
    candidate_from_validation_record,
    classify_hard_negative_candidate,
    hard_negative_training_effect_gate,
    load_hard_negative_shards,
    mine_canonical_hard_negatives,
    mine_hard_negatives,
    prove_hard_negatives_reduce_false_positive_semantic_equivalence,
    write_hard_negative_shards,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_positive_pairs import (
    PositiveEquivalenceIndex,
    make_relationship_evidence,
    make_statement,
    mine_canonical_positive_pairs,
    sealed_campaign_lineage,
)


LEGAL_TEXT = "The agency shall provide notice unless emergency conditions exist within 30 days."


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
    assert {example.training_partition for example in curriculum.examples} == {
        "trusted_hard_negative"
    }


def test_curriculum_schedules_negatives_by_family_difficulty() -> None:
    curriculum = build_legal_ir_hard_negative_curriculum(
        verified_counterexamples=[_trusted_counterexample()],
        source_records=[_source_record()],
        config=LegalIRHardNegativeConfig(stage_count=5),
    )

    scheduled = [example for stage in curriculum.stages for example in stage.examples]
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
    assert all(example.sample_id != "unverified-model-negative" for example in curriculum.examples)


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


def test_specified_mutation_classes_parse_typecheck_and_record_minimality() -> None:
    records = validate_all_minimal_mutation_classes()

    assert {item.mutation.mutation_class for item in records} == set(MINIMAL_MUTATION_CLASSES)
    assert {item.mutation.mutation_class for item in records} == set(MutationClass)
    for record in records:
        original_check = parse_and_typecheck_typed_ir(record.mutation.original)
        assert original_check.accepted is True
        assert record.check.accepted is True
        assert record.confirmed is True
        assert record.minimality_checked is True
        assert record.minimal_mutated_paths
        assert record.evidence_status == "verified"
        assert record.relationship != "unknown"
        assert record.evidence_kind in {
            "counterexample",
            "non_equivalence",
            "satisfiability",
            "entailment",
        }


def test_timeout_and_unavailable_solver_outcomes_are_unknown_not_negative() -> None:
    timeout = seeded_unknown_solver_mutation()
    unavailable = seeded_unavailable_solver_mutation()

    assert timeout.solver_outcome == SOLVER_TIMED_OUT
    assert timeout.unknown is True
    assert timeout.confirmed is False
    assert timeout.relationship == "unknown"
    assert timeout.unknown_reason == "solver_timed_out_is_not_negative"

    assert unavailable.solver_outcome == SOLVER_UNAVAILABLE
    assert unavailable.unknown is True
    assert unavailable.confirmed is False
    assert unavailable.relationship == "unknown"


def test_canonical_miner_covers_every_mutation_class_and_segregates_unknowns() -> None:
    result = mine_canonical_hard_negatives()

    assert result.interface == IR_HARD_NEGATIVE_INTERFACE
    assert result.miner_version == IR_HARD_NEGATIVE_MINER_VERSION
    assert set(result.covered_mutation_classes) == {item.value for item in MINIMAL_MUTATION_CLASSES}
    assert len(result.admitted) == len(MINIMAL_MUTATION_CLASSES)
    assert result.unknown
    assert all(
        item.record.disposition is NegativeDisposition.CONFIRMED_NEGATIVE
        for item in result.admitted
    )
    assert all(item.record.disposition is NegativeDisposition.UNKNOWN for item in result.unknown)
    assert all(item.record.minimality_checked for item in result.admitted)
    assert all(item.record.evidence for item in result.admitted)
    assert all(item.example.training_eligible for item in result.admitted)
    assert all(not item.example.training_eligible for item in result.unknown)
    assert {item.kind for item in result.receipts} >= {
        "counterexample",
        "non_equivalence",
        "satisfiability",
        "entailment",
    }
    for item in result.unknown:
        assert item.record.relationship is SemanticRelationship.UNKNOWN
        assert item.example.disposition is ExampleDisposition.QUARANTINED
    assert result.identity() == mine_canonical_hard_negatives().identity()


def test_every_confirmed_negative_round_trips_the_training_contract() -> None:
    result = mine_canonical_hard_negatives()

    for item in result.admitted:
        restored = IRHardNegative.from_json(item.record.to_json())
        assert restored == item.record
        assert restored.cid == item.record.cid
        assert restored.disposition is NegativeDisposition.CONFIRMED_NEGATIVE
        assert restored.schema_version == "ir-hard-negative/v1"


def test_timeout_unavailable_and_unknown_cannot_be_confirmed_negatives() -> None:
    confirmed = candidate_from_recipe_case(
        {
            "case_id": "timeout-claimed-confirmed",
            "disposition": NegativeDisposition.CONFIRMED_NEGATIVE.value,
            "mutation_class": MutationClass.OPERATOR.value,
            "solver_outcome": SOLVER_TIMED_OUT,
        }
    )
    assert (
        classify_hard_negative_candidate(confirmed)
        is HardNegativeRejection.TIMEOUT_AS_NEGATIVE
    )

    unavailable = candidate_from_recipe_case(
        {
            "case_id": "unavailable-claimed-confirmed",
            "disposition": NegativeDisposition.CONFIRMED_NEGATIVE.value,
            "mutation_class": MutationClass.MODALITY.value,
            "solver_outcome": SOLVER_UNAVAILABLE,
        }
    )
    assert (
        classify_hard_negative_candidate(unavailable)
        is HardNegativeRejection.UNAVAILABLE_AS_NEGATIVE
    )

    unknown = candidate_from_recipe_case(
        {
            "case_id": "unknown-claimed-confirmed",
            "disposition": NegativeDisposition.CONFIRMED_NEGATIVE.value,
            "mutation_class": MutationClass.ARGUMENT.value,
            "solver_outcome": "unknown",
        }
    )
    assert classify_hard_negative_candidate(unknown) is HardNegativeRejection.UNKNOWN_AS_NEGATIVE


def test_same_proposition_and_positive_siblings_are_not_negatives() -> None:
    positives = mine_canonical_positive_pairs()
    seed = candidate_from_recipe_case(
        {
            "case_id": "sibling-seed",
            "mutation_class": MutationClass.NEGATION.value,
        }
    )
    alpha = next(
        item.pair
        for item in positives.admitted
        if item.pair.relationship is SemanticRelationship.ALPHA_EQUIVALENT
    )
    proof = next(
        item.pair
        for item in positives.admitted
        if item.pair.relationship is SemanticRelationship.PROOF_EQUIVALENT
    )
    translation = next(
        item.pair
        for item in positives.admitted
        if item.pair.relationship is SemanticRelationship.TRANSLATION_EQUIVALENT
    )

    alpha_candidate = replace(
        seed,
        candidate_id="candidate:alpha-sibling",
        original=alpha.left,
        mutant=alpha.right,
        lineage=alpha.lineage,
        sibling_statement_ids=(alpha.right.statement_id,),
        sibling_relationship=SemanticRelationship.ALPHA_EQUIVALENT,
    )
    assert (
        classify_hard_negative_candidate(alpha_candidate, positive_index=positives.index)
        is HardNegativeRejection.ALPHA_EQUIVALENT_SIBLING
    )

    proof_candidate = replace(
        seed,
        candidate_id="candidate:proof-sibling",
        original=proof.left,
        mutant=proof.right,
        lineage=proof.lineage,
        sibling_statement_ids=(proof.right.statement_id,),
        sibling_relationship=SemanticRelationship.PROOF_EQUIVALENT,
    )
    assert (
        classify_hard_negative_candidate(proof_candidate, positive_index=positives.index)
        is HardNegativeRejection.PROOF_EQUIVALENT_SIBLING
    )

    translation_candidate = replace(
        seed,
        candidate_id="candidate:translation-sibling",
        original=translation.left,
        mutant=translation.right,
        lineage=translation.lineage,
        sibling_statement_ids=(translation.right.statement_id,),
        sibling_relationship=SemanticRelationship.TRANSLATION_EQUIVALENT,
    )
    assert (
        classify_hard_negative_candidate(
            translation_candidate, positive_index=positives.index
        )
        is HardNegativeRejection.TRANSLATION_SIBLING
    )


def test_unchecked_model_labels_cannot_confirm_a_hard_negative() -> None:
    seed = candidate_from_recipe_case(
        {
            "case_id": "model-label",
            "mutation_class": MutationClass.NEGATION.value,
        }
    )
    model_evidence = make_relationship_evidence(
        seed.original,
        seed.mutant,
        seed.relationship,
        evidence_id="evidence:model-negative",
        authority=LabelAuthority.MODEL_OUTPUT,
        status=EvidenceStatus.CANDIDATE,
        independent=False,
        result_authority=None,
    )
    candidate = HardNegativeCandidate(
        candidate_id="candidate:model-negative",
        original=seed.original,
        mutant=seed.mutant,
        mutation_class=seed.mutation_class,
        mutated_paths=seed.mutated_paths,
        relationship=seed.relationship,
        lineage=seed.lineage,
        evidence=(model_evidence,),
        minimality_checked=True,
        disposition=NegativeDisposition.CONFIRMED_NEGATIVE,
        evidence_kind=seed.evidence_kind,
        solver_outcome=seed.solver_outcome,
    )
    assert (
        classify_hard_negative_candidate(candidate)
        is HardNegativeRejection.UNCHECKED_MODEL_LABEL
    )
    mined = mine_hard_negatives((candidate,))
    assert mined.admitted == ()
    assert mined.rejected[0].reason is HardNegativeRejection.UNCHECKED_MODEL_LABEL


def test_unknowns_are_written_to_a_segregated_shard(tmp_path) -> None:
    bundle = write_hard_negative_shards(tmp_path)
    loaded = load_hard_negative_shards(tmp_path)
    unknown_path = tmp_path / "shards" / "unknown.json"

    assert unknown_path.is_file()
    assert (tmp_path / "recipe.json").is_file()
    assert (tmp_path / "classes.json").is_file()
    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "receipts.json").is_file()
    for mutation_class in MINIMAL_MUTATION_CLASSES:
        assert (tmp_path / "shards" / f"{mutation_class.value}.json").is_file()

    confirmed = [item for item in loaded if item.disposition is NegativeDisposition.CONFIRMED_NEGATIVE]
    unknowns = [item for item in loaded if item.disposition is NegativeDisposition.UNKNOWN]
    assert {item.mutation_class for item in confirmed} == set(MINIMAL_MUTATION_CLASSES)
    assert unknowns
    assert all(item.relationship is SemanticRelationship.UNKNOWN for item in unknowns)
    assert bundle["manifest"]["unknown_count"] == len(unknowns)
    assert set(bundle["manifest"]["covered_mutation_classes"]) == {
        item.value for item in MINIMAL_MUTATION_CLASSES
    }


def test_validation_record_candidates_are_training_labels_only_when_confirmed() -> None:
    records = validate_all_minimal_mutation_classes()
    confirmed = candidate_from_validation_record(records[0])
    unknown = candidate_from_validation_record(seeded_unknown_solver_mutation())

    assert confirmed.disposition is NegativeDisposition.CONFIRMED_NEGATIVE
    assert classify_hard_negative_candidate(confirmed) is None
    assert unknown.disposition is NegativeDisposition.UNKNOWN
    assert unknown.relationship is SemanticRelationship.UNKNOWN
    assert classify_hard_negative_candidate(unknown) is None
