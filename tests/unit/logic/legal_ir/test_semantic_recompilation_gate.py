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


def _same_predicate_modal_rules() -> tuple[CanonicalRule, CanonicalRule]:
    return (
        CanonicalRule("O", "agency", "file", "notice", conditions=("public_interest",)),
        CanonicalRule("P", "agency", "file", "notice", conditions=("emergency",)),
    )


def test_identical_same_predicate_modal_rules_have_no_differences() -> None:
    rules = _same_predicate_modal_rules()
    left = CanonicalRoundTripIR(rules)
    right = CanonicalRoundTripIR.from_dict(left.to_dict())
    assert left.ir_cid == right.ir_cid
    assert compare_canonical_semantics(left, right) == ()
    assert classify_ir_preservation(left, right) == (TranslationPreservationClass.LOSSLESS, ())


def test_dropped_rule_keeps_unchanged_sibling_polarity() -> None:
    unchanged, removed = _same_predicate_modal_rules()
    full = CanonicalRoundTripIR((unchanged, removed))
    remaining = CanonicalRoundTripIR((unchanged,))
    differences = compare_canonical_semantics(full, remaining)
    assert [row["kind"] for row in differences] == ["ir_cid_mismatch", "rule_set_mismatch", "dropped_rule"]
    assert differences[-1]["rule_cid"] == removed.rule_cid
    assert classify_ir_preservation(full, remaining) == (
        TranslationPreservationClass.UNDER_APPROXIMATION,
        (removed.rule_cid,),
    )


def test_one_changed_qualifier_is_matched_after_unchanged_sibling() -> None:
    obligation, permission = _same_predicate_modal_rules()
    changed = CanonicalRule("O", "agency", "file", "notice", conditions=("approval",))
    before = CanonicalRoundTripIR((obligation, permission))
    after = CanonicalRoundTripIR((changed, permission))
    differences = compare_canonical_semantics(before, after)
    assert [row["kind"] for row in differences] == [
        "ir_cid_mismatch", "rule_set_mismatch", "changed_qualifiers",
    ]
    assert differences[-1] == {
        "kind": "changed_qualifiers", "facet": "conditions",
        "added": ["approval"], "dropped": ["public_interest"], "rule_cid": changed.rule_cid,
    }


def test_ambiguous_unmatched_siblings_are_not_paired_speculatively() -> None:
    before = CanonicalRoundTripIR(_same_predicate_modal_rules())
    after = CanonicalRoundTripIR((
        CanonicalRule("O", "agency", "file", "notice", conditions=("approval",)),
        CanonicalRule("P", "agency", "file", "notice", conditions=("urgency",)),
    ))
    differences = compare_canonical_semantics(before, after)
    assert [row["kind"] for row in differences] == [
        "ir_cid_mismatch", "rule_set_mismatch", "added_rule", "added_rule", "dropped_rule", "dropped_rule",
    ]
    assert {row["rule_cid"] for row in differences if row["kind"] == "dropped_rule"} == {
        rule.rule_cid for rule in before.rules
    }
    assert {row["rule_cid"] for row in differences if row["kind"] == "added_rule"} == {
        rule.rule_cid for rule in after.rules
    }


def test_exact_cycle_admits_two_rules_with_the_same_predicate() -> None:
    request = measured_parity_compiler_request(
        "Agency must file notice if public interest. Agency may file notice if emergency.",
        request_id="gate-two-modal-siblings",
        atom_vocabulary=CanonicalAtomVocabulary(
            actors=("agency",), actions=("file",), objects=("notice",),
            qualifiers=("public_interest", "emergency"),
        ),
    )
    gate = run_with_preservation(request)
    assert gate.roundtrip.status is OperationStatus.SUCCESS
    assert gate.l1_ir_cid == gate.l2_ir_cid
    assert gate.roundtrip.l1_result is not None
    assert gate.roundtrip.l1_result.canonical_ir is not None
    assert gate.roundtrip.l1_result.canonical_ir.rules == _same_predicate_modal_rules()
    assert gate.admitted and gate.differences == ()
    assert gate.preservation_class is TranslationPreservationClass.LOSSLESS
    assert gate.fidelity_claim is FidelityClaim.SEMANTIC


def test_exact_rule_multiplicity_preserves_one_unmatched_occurrence() -> None:
    rule, sibling = _same_predicate_modal_rules()
    before = CanonicalRoundTripIR((rule, rule, sibling))
    after = CanonicalRoundTripIR((rule, sibling))
    dropped = compare_canonical_semantics(before, after)
    added = compare_canonical_semantics(after, before)
    assert [row["kind"] for row in dropped] == ["ir_cid_mismatch", "dropped_rule"]
    assert dropped[1]["rule_cid"] == rule.rule_cid
    assert [row["kind"] for row in added] == ["ir_cid_mismatch", "added_rule"]
    assert added[1]["rule_cid"] == rule.rule_cid


def _assert_comparison_cid_matches_public_payload(gate) -> None:
    from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

    payload = gate.to_dict()
    comparison_cid = payload.pop("comparison_cid")
    for field in ("equality_criteria", "receipt", "recorded_directions", "roundtrip_result_cid", "status"):
        payload.pop(field)
    assert comparison_cid == cid_for_dag_json(payload)


def test_failed_gate_cid_matches_serialized_unsupported_class() -> None:
    request = CompilerRequest(
        source_text="Agency must publish notice.",
        request_id="gate-policy-refusal",
        atom_vocabulary=_vocabulary(),
        config={"document_type": "different-profile"},
    )
    gate = run_with_preservation(request)
    assert gate.status is OperationStatus.FAILED
    assert gate.roundtrip.terminal_stage == "l1_compile"
    assert gate.preservation_class is TranslationPreservationClass.UNSUPPORTED
    assert gate.admitted is False and gate.receipt is None
    _assert_comparison_cid_matches_public_payload(gate)


def test_abstained_gate_cid_matches_serialized_heuristic_class() -> None:
    request = CompilerRequest(
        source_text="Agency must file notice unless emergency.",
        request_id="gate-unsupported-facets",
        atom_vocabulary=CanonicalAtomVocabulary(actors=("agency",), actions=("file",), objects=("notice",)),
    )
    gate = run_with_preservation(request)
    assert gate.status is OperationStatus.ABSTAINED
    assert gate.preservation_class is TranslationPreservationClass.HEURISTIC
    assert gate.admitted is False and gate.receipt is None
    _assert_comparison_cid_matches_public_payload(gate)


def test_successful_gate_comparison_cid_matches_receipt_and_payload() -> None:
    gate = run_with_preservation(measured_parity_compiler_request(
        "Agency shall publish notice.", request_id="gate-payload-identity", atom_vocabulary=_vocabulary(),
    ))
    assert gate.status is OperationStatus.SUCCESS and gate.admitted
    assert gate.receipt is not None and gate.receipt.semantic_comparison_cid == gate.comparison_cid
    _assert_comparison_cid_matches_public_payload(gate)
