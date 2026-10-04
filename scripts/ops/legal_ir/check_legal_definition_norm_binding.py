#!/usr/bin/env python3
"""Prepare or compile authored, unreviewed definition/norm binding fixtures."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_source_definition_norm_lake as gate
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context


def fixture_request(modality="O", family="deontic_fol", *, section="1", edition=2024, norm_suffix="", body_operator="any"):
    """No downloaded or authentic statutory content: deliberately authored HTML."""
    cue = bridge.CUES[modality]
    raw = (f'<meta charset="utf-8"><h3 class="section-head">§{section}. Authored binding fixture</h3>'
           '<p class="statutory-body">(a) Definitions. In this section:</p>'
           '<p class="statutory-body-1em">(1) The term "covered filer" means registered or licensed.</p>'
           f'<p class="statutory-body">(b) Each covered filer {cue} register.{norm_suffix}</p>').encode()
    url = f"https://www.govinfo.gov/content/pkg/USCODE-{edition}-title40/html/USCODE-{edition}-title40-sec{section}.htm"
    doc = context.extract_document(raw, url=url, edition=edition, legal_id=f"usc:us:40:{section}")
    text = doc["document_text"]
    def span(literal, after=0):
        start = text.index(literal, after)
        return {"char_start": start, "char_end": start + len(literal), "text": literal}
    definition_request = {"document": doc, "raw_html_base64": base64.b64encode(raw).decode(), "family": "fol",
        "declaration": {"declaration_id": "authored-category", "profile": bridge.definitions.PROFILE,
            "interpretation_status": "unreviewed_caller_declaration", "paragraph_index": 1,
            "scope_span": span("In this section:"), "definition_cue": span("means"), "head": span("covered filer"),
            "body": {"op": body_operator, "operands": [{"op": "atom", "span": span("registered")},
                                                        {"op": "atom", "span": span("licensed")}]}}}
    definition = bridge.definitions.prepare_definition(definition_request)
    paragraph = doc["paragraphs"][2]
    start = paragraph["char_start"]
    norm = {"norm_id": "authored-norm-" + modality, "profile": bridge.PROFILE,
        "interpretation_status": "unreviewed_caller_declaration",
        **{key: doc[key] for key in ("document_id", "document_text_sha256", "legal_id", "edition")},
        "paragraph_index": 2, "source_span": span(f"Each covered filer {cue} register.", start),
        "quantifier_span": span("Each", start), "category_span": span("covered filer", start),
        "modality_span": span(cue, start), "action_span": span("register", start), "modality": modality,
        "variable": "x", "definition_head_symbol": definition["native_ast"]["formula"]["left"]["name"],
        "activation_scope": bridge.ACTIVATION, "modal_context": None}
    return {"definition_request": definition_request, "norm_declaration": norm, "family": family,
        "source_provenance": {"kind": "authored_official_shape_fixture", "authenticity_verified": False,
                              "independently_reviewed": False, "training_admitted": False}}


def file_ref(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def main(args):
    output = Path(args.output).resolve()
    bridge.require(not output.exists(), "fresh evidence directory required")
    if args.prepare_requests:
        bridge.require(args.requests is None and args.freeze is None and args.lake_executable is None,
                       "request preparation cannot also compile")
        requests = [fixture_request(modality, family) for modality in "OPF" for family in bridge.FAMILIES]
        output.mkdir(parents=True)
        (output / "requests.json").write_text(json.dumps(requests, indent=2, sort_keys=True) + "\n")
        reports = [bridge.prepare_definition_norm(request) for request in requests]
        (output / "declared-bindings.json").write_text(json.dumps(reports, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"requests": file_ref(output / "requests.json"), "authored_fixture": True}))
        return
    bridge.require(args.requests and args.freeze and args.lake_executable,
                   "frozen requests, implementation freeze and exact native Lake executable required")
    freeze = json.loads(Path(args.freeze).read_text())
    bridge.require(freeze["requests"] == file_ref(args.requests), "requests differ from prospective freeze")
    for pin in freeze["immutable_files"]:
        bridge.require(file_ref(pin["path"]) == pin, "frozen source or test bytes changed")
    requests = json.loads(Path(args.requests).read_text())
    bridge.require(len(requests) == 6 and {(r["norm_declaration"]["modality"], r["family"]) for r in requests}
                   == {(m, f) for m in "OPF" for f in bridge.FAMILIES}, "all six predeclared family/modality requests required")
    receipt = gate.build(requests, toolchain=args.toolchain, lake_executable=args.lake_executable,
                         output_directory=output / "native-build")
    summary = {"schema": "legal-definition-norm-fixture-qualification/v1", "freeze": file_ref(args.freeze),
        "requests": file_ref(args.requests), "receipt": file_ref(output / "native-build/receipt.json"),
        "requests_count": 6, "actual_backend_calls": int(receipt["backend_executed"]),
        "native_build_passed": receipt["build_passed"], "compiled_modules": receipt["compiled_modules"],
        "real_statutory_sources": 0, "authored_official_shape_fixtures": 6, "model_inference": False,
        "training": False, "source_semantics_verified": False, "source_authenticity_verified": False,
        "independently_reviewed": False, "all_logic_families_supported": False}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    bridge.require(receipt["build_passed"], "native composition build failed; retained attempt evidence")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-requests", action="store_true")
    parser.add_argument("--requests")
    parser.add_argument("--freeze")
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake-executable")
    parser.add_argument("--toolchain", default="leanprover/lean4:v4.34.1")
    main(parser.parse_args())
