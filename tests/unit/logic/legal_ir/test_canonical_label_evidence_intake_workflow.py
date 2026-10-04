"""Synthetic local evidence exercises file integrity, never human admission."""
from __future__ import annotations

import builtins
import copy
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.legal_ir import (
    canonical_binding_review as recorder,
)
from ipfs_datasets_py.logic.legal_ir import (
    canonical_binding_review_workflow as recording_files,
)
from ipfs_datasets_py.logic.legal_ir import (
    canonical_label_evidence_intake as core,
)
from ipfs_datasets_py.logic.legal_ir import (
    canonical_label_evidence_intake_workflow as subject,
)

ROOT = Path(subject.__file__).resolve().parents[3]
CLI = ROOT / "scripts/ops/legal_ir/intake_binding_label_evidence.py"


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def checksum(value):
    return hashlib.sha256(raw(value)).hexdigest()


def write(path, value):
    data = raw(value) + b"\n"
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(path, value):
    return dict(content_sha256=checksum(value), file_sha256=pin(path), file_bytes=path.stat().st_size)


def seal(value):
    value["content_sha256"] = checksum({key: item for key, item in value.items() if key != "content_sha256"})
    return value


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("label-evidence-workflow")


def make_case(tmp_path, *, nonempty=False):
    context = dict(role="none_required", text="", bindings={}, sha256=hashlib.sha256(b"").hexdigest())
    items = []
    for number in range(2):
        source = f"Synthetic fixture {number}: the clerk must retain the filing."
        input_sha = checksum(dict(source_text=source, context=context))
        identity = "binding-review-item-" + hashlib.sha256(
            b"authored-binding-review-v1\0" + bytes.fromhex(input_sha)).hexdigest()[:24]
        items.append(dict(item_id=identity, source_text=source,
            source_sha256=hashlib.sha256(source.encode()).hexdigest(), input_sha256=input_sha,
            context=copy.deepcopy(context), annotation=dict.fromkeys(recorder.ANNOTATION_FIELDS)))
    packet = dict(schema=recorder.REVIEWER_SCHEMA,
        instructions={name: "Synthetic fixture only; no actual review." for name in recorder._INSTRUCTION_FIELDS},
        items=sorted(items, key=lambda item: item["item_id"]))
    packet_path = tmp_path / "reviewer.json"
    packet_sha = write(packet_path, packet)
    submissions = []
    payloads = []
    if nonempty:
        payload = copy.deepcopy(packet)
        payload["items"] = [payload["items"][0]]
        payload["items"][0]["annotation"] = dict(
            interpretation_status="normative", ambiguity=False, unsupported_meaning=False,
            normative_rules=[dict(modality="O", actor="clerk", action="retain", object="filing",
                                  conditions=[], exceptions=[], temporal=[])],
            freeform_qualifier_scope="", notes="Synthetic declaration only.",
            reviewer_id="synthetic-A", reviewed_at_utc="2026-10-04T12:00:00Z")
        payload_path = tmp_path / "submitted-declaration.json"
        submissions.append(dict(path=str(payload_path), sha256=write(payload_path, payload)))
        payloads.append(payload)
    recording_dir = tmp_path / "original-recording"
    recorded = recording_files.run_binding_review_recording(packet_path, packet_sha, submissions, recording_dir)
    report_path = recording_dir / "report_private.json"
    receipt_path = recording_dir / "receipt_private.json"
    receipt = json.loads(receipt_path.read_bytes())
    package = dict(schema=core.SCHEMA, packet_binding=binding(packet_path, packet),
        recording_binding=binding(receipt_path, receipt), organizer_binding=None,
        review_process_binding=None, cohort_policy_binding=None, supersedes_package_sha256=None, items=[])
    selections = {}
    if nonempty:
        metadata = {
            "organizer": {"synthetic": "organizer metadata is not authenticated"},
            "process": dict(schema=subject.PROCESS_SCHEMA, process_id="synthetic-process", organizer_id="synthetic-organizer"),
            "cohort": ["synthetic cohort declaration; semantics unverified"],
        }
        fields = {"organizer": "organizer_binding", "process": "review_process_binding", "cohort": "cohort_policy_binding"}
        for name, value in metadata.items():
            path = tmp_path / (name + ".json")
            selections[name] = dict(path=str(path), sha256=write(path, value))
            package[fields[name]] = binding(path, value)
        item = receipt["items"][0]
        entry = item["received_declarations"][0]
        declaration = dict(submission_binding=dict(submission_index=entry["submission_index"],
            submission_sha256=entry["submission_sha256"]), item_id=item["item_id"],
            annotation_content_sha256=checksum(entry["annotation"]),
            meaning_signature_sha256=entry["meaning_signature_sha256"])
        provenance = dict(process_id="synthetic-process", responsible_organizer="synthetic-organizer",
            principal_id="synthetic-A", role="reviewer", identity_method="unverified unit fixture",
            author_model_relationship="unverified unit fixture", independence_assessment="unverified unit fixture",
            inputs_exposed=dict(source_input_sha256=item["input_sha256"], candidate_or_reference_exposed=False,
                                organizer_metadata_exposed=False, other_exposure=""),
            annotation_binding=copy.deepcopy(declaration), assessed_at_utc="2026-10-04T12:00:00Z",
            rationale="Synthetic declaration for boundary testing.", limitations="No identity or independence evidence.")
        package["items"] = [dict(item_id=item["item_id"], source_sha256=item["source_sha256"],
            input_sha256=item["input_sha256"], declaration_refs=[declaration], provenance_refs=[provenance],
            interpretations=[], adjudication_ref=None)]
    package_path = tmp_path / "evidence.json"
    write(package_path, seal(package))
    args = [packet_path, packet_sha, report_path, pin(report_path), package_path, pin(package_path),
            tmp_path / "intake"]
    options = {} if not nonempty else dict(organizer_binding=selections["organizer"],
        selected_process_binding=selections["process"], cohort_policy_binding=selections["cohort"])
    return dict(args=args, options=options, package=package, recorded=recorded, receipt=receipt,
                receipt_path=receipt_path, packet=packet, payloads=payloads, selections=selections)


def rewrite_report(case, change):
    report = json.loads(case["args"][2].read_bytes())
    change(report)
    case["args"][3] = write(case["args"][2], seal(report))


def rewrite_package(case, change):
    change(case["package"])
    case["args"][5] = write(case["args"][4], seal(case["package"]))


def invoke(case):
    return subject.run_label_evidence_intake(*case["args"], **case["options"])


def assert_pending(report, receipt):
    for value in (report, receipt, *receipt["items"]):
        assert all(value[field] is False for field in recorder._AUTHORITY)
        assert value["verification_status"] == value["admission_status"] == "pending"
        assert all(type(mask) is int and mask == 0 for mask in value["masks"].values())
    for value in (report, receipt):
        assert value["human_reviews_authenticated"] == value["independent_reviews_authenticated"] == 0
        assert all(value[field] == 0 for field in ("model_calls", "provider_calls", "encoder_calls", "prover_calls"))
        assert value["training_executed"] is value["automatic_adjudication"] is False


def test_empty_package_preserves_all_original_items_and_private_outputs(tmp_path):
    case = make_case(tmp_path)
    originals = {path: path.read_bytes() for path in case["args"][:6] if isinstance(path, Path)}
    report = invoke(case)
    directory = case["args"][-1]
    receipt = json.loads((directory / "intake_receipt_private.json").read_bytes())
    assert_pending(report, receipt)
    assert report["declared_package_item_count"] == 0 and report["item_count"] == 2
    assert [row["item_id"] for row in receipt["items"]] == [row["item_id"] for row in case["receipt"]["items"]]
    assert all(row["evidence_status"] == "pending" for row in receipt["items"])
    assert report["input_file_count"] == 4 and len(report["source_bindings"]) == 8
    assert report["input_file_bindings_verified"] is True
    assert receipt["file_bindings_verified"] is receipt["metadata_content_verified"] is False
    assert report["metadata_content_bindings_verified"] is report["organizer_metadata_accessed"] is False
    assert report["selected_process_binding"] is None
    assert report["complete_dependency_manifest"] is False
    assert report["review_declarations_accessed"] is True
    assert report["separate_candidate_or_authored_reference_files_accessed"] is False
    assert report["content_sha256"] == checksum({k: v for k, v in report.items() if k != "content_sha256"})
    assert json.loads((directory / "report_private.json").read_bytes()) == report
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in directory.iterdir())
    assert all(path.read_bytes() == original for path, original in originals.items())


def test_nonempty_evidence_binds_original_submissions_and_selected_metadata_without_authority(tmp_path):
    case = make_case(tmp_path, nonempty=True)
    report = invoke(case)
    receipt = json.loads((case["args"][-1] / "intake_receipt_private.json").read_bytes())
    assert_pending(report, receipt)
    assert report["declared_package_item_count"] == 1 and report["input_file_count"] == 8
    assert report["metadata_content_bindings_verified"] is True
    assert report["metadata_semantics_validated"] is report["selected_process_authenticated"] is False
    assert receipt["items"][0]["evidence_status"] == "declared_unverified"
    assert receipt["items"][1]["evidence_status"] == "pending"
    assert receipt["selected_process_binding"]["process_id"] == "synthetic-process"
    assert report["expected_bindings"]["submissions"][0]["content_sha256"] == checksum(case["payloads"][0])
    assert report["recording_replay_validation"]["declared_completed_annotation_count"] == 1


@pytest.mark.parametrize("position", [1, 3, 5])
def test_stale_input_pins_fail_before_publication(tmp_path, position):
    case = make_case(tmp_path)
    case["args"][position] = "0" * 64
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        invoke(case)
    assert not case["args"][-1].exists()


@pytest.mark.parametrize("change,match", [
    (lambda report: report.update(schema="outer-readiness/v1"), "artifact schema"),
    (lambda report: report.update(reviewer_packet_sha256="0" * 64), "content identity"),
    (lambda report: report.update(submission_count=True), "submission count"),
    (lambda report: report.update(status_counts={"pending": 99}), "outcomes differ"),
    (lambda report: report.update(proof_authority=True), "must remain false"),
    (lambda report: report.update(trust="kernel"), "closed"),
    (lambda report: report["source_bindings"][0].update(sha256="0" * 64), "implementation bindings"),
    (lambda report: report["packet_binding"].update(bytes=1), "packet file binding"),
])
def test_resealed_inner_report_cannot_change_the_selected_generation(tmp_path, change, match):
    case = make_case(tmp_path)
    rewrite_report(case, change)
    with pytest.raises(ValueError, match=match):
        invoke(case)
    assert not case["args"][-1].exists()


def test_recording_report_requires_its_own_content_checksum(tmp_path):
    case = make_case(tmp_path)
    report = json.loads(case["args"][2].read_bytes())
    report["content_sha256"] = "0" * 64
    case["args"][3] = write(case["args"][2], report)
    with pytest.raises(ValueError, match="report checksum"):
        invoke(case)


def test_resealed_changed_receipt_is_rejected_by_original_submission_replay(tmp_path):
    case = make_case(tmp_path, nonempty=True)
    receipt = copy.deepcopy(case["receipt"])
    receipt["items"][0]["received_declarations"][0]["annotation"]["notes"] = "Substituted declaration"
    receipt["receipt_sha256"] = checksum({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    receipt_sha = write(case["receipt_path"], receipt)
    rewrite_report(case, lambda report: report["receipt_binding"].update(
        sha256=receipt_sha, bytes=case["receipt_path"].stat().st_size))
    rewrite_package(case, lambda package: package.update(recording_binding=binding(case["receipt_path"], receipt)))
    with pytest.raises(ValueError, match="exact submission replay"):
        invoke(case)
    assert not case["args"][-1].exists()


def test_original_submission_must_still_exist_at_its_pinned_binding(tmp_path):
    case = make_case(tmp_path, nonempty=True)
    Path(case["recorded"]["submission_bindings"][0]["path"]).unlink()
    with pytest.raises((ValueError, OSError)):
        invoke(case)
    assert not case["args"][-1].exists()


@pytest.mark.parametrize("data", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'\xff'])
def test_strict_file_reader_precedes_package_validation(tmp_path, data):
    case = make_case(tmp_path)
    case["args"][4].write_bytes(data)
    case["args"][5] = pin(case["args"][4])
    with pytest.raises(ValueError, match="UTF8 JSON"):
        invoke(case)
    assert not case["args"][-1].exists()


@pytest.mark.parametrize("mode", ["leaf_symlink", "parent_symlink", "fifo", "sealed_path"])
def test_intake_refuses_unsafe_selected_file_paths(tmp_path, mode):
    case = make_case(tmp_path)
    original = case["args"][4]
    path = tmp_path / "selected.json"
    if mode == "leaf_symlink":
        path.symlink_to(original)
    elif mode == "parent_symlink":
        parent = tmp_path / "alias"
        parent.symlink_to(tmp_path, target_is_directory=True)
        path = parent / original.name
    elif mode == "fifo":
        os.mkfifo(path)
    else:
        path = tmp_path / "sealed-evidence.json"
        path.write_bytes(original.read_bytes())
    case["args"][4] = path
    with pytest.raises((ValueError, OSError)):
        invoke(case)
    assert not case["args"][-1].exists()


def test_aggregate_budget_is_checked_before_parsing_the_next_input(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    monkeypatch.setattr(subject, "MAX_INPUT_BYTES", case["args"][0].stat().st_size - 1)
    monkeypatch.setattr(recording_files, "_read_pinned_json", lambda *args: pytest.fail("body was read past aggregate limit"))
    with pytest.raises(ValueError, match="aggregate"):
        invoke(case)


@pytest.mark.parametrize("nonempty", [False, True])
def test_metadata_selection_scope_is_explicit(tmp_path, nonempty):
    case = make_case(tmp_path, nonempty=nonempty)
    if nonempty:
        case["options"].pop("cohort_policy_binding")
    else:
        case["options"]["organizer_binding"] = {"path": str(tmp_path / "not-read.json"), "sha256": "0" * 64}
    with pytest.raises(ValueError, match="metadata selections"):
        invoke(case)
    assert not case["args"][-1].exists()


def test_selected_process_file_has_a_closed_schema(tmp_path):
    case = make_case(tmp_path, nonempty=True)
    selected = case["selections"]["process"]
    path = Path(selected["path"])
    value = json.loads(path.read_bytes())
    value["authenticated"] = True
    selected["sha256"] = write(path, value)
    with pytest.raises(ValueError, match="closed"):
        invoke(case)
    assert not case["args"][-1].exists()


def test_metadata_content_substitution_is_rejected_even_with_valid_selected_file_hash(tmp_path):
    case = make_case(tmp_path, nonempty=True)
    selected = case["selections"]["organizer"]
    selected["sha256"] = write(Path(selected["path"]), {"different": "unverified organizer declaration"})
    with pytest.raises(ValueError, match="expected organizer binding"):
        invoke(case)


def test_inputs_and_code_are_rechecked_before_publication(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    original = core.validate_label_evidence_intake

    def mutate_after_validation(*args, **kwargs):
        result = original(*args, **kwargs)
        case["args"][4].write_bytes(case["args"][4].read_bytes() + b" ")
        return result

    monkeypatch.setattr(core, "validate_label_evidence_intake", mutate_after_validation)
    with pytest.raises(ValueError, match="changed during execution"):
        invoke(case)
    assert not case["args"][-1].exists()


def test_checkout_and_fresh_output_boundaries(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    with pytest.raises(ValueError, match="canonical checkout"):
        subject.run_label_evidence_intake(*case["args"], repository_root=tmp_path)
    case["args"][-1].mkdir()
    with pytest.raises(ValueError, match="fresh evidence"):
        invoke(case)
    case["args"][-1].rmdir()
    monkeypatch.setattr(core, "__file__", str(tmp_path / "foreign.py"))
    with pytest.raises(ValueError, match="another checkout"):
        invoke(case)


def test_dictionary_core_cannot_promote_authority_through_workflow(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    original = core.validate_label_evidence_intake

    def promoted(*args, **kwargs):
        result = original(*args, **kwargs)
        result["qualified"] = True
        return result

    monkeypatch.setattr(core, "validate_label_evidence_intake", promoted)
    with pytest.raises(ValueError, match="cannot establish"):
        invoke(case)
    assert not case["args"][-1].exists()


def cli_owner():
    spec = importlib.util.spec_from_file_location("label_evidence_cli", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cli_args(case):
    args = case["args"]
    options = ["--reviewer-packet", str(args[0]), "--expected-packet-file-sha256", args[1],
        "--recording-report", str(args[2]), "--expected-recording-report-file-sha256", args[3],
        "--evidence-package", str(args[4]), "--expected-evidence-package-file-sha256", args[5],
        "--output-directory", str(args[6])]
    for name, field in (("organizer", "organizer_binding"), ("selected-process", "selected_process_binding"),
                        ("cohort-policy", "cohort_policy_binding")):
        if field in case["options"]:
            reference = case["options"][field]
            options.extend(["--" + name, reference["path"], reference["sha256"]])
    return options


@pytest.mark.parametrize("nonempty", [False, True])
def test_cli_records_pending_diagnostics_and_rejects_stale_pins(tmp_path, nonempty, capsys):
    case = make_case(tmp_path, nonempty=nonempty)
    cli = cli_owner()
    options = cli_args(case)
    assert cli.main(options) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["declared_package_item_count"] == int(nonempty)
    assert report["qualified"] is False
    assert report["verification_status"] == report["admission_status"] == "pending"
    options[11] = "0" * 64
    options[13] = str(tmp_path / "cli-stale")
    assert cli.main(options) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "failed"
    assert not (tmp_path / "cli-stale").exists()


def test_workflow_import_path_has_no_model_prover_or_service_dependencies(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    original = builtins.__import__
    denied = ("torch", "transformers", "tensorflow", "jax", "sentence_transformers", "spacy",
              "ipfs_accelerate_py", "ipfs_datasets_py.logic.backends", "ipfs_datasets_py.logic.TDFOL")

    def guard(name, *args, **kwargs):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in denied):
            pytest.fail("unexpected runtime dependency: " + name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    report = invoke(case)
    assert report["model_calls"] == report["prover_calls"] == 0
