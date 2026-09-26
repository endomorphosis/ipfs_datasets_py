"""Canonical preparation requests for existing registered v8 campaign jobs.

This module validates bounded ordinary JSON only. It performs no filesystem,
registry, model, scheduler or network access. Owner preparation must compare the
request with the original plan and complete jobs and verify current paths and
artifacts. Encoding is neither execution authorization nor native qualification.

Resource amounts apply to each selected worker independently; max_workers never
replaces resource admission. Job configuration remains in its exact artifact.
"""
from __future__ import annotations

import json
import math
from pathlib import PurePosixPath
import re

SCHEMA = "autoencoder-campaign-training-request-v1"
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_BATCHES = 64
MAX_PLAN_BYTES = 4 * 1024 * 1024
MAX_PLAN_BATCHES = 128
MAX_TOTAL_JOB_BYTES = 64 * 1024 * 1024
MAX_CAMPAIGN_METADATA_BYTES = 64 * 1024 * 1024
MAX_PATH_BYTES = 4096
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 32768
MAX_INTEGER = 2**63 - 1
MAX_STORAGE_BYTES = 50_000_000_000
MAX_MEMORY_MB = 2**31 - 1
MAX_CPU_SLOTS = 32
MAX_WORKERS = 4
MAX_SECONDS = 86400
ROOT_NAMES = frozenset(("source_inventory", "source_partitions", "embedding_receipt_set"))
PARENT_POLICIES = frozenset(("common_fixed_parent", "explicit_registered_parents"))
OWNER_FIELDS = frozenset(("database_path", "artifact_root"))
BATCH_FIELDS = frozenset(("plan_ordinal", "batch_id", "run_id", "job_id", "job_spec_artifact",
    "job_spec_sha256", "base_version_id", "output_directory", "target_snapshot_id",
    "target_snapshot_artifact", "arrow_feature_weights_artifact", "training_config_sha256",
    "autoencoder_config_sha256"))
RESOURCE_POLICY_FIELDS = frozenset(("ledger_path", "roots", "storage_bytes", "memory_mb", "cpu_slots"))
EXECUTION_POLICY_FIELDS = frozenset(("max_workers", "lease_seconds", "poll_seconds", "timeout_seconds",
    "defer_target_hydration_gc", "reduce_native_targets", "sparse_checkpoint_policy"))
SPARSE_POLICY_FIELDS = frozenset(("max_depth", "max_patch_fraction"))
FALSE_FIELDS = frozenset(("admitted", "formalized", "source_authority_authenticated",
    "global_holdout_verified", "training_dispatched", "native_execution_verified",
    "promotion_performed", "publication_performed"))
REQUEST_FIELDS = frozenset(("schema_version", "owner", "plan_artifact", "worker_id", "output_root",
    "variant_id", "variant_manifest_sha256", "source_campaign_binding", "parent_policy", "batches",
    "resource_policy", "execution_policy", *FALSE_FIELDS))
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}\Z")
_WORKER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}\Z")


class CampaignTrainingRequestError(ValueError):
    """A request is malformed, noncanonical or outside its declared bounds."""


def _require(condition, message):
    if not condition:
        raise CampaignTrainingRequestError(message)


def _ordinary(value):
    """Reject custom containers, recursion and oversized values before encoding."""
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _require(depth <= MAX_JSON_DEPTH and nodes <= MAX_JSON_NODES, "request JSON exceeds structural bound")
        kind = type(item)
        if kind is dict:
            _require(all(type(key) is str for key in item), "request JSON keys must be ordinary strings")
            _require(2 * len(item) <= MAX_JSON_NODES - nodes, "request JSON exceeds structural bound")
            pending.extend((key, depth + 1) for key in item)
            pending.extend((entry, depth + 1) for entry in item.values())
        elif kind is list:
            _require(len(item) <= MAX_JSON_NODES - nodes, "request JSON exceeds structural bound")
            pending.extend((entry, depth + 1) for entry in item)
        elif kind is str:
            _require(len(item) <= MAX_REQUEST_BYTES, "request JSON string exceeds byte bound")
            try:
                encoded = item.encode("utf-8")
            except UnicodeError as exc:
                raise CampaignTrainingRequestError("request JSON string is not valid Unicode") from exc
            _require(len(encoded) <= MAX_REQUEST_BYTES, "request JSON string exceeds byte bound")
        elif kind is int:
            _require(-MAX_INTEGER <= item <= MAX_INTEGER, "request JSON integer exceeds bound")
        elif kind is float:
            _require(math.isfinite(item) and abs(item) <= MAX_INTEGER, "request JSON number must be finite and bounded")
        else:
            _require(item is None or kind is bool, "request values must be ordinary JSON")


def _fields(value, expected, name):
    _require(type(value) is dict and set(value) == expected, f"unexpected {name} fields")


def _integer(value, low, high, name):
    _require(type(value) is int and low <= value <= high, f"invalid {name}")


def _number(value, high, name):
    _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= high, f"invalid {name}")


def _digest(value, name):
    _require(type(value) is str and _HASH.fullmatch(value) is not None, f"invalid {name}")


def _identifier(value, name, pattern=_TOKEN):
    _require(type(value) is str and pattern.fullmatch(value) is not None, f"invalid {name}")


def _path(value, name):
    _require(type(value) is str and 0 < len(value.encode("utf-8")) <= MAX_PATH_BYTES
             and not any(ord(char) < 32 or ord(char) == 127 for char in value), f"invalid {name}")
    path = PurePosixPath(value)
    _require(path.is_absolute() and path.anchor == "/" and str(path) == value
             and ".." not in path.parts, f"{name} must be an absolute normalized path")
    return path


def _overlap(left, right):
    return left == right or left in right.parents or right in left.parents


def _reference(value, name, limit=MAX_INTEGER):
    _fields(value, {"sha256", "bytes"}, name)
    _digest(value["sha256"], f"{name}.sha256")
    _integer(value["bytes"], 1, limit, f"{name}.bytes")


def _resource_policy(value):
    _fields(value, RESOURCE_POLICY_FIELDS, "resource policy")
    _path(value["ledger_path"], "resource ledger path")
    roots = value["roots"]
    _require(type(roots) is list and 1 <= len(roots) <= 64, "invalid resource roots")
    paths = []
    for root in roots:
        path = _path(root, "resource root")
        _require(not any(_overlap(path, previous) for previous in paths), "resource roots overlap")
        paths.append(path)
    _integer(value["storage_bytes"], 1, MAX_STORAGE_BYTES, "per-worker storage bytes")
    _integer(value["memory_mb"], 1, MAX_MEMORY_MB, "per-worker memory MB")
    _integer(value["cpu_slots"], 1, MAX_CPU_SLOTS, "per-worker CPU slots")


def _execution_policy(value):
    _fields(value, EXECUTION_POLICY_FIELDS, "execution policy")
    _integer(value["max_workers"], 1, MAX_WORKERS, "worker bound")
    _number(value["lease_seconds"], MAX_SECONDS, "lease seconds")
    _number(value["timeout_seconds"], MAX_SECONDS, "timeout seconds")
    _number(value["poll_seconds"], min(30, value["lease_seconds"] / 4), "poll seconds")
    for name in ("defer_target_hydration_gc", "reduce_native_targets"):
        _require(type(value[name]) is bool, f"{name} must be boolean")
    sparse = value["sparse_checkpoint_policy"]
    _fields(sparse, SPARSE_POLICY_FIELDS, "sparse checkpoint policy")
    _integer(sparse["max_depth"], 1, 8, "sparse max depth")
    _number(sparse["max_patch_fraction"], 1, "sparse max patch fraction")


def _validate(value):
    _ordinary(value)
    _fields(value, REQUEST_FIELDS, "request")
    _require(value["schema_version"] == SCHEMA, "unsupported campaign training request schema")
    _require(all(value[name] is False for name in FALSE_FIELDS), "request cannot claim authority or execution")
    _fields(value["owner"], OWNER_FIELDS, "owner")
    for name in OWNER_FIELDS:
        _path(value["owner"][name], f"owner {name}")
    output_root = _path(value["output_root"], "control output root")
    _reference(value["plan_artifact"], "plan artifact", MAX_PLAN_BYTES)
    _identifier(value["worker_id"], "worker ID", _WORKER)
    _identifier(value["variant_id"], "variant ID")
    _digest(value["variant_manifest_sha256"], "variant manifest SHA-256")
    _fields(value["source_campaign_binding"], ROOT_NAMES, "source campaign binding")
    for name, reference in value["source_campaign_binding"].items():
        _reference(reference, name, MAX_CAMPAIGN_METADATA_BYTES)
    _require(type(value["parent_policy"]) is str and value["parent_policy"] in PARENT_POLICIES,
             "invalid parent policy")
    _resource_policy(value["resource_policy"])
    _execution_policy(value["execution_policy"])
    batches = value["batches"]
    _require(type(batches) is list and 1 <= len(batches) <= MAX_BATCHES, "request batch count exceeds bound")
    ordinals, runs, jobs, identities, parents, outputs = [], set(), set(), set(), set(), []
    total_job_bytes = 0
    for batch in batches:
        _fields(batch, BATCH_FIELDS, "batch")
        _integer(batch["plan_ordinal"], 0, MAX_PLAN_BATCHES - 1, "plan ordinal")
        _require(not ordinals or ordinals[-1] < batch["plan_ordinal"], "selected batches must retain plan order")
        ordinals.append(batch["plan_ordinal"])
        _require(type(batch["batch_id"]) is str and batch["batch_id"].startswith("sha256:"), "invalid batch ID")
        _digest(batch["batch_id"][7:], "batch ID digest")
        for name in ("run_id", "job_id", "base_version_id"):
            _identifier(batch[name], name)
        for name in ("job_spec_sha256", "training_config_sha256", "autoencoder_config_sha256"):
            _digest(batch[name], name)
        _reference(batch["job_spec_artifact"], "job artifact", MAX_TOTAL_JOB_BYTES)
        total_job_bytes += batch["job_spec_artifact"]["bytes"]
        _require(total_job_bytes <= MAX_TOTAL_JOB_BYTES, "aggregate job bytes exceed bound")
        _require(batch["run_id"] not in runs and batch["job_id"] not in jobs
                 and batch["batch_id"] not in identities, "duplicate selected batch, run or job")
        runs.add(batch["run_id"])
        jobs.add(batch["job_id"])
        identities.add(batch["batch_id"])
        parents.add(batch["base_version_id"])
        output = _path(batch["output_directory"], "job output directory")
        _require(not _overlap(output, output_root) and not any(_overlap(output, prior) for prior in outputs),
                 "control and job output directories must be separate")
        outputs.append(output)
        target = batch["target_snapshot_id"]
        _require(type(target) is str and (target == "" or (target.startswith("sha256:")
                 and _HASH.fullmatch(target[7:]) is not None)), "invalid target snapshot ID")
        _require(bool(target) == (batch["target_snapshot_artifact"] is not None), "target snapshot binding is incomplete")
        for name in ("target_snapshot_artifact", "arrow_feature_weights_artifact"):
            if batch[name] is not None:
                _reference(batch[name], name)
    _require(value["parent_policy"] != "common_fixed_parent" or len(parents) == 1,
             "fixed-parent request has different base versions")


def encode_campaign_training_request(value) -> bytes:
    """Validate and encode without reading paths or changing supplied values."""
    _validate(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                         allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise CampaignTrainingRequestError("invalid request JSON") from exc
    _require(0 < len(raw) <= MAX_REQUEST_BYTES, "request exceeds encoded byte bound")
    return raw


def decode_campaign_training_request(raw: bytes) -> dict:
    """Require exact canonical bytes and return a fresh ordinary JSON value."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES, "request exceeds encoded byte bound")
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, "duplicate JSON key")
            value[key] = item
        return value
    def invalid(_):
        raise CampaignTrainingRequestError("nonfinite JSON constant")
    def integer(token):
        _require(len(token) <= 20, "request JSON integer exceeds bound")
        value = int(token)
        _require(-MAX_INTEGER <= value <= MAX_INTEGER, "request JSON integer exceeds bound")
        return value
    def number(token):
        # Every canonical finite binary64 JSON spelling fits within this bound;
        # reject long numeric tokens before attempting their conversion.
        _require(len(token) <= 32, "request JSON number exceeds bound")
        value = float(token)
        _require(math.isfinite(value) and abs(value) <= MAX_INTEGER,
                 "request JSON number must be finite and bounded")
        return value
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid,
                           parse_int=integer, parse_float=number)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise CampaignTrainingRequestError("invalid request JSON") from exc
    _require(encode_campaign_training_request(value) == raw, "request JSON is not canonical")
    return value
