"""Post-inference source agreement for an unchanged learned rich Intent AST.

The bounded grammar is a diagnostic reference, not a model input or a repair.
An exact match here does not execute Lake or establish natural-language truth.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys

from ...autoformal import tree_pin
from ...intent_ir.formalize import instruction_scope, rich_grammar

SCHEMA = "intent-candidate-source-fidelity/v1"
MAX_BYTES = 65536
MAX_NODES = 4096
MAX_DEPTH = 32
FALSE = {"qualified": False, "admitted": False, "formalized": False,
         "source_semantics_verified": False, "proof_authority": False,
         "execution_authority": False, "claim_proved": False,
         "lake_executed": False, "backend_executed": False,
         "training_executed": False, "candidate_rewritten": False}


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json_input(value):
    """Accept bounded exact JSON types, including malformed candidate shapes."""
    count = 0

    def visit(node, depth):
        nonlocal count
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise ValueError("candidate JSON exceeds depth or node bound")
        kind = type(node)
        if kind is dict:
            if any(type(key) is not str for key in node):
                raise ValueError("candidate object keys must be strings")
            for child in node.values():
                visit(child, depth + 1)
        elif kind is list:
            for child in node:
                visit(child, depth + 1)
        elif kind not in (str, int, float, bool, type(None)) or kind is float and not math.isfinite(node):
            raise ValueError("candidate must contain finite exact JSON types")

    visit(value, 0)
    raw = _raw(value)
    if len(raw) > MAX_BYTES:
        raise ValueError("candidate JSON exceeds byte bound")
    return raw


def _type(value):
    return {dict: "object", list: "array", str: "string", bool: "boolean",
            int: "integer", float: "number", type(None): "null"}[type(value)]


def _differences(expected, candidate):
    """Compare complete values with typed JSON pointers; never coerce scalars."""
    rows = []

    def pointer(path):
        return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in path)

    def record(path, left, right, *, left_exists=True, right_exists=True):
        rows.append({"path": pointer(path), "path_segments": list(path),
            "reason": "unexpected_field" if not left_exists else
                      "missing_field" if not right_exists else
                      "type_mismatch" if type(left) is not type(right) else "value_mismatch",
            "expected_present": left_exists, "candidate_present": right_exists,
            "expected_type": _type(left) if left_exists else None,
            "candidate_type": _type(right) if right_exists else None,
            "expected": deepcopy(left) if left_exists else None,
            "candidate": deepcopy(right) if right_exists else None})

    def compare(left, right, path):
        if type(left) is not type(right):
            record(path, left, right)
        elif type(left) is dict:
            for key in sorted(left.keys() | right.keys()):
                if key not in left or key not in right:
                    record((*path, key), left.get(key), right.get(key),
                           left_exists=key in left, right_exists=key in right)
                else:
                    compare(left[key], right[key], (*path, key))
        elif type(left) is list:
            for index in range(max(len(left), len(right))):
                if index >= len(left) or index >= len(right):
                    record((*path, index), left[index] if index < len(left) else None,
                           right[index] if index < len(right) else None,
                           left_exists=index < len(left), right_exists=index < len(right))
                else:
                    compare(left[index], right[index], (*path, index))
        elif left != right:
            record(path, left, right)

    compare(expected, candidate, ())
    return rows


def _pins():
    # Reuse the existing first-use loaded-code/disk check. This scope does not
    # purport to pin every transitive import of the legal compiler.
    from ....optimizers.logic_theorem_optimizer import autoencoder_schema_lake as owner_pin
    root = Path(__file__).resolve().parents[4]
    if Path(tree_pin.workspace_root()).resolve() != root:
        raise ValueError("Intent fidelity tree pin differs from selected source tree")
    modules = (sys.modules[__name__], rich_grammar, instruction_scope, tree_pin, owner_pin)
    if any(root not in Path(module.__file__).resolve().parents for module in modules):
        raise ValueError("Intent fidelity owner resolved outside selected source tree")
    return {module.__name__: owner_pin._pin_imported_module(module) for module in modules}


def audit_intent_candidate(source_text, candidate):
    """Diagnose a target-free prediction against its complete original source.

    ``candidate`` is the original source384 envelope, with ``kind`` equal to
    ``intent_rich_ast`` and ``document`` containing the predicted AST. Malformed
    bounded JSON candidates are retained and classified as native-invalid.
    Neither a target nor a checkpoint is accepted or substituted by this API.
    """
    if type(source_text) is not str or len(source_text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("bounded original source string required")
    candidate_bytes = _json_input(candidate)
    original = deepcopy(candidate)
    pins = _pins()
    resolved_tree = tree_pin.require_workspace_logic_tree()
    native_error = source_error = None
    try:
        if (type(original) is not dict or set(original) != {"kind", "document"}
                or original["kind"] != "intent_rich_ast"):
            raise ValueError("closed intent_rich_ast candidate envelope required")
        rich_grammar.validate_ast(original["document"])
    except ValueError as error:
        native_error = str(error)
    reference = None
    try:
        reference = {"kind": "intent_rich_ast", "document": rich_grammar.parse_instruction(source_text)}
    except ValueError as error:
        source_error = str(error)
    differences = None if reference is None else _differences(reference, original)
    exact = native_error is None and source_error is None and not differences
    status = ("native_invalid" if native_error is not None else
              "source_unsupported" if source_error is not None else
              "source_agreement" if exact else "source_disagreement")
    report = {"schema": SCHEMA, "domain_id": "intent_ir", "status": status,
        "source_text": source_text, "source_sha256": _sha(source_text.encode("utf-8")),
        "candidate": original, "candidate_sha256": _sha(candidate_bytes),
        "native_valid": native_error is None, "native_error": native_error,
        "native_validation_scope": "complete_rich_grammar_AST_schema_only",
        "source_supported": source_error is None, "source_error": source_error,
        "source_reference": reference,
        "source_reference_scope": "post_inference_bounded_whole_input_grammar_not_gold_semantics",
        "exact": exact, "source_agreement": exact, "differences": differences,
        "comparison_scope": "complete_typed_candidate_envelope_and_rich_AST",
        "producer_pins": pins, "resolved_logic_tree": resolved_tree,
        "owner_pin_scope": "direct_owners_loaded_code_and_disk_not_transitive_callgraph",
        "model_inference_executed": False, "model_inputs_modified": False, **FALSE}
    if pins != _pins():
        raise ValueError("Intent fidelity producer changed during audit")
    if _raw(original) != candidate_bytes or _json_input(candidate) != candidate_bytes:
        raise ValueError("Intent fidelity candidate changed during audit")
    report["report_sha256"] = _sha(_raw(report))
    return report


__all__ = ["SCHEMA", "audit_intent_candidate"]
