"""Hermetic file/CLI review recording, never real reviews or adjudication."""
from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import os
import stat
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_panel as panel_owner,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_review_admission as admission,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_review_workflow as subject,
)
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_review import (
    prepare_richer_review,
    validate_richer_review_bundle,
)

ROOT = Path(__file__).resolve().parents[5]
CLI_PATH = ROOT / "scripts/ops/legal_ir/admit_alignment_richer_reviews.py"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_binding(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False))
    return file_binding(path)


@pytest.fixture
def packet(tmp_path):
    """Keep fixture paths outside pytest's deliberately excluded test_* leaf."""
    with tempfile.TemporaryDirectory(prefix="richer-review-fixture-", dir=tmp_path.parent) as directory:
        workspace = Path(directory)
        panel = panel_owner.build_alignment_richer_panel()
        bundle = prepare_richer_review(panel, {
            "evaluation_role": "exposed_development",
            "panel": {"path": "artifacts/richer-development/panel.json", "sha256": digest(panel)},
        })
        path = workspace / "review_bundle_private.json"
        bound = write_json(path, bundle)
        return_value = workspace, bundle, path, bound["sha256"]
        yield return_value


@pytest.fixture
def cli(monkeypatch):
    spec = importlib.util.spec_from_file_location("richer_review_admission_fixture_cli", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Restore CLI search-path/environment side effects without changing its code.
    monkeypatch.setattr(module.sys, "path", list(module.sys.path))
    monkeypatch.setenv("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    return module


def cli_args(path, sha, output, submissions=()):
    args = ["--review-bundle", str(path), "--expected-bundle-sha256", sha,
            "--output-directory", str(output)]
    for item in submissions:
        args.extend(("--submission", item["path"], item["sha256"]))
    return args


def read_artifact(binding):
    path = Path(binding["path"])
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == binding["sha256"] and len(raw) == binding["bytes"]
    return json.loads(raw)


def subset(bundle, identities=None):
    payload = deepcopy(bundle["reviewer_payload"])
    payload["items"] = [item for item in payload["items"] if identities is None or item["item_id"] in identities]
    return payload


def annotate(item, reviewer, *, scope="All listed conditions apply together."):
    """A declared synthetic annotation tests recording, not source correctness."""
    item["annotation"] = {
        "interpretation_status": "normative", "ambiguity": False, "unsupported_meaning": False,
        "normative_rules": [{"modality": "O", "actor": "clerk", "action": "retain", "object": "application",
                             "conditions": ["application_complete"], "exceptions": ["court_order"],
                             "temporal": ["within_48_hours"]}],
        "freeform_qualifier_scope": scope, "notes": "Synthetic test annotation; no human review occurred.",
        "reviewer_id": reviewer, "reviewed_at_utc": "2026-10-03T12:00:00Z",
    }


def test_blank_workflow_preserves_packet_all34_pending_private_artifacts_and_no_authority(packet, monkeypatch):
    workspace, bundle, path, sha = packet
    original = path.read_bytes()
    imported = builtins.__import__

    def no_optional_stack(name, *args, **kwargs):
        assert name.split(".")[0] not in {"torch", "transformers", "spacy", "sentence_transformers", "llama_cpp"}
        return imported(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_optional_stack)
    output = workspace / "admission-01"
    report = subject.run_richer_review_admission(path, sha, [], output, repository_root=ROOT)
    assert report["status"] == "pending" and report["submission_count"] == 0
    assert report["preparation_validation"] == validate_richer_review_bundle(bundle)
    assert report["receipt"]["status_counts"]["pending"] == 34
    assert sum(report["receipt"]["status_counts"].values()) == 34
    assert report["completed_independent_reviews"] == 0
    assert report["submission_bindings"] == [] and path.read_bytes() == original
    assert report["report_sha256"] == digest({key: value for key, value in report.items() if key != "report_sha256"})
    assert json.loads((output / "report_private.json").read_bytes()) == report
    assert read_artifact(report["receipt_binding"]) == report["receipt"]
    assert read_artifact(report["submission_guide_binding"]) == admission.richer_review_submission_guide()
    assert len(report["source_bindings"]) == 7
    assert all(read_artifact_source(item) for item in report["source_bindings"])
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert {child.name for child in output.iterdir()} == {"report_private.json", "receipt_private.json", "submission_guide.json"}
    assert all(stat.S_IMODE(child.stat().st_mode) == 0o600 for child in output.iterdir())
    for name in ("qualified", "production_admitted", "independent_fidelity_available", "source_semantics_verified",
                 "proof_authority", "reviewer_identity_authenticated", "source_author_independence_authenticated",
                 "original_validation_accessed", "sealed_final_test_accessed", "authored_reference_comparison_executed",
                 "new_reviews_created", "automatic_adjudication", "training_executed", "complete_dependency_manifest"):
        assert report[name] is False
    assert all(report[name] == 0 for name in ("model_calls", "provider_calls", "encoder_calls", "prover_calls"))
    assert all(all(value is None for value in item["annotation"].values()) for item in bundle["reviewer_payload"]["items"])
    assert not (workspace / "validation.json").exists()


def read_artifact_source(item):
    raw = Path(item["path"]).read_bytes()
    return hashlib.sha256(raw).hexdigest() == item["sha256"] and len(raw) == item["bytes"]


def test_cli_zero_submissions_reports_pending34_and_preserves_private_bundle(packet, cli, capsys):
    workspace, _, path, sha = packet
    original = path.read_bytes()
    output = workspace / "cli-blank"
    assert cli.main(cli_args(path, sha, output)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "pending" and printed["status_counts"]["pending"] == 34
    assert printed["submission_count"] == printed["completed_independent_reviews"] == 0
    assert printed["qualified"] is False and Path(printed["report"]) == output / "report_private.json"
    assert path.read_bytes() == original


def test_cli_repeated_submissions_preserve_context_identities_without_authenticating_agreement(packet, cli, capsys):
    workspace, bundle, path, sha = packet
    contextual = [item for item in bundle["reviewer_payload"]["items"] if item["context"]["role"] == "explicit_assumptions"]
    assert len(contextual) == 2 and contextual[0]["source_sha256"] == contextual[1]["source_sha256"]
    identities = {item["item_id"] for item in contextual}
    bindings, originals = [], {}
    for name in ("A", "B"):
        payload = subset(bundle, identities)
        for item in payload["items"]:
            annotate(item, "fixture-declared-reviewer-" + name)
        submission = workspace / ("reviewer_" + name + ".json")
        bindings.append(write_json(submission, payload))
        originals[submission] = submission.read_bytes()
    output = workspace / "cli-declarations"
    assert cli.main(cli_args(path, sha, output, bindings)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["submission_count"] == 2 and printed["completed_independent_reviews"] == 0
    assert printed["status_counts"]["agreed_multiple_reviews"] == 2 and printed["status_counts"]["pending"] == 32
    report = json.loads((output / "report_private.json").read_bytes())
    assert len(report["submission_bindings"]) == 2
    agreed = [item for item in report["receipt"]["items"] if item["status"] == "agreed_multiple_reviews"]
    assert {item["item_id"] for item in agreed} == identities
    assert all(item["complete_distinct_reviewer_count"] == 2 for item in agreed)
    assert all(item["external_adjudication_status"] == "pending" for item in agreed)
    assert report["reviewer_identity_authenticated"] is report["source_author_independence_authenticated"] is False
    assert all(file.read_bytes() == raw for file, raw in originals.items())


def test_cli_correctly_typed_incomplete_submission_stays_pending(packet, cli, capsys):
    workspace, bundle, path, sha = packet
    payload = subset(bundle, {bundle["reviewer_payload"]["items"][0]["item_id"]})
    payload["items"][0]["annotation"]["reviewer_id"] = "fixture-incomplete-declaration"
    submitted = write_json(workspace / "incomplete.json", payload)
    output = workspace / "cli-incomplete"
    assert cli.main(cli_args(path, sha, output, [submitted])) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status_counts"]["pending"] == 34 and printed["submission_count"] == 1
    assert printed["completed_independent_reviews"] == 0 and printed["qualified"] is False


def test_cli_stale_bundle_digest_returns_failure_without_outputs(packet, cli, capsys):
    workspace, _, path, _ = packet
    output = workspace / "bad-sha"
    assert cli.main(cli_args(path, "0" * 64, output)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    failed = json.loads(captured.err)
    assert failed["status"] == "failed" and failed["qualified"] is False
    assert not output.exists()


@pytest.mark.parametrize("destination", ["bundle", "submission"])
def test_duplicate_json_keys_are_rejected_even_when_file_digest_is_correct(packet, destination):
    workspace, bundle, path, sha = packet
    if destination == "bundle":
        raw = json.dumps(bundle)[:-1] + ',"status":"prepared_pending_human_review"}'
        path.write_text(raw)
        sha = file_binding(path)["sha256"]
        submissions = []
    else:
        payload = subset(bundle, {bundle["reviewer_payload"]["items"][0]["item_id"]})
        raw = json.dumps(payload)[:-1] + ',"schema":"alignment-richer-source-context-reviewer/v1"}'
        submitted = workspace / "duplicate.json"
        submitted.write_text(raw)
        submissions = [file_binding(submitted)]
    output = workspace / "duplicates"
    with pytest.raises(ValueError, match="duplicate"):
        subject.run_richer_review_admission(path, sha, submissions, output)
    assert not output.exists()


@pytest.mark.parametrize("raw", [b'{"value":NaN}', b'{"value":Infinity}', b'\xff'])
def test_nonfinite_or_invalid_utf8_json_is_rejected_before_publication(packet, raw):
    workspace, _, path, _ = packet
    path.write_bytes(raw)
    output = workspace / "invalid-json"
    with pytest.raises(ValueError):
        subject.run_richer_review_admission(path, file_binding(path)["sha256"], [], output)
    assert not output.exists()


@pytest.mark.parametrize("kind", ["file_symlink", "parent_symlink", "directory", "fifo", "oversized"])
def test_nonregular_symlink_or_oversized_bundle_is_rejected_without_blocking(packet, kind):
    workspace, _, path, sha = packet
    bad = workspace / "nonregular.json"
    if kind == "file_symlink":
        bad.symlink_to(path)
    elif kind == "parent_symlink":
        link = workspace / "linked"
        link.symlink_to(workspace, target_is_directory=True)
        bad = link / path.name
    elif kind == "directory":
        bad.mkdir()
    elif kind == "fifo":
        os.mkfifo(bad)
    else:
        with bad.open("wb") as stream:
            stream.truncate(subject.MAX_FILE_BYTES + 1)
    output = workspace / "nonregular-output"
    with pytest.raises((ValueError, OSError)):
        subject.run_richer_review_admission(bad, sha, [], output)
    assert not output.exists()


@pytest.mark.parametrize("word", ["sealed", "holdout", "heldout", "final", "test"])
def test_excluded_input_path_rejected_before_filesystem_access(packet, monkeypatch, word):
    workspace, _, _, _ = packet

    def no_filesystem_access(*args, **kwargs):
        raise AssertionError("excluded input path must be rejected before lstat/open")

    monkeypatch.setattr(subject, "_no_symlink_components", no_filesystem_access)
    with pytest.raises(ValueError, match="input path forbidden"):
        subject._read_pinned_json(workspace / (word + "-review.json"), "a" * 64)


@pytest.mark.parametrize("changed", ["bundle", "submission"])
def test_bound_input_changed_after_admission_prevents_any_publication(packet, monkeypatch, changed):
    workspace, bundle, path, sha = packet
    payload = subset(bundle, {bundle["reviewer_payload"]["items"][0]["item_id"]})
    submitted_path = workspace / "blank_submission.json"
    submitted = write_json(submitted_path, payload)
    admit = admission.admit_richer_reviews

    def change_after_acceptance(prepared, payloads):
        receipt = admit(prepared, payloads)
        changed_path = path if changed == "bundle" else submitted_path
        changed_path.write_bytes(changed_path.read_bytes() + b"\n")
        return receipt

    monkeypatch.setattr(admission, "admit_richer_reviews", change_after_acceptance)
    output = workspace / "drift"
    with pytest.raises(ValueError, match="changed during execution"):
        subject.run_richer_review_admission(path, sha, [submitted], output)
    assert not output.exists()


def test_input_drift_between_strict_parse_and_binding_is_rejected(packet, monkeypatch):
    _, _, path, sha = packet
    observed = subject._observed_binding

    def change_before_binding(supplied):
        path.write_bytes(path.read_bytes() + b"\n")
        return observed(supplied)

    monkeypatch.setattr(subject, "_observed_binding", change_before_binding)
    with pytest.raises(ValueError, match="drifted after reading"):
        subject._read_pinned_json(path, sha)


def test_source_recheck_detects_changed_bytes_without_editing_repository(packet, monkeypatch):
    workspace, _, path, sha = packet
    observed, seen = subject._observed_binding, []
    selected = ROOT / subject._SOURCE_FILES[0]

    def simulate_version_change(supplied):
        record = observed(supplied)
        if Path(supplied) == selected:
            seen.append(True)
            if len(seen) == 2:
                record["sha256"] = "0" * 64
        return record

    monkeypatch.setattr(subject, "_observed_binding", simulate_version_change)
    output = workspace / "source-drift"
    with pytest.raises(ValueError, match="changed during execution"):
        subject.run_richer_review_admission(path, sha, [], output)
    assert not output.exists()


def test_wrong_loaded_admission_origin_is_rejected(packet, monkeypatch):
    workspace, _, path, sha = packet
    monkeypatch.setattr(admission, "__file__", str(workspace / "foreign-owner.py"))
    output = workspace / "foreign"
    with pytest.raises(ValueError, match="another checkout"):
        subject.run_richer_review_admission(path, sha, [], output)
    assert not output.exists()


def test_workflow_refuses_trusted_helper_contract_drift_before_writing(packet, monkeypatch):
    """Check metadata invariants, not protection against arbitrary runtime code."""
    workspace, _, path, sha = packet
    admit = admission.admit_richer_reviews

    def forged_receipt(prepared, payloads):
        receipt = admit(prepared, payloads)
        receipt["qualified"] = True
        return receipt

    monkeypatch.setattr(admission, "admit_richer_reviews", forged_receipt)
    output = workspace / "forged"
    with pytest.raises(ValueError):
        subject.run_richer_review_admission(path, sha, [], output)
    assert not output.exists()


@pytest.mark.parametrize("bindings", [None, (), [{}], [{"path": "x", "sha256": "a" * 64, "unbound": True}],
                                       [{"path": "x", "sha256": "a" * 64}] * 21])
def test_closed_bounded_submission_binding_contract(packet, bindings):
    workspace, _, path, sha = packet
    output = workspace / "bad-bindings"
    with pytest.raises(ValueError, match="bound|closed"):
        subject.run_richer_review_admission(path, sha, bindings, output)
    assert not output.exists()


def test_existing_output_and_symlink_parent_are_rejected_without_overwriting(packet, cli, capsys):
    workspace, _, path, sha = packet
    output = workspace / "existing"
    output.mkdir()
    sentinel = output / "keep.json"
    sentinel.write_text("preserve")
    assert cli.main(cli_args(path, sha, output)) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "failed"
    assert sentinel.read_text() == "preserve"
    real = workspace / "real-parent"
    real.mkdir()
    link = workspace / "linked-parent"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        subject.run_richer_review_admission(path, sha, [], link / "output")
    assert list(real.iterdir()) == []


def test_workflow_rejects_other_repository_before_any_output(packet):
    workspace, _, path, sha = packet
    with pytest.raises(ValueError, match="canonical checkout"):
        subject.run_richer_review_admission(path, sha, [], workspace / "wrong-root", repository_root=workspace)
    assert not (workspace / "wrong-root").exists()
