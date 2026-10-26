"""Pure closed role weights over offered, source-committed scope inventories.

The enclosing training owner must independently validate/recompute the original
basis checkpoint and grammar inventories. This module checks byte commitments,
lexical/tree annotations and the fixed two-binder geometry; it does not confer
upstream checkpoint, source, legal, training-gold or evaluation authority.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
import re

POLICY_SCHEMA = "legal-compact-role-objective/v1"
INVENTORY_SCHEMA = "legal-compact-role-inventory/v1"
MAXIMUM = 24 * 1024**2
SCOPE_POLICY = "lexically-bound-variable-predicate-arguments/v1"
WEIGHTINGS = ("baseline", "semantic_priority")
ROLE_COUNTS = {"quantifier_constructor": 2, "modal_constructor": 1,
               "modal_letter": 1, "predicate_constructor": 1, "variable_reference": 2}
AUTHORITY = dict.fromkeys(("source_semantics_verified", "legal_roles_verified", "upstream_checkpoint_validated",
    "upstream_grammar_reexecuted", "source_encoder_authenticated", "training_gold_qualified",
    "evaluation_gold_qualified", "accepted", "admitted", "proof_authority", "Lean_admitted"), False)
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class RolePolicyError(ValueError):
    """Malformed commitment, annotation, unsupported geometry or policy."""


def _need(condition, message):
    if not condition:
        raise RolePolicyError(message)


def _wire(value):
    active = set()
    def ordinary(item, depth):
        _need(depth <= 128, "bounded ordinary JSON depth required")
        kind = type(item)
        _need(kind in (dict, list, str, int, float, bool, type(None)), "ordinary JSON values required")
        if kind is float: _need(math.isfinite(item), "finite JSON required")
        if kind in (dict, list):
            _need(id(item) not in active, "cyclic JSON refused")
            active.add(id(item))
            if kind is dict:
                _need(all(type(key) is str for key in item), "ordinary string keys required")
                for child in item.values(): ordinary(child, depth+1)
            else:
                for child in item: ordinary(child, depth+1)
            active.remove(id(item))
    ordinary(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise RolePolicyError("bounded finite UTF8 JSON required") from error
    _need(len(raw) <= MAXIMUM, "role-policy input byte bound exceeded")
    return raw


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _hash(value):
    _need(type(value) is str and _SHA.fullmatch(value) is not None, "lowercase independent SHA256 required")


def _parsed(raw):
    _need(type(raw) is str and 0 < len(raw.encode("utf-8")) <= 262144, "bounded target JSON required")
    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result, "duplicate target field")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(RolePolicyError("nonfinite target JSON")))
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, RolePolicyError): raise
        raise RolePolicyError("ordinary target JSON required") from error
    _need(_wire(value).decode() == raw, "canonical target lexical bytes required")
    return value


def policy(weighting="baseline"):
    """Return one closed scope-conditional policy; no data/model access."""
    _need(type(weighting) is str and weighting in WEIGHTINGS, "closed weighting required")
    weights = {role: {"numerator": 4, "denominator": 1} for role in ROLE_COUNTS}
    if weighting == "semantic_priority":
        weights = {role: {"numerator": 1 if role == "predicate_constructor" else 9,
                          "denominator": 1 if role == "predicate_constructor" else 2} for role in ROLE_COUNTS}
    return dict(schema=POLICY_SCHEMA, weighting=weighting,
        descriptive_name="baseline-choice-four" if weighting == "baseline" else "semantic-structure-priority",
        objective_kind="scope_conditional", normalization="sum_of_complete_position_weights",
        singleton_weight={"numerator": 1, "denominator": 1}, nontrivial_role_weights=weights,
        required_nontrivial_role_counts=dict(ROLE_COUNTS), required_singleton_positions=39,
        required_nontrivial_positions=7, required_supervised_positions=46,
        nontrivial_weight_budget={"numerator": 28, "denominator": 1},
        complete_weight_sum={"numerator": 67, "denominator": 1},
        scope_policy=SCOPE_POLICY, baseline_annotation_schema="legal-compact-content-decisions/v1",
        classification="validated syntax role, lexical constructor and tree path; singleton takes precedence",
        target_exposed=True, upstream_semantics_or_grammar_authority=False)


def policy_sha256(value):
    """Validate an exact closed policy before canonical hashing."""
    _need(type(value) is dict and type(value.get("weighting")) is str, "closed role policy required")
    _need(_wire(value) == _wire(policy(value["weighting"])), "role policy differs from closed definition")
    return _digest(value)


def _annotations(content):
    """Independent narrow lexical/path check, not a general grammar owner."""
    _need(type(content) is dict and set(content) == {"schema", "tree"}
          and content["schema"] == "legal-relational-compact-content/v1", "closed compact content required")
    outer = content["tree"]
    _need(type(outer) is list and len(outer) == 3 and outer[0] in ("forall", "exists")
          and type(outer[1]) is int and outer[1] == 0, "first lexical binder geometry required")
    inner = outer[2]
    _need(type(inner) is list and len(inner) == 3 and inner[0] in ("forall", "exists")
          and type(inner[1]) is int and inner[1] == 1, "second lexical binder geometry required")
    modal = inner[2]
    _need(type(modal) is list and len(modal) == 3 and modal[0] == "extension"
          and type(modal[1]) is str and modal[1] in ("O", "P", "F"), "modal geometry required")
    predicate = modal[2]
    _need(type(predicate) is list and len(predicate) == 3 and predicate[0] == "predicate"
          and type(predicate[1]) is int and predicate[1] == 0 and type(predicate[2]) is list
          and len(predicate[2]) == 2, "one binary predicate geometry required")
    for argument in predicate[2]:
        _need(type(argument) is list and len(argument) == 2 and argument[0] == "variable"
              and type(argument[1]) is int and argument[1] in (0, 1), "bound ordered variable argument required")
    out = []
    def emit(token, role="transport", path=()): out.append(dict(lexical_token=token, role=role, tree_path=list(path)))
    def literal(value, role="transport", path=()): emit(json.dumps(value, ensure_ascii=False, separators=(",", ":")), role, path)
    def tree(node, path):
        kind = node[0]; emit("[", path=path); literal(kind, "constructor", (*path, 0)); emit(",", path=path)
        if kind == "variable": literal(node[1], "variable_reference", (*path, 1))
        elif kind == "predicate":
            literal(node[1], "predicate_reference", (*path, 1)); emit(",", path=path); emit("[", path=(*path, 2))
            for i, child in enumerate(node[2]):
                if i: emit(",", path=(*path, 2))
                tree(child, (*path, 2, i))
            emit("]", path=(*path, 2))
        elif kind in ("forall", "exists"):
            literal(node[1], "binder_declaration", (*path, 1)); emit(",", path=path); tree(node[2], (*path, 2))
        else:
            literal(node[1], "modal_letter", (*path, 1)); emit(",", path=path); tree(node[2], (*path, 2))
        emit("]", path=path)
    emit("{"); literal("schema"); emit(":"); literal(content["schema"]); emit(","); literal("tree"); emit(":")
    tree(outer, ("tree",)); emit("}"); emit("<eos>", "eos")
    _need(len(out) == 46, "closed46-position target required")
    return out


def prepare_inventory(basis_checkpoint, row_index, *, expected_basis_checkpoint_sha256,
                      expected_policy_sha256, policy):
    """Bind offered old annotations and return fixed exact per-position weights.

    This is not an old-checkpoint validator. The enclosing numerical owner must
    recompute the original basis inventory before consuming this result.
    """
    for commitment in (expected_basis_checkpoint_sha256, expected_policy_sha256): _hash(commitment)
    _need(type(row_index) is int and row_index in (0, 1), "closed plain row index required")
    original = _wire(basis_checkpoint)
    _need(hashlib.sha256(original).hexdigest() == expected_basis_checkpoint_sha256, "basis checkpoint commitment differs")
    cp = json.loads(original); policy_raw = _wire(policy); chosen = json.loads(policy_raw)
    _need(policy_sha256(chosen) == expected_policy_sha256, "independent role policy commitment differs")
    try:
        _need(cp["schema"] == "legal-compact-scope-training-checkpoint/v1"
              and cp["objective_policy"]["objective_kind"] == "scope_conditional", "scope-conditional basis required")
        _need(type(cp["rows_utf8"]) is list and len(cp["rows_utf8"]) == 2
              and type(cp["inventories"]) is list and len(cp["inventories"]) == 2
              and type(cp["scope_inventories"]) is list and len(cp["scope_inventories"]) == 2, "closed two-row basis required")
        for field in ("inventories", "scope_inventories", "codec"):
            _need(_digest(cp[field]) == cp[field+"_sha256"], "basis component commitment differs: "+field)
        row, baseline, scoped = (cp[field][row_index] for field in ("rows_utf8", "inventories", "scope_inventories"))
        content = _parsed(row["target_utf8"]); annotations = _annotations(content)
        ids, vocabulary = baseline["target_ids"], cp["codec"]["vocabulary"]
        _need(type(vocabulary) is list and len(vocabulary) == 537 and all(type(x) is str for x in vocabulary)
              and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"]
              and type(ids) is list and len(ids) == 47 and ids[0] == 1 and ids[-1] == 2
              and all(type(i) is int and 0 <= i < 537 for i in ids), "closed fixed537 target vocabulary required")
        _need(baseline["schema"] == "legal-compact-content-decisions/v1"
              and scoped["row_id"] == row["id"] and scoped["baseline_inventory_sha256"] == _digest(baseline)
              and baseline["target_ids_sha256"] == scoped["target_ids_sha256"] == _digest(ids)
              and baseline["codec_sha256"] == scoped["codec_sha256"] == cp["codec_sha256"], "row and inventory identity differs")
        for field, key in (("target_utf8", "content_raw_sha256"), ("context_utf8", "context_raw_sha256")):
            commitment = hashlib.sha256(row[field].encode()).hexdigest()
            _need(baseline[key] == scoped[key] == commitment, "row lexical commitment differs")
        for inv in (baseline, scoped):
            _need(type(inv["authority"]) is dict and inv["authority"] and all(v is False for v in inv["authority"].values())
                  and type(inv["training_mask"]) is type(inv["evaluation_gold_mask"]) is int
                  and inv["training_mask"] == inv["evaluation_gold_mask"] == 0, "offered inventory authority differs")
        _need(len(baseline["positions"]) == len(scoped["positions"]) == 46, "complete position inventory required")
        positions, weights, masks, counts = [], [], [], dict.fromkeys(ROLE_COUNTS, 0)
        total = Fraction(); choice_total = Fraction(); singleton_count = 0
        for index, (annotation, old, scope) in enumerate(zip(annotations, baseline["positions"], scoped["positions"]), 1):
            _need(old["target_position"] == scope["target_position"] == index and type(old["target_position"]) is int
                  and type(scope["target_position"]) is int and old["target_token_id"] == scope["target_token_id"] == ids[index]
                  and type(old["target_token_id"]) is type(scope["target_token_id"]) is int
                  and vocabulary[ids[index]] == annotation["lexical_token"]
                  and all(old[key] == value for key, value in annotation.items())
                  and type(old["tree_path"]) is list and len(old["tree_path"]) == len(annotation["tree_path"])
                  and all(type(a) is type(b) for a,b in zip(old["tree_path"], annotation["tree_path"])),
                  "lexical role/path/token annotation differs")
            before, allowed = old["allowed_token_ids"], scope["allowed_token_ids"]
            for items in (before, allowed):
                _need(type(items) is list and items and all(type(i) is int and 0 <= i < 537 for i in items)
                      and items == sorted(set(items)) and ids[index] in items, "finite unique target-containing allowed set required")
            decision = "forced" if len(before) == 1 else "choice"
            _need(set(allowed) <= set(before) and scope["baseline_allowed_token_ids"] == before
                  and type(old["allowed_count"]) is type(scope["allowed_count"]) is int
                  and old["allowed_count"] == len(before) and scope["allowed_count"] == len(allowed)
                  and old["decision_kind"] == scope["baseline_decision_kind"] == decision
                  and type(scope["baseline_position_weight"]) in (int, float)
                  and scope["baseline_position_weight"] == (1.0 if decision == "forced" else 4.0)
                  and old["prefix_ids_sha256"] == scope["prefix_ids_sha256"] == _digest(ids[:index])
                  and scope["removed_token_ids"] == sorted(set(before)-set(allowed)), "original local inventory decision differs")
            if len(allowed) == 1:
                _need(decision == "forced", "closed profile refuses newly singleton baseline choices")
                role, reason = "singleton", "scope singleton; preserve original unit weight, conditional loss is identically zero"
                rational = Fraction(1); singleton_count += 1
            else:
                role = annotation["role"]
                if role == "constructor":
                    token = json.loads(annotation["lexical_token"])
                    role = {"forall":"quantifier_constructor", "exists":"quantifier_constructor",
                            "extension":"modal_constructor", "predicate":"predicate_constructor"}.get(token)
                _need(role in ROLE_COUNTS, "unsupported nontrivial role")
                counts[role] += 1
                rational = Fraction(**{k: chosen["nontrivial_role_weights"][role][k] for k in ("numerator", "denominator")})
                reason = "baseline choice weight4 retained" if chosen["weighting"] == "baseline" else (
                    "predicate-constructor tradeoff funds six structural choices" if role == "predicate_constructor"
                    else "quantifier, modal or ordered-variable choice receives structural priority")
                choice_total += rational
            total += rational; weight = float(rational); weights.append(weight); masks.append(list(allowed))
            positions.append(dict(target_position=index, role=role, syntax_role=annotation["role"],
                tree_path=list(annotation["tree_path"]), lexical_token=annotation["lexical_token"],
                target_token_id=ids[index], allowed_token_ids=list(allowed), baseline_decision_kind=decision,
                baseline_weight=scope["baseline_position_weight"], weight=weight,
                weight_rational=dict(numerator=rational.numerator, denominator=rational.denominator), reason=reason))
        _need(counts == ROLE_COUNTS and singleton_count == 39 and choice_total == 28 and total == 67
              and scoped["singleton_positions"] == 39 and scoped["nontrivial_positions"] == 7
              and scoped["supervised_positions"] == 46 and scoped["baseline_weight_sum"] == 67,
              "closed role geometry or exact weight budgets differ")
        result = dict(schema=INVENTORY_SCHEMA, weighting=chosen["weighting"], basis_checkpoint_sha256=expected_basis_checkpoint_sha256,
            row_index=row_index, row_id=row["id"], codec_sha256=cp["codec_sha256"],
            context_raw_sha256=baseline["context_raw_sha256"], content_raw_sha256=baseline["content_raw_sha256"],
            baseline_inventory_sha256=_digest(baseline), scope_inventory_sha256=_digest(scoped),
            policy_sha256=expected_policy_sha256, target_ids=list(ids), label_ids=list(ids[1:]),
            positions=positions, position_weights=weights, scope_allowed_token_ids=masks,
            weight_sum=float(total), baseline_weight_sum=67.0, choice_weight_sum=float(choice_total),
            singleton_positions=39, nontrivial_positions=7, nontrivial_role_counts=counts,
            target_exposed=True, upstream_inventory_validation_claimed=False, upstream_grammar_reexecuted=False,
            model_executed=False, training_executed=False, authority=dict(AUTHORITY), training_mask=0, evaluation_gold_mask=0)
        _wire(result)
        _need(_wire(basis_checkpoint) == original and _wire(policy) == policy_raw, "role-policy input changed")
        return result
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError, OverflowError) as error:
        if isinstance(error, RolePolicyError): raise
        raise RolePolicyError("malformed closed role inventory") from error


__all__ = ["RolePolicyError", "policy", "policy_sha256", "prepare_inventory"]
