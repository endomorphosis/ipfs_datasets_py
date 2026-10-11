"""Synthetic consistency diagnostics; no human reviews, legal labels or fitting."""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import json
import socket

import pytest

from ipfs_datasets_py.logic.legal_ir import statutory_source_review as packet_source
from ipfs_datasets_py.logic.legal_ir import statutory_review_recording as recorder
from ipfs_datasets_py.logic.legal_ir import statutory_declaration_preflight as subject

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
    return {"expected_packet_sha256": recorder.digest(packet), "artifact_resolver": fixture["resolver"]}

def guide(packet, fixture):
    return recorder.submission_guide(packet, **kwargs(packet, fixture))

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
    return {"schema": recorder.SUBMISSION_SCHEMA, "packet_sha256": recorder.digest(packet),
            "submission_id": identity, "items": [row]}


def preflight(packet, submissions, fixture, **extra):
    return subject.preflight_declarations(packet, submissions, **kwargs(packet, fixture), **extra)


def declaration(result, index=0, item_index=0):
    return result["items"][item_index]["received_declarations"][index]


def codes(row):
    return {issue["code"] for issue in row["diagnostics"]}


def assert_zero(result):
    nodes = [result, *result.get("items", [])]
    nodes += [row for item in result.get("items", []) for row in item["received_declarations"]]
    for node in nodes:
        assert all(node[field] is False for field in packet_source.AUTHORITY_FIELDS)
        assert node["target_eligibility"] is False and node["target_created"] is False
        assert node["declared_consistency_is_legal_correctness"] is False
        assert node["scope_transport_assessed"] is False and node["formal_output_lowered"] is False
        assert all(type(value) is int and value == 0 for value in node["admission_masks"].values())


def multiple(packet, fixture, *, count=2):
    value = submitted(packet, fixture)
    row = value["items"][0]
    row["review"]["multi_rule_status"] = "multiple_rules"
    rule = row["review"]["normative_rules"][0]
    row["review"]["normative_rules"] = [deepcopy(rule) for _ in range(count)]
    anchors = row["review"]["source_role_anchors"]
    row["review"]["source_role_anchors"] = [
        {**anchor, "rule_index": index, "anchor_id": anchor["anchor_id"] + "-rule-" + str(index)}
        for index in range(count) for anchor in anchors]
    return value


def absent_rules(value, *, eligibility="not_normative", interpretation="no_normative_rule"):
    row = value["items"][0]
    row["review"].update(normative_eligibility=eligibility, interpretation_status=interpretation,
                         normative_rules=[], multi_rule_status="no_rule", source_role_anchors=[],
                         qualifier_attachments=[], trigger=[])
    return value


def test_empty_submissions_preserve_pending_physical_items_and_no_labels(tmp_path):
    packet, fixture = prepared(tmp_path, texts=["The clerk shall record evidence."] * 2)
    before = subject.digest(packet)
    result = preflight(packet, [], fixture)
    assert result["status"] == "pending" and result["declaration_count"] == 0
    assert len(result["items"]) == 2 and all(item["received_declarations"] == [] for item in result["items"])
    assert [item["item_id"] for item in result["items"]] == [item["item_id"] for item in packet["items"]]
    assert len({item["physical_identity_sha256"] for item in result["items"]}) == 2
    assert subject.digest(packet) == before
    assert_zero(result)


def test_complete_consistency_never_becomes_target_eligibility(tmp_path):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    result = preflight(packet, [value], fixture)
    row = declaration(result)
    assert row["status"] == "consistent_declared_normative" and row["diagnostics"] == []
    assert result["formal_targets_created"] == result["gold_labels_created"] == result["qualified_training_pairs"] == 0
    assert result["statement_scope_integration"].startswith("deferred_")
    assert row["declaration"] == value["items"][0]
    assert_zero(result)
    validated = subject.validate_preflight(result, packet, [value], **kwargs(packet, fixture))
    assert validated["status"] == "validated_declared_preflight_only"
    assert_zero(validated)


def test_partial_keeps_null_distinct_from_explicit_absent_lists(tmp_path):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture, complete=False)
    value["items"][0]["review"].update(ambiguity=[], notes="")
    row = declaration(preflight(packet, [value], fixture))
    assert row["status"] == "partial" and row["complete"] is False
    assert row["declaration"]["review"]["normative_rules"] is None
    assert row["declaration"]["review"]["ambiguity"] == []
    assert "review.normative_rules" in row["missing_fields"] and "review.ambiguity" not in row["missing_fields"]


def test_partial_with_contradictions_stays_partial_and_retains_diagnostics(tmp_path):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    value["items"][0]["review"].update(normative_eligibility="not_normative", notes=None)
    row = declaration(preflight(packet, [value], fixture))
    assert row["status"] == "partial"
    assert "normative_interpretation_with_not_normative_eligibility" in codes(row)


@pytest.mark.parametrize("field,value,code", [
    ("normative_eligibility", "not_normative", "normative_interpretation_with_not_normative_eligibility"),
    ("definition_status", "definition_only", "definition_only_with_normative_rules"),
])
def test_contradictory_declared_normative_answers_are_separate_from_recording(tmp_path, field, value, code):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    submission["items"][0]["review"][field] = value
    recording = recorder.record_reviews(packet, [submission], **kwargs(packet, fixture))
    assert recording["items"][0]["received_declarations"][0]["complete"] is True
    row = declaration(preflight(packet, [submission], fixture, recording=recording))
    assert row["status"] == "inconsistent" and code in codes(row)
    assert recording["items"][0]["received_declarations"][0]["declaration"] == submission["items"][0]


def test_no_normative_rule_is_not_compatible_with_declared_normative_eligibility(tmp_path):
    packet, fixture = prepared(tmp_path)
    value = absent_rules(submitted(packet, fixture), eligibility="eligible_normative")
    row = declaration(preflight(packet, [value], fixture))
    assert row["status"] == "inconsistent"
    assert "no_normative_rule_with_eligible_normative_declaration" in codes(row)


def test_mixed_definition_and_norm_cannot_also_declare_rules_explicitly_absent(tmp_path):
    packet, fixture = prepared(tmp_path)
    value = absent_rules(submitted(packet, fixture))
    value["items"][0]["review"]["definition_status"] = "mixed_definition_and_norm"
    row = declaration(preflight(packet, [value], fixture))
    assert row["status"] == "inconsistent"
    assert "mixed_definition_and_norm_with_explicitly_absent_rules" in codes(row)


@pytest.mark.parametrize("status", ["no_normative_rule", "needs_context", "ambiguous", "unsupported"])
def test_non_normative_or_unresolved_findings_keep_explicit_empty_rules(tmp_path, status):
    packet, fixture = prepared(tmp_path)
    value = absent_rules(submitted(packet, fixture), interpretation=status)
    row = declaration(preflight(packet, [value], fixture))
    assert row["status"] == ("non_normative" if status == "no_normative_rule" else "unresolved")
    assert row["declaration"]["review"]["normative_rules"] == []


@pytest.mark.parametrize("eligibility", ["needs_context", "ambiguous", "unsupported"])
def test_declared_eligibility_uncertainty_is_not_promoted(tmp_path, eligibility):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    value["items"][0]["review"]["normative_eligibility"] = eligibility
    row = declaration(preflight(packet, [value], fixture))
    assert row["status"] == "unresolved" and "declared_" + eligibility in codes(row)


@pytest.mark.parametrize("section,field,value,code", [
    ("review", "definition_status", "undetermined", "definition_status_undetermined"),
    ("review", "multi_rule_status", "undetermined", "rule_cardinality_undetermined"),
    ("review", "ambiguity", ["Synthetic ambiguity declaration."], "declared_ambiguity_remains"),
    ("review", "unsupported_meaning", ["Synthetic unsupported declaration."], "declared_unsupported_meaning_remains"),
    ("context_review", "context_sufficiency", "needs_external_context", "declared_context_not_sufficient"),
    ("context_review", "context_sufficiency", "undetermined", "declared_context_not_sufficient"),
    ("context_review", "unresolved_dependencies", ["Synthetic unresolved reference."], "declared_unresolved_dependencies"),
])
def test_complete_answers_can_remain_unresolved(tmp_path, section, field, value, code):
    packet, fixture = prepared(tmp_path)
    submission = submitted(packet, fixture)
    submission["items"][0][section][field] = value
    row = declaration(preflight(packet, [submission], fixture))
    assert row["complete"] is True and row["status"] == "unresolved" and code in codes(row)


@pytest.mark.parametrize("change", ["context_required", "governing_definition", "cross_reference", "symbolic_alias", "mixed_definition"])
def test_context_and_alias_non_errors_are_not_inferred_as_contradictions(tmp_path, change):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    row = value["items"][0]
    if change == "context_required":
        row["context_review"]["context_required_for_interpretation"] = True
    elif change == "governing_definition":
        row["context_review"]["governing_definitions"] = ["Synthetic surrounding definition declaration."]
    elif change == "cross_reference":
        row["context_review"]["cross_references"] = ["Synthetic declared reference, not resolved here."]
    elif change == "symbolic_alias":
        row["review"]["normative_rules"][0]["action"] = "caller_symbol_record"
    else:
        row["review"]["definition_status"] = "mixed_definition_and_norm"
    result = preflight(packet, [value], fixture)
    assert declaration(result)["status"] == "consistent_declared_normative"
    assert declaration(result)["diagnostics"] == []
    assert_zero(result)


def test_disputed_item_retains_both_consistent_declarations_without_selecting_one(tmp_path):
    packet, fixture = prepared(tmp_path)
    first = submitted(packet, fixture)
    second = submitted(packet, fixture, reviewer="synthetic-reviewer-b", identity="synthetic-submission-b")
    second["items"][0]["review"]["normative_rules"][0]["modality"] = "P"
    result = preflight(packet, [first, second], fixture)
    assert result["declared_disputed_item_count"] == 1
    assert result["items"][0]["recording_status"] == "disputed"
    assert [row["status"] for row in result["items"][0]["received_declarations"]] == ["consistent_declared_normative"] * 2
    assert [row["declaration"]["review"]["normative_rules"][0]["modality"] for row in result["items"][0]["received_declarations"]] == ["O", "P"]
    assert_zero(result)


def test_equal_declaration_agreement_has_no_authentication_effect(tmp_path):
    packet, fixture = prepared(tmp_path)
    values = [submitted(packet, fixture), submitted(packet, fixture, reviewer="synthetic-reviewer-b", identity="synthetic-submission-b")]
    result = preflight(packet, values, fixture)
    assert result["items"][0]["recording_status"] == "exact_multiple_declaration_agreement"
    assert result["human_reviews_authenticated"] == result["independent_reviews_authenticated"] == 0
    assert_zero(result)


@pytest.mark.parametrize("facet", ["object", "conditions", "exceptions", "temporal"])
def test_anchors_on_explicitly_absent_facets_are_declared_inconsistencies(tmp_path, facet):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    row = value["items"][0]
    if facet == "object":
        row["review"]["normative_rules"][0]["object"] = ""
    else:
        row["review"]["source_role_anchors"][2]["facet"] = facet
    found = declaration(preflight(packet, [value], fixture))
    assert found["status"] == "inconsistent" and "source_anchor_on_declared_absent_facet" in codes(found)


@pytest.mark.parametrize("facet", ["actor", "action", "object"])
def test_nonempty_declared_facet_without_source_role_anchor_is_unresolved(tmp_path, facet):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    value["items"][0]["review"]["source_role_anchors"] = [a for a in value["items"][0]["review"]["source_role_anchors"] if a["facet"] != facet]
    found = declaration(preflight(packet, [value], fixture))
    assert found["status"] == "unresolved" and "declared_facet_without_source_role_anchor" in codes(found)


def test_multiple_rules_preserve_order_and_shared_exact_mentions_without_flattening(tmp_path):
    packet, fixture = prepared(tmp_path)
    value = multiple(packet, fixture)
    value["items"][0]["review"]["normative_rules"][0]["modality"] = "P"
    row = declaration(preflight(packet, [value], fixture))
    assert row["status"] == "consistent_declared_normative"
    assert [r["modality"] for r in row["declaration"]["review"]["normative_rules"]] == ["P", "O"]
    assert len(row["translated_source_role_anchors"]) == 6
    assert row["declaration"] == value["items"][0]
    assert row["legacy_copied_span_geometry_assessed"] is False


def test_ordered_repeated_qualifiers_and_shared_attachments_are_lossless(tmp_path):
    text = "The clerk shall record evidence if B and A and B."
    packet, fixture = prepared(tmp_path, texts=[text])
    value = multiple(packet, fixture)
    row = value["items"][0]
    positions = [text.index("B"), text.index("A"), text.rindex("B")]
    for index, rule in enumerate(row["review"]["normative_rules"]):
        rule["conditions"] = ["B", "A", "B"]
        row["review"]["source_role_anchors"] += [
            {"anchor_id": f"q-{index}-{j}", "rule_index": index, "facet": "conditions",
             "coordinate_space": "selected_source_unicode_characters", "char_start": start,
             "char_end": start + 1, "text": text[start:start + 1]} for j, start in enumerate(positions)]
    row["review"]["qualifier_attachments"] = [{"attachment_id": "synthetic-shared", "rule_index": 0,
        "facet": "conditions", "anchor_ids": ["q-0-0", "q-0-1", "q-0-2"], "affected_rule_indices": [1, 0],
        "scope_kind": "shared_rules", "scope_text": "Caller-declared shared scope; no connective inferred."}]
    found = declaration(preflight(packet, [value], fixture))
    assert found["status"] == "consistent_declared_normative" and found["declaration"] == row
    assert found["declaration"]["review"]["normative_rules"][0]["conditions"] == ["B", "A", "B"]
    assert found["declaration"]["review"]["qualifier_attachments"][0]["affected_rule_indices"] == [1, 0]
    assert found["Boolean_scope_inferred"] is False


@pytest.mark.parametrize("mode", ["owner_absent", "undetermined"])
def test_explicit_attachment_conflicts_and_unresolved_scope_are_diagnosed(tmp_path, mode):
    packet, fixture = prepared(tmp_path)
    value = multiple(packet, fixture, count=3)
    row = value["items"][0]
    row["review"]["qualifier_attachments"] = [{"attachment_id": "synthetic-scope", "rule_index": 0,
        "facet": "conditions", "anchor_ids": [], "affected_rule_indices": [1, 2] if mode == "owner_absent" else [0],
        "scope_kind": "shared_rules" if mode == "owner_absent" else "undetermined",
        "scope_text": "Synthetic scope assertion with no inferred meaning."}]
    found = declaration(preflight(packet, [value], fixture))
    assert found["status"] == ("inconsistent" if mode == "owner_absent" else "unresolved")
    assert ("attachment_owner_rule_not_in_affected_rules" if mode == "owner_absent" else "qualifier_attachment_scope_undetermined") in codes(found)


@pytest.mark.parametrize("kind", ["editorial", "undetermined"])
def test_declared_interval_roles_are_diagnostics_without_semantic_prohibition(tmp_path, kind):
    packet, fixture = prepared(tmp_path, prefixes=["É📄 § Ω archived fixture\n"])
    value = submitted(packet, fixture)
    value["items"][0]["context_review"]["operative_versus_editorial_boundaries"][0]["kind"] = kind
    found = declaration(preflight(packet, [value], fixture))
    assert found["status"] == "consistent_declared_normative"
    assert all(issue["category"] == "declared_interval" for issue in found["diagnostics"])
    original = value["items"][0]["review"]["source_role_anchors"][0]
    translated = found["translated_source_role_anchors"][0]
    shift = packet["items"][0]["context"]["selected_char_start"]
    assert translated["complete_context_char_interval"] == [shift + original["char_start"], shift + original["char_end"]]
    assert shift != packet["items"][0]["source"]["byte_start"]
    assert translated["overlapping_declared_boundary_indices"] == [0]


def test_overlapping_contrary_role_declarations_are_preserved(tmp_path):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    boundaries = value["items"][0]["context_review"]["operative_versus_editorial_boundaries"]
    boundaries.append({**boundaries[0], "kind": "editorial"})
    found = declaration(preflight(packet, [value], fixture))
    assert found["status"] == "consistent_declared_normative"
    assert "contrary_declared_operative_editorial_intervals_overlap" in codes(found)
    assert found["declaration"]["context_review"]["operative_versus_editorial_boundaries"] == boundaries
    assert found["translated_source_role_anchors"][0]["overlapping_declared_boundary_indices"] == [0, 1]


def test_adjacent_editorial_prefix_does_not_overlap_selected_anchor(tmp_path):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    item = packet["items"][0]
    shift = item["context"]["selected_char_start"]
    text = next(v["text"] for v in packet["context_views"] if v["artifact"] == item["context"]["artifact"])
    value["items"][0]["context_review"]["operative_versus_editorial_boundaries"] = [{
        "coordinate_space": "complete_raw_section_unicode_characters", "char_start": 0,
        "char_end": shift, "text": text[:shift], "context_artifact": item["context"]["artifact"], "kind": "editorial"}]
    found = declaration(preflight(packet, [value], fixture))
    assert found["diagnostics"] == [] and all(a["overlapping_declared_boundary_indices"] == [] for a in found["translated_source_role_anchors"])


def test_supplied_recording_is_replayed_before_a_cached_pass_can_be_used(tmp_path):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    recording = recorder.record_reviews(packet, [value], **kwargs(packet, fixture))
    reference = packet["items"][0]["context"]["artifact"]
    path = fixture["resolver"](reference)
    raw = path.read_bytes()
    path.write_bytes(b"X" + raw[1:])
    with pytest.raises(ValueError):
        preflight(packet, [value], fixture, recording=recording)


@pytest.mark.parametrize("change", ["authority", "status", "declaration", "unknown_field"])
def test_changed_supplied_recording_is_refused_even_with_resealed_body(tmp_path, change):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    recording = recorder.record_reviews(packet, [value], **kwargs(packet, fixture))
    if change == "authority":
        recording["qualified_training_pairs"] = 1
    elif change == "status":
        recording["items"][0]["status"] = "pending"
    elif change == "declaration":
        recording["items"][0]["received_declarations"][0]["declaration"]["review"]["normative_rules"][0]["modality"] = "P"
    else:
        recording["invented_authority"] = True
    recording["content_sha256"] = recorder.digest({k: v for k, v in recording.items() if k != "content_sha256"})
    with pytest.raises(ValueError):
        preflight(packet, [value], fixture, recording=recording)


@pytest.mark.parametrize("change", ["status", "mask", "eligibility", "anchor", "order", "unknown_field"])
def test_preflight_replay_refuses_status_pin_order_or_authority_tampering(tmp_path, change):
    packet, fixture = prepared(tmp_path)
    value = multiple(packet, fixture)
    value["items"][0]["review"]["normative_rules"][0]["modality"] = "P"
    receipt = preflight(packet, [value], fixture)
    row = declaration(receipt)
    if change == "status":
        row["status"] = "non_normative"
    elif change == "mask":
        receipt["admission_masks"]["strong_semantic_fit"] = 1
    elif change == "eligibility":
        row["target_eligibility"] = True
    elif change == "anchor":
        row["translated_source_role_anchors"][0]["complete_context_char_interval"][0] += 1
    elif change == "order":
        row["declaration"]["review"]["normative_rules"].reverse()
    else:
        receipt["unknown"] = "unaccepted"
    receipt["content_sha256"] = subject.digest({k: v for k, v in receipt.items() if k != "content_sha256"})
    with pytest.raises(ValueError, match="preflight differs"):
        subject.validate_preflight(receipt, packet, [value], **kwargs(packet, fixture))


@pytest.mark.parametrize("change", ["packet_pin", "source", "context_pin", "physical_id", "submissions"])
def test_source_context_physical_and_submission_tamper_refused(tmp_path, change):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    options = kwargs(packet, fixture)
    if change == "packet_pin":
        options["expected_packet_sha256"] = "0" * 64
    elif change == "source":
        packet["items"][0]["input"]["source_text"] += " tampered"
    elif change == "context_pin":
        value["items"][0]["context_artifact"]["sha256"] = "0" * 64
    elif change == "physical_id":
        value["items"][0]["physical_identity_sha256"] = "0" * 64
    else:
        value["schema"] = "canonical-binding-review-recording/v1"
    with pytest.raises(ValueError):
        subject.preflight_declarations(packet, [value], **options)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1.0}', b'\xff', b'{}{}'])
def test_strict_parser_refuses_duplicates_scores_nonfinite_invalid_utf8_and_trailing_content(raw):
    with pytest.raises(ValueError):
        subject.parse_json_bytes(raw)


@pytest.mark.parametrize("limit", ["MAX_DIAGNOSTICS", "MAX_DIAGNOSTICS_PER_DECLARATION"])
def test_diagnostic_budget_refuses_instead_of_truncating(tmp_path, monkeypatch, limit):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    value["items"][0]["review"]["normative_eligibility"] = "not_normative"
    monkeypatch.setattr(subject, limit, 0)
    with pytest.raises(ValueError, match="diagnostic budget"):
        preflight(packet, [value], fixture)


def test_returned_data_is_detached_and_no_evidence_method_authenticates_reviews(tmp_path):
    packet, fixture = prepared(tmp_path)
    value = submitted(packet, fixture)
    value["items"][0]["evidence"]["review_process_evidence"] = None
    before = subject.digest([packet, value])
    result = preflight(packet, [value], fixture)
    assert declaration(result)["status"] == "consistent_declared_normative"
    assert_zero(result)
    declaration(result)["declaration"]["review"]["normative_rules"][0]["actor"] = "changed returned copy"
    result["items"][0]["source_input"]["source_text"] = "changed returned input"
    assert subject.digest([packet, value]) == before
