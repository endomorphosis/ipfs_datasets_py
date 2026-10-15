"""Explicit engineering probe of retained §101 bytes; not a legal review.

Run only after source qualification. No product owner is imported at module load.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[4]
HISTORY = Path("/home/barberb/lift_coding/artifacts/legal-corpus-source-structured-sampling-20261015-01")
INPUTS = {
    "source.html": (HISTORY / "official-2024-title10-section101.html", 98879,
                    "4e8d017794220f192668d5313fc537fbb7140652ac4a00faaf93a6c921c2c08b"),
    "acquisition-descriptor.json": (HISTORY / "official-section101-acquisition-descriptor-v01.json", 926,
                    "00cdd9452ada9005ad30fa4e548a98a73914324cb99ec3d10c2911a878f86bfe"),
    "historical-sampling-report.json": (HISTORY / "actual-section101-01/sampling-report.json", 2790275,
                    "173e3995b8628c76fbffcff1e1d77aad8d22d32ef84c3335e3ccc1c05af836d6"),
}
DESCRIPTOR_CANONICAL = "431a4da4edc59bed35841256a9e13a56c52715b227e5d0a036b55ae255df07c8"
HISTORICAL_SAMPLER_CANONICAL = "be524c7822f5e19a16ee56740560b19b0311001c553bd7ca9c2c9ed989af98b1"
REQUIREMENTS = {"definition", "authority", "antecedent", "shared_qualifier",
                "temporal_origin", "referenced_provision"}
BODY = "the Army, Navy, Air Force, Marine Corps, Space Force, and Coast Guard."


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def metadata(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def save(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)


def check(receipt, name, condition):
    receipt["checks"].append({"check": name, "passed": bool(condition)})
    if not condition:
        raise RuntimeError(name)


def opened_contexts(rows):
    return bool(rows) and all(row["availability"] == "required_unavailable"
        and len(row["missing_requirements"]) == 6
        and set(row["missing_requirements"]) == REQUIREMENTS for row in rows)


def run(output, receipt):
    sys.path.insert(0, str(REPOSITORY))
    from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
    from ipfs_datasets_py.logic.autoformal import legal_source_definition_bridge_v2 as bridge
    from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as adapter
    from ipfs_datasets_py.logic.autoformal import corpus_graph_exchange as exchange

    check(receipt, "product owners loaded from selected checkout", all(
        Path(owner.__file__).resolve().is_relative_to(REPOSITORY)
        for owner in (sampler, bridge, adapter, exchange)))
    blobs = {name: path.read_bytes() for name, (path, _, _) in INPUTS.items()}
    for name, (_, length, digest) in INPUTS.items():
        check(receipt, "independent historical file pin: " + name,
              len(blobs[name]) == length and sha(blobs[name]) == digest)
        save(output / name, blobs[name])
    raw = blobs["source.html"]
    descriptor = json.loads(blobs["acquisition-descriptor.json"])
    check(receipt, "descriptor full canonical pin", sha(wire(descriptor)) == DESCRIPTOR_CANONICAL)
    historical_sampling = json.loads(blobs["historical-sampling-report.json"])
    check(receipt, "historical sampler full canonical pin",
          sha(wire(historical_sampling)) == HISTORICAL_SAMPLER_CANONICAL)
    trusted = dict(descriptor=descriptor, expected_descriptor_sha256=DESCRIPTOR_CANONICAL,
                   expected_raw_sha256=INPUTS["source.html"][2], expected_raw_bytes=len(raw))
    sampling = sampler.prepare_source_sampling(raw, **trusted)
    sampling_sha = sampler.source_sampling_report_sha256(sampling)
    check(receipt, "fresh whole-source sampler replay", sampler.validate_source_sampling(
        sampling, raw, expected_report_sha256=sampling_sha, **trusted)["status"] == "whole_source_blocks_prepared")
    save(output / "sampling-report.json", wire(sampling))
    counts = sampling["counts"]
    check(receipt, "all 560 blocks and 134/426 candidate-control population retained",
          counts["blocks"] == counts["units"] == 560 and counts["records"] == 1681
          and counts["strata"] == {"candidate_statute_paragraph": 134, "retained_context_control": 426})
    contexts = [r for r in sampling["records"] if r["schema"] == "legal-corpus-context-declaration/v1"]
    units = [r for r in sampling["records"] if r["schema"] == sampler.UNIT_SCHEMA]
    check(receipt, "complete historical source-record population preserved",
          sampling["records"] == historical_sampling["records"]
          and sampling["unit_refs"] == historical_sampling["unit_refs"])
    check(receipt, "all original 3360 obligations open", len(contexts) == 560
          and opened_contexts(contexts) and sum(len(r["missing_requirements"]) for r in contexts) == 3360)
    check(receipt, "all sampler gold masks and semantic outputs remain empty", all(
        u["training_mask"] == u["evaluation_gold_mask"] == 0 and u["meaning_target"] is None
        and u["formal_outputs"] == [] and u["semantic_assertions"] == [] for u in units))
    by_ordinal = {u["ordinal"]: u for u in units}
    unit_refs = {r["record_cid"]: r for r in sampling["unit_refs"]}
    contributor, scope_unit = by_ordinal[13], by_ordinal[9]
    text = sampling["document_view_report"]["document"]["document_text"]
    blocks = sampling["document_view_report"]["document"]["blocks"]
    spans = {"scope_span": (382, 396, "in this title:"), "head": (780, 792, "armed forces"),
             "definition_cue": (794, 799, "means"), "body": (800, 870, BODY)}
    check(receipt, "fixed original blocks and every exact declared span", all(
        text[a:b] == literal for a, b, literal in spans.values())
        and blocks[9]["char_start"] == 334 and blocks[9]["char_end"] == 396
        and blocks[13]["char_start"] == 766 and blocks[13]["char_end"] == 870
        and contributor["candidate_input"] is True and scope_unit["candidate_input"] is True)
    span = lambda name: dict(zip(("char_start", "char_end", "text"), spans[name]))
    declaration = dict(declaration_id="engineering-only-usc10-101-armed-forces-whole-body",
        interpretation_status="unreviewed_caller_declaration", source_version_ref=contributor["source_version_ref"],
        normalized_view_id=contributor["normalized_view_id"],
        contributor_unit_refs=[unit_refs[contributor["record_cid"]]],
        scope_unit_ref=unit_refs[scope_unit["record_cid"]], scope_span=span("scope_span"),
        head=span("head"), definition_cue=span("definition_cue"),
        body={"op": "atom", "span": span("body")},
        applicability=dict(scope_kind="title", scope_id="engineering-declaration:usc:us:10",
            jurisdiction_id="engineering-declaration:us", instrument_id="engineering-declaration:usc-title10",
            legal_as_of_civil_date=None, source_edition=2024,
            source_release_id="govinfo-markup-v2-edition:2024"))
    full_inputs = dict(trusted, sampling_report=sampling, expected_sampling_report_sha256=sampling_sha,
                       raw_html=raw)
    receipt["population"] = dict(blocks=560, candidate_inputs=134, controls=426, open_obligations=3360)
    receipt["sampling_full_canonical_sha256"] = sampling_sha
    receipt["families"] = {}
    for family in ("fol", "tdfol"):
        directory = output / family
        directory.mkdir(mode=0o700)
        request = dict(schema=bridge.REQUEST_SCHEMA, profile=bridge.PROFILE, family=family, declaration=declaration)
        report = bridge.prepare_definition_v2(request, **full_inputs)
        request_raw, report_raw = wire(request), wire(report)
        save(directory / "request.json", request_raw)
        save(directory / "report.json", report_raw)
        args = dict(full_inputs, request_raw=request_raw, expected_request_sha256=sha(request_raw),
                    expected_report_sha256=sha(report_raw))
        candidate = adapter.adapt_definition_only_bytes_v2(report_raw, **args)
        save(directory / "companion.json", wire(candidate))
        check(receipt, family + " exact companion regeneration", adapter.validate_definition_only_candidate_v2(
            candidate, report_raw, **args) == candidate)
        check(receipt, family + " exact native AST preserved without inferred union",
              candidate["definition_record"]["native_ast"] == candidate["ast_record"]["native_ast"] == report["native_ast"]
              and len(report["symbols"]) == 2 and report["declaration"]["body"] == {"op": "atom", "span": span("body")})
        check(receipt, family + " contexts remain open and authority remains false", opened_contexts(candidate["context_declarations"])
              and all(candidate[k] is False for k in adapter.FALSE_FLAGS)
              and all(value is False for value in report["authority"].values())
              and candidate["definition_record"]["definition_lexical_coverage_complete"] is False)
        graph = candidate["graph"]
        check(receipt, family + " no invented norm or use assertion", "norm_record" not in candidate
              and not ({"norm_assertion", "entity"} & {n["node_type"] for n in graph["nodes"]})
              and "USES_DEFINITION" not in {e["relation"] for e in graph["edges"]}
              and all(graph[k] is False for k in ("admitted", "formalized", "source_semantics_verified")))
        manifest = adapter.export_definition_only_candidate_v2(candidate, directory / "graph-bundle", report_raw=report_raw, **args)
        manifest_sha = sha((directory / "graph-bundle" / "manifest.json").read_bytes())
        cold = exchange.load_graph_bundle(directory / "graph-bundle", expected_manifest_sha256=manifest_sha)
        check(receipt, family + " public Parquet cold-load exact graph", cold == {"manifest": manifest, "snapshot": graph})
        cold_args = args | dict(request_raw=(directory / "request.json").read_bytes(),
            sampling_report=json.loads((output / "sampling-report.json").read_bytes()),
            raw_html=(output / "source.html").read_bytes(),
            descriptor=json.loads((output / "acquisition-descriptor.json").read_bytes()))
        check(receipt, family + " cold companion independently replayed", adapter.validate_definition_only_candidate_v2(
            json.loads((directory / "companion.json").read_bytes()), (directory / "report.json").read_bytes(),
            **cold_args) == candidate)
        receipt["families"][family] = dict(graph_nodes=len(graph["nodes"]), graph_edges=len(graph["edges"]),
            companion_cid=candidate["record_cid"], graph_snapshot_cid=graph["record_cid"],
            graph_manifest_sha256=manifest_sha, source_context_frontier=report["source_context_frontier"])
    check(receipt, "no torch loaded", not any(k == "torch" or k.startswith("torch.") for k in sys.modules))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True, type=Path)
    output = parser.parse_args().output_directory.resolve()
    os.umask(0o077)
    output.mkdir(mode=0o700, exist_ok=False)
    started = time.monotonic()
    receipt = dict(schema="legal-ir-definition-v2-real-source-engineering-probe/v1", checks=[], status="failed",
        driver=metadata(Path(__file__).resolve()), repository=str(REPOSITORY),
        scope="Unreviewed caller encoding over retained real source; not reviewed statutory meaning.",
        limitations=["Whole post-means text is one opaque unary atom; no list union, legal sort or lexical completeness is inferred.",
            "Title applicability and source roles remain unreviewed; legal as-of date is explicitly unknown.",
            "No actual legal/formal review, context closure, semantic/training admission, model/training, proof or Lean execution is qualified.",
            "Graph envelopes alone are insufficient: full companions and exact original external inputs remain required.",
            "Cold-load uses the public disk reader in this process; no fresh-interpreter validation is claimed.",
            "Parallel V2 review-owner work is separate; this probe creates no review subject or authenticated reviewer claim."])
    before = {name: metadata(path) for name, (path, _, _) in INPUTS.items()}
    receipt["historical_inputs_before"] = before
    try:
        run(output, receipt)
        check(receipt, "output tree is private", all((p.stat().st_mode & 0o077) == 0 for p in [output, *output.rglob("*")]))
    except Exception as error:
        receipt["error"] = {"type": type(error).__name__, "message": str(error)}
    try:
        after = {name: metadata(path) for name, (path, _, _) in INPUTS.items()}
        receipt["historical_inputs_after"] = after
        check(receipt, "historical input bytes unchanged", before == after)
    except Exception as error:
        receipt["historical_guard_error"] = {"type": type(error).__name__, "message": str(error)}
    receipt["status"] = "pass" if "error" not in receipt and "historical_guard_error" not in receipt else "failed"
    receipt["elapsed_seconds"] = time.monotonic() - started
    receipt["files"] = [metadata(p) for p in sorted(output.rglob("*")) if p.is_file()]
    save(output / "probe-receipt.json", wire(receipt))
    print(json.dumps({"status": receipt["status"], "receipt": str(output / "probe-receipt.json")}))
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
