#!/usr/bin/env python3
"""Bind frozen real-source decoder outputs to explicit native family profiles.

No decoding, fitting, semantic repair, reference-label construction or qualifier
meaning inference occurs here.  Every model/source/family slot remains visible.
Only exact predicted facet intervals and one saved, enabled trigger with a recognized cue
can enter the qualifier-free profile.  A native build never establishes that a
single decoded rule captures a whole statutory paragraph or section.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from ipfs_datasets_py.logic.autoformal import legal_source_family_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_source_family_lake as gate
from scripts.ops.legal_ir import evaluate_legal_uscode_fidelity as evaluation

SCHEMA = "legal-uscode-decoder-family-pilot/v1"
FAMILIES = ("deontic_fol", "tdfol", "dcec")
MAX_BATCH_REQUESTS = 126
MAX_BATCH_BYTES = 3 * 1024**2
CUES = {"must": "O", "shall": "O", "may": "P", "must not": "F", "shall not": "F", "may not": "F"}
_CUE_PATTERN = re.compile(r"\b(?:must not|shall not|may not|must|shall|may)\b", re.IGNORECASE)


class Refusal(ValueError):
    """An explicit unsupported pilot binding; it is retained in its slot."""


def _require(value, reason):
    if not value:
        raise Refusal(reason)


def _wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def predicted_span(text, literal, diagnostic):
    """Bind exactly the saved decoder interval; repeated surfaces stay distinct."""
    _require(type(diagnostic) is dict, "missing_predicted_facet_diagnostic")
    if literal == "":
        _require(diagnostic.get("present") is False and all(diagnostic.get(k) is None
                 for k in ("char_start", "char_end", "text")), "absent_facet_diagnostic_disagrees")
        return None
    _require(type(literal) is str and bool(literal), "missing_direct_facet")
    start, end = diagnostic.get("char_start"), diagnostic.get("char_end")
    _require(diagnostic.get("present") is True and type(start) is int and type(end) is int
             and 0 <= start < end <= len(text), "invalid_predicted_facet_interval")
    _require(text[start:end] == diagnostic.get("text") == literal, "predicted_facet_exact_source_disagreement")
    return {"start_char": start, "end_char": end, "source_text": literal, "canonical_value": literal}


def _trigger(source, prediction, modality):
    diagnostics = prediction.get("grounding_diagnostics")
    _require(type(diagnostics) is dict and diagnostics.get("trigger_residual_enabled") is True,
             "no_enabled_learned_trigger_diagnostic")
    _require(diagnostics.get("annotations_accessed") is False, "trigger_diagnostic_source_only_not_attested")
    trigger = diagnostics.get("trigger")
    _require(type(trigger) is dict, "missing_trigger_span")
    start, end = trigger.get("char_start"), trigger.get("char_end")
    _require(type(start) is int and type(end) is int and 0 <= start < end <= len(source), "invalid_trigger_span")
    text = source[start:end]
    _require(text == trigger.get("text") and diagnostics.get("trigger_span") == [start, end]
             and diagnostics.get("trigger_text") == text, "trigger_diagnostic_span_disagreement")
    _require(text.lower() in CUES and CUES[text.lower()] == modality, "unsupported_or_inconsistent_modality_cue")
    if modality != "F":
        _require(re.match(r"\s+(?:not|never)\b", source[end:], re.IGNORECASE) is None,
                 "cue_has_unmodeled_negation")
    # A saved pointer cannot authorize choosing one of several statutory norms.
    matches = list(_CUE_PATTERN.finditer(source))
    _require(len(matches) == 1 and matches[0].span() == (start, end), "ambiguous_or_partial_modality_cue")
    return {"start_char": start, "end_char": end, "source_text": text, "canonical_value": modality}


def request_for_prediction(source, prediction, model_name):
    """Prepare a candidate-only request without changing any decoded facet."""
    text = source["source_text"]
    _require(hashlib.sha256(text.encode()).hexdigest() == source["source_sha256"] == prediction.get("source_sha256"),
             "source_prediction_hash_disagreement")
    _require(prediction.get("status") == "decoded", "decoder_did_not_produce_candidate")
    ir = prediction.get("canonical_ir")
    _require(type(ir) is dict and set(ir) == {"rules"} and type(ir["rules"]) is list and len(ir["rules"]) == 1,
             "pilot_requires_one_unchanged_decoded_rule")
    rule = ir["rules"][0]
    _require(type(rule) is dict and set(rule) == {"modality", "actor", "action", "object", "conditions", "exceptions", "temporal"},
             "malformed_canonical_rule")
    for facet in ("conditions", "exceptions", "temporal"):
        _require(type(rule[facet]) is list, "malformed_canonical_qualifier_list")
        _require(not rule[facet], "unreviewed_qualifier_interpretation:" + facet)
    diagnostics = prediction.get("span_diagnostics", {}).get("facets")
    _require(type(diagnostics) is dict, "missing_predicted_facet_diagnostics")
    facets = {facet: predicted_span(text, rule[facet], diagnostics.get(facet)) for facet in ("actor", "action")}
    _require(type(rule["object"]) is str, "malformed_canonical_object")
    facets["object"] = predicted_span(text, rule["object"], diagnostics.get("object"))
    for facet in ("conditions", "exceptions", "temporal"):
        predicted_span(text, "", diagnostics.get(facet))
    facets.update(modality=_trigger(text, prediction, rule["modality"]), conditions=[], exceptions=[], temporal=[])
    # Do not bind a copied facet to part of its own modal cue.
    trigger = facets["modality"]
    for name in ("actor", "action", "object"):
        facet = facets[name]
        _require(facet is None or facet["end_char"] <= trigger["start_char"] or trigger["end_char"] <= facet["start_char"],
                 "copied_facet_overlaps_modality_cue")
    identity = model_name + "::" + source["id"]
    candidate = {"candidate_id": identity, "source_text": text, "source_sha256": source["source_sha256"],
                 "canonical_ir": deepcopy(ir)}
    interpretation = bridge.interpretation_skeleton(candidate)
    interpretation.update(activation_scope=bridge.ACTIVATION_SCOPE, exception_scope=bridge.EXCEPTION_SCOPE)
    occurrence = {"occurrence_id": identity + "::whole-view-candidate", "rule_index": 0,
                  "start_char": 0, "end_char": len(text), "source_text": text, "facets": facets}
    return {"candidate": candidate, "interpretation": interpretation, "occurrence_bindings": [occurrence]}


def partition_requests(requests):
    """Deterministic bounded batches; no filtering based on a build result."""
    batches, current = [], []
    for request in requests:
        if current and (len(current) >= MAX_BATCH_REQUESTS or len(_wire(current + [request])) > MAX_BATCH_BYTES):
            batches.append(current)
            current = []
        _require(len(_wire([request])) <= MAX_BATCH_BYTES, "single_request_exceeds_batch_byte_limit")
        current.append(request)
    if current:
        batches.append(current)
    return batches


def _pins():
    return bridge.producer_pins() | gate._pins() | {
        str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        str(Path(evaluation.__file__).resolve()): hashlib.sha256(Path(evaluation.__file__).read_bytes()).hexdigest()}


def run(summary_path, output, *, toolchain, lake_executable):
    summary_ref = evaluation.reference(summary_path)
    summary = evaluation.read(summary_ref)
    _require(summary.get("schema") == "legal-real-uscode-source-only-evaluation/v1", "source_only_evaluation_summary_required")
    plan = evaluation.read(summary["plan"])
    _require(plan.get("inference_fields") == ["source_text"] and plan.get("fitting_performed") is False,
             "source_only_frozen_evaluation_required")
    for reference in plan["implementation"]:
        _require(evaluation.reference(reference["path"]) == reference, "evaluation_producer_changed")
    manifest = evaluation.read(plan["manifest"])
    sources = evaluation.validate_manifest(manifest)
    index = evaluation.read(plan["checkpoint_index"])
    models = summary["models"]
    _require(len(models) == 18 and [item["name"] for item in models] == plan["model_names"], "complete_eighteen_model_inventory_required")
    _require(len(sources) == summary["source_views"] == plan["input_views"], "complete_source_view_inventory_required")
    _require(summary["model_source_slots"] == len(models) * len(sources), "model_source_denominator_differs")
    _require(len({s["id"] for s in sources}) == len(sources), "duplicate_source_view_identity")
    indexed = {item["name"]: item for item in index["checkpoints"]}
    _require(len(indexed) == 18 and set(indexed) == set(plan["model_names"]), "checkpoint_inventory_differs")
    pins = _pins()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    pilot_plan = evaluation.write(output / "plan.json", {"schema": SCHEMA, "evaluation_summary": summary_ref,
        "source_manifest": plan["manifest"], "families": list(FAMILIES),
        "modality_cues": CUES, "enabled_learned_trigger_required": True,
        "single_recognized_cue_required": True, "qualifier_interpretation_policy": "refuse_all_without_independent_review",
        "facet_binding_policy": "saved_predicted_character_intervals_exact_source_no_normalization_or_fallback",
        "batch_request_limit": MAX_BATCH_REQUESTS, "batch_input_byte_limit": MAX_BATCH_BYTES,
        "source_interpretation_candidate_only": True, "gold_labels_created": False,
        "inference_performed": False, "fitting_performed": False, "producer_pins": pins})
    slots, requests = [], []
    for model in models:
        _require(model["checkpoint"] == indexed[model["name"]]["checkpoint"] and model.get("exact_replay") is True,
                 "frozen_model_checkpoint_or_replay_differs")
        checkpoint_actual = evaluation.reference(model["checkpoint"]["path"])
        _require(checkpoint_actual == {key: model["checkpoint"][key] for key in checkpoint_actual}, "checkpoint_bytes_changed")
        generation = evaluation.read(model["generation"])
        _require(generation.get("target_access") is False and len(generation["rows"]) == len(sources),
                 "source_only_generation_or_coverage_differs")
        for source, prediction in zip(sources, generation["rows"], strict=True):
            _require(prediction.get("source_sha256") == source["source_sha256"], "generation_source_join_differs")
            common = {"model": model["name"], "checkpoint": model["checkpoint"], "source_id": source["id"],
                "source_sha256": source["source_sha256"], "source_kind": source["kind"], "legal_id": source["legal_id"],
                "edition": source["edition"], "source_document": source["document"],
                "source_document_char_start": source["char_start"], "source_document_char_end": source["char_end"],
                "generation": model["generation"], "prediction_sha256": _digest(prediction),
                "prediction_status": prediction.get("status"), "candidate_only": True,
                "source_semantics_verified": False, "complete_rule_coverage_verified": False}
            try:
                request = request_for_prediction(source, prediction, model["name"])
            except (ValueError, TypeError, KeyError) as error:
                slots.extend(common | {"family": family, "status": "refused", "reason": str(error)} for family in FAMILIES)
                continue
            for family in FAMILIES:
                full_request = request | {"family": family}
                record = common | {"family": family, "candidate_id": request["candidate"]["candidate_id"]}
                try:
                    prepared = gate.prepare_source_family_legal([full_request], toolchain=toolchain).to_dict()
                    _require(prepared["all_candidates_supported"], prepared["candidates"][0].get("reason", "native_preparation_refused"))
                    request_index = len(requests)
                    requests.append(full_request)
                    record.update(status="prepared", request_index=request_index, request_sha256=_digest(full_request),
                                  preparation=prepared["candidates"][0])
                except (ValueError, TypeError, KeyError) as error:
                    record.update(status="refused", reason=str(error))
                slots.append(record)
    _require(len(slots) == len(models) * len(sources) * len(FAMILIES), "family_slot_denominator_differs")
    requests_ref = evaluation.write(output / "requests.json", requests)
    decisions_ref = evaluation.write(output / "source-decisions.json", slots)
    batches = partition_requests(requests)
    freeze = evaluation.write(output / "requests-frozen.json", {"plan": pilot_plan, "requests": requests_ref,
        "source_decisions": decisions_ref, "batch_request_counts": [len(batch) for batch in batches],
        "batch_request_sha256": [_digest(batch) for batch in batches], "producer_pins": pins,
        "target": "legal", "no_reference_labels_read_or_created": True})
    builds, built = [], {}
    for index, batch in enumerate(batches):
        _require(_pins() == pins, "pilot_or_gate_producer_changed_before_build")
        receipt = gate.build_source_family_legal(batch, toolchain=toolchain, lake_executable=lake_executable,
            timeout_seconds=60, output_directory=output / f"build-{index:03d}").to_dict()
        reference = evaluation.reference(output / f"build-{index:03d}" / "source-family-receipt.json")
        builds.append({"receipt": reference, "request_count": len(batch),
                       "build_passed": receipt["build_passed"], "backend_executed": receipt["backend_executed"],
                       "command": receipt["command"], "manifest_coverage_passed": receipt["manifest_coverage_passed"]})
        for item in receipt["candidates"]:
            built[(item["candidate_id"], item["family"])] = {"receipt": reference,
                "module": item["module"], "status": "built" if receipt["build_passed"] else "build_failed"}
        print(json.dumps({"batch": index, "requests": len(batch), "build_passed": receipt["build_passed"]}), flush=True)
    for slot in slots:
        if slot["status"] == "prepared":
            slot.update(built[(slot["candidate_id"], slot["family"])])
    result_ref = evaluation.write(output / "results.json", slots)
    for reference in (summary_ref, requests_ref, decisions_ref):
        evaluation.read(reference)
    _require(_pins() == pins, "pilot_or_gate_producer_changed")
    counts = dict(Counter(row["status"] for row in slots))
    return evaluation.write(output / "summary.json", {"schema": SCHEMA, "plan": pilot_plan, "freeze": freeze,
        "results": result_ref, "evaluation_summary": summary_ref, "builds": builds,
        "source_views": len(sources), "models": len(models), "families": list(FAMILIES), "family_slots": len(slots),
        "status_counts": counts, "refusal_counts": dict(Counter(row["reason"] for row in slots if row["status"] == "refused")),
        "by_family": {family: dict(Counter(r["status"] for r in slots if r["family"] == family)) for family in FAMILIES},
        "by_model": {model["name"]: dict(Counter(r["status"] for r in slots if r["model"] == model["name"])) for model in models},
        "actual_native_build_calls": sum(row["backend_executed"] for row in builds),
        "all_requested_builds_passed": bool(builds) and all(row["build_passed"] for row in builds),
        "source_interpretation_candidate_only": True, "independent_gold_count": 0,
        "inference_performed": False, "fitting_performed": False, "source_semantics_verified": False,
        "training_qualified": False, "admitted": False,
        "limitations": ["Overlapping official source views and model seeds are correlated diagnostic observations.",
            "Only unchanged qualifier-free single-rule candidates with exact saved source facet intervals are tested.",
            "Unreviewed qualifier-bearing outputs are refused; no new qualifier meanings are invented.",
            "A recognized learned trigger cue is a binding check, not proof of statutory meaning or correct modality scope.",
            "A compiled candidate can omit other legal requirements or misinterpret its complete source.",
            "TDFOL here is a non-temporal ground deontic subset; DCEC covers no cognitive or event operators.",
            "No independent statutory reference annotations, model promotion or latent 8D/384D/768D qualification occurs."]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-summary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--lake-executable", required=True)
    args = parser.parse_args()
    print(run(args.evaluation_summary, args.output, toolchain=args.toolchain, lake_executable=args.lake_executable))
