"""Join inherited decoder prefixes to exact cached multilingual source receipts.

The whole original 180/60 Legal archive and two original synthetic 8D sources
are audited before any selected replay row is joined. Missing native inputs
remain source-only embedding tasks. No encoder or tensor library is imported,
and receipt consistency cannot authenticate an earlier producer's execution.
Callers authenticate original and saved file bytes before this admission.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path


SCHEMA = "gte-decoder-native-batch/v1"
MAX_TASKS = 4096
MAX_PLAN_BYTES = 24 * 1024 * 1024
FLAGS = {
    "archived_inputs_reused": True,
    "source_split_memberships_changed": False,
    "native768_inputs_joined": True,
    "encoder_inference_executed": False,
    "embeddings_generated": False,
    "source_vectors_relabelled": False,
    "producer_execution_authenticated": False,
    "archive_authenticity_verified": False,
    "teacher_qualified": False,
    "production_kd_eligible": False,
    "training_executed": False,
    "distillation_executed": False,
    "proof_authority": False,
}
_HEAD_FIELDS = {"input_dimension", "donor_input_dimension", "codec_sha256", "target_vocabulary",
    "selected_row_count", "ready_row_count", "missing_row_count", "quarantined_row_count", "status",
    "rows", "missing_rows", "quarantined_rows", "rows_sha256"}
_FIELDS = {"schema", "status", "initialization_representation_id", "batch_sha256", "replay_sha256",
    "donor_pins", "profile_id", "asset_manifest_sha256", "audit_rows", "legacy8_inputs",
    "source_manifest_bindings", "audit", "task_manifest", "cache_reuse", "heads", "selected_row_count",
    "ready_row_count", "missing_row_count", "quarantined_row_count", "plan_sha256", *FLAGS}
_MANIFEST_FIELDS = {"primary_training_manifest_sha256", "primary_validation_manifest_sha256",
    "legacy8_training_manifest_sha256", "legacy8_inputs_sha256"}


def _helper(name):
    spec = importlib.util.spec_from_file_location("_gte_native_batch_" + name,
                                                Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load native decoder batch dependency")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BATCH = _helper("gte_decoder_transfer_batch")
_REPLAY = _helper("gte_decoder_transfer_replay")
_CORPUS = _helper("gte_multilingual_corpus")
_CACHE = _helper("gte_embedding_reuse")
PROFILE_ID = _CORPUS.PROFILE_ID
_AUDIT = _CORPUS._AUDIT
SOURCE_REPRESENTATION_ID = _BATCH._TEACHER.SOURCE_REPRESENTATION_ID


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError("bounded finite native batch JSON required") from exc


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _same(left, right, message):
    _require(_raw(left) == _raw(right), message)


def _source_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manifest(rows):
    return [{"id": row["id"], "source_sha256": _source_sha(row["source_text"]),
        "normalized_source_sha256": _source_sha(" ".join(row["source_text"].casefold().split())),
        "embedding_sha256": _BATCH.digest(row["embedding"]),
        "target_sha256": _BATCH.digest(row["reference_target"])} for row in rows]


def _primary_archive(archive, split, count, vocabulary):
    _BATCH._closed(archive, {"rows", "source_embeddings"}, "original primary " + split + " archive")
    original = archive["rows"]
    _require(type(original) is list and len(original) == count,
             "complete original primary " + split + " archive required")
    _require(_AUDIT._json_value(archive["source_embeddings"]), "finite original embedding provenance required")
    provenance = archive["source_embeddings"]
    expected = {"model_id": "thenlper/gte-small", "revision": "17e1f347d17fe144873b1201da91788898c639cd",
        "dimension": 384, "dtype": "float32", "normalized": True, "truncated": False}
    _require(type(provenance) is dict and all(type(provenance.get(key)) is type(value)
             and provenance[key] == value for key, value in expected.items()),
             "original 384D archive representation declaration differs")
    canonical, seen = [], set()
    for row in original:
        _BATCH._closed(row, _BATCH._PRIMARY_ROW_FIELDS, "original primary cached row")
        for name in ("id", "source_text", "group_id"):
            _BATCH._text(row[name], "original " + name)
        _require(row["id"] not in seen and row["split"] == split and row["proof_authority"] is False
                 and row["source_semantics_verified"] is False, "original primary row split or authority differs")
        seen.add(row["id"])
        _BATCH._vector(row["embedding"], 384, unit=True)
        _BATCH._rule(row["target"])
        _BATCH._encode(row["target"], vocabulary, "primary384")
        _require(_source_sha(row["source_text"]) == row["source_sha256"]
                 and _BATCH.digest(row["embedding"]) == row["embedding_sha256"],
                 "original primary cached source or vector digest differs")
        _BATCH._sha(row["embedding_token_ids_sha256"], "original token IDs")
        _require(_AUDIT._json_value(row["reference_metadata"]), "finite original reference metadata required")
        canonical.append({"id": row["id"], "domain_id": "legal_ir", "document_id": row["group_id"],
            "group_id": row["group_id"], "split": split, "source_text": row["source_text"],
            "embedding": deepcopy(row["embedding"]), "reference_target": deepcopy(row["target"]),
            "target_origin": "authored", "source_language": "en", "evaluation_role": "development"})
    return canonical


def _legacy_sources(inputs):
    _require(type(inputs) is list and len(inputs) == 2, "both original legacy8 cached inputs required")
    canonical, training, seen = [], [], set()
    for cached in inputs:
        _BATCH._closed(cached, _BATCH._INPUT_FIELDS, "original legacy8 cached schema input")
        for name in ("sample_id", "text"):
            _BATCH._text(cached[name], "original legacy8 " + name)
        _require(cached["sample_id"] not in seen and cached["embedding_model"] == "test:explicit-synthetic-vector-not-semantic"
                 and cached["normalized_text"] == cached["text"] and cached["source"] == "us_code",
                 "original legacy8 cached identity or source profile differs")
        seen.add(cached["sample_id"])
        vector = cached["embedding_vector"]
        _BATCH._vector(vector, 8)
        modal = cached["modal_ir"]
        _require(type(modal) is dict and modal.get("document_id") == cached["sample_id"]
                 and modal.get("normalized_text") == cached["text"] and type(modal.get("formulas")) is list
                 and len(modal["formulas"]) == 1, "original legacy8 modal source binding differs")
        formula = modal["formulas"][0]
        _require(type(formula) is dict and type(formula.get("operator")) is dict
                 and type(formula.get("predicate")) is dict, "original legacy8 modal formula required")
        predicate = formula["predicate"]
        arguments = predicate.get("arguments")
        _require(type(arguments) is list and len(arguments) == 2 and formula.get("conditions") == []
                 and formula.get("exceptions") == [], "original legacy8 reference facets differ")
        reference = {"rules": [{"modality": formula["operator"].get("symbol"), "actor": arguments[0],
            "action": predicate.get("name"), "object": arguments[1], "conditions": [], "exceptions": [], "temporal": []}]}
        _BATCH._rule(reference)
        latent = []
        for index in range(0, 8, 2):
            left, right = float(vector[index]), float(vector[index + 1])
            latent.extend([.02 * left + .1 * right, .02 * right - .1 * left])
        training.append({"id": cached["sample_id"], "source_text": cached["text"], "latent": latent,
                         "embedding": deepcopy(vector), "canonical_ir": reference})
        canonical.append({"id": cached["sample_id"], "domain_id": "legal_ir", "document_id": modal["document_id"],
            "group_id": "legacy8:original:" + cached["sample_id"], "split": "train", "source_text": cached["text"],
            "embedding": None, "reference_target": reference, "target_origin": "authored", "source_language": "en",
            "evaluation_role": "development"})
    return canonical, training


def _validate_audit_rows(rows, legacy_inputs, batch, initialization):
    _require(type(rows) is list and len(rows) == 242, "complete 242-row original source audit required")
    primary_train, primary_validation = [], []
    for row in rows[:240]:
        _BATCH._closed(row, _AUDIT.ROW_FIELDS, "canonical original primary audit row")
        for name in ("id", "source_text", "document_id", "group_id"):
            _BATCH._text(row[name], "canonical original " + name)
        _require(row["domain_id"] == "legal_ir" and row["document_id"] == row["group_id"]
                 and row["target_origin"] == "authored" and row["source_language"] == "en"
                 and row["evaluation_role"] == "development", "original primary audit metadata differs")
        _BATCH._vector(row["embedding"], 384, unit=True)
        _BATCH._rule(row["reference_target"])
        _BATCH._encode(row["reference_target"], initialization["primary"]["codec"]["target_vocabulary"], "primary384")
        if row["split"] == "train":
            primary_train.append(row)
        elif row["split"] == "validation":
            primary_validation.append(row)
        else:
            raise ValueError("test or canary data cannot enter native decoder preparation")
    _require(len(primary_train) == 180 and len(primary_validation) == 60
             and rows[:180] == primary_train and rows[180:240] == primary_validation,
             "original full train/validation row order or counts differ")
    for cohort in (primary_train, primary_validation):
        _require(len({row["id"] for row in cohort}) == len(cohort), "duplicate original split IDs")
    legacy_rows, legacy_training = _legacy_sources(legacy_inputs)
    _same(rows[240:], legacy_rows, "canonical legacy8 audit rows differ from original caches")
    training_digest = _BATCH.digest(_manifest(primary_train))
    legacy_digest = _BATCH.digest(legacy_training)
    _require(training_digest == batch["heads"]["primary384"]["original_training_manifest_sha256"]
             and legacy_digest == batch["heads"]["legacy8"]["original_training_manifest_sha256"],
             "whole original donor training manifests differ from saved replay inputs")
    manifests = {"primary_training_manifest_sha256": training_digest,
        "primary_validation_manifest_sha256": _BATCH.digest(_manifest(primary_validation)),
        "legacy8_training_manifest_sha256": legacy_digest, "legacy8_inputs_sha256": digest(legacy_inputs)}
    originals = {"primary384": [{"id": row["id"], "source_text": row["source_text"], "embedding": row["embedding"],
        "target": row["reference_target"], "audit_row": row} for row in primary_train],
        "legacy8": [{**row, "audit_row": canonical} for row, canonical in zip(legacy_training, legacy_rows)]}
    for name, original in originals.items():
        selected = sorted(original, key=lambda row: row["id"])[:batch["max_rows_per_head"]]
        expected = [_BATCH._batch_row(row, row["embedding"] if name == "primary384" else row["latent"],
            row["target"] if name == "primary384" else row["canonical_ir"],
            batch["heads"][name]["target_vocabulary"], name) for row in selected]
        _same(expected, batch["heads"][name]["rows"], "saved selected decoder rows differ from original full archives")
        originals[name] = selected
    return manifests, originals


def _status(selected, ready):
    return "ready" if ready == selected else "partial" if ready else "unavailable"


def _heads(batch, replay, originals, task_manifest, cache):
    tasks = {task["id"]: task for task in task_manifest["tasks"]}
    rejected = {row["row_sha256"]: row for row in task_manifest["rejected_rows"]}
    receipts = {receipt["id"]: receipt for receipt in cache["reused_receipts"]}
    heads = {}
    for name in ("primary384", "legacy8"):
        ready, missing, quarantined = [], [], []
        for selected, batch_row, replay_row in zip(originals[name], batch["heads"][name]["rows"], replay["heads"][name]["rows"]):
            task_id = _CORPUS._task_id("legal_ir", selected["id"])
            rejected_row = rejected.get(_AUDIT._digest(selected["audit_row"]))
            binding = {"id": selected["id"], "source_sha256": batch_row["source_sha256"],
                       "batch_row_sha256": batch_row["row_sha256"], "embedding_task_id": task_id}
            if rejected_row is not None:
                quarantined.append({**binding, "reasons": deepcopy(rejected_row["reasons"]),
                    "audit_row_sha256": rejected_row["row_sha256"], "component_sha256": rejected_row["component_sha256"]})
                continue
            _require(task_id in tasks, "selected source is absent from both admitted and rejected task inventories")
            task = tasks[task_id]
            _require(task["source_sha256"] == batch_row["source_sha256"]
                     and task["metadata"]["split"] == "train"
                     and task["metadata"]["reference_target_sha256"] == _AUDIT._digest(selected["audit_row"]["reference_target"]),
                     "native source task differs from original selected training reference")
            if task_id not in receipts:
                missing.append(binding)
                continue
            row = {**deepcopy(batch_row), "embedding_task": deepcopy(task), "native_receipt": deepcopy(receipts[task_id]),
                "teacher_logits": deepcopy(replay_row["teacher_logits"]),
                "teacher_logits_sha256": replay_row["teacher_logits_sha256"],
                "teacher_replay_row_sha256": _REPLAY.digest(replay_row)}
            row["native_row_sha256"] = digest(row)
            ready.append(row)
        selected_count = batch["heads"][name]["selected_row_count"]
        heads[name] = {"input_dimension": 768, "donor_input_dimension": batch["heads"][name]["input_dimension"],
            "codec_sha256": batch["heads"][name]["codec_sha256"],
            "target_vocabulary": deepcopy(batch["heads"][name]["target_vocabulary"]),
            "selected_row_count": selected_count, "ready_row_count": len(ready), "missing_row_count": len(missing),
            "quarantined_row_count": len(quarantined), "status": _status(selected_count, len(ready)),
            "rows": ready, "missing_rows": missing, "quarantined_rows": quarantined, "rows_sha256": digest(ready)}
    return heads


def _assemble(initialization, batch, replay, pins, rows, legacy_inputs, receipts, asset):
    _BATCH._sha(asset, "selected native asset manifest")
    manifests, originals = _validate_audit_rows(rows, legacy_inputs, batch, initialization)
    audit = _AUDIT.audit_transfer_rows(rows, dimension=384, vector_space_id=SOURCE_REPRESENTATION_ID, max_rows=MAX_TASKS)
    tasks = _CORPUS.prepare_embedding_tasks(rows, audit, max_rows=MAX_TASKS)
    cache = _CACHE.prepare_cached_embedding_reuse(tasks, receipts,
        expected_asset_manifest_sha256=asset, max_rows=MAX_TASKS)
    heads = _heads(batch, replay, originals, tasks, cache)
    counts = {key: sum(head[key] for head in heads.values()) for key in (
        "selected_row_count", "ready_row_count", "missing_row_count", "quarantined_row_count")}
    result = {"schema": SCHEMA, "status": _status(counts["selected_row_count"], counts["ready_row_count"]),
        "initialization_representation_id": initialization["representation_id"], "batch_sha256": batch["batch_sha256"],
        "replay_sha256": _REPLAY.digest(replay), "donor_pins": deepcopy(pins), "profile_id": PROFILE_ID,
        "asset_manifest_sha256": asset, "audit_rows": deepcopy(rows), "legacy8_inputs": deepcopy(legacy_inputs),
        "source_manifest_bindings": manifests, "audit": audit, "task_manifest": tasks,
        "cache_reuse": cache, "heads": heads, **counts, **FLAGS}
    result["native768_inputs_joined"] = bool(counts["ready_row_count"])
    result["plan_sha256"] = digest(result)
    _require(len(_raw(result)) <= MAX_PLAN_BYTES, "native decoder batch exceeds 24 MiB")
    return result


def _admit_saved(initialization, batch, replay, pins):
    _BATCH.inspect_decoder_transfer_batch(batch, initialization, expected_donor_pins=pins)
    _REPLAY.inspect_decoder_transfer_replay(replay, batch, initialization=initialization, expected_donor_pins=pins)


def prepare_decoder_native_batch(initialization, batch, replay, *, expected_donor_pins,
                                 primary_training_archive, primary_validation_archive, legacy8_inputs,
                                 receipts_768, expected_asset_manifest_sha256):
    """Audit complete original inputs and join only exact cached native receipts."""
    _admit_saved(initialization, batch, replay, expected_donor_pins)
    vocabulary = initialization["primary"]["codec"]["target_vocabulary"]
    training = _primary_archive(primary_training_archive, "train", 180, vocabulary)
    validation = _primary_archive(primary_validation_archive, "validation", 60, vocabulary)
    _same(primary_training_archive["source_embeddings"], primary_validation_archive["source_embeddings"],
          "original training and validation embedding provenance differs")
    legacy_rows, _ = _legacy_sources(legacy8_inputs)
    result = _assemble(initialization, batch, replay, expected_donor_pins,
        training + validation + legacy_rows, legacy8_inputs, receipts_768, expected_asset_manifest_sha256)
    inspect_decoder_native_batch(result, initialization, batch, replay, expected_donor_pins=expected_donor_pins)
    return result


def inspect_decoder_native_batch(plan, initialization, batch, replay, *, expected_donor_pins):
    """Reconstruct strict plan content; external file authenticity stays separate."""
    _admit_saved(initialization, batch, replay, expected_donor_pins)
    _BATCH._closed(plan, _FIELDS, "native decoder batch")
    _require(len(_raw(plan)) <= MAX_PLAN_BYTES, "native decoder batch exceeds 24 MiB")
    _BATCH._closed(plan["source_manifest_bindings"], _MANIFEST_FIELDS, "original source manifest bindings")
    _BATCH._closed(plan["heads"], {"primary384", "legacy8"}, "native decoder heads")
    for head in plan["heads"].values():
        _BATCH._closed(head, _HEAD_FIELDS, "native decoder head")
    _require(type(plan["cache_reuse"]) is dict and type(plan["cache_reuse"].get("reused_receipts")) is list,
             "native decoder cache reuse receipt list required")
    recomputed = _assemble(initialization, batch, replay, expected_donor_pins, plan["audit_rows"],
        plan["legacy8_inputs"], plan["cache_reuse"]["reused_receipts"], plan["asset_manifest_sha256"])
    _same(plan, recomputed, "native decoder batch does not exactly match reconstructed audit/task/cache/replay bindings")
    return {"schema": "gte-decoder-native-batch-inspection/v1", "status": plan["status"],
        "plan_sha256": plan["plan_sha256"], "selected_row_count": plan["selected_row_count"],
        "ready_row_count": plan["ready_row_count"], "missing_row_count": plan["missing_row_count"],
        "quarantined_row_count": plan["quarantined_row_count"],
        "full_task_count": plan["cache_reuse"]["task_count"],
        "full_cached_receipt_count": plan["cache_reuse"]["cached_receipt_count"],
        "full_missing_task_count": plan["cache_reuse"]["missing_task_count"],
        **{key: plan[key] for key in FLAGS}}


__all__ = ["SCHEMA", "PROFILE_ID", "MAX_TASKS", "MAX_PLAN_BYTES", "prepare_decoder_native_batch",
           "inspect_decoder_native_batch", "digest"]
