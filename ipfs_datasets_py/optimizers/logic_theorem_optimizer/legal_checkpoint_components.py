"""Optional lossless storage for canonical checkpoints with repeated tensor arrays.

This codec changes storage only. Unpack restores the exact canonical checkpoint
bytes for the existing model validator. It supplies no model or legal authority.
Callers must supply independently trusted checkpoint, state and source identities.
There is no filesystem access, external donor lookup or numerical-model import.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

SCHEMA = "legal-checkpoint-components/v1"
MAX_BYTES = 16_000_000
MAX_COMPONENTS = 4096
MAX_DEPTH = 128
MAX_NODES = 1_000_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(value, message):
    if not value:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    _require(type(value) is str and _SHA.fullmatch(value), "expected SHA256 required")
    return value


def _bounded(value):
    count = 0
    active = set()

    def visit(node, depth):
        nonlocal count
        count += 1
        _require(count <= MAX_NODES and depth <= MAX_DEPTH, "checkpoint structure bound exceeded")
        if type(node) in (dict, list):
            identity = id(node)
            _require(identity not in active, "cyclic structure refused")
            active.add(identity)
            if type(node) is dict:
                _require(all(type(k) is str for k in node), "string object keys required")
                for child in node.values():
                    visit(child, depth + 1)
            else:
                for child in node:
                    visit(child, depth + 1)
            active.remove(identity)
        else:
            _require(node is None or type(node) in (str, bool, int, float), "JSON scalar required")
            _require(type(node) is not float or math.isfinite(node), "nonfinite scalar refused")

    visit(value, 0)


def _read(raw, expected_sha256):
    _hash(expected_sha256)
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "bounded immutable bytes required")
    _require(_digest(raw) == expected_sha256, "raw identity differs")

    def unique(pairs):
        result = {}
        for k, v in pairs:
            _require(k not in result, "duplicate JSON key")
            result[k] = v
        return result

    def constant(value):
        raise ValueError("nonfinite JSON constant: " + value)

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
        _bounded(value)
        _require(_raw(value) == raw, "canonical JSON bytes required")
    except (RecursionError, UnicodeError, OverflowError) as error:
        raise ValueError("invalid bounded JSON structure") from error
    return value


def _shape(value):
    """Return a rectangular finite numeric shape, preserving scalar JSON types."""
    if type(value) in (int, float):
        _require(type(value) is not float or math.isfinite(value), "finite component required")
        return ()
    if type(value) is not list or not value:
        return None
    shapes = [_shape(child) for child in value]
    if any(s is None or s != shapes[0] for s in shapes):
        return None
    return (len(value), *shapes[0])


def _identity(checkpoint, raw):
    _require(type(checkpoint) is dict and type(checkpoint.get("schema")) is str
             and 0 < len(checkpoint["schema"]) <= 256, "checkpoint schema required")
    _require(type(checkpoint.get("model_state")) is dict and checkpoint["model_state"]
             and type(checkpoint.get("implementation")) is dict, "model state and implementation required")
    return dict(checkpoint_sha256=_digest(raw), checkpoint_bytes=len(raw),
                checkpoint_schema=checkpoint["schema"],
                model_state_sha256=_digest(_raw(checkpoint["model_state"])),
                implementation_sha256=_digest(_raw(checkpoint["implementation"])))


def _expected(identity, checkpoint_sha256, model_state_sha256, implementation_sha256):
    for name, expected in (("checkpoint_sha256", checkpoint_sha256),
                           ("model_state_sha256", model_state_sha256),
                           ("implementation_sha256", implementation_sha256)):
        _require(identity[name] == _hash(expected), "trusted checkpoint/state/source identity differs: " + name)


def pack_checkpoint(raw, *, expected_checkpoint_sha256, expected_model_state_sha256,
                    expected_implementation_sha256):
    """Deduplicate rectangular numeric arrays and retain all other checkpoint data."""
    checkpoint = _read(raw, expected_checkpoint_sha256)
    identity = _identity(checkpoint, raw)
    _expected(identity, expected_checkpoint_sha256, expected_model_state_sha256, expected_implementation_sha256)
    components = {}
    references = 0

    def encode(node):
        nonlocal references
        if type(node) is list:
            shape = _shape(node)
            if shape is not None:
                scalar_count = math.prod(shape)
                if scalar_count >= 8:
                    key = _digest(_raw(node))
                    component = dict(shape=list(shape), data=node)
                    _require(key not in components or _raw(components[key]) == _raw(component), "component identity conflict")
                    components[key] = component
                    _require(len(components) <= MAX_COMPONENTS, "component count bound exceeded")
                    references += 1
                    return ["component", key]
            return ["list", [encode(child) for child in node]]
        if type(node) is dict:
            return ["map", [[k, encode(node[k])] for k in sorted(node)]]
        return ["value", node]

    skeleton = encode(checkpoint)
    result = dict(schema=SCHEMA, manifest=dict(**identity, component_count=len(components),
                  component_references=references), skeleton=skeleton, components=components)
    _bounded(result)
    packed = _raw(result)
    _require(len(packed) <= MAX_BYTES, "packed byte bound exceeded")
    return packed


def unpack_checkpoint(packed, *, expected_archive_sha256, expected_checkpoint_sha256,
                      expected_model_state_sha256, expected_implementation_sha256):
    """Restore exact canonical bytes; reject missing, extra or corrupt components."""
    archive = _read(packed, expected_archive_sha256)
    _require(type(archive) is dict and set(archive) == {"schema", "manifest", "skeleton", "components"}
             and archive["schema"] == SCHEMA, "closed archive schema required")
    manifest = archive["manifest"]
    fields = {"checkpoint_sha256", "checkpoint_bytes", "checkpoint_schema", "model_state_sha256",
              "implementation_sha256", "component_count", "component_references"}
    _require(type(manifest) is dict and set(manifest) == fields, "closed manifest required")
    _expected(manifest, expected_checkpoint_sha256, expected_model_state_sha256, expected_implementation_sha256)
    _require(type(manifest["checkpoint_bytes"]) is int and 0 < manifest["checkpoint_bytes"] <= MAX_BYTES,
             "bounded decoded byte size required")
    components = archive["components"]
    _require(type(components) is dict and type(manifest["component_count"]) is int
             and len(components) == manifest["component_count"] <= MAX_COMPONENTS, "exact component inventory required")
    for key, component in components.items():
        _hash(key)
        _require(type(component) is dict and set(component) == {"shape", "data"}, "closed numeric component required")
        shape = component["shape"]
        _require(type(shape) is list and shape and all(type(n) is int and n > 0 for n in shape), "positive component shape required")
        _require(_shape(component["data"]) == tuple(shape) and math.prod(shape) >= 8
                 and _digest(_raw(component["data"])) == key, "component shape or bytes differ")
    used = set()
    references = 0
    visits = 0
    byte_limit = manifest["checkpoint_bytes"]
    component_sizes = {key: len(_raw(component["data"])) for key, component in components.items()}

    def decode(token, depth):
        nonlocal references, visits
        visits += 1
        _require(visits <= MAX_NODES and depth <= MAX_DEPTH, "decoded structure bound exceeded")
        _require(type(token) is list and len(token) == 2 and type(token[0]) is str, "closed typed token required")
        kind, value = token
        if kind == "component":
            _require(type(value) is str and value in components, "missing component reference")
            used.add(value); references += 1
            size = component_sizes[value]
            _require(size <= byte_limit, "expanded component byte bound exceeded")
            return components[value]["data"], size
        if kind == "value":
            _require(value is None or type(value) in (str, bool, int, float), "scalar token required")
            size = len(_raw(value))
            _require(size <= byte_limit, "expanded scalar byte bound exceeded")
            return value, size
        if kind == "list":
            _require(type(value) is list, "list token required")
            result, size = [], 2
            for child in value:
                item, amount = decode(child, depth + 1)
                size += amount + int(bool(result))
                _require(size <= byte_limit, "expanded list byte bound exceeded")
                result.append(item)
            return result, size
        _require(kind == "map" and type(value) is list, "known token kind required")
        result = {}
        size = 2
        previous = None
        for row in value:
            _require(type(row) is list and len(row) == 2 and type(row[0]) is str
                     and (previous is None or previous < row[0]), "strictly sorted unique map keys required")
            previous = row[0]
            item, amount = decode(row[1], depth + 1)
            size += len(_raw(row[0])) + 1 + amount + int(bool(result))
            _require(size <= byte_limit, "expanded map byte bound exceeded")
            result[row[0]] = item
        return result, size

    checkpoint, predicted_bytes = decode(archive["skeleton"], 0)
    _require(predicted_bytes == byte_limit, "decoded byte budget differs")
    _require(used == set(components) and type(manifest["component_references"]) is int
             and references == manifest["component_references"], "extra components or reference count drift")
    _bounded(checkpoint)
    raw = _raw(checkpoint)
    _require(len(raw) == manifest["checkpoint_bytes"] <= MAX_BYTES, "decoded byte size differs")
    identity = _identity(checkpoint, raw)
    _require(all(manifest[k] == v for k, v in identity.items()), "restored identity differs")
    _expected(identity, expected_checkpoint_sha256, expected_model_state_sha256, expected_implementation_sha256)
    return raw
