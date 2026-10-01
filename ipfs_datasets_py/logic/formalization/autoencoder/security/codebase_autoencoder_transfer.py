"""Immutable, partial lexical-weight transfer from a native modal checkpoint.

Only identically keyed ``feature_embedding_weights['token:…']`` rows transfer.
Their dimension and floating-point values are preserved, never reshaped into
AST weights. Legal heads, sample memories, proof state and legal projections
remain absent from the initializer. The complete inert source snapshot is
retained solely to independently replay the exact extraction and lineage.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

SCHEMA = "supervisor-security-code-weight-fork@1"
INITIALIZER_SCHEMA = "supervisor-security-code-lexical-initializer@1"
DOMAIN = "security-code@1"
MAX_SOURCE_BYTES = 512 * 1024 * 1024
_HASH = re.compile(r"[a-f0-9]{64}")
_TOKEN = re.compile(r"token:[a-z0-9]{3,}")
_DESCRIPTOR_FIELDS = {"schema", "domain", "output", "manifest_sha256", "source_checkpoint_sha256",
                      "initializer_sha256", "embedding_width", "transferred_row_count", "authority",
                      "runtime_validation_scope"}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, maximum):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("canonical regular weight artifact required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise ValueError("bounded independent regular weight artifact required")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    current = path.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if len(raw) > maximum or identity(before) != identity(after) or identity(after) != identity(current):
        raise ValueError("source checkpoint changed during immutable snapshot")
    return raw


def _namespace(output, fresh):
    if (not output.is_absolute() or output.resolve() != output or output.name != "security-code-initializer"
            or (fresh and output.exists())
            or any(p.lower() in {"legal-ir", "legal_ir", "legalir", "shared-weights", "shared_weights"} for p in output.parts)):
        raise ValueError("dedicated fresh security-code-initializer namespace required")


def _extract(raw):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as codec
    if raw.startswith(codec.CHECKPOINT_MAGIC):
        # The native inert codec checks checksum, component hashes, revision
        # and full state identity; it never loads a live owner/engine.
        loaded = codec.deserialize_checkpoint(raw, expected_state_schema_version="modal-autoencoder-state-v1")
        weights = loaded.state.feature_embedding_weights
        architecture = loaded.state.architecture_version
        lineage = {"source_state_digest": loaded.manifest.state_digest,
            "source_revision": loaded.manifest.revision, "source_architecture": architecture,
            "source_schema": loaded.manifest.state_schema_version, "source_float_precision": loaded.manifest.float_precision,
            "source_metadata": dict(loaded.manifest.metadata or {}), "source_validation": "native_complete_container_replay"}
    elif raw.lstrip().startswith(b"{"):
        # Historical native JSON lacks a durable revision and may omit schema
        # tags. Verify the independently pinned bytes and selected component,
        # without importing the enormous legal heads into a mutable model.
        value = json.loads(raw)
        if type(value) is not dict or value.get("schema_version", "modal-autoencoder-state-v1") != "modal-autoencoder-state-v1":
            raise ValueError("unsupported legacy modal JSON schema")
        weights = value.get("feature_embedding_weights")
        if type(weights) is not dict:
            raise ValueError("native lexical component missing")
        architecture = value.get("architecture_version", "legacy_dense_v1")
        lineage = {"source_state_digest": None, "source_revision": None, "source_architecture": architecture,
            "source_schema": "modal-autoencoder-state-v1", "source_float_precision": "float64",
            "source_metadata": {}, "source_validation": "pinned_legacy_JSON_bytes_and_exact_lexical_component"}
    else:
        raise ValueError("complete native modal checkpoint required")
    if architecture not in {"legacy_dense_v1", "proof_aware_auxiliary_heads_v2"}:
        raise ValueError("unsupported source modal architecture")
    rows = {}
    for key, values in sorted(weights.items()):
        if not key.startswith("token:"):
            continue
        if not _TOKEN.fullmatch(key) or not isinstance(values, (list, tuple)) or not values:
            raise ValueError("malformed native lexical feature row")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError("finite lexical checkpoint values required")
        rows[key] = list(values)
    widths = {len(row) for row in rows.values()}
    if not 1 <= len(rows) <= 8192 or len(widths) != 1 or not 2 <= next(iter(widths)) <= 16:
        raise ValueError("compatible bounded exact lexical width required; no reshaping")
    if not any(v != 0 for row in rows.values() for v in row):
        raise ValueError("nonzero learned lexical source weights required")
    return {"schema": INITIALIZER_SCHEMA, "domain": DOMAIN,
        "component": "feature_embedding_weights", "selection": "token:* only",
        "tokenizer": "modal_autoencoder._token_features(max_tokens=40)",
        "native_model_sha256": _sha(Path(native.__file__).read_bytes()),
        "native_codec_sha256": _sha(Path(codec.__file__).read_bytes()),
        "transfer_implementation_sha256": _sha(Path(__file__).read_bytes()),
        "source_checkpoint_sha256": _sha(raw), **lineage,
        "source_fit_statistics": "not available in checkpoint; no training quality inferred from values",
        "embedding_width": next(iter(widths)), "keys": list(rows), "weights": list(rows.values()),
        "numeric_conversion": "none: source values and training tensors use float64",
        "legal_heads_loaded": False, "legal_views_loaded": False, "sample_memory_loaded": False,
        "proof_authority": False, "formalization_authority": False, "authority": "unverified_candidate_only"}


def _write(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        os.fchmod(stream.fileno(), 0o444)
        stream.flush()
        os.fsync(stream.fileno())


def _descriptor(output, manifest, raw):
    return {"schema": SCHEMA, "domain": DOMAIN, "output": str(output), "manifest_sha256": _sha(raw),
            "source_checkpoint_sha256": manifest["source_checkpoint_sha256"],
            "initializer_sha256": manifest["initializer_sha256"], "embedding_width": manifest["embedding_width"],
            "transferred_row_count": manifest["transferred_row_count"], "authority": "unverified_candidate_only",
            "runtime_validation_scope": "admitted_initializer_integrity_not_original_legal_state_replay"}


def fork_legal_shared_weights(*, source_checkpoint: Path, expected_sha256: str, output: Path) -> dict:
    """Pin a complete source snapshot and extract only compatible lexical rows.

    The caller supplies the reviewed source identity. Reads reject concurrent
    changes; a second hash check verifies the source remained unchanged during
    publication. Later validation relies on the immutable snapshot so ongoing
    legal training cannot silently change this fork.
    """
    source_checkpoint, output = Path(source_checkpoint).absolute(), Path(output).absolute()
    _namespace(output, True)
    if type(expected_sha256) is not str or _HASH.fullmatch(expected_sha256) is None:
        raise ValueError("independent exact source checkpoint SHA256 required")
    if source_checkpoint.is_relative_to(output) or output.is_relative_to(source_checkpoint.parent):
        raise ValueError("source and fork must occupy separate model namespaces")
    raw = _read(source_checkpoint, MAX_SOURCE_BYTES)
    if _sha(raw) != expected_sha256:
        raise ValueError("source checkpoint SHA256 differs from approved identity")
    initializer = _extract(raw)
    initializer_raw = _json(initializer)
    manifest = {"schema": SCHEMA, "domain": DOMAIN, "source_checkpoint_sha256": expected_sha256,
        "source_checkpoint_bytes": len(raw), "initializer_sha256": _sha(initializer_raw),
        "embedding_width": initializer["embedding_width"], "transferred_row_count": len(initializer["keys"]),
        "source_original_unchanged": True, "legal_state_mutated": False,
        "proof_authority": False, "formalization_authority": False,
        "authority": "unverified_candidate_only"}
    if _sha(_read(source_checkpoint, MAX_SOURCE_BYTES)) != expected_sha256:
        raise ValueError("source checkpoint changed during fork extraction")
    output.mkdir(parents=True, mode=0o700)
    _write(output / "source.checkpoint", raw)
    _write(output / "initializer.json", initializer_raw)
    manifest_raw = _json(manifest)
    _write(output / "manifest.json", manifest_raw)
    if _sha(_read(source_checkpoint, MAX_SOURCE_BYTES)) != expected_sha256:
        raise ValueError("source checkpoint changed during fork publication")
    return _descriptor(output, manifest, manifest_raw)


def validate_legal_shared_weight_fork(*, expected_receipt: dict, replay_source: bool = False) -> dict:
    """Validate pinned portable initializer, optionally replay host source bytes.

    Runtime integrity relies on the independently admitted descriptor pin; it
    does not independently re-extract the original LegalIR model. Host-side
    qualification explicitly uses ``replay_source=True`` with the retained
    full source snapshot. Neither mode opens mutable live legal state.
    """
    if type(expected_receipt) is not dict or set(expected_receipt) != _DESCRIPTOR_FIELDS:
        raise ValueError("exact immutable weight fork descriptor required")
    output = Path(expected_receipt["output"])
    _namespace(output, False)
    manifest_raw = _read(output / "manifest.json", 32_000)
    manifest = json.loads(manifest_raw)
    if _descriptor(output, manifest, manifest_raw) != expected_receipt:
        raise ValueError("weight fork descriptor changed")
    initializer_raw = _read(output / "initializer.json", 4_000_000)
    initializer = json.loads(initializer_raw)
    if _sha(initializer_raw) != expected_receipt["initializer_sha256"]:
        raise ValueError("forked lexical weights differ from admitted initializer")
    _validate_initializer(initializer, expected_receipt)
    if replay_source:
        raw = _read(output / "source.checkpoint", MAX_SOURCE_BYTES)
        if _sha(raw) != expected_receipt["source_checkpoint_sha256"] or len(raw) != manifest.get("source_checkpoint_bytes"):
            raise ValueError("immutable source snapshot changed")
        if initializer_raw != _json(_extract(raw)):
            raise ValueError("forked lexical weights differ from native source")
    if initializer_raw != _json(initializer):
        raise ValueError("forked lexical weights differ from native source")
    expected_manifest = {"schema": SCHEMA, "domain": DOMAIN, "source_checkpoint_sha256": expected_receipt["source_checkpoint_sha256"],
        "source_checkpoint_bytes": manifest.get("source_checkpoint_bytes"), "initializer_sha256": _sha(initializer_raw),
        "embedding_width": initializer["embedding_width"], "transferred_row_count": len(initializer["keys"]),
        "source_original_unchanged": True, "legal_state_mutated": False,
        "proof_authority": False, "formalization_authority": False,
        "authority": "unverified_candidate_only"}
    if manifest != expected_manifest:
        raise ValueError("weight fork namespace or authority differs")
    return initializer


def _validate_initializer(value, descriptor):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as codec
    constants = {"schema": INITIALIZER_SCHEMA, "domain": DOMAIN,
        "component": "feature_embedding_weights", "selection": "token:* only",
        "tokenizer": "modal_autoencoder._token_features(max_tokens=40)",
        "native_model_sha256": _sha(Path(native.__file__).read_bytes()),
        "native_codec_sha256": _sha(Path(codec.__file__).read_bytes()),
        "transfer_implementation_sha256": _sha(Path(__file__).read_bytes()),
        "numeric_conversion": "none: source values and training tensors use float64",
        "source_fit_statistics": "not available in checkpoint; no training quality inferred from values",
        "legal_heads_loaded": False, "legal_views_loaded": False, "sample_memory_loaded": False,
        "proof_authority": False, "formalization_authority": False, "authority": "unverified_candidate_only"}
    fields = set(constants) | {"source_checkpoint_sha256", "source_state_digest", "source_revision", "source_architecture",
        "source_schema", "source_float_precision", "source_metadata", "source_validation", "embedding_width", "keys", "weights"}
    if (type(value) is not dict or set(value) != fields or any(value.get(k) != v for k, v in constants.items())
            or any(value.get(k) is not False for k in ("legal_heads_loaded", "legal_views_loaded", "sample_memory_loaded", "proof_authority", "formalization_authority"))):
        raise ValueError("initializer schema, implementation or authority differs")
    keys, weights, width = value["keys"], value["weights"], value["embedding_width"]
    if (type(keys) is not list or len(keys) != descriptor["transferred_row_count"] or not 1 <= len(keys) <= 8192
            or keys != sorted(set(keys)) or any(type(k) is not str or not _TOKEN.fullmatch(k) for k in keys)
            or type(width) is not int or width != descriptor["embedding_width"] or not 2 <= width <= 16
            or type(weights) is not list or len(weights) != len(keys)
            or value["source_checkpoint_sha256"] != descriptor["source_checkpoint_sha256"]):
        raise ValueError("initializer lexical identities or dimensions differ")
    if any(type(row) is not list or len(row) != width or any(type(v) not in (int, float) or not math.isfinite(v) for v in row) for row in weights):
        raise ValueError("exact finite initializer rows required")


def lexical_observation(text: str, initializer: dict) -> dict:
    """Native exact lexical identities, with explicit per-sample OOV coverage."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import _token_features
    tokens = _token_features(text, max_tokens=40)
    positions = {key: index for index, key in enumerate(initializer["keys"])}
    indices = sorted({positions["token:" + token] for token in tokens if "token:" + token in positions})
    matched = sum("token:" + token in positions for token in tokens)
    return {"lexical_indices": indices, "lexical_coverage": {"selected_tokens": len(tokens),
            "in_vocabulary_tokens": matched, "oov_tokens": len(tokens) - matched,
            "unique_matched_keys": len(indices), "token_window": 40}}
