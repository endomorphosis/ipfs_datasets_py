"""Thin O1 operation delegates.

Every public function here is a compatibility adapter.  Semantic authority
stays with the named owner recorded in :mod:`catalog`.  Owners are imported
only when an operation is invoked so a cold ``import
ipfs_datasets_py.logic.semantic`` starts no process, network, solver, or
model runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class SemanticAPIError(ValueError):
    """Raised when a public semantic operation cannot be formed or dispatched."""


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticAPIError(f"{label} must be a mapping or a reviewed owner record")
    return value


def canonical_owners() -> dict[str, Any]:
    """Return the live owner callables/types for identity and parity checks."""

    from ipfs_datasets_py.logic.bridge.translation import (
        catalog_default_receipt,
        issue_translation_receipt,
    )
    from ipfs_datasets_py.logic.formalization.training_examples import (
        IRHardNegative,
        IRPositivePair,
        validate_training_example,
    )
    from ipfs_datasets_py.logic.ir_core.artifacts import verify_artifact_integrity
    from ipfs_datasets_py.logic.ir_core.source_lineage import CorpusManifest
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
    from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
        SourceWithheldCanonicalDecompiler,
    )
    from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import CanonicalSemanticRoundTrip
    from ipfs_datasets_py.logic.proof_corpus.store import put_envelope
    from ipfs_datasets_py.logic.proof_corpus.verifier import verify_selected_item
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
        LegalIRSplitManifest,
        validate_legal_ir_eval_splits,
    )

    return {
        "compile": TypedDeonticCanonicalCompiler.compile,
        "compile_type": TypedDeonticCanonicalCompiler,
        "corpus": CorpusManifest.from_dict,
        "decompile": SourceWithheldCanonicalDecompiler.decompile,
        "decompile_type": SourceWithheldCanonicalDecompiler,
        "evaluate": CanonicalSemanticRoundTrip.run,
        "evaluate_type": CanonicalSemanticRoundTrip,
        "example": validate_training_example,
        "pair_hard_negative": IRHardNegative.from_dict,
        "pair_positive": IRPositivePair.from_dict,
        "publish": put_envelope,
        "split": LegalIRSplitManifest.from_mapping,
        "split_validate": validate_legal_ir_eval_splits,
        "translate": issue_translation_receipt,
        "translate_default": catalog_default_receipt,
        "verify_artifact": verify_artifact_integrity,
        "verify_proof": verify_selected_item,
    }


def compiler() -> Any:
    """Return a fresh measured compiler.  Does not load deontic until compile."""

    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler

    return TypedDeonticCanonicalCompiler()


def decompiler() -> Any:
    """Return a fresh source-withheld decompiler."""

    from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
        SourceWithheldCanonicalDecompiler,
    )

    return SourceWithheldCanonicalDecompiler()


def roundtrip() -> Any:
    """Return the measured compile/decompile/recompile composition."""

    from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import CanonicalSemanticRoundTrip

    return CanonicalSemanticRoundTrip()


def _coerce_compiler_request(request: object) -> Any:
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CompilerRequest

    if isinstance(request, CompilerRequest):
        return request
    if isinstance(request, Mapping):
        from ipfs_datasets_py.logic.integration.reasoning.legal_ir_canonical_adapter import (
            compiler_request_from_legal_ir_source,
        )

        adapted = compiler_request_from_legal_ir_source(request)
        if adapted is not None:
            return adapted
        try:
            return CompilerRequest.from_dict(request)
        except Exception:
            raise SemanticAPIError(
                "compile/evaluate require CompilerRequest (or a mapping that forms "
                "one with source text and atom_vocabulary)"
            ) from None
    raise SemanticAPIError(
        "compile/evaluate require CompilerRequest (or a mapping that forms one "
        "with source text and atom_vocabulary)"
    )


def _coerce_decompiler_request(request: object) -> Any:
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import DecompilerRequest

    if isinstance(request, DecompilerRequest):
        return request
    if isinstance(request, Mapping):
        try:
            return DecompilerRequest.from_dict(request)
        except Exception:
            raise SemanticAPIError(
                "decompile requires DecompilerRequest (or a complete decompiler wire mapping)"
            ) from None
    raise SemanticAPIError(
        "decompile requires DecompilerRequest (or a complete decompiler wire mapping)"
    )


def corpus(value: object) -> Any:
    """Load a sealed corpus manifest through :class:`CorpusManifest`."""

    from ipfs_datasets_py.logic.ir_core.source_lineage import CorpusManifest

    if isinstance(value, CorpusManifest):
        value.validate()
        return value
    return CorpusManifest.from_dict(_mapping(value, "corpus"))


def split(value: object) -> Any:
    """Load and validate a lineage-safe split manifest."""

    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
        LegalIRSplitManifest,
        validate_legal_ir_eval_splits,
    )

    manifest = (
        value
        if isinstance(value, LegalIRSplitManifest)
        else LegalIRSplitManifest.from_mapping(_mapping(value, "split"))
    )
    guard = validate_legal_ir_eval_splits(manifest)
    if not guard.passed:
        raise SemanticAPIError(
            "split manifest failed the lineage-safe leakage guard: "
            + ",".join(item.kind for item in guard.violations[:8])
        )
    return manifest


def example(value: object) -> Any:
    """Admit one closed training example through the formalization owner."""

    from ipfs_datasets_py.logic.formalization.training_examples import validate_training_example

    return validate_training_example(value)


def compile(request: object, *, owner: Any | None = None) -> Any:
    """Compile through :class:`TypedDeonticCanonicalCompiler`."""

    engine = owner if owner is not None else compiler()
    return engine.compile(_coerce_compiler_request(request))


def decompile(request: object, *, owner: Any | None = None) -> Any:
    """Decompile through :class:`SourceWithheldCanonicalDecompiler`."""

    engine = owner if owner is not None else decompiler()
    return engine.decompile(_coerce_decompiler_request(request))


def translate(
    *,
    direction_id: str,
    source_cid: str,
    target_cid: str,
    reconstruction_mode: Any = None,
    preservation_class: Any = None,
    fidelity_claim: Any = None,
    equality_criteria: Any = None,
    declared_loss: Any = None,
    recompilation_cid: Any = None,
    semantic_comparison_cid: Any = None,
    proof_evidence_cid: Any = None,
    details: Any = None,
) -> Any:
    """Issue a closed translation receipt through the bridge owner."""

    from ipfs_datasets_py.logic.bridge.translation import (
        catalog_default_receipt,
        issue_translation_receipt,
    )

    if (
        reconstruction_mode is None
        and preservation_class is None
        and fidelity_claim is None
        and equality_criteria is None
        and recompilation_cid is None
        and semantic_comparison_cid is None
        and proof_evidence_cid is None
    ):
        return catalog_default_receipt(
            direction_id,
            source_cid=source_cid,
            target_cid=target_cid,
            declared_loss=tuple(declared_loss or ()),
            details=details,
        )
    if reconstruction_mode is None or preservation_class is None or fidelity_claim is None:
        raise SemanticAPIError(
            "explicit translate requires reconstruction_mode, preservation_class, "
            "and fidelity_claim; omit all three to use the catalog default"
        )
    return issue_translation_receipt(
        direction_id=direction_id,
        reconstruction_mode=reconstruction_mode,
        preservation_class=preservation_class,
        fidelity_claim=fidelity_claim,
        source_cid=source_cid,
        target_cid=target_cid,
        equality_criteria=equality_criteria,
        declared_loss=tuple(declared_loss or ()),
        recompilation_cid=recompilation_cid,
        semantic_comparison_cid=semantic_comparison_cid,
        proof_evidence_cid=proof_evidence_cid,
        details=details,
    )


def pair(value: object) -> Any:
    """Admit a positive pair or hard negative through the training-contract owner."""

    from ipfs_datasets_py.logic.formalization.training_examples import (
        IRHardNegative,
        IRPositivePair,
    )
    from ipfs_datasets_py.logic.formalization.training_shared import (
        IR_HARD_NEGATIVE_SCHEMA_VERSION,
        IR_POSITIVE_PAIR_SCHEMA_VERSION,
        TrainingContractValidationError,
    )

    if isinstance(value, (IRPositivePair, IRHardNegative)):
        return type(value).from_dict(value.to_dict())
    payload = _mapping(value, "pair")
    schema = str(payload.get("schema_version") or "")
    if schema == IR_POSITIVE_PAIR_SCHEMA_VERSION or "pair_id" in payload:
        return IRPositivePair.from_dict(payload)
    if schema == IR_HARD_NEGATIVE_SCHEMA_VERSION or "mutated_paths" in payload:
        return IRHardNegative.from_dict(payload)
    raise TrainingContractValidationError(
        "pair payload is neither a positive pair nor a hard negative"
    )


def evaluate(request: object, *, owner: Any | None = None) -> Any:
    """Evaluate the measured compile/decompile/recompile composition."""

    engine = owner if owner is not None else roundtrip()
    return engine.run(_coerce_compiler_request(request))


def verify(payload: object, context: object | None = None, *, root: object | None = None) -> Any:
    """Verify selected proof evidence or an artifact-manifest integrity report."""

    if context is not None:
        from ipfs_datasets_py.logic.proof_corpus.verifier import verify_selected_item

        return verify_selected_item(payload, context)
    if root is not None:
        from ipfs_datasets_py.logic.ir_core.artifacts import verify_artifact_integrity

        return verify_artifact_integrity(payload, root)
    raise SemanticAPIError(
        "verify requires either a verifier context (proof evidence) or root "
        "(artifact-manifest integrity)"
    )


def publish(store: object, value: object, **kwargs: Any) -> Any:
    """Append one envelope to the content-addressed proof corpus store."""

    from ipfs_datasets_py.logic.proof_corpus.store import put_envelope

    return put_envelope(store, value, **kwargs)


__all__ = [
    "SemanticAPIError",
    "canonical_owners",
    "compile",
    "compiler",
    "corpus",
    "decompile",
    "decompiler",
    "evaluate",
    "example",
    "pair",
    "publish",
    "roundtrip",
    "split",
    "translate",
    "verify",
]
