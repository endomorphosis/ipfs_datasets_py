#!/usr/bin/env python3
"""Record complete source-routing decisions without fitting or reference labels."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal import legal_statutory_routing as routing
from scripts.ops.legal_ir import evaluate_legal_uscode_fidelity as frozen


def route_manifest(manifest_path, output):
    manifest_pin = routing.file_ref(manifest_path)
    manifest = routing.read_ref(manifest_pin)
    sources = frozen.validate_manifest(manifest)
    documents = {}
    for item in manifest["documents"]:
        document = routing.read_ref(item["document"])
        if routing.file_ref(item["raw_html"]["path"]) != item["raw_html"]:
            raise ValueError("official HTML reference changed")
        documents[document["document_id"]] = (document, Path(item["raw_html"]["path"]).read_bytes())
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    pins = [routing.file_ref(__file__), routing.file_ref(routing.__file__), routing.file_ref(frozen.__file__), routing.file_ref(routing.context.__file__)]
    plan = frozen.write(output / "plan.json", {"schema": "legal-uscode-routing-plan/v1", "manifest": manifest_pin,
                        "implementation": pins, "source_views": len(sources), "target_access": False,
                        "fitting_performed": False, "threshold_selection_performed": False})
    decisions = [routing.route_source(source, *documents[source["document_id"]]) for source in sources]
    if [r["source_id"] for r in decisions] != [s["id"] for s in sources]:
        raise ValueError("routing changed source denominator/order")
    if decisions != [routing.route_source(source, *documents[source["document_id"]]) for source in sources]:
        raise ValueError("deterministic routing replay differs")
    rows_pin = frozen.write(output / "decisions.json", decisions)
    for pin in pins + [manifest_pin]:
        if routing.file_ref(pin["path"]) != pin:
            raise ValueError("routing input or implementation changed")
    summary = {"schema": "legal-uscode-routing-summary/v1", "plan": plan, "decisions": rows_pin,
               "source_views": len(sources), "routed_views": len(decisions),
               "distinct_source_texts": len({s["source_sha256"] for s in sources}),
               "route_counts": dict(Counter(r["route"] for r in decisions)),
               "decoder_eligible": sum(r["decoder_eligible"] for r in decisions),
               "by_source_kind": {kind: dict(Counter(r["route"] for s, r in zip(sources, decisions, strict=True) if s["kind"] == kind)) for kind in sorted({s["kind"] for s in sources})},
               "context_resolved": 0, "independent_gold": 0, "exact_replay": True,
               "fitting_performed": False, "training_qualified": False,
               "limitations": ["All views remain in the denominator; definitions, notes and abstentions are retained.",
                               "These are five exposed 2024 sections, not a whole-corpus random sample or accuracy benchmark.",
                               "Overlapping paragraph/block/full-body views are correlated.",
                               "Valid-norm false-rejection and unsupported acceptance require separately authored controls."]}
    return frozen.write(output / "summary.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(route_manifest(args.manifest, args.output)))
