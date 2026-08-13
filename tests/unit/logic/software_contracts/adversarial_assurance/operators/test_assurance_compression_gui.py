"""Unit tests for AssuranceCompressionGuiMutationOperators@1 (AAE-020)."""

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
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.assurance_compression_gui import (
    ASSURANCE_COMPRESSION_GUI_OPERATORS_INTERFACE,
    ASSURANCE_COMPRESSION_GUI_OPERATORS_SCHEMA,
    DEFAULT_ASSURANCE_RISK_CLASS,
    DEFAULT_PROOF_RISK_CLASS,
    FORBIDDEN_VISUAL_MUTATION_TOKENS,
    OWNED_OPERATOR_CLASSES,
    REQUIRED_ASSURANCE_COMPRESSION_GUI_FAMILIES,
    AssuranceCompressionGuiClassError,
    AssuranceCompressionGuiCoverageError,
    AssuranceCompressionGuiError,
    AssuranceCompressionGuiFamily,
    AssuranceCompressionGuiMutationOperators,
    AssuranceCompressionGuiOperator,
    AssuranceCompressionGuiOperatorSpec,
    AssuranceCompressionGuiVisualMutationError,
    assert_assurance_compression_gui_defaults,
    assert_no_broad_visual_mutation,
    assurance_compression_gui_families_covered,
    assurance_compression_gui_operator_definitions,
    assurance_compression_gui_operator_specs,
    build_assurance_compression_gui_operator,
    build_assurance_compression_gui_operators,
    default_assurance_compression_gui_operators,
    visual_mutation_operators_present,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.base import (
    OperatorRollbackRecord,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.registry import (
    MutationOperatorRegistryBuilder,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _target(**overrides: object) -> MutationTarget:
    fields = {
        "target_id": "test_module_fn",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state-acg"),
        "symbol_ids": ("tests.test_feature",),
        "artifact_cids": (_cid("artifact-acg"),),
        "language": "python",
        "artifact_type": "test_module",
        "prerequisites": ("parsed_ast", "symbol_table"),
        "risk_class": MutationRiskClass.HIGH,
        "risk_weight_bp": 7_000,
        "capsule_cids": (_cid("capsule-acg"),),
        "proof_unit_cids": (_cid("proof-acg"),),
        "source_path": "tests/test_feature.py",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationTarget(**fields)  # type: ignore[arg-type]


def _gui_target(**overrides: object) -> MutationTarget:
    fields = {
        "target_id": "gui_action_save",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state-gui"),
        "symbol_ids": ("gui.actions.save",),
        "artifact_cids": (_cid("artifact-gui"),),
        "language": "typescript",
        "artifact_type": "gui_optimizer_artifact",
        "prerequisites": (
            "parsed_ast",
            "symbol_table",
            "canonical_gui_optimizer_artifact",
        ),
        "risk_class": MutationRiskClass.HIGH,
        "risk_weight_bp": 8_000,
        "capsule_cids": (),
        "proof_unit_cids": (),
        "source_path": "gui/actions/save.ts",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationTarget(**fields)  # type: ignore[arg-type]


def _capsule_target(**overrides: object) -> MutationTarget:
    fields = {
        "target_id": "semantic_capsule_main",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state-sc"),
        "symbol_ids": ("capsule.main",),
        "artifact_cids": (_cid("artifact-sc"),),
        "language": "python",
        "artifact_type": "semantic_capsule",
        "prerequisites": ("parsed_ast", "symbol_table"),
        "risk_class": MutationRiskClass.HIGH,
        "risk_weight_bp": 7_500,
        "capsule_cids": (_cid("capsule-sc"),),
        "proof_unit_cids": (),
        "source_path": "capsules/main.json",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationTarget(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Spec construction and visual-mutation rejection
# ---------------------------------------------------------------------------


def test_owned_classes_and_defaults() -> None:
    assert OperatorClass.TEST_PROOF.value in OWNED_OPERATOR_CLASSES
    assert OperatorClass.SEMANTIC_COMPRESSION.value in OWNED_OPERATOR_CLASSES
    assert OperatorClass.GUI_ACTION_BINDING.value in OWNED_OPERATOR_CLASSES
    assert OperatorClass.AUTHORIZATION_POLICY.value not in OWNED_OPERATOR_CLASSES
    assert DEFAULT_ASSURANCE_RISK_CLASS == MutationRiskClass.HIGH.value
    assert DEFAULT_PROOF_RISK_CLASS == MutationRiskClass.PROOF_RECEIPT_TRUST.value
    assert "visual" in FORBIDDEN_VISUAL_MUTATION_TOKENS
    assert "css" in FORBIDDEN_VISUAL_MUTATION_TOKENS
    assert "layout" in FORBIDDEN_VISUAL_MUTATION_TOKENS


def test_spec_rejects_unknown_family() -> None:
    with pytest.raises(
        AssuranceCompressionGuiError,
        match="unsupported assurance/compression/GUI family",
    ):
        AssuranceCompressionGuiOperatorSpec(
            operator_id="acg_unknown_family",
            family="not_a_family",
            semantic_intent="Unknown family must fail closed",
            syntactic_transformation="noop",
            expected_violated_property_classes=(PropertyClass.TEST_ADEQUACY,),
        )


def test_spec_rejects_family_class_mismatch() -> None:
    with pytest.raises(AssuranceCompressionGuiClassError, match="requires operator_class"):
        AssuranceCompressionGuiOperatorSpec(
            operator_id="acg_class_mismatch",
            family=AssuranceCompressionGuiFamily.WEAK_TEST,
            operator_class=OperatorClass.GUI_ACTION_BINDING,
            semantic_intent="Weak test under wrong class",
            syntactic_transformation="weaken_assert",
            expected_violated_property_classes=(PropertyClass.TEST_ADEQUACY,),
        )


def test_spec_rejects_visual_syntactic_transformation() -> None:
    with pytest.raises(
        AssuranceCompressionGuiVisualMutationError,
        match="forbidden broad visual mutation",
    ):
        AssuranceCompressionGuiOperatorSpec(
            operator_id="gui_change_button_color",
            family=AssuranceCompressionGuiFamily.GUI_DISPATCHABILITY,
            semantic_intent="Alter button presentation only",
            syntactic_transformation="mutate_css_color_and_layout_tokens",
            expected_violated_property_classes=(PropertyClass.GUI_ACTION_BINDING,),
        )


def test_spec_rejects_pixel_rendering_tokens() -> None:
    with pytest.raises(AssuranceCompressionGuiVisualMutationError, match="pixel"):
        AssuranceCompressionGuiOperatorSpec(
            operator_id="gui_pixel_shift",
            family=AssuranceCompressionGuiFamily.GUI_HANDLER,
            semantic_intent="Shift pixels for cosmetic effect",
            syntactic_transformation="shift_pixel_offset_for_icon",
            expected_violated_property_classes=(PropertyClass.GUI_ACTION_BINDING,),
        )


def test_build_test_operator_seals_with_test_proof_class() -> None:
    spec = AssuranceCompressionGuiOperatorSpec(
        operator_id="test_weaken_assertion",
        family=AssuranceCompressionGuiFamily.WEAK_TEST,
        semantic_intent="Weaken assertion",
        syntactic_transformation="replace_behavioral_assert_with_tautology_or_type_only",
        expected_violated_property_classes=(PropertyClass.TEST_ADEQUACY,),
    )
    sealed = build_assurance_compression_gui_operator(spec)
    assert sealed.operator_class == OperatorClass.TEST_PROOF.value
    assert sealed.deterministic is True
    assert sealed.required_sandbox.network_disabled is True
    assert sealed.required_sandbox.production_credentials_forbidden is True
    assert sealed.rollback.preserves_production is True
    assert sealed.metadata["assurance_family"] == "weak_test"
    assert sealed.metadata["visual_mutation_allowed"] is False
    assert_assurance_compression_gui_defaults(sealed)
    assert_no_broad_visual_mutation(sealed)


def test_build_gui_operator_requires_canonical_prerequisite() -> None:
    sealed = build_assurance_compression_gui_operator(
        AssuranceCompressionGuiOperatorSpec(
            operator_id="gui_break_dispatchability",
            family=AssuranceCompressionGuiFamily.GUI_DISPATCHABILITY,
            semantic_intent="Break dispatchability",
            syntactic_transformation="unlink_action_id_from_declared_dispatch_target",
            expected_violated_property_classes=(PropertyClass.GUI_ACTION_BINDING,),
        )
    )
    assert sealed.operator_class == OperatorClass.GUI_ACTION_BINDING.value
    assert "canonical_gui_optimizer_artifact" in sealed.target_prerequisites
    assert PropertyClass.GUI_ACTION_BINDING.value in (
        sealed.expected_violated_property_classes
    )


def test_assert_defaults_reject_wrong_operator_class() -> None:
    wrong = MutationOperatorDefinition(
        operator_id="control_flow_invert",
        operator_version="1",
        operator_class=OperatorClass.CONTROL_FLOW,
        supported_languages=("python",),
        supported_artifact_types=("source_module",),
        target_prerequisites=("parsed_ast",),
        semantic_intent="Not an assurance operator",
        expected_violated_property_classes=(PropertyClass.CONTROL_INVARIANT,),
        risk_class=MutationRiskClass.HIGH,
        likely_equivalent_conditions=(),
        syntactic_transformation="invert",
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
        metadata={"visual_mutation_allowed": False},
    )
    with pytest.raises(AssuranceCompressionGuiClassError, match="operator_class"):
        assert_assurance_compression_gui_defaults(wrong)


# ---------------------------------------------------------------------------
# Normative catalogue coverage
# ---------------------------------------------------------------------------


def test_normative_specs_cover_every_required_family() -> None:
    specs = assurance_compression_gui_operator_specs()
    families = {spec.family for spec in specs}
    assert families == REQUIRED_ASSURANCE_COMPRESSION_GUI_FAMILIES
    # Acceptance-critical families
    assert AssuranceCompressionGuiFamily.WEAK_TEST.value in families
    assert AssuranceCompressionGuiFamily.DELETED_TEST.value in families
    assert AssuranceCompressionGuiFamily.SKIPPED_TEST.value in families
    assert AssuranceCompressionGuiFamily.FIXTURE.value in families
    assert AssuranceCompressionGuiFamily.VACUOUS_PROOF.value in families
    assert AssuranceCompressionGuiFamily.STALE_PROOF.value in families
    assert AssuranceCompressionGuiFamily.INCOMPLETE_PROOF.value in families
    assert AssuranceCompressionGuiFamily.CAPSULE_OMISSION.value in families
    assert AssuranceCompressionGuiFamily.DEPENDENCY_OMISSION.value in families
    assert AssuranceCompressionGuiFamily.CONTEXT_OMISSION.value in families
    assert AssuranceCompressionGuiFamily.GUI_DISPATCHABILITY.value in families
    assert AssuranceCompressionGuiFamily.GUI_KEYBOARD_ACCESSIBILITY.value in families


def test_test_proof_families_cover_weak_deleted_skipped_fixtures_and_proofs() -> None:
    by_family = {
        family: [
            s
            for s in assurance_compression_gui_operator_specs()
            if s.family == family
        ]
        for family in (
            AssuranceCompressionGuiFamily.WEAK_TEST.value,
            AssuranceCompressionGuiFamily.DELETED_TEST.value,
            AssuranceCompressionGuiFamily.SKIPPED_TEST.value,
            AssuranceCompressionGuiFamily.FIXTURE.value,
            AssuranceCompressionGuiFamily.VACUOUS_PROOF.value,
            AssuranceCompressionGuiFamily.STALE_PROOF.value,
            AssuranceCompressionGuiFamily.INCOMPLETE_PROOF.value,
        )
    }
    assert "test_weaken_assertion" in {
        s.operator_id for s in by_family[AssuranceCompressionGuiFamily.WEAK_TEST.value]
    }
    assert "test_delete_test_case" in {
        s.operator_id
        for s in by_family[AssuranceCompressionGuiFamily.DELETED_TEST.value]
    }
    assert "test_permanent_skip" in {
        s.operator_id
        for s in by_family[AssuranceCompressionGuiFamily.SKIPPED_TEST.value]
    }
    fixture_ids = {
        s.operator_id for s in by_family[AssuranceCompressionGuiFamily.FIXTURE.value]
    }
    assert "test_bypass_fixture" in fixture_ids
    assert "test_fixture_conceals_behavior" in fixture_ids
    vacuous_ids = {
        s.operator_id
        for s in by_family[AssuranceCompressionGuiFamily.VACUOUS_PROOF.value]
    }
    assert "proof_vacuous_impossible_assumption" in vacuous_ids
    assert "proof_unreachable_modeled_state" in vacuous_ids
    assert "proof_stale_receipt" in {
        s.operator_id
        for s in by_family[AssuranceCompressionGuiFamily.STALE_PROOF.value]
    }
    incomplete_ids = {
        s.operator_id
        for s in by_family[AssuranceCompressionGuiFamily.INCOMPLETE_PROOF.value]
    }
    assert "proof_omit_unit" in incomplete_ids
    assert "proof_unchecked_signature" in incomplete_ids


def test_semantic_compression_covers_capsule_dependency_context() -> None:
    specs = assurance_compression_gui_operator_specs()
    capsule_ids = {
        s.operator_id
        for s in specs
        if s.family == AssuranceCompressionGuiFamily.CAPSULE_OMISSION.value
    }
    dep_ids = {
        s.operator_id
        for s in specs
        if s.family == AssuranceCompressionGuiFamily.DEPENDENCY_OMISSION.value
    }
    ctx_ids = {
        s.operator_id
        for s in specs
        if s.family == AssuranceCompressionGuiFamily.CONTEXT_OMISSION.value
    }
    assert "sc_stale_or_wrong_root_capsule" in capsule_ids
    assert "sc_heuristic_or_opaque_as_exact" in capsule_ids
    assert "sc_omit_dependency_edge" in dep_ids
    assert "sc_omit_config_or_exception" in dep_ids
    assert "sc_omit_fixture_or_effect_context" in ctx_ids
    assert "sc_selection_miss" in ctx_ids


def test_gui_families_are_canonical_action_bindings_only() -> None:
    specs = [
        s
        for s in assurance_compression_gui_operator_specs()
        if str(s.operator_class) == OperatorClass.GUI_ACTION_BINDING.value
    ]
    assert len(specs) >= 7
    ids = {s.operator_id for s in specs}
    expected = {
        "gui_break_dispatchability",
        "gui_omit_confirmation",
        "gui_wrong_handler",
        "gui_stale_action_policy",
        "gui_broken_recovery",
        "gui_early_success_before_effect",
        "gui_drop_critical_keyboard_access",
    }
    assert expected <= ids
    for spec in specs:
        assert "visual" not in spec.syntactic_transformation.lower()
        assert "css" not in spec.syntactic_transformation.lower()
        assert "layout" not in spec.syntactic_transformation.lower()
        assert "pixel" not in spec.syntactic_transformation.lower()
        assert spec.metadata["visual_mutation_allowed"] is False


def test_default_catalogue_is_complete_and_visual_free() -> None:
    catalogue = default_assurance_compression_gui_operators()
    assert catalogue.catalogue_id
    assert (
        catalogue.to_dict()["interface_id"]
        == ASSURANCE_COMPRESSION_GUI_OPERATORS_INTERFACE
    )
    assert catalogue.to_dict()["schema"] == ASSURANCE_COMPRESSION_GUI_OPERATORS_SCHEMA
    catalogue.assert_complete_coverage()
    catalogue.assert_visual_mutation_absent()
    assert set(catalogue.families()) == REQUIRED_ASSURANCE_COMPRESSION_GUI_FAMILIES
    assert (
        assurance_compression_gui_families_covered()
        == REQUIRED_ASSURANCE_COMPRESSION_GUI_FAMILIES
    )
    assert set(catalogue.operator_classes()) == OWNED_OPERATOR_CLASSES
    assert visual_mutation_operators_present(catalogue) is False
    for operator in catalogue:
        assert operator.definition.operator_class in OWNED_OPERATOR_CLASSES
        assert operator.definition.deterministic is True
        assert operator.family in REQUIRED_ASSURANCE_COMPRESSION_GUI_FAMILIES
        assert operator.definition.metadata["visual_mutation_allowed"] is False
        assert_assurance_compression_gui_defaults(operator.definition)


def test_expected_operator_ids_present() -> None:
    ids = set(default_assurance_compression_gui_operators().operator_ids())
    expected = {
        "test_weaken_assertion",
        "test_delete_test_case",
        "test_permanent_skip",
        "test_bypass_fixture",
        "test_fixture_conceals_behavior",
        "proof_vacuous_impossible_assumption",
        "proof_unreachable_modeled_state",
        "proof_stale_receipt",
        "proof_omit_unit",
        "proof_unchecked_signature",
        "sc_stale_or_wrong_root_capsule",
        "sc_heuristic_or_opaque_as_exact",
        "sc_omit_dependency_edge",
        "sc_omit_config_or_exception",
        "sc_omit_fixture_or_effect_context",
        "sc_selection_miss",
        "gui_break_dispatchability",
        "gui_omit_confirmation",
        "gui_wrong_handler",
        "gui_stale_action_policy",
        "gui_broken_recovery",
        "gui_early_success_before_effect",
        "gui_drop_critical_keyboard_access",
    }
    assert expected <= ids


def test_proof_operators_use_proof_receipt_trust_risk() -> None:
    for spec in assurance_compression_gui_operator_specs():
        if spec.family in {
            AssuranceCompressionGuiFamily.VACUOUS_PROOF.value,
            AssuranceCompressionGuiFamily.STALE_PROOF.value,
            AssuranceCompressionGuiFamily.INCOMPLETE_PROOF.value,
        }:
            assert spec.risk_class == MutationRiskClass.PROOF_RECEIPT_TRUST.value


def test_catalogue_identity_is_deterministic() -> None:
    left = default_assurance_compression_gui_operators()
    right = default_assurance_compression_gui_operators()
    assert left.catalogue_id == right.catalogue_id
    assert left.operator_cids() == right.operator_cids()
    assert left.identity_payload() == right.identity_payload()


def test_catalogue_round_trip_preserves_identity() -> None:
    original = default_assurance_compression_gui_operators()
    restored = AssuranceCompressionGuiMutationOperators.from_dict(original.to_dict())
    assert restored.catalogue_id == original.catalogue_id
    assert restored.operator_ids() == original.operator_ids()
    assert restored.operator_cids() == original.operator_cids()
    assert set(restored.families()) == set(original.families())
    assert set(restored.operator_classes()) == set(original.operator_classes())


def test_definitions_helper_matches_catalogue() -> None:
    defs = assurance_compression_gui_operator_definitions()
    catalogue = default_assurance_compression_gui_operators()
    assert [d.operator_cid for d in defs] == list(catalogue.operator_cids())
    assert all(d.operator_class in OWNED_OPERATOR_CLASSES for d in defs)


# ---------------------------------------------------------------------------
# Lookup, target support, rollback
# ---------------------------------------------------------------------------


def test_get_and_get_by_cid() -> None:
    catalogue = default_assurance_compression_gui_operators()
    op = catalogue.get("test_weaken_assertion")
    assert op.family == AssuranceCompressionGuiFamily.WEAK_TEST.value
    assert op.operator_class == OperatorClass.TEST_PROOF.value
    by_cid = catalogue.get_by_cid(op.operator_cid)
    assert by_cid.operator_id == op.operator_id
    assert "test_weaken_assertion" in catalogue
    assert op.operator_cid in catalogue
    with pytest.raises(AssuranceCompressionGuiError, match="unknown operator_id"):
        catalogue.get("acg_does_not_exist")
    with pytest.raises(AssuranceCompressionGuiError, match="unknown operator_cid"):
        catalogue.get_by_cid(_cid("missing-operator"))


def test_operators_for_family_class_and_target() -> None:
    catalogue = default_assurance_compression_gui_operators()
    weak = catalogue.operators_for_family(AssuranceCompressionGuiFamily.WEAK_TEST)
    assert len(weak) == 1
    assert weak[0].operator_id == "test_weaken_assertion"

    test_ops = catalogue.operators_for_class(OperatorClass.TEST_PROOF)
    assert all(
        op.definition.operator_class == OperatorClass.TEST_PROOF.value
        for op in test_ops
    )
    gui_ops = catalogue.operators_for_class(OperatorClass.GUI_ACTION_BINDING)
    assert len(gui_ops) >= 7
    sc_ops = catalogue.operators_for_class(OperatorClass.SEMANTIC_COMPRESSION)
    assert len(sc_ops) >= 5

    test_target = _target()
    supporting_tests = catalogue.operators_for_target(test_target)
    assert all(op.supports_target(test_target) for op in supporting_tests)
    assert any(
        op.definition.operator_class == OperatorClass.TEST_PROOF.value
        for op in supporting_tests
    )

    gui_target = _gui_target()
    supporting_gui = catalogue.operators_for_target(gui_target)
    assert supporting_gui
    assert all(
        op.definition.operator_class == OperatorClass.GUI_ACTION_BINDING.value
        for op in supporting_gui
    )

    capsule_target = _capsule_target()
    supporting_sc = catalogue.operators_for_target(capsule_target)
    assert supporting_sc
    assert all(
        op.definition.operator_class == OperatorClass.SEMANTIC_COMPRESSION.value
        for op in supporting_sc
    )

    unsupported = catalogue.operators_for_target(_target(language="cobol"))
    assert unsupported == ()


def test_rollback_record_is_deterministic() -> None:
    catalogue = default_assurance_compression_gui_operators()
    target = _target()
    pre = _cid("pre-mutation-acg")
    first = catalogue.rollback_record(
        "test_delete_test_case",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    second = catalogue.rollback_record(
        "test_delete_test_case",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    assert isinstance(first, OperatorRollbackRecord)
    assert first.record_cid == second.record_cid
    assert first.preserves_production is True
    assert first.requires_clean_worktree is True
    assert first.operator_id == "test_delete_test_case"


def test_rollback_record_fails_closed_for_unsupported_target() -> None:
    catalogue = default_assurance_compression_gui_operators()
    with pytest.raises(Exception, match="does not support|language|artifact"):
        catalogue.rollback_record(
            "gui_break_dispatchability",
            pre_mutation_state_cid=_cid("pre"),
            target=_target(language="cobol"),
        )


# ---------------------------------------------------------------------------
# Registry projection
# ---------------------------------------------------------------------------


def test_as_registry_admits_all_operators() -> None:
    catalogue = default_assurance_compression_gui_operators()
    registry = catalogue.as_registry()
    assert len(registry) == len(catalogue)
    for operator_id in catalogue.operator_ids():
        admitted = registry.get(operator_id)
        assert admitted.operator_class in OWNED_OPERATOR_CLASSES


def test_register_into_builder() -> None:
    catalogue = default_assurance_compression_gui_operators()
    builder = MutationOperatorRegistryBuilder()
    sealed = catalogue.register_into(builder)
    assert len(sealed) == len(catalogue)
    registry = builder.build()
    assert set(registry.operator_ids()) == set(catalogue.operator_ids())


def test_registry_dispatch_for_each_owned_class() -> None:
    catalogue = default_assurance_compression_gui_operators()
    registry = catalogue.as_registry()

    test_matches = registry.dispatch(
        _target(), operator_class=OperatorClass.TEST_PROOF
    )
    assert test_matches
    assert all(m.operator_class == OperatorClass.TEST_PROOF.value for m in test_matches)

    sc_matches = registry.dispatch(
        _capsule_target(), operator_class=OperatorClass.SEMANTIC_COMPRESSION
    )
    assert sc_matches
    assert all(
        m.operator_class == OperatorClass.SEMANTIC_COMPRESSION.value for m in sc_matches
    )

    gui_matches = registry.dispatch(
        _gui_target(), operator_class=OperatorClass.GUI_ACTION_BINDING
    )
    assert gui_matches
    assert all(
        m.operator_class == OperatorClass.GUI_ACTION_BINDING.value for m in gui_matches
    )

    one = registry.dispatch_one(
        _gui_target(),
        operator_id="gui_drop_critical_keyboard_access",
        operator_class=OperatorClass.GUI_ACTION_BINDING,
    )
    assert one.operator_id == "gui_drop_critical_keyboard_access"


# ---------------------------------------------------------------------------
# Coverage / negative assembly
# ---------------------------------------------------------------------------


def test_incomplete_catalogue_rejected() -> None:
    weak_only = AssuranceCompressionGuiOperatorSpec(
        operator_id="test_weaken_assertion",
        family=AssuranceCompressionGuiFamily.WEAK_TEST,
        semantic_intent="Only weak tests",
        syntactic_transformation="replace_behavioral_assert_with_tautology_or_type_only",
        expected_violated_property_classes=(PropertyClass.TEST_ADEQUACY,),
    )
    with pytest.raises(
        AssuranceCompressionGuiCoverageError, match="missing required families"
    ):
        build_assurance_compression_gui_operators([weak_only])

    sealed = build_assurance_compression_gui_operator(weak_only)
    handle = AssuranceCompressionGuiOperator(
        _definition=sealed,
        family=AssuranceCompressionGuiFamily.WEAK_TEST.value,
        spec_operator_id="test_weaken_assertion",
    )
    with pytest.raises(
        AssuranceCompressionGuiCoverageError, match="missing required families"
    ):
        AssuranceCompressionGuiMutationOperators(operators=(handle,))


def test_duplicate_operator_id_rejected() -> None:
    specs = list(assurance_compression_gui_operator_specs())
    specs.append(
        AssuranceCompressionGuiOperatorSpec(
            operator_id="test_weaken_assertion",
            family=AssuranceCompressionGuiFamily.WEAK_TEST,
            semantic_intent="Duplicate id must fail",
            syntactic_transformation="replace_behavioral_assert_with_tautology_v2",
            expected_violated_property_classes=(PropertyClass.TEST_ADEQUACY,),
        )
    )
    with pytest.raises(AssuranceCompressionGuiError, match="duplicate operator_id"):
        build_assurance_compression_gui_operators(specs)


def test_from_dict_rejects_unknown_fields() -> None:
    payload = default_assurance_compression_gui_operators().to_dict()
    payload["unexpected_field"] = True
    with pytest.raises(AssuranceCompressionGuiError, match="unknown fields"):
        AssuranceCompressionGuiMutationOperators.from_dict(payload)


def test_from_dict_rejects_schema_mismatch() -> None:
    payload = default_assurance_compression_gui_operators().to_dict()
    payload["schema"] = "wrong-schema@1"
    with pytest.raises(AssuranceCompressionGuiError, match="unsupported .* schema"):
        AssuranceCompressionGuiMutationOperators.from_dict(payload)


def test_operator_handle_rejects_family_metadata_mismatch() -> None:
    definition = build_assurance_compression_gui_operator(
        AssuranceCompressionGuiOperatorSpec(
            operator_id="test_weaken_assertion",
            family=AssuranceCompressionGuiFamily.WEAK_TEST,
            semantic_intent="Weaken assertion",
            syntactic_transformation="replace_behavioral_assert_with_tautology_or_type_only",
            expected_violated_property_classes=(PropertyClass.TEST_ADEQUACY,),
        )
    )
    with pytest.raises(AssuranceCompressionGuiError, match="does not match"):
        AssuranceCompressionGuiOperator(
            _definition=definition,
            family=AssuranceCompressionGuiFamily.DELETED_TEST.value,
            spec_operator_id="test_weaken_assertion",
        )


def test_declaration_backed_projection() -> None:
    catalogue = default_assurance_compression_gui_operators()
    handle = catalogue.get("sc_omit_dependency_edge")
    backed = handle.as_declaration_backed()
    assert backed.operator_cid == handle.operator_cid
    assert backed.supports_target(_capsule_target()) is True


def test_catalogue_identity_matches_content_address() -> None:
    catalogue = default_assurance_compression_gui_operators()
    recomputed = cid_for_structured(
        catalogue._identity_payload_without_catalogue_id()  # noqa: SLF001
    )
    assert recomputed == catalogue.catalogue_id


def test_property_classes_match_operator_classes() -> None:
    for definition in assurance_compression_gui_operator_definitions():
        props = set(definition.expected_violated_property_classes)
        if definition.operator_class == OperatorClass.TEST_PROOF.value:
            assert props & {
                PropertyClass.TEST_ADEQUACY.value,
                PropertyClass.PROOF_ADEQUACY.value,
                PropertyClass.RECEIPT_AUTHENTICITY.value,
            }
        elif definition.operator_class == OperatorClass.SEMANTIC_COMPRESSION.value:
            assert props & {
                PropertyClass.CAPSULE_COMPLETENESS.value,
                PropertyClass.DATA_INTEGRITY.value,
            }
        elif definition.operator_class == OperatorClass.GUI_ACTION_BINDING.value:
            assert PropertyClass.GUI_ACTION_BINDING.value in props
        else:
            pytest.fail(f"unexpected class {definition.operator_class}")


def test_sandbox_and_scope_are_tight() -> None:
    for definition in assurance_compression_gui_operator_definitions():
        assert definition.scope_limits.allow_verifier_mutation is False
        assert definition.scope_limits.allow_cross_module is False
        assert definition.scope_limits.max_files == 1
        assert definition.max_mutants_per_target <= 8
        assert definition.required_sandbox.disposable_worktree_required is True
        assert definition.deterministic is True


def test_broad_visual_mutation_is_absent_from_entire_catalogue() -> None:
    catalogue = default_assurance_compression_gui_operators()
    for operator in catalogue:
        text = " ".join(
            [
                operator.definition.syntactic_transformation,
                operator.definition.semantic_intent,
                operator.definition.notes or "",
            ]
        ).lower()
        # Syntactic transformations must never encode visual tokens.
        transform = operator.definition.syntactic_transformation.lower()
        for token in ("css", "pixel", "layout", "typography", "theme", "animation"):
            assert token not in transform
        assert operator.definition.metadata.get("visual_mutation_allowed") is False
        # Catalogue notes may mention absence; transformations must not.
        if "visual" in transform or "rendering" in transform:
            pytest.fail(
                f"operator {operator.operator_id} encodes visual mutation: {text!r}"
            )
    assert catalogue.metadata.get("visual_mutation_allowed") is False


def test_gui_operators_do_not_support_non_gui_artifacts() -> None:
    catalogue = default_assurance_compression_gui_operators()
    gui_ops = catalogue.operators_for_class(OperatorClass.GUI_ACTION_BINDING)
    plain_source = _target(
        artifact_type="source_module",
        prerequisites=("parsed_ast", "symbol_table"),
    )
    # source_module is listed, but prerequisites omit canonical GUI artifact.
    for op in gui_ops:
        assert op.supports_target(plain_source) is False
    assert catalogue.operators_for_target(plain_source)
    # GUI targets require the canonical prerequisite.
    for op in gui_ops:
        assert op.supports_target(_gui_target()) is True
