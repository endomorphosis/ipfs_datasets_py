"""LPC-041: Legal domain adapter conformance (TDFOL, DCEC, frame logic).

Acceptance:

* Adapter declares source domain, view, family/profile, property, notation,
  preserved/lost semantics, assumptions, unsupported constructs, proof-safety,
  and counterexample-safety.
* TDFOL, DCEC, and frame logic stay distinct.
* No silent mapping of TDFOL → FOL, DCEC → generic deontic, or frame logic →
  object framing / graph-projection family.

Durable note:
``data/agent_supervisor/logic_platform_canonicalization/notes/legal_domain_adapter.md``

Production adapter role (inventory alias ``legal_ir.domain_slice``):
``LegalLogicSlice@2`` in ``legal_ir/logic_slice_v2.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest

from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    LogicObligationV2,
    RequestAuthorityCeiling,
    RequestBounds,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    encoding_id,
    evidence_id,
    notation_id,
    property_id,
    view_id,
)
from ipfs_datasets_py.logic.families.profiles import (
    COMPOSITION_REQUIRED_FAMILY_IDS,
    OPAQUE_REPLACEMENT_FAMILY_STRINGS,
    build_dcec_composition,
    build_tdfol_composition,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    DOMAIN_LOGIC_SLICE_V2_INTERFACE,
    DomainLogicSliceV2,
    DomainSliceStatus,
)
from ipfs_datasets_py.logic.legal_ir.logic_slice_v2 import (
    LEGAL_DEFERRED_OVERLAY_FAMILIES,
    LEGAL_IR_DOMAIN_ID,
    LEGAL_LOGIC_SLICE_V2_INTERFACE,
    LEGAL_NEVER_FAMILY_VIEW_ROLES,
    GraphProjectionAsFamilyError,
    LegalAuthorityRejectedError,
    LegalAuthorityRole,
    LegalLogicSliceConnector,
    LegalLogicSliceError,
    LegalSliceClaim,
    LegalSliceKind,
    LegalSourceKind,
    build_core_legal_claims,
    connect_legal_base_slices,
    connect_legal_claim,
    reject_graph_projection_as_family,
)
from ipfs_datasets_py.logic.legal_ir.typed_adapter import (
    LEGAL_LOGIC_ROUTE_CATALOG,
    RouteDisposition,
    RouteNamespace,
    resolve_legal_route,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_predicate
from ipfs_datasets_py.logic.syntax_core.contracts import SourceDocument
from ipfs_datasets_py.logic.syntax_core.signatures import propositional_signature


# ---------------------------------------------------------------------------
# Paths and declaration inventory
# ---------------------------------------------------------------------------


def _legal_domain_adapter_note() -> Path:
    note_relative = Path(
        "data/agent_supervisor/logic_platform_canonicalization/notes/"
        "legal_domain_adapter.md"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / note_relative
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[5] / note_relative


# LPC-041 acceptance: every adapter must declare these fields.
REQUIRED_ADAPTER_DECLARATIONS: Final[tuple[str, ...]] = (
    "source domain",
    "view",
    "family / profile",
    "property",
    "notation",
    "preserved semantics",
    "lost semantics",
    "assumptions",
    "unsupported constructs",
    "proof-safety",
    "counterexample-safety",
)

# Foundation sections that must appear in the durable note.
REQUIRED_FOUNDATION_SECTIONS: Final[tuple[str, ...]] = (
    "TDFOL",
    "DCEC",
    "Frame logic",
)

# Required DomainLogicSlice@2 bindings (LPC-040 / LPC-041).
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
    "domain",
)

FOUNDATION_ROUTE_LABELS: Final[tuple[str, ...]] = (
    "tdfol",
    "dcec",
    "event_calculus",
    "frame_logic",
)

FORBIDDEN_TDFOL_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "first_order",
        "fol",
        "temporal_fol",
        "tfol",
        "first_order_temporal",
    }
)
FORBIDDEN_DCEC_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "deontic",
        "first_order",
        "fol",
        "conditional_normative",
    }
)
FORBIDDEN_FRAME_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "graph_projection",
        "knowledge_graphs",
        "object_framing",
        "object",
        "first_order",
        "deontic",
    }
)


def _identity_value(value: Any) -> str:
    if isinstance(value, LogicIdentity):
        return value.value
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _build_typed_expression(
    *,
    expression_id: str,
    family: str,
    profile: str,
    predicate: str = "P",
) -> TypedExpression:
    signature = propositional_signature(
        f"sig:{expression_id}",
        (predicate,),
        family=family,
        profile=profile,
    )
    return TypedExpression(
        expression_id=expression_id,
        root=mk_predicate(f"n:{expression_id}", predicate),
        signature=signature,
        family=family,
        profile=profile,
    )


def _domain_slice_for_route(
    label: str,
    *,
    property_name: str,
    view_name: str | None = None,
    notation_name: str = "canonical_text",
    assumption_ids: tuple[str, ...] = (),
    features: tuple[str, ...] = (),
) -> tuple[DomainLogicSliceV2, SourceDocument, TypedExpression]:
    route = resolve_legal_route(label)
    assert route.family_id, f"route {label!r} must bind a semantic family"
    family = route.family_id
    profile = route.profile_id or family
    document = SourceDocument.from_text(
        f"doc:legal:domain-slice:{label}",
        f"legal foundation obligation for {label}",
        encoding="utf-8",
    )
    expression = _build_typed_expression(
        expression_id=f"expr:legal:{label}",
        family=family,
        profile=profile,
        predicate=f"Legal_{label.replace('.', '_')}",
    )
    domain_slice = DomainLogicSliceV2.from_typed_expression(
        expression,
        slice_id=f"slice:legal:foundation:{label}",
        domain=LEGAL_IR_DOMAIN_ID,
        document_id=document.document_id,
        source_digest=document.content_digest,
        property=property_id(property_name),
        view=view_id(view_name or route.view_name),
        notation=notation_id(notation_name),
        status=DomainSliceStatus.ADMITTED,
        features=features or (family, "legal_ir", f"route.{label}"),
        assumption_ids=assumption_ids
        or (
            f"axis:foundation:{family}",
            f"axis:profile:{profile}",
            "axis:authority:candidate",
        ),
    )
    return domain_slice, document, expression


# ---------------------------------------------------------------------------
# Durable note declarations
# ---------------------------------------------------------------------------


def test_legal_domain_adapter_note_exists_and_declares_required_fields() -> None:
    note_path = _legal_domain_adapter_note()
    assert note_path.is_file(), f"missing LPC-041 note at {note_path}"
    text = note_path.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "lpc-041" in lowered
    assert "legal_ir" in text
    assert "DomainLogicSlice@2" in text
    assert "LegalLogicSlice@2" in text

    for section in REQUIRED_FOUNDATION_SECTIONS:
        assert section in text, f"note missing foundation section {section!r}"

    for declaration in REQUIRED_ADAPTER_DECLARATIONS:
        assert declaration in lowered, (
            f"note must declare {declaration!r} for legal domain adapter conformance"
        )

    # Non-collapse policy language must be present.
    assert "do not map" in lowered or "must not silently" in lowered
    assert "first_order" in text or "FOL" in text
    assert "object framing" in lowered or "object_framing" in lowered


def test_note_declares_foundation_tables_with_namespace_axes() -> None:
    text = _legal_domain_adapter_note().read_text(encoding="utf-8")
    # Each foundation declaration block must name the five namespace axes.
    for marker in (
        "## 1. TDFOL adapter declaration",
        "## 2. DCEC / event-calculus adapter declaration",
        "## 3. Frame logic adapter declaration",
    ):
        assert marker in text
        start = text.index(marker)
        # Bound the section to the next top-level foundation/base heading when present.
        rest = text[start + len(marker) :]
        next_heading = rest.find("\n## ")
        section = text[start : start + len(marker) + (next_heading if next_heading >= 0 else len(rest))]
        chunk = section.lower()
        for axis in (
            "source domain",
            "view",
            "family / profile",
            "property",
            "notation",
            "preserved semantics",
            "lost semantics",
            "assumptions",
            "unsupported constructs",
            "proof-safety",
            "counterexample-safety",
        ):
            assert axis in chunk, f"{marker} missing declaration {axis!r}"


# ---------------------------------------------------------------------------
# Interface / domain identity
# ---------------------------------------------------------------------------


def test_legal_adapter_domain_and_interface_identity() -> None:
    connector = LegalLogicSliceConnector()
    assert connector.interface == LEGAL_LOGIC_SLICE_V2_INTERFACE
    assert connector.interface == "LegalLogicSlice@2"
    assert connector.domain_id == LEGAL_IR_DOMAIN_ID
    assert LEGAL_IR_DOMAIN_ID == "legal_ir"


def test_route_catalog_includes_tdfol_dcec_surface_and_frame_logic() -> None:
    by_family = {route.family_id for route in LEGAL_LOGIC_ROUTE_CATALOG if route.family_id}
    assert "tdfol" in by_family
    assert "event_calculus" in by_family
    assert "frame_logic" in by_family
    assert "deontic" in by_family
    assert "first_order" in by_family

    labels = {
        alias
        for route in LEGAL_LOGIC_ROUTE_CATALOG
        for alias in (route.view_name, *route.aliases)
    }
    for label in FOUNDATION_ROUTE_LABELS:
        assert label in labels


# ---------------------------------------------------------------------------
# Foundation non-collapse
# ---------------------------------------------------------------------------


def test_tdfol_dcec_and_frame_logic_are_pairwise_distinct() -> None:
    tdfol = resolve_legal_route("tdfol")
    dcec_surface = resolve_legal_route("dcec")
    event = resolve_legal_route("event_calculus")
    frame = resolve_legal_route("frame_logic")

    assert tdfol.family_id == "tdfol"
    assert tdfol.profile_id == "temporal_first_order"
    assert frame.family_id == "frame_logic"
    # DCEC event-surface alias routes with event_calculus (not generic deontic).
    assert dcec_surface.family_id == "event_calculus"
    assert event.family_id == "event_calculus"
    assert dcec_surface.route_id == event.route_id

    families = {
        tdfol.family_id,
        dcec_surface.family_id,
        frame.family_id,
    }
    assert families == {"tdfol", "event_calculus", "frame_logic"}
    assert len(families) == 3


def test_tdfol_does_not_map_to_generic_fol() -> None:
    route = resolve_legal_route("tdfol")
    assert route.family_id == "tdfol"
    assert route.family_id not in FORBIDDEN_TDFOL_TARGETS
    assert route.profile_id == "temporal_first_order"
    # Opaque temporal-FOL strings are profiles/compositions, not family ids.
    assert "temporal_first_order" in OPAQUE_REPLACEMENT_FAMILY_STRINGS
    assert "tdfol" in COMPOSITION_REQUIRED_FAMILY_IDS
    composition = build_tdfol_composition()
    assert composition.family_id == "tdfol"
    assert composition.metadata is not None


def test_dcec_does_not_map_to_generic_deontic_or_fol() -> None:
    route = resolve_legal_route("dcec")
    assert route.family_id not in FORBIDDEN_DCEC_TARGETS
    assert route.family_id == "event_calculus"
    # Catalog composition retains canonical dcec identity separately.
    assert "dcec" in COMPOSITION_REQUIRED_FAMILY_IDS
    composition = build_dcec_composition()
    assert composition.family_id == "dcec"
    assert composition.metadata is not None
    components = set(composition.metadata.component_family_ids)
    assert {"deontic", "event_calculus", "modal"} <= components
    # Composition links deontic as a *component*, not a silent rewrite of dcec.
    assert composition.family_id != "deontic"
    assert composition.family_id != "first_order"


def test_frame_logic_does_not_map_to_object_framing_or_graph_projection() -> None:
    route = resolve_legal_route("frame_logic")
    assert route.family_id == "frame_logic"
    assert route.family_id not in FORBIDDEN_FRAME_TARGETS
    assert route.namespace is not RouteNamespace.VIEW_ROLE
    assert route.is_operation_role is False
    # Graph projection remains a separate operation role.
    graph = resolve_legal_route("graph_projection")
    assert graph.namespace is RouteNamespace.VIEW_ROLE
    assert graph.view_role_id == "graph_projection"
    assert graph.family_id == ""
    assert graph.family_id != route.family_id


@pytest.mark.parametrize(
    "label,forbidden",
    [
        ("tdfol", FORBIDDEN_TDFOL_TARGETS),
        ("TDFOL", FORBIDDEN_TDFOL_TARGETS),
        ("temporal_first_order", FORBIDDEN_TDFOL_TARGETS),
        ("dcec", FORBIDDEN_DCEC_TARGETS),
        ("cec", FORBIDDEN_DCEC_TARGETS),
        ("event_calculus", FORBIDDEN_DCEC_TARGETS),
        ("frame_logic", FORBIDDEN_FRAME_TARGETS),
        ("flogic", FORBIDDEN_FRAME_TARGETS),
        ("modal.frame_logic", FORBIDDEN_FRAME_TARGETS),
    ],
)
def test_foundation_aliases_preserve_non_collapse(
    label: str, forbidden: frozenset[str]
) -> None:
    route = resolve_legal_route(label)
    assert route.family_id
    assert route.family_id not in forbidden
    assert route.disposition in {
        RouteDisposition.TYPED,
        RouteDisposition.NATIVE,
        RouteDisposition.BOUNDED,
        RouteDisposition.ADVISORY,
    }


# ---------------------------------------------------------------------------
# DomainLogicSlice@2 emission for foundation routes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,property_name,expected_family",
    [
        ("tdfol", "validity", "tdfol"),
        ("dcec", "reachability", "event_calculus"),
        ("event_calculus", "reachability", "event_calculus"),
        ("frame_logic", "frame", "frame_logic"),
    ],
)
def test_foundation_routes_emit_admitted_domain_logic_slice(
    label: str, property_name: str, expected_family: str
) -> None:
    domain_slice, document, expression = _domain_slice_for_route(
        label,
        property_name=property_name,
    )
    assert domain_slice.interface == DOMAIN_LOGIC_SLICE_V2_INTERFACE
    assert domain_slice.domain == LEGAL_IR_DOMAIN_ID
    assert domain_slice.is_admitted
    domain_slice.require_admitted()
    domain_slice.validate_against(document=document, expression=expression)

    assert _identity_value(domain_slice.family) == expected_family
    assert _identity_value(domain_slice.property)
    assert _identity_value(domain_slice.view)
    assert _identity_value(domain_slice.notation) == "canonical_text"
    assert domain_slice.assumption_ids
    assert domain_slice.unsupported_extensions == ()
    assert domain_slice.status is DomainSliceStatus.ADMITTED
    assert domain_slice.content_digest

    payload = domain_slice.to_dict()
    for field_name in REQUIRED_SLICE_BINDINGS:
        assert field_name in payload, f"missing DomainLogicSlice binding {field_name}"


def test_foundation_domain_slices_have_distinct_families() -> None:
    slices = {
        label: _domain_slice_for_route(
            label,
            property_name=property_name,
        )[0]
        for label, property_name in (
            ("tdfol", "validity"),
            ("dcec", "reachability"),
            ("frame_logic", "frame"),
        )
    }
    families = {_identity_value(item.family) for item in slices.values()}
    assert families == {"tdfol", "event_calculus", "frame_logic"}
    for domain_slice in slices.values():
        assert domain_slice.domain == "legal_ir"
        assert _identity_value(domain_slice.family) not in {
            "graph_projection",
            "object_framing",
        }


# ---------------------------------------------------------------------------
# LegalLogicSlice@2 claim path (base kinds)
# ---------------------------------------------------------------------------


def test_base_legal_claims_emit_domain_slices_with_required_bindings() -> None:
    claims = build_core_legal_claims()
    bundle = connect_legal_base_slices(claims, bundle_id="bundle:lpc041")
    assert len(bundle.slices) >= 4
    for slice_item in bundle.slices:
        assert slice_item.interface == LEGAL_LOGIC_SLICE_V2_INTERFACE
        assert slice_item.is_admitted
        domain_slice = slice_item.to_domain_slice()
        assert domain_slice.domain == LEGAL_IR_DOMAIN_ID
        domain_slice.require_admitted()
        domain_slice.validate_against(
            document=slice_item.document, expression=slice_item.expression
        )
        payload = domain_slice.to_dict()
        for field_name in REQUIRED_SLICE_BINDINGS:
            assert field_name in payload
        # Explicit legal axes (adapter-level assumptions / profiles).
        assert slice_item.deontic_profile.profile_id
        assert slice_item.temporal_model.model_id
        assert slice_item.assumption_ids
        assert slice_item.authority.role is not LegalAuthorityRole.OFFICIAL
        assert slice_item.authority.result_ceiling is not ResultAuthority.THEOREM


def test_event_claim_uses_event_calculus_not_generic_deontic() -> None:
    event_claim = next(
        claim
        for claim in build_core_legal_claims()
        if claim.kind is LegalSliceKind.EVENT
        or str(claim.kind) == LegalSliceKind.EVENT.value
    )
    slice_item = connect_legal_claim(event_claim)
    assert slice_item.family_id == "event_calculus"
    assert slice_item.family_id != "deontic"
    assert slice_item.family_id != "first_order"
    assert slice_item.family_id != "tdfol"
    assert slice_item.family_id != "frame_logic"
    assert _identity_value(slice_item.domain_slice.property) == "reachability"
    assert slice_item.temporal_model.event_order is True


def test_base_norm_remains_deontic_and_distinct_from_foundations() -> None:
    base = connect_legal_claim(build_core_legal_claims()[0])
    assert base.family_id == "deontic"
    assert base.profile_id == "conditional_normative"
    assert base.family_id != "tdfol"
    assert base.family_id != "event_calculus"
    assert base.family_id != "frame_logic"
    assert base.family_id != "first_order"


# ---------------------------------------------------------------------------
# Preservation / loss / unsupported
# ---------------------------------------------------------------------------


def test_foundation_routes_declare_preservation_rules() -> None:
    expected = {
        "tdfol": {
            "quantifier_scope",
            "temporal_anchor",
            "event_order",
            "deontic_force",
        },
        "dcec": {
            "event_identity",
            "fluent_identity",
            "transition_direction",
            "time_anchor",
        },
        "frame_logic": {
            "typed_role",
            "relation_direction",
            "modal_operator",
            "exception_scope",
        },
    }
    for label, rules in expected.items():
        route = resolve_legal_route(label)
        assert rules <= set(route.preservation_rules), (
            f"{label} missing preservation rules: {rules - set(route.preservation_rules)}"
        )


def test_unsupported_operation_roles_never_become_families() -> None:
    connector = LegalLogicSliceConnector()
    for label in sorted(LEGAL_NEVER_FAMILY_VIEW_ROLES):
        with pytest.raises(GraphProjectionAsFamilyError):
            reject_graph_projection_as_family(label)
        with pytest.raises((GraphProjectionAsFamilyError, LegalLogicSliceError)):
            connector.resolve_route(label)


def test_deferred_overlays_are_unsupported_for_base_slices() -> None:
    connector = LegalLogicSliceConnector()
    for family in sorted(LEGAL_DEFERRED_OVERLAY_FAMILIES):
        with pytest.raises(LegalLogicSliceError, match="deferred"):
            connector.resolve_route(family)


# ---------------------------------------------------------------------------
# Proof-safety and counterexample-safety
# ---------------------------------------------------------------------------


def test_proof_safety_rejects_official_and_theorem_authority() -> None:
    from ipfs_datasets_py.logic.legal_ir.logic_slice_v2 import LegalAuthorityBinding

    with pytest.raises(LegalAuthorityRejectedError):
        LegalAuthorityBinding(
            role=LegalAuthorityRole.OFFICIAL,
            result_ceiling=ResultAuthority.THEOREM,
        )
    with pytest.raises(LegalAuthorityRejectedError):
        LegalAuthorityBinding(
            role=LegalAuthorityRole.CANDIDATE,
            result_ceiling=ResultAuthority.THEOREM,
        )


def test_nl_extraction_is_never_proof_authority() -> None:
    claim = LegalSliceClaim(
        claim_id="claim:lpc041:nl",
        kind=LegalSliceKind.BASE_NORM,
        statement="A covered entity shall retain records.",
        formula_id="norm:nl:retain",
        actor="CoveredEntity",
        action="RetainRecords",
        norm_type="obligation",
        jurisdiction="us-federal",
        source_kind=LegalSourceKind.NATURAL_LANGUAGE,
        source_text="A covered entity shall retain records.",
    )
    slice_item = connect_legal_claim(claim)
    assert slice_item.authority.nl_extraction is True
    assert slice_item.authority.role is LegalAuthorityRole.CANDIDATE
    assert slice_item.authority.result_ceiling is ResultAuthority.CANDIDATE
    request = slice_item.to_backend_request(
        request_id="req:lpc041:nl",
        obligation_id="obl:lpc041:nl",
    )
    assert request.authority_ceiling is not RequestAuthorityCeiling.KERNEL


def test_counterexample_safety_binds_request_digests() -> None:
    """Counterexamples must rebind exact source/expression/slice digests."""

    for label, property_name in (
        ("tdfol", "validity"),
        ("dcec", "reachability"),
        ("frame_logic", "frame"),
    ):
        domain_slice, _document, _expression = _domain_slice_for_route(
            label,
            property_name=property_name,
        )
        obligation = LogicObligationV2.from_slice(
            domain_slice,
            obligation_id=f"obl:lpc041:{label}",
            statement=f"foundation obligation {label}",
            encoding=encoding_id("smt_lib2"),
            evidence_kind=evidence_id("model"),
            bounds=RequestBounds.default(),
            authority_ceiling=RequestAuthorityCeiling.CANDIDATE,
        )
        request = BackendRequestV2.from_obligation(
            obligation,
            request_id=f"req:lpc041:{label}",
        )
        # Digest binding for counterexample/replay safety.
        assert request.source_digest == domain_slice.source_digest
        assert request.expression_digest == domain_slice.expression_digest
        assert request.slice_digest == domain_slice.content_digest
        assert obligation.source_digest == domain_slice.source_digest
        assert obligation.expression_digest == domain_slice.expression_digest
        assert obligation.slice_digest == domain_slice.content_digest
        # Authority ceiling stays non-kernel for foundation legal routes.
        assert request.authority_ceiling is not RequestAuthorityCeiling.KERNEL


def test_legal_slice_backend_request_preserves_lineage_digests() -> None:
    slice_item = connect_legal_claim(build_core_legal_claims()[0])
    obligation = slice_item.to_obligation(obligation_id="obl:lpc041:base")
    request = slice_item.to_backend_request(
        request_id="req:lpc041:base",
        obligation_id="obl:lpc041:base",
    )
    assert isinstance(obligation, LogicObligationV2)
    assert isinstance(request, BackendRequestV2)
    assert request.source_digest == slice_item.document.content_digest
    assert request.expression_digest == slice_item.expression.content_digest
    assert request.slice_digest == slice_item.domain_slice.content_digest
    assert request.family.value == slice_item.family_id


# ---------------------------------------------------------------------------
# Route catalog declarations (adapter-level)
# ---------------------------------------------------------------------------


def test_each_typed_route_declares_view_family_and_preservation() -> None:
    typed_routes = [
        route
        for route in LEGAL_LOGIC_ROUTE_CATALOG
        if route.namespace
        in {RouteNamespace.FAMILY, RouteNamespace.PROFILE}
        and route.disposition
        in {
            RouteDisposition.TYPED,
            RouteDisposition.NATIVE,
            RouteDisposition.BOUNDED,
            RouteDisposition.ADVISORY,
        }
    ]
    assert typed_routes
    for route in typed_routes:
        assert route.view_name
        assert route.family_id
        assert route.route_id
        assert route.preservation_rules, (
            f"route {route.route_id} must declare preservation_rules"
        )
        # Result authority ceiling is always explicit.
        assert isinstance(route.result_authority_ceiling, ResultAuthority)


def test_foundation_result_ceilings_are_non_theorem() -> None:
    for label in ("tdfol", "dcec", "frame_logic"):
        route = resolve_legal_route(label)
        assert route.result_authority_ceiling is not ResultAuthority.THEOREM
        assert route.result_authority_ceiling is ResultAuthority.CANDIDATE
