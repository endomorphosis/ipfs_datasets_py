"""Semantic recompilation gate tests for PGIR-022."""

from __future__ import annotations

from ipfs_datasets_py.logic.bridge.translation import (
    EqualityCriterion,
    FidelityClaim,
    ReconstructionMode,
    TranslationPreservationClass,
)
from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalAtomVocabulary,
    CanonicalRoundTripIR,
    CanonicalRule,
    CompilerRequest,
    DecompilerRequest,
    OperationStatus,
)
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
    SourceWithheldCanonicalDecompiler,
)
from ipfs_datasets_py.logic.bridge.recompilation import (
    classify_ir_preservation,
    compare_canonical_semantics,
    evaluate_semantic_recompilation_gate,
    paraphrase_without_recompilation_is_not_fidelity,
    recorded_roundtrip_equality_criteria,
    run_with_preservation,
)
from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import (
    CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID,
    CanonicalSemanticRoundTrip,
    CanonicalSemanticRoundTripResult,
    measured_parity_compiler_request,
    roundtrip_configuration,
)


def _vocabulary() -> CanonicalAtomVocabulary:
    return CanonicalAtomVocabulary(
        actors=("company_a", "agency"),
        actions=("file", "submit", "publish"),
        objects=("annual_report", "backup_report", "notice"),
        qualifiers=("public_interest", "emergency", "within_10_days"),
    )


def _obligation() -> CanonicalRoundTripIR:
    return CanonicalRoundTripIR(
        (
            CanonicalRule(
                modality="O",
                actor="company_a",
                action="file",
                object="annual_report",
            ),
        )
    )


def test_measured_roundtrip_configuration_cid_is_unchanged() -> None:
    payload = roundtrip_configuration()
    assert payload["interface"] == "CanonicalSemanticRoundTrip@1"
    assert payload["decompiler"]["source_withheld"] is True
    from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

    assert cid_for_dag_json(payload) == CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID


def test_paraphrase_without_recompilation_cannot_claim_fidelity() -> None:
    ir = _obligation()
    request = DecompilerRequest(canonical_ir=ir, request_id="no-gate")
    result = SourceWithheldCanonicalDecompiler().decompile(request)
    receipt = paraphrase_without_recompilation_is_not_fidelity(request, result)
    assert receipt.fidelity_claim is FidelityClaim.NONE
    assert receipt.preservation_class is TranslationPreservationClass.HEURISTIC
    assert receipt.recompilation_cid is None


def test_identical_irs_are_lossless_and_polarity_drift_is_heuristic() -> None:
    left = _obligation()
    same = CanonicalRoundTripIR(left.rules)
    flipped = CanonicalRoundTripIR(
        (
            CanonicalRule(
                modality="F",
                actor="company_a",
                action="file",
                object="annual_report",
            ),
        )
    )
    narrowed = CanonicalRoundTripIR(left.rules)
    extra = CanonicalRoundTripIR(
        (
            *left.rules,
            CanonicalRule(
                modality="P",
                actor="agency",
                action="publish",
                object="notice",
            ),
        )
    )
    dropped = CanonicalRoundTripIR(
        (
            CanonicalRule(
                modality="P",
                actor="agency",
                action="publish",
                object="notice",
            ),
        )
    )

    assert classify_ir_preservation(left, same) == (
        TranslationPreservationClass.LOSSLESS,
        (),
    )
    klass, loss = classify_ir_preservation(left, extra)
    assert klass is TranslationPreservationClass.OVER_APPROXIMATION
    assert loss
    klass, loss = classify_ir_preservation(extra, narrowed)
    assert klass is TranslationPreservationClass.UNDER_APPROXIMATION
    klass, loss = classify_ir_preservation(left, flipped)
    assert klass is TranslationPreservationClass.HEURISTIC
    assert "changed_polarity" in set(loss) | {
        item["kind"] for item in compare_canonical_semantics(left, flipped)
    }
    assert classify_ir_preservation(left, dropped)[0] is TranslationPreservationClass.HEURISTIC


def test_gate_admits_only_after_successful_semantic_recompilation() -> None:
    request = measured_parity_compiler_request(
        "Company A shall submit backup report within 10 days unless emergency.",
        request_id="gate-success",
        atom_vocabulary=CanonicalAtomVocabulary(
            actors=("company_a",),
            actions=("submit",),
            objects=("backup_report",),
            qualifiers=("emergency", "within_10_days"),
        ),
    )
    gate = run_with_preservation(request)

    assert gate.roundtrip.status is OperationStatus.SUCCESS
    assert gate.l1_ir_cid == gate.l2_ir_cid
    assert gate.admitted is True
    assert gate.preservation_class is TranslationPreservationClass.LOSSLESS
    assert gate.fidelity_claim is FidelityClaim.SEMANTIC
    assert EqualityCriterion.SEMANTIC_RECOMPILE in gate.equality_criteria
    assert EqualityCriterion.EXACT_IR_CID in gate.equality_criteria
    assert gate.receipt is not None
    assert gate.receipt.recompilation_cid == gate.roundtrip.result_cid
    assert gate.receipt.semantic_comparison_cid == gate.comparison_cid
    assert gate.fidelity_claim is not FidelityClaim.PROOF
    encoded = gate.to_dict()
    assert encoded["admitted"] is True
    assert "A4-CNL-001" in encoded["recorded_directions"]


def test_incomplete_cycle_is_not_admitted() -> None:
    request = CompilerRequest(
        source_text="This paragraph contains no normative rule.",
        request_id="gate-empty",
        atom_vocabulary=_vocabulary(),
    )
    result = CanonicalSemanticRoundTrip().run(request)
    gate = evaluate_semantic_recompilation_gate(result)

    assert result.status is not OperationStatus.SUCCESS
    assert gate.admitted is False
    assert gate.fidelity_claim is FidelityClaim.NONE
    assert gate.receipt is None
    assert "incomplete_recompilation" in gate.declared_loss


def test_recorded_directions_cover_every_required_equality_criterion_name() -> None:
    recorded = recorded_roundtrip_equality_criteria()
    assert recorded["A4-CNL-001"][-1] == "exact_ir_cid" or "semantic_recompile" in recorded[
        "A4-CNL-001"
    ]
    assert "unsupported" in recorded["A4-TYPED-002"]
    assert "ast_identity" in recorded["A4-PROVER-001"]
    for criteria in recorded.values():
        assert criteria


def test_compiler_and_decompiler_remain_the_measured_authorities() -> None:
    request = measured_parity_compiler_request(
        "Agency shall publish notice.",
        request_id="authority",
        atom_vocabulary=CanonicalAtomVocabulary(
            actors=("agency",),
            actions=("publish",),
            objects=("notice",),
        ),
    )
    compiled = TypedDeonticCanonicalCompiler().compile(request)
    assert compiled.status is OperationStatus.SUCCESS
    assert compiled.canonical_ir is not None
    realized = SourceWithheldCanonicalDecompiler().decompile(
        DecompilerRequest(
            canonical_ir=compiled.canonical_ir,
            request_id="authority:t1",
        )
    )
    assert realized.status is OperationStatus.SUCCESS
    cycle = CanonicalSemanticRoundTrip().run(request)
    assert isinstance(cycle, CanonicalSemanticRoundTripResult)
    assert cycle.status is OperationStatus.SUCCESS
    assert cycle.l1_result is not None
    assert cycle.l1_result.canonical_ir is not None
    assert cycle.l1_result.canonical_ir.ir_cid == compiled.canonical_ir.ir_cid
