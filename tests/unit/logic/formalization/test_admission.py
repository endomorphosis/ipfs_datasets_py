"""LPC-040: admit only FormalizationArtifact@3 / DomainLogicSlice@2 new writes.

Acceptance:

* New writes bind source, digest, spans, expression identity,
  family/profile/property/view/notation, features, assumptions, unsupported
  extensions, status, and content identity.
* Incomplete, free-form, or lineage-broken writes fail closed before backend use.
* Production contracts live in ``artifacts_v3`` (preserved); this module owns
  the admission regression gate and binding inventory checks.

Durable note:
``data/agent_supervisor/logic_platform_canonicalization/notes/new_write_path.md``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from ipfs_datasets_py.logic.families.namespaces import (
    notation_id,
    property_id,
    provider_id,
    view_id,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
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
    SyntaxContractError,
)
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


# ---------------------------------------------------------------------------
# Paths and binding inventory
# ---------------------------------------------------------------------------

def _new_write_path_note() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "new_write_path.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / note_relative

# Required bindings on every admitted new write (LPC-040 acceptance).
REQUIRED_SLICE_BINDINGS: Final[tuple[str, ...]] = (
    "document_id",
    "source_digest",
    "expression_id",
    "expression_digest",
    "family",
    "profile",
    "property",
    "view",
    "notation",
    "features",
    "assumption_ids",
    "unsupported_extensions",
    "status",
    "content_digest",
    "source_range",  # spans (optional object; presence tracked when provided)
)

REQUIRED_ARTIFACT_BINDINGS: Final[tuple[str, ...]] = (
    "document_id",
    "source_digest",
    "expression_id",
    "expression_digest",
    "family",
    "profile",
    "view",
    "notation",
    "assumption_ids",
    "status",
    "content_digest",
    "lineage_digest",
    "slices",
    "source_map",  # spans
)

ADMITTED_GENERATIONS: Final[frozenset[str]] = frozenset(
    {
        FORMALIZATION_ARTIFACT_V3_INTERFACE,
        DOMAIN_LOGIC_SLICE_V2_INTERFACE,
    }
)


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _document(text: str = "P", document_id: str = "doc:admit-lpc040") -> SourceDocument:
    return SourceDocument.from_text(document_id, text, encoding="utf-8")


def _expression(expression_id: str = "expr:admit-p") -> TypedExpression:
    return TypedExpression(
        expression_id=expression_id,
        root=mk_predicate("n:p", "P"),
        signature=propositional_signature("sig:admit-p", ("P",)),
        range=SourceRange(start=0, end=1),
    )


def _source_map(document: SourceDocument) -> SourceMap:
    return SourceMap(
        map_id="map:admit-1",
        document_id=document.document_id,
        entries=(
            SourceMapEntry(
                entry_id="map:entry:p",
                range=SourceRange(start=0, end=1),
                role="identifier",
            ),
        ),
    )


def _bound_slice(
    document: SourceDocument | None = None,
    expression: TypedExpression | None = None,
    **overrides: object,
) -> DomainLogicSliceV2:
    document = document or _document()
    expression = expression or _expression()
    kwargs: dict[str, object] = {
        "slice_id": "slice:admit:1",
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
        "source_range": SourceRange(start=0, end=1),
        "features": ("propositional", "classical"),
        "assumption_ids": ("asm:closed-world",),
        "unsupported_extensions": (),
    }
    kwargs.update(overrides)
    return DomainLogicSliceV2(**kwargs)  # type: ignore[arg-type]


def _bound_artifact(
    document: SourceDocument | None = None,
    expression: TypedExpression | None = None,
    **overrides: object,
) -> FormalizationArtifactV3:
    document = document or _document()
    expression = expression or _expression()
    slice_item = overrides.pop("slices", None)
    if slice_item is None:
        slice_item = (_bound_slice(document, expression),)
    kwargs: dict[str, object] = {
        "artifact_id": "art:admit:1",
        "sample_id": "sample:admit:1",
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
        "slices": slice_item,
        "source_map": _source_map(document),
        "assumption_ids": ("asm:closed-world",),
    }
    kwargs.update(overrides)
    return FormalizationArtifactV3(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Admission helper (LPC-040 gate surface; does not replace artifacts_v3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NewWriteAdmissionReport:
    """Result of admitting a FormalizationArtifact@3 new write."""

    artifact: FormalizationArtifactV3
    admitted_slices: tuple[DomainLogicSliceV2, ...]
    bound_fields: tuple[str, ...]


class NewWriteAdmissionError(DomainSliceAdmissionError):
    """Raised when a candidate write fails the LPC-040 binding inventory."""


def _namespace_value(identity: object) -> str:
    value = getattr(identity, "value", None)
    if value is None:
        raise NewWriteAdmissionError(f"missing namespace identity value: {identity!r}")
    text = str(value)
    if not text:
        raise NewWriteAdmissionError("namespace identity value must be non-empty")
    return text


def _require_nonempty_text(value: object, field_name: str) -> str:
    text = str(value or "")
    if not text:
        raise NewWriteAdmissionError(f"new write missing required binding {field_name}")
    return text


def _require_sha256(value: object, field_name: str) -> str:
    text = _require_nonempty_text(value, field_name)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text.lower()):
        raise NewWriteAdmissionError(
            f"{field_name} must be a sha256 hex digest; got {text!r}"
        )
    return text.lower()


def inspect_slice_bindings(slice_item: DomainLogicSliceV2) -> tuple[str, ...]:
    """Return bound field names for one DomainLogicSlice@2; fail if incomplete."""

    if slice_item.interface != DOMAIN_LOGIC_SLICE_V2_INTERFACE:
        raise NewWriteAdmissionError(
            f"new writes require {DOMAIN_LOGIC_SLICE_V2_INTERFACE}; "
            f"got {slice_item.interface!r}"
        )

    bound: list[str] = []
    _require_nonempty_text(slice_item.document_id, "document_id")
    bound.append("document_id")
    _require_sha256(slice_item.source_digest, "source_digest")
    bound.append("source_digest")
    _require_nonempty_text(slice_item.expression_id, "expression_id")
    bound.append("expression_id")
    _require_sha256(slice_item.expression_digest, "expression_digest")
    bound.append("expression_digest")

    for field_name in ("family", "profile", "property", "view", "notation"):
        _namespace_value(getattr(slice_item, field_name))
        bound.append(field_name)

    # Features, assumptions, and unsupported extensions are always present as
    # tuples on the contract (may be empty where allowed).
    if not isinstance(slice_item.features, tuple):
        raise NewWriteAdmissionError("features must be a tuple")
    bound.append("features")
    if not isinstance(slice_item.assumption_ids, tuple):
        raise NewWriteAdmissionError("assumption_ids must be a tuple")
    bound.append("assumption_ids")
    if not isinstance(slice_item.unsupported_extensions, tuple):
        raise NewWriteAdmissionError("unsupported_extensions must be a tuple")
    bound.append("unsupported_extensions")

    status = slice_item.status
    status_value = status.value if hasattr(status, "value") else str(status)
    _require_nonempty_text(status_value, "status")
    bound.append("status")

    _require_sha256(slice_item.content_digest, "content_digest")
    bound.append("content_digest")

    # Spans: source_range is optional but when present must be a SourceRange.
    if slice_item.source_range is not None:
        if not isinstance(slice_item.source_range, SourceRange):
            raise NewWriteAdmissionError("source_range must be a SourceRange when set")
        bound.append("source_range")

    if slice_item.is_admitted:
        if slice_item.unsupported_extensions:
            raise NewWriteAdmissionError(
                "admitted DomainLogicSlice@2 cannot carry unsupported_extensions"
            )
        slice_item.require_admitted()

    return tuple(bound)


def inspect_artifact_bindings(
    artifact: FormalizationArtifactV3,
) -> tuple[str, ...]:
    """Return bound field names for one FormalizationArtifact@3."""

    if artifact.interface != FORMALIZATION_ARTIFACT_V3_INTERFACE:
        raise NewWriteAdmissionError(
            f"new writes require {FORMALIZATION_ARTIFACT_V3_INTERFACE}; "
            f"got {artifact.interface!r}"
        )

    bound: list[str] = []
    _require_nonempty_text(artifact.document_id, "document_id")
    bound.append("document_id")
    _require_sha256(artifact.source_digest, "source_digest")
    bound.append("source_digest")
    _require_nonempty_text(artifact.expression_id, "expression_id")
    bound.append("expression_id")
    _require_sha256(artifact.expression_digest, "expression_digest")
    bound.append("expression_digest")

    for field_name in ("family", "profile", "view", "notation"):
        _namespace_value(getattr(artifact, field_name))
        bound.append(field_name)

    if not isinstance(artifact.assumption_ids, tuple):
        raise NewWriteAdmissionError("assumption_ids must be a tuple")
    bound.append("assumption_ids")

    status_value = (
        artifact.status.value if hasattr(artifact.status, "value") else str(artifact.status)
    )
    _require_nonempty_text(status_value, "status")
    bound.append("status")

    _require_sha256(artifact.content_digest, "content_digest")
    bound.append("content_digest")
    _require_sha256(artifact.lineage_digest, "lineage_digest")
    bound.append("lineage_digest")

    if not artifact.slices:
        raise NewWriteAdmissionError(
            "FormalizationArtifact@3 new write requires at least one DomainLogicSlice@2"
        )
    bound.append("slices")

    if artifact.source_map is not None:
        if not isinstance(artifact.source_map, SourceMap):
            raise NewWriteAdmissionError("source_map must be a SourceMap when set")
        bound.append("source_map")

    for slice_item in artifact.slices:
        inspect_slice_bindings(slice_item)

    return tuple(bound)


def admit_new_write(
    artifact: FormalizationArtifactV3,
    *,
    document: SourceDocument | None = None,
    expression: TypedExpression | None = None,
) -> NewWriteAdmissionReport:
    """Admit a FormalizationArtifact@3 new write under LPC-040 binding rules.

    Fail-closed.  Does not replace ``artifacts_v3`` construction checks; it
    re-validates the binding inventory and requires admitted slices for
    backend-facing use.
    """

    if not isinstance(artifact, FormalizationArtifactV3):
        raise NewWriteAdmissionError(
            "new writes must be FormalizationArtifact@3; legacy compiler "
            "FormalizationArtifact is not an admitted write path"
        )

    bound = inspect_artifact_bindings(artifact)
    artifact.validate_against(document=document, expression=expression)
    admitted = artifact.require_admitted_slices()
    for slice_item in admitted:
        slice_item.validate_against(document=document, expression=expression)
        inspect_slice_bindings(slice_item)

    return NewWriteAdmissionReport(
        artifact=artifact,
        admitted_slices=admitted,
        bound_fields=bound,
    )


def admit_slice_new_write(
    slice_item: DomainLogicSliceV2,
    *,
    document: SourceDocument | None = None,
    expression: TypedExpression | None = None,
) -> DomainLogicSliceV2:
    """Admit one DomainLogicSlice@2 new write; reject non-admitted status."""

    if not isinstance(slice_item, DomainLogicSliceV2):
        raise NewWriteAdmissionError(
            "new domain writes must be DomainLogicSlice@2"
        )
    inspect_slice_bindings(slice_item)
    slice_item.validate_against(document=document, expression=expression)
    return slice_item.require_admitted()


# ---------------------------------------------------------------------------
# Note presence
# ---------------------------------------------------------------------------


def test_new_write_path_note_exists_and_names_interfaces() -> None:
    note_path = _new_write_path_note()
    assert note_path.is_file(), f"missing {note_path}"
    text = note_path.read_text(encoding="utf-8")
    assert "FormalizationArtifact@3" in text
    assert "DomainLogicSlice@2" in text
    assert "content identity" in text.lower() or "content_digest" in text
    for token in (
        "source",
        "expression identity",
        "family",
        "profile",
        "property",
        "view",
        "notation",
        "features",
        "assumptions",
        "unsupported extensions",
        "status",
    ):
        assert token.lower() in text.lower(), f"note missing binding topic {token!r}"


# ---------------------------------------------------------------------------
# Happy-path admission: full binding inventory
# ---------------------------------------------------------------------------


def test_admit_new_write_binds_full_inventory() -> None:
    document = _document("P")
    expression = _expression()
    artifact = _bound_artifact(document, expression)

    report = admit_new_write(artifact, document=document, expression=expression)

    assert report.artifact.interface in ADMITTED_GENERATIONS
    assert len(report.admitted_slices) == 1
    slice_item = report.admitted_slices[0]
    assert slice_item.interface == DOMAIN_LOGIC_SLICE_V2_INTERFACE
    assert slice_item.is_admitted

    # Source + digest
    assert slice_item.document_id == document.document_id
    assert slice_item.source_digest == document.content_digest
    assert artifact.source_digest == document.content_digest

    # Expression identity
    assert slice_item.expression_id == expression.expression_id
    assert slice_item.expression_digest == expression.content_digest
    assert artifact.expression_digest == expression.content_digest

    # Spans
    assert slice_item.source_range is not None
    assert artifact.source_map is not None
    assert artifact.source_map.document_id == document.document_id

    # Family / profile / property / view / notation
    assert slice_item.family.namespace.value == "family"
    assert slice_item.profile.namespace.value == "profile"
    assert slice_item.property.value == "validity"
    assert slice_item.view.namespace.value == "view"
    assert slice_item.notation.namespace.value == "notation"

    # Features, assumptions, unsupported extensions, status, content identity
    assert slice_item.features == ("classical", "propositional")
    assert slice_item.assumption_ids == ("asm:closed-world",)
    assert slice_item.unsupported_extensions == ()
    assert slice_item.status is DomainSliceStatus.ADMITTED
    assert len(slice_item.content_digest) == 64
    assert len(artifact.content_digest) == 64
    assert len(artifact.lineage_digest) == 64

    for field_name in REQUIRED_ARTIFACT_BINDINGS:
        if field_name == "source_map":
            assert "source_map" in report.bound_fields
        else:
            assert field_name in report.bound_fields


def test_admit_slice_from_typed_expression_binds_source_and_expression() -> None:
    document = _document("P & Q")
    expression = _expression()
    slice_item = DomainLogicSliceV2.from_typed_expression(
        expression,
        slice_id="slice:from-expr",
        domain="crypto_ir",
        document_id=document.document_id,
        source_digest=document.content_digest,
        property=property_id("safety"),
        view=view_id("source"),
        notation=notation_id("canonical_text"),
        features=("propositional",),
        assumption_ids=("asm:perfect-crypto",),
        source_range=SourceRange(start=0, end=1),
    )
    admitted = admit_slice_new_write(
        slice_item, document=document, expression=expression
    )
    assert admitted.domain == "crypto_ir"
    assert admitted.expression_id == expression.expression_id
    assert admitted.source_digest == document.content_digest
    assert admitted.property.value == "safety"
    assert admitted.features == ("propositional",)
    assert admitted.assumption_ids == ("asm:perfect-crypto",)
    assert admitted.source_range is not None


def test_admitted_generations_are_v3_and_v2_only() -> None:
    assert FORMALIZATION_ARTIFACT_V3_INTERFACE == "FormalizationArtifact@3"
    assert DOMAIN_LOGIC_SLICE_V2_INTERFACE == "DomainLogicSlice@2"
    artifact = _bound_artifact()
    slice_item = artifact.slices[0]
    assert artifact.interface == "FormalizationArtifact@3"
    assert slice_item.interface == "DomainLogicSlice@2"
    assert {artifact.interface, slice_item.interface} == ADMITTED_GENERATIONS


# ---------------------------------------------------------------------------
# Fail-closed: incomplete or illegal new writes
# ---------------------------------------------------------------------------


def test_admitted_slice_rejects_missing_source_digest() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(
        (DomainSliceAdmissionError, ArtifactV3Error, SyntaxContractError)
    ):
        _bound_slice(
            document,
            expression,
            source_digest="",
        )


def test_admitted_slice_rejects_unsupported_extensions() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(DomainSliceAdmissionError, match="unsupported"):
        _bound_slice(
            document,
            expression,
            unsupported_extensions=("modal.kripke/v1",),
        )


def test_rejected_slice_cannot_admit_new_write() -> None:
    document = _document()
    expression = _expression()
    rejected = _bound_slice(
        document,
        expression,
        status=DomainSliceStatus.REJECTED,
    )
    with pytest.raises(DomainSliceAdmissionError, match="not admitted"):
        admit_slice_new_write(rejected, document=document, expression=expression)


def test_ok_formalization_rejects_only_rejected_slices() -> None:
    document = _document()
    expression = _expression()
    rejected = _bound_slice(
        document,
        expression,
        status=DomainSliceStatus.REJECTED,
    )
    with pytest.raises(ArtifactV3Error, match="admitted"):
        _bound_artifact(document, expression, slices=(rejected,))


def test_admit_new_write_rejects_non_admitted_artifact() -> None:
    document = _document()
    expression = _expression()
    rejected = _bound_slice(
        document,
        expression,
        status=DomainSliceStatus.REJECTED,
    )
    artifact = _bound_artifact(
        document,
        expression,
        status=FormalizationArtifactStatus.FAILED,
        slices=(rejected,),
    )
    with pytest.raises(DomainSliceAdmissionError):
        admit_new_write(artifact, document=document, expression=expression)


def test_slice_lineage_mismatch_fails_closed() -> None:
    document = _document("P")
    other = _document("Q", document_id="doc:other")
    expression = _expression()
    bad_slice = _bound_slice(other, expression)
    with pytest.raises(ArtifactV3LineageError, match="document_id"):
        _bound_artifact(document, expression, slices=(bad_slice,))


def test_source_digest_mismatch_on_validate() -> None:
    document = _document("P")
    other = _document("Q", document_id=document.document_id)
    expression = _expression()
    artifact = _bound_artifact(document, expression)
    with pytest.raises(ArtifactV3LineageError, match="source_digest"):
        admit_new_write(artifact, document=other, expression=expression)


def test_expression_digest_mismatch_on_validate() -> None:
    document = _document()
    expression = _expression("expr:a")
    other = _expression("expr:b")
    artifact = _bound_artifact(document, expression)
    with pytest.raises(ArtifactV3LineageError, match="expression"):
        admit_new_write(artifact, document=document, expression=other)


def test_free_form_routing_metadata_rejected() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(ArtifactV3Error, match="free-form routing"):
        _bound_slice(
            document,
            expression,
            metadata={"payload": {"raw": "true"}},
        )
    with pytest.raises(ArtifactV3Error, match="free-form routing"):
        _bound_artifact(
            document,
            expression,
            metadata={"raw_formula": "P"},
        )


def test_cross_namespace_family_rejected() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(ArtifactV3Error, match="namespace"):
        _bound_slice(
            document,
            expression,
            family=provider_id("z3"),
        )


def test_wrong_content_digest_rejected() -> None:
    artifact = _bound_artifact()
    payload = artifact.to_dict()
    payload["content_digest"] = "0" * 64
    with pytest.raises(ArtifactV3Error, match="content_digest"):
        FormalizationArtifactV3.from_dict(payload)


def test_wrong_slice_content_digest_rejected() -> None:
    slice_item = _bound_slice()
    payload = slice_item.to_dict()
    payload["content_digest"] = "f" * 64
    with pytest.raises(ArtifactV3Error, match="content_digest"):
        DomainLogicSliceV2.from_dict(payload)


def test_source_map_document_mismatch_rejected() -> None:
    document = _document()
    expression = _expression()
    bad_map = SourceMap(
        map_id="map:bad",
        document_id="doc:not-the-artifact",
        entries=(
            SourceMapEntry(
                entry_id="map:entry:bad",
                range=SourceRange(start=0, end=1),
                role="identifier",
            ),
        ),
    )
    with pytest.raises(ArtifactV3LineageError, match="SourceMap"):
        _bound_artifact(document, expression, source_map=bad_map)


def test_unsupported_slice_requires_extension_list() -> None:
    document = _document()
    expression = _expression()
    with pytest.raises(DomainSliceAdmissionError, match="unsupported_extensions"):
        _bound_slice(
            document,
            expression,
            status=DomainSliceStatus.UNSUPPORTED,
            unsupported_extensions=(),
        )


def test_legacy_compiler_artifact_type_is_not_admitted_write_path() -> None:
    """Only FormalizationArtifactV3 instances pass admit_new_write."""

    class LegacyFormalizationArtifact:
        """Stand-in for compiler FormalizationArtifact@1."""

        interface = "FormalizationArtifact@1"

    with pytest.raises(NewWriteAdmissionError, match="FormalizationArtifact@3"):
        admit_new_write(LegacyFormalizationArtifact())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Round-trip stability under admission
# ---------------------------------------------------------------------------


def test_admitted_write_round_trip_preserves_bindings() -> None:
    document = _document()
    expression = _expression()
    artifact = _bound_artifact(document, expression)
    restored = FormalizationArtifactV3.from_dict(artifact.to_dict())
    report = admit_new_write(restored, document=document, expression=expression)
    assert report.artifact.content_digest == artifact.content_digest
    assert report.artifact.lineage_digest == artifact.lineage_digest
    assert report.admitted_slices[0].content_digest == artifact.slices[0].content_digest
    assert report.admitted_slices[0].features == artifact.slices[0].features
    assert report.admitted_slices[0].assumption_ids == artifact.slices[0].assumption_ids


def test_required_binding_inventory_is_exhaustive() -> None:
    """Guard the LPC-040 acceptance field list against silent shrinkage."""

    expected_slice = {
        "document_id",
        "source_digest",
        "expression_id",
        "expression_digest",
        "family",
        "profile",
        "property",
        "view",
        "notation",
        "features",
        "assumption_ids",
        "unsupported_extensions",
        "status",
        "content_digest",
        "source_range",
    }
    expected_artifact = {
        "document_id",
        "source_digest",
        "expression_id",
        "expression_digest",
        "family",
        "profile",
        "view",
        "notation",
        "assumption_ids",
        "status",
        "content_digest",
        "lineage_digest",
        "slices",
        "source_map",
    }
    assert set(REQUIRED_SLICE_BINDINGS) == expected_slice
    assert set(REQUIRED_ARTIFACT_BINDINGS) == expected_artifact


def test_inspect_slice_bindings_covers_admitted_fields() -> None:
    slice_item = _bound_slice()
    bound = inspect_slice_bindings(slice_item)
    for field_name in REQUIRED_SLICE_BINDINGS:
        assert field_name in bound
