"""Unit tests for the measured canonical semantic round-trip orchestrator."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

import pytest

from ipfs_datasets_py.logic.legal_ir.canonical_compiler import (
    TYPED_DEONTIC_COMPILER_CONFIG_CID,
    TypedDeonticCanonicalCompiler,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_PARITY_POLICY_CID,
    CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
    SELECTED_REALIZER_INTERFACE,
    CanonicalAtomVocabulary,
    CanonicalContractError,
    CanonicalErrorCode,
    CompilerRequest,
    CompilerResult,
    OperationStatus,
)
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
    SourceWithheldCanonicalDecompiler,
)
from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import (
    CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID,
    CANONICAL_SEMANTIC_ROUNDTRIP_INTERFACE,
    CanonicalSemanticRoundTrip,
    CanonicalSemanticRoundTripResult,
    measured_parity_compiler_request,
    roundtrip_configuration,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes


def _vocabulary() -> CanonicalAtomVocabulary:
    return CanonicalAtomVocabulary(
        actors=("agency", "company_a", "company_b"),
        actions=("file", "submit", "withdraw"),
        objects=("backup_report", "incident_report", "annual_report"),
        qualifiers=(
            "within_10_days",
            "emergency",
            "within_30_days",
            "natural_disaster",
        ),
    )


def _request(
    *,
    allow_explicit_partial: bool = True,
) -> CompilerRequest:
    return CompilerRequest(
        source_text=(
            "Company A shall submit backup report within 10 days "
            "unless emergency."
        ),
        request_id="roundtrip-unit",
        atom_vocabulary=_vocabulary(),
        policy_cid=CANONICAL_PARITY_POLICY_CID,
        allow_explicit_partial=allow_explicit_partial,
    )


def test_measured_parity_request_opts_into_explicit_partial() -> None:
    request = measured_parity_compiler_request(
        "Company A shall submit backup report within 10 days unless emergency.",
        request_id="parity",
        atom_vocabulary=_vocabulary(),
    )
    assert request.allow_explicit_partial is True
    assert request.policy_cid == CANONICAL_PARITY_POLICY_CID


def test_roundtrip_configuration_is_frozen_and_cid_addressed() -> None:
    payload = roundtrip_configuration()
    assert payload["interface"] == CANONICAL_SEMANTIC_ROUNDTRIP_INTERFACE
    assert payload["policy_cid"] == CANONICAL_PARITY_POLICY_CID
    assert (
        payload["compiler"]["configuration_cid"]
        == TYPED_DEONTIC_COMPILER_CONFIG_CID
    )
    assert payload["fallback_allowed"] is False
    assert CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID


def test_successful_roundtrip_seals_l1_t1_l2_chain() -> None:
    result = CanonicalSemanticRoundTrip().run(_request())

    assert result.status is OperationStatus.SUCCESS
    assert result.terminal_stage == "complete"
    assert result.l1_result is not None
    assert result.t1_result is not None
    assert result.l2_result is not None
    assert result.l1_result.provenance["source_cid"] == result.source_cid
    assert (
        result.t1_result.component_trace[0].input_cid
        == result.l1_result.canonical_ir.ir_cid
    )
    assert (
        result.l2_result.provenance["source_cid"] == result.t1_result.text_cid
    )
    # SUCCESS is stage completion, not a scored parity decision.
    assert result.error is None
    decoded = CanonicalSemanticRoundTripResult.from_dict(result.to_dict())
    assert decoded.result_cid == result.result_cid


def _forged_provenance(
    original: MappingProxyType | dict[str, object],
    *,
    source_cid: str,
) -> dict[str, object]:
    from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

    body = {
        key: (list(value) if isinstance(value, tuple) else value)
        for key, value in dict(original).items()
        if key != "provenance_cid"
    }
    body["source_cid"] = source_cid
    return {**body, "provenance_cid": cid_for_dag_json(body)}


def test_result_rejects_l2_unbound_to_t1_text() -> None:
    result = CanonicalSemanticRoundTrip().run(_request())
    provenance = _forged_provenance(
        result.l2_result.provenance,
        source_cid=cid_for_bytes(b"forged-source"),
    )
    with pytest.raises(CanonicalContractError, match="L2 provenance"):
        CanonicalSemanticRoundTripResult(
            status=OperationStatus.SUCCESS,
            request_cid=result.request_cid,
            source_cid=result.source_cid,
            policy_cid=result.policy_cid,
            terminal_stage="complete",
            completed_stages=result.completed_stages,
            l1_result=result.l1_result,
            t1_result=result.t1_result,
            l2_result=CompilerResult(
                status=result.l2_result.status,
                request_cid=result.l2_result.request_cid,
                canonical_ir=result.l2_result.canonical_ir,
                unsupported_semantics=result.l2_result.unsupported_semantics,
                provenance=MappingProxyType(provenance),
                diagnostics=result.l2_result.diagnostics,
                component_trace=result.l2_result.component_trace,
                error=result.l2_result.error,
            ),
            error=None,
        )


def test_result_rejects_l1_source_mismatch() -> None:
    result = CanonicalSemanticRoundTrip().run(_request())
    provenance = _forged_provenance(
        result.l1_result.provenance,
        source_cid=cid_for_bytes(b"other-source"),
    )
    with pytest.raises(CanonicalContractError, match="L1 provenance"):
        CanonicalSemanticRoundTripResult(
            status=OperationStatus.SUCCESS,
            request_cid=result.request_cid,
            source_cid=result.source_cid,
            policy_cid=result.policy_cid,
            terminal_stage="complete",
            completed_stages=result.completed_stages,
            l1_result=CompilerResult(
                status=result.l1_result.status,
                request_cid=result.l1_result.request_cid,
                canonical_ir=result.l1_result.canonical_ir,
                unsupported_semantics=result.l1_result.unsupported_semantics,
                provenance=MappingProxyType(provenance),
                diagnostics=result.l1_result.diagnostics,
                component_trace=result.l1_result.component_trace,
                error=result.l1_result.error,
            ),
            t1_result=result.t1_result,
            l2_result=result.l2_result,
            error=None,
        )


def test_component_identity_mismatch_fails_closed() -> None:
    class _WrongCompiler(TypedDeonticCanonicalCompiler):
        @property
        def identity(self) -> str:
            return "WrongCompiler@1"

    result = CanonicalSemanticRoundTrip(
        compiler=_WrongCompiler()
    ).run(_request())
    assert result.status is OperationStatus.FAILED
    assert result.terminal_stage == "component_validation"
    assert result.error is not None
    assert result.error.code is CanonicalErrorCode.POLICY_MISMATCH
    assert result.l1_result is None


def test_unbound_request_type_is_rejected() -> None:
    with pytest.raises(CanonicalContractError, match="CompilerRequest"):
        CanonicalSemanticRoundTrip().run({"source_text": "nope"})  # type: ignore[arg-type]


def test_default_components_match_protocols() -> None:
    assert isinstance(
        TypedDeonticCanonicalCompiler(),
        object,
    )
    compiler = TypedDeonticCanonicalCompiler()
    decompiler = SourceWithheldCanonicalDecompiler()
    assert compiler.identity == CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE
    assert decompiler.identity == SELECTED_REALIZER_INTERFACE
    assert decompiler.deterministic is True
    assert decompiler.uses_model is False
