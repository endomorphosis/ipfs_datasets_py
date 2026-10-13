"""Intent-only compatibility for the exact reviewed tree diagnostic transition.

The structured numerical loader remains strict. This adapter permits only the
known stdout-to-stderr diagnostic change in a detached runtime view, while
preserving the caller-pinned artifact and every other implementation field.
It does not permit Security's unrelated UI-decoder transition for Intent.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import stat

from . import structured_source_384 as structured

SCHEMA = "intent-action-384-checkpoint-compatibility/v1"
PROFILE = "intent-structured384-known-stderr-tree-pin/v1"
TREE_PIN_PATH = ("shared_runtime", "numerical", "files", "tree_pin.py")
OLD_TREE_SHA256 = "587165942fb06ea9effc836b555e0ac0606c5876b013a374a1e76d25ee069e4d"
NEW_TREE_SHA256 = "ec43fd9379f3c9198451e8d62d98db53826dcf115e6858039a73c3da7d72a1c2"
COMPONENTS = ("projection_state", "head_state", "target_schema", "training_manifest",
    "validation_manifest", "parent_binding", "input_transform", "config", "training", "lineage")
FALSE = dict(artifact_modified=False, runtime_view_persisted=False,
    numerical_weights_modified=False, target_schema_modified=False,
    training_manifests_modified=False, training_executed=False,
    provider_calls=0, download_calls=0, **structured.FALSE)
SCOPE = ("Only the exact reviewed tree diagnostic stdout-to-stderr pin transition may differ. "
    "Intent validators, numerical code, checkout rejection, weights, schema and every other "
    "checkpoint field remain exact. Compatibility does not establish instruction meaning or proof.")


def _require(value, message):
    if not value:
        raise ValueError(message)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    return _sha(structured._raw(value))


def _tree_pin(implementation):
    try:
        for key in TREE_PIN_PATH:
            implementation = implementation[key]
    except (KeyError, TypeError) as error:
        raise ValueError("complete Intent implementation pin tree required") from error
    return implementation


def _delta(original, current):
    if original == current:
        return "strict", []
    _require(_tree_pin(original) == OLD_TREE_SHA256 and _tree_pin(current) == NEW_TREE_SHA256,
        "only the known tree diagnostic stderr pin transition is compatible")
    expected = deepcopy(current)
    expected["shared_runtime"]["numerical"]["files"]["tree_pin.py"] = OLD_TREE_SHA256
    _require(original == expected, "Intent numerical, validator or other implementation pins differ")
    return "known_tree_pin_stderr_diagnostic", [dict(path=list(TREE_PIN_PATH),
        before=OLD_TREE_SHA256, after=NEW_TREE_SHA256)]


def _read_regular(path):
    """Bounded regular-file reads, including the post-load endpoint fence."""
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= structured.MAX_BYTES,
        "bounded regular checkpoint required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require(stat.S_ISREG(opened.st_mode) and identity(opened) == identity(before),
            "checkpoint identity changed before reading")
        raw = stream.read(structured.MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    final = path.lstat()
    _require(len(raw) <= structured.MAX_BYTES and stat.S_ISREG(final.st_mode)
        and identity(before) == identity(after) == identity(final),
        "checkpoint identity changed during reading")
    return raw, identity(final)


def _read_view(path, expected_sha256):
    _require(type(expected_sha256) is str and re.fullmatch(r"[a-f0-9]{64}", expected_sha256),
        "exact checkpoint SHA256 required")
    selected = Path(path)
    raw, witness = _read_regular(selected)
    _require(_sha(raw) == expected_sha256, "checkpoint bytes differ")
    checkpoint = structured.native._parse(raw)
    _require(type(checkpoint) is dict and checkpoint.get("schema") == structured.SCHEMA
        and checkpoint.get("domain_id") == "intent_ir", "Intent structured checkpoint required")
    _require({"implementation", *COMPONENTS} <= set(checkpoint), "complete Intent checkpoint content required")
    current = structured._implementation()
    mode, changes = _delta(checkpoint["implementation"], current)
    view = deepcopy(checkpoint)
    view["implementation"] = deepcopy(current)
    original_content = {key: value for key, value in checkpoint.items() if key != "implementation"}
    runtime_content = {key: value for key, value in view.items() if key != "implementation"}
    _require(structured._raw(original_content) == structured._raw(runtime_content),
        "compatibility view changed checkpoint content")
    receipt = dict(schema=SCHEMA, profile=PROFILE, domain_id="intent_ir",
        checkpoint_schema=structured.SCHEMA, artifact_sha256=expected_sha256,
        runtime_view_sha256=_digest(view), mode=mode, applied=bool(changes), changed_pins=changes,
        original_implementation=deepcopy(checkpoint["implementation"]), runtime_implementation=deepcopy(current),
        unchanged_content_sha256=_digest(original_content),
        unchanged_component_sha256={key: _digest(checkpoint[key]) for key in COMPONENTS},
        scope=SCOPE, **FALSE)
    return selected, raw, view, receipt, witness


def load_intent_action_checkpoint_384(path, *, expected_sha256):
    """Return a fully validated runtime and explicit receipt; never persist a view.

    No embedding model or numerical inference is executed here. All ordinary
    structured checks still apply to the detached view, including weights,
    domain, typed schema, split manifests and training provenance.
    """
    selected, raw, view, receipt, witness = _read_view(path, expected_sha256)
    runtime = structured.Runtime(view)
    _require(structured._implementation() == view["implementation"],
        "Intent implementation changed during compatibility loading")
    final_raw, final_witness = _read_regular(selected)
    _require(final_raw == raw and final_witness == witness, "checkpoint changed during compatibility loading")
    return runtime, deepcopy(receipt)


def verify_intent_action_checkpoint_compatibility(receipt, *, path, expected_sha256):
    """Replay all artifact/runtime checks before accepting saved metadata."""
    _require(type(receipt) is dict and len(structured._raw(receipt)) <= 65536,
        "bounded Intent checkpoint compatibility receipt required")
    _, expected = load_intent_action_checkpoint_384(path, expected_sha256=expected_sha256)
    _require(structured._raw(receipt) == structured._raw(expected),
        "Intent checkpoint compatibility differs from exact artifact replay")
    return expected


__all__ = ["SCHEMA", "PROFILE", "load_intent_action_checkpoint_384",
    "verify_intent_action_checkpoint_compatibility"]
