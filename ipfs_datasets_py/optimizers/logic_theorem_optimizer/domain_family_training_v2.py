"""Source-bound Security/UIUX/Legal recipes for the shared v2 family head.

Native targets, supervised source decoding, and structural reconstruction are
separate objects. Security may additionally continue its existing source head;
its inherited weights are never replaced by a fresh family-head initializer.
All split/provenance checks and native target preparation precede optimization.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from . import autoencoder_family_training_v2 as numerical
from ...logic.formalization.autoencoder import family_training_v2 as native
from ...logic.formalization.autoencoder import ui_training_inputs
from ...logic.formalization.autoencoder.security import security_formula_decoder_continuation as source_decoder
from ...logic.security_ir.cvefixes.schemas import CodeUnit

SCHEMA = "domain-native-family-training/v2"
DOMAINS = {"security_ir", "ui_ux_ir", "legal_ir"}
MAX_BYTES = 64 * 1024 * 1024
FALSE = {"qualified": False, "admitted": False, "formalized": False, "proof_authority": False,
         "execution_authority": False, "source_semantics_verified": False}
SETTINGS = {"epochs", "latent_width", "learning_rate", "minibatch_size", "denoising", "ridge", "patience", "seed", "max_seconds"}
SOURCE_SETTINGS = {"epochs", "learning_rate", "minibatch_size", "weight_decay", "label_smoothing", "regression_tolerance", "max_seconds", "seed"}


def _require(condition, message):
    if not condition: raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _pins():
    return {"recipe": _sha(Path(__file__).read_bytes()), "native_targets": _sha(Path(native.__file__).read_bytes()),
        "numerical_trainer": _sha(Path(numerical.__file__).read_bytes()), "source_continuation": _sha(Path(source_decoder.__file__).read_bytes()),
        "ui_input_adapter": _sha(Path(ui_training_inputs.__file__).read_bytes())}


def _save(path, value, *, replace=False):
    raw = _raw(value)
    _require(len(raw) <= MAX_BYTES, "domain artifact exceeds byte bound")
    temporary = path.with_suffix(".pending") if replace else path
    with temporary.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    if replace: os.replace(temporary, path)
    return _sha(raw)


def _read(descriptor):
    _require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"} and descriptor["schema"] == SCHEMA, "closed domain recipe descriptor required")
    path = Path(descriptor["path"])
    _require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES, "canonical bounded recipe artifact required")
    raw = path.read_bytes()
    _require(_sha(raw) == descriptor["sha256"], "domain recipe drift")
    saved = json.loads(raw)
    _require(saved.get("schema") == SCHEMA and saved.get("domain_id") in DOMAINS and saved.get("producer") == _pins() and all(saved.get(key) is False for key in FALSE), "domain producer or authority drift")
    targets = path.parent / "targets.json"
    _require(targets.is_file() and not targets.is_symlink() and targets.stat().st_size <= MAX_BYTES and _sha(targets.read_bytes()) == saved["targets_sha256"], "domain target artifact drift")
    _exclude(saved["training_history"], saved["validation_inventory"])
    _require(saved["status"] in {"complete", "partial"}, "invalid domain recipe stage")
    if saved["source_descriptor"] is not None:
        _require(saved["domain_id"] == "security_ir", "source production head belongs to SecurityIR")
        source_decoder.load_security_formula_decoder_continuation(saved["source_descriptor"])
    if saved["family_descriptor"] is not None:
        numerical._read(saved["family_descriptor"])
    _require((saved["status"] == "complete") == (saved["family_descriptor"] is not None and saved["family_error"] is None), "domain completion receipt differs")
    return saved


def _inventory(bindings):
    return {"source_ids": sorted(row["source_id"] for row in bindings),
            "groups": sorted({row["group_id"] for row in bindings}),
            "source_content_sha256": sorted(row["source_content_sha256"] for row in bindings),
            "typed_source_digests": sorted(row["typed_source_digest"] for row in bindings)}


def _exclude(training, validation):
    for key in training:
        _require(not set(training[key]) & set(validation[key]), "historical/current domain split " + key + " leakage")


def _merge(one, two):
    return {key: sorted(set(one[key]) | set(two[key])) for key in one}


def _prepare(domain, rows, *, role, requested_families):
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 384, "bounded nonempty domain rows required")
    roles = {"train"} if role == "training" else {"validation", "valid", "tuning"} if role == "validation" else {"train", "validation", "valid", "tuning", "test", "canary", "inference"}
    reports, bindings, identities, content = [], [], set(), set()
    for row in rows:
        _require(type(row) is dict and set(row) == {"source_id", "group_id", "split", "inputs"}, "closed domain row with explicit source/group/split/inputs required")
        _require(all(type(row[key]) is str and 0 < len(row[key]) <= 512 for key in ("source_id", "group_id", "split")), "bounded explicit source/group/split identity required")
        _require(row["split"] in roles, "test/canary rows cannot enter fitting or selection")
        _require(row["source_id"] not in identities, "duplicate domain source identity")
        inputs = row["inputs"]
        _require(type(inputs) is dict, "native domain input mapping required")
        required = {"security_ir": {"code_unit", "source_bytes", "typed_inputs"},
                    "ui_ux_ir": {"ui_training_row"}, "legal_ir": {"document", "source_text"}}[domain]
        _require(required <= set(inputs) <= required | {"supplemental_inputs"}, "domain input fields differ")
        if domain == "security_ir":
            raw, unit = inputs["source_bytes"], inputs["code_unit"]
            _require(type(raw) is bytes and type(unit) is CodeUnit and unit.payload.get("body_sha256") == _sha(raw), "exact Security source bytes and CodeUnit body binding required")
            content_sha = _sha(raw)
        elif domain == "ui_ux_ir":
            ui = ui_training_inputs.prepare_ui_training_row(inputs["ui_training_row"])
            _require(row["source_id"] == ui.source_id and row["group_id"] == ui.group_id and row["split"] == ui.provenance["split"], "UI envelope cannot relabel native source/group/split provenance")
            # Dataset split/row/group labels cannot hide the same underlying UI
            # declaration on both sides of the train/validation boundary.
            content_sha = _sha(_raw({key: value for key, value in inputs["ui_training_row"].items() if key != "provenance"}))
        else:
            text = inputs["source_text"]
            _require(type(text) is str and text.strip(), "exact nonempty Legal source text required")
            content_sha = _sha(text.encode())
        _require(content_sha not in content, "duplicate exact domain source content")
        report = native.prepare_family_training_targets_v2(domain, requested_families=requested_families, **inputs)
        _require(any(projection["ready_for_training"] for projection in report["projections"]), "each source requires at least one ready actual native target")
        reports.append(report)
        bindings.append({"source_id": row["source_id"], "group_id": row["group_id"], "split": row["split"],
            "source_content_sha256": content_sha, "typed_source_digest": report["source_digest"]})
        identities.add(row["source_id"]); content.add(content_sha)
    return reports, bindings


def prepare_domain_family_rows_v2(domain_id, rows, *, role="training", requested_families=None):
    """Preflight native projections and publish the source/split audit to callers."""
    _require(domain_id in DOMAINS and role in {"training", "validation", "inference"}, "supported domain and explicit data role required")
    reports, bindings = _prepare(domain_id, rows, role=role, requested_families=requested_families)
    return {"reports": reports, "bindings": bindings, "inventory": _inventory(bindings)}


def train_domain_family_autoencoder_v2(domain_id, training_rows, validation_rows, *, output_dir,
        parent_descriptor=None, requested_families=None, source_samples=None,
        parent_source_checkpoint=None, source_settings=None, **settings):
    """Fit actual applicable native targets with historical split exclusion.

    Common rows are ``{source_id,group_id,split,inputs}``. UI inputs contain the
    strict original ``ui_training_row``; Legal inputs contain ``document`` and
    exact ``source_text``; Security inputs contain native ``code_unit``, exact
    ``source_bytes`` and ``typed_inputs``. All accept ``supplemental_inputs`` of
    source-bound native evidence. With Security ``source_samples``, the existing
    full-weight source decoder continuation runs before the separate family
    fitter; no family initialization is applied to source-decoder weights.
    """
    _require(domain_id in DOMAINS, "supported domain required")
    _require(not set(settings) - SETTINGS, "unknown numerical family setting")
    _require(source_settings is None or type(source_settings) is dict and not set(source_settings) - SOURCE_SETTINGS, "unknown source optimization setting")
    output = Path(output_dir)
    _require(output.is_absolute() and output.resolve() == output and not output.exists(), "fresh canonical domain output required")
    source_enabled = source_samples is not None
    _require((domain_id == "security_ir" or not source_enabled and parent_source_checkpoint is None and source_settings is None) and
             (source_enabled == (parent_source_checkpoint is not None)), "Security source samples and inherited checkpoint must be supplied together")
    _require(source_enabled or source_settings is None, "source settings require source training stage")
    producer = _pins()
    parent = _read(parent_descriptor) if parent_descriptor is not None else None
    if parent is not None:
        _require(parent["domain_id"] == domain_id, "domain checkpoint identity differs")
        _require(not output.is_relative_to(Path(parent_descriptor["path"]).parent), "domain continuation requires isolated output namespace")
        _require(parent["requested_families"] == (list(requested_families) if requested_families is not None else None), "family selection changed on continuation")
        _require((parent["source_descriptor"] is not None) == source_enabled, "continuation cannot remove or invent a source stage")
        if source_enabled: _require(parent_source_checkpoint == parent["source_descriptor"], "composite/source parent histories differ")
    prepared_source = None
    if source_enabled:
        source_parent = source_decoder._parent(parent_source_checkpoint)
        prepared_source = source_decoder.prepare_security_production_samples(source_samples, historical_splits=source_decoder._history(source_parent))
        declared = {row["id"]: (split, row["source_sha256"]) for split, rows in prepared_source["splits"].items() for row in rows}
        for role, rows in (("train", training_rows), ("validation", validation_rows)):
            for row in rows:
                _require(type(row) is dict and row.get("source_id") in declared and type(row.get("inputs")) is dict and type(row["inputs"].get("source_bytes")) is bytes, "family row must identify a declared Security source sample")
                _require(declared[row["source_id"]] == (role, _sha(row["inputs"]["source_bytes"])), "Security family/source hash or split role differs")
    train = prepare_domain_family_rows_v2(domain_id, training_rows, role="training", requested_families=requested_families)
    validation = prepare_domain_family_rows_v2(domain_id, validation_rows, role="validation", requested_families=requested_families)
    history = train["inventory"]
    if parent is not None:
        _require(parent["validation_inventory"] == validation["inventory"], "original fixed domain validation panel required")
        history = _merge(history, parent["training_history"])
    _exclude(history, validation["inventory"])
    _require(_pins() == producer, "domain producer changed during prevalidation")
    source_descriptor = None
    if source_enabled:
        source_descriptor = source_decoder.train_security_formula_decoder_continuation(samples=source_samples,
            parent_checkpoint=parent_source_checkpoint, output=output / "source", **(source_settings or {}))
    else:
        output.mkdir(parents=True)
    target_sha = _save(output / "targets.json", {"training": train["reports"], "validation": validation["reports"]})
    receipt = {"schema": SCHEMA, "domain_id": domain_id, "producer": producer, "status": "partial",
        "source_descriptor": source_descriptor, "family_descriptor": None, "parent_descriptor": deepcopy(parent_descriptor),
        "source_parent_checkpoint": deepcopy(parent_source_checkpoint), "source_splits": prepared_source["splits"] if prepared_source else None,
        "source_stage": "complete" if source_enabled else "not_requested", "family_stage": "pending",
        "source_optimizer_steps": source_decoder.load_security_formula_decoder_continuation(source_descriptor)["training"]["optimizer_steps"] if source_enabled else 0,
        "training_history": history, "validation_inventory": validation["inventory"],
        "training_bindings": train["bindings"], "validation_bindings": validation["bindings"],
        "requested_families": list(requested_families) if requested_families is not None else None,
        "targets_sha256": target_sha, "family_error": None, "family_training_report": None,
        "test_used_for_fit_or_selection": False, "source_model_reinitialized": False,
        "family_objective_scope": "typed native structural reconstruction; neither source-language decoding nor theorem correctness", **FALSE}
    path = output / "recipe.json"
    _save(path, receipt)
    try:
        result = numerical.train_family_projection_autoencoder_v2(train["reports"], validation["reports"], output_dir=output / "family",
            parent_descriptor=parent["family_descriptor"] if parent is not None else None, **settings)
        _require(_pins() == producer, "domain producer changed during optimization")
        _require(result["report"]["training_executed"], "family optimization completed no fitting work")
        receipt.update(status="complete", family_stage="complete", family_descriptor=result["descriptor"], family_training_report=result["report"])
    except Exception as exc:
        receipt.update(status="partial", family_stage="failed", family_error={"type": type(exc).__name__, "message": str(exc)[:2000]})
    digest = _save(path, receipt, replace=True)
    return {"descriptor": {"schema": SCHEMA, "path": str(path), "sha256": digest}, "report": receipt}


def train_security_joint_autoencoder_v2(training_rows, validation_rows, *, source_samples, parent_source_checkpoint, **kwargs):
    """Default two-objective Security recipe, sharing exact declared source roles."""
    return train_domain_family_autoencoder_v2("security_ir", training_rows, validation_rows,
        source_samples=source_samples, parent_source_checkpoint=parent_source_checkpoint, **kwargs)


def infer_domain_family_autoencoder_v2(descriptor, rows):
    saved = _read(descriptor)
    _require(saved["status"] == "complete", "complete native family stage required for inference")
    prepared = prepare_domain_family_rows_v2(saved["domain_id"], rows, role="inference", requested_families=saved["requested_families"])
    result = numerical.infer_family_projection_autoencoder_v2(saved["family_descriptor"], prepared["reports"])
    _require(_pins() == saved["producer"], "domain producer changed during inference")
    return {"schema": SCHEMA, "domain_id": saved["domain_id"], "checkpoint": deepcopy(descriptor),
        "input_bindings": prepared["bindings"], "native_inference": result, "formulas_generated": False,
        "source_text_decoded": False, "training_steps": 0, **FALSE}


__all__ = ["train_domain_family_autoencoder_v2", "train_security_joint_autoencoder_v2",
           "infer_domain_family_autoencoder_v2", "prepare_domain_family_rows_v2", "SCHEMA"]
