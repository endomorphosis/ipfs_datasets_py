"""Opt-in bounded singleton lookahead over the unchanged completion policy.

Only forced old-policy tokens are inspected after an offered choice. Branches
and exhausted analysis horizons stay unknown; no model, target or branch search
is supplied. A terminal witness is a typed syntactic observation, not authority.
The original v1 policy and every existing runtime/checkpoint remain separate.
"""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import stat

PREFIX_SCHEMA = "legal-compact-content-forced-lookahead-prefix/v1"
SELECTION_SCHEMA = "legal-compact-content-forced-lookahead-selection/v1"
POLICY = "remaining-token-forced-singleton-lookahead/v1"
DEFAULT_MAX_FORCED_TOKENS = 8
MAX_FORCED_TOKENS = 16
MAX_PREFIX_INSPECTIONS = 1 + 537 * (MAX_FORCED_TOKENS + 1)
MAX_REPORT_BYTES = 16 * 1024**2
_LEGACY_SHA = "0d7362815dad5048652020d03967af4908123d74887e71e1823c62aa958783a7"
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()


class CompletionLookaheadError(ValueError):
    """Input, source custody or a contradictory owner observation failed."""


def _need(ok, message):
    if not ok:
        raise CompletionLookaheadError(message)


def _owners():
    path = _SELF_PATH.with_name("legal_compact_content_completion_budget_v1.py")
    info = path.lstat()
    _need(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode)
          and info.st_nlink == 1 and 0 < info.st_size <= 131072
          and hashlib.sha256(path.read_bytes()).hexdigest() == _LEGACY_SHA,
          "pinned canonical completion-v1 source required")
    legacy = importlib.import_module(__package__ + ".legal_compact_content_completion_budget_v1")
    _need(type(legacy.__file__) is str and Path(legacy.__file__).absolute() == path,
          "completion-v1 module origin differs")
    scope, helper, tokens, pins = legacy._owners()
    _need(helper._source(path, _LEGACY_SHA) in pins,
          "original completion-v1 pin absent")
    return legacy, scope, helper, tokens, pins + [helper._source(_SELF_PATH, _SELF_SHA)]


def _operation(original, work):
    legacy, scope, helper, tokens, pins = _owners()
    failure = None

    def fence():
        current = _owners()
        _need(current[:4] == (legacy, scope, helper, tokens) and current[4] == pins,
              "forced-lookahead source custody changed")

    def guarded(data, inner_scope, inner_helper, inner_tokens, old_pins):
        fence()
        _need((inner_scope, inner_helper, inner_tokens) == (scope, helper, tokens)
              and old_pins == pins[:-1], "lookahead and original owners disagree")
        result = work(data, legacy, helper, tokens, pins)
        helper._wire(result, MAX_REPORT_BYTES)
        fence()
        return result

    try:
        result = legacy._operation(original, guarded)
        fence()
        return result
    except BaseException as error:
        failure = error
        raise
    finally:
        helper._finish(failure, fence)


def _horizon(value):
    _need(type(value) is int and 0 <= value <= MAX_FORCED_TOKENS,
          "plain integer max_forced_tokens in0..16 required")


def _prefix(data, legacy, helper, tokens, pins):
    horizon = data["max_forced_tokens"]
    _horizon(horizon)
    options = {key: data[key] for key in
               ("context_raw", "expected_context_sha256", "codec", "expected_codec_sha256")}
    inspections = 0
    witness_inspections = 0

    def inspect(ids, remaining):
        nonlocal inspections
        inspections += 1
        _need(inspections <= MAX_PREFIX_INSPECTIONS, "bounded prefix-inspection limit")
        report = legacy.allowed_token_ids(ids, remaining_new_tokens=remaining, **options)
        _need(report["schema"] == legacy.PREFIX_SCHEMA and report["policy"] == legacy.POLICY
              and report["owner_pins"] == pins[:-1] and report["offered_ids"] == ids
              and report["remaining_new_tokens"] == remaining
              and report["context_raw_sha256"] == data["expected_context_sha256"]
              and report["codec_sha256"] == data["expected_codec_sha256"],
              "original prefix observation identity differs")
        choices = report["allowed_token_ids"]
        _need(type(choices) is list and len(choices) == len(set(choices))
              and all(type(i) is int and 0 <= i < 537 for i in choices)
              and set(choices) <= set(report["scope_prefix_report"]["allowed_token_ids"]),
              "original prefix choices differ")
        return report

    def witness(ids, report):
        nonlocal witness_inspections
        _need(report["status"] == "complete" and ids and ids[-1] == tokens.EOS_ID,
              "terminal EOS required for a completion witness")
        decoded = tokens.decode_compact_content_tokens_v1(ids, **options)
        witness_inspections += 1
        _need(decoded["status"] == "valid_candidate" and decoded["generated_ids"] == ids
              and decoded["framing"]["eos_terminal"] is True,
              "original complete prefix and typed witness disagree")
        return dict(token_ids=list(ids), status=decoded["status"],
                    generated_content_sha256=decoded["generated_content_sha256"],
                    counts=decoded["counts"],
                    typed_report_sha256=hashlib.sha256(
                        helper._wire(decoded, tokens.MAX_REPORT_BYTES)).hexdigest(),
                    syntactic_only=True, model_generated_completion=False)

    baseline = inspect(data["prefix_ids"], data["remaining_new_tokens"])
    outcomes, allowed = [], []
    for candidate in baseline["allowed_token_ids"]:
        if horizon == 0:
            outcomes.append(dict(token_id=candidate, disposition="keep_unknown",
                reason="lookahead_disabled", forced_token_ids=[], terminal_prefix_ids=None,
                terminal_remaining_new_tokens=None, terminal_allowed_token_ids=None,
                terminal_status=None, terminal_reason=None, prefix_inspections=0,
                completion_witness=None))
            allowed.append(candidate)
            continue
        current = list(data["prefix_ids"]) + [candidate]
        remaining = data["remaining_new_tokens"] - 1
        _need(remaining >= 0, "original choice exceeds supplied token allowance")
        forced, before, completion = [], inspections, None
        while True:
            report = inspect(current, remaining)
            choices = report["allowed_token_ids"]
            # A valid terminal document has no next token; it is not a dead end.
            if report["status"] == "complete":
                completion = witness(current, report)
                disposition, reason = "keep_witness", "typed_terminal_completion"
                break
            if not choices:
                disposition, reason = "remove_proven_dead_end", "empty_original_incomplete_frontier"
                break
            if len(choices) > 1:
                disposition, reason = "keep_unknown", "original_branchpoint"
                break
            if len(forced) == horizon:
                disposition, reason = "keep_unknown", "forced_token_horizon"
                break
            _need(remaining > 0, "original singleton exceeds supplied token allowance")
            forced.append(choices[0])
            current.append(choices[0])
            remaining -= 1
        outcomes.append(dict(token_id=candidate, disposition=disposition, reason=reason,
            forced_token_ids=forced, terminal_prefix_ids=current,
            terminal_remaining_new_tokens=remaining,
            terminal_allowed_token_ids=list(report["allowed_token_ids"]),
            terminal_status=report["status"], terminal_reason=report["reason"],
            prefix_inspections=inspections-before, completion_witness=completion))
        if disposition != "remove_proven_dead_end":
            allowed.append(candidate)
    status, reason = baseline["status"], baseline["reason"]
    if baseline["allowed_token_ids"] and not allowed:
        status, reason = "lookahead_exhausted", "all_old_choices_reach_forced_dead_end"
    prefix_witness = (witness(data["prefix_ids"], baseline)
                      if horizon and baseline["status"] == "complete" else None)
    return dict(schema=PREFIX_SCHEMA, policy=POLICY, status=status, reason=reason,
        offered_ids=list(data["prefix_ids"]), allowed_token_ids=allowed,
        removed_token_ids=sorted(set(baseline["allowed_token_ids"]) - set(allowed)),
        baseline_prefix_report=baseline, candidate_lookahead=outcomes,
        remaining_new_tokens=data["remaining_new_tokens"],
        effective_remaining_tokens=baseline["effective_remaining_tokens"],
        max_forced_tokens=horizon, forced_horizon_excludes_initial_choice=True,
        prefix_inspections=inspections, typed_witness_inspections=witness_inspections,
        prefix_completion_witness=prefix_witness,
        codec_sha256=baseline["codec_sha256"],
        context_raw_sha256=baseline["context_raw_sha256"],
        context_sha256=baseline["context_sha256"], owner_pins=pins,
        branch_search_performed=False, model_or_future_score_queries=False,
        global_completability_proven=False, unknown_branches_retain_choices=True,
        authority=dict(baseline["authority"]), training_mask=0, evaluation_gold_mask=0)


def allowed_token_ids(prefix_ids, context_raw, *, expected_context_sha256, codec,
                      expected_codec_sha256, remaining_new_tokens,
                      max_forced_tokens=DEFAULT_MAX_FORCED_TOKENS):
    """Filter v1 choices only by an empty frontier after at most16 forced tokens.

    The initial offered choice consumes one token independently of the horizon.
    Horizon0 retains the exact original mask without post-choice inspection.
    Positive horizons inspect after the choice and after each forced append.
    """
    original = dict(prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec,
        expected_codec_sha256=expected_codec_sha256,
        remaining_new_tokens=remaining_new_tokens, max_forced_tokens=max_forced_tokens)
    return _operation(original, _prefix)


def select_token(logits, prefix_ids, context_raw, *, expected_context_sha256, codec,
                 expected_codec_sha256, remaining_new_tokens,
                 max_forced_tokens=DEFAULT_MAX_FORCED_TOKENS):
    """Validate every original score, then use the retained mask and lowest-ID tie.

    Probes use no scores and append nothing to the caller's prefix. Only the
    selected first token appears in next_prefix_ids, including a scored EOS.
    """
    original = dict(logits=logits, prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec,
        expected_codec_sha256=expected_codec_sha256,
        remaining_new_tokens=remaining_new_tokens, max_forced_tokens=max_forced_tokens)

    def work(data, legacy, helper, tokens, pins):
        _horizon(data["max_forced_tokens"])
        original_selection = legacy.select_token(**{key: value for key, value in data.items()
                                                     if key != "max_forced_tokens"})
        prefix = _prefix(data, legacy, helper, tokens, pins)
        _need(original_selection["prefix_report"] == prefix["baseline_prefix_report"],
              "original selection and lookahead prefix disagree")
        choices = prefix["allowed_token_ids"]
        selected = helper._argmax(data["logits"], choices) if choices else None
        return dict(schema=SELECTION_SCHEMA, policy=POLICY,
            status="selected" if selected is not None else "no_selection",
            reason=None if selected is not None else (prefix["reason"] or prefix["status"]),
            selected_token_id=selected,
            selected_score=data["logits"][selected] if selected is not None else None,
            offered_prefix_ids=list(data["prefix_ids"]),
            next_prefix_ids=list(data["prefix_ids"]) + ([] if selected is None else [selected]),
            logits=list(data["logits"]), logits_sha256=original_selection["logits_sha256"],
            baseline_selection=original_selection, prefix_report=prefix,
            tie_breaker="lowest_token_id", selection_performed=selected is not None,
            tokens_appended=int(selected is not None), owner_pins=pins,
            authority=dict(prefix["authority"]), training_mask=0, evaluation_gold_mask=0)

    return _operation(original, work)


__all__ = ["CompletionLookaheadError", "allowed_token_ids", "select_token"]
