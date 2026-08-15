"""Unit tests for DataSchemaInterfaceMutationOperators@1 (AAE-016)."""

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
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.data_schema_interface import (
    ADMITTED_OPERATOR_CLASSES,
    DATA_SCHEMA_INTERFACE_OPERATORS_INTERFACE,
    DATA_SCHEMA_INTERFACE_OPERATORS_SCHEMA,
    DEFAULT_DATA_SCHEMA_RISK_CLASS,
    DEFAULT_INTERFACE_RISK_CLASS,
    REQUIRED_DATA_SCHEMA_FAMILIES,
    REQUIRED_DATA_SCHEMA_INTERFACE_FAMILIES,
    REQUIRED_INTERFACE_CONTRACT_FAMILIES,
    DataSchemaInterfaceCoverageError,
    DataSchemaInterfaceError,
    DataSchemaInterfaceFamily,
    DataSchemaInterfaceMutationOperators,
    DataSchemaInterfaceOperator,
    DataSchemaInterfaceOperatorSpec,
    DataSchemaInterfaceTextEditError,
    assert_data_schema_interface_operator_defaults,
    assert_structured_transformation,
    build_data_schema_interface_operator,
    build_data_schema_interface_operators,
    data_schema_interface_families_covered,
    data_schema_interface_operator_definitions,
    data_schema_interface_operator_specs,
    default_data_schema_interface_operators,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.registry import (
    MutationOperatorRegistryBuilder,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _target(**overrides: object) -> MutationTarget:
    fields = {
        "target_id": "schema_gate_fn",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state-dsi"),
        "symbol_ids": ("mod.schema_gate",),
        "artifact_cids": (_cid("artifact-dsi"),),
        "language": "python",
        "artifact_type": "source_module",
        "prerequisites": ("parsed_ast", "symbol_table", "type_check"),
        "risk_class": MutationRiskClass.CRITICAL_INVARIANT,
        "risk_weight_bp": 7_500,
        "capsule_cids": (_cid("capsule-dsi"),),
        "proof_unit_cids": (_cid("proof-dsi"),),
        "source_path": "mod/schema_gate.py",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationTarget(**fields)  # type: ignore[arg-type]


def _minimal_spec(**overrides: object) -> DataSchemaInterfaceOperatorSpec:
    fields: dict[str, object] = {
        "operator_id": "ds_drop_required_field",
        "family": DataSchemaInterfaceFamily.REQUIRED,
        "semantic_intent": "Drop a required field",
        "syntactic_transformation": "remove_required_field_from_object",
        "expected_violated_property_classes": (PropertyClass.SCHEMA_CONTRACT,),
        "likely_equivalent_conditions": (
            "field_is_already_optional_by_schema",
        ),
    }
    fields.update(overrides)
    return DataSchemaInterfaceOperatorSpec(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Spec validation and structured transforms
# ---------------------------------------------------------------------------


def test_default_risk_classes() -> None:
    assert DEFAULT_DATA_SCHEMA_RISK_CLASS == MutationRiskClass.CRITICAL_INVARIANT.value
    assert DEFAULT_INTERFACE_RISK_CLASS == MutationRiskClass.HIGH.value


def test_spec_requires_equivalence_hints() -> None:
    with pytest.raises(DataSchemaInterfaceError, match="equivalence hints"):
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_no_equiv",
            family=DataSchemaInterfaceFamily.REQUIRED,
            semantic_intent="Drop without hints",
            syntactic_transformation="remove_required_field_from_object",
            expected_violated_property_classes=(PropertyClass.SCHEMA_CONTRACT,),
            likely_equivalent_conditions=(),
        )


def test_spec_rejects_unknown_family() -> None:
    with pytest.raises(
        DataSchemaInterfaceError, match="unsupported data/schema/interface family"
    ):
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_unknown_family",
            family="not_a_family",
            semantic_intent="Unknown family must fail closed",
            syntactic_transformation="noop_structured",
            expected_violated_property_classes=(PropertyClass.SCHEMA_CONTRACT,),
            likely_equivalent_conditions=("always_dead",),
        )


def test_spec_rejects_empty_semantic_intent() -> None:
    with pytest.raises(DataSchemaInterfaceError, match="semantic_intent"):
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_empty_intent",
            family=DataSchemaInterfaceFamily.REQUIRED,
            semantic_intent="   ",
            syntactic_transformation="remove_required_field_from_object",
            expected_violated_property_classes=(PropertyClass.SCHEMA_CONTRACT,),
            likely_equivalent_conditions=("x",),
        )


def test_spec_rejects_arbitrary_text_edit_transformation() -> None:
    with pytest.raises(DataSchemaInterfaceTextEditError, match="arbitrary text edit"):
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_freeform_forbidden",
            family=DataSchemaInterfaceFamily.REQUIRED,
            semantic_intent="Must not admit free-form text rewrites",
            syntactic_transformation="arbitrary_text_edit",
            expected_violated_property_classes=(PropertyClass.SCHEMA_CONTRACT,),
            likely_equivalent_conditions=("none",),
        )


def test_assert_structured_transformation_rejects_freeform_spans() -> None:
    with pytest.raises(DataSchemaInterfaceTextEditError):
        assert_structured_transformation("replace some free form text here")
    with pytest.raises(DataSchemaInterfaceTextEditError, match="arbitrary"):
        assert_structured_transformation("freeform_string_replace")
    assert_structured_transformation("remove_required_field_from_object")


def test_family_operator_class_coherence() -> None:
    with pytest.raises(DataSchemaInterfaceError, match="requires operator_class"):
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_wrong_class",
            family=DataSchemaInterfaceFamily.REQUIRED,
            operator_class=OperatorClass.INTERFACE_CONTRACT,
            semantic_intent="Required family cannot be interface_contract",
            syntactic_transformation="remove_required_field_from_object",
            expected_violated_property_classes=(PropertyClass.INTERFACE_CONTRACT,),
            likely_equivalent_conditions=("x",),
        )
    with pytest.raises(DataSchemaInterfaceError, match="requires operator_class"):
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_wrong_class",
            family=DataSchemaInterfaceFamily.PRE,
            operator_class=OperatorClass.DATA_SCHEMA,
            semantic_intent="Pre family cannot be data_schema",
            syntactic_transformation="replace_precondition_check_with_true",
            expected_violated_property_classes=(PropertyClass.INTERFACE_CONTRACT,),
            likely_equivalent_conditions=("x",),
        )


def test_build_operator_seals_with_data_schema_class() -> None:
    sealed = build_data_schema_interface_operator(_minimal_spec())
    assert sealed.operator_class == OperatorClass.DATA_SCHEMA.value
    assert sealed.risk_class == MutationRiskClass.CRITICAL_INVARIANT.value
    assert sealed.deterministic is True
    assert sealed.required_sandbox.network_disabled is True
    assert sealed.required_sandbox.production_credentials_forbidden is True
    assert sealed.rollback.preserves_production is True
    assert sealed.metadata["dsi_family"] == "required"
    assert sealed.semantic_intent
    assert sealed.likely_equivalent_conditions
    assert_data_schema_interface_operator_defaults(sealed)


def test_build_interface_operator_defaults() -> None:
    sealed = build_data_schema_interface_operator(
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_drop_precondition",
            family=DataSchemaInterfaceFamily.PRE,
            semantic_intent="Remove a precondition check",
            syntactic_transformation="replace_precondition_check_with_true",
            expected_violated_property_classes=(PropertyClass.INTERFACE_CONTRACT,),
            likely_equivalent_conditions=("precondition_is_statically_always_true",),
        )
    )
    assert sealed.operator_class == OperatorClass.INTERFACE_CONTRACT.value
    assert sealed.risk_class == MutationRiskClass.HIGH.value
    assert PropertyClass.INTERFACE_CONTRACT.value in sealed.expected_violated_property_classes


def test_assert_defaults_rejects_wrong_operator_class() -> None:
    wrong = MutationOperatorDefinition(
        operator_id="cf_invert_conditional",
        operator_version="1",
        operator_class=OperatorClass.CONTROL_FLOW,
        supported_languages=("python",),
        supported_artifact_types=("source_module",),
        target_prerequisites=("parsed_ast",),
        semantic_intent="Not a data/schema operator",
        expected_violated_property_classes=(PropertyClass.CONTROL_INVARIANT,),
        risk_class=MutationRiskClass.CRITICAL_INVARIANT,
        likely_equivalent_conditions=("public_endpoint",),
        syntactic_transformation="negate_conditional_predicate",
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
    with pytest.raises(DataSchemaInterfaceError, match="data_schema or interface_contract"):
        assert_data_schema_interface_operator_defaults(wrong)


# ---------------------------------------------------------------------------
# Normative catalogue coverage
# ---------------------------------------------------------------------------


def test_normative_specs_cover_every_required_family() -> None:
    specs = data_schema_interface_operator_specs()
    families = {spec.family for spec in specs}
    assert families == REQUIRED_DATA_SCHEMA_INTERFACE_FAMILIES
    for family in (
        DataSchemaInterfaceFamily.REQUIRED,
        DataSchemaInterfaceFamily.NULL,
        DataSchemaInterfaceFamily.DEFAULT,
        DataSchemaInterfaceFamily.ORDER,
        DataSchemaInterfaceFamily.VERSION,
        DataSchemaInterfaceFamily.BOUNDS,
        DataSchemaInterfaceFamily.FLOAT,
        DataSchemaInterfaceFamily.UNICODE,
        DataSchemaInterfaceFamily.SCHEMA,
        DataSchemaInterfaceFamily.PRE,
        DataSchemaInterfaceFamily.POST,
        DataSchemaInterfaceFamily.ERROR,
        DataSchemaInterfaceFamily.EXCEPTION,
        DataSchemaInterfaceFamily.HANDLER,
        DataSchemaInterfaceFamily.SEMANTIC_RESULT,
    ):
        assert family.value in families


def test_every_spec_has_semantic_intent_and_structured_transform() -> None:
    for spec in data_schema_interface_operator_specs():
        assert spec.semantic_intent.strip()
        assert len(spec.likely_equivalent_conditions) >= 1
        assert all(c.strip() for c in spec.likely_equivalent_conditions)
        assert_structured_transformation(spec.syntactic_transformation)
        assert "arbitrary" not in spec.syntactic_transformation.lower()
        assert "freeform" not in spec.syntactic_transformation.lower()


def test_data_schema_cases_covered() -> None:
    specs = data_schema_interface_operator_specs()
    by_family = {f: [] for f in REQUIRED_DATA_SCHEMA_FAMILIES}
    for spec in specs:
        if spec.family in by_family:
            by_family[spec.family].append(spec)
    assert by_family["required"]
    assert by_family["null"]
    assert by_family["default"]
    assert by_family["order"]
    assert by_family["version"]
    assert by_family["bounds"]
    assert by_family["float"]
    assert by_family["unicode"]
    assert by_family["schema"]
    schema_ids = {s.operator_id for s in by_family["schema"]}
    assert "ds_inject_unknown_field" in schema_ids
    assert "ds_truncate_payload_field" in schema_ids
    assert "ds_swap_sibling_fields" in schema_ids


def test_interface_cases_covered() -> None:
    specs = data_schema_interface_operator_specs()
    by_family: dict[str, list[DataSchemaInterfaceOperatorSpec]] = {
        f: [] for f in REQUIRED_INTERFACE_CONTRACT_FAMILIES
    }
    for spec in specs:
        if spec.family in by_family:
            by_family[spec.family].append(spec)
    assert by_family["pre"]
    assert by_family["post"]
    assert by_family["error"]
    assert by_family["exception"]
    assert by_family["version"]
    assert by_family["handler"]
    assert by_family["semantic_result"]
    version_classes = {s.operator_class for s in by_family["version"]}
    assert OperatorClass.DATA_SCHEMA.value in version_classes
    assert OperatorClass.INTERFACE_CONTRACT.value in version_classes
    semantic_ids = {s.operator_id for s in by_family["semantic_result"]}
    assert "ic_structurally_valid_wrong_result" in semantic_ids


def test_default_catalogue_is_complete_and_bounded() -> None:
    catalogue = default_data_schema_interface_operators()
    assert catalogue.catalogue_id
    assert catalogue.to_dict()["interface_id"] == DATA_SCHEMA_INTERFACE_OPERATORS_INTERFACE
    assert catalogue.to_dict()["schema"] == DATA_SCHEMA_INTERFACE_OPERATORS_SCHEMA
    catalogue.assert_complete_coverage()
    assert set(catalogue.families()) == REQUIRED_DATA_SCHEMA_INTERFACE_FAMILIES
    assert data_schema_interface_families_covered() == REQUIRED_DATA_SCHEMA_INTERFACE_FAMILIES
    assert set(catalogue.operator_classes()) == ADMITTED_OPERATOR_CLASSES
    for operator in catalogue:
        assert operator.definition.operator_class in ADMITTED_OPERATOR_CLASSES
        assert operator.definition.deterministic is True
        assert operator.family in REQUIRED_DATA_SCHEMA_INTERFACE_FAMILIES
        assert operator.definition.semantic_intent
        assert operator.definition.likely_equivalent_conditions
        assert_data_schema_interface_operator_defaults(operator.definition)
        assert_structured_transformation(operator.definition.syntactic_transformation)


def test_expected_operator_ids_present() -> None:
    ids = set(default_data_schema_interface_operators().operator_ids())
    expected = {
        "ds_drop_required_field",
        "ds_mark_required_optional",
        "ds_force_null_value",
        "ds_accept_null_where_forbidden",
        "ds_suppress_default_application",
        "ds_wrong_default_value",
        "ds_reorder_object_fields",
        "ds_reorder_array_elements",
        "ds_mismatch_schema_version",
        "ds_skip_version_gate",
        "ds_relax_min_bound",
        "ds_relax_max_bound",
        "ds_float_equality_without_epsilon",
        "ds_inject_nan_or_inf",
        "ds_unicode_normalization_change",
        "ds_unicode_homoglyph_swap",
        "ds_inject_unknown_field",
        "ds_truncate_payload_field",
        "ds_swap_sibling_fields",
        "ic_drop_precondition",
        "ic_wrong_parameter_type_coercion",
        "ic_drop_postcondition",
        "ic_weaken_postcondition",
        "ic_wrong_error_code",
        "ic_suppress_declared_error",
        "ic_wrong_exception_type",
        "ic_swallow_declared_exception",
        "ic_mismatch_interface_version",
        "ic_skip_interface_version_check",
        "ic_wrong_handler_binding",
        "ic_drop_handler_registration",
        "ic_structurally_valid_wrong_result",
        "ic_success_with_error_semantics",
    }
    assert expected <= ids


def test_catalogue_identity_is_deterministic() -> None:
    left = default_data_schema_interface_operators()
    right = default_data_schema_interface_operators()
    assert left.catalogue_id == right.catalogue_id
    assert left.operator_cids() == right.operator_cids()
    assert left.identity_payload() == right.identity_payload()


def test_catalogue_round_trip_preserves_identity() -> None:
    original = default_data_schema_interface_operators()
    restored = DataSchemaInterfaceMutationOperators.from_dict(original.to_dict())
    assert restored.catalogue_id == original.catalogue_id
    assert restored.operator_ids() == original.operator_ids()
    assert restored.operator_cids() == original.operator_cids()
    assert set(restored.families()) == set(original.families())


def test_definitions_helper_matches_catalogue() -> None:
    defs = data_schema_interface_operator_definitions()
    catalogue = default_data_schema_interface_operators()
    assert [d.operator_cid for d in defs] == list(catalogue.operator_cids())
    assert all(d.operator_class in ADMITTED_OPERATOR_CLASSES for d in defs)


# ---------------------------------------------------------------------------
# Lookup, target support, rollback
# ---------------------------------------------------------------------------


def test_get_and_get_by_cid() -> None:
    catalogue = default_data_schema_interface_operators()
    op = catalogue.get("ds_drop_required_field")
    assert op.family == DataSchemaInterfaceFamily.REQUIRED.value
    by_cid = catalogue.get_by_cid(op.operator_cid)
    assert by_cid.operator_id == op.operator_id
    assert "ds_drop_required_field" in catalogue
    assert op.operator_cid in catalogue
    with pytest.raises(DataSchemaInterfaceError, match="unknown operator_id"):
        catalogue.get("ds_does_not_exist")
    with pytest.raises(DataSchemaInterfaceError, match="unknown operator_cid"):
        catalogue.get_by_cid(_cid("missing-operator"))


def test_operators_for_family_class_and_target() -> None:
    catalogue = default_data_schema_interface_operators()
    null_ops = catalogue.operators_for_family(DataSchemaInterfaceFamily.NULL)
    assert {op.operator_id for op in null_ops} == {
        "ds_force_null_value",
        "ds_accept_null_where_forbidden",
    }

    data_ops = catalogue.operators_for_class(OperatorClass.DATA_SCHEMA)
    iface_ops = catalogue.operators_for_class(OperatorClass.INTERFACE_CONTRACT)
    assert data_ops
    assert iface_ops
    assert len(data_ops) + len(iface_ops) == len(catalogue)
    assert all(
        op.definition.operator_class == OperatorClass.DATA_SCHEMA.value
        for op in data_ops
    )
    assert all(
        op.definition.operator_class == OperatorClass.INTERFACE_CONTRACT.value
        for op in iface_ops
    )

    target = _target()
    supporting = catalogue.operators_for_target(target)
    assert len(supporting) == len(catalogue)
    assert all(op.supports_target(target) for op in supporting)

    unsupported = catalogue.operators_for_target(_target(language="cobol"))
    assert unsupported == ()


def test_rollback_record_is_deterministic() -> None:
    catalogue = default_data_schema_interface_operators()
    target = _target()
    pre = _cid("pre-mutation-dsi")
    first = catalogue.rollback_record(
        "ds_swap_sibling_fields",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    second = catalogue.rollback_record(
        "ds_swap_sibling_fields",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    assert isinstance(first, OperatorRollbackRecord)
    assert first.record_cid == second.record_cid
    assert first.preserves_production is True
    assert first.requires_clean_worktree is True
    assert first.operator_id == "ds_swap_sibling_fields"


def test_rollback_record_fails_closed_for_unsupported_target() -> None:
    catalogue = default_data_schema_interface_operators()
    with pytest.raises(Exception, match="does not support|language|artifact"):
        catalogue.rollback_record(
            "ic_drop_precondition",
            pre_mutation_state_cid=_cid("pre"),
            target=_target(language="cobol"),
        )


# ---------------------------------------------------------------------------
# Registry projection
# ---------------------------------------------------------------------------


def test_as_registry_admits_all_operators() -> None:
    catalogue = default_data_schema_interface_operators()
    registry = catalogue.as_registry()
    assert len(registry) == len(catalogue)
    for operator_id in catalogue.operator_ids():
        admitted = registry.get(operator_id)
        assert admitted.operator_class in ADMITTED_OPERATOR_CLASSES


def test_register_into_builder() -> None:
    catalogue = default_data_schema_interface_operators()
    builder = MutationOperatorRegistryBuilder()
    sealed = catalogue.register_into(builder)
    assert len(sealed) == len(catalogue)
    registry = builder.build()
    assert set(registry.operator_ids()) == set(catalogue.operator_ids())


def test_registry_dispatch_for_data_and_interface_targets() -> None:
    catalogue = default_data_schema_interface_operators()
    registry = catalogue.as_registry()
    target = _target()
    data_matches = registry.dispatch(
        target, operator_class=OperatorClass.DATA_SCHEMA
    )
    iface_matches = registry.dispatch(
        target, operator_class=OperatorClass.INTERFACE_CONTRACT
    )
    assert len(data_matches) == len(
        catalogue.operators_for_class(OperatorClass.DATA_SCHEMA)
    )
    assert len(iface_matches) == len(
        catalogue.operators_for_class(OperatorClass.INTERFACE_CONTRACT)
    )
    one = registry.dispatch_one(
        target,
        operator_id="ic_structurally_valid_wrong_result",
        operator_class=OperatorClass.INTERFACE_CONTRACT,
    )
    assert one.operator_id == "ic_structurally_valid_wrong_result"
    assert (
        PropertyClass.INTERFACE_CONTRACT.value
        in one.expected_violated_property_classes
    )


# ---------------------------------------------------------------------------
# Coverage / negative assembly
# ---------------------------------------------------------------------------


def test_incomplete_catalogue_rejected() -> None:
    required_only = _minimal_spec()
    with pytest.raises(
        DataSchemaInterfaceCoverageError, match="missing required families"
    ):
        build_data_schema_interface_operators([required_only])

    sealed = build_data_schema_interface_operator(required_only)
    handle = DataSchemaInterfaceOperator(
        _definition=sealed,
        family=DataSchemaInterfaceFamily.REQUIRED.value,
        spec_operator_id="ds_drop_required_field",
    )
    with pytest.raises(
        DataSchemaInterfaceCoverageError, match="missing required families"
    ):
        DataSchemaInterfaceMutationOperators(operators=(handle,))


def test_duplicate_operator_id_rejected() -> None:
    specs = list(data_schema_interface_operator_specs())
    specs.append(
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_drop_required_field",
            family=DataSchemaInterfaceFamily.REQUIRED,
            semantic_intent="Duplicate id must fail",
            syntactic_transformation="remove_required_field_from_object_v2",
            expected_violated_property_classes=(PropertyClass.SCHEMA_CONTRACT,),
            likely_equivalent_conditions=("dead_field",),
        )
    )
    with pytest.raises(DataSchemaInterfaceError, match="duplicate operator_id"):
        build_data_schema_interface_operators(specs)


def test_from_dict_rejects_unknown_fields() -> None:
    payload = default_data_schema_interface_operators().to_dict()
    payload["unexpected_field"] = True
    with pytest.raises(DataSchemaInterfaceError, match="unknown fields"):
        DataSchemaInterfaceMutationOperators.from_dict(payload)


def test_from_dict_rejects_schema_mismatch() -> None:
    payload = default_data_schema_interface_operators().to_dict()
    payload["schema"] = "wrong-schema@1"
    with pytest.raises(DataSchemaInterfaceError, match="unsupported .* schema"):
        DataSchemaInterfaceMutationOperators.from_dict(payload)


def test_operator_handle_rejects_family_metadata_mismatch() -> None:
    definition = build_data_schema_interface_operator(_minimal_spec())
    with pytest.raises(DataSchemaInterfaceError, match="does not match"):
        DataSchemaInterfaceOperator(
            _definition=definition,
            family=DataSchemaInterfaceFamily.NULL.value,
            spec_operator_id="ds_drop_required_field",
        )


def test_declaration_backed_projection() -> None:
    catalogue = default_data_schema_interface_operators()
    handle = catalogue.get("ds_unicode_normalization_change")
    backed = handle.as_declaration_backed()
    assert backed.operator_cid == handle.operator_cid
    assert backed.supports_target(_target()) is True


def test_catalogue_identity_matches_content_address() -> None:
    catalogue = default_data_schema_interface_operators()
    recomputed = cid_for_structured(
        catalogue._identity_payload_without_catalogue_id()  # noqa: SLF001
    )
    assert recomputed == catalogue.catalogue_id


def test_all_operators_expect_domain_properties() -> None:
    data_allowed = {
        PropertyClass.DATA_INTEGRITY.value,
        PropertyClass.SCHEMA_CONTRACT.value,
    }
    for definition in data_schema_interface_operator_definitions():
        props = set(definition.expected_violated_property_classes)
        assert definition.likely_equivalent_conditions
        assert_structured_transformation(definition.syntactic_transformation)
        if definition.operator_class == OperatorClass.DATA_SCHEMA.value:
            assert props & data_allowed
        else:
            assert PropertyClass.INTERFACE_CONTRACT.value in props


def test_no_arbitrary_text_edits_in_normative_catalogue() -> None:
    """Acceptance: operators use structured transforms only, never free-form text."""

    for definition in data_schema_interface_operator_definitions():
        transform = definition.syntactic_transformation
        lowered = transform.lower()
        for marker in (
            "arbitrary_text",
            "freeform",
            "free_form",
            "regex_replace_text",
            "unstructured_text",
            "open_ended_string",
            "text_edit_anywhere",
        ):
            assert marker not in lowered
        assert " " not in transform
