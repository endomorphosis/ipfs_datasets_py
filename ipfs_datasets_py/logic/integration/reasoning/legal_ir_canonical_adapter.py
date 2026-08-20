"""Compatibility adapter: LegalIR compiler surfaces delegate to one authority.

Parallel LegalIR compiler APIs keep their existing incremental/view contracts,
but semantic compilation authority is :class:`TypedDeonticCanonicalCompiler`.
A LegalIR-shaped source without a caller-supplied atom vocabulary cannot form
a :class:`CompilerRequest`; that path stays a compatibility adapter and records
the canonical compiler as the unused authority rather than inventing a
vocabulary or falling back to a model.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ipfs_datasets_py.logic.legal_ir.canonical_compiler import (
    TYPED_DEONTIC_COMPILER_CONFIG_CID,
    TypedDeonticCanonicalCompiler,
)
from .legal_ir_canonical_pipeline import (
    CANONICAL_COMPILER_PIPELINE_CID,
    CANONICAL_COMPILER_PIPELINE_INTERFACE,
    compile_canonical_pipeline,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
    CanonicalAtomVocabulary,
    CanonicalContractError,
    CompilerRequest,
    CompilerResult,
)


CANONICAL_COMPILER_AUTHORITY_ID = "TypedDeonticCanonicalCompiler"


def canonical_authority_record(
    *,
    delegated: bool,
    reason: str,
    result: CompilerResult | None = None,
) -> dict[str, Any]:
    """Return the machine-readable authority stamp attached to LegalIR results."""

    record: dict[str, Any] = {
        "authority": CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
        "compiler": CANONICAL_COMPILER_AUTHORITY_ID,
        "configuration_cid": TYPED_DEONTIC_COMPILER_CONFIG_CID,
        "delegated": bool(delegated),
        "pipeline_cid": CANONICAL_COMPILER_PIPELINE_CID,
        "pipeline_interface": CANONICAL_COMPILER_PIPELINE_INTERFACE,
        "reason": reason,
    }
    if result is not None:
        record["result_cid"] = result.result_cid
        record["status"] = result.status.value
        record["terminal_stage"] = result.provenance.get("terminal_stage")
        if result.canonical_ir is not None:
            record["canonical_ir_cid"] = result.canonical_ir.ir_cid
        record["pipeline_trace_cid"] = result.provenance.get("pipeline_trace_cid")
    return record


def compiler_request_from_legal_ir_source(
    source: object,
) -> CompilerRequest | None:
    """Build a CompilerRequest when the LegalIR source already carries one."""

    if isinstance(source, CompilerRequest):
        return source
    if not isinstance(source, Mapping):
        return None
    text = _source_text(source)
    vocabulary = source.get("atom_vocabulary")
    if vocabulary is None:
        vocabulary = source.get("allowed_atoms")
    if not text or vocabulary is None:
        return None
    try:
        if isinstance(vocabulary, CanonicalAtomVocabulary):
            atoms = vocabulary
        elif isinstance(vocabulary, Mapping):
            atoms = CanonicalAtomVocabulary.from_dict(vocabulary)
        else:
            return None
        request_id = str(
            source.get("request_id")
            or source.get("source_document_id")
            or source.get("document_id")
            or "legal-ir-api"
        )
        return CompilerRequest(
            source_text=text,
            request_id=request_id,
            atom_vocabulary=atoms,
            allow_explicit_partial=bool(source.get("allow_explicit_partial", False)),
        )
    except (CanonicalContractError, TypeError, ValueError):
        return None


def compile_through_canonical_authority(
    source: object,
) -> tuple[CompilerResult | None, dict[str, Any]]:
    """Delegate to the canonical compiler when a CompilerRequest can be formed."""

    request = compiler_request_from_legal_ir_source(source)
    if request is None:
        return None, canonical_authority_record(
            delegated=False,
            reason="compatibility_adapter_without_compiler_request",
        )
    result = TypedDeonticCanonicalCompiler().compile(request)
    return result, canonical_authority_record(
        delegated=True,
        reason="delegated_to_canonical_compiler",
        result=result,
    )


def compile_legal_ir_canonical(source: object) -> CompilerResult:
    """Compile through the canonical pipeline or raise if no request can be formed."""

    request = compiler_request_from_legal_ir_source(source)
    if request is None:
        raise CanonicalContractError(
            "LegalIR source cannot form CompilerRequest; atom_vocabulary and "
            "source text are required to delegate to the canonical compiler"
        )
    return compile_canonical_pipeline(request).result


def _source_text(payload: Mapping[str, Any]) -> str:
    for key in ("raw_document", "source", "source_text", "text", "normalized_text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    normalized = payload.get("normalized_document")
    if isinstance(normalized, Mapping):
        text = normalized.get("normalized_text")
        if isinstance(text, str) and text.strip():
            return text
    return ""


__all__ = [
    "CANONICAL_COMPILER_AUTHORITY_ID",
    "canonical_authority_record",
    "compile_legal_ir_canonical",
    "compile_through_canonical_authority",
    "compiler_request_from_legal_ir_source",
]
