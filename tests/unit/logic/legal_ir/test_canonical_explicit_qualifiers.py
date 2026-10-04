"""Independent profile tests for complete qualifier and source coverage."""
from __future__ import annotations

import inspect

import pytest
from ipfs_datasets_py.logic.legal_ir import canonical_explicit_qualifiers as subject
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalAtomVocabulary,
    CanonicalContractError,
    CompilerRequest,
    CompilerResult,
    DecompilerRequest,
    OperationStatus,
)
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import SourceWithheldCanonicalDecompiler
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json


@pytest.fixture
def vocabulary():
    return CanonicalAtomVocabulary(actors=("agency", "clerk", "custodian", "officer"),
                                  actions=("file", "retain"), objects=("notice", "record", "application"),
                                  qualifiers=("public_interest", "public_safety", "emergency", "legal_hold",
                                              "within_48_hours", "within_10_days", "before_the_review_deadline"))


def compile_text(text, vocabulary, **kwargs):
    return subject.ExplicitQualifierCanonicalCompiler().compile(CompilerRequest(text, "independent-source", vocabulary, **kwargs))


@pytest.mark.parametrize("modal,expected", [("must", "O"), ("shall", "O"), ("may", "P"), ("must not", "F"), ("shall not", "F")])
def test_full_compound_qualifier_identity_and_modal_polarity(vocabulary, modal, expected):
    source = f"The agency {modal} file notice within 48 hours and before the review deadline if public interest and public safety, unless emergency or legal hold."
    result = compile_text(source, vocabulary)
    assert result.status is OperationStatus.SUCCESS
    rule = result.canonical_ir.rules[0]
    assert (rule.actor, rule.action, rule.object, rule.modality) == ("agency", "file", "notice", expected)
    assert rule.conditions == ("public_interest", "public_safety")
    assert rule.exceptions == ("emergency", "legal_hold")
    assert rule.temporal == ("before_the_review_deadline", "within_48_hours")
    rendering = SourceWithheldCanonicalDecompiler().decompile(DecompilerRequest(result.canonical_ir, "withheld-render"))
    reparsed = compile_text(rendering.text, vocabulary)
    assert reparsed.canonical_ir == result.canonical_ir


def test_leading_condition_and_distinct_numeric_deadlines_preserve_all_constraints(vocabulary):
    result = compile_text("If public interest and public safety, the agency may file the notice within 48 hours and within 10 days, unless emergency or legal hold.", vocabulary)
    rule = result.canonical_ir.rules[0]
    assert rule.conditions == ("public_interest", "public_safety")
    assert rule.temporal == ("within_10_days", "within_48_hours")
    assert rule.exceptions == ("emergency", "legal_hold")


@pytest.mark.parametrize("source", [
    "The agency must file notice if public interest or public safety.",
    "The agency must file notice unless emergency and legal hold.",
    "The agency must file notice within 48 hours or within 10 days.",
    "The agency must file notice if public interest is absent.",
    "The agency must file notice unless no emergency exists.",
    "The agency must not fail to file notice.",
    "The clerk told the custodian that the officer must retain application.",
    "The clerk and custodian must retain application.",
    "Every clerk must file notice.",
    "Each clerk must retain exactly one application.",
    "The agency must file notice if public interest, unless emergency; officer may retain record.",
    "The agency must file notice. The officer may retain record.",
    "The agency must file notice according to the procedure.",
    "The agency must file notice next Friday.",
    "The agency must file notice if public interest and public safety or emergency.",
    "If public interest, the agency must file notice if public safety.",
    "The agency must file notice unless emergency if public interest.",
    "The agency must file notice if.",
    "The agency must file notice unless.",
    "The agency must file notice within 48 hours and.",
    "If public interest the agency must file notice.",
    "The agency must file notice, if public interest.",
    "The agency must file notice if public interest and public interest.",
    "The agency must file notice if public interest unless.",
])
def test_incomplete_unsupported_or_scope_changing_text_never_emits_partial_ir(vocabulary, source):
    result = compile_text(source, vocabulary)
    assert result.status is OperationStatus.ABSTAINED
    assert result.canonical_ir is None and result.source_map == ()
    assert result.unsupported_semantics
    assert result.provenance["fallback_used"] is False


def test_ambiguous_actor_gets_explicit_clarification_diagnostic(vocabulary):
    source = "The clerk told the custodian that they must retain the application."
    result = compile_text(source, vocabulary)
    assert result.status is OperationStatus.ABSTAINED
    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "source.unresolved_actor_pronoun"
    assert source[diagnostic.start:diagnostic.end] == "they"


@pytest.mark.parametrize("source", ["The agency must file notice if public interests.", "The agency must file notice if public interest verified.", "The agencies must file notice."])
def test_unseen_or_near_match_atoms_are_not_fuzzily_assigned(vocabulary, source):
    assert compile_text(source, vocabulary).canonical_ir is None


def test_declared_copula_and_applies_forms_use_generic_atom_rules():
    vocabulary = CanonicalAtomVocabulary(actors=("assessor",), actions=("record",), objects=("evidence",),
                                        qualifiers=("evidence_complete", "fees_paid", "legal_hold"))
    result = compile_text("The assessor must record evidence if the evidence is complete and fees have been paid, unless a legal hold applies.", vocabulary)
    rule = result.canonical_ir.rules[0]
    assert rule.conditions == ("evidence_complete", "fees_paid") and rule.exceptions == ("legal_hold",)


def test_multiple_complete_core_parses_are_rejected():
    vocabulary = CanonicalAtomVocabulary(actors=("clerk",), actions=("file", "file_notice"), objects=("notice",))
    result = compile_text("The clerk must file notice.", vocabulary)
    assert result.canonical_ir is None
    assert result.diagnostics[0].code == "explicit_qualifier.ambiguous_complete_parse"


def test_ambiguous_caller_surface_and_reserved_atoms_fail_closed():
    ambiguous = CanonicalAtomVocabulary(actors=("clerk", "the_clerk"), actions=("file",), objects=("notice",))
    assert compile_text("The clerk must file notice.", ambiguous).diagnostics[0].code == "explicit_qualifier.ambiguous_atom_surface"
    reserved = CanonicalAtomVocabulary(actors=("clerk",), actions=("must_file",), objects=("notice",))
    assert compile_text("The clerk must file notice.", reserved).canonical_ir is None


@pytest.mark.parametrize("actor", ["they", "every_clerk", "each_officer"])
def test_unresolved_pronouns_and_quantifiers_cannot_be_smuggled_as_named_atoms(actor):
    vocabulary = CanonicalAtomVocabulary(actors=(actor,), actions=("file",), objects=("notice",))
    assert compile_text(actor.replace("_", " ") + " must file notice.", vocabulary).canonical_ir is None


def test_unique_profile_cids_receipts_and_source_map_do_not_claim_frozen_selection(vocabulary):
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TYPED_DEONTIC_COMPILER_CONFIG_CID

    result = compile_text("The agency must file notice.", vocabulary)
    assert subject.EXPLICIT_QUALIFIER_CONFIG_CID != TYPED_DEONTIC_COMPILER_CONFIG_CID
    assert subject.EXPLICIT_QUALIFIER_CONFIG_CID == cid_for_dag_json(subject.explicit_qualifier_configuration())
    assert result.provenance["opt_in"] is True and result.provenance["benchmark_admitted"] is False
    assert "implementation_representative_arm_id" not in result.provenance
    assert result.component_trace[0].config_cid == subject.EXPLICIT_QUALIFIER_CONFIG_CID
    assert len(result.source_map) == 7
    assert all(entry.source_cid == CompilerRequest("The agency must file notice.", "independent-source", vocabulary).source_cid for entry in result.source_map)
    assert CompilerResult.from_dict(result.to_dict()).result_cid == result.result_cid


def test_old_frozen_orchestrator_rejects_alternative_configuration_before_execution(vocabulary):
    from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import CanonicalSemanticRoundTrip

    result = CanonicalSemanticRoundTrip(compiler=subject.ExplicitQualifierCanonicalCompiler()).run(
        CompilerRequest("The agency must file notice.", "separate-profile", vocabulary))
    assert result.status is not OperationStatus.SUCCESS and result.l1_result is None
    assert result.terminal_stage == "component_validation"


@pytest.mark.parametrize("kwargs", [{"allow_explicit_partial": True}, {"config": {"document_type": "general"}}, {"config": {"fallback": True}}])
def test_profile_overrides_and_partial_projection_are_rejected(vocabulary, kwargs):
    result = compile_text("The agency must file notice.", vocabulary, **kwargs)
    assert result.status is OperationStatus.FAILED and result.canonical_ir is None


def test_constructor_accepts_only_bound_request_and_has_no_gold_channel(vocabulary):
    with pytest.raises(CanonicalContractError):
        subject.ExplicitQualifierCanonicalCompiler().compile("The agency must file notice.")
    assert list(inspect.signature(subject.ExplicitQualifierCanonicalCompiler.compile).parameters) == ["self", "request"]


def test_no_legacy_converter_or_model_fallback_is_used(vocabulary, monkeypatch):
    from ipfs_datasets_py.logic.legal_ir import canonical_compiler

    def forbid():
        raise AssertionError("legacy execution must remain unavailable to this profile")

    monkeypatch.setattr(canonical_compiler, "_load_deontic_components", forbid)
    assert compile_text("The agency must file notice if public interest.", vocabulary).status is OperationStatus.SUCCESS
    assert compile_text("The agency must file notice if unseen condition.", vocabulary).canonical_ir is None


def test_source_and_vocabulary_bounds_do_not_truncate(vocabulary):
    assert compile_text("x" * 16_385, vocabulary).canonical_ir is None
    assert compile_text("The agéncy must file notice.", vocabulary).canonical_ir is None
    oversized = CanonicalAtomVocabulary(actors=tuple(f"actor_{index}" for index in range(257)), actions=("file",), objects=("notice",))
    assert compile_text("Actor 1 must file notice.", oversized).diagnostics[0].code == "explicit_qualifier.vocabulary_bound"


def test_authored_richer_cases_keep_train_only_vocabulary_and_oov_abstentions():
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_panel import (
        build_alignment_richer_panel,
        richer_training_vocabulary,
    )

    panel = build_alignment_richer_panel()
    vocabulary = richer_training_vocabulary(panel)
    assert "identity_verified" not in vocabulary.qualifiers
    exact, negatives = 0, 0
    for row in panel["rows"]:
        if row["row_kind"] == "explicit_context":
            continue
        result = compile_text(row["source_text"], vocabulary)
        if result.canonical_ir is not None:
            assert row["row_kind"] == "positive" and result.canonical_ir.to_dict() == row["target"]
            exact += 1
        elif row["row_kind"] == "positive":
            assert "identity_verified" in row["target"]["rules"][0]["conditions"]
        else:
            negatives += 1
    assert exact == 22 and negatives == 8
