"""Synthetic saved-report parser-view integrity, with no model or compiler calls.

The unchanged sibling test module owns the synthetic saved-report/schema
fixtures. Loading its helper definitions does not run its tests or subprocesses.
Assertions below concern parser structure and declared artifact consistency,
never correct legal interpretation or authenticated model execution.
"""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.legal_ir import saved_span_native_views as views


@pytest.fixture(scope="module")
def synthetic():
    path = Path(__file__).with_name("test_saved_span_family_adapter.py")
    spec = importlib.util.spec_from_file_location("_native_views_saved_report_fixture_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declared(synthetic, modality="O", *, kind="plain", capture=False, lane="raw"):
    actor, action, obj = "The agency", "retain", "records"
    cue_literal = {"O": "shall", "P": "may", "F": "shall not"}[modality]
    text = f"{actor} {cue_literal} {action} {obj}"
    if kind in ("condition", "both"):
        text += " if licensed"
    if kind in ("exception", "both"):
        text += " unless exempt"
    text += "."
    spans = {"actor": (0, len(actor)),
             "action": (text.index(action), text.index(action) + len(action)),
             "object": (text.index(obj), text.index(obj) + len(obj))}
    for field, literal in (("conditions", "licensed"), ("exceptions", "exempt")):
        if literal in text:
            spans[field] = (text.index(literal), text.index(literal) + len(literal))
    cue = (len(actor) + 1, len(actor) + 1 + len(cue_literal))
    source, report, _ = synthetic.case(modality, text=text, spans=spans, cue=cue,
                                      capture=capture or lane == "joint")
    saved_joint = synthetic.joint_report(source, report) if lane == "joint" else None
    packet = synthetic.pending(source, report, saved_joint)
    declaration = synthetic.declaration(packet, cue)
    for field in ("conditions", "exceptions"):
        for row in declaration["interpretation"]["rules"][0][field]:
            row["expression"] = {"op": "atom", "predicate": {
                "name": "caller_" + row["literal"], "arguments": [actor]}}
    return packet, declaration


def _prepare(packet, declaration, profile="tdfol"):
    return views.prepare_native_view(packet, declaration,
        expected_packet_sha256=views.digest(packet), native_parser_profile=profile)


def _validate(output, packet, declaration, profile="tdfol"):
    return views.validate_native_view(output, packet, declaration,
        expected_packet_sha256=views.digest(packet), native_parser_profile=profile)


def _reseal(output):
    output["output_sha256"] = views.digest({key: value for key, value in output.items()
                                           if key != "output_sha256"})


@pytest.mark.parametrize("modality", ["O", "P", "F"])
@pytest.mark.parametrize("kind", ["plain", "condition", "exception"])
def test_tdfol_ground_views_preserve_original_deontic_output_and_declared_qualifiers(synthetic, modality, kind):
    packet, declaration = _declared(synthetic, modality, kind=kind)
    before = deepcopy((packet, declaration))
    output = _prepare(packet, declaration)
    original = synthetic.adapter.prepare_family(packet, declaration,
        expected_packet_sha256=views.digest(packet), family="deontic")
    assert output["original_deontic_output"] == original
    assert output["request"] == original["request"]
    assert output["original_deontic_output_sha256"] == synthetic.adapter.digest(original)
    assert output["native_parser_profile"] == "tdfol"
    assert output["sealed_legal_family"] == output["sealed_route"]["family_id"] == "deontic"
    assert output["native_view"]["logic_family"] == "tdfol"
    assert "not registered legal-family qualification" in output["native_report_family_metadata_scope"]
    assert output["native_view"]["canonical_roundtrip"] == packet["candidate"]["canonical_ir"]
    node = output["native_view"]["formulas"][0]["native_ast"]
    norm = node if kind == "plain" else node["right"]
    assert norm["node_type"] == "DeonticFormula" and norm["operator"]["value"] == modality
    assert norm["agent"] is None and norm["context"] is None
    if kind != "plain":
        assert node["node_type"] == "BinaryFormula" and node["operator"]["value"] == "→"
    if kind == "exception":
        assert node["left"]["operator"]["value"] == "¬"
    assert output["native_view"]["formulas"][0]["native_receipt"]["exact_native_ast_roundtrip"] is True
    assert output["native_view"]["interpretation"] == original["request"]["interpretation"]
    assert output["native_view"]["occurrence_bindings"] == original["request"]["occurrence_bindings"]
    assert all(output[key] is False for key in views.FALSE)
    assert _validate(output, packet, declaration)
    assert (packet, declaration) == before


@pytest.mark.parametrize("modality", ["O", "P", "F"])
def test_dcec_ground_views_use_independent_native_constants_and_canonical_inverse(synthetic, modality):
    packet, declaration = _declared(synthetic, modality)
    output = _prepare(packet, declaration, "dcec")
    node = output["native_view"]["formulas"][0]["native_ast"]
    original = output["original_deontic_output"]["native_bridge"]["formulas"][0]["native_ast"]
    assert node["operator"]["value"] == original["operator"]["value"] == modality
    assert node["formula"]["node_type"] == "AtomicFormula"
    assert original["formula"]["node_type"] == "Predicate"
    assert node["formula"]["arguments"][0]["node_type"] == "FunctionTerm"
    assert node["formula"]["arguments"][0]["arguments"] == []
    assert original["formula"]["arguments"][0]["node_type"] == "Constant"
    assert node != original
    assert output["native_view"]["canonical_roundtrip"] == output["canonical_ir"]
    assert output["original_deontic_output"]["native_bridge"]["canonical_roundtrip"] == output["canonical_ir"]
    assert output["registry_family_qualified"] is False
    assert output["cross_family_equivalence_verified"] is False
    assert _validate(output, packet, declaration, "dcec")


@pytest.mark.parametrize("modality", ["O", "P", "F"])
@pytest.mark.parametrize("kind", ["condition", "exception", "both"])
def test_dcec_qualifier_refusal_does_not_erase_a_qualifier(synthetic, modality, kind):
    packet, declaration = _declared(synthetic, modality, kind=kind)
    before = deepcopy((packet, declaration))
    with pytest.raises(ValueError, match="qualifier-free"):
        _prepare(packet, declaration, "dcec")
    assert (packet, declaration) == before
    assert _prepare(packet, declaration, "tdfol")["canonical_ir"] == packet["candidate"]["canonical_ir"]


@pytest.mark.parametrize("profile", ["tdfol", "dcec"])
@pytest.mark.parametrize("modality", ["O", "P", "F"])
def test_same_forward_joint_lane_preserves_complete_reports_and_original_bindings(synthetic, profile, modality):
    packet, declaration = _declared(synthetic, modality, lane="joint")
    before = deepcopy(packet)
    output = _prepare(packet, declaration, profile)
    assert packet["binding"]["lane"] == output["binding"]["lane"] == "joint"
    assert packet["saved_head_replay_performed"] is True
    assert output["binding"] == output["original_deontic_output"]["binding"] == packet["binding"]
    assert output["full_original_packet_required_for_replay"] is True
    assert output["packet_sha256"] == views.digest(packet)
    assert output["raw_output_repaired"] is False
    assert output["model_authenticated"] is False and output["checkpoint_authenticated"] is False
    assert _validate(output, packet, declaration, profile)
    assert packet == before


@pytest.mark.parametrize("profile", ["tdfol", "dcec"])
def test_joint_view_retains_refused_raw_parent_without_repair(synthetic, profile):
    source, report, cue = synthetic.case(capture=True)
    scores = report["rows"][0]["scores"]
    scores["start_logits"]["object"] = [10.0, -8.0, -8.0, -8.0, 9.0, -8.0]
    scores["end_logits"]["object"] = [-8.0, 10.0, -8.0, -8.0, 9.0, -8.0]
    greedy = synthetic.joint._greedy(source["source_text"], scores,
        {field: synthetic.joint._rank_spans(scores, field) for field in synthetic.joint.FIELDS})
    report["rows"][0]["decoder_row"] = synthetic.raw_row(source["source_text"], scores, greedy)
    assert greedy["reason"] == "copied_spans_overlap"
    packet = synthetic.pending(source, report, synthetic.joint_report(source, report))
    declaration = synthetic.declaration(packet, cue)
    output = _prepare(packet, declaration, profile)
    assert packet["raw_report"]["rows"][0]["decoder_row"]["canonical_ir"] is None
    assert output["binding"]["lane"] == "joint" and not output["raw_output_repaired"]
    assert _validate(output, packet, declaration, profile)


def test_full_96_row_raw_snapshot_is_required_for_replay_without_selective_transport(synthetic):
    source, report, cue = synthetic.case()
    first = deepcopy(report["rows"][0])
    report["rows"] = []
    for position in range(96):
        row = deepcopy(first)
        identity = "synthetic-native-view-" + str(position)
        row.update(id=identity, position=position, latent_donor_id=identity, latent_donor_position=position)
        report["rows"].append(row)
    report["actual_source_forwards"] = 96
    source["id"] = report["rows"][-1]["id"]
    packet = synthetic.pending(source, report)
    declaration = synthetic.declaration(packet, cue)
    output = _prepare(packet, declaration)
    assert len(packet["raw_report"]["rows"]) == 96
    assert output["binding"]["position"] == 95
    assert output["packet_sha256"] == views.digest(packet)
    assert _validate(output, packet, declaration)
    changed = deepcopy(packet)
    changed["raw_report"]["rows"][0]["decoder_row"]["target_access"] = True
    changed["binding"]["raw_report_content_sha256"] = synthetic.adapter.digest(changed["raw_report"])
    altered_declaration = deepcopy(declaration)
    altered_declaration["packet_sha256"] = views.digest(changed)
    with pytest.raises(ValueError):
        _prepare(changed, altered_declaration)
    assert len(packet["raw_report"]["rows"]) == 96


@pytest.mark.parametrize("profile", ["tdfol", "dcec"])
def test_unicode_and_repeated_argument_occurrences_retain_exact_offsets(synthetic, profile):
    text = "Café bureau shall notify Café bureau."
    source, report, cue = synthetic.case(text=text,
        spans={"actor": (0, 11), "action": (18, 24), "object": (25, 36)}, cue=(12, 17))
    source["physical_occurrence"] = {"occurrence_id": "declared-cafe-occurrence",
        "context_identity": {"document_id": "declared-development-document", "artifact_sha256": "d" * 64,
            "selected_char_start": 7, "selected_char_end": 7 + len(text),
            "selected_utf8_byte_start": 9, "selected_utf8_byte_end": 9 + len(text.encode("utf-8"))}}
    packet = synthetic.pending(source, report)
    declaration = synthetic.declaration(packet, cue)
    output = _prepare(packet, declaration, profile)
    facets = output["request"]["occurrence_bindings"][0]["facets"]
    assert facets["actor"]["source_text"] == facets["object"]["source_text"] == "Café bureau"
    assert facets["actor"]["start_char"] == 0 and facets["object"]["start_char"] == 25
    assert output["original_deontic_output"]["modality_anchor_utf8_bytes"] == [13, 18]
    assert output["physical_context_status"] == "caller_declared_not_authenticated"
    assert output["source_context_custody_verified"] is False
    assert _validate(output, packet, declaration, profile)
    moved = deepcopy(declaration)
    moved["occurrence"].update(start_char=12, source_text=text[12:])
    with pytest.raises(ValueError):
        _prepare(packet, moved, profile)


def test_nested_boolean_qualifier_expression_retains_exact_scope_in_tdfol(synthetic):
    packet, declaration = _declared(synthetic, kind="both")
    row = declaration["interpretation"]["rules"][0]["conditions"][0]
    atom = deepcopy(row["expression"])
    row["expression"] = {"op": "any", "operands": [atom, {"op": "not", "operand": deepcopy(atom)}]}
    output = _prepare(packet, declaration)
    node = output["native_view"]["formulas"][0]["native_ast"]
    assert node["operator"]["value"] == "→" and node["right"]["node_type"] == "DeonticFormula"
    assert node["left"]["operator"]["value"] == "∧"
    assert node["left"]["left"]["operator"]["value"] == "∨"
    assert node["left"]["left"]["right"]["operator"]["value"] == "¬"
    assert node["left"]["right"]["operator"]["value"] == "¬"
    assert output["native_view"]["interpretation"] == declaration["interpretation"]
    assert _validate(output, packet, declaration)


def test_supplied_boolean_operand_order_is_preserved_and_cannot_be_resealed_away(synthetic):
    packet, declaration = _declared(synthetic, kind="condition")
    row = declaration["interpretation"]["rules"][0]["conditions"][0]
    row["expression"] = {"op": "any", "operands": [
        {"op": "atom", "predicate": {"name": "caller_first", "arguments": ["The agency"]}},
        {"op": "atom", "predicate": {"name": "caller_second", "arguments": ["The agency"]}}]}
    output = _prepare(packet, declaration)
    assert output["request"]["interpretation"] == declaration["interpretation"]
    assert output["native_view"]["interpretation"] == declaration["interpretation"]
    assert _validate(output, packet, declaration)
    output["native_view"]["interpretation"]["rules"][0]["conditions"][0]["expression"]["operands"].reverse()
    report = output["native_view"]
    report["report_sha256"] = views.digest({key: value for key, value in report.items()
                                           if key != "report_sha256"})
    output["native_view_sha256"] = views.digest(report)
    _reseal(output)
    with pytest.raises(ValueError):
        _validate(output, packet, declaration)


@pytest.mark.parametrize("profile", ["tdfol", "dcec"])
def test_unary_native_view_retains_absent_object_and_does_not_infer_cue_meaning(synthetic, profile):
    source, report, cue = synthetic.case(text="The agency shall retain.",
        spans={"actor": (0, 10), "action": (17, 23)})
    packet = synthetic.pending(source, report)
    declaration = synthetic.declaration(packet, cue)
    # This deliberately meaningless declaration checks byte binding alone.
    # The original owner permits it without claiming legal interpretation.
    declaration["occurrence"]["modality_anchor"].update(start_char=23, end_char=24, source_text=".")
    output = _prepare(packet, declaration, profile)
    node = output["native_view"]["formulas"][0]["native_ast"]
    assert len(node["formula"]["arguments"]) == 1
    assert output["request"]["occurrence_bindings"][0]["facets"]["object"] is None
    assert output["request"]["occurrence_bindings"][0]["facets"]["modality"]["source_text"] == "."
    assert output["source_semantics_verified"] is False and output["semantic_gold"] is False
    assert _validate(output, packet, declaration, profile)


@pytest.mark.parametrize("profile", ["TDFOL", "DCEC", "temporal_first_order", "event_calculus", "deontic",
    "deontic_fol", "fol", "temporal_fol", "CEC.native", "tdfol_prover", "", None, True])
def test_parser_profile_is_explicit_and_does_not_resolve_sealed_family_aliases(synthetic, profile):
    packet, declaration = _declared(synthetic)
    with pytest.raises(ValueError, match="native_parser_profile"):
        _prepare(packet, declaration, profile)


def test_parser_profile_argument_is_required_and_family_argument_is_not_accepted(synthetic):
    packet, declaration = _declared(synthetic)
    with pytest.raises(TypeError):
        views.prepare_native_view(packet, declaration, expected_packet_sha256=views.digest(packet))
    with pytest.raises(TypeError):
        views.prepare_native_view(packet, declaration, expected_packet_sha256=views.digest(packet),
                                  native_parser_profile="tdfol", family="tdfol")


@pytest.mark.parametrize("mutation", ["modal_context", "agent", "clock", "quantifier", "event", "cognition",
    "cue_unfilled", "cue_overlap", "cue_value", "bool_offset", "truncated_occurrence", "activation_scope",
    "exception_scope", "expression_missing", "qualifier_erasure", "qualifier_literal", "qualifier_extra"])
def test_declarations_cannot_infer_or_rewrite_unsupported_structure(synthetic, mutation):
    packet, declaration = _declared(synthetic, kind="both")
    interpretation = declaration["interpretation"]
    occurrence = declaration["occurrence"]
    rule = interpretation["rules"][0]
    if mutation == "modal_context": interpretation["modal_context"] = "guessed-context"
    elif mutation == "agent": interpretation["agent"] = "agency"
    elif mutation == "clock": interpretation["clock"] = "day"
    elif mutation == "quantifier": interpretation["quantifiers"] = [{"name": "x", "sort": "Object"}]
    elif mutation == "event": interpretation["events"] = [{"name": "notice", "time": 0}]
    elif mutation == "cognition": interpretation["cognition"] = {"operator": "Believes"}
    elif mutation == "cue_unfilled": occurrence["modality_anchor"]["start_char"] = None
    elif mutation == "cue_overlap": occurrence["modality_anchor"].update(start_char=0, end_char=3, source_text="The")
    elif mutation == "cue_value": occurrence["modality_anchor"]["canonical_value"] = "P"
    elif mutation == "bool_offset": occurrence["start_char"] = False
    elif mutation == "truncated_occurrence": occurrence.update(start_char=11, source_text=packet["source"]["source_text"][11:])
    elif mutation == "activation_scope": interpretation["activation_scope"] = "inside_modality"
    elif mutation == "exception_scope": interpretation["exception_scope"] = "per_tick_exemption"
    elif mutation == "expression_missing": rule["conditions"][0]["expression"] = None
    elif mutation == "qualifier_erasure": rule["conditions"] = []
    elif mutation == "qualifier_literal": rule["conditions"][0]["literal"] = "exempt"
    else: rule["exceptions"][0]["quantifier"] = "forall"
    before = deepcopy((packet, declaration))
    with pytest.raises(ValueError):
        _prepare(packet, declaration)
    assert (packet, declaration) == before


@pytest.mark.parametrize("profile", ["tdfol", "dcec"])
def test_temporal_facet_in_resealed_packet_remains_refused(synthetic, profile):
    packet, declaration = _declared(synthetic)
    changed = deepcopy(packet)
    changed["candidate"]["canonical_ir"]["rules"][0]["temporal"] = ["within 30 days"]
    altered_declaration = deepcopy(declaration)
    altered_declaration["packet_sha256"] = views.digest(changed)
    before = deepcopy(changed)
    with pytest.raises(ValueError):
        _prepare(changed, altered_declaration, profile)
    assert changed == before
    source, report, _ = synthetic.case(text="The agency shall retain records within 30 days.",
        spans={"actor": (0, 10), "action": (17, 23), "object": (24, 31), "temporal": (32, 46)})
    with pytest.raises(ValueError, match="temporal"):
        synthetic.pending(source, report)


@pytest.mark.parametrize("mutation", ["checkpoint", "position", "donor", "raw_authority", "row_geometry", "source_text",
    "binding_lane", "derived_geometry", "extra_packet", "packet_authority"])
def test_resealed_saved_packet_cannot_bypass_original_report_custody(synthetic, mutation):
    packet, declaration = _declared(synthetic, capture=True)
    changed = deepcopy(packet)
    raw_report = changed["raw_report"]
    row = raw_report["rows"][0]
    if mutation == "checkpoint": raw_report["checkpoint_sha256"] = "e" * 64
    elif mutation == "position": row["position"] = 2
    elif mutation == "donor": row["latent_donor_id"] = "another-source"
    elif mutation == "raw_authority": row["decoder_row"]["semantic_correctness_verified"] = True
    elif mutation == "row_geometry": row["decoder_row"]["span_diagnostics"]["facets"]["actor"]["char_start"] = 1
    elif mutation == "source_text": changed["source"]["source_text"] += " "
    elif mutation == "binding_lane": changed["binding"]["lane"] = "joint"
    elif mutation == "derived_geometry": changed["facet_geometry"]["object"]["start_char"] = 0
    elif mutation == "extra_packet": changed["gold_labels"] = []
    else: changed["semantic_gold"] = True
    changed["binding"]["raw_report_content_sha256"] = synthetic.adapter.digest(raw_report)
    altered_declaration = deepcopy(declaration)
    altered_declaration["packet_sha256"] = views.digest(changed)
    with pytest.raises(ValueError):
        _prepare(changed, altered_declaration)


@pytest.mark.parametrize("mutation", ["search", "score_digest", "source_ID", "row_coverage"])
def test_resealed_joint_packet_requires_exact_original_saved_score_replay(synthetic, mutation):
    packet, declaration = _declared(synthetic, lane="joint")
    changed = deepcopy(packet)
    saved = changed["joint_report"]
    if mutation == "search": saved["rows"][0]["result"]["search"]["visited_nodes"] += 1
    elif mutation == "score_digest": saved["rows"][0]["result"]["scores_sha256"] = "e" * 64
    elif mutation == "source_ID": saved["rows"][0]["id"] = "another-source"
    else: saved["rows"] = []
    changed["binding"]["joint_report_content_sha256"] = synthetic.adapter.digest(saved)
    altered_declaration = deepcopy(declaration)
    altered_declaration["packet_sha256"] = views.digest(changed)
    with pytest.raises(ValueError):
        _prepare(changed, altered_declaration)


@pytest.mark.parametrize("mutation", ["native_ast", "native_lean", "original_ast", "original_lean", "request",
    "qualifier_structure", "binding", "sealed_family", "route", "parser", "view_scope", "declaration_digest",
    "registry_qualification", "semantic_gold", "cross_family", "model_authentication", "source_custody",
    "producer_pin", "extra", "flag_type"])
def test_output_replay_rejects_tampering_even_with_repaired_nested_and_outer_seals(synthetic, mutation):
    packet, declaration = _declared(synthetic, kind="condition")
    output = _prepare(packet, declaration)
    if mutation == "native_ast": output["native_view"]["formulas"][0]["native_ast"]["right"]["operator"]["value"] = "P"
    elif mutation == "native_lean": output["native_view"]["lean_body"] = "def disguised : Prop := True"
    elif mutation == "original_ast": output["original_deontic_output"]["native_bridge"]["formulas"][0]["native_ast"]["right"]["operator"]["value"] = "P"
    elif mutation == "original_lean": output["original_deontic_output"]["native_bridge"]["lean_body"] = "def disguised : Prop := True"
    elif mutation == "request": output["request"]["occurrence_bindings"][0]["facets"]["actor"]["start_char"] = 1
    elif mutation == "qualifier_structure": output["request"]["interpretation"]["rules"][0]["conditions"][0]["expression"]["predicate"]["name"] = "different_hypothesis"
    elif mutation == "binding": output["binding"]["checkpoint_sha256"] = "e" * 64
    elif mutation == "sealed_family": output["sealed_legal_family"] = "tdfol"
    elif mutation == "route": output["sealed_route"]["family_id"] = "tdfol"
    elif mutation == "parser": output["native_parser_profile"] = "dcec"
    elif mutation == "view_scope": output["native_profile_scope"] = "all temporal first-order formulas"
    elif mutation == "declaration_digest": output["declaration_sha256"] = "e" * 64
    elif mutation == "registry_qualification": output["registry_family_qualified"] = True
    elif mutation == "semantic_gold": output["semantic_gold"] = True
    elif mutation == "cross_family": output["cross_family_equivalence_verified"] = True
    elif mutation == "model_authentication": output["model_authenticated"] = True
    elif mutation == "source_custody": output["source_context_custody_verified"] = True
    elif mutation == "producer_pin": output["producer_pins"][next(iter(output["producer_pins"]))] = "e" * 64
    elif mutation == "extra": output["gold_labels"] = []
    else: output["registry_family_qualified"] = 0
    # Repaired content digests are deliberately insufficient to authorize a
    # changed native structure, source join, qualifier expression or claim.
    for report in (output["native_view"], output["original_deontic_output"]["native_bridge"]):
        report["report_sha256"] = views.digest({key: value for key, value in report.items()
                                               if key != "report_sha256"})
    output["native_view_sha256"] = views.digest(output["native_view"])
    output["original_deontic_output_sha256"] = views.digest(output["original_deontic_output"])
    output["request_sha256"] = views.digest(output["request"])
    _reseal(output)
    with pytest.raises(ValueError):
        _validate(output, packet, declaration)


def test_output_seal_and_expected_packet_digest_are_separate_replay_requirements(synthetic):
    packet, declaration = _declared(synthetic)
    output = _prepare(packet, declaration)
    output["output_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="seal"):
        _validate(output, packet, declaration)
    with pytest.raises(ValueError):
        views.prepare_native_view(packet, declaration, expected_packet_sha256="e" * 64,
                                  native_parser_profile="tdfol")


def test_input_and_output_snapshots_are_detached_without_trimming_original_request(synthetic):
    packet, declaration = _declared(synthetic, kind="both")
    output = _prepare(packet, declaration)
    snapshot = deepcopy(output)
    packet["source"]["source_text"] = "changed after preparation"
    declaration["occurrence"]["source_text"] = "changed after preparation"
    assert output == snapshot
    original = deepcopy(output["original_deontic_output"])
    output["request"]["candidate"]["source_text"] = "changed output request"
    assert output["original_deontic_output"] == original
    assert output["native_view"]["canonical_roundtrip"] == original["canonical_ir"]


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"nested":{"x":1,"x":2}}', b'{"x":NaN}',
    b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e999}', b'\xff', b''])
def test_strict_json_transport_refuses_ambiguous_nonfinite_or_invalid_bytes(raw):
    with pytest.raises(ValueError):
        views.parse_json_bytes(raw)


@pytest.mark.parametrize("value", [{0: "non-string-key"}, {"tuple": (1, 2)}, {"set": {1, 2}},
    {"number": float("nan")}, {"number": float("inf")}])
def test_direct_transport_requires_exact_finite_json_types(value):
    with pytest.raises(ValueError):
        views.digest(value)


def test_content_digest_does_not_equal_pretty_file_identity_and_bounds_are_enforced(monkeypatch, synthetic):
    packet, declaration = _declared(synthetic)
    output = _prepare(packet, declaration)
    pretty = json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    assert views.parse_json_bytes(pretty) == output
    assert hashlib.sha256(pretty).hexdigest() != views.digest(output)
    monkeypatch.setattr(views, "MAX_INPUT_BYTES", 8)
    with pytest.raises(ValueError, match="bound"):
        views.parse_json_bytes(pretty)
    with pytest.raises(ValueError, match="bound"):
        _prepare(packet, declaration)
    monkeypatch.setattr(views, "MAX_OUTPUT_BYTES", 8)
    with pytest.raises(ValueError, match="bound"):
        views.digest(output)


def test_nesting_is_bounded_and_cycles_cannot_become_json(monkeypatch):
    monkeypatch.setattr(views, "MAX_JSON_DEPTH", 2)
    with pytest.raises(ValueError, match="nesting"):
        views.digest([[[[0]]]])
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError, match="nesting"):
        views.digest(cyclic)


def test_pure_transport_does_not_acquire_producer_owners(monkeypatch):
    def denied():
        raise AssertionError("producer owner acquisition during transport")
    monkeypatch.setattr(views, "_owners", denied)
    assert views.parse_json_bytes(br'{"detached":"Caf\u00e9"}') == {"detached": "Café"}
    assert views.digest({"detached": "Café"}) == hashlib.sha256(
        b'{"detached":"Caf\xc3\xa9"}').hexdigest()


def test_changed_producer_endpoint_during_preparation_refuses_output(monkeypatch, synthetic):
    packet, declaration = _declared(synthetic)
    calls = []
    original = views.producer_pins
    def changed():
        pins = original()
        calls.append(True)
        if len(calls) > 1:
            pins["synthetic-changing-producer"] = "e" * 64
        return pins
    monkeypatch.setattr(views, "producer_pins", changed)
    with pytest.raises(ValueError, match="producer changed"):
        _prepare(packet, declaration)
    assert len(calls) == 2


def test_source_import_boundary_is_stdlib_only_and_owner_imports_are_lazy():
    path = Path(views.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = {"__future__", "copy", "hashlib", "importlib", "json", "pathlib", "re"}
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    for node in imports:
        names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module]
        assert all(name.split(".")[0] in allowed for name in names)
    top_calls = [node for node in tree.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)]
    assert top_calls == []
    owner = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_owners")
    names = [node.args[0].value for node in ast.walk(owner) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"]
    assert names == ["ipfs_datasets_py.logic.legal_ir.saved_span_family_adapter",
                     "ipfs_datasets_py.logic.autoformal.legal_source_family_bridge"]
