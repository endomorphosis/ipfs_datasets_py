"""Optional UIUX native-family training with persistent source/group splits.

Strict DOM/ARIA, declared events/state and verified interface joins are adapted
by the existing UI pipeline. The new numerical lane trains structural native
projection reconstruction; it does not generate formulas from screenshots or
infer missing behavior. Its package and optimizer never replace the old head.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from . import ui_feature_training as legacy
from . import autoencoder_family_training as numerical
from ...logic.formalization.autoencoder import family_training

SCHEMA = "ui-native-family-training/v1"
MAX_BYTES = 32 * 1024 * 1024
FALSE = {"qualified": False, "admitted": False, "formalized": False, "proof_authority": False,
         "execution_authority": False, "source_text_decoder_trained": False}


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _require(condition, message):
    if not condition: raise ValueError(message)


def _producer():
    return {"adapter_sha256": _sha(Path(__file__).read_bytes()),
            "family_targets_sha256": _sha(Path(family_training.__file__).read_bytes()),
            "family_trainer_sha256": _sha(Path(numerical.__file__).read_bytes()),
            "native_ui_producer": legacy.producer_identity()}


def _save(path, value):
    raw = _raw(value)
    _require(len(raw) <= MAX_BYTES, "UI family artifact exceeds byte bound")
    with Path(path).open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return _sha(raw)


def _identity(row):
    return (row.provenance["dataset"], row.provenance["revision"], row.source_id)


def _inventory(prepared):
    return {"groups": sorted({row.group_id for row in prepared}),
            "sources": sorted([list(_identity(row)) for row in prepared]),
            "inputs": sorted(row.input_sha256 for row in prepared)}


def _combine(current, previous):
    return {"groups": sorted(set(current["groups"]) | set(previous["groups"])),
            "sources": sorted([list(value) for value in {tuple(value) for value in current["sources"] + previous["sources"]}]),
            "inputs": sorted(set(current["inputs"]) | set(previous["inputs"]))}


def _exclude(first, second):
    for key in ("groups", "sources", "inputs"):
        one = {tuple(value) if isinstance(value, list) else value for value in first[key]}
        two = {tuple(value) if isinstance(value, list) else value for value in second[key]}
        _require(not one & two, "historical/current UI training/validation " + key + " leakage")


def _read(descriptor):
    _require(type(descriptor) is dict and set(descriptor) == {"schema", "output", "audit_sha256", "model_descriptor"} and descriptor["schema"] == SCHEMA, "closed UI family descriptor required")
    output = Path(descriptor["output"])
    _require(output.is_absolute() and output.resolve() == output and output.is_dir() and not output.is_symlink(), "canonical UI family package required")
    _require({path.name for path in output.iterdir()} == {"audit.json", "targets.json", "model"}, "closed UI family package required")
    path = output / "audit.json"
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES, "bounded UI audit required")
    raw = path.read_bytes(); _require(_sha(raw) == descriptor["audit_sha256"], "UI audit drift")
    audit = json.loads(raw)
    _require(audit.get("schema") == SCHEMA and audit.get("producer") == _producer() and all(audit.get(key) is False for key in FALSE), "UI producer or authority drift")
    _require(audit["model_descriptor"] == descriptor["model_descriptor"], "UI model identity differs")
    model_path = Path(descriptor["model_descriptor"]["path"])
    _require(model_path == output / "model" / "family_checkpoint.json", "UI model escapes package")
    targets_path = output / "targets.json"
    _require(targets_path.is_file() and not targets_path.is_symlink() and targets_path.stat().st_size <= MAX_BYTES and _sha(targets_path.read_bytes()) == audit["targets_sha256"], "UI target receipt drift")
    _exclude(audit["training_history"], audit["validation_inventory"])
    saved, _ = numerical._read(descriptor["model_descriptor"])
    _require(saved["space"]["domain_id"] == "ui_ux_ir", "UI native model domain differs")
    return audit


def train_ui_family_autoencoder(training_rows, validation_rows, *, output_dir, requested_families=None,
        parent_descriptor=None, epochs=24, latent_width=16, learning_rate=.005, minibatch_size=32,
        denoising=.15, seed=1729, max_seconds=120):
    """Train actual native targets and retain all historical split exclusions."""
    output = Path(output_dir)
    _require(output.is_absolute() and output.resolve() == output and not output.exists(), "fresh canonical UI training output required")
    producer = _producer()
    training = legacy.prepare_ui_rows(training_rows, role="training")
    validation = legacy.prepare_ui_rows(validation_rows, role="tuning")
    train_inventory, valid_inventory = _inventory(training), _inventory(validation)
    _exclude(train_inventory, valid_inventory)
    parent_model = None
    if parent_descriptor is not None:
        parent = _read(parent_descriptor)
        _require(not output.is_relative_to(Path(parent_descriptor["output"])), "UI continuation cannot overwrite parent namespace")
        _require(parent["validation_inventory"] == valid_inventory, "UI continuation requires original validation panel")
        train_inventory = _combine(train_inventory, parent["training_history"])
        _exclude(train_inventory, valid_inventory)
        parent_model = parent_descriptor["model_descriptor"]
    def prepare(rows):
        return [family_training.prepare_family_training_targets("ui_ux_ir", ui_training_row=row,
                    requested_families=requested_families) for row in rows]
    train_targets, valid_targets = prepare(training_rows), prepare(validation_rows)
    # Existing native compilation owns slot/behavior semantics; missing families
    # remain explicit frontiers and are masked by the shared numerical trainer.
    result = numerical.train_family_projection_autoencoder(train_targets, valid_targets,
        output_dir=output / "model", parent_descriptor=parent_model, epochs=epochs, latent_width=latent_width,
        learning_rate=learning_rate, minibatch_size=minibatch_size, denoising=denoising, seed=seed, max_seconds=max_seconds)
    _require(_producer() == producer, "UI family producer changed during training")
    targets_sha = _save(output / "targets.json", {"training": train_targets, "validation": valid_targets})
    audit = {"schema": SCHEMA, "producer": producer, "model_descriptor": result["descriptor"],
        "parent_descriptor": deepcopy(parent_descriptor), "parent_modified": False,
        "training_history": train_inventory, "validation_inventory": valid_inventory,
        "training_input_count": len(training), "validation_input_count": len(validation),
        "source_provenance": [dict(row.provenance) for row in training + validation],
        "requested_families": list(requested_families) if requested_families is not None else None,
        "targets_sha256": targets_sha, "training": result["report"],
        "test_rows_used": False, "validation_used_for_selection": True,
        "model_scope": "native_structural_family_reconstruction_not_source_to_formula_decoding", **FALSE}
    digest = _save(output / "audit.json", audit)
    descriptor = {"schema": SCHEMA, "output": str(output), "audit_sha256": digest, "model_descriptor": result["descriptor"]}
    _read(descriptor)
    return {"descriptor": descriptor, "report": audit}


def infer_ui_family_autoencoder(descriptor, rows):
    """Reconstruct native projection features with frozen selected weights."""
    audit = _read(descriptor)
    prepared = legacy.prepare_ui_rows(rows, role="inference")
    targets = [family_training.prepare_family_training_targets("ui_ux_ir", ui_training_row=row,
                   requested_families=audit["requested_families"]) for row in rows]
    result = numerical.infer_family_projection_autoencoder(descriptor["model_descriptor"], targets)
    _require(_producer() == audit["producer"], "UI family producer changed during inference")
    return {"schema": SCHEMA, "checkpoint": deepcopy(descriptor), "input_sha256": [row.input_sha256 for row in prepared],
            "native_inference": result, "formulas_generated": False, "training_steps": 0, **FALSE}


__all__ = ["train_ui_family_autoencoder", "infer_ui_family_autoencoder", "SCHEMA"]
