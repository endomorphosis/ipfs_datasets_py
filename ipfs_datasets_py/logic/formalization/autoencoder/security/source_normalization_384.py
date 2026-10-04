"""Explicit, narrow AST source normalization for hybrid learned inference.

This does not produce an IR target or repair a prediction. It removes comments,
formatting and one fresh temporary only in the already guarded two-integer
parameter source fragment. Unsupported source is returned byte-for-byte intact.
The original source must still qualify the independently learned prediction.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json

from . import source_program_binding_384 as binding

SCHEMA = "security-source-normalization-384/v1"
HYBRID_PROFILE = "guarded-source-normalization-384/v1"
INPUT_VIEW = "guarded_ast_normalized"
FALSE = dict(proof_authority=False, execution_authority=False, completion_authority=False,
    source_semantics_verified=False, security_specification_inferred=False,
    whole_program_semantics_verified=False, target_access=False,
    target_dependent_normalization=False, prediction_repair_performed=False,
    source_executed=False)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _signature(guarded):
    function, _, operands, _, operator, native_operator, result_type = guarded
    return dict(function_name=function.name,
        parameters=[dict(name=argument.arg, annotation=ast.unparse(argument.annotation))
            for argument in function.args.args],
        return_annotation=ast.unparse(function.returns) if function.returns is not None else None,
        operator=operator, native_operator=native_operator,
        ordered_operands=[operand.id for operand in operands], result_type=result_type)


def normalize_source(source_text):
    """Return a checked source-only view and explicit non-authoritative receipt.

    The accepted scope is inherited from ``source_program_binding_384._guard``.
    In particular, int annotations remain assumptions, not runtime type checks.
    Input-contract violations raise; unsupported Python retains its exact text.
    """
    if type(source_text) is not str or not 0 < len(source_text.encode("utf-8")) <= binding.MAX_SOURCE_BYTES:
        raise ValueError("bounded nonempty source text required")
    checksum = _sha(source_text)
    receipt = dict(schema=SCHEMA, hybrid_profile=HYBRID_PROFILE, input_view=INPUT_VIEW,
        status="unsupported", reason=None, original_source_sha256=checksum,
        normalized_source_sha256=checksum, normalized_source_text=source_text,
        normalization_applied=False, source_signature=None, signature_preserved=False,
        temporary_eliminated=False, ast_used=True,
        original_source_required_for_qualification=True,
        assumptions=list(binding._ASSUMPTIONS), **FALSE)
    try:
        guarded = binding._guard(source_text)
        function, expression, _, temporary, _, _, _ = guarded
        original_signature = _signature(guarded)
        normalized_function = deepcopy(function)
        normalized_function.body = [ast.Return(value=deepcopy(expression))]
        ast.fix_missing_locations(normalized_function)
        normalized = ast.unparse(normalized_function) + "\n"
        normalized_signature = _signature(binding._guard(normalized))
        if json.dumps(original_signature, sort_keys=True) != json.dumps(normalized_signature, sort_keys=True):
            raise ValueError("normalization_signature_changed")
    except (ValueError, TypeError, SyntaxError, RecursionError) as error:
        # Failure is an explicit abstention, with no partially rewritten text.
        receipt["reason"] = error.code if isinstance(error, binding._Rejected) else "normalization_contract_error"
        return receipt
    receipt.update(status="normalized", normalized_source_text=normalized,
        normalized_source_sha256=_sha(normalized), normalization_applied=normalized != source_text,
        source_signature=original_signature, signature_preserved=True,
        temporary_eliminated=temporary is not None)
    return receipt


__all__ = ["normalize_source", "SCHEMA", "HYBRID_PROFILE", "INPUT_VIEW"]
