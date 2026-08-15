"""Unit tests for AuthorizationPolicyMutationOperators@1 (AAE-018)."""

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
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.authorization_policy import (
    AUTHORIZATION_POLICY_OPERATORS_INTERFACE,
    AUTHORIZATION_POLICY_OPERATORS_SCHEMA,
    DEFAULT_AUTH_RISK_CLASS,
    HIGH_RISK_CLASSES,
    REQUIRED_AUTHORIZATION_POLICY_FAMILIES,
    AuthorizationPolicyCoverageError,
    AuthorizationPolicyError,
    AuthorizationPolicyFamily,
    AuthorizationPolicyMutationOperators,
    AuthorizationPolicyOperator,
    AuthorizationPolicyOperatorSpec,
    AuthorizationPolicyRiskError,
    assert_high_risk_authorization_defaults,
    authorization_policy_families_covered,
    authorization_policy_operator_definitions,
    authorization_policy_operator_specs,
    build_authorization_policy_operator,
    build_authorization_policy_operators,
    default_authorization_policy_operators,
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
        "target_id": "auth_gate_fn",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state-auth"),
        "symbol_ids": ("auth.authorize",),
        "artifact_cids": (_cid("artifact-auth"),),
        "language": "python",
        "artifact_type": "source_module",
        "prerequisites": ("parsed_ast", "symbol_table", "type_check"),
        "risk_class": MutationRiskClass.CRITICAL_SECURITY,
        "risk_weight_bp": 9_000,
        "capsule_cids": (_cid("capsule-auth"),),
        "proof_unit_cids": (_cid("proof-auth"),),
        "source_path": "auth/authorize.py",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationTarget(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Spec and high-risk defaults
# ---------------------------------------------------------------------------


def test_high_risk_classes_are_closed_and_include_default() -> None:
    assert DEFAULT_AUTH_RISK_CLASS in HIGH_RISK_CLASSES
    assert MutationRiskClass.CRITICAL_SECURITY.value in HIGH_RISK_CLASSES
    assert MutationRiskClass.AUTHORIZATION.value in HIGH_RISK_CLASSES
    assert MutationRiskClass.FINANCIAL_LEGAL.value in HIGH_RISK_CLASSES
    assert MutationRiskClass.LOCAL_BUG.value not in HIGH_RISK_CLASSES
    assert MutationRiskClass.LOW.value not in HIGH_RISK_CLASSES


def test_spec_rejects_non_high_risk_class() -> None:
    with pytest.raises(AuthorizationPolicyRiskError, match="high-risk"):
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_low_risk_forbidden",
            family=AuthorizationPolicyFamily.AUTHENTICATION,
            semantic_intent="Must not admit low risk auth operator",
            syntactic_transformation="noop",
            expected_violated_property_classes=(PropertyClass.AUTHORIZATION,),
            risk_class=MutationRiskClass.LOCAL_BUG,
        )


def test_spec_rejects_unknown_family() -> None:
    with pytest.raises(AuthorizationPolicyError, match="unsupported authorization policy family"):
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_unknown_family",
            family="not_a_family",
            semantic_intent="Unknown family must fail closed",
            syntactic_transformation="noop",
            expected_violated_property_classes=(PropertyClass.AUTHORIZATION,),
        )


def test_build_operator_seals_with_authorization_class_and_high_risk() -> None:
    spec = AuthorizationPolicyOperatorSpec(
        operator_id="auth_bypass_authentication",
        family=AuthorizationPolicyFamily.AUTHENTICATION,
        semantic_intent="Bypass authentication gate",
        syntactic_transformation="replace_authentication_predicate_with_true",
        expected_violated_property_classes=(PropertyClass.AUTHORIZATION,),
    )
    sealed = build_authorization_policy_operator(spec)
    assert sealed.operator_class == OperatorClass.AUTHORIZATION_POLICY.value
    assert sealed.risk_class == MutationRiskClass.CRITICAL_SECURITY.value
    assert sealed.deterministic is True
    assert sealed.required_sandbox.network_disabled is True
    assert sealed.required_sandbox.production_credentials_forbidden is True
    assert sealed.rollback.preserves_production is True
    assert sealed.metadata["policy_family"] == "authentication"
    assert_high_risk_authorization_defaults(sealed)


def test_assert_high_risk_rejects_wrong_operator_class() -> None:
    wrong = MutationOperatorDefinition(
        operator_id="control_flow_invert",
        operator_version="1",
        operator_class=OperatorClass.CONTROL_FLOW,
        supported_languages=("python",),
        supported_artifact_types=("source_module",),
        target_prerequisites=("parsed_ast",),
        semantic_intent="Not an auth operator",
        expected_violated_property_classes=(PropertyClass.CONTROL_INVARIANT,),
        risk_class=MutationRiskClass.CRITICAL_SECURITY,
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
    )
    with pytest.raises(AuthorizationPolicyError, match="authorization_policy"):
        assert_high_risk_authorization_defaults(wrong)


# ---------------------------------------------------------------------------
# Normative catalogue coverage
# ---------------------------------------------------------------------------


def test_normative_specs_cover_every_required_family() -> None:
    specs = authorization_policy_operator_specs()
    families = {spec.family for spec in specs}
    assert families == REQUIRED_AUTHORIZATION_POLICY_FAMILIES
    assert AuthorizationPolicyFamily.AUTHENTICATION.value in families
    assert AuthorizationPolicyFamily.TENANT.value in families
    assert AuthorizationPolicyFamily.ATTENUATION.value in families
    assert AuthorizationPolicyFamily.AUDIENCE.value in families
    assert AuthorizationPolicyFamily.EXPIRY.value in families
    assert AuthorizationPolicyFamily.REVOCATION.value in families
    assert AuthorizationPolicyFamily.CONFIRMATION.value in families
    assert AuthorizationPolicyFamily.STALE_DEFAULT_POLICY.value in families
    assert AuthorizationPolicyFamily.PAYMENT_AS_AUTHORITY.value in families


def test_confirmation_family_covers_missing_and_replay() -> None:
    specs = [
        s
        for s in authorization_policy_operator_specs()
        if s.family == AuthorizationPolicyFamily.CONFIRMATION.value
    ]
    ids = {s.operator_id for s in specs}
    assert "auth_missing_confirmation" in ids
    assert "auth_cross_action_confirmation_replay" in ids


def test_stale_default_policy_covers_stale_and_default_allow() -> None:
    specs = [
        s
        for s in authorization_policy_operator_specs()
        if s.family == AuthorizationPolicyFamily.STALE_DEFAULT_POLICY.value
    ]
    ids = {s.operator_id for s in specs}
    assert "auth_stale_policy_or_fencing_token" in ids
    assert "auth_policy_default_to_allow" in ids


def test_payment_as_authority_uses_financial_legal_high_risk() -> None:
    payment = next(
        s
        for s in authorization_policy_operator_specs()
        if s.family == AuthorizationPolicyFamily.PAYMENT_AS_AUTHORITY.value
    )
    assert payment.operator_id == "auth_payment_as_authority"
    assert payment.risk_class == MutationRiskClass.FINANCIAL_LEGAL.value
    assert payment.risk_class in HIGH_RISK_CLASSES


def test_default_catalogue_is_complete_and_high_risk() -> None:
    catalogue = default_authorization_policy_operators()
    assert catalogue.catalogue_id
    assert (
        catalogue.to_dict()["interface_id"]
        == AUTHORIZATION_POLICY_OPERATORS_INTERFACE
    )
    assert catalogue.to_dict()["schema"] == AUTHORIZATION_POLICY_OPERATORS_SCHEMA
    catalogue.assert_complete_coverage()
    assert set(catalogue.families()) == REQUIRED_AUTHORIZATION_POLICY_FAMILIES
    assert authorization_policy_families_covered() == REQUIRED_AUTHORIZATION_POLICY_FAMILIES
    for operator in catalogue:
        assert operator.definition.operator_class == (
            OperatorClass.AUTHORIZATION_POLICY.value
        )
        assert operator.definition.risk_class in HIGH_RISK_CLASSES
        assert operator.definition.deterministic is True
        assert operator.family in REQUIRED_AUTHORIZATION_POLICY_FAMILIES
        assert_high_risk_authorization_defaults(operator.definition)


def test_expected_operator_ids_present() -> None:
    ids = set(default_authorization_policy_operators().operator_ids())
    expected = {
        "auth_bypass_authentication",
        "auth_caller_selected_tenant",
        "auth_missing_attenuation",
        "auth_wrong_audience",
        "auth_accept_expired_delegation",
        "auth_accept_revoked_capability",
        "auth_missing_confirmation",
        "auth_cross_action_confirmation_replay",
        "auth_stale_policy_or_fencing_token",
        "auth_policy_default_to_allow",
        "auth_payment_as_authority",
    }
    assert expected <= ids


def test_catalogue_identity_is_deterministic() -> None:
    left = default_authorization_policy_operators()
    right = default_authorization_policy_operators()
    assert left.catalogue_id == right.catalogue_id
    assert left.operator_cids() == right.operator_cids()
    assert left.identity_payload() == right.identity_payload()


def test_catalogue_round_trip_preserves_identity() -> None:
    original = default_authorization_policy_operators()
    restored = AuthorizationPolicyMutationOperators.from_dict(original.to_dict())
    assert restored.catalogue_id == original.catalogue_id
    assert restored.operator_ids() == original.operator_ids()
    assert restored.operator_cids() == original.operator_cids()
    assert set(restored.families()) == set(original.families())


def test_definitions_helper_matches_catalogue() -> None:
    defs = authorization_policy_operator_definitions()
    catalogue = default_authorization_policy_operators()
    assert [d.operator_cid for d in defs] == list(catalogue.operator_cids())
    assert all(
        d.operator_class == OperatorClass.AUTHORIZATION_POLICY.value for d in defs
    )


# ---------------------------------------------------------------------------
# Lookup, target support, rollback
# ---------------------------------------------------------------------------


def test_get_and_get_by_cid() -> None:
    catalogue = default_authorization_policy_operators()
    op = catalogue.get("auth_bypass_authentication")
    assert op.family == AuthorizationPolicyFamily.AUTHENTICATION.value
    by_cid = catalogue.get_by_cid(op.operator_cid)
    assert by_cid.operator_id == op.operator_id
    assert "auth_bypass_authentication" in catalogue
    assert op.operator_cid in catalogue
    with pytest.raises(AuthorizationPolicyError, match="unknown operator_id"):
        catalogue.get("auth_does_not_exist")
    with pytest.raises(AuthorizationPolicyError, match="unknown operator_cid"):
        catalogue.get_by_cid(_cid("missing-operator"))


def test_operators_for_family_and_target() -> None:
    catalogue = default_authorization_policy_operators()
    tenant_ops = catalogue.operators_for_family(AuthorizationPolicyFamily.TENANT)
    assert len(tenant_ops) == 1
    assert tenant_ops[0].operator_id == "auth_caller_selected_tenant"

    target = _target()
    supporting = catalogue.operators_for_target(target)
    assert len(supporting) == len(catalogue)
    assert all(op.supports_target(target) for op in supporting)

    unsupported = catalogue.operators_for_target(_target(language="cobol"))
    assert unsupported == ()


def test_rollback_record_is_deterministic() -> None:
    catalogue = default_authorization_policy_operators()
    target = _target()
    pre = _cid("pre-mutation-auth")
    first = catalogue.rollback_record(
        "auth_missing_attenuation",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    second = catalogue.rollback_record(
        "auth_missing_attenuation",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    assert isinstance(first, OperatorRollbackRecord)
    assert first.record_cid == second.record_cid
    assert first.preserves_production is True
    assert first.requires_clean_worktree is True
    assert first.operator_id == "auth_missing_attenuation"


def test_rollback_record_fails_closed_for_unsupported_target() -> None:
    catalogue = default_authorization_policy_operators()
    with pytest.raises(Exception, match="does not support|language|artifact"):
        catalogue.rollback_record(
            "auth_bypass_authentication",
            pre_mutation_state_cid=_cid("pre"),
            target=_target(language="cobol"),
        )


# ---------------------------------------------------------------------------
# Registry projection
# ---------------------------------------------------------------------------


def test_as_registry_admits_all_operators() -> None:
    catalogue = default_authorization_policy_operators()
    registry = catalogue.as_registry()
    assert len(registry) == len(catalogue)
    for operator_id in catalogue.operator_ids():
        admitted = registry.get(operator_id)
        assert admitted.operator_class == OperatorClass.AUTHORIZATION_POLICY.value
        assert admitted.risk_class in HIGH_RISK_CLASSES


def test_register_into_builder() -> None:
    catalogue = default_authorization_policy_operators()
    builder = MutationOperatorRegistryBuilder()
    sealed = catalogue.register_into(builder)
    assert len(sealed) == len(catalogue)
    registry = builder.build()
    assert set(registry.operator_ids()) == set(catalogue.operator_ids())


def test_registry_dispatch_for_auth_target() -> None:
    catalogue = default_authorization_policy_operators()
    registry = catalogue.as_registry()
    target = _target()
    matches = registry.dispatch(
        target, operator_class=OperatorClass.AUTHORIZATION_POLICY
    )
    assert len(matches) == len(catalogue)
    one = registry.dispatch_one(
        target,
        operator_id="auth_payment_as_authority",
        operator_class=OperatorClass.AUTHORIZATION_POLICY,
    )
    assert one.risk_class == MutationRiskClass.FINANCIAL_LEGAL.value


# ---------------------------------------------------------------------------
# Coverage / negative assembly
# ---------------------------------------------------------------------------


def test_incomplete_catalogue_rejected() -> None:
    auth_only = AuthorizationPolicyOperatorSpec(
        operator_id="auth_bypass_authentication",
        family=AuthorizationPolicyFamily.AUTHENTICATION,
        semantic_intent="Only authentication",
        syntactic_transformation="replace_authentication_predicate_with_true",
        expected_violated_property_classes=(PropertyClass.AUTHORIZATION,),
    )
    with pytest.raises(AuthorizationPolicyCoverageError, match="missing required families"):
        build_authorization_policy_operators([auth_only])

    sealed = build_authorization_policy_operator(auth_only)
    handle = AuthorizationPolicyOperator(
        _definition=sealed,
        family=AuthorizationPolicyFamily.AUTHENTICATION.value,
        spec_operator_id="auth_bypass_authentication",
    )
    with pytest.raises(AuthorizationPolicyCoverageError, match="missing required families"):
        AuthorizationPolicyMutationOperators(operators=(handle,))


def test_duplicate_operator_id_rejected() -> None:
    specs = list(authorization_policy_operator_specs())
    specs.append(
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_bypass_authentication",
            family=AuthorizationPolicyFamily.AUTHENTICATION,
            semantic_intent="Duplicate id must fail",
            syntactic_transformation="replace_authentication_predicate_with_true_v2",
            expected_violated_property_classes=(PropertyClass.AUTHORIZATION,),
        )
    )
    with pytest.raises(AuthorizationPolicyError, match="duplicate operator_id"):
        build_authorization_policy_operators(specs)


def test_from_dict_rejects_unknown_fields() -> None:
    payload = default_authorization_policy_operators().to_dict()
    payload["unexpected_field"] = True
    with pytest.raises(AuthorizationPolicyError, match="unknown fields"):
        AuthorizationPolicyMutationOperators.from_dict(payload)


def test_from_dict_rejects_schema_mismatch() -> None:
    payload = default_authorization_policy_operators().to_dict()
    payload["schema"] = "wrong-schema@1"
    with pytest.raises(AuthorizationPolicyError, match="unsupported .* schema"):
        AuthorizationPolicyMutationOperators.from_dict(payload)


def test_operator_handle_rejects_family_metadata_mismatch() -> None:
    definition = build_authorization_policy_operator(
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_bypass_authentication",
            family=AuthorizationPolicyFamily.AUTHENTICATION,
            semantic_intent="Bypass authentication",
            syntactic_transformation="replace_authentication_predicate_with_true",
            expected_violated_property_classes=(PropertyClass.AUTHORIZATION,),
        )
    )
    with pytest.raises(AuthorizationPolicyError, match="does not match"):
        AuthorizationPolicyOperator(
            _definition=definition,
            family=AuthorizationPolicyFamily.TENANT.value,
            spec_operator_id="auth_bypass_authentication",
        )


def test_declaration_backed_projection() -> None:
    catalogue = default_authorization_policy_operators()
    handle = catalogue.get("auth_wrong_audience")
    backed = handle.as_declaration_backed()
    assert backed.operator_cid == handle.operator_cid
    assert backed.supports_target(_target()) is True


def test_catalogue_identity_matches_content_address() -> None:
    catalogue = default_authorization_policy_operators()
    recomputed = cid_for_structured(
        catalogue._identity_payload_without_catalogue_id()  # noqa: SLF001
    )
    assert recomputed == catalogue.catalogue_id


def test_all_operators_expect_authorization_or_policy_properties() -> None:
    for definition in authorization_policy_operator_definitions():
        props = set(definition.expected_violated_property_classes)
        assert props & {
            PropertyClass.AUTHORIZATION.value,
            PropertyClass.POLICY_CONSTRAINT.value,
        }


def test_sandbox_and_scope_are_tight_for_security_operators() -> None:
    for definition in authorization_policy_operator_definitions():
        assert definition.scope_limits.allow_verifier_mutation is False
        assert definition.scope_limits.allow_cross_module is False
        assert definition.scope_limits.max_files == 1
        assert definition.max_mutants_per_target <= 8
        assert definition.required_sandbox.disposable_worktree_required is True
