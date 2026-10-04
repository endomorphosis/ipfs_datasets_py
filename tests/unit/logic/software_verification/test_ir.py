"""Contracts for the shared software-verification IR and property vocabulary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.families.models import BoundednessKind
from ipfs_datasets_py.logic.ir_core.artifacts import Artifact, ArtifactRole
from ipfs_datasets_py.logic.ir_core.diagnostics import DiagnosticCode
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.ir import (
    DeclarationKind,
    IRValidationError,
    SoftwareVerificationIR,
    VerificationBound,
    VerificationDeclaration,
    unsupported_construct_diagnostic,
)
from ipfs_datasets_py.logic.software_verification.properties import (
    PROPERTY_VOCABULARY,
    AssumptionKind,
    PropertyKind,
    PropertyValidationError,
    VerificationAssumption,
    VerificationProperty,
)


def _source() -> SourceRef:
    return SourceRef(
        ref_id="source:counter",
        source_uri="file:///src/counter.py",
        source_id="counter.py",
        source_revision="git:0123456789abcdef",
        content_sha256="a" * 64,
    )


def _span() -> SourceSpan:
    return SourceSpan(
        span_id="span:increment",
        source_ref_id="source:counter",
        start_byte=8,
        end_byte=52,
        start_line=2,
        start_column=1,
        end_line=4,
        end_column=14,
    )


def _document(
    *,
    observations: dict[str, object] | None = None,
    diagnostics: tuple[object, ...] = (),
) -> SoftwareVerificationIR:
    declaration = VerificationDeclaration(
        declaration_id="decl:increment",
        kind=DeclarationKind.FUNCTION,
        name="increment",
        payload={
            "parameters": [{"name": "value", "type": "integer"}],
            "returns": "integer",
        },
        source_ref_ids=("source:counter",),
        span_ids=("span:increment",),
        extensions={"example.types.signed": True},
    )
    assumption = VerificationAssumption(
        assumption_id="assumption:integer-model",
        kind=AssumptionKind.MODELING,
        statement="Integers use mathematical, unbounded semantics.",
        expression={"model": "mathematical_integer"},
        subject_ids=(declaration.declaration_id,),
        span_ids=("span:increment",),
    )
    bound = VerificationBound(
        bound_id="bound:inputs",
        kind=BoundednessKind.FINITE_DOMAIN,
        limits={"domain_size": 256},
        source_ref_ids=("source:counter",),
    )
    prop = VerificationProperty(
        property_id="property:monotonic",
        kind=PropertyKind.THEOREM,
        statement="The result is greater than the input.",
        expression={
            "operator": "greater_than",
            "operands": [{"result": "increment"}, {"parameter": "value"}],
        },
        logic_family="first_order",
        subject_ids=(declaration.declaration_id,),
        assumption_ids=(assumption.assumption_id,),
        bound_ids=(bound.bound_id,),
        source_ref_ids=("source:counter",),
        span_ids=("span:increment",),
    )
    artifact = Artifact(
        artifact_id="artifact:source",
        role=ArtifactRole.INPUT,
        content_sha256="a" * 64,
        size=52,
        path="src/counter.py",
        media_type="text/x-python",
    )
    return SoftwareVerificationIR(
        sources=(_source(),),
        spans=(_span(),),
        declarations=(declaration,),
        assumptions=(assumption,),
        bounds=(bound,),
        properties=(prop,),
        diagnostics=diagnostics,  # type: ignore[arg-type]
        artifacts=(artifact,),
        metadata={"language": "python"},
        extensions={"example.analysis.mode": "strict"},
        observations=observations or {},
    )


def test_property_vocabulary_matches_the_canonical_taxonomy() -> None:
    assert set(PROPERTY_VOCABULARY) == {item.value for item in PropertyKind}
    assert {
        "authentication",
        "authorization",
        "contract",
        "data_race_freedom",
        "heap_safety",
        "hyperproperty",
        "invariant",
        "liveness",
        "noninterference",
        "reachability",
        "refinement",
        "safety",
        "satisfiability",
        "secrecy",
        "termination",
        "theorem",
        "trace_conformance",
        "validity",
    } == set(PROPERTY_VOCABULARY)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: VerificationProperty(
            "property:unmapped", PropertyKind.SAFETY, "Always safe."
        ),
        lambda: VerificationAssumption(
            "assumption:unmapped", "The environment is fair."
        ),
    ],
)
def test_every_property_and_assumption_must_be_source_mapped(factory: object) -> None:
    with pytest.raises(PropertyValidationError, match="must be source mapped"):
        factory()  # type: ignore[operator]


def test_document_is_deeply_immutable_and_defensively_copied() -> None:
    payload = {"nested": {"names": ["original"]}}
    declaration = VerificationDeclaration(
        "decl:immutable",
        DeclarationKind.CONSTANT,
        "immutable",
        payload,
        source_ref_ids=("source:counter",),
    )
    payload["nested"]["names"].append("mutated")
    document = SoftwareVerificationIR(
        sources=[_source()],  # type: ignore[arg-type]
        declarations=[declaration],  # type: ignore[arg-type]
        observations={"timing": {"elapsed_ms": 10}},
    )

    assert declaration.payload["nested"]["names"] == ("original",)
    assert document.sources == (_source(),)
    assert document.declarations == (declaration,)
    assert document.observations["timing"]["elapsed_ms"] == 10
    with pytest.raises(TypeError):
        declaration.payload["new"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        document.observations["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        document.document_id = "changed"  # type: ignore[misc]


def test_canonical_identity_excludes_observational_output() -> None:
    first = _document(
        observations={
            "started_at": "2026-07-29T00:00:00Z",
            "duration_ms": 5,
            "host": "runner-a",
        }
    )
    second = _document(
        observations={
            "started_at": "2030-01-01T00:00:00Z",
            "duration_ms": 900,
            "host": "runner-b",
            "resource_usage": {"max_memory_bytes": 4096},
        }
    )

    assert first.document_id == second.document_id
    assert first.identity == second.identity
    assert first.semantic_dict() == second.semantic_dict()
    assert first.to_dict()["observations"] != second.to_dict()["observations"]
    assert first.canonical_bytes() != second.canonical_bytes()
    assert "observations" not in first.semantic_dict()
    assert "runner-a" not in first.semantic_bytes().decode()


def test_semantic_changes_change_identity_but_input_order_does_not() -> None:
    document = _document()
    reordered = replace(
        document,
        sources=tuple(reversed(document.sources)),
        declarations=tuple(reversed(document.declarations)),
        assumptions=tuple(reversed(document.assumptions)),
        properties=tuple(reversed(document.properties)),
    )
    changed = replace(
        document,
        properties=(
            replace(
                document.properties[0],
                statement="The result is at least the input.",
            ),
        ),
        document_id="",
    )

    assert reordered.document_id == document.document_id
    assert changed.document_id != document.document_id


@pytest.mark.parametrize(
    "factory",
    [
        lambda: VerificationDeclaration(
            "decl:bad-extension",
            DeclarationKind.CONSTANT,
            "constant",
            source_ref_ids=("source:counter",),
            extensions={"unqualified": True},
        ),
        lambda: VerificationProperty(
            "property:bad-extension",
            PropertyKind.SAFETY,
            "Safe.",
            source_ref_ids=("source:counter",),
            extensions={"unqualified": True},
        ),
        lambda: SoftwareVerificationIR(
            sources=(_source(),),
            extensions={"unqualified": True},
        ),
    ],
)
def test_extensions_must_be_namespaced(factory: object) -> None:
    with pytest.raises((IRValidationError, PropertyValidationError), match="namespaced"):
        factory()  # type: ignore[operator]


def test_top_level_metadata_rejects_observational_output() -> None:
    with pytest.raises(IRValidationError, match="put runtime output in observations"):
        SoftwareVerificationIR(
            sources=(_source(),),
            metadata={"analysis": {"duration_ms": 8}},
        )


@pytest.mark.parametrize(
    ("kind", "limits", "match"),
    [
        (BoundednessKind.STEP_BOUNDED, {}, "must not be empty"),
        (BoundednessKind.UNBOUNDED, {"max_steps": 10}, "must be empty"),
        (BoundednessKind.RESOURCE_BOUNDED, {"timeout_ms": float("inf")}, "finite"),
        (BoundednessKind.RESOURCE_BOUNDED, {"timeout_ms": -1}, "non-negative"),
    ],
)
def test_bounds_fail_closed_on_contradictory_or_invalid_limits(
    kind: BoundednessKind,
    limits: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(IRValidationError, match=match):
        VerificationBound(
            bound_id="bound:invalid",
            kind=kind,
            limits=limits,
            source_ref_ids=("source:counter",),
        )


def test_source_and_semantic_cross_references_fail_closed() -> None:
    document = _document()
    dangling_source = replace(
        document.properties[0],
        source_ref_ids=("source:missing",),
    )
    with pytest.raises(IRValidationError, match="unknown ids"):
        replace(document, properties=(dangling_source,), document_id="")

    dangling_assumption = replace(
        document.properties[0],
        assumption_ids=("assumption:missing",),
    )
    with pytest.raises(IRValidationError, match="unknown ids"):
        replace(document, properties=(dangling_assumption,), document_id="")

    mismatched_span = replace(
        document.properties[0],
        source_ref_ids=("source:other",),
    )
    other_source = replace(
        document.sources[0],
        ref_id="source:other",
        source_id="other.py",
        content_sha256="b" * 64,
    )
    with pytest.raises(IRValidationError, match="unlisted sources"):
        replace(
            document,
            sources=(*document.sources, other_source),
            properties=(mismatched_span,),
            document_id="",
        )


def test_unsupported_construct_survives_as_structured_diagnostic() -> None:
    diagnostic = unsupported_construct_diagnostic(
        construct="unbounded dynamic allocation",
        subject_ids=("decl:increment",),
        source_ref_ids=("source:counter",),
        span_ids=("span:increment",),
        field_path="/declarations/0/payload/allocation",
        remediation="Use a heap-aware backend.",
    )
    document = _document(diagnostics=(diagnostic,))
    round_trip = SoftwareVerificationIR.from_json(document.to_json())

    assert round_trip == document
    assert len(round_trip.diagnostics) == 1
    retained = round_trip.diagnostics[0]
    assert retained.code == DiagnosticCode.UNSUPPORTED_FEATURE.value
    assert retained.location.metadata["construct"] == "unbounded dynamic allocation"
    assert retained.location.metadata["retained"] is True
    assert retained.location.subject_ids == ("decl:increment",)


def test_document_round_trip_preserves_artifacts_bounds_and_identity() -> None:
    document = _document(observations={"elapsed_ms": 12})
    decoded = SoftwareVerificationIR.from_dict(document.to_dict())

    assert decoded == document
    assert decoded.document_id == document.document_id
    assert decoded.bounds[0].kind is BoundednessKind.FINITE_DOMAIN
    assert decoded.artifacts[0].role is ArtifactRole.INPUT
    assert decoded.to_json() == document.to_json()


def test_supplied_identity_must_match_semantic_content() -> None:
    document = _document()
    payload = document.to_dict()
    payload["document_id"] = "bafkreiinvalid"

    with pytest.raises(IRValidationError, match="does not match"):
        SoftwareVerificationIR.from_dict(payload)


def test_duplicate_and_cross_category_identifiers_are_rejected() -> None:
    document = _document()
    with pytest.raises(IRValidationError, match="duplicate declaration"):
        replace(
            document,
            declarations=(document.declarations[0], document.declarations[0]),
            document_id="",
        )

    conflicting_assumption = replace(
        document.assumptions[0],
        assumption_id=document.declarations[0].declaration_id,
    )
    with pytest.raises(IRValidationError, match="globally unique"):
        replace(
            document,
            assumptions=(conflicting_assumption,),
            document_id="",
        )
