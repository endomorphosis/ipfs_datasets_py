"""Domain-owned source contracts feeding the shared regularization-path fitter."""
from __future__ import annotations

import json
from pathlib import Path

from . import autoencoder_family_ridge_path as numerical
from . import domain_family_training_prepared as native
from . import domain_family_training_v2 as common

SCHEMA = "domain-family-ridge-path/v1"


def _load(descriptor):
    numerical._require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"}
        and descriptor["schema"] == SCHEMA, "closed domain recipe descriptor required")
    path = Path(descriptor["path"])
    numerical._require(path.is_absolute() and path.is_file() and not path.is_symlink()
        and path.stat().st_size <= common.MAX_BYTES, "bounded regular recipe required")
    raw = path.read_bytes()
    numerical._require(numerical._sha(raw) == descriptor["sha256"], "domain recipe changed")
    saved = json.loads(raw)
    numerical._require(saved["schema"] == SCHEMA and saved["domain_id"] in native.DOMAINS,
                       "domain recipe identity differs")
    checkpoint, _ = numerical._read(saved["family_descriptor"])
    numerical._require(checkpoint["space"]["domain_id"] == saved["domain_id"], "cross-domain numerical head")
    common._exclude(saved["training_history"], saved["validation_inventory"])
    return saved


def train_domain_family_ridge_path(domain_id, training_rows, validation_rows, *, output_dir,
        requested_families=None, required_families=(), parent_descriptor=None, **settings):
    """Train all supplied ready native families with source/group split exclusion.

    Default ``requested_families=None`` requests the full canonical inventory.
    Explicit ``required_families`` fails if native or numerical evidence is absent.
    Unavailable native projections remain recorded gaps, never invented labels.
    """
    output = Path(output_dir)
    numerical._require(output.is_absolute() and output.resolve() == output and not output.exists(),
                       "fresh canonical recipe directory required")
    train = native.prepare_domain_family_rows(domain_id, training_rows, requested_families=requested_families)
    tuning = native.prepare_domain_family_rows(domain_id, validation_rows, role="validation", requested_families=requested_families)
    common._exclude(train["inventory"], tuning["inventory"])
    parent = _load(parent_descriptor) if parent_descriptor else None
    requested = None if requested_families is None else list(requested_families)
    history = train["inventory"]
    if parent:
        numerical._require(parent["domain_id"] == domain_id and parent["requested_families"] == requested
            and parent["required_families"] == sorted(set(required_families)), "parent domain or family policy differs")
        numerical._require(parent["validation_inventory"] == tuning["inventory"], "original tuning panel required")
        common._exclude(parent["training_history"], tuning["inventory"])
        history = common._merge(parent["training_history"], history)
    result = numerical.train_family_ridge_path(train["reports"], tuning["reports"],
        output_dir=output / "model", parent_descriptor=None if parent is None else parent["family_descriptor"],
        required_families=required_families, **settings)
    report = {"schema": SCHEMA, "domain_id": domain_id, "requested_families": requested,
        "required_families": sorted(set(required_families)), "training_history": history,
        "validation_inventory": tuning["inventory"], "family_descriptor": result["descriptor"],
        "source_text_decoder_trained": False, "status": "complete", **numerical.FALSE}
    raw = numerical._raw(report)
    path = output / "recipe.json"
    path.write_bytes(raw)
    descriptor = {"schema": SCHEMA, "path": str(path), "sha256": numerical._sha(raw)}
    _load(descriptor)
    return {"descriptor": descriptor, "report": report, "numerical_report": result["report"]}


def infer_domain_family_ridge_path(descriptor, rows):
    saved = _load(descriptor)
    prepared = native.prepare_domain_family_rows(saved["domain_id"], rows, role="inference",
        requested_families=saved["requested_families"])
    return numerical.infer_family_ridge_path(saved["family_descriptor"], prepared["reports"])
