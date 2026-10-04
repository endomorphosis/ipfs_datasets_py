"""Prepare source-only 768D embedding tasks and bind declared producer receipts.

No tokenizer, encoder, model weights, target converter, or trainer is loaded here.
The existing 384D corpus audit is recomputed in full before task preparation.
Receipts are checked for content consistency; authentic model execution and
tokenization remain the responsibility of the pinned embedding worker.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re


PROFILE_ID = (
    "Alibaba-NLP/gte-multilingual-base@9bbca17d9273fd0d03d5725c7a4b0f6b45142062:"
    "code=Alibaba-NLP/new-impl@40ced75c3017eb27626c9d4ea981bde21a2662f4:"
    "d768:pool=cls:norm=l2:cpu:float32:tokens8192:reject_overlength:v1"
)
TASK_SCHEMA = "gte-multilingual-embedding-tasks/v1"
BINDING_SCHEMA = "gte-multilingual-embedding-binding/v1"
RECEIPT_SCHEMA = "gte-multilingual-embedding-receipt/v1"
DIMENSION = 768
MAX_TOKENS = 8192
UNIT_NORM_TOLERANCE = 1e-4
_MAX_ROWS = 100000
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TASK_FIELDS = frozenset(("id", "source_text", "source_sha256", "metadata"))
_METADATA_FIELDS = frozenset((
    "source_id", "domain_id", "document_id", "group_id", "split", "target_origin",
    "source_language", "evaluation_role", "reference_target_sha256", "row_sha256",
    "component_sha256",
))
_RECEIPT_FIELDS = frozenset((
    "schema", "id", "source_sha256", "profile_id", "dimension", "embedding",
    "token_count_including_special_tokens", "token_input_sha256", "truncated",
    "normalized", "asset_manifest_sha256",
))


def _load_audit_module():
    # File loading also works in minimal environments without package import hooks.
    path = Path(__file__).with_name("gte_transfer_corpus.py")
    spec = importlib.util.spec_from_file_location("_gte_multilingual_transfer_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the transfer corpus auditor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_AUDIT = _load_audit_module()


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _finite_json(value):
    return _AUDIT._json_value(value)


def _sha256(value):
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and _finite_json(value)


def _source_sha256(source):
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _task_id(domain_id, source_id):
    return "gte768:" + domain_id + ":" + _digest({
        "domain_id": domain_id, "source_id": source_id,
    })


def _bounded_rows(rows, max_rows, *, label):
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    if isinstance(rows, (str, bytes, dict)):
        raise ValueError(label + " must be an iterable of objects")
    try:
        iterator = iter(rows)
    except TypeError as error:
        raise ValueError(label + " must be an iterable of objects") from error
    result = []
    for value in iterator:
        if len(result) >= max_rows:
            raise ValueError(label + " exceeds max_rows")
        result.append(value)
    return result


def prepare_embedding_tasks(rows, corpus_audit, *, max_rows=100000):
    """Make embedding tasks from a fully matching, recomputed 384D audit.

    Quarantined and deduplicated rows remain excluded, with explicit reasons.
    Every retained source can be embedded, including unlabeled sources and rows
    without a 384D vector. Existing split, group and target-origin declarations
    are retained as metadata. Reference target content and 384D vectors are never
    copied into tasks. Only ``source_text`` may enter the neural embedding worker.
    """
    data = _bounded_rows(rows, max_rows, label="rows")
    if not isinstance(corpus_audit, dict) or not _finite_json(corpus_audit):
        raise ValueError("corpus_audit must be a finite JSON audit object")
    profile = corpus_audit.get("profile")
    if (corpus_audit.get("schema") != _AUDIT.SCHEMA or not isinstance(profile, dict)
            or type(profile.get("dimension")) is not int or profile["dimension"] != 384):
        raise ValueError("corpus_audit must describe the complete 384D transfer corpus")
    recomputed = _AUDIT.audit_transfer_rows(
        data, dimension=384, vector_space_id=profile.get("vector_space_id"),
        max_rows=max_rows,
    )
    if _raw(recomputed) != _raw(corpus_audit):
        raise ValueError("corpus_audit does not exactly match the supplied complete rows")

    source_rows = {}
    for row in data:
        if isinstance(row, dict) and _finite_json(row):
            row_sha256 = _AUDIT._json_digest(row)
            if row_sha256 is not None:
                source_rows[row_sha256] = row
    tasks = []
    rejected = []
    reason_counts = Counter()
    for binding in recomputed["rows"]:
        reasons = list(binding["quarantine_reasons"])
        if binding["deduplicated"]:
            reasons.append("deduplicated")
        original = source_rows.get(binding["row_sha256"])
        source = original.get("source_text") if isinstance(original, dict) else None
        if not _text(source) or binding["source_sha256"] is None:
            reasons.append("missing_source")
        if reasons:
            reasons = sorted(set(reasons))
            rejected.append({
                "source_id": binding["id"], "domain_id": binding["domain_id"],
                "split": binding["split"], "row_sha256": binding["row_sha256"],
                "source_sha256": binding["source_sha256"],
                "component_sha256": binding["component_sha256"],
                "duplicate_of": binding["duplicate_of"], "reasons": reasons,
            })
            reason_counts.update(reasons)
            continue
        metadata = {field: binding[field] for field in _METADATA_FIELDS - {"source_id"}}
        metadata["source_id"] = binding["id"]
        tasks.append({
            "id": _task_id(binding["domain_id"], binding["id"]),
            "source_text": source, "source_sha256": binding["source_sha256"],
            "metadata": metadata,
        })
    tasks.sort(key=lambda item: item["id"])
    rejected.sort(key=_raw)
    if len({item["id"] for item in tasks}) != len(tasks):
        raise ValueError("audited task identifiers are not unique")
    return {
        "schema": TASK_SCHEMA, "profile_id": PROFILE_ID,
        "corpus_inventory_sha256": recomputed["inventory_sha256"],
        "tasks_sha256": _digest(tasks), "input_row_count": len(data),
        "task_count": len(tasks), "rejected_row_count": len(rejected),
        "status": "ready" if not rejected else "partial",
        "rejection_reason_counts": dict(sorted(reason_counts.items())),
        "tasks": tasks, "rejected_rows": rejected,
        "neural_input_fields": ["source_text"],
        "embeddings_generated": False, "split_memberships_changed": False,
        "reference_targets_exported": False, "target_semantics_verified": False,
        "vectors_producer_verified": False,
    }


def _validate_tasks(tasks_or_manifest):
    manifest = tasks_or_manifest if isinstance(tasks_or_manifest, dict) else None
    if manifest is not None:
        if (not _finite_json(manifest) or manifest.get("schema") != TASK_SCHEMA
                or manifest.get("profile_id") != PROFILE_ID
                or not _sha256(manifest.get("corpus_inventory_sha256"))):
            raise ValueError("task manifest has an invalid schema, profile, or corpus binding")
        tasks = _bounded_rows(manifest.get("tasks"), _MAX_ROWS, label="tasks")
        if (type(manifest.get("task_count")) is not int
                or manifest["task_count"] != len(tasks)
                or manifest.get("tasks_sha256") != _digest(tasks)):
            raise ValueError("task manifest count or tasks_sha256 does not match")
    else:
        tasks = _bounded_rows(tasks_or_manifest, _MAX_ROWS, label="tasks")
    identifiers = set()
    for task in tasks:
        if (not isinstance(task, dict) or set(task) != _TASK_FIELDS
                or not _finite_json(task)):
            raise ValueError("each task must be a closed finite JSON task object")
        metadata = task["metadata"]
        if (not isinstance(metadata, dict) or set(metadata) != _METADATA_FIELDS
                or not _text(metadata["source_id"])
                or metadata["domain_id"] not in _AUDIT.DOMAINS
                or metadata["split"] not in _AUDIT.SPLITS
                or metadata["target_origin"] not in _AUDIT.TARGET_ORIGINS
                or metadata["evaluation_role"] not in ("development", "sealed")):
            raise ValueError("task metadata has invalid or unexpected fields")
        for field in ("document_id", "group_id", "source_language"):
            if not _text(metadata[field]):
                raise ValueError("task metadata requires " + field)
        for field in ("row_sha256", "component_sha256"):
            if not _sha256(metadata[field]):
                raise ValueError("task metadata has invalid " + field)
        target_sha = metadata["reference_target_sha256"]
        if target_sha is not None and not _sha256(target_sha):
            raise ValueError("task metadata has invalid reference target binding")
        if ((target_sha is None) != (metadata["target_origin"] == "unlabeled")
                or (metadata["split"] in ("train", "validation")
                    and metadata["evaluation_role"] == "sealed")):
            raise ValueError("task metadata has inconsistent target or evaluation declarations")
        if (not _text(task["source_text"])
                or task["source_sha256"] != _source_sha256(task["source_text"])
                or task["id"] != _task_id(metadata["domain_id"], metadata["source_id"])):
            raise ValueError("task source or scoped identifier binding does not match")
        if task["id"] in identifiers:
            raise ValueError("duplicate task identifier")
        identifiers.add(task["id"])
    tasks.sort(key=lambda item: item["id"])
    # Copy JSON payloads so later caller mutations cannot change the returned binding.
    return json.loads(_raw(tasks)), manifest


def _validate_receipt(receipt, task):
    if (not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS
            or not _finite_json(receipt)):
        raise ValueError("receipt must be a closed finite JSON receipt object")
    if (receipt["schema"] != RECEIPT_SCHEMA or receipt["profile_id"] != PROFILE_ID
            or type(receipt["dimension"]) is not int or receipt["dimension"] != DIMENSION):
        raise ValueError("receipt has the wrong schema, profile, or dimension")
    if (receipt["id"] != task["id"] or receipt["source_sha256"] != task["source_sha256"]):
        raise ValueError("receipt source identity does not match its task")
    for field in ("source_sha256", "token_input_sha256", "asset_manifest_sha256"):
        if not _sha256(receipt[field]):
            raise ValueError("receipt has an invalid " + field)
    if (type(receipt["token_count_including_special_tokens"]) is not int
            or not 1 <= receipt["token_count_including_special_tokens"] <= MAX_TOKENS):
        raise ValueError("receipt token count must include special tokens and be within 8192")
    if receipt["truncated"] is not False or receipt["normalized"] is not True:
        raise ValueError("receipt must assert no truncation and L2 normalization")
    embedding = receipt["embedding"]
    if not isinstance(embedding, list) or len(embedding) != DIMENSION:
        raise ValueError("receipt embedding must contain exactly 768 values")
    vector = []
    for value in embedding:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("receipt embedding values must be finite numbers")
        try:
            number = float(value)
        except (ValueError, OverflowError) as error:
            raise ValueError("receipt embedding values must be finite numbers") from error
        if not math.isfinite(number):
            raise ValueError("receipt embedding values must be finite numbers")
        vector.append(number)
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
        raise ValueError("receipt embedding is not unit normalized within 1e-4")
    return vector


def bind_embedding_receipts(tasks_or_manifest, receipts):
    """Bind strict 768D receipts to exact source tasks without changing targets.

    Missing receipts produce an explicit incomplete coverage report. Malformed,
    duplicate, unexpected, source-mismatched or mixed-asset receipts raise
    ``ValueError``; no partially validated binding is returned. SHA declarations
    do not independently prove encoder execution, tokens, or asset authenticity.
    """
    tasks, manifest = _validate_tasks(tasks_or_manifest)
    tasks_by_id = {task["id"]: task for task in tasks}
    data = _bounded_rows(receipts, _MAX_ROWS, label="receipts")
    seen = set()
    asset_hashes = set()
    bound_rows = []
    for receipt in data:
        if not isinstance(receipt, dict) or not isinstance(receipt.get("id"), str):
            raise ValueError("receipt requires a task identifier")
        identifier = receipt["id"]
        if identifier not in tasks_by_id:
            raise ValueError("receipt has an unexpected task identifier")
        if identifier in seen:
            raise ValueError("duplicate embedding receipt identifier")
        task = tasks_by_id[identifier]
        vector = _validate_receipt(receipt, task)
        seen.add(identifier)
        asset_hashes.add(receipt["asset_manifest_sha256"])
        if len(asset_hashes) > 1:
            raise ValueError("receipts cannot mix asset manifests in one binding")
        receipt_metadata = {key: value for key, value in receipt.items()
                            if key not in ("embedding", "id", "source_sha256")}
        receipt_metadata["receipt_sha256"] = _digest(receipt)
        bound_rows.append({**task, "embedding": vector,
                           "embedding_receipt": receipt_metadata})
    bound_rows.sort(key=lambda item: item["id"])
    missing = sorted(set(tasks_by_id) - seen)
    return {
        "schema": BINDING_SCHEMA, "profile_id": PROFILE_ID,
        "tasks_sha256": _digest(tasks),
        "corpus_inventory_sha256": manifest["corpus_inventory_sha256"] if manifest else None,
        "binding_sha256": _digest(bound_rows),
        "status": "incomplete" if missing else "complete",
        "task_count": len(tasks), "accepted_count": len(bound_rows),
        "rejected_count": len(missing), "missing_receipt_ids": missing,
        "asset_manifest_sha256": next(iter(asset_hashes), None),
        "bound_rows": bound_rows, "split_memberships_changed": False,
        "reference_targets_exported": False, "target_semantics_verified": False,
        "vectors_producer_verified": False, "tokenization_producer_verified": False,
    }
