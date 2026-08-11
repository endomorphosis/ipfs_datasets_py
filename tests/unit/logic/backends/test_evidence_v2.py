"""Unit tests for ProviderExecutionReceipt@2 and EvidenceReplayReceipt@1 (LFP2-008).

Acceptance coverage:

* executable receipts bind launch/tool/output/result identities
* metadata-only records cannot claim execution
* mock records cannot claim execution or replay
* replay claims require executable source receipts and explicit disposition
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.artifacts_v2 import (
    admit_compiled_target,
    admit_parsed_result,
)
from ipfs_datasets_py.logic.backends.evidence_v2 import (
    EVIDENCE_REPLAY_RECEIPT_INTERFACE,
    EVIDENCE_V2_MODULE_VERSION,
    PROVIDER_EXECUTION_RECEIPT_V2_INTERFACE,
    EvidenceLineageError,
    EvidenceReplayReceipt,
    EvidenceV2Error,
    ExecutionClaimError,
    ExecutionOutcome,
    ExecutionRecordKind,
    ProviderExecutionReceiptV2,
    ReplayClaimError,
    ReplayDisposition,
    require_executable_receipt,
    require_replay_receipt,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    RequestAuthorityCeiling,
    RequestBounds,
)
from ipfs_datasets_py.logic.families.namespaces import (
    encoding_id,
    evidence_id,
    notation_id,
    property_id,
    provider_id,
    view_id,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    DomainLogicSliceV2,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_predicate
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SourceDocument,
    SourceMap,
    SourceMapEntry,
    SourceRange,
)
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


def _document(text: str = "P", document_id: str = "doc:ev-v2") -> SourceDocument:
    return SourceDocument.from_text(document_id, text, encoding="utf-8")


def _expression(expression_id: str = "expr:p") -> TypedExpression:
    return TypedExpression(
        expression_id=expression_id,
        root=mk_predicate("n:p", "P"),
        signature=propositional_signature("sig:p", ("P",)),
    )


def _admitted_slice() -> DomainLogicSliceV2:
    document = _document()
    expression = _expression()
    return DomainLogicSliceV2(
        slice_id="slice:ev:1",
        domain="security_ir",
        document_id=document.document_id,
        source_digest=document.content_digest,
        expression_id=expression.expression_id,
        expression_digest=expression.content_digest,
        family=expression.family,
        profile=expression.profile,
        property=property_id("validity"),
        view=view_id("source"),
        notation=notation_id("canonical_text"),
        features=("propositional",),
    )


def _bounds() -> RequestBounds:
    return RequestBounds.default()


def _request() -> BackendRequestV2:
    return BackendRequestV2.from_slice(
        _admitted_slice(),
        request_id="req:ev:1",
        obligation_id="obl:ev:1",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
        requested_provider=provider_id("z3"),
    )


def _source_map() -> SourceMap:
    document = _document()
    return SourceMap(
        map_id="map:ev:1",
        document_id=document.document_id,
        entries=(
            SourceMapEntry(
                entry_id="map:entry:p",
                range=SourceRange(start=0, end=1),
                role="atom",
            ),
        ),
    )


def _live_execution() -> tuple[
    BackendRequestV2,
    object,
    object,
    ProviderExecutionReceiptV2,
]:
    request = _request()
    compiled = admit_compiled_target(
        request,
        artifact_id="compiled:ev:1",
        compiler_id="smtlib2.emit",
        target_text="(assert P)",
        source_map=_source_map(),
    )
    parsed = admit_parsed_result(
        compiled,
        artifact_id="parsed:ev:1",
        provider=provider_id("z3"),
        result_kind="satisfiability.model",
        output_text="sat\n((P true))",
        decoded_evidence_digest="e" * 64,
    )
    receipt = ProviderExecutionReceiptV2.from_parsed_target(
        parsed,
        receipt_id="exec:ev:1",
        launch_id="launch:z3:1",
        tool_id="tool:z3:4.13",
        bounds=request.bounds,
        record_kind=ExecutionRecordKind.LIVE,
        execution_claimed=True,
        outcome=ExecutionOutcome.SUCCEEDED,
        exit_code=0,
        duration_ms=12,
        toolchain_id="toolchain:z3-4",
    )
    return request, compiled, parsed, receipt


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert PROVIDER_EXECUTION_RECEIPT_V2_INTERFACE == "ProviderExecutionReceipt@2"
    assert EVIDENCE_REPLAY_RECEIPT_INTERFACE == "EvidenceReplayReceipt@1"
    assert EVIDENCE_V2_MODULE_VERSION


# ---------------------------------------------------------------------------
# ProviderExecutionReceipt@2
# ---------------------------------------------------------------------------


def test_live_execution_receipt_claims_execution() -> None:
    request, compiled, parsed, receipt = _live_execution()
    assert receipt.interface == PROVIDER_EXECUTION_RECEIPT_V2_INTERFACE
    assert receipt.is_executable_claim
    require_executable_receipt(receipt)
    receipt.validate_against(request=request, compiled=compiled, parsed=parsed)
    assert receipt.launch_id == "launch:z3:1"
    assert receipt.tool_id == "tool:z3:4.13"
    assert receipt.output_digest == parsed.output_digest
    assert receipt.parsed_target_id == parsed.artifact_id


def test_execution_receipt_round_trip() -> None:
    _, _, _, receipt = _live_execution()
    restored = ProviderExecutionReceiptV2.from_dict(receipt.to_dict())
    assert restored.content_digest == receipt.content_digest
    assert restored.execution_claimed is True


def test_successful_execution_requires_parsed_target() -> None:
    request = _request()
    compiled = admit_compiled_target(
        request,
        artifact_id="compiled:ev:noparse",
        compiler_id="smtlib2.emit",
        target_text="(assert P)",
        source_map=_source_map(),
    )
    with pytest.raises(ExecutionClaimError, match="parsed_target"):
        ProviderExecutionReceiptV2(
            receipt_id="exec:noparse",
            request_id=request.request_id,
            request_digest=request.content_digest,
            compiled_artifact_id=compiled.artifact_id,
            compiled_artifact_digest=compiled.content_digest,
            provider=provider_id("z3"),
            evidence_kind=evidence_id("model"),
            launch_id="launch:z3:1",
            tool_id="tool:z3",
            output_digest="a" * 64,
            result_digest="b" * 64,
            bounds=request.bounds,
            record_kind=ExecutionRecordKind.LIVE,
            execution_claimed=True,
            outcome=ExecutionOutcome.SUCCEEDED,
            parsed_target_id="",
            parsed_target_digest="",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
        )


def test_metadata_only_cannot_claim_execution() -> None:
    request = _request()
    compiled = admit_compiled_target(
        request,
        artifact_id="compiled:meta",
        compiler_id="smtlib2.emit",
        target_text="(assert P)",
        source_map=_source_map(),
    )
    with pytest.raises(ExecutionClaimError, match="cannot claim execution"):
        ProviderExecutionReceiptV2(
            receipt_id="exec:meta:claim",
            request_id=request.request_id,
            request_digest=request.content_digest,
            compiled_artifact_id=compiled.artifact_id,
            compiled_artifact_digest=compiled.content_digest,
            provider=provider_id("z3"),
            evidence_kind=evidence_id("model"),
            launch_id="launch:none",
            tool_id="tool:none",
            output_digest="a" * 64,
            result_digest="b" * 64,
            bounds=request.bounds,
            record_kind=ExecutionRecordKind.METADATA_ONLY,
            execution_claimed=True,
            outcome=ExecutionOutcome.SUCCEEDED,
            parsed_target_id="parsed:x",
            parsed_target_digest="c" * 64,
        )


def test_metadata_only_factory_is_non_claiming() -> None:
    request = _request()
    compiled = admit_compiled_target(
        request,
        artifact_id="compiled:meta2",
        compiler_id="smtlib2.emit",
        target_text="(assert P)",
        source_map=_source_map(),
    )
    receipt = ProviderExecutionReceiptV2.metadata_only(
        receipt_id="exec:meta:ok",
        request_id=request.request_id,
        request_digest=request.content_digest,
        compiled_artifact_id=compiled.artifact_id,
        compiled_artifact_digest=compiled.content_digest,
        provider=provider_id("z3"),
        evidence_kind=evidence_id("model"),
        bounds=request.bounds,
        reason="declaration_only",
    )
    assert receipt.record_kind is ExecutionRecordKind.METADATA_ONLY
    assert receipt.execution_claimed is False
    assert not receipt.is_executable_claim
    with pytest.raises(ExecutionClaimError, match="metadata-only"):
        require_executable_receipt(receipt)


def test_mock_cannot_claim_execution() -> None:
    request = _request()
    compiled = admit_compiled_target(
        request,
        artifact_id="compiled:mock",
        compiler_id="smtlib2.emit",
        target_text="(assert P)",
        source_map=_source_map(),
    )
    with pytest.raises(ExecutionClaimError, match="cannot claim execution"):
        ProviderExecutionReceiptV2(
            receipt_id="exec:mock:claim",
            request_id=request.request_id,
            request_digest=request.content_digest,
            compiled_artifact_id=compiled.artifact_id,
            compiled_artifact_digest=compiled.content_digest,
            provider=provider_id("z3"),
            evidence_kind=evidence_id("model"),
            launch_id="launch:mock",
            tool_id="tool:mock",
            output_digest="a" * 64,
            result_digest="b" * 64,
            bounds=request.bounds,
            record_kind=ExecutionRecordKind.MOCK,
            execution_claimed=True,
            outcome=ExecutionOutcome.SUCCEEDED,
            parsed_target_id="parsed:x",
            parsed_target_digest="c" * 64,
        )


def test_mock_factory_is_non_claiming() -> None:
    request = _request()
    compiled = admit_compiled_target(
        request,
        artifact_id="compiled:mock2",
        compiler_id="smtlib2.emit",
        target_text="(assert P)",
        source_map=_source_map(),
    )
    receipt = ProviderExecutionReceiptV2.mock_record(
        receipt_id="exec:mock:ok",
        request_id=request.request_id,
        request_digest=request.content_digest,
        compiled_artifact_id=compiled.artifact_id,
        compiled_artifact_digest=compiled.content_digest,
        provider=provider_id("z3"),
        evidence_kind=evidence_id("model"),
        bounds=request.bounds,
    )
    assert receipt.record_kind is ExecutionRecordKind.MOCK
    assert receipt.execution_claimed is False
    with pytest.raises(ExecutionClaimError, match="mock"):
        receipt.require_execution_claim()


def test_hermetic_fixture_may_claim_execution() -> None:
    request, compiled, parsed, _ = _live_execution()
    receipt = ProviderExecutionReceiptV2.from_parsed_target(
        parsed,
        receipt_id="exec:hermetic",
        launch_id="launch:fixture:1",
        tool_id="tool:fixture",
        bounds=request.bounds,
        record_kind=ExecutionRecordKind.HERMETIC_FIXTURE,
        execution_claimed=True,
    )
    assert receipt.is_executable_claim
    require_executable_receipt(receipt)


def test_execution_rejects_mock_execution_field() -> None:
    _, _, _, receipt = _live_execution()
    payload = receipt.to_dict()
    payload["mock_execution"] = True
    with pytest.raises(ExecutionClaimError, match="mock_execution"):
        ProviderExecutionReceiptV2.from_dict(payload)


def test_execution_lineage_mismatch_fails() -> None:
    request, compiled, parsed, receipt = _live_execution()
    other_request = BackendRequestV2.from_slice(
        _admitted_slice(),
        request_id="req:ev:other",
        obligation_id="obl:ev:other",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )
    with pytest.raises(EvidenceLineageError, match="request_id"):
        receipt.validate_against(request=other_request)


# ---------------------------------------------------------------------------
# EvidenceReplayReceipt@1
# ---------------------------------------------------------------------------


def test_replayed_receipt_claims_replay() -> None:
    _, _, _, execution = _live_execution()
    replay = EvidenceReplayReceipt.from_execution(
        execution,
        receipt_id="replay:1",
        disposition=ReplayDisposition.REPLAYED,
        replay_claimed=True,
        match_digest="f" * 64,
        decoded_evidence_digest="e" * 64,
    )
    assert replay.interface == EVIDENCE_REPLAY_RECEIPT_INTERFACE
    assert replay.is_replay_claim
    require_replay_receipt(replay)
    replay.validate_against_execution(execution)


def test_replay_receipt_round_trip() -> None:
    _, _, _, execution = _live_execution()
    replay = EvidenceReplayReceipt.from_execution(
        execution,
        receipt_id="replay:rt",
        disposition=ReplayDisposition.REPLAYED,
        replay_claimed=True,
        match_digest="f" * 64,
    )
    restored = EvidenceReplayReceipt.from_dict(replay.to_dict())
    assert restored.content_digest == replay.content_digest


def test_mock_source_cannot_claim_replay() -> None:
    request = _request()
    compiled = admit_compiled_target(
        request,
        artifact_id="compiled:mock-replay",
        compiler_id="smtlib2.emit",
        target_text="(assert P)",
        source_map=_source_map(),
    )
    mock = ProviderExecutionReceiptV2.mock_record(
        receipt_id="exec:mock:replay",
        request_id=request.request_id,
        request_digest=request.content_digest,
        compiled_artifact_id=compiled.artifact_id,
        compiled_artifact_digest=compiled.content_digest,
        provider=provider_id("z3"),
        evidence_kind=evidence_id("model"),
        bounds=request.bounds,
    )
    with pytest.raises(ReplayClaimError, match="executable source|mock"):
        EvidenceReplayReceipt.from_execution(
            mock,
            receipt_id="replay:mock",
            disposition=ReplayDisposition.REPLAYED,
            replay_claimed=True,
            match_digest="f" * 64,
        )


def test_metadata_only_cannot_use_replayed_disposition() -> None:
    request = _request()
    compiled = admit_compiled_target(
        request,
        artifact_id="compiled:meta-replay",
        compiler_id="smtlib2.emit",
        target_text="(assert P)",
        source_map=_source_map(),
    )
    meta = ProviderExecutionReceiptV2.metadata_only(
        receipt_id="exec:meta:replay",
        request_id=request.request_id,
        request_digest=request.content_digest,
        compiled_artifact_id=compiled.artifact_id,
        compiled_artifact_digest=compiled.content_digest,
        provider=provider_id("z3"),
        evidence_kind=evidence_id("model"),
        bounds=request.bounds,
    )
    with pytest.raises(ReplayClaimError, match="forbidden|metadata"):
        EvidenceReplayReceipt(
            receipt_id="replay:meta",
            execution_receipt_id=meta.receipt_id,
            execution_receipt_digest=meta.content_digest,
            disposition=ReplayDisposition.REPLAYED,
            source_record_kind=ExecutionRecordKind.METADATA_ONLY,
            replay_claimed=False,
            match_digest="f" * 64,
        )


def test_explicit_non_replay_does_not_claim() -> None:
    _, _, _, execution = _live_execution()
    replay = EvidenceReplayReceipt.explicit_non_replay(
        execution,
        receipt_id="replay:skip",
        reason="provider output is non-deterministic under current bounds",
        disposition=ReplayDisposition.NON_REPLAYABLE,
    )
    assert replay.replay_claimed is False
    assert not replay.is_replay_claim
    with pytest.raises(ReplayClaimError, match="does not claim replay"):
        require_replay_receipt(replay)


def test_replay_claimed_requires_match_digest() -> None:
    _, _, _, execution = _live_execution()
    with pytest.raises(ReplayClaimError, match="match_digest"):
        EvidenceReplayReceipt.from_execution(
            execution,
            receipt_id="replay:nodigest",
            disposition=ReplayDisposition.REPLAYED,
            replay_claimed=True,
            match_digest="",
        )


def test_replay_claimed_requires_replayed_disposition() -> None:
    _, _, _, execution = _live_execution()
    with pytest.raises(ReplayClaimError, match="disposition=replayed"):
        EvidenceReplayReceipt.from_execution(
            execution,
            receipt_id="replay:baddisp",
            disposition=ReplayDisposition.NOT_ATTEMPTED,
            replay_claimed=True,
            match_digest="f" * 64,
        )


def test_replay_rejects_fake_replay_field() -> None:
    _, _, _, execution = _live_execution()
    replay = EvidenceReplayReceipt.from_execution(
        execution,
        receipt_id="replay:fake",
        disposition=ReplayDisposition.EXPLICIT_SKIP,
        replay_claimed=False,
        reason="skip",
    )
    payload = replay.to_dict()
    payload["fake_replay"] = True
    with pytest.raises(ReplayClaimError, match="fake_replay"):
        EvidenceReplayReceipt.from_dict(payload)


def test_replay_lineage_mismatch_fails() -> None:
    _, _, _, execution = _live_execution()
    other = ProviderExecutionReceiptV2.from_parsed_target(
        admit_parsed_result(
            admit_compiled_target(
                _request(),
                artifact_id="compiled:other",
                compiler_id="smtlib2.emit",
                target_text="(assert Q)",
                source_map=_source_map(),
            ),
            artifact_id="parsed:other",
            provider=provider_id("z3"),
            result_kind="satisfiability.model",
            output_text="unsat",
        ),
        receipt_id="exec:other",
        launch_id="launch:other",
        tool_id="tool:other",
        bounds=_bounds(),
    )
    replay = EvidenceReplayReceipt.from_execution(
        execution,
        receipt_id="replay:mismatch",
        disposition=ReplayDisposition.REPLAYED,
        replay_claimed=True,
        match_digest="f" * 64,
    )
    with pytest.raises(EvidenceLineageError, match="execution_receipt"):
        replay.validate_against_execution(other)
