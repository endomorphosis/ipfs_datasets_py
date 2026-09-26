"""Verified inline corpus inputs for a bounded training/repair cycle.

Input integrity and training membership are separate from native execution,
checkpoint promotion and Lean admission. Staging only copies immutable bytes;
the owner and worker still perform their independent verification.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ...optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
    CAMPAIGN_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, TrainingJobSpec, verify_corpus_job_inputs,
)

MAX_FEEDBACK_RECORDS = 128


@dataclass(frozen=True)
class CycleInputs:
    verification: dict
    training_records: tuple


def _inline_spec(spec):
    if type(spec) is not TrainingJobSpec or spec.schema_version not in {PRODUCED_SCHEMA_VERSION, CAMPAIGN_SCHEMA_VERSION}:
        # V7 transports empty embedding vectors and requires live mapped views.
        raise ValueError("training feedback requires the verified v6 or v8 inline input contract")


def _selection(record_ids):
    if record_ids is None:
        return None
    chosen = []
    for record_id in record_ids:
        if len(chosen) >= MAX_FEEDBACK_RECORDS or type(record_id) is not str:
            raise ValueError("feedback selection must contain at most 128 unique training members")
        chosen.append(record_id)
    if not chosen or len(set(chosen)) != len(chosen):
        raise ValueError("feedback selection must contain unique training members only")
    return chosen


def verify_cycle_inputs(spec, *, record_ids=None):
    """Verify both roles, then return exact ordered training records only.

    A cycle using all training rows fails its feedback bound before training.
    An observer may retain the existing explicit bounded-subset behavior.
    """
    from ...optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import load_corpus_manifest

    _inline_spec(spec)
    chosen = _selection(record_ids)
    if chosen is None and len(spec.samples) > MAX_FEEDBACK_RECORDS:
        raise ValueError("cycle feedback is limited to 128 training members before dispatch")
    verification = verify_corpus_job_inputs(spec)
    if spec.schema_version == PRODUCED_SCHEMA_VERSION:
        valid = verification.get("corpus_index_membership_verified") is True
    else:
        valid = (verification.get("source_campaign_verified") is True
                 and verification.get("produced_record_projection_verified") is True)
    if not valid:
        raise ValueError("training feedback requires a verified frozen training split")
    train_ids = list(verification["training_record_ids"])
    chosen = train_ids if chosen is None else chosen
    if (not chosen or len(chosen) > MAX_FEEDBACK_RECORDS or len(set(chosen)) != len(chosen)
            or not set(chosen).issubset(train_ids) or len(train_ids) != len(spec.samples)
            or len(set(train_ids)) != len(train_ids)):
        raise ValueError("feedback selection must contain unique training members only")
    ref = spec.corpus_manifest_artifact
    manifest = load_corpus_manifest(ref.path, expected_sha256=ref.sha256, expected_size_bytes=ref.bytes)
    records = {record.record_id: record for record in manifest.records}
    inputs = dict(zip(train_ids, spec.samples, strict=True))
    if any(record_id not in records or asdict(records[record_id].sample) != asdict(inputs[record_id]) for record_id in chosen):
        raise ValueError("training source correspondence is incomplete")
    return CycleInputs(verification, tuple(records[record_id] for record_id in chosen))


def stage_cycle_job_inputs(registry, spec):
    """Stage declared bytes and build variant metadata, without authorizing use.

    Call verify_cycle_inputs before staging selected sources. A returned payload
    still requires the existing owner/worker checks before training.
    """
    _inline_spec(spec)
    payload = spec.to_dict()
    common = ("base_checkpoint", "corpus_manifest_artifact", "target_snapshot_artifact", "arrow_feature_weights_artifact")
    campaign = ("source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact",
                "produced_record_projection_artifact")
    fields = common + (campaign if spec.schema_version == CAMPAIGN_SCHEMA_VERSION
                       else ("corpus_index_artifact", "embedding_production_artifact"))

    def stage(ref):
        stored = registry.stage_artifact(ref["path"], ref["sha256"])
        if stored != {key: ref[key] for key in ("sha256", "bytes")}:
            raise ValueError("staged cycle artifact differs from its declared byte identity")
        return {**stored, "path": str(registry.artifact_path(stored))}

    for name in fields:
        if payload.get(name) is not None:
            payload[name] = stage(payload[name])
    arrays = ("corpus_source_artifacts", "base_checkpoint_dependencies")
    if spec.schema_version == CAMPAIGN_SCHEMA_VERSION:
        arrays += ("embedding_receipt_artifacts",)
    for name in arrays:
        payload[name] = [stage(ref) for ref in payload[name]]
    variant = dict(payload["variant"])
    if spec.schema_version == CAMPAIGN_SCHEMA_VERSION:
        variant["source_campaign_binding"] = {
            name: {key: payload[name + "_artifact"][key] for key in ("sha256", "bytes")}
            for name in ("source_inventory", "source_partitions", "embedding_receipt_set")}
    else:
        variant.update(corpus_index_binding={"selection_sha256": payload["corpus_selection_sha256"],
            "artifact": {key: payload["corpus_index_artifact"][key] for key in ("sha256", "bytes")}},
            embedding_production_binding={"artifact": {
                key: payload["embedding_production_artifact"][key] for key in ("sha256", "bytes")}})
    return payload, variant
