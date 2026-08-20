"""Adversarial and golden-vector tests for PGIR training contracts."""

from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from ipfs_datasets_py.logic.formalization.training_contracts import (
    EvidenceStatus,
    ExampleDisposition,
    IRCompilerTrace,
    IRDecompilerTrace,
    IRPositivePair,
    IRProofTrace,
    IRRoundTripTrace,
    IRTacticTrace,
    IRTrainingExample,
    LabelAuthority,
    LabelEvidence,
    LineageBinding,
    LogicFamily,
    PreservationClass,
    ProducerKind,
    ProofOutcome,
    QuarantineReason,
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
    kwargs: dict[str, object] = {}
    if kind is ProducerKind.MODEL:
        kwargs = {
            "model_checkpoint_id": "checkpoint:1",
            "model_checkpoint_digest": DIGEST_F,
        }
    return ToolBinding(
        tool_id=f"tool:{name}",
        tool_version="1.0",
        producer_kind=kind,
        config_digest=DIGEST_D,
        implementation_digest=DIGEST_E,
        **kwargs,  # type: ignore[arg-type]
    )


def _relationship_evidence(
    left: StatementBinding,
    right: StatementBinding,
    relationship: SemanticRelationship = SemanticRelationship.EXACT,
    *,
    evidence_id: str = "evidence:relation",
    evidence_digest: str = DIGEST_F,
    authority: LabelAuthority = LabelAuthority.CANONICAL_VALIDATOR,
    independent: bool = False,
    result_authority: AuthorityKind | None = None,
    producer_id: str = "tool:semantic-checker",
) -> LabelEvidence:
    return LabelEvidence(
        evidence_id=evidence_id,
        evidence_digest=evidence_digest,
        authority=authority,
        status=EvidenceStatus.VERIFIED,
        subject_statement_ids=(left.statement_id, right.statement_id),
        subject_statement_digests=(left.statement_digest, right.statement_digest),
        producer_id=producer_id,
        producer_version="1.0",
        independent=independent,
        relationship=relationship,
        result_authority=result_authority,
    )


def _positive() -> IRPositivePair:
    left = _statement("left", DIGEST_A, group="lineage:1", source="source:1")
    right = _statement("right", DIGEST_B, group="lineage:2", source="source:2")
    return IRPositivePair(
        pair_id="pair:adversarial",
        lineage=_lineage(),
        left=left,
        right=right,
        left_authority=StatementAuthority.SOURCE_ASSERTED,
        right_authority=StatementAuthority.CANONICALLY_VALIDATED,
        relationship=SemanticRelationship.EXACT,
        equivalence_class_id="equivalence:adversarial",
        evidence=(_relationship_evidence(left, right),),
    )


def _proof_evidence(
    statement: StatementBinding,
    *,
    receipt_digest: str = DIGEST_B,
    evidence_id: str = "evidence:proof",
    producer_id: str = "tool:kernel",
) -> LabelEvidence:
    return LabelEvidence(
        evidence_id=evidence_id,
        evidence_digest=receipt_digest,
        authority=LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        status=EvidenceStatus.VERIFIED,
        subject_statement_ids=(statement.statement_id,),
        subject_statement_digests=(statement.statement_digest,),
        producer_id=producer_id,
        producer_version="1.0",
        independent=True,
        result_authority=AuthorityKind.THEOREM_PROOF,
    )


def _proof() -> IRProofTrace:
    statement = _statement("theorem", DIGEST_A, representation=RepresentationKind.PROVER_SYNTAX)
    return IRProofTrace(
        trace_id="trace:proof-adversarial",
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


def _compiler_round_trip() -> tuple[IRCompilerTrace, IRDecompilerTrace, IRRoundTripTrace]:
    original = _statement("original", DIGEST_A)
    middle = _statement("middle", DIGEST_B, representation=RepresentationKind.CANONICAL_IR)
    reconstructed = _statement("reconstructed", DIGEST_C)
    forward = IRCompilerTrace(
        trace_id="trace:forward",
        lineage=_lineage(),
        source=original,
        target=middle,
        producer=_tool(ProducerKind.DETERMINISTIC_COMPILER, "compiler"),
        source_authority=StatementAuthority.SOURCE_ASSERTED,
        target_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        relationship=SemanticRelationship.EXACT,
        preservation=PreservationClass.LOSSLESS,
        status=TraceStatus.SUCCEEDED,
        evidence=(_relationship_evidence(original, middle),),
    )
    reverse = IRDecompilerTrace(
        trace_id="trace:reverse",
        lineage=_lineage(),
        source=middle,
        target=reconstructed,
        producer=_tool(ProducerKind.DETERMINISTIC_DECOMPILER, "decompiler"),
        source_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        target_authority=StatementAuthority.DETERMINISTICALLY_DERIVED,
        relationship=SemanticRelationship.EXACT,
        preservation=PreservationClass.LOSSLESS,
        status=TraceStatus.SUCCEEDED,
        evidence=(_relationship_evidence(middle, reconstructed),),
    )
    round_trip = IRRoundTripTrace(
        trace_id="trace:round-trip-adversarial",
        lineage=_lineage(),
        original=original,
        reconstructed=reconstructed,
        forward=TraceReference.from_trace(forward),
        reverse=TraceReference.from_trace(reverse),
        relationship=SemanticRelationship.EXACT,
        preservation=PreservationClass.LOSSLESS,
        evidence=(_relationship_evidence(original, reconstructed),),
    )
    return forward, reverse, round_trip


def test_subject_bindings_preserve_id_digest_pairs_and_allow_shared_content() -> None:
    pair = _positive()
    swapped = LabelEvidence(
        evidence_id="evidence:swapped",
        evidence_digest=DIGEST_F,
        authority=LabelAuthority.CANONICAL_VALIDATOR,
        status=EvidenceStatus.VERIFIED,
        subject_statement_ids=(pair.left.statement_id, pair.right.statement_id),
        subject_statement_digests=(
            pair.right.statement_digest,
            pair.left.statement_digest,
        ),
        producer_id="tool:semantic-checker",
        producer_version="1.0",
        independent=False,
        relationship=SemanticRelationship.EXACT,
    )
    with pytest.raises(TrainingContractValidationError, match="another statement"):
        replace(pair, evidence=(swapped,))

    left = _statement("duplicate-left", DIGEST_C)
    right = _statement("duplicate-right", DIGEST_C)
    shared = _relationship_evidence(left, right)
    duplicate_content_pair = replace(pair, left=left, right=right, evidence=(shared,))
    assert duplicate_content_pair.evidence[0].subject_statement_digests == (
        DIGEST_C,
        DIGEST_C,
    )


def test_exact_relationship_rejects_equisatisfiable_preservation() -> None:
    forward, _, _ = _compiler_round_trip()
    with pytest.raises(TrainingContractValidationError, match="non-exact loss"):
        replace(forward, preservation=PreservationClass.EQUISATISFIABLE)


def test_strict_wire_decoding_rejects_missing_and_falsey_wrong_types() -> None:
    forward, _, _ = _compiler_round_trip()
    payload = forward.to_dict()
    del payload["status"]
    with pytest.raises(TrainingContractValidationError, match="missing.*status"):
        IRCompilerTrace.from_dict(payload)

    evidence_payload = forward.evidence[0].to_dict()
    evidence_payload["result_authority"] = False
    with pytest.raises(TrainingContractValidationError, match="result_authority"):
        LabelEvidence.from_dict(evidence_payload)

    with pytest.raises(TrainingContractValidationError, match="metadata must be a mapping"):
        IRTrainingExample.classify(
            example_id="example:falsey-metadata",
            record=_positive(),
            selected_evidence_id="evidence:relation",
            metadata=[],  # type: ignore[arg-type]
        )


def test_model_transform_cannot_claim_derived_authority_and_stays_quarantined() -> None:
    source = _statement("model-source", DIGEST_A)
    target = _statement("model-target", DIGEST_B)
    evidence = _relationship_evidence(
        source,
        target,
        authority=LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
        independent=True,
    )
    values = {
        "trace_id": "trace:model",
        "lineage": _lineage(),
        "source": source,
        "target": target,
        "producer": _tool(ProducerKind.MODEL, "model"),
        "source_authority": StatementAuthority.SOURCE_ASSERTED,
        "target_authority": StatementAuthority.MODEL_CANDIDATE,
        "relationship": SemanticRelationship.EXACT,
        "preservation": PreservationClass.LOSSLESS,
        "status": TraceStatus.SUCCEEDED,
        "evidence": (evidence,),
    }
    trace = IRCompilerTrace(**values)  # type: ignore[arg-type]
    example = IRTrainingExample.classify(
        example_id="example:model-verified",
        record=trace,
        selected_evidence_id=evidence.evidence_id,
    )
    assert example.disposition is ExampleDisposition.QUARANTINED
    assert QuarantineReason.CANDIDATE_STATEMENT_AUTHORITY in example.quarantine_reasons
    with pytest.raises(TrainingContractValidationError, match="model transformations"):
        IRCompilerTrace(
            **{**values, "target_authority": StatementAuthority.DETERMINISTICALLY_DERIVED}
        )  # type: ignore[arg-type]


def test_wrapper_reasons_are_exact_and_record_types_are_closed() -> None:
    pair = _positive()
    admitted = IRTrainingExample.classify(
        example_id="example:clean",
        record=pair,
        selected_evidence_id="evidence:relation",
    )
    with pytest.raises(TrainingContractValidationError, match="inapplicable"):
        replace(
            admitted,
            disposition=ExampleDisposition.QUARANTINED,
            quarantine_reasons=(QuarantineReason.UNKNOWN_LOGIC_FAMILY,),
        )
    policy_quarantine = replace(
        admitted,
        disposition=ExampleDisposition.QUARANTINED,
        quarantine_reasons=(QuarantineReason.POLICY,),
    )
    assert not policy_quarantine.training_eligible

    class DerivedPositive(IRPositivePair):
        pass

    derived = DerivedPositive.from_dict(pair.to_dict())
    with pytest.raises(TrainingContractValidationError, match="requires IRPositivePair"):
        IRTrainingExample.classify(
            example_id="example:subclass",
            record=derived,
            selected_evidence_id="evidence:relation",
        )


def test_independent_lineages_form_a_symmetric_admitted_positive_pair() -> None:
    pair = _positive()
    reversed_pair = replace(
        pair,
        left=pair.right,
        right=pair.left,
        left_authority=pair.right_authority,
        right_authority=pair.left_authority,
    )
    admitted = IRTrainingExample.classify(
        example_id="example:independent-lineages",
        record=pair,
        selected_evidence_id="evidence:relation",
    )
    assert pair.cid == reversed_pair.cid
    assert pair.left.lineage_group_ids != pair.right.lineage_group_ids
    assert admitted.training_eligible


def test_proof_checker_receipt_and_selected_evidence_are_exactly_bound() -> None:
    proof = _proof()
    with pytest.raises(TrainingContractValidationError, match="theorem-proof evidence"):
        replace(proof, checker=_tool(ProducerKind.CHECKER, "other-kernel"))
    with pytest.raises(TrainingContractValidationError, match="theorem-proof evidence"):
        replace(proof, proof_receipt_digest=DIGEST_C)

    rogue = _proof_evidence(
        proof.statement,
        receipt_digest=DIGEST_C,
        evidence_id="evidence:rogue-proof",
        producer_id="tool:other-kernel",
    )
    multi = replace(proof, evidence=(proof.evidence[0], rogue))
    example = IRTrainingExample.classify(
        example_id="example:rogue-selection",
        record=multi,
        selected_evidence_id=rogue.evidence_id,
    )
    assert example.disposition is ExampleDisposition.QUARANTINED
    assert QuarantineReason.UNVERIFIED_PROOF in example.quarantine_reasons


def test_timeout_proof_round_trips_without_result_and_cannot_retain_proof() -> None:
    proof = _proof()
    timeout = replace(
        proof,
        outcome=ProofOutcome.TIMED_OUT,
        result_digest="",
        output_digest="",
        evidence=(),
        checker=None,
        proof_receipt_digest="",
        diagnostics=("bounded timeout",),
    )
    example = IRTrainingExample.classify(example_id="example:proof-timeout", record=timeout)
    assert IRProofTrace.from_json(timeout.to_json()) == timeout
    assert example.disposition is ExampleDisposition.QUARANTINED

    payload = timeout.to_dict()
    del payload["outcome"]
    with pytest.raises(TrainingContractValidationError, match="missing.*outcome"):
        IRProofTrace.from_dict(payload)
    with pytest.raises(TrainingContractValidationError, match="proof receipt"):
        replace(timeout, proof_receipt_digest=DIGEST_B)
    with pytest.raises(TrainingContractValidationError, match="verified proof label"):
        replace(timeout, evidence=proof.evidence)


def test_disproof_requires_counterexample_authority_bound_to_output() -> None:
    proof = _proof()
    with pytest.raises(TrainingContractValidationError, match="negative evidence"):
        replace(
            proof,
            outcome=ProofOutcome.DISPROVED,
            proof_receipt_digest="",
            output_digest=DIGEST_B,
        )

    counterexample = LabelEvidence(
        evidence_id="evidence:counterexample",
        evidence_digest=DIGEST_C,
        authority=LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
        status=EvidenceStatus.VERIFIED,
        subject_statement_ids=(proof.statement.statement_id,),
        subject_statement_digests=(proof.statement.statement_digest,),
        producer_id="tool:kernel",
        producer_version="1.0",
        independent=True,
        result_authority=AuthorityKind.SATISFIABILITY,
    )
    disproved = replace(
        proof,
        outcome=ProofOutcome.DISPROVED,
        evidence=(counterexample,),
        proof_receipt_digest="",
        output_digest=DIGEST_C,
    )
    assert disproved.outcome is ProofOutcome.DISPROVED


def test_tactic_retries_preserve_state_and_verified_evidence_cannot_be_swapped() -> None:
    statement = _statement(
        "tactic-theorem", DIGEST_A, representation=RepresentationKind.PROOF_STATE
    )
    failed = TacticStep(
        step_id="step:0",
        index=0,
        input_state_digest=DIGEST_A,
        tactic="bad tactic",
        output_state_digest="",
        premise_statement_ids=(),
        premise_statement_digests=(),
        outcome=TacticStepOutcome.FAILED,
    )
    retry = TacticStep(
        step_id="step:1",
        index=1,
        input_state_digest=DIGEST_A,
        tactic="exact premise",
        output_state_digest=DIGEST_B,
        premise_statement_ids=("premise:1",),
        premise_statement_digests=(DIGEST_C,),
        outcome=TacticStepOutcome.SUCCEEDED,
    )
    candidate = IRTacticTrace(
        trace_id="trace:tactic-retry",
        lineage=_lineage(),
        statement=statement,
        obligation_id="obligation:tactic",
        obligation_digest=DIGEST_C,
        initial_state_digest=DIGEST_A,
        final_state_digest=DIGEST_B,
        producer=_tool(ProducerKind.TACTICIAN, "tactician"),
        steps=(failed, retry),
        outcome=TacticOutcome.CANDIDATE_SUCCESS,
    )
    assert IRTacticTrace.from_json(candidate.to_json()) == candidate
    with pytest.raises(TrainingContractValidationError, match="successful final step"):
        replace(candidate, steps=(), final_state_digest=DIGEST_A)

    valid = _proof_evidence(statement, receipt_digest=DIGEST_D)
    verified = replace(
        candidate,
        outcome=TacticOutcome.VERIFIED_SUCCESS,
        evidence=(valid,),
        checker=_tool(ProducerKind.CHECKER, "kernel"),
        proof_trace_digest=DIGEST_D,
    )
    rogue = _proof_evidence(
        statement,
        receipt_digest=DIGEST_E,
        evidence_id="evidence:rogue-tactic-proof",
        producer_id="tool:other-kernel",
    )
    multi = replace(verified, evidence=(valid, rogue))
    example = IRTrainingExample.classify(
        example_id="example:rogue-tactic-selection",
        record=multi,
        selected_evidence_id=rogue.evidence_id,
    )
    assert example.disposition is ExampleDisposition.QUARANTINED
    assert QuarantineReason.UNVERIFIED_TACTIC in example.quarantine_reasons


def test_round_trip_binds_lineage_root_and_failed_stages_never_admit() -> None:
    forward, _, round_trip = _compiler_round_trip()
    with pytest.raises(TrainingContractValidationError, match="lineage|embedded trace"):
        replace(
            round_trip,
            forward=replace(round_trip.forward, lineage_digest=DIGEST_D),
        )

    relationship = SemanticRelationship.LOGICALLY_EQUIVALENT
    assert forward.target is not None
    failed_forward = replace(
        forward,
        status=TraceStatus.FAILED,
        relationship=relationship,
        preservation=PreservationClass.SEMANTIC,
        evidence=(_relationship_evidence(forward.source, forward.target, relationship),),
    )
    failed = replace(
        round_trip,
        forward=TraceReference.from_trace(failed_forward),
        relationship=relationship,
        preservation=PreservationClass.SEMANTIC,
        evidence=(
            _relationship_evidence(
                round_trip.original,
                round_trip.reconstructed,
                relationship,
            ),
        ),
    )
    example = IRTrainingExample.classify(
        example_id="example:failed-round-trip",
        record=failed,
        selected_evidence_id="evidence:relation",
    )
    assert example.disposition is ExampleDisposition.QUARANTINED
    assert QuarantineReason.TRACE_NOT_SUCCEEDED in example.quarantine_reasons


def test_result_authority_families_are_non_interchangeable() -> None:
    pair = _positive()
    with pytest.raises(TrainingContractValidationError, match="cannot substitute"):
        _relationship_evidence(
            pair.left,
            pair.right,
            authority=LabelAuthority.INDEPENDENT_TRANSLATION_CHECKER,
            independent=True,
            result_authority=AuthorityKind.RUNTIME_MONITOR,
        )
    with pytest.raises(TrainingContractValidationError, match="cannot substitute"):
        _relationship_evidence(
            pair.left,
            pair.right,
            authority=LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
            independent=True,
            result_authority=AuthorityKind.POLICY_APPROVAL,
        )


def test_non_string_mapping_keys_and_duplicate_json_fields_fail_closed() -> None:
    lineage = _lineage()
    with pytest.raises(TrainingContractValidationError, match="field names must be strings"):
        LineageBinding.from_dict({1: "not-a-field"})  # type: ignore[dict-item]

    duplicate = lineage.to_json().replace(
        '"split_name":"train"',
        '"split_name":"train","split_name":"test"',
    )
    with pytest.raises(TrainingContractValidationError, match="duplicate JSON object field"):
        LineageBinding.from_json(duplicate)


@settings(max_examples=8, deadline=None)
@given(reverse_groups=st.booleans(), reverse_sources=st.booleans())
def test_lineage_identity_property_is_set_order_independent(
    reverse_groups: bool, reverse_sources: bool
) -> None:
    baseline = _lineage()
    groups = baseline.lineage_group_ids[::-1] if reverse_groups else baseline.lineage_group_ids
    sources = baseline.source_record_ids[::-1] if reverse_sources else baseline.source_record_ids
    permuted = _lineage(lineage_group_ids=groups, source_record_ids=sources)
    assert permuted.canonical_bytes() == baseline.canonical_bytes()
    assert permuted.digest == baseline.digest
    assert permuted.cid == baseline.cid


def test_lineage_identity_has_a_fixed_golden_digest_and_cid() -> None:
    lineage = _lineage()
    assert (
        lineage.digest == "sha256:b85f3ae3d51ab3781590413dbc1f101b3cab86612fd3a0e2d4599d2b87d223b5"
    )
    assert lineage.cid == "bafkreifyl45ohvi2wn4blecbhw6b6ea3hsvymyjp2oqofvcztuvypurdwu"
    assert b'"/lineage_group_ids":"set-like"' in lineage.canonical_bytes()
