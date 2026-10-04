"""Read pinned declaration evidence without authenticating or admitting labels.

Only the selected inner recording generation supplies receipt/submission paths.
Byte and canonical-content checks remain distinct from review authentication,
metadata semantics, source fidelity and training/evaluation admission.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

SCHEMA = "canonical-binding-label-evidence-intake-artifact/v1"
PROCESS_SCHEMA = "canonical-label-review-process-selection/v1"
MAX_INPUT_BYTES = 16 * 1024 * 1024
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/legal_ir/canonical_label_evidence_intake_workflow.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_label_evidence_intake.py",
    "scripts/ops/legal_ir/intake_binding_label_evidence.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_binding_review.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_binding_review_workflow.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review_workflow.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review_admission.py",
    "scripts/ops/legal_ir/record_binding_reviews.py",
)
_REPORT_FIELDS = {
    "schema", "status", "organizer_private", "packet_binding", "reviewer_packet_sha256",
    "packet_content_digest_recipe", "file_digest_recipe", "submission_bindings",
    "source_bindings", "preparation_validation", "recording_validation", "receipt_binding",
    "submission_guide_binding", "output_directory", "submission_count", "status_counts",
    "source_only_packet", "organizer_manifest_accessed", "candidate_or_reference_accessed",
    "completed_independent_reviews", "reviewer_identity_authenticated",
    "reviewer_independence_authenticated", "independent_semantic_review_completed",
    "source_fidelity_established", "semantic_gold_created", "actual_training_or_evaluation_admission",
    "proof_authority", "qualified", "accepted", "model_calls", "provider_calls", "encoder_calls",
    "prover_calls", "training_executed", "automatic_adjudication", "submissions_created",
    "complete_dependency_manifest", "dependency_binding_scope", "content_sha256",
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _modules():
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_review_admission as annotations,
    )
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_review_workflow as files,
    )
    from ipfs_datasets_py.logic.legal_ir import (
        canonical_binding_review as recorder,
    )
    from ipfs_datasets_py.logic.legal_ir import (
        canonical_binding_review_workflow as recording_files,
    )
    from ipfs_datasets_py.logic.legal_ir import (
        canonical_label_evidence_intake as core,
    )

    return files, annotations, recorder, recording_files, core


def _file_reference(value, recorder):
    recorder._closed(value, {"path", "sha256", "bytes"}, "recorded file binding")
    recorder._text(value["path"], 4096, "recorded file path")
    recorder._sha(value["sha256"], "recorded file sha256")
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_INPUT_BYTES,
             "bounded integer recorded file bytes required")


def _selection(value, recorder):
    recorder._closed(value, {"path", "sha256"}, "selected metadata file binding")
    recorder._sha(value["sha256"], "selected metadata sha256")


def _check_report(report, packet, packet_binding, recorder, recording_files, files, root):
    recorder._raw(report)
    recorder._closed(report, _REPORT_FIELDS, "inner recording report")
    _require(report["schema"] == recording_files.SCHEMA, "inner recording artifact schema required")
    recorder._sha(report["content_sha256"], "recording report content_sha256")
    _require(report["content_sha256"] == recorder._digest(
        {key: value for key, value in report.items() if key != "content_sha256"}),
        "inner recording report checksum mismatch")
    _file_reference(report["packet_binding"], recorder)
    _require(report["packet_binding"] == packet_binding,
             "inner recording packet file binding mismatch")
    _require(report["reviewer_packet_sha256"] == recorder._digest(packet),
             "inner recording packet content identity mismatch")
    _require(report["packet_content_digest_recipe"] == recorder.DIGEST_RECIPE
             and report["file_digest_recipe"] == "sha256_exact_file_bytes",
             "inner recording digest recipes differ")
    _require(report["preparation_validation"] == recorder.validate_blank_packet(
        packet, expected_packet_sha256=report["reviewer_packet_sha256"]),
        "inner recording packet validation differs")
    _require(report["organizer_private"] is True and report["source_only_packet"] is True,
             "source-only private recording required")
    for field in (*recording_files._FALSE_FIELDS, "organizer_manifest_accessed",
                  "candidate_or_reference_accessed", "training_executed", "automatic_adjudication",
                  "submissions_created", "complete_dependency_manifest"):
        _require(report[field] is False, "inner recording authority/scope flag must remain false: " + field)
    for field in ("completed_independent_reviews", "model_calls", "provider_calls", "encoder_calls", "prover_calls"):
        _require(type(report[field]) is int and report[field] == 0,
                 "inner recording cannot establish reviews or call models/provers")
    _require(report["dependency_binding_scope"] == "five_explicit_owners_not_dependency_closure",
             "inner recording dependency scope differs")
    references = report["submission_bindings"]
    _require(type(references) is list and len(references) <= recorder.MAX_SUBMISSIONS
             and type(report["submission_count"]) is int and report["submission_count"] == len(references),
             "inner recording submission count differs")
    for value in (report["receipt_binding"], report["submission_guide_binding"], *references):
        _file_reference(value, recorder)
    directory = files._path(report["output_directory"])
    _require(files._path(report["receipt_binding"]["path"]) == directory / "receipt_private.json"
             and files._path(report["submission_guide_binding"]["path"]) == directory / "submission_guide.json",
             "inner recording output generation paths differ")
    sources = report["source_bindings"]
    expected = [files._observed_binding(root / relative) for relative in recording_files._SOURCE_FILES]
    _require(sources == expected, "inner recording implementation bindings differ")
    return references


def _check_scope(receipt, recorder):
    for value in (receipt, *receipt["items"]):
        _require(all(value.get(field) is expected for field, expected in recorder._AUTHORITY.items()),
                 "label intake cannot establish authentication, fidelity or admission")
        masks = value.get("masks")
        _require(type(masks) is dict and set(masks) == set(recorder.MASK_FIELDS)
                 and all(type(value) is int and value == 0 for value in masks.values()),
                 "all label intake masks must remain zero")
        _require(value["verification_status"] == value["admission_status"] == "pending",
                 "label intake verification/admission must remain pending")
    for field in ("human_reviews_authenticated", "independent_reviews_authenticated", "formal_targets_admitted",
                  "model_calls", "provider_calls", "encoder_calls", "prover_calls"):
        _require(type(receipt[field]) is int and receipt[field] == 0,
                 "label intake cannot authenticate reviews, admit targets or call models/provers")
    for field in ("training_executed", "automatic_adjudication", "submissions_created",
                  "file_bindings_verified", "metadata_content_verified", "semantic_profile_validated"):
        _require(receipt[field] is False, "dictionary intake cannot promote file or semantic authority")


def run_label_evidence_intake(packet_path, expected_packet_file_sha256,
        recording_report_path, expected_recording_report_file_sha256,
        package_path, expected_package_file_sha256, output_directory, *,
        organizer_binding=None, selected_process_binding=None, cohort_policy_binding=None,
        repository_root=None):
    """Publish diagnostic evidence after bounded file checks and exact replay.

    Optional metadata selections are explicit ``{path, sha256}`` bindings.
    They are required together for nonempty evidence and forbidden for empty
    readiness. Metadata bytes/content are checked; their semantics and human
    provenance remain unverified. No evidence package is generated here.
    """
    files, annotations, recorder, recording_files, core = _modules()
    executing_root = Path(__file__).resolve().parents[3]
    root = executing_root if repository_root is None else files._path(repository_root).resolve()
    _require(root == executing_root, "intake must use the executing canonical checkout")
    for module, relative in ((core, _SOURCE_FILES[1]), (recorder, _SOURCE_FILES[3]),
                             (recording_files, _SOURCE_FILES[4]), (files, _SOURCE_FILES[5]),
                             (annotations, _SOURCE_FILES[6])):
        _require(Path(module.__file__).resolve() == root / relative,
                 "intake dependency import comes from another checkout")
    directory = files._path(output_directory)
    files._no_symlink_components(directory, allow_missing=True)
    _require(not directory.exists(), "output directory already exists; fresh evidence required")
    sources = [files._observed_binding(root / relative) for relative in _SOURCE_FILES]
    inputs, consumed = [], 0

    def read(path, sha256):
        nonlocal consumed
        path = files._path(path, exposed_input=True)
        files._no_symlink_components(path)
        info = path.stat(follow_symlinks=False)
        _require(stat.S_ISREG(info.st_mode), "regular intake JSON file required")
        _require(info.st_size <= MAX_INPUT_BYTES - consumed,
                 "aggregate intake input byte bound exceeded")
        value, observed = recording_files._read_pinned_json(path, sha256)
        _require(observed["bytes"] == info.st_size,
                 "intake input changed while reading")
        recorder._raw(value)
        consumed += observed["bytes"]
        _require(consumed <= MAX_INPUT_BYTES, "aggregate intake input byte bound exceeded")
        inputs.append(observed)
        return value, observed

    def content_binding(value, observed):
        return {"content_sha256": recorder._digest(value),
                "file_sha256": observed["sha256"], "file_bytes": observed["bytes"]}

    packet, packet_observed = read(packet_path, expected_packet_file_sha256)
    report, report_observed = read(recording_report_path, expected_recording_report_file_sha256)
    references = _check_report(report, packet, packet_observed, recorder, recording_files, files, root)
    package, package_observed = read(package_path, expected_package_file_sha256)
    recorder._closed(package, core.PACKAGE_FIELDS, "label evidence package")
    _require(type(package["items"]) is list, "evidence package item list required")
    metadata = {"organizer": organizer_binding, "process": selected_process_binding,
                "cohort": cohort_policy_binding}
    nonempty = bool(package["items"])
    _require(all(value is not None for value in metadata.values()) if nonempty
             else all(value is None for value in metadata.values()),
             "nonempty evidence requires all three metadata selections; empty evidence requires none")
    receipt_reference = report["receipt_binding"]
    receipt, receipt_observed = read(receipt_reference["path"], receipt_reference["sha256"])
    _require(receipt_observed == receipt_reference, "inner recording receipt file binding differs")
    payloads, submission_pins = [], []
    for reference in references:
        payload, observed = read(reference["path"], reference["sha256"])
        _require(observed == reference, "inner recording original submission file binding differs")
        payloads.append(payload)
        submission_pins.append(content_binding(payload, observed))
    expected = {"packet": content_binding(packet, packet_observed),
                "receipt": content_binding(receipt, receipt_observed),
                "submissions": submission_pins, "organizer": None, "process": None, "cohort": None}
    selected, metadata_observed = None, {}
    for name, reference in metadata.items():
        if reference is None:
            continue
        _selection(reference, recorder)
        value, observed = read(reference["path"], reference["sha256"])
        expected[name] = content_binding(value, observed)
        metadata_observed[name] = observed
        if name == "process":
            recorder._closed(value, {"schema", "process_id", "organizer_id"}, "selected review process file")
            _require(value["schema"] == PROCESS_SCHEMA, "selected review process schema required")
            for field in ("process_id", "organizer_id"):
                recorder._text(value[field], 256, "selected process " + field)
            selected = {"process_id": value["process_id"], "organizer_id": value["organizer_id"],
                        "content_sha256": expected[name]["content_sha256"]}
    replay_envelope = {"receipt": receipt, "reviewed_payloads": payloads}
    result = core.validate_label_evidence_intake(packet, replay_envelope, package,
        expected_bindings=expected, selected_process_binding=selected)
    replay = recorder.validate_recording(receipt, packet, payloads,
        expected_packet_sha256=expected["packet"]["content_sha256"])
    _require(report["recording_validation"] == replay, "inner recording validation differs from exact replay")
    _require(report["status"] == receipt["status"] and report["status_counts"] == receipt["status_counts"]
             and report["submission_count"] == receipt["submission_count"],
             "inner recording outcomes differ from exact replay")
    _check_scope(result, recorder)
    result_binding = files._output_binding(directory, "intake_receipt_private.json", result)
    output = {
        "schema": SCHEMA, "status": result["status"], "organizer_private": True,
        "packet_binding": packet_observed, "recording_report_binding": report_observed,
        "recording_receipt_binding": receipt_observed, "package_binding": package_observed,
        "original_submission_bindings": references, "selected_metadata_file_bindings": metadata_observed,
        "expected_bindings": expected, "selected_process_binding": selected,
        "intake_receipt_binding": result_binding, "recording_replay_validation": replay,
        "output_directory": str(directory), "source_bindings": sources,
        "input_file_count": len(inputs), "input_bytes": consumed, "input_byte_limit": MAX_INPUT_BYTES,
        "input_file_bindings_verified": True, "metadata_content_bindings_verified": nonempty,
        "metadata_semantics_validated": False, "selected_process_authenticated": False,
        "recording_generation_replayed": True, "evidence_packages_created": False,
        "organizer_metadata_accessed": nonempty, "selected_process_metadata_accessed": nonempty,
        "cohort_policy_metadata_accessed": nonempty,
        "separate_candidate_or_authored_reference_files_accessed": False,
        "review_declarations_accessed": True,
        "item_count": result["item_count"], "declared_package_item_count": result["declared_package_item_count"],
        "verification_status": "pending", "admission_status": "pending",
        "masks": dict.fromkeys(recorder.MASK_FIELDS, 0), "formal_targets_admitted": 0,
        "human_reviews_authenticated": 0, "independent_reviews_authenticated": 0,
        "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0,
        "training_executed": False, "automatic_adjudication": False, "submissions_created": False,
        "complete_dependency_manifest": False,
        "dependency_binding_scope": "eight_explicit_owners_not_dependency_closure",
        "file_digest_recipe": "sha256_exact_file_bytes", "content_digest_recipe": recorder.DIGEST_RECIPE,
        **recorder._AUTHORITY,
    }
    output["content_sha256"] = recorder._digest(output)
    files._encoded_json(output)
    files._recheck_bindings([*sources, *inputs])
    files._no_symlink_components(directory, allow_missing=True)
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(directory, 0o700)
    _require(files._write_json(directory, "intake_receipt_private.json", result) == result_binding,
             "intake receipt publication differs from planned binding")
    files._write_json(directory, "report_private.json", output)
    return output


__all__ = ["run_label_evidence_intake"]
