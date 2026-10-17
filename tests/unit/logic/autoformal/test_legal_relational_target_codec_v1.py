"""Model-free byte targets preserve authored syntax without semantic admission."""
from copy import deepcopy
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_target_codec_v1 as subject


def _fixture_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = _fixture_module("_target_codec_relational_fixtures", "test_legal_relational_norm_v1.py")


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def byte_ids(raw, *, terminated=True):
    """Independent fixed-byte oracle; never derive a vocabulary from a target."""
    return [1, *(3 + value for value in raw), *([2] if terminated else [])]


@pytest.fixture(scope="module")
def codec():
    return subject.build_relational_target_codec_v1()


def encode(raw, codec, **changes):
    return subject.encode_relational_target_v1(raw, **{
        "expected_request_sha256": sha(raw), "codec": codec,
        "expected_codec_sha256": subject.relational_target_codec_sha256(codec), **changes})


def decode(ids, codec, **changes):
    return subject.decode_relational_candidate_v1(ids, **{
        "codec": codec, "expected_codec_sha256": subject.relational_target_codec_sha256(codec),
        **changes})


def assert_candidate_only(report):
    assert not any(report["authority"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0


def test_public_source_import_and_fixed_builder_do_not_load_operation_owners(monkeypatch):
    module = ModuleType("_cold_relational_target_codec_contract")
    module.__file__ = subject.__file__
    monkeypatch.setitem(sys.modules, module.__name__, module)
    original_import = builtins.__import__
    attempts = []

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"ipfs_datasets_py", "torch", "numpy", "transformers",
                                  "requests", "pyarrow", "duckdb", "cryptography"}:
            attempts.append(name)
            raise AssertionError("operation owner imported by pure codec boundary")
        return original_import(name, *args, **kwargs)

    source = Path(subject.__file__).read_bytes()
    with monkeypatch.context() as context:
        context.setattr(builtins, "__import__", guarded)
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        frozen = module.build_relational_target_codec_v1()
        assert len(module.relational_target_codec_sha256(frozen)) == 64
    assert attempts == []


def test_fixed_vocabulary_and_byte_oracle_are_independent_of_target(codec):
    before = deepcopy(codec)
    assert codec["vocabulary"] == ["PAD", "BOS", "EOS", *("BYTE_%02X" % i for i in range(256))]
    assert codec["vocabulary_size"] == 259
    assert (codec["pad_id"], codec["bos_id"], codec["eos_id"], codec["byte_offset"]) == (0, 1, 2, 3)
    first = encode(wire(fixtures.approval_request()), codec)
    second = encode(wire(fixtures.role_request(swapped=True)), codec)
    assert first["codec_sha256"] == second["codec_sha256"] == subject.relational_target_codec_sha256(codec)
    assert codec == before == subject.build_relational_target_codec_v1()
    for encoded in (first, second):
        raw = encoded["canonical_request_raw_utf8"].encode("utf-8")
        assert encoded["target_ids"] == byte_ids(raw)
        assert all(3 <= token <= 258 for token in encoded["target_ids"][1:-1])
    assert len(set(byte_ids(bytes(range(256)))[1:-1])) == 256
    assert min(byte_ids(bytes(range(256)))[1:-1]) == 3
    assert max(byte_ids(bytes(range(256)))[1:-1]) == 258


def test_original_transport_and_canonical_request_commitments_stay_distinct(codec):
    request = fixtures.approval_request()
    raw = (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    original = deepcopy((request, codec))
    encoded = encode(raw, codec)
    canonical = wire(request)
    assert raw != canonical and sha(raw) != sha(canonical)
    assert encoded["original_request"] == {"bytes": len(raw), "sha256": sha(raw)}
    assert encoded["canonical_request"] == {"bytes": len(canonical), "sha256": sha(canonical)}
    assert encoded["canonical_request_raw_utf8"].encode("utf-8") == canonical
    assert encoded["target_ids"] == byte_ids(canonical)
    replayed = subject.validate_relational_target_encoding_v1(encoded, raw,
        expected_encoding_sha256=subject.relational_target_encoding_sha256(encoded),
        expected_request_sha256=sha(raw), codec=codec,
        expected_codec_sha256=subject.relational_target_codec_sha256(codec))
    assert replayed == encoded
    candidate = decode(encoded["target_ids"], codec)
    assert candidate["status"] == "valid_candidate"
    assert json.loads(candidate["canonical_request_raw_utf8"]) == request
    assert candidate["canonical_request_sha256"] == sha(canonical)
    assert candidate["generated_transport_sha256"] == sha(canonical)
    assert candidate["framing"]["terminated"]
    canonical_owner = fixtures.prepare(request)
    assert candidate["relational_owner_report_sha256"] == fixtures.bridge.relational_norm_report_sha256(canonical_owner)
    # The relational report retains its original request transport, so a
    # pretty-input owner report has a different hash from this canonical one.
    assert candidate["relational_owner_report_sha256"] != encoded["relational_owner_report_sha256"]
    assert candidate["typed_expression_codec_sha256"] == encoded["typed_expression_codec_sha256"]
    assert (request, codec) == original
    assert_candidate_only(encoded)
    assert_candidate_only(candidate)


@pytest.mark.parametrize("change", ["argument_order", "quantifier_scope", "modality", "negation"])
def test_valid_but_different_semantics_decode_without_repair_or_invalid_label(codec, change):
    if change == "argument_order":
        original, changed = fixtures.role_request(), fixtures.role_request(swapped=True)
    elif change == "quantifier_scope":
        def quantified(order):
            builder = fixtures.Builder()
            return fixtures.request_for(builder, builder.atom("Match", "actor", "recipient"),
                [("Match", ("actor", "recipient"))], order)
        original = quantified([("actor", "forall"), ("recipient", "exists")])
        changed = quantified([("recipient", "exists"), ("actor", "forall")])
    elif change == "modality":
        original, changed = fixtures.approval_request(operator="P"), fixtures.approval_request(operator="F")
    else:
        def polarity(negative):
            builder = fixtures.Builder()
            body = builder.atom("Allowed", "actor")
            if negative:
                body = fixtures.ast.mk_not(builder.nid(), body)
            return fixtures.request_for(builder, body, [("Allowed", ("subject",))], [("actor", "forall")])
        original, changed = polarity(False), polarity(True)
    first = encode(wire(original), codec)
    second = encode(wire(changed), codec)
    candidate = decode(second["target_ids"], codec)
    assert candidate["status"] == "valid_candidate"
    assert json.loads(candidate["canonical_request_raw_utf8"]) == changed
    assert changed != original and second["target_ids"] != first["target_ids"]
    assert candidate["canonical_request_sha256"] != first["canonical_request"]["sha256"]
    assert_candidate_only(candidate)


def test_noncanonical_generated_transport_is_retained_without_relabelling_original_bytes(codec):
    request = fixtures.approval_request()
    raw = (json.dumps(request, indent=1) + "\n").encode()
    ids = byte_ids(raw)
    candidate = decode(ids, codec)
    assert candidate["status"] == "valid_candidate" and candidate["generated_ids"] == ids
    assert candidate["generated_transport_utf8"].encode() == raw
    assert candidate["generated_transport_sha256"] == sha(raw)
    assert candidate["canonical_request_raw_utf8"].encode() == wire(request)
    assert candidate["canonical_request_sha256"] != candidate["generated_transport_sha256"]


@pytest.mark.parametrize("damage,status", [
    ("empty", "incomplete"), ("missing_eos", "incomplete"),
    ("missing_bos", "rejected"), ("interior_bos", "rejected"),
    ("pad", "rejected"), ("after_eos", "rejected"),
    ("out_of_vocabulary", "rejected"), ("invalid_utf8", "rejected"),
])
def test_framing_and_utf8_outcomes_preserve_actual_generated_evidence(codec, damage, status):
    raw = wire(fixtures.approval_request())
    ids = byte_ids(raw)
    if damage == "empty": ids = []
    elif damage == "missing_eos": ids.pop()
    elif damage == "missing_bos": ids.pop(0)
    elif damage == "interior_bos": ids.insert(2, 1)
    elif damage == "pad": ids.insert(2, 0)
    elif damage == "after_eos": ids.append(3 + ord(" "))
    elif damage == "out_of_vocabulary": ids[2] = 259
    else: ids = byte_ids(b"\xff")
    original = deepcopy(ids)
    result = decode(ids, codec)
    assert result["status"] == status and result["generated_ids"] == original and ids == original
    assert result["canonical_request_raw_utf8"] is None
    if damage == "invalid_utf8":
        assert result["generated_transport_utf8"] is None
        assert result["generated_transport_hex"] == "ff"
        assert result["generated_transport_sha256"] == sha(b"\xff")
    if damage in ("empty", "missing_eos"):
        assert not result["framing"]["terminated"] and not result["framing"]["eos_present"]
    assert_candidate_only(result)


@pytest.mark.parametrize("damage", ["duplicate_json", "free_variable", "arity", "unknown_extension", "equality"])
def test_generated_unsupported_requests_remain_rejected_candidates(codec, damage):
    request = fixtures.approval_request()
    expression = request["expression"]
    implication = expression["root"]["arguments"][0]["arguments"][0]["arguments"][0]
    modal = implication["arguments"][0]["extension"]
    if damage == "duplicate_json":
        raw = b'{"schema":"one","schema":"two"}'
    else:
        if damage == "free_variable": modal["children"][0]["arguments"][0]["arguments"][0]["symbol"] = "unbound_actor"
        elif damage == "arity": expression["signature"]["symbols"][0]["domain"].pop()
        elif damage == "unknown_extension": modal["payload_schema"] = "invented.modal/v1"
        else:
            expression["root"] = fixtures.ast.mk_equality("fixture:equality",
                fixtures.ast.mk_variable("fixture:left", "actor", fixtures.OBJECT),
                fixtures.ast.mk_variable("fixture:right", "actor", fixtures.OBJECT)).to_dict()
        if damage == "arity":
            # This is an offered invalid dictionary, not a valid fixture AST:
            # constructing TypedExpression here would refuse before decoding.
            expression["content_digest"] = ""
            raw = wire(request)
        else:
            raw = wire(fixtures.reseal_expression(request))
    ids = byte_ids(raw)
    result = decode(ids, codec)
    assert result["status"] == "rejected" and result["generated_ids"] == ids
    assert result["generated_transport_sha256"] == sha(raw)
    assert result["canonical_request_raw_utf8"] is None
    assert_candidate_only(result)


@pytest.mark.parametrize("damage", ["codec_pin", "codec_extra_field", "codec_mutation"])
def test_unrelated_codec_or_resealed_vocabulary_changes_are_refused(codec, damage):
    changed = deepcopy(codec)
    expected = subject.relational_target_codec_sha256(changed)
    if damage == "codec_pin": expected = "0" * 64
    elif damage == "codec_extra_field":
        changed["invented_target_vocabulary"] = ["a", "b"]
        expected = sha(wire(changed))
    else:
        # A coherent new digest cannot change this profile's fixed mapping.
        changed["vocabulary"][3:5] = reversed(changed["vocabulary"][3:5])
        expected = sha(wire(changed))
    with pytest.raises(ValueError):
        decode(byte_ids(wire(fixtures.approval_request())), changed, expected_codec_sha256=expected)


@pytest.mark.parametrize("damage", ["request_pin", "duplicate_json", "invalid_utf8", "oversize"])
def test_encoding_preflight_refuses_before_loading_typed_owners(codec, monkeypatch, damage):
    raw = wire(fixtures.approval_request())
    expected = sha(raw)
    if damage == "request_pin": expected = "0" * 64
    elif damage == "duplicate_json": raw = b'{"schema":1,"schema":2}'; expected = sha(raw)
    elif damage == "invalid_utf8": raw = b"\xff"; expected = sha(raw)
    else: raw = b" " * (subject.MAX_REQUEST_BYTES + 1); expected = sha(raw)
    monkeypatch.setattr(subject, "_owners", lambda: pytest.fail("typed owners loaded before failed preflight"))
    with pytest.raises(ValueError): encode(raw, codec, expected_request_sha256=expected)


@pytest.mark.parametrize("ids", [[True], [1.0], [2 ** 40]])
def test_noninteger_or_non_int32_sequences_refuse_instead_of_becoming_candidates(codec, ids):
    with pytest.raises(ValueError): decode(ids, codec)


def test_whole_sequence_bound_refuses_instead_of_truncating(codec):
    with pytest.raises(ValueError): decode([1] * (subject.MAX_SEQUENCE_TOKENS + 1), codec)


@pytest.mark.parametrize("damage", ["target", "authority", "mask", "original_transport"])
def test_resealed_encoding_cannot_change_targets_or_promote_unreviewed_data(codec, damage):
    raw = wire(fixtures.approval_request())
    report = encode(raw, codec)
    if damage == "target": report["target_ids"][1] = 3 + ord("[")
    elif damage == "authority": report["authority"]["proof_authority"] = True
    elif damage == "mask": report["training_mask"] = 1
    else: report["original_request"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        subject.validate_relational_target_encoding_v1(report, raw,
            expected_encoding_sha256=sha(wire(report)),
            expected_request_sha256=sha(raw), codec=codec,
            expected_codec_sha256=subject.relational_target_codec_sha256(codec))
