"""Exact free-running reconstruction diagnostics for seven-facet deontic IR.

This evaluator reads explicit compiler weak labels after generation. It does
not train, decode, run syntax/proof tools, or establish independent held-out
fidelity. Loss values and reported syntax success never contribute to a match.
Targets use the closed row shape ``{id, source_text, canonical_ir}``; prediction
rows are the complete rows emitted by ``modal_latent_formula.infer``. Extra
prediction metadata is retained by its producer, not interpreted as authority.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json

SCHEMA = "typed-deontic-free-running-fidelity/v1"
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
MAX_ROWS = 4096
MAX_RULES = 128
MAX_ATOM_CHARS = 4096
MAX_QUALIFIERS = 1000
_FALSE = {"qualified": False, "admitted": False, "formalized": False,
          "roundtrip_ok": False, "proof_authority": False,
          "semantic_correctness_verified": False, "heldout_fidelity_verified": False,
          "independent_validation": False, "lake_executed": False,
          "promotion_performed": False, "publication_performed": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _id(value):
    return type(value) is str and 0 < len(value) <= 512 and bool(value.strip())


def _atom(value, *, blank=False):
    return (type(value) is str and len(value) <= MAX_ATOM_CHARS
            and (blank or bool(value.strip())))


def _ir_error(value):
    """Check the closed JSON shape, without normalization or a grammar claim."""
    if type(value) is not dict or set(value) != {"rules"}:
        return "canonical_ir_requires_exact_rules_field"
    rules = value["rules"]
    if type(rules) is not list or not 1 <= len(rules) <= MAX_RULES:
        return "rules_require_nonempty_bounded_list"
    for rule in rules:
        if type(rule) is not dict or set(rule) != set(FACETS):
            return "rule_requires_exact_seven_facets"
        if rule["modality"] not in ("O", "P", "F") or type(rule["modality"]) is not str:
            return "invalid_modality"
        if not all(_atom(rule[key], blank=key == "object") for key in FACETS[:4]):
            return "invalid_scalar_facet"
        for facet in FACETS[4:]:
            values = rule[facet]
            if (type(values) is not list or len(values) > MAX_QUALIFIERS
                    or not all(_atom(item) for item in values)):
                return "invalid_qualifier_facet"
            if values != sorted(set(values)):
                return "qualifiers_must_be_sorted_unique_without_normalization"
    return None


def _targets(rows):
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= MAX_ROWS,
             "targets require a nonempty bounded list or tuple")
    result = {}
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text", "canonical_ir"},
                 "targets require exactly id, source_text, canonical_ir")
        _require(_id(row["id"]) and row["id"] not in result, "target IDs must be unique bounded strings")
        _require(type(row["source_text"]) is str and row["source_text"].strip()
                 and len(row["source_text"]) <= 16384, "target source_text must be bounded nonempty text")
        error = _ir_error(row["canonical_ir"])
        _require(error is None, "invalid target: " + str(error))
        result[row["id"]] = row
    return result


def _fraction(matched, total):
    return {"matched": matched, "total": total, "fraction": matched / total if total else None}


def _output_error(row, ir):
    if "formal_outputs" not in row:
        return None
    outputs = row["formal_outputs"]
    if type(outputs) is not list or len(outputs) != len(ir["rules"]):
        return "formal_outputs_rule_count_disagrees"
    for output, rule in zip(outputs, ir["rules"]):
        if (type(output) is not dict or output.get("family") != "deontic"
                or output.get("format") != "typed-deontic-rule/v1"
                or output.get("payload") != rule):
            return "formal_outputs_disagree_with_canonical_ir"
    return None


def compare_free_running_formulas(prediction_report, targets, *, partition="unspecified"):
    """Compare complete generated IR against explicit, unverified weak labels.

    Every requested target remains in every accuracy denominator. Duplicate,
    missing, unexpected or unidentifiable prediction IDs invalidate coverage;
    duplicate rows never receive credit by choosing a favorable occurrence.
    Each row must explicitly declare ``teacher_forcing=False`` and
    ``target_access=False`` and match its source hash. Those declarations are
    checked, not independently proven. Top-level declarations are optional,
    but contradictory ones invalidate the evaluation. An honest abstention is
    operationally complete and receives zero reconstruction credit. A malformed
    generated rule is a measurable failure, distinct from an abstention.

    ``valid_evaluation`` concerns coverage and generation/source evidence.
    ``operational_complete`` additionally excludes malformed output records.
    Neither boolean grants semantic qualification or verifies split membership.
    Rule and qualifier order are compared exactly; no facet is dropped, guessed
    from source text, normalized, or replaced by a teacher-forced loss.
    """
    expected = _targets(targets)
    _require(type(partition) is str and 0 < len(partition) <= 128, "bounded partition label required")
    _require(type(prediction_report) is dict, "prediction_report must be an inference report object")
    predictions = prediction_report.get("rows")
    _require(type(predictions) is list and len(predictions) <= MAX_ROWS,
             "prediction_report.rows must be a bounded list")
    envelope_issues = []
    for field in ("teacher_forcing", "target_access"):
        if field in prediction_report and prediction_report[field] is not False:
            envelope_issues.append("report_" + field + "_not_false")
    derived_decoded = sum(type(row) is dict and row.get("status") == "decoded" for row in predictions)
    if "decoded_count" in prediction_report:
        count = prediction_report["decoded_count"]
        if type(count) is not int or count != derived_decoded:
            envelope_issues.append("reported_decoded_count_disagrees_with_rows")

    indexed, invalid_id_rows = defaultdict(list), []
    for index, row in enumerate(predictions):
        if type(row) is not dict or not _id(row.get("id")):
            invalid_id_rows.append(index)
        else:
            indexed[row["id"]].append(row)
    missing = sorted(set(expected) - set(indexed))
    unexpected = sorted(set(indexed) - set(expected))
    duplicates = {key: len(values) for key, values in sorted(indexed.items()) if len(values) != 1}
    coverage_valid = not (missing or unexpected or duplicates or invalid_id_rows)

    target_signatures = defaultdict(list)
    for key, row in expected.items():
        target_signatures[_sha(_json(row["canonical_ir"]))].append(key)
    facet_matches = Counter()
    counts = Counter()
    actor_confusions = Counter()
    output_signatures = Counter()
    predicted_actors = set()
    target_actors = {tuple(rule["actor"] for rule in row["canonical_ir"]["rules"])
                     for row in expected.values()}
    cross_targets, source_copy_ids, diagnostics = [], [], []
    evidence_ok = not envelope_issues
    generation_envelope_ok = not any(issue.startswith("report_teacher_forcing_") or
                                     issue.startswith("report_target_access_") for issue in envelope_issues)
    for key, target in expected.items():
        target_rules = target["canonical_ir"]["rules"]
        diagnostic = {"id": key, "status": "missing", "reasons": [],
                      "target_rule_count": len(target_rules), "predicted_rule_count": None,
                      "rule_count_exact": False, "exact": False,
                      "facets": {facet: False for facet in FACETS},
                      "target_ir_sha256": _sha(_json(target["canonical_ir"])),
                      "prediction_ir_sha256": None,
                      "source_sha256": _sha(target["source_text"])}
        rows = indexed.get(key, [])
        if len(rows) != 1:
            diagnostic["status"] = "duplicate" if rows else "missing"
            diagnostic["reasons"] = ["ambiguous_duplicate_prediction_id" if rows else "missing_prediction_id"]
            counts[diagnostic["status"]] += 1
            diagnostics.append(diagnostic)
            continue
        row = rows[0]
        provenance_reasons = [field + "_not_explicitly_false" for field in
                              ("teacher_forcing", "target_access") if row.get(field) is not False]
        if row.get("source_sha256") != diagnostic["source_sha256"]:
            provenance_reasons.append("prediction_source_hash_mismatch_or_missing")
        if not generation_envelope_ok:
            provenance_reasons.append("report_contradicts_free_running_generation")
        if provenance_reasons:
            diagnostic.update(status="unverifiable_generation", reasons=provenance_reasons)
            counts["unverifiable_generation"] += 1
            evidence_ok = False
            diagnostics.append(diagnostic)
            continue

        if row.get("status") == "abstained":
            if (row.get("canonical_ir") is not None or row.get("formal_outputs", []) != []
                    or row.get("formula_text") is not None):
                diagnostic.update(status="malformed", reasons=["abstention_contains_formula_output"])
                counts["malformed"] += 1
            else:
                diagnostic.update(status="abstained", reasons=["decoder_abstained"])
                counts["abstained"] += 1
            diagnostics.append(diagnostic)
            continue
        ir = row.get("canonical_ir")
        if type(ir) is dict and type(ir.get("rules")) is list:
            diagnostic["predicted_rule_count"] = len(ir["rules"])
        error = _ir_error(ir)
        if row.get("status") != "decoded":
            error = "unknown_or_missing_decoder_status"
        if error is None:
            error = _output_error(row, ir)
        if error is not None:
            diagnostic.update(status="malformed", reasons=[error])
            counts["malformed"] += 1
            diagnostics.append(diagnostic)
            continue

        rules = ir["rules"]
        counts["decoded"] += 1
        diagnostic.update(status="decoded", rule_count_exact=len(rules) == len(target_rules),
                          prediction_ir_sha256=_sha(_json(ir)))
        diagnostic["facets"] = {facet: [rule[facet] for rule in rules] ==
                                [rule[facet] for rule in target_rules] for facet in FACETS}
        diagnostic["exact"] = ir == target["canonical_ir"]
        diagnostic["reasons"] = ["facet_mismatch:" + facet for facet in FACETS if not diagnostic["facets"][facet]]
        if not diagnostic["rule_count_exact"]:
            diagnostic["reasons"].insert(0, "rule_count_mismatch")
        facet_matches.update(facet for facet, match in diagnostic["facets"].items() if match)
        counts["exact"] += int(diagnostic["exact"])
        counts["rule_count_exact"] += int(diagnostic["rule_count_exact"])
        actors = tuple(rule["actor"] for rule in rules)
        expected_actors = tuple(rule["actor"] for rule in target_rules)
        predicted_actors.add(actors)
        if actors != expected_actors:
            actor_confusions[(expected_actors, actors)] += 1
            diagnostic["actor_mismatch"] = {"expected": list(expected_actors), "predicted": list(actors)}
        signature = diagnostic["prediction_ir_sha256"]
        output_signatures[signature] += 1
        if not diagnostic["exact"] and signature in target_signatures:
            cross_targets.append({"id": key, "matching_other_target_ids": list(target_signatures[signature])})
        if row.get("formula_text") == target["source_text"]:
            source_copy_ids.append(key)
        diagnostics.append(diagnostic)

    total = len(expected)
    valid_evaluation = coverage_valid and evidence_ok
    exact = _fraction(counts["exact"], total)
    exact["complete"] = valid_evaluation and counts["exact"] == total
    return {"schema": SCHEMA, "partition": partition, "partition_membership_verified": False,
            "target_origin": "caller_supplied_compiler_weak_labels", "target_origin_verified": False,
            "teacher_forcing": False, "metric_target_access": True,
            "generation_declarations_verified": coverage_valid and evidence_ok,
            "generation_declarations_are_independent_proof": False,
            "valid_evaluation": valid_evaluation,
            "operational_complete": valid_evaluation and counts["malformed"] == 0,
            "all_targets_decoded": valid_evaluation and counts["decoded"] == total,
            "coverage": {"valid": coverage_valid, "target_count": total,
                         "prediction_row_count": len(predictions), "missing_ids": missing,
                         "unexpected_ids": unexpected, "duplicate_ids": duplicates,
                         "invalid_id_row_indices": invalid_id_rows},
            "envelope_issues": envelope_issues,
            "counts": {name: counts[name] for name in ("decoded", "abstained", "malformed",
                         "unverifiable_generation", "missing", "duplicate")},
            "exact_reconstruction": exact,
            "rule_count_exact": _fraction(counts["rule_count_exact"], total),
            "facets": {facet: _fraction(facet_matches[facet], total) for facet in FACETS},
            "actor_confusions": [{"expected": list(expected_actor), "predicted": list(predicted_actor),
                                  "count": count} for (expected_actor, predicted_actor), count
                                 in sorted(actor_confusions.items())],
            "diagnostics": {"unique_target_formulas": len(target_signatures),
                            "unique_decoded_formulas": len(output_signatures),
                            "single_formula_collapse": (counts["decoded"] >= 2 and len(output_signatures) == 1
                                                        and len(target_signatures) > 1),
                            "single_actor_collapse": (counts["decoded"] >= 2 and len(predicted_actors) == 1
                                                      and len(target_actors) > 1),
                            "cross_target_matches": cross_targets,
                            "formula_display_copies_source_ids": source_copy_ids,
                            "similarity_anomalies_prove_target_copying": False},
            "rows": diagnostics,
            "comparison_scope": "exact closed seven-facet JSON and rule order; no source-law equivalence claim",
            "syntax_checks_contribute_to_exact_match": False,
            "teacher_forced_losses_contribute_to_exact_match": False,
            "training_executed": False, **_FALSE}


__all__ = ["compare_free_running_formulas", "FACETS", "SCHEMA"]


# Additive, pure post-freeze consumer of the existing reconstruction evaluator.
F18_MATCHED_SCHEMA = "f18-frozen-matched-arm-fidelity/v1"
_F18_ARMS = ("parent", "coefficient_0", "coefficient_025")
_F18_PARENT_CAPTURE = "modality-conditions-retention-adapter-target-free-head-capture/v1"
_F18_TRAINED_PANEL = "f18-paired-target-free-panel/v1"
_F18_TRAINED_CAPTURE = "conditions-fullspan-four-tensor-target-free-head-capture/v1"
_F18_JOINT_PANEL = "modality-conditions-retention-joint-panel/v1"


def _f18_ids(values, *, count=None):
    _require(type(values) is list and all(_id(item) for item in values)
             and len(set(values)) == len(values), "F18 IDs require an ordered unique string list")
    _require(count is None or len(values) == count, "F18 explicit roster cardinality differs")
    return set(values)


def _f18_declarations(value, issues, where, *, required=False):
    for field in ("teacher_forcing", "target_access"):
        if (required or field in value) and value.get(field) is not False:
            issues.append(where + ":" + field + "_not_false")


def _f18_raw_rows(panel, *, parent, panel_name):
    _require(type(panel) is dict, "F18 raw panel object required")
    issues = []
    _f18_declarations(panel, issues, "raw_panel", required=True)
    if parent:
        _require(panel.get("schema") == _F18_PARENT_CAPTURE, "original F18 parent capture schema required")
        chunks = [panel]
    else:
        _require(panel.get("schema") == _F18_TRAINED_PANEL and panel.get("panel") == panel_name,
                 "trained F18 raw panel schema/name differs")
        chunks = panel.get("chunks")
        _require(type(chunks) is list and 1 <= len(chunks) <= MAX_ROWS, "bounded F18 capture chunks required")
    rows = []
    for index, chunk in enumerate(chunks):
        _require(type(chunk) is dict, "F18 capture object required")
        _require(parent or chunk.get("schema") == _F18_TRAINED_CAPTURE, "original F18 trained chunk schema required")
        _f18_declarations(chunk, issues, "chunk:" + str(index), required=True)
        inference, occurrences = chunk.get("inference"), chunk.get("occurrences")
        _require(type(inference) is dict and type(inference.get("rows")) is list
                 and type(occurrences) is list and len(inference["rows"]) == len(occurrences)
                 and 1 <= len(occurrences) <= MAX_ROWS, "F18 inference/occurrence lengths differ")
        if type(chunk.get("actual_source_forwards")) is not int or chunk["actual_source_forwards"] != len(occurrences):
            issues.append("chunk:" + str(index) + ":source_count_differs")
        if type(chunk.get("extra_capture_forwards")) is not int or chunk["extra_capture_forwards"] != 0:
            issues.append("chunk:" + str(index) + ":extra_capture_forwards_not_zero")
        _f18_declarations(inference, issues, "inference:" + str(index))
        if "decoded_count" in inference:
            count = inference["decoded_count"]
            derived = sum(type(row) is dict and row.get("status") == "decoded" for row in inference["rows"])
            if type(count) is not int or count != derived:
                issues.append("inference:" + str(index) + ":decoded_count_differs")
        for prediction, occurrence in zip(inference["rows"], occurrences, strict=True):
            _require(type(prediction) is dict and type(occurrence) is dict
                     and set(occurrence) == {"id", "source_sha256", "scores"},
                     "F18 original inference/occurrence objects required")
            # IDs belong to occurrence records; never substitute positional target IDs.
            row = dict(prediction)
            _f18_declarations(row, issues, "raw_row:" + str(len(rows)), required=True)
            if "id" in row:
                issues.append("raw_inference_unexpected_id")
            row["id"] = occurrence["id"]
            if row.get("source_sha256") != occurrence["source_sha256"]:
                row["source_sha256"] = None
                issues.append("raw_inference_occurrence_source_hash_differs")
            rows.append(row)
        _require(len(rows) <= MAX_ROWS, "F18 raw panel exceeds row bound")
    for field in (("source_model_forwards",) if parent else ("rows", "source_model_forwards")):
        if type(panel.get(field)) is not int or panel[field] != len(rows):
            issues.append("raw_panel:" + field + "_differs")
    return rows, issues


def _f18_joint_rows(panel):
    _require(type(panel) is dict and panel.get("schema") == _F18_JOINT_PANEL,
             "original F18 joint panel schema required")
    originals = panel.get("rows")
    _require(type(originals) is list and 1 <= len(originals) <= MAX_ROWS, "bounded F18 joint rows required")
    issues, rows = [], []
    _f18_declarations(panel, issues, "joint_panel")
    if panel.get("reference_scoring_performed") is not False:
        issues.append("joint_panel:reference_scoring_not_false")
    for original in originals:
        _require(type(original) is dict and set(original) == {"id", "result"}
                 and type(original["result"]) is dict, "F18 joint ID/result envelope required")
        row = dict(original["result"])
        _f18_declarations(row, issues, "joint_row:" + str(len(rows)), required=True)
        if "id" in row:
            issues.append("joint_result_unexpected_id")
        row["id"] = original["id"]
        # A detached evaluator view changes only this producer-specific status.
        if row.get("status") == "selected":
            row["status"] = "decoded"
        rows.append(row)
    return rows, issues


def _f18_source_coverage(rows, expected, expected_source_sha256):
    counts = Counter(row.get("id") for row in rows if _id(row.get("id")))
    invalid = [index for index, row in enumerate(rows) if not _id(row.get("id"))]
    missing, unexpected = sorted(set(expected) - set(counts)), sorted(set(counts) - set(expected))
    duplicate = {key: count for key, count in sorted(counts.items()) if count != 1}
    invalid_hashes = [index for index, row in enumerate(rows)
                      if type(row.get("source_sha256")) is not str or len(row["source_sha256"]) != 64
                      or any(char not in "0123456789abcdef" for char in row["source_sha256"])]
    mismatched_hashes = [index for index, row in enumerate(rows) if _id(row.get("id"))
                         and row.get("source_sha256") != expected_source_sha256.get(row["id"])]
    ordered = [row.get("id") for row in rows] == expected
    return {"valid": not (missing or unexpected or duplicate or invalid or invalid_hashes or mismatched_hashes) and ordered,
            "expected_count": len(expected), "observed_count": len(rows), "ordered_ids_match": ordered,
            "missing_ids": missing, "unexpected_ids": unexpected, "duplicate_ids": duplicate,
            "invalid_id_row_indices": invalid, "invalid_source_hash_row_indices": invalid_hashes,
            "source_hash_mismatch_row_indices": mismatched_hashes}


def _f18_transition(before, after):
    return "retained" if before and after else "lost" if before else "gained" if after else "still_incorrect"


def compare_f18_frozen_matched_arms(arms, targets, *, expected_ids, expected_source_sha256,
                                  retention_ids, permission_ids, unscored_ids):
    """Pure comparison of three already frozen F18 arms and explicit weak labels.

    This fixed experiment has ten ordered panels, 632 distinct source IDs, 624
    explicit compiler weak-label targets, eight explicit unscored source IDs,
    72 conditions-present TRAIN retention IDs and 32 target-permission IDs.
    Caller-supplied rosters and generation declarations are checked for internal
    consistency; their origin and freeze timing are not independently proven.
    No target ID, membership, permission label or missing output is inferred.
    This parent-relative diagnostic does not establish the separate scientific
    no-loss gates against retained N11/F15/F16/F17 comparators.
    """
    _require(type(expected_ids) is dict and len(expected_ids) == 10
             and all(_id(key) for key in expected_ids), "ten explicit ordered F18 panels required")
    panels = list(expected_ids)
    all_ids = []
    for values in expected_ids.values():
        _f18_ids(values)
        _require(values, "empty F18 source panel is not allowed")
        all_ids.extend(values)
    source_ids = _f18_ids(all_ids, count=632)
    _require(type(expected_source_sha256) is dict and set(expected_source_sha256) == source_ids
             and all(type(value) is str and len(value) == 64
                     and all(char in "0123456789abcdef" for char in value)
                     for value in expected_source_sha256.values()), "explicit source SHA-256 map for all 632 F18 IDs required")
    unscored = _f18_ids(unscored_ids, count=8)
    _require(unscored <= source_ids, "unscored F18 IDs are outside the explicit source roster")
    _require(type(targets) is dict and list(targets) == panels, "F18 weak-label panels/order differ")
    target_rows = []
    for name in panels:
        rows = targets[name]
        _require(type(rows) is list and [row.get("id") if type(row) is dict else None for row in rows]
                 == [key for key in expected_ids[name] if key not in unscored],
                 "F18 target IDs/order must equal the explicit scored roster")
        if rows:
            _targets(rows)
        target_rows.extend(rows)
    target_map = _targets(target_rows)
    _require(len(target_map) == 624, "624 explicit F18 weak-label targets required")
    _require(all(_sha(row["source_text"]) == expected_source_sha256[key] for key, row in target_map.items()),
             "F18 weak-label source text differs from explicit source commitment")
    retained, permissions = _f18_ids(retention_ids, count=72), _f18_ids(permission_ids, count=32)
    _require(retained <= set(target_map) and permissions <= set(target_map), "F18 decision roster is outside targets")
    _require(all(any(rule["conditions"] for rule in target_map[key]["canonical_ir"]["rules"])
                 for key in retention_ids), "all 72 explicit retention IDs require conditions-present weak labels")
    _require(all([rule["modality"] for rule in target_map[key]["canonical_ir"]["rules"]] == ["P"]
                 for key in permission_ids), "all 32 explicit permission IDs require single-rule P weak labels")
    _require(type(arms) is dict and set(arms) == set(_F18_ARMS), "exact parent/coefficient_0/coefficient_025 arms required")
    reports, views, panel_reports, integrity = {}, {}, [], {}
    for arm in _F18_ARMS:
        collection = arms[arm]
        _require(type(collection) is list and len(collection) == 10, "ten ordered F18 arm panels required")
        views[arm] = {mode: [] for mode in ("raw", "joint")}
        integrity[arm] = {mode: [] for mode in ("raw", "joint")}
        for name, item in zip(panels, collection, strict=True):
            _require(type(item) is dict and set(item) == {"panel", "raw", "joint"} and item["panel"] == name,
                     "F18 arm panel envelope/name/order differs")
            raw, raw_issues = _f18_raw_rows(item["raw"], parent=arm == "parent", panel_name=name)
            joint, joint_issues = _f18_joint_rows(item["joint"])
            raw_hashes, joint_hashes = defaultdict(list), defaultdict(list)
            for rows, hashes in ((raw, raw_hashes), (joint, joint_hashes)):
                for row in rows:
                    if _id(row.get("id")):
                        hashes[row["id"]].append(row.get("source_sha256"))
            if dict(raw_hashes) != dict(joint_hashes):
                raw_issues.append("raw_joint_source_occurrence_join_differs")
                joint_issues.append("raw_joint_source_occurrence_join_differs")
            entry = {"arm": arm, "panel": name, "source_count": len(expected_ids[name]),
                     "scored_count": len(targets[name]), "unscored_ids": [key for key in expected_ids[name] if key in unscored]}
            for mode, rows, issues in (("raw", raw, raw_issues), ("joint", joint, joint_issues)):
                coverage = _f18_source_coverage(rows, expected_ids[name], expected_source_sha256)
                valid = coverage["valid"] and not issues
                scored = [row for row in rows if not _id(row.get("id")) or row["id"] not in unscored]
                view = {"rows": scored, "teacher_forcing": False, "target_access": False if valid else True}
                report = compare_free_running_formulas(view, targets[name], partition=name) if targets[name] else None
                entry[mode] = {"source_coverage": coverage, "envelope_issues": issues,
                               "source_integrity_valid": valid, "weak_label_report": report}
                views[arm][mode].extend(scored)
                integrity[arm][mode].append(valid)
            panel_reports.append(entry)
        reports[arm] = {}
        for mode in ("raw", "joint"):
            reports[arm][mode] = compare_free_running_formulas({"rows": views[arm][mode], "teacher_forcing": False,
                "target_access": False if all(integrity[arm][mode]) else True}, target_rows, partition="f18_all_scored_panels")

    retention, permission = {}, {}
    for mode in ("raw", "joint"):
        diagnostic = {arm: {row["id"]: row for row in reports[arm][mode]["rows"]} for arm in _F18_ARMS}
        retention[mode] = []
        for key in retention_ids:
            before, control, candidate = (diagnostic[arm][key] for arm in _F18_ARMS)
            retention[mode].append({"id": key,
                "parent_status": before["status"], "coefficient_0_status": control["status"], "coefficient_025_status": candidate["status"],
                "parent_exact": before["exact"], "coefficient_0_exact": control["exact"], "coefficient_025_exact": candidate["exact"],
                "parent_to_coefficient_0": _f18_transition(before["exact"], control["exact"]),
                "parent_to_coefficient_025": _f18_transition(before["exact"], candidate["exact"]),
                "coefficient_0_to_coefficient_025": _f18_transition(control["exact"], candidate["exact"]),
                "facets": {facet: {"parent": before["facets"][facet], "coefficient_0": control["facets"][facet],
                    "coefficient_025": candidate["facets"][facet],
                    "parent_to_coefficient_0": _f18_transition(before["facets"][facet], control["facets"][facet]),
                    "parent_to_coefficient_025": _f18_transition(before["facets"][facet], candidate["facets"][facet]),
                    "coefficient_0_to_coefficient_025": _f18_transition(control["facets"][facet], candidate["facets"][facet])}
                    for facet in FACETS}})
        permission[mode] = []
        indexed = {arm: defaultdict(list) for arm in _F18_ARMS}
        for arm in _F18_ARMS:
            for row in views[arm][mode]:
                if _id(row.get("id")):
                    indexed[arm][row["id"]].append(row)
        for key in permission_ids:
            decisions = {}
            for arm in _F18_ARMS:
                item = diagnostic[arm][key]
                predicted = ([rule["modality"] for rule in indexed[arm][key][0]["canonical_ir"]["rules"]]
                             if item["status"] == "decoded" else None)
                decisions[arm] = {"status": item["status"], "predicted_modalities": predicted,
                    "permission_retained": predicted == ["P"], "full_ir_exact": item["exact"]}
            permission[mode].append({"id": key, "expected_modalities": ["P"], "arms": decisions})
    valid = all(report["valid_evaluation"] for values in reports.values() for report in values.values())
    return {"schema": F18_MATCHED_SCHEMA, "valid_evaluation": valid,
            "expected_source_count": 632, "weak_label_target_count": 624, "unscored_ids": list(unscored_ids),
            "retention_ids": list(retention_ids), "permission_ids": list(permission_ids),
            "expected_ids": {name: list(values) for name, values in expected_ids.items()},
            "expected_source_sha256": {key: expected_source_sha256[key] for key in all_ids},
            "panels": panel_reports, "arms": reports, "retention": retention, "permission_decisions": permission,
            "permission_counts": {mode: {arm: _fraction(sum(row["arms"][arm]["permission_retained"] for row in permission[mode]), 32)
                                           for arm in _F18_ARMS} for mode in ("raw", "joint")},
            "roster_membership_verified": False, "source_commitment_origin_verified": False,
            "target_origin_verified": False, "freeze_timing_verified": False,
            "parent_relative_only": True, "retained_other_comparator_no_loss_gate_evaluated": False,
            "teacher_forcing": False, "metric_target_access": True, "training_executed": False, **_FALSE}


__all__ += ["compare_f18_frozen_matched_arms", "F18_MATCHED_SCHEMA"]
