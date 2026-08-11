"""Conformance: security_ir typed routes to canonical logic (LFP-034).

Acceptance:

* Every admitted security view parses and elaborates before lowering
* Unsupported cells are explicit
* Proof / model / monitor authority is bounded by translation and backend receipts

Interfaces: SecurityFormalizationAdapter@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.models import EvidenceAuthority, SupportLevel
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY
from ipfs_datasets_py.logic.security_ir.formalization_adapter_v2 import (
    ADMITTED_SECURITY_VIEW_NAMES,
    FUTURE_UNSUPPORTED_FAMILY_CLAIMS,
    NEVER_FAMILY_OPERATION_ROLES,
    NEVER_FAMILY_PROPERTY_KINDS,
    SECURITY_EVIDENCE_BACKENDS,
    SECURITY_FORMALIZATION_ADAPTER_INTERFACE,
    SECURITY_FORMALIZATION_ADAPTER_VERSION,
    SECURITY_LOGIC_ROUTE_CATALOG,
    AuthorityLane,
    AuthorityPromotionError,
    BackendReceipt,
    OperationRoleAsFamilyError,
    ParseElaborateRequiredError,
    ParseElaborateStage,
    ProofAuthorityRole,
    PropertyAsFamilyError,
    RouteDisposition,
    RouteNamespace,
    SecurityFormalizationAdapter,
    SecurityTypedAdapterError,
    UnsupportedCellError,
    UnsupportedCellKind,
    assert_ready_to_lower,
    backend_default_authority,
    bound_authority,
    default_unsupported_cells,
    is_never_family_label,
    is_never_family_property,
    issue_backend_receipt,
    issue_translation_receipt,
    parse_and_elaborate,
    record_unsupported_cell,
    reject_operation_role_as_family,
    reject_property_as_family,
    resolve_security_route,
    route_security_view,
    security_logic_routes,
)


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    adapter = SecurityFormalizationAdapter()
    assert adapter.interface == SECURITY_FORMALIZATION_ADAPTER_INTERFACE
    assert SecurityFormalizationAdapter.INTERFACE == "SecurityFormalizationAdapter@2"
    assert SECURITY_FORMALIZATION_ADAPTER_INTERFACE == "SecurityFormalizationAdapter@2"
    assert adapter.version == SECURITY_FORMALIZATION_ADAPTER_VERSION
    assert adapter.domain_id == "security_ir"
    wire = adapter.to_dict()
    assert wire["interface"] == "SecurityFormalizationAdapter@2"
    assert wire["domain"] == "security"


def test_sealed_route_catalog_is_nonempty_and_stable() -> None:
    routes = security_logic_routes()
    assert routes is SECURITY_LOGIC_ROUTE_CATALOG
    assert len(routes) >= 10
    route_ids = [route.route_id for route in routes]
    assert len(set(route_ids)) == len(route_ids)


# ---------------------------------------------------------------------------
# Admitted views: threat, authorization, VC, state, temporal, protocol,
# noninterference, separation, concurrency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "family_id", "namespace"),
    [
        ("threat", "transition_system", RouteNamespace.PROFILE),
        ("threat_model", "transition_system", RouteNamespace.PROFILE),
        ("authorization", "authorization", RouteNamespace.PROFILE),
        ("secpal", "authorization", RouteNamespace.PROFILE),
        ("policy", "deontic", RouteNamespace.PROFILE),
        ("claim", "first_order", RouteNamespace.PROFILE),
        ("chc_vc", "horn_chc", RouteNamespace.PROFILE),
        ("state", "transition_system", RouteNamespace.FAMILY),
        ("transition", "transition_system", RouteNamespace.FAMILY),
        ("temporal", "temporal", RouteNamespace.PROFILE),
        ("protocol", "cryptographic_protocol", RouteNamespace.FAMILY),
        ("hyperproperty", "hyperproperty", RouteNamespace.FAMILY),
        ("separation", "separation_logic", RouteNamespace.FAMILY),
        ("concurrency", "concurrency", RouteNamespace.FAMILY),
        ("runtime_monitor", "temporal", RouteNamespace.PROFILE),
    ],
)
def test_typed_views_route_to_canonical_families(
    label: str, family_id: str, namespace: RouteNamespace
) -> None:
    adapter = SecurityFormalizationAdapter()
    receipt = adapter.route_view(label)
    assert receipt.route.family_id == family_id
    assert receipt.route.namespace is namespace
    assert receipt.route.disposition in {
        RouteDisposition.TYPED,
        RouteDisposition.NATIVE,
        RouteDisposition.BOUNDED,
    }
    assert receipt.route.is_semantic_family is True
    assert receipt.route.is_operation_role is False
    assert receipt.is_proof is False
    assert family_id in DEFAULT_REGISTRY.families


def test_all_admitted_views_are_resolvable() -> None:
    for name in ADMITTED_SECURITY_VIEW_NAMES:
        route = resolve_security_route(name)
        assert route.view_name == name or name in route.aliases or name in {
            route.property_id,
            route.profile_id,
        }
        assert route.is_admitted is True


def test_matrix_aligned_view_ids() -> None:
    adapter = SecurityFormalizationAdapter()
    assert adapter.resolve("threat").view_id == "security-ir-view/threat/v1"
    assert adapter.resolve("authorization").view_id == "security-ir-view/policy/v1"
    assert adapter.resolve("state").view_id == "security-ir-view/transition/v1"
    assert adapter.resolve("claim").view_id == "security-ir-view/claim/v1"
    assert adapter.resolve("protocol").view_id == "security-ir-view/protocol/v1"
    assert adapter.resolve("hyperproperty").view_id == "security-ir-view/hyperproperty/v1"
    assert adapter.resolve("concurrency").view_id == "security-ir-view/concurrency/v1"
    assert adapter.resolve("separation").view_id == "security-ir-view/separation/v1"


def test_noninterference_is_property_under_hyperproperty() -> None:
    route = resolve_security_route("noninterference")
    assert route.namespace is RouteNamespace.PROPERTY
    assert route.disposition is RouteDisposition.PROPERTY
    assert route.property_id == "noninterference"
    assert route.family_id == "hyperproperty"
    assert route.is_property_kind is True
    assert route.is_semantic_family is False
    assert is_never_family_property("noninterference") is True

    receipt = route_security_view("noninterference")
    assert "security.property_not_family" in receipt.diagnostics
    assert receipt.route.result_authority_ceiling is ResultAuthority.HYPERPROPERTY


def test_safety_and_liveness_are_property_kinds() -> None:
    for label in ("safety", "liveness"):
        route = resolve_security_route(label)
        assert route.is_property_kind is True
        assert route.family_id == "temporal"
        assert route.property_id == label


# ---------------------------------------------------------------------------
# Parse and elaborate before lowering
# ---------------------------------------------------------------------------


def test_every_admitted_view_parses_and_elaborates_before_lowering() -> None:
    adapter = SecurityFormalizationAdapter()
    adapter.assert_admitted_views_parse_before_lower()
    for name in ADMITTED_SECURITY_VIEW_NAMES:
        route = resolve_security_route(name)
        if not route.requires_parse_elaborate:
            continue
        pe = adapter.parse_and_elaborate(name)
        assert pe.ok is True
        assert pe.parsed is True
        assert pe.elaborated is True
        assert pe.ready_to_lower is True
        assert pe.stage in {
            ParseElaborateStage.ELABORATED,
            ParseElaborateStage.READY_TO_LOWER,
        }
        assert_ready_to_lower(pe)

        receipt = adapter.lower_view(name)
        assert receipt.lowered is True
        assert receipt.is_ready_to_lower is True
        assert receipt.parse_elaborate is not None
        assert receipt.parse_elaborate.ready_to_lower is True


def test_lower_without_parse_elaborate_fails_closed() -> None:
    route = resolve_security_route("threat")
    pe = parse_and_elaborate(
        route,
        formulas=[{"formula_id": "f1", "unsupported": True, "construct": "zk_gadget"}],
        fail_on_unsupported=True,
    )
    assert pe.ok is False
    assert pe.ready_to_lower is False
    with pytest.raises(ParseElaborateRequiredError):
        assert_ready_to_lower(pe)

    adapter = SecurityFormalizationAdapter()
    with pytest.raises(ParseElaborateRequiredError):
        adapter.lower_view(
            "threat",
            formulas=[{"formula_id": "f1", "unsupported": True, "construct": "zk"}],
        )


def test_route_view_attaches_parse_elaborate_receipt() -> None:
    receipt = route_security_view("protocol")
    assert receipt.parse_elaborate is not None
    assert receipt.parse_elaborate.ok is True
    assert receipt.parse_elaborate.route_id == receipt.route.route_id
    wire = receipt.to_dict()
    assert wire["parse_elaborate"]["ready_to_lower"] is True
    assert wire["is_ready_to_lower"] is True
    assert wire["is_proof"] is False


def test_structured_formulas_are_counted_on_elaboration() -> None:
    pe = SecurityFormalizationAdapter().parse_and_elaborate(
        "claim",
        formulas=[
            {"formula_id": "f:1", "kind": "obligation"},
            {"formula_id": "f:2", "kind": "assumption"},
        ],
    )
    assert pe.ok is True
    assert pe.formula_count == 2


# ---------------------------------------------------------------------------
# Unsupported cells are explicit
# ---------------------------------------------------------------------------


def test_unsupported_cells_are_explicit() -> None:
    cells = default_unsupported_cells()
    assert len(cells) >= 1
    for cell in cells:
        assert cell.is_explicit is True
        assert cell.may_claim_support is False
        wire = cell.to_dict()
        assert wire["is_explicit"] is True
        assert wire["may_claim_support"] is False

    future = [c for c in cells if c.kind is UnsupportedCellKind.FUTURE_FAMILY]
    assert any(c.label == "probabilistic" for c in future)


def test_future_family_labels_are_explicit_unsupported() -> None:
    for label in ("probabilistic", "zk", "fuzzy_weighted", "finite_field_constraint"):
        assert label in FUTURE_UNSUPPORTED_FAMILY_CLAIMS or any(
            label == item or label in item for item in FUTURE_UNSUPPORTED_FAMILY_CLAIMS
        )
        with pytest.raises(UnsupportedCellError):
            resolve_security_route(label)


def test_record_unsupported_cell_helper() -> None:
    cell = record_unsupported_cell(
        kind=UnsupportedCellKind.MISSING_BACKEND,
        label="unbounded_model_check",
        description="unbounded MC without finite bound profile",
        family_id="transition_system",
    )
    assert cell.is_explicit is True
    assert cell.kind is UnsupportedCellKind.MISSING_BACKEND
    assert cell.may_claim_support is False


def test_unsupported_constructs_surface_on_receipt() -> None:
    receipt = SecurityFormalizationAdapter().route_view(
        "claim",
        formulas=[
            {"formula_id": "f:ok", "kind": "vc"},
            {
                "formula_id": "f:bad",
                "unsupported": True,
                "construct": "probabilistic_gadget",
            },
        ],
        fail_on_unsupported=False,
    )
    assert receipt.parse_elaborate is not None
    assert "probabilistic_gadget" in receipt.parse_elaborate.unsupported_constructs
    assert any(
        cell.label == "probabilistic_gadget" for cell in receipt.unsupported_cells
    )


def test_catalog_manifest_lists_unsupported_cells() -> None:
    manifest = SecurityFormalizationAdapter().catalog_manifest()
    assert manifest["interface"] == "SecurityFormalizationAdapter@2"
    assert len(manifest["unsupported_cells"]) >= 1
    assert "verification_condition" in manifest["never_family_operation_roles"]
    assert "noninterference" in manifest["never_family_property_kinds"]
    assert set(ADMITTED_SECURITY_VIEW_NAMES) <= set(manifest["admitted_view_names"])


# ---------------------------------------------------------------------------
# Operation roles never route as families
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "verification_condition",
        "graph_projection",
        "proof_translation",
        "vc_role",
        "obligation",
    ],
)
def test_operation_roles_never_route_as_families(label: str) -> None:
    adapter = SecurityFormalizationAdapter()
    receipt = adapter.route_view(label)
    assert receipt.route.is_operation_role is True
    assert receipt.route.namespace is RouteNamespace.VIEW_ROLE
    assert receipt.route.disposition is RouteDisposition.OPERATION
    assert receipt.route.family_id == ""
    assert receipt.route.view_role_id in {
        "verification_condition",
        "graph_projection",
        "proof_translation",
    }
    assert receipt.route.is_semantic_family is False
    assert receipt.route.proof_authority is ProofAuthorityRole.NONE
    assert is_never_family_label(label) is True


def test_reject_operation_role_as_family_helper() -> None:
    for label in ("verification_condition", "graph_projection", "proof_translation"):
        with pytest.raises(OperationRoleAsFamilyError):
            reject_operation_role_as_family(label)
    adapter = SecurityFormalizationAdapter()
    with pytest.raises(OperationRoleAsFamilyError):
        adapter.assert_operations_are_not_families()


def test_reject_property_as_family_helper() -> None:
    for label in ("safety", "liveness", "noninterference"):
        with pytest.raises(PropertyAsFamilyError):
            reject_property_as_family(label)
    with pytest.raises(PropertyAsFamilyError):
        SecurityFormalizationAdapter().assert_properties_are_not_families()


def test_never_family_sets_cover_required_roles() -> None:
    assert "verification_condition" in NEVER_FAMILY_OPERATION_ROLES
    assert "graph_projection" in NEVER_FAMILY_OPERATION_ROLES
    assert "noninterference" in NEVER_FAMILY_PROPERTY_KINDS
    assert "safety" in NEVER_FAMILY_PROPERTY_KINDS
    assert "liveness" in NEVER_FAMILY_PROPERTY_KINDS


def test_operation_role_cannot_claim_theorem_authority() -> None:
    adapter = SecurityFormalizationAdapter()
    with pytest.raises(AuthorityPromotionError):
        adapter.route_view(
            "graph_projection", claimed_authority=ResultAuthority.THEOREM
        )


# ---------------------------------------------------------------------------
# Proof / model / monitor authority bounded by translation + backend receipts
# ---------------------------------------------------------------------------


def test_route_alone_never_mints_proof() -> None:
    for name in ADMITTED_SECURITY_VIEW_NAMES:
        receipt = route_security_view(name)
        assert receipt.is_proof is False
        assert receipt.authority_ceiling is not ResultAuthority.THEOREM or (
            receipt.backend is not None
            and receipt.backend.authority is ResultAuthority.THEOREM
        )


def test_theorem_without_backend_receipt_is_rejected() -> None:
    adapter = SecurityFormalizationAdapter()
    with pytest.raises(AuthorityPromotionError):
        adapter.route_view("claim", claimed_authority=ResultAuthority.THEOREM)
    with pytest.raises(AuthorityPromotionError):
        adapter.route_view("separation", claimed_authority=ResultAuthority.THEOREM)


def test_model_authority_bounded_by_backend_receipt() -> None:
    adapter = SecurityFormalizationAdapter()
    receipt = adapter.route_view("threat", backend_id="tla_tlc")
    assert receipt.backend is not None
    assert receipt.backend.authority is ResultAuthority.MODEL_CHECK
    assert receipt.backend.authority_lane is AuthorityLane.MODEL
    assert receipt.authority_ceiling is ResultAuthority.MODEL_CHECK
    assert receipt.route.authority_lane is AuthorityLane.MODEL


def test_monitor_authority_bounded_by_runtime_mtl() -> None:
    adapter = SecurityFormalizationAdapter()
    receipt = adapter.route_view("runtime_monitor", backend_id="runtime_mtl")
    assert receipt.backend is not None
    assert receipt.backend.authority is ResultAuthority.MONITOR
    assert receipt.backend.authority_lane is AuthorityLane.MONITOR
    assert receipt.authority_ceiling is ResultAuthority.MONITOR
    assert receipt.route.result_authority_ceiling is ResultAuthority.MONITOR


def test_authorization_authority_bounded_by_secpal() -> None:
    receipt = route_security_view("authorization", backend_id="datalog_secpal")
    assert receipt.backend is not None
    assert receipt.backend.authority is ResultAuthority.AUTHORIZATION
    assert receipt.authority_ceiling is ResultAuthority.AUTHORIZATION


def test_protocol_authority_bounded_by_proverif() -> None:
    receipt = route_security_view("protocol", backend_id="proverif")
    assert receipt.backend is not None
    assert receipt.backend.authority is ResultAuthority.PROTOCOL
    assert receipt.authority_ceiling is ResultAuthority.PROTOCOL


def test_hyperproperty_authority_bounded_by_hyperltl() -> None:
    receipt = route_security_view("noninterference", backend_id="hyperltl_autohyper_mchyper")
    assert receipt.backend is not None
    assert receipt.backend.authority is ResultAuthority.HYPERPROPERTY
    assert receipt.authority_ceiling is ResultAuthority.HYPERPROPERTY


def test_translation_receipt_bounds_authority() -> None:
    route = resolve_security_route("claim")
    translation = issue_translation_receipt(
        route,
        authority_ceiling=ResultAuthority.CANDIDATE,
        proof_safe=False,
    )
    assert translation.authority_ceiling is ResultAuthority.CANDIDATE
    bounded = bound_authority(
        route,
        claimed=ResultAuthority.SATISFIABILITY,
        translation=translation,
    )
    # Candidate ranks below satisfiability → translation ceiling wins.
    assert bounded is ResultAuthority.CANDIDATE


def test_backend_cannot_exceed_route_ceiling() -> None:
    route = resolve_security_route("separation")
    # Kernel backend defaults to THEOREM, but route ceiling is CANDIDATE.
    backend = issue_backend_receipt(route, "lean")
    assert backend.authority is ResultAuthority.CANDIDATE
    bounded = bound_authority(
        route,
        claimed=ResultAuthority.THEOREM,
        backend=backend,
    )
    assert bounded is ResultAuthority.CANDIDATE


def test_backend_default_authorities_for_evidence_subset() -> None:
    expected = {
        "z3": ResultAuthority.SATISFIABILITY,
        "cvc5": ResultAuthority.SATISFIABILITY,
        "tla_tlc": ResultAuthority.MODEL_CHECK,
        "apalache": ResultAuthority.MODEL_CHECK,
        "datalog_secpal": ResultAuthority.AUTHORIZATION,
        "proverif": ResultAuthority.PROTOCOL,
        "tamarin": ResultAuthority.PROTOCOL,
        "hyperltl_autohyper_mchyper": ResultAuthority.HYPERPROPERTY,
        "vampire": ResultAuthority.CANDIDATE,
        "eprover": ResultAuthority.CANDIDATE,
        "lean": ResultAuthority.THEOREM,
        "rocq": ResultAuthority.THEOREM,
        "isabelle": ResultAuthority.THEOREM,
        "runtime_mtl": ResultAuthority.MONITOR,
    }
    for backend_id, authority in expected.items():
        assert backend_id in SECURITY_EVIDENCE_BACKENDS
        assert backend_default_authority(backend_id) is authority


def test_smt_and_fol_aliases_canonicalize_to_claim() -> None:
    for label in ("smt", "smt_lib", "smtlib2", "fol", "first_order"):
        route = resolve_security_route(label)
        assert route.family_id == "first_order"
        assert route.profile_id == "verification_condition"


def test_verification_condition_is_role_not_family() -> None:
    route = resolve_security_route("verification_condition")
    assert route.is_operation_role is True
    assert route.family_id == ""
    assert route.view_role_id == "verification_condition"
    # Claim route is the semantic family surface for VCs.
    claim = resolve_security_route("claim")
    assert claim.family_id == "first_order"
    assert claim.profile_id == "verification_condition"


# ---------------------------------------------------------------------------
# Catalog integrity
# ---------------------------------------------------------------------------


def test_no_route_assigns_operation_role_as_family_id() -> None:
    for route in SECURITY_LOGIC_ROUTE_CATALOG:
        if route.family_id:
            assert route.family_id not in NEVER_FAMILY_OPERATION_ROLES
            assert route.family_id not in NEVER_FAMILY_PROPERTY_KINDS
            assert route.family_id in DEFAULT_REGISTRY.families
        if route.is_operation_role:
            assert route.family_id == ""
            assert route.view_role_id
            assert route.proof_authority is not ProofAuthorityRole.OFFICIAL
        if route.is_property_kind:
            assert route.property_id
            assert route.proof_authority is not ProofAuthorityRole.OFFICIAL


def test_admitted_routes_declare_backends_or_are_roles() -> None:
    for route in SECURITY_LOGIC_ROUTE_CATALOG:
        if route.is_operation_role:
            continue
        if route.is_admitted:
            assert route.backend_ids, f"{route.route_id} missing backends"
            for backend_id in route.backend_ids:
                assert backend_id in SECURITY_EVIDENCE_BACKENDS


def test_unknown_label_fails_closed() -> None:
    with pytest.raises(SecurityTypedAdapterError) as exc_info:
        resolve_security_route("not_a_real_security_family_xyz")
    assert exc_info.value.code == "security.unknown_view"


def test_receipt_wire_shape() -> None:
    receipt = route_security_view("threat", backend_id="apalache")
    wire = receipt.to_dict()
    assert wire["schema_version"] == "security-logic-route-receipt/v1"
    assert wire["is_proof"] is False
    assert wire["route"]["family_id"] == "transition_system"
    assert wire["route"]["namespace"] == "profile"
    assert wire["route"]["profile_id"] == "threat_model"
    assert wire["backend"]["authority"] == "model_check"
    assert wire["translation"] is not None
    assert wire["parse_elaborate"]["ready_to_lower"] is True


def test_module_level_route_security_view_matches_adapter() -> None:
    a = SecurityFormalizationAdapter().route_view("protocol")
    b = route_security_view("protocol")
    assert a.route.route_id == b.route.route_id
    assert a.family_id == "cryptographic_protocol"


def test_authority_lanes_cover_proof_model_monitor() -> None:
    adapter = SecurityFormalizationAdapter()
    lanes = {route.authority_lane for route in adapter.admitted_routes()}
    assert AuthorityLane.PROOF in lanes
    assert AuthorityLane.MODEL in lanes
    assert AuthorityLane.MONITOR in lanes
    assert AuthorityLane.AUTHORIZATION in lanes
    assert AuthorityLane.PROTOCOL in lanes
    assert AuthorityLane.HYPERPROPERTY in lanes


def test_support_levels_are_sealed() -> None:
    for route in SECURITY_LOGIC_ROUTE_CATALOG:
        assert isinstance(route.support_level, SupportLevel)
        assert isinstance(route.evidence_authority, EvidenceAuthority)
        if route.is_admitted:
            assert route.support_level is not SupportLevel.UNSUPPORTED


def test_backend_receipt_dataclass_wire() -> None:
    route = resolve_security_route("temporal")
    backend = issue_backend_receipt(
        route, "runtime_mtl", status="not_executed", bound_profile="ltl"
    )
    assert isinstance(backend, BackendReceipt)
    wire = backend.to_dict()
    assert wire["backend_id"] == "runtime_mtl"
    assert wire["authority"] == "monitor"
