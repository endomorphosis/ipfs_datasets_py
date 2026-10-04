"""Reuse pinned, matching 768D receipts before considering encoder execution.

This helper never loads producer code, model assets, tensor libraries or an
encoder. Callers authenticate task and receipt file bytes before admission.
Compatible receipts retain their exact content; missing sources remain explicit
tasks. Archived 8D and 384D vectors cannot substitute for multilingual receipts.
Receipt consistency does not authenticate the earlier producer's execution.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import re


SCHEMA = "gte-embedding-reuse/v1"
MAX_ROWS = 4096
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _load_corpus():
    path = Path(__file__).with_name("gte_multilingual_corpus.py")
    spec = importlib.util.spec_from_file_location("_gte_embedding_reuse_corpus", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the multilingual receipt contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CORPUS = _load_corpus()
PROFILE_ID = _CORPUS.PROFILE_ID


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def prepare_cached_embedding_reuse(tasks_or_manifest, receipts, *,
                                   expected_asset_manifest_sha256, max_rows=MAX_ROWS):
    """Bind cached receipts and return only their missing original source tasks.

    The selected asset-manifest hash is required even for an empty cache. No
    local assets need to be installed. Each receipt must already name an exact
    task ID, exact UTF8 source hash, the selected 768D producer profile and asset
    generation. IDs and source hashes are never remapped. Duplicate, unexpected
    or incompatible entries fail the whole admission rather than being dropped.

    For a nonempty task cohort, no receipts means unavailable; some receipts
    means partial. Complete coverage, including an empty cohort, means ready.
    Both task and receipt iterables are consumed under the same explicit bound.
    Returned objects are private copies; numeric leaf types in cached receipts
    are preserved rather than changed by the binding's float conversion.
    """
    _require(type(max_rows) is int and 1 <= max_rows <= MAX_ROWS,
             "max_rows must be an integer between 1 and 4096")
    _require(type(expected_asset_manifest_sha256) is str
             and _SHA256.fullmatch(expected_asset_manifest_sha256) is not None,
             "selected asset manifest requires full lowercase SHA256")
    if isinstance(tasks_or_manifest, dict):
        tasks = _CORPUS._bounded_rows(tasks_or_manifest.get("tasks"), max_rows, label="tasks")
        admitted_tasks = {**tasks_or_manifest, "tasks": tasks}
    else:
        tasks = _CORPUS._bounded_rows(tasks_or_manifest, max_rows, label="tasks")
        admitted_tasks = tasks
    cached = _CORPUS._bounded_rows(receipts, max_rows, label="receipts")
    binding = _CORPUS.bind_embedding_receipts(admitted_tasks, cached)
    _require(all(receipt["asset_manifest_sha256"] == expected_asset_manifest_sha256
                 for receipt in cached), "cached receipt differs from selected asset manifest")
    validated_tasks, _ = _CORPUS._validate_tasks(admitted_tasks)
    missing_ids = set(binding["missing_receipt_ids"])
    reused = deepcopy(sorted(cached, key=lambda item: item["id"]))
    missing = deepcopy([task for task in validated_tasks if task["id"] in missing_ids])
    status = "ready" if not missing else "partial" if reused else "unavailable"
    return {
        "schema": SCHEMA,
        "profile_id": PROFILE_ID,
        "asset_manifest_sha256": expected_asset_manifest_sha256,
        "task_count": binding["task_count"],
        "cached_receipt_count": len(reused),
        "missing_task_count": len(missing),
        "status": status,
        "reused_receipts": reused,
        "missing_tasks": missing,
        "binding": binding,
        "reused_receipts_sha256": _CORPUS._digest(reused),
        "missing_tasks_sha256": _CORPUS._digest(missing),
        "embeddings_generated": False,
        "encoder_inference_executed": False,
        "source_vectors_relabelled": False,
        "producer_execution_authenticated": False,
        "proof_authority": False,
    }


__all__ = ["SCHEMA", "PROFILE_ID", "MAX_ROWS", "prepare_cached_embedding_reuse"]
