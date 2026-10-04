"""A real-source pilot must preserve bad predictions and refuse invented bindings."""
from copy import deepcopy
import hashlib

import pytest

from scripts.ops.legal_ir import check_legal_uscode_family_bridge as pilot


def example(*, text="The agency shall retain records.", modality="O", cue="shall", action="retain"):
    rule = {"modality": modality, "actor": "The agency", "action": action, "object": "records",
            "conditions": [], "exceptions": [], "temporal": []}
    source = {"id": "official-paragraph-1", "source_text": text, "source_sha256": hashlib.sha256(text.encode()).hexdigest()}
    facets = {}
    for key in ("actor", "action", "object"):
        start = text.index(rule[key])
        facets[key] = {"char_start": start, "char_end": start + len(rule[key]), "text": rule[key], "present": True}
    facets.update({key: {"char_start": None, "char_end": None, "text": None, "present": False}
                   for key in ("conditions", "exceptions", "temporal")})
    start = text.index(cue)
    prediction = {"status": "decoded", "canonical_ir": {"rules": [rule]}, "source_sha256": source["source_sha256"],
        "span_diagnostics": {"facets": facets}, "grounding_diagnostics": {
            "trigger": {"char_start": start, "char_end": start + len(cue), "text": cue},
            "trigger_span": [start, start + len(cue)], "trigger_text": cue,
            "trigger_residual_enabled": True, "annotations_accessed": False}}
    return source, prediction


@pytest.mark.parametrize("modality,cue", [("O", "shall"), ("P", "may"), ("F", "must not"), ("F", "may not")])
def test_unchanged_candidate_and_exact_diagnostics_enter_all_native_families(modality, cue):
    source, prediction = example(text=f"The agency {cue} retain records.", modality=modality, cue=cue)
    before = deepcopy(prediction)
    request = pilot.request_for_prediction(source, prediction, "frozen-model-1729")
    assert request["candidate"]["canonical_ir"] == before["canonical_ir"]
    assert prediction == before
    assert "frozen-model-1729" in request["candidate"]["candidate_id"] and source["id"] in request["candidate"]["candidate_id"]
    for family in pilot.FAMILIES:
        prepared = pilot.gate.prepare_source_family_legal([request | {"family": family}],
                                                         toolchain="leanprover/lean4:v4.34.1").to_dict()
        assert prepared["all_candidates_supported"] and prepared["target"] == "legal"
        assert prepared["source_semantics_verified"] is False


def test_repeated_surface_binds_actual_selected_interval_without_search_or_repair():
    text = "The agency shall retain records and retain copies."
    source, prediction = example(text=text)
    position = text.rindex("retain")
    prediction["span_diagnostics"]["facets"]["action"].update(char_start=position, char_end=position + 6)
    request = pilot.request_for_prediction(source, prediction, "model")
    assert request["occurrence_bindings"][0]["facets"]["action"]["start_char"] == position
    # The retained object precedes this action: no semantic repair is performed.
    assert request["candidate"]["canonical_ir"] == prediction["canonical_ir"]


def test_structurally_bound_but_meaningless_action_remains_visible():
    source, prediction = example(text="The agency shall act on records.", action="on")
    request = pilot.request_for_prediction(source, prediction, "model")
    report = pilot.bridge.prepare_source_family(**request, family="deontic_fol")
    assert report["canonical_roundtrip"]["rules"][0]["action"] == "on"
    assert report["source_bound"] and not report["source_semantics_verified"]


@pytest.mark.parametrize("facet", ["conditions", "exceptions", "temporal"])
def test_no_arbitrary_qualifier_meaning_is_created(facet):
    source, prediction = example()
    prediction["canonical_ir"]["rules"][0][facet] = ["unreviewed"]
    with pytest.raises(pilot.Refusal, match="unreviewed_qualifier_interpretation"):
        pilot.request_for_prediction(source, prediction, "model")


@pytest.mark.parametrize("mutation", ["disabled", "missing", "wrong_text", "wrong_modality", "annotations", "bool_offset"])
def test_trigger_requires_enabled_exact_source_only_consistent_diagnostics(mutation):
    source, prediction = example()
    diagnostic = prediction["grounding_diagnostics"]
    if mutation == "disabled":
        diagnostic["trigger_residual_enabled"] = False
    elif mutation == "missing":
        prediction.pop("grounding_diagnostics")
    elif mutation == "wrong_text":
        diagnostic["trigger_text"] = "must"
    elif mutation == "wrong_modality":
        prediction["canonical_ir"]["rules"][0]["modality"] = "P"
    elif mutation == "annotations":
        diagnostic["annotations_accessed"] = True
    else:
        diagnostic["trigger"]["char_start"] = True
    with pytest.raises(pilot.Refusal):
        pilot.request_for_prediction(source, prediction, "model")


def test_partial_negated_cue_and_multiple_cues_are_refused():
    source, prediction = example(text="The agency may not retain records.", modality="P", cue="may")
    with pytest.raises(pilot.Refusal, match="negation"):
        pilot.request_for_prediction(source, prediction, "model")
    source, prediction = example(text="The agency shall retain records and may release them.")
    with pytest.raises(pilot.Refusal, match="ambiguous"):
        pilot.request_for_prediction(source, prediction, "model")


@pytest.mark.parametrize("mutation", ["missing", "false_presence", "changed_end", "normalization", "absent_qualifier"])
def test_no_invented_or_repaired_facet_spans(mutation):
    source, prediction = example()
    facets = prediction["span_diagnostics"]["facets"]
    if mutation == "missing":
        facets.pop("actor")
    elif mutation == "false_presence":
        facets["actor"]["present"] = False
    elif mutation == "changed_end":
        facets["actor"]["char_end"] += 1
    elif mutation == "normalization":
        prediction["canonical_ir"]["rules"][0]["actor"] = "the agency"
    else:
        facets["exceptions"]["present"] = True
    with pytest.raises(pilot.Refusal):
        pilot.request_for_prediction(source, prediction, "model")


def test_deterministic_batches_preserve_every_request_exactly():
    requests = [{"id": index} for index in range(260)]
    batches = pilot.partition_requests(requests)
    assert list(map(len, batches)) == [126, 126, 8]
    assert [item for batch in batches for item in batch] == requests


def test_model_slots_have_distinct_source_bound_candidate_identity():
    source, prediction = example()
    first = pilot.request_for_prediction(source, prediction, "first-model")
    second = pilot.request_for_prediction(source, prediction, "second-model")
    assert first["candidate"]["canonical_ir"] == second["candidate"]["canonical_ir"]
    assert first["candidate"]["candidate_id"] != second["candidate"]["candidate_id"]
    assert first["interpretation"]["candidate_sha256"] != second["interpretation"]["candidate_sha256"]
