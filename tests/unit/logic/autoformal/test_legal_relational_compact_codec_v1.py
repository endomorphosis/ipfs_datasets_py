"""Authored compact transport controls; no model or statutory training claims."""
from copy import deepcopy
import builtins
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_compact_codec_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_target_codec_v1 as byte_codec


def _fixture_module():
    path = Path(__file__).with_name("test_legal_relational_norm_v1.py")
    spec = importlib.util.spec_from_file_location("_compact_relational_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = _fixture_module()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def byte_ids(raw):
    return [1, *(3 + value for value in raw), 2]


def project(value, codec):
    """Independent serialization oracle from the public fixed codec tables."""
    if type(value) is str and value in codec["string_constants"]:
        return {"@": codec["string_constants"].index(value)}
    if type(value) is dict:
        for index, constant in enumerate(codec["container_constants"]):
            if value == constant:
                return {"!": index}
        return {codec["key_map"].get(key, ":" + key): project(child, codec)
                for key, child in value.items()}
    if type(value) is list:
        return [project(child, codec) for child in value]
    return value


def compact_payload(request, codec):
    return {"schema": "legal-relational-compact-payload/v1", "request": project(request, codec)}


def modal_scope_request(*, inner):
    """Authored A/B-shaped declarations, without any statutory source claim."""
    builder = fixtures.Builder()
    action = builder.binary("or", builder.atom("Assign", "recipient", "duties"),
                            builder.atom("Transfer", "recipient", "duties"))
    approval = builder.atom("Approve", "approver", "recipient")
    body = (builder.modal("P", builder.binary("implies", action, approval)) if inner
            else builder.binary("implies", builder.modal("P", action), approval))
    return fixtures.request_for(builder, body,
        [("Assign", ("recipient", "duties")), ("Transfer", ("recipient", "duties")),
         ("Approve", ("approver", "recipient"))],
        [("recipient", "forall"), ("duties", "forall"), ("approver", "forall")])


@pytest.fixture(scope="module")
def codec():
    return subject.build_relational_compact_codec_v1()


def encode(raw, codec, **changes):
    return subject.encode_relational_compact_target_v1(raw, **{
        "expected_request_sha256": sha(raw), "codec": codec,
        "expected_codec_sha256": subject.relational_compact_codec_sha256(codec), **changes})


def decode(ids, codec, **changes):
    return subject.decode_relational_compact_candidate_v1(ids, **{
        "codec": codec, "expected_codec_sha256": subject.relational_compact_codec_sha256(codec),
        **changes})


def assert_candidate_only(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0


def walk(value):
    yield value
    if type(value) is dict:
        for child in value.values():
            yield from walk(child)
    elif type(value) is list:
        for child in value:
            yield from walk(child)


def test_public_import_and_fixed_builder_use_no_model_or_operation_owners(monkeypatch):
    module = ModuleType("_cold_relational_compact_codec_contract")
    module.__file__ = subject.__file__
    monkeypatch.setitem(sys.modules, module.__name__, module)
    original_import = builtins.__import__
    attempts = []

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"ipfs_datasets_py", "torch", "numpy", "transformers",
                                  "requests", "pyarrow", "duckdb", "cryptography"}:
            attempts.append(name)
            raise AssertionError("operation owner loaded by pure compact boundary")
        return original_import(name, *args, **kwargs)

    source = Path(subject.__file__).read_bytes()
    with monkeypatch.context() as context:
        context.setattr(builtins, "__import__", guarded)
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        fixed = module.build_relational_compact_codec_v1()
        assert len(module.relational_compact_codec_sha256(fixed)) == 64
    assert attempts == []


def test_codec_is_target_independent_and_generation_accepts_no_reference(codec):
    original = deepcopy(codec)
    assert codec["vocabulary"] == ["PAD", "BOS", "EOS", *("BYTE_%02X" % i for i in range(256))]
    assert codec["vocabulary_size"] == 259
    assert (codec["pad_id"], codec["bos_id"], codec["eos_id"], codec["byte_offset"]) == (0, 1, 2, 3)
    assert set(inspect.signature(subject.decode_relational_compact_candidate_v1).parameters) == {
        "generated_ids", "codec", "expected_codec_sha256"}
    first = encode(wire(fixtures.approval_request()), codec)
    second = encode(wire(fixtures.role_request(swapped=True)), codec)
    assert first["codec_sha256"] == second["codec_sha256"] == subject.relational_compact_codec_sha256(codec)
    assert codec == original == subject.build_relational_compact_codec_v1()
    assert first["target_ids"] != second["target_ids"]
    assert subject.relational_compact_codec_sha256(codec) != byte_codec.relational_target_codec_sha256(
        byte_codec.build_relational_target_codec_v1())


def test_exact_roundtrip_retains_all_ids_roles_array_order_and_explicit_empty_metadata(codec):
    request = fixtures.approval_request()
    request["expression"]["expression_id"] = "fixture:expression:replacement:0"
    request["expression"]["signature"]["signature_id"] = "fixture:signature:replacement:1"
    for number, node in enumerate(walk(request)):
        if type(node) is dict and "node_id" in node:
            node["node_id"] = "fixture:node:replacement:" + str(number)
    request = fixtures.reseal_expression(request)
    raw = (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    snapshot = deepcopy((request, codec))
    encoded = encode(raw, codec)
    canonical = wire(request)
    compact_raw = encoded["compact_request_raw_utf8"].encode("utf-8")
    assert encoded["original_request"] == {"bytes": len(raw), "sha256": sha(raw)}
    assert encoded["canonical_request"] == {"bytes": len(canonical), "sha256": sha(canonical)}
    assert encoded["canonical_request_raw_utf8"].encode("utf-8") == canonical
    assert encoded["compact_request"] == {"bytes": len(compact_raw), "sha256": sha(compact_raw)}
    assert compact_raw == wire(compact_payload(request, codec))
    assert encoded["target_ids"] == byte_ids(compact_raw)
    assert len(compact_raw) < len(canonical)  # Only this authored transport fixture.
    result = decode(encoded["target_ids"], codec)
    assert result["status"] == "valid_candidate" and result["reason"] is None
    assert result["canonical_request_raw_utf8"].encode("utf-8") == canonical
    assert json.loads(result["canonical_request_raw_utf8"]) == request
    assert result["canonical_request_sha256"] == sha(canonical)
    assert result["generated_transport_sha256"] == sha(compact_raw)
    assert result["generated_transport_bytes"] == len(compact_raw)
    assert result["generated_ids"] == encoded["target_ids"]
    assert any(type(node) is dict and node.get("metadata") == {} for node in walk(request))
    assert (request, codec) == snapshot
    replay = subject.validate_relational_compact_encoding_v1(encoded, raw,
        expected_encoding_sha256=subject.relational_compact_encoding_sha256(encoded),
        expected_request_sha256=sha(raw), codec=codec,
        expected_codec_sha256=subject.relational_compact_codec_sha256(codec))
    assert replay == encoded
    assert_candidate_only(encoded)
    assert_candidate_only(result)


def test_public_projection_tables_are_fixed_injective_and_preserve_unknown_keys(codec):
    aliases = list(codec["key_map"].values())
    assert len(aliases) == len(set(aliases))
    assert all(type(alias) is str and len(alias) == 1 and alias not in {":", "@", "!"}
               for alias in aliases)
    assert len(codec["string_constants"]) == len(set(codec["string_constants"]))
    assert all(type(value) is str for value in codec["string_constants"])
    assert all(type(value) is dict for value in codec["container_constants"])
    assert {} not in codec["container_constants"]
    assert len({wire(value) for value in codec["container_constants"]}) == len(codec["container_constants"])
    # The identity remains a literal supplied identity even if it resembles a
    # fixed key, schema constant or another node's serialization.
    request = fixtures.approval_request()
    request["expression"]["expression_id"] = "legacy.deontic/v1"
    request = fixtures.reseal_expression(request)
    result = decode(byte_ids(wire(compact_payload(request, codec))), codec)
    assert result["status"] == "valid_candidate"
    assert json.loads(result["canonical_request_raw_utf8"]) == request


def test_generated_pretty_transport_retains_its_raw_hash_without_encoder_or_reference(codec):
    request = fixtures.approval_request()
    projected = compact_payload(request, codec)
    raw = (json.dumps(projected, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    result = decode(byte_ids(raw), codec)
    assert result["status"] == "valid_candidate"
    assert result["generated_transport_utf8"].encode("utf-8") == raw
    assert result["generated_transport_hex"] == raw.hex()
    assert result["generated_transport_sha256"] == sha(raw) != sha(wire(projected))
    assert result["canonical_request_raw_utf8"].encode("utf-8") == wire(request)
    assert_candidate_only(result)


@pytest.mark.parametrize("damage", ["unknown_alias", "escaped_known_key", "marker_extra_key",
    "boolean_marker", "marker_range", "literal_fixed_string", "expanded_fixed_container",
    "missing_field", "extra_payload_field", "duplicate_json", "truncated_json"])
def test_malformed_compact_projection_is_retained_and_rejected_without_defaults(codec, monkeypatch, damage):
    payload = compact_payload(fixtures.approval_request(), codec)
    if damage == "unknown_alias": payload["request"]["unknown_compact_alias"] = None
    elif damage == "escaped_known_key":
        alias = codec["key_map"]["expression"]
        payload["request"][":expression"] = payload["request"].pop(alias)
    elif damage == "marker_extra_key": payload["request"] = {"@": 0, "invented": None}
    elif damage == "boolean_marker": payload["request"] = {"@": True}
    elif damage == "marker_range": payload["request"] = {"!": len(codec["container_constants"])}
    elif damage == "literal_fixed_string": payload["request"] = codec["string_constants"][0]
    elif damage == "expanded_fixed_container":
        payload["request"] = {codec["key_map"].get(key, ":" + key): project(value, codec)
                              for key, value in codec["container_constants"][0].items()}
    elif damage == "missing_field": payload.pop("request")
    elif damage == "extra_payload_field": payload["reference"] = fixtures.approval_request()
    raw = (b'{"schema":"one","schema":"two"}' if damage == "duplicate_json" else wire(payload))
    if damage == "truncated_json": raw = raw[:-1]
    ids = byte_ids(raw)
    monkeypatch.setattr(subject, "_base", lambda: pytest.fail("owner loaded before compact refusal"))
    result = decode(ids, codec)
    assert result["status"] == "rejected"
    assert result["reason"] in {"compact_json_rejected", "compact_projection_rejected"}
    assert result["generated_ids"] == ids
    assert result["generated_transport_hex"] == raw.hex()
    assert result["generated_transport_sha256"] == sha(raw)
    assert result["canonical_request_raw_utf8"] is None
    assert_candidate_only(result)


@pytest.mark.parametrize("damage", ["metadata", "source_binding", "free_variable", "missing_signature"])
def test_reversible_projection_cannot_authorize_an_unsupported_relational_request(codec, damage):
    request = fixtures.approval_request()
    if damage == "metadata":
        request["expression"]["metadata"] = {"approved": True, "@": "opaque", ":expression": "opaque"}
        request = fixtures.reseal_expression(request)
    elif damage == "source_binding": request["source_binding"] = {"training_mask": 1}
    elif damage == "missing_signature": request["expression"].pop("signature")
    else:
        root = request["expression"]["root"]
        implication = root["arguments"][0]["arguments"][0]["arguments"][0]
        action = implication["arguments"][0]["extension"]["children"][0]
        action["arguments"][0]["arguments"][0]["symbol"] = "unbound_actor"
        request = fixtures.reseal_expression(request)
    raw = wire(compact_payload(request, codec))
    result = decode(byte_ids(raw), codec)
    assert result["status"] == "rejected" and result["reason"] == "typed_request_rejected"
    assert result["generated_transport_sha256"] == sha(raw)
    assert result["canonical_request_raw_utf8"] is None
    assert_candidate_only(result)


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_owner_unavailability_or_interruption_is_not_a_rejected_model_output(codec, monkeypatch, error_type):
    raw = wire(compact_payload(fixtures.approval_request(), codec))
    failure = error_type("authored owner interruption")

    def unavailable():
        raise failure

    monkeypatch.setattr(subject, "_base", unavailable)
    with pytest.raises(error_type) as raised:
        decode(byte_ids(raw), codec)
    assert raised.value is failure


@pytest.mark.parametrize("variation", ["modal_boundary", "argument_order", "quantifier_order", "permission_force"])
def test_valid_different_semantics_remain_different_without_reference_repair(codec, variation):
    if variation == "modal_boundary":
        first, second = modal_scope_request(inner=False), modal_scope_request(inner=True)
    elif variation == "argument_order":
        first, second = fixtures.role_request(), fixtures.role_request(swapped=True)
    elif variation == "permission_force":
        first, second = fixtures.approval_request(operator="P"), fixtures.approval_request(operator="F")
    else:
        def quantified(binders):
            builder = fixtures.Builder()
            return fixtures.request_for(builder, builder.atom("Match", "actor", "recipient"),
                [("Match", ("actor", "recipient"))], binders)
        first = quantified([("actor", "forall"), ("recipient", "exists")])
        second = quantified([("recipient", "exists"), ("actor", "forall")])
    a, b = encode(wire(first), codec), encode(wire(second), codec)
    assert a["target_ids"] != b["target_ids"]
    result = decode(b["target_ids"], codec)
    assert result["status"] == "valid_candidate"
    assert json.loads(result["canonical_request_raw_utf8"]) == second != first
    assert result["canonical_request_sha256"] != a["canonical_request"]["sha256"]
    assert_candidate_only(result)


@pytest.mark.parametrize("damage,status", [
    ("empty", "incomplete"), ("missing_eos", "incomplete"),
    ("missing_bos", "rejected"), ("interior_bos", "rejected"),
    ("pad", "rejected"), ("after_eos", "rejected"),
    ("out_of_vocabulary", "rejected"), ("invalid_utf8", "rejected"),
])
def test_generation_framing_preserves_original_ids_without_repair(codec, monkeypatch, damage, status):
    ids = byte_ids(b"{}")
    if damage == "empty": ids = []
    elif damage == "missing_eos": ids.pop()
    elif damage == "missing_bos": ids.pop(0)
    elif damage == "interior_bos": ids.insert(2, 1)
    elif damage == "pad": ids.insert(2, 0)
    elif damage == "after_eos": ids.append(3 + ord(" "))
    elif damage == "out_of_vocabulary": ids[2] = 259
    else: ids = byte_ids(b"\xff")
    snapshot = deepcopy(ids)
    monkeypatch.setattr(subject, "_base", lambda: pytest.fail("owner loaded for invalid generated frame"))
    result = decode(ids, codec)
    assert result["status"] == status
    assert result["generated_ids"] == ids == snapshot
    assert result["canonical_request_raw_utf8"] is None
    assert result["canonical_request_sha256"] is None
    if damage == "invalid_utf8":
        assert result["generated_transport_utf8"] is None
        assert result["generated_transport_hex"] == "ff"
        assert result["generated_transport_sha256"] == sha(b"\xff")
    if status == "incomplete":
        assert result["framing"]["terminated"] is False
    assert_candidate_only(result)


@pytest.mark.parametrize("ids", [[True], [1.0], [2 ** 40]])
def test_noninteger_or_unbounded_ids_refuse_instead_of_becoming_model_outcomes(codec, ids):
    with pytest.raises(ValueError):
        decode(ids, codec)


def test_sequence_overflow_refuses_without_truncation(codec):
    with pytest.raises(ValueError):
        decode([1] * (subject.MAX_SEQUENCE_TOKENS + 1), codec)


@pytest.mark.parametrize("damage", ["pin", "vocabulary", "extra_field", "old_byte_codec"])
def test_wrong_codec_or_resealed_codec_change_refuses(codec, damage):
    changed = deepcopy(codec)
    expected = subject.relational_compact_codec_sha256(codec)
    if damage == "pin": expected = "0" * 64
    elif damage == "vocabulary":
        changed["vocabulary"][3:5] = reversed(changed["vocabulary"][3:5])
        expected = sha(wire(changed))
    elif damage == "extra_field":
        changed["target_dictionary"] = {"0": "fixture:node:1"}
        expected = sha(wire(changed))
    else:
        changed = byte_codec.build_relational_target_codec_v1()
        expected = byte_codec.relational_target_codec_sha256(changed)
    with pytest.raises(ValueError):
        subject.decode_relational_compact_candidate_v1([], codec=changed, expected_codec_sha256=expected)


@pytest.mark.parametrize("damage", ["raw_pin", "invalid_utf8", "duplicate_json", "oversize"])
def test_encoding_preflight_refuses_malformed_whole_inputs(codec, monkeypatch, damage):
    raw = wire(fixtures.approval_request())
    expected = sha(raw)
    if damage == "raw_pin": expected = "0" * 64
    elif damage == "invalid_utf8": raw = b"\xff"; expected = sha(raw)
    elif damage == "duplicate_json": raw = b'{"schema":1,"schema":2}'; expected = sha(raw)
    else: raw = b" " * (subject.MAX_REQUEST_BYTES + 1); expected = sha(raw)
    monkeypatch.setattr(subject, "_base", lambda: pytest.fail("owner loaded before failed whole-input preflight"))
    with pytest.raises(ValueError):
        encode(raw, codec, expected_request_sha256=expected)


@pytest.mark.parametrize("damage", ["target_ids", "authority", "training_mask", "original_pin"])
def test_resealing_report_cannot_authorize_target_change_or_promote_masks(codec, damage):
    raw = wire(fixtures.approval_request())
    encoded = encode(raw, codec)
    if damage == "target_ids": encoded["target_ids"][1] = 3 + ord("[")
    elif damage == "authority": encoded["authority"]["proof_authority"] = True
    elif damage == "training_mask": encoded["training_mask"] = 1
    else: encoded["original_request"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        subject.validate_relational_compact_encoding_v1(encoded, raw,
            expected_encoding_sha256=sha(wire(encoded)), expected_request_sha256=sha(raw), codec=codec,
            expected_codec_sha256=subject.relational_compact_codec_sha256(codec))
