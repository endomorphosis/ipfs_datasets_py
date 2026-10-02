"""Legal typed-IR curriculum entrypoint for shared native family training.

This is an auxiliary structural head. It leaves the existing legal text model,
its checkpoint, and its resumable worker pipeline unchanged. Train/validation
roles and document groups must be assigned before preparing projections.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import autoencoder_family_training as shared
from ...logic.formalization.autoencoder.family_training import prepare_family_training_targets

SCHEMA = "legal-family-training-batch/v1"


def _prepare(rows, role):
    shared._require(type(rows) in (list, tuple) and 1 <= len(rows) <= shared.MAX_ROWS,
                    "bounded nonempty legal rows required")
    sources, groups, reports = set(), set(), []
    allowed = {"train"} if role == "training" else {"validation", "valid", "tuning"}
    for row in rows:
        shared._require(type(row) is dict and set(row) ==
                        {"document", "source_text", "source_id", "group_id", "split"},
                        "closed typed legal training row required")
        shared._require(row["split"] in allowed, "test/canary rows cannot enter legal fitting or selection")
        shared._require(all(type(row[k]) is str and row[k].strip() for k in
                            ("source_text", "source_id", "group_id")), "legal source and group required")
        shared._require(row["source_id"] not in sources, "duplicate legal source identity")
        sources.add(row["source_id"])
        groups.add(row["group_id"])
        reports.append(prepare_family_training_targets("legal_ir", document=row["document"],
                                                       source_text=row["source_text"]))
    return reports, sources, groups


def _load(descriptor):
    shared._require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"}
                    and descriptor["schema"] == SCHEMA, "legal family batch descriptor required")
    path = Path(descriptor["path"])
    shared._require(path.is_file() and not path.is_symlink() and path.stat().st_size <= shared.MAX_BYTES,
                    "bounded legal batch artifact required")
    raw = path.read_bytes()
    shared._require(hashlib.sha256(raw).hexdigest() == descriptor["sha256"], "legal batch digest mismatch")
    result = json.loads(raw)
    shared._require(result["schema"] == SCHEMA and all(result[k] is False for k in shared.FALSE),
                    "invalid legal batch authority")
    return result


def train_legal_family_batch(training_rows, validation_rows, *, output_dir,
                             parent_descriptor=None, **settings):
    """Train all available, validated native projections of the supplied IRs.

    The caller supplies a reviewed typed IR; this method does not use an LLM or
    relabel a heuristic legal-text parse as ground truth. Continuation enforces
    historical group/source exclusion as well as the shared target-byte check.
    """
    output = Path(output_dir).absolute()
    shared._require(not output.exists() and not output.is_symlink(), "fresh legal family directory required")
    training, sources, groups = _prepare(training_rows, "training")
    validation, val_sources, val_groups = _prepare(validation_rows, "validation")
    parent_model = None
    if parent_descriptor is not None:
        parent = _load(parent_descriptor)
        parent_model = parent["model_descriptor"]
        sources.update(parent["training_sources"])
        groups.update(parent["training_groups"])
        shared._require(parent["validation_sources"] == sorted(val_sources)
                        and parent["validation_groups"] == sorted(val_groups),
                        "legal validation panel changed on continuation")
    shared._require(not sources & val_sources, "legal source split leakage")
    shared._require(not groups & val_groups, "legal document group split leakage")
    result = shared.train_family_projection_autoencoder(training, validation,
        output_dir=output / "model", parent_descriptor=parent_model, **settings)
    audit = {"schema": SCHEMA, "model_descriptor": result["descriptor"],
             "training_sources": sorted(sources), "training_groups": sorted(groups),
             "validation_sources": sorted(val_sources), "validation_groups": sorted(val_groups),
             "parent_descriptor": parent_descriptor,
             "text_autoencoder_checkpoint_modified": False,
             "training_report": result["report"], **shared.FALSE}
    raw = shared._raw(audit)
    path = output / "legal_batch.json"
    with path.open("xb") as stream:
        stream.write(raw)
    descriptor = {"schema": SCHEMA, "path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
    return {"descriptor": descriptor, "report": result["report"]}


def infer_legal_family_batch(descriptor, *, documents, source_texts):
    shared._require(len(documents) == len(source_texts) and documents,
                    "aligned legal documents and exact source texts required")
    saved = _load(descriptor)
    reports = [prepare_family_training_targets("legal_ir", document=document, source_text=text)
               for document, text in zip(documents, source_texts)]
    return shared.infer_family_projection_autoencoder(saved["model_descriptor"], reports)
