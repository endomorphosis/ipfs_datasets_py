"""Contract vectors for mutation operator/target/candidate/policy/plan models (AAE-008)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    ArtifactProvenance,
    AssuranceArtifactHeader,
    AssuranceTerminalStatus,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    VersionBinding,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    CampaignBudget,
    MAX_MUTANTS_PER_TARGET,
    MutationCampaignPlan,
    MutationCampaignPolicy,
    MutationCandidate,
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
    SeedConfigBinding,
    assert_budget_admits_counts,
    assert_operator_supports_target,
    mutation_risk_classes,
    operator_classes,
    property_classes,
    rollback_strategies,
    sandbox_modes,
    verify_operator_identity,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": "mutation_campaign",
        "generator_version": "1.0.0",
        "interface_id": "generate_mutation_candidates@1",
    }
    fields.update(overrides)
    return GeneratorIdentity(**fields)  # type: ignore[arg-type]


def _versions(**overrides: object) -> VersionBinding:
    fields = {
        "operator_id": "control_flow_invert",
        "operator_version": "1",
        "campaign_policy_id": "default_campaign",
        "campaign_policy_version": "1.0.0",
        "generator": _generator(),
    }
    fields.update(overrides)
    return VersionBinding(**fields)  # type: ignore[arg-type]


def _provenance(**overrides: object) -> ArtifactProvenance:
    fields = {
        "producer_id": "adversarial_assurance",
        "producer_version": "1",
        "execution_mode": ExecutionMode.LIVE,
        "authority_source": AuthoritySource.DETERMINISTIC,
        "input_cids": (_cid("input-a"),),
        "tool_ids": ("mutator.v1",),
        "policy_cid": _cid("policy"),
        "notes": None,
    }
    fields.update(overrides)
    return ArtifactProvenance(**fields)  # type: ignore[arg-type]


def _header(artifact_kind: str, **overrides: object) -> AssuranceArtifactHeader:
    fields = {
        "artifact_kind": artifact_kind,
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state"),
        "target_symbol_ids": ("mod.fn",),
        "target_artifact_cids": (_cid("artifact-a"),),
        "capsule_cids": (_cid("capsule-a"),),
        "proof_unit_cids": (_cid("proof-unit-a"),),
        "environment_cid": _cid("environment"),
        "dependency_lock_cid": _cid("dependency-lock"),
        "versions": _versions(),
        "provenance": _provenance(),
        "terminal_status": AssuranceTerminalStatus.COMPLETE,
        "receipt_cids": (_cid("receipt-a"),),
        "proof_cids": (_cid("proof-a"),),
        "metadata": {"risk_class": "local_bug"},
    }
    fields.update(overrides)
    return AssuranceArtifactHeader(**fields)  # type: ignore[arg-type]


def _seed_config(**overrides: object) -> SeedConfigBinding:
    fields = {
        "seed": 42,
        "config": {"max_depth": 2, "operator_budget": 4},
    }
    fields.update(overrides)
    return SeedConfigBinding(**fields)  # type: ignore[arg-type]


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


def _budget(**overrides: object) -> CampaignBudget:
    fields = {
        "max_total_candidates": 64,
        "max_candidates_per_target": 8,
        "max_candidates_per_operator": 16,
        "max_targets": 32,
        "max_operators": 16,
        "max_execution_seconds": 3_600,
        "max_worktrees": 8,
    }
    fields.update(overrides)
    return CampaignBudget(**fields)  # type: ignore[arg-type]


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


def _candidate(**overrides: object) -> MutationCandidate:
    operator = _operator()
    target = _target()
    fields = {
        "header": _header("mutation_candidate"),
        "candidate_id": "cand_control_flow_invert_0",
        "operator_id": operator.operator_id,
        "operator_version": operator.operator_version,
        "operator_cid": operator.operator_cid,
        "target_id": target.target_id,
        "target_cid": target.target_cid,
        "seed_config": _seed_config(),
        "source_root_cid": _cid("source-root"),
        "repository_state_cid": _cid("repo-state"),
        "transformation_summary": "invert if-test at mod.fn:12",
        "expected_violated_property_classes": (PropertyClass.CONTROL_INVARIANT,),
        "risk_class": MutationRiskClass.LOCAL_BUG,
        "likely_equivalent": False,
        "scope_symbol_ids": ("mod.fn",),
        "scope_paths": ("mod.py",),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationCandidate(**fields)  # type: ignore[arg-type]


def _policy(**overrides: object) -> MutationCampaignPolicy:
    operator = _operator()
    fields = {
        "header": _header("mutation_campaign_policy"),
        "policy_id": "default_campaign",
        "policy_version": "1.0.0",
        "admitted_operator_classes": (
            OperatorClass.CONTROL_FLOW,
            OperatorClass.AUTHORIZATION_POLICY,
        ),
        "admitted_risk_classes": (
            MutationRiskClass.LOCAL_BUG,
            MutationRiskClass.CRITICAL_SECURITY,
            MutationRiskClass.AUTHORIZATION,
        ),
        "budget": _budget(),
        "seed_config": _seed_config(seed=7, config={"mode": "bounded"}),
        "require_disposable_worktree": True,
        "require_network_disabled": True,
        "require_rollback": True,
        "require_deterministic_seed": True,
        "full_suite_fallback_enabled": True,
        "held_out_partition_required": True,
        "operator_cids": (operator.operator_cid,),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationCampaignPolicy(**fields)  # type: ignore[arg-type]


def _plan(**overrides: object) -> MutationCampaignPlan:
    policy = _policy()
    target = _target()
    operator = _operator()
    candidate = _candidate()
    fields = {
        "header": _header("mutation_campaign_plan"),
        "plan_id": "plan_default_1",
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_cid": policy.policy_cid,
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state"),
        "baseline_receipt_cid": _cid("baseline-receipt"),
        "seed_config": policy.seed_config,
        "budget": policy.budget,
        "target_cids": (target.target_cid,),
        "operator_cids": (operator.operator_cid,),
        "candidate_cids": (candidate.candidate_cid,),
        "admitted_risk_classes": policy.admitted_risk_classes,
        "require_sandbox": True,
        "require_rollback": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationCampaignPlan(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


def test_operator_classes_are_closed_and_complete() -> None:
    expected = (
        "control_flow",
        "data_schema",
        "interface_contract",
        "side_effect",
        "error_retry",
        "authorization_policy",
        "state_distributed",
        "storage_durability",
        "test_proof",
        "semantic_compression",
        "gui_action_binding",
    )
    assert operator_classes() == expected
    assert len(OperatorClass) == 11
    with pytest.raises(ValueError):
        OperatorClass("unbounded_random")


def test_risk_property_sandbox_rollback_vocabularies_are_closed() -> None:
    assert mutation_risk_classes() == (
        "critical_security",
        "authorization",
        "durability",
        "financial_legal",
        "distributed_transition",
        "proof_receipt_trust",
        "critical_invariant",
        "high",
        "medium",
        "local_bug",
        "low",
    )
    assert PropertyClass.CONTROL_INVARIANT.value in property_classes()
    assert rollback_strategies() == (
        "worktree_discard",
        "reverse_patch",
        "snapshot_restore",
    )
    assert sandbox_modes() == (
        "disposable_worktree",
        "network_disabled",
        "fakes_only",
        "full_isolation",
    )
    with pytest.raises(ValueError):
        MutationRiskClass("model_guessed")
    with pytest.raises(ValueError):
        PropertyClass("whatever")


# ---------------------------------------------------------------------------
# Operator declaration completeness
# ---------------------------------------------------------------------------


def test_operator_declares_every_required_field() -> None:
    operator = _operator()
    payload = operator.to_dict()
    required = {
        "operator_id",
        "operator_version",
        "operator_class",
        "supported_languages",
        "supported_artifact_types",
        "target_prerequisites",
        "semantic_intent",
        "expected_violated_property_classes",
        "risk_class",
        "likely_equivalent_conditions",
        "syntactic_transformation",
        "scope_limits",
        "rollback",
        "required_sandbox",
        "max_mutants_per_target",
        "deterministic",
        "operator_cid",
        "schema",
        "interface_id",
    }
    assert required.issubset(payload.keys())
    assert payload["deterministic"] is True
    assert payload["max_mutants_per_target"] <= MAX_MUTANTS_PER_TARGET
    assert payload["rollback"]["preserves_production"] is True
    assert payload["required_sandbox"]["network_disabled"] is True
    assert payload["required_sandbox"]["disposable_worktree_required"] is True
    assert verify_operator_identity(operator) == operator.operator_cid


def test_operator_versionless_and_nondeterministic_fail_closed() -> None:
    with pytest.raises(MutationContractError, match="version token|nonempty"):
        _operator(operator_version="")
    with pytest.raises(MutationContractError, match="deterministic must be true"):
        _operator(deterministic=False)
    with pytest.raises(MutationContractError, match="positive integer"):
        _operator(max_mutants_per_target=0)
    with pytest.raises(MutationContractError, match="exceeds maximum"):
        _operator(max_mutants_per_target=MAX_MUTANTS_PER_TARGET + 1)


def test_operator_requires_sandbox_and_rollback_safety() -> None:
    with pytest.raises(MutationContractError, match="preserve production"):
        _rollback(preserves_production=False)
    with pytest.raises(MutationContractError, match="requires_clean_worktree"):
        _rollback(requires_clean_worktree=False)
    with pytest.raises(MutationContractError, match="network_disabled"):
        _sandbox(network_disabled=False)
    with pytest.raises(MutationContractError, match="production_credentials"):
        _sandbox(production_credentials_forbidden=False)
    with pytest.raises(MutationContractError, match="disposable_worktree"):
        _sandbox(disposable_worktree_required=False)
    with pytest.raises(MutationContractError, match="allow_verifier_mutation"):
        _scope(allow_verifier_mutation=True)


def test_operator_empty_languages_or_properties_fail_closed() -> None:
    with pytest.raises(MutationContractError, match="supported_languages"):
        _operator(supported_languages=())
    with pytest.raises(MutationContractError, match="supported_artifact_types"):
        _operator(supported_artifact_types=())
    with pytest.raises(MutationContractError, match="expected_violated_property"):
        _operator(expected_violated_property_classes=())
    with pytest.raises(MutationContractError, match="unsupported value"):
        _operator(operator_class="not_a_class")
    with pytest.raises(MutationContractError, match="unsupported value"):
        _operator(risk_class="invented")


# ---------------------------------------------------------------------------
# Deterministic seed/config binding
# ---------------------------------------------------------------------------


def test_seed_config_binds_and_verifies_config_cid() -> None:
    binding = _seed_config()
    assert binding.config_cid == cid_for_structured({"max_depth": 2, "operator_budget": 4})
    restored = SeedConfigBinding.from_dict(binding.to_dict())
    assert restored == binding
    assert restored.binding_cid == binding.binding_cid


def test_seed_config_forged_config_cid_fails_closed() -> None:
    with pytest.raises(MutationContractError, match="config_cid identity mismatch"):
        SeedConfigBinding(
            seed=1,
            config={"a": 1},
            config_cid=_cid("forged-config"),
        )


def test_identical_seed_config_operator_target_yield_identical_candidate_ids() -> None:
    first = _candidate()
    second = _candidate()
    assert first.candidate_cid == second.candidate_cid
    assert first.seed_config.binding_cid == second.seed_config.binding_cid
    assert first.operator_cid == second.operator_cid
    assert first.target_cid == second.target_cid


def test_seed_change_changes_candidate_identity() -> None:
    left = _candidate(seed_config=_seed_config(seed=1))
    right = _candidate(seed_config=_seed_config(seed=2))
    assert left.candidate_cid != right.candidate_cid


# ---------------------------------------------------------------------------
# Target prerequisites and risk
# ---------------------------------------------------------------------------


def test_target_requires_identity_and_closed_risk() -> None:
    target = _target()
    assert target.target_cid == MutationTarget.from_dict(target.to_dict()).target_cid
    with pytest.raises(MutationContractError, match="symbol_id or artifact_cid"):
        _target(symbol_ids=(), artifact_cids=())
    with pytest.raises(MutationContractError, match="unsupported value"):
        _target(risk_class="unknown_risk")
    with pytest.raises(MutationContractError, match="absolute paths|repository path"):
        _target(source_path="/etc/passwd")
    with pytest.raises(MutationContractError, match="parent-directory"):
        _target(source_path="../escape.py")


def test_operator_target_prerequisites_gate() -> None:
    operator = _operator(target_prerequisites=("parsed_ast", "symbol_table"))
    ok = _target(prerequisites=("parsed_ast", "symbol_table", "type_check"))
    assert operator.supports_target(ok) is True
    assert_operator_supports_target(operator, ok)

    missing = _target(prerequisites=("parsed_ast",))
    assert operator.supports_target(missing) is False
    with pytest.raises(MutationContractError, match="prerequisites"):
        assert_operator_supports_target(operator, missing)

    wrong_lang = _target(language="typescript")
    assert operator.supports_target(wrong_lang) is False


# ---------------------------------------------------------------------------
# Candidate, policy, plan round-trips and identity
# ---------------------------------------------------------------------------


def test_candidate_round_trip_and_header_kind() -> None:
    candidate = _candidate()
    restored = MutationCandidate.from_dict(candidate.to_dict())
    assert restored == candidate
    assert restored.candidate_cid == candidate.candidate_cid
    assert restored.seed_config.seed == 42
    with pytest.raises(MutationContractError, match="mutation_candidate"):
        _candidate(header=_header("mutation_campaign_plan"))
    with pytest.raises(MutationContractError, match="repository_state_cid"):
        _candidate(repository_state_cid=_cid("other-state"))


def test_policy_enforces_budget_sandbox_rollback_and_seed_flags() -> None:
    policy = _policy()
    restored = MutationCampaignPolicy.from_dict(policy.to_dict())
    assert restored.policy_cid == policy.policy_cid
    assert restored.require_rollback is True
    assert restored.require_deterministic_seed is True
    assert restored.budget.max_total_candidates == 64

    operator = _operator()
    assert policy.admits_operator(operator) is True
    assert policy.admits_target(_target()) is True
    assert policy.admits_operator(
        _operator(operator_class=OperatorClass.GUI_ACTION_BINDING)
    ) is False
    assert policy.admits_target(
        _target(risk_class=MutationRiskClass.LOW)
    ) is False

    with pytest.raises(MutationContractError, match="require_rollback must be true"):
        _policy(require_rollback=False)
    with pytest.raises(MutationContractError, match="require_network_disabled"):
        _policy(require_network_disabled=False)
    with pytest.raises(MutationContractError, match="require_deterministic_seed"):
        _policy(require_deterministic_seed=False)
    with pytest.raises(MutationContractError, match="full_suite_fallback"):
        _policy(full_suite_fallback_enabled=False)
    with pytest.raises(MutationContractError, match="admitted_operator_classes"):
        _policy(admitted_operator_classes=())
    with pytest.raises(MutationContractError, match="admitted_risk_classes"):
        _policy(admitted_risk_classes=())
    with pytest.raises(MutationContractError, match="mutation_campaign_policy"):
        _policy(header=_header("mutation_candidate"))


def test_plan_enforces_campaign_budget_and_safety_flags() -> None:
    plan = _plan()
    restored = MutationCampaignPlan.from_dict(plan.to_dict())
    assert restored.plan_cid == plan.plan_cid
    assert restored.require_sandbox is True
    assert restored.require_rollback is True
    assert len(restored.candidate_cids) <= restored.budget.max_total_candidates

    with pytest.raises(MutationContractError, match="max_targets"):
        _plan(
            budget=_budget(max_targets=1),
            target_cids=(_cid("t1"), _cid("t2")),
        )
    with pytest.raises(MutationContractError, match="max_operators"):
        _plan(
            budget=_budget(max_operators=1),
            operator_cids=(_cid("o1"), _cid("o2")),
        )
    with pytest.raises(MutationContractError, match="max_total_candidates"):
        _plan(
            budget=_budget(max_total_candidates=1, max_candidates_per_target=1),
            candidate_cids=(_cid("c1"), _cid("c2")),
        )
    with pytest.raises(MutationContractError, match="target_cids must not be empty"):
        _plan(target_cids=())
    with pytest.raises(MutationContractError, match="operator_cids must not be empty"):
        _plan(operator_cids=())
    with pytest.raises(MutationContractError, match="require_sandbox must be true"):
        _plan(require_sandbox=False)
    with pytest.raises(MutationContractError, match="require_rollback must be true"):
        _plan(require_rollback=False)
    with pytest.raises(MutationContractError, match="mutation_campaign_plan"):
        _plan(header=_header("mutation_campaign_policy"))
    with pytest.raises(MutationContractError, match="repository_id must match"):
        _plan(repository_id="repository:sha256:other")


def test_budget_bounds_and_helper() -> None:
    budget = _budget()
    assert_budget_admits_counts(
        budget, target_count=1, operator_count=1, candidate_count=1
    )
    with pytest.raises(MutationContractError, match="max_targets"):
        assert_budget_admits_counts(
            budget, target_count=budget.max_targets + 1, operator_count=1, candidate_count=1
        )
    with pytest.raises(MutationContractError, match="max_total_candidates"):
        assert_budget_admits_counts(
            budget,
            target_count=1,
            operator_count=1,
            candidate_count=budget.max_total_candidates + 1,
        )
    with pytest.raises(MutationContractError, match="cannot exceed max_total"):
        _budget(max_total_candidates=4, max_candidates_per_target=8)
    with pytest.raises(MutationContractError, match="positive integer"):
        _budget(max_total_candidates=0)


# ---------------------------------------------------------------------------
# Fail-closed: unknown fields, floats, forged CIDs, private/model authority
# ---------------------------------------------------------------------------


def test_unknown_fields_fail_closed_across_models() -> None:
    for model, factory in (
        ("operator", _operator),
        ("target", _target),
        ("candidate", _candidate),
        ("policy", _policy),
        ("plan", _plan),
    ):
        payload = factory().to_dict()
        payload["extra"] = "nope"
        cls = {
            "operator": MutationOperatorDefinition,
            "target": MutationTarget,
            "candidate": MutationCandidate,
            "policy": MutationCampaignPolicy,
            "plan": MutationCampaignPlan,
        }[model]
        with pytest.raises(MutationContractError, match="fields must be exactly"):
            cls.from_dict(payload)


def test_forged_identity_cids_fail_closed() -> None:
    op_payload = _operator().to_dict()
    op_payload["operator_cid"] = _cid("forged-operator")
    with pytest.raises(MutationContractError, match="identity mismatch"):
        MutationOperatorDefinition.from_dict(op_payload)

    target_payload = _target().to_dict()
    target_payload["target_cid"] = _cid("forged-target")
    with pytest.raises(MutationContractError, match="identity mismatch"):
        MutationTarget.from_dict(target_payload)

    cand_payload = _candidate().to_dict()
    cand_payload["candidate_cid"] = _cid("forged-candidate")
    with pytest.raises(MutationContractError, match="identity mismatch"):
        MutationCandidate.from_dict(cand_payload)

    policy_payload = _policy().to_dict()
    policy_payload["policy_cid"] = _cid("forged-policy")
    with pytest.raises(MutationContractError, match="identity mismatch"):
        MutationCampaignPolicy.from_dict(policy_payload)

    plan_payload = _plan().to_dict()
    plan_payload["plan_cid"] = _cid("forged-plan")
    with pytest.raises(MutationContractError, match="identity mismatch"):
        MutationCampaignPlan.from_dict(plan_payload)


def test_floats_host_objects_private_and_model_authority_fail_closed() -> None:
    with pytest.raises(MutationContractError, match="DAG-JSON|float"):
        _operator(metadata={"score": 0.5})
    with pytest.raises(MutationContractError, match="DAG-JSON|host"):
        _target(metadata={"path": Path("/tmp/x")})
    with pytest.raises(MutationContractError, match="private data"):
        _candidate(metadata={"raw_source": "secret"})
    with pytest.raises(MutationContractError, match="model-written authority"):
        _policy(metadata={"model_authority": True})
    with pytest.raises(MutationContractError, match="host fallback"):
        _plan(metadata={"local_path": "./x"})


def test_list_order_normalized_for_identity() -> None:
    left = _operator(
        supported_languages=("python", "typescript"),
        target_prerequisites=("symbol_table", "parsed_ast"),
    )
    right = _operator(
        supported_languages=("typescript", "python"),
        target_prerequisites=("parsed_ast", "symbol_table"),
    )
    assert left.operator_cid == right.operator_cid
    assert list(left.supported_languages) == sorted(left.supported_languages)

    t_left = _target(prerequisites=("b_prereq", "a_prereq"))
    t_right = _target(prerequisites=("a_prereq", "b_prereq"))
    assert t_left.target_cid == t_right.target_cid


def test_duplicate_lists_fail_closed() -> None:
    with pytest.raises(MutationContractError, match="duplicate"):
        _operator(supported_languages=("python", "python"))
    with pytest.raises(MutationContractError, match="duplicate"):
        _target(symbol_ids=("mod.fn", "mod.fn"))
    with pytest.raises(MutationContractError, match="duplicate"):
        _plan(target_cids=(_cid("t"), _cid("t")))


def test_unsupported_schema_and_interface_fail_closed() -> None:
    payload = _operator().to_dict()
    payload["schema"] = (
        "ipfs-datasets.software-contracts.adversarial-assurance-mutation-operator@2"
    )
    with pytest.raises(MutationContractError, match="unsupported"):
        MutationOperatorDefinition.from_dict(payload)

    payload = _candidate().to_dict()
    payload["interface_id"] = "MutationCandidate@2"
    with pytest.raises(MutationContractError, match="unsupported"):
        MutationCandidate.from_dict(payload)


def test_identity_payload_matches_content_profile() -> None:
    operator = _operator()
    assert cid_for_structured(operator.identity_payload()) == operator.operator_cid
    target = _target()
    assert cid_for_structured(target.identity_payload()) == target.target_cid
    candidate = _candidate()
    assert cid_for_structured(candidate.identity_payload()) == candidate.candidate_cid
    policy = _policy()
    assert cid_for_structured(policy.identity_payload()) == policy.policy_cid
    plan = _plan()
    assert cid_for_structured(plan.identity_payload()) == plan.plan_cid


def test_nested_mapping_normalization_from_dict() -> None:
    operator = _operator()
    raw = operator.to_dict()
    # Nested sealed maps accepted via from_dict.
    restored = MutationOperatorDefinition.from_dict(raw)
    assert restored.scope_limits.max_files == 1
    assert restored.rollback.strategy == RollbackStrategy.WORKTREE_DISCARD.value
    assert restored.required_sandbox.mode == SandboxMode.DISPOSABLE_WORKTREE.value

    # Plain mappings (without nested cid fields) also normalize.
    plain = MutationOperatorDefinition(
        operator_id="auth_bypass",
        operator_version="1",
        operator_class=OperatorClass.AUTHORIZATION_POLICY,
        supported_languages=["python"],
        supported_artifact_types=["source_module"],
        target_prerequisites=["policy_graph"],
        semantic_intent="Drop authentication check",
        expected_violated_property_classes=["authorization"],
        risk_class="critical_security",
        likely_equivalent_conditions=[],
        syntactic_transformation="remove_auth_guard",
        scope_limits={
            "max_files": 1,
            "max_symbols": 1,
            "max_span_lines": 32,
            "allow_cross_module": False,
            "allow_verifier_mutation": False,
        },
        rollback={
            "strategy": "worktree_discard",
            "requires_clean_worktree": True,
            "preserves_production": True,
        },
        required_sandbox={
            "mode": "full_isolation",
            "network_disabled": True,
            "production_credentials_forbidden": True,
            "disposable_worktree_required": True,
        },
        max_mutants_per_target=4,
    )
    assert plain.risk_class == MutationRiskClass.CRITICAL_SECURITY.value
    assert plain.required_sandbox.mode == SandboxMode.FULL_ISOLATION.value


def test_policy_operator_budget_limit_on_operator_cids() -> None:
    with pytest.raises(MutationContractError, match="max_operators"):
        _policy(
            budget=_budget(max_operators=1),
            operator_cids=(_cid("op-a"), _cid("op-b")),
        )


def test_verify_operator_identity_rejects_non_operator() -> None:
    with pytest.raises(MutationContractError, match="operator must be"):
        verify_operator_identity("not-an-operator")  # type: ignore[arg-type]
