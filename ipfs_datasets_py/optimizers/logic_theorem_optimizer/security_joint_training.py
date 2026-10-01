"""Run Security source-production and native-family training as one recipe.

The objectives and checkpoints remain separate. Native family inputs must be
explicit typed evidence joined to the same exact source samples and split roles
used by the production decoder. A completed source stage is retained if family
optimization fails; a partial attempt is never reported as complete.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from . import autoencoder_family_training as families
from ...logic.formalization.autoencoder import family_training as targets
from ...logic.formalization.autoencoder.security import security_formula_decoder_continuation as production
from ...logic.security_ir.cvefixes.schemas import CodeUnit

SCHEMA = "security-joint-training/v1"
MAX_BYTES = 32 * 1024 * 1024
FALSE = {"proof_authority": False, "execution_authority": False, "qualified": False,
         "source_semantics_verified": False, "security_specification_inferred": False}


def _require(condition, message):
    if not condition: raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pins():
    return {"joint_recipe": _sha(Path(__file__).read_bytes()), "source_trainer": _sha(Path(production.__file__).read_bytes()),
            "family_trainer": _sha(Path(families.__file__).read_bytes()), "family_targets": _sha(Path(targets.__file__).read_bytes())}


def _save(path, value, *, replace=False):
    raw = _raw(value)
    _require(len(raw) <= MAX_BYTES, "joint receipt exceeds byte bound")
    temporary = path.with_suffix(".pending") if replace else path
    with temporary.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    if replace: os.replace(temporary, path)
    return _sha(raw)


def _load(descriptor):
    _require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"} and descriptor["schema"] == SCHEMA, "closed joint descriptor required")
    path = Path(descriptor["path"])
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES, "bounded joint receipt required")
    raw = path.read_bytes()
    _require(_sha(raw) == descriptor["sha256"], "joint receipt drift")
    saved = json.loads(raw)
    _require(saved.get("schema") == SCHEMA and saved.get("producer") == _pins() and all(saved.get(key) is False for key in FALSE), "joint producer or authority drift")
    target_path = path.parent / "family_targets.json"
    _require(target_path.is_file() and not target_path.is_symlink() and target_path.stat().st_size <= MAX_BYTES and
        _sha(target_path.read_bytes()) == saved["family_targets_sha256"], "joint family target receipt drift")
    _require(saved["source_stage"] == "complete" and saved["status"] in {"complete", "partial"} and
        ((saved["status"] == "complete" and saved["family_stage"] == "complete" and saved["both_objectives_executed"] is True and saved["family_descriptor"] is not None and saved["family_error"] is None) or
         (saved["status"] == "partial" and saved["family_stage"] in {"pending", "failed"} and saved["both_objectives_executed"] is False and saved["family_descriptor"] is None)), "joint stage receipt differs")
    production.load_security_formula_decoder_continuation(saved["source_descriptor"])
    if saved["family_descriptor"] is not None: families._read(saved["family_descriptor"])
    return saved


def _family_rows(rows, role, declared):
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 384, "bounded nonempty typed family inputs required")
    ids, groups, hashes, prepared = set(), set(), set(), []
    fields = {"sample_id", "group_id", "split", "code_unit", "source_bytes", "typed_inputs"}
    for row in rows:
        _require(type(row) is dict and set(row) == fields, "closed typed family row required")
        name, group = row["sample_id"], row["group_id"]
        _require(type(name) is str and name in declared and name not in ids, "unique declared source sample ID required")
        _require(type(group) is str and 0 < len(group) <= 256, "bounded explicit source group required")
        _require(row["split"] == role == declared[name]["split"], "family/source sample split role differs")
        source = row["source_bytes"]
        _require(type(source) is bytes and _sha(source) == declared[name]["source_sha256"], "family bytes differ from declared source sample")
        unit = row["code_unit"]
        _require(type(unit) is CodeUnit and unit.payload.get("body_sha256") == _sha(source) and isinstance(unit.payload.get("body_cid"), str) and unit.payload["body_cid"], "exact native CodeUnit body binding required")
        _require(type(row["typed_inputs"]) in (list, tuple), "explicit native typed evidence sequence required")
        ids.add(name); groups.add(group); hashes.add(_sha(source)); prepared.append(row)
    _require(len(hashes) == len(rows), "duplicate family source bytes")
    return prepared, {"sample_ids": sorted(ids), "groups": sorted(groups), "source_sha256": sorted(hashes)}


def _exclude(train, validation):
    for key in ("sample_ids", "groups", "source_sha256"):
        _require(not set(train[key]) & set(validation[key]), "historical/current family split " + key + " leakage")


def train_security_joint_autoencoder(*, source_samples, parent_source_checkpoint, family_training_inputs,
        family_validation_inputs, output_dir, source_settings=None, family_settings=None,
        parent_descriptor=None, requested_families=None):
    """Run both real objectives; return complete or an explicit partial receipt.

    Family rows have exactly ``sample_id, group_id, split, code_unit,
    source_bytes, typed_inputs``. Source samples use the production trainer's
    explicit train/validation/test format. Every family row joins one such
    sample by both identifier and exact bytes; test samples cannot enter either
    family fitting or selection. Typed evidence is supplied, never inferred
    from a CWE label or silently replaced with the source decoder's AST.
    """
    output = Path(output_dir)
    _require(output.is_absolute() and output.resolve() == output and not output.exists(), "fresh canonical joint output required")
    source_settings = {} if source_settings is None else dict(source_settings)
    family_settings = {} if family_settings is None else dict(family_settings)
    _require(not set(source_settings) - {"epochs", "learning_rate", "minibatch_size", "weight_decay", "label_smoothing", "regression_tolerance", "max_seconds", "seed"}, "unsupported source optimization setting")
    _require(not set(family_settings) - {"epochs", "latent_width", "learning_rate", "minibatch_size", "denoising", "seed", "max_seconds"}, "unsupported family optimization setting")
    producer = _pins()
    parent = None
    if parent_descriptor is not None:
        parent = _load(parent_descriptor)
        _require(parent_source_checkpoint == parent["source_descriptor"], "composite/source parent histories differ")
        _require(not output.is_relative_to(Path(parent_descriptor["path"]).parent), "joint continuation requires an isolated output namespace")
    # Perform source shape and historical-role checks before either optimizer.
    source_parent = production._parent(parent_source_checkpoint)
    source_prepared = production.prepare_security_production_samples(source_samples, historical_splits=production._history(source_parent))
    declared = {item["id"]: {**item, "split": role} for role, rows in source_prepared["splits"].items() for item in rows}
    train_rows, train_inventory = _family_rows(family_training_inputs, "train", declared)
    validation_rows, validation_inventory = _family_rows(family_validation_inputs, "validation", declared)
    _exclude(train_inventory, validation_inventory)
    if parent is not None:
        _require(parent["validation_inventory"] == validation_inventory, "joint continuation requires original family validation panel")
        train_inventory = {key: sorted(set(train_inventory[key]) | set(parent["training_history"][key])) for key in train_inventory}
        _exclude(train_inventory, validation_inventory)
    # Native preparation validates CodeUnit/evidence joins before costly fitting.
    def prepare(rows):
        return [targets.prepare_family_training_targets("security_ir", code_unit=row["code_unit"],
            source_bytes=row["source_bytes"], typed_inputs=row["typed_inputs"], requested_families=requested_families) for row in rows]
    train_targets, validation_targets = prepare(train_rows), prepare(validation_rows)
    _require(all(any(row["ready_for_training"] for row in report["projections"]) for report in train_targets + validation_targets),
        "each family input requires at least one ready native typed projection before fitting")
    _require(_pins() == producer, "joint producer changed during prevalidation")
    source_descriptor = production.train_security_formula_decoder_continuation(samples=source_samples,
        parent_checkpoint=parent_source_checkpoint, output=output / "source", **source_settings)
    source_model = production.load_security_formula_decoder_continuation(source_descriptor)
    target_sha = _save(output / "family_targets.json", {"training": train_targets, "validation": validation_targets})
    receipt = {"schema": SCHEMA, "producer": producer, "status": "partial", "source_stage": "complete", "family_stage": "pending",
        "source_descriptor": source_descriptor, "family_descriptor": None, "parent_descriptor": deepcopy(parent_descriptor),
        "source_parent_descriptor": deepcopy(parent_source_checkpoint), "source_splits": source_prepared["splits"],
        "training_history": train_inventory, "validation_inventory": validation_inventory, "family_targets_sha256": target_sha,
        "requested_families": list(requested_families) if requested_families is not None else None,
        "source_objective": source_model["training"]["algorithm"], "source_optimizer_steps": source_model["training"]["optimizer_steps"],
        "family_objective": None, "family_training_report": None, "family_error": None,
        "both_objectives_executed": False, "parent_modified": False, "test_used_for_fit_or_selection": False,
        "objectives_share_source_splits": True, "objectives_share_weights": False,
        "typed_evidence_scope": "supplied source-bound structural models; source meaning and security specification remain unverified", **FALSE}
    path = output / "receipt.json"
    digest = _save(path, receipt)
    try:
        result = families.train_family_projection_autoencoder(train_targets, validation_targets, output_dir=output / "family",
            parent_descriptor=parent["family_descriptor"] if parent is not None else None, **family_settings)
        _require(_pins() == producer, "joint producer changed during family optimization")
        _require(result["report"]["training_executed"], "family optimizer completed no steps")
        receipt.update(status="complete", family_stage="complete", family_descriptor=result["descriptor"],
            family_objective=result["report"]["objective"], family_training_report=result["report"], both_objectives_executed=True)
    except Exception as exc:
        receipt.update(status="partial", family_stage="failed", family_error={"type": type(exc).__name__, "message": str(exc)[:2000]},
            both_objectives_executed=False)
    digest = _save(path, receipt, replace=True)
    descriptor = {"schema": SCHEMA, "path": str(path), "sha256": digest}
    return {"descriptor": descriptor, "report": receipt}


__all__ = ["SCHEMA", "train_security_joint_autoencoder"]
