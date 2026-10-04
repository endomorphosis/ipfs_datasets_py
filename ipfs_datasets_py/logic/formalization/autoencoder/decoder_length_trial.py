"""Preparation-only, per-lineage decoder length trials with no numerical imports.

A ready plan admits declared metadata, not the authenticity of its inputs,
checkpoint, migration, teacher, source semantics or native validation. Numeric
owners must independently authenticate those bindings before execution.
"""
from copy import deepcopy
import hashlib
import json
import re

SCHEMA = "decoder-length-trial/v1"
DEFAULT_LIMITS = (64, 128, 256, 512, 1024)
LANES = {"legacy_8d": 8, "source_384d": 384, "multilingual_768d": 768}
LINEAGE_FIELDS = {"lane_id", "domain_id", "dimension", "runtime_id", "checkpoint_sha256",
    "representation_id", "encoder_context_tokens", "head_id", "codec", "codec_sha256",
    "bos_token_id", "eos_token_id", "pad_token_id", "codec_origin", "codec_fit_training_ids_sha256",
    "inherited_max_target_tokens", "owner_max_target_tokens"}
ROW_FIELDS = {"id", "group_id", "split", "source_sha256", "normalized_source_sha256",
    "target_sha256", "codec_sha256", "token_ids", "input_status", "input_sha256", "teacher_replay"}
MIGRATION_FIELDS = {"schema", "parent_checkpoint_sha256", "parent_runtime_id", "new_runtime_id",
    "old_max_target_tokens", "new_max_target_tokens", "codec_sha256", "encoder_context_tokens",
    "inherited_tensor_sha256", "migrated_inherited_tensor_sha256", "new_checkpoint_sha256"}
SCOPE_FIELDS = {"scope_id", "teacher_checkpoint_sha256", "codec_sha256", "split", "head_id",
    "distribution", "eligible_training_ids_sha256"}
REPLAY_FIELDS = {"scope_id", "teacher_checkpoint_sha256", "codec_sha256", "head_id", "distribution",
    "reference_prefix_sha256", "teacher_logits_sha256", "token_mask"}
FALSE = {key: False for key in ("training_executed", "optimizer_created", "numerical_model_loaded",
    "encoder_executed", "native_validation_executed", "distillation_executed", "teacher_qualified",
    "production_kd_eligible", "checkpoint_authenticated", "migration_authenticated", "source_semantics_verified",
    "proof_authority", "admitted", "qualified", "outputs_truncated", "logits_combined", "fresh_holdout", "convergence_proven")}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == fields, "closed " + label + " required")


def _sha(value, label):
    _require(type(value) is str and _SHA.fullmatch(value), "lowercase SHA256 required: " + label)


def _name(value, label):
    _require(type(value) is str and 0 < len(value) <= 512 and value.strip() == value
             and value.isprintable(), "bounded identity required: " + label)


def _lineage(value):
    _closed(value, LINEAGE_FIELDS, "lineage")
    _require(type(value["lane_id"]) is str and value["lane_id"] in LANES and type(value["dimension"]) is int
             and LANES[value["lane_id"]] == value["dimension"], "lane dimension differs")
    _require(value["domain_id"] in ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir"), "unknown domain")
    for key in ("runtime_id", "representation_id", "head_id"):
        _name(value[key], key)
    for key in ("checkpoint_sha256", "codec_sha256"):
        _sha(value[key], key)
    context = value["encoder_context_tokens"]
    _require(context is None and value["lane_id"] == "legacy_8d" or
             type(context) is int and 1 <= context <= 8192, "fixed encoder context required")
    codec = value["codec"]
    _require(type(codec) is dict and type(codec.get("target_vocabulary")) is list, "original codec payload required")
    vocabulary = codec["target_vocabulary"]
    _require(3 <= len(vocabulary) <= 4096 and all(type(t) is str and 0 < len(t) <= 4096 for t in vocabulary)
             and len(set(vocabulary)) == len(vocabulary), "bounded unique codec vocabulary required")
    _require(digest(codec) == value["codec_sha256"], "codec digest differs")
    special = [value[key] for key in ("bos_token_id", "eos_token_id", "pad_token_id")]
    _require(all(type(i) is int and 0 <= i < len(vocabulary) for i in special)
             and len(set(special)) == 3, "distinct reserved token IDs required")
    inherited, maximum = value["inherited_max_target_tokens"], value["owner_max_target_tokens"]
    _require(type(inherited) is int and type(maximum) is int and 4 <= inherited <= maximum <= 1024,
             "bounded inherited and owner output ceilings required")
    _require(value["codec_origin"] in ("inherited", "train_only"), "explicit codec origin required")
    if value["codec_origin"] == "inherited":
        _require(value["codec_fit_training_ids_sha256"] is None, "inherited codec cannot claim a new fit")
    else:
        _sha(value["codec_fit_training_ids_sha256"], "training codec fit")


def split_manifest(rows):
    """Copy declared immutable partition identities; does not infer grouping."""
    fields = ("id", "group_id", "split", "source_sha256", "normalized_source_sha256", "target_sha256")
    return [{key: row[key] for key in fields} for row in rows]


def _rows(rows, lineage, manifest):
    _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded row list required")
    seen = set()
    partitions = {key: {} for key in ("group_id", "source_sha256", "normalized_source_sha256", "input_sha256") }
    vocabulary = lineage["codec"]["target_vocabulary"]
    bos, eos, pad = (lineage[key] for key in ("bos_token_id", "eos_token_id", "pad_token_id"))
    for row in rows:
        _closed(row, ROW_FIELDS, "row")
        for key in ("id", "group_id"):
            _name(row[key], key)
        _require(row["id"] not in seen, "duplicate row ID")
        seen.add(row["id"])
        _require(row["split"] in ("train", "validation", "test"), "unknown split")
        for key in ("source_sha256", "normalized_source_sha256", "target_sha256", "codec_sha256"):
            _sha(row[key], key)
        _require(row["input_status"] in ("ready", "missing_native", "quarantined"), "explicit input status required")
        if row["input_status"] == "ready":
            _sha(row["input_sha256"], "ready source representation")
        else:
            _require(row["input_sha256"] is None, "unready row cannot claim a usable input")
        for key, assignment in partitions.items():
            if key == "input_sha256" and row[key] is None:
                continue
            old = assignment.setdefault(row[key], row["split"])
            _require(old == row["split"], "cross-split " + key + " leakage")
        tokens = row["token_ids"]
        _require(type(tokens) is list and 3 <= len(tokens) <= 16384
                 and all(type(t) is int and 0 <= t < len(vocabulary) for t in tokens), "bounded original target tokens required")
        _require(tokens[0] == bos and tokens[-1] == eos and all(t not in (bos, eos, pad) for t in tokens[1:-1]),
                 "complete target with unique BOS/final EOS and no padding required")
        _require(row["codec_sha256"] == lineage["codec_sha256"], "row codec differs")
    _require(type(manifest) is list and digest(manifest) == digest(split_manifest(rows)), "immutable split manifest differs")
    training = [row for row in rows if row["split"] == "train"]
    _require(training, "at least one training row required")
    if lineage["codec_origin"] == "train_only":
        _require(lineage["codec_fit_training_ids_sha256"] == digest(sorted(row["id"] for row in training)),
                 "codec fit is not bound to exactly the training split")
        used = {t for row in training for t in row["token_ids"]} | {pad}
        _require(used == set(range(len(vocabulary))), "train-only codec contains tokens absent from training")
    return training


def _migration(value, lineage):
    if value is None:
        return lineage["inherited_max_target_tokens"]
    _closed(value, MIGRATION_FIELDS, "length migration")
    _require(value["schema"] == "explicit-decoder-length-migration/v1", "migration schema differs")
    for key in ("parent_checkpoint_sha256", "new_checkpoint_sha256", "codec_sha256", "inherited_tensor_sha256",
                "migrated_inherited_tensor_sha256"):
        _sha(value[key], key)
    _name(value["new_runtime_id"], "new runtime")
    _require(value["parent_checkpoint_sha256"] == lineage["checkpoint_sha256"]
             and value["parent_runtime_id"] == lineage["runtime_id"]
             and value["new_runtime_id"] != lineage["runtime_id"]
             and value["new_checkpoint_sha256"] != lineage["checkpoint_sha256"], "explicit distinct migration ancestry required")
    _require(value["codec_sha256"] == lineage["codec_sha256"]
             and value["encoder_context_tokens"] == lineage["encoder_context_tokens"], "migration changed codec or encoder context")
    _require(type(value["old_max_target_tokens"]) is int and value["old_max_target_tokens"] == lineage["inherited_max_target_tokens"]
             and type(value["new_max_target_tokens"]) is int
             and value["old_max_target_tokens"] < value["new_max_target_tokens"] <= lineage["owner_max_target_tokens"],
             "migration limits differ from parent or owner bounds")
    _require(value["inherited_tensor_sha256"] == value["migrated_inherited_tensor_sha256"], "migration inherited tensor preservation differs")
    return value["new_max_target_tokens"]


def _scope(value, lineage, training):
    if value is None:
        return
    _closed(value, SCOPE_FIELDS, "teacher scope")
    _name(value["scope_id"], "teacher scope")
    for key in ("teacher_checkpoint_sha256", "codec_sha256", "eligible_training_ids_sha256"):
        _sha(value[key], key)
    _require(value["split"] == "train" and value["head_id"] == lineage["head_id"]
             and value["codec_sha256"] == lineage["codec_sha256"], "teacher scope head/codec/training split differs")
    _require(value["distribution"] in ("raw", "grammar_masked"), "explicit teacher distribution required")
    _require(value["eligible_training_ids_sha256"] == digest(sorted(row["id"] for row in training)),
             "teacher scope must bind exact training IDs")


def _replay_blockers(row, lineage, scope):
    if scope is None:
        return ["teacher_scope_missing"]
    replay = row["teacher_replay"]
    if replay is None:
        return ["teacher_replay_missing"]
    _closed(replay, REPLAY_FIELDS, "teacher replay")
    for key in ("teacher_checkpoint_sha256", "codec_sha256", "reference_prefix_sha256", "teacher_logits_sha256"):
        _sha(replay[key], key)
    _require(all(replay[key] == scope[key] for key in ("scope_id", "teacher_checkpoint_sha256", "codec_sha256", "head_id", "distribution")),
             "teacher replay scope differs")
    _require(replay["reference_prefix_sha256"] == digest(row["token_ids"][:-1]), "teacher prefix differs from complete original reference")
    mask = replay["token_mask"]
    _require(type(mask) is list and len(mask) == len(row["token_ids"]) - 1
             and all(type(v) is bool for v in mask), "exact boolean replay token mask required")
    return [] if any(mask) else ["teacher_scope_excludes_all_tokens"]


def prepare_trial(lineage, rows, *, output_limits=DEFAULT_LIMITS, objective="reference_ce",
                  split_manifest, teacher_scope=None, migration=None):
    """Keep every requested cap/row; admit complete targets without truncation.

    Diagnostic KL uses T=1, separately from greedy generation temperature zero.
    It binds replay declarations only; numerical callers must authenticate actual
    logits and scope. Test references are counted for fit diagnostics but never
    enter fitting, normalization, vocabulary fitting, or checkpoint selection.
    """
    lineage, rows, manifest, scope, migration = deepcopy((lineage, rows, split_manifest, teacher_scope, migration))
    _require(len(json.dumps([lineage, rows, manifest, scope, migration], allow_nan=False).encode()) <= 16 * 1024 * 1024,
             "bounded plan inputs required")
    _lineage(lineage)
    training = _rows(rows, lineage, manifest)
    _require(type(output_limits) in (list, tuple) and 1 <= len(output_limits) <= 16
             and all(type(v) is int and 4 <= v <= 1024 for v in output_limits)
             and len(set(output_limits)) == len(output_limits), "unique bounded output limits required")
    _require(objective in ("reference_ce", "diagnostic_kd"), "reference or explicitly diagnostic KD objective required")
    if objective == "reference_ce":
        _require(scope is None, "reference-only control cannot carry a distillation scope")
    _scope(scope, lineage, training)
    effective = _migration(migration, lineage)
    trials = []
    for limit in output_limits:
        observations = []
        for row in rows:
            reasons = []
            if limit > lineage["owner_max_target_tokens"]:
                reasons.append("above_owner_output_limit")
            elif limit > effective:
                reasons.append("explicit_versioned_length_migration_required")
            if len(row["token_ids"]) > limit:
                reasons.append("complete_target_exceeds_output_limit")
            if row["input_status"] != "ready":
                reasons.append(row["input_status"])
            if objective == "diagnostic_kd" and row["split"] == "train":
                reasons.extend(_replay_blockers(row, lineage, scope))
            observations.append({"id": row["id"], "split": row["split"], "group_id": row["group_id"],
                "target_tokens_including_bos_eos": len(row["token_ids"]), "status": "blocked" if reasons else "ready",
                "reasons": reasons, "used_for_fit": not reasons and row["split"] == "train",
                "used_for_checkpoint_selection": False, "target_truncated": False})
        ready = sum(row["status"] == "ready" for row in observations)
        eligible = sum(row["used_for_fit"] for row in observations)
        train_count = len(training)
        validation = [row for row in observations if row["split"] == "validation"]
        validation_ready = sum(row["status"] == "ready" for row in validation)
        trials.append({"output_limit": limit, "max_new_tokens": limit - 1, "selected_row_count": len(rows),
            "ready_row_count": ready, "blocked_row_count": len(rows) - ready,
            "training_row_count": train_count, "eligible_training_row_count": eligible,
            "validation_row_count": len(validation), "ready_validation_row_count": validation_ready,
            "convergence_evaluation_ready": eligible == train_count and bool(validation) and validation_ready == len(validation),
            "status": "ready" if ready == len(rows) else "partial" if ready else "blocked",
            "training_admission": "ready" if eligible == train_count else "blocked",
            "requires_migration_authentication": migration is not None and limit > lineage["inherited_max_target_tokens"],
            "rows": observations})
    plan = {"schema": SCHEMA, "lineage": lineage, "lineage_sha256": digest(lineage),
        "source_rows_sha256": digest(rows), "split_manifest": manifest, "split_manifest_sha256": digest(manifest),
        "teacher_scope": scope, "migration": migration, "objective": objective,
        "generation_temperature": 0, "distillation_temperature": 1. if objective == "diagnostic_kd" else None,
        "encoder_context_tokens": lineage["encoder_context_tokens"], "encoder_context_changed": False,
        "requested_output_limits": list(output_limits), "requested_trial_count": len(output_limits),
        "ready_trial_count": sum(t["status"] == "ready" for t in trials), "trials": trials,
        "scope": "metadata_preparation_only_requires_external_owner_input_and_replay_authentication",
        "test_used_for_fit_or_selection": False, **FALSE}
    plan["plan_sha256"] = digest(plan)
    return plan


def validate_trial(plan, lineage, rows, **options):
    expected = prepare_trial(lineage, rows, **options)
    _require(type(plan) is dict and digest(plan) == digest(expected), "trial plan differs from original complete inputs")
    return deepcopy(expected)
