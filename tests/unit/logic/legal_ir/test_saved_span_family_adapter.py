"""Inert saved-artifact transport and native preparation, never a model fit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.legal_ir import saved_span_family_adapter as adapter
from ipfs_datasets_py.logic.legal_ir import joint_span_selection as joint


CHECKPOINT = "a" * 64
PARENT = "b" * 64
LATENT = "c" * 64
FALSE = {"qualified": False, "admitted": False, "formalized": False, "roundtrip_ok": False,
         "proof_authority": False, "semantic_correctness_verified": False,
         "promotion_performed": False, "publication_performed": False}


def case(modality="O", *, capture=False, text=None, spans=None, cue=None):
    fixtures = {
        "O": ("The agency shall retain records.", (11, 16), (0, 10), (17, 23), (24, 31)),
        "P": ("The agency may retain records.", (11, 14), (0, 10), (15, 21), (22, 29)),
        "F": ("The agency shall not retain records.", (11, 20), (0, 10), (21, 27), (28, 35)),
    }
    default, modal, actor, action, obj = fixtures[modality]
    text = default if text is None else text
    cue = modal if cue is None else cue
    spans = {"actor": actor, "action": action, "object": obj} if spans is None else spans
    tokens = [{k: v[k] for k in ("text", "start", "end")} for v in joint._owner().tokenize_source(text)]
    scores = {"schema": joint.SCORE_SCHEMA, "tokens": tokens,
              "modality_logits": [6.0 if m == modality else 0.0 for m in joint.MODALITIES],
              "presence_logits": {f: [0.0, 8.0] if f in spans else [8.0, 0.0] for f in joint.OPTIONAL_FIELDS},
              "start_logits": {}, "end_logits": {}}
    for field in joint.FIELDS:
        starts = [-8.0] * len(tokens)
        ends = [-8.0] * len(tokens)
        if field in spans:
            left, right = spans[field]
            starts[next(i for i, t in enumerate(tokens) if t["start"] == left)] = 16.0
            ends[next(i for i, t in enumerate(tokens) if t["end"] == right)] = 16.0
        scores["start_logits"][field], scores["end_logits"][field] = starts, ends
    greedy = joint._greedy(text, scores, {f: joint._rank_spans(scores, f) for f in joint.FIELDS})
    raw = raw_row(text, scores, greedy)
    identity = "authored-development-" + modality
    source = {"id": identity, "source_text": text, "source_sha256": hashlib.sha256(text.encode()).hexdigest()}
    row = {"id": identity, "position": 0, "source_sha256": source["source_sha256"],
           "effective_latent_sha256": LATENT, "latent_donor_id": identity, "latent_donor_position": 0,
           "decoder_row": raw, "scores": scores if capture else None}
    report = {
        "schema": adapter.RAW_SCHEMA, "lineage_id": adapter.LINEAGE, "checkpoint_sha256": CHECKPOINT,
        "historical_parent_sha256": PARENT, "control": "none", "rows": [row],
        "objective": {"schema": "source-span-order-overlap-probability/v1", "structure_weight": 0.0,
            "accumulator": "float64_probability_terms_from_CPU_float32_heads",
            "active_fields": "authored_reference_presence_only; actor_and_action_required",
            "authority": "authored_engineering_geometry; no_legal_semantic_qualification",
            "base_ce": "equal_facet_modality_presence_mean_start_end/v1",
            "total": "CE + weight * (validity + overlap) / 2"},
        "progress": {"absolute_optimizer_steps": 432, "inherited_optimizer_steps": 400,
                     "new_optimizer_steps": 32, "epochs_completed": 4, "row_cursor": 576},
        "same_forward_scores": capture, "actual_source_forwards": 1, "additional_model_forwards": 0,
        "weights_unchanged": True, "optimizer_moments_unchanged": True, "ambient_CPU_RNG_preserved": True,
        "optimizer_updates": 0, "native_encoder_executed": False, "legal_accuracy": None,
        "family_bridge_admitted": False, "Lake_executed": False, "target_access": False,
        "teacher_forcing": False, "training_executed": False, **FALSE,
    }
    return source, report, cue


def raw_row(text, scores, greedy):
    facets = {}
    for field, item in greedy["facets"].items():
        span = item["span"]
        facets[field] = {"present": item["present"], "presence_logit_margin": item["presence_logit_margin"],
                        "span_logit_margin": item["span_logit_margin"],
                        **{k: span[k] if span else None for k in
                           ("token_start", "token_end_inclusive", "char_start", "char_end", "text")}}
    ir = deepcopy(greedy["canonical_ir"])
    display = None if ir is None else json.dumps(ir, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    raw = {"source_sha256": hashlib.sha256(text.encode()).hexdigest(), "latent_sha256": LATENT,
           "status": greedy["status"], "reason": greedy["reason"], "canonical_ir": ir,
           "formula_text": display, "formal_outputs": [], "teacher_forcing": False, "target_access": False,
           "training_executed": False, "source_input_conditioned": True, "learned_formula_generation": True,
           "sample_memory_used": False, "family_syntax_checked": ir is not None,
           "latent_input_enabled": False, "span_diagnostics": {"tokens": deepcopy(scores["tokens"]),
               "modality_logits": deepcopy(scores["modality_logits"]), "facets": facets}, **FALSE}
    if ir is not None:
        raw.update(minimum_decision_logit_margin=greedy["minimum_decision_logit_margin"],
                   syntax_scope="single_canonical_deontic_rule_with_one_copied_span_per_facet",
                   formal_outputs=[{"family": "deontic", "format": "typed-deontic-rule/v1", "payload": ir["rules"][0],
                       "formula_text": display, "formula_text_role": "display_only_full_ast_is_authoritative",
                       "origin": "learned_source_span_formula_decoder", **FALSE}])
    return raw


def pending(source, report, joint_report=None):
    return adapter.prepare_pending(source, report, expected_report_sha256=adapter.digest(report),
        expected_checkpoint_sha256=CHECKPOINT, row_id=source["id"], joint_report=joint_report,
        expected_joint_report_sha256=None if joint_report is None else adapter.digest(joint_report))


def declaration(packet, cue):
    from ipfs_datasets_py.logic.autoformal import legal_source_family_bridge as bridge
    value = adapter.declaration_skeleton(packet)
    source = packet["source"]["source_text"]
    value["occurrence"].update(occurrence_id="explicit-development-occurrence", start_char=0,
        end_char=len(source), source_text=source,
        modality_anchor={"start_char": cue[0], "end_char": cue[1], "source_text": source[cue[0]:cue[1]],
            "canonical_value": packet["candidate"]["canonical_ir"]["rules"][0]["modality"]})
    value["interpretation"].update(activation_scope=bridge.ACTIVATION_SCOPE, exception_scope=bridge.EXCEPTION_SCOPE)
    return value


@pytest.mark.parametrize("modality", ["O", "P", "F"])
@pytest.mark.parametrize("capture", [False, True])
def test_declared_saved_proposal_emits_real_native_spine_without_authority(modality, capture):
    source, report, cue = case(modality, capture=capture)
    initial = deepcopy((source, report))
    packet = pending(source, report)
    value = declaration(packet, cue)
    output = adapter.prepare_family(packet, value, expected_packet_sha256=adapter.digest(packet))
    assert output["sealed_route"]["family_id"] == "deontic"
    assert output["native_parser_profile"] == "deontic_fol"
    assert output["canonical_ir"] == report["rows"][0]["decoder_row"]["canonical_ir"]
    node = output["native_bridge"]["formulas"][0]["native_ast"]
    assert node["node_type"] == "DeonticFormula" and node["operator"]["value"] == modality
    assert "i.modal \"deontic:" + modality + "\"" in output["native_bridge"]["lean_body"]
    assert all(output[k] is False for k in adapter.FALSE)
    assert adapter.validate_family(output, packet, value, expected_packet_sha256=adapter.digest(packet))
    assert (source, report) == initial
    assert packet["saved_head_replay_performed"] is capture


def test_full_96_row_report_is_bound_without_truncation_or_source_aliasing():
    source, report, _ = case()
    first = deepcopy(report["rows"][0])
    report["rows"] = []
    for i in range(96):
        row = deepcopy(first)
        row.update(id="authored-" + str(i), position=i, latent_donor_id="authored-" + str(i), latent_donor_position=i)
        report["rows"].append(row)
    report["actual_source_forwards"] = 96
    source["id"] = "authored-95"
    packet = pending(source, report)
    assert len(packet["raw_report"]["rows"]) == 96 and packet["binding"]["position"] == 95
    assert packet["physical_context_status"] == "absent" and packet["source_context_custody_verified"] is False
    changed = deepcopy(report)
    changed["rows"][0]["id"] = "another-ID"
    changed["rows"][0]["latent_donor_id"] = "another-ID"
    assert pending(source, changed)["binding"]["raw_report_content_sha256"] != packet["binding"]["raw_report_content_sha256"]


def test_unicode_geometry_and_declared_physical_identity_do_not_imply_context_custody():
    text = "Café bureau shall retain résumé records."
    source, report, cue = case(text=text, spans={"actor": (0, 11), "action": (18, 24), "object": (25, 39)}, cue=(12, 17))
    source["physical_occurrence"] = {"occurrence_id": "archived-physical-27",
        "context_identity": {"document_id": "section-27", "artifact_sha256": "d" * 64,
            "selected_char_start": 7, "selected_char_end": 7 + len(text),
            "selected_utf8_byte_start": 9, "selected_utf8_byte_end": 9 + len(text.encode())}}
    packet = pending(source, report)
    assert packet["facet_geometry"]["actor"]["end_char"] == 11
    assert packet["facet_geometry"]["actor"]["utf8_byte_end"] == 12
    output = adapter.prepare_family(packet, declaration(packet, cue), expected_packet_sha256=adapter.digest(packet))
    assert output["modality_anchor_utf8_bytes"] == [13, 18]
    assert output["physical_context_status"] == "caller_declared_not_authenticated"
    assert not output["source_context_custody_verified"]


def test_repeated_surface_preserves_actual_occurrence_not_first_text_match():
    source, report, cue = case(text="Agency shall notify Agency.",
        spans={"actor": (0, 6), "action": (13, 19), "object": (20, 26)}, cue=(7, 12))
    packet = pending(source, report)
    output = adapter.prepare_family(packet, declaration(packet, cue), expected_packet_sha256=adapter.digest(packet))
    facets = output["request"]["occurrence_bindings"][0]["facets"]
    assert facets["actor"]["source_text"] == facets["object"]["source_text"] == "Agency"
    assert facets["actor"]["start_char"] == 0 and facets["object"]["start_char"] == 20


def test_pending_declarations_leave_cue_and_meaning_unassigned():
    source, report, _ = case()
    packet = pending(source, report)
    blank = adapter.declaration_skeleton(packet)
    assert blank["occurrence"]["start_char"] is None and blank["occurrence"]["source_text"] is None
    assert blank["occurrence"]["modality_anchor"]["start_char"] is None
    assert blank["occurrence"]["modality_anchor"]["source_text"] is None
    assert blank["interpretation"]["activation_scope"] is None
    with pytest.raises(ValueError):
        adapter.prepare_family(packet, blank, expected_packet_sha256=adapter.digest(packet))


def test_no_object_is_unary_and_no_modality_surface_meaning_is_inferred():
    source, report, cue = case(text="The agency shall retain.", spans={"actor": (0, 10), "action": (17, 23)})
    packet = pending(source, report)
    assert packet["facet_geometry"]["object"] is None
    value = declaration(packet, cue)
    # A deliberately meaningless caller declaration remains a declaration;
    # the transport performs no shall/may heuristic or semantic validation.
    value["occurrence"]["modality_anchor"].update(start_char=23, end_char=24, source_text=".")
    output = adapter.prepare_family(packet, value, expected_packet_sha256=adapter.digest(packet))
    assert len(output["native_bridge"]["formulas"][0]["native_ast"]["formula"]["arguments"]) == 1
    assert output["source_semantics_verified"] is False


def test_temporal_profile_is_refused_without_dropping_the_copied_facet():
    source, report, _ = case(text="The agency shall retain records within 30 days.",
        spans={"actor": (0, 10), "action": (17, 23), "object": (24, 31), "temporal": (32, 46)})
    before = deepcopy(report)
    with pytest.raises(ValueError, match="temporal"): pending(source, report)
    assert report == before


def test_qualifier_expression_requires_explicit_declaration_and_preserves_scope():
    text = "The agency shall retain records if licensed."
    source, report, cue = case(text=text, spans={"actor": (0, 10), "action": (17, 23),
        "object": (24, 31), "conditions": (35, 43)})
    packet = pending(source, report)
    value = declaration(packet, cue)
    assert value["interpretation"]["rules"][0]["conditions"][0]["expression"] is None
    with pytest.raises(ValueError):
        adapter.prepare_family(packet, value, expected_packet_sha256=adapter.digest(packet))
    value["interpretation"]["rules"][0]["conditions"][0]["expression"] = {
        "op": "atom", "predicate": {"name": "caller_licensed", "arguments": ["The agency"]}}
    output = adapter.prepare_family(packet, value, expected_packet_sha256=adapter.digest(packet))
    node = output["native_bridge"]["formulas"][0]["native_ast"]
    assert node["node_type"] == "BinaryFormula" and node["operator"]["value"] == "→"
    assert node["right"]["node_type"] == "DeonticFormula"
    assert not output["source_semantics_verified"]


@pytest.mark.parametrize("mutation", ["duplicate_id", "position", "bool_position", "extra", "target_access",
    "checkpoint", "lineage", "source_sha", "latent_sha", "donor", "capture", "forward_count",
    "objective", "progress", "display", "formal_payload", "authority", "facet_interval", "tokens", "presence"])
def test_malformed_or_inconsistent_raw_transport_is_rejected_even_with_repaired_digest(mutation):
    source, report, _ = case()
    row = report["rows"][0]
    raw = row["decoder_row"]
    if mutation == "duplicate_id": report["rows"].append(deepcopy(row))
    elif mutation == "position": row["position"] = 3
    elif mutation == "bool_position": row["position"] = False
    elif mutation == "extra": report["labels"] = []
    elif mutation == "target_access": report["target_access"] = True
    elif mutation == "checkpoint": report["checkpoint_sha256"] = "e" * 64
    elif mutation == "lineage": report["lineage_id"] = "old-alias"
    elif mutation == "source_sha": row["source_sha256"] = "e" * 64
    elif mutation == "latent_sha": raw["latent_sha256"] = "e" * 64
    elif mutation == "donor": row["latent_donor_id"] = "unrelated"
    elif mutation == "capture": row["scores"] = {}
    elif mutation == "forward_count": report["actual_source_forwards"] = True
    elif mutation == "objective": report["objective"]["authority"] = "human gold"
    elif mutation == "progress": report["progress"]["new_optimizer_steps"] = 33
    elif mutation == "display": raw["formula_text"] = "O(True)"
    elif mutation == "formal_payload": raw["formal_outputs"][0]["payload"] = {}
    elif mutation == "authority": raw["proof_authority"] = True
    elif mutation == "facet_interval": raw["span_diagnostics"]["facets"]["actor"]["char_start"] = 1
    elif mutation == "tokens": raw["span_diagnostics"]["tokens"][0]["text"] = "Wrong"
    elif mutation == "presence": raw["span_diagnostics"]["facets"]["object"]["present"] = False
    with pytest.raises(ValueError): pending(source, report)


@pytest.mark.parametrize("mutation", ["cue_unfilled", "cue_overlap", "cue_value", "bool_offset", "occurrence_truncated",
    "occurrence_text", "occurrence_id", "wrong_packet", "interpretation_scope", "extra"])
def test_caller_declaration_cannot_invent_or_cross_attach_bindings(mutation):
    source, report, cue = case()
    packet = pending(source, report)
    value = declaration(packet, cue)
    o = value["occurrence"]
    if mutation == "cue_unfilled": o["modality_anchor"]["start_char"] = None
    elif mutation == "cue_overlap": o["modality_anchor"].update(start_char=0, end_char=3, source_text="The")
    elif mutation == "cue_value": o["modality_anchor"]["canonical_value"] = "P"
    elif mutation == "bool_offset": o["start_char"] = False
    elif mutation == "occurrence_truncated": o.update(start_char=11, source_text=source["source_text"][11:])
    elif mutation == "occurrence_text": o["source_text"] += " "
    elif mutation == "occurrence_id": o["occurrence_id"] = None
    elif mutation == "wrong_packet": value["packet_sha256"] = "e" * 64
    elif mutation == "interpretation_scope": value["interpretation"]["modal_context"] = "guessed-context"
    elif mutation == "extra": value["gold"] = True
    with pytest.raises(ValueError): adapter.prepare_family(packet, value, expected_packet_sha256=adapter.digest(packet))


@pytest.mark.parametrize("family", ["tdfol", "dcec", "event_calculus", "fol", "deontic_fol", "frame_logic", "graph_projection"])
def test_family_labels_cannot_invent_unsupported_profile_or_composition(family):
    source, report, cue = case()
    packet = pending(source, report)
    with pytest.raises(ValueError): adapter.prepare_family(packet, declaration(packet, cue),
        expected_packet_sha256=adapter.digest(packet), family=family)


def joint_report(source, report):
    result = joint.select_joint_spans(source["source_text"], report["rows"][0]["scores"], top_k=8, max_search_nodes=50000)
    return {"schema": adapter.JOINT_SCHEMA, "rows": [{"id": source["id"], "result": result}],
        "top_k": 8, "max_search_nodes": 50000, "learned_presence_and_modality_fixed": True,
        "raw_greedy_preserved": True, "qualified": False, "semantic_accuracy": None,
        "used_for_updates_or_selection": False}


def test_joint_replay_preserves_separate_readout_and_refused_raw_parent():
    source, report, cue = case(capture=True)
    scores = report["rows"][0]["scores"]
    scores["start_logits"]["object"] = [10.0, -8.0, -8.0, -8.0, 9.0, -8.0]
    scores["end_logits"]["object"] = [-8.0, 10.0, -8.0, -8.0, 9.0, -8.0]
    greedy = joint._greedy(source["source_text"], scores, {f: joint._rank_spans(scores, f) for f in joint.FIELDS})
    report["rows"][0]["decoder_row"] = raw_row(source["source_text"], scores, greedy)
    assert greedy["reason"] == "copied_spans_overlap"
    with pytest.raises(ValueError, match="refused"): pending(source, report)
    saved_joint = joint_report(source, report)
    assert saved_joint["rows"][0]["result"]["status"] == "selected"
    packet = pending(source, report, saved_joint)
    assert packet["binding"]["lane"] == "joint" and packet["raw_report"]["rows"][0]["decoder_row"]["canonical_ir"] is None
    output = adapter.prepare_family(packet, declaration(packet, cue), expected_packet_sha256=adapter.digest(packet))
    assert not output["raw_output_repaired"]


@pytest.mark.parametrize("mutation", ["id", "candidate", "scores", "search", "policy", "coverage", "extra", "no_capture"])
def test_joint_attachment_requires_exact_saved_score_replay(mutation):
    source, report, _ = case(capture=True)
    saved = joint_report(source, report)
    result = saved["rows"][0]["result"]
    if mutation == "id": saved["rows"][0]["id"] = "another-row"
    elif mutation == "candidate": result["canonical_ir"]["rules"][0]["action"] = "shall"
    elif mutation == "scores": result["scores_sha256"] = "e" * 64
    elif mutation == "search": result["search"]["visited_nodes"] += 1
    elif mutation == "policy": saved["top_k"] = True
    elif mutation == "coverage": saved["rows"] = []
    elif mutation == "extra": saved["checkpoint_sha256"] = CHECKPOINT
    elif mutation == "no_capture": report["same_forward_scores"] = False; report["rows"][0]["scores"] = None
    with pytest.raises(ValueError): pending(source, report, saved)


@pytest.mark.parametrize("field", ["candidate", "geometry", "source", "binding", "authority", "extra"])
def test_pending_replay_rejects_derived_tampering_with_repaired_digest(field):
    source, report, _ = case()
    packet = pending(source, report)
    if field == "candidate": packet["candidate"]["canonical_ir"]["rules"][0]["action"] = "shall"
    elif field == "geometry": packet["facet_geometry"]["actor"]["start_char"] = 1
    elif field == "source": packet["source"]["source_text"] += " "
    elif field == "binding": packet["binding"]["lane"] = "joint"
    elif field == "authority": packet["semantic_gold"] = True
    else: packet["targets"] = []
    with pytest.raises(ValueError): adapter.validate_pending(packet, expected_packet_sha256=adapter.digest(packet))


@pytest.mark.parametrize("field", ["lean", "ast", "occurrence", "declaration", "authority"])
def test_native_output_replay_rejects_substitution(field):
    source, report, cue = case()
    packet = pending(source, report)
    value = declaration(packet, cue)
    output = adapter.prepare_family(packet, value, expected_packet_sha256=adapter.digest(packet))
    if field == "lean": output["native_bridge"]["lean_body"] = "def disguised : Prop := True"
    elif field == "ast": output["native_bridge"]["formulas"][0]["native_ast"]["operator"]["value"] = "P"
    elif field == "occurrence": output["request"]["occurrence_bindings"][0]["start_char"] = 1
    elif field == "declaration": output["declaration_sha256"] = "e" * 64
    else: output["qualified"] = True
    with pytest.raises(ValueError): adapter.validate_family(output, packet, value, expected_packet_sha256=adapter.digest(packet))


def test_strict_transport_distinguishes_file_sha_and_supports_packet_bound():
    source, report, _ = case()
    compact = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    pretty = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode()
    assert hashlib.sha256(compact).hexdigest() != hashlib.sha256(pretty).hexdigest()
    assert adapter.digest(adapter.parse_json_bytes(pretty)) == adapter.digest(report)
    packet = pending(source, report)
    assert adapter.parse_json_bytes(json.dumps(packet).encode()) == packet
    for raw in [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'\xff']:
        with pytest.raises(ValueError): adapter.parse_json_bytes(raw)
    with pytest.raises(ValueError): adapter.prepare_pending(source, report,
        expected_report_sha256=hashlib.sha256(pretty).hexdigest(), expected_checkpoint_sha256=CHECKPOINT, row_id=source["id"])


@pytest.mark.parametrize("mutation", ["source_ID", "text", "labels", "physical_extra", "physical_length", "bool_physical_offset"])
def test_source_and_declared_physical_aliases_fail_closed(mutation):
    source, report, _ = case()
    source["physical_occurrence"] = {"occurrence_id": "physical-1", "context_identity": {
        "document_id": "document-1", "artifact_sha256": "d" * 64, "selected_char_start": 5,
        "selected_char_end": 5 + len(source["source_text"]), "selected_utf8_byte_start": 5,
        "selected_utf8_byte_end": 5 + len(source["source_text"].encode())}}
    if mutation == "source_ID": source["id"] = "unrelated-occurrence"
    elif mutation == "text": source["source_text"] += " "
    elif mutation == "labels": source["canonical_ir"] = {}
    elif mutation == "physical_extra": source["physical_occurrence"]["official_authority"] = True
    elif mutation == "physical_length": source["physical_occurrence"]["context_identity"]["selected_char_end"] += 1
    else: source["physical_occurrence"]["context_identity"]["selected_char_start"] = False
    with pytest.raises(ValueError): pending(source, report)


def test_report_and_packet_limits_are_separate(monkeypatch):
    # Small control bounds exercise the transport relation without a large file.
    monkeypatch.setattr(adapter, "MAX_REPORT_BYTES", 8)
    monkeypatch.setattr(adapter, "MAX_PACKET_BYTES", 128)
    assert adapter.parse_json_bytes(b'{"valid_packet":"more than report budget"}')
    source, report, _ = case()
    with pytest.raises(ValueError, match="bound"): pending(source, report)


def test_import_and_pure_transport_have_no_numerical_imports():
    root = Path(__file__).resolve().parents[4]
    source, report, _ = case()
    script = '''
import builtins, sys, json
original = builtins.__import__
def denied(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'numpy', 'tensorflow', 'jax', 'transformers'}:
        raise AssertionError('numerical import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = denied
from ipfs_datasets_py.logic.legal_ir import saved_span_family_adapter as a
assert a.parse_json_bytes(b'{"source_only":true}') == {'source_only': True}
'''
    script += "source = json.loads(" + repr(json.dumps(source)) + ")\n"
    script += "report = json.loads(" + repr(json.dumps(report)) + ")\n"
    script += '''
packet = a.prepare_pending(source, report, expected_report_sha256=a.digest(report),
    expected_checkpoint_sha256='a'*64, row_id=source['id'])
assert packet['model_executed'] is False
assert not ({'torch', 'numpy', 'tensorflow', 'jax', 'transformers'} & set(sys.modules))
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
