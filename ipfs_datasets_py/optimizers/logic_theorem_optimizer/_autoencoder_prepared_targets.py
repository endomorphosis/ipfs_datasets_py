"""Private runtime values derived *after* complete worker target validation.

These objects confer no verification authority and are not an artifact codec.
Only the worker owns the original hydrated targets. Public evaluators continue
to observe caller-owned mutable and custom targets through their existing path.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from types import FunctionType, MappingProxyType
from typing import Mapping

from ipfs_datasets_py.logic.bridge import multiview, types as bridge_types


_TARGET = multiview.LegalIRTrainingTarget
_DOCUMENT = bridge_types.LegalIRDocument
_VIEW = bridge_types.LogicIRView
_COMMON_CLASS_KEYS = frozenset({
    "__module__", "__annotations__", "__doc__", "__dict__", "__weakref__",
    "__dataclass_params__", "__dataclass_fields__", "__init__", "__repr__",
    "__eq__", "__setattr__", "__delattr__", "__hash__", "__match_args__",
})
_CLASS_KEYS = {
    _TARGET: _COMMON_CLASS_KEYS | {"accepted", "total_loss", "to_dict"},
    _DOCUMENT: _COMMON_CLASS_KEYS | {"source", "citation", "version", "has_frame_logic",
                                     "to_dict", "to_json", "canonical_hash"},
    _VIEW: _COMMON_CLASS_KEYS | {"format", "source_component", "to_dict"},
}
_FIELD_NAMES = {
    _TARGET: frozenset({"bridge_names", "document", "losses", "adapter_losses", "view_distribution", "accepted"}),
    _DOCUMENT: frozenset({"document_id", "source_text", "normalized_text", "source", "citation",
                          "views", "frame_logic_triples", "metadata", "version"}),
    _VIEW: frozenset({"name", "payload", "format", "source_component", "metadata"}),
}


# Capture before the native worker hydrates targets. These are local mutation
# guards, not attestation of Python code loaded before this module was imported.
_CLASS_STATE = {cls: dict(vars(cls)) for cls in _CLASS_KEYS}
_ANNOTATIONS = {cls: dict(vars(cls)["__annotations__"]) for cls in _CLASS_KEYS}
_FIELDS = {cls: dict(vars(cls)["__dataclass_fields__"]) for cls in _CLASS_KEYS}
_FUNCTION_STATE = {
    value: (value.__code__, value.__defaults__, value.__kwdefaults__)
    for state in _CLASS_STATE.values() for value in state.values() if type(value) is FunctionType
}
_FUNCTION_STATE.update({
    value.fget: (value.fget.__code__, value.fget.__defaults__, value.fget.__kwdefaults__)
    for state in _CLASS_STATE.values() for value in state.values()
    if type(value) is property and type(value.fget) is FunctionType
})


def _native_classes_unchanged():
    if (vars(multiview).get("LegalIRTrainingTarget") is not _TARGET
            or vars(bridge_types).get("LegalIRDocument") is not _DOCUMENT
            or vars(bridge_types).get("LogicIRView") is not _VIEW
            or _TARGET.__dict__.get("to_dict") is not vars(multiview).get("_NATIVE_LEGAL_IR_TRAINING_TARGET_TO_DICT")):
        return False
    for cls, expected_keys in _CLASS_KEYS.items():
        state = vars(cls)
        if set(state) != expected_keys:
            return False
        for name, previous in _CLASS_STATE[cls].items():
            value = state[name]
            if name == "__annotations__":
                if type(value) is not dict or value != _ANNOTATIONS[cls]:
                    return False
            elif name == "__dataclass_fields__":
                if type(value) is not dict or value != _FIELDS[cls] or set(value) != _FIELD_NAMES[cls]:
                    return False
            elif value is not previous:
                return False
            if type(value) is FunctionType and (
                value.__code__, value.__defaults__, value.__kwdefaults__
            ) != _FUNCTION_STATE[value]:
                return False
            if type(value) is property:
                getter = value.fget
                if type(getter) is not FunctionType or (
                    getter.__code__, getter.__defaults__, getter.__kwdefaults__
                ) != _FUNCTION_STATE.get(getter):
                    return False
    return True


def _ordinary_fields(value, cls):
    if type(value) is not cls:
        return None
    fields = object.__getattribute__(value, "__dict__")
    return fields if type(fields) is dict and set(fields) == _FIELD_NAMES[cls] else None


def _numeric_mapping(value):
    if type(value) is not dict:
        return False
    for key, number in value.items():
        if type(key) is not str or type(number) not in (int, float):
            return False
        try:
            if not math.isfinite(number):
                return False
        except OverflowError:
            return False
    return True


def _eligible(target, sample_id):
    fields = _ordinary_fields(target, _TARGET)
    if fields is None:
        return "non_native_target_or_fields"
    document = _ordinary_fields(fields["document"], _DOCUMENT)
    if document is None:
        return "non_native_document_or_fields"
    if (type(sample_id) is not str or type(document["document_id"]) is not str
            or document["document_id"] != sample_id or type(document["version"]) is not str):
        return "non_native_document_identity"
    if type(document["views"]) is not dict or any(
        type(name) is not str or _ordinary_fields(view, _VIEW) is None
        for name, view in document["views"].items()
    ):
        return "non_native_views_or_fields"
    if type(fields["bridge_names"]) not in (list, tuple) or any(
        type(name) is not str for name in fields["bridge_names"]
    ) or type(fields["accepted"]) is not bool:
        return "non_native_target_identity"
    if not _numeric_mapping(fields["losses"]) or not _numeric_mapping(fields["view_distribution"]):
        return "non_native_numeric_mappings"
    # Adapter losses remain part of the native cache-summary consumer's shape.
    adapters = fields["adapter_losses"]
    if type(adapters) is not dict or any(
        type(name) is not str or not _numeric_mapping(values) for name, values in adapters.items()
    ):
        return "non_native_adapter_losses"
    return None


@dataclass(frozen=True, slots=True)
class _PreparedNativeDocument:
    document_hash: str
    document_id: str
    version: str

    def canonical_hash(self):
        return self.document_hash


@dataclass(frozen=True, slots=True)
class _PreparedNativeTarget:
    bridge_names: tuple[str, ...]
    document: _PreparedNativeDocument
    losses: Mapping[str, float]
    adapter_losses: Mapping[str, Mapping[str, float]]
    view_distribution: Mapping[str, float]
    accepted: bool

    @property
    def total_loss(self):
        return float(self.losses.get("legal_ir_multiview_total_loss", 0.0))


def _prepare_native_targets(targets):
    """Derive immutable native values, or return the identical original map.

    This is an eligibility/conversion helper, NOT source or artifact validation.
    Unsupported envelopes return without invoking their getters/serializers.
    Nested values must already come from the worker's strict native hydration;
    this is not recursive validation of arbitrary caller-owned native objects.
    Hashing errors propagate. The caller must release its original mapping.
    """
    started = time.perf_counter()
    telemetry = {"applied": False, "skip_reason": None, "original_target_count": len(targets)
                 if type(targets) is dict else None, "prepared_target_count": 0,
                 "preparation_seconds": 0.0, "hash_seconds": 0.0}

    def unchanged(reason):
        telemetry["skip_reason"] = reason
        telemetry["preparation_seconds"] = time.perf_counter() - started
        return targets, telemetry

    if type(targets) is not dict or not targets:
        return unchanged("non_native_or_empty_target_mapping")
    if not _native_classes_unchanged():
        return unchanged("native_class_contract_changed")
    for sample_id, target in targets.items():
        reason = _eligible(target, sample_id)
        if reason is not None:
            return unchanged(reason)
    prepared = {}
    for sample_id, target in targets.items():
        fields = object.__getattribute__(target, "__dict__")
        document = fields["document"]
        hash_started = time.perf_counter()
        document_hash = document.canonical_hash()
        telemetry["hash_seconds"] += time.perf_counter() - hash_started
        prepared[sample_id] = _PreparedNativeTarget(
            bridge_names=tuple(fields["bridge_names"]),
            document=_PreparedNativeDocument(document_hash, document.document_id, document.version),
            losses=MappingProxyType(dict(fields["losses"])),
            adapter_losses=MappingProxyType({name: MappingProxyType(dict(values))
                                            for name, values in fields["adapter_losses"].items()}),
            view_distribution=MappingProxyType(dict(fields["view_distribution"])),
            accepted=fields["accepted"],
        )
    telemetry.update(applied=True, prepared_target_count=len(prepared),
                     preparation_seconds=time.perf_counter() - started)
    return MappingProxyType(prepared), telemetry
