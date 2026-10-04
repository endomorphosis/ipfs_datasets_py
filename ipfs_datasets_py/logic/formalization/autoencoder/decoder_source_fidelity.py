"""Bounded scoring of generated Legal JSON against complete authored references.

This owner decodes only supplied generated content tokens. Source text is optional
provenance, never a decoding fallback. Reference agreement, syntax, and declared
ablations confer no source-semantic, native, teacher, or proof authority.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import re

SCHEMA = "decoder-source-fidelity/v1"
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
FALSE = {name: False for name in ("qualified", "admitted", "proof_authority",
    "source_semantics_verified", "lake_executed", "native_validation_executed",
    "model_executed", "control_execution_verified", "fresh_holdout", "convergence_proven")}
_COUNTS = ("rows", "expected_rules", "generated_rules", "valid_generated_rules", "syntax_valid",
    "parsed_documents", "eos_count", "ordered_exact", "all_rules_preserved", "whole_rules_missing",
    "whole_rules_extra", "duplicate_rules", "order_mismatch_rows", "invalid_rule_count",
    "invalid_rows", "unscorable_generation_rows", "prediction_missing_rows")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _name(value):
    return type(value) is str and 0 < len(value) <= 512 and value.isprintable()


def _strict_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate generated JSON key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("nonfinite generated JSON constant")
    return json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)


def _rule(rule, validate_rule):
    _require(type(rule) is dict and set(rule) == set(FACETS), "exact seven-facet rule required")
    _require(all(type(rule[field]) is str for field in FACETS[:4]), "scalar facet must be a string")
    _require(all(type(rule[field]) is list and len(rule[field]) <= 128
        and all(type(value) is str for value in rule[field]) for field in FACETS[4:]),
        "qualifier facet must contain bounded string atoms")
    before = _raw(rule)
    # A supplied validator cannot normalize or mutate the model's candidate.
    wrapper = {"rules": [deepcopy(rule)]}
    receipt = validate_rule(wrapper)
    _require(_raw(wrapper) == _raw({"rules": [rule]}), "rule validator mutated candidate")
    _require(type(receipt) is dict and receipt.get("valid") is True,
        "single-rule validator rejected generated rule")
    _require(_raw(rule) == before, "rule validation changed candidate")


def _control(value, ids):
    if value is None:
        value = dict(kind="conditioned", source_assignment={identity: identity for identity in ids})
    _require(type(value) is dict and set(value) == {"kind", "source_assignment"}, "closed control descriptor required")
    _require(value["kind"] in ("conditioned", "zero_condition", "source_shuffle", "cross_length_shuffle",
        "context_only_shuffle", "context_reverse", "context_rotate"), "unknown control kind")
    assignment = value["source_assignment"]
    _require(type(assignment) is dict and set(assignment) == set(ids)
        and all(type(item) is str for item in assignment.values())
        and set(assignment.values()) == set(ids), "control must preserve all source identities")
    if value["kind"] in ("source_shuffle", "cross_length_shuffle", "context_only_shuffle"):
        _require(len(ids) > 1 and all(key != item for key, item in assignment.items()),
            "source-shuffle control must be a complete derangement")
    else:
        _require(all(key == item for key, item in assignment.items()), "unshuffled control must retain source identity")
    return deepcopy(value)


def _prediction(prediction, vocabulary, output_limit):
    """Return raw parse evidence; no target or source is available here."""
    if prediction is None:
        return dict(present=False, eos=False, parsed=None, rules=None,
            errors=["prediction_missing"], token_ids=None, status="missing")
    result = dict(present=True, eos=False, parsed=None, rules=None, errors=[],
        token_ids=None, status=prediction.get("generation_status")
            if type(prediction.get("generation_status")) is str else None)
    try:
        tokens = prediction.get("token_ids")
        _require(type(tokens) is list and len(tokens) <= output_limit-1
            and all(type(token) is int and 3 <= token < len(vocabulary) for token in tokens),
            "generated token outside content vocabulary or output budget")
        result["token_ids"] = deepcopy(tokens)
        _require(type(prediction.get("eos_reached")) is bool, "explicit Boolean EOS receipt required")
        status = prediction.get("generation_status")
        if status is not None:
            _require(status in ("eos", "output_limit", "invalid_special_token"), "unknown generation status")
            _require((status == "eos") == prediction["eos_reached"], "generation status contradicts EOS receipt")
        if prediction["eos_reached"]:
            _require(len(tokens)+2 <= output_limit, "EOS exceeds complete output budget")
        result["eos"] = prediction["eos_reached"]
        text = "".join(vocabulary[token] for token in tokens)
        _require(len(text.encode("utf-8")) <= 1048576, "generated JSON byte limit exceeded")
        parsed = _strict_json(text)
        _raw(parsed)  # Reject overflowed float literals and lone Unicode surrogates.
        result["parsed"] = parsed
        _require(type(parsed) is dict and set(parsed) == {"rules"}
            and type(parsed["rules"]) is list and len(parsed["rules"]) <= 32,
            "bounded composite rule document required")
        result["rules"] = parsed["rules"]
        if not parsed["rules"]:
            result["errors"].append("generated rule list is empty")
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError, UnicodeError) as error:
        result["errors"].append(str(error)[:512])
    return result


def _row(reference, prediction, vocabulary, validate_rule, output_limit):
    evidence = _prediction(prediction, vocabulary, output_limit)
    gold = reference["target"]["rules"]
    generated = evidence["rules"]
    valid = {}
    if generated is not None:
        for position, rule in enumerate(generated):
            try:
                _rule(rule, validate_rule)
                valid[position] = rule
            except (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError, UnicodeError) as error:
                evidence["errors"].append("rule["+str(position)+"]: "+str(error)[:512])
    expected = Counter(_raw(rule) for rule in gold)
    actual = Counter(_raw(rule) for rule in valid.values())
    matched = sum((expected & actual).values())
    generated_count = 0 if generated is None else len(generated)
    syntax_valid = generated is not None and bool(generated) and len(valid) == len(generated) and not evidence["errors"]
    all_preserved = syntax_valid and evidence["eos"] and matched == len(gold) == generated_count
    ordered = bool(syntax_valid and evidence["eos"] and _raw(evidence["parsed"]) == _raw(reference["target"]))
    facets = {}
    for field in FACETS:
        correct = sum(position in valid and _raw(valid[position][field]) == _raw(rule[field])
            for position, rule in enumerate(gold))
        gold_values = Counter(_raw(rule[field]) for rule in gold)
        generated_values = Counter(_raw(rule[field]) for rule in valid.values())
        facets[field] = dict(correct=correct, total=len(gold),
            unordered_correct=sum((gold_values & generated_values).values()))
    counts = dict(rows=1, expected_rules=len(gold), generated_rules=generated_count,
        valid_generated_rules=len(valid), syntax_valid=int(syntax_valid),
        parsed_documents=int(generated is not None), eos_count=int(evidence["eos"]),
        ordered_exact=int(ordered), all_rules_preserved=int(all_preserved),
        whole_rules_missing=len(gold)-matched, whole_rules_extra=generated_count-matched,
        duplicate_rules=sum(max(0, count-1) for count in actual.values()),
        order_mismatch_rows=int(all_preserved and not ordered),
        invalid_rule_count=generated_count-len(valid), invalid_rows=int(not syntax_valid),
        unscorable_generation_rows=int(generated is None), prediction_missing_rows=int(not evidence["present"]))
    return dict(id=reference["id"], clause_count=reference["clause_count"],
        source_provenance=deepcopy(reference.get("source_provenance")),
        target_sha256=digest(reference["target"]), expected_ir=deepcopy(reference["target"]),
        generated_ir=deepcopy(evidence["parsed"]), generated_token_ids=evidence["token_ids"],
        generation_status=evidence["status"], errors=evidence["errors"], counts=counts,
        by_facet=facets, **FALSE)


def _aggregate(records):
    result = {key: sum(row["counts"][key] for row in records) for key in _COUNTS}
    facets = {field: {key: sum(row["by_facet"][field][key] for row in records)
        for key in ("correct", "total", "unordered_correct")} for field in FACETS}
    return result, facets


def score_predictions(rows, predictions, *, codec, validate_rule, output_limit=1024,
                      validator_id="declared-single-rule-validator/v1", control=None):
    """Score supplied generated tokens, with fixed per-reference denominators.

    ``token_ids`` excludes BOS/EOS; ``output_limit`` includes both. Optional
    source text is hashed as provenance only. ``validate_rule`` receives an
    isolated ``{'rules': [rule]}`` and returns ``{'valid': True}`` on acceptance.
    Its identity is caller-declared. Missing prediction rows remain failures;
    duplicate/unknown prediction identities are rejected rather than collapsed.
    """
    _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded nonempty reference rows required")
    _require(type(predictions) is list and len(predictions) <= len(rows), "bounded prediction rows required")
    _require(callable(validate_rule) and _name(validator_id), "explicit rule validator required")
    _require(type(output_limit) is int and 4 <= output_limit <= 1024, "bounded decoder output limit required")
    _require(type(codec) is dict and type(codec.get("target_vocabulary")) is list, "explicit target codec required")
    vocabulary = codec["target_vocabulary"]
    _require(4 <= len(vocabulary) <= 4096 and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"]
        and all(type(token) is str and 0 < len(token) <= 16384 for token in vocabulary)
        and len(set(vocabulary)) == len(vocabulary) and len(_raw(codec)) <= 4194304,
        "bounded unique content vocabulary with reserved IDs required")
    reference_rows, seen = [], set()
    for row in rows:
        _require(type(row) is dict and _name(row.get("id")) and row["id"] not in seen,
            "unique reference identity required")
        seen.add(row["id"])
        target = row.get("target")
        _require(type(target) is dict and set(target) == {"rules"} and type(target["rules"]) is list
            and 1 <= len(target["rules"]) <= 32 and type(row.get("clause_count")) is int
            and row["clause_count"] == len(target["rules"]), "complete target and exact clause count required")
        _require(len(_raw(target)) <= 1048576, "reference target exceeds byte limit")
        for rule in target["rules"]:
            _rule(rule, validate_rule)
        provenance = None
        if "source_text" in row:
            _require(type(row["source_text"]) is str and len(row["source_text"].encode()) <= 1048576,
                "bounded source provenance required")
            source_sha = hashlib.sha256(row["source_text"].encode()).hexdigest()
            _require(row.get("source_sha256", source_sha) == source_sha, "source provenance digest differs")
            provenance = dict(source_sha256=source_sha, source_text=row["source_text"],
                use="evaluation_provenance_only")
        elif "source_sha256" in row:
            _require(type(row["source_sha256"]) is str
                and re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]), "declared source digest is invalid")
            provenance = dict(source_sha256=row["source_sha256"], source_text=None,
                use="caller_declared_evaluation_provenance_only")
        reference_rows.append(dict(id=row["id"], target=deepcopy(target), clause_count=row["clause_count"],
            source_provenance=provenance))
    indexed = {}
    for prediction in predictions:
        _require(type(prediction) is dict and _name(prediction.get("id")) and prediction["id"] in seen
            and prediction["id"] not in indexed, "unknown or duplicate prediction identity")
        indexed[prediction["id"]] = prediction
    control = _control(control, [row["id"] for row in reference_rows])
    records = [_row(row, indexed.get(row["id"]), vocabulary, validate_rule, output_limit) for row in reference_rows]
    metrics, facets = _aggregate(records)
    lengths = {}
    for length in sorted({row["clause_count"] for row in records}):
        counts, fields = _aggregate([row for row in records if row["clause_count"] == length])
        lengths[str(length)] = dict(metrics=counts, by_facet=fields)
    report = dict(schema=SCHEMA, evaluation_sha256=digest(reference_rows), codec_sha256=digest(codec),
        validator_id=validator_id, validator_identity_authenticated=False, output_limit=output_limit,
        control=control, complete_evaluation=len(indexed) == len(rows), metrics=metrics,
        by_length=lengths, by_facet=facets, rows=records,
        facet_alignment="original_rule_position_no_target_based_realignment",
        facet_scope="valid_generated_rule_content; complete ordered exactness additionally requires EOS",
        unknown_extra_count_policy="unparseable documents counted separately; no guessed rule count",
        generation_target_access_verified=False, source_text_used_for_decoding=False, **FALSE)
    report["report_sha256"] = digest(report)
    return report


def _checked_report(report):
    _require(type(report) is dict and report.get("schema") == SCHEMA, "exact fidelity report required")
    _require(report.get("report_sha256") == digest({key: value for key, value in report.items()
        if key != "report_sha256"}), "fidelity report was modified")
    return report


def compare_nonregression(candidate, baseline, incumbent=None):
    """Require each length/facet to retain its score; external loss ranks survivors.

    This comparison neither authenticates reports nor selects weights. It returns
    whether scores satisfy a declared constraint and whether any score improved.
    """
    candidate, baseline = _checked_report(candidate), _checked_report(baseline)
    references = [("baseline", baseline)]
    if incumbent is not None:
        references.append(("incumbent", _checked_report(incumbent)))
    reasons, progress = [], False
    if candidate["complete_evaluation"] is not True:
        reasons.append("candidate evaluation incomplete")
    maximize = ("ordered_exact", "all_rules_preserved", "eos_count", "syntax_valid")
    minimize = ("whole_rules_missing", "whole_rules_extra", "invalid_rule_count", "invalid_rows",
        "unscorable_generation_rows", "prediction_missing_rows")
    identity = ("evaluation_sha256", "codec_sha256", "validator_id", "output_limit", "control")
    for label, reference in references:
        _require(all(candidate[key] == reference[key] for key in identity), "comparison evaluation identity differs")
        _require(set(candidate["by_length"]) == set(reference["by_length"]), "comparison clause lengths differ")
        for length, bucket in candidate["by_length"].items():
            previous = reference["by_length"][length]
            _require(all(bucket["metrics"][key] == previous["metrics"][key] for key in ("rows", "expected_rules")),
                "comparison reference denominators differ")
            for key in maximize+minimize:
                current, old = bucket["metrics"][key], previous["metrics"][key]
                worse = current < old if key in maximize else current > old
                if worse:
                    reasons.append(label+"/length="+length+"/"+key+" regressed")
                progress |= current > old if key in maximize else current < old
            for field in FACETS:
                current, old = bucket["by_facet"][field], previous["by_facet"][field]
                _require(current["total"] == old["total"], "comparison facet denominator differs")
                if current["correct"] < old["correct"]:
                    reasons.append(label+"/length="+length+"/"+field+" regressed")
                progress |= current["correct"] > old["correct"]
    return dict(accepted=not reasons, strict_progress=bool(progress and not reasons), reasons=reasons,
        compared_to=[name for name, _ in references], weight_selection_performed=False, **FALSE)
