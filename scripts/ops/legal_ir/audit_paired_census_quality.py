#!/usr/bin/env python3
"""Audit local paired census evidence without compiling, filtering or enqueueing."""
from collections import Counter
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys

MAX_MANIFESTS, MAX_TOTAL_BYTES, MAX_ROWS = 16, 64 * 1024**2, 64
MAX_RETAINED_BYTES = MAX_REPORT_BYTES = 64 * 1024**2
STREAMS = {"canonical_compiler": ("compiler", "canonical_formal_outputs"),
           "compiler_view": ("compiler", "formal_outputs"),
           "autoencoder": ("autoencoder", "formal_outputs")}
TOTALS = ("spans", "goals", "canonical_formal_outputs", "compiler_view_outputs", "autoencoder_formal_outputs",
          "canonical_compiled_rows", "producer_canonical_complete_rows", "independent_comparison_claims",
          "independent_comparable_rows", "independent_agreement_rows", "diagnostic_comparable_rows",
          "diagnostic_agreement_rows", "portable_goals", "classification_review_candidates",
          "canonical_output_with_comparison_unavailable_rows")


def review_hypotheses(text):
    """Narrow source-quality cues, never a non-operative classification."""
    candidates = []
    if re.fullmatch(r"\s*Government Publishing Office,\s*(?:https?://)?www\.gpo\.gov(?:\s+§{1,2}\s*[\w().—–-]+\.?)?\s*", text, re.I):
        candidates.append(("editorial_gpo_footer", "Standalone publisher/footer-shaped text; inspect the original page and neighboring spans."))
    if re.match(r"\s*(?:Statutory Notes and Related Subsidiaries|Historical and Revision Notes)\b", text, re.I):
        candidates.append(("editorial_notes_heading", "Editorial heading present; following effective-date or amendment text may still have legal effect."))
    if re.search(r"\bPub\.\s*(?:L\.?\s*(?:\d{1,3}\s*[-–]\s*)?)?$", text):
        candidates.append(("truncated_public_law_reference", "Public-law citation appears unfinished; retrieve adjacent spans and original source context."))
    return [{"kind": kind, "reason": reason, "requires_context_review": True,
             "classification_proven": False} for kind, reason in candidates]


def _forbid_authority(value):
    if any(value.get(key, False) is not False for key in ("admitted", "formalized", "enqueued")):
        raise ValueError("census audit cannot consume or grant authority flags")


def _enumerated_object_review(text, canonical_outputs):
    if not re.search(r"\(A\).*\(B\)", text, re.S):
        return []
    for output in canonical_outputs:
        payload = json.loads(output["payload_json"])
        obj = payload.get("object") if isinstance(payload, dict) else None
        if output["format"] == "typed-deontic-rule/v1" and isinstance(obj, str) and len(obj) <= 160 and not re.search(
                r"\([AB]\)|[;:—–]", obj) and re.match(
                r"^to\s+(?:the\s+)?(?:committees?|congress|secretary|agency)\b", obj, re.I):
            return [{"kind": "enumerated_object_context_review", "requires_context_review": True,
                "classification_proven": False, "reason": "Source contains (A)/(B) and the typed object starts with a recipient; review complete source and all rule fields for enumeration coverage."}]
    return []


def summarize_bundle(bundle, manifest_path):
    """Summarize an already validated existing-loader bundle; preserve evidence."""
    _forbid_authority(bundle)
    totals = Counter({key: 0 for key in TOTALS})
    counts = {key: Counter() for key in ("compiler_status", "autoencoder_status", "comparison_status", "goal_issue", "goal_kind")}
    groups, rows = Counter(), []
    for row in bundle["paired_spans"]:
        _forbid_authority(row)
        if row["lake"]["admitted"] is not False or (row["source"]["constitution"] and row["compiler"]["roundtrip_ok"]):
            raise ValueError("invalid Lake or Constitution authority in census")
        compiler, comparison = row["compiler"], row["comparison"]
        totals["spans"] += 1
        totals["canonical_compiled_rows"] += compiler["status"] == "compiled"
        totals["producer_canonical_complete_rows"] += compiler["canonical_complete"] is True
        independent, comparable = comparison["independent"] is True, comparison["comparable"] is True
        totals["independent_comparison_claims"] += independent
        totals["independent_comparable_rows"] += independent and comparable
        totals["independent_agreement_rows"] += independent and comparable and comparison["agrees"] is True
        totals["diagnostic_comparable_rows"] += not independent and comparable
        totals["diagnostic_agreement_rows"] += comparison["status"] == "diagnostic_agree"
        counts["compiler_status"][compiler["status"]] += 1
        counts["autoencoder_status"][row["autoencoder"]["status"]] += 1
        counts["comparison_status"][comparison["status"]] += 1
        outputs, metadata = {}, []
        for stream, (producer, field) in STREAMS.items():
            outputs[stream] = row[producer][field]
            totals[{"canonical_compiler": "canonical_formal_outputs", "compiler_view": "compiler_view_outputs",
                    "autoencoder": "autoencoder_formal_outputs"}[stream]] += len(outputs[stream])
            for output in outputs[stream]:
                groups[(stream, output["origin"], output["format"], output["family"], output["syntax_status"])] += 1
                payload = json.loads(output["payload_json"])
                raw = payload.get("metadata", {}) if isinstance(payload, dict) else {}
                cues = {key: raw[key] for key in ("cue", "fallback_rule", "residual_segment_role", "residual_token_count", "aliased_from")
                        if isinstance(raw, dict) and key in raw}
                if cues:
                    metadata.append({"stream": stream, "formula_sha256": output["sha256"], "metadata": cues})
        unavailable = bool(outputs["canonical_compiler"]) and comparison["status"] == "both_unavailable"
        totals["canonical_output_with_comparison_unavailable_rows"] += unavailable
        hypotheses = review_hypotheses(row["source"]["text"]) + _enumerated_object_review(row["source"]["text"], outputs["canonical_compiler"])
        totals["classification_review_candidates"] += bool(hypotheses)
        rows.append({"observation_id": row["observation_id"], "source": row["source"],
            "manifest_path": str(manifest_path), "manifest_sha256": bundle["manifest_sha256"],
            "compiler_status": compiler["status"], "compiler_reason": compiler["reason"],
            "autoencoder_status": row["autoencoder"]["status"],
            "producer_canonical_complete": compiler["canonical_complete"], "producer_compiler_complete": compiler["complete"],
            "producer_roundtrip_ok": compiler["roundtrip_ok"], "decompiled": compiler["decompiled"],
            "provenance": row["provenance"], "lake_observation": row["lake"],
            "canonical_output_comparison_unavailable": unavailable,
            "comparison": comparison, "goal_ids": row["goal_ids"], "formal_outputs": outputs,
            "fallback_metadata": metadata, "classification_review_hypotheses": hypotheses,
            "model_identity": row["autoencoder"]["model_identity"], "embedding_model": row["autoencoder"]["embedding_model"],
            "semantic_embeddings": row["autoencoder"]["semantic_embeddings"],
            "learned_formula_capture_verified": row["autoencoder"].get("learned_formula_capture_verified", False),
            "source_target_artifact_sha256": row["source_target_artifact_sha256"],
            "source_target_artifact_pointer": row["source_target_artifact_pointer"],
            "compiler_components_artifact_sha256": compiler["components_artifact_sha256"],
            "compiler_components_artifact_pointer": compiler["components_artifact_pointer"],
            "admitted": False, "formalized": False, "enqueued": False})
    for goal in bundle["goals"]:
        _forbid_authority(goal)
        totals["goals"] += 1
        totals["portable_goals"] += goal["packet_artifact_sha256"] is not None
        counts["goal_issue"][goal["issue"]] += 1
        counts["goal_kind"][goal["record_kind"]] += 1
    formal = [dict(zip(("stream", "origin", "format", "family", "syntax_status"), key), count=value)
              for key, value in sorted(groups.items())]
    return {"totals": dict(totals), "counts": {**{key: dict(value) for key, value in counts.items()}, "formal_outputs": formal},
            "rows": rows, "goals": bundle["goals"], "admitted": False, "formalized": False, "enqueued": False}


def _existing_reader(workspace_tree):
    root = Path(workspace_tree or os.environ.get("IPFS_DATASETS_EXPECTED_SOURCE_ROOT") or Path(__file__).resolve().parents[3]).resolve()
    for name, module in tuple(sys.modules.items()):
        if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py."):
            origin = getattr(module, "__file__", None)
            if origin and not Path(origin).resolve().is_relative_to(root):
                raise ValueError("a different datasets tree was imported first")
    sys.path.insert(0, str(root))
    paired = importlib.import_module("ipfs_datasets_py.logic.autoformal.paired_span_census")
    pin = importlib.import_module("ipfs_datasets_py.logic.autoformal.tree_pin")
    if Path(paired.__file__).resolve() != root / "ipfs_datasets_py/logic/autoformal/paired_span_census.py":
        raise ValueError("paired reader escaped the explicit workspace tree")
    pin.require_workspace_logic_tree()
    return paired.load_paired_census_bundle


def audit_manifests(manifests, *, max_manifests=MAX_MANIFESTS, max_total_bytes=MAX_TOTAL_BYTES,
                    max_rows=MAX_ROWS, loader=None, workspace_tree=None):
    """Use the existing immutable-bundle reader once per explicitly selected path."""
    for value, ceiling in ((max_manifests, MAX_MANIFESTS), (max_total_bytes, MAX_TOTAL_BYTES), (max_rows, MAX_ROWS)):
        if type(value) is not int or not 0 < value <= ceiling:
            raise ValueError("audit limits must be positive and cannot exceed fixed ceilings")
    paths = list(manifests)
    if not 0 < len(paths) <= max_manifests:
        raise ValueError("explicit manifest count exceeds the audit bound")
    prepared, seen, content_seen, used = [], set(), set(), 0
    for item in paths:
        path = Path(item).absolute()
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
            raise ValueError("bounded regular manifest required")
        info = path.stat()
        if (info.st_dev, info.st_ino) in seen:
            raise ValueError("duplicate manifest file")
        seen.add((info.st_dev, info.st_ino))
        with path.open("rb") as stream:
            raw = stream.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise ValueError("manifest changed beyond the header bound")
        header = json.loads(raw)
        identity = hashlib.sha256(raw).hexdigest()
        if identity in content_seen:
            raise ValueError("duplicate manifest content")
        content_seen.add(identity)
        sizes = [entry["bytes"] for entry in header["tables"].values()]
        if not sizes or any(type(size) is not int or size < 0 for size in sizes):
            raise ValueError("invalid declared compressed-table budget")
        charge = len(raw) + sum(sizes)
        used += charge
        if used > max_total_bytes:
            raise ValueError("total selected compressed input exceeds audit bound")
        prepared.append((path, charge, identity))
    reader = loader if loader is not None else _existing_reader(workspace_tree)
    report = {"schema": "paired-census-quality-audit/v1", "totals": Counter(),
              "counts": {key: Counter() for key in ("compiler_status", "autoencoder_status", "comparison_status", "goal_issue", "goal_kind")},
              "rows": [], "goals": [], "batches": [], "bounded_input_bytes": used}
    formal, retained = Counter(), 0
    for path, charge, identity in prepared:
        if hashlib.sha256(path.read_bytes()).hexdigest() != identity:
            raise ValueError("manifest changed after preflight")
        # The existing reader uses this bound for decompressed Arrow/artifacts
        # as well as compressed tables. Keep that per-bundle ceiling separate
        # from the aggregate compressed-input budget checked above.
        bundle = reader(path, max_bytes=max_total_bytes, max_rows=max_rows)
        if bundle["manifest_sha256"] != identity:
            raise ValueError("existing reader returned a different manifest")
        summary = summarize_bundle(bundle, path)
        retained += len(json.dumps({"rows": summary["rows"], "goals": summary["goals"]},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if retained > MAX_RETAINED_BYTES:
            raise ValueError("retained row and goal JSON exceeds audit bound")
        report["totals"].update(summary["totals"])
        for key, counter in report["counts"].items():
            counter.update(summary["counts"][key])
        for group in summary["counts"]["formal_outputs"]:
            formal[tuple(group[key] for key in ("stream", "origin", "format", "family", "syntax_status"))] += group["count"]
        report["rows"].extend(summary["rows"])
        report["goals"].extend(summary["goals"])
        report["batches"].append({"manifest_path": str(path), "manifest_sha256": identity,
            "repository_id": bundle["repository_id"], "path_in_repo": bundle["manifest"]["path_in_repo"],
            "original_receipt_artifact_sha256": bundle["manifest"].get("original_receipt_artifact_sha256"),
            "totals": summary["totals"], "compressed_input_bytes": charge})
        del bundle
    report["totals"] = dict(report["totals"])
    report["counts"] = {key: dict(value) for key, value in report["counts"].items()}
    report["counts"]["formal_outputs"] = [dict(zip(("stream", "origin", "format", "family", "syntax_status"), key), count=value)
        for key, value in sorted(formal.items())]
    report.update(admitted=False, Lean_admitted=False, formalized=False, enqueued=False,
        Constitution_formalized=False, model_executed=False, compiler_executed=False,
        goals_modified=False, inputs_filtered=False,
        comparison_scope="Retained comparisons concern compiler.formal_outputs; canonical_formal_outputs are reported separately.",
        producer_complete_flags_are_semantic_coverage_proof=False,
        scope="Selected retained observations only; no coverage or semantic qualification estimate.")
    report["retained_record_json_bytes"] = retained
    if len((json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("serialized audit report exceeds output bound")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace-tree", type=Path)
    parser.add_argument("--max-manifests", type=int, default=MAX_MANIFESTS)
    parser.add_argument("--max-total-bytes", type=int, default=MAX_TOTAL_BYTES)
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("a fresh output path is required")
    report = audit_manifests(args.manifest, max_manifests=args.max_manifests,
        max_total_bytes=args.max_total_bytes, max_rows=args.max_rows, workspace_tree=args.workspace_tree)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({"output": str(args.output), "totals": report["totals"], "admitted": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
