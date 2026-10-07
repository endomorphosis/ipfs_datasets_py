"""Finite data correspondence: exact types, complete bytes, no stored authority."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.software_contracts import finite_record_projection as p
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured


RENAME = p.FiniteRecordProjectionContract("rename", "id", "key")
COPY = p.FiniteRecordProjectionContract("copy", "id", "key")
INPUT = b'{"id":1,"name":"Ada"}\n{"id":"two","name":"Lin"}\n'
RENAMED = b'{"key":1,"name":"Ada"}\n{"key":"two","name":"Lin"}\n'
COPIED = b'{"id":1,"key":1,"name":"Ada"}\n{"id":"two","key":"two","name":"Lin"}\n'


def ndjson(rows):
    return b"".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
                    for row in rows)


def assert_rejected(call, reason=None):
    with pytest.raises(p.FiniteRecordProjectionError) as error:
        call()
    if reason is not None:
        assert error.value.reason_code == reason


@pytest.mark.parametrize("contract,expected", [(RENAME, RENAMED), (COPY, COPIED)])
def test_authored_two_record_projection_checks_and_binds_every_artifact(contract, expected):
    assert p.synthesize_finite_record_projection(INPUT, contract) == expected
    result = p.check_finite_record_projection(INPUT, expected, contract)
    assert result["status"] == "checked"
    assert result["evidence_kind"] == "finite_record_check"
    assert result["record_count"] == 2
    assert result["checked_scalar_count"] == (4 if contract.mode == "rename" else 6)
    assert result["input_sha256"] == hashlib.sha256(INPUT).hexdigest()
    assert result["output_sha256"] == hashlib.sha256(expected).hexdigest()
    assert result["contract_cid"] == contract.cid
    assert result["receipt_cid"] == cid_for_structured({k: v for k, v in result.items() if k != "receipt_cid"})
    assert p.verify_finite_record_check(result, input_bytes=INPUT, output_bytes=expected, contract=contract) == result
    for field in ("semantic_alignment_verified", "kernel_checked", "proof_authority",
                  "execution_authority", "publication_authority", "completion_authority"):
        assert result[field] is False
    assert len(result["checker_provenance"]["sources"]) == 2


def test_checker_independent_of_synthesizer_and_serialization(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("checker used the candidate synthesizer")
    monkeypatch.setattr(p, "synthesize_finite_record_projection", forbidden)
    reordered_keys = b'{ "name": "Ada", "key": 1 }\r\n{"name":"Lin","key":"two"}'
    result = p.check_finite_record_projection(INPUT, reordered_keys, RENAME)
    assert result["record_count"] == 2
    assert result["output_sha256"] != hashlib.sha256(RENAMED).hexdigest()


@pytest.mark.parametrize("value", [None, True, False, 0, -7, p.MAX_SAFE_INTEGER,
                                  -p.MAX_SAFE_INTEGER, "", "null", "α🙂", 'quotes"\\\n{}[]'])
@pytest.mark.parametrize("contract", [COPY, RENAME])
def test_all_admitted_scalar_values_round_trip_with_exact_types(value, contract):
    source = ndjson([{"id": value, "unrelated": value}])
    target = p.synthesize_finite_record_projection(source, contract)
    row = json.loads(target)
    assert type(row["key"]) is type(value)
    assert row["key"] == value
    assert type(row["unrelated"]) is type(value)
    assert p.check_finite_record_projection(source, target, contract)["record_count"] == 1


def test_record_duplicates_preserve_multiplicity_without_inventing_unique_identifiers():
    source = b'{"id":1}\n{"id":1}\n'
    target = b'{"key":1}\n{"key":1}\n'
    assert p.check_finite_record_projection(source, target, RENAME)["record_count"] == 2
    assert_rejected(lambda: p.check_finite_record_projection(source, target.splitlines()[0], RENAME),
                    "record_cardinality_mismatch")


def test_unicode_controls_and_link_looking_fields_are_exact_ordinary_data():
    source = ndjson([{"id": "é", "é": "e\u0301", "e\u0301": "é",
                     "/": "bafkreievalue", "control": "\x00\r\n\t\b\u2028",
                     "": "empty key remains data"}])
    output = p.synthesize_finite_record_projection(source, RENAME)
    decoded = json.loads(output)
    assert decoded["key"] == "é"
    assert decoded["é"] == "e\u0301"
    assert decoded["e\u0301"] == "é"
    assert decoded["/"] == "bafkreievalue"
    assert decoded["control"] == "\x00\r\n\t\b\u2028"
    assert decoded[""] == "empty key remains data"
    assert p.check_finite_record_projection(source, output, RENAME)["record_count"] == 1
    decoded["key"] = "e\u0301"
    assert_rejected(lambda: p.check_finite_record_projection(source, ndjson([decoded]), RENAME),
                    "record_scalar_correspondence_mismatch")


@pytest.mark.parametrize("target,reason", [
    (b'{"key":"two","name":"Lin"}\n{"key":1,"name":"Ada"}\n', "record_scalar_correspondence_mismatch"),
    (RENAMED.splitlines()[0], "record_cardinality_mismatch"),
    (RENAMED + RENAMED.splitlines()[0] + b"\n", "record_cardinality_mismatch"),
    (RENAMED.replace(b'"Ada"', b'"Else"'), "record_scalar_correspondence_mismatch"),
    (RENAMED.replace(b'"key":1', b'"key":true'), "record_scalar_correspondence_mismatch"),
    (RENAMED.replace(b'"key":1', b'"key":"1"'), "record_scalar_correspondence_mismatch"),
    (RENAMED.replace(b'"key":1', b'"key":null'), "record_scalar_correspondence_mismatch"),
    (RENAMED.replace(b'"key":1,', b''), "record_field_correspondence_mismatch"),
    (RENAMED.replace(b'"key":1', b'"key":1,"extra":false'), "record_field_correspondence_mismatch"),
    (RENAMED.replace(b'"key":1', b'"key":1,"id":1'), "record_field_correspondence_mismatch"),
    (RENAMED.replace(b'"key":1', b'"key":1,"key":2'), "duplicate_json_key"),
])
def test_record_mutations_never_pass(target, reason):
    assert_rejected(lambda: p.check_finite_record_projection(INPUT, target, RENAME), reason)


def test_copy_requires_original_source_while_rename_removes_it():
    assert_rejected(lambda: p.check_finite_record_projection(INPUT, RENAMED, COPY),
                    "record_field_correspondence_mismatch")
    assert_rejected(lambda: p.check_finite_record_projection(INPUT, COPIED, RENAME),
                    "record_field_correspondence_mismatch")


@pytest.mark.parametrize("source,reason", [
    (b'{"name":null}', "source_field_absent"),
    (b'{"id":null,"key":null}', "target_field_already_present"),
    (b'{"id":1,"key":1}', "target_field_already_present"),
    (b'{"id":1,"id":2}', "duplicate_json_key"),
    (b'{"id":1,"\\u0069d":2}', "duplicate_json_key"),
    (b'{"id":1.0}', "non_integer_number"),
    (b'{"id":1e0}', "non_integer_number"),
    (b'{"id":NaN}', "non_integer_number"),
    (b'{"id":Infinity}', "non_integer_number"),
    (b'{"id":-Infinity}', "non_integer_number"),
    (b'{"id":9007199254740992}', "integer_bound"),
    (b'{"id":-9007199254740992}', "integer_bound"),
    (b'{"id":' + b'9' * 8000 + b'}', "integer_bound"),
    (b'{"id":[]}', "nested_or_non_object_record"),
    (b'{"id":{}}', "nested_or_non_object_record"),
    (b'[{"id":1}]', "nested_or_non_object_record"),
    (b'{"id":"\\ud800"}', "non_scalar_unicode"),
    (b'{"id":1,"\\udfff":null}', "non_scalar_unicode"),
    (b'{"id":"\xff"}', "invalid_utf8"),
    (b'{"id":1}\n\n', "record_line_bound"),
    (b'\n{"id":1}', "record_line_bound"),
    (b' ', "invalid_json_record"),
    (b'', "record_bytes_bound"),
    (b'{"id":1} {"id":2}', "nested_or_non_object_record"),
    (b'{"id":1,}', "invalid_json_record"),
])
def test_unsupported_or_ambiguous_input_is_rejected_by_synthesis_and_checker(source, reason):
    assert_rejected(lambda: p.synthesize_finite_record_projection(source, RENAME), reason)
    assert_rejected(lambda: p.check_finite_record_projection(source, RENAMED, RENAME), reason)


@pytest.mark.parametrize("payload", [b'{"id":' + b'[' * 20000 + b'0' + b']' * 20000 + b'}',
                                    b'{"id":' + b'{"x":' * 10000 + b'0' + b'}' * 10001])
def test_nested_bombs_rejected_before_recursive_json_decoder(payload, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("nested input reached the JSON decoder")
    monkeypatch.setattr(p.json, "loads", forbidden)
    assert_rejected(lambda: p.synthesize_finite_record_projection(payload, RENAME),
                    "nested_or_non_object_record")


@pytest.mark.parametrize("value", [bytearray(INPUT), memoryview(INPUT), INPUT.decode(), None, 1])
def test_byte_boundary_rejects_coercion(value):
    assert_rejected(lambda: p.synthesize_finite_record_projection(value, RENAME), "exact_bytes_required")
    assert_rejected(lambda: p.check_finite_record_projection(INPUT, value, RENAME), "exact_bytes_required")


@pytest.mark.parametrize("field,value", [
    ("mode", "filter"), ("mode", None), ("mode", True),
    ("source_field", "id\n"), ("source_field", "a.b"), ("source_field", "é"),
    ("source_field", ""), ("source_field", 1), ("source_field", "a" * 65),
    ("target_field", "id"), ("target_field", "../key"),
])
def test_contract_rejects_unsupported_or_ambiguous_operations(field, value):
    args = {"mode": "rename", "source_field": "id", "target_field": "key"}
    args[field] = value
    assert_rejected(lambda: p.FiniteRecordProjectionContract(**args))


def test_contract_frozen_closed_and_completely_content_bound():
    assert p.FiniteRecordProjectionContract.from_dict(RENAME.to_dict()) == RENAME
    assert RENAME.cid == cid_for_structured(RENAME.to_dict())
    assert replace(RENAME, mode="copy").cid != RENAME.cid
    assert replace(RENAME, target_field="label").cid != RENAME.cid
    with pytest.raises(FrozenInstanceError):
        RENAME.mode = "copy"
    for mutation in ({"extra": True}, {"mode": "filter"}, {"schema": "unknown"},
                     {"bounds": {}}, {"record_policy": {}}, {"correspondence_policy": "unordered"}):
        assert_rejected(lambda: p.FiniteRecordProjectionContract.from_dict({**RENAME.to_dict(), **mutation}))
    cyclic = RENAME.to_dict()
    cyclic["bounds"] = cyclic
    assert_rejected(lambda: p.FiniteRecordProjectionContract.from_dict(cyclic))


def test_exact_bounds_are_enforced_and_boundaries_are_admitted():
    source = ndjson([{"id": 0, "x": "a" * p.MAX_STRING_BYTES}])
    assert p.check_finite_record_projection(source, p.synthesize_finite_record_projection(source, RENAME),
                                           RENAME)["record_count"] == 1
    assert_rejected(lambda: p.synthesize_finite_record_projection(
        ndjson([{"id": "a" * (p.MAX_STRING_BYTES + 1)}]), RENAME), "record_string_bound")
    assert_rejected(lambda: p.synthesize_finite_record_projection(
        ndjson([{"id": 0, "a" * (p.MAX_KEY_BYTES + 1): 1}]), RENAME), "record_key_bound")
    many_fields = {"id": 1, **{f"x{i}": i for i in range(p.MAX_FIELDS - 1)}}
    at_bound = ndjson([many_fields])
    assert p.check_finite_record_projection(at_bound, p.synthesize_finite_record_projection(at_bound, RENAME),
                                           RENAME)["checked_scalar_count"] == p.MAX_FIELDS
    assert_rejected(lambda: p.synthesize_finite_record_projection(at_bound, COPY),
                    "projected_record_field_bound")
    assert_rejected(lambda: p.synthesize_finite_record_projection(
        ndjson([{**many_fields, "extra": 1}]), RENAME), "record_field_bound")
    max_rows = b'{"id":1}\n' * p.MAX_RECORDS
    assert p.check_finite_record_projection(max_rows, p.synthesize_finite_record_projection(max_rows, RENAME),
                                           RENAME)["record_count"] == p.MAX_RECORDS
    assert_rejected(lambda: p.synthesize_finite_record_projection(max_rows + b'{"id":1}\n', RENAME),
                    "record_count_bound")
    assert_rejected(lambda: p.synthesize_finite_record_projection(b" " * (p.MAX_BYTES + 1), RENAME),
                    "record_bytes_bound")
    assert_rejected(lambda: p.synthesize_finite_record_projection(b" " * (p.MAX_LINE_BYTES + 1), RENAME),
                    "record_line_bound")


def test_output_growth_is_bounded_before_returning_candidate():
    # Input is within the byte budget but adding a copy would exceed it.
    source = ndjson([{"id": "x" * 10000, "other": "z" * 10000}] * 40)
    assert len(source) < p.MAX_BYTES
    assert_rejected(lambda: p.synthesize_finite_record_projection(source, COPY),
                    "projected_record_bytes_bound")


@pytest.mark.parametrize("field,value", [
    ("input_sha256", "0" * 64), ("output_sha256", "0" * 64),
    ("contract_cid", "forged"), ("record_count", 1), ("record_count", True),
    ("proof_authority", True), ("status", "proved"), ("receipt_cid", "forged"),
    ("checker_provenance", {}), ("scope", "all programs"), ("extra", "forged"),
])
def test_forged_or_stale_receipt_never_replays_even_with_recomputed_cid(field, value):
    original = p.check_finite_record_projection(INPUT, RENAMED, RENAME)
    changed = {**original, field: value}
    if field != "receipt_cid":
        changed["receipt_cid"] = cid_for_structured({k: v for k, v in changed.items() if k != "receipt_cid"})
    assert_rejected(lambda: p.verify_finite_record_check(changed, input_bytes=INPUT,
                    output_bytes=RENAMED, contract=RENAME), "finite_record_check_binding_mismatch")


@pytest.mark.parametrize("change", ["input_bytes", "output_bytes", "contract", "checker"])
def test_every_current_binding_is_rechecked_before_replay(change, monkeypatch):
    receipt = p.check_finite_record_projection(INPUT, RENAMED, RENAME)
    args = {"input_bytes": INPUT, "output_bytes": RENAMED, "contract": RENAME}
    if change in {"input_bytes", "output_bytes"}:
        args[change] = args[change].replace(b'{', b'{ ', 1)
    elif change == "contract":
        args["contract"] = COPY
        args["output_bytes"] = COPIED
    else:
        changed = deepcopy(receipt["checker_provenance"])
        changed["sources"][0]["sha256"] = "0" * 64
        monkeypatch.setattr(p, "_checker_provenance", lambda: changed)
    assert_rejected(lambda: p.verify_finite_record_check(receipt, **args),
                    "finite_record_check_binding_mismatch")


def test_receipt_cannot_replace_reexecution(monkeypatch):
    receipt = p.check_finite_record_projection(INPUT, RENAMED, RENAME)
    calls = []
    original = p.check_finite_record_projection
    def check(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(p, "check_finite_record_projection", check)
    assert_rejected(lambda: p.verify_finite_record_check(receipt, input_bytes=INPUT,
                    output_bytes=RENAMED.replace(b'"Ada"', b'"Wrong"'), contract=RENAME),
                    "record_scalar_correspondence_mismatch")
    assert calls == [True]
