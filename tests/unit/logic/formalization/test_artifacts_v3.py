"""Unit tests for FormalizationArtifact@3 and DomainLogicSlice@2 (LFP2-007).

Acceptance coverage:

* every admitted domain slice binds source and typed-expression identity
* free-form routing metadata is rejected
* unsupported extensions cannot be admitted
* cross-namespace identity misuse fails closed
* artifacts round-trip through codecs with stable digests
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.families.namespaces import (
    notation_id,
    property_id,
    provider_id,
    view_id,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    ARTIFACTS_V3_MODULE_VERSION,
    DOMAIN_LOGIC_SLICE_V2_INTERFACE,
    FORMALIZATION_ARTIFACT_V3_INTERFACE,
    ArtifactV3Error,
    ArtifactV3LineageError,
    DomainLogicSliceV2,
    DomainSliceAdmissionError,
    DomainSliceStatus,
    FormalizationArtifactStatus,
    FormalizationArtifactV3,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_predicate
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SourceDocument,
    SourceMap,
    SourceMapEntry,
    SourceRange,
    SyntaxDiagnostic,
)
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


def _document(text: str = "P", document_id: str = "doc:form-v3") -> SourceDocument:
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
    **overrides: object,
) -> DomainLogicSliceV2:
    document = document or _document()
    expression = expression or _expression()
    kwargs: dict[str, object] = {
        "slice_id": "slice:1",
        "domain": "security_ir",
        "document_id": document.document_id,
        "source_digest": document.content_digest,
        "expression_id": expression.expression_id,
        "expression_digest": expression.content_digest,
        "family": expression.family,
        "profile": expression.profile,
        "property": property_id("validity"),
        "view": view_id("source"),
        "notation": notation_id("canonical_text"),
        "status": DomainSliceStatus.ADMITTED,
        "features": ("propositional",),
    }
    kwargs.update(overrides)
    return DomainLogicSliceV2(**kwargs)  # type: ignore[arg-type]


def _formalization(
    document: SourceDocument | None = None,
    expression: TypedExpression | None = None,
    **overrides: object,
) -> FormalizationArtifactV3:
    document = document or _document()
    expression = expression or _expression()
    slice_item = _admitted_slice(document, expression)
    kwargs: dict[str, object] = {
        "artifact_id": "art:form:1",
        "sample_id": "sample:1",
        "domain": "security_ir",
        "document_id": document.document_id,
        "source_digest": document.content_digest,
        "expression_id": expression.expression_id,
        "expression_digest": expression.content_digest,
        "family": expression.family,
        "profile": expression.profile,
        "view": view_id("source"),
        "notation": notation_id("canonical_text"),
        "status": FormalizationArtifactStatus.OK,
        "slices": (slice_item,),
    }
    kwargs.update(overrides)
    return FormalizationArtifactV3(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert FORMALIZATION_ARTIFACT_V3_INTERFACE == "FormalizationArtifact@3"
    assert DOMAIN_LOGIC_SLICE_V2_INTERFACE == "DomainLogicSlice@2"
    assert ARTIFACTS_V3_MODULE_VERSION


# ---------------------------------------------------------------------------
# DomainLogicSlice@2
# ---------------------------------------------------------------------------


def test_admitted_slice_binds_source_and_expression() -> None:
    document = _document("P & Q")
    expression = _expression()
    slice_item = _admitted_slice(document, expression)
    assert slice_item.interface == DOMAIN_LOGIC_SLICE_V2_INTERFACE
    assert slice_item.is_admitted
    assert slice_item.source_digest == document.content_digest
    assert slice_item.expression_digest == expression.content_digest
    assert slice_item.family.namespace.value == "family"
    assert slice_item.property.value == "validity"
    slice_item.validate_against(document=document, expression=expression)
    slice_item.require_admitted()


def test_slice_from_typed_expression() -> None:
    document = _document()
    expression = _expression()
    slice_item = DomainLogicSliceV2.from_typed_expression(
        expression,
        slice_id="slice:from-expr",
        domain="crypto_ir",
        document_id=document.document_id,
        source_digest=document.content_digest,
        property=property_id("safety"),
        features=("propositional",),
    )
    assert slice_item.domain == "crypto_ir"
    assert slice_item.expression_id == expression.expression_id
    assert slice_item.property.value == "safety"


def test_slice_rejects_cross_namespace_family() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(ArtifactV3Error, match="namespace"):
        _admitted_slice(
            document,
            expression,
            family=provider_id("z3"),  # provider is not a family
        )


def test_slice_rejects_free_form_payload_metadata() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(ArtifactV3Error, match="free-form routing"):
        _admitted_slice(
            document,
            expression,
            metadata={"payload": {"raw": "true"}},
        )


def test_admitted_slice_rejects_unsupported_extensions() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(DomainSliceAdmissionError, match="unsupported"):
        _admitted_slice(
            document,
            expression,
            unsupported_extensions=("modal.kripke/v1",),
        )


def test_unsupported_slice_requires_extension_list() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(DomainSliceAdmissionError, match="unsupported_extensions"):
        _admitted_slice(
            document,
            expression,
            status=DomainSliceStatus.UNSUPPORTED,
            unsupported_extensions=(),
        )


def test_rejected_slice_is_not_admitted() -> None:
    document = _document()
    expression = _expression()
    slice_item = _admitted_slice(
        document,
        expression,
        status=DomainSliceStatus.REJECTED,
        unsupported_extensions=(),
    )
    assert not slice_item.is_admitted
    with pytest.raises(DomainSliceAdmissionError, match="not admitted"):
        slice_item.require_admitted()


def test_slice_round_trip_stable_digest() -> None:
    slice_item = _admitted_slice()
    restored = DomainLogicSliceV2.from_dict(slice_item.to_dict())
    assert restored.content_digest == slice_item.content_digest
    assert restored.to_dict() == slice_item.to_dict()


def test_slice_source_digest_mismatch() -> None:
    document = _document("P")
    other = _document("Q", document_id="doc:form-v3")
    expression = _expression()
    slice_item = _admitted_slice(document, expression)
    with pytest.raises(ArtifactV3LineageError, match="source_digest"):
        slice_item.validate_against(document=other)


# ---------------------------------------------------------------------------
# FormalizationArtifact@3
# ---------------------------------------------------------------------------


def test_formalization_binds_source_expression_and_slices() -> None:
    document = _document()
    expression = _expression()
    artifact = _formalization(document, expression)
    assert artifact.interface == FORMALIZATION_ARTIFACT_V3_INTERFACE
    assert len(artifact.admitted_slices) == 1
    artifact.validate_against(document=document, expression=expression)
    assert artifact.require_admitted_slices()[0].slice_id == "slice:1"


def test_formalization_ok_requires_admitted_slice() -> None:
    document = _document()
    expression = _expression()
    rejected = _admitted_slice(
        document,
        expression,
        status=DomainSliceStatus.REJECTED,
    )
    with pytest.raises(ArtifactV3Error, match="admitted"):
        _formalization(document, expression, slices=(rejected,))


def test_formalization_rejects_slice_source_mismatch() -> None:
    document = _document()
    other = _document("Q", document_id="doc:other")
    expression = _expression()
    bad_slice = _admitted_slice(other, expression)
    with pytest.raises(ArtifactV3LineageError, match="document_id"):
        _formalization(document, expression, slices=(bad_slice,))


def test_formalization_round_trip() -> None:
    artifact = _formalization()
    restored = FormalizationArtifactV3.from_dict(artifact.to_dict())
    assert restored.content_digest == artifact.content_digest
    assert restored.lineage_digest == artifact.lineage_digest
    assert restored.slices[0].expression_digest == artifact.expression_digest


def test_formalization_rejects_wrong_content_digest() -> None:
    artifact = _formalization()
    payload = artifact.to_dict()
    payload["content_digest"] = "0" * 64
    with pytest.raises(ArtifactV3Error, match="content_digest"):
        FormalizationArtifactV3.from_dict(payload)


def test_formalization_rejects_payload_metadata() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(ArtifactV3Error, match="free-form routing"):
        _formalization(
            document,
            expression,
            metadata={"raw_formula": "P"},
        )


def test_formalization_source_map_lineage() -> None:
    document = _document("P")
    expression = _expression()
    source_map = SourceMap(
        map_id="map:1",
        document_id=document.document_id,
        entries=(
            SourceMapEntry(
                entry_id="map:entry:p",
                range=SourceRange(start=0, end=1),
                role="identifier",
            ),
        ),
    )
    artifact = _formalization(document, expression, source_map=source_map)
    artifact.validate_against(document=document, expression=expression)
    assert artifact.source_map is not None
    assert artifact.source_map.document_id == document.document_id


def test_formalization_rejects_dangling_diagnostic_lineage() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(ArtifactV3LineageError, match="unknown related"):
        _formalization(
            document,
            expression,
            status=FormalizationArtifactStatus.FAILED,
            slices=(
                _admitted_slice(
                    document,
                    expression,
                    status=DomainSliceStatus.REJECTED,
                ),
            ),
            diagnostics=(
                SyntaxDiagnostic(
                    diagnostic_id="diag:orphan",
                    code="formalization.error.sample",
                    message="orphan",
                    related_diagnostic_ids=("diag:missing",),
                ),
            ),
        )
