"""Opt-in completion lower bounds over the pinned compact LegalIR scope policy.

The bound is the shortest suffix in an explicit relaxation of the existing
canonical grammar, not a completion witness or semantic interpretation. Global
predicate coverage, lexical binding, quantifier presence, binder order and node/
depth limits are omitted from that relaxation. These omissions only enlarge its
language. A known bound can rule out a choice; an unknown bound retains it.

No historical codec, selector, checkpoint inventory or consumer is modified.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import stat

PREFIX_SCHEMA = "legal-compact-content-completion-budget-prefix/v1"
SELECTION_SCHEMA = "legal-compact-content-completion-budget-selection/v1"
POLICY = "remaining-token-relaxed-grammar-lower-bound/v1"
BOUND_METHOD = "relaxed-canonical-grammar/v1"
MAX_REPLAY_STEPS = 4096
MAX_STACK_ITEMS = 4096
_SCOPE_REL = "logic/formalization/autoencoder/legal_compact_content_scope_filter_v1.py"
_SCOPE_SHA = "7b77e5d71012f9394ec0eb9fa05a70310644a3ed5e334f8e91904354b6a187b9"
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_AUTHORITY = dict.fromkeys((
    "accepted", "admitted", "source_semantics_verified", "source_bound",
    "context_permission_verified", "checkpoint_compatibility_verified",
    "model_executed", "training_executed", "logits_origin_verified",
    "training_qualified", "heldout_accuracy", "Lean_admitted",
    "global_prefix_completability_proven",
), False)
_RELAXATIONS = [
    "Every declared predicate need not occur.",
    "A quantifier need not occur and its integer need not follow binder order.",
    "Variable indices need not be lexically bound.",
    "Node and depth limits are omitted from the lower-bound language.",
]


class CompletionBudgetError(ValueError):
    """Input or pinned-source custody failed; no prefix repair is attempted."""


def _need(ok, message):
    if not ok:
        raise CompletionBudgetError(message)


def _owners():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SCOPE_REL).is_file():
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None and root.resolve() == root, "canonical scope source unavailable")
    path = root / _SCOPE_REL
    _need(all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents)
          and stat.S_ISREG(path.lstat().st_mode) and path.stat().st_size <= 131072,
          "bounded direct scope source required")
    _need(hashlib.sha256(path.read_bytes()).hexdigest() == _SCOPE_SHA, "pinned scope source differs")
    scope = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_scope_filter_v1")
    _need(Path(scope.__file__).absolute() == path, "scope module origin differs")
    helper, tokens, scope_pins = scope._owners()
    _need(helper._source(path, _SCOPE_SHA) in scope_pins, "scope source pin absent")
    return scope, helper, tokens, scope_pins + [helper._source(_SELF_PATH, _SELF_SHA)]


def _operation(original, work):
    scope, helper, tokens, pins = _owners()
    failure = None

    def fence():
        current = _owners()
        _need(current[0] is scope and current[1] is helper and current[2] is tokens
              and current[3] == pins, "completion-budget source custody changed")

    def guarded(data, inner_helper, inner_tokens, scope_pins):
        fence()
        _need(inner_helper is helper and inner_tokens is tokens and scope_pins == pins[:-1],
              "completion-budget and scope dependency identities disagree")
        result = work(data, scope, helper, tokens, pins)
        fence()
        return result

    try:
        result = scope._operation(original, guarded)
        fence()
        return result
    except BaseException as error:
        failure = error
        raise
    finally:
        helper._finish(failure, fence)


def _unknown(reason):
    return dict(status="unknown", minimum_additional_tokens=None, reason=reason,
                method=BOUND_METHOD, completed=False)


def _completion_lower_bound(ids, vocabulary, context):
    """Shortest residual length of a relaxed grammar; no greedy completion.

    The deterministic lexical prefix leaves a stack of pending grammar symbols.
    Every unconstrained formula can use the cheapest declared predicate: its
    lexical length is 7 + 6 * arity. Wrappers have positive extra cost, and
    binary constructors contain two formulas, so none can be shorter. A variable
    has length 5. Residual costs add because their token positions are disjoint.
    Dynamic predicate indices retain the exact chosen arity once consumed.

    Baseline owners validate the actual language separately. This replay cannot
    reject a baseline prefix: unsupported input or bounded analysis exhaustion
    returns unknown and does not remove any choice.
    """
    arities = [len(symbol["domain"]) for symbol in context["signature"]["symbols"]]
    if not arities or any(type(a) is not int or not 1 <= a <= 8 for a in arities):
        return _unknown("unsupported_predicate_arity")
    if len(ids) > 512 or any(type(i) is not int or not 0 <= i < len(vocabulary) for i in ids):
        return _unknown("unsupported_lexical_input")
    minimum_arity = min(arities)
    formula_cost = 7 + 6 * minimum_arity
    # Lists are placed in natural order then pushed in reverse; last is next.
    pending = []

    def push(*symbols):
        pending.extend(reversed(symbols))

    def lit(value):
        return ("literal", value)

    push(lit("<bos>"), lit("{"), lit('"schema"'), lit(":"),
         lit('"legal-relational-compact-content/v1"'), lit(","),
         lit('"tree"'), lit(":"), ("formula",), lit("}"), lit("<eos>"))
    steps = 0
    for token_id in ids:
        lexical = vocabulary[token_id]
        while pending and pending[-1][0] in {"formula", "variable"}:
            steps += 1
            if steps > MAX_REPLAY_STEPS or len(pending) > MAX_STACK_ITEMS:
                return _unknown("analysis_work_limit")
            kind = pending.pop()[0]
            if kind == "formula":
                push(lit("["), ("constructor",))
            else:
                push(lit("["), lit('"variable"'), lit(","), ("integer",), lit("]"))
        steps += 1
        if steps > MAX_REPLAY_STEPS or len(pending) > MAX_STACK_ITEMS:
            return _unknown("analysis_work_limit")
        if not pending:
            return _unknown("tokens_after_relaxed_document")
        symbol = pending.pop()
        kind = symbol[0]
        if kind == "literal":
            if lexical != symbol[1]:
                return _unknown("relaxed_prefix_mismatch")
        elif kind == "integer":
            if not lexical.isascii() or not lexical.isdigit() or str(int(lexical)) != lexical or not 0 <= int(lexical) <= 511:
                return _unknown("unsupported_integer")
        elif kind == "letter":
            if lexical not in {'"O"', '"P"', '"F"'}:
                return _unknown("unsupported_modality")
        elif kind == "predicate_index":
            if not lexical.isascii() or not lexical.isdigit() or str(int(lexical)) != lexical or not 0 <= int(lexical) < len(arities):
                return _unknown("unsupported_predicate_index")
            arguments = []
            for number in range(arities[int(lexical)]):
                if number:
                    arguments.append(lit(","))
                arguments.append(("variable",))
            push(lit(","), lit("["), *arguments, lit("]"), lit("]"))
        elif kind == "constructor":
            if lexical == '"predicate"':
                push(lit(","), ("predicate_index",))
            elif lexical in {'"forall"', '"exists"'}:
                push(lit(","), ("integer",), lit(","), ("formula",), lit("]"))
            elif lexical in {'"and"', '"or"', '"implies"', '"iff"'}:
                push(lit(","), ("formula",), lit(","), ("formula",), lit("]"))
            elif lexical == '"not"':
                push(lit(","), ("formula",), lit("]"))
            elif lexical == '"extension"':
                push(lit(","), ("letter",), lit(","), ("formula",), lit("]"))
            else:
                return _unknown("unsupported_constructor")
        else:
            return _unknown("unsupported_pending_symbol")
    costs = dict(literal=1, integer=1, letter=1, variable=5,
                 formula=formula_cost, constructor=formula_cost - 1,
                 predicate_index=4 + 6 * minimum_arity)
    if len(pending) > MAX_STACK_ITEMS:
        return _unknown("analysis_work_limit")
    return dict(status="lower_bound", minimum_additional_tokens=sum(costs[item[0]] for item in pending),
                reason=None, method=BOUND_METHOD, completed=not pending)


def _prefix(data, scope, helper, tokens, pins):
    remaining = data["remaining_new_tokens"]
    _need(type(remaining) is int and 0 <= remaining <= tokens.MAX_SEQUENCE_TOKENS,
          "remaining-new-token allowance must be a plain integer in 0..512")
    scope_data = {key: value for key, value in data.items() if key not in {"remaining_new_tokens", "logits"}}
    scope_report = scope._prefix(scope_data, helper, tokens, pins[:-1])
    baseline = scope_report["baseline_prefix_report"]
    effective = min(remaining, tokens.MAX_SEQUENCE_TOKENS - len(data["prefix_ids"]))
    context = json.loads(data["context_raw"])
    vocabulary = data["codec"]["vocabulary"]
    prefix_bound = _completion_lower_bound(data["prefix_ids"], vocabulary, context)
    allowed, bounds = [], []
    for token_id in scope_report["allowed_token_ids"]:
        bound = _completion_lower_bound(data["prefix_ids"] + [token_id], vocabulary, context)
        known = bound["status"] == "lower_bound"
        minimum = 1 + bound["minimum_additional_tokens"] if known else 1
        over = minimum > effective
        disposition = "remove_proven_over_budget" if over else ("keep" if known else "keep_unknown")
        bounds.append(dict(token_id=token_id, **bound, minimum_tokens_with_choice=minimum,
                           disposition=disposition))
        if not over:
            allowed.append(token_id)
    status, reason = scope_report["status"], scope_report["reason"]
    if scope_report["allowed_token_ids"] and not allowed:
        status, reason = "budget_exhausted", "no_scope_continuation_within_remaining_budget"
    return dict(schema=PREFIX_SCHEMA, policy=POLICY, status=status, reason=reason,
        offered_ids=list(data["prefix_ids"]), allowed_token_ids=allowed,
        removed_token_ids=sorted(set(baseline["allowed_token_ids"]) - set(allowed)),
        budget_removed_token_ids=sorted(set(scope_report["allowed_token_ids"]) - set(allowed)),
        baseline_prefix_report=baseline, scope_prefix_report=scope_report,
        remaining_new_tokens=remaining, effective_remaining_tokens=effective,
        prefix_lower_bound=prefix_bound, candidate_bounds=bounds,
        codec_sha256=baseline["codec_sha256"], context_raw_sha256=baseline["context_raw_sha256"],
        context_sha256=baseline["context_sha256"], owner_pins=pins,
        local_prefix_only=True, global_completability_proven=False,
        relaxed_grammar_omissions=list(_RELAXATIONS), unknown_bounds_retain_choices=True,
        authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0)


def allowed_token_ids(prefix_ids, context_raw, *, expected_context_sha256, codec,
                      expected_codec_sha256, remaining_new_tokens):
    """Refine scope choices only when a sound lower bound exceeds the budget."""
    original = dict(prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec,
        expected_codec_sha256=expected_codec_sha256, remaining_new_tokens=remaining_new_tokens)
    return _operation(original, _prefix)


def select_token(logits, prefix_ids, context_raw, *, expected_context_sha256, codec,
                 expected_codec_sha256, remaining_new_tokens):
    """Select one full537 finite score using the identical explicit budget."""
    original = dict(logits=logits, prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec,
        expected_codec_sha256=expected_codec_sha256, remaining_new_tokens=remaining_new_tokens)

    def work(data, scope, helper, tokens, pins):
        scope_data = {key: value for key, value in data.items() if key != "remaining_new_tokens"}
        scope_selection = scope.select_token(**scope_data)
        prefix = _prefix(data, scope, helper, tokens, pins)
        _need(scope_selection["prefix_report"] == prefix["scope_prefix_report"]
              and scope_selection["baseline_selection"]["prefix_report"] == prefix["baseline_prefix_report"],
              "completion budget and scope selector prefix disagree")
        selected = helper._argmax(data["logits"], prefix["allowed_token_ids"]) if prefix["allowed_token_ids"] else None
        return dict(schema=SELECTION_SCHEMA, policy=POLICY,
            status="selected" if selected is not None else "no_selection",
            reason=None if selected is not None else (prefix["reason"] or prefix["status"]),
            selected_token_id=selected, selected_score=data["logits"][selected] if selected is not None else None,
            offered_prefix_ids=list(data["prefix_ids"]),
            next_prefix_ids=list(data["prefix_ids"]) + ([] if selected is None else [selected]),
            logits=list(data["logits"]), logits_sha256=scope_selection["logits_sha256"],
            baseline_selection=scope_selection["baseline_selection"], scope_selection=scope_selection,
            prefix_report=prefix, tie_breaker="lowest_token_id",
            remaining_new_tokens=data["remaining_new_tokens"],
            selection_performed=selected is not None, tokens_appended=int(selected is not None),
            owner_pins=pins, authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0)

    return _operation(original, work)


__all__ = ["CompletionBudgetError", "allowed_token_ids", "select_token"]
