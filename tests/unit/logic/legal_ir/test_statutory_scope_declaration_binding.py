"""Synthetic declaration custody and scope joins; no independently reviewed gold."""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import json
import socket

import pytest

from ipfs_datasets_py.logic.legal_ir import statutory_source_review as packets
from ipfs_datasets_py.logic.legal_ir import statutory_review_recording as recorder
from ipfs_datasets_py.logic.legal_ir import statutory_declaration_preflight as preflight
from ipfs_datasets_py.logic.legal_ir import statutory_scope_declaration_binding as subject

TEXT = "É📄 The clerk shall record evidence if A and B and A unless X or Y before T. For each z in People."


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def ref(raw):
    return {"sha256": sha(raw), "bytes": len(raw)}


def synthetic_packet(tmp_path, *, count=1, prefix="§ Ω archived fixture\n", text=TEXT):
    paths, records, rows = {}, [], []
    parent = {**ref(b"Synthetic parent bytes not read or authenticated."), "repository_id": "unit/synthetic",
              "revision": "1" * 40, "release_id": "synthetic-release"}

    def retain(raw):
        value = ref(raw)
        path = tmp_path / (value["sha256"] + ".artifact")
        if not path.exists():
            path.write_bytes(raw)
        paths[value["sha256"]] = path
        return value

    for index in range(count):
        complete = prefix + text + "\nSynthetic fixture notes; no legal authority."
        artifact = retain(complete.encode())
        start, end = len(prefix), len(prefix) + len(text)
        bstart, bend = len(prefix.encode()), len((prefix + text).encode())
        identity = "synthetic-source-" + str(index)
        source = {"artifact": artifact, "source_kind": "us_code", "release_id": parent["release_id"],
                  "document_id": "unit:section:" + str(index), "language": "en", "citation": "Synthetic " + str(index),
                  "byte_start": bstart, "byte_end": bend, "normalization": "identity"}
        records.append({"request_id": identity, "parent_parquet": parent, "physical_source_section_offset": index,
                        "raw_section_sha256": artifact["sha256"], "raw_span_char_offsets": [start, end],
                        "raw_span_utf8_byte_offsets": [bstart, bend], "raw_span_sha256": sha(text.encode()),
                        "source_view": artifact, "legal_id": source["document_id"], "citation": source["citation"],
                        "source_kind": "us_code", "source_view_normalization": "identity",
                        "source_view_complete_raw_section": True, "source_view_truncated": False,
                        "request_text_equals_exact_raw_span": True, "historical_census_occurrence_id": identity,
                        "historical_source_span_id": identity, "historical_normalized_source_sha256": sha(text.encode()),
                        "raw_span_sha256_equals_historical_normalized_source_sha256": True,
                        "raw_span_text_equals_historical_normalized_source_text": True, "frontend": "legacy_us_code",
                        **dict.fromkeys(("admitted", "formalized", "proof_authority", "source_authority_authenticated",
                                         "source_semantics_verified", "target_attached", "training_qualified"), False)})
        rows.append({"id": identity, "source_text": text, "source": source,
                     "physical_origin": {"provenance_artifact": None, "provenance_record_id": identity},
                     "context": {"artifact": artifact, "selected_char_start": start, "selected_char_end": end,
                                 "complete_raw_section": True, "normalization": "identity"},
                     "exposure": {"status": "previously_exposed_development", "prior_exposure_complete": False,
                                  "events": [{"stage": "source-context-engineering-inspection", "case_id": identity,
                                              "source_text_sha256": sha(text.encode()), "evidence_artifact": ref(b"Not authenticated.")}]}})
    provenance = {"schema": packets.ORIGIN_SCHEMA, "passed": True,
                  "raw_section_and_byte_slice_verified_before_writes": True,
                  "source_document_views_complete": True, "rows": records}
    origin = retain(json.dumps(provenance, sort_keys=True, ensure_ascii=False).encode())
    for row in rows:
        row["physical_origin"]["provenance_artifact"] = origin
    fixture = {"paths": paths, "retain": retain, "resolver": lambda value: paths[value["sha256"]]}
    packet = packets.create_blank_packet(rows, artifact_resolver=fixture["resolver"])
    return packet, fixture


def options(packet, fixture):
    return {"expected_packet_sha256": subject.digest(packet), "artifact_resolver": fixture["resolver"]}


def anchor(text, surface, *, after=0, **extra):
    start = text.index(surface, after)
    return {"coordinate_space": "selected_source_unicode_characters", "char_start": start,
            "char_end": start + len(surface), "text": surface, **extra}


def submission(packet, fixture, *, rule_count=1, shared=False, qualifiers=True,
               reviewer="synthetic-reviewer-a", identity="synthetic-submission-a", item_index=0):
    row = deepcopy(recorder.submission_guide(packet, **options(packet, fixture))["items"][item_index])
    item = packet["items"][item_index]
    text = item["input"]["source_text"]
    literals = {"conditions": ["A", "B", "A"], "exceptions": ["X", "Y"], "temporal": ["T"]}
    rules, anchors, attachments = [], [], []
    for index in range(rule_count):
        rules.append({"modality": "O", "actor": "The clerk", "action": "record", "object": "evidence",
                      **{facet: literals[facet][:] if qualifiers else [] for facet in recorder.QUALIFIERS}})
        for facet, surface in [("actor", "The clerk"), ("action", "record"), ("object", "evidence")]:
            anchors.append(anchor(text, surface, anchor_id=f"r{index}-{facet}", rule_index=index, facet=facet))
        if qualifiers:
            for facet in recorder.QUALIFIERS:
                after = text.index({"conditions": "if ", "exceptions": "unless ", "temporal": "before "}[facet])
                ids = []
                for position, surface in enumerate(literals[facet]):
                    identity_anchor = f"r{index}-{facet}-{position}"
                    value = anchor(text, surface, after=after, anchor_id=identity_anchor, rule_index=index, facet=facet)
                    anchors.append(value)
                    after = value["char_end"]
                    ids.append(identity_anchor)
                is_shared = shared and facet == "conditions"
                attachments.append({"attachment_id": f"r{index}-{facet}-attachment", "rule_index": index,
                                    "facet": facet, "anchor_ids": ids, "affected_rule_indices": list(range(rule_count)) if is_shared else [index],
                                    "scope_kind": "shared_rules" if is_shared else "rule",
                                    "scope_text": "Synthetic caller-declared scope; not legal interpretation."})
    row["review"] = {"normative_eligibility": "eligible_normative", "definition_status": "no_definition_declared",
                     "multi_rule_status": "multiple_rules" if rule_count > 1 else "single_rule", "interpretation_status": "normative",
                     "normative_rules": rules, "source_role_anchors": anchors, "qualifier_attachments": attachments,
                     "trigger": [anchor(text, "shall")], "ambiguity": [], "unsupported_meaning": [],
                     "freeform_qualifier_scope": "", "notes": "Synthetic declaration, no human authenticity.",
                     "reviewer_id": reviewer, "reviewed_at_utc": "2026-10-11T00:00:00Z"}
    row["context_review"] = {"context_required_for_interpretation": False,
                             "operative_versus_editorial_boundaries": [], "governing_definitions": [], "cross_references": [],
                             "unresolved_dependencies": [], "context_sufficiency": "sufficient_as_declared",
                             "source_authority_or_currentness_evidence": []}
    row["evidence"]["review_process_evidence"] = fixture["retain"](b"Synthetic process evidence; not reviewed truth.")
    row["exposure_declaration"] = {"candidate_or_reference_exposed": False, "organizer_metadata_exposed": False,
                                  "other_exposure": "Synthetic fixture; no reviewer blindness authenticated."}
    return {"schema": recorder.SUBMISSION_SCHEMA, "packet_sha256": subject.digest(packet),
            "submission_id": identity, "items": [row]}


def seal_scope(declaration):
    declaration["content_sha256"] = subject.digest({k: v for k, v in declaration.items() if k != "content_sha256"})


def sidecar(packet, value, fixture, *, shared=False, binder=False, context_anchors=False):
    guide = subject.prepare_binding_slots(packet, [value], **options(packet, fixture))
    index = next(i for i, item in enumerate(guide["items"]) if item["item_id"] == value["items"][0]["item_id"])
    output = deepcopy(guide["items"][index]["submission_slots"][0]["slot"])
    output["binding_id"] = "synthetic-binding-" + value["submission_id"]
    request = deepcopy(guide["items"][index]["scope_request"])
    assert request is not None
    reviewed = value["items"][0]["review"]
    item = packet["items"][index]
    text, shift = request["source_text"], item["context"]["selected_char_start"]
    occurrences, rules, maps, qualifier_maps, attachment_maps = [], [], [], [], []
    seen = set()

    def occur(identity, facet, symbol, left, right):
        if identity in seen:
            return
        seen.add(identity)
        origin = "context" if context_anchors else "source"
        a, b = (left + shift, right + shift) if context_anchors else (left, right)
        source = request["context"]["text"] if context_anchors else text
        occurrences.append({"occurrence_id": identity, "facet": facet, "canonical_symbol": symbol,
                            "anchor": {"origin": origin, "start": a, "end": b, "text": source[a:b],
                                       "offset_unit": "unicode_character_half_open"}})

    shared_conditions = None
    for index_rule, original in enumerate(reviewed["normative_rules"]):
        body = {}
        cue = anchor(text, "shall")
        occur(f"r{index_rule}-modal", "modality", original["modality"], cue["char_start"], cue["char_end"])
        body["modality"] = f"r{index_rule}-modal"
        for facet in ("actor", "action", "object"):
            if original[facet] == "":
                body[facet] = None
                continue
            value_anchor = next(a for a in reviewed["source_role_anchors"] if a["rule_index"] == index_rule and a["facet"] == facet)
            occur(value_anchor["anchor_id"], facet, original[facet], value_anchor["char_start"], value_anchor["char_end"])
            body[facet] = value_anchor["anchor_id"]
        expressions = {}
        for facet in recorder.QUALIFIERS:
            children = []
            for position, symbol in enumerate(original[facet]):
                value_anchor = next(a for a in reviewed["source_role_anchors"] if a["anchor_id"] == f"r{index_rule}-{facet}-{position}")
                identity_occ = f"shared-conditions-{position}" if shared and facet == "conditions" else value_anchor["anchor_id"]
                occur(identity_occ, facet, symbol, value_anchor["char_start"], value_anchor["char_end"])
                children.append({"op": "leaf", "occurrence_id": identity_occ})
                base = "/statement_structure/qualifiers/conditions" if shared and facet == "conditions" else f"/rules/{index_rule}/qualifiers/{facet}"
                path = base + f"/children/{position}" if len(original[facet]) > 1 else base
                qualifier_maps.append({"rule_index": index_rule, "facet": facet, "qualifier_index": position, "scope_leaf_path": path})
            expression = (None if not children else children[0] if len(children) == 1 else
                          {"op": "any" if facet == "exceptions" else "all", "children": children, "operator_anchor": None})
            if shared and facet == "conditions":
                shared_conditions = expression
                expressions[facet] = None
            else:
                expressions[facet] = expression
        rules.append({"rule_id": f"scope-rule-{index_rule}", "body": body, "qualifiers": expressions})
    for value_anchor in reviewed["source_role_anchors"]:
        identity_occ = ("shared-conditions-" + value_anchor["anchor_id"].rsplit("-", 1)[1]
                        if shared and value_anchor["facet"] == "conditions" else value_anchor["anchor_id"])
        maps.append({"anchor_id": value_anchor["anchor_id"], "scope_occurrence_id": identity_occ})
    for attachment in reviewed["qualifier_attachments"]:
        path = ("/statement_structure/qualifiers/conditions" if shared and attachment["facet"] == "conditions" else
                f"/rules/{attachment['rule_index']}/qualifiers/{attachment['facet']}")
        attachment_maps.append({"attachment_id": attachment["attachment_id"], "scope_path": path})
    structure = ({"op": "rule", "rule_id": rules[0]["rule_id"]} if len(rules) == 1 else
                 {"op": "all", "children": [{"op": "rule", "rule_id": r["rule_id"]} for r in rules], "operator_anchor": None})
    if shared:
        structure = {"op": "attach", "body": structure, "qualifiers": {"conditions": shared_conditions, "exceptions": None, "temporal": None}}
    binders = []
    if binder:
        for identity, facet, surface in [("variable-z", "binder_variable", "z"), ("domain-People", "binder_domain", "People")]:
            point = text.index(surface, text.index("For each"))
            occur(identity, facet, surface, point, point + len(surface))
        binders.append({"binder_id": "caller-binder", "quantifier": "forall", "variable_occurrence": "variable-z",
                        "domain_occurrence": "domain-People", "scope_path": "/rules/0", "bound_occurrence_ids": ["r0-actor"]})
    declaration = {"schema": "canonical-normative-scope-declaration/v1", "family": "deontic",
                   "profile": "normative-occurrence-scope/v1", "input": request, "input_sha256": output["scope_input_sha256"],
                   "occurrences": occurrences, "rules": rules, "statement_structure": structure, "binders": binders,
                   "coverage": {"declared_status": "partial", "segments": []}, "unresolved": []}
    seal_scope(declaration)
    output.update(scope_declaration=declaration, rule_bindings=[{"rule_index": i, "scope_rule_id": r["rule_id"]} for i, r in enumerate(rules)],
                  modality_bindings=[{"rule_index": i, "scope_occurrence_id": r["body"]["modality"]} for i, r in enumerate(rules)],
                  qualifier_bindings=qualifier_maps, anchor_bindings=maps, attachment_bindings=attachment_maps)
    return output


def bind(packet, submissions, sidecars, fixture, **extra):
    return subject.bind_scope_declarations(packet, submissions, sidecars, **options(packet, fixture), **extra)


def first(result, item_index=0, declaration_index=0):
    return result["items"][item_index]["reviewed_declarations"][declaration_index]


def assert_zero(result):
    for node in [result, *result.get("items", []), *[d for r in result.get("items", []) for d in r.get("reviewed_declarations", [])]]:
        assert all(node[k] is False for k in packets.AUTHORITY_FIELDS)
        assert node["target_eligibility"] is False and node["target_created"] is False
        assert node["review_status_promoted"] is False and node["scope_binding_authorizes_lowering"] is False
        assert all(type(v) is int and v == 0 for v in node["admission_masks"].values())


@pytest.fixture(autouse=True)
def no_numerical_or_network_work(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers"}:
            raise AssertionError("numerical imports prohibited in inert binding tests")
        return original(name, *args, **kwargs)

    def denied(*args, **kwargs):
        raise AssertionError("network prohibited in inert binding tests")

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def test_empty_eight_physical_items_generate_no_review_or_scope_declaration(tmp_path):
    packet, fixture = synthetic_packet(tmp_path, count=8)
    before = subject.digest(packet)
    guide = subject.prepare_binding_slots(packet, [], **options(packet, fixture))
    result = bind(packet, [], [], fixture)
    assert len(result["items"]) == len(guide["items"]) == 8
    assert result["status"] == "pending" and result["declaration_count"] == result["sidecar_count"] == 0
    assert all(r["submission_slots"] == [] and r["unsubmitted_binding_slot"]["scope_declaration"] is None for r in guide["items"])
    assert all(r["reviewed_declarations"] == [] for r in result["items"])
    assert len({r["physical_identity_sha256"] for r in result["items"]}) == 8
    assert subject.digest(packet) == before
    assert_zero(result)
    assert_zero(guide)


def test_join_is_lossless_replayable_and_never_legal_gold(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture, binder=True)
    snapshot = deepcopy((packet, value, supplied))
    result = bind(packet, [value], [supplied], fixture)
    row = first(result)
    assert row["binding_status"] == "joined_declared_scope_only"
    assert row["review_declaration"]["status"] == "consistent_declared_normative"
    assert row["scope_graph_validation_performed"] and row["scope_bridge_transport_validated"]
    assert row["scope_bridge_view"]["payload"] == supplied["scope_declaration"]
    assert row["sidecar"] == supplied and row["declaration_join"]["binder_count"] == 1
    assert row["scope_validation"]["binder_terms_typechecked"] is False
    assert row["declaration_join"]["review_trigger_anchors_preserved"] == value["items"][0]["review"]["trigger"]
    assert row["declaration_join"]["review_trigger_rule_linkage"].startswith("not_assessed")
    assert result["gold_labels_created"] == result["formal_targets_created"] == result["human_reviews_authenticated"] == 0
    assert (packet, value, supplied) == snapshot
    checked = subject.validate_binding(result, packet, [value], [supplied], **options(packet, fixture))
    assert checked["binding_sha256"] == subject.digest(result)
    assert_zero(result)
    assert_zero(checked)


def test_missing_sidecar_retains_complete_original_declaration(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    row = first(bind(packet, [value], [], fixture))
    assert row["binding_status"] == "pending_scope_declaration" and row["sidecar"] is None
    assert row["review_declaration"]["declaration"] == value["items"][0]
    assert row["scope_validation"] is row["scope_bridge_view"] is None


@pytest.mark.parametrize("missing", ["scope_declaration", *subject.MAP_FIELDS])
def test_partially_answered_sidecar_remains_unassessed(tmp_path, missing):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    supplied[missing] = None
    row = first(bind(packet, [value], [supplied], fixture))
    assert row["binding_status"] == "partial_binding" and row["sidecar"][missing] is None
    assert row["scope_validation"] is None and row["scope_bridge_view"] is None


def test_recorded_partial_review_stays_partial_after_valid_scope_join(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    value["items"][0]["review"]["notes"] = None
    supplied = sidecar(packet, value, fixture)
    result = bind(packet, [value], [supplied], fixture)
    assert first(result)["review_declaration"]["status"] == "partial"
    assert first(result)["binding_status"] == "joined_declared_scope_only"
    assert_zero(result)


@pytest.mark.parametrize("status", ["inconsistent", "unresolved"])
def test_review_diagnostics_are_not_promoted_by_scope_transport(tmp_path, status):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    if status == "inconsistent":
        value["items"][0]["review"]["normative_eligibility"] = "not_normative"
    else:
        value["items"][0]["context_review"]["unresolved_dependencies"] = ["Synthetic unresolved dependency"]
    supplied = sidecar(packet, value, fixture)
    result = bind(packet, [value], [supplied], fixture)
    assert first(result)["review_declaration"]["status"] == status
    assert first(result)["binding_status"] == "joined_declared_scope_only"
    assert_zero(result)


def test_disputed_reviews_both_remain_visible_with_independent_sidecars(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    a = submission(packet, fixture)
    b = submission(packet, fixture, reviewer="synthetic-reviewer-b", identity="synthetic-submission-b")
    b["items"][0]["review"]["notes"] = "Distinct synthetic interpretation declaration."
    b["items"][0]["review"]["normative_eligibility"] = "not_normative"
    sa, sb = sidecar(packet, a, fixture), sidecar(packet, b, fixture)
    result = bind(packet, [b, a], [sa, sb], fixture)
    assert result["declared_disputed_item_count"] == 1 and result["items"][0]["recording_status"] == "disputed"
    assert [r["review_declaration"]["submission_id"] for r in result["items"][0]["reviewed_declarations"]] == [b["submission_id"], a["submission_id"]]
    assert [r["binding_index"] for r in result["items"][0]["reviewed_declarations"]] == [1, 0]
    assert result["scope_sidecars"] == [sa, sb]
    assert_zero(result)


def test_shared_qualifiers_retain_rule_and_occurrence_multiplicity(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture, rule_count=2, shared=True)
    supplied = sidecar(packet, value, fixture, shared=True)
    row = first(bind(packet, [value], [supplied], fixture))
    assert row["binding_status"] == "joined_declared_scope_only"
    assert row["declaration_join"]["ordered_rule_count"] == 2
    assert row["declaration_join"]["qualifier_index_count"] == 12
    assert row["declaration_join"]["scope_leaf_site_count"] == 9
    assert row["sidecar"]["scope_declaration"]["statement_structure"]["op"] == "attach"
    assert row["sidecar"]["scope_declaration"]["rules"][0]["qualifiers"]["conditions"] is None


def test_context_occurrences_translate_exact_unicode_offsets(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture, context_anchors=True, binder=True)
    row = first(bind(packet, [value], [supplied], fixture))
    assert row["binding_status"] == "joined_declared_scope_only"
    assert all(o["anchor"]["origin"] == "context" for o in supplied["scope_declaration"]["occurrences"])
    assert row["scope_bridge_view"]["payload"]["input"]["context"]["text"].startswith("§ Ω")


@pytest.mark.parametrize("field", ["packet_sha256", "submission_sha256", "declaration_sha256", "physical_identity_sha256",
                                     "input_sha256", "source_text_sha256", "scope_input_sha256"])
def test_detached_digest_join_tampering_is_refused(tmp_path, field):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    supplied[field] = "0" * 64
    with pytest.raises(ValueError):
        bind(packet, [value], [supplied], fixture)


@pytest.mark.parametrize("field", ["submission_id", "item_id"])
def test_unknown_submission_or_physical_item_is_refused(tmp_path, field):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    supplied[field] = "unknown"
    with pytest.raises(ValueError, match="existing submission/physical item"):
        bind(packet, [value], [supplied], fixture)


def test_equal_source_text_does_not_substitute_physical_item(tmp_path):
    packet, fixture = synthetic_packet(tmp_path, count=2)
    a = submission(packet, fixture, item_index=0)
    b = submission(packet, fixture, item_index=1, identity="synthetic-submission-b")
    supplied = sidecar(packet, a, fixture)
    supplied.update(submission_id=b["submission_id"], submission_sha256=subject.digest(b),
                    declaration_sha256=subject.digest(b["items"][0]), item_id=b["items"][0]["item_id"])
    with pytest.raises(ValueError, match="physical/source/context envelope"):
        bind(packet, [a, b], [supplied], fixture)


def test_duplicate_pair_and_renamed_replay_are_refused(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    other = deepcopy(supplied)
    other["binding_id"] = "renamed-replay"
    with pytest.raises(ValueError, match="duplicate scope sidecar"):
        bind(packet, [value], [supplied, other], fixture)


def test_binding_id_collision_across_distinct_reviews_is_refused(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    a = submission(packet, fixture)
    b = submission(packet, fixture, reviewer="synthetic-reviewer-b", identity="synthetic-submission-b")
    sa, sb = sidecar(packet, a, fixture), sidecar(packet, b, fixture)
    sb["binding_id"] = sa["binding_id"]
    with pytest.raises(ValueError, match="duplicate scope binding_id"):
        bind(packet, [a, b], [sa, sb], fixture)


@pytest.mark.parametrize("field", list(subject.MAP_FIELDS))
def test_explicit_empty_map_is_not_an_unanswered_complete_map(tmp_path, field):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    supplied[field] = []
    with pytest.raises(ValueError):
        bind(packet, [value], [supplied], fixture)


@pytest.mark.parametrize("field", list(subject.MAP_FIELDS))
def test_duplicate_mapping_rows_are_refused(tmp_path, field):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    supplied[field].append(deepcopy(supplied[field][0]))
    with pytest.raises(ValueError):
        bind(packet, [value], [supplied], fixture)


def test_rule_and_anchor_mapping_order_cannot_be_normalized(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture, rule_count=2)
    supplied = sidecar(packet, value, fixture)
    supplied["rule_bindings"].reverse()
    with pytest.raises(ValueError, match="ordered exhaustive rule"):
        bind(packet, [value], [supplied], fixture)
    supplied = sidecar(packet, value, fixture)
    supplied["anchor_bindings"].reverse()
    with pytest.raises(ValueError, match="ordered exhaustive original anchor"):
        bind(packet, [value], [supplied], fixture)


def test_repeated_same_symbol_leaf_occurrences_cannot_swap_positions(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    a, b = supplied["qualifier_bindings"][0], supplied["qualifier_bindings"][2]
    a["scope_leaf_path"], b["scope_leaf_path"] = b["scope_leaf_path"], a["scope_leaf_path"]
    with pytest.raises(ValueError, match="leaf occurrence order"):
        bind(packet, [value], [supplied], fixture)


def test_shared_attachment_cannot_be_silently_made_local(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture, rule_count=2, shared=True)
    supplied = sidecar(packet, value, fixture, shared=True)
    supplied["attachment_bindings"][0]["scope_path"] = "/rules/0/qualifiers/exceptions"
    with pytest.raises(ValueError, match="path/facet"):
        bind(packet, [value], [supplied], fixture)


def test_attachment_cannot_drop_an_affected_rule(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture, rule_count=2, shared=True)
    value["items"][0]["review"]["qualifier_attachments"][0].update(scope_kind="rule", affected_rule_indices=[0])
    supplied = sidecar(packet, value, fixture, shared=True)
    with pytest.raises(ValueError, match="affected rules differ"):
        bind(packet, [value], [supplied], fixture)


def test_qualifier_map_cannot_escape_rule_attachment(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture, rule_count=2)
    supplied = sidecar(packet, value, fixture)
    supplied["qualifier_bindings"][0]["scope_leaf_path"] = "/rules/1/qualifiers/conditions/children/0"
    with pytest.raises(ValueError, match="escapes"):
        bind(packet, [value], [supplied], fixture)


def test_source_versus_context_occurrence_shift_cannot_be_omitted(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture, context_anchors=True)
    occurrence = next(o for o in supplied["scope_declaration"]["occurrences"] if o["occurrence_id"] == "r0-actor")
    shift = packet["items"][0]["context"]["selected_char_start"]
    occurrence["anchor"]["start"] -= shift
    occurrence["anchor"]["end"] -= shift
    occurrence["anchor"]["text"] = supplied["scope_declaration"]["input"]["context"]["text"][occurrence["anchor"]["start"]:occurrence["anchor"]["end"]]
    seal_scope(supplied["scope_declaration"])
    with pytest.raises(ValueError, match="exact source/context occurrence"):
        bind(packet, [value], [supplied], fixture)


def test_symbol_alias_is_explicit_and_not_inferred_from_literal(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    value["items"][0]["review"]["normative_rules"][0]["actor"] = "clericalActor"
    supplied = sidecar(packet, value, fixture)
    row = first(bind(packet, [value], [supplied], fixture))
    assert row["binding_status"] == "joined_declared_scope_only"
    assert next(o for o in supplied["scope_declaration"]["occurrences"] if o["facet"] == "actor")["anchor"]["text"] == "The clerk"
    assert row["symbolic_aliases_inferred"] is False


def test_scope_core_symbol_cannot_change_recorded_alias(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    next(o for o in supplied["scope_declaration"]["occurrences"] if o["facet"] == "actor")["canonical_symbol"] = "otherActor"
    seal_scope(supplied["scope_declaration"])
    with pytest.raises(ValueError, match="core symbol"):
        bind(packet, [value], [supplied], fixture)


@pytest.mark.parametrize("kind", ["bound_outside_scope", "shared_leaf_used_outside_scope", "wrong_domain_facet"])
def test_existing_binder_escape_and_type_checks_are_reused(tmp_path, kind):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture, rule_count=2)
    supplied = sidecar(packet, value, fixture, binder=True)
    binder = supplied["scope_declaration"]["binders"][0]
    if kind == "bound_outside_scope":
        binder["bound_occurrence_ids"] = ["r1-actor"]
    elif kind == "shared_leaf_used_outside_scope":
        declaration = supplied["scope_declaration"]
        declaration["rules"][1]["qualifiers"]["conditions"]["children"][0]["occurrence_id"] = "r0-conditions-0"
        declaration["occurrences"] = [o for o in declaration["occurrences"] if o["occurrence_id"] != "r1-conditions-0"]
        next(a for a in supplied["anchor_bindings"] if a["anchor_id"] == "r1-conditions-0")["scope_occurrence_id"] = "r0-conditions-0"
        binder["bound_occurrence_ids"] = ["r0-conditions-0"]
    else:
        binder["domain_occurrence"] = "r0-actor"
    seal_scope(supplied["scope_declaration"])
    with pytest.raises(ValueError):
        bind(packet, [value], [supplied], fixture)


def test_declared_complete_literal_coverage_cannot_omit_full_context(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    supplied["scope_declaration"]["coverage"]["declared_status"] = "complete"
    seal_scope(supplied["scope_declaration"])
    with pytest.raises(ValueError, match="coverage omits"):
        bind(packet, [value], [supplied], fixture)


@pytest.mark.parametrize("replacement", ["none_required", "required_unavailable", "shortened_context"])
def test_complete_context_cannot_be_erased_or_replaced(tmp_path, replacement):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    context = supplied["scope_declaration"]["input"]["context"]
    context.update(role="declared_context" if replacement == "shortened_context" else replacement,
                   text=TEXT if replacement == "shortened_context" else "")
    context["sha256"] = sha(context["text"].encode())
    supplied["scope_declaration"]["input_sha256"] = subject.digest(supplied["scope_declaration"]["input"])
    seal_scope(supplied["scope_declaration"])
    with pytest.raises(ValueError, match="complete source/context"):
        bind(packet, [value], [supplied], fixture)


@pytest.mark.parametrize("context_length", [16384, 16385, 21347, 28500, 71688])
def test_exact_full_context_limit_preserves_physical_items(tmp_path, context_length):
    suffix = "\nSynthetic fixture notes; no legal authority."
    packet, fixture = synthetic_packet(tmp_path, prefix="Ω" * (context_length - len(TEXT) - len(suffix)))
    value = submission(packet, fixture)
    guide = subject.prepare_binding_slots(packet, [value], **options(packet, fixture))
    result = bind(packet, [value], [], fixture)
    assert guide["items"][0]["complete_context_characters"] == context_length
    assert result["items"][0]["complete_context_characters"] == context_length
    if context_length > 16384:
        assert guide["items"][0]["scope_request"] is None
        assert first(result)["binding_status"] == "profile_limit"
        assert "complete_raw_context_character_limit" in first(result)["profile_limits"]
    else:
        assert guide["items"][0]["scope_request"]["context"]["text"] == packet["context_views"][0]["text"]
        assert first(result)["binding_status"] == "pending_scope_declaration"
    assert first(result)["review_declaration"]["declaration"] == value["items"][0]
    assert_zero(result)


def test_oversized_recorded_rule_inventory_is_retained_without_truncation(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture, rule_count=33, qualifiers=False)
    result = bind(packet, [value], [], fixture)
    row = first(result)
    assert row["binding_status"] == "profile_limit"
    assert row["profile_limits"] == ["recorded_rule_count_exceeds_scope_profile"]
    assert len(row["review_declaration"]["declaration"]["review"]["normative_rules"]) == 33


@pytest.mark.parametrize("owner", ["recording", "preflight"])
def test_supplied_upstream_receipts_are_replayed_before_use(tmp_path, owner):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    recording = recorder.record_reviews(packet, [value], **options(packet, fixture))
    pf = preflight.preflight_declarations(packet, [value], recording=recording, **options(packet, fixture))
    good = bind(packet, [value], [], fixture, recording=recording, preflight=pf)
    assert good["recording_sha256"] == subject.digest(recording)
    bad = deepcopy(recording if owner == "recording" else pf)
    bad["admitted"] = True
    with pytest.raises(ValueError):
        bind(packet, [value], [], fixture, **{owner: bad})


@pytest.mark.parametrize("mutation", ["authority", "status", "view", "sidecar", "body_seal"])
def test_resealed_output_tampering_is_refused_by_exact_replay(tmp_path, mutation):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    result = bind(packet, [value], [supplied], fixture)
    if mutation == "authority":
        result["admitted"] = True
    elif mutation == "status":
        first(result)["binding_status"] = "pending_scope_declaration"
    elif mutation == "view":
        first(result)["scope_bridge_view"]["payload"]["binders"] = [{"invented": True}]
    elif mutation == "sidecar":
        result["scope_sidecars"][0]["binding_id"] = "changed"
    else:
        result["content_sha256"] = "0" * 64
    if mutation != "body_seal":
        result["content_sha256"] = subject.digest({k: v for k, v in result.items() if k != "content_sha256"})
    with pytest.raises(ValueError, match="authoritative replay"):
        subject.validate_binding(result, packet, [value], [supplied], **options(packet, fixture))


@pytest.mark.parametrize("mutation", ["sidecar_extra", "map_extra", "scope_extra", "bad_seal", "bad_profile", "bool_index"])
def test_closed_sidecar_and_map_schemas_are_fail_closed(tmp_path, mutation):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    if mutation == "sidecar_extra":
        supplied["admitted"] = True
    elif mutation == "map_extra":
        supplied["rule_bindings"][0]["admitted"] = False
    elif mutation == "scope_extra":
        supplied["scope_declaration"]["legal_truth"] = True
    elif mutation == "bad_seal":
        supplied["scope_declaration"]["content_sha256"] = "0" * 64
    elif mutation == "bad_profile":
        supplied["scope_declaration"]["profile"] = "ground-null-context/v1"
    else:
        supplied["rule_bindings"][0]["rule_index"] = True
    with pytest.raises(ValueError):
        bind(packet, [value], [supplied], fixture)


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1.25}', b'\xff', b'null trailing'])
def test_strict_transport_rejects_ambiguous_or_scored_JSON(raw):
    with pytest.raises(ValueError):
        subject.parse_json_bytes(raw)


def test_output_snapshots_are_detached_from_caller_inputs(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    result = bind(packet, [value], [supplied], fixture)
    before = subject.digest(result)
    supplied["scope_declaration"]["occurrences"].clear()
    value["items"][0]["review"]["normative_rules"].clear()
    packet["items"][0]["review"]["notes"] = "Changed caller object."
    assert subject.digest(result) == before


def test_context_artifact_body_drift_is_refused(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    path = fixture["paths"][packet["items"][0]["context"]["artifact"]["sha256"]]
    body = path.read_bytes()
    path.write_bytes(b"!" + body[1:])
    with pytest.raises(ValueError, match="bytes/SHA256"):
        bind(packet, [value], [supplied], fixture)


def pad_scope_to(declaration, byte_count):
    """Add explicit synthetic coverage reasons, keeping ordinary graph fields."""
    source = declaration["input"]["source_text"]
    while len(packets._wire(declaration)) < byte_count:
        row = {"span": {"origin": "source", "start": 0, "end": len(source), "text": source,
                        "offset_unit": "unicode_character_half_open"},
               "disposition": "represented", "rule_ids": ["scope-rule-0"], "occurrence_ids": [], "reason": "a"}
        declaration["coverage"]["segments"].append(row)
        difference = byte_count - len(packets._wire(declaration))
        if difference < 0:
            declaration["coverage"]["segments"].pop()
            declaration["coverage"]["segments"][-1]["reason"] += "a" * (byte_count - len(packets._wire(declaration)))
            break
        row["reason"] += "a" * min(difference, 3499)
    seal_scope(declaration)
    assert len(packets._wire(declaration)) == byte_count


@pytest.mark.parametrize("byte_count,expected_limit", [(65500, "complete_scope_bridge_view_byte_limit"),
                                                      (65537, "declaration_byte_limit")])
def test_complete_payload_and_bridge_wrapper_caps_are_separate(tmp_path, byte_count, expected_limit):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    pad_scope_to(supplied["scope_declaration"], byte_count)
    row = first(bind(packet, [value], [supplied], fixture))
    assert row["binding_status"] == "profile_limit" and row["profile_limits"] == [expected_limit]
    assert row["sidecar"] == supplied and row["scope_bridge_view"] is None
    assert row["scope_graph_validation_performed"] == (byte_count == 65500)


def test_full_literal_coverage_is_only_a_caller_declaration(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture)
    declaration = supplied["scope_declaration"]
    segments = []
    for origin, text in [("source", declaration["input"]["source_text"]), ("context", declaration["input"]["context"]["text"])]:
        segments.append({"span": {"origin": origin, "start": 0, "end": len(text), "text": text,
                                  "offset_unit": "unicode_character_half_open"},
                         "disposition": "represented", "rule_ids": ["scope-rule-0"],
                         "occurrence_ids": [o["occurrence_id"] for o in declaration["occurrences"] if o["anchor"]["origin"] == origin],
                         "reason": "Synthetic full literal coverage, not legal meaning completeness."})
    declaration["coverage"] = {"declared_status": "complete", "segments": segments}
    seal_scope(declaration)
    result = bind(packet, [value], [supplied], fixture)
    assert first(result)["scope_validation"]["declared_coverage_status"] == "complete"
    assert first(result)["scope_validation"]["source_fidelity_established"] is False
    assert_zero(result)


def test_declared_absent_object_and_qualifiers_are_preserved(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture, qualifiers=False)
    value["items"][0]["review"]["normative_rules"][0]["object"] = ""
    value["items"][0]["review"]["source_role_anchors"] = [a for a in value["items"][0]["review"]["source_role_anchors"] if a["facet"] != "object"]
    supplied = sidecar(packet, value, fixture)
    row = first(bind(packet, [value], [supplied], fixture))
    assert row["binding_status"] == "joined_declared_scope_only"
    assert row["declaration_join"]["qualifier_index_count"] == 0
    assert row["scope_bridge_view"]["payload"]["rules"][0]["body"]["object"] is None


@pytest.mark.parametrize("kind", ["statement_any", "qualifier_not"])
def test_explicit_nonflat_connectives_are_retained_without_equivalence_claim(tmp_path, kind):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture, rule_count=2 if kind == "statement_any" else 1)
    supplied = sidecar(packet, value, fixture)
    declaration = supplied["scope_declaration"]
    if kind == "statement_any":
        declaration["statement_structure"]["op"] = "any"
    else:
        children = declaration["rules"][0]["qualifiers"]["conditions"]["children"]
        children[0] = {"op": "not", "child": children[0], "operator_anchor": None}
        supplied["qualifier_bindings"][0]["scope_leaf_path"] += "/child"
    seal_scope(declaration)
    result = bind(packet, [value], [supplied], fixture)
    assert first(result)["scope_bridge_view"]["payload"] == declaration
    assert first(result)["scope_validation"]["semantic_equivalence_assessed"] is False
    assert_zero(result)


def test_binder_domain_can_use_exact_context_outside_selected_source(tmp_path):
    packet, fixture = synthetic_packet(tmp_path, prefix="Synthetic domain People. § Ω\n")
    value = submission(packet, fixture)
    supplied = sidecar(packet, value, fixture, binder=True)
    domain = next(o for o in supplied["scope_declaration"]["occurrences"] if o["facet"] == "binder_domain")
    context = supplied["scope_declaration"]["input"]["context"]["text"]
    start = context.index("People")
    domain["anchor"] = {"origin": "context", "start": start, "end": start + len("People"), "text": "People",
                        "offset_unit": "unicode_character_half_open"}
    seal_scope(supplied["scope_declaration"])
    row = first(bind(packet, [value], [supplied], fixture))
    assert row["binding_status"] == "joined_declared_scope_only"
    assert row["scope_bridge_view"]["payload"]["binders"] == supplied["scope_declaration"]["binders"]
    assert row["scope_validation"]["binder_terms_typechecked"] is False


def test_sidecar_inventory_budget_refuses_without_dropping_rows(tmp_path):
    packet, fixture = synthetic_packet(tmp_path)
    value = submission(packet, fixture)
    slot = subject.prepare_binding_slots(packet, [value], **options(packet, fixture))["items"][0]["submission_slots"][0]["slot"]
    slot["binding_id"] = "synthetic-budget"
    with pytest.raises(ValueError, match="bounded scope sidecar list"):
        bind(packet, [value], [slot] * (subject.MAX_SIDECARS + 1), fixture)


@pytest.mark.parametrize("kind", ["bytes", "depth", "nonordinary"])
def test_transport_budgets_refuse_before_assessment(kind):
    if kind == "bytes":
        with pytest.raises(ValueError, match="bounded exact JSON bytes"):
            subject.parse_json_bytes(b'"' + b'a' * subject.MAX_JSON_BYTES + b'"')
    elif kind == "depth":
        with pytest.raises(ValueError, match="bounded ordinary JSON"):
            subject.parse_json_bytes(b'[' * 30 + b'0' + b']' * 30)
    else:
        class ForeignDict(dict):
            pass

        with pytest.raises(ValueError, match="ordinary JSON"):
            subject.digest(ForeignDict(x=1))
