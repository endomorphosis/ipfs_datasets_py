"""Independent authored catalog-selection controls, not statutory gold.

The Alpha/Beta/Gamma vocabulary is fictional. No source, review, checkpoint,
model or permission is supplied. Tests run only in the existing admitted owner.
"""
from copy import deepcopy
import hashlib
import json
import re

import pytest

from ipfs_datasets_py.logic.autoformal import legal_compact_content_v1 as content_owner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_catalog_tokens_v1 as subject
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


def sort(name, kind):
    return {"arguments": [], "kind": kind, "name": name,
            "schema_version": "syntax-logic-sort/v1"}


def catalog():
    """Explicit fictional context; role-ledger order deliberately differs."""
    obj, boolean = sort("Object", "atomic"), sort("Bool", "bool")
    symbols = [{"schema_version": "syntax-symbol-declaration/v1",
                "name": name, "kind": "predicate", "metadata": {},
                "domain": [deepcopy(obj) for _ in range(arity)],
                "range": deepcopy(boolean)}
               for name, arity in (("Alpha", 1), ("Beta", 1), ("Gamma", 2))]
    return {"schema": "legal-relational-compact-context/v1", "signature": {
        "schema_version": "syntax-logic-signature/v1", "interface": "LogicSignature@1",
        "family": identity("family", "tdfol"), "profile": identity("profile", "tdfol_default"),
        "features": [], "metadata": {}, "sorts": [boolean, obj], "symbols": symbols},
        "argument_roles": [{"symbol": "Gamma", "roles": ["sender", "receiver"]},
                           {"symbol": "Alpha", "roles": ["subject"]},
                           {"symbol": "Beta", "roles": ["observer"]}]}


def context():
    return {"schema": "legal-relational-compact-catalog-context/v1",
            "selection_policy": "referenced_predicates_in_catalog_order/v1", "catalog": catalog()}


def content(mode="mixed"):
    alpha = ["predicate", 0, [["variable", 0]]]
    gamma = ["predicate", 2, [["variable", 1], ["variable", 0]]]
    if mode == "single":
        tree = ["forall", 0, alpha]
    else:
        body = ["and", gamma, ["extension", "P", alpha]]
        if mode == "all":
            body = ["implies", ["predicate", 1, [["variable", 0]]], body]
        tree = ["forall", 0, ["exists", 1, body]]
    return {"schema": "legal-relational-compact-content/v1", "tree": tree}


def nodes(value):
    """Independent tree walk, preserving ordered children and modal scope."""
    result = []
    def visit(node):
        result.append(node)
        if node[0] == "predicate":
            for child in node[2]: visit(child)
        elif node[0] in {"forall", "exists", "extension"}: visit(node[2])
        elif node[0] in {"and", "or", "implies", "iff"}:
            visit(node[1]); visit(node[2])
        elif node[0] == "not": visit(node[1])
    visit(value["tree"])
    return result


def ids_for(value, codec, *, eos=True):
    raw = wire(value).decode("utf-8")
    lexical = LEXICAL.findall(raw)
    assert "".join(lexical) == raw
    table = {token: index for index, token in enumerate(codec["vocabulary"])}
    return [codec["bos_id"], *(table[token] for token in lexical),
            *([codec["eos_id"]] if eos else [])]


@pytest.fixture(scope="module")
def codec():
    return subject.build_compact_catalog_token_codec_v1()


def codec_sha(codec):
    return subject.compact_catalog_token_codec_sha256(codec)


def encode(value, ctx, codec):
    c, x = wire(value), wire(ctx)
    return subject.encode_compact_catalog_tokens_v1(c, x,
        expected_content_sha256=sha(c), expected_context_sha256=sha(x),
        codec=codec, expected_codec_sha256=codec_sha(codec))


def decode(ids, ctx, codec):
    raw = wire(ctx)
    return subject.decode_compact_catalog_tokens_v1(ids, raw,
        expected_context_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha(codec))


def prefix(ids, ctx, codec):
    raw = wire(ctx)
    return subject.compact_catalog_allowed_token_ids_v1(ids, raw,
        expected_context_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha(codec))


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    for key in ("training_mask", "evaluation_gold_mask"):
        assert type(report[key]) is int and report[key] == 0
    selection = report.get("selection")
    if selection is not None:
        prediction = selection["prediction"]
        assert prediction["identity_mode"] == "generated"
        assert prediction["request"]["source_binding"] is None
        assert all(value is False for value in prediction["authority"].values())
        assert prediction["training_mask"] == prediction["evaluation_gold_mask"] == 0


def invoke(operation, codec):
    if operation == "encode": return encode(content(), context(), codec)
    if operation == "prefix": return prefix([], context(), codec)
    return decode(ids_for(content(), codec), context(), codec)


def test_context_preparation_is_exact_old_public_validation_without_target_or_identity():
    cat = catalog()
    signature = {**cat["signature"], "signature_id": "authored-fictional-signature"}
    s, r = wire(signature), wire(cat["argument_roles"])
    pins = {"expected_signature_sha256": sha(s), "expected_argument_roles_sha256": sha(r)}
    result = subject.prepare_catalog_context_v1(s, r, **pins)
    assert result == context()
    assert result["catalog"] == content_owner.prepare_context_v1(s, r, **pins)
    assert set(result) == {"schema", "selection_policy", "catalog"}
    assert "signature_id" not in result["catalog"]["signature"]
    with pytest.raises(TypeError):
        subject.prepare_catalog_context_v1(s, r, content_raw=wire(content()), **pins)


def test_codec_reuses_only_lexical_spellings_with_distinct_profile_and_commitment(codec):
    old = old_tokens.build_compact_content_token_codec_v1()
    assert codec["vocabulary"] == old["vocabulary"]
    assert codec["vocabulary_size"] == 537 and codec["max_sequence_tokens"] == 512
    assert (codec["pad_id"], codec["bos_id"], codec["eos_id"]) == (0, 1, 2)
    assert codec["schema"] != old["schema"] and codec["profile"] != old["profile"]
    assert codec_sha(codec) != old_tokens.compact_content_token_codec_sha256(old)
    assert codec["numerical_head_compatible"] is False
    assert codec["permitted_inference_context_verified"] is False
    with pytest.raises(ValueError): subject.compact_catalog_token_codec_sha256(old)
    with pytest.raises(ValueError): old_tokens.compact_content_token_codec_sha256(codec)


@pytest.mark.parametrize("mode", ["single", "mixed", "all"])
def test_new_optional_selection_and_old_all_predicates_contract_are_both_preserved(mode, codec):
    value, ctx = content(mode), context()
    ids = ids_for(value, codec)
    result = decode(ids, ctx, codec)
    assert result["status"] == "valid_candidate" and result["generated_ids"] == ids
    assert result["selection"]["catalog_content"] == value
    old = old_tokens.build_compact_content_token_codec_v1()
    raw = wire(ctx["catalog"])
    prior = old_tokens.decode_compact_content_tokens_v1(ids, raw,
        expected_context_sha256=sha(raw), codec=old,
        expected_codec_sha256=old_tokens.compact_content_token_codec_sha256(old))
    assert prior["status"] == ("valid_candidate" if mode == "all" else "rejected")
    if mode != "all":
        assert prior["prediction"] is None
        with pytest.raises(ValueError):
            content_owner.decode_prediction_v1(wire(value), raw,
                expected_content_sha256=sha(wire(value)), expected_context_sha256=sha(raw))
    no_authority(result)


@pytest.mark.parametrize("mode", ["single", "mixed"])
def test_every_actual_prefix_including_subset_eos_is_admitted_without_completion_claim(mode, codec):
    value, ctx = content(mode), context()
    ids = ids_for(value, codec)
    encoded = encode(value, ctx, codec)
    assert encoded["target_ids"] == ids
    for length in range(len(ids) + 1):
        report = prefix(ids[:length], ctx, codec)
        assert report["offered_ids"] == ids[:length]
        assert report["local_prefix_only"] is True
        assert report["global_completability_proven"] is False
        assert report["remaining_token_slots"] == 512 - length
        if length < len(ids):
            assert report["status"] == ("empty" if length == 0 else "prefix")
            assert ids[length] in report["allowed_token_ids"]
        else:
            assert report["status"] == "complete" and report["allowed_token_ids"] == []
        no_authority(report)
    assert prefix(ids[:-1], ctx, codec)["allowed_token_ids"] == [codec["eos_id"]]
    assert decode(ids[:-1], ctx, codec)["status"] == "incomplete"


def test_original_catalog_order_roles_and_inverse_projection_survive_full_public_owner(codec, tmp_path, record_property):
    value, ctx = content(), context()
    before = deepcopy((value, ctx, codec))
    encoded = encode(value, ctx, codec)
    result = decode(encoded["target_ids"], ctx, codec)
    selection = result["selection"]
    assert selection == encoded["selection"]
    assert selection["selected_catalog_indices"] == [0, 2]
    assert selection["unused_catalog_indices"] == [1]
    assert selection["catalog_to_effective"] == [0, None, 1]
    assert selection["selected_role_row_indices"] == [1, 0]
    effective = selection["effective_context"]
    assert [row["name"] for row in effective["signature"]["symbols"]] == ["Alpha", "Gamma"]
    assert effective["argument_roles"] == [ctx["catalog"]["argument_roles"][1],
                                          ctx["catalog"]["argument_roles"][0]]
    inverse = deepcopy(selection["effective_content"])
    for node in nodes(inverse):
        if node[0] == "predicate": node[1] = selection["selected_catalog_indices"][node[1]]
    assert inverse == value
    assert [node[1] for node in nodes(selection["effective_content"]) if node[0] == "predicate"] == [1, 0]
    request_raw = wire(selection["prediction"]["request"])
    projection = content_owner.project_request_v1(request_raw, expected_request_sha256=sha(request_raw))
    assert projection["content"] == selection["effective_content"]
    assert projection["context"] == effective
    for key in ("catalog_content", "effective_content", "effective_context", "prediction"):
        assert selection[key + "_sha256"] == sha(wire(selection[key]))
    assert result["catalog_context"] == ctx and result["catalog_sha256"] == sha(wire(ctx["catalog"]))
    identity_payload = {"schema": "legal-compact-catalog-prediction-identity/v1",
        "selection_policy": ctx["selection_policy"], "codec_sha256": codec_sha(codec),
        "context_sha256": sha(wire(ctx)), "content_sha256": sha(wire(value))}
    assert selection["catalog_prediction_id"] == "compact-catalog-prediction-v1:" + sha(wire(identity_payload))
    assert (value, ctx, codec) == before
    no_authority(result)
    payloads = {"content.json": wire(value), "context.json": wire(ctx), "codec.json": wire(codec),
                "encoding.json": wire(encoded), "prefix.json": wire(prefix(encoded["target_ids"][:-1], ctx, codec)),
                "candidate.json": wire(result)}
    for filename, raw in payloads.items(): (tmp_path / filename).write_bytes(raw)
    manifest = {"schema": "authored-optional-catalog-fixture/v1", "fixture_origin": "authored_fictional",
        "human_review_verified": False, "model_executed": False, "permitted_inference_context_verified": False,
        "files": [{"name": filename, "sha256": sha(raw), "bytes": len(raw)} for filename, raw in payloads.items()]}
    (tmp_path / "manifest.json").write_bytes(wire(manifest))
    record_property("optional_catalog_fixture_manifest", str(tmp_path / "manifest.json"))


@pytest.mark.parametrize("mutation", ["unused_name", "unused_roles", "catalog_order", "role_order"])
def test_unused_entries_and_both_orders_remain_committed_even_when_effective_tree_matches(mutation, codec):
    value, ctx = content(), context()
    original = decode(ids_for(value, codec), ctx, codec)
    changed = deepcopy(ctx)
    if mutation == "unused_name":
        changed["catalog"]["signature"]["symbols"][1]["name"] = "UnusedAlternative"
        changed["catalog"]["argument_roles"][2]["symbol"] = "UnusedAlternative"
    elif mutation == "unused_roles": changed["catalog"]["argument_roles"][2]["roles"] = ["witness"]
    elif mutation == "catalog_order":
        symbols = changed["catalog"]["signature"]["symbols"]
        symbols[0], symbols[1] = symbols[1], symbols[0]
        for node in nodes(value):
            if node[0] == "predicate" and node[1] == 0: node[1] = 1
    else: changed["catalog"]["argument_roles"].reverse()
    result = decode(ids_for(value, codec), changed, codec)
    assert result["status"] == "valid_candidate"
    assert result["context_sha256"] != original["context_sha256"]
    assert result["selection"]["catalog_prediction_id"] != original["selection"]["catalog_prediction_id"]
    assert result["selection"]["effective_context"] == original["selection"]["effective_context"]
    assert result["selection"]["effective_content"] == original["selection"]["effective_content"]
    with pytest.raises(ValueError):
        subject.decode_compact_catalog_tokens_v1(ids_for(value, codec), wire(changed),
            expected_context_sha256=sha(wire(ctx)), codec=codec, expected_codec_sha256=codec_sha(codec))


@pytest.mark.parametrize("mutation", ["argument_order", "modal_letter", "modal_scope", "quantifier", "ordered_roles"])
def test_valid_semantic_changes_are_preserved_and_never_repaired_to_original(mutation, codec):
    value, ctx = content(), context()
    original = decode(ids_for(value, codec), ctx, codec)
    if mutation == "argument_order": next(row for row in nodes(value) if row[0] == "predicate")[2].reverse()
    elif mutation == "modal_letter": next(row for row in nodes(value) if row[0] == "extension")[1] = "F"
    elif mutation == "modal_scope":
        body = value["tree"][2][2]
        body[2] = body[2][2]
        value["tree"][2][2] = ["extension", "P", body]
    elif mutation == "quantifier": value["tree"][2][0] = "forall"
    else: ctx["catalog"]["argument_roles"][0]["roles"].reverse()
    result = decode(ids_for(value, codec), ctx, codec)
    assert result["status"] == "valid_candidate"
    assert result["selection"]["catalog_content"] == value
    assert result["selection"]["catalog_prediction_id"] != original["selection"]["catalog_prediction_id"]
    assert result["selection"]["prediction"]["request"] != original["selection"]["prediction"]["request"]
    no_authority(result)


@pytest.mark.parametrize("damage", ["unknown_predicate", "arity", "free", "reused_binder", "nonpreorder", "sibling_capture", "bad_modal", "formula_argument", "zero_quantifiers"])
def test_invalid_candidate_grammar_is_retained_without_subset_repair(damage, codec):
    value = content()
    tree = nodes(value)
    if damage == "unknown_predicate": next(row for row in tree if row[0] == "predicate")[1] = 511
    elif damage == "arity": next(row for row in tree if row[0] == "predicate")[2].pop()
    elif damage == "free": next(row for row in tree if row[0] == "variable")[1] = 511
    elif damage == "reused_binder": value["tree"][2][1] = 0
    elif damage == "nonpreorder": value["tree"][1] = 1
    elif damage == "sibling_capture":
        value["tree"] = ["and", ["forall", 0, ["predicate", 0, [["variable", 0]]]],
            ["exists", 1, ["predicate", 2, [["variable", 1], ["variable", 0]]]]]
    elif damage == "bad_modal": next(row for row in tree if row[0] == "extension")[1] = "and"
    elif damage == "formula_argument": next(row for row in tree if row[0] == "predicate")[2][0] = ["not", ["variable", 0]]
    else: value["tree"] = ["predicate", 0, [["variable", 0]]]
    ids = ids_for(value, codec)
    report = decode(ids, context(), codec)
    assert report["status"] == "rejected" and report["selection"] is None
    assert report["generated_ids"] == ids and report["counts"] is None
    assert prefix(ids, context(), codec)["status"] == "rejected"
    with pytest.raises(ValueError): encode(value, context(), codec)
    no_authority(report)


@pytest.mark.parametrize("damage", ["unused_arity", "unused_sort", "unused_roles", "duplicate_symbol", "duplicate_roles", "empty", "too_many", "old_context", "policy", "extra"])
def test_entire_catalog_is_validated_even_when_only_first_predicate_is_used(damage, codec):
    ctx = context()
    cat = ctx["catalog"]
    if damage == "unused_arity": cat["signature"]["symbols"][1]["domain"] *= 9
    elif damage == "unused_sort": cat["signature"]["symbols"][1]["domain"][0] = sort("Bool", "bool")
    elif damage == "unused_roles": cat["argument_roles"][2]["roles"] = []
    elif damage == "duplicate_symbol": cat["signature"]["symbols"][1]["name"] = "Alpha"
    elif damage == "duplicate_roles": cat["argument_roles"][2] = deepcopy(cat["argument_roles"][1])
    elif damage == "empty": cat["signature"]["symbols"] = []; cat["argument_roles"] = []
    elif damage == "too_many":
        base = deepcopy(cat["signature"]["symbols"][0])
        cat["signature"]["symbols"] = [{**deepcopy(base), "name": "P" + str(i)} for i in range(65)]
        cat["argument_roles"] = [{"symbol": "P" + str(i), "roles": ["subject"]} for i in range(65)]
    elif damage == "old_context": ctx = cat
    elif damage == "policy": ctx["selection_policy"] = "first_occurrence_order/v1"
    else: ctx["source_binding"] = {"permitted": True}
    for ids in ([], [-1], ids_for(content("single"), codec)):
        with pytest.raises(ValueError): decode(ids, ctx, codec)


@pytest.mark.parametrize("damage,status", [("empty", "incomplete"), ("missing_eos", "incomplete"),
    ("missing_bos", "rejected"), ("pad", "rejected"), ("interior_bos", "rejected"),
    ("interior_eos", "rejected"), ("post_eos", "rejected"), ("unknown", "rejected")])
def test_every_framing_failure_keeps_raw_ids_and_null_selection(damage, status, codec):
    ids = ids_for(content("single"), codec)
    if damage == "empty": ids = []
    elif damage == "missing_eos": ids.pop()
    elif damage == "missing_bos": ids.pop(0)
    elif damage == "pad": ids.insert(10, 0)
    elif damage == "interior_bos": ids.insert(10, 1)
    elif damage == "interior_eos": ids.insert(10, 2)
    elif damage == "post_eos": ids.append(3)
    else: ids[10] = 537
    before = deepcopy(ids)
    result = decode(ids, context(), codec)
    assert result["status"] == status and result["generated_ids"] == ids == before
    assert result["selection"] is None and result["counts"] is None
    no_authority(result)


@pytest.mark.parametrize("ids", [None, (), [True], [1.0], [1 << 63], [1] * 513])
def test_api_id_malformation_or_overflow_is_atomic_operation_failure(ids, codec):
    for operation in (prefix, decode):
        with pytest.raises(ValueError): operation(ids, context(), codec)


@pytest.mark.parametrize("field", ["source_binding", "identity_sidecar", "authority", "original_request_sha256"])
def test_content_cannot_intake_archival_identity_or_permission(field, codec):
    value = content()
    value[field] = None
    with pytest.raises(ValueError): encode(value, context(), codec)


@pytest.mark.parametrize("location", ["content", "context", "codec"])
def test_independent_input_pins_refuse_before_model_classification(location, codec):
    c, x = wire(content()), wire(context())
    with pytest.raises(ValueError):
        subject.encode_compact_catalog_tokens_v1(c, x,
            expected_content_sha256="0" * 64 if location == "content" else sha(c),
            expected_context_sha256="0" * 64 if location == "context" else sha(x),
            codec=codec, expected_codec_sha256="0" * 64 if location == "codec" else codec_sha(codec))


@pytest.mark.parametrize("location", ["content", "context"])
def test_duplicate_json_keys_and_real_raw_byte_limits_are_not_truncated(location, codec):
    c, x = wire(content()), wire(context())
    raw = c if location == "content" else x
    duplicate = b'{"schema":' + wire(json.loads(raw)["schema"]) + b',' + raw[1:]
    maximum = subject.MAX_CONTENT_BYTES if location == "content" else subject.MAX_CONTEXT_BYTES
    oversized = raw + b" " * (maximum + 1 - len(raw))
    for invalid in (duplicate, oversized):
        left, right = (invalid, x) if location == "content" else (c, invalid)
        with pytest.raises(ValueError):
            subject.encode_compact_catalog_tokens_v1(left, right,
                expected_content_sha256=sha(left), expected_context_sha256=sha(right),
                codec=codec, expected_codec_sha256=codec_sha(codec))


def test_raw_whitespace_commitments_are_distinct_from_canonical_catalog_identity(codec):
    value, ctx = content(), context()
    c, x = json.dumps(value, indent=2).encode(), json.dumps(ctx, indent=2).encode()
    result = subject.encode_compact_catalog_tokens_v1(c, x,
        expected_content_sha256=sha(c), expected_context_sha256=sha(x),
        codec=codec, expected_codec_sha256=codec_sha(codec))
    canonical = encode(value, ctx, codec)
    assert result["original_content_raw_sha256"] == sha(c) != canonical["original_content_raw_sha256"]
    assert result["context_raw_sha256"] == sha(x) != canonical["context_raw_sha256"]
    assert result["context_sha256"] == canonical["context_sha256"]
    assert result["content_sha256"] == canonical["content_sha256"]
    assert result["selection"] == canonical["selection"]


@pytest.mark.parametrize("damage", ["profile", "vocabulary", "special", "extra"])
def test_resealed_codec_mutation_cannot_claim_new_profile_compatibility(damage, codec):
    changed = deepcopy(codec)
    if damage == "profile": changed["profile"] = old_tokens.PROFILE
    elif damage == "vocabulary": changed["vocabulary"][3:5] = reversed(changed["vocabulary"][3:5])
    elif damage == "special": changed["eos_id"] = 1
    else: changed["target_dictionary"] = {"untrusted": "entry"}
    with pytest.raises(ValueError):
        subject.decode_compact_catalog_tokens_v1([], wire(context()),
            expected_context_sha256=sha(wire(context())), codec=changed, expected_codec_sha256=sha(wire(changed)))


@pytest.mark.parametrize("operation", ["encode", "prefix", "decode"])
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_owner_load_failures_and_interrupts_keep_exact_exception_identity(operation, error_type, codec, monkeypatch):
    failure = error_type("authored owner-load failure")
    def fail(*args): raise failure
    monkeypatch.setattr(subject, "_owners", fail)
    with pytest.raises(error_type) as caught: invoke(operation, codec)
    assert caught.value is failure


def test_returned_selection_and_full_catalog_are_detached_from_all_inputs(codec):
    value, ctx = content(), context()
    before = deepcopy((value, ctx, codec))
    ids = ids_for(value, codec)
    result = decode(ids, ctx, codec)
    result["catalog_context"]["catalog"]["signature"]["symbols"].clear()
    result["selection"]["selected_catalog_indices"].append(1)
    result["selection"]["prediction"]["request"]["source_binding"] = {"accepted": True}
    assert (value, ctx, codec) == before
    fresh = decode(ids, ctx, codec)
    assert fresh["selection"]["selected_catalog_indices"] == [0, 2]
    no_authority(fresh)


def near_limit_content():
    rows = [["predicate", 0, [["variable", 0]]] for _ in range(27)]
    while len(rows) > 1:
        pairs = [["and", rows[i], rows[i + 1]] for i in range(0, len(rows) - 1, 2)]
        if len(rows) % 2: pairs.append(rows[-1])
        rows = pairs
    return {"schema": content_owner.CONTENT_SCHEMA,
            "tree": ["forall", 0, ["exists", 1, ["not", ["not", rows[0]]]]]}


def test_real_511_token_candidate_and_515_token_whole_refusal_with_unused_catalog_entries(codec):
    value, ctx = near_limit_content(), context()
    ids = ids_for(value, codec)
    assert len(ids) == 511
    assert encode(value, ctx, codec)["target_ids"] == ids
    accepted = decode(ids, ctx, codec)
    assert accepted["status"] == "valid_candidate"
    assert accepted["selection"]["unused_catalog_indices"] == [1, 2]
    assert prefix(ids[:-1], ctx, codec)["allowed_token_ids"] == [2]
    value["tree"][2][2] = ["not", value["tree"][2][2]]
    over = ids_for(value, codec)
    assert len(over) == 515
    with pytest.raises(ValueError): encode(value, ctx, codec)
    with pytest.raises(ValueError): decode(over, ctx, codec)
    state = prefix(over[:512], ctx, codec)
    assert state["status"] == "budget_exhausted" and state["remaining_token_slots"] == 0
    assert state["offered_ids"] == over[:512] and state["allowed_token_ids"] == []
    result = decode(over[:512], ctx, codec)
    assert result["status"] != "valid_candidate" and result["selection"] is None
    no_authority(result)


def test_nested_depth_limit_is_still_enforced_inside_total_token_limit(codec):
    body = ["predicate", 0, [["variable", 0]]]
    for _ in range(49): body = ["not", body]
    value = {"schema": content_owner.CONTENT_SCHEMA, "tree": ["forall", 0, body]}
    ids = ids_for(value, codec)
    assert len(ids) < 512
    result = decode(ids, context(), codec)
    assert result["status"] == "rejected" and result["selection"] is None
    with pytest.raises(ValueError): encode(value, context(), codec)


@pytest.mark.parametrize("operation", ["prepare", "encode", "prefix", "decode"])
def test_raw_pin_preflight_refuses_before_any_operation_import(operation, codec, monkeypatch):
    c, x = wire(content()), wire(context())
    fixed_sha = codec_sha(codec)
    def forbidden(*args): raise AssertionError("owner loaded before raw commitment preflight")
    monkeypatch.setattr(subject, "_token_owner", forbidden)
    monkeypatch.setattr(subject, "_owners", forbidden)
    with pytest.raises(ValueError):
        if operation == "prepare":
            cat = catalog()
            signature = {**cat["signature"], "signature_id": "authored"}
            subject.prepare_catalog_context_v1(wire(signature), wire(cat["argument_roles"]),
                expected_signature_sha256="0" * 64, expected_argument_roles_sha256=sha(wire(cat["argument_roles"])))
        elif operation == "encode":
            subject.encode_compact_catalog_tokens_v1(c, x, expected_content_sha256="0" * 64,
                expected_context_sha256=sha(x), codec=codec, expected_codec_sha256=fixed_sha)
        else:
            method = (subject.compact_catalog_allowed_token_ids_v1 if operation == "prefix"
                      else subject.decode_compact_catalog_tokens_v1)
            method([], x, expected_context_sha256="0" * 64, codec=codec, expected_codec_sha256=fixed_sha)


@pytest.mark.parametrize("operation", ["encode", "prefix", "decode"])
def test_source_change_after_full_report_serialization_refuses_instead_of_returning_candidate(operation, codec, monkeypatch):
    detach, seen = old_tokens._detach, []
    def changed_after_serialization(value, maximum):
        result = detach(value, maximum)
        if type(value) is dict and value.get("schema") in {
                subject.ENCODING_SCHEMA, subject.PREFIX_SCHEMA, subject.CANDIDATE_SCHEMA}:
            seen.append(value["schema"])
            monkeypatch.setattr(subject, "_SELF_SNAPSHOT", ("0" * 64, subject._SELF_SNAPSHOT[1]))
        return result
    # Instrument only the reused serializer after a complete NEW-profile report.
    # The source fence remains real; no original file is edited.
    monkeypatch.setattr(old_tokens, "_detach", changed_after_serialization)
    with pytest.raises(ValueError): invoke(operation, codec)
    assert len(seen) == 1


def test_changed_loaded_old_owner_anchor_is_not_a_candidate_failure(codec, monkeypatch):
    monkeypatch.setattr(content_owner, "_SELF_SHA", "0" * 64)
    with pytest.raises(ValueError): decode([-1], context(), codec)
