"""Exact complete-function inputs for the frozen SecurityIR production head.

A token window is a retrieval input, not necessarily a Python modeling unit.
This adapter finds functions in the original, independently pinned source and
keeps their exact byte maps. It never closes brackets, invents a function
wrapper, unescapes source, or substitutes parsed productions for predictions.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import warnings

from ..source_screening import SourceSecretError, _contains_secret, _credential_path_reason
from . import security_formula_decoder as decoder
from .security_formula_corpus import _qualified_functions, _verify_span
from .security_formalization_evaluation import _function_span

SCHEMA = "security-formula-source-units@1"
MAX_SOURCE_BYTES = 1_048_576
MAX_AST_NODES = 65_536


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _identity(value):
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def _decoder_functions(checkpoint):
    """Select the explicit version without modifying either frozen grammar."""
    if isinstance(checkpoint, dict) and checkpoint.get("schema") == "security-formula-production-decoder@2":
        from .security_formula_decoder_v2 import load_security_formula_decoder_v2, decode_security_formula_v2
        return load_security_formula_decoder_v2, decode_security_formula_v2
    return decoder.load_security_formula_decoder, decoder.decode_security_formula


def decode_security_source_units(*, source_bytes: bytes, source_sha256: str,
        source_path: str, checkpoint: dict, language: str | None = None, window_start_byte: int = 0,
        window_end_byte: int | None = None, recover_context: bool = False,
        max_functions: int = 1024, model_enabled: bool = True,
        weight_ablation: str | None = None) -> dict:
    """Decode complete units, distinguishing window content from added context.

    By default only functions wholly contained in the requested window are
    decoded. ``recover_context=True`` additionally decodes complete intersecting
    functions from the supplied original source. Those successes are reported
    separately and never credited as standalone window coverage. Every function
    in the file remains in the inventory, including unsupported and unselected
    ones. Module imports, initialization and enclosing scopes remain assumptions;
    a local function model is not a whole-file semantics claim. Explicit Python
    ``language`` permits original paths without a ``.py`` suffix; without a
    language declaration the existing ``.py`` gate remains in force.
    """
    if (type(source_bytes) is not bytes or not 0 < len(source_bytes) <= MAX_SOURCE_BYTES
            or type(source_sha256) is not str or source_sha256 != _sha(source_bytes)):
        raise ValueError("bounded source bytes with matching independent SHA256 required")
    if (type(source_path) is not str or not source_path or len(source_path) > 512
            or (language is not None and type(language) is not str)
            or type(recover_context) is not bool or type(model_enabled) is not bool
            or type(max_functions) is not int or not 1 <= max_functions <= 1024):
        raise ValueError("explicit source identity, context policy and function bound required")
    if window_end_byte is None:
        window_end_byte = len(source_bytes)
    if (type(window_start_byte) is not int or type(window_end_byte) is not int
            or not 0 <= window_start_byte < window_end_byte <= len(source_bytes)):
        raise ValueError("exact nonempty source-relative window byte range required")
    if _credential_path_reason(source_path) or _contains_secret(source_bytes):
        raise SourceSecretError("formula source units refused by shared source screen")
    load_model, decode_model = _decoder_functions(checkpoint)
    loaded = load_model(checkpoint)
    report = {"schema": SCHEMA, "source_path": source_path, "language": language, "source_sha256": source_sha256,
        "source_bytes": len(source_bytes), "checkpoint": checkpoint,
        "window": {"start_byte": window_start_byte, "end_byte": window_end_byte,
            "sha256": _sha(source_bytes[window_start_byte:window_end_byte])},
        "recover_context": recover_context, "model_enabled": model_enabled,
        "weight_ablation": weight_ablation, "max_functions": max_functions,
        "status": "unsupported", "units": [], "frontiers": [],
        "counts": {"observed_functions": 0, "selected_functions": 0,
            "unselected_functions": 0, "normalization_refused_functions": 0,
            "unsupported_functions": 0, "rejected_functions": 0, "candidate_functions": 0,
            "contained_functions": 0, "context_recovered_functions": 0,
            "learned_inference_functions": 0, "source_AST_equivalent_functions": 0,
            "accepted_functions": 0, "accepted_contained_functions": 0,
            "accepted_context_recovered_functions": 0, "learned_formula_count": 0},
        "implementation_sha256": {"adapter": _sha(Path(__file__).read_bytes()),
            "span_adapter": _sha(Path(_function_span.__code__.co_filename).read_bytes()),
            "span_verifier": _sha(Path(_verify_span.__code__.co_filename).read_bytes())},
        "assumptions": ["isolated function under the frozen decoder's explicit model",
            "module initialization and enclosing scopes are not inferred or executed",
            "context-recovered units are not standalone window successes"],
        "source_semantics_verified": False, "whole_file_semantics_verified": False,
        "proof_authority": False, "execution_authority": False,
        "completion_authority": False, "training_steps": 0, "provider_calls": 0,
        "download_calls": 0, "solver_calls": 0}
    if (language is None and not source_path.endswith(".py")) or language not in {None, "python", "py", "python3"}:
        report["frontiers"] = ["non_python_source; choose a decoder for the declared language"]
        return report
    if any(byte in source_bytes for byte in (b"\r", b"\v", b"\f", b"\x00")):
        report["frontiers"] = ["source_line_controls_not_mapped"]
        return report
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source_bytes.decode("utf-8"), type_comments=True)
    except (SyntaxError, UnicodeError, ValueError, RecursionError):
        report["frontiers"] = ["complete_python_source_required; fragments are not repaired"]
        return report
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        report["frontiers"] = ["source_ast_node_bound_exceeded"]
        return report
    found = _qualified_functions(tree)
    if len(found) > max_functions:
        raise ValueError("source function bound exceeded; functions are not truncated")
    counts = report["counts"]
    counts["observed_functions"] = len(found)
    for node, qualified_name, enclosing_scope in found:
        body, binding = _function_span(source_bytes, node)
        _verify_span(source_bytes, body, binding)
        start, end = binding["start_byte"], binding["end_byte"]
        contained = window_start_byte <= start and end <= window_end_byte
        intersects = start < window_end_byte and window_start_byte < end
        selected = contained or (recover_context and intersects)
        relation = "contained" if contained else "intersects" if intersects else "outside"
        identity = {"source_sha256": source_sha256, "source_path": source_path,
            "qualified_name": qualified_name, "start_byte": start, "end_byte": end,
            "normalized_body_sha256": _sha(body)}
        unit = {"unit_id": _identity(identity), **identity, "source_binding": binding,
            "enclosing_scope": enclosing_scope, "window_relation": relation,
            "selected": selected, "context_recovered": selected and not contained,
            "normalization": binding["normalization"],
            "normalized_AST_matches_source_function": False,
            "preparation_frontiers": [], "decode": None}
        report["units"].append(unit)
        if not selected:
            counts["unselected_functions"] += 1
            continue
        counts["selected_functions"] += 1
        counts["contained_functions" if contained else "context_recovered_functions"] += 1
        # Removing indentation can also change indentation inside multiline
        # string literals. Byte-map fidelity alone cannot establish that the
        # isolated modeling input retains the original function's syntax.
        try:
            isolated = ast.parse(body.decode("utf-8"), type_comments=True)
            same_ast = (len(isolated.body) == 1 and not isolated.type_ignores
                and ast.dump(isolated.body[0], include_attributes=False)
                == ast.dump(node, include_attributes=False))
        except (SyntaxError, UnicodeError, ValueError, RecursionError):
            same_ast = False
        unit["normalized_AST_matches_source_function"] = same_ast
        if not same_ast:
            counts["normalization_refused_functions"] += 1
            counts["unsupported_functions"] += 1
            unit["preparation_frontiers"] = ["normalization_does_not_preserve_original_function_AST"]
            report["frontiers"].append({"unit_id": unit["unit_id"],
                "status": "unsupported", "reasons": unit["preparation_frontiers"]})
            continue
        decoded = decode_model(source_bytes=body, source_path=source_path,
            checkpoint=checkpoint, loaded=loaded, model_enabled=model_enabled,
            weight_ablation=weight_ablation)
        unit["decode"] = decoded
        counts["learned_inference_functions"] += bool(decoded["predicted_productions"])
        counts["source_AST_equivalent_functions"] += decoded["validation"]["source_AST_equivalent"]
        counts["learned_formula_count"] += decoded["learned_formula_count"]
        if decoded["status"] in {"unsupported", "rejected", "candidate"}:
            counts[decoded["status"] + "_functions"] += 1
        if decoded["status"] == "accepted":
            counts["accepted_functions"] += 1
            counts["accepted_contained_functions" if contained else "accepted_context_recovered_functions"] += 1
        else:
            report["frontiers"].append({"unit_id": unit["unit_id"],
                "status": decoded["status"], "reasons": decoded["frontiers"]})
    if not found:
        report["frontiers"].append("no_function_units; source prose and statements are not functions")
    elif not counts["selected_functions"]:
        report["frontiers"].append("no_complete_function_in_window; original source context required")
    report["status"] = "evaluated" if counts["selected_functions"] else "unsupported"
    return report


def validate_security_source_units(report: dict, *, source_bytes: bytes, checkpoint: dict) -> dict:
    """Recheck source selection, exact byte maps and frozen learned outputs."""
    actual = decode_security_source_units(source_bytes=source_bytes,
        source_sha256=report["source_sha256"], source_path=report["source_path"],
        checkpoint=checkpoint, language=report["language"], window_start_byte=report["window"]["start_byte"],
        window_end_byte=report["window"]["end_byte"], recover_context=report["recover_context"],
        max_functions=report["max_functions"], model_enabled=report["model_enabled"],
        weight_ablation=report["weight_ablation"])
    if actual != report:
        raise ValueError("source-unit selection, lineage or learned decoder replay differs")
    return actual
