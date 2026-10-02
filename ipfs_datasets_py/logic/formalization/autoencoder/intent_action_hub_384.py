"""Resolve an explicitly selected immutable experimental Intent checkpoint.

Transport stays in datasets. The caller opts into downloads; default resolution
uses the local Hub cache. The existing numerical owner validates the weights
when inference is invoked. Nothing changes the default Intent model registry.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

SCHEMA = "intent-action-384-hub-reference/v1"
REPOSITORY = "Publicus/intent-ir-autoencoder"
FIELDS = {"schema", "repository_id", "revision", "checkpoint_path", "checkpoint_sha256"}


def resolve_intent_action_checkpoint(reference, *, cache_dir=None, local_files_only=True):
    """Return the exact local options for prepare_intent_action_inference.

    Both the containing manifest and checkpoint are fetched at the same full
    revision, hash-checked, and left unchanged. Hub snapshot links resolve to
    their regular cached blobs before the numerical loader receives a path.
    """
    if (type(reference) is not dict or set(reference) != FIELDS or reference["schema"] != SCHEMA
            or reference["repository_id"] != REPOSITORY or type(local_files_only) is not bool):
        raise ValueError("closed experimental Intent Hub reference required")
    if (type(reference["revision"]) is not str or not re.fullmatch(r"[0-9a-f]{40}", reference["revision"])
            or type(reference["checkpoint_sha256"]) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", reference["checkpoint_sha256"])):
        raise ValueError("immutable revision and checkpoint hash required")
    if type(reference["checkpoint_path"]) is not str:
        raise ValueError("versioned experimental checkpoint path required")
    match = re.fullmatch(r"(experiments/action-contracts-384/v1/([0-9a-f]{64}))/checkpoint.json",
                         reference["checkpoint_path"])
    if match is None:
        raise ValueError("versioned experimental checkpoint path required")
    from huggingface_hub import hf_hub_download
    options = dict(repo_id=REPOSITORY, repo_type="model", revision=reference["revision"],
                   cache_dir=cache_dir, local_files_only=local_files_only)
    manifest_path = Path(hf_hub_download(filename=match[1] + "/manifest.json", **options)).resolve(strict=True)
    if not manifest_path.is_file() or not 0 < manifest_path.stat().st_size <= 4 * 1024 * 1024:
        raise ValueError("bounded regular Intent release manifest required")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != match[2]:
        raise ValueError("Intent release manifest hash differs")
    manifest = json.loads(manifest_bytes)
    if (type(manifest) is not dict or manifest.get("schema") != "intent-action-384-development-release/v1"
            or manifest.get("repository_id") != REPOSITORY
            or manifest.get("checkpoint_schema") != "structured-source-384-autoencoder/v1"
            or manifest.get("checkpoint_sha256") != reference["checkpoint_sha256"]
            or manifest.get("production_promoted") is not False):
        raise ValueError("Intent release manifest checkpoint or experimental scope differs")
    checkpoint = Path(hf_hub_download(filename=reference["checkpoint_path"], **options)).resolve(strict=True)
    if not checkpoint.is_file() or not 0 < checkpoint.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError("bounded regular Intent checkpoint required")
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != reference["checkpoint_sha256"]:
        raise ValueError("downloaded Intent checkpoint hash differs")
    return {"checkpoint_path": str(checkpoint), "expected_sha256": reference["checkpoint_sha256"]}


__all__ = ["SCHEMA", "resolve_intent_action_checkpoint"]
