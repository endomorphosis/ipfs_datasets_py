"""Inspect original v8 corpus bindings through a detached artifact resolver.

Historical absolute paths remain part of the original job identity. They are
never used to locate payloads here. This verifies evidence, not an executable
restored job, current producer compatibility, checkpoint replay or admission.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import re

from .autoencoder_training_worker import (
    CAMPAIGN_SCHEMA_VERSION, MAX_CAMPAIGN_METADATA_BYTES,
    MAX_CORPUS_MANIFEST_BYTES, MAX_PRODUCED_RECORD_PROJECTION_BYTES,
    TrainingJobSpec, _json_bytes, _parse_json,
)


SCHEMA_VERSION = "autoencoder-detached-campaign-job-verification-v1"
MAX_JOB_BYTES = 64 * 1024**2


class DetachedCampaignInputError(ValueError):
    """Detached bytes disagree with an original job or its selected closure."""


def _require(condition, message):
    if not condition:
        raise DetachedCampaignInputError(message)


def _reference(value):
    _require(type(value) is dict and set(value) == {"sha256", "bytes"}
             and type(value["sha256"]) is str
             and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None
             and type(value["bytes"]) is int and 0 < value["bytes"] < 2**63,
             "detached artifact requires an exact bare byte descriptor")
    return dict(value)


def _bare(value):
    # Deliberately never examine or resolve CheckpointArtifact.path.
    return {"sha256": value.sha256, "bytes": value.bytes}


def _dependencies(spec, job_artifact):
    rows = {}

    def add(reference, role):
        reference = _reference(reference)
        digest = reference["sha256"]
        prior = rows.setdefault(digest, {**reference, "roles": set()})
        _require(prior["bytes"] == reference["bytes"],
                 "same detached digest has conflicting byte sizes")
        prior["roles"].add(role)

    add(job_artifact, "job_spec")
    for name, role in (
        ("source_inventory_artifact", "source_inventory"),
        ("source_partitions_artifact", "source_partitions"),
        ("embedding_receipt_set_artifact", "embedding_receipt_set"),
        ("produced_record_projection_artifact", "produced_record_projection"),
        ("corpus_manifest_artifact", "corpus_manifest"),
        ("base_checkpoint", "base_checkpoint"),
        ("target_snapshot_artifact", "target_snapshot"),
        ("arrow_feature_weights_artifact", "arrow_feature_weights"),
    ):
        artifact = getattr(spec, name)
        if artifact is not None:
            add(_bare(artifact), role)
    for name, role in (("corpus_source_artifacts", "corpus_source"),
                       ("embedding_receipt_artifacts", "embedding_receipt"),
                       ("base_checkpoint_dependencies", "base_checkpoint_dependency")):
        for artifact in getattr(spec, name):
            add(_bare(artifact), role)
    return [{**rows[key], "roles": sorted(rows[key]["roles"])} for key in sorted(rows)]


class _Resolver:
    """Capture caller-supplied locations once, without consulting job paths."""

    def __init__(self, resolver, job_artifact):
        _require(callable(resolver), "detached artifact resolver required")
        self._resolver = resolver
        self._allowed = {job_artifact["sha256"]: dict(job_artifact)}
        self._paths = {}

    def bind(self, required):
        for row in required:
            ref = {key: row[key] for key in ("sha256", "bytes")}
            _require(self._allowed.setdefault(ref["sha256"], ref) == ref,
                     "detached resolver binding has conflicting byte sizes")

    def __call__(self, reference):
        ref = _reference(reference)
        _require(self._allowed.get(ref["sha256"]) == ref,
                 "detached artifact is outside the original job closure")
        if ref["sha256"] not in self._paths:
            path = Path(self._resolver(dict(ref)))
            _require(path.is_absolute() and path.resolve() == path,
                     "detached resolver must supply absolute paths without aliases")
            self._paths[ref["sha256"]] = path
        return self._paths[ref["sha256"]]


def _read(reference, resolver, maximum):
    from .autoencoder_uscode_import import _verified_file

    _require(reference["bytes"] <= maximum, "detached artifact exceeds byte bound")
    with _verified_file(resolver(reference), reference, maximum) as stream:
        raw = stream.read(reference["bytes"] + 1)
    _require(len(raw) == reference["bytes"], "detached artifact size changed")
    return raw


def _load(loader, artifact, resolver, **kwargs):
    reference = _bare(artifact)
    return loader(resolver(reference), expected_sha256=reference["sha256"],
                  expected_size_bytes=reference["bytes"], **kwargs)


def _metadata_current(spec, job_artifact, resolver):
    from .autoencoder_uscode_import import _verified_file

    values = [(job_artifact, MAX_JOB_BYTES)]
    values.extend((_bare(artifact), maximum) for artifact, maximum in (
        (spec.source_inventory_artifact, MAX_CAMPAIGN_METADATA_BYTES),
        (spec.source_partitions_artifact, MAX_CAMPAIGN_METADATA_BYTES),
        (spec.embedding_receipt_set_artifact, MAX_CAMPAIGN_METADATA_BYTES),
        (spec.produced_record_projection_artifact, MAX_PRODUCED_RECORD_PROJECTION_BYTES),
        (spec.corpus_manifest_artifact, MAX_CORPUS_MANIFEST_BYTES)))
    for reference, maximum in values:
        with _verified_file(resolver(reference), reference, maximum):
            pass


def _selected_resolver(supplied, expected, resolver, label):
    provided = {(artifact.sha256, artifact.bytes) for artifact in supplied}
    required = {(reference["sha256"], reference["bytes"]) for reference in expected}
    _require(provided == required and len(provided) == len(supplied),
             f"detached selected {label} differ from the exact projection closure")

    def resolve(reference):
        reference = _reference(reference)
        _require((reference["sha256"], reference["bytes"]) in required,
                 f"detached {label} resolver received an unselected artifact")
        return resolver(reference)

    return resolve


def _code_identity():
    # Reuse the bounded current-validator drift checks, not a historical
    # execution-source attestation or a claim of whole-package provenance.
    from .autoencoder_campaign_job_inputs import _scope_code_identity, _scope_source_sha256

    return (_scope_code_identity(), _scope_source_sha256(Path(__file__)))


def verify_detached_campaign_job(job_artifact, *, resolver,
                                 expected_job_spec_sha256, variant_manifest):
    """Verify original v8 bytes and selected corpus payloads via bare descriptors.

    The caller supplies the exact expected canonical job digest and original
    variant manifest from its typed page/registry binding. Checkpoint, target
    and Arrow references are returned for that caller's transitive inventory;
    this adapter does not open them or grant execution authority. The private
    returned codec objects are operation-local state, never wire data.
    """
    try:
        from ...logic.autoformal.tree_pin import require_workspace_logic_tree
        from .autoencoder_corpus_index import _summary
        from .autoencoder_corpus_manifest import load_corpus_manifest
        from .autoencoder_embedding_receipt_set import load_embedding_receipt_set
        from .autoencoder_produced_record_projection import (
            load_produced_record_projection, _manifest as bounded_manifest,
        )
        from .autoencoder_source_partitions import load_source_partitions
        from .autoencoder_training_coordinator import _verify_variant_source_campaign_binding
        from .autoencoder_uscode_inventory import load_uscode_source_inventory

        require_workspace_logic_tree()
        code = _code_identity()
        reference = _reference(job_artifact)
        _require(type(expected_job_spec_sha256) is str
                 and re.fullmatch(r"[0-9a-f]{64}", expected_job_spec_sha256) is not None,
                 "an exact expected canonical job SHA-256 is required")
        captured = _Resolver(resolver, reference)
        raw = _read(reference, captured, MAX_JOB_BYTES)
        spec = TrainingJobSpec.from_dict(_parse_json(raw))
        _require(spec.schema_version == CAMPAIGN_SCHEMA_VERSION,
                 "detached campaign inspection requires the v8 job schema")
        _require(spec.canonical_sha256 == expected_job_spec_sha256,
                 "detached original job differs from the expected complete specification")
        _require(type(variant_manifest) is dict, "original variant manifest must be an object")
        variant_raw = _json_bytes(variant_manifest)
        variant = _parse_json(variant_raw)
        _verify_variant_source_campaign_binding(variant, spec)
        expected_variant = asdict(spec.variant)
        _require(_json_bytes({name: variant.get(name) for name in expected_variant})
                 == _json_bytes(expected_variant),
                 "detached original variant differs from the job variant")
        required = _dependencies(spec, reference)
        captured.bind(required)

        inventory = _load(load_uscode_source_inventory, spec.source_inventory_artifact, captured)
        partitions = _load(load_source_partitions, spec.source_partitions_artifact, captured,
                           inventory=inventory)
        receipt_set = _load(load_embedding_receipt_set, spec.embedding_receipt_set_artifact,
                            captured, partitions=partitions)
        # Every public constructor has run; retain only its final owned graph.
        partitions = receipt_set.partitions
        del inventory
        # The existing projection constructor authorizes both role groups and
        # applies selected-byte budgets before either selected resolver is used.
        projection = _load(load_produced_record_projection, spec.produced_record_projection_artifact,
                           captured, receipt_set=receipt_set)
        selected = projection.selected_artifacts()
        leaf_resolver = _selected_resolver(spec.embedding_receipt_artifacts,
            selected["leaf_receipts"], captured, "receipts")
        source_resolver = _selected_resolver(spec.corpus_source_artifacts,
            selected["source_artifacts"], captured, "sources")
        metadata = projection.to_dict()
        _require(metadata["corpus_manifest"] == _bare(spec.corpus_manifest_artifact),
                 "detached manifest differs from the exact projection binding")
        manifest = bounded_manifest(_load(load_corpus_manifest, spec.corpus_manifest_artifact,
                                         captured), projection.limits)
        _require(metadata["dataset_snapshot_id"] == manifest.dataset_snapshot_id
                 and metadata["split_snapshot_id"] == manifest.split_snapshot_id
                 and metadata["training_record_ids"] == list(manifest._training_record_ids)
                 and metadata["validation_record_ids"] == list(manifest._validation_record_ids)
                 and [row["record_summary"] for row in metadata["records"]]
                     == [_summary(record) for record in manifest.records],
                 "detached manifest differs from projected snapshots, ordered roles or records")
        _require({(ref["sha256"], ref["bytes"]) for ref in manifest.source_refs}
                 == {(ref["sha256"], ref["bytes"]) for ref in selected["source_artifacts"]},
                 "detached manifest sources differ from the exact selected closure")
        membership = manifest.verify_job_records(spec.samples, spec.validation_samples,
            dataset_snapshot_id=spec.dataset_snapshot_id, split_snapshot_id=spec.split_snapshot_id)
        _require(manifest.mode == "corpus" and set(manifest.language_counts) == {"en"}
                 and spec.variant.source_language == "en" and set(manifest.source_kind_counts) == {"us_code"},
                 "detached v8 inspection requires the qualified English us_code frontend")

        _metadata_current(spec, reference, captured)
        _require(_code_identity() == code, "detached validator changed before selected verification")
        verification = projection.verify_batch(manifest,
            receipt_resolver=leaf_resolver, source_resolver=source_resolver)
        source_validation = manifest.validate_sources(source_resolver)
        _metadata_current(spec, reference, captured)
        _require(spec.canonical_sha256 == expected_job_spec_sha256
                 and _json_bytes(variant_manifest) == variant_raw and _code_identity() == code,
                 "detached job, variant or validator changed during verification")
        corpus = {**membership,
            "verification_mode": "manifest_source_bytes_source_campaign_and_record_projection",
            "dataset_and_split_identity_verified": True, "source_validation": source_validation,
            "frontend": "legacy_us_code", "global_holdout_verified": False,
            "source_campaign_verified": True,
            "source_campaign_verification": {
                "source_inventory": _bare(spec.source_inventory_artifact),
                "source_partitions": _bare(spec.source_partitions_artifact),
                "embedding_receipt_set": _bare(spec.embedding_receipt_set_artifact),
                "source_partition_verification": partitions.verification_summary(),
                "receipt_set_verification": receipt_set.summary()},
            "produced_record_projection_verified": True,
            "produced_record_projection_verification": {**verification, "selected_artifacts": selected}}
        qualification = {
            "schema_version": SCHEMA_VERSION,
            "original_job_artifact": reference,
            "original_job_spec_sha256": spec.canonical_sha256,
            "original_job_configuration_binding_verified": True,
            "canonical_logic_tree_verified": True,
            "detached_validator_source_unchanged": True,
            "historical_absolute_paths_used": False,
            "expected_source_manifest_supplied": bool(spec.expected_source_sha256),
            "expected_source_manifest_preserved": True,
            "execution_source_manifest_verified": False,
            "checkpoint_semantic_replay_verified": False,
            "target_runtime_membership_verified": False,
            "arrow_runtime_compatibility_verified": False,
            "training_authorized": False, "weights_constructed": False,
            "source_authority_authenticated": False, "global_holdout_verified": False,
            "admitted": False, "formalized": False, "publication_performed": False,
        }
        return {"spec": spec, "corpus_verification": corpus, "required_artifacts": required,
                "qualification": qualification, "_receipt_set": receipt_set,
                "_projection": projection, "_manifest": manifest}
    except (ValueError, TypeError, KeyError, AttributeError, OSError, UnicodeError) as exc:
        if isinstance(exc, DetachedCampaignInputError):
            raise
        raise DetachedCampaignInputError("detached campaign input verification failed: " + str(exc)) from exc


__all__ = ["DetachedCampaignInputError", "verify_detached_campaign_job"]
