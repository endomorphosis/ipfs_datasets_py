"""Complete blank source-review packets preserve custody and create no reviews."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import unicodedata
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_source_review as source_review
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pretty(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()


def fixture_helper():
    """Reuse authored fixtures; all product operations use real public owners."""
    spec = importlib.util.spec_from_file_location(
        "authored_source_review_fixture_for_packet_tests",
        Path(__file__).with_name("test_corpus_source_review.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case(tmp_path, **options):
    helper = fixture_helper()
    data = helper.case(tmp_path, **options)
    inherited = helper.prepare(source_review, data)
    return {
        "source_data": data,
        "preparation": inherited,
        "arguments": {
            **data["arguments"],
            "expected_preparation_manifest_sha256": sha(canonical_dag_json_bytes(inherited["manifest"])),
        },
    }


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_source_review_packets

    return corpus_source_review_packets


@pytest.fixture(scope="module")
def fixture_data(tmp_path_factory):
    return case(tmp_path_factory.mktemp("original-source-packet-inputs"))


def build(owner, data, **options):
    return owner.prepare_source_review_packets(**data["arguments"], **options)


def validate(owner, bundle, data, **options):
    return owner.validate_source_review_packets(bundle, **data["arguments"], **options)


def reseal(record):
    return contracts.seal_record({
        key: deepcopy(value) for key, value in record.items() if key not in {"record_cid", "cid_scope"}
    })


def records(bundle):
    for key, values in bundle.items():
        if key == "manifest":
            yield values
        else:
            yield from values


def producer_refusal(*_args, **_kwargs):
    pytest.fail("untrusted input reached inherited source preparation before boundary refusal")


@pytest.fixture(scope="module")
def baseline_bundle(fixture_data):
    from ipfs_datasets_py.logic.autoformal import corpus_source_review_packets

    return build(corpus_source_review_packets, fixture_data)


def ref(record):
    return {"record_cid": record["record_cid"], "sha256": sha(canonical_dag_json_bytes(record)), "schema": record["schema"]}


def pointer(value, path):
    for part in path.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if type(value) is list else value[part]
    return value


def reconstruct_transport(transport, parts):
    """Independent lossless oracle; never use the product reconstruction helper."""
    if transport is None:
        return None
    result = deepcopy(transport["head"])
    seen = set()
    for field in transport["list_fields"]:
        original = []
        for reference in field["part_refs"]:
            part = parts[reference["record_cid"]]
            assert reference == ref(part)
            assert part["record_cid"] not in seen
            seen.add(part["record_cid"])
            assert part["document_index"] == transport["document_index"]
            assert part["report_kind"] == transport["report_kind"]
            assert part["field_pointer"] == field["json_pointer"]
            assert type(part["first_item_index"]) is int and part["first_item_index"] == len(original)
            assert type(part["item_count"]) is int and part["item_count"] == len(part["values"])
            assert part["values_sha256"] == sha(canonical_dag_json_bytes(part["values"]))
            assert part["original_list_sha256"] == field["original_list_sha256"]
            original.extend(deepcopy(part["values"]))
        assert len(original) == field["item_count"]
        assert sha(canonical_dag_json_bytes(original)) == field["original_list_sha256"]
        keys = [part.replace("~1", "/").replace("~0", "~") for part in field["json_pointer"][1:].split("/")]
        parent = result
        for key in keys[:-1]:
            parent = parent[key]
        assert keys[-1] not in parent
        parent[keys[-1]] = original
    assert sha(canonical_dag_json_bytes(result)) == transport["original_value_sha256"]
    return result


def rebind_bundle(bundle):
    """Repair custody refs/seals after a mutation; original replay must still win."""
    replacements = {}

    def replace(value):
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            result = {key: replace(item) for key, item in value.items()}
            cid = result.get("record_cid")
            old = replacements.get(cid) if type(cid) is str else None
            if old is not None and "sha256" in result:
                result.update(old)
            return result
        return value

    for group in (
        "source_views", "document_parts", "official_documents", "selector_projections", "comparison_evidence", "question_catalog",
        "unit_packets", "response_guides", "parent_packets", "pages",
    ):
        for index, record in enumerate(bundle[group]):
            original_cid = record["record_cid"]
            updated = reseal(replace(record))
            bundle[group][index] = updated
            replacements[original_cid] = ref(updated)
    bundle["manifest"] = reseal(replace(bundle["manifest"]))
    return bundle


def test_complete_packet_population_embeds_exact_unchanged_source_requests_and_origins(owner, fixture_data, baseline_bundle):
    bundle = baseline_bundle
    inherited = fixture_data["preparation"]
    source_data = fixture_data["source_data"]
    assert set(bundle) == set(owner.COMPONENTS)
    assert bundle["manifest"]["source_preparation_ref"] == ref(inherited["manifest"])
    assert bundle["manifest"]["source_input_bindings"] == inherited["manifest"]["input_bindings"]
    assert len(bundle["unit_packets"]) == len(bundle["response_guides"]) == len(inherited["requests"])
    for unit, request, subject, dependency in zip(
        bundle["unit_packets"], inherited["requests"], inherited["subjects"], inherited["dependency_manifests"], strict=True
    ):
        assert unit["source_review_request"] == request
        assert unit["queue_ordinal"] == request["queue_ordinal"]
        assert unit["source_review_subject_ref"] == ref(subject)
        assert unit["dependency_manifest_sha256"] == dependency["manifest_sha256"]
        assert unit["original_queue_unit"] == source_data["source_reports"]["handoff"]["queue_units"][request["queue_ordinal"]]
        original = request["original_context_binding"]
        assert unit["original_context_unit"] == (
            None if original is None else pointer(source_data["source_reports"]["context"], original["json_pointer"])
        )
        assert [row["record_cid"] for row in unit["comparison_record_refs"]] == request["comparison_record_cids"]
        assert unit["candidate_interpretations_included"] is False
    assert validate(owner, bundle, fixture_data) == bundle


def test_parent_groups_preserve_each_request_and_all_competing_comparison_documents(owner, fixture_data, baseline_bundle):
    bundle = baseline_bundle
    inherited = fixture_data["preparation"]
    observed = []
    expected_documents = [ref(record) for record in bundle["official_documents"]]
    original_comparisons = [record for record in fixture_data["source_data"]["alignment_corpus"]["records"] if record.get("kind") == "comparison"]
    for index, packet in enumerate(bundle["parent_packets"]):
        expected = [request for request in inherited["requests"] if request["parent_index"] == index]
        assert packet["parent_index"] == index
        assert [row["request_cid"] for row in packet["unit_refs"]] == [request["record_cid"] for request in expected]
        assert [row["ordinal"] for row in packet["unit_refs"]] == [request["queue_ordinal"] for request in expected]
        assert packet["official_document_refs"] == expected_documents
        assert packet["comparison_record_refs"] == [ref(row) for row in original_comparisons if row["parent_index"] == index]
        assert len(packet["comparison_record_refs"]) == len(expected_documents)
        assert packet["candidate_interpretations_included"] is False
        observed.extend(packet["unit_refs"])
    assert [row["request_cid"] for row in sorted(observed, key=lambda row: row["ordinal"])] == [row["record_cid"] for row in inherited["requests"]]
    assert len({row["request_cid"] for row in observed}) == len(observed)
    counts = bundle["manifest"]["counts"]
    assert counts["parent_unit_counts"] == [len(packet["unit_refs"]) for packet in bundle["parent_packets"]]
    assert counts["units"] == len(observed)
    assert counts["recorded_reviews"] == 0


def test_full_shared_views_bind_exact_original_text_profiles_and_every_membership(owner, fixture_data, baseline_bundle):
    bundle = baseline_bundle
    aligned = fixture_data["source_data"]["alignment_data"]["alignment"]
    for view in bundle["source_views"]:
        text = view["text"]
        assert view["text_sha256"] == sha(text.encode())
        assert view["char_count"] == len(text)
        assert view["utf8_bytes"] == len(text.encode())
        version = view["source_version_record"]
        assert version["record_cid"] == view["source_version_cid"]
        assert version["extracted_view"]["sha256"] == view["text_sha256"]
        assert version["extracted_view"]["cid"] == view["text_cid"]
        assert view["coordinate_system"] == version["extracted_view"]["coordinate_system"]
        assert len(view["original_field_bindings"]) == len(view["source_observation_memberships"])
        for binding in view["original_field_bindings"]:
            original = pointer(aligned, binding["json_pointer"])
            assert original == text
            assert binding["value_sha256"] == sha(canonical_dag_json_bytes(original))
    assert Counter(view["origin_kind"] for view in bundle["source_views"]) == bundle["manifest"]["counts"]["source_view_kinds"]
    assert len({view["source_version_cid"] for view in bundle["source_views"]}) == len(bundle["source_views"])
    assert any("雪" in view["text"] for view in bundle["source_views"])


def test_shared_projection_catalog_resolves_every_original_context_reference_without_selector_coercion(
    owner, fixture_data, baseline_bundle
):
    context = fixture_data["source_data"]["source_reports"]["context"]
    views = {row["record_cid"]: row for row in baseline_bundle["source_views"]}
    projections = baseline_bundle["selector_projections"]
    assert len(projections) == len(context["selector_projection_table"])
    for index, record in enumerate(projections):
        original = context["selector_projection_table"][index]
        assert record["projection_index"] == index
        assert record["original_projection"] == original
        assert record["original_context_binding"]["json_pointer"] == f"/selector_projection_table/{index}"
        assert record["original_context_binding"]["value_sha256"] == sha(canonical_dag_json_bytes(original))
        view = views[record["full_source_view_ref"]["record_cid"]]
        assert record["full_source_view_ref"] == ref(view)
        assert record["quoted_text"] == view["text"][original["char_start"]:original["char_end"]]
        assert sha(record["quoted_text"].encode()) == original["text_sha256"]
        if original["coordinate_space"] == "parent_literal_field":
            left, right = original["utf8byte_start"], original["utf8byte_end"]
            assert view["origin_kind"] == "parent_literal_field"
        else:
            assert original["coordinate_space"] == "official_normalized_view"
            left, right = original["utf8_byte_start"], original["utf8_byte_end"]
            assert view["origin_kind"] == "official_normalized"
        assert view["text"].encode()[left:right] == record["quoted_text"].encode()
        assert record["coordinate_system"] == view["coordinate_system"]

    referenced = []

    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if value.get("schema") == "legal-candidate-context-selector-reference/v1":
                index = value["selector_projection_index"]
                assert type(index) is int and 0 <= index < len(projections)
                referenced.append(index)
            for item in value.values():
                walk(item)

    for unit in baseline_bundle["unit_packets"]:
        walk(unit["original_context_unit"])
    assert referenced
    assert baseline_bundle["manifest"]["selector_projection_refs"] == [ref(row) for row in projections]
    assert baseline_bundle["manifest"]["counts"]["selector_projections"] == len(projections)


def test_every_comparison_cell_retains_complete_original_alignment_context_and_core_evidence(
    owner, fixture_data, baseline_bundle
):
    source_data = fixture_data["source_data"]
    aligned = source_data["alignment_data"]["alignment"]
    context = source_data["source_reports"]["context"]
    originals = {(row["parent_index"], row["document_index"]): row for row in source_data["alignment_corpus"]["records"] if row.get("kind") == "comparison"}
    contexts = {(row["parent_index"], row["document_index"]): row for row in context["comparison_table"]}
    evidence = baseline_bundle["comparison_evidence"]
    assert [(row["parent_index"], row["document_index"]) for row in evidence] == [
        (parent, document) for parent in range(len(baseline_bundle["parent_packets"]))
        for document in range(len(baseline_bundle["official_documents"]))
    ]
    for record in evidence:
        parent, document = record["parent_index"], record["document_index"]
        assert record["comparison_record"] == originals[(parent, document)]
        assert record["original_alignment_comparison"] == aligned["rows"][parent]["comparisons"][document]
        assert record["original_context_comparison"] == contexts[(parent, document)]
        for field, original_report in (("original_alignment_binding", aligned), ("original_context_binding", context)):
            binding = record[field]
            assert binding["value_sha256"] == sha(canonical_dag_json_bytes(pointer(original_report, binding["json_pointer"])))
    assert baseline_bundle["manifest"]["comparison_evidence_refs"] == [ref(row) for row in evidence]
    assert baseline_bundle["manifest"]["original_context_authority"] == context["authority"]
    assert all(value is False for value in baseline_bundle["manifest"]["original_context_authority"].values())


def test_official_document_acquisitions_keep_full_block_event_and_fragment_structures(owner, fixture_data, baseline_bundle):
    originals = fixture_data["source_data"]["alignment_data"]["alignment"]["official_documents"]
    parts = {row["record_cid"]: row for row in baseline_bundle["document_parts"]}
    for index, record in enumerate(baseline_bundle["official_documents"]):
        assert record["document_index"] == index
        assert reconstruct_transport(record["view_report_transport"], parts) == originals[index]["view_report"]
        assert reconstruct_transport(record["rendered_field_transport"], parts) == originals[index]["rendered_field_view"]
        assert record["original_input_identity"] == originals[index]["input_identity"]
        assert record["normalized_view_ref"] != record["rendered_view_ref"]
        assert record["original_alignment_binding"]["json_pointer"] == f"/official_documents/{index}"
        for transport, kind in ((record["view_report_transport"], "view_report"), (record["rendered_field_transport"], "rendered_field_view")):
            assert transport["original_field_binding"]["json_pointer"] == f"/official_documents/{index}/{kind}"
            assert transport["original_field_binding"]["value_sha256"] == sha(canonical_dag_json_bytes(originals[index][kind]))
    assert baseline_bundle["manifest"]["document_part_refs"] == [ref(row) for row in baseline_bundle["document_parts"]]
    assert baseline_bundle["manifest"]["counts"]["document_parts"] == len(parts)


def test_every_quoted_occurrence_has_exact_full_view_unicode_and_utf8_geometry(owner, fixture_data, baseline_bundle):
    views = {row["record_cid"]: row for row in baseline_bundle["source_views"]}
    for unit in baseline_bundle["unit_packets"]:
        quote = unit["quoted_source_occurrence"]
        assert quote is not None
        occurrence = quote["source_occurrence_record"]
        view = views[quote["full_source_view_ref"]["record_cid"]]
        assert quote["full_source_view_ref"] == ref(view)
        assert occurrence["source_version_cid"] == view["source_version_cid"]
        assert occurrence["record_cid"] == unit["source_review_request"]["source_occurrence_cid"]
        assert view["text"][occurrence["start_char"]:occurrence["end_char"]] == occurrence["span_text"]
        assert view["text"].encode()[occurrence["start_utf8"]:occurrence["end_utf8"]] == occurrence["span_text"].encode()
        assert len(view["text"][:occurrence["start_char"]].encode()) == occurrence["start_utf8"]
        assert len(view["text"][:occurrence["end_char"]].encode()) == occurrence["end_utf8"]
        assert quote["coordinate_system"] == occurrence["coordinate_system"]
        assert quote["raw_HTML_coordinate_mapping_verified"] is False
        context = quote["source_context_record"]
        assert context["record_cid"] == unit["source_review_request"]["context_cid"]
        assert context["availability"] == "required_unavailable"
        assert context["dependency_verification"] == "declaration_only"


def test_nine_blank_answer_slots_and_seven_deferred_topics_create_no_review_or_identity(owner, fixture_data, baseline_bundle):
    for guide, unit in zip(baseline_bundle["response_guides"], baseline_bundle["unit_packets"], strict=True):
        request = unit["source_review_request"]
        assert guide["request_cid"] == request["record_cid"]
        assert guide["request_sha256"] == sha(canonical_dag_json_bytes(request))
        assert guide["unit_packet_ref"] == ref(unit)
        assert guide["subject_ref"] == unit["source_review_subject_ref"]
        assert guide["dependency_manifest_sha256"] == unit["dependency_manifest_sha256"]
        assert guide["status"] == "blank_not_a_review"
        assert [row["slot_id"] for row in guide["answers"]] == request["context_slot_ids"]
        assert len(guide["answers"]) == 9
        assert all(row["disposition"] is row["finding"] is row["rationale"] is None and row["evidence_refs"] == [] for row in guide["answers"])
        assert [row["slot_id"] for row in guide["deferred_questions"]] == request["deferred_review_slot_ids"]
        assert len(guide["deferred_questions"]) == 7
        assert all(row["answer"] is None and row["status"] == "deferred_semantic_or_proof_review" for row in guide["deferred_questions"])
        assert guide["reviewer_declaration"] == {
            "principal_id": None, "role": None, "issued_at_utc": None,
            "identity_evidence_refs": [], "independence_evidence_refs": [], "process_evidence_refs": [],
        }
        assert all(value is None for value in guide["exposure_declaration"].values())
        assert guide["required_existing_auth_domain"] == {
            "claim_schema": source_review.CLAIM_SCHEMA, "action": source_review.ACTION, "audience": source_review.AUDIENCE,
        }
    catalog = baseline_bundle["question_catalog"][0]
    assert [(row["category"], row["kind"]) for row in catalog["questions"]] == [
        *(("context", kind) for kind in source_review.CONTEXT_KINDS),
        *(("handoff", kind) for kind in source_review.HANDOFF_KINDS),
    ]
    assert len(catalog["questions"]) == 16
    assert all(row["status"] == "pending_independent_review" and row["verified"] is row["closed"] is False for row in catalog["questions"])
    assert [row["assessment_scope"] for row in catalog["questions"]] == ["source_context_evidence_declaration"] * 9 + ["deferred_semantic_or_proof_review"] * 7


def test_every_packet_record_is_bounded_candidate_unselected_and_sealed(owner, fixture_data, baseline_bundle):
    for record in records(baseline_bundle):
        assert len(canonical_dag_json_bytes(record)) <= contracts.MAX_RECORD_BYTES
        assert record["view"] == "candidate"
        assert record["selected_occurrence"] is record["governing_source_binding"] is None
        for flag in owner.FALSE_FLAGS:
            assert record[flag] is False
        assert reseal(record) == record
    assert baseline_bundle["manifest"]["population_complete"] is True
    assert baseline_bundle["manifest"]["counts"]["blank_active_answers"] == len(baseline_bundle["unit_packets"]) * 9
    assert baseline_bundle["manifest"]["counts"]["deferred_questions"] == len(baseline_bundle["unit_packets"]) * 7


def test_packet_prepare_and_validate_each_regenerate_original_source_preparation_once(owner, fixture_data, baseline_bundle, monkeypatch):
    original = source_review.prepare_source_review_requests
    calls = []

    def observed(**arguments):
        calls.append(True)
        return original(**arguments)

    monkeypatch.setattr(source_review, "prepare_source_review_requests", observed)
    assert build(owner, fixture_data) == baseline_bundle
    assert len(calls) == 1
    assert validate(owner, baseline_bundle, fixture_data) == baseline_bundle
    assert len(calls) == 2


def test_literal_normalization_aliases_are_not_made_into_source_geometry(owner, tmp_path):
    literals = [" É e\u0301 雪 aa under section 12. ", " E\u0301 é 雪 aa under section 12. "]
    assert unicodedata.normalize("NFKC", literals[0]).casefold() == unicodedata.normalize("NFKC", literals[1]).casefold()
    data = case(tmp_path, parent_texts=literals)
    bundle = build(owner, data)
    parents = [row for row in bundle["source_views"] if row["origin_kind"] == "parent_literal_field"]
    assert [row["text"] for row in parents] == literals
    assert parents[0]["source_version_cid"] != parents[1]["source_version_cid"]
    assert parents[0]["text_sha256"] != parents[1]["text_sha256"]
    assert all(row["utf8_bytes"] > row["char_count"] for row in parents)
    assert validate(owner, bundle, data) == bundle


def test_identical_parent_literals_and_overlapping_roles_do_not_merge_review_units(owner, tmp_path):
    data = case(tmp_path, parent_texts=["aa", "aa"])
    bundle = build(owner, data)
    parents = [row for row in bundle["source_views"] if row["origin_kind"] == "parent_literal_field"]
    assert parents[0]["text"] == parents[1]["text"] == "aa"
    assert parents[0]["source_version_cid"] != parents[1]["source_version_cid"]
    requests = [unit["source_review_request"] for unit in bundle["unit_packets"]]
    assert len(requests) == len(data["preparation"]["requests"])
    assert any(count > 1 for count in Counter(row["source_occurrence_cid"] for row in requests).values())
    assert len({row["record_cid"] for row in requests}) == len(requests)
    assert len(bundle["response_guides"]) == len(requests)
    assert {row["unit_kind"] for row in requests} == {"original_parent_partition_piece", "exact_declared_markup_statute_block_opportunity"}
    assert len({row["parent_record_cid"] for row in requests}) == 2
    assert validate(owner, bundle, data) == bundle


def test_missing_parent_and_official_views_remain_explicit_with_all_original_competitors(owner, tmp_path):
    helper = fixture_helper().fixture_helper()
    data = case(tmp_path, parent_texts=[None, "No matching text."], docs=[helper.missing_document(), helper.document(2)])
    bundle = build(owner, data)
    assert len(bundle["parent_packets"]) == len(bundle["official_documents"]) == 2
    assert bundle["parent_packets"][0]["parent_view_ref"] is None
    assert bundle["official_documents"][0]["normalized_view_ref"] is None
    assert bundle["official_documents"][0]["rendered_view_ref"] is None
    assert bundle["official_documents"][0]["rendered_field_transport"] is None
    missing = [unit for unit in bundle["unit_packets"] if unit["parent_index"] == 0]
    assert len(missing) == 1
    assert missing[0]["source_review_request"]["unit_kind"] == "unavailable_parent_text_observation"
    assert missing[0]["quoted_source_occurrence"] is missing[0]["parent_view_ref"] is None
    assert all(len(packet["comparison_record_refs"]) == 2 for packet in bundle["parent_packets"])
    assert validate(owner, bundle, data) == bundle


def test_duplicate_acquisitions_share_immutable_views_and_preserve_each_custody_membership(owner, tmp_path):
    helper = fixture_helper().fixture_helper()
    first = helper.document()
    second = deepcopy(first)
    second["descriptor"]["retrieved_at"] = "2026-10-14T12:00:00+00:00"
    second["expected_descriptor_sha256"] = sha(canonical(second["descriptor"]))
    from ipfs_datasets_py.logic.autoformal import legal_official_document_views

    second["view_report"] = legal_official_document_views.prepare_official_document_view(
        second["raw_bytes"], **{key: second[key] for key in (
            "descriptor", "expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes"
        )},
    )
    second["expected_view_report_sha256"] = sha(canonical(second["view_report"]))
    data = case(tmp_path, docs=[first, second])
    bundle = build(owner, data)
    documents = bundle["official_documents"]
    assert len(documents) == 2 and documents[0]["record_cid"] != documents[1]["record_cid"]
    assert documents[0]["normalized_view_ref"] == documents[1]["normalized_view_ref"]
    assert documents[0]["rendered_view_ref"] == documents[1]["rendered_view_ref"]
    shared = [row for row in bundle["source_views"] if row["origin_kind"].startswith("official")]
    assert len(shared) == 2
    assert all([membership["document_index"] for membership in row["source_observation_memberships"]] == [0, 1] for row in shared)
    assert all(len(row["original_field_bindings"]) == 2 for row in shared)
    assert validate(owner, bundle, data) == bundle


def test_large_real_official_structures_are_lossless_parts_without_increasing_any_record_envelope(owner, tmp_path):
    helper = fixture_helper().fixture_helper()
    item = helper.document(1)
    paragraphs = "".join(f"<p>Café independent structural paragraph {index:04d}.</p>" for index in range(2200))
    raw = (
        '<html><head><meta charset="utf-8"><title>Retained structure</title></head><body>'
        '<h3 class="section-head">§1. Heading</h3><!-- field-start:statute -->'
        + paragraphs + '<!-- field-end:statute --></body></html>'
    ).encode()
    item = helper.redocument(item, raw)
    data = case(tmp_path, parent_texts=["Only unmatched source sample."], docs=[item])
    original = data["source_data"]["alignment_data"]["alignment"]["official_documents"][0]
    assert len(canonical_dag_json_bytes(original["view_report"])) > contracts.MAX_RECORD_BYTES
    assert len(original["view_report"]["document"]["blocks"]) >= 2200
    bundle = build(owner, data)
    parts = {row["record_cid"]: row for row in bundle["document_parts"]}
    document = bundle["official_documents"][0]
    assert reconstruct_transport(document["view_report_transport"], parts) == original["view_report"]
    assert reconstruct_transport(document["rendered_field_transport"], parts) == original["rendered_field_view"]
    assert all(len(canonical_dag_json_bytes(record)) <= contracts.MAX_RECORD_BYTES for record in records(bundle))
    assert all(0 < record["item_count"] <= owner.DEFAULT_LIMITS["max_document_part_items"] for record in parts.values())
    assert bundle["manifest"]["counts"]["recorded_reviews"] == 0
    assert validate(owner, bundle, data) == bundle


def test_lowered_document_item_cap_repartitions_whole_arrays_without_omitting_structure(owner, fixture_data):
    bundle = build(owner, fixture_data, limits={"max_document_part_items": 1})
    parts = {row["record_cid"]: row for row in bundle["document_parts"]}
    assert parts and all(row["item_count"] == len(row["values"]) == 1 for row in parts.values())
    originals = fixture_data["source_data"]["alignment_data"]["alignment"]["official_documents"]
    for document, original in zip(bundle["official_documents"], originals, strict=True):
        assert reconstruct_transport(document["view_report_transport"], parts) == original["view_report"]
        assert reconstruct_transport(document["rendered_field_transport"], parts) == original["rendered_field_view"]
    assert validate(owner, bundle, fixture_data, limits={"max_document_part_items": 1}) == bundle


@pytest.mark.parametrize("kind", ["atomic_array_item", "scalar_head"])
def test_oversized_atomic_document_item_or_head_refuses_without_truncating_original_values(owner, kind):
    text = "x" * contracts.MAX_RECORD_BYTES
    value = {"items": [{"text": text}]} if kind == "atomic_array_item" else {"literal_head": text}
    retained = []
    with pytest.raises(contracts.CorpusContractError):
        transport = owner._document_transport(
            value, 0, "authored_document_structure_limit_control", {},
            lambda _group, record: retained.append(record), owner._limits(None),
        )
        # The actual writer then places the transport inside its ordinary
        # individually sealed document record; the head has the same1MiB cap.
        owner._candidate(owner.DOCUMENT_SCHEMA, view_report_transport=transport)
    assert retained == []
    assert (value["items"][0]["text"] if kind == "atomic_array_item" else value["literal_head"]) == text


@pytest.mark.parametrize("damage", [
    "part_value", "part_order", "part_start", "part_bool_count", "part_document", "part_kind",
    "part_pointer", "part_value_hash", "transport_head", "transport_refs", "transport_missing", "transport_duplicate",
])
def test_resealed_document_parts_and_transport_heads_cannot_change_original_structure(owner, fixture_data, baseline_bundle, damage):
    bundle = deepcopy(baseline_bundle)
    part = next(row for row in bundle["document_parts"] if len(row["values"]) > 1)
    transport = bundle["official_documents"][part["document_index"]][
        "view_report_transport" if part["report_kind"] == "view_report" else "rendered_field_transport"
    ]
    field = next(row for row in transport["list_fields"] if row["json_pointer"] == part["field_pointer"])
    if damage == "part_value":
        part["values"][0] = {"replacement": "invented extraction observation"}
        part["values_sha256"] = sha(canonical_dag_json_bytes(part["values"]))
    elif damage == "part_order":
        part["values"].reverse()
        part["values_sha256"] = sha(canonical_dag_json_bytes(part["values"]))
    elif damage == "part_start":
        part["first_item_index"] += 1
    elif damage == "part_bool_count":
        part["item_count"] = True
    elif damage == "part_document":
        part["document_index"] = 1 - part["document_index"]
    elif damage == "part_kind":
        part["report_kind"] = "different_original_report"
    elif damage == "part_pointer":
        part["field_pointer"] = "/another_field"
    elif damage == "part_value_hash":
        part["values_sha256"] = "0" * 64
    elif damage == "transport_head":
        transport["head"]["added_observation"] = "invented"
    elif damage == "transport_refs":
        other = next(row for row in bundle["document_parts"] if row["record_cid"] != part["record_cid"])
        field["part_refs"][0] = ref(other)
    elif damage == "transport_missing":
        field["part_refs"] = []
    else:
        field["part_refs"].append(deepcopy(field["part_refs"][0]))
    rebind_bundle(bundle)
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, bundle, fixture_data)


def test_bounded_pages_preserve_exact_global_request_order_and_parent_memberships(owner, fixture_data):
    bundle = build(owner, fixture_data, limits={"max_units_per_page": 2})
    units = bundle["unit_packets"]
    entries = [row for page in bundle["pages"] for row in page["entries"]]
    assert len(bundle["pages"]) > 1
    assert [entry["ordinal"] for entry in entries] == list(range(len(units)))
    assert [entry["request_cid"] for entry in entries] == [unit["source_review_request"]["record_cid"] for unit in units]
    for page, page_ref in zip(bundle["pages"], bundle["manifest"]["page_refs"], strict=True):
        assert len(page["entries"]) <= 2
        assert page_ref["record_cid"] == page["record_cid"]
        assert page_ref["sha256"] == sha(canonical_dag_json_bytes(page))
        assert page_ref["entry_count"] == len(page["entries"])
    assert validate(owner, bundle, fixture_data, limits={"max_units_per_page": 2}) == bundle


@pytest.mark.parametrize("damage", [
    "view_text", "view_membership", "view_binding", "view_origin", "document_view", "document_original",
    "projection_geometry", "projection_quote", "projection_binding", "comparison_original", "comparison_context",
    "parent_missing_unit", "parent_duplicate_unit", "parent_order", "parent_competitor",
    "unit_original", "unit_request", "unit_context", "unit_subject", "unit_dependency", "unit_quote",
    "quote_bool_offset", "quote_stale_span", "quote_byte_offset", "quote_context",
    "guide_finding", "guide_disposition", "guide_identity", "guide_time", "guide_domain", "guide_deferred",
    "guide_order", "catalog_prompt", "manifest_count", "manifest_population", "manifest_authority",
])
def test_resealed_referenced_packets_still_require_exact_original_replay(owner, fixture_data, baseline_bundle, damage):
    bundle = deepcopy(baseline_bundle)
    unit = bundle["unit_packets"][0]
    guide = bundle["response_guides"][0]
    if damage == "view_text":
        bundle["source_views"][0]["text"] += "invented"
    elif damage == "view_membership":
        bundle["source_views"][0]["source_observation_memberships"] = []
    elif damage == "view_binding":
        bundle["source_views"][0]["original_field_bindings"][0]["value_sha256"] = "0" * 64
    elif damage == "view_origin":
        bundle["source_views"][0]["origin_kind"] = "official_normalized"
    elif damage == "document_view":
        bundle["official_documents"][0]["normalized_view_ref"] = bundle["official_documents"][0]["rendered_view_ref"]
    elif damage == "document_original":
        bundle["official_documents"][0]["rendered_field_transport"]["head"]["text"] = "replacement rendered body"
    elif damage == "projection_geometry":
        bundle["selector_projections"][0]["original_projection"]["char_start"] = True
    elif damage == "projection_quote":
        bundle["selector_projections"][0]["quoted_text"] = "unrelated selector text"
    elif damage == "projection_binding":
        bundle["selector_projections"][0]["original_context_binding"]["value_sha256"] = "0" * 64
    elif damage == "comparison_original":
        bundle["comparison_evidence"][0]["original_alignment_comparison"]["parent_partition"] = []
    elif damage == "comparison_context":
        bundle["comparison_evidence"][0]["original_context_comparison"]["selected_source_occurrence"] = "chosen"
    elif damage == "parent_missing_unit":
        del bundle["parent_packets"][0]["unit_refs"][0]
    elif damage == "parent_duplicate_unit":
        bundle["parent_packets"][0]["unit_refs"].append(deepcopy(bundle["parent_packets"][0]["unit_refs"][0]))
    elif damage == "parent_order":
        bundle["parent_packets"][0]["unit_refs"].reverse()
    elif damage == "parent_competitor":
        del bundle["parent_packets"][0]["comparison_record_refs"][0]
    elif damage == "unit_original":
        unit["original_queue_unit"]["status"] = "reviewed"
    elif damage == "unit_request":
        unit["source_review_request"]["admitted"] = True
        unit["source_review_request"] = reseal(unit["source_review_request"])
    elif damage == "unit_context":
        assert unit["original_context_unit"] is not None
        unit["original_context_unit"]["context_dependency_slots"][0]["closure_verified"] = True
    elif damage == "unit_subject":
        unit["source_review_subject_ref"]["sha256"] = "0" * 64
    elif damage == "unit_dependency":
        unit["dependency_manifest_sha256"] = "0" * 64
    elif damage == "unit_quote":
        unit["quoted_source_occurrence"]["raw_HTML_coordinate_mapping_verified"] = True
    elif damage in {"quote_bool_offset", "quote_stale_span", "quote_byte_offset"}:
        occurrence = unit["quoted_source_occurrence"]["source_occurrence_record"]
        if damage == "quote_bool_offset":
            occurrence["start_char"] = True
        elif damage == "quote_stale_span":
            occurrence["span_text"] = "different quoted source"
        else:
            occurrence["end_utf8"] += 1
        unit["quoted_source_occurrence"]["source_occurrence_record"] = reseal(occurrence)
    elif damage == "quote_context":
        context = unit["quoted_source_occurrence"]["source_context_record"]
        context["availability"] = "none_required"
        unit["quoted_source_occurrence"]["source_context_record"] = reseal(context)
    elif damage == "guide_finding":
        guide["answers"][0]["finding"] = "automatic definition found"
    elif damage == "guide_disposition":
        guide["answers"][0]["disposition"] = "not_applicable"
    elif damage == "guide_identity":
        guide["reviewer_declaration"]["principal_id"] = "invented:reviewer"
    elif damage == "guide_time":
        guide["reviewer_declaration"]["issued_at_utc"] = "2026-10-14T12:00:00Z"
    elif damage == "guide_domain":
        guide["required_existing_auth_domain"]["action"] = "record_graph_review_evidence/v1"
    elif damage == "guide_deferred":
        guide["deferred_questions"][0]["answer"] = True
    elif damage == "guide_order":
        guide["answers"].reverse()
    elif damage == "catalog_prompt":
        bundle["question_catalog"][0]["questions"][0]["prompt"] = "Infer a governing definition."
    elif damage == "manifest_count":
        bundle["manifest"]["counts"]["units"] -= 1
    elif damage == "manifest_population":
        bundle["manifest"]["population_complete"] = False
    elif damage == "manifest_authority":
        bundle["manifest"]["training_qualified"] = True
    rebind_bundle(bundle)
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, bundle, fixture_data)


@pytest.mark.parametrize("group", [
    "source_views", "official_documents", "document_parts", "selector_projections", "comparison_evidence",
    "parent_packets", "unit_packets", "response_guides", "question_catalog",
])
def test_missing_nonroot_packet_populations_are_not_qualified_partial_outputs(owner, fixture_data, baseline_bundle, group):
    bundle = deepcopy(baseline_bundle)
    del bundle[group][-1]
    bundle["manifest"] = reseal(bundle["manifest"])
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, bundle, fixture_data)


@pytest.mark.parametrize("damage", ["drop", "reorder", "duplicate", "bool_ordinal", "bad_cid"])
def test_resealed_nonfirst_page_cannot_change_full_request_membership(owner, fixture_data, damage):
    bundle = build(owner, fixture_data, limits={"max_units_per_page": 2})
    page = bundle["pages"][1]
    if damage == "drop":
        del page["entries"][0]
    elif damage == "reorder":
        page["entries"].reverse()
    elif damage == "duplicate":
        page["entries"][1] = deepcopy(page["entries"][0])
    elif damage == "bool_ordinal":
        page["entries"][0]["ordinal"] = True
    else:
        page["entries"][0]["unit_packet_ref"]["record_cid"] = []
    rebind_bundle(bundle)
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, bundle, fixture_data, limits={"max_units_per_page": 2})


def test_packet_outputs_are_detached_from_mutable_original_replay_and_every_returned_record(owner, fixture_data):
    data = deepcopy(fixture_data)
    before = canonical(data["preparation"])
    bundle = build(owner, data)
    data["arguments"]["source_report_bytes"]["handoff"] = b"{}"
    data["source_data"]["source_reports"]["handoff"]["queue_units"][0]["status"] = "edited"
    assert bundle["unit_packets"][0]["original_queue_unit"]["status"] == "pending_independent_source_and_legal_review"
    bundle["unit_packets"][0]["source_review_request"]["admitted"] = True
    assert canonical(data["preparation"]) == before
    assert data["source_data"]["alignment_corpus"]["manifest"]["admitted"] is False


def test_producer_drift_after_manifest_creation_refuses_the_complete_packet_return(owner, fixture_data, monkeypatch):
    original_candidate = owner._candidate
    original_pins = owner._pins
    state = {"drift": False}

    def observed_candidate(schema, **values):
        result = original_candidate(schema, **values)
        if schema == owner.MANIFEST_SCHEMA:
            state["drift"] = True
        return result

    def observed_pins():
        result = original_pins()
        if state["drift"]:
            result[next(iter(result))] = "0" * 64
        return result

    monkeypatch.setattr(owner, "_candidate", observed_candidate)
    monkeypatch.setattr(owner, "_pins", observed_pins)
    with pytest.raises(contracts.CorpusContractError):
        build(owner, fixture_data)
    assert state["drift"]


def test_producer_drift_after_full_validator_comparison_refuses_consumption(owner, fixture_data, baseline_bundle, monkeypatch):
    original_equal = source_review._equal_components
    original_pins = owner._pins
    state = {"drift": False}

    def observed_equal(actual, expected):
        result = original_equal(actual, expected)
        state["drift"] = True
        return result

    def observed_pins():
        result = original_pins()
        if state["drift"]:
            result[next(iter(result))] = "0" * 64
        return result

    monkeypatch.setattr(source_review, "_equal_components", observed_equal)
    monkeypatch.setattr(owner, "_pins", observed_pins)
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, baseline_bundle, fixture_data)
    assert state["drift"]


@pytest.mark.parametrize("value", [None, True, "", "bad", "f" * 63, "F" * 64, "0" * 64])
def test_inherited_complete_preparation_needs_an_independent_full_manifest_hash(owner, fixture_data, value):
    data = deepcopy(fixture_data)
    data["arguments"]["expected_preparation_manifest_sha256"] = value
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)


@pytest.mark.parametrize("key", ["manifest", "pages", "records"])
def test_every_alignment_transport_byte_stream_keeps_its_external_raw_pin(owner, fixture_data, key):
    data = deepcopy(fixture_data)
    data["arguments"]["alignment_corpus_bytes"][key] += b"\n"
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)


@pytest.mark.parametrize("key", ["context", "handoff"])
@pytest.mark.parametrize("pin", ["raw_sha256", "canonical_sha256"])
def test_original_source_reports_require_both_raw_and_full_canonical_pins(owner, fixture_data, key, pin):
    data = deepcopy(fixture_data)
    data["arguments"]["expected_source_report_pins"][key][pin] = "0" * 64
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)


@pytest.mark.parametrize("damage", [
    "missing_report", "extra_report", "missing_corpus", "extra_corpus", "bad_report_bytes",
    "missing_pin", "unknown_pin_field", "missing_replay", "unknown_replay", "missing_population_pin",
])
def test_packet_intake_requires_complete_closed_original_source_inputs(owner, fixture_data, damage):
    data = deepcopy(fixture_data)
    args = data["arguments"]
    if damage == "missing_report":
        del args["source_report_bytes"]["context"]
    elif damage == "extra_report":
        args["source_report_bytes"]["alternate"] = b"{}"
    elif damage == "missing_corpus":
        del args["alignment_corpus_bytes"]["pages"]
    elif damage == "extra_corpus":
        args["alignment_corpus_bytes"]["other"] = b"{}"
    elif damage == "bad_report_bytes":
        args["source_report_bytes"]["context"] = "{}"
    elif damage == "missing_pin":
        del args["expected_source_report_pins"]["handoff"]
    elif damage == "unknown_pin_field":
        args["expected_source_report_pins"]["context"]["allow_unreviewed"] = True
    elif damage == "missing_replay":
        del args["alignment_replay_inputs"]["base_replay_inputs"]
    elif damage == "unknown_replay":
        args["alignment_replay_inputs"]["replacement_sources"] = []
    elif damage == "missing_population_pin":
        del args["alignment_replay_inputs"]["expected_document_population_sha256"]
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)


@pytest.mark.parametrize("key", ["context", "handoff"])
def test_raw_repinned_duplicate_json_keys_cannot_supply_source_reports(owner, fixture_data, key):
    data = deepcopy(fixture_data)
    raw = data["arguments"]["source_report_bytes"][key]
    mutated = b'{"schema":"duplicate",' + raw.lstrip()[1:]
    data["arguments"]["source_report_bytes"][key] = mutated
    data["arguments"]["expected_source_report_pins"][key]["raw_sha256"] = sha(mutated)
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)


@pytest.mark.parametrize("key", ["context", "handoff"])
def test_repaired_source_report_outer_hash_and_internal_seal_cannot_replace_original_replay(owner, fixture_data, key):
    data = deepcopy(fixture_data)
    fixture_helper().repin_source(data["source_data"], key, lambda value: value.update({"population_complete": False}))
    data["arguments"].update(data["source_data"]["arguments"])
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)


@pytest.mark.parametrize("limits", [
    [], {"unknown": 1}, {"max_parents": True}, {"max_parents": 0}, {"max_parents": 7},
    {"max_source_views": 33}, {"max_units": 8193}, {"max_units_per_page": 65},
    {"max_selector_projections": 4097},
    {"max_document_parts": 1025}, {"max_document_part_items": 129}, {"max_document_part_items": True},
    {"max_pages": 257}, {"max_page_bytes": contracts.MAX_RECORD_BYTES + 1},
    {"max_collection_bytes": 64 * 1024**2 + 1},
])
def test_packet_limits_are_closed_exact_integer_lower_only(owner, fixture_data, monkeypatch, limits):
    monkeypatch.setattr(source_review, "prepare_source_review_requests", producer_refusal)
    with pytest.raises(contracts.CorpusContractError):
        build(owner, fixture_data, limits=limits)


@pytest.mark.parametrize("limit", [
    "max_parents", "max_source_views", "max_units", "max_selector_projections", "max_document_parts", "max_page_bytes", "max_collection_bytes",
])
def test_lower_whole_population_caps_refuse_without_returning_an_easy_prefix(owner, fixture_data, limit):
    with pytest.raises(contracts.CorpusContractError):
        build(owner, fixture_data, limits={limit: 1})


@pytest.mark.parametrize("bad", [None, [], {"manifest": {}}, {"manifest": {}, "pages": [], "reviews": []}])
def test_consumption_requires_a_closed_complete_packet_bundle(owner, fixture_data, bad):
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, bad, fixture_data)


@pytest.mark.parametrize("damage", ["unknown_field", "bad_component", "bad_schema", "oversized_text"])
def test_malformed_or_oversized_offered_packets_refuse_before_source_regeneration(
    owner, fixture_data, baseline_bundle, monkeypatch, damage
):
    bundle = deepcopy(baseline_bundle)
    if damage == "unknown_field":
        bundle["unit_packets"][0]["alternate_reviewer"] = "ignored"
        bundle["unit_packets"][0] = reseal(bundle["unit_packets"][0])
    elif damage == "bad_component":
        bundle["source_views"] = {"views": bundle["source_views"]}
    elif damage == "bad_schema":
        bundle["response_guides"][0]["schema"] = "unrelated/v1"
        bundle["response_guides"][0] = reseal(bundle["response_guides"][0])
    else:
        bundle["source_views"][0]["text"] = "雪" * contracts.MAX_RECORD_BYTES
    monkeypatch.setattr(source_review, "prepare_source_review_requests", producer_refusal)
    with pytest.raises(contracts.CorpusContractError):
        validate(owner, bundle, fixture_data)


def test_explicit_inherited_lower_limits_need_the_exact_corresponding_preparation_pin(owner, fixture_data):
    data = deepcopy(fixture_data)
    lower = {"max_requests": len(data["preparation"]["requests"])}
    data["arguments"]["source_review_limits"] = lower
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)
    preparation = source_review.prepare_source_review_requests(**data["source_data"]["arguments"], limits=lower)
    data["arguments"]["expected_preparation_manifest_sha256"] = sha(canonical_dag_json_bytes(preparation["manifest"]))
    bundle = build(owner, data)
    assert bundle["manifest"]["source_review_limits"]["max_requests"] == len(preparation["requests"])
    assert bundle["manifest"]["source_preparation_ref"] == ref(preparation["manifest"])
    assert validate(owner, bundle, data) == bundle


def test_original_replay_budget_refuses_before_bulk_encoding_and_source_regeneration(
    owner, fixture_data, monkeypatch
):
    data = deepcopy(fixture_data)
    target = data["arguments"]["alignment_replay_inputs"]["base_replay_inputs"]
    data["arguments"]["source_review_limits"] = {"max_replay_bytes": 1024}
    original = json.dumps

    def observed(value, *args, **kwargs):
        if value is target:
            pytest.fail("over-budget original replay reached bulk JSON serialization")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(json, "dumps", observed)
    monkeypatch.setattr(source_review, "prepare_source_review_requests", producer_refusal)
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)


def test_actual_public_packet_module_import_is_inert():
    script = """
import sys
def forbidden(event, args):
    if event in {'socket.connect', 'subprocess.Popen'}:
        raise RuntimeError('unexpected import side effect: ' + event)
sys.addaudithook(forbidden)
from ipfs_datasets_py.logic.autoformal import corpus_source_review_packets
for name in ('torch', 'numpy', 'pyarrow', 'cryptography', 'ipfs_datasets_py.logic.profile_g'):
    assert name not in sys.modules, name
assert callable(corpus_source_review_packets.prepare_source_review_packets)
assert callable(corpus_source_review_packets.validate_source_review_packets)
"""
    environment = {**os.environ, "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[4],
        env=environment, capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
