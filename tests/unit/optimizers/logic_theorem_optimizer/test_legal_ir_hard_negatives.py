"""Tests for verified LegalIR hard-negative curricula and IRHardNegative@1 mining."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.formalization.training_contracts import (
    EvidenceStatus,
    ExampleDisposition,
    IRHardNegative,
    LabelEvidence,
    TrainingContractValidationError,
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
    HardNegativeAdmissionError,
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
        assert parse_and_typecheck_typed_ir(record.mutation.original).accepted is True
        assert record.check.accepted is True
        assert record.confirmed is False
        assert record.unknown is True
        assert record.minimality_checked is True
        assert record.minimal_mutated_paths
        assert record.evidence_status == "unknown"
        assert record.relationship == "unknown"
        assert record.solver_outcome == "unknown"
        assert record.evidence_kind in {"counterexample", "non_equivalence", "satisfiability", "entailment"}


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
    assert result.miner_version == IR_HARD_NEGATIVE_MINER_VERSION == "pgir-041-negative-miner-v2"
    assert result.covered_mutation_classes == ()  # This field counts admitted classes.
    assert result.admitted == ()
    assert result.receipts == ()
    assert len(result.unknown) == len(MINIMAL_MUTATION_CLASSES) + 1
    assert {item.record.mutation_class for item in result.unknown} == set(MINIMAL_MUTATION_CLASSES)
    for item in result.unknown:
        assert item.record.disposition is NegativeDisposition.UNKNOWN
        assert item.record.relationship is SemanticRelationship.UNKNOWN
        assert item.record.evidence == ()
        assert item.example.training_eligible is False
        assert item.example.disposition is ExampleDisposition.QUARANTINED
    assert result.identity() == mine_canonical_hard_negatives().identity()


def test_every_confirmed_negative_round_trips_the_training_contract() -> None:
    # Fictional caller labels exercise software admission, not a solver or law.
    candidates = tuple(_fictional_admitted_pgir041_candidate(kind) for kind in MINIMAL_MUTATION_CLASSES)
    result = mine_hard_negatives(candidates, positive_index=PositiveEquivalenceIndex())
    assert len(result.admitted) == len(MINIMAL_MUTATION_CLASSES) > 0
    assert result.rejected == ()
    assert result.unknown == ()
    assert len(result.receipts) == len(result.admitted)
    for item in result.admitted:
        assert item.example.training_eligible is True
        restored = IRHardNegative.from_json(item.record.to_json())
        assert restored == item.record
        assert restored.cid == item.record.cid
        assert restored.disposition is NegativeDisposition.CONFIRMED_NEGATIVE
        assert restored.schema_version == "ir-hard-negative/v1"


def test_timeout_unavailable_and_unknown_cannot_be_confirmed_negatives() -> None:
    for outcome, kind, rejection in (
        (SOLVER_TIMED_OUT, MutationClass.OPERATOR, HardNegativeRejection.TIMEOUT_AS_NEGATIVE),
        (SOLVER_UNAVAILABLE, MutationClass.MODALITY, HardNegativeRejection.UNAVAILABLE_AS_NEGATIVE),
        ("unknown", MutationClass.ARGUMENT, HardNegativeRejection.UNKNOWN_AS_NEGATIVE),
    ):
        # A recipe cannot promote an unattested proposal through a disposition flag.
        recipe_candidate = candidate_from_recipe_case({
            "case_id": "fictional-forced-confirmed-" + kind.value,
            "disposition": NegativeDisposition.CONFIRMED_NEGATIVE.value,
            "mutation_class": kind.value,
            "solver_outcome": outcome,
        })
        _assert_unattested_pgir041_candidate_is_unknown(recipe_candidate)
        # Keep a separate direct malicious-candidate control for classifier fences.
        explicit = _fictional_admitted_pgir041_candidate(kind)
        malicious = replace(explicit, solver_outcome=outcome)
        assert malicious.disposition is NegativeDisposition.CONFIRMED_NEGATIVE
        assert classify_hard_negative_candidate(malicious) is rejection
        result = mine_hard_negatives((malicious,), positive_index=PositiveEquivalenceIndex())
        assert result.admitted == ()
        assert result.unknown == ()
        assert len(result.rejected) == 1
        assert result.rejected[0].reason is rejection


def test_same_proposition_and_positive_siblings_are_not_negatives() -> None:
    # Fictional caller-supplied labels exercise sibling filtering, not a real proof/review.
    from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_positive_pairs as positive_owner
    candidates = []
    for case in positive_owner.canonical_positive_pair_recipe()["cases"]:
        proposal = positive_owner.candidate_from_recipe_case(case)
        label = positive_owner.make_relationship_evidence(
            proposal.left, proposal.right, proposal.relationship,
            evidence_id="fixture:positive-sibling:" + case["case_id"],
            authority=LabelAuthority(case["required_authority"]),
            independent=case.get("required_independent"),
            result_authority=AuthorityKind(case["required_result_authority"])
                if case.get("required_result_authority") else None,
            producer_id="fixture:positive-sibling-not-real-checker", producer_version="1",
        )
        candidates.append(positive_owner.candidate_from_recipe_case(case, evidence=(label,)))
    positives = positive_owner.mine_positive_pairs(candidates)
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
    seed = _fictional_admitted_pgir041_candidate(MutationClass.NEGATION, case_id="model-label")
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
    assert (tmp_path / "shards" / "unknown.json").is_file()
    for name in ("recipe.json", "classes.json", "manifest.json", "receipts.json"):
        assert (tmp_path / name).is_file()
    for mutation_class in MINIMAL_MUTATION_CLASSES:
        assert not (tmp_path / "shards" / f"{mutation_class.value}.json").exists()
    assert loaded
    assert all(item.disposition is NegativeDisposition.UNKNOWN for item in loaded)
    assert all(item.relationship is SemanticRelationship.UNKNOWN for item in loaded)
    assert all(item.evidence == () for item in loaded)
    assert {item.mutation_class for item in loaded} == set(MINIMAL_MUTATION_CLASSES)
    assert bundle["manifest"]["unknown_count"] == len(loaded)
    assert bundle["manifest"]["covered_mutation_classes"] == []
    assert bundle["receipts"]["receipts"] == []


def test_validation_record_candidates_are_training_labels_only_when_confirmed() -> None:
    records = validate_all_minimal_mutation_classes()
    for record in records:
        _assert_unattested_pgir041_candidate_is_unknown(candidate_from_validation_record(record))
    _assert_unattested_pgir041_candidate_is_unknown(
        candidate_from_validation_record(seeded_unknown_solver_mutation()))
    confirmed = _fictional_admitted_pgir041_candidate(MutationClass.NEGATION)
    assert confirmed.disposition is NegativeDisposition.CONFIRMED_NEGATIVE
    assert classify_hard_negative_candidate(confirmed) is None
    mined = mine_hard_negatives((confirmed,), positive_index=PositiveEquivalenceIndex())
    assert len(mined.admitted) == 1
    assert mined.admitted[0].example.training_eligible is True


# PGIR-041 admission boundary: these are fictional proposal-only records.
# They provide no solver execution, witness, signed review, or legal authority.
# Original red results and pre-fix expectations remain in immutable receipts.
def _assert_unattested_pgir041_candidate_is_unknown(candidate) -> None:
    assert candidate.disposition is NegativeDisposition.UNKNOWN
    assert candidate.relationship is SemanticRelationship.UNKNOWN
    assert candidate.evidence == ()
    result = mine_hard_negatives((candidate,), positive_index=PositiveEquivalenceIndex())
    assert result.admitted == ()
    assert result.rejected == ()
    assert result.receipts == ()
    assert len(result.unknown) == 1
    assert result.unknown[0].record.disposition is NegativeDisposition.UNKNOWN
    assert result.unknown[0].example.disposition is ExampleDisposition.QUARANTINED
    assert result.unknown[0].example.training_eligible is False


def test_pgir041_default_mutation_record_without_solver_evidence_is_unknown() -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import (
        collect_mutation_evidence,
    )

    mutation = generate_minimal_semantic_mutations()[0]
    record = collect_mutation_evidence(mutation)
    assert record.check.accepted is True
    assert record.evidence_status == "unknown"
    assert record.relationship == "unknown"
    assert record.confirmed is False
    assert record.unknown is True


def test_pgir041_default_record_cannot_mint_independent_training_evidence() -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import (
        collect_mutation_evidence,
    )

    record = collect_mutation_evidence(generate_minimal_semantic_mutations()[0])
    candidate = candidate_from_validation_record(record, case_id="fictional-no-checker")
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


def test_pgir041_arbitrary_not_run_solver_string_is_unknown() -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import (
        collect_mutation_evidence,
    )

    record = collect_mutation_evidence(
        generate_minimal_semantic_mutations()[0], solver_outcome="not_run"
    )
    assert record.check.accepted is True
    assert record.evidence_status == "unknown"
    assert record.relationship == "unknown"
    assert record.confirmed is False
    assert record.unknown is True


def test_pgir041_recipe_solver_string_cannot_supply_training_authority() -> None:
    candidate = candidate_from_recipe_case({
        "case_id": "fictional-not-run-recipe",
        "mutation_class": MutationClass.NEGATION.value,
        "solver_outcome": "not_run",
    })
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


def test_pgir041_forged_verified_record_without_evidence_stays_unknown() -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import (
        MutationValidationRecord,
    )

    mutation = generate_minimal_semantic_mutations()[0]
    # A caller-authored result enum is the attack input, not a checker receipt.
    record = MutationValidationRecord(
        mutation=mutation,
        check=parse_and_typecheck_typed_ir(mutation.mutant),
        evidence_kind=mutation.evidence_kind,
        evidence_status="verified",
        solver_outcome="counterexample",
        minimality_checked=True,
        minimal_mutated_paths=mutation.mutated_paths,
        relationship=mutation.relationship,
    )
    assert record.check.accepted is True
    candidate = candidate_from_validation_record(record, case_id="fictional-forged-verified")
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


def test_pgir041_unused_binder_rename_cannot_become_verified_non_equivalence() -> None:
    from copy import deepcopy
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import (
        MinimalSemanticMutation,
        canonical_typed_legal_ir,
        collect_mutation_evidence,
    )

    original = canonical_typed_legal_ir()
    renamed = deepcopy(original)
    # This legacy typed-formula fixture has no predicate occurrence of binder x.
    # Renaming that bound label does not change its formula. This test does not
    # claim that the fixture is canonical TypedExpression or reviewed legal IR.
    assert original["formulas"][0]["quantifier"]["binder"] == "x"
    assert original["formulas"][0]["predicate"]["arguments"] == ["notice"]
    renamed["formulas"][0]["quantifier"]["binder"] = "y"
    assert parse_and_typecheck_typed_ir(original).accepted is True
    assert parse_and_typecheck_typed_ir(renamed).accepted is True
    restored = deepcopy(renamed)
    restored["formulas"][0]["quantifier"]["binder"] = "x"
    assert restored == original
    mutation = MinimalSemanticMutation(
        mutation_class=MutationClass.QUANTIFIER,
        original=original,
        mutant=renamed,
        mutated_paths=("/formulas/0/quantifier/binder",),
        relationship="non_equivalent",
        evidence_kind="satisfiability",
        description="Fictional unused-bound-label alpha rename; no solver evidence.",
        solver_outcome="sat_model",
    )
    record = collect_mutation_evidence(mutation)
    assert record.evidence_status == "unknown"
    assert record.relationship == "unknown"
    assert record.confirmed is False
    candidate = candidate_from_validation_record(record, case_id="fictional-alpha-rename")
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


def test_pgir041_unattested_canonical_recipe_cannot_admit_training_negatives() -> None:
    result = mine_canonical_hard_negatives()
    assert result.admitted == ()
    assert result.receipts == ()
    assert result.unknown
    assert {item.record.mutation_class for item in result.unknown} == set(MINIMAL_MUTATION_CLASSES)
    assert all(item.record.disposition is NegativeDisposition.UNKNOWN for item in result.unknown)
    assert all(item.record.evidence == () for item in result.unknown)
    assert all(item.example.training_eligible is False for item in result.unknown)


def test_pgir041_existing_timeout_record_stays_unknown_without_training() -> None:
    record = seeded_unknown_solver_mutation()
    assert record.check.accepted is True
    assert record.evidence_status == "unknown"
    assert record.confirmed is False
    candidate = candidate_from_validation_record(record, case_id="fictional-timeout-control")
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


# Explicit LabelEvidence below is fictional, trusted-caller test metadata.
# No fixture executes/authenticates a solver, toolchain, directed proof,
# independent reviewer or legal interpretation. These labels test binding only.
def _fictional_pgir041_record_and_label(kind=MutationClass.NEGATION, *, case_id=None):
    from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import collect_mutation_evidence

    mutation = next(item for item in generate_minimal_semantic_mutations() if item.mutation_class is kind)
    outcome = {"counterexample": "counterexample", "non_equivalence": "disproved",
               "satisfiability": "sat_model", "entailment": "not_entailed"}[mutation.evidence_kind]
    record = collect_mutation_evidence(mutation, solver_outcome=outcome)
    case = case_id or "fictional-caller-label-" + kind.value
    seed = candidate_from_validation_record(record, case_id=case)
    assert seed.disposition is NegativeDisposition.UNKNOWN
    authority = (LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER
                 if mutation.evidence_kind in {"counterexample", "satisfiability"}
                 else LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER)
    label = make_relationship_evidence(
        seed.original, seed.mutant, SemanticRelationship(mutation.relationship),
        evidence_id="evidence:" + case, authority=authority, status=EvidenceStatus.VERIFIED,
        independent=True, producer_id="fixture:caller-metadata-only", producer_version="fictional/v1",
        result_authority=(AuthorityKind.THEOREM_PROOF if mutation.evidence_kind == "entailment"
                          else AuthorityKind.SATISFIABILITY))
    return record, label, case


def _fictional_admitted_pgir041_candidate(kind=MutationClass.NEGATION, *, case_id=None):
    record, label, case = _fictional_pgir041_record_and_label(kind, case_id=case_id)
    candidate = candidate_from_validation_record(record, case_id=case, evidence=(label,))
    assert candidate.disposition is NegativeDisposition.CONFIRMED_NEGATIVE
    assert candidate.evidence == (label,)
    return candidate


@pytest.mark.parametrize("outcome", ["counterexample", "disproved", "sat_model", "not_entailed",
                                    "not_run", "unknown", "timed_out", "unavailable"])
def test_pgir041_reported_outcomes_and_override_knobs_alone_never_admit(outcome):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import collect_mutation_evidence
    record = collect_mutation_evidence(generate_minimal_semantic_mutations()[0], solver_outcome=outcome)
    assert record.evidence_status == "unknown"
    assert record.confirmed is False
    candidate = candidate_from_validation_record(record,
        authority=LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
        evidence_status=EvidenceStatus.VERIFIED, independent=True)
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


@pytest.mark.parametrize("outcome", ["not_run", "unknown", "timed_out", "unavailable", ""])
def test_pgir041_explicit_labels_cannot_rescue_unsupported_outcome(outcome):
    record, label, case = _fictional_pgir041_record_and_label()
    record = replace(record, solver_outcome=outcome)
    candidate = candidate_from_validation_record(record, case_id=case, evidence=(label,))
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


@pytest.mark.parametrize("damage", ["subject-id", "subject-digest", "missing-endpoint", "relationship",
    "candidate-status", "unknown-status", "rejected-status", "unknown-authority", "model-authority", "not-independent"])
def test_pgir041_supplied_evidence_must_bind_exact_pair_and_eligible_label(damage):
    record, label, case = _fictional_pgir041_record_and_label()
    if damage == "subject-id":
        label = replace(label, subject_statement_ids=("fictional:other-statement", label.subject_statement_ids[1]))
    elif damage == "subject-digest":
        label = replace(label, subject_statement_digests=("sha256:" + "0" * 64, label.subject_statement_digests[1]))
    elif damage == "missing-endpoint":
        label = replace(label, subject_statement_ids=label.subject_statement_ids[:1],
                        subject_statement_digests=label.subject_statement_digests[:1])
    elif damage == "relationship":
        label = replace(label, relationship=SemanticRelationship.NON_EQUIVALENT)
    elif damage.endswith("-status"):
        label = replace(label, status=EvidenceStatus(damage.removesuffix("-status")))
    elif damage == "unknown-authority":
        label = replace(label, authority=LabelAuthority.UNKNOWN, status=EvidenceStatus.CANDIDATE,
                        independent=False, result_authority=None)
    elif damage == "model-authority":
        label = replace(label, authority=LabelAuthority.MODEL_OUTPUT, status=EvidenceStatus.CANDIDATE,
                        independent=False, result_authority=None)
    elif damage == "not-independent":
        label = replace(label, authority=LabelAuthority.HUMAN_REVIEW,
                        independent=False, result_authority=None)
    with pytest.raises((TrainingContractValidationError, HardNegativeAdmissionError)):
        candidate_from_validation_record(record, case_id=case, evidence=(label,))


@pytest.mark.parametrize("knob", ["authority", "evidence_status", "independent"])
def test_pgir041_override_knobs_cannot_upgrade_supplied_labels(knob):
    record, label, case = _fictional_pgir041_record_and_label()
    if knob == "authority":
        label = replace(label, authority=LabelAuthority.UNKNOWN, status=EvidenceStatus.CANDIDATE,
                        independent=False, result_authority=None)
        requested = LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER
    elif knob == "evidence_status":
        label = replace(label, status=EvidenceStatus.CANDIDATE)
        requested = EvidenceStatus.VERIFIED
    else:
        label = replace(label, authority=LabelAuthority.HUMAN_REVIEW,
                        independent=False, result_authority=None)
        requested = True
    with pytest.raises(HardNegativeAdmissionError, match="metadata cannot override supplied evidence"):
        candidate_from_validation_record(record, case_id=case, evidence=(label,), **{knob: requested})


def test_pgir041_supplied_label_wire_is_detached_without_authenticating_it():
    record, label, case = _fictional_pgir041_record_and_label()
    original_wire = label.to_dict()
    labels = [label]
    candidate = candidate_from_validation_record(record, case_id=case, evidence=labels)
    labels.clear()
    assert candidate.evidence == (label,)
    assert candidate.evidence[0] is not label
    assert label.to_dict() == original_wire
    assert candidate.evidence[0].producer_id == "fixture:caller-metadata-only"
    # The opaque caller-supplied digest is retained, not authenticated by a solver.
    alternate = replace(label, evidence_digest="sha256:" + "1" * 64)
    alternate_candidate = candidate_from_validation_record(record, case_id=case, evidence=(alternate,))
    assert alternate_candidate.evidence[0].evidence_digest == alternate.evidence_digest


def test_pgir041_mapping_cannot_impersonate_canonical_label_evidence():
    record, label, case = _fictional_pgir041_record_and_label()
    with pytest.raises(HardNegativeAdmissionError, match="explicit LabelEvidence records required"):
        candidate_from_validation_record(record, case_id=case, evidence=(label.to_dict(),))


def test_pgir041_labels_for_other_case_identity_do_not_rebind_automatically():
    record, label, case = _fictional_pgir041_record_and_label()
    with pytest.raises(TrainingContractValidationError, match="bound to another statement"):
        candidate_from_validation_record(record, case_id=case + "-other", evidence=(label,))


def test_pgir041_labels_for_stale_endpoint_bytes_are_refused():
    record, label, case = _fictional_pgir041_record_and_label()
    record.mutation.mutant["formulas"][0]["predicate"]["arguments"] = ["different_document"]
    with pytest.raises(TrainingContractValidationError, match="bound to another statement"):
        candidate_from_validation_record(record, case_id=case, evidence=(label,))


def test_pgir041_rebound_labels_do_not_rescue_stale_successful_parse_flags():
    record, label, case = _fictional_pgir041_record_and_label()
    assert record.check.accepted is True
    record.mutation.mutant["formulas"][0]["operator"]["symbol"] = "unsupported-symbol"
    seed = candidate_from_validation_record(record, case_id=case)
    rebound = replace(label,
        subject_statement_ids=(seed.original.statement_id, seed.mutant.statement_id),
        subject_statement_digests=(seed.original.statement_digest, seed.mutant.statement_digest))
    candidate = candidate_from_validation_record(record, case_id=case, evidence=(rebound,))
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


def test_pgir041_incomplete_operator_leaf_path_does_not_supply_minimality():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import collect_mutation_evidence
    record, label, case = _fictional_pgir041_record_and_label(MutationClass.OPERATOR)
    assert record.mutation.mutated_paths == ("/formulas/0/operator",)
    incomplete = replace(record.mutation, mutated_paths=("/formulas/0/operator/symbol",))
    recomputed = collect_mutation_evidence(incomplete, solver_outcome="disproved")
    assert recomputed.check.accepted is True
    assert recomputed.minimality_checked is False
    forged = replace(record, mutation=incomplete, minimality_checked=True)
    candidate = candidate_from_validation_record(forged, case_id=case, evidence=(label,))
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


def test_pgir041_current_identical_payload_does_not_reuse_old_minimality_flags():
    from copy import deepcopy
    record, label, case = _fictional_pgir041_record_and_label()
    record.mutation.mutant.clear()
    record.mutation.mutant.update(deepcopy(record.mutation.original))
    seed = candidate_from_validation_record(record, case_id=case)
    rebound = replace(label,
        subject_statement_ids=(seed.original.statement_id, seed.mutant.statement_id),
        subject_statement_digests=(seed.original.statement_digest, seed.mutant.statement_digest))
    candidate = candidate_from_validation_record(record, case_id=case, evidence=(rebound,))
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


def test_pgir041_endpoint_mutation_during_evidence_serialization_refuses(monkeypatch):
    record, label, case = _fictional_pgir041_record_and_label()
    original_to_dict = LabelEvidence.to_dict
    def mutate_during_serialization(item):
        wire = original_to_dict(item)
        record.mutation.mutant["formulas"][0]["predicate"]["arguments"] = ["changed_during_binding"]
        return wire
    monkeypatch.setattr(LabelEvidence, "to_dict", mutate_during_serialization)
    with pytest.raises(HardNegativeAdmissionError, match="mutation endpoints changed during evidence binding"):
        candidate_from_validation_record(record, case_id=case, evidence=(label,))


def test_pgir041_first_unverified_label_cannot_steal_receipt_or_training_selection():
    record, label, case = _fictional_pgir041_record_and_label()
    pending = replace(label, evidence_id="a-fictional-pending", status=EvidenceStatus.CANDIDATE)
    verified = replace(label, evidence_id="z-fictional-selected")
    candidate = candidate_from_validation_record(record, case_id=case, evidence=(pending, verified))
    assert candidate.evidence[0].status is EvidenceStatus.CANDIDATE
    result = mine_hard_negatives((candidate,), positive_index=PositiveEquivalenceIndex())
    assert len(result.admitted) == 1
    assert result.admitted[0].example.training_eligible is True
    assert len(result.receipts) == 1
    assert result.receipts[0].evidence_id == verified.evidence_id
    assert result.receipts[0].evidence_digest == verified.evidence_digest
    assert result.admitted[0].example.selected_evidence_id == verified.evidence_id


def test_pgir041_explicit_fictional_labels_roundtrip_nonempty_class_shards(tmp_path):
    candidates = [_fictional_admitted_pgir041_candidate(kind) for kind in MINIMAL_MUTATION_CLASSES]
    candidates.append(candidate_from_validation_record(seeded_unknown_solver_mutation(), case_id="fictional-pending-timeout"))
    result = mine_hard_negatives(candidates, positive_index=PositiveEquivalenceIndex())
    assert len(result.admitted) == len(MINIMAL_MUTATION_CLASSES) > 0
    assert len(result.unknown) == 1
    bundle = write_hard_negative_shards(tmp_path, result=result)
    loaded = load_hard_negative_shards(tmp_path)
    confirmed = [item for item in loaded if item.disposition is NegativeDisposition.CONFIRMED_NEGATIVE]
    unknown = [item for item in loaded if item.disposition is NegativeDisposition.UNKNOWN]
    assert len(confirmed) == len(MINIMAL_MUTATION_CLASSES)
    assert len(unknown) == 1
    assert {item.mutation_class for item in confirmed} == set(MINIMAL_MUTATION_CLASSES)
    for kind in MINIMAL_MUTATION_CLASSES:
        assert (tmp_path / "shards" / f"{kind.value}.json").is_file()
    assert (tmp_path / "shards" / "unknown.json").is_file()
    assert bundle["manifest"]["unknown_count"] == 1
    assert set(bundle["manifest"]["covered_mutation_classes"]) == {kind.value for kind in MINIMAL_MUTATION_CLASSES}
    assert len(bundle["receipts"]["receipts"]) == len(MINIMAL_MUTATION_CLASSES)



def test_pgir041_explicit_label_iterable_is_consumed_once():
    record, label, case = _fictional_pgir041_record_and_label()
    class SinglePassLabels:
        def __init__(self):
            self.iterations = 0
        def __iter__(self):
            self.iterations += 1
            if self.iterations != 1:
                raise AssertionError("caller evidence iterable consumed more than once")
            yield label
    supplied = SinglePassLabels()
    candidate = candidate_from_validation_record(record, case_id=case, evidence=supplied)
    assert supplied.iterations == 1
    assert candidate.evidence == (label,)
    assert candidate.evidence[0] is not label
    result = mine_hard_negatives((candidate,), positive_index=PositiveEquivalenceIndex())
    assert len(result.admitted) == 1
    assert result.admitted[0].example.training_eligible is True


def test_pgir041_changing_label_iterable_cannot_upgrade_first_observation():
    record, label, case = _fictional_pgir041_record_and_label()
    first = replace(label, authority=LabelAuthority.MODEL_OUTPUT,
                    status=EvidenceStatus.CANDIDATE, independent=False, result_authority=None)
    class ChangingLabels:
        def __init__(self):
            self.iterations = 0
        def __iter__(self):
            self.iterations += 1
            yield first if self.iterations == 1 else label
    supplied = ChangingLabels()
    with pytest.raises(HardNegativeAdmissionError, match="unchecked_model_label"):
        candidate_from_validation_record(record, case_id=case, evidence=supplied)
    assert supplied.iterations == 1


def test_pgir041_identical_payload_is_rejected_without_semantic_evidence():
    from copy import deepcopy
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import collect_mutation_evidence
    mutation = generate_minimal_semantic_mutations()[0]
    same = replace(mutation, mutant=deepcopy(mutation.original))
    record = collect_mutation_evidence(same)
    assert record.check.accepted is True
    assert record.evidence_status == "rejected"
    assert record.unknown_reason == "mutation_did_not_change_formula_payload"
    assert record.relationship == "unknown"
    assert record.confirmed is False
    assert record.minimality_checked is False
    _assert_unattested_pgir041_candidate_is_unknown(candidate_from_validation_record(record))



@pytest.mark.parametrize("paths", [
    ("/formulas/0/operator", "/formulas/0"),
    ("/formulas/0/operator", "/formulas/0/operator/label"),
    ("/formulas/0/operator", "/formulas/0/operator"),
    ("/formulas/00/operator",),
    ("/formulas/0/operator", "/formulas/00/operator"),
])
def test_pgir041_overlapping_duplicate_or_alias_paths_cannot_supply_minimality(paths):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import collect_mutation_evidence
    record, label, case = _fictional_pgir041_record_and_label(MutationClass.OPERATOR)
    altered = replace(record.mutation, mutated_paths=paths)
    recomputed = collect_mutation_evidence(altered, solver_outcome="disproved")
    assert recomputed.check.accepted is True
    assert recomputed.minimality_checked is False
    stale_claim = replace(record, mutation=altered, minimality_checked=True)
    candidate = candidate_from_validation_record(stale_claim, case_id=case, evidence=(label,))
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


@pytest.mark.parametrize("field,value,reason", [
    ("mutated_paths", ["/formulas/0"], "recipe cannot override checked mutation paths"),
    ("evidence_kind", "non_equivalence", "recipe cannot override checked evidence kind"),
])
def test_pgir041_recipe_cannot_rewrite_checked_paths_or_evidence_kind(field, value, reason):
    record, label, case = _fictional_pgir041_record_and_label()
    recipe = {"case_id": case, "mutation_class": record.mutation.mutation_class.value,
              "solver_outcome": record.solver_outcome, field: value}
    with pytest.raises(HardNegativeAdmissionError, match=reason):
        candidate_from_recipe_case(recipe, evidence=(label,))


@pytest.mark.parametrize("outcome", ["counterexample", "disproved", "sat_model", "not_entailed", "not_run"])
def test_pgir041_recipe_confirmed_flag_without_evidence_stays_unknown(outcome):
    candidate = candidate_from_recipe_case({
        "case_id": "fictional-no-evidence-forced-confirmed",
        "mutation_class": MutationClass.NEGATION.value,
        "solver_outcome": outcome,
        "disposition": NegativeDisposition.CONFIRMED_NEGATIVE.value,
        "authority": LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER.value,
        "evidence_status": EvidenceStatus.VERIFIED.value,
        "independent": True,
    })
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


def test_pgir041_exact_recipe_preserves_source_kind_and_can_only_quarantine():
    record, label, case = _fictional_pgir041_record_and_label()
    recipe = {"case_id": case, "mutation_class": record.mutation.mutation_class.value,
              "solver_outcome": record.solver_outcome,
              "mutated_paths": list(record.mutation.mutated_paths),
              "evidence_kind": record.mutation.evidence_kind,
              "source_kind": "fictional-impersonated-reviewed-proof"}
    explicit = candidate_from_recipe_case(recipe, evidence=(label,))
    assert explicit.disposition is NegativeDisposition.CONFIRMED_NEGATIVE
    assert explicit.source_kind == "typed_mutation"
    result = mine_hard_negatives((explicit,), positive_index=PositiveEquivalenceIndex())
    assert len(result.admitted) == 1
    assert result.admitted[0].example.training_eligible is True
    quarantined = candidate_from_recipe_case(
        {**recipe, "disposition": NegativeDisposition.UNKNOWN.value}, evidence=(label,))
    assert quarantined.source_kind == "typed_mutation"
    _assert_unattested_pgir041_candidate_is_unknown(quarantined)



def test_pgir041_quarantined_recipe_cannot_retain_explicit_admission():
    record, label, case = _fictional_pgir041_record_and_label()
    recipe = {"case_id": case, "mutation_class": record.mutation.mutation_class.value,
              "solver_outcome": record.solver_outcome}
    explicit = candidate_from_recipe_case(recipe, evidence=(label,))
    assert explicit.disposition is NegativeDisposition.CONFIRMED_NEGATIVE
    quarantined = candidate_from_recipe_case(
        {**recipe, "disposition": NegativeDisposition.QUARANTINED.value}, evidence=(label,))
    _assert_unattested_pgir041_candidate_is_unknown(quarantined)


def test_pgir041_empty_root_shadow_pointer_cannot_supply_minimality():
    from copy import deepcopy
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import collect_mutation_evidence
    record, label, case = _fictional_pgir041_record_and_label(MutationClass.OPERATOR)
    original, mutant = deepcopy(record.mutation.original), deepcopy(record.mutation.mutant)
    # The legacy parser permits diagnostic root fields. The declared pointer
    # enters the empty root key; lstrip('/') must not reinterpret it as root.
    # This is not a canonical TypedExpression or reviewed legal payload.
    shadow = {"formulas": deepcopy(original["formulas"])}
    original[""] = deepcopy(shadow)
    mutant[""] = deepcopy(shadow)
    assert original[""] == mutant[""]
    assert original["formulas"] != mutant["formulas"]
    changed = replace(record.mutation, original=original, mutant=mutant,
                      mutated_paths=("//formulas/0/operator",))
    current = collect_mutation_evidence(changed, solver_outcome="disproved")
    assert current.check.accepted is True
    assert current.minimality_checked is False
    stale = replace(record, mutation=changed, minimality_checked=True)
    seed = candidate_from_validation_record(stale, case_id=case)
    rebound = replace(label,
        subject_statement_ids=(seed.original.statement_id, seed.mutant.statement_id),
        subject_statement_digests=(seed.original.statement_digest, seed.mutant.statement_digest))
    candidate = candidate_from_validation_record(stale, case_id=case, evidence=(rebound,))
    _assert_unattested_pgir041_candidate_is_unknown(candidate)


@pytest.mark.parametrize("endpoint", ["original", "mutant"])
@pytest.mark.parametrize("schema", [None, "fictional-unsupported-typed-formula/v999"])
def test_pgir041_missing_or_unknown_schema_cannot_be_rescued_by_labels(endpoint, schema):
    record, label, case = _fictional_pgir041_record_and_label()
    assert record.check.accepted is True
    payload = getattr(record.mutation, endpoint)
    if schema is None:
        payload.pop("schema")
    else:
        payload["schema"] = schema
    checked = parse_and_typecheck_typed_ir(payload)
    assert checked.accepted is False
    assert checked.typed is False
    assert "missing_or_unknown_schema" in checked.diagnostics
    seed = candidate_from_validation_record(record, case_id=case)
    rebound = replace(label,
        subject_statement_ids=(seed.original.statement_id, seed.mutant.statement_id),
        subject_statement_digests=(seed.original.statement_digest, seed.mutant.statement_digest))
    candidate = candidate_from_validation_record(record, case_id=case, evidence=(rebound,))
    _assert_unattested_pgir041_candidate_is_unknown(candidate)



def test_pgir041_direct_quarantined_candidate_has_no_admission_or_receipt():
    explicit = _fictional_admitted_pgir041_candidate()
    baseline = mine_hard_negatives((explicit,), positive_index=PositiveEquivalenceIndex())
    assert len(baseline.admitted) == 1
    assert baseline.admitted[0].example.training_eligible is True
    assert len(baseline.receipts) == 1
    quarantined = replace(explicit, disposition=NegativeDisposition.QUARANTINED)
    result = mine_hard_negatives((quarantined,), positive_index=PositiveEquivalenceIndex())
    assert result.admitted == ()
    assert result.rejected == ()
    assert len(result.unknown) == 1
    assert result.unknown[0].record.disposition is NegativeDisposition.QUARANTINED
    assert result.unknown[0].example.disposition is ExampleDisposition.QUARANTINED
    assert result.unknown[0].example.training_eligible is False
    assert result.unknown[0].receipt is None
    assert result.receipts == ()



def test_pgir041_invalid_pointer_escape_refuses_canonical_unknown_storage():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_fuzzing import collect_mutation_evidence
    record, label, case = _fictional_pgir041_record_and_label(MutationClass.OPERATOR)
    altered = replace(record.mutation, mutated_paths=("/formulas/0/operator~2",))
    recomputed = collect_mutation_evidence(altered, solver_outcome="disproved")
    assert recomputed.check.accepted is True
    assert recomputed.minimality_checked is False
    stale_claim = replace(record, mutation=altered, minimality_checked=True)
    candidate = candidate_from_validation_record(stale_claim, case_id=case, evidence=(label,))
    assert candidate.disposition is NegativeDisposition.UNKNOWN
    assert candidate.relationship is SemanticRelationship.UNKNOWN
    assert candidate.evidence == ()
    assert candidate.minimality_checked is False
    # The proposal is nontraining, but its malformed JSON pointer is also
    # refused by the canonical IRHardNegative record rather than persisted.
    with pytest.raises(TrainingContractValidationError):
        mine_hard_negatives((candidate,), positive_index=PositiveEquivalenceIndex())
