"""Exact, bounded exchange of the two learned formula checkpoint lineages.

This codec does not use the modal weight patch codec. Updates are immutable
postimages against one exact parent, including optimizer and selection state.
They are independent branches, never averages, qualifications or promoted heads.
Network transfer is opt-in; callers own scheduling, resource admission and the
single registry writer. Loading native checkpoints requires a caller-managed
single Torch CPU thread, just like their training and inference APIs.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

from ...huggingface import autoencoder_incremental as transport
from ...huggingface import autoencoder_incremental_download as download
from ...huggingface.publisher import _reject_secrets

SCHEMA = "autoencoder-formula-exchange/v1"
PATCH_SCHEMA = "autoencoder-formula-postimages/v1"
PREFIX = "autoformal/uscode/formula-training"
REPOSITORY = transport.REPOSITORY
MAX_RESULT_BYTES = 72 * 1024 * 1024
MAX_PAYLOAD_BYTES = 80 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_OPERATIONS = 65536
MAX_DEPTH = 32
FALSE = {"qualified": False, "admitted": False, "formalized": False,
         "roundtrip_ok": False, "promotion_performed": False,
         "semantic_correctness_verified": False, "lake_executed": False}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MUTABLE = {
    "native_formula_v1": {"latest", "selected", "parent_checkpoint_sha256"},
    "source_conditioned_formula_v1": {"model_state", "optimizer_state", "progress", "parent_checkpoint_sha256"},
}


class FormulaExchangeError(ValueError):
    """A formula transfer is incompatible, unbound, altered or over budget."""


def _require(condition, message):
    if not condition:
        raise FormulaExchangeError(message)


def _raw(value, maximum=MAX_PAYLOAD_BYTES):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                     allow_nan=False).encode()
    _require(len(raw) <= maximum, "formula exchange byte cap exceeded")
    return raw


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _ref(raw):
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _reference(value, maximum):
    _require(type(value) is dict and set(value) == {"sha256", "bytes"}
             and type(value["sha256"]) is str and _SHA.fullmatch(value["sha256"])
             and type(value["bytes"]) is int and 0 < value["bytes"] <= maximum,
             "closed bounded artifact reference required")
    return value


def _shape(value, depth=0):
    _require(depth <= MAX_DEPTH, "formula JSON nesting cap exceeded")
    if type(value) is dict:
        _require(all(type(key) is str for key in value), "JSON string keys required")
        for child in value.values():
            _shape(child, depth + 1)
    elif type(value) is list:
        for child in value:
            _shape(child, depth + 1)
    else:
        _require(value is None or type(value) in (str, bool, int, float), "plain JSON values required")


def _decode(raw, maximum):
    _require(0 < len(raw) <= maximum, "formula exchange byte cap exceeded")
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate formula JSON key")
            result[key] = value
        return result
    def reject(value):
        raise FormulaExchangeError("nonfinite formula JSON")
    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)
        _shape(result)
        _require(raw == _raw(result, maximum), "canonical formula JSON required")
    except (RecursionError, UnicodeError, json.JSONDecodeError) as exc:
        raise FormulaExchangeError("invalid bounded formula JSON") from exc
    return result


def _validated(result):
    _shape(result)
    _raw(result, MAX_RESULT_BYTES)
    _require(type(result) is dict and set(result) == {"checkpoint", "report"}
             and type(result["checkpoint"]) is dict and type(result["report"]) is dict,
             "closed formula training result required")
    _require(result["report"].get("training_executed") is True,
             "formula exchange requires explicitly completed training")
    # Native and source-only reports have different historical flag sets. The
    # transport must reject even an added authority field neither schema uses.
    for section in (result["checkpoint"], result["report"]):
        _require(all(section.get(key, False) is False for key in
                     (*FALSE, "proof_authority", "publication_performed")),
                 "formula checkpoint/report cannot grant authority")
    checkpoint = result["checkpoint"]
    if checkpoint.get("schema") == "native-formula-checkpoint/v1":
        from . import native_formula_checkpoint as storage
        version, domain = "native_formula_v1", checkpoint.get("domain_id")
    elif checkpoint.get("schema") == "learned-legal-formula-checkpoint/v1":
        from . import legal_formula_checkpoint as storage
        version, domain = "source_conditioned_formula_v1", "legal_ir"
    else:
        raise FormulaExchangeError("unsupported formula lineage; modal checkpoints use their own codec")
    storage._validate(result)
    _reject_secrets(result, label="formula training result")
    frozen = {key: value for key, value in checkpoint.items() if key not in _MUTABLE[version]}
    binding = {"schema": "autoencoder-formula-binding/v1", "runtime_version": version,
               "domain_id": domain, "checkpoint_schema": checkpoint["schema"],
               "immutable_checkpoint_sha256": _digest(frozen),
               "implementation_sha256": _digest(checkpoint["implementation"]),
               "config_sha256": _digest(checkpoint["config"]),
               "training_manifest_sha256": checkpoint["training_manifest_sha256"],
               "tuning_manifest_sha256": checkpoint["tuning_manifest_sha256"]}
    return binding


def formula_binding(result):
    """Validate current producer/config/vocabulary and return its portable identity."""
    return _validated(result)


def _steps(result):
    cp = result["checkpoint"]
    return (cp["latest"]["progress"] if "latest" in cp else cp["progress"])["optimizer_steps"]


def _parent(parent, result):
    _require(_validated(parent) == _validated(result), "formula parent domain/runtime/source/vocabulary/config differs")
    _require(result["checkpoint"]["parent_checkpoint_sha256"] == _digest(parent["checkpoint"]),
             "formula numerical parent differs")
    _require(_steps(result) > _steps(parent), "formula update requires new optimizer progress")


def _diff(before, after, path=()):
    # Canonical byte equality distinguishes bool/int and -0.0/0.0. Dense arrays
    # use one subtree postimage; sparse small arrays can retain unchanged cells.
    if _raw(before) == _raw(after):
        return []
    replacement = [{"path": list(path), "before_sha256": _digest(before), "value": after}]
    parts = []
    if type(before) is dict and type(after) is dict and set(before) == set(after):
        for key in sorted(before):
            parts.extend(_diff(before[key], after[key], (*path, key)))
    elif type(before) is list and type(after) is list and len(before) == len(after) and len(before) <= 64:
        for index, (left, right) in enumerate(zip(before, after)):
            parts.extend(_diff(left, right, (*path, index)))
    return parts if parts and len(parts) <= MAX_OPERATIONS and len(_raw(parts)) < len(_raw(replacement)) else replacement


def _lookup(value, path):
    for key in path:
        if type(value) is dict:
            _require(type(key) is str and key in value, "unknown formula postimage key")
        else:
            _require(type(value) is list and type(key) is int and 0 <= key < len(value),
                     "unknown formula postimage index")
        value = value[key]
    return value


def _replay(parent, patch):
    _require(type(patch) is dict and set(patch) == {"schema", "operations"}
             and patch["schema"] == PATCH_SCHEMA, "closed formula postimage schema required")
    ops = patch["operations"]
    _require(type(ops) is list and 1 <= len(ops) <= MAX_OPERATIONS, "formula operation cap exceeded")
    result = copy.deepcopy(parent)
    trie = {}
    for op in ops:
        _require(type(op) is dict and set(op) == {"path", "before_sha256", "value"}, "closed postimage required")
        path = op["path"]
        _require(type(path) is list and len(path) <= MAX_DEPTH and all(type(v) in (str, int) for v in path),
                 "invalid formula postimage path")
        node = trie
        for part in path:
            _require(None not in node, "duplicate or overlapping formula postimages")
            node = node.setdefault(part, {})
        _require(not node, "duplicate or overlapping formula postimages")
        node[None] = True
        _require(_digest(_lookup(parent, path)) == op["before_sha256"], "formula postimage preimage differs")
        if path:
            _lookup(result, path[:-1])[path[-1]] = copy.deepcopy(op["value"])
        else:
            result = copy.deepcopy(op["value"])
    _raw(result, MAX_RESULT_BYTES)
    return result


def _path(ref, role):
    return f"{PREFIX}/{role}/{ref['sha256']}.json"


def _manifest(value):
    keys = {"schema", "repository_id", "kind", "binding", "parent_result", "parent_checkpoint_sha256",
            "result", "checkpoint_sha256", "payload", "payload_filename", "payload_path_in_repo", *FALSE}
    _require(type(value) is dict and set(value) == keys and value["schema"] == SCHEMA
             and value["repository_id"] == REPOSITORY and value["kind"] in {"anchor", "update"},
             "closed formula exchange manifest required")
    _require(all(value[key] is False for key in FALSE), "formula transport cannot grant authority")
    payload = _reference(value["payload"], MAX_PAYLOAD_BYTES)
    _reference(value["result"], MAX_RESULT_BYTES)
    _require(value["payload_filename"] == payload["sha256"] + ".payload.json"
             and value["payload_path_in_repo"] == _path(payload, "artifacts"), "unbound formula payload path")
    _require(type(value["checkpoint_sha256"]) is str and _SHA.fullmatch(value["checkpoint_sha256"]),
             "invalid formula checkpoint digest")
    if value["kind"] == "anchor":
        _require(value["parent_result"] is None, "anchor must be standalone")
    else:
        _reference(value["parent_result"], MAX_RESULT_BYTES)
        _require(type(value["parent_checkpoint_sha256"]) is str and _SHA.fullmatch(value["parent_checkpoint_sha256"]),
                 "update needs exact checkpoint parent")
    _require(type(value["binding"]) is dict, "formula binding required")
    return value


def _stage(result, destination, parent):
    # Own the snapshots so mutation by a caller cannot change bytes after checks.
    result = _decode(_raw(result, MAX_RESULT_BYTES), MAX_RESULT_BYTES)
    binding = _validated(result)
    if parent is None:
        payload, kind, parent_ref = result, "anchor", None
    else:
        parent = _decode(_raw(parent, MAX_RESULT_BYTES), MAX_RESULT_BYTES)
        _parent(parent, result)
        # Immutable configuration/vocabularies are never retransmitted by the
        # update codec, even when replacing the whole JSON would be cheaper.
        operations = _diff(parent["report"], result["report"], ("report",))
        for key in sorted(_MUTABLE[binding["runtime_version"]]):
            operations.extend(_diff(parent["checkpoint"][key], result["checkpoint"][key], ("checkpoint", key)))
        payload = {"schema": PATCH_SCHEMA, "operations": operations}
        _require(_replay(parent, payload) == result, "formula staging replay differs")
        kind, parent_ref = "update", _ref(_raw(parent, MAX_RESULT_BYTES))
    payload_raw = _raw(payload); payload_ref = _ref(payload_raw)
    value = {"schema": SCHEMA, "repository_id": REPOSITORY, "kind": kind, "binding": binding,
             "parent_result": parent_ref, "parent_checkpoint_sha256": result["checkpoint"]["parent_checkpoint_sha256"],
             "result": _ref(_raw(result, MAX_RESULT_BYTES)), "checkpoint_sha256": _digest(result["checkpoint"]),
             "payload": payload_ref, "payload_filename": payload_ref["sha256"] + ".payload.json",
             "payload_path_in_repo": _path(payload_ref, "artifacts"), **FALSE}
    manifest_raw = _raw(_manifest(value), MAX_MANIFEST_BYTES); ref = _ref(manifest_raw)
    root = Path(destination).absolute()
    transport._write(root / value["payload_filename"], payload_raw)
    path = root / (ref["sha256"] + ".manifest.json")
    transport._write(path, manifest_raw)
    # Recheck current source identity and complete serialized replay before export.
    verified = load_formula_bundle(path, parent_result=parent, expected_binding=binding)
    return {"manifest_path": str(path), "manifest_artifact": ref, "path_in_repo": _path(ref, "manifests"),
            "binding": binding, "result_artifact": value["result"], "checkpoint_sha256": value["checkpoint_sha256"],
            "kind": kind, "payload_bytes": len(payload_raw), "full_result_bytes": value["result"]["bytes"],
            "replay_verified": verified["replay_verified"], **FALSE}


def stage_formula_anchor(result, destination):
    """Stage a full trained result including report, optimizer and selected state."""
    return _stage(result, destination, None)


def stage_formula_update(parent_result, result, destination):
    """Stage an exact parent-bound branch, never an arithmetic weight delta."""
    return _stage(result, destination, parent_result)


def load_formula_bundle(manifest_path, *, parent_result=None, expected_binding=None):
    """Verify local bytes, reconstruct exactly and validate against local sources.

    The returned ``result`` is the existing registration input with keys
    ``checkpoint`` and ``report``. No registry mutation or head movement occurs.
    ``manifest`` and ``manifest_artifact`` retain the complete portable binding.
    A receiving worker should supply its trusted ``expected_binding``; updates
    additionally require the exact parent result, not merely matching weights.
    """
    path = Path(manifest_path).absolute()
    raw = transport._read(path, MAX_MANIFEST_BYTES)
    value = _manifest(_decode(raw, MAX_MANIFEST_BYTES))
    if expected_binding is not None:
        _require(value["binding"] == expected_binding, "formula receiver domain/runtime/source/config binding differs")
    payload_raw = transport._read(path.parent / value["payload_filename"], MAX_PAYLOAD_BYTES, value["payload"])
    payload = _decode(payload_raw, MAX_PAYLOAD_BYTES)
    if value["kind"] == "anchor":
        _require(parent_result is None, "standalone anchor does not consume a parent")
        result = payload
    else:
        _require(parent_result is not None, "formula update requires its locally provisioned exact parent")
        _require(_ref(_raw(parent_result, MAX_RESULT_BYTES)) == value["parent_result"], "formula result parent differs")
        _require(_validated(parent_result) == value["binding"], "formula parent binding differs")
        result = _replay(parent_result, payload)
        _parent(parent_result, result)
    _require(_ref(_raw(result, MAX_RESULT_BYTES)) == value["result"], "formula replay result digest differs")
    _require(_validated(result) == value["binding"] and _digest(result["checkpoint"]) == value["checkpoint_sha256"]
             and result["checkpoint"]["parent_checkpoint_sha256"] == value["parent_checkpoint_sha256"],
             "formula result checkpoint or immutable binding differs")
    return {"result": result, "manifest": value, "manifest_artifact": _ref(raw),
            "binding": value["binding"], "checkpoint_sha256": value["checkpoint_sha256"],
            "snapshots": {value["payload_path_in_repo"]: payload_raw, _path(_ref(raw), "manifests"): raw},
            "replay_verified": True, "registration_performed": False, **FALSE}


def publish_formula_bundle(manifest_path, *, parent_result=None, upload=False, api=None):
    """Append immutable artifacts with Hub parent-commit CAS; dry-run by default."""
    _require(type(upload) is bool, "explicit boolean upload required")
    bundle = load_formula_bundle(manifest_path, parent_result=parent_result)
    # Reuse only the bounded immutable Hub publication mechanics. No legacy
    # checkpoint parser, state codec, acceptance test or head API is called.
    from .autoencoder_feature_exchange import _publish
    published = _publish(bundle["snapshots"], upload=upload, api=api)
    reference = None
    if published["uploaded"]:
        reference = {"schema": SCHEMA, "repository_id": REPOSITORY, "commit_sha": published["commit_sha"],
                     "path_in_repo": _path(bundle["manifest_artifact"], "manifests"),
                     **bundle["manifest_artifact"], "binding": bundle["binding"],
                     "result_artifact": bundle["manifest"]["result"]}
    return {**published, "formula_reference": reference, "manifest_artifact": bundle["manifest_artifact"],
            "full_checkpoint_uploaded": published["uploaded"] and bundle["manifest"]["kind"] == "anchor", **FALSE}


def _remote_reference(reference):
    keys = {"schema", "repository_id", "commit_sha", "path_in_repo", "sha256", "bytes", "binding", "result_artifact"}
    _require(type(reference) is dict and set(reference) == keys and reference["schema"] == SCHEMA,
             "closed formula remote reference required")
    download._binding(reference["repository_id"], reference["commit_sha"])
    ref = _reference({key: reference[key] for key in ("sha256", "bytes")}, MAX_MANIFEST_BYTES)
    _require(reference["path_in_repo"] == _path(ref, "manifests"), "unbound formula remote path")
    _reference(reference["result_artifact"], MAX_RESULT_BYTES)
    _require(type(reference["binding"]) is dict, "formula reference binding required")
    return ref


def receive_formula_bundle(reference, destination, *, parent_result=None, expected_binding=None,
                           allow_weight_download=False, client=None, api=None):
    """Fetch one pinned bundle with explicit consent; never chase parent chains.

    ``client`` injection supports offline fixtures. Real network transfer always
    uses the bounded campaign downloader. Repeated receives verify retained
    bytes and reuse them. Pass the returned ``result`` to an owner-controlled
    registration API; remote metadata never qualifies or promotes the result.
    """
    _require(allow_weight_download is True, "formula weight download requires explicit opt-in")
    ref = _remote_reference(reference)
    if expected_binding is not None:
        _require(reference["binding"] == expected_binding, "formula receiver binding differs before download")
    root = Path(destination).absolute()
    telemetry = {"downloaded_bytes": 0, "downloaded_files": 0, "downloaded_weight_files": 0, "reused_files": 0}
    client = client or download.HubCampaignArtifactClient(api)
    with download._owner(root):
        path = root / (ref["sha256"] + ".manifest.json")
        raw = download._cached_fetch(client, REPOSITORY, reference["commit_sha"], reference["path_in_repo"],
            path, MAX_MANIFEST_BYTES, root, telemetry, ref=ref)
        value = _manifest(_decode(raw, MAX_MANIFEST_BYTES))
        _require(value["binding"] == reference["binding"] and value["result"] == reference["result_artifact"],
                 "formula remote manifest identity differs")
        if value["kind"] == "update":
            _require(parent_result is not None and _ref(_raw(parent_result, MAX_RESULT_BYTES)) == value["parent_result"],
                     "formula receive requires exact local parent before fetching weights")
            _require(_validated(parent_result) == value["binding"], "formula parent binding differs")
        download._cached_fetch(client, REPOSITORY, reference["commit_sha"], value["payload_path_in_repo"],
            root / value["payload_filename"], MAX_PAYLOAD_BYTES, root, telemetry, ref=value["payload"], weight=True)
        bundle = load_formula_bundle(path, parent_result=parent_result, expected_binding=expected_binding)
        return {"result": bundle["result"], "manifest_path": str(path), "binding": bundle["binding"],
                "checkpoint_sha256": bundle["checkpoint_sha256"], "replay_verified": True,
                "registration_performed": False, "weights_downloaded": telemetry["downloaded_weight_files"] > 0,
                **telemetry, **FALSE}


__all__ = ["FormulaExchangeError", "formula_binding", "stage_formula_anchor", "stage_formula_update",
           "load_formula_bundle", "publish_formula_bundle", "receive_formula_bundle"]
