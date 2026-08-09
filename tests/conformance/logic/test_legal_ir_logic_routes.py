"""Conformance: legal_ir typed routes to canonical logic (LFP-037).

Acceptance:

* Norm conflicts and ambiguity are explicit
* Argumentation receives an explicit declaration-only/unsupported disposition
* graph_projection / proof_translation / structural_round_trip never route as families
* Natural-language extraction is never proof authority

Interfaces: LegalFormalizationAdapter@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.models import EvidenceAuthority, SupportLevel
from ipfs_datasets_py.logic.families.registry import (
    DECLARATION_ONLY_FAMILY_IDS,
    DEFAULT_REGISTRY,
)
from ipfs_datasets_py.logic.legal_ir.typed_adapter import (
    LEGAL_FORMALIZATION_ADAPTER_INTERFACE,
    LEGAL_FORMALIZATION_ADAPTER_VERSION,
    LEGAL_LOGIC_ROUTE_CATALOG,
    NEVER_FAMILY_OPERATION_ROLES,
    AmbiguityKind,
    AmbiguityRecord,
    AuthorityPromotionError,
    LegalFormalizationAdapter,
    LegalTypedAdapterError,
    NaturalLanguageProofAuthorityError,
    NormConflictKind,
    OperationRoleAsFamilyError,
    ProofAuthorityRole,
    RouteDisposition,
    RouteNamespace,
    detect_norm_conflicts,
    is_never_family_label,
    legal_logic_routes,
    looks_like_natural_language,
    record_ambiguity,
    reject_natural_language_proof_authority,
    reject_operation_role_as_family,
    resolve_legal_route,
    route_legal_view,
)


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    adapter = LegalFormalizationAdapter()
    assert adapter.interface == LEGAL_FORMALIZATION_ADAPTER_INTERFACE
    assert LegalFormalizationAdapter.INTERFACE == "LegalFormalizationAdapter@2"
    assert LEGAL_FORMALIZATION_ADAPTER_INTERFACE == "LegalFormalizationAdapter@2"
    assert adapter.version == LEGAL_FORMALIZATION_ADAPTER_VERSION
    wire = adapter.to_dict()
    assert wire["interface"] == "LegalFormalizationAdapter@2"
    assert wire["domain"] == "legal"


def test_sealed_route_catalog_is_nonempty_and_stable() -> None:
    routes = legal_logic_routes()
    assert routes is LEGAL_LOGIC_ROUTE_CATALOG
    assert len(routes) >= 10
    route_ids = [route.route_id for route in routes]
    assert route_ids == sorted(route_ids) or len(set(route_ids)) == len(route_ids)
    assert len(set(route_ids)) == len(route_ids)


# ---------------------------------------------------------------------------
# Typed foundation families: deontic, temporal, event, frame, authorization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "family_id", "namespace"),
    [
        ("deontic", "deontic", RouteNamespace.FAMILY),
        ("conditional_normative", "deontic", RouteNamespace.PROFILE),
        ("defeasible", "deontic", RouteNamespace.PROFILE),
        ("tdfol", "tdfol", RouteNamespace.FAMILY),
        ("temporal_first_order", "tdfol", RouteNamespace.FAMILY),
        ("first_order", "first_order", RouteNamespace.FAMILY),
        ("event_calculus", "event_calculus", RouteNamespace.FAMILY),
        ("cec", "event_calculus", RouteNamespace.FAMILY),
        ("frame_logic", "frame_logic", RouteNamespace.FAMILY),
        ("authorization", "authorization", RouteNamespace.FAMILY),
        ("secpal", "authorization", RouteNamespace.FAMILY),
        ("rules", "authorization", RouteNamespace.FAMILY),
    ],
)
def test_typed_views_route_to_canonical_families(
    label: str, family_id: str, namespace: RouteNamespace
) -> None:
    adapter = LegalFormalizationAdapter()
    receipt = adapter.route_view(label)
    assert receipt.route.family_id == family_id
    assert receipt.route.namespace is namespace
    assert receipt.route.disposition in {
        RouteDisposition.TYPED,
        RouteDisposition.NATIVE,
    }
    assert receipt.route.is_semantic_family is True
    assert receipt.route.is_operation_role is False
    assert receipt.is_proof is False
    assert family_id in DEFAULT_REGISTRY.families


def test_deontic_preserves_exceptions_and_priorities() -> None:
    route = resolve_legal_route("deontic")
    assert "exception_precedence" in route.preservation_rules
    assert "priority_order" in route.preservation_rules
    defeasible = resolve_legal_route("defeasible_normative")
    assert defeasible.family_id == "deontic"
    assert defeasible.profile_id == "defeasible_normative"
    assert "defeater_scope" in defeasible.preservation_rules


# ---------------------------------------------------------------------------
# Argumentation / description: declaration-only
# ---------------------------------------------------------------------------


def test_argumentation_is_explicit_declaration_only() -> None:
    adapter = LegalFormalizationAdapter()
    route = adapter.argumentation_disposition()
    assert route.family_id == "argumentation"
    assert route.namespace is RouteNamespace.DECLARATION_ONLY
    assert route.disposition is RouteDisposition.DECLARATION_ONLY
    assert route.support_level is SupportLevel.DECLARATION_ONLY
    assert route.proof_authority is ProofAuthorityRole.DECLARATION
    assert route.may_emit_proof is False
    assert route.family_id in DECLARATION_ONLY_FAMILY_IDS

    receipt = adapter.route_view("argumentation")
    assert "legal.declaration_only" in receipt.diagnostics
    assert receipt.authority_ceiling is not ResultAuthority.THEOREM

    with pytest.raises(AuthorityPromotionError):
        adapter.route_view("argumentation", claimed_authority=ResultAuthority.THEOREM)


def test_description_logic_is_declaration_only() -> None:
    receipt = route_legal_view("description_logic")
    assert receipt.route.disposition is RouteDisposition.DECLARATION_ONLY
    assert receipt.route.family_id == "description_logic"
    assert receipt.route.may_emit_proof is False


def test_full_defeasible_logic_family_remains_declaration_only() -> None:
    """Defeasible norms under deontic are typed; the family itself is not."""

    family_route = resolve_legal_route("defeasible_logic")
    assert family_route.disposition is RouteDisposition.DECLARATION_ONLY
    assert family_route.family_id == "defeasible_logic"
    norm_route = resolve_legal_route("defeasible")
    assert norm_route.family_id == "deontic"
    assert norm_route.disposition is RouteDisposition.TYPED


# ---------------------------------------------------------------------------
# Operation roles never route as families
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "graph_projection",
        "proof_translation",
        "structural_round_trip",
        "knowledge_graphs",
        "external_provers",
        "decompiler",
        "round_trip",
        "legal-ir-view/knowledge-graphs/v1",
        "legal-ir-view/external-provers/v1",
        "legal-ir-view/decompiler/v1",
    ],
)
def test_operation_roles_never_route_as_families(label: str) -> None:
    adapter = LegalFormalizationAdapter()
    receipt = adapter.route_view(label)
    assert receipt.route.is_operation_role is True
    assert receipt.route.namespace is RouteNamespace.VIEW_ROLE
    assert receipt.route.disposition is RouteDisposition.OPERATION
    assert receipt.route.family_id == ""
    assert receipt.route.view_role_id in {
        "graph_projection",
        "proof_translation",
        "structural_round_trip",
    }
    assert receipt.route.is_semantic_family is False
    assert receipt.route.proof_authority is ProofAuthorityRole.NONE
    assert is_never_family_label(label) is True


def test_reject_operation_role_as_family_helper() -> None:
    for label in ("graph_projection", "proof_translation", "structural_round_trip"):
        with pytest.raises(OperationRoleAsFamilyError):
            reject_operation_role_as_family(label)
    adapter = LegalFormalizationAdapter()
    with pytest.raises(OperationRoleAsFamilyError):
        adapter.assert_operations_are_not_families()


def test_never_family_set_covers_required_roles() -> None:
    required = {
        "graph_projection",
        "proof_translation",
        "structural_round_trip",
    }
    assert required <= NEVER_FAMILY_OPERATION_ROLES


def test_operation_role_cannot_claim_theorem_authority() -> None:
    adapter = LegalFormalizationAdapter()
    with pytest.raises(AuthorityPromotionError):
        adapter.route_view(
            "graph_projection", claimed_authority=ResultAuthority.THEOREM
        )


# ---------------------------------------------------------------------------
# Norm conflicts and ambiguity are explicit
# ---------------------------------------------------------------------------


def test_norm_conflicts_are_explicit() -> None:
    formulas = [
        {
            "formula_id": "f:obl",
            "norm_type": "obligation",
            "actor": "agency",
            "action": "publish_notice",
            "object": "notice",
        },
        {
            "formula_id": "f:proh",
            "norm_type": "prohibition",
            "actor": "agency",
            "action": "publish_notice",
            "object": "notice",
        },
    ]
    conflicts = detect_norm_conflicts(formulas)
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.kind is NormConflictKind.OBLIGATION_PROHIBITION
    assert conflict.is_explicit is True
    assert conflict.unresolved is True
    assert set(conflict.formula_ids) == {"f:obl", "f:proh"}
    wire = conflict.to_dict()
    assert wire["is_explicit"] is True
    assert wire["kind"] == "obligation_prohibition"

    receipt = LegalFormalizationAdapter().route_view("deontic", formulas=formulas)
    assert len(receipt.conflicts) == 1
    assert "legal.norm_conflict" in receipt.diagnostics


def test_priority_orders_can_resolve_conflict_flag() -> None:
    formulas = [
        {
            "formula_id": "f:high",
            "norm_type": "obligation",
            "actor": "agency",
            "action": "disclose",
            "priority": 1,
            "exceptions": ["emergency"],
        },
        {
            "formula_id": "f:low",
            "norm_type": "prohibition",
            "actor": "agency",
            "action": "disclose",
            "priority": 10,
            "exceptions": ["emergency"],
        },
    ]
    conflicts = detect_norm_conflicts(formulas)
    assert len(conflicts) >= 1
    # Priority or exceptions present → not left as wholly unresolved silence.
    assert any(c.priority_order or c.exception_ids for c in conflicts)
    assert all(c.is_explicit for c in conflicts)


def test_ambiguity_is_explicit_and_not_proof_safe() -> None:
    ambiguity = record_ambiguity(
        kind=AmbiguityKind.COMPETING_PARSES,
        description="operator may be obligation or permission",
        competing_interpretations=("obligation", "permission"),
        target_views=("deontic",),
        formula_ids=("f:1",),
        unresolved=True,
    )
    assert ambiguity.is_explicit is True
    assert ambiguity.unresolved is True
    assert ambiguity.proof_safe is False
    assert ambiguity.learned_label_safe is False
    wire = ambiguity.to_dict()
    assert wire["is_explicit"] is True
    assert wire["proof_safe"] is False

    receipt = LegalFormalizationAdapter().route_view(
        "deontic", ambiguities=(ambiguity,)
    )
    assert len(receipt.ambiguities) == 1
    assert "legal.ambiguity" in receipt.diagnostics
    assert receipt.is_proof is False


def test_natural_language_ambiguity_blocks_proof() -> None:
    ambiguity = record_ambiguity(
        kind=AmbiguityKind.NATURAL_LANGUAGE,
        description="prose-only extraction without typed parse",
        unresolved=True,
    )
    assert ambiguity.proof_safe is False
    assert ambiguity.kind is AmbiguityKind.NATURAL_LANGUAGE


# ---------------------------------------------------------------------------
# Natural-language extraction is never proof authority
# ---------------------------------------------------------------------------


def test_nl_extraction_never_proof_authority() -> None:
    adapter = LegalFormalizationAdapter()
    receipt = adapter.route_view(
        "deontic",
        nl_extraction=True,
        source={
            "kind": "natural_language",
            "text": "Agency shall publish notice.",
            "nl_extraction": True,
        },
    )
    assert receipt.nl_extraction is True
    assert receipt.is_proof is False
    assert receipt.authority_ceiling is ResultAuthority.CANDIDATE
    assert "legal.nl_extraction_not_proof" in receipt.diagnostics


def test_nl_extraction_cannot_claim_theorem() -> None:
    with pytest.raises(NaturalLanguageProofAuthorityError):
        reject_natural_language_proof_authority(
            {
                "kind": "natural_language",
                "nl_extraction": True,
                "text": "Please prove that the agency must publish notice.",
            },
            claimed_authority="theorem",
        )
    with pytest.raises(NaturalLanguageProofAuthorityError):
        LegalFormalizationAdapter().route_view(
            "deontic",
            nl_extraction=True,
            claimed_authority=ResultAuthority.THEOREM,
            source={"nl_extraction": True, "kind": "nl"},
        )


def test_looks_like_natural_language_detects_prose() -> None:
    assert looks_like_natural_language(
        "The agency shall publish notice in the Federal Register."
    )
    assert looks_like_natural_language(
        {"kind": "natural_language", "text": "hello world"}
    )
    assert not looks_like_natural_language(
        "(assert (forall ((x Person)) (obligated x)))"
    )
    assert not looks_like_natural_language("fof(ax1, axiom, p(a)).")


def test_typed_symbolic_source_does_not_force_nl_flag() -> None:
    receipt = route_legal_view(
        "first_order",
        source="fof(ax1, axiom, obligated(agency, publish_notice)).",
    )
    assert receipt.nl_extraction is False
    assert receipt.is_proof is False


# ---------------------------------------------------------------------------
# Catalog integrity / authority ceilings
# ---------------------------------------------------------------------------


def test_no_route_assigns_operation_role_as_family_id() -> None:
    for route in LEGAL_LOGIC_ROUTE_CATALOG:
        if route.family_id:
            assert route.family_id not in NEVER_FAMILY_OPERATION_ROLES
            assert route.family_id in DEFAULT_REGISTRY.families
        if route.is_operation_role:
            assert route.family_id == ""
            assert route.view_role_id
            assert route.proof_authority is not ProofAuthorityRole.OFFICIAL


def test_catalog_manifest_lists_operation_and_declaration_routes() -> None:
    manifest = LegalFormalizationAdapter().catalog_manifest()
    assert manifest["interface"] == "LegalFormalizationAdapter@2"
    assert any("argumentation" in rid for rid in manifest["declaration_only_route_ids"])
    assert any(
        "graph-projection" in rid or "graph_projection" in rid
        for rid in manifest["operation_role_route_ids"]
    )
    assert "graph_projection" in manifest["never_family_operation_roles"]
    assert "proof_translation" in manifest["never_family_operation_roles"]
    assert "structural_round_trip" in manifest["never_family_operation_roles"]


def test_unknown_label_fails_closed() -> None:
    with pytest.raises(LegalTypedAdapterError) as exc_info:
        resolve_legal_route("not_a_real_legal_family_xyz")
    assert exc_info.value.code == "legal.unknown_view"


def test_frame_logic_is_advisory_not_proof() -> None:
    route = resolve_legal_route("frame_logic")
    assert route.evidence_authority is EvidenceAuthority.ADVISORY
    assert route.proof_authority is ProofAuthorityRole.ADVISORY
    assert route.result_authority_ceiling is ResultAuthority.CANDIDATE


def test_receipt_wire_shape() -> None:
    receipt = route_legal_view("deontic")
    wire = receipt.to_dict()
    assert wire["schema_version"] == "legal-logic-route-receipt/v1"
    assert wire["is_proof"] is False
    assert wire["route"]["family_id"] == "deontic"
    assert wire["route"]["namespace"] == "family"


def test_module_level_route_legal_view_matches_adapter() -> None:
    a = LegalFormalizationAdapter().route_view("event_calculus")
    b = route_legal_view("event_calculus")
    assert a.route.route_id == b.route.route_id
    assert a.family_id == "event_calculus"
