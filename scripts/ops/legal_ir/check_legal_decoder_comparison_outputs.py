#!/usr/bin/env python3
"""Build comparison predictions using generated structure and source bindings.

Selection reads no canonical references or semantic scores. Every challenge
row is accounted for; only the currently supported, unqualified deontic
fragment is sent to the exact ``lake build legal`` gate. Build success means
representation compilation and is never evidence of legal interpretation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

SCHEMA = "legal-decoder-comparison-builds/v1"
MAX_JSON_BYTES = 64 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    require(path.is_file() and path.stat().st_size <= MAX_JSON_BYTES, "bounded JSON file required")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite JSON constant: " + value)
    return json.loads(path.read_bytes(), object_pairs_hook=unique, parse_constant=reject)


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return {"path": str(Path(path).resolve()), "sha256": sha(path)}


def select_candidates(source_rows, generated_rows, *, toolchain):
    """Keep generated unsupported/abstained rows in explicit exclusion records."""
    from ipfs_datasets_py.logic.autoformal.legal_pilot_lake import prepare_legal_pilot
    require(type(source_rows) is list and type(generated_rows) is list
            and len(source_rows) == len(generated_rows) > 0, "complete ordered challenge coverage required")
    candidates, excluded, ids = [], [], set()
    decoded = 0
    for index, (source, generated) in enumerate(zip(source_rows, generated_rows)):
        require(type(source) is dict and type(generated) is dict, "source and prediction objects required")
        identity, text = source["id"], source["source_text"]
        require(type(identity) is str and identity not in ids, "unique source id required")
        ids.add(identity)
        require(type(text) is str, "exact source text required")
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        require(source_hash == source["source_sha256"] == generated.get("source_sha256"),
                "generated/source text binding differs at row " + str(index))
        require("id" not in generated or generated["id"] == identity, "prediction id differs from ordered source")
        require(generated.get("target_access") is False and generated.get("teacher_forcing") is False,
                "free generation without target access required")
        record = {"id": identity, "row_index": index, "source_sha256": source_hash}
        if generated.get("status") != "decoded":
            excluded.append({**record, "reason": "decoder_abstained", "decoder_reason": generated.get("reason")})
            continue
        decoded += 1
        ir = generated.get("canonical_ir")
        candidate = {"candidate_id": identity, "source_text": text,
                     "source_sha256": source_hash, "canonical_ir": ir}
        try:
            preparation = prepare_legal_pilot([candidate], toolchain=toolchain).to_dict()
        except (ValueError, TypeError, KeyError) as error:
            excluded.append({**record, "reason": "generated_ir_or_source_profile_rejected", "detail": str(error)})
            continue
        if not preparation["all_candidates_supported"]:
            rejection = preparation["candidates"][0]
            excluded.append({**record, "reason": "generated_profile_unsupported", "detail": rejection.get("reason")})
            continue
        candidates.append(candidate)
    return {"candidates": candidates, "excluded": excluded, "decoded_count": decoded,
            "source_count": len(source_rows), "supported_count": len(candidates),
            "exclusion_counts": dict(Counter(row["reason"] for row in excluded))}


def run(args):
    from ipfs_datasets_py.logic.autoformal.legal_pilot_lake import MAX_ROWS, build_legal_pilot
    run_directory = Path(args.run_directory).resolve()
    output = Path(args.output_directory).resolve()
    require(not output.exists(), "fresh output directory required")
    summary_path = run_directory / "summary.json"
    prepared_path = run_directory / "prepared-inputs.json"
    summary, prepared = read(summary_path), read(prepared_path)
    require(type(summary.get("runs")) is list and bool(summary["runs"]), "completed comparison runs required")
    source_rows = prepared["challenge"]
    pins = {str(path): sha(path) for path in (summary_path, prepared_path, Path(__file__))}
    names = []
    # Validate completeness and every source binding before executing a build.
    selections = []
    for item in summary["runs"]:
        name = item["name"]
        require(type(name) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", name) and name not in names,
                "unique bounded filesystem-safe model name required")
        names.append(name)
        predictions_path = run_directory / name / "challenge.json"
        predictions = read(predictions_path)
        pins[str(predictions_path)] = sha(predictions_path)
        generation = predictions["generation"]
        require(generation.get("control") in (None, "normal"), "ordinary predictions required for build coverage")
        selected = select_candidates(source_rows, generation["rows"], toolchain=args.toolchain)
        selections.append((name, selected))
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for name, selected in selections:
        model_output = output / name
        model_output.mkdir()
        candidate_reference = write(model_output / "selected-candidates.json", selected["candidates"])
        exclusion_reference = write(model_output / "excluded.json", selected["excluded"])
        receipts, passed_count = [], 0
        for start in range(0, len(selected["candidates"]), MAX_ROWS):
            batch = selected["candidates"][start:start + MAX_ROWS]
            directory = model_output / ("lake-" + str(start // MAX_ROWS).zfill(3))
            receipt = build_legal_pilot(batch, toolchain=args.toolchain, lake_executable=args.lake_executable,
                timeout_seconds=args.timeout_seconds, output_directory=directory).to_dict()
            if receipt["build_passed"]:
                passed_count += len(batch)
            receipts.append({"candidate_count": len(batch), "build_passed": receipt["build_passed"],
                "manifest_coverage_passed": receipt["manifest_coverage_passed"],
                "backend_executed": receipt["backend_executed"], "status": receipt["status"],
                "command": receipt["command"], "returncode": receipt["returncode"],
                "receipt": {"path": str(directory / "pilot-receipt.json"),
                            "sha256": sha(directory / "pilot-receipt.json")}})
        result = {"name": name, "challenge_count": selected["source_count"],
            "decoded_count": selected["decoded_count"], "supported_count": selected["supported_count"],
            "excluded_count": len(selected["excluded"]), "exclusion_counts": selected["exclusion_counts"],
            "built_candidate_count": passed_count,
            "all_supported_candidates_built": bool(receipts) and passed_count == selected["supported_count"],
            "full_challenge_build_coverage": passed_count == selected["source_count"],
            "selected_candidates": candidate_reference, "excluded": exclusion_reference, "builds": receipts}
        results.append(result)
        print(json.dumps({"model": name, "supported": selected["supported_count"],
                          "built": passed_count, "challenge": selected["source_count"]}), flush=True)
    require(all(sha(path) == digest for path, digest in pins.items()), "comparison inputs changed during build checks")
    report = {"schema": SCHEMA, "toolchain": args.toolchain, "target": "legal", "input_sha256": pins,
        "selection_policy": "all generated candidates within canonical-unqualified/v1; unsupported rows accounted for",
        "canonical_references_used_for_selection": False, "semantic_scores_used_for_selection": False,
        "sealed_target_files_opened": False, "model_count": len(results), "models": results,
        "source_semantics_verified": False, "proof_authority": False, "admitted": False,
        "scope": "Compilation of parameterized deontic representations; unsupported qualifier profiles excluded explicitly"}
    write(output / "summary.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--lake-executable", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    args = parser.parse_args(argv)
    require(0 < args.timeout_seconds <= 60, "timeout must be in (0, 60]")
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
