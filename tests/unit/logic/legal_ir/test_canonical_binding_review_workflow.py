"""Verify recording file boundaries using synthetic declarations only."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_binding_review_workflow as workflow

ROOT = Path(workflow.__file__).resolve().parents[3]
CLI = ROOT / "scripts/ops/legal_ir/record_binding_reviews.py"


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def checksum(value):
    return hashlib.sha256(raw(value)).hexdigest()


def expected_counts(status):
    return {name: int(name == status) for name in (
        "pending", "single_review", "agreed_multiple_reviews", "disputed", "ambiguous", "unsupported")}


@pytest.fixture
def tmp_path(tmp_path_factory):
    # The existing exposed-input scope heuristic rejects components beginning
    # with "test_"; neutral temporary paths let these tests reach each boundary.
    return tmp_path_factory.mktemp("binding-recording")


@pytest.fixture
def packet():
    source = "The clerk must retain the filing."
    context = dict(role="none_required", text="", bindings={}, sha256=hashlib.sha256(b"").hexdigest())
    input_hash = checksum(dict(source_text=source, context=context))
    identity = "binding-review-item-" + hashlib.sha256(
        b"authored-binding-review-v1\0" + bytes.fromhex(input_hash)).hexdigest()[:24]
    return dict(schema="symbol-binding-source-reviewer/v1",
        instructions={key: "Synthetic test instructions" for key in (
            "task", "context", "normative_rules", "qualifier_scope", "blank_annotations", "identity", "provenance")},
        items=[dict(item_id=identity, source_text=source, source_sha256=hashlib.sha256(source.encode()).hexdigest(),
            input_sha256=input_hash, context=context, annotation={key: None for key in (
                "interpretation_status", "ambiguity", "unsupported_meaning", "normative_rules",
                "freeform_qualifier_scope", "notes", "reviewer_id", "reviewed_at_utc")})])


def write_file(path, value):
    data = raw(value)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def invoke(tmp_path, packet, submissions=None):
    path = tmp_path / "reviewer.json"
    pin = write_file(path, packet)
    directory = tmp_path / "recording"
    return workflow.run_binding_review_recording(path, pin, submissions or [], directory), directory


def test_zero_submission_publishes_private_pending_receipt(tmp_path, packet):
    report, directory = invoke(tmp_path, packet)
    assert report["submission_count"] == 0 and report["status_counts"] == expected_counts("pending")
    assert report["reviewer_packet_sha256"] == checksum(packet)
    assert report["packet_binding"]["sha256"] == hashlib.sha256((tmp_path / "reviewer.json").read_bytes()).hexdigest()
    assert report["completed_independent_reviews"] == 0
    assert report["source_only_packet"] is True
    assert report["organizer_manifest_accessed"] is report["candidate_or_reference_accessed"] is False
    assert len(report["source_bindings"]) == 5 and report["complete_dependency_manifest"] is False
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for filename in ("report_private.json", "receipt_private.json", "submission_guide.json"):
        assert stat.S_IMODE((directory / filename).stat().st_mode) == 0o600
    saved = json.loads((directory / "report_private.json").read_bytes())
    assert saved == report and saved["content_sha256"] == checksum({k: v for k, v in saved.items() if k != "content_sha256"})
    receipt = json.loads((directory / "receipt_private.json").read_bytes())
    assert all(value == 0 for value in receipt["items"][0]["masks"].values())


def test_synthetic_complete_declaration_cannot_admit_supervision(tmp_path, packet):
    submitted = copy.deepcopy(packet)
    submitted["items"][0]["annotation"] = dict(
        interpretation_status="normative", ambiguity=False, unsupported_meaning=False,
        normative_rules=[dict(modality="O", actor="clerk", action="retain", object="filing",
                              conditions=[], exceptions=[], temporal=[])],
        freeform_qualifier_scope="", notes="Synthetic fixture only", reviewer_id="synthetic-reviewer-A",
        reviewed_at_utc="2026-10-04T03:00:00Z")
    path = tmp_path / "synthetic-declaration.json"
    pin = write_file(path, submitted)
    report, directory = invoke(tmp_path, packet, [dict(path=str(path), sha256=pin)])
    assert report["submission_count"] == 1 and report["status_counts"] == expected_counts("single_review")
    assert report["actual_training_or_evaluation_admission"] is False
    row = json.loads((directory / "receipt_private.json").read_bytes())["items"][0]
    assert row["reviewer_identity_authenticated"] is False
    assert row["independent_adjudication_completed"] is False
    assert all(type(value) is int and value == 0 for value in row["masks"].values())


@pytest.mark.parametrize("data", [
    b'{"same":1,"same":2}', b'{"nested":{"same":1,"same":2}}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e999}',
    b'\xff', b'\xef\xbb\xbf{}', '{}'.encode("utf-16"), '{}'.encode("utf-32"),
])
def test_pinned_reader_rejects_nonordinary_or_non_utf8_json(tmp_path, data):
    path = tmp_path / "payload.json"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        workflow._read_pinned_json(path, hashlib.sha256(data).hexdigest())


def test_stale_pin_fails_before_output_creation(tmp_path, packet):
    path = tmp_path / "packet.json"
    write_file(path, packet)
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        workflow.run_binding_review_recording(path, "0" * 64, [], output)
    assert not output.exists()


@pytest.mark.parametrize("mode", ["leaf_symlink", "parent_symlink", "fifo", "oversized", "sealed_path"])
def test_reader_refuses_unsafe_file_boundaries(tmp_path, mode, packet):
    real = tmp_path / "payload.json"
    pin = write_file(real, packet)
    candidate = tmp_path / "candidate.json"
    if mode == "leaf_symlink":
        candidate.symlink_to(real)
    elif mode == "parent_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        candidate = alias / real.name
    elif mode == "fifo":
        os.mkfifo(candidate)
    elif mode == "oversized":
        with candidate.open("wb") as stream:
            stream.truncate(workflow.MAX_FILE_BYTES + 1)
    else:
        candidate = tmp_path / "sealed-payload.json"
        candidate.write_bytes(real.read_bytes())
    with pytest.raises((ValueError, OSError)):
        workflow._read_pinned_json(candidate, pin)


def test_canonical_root_and_fresh_output_are_required(tmp_path, packet):
    path = tmp_path / "packet.json"
    pin = write_file(path, packet)
    with pytest.raises(ValueError, match="executing canonical checkout"):
        workflow.run_binding_review_recording(path, pin, [], tmp_path / "output", repository_root=tmp_path)
    (tmp_path / "existing").mkdir()
    with pytest.raises(ValueError, match="fresh evidence"):
        workflow.run_binding_review_recording(path, pin, [], tmp_path / "existing")


def test_changed_input_is_refused_before_publication(tmp_path, packet, monkeypatch):
    from ipfs_datasets_py.logic.legal_ir import canonical_binding_review as adapter

    path = tmp_path / "packet.json"
    pin = write_file(path, packet)
    original = adapter.submission_guide

    def changed_after_replay():
        path.write_bytes(path.read_bytes() + b" ")
        return original()

    monkeypatch.setattr(adapter, "submission_guide", changed_after_replay)
    with pytest.raises(ValueError, match="changed during execution"):
        workflow.run_binding_review_recording(path, pin, [], tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_wrong_dependency_checkout_is_refused(tmp_path, packet, monkeypatch):
    from ipfs_datasets_py.logic.legal_ir import canonical_binding_review as adapter

    monkeypatch.setattr(adapter, "__file__", str(tmp_path / "wrong.py"))
    with pytest.raises(ValueError, match="another checkout"):
        invoke(tmp_path, packet)
    assert not (tmp_path / "recording").exists()


def test_helper_cannot_promote_authority(tmp_path, packet, monkeypatch):
    from ipfs_datasets_py.logic.legal_ir import canonical_binding_review as adapter

    original = adapter.submission_guide

    def forged_guide():
        guide = original()
        guide["qualified"] = True
        return guide

    monkeypatch.setattr(adapter, "submission_guide", forged_guide)
    with pytest.raises(ValueError, match="cannot establish"):
        invoke(tmp_path, packet)
    assert not (tmp_path / "recording").exists()


def cli_owner():
    spec = importlib.util.spec_from_file_location("binding_review_cli", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_zero_submission_and_stale_pin(tmp_path, packet, capsys):
    path = tmp_path / "packet.json"
    pin = write_file(path, packet)
    cli = cli_owner()
    options = ["--reviewer-packet", str(path), "--expected-packet-file-sha256", pin,
               "--output-directory", str(tmp_path / "cli-recording")]
    assert cli.main(options) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["submission_count"] == output["completed_independent_reviews"] == 0
    assert output["qualified"] is False and output["status_counts"] == expected_counts("pending")
    options[3] = "0" * 64
    options[-1] = str(tmp_path / "cli-stale")
    assert cli.main(options) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "failed"
    assert not (tmp_path / "cli-stale").exists()
