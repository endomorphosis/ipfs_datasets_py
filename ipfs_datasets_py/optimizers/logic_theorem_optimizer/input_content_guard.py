"""Fresh input-content checks without an unused canonical JSON digest.

Ordinary finite builtin JSON trees use an immutable structural snapshot. Flat
atom arrays are copied once and validated without recursively freezing every
scalar. Unusual JSON values retain the existing canonical encoder semantics.
This guard is for per-call inputs; it does not replace checkpoint identities.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import operator
from pathlib import Path


_HASH_SHA256 = hashlib.sha256
_JSON_DUMPS = json.dumps
_ISFINITE = math.isfinite
_COPYSIGN = math.copysign
_IS = operator.is_
_READ_BYTES = Path.read_bytes
_SOURCE_PATH = Path(__file__)


def _source_sha256():
    return _HASH_SHA256(_READ_BYTES(_SOURCE_PATH)).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()
_ATOM_TYPES = frozenset((type(None), bool, int, float, str))
_JSON_TYPES = _ATOM_TYPES | frozenset((dict, list, tuple))
_NUMERIC_TYPES = frozenset((bool, int, float))


class _UnsupportedFastValue(Exception):
    """Use canonical JSON for values outside the exact builtin tree path."""


@dataclass(frozen=True, slots=True)
class _Object:
    fields: tuple
    keys: frozenset


@dataclass(frozen=True, slots=True)
class _Array:
    items: tuple
    atoms: bool


def _raw(value):
    return _JSON_DUMPS(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False, ensure_ascii=True).encode()


def _validate_atom(value):
    kind = type(value)
    if kind is float and not _ISFINITE(value):
        raise ValueError("input content must contain only finite floats")
    if kind is int and value.bit_length() > 1024:
        # The canonical encoder uses Python's integer decimal conversion limit.
        # Validate rare large integers without serializing the ordinary tree.
        str(value)


def _freeze(value, active=None):
    kind = type(value)
    if kind in _ATOM_TYPES:
        _validate_atom(value)
        return value
    if kind not in (dict, list, tuple):
        raise _UnsupportedFastValue
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise ValueError("circular input content")
    active.add(identity)
    try:
        if kind is dict:
            if any(type(key) is not str for key in value):
                raise _UnsupportedFastValue
            return _Object(tuple((key, _freeze(item, active))
                                 for key, item in value.items()), frozenset(value))
        items = tuple(value)
        kinds = frozenset(map(type, items))
        if kinds <= _ATOM_TYPES:
            if kinds <= _NUMERIC_TYPES:
                try:
                    finite = all(map(_ISFINITE, items))
                except OverflowError:
                    # Large integers can be valid JSON although conversion to
                    # a double overflows; check their decimal limit separately.
                    finite = True
                    for item in items:
                        _validate_atom(item)
                if not finite:
                    raise ValueError("input content must contain only finite floats")
                if int in kinds:
                    for item in items:
                        if type(item) is int and item.bit_length() > 1024:
                            str(item)
            else:
                for item in items:
                    _validate_atom(item)
            return _Array(items, True)
        return _Array(tuple(_freeze(item, active) for item in items), False)
    finally:
        active.remove(identity)


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
        if expected.atoms and all(map(_IS, current, expected.items)):
            return True
        return all(_matches(left, right) for left, right in zip(current, expected.items))
    if kind is not type(expected):
        if kind not in _JSON_TYPES:
            raise _UnsupportedFastValue
        return False
    if kind is float:
        return (current == expected and
                (current != 0.0 or _COPYSIGN(1.0, current) == _COPYSIGN(1.0, expected)))
    return current == expected


def _thaw(reference):
    if type(reference) is _Object:
        return {key: _thaw(value) for key, value in reference.fields}
    if type(reference) is _Array:
        return [_thaw(value) for value in reference.items]
    return reference


def _verify_bindings():
    for name, expected in _GLOBAL_BINDINGS:
        if globals().get(name) is not expected:
            raise ValueError("input content guard callable or constant binding changed")
    for owner, name, function, code, defaults, kwdefaults, kwitems in _METHOD_BINDINGS:
        actual = owner.__dict__.get(name)
        if isinstance(actual, property):
            actual = actual.fget
        if (actual is not function or function.__code__ is not code or
                function.__defaults__ is not defaults or
                function.__kwdefaults__ is not kwdefaults or
                (kwdefaults is not None and tuple(kwdefaults.items()) != kwitems)):
            raise ValueError("input content guard method binding changed")
    for function, code, defaults, kwdefaults, kwitems in _FUNCTION_BINDINGS:
        if (function.__code__ is not code or function.__defaults__ is not defaults or
                function.__kwdefaults__ is not kwdefaults or
                (kwdefaults is not None and tuple(kwdefaults.items()) != kwitems)):
            raise ValueError("input content guard function binding changed")


def inference_implementation():
    """Verify current source and loaded callable identities without caching."""
    _verify_bindings()
    if _source_sha256() != _SOURCE_AT_IMPORT:
        raise ValueError("input content guard source changed since import")
    return {
        "schema": "input-content-guard-implementation/v1",
        "source_sha256": _SOURCE_AT_IMPORT,
        "comparison": "immutable-input-structural-content-with-canonical-json-fallback/v1",
        "standard_path_canonical_json_serialized": False,
        "standard_path_digest_computed": False,
        "atom_array_snapshot_per_scalar_freeze": False,
        "finite_float_required": True,
        "exact_builtin_atom_types": True,
        "signed_zero_checked": True,
        "list_tuple_equivalence": True,
        "dictionary_order_ignored": True,
        "current_content_fully_compared": True,
        "source_and_callable_bindings_checked": True,
        "success_or_revision_cached": False,
    }


@dataclass(frozen=True, slots=True, init=False)
class InputContentGuard:
    """Immutable input snapshot with the existing canonical fallback.

    Exact finite builtin trees retain no mutable container aliases and do not
    create an unused serialization or digest. Each comparison examines current
    content. Frozen fields prevent ordinary writes; session owners must also
    bind this guard object and snapshot identities against replacement.
    """
    _reference: object
    _canonical_bytes: bytes | None
    _use_fast_comparison: bool

    def __init__(self, value):
        _IMPLEMENTATION_AT_IMPORT()
        try:
            reference = _freeze(value)
            canonical = None
            use_fast = True
        except _UnsupportedFastValue:
            canonical = _raw(value)
            reference = None
            use_fast = False
        object.__setattr__(self, "_reference", reference)
        object.__setattr__(self, "_canonical_bytes", canonical)
        object.__setattr__(self, "_use_fast_comparison", use_fast)

    @property
    def inference_implementation(self):
        return _IMPLEMENTATION_AT_IMPORT()

    def matches(self, value):
        """Compare current inputs; implementation drift raises independently."""
        _IMPLEMENTATION_AT_IMPORT()
        try:
            if not self._use_fast_comparison:
                raise _UnsupportedFastValue
            return _matches(value, self._reference)
        except _UnsupportedFastValue:
            try:
                expected = (self._canonical_bytes if not self._use_fast_comparison
                            else _raw(_thaw(self._reference)))
                return _raw(value) == expected
            except (TypeError, ValueError, OverflowError, RecursionError):
                return False
        except (KeyError, RuntimeError, RecursionError):
            # Concurrent unsupported writes cannot yield an accepted partial
            # comparison. Owned session contracts separately disallow reentry.
            return False

    def check(self, value, *, message="input content changed"):
        if not _MATCHES_AT_IMPORT(self, value):
            raise ValueError(message)


_IMPLEMENTATION_AT_IMPORT = inference_implementation
_MATCHES_AT_IMPORT = InputContentGuard.matches
_GLOBAL_NAMES = (
    "_source_sha256", "_raw", "_validate_atom", "_freeze", "_matches", "_thaw",
    "_verify_bindings", "inference_implementation", "InputContentGuard", "_Object",
    "_Array", "_UnsupportedFastValue", "_HASH_SHA256", "_JSON_DUMPS", "_ISFINITE",
    "_COPYSIGN", "_IS", "_READ_BYTES", "_SOURCE_PATH", "_SOURCE_AT_IMPORT",
    "_ATOM_TYPES", "_JSON_TYPES", "_NUMERIC_TYPES", "_IMPLEMENTATION_AT_IMPORT",
    "_MATCHES_AT_IMPORT",
)
_GLOBAL_BINDINGS = tuple((name, globals()[name]) for name in _GLOBAL_NAMES)
_FUNCTION_BINDINGS = tuple(
    (function, function.__code__, function.__defaults__, function.__kwdefaults__,
     tuple(function.__kwdefaults__.items()) if function.__kwdefaults__ else ())
    for function in (_source_sha256, _raw, _validate_atom, _freeze, _matches,
                     _thaw, _verify_bindings, inference_implementation)
)
_METHOD_BINDINGS = tuple(
    (owner, name, function, function.__code__, function.__defaults__,
     function.__kwdefaults__,
     tuple(function.__kwdefaults__.items()) if function.__kwdefaults__ else ())
    for owner in (InputContentGuard, _Object, _Array)
    for name, value in owner.__dict__.items()
    for function in (value.fget if isinstance(value, property) else value,)
    if callable(function) and hasattr(function, "__code__")
)


__all__ = ["InputContentGuard", "inference_implementation"]
