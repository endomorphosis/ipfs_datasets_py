"""Production contract tests for PGIR training examples and traces."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from ipfs_datasets_py.logic.formalization.training_contracts import (
    EvidenceStatus,
    ExampleDisposition,
    ExampleKind,
    IRCompilerTrace,
    IRDecompilerTrace,
    IRHardNegative,
    IRPositivePair,
    IRProofTrace,
    IRRoundTripTrace,
    IRTacticTrace,
    IRTrainingExample,
    IRTranslationTrace,
    LabelAuthority,
    LabelEvidence,
    LineageBinding,
    LogicFamily,
    MutationClass,
    NegativeDisposition,
    PreservationClass,
    ProducerKind,
    ProofOutcome,
    RepresentationKind,
    SemanticRelationship,
    StatementAuthority,
    StatementBinding,
    TacticOutcome,
    TacticStep,
    TacticStepOutcome,
    ToolBinding,
    TraceReference,
    TraceStatus,
    TrainingContractValidationError,
    training_contract_schema_versions,
    validate_training_example,
)
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
from ipfs_datasets_py.logic.ir_core.source_lineage import RightsDisposition

DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"
DIGEST_C = f"sha256:{'c' * 64}"
DIGEST_D = f"sha256:{'d' * 64}"
DIGEST_E = f"sha256:{'e' * 64}"
DIGEST_F = f"sha256:{'f' * 64}"
CID_A = "bafkreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _lineage(**changes: object) -> LineageBinding:
    values: dict[str, object] = {
        "corpus_manifest_id": "corpus:test-v1",
        "corpus_manifest_cid": CID_A,
        "lineage_graph_id": "lineage-graph:test-v1",
        "lineage_graph_cid": CID_A,
        "split_manifest_id": "split:test-v1",
        "split_manifest_digest": DIGEST_A,
        "split_name": "train",
        "lineage_group_ids": ("lineage:1", "lineage:2"),
        "rights_disposition": RightsDisposition.ADMITTED,
        "source_record_ids": ("source:1", "source:2"),
    }
    values.update(changes)
    return LineageBinding(**values)  # type: ignore[arg-type]


def _statement(
    name: str,
    digest: str,
    *,
    representation: RepresentationKind = RepresentationKind.SOURCE_TEXT,
    group: str = "lineage:1",
    source: str = "source:1",
) -> StatementBinding:
    return StatementBinding(
        statement_id=f"statement:{name}",
        statement_digest=digest,
        representation=representation,
        logic_family=LogicFamily.FIRST_ORDER,
        artifact_id=f"artifact:{name}",
        artifact_digest=digest,
        lineage_group_ids=(group,),
        source_record_ids=(source,),
        source_ref_ids=(f"source-ref:{name}",),
    )


def _tool(kind: ProducerKind, name: str) -> ToolBinding:
    return ToolBinding(
        tool_id=f"tool:{name}",
        tool_version="1.0",
        producer_kind=kind,
        config_digest=DIGEST_D,
        implementation_digest=DIGEST_E,
    )


def _relationship_evidence(
    left: StatementBinding,
    right: StatementBinding,
    relationship: SemanticRelationship = SemanticRelationship.EXACT,
    *,
    evidence_id: str = "evidence:relation",
    authority: LabelAuthority = LabelAuthority.CANONICAL_VALIDATOR,
    status: EvidenceStatus = EvidenceStatus.VERIFIED,
    independent: bool = False,
    result_authority: AuthorityKind | None = None,
) -> LabelEvidence:
    return LabelEvidence(
        evidence_id=evidence_id,
        evidence_digest=DIGEST_F,
        authority=authority,
        status=status,
        subject_statement_ids=(left.statement_id, right.statement_id),
        subject_statement_digests=(left.statement_digest, right.statement_digest),
        producer_id="checker:semantic",
        producer_version="1.0",
        independent=independent,
        relationship=relationship,
        result_authority=result_authority,
    )


def _proof_evidence(
    statement: StatementBinding, *, receipt_digest: str = DIGEST_B
) -> LabelEvidence:
    return LabelEvidence(
        evidence_id="evidence:proof",
        evidence_digest=receipt_digest,
        authority=LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        status=EvidenceStatus.VERIFIED,
        subject_statement_ids=(statement.statement_id,),
        subject_statement_digests=(statement.statement_digest,),
        producer_id="tool:kernel",
        producer_version="1.0",
        independent=True,
        result_authority=AuthorityKind.THEOREM_PROOF,
    )


def _compiler() -> IRCompilerTrace:
    source = _statement("source", DIGEST_A)
    target = _statement("ir", DIGEST_B, representation=RepresentationKind.CANONICAL_IR)
    return IRCompilerTrace(
        trace_id="trace:compiler",
        lineage=_lineage(),
        source=source,
        target=target,
        producer=_tool(ProducerKind.DETERMINISTIC_COMPILER, "compiler"),
        source_authority=StatementAuthority.SOURCE_ASSERTED,
        target_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        relationship=SemanticRelationship.EXACT,
        preservation=PreservationClass.LOSSLESS,
        status=TraceStatus.SUCCEEDED,
        evidence=(_relationship_evidence(source, target),),
    )


def _decompiler() -> IRDecompilerTrace:
    source = _statement("ir", DIGEST_B, representation=RepresentationKind.CANONICAL_IR)
    target = _statement("reconstructed", DIGEST_C)
    return IRDecompilerTrace(
        trace_id="trace:decompiler",
        lineage=_lineage(),
        source=source,
        target=target,
        producer=_tool(ProducerKind.DETERMINISTIC_DECOMPILER, "decompiler"),
        source_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        target_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        relationship=SemanticRelationship.EXACT,
        preservation=PreservationClass.LOSSLESS,
        status=TraceStatus.SUCCEEDED,
        evidence=(_relationship_evidence(source, target),),
    )


def _translation() -> IRTranslationTrace:
    source = _statement("ir", DIGEST_B, representation=RepresentationKind.CANONICAL_IR)
    target = _statement("prover", DIGEST_C, representation=RepresentationKind.PROVER_SYNTAX)
    evidence = _relationship_evidence(
        source,
        target,
        SemanticRelationship.TRANSLATION_EQUIVALENT,
        authority=LabelAuthority.INDEPENDENT_TRANSLATION_CHECKER,
        independent=True,
    )
    return IRTranslationTrace(
        trace_id="trace:translation",
        lineage=_lineage(),
        source=source,
        target=target,
        producer=_tool(ProducerKind.DETERMINISTIC_TRANSLATOR, "translator"),
        source_authority=StatementAuthority.CANONICALLY_VALIDATED,
        target_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        relationship=SemanticRelationship.TRANSLATION_EQUIVALENT,
        preservation=PreservationClass.SEMANTIC,
        status=TraceStatus.SUCCEEDED,
        evidence=(evidence,),
    )


def _round_trip() -> IRRoundTripTrace:
    forward = _compiler()
    reverse = _decompiler()
    assert forward.target is not None and reverse.target is not None
    evidence = _relationship_evidence(forward.source, reverse.target)
    return IRRoundTripTrace(
        trace_id="trace:round-trip",
        lineage=_lineage(),
        original=forward.source,
        reconstructed=reverse.target,
        forward=TraceReference.from_trace(forward),
        reverse=TraceReference.from_trace(reverse),
        relationship=SemanticRelationship.EXACT,
        preservation=PreservationClass.LOSSLESS,
        evidence=(evidence,),
    )


def _proof() -> IRProofTrace:
    statement = _statement("theorem", DIGEST_A, representation=RepresentationKind.PROVER_SYNTAX)
    return IRProofTrace(
        trace_id="trace:proof",
        lineage=_lineage(),
        statement=statement,
        claim_id="claim:1",
        claim_digest=DIGEST_A,
        obligation_id="obligation:1",
        obligation_digest=DIGEST_B,
        assumption_ids=("assumption:1",),
        assumption_digests=(DIGEST_C,),
        request_digest=DIGEST_D,
        attempt_digest=DIGEST_E,
        result_digest=DIGEST_F,
        output_digest=DIGEST_A,
        producer=_tool(ProducerKind.PROVER, "prover"),
        outcome=ProofOutcome.PROVED,
        evidence=(_proof_evidence(statement),),
        checker=_tool(ProducerKind.CHECKER, "kernel"),
        proof_receipt_digest=DIGEST_B,
    )


def _tactic() -> IRTacticTrace:
    statement = _statement("theorem", DIGEST_A, representation=RepresentationKind.PROOF_STATE)
    step = TacticStep(
        step_id="step:0",
        index=0,
        input_state_digest=DIGEST_A,
        tactic="intro; exact premise",
        output_state_digest=DIGEST_B,
        premise_statement_ids=("premise:1",),
        premise_statement_digests=(DIGEST_C,),
        outcome=TacticStepOutcome.SUCCEEDED,
    )
    return IRTacticTrace(
        trace_id="trace:tactic",
        lineage=_lineage(),
        statement=statement,
        obligation_id="obligation:1",
        obligation_digest=DIGEST_D,
        initial_state_digest=DIGEST_A,
        final_state_digest=DIGEST_B,
        producer=_tool(ProducerKind.TACTICIAN, "tactician"),
        steps=(step,),
        outcome=TacticOutcome.VERIFIED_SUCCESS,
        evidence=(_proof_evidence(statement, receipt_digest=DIGEST_E),),
        checker=_tool(ProducerKind.CHECKER, "kernel"),
        proof_trace_digest=DIGEST_E,
    )


def _positive() -> IRPositivePair:
    left = _statement("source", DIGEST_A)
    right = _statement("ir", DIGEST_B, representation=RepresentationKind.CANONICAL_IR)
    return IRPositivePair(
        pair_id="pair:1",
        lineage=_lineage(),
        left=left,
        right=right,
        left_authority=StatementAuthority.SOURCE_ASSERTED,
        right_authority=StatementAuthority.CANONICALLY_VALIDATED,
        relationship=SemanticRelationship.EXACT,
        equivalence_class_id="equivalence:1",
        evidence=(_relationship_evidence(left, right),),
    )


def _negative() -> IRHardNegative:
    original = _statement("source", DIGEST_A)
    mutant = _statement("mutant", DIGEST_C)
    evidence = _relationship_evidence(
        original,
        mutant,
        SemanticRelationship.NON_EQUIVALENT,
        authority=LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
        independent=True,
        result_authority=AuthorityKind.SATISFIABILITY,
    )
    return IRHardNegative(
        negative_id="negative:1",
        lineage=_lineage(),
        original=original,
        mutant=mutant,
        relationship=SemanticRelationship.NON_EQUIVALENT,
        mutation_class=MutationClass.NEGATION,
        mutated_paths=("/operator",),
        minimality_checked=True,
        disposition=NegativeDisposition.CONFIRMED_NEGATIVE,
        evidence=(evidence,),
    )


def _records() -> tuple[object, ...]:
    return (
        _lineage(),
        _statement("source", DIGEST_A),
        _tool(ProducerKind.DETERMINISTIC_COMPILER, "compiler"),
        _compiler().evidence[0],
        _compiler(),
        _decompiler(),
        _translation(),
        _round_trip(),
        _proof(),
        _tactic().steps[0],
        _tactic(),
        _positive(),
        _negative(),
        IRTrainingExample.classify(
            example_id="example:1",
            record=_positive(),
            selected_evidence_id="evidence:relation",
        ),
    )


@pytest.mark.parametrize("record", _records())
def test_all_contracts_round_trip_with_stable_content_identity(record: object) -> None:
    restored = type(record).from_json(record.to_json())  # type: ignore[attr-defined]

    assert restored == record
    assert restored.to_dict() == record.to_dict()  # type: ignore[attr-defined]
    assert restored.digest == record.digest  # type: ignore[attr-defined]
    assert restored.cid == record.cid  # type: ignore[attr-defined]
    assert record.digest.startswith("sha256:")  # type: ignore[attr-defined]
    assert record.cid.startswith("b")  # type: ignore[attr-defined]


def test_schema_registry_is_closed_and_complete() -> None:
    schemas = training_contract_schema_versions()

    assert len(schemas) == 15
    assert len(schemas) == len(set(schemas))
    assert all(item.startswith("ir-") and item.endswith("/v1") for item in schemas)


def test_unknown_fields_versions_families_relationships_and_authorities_fail() -> None:
    payload = _positive().to_dict()
    payload["surprise"] = True
    with pytest.raises(TrainingContractValidationError, match="unknown"):
        IRPositivePair.from_dict(payload)
    with pytest.raises(TrainingContractValidationError, match="schema"):
        replace(_positive(), schema_version="ir-positive-pair/v2")
    with pytest.raises(TrainingContractValidationError, match="logic_family"):
        replace(_statement("source", DIGEST_A), logic_family="invented")
    with pytest.raises(TrainingContractValidationError, match="relationship"):
        replace(_positive(), relationship="close_enough")
    with pytest.raises(TrainingContractValidationError, match="authority"):
        replace(_compiler().evidence[0], authority="model_says_true")


def test_immutable_and_set_like_bindings_have_order_independent_identity() -> None:
    lineage = _lineage()
    reversed_lineage = _lineage(
        lineage_group_ids=tuple(reversed(lineage.lineage_group_ids)),
        source_record_ids=tuple(reversed(lineage.source_record_ids)),
    )

    assert lineage == reversed_lineage
    assert lineage.cid == reversed_lineage.cid
    with pytest.raises(FrozenInstanceError):
        lineage.split_name = "test"  # type: ignore[misc]
    with pytest.raises(TypeError):
        IRTrainingExample.classify(
            example_id="example:immutable",
            record=_positive(),
            selected_evidence_id="evidence:relation",
            metadata={"nested": {"safe": True}},
        ).metadata["new"] = True  # type: ignore[index]


def test_positive_pair_is_symmetric_but_negative_and_translation_are_directional() -> None:
    pair = _positive()
    reversed_pair = replace(
        pair,
        left=pair.right,
        right=pair.left,
        left_authority=pair.right_authority,
        right_authority=pair.left_authority,
    )
    translation = _translation()
    assert translation.target is not None

    assert pair.cid == reversed_pair.cid
    with pytest.raises(TrainingContractValidationError, match="authority"):
        replace(
            translation,
            source_authority=StatementAuthority.MODEL_CANDIDATE,
            target_authority=StatementAuthority.CANONICALLY_VALIDATED,
        )
    assert _negative().original.statement_id != _negative().mutant.statement_id


def test_model_output_never_becomes_verified_or_admitted_truth() -> None:
    source = _statement("source", DIGEST_A)
    target = _statement("candidate", DIGEST_B)
    with pytest.raises(TrainingContractValidationError, match="cannot be verified"):
        _relationship_evidence(
            source,
            target,
            authority=LabelAuthority.MODEL_OUTPUT,
            status=EvidenceStatus.VERIFIED,
        )

    candidate = _relationship_evidence(
        source,
        target,
        authority=LabelAuthority.MODEL_OUTPUT,
        status=EvidenceStatus.CANDIDATE,
    )
    trace = IRCompilerTrace(
        trace_id="trace:model-candidate",
        lineage=_lineage(),
        source=source,
        target=target,
        producer=ToolBinding(
            tool_id="tool:model",
            tool_version="1.0",
            producer_kind=ProducerKind.MODEL,
            config_digest=DIGEST_C,
            implementation_digest=DIGEST_D,
            model_checkpoint_id="checkpoint:1",
            model_checkpoint_digest=DIGEST_E,
        ),
        source_authority=StatementAuthority.SOURCE_ASSERTED,
        target_authority=StatementAuthority.MODEL_CANDIDATE,
        relationship=SemanticRelationship.EXACT,
        preservation=PreservationClass.LOSSLESS,
        status=TraceStatus.SUCCEEDED,
        evidence=(candidate,),
    )
    example = IRTrainingExample.classify(
        example_id="example:model", record=trace, selected_evidence_id=candidate.evidence_id
    )

    assert example.disposition is ExampleDisposition.QUARANTINED
    assert not example.training_eligible
    with pytest.raises(TrainingContractValidationError, match="inadmissible"):
        replace(example, disposition=ExampleDisposition.ADMITTED, quarantine_reasons=())


def test_unresolved_loss_cannot_be_serialized_as_exact() -> None:
    with pytest.raises(TrainingContractValidationError, match="relationship|unresolved"):
        replace(
            _translation(), relationship=SemanticRelationship.EXACT, unresolved_losses=("modality",)
        )
    with pytest.raises(TrainingContractValidationError, match="lossless"):
        replace(
            _translation(), preservation=PreservationClass.LOSSLESS, unresolved_losses=("scope",)
        )


def test_failed_and_timeout_traces_remain_serializable_but_quarantined() -> None:
    source = _statement("source", DIGEST_A)
    trace = IRCompilerTrace(
        trace_id="trace:timeout",
        lineage=_lineage(),
        source=source,
        target=None,
        producer=_tool(ProducerKind.DETERMINISTIC_COMPILER, "compiler"),
        source_authority=StatementAuthority.SOURCE_ASSERTED,
        target_authority=StatementAuthority.UNKNOWN,
        relationship=SemanticRelationship.UNKNOWN,
        preservation=PreservationClass.UNKNOWN,
        status=TraceStatus.TIMED_OUT,
        diagnostics=("bounded timeout",),
    )
    example = IRTrainingExample.classify(example_id="example:timeout", record=trace)

    assert IRCompilerTrace.from_json(trace.to_json()) == trace
    assert example.disposition is ExampleDisposition.QUARANTINED
    assert {item.value for item in example.quarantine_reasons} >= {
        "trace_not_succeeded",
        "unknown_relationship",
        "unverified_evidence",
    }


def test_cross_statement_proof_binding_and_authority_substitution_fail_closed() -> None:
    proof = _proof()
    other = _statement("other", DIGEST_B, representation=RepresentationKind.PROVER_SYNTAX)
    with pytest.raises(TrainingContractValidationError, match="another statement"):
        replace(proof, statement=other)
    with pytest.raises(TrainingContractValidationError, match="result authority|theorem_proof"):
        replace(
            proof.evidence[0],
            result_authority=AuthorityKind.SATISFIABILITY,
        )
    with pytest.raises(TrainingContractValidationError, match="receipt"):
        replace(proof, proof_receipt_digest="")


def test_unknown_timeout_or_unchecked_outcome_cannot_confirm_hard_negative() -> None:
    negative = _negative()
    unchecked = replace(
        negative.evidence[0],
        authority=LabelAuthority.TOOL_CANDIDATE,
        status=EvidenceStatus.UNKNOWN,
        independent=False,
        result_authority=None,
    )
    with pytest.raises(TrainingContractValidationError, match="independently checked"):
        replace(negative, evidence=(unchecked,))

    unknown = replace(
        negative,
        relationship=SemanticRelationship.UNKNOWN,
        disposition=NegativeDisposition.UNKNOWN,
        minimality_checked=False,
        evidence=(),
    )
    example = IRTrainingExample.classify(example_id="example:unknown-negative", record=unknown)
    assert example.disposition is ExampleDisposition.QUARANTINED
    assert not example.training_eligible


def test_round_trip_and_tactic_steps_bind_ordered_contiguous_state() -> None:
    round_trip = _round_trip()
    with pytest.raises(TrainingContractValidationError, match="contiguous|embedded trace"):
        replace(round_trip, reverse=replace(round_trip.reverse, source_statement_digest=DIGEST_D))

    tactic = _tactic()
    bad_step = replace(tactic.steps[0], index=1)
    with pytest.raises(TrainingContractValidationError, match="indices"):
        replace(tactic, steps=(bad_step,))
    with pytest.raises(TrainingContractValidationError, match="proof authority"):
        replace(
            tactic,
            outcome=TacticOutcome.CANDIDATE_SUCCESS,
            checker=None,
        )


def test_wrapper_kind_selected_evidence_rights_split_and_metadata_are_bound() -> None:
    admitted = IRTrainingExample.classify(
        example_id="example:admitted",
        record=_positive(),
        selected_evidence_id="evidence:relation",
    )
    assert admitted.training_eligible
    assert validate_training_example(admitted.to_dict()) == admitted
    with pytest.raises(TrainingContractValidationError, match="requires IRProofTrace"):
        replace(admitted, kind=ExampleKind.PROOF)
    with pytest.raises(TrainingContractValidationError, match="not embedded"):
        IRTrainingExample.classify(
            example_id="example:missing-evidence",
            record=_positive(),
            selected_evidence_id="evidence:missing",
        )
    with pytest.raises(TrainingContractValidationError, match="float-valued"):
        IRTrainingExample.classify(
            example_id="example:float",
            record=_positive(),
            selected_evidence_id="evidence:relation",
            metadata={"confidence": 0.99},
        )

    rights_blocked = replace(
        _positive(),
        lineage=_lineage(rights_disposition=RightsDisposition.QUARANTINED),
    )
    split_blocked = replace(_positive(), lineage=_lineage(split_name="hidden-test"))
    assert not IRTrainingExample.classify(
        example_id="example:rights",
        record=rights_blocked,
        selected_evidence_id="evidence:relation",
    ).training_eligible
    assert not IRTrainingExample.classify(
        example_id="example:split",
        record=split_blocked,
        selected_evidence_id="evidence:relation",
    ).training_eligible
