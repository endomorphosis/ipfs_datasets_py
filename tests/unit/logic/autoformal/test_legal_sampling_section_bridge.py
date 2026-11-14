"""Real official-sampler/primary-index joins remain source-review nominations."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_span_section_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as review
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_reconstruction as reconstruction
from ipfs_datasets_py.logic.autoformal.legal_primary_section_index import PrimarySectionIndex
from tests.unit.logic.autoformal.test_legal_source_sampling_review import prepared, fixture, inputs
from tests.unit.logic.autoformal.test_legal_span_section_bridge import open_index, LEGAL_ID, SOURCE_REVISION, cid
from tests.unit.logic.autoformal.test_legal_source_graph_proposals import release_point_index
from tests.unit.logic.autoformal.test_legal_primary_graph_reconstruction import (
    fixture as graph_fixture, node, wrapped,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def request(index, replay, bundle, selected=None):
    refs = deepcopy(selected if selected is not None else [guide["subject_ref"] for guide in bundle["guides"][:2]])
    return dict(expected_bundle_sha256=review.sampling_review_bundle_sha256(bundle),
        selected_subject_refs=refs, expected_selected_subjects_sha256=bridge.sampling_section_subjects_sha256(refs),
        section_index=index, expected_section_index_sha256=index.index_sha256, **replay)


def assert_inert(report):
    assert report["status"] == "source_review_candidates_only"
    assert report["review_response_count"] == report["semantic_graph_assertions"] == 0
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert all(value is False for value in report["authority"].values())
    assert report["correspondence"]["edition_mapping"] is None
    assert report["correspondence"]["historical_cache_binding"] is None
    for row in report["rows"]:
        assert row["meaning_target"] is row["typed_IR"] is None
        assert row["training_mask"] == row["evaluation_gold_mask"] == 0
        assert all(value is False for value in row["authority"].values())


def test_real_sampler_and_primary_owners_retain_complete_populations_and_exact_selected_inputs(tmp_path, monkeypatch):
    raw, replay, bundle = prepared()
    source_before = digest(bundle)
    owner = review.validate_sampling_review_bundle
    calls = []
    def observed(*args, **kwargs):
        calls.append(kwargs["expected_bundle_sha256"])
        return owner(*args, **kwargs)
    monkeypatch.setattr(review, "validate_sampling_review_bundle", observed)
    with open_index(tmp_path) as index:
        trusted = request(index, replay, bundle)
        report = bridge.reconcile_sampling_sections(bundle, raw, **trusted)
        assert calls == [trusted["expected_bundle_sha256"]]
        assert report["sampling_population"]["counts"] == bundle["manifest"]["counts"]
        assert report["sampling_population"]["sampler_counts"] == bundle["sampling_report"]["counts"]
        assert report["sampling_population"]["counts"]["subjects"] > report["selected_count"] == 2
        assert report["section_lookup"] == index.lookup_sections(LEGAL_ID)
        assert report["section_disposition"] == "unique_literal_section_nomination_only"
        assert report["source_identity"]["edition"] == 2024
        assert report["primary_identity"]["source_revision"] == SOURCE_REVISION
        assert report["correspondence"]["primary_release_point"] == "us/pl/119/102"
        for offset, row in enumerate(report["rows"]):
            assert row["guide"] == bundle["guides"][offset]
            assert row["subject_ref"] == trusted["selected_subject_refs"][offset]
            for field in ("source_version", "source_occurrence", "context_declaration"):
                assert row[field] in bundle["sampling_report"]["records"]
        assert_inert(report)
        assert bridge.validate_sampling_section_bridge(report, bundle, raw,
            expected_bridge_sha256=bridge.sampling_section_bridge_sha256(report), **trusted) == report
    assert digest(bundle) == source_before


@pytest.mark.parametrize("missing,duplicate,expected,count", [
    (True, False, "section_candidate_missing", 0),
    (False, True, "section_candidate_ambiguous", 2),
])
def test_missing_and_ambiguous_sections_keep_all_candidates_without_first_match(tmp_path, missing, duplicate, expected, count):
    raw, replay, bundle = prepared()
    with open_index(tmp_path, missing=missing, duplicate=duplicate) as index:
        report = bridge.reconcile_sampling_sections(bundle, raw, **request(index, replay, bundle))
    assert report["section_disposition"] == expected
    assert len(report["section_lookup"]["sections"]) == count
    assert report["selected_count"] == 2
    assert_inert(report)


def test_package_and_release_relationship_records_are_preserved_without_edition_inference(tmp_path):
    raw, replay, bundle = prepared()
    with release_point_index(tmp_path) as index:
        report = bridge.reconcile_sampling_sections(bundle, raw, **request(index, replay, bundle))
    section, = report["section_lookup"]["sections"]
    assert section["source_packages"][0]["entry_cid"] == cid("package")
    point, = section["release_points"]
    assert point["entry_cid"] == cid("release-point")
    assert point["has_source_observations"][0]["declared_identity"]["entry_cid"] == cid("release-relation")
    assert report["correspondence"]["source_package_candidates"] == 1
    assert report["correspondence"]["recognized_release_point_candidates"] == 1
    assert_inert(report)


def test_unique_section_without_source_package_keeps_the_missing_relationship_gap(tmp_path):
    raw, replay, bundle = prepared()
    selection, root, pins = graph_fixture(tmp_path, nodes=[wrapped(node("section"))], edges=[])
    candidate = tmp_path/"candidate.jsonl"
    reconstructed = reconstruction.reconstruct_to_jsonl(selection, root, candidate, **pins)
    with PrimarySectionIndex(candidate, reconstruction_report=reconstructed,
            expected_candidate_sha256=reconstructed["candidate_sha256"],
            expected_reconstruction_sha256=reconstructed["reconstruction_sha256"]) as index:
        report = bridge.reconcile_sampling_sections(bundle, raw, **request(index, replay, bundle))
    assert report["section_disposition"] == "unique_literal_section_nomination_only"
    assert report["correspondence"]["source_package_candidates"] == 0
    assert "section_has_no_declared_source_package" in {issue["code"] for issue in report["issues"]}
    assert_inert(report)


def test_equal_source_text_at_two_positions_keeps_distinct_review_subjects_and_occurrences(tmp_path):
    raw, replay, bundle = prepared(statute='<p class="statutory-body">Café officer acts.</p>'*2)
    wanted = [guide["subject_ref"] for guide in bundle["guides"] if guide["sampling_stratum"] == "candidate_statute_paragraph"]
    with open_index(tmp_path) as index:
        report = bridge.reconcile_sampling_sections(bundle, raw, **request(index, replay, bundle, wanted))
    first, second = report["rows"]
    assert first["source_occurrence"]["span_text"] == second["source_occurrence"]["span_text"]
    assert first["source_occurrence"]["record_cid"] != second["source_occurrence"]["record_cid"]
    assert first["subject_ref"] != second["subject_ref"]


@pytest.mark.parametrize("damage", ["empty", "kind", "boolean_index", "negative", "duplicate", "order", "extra", "sha", "overflow"])
def test_malformed_subject_selection_is_rejected_before_operation_owners(tmp_path, monkeypatch, damage):
    raw, replay, bundle = prepared()
    refs = deepcopy([guide["subject_ref"] for guide in bundle["guides"][:2]])
    if damage == "empty": refs = []
    elif damage == "kind": refs[0]["kind"] = "withheld_context"
    elif damage == "boolean_index": refs[0]["index"] = False
    elif damage == "negative": refs[0]["index"] = -1
    elif damage == "duplicate": refs[1] = deepcopy(refs[0])
    elif damage == "order": refs.reverse()
    elif damage == "extra": refs[0]["ignored"] = True
    elif damage == "sha": refs[0]["sha256"] = "short"
    else: refs[1]["index"] = 4096
    def forbidden(): pytest.fail("malformed selection reached operational owners")
    monkeypatch.setattr(bridge, "_sampling_owners", forbidden)
    with pytest.raises(ValueError):
        bridge.reconcile_sampling_sections(bundle, raw, expected_bundle_sha256=digest(bundle),
            selected_subject_refs=refs, expected_selected_subjects_sha256=digest(refs),
            section_index=None, expected_section_index_sha256="f"*64, **replay)


@pytest.mark.parametrize("damage", ["bundle_pin", "selection_pin", "raw_bytes", "raw_pin", "raw_length", "descriptor_pin", "sampler_pin", "extra_input"])
def test_original_pins_and_input_types_are_checked_before_operation_owners(tmp_path, monkeypatch, damage):
    raw, replay, bundle = prepared()
    with open_index(tmp_path) as index:
        trusted = request(index, replay, bundle)
        if damage == "bundle_pin": trusted["expected_bundle_sha256"] = "0"*64
        elif damage == "selection_pin": trusted["expected_selected_subjects_sha256"] = "0"*64
        elif damage == "raw_bytes": raw = bytearray(raw)
        elif damage == "raw_pin": trusted["expected_raw_sha256"] = "0"*64
        elif damage == "raw_length": trusted["expected_raw_bytes"] = True
        elif damage == "descriptor_pin": trusted["expected_descriptor_sha256"] = "0"*64
        elif damage == "sampler_pin": trusted["expected_sampling_report_sha256"] = "0"*64
        else: trusted["ignored"] = True
        def forbidden(): pytest.fail("malformed original pins reached operational owners")
        monkeypatch.setattr(bridge, "_sampling_owners", forbidden)
        with pytest.raises(ValueError): bridge.reconcile_sampling_sections(bundle, raw, **trusted)


def test_same_bytes_from_other_edition_do_not_authorize_foreign_subject_refs(tmp_path):
    raw, replay, original = prepared()
    different = inputs(raw)
    descriptor = different["descriptor"]
    descriptor["edition"] = 2025
    for key in ("package_id", "granule_id", "url"): descriptor[key] = descriptor[key].replace("2024", "2025")
    for key in ("requested_url", "final_url"): descriptor["http_provenance"][key] = descriptor["url"]
    different["expected_descriptor_sha256"] = custody.acquisition_descriptor_sha256(descriptor)
    sampling = sampler.prepare_source_sampling(raw, **different)
    different["expected_sampling_report_sha256"] = sampler.source_sampling_report_sha256(sampling)
    other = review.prepare_sampling_review_bundle(raw, **different)
    assert original["guides"][0]["subject_ref"] != other["guides"][0]["subject_ref"]
    with open_index(tmp_path) as index:
        trusted = request(index, replay, original, [other["guides"][0]["subject_ref"]])
        with pytest.raises(ValueError, match="selected subject differs"):
            bridge.reconcile_sampling_sections(original, raw, **trusted)


def test_withheld_fragment_is_explicitly_unsupported_instead_of_losing_parent_context(tmp_path):
    raw, replay, bundle = prepared(statute='<p class="statutory-body">The officer shall act<br>only if approved.</p>')
    unit = next(row for row in bundle["sampling_report"]["records"] if row.get("paragraph_fragment_withheld") is True)
    ref = {"kind": "unit", "index": unit["ordinal"], "sha256": digest(unit)}
    with open_index(tmp_path) as index:
        with pytest.raises(ValueError, match="withheld paragraph fragment"):
            bridge.reconcile_sampling_sections(bundle, raw, **request(index, replay, bundle, [ref]))


@pytest.mark.parametrize("damage", ["guide", "unselected_unit", "boolean_authority"])
def test_resealed_complete_bundle_cannot_change_selected_or_unselected_source(tmp_path, damage):
    raw, replay, bundle = prepared()
    with open_index(tmp_path) as index:
        trusted = request(index, replay, bundle)
        if damage == "guide": bundle["guides"][0]["status"] = "reviewed"
        elif damage == "boolean_authority": bundle["guides"][0]["authority"]["meaning_admitted"] = 0
        else: bundle["guides"][-1]["response_template"]["source_answers"][0]["rationale"] = "invented"
        trusted["expected_bundle_sha256"] = digest(bundle)
        with pytest.raises(ValueError): bridge.reconcile_sampling_sections(bundle, raw, **trusted)


@pytest.mark.parametrize("damage", ["lookup", "source", "guide", "population", "authority", "selection", "unknown", "integer_authority"])
def test_full_output_replay_rejects_resealed_changes(tmp_path, damage):
    raw, replay, bundle = prepared()
    with open_index(tmp_path) as index:
        trusted = request(index, replay, bundle)
        report = bridge.reconcile_sampling_sections(bundle, raw, **trusted)
        if damage == "lookup": report["section_lookup"]["sections"][0]["source_packages"] = []
        elif damage == "source": report["source_identity"]["edition"] = 2025
        elif damage == "guide": report["rows"][0]["guide"]["status"] = "reviewed"
        elif damage == "population": report["sampling_population"]["counts"]["subjects"] = report["selected_count"]
        elif damage == "authority": report["authority"]["edition_correspondence_verified"] = True
        elif damage == "selection": report["selected_subject_refs"].reverse()
        elif damage == "unknown": report["unexpected"] = "retain?"
        else: report["authority"]["formalized"] = 0
        with pytest.raises(ValueError, match="complete independent replay"):
            bridge.validate_sampling_section_bridge(report, bundle, raw,
                expected_bridge_sha256=digest(report), **trusted)


def test_index_pin_is_not_replaced_by_unique_legal_id_and_output_bound_precedes_lookup(tmp_path, monkeypatch):
    raw, replay, bundle = prepared()
    with open_index(tmp_path) as index:
        trusted = request(index, replay, bundle)
        def forbidden(*args): pytest.fail("invalid pin or impossible output bound reached lookup")
        monkeypatch.setattr(PrimarySectionIndex, "lookup_sections", forbidden)
        with pytest.raises(ValueError, match="index pin differs"):
            bridge.reconcile_sampling_sections(bundle, raw, **{**trusted, "expected_section_index_sha256": "0"*64})
        with pytest.raises(ValueError):
            bridge.reconcile_sampling_sections(bundle, raw, **trusted, limits={"max_output_bytes": 1})


@pytest.mark.parametrize("damage", ["legal_id", "primary_identity", "index_pin"])
def test_changed_guarded_lookup_response_is_not_silently_normalized(tmp_path, monkeypatch, damage):
    raw, replay, bundle = prepared()
    original = PrimarySectionIndex.lookup_sections
    with open_index(tmp_path) as index:
        trusted = request(index, replay, bundle)
        def changed(self, legal_id):
            value = original(self, legal_id)
            if damage == "legal_id": value["legal_id"] = legal_id.upper()
            elif damage == "primary_identity": value["primary_identity"]["revision"] = "e"*40
            else: value["index_sha256"] = "0"*64
            return value
        monkeypatch.setattr(PrimarySectionIndex, "lookup_sections", changed)
        with pytest.raises(ValueError, match="lookup identity differs"):
            bridge.reconcile_sampling_sections(bundle, raw, **trusted)
