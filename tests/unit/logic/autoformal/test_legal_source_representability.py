"""Occurrence-preserving proposals, real profile checks, and population guards."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_representability as subject


def bound(text, *, occurrence_id="section-1:occurrence-0", region_kind="codified_body",
          document_id="usc:fixture:1", document_revision="edition-2026", document_text=None,
          start=0):
    document = text if document_text is None else document_text
    unit = subject.bind_source_unit(
        document, document_id=document_id, document_revision=document_revision,
        occurrence_id=occurrence_id, char_start=start, char_end=start + len(text),
        region_kind=region_kind)
    return {"unit": unit, "document_text": document}


def vocabulary(**overrides):
    return {"actors": ["agency", "clerk"], "actions": ["file", "retain"],
            "objects": ["notice", "records"], "qualifiers": [], **overrides}


def propose(text, **kwargs):
    return subject.propose_source_representability(**bound(text), **kwargs)


def inventory(requests):
    return subject.inventory_source_representability(
        requests, expected_unit_sha256s=[row["unit"]["unit_sha256"] for row in requests])


def test_lexical_cues_are_never_reviewed_or_full_representability():
    report = propose("The agency must retain records.")
    assert "operative_norm" in report["labels"]
    assert report["disposition"] == "unresolved_profile_assessment"
    assert report["routes"][0]["status"] == "not_assessed"
    assert report["source_preflight"]["outcome"] == "unassessed"
    for key in subject._FALSE:
        assert report[key] is False
    assert report["proposal_status"] == "unreviewed_multilabel_proposal"


def test_declared_vocabulary_invokes_actual_complete_parser_without_gold_authority():
    report = propose("The agency must retain records.", vocabulary=vocabulary())
    route = report["routes"][0]
    assert route["status"] == "declared_syntax_accepted"
    assert route["complete_source_consumption"] is True
    assert route["canonical_ir"]["rules"][0]["modality"] == "O"
    assert route["profile"] == "explicit-qualifier-single-rule/v1"
    assert route["source_semantics_verified"] is False
    assert report["disposition"] == "declared_syntax_candidate"
    assert report["full_representability_established"] is False
    wrong = propose("The agency must retain records.", vocabulary=vocabulary(actors=["clerk"]))
    assert wrong["routes"][0]["status"] == "outside_profile"
    assert wrong["disposition"] == "outside_selected_profile"


def test_multiclause_source_is_preserved_and_not_projected_to_first_easy_rule():
    text = "The agency must retain records; the clerk may file notice."
    report = propose(text, vocabulary=vocabulary())
    assert report["source_unit"]["source_text"] == text
    assert report["length"]["normative_cue_count"] == 2
    assert "ambiguous" in report["labels"]
    assert "multiple_normative_cues_require_composition" in report["selected_flat_profile_blockers"]
    assert report["routes"][0]["status"] == "outside_profile"
    assert report["routes"][0]["canonical_ir"] is None


def test_definition_scope_and_reference_proposals_coexist_with_named_existing_routes():
    text = 'In this section, the term “provider” means a person defined in section 12.'
    report = propose(text)
    assert {"definition", "scope", "cross_reference", "unsupported"} <= set(report["labels"])
    profiles = {row["profile"] for row in report["routes"]}
    assert "section-local-unary-predicate-definition/v1" in profiles
    assert "legal-statutory-context-routing/v1" in profiles
    assert report["context"]["missing"] is True
    assert report["disposition"] == "unresolved_context"


@pytest.mark.parametrize("text,label", [
    ("Section 4 was amended by Pub. L. 123.", "amendment_history"),
    ("There is hereby established an Office of Review.", "constitutive"),
    ("A person may file a petition for a hearing.", "procedure"),
    ("This provision shall apply to every agency.", "scope"),
])
def test_distinct_legal_function_cues_are_exposed_without_automatic_meaning(text, label):
    report = propose(text)
    assert label in report["labels"]
    assert report["reviewed_label"] is False


def test_notes_are_retained_even_when_they_include_operative_language():
    request = bound("The agency must retain records.", region_kind="notes_or_other")
    report = subject.propose_source_representability(**request, vocabulary=vocabulary())
    assert {"operative_norm", "ambiguous", "unsupported"} <= set(report["labels"])
    # An ASCII parser can consume the sentence while its legal source region
    # remains outside the selected standalone codified-norm interpretation.
    assert report["routes"][0]["status"] == "declared_syntax_accepted"
    assert report["disposition"] == "outside_selected_profile"
    assert report["source_unit"]["region_kind"] == "notes_or_other"


def test_required_context_and_supplied_unresolved_context_remain_distinct():
    text = "The agency must retain records."
    missing = propose(text, requires_context_resolution=True, vocabulary=vocabulary())
    supplied = propose(text, requires_context_resolution=True, context_text="Section 2 definitions.",
                       vocabulary=vocabulary())
    assert missing["context"]["missing"] is True
    assert supplied["context"]["missing"] is False
    assert supplied["context"]["resolved"] is False
    assert supplied["context"]["applied"] is False
    assert missing["disposition"] == supplied["disposition"] == "unresolved_context"
    assert supplied["routes"][0]["complete_source_consumption"] is True


def test_incomplete_list_and_quantified_binding_expose_existing_profile_limit():
    partial = propose("The following persons:")
    assert partial["context"]["missing"] is True
    quantified = propose("Every agency must retain exactly one records.")
    codes = {row["code"] for row in quantified["evidence"]}
    assert {"source.quantified_binding", "source.quantified_cardinality"} <= codes
    assert "unsupported" in quantified["labels"]


def test_oversized_supplied_context_is_preserved_and_never_reported_missing():
    context = "Explicit supplied context. " * 100
    report = propose("The agency must retain records.", context_text=context,
                     requires_context_resolution=True)
    assert report["context"]["text"] == context
    assert report["context"]["missing"] is False
    assert report["context"]["required"] is True
    assert report["source_preflight_context_coverage"] == "not_assessed_exceeds_context_bound"
    assert "source.required_context_missing" not in {row["code"] for row in report["evidence"]}


def test_oversized_source_cannot_claim_preflight_context_diagnostic_ran():
    text = "The agency must retain records. " + "x" * subject.preflight.MAX_SOURCE_CHARS
    report = propose(text, context_text="Explicit supplied context.")
    assert report["source_unit"]["source_text"] == text
    assert report["source_preflight"] is None
    assert report["source_preflight_context_coverage"] == "not_assessed_exceeds_source_bound"
    assert report["context"]["text"] == "Explicit supplied context."
    assert report["context"]["missing"] is False
    assert "source_exceeds_existing_preflight_bound" in report["selected_flat_profile_blockers"]


def test_unicode_offsets_are_absolute_and_preserve_original_case_whitespace():
    text = "Café bureau  must retain résumé records."
    document = "§1 — Préface\n" + text + "\nEnd."
    request = bound(text, document_text=document, start=document.index(text))
    report = subject.propose_source_representability(**request, vocabulary=vocabulary())
    cue = next(row for row in report["evidence"] if row["label"] == "operative_norm")
    assert document[cue["document_char_start"]:cue["document_char_end"]] == "must"
    assert text[cue["source_char_start"]:cue["source_char_end"]] == "must"
    assert request["unit"]["offset_coordinate_system"] == subject.OFFSET_COORDINATES
    assert request["unit"]["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert report["source_unit"]["source_text"] == text
    assert report["routes"][0]["status"] == "outside_profile"  # real ASCII-profile refusal


def test_equal_text_occurrences_and_repeated_presentations_are_not_deduplicated():
    text = "The agency must retain records."
    document = text + "\n" + text
    first = bound(text, document_text=document, occurrence_id="physical-0")
    second = bound(text, document_text=document, start=len(text) + 1, occurrence_id="physical-1")
    result = inventory([first, second, first])
    assert result["presentation_count"] == 3
    assert result["physical_occurrence_count"] == 2
    assert [row["presentation_index"] for row in result["rows"]] == [0, 1, 2]
    assert result["observed_unit_sha256s"] == [first["unit"]["unit_sha256"],
                                              second["unit"]["unit_sha256"], first["unit"]["unit_sha256"]]
    assert result["population_complete"] is True
    assert result["coverage_scope"] == "exact_supplied_upstream_population_only"


def test_population_gate_forbids_easy_selection_reordering_and_duplicate_erasure():
    requests = [bound("The agency must retain records.", occurrence_id="easy"),
                bound("Opaque text beyond the selected profile.", occurrence_id="hard")]
    expected = [row["unit"]["unit_sha256"] for row in requests]
    for selected in (requests[:1], list(reversed(requests)), [requests[0], requests[0]]):
        with pytest.raises(subject.RepresentabilityError, match="source population differs"):
            subject.inventory_source_representability(selected, expected_unit_sha256s=expected)
    result = inventory(requests)
    assert result["outside_selected_profile_presentations"] == [1]
    assert len(result["rows"]) == 2


def test_all_out_of_profile_is_a_complete_inventory_without_false_success():
    requests = [bound("Opaque text.", occurrence_id="opaque"),
                bound("There is established a commission.", occurrence_id="constitutive")]
    result = inventory(requests)
    assert result["outside_selected_profile_presentations"] == [0, 1]
    assert result["presentation_count"] == 2
    assert result["full_representability_established"] is False
    assert result["training_qualified"] is False


def test_conflicting_physical_identity_and_changed_version_are_not_merged():
    first = bound("Opaque text.")
    conflict = bound("Another text.")
    with pytest.raises(subject.RepresentabilityError, match="conflicting physical"):
        inventory([first, conflict])
    next_version = bound("Opaque text.", document_revision="edition-2027")
    assert inventory([first, next_version])["physical_occurrence_count"] == 2


def test_tampered_source_hash_offsets_and_resealed_proposal_are_refused():
    request = bound("The agency must retain records.")
    for field, value in (("source_sha256", "0" * 64), ("char_start", True),
                         ("source_text", "The agency may retain records.")):
        unit = deepcopy(request["unit"])
        unit[field] = value
        with pytest.raises(subject.RepresentabilityError):
            subject.propose_source_representability(unit, request["document_text"])
    result = subject.propose_source_representability(**request)
    bad = deepcopy(result)
    bad["source_semantics_verified"] = True
    bad["proposal_sha256"] = subject._digest({k: v for k, v in bad.items() if k != "proposal_sha256"})
    with pytest.raises(subject.RepresentabilityError, match="exact regeneration"):
        subject.validate_source_representability(bad, **request)
    result = inventory([request])
    result["outside_selected_profile_presentations"] = [0]
    with pytest.raises(subject.RepresentabilityError, match="exact regeneration"):
        subject.validate_representability_inventory(result, [request],
            expected_unit_sha256s=[request["unit"]["unit_sha256"]])


def test_bounds_fail_entire_batch_without_silently_truncated_outputs():
    request = bound("Opaque text.")
    with pytest.raises(subject.RepresentabilityError, match="unit bound exceeded"):
        subject.inventory_source_representability([request, request],
            expected_unit_sha256s=[request["unit"]["unit_sha256"]], max_units=1)
    with pytest.raises(subject.RepresentabilityError, match="evidence bound exceeded"):
        propose(" ".join(["may"] * (subject.MAX_EVIDENCE + 1)))
    with pytest.raises(subject.RepresentabilityError, match="valid UTF-8"):
        bound("bad surrogate \ud800")


def test_quoted_normative_example_does_not_become_an_operative_proposal():
    report = propose('The example is “The agency must retain records.”')
    assert "operative_norm" not in report["labels"]


def test_detached_inventory_regenerates_exactly_with_public_api():
    request = bound("The agency must retain records.")
    result = inventory([request])
    detached = json.loads(json.dumps(result))
    assert subject.validate_representability_inventory(detached, [request],
        expected_unit_sha256s=[request["unit"]["unit_sha256"]]) == result
