#!/usr/bin/env python3
"""Verify completed calendar builds before posthoc authored-reference comparison."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir.summarize_legal_qualified_decoder_outputs import (
    read, read_ref, sha, digest, require, compare_ir)
from scripts.ops.legal_ir.compare_legal_decoder_architectures import write

POLICY = "synthetic-activation-waiver-gregorian-calendar/v1"


def expected_interpretation(candidate):
    from ipfs_datasets_py.logic.autoformal import legal_canonical_calendar as bridge
    sidecar = bridge.interpretation_skeleton(candidate)
    for rule, declaration in zip(candidate["canonical_ir"]["rules"], sidecar["formulas"]):
        declaration["activation_scope"] = "all_conditions_at_evaluation_origin"
        declaration["exception_scope"] = "activation_time_waiver"
        for facet in ("conditions", "exceptions"):
            for binding in declaration[facet]:
                binding["expression"] = {"op": "atom", "predicate": {
                    "name": "declared_qualifier", "arguments": [binding["source_text"]]}}
        if not rule["temporal"]:
            continue
        require(len(rule["temporal"]) == 1, "one temporal qualifier required")
        literal = rule["temporal"][0]
        common = {"source_index": len(rule["conditions"]), "source_text": literal, "lower_inclusive": True}
        calendar = re.fullmatch(r"before ([0-9]{4}-[0-9]{2}-[0-9]{2})", literal)
        if calendar:
            day = date.fromisoformat(calendar[1])
            declaration["temporal"] = {**common, "temporal_kind": "before_calendar_date",
                "calendar": "proleptic_gregorian", "ordinal_epoch": "0001-01-01", "ordinal_epoch_value": 1,
                "time_domain": "discrete_nat_days", "origin": "caller_supplied_evaluation_date_ordinal",
                "upper_inclusive": False, "expired_deadline_policy": "empty_witness_interval",
                "date": day.isoformat(), "date_ordinal": day.toordinal()}
        else:
            duration = re.fullmatch(r"(within|for at least) ([1-9][0-9]*) (day|hour)(s?)", literal)
            require(duration is not None, "unsupported temporal literal")
            amount = int(duration[2])
            require(duration[4] == ("s" if amount != 1 else ""), "duration plural differs")
            declaration["temporal"] = {**common,
                "temporal_kind": "within_duration" if duration[1] == "within" else "minimum_duration",
                "quantity": amount, "unit": duration[3], "time_domain": "discrete_nat",
                "origin": "caller_supplied_evaluation_time", "upper_inclusive": True}
    return sidecar


def verify_entry(source, prediction, entry):
    candidate = {"candidate_id": source["id"], "source_text": source["source_text"],
                 "source_sha256": source["source_sha256"], "canonical_ir": prediction["canonical_ir"]}
    require(entry == {"candidate": candidate, "interpretation": expected_interpretation(candidate)},
            "selected candidate or explicit interpretation differs from frozen prediction")


def verify_receipt(reference, entries):
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    receipt = read_ref(reference)
    require(digest({k: v for k, v in receipt.items() if k != "receipt_sha256"}) == receipt["receipt_sha256"],
            "internal receipt hash differs")
    prepared = gate.prepare_qualified_legal(entries, toolchain=receipt["toolchain"])
    gate.validate_preparation(prepared)
    manifest, folder = prepared.to_dict(), Path(reference["path"]).parent
    require(manifest["all_candidates_supported"] is True, "unsupported receipt entry")
    require(read(folder / "qualified-manifest.json") == manifest, "persisted manifest differs")
    require(all(receipt.get(k) == v for k, v in manifest.items() if k not in ("status", "backend_executed")),
            "receipt fields differ from replay")
    for filename, content in prepared.files:
        require((folder / filename).read_bytes() == content.encode(), "emitted source differs: " + filename)
    require(all(sha(path) == wanted for path, wanted in receipt["producer_pins"].items()), "producer pins differ")
    command = receipt["command"]
    require(type(command) is list and len(command) == 3 and command[1:] == ["build", "legal"] and
            digest(command) == receipt["command_sha256"], "exact legal command required")
    binaries = receipt["binary_sha256"]
    require(len(binaries) == 2 and {Path(p).name for p in binaries} == {"lake", "lean"} and command[0] in binaries,
            "both installed binaries required")
    require(all(sha(p) == h for p, h in binaries.items()) and receipt["binary_pins_match"] is True, "binary pins differ")
    version = receipt["toolchain"].split(":v")[1]
    require(set(receipt["version_probe"]) == {"lake", "lean"}, "both version probes required")
    for name, probe in receipt["version_probe"].items():
        match = re.search(r"Lean \(?version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)", probe["stdout"])
        require(probe["command"] == [next(p for p in binaries if Path(p).name == name), "--version"] and
                probe["returncode"] == 0 and match is not None and match[1] == version, "compiler version differs")
    modules = ["LegalCalendar.Prelude", *(r["module"] for r in receipt["candidates"]), "LegalCalendar"]
    paths = {".lake/build/lib/lean/" + m.replace(".", "/") + ".olean" for m in modules}
    artifacts = receipt["artifact_sha256"]
    require(all(re.fullmatch(r"[0-9a-f]{64}", v) for v in artifacts.values()), "invalid compiled artifact hash")
    coverage = set(artifacts) == paths
    require(receipt["manifest_coverage_passed"] is coverage and receipt["compiled_modules"] == [m for m in modules
        if ".lake/build/lib/lean/" + m.replace(".", "/") + ".olean" in artifacts], "module coverage differs")
    for stream in ("stdout", "stderr"):
        require(hashlib.sha256(receipt[stream].encode()).hexdigest() == receipt[stream + "_sha256"], "stream hash differs")
    if receipt["build_passed"]:
        require(receipt["backend_executed"] is True and receipt["returncode"] == 0 and coverage and
                receipt["status"] == "passed", "build success lacks execution and coverage")
        require(all(receipt[k] is False for k in ("timed_out", "output_truncated", "workspace_limit_exceeded",
            "resource_exhausted", "unavailable", "cancelled")), "build success conflicts with failure flags")
        require(not re.search(r"\b(?:sorry|sorryAx)\b", receipt["stdout"] + receipt["stderr"]), "placeholder build")
    require(all(receipt[k] is False for k in ("admitted", "formalized", "source_semantics_verified", "proof_authority")),
            "unsupported authority claim")
    return receipt


def summarize(run_directory, build_directory, output):
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    from scripts.ops.legal_ir.summarize_legal_structured_retrieval_experiment import verify_generation
    directory, builds = Path(run_directory), Path(build_directory)
    # No target-file read until every completed build and frozen generation is verified.
    completed = read(builds / "summary.json")
    require(completed["schema"] == "legal-calendar-decoder-builds/v1" and
            completed["canonical_references_used_for_selection"] is False and
            completed["semantic_scores_used_for_selection"] is False, "reference-blind completed builds required")
    require(all(sha(p) == h for p, h in completed["input_sha256"].items()), "build input hash differs")
    policy = read_ref(completed["interpretation_policy"])
    require(policy["id"] == POLICY and policy["source_semantics_verified"] is False, "wrong explicit policy")
    original, prepared, plan = read(directory / "summary.json"), read(directory / "prepared-inputs.json"), read(directory / "plan.json")
    require(sha(directory / "plan.json") == original["plan_sha256"], "training plan hash differs")
    frozen, selections = read_ref(original["generation_frozen"]), read_ref(completed["frozen_selections"])
    sources = prepared["challenge"]
    source_ids = {r["id"] for r in sources}
    require(len(source_ids) == len(sources) and all("canonical_ir" not in r for r in sources), "source identities or target exclusion differ")
    models = {m["name"]: m for m in original["runs"]}
    selected = {m["name"]: m for m in selections}
    compiled = {m["name"]: m for m in completed["models"]}
    require(len(models) == len(original["runs"]) == len(selected) == len(selections) == len(compiled) ==
            len(completed["models"]) == 15 and set(models) == set(selected) == set(compiled) == set(frozen),
            "complete fifteen-model coverage required")
    evidence = {}
    for name, model in models.items():
        generation = read(directory / name / "challenge-generation.json")
        require(digest(generation, ascii=True) == frozen[name]["challenge"], "generation freeze differs")
        verify_generation(generation, model["checkpoint"]["sha256"])
        predictions = generation["rows"]
        chosen, counts = selected[name], compiled[name]
        require(chosen["arm"] == counts["arm"] == model["arm"], "model arm differs")
        by_id = {r["candidate"]["candidate_id"]: r for r in chosen["rows"]}
        excluded = {r["candidate_id"]: r for r in chosen["excluded"]}
        require(len(by_id) == len(chosen["rows"]) and len(excluded) == len(chosen["excluded"]) and
                not set(by_id) & set(excluded) and set(by_id) | set(excluded) == source_ids, "selection partition differs")
        require(len(predictions) == len(sources), "source/prediction coverage differs")
        for source, prediction in zip(sources, predictions):
            identity = source["id"]
            require(hashlib.sha256(source["source_text"].encode()).hexdigest() == source["source_sha256"] ==
                    prediction["source_sha256"] and ("id" not in prediction or prediction["id"] == identity), "prediction source differs")
            if identity in by_id:
                require(prediction["status"] == "decoded", "selected abstention")
                verify_entry(source, prediction, by_id[identity])
            elif prediction["status"] != "decoded":
                require(excluded[identity]["reason"] == "decoder_abstained", "wrong abstention classification")
            else:
                candidate = {"candidate_id": identity, "source_text": source["source_text"],
                    "source_sha256": source["source_sha256"], "canonical_ir": prediction["canonical_ir"]}
                try:
                    sidecar = expected_interpretation(candidate)
                    supported = gate.prepare_qualified_legal([{"candidate": candidate, "interpretation": sidecar}],
                        toolchain=completed["toolchain"]).to_dict()["all_candidates_supported"]
                except ValueError:
                    supported = False
                require(not supported and excluded[identity]["reason"] == "explicit_interpretation_unsupported",
                        "supported prediction was excluded")
        built_ids, cursor = set(), 0
        for record in counts["builds"]:
            entries = chosen["rows"][cursor:cursor + record["candidate_count"]]
            require(len(entries) == record["candidate_count"] > 0, "batch coverage differs")
            receipt = verify_receipt(record["receipt"], entries)
            require(all(record[k] == receipt[k] for k in ("build_passed", "manifest_coverage_passed", "backend_executed", "returncode", "command")),
                    "batch summary differs")
            if receipt["build_passed"]:
                built_ids.update(r["candidate"]["candidate_id"] for r in entries)
            cursor += len(entries)
        require(cursor == len(chosen["rows"]) and len(built_ids) == counts["built_count"] and
                counts["supported_count"] == len(by_id) and counts["source_count"] == len(sources) and
                counts["decoded_count"] == sum(p["status"] == "decoded" for p in predictions), "model counts differ")
        evidence[name] = (predictions, built_ids)
    target_ref = plan.get("targets", plan.get("challenge_targets"))
    references = read_ref(target_ref)["targets"]
    gold = {r["id"]: r for r in references}
    require(len(gold) == len(references) == len(sources) and set(gold) == source_ids, "reference identity coverage differs")
    for source in sources:
        require(gold[source["id"]]["source_sha256"] == source["source_sha256"] and
                digest(gold[source["id"]]["canonical_ir"], ascii=True) == gold[source["id"]]["canonical_target_sha256"], "reference binding differs")
    results = []
    for name, (predictions, built_ids) in evidence.items():
        counts = Counter()
        omissions, additions, facet_errors = Counter(), Counter(), Counter()
        for source, prediction in zip(sources, predictions):
            actual = prediction.get("canonical_ir") if prediction["status"] == "decoded" else None
            comparison = compare_ir(actual, gold[source["id"]]["canonical_ir"])
            built, exact = source["id"] in built_ids, comparison["exact_authored_reference_match"]
            counts.update({"source_count": 1, "built": int(built), "authored_exact": int(exact),
                "built_and_authored_exact": int(built and exact), "built_but_authored_wrong": int(built and not exact),
                "decoder_abstained": int(actual is None)})
            if actual is not None:
                omissions.update(comparison["omitted_reference_qualifiers"])
                additions.update(comparison["additional_predicted_qualifiers"])
                facet_errors.update({k: int(not v) for k, v in comparison["facet_matches"].items()})
        results.append({"name": name, "arm": models[name]["arm"], "seed": models[name]["seed"], **dict(counts),
            "omitted_reference_qualifiers_in_decoded": dict(omissions), "extra_predicted_qualifiers": dict(additions),
            "decoded_facet_error_counts": dict(facet_errors)})
    report = {"schema": "legal-calendar-decoder-reference-comparison/v1", "models": results,
        "totals": {k: sum(m[k] for m in results) for k in ("source_count", "built", "authored_exact",
            "built_and_authored_exact", "built_but_authored_wrong", "decoder_abstained")},
        "run_summary": {"path": str(directory / "summary.json"), "sha256": sha(directory / "summary.json")},
        "build_summary": {"path": str(builds / "summary.json"), "sha256": sha(builds / "summary.json")},
        "target_reference": target_ref, "references_opened_after_build_verification": True,
        "compiled_artifact_bytes_reverified": False,
        "compiled_artifact_evidence": "Module coverage and output hashes recorded by actual runner; temporary olean bytes were removed",
        "label_scope": "Authored synthetic references; agreement is not independent legal-source validation",
        "semantic_correctness_verified": False, "qualified": False, "all_logic_families_supported": False,
        "producer_sha256": sha(__file__)}
    write(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-directory", "build-directory", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    summarize(args.run_directory, args.build_directory, args.output)
