"""Record declarations for the source-only binding packet without semantic admission.

The file boundary pins exact UTF8 bytes. The dictionary adapter separately pins
canonical packet content. Existing filesystem helpers are reused unchanged;
their explicit source bindings do not attest an entire dependency closure.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

SCHEMA = "canonical-binding-review-recording-artifact/v1"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SUBMISSIONS = 20
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/legal_ir/canonical_binding_review_workflow.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_binding_review.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review_workflow.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review_admission.py",
    "scripts/ops/legal_ir/record_binding_reviews.py",
)
_FALSE_FIELDS = (
    "qualified", "accepted", "source_fidelity_established", "proof_authority",
    "independent_semantic_review_completed", "reviewer_identity_authenticated",
    "reviewer_independence_authenticated", "semantic_gold_created",
    "actual_training_or_evaluation_admission",
)
_MASKS = ("weak_decoder_fit", "strong_semantic_fit", "contrastive_supervision",
          "proof_supervision", "fidelity_evaluation")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("finite ordinary UTF8 JSON required") from error


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _files():
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_review_workflow

    return alignment_richer_review_workflow


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "duplicate JSON key forbidden")
        value[key] = item
    return value


def _nonfinite(value):
    raise ValueError("nonfinite JSON value forbidden: " + value)


def _read_pinned_json(path, expected_sha256):
    """Strict UTF8 parsing; reject ambiguous keys before building dictionaries."""
    _require(type(expected_sha256) is str and _SHA.fullmatch(expected_sha256),
             "canonical expected file SHA256 required")
    files = _files()
    path = files._path(path, exposed_input=True)
    files._no_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode), "regular review JSON file required")
        _require(info.st_size <= MAX_FILE_BYTES, "review JSON exceeds byte bound")
        data = stream.read(MAX_FILE_BYTES + 1)
        _require(len(data) == info.st_size and len(data) <= MAX_FILE_BYTES,
                 "review input changed while reading or exceeds byte bound")
    observed = dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    _require(observed["sha256"] == expected_sha256, "review file SHA256 mismatch")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_nonfinite)
        _raw(value)
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as error:
        raise ValueError("strict finite UTF8 JSON required: " + str(error)) from error
    _require(files._observed_binding(path) == observed, "review file drifted after parsing")
    return value, observed


def _check_scope(receipt, validation, guide):
    for value in (receipt, validation, guide, *receipt["items"]):
        _require(all(value.get(field) is False for field in _FALSE_FIELDS),
                 "binding review recording cannot establish semantic or identity authority")
    for value in (receipt, validation):
        _require(all(type(value.get(field)) is int and value[field] == 0 for field in (
            "human_reviews_authenticated", "independent_reviews_authenticated")),
            "binding review recording cannot authenticate reviewers")
    for value in (receipt, guide):
        _require(all(type(value.get(field)) is int and value[field] == 0 for field in (
            "model_calls", "provider_calls", "encoder_calls", "prover_calls")),
            "binding review recording cannot call models or provers")
        _require(all(value.get(field) is False for field in (
            "training_executed", "automatic_adjudication", "submissions_created")),
            "binding review recording cannot generate supervision or adjudication")
    for item in receipt["items"]:
        masks = item.get("masks")
        _require(type(masks) is dict and set(masks) == set(_MASKS)
                 and all(type(value) is int and value == 0 for value in masks.values()),
                 "all binding review fit and evaluation masks must remain zero")
        _require(item.get("external_adjudication_status") == "pending"
                 and item.get("independent_adjudication_completed") is False,
                 "binding reviews require external adjudication")


def run_binding_review_recording(packet_path, expected_packet_file_sha256, submission_bindings,
                                output_directory, repository_root=None):
    """Record SHA-pinned declarations in a fresh private evidence directory.

    An empty submission list is a readiness check. Agreement never activates
    training or evaluation masks. File permissions and names do not authenticate
    reviewers or supply a complete filesystem security boundary.
    """
    files = _files()
    executing_root = Path(__file__).resolve().parents[3]
    root = executing_root if repository_root is None else files._path(repository_root).resolve()
    _require(root == executing_root, "recording must use the executing canonical checkout")
    directory = files._path(output_directory)
    files._no_symlink_components(directory, allow_missing=True)
    _require(not directory.exists(), "output directory already exists; fresh evidence required")
    _require(type(submission_bindings) is list and len(submission_bindings) <= MAX_SUBMISSIONS,
             "bounded submission path/SHA256 bindings required")
    for reference in submission_bindings:
        _require(type(reference) is dict and set(reference) == {"path", "sha256"},
                 "closed submission path/SHA256 binding required")
    sources = [files._observed_binding(root / relative) for relative in _SOURCE_FILES]
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_review_admission as annotations,
    )
    from ipfs_datasets_py.logic.legal_ir import canonical_binding_review as adapter

    for module, relative in ((adapter, _SOURCE_FILES[1]), (files, _SOURCE_FILES[2]),
                             (annotations, _SOURCE_FILES[3])):
        _require(Path(module.__file__).resolve() == root / relative,
                 "recording dependency import comes from another checkout")
    packet, packet_binding = _read_pinned_json(packet_path, expected_packet_file_sha256)
    packet_pin = _digest(packet)
    preparation = adapter.validate_blank_packet(packet, expected_packet_sha256=packet_pin)
    payloads, inputs = [], []
    for reference in submission_bindings:
        payload, observed = _read_pinned_json(reference["path"], reference["sha256"])
        payloads.append(payload)
        inputs.append(observed)
    receipt = adapter.record_reviews(packet, payloads, expected_packet_sha256=packet_pin)
    validation = adapter.validate_recording(receipt, packet, payloads, expected_packet_sha256=packet_pin)
    guide = adapter.submission_guide()
    _check_scope(receipt, validation, guide)
    receipt_binding = files._output_binding(directory, "receipt_private.json", receipt)
    guide_binding = files._output_binding(directory, "submission_guide.json", guide)
    report = dict(
        schema=SCHEMA, status=receipt["status"], organizer_private=True,
        packet_binding=packet_binding, reviewer_packet_sha256=packet_pin,
        packet_content_digest_recipe="sha256_sorted_compact_utf8_json_no_nan_no_newline",
        file_digest_recipe="sha256_exact_file_bytes", submission_bindings=inputs,
        source_bindings=sources, preparation_validation=preparation, recording_validation=validation,
        receipt_binding=receipt_binding, submission_guide_binding=guide_binding,
        output_directory=str(directory), submission_count=len(payloads), status_counts=receipt["status_counts"],
        source_only_packet=True, organizer_manifest_accessed=False, candidate_or_reference_accessed=False,
        completed_independent_reviews=0, reviewer_identity_authenticated=False,
        reviewer_independence_authenticated=False, independent_semantic_review_completed=False,
        source_fidelity_established=False, semantic_gold_created=False,
        actual_training_or_evaluation_admission=False, proof_authority=False, qualified=False, accepted=False,
        model_calls=0, provider_calls=0, encoder_calls=0, prover_calls=0,
        training_executed=False, automatic_adjudication=False, submissions_created=False,
        complete_dependency_manifest=False, dependency_binding_scope="five_explicit_owners_not_dependency_closure",
    )
    report["content_sha256"] = _digest(report)
    files._encoded_json(report)
    files._recheck_bindings([*sources, packet_binding, *inputs])
    files._no_symlink_components(directory, allow_missing=True)
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(directory, 0o700)
    _require(files._write_json(directory, "receipt_private.json", receipt) == receipt_binding,
             "receipt publication differs from planned binding")
    _require(files._write_json(directory, "submission_guide.json", guide) == guide_binding,
             "guide publication differs from planned binding")
    files._write_json(directory, "report_private.json", report)
    return report


__all__ = ["run_binding_review_recording"]
