"""Current wrapped records remain exact observations, never accepted graphs."""
import base64
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_primary_graph_records as records

ENTRY = "sha256:" + "1" * 64
SOURCE = "sha256:" + "2" * 64
TARGET = "sha256:" + "3" * 64


def fixture(family="graph_nodes", *, body=None, encoded=None):
    if body is None:
        body = ({"entry_cid": ENTRY, "family": family, "legal_id": None,
                 "node_type": "source_package", "label": "A label", "node_key": "source:literal"}
                if family == "graph_nodes" else
                {"entry_cid": ENTRY, "family": family, "source_entry_cid": SOURCE,
                 "target_entry_cid": TARGET, "edge_type": "CONTAINS", "edge_class": "structural",
                 "resolution_status": None})
    encoded = encoded if encoded is not None else json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    row = {"entry_cid": body.get("entry_cid") or "", "legal_id": body.get("legal_id") or "",
           "family": family, "record_sha256": hashlib.sha256(encoded.encode()).hexdigest(), "record_json": encoded}
    custody = {"repository": "justicedao/ipfs_uscode", "revision": "a" * 40,
        "manifest_sha256": "b" * 64, "selection_sha256": "c" * 64,
        "release_root_cid": "sha256:" + "d" * 64, "source_revision": "e" * 40,
        "family": family, "shard_path": "data/graph/" + ("nodes" if family == "graph_nodes" else "edges") + "/part-000000.parquet",
        "file_sha256": "f" * 64, "file_bytes": 1000, "file_row_count": 4,
        "row_ordinal": 1, "row_group": 0, "row_group_ordinal": 1}
    return row, custody


def trusted(row, custody):
    return {"custody": custody, "expected_raw_row_sha256": records.raw_row_sha256(row),
            "expected_custody_sha256": records.custody_sha256(custody)}


def decode(row, custody):
    return records.decode_primary_graph_record(row, **trusted(row, custody))


def codes(report):
    return {issue["code"] for issue in report["issues"]}


@pytest.mark.parametrize("family", ["graph_nodes", "graph_edges"])
@pytest.mark.parametrize("malformed", [False, True])
def test_payload_observation_preserves_decoder_fields_without_fabricating_custody(family, malformed):
    row, custody = fixture(family, encoded="{broken" if malformed else None)
    row["opaque_wrapper"] = {"observed": ["café", None, 3]}
    payload = records.decode_primary_graph_payload(row, family=family,
        expected_raw_row_sha256=records.raw_row_sha256(row))
    physical = decode(row, custody)
    assert payload["schema"] == records.PAYLOAD_SCHEMA != physical["schema"]
    assert payload["coverage_scope"] == "pinned_payload_only_no_physical_custody"
    assert "custody" not in payload and "custody_sha256" not in payload
    assert all(value is False for value in payload["authority"].values())
    assert {key: value for key, value in payload.items()
            if key not in {"schema", "coverage_scope", "envelope_sha256"}} == {
        key: value for key, value in physical.items()
        if key not in {"schema", "coverage_scope", "envelope_sha256", "custody", "custody_sha256"}}
    with pytest.raises(records.PrimaryGraphRecordError, match="exact pinned regeneration"):
        records.validate_primary_graph_record(payload, row, **trusted(row, custody))


def test_payload_pin_mismatch_and_unsupported_family_cannot_decode_a_different_observation():
    row, _ = fixture()
    with pytest.raises(records.PrimaryGraphRecordError, match="pinned raw graph row differs"):
        records.decode_primary_graph_payload(row, family="graph_nodes", expected_raw_row_sha256="0" * 64)
    with pytest.raises(records.PrimaryGraphRecordError, match="supported graph family"):
        records.decode_primary_graph_payload(row, family="legacy_nodes",
            expected_raw_row_sha256=records.raw_row_sha256(row))


@pytest.mark.parametrize("family", ["graph_nodes", "graph_edges"])
def test_current_wrapper_decodes_literal_ids_without_semantic_authority(family):
    row, custody = fixture(family)
    report = decode(row, custody)
    assert report["disposition"] == ("decoded_unreviewed_node" if family == "graph_nodes" else "decoded_unreviewed_edge")
    assert report["declared_identity"] == {"entry_cid": ENTRY, "source_entry_cid": SOURCE if family == "graph_edges" else None,
                                          "target_entry_cid": TARGET if family == "graph_edges" else None}
    assert report["raw_row"] == row and report["custody"] == custody
    assert report["record_sha256_verified"] is True
    assert all(value is False for value in report["authority"].values())
    assert report["legal_id"] is None


def test_original_record_bytes_whitespace_unicode_escapes_and_unknown_fields_are_lossless():
    body = {"entry_cid": ENTRY, "family": "graph_nodes", "node_type": "term", "legal_id": "usc:us:10:1",
            "label": "café", "future_field": {"ordered": [3, None, "é", 3], "legacy": True}}
    encoded = " \n" + json.dumps(body, ensure_ascii=True, indent=2) + "\t"
    row, custody = fixture(body=body, encoded=encoded)
    row["future_wrapper"] = {"preserved": [True, None, "é"]}
    report = decode(row, custody)
    assert report["record_json"] == encoded
    assert base64.b64decode(report["record_json_utf8_base64"]) == encoded.encode()
    assert report["original_body"] == body and report["raw_row"] == row
    assert report["record_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
    normalized_row, _ = fixture(body=body)
    assert records.raw_row_sha256(normalized_row) != report["raw_row_sha256"]
    assert report["disposition"] == "decoded_unreviewed_node"


@pytest.mark.parametrize("legal_id", [None, "", "usc:us:10:1"])
def test_optional_legal_id_transport_parity_preserves_original_body_value(legal_id):
    row, custody = fixture()
    body = json.loads(row["record_json"])
    body["legal_id"] = legal_id
    row, custody = fixture(body=body)
    report = decode(row, custody)
    assert report["disposition"] == "decoded_unreviewed_node"
    assert report["original_body"]["legal_id"] == legal_id
    assert report["raw_row"]["legal_id"] == (legal_id or "")


def test_materialized_wrapper_endpoint_field_cannot_override_body_endpoint():
    row, custody = fixture("graph_edges")
    row["source_entry_cid"] = TARGET
    report = decode(row, custody)
    assert "endpoint_parity_mismatch" in codes(report)
    assert report["disposition"] == "unresolved" and report["raw_row"] == row


@pytest.mark.parametrize("field", ["family", "entry_cid", "legal_id", "record_sha256"])
def test_wrapper_body_parity_or_original_byte_hash_tampering_stays_unresolved(field):
    row, custody = fixture()
    row[field] = {"family": "graph_edges", "entry_cid": SOURCE, "legal_id": "usc:us:10:2",
                  "record_sha256": "0" * 64}[field]
    report = decode(row, custody)
    assert report["disposition"] == "unresolved"
    assert all(value is None for value in report["declared_identity"].values())
    assert report["raw_row"] == row


@pytest.mark.parametrize("encoded", ['{"x":1,"x":2}', '{"nested":{"x":1,"x":2}}',
    '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}', '{broken', '[1,2]', 'null'])
def test_duplicate_nonfinite_malformed_or_nonobject_body_is_retained_unresolved(encoded):
    row, custody = fixture(encoded=encoded)
    report = decode(row, custody)
    assert report["disposition"] == "unresolved"
    assert report["record_json"] == encoded
    assert base64.b64decode(report["record_json_utf8_base64"]) == encoded.encode()
    assert report["record_sha256_verified"] is True
    assert all(value is None for value in report["declared_identity"].values())


@pytest.mark.parametrize("missing", ["entry_cid", "source_entry_cid", "target_entry_cid"])
def test_missing_explicit_edge_identities_never_use_labels_or_positional_fallback(missing):
    row, custody = fixture("graph_edges")
    body = json.loads(row["record_json"])
    body.pop(missing)
    body.update(label="same label", legal_id="usc:us:10:1")
    row, custody = fixture("graph_edges", body=body)
    report = decode(row, custody)
    assert "missing_" + missing in codes(report)
    assert all(value is None for value in report["declared_identity"].values())
    assert report["original_body"] == body


@pytest.mark.parametrize("alias", ["edge_cid", "src", "source_node_cid", "dst", "target_node_cid"])
def test_conflicting_identity_aliases_cannot_be_chosen(alias):
    row, custody = fixture("graph_edges")
    body = json.loads(row["record_json"])
    body[alias] = "sha256:" + "9" * 64
    row, custody = fixture("graph_edges", body=body)
    report = decode(row, custody)
    assert "conflicting_identity_alias" in codes(report)
    assert report["disposition"] == "unresolved"


def test_agreeing_legacy_alias_remains_observed_without_becoming_an_identity_source():
    row, custody = fixture()
    body = json.loads(row["record_json"])
    body["node_cid"] = ENTRY
    row, custody = fixture(body=body)
    assert decode(row, custody)["disposition"] == "decoded_unreviewed_node"
    body.pop("entry_cid")
    row, custody = fixture(body=body)
    report = decode(row, custody)
    assert {"missing_entry_cid", "unsupported_identity_alias"} <= codes(report)
    assert report["declared_identity"]["entry_cid"] is None


@pytest.mark.parametrize("origin", ["body", "wrapper"])
def test_explicit_unknown_version_never_selects_another_graph_layout(origin):
    row, custody = fixture()
    if origin == "body":
        body = json.loads(row["record_json"])
        body["schema_version"] = "uscode-sparse-graphrag-release-schema-v2"
        row, custody = fixture(body=body)
    else:
        row["schema_version"] = "future-graph/v9000"
    report = decode(row, custody)
    assert "unsupported_graph_schema_version" in codes(report)
    assert report["disposition"] == "unresolved"


def test_physical_occurrences_are_distinct_without_text_or_identity_deduplication():
    row, custody = fixture()
    first = decode(row, custody)
    second_custody = {**custody, "row_ordinal": 2, "row_group_ordinal": 2}
    second = decode(row, second_custody)
    assert first["record_sha256"] == second["record_sha256"]
    assert first["raw_row_sha256"] == second["raw_row_sha256"]
    assert first["envelope_sha256"] != second["envelope_sha256"]
    assert first["declared_identity"] == second["declared_identity"]


def test_independent_raw_row_and_manifest_file_ordinal_pins_reject_retargeting():
    row, custody = fixture()
    args = trusted(row, custody)
    for field, value in (("manifest_sha256", "0" * 64), ("file_sha256", "0" * 64),
                         ("row_ordinal", 2), ("revision", "9" * 40)):
        moved = deepcopy(custody)
        moved[field] = value
        with pytest.raises(ValueError, match="pinned physical graph custody"):
            records.decode_primary_graph_record(row, **{**args, "custody": moved})
    row["future_wrapper"] = "changed"
    with pytest.raises(ValueError, match="pinned raw graph row"):
        records.decode_primary_graph_record(row, **args)


def test_regeneration_rejects_resealed_identity_or_authority_promotion():
    row, custody = fixture()
    args = trusted(row, custody)
    report = records.decode_primary_graph_record(row, **args)
    assert records.validate_primary_graph_record(report, row, **args) == report
    report["declared_identity"]["entry_cid"] = SOURCE
    report["authority"]["admitted"] = True
    report["envelope_sha256"] = hashlib.sha256(records._wire({key: value for key, value in report.items()
                                                             if key != "envelope_sha256"})).hexdigest()
    with pytest.raises(ValueError, match="exact pinned regeneration"):
        records.validate_primary_graph_record(report, row, **args)


@pytest.mark.parametrize("value", ["row-12", " " + ENTRY, ENTRY.upper(), "same display label"])
def test_invalid_or_noncanonical_identity_is_never_normalized(value):
    row, custody = fixture()
    body = json.loads(row["record_json"])
    body["entry_cid"] = value
    row, custody = fixture(body=body)
    report = decode(row, custody)
    assert "invalid_entry_cid" in codes(report)
    assert report["original_body"]["entry_cid"] == value
    assert report["disposition"] == "unresolved"


def test_legacy_flags_missing_wrapper_and_absent_legal_id_cannot_confer_authority():
    row, custody = fixture("graph_edges")
    row.update(admitted=True, formalized=True)
    report = decode(row, custody)
    assert report["disposition"] == "decoded_unreviewed_edge"
    assert report["legal_id"] is None and report["authority"]["admitted"] is False
    row.pop("record_json")
    report = decode(row, custody)
    assert report["record_json"] is None and report["record_sha256"] is None
    assert report["disposition"] == "unresolved" and report["raw_row"] == row


def test_finite_byte_bounds_and_plain_json_custody_raise_without_truncation(monkeypatch):
    row, custody = fixture()
    args = trusted(row, custody)
    monkeypatch.setattr(records, "MAX_ROW_BYTES", 20)
    with pytest.raises(ValueError, match="byte bound"):
        records.decode_primary_graph_record(row, **args)
    with pytest.raises(ValueError, match="finite"):
        records.raw_row_sha256({"metric": float("nan")})
    with pytest.raises(ValueError, match="plain JSON"):
        records.raw_row_sha256({"unknown": {1: "key would be coerced"}})
