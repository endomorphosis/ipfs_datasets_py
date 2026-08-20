"""Unit tests for ControlFlowMutationOperators@1 (AAE-015)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MutationOperatorDefinition,
    MutationRiskClass,
    MutationTarget,
    OperatorClass,
    PropertyClass,
    RollbackDeclaration,
    RollbackStrategy,
    SandboxMode,
    SandboxRequirement,
    ScopeLimits,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.base import (
    OperatorRollbackRecord,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.control_flow import (
    CONTROL_FLOW_OPERATORS_INTERFACE,
    CONTROL_FLOW_OPERATORS_SCHEMA,
    DEFAULT_CONTROL_FLOW_RISK_CLASS,
    REQUIRED_CONTROL_FLOW_FAMILIES,
    ControlFlowCoverageError,
    ControlFlowError,
    ControlFlowFamily,
    ControlFlowMutationOperators,
    ControlFlowOperator,
    ControlFlowOperatorSpec,
    assert_control_flow_operator_defaults,
    build_control_flow_operator,
    build_control_flow_operators,
    control_flow_families_covered,
    control_flow_operator_definitions,
    control_flow_operator_specs,
    default_control_flow_operators,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.registry import (
    MutationOperatorRegistryBuilder,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _target(**overrides: object) -> MutationTarget:
    fields = {
        "target_id": "control_gate_fn",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state-cf"),
        "symbol_ids": ("mod.control_gate",),
        "artifact_cids": (_cid("artifact-cf"),),
        "language": "python",
        "artifact_type": "source_module",
        "prerequisites": ("parsed_ast", "symbol_table", "type_check"),
        "risk_class": MutationRiskClass.CRITICAL_INVARIANT,
        "risk_weight_bp": 7_500,
        "capsule_cids": (_cid("capsule-cf"),),
        "proof_unit_cids": (_cid("proof-cf"),),
        "source_path": "mod/control_gate.py",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationTarget(**fields)  # type: ignore[arg-type]


def _minimal_spec(**overrides: object) -> ControlFlowOperatorSpec:
    fields: dict[str, object] = {
        "operator_id": "cf_invert_conditional",
        "family": ControlFlowFamily.INVERSION,
        "semantic_intent": "Invert a boolean guard",
        "syntactic_transformation": "negate_conditional_predicate",
        "expected_violated_property_classes": (PropertyClass.CONTROL_INVARIANT,),
        "likely_equivalent_conditions": (
            "then_and_else_bodies_are_observationally_identical",
        ),
    }
    fields.update(overrides)
    return ControlFlowOperatorSpec(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Spec validation and defaults
# ---------------------------------------------------------------------------


def test_default_risk_class_is_critical_invariant() -> None:
    assert DEFAULT_CONTROL_FLOW_RISK_CLASS == MutationRiskClass.CRITICAL_INVARIANT.value


def test_spec_requires_equivalence_hints() -> None:
    with pytest.raises(ControlFlowError, match="equivalence hints"):
        ControlFlowOperatorSpec(
            operator_id="cf_no_equiv",
            family=ControlFlowFamily.INVERSION,
            semantic_intent="Invert without hints",
            syntactic_transformation="negate_conditional_predicate",
            expected_violated_property_classes=(PropertyClass.CONTROL_INVARIANT,),
            likely_equivalent_conditions=(),
        )


def test_spec_rejects_unknown_family() -> None:
    with pytest.raises(ControlFlowError, match="unsupported control-flow family"):
        ControlFlowOperatorSpec(
            operator_id="cf_unknown_family",
            family="not_a_family",
            semantic_intent="Unknown family must fail closed",
            syntactic_transformation="noop",
            expected_violated_property_classes=(PropertyClass.CONTROL_INVARIANT,),
            likely_equivalent_conditions=("always_dead",),
        )


def test_spec_rejects_empty_semantic_intent() -> None:
    with pytest.raises(ControlFlowError, match="semantic_intent"):
        ControlFlowOperatorSpec(
            operator_id="cf_empty_intent",
            family=ControlFlowFamily.INVERSION,
            semantic_intent="   ",
            syntactic_transformation="negate_conditional_predicate",
            expected_violated_property_classes=(PropertyClass.CONTROL_INVARIANT,),
            likely_equivalent_conditions=("x",),
        )


def test_build_operator_seals_with_control_flow_class() -> None:
    sealed = build_control_flow_operator(_minimal_spec())
    assert sealed.operator_class == OperatorClass.CONTROL_FLOW.value
    assert sealed.risk_class == MutationRiskClass.CRITICAL_INVARIANT.value
    assert sealed.deterministic is True
    assert sealed.required_sandbox.network_disabled is True
    assert sealed.required_sandbox.production_credentials_forbidden is True
    assert sealed.rollback.preserves_production is True
    assert sealed.metadata["cf_family"] == "inversion"
    assert sealed.semantic_intent
    assert sealed.likely_equivalent_conditions
    assert_control_flow_operator_defaults(sealed)


def test_assert_defaults_rejects_wrong_operator_class() -> None:
    wrong = MutationOperatorDefinition(
        operator_id="auth_bypass_authentication",
        operator_version="1",
        operator_class=OperatorClass.AUTHORIZATION_POLICY,
        supported_languages=("python",),
        supported_artifact_types=("source_module",),
        target_prerequisites=("parsed_ast",),
        semantic_intent="Not a control-flow operator",
        expected_violated_property_classes=(PropertyClass.AUTHORIZATION,),
        risk_class=MutationRiskClass.CRITICAL_SECURITY,
        likely_equivalent_conditions=("public_endpoint",),
        syntactic_transformation="bypass",
        scope_limits=ScopeLimits(
            max_files=1,
            max_symbols=1,
            max_span_lines=8,
            allow_cross_module=False,
            allow_verifier_mutation=False,
        ),
        rollback=RollbackDeclaration(
            strategy=RollbackStrategy.WORKTREE_DISCARD,
            requires_clean_worktree=True,
            preserves_production=True,
        ),
        required_sandbox=SandboxRequirement(
            mode=SandboxMode.DISPOSABLE_WORKTREE,
            network_disabled=True,
            production_credentials_forbidden=True,
            disposable_worktree_required=True,
        ),
        max_mutants_per_target=2,
        deterministic=True,
    )
    with pytest.raises(ControlFlowError, match="control_flow"):
        assert_control_flow_operator_defaults(wrong)


# ---------------------------------------------------------------------------
# Normative catalogue coverage
# ---------------------------------------------------------------------------


def test_normative_specs_cover_every_required_family() -> None:
    specs = control_flow_operator_specs()
    families = {spec.family for spec in specs}
    assert families == REQUIRED_CONTROL_FLOW_FAMILIES
    assert ControlFlowFamily.INVERSION.value in families
    assert ControlFlowFamily.BRANCH_REMOVAL.value in families
    assert ControlFlowFamily.BOUNDARY_SHIFT.value in families
    assert ControlFlowFamily.RECOVERY_OBLIGATION_EARLY_RETURN.value in families
    assert ControlFlowFamily.LOOP_TERMINATION.value in families
    assert ControlFlowFamily.CANCELLATION.value in families


def test_every_spec_has_semantic_intent_and_equivalence_hints() -> None:
    for spec in control_flow_operator_specs():
        assert spec.semantic_intent.strip()
        assert len(spec.likely_equivalent_conditions) >= 1
        assert all(c.strip() for c in spec.likely_equivalent_conditions)
        assert spec.syntactic_transformation.strip()


def test_inversion_family_covers_conditional_and_loop_guard() -> None:
    specs = [
        s
        for s in control_flow_operator_specs()
        if s.family == ControlFlowFamily.INVERSION.value
    ]
    ids = {s.operator_id for s in specs}
    assert "cf_invert_conditional" in ids
    assert "cf_invert_loop_guard" in ids


def test_branch_removal_covers_remove_and_unconditional() -> None:
    specs = [
        s
        for s in control_flow_operator_specs()
        if s.family == ControlFlowFamily.BRANCH_REMOVAL.value
    ]
    ids = {s.operator_id for s in specs}
    assert "cf_remove_then_branch" in ids
    assert "cf_force_then_unconditional" in ids
    assert "cf_remove_else_branch" in ids


def test_boundary_shift_covers_comparison_edges() -> None:
    specs = [
        s
        for s in control_flow_operator_specs()
        if s.family == ControlFlowFamily.BOUNDARY_SHIFT.value
    ]
    ids = {s.operator_id for s in specs}
    assert "cf_boundary_lt_to_le" in ids
    assert "cf_boundary_le_to_lt" in ids
    assert "cf_boundary_gt_to_ge" in ids
    assert "cf_boundary_ge_to_gt" in ids


def test_recovery_obligation_early_return_family() -> None:
    specs = [
        s
        for s in control_flow_operator_specs()
        if s.family == ControlFlowFamily.RECOVERY_OBLIGATION_EARLY_RETURN.value
    ]
    ids = {s.operator_id for s in specs}
    assert "cf_early_return_before_recovery" in ids
    assert "cf_early_return_before_obligation" in ids
    for s in specs:
        props = {str(p.value if hasattr(p, "value") else p) for p in s.expected_violated_property_classes}
        # specs store enums; after post_init they remain as PropertyClass or str
        assert props  # nonempty


def test_loop_termination_family() -> None:
    specs = [
        s
        for s in control_flow_operator_specs()
        if s.family == ControlFlowFamily.LOOP_TERMINATION.value
    ]
    ids = {s.operator_id for s in specs}
    assert "cf_loop_break_early" in ids
    assert "cf_loop_skip_termination_check" in ids


def test_cancellation_family() -> None:
    specs = [
        s
        for s in control_flow_operator_specs()
        if s.family == ControlFlowFamily.CANCELLATION.value
    ]
    ids = {s.operator_id for s in specs}
    assert "cf_ignore_cancellation" in ids
    assert "cf_cancel_without_cleanup" in ids


def test_default_catalogue_is_complete_and_bounded() -> None:
    catalogue = default_control_flow_operators()
    assert catalogue.catalogue_id
    assert catalogue.to_dict()["interface_id"] == CONTROL_FLOW_OPERATORS_INTERFACE
    assert catalogue.to_dict()["schema"] == CONTROL_FLOW_OPERATORS_SCHEMA
    catalogue.assert_complete_coverage()
    assert set(catalogue.families()) == REQUIRED_CONTROL_FLOW_FAMILIES
    assert control_flow_families_covered() == REQUIRED_CONTROL_FLOW_FAMILIES
    for operator in catalogue:
        assert operator.definition.operator_class == OperatorClass.CONTROL_FLOW.value
        assert operator.definition.deterministic is True
        assert operator.family in REQUIRED_CONTROL_FLOW_FAMILIES
        assert operator.definition.semantic_intent
        assert operator.definition.likely_equivalent_conditions
        assert_control_flow_operator_defaults(operator.definition)


def test_expected_operator_ids_present() -> None:
    ids = set(default_control_flow_operators().operator_ids())
    expected = {
        "cf_invert_conditional",
        "cf_invert_loop_guard",
        "cf_remove_then_branch",
        "cf_force_then_unconditional",
        "cf_remove_else_branch",
        "cf_boundary_lt_to_le",
        "cf_boundary_le_to_lt",
        "cf_boundary_gt_to_ge",
        "cf_boundary_ge_to_gt",
        "cf_early_return_before_recovery",
        "cf_early_return_before_obligation",
        "cf_loop_break_early",
        "cf_loop_skip_termination_check",
        "cf_ignore_cancellation",
        "cf_cancel_without_cleanup",
    }
    assert expected <= ids


def test_catalogue_identity_is_deterministic() -> None:
    left = default_control_flow_operators()
    right = default_control_flow_operators()
    assert left.catalogue_id == right.catalogue_id
    assert left.operator_cids() == right.operator_cids()
    assert left.identity_payload() == right.identity_payload()


def test_catalogue_round_trip_preserves_identity() -> None:
    original = default_control_flow_operators()
    restored = ControlFlowMutationOperators.from_dict(original.to_dict())
    assert restored.catalogue_id == original.catalogue_id
    assert restored.operator_ids() == original.operator_ids()
    assert restored.operator_cids() == original.operator_cids()
    assert set(restored.families()) == set(original.families())


def test_definitions_helper_matches_catalogue() -> None:
    defs = control_flow_operator_definitions()
    catalogue = default_control_flow_operators()
    assert [d.operator_cid for d in defs] == list(catalogue.operator_cids())
    assert all(d.operator_class == OperatorClass.CONTROL_FLOW.value for d in defs)


# ---------------------------------------------------------------------------
# Lookup, target support, rollback
# ---------------------------------------------------------------------------


def test_get_and_get_by_cid() -> None:
    catalogue = default_control_flow_operators()
    op = catalogue.get("cf_invert_conditional")
    assert op.family == ControlFlowFamily.INVERSION.value
    by_cid = catalogue.get_by_cid(op.operator_cid)
    assert by_cid.operator_id == op.operator_id
    assert "cf_invert_conditional" in catalogue
    assert op.operator_cid in catalogue
    with pytest.raises(ControlFlowError, match="unknown operator_id"):
        catalogue.get("cf_does_not_exist")
    with pytest.raises(ControlFlowError, match="unknown operator_cid"):
        catalogue.get_by_cid(_cid("missing-operator"))


def test_operators_for_family_and_target() -> None:
    catalogue = default_control_flow_operators()
    boundary_ops = catalogue.operators_for_family(ControlFlowFamily.BOUNDARY_SHIFT)
    assert len(boundary_ops) == 4
    assert {op.operator_id for op in boundary_ops} == {
        "cf_boundary_lt_to_le",
        "cf_boundary_le_to_lt",
        "cf_boundary_gt_to_ge",
        "cf_boundary_ge_to_gt",
    }

    target = _target()
    supporting = catalogue.operators_for_target(target)
    assert len(supporting) == len(catalogue)
    assert all(op.supports_target(target) for op in supporting)

    unsupported = catalogue.operators_for_target(_target(language="cobol"))
    assert unsupported == ()


def test_rollback_record_is_deterministic() -> None:
    catalogue = default_control_flow_operators()
    target = _target()
    pre = _cid("pre-mutation-cf")
    first = catalogue.rollback_record(
        "cf_loop_break_early",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    second = catalogue.rollback_record(
        "cf_loop_break_early",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    assert isinstance(first, OperatorRollbackRecord)
    assert first.record_cid == second.record_cid
    assert first.preserves_production is True
    assert first.requires_clean_worktree is True
    assert first.operator_id == "cf_loop_break_early"


def test_rollback_record_fails_closed_for_unsupported_target() -> None:
    catalogue = default_control_flow_operators()
    with pytest.raises(Exception, match="does not support|language|artifact"):
        catalogue.rollback_record(
            "cf_invert_conditional",
            pre_mutation_state_cid=_cid("pre"),
            target=_target(language="cobol"),
        )


# ---------------------------------------------------------------------------
# Registry projection
# ---------------------------------------------------------------------------


def test_as_registry_admits_all_operators() -> None:
    catalogue = default_control_flow_operators()
    registry = catalogue.as_registry()
    assert len(registry) == len(catalogue)
    for operator_id in catalogue.operator_ids():
        admitted = registry.get(operator_id)
        assert admitted.operator_class == OperatorClass.CONTROL_FLOW.value


def test_register_into_builder() -> None:
    catalogue = default_control_flow_operators()
    builder = MutationOperatorRegistryBuilder()
    sealed = catalogue.register_into(builder)
    assert len(sealed) == len(catalogue)
    registry = builder.build()
    assert set(registry.operator_ids()) == set(catalogue.operator_ids())


def test_registry_dispatch_for_control_flow_target() -> None:
    catalogue = default_control_flow_operators()
    registry = catalogue.as_registry()
    target = _target()
    matches = registry.dispatch(
        target, operator_class=OperatorClass.CONTROL_FLOW
    )
    assert len(matches) == len(catalogue)
    one = registry.dispatch_one(
        target,
        operator_id="cf_ignore_cancellation",
        operator_class=OperatorClass.CONTROL_FLOW,
    )
    assert one.operator_id == "cf_ignore_cancellation"
    assert PropertyClass.CANCELLATION.value in one.expected_violated_property_classes


# ---------------------------------------------------------------------------
# Coverage / negative assembly
# ---------------------------------------------------------------------------


def test_incomplete_catalogue_rejected() -> None:
    invert_only = _minimal_spec()
    with pytest.raises(ControlFlowCoverageError, match="missing required families"):
        build_control_flow_operators([invert_only])

    sealed = build_control_flow_operator(invert_only)
    handle = ControlFlowOperator(
        _definition=sealed,
        family=ControlFlowFamily.INVERSION.value,
        spec_operator_id="cf_invert_conditional",
    )
    with pytest.raises(ControlFlowCoverageError, match="missing required families"):
        ControlFlowMutationOperators(operators=(handle,))


def test_duplicate_operator_id_rejected() -> None:
    specs = list(control_flow_operator_specs())
    specs.append(
        ControlFlowOperatorSpec(
            operator_id="cf_invert_conditional",
            family=ControlFlowFamily.INVERSION,
            semantic_intent="Duplicate id must fail",
            syntactic_transformation="negate_conditional_predicate_v2",
            expected_violated_property_classes=(PropertyClass.CONTROL_INVARIANT,),
            likely_equivalent_conditions=("dead_guard",),
        )
    )
    with pytest.raises(ControlFlowError, match="duplicate operator_id"):
        build_control_flow_operators(specs)


def test_from_dict_rejects_unknown_fields() -> None:
    payload = default_control_flow_operators().to_dict()
    payload["unexpected_field"] = True
    with pytest.raises(ControlFlowError, match="unknown fields"):
        ControlFlowMutationOperators.from_dict(payload)


def test_from_dict_rejects_schema_mismatch() -> None:
    payload = default_control_flow_operators().to_dict()
    payload["schema"] = "wrong-schema@1"
    with pytest.raises(ControlFlowError, match="unsupported .* schema"):
        ControlFlowMutationOperators.from_dict(payload)


def test_operator_handle_rejects_family_metadata_mismatch() -> None:
    definition = build_control_flow_operator(_minimal_spec())
    with pytest.raises(ControlFlowError, match="does not match"):
        ControlFlowOperator(
            _definition=definition,
            family=ControlFlowFamily.CANCELLATION.value,
            spec_operator_id="cf_invert_conditional",
        )


def test_declaration_backed_projection() -> None:
    catalogue = default_control_flow_operators()
    handle = catalogue.get("cf_boundary_lt_to_le")
    backed = handle.as_declaration_backed()
    assert backed.operator_cid == handle.operator_cid
    assert backed.supports_target(_target()) is True


def test_catalogue_identity_matches_content_address() -> None:
    catalogue = default_control_flow_operators()
    recomputed = cid_for_structured(
        catalogue._identity_payload_without_catalogue_id()  # noqa: SLF001
    )
    assert recomputed == catalogue.catalogue_id


def test_all_operators_expect_control_related_properties() -> None:
    allowed = {
        PropertyClass.CONTROL_INVARIANT.value,
        PropertyClass.SIDE_EFFECT_OBLIGATION.value,
        PropertyClass.ERROR_HANDLING.value,
        PropertyClass.CANCELLATION.value,
        PropertyClass.STATE_TRANSITION.value,
        PropertyClass.COMPENSATION.value,
    }
    for definition in control_flow_operator_definitions():
        props = set(definition.expected_violated_property_classes)
        assert props & allowed
        assert definition.likely_equivalent_conditions


def test_cancellation_operators_expect_cancellation_property() -> None:
    catalogue = default_control_flow_operators()
    for op in catalogue.operators_for_family(ControlFlowFamily.CANCELLATION):
        assert (
            PropertyClass.CANCELLATION.value
            in op.definition.expected_violated_property_classes
        )


def test_sandbox_and_scope_are_tight() -> None:
    for definition in control_flow_operator_definitions():
        assert definition.scope_limits.allow_verifier_mutation is False
        assert definition.scope_limits.allow_cross_module is False
        assert definition.scope_limits.max_files == 1
        assert definition.max_mutants_per_target <= 8
        assert definition.required_sandbox.disposable_worktree_required is True


def test_recovery_operators_expect_obligation_or_error_handling() -> None:
    catalogue = default_control_flow_operators()
    for op in catalogue.operators_for_family(
        ControlFlowFamily.RECOVERY_OBLIGATION_EARLY_RETURN
    ):
        props = set(op.definition.expected_violated_property_classes)
        assert props & {
            PropertyClass.SIDE_EFFECT_OBLIGATION.value,
            PropertyClass.ERROR_HANDLING.value,
            PropertyClass.CONTROL_INVARIANT.value,
        }
