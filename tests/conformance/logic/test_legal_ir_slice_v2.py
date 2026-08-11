"""Conformance: Legal IR base vertical slices (LFP2-025).

Acceptance:

* Deontic profile, temporal model, defeasibility, jurisdiction, priority, and
  authority are explicit on every admitted LegalLogicSlice@2
* Graph projection is not a family
* Base norm, exception, event, and jurisdiction slices connect through
  DomainLogicSlice@2 / FormalizationArtifact@3 typed evidence paths

Interfaces: LegalLogicSlice@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    LogicObligationV2,
    RequestAuthorityCeiling,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.profiles import NormForm, TimeDensity, TraceModel
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    DOMAIN_LOGIC_SLICE_V2_INTERFACE,
    FORMALIZATION_ARTIFACT_V3_INTERFACE,
    DomainLogicSliceV2,
    FormalizationArtifactV3,
)
from ipfs_datasets_py.logic.legal_ir.logic_slice_v2 import (
    LEGAL_EVIDENCE_SUBSET,
    LEGAL_IR_DOMAIN_ID,
    LEGAL_LOGIC_SLICE_MODULE_VERSION,
    LEGAL_LOGIC_SLICE_V2_INTERFACE,
    LEGAL_NEVER_FAMILY_VIEW_ROLES,
    GraphProjectionAsFamilyError,
    LegalAuthorityBinding,
    LegalAuthorityRejectedError,
    LegalAuthorityRole,
    LegalDefeasibilityBinding,
    LegalDeonticProfileBinding,
    LegalJurisdictionBinding,
    LegalLogicSliceBundle,
    LegalLogicSliceConnector,
    LegalLogicSliceError,
    LegalLogicSliceV2,
    LegalPriorityBinding,
    LegalSliceClaim,
    LegalSliceKind,
    LegalSourceKind,
    LegalTemporalModelBinding,
    MissingLegalAxisError,
    build_core_legal_claims,
    connect_legal_base_slices,
    connect_legal_claim,
    is_graph_projection_label,
    legal_logic_slice_connector,
    legal_slice_kind_specs,
    reject_graph_projection_as_family,
)
from ipfs_datasets_py.logic.legal_ir.typed_adapter import (
    RouteNamespace,
)


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    connector = LegalLogicSliceConnector()
    assert connector.interface == LEGAL_LOGIC_SLICE_V2_INTERFACE
    assert LegalLogicSliceConnector.INTERFACE == "LegalLogicSlice@2"
    assert LEGAL_LOGIC_SLICE_V2_INTERFACE == "LegalLogicSlice@2"
    assert connector.version == LEGAL_LOGIC_SLICE_MODULE_VERSION
    assert connector.domain_id == LEGAL_IR_DOMAIN_ID
    wire = connector.to_dict()
    assert wire["interface"] == "LegalLogicSlice@2"
    assert wire["domain_id"] == "legal_ir"
    assert "base_norm" in wire["supported_kinds"]
    assert "exception" in wire["supported_kinds"]
    assert "event" in wire["supported_kinds"]
    assert "jurisdiction" in wire["supported_kinds"]


def test_evidence_subset_covers_required_kinds() -> None:
    required = {
        "norm",
        "policy",
        "exception",
        "priority",
        "event",
        "conflict",
        "jurisdiction",
    }
    assert required.issubset(set(LEGAL_EVIDENCE_SUBSET))


def test_kind_specs_cover_core_slices() -> None:
    specs = legal_slice_kind_specs()
    for kind in (
        LegalSliceKind.BASE_NORM,
        LegalSliceKind.EXCEPTION,
        LegalSliceKind.EVENT,
        LegalSliceKind.JURISDICTION,
    ):
        assert kind in specs
        assert specs[kind].family
        assert specs[kind].profile


# ---------------------------------------------------------------------------
# Graph projection is not a family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "graph_projection",
        "knowledge_graphs",
        "knowledge_graph",
        "neo4j_compat",
        "proof_translation",
        "structural_round_trip",
        "round_trip",
        "decompiler",
        "external_provers",
    ],
)
def test_graph_projection_and_operation_roles_never_families(label: str) -> None:
    assert is_graph_projection_label(label) or label in {
        "proof_translation",
        "structural_round_trip",
        "round_trip",
        "decompiler",
        "external_provers",
    } or label in LEGAL_NEVER_FAMILY_VIEW_ROLES
    with pytest.raises(GraphProjectionAsFamilyError):
        reject_graph_projection_as_family(label)
    connector = LegalLogicSliceConnector()
    with pytest.raises(GraphProjectionAsFamilyError):
        connector.resolve_route(label)


def test_domain_slice_family_rejects_graph_projection() -> None:
    claims = build_core_legal_claims()
    slice_item = connect_legal_claim(claims[0])
    # Admitted family is a real semantic family, never graph_projection.
    assert slice_item.family_id != "graph_projection"
    assert slice_item.family_id in {
        "deontic",
        "event_calculus",
        "authorization",
        "tdfol",
        "frame_logic",
        "first_order",
    }
    assert slice_item.route.is_operation_role is False
    assert slice_item.route.namespace is not RouteNamespace.VIEW_ROLE


# ---------------------------------------------------------------------------
# Explicit axes on every admitted slice
# ---------------------------------------------------------------------------


def test_single_claim_axes_are_explicit() -> None:
    claim = build_core_legal_claims()[0]
    slice_item = connect_legal_claim(claim)

    assert isinstance(slice_item, LegalLogicSliceV2)
    assert slice_item.interface == LEGAL_LOGIC_SLICE_V2_INTERFACE
    assert slice_item.is_admitted
    slice_item.require_admitted()
    slice_item.require_explicit_axes()

    # Deontic profile
    assert isinstance(slice_item.deontic_profile, LegalDeonticProfileBinding)
    assert slice_item.deontic_profile.profile_id
    assert slice_item.deontic_profile.form is not NormForm.NOT_APPLICABLE
    assert slice_item.deontic_profile.exceptions is True
    assert slice_item.deontic_profile.priorities is True

    # Temporal model
    assert isinstance(slice_item.temporal_model, LegalTemporalModelBinding)
    assert slice_item.temporal_model.model_id
    assert slice_item.temporal_model.density is TimeDensity.DISCRETE
    assert slice_item.temporal_model.trace_model is TraceModel.FINITE

    # Defeasibility
    assert isinstance(slice_item.defeasibility, LegalDefeasibilityBinding)
    assert slice_item.defeasibility.enabled is True
    assert "norm:exc:emergency" in slice_item.defeasibility.exception_ids

    # Jurisdiction
    assert isinstance(slice_item.jurisdiction, LegalJurisdictionBinding)
    assert slice_item.jurisdiction.jurisdiction == "us-federal"
    assert slice_item.jurisdiction.authority_id

    # Priority
    assert isinstance(slice_item.priority, LegalPriorityBinding)
    assert slice_item.priority.ordered_ids

    # Authority
    assert isinstance(slice_item.authority, LegalAuthorityBinding)
    assert slice_item.authority.role is not LegalAuthorityRole.OFFICIAL
    assert slice_item.authority.result_ceiling is not ResultAuthority.THEOREM


def test_missing_jurisdiction_fails_for_base_norm() -> None:
    claim = LegalSliceClaim(
        claim_id="claim:no-juris",
        kind=LegalSliceKind.BASE_NORM,
        statement="O(PayTax)",
        formula_id="norm:pay",
        actor="Person",
        action="PayTax",
        norm_type="obligation",
        # jurisdiction omitted
    )
    with pytest.raises(MissingLegalAxisError, match="jurisdiction"):
        connect_legal_claim(claim)


# ---------------------------------------------------------------------------
# Connect base norm, exception, event, jurisdiction
# ---------------------------------------------------------------------------


def test_connect_base_slices_joins_four_core_kinds() -> None:
    claims = build_core_legal_claims()
    bundle = connect_legal_base_slices(claims, bundle_id="bundle:legal:core")

    assert isinstance(bundle, LegalLogicSliceBundle)
    bundle.require_kinds(
        LegalSliceKind.BASE_NORM,
        LegalSliceKind.EXCEPTION,
        LegalSliceKind.EVENT,
        LegalSliceKind.JURISDICTION,
    )

    base = bundle.slice_for(LegalSliceKind.BASE_NORM)
    exc = bundle.slice_for(LegalSliceKind.EXCEPTION)
    event = bundle.slice_for(LegalSliceKind.EVENT)
    juris = bundle.slice_for(LegalSliceKind.JURISDICTION)
    assert base is not None and exc is not None
    assert event is not None and juris is not None

    # Base norm → deontic
    assert base.family_id == "deontic"
    assert base.deontic_profile.profile_id == "conditional_normative"

    # Exception → defeasible deontic profile
    assert exc.family_id == "deontic"
    assert exc.profile_id == "defeasible_normative"
    assert exc.defeasibility.enabled is True
    assert exc.defeasibility.exception_ids

    # Event → event_calculus with explicit temporal model
    assert event.family_id == "event_calculus"
    assert event.temporal_model.event_order is True
    assert event.temporal_model.temporal_anchors

    # Jurisdiction → authorization with explicit jurisdiction + authority
    assert juris.family_id == "authorization"
    assert juris.jurisdiction.jurisdiction == "us-federal"
    assert juris.authority.role is LegalAuthorityRole.BOUNDED
    assert juris.authority.result_ceiling is ResultAuthority.AUTHORIZATION


def test_connect_base_slices_requires_core_kinds() -> None:
    only_norm = [build_core_legal_claims()[0]]
    with pytest.raises(LegalLogicSliceError, match="missing core kinds"):
        connect_legal_base_slices(only_norm)


def test_bundle_formalization_artifact_v3() -> None:
    bundle = connect_legal_base_slices(build_core_legal_claims())
    assert bundle.formalization is not None
    art = bundle.formalization
    assert isinstance(art, FormalizationArtifactV3)
    assert art.interface == FORMALIZATION_ARTIFACT_V3_INTERFACE
    assert art.domain == LEGAL_IR_DOMAIN_ID
    assert len(art.slices) == 4
    for domain_slice in art.slices:
        assert isinstance(domain_slice, DomainLogicSliceV2)
        assert domain_slice.interface == DOMAIN_LOGIC_SLICE_V2_INTERFACE
        assert domain_slice.is_admitted
        assert domain_slice.domain == LEGAL_IR_DOMAIN_ID
        assert domain_slice.source_digest == bundle.document.content_digest
        # Graph projection never appears as family.
        family_value = (
            domain_slice.family.value
            if hasattr(domain_slice.family, "value")
            else str(domain_slice.family)
        )
        assert family_value != "graph_projection"
        assert family_value not in LEGAL_NEVER_FAMILY_VIEW_ROLES


def test_shared_document_lineage_across_slices() -> None:
    bundle = connect_legal_base_slices(
        build_core_legal_claims(),
        document_id="doc:legal:shared",
        source_text="O(FileReport) unless Emergency. Happens(FileReportEvent, t).",
    )
    digests = {s.document.content_digest for s in bundle.slices}
    assert len(digests) == 1
    assert bundle.document.content_digest in digests
    for s in bundle.slices:
        s.domain_slice.validate_against(
            document=bundle.document, expression=s.expression
        )


# ---------------------------------------------------------------------------
# Priority and conflict explicitness
# ---------------------------------------------------------------------------


def test_cross_claim_priority_is_explicit() -> None:
    claims = build_core_legal_claims()
    bundle = connect_legal_base_slices(claims)
    # Exception has priority_rank=1, base has 2 → exception first.
    base = bundle.slice_for(LegalSliceKind.BASE_NORM)
    assert base is not None
    ordered = base.priority.ordered_ids
    assert "norm:exc:emergency" in ordered
    assert "norm:base:file_report" in ordered
    assert ordered.index("norm:exc:emergency") < ordered.index("norm:base:file_report")


def test_priority_slice_requires_ordered_ids() -> None:
    claim = LegalSliceClaim(
        claim_id="claim:prio:empty",
        kind=LegalSliceKind.PRIORITY,
        statement="priority(a, b)",
        formula_id="prio:only",
        jurisdiction="us-federal",
        # no exception_ids → fewer than 2 ordered ids when require_priority_ids
    )
    with pytest.raises(MissingLegalAxisError, match="priority"):
        connect_legal_claim(claim)


# ---------------------------------------------------------------------------
# Authority fail-closed
# ---------------------------------------------------------------------------


def test_nl_extraction_never_theorem_authority() -> None:
    claim = LegalSliceClaim(
        claim_id="claim:nl:1",
        kind=LegalSliceKind.BASE_NORM,
        statement="A person shall file a report with the agency.",
        formula_id="norm:nl",
        actor="Person",
        action="FileReport",
        norm_type="obligation",
        jurisdiction="us-federal",
        source_kind=LegalSourceKind.NATURAL_LANGUAGE,
        source_text="A person shall file a report with the agency.",
    )
    slice_item = connect_legal_claim(claim)
    assert slice_item.authority.nl_extraction is True
    assert slice_item.authority.role is LegalAuthorityRole.CANDIDATE
    assert slice_item.authority.result_ceiling is ResultAuthority.CANDIDATE


def test_official_authority_rejected() -> None:
    with pytest.raises(LegalAuthorityRejectedError):
        LegalAuthorityBinding(
            role=LegalAuthorityRole.OFFICIAL,
            result_ceiling=ResultAuthority.THEOREM,
        )


def test_theorem_ceiling_without_official_rejected() -> None:
    with pytest.raises(LegalAuthorityRejectedError):
        LegalAuthorityBinding(
            role=LegalAuthorityRole.CANDIDATE,
            result_ceiling=ResultAuthority.THEOREM,
        )


# ---------------------------------------------------------------------------
# Backend request lineage
# ---------------------------------------------------------------------------


def test_slice_to_obligation_and_backend_request() -> None:
    slice_item = connect_legal_claim(build_core_legal_claims()[0])
    obligation = slice_item.to_obligation(obligation_id="obl:legal:1")
    assert isinstance(obligation, LogicObligationV2)
    assert obligation.document_id == slice_item.document.document_id
    assert obligation.source_digest == slice_item.document.content_digest
    assert obligation.expression_digest == slice_item.expression.content_digest
    assert obligation.slice_digest == slice_item.domain_slice.content_digest

    request = slice_item.to_backend_request(
        request_id="req:legal:1",
        obligation_id="obl:legal:1",
    )
    assert isinstance(request, BackendRequestV2)
    assert request.source_digest == slice_item.document.content_digest
    assert request.expression_digest == slice_item.expression.content_digest
    assert request.authority_ceiling is not RequestAuthorityCeiling.KERNEL
    assert request.family.value == slice_item.family_id


# ---------------------------------------------------------------------------
# Serialization stability
# ---------------------------------------------------------------------------


def test_slice_to_dict_exposes_explicit_axes() -> None:
    slice_item = connect_legal_claim(build_core_legal_claims()[0])
    wire = slice_item.to_dict()
    assert wire["interface"] == LEGAL_LOGIC_SLICE_V2_INTERFACE
    assert "deontic_profile" in wire
    assert "temporal_model" in wire
    assert "defeasibility" in wire
    assert "jurisdiction" in wire
    assert "priority" in wire
    assert "authority" in wire
    assert wire["domain_slice"]["domain"] == LEGAL_IR_DOMAIN_ID
    assert wire["family_id"] != "graph_projection"


def test_axis_round_trips() -> None:
    deontic = LegalDeonticProfileBinding(
        profile_id="conditional_normative",
        form=NormForm.DYADIC,
        permission="strong",
        exceptions=True,
        priorities=True,
    )
    assert LegalDeonticProfileBinding.from_dict(deontic.to_dict()).profile_id == (
        deontic.profile_id
    )

    temporal = LegalTemporalModelBinding(
        model_id="legal_discrete_finite",
        density=TimeDensity.DISCRETE,
        trace_model=TraceModel.FINITE,
    )
    restored_t = LegalTemporalModelBinding.from_dict(temporal.to_dict())
    assert restored_t.density is TimeDensity.DISCRETE

    juris = LegalJurisdictionBinding(
        jurisdiction="us-federal",
        territory="united-states",
        authority_id="auth:1",
    )
    assert LegalJurisdictionBinding.from_dict(juris.to_dict()).jurisdiction == (
        "us-federal"
    )


def test_default_connector_singleton() -> None:
    a = legal_logic_slice_connector()
    b = legal_logic_slice_connector()
    assert a is b


def test_deferred_overlay_routes_rejected() -> None:
    connector = LegalLogicSliceConnector()
    with pytest.raises(LegalLogicSliceError, match="deferred"):
        connector.resolve_route("argumentation")
    with pytest.raises(LegalLogicSliceError, match="deferred"):
        connector.resolve_route("description_logic")


def test_mapping_claim_input_supported() -> None:
    claim = {
        "claim_id": "claim:map:1",
        "kind": "base_norm",
        "statement": "O(Disclose)",
        "formula_id": "norm:disclose",
        "actor": "Org",
        "action": "Disclose",
        "norm_type": "obligation",
        "jurisdiction": "eu-gdpr",
        "exception_ids": ["norm:exc:public_interest"],
    }
    slice_item = connect_legal_claim(claim)
    assert slice_item.kind is LegalSliceKind.BASE_NORM
    assert slice_item.jurisdiction.jurisdiction == "eu-gdpr"
    assert slice_item.family_id == "deontic"
