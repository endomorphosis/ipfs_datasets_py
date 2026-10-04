"""Synthetic scope views preserve declarations without accepting their meaning."""
from __future__ import annotations

import builtins
import copy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_byte_codec as byte_codec
from ipfs_datasets_py.logic.legal_ir import canonical_statement_scope as scope
from ipfs_datasets_py.logic.legal_ir import canonical_statement_scope_bridge as subject
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    BridgeRepresentationKind,
    BridgeSourceReference,
    BridgeUnsupportedConstruct,
    BridgeView,
    CanonicalContractError,
    CanonicalRoundTripIR,
    CanonicalTypedBridge,
    ConstructDisposition,
    DomainLogicSliceRole,
    UnsupportedDisposition,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, cid_for_dag_json


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def seal(declaration):
    declaration["content_sha256"] = digest({k: v for k, v in declaration.items() if k != "content_sha256"})
    return declaration


def fixture_scope():
    source = "Clérk e\u0301 must retain filing if paid and paid."
    request = dict(source_text=source,
        context=dict(role="none_required", text="", bindings={}, sha256=hashlib.sha256(b"").hexdigest()))

    def span(text, *, start=0):
        offset = source.index(text, start)
        return dict(origin="source", start=offset, end=offset + len(text), text=text,
                    offset_unit="unicode_character_half_open")

    occurrences = [dict(occurrence_id=identity, facet=facet, canonical_symbol=symbol, anchor=span(text))
        for identity, facet, symbol, text in (
            ("actor-1", "actor", "clerk", "Clérk"), ("modality-1", "modality", "O", "must"),
            ("action-1", "action", "retain", "retain"), ("object-1", "object", "filing", "filing"),
            ("paid-1", "conditions", "paid", "paid"))]
    occurrences.append(dict(occurrence_id="paid-2", facet="conditions", canonical_symbol="paid",
                            anchor=span("paid", start=source.index("paid") + 4)))
    declaration = dict(schema=scope.SCHEMA, family="deontic", profile=scope.PROFILE,
        input=copy.deepcopy(request), input_sha256=digest(request), occurrences=occurrences,
        rules=[dict(rule_id="rule-1", body=dict(actor="actor-1", modality="modality-1", action="action-1", object="object-1"),
            qualifiers=dict(conditions=dict(op="all", children=[dict(op="leaf", occurrence_id="paid-2"),
                dict(op="leaf", occurrence_id="paid-1")], operator_anchor=span("and")), exceptions=None, temporal=None))],
        statement_structure=dict(op="rule", rule_id="rule-1"), binders=[],
        coverage=dict(declared_status="complete", segments=[dict(
            span=dict(origin="source", start=0, end=len(source), text=source, offset_unit="unicode_character_half_open"),
            disposition="represented", rule_ids=["rule-1"], occurrence_ids=[row["occurrence_id"] for row in occurrences],
            reason="Synthetic literal coverage declaration; meaning is unreviewed.")]), unresolved=[])
    return request, seal(declaration)


def prepare(request, declaration):
    return subject.prepare_scope_bridge_view(request, declaration, expected_input_sha256=digest(request))


def validate(view, request):
    return subject.validate_scope_bridge_view(view, request, expected_input_sha256=digest(request))


def test_view_roundtrip_preserves_repeated_occurrences_order_and_exact_unicode():
    request, declaration = fixture_scope()
    view = prepare(request, declaration)
    encoded = view.to_dict()
    assert encoded["payload"] == declaration
    assert view.name == "statement_scope_v1" and view.kind is BridgeRepresentationKind.FAMILY_EXTENSION
    assert view.schema_id == scope.SCHEMA and view.family_id == "deontic"
    assert view.payload_cid == cid_for_dag_json(declaration)
    assert "e\u0301" in encoded["payload"]["input"]["source_text"]
    assert "Clérk é must" not in encoded["payload"]["input"]["source_text"]
    children = encoded["payload"]["rules"][0]["qualifiers"]["conditions"]["children"]
    assert [row["occurrence_id"] for row in children] == ["paid-2", "paid-1"]
    assert BridgeView.from_dict(json.loads(raw(encoded))).to_dict() == encoded
    receipt = validate(encoded, request)
    assert receipt["serialized_view_bytes"] == len(raw(encoded))
    assert receipt["limits_scope"] == "complete_serialized_view_including_wrapper"
    assert receipt["declaration_preserved_exactly"] is True
    assert receipt["typed_bridge_created"] is receipt["domain_logic_slice_projected"] is False
    assert receipt["verification_status"] == receipt["admission_status"] == "pending"
    assert all(receipt[field] is False for field in scope._FALSE)
    assert all(type(value) is int and value == 0 for value in receipt["masks"].values())
    assert receipt["content_sha256"] == digest({k: v for k, v in receipt.items() if k != "content_sha256"})


def test_frozen_view_and_detached_wire_cannot_mutate_original_declaration():
    request, declaration = fixture_scope()
    view = prepare(request, declaration)
    original = copy.deepcopy(declaration)
    declaration["occurrences"].reverse()
    exported = view.to_dict()
    exported["payload"]["rules"][0]["rule_id"] = "altered-export"
    assert view.to_dict()["payload"] == original
    with pytest.raises(TypeError):
        view.payload["profile"] = "changed"
    assert validate(view, request)["view_payload_cid"] == view.payload_cid


def test_occurrence_and_expression_order_remain_content_addressed():
    request, declaration = fixture_scope()
    original = prepare(request, declaration)
    changed = copy.deepcopy(declaration)
    changed["occurrences"].reverse()
    changed["rules"][0]["qualifiers"]["conditions"]["children"].reverse()
    reordered = prepare(request, seal(changed))
    assert reordered.payload_cid != original.payload_cid
    assert reordered.to_dict()["payload"] == changed
    assert validate(reordered, request)["normalization_approved"] is False


@pytest.mark.parametrize("field,value", [
    ("name", "canonical_roundtrip_ir"), ("kind", "canonical_ir"),
    ("schema_id", "ipfs-datasets.canonical-roundtrip-ir.v1"), ("family_id", "first_order"),
])
def test_foreign_view_roles_cannot_impersonate_the_scope_extension(field, value):
    request, declaration = fixture_scope()
    wire = prepare(request, declaration).to_dict()
    wire[field] = value
    with pytest.raises((ValueError, CanonicalContractError), match="differs"):
        validate(wire, request)


def test_view_payload_cid_tamper_and_unknown_fields_are_rejected():
    request, declaration = fixture_scope()
    wire = prepare(request, declaration).to_dict()
    wire["payload_cid"] = cid_for_dag_json({"different": "payload"})
    with pytest.raises(CanonicalContractError, match="payload_cid"):
        validate(wire, request)
    wire = prepare(request, declaration).to_dict()
    wire["qualified"] = True
    with pytest.raises(CanonicalContractError, match="fields"):
        validate(wire, request)


def test_serialized_view_cannot_request_cid_autofill():
    request, declaration = fixture_scope()
    view = prepare(request, declaration)
    wire = view.to_dict()
    wire["payload_cid"] = ""
    # The legacy owner repairs this wrapper; our strict transport interface
    # rejects it rather than silently accepting changed serialized content.
    assert BridgeView.from_dict(wire).to_dict() == view.to_dict()
    with pytest.raises(ValueError, match="differs after reconstruction"):
        validate(wire, request)
    assert validate(view, request)["view_payload_cid"] == view.payload_cid
    assert validate(view.to_dict(), request)["view_payload_cid"] == view.payload_cid


def test_external_input_pin_is_required_in_both_directions():
    request, declaration = fixture_scope()
    view = prepare(request, declaration)
    for call, args in ((subject.prepare_scope_bridge_view, (request, declaration)),
                       (subject.validate_scope_bridge_view, (view, request))):
        with pytest.raises(ValueError, match="externally expected"):
            call(*args, expected_input_sha256="0" * 64)
    changed = copy.deepcopy(request)
    changed["source_text"] += " Another clause."
    with pytest.raises(ValueError, match="input binding"):
        validate(view, changed)


def test_span_substitution_rejects_even_a_resealed_declaration():
    request, declaration = fixture_scope()
    declaration["occurrences"][0]["anchor"]["end"] += 1
    with pytest.raises(ValueError, match="exact source/context occurrence"):
        prepare(request, seal(declaration))


def pad_declaration(declaration, target_bytes):
    value = copy.deepcopy(declaration)
    # Duplicate literal coverage segments remain declared observations, not a
    # semantic completeness claim. Padding exercises the real carrier boundary.
    segment = copy.deepcopy(value["coverage"]["segments"][0])
    while len(raw(value)) < target_bytes:
        room = target_bytes - len(raw(value))
        if room > 4400:
            new = copy.deepcopy(segment)
            new["reason"] = "x" * 4096
            value["coverage"]["segments"].append(new)
        else:
            current = value["coverage"]["segments"][-1]["reason"]
            add = min(room, 4096 - len(current))
            if add == 0:
                new = copy.deepcopy(segment)
                new["reason"] = "x"
                value["coverage"]["segments"].append(new)
            else:
                value["coverage"]["segments"][-1]["reason"] += "x" * add
    return seal(value)


def test_payload_that_fits_legacy_payload_cap_can_exceed_complete_view_cap():
    request, declaration = fixture_scope()
    padded = pad_declaration(declaration, 65500)
    assert 65000 < len(raw(padded)) <= scope.MAX_BYTES
    scope.validate_scope_declaration(request, padded, expected_input_sha256=digest(request))
    with pytest.raises(ValueError, match="byte bound|byte limit"):
        prepare(request, padded)
    view = BridgeView(name=subject.VIEW_NAME, kind=BridgeRepresentationKind.FAMILY_EXTENSION,
                      schema_id=scope.SCHEMA, family_id="deontic", payload=padded)
    assert len(raw(view.to_dict())) > 65536
    with pytest.raises(ValueError, match="byte bound|byte limit"):
        validate(view, request)


def test_near_limit_valid_view_reports_actual_wrapper_cost_without_truncation():
    request, declaration = fixture_scope()
    padded = pad_declaration(declaration, 64000)
    view = prepare(request, padded)
    receipt = validate(view, request)
    assert len(raw(padded)) < receipt["serialized_view_bytes"] <= 65536
    assert receipt["truncation_performed"] is False
    assert view.to_dict()["payload"] == padded


def test_wrapper_depth_is_part_of_the_same_twenty_level_limit():
    request, declaration = fixture_scope()
    def leaf():
        return dict(op="leaf", occurrence_id="paid-1")

    found = None
    for attachments in range(1, 7):
        for qualifier_depth in range(7):
            candidate = copy.deepcopy(declaration)
            candidate["rules"][0]["qualifiers"]["conditions"] = dict(op="leaf", occurrence_id="paid-2")
            expression = leaf()
            for _ in range(qualifier_depth):
                expression = dict(op="all", children=[expression], operator_anchor=None)
            if qualifier_depth < 6:
                expression = dict(op="not", child=expression, operator_anchor=None)
            statement = dict(op="rule", rule_id="rule-1")
            for _ in range(attachments):
                statement = dict(op="attach", body=statement,
                    qualifiers=dict(conditions=expression, exceptions=None, temporal=None))
            candidate["statement_structure"] = statement
            seal(candidate)
            try:
                scope.validate_scope_declaration(request, candidate, expected_input_sha256=digest(request))
            except ValueError:
                continue
            try:
                scope._raw({"payload": candidate})
            except ValueError as error:
                if "depth" in str(error):
                    found = candidate
                    break
        if found is not None:
            break
    assert found is not None, "fixture must distinguish payload depth from carrier depth"
    with pytest.raises(ValueError, match="depth"):
        prepare(request, found)


def test_typed_bridge_roundtrip_keeps_scope_extension_and_slice_explicitly_unsupported():
    request, declaration = fixture_scope()
    view = prepare(request, declaration)
    unsupported = BridgeUnsupportedConstruct(construct_id="domain_logic_slice", code="scope_projection_unavailable",
        message="Synthetic scope carrier has no admitted domain projection.", disposition=UnsupportedDisposition.ABSTAIN,
        family_id="deontic")
    role = DomainLogicSliceRole(disposition=ConstructDisposition.UNSUPPORTED, family_id="deontic", unsupported=unsupported)
    bridge = CanonicalTypedBridge.compose(family_id="deontic", authority_schema=scope.SCHEMA, views=[view],
        source_references=[BridgeSourceReference(ref_id="synthetic-source", source_cid=cid_for_bytes(request["source_text"].encode()))],
        domain_logic_slice=role, adapter_name="synthetic-scope-carrier-test",
        provenance={"synthetic": True, "source_fidelity_established": False})
    replay = CanonicalTypedBridge.from_dict(json.loads(raw(bridge.to_dict())))
    assert replay.to_dict() == bridge.to_dict()
    assert replay.views[subject.VIEW_NAME].to_dict()["payload"] == declaration
    assert replay.construct_dispositions["family_extensions"] is ConstructDisposition.REPRESENTED
    assert replay.construct_dispositions["canonical_ir"] is ConstructDisposition.UNSUPPORTED
    assert replay.domain_logic_slice.disposition is ConstructDisposition.UNSUPPORTED
    assert replay.assumptions == () and replay.domain_logic_slice.projected_payload_cid is None


def test_unchanged_legacy_ir_sorts_deduplicates_qualifiers_but_retains_duplicate_rules():
    request, declaration = fixture_scope()
    view = prepare(request, declaration)
    rule = dict(modality="O", actor="clerk", action="retain", object="filing",
                conditions=["z", "paid", "paid"], exceptions=[], temporal=[])
    legacy = CanonicalRoundTripIR.from_dict({"rules": [rule, copy.deepcopy(rule)]}).to_dict()
    assert len(legacy["rules"]) == 2
    assert legacy["rules"][0]["conditions"] == ["paid", "z"]
    assert view.to_dict()["payload"] == declaration


def test_unchanged_byte_codec_refuses_duplicate_qualifiers_and_multiple_rules():
    request, declaration = fixture_scope()
    rule = dict(modality="O", actor="clerk", action="retain", object="filing",
                conditions=["paid", "paid"], exceptions=[], temporal=[])
    proposal = dict(schema=byte_codec.PROPOSAL_SCHEMA,
        source_sha256=hashlib.sha256(request["source_text"].encode()).hexdigest(),
        canonical_ir={"rules": [rule]}, anchors=[], facet_operators=dict(scope.OPERATORS), single_rule_scope=True,
        **byte_codec._FALSE)
    with pytest.raises(ValueError, match="sorted and unique"):
        byte_codec.validate_proposal(proposal, request["source_text"])
    proposal["canonical_ir"]["rules"] = [rule, copy.deepcopy(rule)]
    with pytest.raises(ValueError, match="exactly one"):
        byte_codec.validate_proposal(proposal, request["source_text"])
    assert prepare(request, declaration).to_dict()["payload"] == declaration


def test_scope_carrier_uses_no_model_parser_or_prover_dependency(monkeypatch):
    request, declaration = fixture_scope()
    original = builtins.__import__
    forbidden = ("torch", "transformers", "spacy", "tensorflow", "ipfs_datasets_py.logic.backends",
                 "ipfs_datasets_py.logic.TDFOL", "ipfs_accelerate_py")

    def guard(name, *args, **kwargs):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
            pytest.fail("unexpected runtime import: " + name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    receipt = validate(prepare(request, declaration), request)
    assert receipt["model_calls"] == receipt["prover_calls"] == 0
