#!/usr/bin/env python3
"""Pin official historical sections and replay source-only decoders for review.

No fitting, selection, automatic reference labels, or statutory accuracy claim.
The reviewed input manifest is frozen before decoder inference.  Paragraph,
enclosing block, and full codified-body views intentionally overlap, and are
diagnostic views, not independent test examples or train/test partitions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context

SECTIONS = {
    "18:4004": "title18-partIII-chap301-sec4004",
    "18:3284": "title18-partII-chap213-sec3284",
    "10:7657": "title10-subtitleB-partIV-chap771-sec7657",
    "40:3318": "title40-subtitleII-partA-chap33-sec3318",
    "10:4873": "title10-subtitleA-partV-subpartI-chap385-subchapIII-sec4873",
}


def reference(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def write(path, value):
    path = Path(path)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return reference(path)


def read(reference_):
    actual = reference(reference_["path"])
    if actual != {k: reference_[k] for k in actual}:
        raise ValueError("artifact bytes differ")
    return json.loads(Path(reference_["path"]).read_text())


def make_sources(document, document_ref):
    rows = []
    text = document["document_text"]
    doc_id = document["document_id"]
    def add(kind, start, end, local_id, subsection):
        value = text[start:end]
        rows.append({"id": doc_id + ":" + local_id, "source_text": value,
                     "source_sha256": context.sha(value), "kind": kind,
                     "document": document_ref, "document_id": doc_id,
                     "legal_id": document["legal_id"], "section_heading": document["heading"],
                     "edition": document["edition"], "char_start": start, "char_end": end,
                     "subsection_path": subsection, "split": "exposed_diagnostic_only",
                     "independent_reference": None, "training_qualified": False})
    body = [p for p in document["paragraphs"] if p["kind"] == "codified_body"]
    for row in body:
        add("paragraph", row["char_start"], row["char_end"], f"paragraph-{row['paragraph_index']}", row["subsection_path"])
    for block in document["blocks"]:
        if block["descendant_paragraphs"]:
            add("enclosing_block", block["char_start"], block["char_end"], f"block-{block['paragraph_index']}", block["subsection_path"])
    add("full_codified_body", body[0]["char_start"], body[-1]["char_end"], "codified-body", None)
    # Deterministically retain one editorial/historical paragraph per document
    # as a classification control. It is not labelled legally meaningless.
    notes = [p for p in document["paragraphs"] if p["kind"] == "notes_or_other"]
    if notes:
        row = notes[0]
        add("notes_control", row["char_start"], row["char_end"], f"notes-{row['paragraph_index']}", None)
    return rows


def prepare(output):
    import requests
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    documents, sources, receipts = [], [], []
    for section, suffix in SECTIONS.items():
        title = section.split(":")[0]
        url = f"https://www.govinfo.gov/content/pkg/USCODE-2024-title{title}/html/USCODE-2024-{suffix}.htm"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        if response.url != url:
            raise ValueError("unexpected source redirect")
        name = section.replace(":", "-")
        path = output / (name + ".html")
        with path.open("xb") as stream:
            stream.write(response.content)
        document = context.extract_document(response.content, url=url, edition=2024, legal_id="usc:us:" + section)
        context.validate_document(document, response.content)
        document_ref = write(output / (name + ".json"), document)
        documents.append({"document": document_ref, "raw_html": reference(path)})
        sources.extend(make_sources(document, document_ref))
        receipts.append({"url": url, "status": response.status_code, "etag": response.headers.get("ETag"),
                         "last_modified": response.headers.get("Last-Modified"), "raw_html": reference(path),
                         "retrieved_utc": datetime.now(timezone.utc).isoformat()})
    source_ref = write(output / "source-inputs.json", sources)
    return write(output / "manifest.json", {"schema": "legal-official-uscode-diagnostic-manifest/v1",
        "documents": documents, "receipts": receipts, "sources": source_ref,
        "counts": {"documents": len(documents), "views": len(sources),
                   "view_kinds": dict(Counter(s["kind"] for s in sources)),
                   "distinct_texts": len({s["source_sha256"] for s in sources})},
        "selection": "Five explicitly listed edition-fixed sections; every codified paragraph, descendant block, full codified body and first note paragraph.",
        "views_are_independent_examples": False, "source_context_closed": False,
        "statutory_accuracy_available": False, "training_qualified": False,
        "implementation": [reference(__file__), reference(context.__file__)]})


def validate_manifest(manifest):
    if manifest.get("schema") != "legal-official-uscode-diagnostic-manifest/v1":
        raise ValueError("official diagnostic manifest required")
    documents = {}
    for item in manifest["documents"]:
        document = read(item["document"])
        if reference(item["raw_html"]["path"]) != item["raw_html"]:
            raise ValueError("official HTML changed")
        context.validate_document(document, Path(item["raw_html"]["path"]).read_bytes())
        if document["document_id"] in documents:
            raise ValueError("duplicate document identity")
        documents[document["document_id"]] = (document, item["document"])
    if len(documents) != len(SECTIONS) or {d["legal_id"] for d, _ in documents.values()} != {"usc:us:" + s for s in SECTIONS}:
        raise ValueError("exact declared five-section pilot inventory required")
    expected = [row for document, ref in documents.values() for row in make_sources(document, ref)]
    sources = read(manifest["sources"])
    if sources != expected:
        raise ValueError("source inventory differs from official context")
    counts = {"documents": len(documents), "views": len(sources),
              "view_kinds": dict(Counter(s["kind"] for s in sources)),
              "distinct_texts": len({s["source_sha256"] for s in sources})}
    if manifest["counts"] != counts or manifest["training_qualified"] is not False or manifest["statutory_accuracy_available"] is not False:
        raise ValueError("declared source denominators or authority claims differ")
    for pin in manifest["implementation"]:
        if reference(pin["path"]) != pin:
            raise ValueError("official context implementation changed")
    return sources


def evaluate(manifest_path, checkpoint_index, output):
    import torch
    from scripts.ops.legal_ir import run_legal_grounding_experiment as shared
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as consistency
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    torch.set_num_threads(1)
    manifest_ref, index_ref = reference(manifest_path), reference(checkpoint_index)
    manifest, index = read(manifest_ref), read(index_ref)
    sources = validate_manifest(manifest)
    if index["schema"] != "legal-clause-consistency-selected-checkpoint-index/v1":
        raise ValueError("frozen selected checkpoint index required")
    models = index["checkpoints"]
    if len(models) != 18 or len({m["name"] for m in models}) != 18:
        raise ValueError("all eighteen frozen model slots required")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    plan = write(output / "plan.json", {"schema": "legal-real-uscode-source-only-evaluation/v1",
        "manifest": manifest_ref, "checkpoint_index": index_ref,
        "model_names": [m["name"] for m in models], "input_views": len(sources),
        "runtime": {"python_executable": sys.executable, "python_version": sys.version,
                    "torch_version": torch.__version__, "torch_threads": torch.get_num_threads()},
        "inference_fields": ["source_text"], "context_available_as_sidecar_only": True,
        "fitting_performed": False, "selection_performed": False,
        "implementation": [reference(__file__), reference(context.__file__),
                           reference(shared.__file__), reference(consistency.__file__), reference(mixed.__file__)]})
    model_reports, by_source = [], {s["id"]: [] for s in sources}
    for item in models:
        module, cls = (consistency, consistency.ConsistencyDecoder) if item["decoder_kind"] == "consistency" else (mixed, mixed.MixedReplayDecoder)
        checkpoint = module.load_checkpoint(item["checkpoint"]["path"], expected_sha256=item["checkpoint"]["sha256"])
        decoder = cls(checkpoint)
        inputs = [{k: row[k] for k in ("id", "source_text", "source_sha256")} for row in sources]
        result = shared.generate(decoder, inputs)
        replay = shared.generate(decoder, inputs)
        if result != replay:
            raise ValueError("source-only numerical replay differs")
        generation = write(output / (item["name"] + "-generation.json"), result)
        diagnostics = []
        for source, prediction in zip(sources, result["rows"], strict=True):
            diagnostic = context.inspect_prediction(source, prediction)
            diagnostics.append(diagnostic)
            by_source[source["id"]].append({"model": item["name"], "status": prediction["status"],
                "canonical_ir_sha256": hashlib.sha256(json.dumps(prediction.get("canonical_ir"), sort_keys=True).encode()).hexdigest(),
                "unretained_literal_cues": len(diagnostic["unretained_cues"])})
        diagnostic_ref = write(output / (item["name"] + "-diagnostics.json"), diagnostics)
        counts = Counter(row["status"] for row in result["rows"])
        report = {"name": item["name"], "checkpoint": item["checkpoint"], "generation": generation,
                  "diagnostics": diagnostic_ref, "decoded": counts["decoded"], "abstained": counts["abstained"],
                  "by_kind": {kind: dict(Counter(p["status"] for s, p in zip(sources, result["rows"], strict=True)
                                                 if s["kind"] == kind)) for kind in sorted({s["kind"] for s in sources})},
                  "exact_replay": True, "reference_accuracy": None, "latent_dimensions": 0}
        model_reports.append(report)
        print(json.dumps({"model": item["name"], "decoded": counts["decoded"], "input_views": len(sources)}), flush=True)
    read(manifest_ref); read(index_ref)
    for pin in read(plan)["implementation"]:
        if reference(pin["path"]) != pin:
            raise ValueError("evaluation implementation changed")
    return write(output / "summary.json", {"schema": "legal-real-uscode-source-only-evaluation/v1", "plan": plan,
        "models": model_reports, "source_diagnostics": by_source, "source_views": len(sources),
        "model_source_slots": len(models) * len(sources), "replayed_records": len(models) * len(sources),
        "reference_accuracy_available": False, "independent_gold_count": 0,
        "fitting_performed": False, "training_qualified": False, "source_semantics_verified": False,
        "limitations": ["Overlapping source views are correlated diagnostic probes, not an accuracy benchmark.",
                        "Only source strings reach the decoder; recovered context sidecars are review evidence.",
                        "All checkpoints are frozen source-only decoders; 8D/384D/768D latents are not tested here.",
                        "Historical 2024 sources are not claims about current statutory applicability.",
                        "Decoding and literal cue retention do not establish statutory meaning."]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "evaluate"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--checkpoint-index")
    args = parser.parse_args()
    if args.phase == "prepare":
        print(prepare(args.output))
    else:
        if not args.manifest or not args.checkpoint_index:
            parser.error("evaluate requires --manifest and --checkpoint-index")
        print(evaluate(args.manifest, args.checkpoint_index, args.output))
