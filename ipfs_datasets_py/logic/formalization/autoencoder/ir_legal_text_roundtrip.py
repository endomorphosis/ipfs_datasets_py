"""Detached, bounded scoring of retained Legal384 source-to-rule predictions.

This module never loads a model or produces embeddings. Rendering is opt-in;
the default canonical renderer receives only detached predicted IR and a row
request ID. Original wording, gold IR and caches remain on the scoring side.
Per-file endpoint fences are cooperative observations, not an atomic snapshot
or ancestor-containment guarantee. Authentic bytes do not qualify a teacher.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

SCHEMA = "legal-original-text-roundtrip-score/v1"
_SOURCE_SCHEMA = "shared-source-384-autoencoder/v2"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
_FALSE = ("qualified", "admitted", "proof_authority", "source_semantics_verified", "publication_performed")
_CACHE_FIELDS = {"id", "source_text", "source_sha256", "embedding", "embedding_sha256",
    "embedding_token_ids_sha256", "group_id", "split", "target", "wording_style",
    "reference_metadata", "proof_authority", "source_semantics_verified"}
_PRED_FIELDS = {"id", "source_sha256", "status", "reason", "candidate_ir", "generated_tokens", "ended",
    "reconstructed_embedding", "weight_ablation", "weights_sha256", "target_access", "teacher_forcing",
    "continue_planning", *_FALSE}
_MAX_JSON = 16 * 1024 * 1024


class LegalTextRoundTripError(ValueError):
    """Invalid declared input or corpus authenticity contract."""


def _require(condition, message):
    if not condition:
        raise LegalTextRoundTripError(message)


def _plain(value, depth=0, budget=None):
    if budget is None:
        budget = [1_000_000]
    budget[0] -= 1
    _require(budget[0] >= 0, "JSON node count exceeds bound")
    _require(depth <= 64, "JSON nesting exceeds bound")
    if type(value) is dict:
        _require(len(value) <= 4096 and all(type(key) is str and len(key) <= 65536 for key in value),
                 "bounded string JSON keys required")
        for item in value.values():
            _plain(item, depth + 1, budget)
    elif type(value) is list:
        _require(len(value) <= 4096, "JSON list count exceeds bound")
        for item in value:
            _plain(item, depth + 1, budget)
    else:
        _require(value is None or type(value) in (str, int, bool, float), "plain JSON values required")
        _require(type(value) is not float or math.isfinite(value), "finite JSON numbers required")
        _require(type(value) is not str or len(value) <= 65536, "JSON string exceeds bound")
        _require(type(value) is not int or value.bit_length() <= 1024, "JSON integer exceeds bound")


def _raw(value):
    _plain(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                         allow_nan=False).encode("utf-8")
    except (ValueError, OverflowError, UnicodeError, RecursionError) as error:
        raise LegalTextRoundTripError("bounded finite JSON required") from error
    _require(len(raw) <= _MAX_JSON, "JSON exceeds bound")
    return raw


def _copy(value):
    return json.loads(_raw(value))


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _text(value, maximum=16384):
    return type(value) is str and 0 < len(value) <= maximum


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def invalid(_):
        raise LegalTextRoundTripError("nonfinite JSON number")

    def number(value):
        result = float(value)
        _require(math.isfinite(result), "JSON float overflows")
        return result

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid, parse_float=number)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise LegalTextRoundTripError("invalid strict corpus JSON") from error


def _read_pin(pin, maximum):
    _require(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
        and type(pin["path"]) is str and Path(pin["path"]).is_absolute()
        and type(pin["bytes"]) is int and 0 < pin["bytes"] <= maximum and _sha(pin["sha256"]),
        "closed bounded corpus pin required")
    path = Path(pin["path"])
    try:
        before = path.lstat()
        _require(stat.S_ISREG(before.st_mode), "regular corpus file required")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _require(_identity(before) == _identity(opened) and opened.st_size == pin["bytes"],
                     "corpus endpoint changed before read")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        _require(_identity(before) == _identity(after) == _identity(path.lstat())
            and len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
            "corpus bytes or endpoint differ")
        return raw
    except OSError as error:
        raise LegalTextRoundTripError("corpus file unavailable or unsafe") from error


def _vector(value):
    try:
        return (type(value) is list and len(value) == 384
            and all(type(item) in (int, float) and math.isfinite(item) for item in value))
    except OverflowError:
        return False


def _rule_ir(value):
    if type(value) is not dict or set(value) != {"rules"} or type(value["rules"]) is not list or len(value["rules"]) != 1:
        return False
    rule = value["rules"][0]
    return (type(rule) is dict and set(rule) == set(_FACETS) and rule["modality"] in ("O", "P", "F")
        and all(_text(rule[key], 4096) for key in ("actor", "action", "object"))
        and all(type(rule[key]) is list and len(rule[key]) <= 64
            and all(_text(atom, 4096) for atom in rule[key]) for key in ("conditions", "exceptions", "temporal")))


def _corpus(pin, maximum):
    value = _parse(_read_pin(pin, maximum))
    _require(type(value) is dict and set(value) == {"rows", "source_embeddings"}
        and type(value["source_embeddings"]) is dict and type(value["rows"]) is list
        and 1 <= len(value["rows"]) <= 4096, "original source-v2 corpus envelope required")
    _raw(value["source_embeddings"])
    indexed = {}
    for row in value["rows"]:
        _require(type(row) is dict and set(row) == _CACHE_FIELDS and _text(row["id"], 512)
            and row["id"] not in indexed and _text(row["source_text"])
            and _text(row["group_id"], 512) and row["split"] in ("train", "validation", "test", "canary")
            and type(row["wording_style"]) is int and 0 <= row["wording_style"] <= 64
            and type(row["reference_metadata"]) is dict and row["proof_authority"] is False
            and row["source_semantics_verified"] is False and _vector(row["embedding"])
            and _sha(row["source_sha256"]) and _sha(row["embedding_sha256"])
            and _sha(row["embedding_token_ids_sha256"]) and _rule_ir(row["target"]),
            "closed original source-v2 row required")
        try:
            source_hash = hashlib.sha256(row["source_text"].encode("utf-8")).hexdigest()
        except UnicodeError as error:
            raise LegalTextRoundTripError("source must encode as UTF-8") from error
        _require(source_hash == row["source_sha256"] and _digest(row["embedding"]) == row["embedding_sha256"],
                 "retained source or vector hash differs")
        indexed[row["id"]] = row
    return value, indexed


def _render_predicted_ir(predicted_ir, request_id):
    """Explicit optional owner boundary: no source, gold, vector or lookup key."""
    from ...legal_ir.canonical_contracts import CanonicalRoundTripIR, DecompilerRequest, OperationStatus
    from ...legal_ir.canonical_decompiler import SourceWithheldCanonicalDecompiler
    result = SourceWithheldCanonicalDecompiler().decompile(
        DecompilerRequest(canonical_ir=CanonicalRoundTripIR.from_dict(predicted_ir), request_id=request_id))
    if result.status != OperationStatus.SUCCESS:
        return {"status": "refused", "text": None, "reason": "canonical_decompiler_refused"}
    return {"status": "rendered", "text": result.text, "reason": None}


def _distance(left, right, budget):
    """Exact Levenshtein distance, or an explicit unscored bounded outcome."""
    cells = len(left) * len(right)
    if cells > budget[0]:
        return {"status": "cell_budget_exhausted", "distance": None, "cells": cells}
    budget[0] -= cells
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for index, a in enumerate(left, 1):
        current = [index]
        for column, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[column] + 1, previous[column - 1] + (a != b)))
        previous = current
    return {"status": "scored", "distance": previous[-1], "cells": cells}


def _collisions(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[_digest(row["target"])].append(row)
    upper_matches = 0
    records = []
    for target_hash, members in sorted(groups.items()):
        wordings = Counter(row["source_sha256"] for row in members)
        upper_matches += max(wordings.values())
        records.append({"target_sha256": target_hash, "row_ids": [row["id"] for row in members],
            "row_count": len(members), "distinct_original_wordings": len(wordings),
            "largest_identical_wording_count": max(wordings.values())})
    return {"semantic_group_count": len(groups), "source_row_count": len(rows), "groups": records,
        "semantic_ir_only_single_output_exact_source_ceiling_count": upper_matches,
        "semantic_ir_only_single_output_exact_source_ceiling_rate": upper_matches / len(rows),
        "scope": "this selected empirical corpus; identical gold semantic IR, one output per IR, no residual/style/source side channel",
        "is_global_model_limit": False, "applies_to_learned_surface_or_residual_input": False}



def _recompile_selected_prose(rendering, predicted_ir, reference_ir, recompiler):
    """Score one text-only callback result; never give it an IR or source.

    This measures a caller-owned canonical-syntax cycle. It does not authenticate
    the callback's closure, model, parser execution, or legal interpretation.
    """
    result = {"status": "unavailable", "reason": "selected_prose_unavailable",
        "callback_invoked": False, "input_text_sha256": None,
        "output_ir": None, "output_ir_sha256": None,
        "exact_predicted_ir": False, "exact_reference_ir": False,
        "facets_predicted": {key: False for key in _FACETS},
        "facets_reference": {key: False for key in _FACETS}}
    if rendering["status"] != "rendered":
        return result
    text = rendering["text"]
    result["input_text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    result["callback_invoked"] = True
    try:
        # No source wording, reference, predicted IR, vector, row identifier,
        # cache lookup key, decoder prefix or proof signal crosses this boundary.
        output = recompiler(text, "legal-selected-prose-recompile")
    except Exception as error:
        result.update(status="error", reason=type(error).__name__)
        return result
    try:
        output = _copy(output)
        _require(type(output) is dict and set(output) == {"status", "candidate_ir", "reason"}
            and output["status"] in ("recompiled", "unsupported", "abstained"),
            "closed prose-recompiler result required")
        if output["status"] in ("unsupported", "abstained"):
            _require(output["candidate_ir"] is None and _text(output["reason"], 512),
                "unsupported or abstained recompile must contain no IR")
            result.update(status=output["status"], reason=output["reason"])
            return result
        _require(output["reason"] is None and _rule_ir(output["candidate_ir"]),
            "complete single-rule canonical IR required; unsupported fields cannot be discarded")
        candidate = output["candidate_ir"]
        result.update(status="recompiled", reason=None, output_ir=candidate,
            output_ir_sha256=_digest(candidate),
            exact_predicted_ir=_raw(candidate) == _raw(predicted_ir),
            exact_reference_ir=_raw(candidate) == _raw(reference_ir),
            facets_predicted={key: candidate["rules"][0][key] == predicted_ir["rules"][0][key]
                for key in _FACETS},
            facets_reference={key: candidate["rules"][0][key] == reference_ir["rules"][0][key]
                for key in _FACETS})
    except Exception as error:
        result.update(status="invalid", reason=type(error).__name__)
    return result


def score_legal_original_text_roundtrip(corpus_pin, captured_inputs, candidate_report, *,
        render_canonical=False, renderer=None, max_edit_cells=2_000_000, max_reference_bytes=_MAX_JSON,
        recompile_rendered=False, recompiler=None):
    """Score an explicit cached cohort; never invoke its numerical decoder.

    Captured rows must be exactly ``{id, source_text, embedding}``. Gold remains
    detached from rendering, which receives ``(predicted_ir, request_id)`` only.
    A supplied renderer is a caller-owned boundary, not authenticated model or
    source-free behavior. The built-in opt-in renderer is deterministic and has
    no learned prose head. Missing/duplicate/invalid outputs receive zero credit
    in all selected-row accuracy denominators, with coverage recorded separately.
    Optional prose recompilation passes only the selected rendered text and a
    constant non-source request ID to the supplied callback. Its outputs receive
    exact seven-facet CanonicalRoundTripIR@1 comparisons, not complete TypedAST,
    semantic-equivalence, legal-faithfulness or proof credit. Callback behavior,
    including hidden closure state, remains unauthenticated. Defaults are unchanged.
    """
    _require(type(render_canonical) is bool and (renderer is None or render_canonical and callable(renderer)),
             "renderer requires explicit canonical-rendering selection")
    _require(type(recompile_rendered) is bool
        and (recompiler is None or recompile_rendered and callable(recompiler))
        and (not recompile_rendered or render_canonical and callable(recompiler)),
        "prose recompilation requires explicit rendering selection and a text-only callback")
    _require(type(max_edit_cells) is int and 1 <= max_edit_cells <= 4_000_000
        and type(max_reference_bytes) is int and 1 <= max_reference_bytes <= _MAX_JSON, "finite scoring budgets required")
    pin, inputs, report = _copy(corpus_pin), _copy(captured_inputs), _copy(candidate_report)
    corpus, by_id = _corpus(pin, max_reference_bytes)
    _require(type(inputs) is list and 1 <= len(inputs) <= 64, "one to 64 captured inputs required")
    seen, gold = set(), []
    for row in inputs:
        _require(type(row) is dict and set(row) == {"id", "source_text", "embedding"}
            and _text(row["id"], 512) and row["id"] not in seen and row["id"] in by_id
            and _vector(row["embedding"]), "closed unique captured source-v2 inputs required")
        expected = by_id[row["id"]]
        _require(row["source_text"] == expected["source_text"] and _digest(row["embedding"]) == expected["embedding_sha256"],
                 "captured source or vector differs from retained corpus")
        seen.add(row["id"])
        gold.append(expected)
    top_fields = {"schema", "domain_id", "dimension", "rows", *_FALSE}
    envelope_ok = (type(report) is dict and set(report) == top_fields
        and report.get("schema") == _SOURCE_SCHEMA and report.get("domain_id") == "legal_ir"
        and type(report.get("dimension")) is int and report["dimension"] == 384
        and all(report.get(key) is False for key in _FALSE) and type(report.get("rows")) is list
        and len(report["rows"]) <= 128)
    predictions = report.get("rows", []) if type(report) is dict and type(report.get("rows")) is list else []
    _require(len(predictions) <= 128, "prediction count exceeds bound")
    indexed, invalid_ids = defaultdict(list), []
    for index, row in enumerate(predictions):
        if type(row) is not dict or not _text(row.get("id"), 512):
            invalid_ids.append(index)
        else:
            indexed[row["id"]].append(row)
    missing, unexpected = sorted(seen - set(indexed)), sorted(set(indexed) - seen)
    duplicate = {key: len(values) for key, values in sorted(indexed.items()) if len(values) > 1}
    coverage_ok = not (missing or unexpected or duplicate or invalid_ids)
    results, budget = [], [max_edit_cells]
    render = renderer or _render_predicted_ir
    for expected in gold:
        row_id, matches = expected["id"], indexed.get(expected["id"], [])
        result = {"id": row_id, "source_sha256": expected["source_sha256"], "embedding_sha256": expected["embedding_sha256"],
            "group_id": expected["group_id"], "split": expected["split"], "wording_style": expected["wording_style"],
            "target_sha256": _digest(expected["target"]), "outcome": "refused", "reason": None,
            "exact_ir": False, "facets": {key: False for key in _FACETS}, "candidate_ir_sha256": None,
            "rendering": {"status": "not_requested" if not render_canonical else "unavailable", "text": None,
                "reason": None, "exact_original_utf8": None if not render_canonical else False,
                "whitespace_collapsed_exact": None if not render_canonical else False,
                "character_edit": None, "whitespace_token_edit": None}}
        if len(matches) != 1:
            result.update(outcome="duplicate" if matches else "missing", reason="ambiguous_or_missing_prediction_id")
        elif not envelope_ok:
            result["reason"] = "invalid_source_v2_report_envelope"
        else:
            actual = matches[0]
            if (set(actual) != _PRED_FIELDS or actual.get("source_sha256") != expected["source_sha256"]
                or actual.get("target_access") is not False or actual.get("teacher_forcing") is not False
                or actual.get("continue_planning") is not True or any(actual.get(key) is not False for key in _FALSE)
                or not _sha(actual.get("weights_sha256")) or not _vector(actual.get("reconstructed_embedding"))
                or actual.get("weight_ablation") not in (None, "zero_projection", "zero_condition", "zero_decoder")
                or type(actual.get("ended")) is not bool or type(actual.get("generated_tokens")) is not list
                or len(actual["generated_tokens"]) > 1024 or not all(_text(token, 16384) for token in actual["generated_tokens"])
                or actual.get("reason") is not None and not _text(actual.get("reason"), 512)):
                result["reason"] = "invalid_prediction_schema_or_source_provenance"
            elif actual.get("status") == "fail_open_invalid_output" and actual.get("candidate_ir") is None:
                result.update(outcome="refused", reason="invalid_generation_no_ir")
            elif actual.get("status") != "unqualified_candidate" or not actual["ended"] or not _rule_ir(actual.get("candidate_ir")):
                result["reason"] = "invalid_or_incomplete_single_rule_candidate"
            else:
                predicted = _copy(actual["candidate_ir"])
                result.update(outcome="decoded", exact_ir=_raw(predicted) == _raw(expected["target"]),
                    candidate_ir_sha256=_digest(predicted), facets={key: predicted["rules"][0][key] == expected["target"]["rules"][0][key]
                                                               for key in _FACETS})
                if render_canonical:
                    try:
                        rendered = _copy(render(_copy(predicted), "legal-original-text-roundtrip"))
                        _require(type(rendered) is dict and set(rendered) == {"status", "text", "reason"}
                            and rendered["status"] in ("rendered", "refused"), "closed renderer result required")
                        if rendered["status"] == "refused":
                            _require(rendered["text"] is None and _text(rendered["reason"], 512), "refusal must contain no text")
                            result["rendering"].update(status="refused", reason=rendered["reason"])
                        else:
                            text = rendered["text"]
                            _require(_text(text) and rendered["reason"] is None, "bounded rendered text required")
                            target = expected["source_text"]
                            result["rendering"].update(status="rendered", text=text,
                                exact_original_utf8=text.encode("utf-8") == target.encode("utf-8"),
                                whitespace_collapsed_exact=" ".join(text.split()) == " ".join(target.split()),
                                character_edit=_distance(text, target, budget),
                                whitespace_token_edit=_distance(text.split(), target.split(), budget))
                    except Exception as error:
                        result["rendering"].update(status="refused", reason=type(error).__name__)
        result["joint_ir_original_utf8_exact"] = (
            result["exact_ir"] and result["rendering"]["exact_original_utf8"] is True
        ) if render_canonical else None
        results.append(result)
    if recompile_rendered:
        for result, expected in zip(results, gold):
            predicted = (indexed[result["id"]][0]["candidate_ir"]
                if result["outcome"] == "decoded" else None)
            result["recompilation"] = _recompile_selected_prose(
                result["rendering"], predicted, expected["target"], recompiler)
    # Reread the complete corpus after optional caller-owned rendering. This
    # observes endpoint stability; no atomic multi-file/current-model claim.
    _read_pin(pin, max_reference_bytes)
    total = len(gold)
    counts = {key: sum(row["outcome"] == key for row in results) for key in ("decoded", "abstained", "refused", "missing", "duplicate")}
    counts.update(attempted=total, exact_ir=sum(row["exact_ir"] for row in results),
        rendered=sum(row["rendering"]["status"] == "rendered" for row in results) if render_canonical else None,
        rendering_refused=sum(row["rendering"]["status"] == "refused" for row in results) if render_canonical else None,
        exact_original_utf8=sum(row["rendering"]["exact_original_utf8"] is True for row in results) if render_canonical else None,
        whitespace_collapsed_exact=sum(row["rendering"]["whitespace_collapsed_exact"] is True for row in results) if render_canonical else None,
        joint_ir_original_utf8_exact=sum(row["joint_ir_original_utf8_exact"] is True for row in results) if render_canonical else None)
    ir_text_joint_counts = None
    if render_canonical:
        ir_text_joint_counts = {"denominator": "all_captured_input_rows", "total": total,
            "both_exact": counts["joint_ir_original_utf8_exact"],
            "ir_only_exact": sum(row["exact_ir"] and row["rendering"]["exact_original_utf8"] is not True for row in results),
            "text_only_exact": sum(not row["exact_ir"] and row["rendering"]["exact_original_utf8"] is True for row in results),
            "neither_exact": sum(not row["exact_ir"] and row["rendering"]["exact_original_utf8"] is not True for row in results)}
    provenance_ok = not any(row["reason"] == "invalid_prediction_schema_or_source_provenance" for row in results)
    edits = {}
    for name in ("character_edit", "whitespace_token_edit"):
        scored = [row["rendering"][name]["distance"] for row in results
            if row["rendering"][name] is not None and row["rendering"][name]["status"] == "scored"]
        edits[name] = {"scored_rows": len(scored), "attempted_rows": total,
            "mean_distance_on_scored_rows": sum(scored) / len(scored) if scored else None,
            "scored_coverage_fraction": len(scored) / total,
            "mean_excludes_unrendered_and_budget_exhausted_rows": True}
    scored = {"schema": SCHEMA, "corpus_pin": pin, "source_embeddings_metadata_sha256": _digest(corpus["source_embeddings"]),
        "captured_inputs_sha256": _digest(inputs), "candidate_report_sha256": _digest(report),
        "coverage": {"valid": coverage_ok, "expected_count": total, "prediction_count": len(predictions),
            "missing_ids": missing, "unexpected_ids": unexpected, "duplicate_ids": duplicate, "invalid_id_row_indices": invalid_ids},
        "report_envelope_valid": envelope_ok, "prediction_provenance_valid": provenance_ok,
        "valid_evaluation": envelope_ok and coverage_ok and provenance_ok,
        "operational_complete": envelope_ok and coverage_ok and provenance_ok and counts["decoded"] == total
            and (not render_canonical or counts["rendered"] == total),
        "counts": counts, "rates": {"denominator": "all_captured_input_rows", "exact_ir": counts["exact_ir"] / total,
            "exact_original_utf8": counts["exact_original_utf8"] / total if render_canonical else None,
            "whitespace_collapsed_exact": counts["whitespace_collapsed_exact"] / total if render_canonical else None,
            "joint_ir_original_utf8_exact": counts["joint_ir_original_utf8_exact"] / total if render_canonical else None},
        "ir_text_joint_counts": ir_text_joint_counts,
        "facets": {key: {"matched": sum(row["facets"][key] for row in results), "total": total} for key in _FACETS},
        "edit_budget": {"maximum_cells": max_edit_cells, "used_cells": max_edit_cells - budget[0],
            "scope": "global character and whitespace-token Levenshtein cells; exhausted distances stay null"},
        "edit_metrics": edits,
        "surface_information": _collisions(gold), "rows": results,
        "rendering_task": "deterministic_canonical_text" if render_canonical else "not_requested",
        "renderer_boundary": "detached_predicted_ir_and_non_source_request_id_only" if render_canonical else None,
        "renderer_is_caller_supplied": renderer is not None, "renderer_behavior_authenticated": False,
        "renderer_uses_model": False if render_canonical and renderer is None else None,
        "native_grammar_verified": False, "producer_execution_authenticated": False,
        "embedding_generation_executed": False, "model_inference_executed_by_scorer": False,
        "decoder_execution_authenticated": False, "checkpoint_loaded_by_scorer": False,
        "training_executed": False, "teacher_forcing_used_for_generation": False,
        "independent_holdout_qualified": False, "teacher_qualified": False,
        "learned_original_prose_head_evaluated": False, "retained_source_restoration_evaluated": False,
        "semantic_correctness_qualified": False, "proof_authority": False}

    if recompile_rendered:
        recompilations = [row["recompilation"] for row in results]
        statuses = {name: sum(row["status"] == name for row in recompilations)
            for name in ("recompiled", "unsupported", "abstained", "unavailable", "error", "invalid")}
        cycle_exact = sum(row["exact_predicted_ir"] for row in recompilations)
        reference_exact = sum(row["exact_reference_ir"] for row in recompilations)
        scored["prose_recompilation"] = {
            "scope": "single_rule_CanonicalRoundTripIR@1_seven_facet_syntax_only",
            "prose_input": "selected_renderer_output_verbatim",
            "denominator": "all_captured_input_rows", "attempted_rows": total,
            "callback_calls": sum(row["callback_invoked"] for row in recompilations),
            "counts": {**statuses, "exact_predicted_ir": cycle_exact, "exact_reference_ir": reference_exact},
            "rates": {"exact_predicted_ir": cycle_exact / total,
                "exact_reference_ir": reference_exact / total},
            "facets_predicted": {key: {"matched": sum(row["facets_predicted"][key]
                for row in recompilations), "total": total} for key in _FACETS},
            "facets_reference": {key: {"matched": sum(row["facets_reference"][key]
                for row in recompilations), "total": total} for key in _FACETS},
            "callback_boundary": "selected_prose_and_constant_non_source_request_id_only",
            "callback_is_caller_supplied": True, "callback_behavior_authenticated": False,
            "hidden_source_or_target_copying_ruled_out": False,
            "native_compiler_or_model_execution_authenticated": False,
            "complete_typed_AST_fidelity": None, "semantic_equivalence": None,
            "legal_source_faithfulness": None, "proof_validity": None,
            "unsupported_semantics": ["quantifier_and_binder_scope", "observed_compliance",
                "nested_exception_scope", "calendar_interpretation", "legal_effective_dates",
                "typed_cardinality", "governing_definition_dependencies"],
            "semantic_correctness_qualified": False, "proof_authority": False}
        scored["operational_complete"] = scored["operational_complete"] and statuses["recompiled"] == total
    return scored


__all__ = ["SCHEMA", "LegalTextRoundTripError", "score_legal_original_text_roundtrip"]


def score_relational_legal_text_roundtrip(reference_expression, candidate_text, *,
        reference_argument_roles, profile, original_text=None,
        reference_governing_fields=None, candidate_governing_fields=None, capacity_profile=None):
    """Score one complete opt-in controlled-prose prediction against typed content.

    Original source is optional and remains exclusively on the scoring side.
    The compiler receives only candidate prose and its explicit profile; the
    reference and original source cannot influence its reconstruction. Unsupported
    candidates remain an abstention in the one-input denominator. No model, file,
    native backend or legal review operation is performed by this score path.
    Optional governing_context and definition_uses observations are compared
    independently and stay on the scoring side, even for unsupported prose.
    Mutable reference/role/governing inputs are detached and fenced; changes
    during scoring refuse the report rather than mix observation epochs.
    """
    from ipfs_datasets_py.logic.legal_ir.extended_decompiler import (
        decompile_relational, _prose_capacity_options, _prose_capacity_json)
    from ipfs_datasets_py.logic.legal_ir.extended_compiler import compile_relational
    from ipfs_datasets_py.logic.autoformal.legal_relational_reconstruction_v1 import (
        compare_relational_governing_fields_v1,
        compare_relational_prose_structure_v1,
    )

    capacity_options = _prose_capacity_options(profile, capacity_profile)
    input_wire = (_raw if not capacity_options else
        lambda value: _prose_capacity_json(value, **capacity_options))

    _require(type(candidate_text) is str, "candidate prose text required")
    _require(original_text is None or type(original_text) is str, "optional original source text required")
    try:
        candidate_bytes = candidate_text.encode("utf-8")
        original_bytes = None if original_text is None else original_text.encode("utf-8")
    except UnicodeError as error:
        raise LegalTextRoundTripError("valid UTF8 candidate and optional original text required") from error
    _require(len(candidate_bytes) <= _MAX_JSON and (original_bytes is None or len(original_bytes) <= _MAX_JSON),
             "bounded candidate and optional original source text required")
    # The reference and scoring-only observations are caller-owned mutable
    # objects. Detach them before invoking either realization or inverse code,
    # and refuse mutation instead of issuing a mixed-epoch equality report.
    from ipfs_datasets_py.logic.syntax_core import ast
    _require(type(reference_expression) is ast.TypedExpression, "canonical TypedExpression required")
    original_expression, original_roles = reference_expression, reference_argument_roles
    original_reference_governing = reference_governing_fields
    original_candidate_governing = candidate_governing_fields

    def original_inputs():
        return {"expression": original_expression.to_dict(), "roles": original_roles,
            "reference_governing": original_reference_governing,
            "candidate_governing": original_candidate_governing}

    frozen = input_wire(original_inputs())
    detached = json.loads(frozen)
    reference_expression = ast.TypedExpression.from_dict(detached["expression"])
    reference_argument_roles = detached["roles"]
    reference_governing_fields = detached["reference_governing"]
    candidate_governing_fields = detached["candidate_governing"]

    def input_fence():
        current = {"expression": reference_expression.to_dict(), "roles": reference_argument_roles,
            "reference_governing": reference_governing_fields,
            "candidate_governing": candidate_governing_fields}
        _require(input_wire(original_inputs()) == frozen and input_wire(current) == frozen,
                 "relational roundtrip inputs changed during scoring")

    governing_comparison = None
    if reference_governing_fields is not None or candidate_governing_fields is not None:
        governing_comparison = compare_relational_governing_fields_v1(
            reference_governing_fields, candidate_governing_fields)
    reference_prose = decompile_relational(reference_expression,
        argument_roles=reference_argument_roles, profile=profile, **capacity_options)
    input_fence()
    candidate = compile_relational(candidate_text, profile=profile, **capacity_options) if candidate_text.strip() else None
    comparison = dict.fromkeys(("exact_typed_expression_equal", "typed_structure_equal",
                                 "canonical_prose_equal", "argument_roles_equal"), False)
    normalized_candidate = None
    if candidate is not None:
        expression, roles = candidate
        comparison = compare_relational_prose_structure_v1(reference_expression, expression,
            reference_argument_roles=reference_argument_roles, candidate_argument_roles=roles, profile=profile, **capacity_options)
        normalized_candidate = decompile_relational(expression, argument_roles=roles, profile=profile, **capacity_options)
    byte_exact = None if original_bytes is None else candidate_bytes == original_bytes
    result = {
        "schema": "legal-relational-text-roundtrip-score/v1", "profile": profile,
        "status": "complete_candidate_scored" if candidate is not None else "unsupported_candidate_abstained",
        "input_count": 1, "supported_count": int(candidate is not None),
        "abstention_count": int(candidate is None),
        "measurements": {
            "original_utf8_exact": byte_exact,
            "canonical_prose_exact": comparison["canonical_prose_equal"],
            "complete_typed_structure_exact": comparison["typed_structure_equal"],
            "exact_typed_expression_equal": comparison["exact_typed_expression_equal"],
            "argument_roles_exact": comparison["argument_roles_equal"],
            "joint_typed_structure_original_utf8_exact": (None if byte_exact is None else
                comparison["typed_structure_equal"] and byte_exact),
            "semantic_equivalence_verified": False, "source_correspondence_verified": False,
            "proof_validity_verified": False, "source_dependence_evaluated": False,
        },
        "normalized_reference_prose": reference_prose,
        "normalized_candidate_prose": normalized_candidate,
        "original_source_available_to_inverse": False,
        "reference_target_available_to_inverse": False,
        "authority": {"source_semantics_verified": False, "admitted": False,
                      "proof_authority": False, "model_quality_established": False},
        "training_mask": 0, "evaluation_gold_mask": 0,
    }
    if governing_comparison is not None:
        result["governing_fields_comparison"] = governing_comparison
    if capacity_options:
        result["capacity_profile"] = capacity_profile
    input_fence()
    return result


__all__.append("score_relational_legal_text_roundtrip")



def score_deadline_legal_text_roundtrip(reference_ir, candidate_text, *,
        anchor_dates, workday_calendar=None, original_text=None):
    """Score controlled deadline prose and its due dates in one declared context.

    The inverse receives only the candidate prose and its fixed profile.
    The date and workday context is used after reconstruction. Due date
    equality compares ordered dates at their original statement positions
    in that context. The date lists in the report show the dates alone.
    """
    from datetime import date

    from ipfs_datasets_py.logic.TDFOL.compiler_repairs import (
        CivilWorkdayCalendar, TemporalDeadline, evaluate_civil_deadline,
    )
    from ipfs_datasets_py.logic.legal_ir.extended_contracts import ExtendedDeadlineLegalIR, NormV2
    from ipfs_datasets_py.logic.legal_ir.extended_decompiler import TYPED_DEADLINE_PROSE_PROFILE

    _require(type(reference_ir) is ExtendedDeadlineLegalIR, "typed deadline legal IR required")
    _require(type(candidate_text) is str, "candidate prose text required")
    _require(original_text is None or type(original_text) is str, "optional original source text required")
    _require(type(anchor_dates) is dict, "explicit anchor date mapping required")
    _require(workday_calendar is None or type(workday_calendar) is CivilWorkdayCalendar,
             "explicit civil workday calendar required")
    anchors = dict(anchor_dates)
    _require(all(type(name) is str and type(value) is date for name, value in anchors.items()),
             "anchor dates must map event names to civil dates")

    def due_dates_by_statement(ir):
        result = []
        for statement_index, statement in enumerate(ir.statements):
            if type(statement) is NormV2:
                for deadline in statement.temporal:
                    if type(deadline) is TemporalDeadline:
                        _require(deadline.anchor in anchors, "missing civil date for deadline anchor")
                        due = evaluate_civil_deadline(deadline, anchors[deadline.anchor],
                                                      workday_calendar=workday_calendar)
                        result.append((statement_index, due.isoformat()))
        return result

    profile = TYPED_DEADLINE_PROSE_PROFILE
    reference, candidate, reference_prose, candidate_prose, measurements = _compile_extended_roundtrip(
        reference_ir, candidate_text, profile=profile, original_text=original_text)
    reference_dates = due_dates_by_statement(reference)
    _require(bool(reference_dates), "reference must contain at least one evaluable deadline")
    candidate_dates = None if candidate is None else due_dates_by_statement(candidate)
    return {
        "schema": "legal-civil-deadline-text-roundtrip-score/v1",
        "profile": profile,
        "status": "unsupported_candidate_abstained" if candidate is None else "complete_candidate_scored",
        "input_count": 1, "supported_count": int(candidate is not None),
        "abstention_count": int(candidate is None),
        "normalized_reference_prose": reference_prose,
        "normalized_candidate_prose": candidate_prose,
        "reference_due_dates": [due for _, due in reference_dates],
        "candidate_due_dates": None if candidate_dates is None else [due for _, due in candidate_dates],
        "measurements": {
            **measurements,
            "due_dates_exact": None if candidate_dates is None else candidate_dates == reference_dates,
            "semantic_equivalence_verified": False,
            "source_correspondence_verified": False,
            "proof_validity_verified": False,
        },
        "original_source_available_to_inverse": False,
        "reference_target_available_to_inverse": False,
        "authority": {"source_semantics_verified": False, "admitted": False,
                      "proof_authority": False, "model_quality_established": False},
        "training_mask": 0, "evaluation_gold_mask": 0,
    }


__all__.append("score_deadline_legal_text_roundtrip")



def _compile_extended_roundtrip(reference_ir, candidate_text, *, profile, original_text):
    from ipfs_datasets_py.logic.legal_ir.extended_compiler import compile_extended
    from ipfs_datasets_py.logic.legal_ir.extended_decompiler import decompile_extended

    try:
        candidate_bytes = candidate_text.encode("utf-8")
        original_bytes = None if original_text is None else original_text.encode("utf-8")
    except UnicodeError as error:
        raise LegalTextRoundTripError("valid UTF8 candidate and optional original text required") from error
    _require(len(candidate_bytes) <= _MAX_JSON and (original_bytes is None or len(original_bytes) <= _MAX_JSON),
             "bounded candidate and optional original source text required")
    reference_wire = reference_ir.to_dict()
    reference = type(reference_ir).from_dict(reference_wire)
    candidate = compile_extended(candidate_text, profile=profile)
    reference_prose = decompile_extended(reference, profile=profile)
    candidate_prose = None if candidate is None else decompile_extended(candidate, profile=profile)
    measurements = {
        "original_utf8_exact": None if original_bytes is None else candidate_bytes == original_bytes,
        "canonical_prose_exact": candidate_prose == reference_prose,
        "complete_typed_structure_exact": candidate is not None and candidate.to_dict() == reference_wire,
    }
    return reference, candidate, reference_prose, candidate_prose, measurements


def score_effective_date_legal_text_roundtrip(reference_ir, candidate_text, *,
        as_of_date, original_text=None):
    """Score explicit norm start dates reconstructed from controlled prose.

    The supplied as-of date is used after reconstruction to evaluate each
    explicit inclusive start condition. That result is specific to the
    supplied date and the statement carrying the condition.
    """
    from datetime import date

    from ipfs_datasets_py.logic.legal_ir.extended_contracts import (
        EffectiveFrom, ExtendedEffectiveDateLegalIR, NormV2,
    )
    from ipfs_datasets_py.logic.legal_ir.extended_decompiler import EFFECTIVE_DATE_PROSE_PROFILE

    _require(type(reference_ir) is ExtendedEffectiveDateLegalIR, "typed effective date legal IR required")
    _require(type(candidate_text) is str, "candidate prose text required")
    _require(original_text is None or type(original_text) is str, "optional original source text required")
    _require(type(as_of_date) is date, "exact civil as-of date required")
    profile = EFFECTIVE_DATE_PROSE_PROFILE
    reference, candidate, reference_prose, candidate_prose, measurements = _compile_extended_roundtrip(
        reference_ir, candidate_text, profile=profile, original_text=original_text)

    def dated_statements(ir):
        return [
            {"statement_index": index, "effective_from": condition.effective_from,
             "started_on_as_of": condition.has_started_on(as_of_date)}
            for index, statement in enumerate(ir.statements)
            if type(statement) is NormV2
            for condition in statement.temporal
            if type(condition) is EffectiveFrom
        ]

    reference_dates = dated_statements(reference)
    candidate_dates = None if candidate is None else dated_statements(candidate)

    def projection(rows, field):
        return [(row["statement_index"], row[field]) for row in rows]

    return {
        "schema": "legal-effective-date-text-roundtrip-score/v1",
        "profile": profile,
        "status": "unsupported_candidate_abstained" if candidate is None else "complete_candidate_scored",
        "input_count": 1, "supported_count": int(candidate is not None),
        "abstention_count": int(candidate is None),
        "normalized_reference_prose": reference_prose,
        "normalized_candidate_prose": candidate_prose,
        "as_of_date": as_of_date.isoformat(),
        "reference_effective_dates": reference_dates,
        "candidate_effective_dates": candidate_dates,
        "measurements": {
            **measurements,
            "effective_dates_exact": None if candidate_dates is None else
                projection(candidate_dates, "effective_from") == projection(reference_dates, "effective_from"),
            "start_conditions_exact_as_of": None if candidate_dates is None else
                projection(candidate_dates, "started_on_as_of") == projection(reference_dates, "started_on_as_of"),
            "semantic_equivalence_verified": False,
            "source_correspondence_verified": False,
            "proof_validity_verified": False,
        },
        "original_source_available_to_inverse": False,
        "reference_target_available_to_inverse": False,
        "authority": {"source_semantics_verified": False, "admitted": False,
                      "proof_authority": False, "model_quality_established": False},
        "training_mask": 0,
        "evaluation_gold_mask": 0,
    }


__all__.append("score_effective_date_legal_text_roundtrip")
