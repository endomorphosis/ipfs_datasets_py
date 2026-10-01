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
