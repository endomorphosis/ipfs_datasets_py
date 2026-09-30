"""Immutable native numeric-state/decoder-head candidates in the local registry.

This separate envelope leaves the numerical backend and its historical four-key
checkpoints untouched. One artifact and one model-version transaction bind a
head to a numeric candidate. Registration grants no proof or promotion authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from . import autoencoder_projection_features as features
from .autoencoder_modality_contracts import ModalityContract

SCHEMA = "native-formal-projection-candidate/v1"
VARIANT_SCHEMA = "native-formal-projection-variant/v1"
MAX_CANDIDATE_BYTES = 32 * 1024 * 1024
DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir")
_ENVELOPE_FIELDS = {"schema", "contract", "feature_space", "state", "report", "decoder_head"}
_REPORT_FIELDS = {"schema", "backend", "contract_sha256", "feature_space_sha256", "base_state_sha256",
    "training_targets_sha256", "tuning_targets_sha256", "configuration", "deadline_enforcement",
    "attempted_epochs", "selected_total_epochs", "training_target_count", "tuning_target_count",
    "before", "after", "epochs", "improved", "stopped_reason", "elapsed_seconds", "train_coverage",
    "tuning_coverage", "heldout_canary", "representation", "weights_downloaded", "lake_executed", *features.FALSE}


class FormalCandidateError(ValueError):
    """Incompatible, drifted or corrupt numeric/decoder candidate binding."""


def _require(condition, message):
    if not condition:
        raise FormalCandidateError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError) as error:
        raise FormalCandidateError("candidate must contain finite JSON data") from error


def _decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate candidate JSON key")
            result[key] = value
        return result
    def reject(value):
        raise FormalCandidateError("nonfinite candidate JSON number")
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    except (ValueError, UnicodeError) as error:
        raise FormalCandidateError("invalid candidate JSON") from error


def _copy(value):
    return _decode(_raw(value))


def _hash(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _digest(value, label, *, optional=False):
    _require((optional and value is None) or
             (type(value) is str and re.fullmatch("[0-9a-f]{64}", value)), label + " must be an exact SHA256")


def _adapter_guard(contract):
    from ...logic.formalization.autoencoder import domain_targets, ui_targets
    _require(contract.domain in DOMAINS, "unsupported native formal candidate domain")
    adapter = ui_targets if contract.domain == "ui_ux_ir" else domain_targets
    _require(contract.adapter.identifier == "native-domain-target-adapter" and contract.adapter.version == "1"
             and contract.adapter.sha256 == hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(),
             "installed native target adapter differs from contract")


def _validate(contract, space, result, decoder_head):
    from .native_formal_decoder import validate_decoder
    _require(type(contract) is ModalityContract, "typed modality contract required")
    _require(type(result) is dict and set(result) == {"state", "report"}, "closed native training result required")
    features._contract(contract, space)
    _adapter_guard(contract)
    state, report = result["state"], result["report"]
    features._validate_state(contract, space, state)
    _require(type(report) is dict and set(report) == _REPORT_FIELDS and report.get("schema") == "native-projection-feature-training/v1"
             and report.get("backend") == features.BACKEND, "native v1 training report required")
    _require(report.get("contract_sha256") == contract.sha256
             and report.get("feature_space_sha256") == features.digest(space),
             "candidate report contract or feature space differs")
    _require(all(report.get(key) is False for key in features.FALSE)
             and report.get("weights_downloaded") is False and report.get("lake_executed") is False
             and report.get("heldout_canary") is False, "candidate report cannot claim qualification or unperformed checks")
    for key in ("training_targets_sha256", "tuning_targets_sha256"):
        _digest(report.get(key), key)
    _digest(report.get("base_state_sha256"), "base_state_sha256", optional=True)
    _require(report["tuning_targets_sha256"] == state["tuning_targets_sha256"],
             "training report tuning sources differ from numeric state")
    _require(type(report.get("selected_total_epochs")) is int and report["selected_total_epochs"] == state["completed_epochs"],
             "training report selected epoch differs from numeric state")
    _require(type(report.get("training_target_count")) is int and 1 <= report["training_target_count"] <= 1024
             and type(report.get("tuning_target_count")) is int and 1 <= report["tuning_target_count"] <= 1024,
             "bounded positive training and tuning source counts required")
    validate_decoder(space, decoder_head)
    return {"contract_sha256": contract.sha256, "feature_space_sha256": features.digest(space),
            "decoder_head_sha256": features.digest(decoder_head)}


def _manifest(contract, bindings):
    return {"schema": VARIANT_SCHEMA, "candidate_schema": SCHEMA,
            "modality_contract": contract.to_dict(), **bindings, **features.FALSE}


def _variant_id(manifest):
    return "formal-modality-" + _hash(manifest)


def formal_variant_id(contract, decoder_head):
    """Return compound identity; full validation requires the bound feature space."""
    _require(type(contract) is ModalityContract and type(decoder_head) is dict,
             "typed contract and decoder head required")
    _digest(decoder_head.get("feature_space_sha256"), "decoder feature_space_sha256")
    bindings = {"contract_sha256": contract.sha256,
                "feature_space_sha256": decoder_head["feature_space_sha256"],
                "decoder_head_sha256": features.digest(decoder_head)}
    return _variant_id(_manifest(contract, bindings))


def _metadata(bindings):
    return {"schema": SCHEMA, "training_purpose": "formal_projection_reconstruction",
            **bindings, **features.FALSE}


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(registry, row):
    from ...duckdb_control.autoencoder_registry import SCHEMA as REGISTRY_SCHEMA, content_identity
    _require(type(row) is dict and set(row) == {"version_id", "variant_id", "parent_version_id", "artifact", "metadata"},
             "closed registry version record required")
    expected = content_identity({"schema": REGISTRY_SCHEMA, **{
        key: row[key] for key in ("variant_id", "parent_version_id", "artifact", "metadata")}})
    _require(row["version_id"] == expected, "registry version content identity differs")
    artifact = row["artifact"]
    _require(type(artifact) is dict and set(artifact) == {"bytes", "sha256"}
             and type(artifact["bytes"]) is int and 0 < artifact["bytes"] <= MAX_CANDIDATE_BYTES,
             "candidate exceeds checkpoint byte bound")
    _digest(artifact["sha256"], "artifact sha256")
    path = registry.artifact_path(artifact)
    _require(not path.is_symlink() and not path.parent.is_symlink(), "candidate artifact may not use symlink aliases")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size == artifact["bytes"],
                 "candidate artifact size or file type differs")
        raw = stream.read(MAX_CANDIDATE_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(_file_identity(before) == _file_identity(after) == _file_identity(path.stat())
             and len(raw) == artifact["bytes"] and hashlib.sha256(raw).hexdigest() == artifact["sha256"],
             "candidate artifact changed or digest differs")
    registry.verify_artifact(artifact)
    saved = _decode(raw)
    _require(type(saved) is dict and set(saved) == _ENVELOPE_FIELDS and saved["schema"] == SCHEMA,
             "closed formal candidate envelope required")
    return saved


def _validated_row(registry, row, domain):
    saved = _read(registry, row)
    contract = ModalityContract.from_dict(saved["contract"])
    _require(contract.domain == domain, "formal candidate belongs to another domain")
    bindings = _validate(contract, saved["feature_space"],
                         {"state": saved["state"], "report": saved["report"]}, saved["decoder_head"])
    manifest = _manifest(contract, bindings)
    _require(row["variant_id"] == _variant_id(manifest), "formal candidate variant differs from bound contract or decoder")
    _require(registry.get_variant(row["variant_id"])["manifest"] == manifest,
             "immutable formal variant manifest differs")
    _require(row["metadata"] == _metadata(bindings), "formal candidate metadata differs")
    return saved, contract, bindings


def _parent(registry, parent_id, domain, variant_id, base_sha, decoder_head):
    if parent_id is None:
        _require(base_sha is None, "resumed formal candidate requires its exact registry parent")
        return
    row = registry.get_version(parent_id)
    _require(row["variant_id"] == variant_id, "formal parent variant or decoder head mismatch")
    saved, _, _ = _validated_row(registry, row, domain)
    _require(features.digest(saved["decoder_head"]) == features.digest(decoder_head), "formal parent decoder head differs")
    _require(features.digest(saved["state"]) == base_sha, "formal candidate numerical parent differs from registry parent")


def register_formal_candidate(registry, contract, space, result, decoder_head, directory, *, parent_version_id=None):
    """Persist one bound candidate; changed decoder heads require new variants."""
    space, result, decoder_head = _copy(space), _copy(result), _copy(decoder_head)
    bindings = _validate(contract, space, result, decoder_head)
    manifest = _manifest(contract, bindings)
    variant_id = _variant_id(manifest)
    _parent(registry, parent_version_id, contract.domain, variant_id,
            result["report"]["base_state_sha256"], decoder_head)
    envelope = {"schema": SCHEMA, "contract": contract.to_dict(), "feature_space": space,
                "state": result["state"], "report": result["report"], "decoder_head": decoder_head}
    raw = _raw(envelope)
    _require(len(raw) <= MAX_CANDIDATE_BYTES, "candidate exceeds checkpoint byte bound")
    directory = Path(directory)
    _require(not directory.exists(), "fresh formal candidate staging directory required")
    directory.mkdir(parents=True)
    path = directory / "candidate.json"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    artifact = registry.stage_artifact(path, hashlib.sha256(raw).hexdigest())
    # Recheck source-bound contracts after disk I/O and before registry mutation.
    _require(_validate(contract, space, result, decoder_head) == bindings, "formal candidate producer changed during preparation")
    registry.register_variant("formal-variant:" + _hash(manifest), variant_id, manifest)
    receipt = registry.register_version("formal-candidate:" + artifact["sha256"], variant_id, artifact,
                                        _metadata(bindings), parent_version_id)
    return {"version_id": receipt["version_id"], "variant_id": variant_id, "artifact": artifact,
            "decoder_head_sha256": bindings["decoder_head_sha256"], **features.FALSE}


def load_formal_candidate(registry, version_id, domain):
    """Read and validate an exact local version without training or promotion."""
    _require(domain in DOMAINS, "unsupported native formal candidate domain")
    row = registry.get_version(version_id)
    saved, contract, bindings = _validated_row(registry, row, domain)
    _parent(registry, row["parent_version_id"], domain, row["variant_id"],
            saved["report"]["base_state_sha256"], saved["decoder_head"])
    _require(_validate(contract, saved["feature_space"], {"state": saved["state"], "report": saved["report"]},
                       saved["decoder_head"]) == bindings, "formal candidate producer changed while loading")
    return {**saved, "contract": contract, "version_id": row["version_id"],
            "parent_version_id": row["parent_version_id"], "variant_id": row["variant_id"],
            "decoder_head_sha256": bindings["decoder_head_sha256"]}


__all__ = ["FormalCandidateError", "register_formal_candidate", "load_formal_candidate", "formal_variant_id", "SCHEMA"]
