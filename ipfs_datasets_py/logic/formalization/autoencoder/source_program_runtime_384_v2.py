"""Explicit Security-only compatibility for one unrelated UI decoder pin change.

The immutable artifact is checked against a caller-supplied SHA256. Only a
detached runtime view changes: one known historical UI decoder dependency pin
may move to its known current value. Every other implementation field, weight,
schema, split manifest and runtime check remains unchanged. This is not a
general checkpoint migration or permission to ignore numerical/validator drift.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re

from . import structured_source_384 as structured
from .source_program_runtime_384 import SourceProgramDecoder384, FALSE
from .normalized_source_program_runtime_384 import NormalizedSourceProgramDecoder384
from .security.source_normalization_384 import INPUT_VIEW

SCHEMA = "security-source-384-checkpoint-compatibility/v1"
PROFILE = "security-structured384-known-unrelated-ui-pin/v1"
UI_DEPENDENCY = "ipfs_datasets_py.logic.ui_ux_ir.decoder"
OLD_UI_SHA256 = "d7be6bff3a1f1464d4783567b90942258ef718bc1c2b7e02938698ed4e619e57"
NEW_UI_SHA256 = "21e8315b0054f7755512212d610d4e3f5f4ac86387f3b27edb9632fa8ca68bc3"
PIN_PATH = ("shared_runtime", "native", "dependencies", UI_DEPENDENCY)
COMPONENTS = ("projection_state", "head_state", "target_schema", "training_manifest",
    "validation_manifest", "parent_binding", "input_transform", "config", "training", "lineage")
UNCHANGED = dict(artifact_modified=False, runtime_view_persisted=False,
    numerical_weights_modified=False, target_schema_modified=False,
    training_manifests_modified=False, training_executed=False,
    provider_calls=0, download_calls=0, **FALSE)
SCOPE = ("Only a known unrelated UI decoder pin differs; the Security structured runtime, "
         "numerical implementation, Security validators and all checkpoint content except "
         "that implementation pin must remain exact. Receipt validation alone is not artifact replay.")


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    return _sha(structured._raw(value))


def _hash(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _pin(implementation):
    try:
        return implementation["shared_runtime"]["native"]["dependencies"][UI_DEPENDENCY]
    except (TypeError, KeyError) as error:
        raise ValueError("closed Security implementation pin tree required") from error


def _delta(original, current):
    if original == current:
        return "strict", []
    _require(_pin(original) == OLD_UI_SHA256 and _pin(current) == NEW_UI_SHA256,
        "only the known unrelated UI decoder pin transition is compatible")
    expected = deepcopy(current)
    expected["shared_runtime"]["native"]["dependencies"][UI_DEPENDENCY] = OLD_UI_SHA256
    _require(original == expected,
        "Security numerical, validator or other implementation pins differ")
    return "known_unrelated_ui_decoder_pin", [dict(path=list(PIN_PATH),
        before=OLD_UI_SHA256, after=NEW_UI_SHA256)]


def _receipt(checkpoint, view, artifact_sha256):
    original, current = checkpoint["implementation"], view["implementation"]
    mode, changed = _delta(original, current)
    before = {key: value for key, value in checkpoint.items() if key != "implementation"}
    after = {key: value for key, value in view.items() if key != "implementation"}
    _require(structured._raw(before) == structured._raw(after),
        "compatibility view changed checkpoint content")
    return dict(schema=SCHEMA, profile=PROFILE, domain_id="security_ir",
        checkpoint_schema=structured.SCHEMA, artifact_sha256=artifact_sha256,
        runtime_view_sha256=_digest(view), mode=mode, applied=bool(changed),
        original_implementation=deepcopy(original), runtime_implementation=deepcopy(current),
        original_implementation_sha256=_digest(original), runtime_implementation_sha256=_digest(current),
        changed_pins=changed, unchanged_content_sha256=_digest(before),
        unchanged_component_sha256={key: _digest(checkpoint[key]) for key in COMPONENTS},
        scope=SCOPE, **UNCHANGED)


def validate_checkpoint_compatibility(receipt, expected_sha256):
    """Validate closed metadata and current pins, without claiming artifact access.

    To verify content digests against bytes, use ``verify_checkpoint_compatibility``.
    No receipt, including this validated metadata, grants inference or proof authority.
    """
    _require(_hash(expected_sha256), "exact checkpoint SHA256 required")
    fields = {"schema", "profile", "domain_id", "checkpoint_schema", "artifact_sha256",
        "runtime_view_sha256", "mode", "applied", "original_implementation", "runtime_implementation",
        "original_implementation_sha256", "runtime_implementation_sha256", "changed_pins",
        "unchanged_content_sha256", "unchanged_component_sha256", "scope", *UNCHANGED}
    _require(type(receipt) is dict and set(receipt) == fields,
        "closed checkpoint compatibility receipt required")
    _require(receipt["schema"] == SCHEMA and receipt["profile"] == PROFILE
        and receipt["domain_id"] == "security_ir" and receipt["checkpoint_schema"] == structured.SCHEMA
        and receipt["artifact_sha256"] == expected_sha256 and receipt["scope"] == SCOPE,
        "checkpoint compatibility profile or artifact differs")
    _require(all(type(receipt[key]) is type(value) and receipt[key] == value
        for key, value in UNCHANGED.items()), "checkpoint compatibility cannot grant authority or mutation")
    current = structured._implementation()
    _require(receipt["runtime_implementation"] == current, "current implementation differs from compatibility receipt")
    mode, changes = _delta(receipt["original_implementation"], current)
    _require(receipt["mode"] == mode and type(receipt["applied"]) is bool
        and receipt["applied"] == bool(changes) and receipt["changed_pins"] == changes,
        "checkpoint compatibility pin delta differs")
    _require(receipt["original_implementation_sha256"] == _digest(receipt["original_implementation"])
        and receipt["runtime_implementation_sha256"] == _digest(current),
        "checkpoint compatibility implementation digest differs")
    _require(all(_hash(receipt[key]) for key in ("runtime_view_sha256", "unchanged_content_sha256")),
        "checkpoint compatibility content hashes required")
    components = receipt["unchanged_component_sha256"]
    _require(type(components) is dict and set(components) == set(COMPONENTS)
        and all(_hash(value) for value in components.values()),
        "closed unchanged checkpoint component hashes required")
    return deepcopy(receipt)


def _read_view(path, expected_sha256):
    _require(_hash(expected_sha256), "exact checkpoint SHA256 required")
    selected = Path(path)
    _require(selected.is_file() and not selected.is_symlink()
        and 0 < selected.stat().st_size <= structured.MAX_BYTES,
        "bounded regular checkpoint required")
    raw = selected.read_bytes()
    _require(_sha(raw) == expected_sha256, "checkpoint bytes differ")
    checkpoint = structured.native._parse(raw)
    _require(type(checkpoint) is dict and checkpoint.get("domain_id") == "security_ir"
        and checkpoint.get("schema") == structured.SCHEMA,
        "Security structured checkpoint required")
    _require({"implementation", *COMPONENTS} <= set(checkpoint),
        "complete Security checkpoint content required")
    current = structured._implementation()
    _delta(checkpoint.get("implementation"), current)
    view = deepcopy(checkpoint)
    view["implementation"] = current
    receipt = _receipt(checkpoint, view, expected_sha256)
    validate_checkpoint_compatibility(receipt, expected_sha256)
    return selected, raw, view, receipt


def verify_checkpoint_compatibility(receipt, path, expected_sha256):
    """Reload exact bytes and fully validate the detached runtime view and receipt."""
    validate_checkpoint_compatibility(receipt, expected_sha256)
    selected, raw, view, expected = _read_view(path, expected_sha256)
    structured.Runtime(view)  # Includes all numerical, schema, manifest and leakage checks.
    _require(selected.read_bytes() == raw, "checkpoint changed during compatibility verification")
    _require(structured._raw(receipt) == structured._raw(expected),
        "checkpoint compatibility differs from exact artifact replay")
    return expected


class CompatibleSourceProgramDecoder384:
    """Keep compatibility visible outside both raw and normalized consumers."""
    def __init__(self, decoder, receipt, *, input_view):
        self.decoder = decoder
        self.checkpoint_sha256 = receipt["artifact_sha256"]
        self._receipt = validate_checkpoint_compatibility(receipt, self.checkpoint_sha256)
        self.input_view = input_view

    def _attach(self, result):
        value = deepcopy(result)
        _require(value.get("domain_id") == "security_ir"
            and value.get("checkpoint_sha256") == self.checkpoint_sha256,
            "compatible decoder artifact or domain differs")
        value["checkpoint_compatibility"] = validate_checkpoint_compatibility(self._receipt, self.checkpoint_sha256)
        value["input_view"] = self.input_view
        return value

    def describe(self):
        return self._attach(self.decoder.describe())

    def infer(self, rows, **options):
        _require(self.input_view == "raw", "normalized input view requires infer_texts with source-bound embeddings")
        return self._attach(self.decoder.infer(rows, **options))

    def infer_texts(self, texts, *, snapshot_path=None, **options):
        return self._attach(self.decoder.infer_texts(texts, snapshot_path=snapshot_path, **options))


def load_source_program_decoder_384_v2(path, *, expected_sha256, decoder="structured", input_view="raw"):
    """Load Security weights with one explicit, exactly identified compatibility case."""
    _require(decoder == "structured", "compatibility loader supports structured Security checkpoints only")
    _require(input_view in ("raw", INPUT_VIEW), "unsupported source input view")
    selected, raw, view, receipt = _read_view(path, expected_sha256)
    runtime = structured.Runtime(view)
    source = SourceProgramDecoder384(runtime, checkpoint_sha256=expected_sha256)
    consumer = NormalizedSourceProgramDecoder384(source) if input_view == INPUT_VIEW else source
    _require(selected.read_bytes() == raw, "checkpoint changed during compatibility loading")
    return CompatibleSourceProgramDecoder384(consumer, receipt, input_view=input_view)


__all__ = ["SCHEMA", "PROFILE", "load_source_program_decoder_384_v2",
    "validate_checkpoint_compatibility", "verify_checkpoint_compatibility", "CompatibleSourceProgramDecoder384"]
