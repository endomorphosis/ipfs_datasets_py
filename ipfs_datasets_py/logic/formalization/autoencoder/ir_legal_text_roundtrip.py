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


def score_legal_original_text_roundtrip(corpus_pin, captured_inputs, candidate_report, *,
        render_canonical=False, renderer=None, max_edit_cells=2_000_000, max_reference_bytes=_MAX_JSON):
    """Score an explicit cached cohort; never invoke its numerical decoder.

    Captured rows must be exactly ``{id, source_text, embedding}``. Gold remains
    detached from rendering, which receives ``(predicted_ir, request_id)`` only.
    A supplied renderer is a caller-owned boundary, not authenticated model or
    source-free behavior. The built-in opt-in renderer is deterministic and has
    no learned prose head. Missing/duplicate/invalid outputs receive zero credit
    in all selected-row accuracy denominators, with coverage recorded separately.
    """
    _require(type(render_canonical) is bool and (renderer is None or render_canonical and callable(renderer)),
             "renderer requires explicit canonical-rendering selection")
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
        results.append(result)
    # Reread the complete corpus after optional caller-owned rendering. This
    # observes endpoint stability; no atomic multi-file/current-model claim.
    _read_pin(pin, max_reference_bytes)
    total = len(gold)
    counts = {key: sum(row["outcome"] == key for row in results) for key in ("decoded", "abstained", "refused", "missing", "duplicate")}
    counts.update(attempted=total, exact_ir=sum(row["exact_ir"] for row in results),
        rendered=sum(row["rendering"]["status"] == "rendered" for row in results) if render_canonical else None,
        rendering_refused=sum(row["rendering"]["status"] == "refused" for row in results) if render_canonical else None,
        exact_original_utf8=sum(row["rendering"]["exact_original_utf8"] is True for row in results) if render_canonical else None,
        whitespace_collapsed_exact=sum(row["rendering"]["whitespace_collapsed_exact"] is True for row in results) if render_canonical else None)
    provenance_ok = not any(row["reason"] == "invalid_prediction_schema_or_source_provenance" for row in results)
    edits = {}
    for name in ("character_edit", "whitespace_token_edit"):
        scored = [row["rendering"][name]["distance"] for row in results
            if row["rendering"][name] is not None and row["rendering"][name]["status"] == "scored"]
        edits[name] = {"scored_rows": len(scored), "attempted_rows": total,
            "mean_distance_on_scored_rows": sum(scored) / len(scored) if scored else None,
            "scored_coverage_fraction": len(scored) / total,
            "mean_excludes_unrendered_and_budget_exhausted_rows": True}
    return {"schema": SCHEMA, "corpus_pin": pin, "source_embeddings_metadata_sha256": _digest(corpus["source_embeddings"]),
        "captured_inputs_sha256": _digest(inputs), "candidate_report_sha256": _digest(report),
        "coverage": {"valid": coverage_ok, "expected_count": total, "prediction_count": len(predictions),
            "missing_ids": missing, "unexpected_ids": unexpected, "duplicate_ids": duplicate, "invalid_id_row_indices": invalid_ids},
        "report_envelope_valid": envelope_ok, "prediction_provenance_valid": provenance_ok,
        "valid_evaluation": envelope_ok and coverage_ok and provenance_ok,
        "operational_complete": envelope_ok and coverage_ok and provenance_ok and counts["decoded"] == total
            and (not render_canonical or counts["rendered"] == total),
        "counts": counts, "rates": {"denominator": "all_captured_input_rows", "exact_ir": counts["exact_ir"] / total,
            "exact_original_utf8": counts["exact_original_utf8"] / total if render_canonical else None,
            "whitespace_collapsed_exact": counts["whitespace_collapsed_exact"] / total if render_canonical else None},
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


__all__ = ["SCHEMA", "LegalTextRoundTripError", "score_legal_original_text_roundtrip"]
