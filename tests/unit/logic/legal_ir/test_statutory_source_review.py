"""Synthetic physical byte fixtures; no legal labels or real reviews asserted."""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.legal_ir import statutory_source_review as subject


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
    provenance = {"schema": subject.ORIGIN_SCHEMA, "passed": True,
        "raw_section_and_byte_slice_verified_before_writes": True,
        "source_document_views_complete": True, "rows": records}
    provenance_ref = retain(json.dumps(provenance, ensure_ascii=False, sort_keys=True).encode())
    for row in rows:
        row["physical_origin"]["provenance_artifact"] = provenance_ref
    return {"rows": rows, "paths": paths, "provenance": provenance, "retain": retain,
            "resolver": lambda ref: paths[ref["sha256"]]}


def create(fixture):
    return subject.create_blank_packet(fixture["rows"], artifact_resolver=fixture["resolver"])


def validate(packet, fixture):
    return subject.validate_blank_packet(packet, expected_packet_sha256=subject.digest(packet),
                                         artifact_resolver=fixture["resolver"])


def reseal(packet):
    packet["content_sha256"] = subject.digest({key: value for key, value in packet.items() if key != "content_sha256"})
    return packet


def change_provenance(fixture, mutate):
    body = deepcopy(fixture["provenance"])
    mutate(body)
    ref = fixture["retain"](json.dumps(body, ensure_ascii=False, sort_keys=True).encode())
    for row in fixture["rows"]:
        row["physical_origin"]["provenance_artifact"] = ref


def assert_no_authority(receipt):
    assert all(receipt[name] is False for name in subject.AUTHORITY_FIELDS)
    assert all(type(value) is int and value == 0 for value in receipt["admission_masks"].values())


def anchor(text, surface, *, offset=None):
    left = text.index(surface) if offset is None else offset
    return {"coordinate_space": "selected_source_unicode_characters", "char_start": left,
            "char_end": left + len(surface), "text": surface}


def proposal(packet, fixture, *, item_index=0, rules=None, status="normative"):
    item = packet["items"][item_index]
    text = item["input"]["source_text"]
    if rules is None:
        rules = [{"modality": "O", "actor": [anchor(text, "The clerk")],
            "action": [anchor(text, "record")], "object": [anchor(text, "evidence")],
            "conditions": [], "exceptions": [], "temporal": []}]
    evidence = fixture["retain"](b"Synthetic caller review declaration; no person authenticated.")
    return {"item_id": item["item_id"], "packet_sha256": subject.digest(packet),
        "review_declaration": {"status": "caller_declared_source_context_reviewed_proposal",
            "reviewer_id": "unit-declared-reviewer", "reviewed_at_utc": "2026-10-11T00:00:00Z",
            "evidence_artifact": evidence, "source_text_sha256": item["source_text_sha256"],
            "context_artifact_sha256": item["context"]["artifact"]["sha256"]},
        "interpretation_status": status, "rules": rules}


def assess(packet, proposals, fixture):
    return subject.assess_representability(packet, proposals, expected_packet_sha256=subject.digest(packet),
                                           artifact_resolver=fixture["resolver"])


def test_unicode_source_context_preserves_character_byte_and_lexical_coordinates(tmp_path):
    f = make_fixture(tmp_path, texts=["Le greffier doit conserver le café — aujourd’hui."])
    packet = create(f)
    item = packet["items"][0]
    assert item["source"]["byte_start"] != item["context"]["selected_char_start"]
    for token in item["lexical_source"]["tokens"]:
        source = item["input"]["source_text"]
        assert source[token["char_start"]:token["char_end"]] == token["text"]
        assert source.encode()[token["utf8_byte_start"]:token["utf8_byte_end"]].decode() == token["text"]
        assert token["casefold_utf8_byte_ids"] == [value + 1 for value in token["text"].casefold().encode()]
    assert validate(packet, f)["local_source_bytes_and_selectors_verified"] is True
    assert item["physical_origin"]["parent_export_bytes_reverified"] is False
    assert item["physical_origin"]["official_HTML_coordinate_mapping_verified"] is False
    assert_no_authority(packet)
    assert_no_authority(item)


@pytest.mark.parametrize("mutate", [
    lambda row: row["context"].update(selected_char_start=0),
    lambda row: row["source"].update(byte_start=row["context"]["selected_char_start"]),
    lambda row: row["context"].update(complete_raw_section=False),
    lambda row: row["context"].update(normalization="whitespace-v1"),
    lambda row: row["source"].update(normalization="whitespace-v1"),
    lambda row: row["source"].update(source_kind="legacy_us_code"),
    lambda row: row["source"].update(byte_start=True),
    lambda row: row["context"].update(selected_char_end=True),
    lambda row: row.update(source_text="The clerk shall record a different source."),
])
def test_rejects_wrong_unicode_selectors_raw_normalization_and_source_aliases(tmp_path, mutate):
    f = make_fixture(tmp_path)
    mutate(f["rows"][0])
    with pytest.raises(ValueError):
        create(f)


def test_modified_context_bytes_rejected_without_trusting_path_or_declared_hash(tmp_path):
    f = make_fixture(tmp_path)
    path = f["paths"][f["rows"][0]["source"]["artifact"]["sha256"]]
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"clerk", b"agent"))
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        create(f)


def test_changed_context_between_opening_and_closing_snapshots_refuses(tmp_path):
    f = make_fixture(tmp_path)
    key = f["rows"][0]["source"]["artifact"]["sha256"]
    counts = {}

    def resolver(ref):
        counts[ref["sha256"]] = counts.get(ref["sha256"], 0) + 1
        path = f["resolver"](ref)
        if ref["sha256"] == key and counts[key] == 2:
            path.write_bytes(path.read_bytes().replace(b"clerk", b"agent"))
        return path

    with pytest.raises(ValueError, match="SHA256 mismatch"):
        subject.create_blank_packet(f["rows"], artifact_resolver=resolver)


def test_resolver_bytes_are_not_accepted_as_a_path(tmp_path):
    f = make_fixture(tmp_path)
    with pytest.raises(ValueError, match="local path"):
        subject.create_blank_packet(f["rows"], artifact_resolver=lambda ref: b"raw bytes")


@pytest.mark.parametrize("alias", ["symlink", "parent_symlink", "hardlink", "dotdot"])
def test_ordinary_view_aliases_refused(tmp_path, alias):
    f = make_fixture(tmp_path)
    key = f["rows"][0]["source"]["artifact"]["sha256"]
    path = f["paths"][key]
    if alias == "symlink":
        chosen = tmp_path / "alias.txt"
        chosen.symlink_to(path)
    elif alias == "parent_symlink":
        directory = tmp_path / "directory-alias"
        directory.symlink_to(tmp_path, target_is_directory=True)
        chosen = directory / path.name
    elif alias == "hardlink":
        chosen = tmp_path / "linked.txt"
        os.link(path, chosen)
    else:
        directory = tmp_path / "child"
        directory.mkdir()
        chosen = directory / ".." / path.name
    f["paths"][key] = chosen
    with pytest.raises(ValueError):
        create(f)


@pytest.mark.parametrize("field,value", [
    ("physical_source_section_offset", True),
    ("raw_span_char_offsets", [0, 1]),
    ("raw_section_sha256", "0" * 64),
    ("legal_id", "source-alias"),
    ("raw_span_sha256_equals_historical_normalized_source_sha256", False),
    ("training_qualified", True),
    ("source_view_complete_raw_section", False),
    ("canonical_ir", {"rules": []}),
])
def test_replays_origin_coordinates_identity_crossjoin_and_unqualified_status(tmp_path, field, value):
    f = make_fixture(tmp_path)
    change_provenance(f, lambda body: body["rows"][0].update({field: value}))
    with pytest.raises(ValueError):
        create(f)


def test_historical_normalized_and_raw_sources_remain_explicitly_separate(tmp_path):
    f = make_fixture(tmp_path)
    change_provenance(f, lambda body: body["rows"][0].update(
        historical_normalized_source_sha256="2" * 64,
        raw_span_sha256_equals_historical_normalized_source_sha256=False,
        raw_span_text_equals_historical_normalized_source_text=False))
    item = create(f)["items"][0]
    assert item["physical_origin"]["historical_normalized_and_raw_hash_equal"] is False
    assert item["physical_origin"]["historical_normalized_and_raw_text_equal_declared"] is False
    assert item["physical_origin"]["historical_normalized_text_bytes_reverified"] is False


def test_equal_text_in_distinct_physical_sections_retained_not_merged(tmp_path):
    f = make_fixture(tmp_path, texts=["The clerk shall record evidence."] * 2, ordinals=[12, 13])
    packet = create(f)
    assert len(packet["items"]) == 2
    assert len({item["item_id"] for item in packet["items"]}) == 2
    assert len(packet["context_views"]) == 1
    assert len(packet["duplicate_inventory"]["exact_source"][0]["item_ids"]) == 2
    assert packet["duplicate_inventory"]["physical_occurrences_merged"] is False
    assert packet["duplicate_inventory"]["global_duplicate_closure_verified"] is False
    validate(packet, f)


def test_case_id_alias_cannot_admit_duplicate_physical_occurrence(tmp_path):
    f = make_fixture(tmp_path, texts=["The clerk shall record evidence."] * 2, ordinals=[12, 12])
    with pytest.raises(ValueError, match="duplicate physical occurrence"):
        create(f)


def test_cached_row_id_cannot_override_physical_origin_case_join(tmp_path):
    f = make_fixture(tmp_path)
    f["rows"][0]["id"] = "new-cache-alias"
    with pytest.raises(ValueError, match="origin record"):
        create(f)


def test_duplicate_metadata_json_keys_are_rejected_before_source_origin_join(tmp_path):
    f = make_fixture(tmp_path)
    original = json.dumps(f["provenance"], sort_keys=True).encode()
    duplicate = b'{"schema":"wrong",' + original[1:]
    ref = f["retain"](duplicate)
    f["rows"][0]["physical_origin"]["provenance_artifact"] = ref
    with pytest.raises(ValueError, match="strict metadata UTF8 JSON"):
        create(f)


def test_packet_content_is_deterministic_under_row_order_but_not_source_identity_changes(tmp_path):
    f = make_fixture(tmp_path, texts=["The clerk shall record evidence.", "The officer may retain records."])
    first = create(f)
    f["rows"].reverse()
    assert create(f) == first


def test_unknown_exposure_with_no_events_remains_review_only_and_not_unseen(tmp_path):
    f = make_fixture(tmp_path)
    f["rows"][0]["exposure"] = {"status": "exposure_unknown_review_only",
        "prior_exposure_complete": False, "events": []}
    packet = create(f)
    assert packet["items"][0]["prior_exposure"]["evaluation_role"] == (
        "review_only_development_source_not_independent_confirmation")
    assert_no_authority(packet)


@pytest.mark.parametrize("mutate", [
    lambda row: row["exposure"].update(status="fresh_holdout"),
    lambda row: row["exposure"].update(prior_exposure_complete=True),
    lambda row: row["exposure"]["events"][0].update(case_id="another-case"),
    lambda row: row["exposure"]["events"][0].update(source_text_sha256="0" * 64),
    lambda row: row["exposure"]["events"][0].update(predicted_actor="clerk"),
    lambda row: row.update(target={"modality": "O"}),
    lambda row: row.update(source_text_score=0.4),
])
def test_rejects_exposure_crossjoins_candidate_fields_targets_and_unseen_claims(tmp_path, mutate):
    f = make_fixture(tmp_path)
    mutate(f["rows"][0])
    with pytest.raises(ValueError):
        create(f)


def test_no_exposure_prediction_or_original_export_body_is_opened(tmp_path):
    f = make_fixture(tmp_path)
    calls = []

    def resolver(ref):
        calls.append(ref["sha256"])
        return f["resolver"](ref)

    packet = subject.create_blank_packet(f["rows"], artifact_resolver=resolver)
    assert set(calls) == set(f["paths"])
    exposure = packet["items"][0]["prior_exposure"]
    assert exposure["evidence_bodies_opened"] is False
    assert exposure["evidence_content_case_join_verified"] is False
    assert exposure["reviewer_blindness_verified"] is False


@pytest.mark.parametrize("part,field,value", [
    ("review", "normative_eligibility", False),
    ("review", "normative_rules", []),
    ("context_review", "governing_definitions", []),
    ("target_binding", "proposed_target", {"modality": "O"}),
    ("admission_masks", "weak_decoder_fit", 1),
    ("admission_masks", "fidelity_evaluation", False),
])
def test_blank_snapshot_cannot_be_resealed_with_answers_or_promoted_masks(tmp_path, part, field, value):
    f = make_fixture(tmp_path)
    packet = create(f)
    packet["items"][0][part][field] = value
    reseal(packet)
    with pytest.raises(ValueError, match="reconstruction differs"):
        validate(packet, f)


def test_blank_template_null_means_unanswered_without_absence_or_eligibility(tmp_path):
    f = make_fixture(tmp_path)
    packet = create(f)
    template = subject.review_template(packet, expected_packet_sha256=subject.digest(packet),
                                      artifact_resolver=f["resolver"])
    assert template["schema"] != "symbol-binding-source-reviewer/v1"
    assert template["submission_recording_supported"] is False
    for item in template["items"]:
        assert all(value is None for value in item["review"].values())
        assert all(value is None for value in item["context_review"].values())
        assert item["representability_assessment"] is None
        assert_no_authority(item)
    assert packet["items"][0]["representability"]["source_interval_geometry_representable"] is None
    assert_no_authority(template)


def test_input_and_template_return_values_are_detached_and_pin_is_required(tmp_path):
    f = make_fixture(tmp_path)
    packet = create(f)
    old = deepcopy(packet)
    f["rows"][0]["source_text"] = "Caller changed original input after construction."
    assert packet == old
    template = subject.review_template(packet, expected_packet_sha256=subject.digest(packet),
                                      artifact_resolver=f["resolver"])
    template["items"][0]["context_artifact"]["sha256"] = "0" * 64
    assert packet == old
    with pytest.raises(ValueError, match="content pin mismatch"):
        subject.validate_blank_packet(packet, expected_packet_sha256="0" * 64, artifact_resolver=f["resolver"])


def test_template_uses_pinned_detached_packet_when_caller_mutates_outer_input(tmp_path):
    f = make_fixture(tmp_path)
    packet = create(f)
    expected = subject.digest(packet)

    def resolver(ref):
        packet["items"][0]["review"]["normative_rules"] = [{"untrusted": "outer caller mutation"}]
        packet["items"][0]["training_qualified"] = True
        return f["resolver"](ref)

    template = subject.review_template(packet, expected_packet_sha256=expected, artifact_resolver=resolver)
    assert template["packet_sha256"] == expected
    assert template["items"][0]["review"]["normative_rules"] is None
    assert_no_authority(template["items"][0])
    with pytest.raises(ValueError, match="content pin mismatch"):
        subject.validate_blank_packet(packet, expected_packet_sha256=expected, artifact_resolver=f["resolver"])


def test_geometry_requires_explicit_separate_unverified_review_and_preserves_blank_packet(tmp_path):
    f = make_fixture(tmp_path)
    packet = create(f)
    old = deepcopy(packet)
    result = assess(packet, [proposal(packet, f)], f)
    row = result["items"][0]
    assert row["source_interval_geometry_representable"] is True
    assert row["review_declaration_verified"] is False
    assert row["semantic_representability_verified"] is False
    assert row["target_created"] is False
    assert result["review_declarations_authenticated"] == 0
    assert_no_authority(row)
    assert_no_authority(result)
    assert packet == old


@pytest.mark.parametrize("mutation", [
    lambda p: p["review_declaration"].update(status="model_generated"),
    lambda p: p["review_declaration"].update(source_text_sha256="0" * 64),
    lambda p: p["review_declaration"].update(context_artifact_sha256="0" * 64),
    lambda p: p.update(packet_sha256="0" * 64),
    lambda p: p["rules"][0]["actor"][0].update(coordinate_space="complete_section_UTF8_bytes"),
    lambda p: p["rules"][0]["actor"][0].update(char_start=True),
    lambda p: p["rules"][0]["action"][0].update(text="retain"),
])
def test_geometry_refuses_undeclared_review_unbound_evidence_and_wrong_anchor_coordinates(tmp_path, mutation):
    f = make_fixture(tmp_path)
    packet = create(f)
    p = proposal(packet, f)
    mutation(p)
    with pytest.raises(ValueError):
        assess(packet, [p], f)


def test_geometry_reports_crossfacet_overlap_without_semantic_repair(tmp_path):
    f = make_fixture(tmp_path)
    packet = create(f)
    p = proposal(packet, f)
    p["rules"][0]["object"] = deepcopy(p["rules"][0]["action"])
    result = assess(packet, [p], f)["items"][0]
    assert result["source_interval_geometry_representable"] is False
    assert "overlapping_copied_facets:object" in result["issues"]
    assert_no_authority(result)


def test_geometry_reports_repeated_surfaces_and_multirule_profile_limits(tmp_path):
    f = make_fixture(tmp_path, texts=["The clerk shall record evidence and retain evidence."])
    packet = create(f)
    p = proposal(packet, f)
    p["rules"].append(deepcopy(p["rules"][0]))
    result = assess(packet, [p], f)["items"][0]
    assert result["source_interval_geometry_representable"] is False
    assert "requires_exactly_one_rule" in result["issues"]
    assert "ambiguous_copied_surface:object" in result["issues"]
    assert_no_authority(result)


def test_non_normative_declaration_and_unproposed_cases_are_not_semantic_negatives(tmp_path):
    f = make_fixture(tmp_path, texts=["The clerk shall record evidence.", "A synthetic term means a fixture."])
    packet = create(f)
    p = proposal(packet, f, rules=[], status="no_normative_rule")
    result = assess(packet, [p], f)
    assert result["items"][0]["source_interval_geometry_representable"] is None
    assert len(result["not_assessed_item_ids"]) == 1
    assert_no_authority(result)


def test_geometry_misaligned_anchor_is_a_profile_limit_not_a_repaired_target(tmp_path):
    f = make_fixture(tmp_path)
    packet = create(f)
    p = proposal(packet, f)
    p["rules"][0]["actor"] = [anchor(p["rules"][0]["actor"][0]["text"], "he clerk", offset=1)]
    result = assess(packet, [p], f)["items"][0]
    assert "not_token_aligned:actor" in result["issues"]
    assert result["source_interval_geometry_representable"] is False


def test_lexical_limit_does_not_truncate_or_claim_semantic_unrepresentability(tmp_path):
    f = make_fixture(tmp_path, texts=["word " * 257])
    item = create(f)["items"][0]
    assert item["lexical_source"]["token_count"] == 257
    assert item["lexical_source"]["truncated"] is False
    assert item["lexical_source"]["within_retained_lexical_transport_limits"] is False
    assert item["representability"]["source_interval_geometry_representable"] is None


def test_selected_context_and_row_budgets_refuse_without_partial_packet(tmp_path):
    f = make_fixture(tmp_path)
    with pytest.raises(ValueError, match="one to32"):
        subject.create_blank_packet(f["rows"] * 33, artifact_resolver=f["resolver"])
    f = make_fixture(tmp_path, texts=["x" * (subject.MAX_SELECTED_BYTES + 1)])
    with pytest.raises(ValueError, match="byte budget"):
        create(f)


def test_context_artifact_count_and_aggregate_bytes_have_separate_bounds(tmp_path):
    f = make_fixture(tmp_path, texts=["The clerk shall record fixture " + str(i) + "." for i in range(17)])
    with pytest.raises(ValueError, match="context closure exceeds budget"):
        create(f)
    f = make_fixture(tmp_path, texts=["The clerk shall record evidence."] * 2,
                     prefixes=["a" * 600000, "b" * 600000])
    with pytest.raises(ValueError, match="context closure exceeds budget"):
        create(f)
    f = make_fixture(tmp_path)
    f["rows"][0]["context"]["artifact"]["bytes"] = subject.MAX_CONTEXT_BYTES + 1
    with pytest.raises(ValueError, match="byte budget"):
        create(f)


def test_packet_and_geometry_work_with_numerical_imports_denied(tmp_path, monkeypatch):
    f = make_fixture(tmp_path)
    real_import = builtins.__import__
    forbidden = {"torch", "numpy", "transformers", "sentence_transformers", "tensorflow", "jax"}

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in forbidden:
            raise AssertionError("numerical import denied: " + name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    packet = create(f)
    validate(packet, f)
    subject.review_template(packet, expected_packet_sha256=subject.digest(packet), artifact_resolver=f["resolver"])
    result = assess(packet, [proposal(packet, f)], f)
    assert result["items"][0]["source_interval_geometry_representable"] is True
    assert_no_authority(result)
