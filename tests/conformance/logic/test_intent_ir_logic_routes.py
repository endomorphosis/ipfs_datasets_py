"""Conformance: intent_ir skill-prompt typed logic routes (LFP-036).

Acceptance:

* Safety/liveness remain property kinds and VC remains a view role
* Prompt-derived formulas are candidates until deterministic
  parsing/typechecking/verification
* Tool authority never follows confidence alone

Interfaces: IntentFormalizationCompiler@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.models import EvidenceAuthority, SupportLevel
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY
from ipfs_datasets_py.logic.intent_ir.formalize.typed_compiler import (
    ADMITTED_INTENT_VIEW_NAMES,
    FUTURE_UNSUPPORTED_FAMILY_CLAIMS,
    INTENT_EVIDENCE_BACKENDS,
    INTENT_FORMALIZATION_COMPILER_INTERFACE,
    INTENT_FORMALIZATION_COMPILER_VERSION,
    INTENT_LOGIC_ROUTE_CATALOG,
    NEVER_FAMILY_OPERATION_ROLES,
    NEVER_FAMILY_PROPERTY_KINDS,
    AuthorityLane,
    AuthorityPromotionError,
    FormulaStatus,
    IntentFormalizationCompiler,
    IntentTypedCompilerError,
    OperationRoleAsFamilyError,
    ParseElaborateStage,
    ParseTypecheckRequiredError,
    ProofAuthorityRole,
    PropertyAsFamilyError,
    RouteDisposition,
    RouteNamespace,
    ToolAuthorityBasis,
    ToolAuthorityFromConfidenceError,
    assert_ready_to_verify,
    classify_formula_candidate,
    decide_tool_authority,
    intent_logic_routes,
    is_never_family_label,
    is_never_family_property,
    parse_and_typecheck,
    reject_operation_role_as_family,
    reject_property_as_family,
    reject_tool_authority_from_confidence,
    resolve_intent_route,
    route_intent_view,
)


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    compiler = IntentFormalizationCompiler()
    assert compiler.interface == INTENT_FORMALIZATION_COMPILER_INTERFACE
    assert IntentFormalizationCompiler.INTERFACE == "IntentFormalizationCompiler@2"
    assert INTENT_FORMALIZATION_COMPILER_INTERFACE == "IntentFormalizationCompiler@2"
    assert compiler.version == INTENT_FORMALIZATION_COMPILER_VERSION
    assert compiler.domain_id == "intent_ir"
    wire = compiler.to_dict()
    assert wire["interface"] == "IntentFormalizationCompiler@2"
    assert wire["domain"] == "intent"
    assert wire["tool_authority_follows_confidence_alone"] is False
    assert wire["prompt_derived_is_candidate_until_verified"] is True


def test_sealed_route_catalog_is_nonempty_and_stable() -> None:
    routes = intent_logic_routes()
    assert routes is INTENT_LOGIC_ROUTE_CATALOG
    assert len(routes) >= 10
    route_ids = [route.route_id for route in routes]
    assert len(set(route_ids)) == len(route_ids)


# ---------------------------------------------------------------------------
# Admitted views: skill goals, tool permissions, guards/effects, norms,
# intentions, workflows, safety/liveness, VCs — separate namespaces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "family_id", "namespace"),
    [
        ("facts", "first_order", RouteNamespace.FAMILY),
        ("guards_effects", "first_order", RouteNamespace.PROFILE),
        ("skill_goals", "intention_agency", RouteNamespace.PROFILE),
        ("intentions", "intention_agency", RouteNamespace.FAMILY),
        ("norms", "deontic", RouteNamespace.FAMILY),
        ("action_hoare", "program", RouteNamespace.PROFILE),
        ("workflows", "temporal", RouteNamespace.PROFILE),
        ("tool_permissions", "authorization", RouteNamespace.PROFILE),
        ("runtime_monitor", "temporal", RouteNamespace.PROFILE),
    ],
)
def test_typed_views_route_to_canonical_families(
    label: str, family_id: str, namespace: RouteNamespace
) -> None:
    compiler = IntentFormalizationCompiler()
    receipt = compiler.route_view(label)
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
    for name in ADMITTED_INTENT_VIEW_NAMES:
        route = resolve_intent_route(name)
        assert route.view_name == name or name in route.aliases or name in {
            route.property_id,
            route.profile_id,
        }
        assert route.is_admitted is True


def test_matrix_aligned_view_ids() -> None:
    compiler = IntentFormalizationCompiler()
    assert compiler.resolve("facts").view_id == "intent-ir-view/facts/v1"
    assert compiler.resolve("intentions").view_id == "intent-ir-view/intention-deontic/v1"
    assert compiler.resolve("action_hoare").view_id == "intent-ir-view/action-hoare/v1"
    assert compiler.resolve("workflows").view_id == "intent-ir-view/workflow-temporal/v1"
    assert compiler.resolve("tool_permissions").view_id == "intent-ir-view/tool-permissions/v1"
    assert compiler.resolve("safety").view_id == "intent-ir-view/invariant/v1"
    assert compiler.resolve("verification_condition").view_id == (
        "intent-ir-view/verification/v1"
    )


def test_separate_namespaces_for_skill_prompt_constructs() -> None:
    """Effects: goals, tools, guards, norms, intentions, workflows, props, VCs."""

    compiler = IntentFormalizationCompiler()
    goals = compiler.resolve("skill_goals")
    tools = compiler.resolve("tool_permissions")
    guards = compiler.resolve("guards_effects")
    norms = compiler.resolve("norms")
    intentions = compiler.resolve("intentions")
    workflows = compiler.resolve("workflows")
    safety = compiler.resolve("safety")
    liveness = compiler.resolve("liveness")
    vc = compiler.resolve("verification_condition")

    namespaces = {
        goals.route_id: (goals.namespace, goals.family_id),
        tools.route_id: (tools.namespace, tools.family_id),
        guards.route_id: (guards.namespace, guards.family_id),
        norms.route_id: (norms.namespace, norms.family_id),
        intentions.route_id: (intentions.namespace, intentions.family_id),
        workflows.route_id: (workflows.namespace, workflows.family_id),
        safety.route_id: (safety.namespace, safety.property_id),
        liveness.route_id: (liveness.namespace, liveness.property_id),
        vc.route_id: (vc.namespace, vc.view_role_id),
    }
    # All nine constructs resolve to distinct routes.
    assert len(namespaces) == 9
    assert goals.family_id == "intention_agency"
    assert tools.family_id == "authorization"
    assert guards.family_id == "first_order"
    assert norms.family_id == "deontic"
    assert intentions.family_id == "intention_agency"
    assert workflows.family_id == "temporal"
    assert safety.is_property_kind and safety.property_id == "safety"
    assert liveness.is_property_kind and liveness.property_id == "liveness"
    assert vc.is_operation_role and vc.view_role_id == "verification_condition"


# ---------------------------------------------------------------------------
# Safety / liveness remain property kinds; VC remains a view role
# ---------------------------------------------------------------------------


def test_safety_and_liveness_are_property_kinds() -> None:
    for label in ("safety", "liveness"):
        route = resolve_intent_route(label)
        assert route.is_property_kind is True
        assert route.namespace is RouteNamespace.PROPERTY
        assert route.disposition is RouteDisposition.PROPERTY
        assert route.family_id == "temporal"
        assert route.property_id == label
        assert route.is_semantic_family is False
        assert is_never_family_property(label) is True

        receipt = route_intent_view(label)
        assert "intent.property_not_family" in receipt.diagnostics
        assert receipt.route.result_authority_ceiling is ResultAuthority.MODEL_CHECK


def test_legacy_safety_liveness_family_label_dual_reads_to_property() -> None:
    """Legacy compiler used logic_family='safety' / 'safety_liveness'."""

    safety = resolve_intent_route("safety")
    assert safety.is_property_kind is True
    assert safety.family_id != "safety"

    # safety_liveness dual-reads as liveness property kind (not a family).
    dual = resolve_intent_route("safety_liveness")
    assert dual.is_property_kind is True
    assert dual.property_id == "liveness"
    assert dual.family_id == "temporal"


def test_verification_condition_is_view_role() -> None:
    route = resolve_intent_route("verification_condition")
    assert route.is_operation_role is True
    assert route.namespace is RouteNamespace.VIEW_ROLE
    assert route.disposition is RouteDisposition.OPERATION
    assert route.family_id == ""
    assert route.view_role_id == "verification_condition"
    assert route.is_semantic_family is False
    assert route.proof_authority is ProofAuthorityRole.NONE
    assert is_never_family_label("verification_condition") is True

    receipt = route_intent_view("verification_condition")
    assert "intent.view_role_not_family" in receipt.diagnostics
    assert receipt.is_proof is False


def test_legacy_vc_logic_family_dual_reads_to_view_role() -> None:
    """Legacy compiler used logic_family='verification_condition'."""

    for label in ("verification_condition", "vc", "verification", "obligation"):
        route = resolve_intent_route(label)
        assert route.is_operation_role is True
        assert route.view_role_id == "verification_condition"
        assert route.family_id == ""


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
    compiler = IntentFormalizationCompiler()
    receipt = compiler.route_view(label)
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
    compiler = IntentFormalizationCompiler()
    with pytest.raises(OperationRoleAsFamilyError):
        compiler.assert_operations_are_not_families()


def test_reject_property_as_family_helper() -> None:
    for label in ("safety", "liveness", "safety_liveness"):
        with pytest.raises(PropertyAsFamilyError):
            reject_property_as_family(label)
    with pytest.raises(PropertyAsFamilyError):
        IntentFormalizationCompiler().assert_properties_are_not_families()


def test_never_family_sets_cover_required_roles() -> None:
    assert "verification_condition" in NEVER_FAMILY_OPERATION_ROLES
    assert "graph_projection" in NEVER_FAMILY_OPERATION_ROLES
    assert "safety" in NEVER_FAMILY_PROPERTY_KINDS
    assert "liveness" in NEVER_FAMILY_PROPERTY_KINDS


def test_operation_role_cannot_claim_theorem_authority() -> None:
    compiler = IntentFormalizationCompiler()
    with pytest.raises(AuthorityPromotionError):
        compiler.route_view(
            "verification_condition", claimed_authority=ResultAuthority.THEOREM
        )
    with pytest.raises(AuthorityPromotionError):
        compiler.route_view(
            "graph_projection", claimed_authority=ResultAuthority.THEOREM
        )


# ---------------------------------------------------------------------------
# Prompt-derived formulas are candidates until parse/typecheck/verify
# ---------------------------------------------------------------------------


def test_prompt_derived_formulas_remain_candidates() -> None:
    candidate = classify_formula_candidate(
        {
            "formula_id": "f:prompt:1",
            "source_kind": "prompt",
            "text": "the agent should always succeed",
            "confidence": 0.99,
        }
    )
    assert candidate.prompt_derived is True
    assert candidate.is_candidate is True
    assert candidate.status is FormulaStatus.CANDIDATE
    assert candidate.may_claim_verified is False
    assert candidate.verified is False
    assert "intent.prompt_derived_candidate" in candidate.diagnostics


def test_prompt_derived_with_high_confidence_still_candidate() -> None:
    candidate = classify_formula_candidate(
        {
            "formula_id": "f:prompt:2",
            "source_kind": "skill_prompt",
            "confidence": 1.0,
            "llm_extracted": True,
        }
    )
    assert candidate.is_candidate is True
    assert candidate.may_claim_verified is False


def test_prompt_derived_advances_only_after_parse_typecheck_verify() -> None:
    still_candidate = classify_formula_candidate(
        {
            "formula_id": "f:prompt:3",
            "source_kind": "prompt_derived",
            "parsed": True,
            "typechecked": True,
            # verified missing → still candidate
        }
    )
    assert still_candidate.is_candidate is True
    assert still_candidate.status is FormulaStatus.CANDIDATE

    verified = classify_formula_candidate(
        {
            "formula_id": "f:prompt:4",
            "source_kind": "prompt_derived",
            "parsed": True,
            "typechecked": True,
            "verified": True,
        }
    )
    assert verified.may_claim_verified is True
    assert verified.status is FormulaStatus.VERIFIED
    assert verified.is_candidate is False


def test_declaration_structured_formulas_parse_and_typecheck() -> None:
    pe = IntentFormalizationCompiler().parse_and_typecheck(
        "facts",
        formulas=[
            {"formula_id": "f:1", "kind": "fact"},
            {"formula_id": "f:2", "kind": "guard"},
        ],
        source_kind="declaration",
    )
    assert pe.ok is True
    assert pe.parsed is True
    assert pe.typechecked is True
    assert pe.ready_to_verify is True
    assert pe.formula_count == 2
    assert pe.stage in {
        ParseElaborateStage.TYPECHECKED,
        ParseElaborateStage.READY_TO_VERIFY,
    }


def test_prompt_derived_batch_not_ready_to_verify_without_pipeline() -> None:
    pe = parse_and_typecheck(
        resolve_intent_route("norms"),
        formulas=[
            {
                "formula_id": "f:nl:1",
                "source_kind": "prompt",
                "text": "must not leak secrets",
            }
        ],
        source_kind="prompt",
    )
    assert pe.prompt_derived_count >= 1
    assert pe.candidate_count >= 1
    assert pe.ready_to_verify is False
    assert pe.parsed is False or pe.typechecked is False
    with pytest.raises(ParseTypecheckRequiredError):
        assert_ready_to_verify(pe)


def test_lower_without_parse_typecheck_fails_closed() -> None:
    compiler = IntentFormalizationCompiler()
    with pytest.raises(ParseTypecheckRequiredError):
        compiler.lower_view(
            "facts",
            formulas=[
                {
                    "formula_id": "f:prompt",
                    "source_kind": "prompt",
                    "text": "do the thing",
                }
            ],
            source_kind="prompt",
        )


def test_every_admitted_view_parses_before_verify() -> None:
    compiler = IntentFormalizationCompiler()
    compiler.assert_admitted_views_parse_before_verify()
    for name in ADMITTED_INTENT_VIEW_NAMES:
        route = resolve_intent_route(name)
        if not route.requires_parse_typecheck:
            continue
        pe = compiler.parse_and_typecheck(name)
        assert pe.ok is True
        assert pe.ready_to_verify is True
        receipt = compiler.lower_view(name)
        assert receipt.lowered is True
        assert receipt.is_ready_to_verify is True


def test_route_view_attaches_parse_typecheck_receipt() -> None:
    receipt = route_intent_view("action_hoare")
    assert receipt.parse_typecheck is not None
    assert receipt.parse_typecheck.ok is True
    assert receipt.parse_typecheck.route_id == receipt.route.route_id
    wire = receipt.to_dict()
    assert wire["parse_typecheck"]["ready_to_verify"] is True
    assert wire["is_ready_to_verify"] is True
    assert wire["is_proof"] is False


# ---------------------------------------------------------------------------
# Tool authority never follows confidence alone
# ---------------------------------------------------------------------------


def test_tool_authority_rejected_from_confidence_alone() -> None:
    with pytest.raises(ToolAuthorityFromConfidenceError) as excinfo:
        reject_tool_authority_from_confidence(tool_id="tool:fs.write", confidence=0.999)
    assert excinfo.value.code == "intent.tool_authority_not_from_confidence"

    with pytest.raises(ToolAuthorityFromConfidenceError):
        decide_tool_authority(
            tool_id="tool:net.http",
            confidence=1.0,
            claimed_authority=True,
        )


def test_high_confidence_without_grounding_does_not_grant() -> None:
    receipt = decide_tool_authority(
        tool_id="tool:shell.exec",
        confidence=0.99,
        claimed_authority=False,
    )
    assert receipt.granted is False
    assert receipt.basis is ToolAuthorityBasis.CONFIDENCE_SCORE
    assert "intent.tool_authority_not_from_confidence" in receipt.diagnostics


def test_tool_authority_granted_with_grounded_permission() -> None:
    receipt = decide_tool_authority(
        tool_id="tool:fs.read",
        confidence=0.1,  # low confidence is fine when grounded
        grounded_permission=True,
    )
    assert receipt.granted is True
    assert receipt.basis is ToolAuthorityBasis.GROUNDED_PERMISSION
    assert receipt.grounded_permission is True


def test_tool_authority_granted_with_authorization_receipt() -> None:
    receipt = decide_tool_authority(
        tool_id="tool:mcp.call",
        confidence=None,
        authorization_receipt_id="authz:receipt:abc",
    )
    assert receipt.granted is True
    assert receipt.basis is ToolAuthorityBasis.AUTHORIZATION_RECEIPT


def test_tool_authority_granted_with_declared_policy() -> None:
    receipt = decide_tool_authority(
        tool_id="tool:db.query",
        policy_id="policy:readonly-db",
        confidence=0.0,
    )
    assert receipt.granted is True
    assert receipt.basis is ToolAuthorityBasis.DECLARED_POLICY


def test_tool_permissions_route_never_uses_confidence_alone() -> None:
    compiler = IntentFormalizationCompiler()
    # Confidence alone → not granted
    receipt = compiler.route_view(
        "tool_permissions",
        tool_id="tool:dangerous",
        tool_confidence=1.0,
    )
    assert receipt.tool_authority is not None
    assert receipt.tool_authority.granted is False
    assert receipt.route.family_id == "authorization"
    assert receipt.route.authority_lane is AuthorityLane.AUTHORIZATION

    # Grounded permission → granted
    receipt_ok = compiler.route_view(
        "tool_permissions",
        tool_id="tool:safe",
        tool_confidence=0.2,
        grounded_permission=True,
    )
    assert receipt_ok.tool_authority is not None
    assert receipt_ok.tool_authority.granted is True

    # Direct API
    auth = compiler.decide_tool_authority(
        tool_id="tool:x",
        confidence=1.0,
        claimed_authority=False,
    )
    assert auth.granted is False


def test_tool_permissions_authority_ceiling_is_authorization() -> None:
    route = resolve_intent_route("tool_permissions")
    assert route.result_authority_ceiling is ResultAuthority.AUTHORIZATION
    assert route.evidence_authority is EvidenceAuthority.INDEPENDENTLY_CHECKABLE
    receipt = route_intent_view("tool_permissions")
    assert receipt.authority_ceiling is ResultAuthority.AUTHORIZATION
    assert receipt.is_proof is False


# ---------------------------------------------------------------------------
# Authority: routes never mint theorem / unknown views fail closed
# ---------------------------------------------------------------------------


def test_route_alone_never_mints_proof() -> None:
    for name in ADMITTED_INTENT_VIEW_NAMES:
        receipt = route_intent_view(name)
        assert receipt.is_proof is False
        assert receipt.route.proof_authority is not ProofAuthorityRole.OFFICIAL


def test_theorem_without_kernel_is_rejected() -> None:
    compiler = IntentFormalizationCompiler()
    with pytest.raises(AuthorityPromotionError):
        compiler.route_view("facts", claimed_authority=ResultAuthority.THEOREM)
    with pytest.raises(AuthorityPromotionError):
        compiler.route_view("safety", claimed_authority=ResultAuthority.THEOREM)


def test_unknown_view_fails_closed() -> None:
    compiler = IntentFormalizationCompiler()
    with pytest.raises(IntentTypedCompilerError) as excinfo:
        compiler.route_for("not_an_intent_view")
    assert excinfo.value.code == "intent.unknown_view"


def test_future_family_labels_are_unsupported() -> None:
    for label in ("probabilistic", "zk", "fuzzy_weighted"):
        assert label in FUTURE_UNSUPPORTED_FAMILY_CLAIMS
        with pytest.raises(IntentTypedCompilerError) as excinfo:
            resolve_intent_route(label)
        assert excinfo.value.code == "intent.unsupported"


def test_catalog_manifest_lists_namespace_separations() -> None:
    manifest = IntentFormalizationCompiler().catalog_manifest()
    assert manifest["interface"] == "IntentFormalizationCompiler@2"
    assert "verification_condition" in manifest["never_family_operation_roles"]
    assert "safety" in manifest["never_family_property_kinds"]
    assert "liveness" in manifest["never_family_property_kinds"]
    assert set(ADMITTED_INTENT_VIEW_NAMES) <= set(manifest["admitted_view_names"])
    assert set(INTENT_EVIDENCE_BACKENDS) == set(manifest["evidence_backends"])
    assert "prompt" in manifest["prompt_derived_source_kinds"]


def test_hoare_and_dynamic_aliases_route_to_program() -> None:
    for label in ("hoare", "dynamic_hoare", "dynamic_logic", "action_hoare"):
        route = resolve_intent_route(label)
        assert route.family_id == "program"
        assert route.profile_id == "dynamic_hoare"


def test_bdi_alias_routes_to_intention_agency() -> None:
    route = resolve_intent_route("bdi")
    assert route.family_id == "intention_agency"
    assert route.is_semantic_family is True


def test_support_levels_are_declared() -> None:
    for route in INTENT_LOGIC_ROUTE_CATALOG:
        assert isinstance(route.support_level, SupportLevel)
        assert route.support_level is not SupportLevel.UNSUPPORTED or route.is_declaration_only
