#!/usr/bin/env python3
"""Replay frozen predictions under an explicit synthetic qualifier convention.

This experiment declares activation-time conjunction/waiver and closed Nat
duration intervals. Those are experimental caller premises, not interpretations
verified against legislation. Calendar deadlines remain unsupported. No targets
or semantic scores enter candidate selection or Lean compilation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir.check_legal_decoder_comparison_outputs import read, write, sha, require
from scripts.ops.legal_ir.run_legal_span_retrieval_experiment import digest
from scripts.ops.legal_ir.summarize_legal_structured_retrieval_experiment import verify_generation

POLICY = "synthetic-activation-waiver-closed-duration/v1"
POLICY_DESCRIPTION = {
    "id": POLICY, "independently_reviewed": False, "source_semantics_verified": False,
    "origin": "experimental caller convention applied to predicted fields, never a source translation",
    "activation": "all condition atoms hold at caller-supplied evaluation origin, outside the modality",
    "exceptions": "any exception atom at that origin waives activation; no inferred per-tick scope",
    "duration": "within N days/hours is existential over closed discrete Nat interval [origin, origin+N]; minimum duration is universal",
    "clock": "Nat ticks in declared units; business days, calendar dates, real-world clocks and occurrences unsupported",
    "atoms": "each qualifier literal L is explicitly declared as the atom declared_qualifier(L); no asserted truth or internal parsing",
    "modality": "O/P/F remain distinct interpretation parameters; clock annotation is explicit, unlike the old unqualified profile",
}


def validate_model_coverage(summary, frozen):
    runs = summary.get("runs")
    require(type(runs) is list and bool(runs) and type(frozen) is dict and bool(frozen),
            "nonempty completed models and generation freeze required")
    require(all(type(row) is dict and type(row.get("name")) is str and
                re.fullmatch(r"[A-Za-z0-9_-]{1,120}", row["name"]) for row in runs),
            "bounded model names required")
    names = [row["name"] for row in runs]
    require(len(set(names)) == len(names) and set(names) == set(frozen),
            "complete unique model coverage must equal the generation freeze")
    require(all(type(frozen[name]) is dict and "challenge" in frozen[name] for name in names),
            "challenge generation commitment required for every model")


def synthetic_interpretation(candidate, *, policy):
    """An explicit experimental assumption builder, never the bridge default."""
    from ipfs_datasets_py.logic.autoformal import legal_canonical_qualified as bridge
    require(policy == POLICY, "explicit supported synthetic interpretation policy required")
    sidecar = bridge.interpretation_skeleton(candidate)
    for declaration, rule in zip(sidecar["formulas"], candidate["canonical_ir"]["rules"]):
        declaration["activation_scope"] = "all_conditions_at_evaluation_origin"
        declaration["exception_scope"] = "activation_time_waiver"
        for field in ("conditions", "exceptions"):
            for binding in declaration[field]:
                binding["expression"] = {"op": "atom", "predicate": {
                    "name": "declared_qualifier", "arguments": [binding["source_text"]]}}
        if rule["temporal"]:
            require(len(rule["temporal"]) == 1, "multiple temporal qualifiers require a new interpretation profile")
            literal = rule["temporal"][0]
            match = re.fullmatch(r"(within|for at least) ([1-9][0-9]*) (day|hour)(s?)", literal)
            require(match is not None, "calendar or unsupported temporal literal requires explicit new clock semantics")
            quantity, unit = int(match[2]), match[3]
            require(match[4] == ("s" if quantity != 1 else ""), "exact duration plural required")
            declaration["temporal"] = {"source_index": len(rule["conditions"]), "source_text": literal,
                "temporal_kind": "within_duration" if match[1] == "within" else "minimum_duration",
                "quantity": quantity, "unit": unit, "time_domain": "discrete_nat",
                "origin": "caller_supplied_evaluation_time", "lower_inclusive": True, "upper_inclusive": True}
    return sidecar


def select_candidates(sources, generated, *, toolchain, policy):
    import hashlib
    from ipfs_datasets_py.logic.autoformal import legal_qualified_lake as gate
    require(type(sources) is list and type(generated) is list and len(sources) == len(generated) > 0,
            "complete source/prediction coverage required")
    rows, excluded, seen, decoded = [], [], set(), 0
    for index, (source, prediction) in enumerate(zip(sources, generated)):
        identity, text = source["id"], source["source_text"]
        require(type(identity) is str and identity not in seen, "unique source id required")
        seen.add(identity)
        source_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        require(source_sha == source["source_sha256"] == prediction.get("source_sha256"), "source binding differs")
        require("id" not in prediction or prediction["id"] == identity, "source/prediction identity differs")
        require(prediction.get("target_access") is False and prediction.get("teacher_forcing") is False,
                "free prediction without reference access required")
        record = {"candidate_id": identity, "row_index": index, "source_sha256": source_sha}
        if prediction.get("status") != "decoded":
            excluded.append({**record, "reason": "decoder_abstained", "detail": prediction.get("reason")})
            continue
        decoded += 1
        candidate = {"candidate_id": identity, "source_text": text, "source_sha256": source_sha,
                     "canonical_ir": prediction["canonical_ir"]}
        try:
            sidecar = synthetic_interpretation(candidate, policy=policy)
            entry = {"candidate": candidate, "interpretation": sidecar}
            preparation = gate.prepare_qualified_legal([entry], toolchain=toolchain).to_dict()
            require(preparation["all_candidates_supported"], preparation["candidates"][0].get("reason", "unsupported"))
        except (ValueError, KeyError, TypeError) as error:
            excluded.append({**record, "reason": "explicit_interpretation_unsupported", "detail": str(error)})
            continue
        rows.append(entry)
    return {"rows": rows, "excluded": excluded, "source_count": len(sources), "decoded_count": decoded,
            "supported_count": len(rows), "exclusion_counts": dict(Counter(r["reason"] for r in excluded))}


def run(args):
    from ipfs_datasets_py.logic.autoformal import legal_qualified_lake as gate
    require(args.interpretation_policy == POLICY, "explicit synthetic policy required")
    directory, output = Path(args.run_directory).resolve(), Path(args.output_directory).resolve()
    require(not output.exists(), "fresh output directory required")
    summary_path, prepared_path = directory / "summary.json", directory / "prepared-inputs.json"
    summary, prepared = read(summary_path), read(prepared_path)
    frozen_path = directory / "generation-frozen.json"
    require(sha(frozen_path) == summary["generation_frozen"]["sha256"], "generation freeze hash differs")
    frozen = read(frozen_path)
    validate_model_coverage(summary, frozen)
    pins = {str(path): sha(path) for path in (summary_path, prepared_path, frozen_path, Path(__file__))}
    for function in (read, write, sha, digest, verify_generation):
        path = Path(sys.modules[function.__module__].__file__).resolve()
        pins[str(path)] = sha(path)
    selections, names = [], set()
    for item in summary["runs"]:
        name = item["name"]
        require(type(name) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", name) and name not in names,
                "unique bounded model name required")
        names.add(name)
        path = directory / name / "challenge-generation.json"
        generation = read(path)
        pins[str(path)] = sha(path)
        require(digest(generation) == frozen[name]["challenge"], "frozen generation differs")
        require(generation.get("control") in (None, "normal"), "ordinary generation required")
        verify_generation(generation, item["checkpoint"]["sha256"])
        selected = select_candidates(prepared["challenge"], generation["rows"],
                                     toolchain=args.toolchain, policy=args.interpretation_policy)
        selections.append({"name": name, "arm": item["arm"], **selected})
        print(json.dumps({"phase": "prepared", "name": name,
            "supported": selected["supported_count"], "exclusions": selected["exclusion_counts"]}), flush=True)
    output.mkdir(parents=True, exist_ok=False)
    plan_ref = write(output / "interpretation-policy.json", POLICY_DESCRIPTION)
    selected_ref = write(output / "frozen-selections.json", selections)
    models = []
    for selected in selections:
        folder = output / selected["name"]
        folder.mkdir()
        receipts, built = [], 0
        for start in range(0, len(selected["rows"]), gate.MAX_ROWS):
            batch = selected["rows"][start:start + gate.MAX_ROWS]
            destination = folder / f"lake-{start // gate.MAX_ROWS:03d}"
            receipt = gate.build_qualified_legal(batch, toolchain=args.toolchain,
                lake_executable=args.lake_executable, timeout_seconds=args.timeout_seconds,
                output_directory=destination).to_dict()
            if receipt["build_passed"]:
                built += len(batch)
            receipts.append({"candidate_count": len(batch), "build_passed": receipt["build_passed"],
                "manifest_coverage_passed": receipt["manifest_coverage_passed"],
                "backend_executed": receipt["backend_executed"], "returncode": receipt["returncode"],
                "command": receipt["command"], "receipt": {"path": str(destination / "qualified-receipt.json"),
                    "sha256": sha(destination / "qualified-receipt.json")}})
        model = {k: selected[k] for k in ("name", "arm", "source_count", "decoded_count", "supported_count", "exclusion_counts")}
        model.update(built_count=built, excluded_count=len(selected["excluded"]),
                     build_applicable=bool(receipts),
                     all_supported_built=bool(receipts) and built == selected["supported_count"], builds=receipts)
        models.append(model)
        print(json.dumps({"name": model["name"], "built": built, "supported": model["supported_count"]}), flush=True)
    require(all(sha(path) == wanted for path, wanted in pins.items()), "inputs or checker changed during builds")
    totals = {key: sum(model[key] for model in models) for key in
              ("source_count", "decoded_count", "supported_count", "built_count", "excluded_count")}
    result = {"schema": "legal-qualified-decoder-builds/v1", "interpretation_policy": plan_ref,
              "frozen_selections": selected_ref, "input_sha256": pins, "models": models, "totals": totals,
              "target": "legal", "toolchain": args.toolchain, "canonical_references_used_for_selection": False,
              "semantic_scores_used_for_selection": False, "source_semantics_verified": False,
              "admitted": False, "qualified": False, "all_logic_families_supported": False,
              "scope": "Explicit experimental interpretations of frozen predictions; not reviewed statutory meaning"}
    write(output / "summary.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--lake-executable", required=True)
    parser.add_argument("--interpretation-policy", required=True, choices=[POLICY])
    parser.add_argument("--timeout-seconds", type=float, default=60)
    args = parser.parse_args(argv)
    require(0 < args.timeout_seconds <= 60, "timeout must be in (0,60]")
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
