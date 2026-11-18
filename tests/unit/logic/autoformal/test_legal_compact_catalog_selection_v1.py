"""Authored one-step catalog selection controls; no numerical model or gold.

All signatures, trees and score vectors are fictional controls. Helpers are
self-contained and import no test fixture or historical evidence package.
"""
from copy import deepcopy
import hashlib
import inspect
import json
import math
import re
import sys

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_catalog_selection_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_catalog_tokens_v1 as tokens
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_selection_v1 as old_selection
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as old_tokens


LEXICAL = re.compile(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]')


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(namespace, value):
    return {"interface": "LogicIdentityNamespaces@1", "namespace": namespace,
            "schema_version": "logic-identity-namespaces/v1", "value": value,
            "version": "1.0.0"}


def context():
    obj = {"arguments": [], "kind": "atomic", "name": "Object",
           "schema_version": "syntax-logic-sort/v1"}
    boolean = {"arguments": [], "kind": "bool", "name": "Bool",
               "schema_version": "syntax-logic-sort/v1"}
    symbols = [{"schema_version": "syntax-symbol-declaration/v1", "name": name,
                "kind": "predicate", "metadata": {}, "domain": [deepcopy(obj) for _ in range(arity)],
                "range": deepcopy(boolean)}
               for name, arity in (("Alpha", 1), ("Beta", 1), ("Gamma", 2))]
    catalog = {"schema": "legal-relational-compact-context/v1", "signature": {
        "schema_version": "syntax-logic-signature/v1", "interface": "LogicSignature@1",
        "family": identity("family", "tdfol"), "profile": identity("profile", "tdfol_default"),
        "features": [], "metadata": {}, "sorts": [boolean, obj], "symbols": symbols},
        "argument_roles": [{"symbol": "Gamma", "roles": ["sender", "receiver"]},
                           {"symbol": "Alpha", "roles": ["subject"]},
                           {"symbol": "Beta", "roles": ["observer"]}]}
    return {"schema": "legal-relational-compact-catalog-context/v1",
            "selection_policy": "referenced_predicates_in_catalog_order/v1", "catalog": catalog}


def content():
    return {"schema": "legal-relational-compact-content/v1", "tree": ["forall", 0,
        ["exists", 1, ["and", ["predicate", 2, [["variable", 1], ["variable", 0]]],
                     ["extension", "P", ["predicate", 0, [["variable", 0]]]]]]]}


def ids_for(value, codec, *, eos=True):
    raw = wire(value).decode("utf-8")
    lexical = LEXICAL.findall(raw)
    assert "".join(lexical) == raw
    table = {token: index for index, token in enumerate(codec["vocabulary"])}
    return [1, *(table[token] for token in lexical), *([2] if eos else [])]


@pytest.fixture(scope="module")
def codec():
    return tokens.build_compact_catalog_token_codec_v1()


def codec_sha(codec):
    return tokens.compact_catalog_token_codec_sha256(codec)


def prefix(offered, ctx, codec):
    raw = wire(ctx)
    return tokens.compact_catalog_allowed_token_ids_v1(offered, raw,
        expected_context_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha(codec))


def select(logits, offered, ctx, codec):
    raw = wire(ctx)
    return subject.select_compact_catalog_token_v1(logits, offered, raw,
        expected_context_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha(codec))


def scores(value=-10):
    return [value for _ in range(537)]


def variable_prefix(codec):
    lexical = LEXICAL.findall(wire(content()).decode())
    before_integer = lexical.index('"variable"') + 2
    by_token = {token: index for index, token in enumerate(codec["vocabulary"])}
    return [1, *(by_token[token] for token in lexical[:before_integer])]


def independent_argmax(logits, allowed):
    """Rank explicitly by descending score then ascending numeric token ID."""
    return min(allowed, key=lambda index: (-logits[index], index))


def no_authority(report):
    for item in (report, report["prefix_report"]):
        assert item["authority"] and all(value is False for value in item["authority"].values())
        for key in ("training_mask", "evaluation_gold_mask"):
            assert type(item[key]) is int and item[key] == 0
    assert report["logits_origin_verified"] is False
    assert report["head_compatibility_qualified"] is False
    assert report["prefix_report"]["local_prefix_only"] is True
    assert report["prefix_report"]["global_completability_proven"] is False


def test_api_accepts_no_expected_target_model_checkpoint_or_archival_sidecar():
    assert set(inspect.signature(subject.select_compact_catalog_token_v1).parameters) == {
        "logits", "prefix_ids", "context_raw", "expected_context_sha256", "codec", "expected_codec_sha256"}


def test_every_authored_valid_prefix_uses_full_scores_and_actual_public_mask(codec):
    ctx, target = context(), ids_for(content(), codec)
    for position, desired in enumerate(target):
        offered = target[:position]
        logits = scores()
        logits[0], logits[desired] = 100, 99.0
        before = deepcopy((logits, offered, codec))
        report = select(logits, offered, ctx, codec)
        upstream = prefix(offered, ctx, codec)
        assert report["prefix_report"] == upstream
        assert report["prefix_report_sha256"] == sha(wire(upstream))
        assert report["status"] == "selected" and report["reason"] is None
        assert report["selected_token_id"] == independent_argmax(logits, upstream["allowed_token_ids"]) == desired
        assert report["raw_argmax_token_id"] == independent_argmax(logits, range(537)) == 0
        assert report["raw_argmax_score"] == 100 and report["selected_score"] == 99.0
        assert type(report["selected_score"]) is float
        assert report["selection_overrode_raw_argmax"] is True
        assert report["selection_performed"] is True and report["tokens_appended"] == 1
        assert report["offered_prefix_ids"] == offered and report["next_prefix_ids"] == offered + [desired]
        assert report["logits"] == logits and len(report["logits"]) == 537
        assert report["logits_sha256"] == sha(wire(logits))
        assert (logits, offered, codec) == before
        no_authority(report)


@pytest.mark.parametrize("mode", ["allowed_maximum", "two_allowed_ties", "all_equal", "negative_scores"])
def test_independent_constrained_argmax_and_lowest_id_ties(mode, codec):
    offered, ctx = variable_prefix(codec), context()
    allowed = prefix(offered, ctx, codec)["allowed_token_ids"]
    assert allowed == sorted([codec["vocabulary"].index("0"), codec["vocabulary"].index("1")])
    logits = scores(-100)
    if mode == "allowed_maximum": logits[allowed[-1]] = 200
    elif mode == "two_allowed_ties":
        logits[0] = 300
        for index in allowed: logits[index] = 200
    elif mode == "all_equal": logits = scores(0)
    else:
        logits[0] = -1
        logits[allowed[0]], logits[allowed[-1]] = -4, -2
    report = select(logits, offered, ctx, codec)
    raw = independent_argmax(logits, range(537))
    chosen = independent_argmax(logits, allowed)
    assert report["raw_argmax_token_id"] == raw
    assert report["selected_token_id"] == chosen
    assert report["selected_score"] == logits[chosen]
    assert report["tie_breaker"] == "lowest_token_id"
    assert report["selection_overrode_raw_argmax"] is (raw != chosen)
    assert report["next_prefix_ids"] == offered + [chosen]
    no_authority(report)


def test_subset_eos_is_explicit_scored_step_while_old_profile_still_refuses(codec, tmp_path, record_property):
    ctx, target = context(), ids_for(content(), codec)
    offered = target[:-1]
    logits = scores()
    logits[0], logits[2] = 100, 90
    result = select(logits, offered, ctx, codec)
    assert result["prefix_report"]["allowed_token_ids"] == [2]
    assert result["selected_token_id"] == 2 and result["next_prefix_ids"] == target
    assert result["tokens_appended"] == 1
    raw = wire(ctx)
    candidate = tokens.decode_compact_catalog_tokens_v1(result["next_prefix_ids"], raw,
        expected_context_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha(codec))
    assert candidate["status"] == "valid_candidate"
    assert candidate["selection"]["selected_catalog_indices"] == [0, 2]
    assert candidate["selection"]["unused_catalog_indices"] == [1]
    prior = old_tokens.build_compact_content_token_codec_v1()
    old_raw = wire(ctx["catalog"])
    old_result = old_selection.select_compact_content_token_v1(logits, offered, old_raw,
        expected_context_sha256=sha(old_raw), codec=prior,
        expected_codec_sha256=old_tokens.compact_content_token_codec_sha256(prior))
    assert old_result["status"] == "no_selection" and old_result["prefix_status"] == "rejected"
    assert old_result["next_prefix_ids"] == offered and old_result["tokens_appended"] == 0
    payloads = {"context.json": raw, "codec.json": wire(codec), "content.json": wire(content()),
        "scores.json": wire(logits), "prefix.json": wire(offered), "selection.json": wire(result),
        "candidate.json": wire(candidate), "old-selection.json": wire(old_result)}
    for name, data in payloads.items(): (tmp_path / name).write_bytes(data)
    manifest = {"schema": "authored-catalog-selection-fixture/v1", "fixture_origin": "authored_fictional",
        "model_executed": False, "human_review_verified": False, "permitted_inference_context_verified": False,
        "files": [{"name": name, "sha256": sha(data), "bytes": len(data)} for name, data in payloads.items()]}
    path = tmp_path / "manifest.json"
    path.write_bytes(wire(manifest))
    record_property("catalog_selection_fixture_manifest", str(path))
    no_authority(result)


def unfinishable_limit_prefix(codec):
    rows = [["predicate", 0, [["variable", 0]]] for _ in range(27)]
    while len(rows) > 1:
        grouped = [["and", rows[i], rows[i + 1]] for i in range(0, len(rows) - 1, 2)]
        if len(rows) % 2: grouped.append(rows[-1])
        rows = grouped
    value = {"schema": tokens.CONTENT_SCHEMA,
        "tree": ["forall", 0, ["exists", 1, ["not", ["not", ["not", rows[0]]]]]]}
    ids = ids_for(value, codec, eos=False)
    assert len(ids) == 514
    return ids[:512]


@pytest.mark.parametrize("case", ["complete", "unknown", "pad", "bad_arity", "budget_exhausted"])
def test_terminal_prefixes_keep_all_scores_and_ids_with_null_selection(case, codec):
    ctx = context()
    if case == "complete": offered = ids_for(content(), codec)
    elif case == "unknown": offered = [1, -1]
    elif case == "pad": offered = [1, 0]
    elif case == "budget_exhausted": offered = unfinishable_limit_prefix(codec)
    else:
        value = content()
        value["tree"][2][2][1][2].pop()
        offered = ids_for(value, codec)
    upstream = prefix(offered, ctx, codec)
    expected = "complete" if case == "complete" else "budget_exhausted" if case == "budget_exhausted" else "rejected"
    assert upstream["status"] == expected and upstream["allowed_token_ids"] == []
    logits = scores()
    logits[2] = 100
    result = select(logits, offered, ctx, codec)
    assert result["status"] == "no_selection" and result["prefix_status"] == expected
    assert result["reason"] == (upstream["reason"] or upstream["status"])
    assert result["prefix_report"] == upstream
    assert result["selected_token_id"] is None and result["selected_score"] is None
    assert result["next_prefix_ids"] == result["offered_prefix_ids"] == offered
    assert result["tokens_appended"] == 0
    assert result["selection_performed"] is result["selection_overrode_raw_argmax"] is False
    assert result["raw_argmax_token_id"] == 2 and result["raw_argmax_score"] == 100
    assert result["logits"] == logits and result["logits_sha256"] == sha(wire(logits))
    no_authority(result)


def test_every_one_of_537_scores_is_checked_before_prefix_owner_even_when_masked(codec, monkeypatch):
    def forbidden(*args): raise AssertionError("prefix operation loaded before invalid full-score refusal")
    monkeypatch.setattr(subject, "_owners", forbidden)
    for index in range(537):
        logits = scores()
        logits[index] = float("nan")
        with pytest.raises(ValueError): select(logits, [1], context(), codec)


class ScalarFloat(float): pass
class ScalarInt(int): pass
class VectorList(list): pass
class ConversionTrap:
    def __len__(self): raise AssertionError("no length coercion")
    def __float__(self): raise AssertionError("no numeric coercion")
    def __array__(self, *args, **kwargs): raise AssertionError("no tensor conversion")
    def tolist(self): raise AssertionError("no list conversion")


@pytest.mark.parametrize("kind", ["none", "tuple", "short", "long", "subclass", "conversion"])
def test_score_vector_requires_exact_plain_complete_list(kind, codec):
    value = {"none": None, "tuple": tuple(scores()), "short": scores()[:-1], "long": scores() + [0],
             "subclass": VectorList(scores()), "conversion": ConversionTrap()}[kind]
    with pytest.raises(ValueError): select(value, [1], context(), codec)


@pytest.mark.parametrize("kind", ["bool", "nan", "inf", "negative_inf", "unsafe_integer", "unsafe_negative", "huge_integer", "text", "none", "float_subclass", "int_subclass", "conversion"])
def test_invalid_last_score_is_refused_even_when_prefix_is_already_complete(kind, codec):
    invalid = {"bool": True, "nan": float("nan"), "inf": float("inf"), "negative_inf": -float("inf"),
        "unsafe_integer": 1 << 53, "unsafe_negative": -(1 << 53), "huge_integer": 1 << 200,
        "text": "1", "none": None, "float_subclass": ScalarFloat(1), "int_subclass": ScalarInt(1),
        "conversion": ConversionTrap()}[kind]
    logits = scores()
    logits[-1] = invalid
    with pytest.raises(ValueError): select(logits, ids_for(content(), codec), context(), codec)


@pytest.mark.parametrize("value", [sys.float_info.max, -sys.float_info.max, (1 << 53) - 1, -((1 << 53) - 1)])
def test_finite_extremes_and_safe_integer_edges_keep_exact_types(value, codec):
    logits = scores()
    logits[0] = value
    result = select(logits, [1], context(), codec)
    assert result["logits"][0] == value and type(result["logits"][0]) is type(value)
    assert result["logits_sha256"] == sha(wire(logits))
    no_authority(result)


def test_mixed_int_float_and_negative_zero_survive_commitment_and_tie_selection(codec):
    offered, ctx = [1], context()
    desired = prefix(offered, ctx, codec)["allowed_token_ids"][0]
    logits = scores(-3)
    logits[0], logits[desired], logits[5] = -0.0, -0.0, 0.0
    result = select(logits, offered, ctx, codec)
    assert result["raw_argmax_token_id"] == 0 and result["selected_token_id"] == desired
    assert all(type(a) is type(b) for a, b in zip(logits, result["logits"]))
    assert math.copysign(1.0, result["raw_argmax_score"]) == -1.0
    assert math.copysign(1.0, result["selected_score"]) == -1.0
    assert math.copysign(1.0, result["logits"][5]) == 1.0
    changed = list(logits)
    changed[0] = 0.0
    assert result["logits_sha256"] == sha(wire(logits)) != sha(wire(changed))


@pytest.mark.parametrize("offered", [None, (), [True], [1.0], [1 << 63], [1] * 513])
def test_prefix_shape_or_overflow_is_atomic_operation_failure(offered, codec):
    with pytest.raises(ValueError): select(scores(), offered, context(), codec)


@pytest.mark.parametrize("damage", ["context_pin", "codec_pin", "old_codec", "old_context", "catalog_schema", "catalog_policy", "unused_roles", "extra_authority"])
def test_context_and_codec_errors_cannot_be_hidden_as_no_selection(damage, codec):
    ctx, fixed = context(), deepcopy(codec)
    if damage == "old_codec": fixed = old_tokens.build_compact_content_token_codec_v1()
    elif damage == "old_context": ctx = ctx["catalog"]
    elif damage == "catalog_schema": ctx["schema"] += "-changed"
    elif damage == "catalog_policy": ctx["selection_policy"] = "occurrence_order/v1"
    elif damage == "unused_roles": ctx["catalog"]["argument_roles"][2]["roles"] = []
    elif damage == "extra_authority": ctx["permission"] = True
    raw = wire(ctx)
    expected_context = "0" * 64 if damage == "context_pin" else sha(raw)
    expected_codec = "0" * 64 if damage == "codec_pin" else sha(wire(fixed))
    with pytest.raises(ValueError):
        subject.select_compact_catalog_token_v1(scores(), [1, -1], raw,
            expected_context_sha256=expected_context, codec=fixed, expected_codec_sha256=expected_codec)


@pytest.mark.parametrize("mutation", ["unused_name", "unused_role", "role_ledger_order"])
def test_full_catalog_changes_remain_visible_when_selection_is_unchanged(mutation, codec):
    ctx = context()
    offered, logits = [1], scores()
    original = select(logits, offered, ctx, codec)
    if mutation == "unused_name":
        ctx["catalog"]["signature"]["symbols"][1]["name"] = "UnusedAlternative"
        ctx["catalog"]["argument_roles"][2]["symbol"] = "UnusedAlternative"
    elif mutation == "unused_role": ctx["catalog"]["argument_roles"][2]["roles"] = ["witness"]
    else: ctx["catalog"]["argument_roles"].reverse()
    result = select(logits, offered, ctx, codec)
    assert result["selected_token_id"] == original["selected_token_id"]
    assert result["prefix_report"]["catalog_context"] == ctx
    assert result["context_sha256"] == sha(wire(ctx)) != original["context_sha256"]
    assert result["catalog_sha256"] == sha(wire(ctx["catalog"])) != original["catalog_sha256"]
    assert result["prefix_report_sha256"] != original["prefix_report_sha256"]
    no_authority(result)


def test_raw_whitespace_commitment_is_not_replaced_by_canonical_context_identity(codec):
    ctx = context()
    raw = json.dumps(ctx, indent=2).encode()
    result = subject.select_compact_catalog_token_v1(scores(), [1], raw,
        expected_context_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha(codec))
    assert result["context_raw_sha256"] == sha(raw) != sha(wire(ctx))
    assert result["context_sha256"] == sha(wire(ctx))
    assert result["prefix_report"]["context_raw_sha256"] == sha(raw)
    no_authority(result)


def test_reports_detach_full_catalog_prefix_scores_and_authority_from_inputs(codec):
    logits, offered, ctx, fixed = scores(), [1], context(), deepcopy(codec)
    before = deepcopy((logits, offered, ctx, fixed))
    result = select(logits, offered, ctx, fixed)
    saved = deepcopy(result)
    result["logits"][0] = 999
    result["next_prefix_ids"].append(0)
    result["prefix_report"]["allowed_token_ids"].clear()
    result["prefix_report"]["catalog_context"]["catalog"]["signature"]["symbols"].clear()
    result["authority"]["accepted"] = True
    assert (logits, offered, ctx, fixed) == before
    assert select(logits, offered, ctx, fixed) == saved


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError, KeyboardInterrupt])
def test_selector_owner_error_or_cancellation_preserves_first_exception(error_type, codec, monkeypatch):
    failure = error_type("authored selector operation failure")
    def unavailable(*args): raise failure
    monkeypatch.setattr(subject, "_owners", unavailable)
    with pytest.raises(error_type) as caught: select(scores(), [1], context(), codec)
    assert caught.value is failure


@pytest.mark.parametrize("changed", ["logits", "prefix", "codec", "source"])
def test_final_serialization_is_followed_by_input_and_source_custody_checks(changed, codec, monkeypatch):
    logits, offered, fixed = scores(), [1], deepcopy(codec)
    detach, seen = old_selection._detach, []
    def changing_detach(value, maximum):
        result = detach(value, maximum)
        if type(value) is dict and value.get("schema") == "legal-compact-catalog-token-selection/v1":
            seen.append(True)
            if changed == "logits": logits[0] = 100
            elif changed == "prefix": offered.append(0)
            elif changed == "codec": fixed["max_sequence_tokens"] = 511
            else: monkeypatch.setattr(subject, "_SELF_SNAPSHOT", ("0" * 64, subject._SELF_SNAPSHOT[1]))
        return result
    # Instrument only the final NEW-selector serialization, leaving the public
    # grammar and real source reads unchanged. No source file is modified.
    monkeypatch.setattr(old_selection, "_detach", changing_detach)
    with pytest.raises(ValueError): select(logits, offered, context(), fixed)
    assert len(seen) == 1


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_first_operation_exception_survives_secondary_closing_source_failure(error_type, codec, monkeypatch):
    failure = error_type("authored primary failure")
    def unavailable(*args):
        monkeypatch.setattr(subject, "_SELF_SNAPSHOT", ("0" * 64, subject._SELF_SNAPSHOT[1]))
        raise failure
    monkeypatch.setattr(subject, "_owners", unavailable)
    with pytest.raises(error_type) as caught: select(scores(), [1], context(), codec)
    assert caught.value is failure
    assert any("closing" in note.lower() for note in getattr(failure, "__notes__", []))


def test_oversize_context_refuses_whole_input_even_for_rejected_prefix(codec):
    raw = wire(context())
    raw += b" " * (subject.MAX_CONTEXT_BYTES + 1 - len(raw))
    with pytest.raises(ValueError):
        subject.select_compact_catalog_token_v1(scores(), [1, -1], raw,
            expected_context_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha(codec))


@pytest.mark.parametrize("damage", ["raw_hash", "canonical_hash", "catalog_hash", "catalog_payload",
    "offered_bool", "allowed_bool", "missing_pin", "duplicate_pin", "authority", "empty_authority",
    "mask_bool", "remaining_bool", "wrong_remaining", "count_bool", "status_contradiction", "extra"])
def test_actual_public_prefix_return_tampering_is_refused_before_selection(damage, codec, monkeypatch):
    original = tokens.compact_catalog_allowed_token_ids_v1
    observed = []
    offered = [1] if damage == "offered_bool" else []
    def changed_prefix(*args, **kwargs):
        report = original(*args, **kwargs)
        observed.append(deepcopy(report))
        if damage == "raw_hash": report["context_raw_sha256"] = "0" * 64
        elif damage == "canonical_hash": report["context_sha256"] = "0" * 64
        elif damage == "catalog_hash": report["catalog_sha256"] = "0" * 64
        elif damage == "catalog_payload": report["catalog_context"]["catalog"]["argument_roles"][2]["roles"] = ["changed"]
        elif damage == "offered_bool": report["offered_ids"] = [True]
        elif damage == "allowed_bool": report["allowed_token_ids"] = [True]
        elif damage == "missing_pin": report["owner_pins"].pop()
        elif damage == "duplicate_pin": report["owner_pins"][-1] = deepcopy(report["owner_pins"][0])
        elif damage == "authority": report["authority"]["accepted"] = True
        elif damage == "empty_authority": report["authority"] = {}
        elif damage == "mask_bool": report["training_mask"] = False
        elif damage == "remaining_bool": report["remaining_token_slots"] = True
        elif damage == "wrong_remaining": report["remaining_token_slots"] -= 1
        elif damage == "count_bool": report["counts"]["nodes"] = False
        elif damage == "status_contradiction": report["status"] = "complete"
        else: report["permitted_target"] = True
        return report
    # Real grammar runs first. Only the returned association/authority evidence
    # is corrupted at this explicit trust-boundary seam; no invented mask.
    monkeypatch.setattr(tokens, "compact_catalog_allowed_token_ids_v1", changed_prefix)
    with pytest.raises(ValueError): select(scores(), offered, context(), codec)
    assert len(observed) == 1
    assert observed[0]["offered_ids"] == offered
