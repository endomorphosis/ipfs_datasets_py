"""Exact canonical checkpoint content checks without repeated float formatting.

Keep the original SHA-256 and freeze a private structural snapshot. Every check
compares the current content, including direct writes to base dict/list methods;
no mutation revision or retained mutable alias can bypass that comparison.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import operator
from pathlib import Path


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()
_ATOM_TYPES = frozenset((type(None), bool, int, float, str))
_JSON_TYPES = frozenset((type(None), bool, int, float, str, dict, list, tuple))


def inference_implementation():
    """Bind the separately owned guard implementation to its loaded source."""
    if _source_sha256() != _SOURCE_AT_IMPORT:
        raise ValueError("checkpoint content guard source changed since import")
    return {"schema": "checkpoint-content-guard-implementation/v1",
            "source_sha256": _SOURCE_AT_IMPORT,
            "comparison": "immutable-canonical-json-content/v1"}


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, ensure_ascii=True).encode()


class _UnsupportedFastValue(Exception):
    """Use the exact JSON encoder for values outside the standard fast path."""


@dataclass(frozen=True, slots=True)
class _Object:
    fields: tuple
    keys: frozenset


@dataclass(frozen=True, slots=True)
class _Array:
    items: tuple
    atoms: bool


def _freeze(value):
    kind = type(value)
    if kind is dict:
        if any(type(key) is not str for key in value):
            raise _UnsupportedFastValue
        return _Object(tuple((key, _freeze(item)) for key, item in value.items()),
                       frozenset(value))
    if kind in (list, tuple):
        items = tuple(_freeze(item) for item in value)
        return _Array(items, all(type(item) in _ATOM_TYPES for item in items))
    if kind in _ATOM_TYPES:
        # Exact built-in JSON atoms are immutable. Reusing them retains no
        # mutable alias and makes an unchanged leaf cheap to compare.
        return value
    raise _UnsupportedFastValue


def _matches(current, expected):
    if current is expected and type(expected) in _ATOM_TYPES:
        return True
    kind = type(current)
    if type(expected) is _Object:
        if kind is not dict:
            if kind not in _JSON_TYPES:
                raise _UnsupportedFastValue
            return False
        if any(type(key) is not str for key in current):
            raise _UnsupportedFastValue
        return (current.keys() == expected.keys and
                all(_matches(current[key], item) for key, item in expected.fields))
    if type(expected) is _Array:
        if kind not in (list, tuple):
            if kind not in _JSON_TYPES:
                raise _UnsupportedFastValue
            return False
        if len(current) != len(expected.items):
            return False
        # Only immutable JSON atoms qualify. Scan every item in C before
        # falling back to exact type/value/sign checks for replaced atoms.
        # Snapshot container objects must never be accepted as JSON values.
        if expected.atoms and all(map(operator.is_, current, expected.items)):
            return True
        return all(_matches(left, right) for left, right in zip(current, expected.items))
    if kind is not type(expected):
        if kind not in _JSON_TYPES:
            raise _UnsupportedFastValue
        return False
    if kind is float:
        # JSON distinguishes 1 from 1.0 and signed zeros. Type checks above
        # preserve the first distinction; compare the sign of equal zeros too.
        return (current == expected and
                (current != 0.0 or math.copysign(1.0, current) == math.copysign(1.0, expected)))
    return current == expected


@dataclass(frozen=True, slots=True, init=False)
class CheckpointContentGuard:
    """An immutable snapshot matching the original canonical JSON digest.

    List and tuple arrays and dictionary key order have identical canonical
    JSON semantics. Numeric types and signed zero remain distinct. Unusual
    JSON-serializable subclasses use the original encoder as a safe fallback.
    """
    _reference: object
    _canonical_bytes: bytes
    _sha256: str
    _use_fast_comparison: bool

    def __init__(self, checkpoint, *, expected_sha256=None):
        inference_implementation()
        raw = _raw(checkpoint)
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and expected_sha256 != digest:
            raise ValueError("checkpoint content SHA-256 differs from expected checkpoint")
        try:
            reference = _freeze(checkpoint)
            use_fast = True
        except _UnsupportedFastValue:
            reference = _freeze(json.loads(raw))
            # Sorting non-string dictionary keys precedes JSON key conversion.
            # Preserve those original bytes rather than assuming normalized
            # string keys would have the same canonical ordering.
            use_fast = False
        object.__setattr__(self, "_reference", reference)
        object.__setattr__(self, "_canonical_bytes", raw)
        object.__setattr__(self, "_sha256", digest)
        object.__setattr__(self, "_use_fast_comparison", use_fast)

    @property
    def sha256(self):
        return self._sha256

    @property
    def inference_implementation(self):
        return inference_implementation()

    def matches(self, checkpoint):
        """Compare all current content; source drift raises independently."""
        inference_implementation()
        try:
            if not self._use_fast_comparison:
                raise _UnsupportedFastValue
            return _matches(checkpoint, self._reference)
        except _UnsupportedFastValue:
            try:
                return _raw(checkpoint) == self._canonical_bytes
            except (TypeError, ValueError, OverflowError, RecursionError):
                return False

    def check(self, checkpoint, *, message="checkpoint content changed"):
        if not self.matches(checkpoint):
            raise ValueError(message)


__all__ = ["CheckpointContentGuard", "inference_implementation"]
