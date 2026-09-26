"""Prepare deterministic bounded v8 jobs from an existing sealed source campaign.

Only existing receipt vectors are consumed. This module neither builds targets
nor invokes a model, dispatches training, selects a head or publishes artifacts.
The caller owns resource admission for source reads, CAS staging and registry
commands. Unregistered staged bytes may remain after a failed preparation.
"""
from __future__ import annotations

from collections import Counter
from contextlib import nullcontext
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile

from ...duckdb_control.autoencoder_registry import RegistryError, SCHEMA as REGISTRY_SCHEMA
from . import autoencoder_campaign_plan as plans
from . import autoencoder_embedding_receipt_set as receipt_sets
from . import autoencoder_training_coordinator as coordinator
from .autoencoder_corpus_manifest import build_corpus_manifest
from .autoencoder_embedding_production import EmbeddingInput
from .autoencoder_produced_record_projection import build_produced_record_projection
from .autoencoder_source_partitions import load_source_partitions
from .autoencoder_training_worker import CAMPAIGN_SCHEMA_VERSION, TrainingJobSpec, verify_corpus_job_inputs
from .autoencoder_uscode_inventory import load_uscode_source_inventory
from .legal_ir_eval_splits import HPARAM_SELECTION_OPERATION, TRAINING_OPERATION


SCHEMA_VERSION = "autoencoder-campaign-generation-v1"
REPORT_SCHEMA_VERSION = "autoencoder-campaign-generation-report-v1"
MAX_SELECTED_LEAF_BYTES = 64 * 1024**2
MAX_SELECTED_SOURCE_BYTES = 64 * 1024**2
MAX_TOTAL_JOB_BYTES = 64 * 1024**2
MAX_GENERATION_BYTES = 64 * 1024**2
_SPLITS = ("train", "validation", "canary", "holdout")
_FLAGS = ("admitted", "formalized", "source_authority_authenticated", "global_holdout_verified",
          "training_dispatched", "promotion_performed", "publication_performed")


class CampaignBatchError(ValueError):
    """A bounded generation recipe or its immutable inputs are inconsistent."""


def _require(value, message):
    if not value:
        raise CampaignBatchError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CampaignBatchError("generation values require finite canonical JSON") from exc


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _bare(ref):
    return {name: ref[name] for name in ("sha256", "bytes")}


def _source_hash():
    return _sha(Path(__file__).read_bytes())


def _stage_bytes(registry, raw, guard):
    guard()
    descriptor, filename = tempfile.mkstemp(prefix=".campaign-generation-", dir=registry.artifact_root)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        stored = registry.stage_artifact(filename, _sha(raw))
        _require(stored == {"sha256": _sha(raw), "bytes": len(raw)}, "staged generation bytes differ")
        guard()
        return stored
    finally:
        Path(filename).unlink(missing_ok=True)


def _path_ref(registry, ref):
    return {**ref, "path": str(registry.artifact_path(ref))}


def _load(loader, artifact, **kwargs):
    return loader(artifact.path, expected_sha256=artifact.sha256,
                  expected_size_bytes=artifact.bytes, **kwargs)


def _bounded_resolver(resolver, allowed, label):
    captured = receipt_sets._captured_resolver(resolver)
    def resolve(ref):
        _require(ref.get("sha256") in allowed and allowed[ref["sha256"]] == ref,
                 f"{label} is outside the selected page closure")
        return captured(ref)
    return resolve


def _membership(root):
    """Read the full frozen denominator without opening sources or leaves."""
    inventory = root.partitions.inventory.to_dict()
    aliases, source_refs, statuses = {}, {}, Counter()
    for shard in inventory["shards"]:
        for row in shard["rows"]:
            statuses[row["status"]] += 1
            if row["status"] != "ready_published_text":
                continue
            entry = row["entry_cid"]
            binding = root.binding_for(entry)
            aliases.setdefault(binding["input_id"], []).append(entry)
            meta = row["metadata"]
            source_refs[entry] = {"sha256": meta["text_sha256"], "bytes": meta["text_bytes"]}
    members = []
    for input_id in sorted(aliases):
        entries = sorted(aliases[input_id])
        binding = root.binding_for(entries[0])
        _require(all(root.binding_for(entry)["split"] == binding["split"] for entry in entries),
                 "source aliases cross frozen partitions")
        members.append({"input_id": input_id, "entry_cids": entries,
            "representative_entry_cid": entries[0], "split": binding["split"],
            "embedding_status": binding["status"]})
    return members, source_refs, dict(sorted(statuses.items()))


def _select(root, members, sources, source_status_counts, training_batch_size, validation_batch_size, start_batch, max_batches):
    train = [row for row in members if row["split"] == "train" and row["embedding_status"] == "embedded"]
    validation = [row for row in members if row["split"] == "validation" and row["embedding_status"] == "embedded"]
    _require(train and validation, "generation requires embedded training and validation members; no resampling")
    total_batches = (len(train) + training_batch_size - 1) // training_batch_size
    _require(start_batch < total_batches, "start_batch is beyond the embedded training batches")
    ordinals = list(range(start_batch, min(total_batches, start_batch + max_batches)))
    fixed_validation = validation[:validation_batch_size]
    chunks = [(ordinal, train[ordinal * training_batch_size:(ordinal + 1) * training_batch_size])
              for ordinal in ordinals]
    selected_train = [row for _, chunk in chunks for row in chunk]
    train_entries = [row["representative_entry_cid"] for row in selected_train]
    validation_entries = [row["representative_entry_cid"] for row in fixed_validation]
    # Both complete operation groups are authorized before any selected I/O.
    root.partitions.authorize(TRAINING_OPERATION, train_entries)
    root.partitions.authorize(HPARAM_SELECTION_OPERATION, validation_entries)
    leaves, selected_sources = {}, {}
    for _, chunk in chunks:
        entries = [row["representative_entry_cid"] for row in (*chunk, *fixed_validation)]
        for ref in root.selected_leaf_artifacts(entries):
            leaves[ref["sha256"]] = ref
        for entry in entries:
            ref = sources[entry]
            previous = selected_sources.setdefault(ref["sha256"], ref)
            _require(previous == ref, "selected source size declarations differ")
    _require(sum(ref["bytes"] for ref in leaves.values()) <= MAX_SELECTED_LEAF_BYTES,
             "selected page leaf bytes exceed bound; fixed batches are not repacked")
    _require(sum(ref["bytes"] for ref in selected_sources.values()) <= MAX_SELECTED_SOURCE_BYTES,
             "selected page source bytes exceed bound; fixed batches are not repacked")
    selected_ids = {row["input_id"] for row in selected_train}
    validation_ids = {row["input_id"] for row in fixed_validation}
    train_ordinals = {row["input_id"]: number // training_batch_size for number, row in enumerate(train)}
    dispositions = []
    for row in members:
        split, status, input_id = row["split"], row["embedding_status"], row["input_id"]
        if split in {"canary", "holdout"}:
            disposition = "protected_" + split
        elif status != "embedded":
            disposition = status
        elif split == "train":
            disposition = "planned_training" if input_id in selected_ids else "deferred_training"
        else:
            disposition = "fixed_validation" if input_id in validation_ids else "deferred_validation"
        dispositions.append({**row, "disposition": disposition, "batch_ordinal": train_ordinals.get(input_id)})
    summary = root.summary()
    statuses = {split: dict.fromkeys(receipt_sets.STATUSES, 0) for split in _SPLITS}
    for row in members:
        statuses[row["split"]][row["embedding_status"]] += 1
    coverage = {"physical_row_count": summary["physical_row_count"], "eligible_row_count": summary["eligible_row_count"],
        "excluded_row_count": summary["excluded_row_count"],
        "alias_row_count": summary["eligible_row_count"] - summary["eligible_unique_input_count"],
        "eligible_unique_input_count": summary["eligible_unique_input_count"],
        "source_partition_counts": root.partitions.partition_counts,
        "source_status_counts": source_status_counts,
        "unique_embedding_status_counts": summary["unique_status_counts"], "unique_split_status_counts": statuses,
        "embedded_training_input_count": len(train), "embedded_validation_input_count": len(validation),
        "selected_training_input_count": len(selected_train), "deferred_training_input_count": len(train) - len(selected_train),
        "selected_validation_input_count": len(fixed_validation), "deferred_validation_input_count": len(validation) - len(fixed_validation),
        "protected_canary_input_count": sum(statuses["canary"].values()),
        "protected_holdout_input_count": sum(statuses["holdout"].values())}
    page = {"start_batch": start_batch, "max_batches": max_batches, "total_batches": total_batches,
            "selected_batch_ordinals": ordinals}
    return chunks, fixed_validation, leaves, selected_sources, dispositions, coverage, page


def _create_receipt(receipt, operation_id, payload):
    expected = {"schema": REGISTRY_SCHEMA, "operation_id": operation_id, "command": "CreateRun",
                "admitted": False, "run_id": payload["run_id"], "status": "queued"}
    _require(_raw(receipt) == _raw(expected), "CreateRun receipt differs from stable generation command")


def _run_binding(run, payload):
    _require(all(_raw(run[name]) == _raw(payload[name]) for name in ("variant_id", "base_version_id", "spec")),
             "existing generated run differs from its immutable job")


def _preflight_registration(registry, operation_id, payload, output):
    receipt = registry.resolve_operation(operation_id, "CreateRun", payload)
    if receipt is not None:
        _create_receipt(receipt, operation_id, payload)
    try:
        run = registry.get_run(payload["run_id"])
    except RegistryError as exc:
        if str(exc) != "unknown run":
            raise
        _require(receipt is None, "committed CreateRun operation has no corresponding run")
        _require(not output.exists() and not output.is_symlink(), "new generated attempt output already exists")
        return
    _require(receipt is not None, "existing generated run lacks its exact stable CreateRun operation")
    _run_binding(run, payload)


def _register(registry, operation_id, payload):
    try:
        receipt = registry.create_run(operation_id, **payload)
    except Exception:
        # Resolve only this stable command, never invent a second operation ID.
        receipt = registry.resolve_operation(operation_id, "CreateRun", payload)
        if receipt is None:
            raise
    _create_receipt(receipt, operation_id, payload)
    _run_binding(registry.get_run(payload["run_id"]), payload)


def prepare_campaign_batches(registry, template_run_id, *, receipt_resolver, source_resolver, output_root,
                             training_batch_size=128, validation_batch_size=16, start_batch=0, max_batches=128):
    """Stage and register one deterministic page, then seal its existing plan.

    ``output_root`` must be an existing absolute directory. Page arguments do
    not affect recipe or job identities. Fixed validation members may repeat;
    physical aliases contribute one canonical input. Byte overflow fails rather
    than changing batch boundaries. Shared targets/Arrow descriptors are kept
    unchanged; runtime membership and compatibility remain worker checks.
    """
    return _prepare_campaign_batches(registry, template_run_id, receipt_resolver=receipt_resolver,
        source_resolver=source_resolver, output_root=output_root, training_batch_size=training_batch_size,
        validation_batch_size=validation_batch_size, start_batch=start_batch, max_batches=max_batches,
        reuse_root_metadata=True)


def _prepare_campaign_batches(registry, template_run_id, *, receipt_resolver, source_resolver, output_root,
                             training_batch_size=128, validation_batch_size=16, start_batch=0, max_batches=128, reuse_root_metadata=True):
    """Stage and register one deterministic page, then seal its existing plan.

    ``output_root`` must be an existing absolute directory. Page arguments do
    not affect recipe or job identities. Fixed validation members may repeat;
    physical aliases contribute one canonical input. Byte overflow fails rather
    than changing batch boundaries. Shared targets/Arrow descriptors are kept
    unchanged; runtime membership and compatibility remain worker checks.
    """
    _require(type(reuse_root_metadata) is bool, "reuse_root_metadata must be boolean")
    for value, minimum, maximum, label in ((training_batch_size, 1, 128, "training_batch_size"),
            (validation_batch_size, 1, 255, "validation_batch_size"),
            (start_batch, 0, receipt_sets.ReceiptSetLimits().max_inputs - 1, "start_batch"),
            (max_batches, 1, plans.MAX_BATCHES, "max_batches")):
        _require(type(value) is int and minimum <= value <= maximum, f"invalid bounded {label}")
    _require(training_batch_size + validation_batch_size <= 256, "training and validation exceed per-job record bound")
    _require(callable(receipt_resolver) and callable(source_resolver), "both selected artifact resolvers are required")
    _require(plans._token(template_run_id), "invalid template run identifier")
    _require(isinstance(output_root, (str, Path)), "output_root must be a local absolute directory")
    output = Path(output_root)
    _require(output.is_absolute() and output.is_dir() and not output.is_symlink()
             and output == output.resolve(), "output_root must be an existing absolute directory without aliases")
    before = _source_hash()
    parent = None
    root_scope = None
    spec = None
    def guard():
        if root_scope is not None:
            root_scope.check(spec)
        _require(before == _source_hash(), "campaign batch helper changed during preparation")
        _require(output.is_dir() and not output.is_symlink() and output == output.resolve(), "output root changed or became aliased")
        if parent is not None:
            _require(not parent.is_symlink() and parent == parent.resolve()
                     and (not parent.exists() or parent.is_dir()), "recipe output parent is aliased or not a directory")

    try:
        from .autoencoder_campaign_job_inputs import (
            _CampaignRootScope, _preflight_campaign_job_inputs, _verify_prepared_campaign_job_inputs)
        scope_context = _CampaignRootScope(registry) if reuse_root_metadata else nullcontext(None)
        with scope_context as root_scope:
            template = (coordinator.registered_corpus_job_inputs(registry, template_run_id) if root_scope is None else
                coordinator._registered_corpus_job_inputs(registry, template_run_id, root_scope=root_scope))
            spec, run = template["spec"], template["run"]
            _require(spec.schema_version == CAMPAIGN_SCHEMA_VERSION, "generation requires a registered v8 template")
            plans._verify_extra_artifacts(registry, spec)
            if root_scope is None:
                inventory = _load(load_uscode_source_inventory, spec.source_inventory_artifact)
                partitions = _load(load_source_partitions, spec.source_partitions_artifact, inventory=inventory)
                root = _load(receipt_sets.load_embedding_receipt_set, spec.embedding_receipt_set_artifact, partitions=partitions)
                del inventory, partitions
            else:
                _, _, root = root_scope.roots_for(spec)
            _require(root.native_execution_profile, "generation requires existing native-profile receipt vectors")
            members, sources, source_status_counts = _membership(root)
            chunks, validation, leaves, selected_sources, dispositions, coverage, page = _select(
                root, members, sources, source_status_counts, training_batch_size, validation_batch_size, start_batch, max_batches)
            del members, sources
            selected = {row["input_id"] for _, chunk in chunks for row in chunk} | {row["input_id"] for row in validation}
            leaf_resolve = _bounded_resolver(receipt_resolver, leaves, "receipt leaf")
            source_resolve = _bounded_resolver(source_resolver, selected_sources, "source artifact")
            records = {}
            for leaf in sorted(leaves):
                receipt, _ = root._checked_member(leaf, leaf_resolve)
                # Public to_corpus_records verifies every source in a shared leaf.
                # Decode here, then authorize/verify only exact selected records in
                # the existing produced-projection builder below.
                for record in receipt._corpus_records():
                    input_id = EmbeddingInput.from_source_record(record).input_id
                    if input_id in selected:
                        _require(input_id not in records, "selected input is owned by multiple receipt leaves")
                        records[input_id] = record
                del receipt
            _require(set(records) == selected, "selected embedded inputs are absent from their sealed leaves")

            payload = spec.to_dict()
            recipe = {"schema_version": "autoencoder-campaign-generation-recipe-v1",
                "template_run_id": template_run_id, "template_job_spec_artifact": template["job_spec_artifact"],
                "template_job_spec_sha256": spec.canonical_sha256, "variant_id": run["variant_id"],
                "variant_manifest_sha256": _sha(_raw(template["variant"])), "base_version_id": spec.base_version_id,
                "source_campaign_binding": template["variant"]["source_campaign_binding"],
                "artifact_root": str(registry.artifact_root), "output_root": str(output),
                "training_batch_size": training_batch_size, "validation_batch_size": validation_batch_size,
                "selection_policy": "embedded-input-id-order-lowest-entry-cid-fixed-validation-v1",
                "helper_source_sha256": before}
            recipe_id = "sha256:" + _sha(_raw(recipe))
            parent = output / ("campaign-" + recipe_id.split(":", 1)[1])
            jobs, total_bytes = [], 0
            staged = {}
            for ordinal, chunk in chunks:
                chosen = [*chunk, *validation]
                by_record = {records[row["input_id"]].record_id: row["representative_entry_cid"] for row in chosen}
                manifest = build_corpus_manifest([records[row["input_id"]] for row in chosen],
                    training_record_ids=[records[row["input_id"]].record_id for row in chunk],
                    validation_record_ids=[records[row["input_id"]].record_id for row in validation])
                projection = build_produced_record_projection(root, manifest,
                    entry_cids=[by_record[record.record_id] for record in manifest.records],
                    receipt_resolver=leaf_resolve, source_resolver=source_resolve)
                manifest_ref = _stage_bytes(registry, manifest.to_bytes(), guard)
                projection_ref = _stage_bytes(registry, projection.to_bytes(), guard)
                selected_artifacts = projection.selected_artifacts()
                for label, refs, resolver in (("leaf", selected_artifacts["leaf_receipts"], leaf_resolve),
                                             ("source", selected_artifacts["source_artifacts"], source_resolve)):
                    for ref in refs:
                        key = (label, ref["sha256"])
                        if key not in staged:
                            guard()
                            actual = registry.stage_artifact(resolver(ref), ref["sha256"])
                            _require(actual == ref, "selected staged bytes differ from declared closure")
                            staged[key] = actual
                            guard()
                job_digest = _sha(_raw({"recipe_id": recipe_id, "ordinal": ordinal,
                    "corpus_manifest_artifact": manifest_ref, "produced_record_projection_artifact": projection_ref}))
                job_id, run_id = "campaign-job:" + job_digest, "campaign-run:" + job_digest
                generated = {**payload, "job_id": job_id, "run_id": run_id,
                    "output_directory": str(parent / f"batch-{ordinal:06d}"),
                    "dataset_snapshot_id": manifest.dataset_snapshot_id, "split_snapshot_id": manifest.split_snapshot_id,
                    "samples": [asdict(records[row["input_id"]].sample) for row in chunk],
                    "validation_samples": [asdict(records[row["input_id"]].sample) for row in validation],
                    "corpus_manifest_artifact": _path_ref(registry, manifest_ref),
                    "produced_record_projection_artifact": _path_ref(registry, projection_ref),
                    "corpus_source_artifacts": [_path_ref(registry, ref) for ref in selected_artifacts["source_artifacts"]],
                    "embedding_receipt_artifacts": [_path_ref(registry, ref) for ref in selected_artifacts["leaf_receipts"]]}
                job = TrainingJobSpec.from_dict(generated)
                if root_scope is None:
                    verify_corpus_job_inputs(job)
                else:
                    prepared = _preflight_campaign_job_inputs(job, root_scope=root_scope)
                    _verify_prepared_campaign_job_inputs(job, prepared)
                    del prepared
                raw = _raw(job.to_dict())
                total_bytes += len(raw)
                _require(total_bytes <= MAX_TOTAL_JOB_BYTES, "selected page job bytes exceed bound; fixed batches are not repacked")
                job_ref = _stage_bytes(registry, raw, guard)
                jobs.append({"ordinal": ordinal, "job_id": job_id, "run_id": run_id,
                    "job_spec_sha256": job.canonical_sha256, "job_spec_artifact": job_ref,
                    "corpus_manifest_artifact": manifest_ref, "produced_record_projection_artifact": projection_ref})

            flags = {name: False for name in _FLAGS}
            qualification = "deferred_to_worker" if spec.target_snapshot_artifact is not None else "not_configured"
            scope = "selected_source_inputs_and_registered_job_contracts_only"
            generation = {"schema_version": SCHEMA_VERSION, "recipe_id": recipe_id, "recipe": recipe,
                "page": page, "jobs": jobs, "coverage": coverage, "input_dispositions": dispositions,
                "selected_leaf_artifacts": [leaves[key] for key in sorted(leaves)],
                "selected_source_artifacts": [selected_sources[key] for key in sorted(selected_sources)],
                "total_job_bytes": total_bytes, "target_membership_verified": False,
                "target_membership_qualification": qualification,
                "qualification_scope": scope, **flags}
            generation_raw = _raw(generation)
            _require(len(generation_raw) <= MAX_GENERATION_BYTES, "generation manifest exceeds byte bound")
            generation_ref = _stage_bytes(registry, generation_raw, guard)
            # Keep only the one scoped root graph while sealing the plan. Per-job
            # records, projections and exhaustive disposition reports can be freed.
            del generation_raw, generation, dispositions, records, root, projection, manifest
            del chunks, validation, recipe, job, generated, raw, payload

            def final_inputs():
                guard()
                # Rehash the captured original paths as well as all staged copies.
                # A later callback must not conceal mutation of an earlier source.
                receipt_sets._rehash(leaves.values(), leaf_resolve, "selected receipt leaf")
                receipt_sets._rehash(selected_sources.values(), source_resolve, "selected source")
                for name in ("source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact",
                             "corpus_manifest_artifact", "produced_record_projection_artifact",
                             "target_snapshot_artifact", "arrow_feature_weights_artifact", "base_checkpoint"):
                    artifact = getattr(spec, name)
                    if artifact is not None:
                        registry.verify_artifact(_bare(asdict(artifact)))
                for artifact in (*spec.base_checkpoint_dependencies, *spec.corpus_source_artifacts, *spec.embedding_receipt_artifacts):
                    registry.verify_artifact(_bare(asdict(artifact)))
                registry.verify_artifact(template["job_spec_artifact"])
                for ref in (*staged.values(), generation_ref):
                    registry.verify_artifact(ref)
                for row in jobs:
                    for name in ("job_spec_artifact", "corpus_manifest_artifact", "produced_record_projection_artifact"):
                        registry.verify_artifact(row[name])
                plans._verify_extra_artifacts(registry, spec)
                _require(registry.get_variant(run["variant_id"])["manifest"] == template["variant"], "template variant changed")
                _run_binding(registry.get_run(template_run_id), run)
                guard()

            final_inputs()
            commands = []
            for row in jobs:
                command = {"run_id": row["run_id"], "variant_id": run["variant_id"], "base_version_id": spec.base_version_id,
                           "spec": {"job_spec_sha256": row["job_spec_sha256"], "job_spec_artifact": row["job_spec_artifact"]}}
                operation_id = "campaign-create:" + row["job_id"].split(":", 1)[1]
                _preflight_registration(registry, operation_id, command, parent / f"batch-{row['ordinal']:06d}")
                commands.append((operation_id, command))
            final_inputs()
            parent.mkdir(exist_ok=True)
            guard()
            for operation_id, command in commands:
                guard()
                _register(registry, operation_id, command)
                guard()
            final_inputs()
            if root_scope is None:
                plan_ref = plans.seal_campaign_plan(registry, [row["run_id"] for row in jobs], parent_policy="common_fixed_parent")
            else:
                plan_ref = plans._seal_campaign_plan(registry, [row["run_id"] for row in jobs],
                    parent_policy="common_fixed_parent", root_scope=root_scope)
            final_inputs()
            registry.verify_artifact(plan_ref)
            guard()
            return {"schema_version": REPORT_SCHEMA_VERSION, "recipe_id": recipe_id, "page": page,
                "generation_artifact": generation_ref, "plan_artifact": plan_ref, "run_ids": [row["run_id"] for row in jobs],
                "jobs": jobs, "coverage": coverage, "target_membership_verified": False,
                "target_membership_qualification": qualification,
                "qualification_scope": scope, **flags}
    except (ValueError, TypeError, KeyError, OSError) as exc:
        if isinstance(exc, CampaignBatchError):
            raise
        raise CampaignBatchError("cannot prepare verified campaign batches: " + str(exc)) from exc
