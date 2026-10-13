"""Identity and refusal properties independent of corpus semantics."""
import hashlib
import json

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as c
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes
from multiformats import CID


def test_seal_uses_declared_scope_and_exact_canonical_bytes():
    record = c.seal_record({"schema": "example/v1", "value": ["é", 3]})
    body = {key: value for key, value in record.items() if key != "record_cid"}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert bytes(CID.decode(record["record_cid"]).raw_digest) == hashlib.sha256(raw).digest()
    assert c.validate_record(record, schema="example/v1", fields={"value"}) == record


def test_input_key_order_does_not_change_record_identity_and_lists_keep_order():
    first = c.seal_record({"schema": "example/v1", "value": ["a", "b"]})
    assert first == c.seal_record({"value": ["a", "b"], "schema": "example/v1"})
    assert first["record_cid"] != c.seal_record({"schema": "example/v1", "value": ["b", "a"]})["record_cid"]


def test_results_do_not_alias_caller_nested_objects():
    payload = {"schema": "example/v1", "value": {"items": [1]}}
    record = c.seal_record(payload)
    payload["value"]["items"].append(2)
    result = c.validate_record(record, schema="example/v1", fields={"value"})
    result["value"]["items"].append(3)
    assert record["value"]["items"] == [1]


def test_json_content_preserves_whitespace_strings_without_normalizing_them():
    record = c.seal_record({"schema": "example/v1", "value": [" ", "\n\t", ""]})
    assert c.validate_record(record, schema="example/v1", fields={"value"})["value"] == [" ", "\n\t", ""]
    with pytest.raises(c.CorpusContractError):
        c.require_text(" ", "schema metadata")


@pytest.mark.parametrize("change", ["payload", "scope", "extra", "schema", "raw_cid"])
def test_identity_and_shape_tampering_refuse(change):
    record = c.seal_record({"schema": "example/v1", "value": 1})
    if change == "payload":
        record["value"] = 2
    elif change == "scope":
        record["cid_scope"] = "different"
    elif change == "extra":
        record["unknown"] = 0
    elif change == "schema":
        record["schema"] = "other/v1"
    else:
        record["record_cid"] = cid_for_bytes(b"not a structured record")
    with pytest.raises(c.CorpusContractError):
        c.validate_record(record, schema="example/v1", fields={"value"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "bad key"}, (1,), object(), "\ud800", "\x00"])
def test_noncanonical_values_refuse(value):
    with pytest.raises(c.CorpusContractError):
        c.seal_record({"schema": "example/v1", "value": value})


def test_depth_nodes_and_aggregate_byte_bounds(monkeypatch):
    monkeypatch.setattr(c, "MAX_JSON_DEPTH", 3)
    with pytest.raises(c.CorpusContractError):
        c.clone_json([[[[[0]]]]])
    monkeypatch.setattr(c, "MAX_JSON_NODES", 3)
    with pytest.raises(c.CorpusContractError):
        c.clone_json([0, 0, 0])
    monkeypatch.setattr(c, "MAX_JSON_NODES", 100)
    monkeypatch.setattr(c, "MAX_RECORD_BYTES", 100)
    with pytest.raises(c.CorpusContractError):
        c.clone_json(["x" * 60, "y" * 60])


def test_cyclic_input_refuses_without_recursion_overflow():
    value = []
    value.append(value)
    with pytest.raises(c.CorpusContractError):
        c.clone_json(value)


@pytest.mark.parametrize("value", [True, 1.0, "1", -1])
def test_integer_contract_never_coerces(value):
    with pytest.raises(c.CorpusContractError):
        c.require_int(value, "offset")


def test_raw_cid_digest_must_match_independent_expected_hash():
    cid = cid_for_bytes(b"source")
    assert c.require_cid_sha256(cid, hashlib.sha256(b"source").hexdigest(), "source") == cid
    with pytest.raises(c.CorpusContractError):
        c.require_cid_sha256(cid, hashlib.sha256(b"other").hexdigest(), "source")


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'\xff'])
def test_digest_bound_loader_rejects_ambiguous_or_invalid_json(raw):
    with pytest.raises(c.CorpusContractError):
        c.load_record_bytes(raw, expected_sha256=hashlib.sha256(raw).hexdigest())


def test_loader_checks_bytes_not_only_parsed_values():
    raw = b'{"a":1}'
    assert c.load_record_bytes(raw, expected_sha256=hashlib.sha256(raw).hexdigest()) == {"a": 1}
    with pytest.raises(c.CorpusContractError):
        c.load_record_bytes(b'{ "a": 1 }', expected_sha256=hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("field", ["record_cid", "cid_scope"])
def test_builders_do_not_accept_caller_owned_seal_fields(field):
    with pytest.raises(c.CorpusContractError):
        c.seal_record({"schema": "example/v1", field: "forged"})
