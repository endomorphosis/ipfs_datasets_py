"""Unit tests for MutationOperatorRegistry@1 and rollback contracts (AAE-014)."""

from __future__ import annotations

import copy

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MAX_MUTANTS_PER_TARGET,
    MutationContractError,
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
    DeclarationBackedOperator,
    OperatorBaseError,
    OperatorBoundError,
    OperatorDeclarationError,
    OperatorRollbackRecord,
    RegisteredOperator,
    assert_operator_bounded,
    canonicalize_operator_declaration,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.registry import (
    MUTATION_OPERATOR_REGISTRY_INTERFACE,
    MUTATION_OPERATOR_REGISTRY_SCHEMA,
    DuplicateOperatorError,
    MutationOperatorRegistry,
    MutationOperatorRegistryBuilder,
    OperatorRegistryError,
    UnknownOperatorError,
    UnsupportedTargetError,
    build_mutation_operator_registry,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _rollback(**overrides: object) -> RollbackDeclaration:
    fields = {
        "strategy": RollbackStrategy.WORKTREE_DISCARD,
        "requires_clean_worktree": True,
        "preserves_production": True,
    }
    fields.update(overrides)
    return RollbackDeclaration(**fields)  # type: ignore[arg-type]


def _sandbox(**overrides: object) -> SandboxRequirement:
    fields = {
        "mode": SandboxMode.DISPOSABLE_WORKTREE,
        "network_disabled": True,
        "production_credentials_forbidden": True,
        "disposable_worktree_required": True,
    }
    fields.update(overrides)
    return SandboxRequirement(**fields)  # type: ignore[arg-type]


def _scope(**overrides: object) -> ScopeLimits:
    fields = {
        "max_files": 1,
        "max_symbols": 2,
        "max_span_lines": 64,
        "allow_cross_module": False,
        "allow_verifier_mutation": False,
    }
    fields.update(overrides)
    return ScopeLimits(**fields)  # type: ignore[arg-type]


def _operator(**overrides: object) -> MutationOperatorDefinition:
    fields = {
        "operator_id": "control_flow_invert",
        "operator_version": "1",
        "operator_class": OperatorClass.CONTROL_FLOW,
        "supported_languages": ("python",),
        "supported_artifact_types": ("source_module",),
        "target_prerequisites": ("parsed_ast", "symbol_table"),
        "semantic_intent": "Invert a boolean condition controlling a branch",
        "expected_violated_property_classes": (PropertyClass.CONTROL_INVARIANT,),
        "risk_class": MutationRiskClass.LOCAL_BUG,
        "likely_equivalent_conditions": ("condition_always_true",),
        "syntactic_transformation": "replace_if_test_with_not_test",
        "scope_limits": _scope(),
        "rollback": _rollback(),
        "required_sandbox": _sandbox(),
        "max_mutants_per_target": 8,
        "deterministic": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationOperatorDefinition(**fields)  # type: ignore[arg-type]


def _target(**overrides: object) -> MutationTarget:
    fields = {
        "target_id": "mod_fn",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state"),
        "symbol_ids": ("mod.fn",),
        "artifact_cids": (_cid("artifact-a"),),
        "language": "python",
        "artifact_type": "source_module",
        "prerequisites": ("parsed_ast", "symbol_table", "type_check"),
        "risk_class": MutationRiskClass.LOCAL_BUG,
        "risk_weight_bp": 2_500,
        "capsule_cids": (_cid("capsule-a"),),
        "proof_unit_cids": (_cid("proof-unit-a"),),
        "source_path": "mod.py",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationTarget(**fields)  # type: ignore[arg-type]


def _operator_map(**overrides: object) -> dict[str, object]:
    """Return a raw declaration map (constructor path; may be invalid).

    Does not pre-construct ``MutationOperatorDefinition`` so negative cases
    (versionless, unbounded, unsafe rollback) can be submitted to the registry
    admission surface without failing earlier in the helper.
    """

    payload: dict[str, object] = {
        "operator_id": "control_flow_invert",
        "operator_version": "1",
        "operator_class": OperatorClass.CONTROL_FLOW.value,
        "supported_languages": ["typescript", "python"],
        "supported_artifact_types": ["source_module"],
        "target_prerequisites": ["symbol_table", "parsed_ast"],
        "semantic_intent": "Invert a boolean condition controlling a branch",
        "expected_violated_property_classes": [
            PropertyClass.CONTROL_INVARIANT.value
        ],
        "risk_class": MutationRiskClass.LOCAL_BUG.value,
        "likely_equivalent_conditions": ["condition_always_true"],
        "syntactic_transformation": "replace_if_test_with_not_test",
        "scope_limits": {
            "max_files": 1,
            "max_symbols": 2,
            "max_span_lines": 64,
            "allow_cross_module": False,
            "allow_verifier_mutation": False,
        },
        "rollback": {
            "strategy": RollbackStrategy.WORKTREE_DISCARD.value,
            "requires_clean_worktree": True,
            "preserves_production": True,
        },
        "required_sandbox": {
            "mode": SandboxMode.DISPOSABLE_WORKTREE.value,
            "network_disabled": True,
            "production_credentials_forbidden": True,
            "disposable_worktree_required": True,
        },
        "max_mutants_per_target": 8,
        "deterministic": True,
        "notes": None,
        "metadata": {},
    }
    for key, value in overrides.items():
        payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Canonicalization and bounds
# ---------------------------------------------------------------------------


def test_canonicalize_operator_declaration_is_stable() -> None:
    raw = _operator_map(
        supported_languages=("typescript", "python"),
        target_prerequisites=("symbol_table", "parsed_ast"),
    )
    first = canonicalize_operator_declaration(raw)
    second = canonicalize_operator_declaration(raw)
    third = canonicalize_operator_declaration(first)
    assert first.operator_cid == second.operator_cid == third.operator_cid
    assert list(first.supported_languages) == ["python", "typescript"]
    assert list(first.target_prerequisites) == ["parsed_ast", "symbol_table"]
    assert first.deterministic is True


def test_canonicalize_rejects_versionless_operator() -> None:
    with pytest.raises(
        (OperatorDeclarationError, OperatorBoundError, MutationContractError),
        match="version|nonempty",
    ):
        canonicalize_operator_declaration(_operator_map(operator_version=""))


def test_assert_operator_bounded_rejects_unbounded_mutants() -> None:
    # Constructor already rejects 0 / over-max; exercise the bound helper
    # with a monkeypatched-like sealed definition via normal construction path.
    operator = _operator(max_mutants_per_target=MAX_MUTANTS_PER_TARGET)
    assert_operator_bounded(operator)
    with pytest.raises(MutationContractError, match="positive integer|exceeds maximum"):
        _operator(max_mutants_per_target=0)
    with pytest.raises(MutationContractError, match="exceeds maximum"):
        _operator(max_mutants_per_target=MAX_MUTANTS_PER_TARGET + 1)


def test_assert_operator_bounded_rejects_nondeterministic() -> None:
    with pytest.raises(MutationContractError, match="deterministic must be true"):
        _operator(deterministic=False)


def test_declaration_backed_operator_seals_definition() -> None:
    handle = DeclarationBackedOperator(_definition=_operator())
    assert handle.operator_id == "control_flow_invert"
    assert handle.supports_target(_target()) is True
    handle.assert_supports_target(_target())
    with pytest.raises(OperatorBaseError, match="does not support"):
        handle.assert_supports_target(_target(language="rust"))


# ---------------------------------------------------------------------------
# Registry admission: duplicates / versionless / unbounded
# ---------------------------------------------------------------------------


def test_registry_rejects_duplicate_operator_id_version() -> None:
    builder = MutationOperatorRegistryBuilder()
    builder.register(_operator())
    with pytest.raises(DuplicateOperatorError, match="duplicate operator"):
        builder.register(_operator())


def test_registry_rejects_duplicate_operator_cid_across_ids() -> None:
    # Same sealed identity cannot be admitted under a second registration path.
    sealed = canonicalize_operator_declaration(_operator())
    builder = MutationOperatorRegistryBuilder()
    builder.register(sealed)
    with pytest.raises(DuplicateOperatorError, match="duplicate operator"):
        builder.register(sealed.to_dict())


def test_registry_rejects_versionless_via_builder() -> None:
    builder = MutationOperatorRegistryBuilder()
    with pytest.raises(
        (OperatorRegistryError, OperatorDeclarationError, MutationContractError),
        match="version|nonempty",
    ):
        builder.register(_operator_map(operator_version=""))


def test_registry_rejects_unbounded_via_max_mutants() -> None:
    builder = MutationOperatorRegistryBuilder()
    with pytest.raises(
        (OperatorRegistryError, OperatorDeclarationError, MutationContractError),
        match="positive integer|unbounded|exceeds",
    ):
        builder.register(_operator_map(max_mutants_per_target=0))


def test_registry_rejects_unbounded_via_verifier_mutation() -> None:
    builder = MutationOperatorRegistryBuilder()
    with pytest.raises(
        (OperatorRegistryError, OperatorDeclarationError, MutationContractError),
        match="verifier_mutation|unbounded",
    ):
        builder.register(
            _operator_map(
                scope_limits={
                    "max_files": 1,
                    "max_symbols": 1,
                    "max_span_lines": 8,
                    "allow_cross_module": False,
                    "allow_verifier_mutation": True,
                }
            )
        )


def test_registry_rejects_missing_rollback_production_safety() -> None:
    builder = MutationOperatorRegistryBuilder()
    with pytest.raises(
        (OperatorRegistryError, OperatorDeclarationError, MutationContractError),
        match="preserve production|production",
    ):
        builder.register(
            _operator_map(
                rollback={
                    "strategy": "worktree_discard",
                    "requires_clean_worktree": True,
                    "preserves_production": False,
                }
            )
        )


def test_registry_from_operators_canonicalizes_and_sorts() -> None:
    later = _operator(
        operator_id="zeta_operator",
        operator_version="1",
        semantic_intent="Zeta class sentinel",
        syntactic_transformation="zeta_transform",
    )
    earlier = _operator(
        operator_id="alpha_operator",
        operator_version="2",
        semantic_intent="Alpha class sentinel",
        syntactic_transformation="alpha_transform",
    )
    mid = _operator(
        operator_id="alpha_operator",
        operator_version="1",
        semantic_intent="Alpha class sentinel v1",
        syntactic_transformation="alpha_transform_v1",
    )
    registry = MutationOperatorRegistry.from_operators((later, mid, earlier))
    ids = [(op.operator_id, op.operator_version) for op in registry.list_operators()]
    assert ids == [
        ("alpha_operator", "1"),
        ("alpha_operator", "2"),
        ("zeta_operator", "1"),
    ]
    assert registry.registry_id == cid_for_structured(
        registry._identity_payload_without_registry_id()  # noqa: SLF001
    )


def test_registry_identity_is_deterministic_for_same_catalogue() -> None:
    ops = (
        _operator(operator_id="a_op", semantic_intent="A", syntactic_transformation="a"),
        _operator(operator_id="b_op", semantic_intent="B", syntactic_transformation="b"),
    )
    left = build_mutation_operator_registry(ops)
    right = build_mutation_operator_registry(reversed(ops))
    assert left.registry_id == right.registry_id
    assert left.operator_cids() == right.operator_cids()
    assert left.to_dict()["interface_id"] == MUTATION_OPERATOR_REGISTRY_INTERFACE
    assert left.to_dict()["schema"] == MUTATION_OPERATOR_REGISTRY_SCHEMA


def test_registry_round_trip_dict() -> None:
    registry = build_mutation_operator_registry((_operator(),))
    restored = MutationOperatorRegistry.from_dict(registry.to_dict())
    assert restored.registry_id == registry.registry_id
    assert restored.list_operators()[0].operator_cid == registry.list_operators()[0].operator_cid


def test_registry_forged_registry_id_fails_closed() -> None:
    registry = build_mutation_operator_registry((_operator(),))
    payload = registry.to_dict()
    payload["registry_id"] = _cid("forged-registry")
    with pytest.raises(OperatorRegistryError, match="registry_id identity mismatch"):
        MutationOperatorRegistry.from_dict(payload)


# ---------------------------------------------------------------------------
# Dispatch: only supported targets
# ---------------------------------------------------------------------------


def test_dispatch_returns_only_supported_operators() -> None:
    python_op = _operator(
        operator_id="py_invert",
        supported_languages=("python",),
        supported_artifact_types=("source_module",),
        target_prerequisites=("parsed_ast",),
    )
    rust_op = _operator(
        operator_id="rs_invert",
        supported_languages=("rust",),
        supported_artifact_types=("source_module",),
        target_prerequisites=("parsed_ast",),
        semantic_intent="Rust invert",
        syntactic_transformation="rust_invert",
    )
    registry = build_mutation_operator_registry((python_op, rust_op))
    target = _target(
        language="python",
        artifact_type="source_module",
        prerequisites=("parsed_ast", "type_check"),
    )
    matched = registry.dispatch(target)
    assert [item.operator_id for item in matched] == ["py_invert"]
    assert registry.operators_for_target(_target(language="go")) == ()


def test_dispatch_explicit_unsupported_operator_fails_closed() -> None:
    registry = build_mutation_operator_registry((_operator(),))
    target = _target(language="rust")
    with pytest.raises(UnsupportedTargetError, match="does not support"):
        registry.dispatch(target, operator_id="control_flow_invert")


def test_dispatch_unknown_operator_fails_closed() -> None:
    registry = build_mutation_operator_registry((_operator(),))
    with pytest.raises(UnknownOperatorError, match="unknown operator"):
        registry.dispatch(_target(), operator_id="missing_operator")


def test_dispatch_require_nonempty_fails_when_no_support() -> None:
    registry = build_mutation_operator_registry(
        [_operator(supported_languages=("go",))]
    )
    with pytest.raises(UnsupportedTargetError, match="no registered operator"):
        registry.dispatch(_target(language="python"))
    assert (
        registry.dispatch(_target(language="python"), require_nonempty=False) == ()
    )


def test_dispatch_one_requires_unique_match() -> None:
    op_a = _operator(
        operator_id="flow_a",
        operator_class=OperatorClass.CONTROL_FLOW,
        target_prerequisites=("parsed_ast",),
    )
    op_b = _operator(
        operator_id="flow_b",
        operator_class=OperatorClass.CONTROL_FLOW,
        semantic_intent="Second flow operator",
        syntactic_transformation="second_flow",
        target_prerequisites=("parsed_ast",),
    )
    registry = build_mutation_operator_registry((op_a, op_b))
    target = _target(prerequisites=("parsed_ast",))
    with pytest.raises(OperatorRegistryError, match="exactly one"):
        registry.dispatch_one(target)
    single = registry.dispatch_one(target, operator_id="flow_a")
    assert single.operator_id == "flow_a"


def test_dispatch_filters_by_operator_class() -> None:
    control = _operator(
        operator_id="cf_op",
        operator_class=OperatorClass.CONTROL_FLOW,
        target_prerequisites=(),
    )
    auth = _operator(
        operator_id="auth_op",
        operator_class=OperatorClass.AUTHORIZATION_POLICY,
        semantic_intent="Weaken auth check",
        syntactic_transformation="drop_auth",
        expected_violated_property_classes=(PropertyClass.AUTHORIZATION,),
        risk_class=MutationRiskClass.AUTHORIZATION,
        target_prerequisites=(),
    )
    registry = build_mutation_operator_registry((control, auth))
    target = _target(prerequisites=())
    matched = registry.dispatch(
        target, operator_class=OperatorClass.AUTHORIZATION_POLICY
    )
    assert [item.operator_id for item in matched] == ["auth_op"]


def test_get_ambiguous_version_fails_closed() -> None:
    v1 = _operator(operator_version="1")
    v2 = _operator(
        operator_version="2",
        semantic_intent="Invert condition v2",
        syntactic_transformation="replace_if_test_with_not_test_v2",
    )
    registry = build_mutation_operator_registry((v1, v2))
    with pytest.raises(OperatorRegistryError, match="ambiguous"):
        registry.get("control_flow_invert")
    assert registry.get("control_flow_invert", "2").operator_version == "2"
    versions = registry.get_versions("control_flow_invert")
    assert [item.operator_version for item in versions] == ["1", "2"]


# ---------------------------------------------------------------------------
# Deterministic rollback records
# ---------------------------------------------------------------------------


def test_rollback_record_is_deterministic() -> None:
    registry = build_mutation_operator_registry((_operator(),))
    target = _target()
    pre = _cid("pre-mutation-state")
    left = registry.rollback_record(
        "control_flow_invert",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    right = registry.rollback_record(
        "control_flow_invert",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    assert left.record_cid == right.record_cid
    assert left.preserves_production is True
    assert left.requires_clean_worktree is True
    assert left.strategy == RollbackStrategy.WORKTREE_DISCARD.value
    assert left.operator_cid == registry.get("control_flow_invert").operator_cid
    assert left.target_id == target.target_id
    assert left.target_cid == target.target_cid
    # Scope defaults from target when not provided.
    assert left.scope_paths == ("mod.py",)
    assert left.scope_symbol_ids == ("mod.fn",)


def test_rollback_record_round_trip_and_forged_cid() -> None:
    registry = build_mutation_operator_registry((_operator(),))
    record = registry.rollback_record(
        "control_flow_invert",
        pre_mutation_state_cid=_cid("pre"),
    )
    restored = OperatorRollbackRecord.from_dict(record.to_dict())
    assert restored.record_cid == record.record_cid
    forged = record.to_dict()
    forged["record_cid"] = _cid("forged-record")
    with pytest.raises(OperatorBaseError, match="record_cid identity mismatch"):
        OperatorRollbackRecord.from_dict(forged)


def test_rollback_record_changes_with_pre_state() -> None:
    registry = build_mutation_operator_registry((_operator(),))
    a = registry.rollback_record(
        "control_flow_invert", pre_mutation_state_cid=_cid("pre-a")
    )
    b = registry.rollback_record(
        "control_flow_invert", pre_mutation_state_cid=_cid("pre-b")
    )
    assert a.record_cid != b.record_cid


def test_rollback_record_rejects_production_unsafe_flags() -> None:
    operator = _operator()
    with pytest.raises(OperatorBaseError, match="preserve production"):
        OperatorRollbackRecord(
            operator_id=operator.operator_id,
            operator_version=operator.operator_version,
            operator_cid=operator.operator_cid,
            strategy=operator.rollback.strategy,
            rollback_declaration_cid=operator.rollback.rollback_cid,
            pre_mutation_state_cid=_cid("pre"),
            preserves_production=False,
        )


def test_rollback_record_for_definition_requires_registration() -> None:
    registry = build_mutation_operator_registry((_operator(),))
    foreign = _operator(
        operator_id="foreign_op",
        semantic_intent="Foreign",
        syntactic_transformation="foreign",
    )
    with pytest.raises(UnknownOperatorError):
        registry.rollback_record_for_definition(
            foreign, pre_mutation_state_cid=_cid("pre")
        )
    admitted = registry.get("control_flow_invert")
    record = registry.rollback_record_for_definition(
        admitted, pre_mutation_state_cid=_cid("pre"), target=_target()
    )
    assert record.operator_id == "control_flow_invert"


def test_rollback_record_scope_lists_are_sorted_and_unique() -> None:
    registry = build_mutation_operator_registry((_operator(),))
    record = registry.rollback_record(
        "control_flow_invert",
        pre_mutation_state_cid=_cid("pre"),
        scope_paths=("b.py", "a.py"),
        scope_symbol_ids=("z.fn", "a.fn"),
    )
    assert record.scope_paths == ("a.py", "b.py")
    assert record.scope_symbol_ids == ("a.fn", "z.fn")
    with pytest.raises(OperatorRegistryError, match="duplicates"):
        registry.rollback_record(
            "control_flow_invert",
            pre_mutation_state_cid=_cid("pre"),
            scope_paths=("a.py", "a.py"),
        )


def test_declaration_backed_operator_build_rollback_record() -> None:
    handle = DeclarationBackedOperator(_definition=_operator())
    record = handle.build_rollback_record(
        pre_mutation_state_cid=_cid("pre"),
        target=_target(),
    )
    assert record.record_cid == OperatorRollbackRecord.from_operator(
        handle.definition,
        pre_mutation_state_cid=_cid("pre"),
        target=_target(),
    ).record_cid


# ---------------------------------------------------------------------------
# Registered operator bindings
# ---------------------------------------------------------------------------


def test_registered_operators_have_stable_indices_and_cids() -> None:
    registry = build_mutation_operator_registry(
        (
            _operator(operator_id="b_op", semantic_intent="B", syntactic_transformation="b"),
            _operator(operator_id="a_op", semantic_intent="A", syntactic_transformation="a"),
        )
    )
    bindings = registry.registered_operators()
    assert [item.operator_id for item in bindings] == ["a_op", "b_op"]
    assert [item.registration_index for item in bindings] == [0, 1]
    first = bindings[0]
    restored = RegisteredOperator.from_dict(first.to_dict())
    assert restored.registration_cid == first.registration_cid


def test_empty_registry_is_valid_and_deterministic() -> None:
    left = MutationOperatorRegistry.empty()
    right = MutationOperatorRegistry.empty()
    assert len(left) == 0
    assert left.registry_id == right.registry_id
    with pytest.raises(UnknownOperatorError):
        left.get("any")


def test_registry_contains_and_get_by_cid() -> None:
    operator = _operator()
    registry = build_mutation_operator_registry((operator,))
    assert operator.operator_cid in registry
    assert "control_flow_invert" in registry
    assert registry.get_by_cid(operator.operator_cid).operator_id == "control_flow_invert"
    with pytest.raises(UnknownOperatorError):
        registry.get_by_cid(_cid("missing-operator"))


def test_builder_register_many_and_as_mutation_operators() -> None:
    builder = MutationOperatorRegistryBuilder()
    sealed = builder.register_many(
        (
            _operator(operator_id="one", semantic_intent="One", syntactic_transformation="one"),
            DeclarationBackedOperator(
                _definition=_operator(
                    operator_id="two",
                    semantic_intent="Two",
                    syntactic_transformation="two",
                )
            ),
        )
    )
    assert len(sealed) == 2
    registry = builder.build()
    handles = registry.as_mutation_operators()
    assert len(handles) == 2
    assert all(isinstance(item, DeclarationBackedOperator) for item in handles)


def test_canonicalize_mapping_without_cid_fields() -> None:
    payload = _operator_map()
    sealed = canonicalize_operator_declaration(payload)
    again = canonicalize_operator_declaration(copy.deepcopy(payload))
    assert sealed.operator_cid == again.operator_cid
    assert sealed.operator_class == OperatorClass.CONTROL_FLOW.value


def test_registry_rejects_non_mapping_declaration() -> None:
    builder = MutationOperatorRegistryBuilder()
    with pytest.raises(OperatorRegistryError):
        builder.register(object())  # type: ignore[arg-type]
