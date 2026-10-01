"""Immutable Hub exchange of bound inputs, sufficient statistics and heads.

Checkpoint postimages reuse the existing exact-preimage codec. They are byte
transport, never model averaging or permission to qualify a remote candidate.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

from .contracts import (COMMIT, DOMAINS, FALSE, MAX_BYTES, SHA, binding as plan_binding,
                       digest, raw, read_bound, read_json, read_json_bound, require, write_json)

SCHEMA = "distributed-structured-384-bundle/v1"
REFERENCE_SCHEMA = "distributed-structured-384-reference/v1"
INPUTS_SCHEMA = "distributed-structured-384-inputs/v1"
_BINDING = {"plan_id", "domain_id", "base_checkpoint_sha256", "dataset_sha256", "recipe_sha256"}
_KINDS = {"update", "checkpoint", "inputs"}
_MAX_MANIFEST = 1024 * 1024
_MAX_FILES = 10000


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _binding(value, domain=None):
    require(type(value) is dict and set(value) == _BINDING, "closed training binding required")
    require(value["domain_id"] in DOMAINS and (domain is None or value["domain_id"] == domain),
            "binding domain differs")
    require(all(type(value[key]) is str and SHA.fullmatch(value[key])
        for key in _BINDING - {"domain_id"}), "binding digests required")
    return value


def _decode(data, *, canonical=True, maximum=MAX_BYTES):
    require(type(data) is bytes and 0 < len(data) <= maximum, "bounded JSON bytes required")
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value
    def bad(_):
        raise ValueError("nonfinite JSON number")
    value = json.loads(data, object_pairs_hook=pairs, parse_constant=bad)
    encoded = raw(value)
    require(len(encoded) <= maximum and (not canonical or encoded == data), "canonical JSON bytes required")
    return value


def _safe(value):
    from .....huggingface.publisher import _reject_secrets
    _reject_secrets(value, label="distributed structured384 exchange")


def _validate_payload(value, kind, binding):
    from . import numerics
    from ..structured_source_384 import Runtime
    _binding(binding)
    require(type(value) is dict and kind in _KINDS, "typed exchange payload required")
    _safe(value)
    require(len(raw(value)) <= MAX_BYTES, "payload exceeds byte bound")
    if kind == "update":
        require(set(value) == {"schema", *_BINDING, "shard_id", "rows_sha256", "row_count",
            "statistics", "update_id", *FALSE}, "closed update payload required")
        require(value["schema"] == numerics.UPDATE_SCHEMA and value["update_id"] == digest(
            {k: v for k, v in value.items() if k != "update_id"}), "update identity differs")
        require(all(value[k] == v for k, v in binding.items()) and all(value[k] is False for k in FALSE),
                "update binding or authority differs")
        require(type(value["shard_id"]) is str and numerics._SHARD_ID.fullmatch(value["shard_id"])
            and type(value["rows_sha256"]) is str and SHA.fullmatch(value["rows_sha256"]), "shard identity differs")
        count = value["row_count"]
        require(type(count) is int and 1 <= count <= 2048, "bounded update rows required")
        stats = value["statistics"]
        require(type(stats) is dict and set(stats) == {"encoding", "projected", "class_ids"}
            and stats["encoding"] == "low_rank_sparse_labels/v1", "statistics encoding differs")
        x, labels = stats["projected"], stats["class_ids"]
        require(type(x) is list and len(x) == count and all(type(row) is list and len(row) == 384
            and all(type(v) in (int, float) and math.isfinite(v) for v in row) for row in x),
            "invalid projected statistics")
        require(type(labels) is list and len(labels) == count and type(labels[0]) is list
            and 1 <= len(labels[0]) <= 256 and all(type(row) is list and len(row) == len(labels[0])
                and all(type(v) is int and 0 <= v < 512 for v in row) for row in labels),
            "invalid sparse target coordinates")
    elif kind == "checkpoint":
        Runtime(value)
        require(value["domain_id"] == binding["domain_id"], "checkpoint domain differs")
        training = value["training"]
        require(training.get("trainer_id") == numerics.ALGORITHM,
                "distributed checkpoint requires completed round training metadata; send base heads as inputs")
        for key in ("plan_id", "recipe_sha256", "base_checkpoint_sha256"):
            require(training.get(key) == binding[key], "checkpoint training binding differs")
    else:
        require(set(value) == {"schema", "plan", "base_checkpoint_raw", "training_rows", "validation_rows"}
            and value["schema"] == INPUTS_SCHEMA, "closed training inputs required")
        plan = numerics.validate_plan(value["plan"])
        require(plan_binding(plan) == binding and plan["dataset_sha256"] == digest(plan["dataset"]),
                "input plan binding differs")
        source = value["base_checkpoint_raw"]
        require(type(source) is str, "original base checkpoint JSON required")
        data = source.encode()
        base = _decode(data, canonical=False)
        _safe(base)
        require(_sha(data) == binding["base_checkpoint_sha256"] and digest(base) == plan["base_json_sha256"],
                "input base raw or canonical hash differs")
        numerics._base(base, plan)
        for key in ("training_rows", "validation_rows"):
            require(type(value[key]) is list and digest(value[key]) == plan["dataset"][key + "_sha256"],
                    "input corpus rows differ")
    return value


def _artifact(value, *, maximum=MAX_BYTES):
    require(type(value) is dict and set(value) == {"sha256", "bytes"}
        and type(value["sha256"]) is str and SHA.fullmatch(value["sha256"])
        and type(value["bytes"]) is int and 0 < value["bytes"] <= maximum, "bounded artifact reference required")
    return value


def _ref(data):
    return dict(sha256=_sha(data), bytes=len(data))


def _manifest(value):
    require(type(value) is dict and set(value) == {"schema", "kind", "domain_id", "binding", "encoding",
        "parent", "payload", "result", *FALSE} and value["schema"] == SCHEMA and value["kind"] in _KINDS,
        "closed exchange manifest required")
    _binding(value["binding"], value["domain_id"])
    require(all(value[k] is False for k in FALSE), "manifest cannot grant authority")
    _artifact(value["payload"]); _artifact(value["result"])
    require(value["encoding"] in {"json", "postimages"}, "unknown payload encoding")
    if value["parent"] is None:
        require(value["encoding"] == "json" and value["payload"] == value["result"], "standalone payload differs")
    else:
        parent = value["parent"]
        require(value["kind"] == "checkpoint" and value["encoding"] == "postimages"
            and type(parent) is dict and set(parent) == {"raw", "canonical_sha256"}, "checkpoint parent required")
        _artifact(parent["raw"])
        require(parent["raw"]["sha256"] == value["binding"]["base_checkpoint_sha256"],
                "manifest parent differs from bound round base")
        require(type(parent["canonical_sha256"]) is str and SHA.fullmatch(parent["canonical_sha256"]),
                "canonical parent hash required")
    _safe(value)
    return value


def _patch(parent, target):
    from .....optimizers.logic_theorem_optimizer.autoencoder_formula_exchange import _diff, _replay, PATCH_SCHEMA
    operations = _diff(parent, target)
    # Empty updates use a harmless exact root postimage; the inherited codec
    # intentionally requires at least one operation.
    if not operations:
        from .....optimizers.logic_theorem_optimizer.autoencoder_formula_exchange import _digest
        operations = [dict(path=[], before_sha256=_digest(parent), value=deepcopy(target))]
    patch = dict(schema=PATCH_SCHEMA, operations=operations)
    require(raw(_replay(parent, patch)) == raw(target), "postimage reconstruction differs")
    return patch


def stage_bundle(payload_path, output_dir, *, domain_id, kind, binding, parent_path=None):
    """Validate and stage an immutable canonical payload or exact postimage."""
    _binding(binding, domain_id)
    value = _validate_payload(read_json(payload_path), kind, binding)
    payload, parent = value, None
    parent_value = None
    if parent_path is not None:
        require(kind == "checkpoint", "only checkpoint bundles accept a parent")
        parent_value, parent_reference = read_json_bound(parent_path)
        from ..structured_source_384 import Runtime
        Runtime(parent_value)
        require(parent_value["domain_id"] == domain_id, "parent domain differs")
        parent = dict(raw=parent_reference, canonical_sha256=digest(parent_value))
        require(parent["raw"]["sha256"] == binding["base_checkpoint_sha256"], "parent is not bound round base")
        payload = _patch(parent_value, value)
    manifest = _manifest(dict(schema=SCHEMA, kind=kind, domain_id=domain_id, binding=deepcopy(binding),
        encoding="postimages" if parent else "json", parent=parent,
        payload=_ref(raw(payload)), result=_ref(raw(value)), **FALSE))
    root = Path(output_dir) / digest(manifest)
    write_json(root / "payload.json", payload)
    write_json(root / "result.json", value)
    if parent_value is not None:
        write_json(root / "parent.json", parent_value)
    path = write_json(root / "manifest.json", manifest)
    return dict(manifest_path=str(path), manifest=manifest, payload_path=str(root / "result.json"))


def _local_bundle(path):
    path = Path(path)
    manifest_data, _ = read_bound(path, maximum=_MAX_MANIFEST)
    manifest = _manifest(_decode(manifest_data, maximum=_MAX_MANIFEST))
    root = path.parent
    payload_data, payload_ref = read_bound(root / "payload.json")
    payload = _decode(payload_data)
    require(payload_ref == manifest["payload"], "staged payload differs")
    result_data, result_ref = read_bound(root / "result.json")
    result = _decode(result_data)
    require(result_ref == manifest["result"], "staged result differs")
    if manifest["parent"] is not None:
        from .....optimizers.logic_theorem_optimizer.autoencoder_formula_exchange import _replay
        parent = read_json(root / "parent.json")
        require(digest(parent) == manifest["parent"]["canonical_sha256"], "staged parent differs")
        require(raw(_replay(parent, payload)) == raw(result), "staged postimage differs")
    else:
        require(raw(payload) == raw(result), "staged full payload differs")
    _validate_payload(result, manifest["kind"], manifest["binding"])
    return manifest, {"manifest.json": raw(manifest), "payload.json": raw(payload)}


def _location(repository_id, prefix):
    require(type(repository_id) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository_id),
            "explicit namespace/repository required")
    require(type(prefix) is str and 0 < len(prefix) <= 256 and not prefix.startswith("/")
        and all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", part) for part in prefix.split("/")),
        "safe repository prefix required")


def _revision(value):
    require(type(value) is str and COMMIT.fullmatch(value), "immutable Hub revision required")
    return value


def _download(repository_id, revision, filename, *, local_files_only=False, download_fn=None):
    if download_fn is None:
        from huggingface_hub import hf_hub_download
        download_fn = hf_hub_download
    path = Path(download_fn(repo_id=repository_id, repo_type="model", revision=revision,
        filename=filename, local_files_only=local_files_only))
    # Hub cache inputs may be symlinks; outputs are always regular files.
    return read_bound(path.resolve(strict=True))[0]


def _files(api, repository_id, revision):
    result = []
    for name in api.list_repo_files(repo_id=repository_id, repo_type="model", revision=revision):
        require(len(result) < _MAX_FILES and type(name) is str, "Hub file inventory exceeds bound")
        result.append(name)
    return set(result)


def _reference(repository_id, revision, filename, manifest):
    return dict(schema=REFERENCE_SCHEMA, repository_id=repository_id, repo_type="model",
        revision=_revision(revision), manifest_path_in_repo=filename,
        manifest_sha256=digest(manifest), kind=manifest["kind"], binding=deepcopy(manifest["binding"]))


def publish_bundle(manifest_path, *, repository_id, prefix, upload=False, api=None):
    """Append content-addressed files with bounded parent-commit CAS retries."""
    _location(repository_id, prefix)
    require(type(upload) is bool, "explicit upload boolean required")
    manifest, files = _local_bundle(manifest_path)
    directory = prefix + "/" + digest(manifest)
    snapshots = {directory + "/" + name: data for name, data in files.items()}
    if not upload:
        return dict(uploaded=False, reference=None, repository_id=repository_id, prefix=prefix,
            files=[dict(path_in_repo=name, **_ref(data)) for name, data in snapshots.items()])
    from huggingface_hub import HfApi, CommitOperationAdd
    api = api or HfApi()
    downloader = getattr(api, "hf_hub_download", None)
    for attempt in range(4):
        head = _revision(api.model_info(repo_id=repository_id).sha)
        existing = _files(api, repository_id, head)
        additions = []
        for filename, data in snapshots.items():
            if filename in existing:
                observed = _download(repository_id, head, filename, download_fn=downloader)
                require(observed == data, "immutable remote artifact conflicts")
            else:
                additions.append(CommitOperationAdd(path_in_repo=filename, path_or_fileobj=data))
        if not additions:
            return _reference(repository_id, head, directory + "/manifest.json", manifest)
        try:
            commit = api.create_commit(repo_id=repository_id, repo_type="model", parent_commit=head,
                commit_message="Add immutable distributed384 " + manifest["kind"] + " " + digest(manifest)[:12],
                operations=additions)
        except Exception as error:
            if getattr(getattr(error, "response", None), "status_code", None) not in (409, 412) or attempt == 3:
                raise
            continue
        revision = _revision(commit.oid)
        for filename, data in snapshots.items():
            require(_download(repository_id, revision, filename, download_fn=downloader) == data,
                    "published artifact verification differs")
        return _reference(repository_id, revision, directory + "/manifest.json", manifest)
    raise ValueError("Hub parent-commit retry budget exhausted")


def _remote_ref(reference):
    require(type(reference) is dict and set(reference) == {"schema", "repository_id", "repo_type", "revision",
        "manifest_path_in_repo", "manifest_sha256", "kind", "binding"}
        and reference["schema"] == REFERENCE_SCHEMA and reference["repo_type"] == "model"
        and reference["kind"] in _KINDS, "closed immutable Hub reference required")
    _binding(reference["binding"])
    _revision(reference["revision"])
    sha = reference["manifest_sha256"]
    require(type(sha) is str and SHA.fullmatch(sha), "manifest SHA256 required")
    path = reference["manifest_path_in_repo"]
    require(type(path) is str and path.endswith("/" + sha + "/manifest.json"), "manifest path differs from digest")
    prefix = path[:-(len(sha) + len("/manifest.json") + 1)]
    _location(reference["repository_id"], prefix)
    return reference


def receive_bundle(reference, output_dir, *, parent_path=None, local_files_only=False, download_fn=None):
    """Receive pinned artifacts and replay only against the exact local parent."""
    reference = _remote_ref(reference)
    require(type(local_files_only) is bool, "boolean local_files_only required")
    def fetch(name):
        return _download(reference["repository_id"], reference["revision"], name,
            local_files_only=local_files_only, download_fn=download_fn)
    data = fetch(reference["manifest_path_in_repo"])
    require(_sha(data) == reference["manifest_sha256"], "remote manifest hash differs")
    manifest = _manifest(_decode(data, maximum=_MAX_MANIFEST))
    require(manifest["kind"] == reference["kind"] and manifest["binding"] == reference["binding"],
            "remote manifest binding differs")
    parent = None
    if manifest["parent"] is not None:
        require(parent_path is not None, "exact original parent file required")
        parent, parent_ref = read_json_bound(parent_path)
        require(parent_ref == manifest["parent"]["raw"], "exact original parent file required")
        require(digest(parent) == manifest["parent"]["canonical_sha256"], "canonical parent differs")
    payload_data = fetch(str(PurePosixPath(reference["manifest_path_in_repo"]).parent / "payload.json"))
    require(_ref(payload_data) == manifest["payload"], "remote payload hash differs")
    payload = _decode(payload_data)
    if parent is not None:
        from .....optimizers.logic_theorem_optimizer.autoencoder_formula_exchange import _replay
        value = _replay(parent, payload)
    else:
        value = payload
    require(_ref(raw(value)) == manifest["result"], "reconstructed payload hash differs")
    _validate_payload(value, manifest["kind"], manifest["binding"])
    root = Path(output_dir) / reference["manifest_sha256"]
    write_json(root / "payload.json", payload)
    result_path = write_json(root / "result.json", value)
    if parent is not None:
        write_json(root / "parent.json", parent)
    manifest_path = write_json(root / "manifest.json", manifest)
    return dict(payload_path=str(result_path), manifest_path=str(manifest_path), manifest=manifest)


def discover_bundles(repository_id, prefix, *, kind="update", expected_binding, api=None, download_fn=None):
    """Pin one Hub HEAD and return only exact-binding manifests under a prefix."""
    _location(repository_id, prefix)
    _binding(expected_binding)
    require(kind in _KINDS, "known bundle kind required")
    if api is None:
        from huggingface_hub import HfApi
        api = HfApi()
    head = _revision(api.model_info(repo_id=repository_id).sha)
    files = _files(api, repository_id, head)
    downloader = download_fn or getattr(api, "hf_hub_download", None)
    pattern = re.compile(re.escape(prefix) + r"/([0-9a-f]{64})/manifest\.json\Z")
    matches = sorted(name for name in files if pattern.fullmatch(name))
    require(len(matches) <= 2048, "manifest discovery exceeds bound")
    result = []
    for name in matches:
        data = _download(repository_id, head, name, download_fn=downloader)
        require(_sha(data) == pattern.fullmatch(name)[1], "discovered manifest path hash differs")
        manifest = _manifest(_decode(data, maximum=_MAX_MANIFEST))
        if manifest["kind"] == kind and manifest["binding"] == expected_binding:
            result.append(_reference(repository_id, head, name, manifest))
    return result


__all__ = ["stage_bundle", "publish_bundle", "receive_bundle", "discover_bundles"]
