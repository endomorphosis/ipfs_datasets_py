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


# This opt-in profile stages provenance, not a numerical training input. The
# v6/v8 functions above and their closed worker/checkpoint profiles stay intact.
REVIEWED_CYCLE_SCHEMA = "reviewed-example-cycle-input-artifact/v2"
REVIEWED_CYCLE_PROFILE = "complete-reviewed-typed-transition-staging/v2"
REVIEWED_COMPONENT_CYCLE_SCHEMA = "reviewed-example-cycle-input-artifact/v3"
REVIEWED_COMPONENT_CYCLE_PROFILE = "independently-reviewed-component-transition-staging/v3"
_REVIEWED_COMPONENT_RECEIPTS_SCHEMA = "reviewed-cycle-component-consumer-receipts/v1"
REVIEWED_MIXED_CYCLE_SCHEMA = "reviewed-example-cycle-input-artifact/v4"
REVIEWED_MIXED_CYCLE_PROFILE = "mixed-sort-admission-component-transition-staging/v4"
REVIEWED_MIXED_ADMISSION_PROFILE = "complete-reviewed-mixed-sort-norm-admission/v3"
_REVIEWED_MIXED_COMPONENT_RECEIPTS_SCHEMA = "reviewed-cycle-component-consumer-receipts/v2"
REVIEWED_MIXED_DECODER_INPUT_SCHEMA = "reviewed-decoder-training-inputs/v4"
REVIEWED_MIXED_DECODER_INPUT_PROFILE = "mixed-sort-admission-component-decoder-training-inputs/v4"


def _reviewed_cycle_contract(version):
    """Closed admission selection; old cycle V3 remains admission V2."""
    from ...optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    if version == "v2":
        from . import legal_norm_content_adjudication_v1 as admission
        return {"admission": admission, "assess": admission.assess_reviewed_norm_admission_v2,
            "prepare": consumer.prepare_reviewed_source_span_consumer_binding_v2,
            "validate": consumer.validate_reviewed_source_span_consumer_binding_v2,
            "consume": consumer.consume_reviewed_source_span_binding_v2,
            "receipt_schema": consumer.REVIEWED_SCHEMA, "aggregate_schema": _REVIEWED_COMPONENT_RECEIPTS_SCHEMA}
    if version == "v3":
        from . import legal_reviewed_norm_admission_v3 as admission
        return {"admission": admission, "assess": admission.assess_reviewed_norm_admission_v3,
            "prepare": consumer.prepare_reviewed_source_span_consumer_binding_v3,
            "validate": consumer.validate_reviewed_source_span_consumer_binding_v3,
            "consume": consumer.consume_reviewed_source_span_binding_v3,
            "receipt_schema": consumer.REVIEWED_V3_SCHEMA, "aggregate_schema": _REVIEWED_MIXED_COMPONENT_RECEIPTS_SCHEMA}
    raise ValueError("unsupported explicit reviewed admission contract")


def _reviewed_cycle_fields(version):
    return _REVIEWED_ARTIFACT_FIELDS | ({"admission_profile"} if version == "v3" else set())


MAX_REVIEWED_CYCLE_ROWS = 128
MAX_REVIEWED_HISTORY = 512
MAX_REVIEWED_HISTORY_BYTES = 8 * 1024**2
MAX_REVIEWED_ARTIFACT_BYTES = 32 * 1024**2
MAX_REVIEWED_STAGE_BYTES = 64 * 1024**2
_REVIEWED_COMPATIBILITY = {
    "source_sample_record_projection_performed": False,
    "training_job_profile_supported": False,
    "registered_input_snapshot": False,
    "numerical_consumption_ready": False,
    "weights_updated": False,
    "optimizer_resumed": False,
    "model_or_registry_promotion_authorized": False,
    "reason": "compatible_full_typed_training_profile_unprovided",
}
_REVIEWED_ARTIFACT_FIELDS = {
    "schema", "profile", "transition_kind", "parent_artifact", "rows_artifact",
    "consumer_receipt", "admission_assessment_artifact", "admission_transport_artifact",
    "split_manifest_artifact", "history_artifact", "transition", "checkpoint_lineage",
    "implementation", "compatibility", "history_guard", "withdrawal_provenance",
}


def _reviewed_need(condition, message):
    if not condition:
        raise ValueError(message)


def _reviewed_wire(value):
    import json
    from ...optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer

    # Reuse the bounded ordinary-JSON guard; bytes are handled separately by the
    # admission transport, never converted into strings by this JSON path.
    raw = consumer._preflight(value)
    _reviewed_need(len(raw) <= MAX_REVIEWED_ARTIFACT_BYTES, "unsupported_reviewed_artifact_capacity")
    return raw


def _reviewed_json(raw):
    import json

    _reviewed_need(type(raw) is bytes and len(raw) <= MAX_REVIEWED_ARTIFACT_BYTES,
                   "bounded exact reviewed artifact bytes required")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _reviewed_need(key not in result, "duplicate reviewed artifact JSON key")
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    _reviewed_need(_reviewed_wire(value) == raw, "canonical reviewed artifact JSON required")
    return value


def _reviewed_copy(value, expected_sha256=None):
    import hashlib
    raw = _reviewed_wire(value)
    if expected_sha256 is not None:
        _reviewed_sha(expected_sha256)
        _reviewed_need(hashlib.sha256(raw).hexdigest() == expected_sha256,
                       "complete reviewed input commitment differs")
    return _reviewed_json(raw)


def _reviewed_sha(value):
    import re
    _reviewed_need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
                   "exact lowercase reviewed SHA256 required")


def _reviewed_closed(value, fields, label):
    _reviewed_need(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _reviewed_ref(value):
    from pathlib import Path
    _reviewed_closed(value, {"path", "sha256", "bytes"}, "artifact reference")
    _reviewed_sha(value["sha256"])
    _reviewed_need(type(value["bytes"]) is int and value["bytes"] >= 0,
                   "plain nonnegative artifact byte count required")
    _reviewed_need(type(value["path"]) is str and "\x00" not in value["path"]
                   and Path(value["path"]).is_absolute()
                   and all(part != ".." for part in Path(value["path"]).parts),
                   "absolute declared artifact path required")
    return {key: value[key] for key in ("sha256", "bytes")}


def _reviewed_read(registry, reference):
    import hashlib
    from pathlib import Path
    descriptor = _reviewed_ref(reference)
    _reviewed_need(Path(reference["path"]) == registry.artifact_path(descriptor),
                   "artifact path differs from registry-owned identity")
    raw = registry.read_artifact(descriptor, max_bytes=MAX_REVIEWED_ARTIFACT_BYTES)
    _reviewed_need(type(raw) is bytes and len(raw) == descriptor["bytes"]
                   and hashlib.sha256(raw).hexdigest() == descriptor["sha256"],
                   "registry artifact exact readback differs")
    return raw


def _reviewed_lineage(value):
    _reviewed_closed(value, {"schema", "base_checkpoint", "parent_checkpoint", "optimizer_state", "weights_updated"},
                     "checkpoint lineage declaration")
    _reviewed_need(value["schema"] == "reviewed-cycle-checkpoint-lineage/v1"
                   and value["weights_updated"] is False, "metadata-only checkpoint lineage required")
    for key in ("base_checkpoint", "parent_checkpoint", "optimizer_state"):
        if value[key] is not None:
            _reviewed_ref(value[key])  # No checkpoint path or tensor is opened.


def _reviewed_history(value, current_manifest, rows, config, parent_history, split_owner, *, withdrawal=False):
    import hashlib
    from dataclasses import replace

    _reviewed_closed(value, {"schema", "scope_id", "scope_kind", "split_manifests", "records", "parent_history_artifact"},
                     "complete declared guard history")
    _reviewed_need(value["schema"] == "reviewed-example-cycle-history/v1"
                   and type(value["scope_id"]) is str and 0 < len(value["scope_id"]) <= 512
                   and value["scope_kind"] in {"complete_declared_history", "declared_genesis"},
                   "explicit declared historical scope required")
    _reviewed_need(type(value["records"]) is list and len(value["records"]) <= MAX_REVIEWED_HISTORY,
                   "unsupported_historical_guard_capacity")
    _reviewed_need(type(value["split_manifests"]) is list
                   and len(value["split_manifests"]) <= MAX_REVIEWED_HISTORY,
                   "unsupported_historical_guard_capacity")
    if parent_history is not None:
        _reviewed_need(value["scope_kind"] == "complete_declared_history"
                       and value["scope_id"] == parent_history["scope_id"], "historical scope changed")
        prefix = value["split_manifests"][:len(parent_history["split_manifests"])]
        _reviewed_need(prefix == parent_history["split_manifests"], "parent split history omitted or changed")
    elif value["scope_kind"] == "declared_genesis":
        _reviewed_need(not value["split_manifests"], "genesis cannot omit declared predecessors")

    cfg = split_owner.LegalIREvalSplitConfig(**config)
    _reviewed_need(cfg.to_dict() == config, "complete existing split configuration required")
    _reviewed_need(cfg.protected_splits == split_owner.PROTECTED_LEGAL_IR_SPLITS,
                   "configuration and frozen protected profile must agree")
    manifests = list(value["split_manifests"])
    current_sha = hashlib.sha256(_reviewed_wire(current_manifest)).hexdigest()
    if not any(entry.get("sha256") == current_sha for entry in manifests if type(entry) is dict):
        manifests.append({"manifest": current_manifest, "sha256": current_sha})
    _reviewed_need(len(manifests) <= MAX_REVIEWED_HISTORY, "unsupported_historical_guard_capacity")
    examples, assignments, assignment_conflicts, manifest_hashes = {}, {}, {}, set()
    unicode_by_id, fingerprint_spaces = {}, {}
    for entry in manifests:
        _reviewed_closed(entry, {"manifest", "sha256"}, "pinned historical split manifest")
        data = _reviewed_copy(entry["manifest"], entry["sha256"])
        _reviewed_need(entry["sha256"] not in manifest_hashes, "duplicate historical manifest identity")
        manifest_hashes.add(entry["sha256"])
        resolved = split_owner.LegalIRSplitManifest.from_mapping(data)
        _reviewed_need(resolved.to_dict() == data and resolved.config_digest == cfg.digest
                       and resolved.protected_splits == split_owner.PROTECTED_LEGAL_IR_SPLITS
                       and resolved.partition_names == split_owner.LEGAL_IR_EVAL_SPLITS
                       and set(resolved.assignments) == {item.sample_id for item in resolved.examples},
                       "frozen split policy, metadata or population differs")
        metadata = {key: resolved.metadata[key] for key in ("campaign_split_profile", "unicode_data_version")
                    if key in resolved.metadata}
        if metadata:
            split_owner.legal_ir_split_source_fingerprint("", metadata=metadata)
        unicode_profile = bool(metadata and metadata.get("campaign_split_profile")
                               == split_owner.UNICODE_CAMPAIGN_SPLIT_PROFILE)
        fingerprint_spaces.setdefault(unicode_profile, metadata)
        for key, conflicts in resolved.assignment_conflicts.items():
            merged = assignment_conflicts.setdefault(key, [])
            for split in conflicts:
                if split not in merged:
                    merged.append(split)
        for example in resolved.examples:
            key, assignment = example.sample_id, resolved.assignments[example.sample_id]
            _reviewed_need(key not in examples or (examples[key].to_dict() == example.to_dict()
                           and assignments[key] == assignment), "historical example or assignment changed")
            _reviewed_need(unicode_by_id.get(key, unicode_profile) == unicode_profile,
                           "historical source fingerprint profile changed")
            examples[key], assignments[key] = example, assignment
            unicode_by_id[key] = unicode_profile
    _reviewed_need(len(examples) <= MAX_REVIEWED_HISTORY
                   and len(fingerprint_spaces) * len(examples) * (len(examples) - 1) // 2 <= 131072,
                   "unsupported_historical_guard_capacity")
    records, source_bytes = {}, 0
    recomputed = {profile: {} for profile in fingerprint_spaces}
    for record in value["records"]:
        _reviewed_closed(record, {"id", "source_text", "source_sha256", "split_example", "assignment"},
                         "historical source replay record")
        key = record["id"]
        _reviewed_need(type(key) is str and key in examples and key not in records,
                       "historical source population missing, duplicate or foreign")
        _reviewed_need(type(record["source_text"]) is str, "unsupported_historical_source_replay")
        raw = record["source_text"].encode("utf-8")
        source_bytes += len(raw)
        _reviewed_need(source_bytes <= MAX_REVIEWED_HISTORY_BYTES, "unsupported_historical_guard_capacity")
        _reviewed_need(hashlib.sha256(raw).hexdigest() == record["source_sha256"],
                       "historical source bytes differ")
        frozen = examples[key]
        text = record["source_text"]
        for profile, metadata in fingerprint_spaces.items():
            if metadata:
                content_hash, fingerprint = split_owner.legal_ir_split_source_fingerprint(text, metadata=metadata)
            else:
                actual = split_owner.LegalIRSplitExample.from_sample({"id": key, "text": text})
                content_hash, fingerprint = actual.content_hash, actual.token_fingerprint
            if profile == unicode_by_id[key]:
                _reviewed_need((frozen.content_hash, frozen.token_fingerprint) == (content_hash, fingerprint),
                               "historical source fingerprint or frozen grouping differs")
            recomputed[profile][key] = (frozen if frozen.token_fingerprint == fingerprint
                                       else replace(frozen, token_fingerprint=fingerprint))
        _reviewed_need(record["split_example"] == frozen.to_dict()
                       and record["assignment"] == assignments[key],
                       "historical source fingerprint or frozen grouping differs")
        records[key] = record
    _reviewed_need(set(records) == set(examples), "unsupported_historical_source_replay")
    if parent_history is not None:
        for old in parent_history["records"]:
            _reviewed_need(records.get(old["id"]) == old, "parent raw history omitted or changed")
    for row in rows:
        _reviewed_need(row["id"] in records and records[row["id"]]["source_text"] == row["source_text"],
                       "successor source differs from full historical guard")
    frozen_union = split_owner.LegalIRSplitManifest(
        examples=tuple(examples.values()), assignments=assignments, config_digest=cfg.digest,
        protected_splits=cfg.protected_splits, assignment_conflicts=assignment_conflicts,
        metadata={"guard_only": True, "assignments_recomputed": False, "duplicate_view": "frozen"})
    views = [frozen_union]
    for profile, members in recomputed.items():
        # Every row participates in each selected feature space before comparison.
        clusters = split_owner._near_duplicate_clusters([members[key] for key in examples],
                                                        cfg.near_duplicate_jaccard_threshold)
        views.append(split_owner.LegalIRSplitManifest(
            examples=tuple(members[key].with_near_duplicate_key(clusters[key]) for key in examples),
            assignments=assignments, config_digest=cfg.digest, protected_splits=cfg.protected_splits,
            assignment_conflicts=assignment_conflicts,
            metadata={"guard_only": True, "assignments_recomputed": False,
                      "duplicate_view": "recomputed_unicode" if profile else "recomputed"}))
    # Recomputed token relations add a check; they cannot replace committed
    # duplicate groups or assignment conflicts. Keep only actual violations
    # returned by the canonical guards, in the canonical result type.
    results = tuple(split_owner.validate_legal_ir_eval_splits(view) for view in views)
    violations = {_reviewed_wire(item.to_dict()): item
                  for guard in results for item in guard.violations}
    result = split_owner.LegalIRSplitGuardResult(
        passed=all(guard.passed for guard in results),
        violations=tuple(violations[key] for key in sorted(violations)),
        blocked_operations=tuple(sorted({operation for guard in results for operation in guard.blocked_operations})))
    if not withdrawal:
        if not result.passed:
            raise split_owner.LegalIRSplitLeakageError("LegalIR split leakage blocks reviewed-cycle positive use", result)
        for view in views:
            split_owner.authorize_legal_ir_split_use(view, operation="training",
                                                   items=[{"sample_id": row["id"]} for row in rows])
    observation = {"schema": "reviewed-cycle-history-guard-observation/v1",
                   "status": "passed" if result.passed else "violations",
                   "result": result.to_dict(), "positive_use_authorized": False}
    return dict(value, split_manifests=manifests), records, observation


def _reviewed_transition(value, parent_rows, rows, records, parent_records, registry):
    _reviewed_closed(value, {"schema", "retained", "added", "corrected", "superseded", "revoked"},
                     "classified reviewed transition")
    _reviewed_need(value["schema"] == "reviewed-example-cycle-transition/v1", "reviewed transition schema required")
    previous, successor = {row["id"]: row for row in parent_rows}, {row["id"]: row for row in rows}
    old_members, new_members = [], []
    for kind in ("retained", "added"):
        ids = value[kind]
        _reviewed_need(type(ids) is list and all(type(key) is str for key in ids)
                       and len(ids) == len(set(ids)), "ordered unique transition IDs required")
    for key in value["retained"]:
        _reviewed_need(key in previous and key in successor and previous[key] == successor[key]
                       and parent_records[key]["assignment"] == records[key]["assignment"],
                       "retained source, target, unit or split changed")
        old_members.append(key)
        new_members.append(key)
    new_members.extend(value["added"])
    for kind in ("corrected", "superseded", "revoked"):
        _reviewed_need(type(value[kind]) is list and len(value[kind]) <= MAX_REVIEWED_CYCLE_ROWS,
                       "bounded classified transition entries required")
        for entry in value[kind]:
            fields = {"parent_id", "reason_ref"} | ({"successor_id"} if kind != "revoked" else set())
            _reviewed_closed(entry, fields, "reviewed replacement/retirement")
            _reviewed_need(type(entry["parent_id"]) is str, "immutable parent row ID required")
            old_members.append(entry["parent_id"])
            _reviewed_read(registry, entry["reason_ref"])  # Byte custody, not legal adjudication.
            if kind != "revoked":
                key = entry["successor_id"]
                _reviewed_need(key is None and kind == "superseded" or type(key) is str,
                               "explicit immutable replacement row ID required")
                if key is not None:
                    _reviewed_need(key != entry["parent_id"] and key not in previous,
                                   "changed examples require new revision row IDs")
                    new_members.append(key)
    _reviewed_need(len(old_members) == len(set(old_members)) and set(old_members) == set(previous)
                   and len(new_members) == len(set(new_members)) and set(new_members) == set(successor),
                   "transition membership must exhaustively partition parent and successor")
    _reviewed_need(not set(value["added"]) & set(previous), "existing row ID cannot become a new example")


def _reviewed_restore_admission(registry, transport):
    _reviewed_closed(transport, {"schema", "skeleton", "byte_leaves", "admission_inputs_sha256"},
                     "byte-preserving admission transport")
    _reviewed_need(transport["schema"] == "reviewed-cycle-admission-input-transport/v2"
                   and type(transport["byte_leaves"]) is list, "exact admission transport required")
    result, paths = _reviewed_copy(transport["skeleton"]), []
    for leaf in transport["byte_leaves"]:
        _reviewed_need(type(leaf) is dict and type(leaf.get("kind")) is str
                       and leaf["kind"] in {"artifact_bytes", "empty_bytes"},
                       "discriminated admission byte leaf required")
        if leaf["kind"] == "empty_bytes":
            _reviewed_closed(leaf, {"path", "kind", "bytes", "sha256"}, "exact empty bytes marker")
            _reviewed_need(type(leaf["bytes"]) is int and leaf["bytes"] == 0
                           and leaf["sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                           "exact empty byte length and SHA256 required")
            raw = b""
        else:
            _reviewed_closed(leaf, {"path", "kind", "artifact"}, "nonempty admission byte leaf")
            _reviewed_need(_reviewed_ref(leaf["artifact"])["bytes"] > 0, "empty bytes require the exact typed marker")
            raw = _reviewed_read(registry, leaf["artifact"])
        path = leaf["path"]
        _reviewed_need(type(path) is list and all(type(part) in (str, int) for part in path),
                       "typed admission byte path required")
        _reviewed_need(not any(path[:len(old)] == old or old[:len(path)] == path for old in paths),
                       "duplicate or overlapping admission byte paths")
        paths.append(path)
        if not path:
            _reviewed_need(result is None, "byte root placeholder differs")
            result = raw
            continue
        node = result
        for part in path[:-1]:
            _reviewed_need(type(node) is dict and type(part) is str and part in node
                           or type(node) is list and type(part) is int and 0 <= part < len(node),
                           "admission byte path is unused or invalid")
            node = node[part]
        final = path[-1]
        _reviewed_need(type(node) is dict and type(final) is str and final in node
                       or type(node) is list and type(final) is int and 0 <= final < len(node),
                       "admission byte path is unused or invalid")
        _reviewed_need(node[final] is None, "admission byte placeholder differs")
        node[final] = raw
    from ...optimizers.logic_theorem_optimizer.legal_span_consumer_binding import reviewed_admission_inputs_sha256
    _reviewed_need(reviewed_admission_inputs_sha256(result) == transport["admission_inputs_sha256"],
                   "restored type-separated admission commitment differs")
    return result


def _reviewed_withdrawal(value, expected_sha256, parent_ref, transition, history_sha, lineage, *, transition_sha=None, lineage_sha=None):
    from datetime import datetime, timedelta
    import hashlib
    _reviewed_need(value is not None and expected_sha256 is not None,
                   "independent explicit withdrawal provenance required")
    value = _reviewed_copy(value, expected_sha256)
    _reviewed_closed(value, {"schema", "parent_artifact_sha256", "transition_sha256", "history_sha256",
                     "checkpoint_lineage_sha256", "reason_refs", "declared_at_utc", "authority_kind"},
                     "operator-declared withdrawal provenance")
    transition_sha = transition_sha or hashlib.sha256(_reviewed_wire(transition)).hexdigest()
    lineage_sha = lineage_sha or hashlib.sha256(_reviewed_wire(lineage)).hexdigest()
    reasons = {_reviewed_wire(entry["reason_ref"]): entry["reason_ref"]
               for kind in ("superseded", "revoked") for entry in transition[kind]}
    _reviewed_need(value["schema"] == "reviewed-cycle-withdrawal-provenance/v1"
                   and value["authority_kind"] == "operator_declared_retirement_only"
                   and value["parent_artifact_sha256"] == parent_ref["sha256"]
                   and value["transition_sha256"] == transition_sha
                   and value["history_sha256"] == history_sha
                   and value["checkpoint_lineage_sha256"] == lineage_sha
                   and value["reason_refs"] == [reasons[key] for key in sorted(reasons)],
                   "withdrawal provenance or exhaustive retirement reasons differ")
    stamp = value["declared_at_utc"]
    _reviewed_need(type(stamp) is str and 0 < len(stamp) <= 64, "issuer-declared UTC timestamp required")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("issuer-declared UTC timestamp required") from error
    _reviewed_need(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0),
                   "issuer-declared UTC timestamp required")
    return value


def _reviewed_na_consumer():
    return {"schema": "reviewed-cycle-consumer-not-applicable/v1", "status": "not_applicable",
            "reason": "withdrawal_has_zero_active_successor_rows", "active_row_count": 0,
            "positive_consumer_called": False, "semantic_admission_replayed": False}


def _reviewed_cycle_format(artifact, *, admission_version="v2"):
    if admission_version == "v3":
        return ((artifact["schema"], artifact["profile"]) == (REVIEWED_MIXED_CYCLE_SCHEMA, REVIEWED_MIXED_CYCLE_PROFILE)
                and artifact.get("admission_profile") == REVIEWED_MIXED_ADMISSION_PROFILE
                and artifact["compatibility"] == _REVIEWED_COMPATIBILITY)
    _reviewed_need(admission_version == "v2", "unsupported explicit reviewed admission contract")
    return (artifact["schema"], artifact["profile"]) in (
        (REVIEWED_CYCLE_SCHEMA, REVIEWED_CYCLE_PROFILE),
        (REVIEWED_COMPONENT_CYCLE_SCHEMA, REVIEWED_COMPONENT_CYCLE_PROFILE),
    ) and artifact["compatibility"] == _REVIEWED_COMPATIBILITY


def _reviewed_component_id(admission_inputs):
    value = admission_inputs
    for field in ("preparation", "subject", "graph_id"):
        _reviewed_need(type(value) is dict and field in value, "complete reviewed component identity required")
        value = value[field]
    _reviewed_need(type(value) is str and bool(value), "complete reviewed component identity required")
    return value


def _reviewed_component_groups(components, bindings, admissions, rows, exposure, consumer):
    _reviewed_need(type(components) is list and 0 < len(components) <= len(rows)
                   and type(bindings) is dict and type(admissions) is dict,
                   "explicit per-component rows, bindings and current admission inputs required")
    _reviewed_need(type(exposure) is list and len(exposure) == len(rows),
                   "complete ordered component exposure population required")
    row_ids = [row["id"] for row in rows]
    _reviewed_need(len(set(row_ids)) == len(rows), "unique component transition row IDs required")
    positions = {key: index for index, key in enumerate(row_ids)}
    assigned, groups = {}, {}
    for component in components:
        _reviewed_closed(component, {"component_id", "row_ids", "admission_inputs_sha256"},
                         "component row membership")
        identity, members = component["component_id"], component["row_ids"]
        _reviewed_need(type(identity) is str and identity in bindings and identity in admissions
                       and identity not in groups, "unique complete reviewed component identity required")
        _reviewed_need(type(members) is list and members and all(
            type(key) is str and key in positions and key not in assigned for key in members)
            and len(set(members)) == len(members), "disjoint reviewed component rows required")
        indices = [positions[key] for key in members]
        _reviewed_need(indices == sorted(indices), "component rows must retain the successor order")
        admitted = admissions[identity]
        _reviewed_sha(component["admission_inputs_sha256"])
        _reviewed_need(consumer.reviewed_admission_inputs_sha256(admitted) == component["admission_inputs_sha256"]
                       and _reviewed_component_id(admitted) == identity,
                       "component identity or independent current admission commitment differs")
        assigned.update(dict.fromkeys(members, identity))
        groups[identity] = (bindings[identity], [rows[i] for i in indices], [exposure[i] for i in indices])
    _reviewed_need(set(assigned) == set(positions) and set(groups) == set(bindings) == set(admissions),
                   "component membership must exhaust the exact successor population")
    return assigned, groups


def _reviewed_component_parent_memberships(receipts, rows, consumer, *, admission_version="v2"):
    import hashlib

    admission_contract = _reviewed_cycle_contract(admission_version)
    _reviewed_closed(receipts, {"schema", "row_count", "components"}, "historical component receipts")
    _reviewed_need(receipts["schema"] == admission_contract["aggregate_schema"]
                   and receipts["row_count"] == len(rows) and type(receipts["components"]) is list,
                   "complete historical component receipt population required")
    memberships, identities = {}, set()
    by_id = {row["id"]: row for row in rows}
    for component in receipts["components"]:
        _reviewed_closed(component, {"component_id", "row_ids", "admission_inputs_sha256", "receipt",
                         "component_split_guard"}, "historical component receipt")
        identity, members, receipt = component["component_id"], component["row_ids"], component["receipt"]
        _reviewed_need(type(identity) is str and identity not in identities and type(members) is list and members
                       and type(receipt) is dict and receipt.get("schema") == admission_contract["receipt_schema"]
                       and receipt.get("status") == "ready" and receipt.get("operation") == "training"
                       and receipt.get("row_count") == len(members)
                       and receipt.get("admission_inputs_sha256") == component["admission_inputs_sha256"]
                       and members == [row["id"] for row in receipt["rows"]],
                       "historical per-component binding differs")
        _reviewed_need(all(type(key) is str and key in by_id and key not in memberships for key in members)
                       and len(set(members)) == len(members), "duplicate or foreign historical component rows")
        _reviewed_need(receipt["input_sha256s"]["rows"] == hashlib.sha256(
            _reviewed_wire([by_id[key] for key in members])).hexdigest(), "historical component row bytes differ")
        memberships.update(dict.fromkeys(members, identity))
        identities.add(identity)
    _reviewed_need(set(memberships) == {row["id"] for row in rows},
                   "historical component bindings must exhaust the active parent")
    return memberships


def _reviewed_joint_components(observations, row_count, records, dependencies, *, require=_reviewed_need, admission_version="v2"):
    """Close aggregate source, dependency and frozen-split checks after signed replay."""
    component_receipts, assessments, unit_ids, occurrences = [], {}, set(), set()
    physical_occurrences, norm_intervals = set(), []
    artifact_observations = {}
    pin_observations = {kind: {} for kind in dependencies.PIN_KINDS}
    for component, admitted, receipt, assessment in observations:
        key = component["component_id"]
        # Admission verified each complete manifest and its current observed
        # digests. A joint snapshot must agree wherever those identities meet.
        for artifact_id, digest in admitted["observed_artifact_sha256s"].items():
            require(artifact_observations.setdefault(artifact_id, digest) == digest,
                           "reviewed components have conflicting dependency artifact digests")
        for kind, observations in admitted["observed_pins"].items():
            for pin, digest in observations.items():
                require(pin_observations[kind].setdefault(pin, digest) == digest,
                               "reviewed components have conflicting dependency pin digests")
        assessed_units = {unit["unit_id"] for unit in assessment["units"]}
        assessed_occurrences = {unit["occurrence_cid"] for unit in assessment["units"]}
        require(not unit_ids & assessed_units and not occurrences & assessed_occurrences,
                       "reviewed components have overlapping unit or occurrence identities")
        unit_ids.update(assessed_units)
        occurrences.update(assessed_occurrences)
        # Admission replay verified the raw source, extracted view and span for
        # every unit. Check those physical coordinates across the entire batch,
        # including unselected units that may govern active rows.
        for unit in admitted["preparation"]["declaration"]["units"]:
            version, occurrence = unit["source_version"], unit["occurrence"]
            interval = (version["raw_artifact"]["sha256"], version["extracted_view"]["sha256"],
                        occurrence["start_char"], occurrence["end_char"])
            require(interval not in physical_occurrences,
                           "two interpretations of one physical occurrence are not distinct units")
            physical_occurrences.add(interval)
            if unit["kind"] == "norm":
                norm_intervals.append(interval)
        component_receipts.append(dict(component, receipt=receipt,
            component_split_guard=_reviewed_decoder_component_split_guard(assessment, records)))
        assessments[key] = assessment
    norm_intervals.sort()
    require(all(left[:2] != right[:2] or left[3] <= right[2]
                       for left, right in zip(norm_intervals, norm_intervals[1:])),
                   "overlapping interpretations are not two distinct normative uses")
    require(not any(pin_observations[kind] for kind in ("source", "revision", "definition")),
                   "unsupported dependency pin source/frozen-split mapping in reviewed components")
    return {"schema": _reviewed_cycle_contract(admission_version)["aggregate_schema"], "row_count": row_count,
            "components": component_receipts}, assessments


def stage_reviewed_cycle_inputs(registry, *, transition_kind, parent_artifact, expected_parent_sha256,
        successor_rows, expected_successor_rows_sha256, successor_binding, split_manifest,
        admission_inputs, exposure_records, transition, expected_transition_sha256,
        history, expected_history_sha256, split_config, expected_split_config_sha256,
        checkpoint_lineage, expected_checkpoint_lineage_sha256, output_directory, allow_bootstrap=False,
        withdrawal_provenance=None, expected_withdrawal_provenance_sha256=None,
        successor_components=None, expected_successor_components_sha256=None):
    """Legacy public contract, fixed to reviewed admission V2."""
    return _stage_reviewed_cycle_inputs(registry, _admission_version="v2",
        transition_kind=transition_kind,
        parent_artifact=parent_artifact,
        expected_parent_sha256=expected_parent_sha256,
        successor_rows=successor_rows,
        expected_successor_rows_sha256=expected_successor_rows_sha256,
        successor_binding=successor_binding,
        split_manifest=split_manifest,
        admission_inputs=admission_inputs,
        exposure_records=exposure_records,
        transition=transition,
        expected_transition_sha256=expected_transition_sha256,
        history=history,
        expected_history_sha256=expected_history_sha256,
        split_config=split_config,
        expected_split_config_sha256=expected_split_config_sha256,
        checkpoint_lineage=checkpoint_lineage,
        expected_checkpoint_lineage_sha256=expected_checkpoint_lineage_sha256,
        output_directory=output_directory,
        allow_bootstrap=allow_bootstrap,
        withdrawal_provenance=withdrawal_provenance,
        expected_withdrawal_provenance_sha256=expected_withdrawal_provenance_sha256,
        successor_components=successor_components,
        expected_successor_components_sha256=expected_successor_components_sha256,
    )


def stage_reviewed_mixed_cycle_inputs_v4(registry, *, admission_profile, **kwargs):
    """Explicit homogeneous admission V3 staging; legacy lineage is refused."""
    _reviewed_need(type(admission_profile) is str and admission_profile == REVIEWED_MIXED_ADMISSION_PROFILE,
                   "explicit mixed-sort admission V3 profile required")
    return _stage_reviewed_cycle_inputs(registry, _admission_version="v3", **kwargs)


def _stage_reviewed_cycle_inputs(registry, *, transition_kind, parent_artifact, expected_parent_sha256,
        successor_rows, expected_successor_rows_sha256, successor_binding, split_manifest,
        admission_inputs, exposure_records, transition, expected_transition_sha256,
        history, expected_history_sha256, split_config, expected_split_config_sha256,
        checkpoint_lineage, expected_checkpoint_lineage_sha256, output_directory, allow_bootstrap=False,
        withdrawal_provenance=None, expected_withdrawal_provenance_sha256=None,
        successor_components=None, expected_successor_components_sha256=None, _admission_version="v2"):
    """Stage a reviewed typed-example transition through the real v2 consumer.

    The returned ArtifactRef identifies provenance/library metadata, never a
    TrainingJobSpec or model-input export. Whole assessments, byte evidence and
    held-out historical sources are separate artifacts, not training callback
    inputs. Their visibility is no claim that arbitrary readers are exposure-safe.
    The caller supplies independent source/trust/history/artifact identities;
    this function does not authenticate their issuer or global completeness.
    Explicit successor_components select v3 metadata staging. Each entry pins a
    component's ordered row IDs and current admission inputs. In this profile,
    successor_binding and admission_inputs are keyed by the same component IDs.
    Every component retains its own v2 receipt and split guard.
    Positive v3 descendants require explicit component membership, including
    after a withdrawal. A withdrawal keeps the lineage's version and zero rows.
    """
    # These commitments are mandatory even though _reviewed_copy also supports
    # deliberate unpinned internal copies. Validate before operation imports,
    # admission replay, parent reads or any staging side effect.
    for expected in (expected_successor_rows_sha256, expected_transition_sha256,
                     expected_history_sha256, expected_split_config_sha256,
                     expected_checkpoint_lineage_sha256):
        _reviewed_sha(expected)
    import hashlib
    from pathlib import Path
    import sys
    from ...optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    from ...optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    from . import legal_graph_dependencies as dependencies
    admission_contract = _reviewed_cycle_contract(_admission_version)
    admission = admission_contract["admission"]

    _reviewed_need(type(allow_bootstrap) is bool and type(transition_kind) is str
                   and transition_kind in {"bootstrap", "successor", "withdrawal"},
                   "explicit reviewed transition kind required")
    withdrawal = transition_kind == "withdrawal"
    multiple = successor_components is not None
    _reviewed_need(_admission_version != "v3" or withdrawal or multiple,
                   "mixed admission cycle requires explicit complete component membership")
    _reviewed_need(not withdrawal or not multiple, "withdrawal cannot carry active components")
    if multiple:
        _reviewed_sha(expected_successor_components_sha256)
    else:
        _reviewed_need(expected_successor_components_sha256 is None, "unexpected component membership commitment")
    _reviewed_need(type(successor_rows) is list, "complete successor row list required")
    if withdrawal:
        _reviewed_need(successor_rows == [] and successor_binding is None
                       and admission_inputs is None and exposure_records is None,
                       "withdrawal requires zero active rows and explicit N/A consumer/admission inputs")
    else:
        _reviewed_need(bool(successor_rows), "unsupported_empty_successor_consumer")
        _reviewed_need(withdrawal_provenance is None and expected_withdrawal_provenance_sha256 is None,
                       "positive staging cannot carry withdrawal provenance")
    _reviewed_need(len(successor_rows) <= MAX_REVIEWED_CYCLE_ROWS,
                   "one through 128 active successor rows required")
    parent_reference = _reviewed_copy(parent_artifact)
    rows = _reviewed_copy(successor_rows, expected_successor_rows_sha256)
    components = _reviewed_copy(successor_components, expected_successor_components_sha256)
    changes = _reviewed_copy(transition, expected_transition_sha256)
    history_copy = _reviewed_copy(history, expected_history_sha256)
    config = _reviewed_copy(split_config, expected_split_config_sha256)
    lineage = _reviewed_copy(checkpoint_lineage, expected_checkpoint_lineage_sha256)
    manifest, exposure = _reviewed_copy(split_manifest), _reviewed_copy(exposure_records)
    original_json_inputs = (successor_rows, split_manifest, exposure_records, transition, history,
                            split_config, checkpoint_lineage, parent_artifact, withdrawal_provenance,
                            successor_components)
    frozen_json_inputs = tuple(_reviewed_wire(value) for value in original_json_inputs)
    if multiple:
        admission_snapshot, admission_sha = consumer._reviewed_snapshot(admission_inputs)
    else:
        admission_snapshot = admission_inputs
        admission_sha = None if withdrawal else consumer.reviewed_admission_inputs_sha256(admission_inputs)
    memberships, groups = ({}, {})
    if multiple:
        memberships, groups = _reviewed_component_groups(
            components, successor_binding, admission_snapshot, rows, exposure, consumer)
    _reviewed_lineage(lineage)
    parent, parent_rows, previous_history, parent_records = None, [], None, {}
    parent_components = None
    parent_is_v3 = False
    if transition_kind == "bootstrap":
        _reviewed_need(allow_bootstrap and parent_artifact is None and expected_parent_sha256 is None,
                       "explicit bootstrap opt-in, null parent and null parent commitment required")
        _reviewed_need(history_copy.get("parent_history_artifact") is None,
                       "bootstrap cannot silently replace prior history")
    else:
        _reviewed_need(parent_artifact is not None and expected_parent_sha256 is not None,
                       "successor requires an exact historical parent artifact")
        _reviewed_sha(expected_parent_sha256)
        _reviewed_need(_reviewed_ref(parent_artifact)["sha256"] == expected_parent_sha256,
                       "independent parent artifact identity differs")
        parent = _reviewed_json(_reviewed_read(registry, parent_artifact))
        _reviewed_closed(parent, _reviewed_cycle_fields(_admission_version), "reviewed cycle parent artifact")
        _reviewed_need(_reviewed_cycle_format(parent, admission_version=_admission_version),
                       "legacy or numerical snapshots cannot supply a reviewed cycle parent")
        parent_is_v3 = parent["schema"] in {REVIEWED_COMPONENT_CYCLE_SCHEMA, REVIEWED_MIXED_CYCLE_SCHEMA}
        _reviewed_need(not parent_is_v3 or withdrawal or multiple,
                       "positive descendants of a component cycle require explicit component membership")
        parent_rows = _reviewed_json(_reviewed_read(registry, parent["rows_artifact"]))
        _reviewed_need(type(parent_rows) is list and len(parent_rows) <= MAX_REVIEWED_CYCLE_ROWS,
                       "bounded complete historical active row population required")
        for row in parent_rows:
            _reviewed_closed(row, {"id", "unit_id", "source_text", "canonical_ir"}, "historical typed row")
            _reviewed_need(type(row["id"]) is str, "historical row ID must be a string")
        _reviewed_need(len({row["id"] for row in parent_rows}) == len(parent_rows),
                       "unique historical active IDs required")
        previous_history = _reviewed_json(_reviewed_read(registry, parent["history_artifact"]))
        _reviewed_closed(previous_history, {"schema", "scope_id", "scope_kind", "split_manifests",
                         "records", "parent_history_artifact"}, "historical parent guard")
        _reviewed_need(previous_history["schema"] == "reviewed-example-cycle-history/v1"
                       and type(previous_history["records"]) is list
                       and len(previous_history["records"]) <= MAX_REVIEWED_HISTORY
                       and type(previous_history["split_manifests"]) is list
                       and len(previous_history["split_manifests"]) <= MAX_REVIEWED_HISTORY
                       and history_copy.get("parent_history_artifact") == parent["history_artifact"],
                       "exact parent guard history reference required")
        parent_manifest = _reviewed_json(_reviewed_read(registry, parent["split_manifest_artifact"]))
        _reviewed_closed(parent["history_guard"], {"schema", "status", "result", "positive_use_authorized"},
                         "historical actual guard observation")
        _reviewed_need(parent["history_guard"]["schema"] == "reviewed-cycle-history-guard-observation/v1"
                       and parent["history_guard"]["positive_use_authorized"] is False
                       and type(parent["history_guard"]["result"]) is dict
                       and type(parent["history_guard"]["result"].get("passed")) is bool
                       and parent["history_guard"]["status"] == (
                           "passed" if parent["history_guard"]["result"]["passed"] else "violations"),
                       "historical guard cannot grant positive use")
        if parent["transition_kind"] == "withdrawal":
            _reviewed_need(not parent_rows and parent["consumer_receipt"] == _reviewed_na_consumer()
                           and parent["admission_assessment_artifact"] is None
                           and parent["admission_transport_artifact"] is None,
                           "empty parent must be an explicit non-positive withdrawal")
            _reviewed_withdrawal(parent["withdrawal_provenance"],
                hashlib.sha256(_reviewed_wire(parent["withdrawal_provenance"])).hexdigest(),
                parent["parent_artifact"], parent["transition"],
                hashlib.sha256(_reviewed_wire(previous_history)).hexdigest(), parent["checkpoint_lineage"])
            prior = _reviewed_json(_reviewed_read(registry, parent["parent_artifact"]))
            _reviewed_closed(prior, _reviewed_cycle_fields(_admission_version), "withdrawal predecessor")
            prior_rows = _reviewed_json(_reviewed_read(registry, prior["rows_artifact"]))
            _reviewed_need(_reviewed_cycle_format(prior, admission_version=_admission_version)
                           and parent_is_v3 == (prior["schema"] in {REVIEWED_COMPONENT_CYCLE_SCHEMA, REVIEWED_MIXED_CYCLE_SCHEMA})
                           and prior["transition_kind"] in {"bootstrap", "successor"}
                           and type(prior_rows) is list and 0 < len(prior_rows) <= MAX_REVIEWED_CYCLE_ROWS
                           and parent["checkpoint_lineage"] == prior["checkpoint_lineage"]
                           and parent_manifest == _reviewed_json(_reviewed_read(registry, prior["split_manifest_artifact"])),
                           "withdrawal predecessor content or lineage differs")
            _reviewed_need(not any(parent["transition"][key] for key in ("retained", "added", "corrected")),
                           "historical withdrawal cannot contain positive transitions")
            _reviewed_transition(parent["transition"], prior_rows, [], {}, {}, registry)
        else:
            _reviewed_need(parent["transition_kind"] in {"bootstrap", "successor"} and bool(parent_rows)
                           and parent["withdrawal_provenance"] is None
                           and parent["history_guard"]["status"] == "passed"
                           and parent["history_guard"]["result"].get("passed") is True,
                           "historical positive parent must retain its actual ready profile")
            prior_receipt = parent["consumer_receipt"]
            if parent_is_v3:
                parent_components = _reviewed_component_parent_memberships(prior_receipt, parent_rows, consumer, admission_version=_admission_version)
            else:
                _reviewed_need(prior_receipt.get("schema") == consumer.REVIEWED_SCHEMA
                               and prior_receipt.get("status") == "ready"
                               and prior_receipt.get("operation") == "training"
                               and prior_receipt.get("row_count") == len(parent_rows)
                               and prior_receipt.get("input_sha256s", {}).get("rows") == parent["rows_artifact"]["sha256"],
                               "historical positive parent must retain its actual ready profile")
                if multiple and changes["retained"]:
                    prior_transport = _reviewed_json(_reviewed_read(registry, parent["admission_transport_artifact"]))
                    _reviewed_need(prior_transport["admission_inputs_sha256"] == prior_receipt["admission_inputs_sha256"],
                                   "historical component admission transport differs")
                    prior_identity = _reviewed_component_id(prior_transport["skeleton"])
                    parent_components = dict.fromkeys((row["id"] for row in parent_rows), prior_identity)
            _reviewed_ref(parent["admission_assessment_artifact"])
            _reviewed_ref(parent["admission_transport_artifact"])
        parent_manifest_sha = hashlib.sha256(_reviewed_wire(parent_manifest)).hexdigest()
        _reviewed_need(any(entry.get("sha256") == parent_manifest_sha
                          and entry.get("manifest") == parent_manifest
                          for entry in previous_history["split_manifests"]),
                       "historical parent split population missing")
        parent_records = {record["id"]: record for record in previous_history["records"]}
        _reviewed_need(len(parent_records) == len(previous_history["records"]), "duplicate parent historical IDs")
        _reviewed_lineage(parent["checkpoint_lineage"])
        _reviewed_need(lineage == parent["checkpoint_lineage"], "declared checkpoint or optimizer lineage changed")
        for row in parent_rows:
            _reviewed_closed(row, {"id", "unit_id", "source_text", "canonical_ir"}, "historical typed row")
            _reviewed_need(row["id"] in parent_records
                           and parent_records[row["id"]]["source_text"] == row["source_text"],
                           "historical active source missing from cumulative guard")

    guard_history, records, history_guard = _reviewed_history(
        history_copy, manifest, rows, config, previous_history, splits, withdrawal=withdrawal)
    _reviewed_transition(changes, parent_rows, rows, records, parent_records, registry)
    if parent_components is not None and changes["retained"]:
        _reviewed_need(all(parent_components[key] == memberships[key] for key in changes["retained"]),
                       "retained rows must keep their independently reviewed component identity")
    withdrawal_record = None
    if withdrawal:
        _reviewed_need(bool(parent_rows) and manifest == parent_manifest
                       and not any(changes[key] for key in ("retained", "added", "corrected")),
                       "withdrawal requires a nonempty parent, its frozen split and retirement-only classification")
        withdrawal_record = _reviewed_withdrawal(withdrawal_provenance, expected_withdrawal_provenance_sha256,
            parent_reference, changes, expected_history_sha256, lineage,
            transition_sha=expected_transition_sha256, lineage_sha=expected_checkpoint_lineage_sha256)
    if transition_kind == "bootstrap":
        _reviewed_need(not any(changes[key] for key in ("retained", "corrected", "superseded", "revoked")),
                       "bootstrap requires added-only classification")
    else:
        # History intentionally carries source/split metadata, not retired target
        # hashes. Never reactivate an old ID with an uncheckable new target.
        retained = set(changes["retained"])
        _reviewed_need(not any(row["id"] in parent_records and row["id"] not in retained for row in rows),
                       "unsupported_historical_id_reactivation")

    byte_values = []
    def skeleton(item, path):
        if type(item) is bytes:
            _reviewed_need(len(item) <= MAX_REVIEWED_ARTIFACT_BYTES, "unsupported_reviewed_artifact_capacity")
            _reviewed_need(len(byte_values) < 4096, "unsupported_admission_byte_leaf_capacity")
            byte_values.append((list(path), item))
            return None
        if type(item) is dict:
            return {key: skeleton(child, path + [key]) for key, child in sorted(item.items())}
        if type(item) is list:
            return [skeleton(child, path + [index]) for index, child in enumerate(item)]
        return item
    admission_skeleton = skeleton(admission_snapshot, [])
    _reviewed_wire(admission_skeleton)
    _reviewed_need(sum(len(raw) for _, raw in byte_values) <= MAX_REVIEWED_STAGE_BYTES,
                   "unsupported_reviewed_staging_capacity")
    directory = Path(output_directory)
    _reviewed_need(directory.is_absolute() and directory.parent.resolve(strict=True) == directory.parent
                   and directory.parent.is_dir() and not directory.exists() and not directory.is_symlink(),
                   "fresh ordinary output directory in existing canonical parent required")

    modules = (sys.modules[__name__], consumer, admission, splits)
    # Mixed V4 retains the dependency owner during an inactive withdrawal:
    # its producer identity belongs to the lineage, not active row presence.
    if multiple or _admission_version == "v3":
        modules += (dependencies,)
    def implementation():
        return {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                for module in modules}
    producers = implementation()
    def verify_binding(binding, selected, exposures, admitted):
        receipt = admission_contract["validate"](binding, selected,
            split_manifest=split_manifest, admission_inputs=admitted, exposure_records=exposures)
        assessment = admission_contract["assess"](**admitted)
        _reviewed_need(receipt["status"] == "ready" and receipt["operation"] == "training"
                       and receipt["row_count"] == len(selected)
                       and receipt["admission_assessment_sha256"] == admission.norm_content_adjudication_sha256(assessment)
                       and assessment["semantic_use_eligible"] is True and not assessment["blockers"],
                       "fresh complete current reviewed admission required")
        return receipt, assessment

    def current():
        _reviewed_need(tuple(_reviewed_wire(value) for value in original_json_inputs) == frozen_json_inputs
                       and (withdrawal or consumer.reviewed_admission_inputs_sha256(admission_inputs) == admission_sha)
                       and implementation() == producers, "reviewed staging inputs or named producers changed")
        if withdrawal:
            return _reviewed_na_consumer(), None
        if not multiple:
            return verify_binding(successor_binding, successor_rows, exposure_records, admission_inputs)
        _reviewed_need(set(successor_binding) == set(groups) and all(
            successor_binding[key] is values[0] for key, values in groups.items()), "component bindings changed")
        def observations():
            for component in components:
                key = component["component_id"]
                binding, selected, exposures = groups[key]
                admitted = admission_snapshot[key]
                yield component, admitted, *verify_binding(binding, selected, exposures, admitted)
        return _reviewed_joint_components(observations(), len(rows), records, dependencies, admission_version=_admission_version)
    receipt, assessment = current()

    def stage(consumed_rows):
        current_receipt, current_assessment = current()
        _reviewed_need(consumed_rows == rows and current_receipt == receipt and current_assessment == assessment,
                       "current consumed rows or complete admission changed before staging")
        directory.mkdir(mode=0o700, exist_ok=False)
        sequence, total = 0, 0
        def put(raw):
            nonlocal sequence, total
            total += len(raw)
            _reviewed_need(type(raw) is bytes and 0 < len(raw) <= MAX_REVIEWED_ARTIFACT_BYTES
                           and total <= MAX_REVIEWED_STAGE_BYTES, "unsupported_reviewed_staging_capacity")
            path = directory / (str(sequence) + ".artifact")
            sequence += 1
            with path.open("xb") as stream:
                stream.write(raw)
            expected = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            stored = registry.stage_artifact(path, expected["sha256"])
            _reviewed_need(stored == expected, "registry staged descriptor differs")
            reference = dict(stored, path=str(registry.artifact_path(stored)))
            _reviewed_need(_reviewed_read(registry, reference) == raw, "staged exact artifact bytes differ")
            return reference
        transport_ref = None
        if not withdrawal:
            leaves = [{"path": path, "kind": "artifact_bytes", "artifact": put(raw)} if raw else
                      {"path": path, "kind": "empty_bytes", "bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}
                      for path, raw in byte_values]
            transport = {"schema": "reviewed-cycle-admission-input-transport/v2", "skeleton": admission_skeleton,
                         "byte_leaves": leaves, "admission_inputs_sha256": admission_sha}
            transport_ref = put(_reviewed_wire(transport))
            restored = _reviewed_restore_admission(registry, _reviewed_json(_reviewed_read(registry, transport_ref)))
            _reviewed_need(consumer.reviewed_admission_inputs_sha256(restored) == admission_sha,
                           "complete raw admission transport differs")
        artifact = {"schema": (REVIEWED_MIXED_CYCLE_SCHEMA if _admission_version == "v3" else
                       REVIEWED_COMPONENT_CYCLE_SCHEMA if multiple or parent_is_v3 else REVIEWED_CYCLE_SCHEMA),
            "profile": (REVIEWED_MIXED_CYCLE_PROFILE if _admission_version == "v3" else
                        REVIEWED_COMPONENT_CYCLE_PROFILE if multiple or parent_is_v3 else REVIEWED_CYCLE_PROFILE),
            "transition_kind": transition_kind, "parent_artifact": parent_reference,
            "rows_artifact": put(_reviewed_wire(consumed_rows)), "consumer_receipt": current_receipt,
            "admission_assessment_artifact": None if withdrawal else put(_reviewed_wire(current_assessment)),
            "admission_transport_artifact": transport_ref, "split_manifest_artifact": put(_reviewed_wire(manifest)),
            "history_artifact": put(_reviewed_wire(guard_history)), "transition": changes,
            "checkpoint_lineage": lineage, "implementation": producers, "compatibility": dict(_REVIEWED_COMPATIBILITY),
            "history_guard": history_guard, "withdrawal_provenance": withdrawal_record}
        if _admission_version == "v3":
            artifact["admission_profile"] = REVIEWED_MIXED_ADMISSION_PROFILE
        _reviewed_need(current() == (receipt, assessment), "reviewed staging state changed after payload writes")
        result = put(_reviewed_wire(artifact))
        _reviewed_need(current() == (receipt, assessment), "reviewed staging state changed after metadata write")
        return result

    if withdrawal or multiple:
        return stage(rows)
    return admission_contract["consume"](successor_binding, successor_rows,
        split_manifest=split_manifest, admission_inputs=admission_inputs,
        exposure_records=exposure_records, consumer=stage)


class ReviewedDecoderInputValidationError(ValueError):
    """Known validation emitted by the appended reviewed-decoder owner.

    Arbitrary tokenizer/registry/admission callback exceptions are not converted
    to this type, and the older staging owner keeps its existing error boundary.
    """


def _reviewed_decoder_need(condition, message):
    if not condition:
        raise ReviewedDecoderInputValidationError(message)


# This input profile is separate from metadata staging and the legacy span/
# embedding codecs. It prepares complete targets; it never restores or fits a
# model, grants execution, or upgrades fictional examples into statutory gold.
# Historical v1 four-key source wires and full-target codec keep their distinct
# names; this v2 preparation does not silently reinterpret or fill those inputs.
REVIEWED_DECODER_INPUT_SCHEMA_V1 = "reviewed-decoder-training-inputs/v1"
REVIEWED_DECODER_INPUT_PROFILE_V1 = "complete-reviewed-decoder-training-inputs/v1"
REVIEWED_DECODER_TARGET_CODEC_V1 = "complete-reviewed-norm-json/v1"
REVIEWED_DECODER_SOURCE_PROFILE_V1 = "reviewed-source-known-context/v1"
REVIEWED_DECODER_INPUT_SCHEMA = "reviewed-decoder-training-inputs/v2"
REVIEWED_DECODER_INPUT_PROFILE = "complete-reviewed-decoder-training-inputs/v2"
REVIEWED_DECODER_TARGET_CODEC = "complete-reviewed-norm-json/v2"
REVIEWED_DECODER_SOURCE_PROFILE = "reviewed-source-selection-context/v2"
REVIEWED_COMPONENT_DECODER_CONTEXT_PROFILE = "reviewed-component-source-selection-context/v1"
REVIEWED_COMPONENT_DECODER_INPUT_SCHEMA = "reviewed-decoder-training-inputs/v3"
REVIEWED_COMPONENT_DECODER_INPUT_PROFILE = "independently-reviewed-component-decoder-training-inputs/v3"
_REVIEWED_DECODER_TARGET_FIELDS = {
    "profile", "typed_expression", "argument_roles", "assumptions", "governing_context",
    "interpretation_id", "source_binding", "definition_uses", "cross_references",
}


def _reviewed_decoder_tokenizer_ids(tokenizer):
    ids = {key: getattr(tokenizer, key, None)
           for key in ("bos_token_id", "eos_token_id", "vocab_size")}
    _reviewed_decoder_need(type(ids["vocab_size"]) is int and 3 <= ids["vocab_size"] <= 2**31,
                   "plain bounded decoder vocabulary size required")
    _reviewed_decoder_need(all(type(ids[key]) is int and 0 <= ids[key] < ids["vocab_size"]
                       for key in ("bos_token_id", "eos_token_id"))
                   and ids["bos_token_id"] != ids["eos_token_id"],
                   "distinct plain decoder BOS and EOS required")
    return ids


def _reviewed_decoder_tokenizer_implementation(implementation):
    """Authenticate serialized live implementation identities, without importing."""
    import hashlib
    import os
    from pathlib import Path
    import stat

    _reviewed_decoder_need(type(implementation) is list and 0 < len(implementation) <= 128,
                   "nonempty bounded tokenizer implementation identities required")
    seen = set()
    for reference in implementation:
        _reviewed_closed(reference, {"path", "bytes", "sha256"}, "actual tokenizer implementation identity")
        _reviewed_sha(reference["sha256"])
        _reviewed_decoder_need(type(reference["path"]) is str and reference["path"] not in seen
                       and type(reference["bytes"]) is int and 0 < reference["bytes"] <= 512 * 1024**2,
                       "unique bounded actual tokenizer implementation file required")
        seen.add(reference["path"])
        path = Path(reference["path"])
        _reviewed_decoder_need(path.is_absolute() and path.resolve(strict=True) == path,
                       "ordinary absolute tokenizer implementation source required")
        _reviewed_decoder_need(all(stat.S_ISDIR(parent.lstat().st_mode) for parent in path.parents),
                       "ordinary tokenizer implementation ancestry required")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            first = os.fstat(stream.fileno())
            _reviewed_decoder_need(stat.S_ISREG(first.st_mode) and first.st_nlink == 1
                           and first.st_size == reference["bytes"],
                           "tokenizer implementation SourceChanged: file identity differs")
            digest, used = hashlib.sha256(), 0
            while block := stream.read(1024**2):
                used += len(block)
                _reviewed_decoder_need(used <= reference["bytes"], "tokenizer implementation SourceChanged: file grew")
                digest.update(block)
            last = os.fstat(stream.fileno())
        stamp = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_uid,
                               value.st_gid, value.st_nlink, value.st_size,
                               value.st_mtime_ns, value.st_ctime_ns)
        _reviewed_decoder_need(used == reference["bytes"] and digest.hexdigest() == reference["sha256"]
                       and stamp(first) == stamp(last) == stamp(path.lstat()),
                       "tokenizer implementation SourceChanged: bytes or source identity changed")


def _reviewed_decoder_fixed_byte_method(method):
    """Bind actual Python code/defaults; captured behavior is not attested.

    Fixture callbacks deliberately retain external mutable aliases for the
    boundary tests. Free-variable names are recorded, not passed off as a
    complete physical/behavioral identity of those external objects.
    """
    import hashlib
    import marshal
    import types
    from ...optimizers.logic_theorem_optimizer.autoencoder_training_worker import _reviewed_tokenizer_configuration

    function = method.__func__ if type(method) is types.MethodType else method
    _reviewed_decoder_need(type(function) is types.FunctionType, "supported actual Python fixed-byte methods required")
    code = function.__code__
    closure = ({"type": "unattested_freevars", "names": list(code.co_freevars)} if code.co_freevars
               else {"type": "tuple", "items": []})
    # Match the reference-independent code encoding used by the producer.
    return {"module": function.__module__, "qualname": function.__qualname__, "kind": "python_code",
        "code_sha256": hashlib.sha256(marshal.dumps(code, 2)).hexdigest(),
        "defaults": _reviewed_tokenizer_configuration(function.__defaults__),
        "keyword_defaults": _reviewed_tokenizer_configuration(function.__kwdefaults__), "closure": closure}


def _reviewed_decoder_fixed_byte_pipeline(tokenizer):
    """Maintained complete fictional emitter; no behavior or asset authority."""
    import hashlib
    from pathlib import Path
    methods = {name: getattr(tokenizer, name) for name in ("encode", "decode", "pipeline_serialization")}
    paths = {str(Path(__file__)), *(str(Path(method.__func__.__code__.co_filename)) for method in methods.values())}
    implementation = []
    for spelling in sorted(paths):
        path = Path(spelling)
        raw = path.read_bytes()
        implementation.append({"path": spelling, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return _reviewed_wire({"schema": "reviewed-decoder-tokenizer-pipeline/v1", "kind": "fictional_fixed_byte",
        "backend": {"type": "fixed_utf8_byte", "byte_to_id": list(tokenizer.byte_to_id), "added_tokens": []},
        "frontend": {"encoding": tokenizer.text_encoding, "errors": "strict",
            "configuration": dict(tokenizer.frontend_config),
            "bos_token_id": tokenizer.bos_token_id, "eos_token_id": tokenizer.eos_token_id,
            "vocab_size": tokenizer.vocab_size,
            "methods": {name: _reviewed_decoder_fixed_byte_method(method) for name, method in methods.items()}},
        "implementation": implementation,
        "transport": {"body_only": True, "truncation": False, "padding": False}})


def _reviewed_decoder_fixed_byte_configuration(tokenizer):
    """Only the declared mapping/options are a supported fictional config.

    observation_state is explicitly non-attested test observation/callback state;
    it cannot confer behavior or production-asset authority. Extra live fields
    must not be silently omitted from the serialized semantic configuration.
    """
    state = getattr(tokenizer, "__dict__", None)
    allowed = {"byte_to_id", "frontend_config", "text_encoding", "observation_state",
               "bos_token_id", "eos_token_id", "vocab_size"}
    class_fields = {"__module__", "__doc__", "__dict__", "__weakref__", "__init__",
                    "encode", "decode", "pipeline_serialization", "byte_token_ids",
                    "bos_token_id", "eos_token_id", "vocab_size"}
    _reviewed_decoder_need(all(set(cls.__dict__) <= class_fields for cls in type(tokenizer).__mro__ if cls is not object),
                   "unsupported unencoded fixed-byte fixture class setting")
    _reviewed_decoder_need(type(state) is dict and set(state) <= allowed,
                   "unsupported unencoded fixed-byte fixture setting")
    mapping = getattr(tokenizer, "byte_to_id", None)
    config = getattr(tokenizer, "frontend_config", None)
    _reviewed_decoder_need(type(mapping) is list and len(mapping) == 256
                   and all(type(value) is int for value in mapping) and len(set(mapping)) == 256,
                   "complete actual unique plain-integer fixed-byte mapping required")
    _reviewed_closed(config, {"normalizer", "cleanup"}, "complete fixed-byte frontend configuration")
    _reviewed_decoder_need(type(config["normalizer"]) is str
                   and config["normalizer"] in {"identity", "lowercase"} and config["cleanup"] is False,
                   "supported explicit fixed-byte normalization/cleanup options required")
    encoding = state.get("text_encoding", "utf-8")
    _reviewed_decoder_need(type(encoding) is str and encoding in {"utf-8", "utf8"},
                   "explicit strict UTF8 fixed-byte encoding required")
    _reviewed_decoder_need("observation_state" not in state or type(state["observation_state"]) is dict,
                   "explicit non-attested fixture observation state required")
    return list(mapping), dict(config), encoding


def _reviewed_decoder_validate_fixed_byte_pipeline(tokenizer, pipeline, ids):
    """Refuse opaque/partial mappings and bind the complete declared config."""
    from pathlib import Path
    from ...optimizers.logic_theorem_optimizer.autoencoder_training_worker import ReviewedPretrainedTokenizer

    frontend = pipeline["frontend"]
    implementation_paths = {row["path"] for row in pipeline["implementation"]
                            if type(row) is dict and type(row.get("path")) is str}
    delegate = tokenizer
    if type(tokenizer) is ReviewedPretrainedTokenizer:
        _reviewed_decoder_need(tokenizer.allow_fictional_fixture is True,
                       "explicit maintained wrapper fixture opt-in required")
        _reviewed_closed(frontend, {"fixture", "wrapper_options", "wrapper_special_ids", "wrapper_methods", "delegate_methods"},
                         "complete maintained fixed-byte wrapper configuration")
        _reviewed_decoder_need(frontend["wrapper_options"] == {
            "encode": {"add_special_tokens": False, "truncation": False, "padding": False},
            "decode": {"skip_special_tokens": False, "clean_up_tokenization_spaces": False}}
            and frontend["wrapper_special_ids"] == ids,
            "maintained fixed-byte wrapper transport or special IDs differ")
        _reviewed_decoder_need(frontend["wrapper_methods"] == {name: _reviewed_decoder_fixed_byte_method(getattr(tokenizer, name))
                       for name in ("encode", "decode", "pipeline_serialization", "binding_metadata", "_fast_backend")},
                       "actual maintained fixture wrapper method identity differs")
        delegate = tokenizer.tokenizer
        _reviewed_decoder_need(frontend["delegate_methods"] == {name: _reviewed_decoder_fixed_byte_method(getattr(delegate, name))
                       for name in ("encode", "decode", "pipeline_serialization")},
                       "actual fixed-byte delegate method identity differs")
        frontend = frontend["fixture"]
    backend = pipeline["backend"]
    _reviewed_closed(backend, {"type", "byte_to_id", "added_tokens"}, "complete fixed-byte backend")
    mapping = backend["byte_to_id"]
    _reviewed_decoder_need(backend["type"] == "fixed_utf8_byte" and backend["added_tokens"] == []
                   and type(mapping) is list and len(mapping) == 256
                   and all(type(value) is int and 0 <= value < ids["vocab_size"]
                           and value not in (ids["bos_token_id"], ids["eos_token_id"]) for value in mapping)
                   and len(set(mapping)) == 256,
                   "complete unique in-range fixed-byte mapping excluding BOS/EOS required")
    _reviewed_closed(frontend, {"encoding", "errors", "configuration", "bos_token_id", "eos_token_id", "vocab_size", "methods"},
                     "complete fixed-byte frontend/options/method configuration")
    live_mapping, live_config, encoding = _reviewed_decoder_fixed_byte_configuration(delegate)
    _reviewed_decoder_need(mapping == live_mapping and frontend["configuration"] == live_config
                   and frontend["encoding"] == encoding and frontend["errors"] == "strict"
                   and all(type(frontend[key]) is int for key in ("bos_token_id", "eos_token_id", "vocab_size"))
                   and {key: frontend[key] for key in ("bos_token_id", "eos_token_id", "vocab_size")} == ids
                   and _reviewed_decoder_tokenizer_ids(delegate) == ids,
                   "serialized fixed-byte mapping/options differ from actual declared fixture config")
    methods = {name: getattr(delegate, name) for name in ("encode", "decode", "pipeline_serialization")}
    _reviewed_decoder_need(frontend["methods"] == {name: _reviewed_decoder_fixed_byte_method(method) for name, method in methods.items()},
                   "serialized fixed-byte method identity differs from actual code/defaults")
    for method in methods.values():
        path = str(Path(method.__func__.__code__.co_filename))
        _reviewed_decoder_need(path in implementation_paths, "actual fixed-byte method source is missing from implementation pins")


import threading as _reviewed_decoder_pipeline_cache_threading

# Pure bytes-to-structure memoization only. Neither live serialization nor any
# implementation-file authentication is cached. Values contain no mutable JSON.
_REVIEWED_DECODER_HF_PIPELINE_SUMMARY_CACHE = {}
_REVIEWED_DECODER_HF_PIPELINE_SUMMARY_LOCK = _reviewed_decoder_pipeline_cache_threading.Lock()
_REVIEWED_DECODER_HF_PIPELINE_SUMMARY_MAX_ENTRIES = 2
_REVIEWED_DECODER_HF_PIPELINE_SUMMARY_MAX_RAW_BYTES = 16 * 1024**2

def _reviewed_decoder_hf_pipeline_summary(raw):
    """Reuse only pure parsing of identical maintained production bytes.

    The caller freshly serializes its actual tokenizer and reauthenticates all
    implementation files on every call. Oversized otherwise-valid bytes and
    fixed-byte pipelines keep their ordinary validation path.
    """
    import hashlib
    eligible = type(raw) is bytes and len(raw) <= _REVIEWED_DECODER_HF_PIPELINE_SUMMARY_MAX_RAW_BYTES
    if eligible:
        with _REVIEWED_DECODER_HF_PIPELINE_SUMMARY_LOCK:
            cached = _REVIEWED_DECODER_HF_PIPELINE_SUMMARY_CACHE.get(raw)
        if cached is not None:
            return cached, None
    pipeline = _reviewed_json(raw)
    if type(pipeline) is not dict or pipeline.get("kind") != "huggingface_fast":
        return None, pipeline
    _reviewed_closed(pipeline, {"schema", "kind", "backend", "frontend", "implementation", "transport"},
                     "complete actual tokenizer pipeline")
    _reviewed_decoder_need(pipeline["schema"] == "reviewed-decoder-tokenizer-pipeline/v1"
                   and pipeline["kind"] in {"huggingface_fast", "fictional_fixed_byte"}
                   and type(pipeline["backend"]) is dict and bool(pipeline["backend"])
                   and type(pipeline["frontend"]) is dict and bool(pipeline["frontend"]),
                   "supported complete tokenizer pipeline with actual backend/frontend required")
    _reviewed_closed(pipeline["transport"], {"body_only", "truncation", "padding"},
                     "explicit tokenizer transport configuration")
    _reviewed_decoder_need(pipeline["transport"]["body_only"] is True
                   and pipeline["transport"]["truncation"] is False
                   and pipeline["transport"]["padding"] is False,
                   "body-only tokenizer transport without truncation or padding required")
    summary = (pipeline["kind"], _reviewed_wire(pipeline["implementation"]),
               hashlib.sha256(raw).hexdigest(), len(raw))
    if eligible:
        with _REVIEWED_DECODER_HF_PIPELINE_SUMMARY_LOCK:
            _REVIEWED_DECODER_HF_PIPELINE_SUMMARY_CACHE[raw] = summary
            while len(_REVIEWED_DECODER_HF_PIPELINE_SUMMARY_CACHE) > _REVIEWED_DECODER_HF_PIPELINE_SUMMARY_MAX_ENTRIES:
                del _REVIEWED_DECODER_HF_PIPELINE_SUMMARY_CACHE[next(iter(_REVIEWED_DECODER_HF_PIPELINE_SUMMARY_CACHE))]
    return summary, None

def _reviewed_decoder_tokenizer_contract(tokenizer):
    """Derive identity from the complete live pipeline, never an opaque label.

    This helper supplies identity only. The preparation owner additionally gates
    fictional transports against the fresh actual admission and explicit opt-in.
    """
    import hashlib

    ids = _reviewed_decoder_tokenizer_ids(tokenizer)
    _reviewed_decoder_need(callable(getattr(tokenizer, "encode", None))
                   and callable(getattr(tokenizer, "decode", None))
                   and callable(getattr(tokenizer, "pipeline_serialization", None)),
                   "explicit lossless tokenizer pipeline_serialization protocol required")
    from ...optimizers.logic_theorem_optimizer.autoencoder_training_worker import ReviewedPretrainedTokenizer
    if type(tokenizer) is ReviewedPretrainedTokenizer:
        # Use the maintained class entry, whose own first guard refuses all
        # instance method shadows before touching a backend or delegate getter.
        raw = ReviewedPretrainedTokenizer.pipeline_serialization(tokenizer)
    else:
        raw = tokenizer.pipeline_serialization()
    _reviewed_decoder_need(_reviewed_decoder_tokenizer_ids(tokenizer) == ids,
                   "decoder tokenizer IDs changed during pipeline serialization")
    _reviewed_decoder_need(type(raw) is bytes and 0 < len(raw) <= MAX_REVIEWED_ARTIFACT_BYTES,
                   "bounded complete canonical tokenizer pipeline bytes required")
    if type(tokenizer) is ReviewedPretrainedTokenizer:
        summary, pipeline = _reviewed_decoder_hf_pipeline_summary(raw)
        if summary is not None:
            _reviewed_decoder_need(type(tokenizer) is ReviewedPretrainedTokenizer,
                           "exact maintained ReviewedPretrainedTokenizer required for production pipeline")
            # Decode a fresh small inventory and authenticate every actual file;
            # unchanged metadata never substitutes for a fresh content read.
            implementation = _reviewed_json(summary[1])
            _reviewed_decoder_tokenizer_implementation(implementation)
            _reviewed_decoder_need(_reviewed_decoder_tokenizer_ids(tokenizer) == ids,
                           "decoder tokenizer IDs changed during implementation authentication")
            return {"schema": "reviewed-decoder-tokenizer-contract/v2", **ids,
                    "pipeline_kind": summary[0], "pipeline_sha256": summary[2],
                    "pipeline_bytes": summary[3]}
    else:
        pipeline = _reviewed_json(raw)
    _reviewed_closed(pipeline, {"schema", "kind", "backend", "frontend", "implementation", "transport"},
                     "complete actual tokenizer pipeline")
    _reviewed_decoder_need(pipeline["schema"] == "reviewed-decoder-tokenizer-pipeline/v1"
                   and pipeline["kind"] in {"huggingface_fast", "fictional_fixed_byte"}
                   and type(pipeline["backend"]) is dict and bool(pipeline["backend"])
                   and type(pipeline["frontend"]) is dict and bool(pipeline["frontend"]),
                   "supported complete tokenizer pipeline with actual backend/frontend required")
    _reviewed_closed(pipeline["transport"], {"body_only", "truncation", "padding"},
                     "explicit tokenizer transport configuration")
    _reviewed_decoder_need(pipeline["transport"]["body_only"] is True
                   and pipeline["transport"]["truncation"] is False
                   and pipeline["transport"]["padding"] is False,
                   "body-only tokenizer transport without truncation or padding required")
    if pipeline["kind"] == "huggingface_fast":
        from ...optimizers.logic_theorem_optimizer.autoencoder_training_worker import ReviewedPretrainedTokenizer
        _reviewed_decoder_need(type(tokenizer) is ReviewedPretrainedTokenizer,
                       "exact maintained ReviewedPretrainedTokenizer required for production pipeline")
    else:
        _reviewed_decoder_need(type(pipeline["implementation"]) is list,
                       "complete fixed-byte implementation pin inventory required")
        _reviewed_decoder_validate_fixed_byte_pipeline(tokenizer, pipeline, ids)
    _reviewed_decoder_tokenizer_implementation(pipeline["implementation"])
    _reviewed_decoder_need(_reviewed_decoder_tokenizer_ids(tokenizer) == ids,
                   "decoder tokenizer IDs changed during implementation authentication")
    return {"schema": "reviewed-decoder-tokenizer-contract/v2", **ids,
            "pipeline_kind": pipeline["kind"], "pipeline_sha256": hashlib.sha256(raw).hexdigest(),
            "pipeline_bytes": len(raw)}


def _reviewed_decoder_tokens(tokenizer, text, contract, maximum, label):
    # encode is a body-only transport. Special tokens are added here, counted
    # in the bound, and never inferred or removed from an offered token stream.
    offered = tokenizer.encode(text)
    _reviewed_decoder_need(type(offered) is list, "ordinary body-only " + label + " token list required")
    # A tokenizer can retain its returned list and mutate it inside decode.
    # Validate an owned snapshot, and pass a second copy to that callback.
    body = list(offered)
    _reviewed_decoder_need(len(body) + 2 <= maximum,
                   label + " token budget exceeded; truncation forbidden")
    _reviewed_decoder_need(all(type(value) is int and 0 <= value < contract["vocab_size"]
                       and value not in (contract["bos_token_id"], contract["eos_token_id"])
                       for value in body), "plain body-only " + label + " token IDs required")
    decoded = tokenizer.decode(list(body))
    _reviewed_decoder_need(type(decoded) is str and decoded == text,
                   "lossless exact " + label + " tokenizer roundtrip required")
    return [contract["bos_token_id"], *body, contract["eos_token_id"]]


def _reviewed_decoder_component_split_guard(assessment, records):
    """Keep the entire currently reviewed component in the training partition.

    A complete definition target includes its links to the other normative
    uses. Text similarity/group metadata alone cannot detect that dependency.
    The existing cumulative guard has already checked frozen assignments and
    conflicts; this additional exact-source join includes unselected component
    units too. It never relabels a split or drops target fields to fit a batch.

    Current admission records external references as artifact/version pins,
    without an external target-unit/source/fold map. Nonempty cross_references
    anywhere in this assessed component are therefore unsupported here. Internal
    definition_uses remain intact in every complete nine-field target. This
    local guard does not establish corpus-wide dependency isolation.
    """
    import hashlib
    units = assessment["units"]
    _reviewed_decoder_need(type(units) is list and bool(units), "complete assessed decoder component required")
    seen, joined = set(), []
    for unit in units:
        _reviewed_decoder_need(type(unit) is dict and type(unit.get("unit_id")) is str
                       and unit["unit_id"] not in seen and type(unit.get("source_text")) is str,
                       "unique source-grounded assessed decoder component unit required")
        seen.add(unit["unit_id"])
        target = unit.get("canonical_ir")
        _reviewed_decoder_need(type(target) is dict and set(target) == _REVIEWED_DECODER_TARGET_FIELDS,
                       "complete nine-field assessed decoder component target required")
        _reviewed_decoder_need(type(target["cross_references"]) is list,
                       "complete assessed decoder component cross-reference inventory required")
        _reviewed_decoder_need(not target["cross_references"],
                       "unsupported external cross-reference source/frozen-split mapping in reviewed component")
        source_sha = hashlib.sha256(unit["source_text"].encode("utf-8")).hexdigest()
        matches = sorted((record for record in records.values()
                          if record["source_sha256"] == source_sha
                          and record["source_text"] == unit["source_text"]), key=lambda item: item["id"])
        _reviewed_decoder_need(bool(matches), "reviewed component source is missing from cumulative frozen history")
        _reviewed_decoder_need(all(record["assignment"] == "train" for record in matches),
                       "reviewed component dependency crosses a non-training frozen assignment")
        joined.append({"unit_id": unit["unit_id"], "source_text_sha256": source_sha,
                       "history_sample_ids": [record["id"] for record in matches], "assignment": "train"})
    return {"schema": "reviewed-decoder-component-split-guard/v1",
            "rule": "all_current_reviewed_component_sources_resolve_only_to_train_history",
            "units": joined, "component_unit_count": len(joined), "passed": True,
            "external_cross_reference_count": 0, "external_cross_reference_mapping_supported": False,
            "corpus_wide_dependency_isolation_proved": False,
            "assignments_recomputed": False, "target_fields_discarded": False}


def _reviewed_decoder_target_identities(canonical_ir):
    """Separate syntax/local facets from full record and custody identities.

    These are exact content identities, with no claim of semantic equivalence
    or incompatibility when different custody/context records hash differently.
    """
    import hashlib
    _reviewed_closed(canonical_ir, _REVIEWED_DECODER_TARGET_FIELDS, "complete target identity population")
    digest = lambda value: hashlib.sha256(_reviewed_wire(value)).hexdigest()
    return {"schema": "reviewed-decoder-target-identities/v1",
        "pure_typed_expression_sha256": digest(canonical_ir["typed_expression"]),
        "ordered_argument_roles_sha256": digest(canonical_ir["argument_roles"]),
        "assumptions_sha256": digest(canonical_ir["assumptions"]),
        "local_facets_sha256": digest({key: canonical_ir[key]
            for key in ("profile", "argument_roles", "assumptions")}),
        "interpretation_id_sha256": digest(canonical_ir["interpretation_id"]),
        "governing_context_sha256": digest(canonical_ir["governing_context"]),
        "source_binding_sha256": digest(canonical_ir["source_binding"]),
        "definition_uses_sha256": digest(canonical_ir["definition_uses"]),
        "cross_references_sha256": digest(canonical_ir["cross_references"]),
        "dependency_custody_sha256": digest({key: canonical_ir[key]
            for key in ("definition_uses", "cross_references")}),
        "full_nine_field_target_sha256": digest(canonical_ir),
        "semantic_equivalence_or_incompatibility_proved": False}


def _reviewed_decoder_source_target_wires(rows, contexts, selection_context, *, _target_codec=REVIEWED_DECODER_TARGET_CODEC):
    """Reject unsupported many-target transport for identical complete inputs.

    This current-batch relation check does not adjudicate meaning, turn custody
    differences into semantic contradictions or reconstruct historical caller
    inputs from target labels. Current admission offers no multi-target policy.
    """
    seen, wires = {}, []
    selections = [selection_context] * len(rows) if type(selection_context) is dict else selection_context
    for row, context, selection_context in zip(rows, contexts, selections, strict=True):
        target = row["canonical_ir"]
        _reviewed_decoder_need(target["interpretation_id"] == selection_context["interpretation_id"],
                       "caller-known interpretation selection differs from full target; no label filling")
        _reviewed_decoder_need(type(target["definition_uses"]) is list
                       and all(type(use) is dict
                               and use.get("interpretation_id") == selection_context["interpretation_id"]
                               for use in target["definition_uses"]),
                       "definition-use interpretation differs from caller-known selection")
        source = {"profile": REVIEWED_DECODER_SOURCE_PROFILE, "source_text": row["source_text"],
            "governing_context": context["governing_context"], "source_binding": context["source_binding"],
            "selection_context": selection_context}
        source_wire = _reviewed_wire(source).decode("utf-8")
        _reviewed_decoder_need(_target_codec in {REVIEWED_DECODER_TARGET_CODEC, REVIEWED_DECODER_DIGEST_OMITTED_TARGET_CODEC},
                               "explicit supported target codec required")
        target_json = (encode_reviewed_decoder_digest_omitted_target(target, target_codec=_target_codec)
            if _target_codec == REVIEWED_DECODER_DIGEST_OMITTED_TARGET_CODEC
            else _reviewed_wire(target).decode("utf-8"))
        _reviewed_decoder_need(source_wire not in seen or seen[source_wire] == target_json,
                       "unsupported conflicting full-target relation for identical complete source/selection input; no admitted multi-target policy")
        seen[source_wire] = target_json
        wires.append((source_wire, target_json))
    return wires


def _reviewed_decoder_selection(selection):
    _reviewed_closed(selection, {"schema", "interpretation_id", "selection_mode"},
                     "caller-known interpretation selection without reference labels")
    _reviewed_decoder_need(selection["schema"] == "caller-known-interpretation-selection/v1"
                   and selection["selection_mode"] == "identifier_only"
                   and type(selection["interpretation_id"]) is str
                   and 0 < len(selection["interpretation_id"]) <= 512,
                   "explicit caller-known identifier_only selection required; meaning-policy route UNPROVIDED/unsupported")


def _reviewed_decoder_admission_custody(admitted):
    return {"registry_sha256": admitted["expected_registry_sha256"],
            "policy_sha256": admitted["expected_policy_sha256"],
            "reviews_sha256": admitted["expected_reviews_sha256"],
            "dependency_manifest_sha256": admitted["preparation"]["subject"]["dependency_manifest_sha256"],
            "review_subject_full_unit_records_sha256": admitted["preparation"]["subject"]["ast_sha256"],
            "review_subject_ast_label_is_pure_typed_expression": False}


def prepare_reviewed_decoder_training_inputs(registry, *, stage_artifact, expected_stage_sha256,
        current_admission_inputs, expected_admission_inputs_sha256,
        exposure_records, expected_exposure_sha256, source_contexts,
        expected_source_contexts_sha256, split_config, expected_split_config_sha256,
        tokenizer, max_source_tokens, max_target_tokens, allow_fictional_fixture=False):
    """Legacy public contract, fixed to reviewed admission V2."""
    return _prepare_reviewed_decoder_training_inputs(registry, _admission_version="v2",
        stage_artifact=stage_artifact,
        expected_stage_sha256=expected_stage_sha256,
        current_admission_inputs=current_admission_inputs,
        expected_admission_inputs_sha256=expected_admission_inputs_sha256,
        exposure_records=exposure_records,
        expected_exposure_sha256=expected_exposure_sha256,
        source_contexts=source_contexts,
        expected_source_contexts_sha256=expected_source_contexts_sha256,
        split_config=split_config,
        expected_split_config_sha256=expected_split_config_sha256,
        tokenizer=tokenizer,
        max_source_tokens=max_source_tokens,
        max_target_tokens=max_target_tokens,
        allow_fictional_fixture=allow_fictional_fixture,
    )


def prepare_reviewed_mixed_decoder_training_inputs_v4(registry, *, admission_profile, **kwargs):
    """Prepare data only from explicit homogeneous admission V3 cycle V4."""
    _reviewed_decoder_need(type(admission_profile) is str and admission_profile == REVIEWED_MIXED_ADMISSION_PROFILE,
                           "explicit mixed-sort admission V3 profile required")
    return _prepare_reviewed_decoder_training_inputs(registry, _admission_version="v3", **kwargs)


def _prepare_reviewed_decoder_training_inputs(registry, *, stage_artifact, expected_stage_sha256,
        current_admission_inputs, expected_admission_inputs_sha256,
        exposure_records, expected_exposure_sha256, source_contexts,
        expected_source_contexts_sha256, split_config, expected_split_config_sha256,
        tokenizer, max_source_tokens, max_target_tokens, allow_fictional_fixture=False, _admission_version="v2", _target_codec=REVIEWED_DECODER_TARGET_CODEC):
    """Prepare detached training-only source/full-target tokens, without fitting.

    The registry protocol is read-only: artifact_path(descriptor) and
    read_artifact(descriptor, max_bytes=...). Current source/review/policy inputs
    are supplied separately and replayed by the existing v2 owners. A staged
    seal or historical ready receipt cannot replace that replay.

    Source context is independently supplied and pinned input metadata with
    governing_context, source_binding and a caller-known interpretation selector.
    The selector is never filled from targets/admission labels, and identifier
    equality is not meaning resolution. Equality to admitted facts is checked;
    this function does not authenticate how the caller learned those facts.
    All nine target fields remain in target_json. No formula, ordered roles,
    definition uses or reference target enter the five-key v2 source_wire.
    A v3 stage requires a current admission mapping and caller-known selection
    mapping keyed by its exact signed component IDs. Its v3 preparation receipt
    retains each component's custody and guard. Row-level token wires keep v2.

    Tokenizer assets and external clock/registry freshness retain their existing
    owners. Full canonical pipeline/configuration and ordinary implementation
    identities are checked alongside encode/decode and BOS/EOS/vocabulary.
    Re-call this function at the independently guarded training boundary; its
    return is data and provenance, not an execution capability.
    """
    digest_omitted = _target_codec == REVIEWED_DECODER_DIGEST_OMITTED_TARGET_CODEC
    _reviewed_decoder_need(type(_target_codec) is str and _target_codec in {
        REVIEWED_DECODER_TARGET_CODEC, REVIEWED_DECODER_DIGEST_OMITTED_TARGET_CODEC}
        and (not digest_omitted or _admission_version == "v3"),
        "explicit digest-omitted codec requires mixed admission V3")
    for expected in (expected_stage_sha256, expected_admission_inputs_sha256,
                     expected_exposure_sha256, expected_source_contexts_sha256,
                     expected_split_config_sha256):
        _reviewed_sha(expected)
    _reviewed_decoder_need(type(split_config) is dict,
                   "complete split_config required: staged history stores only frozen config digests")
    _reviewed_decoder_need(type(allow_fictional_fixture) is bool, "explicit decoder fixture opt-in required")
    for value, label in ((max_source_tokens, "source"), (max_target_tokens, "target")):
        _reviewed_decoder_need(type(value) is int and 2 <= value <= 65536,
                       "plain bounded " + label + " token budget including BOS/EOS required")
    import hashlib
    import sys
    from pathlib import Path
    from ...optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    from ...optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    admission_contract = _reviewed_cycle_contract(_admission_version)
    admission = admission_contract["admission"]

    reference = _reviewed_copy(stage_artifact)
    _reviewed_decoder_need(_reviewed_ref(reference)["sha256"] == expected_stage_sha256,
                   "independently pinned reviewed stage artifact differs")
    observed_artifacts = []
    def read_current_artifact(selected):
        raw = _reviewed_read(registry, selected)
        observed_artifacts.append((_reviewed_copy(selected), raw))
        return raw
    stage_raw = read_current_artifact(reference)
    stage = _reviewed_json(stage_raw)
    _reviewed_closed(stage, _reviewed_cycle_fields(_admission_version), "reviewed decoder stage artifact")
    component_cycle = stage["schema"] in {REVIEWED_COMPONENT_CYCLE_SCHEMA, REVIEWED_MIXED_CYCLE_SCHEMA}
    _reviewed_decoder_need(_reviewed_cycle_format(stage, admission_version=_admission_version)
                   and stage["transition_kind"] in {"bootstrap", "successor"}
                   and stage["withdrawal_provenance"] is None,
                   "positive complete reviewed stage profile required; metadata compatibility stays false")
    _reviewed_lineage(stage["checkpoint_lineage"])
    rows = _reviewed_json(read_current_artifact(stage["rows_artifact"]))
    _reviewed_decoder_need(type(rows) is list and 0 < len(rows) <= MAX_REVIEWED_CYCLE_ROWS,
                   "bounded nonempty complete reviewed decoder rows required")
    for row in rows:
        _reviewed_closed(row, {"id", "unit_id", "source_text", "canonical_ir"}, "complete decoder row")
        _reviewed_closed(row["canonical_ir"], _REVIEWED_DECODER_TARGET_FIELDS,
                         "full nine-field reviewed decoder target")
    memberships = (_reviewed_component_parent_memberships(stage["consumer_receipt"], rows, consumer, admission_version=_admission_version)
                   if component_cycle else None)
    manifest = _reviewed_json(read_current_artifact(stage["split_manifest_artifact"]))
    history = _reviewed_json(read_current_artifact(stage["history_artifact"]))
    config = _reviewed_copy(split_config, expected_split_config_sha256)
    exposure = _reviewed_copy(exposure_records, expected_exposure_sha256)
    contexts = _reviewed_copy(source_contexts, expected_source_contexts_sha256)
    admission_copy, admission_sha = consumer._reviewed_snapshot(current_admission_inputs)
    _reviewed_decoder_need(admission_sha == expected_admission_inputs_sha256,
                   "current complete admission input commitment differs")
    json_inputs = (stage_artifact, exposure_records, source_contexts, split_config)
    frozen_inputs = tuple(_reviewed_wire(value) for value in json_inputs)
    modules = (sys.modules[__name__], consumer, splits, admission)
    if component_cycle:
        from . import legal_graph_dependencies as dependencies
        modules += (dependencies,)
    def implementation():
        return {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                for module in modules}
    producers = implementation()

    parent_rows, parent_records, previous_history = [], {}, None
    replay_history = history
    if stage["transition_kind"] == "bootstrap":
        _reviewed_decoder_need(stage["parent_artifact"] is None and history.get("parent_history_artifact") is None,
                       "bootstrap decoder history cannot conceal a parent")
        if history.get("scope_kind") == "declared_genesis":
            # The staging owner appends the current manifest. Invert only that
            # exact deterministic append before reusing its genesis validator.
            current_entry = {"manifest": manifest, "sha256": stage["split_manifest_artifact"]["sha256"]}
            _reviewed_decoder_need(history.get("split_manifests") == [current_entry],
                           "declared genesis must retain exactly its staged current manifest")
            replay_history = dict(history, split_manifests=[])
    else:
        parent = _reviewed_json(read_current_artifact(stage["parent_artifact"]))
        _reviewed_closed(parent, _reviewed_cycle_fields(_admission_version), "decoder historical parent")
        _reviewed_decoder_need(_reviewed_cycle_format(parent, admission_version=_admission_version)
                       and (component_cycle or parent["schema"] == REVIEWED_CYCLE_SCHEMA),
                       "complete reviewed decoder parent profile required")
        parent_rows = _reviewed_json(read_current_artifact(parent["rows_artifact"]))
        previous_history = _reviewed_json(read_current_artifact(parent["history_artifact"]))
        _reviewed_decoder_need(history.get("parent_history_artifact") == parent["history_artifact"]
                       and stage["checkpoint_lineage"] == parent["checkpoint_lineage"],
                       "decoder parent history or declared checkpoint lineage differs")
        _reviewed_decoder_need(type(parent_rows) is list and len(parent_rows) <= MAX_REVIEWED_CYCLE_ROWS
                       and type(previous_history.get("records")) is list,
                       "bounded complete decoder parent population required")
        parent_records = {record["id"]: record for record in previous_history["records"]}
        _reviewed_decoder_need(len(parent_records) == len(previous_history["records"]),
                       "duplicate decoder historical parent identity")
    guarded_history, records, guard = _reviewed_history(
        replay_history, manifest, rows, config, previous_history, splits)
    _reviewed_decoder_need(guarded_history == history and guard == stage["history_guard"],
                   "staged history differs from complete current cumulative split replay")
    _reviewed_transition(stage["transition"], parent_rows, rows, records, parent_records, registry)
    if stage["transition_kind"] == "successor":
        retained = set(stage["transition"]["retained"])
        _reviewed_decoder_need(not any(row["id"] in parent_records and row["id"] not in retained for row in rows),
                       "unsupported_historical_id_reactivation")
        if component_cycle and retained:
            if parent["schema"] in {REVIEWED_COMPONENT_CYCLE_SCHEMA, REVIEWED_MIXED_CYCLE_SCHEMA}:
                parent_memberships = _reviewed_component_parent_memberships(parent["consumer_receipt"], parent_rows, consumer, admission_version=_admission_version)
            else:
                transport = _reviewed_json(read_current_artifact(parent["admission_transport_artifact"]))
                _reviewed_decoder_need(transport["admission_inputs_sha256"] == parent["consumer_receipt"]["admission_inputs_sha256"],
                               "historical component admission transport differs")
                identity = _reviewed_component_id(transport["skeleton"])
                parent_memberships = dict.fromkeys((row["id"] for row in parent_rows), identity)
            _reviewed_decoder_need(all(parent_memberships[row_id] == memberships[row_id] for row_id in retained),
                           "retained rows must keep their independently reviewed component identity")

    selection_field = "component_selection_contexts" if component_cycle else "selection_context"
    context_profile = REVIEWED_COMPONENT_DECODER_CONTEXT_PROFILE if component_cycle else REVIEWED_DECODER_SOURCE_PROFILE
    _reviewed_closed(contexts, {"profile", selection_field, "rows"},
                     "separately supplied source-known selection contexts")
    _reviewed_decoder_need(contexts["profile"] == context_profile
                   and type(contexts["rows"]) is list and len(contexts["rows"]) == len(rows),
                   "explicit complete source-known component selection context required" if component_cycle
                   else "explicit complete source-known selection context v2 required")
    selection = contexts[selection_field]
    if component_cycle:
        _reviewed_decoder_need(type(selection) is dict and set(selection) == set(memberships.values()),
                       "caller-known selection must cover the exact staged component population")
        for selected in selection.values():
            _reviewed_decoder_selection(selected)
        selections = [selection[memberships[row["id"]]] for row in rows]
    else:
        _reviewed_decoder_selection(selection)
        selections = selection
    for row, context in zip(rows, contexts["rows"], strict=True):
        _reviewed_closed(context, {"id", "unit_id", "governing_context", "source_binding"},
                         "source-known context row without target labels")
        _reviewed_closed(context["governing_context"], {"jurisdiction", "instrument_id", "governing_edition",
            "legal_as_of_utc", "valid_from_utc", "valid_until_utc"}, "source-known governing context")
        _reviewed_closed(context["source_binding"], {"source_version_cid", "occurrence_cid", "document_revision"},
                         "source-known source binding")
        _reviewed_decoder_need(context["id"] == row["id"] and context["unit_id"] == row["unit_id"]
                       and context["governing_context"] == row["canonical_ir"]["governing_context"]
                       and context["source_binding"] == row["canonical_ir"]["source_binding"],
                       "separately pinned source context differs from admitted source facts")

    def bind_training(selected, exposed, admitted, rows_sha, exposed_sha, admitted_sha):
        binding = admission_contract["prepare"](selected,
            expected_rows_sha256=rows_sha, split_manifest=manifest,
            expected_split_manifest_sha256=stage["split_manifest_artifact"]["sha256"],
            admission_inputs=admitted, expected_admission_inputs_sha256=admitted_sha,
            exposure_records=exposed, expected_exposure_sha256=exposed_sha,
            operation="training", allow_fictional_fixture=allow_fictional_fixture)
        receipt = admission_contract["validate"](binding, selected,
            split_manifest=manifest, admission_inputs=admitted, exposure_records=exposed)
        assessment = admission_contract["assess"](**admitted)
        _reviewed_decoder_need(receipt["status"] == "ready" and receipt["operation"] == "training"
                       and receipt["row_count"] == len(selected)
                       and receipt["admission_assessment_sha256"] == admission.norm_content_adjudication_sha256(assessment)
                       and assessment["semantic_use_eligible"] is True and not assessment["blockers"],
                       "fresh current reviewed training admission required")
        fixture = assessment["provenance_kind"] == "fictional_fixture"
        _reviewed_decoder_need(type(assessment["training_mask"]) is int
                       and (fixture and allow_fictional_fixture and assessment["training_mask"] == 0
                            or not fixture and assessment["training_mask"] == 1),
                       "explicit fictional smoke scope or eligible statutory training mask required")
        return binding, receipt, assessment

    def check_current(bindings, phase):
        for binding, selected, exposed, admitted, receipt in bindings:
            current = admission_contract["validate"](binding, selected,
                split_manifest=manifest, admission_inputs=admitted, exposure_records=exposed)
            _reviewed_decoder_need(current == receipt, "current reviewed decoder admission changed " + phase)

    if component_cycle:
        _reviewed_decoder_need(type(admission_copy) is dict and set(admission_copy) == set(memberships.values()),
                       "current reviewed admission must cover the exact staged component population")
        _reviewed_decoder_need(type(exposure) is list and len(exposure) == len(rows),
                       "complete ordered component exposure population required")
        positions = {row["id"]: index for index, row in enumerate(rows)}
        bindings = []
        staged_components = stage["consumer_receipt"]["components"]

        def observations():
            for component in staged_components:
                key = component["component_id"]
                admitted = admission_copy[key]
                _reviewed_decoder_need(_reviewed_component_id(admitted) == key,
                               "current reviewed admission names another staged component")
                indices = [positions[row_id] for row_id in component["row_ids"]]
                prior_receipt = component["receipt"]
                _reviewed_decoder_need(indices == sorted(indices)
                               and prior_receipt["input_sha256s"]["split_manifest"] == stage["split_manifest_artifact"]["sha256"],
                               "staged component row order or split commitment differs")
                selected = [rows[index] for index in indices]
                exposed = [exposure[index] for index in indices]
                admitted_sha = consumer.reviewed_admission_inputs_sha256(admitted)
                binding, receipt, assessment = bind_training(selected, exposed, admitted,
                    prior_receipt["input_sha256s"]["rows"], hashlib.sha256(_reviewed_wire(exposed)).hexdigest(), admitted_sha)
                _reviewed_decoder_need(receipt["declaration_sha256"] == prior_receipt["declaration_sha256"],
                               "current reviewed declaration differs from staged component")
                bindings.append((binding, selected, exposed, admitted, receipt))
                yield {"component_id": key, "row_ids": component["row_ids"],
                       "admission_inputs_sha256": admitted_sha}, admitted, receipt, assessment

        receipt, assessments = _reviewed_joint_components(
            observations(), len(rows), records, dependencies, require=_reviewed_decoder_need, admission_version=_admission_version)
        for prior, current in zip(staged_components, receipt["components"], strict=True):
            _reviewed_decoder_need(prior["component_split_guard"] == current["component_split_guard"],
                           "staged component split guard differs from current complete replay")
        provenance_kinds = {item["provenance_kind"] for item in assessments.values()}
        _reviewed_decoder_need(len(provenance_kinds) == 1,
                       "mixed fictional and statutory components require separate training populations")
        provenance_kind = next(iter(provenance_kinds))
        fixture = provenance_kind == "fictional_fixture"
        training_mask = int(not fixture)
        component_guard = {item["component_id"]: item["component_split_guard"] for item in receipt["components"]}
        assessment_sha = {item["component_id"]: item["receipt"]["admission_assessment_sha256"]
                          for item in receipt["components"]}
        custody = {key: _reviewed_decoder_admission_custody(admitted) for key, admitted in admission_copy.items()}
    else:
        binding, receipt, assessment = bind_training(rows, exposure, admission_copy,
            stage["rows_artifact"]["sha256"], expected_exposure_sha256, admission_sha)
        bindings = [(binding, rows, exposure, admission_copy, receipt)]
        provenance_kind = assessment["provenance_kind"]
        fixture = provenance_kind == "fictional_fixture"
        training_mask = assessment["training_mask"]
        component_guard = _reviewed_decoder_component_split_guard(assessment, records)
        assessment_sha = receipt["admission_assessment_sha256"]
        custody = _reviewed_decoder_admission_custody(admission_copy)
    wires = _reviewed_decoder_source_target_wires(rows, contexts["rows"], selections, _target_codec=_target_codec)
    contract = _reviewed_decoder_tokenizer_contract(tokenizer)
    _reviewed_decoder_need(contract["pipeline_kind"] != "fictional_fixed_byte" or fixture and allow_fictional_fixture,
                   "fictional tokenizer pipeline requires fresh fictional admission and explicit fixture opt-in")

    def prepare(consumed_rows):
        _reviewed_decoder_need(consumed_rows == rows, "detached complete decoder rows changed before tokenization")
        prepared, commitments = [], []
        for row, (source_wire, target_json) in zip(consumed_rows, wires, strict=True):
            source_ids = _reviewed_decoder_tokens(tokenizer, source_wire, contract, max_source_tokens, "source")
            target_ids = _reviewed_decoder_tokens(tokenizer, target_json, contract, max_target_tokens, "target")
            prepared.append({"id": row["id"], "unit_id": row["unit_id"], "source_wire": source_wire,
                "target_json": target_json, "source_token_ids": source_ids, "target_token_ids": target_ids})
            commitments.append({"id": row["id"], "unit_id": row["unit_id"],
                "source_text_sha256": hashlib.sha256(row["source_text"].encode("utf-8")).hexdigest(),
                "source_wire_sha256": hashlib.sha256(source_wire.encode("utf-8")).hexdigest(),
                "canonical_ir_sha256": hashlib.sha256(_reviewed_wire(row["canonical_ir"]) if digest_omitted else target_json.encode("utf-8")).hexdigest(),
                "source_tokens_sha256": hashlib.sha256(_reviewed_wire(source_ids)).hexdigest(),
                "target_tokens_sha256": hashlib.sha256(_reviewed_wire(target_ids)).hexdigest(),
                "target_identities": _reviewed_decoder_target_identities(row["canonical_ir"])})
            if digest_omitted:
                commitments[-1]["model_target_wire_sha256"] = hashlib.sha256(target_json.encode("utf-8")).hexdigest()
        # All rows and both complete output budgets have passed before a caller
        # can obtain this data. No model restore/fit callback exists in this API.
        _reviewed_decoder_need(_reviewed_decoder_tokenizer_contract(tokenizer) == contract,
                       "decoder tokenizer contract changed during preparation")
        check_current(bindings, "during tokenization")
        # This is the LAST tokenizer callback. Its serializer/file/configuration
        # helpers are not assumed pure: they may retain original caller aliases.
        # Every remaining external registry observation precedes final closure.
        _reviewed_decoder_need(_reviewed_decoder_tokenizer_contract(tokenizer) == contract,
                       "decoder tokenizer contract changed after current admission replay")
        _reviewed_transition(stage["transition"], parent_rows, rows, records, parent_records, registry)
        for selected, raw in observed_artifacts:
            _reviewed_decoder_need(_reviewed_read(registry, selected) == raw,
                           "reviewed decoder registry artifact changed during tokenization or final serialization")
        # No tokenizer or registry callback occurs after these stability checks.
        check_current(bindings, "during final closure")
        _reviewed_decoder_need(tuple(_reviewed_wire(value) for value in json_inputs) == frozen_inputs
                       and consumer.reviewed_admission_inputs_sha256(current_admission_inputs) == admission_sha
                       and consumer.reviewed_admission_inputs_sha256(admission_copy) == admission_sha
                       and implementation() == producers,
                       "reviewed decoder preparation inputs, admission or named producers changed during final closure")
        _reviewed_decoder_need(_reviewed_decoder_source_target_wires(rows, contexts["rows"], selections, _target_codec=_target_codec) == wires,
                       "caller-known full input/target relation changed during preparation")
        proof = {"schema": ("reviewed-decoder-training-input-receipt/v4" if _admission_version == "v3" else
                            "reviewed-decoder-training-input-receipt/v3" if component_cycle
                            else "reviewed-decoder-training-input-receipt/v2"),
            "profile": (REVIEWED_MIXED_DECODER_INPUT_PROFILE if _admission_version == "v3" else
                        REVIEWED_COMPONENT_DECODER_INPUT_PROFILE if component_cycle else REVIEWED_DECODER_INPUT_PROFILE),
            "target_codec": REVIEWED_DECODER_TARGET_CODEC,
            "reviewed_consumer_target_codec": consumer.REVIEWED_TARGET_CODEC,
            "source_profile": REVIEWED_DECODER_SOURCE_PROFILE, "record_count": len(prepared),
            "selection_context_sha256": hashlib.sha256(_reviewed_wire(selection)).hexdigest(),
            "selection_mode": "identifier_only", "semantic_selection_supported": False,
            "meaning_policy_route": "UNPROVIDED/unsupported",
            "identifier_equality_is_meaning_resolution": False,
            "target_relation_policy": "single_exact_full_target_per_current_batch_complete_input",
            "admitted_multi_target_relation": False,
            "historical_complete_input_target_relation_proved": False,
            "custody_hash_difference_is_semantic_incompatibility": False,
            "current_admission_custody": custody,
            "training_record_ids": [row["id"] for row in prepared], "row_commitments": commitments,
            "stage_artifact_sha256": expected_stage_sha256, "rows_sha256": stage["rows_artifact"]["sha256"],
            "split_manifest_sha256": stage["split_manifest_artifact"]["sha256"],
            "history_sha256": stage["history_artifact"]["sha256"], "history_guard": guard,
            "component_split_guard": component_guard,
            "split_config_sha256": expected_split_config_sha256, "admission_inputs_sha256": admission_sha,
            "admission_assessment_sha256": assessment_sha,
            "exposure_sha256": expected_exposure_sha256, "source_contexts_sha256": expected_source_contexts_sha256,
            "prepared_records_sha256": hashlib.sha256(_reviewed_wire(prepared)).hexdigest(),
            "tokenizer_contract": contract, "max_source_tokens": max_source_tokens,
            "max_target_tokens": max_target_tokens, "implementation": producers,
            "provenance_kind": provenance_kind, "fixture_only": fixture,
            "training_mask": training_mask, "production_training_eligible": not fixture,
            "current_reviewed_training_permitted": True, "current_consumer_receipt": receipt,
            "source_context_independently_authenticated": False, "tokenizer_assets_authenticated": False,
            "tokenizer_pipeline_identity_authenticated": False,
            "tokenizer_pipeline_serialization_verified": True,
            "tokenizer_implementation_file_pins_verified": True,
            "tokenizer_behavior_independently_attested": False,
            "tokenizer_configuration_scope": "verified serialized mapping/options and code/file pins; fixture observation/closure behavior, production behavior and asset authority are not independently attested",
            "tokenizer_license_model_assets_or_execution_authorized": False,
            "backend_execution_authorized": False, "training_executed": False, "weights_updated": False,
            "proof_authority": False, "Lean_admitted": False, "corpus_admitted": False,
            "scope": "complete current-policy training-only callback inputs; no external clock, tokenizer assets or arbitrary process-read attestation"}
        if _admission_version == "v3":
            proof["admission_profile"] = REVIEWED_MIXED_ADMISSION_PROFILE
        if component_cycle:
            proof["source_context_profile"] = context_profile
        result = {"schema": (REVIEWED_MIXED_DECODER_INPUT_SCHEMA if _admission_version == "v3" else
                             REVIEWED_COMPONENT_DECODER_INPUT_SCHEMA if component_cycle else REVIEWED_DECODER_INPUT_SCHEMA),
                  "records": prepared, "receipt": proof}
        if digest_omitted:
            proof.update(schema=REVIEWED_DIGEST_OMITTED_INPUT_RECEIPT_SCHEMA,
                profile=REVIEWED_DIGEST_OMITTED_INPUT_PROFILE, target_codec=_target_codec,
                model_target_projection={"schema": "reviewed-digest-omitted-target-projection/v1",
                    "omitted_field": "typed_expression.content_digest", "other_fields_discarded": False})
            result["schema"] = REVIEWED_DIGEST_OMITTED_INPUT_SCHEMA
        result["prepared_sha256"] = hashlib.sha256(_reviewed_wire(result)).hexdigest()
        return result

    if component_cycle:
        check_current(bindings, "before tokenization")
        return prepare(rows)
    return admission_contract["consume"](binding, rows, split_manifest=manifest,
        admission_inputs=admission_copy, exposure_records=exposure, consumer=prepare)


def prepare_reviewed_decoder_generation_inputs(source_arguments, *, source_contexts,
        expected_source_contexts_sha256, tokenizer, max_source_tokens):
    """Tokenize detached source-only evaluator arguments, without reading gold.

    The existing evaluator supplies id/source_text/empty context. Independently
    pinned source contexts supply the unit ID, governing/source facts and an
    explicit caller-known interpretation selector. This transport does not
    authenticate those facts, replay admission or authorize model execution.
    Current fact equality and all execution/asset policies belong to the caller.
    No registry, training stage, canonical target or target prefix is accepted.
    """
    import hashlib
    _reviewed_decoder_need(type(max_source_tokens) is int and 2 <= max_source_tokens <= 65536,
                   "plain bounded generation source budget including BOS/EOS required")
    import re
    _reviewed_decoder_need(type(expected_source_contexts_sha256) is str
                   and re.fullmatch(r"[0-9a-f]{64}", expected_source_contexts_sha256) is not None,
                   "exact lowercase generation source-context SHA256 required")

    def text(value, label, maximum=512):
        _reviewed_decoder_need(type(value) is str and 0 < len(value) <= maximum
                       and not any(character in value for character in "\r\n\0"),
                       "bounded plain " + label + " required")

    def current_raw_inputs():
        _reviewed_decoder_need(type(source_arguments) in (list, tuple)
                       and 1 <= len(source_arguments) <= 32,
                       "one through 32 ordered source-only callback arguments required")
        _reviewed_decoder_need(type(source_contexts) is dict
                       and set(source_contexts) == {"profile", "selection_context", "rows"},
                       "closed independent generation source contexts required")
        _reviewed_decoder_need(source_contexts["profile"] == REVIEWED_DECODER_SOURCE_PROFILE
                       and type(source_contexts["rows"]) is list
                       and len(source_contexts["rows"]) == len(source_arguments),
                       "complete ordered source-context v2 population required")
        selection = source_contexts["selection_context"]
        _reviewed_decoder_need(type(selection) is dict
                       and set(selection) == {"schema", "interpretation_id", "selection_mode"}
                       and selection["schema"] == "caller-known-interpretation-selection/v1"
                       and selection["selection_mode"] == "identifier_only",
                       "closed caller-known identifier-only selection required")
        text(selection["interpretation_id"], "interpretation selector")
        identifiers, units, source_bytes = set(), set(), 0
        for argument, context in zip(source_arguments, source_contexts["rows"], strict=True):
            _reviewed_decoder_need(type(argument) is dict and set(argument) == {"id", "source_text", "context"},
                           "closed source-only evaluator argument required; targets forbidden")
            text(argument["id"], "source row ID")
            _reviewed_decoder_need(argument["id"] not in identifiers, "unique generation source IDs required")
            identifiers.add(argument["id"])
            _reviewed_decoder_need(type(argument["source_text"]) is str
                           and 0 < len(argument["source_text"]) <= MAX_REVIEWED_ARTIFACT_BYTES,
                           "complete bounded generation source text required")
            try:
                source_bytes += len(argument["source_text"].encode("utf-8"))
            except UnicodeError as error:
                raise ReviewedDecoderInputValidationError("generation source must be valid UTF8") from error
            _reviewed_decoder_need(source_bytes <= MAX_REVIEWED_ARTIFACT_BYTES,
                           "generation source population exceeds existing artifact bound")
            supplied = argument["context"]
            _reviewed_decoder_need(type(supplied) is dict and set(supplied) == {"permitted", "retrieved"}
                           and type(supplied["permitted"]) is list and supplied["permitted"] == []
                           and type(supplied["retrieved"]) is list and supplied["retrieved"] == [],
                           "source-selection-context v2 requires empty supplied examples; no silent context dropping")
            _reviewed_decoder_need(type(context) is dict
                           and set(context) == {"id", "unit_id", "governing_context", "source_binding"},
                           "closed generation source-context row required")
            text(context["id"], "context row ID")
            text(context["unit_id"], "context unit ID")
            _reviewed_decoder_need(context["id"] == argument["id"] and context["unit_id"] not in units,
                           "exact ordered source/context ID join and unique unit IDs required")
            units.add(context["unit_id"])
            governing, binding = context["governing_context"], context["source_binding"]
            _reviewed_decoder_need(type(governing) is dict
                           and set(governing) == {"jurisdiction", "instrument_id", "governing_edition",
                               "legal_as_of_utc", "valid_from_utc", "valid_until_utc"}
                           and type(binding) is dict
                           and set(binding) == {"source_version_cid", "occurrence_cid", "document_revision"},
                           "closed six-field governing context and three-field source binding required")
            for key, value in governing.items():
                if key != "valid_until_utc" or value is not None:
                    text(value, "governing context scalar")
            for value in binding.values():
                text(value, "source binding scalar")
        return _reviewed_wire(list(source_arguments)), _reviewed_wire(source_contexts)

    arguments_raw, contexts_raw = current_raw_inputs()
    _reviewed_decoder_need(hashlib.sha256(contexts_raw).hexdigest() == expected_source_contexts_sha256,
                   "independently pinned generation source contexts differ")
    arguments, contexts = _reviewed_json(arguments_raw), _reviewed_json(contexts_raw)
    contract = _reviewed_decoder_tokenizer_contract(tokenizer)
    _reviewed_decoder_need(current_raw_inputs() == (arguments_raw, contexts_raw),
                   "generation source inputs changed during tokenizer contract derivation")
    records, commitments = [], []
    for argument, context in zip(arguments, contexts["rows"], strict=True):
        source = {"profile": REVIEWED_DECODER_SOURCE_PROFILE, "source_text": argument["source_text"],
            "governing_context": context["governing_context"], "source_binding": context["source_binding"],
            "selection_context": contexts["selection_context"]}
        wire = _reviewed_wire(source).decode("utf-8")
        tokens = _reviewed_decoder_tokens(tokenizer, wire, contract, max_source_tokens, "generation source")
        _reviewed_decoder_need(_reviewed_decoder_tokenizer_contract(tokenizer) == contract,
                       "generation tokenizer pipeline changed during source tokenization")
        _reviewed_decoder_need(current_raw_inputs() == (arguments_raw, contexts_raw),
                       "generation source inputs changed during tokenization")
        records.append({"id": argument["id"], "unit_id": context["unit_id"],
                        "source_wire": wire, "source_token_ids": tokens})
        commitments.append({"id": argument["id"], "unit_id": context["unit_id"],
            "source_text_sha256": hashlib.sha256(argument["source_text"].encode("utf-8")).hexdigest(),
            "source_wire_sha256": hashlib.sha256(wire.encode("utf-8")).hexdigest(),
            "source_token_ids_sha256": hashlib.sha256(_reviewed_wire(tokens)).hexdigest()})
    # The final tokenizer callback precedes all final input stability checks.
    _reviewed_decoder_need(_reviewed_decoder_tokenizer_contract(tokenizer) == contract,
                   "generation tokenizer pipeline changed before final closure")
    _reviewed_decoder_need(current_raw_inputs() == (arguments_raw, contexts_raw),
                   "generation source inputs changed before final closure")
    receipt = {"schema": "reviewed-decoder-generation-input-receipt/v1",
        "profile": "source-only-reviewed-decoder-generation-inputs/v1",
        "source_profile": REVIEWED_DECODER_SOURCE_PROFILE, "record_count": len(records),
        "source_arguments_sha256": hashlib.sha256(arguments_raw).hexdigest(),
        "source_contexts_sha256": expected_source_contexts_sha256,
        "selection_context_sha256": hashlib.sha256(_reviewed_wire(contexts["selection_context"])).hexdigest(),
        "prepared_records_sha256": hashlib.sha256(_reviewed_wire(records)).hexdigest(),
        "row_commitments": commitments, "tokenizer_contract": contract,
        "max_source_tokens": max_source_tokens, "supplied_examples": "empty_only",
        "semantic_selection_supported": False, "source_facts_authenticated": False,
        "current_admission_replayed": False, "backend_execution_authorized": False,
        "target_access_performed": False, "training_stage_access_performed": False,
        "proof_authority": False, "corpus_admitted": False}
    return {"records": records, "receipt": receipt}


def prepare_reviewed_decoder_context_generation_inputs(source_arguments, *, source_contexts,
        expected_source_contexts_sha256, expected_context_records_sha256,
        tokenizer, max_source_tokens, context_transport="plain_json_v1", context_budget_profile=None):
    """Transport complete rich TRAIN examples; never authenticate permission.

    The admitted caller owns all review, split, context-use and execution policy.
    This sibling accepts only detached source arguments and independently bound
    source facts. The original source-only preparer continues to require empty
    context. No target, registry, training stage or permission flag is accepted.
    """
    import hashlib
    import re
    from ...optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker

    _reviewed_decoder_need(context_budget_profile is None or type(context_budget_profile) is str
        and context_budget_profile in {worker.REVIEWED_QWEN2_CONTEXT_BUDGET_PROFILE,
            worker.REVIEWED_QWEN2_EXPANDED_CONTEXT_BUDGET_PROFILE},
        "explicit supported context budget profile required")
    context_token_limit = (worker.REVIEWED_QWEN2_EXPANDED_CONTEXT_MAX_TOKENS
        if context_budget_profile == worker.REVIEWED_QWEN2_EXPANDED_CONTEXT_BUDGET_PROFILE else
        worker.REVIEWED_QWEN2_CONTEXT_MAX_TOKENS if context_budget_profile is not None
        else worker.REVIEWED_GENERATION_CONTEXT_MAX_TOKENS)
    _reviewed_decoder_need(type(context_transport) is str and context_transport in {"plain_json_v1", "shared_json_v1", "shared_json_v2", "shared_json_v3"},
        "explicit supported rich context DATA transport required")
    # Both lossless wires use the exact named budget checked above; None
    # retains the unchanged generic context limit and every codec bound.
    shared = context_transport in {"shared_json_v1", "shared_json_v2", "shared_json_v3"}
    shorttag = context_transport == "shared_json_v2"
    keylayout = context_transport == "shared_json_v3"
    shared_profile = (worker.REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V3 if keylayout else
                      worker.REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V2 if shorttag
                      else worker.REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE)
    _reviewed_decoder_need(type(expected_context_records_sha256) is str
        and re.fullmatch(r"[0-9a-f]{64}", expected_context_records_sha256) is not None,
        "exact rich generation context-record SHA256 required")

    def snapshot():
        _reviewed_decoder_need(type(source_arguments) in (list, tuple)
            and 1 <= len(source_arguments) <= 32, "bounded ordered rich source arguments required")
        for argument in source_arguments:
            _reviewed_decoder_need(type(argument) is dict
                and set(argument) == {"id", "source_text", "context"}
                and type(argument["context"]) is dict
                and set(argument["context"]) == {"permitted", "retrieved"}
                and type(argument["context"]["permitted"]) is list
                and type(argument["context"]["retrieved"]) is list,
                "closed detached rich source arguments required")
        return _reviewed_wire(list(source_arguments)), _reviewed_wire(source_contexts)

    arguments_raw, contexts_raw = snapshot()
    arguments = _reviewed_json(arguments_raw)
    context_population = [{"id": argument["id"], "context": argument["context"]}
                          for argument in arguments]
    _reviewed_decoder_need(hashlib.sha256(_reviewed_wire(context_population)).hexdigest()
        == expected_context_records_sha256, "independently pinned rich context population differs")
    # Explicit composition of source fields, never silent context dropping:
    # the returned records below always serialize the original complete context.
    empty_arguments = [{"id": row["id"], "source_text": row["source_text"],
                        "context": {"permitted": [], "retrieved": []}} for row in arguments]
    base = prepare_reviewed_decoder_generation_inputs(empty_arguments,
        source_contexts=source_contexts,
        expected_source_contexts_sha256=expected_source_contexts_sha256,
        tokenizer=tokenizer, max_source_tokens=max_source_tokens)
    _reviewed_decoder_need(snapshot() == (arguments_raw, contexts_raw),
        "rich source/context inputs changed during source-field preparation")
    contract = _reviewed_decoder_tokenizer_contract(tokenizer)
    _reviewed_decoder_need(snapshot() == (arguments_raw, contexts_raw),
        "rich source/context inputs changed during tokenizer contract derivation")
    query_ids = {row[key] for row in base["records"] for key in ("id", "unit_id")}
    records, commitments = [], []

    def closed_inputs():
        _reviewed_decoder_need(_reviewed_decoder_tokenizer_contract(tokenizer) == contract,
            "rich generation tokenizer pipeline changed")
        _reviewed_decoder_need(snapshot() == (arguments_raw, contexts_raw),
            "rich source/context inputs changed during tokenization")

    for argument, original in zip(arguments, base["records"], strict=True):
        source = _reviewed_json(original["source_wire"].encode("utf-8"))
        source["profile"] = (shared_profile if shared
                             else worker.REVIEWED_GENERATION_CONTEXT_SOURCE_PROFILE)
        source["context"] = ((pack_reviewed_context_json_v3(argument["context"]) if keylayout else
                              pack_reviewed_context_json_v2(argument["context"]) if shorttag
                              else pack_reviewed_context_json_v1(argument["context"])) if shared else
            {"profile": worker.REVIEWED_GENERATION_CONTEXT_PROFILE,
             "mode": "rich_full_ast", **argument["context"]})
        try:
            context_text = worker._reviewed_generation_context_wire(source, query_ids)
        except worker.TrainingJobValidationError as error:
            raise ReviewedDecoderInputValidationError(str(error)) from error
        context_tokens = _reviewed_decoder_tokens(tokenizer, context_text, contract,
            context_token_limit, "complete rich context")
        closed_inputs()
        source_text = _reviewed_wire(source).decode("utf-8")
        source_tokens = _reviewed_decoder_tokens(tokenizer, source_text, contract,
            max_source_tokens, "complete source with rich context")
        closed_inputs()
        record = {"id": original["id"], "unit_id": original["unit_id"],
                  "source_wire": source_text, "source_token_ids": source_tokens}
        records.append(record)
        commitments.append({"id": record["id"], "unit_id": record["unit_id"],
            "source_wire_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            "source_token_ids_sha256": hashlib.sha256(_reviewed_wire(source_tokens)).hexdigest(),
            "context_sha256": hashlib.sha256(context_text.encode("utf-8")).hexdigest(),
            "context_tokens_including_bos_eos": len(context_tokens)})
    closed_inputs()
    return {"records": records, "receipt": {
        "schema": "reviewed-decoder-context-generation-input-receipt/v2" if context_budget_profile is not None else "reviewed-decoder-context-generation-input-receipt/v1",
        "profile": "rich-TRAIN-reviewed-decoder-generation-inputs/v2" if context_budget_profile is not None else "rich-TRAIN-reviewed-decoder-generation-inputs/v1",
        **({"context_budget_profile": context_budget_profile} if context_budget_profile is not None else {}),
        "source_profile": (shared_profile if shared
                           else worker.REVIEWED_GENERATION_CONTEXT_SOURCE_PROFILE),
        **({"context_transport": context_transport,
            "max_expanded_context_bytes": REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES} if shared else {}),
        "context_profile": worker.REVIEWED_GENERATION_CONTEXT_PROFILE,
        "context_mode": "rich_full_ast", "record_count": len(records),
        "source_arguments_sha256": hashlib.sha256(arguments_raw).hexdigest(),
        "source_contexts_sha256": expected_source_contexts_sha256,
        "context_records_sha256": expected_context_records_sha256,
        "prepared_records_sha256": hashlib.sha256(_reviewed_wire(records)).hexdigest(),
        "row_commitments": commitments, "tokenizer_contract": contract,
        "max_source_tokens": max_source_tokens,
        "max_context_tokens": context_token_limit,
        "max_context_bytes": worker.REVIEWED_GENERATION_CONTEXT_MAX_BYTES,
        "context_budget_is_inside_source_budget": True,
        "semantic_selection_supported": False, "source_facts_authenticated": False,
        "current_admission_replayed": False, "context_use_permission_verified": False,
        "backend_execution_authorized": False, "target_access_performed": False,
        "training_stage_access_performed": False, "proof_authority": False,
        "corpus_admitted": False}}


# Optional lossless DATA transport. No decoder profile, token budget, admission
# policy or model execution permission changes merely by packing/unpacking it.
REVIEWED_SHARED_CONTEXT_JSON_SCHEMA = "reviewed-lossless-shared-context/v1"
REVIEWED_SHARED_CONTEXT_MAX_WIRE_BYTES = 16 * 1024
REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES = 262144
REVIEWED_SHARED_CONTEXT_MAX_NODES = 4096
REVIEWED_SHARED_CONTEXT_MAX_DEPTH = 64


def _reviewed_shared_context_json_graph(value):
    nodes, seen = [], {}
    def intern(item, depth=0):
        _reviewed_decoder_need(depth <= REVIEWED_SHARED_CONTEXT_MAX_DEPTH, "shared context depth exceeded")
        key = _reviewed_wire(item)
        if key in seen:
            return seen[key]
        if type(item) is dict:
            node = ["object", *[ref for k,v in sorted(item.items())
                               for ref in (intern(k,depth+1),intern(v,depth+1))]]
        elif type(item) is list:
            node = ["array", *[intern(v,depth+1) for v in item]]
        else:
            node = item
        _reviewed_decoder_need(len(nodes) < REVIEWED_SHARED_CONTEXT_MAX_NODES, "shared context node bound exceeded")
        index = len(nodes)
        nodes.append(node)
        seen[key] = index
        return index
    root = intern(value)
    return {"schema":REVIEWED_SHARED_CONTEXT_JSON_SCHEMA,"nodes":nodes,"root":root}


def pack_reviewed_context_json_v1(value):
    """Share complete ordinary JSON structure without normalizing legal data.

    Object keys, ordered arrays, scalar types and UTF-8 values survive. This
    separate DATA schema supplies no review, proof, model or context permission;
    the existing decoder profile continues to reject it by default.
    """
    raw = _reviewed_wire(value)
    _reviewed_decoder_need(len(raw) <= REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES,
                           "complete logical context exceeds expanded byte bound; truncation refused")
    graph = _reviewed_shared_context_json_graph(_reviewed_json(raw))
    _reviewed_decoder_need(len(_reviewed_wire(graph)) <= REVIEWED_SHARED_CONTEXT_MAX_WIRE_BYTES,
                           "complete shared context exceeds encoded byte bound; truncation refused")
    _reviewed_decoder_need(_reviewed_wire(value)==raw,"shared context input changed during packing")
    return graph


def unpack_reviewed_context_json_v1(value):
    """Validate canonical backward references and bound expansion before build.

    Object nodes contain alternating string-key and value references; array
    nodes contain ordered value references. Scalars remain ordinary JSON values.
    Repeated containers reconstruct detached occurrences, not mutable aliases.
    Stored flags/identities cannot grant inference or context-use permission.
    """
    raw = _reviewed_wire(value)
    _reviewed_decoder_need(len(raw) <= REVIEWED_SHARED_CONTEXT_MAX_WIRE_BYTES,"shared context encoded byte bound exceeded")
    packed = _reviewed_json(raw)
    _reviewed_decoder_need(type(packed) is dict and set(packed)=={"schema","nodes","root"}
        and packed["schema"]==REVIEWED_SHARED_CONTEXT_JSON_SCHEMA,"closed shared context DATA schema required")
    nodes, root = packed["nodes"], packed["root"]
    _reviewed_decoder_need(type(nodes) is list and 1 <= len(nodes) <= REVIEWED_SHARED_CONTEXT_MAX_NODES
        and type(root) is int and root==len(nodes)-1,"canonical shared context root/node population required")
    sizes, depths = [], []
    def reference(index,current):
        _reviewed_decoder_need(type(index) is int and 0 <= index < current,
                               "acyclic topologically prior shared context reference required")
        return index
    for current,node in enumerate(nodes):
        if type(node) is list:
            _reviewed_decoder_need(node and type(node[0]) is str and node[0] in {"object","array"},
                                   "closed shared context container required")
            refs = [reference(index,current) for index in node[1:]]
            if node[0]=="array":
                size = 2 + max(0,len(refs)-1) + sum(sizes[index] for index in refs)
            else:
                _reviewed_decoder_need(len(refs)%2==0,"closed shared object key/value pairs required")
                keys=[];size=2+max(0,len(refs)//2-1)
                for key,value_index in zip(refs[::2],refs[1::2],strict=True):
                    _reviewed_decoder_need(type(nodes[key]) is str,"shared object key must name a string scalar")
                    keys.append(nodes[key]);size += sizes[key]+1+sizes[value_index]
                _reviewed_decoder_need(keys==sorted(set(keys)),"distinct canonically ordered shared object keys required")
            depth = 1+max((depths[index] for index in refs),default=0)
        else:
            _reviewed_decoder_need(node is None or type(node) in (str,int,float,bool),"ordinary shared context scalar required")
            size,depth=len(_reviewed_wire(node)),0
        _reviewed_decoder_need(size <= REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES,
                               "shared context expanded byte bound exceeded before materialization")
        _reviewed_decoder_need(depth <= REVIEWED_SHARED_CONTEXT_MAX_DEPTH,"shared context expanded depth exceeded")
        sizes.append(size);depths.append(depth)
    def build(index):
        node=nodes[index]
        if type(node) is not list:return node
        if node[0]=="array":return [build(child) for child in node[1:]]
        refs=node[1:]
        return {nodes[key]:build(child) for key,child in zip(refs[::2],refs[1::2],strict=True)}
    restored=build(root)
    _reviewed_decoder_need(len(_reviewed_wire(restored))==sizes[root],"shared context expanded size differs")
    _reviewed_decoder_need(_reviewed_wire(_reviewed_shared_context_json_graph(restored))==raw,
                           "shared context table is not the canonical reachable representation")
    _reviewed_decoder_need(_reviewed_wire(value)==raw,"shared context input changed during unpacking")
    return restored


REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2 = "reviewed-lossless-shared-context/v2"


def pack_reviewed_context_json_v2(value):
    """Lossless compact container tags, with all v1 bounds and semantics.

    This explicit DATA version changes only container tags (object=0, array=1).
    The original codec owns canonical interning and every expansion bound.
    Neither wire version grants context-use, review or execution permission.
    """
    raw = _reviewed_wire(value)
    graph = pack_reviewed_context_json_v1(value)
    graph["schema"] = REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2
    for node in graph["nodes"]:
        if type(node) is list:
            node[0] = {"object": 0, "array": 1}[node[0]]
    _reviewed_decoder_need(_reviewed_wire(value) == raw, "shorttag input changed during packing")
    return graph


def unpack_reviewed_context_json_v2(value):
    """Translate detached tags and reuse the strict canonical v1 validator.

    Reject boolean/float tag aliases and cross-version payloads explicitly.
    Expansion is checked before building by the existing v1 implementation;
    no new graph, AST or legal interpretation machinery is introduced.
    """
    raw = _reviewed_wire(value)
    _reviewed_decoder_need(len(raw) <= REVIEWED_SHARED_CONTEXT_MAX_WIRE_BYTES,
                           "shared context encoded byte bound exceeded")
    graph = _reviewed_json(raw)
    _reviewed_decoder_need(type(graph) is dict and set(graph) == {"schema", "nodes", "root"}
        and graph["schema"] == REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2,
        "closed shorttag context DATA schema required")
    nodes = graph["nodes"]
    _reviewed_decoder_need(type(nodes) is list and 1 <= len(nodes) <= REVIEWED_SHARED_CONTEXT_MAX_NODES,
                           "canonical shared context node population required")
    for node in nodes:
        if type(node) is list:
            _reviewed_decoder_need(node and type(node[0]) is int and node[0] in (0, 1),
                                   "exact integer shorttag container required")
            node[0] = {0: "object", 1: "array"}[node[0]]
    graph["schema"] = REVIEWED_SHARED_CONTEXT_JSON_SCHEMA
    restored = unpack_reviewed_context_json_v1(graph)
    _reviewed_decoder_need(_reviewed_wire(pack_reviewed_context_json_v2(restored)) == raw,
                           "shorttag table is not the canonical reachable representation")
    _reviewed_decoder_need(_reviewed_wire(value) == raw, "shorttag input changed during unpacking")
    return restored


REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V3 = "reviewed-lossless-shared-context/v3"


def pack_reviewed_context_json_v3(value):
    """Intern repeated object-key layouts over the unchanged strict v2 graph.

    Scalar/array nodes, node IDs, field values and list order stay unchanged.
    Both the encoded v3 and reconstructed v2 wires retain the 16-KiB bound.
    This optional DATA profile grants no context-use or execution authority.
    """
    raw = _reviewed_wire(value)
    graph = pack_reviewed_context_json_v2(value)
    layouts, indices, nodes = [], {}, []
    for node in graph["nodes"]:
        if type(node) is list and node[0] == 0:
            keys = tuple(node[1::2])
            if keys not in indices:
                indices[keys] = len(layouts)
                layouts.append(list(keys))
            nodes.append([0, indices[keys], *node[2::2]])
        else:
            nodes.append(node)
    result = {"schema": REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V3,
              "layouts": layouts, "nodes": nodes, "root": graph["root"]}
    _reviewed_decoder_need(len(_reviewed_wire(result)) <= REVIEWED_SHARED_CONTEXT_MAX_WIRE_BYTES,
                           "key-layout context encoded byte bound exceeded")
    _reviewed_decoder_need(_reviewed_wire(value) == raw, "key-layout input changed during packing")
    return result


def unpack_reviewed_context_json_v3(value):
    """Reconstruct exact v2 DATA, then reuse its full bounded validator.

    Layout IDs follow first object occurrence in the existing node order.
    Re-encoding rejects duplicate, unused, reordered and noncanonical layouts.
    Expansion is bounded by v2 before materializing the complete JSON tree.
    """
    raw = _reviewed_wire(value)
    _reviewed_decoder_need(len(raw) <= REVIEWED_SHARED_CONTEXT_MAX_WIRE_BYTES,
                           "key-layout context encoded byte bound exceeded")
    packed = _reviewed_json(raw)
    _reviewed_decoder_need(type(packed) is dict
        and set(packed) == {"schema", "layouts", "nodes", "root"}
        and packed["schema"] == REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V3,
        "closed key-layout context DATA schema required")
    layouts, offered_nodes = packed["layouts"], packed["nodes"]
    _reviewed_decoder_need(type(offered_nodes) is list
        and 1 <= len(offered_nodes) <= REVIEWED_SHARED_CONTEXT_MAX_NODES
        and type(layouts) is list and len(layouts) <= REVIEWED_SHARED_CONTEXT_MAX_NODES,
        "bounded key-layout and node populations required")
    for keys in layouts:
        _reviewed_decoder_need(type(keys) is list and len(keys) <= REVIEWED_SHARED_CONTEXT_MAX_NODES,
                               "bounded key-layout reference list required")
        _reviewed_decoder_need(all(type(key) is int and 0 <= key < len(offered_nodes)
            and type(offered_nodes[key]) is str for key in keys),
            "exact key-layout references to string scalars required")
    nodes = []
    for node in offered_nodes:
        if type(node) is list:
            _reviewed_decoder_need(node and type(node[0]) is int and node[0] in (0, 1),
                                   "exact integer key-layout container tag required")
            if node[0] == 0:
                _reviewed_decoder_need(len(node) >= 2 and type(node[1]) is int
                    and 0 <= node[1] < len(layouts), "exact in-range key-layout ID required")
                keys, values = layouts[node[1]], node[2:]
                _reviewed_decoder_need(len(keys) == len(values), "complete key-layout value arity required")
                nodes.append([0, *[ref for pair in zip(keys, values, strict=True) for ref in pair]])
            else:
                nodes.append(list(node))
        else:
            nodes.append(node)
    graph = {"schema": REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2,
             "nodes": nodes, "root": packed["root"]}
    _reviewed_decoder_need(len(_reviewed_wire(graph)) <= REVIEWED_SHARED_CONTEXT_MAX_WIRE_BYTES,
                           "reconstructed v2 context encoded byte bound exceeded")
    restored = unpack_reviewed_context_json_v2(graph)
    _reviewed_decoder_need(_reviewed_wire(pack_reviewed_context_json_v3(restored)) == raw,
                           "key-layout table is not the canonical reachable representation")
    _reviewed_decoder_need(_reviewed_wire(value) == raw, "key-layout input changed during unpacking")
    return restored


REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE = "reviewed-mixed-cycle-stage-continuation/v1"
REVIEWED_MIXED_DECODER_CONTINUATION_SCHEMA = "reviewed-mixed-decoder-stage-ancestry/v1"


def prepare_reviewed_mixed_decoder_continuation_v4(registry, *, admission_profile,
        stage_artifact, expected_stage_sha256, parent_training_binding,
        expected_parent_training_binding_sha256, current_training_binding,
        expected_current_training_binding_sha256, split_config,
        expected_split_config_sha256):
    """Replay bounded V4 stage ancestry; never load a numerical checkpoint.

    Both bindings come from the checkpoint/complete-input owners. This helper
    authenticates their staged source history, not historical positive authority
    or removal of retired information from already-trained parameters. The
    current training population still requires the ordinary fresh V4 preparation.
    """
    import hashlib
    from ...optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    from ...optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits

    need = _reviewed_decoder_need
    need(type(admission_profile) is str and admission_profile == REVIEWED_MIXED_ADMISSION_PROFILE,
         "explicit same-domain V4 continuation profile required")
    previous = _reviewed_copy(parent_training_binding, expected_parent_training_binding_sha256)
    current = _reviewed_copy(current_training_binding, expected_current_training_binding_sha256)
    config = _reviewed_copy(split_config, expected_split_config_sha256)
    for binding in (previous, current):
        need(type(binding) is dict
             and binding.get("schema") == "reviewed-decoder-training-input-receipt/v4"
             and binding.get("profile") == REVIEWED_MIXED_DECODER_INPUT_PROFILE
             and binding.get("admission_profile") == admission_profile
             and binding.get("target_codec") == REVIEWED_DECODER_TARGET_CODEC
             and binding.get("source_profile") == REVIEWED_DECODER_SOURCE_PROFILE
             and binding.get("source_context_profile") == REVIEWED_COMPONENT_DECODER_CONTEXT_PROFILE
             and binding.get("current_reviewed_training_permitted") is True
             and type(binding.get("record_count")) is int and 0 < binding["record_count"] <= MAX_REVIEWED_CYCLE_ROWS,
             "same-domain complete V4 training bindings required for continuation")
        for field in ("stage_artifact_sha256", "rows_sha256", "split_manifest_sha256", "history_sha256",
                      "split_config_sha256", "admission_inputs_sha256", "exposure_sha256", "source_contexts_sha256"):
            _reviewed_sha(binding.get(field))
        need(binding["split_config_sha256"] == expected_split_config_sha256,
             "continuation split configuration changed")
    need(set(previous) == set(current),
         "historical continuation binding must retain the complete current receipt field set")
    evolving = {"record_count", "training_record_ids", "row_commitments", "selection_context_sha256",
        "current_admission_custody", "stage_artifact_sha256", "rows_sha256", "split_manifest_sha256",
        "history_sha256", "history_guard", "component_split_guard", "admission_inputs_sha256",
        "admission_assessment_sha256", "exposure_sha256", "source_contexts_sha256",
        "prepared_records_sha256", "current_consumer_receipt"}
    need(all(_reviewed_wire(previous[field]) == _reviewed_wire(current[field])
             for field in set(current) - evolving),
         "continuation complete receipt policy, provenance or producer identity changed")
    need(previous["stage_artifact_sha256"] != current["stage_artifact_sha256"],
         "changed binding requires an explicit successor stage")
    for field in ("tokenizer_contract", "max_source_tokens", "max_target_tokens", "implementation"):
        need(_reviewed_wire(previous.get(field)) == _reviewed_wire(current.get(field)),
             "continuation tokenizer, complete budgets or producer Source changed")
    need(current["stage_artifact_sha256"] == expected_stage_sha256,
         "current continuation binding names a different stage")

    observed, total_bytes, cache = [], 0, {}
    def read_raw(reference):
        nonlocal total_bytes
        reference = _reviewed_copy(reference)
        _reviewed_ref(reference)
        key = _reviewed_wire(reference)
        if key not in cache:
            raw = _reviewed_read(registry, reference)
            total_bytes += len(raw)
            need(total_bytes <= MAX_REVIEWED_STAGE_BYTES,
                 "unsupported continuation artifact byte capacity")
            cache[key] = raw
            observed.append((reference, raw))
        return cache[key]

    def read(reference):
        return _reviewed_json(read_raw(reference))

    selected = _reviewed_copy(stage_artifact)
    need(_reviewed_ref(selected)["sha256"] == expected_stage_sha256,
         "independent continuation stage commitment differs")
    chain, seen = [], set()
    while True:
        need(len(chain) < MAX_REVIEWED_HISTORY and selected["sha256"] not in seen,
             "unsupported continuation ancestry depth or cycle")
        seen.add(selected["sha256"])
        stage = read(selected)
        _reviewed_closed(stage, _reviewed_cycle_fields("v3"), "continuation V4 stage")
        need(_reviewed_cycle_format(stage, admission_version="v3"),
             "continuation ancestry crosses the V4 admission domain")
        _reviewed_lineage(stage["checkpoint_lineage"])
        rows = read(stage["rows_artifact"])
        history = read(stage["history_artifact"])
        manifest = read(stage["split_manifest_artifact"])
        need(type(rows) is list and len(rows) <= MAX_REVIEWED_CYCLE_ROWS,
             "bounded continuation stage rows required")
        for row in rows:
            _reviewed_closed(row, {"id", "unit_id", "source_text", "canonical_ir"}, "continuation historical row")
        kind = stage["transition_kind"]
        need(kind in {"bootstrap", "successor", "withdrawal"}, "unsupported continuation stage kind")
        if kind == "withdrawal":
            need(not rows and stage["consumer_receipt"] == _reviewed_na_consumer()
                 and stage["admission_assessment_artifact"] is None and stage["admission_transport_artifact"] is None,
                 "continuation withdrawal must remain empty and non-positive")
        else:
            need(rows and stage["withdrawal_provenance"] is None,
                 "positive continuation ancestor must retain complete rows")
            _reviewed_component_parent_memberships(stage["consumer_receipt"], rows, consumer, admission_version="v3")
        chain.append((selected, stage, rows, history, manifest))
        if selected["sha256"] == previous["stage_artifact_sha256"]:
            break
        need(kind != "bootstrap" and stage["parent_artifact"] is not None,
             "trained parent stage is not an ancestor of the current population")
        selected = _reviewed_copy(stage["parent_artifact"])

    need(len(chain) >= 2 and chain[0][1]["transition_kind"] == "successor",
         "changed training population requires a positive successor, never withdrawal")
    lineage, implementation = chain[-1][1]["checkpoint_lineage"], chain[-1][1]["implementation"]
    replayed = []
    parent_entry = None
    for reference, stage, rows, history, manifest in reversed(chain):
        need(stage["checkpoint_lineage"] == lineage and stage["implementation"] == implementation,
             "continuation declared lineage or staged producer Source changed")
        withdrawal = stage["transition_kind"] == "withdrawal"
        if parent_entry is None:
            need(not withdrawal, "trained parent binding cannot be a withdrawal")
            replay_history = history
            if history.get("scope_kind") == "declared_genesis":
                need(stage["transition_kind"] == "bootstrap" and history.get("parent_history_artifact") is None
                     and history.get("split_manifests") == [{"manifest": manifest,
                         "sha256": stage["split_manifest_artifact"]["sha256"]}],
                     "continuation ancestor genesis history differs")
                replay_history = dict(history, split_manifests=[])
            guarded, records, guard = _reviewed_history(replay_history, manifest, rows, config, None, splits)
        else:
            parent_ref, parent_stage, parent_rows, parent_history, parent_records = parent_entry
            need(stage["parent_artifact"] == parent_ref
                 and history.get("parent_history_artifact") == parent_stage["history_artifact"],
                 "continuation parent stage/history reference differs")
            guarded, records, guard = _reviewed_history(history, manifest, rows, config,
                parent_history, splits, withdrawal=withdrawal)
            _reviewed_transition(stage["transition"], parent_rows, rows, records, parent_records, registry)
            for kind in ("corrected", "superseded", "revoked"):
                for item in stage["transition"][kind]:
                    read_raw(item["reason_ref"])
            if withdrawal:
                need(not any(stage["transition"][key] for key in ("retained", "added", "corrected")),
                     "continuation withdrawal contains a positive transition")
                _reviewed_withdrawal(stage["withdrawal_provenance"],
                    hashlib.sha256(_reviewed_wire(stage["withdrawal_provenance"])).hexdigest(),
                    parent_ref, stage["transition"], stage["history_artifact"]["sha256"], lineage)
            else:
                retained = set(stage["transition"]["retained"])
                need(not any(row["id"] in parent_records and row["id"] not in retained for row in rows),
                     "unsupported_historical_id_reactivation")
                if retained:
                    need(parent_rows, "withdrawn examples require fresh revision IDs and current admission")
                    old_members = _reviewed_component_parent_memberships(parent_stage["consumer_receipt"],
                        parent_rows, consumer, admission_version="v3")
                    new_members = _reviewed_component_parent_memberships(stage["consumer_receipt"], rows,
                        consumer, admission_version="v3")
                    need(all(old_members[key] == new_members[key] for key in retained),
                         "retained continuation component identity changed")
        need(guarded == history and guard == stage["history_guard"],
             "continuation cumulative source/split history differs from canonical replay")
        parent_entry = (reference, stage, rows, history, records)
        replayed.append({"stage": reference, "transition_kind": stage["transition_kind"],
            "rows_sha256": stage["rows_artifact"]["sha256"], "history_sha256": stage["history_artifact"]["sha256"],
            "split_manifest_sha256": stage["split_manifest_artifact"]["sha256"], "record_count": len(rows)})

    for binding, entry in ((previous, chain[-1]), (current, chain[0])):
        reference, stage, rows, _, _ = entry
        need(binding["record_count"] == len(rows)
             and binding.get("training_record_ids") == [row["id"] for row in rows],
             "continuation binding row population differs")
        need(binding["stage_artifact_sha256"] == reference["sha256"]
             and binding["rows_sha256"] == stage["rows_artifact"]["sha256"]
             and binding["history_sha256"] == stage["history_artifact"]["sha256"]
             and binding["split_manifest_sha256"] == stage["split_manifest_artifact"]["sha256"],
             "continuation binding staged history/population commitments differ")
        need(binding["history_guard"] == stage["history_guard"],
             "continuation binding canonical history guard differs")
        _reviewed_component_parent_memberships(binding["current_consumer_receipt"], rows,
            consumer, admission_version="v3")
        commitments = binding.get("row_commitments")
        need(type(commitments) is list and len(commitments) == len(rows),
             "continuation binding full row commitments are required")
        for offered, row in zip(commitments, rows, strict=True):
            _reviewed_closed(offered, {"id", "unit_id", "source_text_sha256", "source_wire_sha256",
                "canonical_ir_sha256", "source_tokens_sha256", "target_tokens_sha256", "target_identities"},
                "complete continuation row commitment")
            for field in ("source_text_sha256", "source_wire_sha256", "canonical_ir_sha256",
                          "source_tokens_sha256", "target_tokens_sha256"):
                _reviewed_sha(offered[field])
            need(offered["id"] == row["id"] and offered["unit_id"] == row["unit_id"]
                 and offered["source_text_sha256"] == hashlib.sha256(row["source_text"].encode()).hexdigest()
                 and offered["canonical_ir_sha256"] == hashlib.sha256(_reviewed_wire(row["canonical_ir"])).hexdigest()
                 and offered["target_identities"] == _reviewed_decoder_target_identities(row["canonical_ir"]),
                 "continuation binding historical full-target/source commitments differ")
    for reference, raw in observed:
        need(_reviewed_read(registry, reference) == raw,
             "continuation registry artifacts changed during final ancestry closure")
    need(_reviewed_wire(parent_training_binding) == _reviewed_wire(previous)
         and _reviewed_wire(current_training_binding) == _reviewed_wire(current),
         "continuation training bindings changed during ancestry replay")
    return {"schema": REVIEWED_MIXED_DECODER_CONTINUATION_SCHEMA,
        "profile": REVIEWED_MIXED_DECODER_CONTINUATION_PROFILE,
        "parent_training_binding_sha256": expected_parent_training_binding_sha256,
        "current_training_binding_sha256": expected_current_training_binding_sha256,
        "ancestor_stage": chain[-1][0], "successor_stage": chain[0][0],
        "stage_chain": replayed, "staged_artifact_bytes_observed": total_bytes,
        "current_training_authority_supplied_by_complete_preparation": True,
        "historical_positive_authority_replayed": False, "weights_or_optimizer_loaded": False,
        "retired_information_unlearned": False, "qualified": False, "corpus_admitted": False}


# Explicit primitive only: existing preparation, targets, prompts and defaults
# still use complete-reviewed-norm-json/v2. This selector omits one derived AST
# digest from a new model wire; all semantic/custody fields remain mandatory.
REVIEWED_DECODER_DIGEST_OMITTED_TARGET_CODEC = "complete-reviewed-norm-digest-omitted-json/v1"


def _reviewed_decoder_digest_omitted_codec(target_codec):
    _reviewed_decoder_need(
        type(target_codec) is str and target_codec == REVIEWED_DECODER_DIGEST_OMITTED_TARGET_CODEC,
        "explicit digest-omitted target codec required")


def _reviewed_decoder_canonical_formula_target(canonical_ir):
    """Use the maintained full-nine/formula boundary, without legal authority."""
    from ...optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
        evaluate_complete_norm_typed_structure,
    )

    value = _reviewed_copy(canonical_ir)
    try:
        # Both sides are deliberately the offered value: this validates shape
        # and exact AST canonicality, not reference accuracy or source fidelity.
        evaluate_complete_norm_typed_structure([{
            "case_id": "digest-omitted-codec-structural-boundary",
            "reference": value, "candidate": value, "outcome": "complete",
        }])
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ReviewedDecoderInputValidationError(
            "strict canonical full-nine formula target required") from exc
    return value


def encode_reviewed_decoder_digest_omitted_target(canonical_ir, *, target_codec):
    """Project an exact full target; remove only typed_expression.content_digest.

    This opt-in primitive does not alter an input profile, prepare training
    records, select a prompt, authenticate custody, or grant legal meaning.
    """
    _reviewed_decoder_digest_omitted_codec(target_codec)
    value = _reviewed_decoder_canonical_formula_target(canonical_ir)
    expression = value["typed_expression"]
    _reviewed_decoder_need("content_digest" in expression,
                           "canonical expression digest required before projection")
    del expression["content_digest"]
    return _reviewed_wire(value).decode("utf-8")


def assemble_reviewed_decoder_digest_omitted_target(model_wire, *, target_codec):
    """Compute the one omitted digest; refuse every other AST normalization.

    No reference target or dependency resolver is accepted. IDs, binders,
    children, roles and custody are the offered values, never generated or
    repaired. Dependency/context admission remains with its existing owners.
    """
    from ...logic.syntax_core.ast import TypedExpression

    _reviewed_decoder_digest_omitted_codec(target_codec)
    _reviewed_decoder_need(type(model_wire) is str, "ordinary model wire string required")
    value = _reviewed_json(model_wire.encode("utf-8"))
    _reviewed_closed(value, _REVIEWED_DECODER_TARGET_FIELDS, "digest-omitted full target")
    offered = value["typed_expression"]
    _reviewed_decoder_need(type(offered) is dict and "content_digest" not in offered,
                           "model wire must omit content_digest entirely")
    try:
        expression = TypedExpression.from_dict(offered)
        _reviewed_decoder_need(expression.is_formula, "formula expression required")
        assembled = expression.to_dict()
        projected = dict(assembled)
        del projected["content_digest"]
        _reviewed_decoder_need(_reviewed_wire(projected) == _reviewed_wire(offered),
                               "only the computed content_digest may be added")
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ReviewedDecoderInputValidationError(
            "strict digest-omitted formula wire required; no repair allowed") from exc
    value["typed_expression"] = assembled
    # Apply the unchanged strict from_dict/to_dict boundary with the computed
    # digest now present. The original model wire itself remains untouched.
    return _reviewed_decoder_canonical_formula_target(value)


REVIEWED_DIGEST_OMITTED_INPUT_SCHEMA = "reviewed-decoder-digest-omitted-training-inputs/v1"
REVIEWED_DIGEST_OMITTED_INPUT_PROFILE = "complete-reviewed-mixed-digest-omitted-training-inputs/v1"
REVIEWED_DIGEST_OMITTED_INPUT_RECEIPT_SCHEMA = "reviewed-decoder-digest-omitted-training-input-receipt/v1"


def prepare_reviewed_mixed_decoder_digest_omitted_inputs_v1(registry, *, admission_profile, **kwargs):
    """Explicit projected model wire; full semantic rows/current admission remain."""
    _reviewed_decoder_need(type(admission_profile) is str and admission_profile == REVIEWED_MIXED_ADMISSION_PROFILE,
                           "explicit mixed admission V3 required for digest-omitted targets")
    return _prepare_reviewed_decoder_training_inputs(registry, _admission_version="v3",
        _target_codec=REVIEWED_DECODER_DIGEST_OMITTED_TARGET_CODEC, **kwargs)
