"""Pure complete-function maps reused from the existing Security source owner.

No decoder, target derivation or source execution participates in extraction.
Normalized functions retain their original file identity and enclosing scopes.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import warnings

from .security.security_formula_corpus import _qualified_functions, _verify_span
from .security.security_formalization_evaluation import _function_span
from .source_screening import _contains_secret, _credential_path_reason

SCHEMA = "source-function-units@1"
MAX_SOURCE_BYTES = 1_048_576
MAX_AST_NODES = 65_536


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def pins():
    return {str(Path(f.__code__.co_filename).name): sha(Path(f.__code__.co_filename).read_bytes())
            for f in (extract_function_units, _qualified_functions, _verify_span, _function_span,
                      _contains_secret, _credential_path_reason)}


def extract_function_units(*, source_bytes, source_sha256, source_path, max_functions=1024):
    """Inventory every function or report an explicit file-level frontier.

    A function bound is a hard refusal, never silent truncation. Byte maps are
    the same maps used by the older formula decoder, which remains unchanged.
    """
    if (type(source_bytes) is not bytes or not 0 < len(source_bytes) <= MAX_SOURCE_BYTES
            or source_sha256 != sha(source_bytes)):
        raise ValueError("bounded exact original source bytes and hash required")
    if (type(source_path) is not str or not 0 < len(source_path.encode()) <= 1024
            or PurePosixPath(source_path).as_posix() != source_path
            or PurePosixPath(source_path).is_absolute() or ".." in source_path.split("/")
            or "\\" in source_path or any(ord(c) < 32 or ord(c) == 127 for c in source_path)):
        raise ValueError("canonical original repository-relative path required")
    if type(max_functions) is not int or not 1 <= max_functions <= 1024:
        raise ValueError("bounded exact function count required")
    result = dict(schema=SCHEMA, source_path=source_path, source_sha256=source_sha256,
        source_bytes=len(source_bytes), max_functions=max_functions, producer=pins(),
        status="unsupported", frontier=None, units=[], source_executed=False,
        whole_file_semantics_verified=False, proof_authority=False)
    if _credential_path_reason(source_path) or _contains_secret(source_bytes):
        result["frontier"] = "source_screen_refused"
        return result
    if not source_path.endswith(".py"):
        result["frontier"] = "unsupported_language"
        return result
    if any(c in source_bytes for c in (b"\r", b"\v", b"\f", b"\x00")):
        result["frontier"] = "source_line_controls_not_mapped"
        return result
    if source_bytes.count(b"\n") > 16384:
        result["frontier"] = "source_line_map_bound_exceeded"
        return result
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source_bytes.decode("utf-8"), type_comments=True)
        if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
            result["frontier"] = "source_ast_node_bound_exceeded"
            return result
        found = _qualified_functions(tree)
    except (SyntaxError, UnicodeError, ValueError, RecursionError):
        result["frontier"] = "complete_python_source_required"
        return result
    if len(found) > max_functions:
        raise ValueError("source function bound exceeded; inventory is not truncated")
    mapped_bytes = mapped_lines = 0
    for node, qualified, enclosing in found:
        body, binding = _function_span(source_bytes, node)
        mapped_bytes += len(body)
        mapped_lines += len(binding["line_byte_map"])
        if mapped_bytes > 4 * MAX_SOURCE_BYTES or mapped_lines > 65536:
            raise ValueError("complete normalized function maps exceed bound; inventory is not truncated")
        _verify_span(source_bytes, body, binding)
        try:
            isolated = ast.parse(body.decode("utf-8"), type_comments=True)
            same = (len(isolated.body) == 1 and not isolated.type_ignores
                    and ast.dump(isolated.body[0], include_attributes=False)
                    == ast.dump(node, include_attributes=False))
        except (SyntaxError, UnicodeError, ValueError, RecursionError):
            same = False
        identity = dict(source_path=source_path, source_sha256=source_sha256,
            qualified_name=qualified, start_byte=binding["start_byte"], end_byte=binding["end_byte"],
            normalized_body_sha256=sha(body))
        result["units"].append(dict(unit_id=sha(wire(identity)), **identity,
            enclosing_scope=enclosing, source_binding=binding,
            normalized_AST_matches_source_function=same,
            normalized_source_text=body.decode("utf-8"),
            status="eligible" if same else "unsupported_normalization",
            whole_file_semantics_verified=False, proof_authority=False))
    result.update(status="inventoried", frontier=None if found else "no_function_units")
    return result


def validate_function_units(report, *, source_bytes):
    """Re-extract every map; caller-supplied IDs and success flags are untrusted."""
    actual = extract_function_units(source_bytes=source_bytes, source_sha256=report["source_sha256"],
        source_path=report["source_path"], max_functions=report["max_functions"])
    if wire(actual) != wire(report):
        raise ValueError("function inventory, source mapping or producer differs")
    return actual
