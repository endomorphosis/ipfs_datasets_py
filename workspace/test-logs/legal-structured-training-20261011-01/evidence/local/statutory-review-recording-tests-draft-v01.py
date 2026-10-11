"""Inert synthetic declarations; no real reviewers, labels or fit rights asserted."""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import json
import socket

import pytest

from ipfs_datasets_py.logic.legal_ir import statutory_source_review as packet_source
from ipfs_datasets_py.logic.legal_ir import statutory_review_recording as subject


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(raw):
    return {"sha256": sha(raw), "bytes": len(raw)}


def make_fixture(tmp_path, *, texts=None, ordinals=None, prefixes=None):
    texts = texts or ["The clerk shall record evidence."]
    ordinals = ordinals or list(range(len(texts)))
    prefixes = prefixes or ["§ Ω archived fixture\n" for _ in texts]
    records, rows, paths = [], [], {}
    parent = {**pin(b"Synthetic original export not read or authenticated."),
        "repository_id": "unit/synthetic-uscode-export", "revision": "1" * 40,
        "release_id": "synthetic-archived-release"}

    def retain(raw):
        reference = pin(raw)
        path = tmp_path / (reference["sha256"] + ".artifact")
        if not path.exists():
            path.write_bytes(raw)
        paths[reference["sha256"]] = path
        return reference

    for index, (text, ordinal, prefix) in enumerate(zip(texts, ordinals, prefixes, strict=True)):
        complete = prefix + text + "\nArchived fixture notes—not legal authority."
        artifact = retain(complete.encode("utf-8"))
        start, end = len(prefix), len(prefix) + len(text)
        byte_start, byte_end = len(prefix.encode()), len((prefix + text).encode())
        identity = "unit-physical-case-" + str(index)
        source = {"artifact": artifact, "source_kind": "us_code", "release_id": parent["release_id"],
            "document_id": "unit:section:" + str(ordinal), "language": "en",
            "citation": "Synthetic section " + str(ordinal), "byte_start": byte_start,
            "byte_end": byte_end, "normalization": "identity"}
        record = {"request_id": identity, "parent_parquet": parent,
            "physical_source_section_offset": ordinal, "raw_section_sha256": artifact["sha256"],
            "raw_span_char_offsets": [start, end], "raw_span_utf8_byte_offsets": [byte_start, byte_end],
            "raw_span_sha256": sha(text.encode()), "source_view": artifact,
            "legal_id": source["document_id"], "citation": source["citation"], "source_kind": "us_code",
            "source_view_normalization": "identity", "source_view_complete_raw_section": True,
            "source_view_truncated": False, "request_text_equals_exact_raw_span": True,
            "historical_census_occurrence_id": "synthetic-occurrence-" + str(index),
            "historical_source_span_id": "synthetic-span-" + str(index),
            "historical_normalized_source_sha256": sha(text.encode()),
            "raw_span_sha256_equals_historical_normalized_source_sha256": True,
            "raw_span_text_equals_historical_normalized_source_text": True, "frontend": "legacy_us_code",
            **{name: False for name in ("admitted", "formalized", "proof_authority",
                "source_authority_authenticated", "source_semantics_verified", "target_attached", "training_qualified")}}
        records.append(record)
        rows.append({"id": identity, "source_text": text, "source": source,
            "physical_origin": {"provenance_artifact": None, "provenance_record_id": identity},
            "context": {"artifact": artifact, "selected_char_start": start, "selected_char_end": end,
                "complete_raw_section": True, "normalization": "identity"},
            "exposure": {"status": "previously_exposed_development", "prior_exposure_complete": False,
                "events": [{"stage": "source-context-engineering-inspection", "case_id": identity,
                    "source_text_sha256": sha(text.encode()),
                    # Evidence bodies deliberately absent: only linkage metadata enters packets.
                    "evidence_artifact": pin(b"Not opened and not claimed authentic.")}]}})
    provenance = {"schema": packet_source.ORIGIN_SCHEMA, "passed": True,
        "raw_section_and_byte_slice_verified_before_writes": True,
        "source_document_views_complete": True, "rows": records}
    provenance_ref = retain(json.dumps(provenance, ensure_ascii=False, sort_keys=True).encode())
    for row in rows:
        row["physical_origin"]["provenance_artifact"] = provenance_ref
    return {"rows": rows, "paths": paths, "provenance": provenance, "retain": retain,
            "resolver": lambda ref: paths[ref["sha256"]]}


@pytest.fixture(autouse=True)
def deny_numerical_and_network_work(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers"}:
            raise AssertionError("numerical import prohibited in inert review tests")
        return original(name, *args, **kwargs)

    def prohibited(*args, **kwargs):
        raise AssertionError("network prohibited in inert review tests")

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(socket, "create_connection", prohibited)
    monkeypatch.setattr(socket.socket, "connect", prohibited)


def prepared(tmp_path, **options):
    fixture = make_fixture(tmp_path, **options)
    packet = packet_source.create_blank_packet(fixture["rows"], artifact_resolver=fixture["resolver"])
    return packet, fixture


def kwargs(packet, fixture):
    return {"expected_packet_sha256": subject.digest(packet), "artifact_resolver": fixture["resolver"]}


def guide(packet, fixture):
    return subject.submission_guide(packet, **kwargs(packet, fixture))


def literal(text, surface, **extra):
    left = text.index(surface)
    return {"coordinate_space": "selected_source_unicode_characters", "char_start": left,
            "char_end": left + len(surface), "text": surface, **extra}


def submitted(packet, fixture, *, reviewer="synthetic-reviewer-a", identity="synthetic-submission-a", complete=True, item_index=0):
    row = deepcopy(guide(packet, fixture)["items"][item_index])
    if complete:
        item = packet["items"][item_index]
        text = item["input"]["source_text"]
        rule = {"modality": "O", "actor": "The clerk", "action": "record", "object": "evidence",
                "conditions": [], "exceptions": [], "temporal": []}
        row["review"] = {
            "normative_eligibility": "eligible_normative", "definition_status": "no_definition_declared",
            "multi_rule_status": "single_rule", "interpretation_status": "normative", "normative_rules": [rule],
            "source_role_anchors": [literal(text, surface, anchor_id=facet + "-0", rule_index=0, facet=facet)
                                    for facet, surface in (("actor", "The clerk"), ("action", "record"), ("object", "evidence"))],
            "qualifier_attachments": [], "trigger": [literal(text, "shall")], "ambiguity": [],
            "unsupported_meaning": [], "freeform_qualifier_scope": "", "notes": "Synthetic engineering declaration.",
            "reviewer_id": reviewer, "reviewed_at_utc": "2026-10-11T00:00:00Z"}
        row["context_review"] = {"context_required_for_interpretation": False,
            "operative_versus_editorial_boundaries": [{"coordinate_space": "complete_raw_section_unicode_characters",
                "char_start": item["context"]["selected_char_start"], "char_end": item["context"]["selected_char_end"],
                "text": text, "context_artifact": item["context"]["artifact"], "kind": "operative"}],
            "governing_definitions": [], "cross_references": [], "unresolved_dependencies": [],
            "context_sufficiency": "sufficient_as_declared", "source_authority_or_currentness_evidence": []}
        row["evidence"]["review_process_evidence"] = fixture["retain"](b"Synthetic evidence; no human or legal authority authenticated.")
        row["exposure_declaration"] = {"candidate_or_reference_exposed": False,
            "organizer_metadata_exposed": False, "other_exposure": "Synthetic-only declaration, not verified blindness."}
    return {"schema": subject.SUBMISSION_SCHEMA, "packet_sha256": subject.digest(packet),
            "submission_id": identity, "items": [row]}


def record(packet, submissions, fixture):
    return subject.record_reviews(packet, submissions, **kwargs(packet, fixture))


def assert_zero(receipt):
    assert all(receipt[field] is False for field in packet_source.AUTHORITY_FIELDS)
    assert all(type(value) is int and value == 0 for value in receipt["admission_masks"].values())
    for field in ("human_review_authenticated", "independent_adjudication_completed", "target_created",
                  "signature_verification_executed", "completed_submissions_generated",
                  "reviewer_blindness_verified", "file_bytes_verified_by_dictionary_api"):
        assert receipt[field] is False


def adjudication(packet, submissions, fixture, *, decision="accept_unique"):
    recording = record(packet, submissions, fixture)
    item = recording["items"][0]
    refs = [{field: entry[field] for field in ("submission_sha256", "declaration_sha256")}
            for entry in item["received_declarations"] if entry["complete"]]
    accepted = refs[:1] if decision == "accept_unique" else refs if decision == "accept_alternatives" else []
    return {"schema": subject.ADJUDICATION_SCHEMA, "packet_sha256": subject.digest(packet),
        "recording_sha256": subject.digest(recording), "items": [{"item_id": item["item_id"],
            "principal_id": "synthetic-distinct-adjudicator", "adjudicated_at_utc": "2026-10-11T01:00:00Z",
            "declaration_refs": refs, "decision": decision, "accepted_declaration_refs": accepted,
            "unresolved_scope": [], "rationale": "Synthetic declared decision; not authenticated legal review.",
            "evidence": {field: None for field in subject.EVIDENCE_FIELDS}}]}


def test_zero_submissions_preserve_all_physical_context_inputs_and_blank_answers(tmp_path):
    packet, fixture = prepared(tmp_path, texts=["The clerk shall record evidence.", "The clerk shall record evidence."], ordinals=[1, 2])
    original = deepcopy(packet)
    receipt = record(packet, [], fixture)
    assert packet == original
    assert receipt["item_count"] == 2
    assert receipt["submission_count"] == 0
    assert receipt["status_counts"]["pending"] == 2
    assert receipt["structurally_complete_declaration_count"] == 0
    assert len({row["physical_identity_sha256"] for row in receipt["items"]}) == 2
    assert {row["source_text_sha256"] for row in receipt["items"]} == {sha(b"The clerk shall record evidence.")}
    for row in receipt["items"]:
        assert row["received_declarations"] == []
        assert_zero(row)
    assert_zero(receipt)


def test_guide_is_a_distinct_detached_blank_submission_boundary(tmp_path):
    packet, fixture = prepared(tmp_path)
    result = guide(packet, fixture)
    assert result["schema"] == subject.GUIDE_SCHEMA
    assert result["submission_schema"] == subject.SUBMISSION_SCHEMA
    assert all(value is None for field in ("review", "context_review", "evidence", "exposure_declaration")
               for value in result["items"][0][field].values())
    result["items"][0]["context_artifact"]["sha256"] = "0" * 64
    assert packet["items"][0]["context"]["artifact"]["sha256"] != "0" * 64
    assert_zero(result)


def test_partial_and_complete_declarations_keep_absent_distinct_from_unanswered(tmp_path):
    packet, fixture = prepared(tmp_path)
    partial = submitted(packet, fixture, complete=False)
    partial["items"][0]["review"]["ambiguity"] = []
    receipt = record(packet, [partial], fixture)
    item = receipt["items"][0]
    assert item["status"] == "partial_declarations"
    entry = item["received_declarations"][0]
    assert "review.ambiguity" not in entry["missing_fields"]
    assert "review.unsupported_meaning" in entry["missing_fields"]
    assert entry["meaning_signature_sha256"] is None
    complete = submitted(packet, fixture)
    receipt = record(packet, [complete], fixture)
    assert receipt["items"][0]["status"] == "single_complete_declaration"
    assert receipt["items"][0]["received_declarations"][0]["missing_fields"] == []
    assert receipt["human_reviews_authenticated"] == 0
    assert_zero(receipt)


def test_recording_is_detached_and_replay_refuses_authority_or_payload_changes(tmp_path):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    original = deepcopy(submission)
    receipt = record(packet, [submission], fixture)
    assert submission == original
    replay = subject.validate_recording(receipt, packet, [submission], **kwargs(packet, fixture))
    assert_zero(replay)
    changed = deepcopy(receipt)
    changed["admitted"] = True
    changed["content_sha256"] = subject.digest({key: value for key, value in changed.items() if key != "content_sha256"})
    with pytest.raises(ValueError, match="exact submission replay"):
        subject.validate_recording(changed, packet, [submission], **kwargs(packet, fixture))
    changed = deepcopy(submission)
    changed["items"][0]["review"]["notes"] += " changed"
    with pytest.raises(ValueError, match="exact submission replay"):
        subject.validate_recording(receipt, packet, [changed], **kwargs(packet, fixture))


def test_exact_agreement_excludes_declared_identity_time_notes_and_evidence(tmp_path):
    packet, fixture = prepared(tmp_path)
    first = submitted(packet, fixture)
    second = submitted(packet, fixture, reviewer="synthetic-reviewer-b", identity="synthetic-submission-b")
    second["items"][0]["review"].update(notes="Different free notes.", reviewed_at_utc="2026-10-11T00:30:00+00:00")
    second["items"][0]["evidence"]["identity_evidence"] = fixture["retain"](b"Synthetic identity assertion, not authenticated.")
    receipt = record(packet, [first, second], fixture)
    assert receipt["items"][0]["status"] == "exact_multiple_declaration_agreement"
    assert receipt["items"][0]["meaning_signature_count"] == 1
    assert receipt["independent_reviews_authenticated"] == 0
    assert_zero(receipt)


@pytest.mark.parametrize("change", [
    lambda row: row["review"].update(normative_eligibility="needs_context"),
    lambda row: row["review"].update(definition_status="mixed_definition_and_norm"),
    lambda row: row["review"].update(freeform_qualifier_scope="Declared different scope."),
    lambda row: row["review"]["normative_rules"][0].update(modality="P"),
    lambda row: row["review"]["source_role_anchors"].pop(),
    lambda row: row["context_review"].update(context_required_for_interpretation=True),
    lambda row: row["context_review"].update(context_sufficiency="needs_external_context"),
    lambda row: row["context_review"].update(governing_definitions=["Synthetic declared definition."]),
])
def test_interpretation_and_context_disagreement_are_preserved_without_resolution(tmp_path, change):
    packet, fixture = prepared(tmp_path)
    first = submitted(packet, fixture)
    second = submitted(packet, fixture, reviewer="synthetic-reviewer-b", identity="synthetic-submission-b")
    change(second["items"][0])
    receipt = record(packet, [first, second], fixture)
    assert receipt["items"][0]["status"] == "disputed"
    assert receipt["items"][0]["meaning_signature_count"] == 2
    assert receipt["items"][0]["external_adjudication_status"] == "pending"
    assert_zero(receipt)


@pytest.mark.parametrize("status", ["no_normative_rule", "needs_context", "ambiguous", "unsupported"])
def test_complete_non_normative_declarations_need_explicit_absent_rules(tmp_path, status):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    review = submission["items"][0]["review"]
    review.update(interpretation_status=status, normative_eligibility="not_normative" if status == "no_normative_rule" else status,
                  multi_rule_status="no_rule", normative_rules=[], source_role_anchors=[], qualifier_attachments=[], trigger=[])
    receipt = record(packet, [submission], fixture)
    assert receipt["items"][0]["consensus_declared_interpretation_status"] == status
    assert receipt["structurally_complete_declaration_count"] == 1
    assert_zero(receipt)


@pytest.mark.parametrize("change", [
    lambda submission: submission.update(schema="symbol-binding-source-reviewer/v1"),
    lambda submission: submission.update(packet_sha256="0" * 64),
    lambda submission: submission["items"][0].update(item_id="unknown-physical-item"),
    lambda submission: submission["items"][0].update(input_sha256="0" * 64),
    lambda submission: submission["items"][0].update(physical_identity_sha256="0" * 64),
    lambda submission: submission["items"][0].update(source_text_sha256="0" * 64),
    lambda submission: submission["items"][0]["context_artifact"].update(bytes=1),
    lambda submission: submission["items"][0].update(selected_context_char_offsets=[0, 1]),
    lambda submission: submission["items"][0].update(accepted=True),
    lambda submission: submission["items"][0]["review"].update(proposed_target={"rules": []}),
    lambda submission: submission.update(signature_verifier="submitted.callback"),
])
def test_closed_submission_profile_and_immutable_envelope_reject_tampering(tmp_path, change):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    change(submission)
    with pytest.raises(ValueError):
        record(packet, [submission], fixture)


@pytest.mark.parametrize("mode", ["same_id", "renamed_content", "same_reviewer", "duplicate_item"])
def test_duplicate_ids_payloads_reviewers_and_items_refused(tmp_path, mode):
    packet, fixture = prepared(tmp_path)
    first = submitted(packet, fixture)
    second = deepcopy(first)
    if mode == "renamed_content":
        second["submission_id"] = "renamed-synthetic-id"
    elif mode == "same_reviewer":
        second["submission_id"] = "second-synthetic-id"
        second["items"][0]["review"]["notes"] = "Different notes do not create another reviewer."
    elif mode == "duplicate_item":
        first["items"].append(deepcopy(first["items"][0]))
        second = None
    with pytest.raises(ValueError, match="duplicate"):
        record(packet, [first] if second is None else [first, second], fixture)


@pytest.mark.parametrize("change", [
    lambda row: row["review"].update(reviewed_at_utc="2026-02-30T00:00:00Z"),
    lambda row: row["review"].update(reviewed_at_utc="2026-10-11T00:00:00+01:00"),
    lambda row: row["review"].update(reviewed_at_utc="yesterday"),
    lambda row: row["review"].update(normative_eligibility=True),
    lambda row: row["review"].update(normative_rules=[]),
    lambda row: row["review"]["normative_rules"][0].update(actor=""),
    lambda row: row["review"]["normative_rules"][0].update(modality="must"),
    lambda row: row["review"]["source_role_anchors"][0].update(char_start=True),
    lambda row: row["review"]["source_role_anchors"][0].update(coordinate_space="UTF8_bytes"),
    lambda row: row["review"]["source_role_anchors"][0].update(text="A different clerk"),
    lambda row: row["review"]["source_role_anchors"][0].update(rule_index=20),
    lambda row: row["review"]["source_role_anchors"].append(deepcopy(row["review"]["source_role_anchors"][0])),
    lambda row: row["context_review"].update(context_required_for_interpretation=1),
    lambda row: row["context_review"]["operative_versus_editorial_boundaries"][0].update(context_artifact=pin(b"wrong context")),
    lambda row: row["context_review"]["operative_versus_editorial_boundaries"][0].update(coordinate_space="selected_source_unicode_characters"),
    lambda row: row["exposure_declaration"].update(candidate_or_reference_exposed="false"),
])
def test_typed_calendar_rules_anchors_context_and_exposure_refuse_invalid_shapes(tmp_path, change):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    change(submission["items"][0])
    with pytest.raises(ValueError):
        record(packet, [submission], fixture)


def test_selected_character_coordinates_remain_distinct_from_full_context_and_utf8_bytes(tmp_path):
    packet, fixture = prepared(tmp_path, prefixes=["§ Ω café — synthetic\n"])
    submission = submitted(packet, fixture)
    item = packet["items"][0]
    assert item["source"]["byte_start"] != item["context"]["selected_char_start"]
    receipt = record(packet, [submission], fixture)
    assert receipt["structurally_complete_declaration_count"] == 1
    anchor = submission["items"][0]["review"]["source_role_anchors"][0]
    anchor["char_start"] += item["context"]["selected_char_start"]
    anchor["char_end"] += item["context"]["selected_char_start"]
    with pytest.raises(ValueError, match="literal selector"):
        record(packet, [submission], fixture)


def test_multirule_overlapping_and_repeated_anchors_record_without_flattening(tmp_path):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    review = submission["items"][0]["review"]
    review["multi_rule_status"] = "multiple_rules"
    review["normative_rules"].append(deepcopy(review["normative_rules"][0]))
    originals = deepcopy(review["source_role_anchors"])
    review["source_role_anchors"] += [{**anchor, "anchor_id": anchor["anchor_id"] + "-second", "rule_index": 1}
                                     for anchor in originals]
    receipt = record(packet, [submission], fixture)
    assert receipt["items"][0]["received_declarations"][0]["declaration"]["review"] == review
    diagnostic = subject.assess_declaration_geometry(packet, [submission], submission_index=0,
        item_id=packet["items"][0]["item_id"], **kwargs(packet, fixture))
    assert "requires_exactly_one_rule" in diagnostic["items"][0]["issues"]
    assert diagnostic["items"][0]["source_interval_geometry_representable"] is False
    assert diagnostic["items"][0]["target_created"] is False
    assert all(value == 0 for value in diagnostic["admission_masks"].values())
    assert_zero(receipt)


def with_qualifier(submission, packet):
    review = submission["items"][0]["review"]
    text = packet["items"][0]["input"]["source_text"]
    review["normative_rules"][0]["conditions"] = ["after notice"]
    review["source_role_anchors"].append(literal(text, "after notice", anchor_id="condition-0", rule_index=0, facet="conditions"))
    review["qualifier_attachments"] = [{"attachment_id": "attachment-0", "rule_index": 0, "facet": "conditions",
        "anchor_ids": ["condition-0"], "affected_rule_indices": [0], "scope_kind": "rule",
        "scope_text": "Synthetic declared condition scope for rule zero."}]
    review["freeform_qualifier_scope"] = "Declared condition applies to rule zero."


def test_qualifier_rule_anchor_and_scope_references_are_preserved(tmp_path):
    packet, fixture = prepared(tmp_path, texts=["The clerk shall record evidence after notice."])
    submission = submitted(packet, fixture)
    with_qualifier(submission, packet)
    receipt = record(packet, [submission], fixture)
    assert receipt["items"][0]["received_declarations"][0]["declaration"]["review"]["qualifier_attachments"] == submission["items"][0]["review"]["qualifier_attachments"]
    diagnostic = subject.assess_declaration_geometry(packet, [submission], submission_index=0,
        item_id=packet["items"][0]["item_id"], **kwargs(packet, fixture))
    assert diagnostic["items"][0]["source_interval_geometry_representable"] is True
    assert diagnostic["items"][0]["target_created"] is False
    assert_zero(receipt)


@pytest.mark.parametrize("change", [
    lambda attachment: attachment.update(anchor_ids=["missing-anchor"]),
    lambda attachment: attachment.update(anchor_ids=["actor-0"]),
    lambda attachment: attachment.update(affected_rule_indices=[0, 0]),
    lambda attachment: attachment.update(affected_rule_indices=[5]),
    lambda attachment: attachment.update(scope_kind="shared_rules"),
    lambda attachment: attachment.update(scope_text=""),
])
def test_qualifier_reference_scope_mismatch_refused(tmp_path, change):
    packet, fixture = prepared(tmp_path, texts=["The clerk shall record evidence after notice."])
    submission = submitted(packet, fixture)
    with_qualifier(submission, packet)
    change(submission["items"][0]["review"]["qualifier_attachments"][0])
    with pytest.raises(ValueError):
        record(packet, [submission], fixture)


def test_evidence_bytes_verified_without_authenticating_identities_or_contents(tmp_path):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    submission["items"][0]["evidence"]["identity_evidence"] = fixture["retain"](b"Claiming a human identity is not proving one.")
    submission["items"][0]["context_review"]["source_authority_or_currentness_evidence"] = [fixture["retain"](b"Source-currentness assertion, not authenticated law.")]
    receipt = record(packet, [submission], fixture)
    assert len(receipt["evidence_artifacts"]) == 3
    assert receipt["evidence_integrity_checked"] is True
    assert receipt["evidence_contents_authenticated"] is False
    assert_zero(receipt)
    ref = submission["items"][0]["evidence"]["identity_evidence"]
    fixture["paths"][ref["sha256"]].write_bytes(b"Different bytes")
    with pytest.raises(ValueError):
        record(packet, [submission], fixture)


def test_evidence_mutation_at_closing_boundary_refused(tmp_path):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    ref = submission["items"][0]["evidence"]["review_process_evidence"]
    count = 0

    def resolver(binding):
        nonlocal count
        if binding["sha256"] == ref["sha256"]:
            count += 1
            if count == 2:
                fixture["paths"][binding["sha256"]].write_bytes(b"Changed after opening.")
        return fixture["resolver"](binding)

    with pytest.raises(ValueError):
        subject.record_reviews(packet, [submission], expected_packet_sha256=subject.digest(packet), artifact_resolver=resolver)


def test_changed_packet_or_raw_context_refused_before_review_recording(tmp_path):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    changed = deepcopy(packet)
    changed["items"][0]["review"]["notes"] = "A completed answer cannot be inserted in the blank parent."
    changed["content_sha256"] = subject.digest({key: value for key, value in changed.items() if key != "content_sha256"})
    with pytest.raises(ValueError, match="reconstruction differs"):
        subject.record_reviews(changed, [], expected_packet_sha256=subject.digest(changed), artifact_resolver=fixture["resolver"])
    ref = packet["items"][0]["context"]["artifact"]
    fixture["paths"][ref["sha256"]].write_bytes(b"Mutated complete raw section.")
    with pytest.raises(ValueError):
        record(packet, [submission], fixture)


def test_packet_body_seal_is_not_the_full_packet_binding(tmp_path):
    packet, fixture = prepared(tmp_path)
    assert packet["content_sha256"] != subject.digest(packet)
    with pytest.raises(ValueError, match="content pin mismatch"):
        subject.record_reviews(packet, [], expected_packet_sha256=packet["content_sha256"], artifact_resolver=fixture["resolver"])


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b'{"a":NaN}', b'\xff', b'{} trailing'])
def test_parser_rejects_duplicate_keys_nonfinite_invalid_utf8_and_trailing_bytes(raw):
    with pytest.raises(ValueError):
        subject.parse_json_bytes(raw)


def test_submission_count_and_json_byte_budgets_refused_before_unbounded_work(tmp_path, monkeypatch):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    with pytest.raises(ValueError, match="bounded review submission"):
        record(packet, [submission] * (subject.MAX_SUBMISSIONS + 1), fixture)
    monkeypatch.setattr(subject, "MAX_JSON_BYTES", 10)
    with pytest.raises(ValueError, match="bounded exact JSON bytes"):
        subject.parse_json_bytes(b'{"long":"value"}')


def test_adjudication_declarations_bind_exact_generation_and_stay_pending(tmp_path):
    packet, fixture = prepared(tmp_path)
    submissions = [submitted(packet, fixture)]
    package = adjudication(packet, submissions, fixture)
    receipt = subject.record_adjudications(packet, submissions, package, **kwargs(packet, fixture))
    assert receipt["declared_adjudication_count"] == 1
    assert receipt["external_adjudication_status"] == "pending"
    assert receipt["items"][0]["external_adjudication_status"] == "pending"
    assert_zero(receipt)
    assert_zero(receipt["items"][0])
    validation = subject.validate_adjudication_recording(receipt, packet, submissions, package, **kwargs(packet, fixture))
    assert_zero(validation)
    changed = deepcopy(receipt)
    changed["items"][0]["admitted"] = True
    with pytest.raises(ValueError, match="exact declaration replay"):
        subject.validate_adjudication_recording(changed, packet, submissions, package, **kwargs(packet, fixture))


@pytest.mark.parametrize("change", [
    lambda package: package.update(recording_sha256="0" * 64),
    lambda package: package["items"][0].update(principal_id="synthetic-reviewer-a"),
    lambda package: package["items"][0]["declaration_refs"][0].update(declaration_sha256="0" * 64),
    lambda package: package["items"][0].update(accepted_declaration_refs=[]),
    lambda package: package["items"][0].update(unresolved_scope=["Scope is still unresolved."]),
    lambda package: package["items"][0].update(decision="unsupported"),
    lambda package: package["items"][0].update(decision="accept_alternatives"),
    lambda package: package["items"].append(deepcopy(package["items"][0])),
    lambda package: package["items"][0].update(admitted=True),
])
def test_adjudication_generation_refs_roles_cardinality_and_authority_tamper_refused(tmp_path, change):
    packet, fixture = prepared(tmp_path)
    submissions = [submitted(packet, fixture)]
    package = adjudication(packet, submissions, fixture)
    change(package)
    with pytest.raises(ValueError):
        subject.record_adjudications(packet, submissions, package, **kwargs(packet, fixture))


def test_distinct_declared_alternatives_do_not_resolve_a_dispute_or_admit_targets(tmp_path):
    packet, fixture = prepared(tmp_path)
    first = submitted(packet, fixture)
    second = submitted(packet, fixture, reviewer="synthetic-reviewer-b", identity="synthetic-submission-b")
    second["items"][0]["review"]["normative_rules"][0]["modality"] = "P"
    submissions = [first, second]
    assert record(packet, submissions, fixture)["items"][0]["status"] == "disputed"
    package = adjudication(packet, submissions, fixture, decision="accept_alternatives")
    result = subject.record_adjudications(packet, submissions, package, **kwargs(packet, fixture))
    assert result["items"][0]["declaration"]["decision"] == "accept_alternatives"
    assert result["independent_adjudication_completed"] is False
    assert record(packet, submissions, fixture)["items"][0]["status"] == "disputed"
    assert_zero(result)


def test_omitting_a_review_reference_does_not_hide_a_declared_adjudicator_overlap(tmp_path):
    packet, fixture = prepared(tmp_path)
    first = submitted(packet, fixture)
    second = submitted(packet, fixture, reviewer="synthetic-reviewer-b", identity="synthetic-submission-b")
    submissions = [first, second]
    package = adjudication(packet, submissions, fixture)
    package["items"][0]["declaration_refs"] = package["items"][0]["declaration_refs"][:1]
    package["items"][0]["principal_id"] = "synthetic-reviewer-b"
    with pytest.raises(ValueError, match="recorded reviewer"):
        subject.record_adjudications(packet, submissions, package, **kwargs(packet, fixture))


@pytest.mark.parametrize("mode", ["partial", "missing_evidence", "unknown_index", "unknown_item", "boolean_index"])
def test_geometry_is_explicit_separate_and_refuses_unbound_or_incomplete_declarations(tmp_path, mode):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture, complete=mode != "partial")
    index, identity = 0, packet["items"][0]["item_id"]
    if mode == "missing_evidence":
        submission["items"][0]["evidence"]["review_process_evidence"] = None
    elif mode == "unknown_index":
        index = 1
    elif mode == "unknown_item":
        identity = "unknown-item"
    elif mode == "boolean_index":
        index = True
    with pytest.raises(ValueError):
        subject.assess_declaration_geometry(packet, [submission], submission_index=index,
            item_id=identity, **kwargs(packet, fixture))
