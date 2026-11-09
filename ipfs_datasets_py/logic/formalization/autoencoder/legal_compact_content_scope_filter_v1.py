"""Opt-in lexical-scope refinement of the pinned compact LegalIR grammar.

Reuse the existing context, grammar, complete-tree and score validators. This
policy removes locally impossible predicate branches; it neither rewrites an
offered prefix nor changes the old codec, checkpoint inventories or consumers.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import stat

PREFIX_SCHEMA = "legal-compact-content-scope-prefix/v1"
SELECTION_SCHEMA = "legal-compact-content-scope-selection/v1"
POLICY = "lexically-bound-variable-predicate-arguments/v1"
_SELECTOR_REL = "logic/formalization/autoencoder/legal_compact_content_selection_v1.py"
_SELECTOR_SHA = "936b476ea86a406a8c73937bbff9726dcaa3b2314b84b067064d8a618d1ee656"
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_AUTHORITY = dict.fromkeys((
    "accepted", "admitted", "source_semantics_verified", "source_bound",
    "context_permission_verified", "checkpoint_compatibility_verified",
    "model_executed", "training_executed", "logits_origin_verified",
    "training_qualified", "heldout_accuracy", "Lean_admitted",
    "global_prefix_completability_proven",
), False)


class ScopeFilterError(ValueError):
    """Input or pinned-source custody failed; no candidate repair is attempted."""


def _need(ok, message):
    if not ok:
        raise ScopeFilterError(message)


def _owners():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SELECTOR_REL).is_file():
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None and root.resolve() == root, "canonical selector source unavailable")
    path = root / _SELECTOR_REL
    _need(all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents)
          and stat.S_ISREG(path.lstat().st_mode) and path.stat().st_size <= 131072,
          "bounded direct selector source required")
    _need(hashlib.sha256(path.read_bytes()).hexdigest() == _SELECTOR_SHA,
          "pinned selector source differs")
    helper = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_selection_v1")
    _need(Path(helper.__file__).absolute() == path, "selector module origin differs")
    pins = [helper._source(path, _SELECTOR_SHA), helper._source(_SELF_PATH, _SELF_SHA)]
    tokens, token_pins = helper._owner()
    return helper, tokens, pins + token_pins


def _operation(original, work):
    helper, tokens, pins = _owners()
    snapshot = helper._copy(original, helper.MAX_INPUT_BYTES, allow_bytes=True)
    identity = helper._fingerprint(snapshot)
    failure = None

    def fence():
        _need(helper._fingerprint(helper._copy(original, helper.MAX_INPUT_BYTES, allow_bytes=True)) == identity
              and helper._fingerprint(snapshot) == identity, "scope-filter inputs changed")
        current = _owners()
        _need(current[0] is helper and current[1] is tokens and current[2] == pins,
              "scope-filter source custody changed")

    try:
        fence()
        result = work(snapshot, helper, tokens, pins)
        fence()
        return helper._detach(result, helper.MAX_REPORT_BYTES)
    except BaseException as error:
        failure = error
        raise
    finally:
        helper._finish(failure, fence)


def _scope_choices(ids, vocabulary, context, tokens):
    """Replay the pinned parser, refining only constructor/index feasibility.

    Its recursive calls dispatch to this subclass, so bound is the actual
    lexical set at every child, including after a quantified sibling closes.
    A variable can fill multiple argument slots; arity is not binder count.
    """
    class ScopedParser(tokens._PrefixParser):
        def tree(self, bound, depth, formula=True):
            if not formula and not bound:
                raise tokens._GrammarError("no lexically active binder")
            position = self.position
            viable = tuple(index for index, arity in enumerate(self.arities) if bound or arity == 0)
            if formula and self.tokens[position:position + 1] == ["["]:
                if len(self.tokens) == position + 1:
                    raise tokens._More(json.dumps(name) for name in tokens._FORMULAS
                                       if name != "predicate" or viable)
                if self.tokens[position + 1] == '"predicate"':
                    if not viable:
                        raise tokens._GrammarError("predicate arguments require an active binder")
                    if self.tokens[position + 2:position + 3] == [","]:
                        choices = {str(index) for index in viable}
                        if len(self.tokens) == position + 3:
                            raise tokens._More(choices)
                        if self.tokens[position + 3] not in choices:
                            raise tokens._GrammarError("predicate arguments have no viable binding")
            return super().tree(bound, depth, formula)

    terminal = len(ids) > 1 and ids[-1] == tokens.EOS_ID
    body = ids[1:-1] if terminal else ids[1:]
    parser = ScopedParser([vocabulary[index] for index in body], context)
    try:
        parser.document()
    except tokens._More as more:
        return None if terminal else set(more.choices)
    except tokens._GrammarError:
        return None
    return set() if terminal else {"<eos>"}


def _prefix(data, helper, tokens, pins):
    options = {name: data[name] for name in ("expected_context_sha256", "codec", "expected_codec_sha256")}
    baseline = tokens.compact_content_allowed_token_ids_v1(data["prefix_ids"], data["context_raw"], **options)
    # The public owner has validated/captured the full context, codec and IDs.
    # These operation-owned copies remain fenced before and after the replay.
    allowed = list(baseline["allowed_token_ids"])
    status, reason = baseline["status"], baseline["reason"]
    if status == "prefix":
        context = json.loads(data["context_raw"])
        vocabulary = data["codec"]["vocabulary"]
        choices = _scope_choices(data["prefix_ids"], vocabulary, context, tokens)
        allowed = [] if choices is None else [index for index in allowed if vocabulary[index] in choices]
        allowed = [index for index in allowed if _scope_choices(
            data["prefix_ids"] + [index], vocabulary, context, tokens) is not None]
        if not allowed:
            status, reason = "rejected", "no_scope_viable_continuation"
    return dict(schema=PREFIX_SCHEMA, policy=POLICY, status=status, reason=reason,
        offered_ids=list(data["prefix_ids"]), allowed_token_ids=allowed,
        removed_token_ids=sorted(set(baseline["allowed_token_ids"]) - set(allowed)),
        baseline_prefix_report=baseline, codec_sha256=baseline["codec_sha256"],
        context_raw_sha256=baseline["context_raw_sha256"], context_sha256=baseline["context_sha256"],
        owner_pins=pins, local_prefix_only=True, global_completability_proven=False,
        authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0)


def allowed_token_ids(prefix_ids, context_raw, *, expected_context_sha256, codec, expected_codec_sha256):
    """Return a subset of v1 choices under an explicit scope-filter policy.

    Complete-tree decoding remains with tokens_v1. The admitted context permits
    only Object predicates of arity1..8; zero-arity predicates remain unsupported.
    """
    original = dict(prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec, expected_codec_sha256=expected_codec_sha256)
    return _operation(original, _prefix)


def select_token(logits, prefix_ids, context_raw, *, expected_context_sha256, codec, expected_codec_sha256):
    """Apply the refinement to full537 finite scores with lowest-ID ties.

    Retain the original selection separately. No numerical model is invoked,
    score provenance authenticated, checkpoint converted or old inventory changed.
    """
    original = dict(logits=logits, prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec, expected_codec_sha256=expected_codec_sha256)

    def work(data, helper, tokens, pins):
        baseline = helper.select_compact_content_token_v1(**data)
        prefix = _prefix(data, helper, tokens, pins)
        _need(baseline["prefix_report"] == prefix["baseline_prefix_report"],
              "scope filter and original selector prefix disagree")
        choices = prefix["allowed_token_ids"]
        selected = helper._argmax(data["logits"], choices) if choices else None
        return dict(schema=SELECTION_SCHEMA, policy=POLICY,
            status="selected" if selected is not None else "no_selection",
            reason=None if selected is not None else (prefix["reason"] or prefix["status"]),
            selected_token_id=selected, selected_score=data["logits"][selected] if selected is not None else None,
            offered_prefix_ids=list(data["prefix_ids"]),
            next_prefix_ids=list(data["prefix_ids"]) + ([] if selected is None else [selected]),
            logits=list(data["logits"]), logits_sha256=baseline["logits_sha256"],
            baseline_selection=baseline, prefix_report=prefix, tie_breaker="lowest_token_id",
            selection_performed=selected is not None, tokens_appended=int(selected is not None),
            owner_pins=pins, authority=dict(_AUTHORITY), training_mask=0, evaluation_gold_mask=0)

    return _operation(original, work)


__all__ = ["ScopeFilterError", "allowed_token_ids", "select_token"]
