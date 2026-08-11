"""Unit tests for CompiledLogicArtifact@1 and ParsedTargetArtifact@1 (LFP2-008).

Acceptance coverage:

* raw target content cannot bypass CompiledLogicArtifact
* raw result content cannot bypass ParsedTargetArtifact
* admitted artifacts bind origin, source map, compiler, encoding, request,
  assumptions, losses, bounds, and digests
* unidentifiable target/result content fails closed
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.artifacts_v2 import (
    ARTIFACTS_V2_MODULE_VERSION,
    COMPILED_LOGIC_ARTIFACT_INTERFACE,
    PARSED_TARGET_ARTIFACT_INTERFACE,
    ArtifactLineageError,
    ArtifactV2Error,
    CompiledArtifactStatus,
    CompiledLogicArtifact,
    ParsedTargetArtifact,
    ParsedTargetStatus,
    RawResultAdmissionError,
    RawTargetAdmissionError,
    admit_compiled_target,
    admit_parsed_result,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    CrossNamespaceRequestError,
    MissingBoundsError,
    RequestAuthorityCeiling,
    RequestBounds,
)
from ipfs_datasets_py.logic.families.namespaces import (
    encoding_id,
    evidence_id,
    family_id,
    notation_id,
    profile_id,
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


def _document(text: str = "P", document_id: str = "doc:art-backend-v2") -> SourceDocument:
    return SourceDocument.from_text(document_id, text, encoding="utf-8")


def _expression(expression_id: str = "expr:p") -> TypedExpression:
    return TypedExpression(
        expression_id=expression_id,
        root=mk_predicate("n:p", "P"),
        signature=propositional_signature("sig:p", ("P",)),
    )


def _admitted_slice(
    document: SourceDocument | None = None,
    expression: TypedExpression | None = None,
) -> DomainLogicSliceV2:
    document = document or _document()
    expression = expression or _expression()
    return DomainLogicSliceV2(
        slice_id="slice:art:1",
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
        request_id="req:art:1",
        obligation_id="obl:art:1",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
        requested_provider=provider_id("z3"),
    )


def _source_map(document: SourceDocument | None = None) -> SourceMap:
    document = document or _document()
    return SourceMap(
        map_id="map:art:1",
        document_id=document.document_id,
        entries=(
            SourceMapEntry(
                entry_id="map:entry:p",
                range=SourceRange(start=0, end=1),
                role="atom",
            ),
        ),
    )


def _compiled(
    request: BackendRequestV2 | None = None,
    *,
    target_text: str = "(assert P)",
) -> CompiledLogicArtifact:
    request = request or _request()
    return admit_compiled_target(
        request,
        artifact_id="compiled:1",
        compiler_id="smtlib2.emit",
        target_text=target_text,
        source_map=_source_map(),
        assumption_ids=("asm:classical",),
        loss_ids=("loss.quantifier_prefix",),
        toolchain_id="toolchain:z3-4",
    )


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert COMPILED_LOGIC_ARTIFACT_INTERFACE == "CompiledLogicArtifact@1"
    assert PARSED_TARGET_ARTIFACT_INTERFACE == "ParsedTargetArtifact@1"
    assert ARTIFACTS_V2_MODULE_VERSION


# ---------------------------------------------------------------------------
# CompiledLogicArtifact@1
# ---------------------------------------------------------------------------


def test_admit_compiled_target_binds_origin_and_source_map() -> None:
    request = _request()
    compiled = _compiled(request)
    assert compiled.interface == COMPILED_LOGIC_ARTIFACT_INTERFACE
    assert compiled.is_admitted
    assert compiled.request_id == request.request_id
    assert compiled.request_digest == request.content_digest
    assert compiled.document_id == request.document_id
    assert compiled.source_digest == request.source_digest
    assert compiled.expression_digest == request.expression_digest
    assert compiled.target_digest
    assert compiled.source_map is not None
    assert compiled.compiler_id == "smtlib2.emit"
    assert "loss.quantifier_prefix" in compiled.loss_ids
    compiled.validate_against_request(request)


def test_compiled_artifact_round_trip() -> None:
    compiled = _compiled()
    restored = CompiledLogicArtifact.from_dict(compiled.to_wire_dict())
    assert restored.content_digest == compiled.content_digest
    assert restored.target_digest == compiled.target_digest
    assert restored.target_bytes == compiled.target_bytes


def test_compiled_rejects_missing_source_map_for_ok_status() -> None:
    request = _request()
    with pytest.raises(RawTargetAdmissionError, match="source_map"):
        CompiledLogicArtifact.from_request(
            request,
            artifact_id="compiled:nosmap",
            compiler_id="smtlib2.emit",
            target_text="(assert P)",
            source_map=None,
            status=CompiledArtifactStatus.OK,
        )


def test_compiled_rejects_empty_target() -> None:
    request = _request()
    with pytest.raises(RawTargetAdmissionError, match="identifiable"):
        CompiledLogicArtifact.from_request(
            request,
            artifact_id="compiled:empty",
            compiler_id="smtlib2.emit",
            target_text="",
            target_bytes=b"",
            source_map=_source_map(),
        )


def test_compiled_rejects_mismatched_target_digest() -> None:
    request = _request()
    with pytest.raises(ArtifactV2Error, match="target_digest"):
        CompiledLogicArtifact(
            artifact_id="compiled:bad-digest",
            request_id=request.request_id,
            request_digest=request.content_digest,
            document_id=request.document_id,
            source_digest=request.source_digest,
            expression_id=request.expression_id,
            expression_digest=request.expression_digest,
            family=request.family,
            profile=request.profile,
            property=request.property,
            view=request.view,
            notation=request.notation,
            encoding=request.encoding,
            compiler_id="smtlib2.emit",
            bounds=request.bounds,
            target_text="(assert P)",
            target_digest="a" * 64,
            source_map=_source_map(),
            evidence_kind=request.evidence_kind,
            authority_ceiling=request.authority_ceiling,
        )


def test_compiled_rejects_missing_bounds() -> None:
    request = _request()
    payload = CompiledLogicArtifact.from_request(
        request,
        artifact_id="compiled:bounds",
        compiler_id="smtlib2.emit",
        target_text="(assert P)",
        source_map=_source_map(),
    ).to_dict()
    del payload["bounds"]
    with pytest.raises(MissingBoundsError, match="bounds"):
        CompiledLogicArtifact.from_dict(payload)


def test_compiled_rejects_raw_target_field() -> None:
    request = _request()
    payload = _compiled(request).to_dict()
    payload["raw_target"] = "(assert Q)"
    with pytest.raises(RawTargetAdmissionError, match="raw_target"):
        CompiledLogicArtifact.from_dict(payload)


def test_compiled_rejects_free_form_payload_without_target() -> None:
    with pytest.raises(RawTargetAdmissionError, match="payload"):
        CompiledLogicArtifact.from_dict(
            {
                "artifact_id": "compiled:payload",
                "request_id": "req:x",
                "request_digest": "a" * 64,
                "document_id": "doc:x",
                "source_digest": "b" * 64,
                "expression_id": "expr:x",
                "expression_digest": "c" * 64,
                "family": family_id("first_order").to_dict(),
                "profile": profile_id("classical").to_dict(),
                "property": property_id("validity").to_dict(),
                "view": view_id("source").to_dict(),
                "notation": notation_id("canonical_text").to_dict(),
                "encoding": encoding_id("smtlib2").to_dict(),
                "compiler_id": "smtlib2.emit",
                "bounds": _bounds().to_dict(),
                "payload": {"target_source": "P"},
            }
        )


def test_compiled_rejects_cross_namespace_encoding() -> None:
    request = _request()
    with pytest.raises(CrossNamespaceRequestError, match="namespace"):
        CompiledLogicArtifact(
            artifact_id="compiled:xns",
            request_id=request.request_id,
            request_digest=request.content_digest,
            document_id=request.document_id,
            source_digest=request.source_digest,
            expression_id=request.expression_id,
            expression_digest=request.expression_digest,
            family=request.family,
            profile=request.profile,
            property=request.property,
            view=request.view,
            notation=request.notation,
            encoding=provider_id("z3"),  # not encoding
            compiler_id="smtlib2.emit",
            bounds=request.bounds,
            target_text="(assert P)",
            source_map=_source_map(),
        )


def test_compiled_rejects_source_map_document_mismatch() -> None:
    request = _request()
    bad_map = SourceMap(
        map_id="map:bad",
        document_id="doc:other",
        entries=(
            SourceMapEntry(
                entry_id="map:entry:bad",
                range=SourceRange(start=0, end=1),
                role="atom",
            ),
        ),
    )
    with pytest.raises(ArtifactLineageError, match="document_id"):
        CompiledLogicArtifact.from_request(
            request,
            artifact_id="compiled:bad-map",
            compiler_id="smtlib2.emit",
            target_text="(assert P)",
            source_map=bad_map,
        )


def test_admit_compiled_target_requires_request() -> None:
    with pytest.raises(RawTargetAdmissionError, match="BackendRequest"):
        admit_compiled_target(  # type: ignore[arg-type]
            object(),
            artifact_id="compiled:bad",
            compiler_id="smtlib2.emit",
            target_text="(assert P)",
            source_map=_source_map(),
        )


def test_failed_compiled_may_omit_source_map() -> None:
    request = _request()
    failed = CompiledLogicArtifact.from_request(
        request,
        artifact_id="compiled:failed",
        compiler_id="smtlib2.emit",
        target_text="(assert P)",
        source_map=None,
        status=CompiledArtifactStatus.FAILED,
    )
    assert failed.status is CompiledArtifactStatus.FAILED
    assert not failed.is_admitted
    with pytest.raises(RawTargetAdmissionError, match="not admitted"):
        failed.require_admitted()


# ---------------------------------------------------------------------------
# ParsedTargetArtifact@1
# ---------------------------------------------------------------------------


def test_admit_parsed_result_binds_compiled_lineage() -> None:
    compiled = _compiled()
    parsed = admit_parsed_result(
        compiled,
        artifact_id="parsed:1",
        provider=provider_id("z3"),
        result_kind="satisfiability.model",
        output_text="sat\n((P true))",
        decoded_evidence_digest="d" * 64,
    )
    assert parsed.interface == PARSED_TARGET_ARTIFACT_INTERFACE
    assert parsed.is_admitted
    assert parsed.compiled_artifact_id == compiled.artifact_id
    assert parsed.compiled_artifact_digest == compiled.content_digest
    assert parsed.output_digest
    assert parsed.result_digest
    assert parsed.target_digest == compiled.target_digest
    parsed.validate_against_compiled(compiled)


def test_parsed_artifact_round_trip() -> None:
    compiled = _compiled()
    parsed = admit_parsed_result(
        compiled,
        artifact_id="parsed:rt",
        provider=provider_id("z3"),
        result_kind="satisfiability.model",
        output_text="sat",
    )
    restored = ParsedTargetArtifact.from_dict(parsed.to_wire_dict())
    assert restored.content_digest == parsed.content_digest
    assert restored.output_bytes == parsed.output_bytes


def test_parsed_rejects_missing_output() -> None:
    compiled = _compiled()
    with pytest.raises(RawResultAdmissionError, match="identifiable"):
        ParsedTargetArtifact.from_compiled(
            compiled,
            artifact_id="parsed:empty",
            provider=provider_id("z3"),
            result_kind="satisfiability.model",
            output_text="",
            output_bytes=b"",
            output_digest="",
        )


def test_parsed_rejects_raw_result_field() -> None:
    compiled = _compiled()
    parsed = admit_parsed_result(
        compiled,
        artifact_id="parsed:raw",
        provider=provider_id("z3"),
        result_kind="satisfiability.model",
        output_text="sat",
    )
    payload = parsed.to_dict()
    payload["raw_result"] = "sat"
    with pytest.raises(RawResultAdmissionError, match="raw_result"):
        ParsedTargetArtifact.from_dict(payload)


def test_parsed_rejects_without_compiled_lineage() -> None:
    compiled = _compiled()
    parsed = admit_parsed_result(
        compiled,
        artifact_id="parsed:nolineage",
        provider=provider_id("z3"),
        result_kind="satisfiability.model",
        output_text="sat",
    )
    payload = parsed.to_dict()
    # Break compiled lineage while keeping digest-shaped fields.
    payload["compiled_artifact_id"] = "compiled:missing"
    payload["compiled_artifact_digest"] = "0" * 64
    payload["content_digest"] = ""
    restored = ParsedTargetArtifact.from_dict(payload)
    # Restored object is structurally valid but no longer matches the parent.
    with pytest.raises(ArtifactLineageError, match="compiled_artifact"):
        restored.validate_against_compiled(compiled)


def test_parsed_rejects_cross_namespace_provider() -> None:
    compiled = _compiled()
    with pytest.raises(CrossNamespaceRequestError, match="namespace"):
        ParsedTargetArtifact.from_compiled(
            compiled,
            artifact_id="parsed:xns",
            provider=family_id("first_order"),
            result_kind="satisfiability.model",
            output_text="sat",
        )


def test_parsed_rejects_lineage_mismatch() -> None:
    compiled = _compiled()
    other = _compiled()
    # Force a different artifact by changing target text.
    other = admit_compiled_target(
        _request(),
        artifact_id="compiled:other",
        compiler_id="smtlib2.emit",
        target_text="(assert Q)",
        source_map=_source_map(),
    )
    parsed = admit_parsed_result(
        compiled,
        artifact_id="parsed:mismatch",
        provider=provider_id("z3"),
        result_kind="satisfiability.model",
        output_text="sat",
    )
    with pytest.raises(ArtifactLineageError, match="compiled_artifact"):
        parsed.validate_against_compiled(other)


def test_admit_parsed_result_requires_compiled() -> None:
    with pytest.raises(RawResultAdmissionError, match="CompiledLogicArtifact"):
        admit_parsed_result(  # type: ignore[arg-type]
            object(),
            artifact_id="parsed:bad",
            provider=provider_id("z3"),
            result_kind="satisfiability.model",
            output_text="sat",
        )


def test_rejected_parsed_cannot_claim_admission() -> None:
    compiled = _compiled()
    rejected = ParsedTargetArtifact.from_compiled(
        compiled,
        artifact_id="parsed:rej",
        provider=provider_id("z3"),
        result_kind="satisfiability.model",
        output_text="unknown",
        status=ParsedTargetStatus.REJECTED,
    )
    assert not rejected.is_admitted
    with pytest.raises(RawResultAdmissionError, match="not admitted"):
        rejected.require_admitted()
