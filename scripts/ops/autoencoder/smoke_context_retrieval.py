#!/usr/bin/env python3
"""Offline authored context-retrieval smoke; no source admissions or downloads."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def run(output):
    from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan, SourceReviewStatus
    from ipfs_datasets_py.logic.formalization.context_resolution import (
        ContextSpan, BoundedContextIndex, prepare_context_bundle, validate_context_bundle)
    from ipfs_datasets_py.logic.formalization.context_link_obligations import (
        prepare_context_link_obligation, validate_context_link_obligation)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    rows, documents = [], []

    def add(document, text, excerpts):
        ref = SourceRef(ref_id="ref:" + document, source_uri="fixture://" + document,
            source_id=document, source_revision="provisional-context-demo/v1",
            content_sha256=hashlib.sha256(text.encode()).hexdigest(), review_status=SourceReviewStatus.TRUSTED_FIXTURE)
        documents.append({"source_ref": ref.to_dict(), "source_text": text})
        for key, excerpt in excerpts:
            start = text.encode().index(excerpt.encode())
            rows.append(ContextSpan.from_source(source_ref=ref, source_text=text, partition="authored-demo",
                span=SourceSpan(key, ref.ref_id, start, start + len(excerpt.encode()))))

    legal_context = "In this authored fixture the deadline begins on receipt of notice."
    legal_text = "The custodian must publish the record within ten days."
    add("legal-fixture", legal_context + "\n" + legal_text,
        [("legal-context", legal_context), ("legal-selected", legal_text)])
    definition = "This authored notice means a synthetic request; this is not a statute."
    add("definition-fixture", definition, [("notice-definition", definition)])
    ui_context = "Authored policy: confirmation and invocation must share the same action and request identity."
    ui_text = "Confirm before invoking publish_ledger."
    add("ui-fixture", ui_context + "\n" + ui_text, [("ui-policy", ui_context), ("ui-selected", ui_text)])
    index = BoundedContextIndex(rows, edges=[
        {"source_span_id": "legal-selected", "target_span_id": "legal-context", "relation": "parent"},
        {"source_span_id": "legal-context", "target_span_id": "notice-definition", "relation": "definition"},
        {"source_span_id": "ui-selected", "target_span_id": "ui-policy", "relation": "policy"}],
        revision="authored-context-demo/v1")
    results = []
    for key, question, sort, projections in [
        ("legal-selected", "deadline begins receipt notice", "temporal_anchor", ["deontic", "temporal"]),
        ("ui-selected", "confirmation invocation request identity", "confirmation_policy", ["ui_ux_ir:tdfol"])]:
        tick = perf_counter()
        bundle = prepare_context_bundle(index, source_span_id=key,
            slots=[{"slot_id": "missing-context", "question": question, "sort": sort, "projection_ids": projections}])
        validate_context_bundle(bundle, index=index)
        candidate = "legal-context" if key == "legal-selected" else "ui-policy"
        plan = prepare_context_link_obligation(bundle, index=index, slot_id="missing-context",
            candidate_span_id=candidate, proposed_binding={"source_span_id": candidate, "needs_review": True},
            relation="deadline_trigger" if key == "legal-selected" else "application_policy")
        validate_context_link_obligation(plan, bundle=bundle, index=index)
        (destination / (key + "-link-plan.json")).write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        (destination / (key + ".json")).write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
        results.append({"source_span_id": key, "candidate_count": len(bundle["slots"][0]["candidates"]),
            "wall_seconds_with_replay": perf_counter() - tick, "telemetry": bundle["telemetry"],
            "source_resolved_slot_count": bundle["source_resolved_slot_count"], "bundle_sha256": bundle["bundle_sha256"]})
    summary = {"schema": "authored-context-retrieval-smoke/v1", "source_count": 2,
        "context_span_count": len(rows), "results": results, "wall_seconds": perf_counter() - started,
        "index_sha256": index.index_sha256, "scope": "authored local BM25/neighbor/explicit-graph retrieval",
        "cold_index": True, "workers": 1, "bridge_evaluate_executed": False,
        "proof_executed": False, "admitted": False, "source_semantics_verified": False,
        "weights_downloaded": False, "model_training_executed": False}
    (destination / "inputs.json").write_text(json.dumps({"documents": documents, "index": index.to_dict()}, indent=2, sort_keys=True) + "\n")
    (destination / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
