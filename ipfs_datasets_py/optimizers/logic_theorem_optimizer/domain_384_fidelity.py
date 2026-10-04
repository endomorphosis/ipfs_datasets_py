"""Complete JSON value weighting and post-inference fidelity diagnostics.

These helpers own no vocabulary, model, decoder, or native schema. Alignment
matches domain_384_autoencoder's canonical JSON tokens. Every scalar value,
including discriminators, enums, booleans, nulls and numbers, receives the same
configurable value weight. Keys and punctuation remain in the objective.

Generated tokens are parsed without reference to expected targets. Comparisons
are evaluation-only, preserve types and array order, and confer no authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

SCHEMA = "domain-384-complete-json-fidelity/v1"
MAX_BYTES = 128 * 1024
MAX_TOKENS = 1022
MAX_DEPTH = 64
MAX_NODES = 4096
FALSE = {"qualified": False, "admitted": False, "proof_authority": False,
         "source_semantics_verified": False, "lake_executed": False}
_TOKEN = re.compile(
    r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
    r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
    r'|true|false|null|[{}\[\],:]'
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _type(value):
    return {dict: "object", list: "array", str: "string", bool: "boolean",
            int: "integer", float: "number", type(None): "null"}[type(value)]


def _pointer(path):
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1")
                   for part in path)


def _bounded(value):
    """Validate before recursive encoding; no implicit coercion or field loss."""
    active, nodes = set(), 0

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        _require(nodes <= MAX_NODES and depth <= MAX_DEPTH,
                 "JSON target exceeds node or depth bound")
        _require(type(item) in (dict, list, str, bool, int, float, type(None)),
                 "closed JSON types required")
        if type(item) is float:
            _require(math.isfinite(item), "nonfinite JSON number")
        elif type(item) is int:
            _require(item.bit_length() <= 4096, "JSON integer exceeds bound")
        elif type(item) is str:
            _require(len(item) <= MAX_BYTES, "JSON string exceeds bound")
        if type(item) in (dict, list):
            _require(id(item) not in active, "cyclic JSON target")
            active.add(id(item))
            _require(len(item) <= MAX_NODES, "JSON container exceeds bound")
            if type(item) is dict:
                for key, child in item.items():
                    _require(type(key) is str and len(key) <= MAX_BYTES,
                             "bounded JSON string keys required")
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            active.remove(id(item))

    visit(value, 0)
    chunks, size = [], 0
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False)
    for chunk in encoder.iterencode(value):
        size += len(chunk)  # ensure_ascii guarantees one byte per character.
        _require(size <= MAX_BYTES, "JSON target exceeds byte bound")
        chunks.append(chunk)
    return "".join(chunks)


def target_token_alignment(target, *, scalar_value_weight=4.0):
    """Return all canonical target tokens with JSON-pointer paths and weights.

    Object keys sort exactly as the baseline JSON codec. Array positions retain
    order. The empty pointer denotes the root. ``path_segments`` distinguish
    numeric object keys (strings) from array positions (integers).
    No special BOS/EOS/PAD tokens are part of this lexical result.
    """
    _require(type(scalar_value_weight) in (int, float)
             and math.isfinite(scalar_value_weight)
             and 1 <= scalar_value_weight <= 100,
             "scalar_value_weight must be finite and between 1 and 100")
    encoded = _bounded(target)
    alignment = []

    def emit(token, role, path, value=None):
        _require(len(alignment) < MAX_TOKENS, "target exceeds token bound")
        alignment.append({"index": len(alignment), "token": token,
                          "role": role, "path": _pointer(path),
                          "path_segments": list(path),
                          "value_type": _type(value) if role == "scalar_value" else None,
                          "weight": float(scalar_value_weight) if role == "scalar_value" else 1.0})

    def walk(value, path):
        if type(value) is dict:
            emit("{", "structure", path)
            for index, key in enumerate(sorted(value)):
                child = path + (key,)
                if index:
                    emit(",", "structure", path)
                emit(_raw(key), "key", child)
                emit(":", "structure", child)
                walk(value[key], child)
            emit("}", "structure", path)
        elif type(value) is list:
            emit("[", "structure", path)
            for index, child in enumerate(value):
                if index:
                    emit(",", "structure", path)
                walk(child, path + (index,))
            emit("]", "structure", path)
        else:
            emit(_raw(value), "scalar_value", path, value)

    walk(target, ())
    tokens = [item["token"] for item in alignment]
    _require("".join(tokens) == encoded and tokens == _TOKEN.findall(encoded),
             "canonical JSON token alignment differs")
    return {"schema": SCHEMA, "canonical_json": encoded,
            "target_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "tokens": tokens, "alignment": alignment,
            "weights": [item["weight"] for item in alignment],
            "scalar_value_count": sum(item["role"] == "scalar_value" for item in alignment),
            "scalar_value_weight": float(scalar_value_weight),
            "special_tokens_included": False, **FALSE}


def teacher_forcing_weights(target, *, width, scalar_value_weight=4.0):
    """Weights for shifted prediction labels: target tokens, EOS=1, PAD=0.

    ``width`` is labels[:, 1:] width, not the BOS-inclusive sequence width.
    BOS is only decoder input and never receives a prediction weight.
    No token truncation or vocabulary construction occurs here.
    """
    _require(type(width) is int and 1 <= width <= MAX_TOKENS + 1,
             "bounded prediction-label width required")
    weights = target_token_alignment(target, scalar_value_weight=scalar_value_weight)["weights"]
    _require(width >= len(weights) + 1, "width would omit target tokens or EOS")
    return weights + [1.0] + [0.0] * (width - len(weights) - 1)


def parse_generated(generated_tokens, *, ended):
    """Parse a completed runtime token sequence without receiving any target.

    The runtime reports EOS separately through ``ended``. PAD, BOS, EOS strings
    in the lexical sequence are invalid; premature termination is never treated
    as a valid candidate even when the available prefix happens to be JSON.
    """
    result = {"json_valid": False, "candidate": None, "status": None,
              "error": None, "target_access": False, **FALSE}
    if type(ended) is not bool:
        return {**result, "status": "invalid_generation_metadata", "error": "ended must be boolean"}
    if not ended:
        return {**result, "status": "incomplete_generation", "error": "EOS was not generated"}
    if (type(generated_tokens) is not list or not 1 <= len(generated_tokens) <= MAX_TOKENS
            or any(type(token) is not str or not 0 < len(token) <= MAX_BYTES
                   for token in generated_tokens)):
        return {**result, "status": "invalid_token_sequence", "error": "bounded nonempty lexical tokens required"}
    try:
        byte_count = sum(len(token.encode()) for token in generated_tokens)
    except UnicodeError:
        return {**result, "status": "invalid_token_sequence", "error": "generated tokens contain invalid Unicode"}
    if byte_count > MAX_BYTES:
        return {**result, "status": "invalid_token_sequence", "error": "generated JSON exceeds byte bound"}
    if any(_TOKEN.fullmatch(token) is None for token in generated_tokens):
        return {**result, "status": "invalid_token_sequence", "error": "invalid JSON lexical token"}

    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate generated JSON key")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite generated JSON number")

    try:
        candidate = json.loads("".join(generated_tokens), object_pairs_hook=unique,
                               parse_constant=nonfinite)
        _bounded(candidate)
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        return {**result, "status": "invalid_generated_json", "error": str(exc)[:512]}
    return {**result, "json_valid": True, "candidate": candidate,
            "status": "parsed_unqualified_json"}


def _leaves(value, path=()):
    if type(value) is dict:
        return [item for key in sorted(value) for item in _leaves(value[key], path + (key,))]
    if type(value) is list:
        return [item for index, child in enumerate(value) for item in _leaves(child, path + (index,))]
    return [(path, value)]


def _at(value, path):
    for part in path:
        if type(part) is str and type(value) is dict and part in value:
            value = value[part]
        elif type(part) is int and type(value) is list and part < len(value):
            value = value[part]
        else:
            return False, None
    return True, value


def _differences(expected, actual, path=()):
    base = {"path": _pointer(path), "path_segments": list(path)}
    if type(expected) is not type(actual):
        return [{**base, "kind": "type", "expected_type": _type(expected),
                 "actual_type": _type(actual), "expected": expected, "actual": actual}]
    result = []
    if type(expected) is dict:
        for key in sorted(set(expected) | set(actual)):
            if key not in actual or key not in expected:
                result.append({"path": _pointer(path + (key,)), "path_segments": list(path + (key,)),
                    "kind": "missing_field" if key not in actual else "extra_field",
                    "expected_present": key in expected, "actual_present": key in actual,
                    "expected": expected.get(key), "actual": actual.get(key)})
            else:
                result.extend(_differences(expected[key], actual[key], path + (key,)))
    elif type(expected) is list:
        for index in range(max(len(expected), len(actual))):
            if index >= len(actual) or index >= len(expected):
                result.append({"path": _pointer(path + (index,)), "path_segments": list(path + (index,)),
                    "kind": "missing_item" if index >= len(actual) else "extra_item",
                    "expected_present": index < len(expected), "actual_present": index < len(actual),
                    "expected": expected[index] if index < len(expected) else None,
                    "actual": actual[index] if index < len(actual) else None})
            else:
                result.extend(_differences(expected[index], actual[index], path + (index,)))
    elif _raw(expected) != _raw(actual):
        result.append({**base, "kind": "value", "expected": expected, "actual": actual})
    return result


def validate_native_target(domain, target):
    """Preserve the baseline target and apply existing semantic schema owners.

    UI envelope strings alone do not establish a valid semantic component.
    The existing source contract additionally checks its closed vocabularies
    and, for full UI documents, the component graph. This is native structure
    validation, not verification of source meaning or of unprojected UI facets.
    """
    from .domain_384_autoencoder import validate_target
    validated = validate_target(domain, target)
    semantic = None
    if domain == "ui_ux_ir":
        from ...logic.formalization.autoencoder.ui_source_contract_384 import validate_training_target
        semantic = validate_training_target(target)
    return {**validated, "semantic_validation": semantic}


def evaluate_generated(expected, generated_tokens, *, ended, domain_id=None, critical_paths=None):
    """Evaluate a completed prediction against a separate authored reference.

    Every expected scalar is reported and counted, including invalid/missing
    predictions. ``critical_paths=None`` marks all scalar paths critical; an
    explicit subset affects only the diagnostic view, never training weights
    or the complete exact-match and scalar-value metrics. Paths are JSON
    pointers into the expected target and must identify existing scalars.

    Optional native validation delegates to the existing domain schema owners.
    Valid native syntax remains independent from exact reference equality and
    from semantic source fidelity. The reference is never a fallback output.
    """
    expected_alignment = target_token_alignment(expected)
    parsed = parse_generated(generated_tokens, ended=ended)
    candidate = parsed["candidate"]
    native = {"status": "not_requested", "valid": None, "error": None}
    if domain_id is not None:
        from .domain_384_autoencoder import DOMAINS
        _require(domain_id in DOMAINS, "unsupported native validation domain")
        validate_native_target(domain_id, expected)
        if parsed["json_valid"]:
            try:
                receipt = validate_native_target(domain_id, candidate)
                native = {"status": "native_valid_unqualified", "valid": True,
                          "scope": receipt["scope"],
                          "semantic_validation": receipt["semantic_validation"], "error": None}
            except (ValueError, TypeError, KeyError, RecursionError) as exc:
                native = {"status": "native_invalid", "valid": False, "error": str(exc)[:512]}
        else:
            native = {"status": "generation_invalid", "valid": False, "error": parsed["error"]}
    score_eligible = parsed["json_valid"] and native["valid"] is not False
    fields = []
    expected_leaves = _leaves(expected)
    available = {_pointer(path) for path, _ in expected_leaves}
    if critical_paths is None:
        critical = available
    else:
        _require(type(critical_paths) in (list, tuple) and len(critical_paths) <= MAX_TOKENS
                 and all(type(path) is str and len(path) <= MAX_BYTES for path in critical_paths),
                 "bounded critical JSON-pointer paths required")
        critical = set(critical_paths)
        _require(critical <= available, "critical path must identify an expected scalar")
    for path, value in expected_leaves:
        present, observed = _at(candidate, path) if parsed["json_valid"] else (False, None)
        same_type = present and type(value) is type(observed)
        raw_exact = same_type and _raw(value) == _raw(observed)
        fields.append({"path": _pointer(path), "path_segments": list(path),
            "expected_type": _type(value), "expected": value, "actual_present": present,
            "actual_type": _type(observed) if present else None, "actual": observed,
            "type_correct": score_eligible and same_type,
            "raw_typed_value_equal": raw_exact,
            "exact": score_eligible and raw_exact,
            "correct": score_eligible and raw_exact,
            "critical": _pointer(path) in critical})
    differences = (_differences(expected, candidate) if parsed["json_valid"] else
                   [{"path": "", "path_segments": [], "kind": "invalid_or_missing_generation",
                     "status": parsed["status"], "error": parsed["error"]}])
    actual_leaves = _leaves(candidate) if parsed["json_valid"] else []
    correct = sum(field["exact"] for field in fields)
    critical_fields = [field for field in fields if field["critical"]]
    exact = score_eligible and not differences
    return {"schema": SCHEMA, "reference_sha256": expected_alignment["target_sha256"],
        "generation": parsed, "native_validation": native,
        "exact_target": exact, "exact": exact,
        "native_valid": native["valid"] is True,
        "scalar_total": len(fields), "scalar_correct": correct,
        "scalar_value_count": len(fields), "scalar_values_correct": correct,
        "scalar_value_accuracy": correct / len(fields) if fields else None,
        "generated_scalar_count": len(actual_leaves),
        "scalar_value_precision": correct / len(actual_leaves) if actual_leaves else None,
        "scalar_type_accuracy": sum(field["type_correct"] for field in fields) / len(fields) if fields else None,
        "fields": fields, "per_path": fields, "differences": differences,
        "critical_fields": critical_fields,
        "critical_fields_exact": score_eligible and all(field["exact"] for field in critical_fields),
        "scalar_credit_eligible": score_eligible,
        "all_scalar_values_weighted": True,
        "scope": "post_inference_reference_fidelity_not_source_semantics_or_proof",
        "target_used_for_generation": False, **FALSE}


__all__ = ["SCHEMA", "target_token_alignment", "teacher_forcing_weights",
           "parse_generated", "validate_native_target", "evaluate_generated"]
