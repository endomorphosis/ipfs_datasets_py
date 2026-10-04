"""Source/group-audited four-domain training on complete native feature bases.

This additive recipe leaves existing source decoders and checkpoint lineages
unchanged. A family head reconstructs supplied native expressions; it does not
decode source language or establish that a source satisfies those expressions.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import autoencoder_family_complete_training as numerical
from . import domain_family_training_prepared as native
from . import domain_family_training_v2 as common
from ...logic.formalization.autoencoder.family_training_v2 import family_training_catalog_v2

SCHEMA = "domain-complete-family-training/v1"


def _pins():
    return {"recipe": common._sha(Path(__file__).read_bytes()), "numerical": numerical._pins()}


def native_family_ids(domain_id):
    """Return actual registered domain routes, not the entire logic catalog."""
    common._require(domain_id in native.DOMAINS, "supported IR domain required")
    return tuple(row["family_id"] for row in family_training_catalog_v2(domain_id)["family_inventory"]
                 if row["projection_adapter_available"])


def _prepare(domain_id, rows, *, role="training", requested_families=None):
    """Keep the rich-AST contract and also accept exact typed Intent owners.

    Typed declarations can contain intentions, invariants and control evidence
    beyond the source grammar. Their source hash is checked, while semantic
    correspondence to that source remains an explicit unproved assumption.
    """
    if domain_id != "intent_ir":
        return native.prepare_domain_family_rows(domain_id, rows, role=role,
                                                 requested_families=requested_families)
    from ...logic.intent_ir.schema import IntentIRDocument
    from ...logic.formalization.autoencoder.family_training_v2 import prepare_family_training_targets_v2
    common._require(type(rows) in (list, tuple) and 1 <= len(rows) <= 384,
                    "bounded nonempty Intent rows required")
    typed = [type(row.get("inputs", {}).get("document")) is IntentIRDocument
             if type(row) is dict and type(row.get("inputs")) is dict else False for row in rows]
    if not any(typed):
        return native.prepare_domain_family_rows(domain_id, rows, role=role,
                                                 requested_families=requested_families)
    common._require(all(typed), "one Intent representation per panel required")
    roles = {"training": {"train"}, "validation": {"validation", "valid", "tuning"},
             "inference": {"train", "validation", "valid", "tuning", "test", "canary", "inference"}}
    common._require(role in roles, "explicit preparation role required")
    reports, bindings, identities, contents = [], [], set(), set()
    for row in rows:
        common._require(set(row) == {"source_id", "group_id", "split", "inputs"}
            and all(type(row[key]) is str and 0 < len(row[key]) <= 512 for key in ("source_id", "group_id", "split")),
            "closed typed Intent source/group/split row required")
        common._require(row["split"] in roles[role], "test/canary rows cannot enter fitting or selection")
        common._require(row["source_id"] not in identities, "duplicate Intent source identity")
        inputs = row["inputs"]
        common._require({"document", "source_text"} <= set(inputs)
            <= {"document", "source_text", "context", "supplemental_inputs"}, "Intent native input fields differ")
        document, text = inputs["document"], inputs["source_text"]
        common._require(type(text) is str and text.strip() and len(text.encode()) <= 1048576,
                        "bounded exact Intent source text required")
        document.validate()
        content = common._sha(text.encode())
        common._require(content not in contents, "duplicate exact Intent source content")
        common._require(all(source.content_sha256 == content and
            (source.span is None or source.span.end_char <= len(text)) for source in document.sources),
            "typed Intent sources must bind the exact supplied text and bounded spans")
        report = prepare_family_training_targets_v2(domain_id, requested_families=requested_families, **inputs)
        common._require(any(target["ready_for_training"] for target in report["projections"]),
                        "typed Intent source has no ready native target")
        # This identity removes provenance only; it is not a graph-isomorphism
        # or synonym-equivalence claim. Explicit document groups remain vital.
        def declaration(value):
            if type(value) is dict:
                return {key: declaration(child) for key, child in value.items()
                        if key not in {"sources", "source_ref_ids", "document_id", "title", "confidence", "grounding"}}
            if type(value) is list:
                return [declaration(child) for child in value]
            return value
        bindings.append(dict(source_id=row["source_id"], group_id=row["group_id"], split=row["split"],
            source_content_sha256=content, typed_source_digest=report["source_digest"],
            normalized_source_sha256=common._sha(" ".join(text.casefold().split()).encode()),
            declaration_sha256=common._sha(common._raw(declaration(document.to_dict())))))
        reports.append(report)
        identities.add(row["source_id"])
        contents.add(content)
    inventory = common._inventory(bindings)
    inventory.update(normalized_sources=sorted({row["normalized_source_sha256"] for row in bindings}),
        declarations_without_provenance=sorted({row["declaration_sha256"] for row in bindings}))
    return {"reports": reports, "bindings": bindings, "inventory": inventory,
        "input_representation": "typed_IntentIRDocument", "source_semantics_verified": False}


def load_domain_complete_family_recipe(descriptor):
    common._require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"}
        and descriptor["schema"] == SCHEMA, "closed complete domain descriptor required")
    path = Path(descriptor["path"])
    common._require(path.is_absolute() and path.resolve() == path and path.is_file()
        and not path.is_symlink() and path.stat().st_size <= common.MAX_BYTES,
        "canonical bounded recipe required")
    raw = path.read_bytes()
    common._require(common._sha(raw) == descriptor["sha256"], "domain recipe changed")
    saved = json.loads(raw)
    fields = {"schema", "producer", "domain_id", "requested_families", "required_families",
        "available_native_families", "training_inventory", "validation_inventory",
        "targets_sha256", "family_descriptor", "source_text_decoder_trained", *common.FALSE}
    common._require(set(saved) == fields and saved["schema"] == SCHEMA
        and saved["domain_id"] in native.DOMAINS and saved["producer"] == _pins()
        and saved["source_text_decoder_trained"] is False
        and all(saved[key] is False for key in common.FALSE), "recipe identity, source or authority differs")
    common._exclude(saved["training_inventory"], saved["validation_inventory"])
    target = path.parent / "targets.json"
    common._require(target.is_file() and not target.is_symlink() and target.stat().st_size <= common.MAX_BYTES
        and common._sha(target.read_bytes()) == saved["targets_sha256"], "native targets changed")
    checkpoint, _ = numerical.load_complete_family_checkpoint(saved["family_descriptor"])
    common._require(checkpoint["space"]["domain_id"] == saved["domain_id"], "cross-domain family checkpoint")
    common._require(set(saved["required_families"]) <= set(checkpoint["report"]["trained_logic_families"]),
                    "required native family is absent from numerical model")
    return saved


def train_domain_complete_family_autoencoder(domain_id, training_rows, validation_rows, *,
        output_dir, requested_families=None, required_families=(), require_all_native_families=False,
        **settings):
    """Fit all ready requested native projections with explicit split exclusion.

    ``requested_families=None`` examines the complete logic catalog. Unsupported
    projections remain named gaps. ``require_all_native_families=True`` instead
    requires training AND tuning evidence for every domain route and fails if
    native models are missing. It never fabricates a model to satisfy coverage.
    Test/canary rows cannot train or select weights. Existing checkpoints are
    immutable; this recipe creates a fresh family head and does not resume one.
    """
    common._require(type(require_all_native_families) is bool, "explicit boolean family policy required")
    available = native_family_ids(domain_id)
    required = sorted(set(required_families) | (set(available) if require_all_native_families else set()))
    common._require(set(required) <= set(available), "required family has no native domain route")
    output = Path(output_dir)
    common._require(output.is_absolute() and output.resolve() == output and not output.exists(),
                    "fresh canonical output directory required")
    producer = _pins()
    training = _prepare(domain_id, training_rows, requested_families=requested_families)
    tuning = _prepare(domain_id, validation_rows, role="validation", requested_families=requested_families)
    common._require(set(training["inventory"]) == set(tuning["inventory"]),
                    "training and tuning must use the same Intent input representation")
    common._exclude(training["inventory"], tuning["inventory"])
    # Native and split checks precede output creation or numerical optimization.
    fitted = numerical.train_complete_family_autoencoder(training["reports"], tuning["reports"],
        output_dir=output / "model", required_families=required, **settings)
    target_sha = common._save(output / "targets.json", {"training": training, "validation": tuning})
    common._require(producer == _pins(), "training recipe changed during fitting")
    saved = {"schema": SCHEMA, "producer": producer, "domain_id": domain_id,
        "requested_families": None if requested_families is None else list(requested_families),
        "required_families": required, "available_native_families": list(available),
        "training_inventory": training["inventory"], "validation_inventory": tuning["inventory"],
        "targets_sha256": target_sha, "family_descriptor": fitted["descriptor"],
        "source_text_decoder_trained": False, **common.FALSE}
    path = output / "recipe.json"
    digest = common._save(path, saved)
    descriptor = {"schema": SCHEMA, "path": str(path), "sha256": digest}
    load_domain_complete_family_recipe(descriptor)
    return {"descriptor": descriptor, "report": saved, "numerical_report": fitted["report"]}


def infer_domain_complete_family_autoencoder(descriptor, rows):
    saved = load_domain_complete_family_recipe(descriptor)
    prepared = _prepare(saved["domain_id"], rows, role="inference", requested_families=saved["requested_families"])
    return numerical.infer_complete_family_autoencoder(saved["family_descriptor"], prepared["reports"])


__all__ = ["SCHEMA", "native_family_ids", "train_domain_complete_family_autoencoder",
           "infer_domain_complete_family_autoencoder", "load_domain_complete_family_recipe"]
