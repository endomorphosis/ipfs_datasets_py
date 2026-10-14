"""Source-specific quality diagnostics retain scope and readiness boundaries."""

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic import metrics
from ipfs_datasets_py.logic.deontic.exports import (
    build_deterministic_parser_capability_profile_record,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


EXCEPTION_TEXT = "The Secretary shall publish the notice except as provided in section 552."
MIXED_SCOPE_TEXT = (
    "Notwithstanding section 9, the inspector shall knowingly approve discharge "
    "if the permit is valid unless approval is denied."
)


def _element(text):
    return extract_normative_elements(text)[0]


def _assert_nested_diagnostics(summary):
    quality = summary["phase8_quality_summary"]
    for key in (
        "prover_syntax_target_coverage",
        "prover_syntax_corpus_coverage",
        "ir_slot_provenance",
    ):
        assert quality[key] == summary[key]
    return quality


@pytest.mark.parametrize(
    ("text", "scope_slots"),
    [
        ("The Secretary shall publish the notice if approval is granted.", ["conditions"]),
        (EXCEPTION_TEXT, ["exceptions"]),
        (
            "Notwithstanding section 5.01.020, the Director may issue a variance.",
            ["overrides"],
        ),
    ],
)
def test_conditional_capability_checks_the_scope_that_is_present(text, scope_slots):
    norm = LegalNormIR.from_parser_element(_element(text))
    before = deepcopy(norm.to_dict())

    profile = build_deterministic_parser_capability_profile_record(norm)

    assert profile["capability_family"] == "conditional_normative"
    assert profile["checked_slots"] == ["actor", "modality", "action", *scope_slots]
    assert profile["grounded_slots"] == profile["checked_slots"]
    assert profile["missing_slots"] == []
    assert profile["ungrounded_slots"] == []
    assert profile["source_grounded_slot_rate"] == 1.0
    assert norm.to_dict() == before


def test_conditional_capability_keeps_all_scopes_mental_state_and_repair_gates():
    element = _element(MIXED_SCOPE_TEXT)
    norm = LegalNormIR.from_parser_element(element)
    before = deepcopy(norm.to_dict())

    profile = build_deterministic_parser_capability_profile_record(norm)

    assert profile["checked_slots"] == [
        "actor", "modality", "mental_state", "action", "conditions", "exceptions", "overrides"
    ]
    assert profile["grounded_slots"] == profile["checked_slots"]
    assert profile["source_grounded_slot_rate"] == 1.0
    assert profile["formula_proof_ready"] is False
    assert profile["parser_proof_ready"] is False
    assert profile["repair_required"] is True
    assert profile["requires_validation"] is True
    assert "cross_reference_requires_resolution" in profile["blockers"]
    assert norm.to_dict() == before


def test_explicit_capability_slots_still_require_absent_condition():
    norm = LegalNormIR.from_parser_element(_element(EXCEPTION_TEXT))
    requested = ("actor", "conditions", "exceptions")

    profile = build_deterministic_parser_capability_profile_record(norm, slots=requested)

    assert profile["checked_slots"] == list(requested)
    assert profile["missing_slots"] == ["conditions"]
    assert profile["grounded_slots"] == ["actor", "exceptions"]
    assert profile["repair_required"] is True


def test_present_but_ungrounded_exception_is_still_audited():
    norm = LegalNormIR.from_parser_element(_element(EXCEPTION_TEXT))
    norm = replace(norm, exceptions=[{"value": "unrelated ungrounded exception"}])
    before = deepcopy(norm.to_dict())

    profile = build_deterministic_parser_capability_profile_record(norm)

    assert profile["checked_slots"] == ["actor", "modality", "action", "exceptions"]
    assert profile["missing_slots"] == []
    assert profile["ungrounded_slots"] == ["exceptions"]
    assert profile["source_grounded_slot_rate"] == 0.75
    assert norm.to_dict() == before


def test_event_procedure_without_conditional_scope_keeps_its_family():
    norm = LegalNormIR.from_parser_element(
        _element("Upon receipt of an application, the Bureau shall inspect the premises before approval.")
    )

    profile = build_deterministic_parser_capability_profile_record(norm)

    assert profile["capability_family"] == "procedural_event_duty"
    assert profile["checked_slots"] == ["actor", "modality", "action"]


@pytest.mark.parametrize("summarize", [metrics.summarize_parser_elements, metrics.summarize_phase8_parser_metrics])
def test_empty_summary_keeps_nested_diagnostics_without_completeness(summarize):
    summary = summarize([])
    quality = _assert_nested_diagnostics(summary)

    assert summary["phase8_source_count"] == 0
    assert quality["phase8_quality_complete"] is False
    assert quality["requires_validation"] is True
    assert quality["prover_syntax_target_coverage"]["all_required_passed"] is False


def test_mixed_source_quality_preserves_per_source_slots_and_repair_boundaries():
    elements = [_element("The tenant must pay rent monthly."), _element(EXCEPTION_TEXT)]
    before = deepcopy(elements)

    summary = metrics.summarize_parser_elements(elements)
    quality = _assert_nested_diagnostics(summary)

    assert quality["source_record_count"] == 2
    assert quality["complete_source_count"] == 1
    assert quality["source_complete_rate"] == 0.5
    assert quality["requires_validation"] is True
    assert quality["coverage_blocker_distribution"] == {
        "missing_reconstruction_slot:temporal_constraints": 1
    }
    assert summary["prover_syntax_corpus_coverage"]["all_sources_complete"] is True
    assert summary["phase8_parser_capability_source_grounding_rate"] == 1.0
    assert summary["proof_ready_count"] == 1
    assert summary["repair_required_count"] == 1
    assert elements == before


def test_partial_source_target_coverage_cannot_borrow_another_sources_target(monkeypatch):
    complete = _element("The tenant must pay rent.")
    partial = _element(EXCEPTION_TEXT)
    partial_source = LegalNormIR.from_parser_element(partial).source_id
    build_records = metrics.build_prover_syntax_records_from_ir

    def omit_one_target(norm):
        records = build_records(norm)
        if norm.source_id == partial_source:
            return [record for record in records if record["target"] != "fol"]
        return records

    monkeypatch.setattr(metrics, "build_prover_syntax_records_from_ir", omit_one_target)
    summary = metrics.summarize_parser_elements([complete, partial])
    quality = _assert_nested_diagnostics(summary)

    assert quality["prover_syntax_target_coverage"]["all_required_passed"] is True
    corpus = quality["prover_syntax_corpus_coverage"]
    assert corpus["source_count"] == 2
    assert corpus["complete_source_count"] == 1
    assert corpus["source_missing_targets_by_source"][partial_source] == ["fol"]
    assert corpus["all_sources_complete"] is False
    assert quality["complete_source_count"] == 1
    assert quality["phase8_quality_complete"] is False
    assert quality["requires_validation"] is True
    assert summary["proof_ready_count"] == 1
    assert summary["repair_required_count"] == 1


def test_duplicate_rows_with_one_source_identity_remain_incomplete():
    element = _element("The tenant must pay rent.")
    summary = metrics.summarize_phase8_parser_metrics([element, deepcopy(element)])
    quality = _assert_nested_diagnostics(summary)

    assert quality["source_record_count"] == 1
    assert quality["prover_syntax_corpus_coverage"]["source_count"] == 1
    assert quality["prover_syntax_corpus_coverage"]["target_duplicate_record_count"] == 5
    assert quality["complete_source_count"] == 0
    assert quality["phase8_quality_complete"] is False
    assert quality["requires_validation"] is True
