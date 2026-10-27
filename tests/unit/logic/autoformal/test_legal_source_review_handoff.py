"""Review requests cannot discard observations or fabricate review authority."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_review_handoff as owner

# The repository uses pytest's importlib mode; load the independently pinned
# sibling fixture by its physical path instead of assuming a test sys.path.
_spec = importlib.util.spec_from_file_location("candidate_context_fixture",
    Path(__file__).with_name("test_legal_candidate_context_inventory.py"))
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
materialize, digest, damage_nested_replay = _fixtures.materialize, _fixtures.digest, _fixtures.damage_nested_replay


def prepared(tmp_path, **options):
    context, sentence, alignment, args = materialize(tmp_path, **options)
    context_inputs = {"sentence_candidates_report": sentence, "alignment_report": alignment, **args}
    inputs = {"expected_candidate_context_inventory_report_sha256": digest(context), "context_inputs": context_inputs}
    report = owner.prepare_source_review_handoff(context, **inputs)
    return report, context, inputs


def test_complete_queue_preserves_all_pieces_references_opportunities_and_denominators(tmp_path):
    report, context, inputs = prepared(tmp_path)
    queue = report["queue_units"]
    pieces = [u for u in queue if u["unit_kind"] == "original_parent_partition_piece"]
    references = [u for u in queue if u["unit_kind"] == "original_unresolved_surface_reference"]
    opportunities = [u for u in queue if u["unit_kind"] == "exact_declared_markup_statute_block_opportunity"]
    assert [u["original_observation"] for u in pieces] == [p["original_observation"] for r in context["rows"] for p in r["partition_piece_contexts"]]
    assert [u["original_observation"] for u in references] == [p["original_observation"] for r in context["rows"] for p in r["surface_reference_contexts"]]
    assert [u["original_observation"] for u in opportunities] == context["source_block_opportunities"]
    assert report["queue_unit_count"] == context["partition_piece_count"] + context["surface_reference_count"] + context["source_block_opportunity_count"]
    assert [u["queue_ordinal"] for u in queue] == list(range(len(queue)))
    assert len(report["official_block_denominator"]) == context["source_block_count"]
    assert len(report["comparison_denominators"]) == context["comparison_count"]
    assert report["parent_rows"][0]["original_row_observation"]["boundary_observations"] == context["rows"][0]["original_row_observation"]["boundary_observations"]
    assert owner.source_review_handoff_report_sha256(report) == digest(report)
    assert owner.validate_source_review_handoff(report, context, expected_report_sha256=digest(report), **inputs) == report


def test_every_note_metadata_gap_and_uncovered_parent_piece_remains_in_review_queue(tmp_path):
    report, _, _ = prepared(tmp_path)
    pieces = [u["original_observation"] for u in report["queue_units"] if u["unit_kind"] == "original_parent_partition_piece"]
    text = "".join(u["selector"]["text"] for u in pieces)
    assert "Header." in text and "Editorial Notes" in text and "Tail fragment" in text
    assert pieces[0]["kind"] == "raw_whitespace_gap" and pieces[-1]["kind"] == "raw_whitespace_gap"
    assert {b["declared_region_kind_observation"] for b in report["official_block_denominator"]} >= {"section_heading", "statute", "source_credit", "editorial_notes"}
    assert any(c["uncovered_parent_characters"] > 0 for c in report["comparison_denominators"])


def test_declared_statute_opportunity_has_both_exact_selectors_but_no_legal_or_review_authority(tmp_path):
    report, _, _ = prepared(tmp_path)
    for unit in report["queue_units"]:
        assert unit["status"] == "pending_independent_source_and_legal_review"
        assert all(o["status"] == "pending_independent_review" and not o["verified"] and not o["closed"] for o in unit["review_obligations"])
        assert [o["kind"] for o in unit["review_obligations"]] == list(owner.REVIEW_OBLIGATION_KINDS)
        assert not unit["original_candidate_cropped_or_replaced"] and not unit["selected_as_legal_text"] and not unit["autoformalization_eligible"]
        assert all(flag is False for flag in unit["authority"].values())
        if unit["unit_kind"] == "exact_declared_markup_statute_block_opportunity":
            original = unit["original_observation"]
            assert original["parent_selector"]["text"] == original["official_selector"]["text"]
            assert original["parent_selector"]["schema"] != original["official_selector"]["schema"]
            assert original["declared_region_kind_observation"] == "statute" and not original["legal_role_verified"]
    assert report["actual_review_receipts_created"] is report["accepted_graphs_created"] is report["source_candidates_used_as_gold"] is False


def test_duplicate_physical_rows_and_overlapping_opportunities_are_never_deduplicated(tmp_path):
    report, context, _ = prepared(tmp_path, texts=["aaaa", "aaaa"], bodies=["aaa"])
    assert report["parent_row_count"] == 2 and report["declared_statute_block_opportunity_count"] == 4
    assert len(set(report["ordered_partition_piece_ids"])) == len(report["ordered_partition_piece_ids"])
    assert len(set(report["ordered_markup_opportunity_ids"])) == 4
    assert len({u["review_unit_id"] for u in report["queue_units"]}) == report["queue_unit_count"]
    assert report["partition_piece_count"] == context["partition_piece_count"]


def test_missing_parent_text_has_explicit_review_observation_and_complete_row_denominator(tmp_path):
    report, _, _ = prepared(tmp_path, texts=[None, "Available sentence."])
    missing = [u for u in report["queue_units"] if u["unit_kind"] == "unavailable_parent_text_observation"]
    assert len(missing) == 1 and missing[0]["parent_index"] == 0
    assert missing[0]["original_observation"]["source_text"] is None
    assert report["parent_row_count"] == 2 and len(report["parent_rows"]) == 2


def test_rendered_field_equality_is_retained_without_closing_source_review_obligations(tmp_path):
    text = "Header. §1. Heading Body. Source credit. Editorial Notes Body."
    report, _, _ = prepared(tmp_path, texts=[text], bodies=["Body."])
    assert report["comparison_denominators"][0]["exact_rendered_field_equal"] is True
    assert report["official_document_denominator"][0]["rendered_field_view"]["text"] == text
    assert all(not o["closed"] for u in report["queue_units"] for o in u["review_obligations"])
    assert all(flag is False for flag in report["authority"].values())


@pytest.mark.parametrize("damage", ["context_pin", "missing_input", "extra_input", "sentence_pin", "alignment_pin", "parent_population_pin"])
def test_independent_context_population_and_closed_replay_required(tmp_path, damage):
    _, context, inputs = prepared(tmp_path)
    if damage == "context_pin": inputs["expected_candidate_context_inventory_report_sha256"] = "0" * 64
    elif damage == "missing_input": inputs["context_inputs"].pop("sentence_inputs")
    elif damage == "extra_input": inputs["context_inputs"]["review_callback"] = "untrusted"
    elif damage == "sentence_pin": inputs["context_inputs"]["expected_sentence_candidates_report_sha256"] = "0" * 64
    elif damage == "alignment_pin": inputs["context_inputs"]["expected_alignment_report_sha256"] = "0" * 64
    else: inputs["context_inputs"]["alignment_inputs"]["expected_document_population_sha256"] = "0" * 64
    with pytest.raises(ValueError): owner.prepare_source_review_handoff(context, **inputs)


@pytest.mark.parametrize("damage", ["drop_piece", "drop_reference", "drop_opportunity", "drop_block_denominator", "crop", "reorder", "admit", "close_obligation", "fake_receipt", "change_source_selector"])
def test_resealed_handoff_cannot_omit_retarget_or_claim_completed_review(tmp_path, damage):
    report, context, inputs = prepared(tmp_path)
    if damage in {"drop_piece", "drop_reference", "drop_opportunity"}:
        kind = {"drop_piece": "original_parent_partition_piece", "drop_reference": "original_unresolved_surface_reference",
            "drop_opportunity": "exact_declared_markup_statute_block_opportunity"}[damage]
        report["queue_units"].remove(next(u for u in report["queue_units"] if u["unit_kind"] == kind))
    elif damage == "drop_block_denominator": report["official_block_denominator"].pop()
    elif damage == "crop": report["queue_units"][0]["original_observation"]["selector"]["text"] = "cropped"
    elif damage == "reorder": report["queue_units"].reverse()
    elif damage == "admit": report["authority"]["admitted"] = True
    elif damage == "close_obligation": report["queue_units"][0]["review_obligations"][0]["closed"] = True
    elif damage == "fake_receipt": report["queue_units"][0]["review_receipt"] = {"approved": True}
    else:
        unit = next(u for u in report["queue_units"] if u["unit_kind"] == "exact_declared_markup_statute_block_opportunity")
        unit["original_observation"]["official_selector"]["char_start"] += 1
    with pytest.raises(ValueError): owner.validate_source_review_handoff(report, context, expected_report_sha256=digest(report), **inputs)


def test_resealed_context_population_deletion_cannot_be_imported_as_review_queue(tmp_path):
    _, context, inputs = prepared(tmp_path)
    context["rows"][0]["partition_piece_contexts"].pop(0)
    inputs["expected_candidate_context_inventory_report_sha256"] = digest(context)
    with pytest.raises(ValueError): owner.prepare_source_review_handoff(context, **inputs)


@pytest.mark.parametrize("limits", [{"max_review_units": 1}, {"max_input_report_bytes": 1}, {"max_report_bytes": 1},
    {"unknown": 1}, {"max_review_units": True}, {"max_review_units": 8193}])
def test_complete_queue_limits_refuse_before_truncation_or_subset_selection(tmp_path, limits):
    _, context, inputs = prepared(tmp_path)
    with pytest.raises(ValueError): owner.prepare_source_review_handoff(context, **inputs, limits=limits)


@pytest.mark.parametrize("damage", ["document_count", "raw_bytes", "nested_document_report_bytes", "parent_row_population", "parent_preflight_depth", "nested_document_report_depth"])
def test_nested_replay_guard_runs_before_handoff_or_context_deepcopy(tmp_path, monkeypatch, damage):
    _, context, inputs = prepared(tmp_path)
    damage_nested_replay(inputs["context_inputs"], damage)
    calls = []
    def snapshot(value):
        calls.append(value)
        raise AssertionError("unqualified handoff replay reached deepcopy")
    monkeypatch.setattr(owner, "deepcopy", snapshot)
    monkeypatch.setattr(owner.contexts, "deepcopy", snapshot)
    with pytest.raises(ValueError): owner.prepare_source_review_handoff(context, **inputs)
    assert calls == []


def _dossier_view(**changes):
    value = {'schema': 'legal-source-edition-context-dossier/v1', 'operative_use_count': 0,
             'operative_uses': [], 'legal_meaning_manufactured': False, 'review_manufactured': False,
             'crosswalk_status': 'missing',
             'authority': {'source_review_completed': False, 'legal_review_completed': False}}
    value.update(changes)
    return value


def test_dossier_review_questions_stay_pending_and_do_not_replay_handoff(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError('review handoff replay is not a dossier question binding')
    monkeypatch.setattr(owner, 'prepare_source_review_handoff', refused)
    bound = owner.bind_source_dossier_review_questions(_dossier_view())
    assert [item['kind'] for item in bound['review_obligations']] == list(owner.REVIEW_OBLIGATION_KINDS)
    assert all(item['status'] == 'pending_independent_review' and item['verified'] is False
               and item['closed'] is False for item in bound['review_obligations'])
    assert bound['actual_review_receipts_created'] is False
    assert bound['legal_role_classification_performed'] is False
    assert all(value is False for value in bound['authority'].values())


@pytest.mark.parametrize('changes', [
    {'operative_use_count': 2, 'operative_uses': ['first', 'second']},
    {'review_manufactured': True},
    {'legal_meaning_manufactured': True},
    {'crosswalk_status': 'verified'},
    {'authority': {'source_review_completed': True}},
])
def test_dossier_review_binding_refuses_manufactured_meaning_or_uses(changes):
    with pytest.raises(ValueError):
        owner.bind_source_dossier_review_questions(_dossier_view(**changes))
