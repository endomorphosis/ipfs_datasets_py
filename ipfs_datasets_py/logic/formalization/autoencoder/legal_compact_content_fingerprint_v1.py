"""Bounded byte-compatible framed fingerprints for ordinary compact inputs.

The reference is trained_runtime_v2._copy followed by head_v1._fingerprint,
on stable plain inputs within the declared bounds. The head's standalone
fingerprint does not enforce aggregate bounds. This utility imports neither
owner, changes no consumer and grants no source/input custody by itself.
"""
from __future__ import annotations

import hashlib
from json.encoder import encode_basestring
import math


DEFAULT_MAXIMUM = 24 * 1024 * 1024
MAXIMUM = 64 * 1024 * 1024
MAX_JSON_ITEMS = 12_000_000
MAX_JSON_DEPTH = 96


class FingerprintError(ValueError):
    """The offered value or bound is outside the finite plain-input domain."""


def _need(condition, message):
    if not condition:
        raise FingerprintError(message)


def _stream(value, sink, *, maximum=DEFAULT_MAXIMUM, allow_bytes=True):
    """Send the exact d/l/b/j framed bytes to a private caller-supplied sink.

This test seam returns None, never a materialized stream. A refused input may
already have emitted a prefix: callers must discard it. The public fingerprint
exposes no digest unless the entire traversal succeeds.
"""
    _need(type(maximum) is int and 0 <= maximum <= MAXIMUM,
          "maximum must be a plain integer from zero through 64 MiB")
    _need(type(allow_bytes) is bool, "allow_bytes must be a plain boolean")
    _need(callable(sink), "private stream sink must be callable")
    remaining, items, active = maximum, MAX_JSON_ITEMS, set()

    def charge(count):
        nonlocal remaining
        remaining -= count
        _need(remaining >= 0, "whole JSON byte bound exceeded")

    def string_bytes(item):
        # Charge the original runtime's JSON footprint before allocating the
        # escaped scalar. This preserves early bounds for escape-heavy strings.
        _need(len(item) <= maximum, "bounded plain string required")
        charge(2)
        for character in item:
            code = ord(character)
            _need(code != 0 and not 0xD800 <= code <= 0xDFFF,
                  "ordinary scalar UTF8 required")
            if character in ('"', "\\") or character in "\b\f\n\r\t":
                charge(2)
            elif code < 32:
                charge(6)
            else:
                charge(1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
        # This is the same standard-library string encoder used by canonical
        # json.dumps(..., ensure_ascii=False), including its qualified fallback.
        return encode_basestring(item).encode("utf-8")

    def scalar(marker, body):
        sink(marker + str(len(body)).encode("ascii") + b":")
        sink(body)

    def visit(item, depth):
        nonlocal items
        items -= 1
        _need(items >= 0 and depth <= MAX_JSON_DEPTH, "whole JSON item/depth bound exceeded")
        kind = type(item)
        if kind is dict or kind is list:
            _need(id(item) not in active and len(item) <= items,
                  "cyclic or oversized ordinary container")
            active.add(id(item))
            try:
                charge(2)
                if kind is dict:
                    # Reject nonplain keys before sorting; never dispatch
                    # arbitrary comparison methods on offered key objects.
                    _need(all(type(key) is str for key in item), "plain string keys required")
                    sink(b"d" + str(len(item)).encode("ascii") + b":")
                    for index, key in enumerate(sorted(item)):
                        charge(1 + bool(index))
                        visit(key, depth + 1)
                        visit(item[key], depth + 1)
                else:
                    sink(b"l" + str(len(item)).encode("ascii") + b":")
                    for index, child in enumerate(item):
                        if index:
                            charge(1)
                        visit(child, depth + 1)
            finally:
                active.remove(id(item))
            return
        if kind is bytes and allow_bytes:
            charge(len(item))
            scalar(b"b", item)
        elif kind is str:
            scalar(b"j", string_bytes(item))
        elif item is None:
            charge(4)
            scalar(b"j", b"null")
        elif kind is bool:
            body = b"true" if item else b"false"
            charge(len(body))
            scalar(b"j", body)
        elif kind is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded plain integer required")
            body = str(item).encode("ascii")
            charge(len(body))
            scalar(b"j", body)
        elif kind is float:
            _need(math.isfinite(item), "finite plain number required")
            # Plain finite float repr is the JSON encoder's float spelling,
            # including -0.0, subnormal/exponent forms and its .0 distinction.
            body = repr(item).encode("ascii")
            charge(len(body))
            scalar(b"j", body)
        else:
            raise FingerprintError("ordinary containers/primitives required")

    try:
        visit(value, 0)
    except (RuntimeError, RecursionError, KeyError, UnicodeError) as error:
        raise FingerprintError("stable bounded ordinary input required") from error


def fingerprint(value, *, maximum=DEFAULT_MAXIMUM, allow_bytes=True):
    """Return the exact legacy head-framed SHA256 after bounded validation.

maximum charges the runtime-copy JSON footprint (raw length for byte leaves),
not framed-stream length. Plain dict/list/bytes/str/None/bool/int/float only;
aliases are traversed independently and ancestor cycles refuse. No object hash
cache, snapshot, lock, source fence or numerical operation is provided.
"""
    result = hashlib.sha256()
    _stream(value, result.update, maximum=maximum, allow_bytes=allow_bytes)
    return result.hexdigest()


__all__ = ["FingerprintError", "fingerprint"]
