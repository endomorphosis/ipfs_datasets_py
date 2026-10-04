#!/usr/bin/env python3
"""Retrieve authored slot manifests, bind them, and build all Legal/UI views.

Both provisional and cited interpretations remain assumptions. No corpus law,
application policy, observed event or trained checkpoint is qualified here.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from smoke_provisional_context_fixtures import _tool_pins, _lake_counts


def _write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _values(domain, inputs):
    if domain == "legal_ir":
        return {
            "legal.temporal_anchor": {"origin": "caller_supplied_evaluation_time",
                "binding_kind": "evaluation_origin_declared_as_trigger", "trigger_ref": "fixture:notice_receipt"},
            "legal.temporal_model": {"temporal_kind": "within_duration", "quantity": 10, "unit": "day",
                "time_domain": "discrete_nat", "lower_inclusive": True, "upper_inclusive": True},
            "legal.scope": {"norm_projection_id": "legal-ir/modal-family/deontic/v3",
                "body_projection_id": "legal-ir/modal-family/temporal/v3", "body_relation": "temporal_view_is_auxiliary_body_not_fact",
                "enclosing_modal_symbol": "O", "activation_scope": "all_conditions_at_evaluation_origin",
                "exception_scope": "activation_time_waiver", "independent_event_fact": False},
        }
    return {
        "ui.confirmation_policy": {"action_ids": sorted(b["action_id"] for b in inputs["ui_training_row"]["bindings"]),
            "event_order": "strict_sequence_position", "clock_order": "nondecreasing", "time_domain": "discrete_nat_ticks",
            "max_age_ticks": 10, "freshness_upper_inclusive": True, "correlation": "action_request_token",
            "cancellation": "since_latest_confirmation", "consumption": "every_prior_invocation_consumes_token"},
        "ui.trace_scope": {"trace_scope": "finite_observed_prefix", "unobserved_future": "unknown",
            "origin": "caller_supplied_sequence_position", "event_occurrences_attested": False, "whole_workflow_verified": False},
    }


def _context(domain, inputs):
    from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan, SourceReviewStatus
    from ipfs_datasets_py.logic.formalization.context_resolution import ContextSpan, BoundedContextIndex, prepare_context_bundle
    from ipfs_datasets_py.logic.formalization.context_slot_manifests import MANIFEST_SCHEMA
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v2 as sources
    from ipfs_datasets_py.logic.formalization.autoencoder import context_declaration_bridge as bridge
    raw, _, _ = sources._source_bytes(domain, inputs)
    source = sources.supplemental_source_ref(domain, **inputs)
    selected = ContextSpan.from_source(source_ref=source, span=SourceSpan("selected", source.ref_id, 0, len(raw)),
        source_text=raw.decode(), partition="authored-context-smoke")
    values = _values(domain, inputs)
    cited_values = deepcopy(values)
    if domain == "legal_ir":
        cited_values["legal.temporal_anchor"]["trigger_ref"] = "retrieved_manifest:notice_receipt"
    else:
        cited_values["ui.confirmation_policy"]["max_age_ticks"] = 12
    projections = list(bridge.LEGAL_PROJECTIONS if domain == "legal_ir" else bridge.UI_PROJECTIONS)
    slots = [{"slot_id": key, "sort": sort, "question": key.replace(".", " ").replace("_", " ") + " declared context policy",
        "projection_ids": projections} for key, sort in bridge.SLOTS[domain].items()]
    spans, edges, documents = [selected], [], [{"source_ref": source.to_dict(), "text": raw.decode()}]
    for number, slot in enumerate(slots):
        manifest = {"schema": MANIFEST_SCHEMA, "selected_source_ref": source.to_dict(),
            "scope_note": "Authored integration-test declaration for the exact selected source; no claim about actual law or application policy.",
            "slots": [{k: slot[k] for k in ("slot_id", "sort", "projection_ids")} | {"value": cited_values[slot["slot_id"]]}]}
        text = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        key = "context:" + str(number)
        ref = SourceRef("ref:" + domain + ":" + str(number), "fixture://context-manifest/" + domain + "/" + str(number),
            domain + ":policy:" + str(number), "authored-context-manifest/v1", hashlib.sha256(text.encode()).hexdigest(),
            review_status=SourceReviewStatus.TRUSTED_FIXTURE)
        spans.append(ContextSpan.from_source(source_ref=ref, source_text=text, partition="authored-context-smoke",
            span=SourceSpan(key, ref.ref_id, 0, len(text.encode()))))
        edges.append({"source_span_id": "selected", "target_span_id": key, "relation": "policy"})
        documents.append({"source_ref": ref.to_dict(), "text": text})
    index = BoundedContextIndex(spans, edges=edges, revision="authored-context-handoff/v1")
    bundle = prepare_context_bundle(index, source_span_id="selected", slots=slots,
        fixtures=[{"slot_id": key, "value": value, "rationale": "Explicit temporary integration-test premise."}
            for key, value in values.items()])
    return index, bundle, values, documents


def run(output, lake, java, jar):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import provisional_context_panel as panel
    from ipfs_datasets_py.logic.formalization.autoencoder import projection_context_audit as audit
    from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as native
    from ipfs_datasets_py.logic.formalization.autoencoder import context_declaration_bridge as bridge
    from ipfs_datasets_py.logic.formalization.context_slot_bindings import prepare_context_binding
    from ipfs_datasets_py.logic.formalization.context_slot_manifests import prepare_manifest_binding_proposals, bind_manifest_proposals
    destination = Path(output).absolute()
    destination.mkdir(parents=True, exist_ok=False)
    before = _tool_pins(lake, java, jar)
    started, results, executions = perf_counter(), {}, []
    for domain in panel.DOMAINS:
        directory = destination / domain
        directory.mkdir()
        case = panel.prepare_companion(domain)
        inputs = case["original_source_inputs"]
        negative = native.prepare_native_family_lean(case["original_report"], source_inputs=inputs)
        blockers = {row["projection_id"]: row["reason"] for row in negative["per_projection"] if not row["semantic_lowering_supported"]}
        if blockers != audit.BLOCKERS[domain]:
            raise ValueError("original_negative_control_changed")
        index, bundle, values, documents = _context(domain, inputs)
        proposals = prepare_manifest_binding_proposals(bundle, index=index)
        cited = bind_manifest_proposals(proposals, bundle=bundle, index=index,
            reviewer_record={"reviewer_id": "authored-context-smoke", "review_method": "machine_review_declared",
                "rationale": "Exact structured declarations in authored fixture manifests; not authenticated source review."})
        fixture = tuple(prepare_context_binding(bundle, index=index, slot_id=key, mode="fixture_assumption", value=value)
            for key, value in values.items())
        _write(directory / "context-inputs.json", {"documents": documents, "index": index.to_dict()})
        _write(directory / "context-bundle.json", bundle)
        _write(directory / "manifest-proposals.json", proposals)
        _write(directory / "original-negative-preparation.json", negative)
        _write(directory / "original-targets.json", case["original_report"])
        variants = {}
        for label, bindings in (("fixture", fixture), ("cited", cited)):
            tick = perf_counter()
            prepared = bridge.prepare_contextual_targets(domain, source_inputs=inputs, context_index=index,
                context_bundle=bundle, bindings=bindings)
            _write(directory / (label + "-bindings.json"), [binding.to_dict() for binding in bindings])
            _write(directory / (label + "-preparation.json"), prepared.to_dict())
            _write(directory / (label + "-targets.json"), prepared.report)
            checked = bridge.build_contextual_family_lake(prepared, source_inputs=inputs, context_index=index,
                context_bundle=bundle, bindings=bindings, lake_executable=lake,
                output_directory=directory / (label + "-native"), java_executable=java, tla2tools_jar=jar)
            receipt = checked["receipt"]
            _write(directory / (label + "-execution.json"), receipt)
            native_receipt = receipt["native"]
            executions.append(native_receipt["execution"])
            rows = native_receipt["per_projection"]
            passed = all(row["parser_status"] == row["lake_status"] == "passed" for row in rows)
            if not passed or len(rows) != len(case["original_report"]["projections"]):
                raise ValueError("context_handoff_omitted_or_failed_projection")
            if receipt["training_gate"]["strict_training_allowed"] is not False:
                raise ValueError("context_handoff_changed_training_authority")
            variants[label] = {"projection_count": len(rows), "passed_projection_count": sum(
                row["parser_status"] == row["lake_status"] == "passed" for row in rows),
                "contextual_target_sha256": prepared.to_dict()["contextual_target_sha256"],
                "native_report_sha256": prepared.report["report_sha256"],
                "wall_seconds": perf_counter() - tick, "training_allowed": False,
                "native_library": native_receipt["library"], "actual_lake_build": native_receipt["execution"]["backend_executed"],
                "additional_syntax_checks": [row["additional_syntax_checks"] for row in rows if row.get("additional_syntax_checks")]}
            if domain == "ui_ux_ir":
                actual_age = prepared.report["ui_confirmation_inputs"][0]["formulas"][0]["max_age_ticks"]
                if actual_age != (10 if label == "fixture" else 12):
                    raise ValueError("retrieved_UI_policy_value_did_not_reach_projection")
                variants[label]["projected_max_age_ticks"] = actual_age
        if variants["fixture"]["contextual_target_sha256"] == variants["cited"]["contextual_target_sha256"]:
            raise ValueError("context_target_cache_identity_ignored_new_bindings")
        results[domain] = {"original_blockers": blockers, "slot_count": len(values), "variants": variants,
            "context_change_invalidates_target_identity": True, "original_source_preserved": True}
        print(json.dumps({"domain": domain, "original_blockers": len(blockers), "variants": variants}), flush=True)
    after = _tool_pins(lake, java, jar)
    if before != after:
        raise ValueError("native_tool_identity_changed")
    summary = {"schema": "context-projection-handoff-smoke/v1", "results": results,
        "source_count": 2, "interpretation_variants": 4, "unique_native_projection_count": 27,
        "total_projection_checks": sum(v["projection_count"] for d in results.values() for v in d["variants"].values()),
        "original_blocker_count": sum(len(d["original_blockers"]) for d in results.values()),
        "tool_pins_before": before, "tool_pins_after": after, **_lake_counts(executions),
        "wall_seconds": perf_counter() - started, "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "integration_passed": True, "source_semantics_verified": False, "admitted": False,
        "qualified": False, "training_executed": False, "weights_downloaded": False,
        "scope": "authored retrieval manifests to explicit slot bindings to native conditional projections"}
    _write(destination / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake", required=True)
    parser.add_argument("--java-executable", required=True)
    parser.add_argument("--tla2tools-jar", required=True)
    args = parser.parse_args()
    run(args.output, args.lake, args.java_executable, args.tla2tools_jar)
