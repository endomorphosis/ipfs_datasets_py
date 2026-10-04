#!/usr/bin/env python3
"""Verify completed qualified builds, then compare frozen authored references.

Compilation and structural reference agreement are separate observations. The
reference labels are authored synthetic examples, not adjudicated legal truth.
The old and new compilation profiles have different declared clock semantics.
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
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
QUALIFIERS = ("conditions", "exceptions", "temporal")
POLICY = "synthetic-activation-waiver-closed-duration/v1"
SCHEMA = "legal-qualified-decoder-posthoc-reference-comparison/v1"
MAX_BYTES = 64 * 1024 * 1024


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value, *, ascii=False):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=ascii, allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    require(path.is_file() and path.stat().st_size <= MAX_BYTES, "bounded completed JSON required: " + str(path))
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite JSON: " + value)
    return json.loads(path.read_bytes(), object_pairs_hook=unique, parse_constant=reject)


def read_ref(reference):
    require(sha(reference["path"]) == reference["sha256"], "artifact hash differs: " + reference["path"])
    return read(reference["path"])


def expected_interpretation(candidate):
    """Independently restate the experiment's declared, nonlegal convention."""
    from ipfs_datasets_py.logic.autoformal import legal_canonical_qualified as bridge
    result = bridge.interpretation_skeleton(candidate)
    for rule, declaration in zip(candidate["canonical_ir"]["rules"], result["formulas"]):
        declaration["activation_scope"] = "all_conditions_at_evaluation_origin"
        declaration["exception_scope"] = "activation_time_waiver"
        for facet in ("conditions", "exceptions"):
            for binding in declaration[facet]:
                binding["expression"] = {"op": "atom", "predicate": {
                    "name": "declared_qualifier", "arguments": [binding["source_text"]]}}
        if rule["temporal"]:
            require(len(rule["temporal"]) == 1, "multiple temporal qualifiers unsupported")
            literal = rule["temporal"][0]
            match = re.fullmatch(r"(within|for at least) ([1-9][0-9]*) (day|hour)(s?)", literal)
            require(match is not None, "calendar or unsupported temporal literal")
            amount = int(match[2])
            require(match[4] == ("s" if amount != 1 else ""), "duration plural differs")
            declaration["temporal"] = {
                "source_index": len(rule["conditions"]), "source_text": literal,
                "temporal_kind": "within_duration" if match[1] == "within" else "minimum_duration",
                "quantity": amount, "unit": match[3], "time_domain": "discrete_nat",
                "origin": "caller_supplied_evaluation_time", "lower_inclusive": True, "upper_inclusive": True}
    return result


def verify_selected_entry(source, prediction, entry):
    """Detect changed or omitted fields before consulting any reference IR."""
    candidate = {"candidate_id": source["id"], "source_text": source["source_text"],
                 "source_sha256": source["source_sha256"], "canonical_ir": prediction["canonical_ir"]}
    require(entry.get("candidate") == candidate, "selected candidate differs from exact frozen generation")
    require(entry.get("interpretation") == expected_interpretation(candidate),
            "explicit interpretation changed or omitted a predicted qualifier")
    return candidate


def verify_receipt(reference, entries, *, qualified):
    """Check persisted source, manifests, module coverage and executable hashes.

    Compiled oleans were captured and hashed by the bounded runner, then removed;
    their bytes cannot be rehashed here. Receipts are not trusted signatures.
    """
    from ipfs_datasets_py.logic.autoformal import legal_qualified_lake as new
    from ipfs_datasets_py.logic.autoformal import legal_pilot_lake as old
    receipt = read_ref(reference)
    stripped = dict(receipt)
    recorded_hash = stripped.pop("receipt_sha256")
    require(digest(stripped) == recorded_hash, "internal receipt hash differs")
    require(receipt["target"] == "legal", "wrong Lake target")
    require(all(receipt.get(flag) is False for flag in ("admitted", "formalized", "source_semantics_verified", "proof_authority")),
            "receipt grants unsupported semantic or proof authority")
    prepared = (new.prepare_qualified_legal(entries, toolchain=receipt["toolchain"]) if qualified
                else old.prepare_legal_pilot(entries, toolchain=receipt["toolchain"]))
    manifest = prepared.to_dict()
    folder = Path(reference["path"]).parent
    stem = "qualified" if qualified else "pilot"
    require(read(folder / (stem + "-manifest.json")) == manifest, "persisted manifest differs from replay")
    require(all(receipt.get(key) == value for key, value in manifest.items()
                if key not in {"status", "backend_executed"}), "receipt preparation fields differ")
    for filename, body in prepared.files:
        require((folder / filename).read_bytes() == body.encode(), "persisted emitted source differs: " + filename)
    require(all(sha(path) == wanted for path, wanted in receipt["producer_pins"].items()), "receipt producer implementation differs")
    require(receipt["all_candidates_supported"] is True, "selected receipt unexpectedly unsupported")
    root = "LegalQualified" if qualified else "LegalPilot"
    modules = [root + ".Prelude", *(candidate["module"] for candidate in receipt["candidates"]), root]
    expected_artifacts = {".lake/build/lib/lean/" + module.replace(".", "/") + ".olean" for module in modules}
    artifacts = receipt.get("artifact_sha256", {})
    require(all(re.fullmatch(r"[0-9a-f]{64}", value) for value in artifacts.values()), "invalid olean digest")
    observed_coverage = set(artifacts) == expected_artifacts
    require(receipt["manifest_coverage_passed"] is observed_coverage, "receipt artifact coverage claim differs")
    require(receipt["compiled_modules"] == [module for module in modules
        if ".lake/build/lib/lean/" + module.replace(".", "/") + ".olean" in artifacts], "compiled module list differs")
    command = receipt["command"]
    require(type(command) is list and len(command) == 3 and command[1:] == ["build", "legal"], "command differs from exact legal target")
    require(digest(command) == receipt["command_sha256"], "command hash differs")
    binaries = receipt["binary_sha256"]
    require(len(binaries) == 2 and {Path(path).name for path in binaries} == {"lake", "lean"}, "Lean and Lake ELF pins required")
    require(command[0] in binaries, "executed Lake differs from pinned executable")
    require(all(sha(path) == wanted for path, wanted in binaries.items()), "installed executable hash differs")
    require(receipt["binary_pins_match"] is True, "binary changed during build")
    version = receipt["toolchain"].split(":v", 1)[1]
    require(set(receipt["version_probe"]) == {"lake", "lean"}, "both version probes required")
    for name, probe in receipt["version_probe"].items():
        match = re.search(r"Lean \(?version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)", probe["stdout"])
        require(probe["returncode"] == 0 and probe["command"] == [next(path for path in binaries if Path(path).name == name), "--version"]
                and match is not None and match[1] == version, "version probe does not bind pinned compiler")
    for stream in ("stdout", "stderr"):
        require(hashlib.sha256(receipt[stream].encode()).hexdigest() == receipt[stream + "_sha256"], "output stream hash differs")
    if receipt["build_passed"]:
        require(receipt["status"] == "passed" and receipt["backend_executed"] is True
                and receipt["returncode"] == 0 and observed_coverage, "build success lacks execution or complete coverage")
        require(all(receipt.get(flag) is False for flag in ("timed_out", "output_truncated", "workspace_limit_exceeded", "resource_exhausted", "unavailable", "cancelled")),
                "build success conflicts with process failure flags")
        require(not re.search(r"\b(?:sorry|sorryAx)\b", receipt["stdout"] + receipt["stderr"]), "placeholder in successful build output")
    return receipt


def compare_ir(prediction, reference):
    """Structural comparison only; missing/extra qualifiers retain multiplicity."""
    rules = prediction["rules"] if prediction is not None else []
    expected = reference["rules"]
    facets = {facet: [rule[facet] for rule in rules] == [rule[facet] for rule in expected] for facet in FACETS}
    omitted, added = {}, {}
    for facet in QUALIFIERS:
        omissions = additions = 0
        for index in range(max(len(rules), len(expected))):
            actual = Counter(rules[index][facet]) if index < len(rules) else Counter()
            wanted = Counter(expected[index][facet]) if index < len(expected) else Counter()
            omissions += sum((wanted - actual).values())
            additions += sum((actual - wanted).values())
        omitted[facet], added[facet] = omissions, additions
    return {"exact_authored_reference_match": prediction == reference, "facet_matches": facets,
            "omitted_reference_qualifiers": omitted, "additional_predicted_qualifiers": added}


def summarize(run_directory, build_directory, old_build_directory, output):
    from ipfs_datasets_py.logic.autoformal import legal_qualified_lake as gate
    from ipfs_datasets_py.logic.autoformal import legal_pilot_lake as old_gate
    directory, builds, old_builds = map(lambda p: Path(p).resolve(), (run_directory, build_directory, old_build_directory))
    # Hard barrier: no authored target file is opened before build completion.
    require((builds / "summary.json").is_file(), "completed qualified build summary required before reference access")
    completed = read(builds / "summary.json")
    require(completed["schema"] == "legal-qualified-decoder-builds/v1", "wrong completed summary schema")
    require(completed["canonical_references_used_for_selection"] is False and completed["semantic_scores_used_for_selection"] is False,
            "build selections used reference targets")
    for path, wanted in completed["input_sha256"].items():
        require(sha(path) == wanted, "completed build input pin changed")
    policy = read_ref(completed["interpretation_policy"])
    require(policy["id"] == POLICY and policy["source_semantics_verified"] is False, "unsupported experimental policy")
    selections = read_ref(completed["frozen_selections"])
    original, prepared, plan = read(directory / "summary.json"), read(directory / "prepared-inputs.json"), read(directory / "plan.json")
    require(sha(directory / "plan.json") == original["plan_sha256"], "original plan hash differs")
    frozen = read_ref(original["generation_frozen"])
    sources = prepared["challenge"]
    require(all("canonical_ir" not in source for source in sources), "generation source inputs contain targets")
    sources_by_id = {source["id"]: source for source in sources}
    require(len(sources_by_id) == len(sources), "duplicate source ids")
    originals = {model["name"]: model for model in original["runs"]}
    selected_models = {model["name"]: model for model in selections}
    model_summaries = {model["name"]: model for model in completed["models"]}
    require(len(originals) == len(selected_models) == len(model_summaries) == 15
            and set(originals) == set(selected_models) == set(model_summaries), "all fifteen models required")
    require(sum(model["arm"] == "parent_source" for model in original["runs"]) == 3, "three parent controls required")
    old_summary = read(old_builds / "summary.json")
    old_models = {model["name"]: model for model in old_summary["models"]}
    require(set(old_models) == set(originals), "old/new model coverage differs")
    for path, wanted in old_summary["input_sha256"].items():
        require(sha(path) == wanted, "old build input pin differs")
    verified, generations = {}, {}
    for name in sorted(originals):
        selected, model = selected_models[name], model_summaries[name]
        require(model["arm"] == selected["arm"] == originals[name]["arm"], "arm identity differs")
        payload = read(directory / name / "challenge-generation.json")
        require(digest(payload, ascii=True) == frozen[name]["challenge"], "generation freeze differs")
        require(payload["generation_inputs_contained_references"] is False, "generation accessed reference targets")
        predictions = payload["rows"]
        require(predictions == [row for report in payload["reports"] for row in report["rows"]], "generation wrapper differs")
        require(all(report["checkpoint_sha256"] == originals[name]["checkpoint"]["sha256"]
                    and report["target_access"] is False and report["teacher_forcing"] is False for report in payload["reports"]), "checkpoint or generation provenance differs")
        require(len(predictions) == len(sources), "prediction count differs")
        generation_by_id = {}
        for source, prediction in zip(sources, predictions):
            require(source["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest() == prediction["source_sha256"], "source hash differs")
            require("id" not in prediction or prediction["id"] == source["id"], "prediction identity differs")
            require(prediction["target_access"] is False and prediction["teacher_forcing"] is False, "prediction used targets")
            generation_by_id[source["id"]] = prediction
        generations[name] = generation_by_id
        rows_by_id = {entry["candidate"]["candidate_id"]: entry for entry in selected["rows"]}
        excluded = {row["candidate_id"]: row for row in selected["excluded"]}
        require(len(rows_by_id) == len(selected["rows"]) and len(excluded) == len(selected["excluded"])
                and not set(rows_by_id) & set(excluded) and set(rows_by_id) | set(excluded) == set(sources_by_id), "selection/exclusion partition differs")
        old_expected = []
        for index, source in enumerate(sources):
            prediction = predictions[index]
            if prediction["status"] != "decoded":
                require(source["id"] in excluded and excluded[source["id"]]["reason"] == "decoder_abstained", "abstention exclusion differs")
                continue
            candidate = {"candidate_id": source["id"], "source_text": source["source_text"],
                         "source_sha256": source["source_sha256"], "canonical_ir": prediction["canonical_ir"]}
            old_prepared = old_gate.prepare_legal_pilot([candidate], toolchain=completed["toolchain"]).to_dict()
            if old_prepared["all_candidates_supported"]:
                old_expected.append(candidate)
            try:
                expected_entry = {"candidate": candidate, "interpretation": expected_interpretation(candidate)}
                supported = gate.prepare_qualified_legal([expected_entry], toolchain=completed["toolchain"]).to_dict()["all_candidates_supported"]
            except (ValueError, KeyError, TypeError):
                supported = False
            require((source["id"] in rows_by_id) is supported, "new profile selection differs from independent eligibility replay")
            if supported:
                verify_selected_entry(source, prediction, rows_by_id[source["id"]])
            else:
                require(excluded[source["id"]]["reason"] == "explicit_interpretation_unsupported", "unsupported exclusion differs")
        for identity, exclusion in excluded.items():
            require(exclusion["row_index"] == sources.index(sources_by_id[identity])
                    and exclusion["source_sha256"] == sources_by_id[identity]["source_sha256"], "exclusion source binding differs")
        require([entry["candidate"]["candidate_id"] for entry in selected["rows"]] == [source["id"] for source in sources if source["id"] in rows_by_id], "selection order changed")
        observed_built, receipt_verifications = [], []
        cursor = 0
        for build in model["builds"]:
            batch = selected["rows"][cursor:cursor + build["candidate_count"]]
            require(len(batch) == build["candidate_count"] > 0, "receipt batch coverage differs")
            receipt = verify_receipt(build["receipt"], batch, qualified=True)
            require(all(build[key] == receipt[key] for key in ("build_passed", "manifest_coverage_passed", "backend_executed", "returncode", "command")), "build summary differs from receipt")
            if receipt["build_passed"]:
                observed_built.extend(entry["candidate"]["candidate_id"] for entry in batch)
            receipt_verifications.append({"path": build["receipt"]["path"], "candidate_count": len(batch), "verified": True})
            cursor += len(batch)
        require(cursor == len(selected["rows"]), "selected rows missing build receipts")
        require(model["built_count"] == len(observed_built) and model["supported_count"] == len(rows_by_id)
                and model["excluded_count"] == len(excluded) and model["source_count"] == len(sources)
                and model["decoded_count"] == sum(row["status"] == "decoded" for row in predictions), "model counts differ")
        old_model = old_models[name]
        require(read_ref(old_model["selected_candidates"]) == old_expected, "old support differs from exact frozen predictions")
        require(old_model["supported_count"] == len(old_expected) and old_model["decoded_count"] == model["decoded_count"]
                and old_model["challenge_count"] == len(sources), "old model source/support counts differ")
        old_built, old_cursor = [], 0
        for build in old_model["builds"]:
            batch = old_expected[old_cursor:old_cursor + build["candidate_count"]]
            require(len(batch) == build["candidate_count"] > 0, "old receipt batch coverage differs")
            receipt = verify_receipt(build["receipt"], batch, qualified=False)
            require(all(build[key] == receipt[key] for key in ("build_passed", "manifest_coverage_passed", "backend_executed", "returncode", "command")), "old build summary differs from receipt")
            if receipt["build_passed"]:
                old_built.extend(candidate["candidate_id"] for candidate in batch)
            old_cursor += len(batch)
        require(old_cursor == len(old_expected) and old_model["built_candidate_count"] == len(old_built), "old build coverage differs")
        unsupported = Counter()
        for entry in excluded.values():
            detail = entry.get("detail", "").lower()
            reason = ("decoder_abstained" if entry["reason"] == "decoder_abstained" else
                      "calendar_or_unsupported_temporal" if "calendar" in detail or "duration" in detail else
                      "other_explicit_interpretation_unsupported")
            unsupported[reason] += 1
        verified[name] = {"arm": model["arm"], "source_count": len(sources),
            "decoded_count": model["decoded_count"], "new_supported_ids": list(rows_by_id), "new_built_ids": observed_built,
            "old_supported_ids": [candidate["candidate_id"] for candidate in old_expected], "old_built_ids": old_built,
            "unsupported_reason_counts": dict(sorted(unsupported.items())), "exclusions": selected["excluded"],
            "receipt_verifications": receipt_verifications, "all_selected_candidates_equal_original_generation": True,
            "all_predicted_qualifiers_retained_in_selected_interpretations": True}
    require(completed["totals"] == {key: sum(model[key] for model in completed["models"]) for key in
            ("source_count", "decoded_count", "supported_count", "built_count", "excluded_count")}, "qualified summary totals differ")
    # First authored-reference access occurs only after every build/selection check.
    targets = read_ref(plan["challenge_targets"])
    references = {row["id"]: row for row in targets["targets"]}
    require(len(references) == len(targets["targets"]) == len(sources) and set(references) == set(sources_by_id), "authored reference coverage differs")
    corpus = read_ref(plan["corpus"])
    commitments = {row["id"]: row["canonical_target_sha256"] for row in corpus["splits"]["challenge"]}
    for identity, reference in references.items():
        require(reference["source_sha256"] == sources_by_id[identity]["source_sha256"]
                and digest(reference["canonical_ir"], ascii=True) == reference["canonical_target_sha256"] == commitments[identity], "authored reference source/IR commitment differs")
    for name, model in verified.items():
        comparisons = []
        for identity, prediction in generations[name].items():
            comparison = compare_ir(prediction["canonical_ir"] if prediction["status"] == "decoded" else None, references[identity]["canonical_ir"])
            comparisons.append({"candidate_id": identity, "source_sha256": sources_by_id[identity]["source_sha256"],
                                "prediction_status": prediction["status"], "old_built": identity in model["old_built_ids"],
                                "new_built": identity in model["new_built_ids"], **comparison})
        model["reference_comparison"] = comparisons
        model["comparison_counts"] = aggregate(comparisons)
        expected_facets = originals[name]["scores"]["challenge"]["facets"]
        require(model["comparison_counts"]["all_predictions_facet_matches"] == expected_facets, "posthoc facet comparison differs from original frozen prediction scores")
    groups = {}
    for group_name, include_parent in (("selected_12_heads", False), ("parent_3_heads", True)):
        members = [name for name, model in verified.items() if (model["arm"] == "parent_source") is include_parent]
        require(len(members) == (3 if include_parent else 12), "head/control grouping differs")
        comparisons = [row for name in members for row in verified[name]["reference_comparison"]]
        groups[group_name] = {"models": members, "model_count": len(members), **aggregate(comparisons),
                              "unsupported_reason_counts": dict(sum((Counter(verified[name]["unsupported_reason_counts"]) for name in members), Counter()))}
    result = {"schema": SCHEMA, "groups": groups, "models": verified,
        "input_artifacts": {"qualified_summary": {"path": str(builds / "summary.json"), "sha256": sha(builds / "summary.json")},
                            "old_summary": {"path": str(old_builds / "summary.json"), "sha256": sha(old_builds / "summary.json")},
                            "references": plan["challenge_targets"]},
        "verification": {"completed_build_summary_required_before_reference_access": True,
            "references_opened_only_after_all_selection_and_receipt_checks": True,
            "all_selected_candidates_equal_frozen_generation": True, "all_predicted_qualifiers_retained": True,
            "persisted_lean_source_and_manifest_coverage_verified": True, "executable_hashes_recomputed": True,
            "compiled_olean_bytes_recomputed": False, "receipt_checks_are_signature_verification": False},
        "profile_comparison_scope": "Old canonical-unqualified/v1 and new canonical-explicit-qualified/v1 use different declared modal clock annotations; larger syntactic build coverage does not establish equivalent interpretations.",
        "reference_scope": "Authored synthetic canonical IR comparison only; no expert-reviewed legal truth.",
        "runtime_provenance_scope": "Executable ELF hashes exclude Lean/Lake shared libraries, imported standard-library oleans and system runtime libraries.",
        "canonical_facets_compared_per_prediction": len(FACETS), "qualified": False, "admitted": False,
        "source_semantics_verified": False, "new_training_performed": False, "new_inference_performed": False,
        "summarizer_sha256": sha(__file__)}
    with Path(output).open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return result


def aggregate(comparisons):
    result = {"prediction_count": len(comparisons),
              "all_predictions_facet_matches": {facet: sum(row["facet_matches"][facet] for row in comparisons) for facet in FACETS},
              "all_predictions_exact_authored_reference_matches": sum(row["exact_authored_reference_match"] for row in comparisons)}
    for profile in ("old", "new"):
        built = [row for row in comparisons if row[profile + "_built"]]
        result[profile + "_built_count"] = len(built)
        result[profile + "_compiled_reference_mismatches"] = sum(not row["exact_authored_reference_match"] for row in built)
        result[profile + "_compiled_facet_matches"] = {facet: sum(row["facet_matches"][facet] for row in built) for facet in FACETS}
        result[profile + "_compiled_omitted_reference_qualifiers"] = {facet: sum(row["omitted_reference_qualifiers"][facet] for row in built) for facet in QUALIFIERS}
        result[profile + "_compiled_additional_predicted_qualifiers"] = {facet: sum(row["additional_predicted_qualifiers"][facet] for row in built) for facet in QUALIFIERS}
    result["all_prediction_facets_unchanged_between_profiles"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--build-directory", required=True)
    parser.add_argument("--old-build-directory", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = summarize(args.run_directory, args.build_directory, args.old_build_directory, args.output)
    print(json.dumps({"output": args.output, "groups": result["groups"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
