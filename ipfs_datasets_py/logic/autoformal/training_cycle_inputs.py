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
        for key, conflicts in resolved.assignment_conflicts.items():
            merged = assignment_conflicts.setdefault(key, [])
            for split in conflicts:
                if split not in merged:
                    merged.append(split)
        for example in resolved.examples:
            key, assignment = example.sample_id, resolved.assignments[example.sample_id]
            _reviewed_need(key not in examples or (examples[key].to_dict() == example.to_dict()
                           and assignments[key] == assignment), "historical example or assignment changed")
            examples[key], assignments[key] = example, assignment
    _reviewed_need(len(examples) <= MAX_REVIEWED_HISTORY
                   and len(examples) * (len(examples) - 1) // 2 <= 131072,
                   "unsupported_historical_guard_capacity")
    records, source_bytes = {}, 0
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
        actual = split_owner.LegalIRSplitExample.from_sample({"id": key, "text": record["source_text"]})
        frozen = examples[key]
        _reviewed_need(record["split_example"] == frozen.to_dict()
                       and record["assignment"] == assignments[key]
                       and frozen.content_hash == actual.content_hash
                       and frozen.token_fingerprint == actual.token_fingerprint,
                       "historical source fingerprint or frozen grouping differs")
        records[key] = record
    _reviewed_need(set(records) == set(examples), "unsupported_historical_source_replay")
    if parent_history is not None:
        for old in parent_history["records"]:
            _reviewed_need(records.get(old["id"]) == old, "parent raw history omitted or changed")
    for row in rows:
        _reviewed_need(row["id"] in records and records[row["id"]]["source_text"] == row["source_text"],
                       "successor source differs from full historical guard")
    clusters = split_owner._near_duplicate_clusters(list(examples.values()), cfg.near_duplicate_jaccard_threshold)
    frozen_union = split_owner.LegalIRSplitManifest(
        examples=tuple(examples.values()), assignments=assignments, config_digest=cfg.digest,
        protected_splits=cfg.protected_splits, assignment_conflicts=assignment_conflicts,
        metadata={"guard_only": True, "assignments_recomputed": False, "duplicate_view": "frozen"})
    recomputed_union = split_owner.LegalIRSplitManifest(
        examples=tuple(example.with_near_duplicate_key(clusters[key]) for key, example in examples.items()),
        assignments=assignments, config_digest=cfg.digest, protected_splits=cfg.protected_splits,
        assignment_conflicts=assignment_conflicts,
        metadata={"guard_only": True, "assignments_recomputed": False, "duplicate_view": "recomputed"})
    # Recomputed token relations add a check; they cannot replace committed
    # duplicate groups or assignment conflicts. Keep only actual violations
    # returned by the two canonical guards, in the canonical result type.
    results = tuple(split_owner.validate_legal_ir_eval_splits(view)
                    for view in (frozen_union, recomputed_union))
    violations = {_reviewed_wire(item.to_dict()): item
                  for guard in results for item in guard.violations}
    result = split_owner.LegalIRSplitGuardResult(
        passed=all(guard.passed for guard in results),
        violations=tuple(violations[key] for key in sorted(violations)),
        blocked_operations=tuple(sorted({operation for guard in results for operation in guard.blocked_operations})))
    if not withdrawal:
        if not result.passed:
            raise split_owner.LegalIRSplitLeakageError("LegalIR split leakage blocks reviewed-cycle positive use", result)
        for view in (frozen_union, recomputed_union):
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


def stage_reviewed_cycle_inputs(registry, *, transition_kind, parent_artifact, expected_parent_sha256,
        successor_rows, expected_successor_rows_sha256, successor_binding, split_manifest,
        admission_inputs, exposure_records, transition, expected_transition_sha256,
        history, expected_history_sha256, split_config, expected_split_config_sha256,
        checkpoint_lineage, expected_checkpoint_lineage_sha256, output_directory, allow_bootstrap=False,
        withdrawal_provenance=None, expected_withdrawal_provenance_sha256=None):
    """Stage a reviewed typed-example transition through the real v2 consumer.

    The returned ArtifactRef identifies provenance/library metadata, never a
    TrainingJobSpec or model-input export. Whole assessments, byte evidence and
    held-out historical sources are separate artifacts, not training callback
    inputs. Their visibility is no claim that arbitrary readers are exposure-safe.
    The caller supplies independent source/trust/history/artifact identities;
    this function does not authenticate their issuer or global completeness.
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
    from . import legal_norm_content_adjudication_v1 as admission

    _reviewed_need(type(allow_bootstrap) is bool and type(transition_kind) is str
                   and transition_kind in {"bootstrap", "successor", "withdrawal"},
                   "explicit reviewed transition kind required")
    withdrawal = transition_kind == "withdrawal"
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
    changes = _reviewed_copy(transition, expected_transition_sha256)
    history_copy = _reviewed_copy(history, expected_history_sha256)
    config = _reviewed_copy(split_config, expected_split_config_sha256)
    lineage = _reviewed_copy(checkpoint_lineage, expected_checkpoint_lineage_sha256)
    manifest, exposure = _reviewed_copy(split_manifest), _reviewed_copy(exposure_records)
    original_json_inputs = (successor_rows, split_manifest, exposure_records, transition, history,
                            split_config, checkpoint_lineage, parent_artifact, withdrawal_provenance)
    frozen_json_inputs = tuple(_reviewed_wire(value) for value in original_json_inputs)
    admission_sha = None if withdrawal else consumer.reviewed_admission_inputs_sha256(admission_inputs)
    _reviewed_lineage(lineage)
    parent, parent_rows, previous_history, parent_records = None, [], None, {}
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
        _reviewed_closed(parent, _REVIEWED_ARTIFACT_FIELDS, "reviewed cycle parent artifact")
        _reviewed_need(parent["schema"] == REVIEWED_CYCLE_SCHEMA and parent["profile"] == REVIEWED_CYCLE_PROFILE
                       and parent["compatibility"] == _REVIEWED_COMPATIBILITY,
                       "legacy or numerical snapshots cannot supply a reviewed cycle parent")
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
            _reviewed_closed(prior, _REVIEWED_ARTIFACT_FIELDS, "withdrawal predecessor")
            prior_rows = _reviewed_json(_reviewed_read(registry, prior["rows_artifact"]))
            _reviewed_need(prior["schema"] == REVIEWED_CYCLE_SCHEMA and prior["profile"] == REVIEWED_CYCLE_PROFILE
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
                           and parent["consumer_receipt"].get("schema") == consumer.REVIEWED_SCHEMA
                           and parent["consumer_receipt"].get("status") == "ready"
                           and parent["consumer_receipt"].get("operation") == "training"
                           and parent["consumer_receipt"].get("row_count") == len(parent_rows)
                           and parent["consumer_receipt"].get("input_sha256s", {}).get("rows") == parent["rows_artifact"]["sha256"]
                           and parent["history_guard"]["status"] == "passed"
                           and parent["history_guard"]["result"].get("passed") is True,
                           "historical positive parent must retain its actual ready profile")
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
    admission_skeleton = skeleton(admission_inputs, [])
    _reviewed_wire(admission_skeleton)
    _reviewed_need(sum(len(raw) for _, raw in byte_values) <= MAX_REVIEWED_STAGE_BYTES,
                   "unsupported_reviewed_staging_capacity")
    directory = Path(output_directory)
    _reviewed_need(directory.is_absolute() and directory.parent.resolve(strict=True) == directory.parent
                   and directory.parent.is_dir() and not directory.exists() and not directory.is_symlink(),
                   "fresh ordinary output directory in existing canonical parent required")

    modules = (sys.modules[__name__], consumer, admission, splits)
    def implementation():
        return {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                for module in modules}
    producers = implementation()
    def current():
        _reviewed_need(tuple(_reviewed_wire(value) for value in original_json_inputs) == frozen_json_inputs
                       and (withdrawal or consumer.reviewed_admission_inputs_sha256(admission_inputs) == admission_sha)
                       and implementation() == producers, "reviewed staging inputs or named producers changed")
        if withdrawal:
            return _reviewed_na_consumer(), None
        receipt = consumer.validate_reviewed_source_span_consumer_binding_v2(successor_binding, successor_rows,
            split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records)
        assessment = admission.assess_reviewed_norm_admission_v2(**admission_inputs)
        _reviewed_need(receipt["status"] == "ready" and receipt["operation"] == "training"
                       and receipt["row_count"] == len(rows)
                       and receipt["admission_assessment_sha256"] == admission.norm_content_adjudication_sha256(assessment)
                       and assessment["semantic_use_eligible"] is True and not assessment["blockers"],
                       "fresh complete current reviewed admission required")
        return receipt, assessment
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
        artifact = {"schema": REVIEWED_CYCLE_SCHEMA, "profile": REVIEWED_CYCLE_PROFILE,
            "transition_kind": transition_kind, "parent_artifact": parent_reference,
            "rows_artifact": put(_reviewed_wire(consumed_rows)), "consumer_receipt": current_receipt,
            "admission_assessment_artifact": None if withdrawal else put(_reviewed_wire(current_assessment)),
            "admission_transport_artifact": transport_ref, "split_manifest_artifact": put(_reviewed_wire(manifest)),
            "history_artifact": put(_reviewed_wire(guard_history)), "transition": changes,
            "checkpoint_lineage": lineage, "implementation": producers, "compatibility": dict(_REVIEWED_COMPATIBILITY),
            "history_guard": history_guard, "withdrawal_provenance": withdrawal_record}
        _reviewed_need(current() == (receipt, assessment), "reviewed staging state changed after payload writes")
        result = put(_reviewed_wire(artifact))
        _reviewed_need(current() == (receipt, assessment), "reviewed staging state changed after metadata write")
        return result

    if withdrawal:
        return stage([])
    return consumer.consume_reviewed_source_span_binding_v2(successor_binding, successor_rows,
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
    return {"module": function.__module__, "qualname": function.__qualname__, "kind": "python_code",
        "code_sha256": hashlib.sha256(marshal.dumps(code)).hexdigest(),
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


def _reviewed_decoder_source_target_wires(rows, contexts, selection_context):
    """Reject unsupported many-target transport for identical complete inputs.

    This current-batch relation check does not adjudicate meaning, turn custody
    differences into semantic contradictions or reconstruct historical caller
    inputs from target labels. Current admission offers no multi-target policy.
    """
    seen, wires = {}, []
    for row, context in zip(rows, contexts, strict=True):
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
        target_json = _reviewed_wire(target).decode("utf-8")
        _reviewed_decoder_need(source_wire not in seen or seen[source_wire] == target_json,
                       "unsupported conflicting full-target relation for identical complete source/selection input; no admitted multi-target policy")
        seen[source_wire] = target_json
        wires.append((source_wire, target_json))
    return wires


def prepare_reviewed_decoder_training_inputs(registry, *, stage_artifact, expected_stage_sha256,
        current_admission_inputs, expected_admission_inputs_sha256,
        exposure_records, expected_exposure_sha256, source_contexts,
        expected_source_contexts_sha256, split_config, expected_split_config_sha256,
        tokenizer, max_source_tokens, max_target_tokens, allow_fictional_fixture=False):
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

    Tokenizer assets and external clock/registry freshness retain their existing
    owners. Full canonical pipeline/configuration and ordinary implementation
    identities are checked alongside encode/decode and BOS/EOS/vocabulary.
    Re-call this function at the independently guarded training boundary; its
    return is data and provenance, not an execution capability.
    """
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
    from . import legal_norm_content_adjudication_v1 as admission

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
    _reviewed_closed(stage, _REVIEWED_ARTIFACT_FIELDS, "reviewed decoder stage artifact")
    _reviewed_decoder_need(stage["schema"] == REVIEWED_CYCLE_SCHEMA
                   and stage["profile"] == REVIEWED_CYCLE_PROFILE
                   and stage["compatibility"] == _REVIEWED_COMPATIBILITY
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
        _reviewed_closed(parent, _REVIEWED_ARTIFACT_FIELDS, "decoder historical parent")
        _reviewed_decoder_need(parent["schema"] == REVIEWED_CYCLE_SCHEMA and parent["profile"] == REVIEWED_CYCLE_PROFILE
                       and parent["compatibility"] == _REVIEWED_COMPATIBILITY,
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

    _reviewed_closed(contexts, {"profile", "selection_context", "rows"},
                     "separately supplied source-known selection contexts")
    _reviewed_decoder_need(contexts["profile"] == REVIEWED_DECODER_SOURCE_PROFILE
                   and type(contexts["rows"]) is list and len(contexts["rows"]) == len(rows),
                   "explicit complete source-known selection context v2 required")
    selection = contexts["selection_context"]
    _reviewed_closed(selection, {"schema", "interpretation_id", "selection_mode"},
                     "caller-known interpretation selection without reference labels")
    _reviewed_decoder_need(selection["schema"] == "caller-known-interpretation-selection/v1"
                   and selection["selection_mode"] == "identifier_only"
                   and type(selection["interpretation_id"]) is str
                   and 0 < len(selection["interpretation_id"]) <= 512,
                   "explicit caller-known identifier_only selection required; meaning-policy route UNPROVIDED/unsupported")
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

    arguments = dict(expected_rows_sha256=stage["rows_artifact"]["sha256"], split_manifest=manifest,
        expected_split_manifest_sha256=stage["split_manifest_artifact"]["sha256"],
        admission_inputs=admission_copy, expected_admission_inputs_sha256=admission_sha,
        exposure_records=exposure, expected_exposure_sha256=expected_exposure_sha256,
        operation="training", allow_fictional_fixture=allow_fictional_fixture)
    binding = consumer.prepare_reviewed_source_span_consumer_binding_v2(rows, **arguments)
    receipt = consumer.validate_reviewed_source_span_consumer_binding_v2(binding, rows,
        split_manifest=manifest, admission_inputs=admission_copy, exposure_records=exposure)
    assessment = admission.assess_reviewed_norm_admission_v2(**admission_copy)
    _reviewed_decoder_need(receipt["status"] == "ready" and receipt["operation"] == "training"
                   and receipt["row_count"] == len(rows)
                   and receipt["admission_assessment_sha256"] == admission.norm_content_adjudication_sha256(assessment)
                   and assessment["semantic_use_eligible"] is True and not assessment["blockers"],
                   "fresh current reviewed training admission required")
    fixture = assessment["provenance_kind"] == "fictional_fixture"
    _reviewed_decoder_need(type(assessment["training_mask"]) is int
                   and (fixture and allow_fictional_fixture and assessment["training_mask"] == 0
                        or not fixture and assessment["training_mask"] == 1),
                   "explicit fictional smoke scope or eligible statutory training mask required")
    # This precedes every tokenizer callback and any return to the backend.
    # A held-out norm linked by the complete definition cannot be hidden merely
    # by excluding that norm from the active training-row list.
    component_guard = _reviewed_decoder_component_split_guard(assessment, records)
    wires = _reviewed_decoder_source_target_wires(rows, contexts["rows"], selection)
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
                "canonical_ir_sha256": hashlib.sha256(target_json.encode("utf-8")).hexdigest(),
                "source_tokens_sha256": hashlib.sha256(_reviewed_wire(source_ids)).hexdigest(),
                "target_tokens_sha256": hashlib.sha256(_reviewed_wire(target_ids)).hexdigest(),
                "target_identities": _reviewed_decoder_target_identities(row["canonical_ir"])})
        # All rows and both complete output budgets have passed before a caller
        # can obtain this data. No model restore/fit callback exists in this API.
        _reviewed_decoder_need(_reviewed_decoder_tokenizer_contract(tokenizer) == contract,
                       "decoder tokenizer contract changed during preparation")
        current = consumer.validate_reviewed_source_span_consumer_binding_v2(binding, rows,
            split_manifest=manifest, admission_inputs=admission_copy, exposure_records=exposure)
        _reviewed_decoder_need(current == receipt, "current reviewed decoder admission changed during tokenization")
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
        current = consumer.validate_reviewed_source_span_consumer_binding_v2(binding, rows,
            split_manifest=manifest, admission_inputs=admission_copy, exposure_records=exposure)
        _reviewed_decoder_need(current == receipt, "current reviewed decoder admission changed during final closure")
        _reviewed_decoder_need(tuple(_reviewed_wire(value) for value in json_inputs) == frozen_inputs
                       and consumer.reviewed_admission_inputs_sha256(current_admission_inputs) == admission_sha
                       and consumer.reviewed_admission_inputs_sha256(admission_copy) == admission_sha
                       and implementation() == producers,
                       "reviewed decoder preparation inputs, admission or named producers changed during final closure")
        _reviewed_decoder_need(_reviewed_decoder_source_target_wires(rows, contexts["rows"], selection) == wires,
                       "caller-known full input/target relation changed during preparation")
        proof = {"schema": "reviewed-decoder-training-input-receipt/v2",
            "profile": REVIEWED_DECODER_INPUT_PROFILE, "target_codec": REVIEWED_DECODER_TARGET_CODEC,
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
            "current_admission_custody": {
                "registry_sha256": admission_copy["expected_registry_sha256"],
                "policy_sha256": admission_copy["expected_policy_sha256"],
                "reviews_sha256": admission_copy["expected_reviews_sha256"],
                "dependency_manifest_sha256": admission_copy["preparation"]["subject"]["dependency_manifest_sha256"],
                "review_subject_full_unit_records_sha256": admission_copy["preparation"]["subject"]["ast_sha256"],
                "review_subject_ast_label_is_pure_typed_expression": False},
            "training_record_ids": [row["id"] for row in prepared], "row_commitments": commitments,
            "stage_artifact_sha256": expected_stage_sha256, "rows_sha256": stage["rows_artifact"]["sha256"],
            "split_manifest_sha256": stage["split_manifest_artifact"]["sha256"],
            "history_sha256": stage["history_artifact"]["sha256"], "history_guard": guard,
            "component_split_guard": component_guard,
            "split_config_sha256": expected_split_config_sha256, "admission_inputs_sha256": admission_sha,
            "admission_assessment_sha256": receipt["admission_assessment_sha256"],
            "exposure_sha256": expected_exposure_sha256, "source_contexts_sha256": expected_source_contexts_sha256,
            "prepared_records_sha256": hashlib.sha256(_reviewed_wire(prepared)).hexdigest(),
            "tokenizer_contract": contract, "max_source_tokens": max_source_tokens,
            "max_target_tokens": max_target_tokens, "implementation": producers,
            "provenance_kind": assessment["provenance_kind"], "fixture_only": fixture,
            "training_mask": assessment["training_mask"], "production_training_eligible": not fixture,
            "current_reviewed_training_permitted": True, "current_consumer_receipt": current,
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
        result = {"schema": REVIEWED_DECODER_INPUT_SCHEMA, "records": prepared, "receipt": proof}
        result["prepared_sha256"] = hashlib.sha256(_reviewed_wire(result)).hexdigest()
        return result

    return consumer.consume_reviewed_source_span_binding_v2(binding, rows, split_manifest=manifest,
        admission_inputs=admission_copy, exposure_records=exposure, consumer=prepare)
