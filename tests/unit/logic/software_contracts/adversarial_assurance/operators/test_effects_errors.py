"""Unit tests for SideEffectErrorRetryMutationOperators@1 (AAE-017)."""

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
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.effects_errors import (
    ADMITTED_OPERATOR_CLASSES,
    DEFAULT_ERROR_RETRY_RISK_CLASS,
    DEFAULT_SIDE_EFFECT_RISK_CLASS,
    EFFECTS_ERRORS_OPERATORS_INTERFACE,
    EFFECTS_ERRORS_OPERATORS_SCHEMA,
    REQUIRED_EFFECTS_ERRORS_FAMILIES,
    REQUIRED_ERROR_RETRY_FAMILIES,
    REQUIRED_SIDE_EFFECT_FAMILIES,
    EffectsErrorsCoverageError,
    EffectsErrorsError,
    EffectsErrorsFamily,
    EffectsErrorsMutationOperators,
    EffectsErrorsOperator,
    EffectsErrorsOperatorSpec,
    SideEffectErrorRetryMutationOperators,
    assert_effects_errors_operator_defaults,
    build_effects_errors_operator,
    build_effects_errors_operators,
    default_effects_errors_operators,
    effects_errors_families_covered,
    effects_errors_operator_definitions,
    effects_errors_operator_specs,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.registry import (
    MutationOperatorRegistryBuilder,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _target(**overrides: object) -> MutationTarget:
    fields = {
        "target_id": "effects_gate_fn",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state-ee"),
        "symbol_ids": ("mod.effects_gate",),
        "artifact_cids": (_cid("artifact-ee"),),
        "language": "python",
        "artifact_type": "source_module",
        "prerequisites": ("parsed_ast", "symbol_table"),
        "risk_class": MutationRiskClass.HIGH,
        "risk_weight_bp": 7_000,
        "capsule_cids": (_cid("capsule-ee"),),
        "proof_unit_cids": (_cid("proof-ee"),),
        "source_path": "mod/effects_gate.py",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationTarget(**fields)  # type: ignore[arg-type]


def _minimal_spec(**overrides: object) -> EffectsErrorsOperatorSpec:
    fields: dict[str, object] = {
        "operator_id": "se_omit_required_write",
        "family": EffectsErrorsFamily.OMITTED_EFFECT,
        "semantic_intent": "Omit a required write",
        "syntactic_transformation": "remove_required_side_effect_call",
        "expected_violated_property_classes": (
            PropertyClass.SIDE_EFFECT_OBLIGATION,
        ),
        "likely_equivalent_conditions": (
            "write_is_already_satisfied_on_all_paths",
        ),
    }
    fields.update(overrides)
    return EffectsErrorsOperatorSpec(**fields)  # type: ignore[arg-type]


def _minimal_error_spec(**overrides: object) -> EffectsErrorsOperatorSpec:
    fields: dict[str, object] = {
        "operator_id": "er_swallow_exception",
        "family": EffectsErrorsFamily.SWALLOWED_FAILURE,
        "semantic_intent": "Swallow an exception",
        "syntactic_transformation": "replace_except_body_with_pass_or_continue",
        "expected_violated_property_classes": (PropertyClass.ERROR_HANDLING,),
        "likely_equivalent_conditions": ("exception_class_is_never_raised",),
    }
    fields.update(overrides)
    return EffectsErrorsOperatorSpec(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Spec validation and defaults
# ---------------------------------------------------------------------------


def test_default_risk_classes() -> None:
    assert DEFAULT_SIDE_EFFECT_RISK_CLASS == MutationRiskClass.HIGH.value
    assert (
        DEFAULT_ERROR_RETRY_RISK_CLASS
        == MutationRiskClass.CRITICAL_INVARIANT.value
    )


def test_interface_alias_matches_catalogue() -> None:
    assert SideEffectErrorRetryMutationOperators is EffectsErrorsMutationOperators
    assert (
        EFFECTS_ERRORS_OPERATORS_INTERFACE
        == "SideEffectErrorRetryMutationOperators@1"
    )


def test_spec_requires_equivalence_hints() -> None:
    with pytest.raises(EffectsErrorsError, match="equivalence hints"):
        EffectsErrorsOperatorSpec(
            operator_id="se_no_equiv",
            family=EffectsErrorsFamily.OMITTED_EFFECT,
            semantic_intent="Omit without hints",
            syntactic_transformation="remove_required_side_effect_call",
            expected_violated_property_classes=(
                PropertyClass.SIDE_EFFECT_OBLIGATION,
            ),
            likely_equivalent_conditions=(),
        )


def test_spec_rejects_unknown_family() -> None:
    with pytest.raises(
        EffectsErrorsError, match="unsupported side-effect/error-retry family"
    ):
        EffectsErrorsOperatorSpec(
            operator_id="se_unknown_family",
            family="not_a_family",
            semantic_intent="Unknown family must fail closed",
            syntactic_transformation="noop",
            expected_violated_property_classes=(
                PropertyClass.SIDE_EFFECT_OBLIGATION,
            ),
            likely_equivalent_conditions=("always_dead",),
        )


def test_spec_rejects_empty_semantic_intent() -> None:
    with pytest.raises(EffectsErrorsError, match="semantic_intent"):
        EffectsErrorsOperatorSpec(
            operator_id="se_empty_intent",
            family=EffectsErrorsFamily.OMITTED_EFFECT,
            semantic_intent="   ",
            syntactic_transformation="remove_required_side_effect_call",
            expected_violated_property_classes=(
                PropertyClass.SIDE_EFFECT_OBLIGATION,
            ),
            likely_equivalent_conditions=("x",),
        )


def test_spec_rejects_class_family_mismatch() -> None:
    with pytest.raises(EffectsErrorsError, match="requires operator_class"):
        EffectsErrorsOperatorSpec(
            operator_id="se_wrong_class",
            family=EffectsErrorsFamily.OMITTED_EFFECT,
            operator_class=OperatorClass.ERROR_RETRY,
            semantic_intent="Side-effect family cannot be error_retry class",
            syntactic_transformation="remove_required_side_effect_call",
            expected_violated_property_classes=(
                PropertyClass.SIDE_EFFECT_OBLIGATION,
            ),
            likely_equivalent_conditions=("x",),
        )


def test_build_side_effect_operator_seals() -> None:
    sealed = build_effects_errors_operator(_minimal_spec())
    assert sealed.operator_class == OperatorClass.SIDE_EFFECT.value
    assert sealed.risk_class == MutationRiskClass.HIGH.value
    assert sealed.deterministic is True
    assert sealed.required_sandbox.network_disabled is True
    assert sealed.required_sandbox.production_credentials_forbidden is True
    assert sealed.rollback.preserves_production is True
    assert sealed.metadata["ee_family"] == "omitted_effect"
    assert sealed.metadata["ee_operator_class"] == "side_effect"
    assert sealed.semantic_intent
    assert sealed.likely_equivalent_conditions
    assert_effects_errors_operator_defaults(sealed)


def test_build_error_retry_operator_seals() -> None:
    sealed = build_effects_errors_operator(_minimal_error_spec())
    assert sealed.operator_class == OperatorClass.ERROR_RETRY.value
    assert sealed.risk_class == MutationRiskClass.CRITICAL_INVARIANT.value
    assert sealed.metadata["ee_family"] == "swallowed_failure"
    assert_effects_errors_operator_defaults(sealed)


def test_assert_defaults_rejects_wrong_operator_class() -> None:
    wrong = MutationOperatorDefinition(
        operator_id="cf_invert_conditional",
        operator_version="1",
        operator_class=OperatorClass.CONTROL_FLOW,
        supported_languages=("python",),
        supported_artifact_types=("source_module",),
        target_prerequisites=("parsed_ast",),
        semantic_intent="Not a side-effect or error/retry operator",
        expected_violated_property_classes=(PropertyClass.CONTROL_INVARIANT,),
        risk_class=MutationRiskClass.CRITICAL_INVARIANT,
        likely_equivalent_conditions=("public_endpoint",),
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
    )
    with pytest.raises(EffectsErrorsError, match="side_effect or error_retry"):
        assert_effects_errors_operator_defaults(wrong)


# ---------------------------------------------------------------------------
# Normative catalogue coverage
# ---------------------------------------------------------------------------


def test_normative_specs_cover_every_required_family() -> None:
    specs = effects_errors_operator_specs()
    families = {spec.family for spec in specs}
    assert families == REQUIRED_EFFECTS_ERRORS_FAMILIES
    assert REQUIRED_SIDE_EFFECT_FAMILIES <= families
    assert REQUIRED_ERROR_RETRY_FAMILIES <= families


def test_every_spec_has_semantic_intent_and_equivalence_hints() -> None:
    for spec in effects_errors_operator_specs():
        assert spec.semantic_intent.strip()
        assert len(spec.likely_equivalent_conditions) >= 1
        assert all(c.strip() for c in spec.likely_equivalent_conditions)
        assert spec.syntactic_transformation.strip()


def test_side_effect_families_coverage() -> None:
    by_family = {
        family: [
            s
            for s in effects_errors_operator_specs()
            if s.family == family
        ]
        for family in REQUIRED_SIDE_EFFECT_FAMILIES
    }
    assert by_family[EffectsErrorsFamily.OMITTED_EFFECT.value]
    assert by_family[EffectsErrorsFamily.WRONG_EFFECT.value]
    assert by_family[EffectsErrorsFamily.EARLY_EFFECT.value]
    assert by_family[EffectsErrorsFamily.DOUBLE_EFFECT.value]
    assert by_family[EffectsErrorsFamily.REORDERED_EFFECT.value]
    assert by_family[EffectsErrorsFamily.AUDIT_OMISSION.value]
    assert by_family[EffectsErrorsFamily.SUCCESS_BEFORE_OBSERVATION.value]
    assert by_family[EffectsErrorsFamily.MISSING_COMPENSATION.value]
    for family, specs in by_family.items():
        for s in specs:
            assert s.operator_class == OperatorClass.SIDE_EFFECT.value
            assert s.family == family


def test_error_retry_families_coverage() -> None:
    by_family = {
        family: [
            s
            for s in effects_errors_operator_specs()
            if s.family == family
        ]
        for family in REQUIRED_ERROR_RETRY_FAMILIES
    }
    assert by_family[EffectsErrorsFamily.SWALLOWED_FAILURE.value]
    assert by_family[EffectsErrorsFamily.MISCLASSIFIED_FAILURE.value]
    assert by_family[EffectsErrorsFamily.UNAVAILABLE_TO_SUCCESS.value]
    assert by_family[EffectsErrorsFamily.RETRY_BUDGET.value]
    assert by_family[EffectsErrorsFamily.CANCELLATION.value]
    assert by_family[EffectsErrorsFamily.INTEGRITY_FAILURE.value]
    for family, specs in by_family.items():
        for s in specs:
            assert s.operator_class == OperatorClass.ERROR_RETRY.value
            assert s.family == family


def test_omitted_wrong_early_double_reordered_operator_ids() -> None:
    ids = {s.operator_id for s in effects_errors_operator_specs()}
    assert "se_omit_required_write" in ids
    assert "se_wrong_write_target" in ids
    assert "se_effect_before_validation" in ids
    assert "se_double_write" in ids
    assert "se_reorder_writes" in ids


def test_audit_and_compensation_operator_ids() -> None:
    ids = {s.operator_id for s in effects_errors_operator_specs()}
    assert "se_omit_audit_log" in ids
    assert "se_skip_compensation_on_partial_failure" in ids
    assert "se_incomplete_compensation" in ids


def test_swallowed_misclassified_retry_cancel_integrity_ids() -> None:
    ids = {s.operator_id for s in effects_errors_operator_specs()}
    assert "er_swallow_exception" in ids
    assert "er_misclassify_error_code" in ids
    assert "er_remove_retry_budget" in ids
    assert "er_unbounded_retries" in ids
    assert "er_ignore_cancellation_signal" in ids
    assert "er_bypass_integrity_check" in ids
    assert "er_accept_integrity_failure" in ids


def test_default_catalogue_is_complete_and_bounded() -> None:
    catalogue = default_effects_errors_operators()
    assert catalogue.catalogue_id
    assert catalogue.to_dict()["interface_id"] == EFFECTS_ERRORS_OPERATORS_INTERFACE
    assert catalogue.to_dict()["schema"] == EFFECTS_ERRORS_OPERATORS_SCHEMA
    catalogue.assert_complete_coverage()
    assert set(catalogue.families()) == REQUIRED_EFFECTS_ERRORS_FAMILIES
    assert effects_errors_families_covered() == REQUIRED_EFFECTS_ERRORS_FAMILIES
    assert set(catalogue.operator_classes()) == ADMITTED_OPERATOR_CLASSES
    for operator in catalogue:
        assert operator.definition.operator_class in ADMITTED_OPERATOR_CLASSES
        assert operator.definition.deterministic is True
        assert operator.family in REQUIRED_EFFECTS_ERRORS_FAMILIES
        assert operator.definition.semantic_intent
        assert operator.definition.likely_equivalent_conditions
        assert_effects_errors_operator_defaults(operator.definition)


def test_expected_operator_ids_present() -> None:
    ids = set(default_effects_errors_operators().operator_ids())
    expected = {
        "se_omit_required_write",
        "se_omit_ack_publication",
        "se_wrong_write_target",
        "se_wrong_effect_payload",
        "se_effect_before_validation",
        "se_effect_before_commit_gate",
        "se_double_write",
        "se_retry_without_dedup",
        "se_reorder_writes",
        "se_reorder_release_before_publish",
        "se_omit_audit_log",
        "se_suppress_security_event",
        "se_success_before_durability_observe",
        "se_ack_before_effect_complete",
        "se_skip_compensation_on_partial_failure",
        "se_incomplete_compensation",
        "er_swallow_exception",
        "er_silent_error_to_none",
        "er_misclassify_error_code",
        "er_treat_fatal_as_retryable",
        "er_unavailable_to_success",
        "er_unknown_to_allow",
        "er_remove_retry_budget",
        "er_unbounded_retries",
        "er_ignore_retry_after",
        "er_ignore_cancellation_signal",
        "er_cancel_without_cleanup",
        "er_bypass_integrity_check",
        "er_accept_integrity_failure",
        "er_strip_integrity_metadata",
    }
    assert expected <= ids


def test_catalogue_identity_is_deterministic() -> None:
    left = default_effects_errors_operators()
    right = default_effects_errors_operators()
    assert left.catalogue_id == right.catalogue_id
    assert left.operator_cids() == right.operator_cids()
    assert left.identity_payload() == right.identity_payload()


def test_catalogue_round_trip_preserves_identity() -> None:
    original = default_effects_errors_operators()
    restored = EffectsErrorsMutationOperators.from_dict(original.to_dict())
    assert restored.catalogue_id == original.catalogue_id
    assert restored.operator_ids() == original.operator_ids()
    assert restored.operator_cids() == original.operator_cids()
    assert set(restored.families()) == set(original.families())
    assert set(restored.operator_classes()) == set(original.operator_classes())


def test_definitions_helper_matches_catalogue() -> None:
    defs = effects_errors_operator_definitions()
    catalogue = default_effects_errors_operators()
    assert [d.operator_cid for d in defs] == list(catalogue.operator_cids())
    assert all(d.operator_class in ADMITTED_OPERATOR_CLASSES for d in defs)


# ---------------------------------------------------------------------------
# Lookup, target support, rollback
# ---------------------------------------------------------------------------


def test_get_and_get_by_cid() -> None:
    catalogue = default_effects_errors_operators()
    op = catalogue.get("se_omit_required_write")
    assert op.family == EffectsErrorsFamily.OMITTED_EFFECT.value
    by_cid = catalogue.get_by_cid(op.operator_cid)
    assert by_cid.operator_id == op.operator_id
    assert "se_omit_required_write" in catalogue
    assert op.operator_cid in catalogue
    with pytest.raises(EffectsErrorsError, match="unknown operator_id"):
        catalogue.get("se_does_not_exist")
    with pytest.raises(EffectsErrorsError, match="unknown operator_cid"):
        catalogue.get_by_cid(_cid("missing-operator"))


def test_operators_for_family_class_and_target() -> None:
    catalogue = default_effects_errors_operators()
    retry_ops = catalogue.operators_for_family(EffectsErrorsFamily.RETRY_BUDGET)
    assert len(retry_ops) == 3
    assert {op.operator_id for op in retry_ops} == {
        "er_remove_retry_budget",
        "er_unbounded_retries",
        "er_ignore_retry_after",
    }

    side_effect_ops = catalogue.operators_for_class(OperatorClass.SIDE_EFFECT)
    error_retry_ops = catalogue.operators_for_class(OperatorClass.ERROR_RETRY)
    assert len(side_effect_ops) + len(error_retry_ops) == len(catalogue)
    assert all(
        op.definition.operator_class == OperatorClass.SIDE_EFFECT.value
        for op in side_effect_ops
    )
    assert all(
        op.definition.operator_class == OperatorClass.ERROR_RETRY.value
        for op in error_retry_ops
    )

    target = _target()
    supporting = catalogue.operators_for_target(target)
    assert len(supporting) == len(catalogue)
    assert all(op.supports_target(target) for op in supporting)

    unsupported = catalogue.operators_for_target(_target(language="cobol"))
    assert unsupported == ()


def test_rollback_record_is_deterministic() -> None:
    catalogue = default_effects_errors_operators()
    target = _target()
    pre = _cid("pre-mutation-ee")
    first = catalogue.rollback_record(
        "er_remove_retry_budget",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    second = catalogue.rollback_record(
        "er_remove_retry_budget",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    assert isinstance(first, OperatorRollbackRecord)
    assert first.record_cid == second.record_cid
    assert first.preserves_production is True
    assert first.requires_clean_worktree is True
    assert first.operator_id == "er_remove_retry_budget"


def test_rollback_record_fails_closed_for_unsupported_target() -> None:
    catalogue = default_effects_errors_operators()
    with pytest.raises(Exception, match="does not support|language|artifact"):
        catalogue.rollback_record(
            "se_omit_required_write",
            pre_mutation_state_cid=_cid("pre"),
            target=_target(language="cobol"),
        )


# ---------------------------------------------------------------------------
# Registry projection
# ---------------------------------------------------------------------------


def test_as_registry_admits_all_operators() -> None:
    catalogue = default_effects_errors_operators()
    registry = catalogue.as_registry()
    assert len(registry) == len(catalogue)
    for operator_id in catalogue.operator_ids():
        admitted = registry.get(operator_id)
        assert admitted.operator_class in ADMITTED_OPERATOR_CLASSES


def test_register_into_builder() -> None:
    catalogue = default_effects_errors_operators()
    builder = MutationOperatorRegistryBuilder()
    sealed = catalogue.register_into(builder)
    assert len(sealed) == len(catalogue)
    registry = builder.build()
    assert set(registry.operator_ids()) == set(catalogue.operator_ids())


def test_registry_dispatch_for_side_effect_and_error_retry() -> None:
    catalogue = default_effects_errors_operators()
    registry = catalogue.as_registry()
    target = _target()

    side_matches = registry.dispatch(
        target, operator_class=OperatorClass.SIDE_EFFECT
    )
    assert len(side_matches) == len(
        catalogue.operators_for_class(OperatorClass.SIDE_EFFECT)
    )

    error_matches = registry.dispatch(
        target, operator_class=OperatorClass.ERROR_RETRY
    )
    assert len(error_matches) == len(
        catalogue.operators_for_class(OperatorClass.ERROR_RETRY)
    )

    one = registry.dispatch_one(
        target,
        operator_id="er_ignore_cancellation_signal",
        operator_class=OperatorClass.ERROR_RETRY,
    )
    assert one.operator_id == "er_ignore_cancellation_signal"
    assert PropertyClass.CANCELLATION.value in one.expected_violated_property_classes


# ---------------------------------------------------------------------------
# Coverage / negative assembly
# ---------------------------------------------------------------------------


def test_incomplete_catalogue_rejected() -> None:
    omit_only = _minimal_spec()
    with pytest.raises(EffectsErrorsCoverageError, match="missing required"):
        build_effects_errors_operators([omit_only])

    sealed = build_effects_errors_operator(omit_only)
    handle = EffectsErrorsOperator(
        _definition=sealed,
        family=EffectsErrorsFamily.OMITTED_EFFECT.value,
        spec_operator_id="se_omit_required_write",
    )
    with pytest.raises(EffectsErrorsCoverageError, match="missing required"):
        EffectsErrorsMutationOperators(operators=(handle,))


def test_duplicate_operator_id_rejected() -> None:
    specs = list(effects_errors_operator_specs())
    specs.append(
        EffectsErrorsOperatorSpec(
            operator_id="se_omit_required_write",
            family=EffectsErrorsFamily.OMITTED_EFFECT,
            semantic_intent="Duplicate id must fail",
            syntactic_transformation="remove_required_side_effect_call_v2",
            expected_violated_property_classes=(
                PropertyClass.SIDE_EFFECT_OBLIGATION,
            ),
            likely_equivalent_conditions=("dead_effect",),
        )
    )
    with pytest.raises(EffectsErrorsError, match="duplicate operator_id"):
        build_effects_errors_operators(specs)


def test_from_dict_rejects_unknown_fields() -> None:
    payload = default_effects_errors_operators().to_dict()
    payload["unexpected_field"] = True
    with pytest.raises(EffectsErrorsError, match="unknown fields"):
        EffectsErrorsMutationOperators.from_dict(payload)


def test_from_dict_rejects_schema_mismatch() -> None:
    payload = default_effects_errors_operators().to_dict()
    payload["schema"] = "wrong-schema@1"
    with pytest.raises(EffectsErrorsError, match="unsupported .* schema"):
        EffectsErrorsMutationOperators.from_dict(payload)


def test_operator_handle_rejects_family_metadata_mismatch() -> None:
    definition = build_effects_errors_operator(_minimal_spec())
    with pytest.raises(EffectsErrorsError, match="does not match"):
        EffectsErrorsOperator(
            _definition=definition,
            family=EffectsErrorsFamily.CANCELLATION.value,
            spec_operator_id="se_omit_required_write",
        )


def test_declaration_backed_projection() -> None:
    catalogue = default_effects_errors_operators()
    handle = catalogue.get("se_double_write")
    backed = handle.as_declaration_backed()
    assert backed.operator_cid == handle.operator_cid
    assert backed.supports_target(_target()) is True


def test_catalogue_identity_matches_content_address() -> None:
    catalogue = default_effects_errors_operators()
    recomputed = cid_for_structured(
        catalogue._identity_payload_without_catalogue_id()  # noqa: SLF001
    )
    assert recomputed == catalogue.catalogue_id


def test_side_effect_operators_expect_obligation_or_compensation() -> None:
    catalogue = default_effects_errors_operators()
    for op in catalogue.operators_for_class(OperatorClass.SIDE_EFFECT):
        props = set(op.definition.expected_violated_property_classes)
        assert props & {
            PropertyClass.SIDE_EFFECT_OBLIGATION.value,
            PropertyClass.COMPENSATION.value,
        }


def test_error_retry_operators_expect_error_related_properties() -> None:
    allowed = {
        PropertyClass.ERROR_HANDLING.value,
        PropertyClass.RETRY_BUDGET.value,
        PropertyClass.CANCELLATION.value,
        PropertyClass.DATA_INTEGRITY.value,
        PropertyClass.STORAGE_INTEGRITY.value,
        PropertyClass.SIDE_EFFECT_OBLIGATION.value,
        PropertyClass.COMPENSATION.value,
    }
    catalogue = default_effects_errors_operators()
    for op in catalogue.operators_for_class(OperatorClass.ERROR_RETRY):
        props = set(op.definition.expected_violated_property_classes)
        assert props & allowed


def test_cancellation_operators_expect_cancellation_property() -> None:
    catalogue = default_effects_errors_operators()
    for op in catalogue.operators_for_family(EffectsErrorsFamily.CANCELLATION):
        assert (
            PropertyClass.CANCELLATION.value
            in op.definition.expected_violated_property_classes
        )


def test_retry_budget_operators_expect_retry_budget_property() -> None:
    catalogue = default_effects_errors_operators()
    for op in catalogue.operators_for_family(EffectsErrorsFamily.RETRY_BUDGET):
        assert (
            PropertyClass.RETRY_BUDGET.value
            in op.definition.expected_violated_property_classes
        )


def test_integrity_operators_expect_integrity_properties() -> None:
    catalogue = default_effects_errors_operators()
    for op in catalogue.operators_for_family(EffectsErrorsFamily.INTEGRITY_FAILURE):
        props = set(op.definition.expected_violated_property_classes)
        assert props & {
            PropertyClass.DATA_INTEGRITY.value,
            PropertyClass.STORAGE_INTEGRITY.value,
        }


def test_compensation_operators_expect_compensation_property() -> None:
    catalogue = default_effects_errors_operators()
    for op in catalogue.operators_for_family(
        EffectsErrorsFamily.MISSING_COMPENSATION
    ):
        assert (
            PropertyClass.COMPENSATION.value
            in op.definition.expected_violated_property_classes
        )


def test_swallowed_and_misclassified_expect_error_handling() -> None:
    catalogue = default_effects_errors_operators()
    for family in (
        EffectsErrorsFamily.SWALLOWED_FAILURE,
        EffectsErrorsFamily.MISCLASSIFIED_FAILURE,
        EffectsErrorsFamily.UNAVAILABLE_TO_SUCCESS,
    ):
        for op in catalogue.operators_for_family(family):
            assert (
                PropertyClass.ERROR_HANDLING.value
                in op.definition.expected_violated_property_classes
            )


def test_sandbox_and_scope_are_tight() -> None:
    for definition in effects_errors_operator_definitions():
        assert definition.scope_limits.allow_verifier_mutation is False
        assert definition.scope_limits.allow_cross_module is False
        assert definition.scope_limits.max_files == 1
        assert definition.max_mutants_per_target <= 8
        assert definition.required_sandbox.disposable_worktree_required is True


def test_admitted_classes_are_exactly_side_effect_and_error_retry() -> None:
    assert ADMITTED_OPERATOR_CLASSES == frozenset(
        {
            OperatorClass.SIDE_EFFECT.value,
            OperatorClass.ERROR_RETRY.value,
        }
    )
    catalogue = default_effects_errors_operators()
    assert set(catalogue.operator_classes()) == ADMITTED_OPERATOR_CLASSES
