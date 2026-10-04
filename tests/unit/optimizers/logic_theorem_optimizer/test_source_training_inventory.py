"""Bounded local inventory is evidence of bytes/shape, never eligibility."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts/ops/autoencoder/audit_source_training_inventory.py"
spec = importlib.util.spec_from_file_location("source_training_inventory_script", SCRIPT)
inventory = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = inventory
spec.loader.exec_module(inventory)


def declaration(path="rows.jsonl", **kwargs):
    return dict(artifact_id="rows", domain_id="legal_ir", path=str(path), format="jsonl",
                declared_role="rows", declared_source_kind="real_source", **kwargs)


def audit(tmp_path, *entries, limits=None):
    return inventory.audit_inventory({"schema": inventory.SPEC_SCHEMA, "artifacts": list(entries)},
                                     base_directory=tmp_path, limits=limits)


def test_streamed_identity_and_presence_do_not_grant_authority(tmp_path):
    raw = b'{"text":"caf\\u00e9","embedding_vector":[1,2],"qualified":true}\n{"text":"","embedding_vector":[]}\n'
    (tmp_path / "rows.jsonl").write_bytes(raw)
    report = audit(tmp_path, declaration(record_fields=["/text", "/embedding_vector", "/missing", "/qualified"]))
    row = report["artifacts"][0]
    assert row["status"] == "available"
    assert row["content_sha256"] == hashlib.sha256(raw).hexdigest()
    assert row["observed_record_count"] == 2
    assert row["record_count_complete"] is True
    assert row["field_presence"]["/embedding_vector"] == {"present_rows": 2, "nonempty_rows": 1}
    assert row["field_presence"]["/missing"] == {"present_rows": 0, "nonempty_rows": 0}
    assert report["bytes_read"] == len(raw)
    assert set(report["domains"]) == set(inventory.DOMAINS)
    assert report["domains"]["ui_ux_ir"]["artifact_count"] == 0
    for flag in ("eligibility_granted", "qualified", "admitted", "training_executed", "native_checks_executed", "embedding_producer_authenticated", "source_semantics_verified"):
        assert report[flag] is False
    assert "café" not in json.dumps(report, ensure_ascii=False)


def test_json_pointer_schema_and_false_claims_are_inert(tmp_path):
    value = {"schema": "autoencoder-domain-targets/v1", "qualified": True, "admitted": True,
             "ready_for_training": True, "outer": {"a/b": [{"a~b": "secret marker"}]}}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value))
    entry = declaration(path, records_pointer="/outer/a~1b", record_fields=["/a~0b"])
    entry["format"] = "json"
    row = audit(tmp_path, entry)["artifacts"][0]
    assert row["observed_schema"] == value["schema"]
    assert row["field_presence"] == {"/a~0b": {"present_rows": 1, "nonempty_rows": 1}}
    assert row["readiness_assessed"] is False and row["evidence_verified"] is False
    assert "secret marker" not in json.dumps(row)


def test_no_references_followed_or_source_executed(tmp_path):
    value = {"source_artifacts": [{"path": str(tmp_path / "not-read") }],
             "python": "raise RuntimeError('do not execute')"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value))
    entry = declaration(path)
    entry["format"] = "json"
    report = audit(tmp_path, entry)
    assert report["all_declared_artifacts_available"] is True
    assert "observed_record_count" not in report["artifacts"][0]


@pytest.mark.parametrize("raw,reason", [(b'{"x":1,"x":2}\n', "invalid_json"),
    (b'{"x":NaN}\n', "invalid_json"), (b'{"x":1e1000}\n', "nonfinite_json"),
    (b'{bad}\n', "invalid_json"), (b'\n', "blank_jsonl_record"),
    (b'[]\n', "record_not_object"), (b'\xff\n', "invalid_json")])
def test_invalid_records_preserve_complete_artifact_hash_and_incomplete_count(tmp_path, raw, reason):
    raw = b'{"text":"first"}\n' + raw + b'{"text":"third"}\n'
    (tmp_path / "rows.jsonl").write_bytes(raw)
    row = audit(tmp_path, declaration())["artifacts"][0]
    assert row["status"] == "invalid" and row["reason"] == reason
    assert row["content_sha256"] == hashlib.sha256(raw).hexdigest()
    assert row["observed_record_count"] == 1 and row["record_count_complete"] is False


@pytest.mark.parametrize("case", ["missing", "directory", "symlink", "fifo"])
def test_unavailable_file_kinds_fail_without_blocking(tmp_path, case):
    path = tmp_path / "rows.jsonl"
    if case == "directory":
        path.mkdir()
    elif case == "symlink":
        target = tmp_path / "target"
        target.write_text('{}\n')
        path.symlink_to(target)
    elif case == "fifo":
        os.mkfifo(path)
    row = audit(tmp_path, declaration())["artifacts"][0]
    assert row["status"] == ("missing" if case == "missing" else "unavailable")
    assert row["bytes_read"] == 0 and row["content_sha256"] is None


@pytest.mark.parametrize("bound,value,raw,format,reason", [
    ("max_file_bytes", 1, b'{}\n', "jsonl", "file_or_total_byte_limit_exceeded"),
    ("max_total_bytes", 1, b'{}\n', "jsonl", "file_or_total_byte_limit_exceeded"),
    ("max_json_bytes", 1, b'{}', "json", "json_byte_limit_exceeded"),
    ("max_record_bytes", 2, b'{}\n', "jsonl", "record_byte_limit_exceeded"),
    ("max_records", 1, b'{}\n{}\n', "jsonl", "record_limit_exceeded"),
    ("max_json_depth", 1, b'{"a":{"b":1}}', "json", "json_shape_limit_exceeded"),
    ("max_json_nodes", 1, b'{"a":1}', "json", "json_shape_limit_exceeded"),
])
def test_explicit_resource_limits(tmp_path, bound, value, raw, format, reason):
    (tmp_path / "rows.jsonl").write_bytes(raw)
    entry = declaration()
    entry["format"] = format
    row = audit(tmp_path, entry, limits=inventory.Limits(**{bound: value}))["artifacts"][0]
    assert row["reason"] == reason
    assert row["status"] != "available"


def test_total_budget_accounts_for_prior_artifacts(tmp_path):
    (tmp_path / "first").write_bytes(b'{}\n')
    (tmp_path / "second").write_bytes(b'{}\n')
    first, second = declaration("first"), declaration("second")
    second["artifact_id"] = "second"
    report = audit(tmp_path, first, second, limits=inventory.Limits(max_total_bytes=5))
    assert [row["status"] for row in report["artifacts"]] == ["available", "unavailable"]
    assert report["bytes_read"] == 3


def test_expected_digest_is_checked_not_assumed(tmp_path):
    raw = b'{}\n'
    (tmp_path / "rows.jsonl").write_bytes(raw)
    bad = audit(tmp_path, declaration(expected_sha256="0" * 64))["artifacts"][0]
    good = audit(tmp_path, declaration(expected_sha256=hashlib.sha256(raw).hexdigest()))["artifacts"][0]
    assert bad["expected_sha256_match"] is False and bad["status"] == "invalid"
    assert good["expected_sha256_match"] is True and good["status"] == "available"
    assert good["evidence_verified"] is False


@pytest.mark.parametrize("patch", [{"unknown": True}, {"domain_id": "unknown"},
    {"declared_source_kind": "verified"}, {"declared_role": "admit"},
    {"expected_sha256": "SHA"}, {"record_fields": ["/x", "/x"]},
    {"record_fields": ["/a~bad"]}, {"records_pointer": "/rows"}, {"path": ""},
    {"artifact_id": "contains spaces"}, {"format": []}, {"declared_role": {}}, {"domain_id": []}])
def test_closed_spec_rejects_invalid_declarations_before_reads(tmp_path, patch):
    entry = declaration()
    entry.update(patch)
    with pytest.raises(inventory.InventoryError):
        audit(tmp_path, entry)


def test_duplicate_ids_and_artifact_limit_rejected(tmp_path):
    with pytest.raises(inventory.InventoryError, match="duplicate"):
        audit(tmp_path, declaration(), declaration())
    second = declaration()
    second["artifact_id"] = "other"
    with pytest.raises(inventory.InventoryError, match="artifact count"):
        audit(tmp_path, declaration(), second, limits=inventory.Limits(max_artifacts=1))


def test_mutation_during_read_is_not_hashed_as_stable_evidence(tmp_path, monkeypatch):
    path = tmp_path / "rows.jsonl"
    path.write_bytes(b'{}\n')
    actual = inventory.hashlib.sha256
    class RacingDigest:
        def __init__(self):
            self.digest = actual()
        def update(self, raw):
            self.digest.update(raw)
            path.write_bytes(b'[]\n')
        def hexdigest(self):
            return self.digest.hexdigest()
    monkeypatch.setattr(inventory.hashlib, "sha256", RacingDigest)
    row = audit(tmp_path, declaration())["artifacts"][0]
    assert row["status"] == "unavailable" and row["reason"] == "changed_during_read"
    assert row["content_sha256"] is None


def test_cli_pins_spec_and_never_overwrites(tmp_path, capsys):
    (tmp_path / "rows.jsonl").write_text('{}\n')
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"schema": inventory.SPEC_SCHEMA, "artifacts": [declaration()]}))
    output = tmp_path / "out.json"
    assert inventory.main(["--spec", str(spec), "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["spec_sha256"] == hashlib.sha256(spec.read_bytes()).hexdigest()
    original = output.read_bytes()
    with pytest.raises(inventory.InventoryError, match="fresh"):
        inventory.main(["--spec", str(spec), "--output", str(output)])
    assert output.read_bytes() == original


def test_empty_opaque_file_has_no_inferred_rows(tmp_path):
    path = tmp_path / "source"
    path.write_bytes(b'')
    entry = declaration(path)
    entry["format"] = "opaque"
    row = audit(tmp_path, entry)["artifacts"][0]
    assert row["status"] == "available"
    assert row["content_sha256"] == hashlib.sha256(b'').hexdigest()
    assert "observed_record_count" not in row


def test_cli_explicit_limit_override_is_retained_and_enforced(tmp_path):
    (tmp_path / "rows.jsonl").write_bytes(b'{}\n{}\n')
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"schema": inventory.SPEC_SCHEMA, "artifacts": [declaration()]}))
    output = tmp_path / "report.json"
    assert inventory.main(["--spec", str(spec), "--output", str(output), "--max-records", "1"]) == 2
    report = json.loads(output.read_text())
    assert report["limits"]["max_records"] == 1
    assert report["artifacts"][0]["reason"] == "record_limit_exceeded"
    with pytest.raises(inventory.InventoryError, match="invalid bound"):
        inventory.main(["--spec", str(spec), "--output", str(tmp_path / "unused"), "--max-json-nodes", "999999999"])


def test_specification_is_also_a_bounded_regular_file(tmp_path):
    source = tmp_path / "spec.pipe"
    os.mkfifo(source)
    with pytest.raises(inventory.InventoryError, match="not_regular"):
        inventory.main(["--spec", str(source), "--output", str(tmp_path / "output")])
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(inventory.InventoryError, match="exceeds byte limit"):
        inventory.main(["--spec", str(oversized), "--output", str(tmp_path / "output")])
