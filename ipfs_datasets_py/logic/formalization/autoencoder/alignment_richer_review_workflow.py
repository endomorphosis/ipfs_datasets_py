"""Run a bounded richer-review recording workflow with immutable input bindings.

No reviews, identities, attestations, semantic labels, or proof evidence are
created here. Submitted declarations stay private and require external review
authentication and adjudication before any independent semantic claim.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

SCHEMA = "alignment-richer-review-admission-artifact/v1"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SUBMISSIONS = 20
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FORBIDDEN = re.compile(r"(^|[-_])(sealed|holdout|heldout|final|test)([-_.]|$)", re.IGNORECASE)
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review_workflow.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review_admission.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_panel.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_review_admission.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
    "scripts/ops/legal_ir/admit_alignment_richer_reviews.py",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("bounded finite UTF-8 JSON required") from error


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _path(value, *, exposed_input=False):
    _require(type(value) is str or isinstance(value, Path), "text or Path required")
    text = str(value)
    _require(0 < len(text) <= 4096 and "\x00" not in text, "bounded path required")
    path = Path(os.path.abspath(text))
    if exposed_input:
        _require(not any(_FORBIDDEN.search(part) for part in path.parts),
                 "sealed/final/test review input path forbidden")
    return path


def _no_symlink_components(path, *, allow_missing=False):
    """Check existing path components; a path name is only a scope heuristic."""
    for component in reversed((path, *path.parents)):
        try:
            info = component.lstat()
        except FileNotFoundError:
            _require(allow_missing, "review path does not exist")
            continue
        _require(not stat.S_ISLNK(info.st_mode), "symlink review path forbidden")
        if component != path:
            _require(stat.S_ISDIR(info.st_mode), "review parent must be a directory")


def _observed_binding(path):
    path = _path(path)
    _no_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode), "regular evidence file required")
        _require(info.st_size <= MAX_FILE_BYTES, "evidence file exceeds byte bound")
        raw = stream.read(MAX_FILE_BYTES + 1)
        _require(len(raw) == info.st_size and len(raw) <= MAX_FILE_BYTES,
                 "evidence file changed during reading or exceeds bound")
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _read_pinned_json(path, expected_sha256):
    _require(type(expected_sha256) is str and _SHA.fullmatch(expected_sha256),
             "canonical expected SHA256 required")
    path = _path(path, exposed_input=True)
    _no_symlink_components(path)
    from .alignment_review_admission import read_alignment_review_file

    value = read_alignment_review_file(path, expected_sha256=expected_sha256)
    binding = _observed_binding(path)
    _require(binding["sha256"] == expected_sha256, "review file drifted after reading")
    return value, binding


def _recheck_bindings(bindings):
    for binding in bindings:
        _require(_observed_binding(binding["path"]) == binding,
                 "bound review input or implementation changed during execution")


def _check_scope(receipt, validation, guide):
    """Keep this recording workflow unqualified if a helper contract drifts.

    These independent metadata checks do not attest arbitrary runtime code or
    authenticate a submitted review. Exact admission replay remains separate.
    """
    authority_fields = ("qualified", "production_admitted", "independent_fidelity_available",
                        "source_fidelity_established", "source_semantics_verified", "proof_authority",
                        "reviewer_identity_attestations_created", "reviewer_attestations_created",
                        "reviewer_independence_authenticated", "source_author_independence_authenticated")
    for value in (receipt, validation, guide, *receipt["items"]):
        _require(all(value.get(field) is False for field in authority_fields),
                 "richer review recording cannot grant authority")
    for value in (receipt, validation):
        _require(value.get("human_reviews_authenticated") == 0
                 and type(value.get("human_reviews_authenticated")) is int
                 and value.get("independent_reviews_authenticated") == 0
                 and type(value.get("independent_reviews_authenticated")) is int,
                 "richer review recording cannot authenticate reviewers")
    for value in (receipt, guide):
        _require(all(type(value.get(field)) is int and value[field] == 0
                     for field in ("model_calls", "provider_calls", "encoder_calls", "prover_calls"))
                 and value.get("automatic_adjudication") is False,
                 "richer review recording cannot create model or adjudication evidence")
    _require(all(receipt.get(field) is False for field in (
        "candidate_aware_computation", "authored_reference_scoring_executed",
        "reference_used_to_resolve_disputes", "submissions_created", "training_executed",
    )), "richer review recording cannot synthesize annotations or use candidate answers")


def _encoded_json(value):
    raw = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                     allow_nan=False).encode("utf-8") + b"\n"
    _require(len(raw) <= MAX_FILE_BYTES, "review output exceeds byte bound")
    return raw


def _output_binding(directory, name, value):
    raw = _encoded_json(value)
    return {"path": str(directory / name), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _write_json(directory, name, value):
    raw = _encoded_json(value)
    path = directory / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def run_richer_review_admission(bundle_path, expected_bundle_sha256, submission_bindings,
                               output_directory, repository_root=None):
    """Record zero or more submitted payloads under the existing blank contract.

    Fresh evidence is written only after input, source, and replay validation.
    Restrictive permissions do not authenticate reviewers or provide a complete
    filesystem security boundary. The dependency manifest is explicitly partial.
    """
    executing_root = Path(__file__).resolve().parents[4]
    root = executing_root if repository_root is None else _path(repository_root).resolve()
    _require(root == executing_root, "review workflow must use the executing canonical checkout")
    directory = _path(output_directory)
    _no_symlink_components(directory, allow_missing=True)
    _require(not directory.exists(), "output directory already exists; choose fresh evidence")
    _require(type(submission_bindings) is list and len(submission_bindings) <= MAX_SUBMISSIONS,
             "bounded submission bindings required")
    for binding in submission_bindings:
        _require(type(binding) is dict and set(binding) == {"path", "sha256"},
                 "closed submission path/SHA256 binding required")

    sources = [_observed_binding(root / relative) for relative in _SOURCE_FILES]
    from ipfs_datasets_py.logic.legal_ir import canonical_contracts

    from . import alignment_review_admission as reader
    from . import alignment_richer_panel as panel
    from . import alignment_richer_review as preparation
    from . import alignment_richer_review_admission as admission

    for module, relative in (
        (preparation, _SOURCE_FILES[2]), (admission, _SOURCE_FILES[1]),
        (reader, _SOURCE_FILES[4]), (panel, _SOURCE_FILES[3]),
        (canonical_contracts, _SOURCE_FILES[5]),
    ):
        _require(Path(module.__file__).resolve() == root / relative,
                 "review dependency import comes from another checkout")

    bundle, bundle_binding = _read_pinned_json(bundle_path, expected_bundle_sha256)
    preparation_validation = preparation.validate_richer_review_bundle(bundle)
    payloads, inputs = [], []
    for binding in submission_bindings:
        payload, observed = _read_pinned_json(binding["path"], binding["sha256"])
        payloads.append(payload)
        inputs.append(observed)
    receipt = admission.admit_richer_reviews(bundle, payloads)
    replay = admission.validate_richer_review_admission(receipt, bundle, payloads)
    guide = admission.richer_review_submission_guide()
    _check_scope(receipt, replay, guide)
    _raw(guide)
    _require(len(_raw(receipt)) <= MAX_FILE_BYTES, "receipt exceeds bounded output")
    bound_inputs = [bundle_binding, *inputs]
    receipt_binding = _output_binding(directory, "receipt_private.json", receipt)
    guide_binding = _output_binding(directory, "submission_guide.json", guide)
    report = {
        "schema": SCHEMA, "status": receipt["status"],
        "evaluation_role": "exposed_development", "organizer_private": True,
        "bundle_binding": bundle_binding, "submission_bindings": inputs,
        "source_bindings": sources, "preparation_validation": preparation_validation,
        "admission_validation": replay, "receipt": receipt,
        "receipt_binding": receipt_binding, "submission_guide_binding": guide_binding,
        "output_directory": str(directory), "submission_count": len(payloads),
        "completed_independent_reviews": 0,
        "reviewer_identity_authenticated": False,
        "source_author_independence_authenticated": False,
        "independent_fidelity_available": False, "source_semantics_verified": False,
        "proof_authority": False, "qualified": False, "production_admitted": False,
        "complete_dependency_manifest": False,
        "dependency_binding_scope": "seven_explicit_owner_source_files_not_dependency_closure",
        "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0,
        "training_executed": False, "original_validation_accessed": False,
        "sealed_final_test_accessed": False, "authored_reference_comparison_executed": False,
        "new_reviews_created": False, "automatic_adjudication": False,
        "limitations": [
            "Exact integrity and declared-review agreement do not authenticate identity or independence.",
            "Only the already exposed authored panel is admitted; natural-source corpus review is a separate scope.",
            "Annotation structure is validated without deciding whether an interpretation is correct.",
            "The private bundle includes authored references solely for closed preparation validation.",
            "No authored reference is used to score, select, or resolve submitted annotations.",
            "Pending, ambiguous, unsupported, and disputed declarations require external human work.",
            "Listed source bindings do not attest the interpreter or a complete dependency closure.",
        ],
    }
    report["report_sha256"] = _digest(report)
    _encoded_json(report)
    _recheck_bindings([*sources, *bound_inputs])
    _no_symlink_components(directory, allow_missing=True)
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(directory, 0o700)
    _require(_write_json(directory, "receipt_private.json", receipt) == receipt_binding,
             "receipt publication differs from planned binding")
    _require(_write_json(directory, "submission_guide.json", guide) == guide_binding,
             "guide publication differs from planned binding")
    _write_json(directory, "report_private.json", report)
    return report


__all__ = ["run_richer_review_admission"]
