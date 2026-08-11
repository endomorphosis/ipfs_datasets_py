"""Unit tests for LogicObligation@2 and BackendRequest@2 (LFP2-007).

Acceptance coverage:

* admitted domain slices bind source/typed-expression identity before
  BackendRequest@2
* cross-namespace misuse fails before provider selection
* arbitrary payloads are rejected
* unsupported extensions fail closed
* missing bounds fail closed
* authority overclaims fail closed
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.requests_v2 import (
    BACKEND_REQUEST_V2_INTERFACE,
    LOGIC_OBLIGATION_V2_INTERFACE,
    REQUESTS_V2_MODULE_VERSION,
    ArbitraryPayloadError,
    AuthorityOverclaimError,
    BackendRequestV2,
    CrossNamespaceRequestError,
    LogicObligationV2,
    MissingBoundsError,
    RequestAuthorityCeiling,
    RequestBounds,
    UnsupportedExtensionRequestError,
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
    DomainSliceAdmissionError,
    DomainSliceStatus,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest as LegacyBackendRequest,
    ExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_predicate
from ipfs_datasets_py.logic.syntax_core.contracts import SourceDocument
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


def _document(text: str = "P", document_id: str = "doc:req-v2") -> SourceDocument:
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
        slice_id="slice:req:1",
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


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert LOGIC_OBLIGATION_V2_INTERFACE == "LogicObligation@2"
    assert BACKEND_REQUEST_V2_INTERFACE == "BackendRequest@2"
    assert REQUESTS_V2_MODULE_VERSION


# ---------------------------------------------------------------------------
# RequestBounds
# ---------------------------------------------------------------------------


def test_bounds_require_all_positive_fields() -> None:
    bounds = RequestBounds.default()
    assert bounds.timeout_ms > 0
    restored = RequestBounds.from_dict(bounds.to_dict())
    assert restored.to_dict() == bounds.to_dict()


def test_missing_bounds_fields_fail() -> None:
    with pytest.raises(MissingBoundsError, match="missing required"):
        RequestBounds.from_dict({"timeout_ms": 1000})


def test_non_positive_bounds_fail() -> None:
    with pytest.raises(MissingBoundsError, match="positive"):
        RequestBounds(
            timeout_ms=0,
            max_steps=1,
            max_memory_bytes=1,
            max_output_bytes=1,
        )


# ---------------------------------------------------------------------------
# LogicObligation@2
# ---------------------------------------------------------------------------


def test_obligation_from_admitted_slice() -> None:
    document = _document()
    expression = _expression()
    slice_item = _admitted_slice(document, expression)
    obligation = LogicObligationV2.from_slice(
        slice_item,
        obligation_id="obl:1",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )
    assert obligation.interface == LOGIC_OBLIGATION_V2_INTERFACE
    assert obligation.document_id == document.document_id
    assert obligation.expression_digest == expression.content_digest
    assert obligation.slice_id == slice_item.slice_id
    assert obligation.family.namespace.value == "family"
    assert obligation.encoding.value == "smtlib2"


def test_obligation_rejects_non_admitted_slice() -> None:
    document = _document()
    expression = _expression()
    rejected = DomainLogicSliceV2(
        slice_id="slice:rej",
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
        status=DomainSliceStatus.REJECTED,
    )
    with pytest.raises(DomainSliceAdmissionError, match="not admitted"):
        LogicObligationV2.from_slice(
            rejected,
            obligation_id="obl:rej",
            statement="prove P",
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=_bounds(),
        )


def test_obligation_rejects_missing_bounds() -> None:
    slice_item = _admitted_slice()
    with pytest.raises(MissingBoundsError, match="bounds"):
        LogicObligationV2.from_slice(
            slice_item,
            obligation_id="obl:nobounds",
            statement="prove P",
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=None,
        )


def test_obligation_rejects_unsupported_extensions() -> None:
    document = _document()
    expression = _expression()
    # Build a rejected/unsupported path via direct construction attempt on
    # obligation with unsupported extensions.
    with pytest.raises(UnsupportedExtensionRequestError, match="unsupported"):
        LogicObligationV2(
            obligation_id="obl:ext",
            statement="prove P",
            document_id=document.document_id,
            source_digest=document.content_digest,
            expression_id=expression.expression_id,
            expression_digest=expression.content_digest,
            family=expression.family,
            profile=expression.profile,
            property=property_id("validity"),
            view=view_id("source"),
            notation=notation_id("canonical_text"),
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=_bounds(),
            unsupported_extensions=("modal.kripke/v1",),
        )


def test_obligation_rejects_cross_namespace_encoding() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(CrossNamespaceRequestError, match="namespace"):
        LogicObligationV2(
            obligation_id="obl:xns",
            statement="prove P",
            document_id=document.document_id,
            source_digest=document.content_digest,
            expression_id=expression.expression_id,
            expression_digest=expression.content_digest,
            family=expression.family,
            profile=expression.profile,
            property=property_id("validity"),
            view=view_id("source"),
            notation=notation_id("canonical_text"),
            encoding=provider_id("z3"),  # provider is not encoding
            evidence_kind=evidence_id("model"),
            bounds=_bounds(),
        )


def test_obligation_rejects_authority_overclaim() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(AuthorityOverclaimError, match="overclaim"):
        LogicObligationV2(
            obligation_id="obl:over",
            statement="prove P",
            document_id=document.document_id,
            source_digest=document.content_digest,
            expression_id=expression.expression_id,
            expression_digest=expression.content_digest,
            family=expression.family,
            profile=expression.profile,
            property=property_id("validity"),
            view=view_id("source"),
            notation=notation_id("canonical_text"),
            encoding=encoding_id("lean4"),
            evidence_kind=evidence_id("parse"),  # parse cannot claim kernel
            bounds=_bounds(),
            authority_ceiling=RequestAuthorityCeiling.KERNEL,
        )


def test_obligation_rejects_arbitrary_payload_metadata() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(ArbitraryPayloadError, match="free-form"):
        LogicObligationV2(
            obligation_id="obl:payload",
            statement="prove P",
            document_id=document.document_id,
            source_digest=document.content_digest,
            expression_id=expression.expression_id,
            expression_digest=expression.content_digest,
            family=expression.family,
            profile=expression.profile,
            property=property_id("validity"),
            view=view_id("source"),
            notation=notation_id("canonical_text"),
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=_bounds(),
            metadata={"payload": {"family": "smt"}},
        )


def test_obligation_round_trip() -> None:
    slice_item = _admitted_slice()
    obligation = LogicObligationV2.from_slice(
        slice_item,
        obligation_id="obl:rt",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )
    restored = LogicObligationV2.from_dict(obligation.to_dict())
    assert restored.content_digest == obligation.content_digest


# ---------------------------------------------------------------------------
# BackendRequest@2
# ---------------------------------------------------------------------------


def test_backend_request_from_admitted_slice() -> None:
    document = _document()
    expression = _expression()
    slice_item = _admitted_slice(document, expression)
    request = BackendRequestV2.from_slice(
        slice_item,
        request_id="req:1",
        obligation_id="obl:1",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
        requested_provider=provider_id("z3"),
    )
    assert request.interface == BACKEND_REQUEST_V2_INTERFACE
    assert request.document_id == document.document_id
    assert request.expression_digest == expression.content_digest
    assert request.slice_id == slice_item.slice_id
    assert request.requested_provider is not None
    assert request.requested_provider.value == "z3"
    assert "payload" not in request.to_dict()
    assert "logic_family" not in request.to_dict()


def test_backend_request_from_obligation() -> None:
    slice_item = _admitted_slice()
    obligation = LogicObligationV2.from_slice(
        slice_item,
        obligation_id="obl:2",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )
    request = BackendRequestV2.from_obligation(obligation, request_id="req:2")
    assert request.obligation_digest == obligation.content_digest
    assert request.family.value == obligation.family.value  # type: ignore[union-attr]


def test_backend_request_rejects_arbitrary_payload_field() -> None:
    slice_item = _admitted_slice()
    request = BackendRequestV2.from_slice(
        slice_item,
        request_id="req:payload",
        obligation_id="obl:payload",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )
    payload = request.to_dict()
    payload["payload"] = {"raw_formula": "P"}
    with pytest.raises(ArbitraryPayloadError, match="arbitrary payload"):
        BackendRequestV2.from_dict(payload)


def test_backend_request_rejects_free_form_logic_family() -> None:
    with pytest.raises(ArbitraryPayloadError, match="logic_family"):
        BackendRequestV2.from_dict(
            {
                "request_id": "req:ff",
                "obligation_id": "obl:ff",
                "obligation_digest": "a" * 64,
                "document_id": "doc:req-v2",
                "source_digest": "b" * 64,
                "expression_id": "expr:p",
                "expression_digest": "c" * 64,
                "logic_family": "smt",  # free-form
                "profile": profile_id("classical").to_dict(),
                "property": property_id("validity").to_dict(),
                "view": view_id("source").to_dict(),
                "notation": notation_id("canonical_text").to_dict(),
                "encoding": encoding_id("smtlib2").to_dict(),
                "evidence_kind": evidence_id("model").to_dict(),
                "bounds": _bounds().to_dict(),
            }
        )


def test_backend_request_rejects_missing_bounds() -> None:
    slice_item = _admitted_slice()
    request = BackendRequestV2.from_slice(
        slice_item,
        request_id="req:nb",
        obligation_id="obl:nb",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )
    payload = request.to_dict()
    del payload["bounds"]
    with pytest.raises(MissingBoundsError, match="bounds"):
        BackendRequestV2.from_dict(payload)


def test_backend_request_rejects_cross_namespace_provider() -> None:
    slice_item = _admitted_slice()
    with pytest.raises(CrossNamespaceRequestError, match="namespace"):
        BackendRequestV2.from_slice(
            slice_item,
            request_id="req:xns",
            obligation_id="obl:xns",
            statement="prove P",
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=_bounds(),
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            requested_provider=family_id("first_order"),  # not a provider
        )


def test_backend_request_rejects_kernel_overclaim_on_model_evidence() -> None:
    slice_item = _admitted_slice()
    with pytest.raises(AuthorityOverclaimError):
        BackendRequestV2.from_slice(
            slice_item,
            request_id="req:kernel",
            obligation_id="obl:kernel",
            statement="prove P",
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=_bounds(),
            authority_ceiling=RequestAuthorityCeiling.KERNEL,
        )


def test_backend_request_rejects_non_admitted_slice() -> None:
    document = _document()
    expression = _expression()
    unsupported = DomainLogicSliceV2(
        slice_id="slice:unsup",
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
        status=DomainSliceStatus.UNSUPPORTED,
        unsupported_extensions=("hyper.trace/v1",),
    )
    with pytest.raises(DomainSliceAdmissionError):
        BackendRequestV2.from_slice(
            unsupported,
            request_id="req:unsup",
            obligation_id="obl:unsup",
            statement="prove P",
            encoding=encoding_id("smtlib2"),
            evidence_kind=evidence_id("model"),
            bounds=_bounds(),
        )


def test_backend_request_round_trip() -> None:
    slice_item = _admitted_slice()
    request = BackendRequestV2.from_slice(
        slice_item,
        request_id="req:rt",
        obligation_id="obl:rt",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )
    restored = BackendRequestV2.from_dict(request.to_dict())
    assert restored.content_digest == request.content_digest
    assert restored.expression_id == request.expression_id


def test_backend_request_legacy_lift_requires_lineage() -> None:
    legacy = LegacyBackendRequest(
        request_id="req:legacy",
        claim_id="claim:1",
        declaration_id="decl:1",
        claim_digest="a" * 64,
        obligation_id="obl:legacy",
        obligation_digest="b" * 64,
        assumption_ids=(),
        logic_family="first_order",
        query_kind=QueryKind.SATISFIABILITY,
        bounds=ExecutionBounds(),
        payload={},
    )
    document = _document()
    expression = _expression()
    request = BackendRequestV2.from_legacy(
        legacy,
        document_id=document.document_id,
        source_digest=document.content_digest,
        expression_id=expression.expression_id,
        expression_digest=expression.content_digest,
        profile=profile_id("classical"),
        property=property_id("validity"),
        view=view_id("source"),
        notation=notation_id("canonical_text"),
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )
    assert request.legacy_request_digest
    assert request.metadata["legacy_payload_dropped"] is True
    assert "payload" not in request.to_dict()


def test_end_to_end_slice_to_request_binds_identities() -> None:
    """Every admitted domain slice binds source + expression before request."""

    document = _document("P")
    expression = _expression()
    slice_item = DomainLogicSliceV2.from_typed_expression(
        expression,
        slice_id="slice:e2e",
        domain="intent_ir",
        document_id=document.document_id,
        source_digest=document.content_digest,
        property=property_id("validity"),
        features=("propositional",),
    )
    slice_item.require_admitted()
    slice_item.validate_against(document=document, expression=expression)

    request = BackendRequestV2.from_slice(
        slice_item,
        request_id="req:e2e",
        obligation_id="obl:e2e",
        statement="prove P",
        encoding=encoding_id("smtlib2"),
        evidence_kind=evidence_id("model"),
        bounds=_bounds(),
        authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
    )
    assert request.source_digest == document.content_digest
    assert request.expression_digest == expression.content_digest
    assert request.family.value == expression.family.value  # type: ignore[union-attr]
    assert request.slice_digest == slice_item.content_digest
