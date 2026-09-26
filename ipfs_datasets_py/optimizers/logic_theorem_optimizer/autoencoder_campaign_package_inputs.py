"""Typed selected-page closure for offline campaign evidence packages.

Original job paths remain data. Only the supplied descriptor resolver supplies
locations to read. This validates stored contracts, never grants execution or
publication authority, and never reconstructs checkpoint weights.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from . import autoencoder_campaign_batches as batches
from . import autoencoder_campaign_plan as plans
from .autoencoder_training_worker import _parse_json
from .autoencoder_uscode_import import _verified_file

MAX_PACKAGE_VERSIONS = 256
_ROOTS = ("source_inventory", "source_partitions", "embedding_receipt_set")
_GEN_FIELDS = {"schema_version", "recipe_id", "recipe", "page", "jobs", "coverage",
    "input_dispositions", "selected_leaf_artifacts", "selected_source_artifacts",
    "total_job_bytes", "target_membership_verified", "target_membership_qualification",
    "qualification_scope", *batches._FLAGS}
_RECIPE_FIELDS = {"schema_version", "template_run_id", "template_job_spec_artifact",
    "template_job_spec_sha256", "variant_id", "variant_manifest_sha256", "base_version_id",
    "source_campaign_binding", "artifact_root", "output_root", "training_batch_size",
    "validation_batch_size", "selection_policy", "helper_source_sha256"}
_JOB_FIELDS = {"ordinal", "job_id", "run_id", "job_spec_sha256", "job_spec_artifact",
    "corpus_manifest_artifact", "produced_record_projection_artifact"}
_RUN_FIELDS = {"run_id", "variant_id", "base_version_id", "spec", "status", "attempt", "fence", "lease", "result"}
_VERSION_FIELDS = {"version_id", "variant_id", "parent_version_id", "artifact", "metadata"}


class CampaignPackageInputError(ValueError):
    """A selected page or its typed dependency closure differs from its binding."""


def _require(condition, message):
    if not condition:
        raise CampaignPackageInputError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _same(actual, expected):
    return _raw(actual) == _raw(expected)


def _ref(value):
    plans._ref(value)
    return dict(value)


def _bare(value):
    return {name: value[name] for name in ("sha256", "bytes")}


class _Artifacts:
    def __init__(self, resolver, maximum, total, count):
        self.resolver, self.maximum, self.total_limit, self.count_limit = resolver, maximum, total, count
        self.refs, self.roles, self.paths = {}, {}, {}
        self.total = 0

    def add(self, reference, role):
        ref = _ref(reference)
        digest = ref["sha256"]
        _require(ref["bytes"] <= self.maximum, "package artifact exceeds byte bound")
        if digest in self.refs:
            _require(self.refs[digest] == ref, "one package digest has inconsistent sizes")
        else:
            _require(len(self.refs) < self.count_limit, "package artifact count exceeds bound")
            _require(self.total + ref["bytes"] <= self.total_limit, "package payload exceeds total bound")
            self.total += ref["bytes"]
            self.refs[digest], self.roles[digest] = ref, set()
        if role:
            self.roles[digest].add(role)
        return ref

    def resolve(self, reference):
        ref = self.add(reference, "")
        digest = ref["sha256"]
        if digest not in self.paths:
            path = Path(self.resolver(dict(ref)))
            _require(path.is_absolute() and path == path.resolve(), "package resolver returned an aliased or relative path")
            self.paths[digest] = path
        return self.paths[digest]

    def read(self, reference, role, maximum):
        ref = self.add(reference, role)
        with _verified_file(self.resolve(ref), ref, min(maximum, self.maximum)) as stream:
            return stream.read(ref["bytes"] + 1)

    def current(self):
        # Called only after typed validation has authorized each job's selected
        # payload reads. A generic hash-all pass must not run before that point.
        for ref in self.refs.values():
            with _verified_file(self.resolve(ref), ref, self.maximum):
                pass

    def descriptors(self):
        _require(all(self.roles.values()), "unclassified package dependency")
        return [{**self.refs[key], "roles": sorted(self.roles[key])} for key in sorted(self.refs)]


def _run(record, spec, artifact, variant_id, *, generated):
    _require(type(record) is dict and set(record) == _RUN_FIELDS, "unexpected captured run fields")
    _require(record["run_id"] == spec.run_id and record["variant_id"] == variant_id
        and record["base_version_id"] == spec.base_version_id
        and _same(record["spec"], {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": artifact}),
        "captured run differs from exact stored job")
    _require(record["status"] in {"queued", "running", "failed", "completed"}
        and all(type(record[key]) is int and record[key] >= 0 for key in ("attempt", "fence"))
        and all(record[key] is None or type(record[key]) is dict for key in ("lease", "result")),
        "invalid captured run state")
    if generated:
        _require(record["status"] == "queued" and record["attempt"] == record["fence"] == 0
            and record["lease"] is record["result"] is None, "package v1 requires untouched queued generated jobs")


def _historical_cas(spec, artifact_root):
    """Validate original locator relationships without inspecting those paths."""
    refs = [getattr(spec, name) for name in ("base_checkpoint", "corpus_manifest_artifact",
        "source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact",
        "produced_record_projection_artifact", "target_snapshot_artifact", "arrow_feature_weights_artifact")]
    refs.extend((*spec.base_checkpoint_dependencies, *spec.corpus_source_artifacts, *spec.embedding_receipt_artifacts))
    for ref in refs:
        if ref is not None:
            _require(ref.path == str(Path(artifact_root) / ref.sha256[:2] / ref.sha256),
                "original job locator differs from its historical campaign CAS")


def _versions(records, variant_id, base_ids, artifacts):
    from ...duckdb_control.contracts import content_identity
    from ...duckdb_control.autoencoder_registry import SCHEMA as registry_schema
    from .modal_autoencoder_checkpoint import (CHECKPOINT_MAGIC, CheckpointManifest, ModalAutoencoderCheckpointError,
        _parse_container, _validate_manifest_payload)
    from .modal_autoencoder_sparse_checkpoint import ResolutionLimits, inventory_checkpoint

    _require(type(records) is list and 1 <= len(records) <= MAX_PACKAGE_VERSIONS,
        "registered version ancestry exceeds package bound")
    by_id, order = {}, []
    for record in records:
        _require(type(record) is dict and set(record) == _VERSION_FIELDS
            and record["variant_id"] == variant_id and type(record["metadata"]) is dict,
            "version record is malformed or belongs to another variant")
        _ref(record["artifact"])
        expected = content_identity({"schema": registry_schema, **{name: record[name]
            for name in ("variant_id", "artifact", "metadata", "parent_version_id")}})
        _require(record["version_id"] == expected and expected not in by_id,
            "version identity differs or is duplicated")
        parent = record["parent_version_id"]
        _require(parent is None or parent in by_id, "version records must be parent-before-child with complete ancestry")
        by_id[expected] = record
        order.append(expected)
    required = set()
    for base in base_ids:
        active = set()
        while base is not None:
            _require(base in by_id and base not in active, "missing or cyclic registered version ancestry")
            active.add(base)
            required.add(base)
            base = by_id[base]["parent_version_id"]
    _require(required == set(by_id), "package contains unrelated registered versions")
    inventories = {}
    defaults = ResolutionLimits()
    limits = ResolutionLimits(max_checkpoint_bytes=artifacts.maximum,
        max_manifest_bytes=min(1024**2, artifacts.maximum),
        max_patch_bytes=min(defaults.max_patch_bytes, artifacts.maximum),
        max_total_patch_bytes=min(256 * 1024**2, artifacts.total_limit),
        max_total_bytes=artifacts.total_limit, max_artifacts=artifacts.count_limit)
    for version_id in order:
        record = by_id[version_id]
        ref = artifacts.add(record["artifact"], "registered_checkpoint")
        path = artifacts.resolve(ref)
        with _verified_file(path, ref, artifacts.maximum) as stream:
            compact = stream.read(len(CHECKPOINT_MAGIC)) == CHECKPOINT_MAGIC
            if compact:
                stream.seek(0)
                compact_raw = stream.read(ref["bytes"] + 1)
        if compact:
            _require(version_id not in base_ids, "v8 base checkpoints require the existing JSON/sparse inventory contract")
            # Full compact registry ancestors can be self-contained. Framing
            # validation constructs no state; it never claims semantic replay.
            try:
                manifest_data, payload, end = _parse_container(compact_raw, expected_magic=CHECKPOINT_MAGIC)
                _require(end == len(compact_raw), "full compact checkpoint has trailing bytes")
                _validate_manifest_payload(CheckpointManifest.from_dict(manifest_data), payload, kind="full")
            except ModalAutoencoderCheckpointError as exc:
                raise CampaignPackageInputError("invalid compact checkpoint framing: " + str(exc)) from exc
            del compact_raw, manifest_data, payload
            with _verified_file(path, ref, artifacts.maximum):
                pass
            continue
        inventory = inventory_checkpoint(ref, resolver=artifacts.resolve, limits=limits)
        for item in inventory.artifacts:
            artifacts.add(dict(item), "checkpoint_physical_dependency")
        if inventory.manifest is not None:
            parent = record["parent_version_id"]
            _require(parent is not None and inventory.manifest["base_version_id"] == parent
                and dict(inventory.manifest["parent"]) == by_id[parent]["artifact"],
                "sparse manifest parent differs from registered parent version")
        inventories[version_id] = inventory
    return by_id, inventories


def _inspect_campaign_inputs(generation_artifact, plan_artifact, *, variant_record,
        version_records, run_records, artifact_resolver, max_blob_bytes=256 * 1024**2,
        max_total_bytes=512 * 1024**2, max_blobs=4096):
    """Derive and verify one exact selected-page closure through bare references.

    The template can be a historical input anchor. Generated jobs must still be
    queued in the captured records. Capture authenticity and current registry
    authority are not inferred from these records or their content digests.
    """
    from .autoencoder_campaign_detached_inputs import verify_detached_campaign_job
    from .autoencoder_embedding_production import EmbeddingInput
    from .autoencoder_embedding_receipt_set import ReceiptSetLimits

    _require(callable(artifact_resolver), "package requires a descriptor resolver")
    for value, ceiling in ((max_blob_bytes, 256 * 1024**2), (max_total_bytes, 512 * 1024**2), (max_blobs, 4096)):
        _require(type(value) is int and 1 <= value <= ceiling, "invalid package dependency bound")
    artifacts = _Artifacts(artifact_resolver, max_blob_bytes, max_total_bytes, max_blobs)
    gen_raw = artifacts.read(generation_artifact, "campaign_generation", batches.MAX_GENERATION_BYTES)
    generation = _parse_json(gen_raw)
    _require(type(generation) is dict and set(generation) == _GEN_FIELDS
        and generation["schema_version"] == batches.SCHEMA_VERSION and _raw(generation) == gen_raw,
        "generation artifact has noncanonical or unsupported fields")
    del gen_raw
    plan = plans.decode_campaign_plan(artifacts.read(plan_artifact, "campaign_plan", plans.MAX_PLAN_BYTES))
    recipe, page = generation["recipe"], generation["page"]
    _require(type(recipe) is dict and set(recipe) == _RECIPE_FIELDS
        and recipe["schema_version"] == "autoencoder-campaign-generation-recipe-v1"
        and recipe["selection_policy"] == "embedded-input-id-order-lowest-entry-cid-fixed-validation-v1"
        and generation["recipe_id"] == "sha256:" + _sha(recipe), "generation recipe identity or policy differs")
    _require(type(variant_record) is dict and set(variant_record) == {"variant_id", "manifest"}
        and type(variant_record["manifest"]) is dict and plans._token(variant_record["variant_id"]),
        "invalid captured variant")
    variant_id, variant = variant_record["variant_id"], variant_record["manifest"]
    _require(recipe["variant_id"] == plan["variant_id"] == variant_id
        and recipe["variant_manifest_sha256"] == plan["variant_manifest_sha256"] == _sha(variant)
        and _same(recipe["source_campaign_binding"], plan["source_campaign_binding"])
        and _same(plan["source_campaign_binding"], variant["source_campaign_binding"]),
        "campaign variant or source roots differ")
    _require(plan["parent_policy"] == "common_fixed_parent" and recipe["artifact_root"] == plan["artifact_root"],
        "generated page requires its original fixed parent and artifact root")
    _require(plans._hash(recipe["helper_source_sha256"]), "invalid historical generation producer digest")
    for name in ("artifact_root", "output_root"):
        value = recipe[name]
        _require(type(value) is str and Path(value).is_absolute() and str(Path(value)) == value
            and ".." not in Path(value).parts and "\x00" not in value and not value.startswith("//"),
            "historical campaign paths must remain absolute normalized data")
    _require(type(page) is dict and set(page) == {"start_batch", "max_batches", "total_batches", "selected_batch_ordinals"},
        "unexpected generation page fields")
    for value, minimum, maximum in ((recipe["training_batch_size"], 1, 128),
            (recipe["validation_batch_size"], 1, 255), (page["start_batch"], 0, ReceiptSetLimits().max_inputs - 1),
            (page["max_batches"], 1, plans.MAX_BATCHES)):
        _require(type(value) is int and minimum <= value <= maximum, "generation page selection bound differs")
    _require(recipe["training_batch_size"] + recipe["validation_batch_size"] <= 256, "job record limit differs")
    rows = generation["jobs"]
    _require(type(rows) is list and len(rows) == len(plan["batches"]) and 1 <= len(rows) <= plans.MAX_BATCHES
        and type(run_records) is list and len(run_records) == len(rows) + 1,
        "package must bind its template and every selected generated job")
    _require(all(type(row) is dict and set(row) == _JOB_FIELDS for row in rows), "unexpected generated job fields")
    for row in rows:
        for name in ("job_spec_artifact", "corpus_manifest_artifact", "produced_record_projection_artifact"):
            _ref(row[name])
    total_job_bytes = sum(_ref(row["job_spec_artifact"])["bytes"] for row in rows)
    _require(type(generation["total_job_bytes"]) is int and generation["total_job_bytes"] == total_job_bytes
        and total_job_bytes <= plans.MAX_TOTAL_JOB_BYTES, "aggregate generated job bytes differ")

    def verify_job(ref, expected):
        item = verify_detached_campaign_job(ref, resolver=artifacts.resolve,
            expected_job_spec_sha256=expected, variant_manifest=variant)
        _historical_cas(item["spec"], recipe["artifact_root"])
        for dependency in item["required_artifacts"]:
            for role in dependency["roles"]:
                artifacts.add(_bare(dependency), role)
        return item

    template_ref = _ref(recipe["template_job_spec_artifact"])
    template_item = verify_job(template_ref, recipe["template_job_spec_sha256"])
    template = template_item["spec"]
    _require(template.run_id == recipe["template_run_id"] and template.base_version_id == recipe["base_version_id"],
        "original template binding differs from generation recipe")
    _run(run_records[0], template, template_ref, variant_id, generated=False)
    root = template_item["_receipt_set"]
    _require(root.native_execution_profile, "generated page lacks its declared native-profile vectors")
    members, sources, statuses = batches._membership(root)
    chunks, validation, leaves, selected_sources, dispositions, coverage, selected_page = batches._select(
        root, members, sources, statuses, recipe["training_batch_size"], recipe["validation_batch_size"],
        page["start_batch"], page["max_batches"])
    _require(_same(page, selected_page) and _same(generation["coverage"], coverage)
        and _same(generation["input_dispositions"], dispositions)
        and _same(generation["selected_leaf_artifacts"], [leaves[key] for key in sorted(leaves)])
        and _same(generation["selected_source_artifacts"], [selected_sources[key] for key in sorted(selected_sources)]),
        "generation selection, full dispositions or selected closure differ from frozen roots")
    del members, sources, statuses, dispositions
    qualification = "deferred_to_worker" if template.target_snapshot_artifact is not None else "not_configured"
    _require(all(generation[name] is False for name in batches._FLAGS)
        and generation["target_membership_verified"] is False
        and generation["target_membership_qualification"] == qualification
        and generation["qualification_scope"] == "selected_source_inputs_and_registered_job_contracts_only",
        "generation artifact expanded its qualification")
    recipe_id = generation["recipe_id"]
    # The exhaustive census and template root graph have served their purpose.
    # Release them before each independently decoded generated-job verification.
    # The collector retains exact byte descriptors for the final rehash barrier.
    del generation, root, template_item
    specs, verifications, selected_ids = [template], [], set()
    payload = template.to_dict()
    _require(len(chunks) == len(rows), "generation omitted selected batches")
    for local, (row, batch, (ordinal, chunk), run) in enumerate(zip(rows, plan["batches"], chunks, run_records[1:])):
        item = verify_job(row["job_spec_artifact"], row["job_spec_sha256"])
        spec, verified = item["spec"], item["corpus_verification"]
        digest = _sha({"recipe_id": recipe_id, "ordinal": ordinal,
            "corpus_manifest_artifact": row["corpus_manifest_artifact"],
            "produced_record_projection_artifact": row["produced_record_projection_artifact"]})
        expected_job, expected_run = "campaign-job:" + digest, "campaign-run:" + digest
        _require(type(row["ordinal"]) is int and row["ordinal"] == ordinal and row["job_id"] == spec.job_id == expected_job
            and row["run_id"] == spec.run_id == expected_run, "global generated job ordinal or identity differs")
        _run(run, spec, _ref(row["job_spec_artifact"]), variant_id, generated=True)
        _require(spec.run_id != template.run_id and spec.job_id != template.job_id
            and spec.run_id not in selected_ids, "duplicate template or generated job identity")
        selected_ids.add(spec.run_id)
        generated_payload = spec.to_dict()
        varying = {"job_id", "run_id", "output_directory", "dataset_snapshot_id", "split_snapshot_id",
            "samples", "validation_samples", "corpus_manifest_artifact", "produced_record_projection_artifact",
            "corpus_source_artifacts", "embedding_receipt_artifacts"}
        _require(set(payload) == set(generated_payload)
            and all(_same(payload[key], generated_payload[key]) for key in payload.keys() - varying),
            "generated job changed template configuration or shared dependencies")
        _require(spec.output_directory == str(Path(recipe["output_root"]) / ("campaign-" + recipe_id[7:]) / f"batch-{ordinal:06d}"),
            "generated historical output path differs")
        _require(_same(_bare(asdict(spec.corpus_manifest_artifact)), row["corpus_manifest_artifact"])
            and _same(_bare(asdict(spec.produced_record_projection_artifact)), row["produced_record_projection_artifact"]),
            "generated corpus artifacts differ")
        # Reuse only this job's verified metadata. Source aliases can share an
        # input ID, so exact generation also requires its canonical occurrence.
        manifest = item["_manifest"]
        by_record = {record.record_id: EmbeddingInput.from_source_record(record).input_id for record in manifest.records}
        by_entry = {record["record_summary"]["record_id"]: record["entry_cid"]
            for record in item["_projection"].to_dict()["records"]}
        _require([by_record[key] for key in verified["training_record_ids"]] == [entry["input_id"] for entry in chunk]
            and [by_record[key] for key in verified["validation_record_ids"]] == [entry["input_id"] for entry in validation]
            and [by_entry[key] for key in verified["training_record_ids"]] == [entry["representative_entry_cid"] for entry in chunk]
            and [by_entry[key] for key in verified["validation_record_ids"]] == [entry["representative_entry_cid"] for entry in validation],
            "generated ordered samples differ from deterministic page selection")
        expected_batch = {"ordinal": local, "run_id": spec.run_id, "job_id": spec.job_id,
            "job_spec_artifact": row["job_spec_artifact"], "job_spec_sha256": spec.canonical_sha256,
            "base_version_id": spec.base_version_id, "training_record_ids": verified["training_record_ids"],
            "validation_record_ids": verified["validation_record_ids"], "target_snapshot_id": spec.target_snapshot_id,
            "target_snapshot_artifact": _bare(asdict(spec.target_snapshot_artifact)) if spec.target_snapshot_artifact else None,
            "arrow_feature_weights_artifact": _bare(asdict(spec.arrow_feature_weights_artifact)) if spec.arrow_feature_weights_artifact else None,
            "training_config_sha256": _sha(generated_payload["training_config"]),
            "autoencoder_config_sha256": _sha(generated_payload["autoencoder_config"])}
        expected_batch["batch_id"] = plans._batch_id(expected_batch)
        _require(_same(batch, expected_batch), "sealed plan differs from generated job configuration or ordered roles")
        specs.append(spec)
        verifications.append(verified)
        del manifest, item
    _require(_same(plan["coverage"], plans._coverage(verifications[0], plan["batches"])), "plan coverage differs from verified jobs")
    bases = {spec.base_version_id for spec in specs}
    versions, inventories = _versions(version_records, variant_id, bases, artifacts)
    for spec in specs:
        ref = _bare(asdict(spec.base_checkpoint))
        inventory = inventories[spec.base_version_id]
        _require(ref == versions[spec.base_version_id]["artifact"], "job base differs from registered checkpoint")
        expected = sorted((dict(item) for item in inventory.artifacts if dict(item) != ref), key=lambda item: item["sha256"])
        _require([_bare(asdict(item)) for item in sorted(spec.base_checkpoint_dependencies, key=lambda item: item.sha256)] == expected,
            "job checkpoint physical dependency closure differs")
    artifacts.current()
    return {"artifacts": artifacts.descriptors(), "coverage": coverage,
        "qualification": {"corpus_membership_verified": True, "selected_source_bytes_verified": True,
            "checkpoint_inventory_verified": True, "checkpoint_semantic_replay_verified": False,
            "weights_constructed": False, "target_membership_verified": False,
            "target_membership_qualification": qualification, "arrow_runtime_compatibility_verified": False,
            "expected_source_manifest_preserved": True, "execution_source_manifest_verified": False,
            "historical_absolute_paths_used": False, "execution_authorized": False,
            "full_source_payload_closure": False, "completion_history_exported": False,
            "source_authority_authenticated": False, "global_holdout_verified": False,
            "full_federal_corpus_complete": False, "constitution_formalized": False,
            "formalized": False, "admitted": False, "publication_performed": False,
            "training_performed": False}}


def inspect_campaign_inputs(generation_artifact, plan_artifact, *, variant_record,
        version_records, run_records, artifact_resolver, max_blob_bytes=256 * 1024**2,
        max_total_bytes=512 * 1024**2, max_blobs=4096):
    """Verify and derive the exact typed closure of a selected campaign page."""
    try:
        return _inspect_campaign_inputs(generation_artifact, plan_artifact,
            variant_record=variant_record, version_records=version_records, run_records=run_records,
            artifact_resolver=artifact_resolver, max_blob_bytes=max_blob_bytes,
            max_total_bytes=max_total_bytes, max_blobs=max_blobs)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, UnicodeError) as exc:
        if isinstance(exc, CampaignPackageInputError):
            raise
        raise CampaignPackageInputError("campaign package input verification failed: " + str(exc)) from exc


__all__ = ["CampaignPackageInputError", "inspect_campaign_inputs"]
