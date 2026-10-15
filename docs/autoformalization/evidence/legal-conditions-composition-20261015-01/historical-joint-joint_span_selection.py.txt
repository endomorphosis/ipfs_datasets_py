"""Pure, opt-in compatible span selection from saved decoder head scores.

This is a different readout policy, never a repaired raw decoder result. Presence
and modality decisions are fixed before search. The objective is a float64 sum
of float32 start-plus-end scores; it has no legal or probabilistic interpretation.
Optimality applies only to the declared candidate domain and completed search.
The retained tokenizer and typed single-rule codec are used without constructing
or invoking a model. Importing this module loads only the Python standard library.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import struct

SCORE_SCHEMA = "joint-source-span-scores/v1"
SCHEMA = "joint-copied-span-selection/v1"
ORIGIN = "bounded_joint_source_span_selector"
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
OPTIONAL_FIELDS = FIELDS[2:]
QUALIFIERS = FIELDS[3:]
MODALITIES = ("O", "P", "F")
AMBIGUITY_GUARD = 1e-7
MAX_TOP_K = 16
MAX_SEARCH_NODES = 50000
FALSE = {
    "qualified": False, "admitted": False, "formalized": False,
    "roundtrip_ok": False, "proof_authority": False,
    "semantic_correctness_verified": False, "promotion_performed": False,
    "publication_performed": False, "default_promoted": False,
    "target_access": False, "teacher_forcing": False,
    "training_executed": False, "model_execution_performed": False,
    "encoder_execution_performed": False, "Lake_executed": False,
}


class JointSelectionError(ValueError):
    """Malformed, incompatible, oversized or nonfinite score input."""


def _require(condition, message):
    if not condition:
        raise JointSelectionError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _f32(value, name, *, exact=False):
    _require(type(value) in (int, float), name + " must be a float32 number, never boolean")
    try:
        _require(math.isfinite(value), name + " must be finite")
        result = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error) as error:
        raise JointSelectionError(name + " overflows float32") from error
    _require(math.isfinite(result), name + " overflows float32")
    _require(not exact or result == value, name + " is not an exact saved float32 value")
    return result


def _keys(value, expected, name):
    _require(type(value) is dict and set(value) == set(expected), name + " fields differ")


def _owner():
    # The owner imports no tensor library until its explicit numerical methods.
    return importlib.import_module(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula")


def _validated(source, scores):
    _require(type(source) is str, "source_text must be an exact string")
    try:
        source.encode("utf-8")
        tokens = _owner().tokenize_source(source)
    except (ValueError, UnicodeError) as error:
        raise JointSelectionError("source tokenization rejected: " + str(error)) from error
    expected = [{key: token[key] for key in ("text", "start", "end")} for token in tokens]
    _keys(scores, ("schema", "tokens", "modality_logits", "presence_logits",
                  "start_logits", "end_logits"), "saved scores")
    _require(type(scores["schema"]) is str and scores["schema"] == SCORE_SCHEMA,
             "saved score schema differs")
    _require(type(scores["tokens"]) is list and len(scores["tokens"]) == len(expected),
             "saved tokens must cover the complete owner tokenization")
    for token in scores["tokens"]:
        _keys(token, ("text", "start", "end"), "saved token")
        _require(type(token["text"]) is str and type(token["start"]) is int
                 and type(token["end"]) is int, "saved token value types differ")
    _require(_raw(scores["tokens"]) == _raw(expected),
             "saved tokens must cover the exact complete owner tokenization")

    def vector(value, size, name):
        _require(type(value) is list and len(value) == size, name + " length differs")
        return [_f32(item, name, exact=True) for item in value]

    clean = {"schema": SCORE_SCHEMA, "tokens": expected,
             "modality_logits": vector(scores["modality_logits"], 3, "modality_logits")}
    for name, fields, size in (("presence_logits", OPTIONAL_FIELDS, 2),
                               ("start_logits", FIELDS, len(tokens)),
                               ("end_logits", FIELDS, len(tokens))):
        _keys(scores[name], fields, name)
        clean[name] = {field: vector(scores[name][field], size, name + "." + field)
                       for field in fields}
    return clean


def _choice(logits):
    indices = sorted(range(len(logits)), key=lambda index: (-logits[index], index))
    margin = _f32(logits[indices[0]] - logits[indices[1]], "decision margin")
    return indices[0], margin


def _rank_spans(scores, field):
    start, end = scores["start_logits"][field], scores["end_logits"][field]
    # Row-major coordinates are the owner's stable tie order, with left <= right.
    candidates = [(_f32(start[left] + end[right], "span score"), left, right)
                  for left in range(len(start)) for right in range(left, len(end))]
    candidates.sort(key=lambda span: (-span[0], span[1], span[2]))
    margin = (_f32(candidates[0][0] - candidates[1][0], "span margin")
              if len(candidates) > 1 else None)
    return candidates, margin


def _span(source, tokens, candidate):
    score, left, right = candidate
    begin, end = tokens[left]["start"], tokens[right]["end"]
    return {"token_start": left, "token_end_inclusive": right,
            "char_start": begin, "char_end": end,
            "utf8_byte_start": len(source[:begin].encode("utf-8")),
            "utf8_byte_end": len(source[:end].encode("utf-8")),
            "text": source[begin:end], "span_score_float32": score}


def _canonical(source, tokens, modality, present, selection):
    rule = {"modality": modality}
    for field in FIELDS:
        atom = _span(source, tokens, selection[field])["text"] if present[field] else ""
        rule[field] = ([atom] if present[field] else []) if field in QUALIFIERS else atom
    ir = {"rules": [rule]}
    # This checks the existing canonical contract and single-rule deontic grammar.
    _owner().codec_module._rule(ir)
    return ir


def _greedy(source, scores, rankings):
    """Reconstruct the legacy sequential readout; never label it a raw report."""
    tokens = scores["tokens"]
    result = {"origin": "reconstructed_independent_greedy_from_saved_scores",
              "actual_owner_report": False, "status": "abstained", "reason": None,
              "canonical_ir": None, "facets": {}, "minimum_decision_logit_margin": None,
              **FALSE}
    modality, margin = _choice(scores["modality_logits"])
    if margin <= AMBIGUITY_GUARD:
        result["reason"] = "ambiguous_decoder_scores"
        return result
    minimum = margin
    occupied, selection, present = set(), {}, {}
    for field in FIELDS:
        enabled, presence_margin = True, None
        if field in OPTIONAL_FIELDS:
            choice, presence_margin = _choice(scores["presence_logits"][field])
            if presence_margin <= AMBIGUITY_GUARD:
                result["reason"] = "ambiguous_decoder_scores"
                return result
            minimum = min(minimum, presence_margin)
            enabled = choice == 1
        present[field] = enabled
        diagnostic = {"present": enabled, "presence_logit_margin": presence_margin,
                      "span": None, "span_logit_margin": None}
        if enabled:
            candidates, span_margin = rankings[field]
            if span_margin is not None and span_margin <= AMBIGUITY_GUARD:
                result["reason"] = "ambiguous_decoder_scores"
                return result
            if span_margin is not None:
                minimum = min(minimum, span_margin)
            candidate = candidates[0]
            diagnostic.update(span=_span(source, tokens, candidate), span_logit_margin=span_margin)
            result["facets"][field] = diagnostic
            positions = set(range(candidate[1], candidate[2] + 1))
            if occupied & positions:
                result["reason"] = "copied_spans_overlap"
                return result
            occupied.update(positions)
            selection[field] = candidate
        result["facets"][field] = diagnostic
    try:
        ir = _canonical(source, tokens, MODALITIES[modality], present, selection)
    except ValueError as error:
        result.update(reason="generated_ir_rejected", detail=str(error))
        return result
    result.update(status="decoded", canonical_ir=ir, minimum_decision_logit_margin=minimum)
    return result


def select_joint_spans(source_text, scores, *, top_k=8, max_search_nodes=50000):
    """Select one nonoverlapping span for every fixed present facet.

    ``scores`` is a closed SCORE_SCHEMA JSON packet of full float32 heads and
    exact owner tokens. Required actor/action have no presence head. Optional
    presence and modality argmax ties within 1e-7 cause abstention. Span ties may
    be resolved by compatibility, but a joint objective tie causes abstention.
    A truncated candidate domain never establishes full-domain optimality.
    Any search-budget cutoff returns abstention, even if a candidate was found.
    """
    _require(type(top_k) is int and 1 <= top_k <= MAX_TOP_K, "top_k must be between 1 and 16")
    _require(type(max_search_nodes) is int and 1 <= max_search_nodes <= MAX_SEARCH_NODES,
             "max_search_nodes must be between 1 and 50000")
    clean = _validated(source_text, scores)
    tokens = clean["tokens"]
    modality_index, modality_margin = _choice(clean["modality_logits"])
    decisions = {"modality": MODALITIES[modality_index], "modality_logit_margin": modality_margin,
                 "facets": {}}
    present = {}
    ambiguous = modality_margin <= AMBIGUITY_GUARD
    rankings = {}
    for field in FIELDS:
        enabled, margin = True, None
        if field in OPTIONAL_FIELDS:
            choice, margin = _choice(clean["presence_logits"][field])
            enabled = choice == 1
            ambiguous |= margin <= AMBIGUITY_GUARD
        present[field] = enabled
        decisions["facets"][field] = {"present": enabled, "required": field not in OPTIONAL_FIELDS,
            "presence_logit_margin": margin,
            "origin": "fixed_saved_head_argmax_completed_independently_of_raw_early_refusal"}
        if enabled:
            rankings[field] = _rank_spans(clean, field)
    greedy = _greedy(source_text, clean, rankings)
    domains = {field: rankings[field][0][:top_k] for field in FIELDS if present[field]}
    candidate_summary = {}
    for field, candidates in domains.items():
        full = rankings[field][0]
        truncated = len(full) > len(candidates)
        boundary_margin = (_f32(candidates[-1][0] - full[len(candidates)][0], "candidate boundary margin")
                           if truncated else None)
        candidate_summary[field] = {"valid_span_count": len(full), "retained_count": len(candidates),
            "truncated": truncated, "boundary_score_margin_float32": boundary_margin,
            "boundary_tied_within_guard": boundary_margin is not None and boundary_margin <= AMBIGUITY_GUARD,
            "independent_best_span_margin_float32": rankings[field][1]}
    truncated = any(item["truncated"] for item in candidate_summary.values())
    search = {"visited_nodes": 0, "conflict_nodes": 0, "bound_pruned_nodes": 0,
              "feasible_assignments": 0, "budget_exhausted": False, "completed": False,
              "retained_domain_optimality_established": False,
              "full_domain_optimality_established": False, "unique_within_guard": False,
              "best_score": None, "runner_up_score": None, "joint_score_margin": None,
              "best_observed_spans": None,
              "node_count_scope": "every attempted facet assignment, including conflicts and pruned nodes"}
    result = {"schema": SCHEMA, "origin": ORIGIN, "status": "abstained", "reason": None,
              "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
              "scores_sha256": hashlib.sha256(_raw(clean)).hexdigest(), "input_token_count": len(tokens),
              "top_k": top_k, "max_search_nodes": max_search_nodes, "ambiguity_guard": AMBIGUITY_GUARD,
              "objective": "math.fsum_float64_of_float32_start_plus_end_in_canonical_facet_order/v1",
              "candidate_domain_truncated": truncated, "candidate_summary": candidate_summary,
              "fixed_decisions": decisions, "independent_greedy": greedy, "search": search,
              "canonical_ir": None, "span_diagnostics": None, "formal_outputs": [],
              "canonical_rule_valid": False, "family_syntax_checked": False,
              "readout_policy_changed": True, "raw_output_repaired": False, **FALSE}
    if ambiguous:
        result["reason"] = "ambiguous_fixed_head_decision"
        return result

    fields = tuple(domains)
    top_two = []

    def visit(depth, chosen, occupied):
        if depth == len(fields):
            value = math.fsum(chosen[field][0] for field in fields)
            coordinates = tuple((chosen[field][1], chosen[field][2]) for field in fields)
            top_two.append((value, coordinates, dict(chosen)))
            top_two.sort(key=lambda item: (-item[0], item[1]))
            del top_two[2:]
            search["feasible_assignments"] += 1
            return
        field = fields[depth]
        for candidate in domains[field]:
            if search["visited_nodes"] >= max_search_nodes:
                search["budget_exhausted"] = True
                return
            search["visited_nodes"] += 1
            positions = ((1 << (candidate[2] - candidate[1] + 1)) - 1) << candidate[1]
            if positions & occupied:
                search["conflict_nodes"] += 1
                continue
            chosen[field] = candidate
            # Prune only below the known runner-up, preserving all best-score ties.
            bound = math.fsum([chosen[item][0] for item in fields[:depth + 1]] +
                              [domains[item][0][0] for item in fields[depth + 1:]])
            if len(top_two) == 2 and bound < top_two[1][0]:
                search["bound_pruned_nodes"] += 1
            else:
                visit(depth + 1, chosen, occupied | positions)
            del chosen[field]
            if search["budget_exhausted"]:
                return

    visit(0, {}, 0)
    search["completed"] = not search["budget_exhausted"]
    if top_two:
        search["best_score"] = top_two[0][0]
        search["best_observed_spans"] = {field: _span(source_text, tokens, candidate)
                                         for field, candidate in top_two[0][2].items()}
    if len(top_two) == 2:
        search["runner_up_score"] = top_two[1][0]
        search["joint_score_margin"] = top_two[0][0] - top_two[1][0]
    if search["budget_exhausted"]:
        result["reason"] = "search_budget_exhausted"
        return result
    if not top_two:
        result["reason"] = "no_compatible_assignment_in_retained_domain"
        return result
    search["retained_domain_optimality_established"] = True
    search["full_domain_optimality_established"] = not truncated
    if len(top_two) == 2 and search["joint_score_margin"] <= AMBIGUITY_GUARD:
        result["reason"] = "ambiguous_joint_scores"
        return result
    search["unique_within_guard"] = True
    selection = top_two[0][2]
    try:
        ir = _canonical(source_text, tokens, decisions["modality"], present, selection)
    except ValueError as error:
        result.update(reason="generated_ir_rejected", detail=str(error))
        return result
    diagnostics = {field: {"present": present[field],
                           "span": _span(source_text, tokens, selection[field]) if present[field] else None}
                   for field in FIELDS}
    display = json.dumps(ir, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result.update(status="selected", canonical_ir=ir, span_diagnostics=diagnostics,
                  canonical_rule_valid=True, family_syntax_checked=True,
                  formal_outputs=[{"family": "deontic", "format": "typed-deontic-rule/v1",
                      "payload": ir["rules"][0].copy(), "formula_text": display,
                      "formula_text_role": "display_only_full_ast_is_authoritative",
                      "origin": ORIGIN, **FALSE}])
    return result
