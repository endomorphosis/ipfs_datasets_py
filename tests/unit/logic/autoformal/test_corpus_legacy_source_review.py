"""Fictional stored-source review preparations preserve ambiguity and provenance.

These tests create no human reviews, authenticated responses, legal targets,
models or Lean evidence. Missing-source and no-match cases are synthetic controls.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_join as joins
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_review as owner
from ipfs_datasets_py.logic.autoformal.corpus_contracts import CorpusContractError, seal_record


def wire(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def source_fixture(*args, **kwargs):
    """Reuse the exact fictional source fixture without collecting another suite."""
    spec = importlib.util.spec_from_file_location(
        "fictional_legacy_join_fixture_for_review",
        Path(__file__).with_name("test_corpus_legacy_source_join.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fixture(*args, **kwargs)


def case(*, text="§ Café Clerk; Clerk.", span="Clerk", second=False, unavailable=None):
    rows, inputs = source_fixture(text, span)
    if second:
        receipt = json.loads(inputs["producer_receipt_bytes"])
        producer = copy.deepcopy(receipt["rows"][0])
        producer.update(source_span_id="second-fictional-span", text="Café", source_sha256=sha("Café".encode()))
        receipt["rows"].append(producer)
        receipt_bytes = wire(receipt)
        inputs.update(
            producer_receipt_bytes=receipt_bytes,
            expected_producer_receipt_sha256=sha(receipt_bytes),
        )
        first = json.loads(rows[0])
        first["source_target_artifact_sha256"] = sha(receipt_bytes)
        second_row = copy.deepcopy(first)
        second_row.update(
            observation_id="second-fictional-observation",
            source_target_artifact_pointer="/rows/1/logic_target_observation",
        )
        second_row["source"].update(
            span_id=producer["source_span_id"], text="Café", text_sha256=producer["source_sha256"]
        )
        rows = [wire(first), wire(second_row)]
        inputs["expected_population"][0]["row_sha256"] = sha(rows[0])
        inputs["expected_population"].append({
            **inputs["expected_population"][0],
            "row_sha256": sha(rows[1]),
            "source_span_id": producer["source_span_id"],
            "text_sha256": producer["source_sha256"],
        })
    if unavailable == "receipt":
        inputs.update(producer_receipt_bytes=None, expected_producer_receipt_sha256=None)
    elif unavailable == "section":
        inputs.update(source_sections=[], expected_source_sections=[])
    ledger = joins.build_legacy_source_join(rows, **inputs)
    raw = wire(ledger)
    return {"ledger": ledger, "join_bytes": raw, "rows": rows, "inputs": inputs}


def prepare(data):
    return owner.prepare_legacy_source_review_requests(
        data["join_bytes"], data["rows"],
        expected_join_sha256=sha(data["join_bytes"]), **data["inputs"],
    )


def validate(bundle, data):
    return owner.validate_legacy_source_review_requests(
        bundle, data["join_bytes"], data["rows"],
        expected_join_sha256=sha(data["join_bytes"]), **data["inputs"],
    )


def reseal(record):
    return seal_record({
        key: copy.deepcopy(value) for key, value in record.items()
        if key not in {"record_cid", "cid_scope"}
    })


def test_complete_unicode_ambiguity_population_is_preserved_without_selection():
    data = case(second=True)
    before = copy.deepcopy(data)
    bundle = prepare(data)
    assert data == before
    assert set(bundle) == {"manifest", "source_sections", "requests", "subjects", "dependency_manifests"}
    assert bundle["source_sections"] == data["ledger"]["source_sections"]
    assert len(bundle["requests"]) == len(bundle["subjects"]) == len(bundle["dependency_manifests"]) == 2
    assert [request["original_row"] for request in bundle["requests"]] == data["ledger"]["rows"]
    occurrences = [item["source_occurrence"] for item in bundle["requests"][0]["original_row"]["candidates"]]
    assert [item["start_char"] for item in occurrences] == [7, 14]
    assert [item["start_utf8"] for item in occurrences] == [9, 16]
    assert bundle["requests"][1]["original_row"]["disposition"] == "unique_exact_candidate"
    for request in bundle["requests"]:
        assert request["selected_occurrence"] is None
        assert request["original_producer_occurrence_attested"] is False
        assert request["original_row"]["selected_occurrence"] is None
        assert all(request[flag] is False for flag in owner.FALSE_FLAGS)
    assert validate(bundle, data) == bundle


def test_question_slots_keep_nine_active_and_seven_deferred_without_answers():
    bundle = prepare(case(second=True))
    all_slots = []
    for request in bundle["requests"]:
        questions = request["review_questions"]
        active, deferred = request["context_slot_ids"], request["deferred_review_slot_ids"]
        assert len(questions) == 16 and len(active) == 9 and len(deferred) == 7
        slots = [question["slot_id"] for question in questions]
        assert len(set(slots)) == 16 and set(slots) == set(active + deferred)
        assert not set(active) & set(deferred)
        for question in questions:
            assert question["verified"] is question["closed"] is False
            assert question["status"] == "pending_independent_review"
            assert question["assessment_scope"] == (
                "source_context_evidence_declaration" if question["slot_id"] in active
                else "deferred_semantic_or_proof_review"
            )
        all_slots.extend(slots)
    assert len(set(all_slots)) == 32


@pytest.mark.parametrize("options,disposition", [
    ({"text": "Clerk  shall", "span": "Clerk shall"}, "no_exact_occurrence"),
    ({"unavailable": "receipt"}, "producer_source_unavailable"),
    ({"unavailable": "section"}, "source_section_unavailable"),
])
def test_synthetic_missing_and_no_match_controls_keep_the_original_observation(options, disposition):
    data = case(**options)
    bundle = prepare(data)
    assert len(bundle["requests"]) == 1
    request = bundle["requests"][0]
    assert request["original_row"] == data["ledger"]["rows"][0]
    assert request["original_row"]["disposition"] == disposition
    assert request["original_row"]["candidates"] == []
    assert request["selected_occurrence"] is None
    assert request["original_producer_occurrence_attested"] is False
    assert validate(bundle, data) == bundle


def test_overlapping_matches_are_all_reviewed_as_candidates():
    bundle = prepare(case(text="aaaa", span="aa"))
    candidates = bundle["requests"][0]["original_row"]["candidates"]
    assert [item["source_occurrence"]["start_char"] for item in candidates] == [0, 1, 2]
    assert all(item["context_declaration"]["availability"] == "required_unavailable" for item in candidates)


def test_preparation_and_validation_are_deterministic_detached_copies():
    data = case()
    first = prepare(data)
    second = prepare(data)
    checked = validate(first, data)
    assert first == second == checked
    first["requests"][0]["original_row"]["candidates"].clear()
    assert len(second["requests"][0]["original_row"]["candidates"]) == 2
    assert len(checked["requests"][0]["original_row"]["candidates"]) == 2
    data["inputs"]["source_sections"][0]["text"] = "mutated after preparation"
    assert second["source_sections"][0]["extracted_text"] == "§ Café Clerk; Clerk."


@pytest.mark.parametrize("component", ["requests", "subjects", "dependency_manifests", "source_sections"])
def test_dropped_component_population_is_rejected(component):
    data = case(second=True)
    bundle = prepare(data)
    bundle[component].pop()
    with pytest.raises(CorpusContractError):
        validate(bundle, data)


@pytest.mark.parametrize("component", ["requests", "subjects", "dependency_manifests"])
def test_reordered_observation_components_are_rejected(component):
    data = case(second=True)
    bundle = prepare(data)
    bundle[component].reverse()
    with pytest.raises(CorpusContractError):
        validate(bundle, data)


@pytest.mark.parametrize("damage", [
    "drop_candidate", "reverse_candidates", "selector", "row_disposition",
    "select_occurrence", "claim_original_occurrence", "question_omission", "question_reorder",
    "active_deferred_swap", "question_claim_closed", "wrong_profile", "extra_field",
])
def test_resealed_request_tampering_is_rejected_by_full_regeneration(damage):
    data = case()
    bundle = prepare(data)
    request = bundle["requests"][0]
    original = request["original_row"]
    if damage == "drop_candidate":
        original["candidates"].pop()
        original["occurrence_count"] = 1
    elif damage == "reverse_candidates":
        original["candidates"].reverse()
    elif damage == "selector":
        candidate = original["candidates"][0]
        candidate["source_occurrence"]["start_char"] += 1
        candidate["source_occurrence"] = reseal(candidate["source_occurrence"])
    elif damage == "row_disposition":
        original["disposition"] = "unique_exact_candidate"
    elif damage == "select_occurrence":
        request["selected_occurrence"] = original["candidates"][0]["source_occurrence"]["record_cid"]
    elif damage == "claim_original_occurrence":
        request["original_producer_occurrence_attested"] = True
    elif damage == "question_omission":
        request["review_questions"].pop()
    elif damage == "question_reorder":
        request["review_questions"].reverse()
    elif damage == "active_deferred_swap":
        active, deferred = request["context_slot_ids"], request["deferred_review_slot_ids"]
        active[0], deferred[0] = deferred[0], active[0]
    elif damage == "question_claim_closed":
        request["review_questions"][0].update(closed=True, verified=True)
    elif damage == "wrong_profile":
        request["profile"] = "complete-parent-official-source-context-evidence-review/v1"
    elif damage == "extra_field":
        request["invented_review"] = {"accepted": True}
    bundle["requests"][0] = reseal(request)
    with pytest.raises(CorpusContractError):
        validate(bundle, data)


@pytest.mark.parametrize("flag", [
    "source_authenticity_verified", "source_semantics_verified", "context_closure_verified",
    "admitted", "formalized", "proof_authority",
])
def test_resealed_authority_promotion_cannot_be_supplied_by_caller(flag):
    data = case()
    bundle = prepare(data)
    bundle["requests"][0][flag] = True
    bundle["requests"][0] = reseal(bundle["requests"][0])
    with pytest.raises(CorpusContractError):
        validate(bundle, data)


def test_subject_and_dependency_changes_cannot_reinterpret_the_request():
    data = case()
    for component in ("subjects", "dependency_manifests"):
        bundle = prepare(data)
        if component == "subjects":
            bundle[component][0]["graph_sha256"] = "f" * 64
            bundle[component][0] = reseal(bundle[component][0])
        else:
            bundle[component][0]["manifest_sha256"] = "f" * 64
        with pytest.raises(CorpusContractError):
            validate(bundle, data)


@pytest.mark.parametrize("damage", ["join_bytes", "paired_bytes", "receipt_bytes", "source_text", "expected_source", "population"])
def test_independent_input_commitments_are_required_before_review_preparation(damage):
    data = case()
    expected_join = sha(data["join_bytes"])
    if damage == "join_bytes":
        data["join_bytes"] += b" "
    elif damage == "paired_bytes":
        data["rows"][0] += b" "
    elif damage == "receipt_bytes":
        data["inputs"]["producer_receipt_bytes"] += b" "
    elif damage == "source_text":
        data["inputs"]["source_sections"][0]["text"] += " extra"
    elif damage == "expected_source":
        data["inputs"]["expected_source_sections"][0]["parquet_row_index"] += 1
    else:
        data["inputs"]["expected_population"] = []
    with pytest.raises(CorpusContractError):
        owner.prepare_legacy_source_review_requests(
            data["join_bytes"], data["rows"], expected_join_sha256=expected_join, **data["inputs"]
        )


@pytest.mark.parametrize("damage", ["candidate_omission", "wrong_profile", "claimed_authority", "source_rewrite"])
def test_rehashed_resealed_join_does_not_replace_independent_replay(damage):
    data = case()
    ledger = data["ledger"]
    if damage == "candidate_omission":
        ledger["rows"][0]["candidates"].pop()
        ledger["rows"][0]["occurrence_count"] = 1
    elif damage == "wrong_profile":
        ledger["profile"] = "fictional-unsupported-coordinate-system/v1"
    elif damage == "claimed_authority":
        ledger["source_authenticity_verified"] = True
    else:
        ledger["source_sections"][0]["extracted_text"] += " altered"
    data["join_bytes"] = wire(reseal(ledger))
    with pytest.raises(CorpusContractError):
        prepare(data)


@pytest.mark.parametrize("expected", [None, "", "a" * 63, "A" * 64, "g" * 64, "0" * 64, True])
def test_join_hash_requires_exact_independently_expected_lowercase_sha256(expected):
    data = case()
    with pytest.raises(CorpusContractError):
        owner.prepare_legacy_source_review_requests(
            data["join_bytes"], data["rows"], expected_join_sha256=expected, **data["inputs"]
        )


@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b"{", b'{"schema": 1, "schema": 2}', b'{"number": NaN}'])
def test_malformed_or_nonordinary_join_transport_is_rejected(raw):
    data = case()
    with pytest.raises(CorpusContractError):
        owner.prepare_legacy_source_review_requests(
            raw, data["rows"], expected_join_sha256=sha(raw), **data["inputs"]
        )


def test_mutable_join_transport_and_unknown_bundle_fields_are_rejected():
    data = case()
    with pytest.raises(CorpusContractError):
        owner.prepare_legacy_source_review_requests(
            bytearray(data["join_bytes"]), data["rows"],
            expected_join_sha256=sha(data["join_bytes"]), **data["inputs"],
        )
    bundle = prepare(data)
    bundle["answers"] = [{"accepted": True}]
    with pytest.raises(CorpusContractError):
        validate(bundle, data)
