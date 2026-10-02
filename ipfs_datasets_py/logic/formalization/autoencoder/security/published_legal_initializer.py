"""Pinned published lineage for an existing, independently replayed lexical fork.

The resolver fetches two bounded metadata files, never checkpoint state or code.
Binding replays the existing native extractor against its retained exact source.
Later profile validation checks admitted bytes without importing that historical
extractor. Published run metrics remain publisher claims, not code-domain scores.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import urllib.request

REPO_ID = "justicedao/legal-ir-autoencoder-checkpoints"
SOURCE_SCHEMA = "published-legal-initializer-source@1"
PIN_SCHEMA = "published-legal-initializer-pin@1"
BINDING_SCHEMA = "published-legal-initializer-binding@1"
MAX_METADATA_BYTES = 262_144
MAX_SOURCE_BYTES = 512 * 1024 * 1024
_HASH = re.compile(r"[a-f0-9]{64}")
_REVISION = re.compile(r"[a-f0-9]{40}")
_MANIFEST_PATH = re.compile(r"checkpoints/[0-9]{8}T[0-9]{6}Z/manifest\.json")
_PIN_FIELDS = {"schema", "repo_id", "revision", "manifest_path", "manifest_sha256", "readme_sha256",
    "checkpoint_id", "state_path", "state_sha256", "state_bytes", "source_records_sha256", "source_count", "source_git_commit"}
_SOURCE_FIELDS = {"schema", "output", "pin", "metadata_download_calls", "checkpoint_download_calls", "training_steps", "provider_calls"}
_COUNTS = {"checkpoint_download_calls": 0, "training_steps": 0, "provider_calls": 0}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate metadata field")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite metadata required")))


def _hash(value):
    if type(value) is not str or not _HASH.fullmatch(value):
        raise ValueError("independent SHA256 pin required")
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("bounded integer required")
    return value


def _path(value):
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("canonical path without symlinks required")
    return path


def _read(path, maximum):
    path = _path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise ValueError("bounded independent regular metadata file required")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if len(raw) > maximum or identity(before) != identity(after) or identity(after) != identity(path.stat()):
        raise ValueError("metadata changed during read")
    return raw


def _snapshot_hash(path, expected_size):
    path = _path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size != expected_size:
            raise ValueError("published source size or regular-file identity differs")
        remaining = expected_size
        while remaining:
            raw = stream.read(min(1_048_576, remaining))
            if not raw:
                raise ValueError("source truncated")
            digest.update(raw)
            remaining -= len(raw)
        if stream.read(1):
            raise ValueError("source grew")
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if identity(before) != identity(after) or identity(after) != identity(path.stat()):
        raise ValueError("published source changed during read")
    return digest.hexdigest()


def _fresh(output, basename):
    output = _path(output)
    if output.name != basename or output.exists():
        raise ValueError("dedicated fresh published-lineage namespace required")
    return output


def _write(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        os.fchmod(stream.fileno(), 0o444)
        stream.flush()
        os.fsync(stream.fileno())


def validate_published_legal_source_pin(pin):
    """Check the portable selection contract; does not fetch or attest metadata."""
    if type(pin) is not dict or set(pin) != _PIN_FIELDS:
        raise ValueError("closed published LegalIR source pin required")
    if pin["schema"] != PIN_SCHEMA or pin["repo_id"] != REPO_ID:
        raise ValueError("published LegalIR namespace differs")
    if type(pin["revision"]) is not str or not _REVISION.fullmatch(pin["revision"]):
        raise ValueError("full immutable Hub commit required")
    if type(pin["manifest_path"]) is not str or not _MANIFEST_PATH.fullmatch(pin["manifest_path"]):
        raise ValueError("bounded canonical manifest path required")
    expected_state = str(PurePosixPath(pin["manifest_path"]).parent / "state/legal-ir-autoencoder-canonical.state.json")
    if pin["state_path"] != expected_state:
        raise ValueError("canonical state selection differs")
    for key in ("manifest_sha256", "readme_sha256", "state_sha256", "source_records_sha256"):
        _hash(pin[key])
    _integer(pin["state_bytes"], 1, MAX_SOURCE_BYTES)
    _integer(pin["source_count"], 1, 4096)
    if (type(pin["checkpoint_id"]) is not str or not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", pin["checkpoint_id"])
            or type(pin["source_git_commit"]) is not str or not _REVISION.fullmatch(pin["source_git_commit"])):
        raise ValueError("published checkpoint identity differs")
    return dict(pin)


def _pin_from_metadata(revision, manifest_path, raw, readme):
    value = _decode(raw)
    if type(value) is not dict or value.get("repo_id") != REPO_ID:
        raise ValueError("published metadata namespace differs")
    state, files, records = value.get("canonical_state"), value.get("files"), value.get("source_records")
    if type(state) is not dict or type(files) is not list or not 1 <= len(files) <= 128 or type(records) is not list:
        raise ValueError("bounded published state inventory required")
    count = _integer(state.get("source_count"), 1, 4096)
    if len(records) != count:
        raise ValueError("published source-record count differs")
    record_fields = {"architecture", "backend", "cycles", "merge_weight", "metric_schema", "path", "run_id", "score", "state_schema", "status"}
    for record in records:
        if type(record) is not dict or set(record) != record_fields:
            raise ValueError("closed published run metadata required")
        _integer(record["cycles"], 0, 10**9)
        for key in ("merge_weight", "score"):
            if type(record[key]) not in (int, float) or not math.isfinite(record[key]):
                raise ValueError("finite published metrics required")
        for key in record_fields - {"cycles", "merge_weight", "score"}:
            if record[key] is None and key in {"metric_schema", "state_schema"}:
                continue
            if type(record[key]) is not str or len(record[key]) > 4096:
                raise ValueError("bounded published run metadata required")
    selected = []
    paths = set()
    for item in files:
        if type(item) is not dict or set(item) != {"path", "sha256", "size_bytes"}:
            raise ValueError("closed published file ledger required")
        path = item["path"]
        if (type(path) is not str or not path or len(path) > 512 or path in paths
                or PurePosixPath(path).is_absolute() or any(p in {".", ".."} for p in path.split("/"))
                or "\\" in path or str(PurePosixPath(path)) != path):
            raise ValueError("published file path differs")
        paths.add(path)
        _hash(item["sha256"])
        _integer(item["size_bytes"], 1, MAX_SOURCE_BYTES)
        if path == state.get("relative_path"):
            selected.append(item)
    if len(selected) != 1 or selected[0] != {"path": state.get("relative_path"), "sha256": state.get("sha256"), "size_bytes": state.get("size_bytes")}:
        raise ValueError("canonical checkpoint and file ledger disagree")
    return validate_published_legal_source_pin({"schema": PIN_SCHEMA, "repo_id": REPO_ID, "revision": revision,
        "manifest_path": manifest_path, "manifest_sha256": _sha(raw), "readme_sha256": _sha(readme),
        "checkpoint_id": value.get("checkpoint_id"), "state_path": state.get("relative_path"),
        "state_sha256": state.get("sha256"), "state_bytes": state.get("size_bytes"),
        "source_records_sha256": _sha(_json(records)), "source_count": count, "source_git_commit": value.get("source_git_commit")})


def _fetch(url, maximum):
    # Metadata is immutable and independently pinned; no credentials or remote code.
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("published metadata exceeds byte bound")
    return raw


def resolve_published_legal_source(*, revision, manifest_path, expected_manifest_sha256,
                                 expected_readme_sha256, output, fetch_bytes=None):
    """Resolve pinned metadata only. ``fetch_bytes(url, maximum)`` supports offline replay."""
    output = _fresh(output, "published-legal-source")
    if type(revision) is not str or not _REVISION.fullmatch(revision):
        raise ValueError("full immutable Hub commit required")
    if type(manifest_path) is not str or not _MANIFEST_PATH.fullmatch(manifest_path):
        raise ValueError("bounded canonical manifest path required")
    _hash(expected_manifest_sha256)
    _hash(expected_readme_sha256)
    fetch = fetch_bytes or _fetch
    base = f"https://huggingface.co/datasets/{REPO_ID}/resolve/{revision}/"
    raw, readme = [fetch(base + name, MAX_METADATA_BYTES) for name in (manifest_path, "README.md")]
    if any(type(item) is not bytes or len(item) > MAX_METADATA_BYTES for item in (raw, readme)):
        raise ValueError("bounded raw metadata bytes required")
    if _sha(raw) != expected_manifest_sha256 or _sha(readme) != expected_readme_sha256:
        raise ValueError("published metadata differs from independent pins")
    readme.decode("utf-8")
    pin = _pin_from_metadata(revision, manifest_path, raw, readme)
    descriptor = {"schema": SOURCE_SCHEMA, "output": str(output), "pin": pin,
        "metadata_download_calls": 2 if fetch_bytes is None else 0, **_COUNTS}
    output.mkdir(parents=True, mode=0o700)
    _write(output / "manifest.json", raw)
    _write(output / "README.md", readme)
    _write(output / "source.json", _json(descriptor))
    return descriptor


def published_legal_source_pin(source):
    """Replay admitted local metadata and return its portable, path-free selection."""
    if type(source) is not dict or set(source) != _SOURCE_FIELDS or source.get("schema") != SOURCE_SCHEMA:
        raise ValueError("closed published source descriptor required")
    if any(type(source[k]) is not int or source[k] != v for k, v in _COUNTS.items()):
        raise ValueError("metadata resolution grants no training or model authority")
    if type(source["metadata_download_calls"]) is not int or source["metadata_download_calls"] not in {0, 2}:
        raise ValueError("bounded metadata resolution count required")
    pin = validate_published_legal_source_pin(source["pin"])
    output = _path(source["output"])
    if output.name != "published-legal-source" or {p.name for p in output.iterdir()} != {"manifest.json", "README.md", "source.json"}:
        raise ValueError("closed published metadata inventory required")
    if _read(output / "source.json", MAX_METADATA_BYTES) != _json(source):
        raise ValueError("published source receipt differs")
    raw, readme = _read(output / "manifest.json", MAX_METADATA_BYTES), _read(output / "README.md", MAX_METADATA_BYTES)
    if _pin_from_metadata(pin["revision"], pin["manifest_path"], raw, readme) != pin:
        raise ValueError("published source metadata drift")
    return pin


def _fork_bytes(initializer):
    fields = {"schema", "domain", "output", "manifest_sha256", "source_checkpoint_sha256",
        "initializer_sha256", "embedding_width", "transferred_row_count", "authority", "runtime_validation_scope"}
    constants = {"schema": "supervisor-security-code-weight-fork@1", "domain": "security-code@1",
        "authority": "unverified_candidate_only",
        "runtime_validation_scope": "admitted_initializer_integrity_not_original_legal_state_replay"}
    if type(initializer) is not dict or set(initializer) != fields or any(initializer[k] != v for k, v in constants.items()):
        raise ValueError("closed independently admitted security initializer required")
    for key in ("manifest_sha256", "source_checkpoint_sha256", "initializer_sha256"):
        _hash(initializer[key])
    _integer(initializer["embedding_width"], 2, 16)
    _integer(initializer["transferred_row_count"], 1, 8192)
    output = _path(initializer["output"])
    if output.name != "security-code-initializer":
        raise ValueError("isolated security initializer required")
    raw = _read(output / "initializer.json", 4_000_000)
    manifest_raw = _read(output / "manifest.json", 32_000)
    if _sha(raw) != initializer["initializer_sha256"] or _sha(manifest_raw) != initializer["manifest_sha256"]:
        raise ValueError("admitted initializer bytes drifted")
    return raw, manifest_raw


def _binding_descriptor(output, raw, value):
    return {"schema": BINDING_SCHEMA, "output": str(output), "binding_sha256": _sha(raw),
        "source_pin": value["source"]["pin"], "initializer_sha256": value["initializer"]["initializer_sha256"],
        "authority": "lineage_only", "training_steps": 0, "provider_calls": 0, "checkpoint_download_calls": 0}


def bind_published_legal_initializer(*, source, local_snapshot, initializer, output):
    """Replay an existing exact fork once, preserving every old artifact byte.

    Run with the historical native dependency profile pinned by the old fork.
    The resulting evidence is separate; it never upgrades the old model's
    training quality, domain semantics, or publication approval.
    """
    output = _fresh(output, "published-legal-binding")
    pin = published_legal_source_pin(source)
    before = _fork_bytes(initializer)
    if any(output.is_relative_to(_path(root)) for root in (source["output"], initializer["output"])):
        raise ValueError("published lineage must remain outside existing source and initializer namespaces")
    local_snapshot = _path(local_snapshot)
    if local_snapshot != _path(initializer["output"]) / "source.checkpoint":
        raise ValueError("exact retained initializer snapshot required")
    if initializer.get("source_checkpoint_sha256") != pin["state_sha256"] or _snapshot_hash(local_snapshot, pin["state_bytes"]) != pin["state_sha256"]:
        raise ValueError("published canonical parent differs from retained snapshot")
    from .codebase_autoencoder_transfer import validate_legal_shared_weight_fork
    selected = validate_legal_shared_weight_fork(expected_receipt=initializer, replay_source=True)
    if _fork_bytes(initializer) != before or _snapshot_hash(local_snapshot, pin["state_bytes"]) != pin["state_sha256"]:
        raise ValueError("initializer changed during published parent replay")
    published_legal_source_pin(source)
    value = {"schema": BINDING_SCHEMA, "source": source, "initializer": initializer,
        "snapshot_bytes": pin["state_bytes"], "native_source_extraction_replayed": True,
        "selected_component": "feature_embedding_weights[token:*]", "selected_rows": len(selected["keys"]),
        "embedding_width": selected["embedding_width"], "native_model_sha256": selected["native_model_sha256"],
        "native_codec_sha256": selected["native_codec_sha256"], "transfer_implementation_sha256": selected["transfer_implementation_sha256"],
        "legal_heads_transferred": False, "proof_authority": False, "formalization_authority": False,
        "code_domain_quality_established": False, "publisher_metrics_revalidated": False,
        "validation_scope": "published_metadata_and_exact_previously_replayed_lexical_bytes",
        "authority": "lineage_only", **_COUNTS}
    raw = _json(value)
    output.mkdir(parents=True, mode=0o700)
    _write(output / "binding.json", raw)
    return _binding_descriptor(output, raw, value)


def validate_published_legal_initializer(*, expected_receipt, replay_snapshot=False):
    """Validate lineage and exact fork bytes without importing historical models.

    By default this neither requires nor reads the retained 398 MB parent.
    ``replay_snapshot=True`` additionally rehashes that exact snapshot; native
    extraction was performed at binding time, not repeated under new code.
    """
    if type(expected_receipt) is not dict or set(expected_receipt) != {
            "schema", "output", "binding_sha256", "source_pin", "initializer_sha256", "authority", *_COUNTS}:
        raise ValueError("closed pinned published binding receipt required")
    if type(replay_snapshot) is not bool:
        raise ValueError("explicit snapshot replay selection required")
    output = _path(expected_receipt["output"])
    if output.name != "published-legal-binding" or {p.name for p in output.iterdir()} != {"binding.json"}:
        raise ValueError("closed published binding namespace required")
    raw = _read(output / "binding.json", MAX_METADATA_BYTES)
    value = _decode(raw)
    constants = {"schema": BINDING_SCHEMA, "native_source_extraction_replayed": True,
        "selected_component": "feature_embedding_weights[token:*]", "legal_heads_transferred": False,
        "proof_authority": False, "formalization_authority": False, "code_domain_quality_established": False,
        "publisher_metrics_revalidated": False, "validation_scope": "published_metadata_and_exact_previously_replayed_lexical_bytes",
        "authority": "lineage_only", **_COUNTS}
    fields = {*constants, "source", "initializer", "snapshot_bytes", "selected_rows", "embedding_width",
              "native_model_sha256", "native_codec_sha256", "transfer_implementation_sha256"}
    if type(value) is not dict or set(value) != fields or any(type(value[k]) is not type(v) or value[k] != v for k, v in constants.items()):
        raise ValueError("published binding scope or authority differs")
    if _binding_descriptor(output, raw, value) != expected_receipt or any(type(expected_receipt[k]) is not int for k in _COUNTS):
        raise ValueError("published binding differs from admitted identity")
    pin = published_legal_source_pin(value["source"])
    initializer = value["initializer"]
    weight_raw, manifest_raw = _fork_bytes(initializer)
    weights, manifest = _decode(weight_raw), _decode(manifest_raw)
    if (initializer["source_checkpoint_sha256"] != pin["state_sha256"]
            or manifest.get("source_checkpoint_sha256") != pin["state_sha256"]
            or manifest.get("source_checkpoint_bytes") != pin["state_bytes"]
            or value["snapshot_bytes"] != pin["state_bytes"]):
        raise ValueError("published parent binding differs")
    for key in ("native_model_sha256", "native_codec_sha256", "transfer_implementation_sha256"):
        if _hash(value[key]) != weights.get(key):
            raise ValueError("historical extractor identity differs")
    if (type(value["selected_rows"]) is not int or value["selected_rows"] != initializer["transferred_row_count"]
            or value["selected_rows"] != len(weights["keys"]) or type(value["embedding_width"]) is not int
            or value["embedding_width"] != initializer["embedding_width"] or value["embedding_width"] != weights["embedding_width"]):
        raise ValueError("selected lexical component dimensions differ")
    if replay_snapshot and _snapshot_hash(_path(initializer["output"]) / "source.checkpoint", pin["state_bytes"]) != pin["state_sha256"]:
        raise ValueError("retained published snapshot drifted")
    if _read(output / "binding.json", MAX_METADATA_BYTES) != raw or _fork_bytes(initializer) != (weight_raw, manifest_raw):
        raise ValueError("published binding changed during validation")
    return {"source_pin": pin, "initializer": dict(initializer), "selected_rows": value["selected_rows"],
        "embedding_width": value["embedding_width"], "authority": "lineage_only",
        "native_extraction_replayed_now": False, "snapshot_rehashed_now": replay_snapshot, **_COUNTS}
