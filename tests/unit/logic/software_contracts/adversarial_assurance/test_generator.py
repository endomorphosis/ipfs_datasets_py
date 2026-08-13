"""Unit vectors for deterministic bounded semantic mutation generation (AAE-022)."""

from __future__ import annotations

from typing import Sequence

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
    MutationCampaignPolicy,
    MutationCandidate,
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
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.registry import (
    MutationOperatorRegistry,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.generator import (
    GENERATE_MUTATION_CANDIDATES_INTERFACE,
    GENERATOR_ID,
    GENERATOR_VERSION,
    MUTATION_GENERATION_MANIFEST_INTERFACE,
    MutationGenerationError,
    MutationGenerationManifest,
    MutationGenerationResult,
    generate_mutation_candidates,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


REPO_ID = "repository:sha256:test-repo-identity"
REPO_STATE = _cid("repo-state")
SOURCE_ROOT = _cid("source-root")
ENV_CID = _cid("environment")
DEP_LOCK = _cid("dependency-lock")


def _generator(**overrides: object) -> GeneratorIdentity:
    fields = {
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "interface_id": GENERATE_MUTATION_CANDIDATES_INTERFACE,
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
        "repository_id": REPO_ID,
        "repository_state_cid": REPO_STATE,
        "target_symbol_ids": ("mod.fn",),
        "target_artifact_cids": (_cid("artifact-a"),),
        "capsule_cids": (_cid("capsule-a"),),
        "proof_unit_cids": (_cid("proof-unit-a"),),
        "environment_cid": ENV_CID,
        "dependency_lock_cid": DEP_LOCK,
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
        "max_symbols": 4,
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
        "max_mutants_per_target": 4,
        "deterministic": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationOperatorDefinition(**fields)  # type: ignore[arg-type]


def _operator_auth(**overrides: object) -> MutationOperatorDefinition:
    fields = {
        "operator_id": "auth_drop_tenant_check",
        "operator_version": "1",
        "operator_class": OperatorClass.AUTHORIZATION_POLICY,
        "supported_languages": ("python",),
        "supported_artifact_types": ("source_module",),
        "target_prerequisites": ("parsed_ast", "symbol_table"),
        "semantic_intent": "Drop tenant binding check on authorization path",
        "expected_violated_property_classes": (PropertyClass.AUTHORIZATION,),
        "risk_class": MutationRiskClass.AUTHORIZATION,
        "likely_equivalent_conditions": ("tenant_always_matches",),
        "syntactic_transformation": "remove_tenant_equality_guard",
        "scope_limits": _scope(),
        "rollback": _rollback(),
        "required_sandbox": _sandbox(),
        "max_mutants_per_target": 3,
        "deterministic": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationOperatorDefinition(**fields)  # type: ignore[arg-type]


def _target(**overrides: object) -> MutationTarget:
    fields = {
        "target_id": "mod_fn",
        "repository_id": REPO_ID,
        "repository_state_cid": REPO_STATE,
        "symbol_ids": ("mod.fn", "mod.helper"),
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


def _target_auth(**overrides: object) -> MutationTarget:
    fields = {
        "target_id": "auth_check",
        "repository_id": REPO_ID,
        "repository_state_cid": REPO_STATE,
        "symbol_ids": ("auth.check",),
        "artifact_cids": (_cid("artifact-auth"),),
        "language": "python",
        "artifact_type": "source_module",
        "prerequisites": ("parsed_ast", "symbol_table"),
        "risk_class": MutationRiskClass.AUTHORIZATION,
        "risk_weight_bp": 8_000,
        "capsule_cids": (_cid("capsule-auth"),),
        "proof_unit_cids": (_cid("proof-auth"),),
        "source_path": "auth.py",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationTarget(**fields)  # type: ignore[arg-type]


def _policy(
    operators: Sequence[MutationOperatorDefinition] | None = None,
    **overrides: object,
) -> MutationCampaignPolicy:
    ops = list(operators) if operators is not None else [_operator()]
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
            MutationRiskClass.CRITICAL_INVARIANT,
            MutationRiskClass.HIGH,
        ),
        "budget": _budget(),
        "seed_config": _seed_config(seed=7, config={"mode": "bounded"}),
        "require_disposable_worktree": True,
        "require_network_disabled": True,
        "require_rollback": True,
        "require_deterministic_seed": True,
        "full_suite_fallback_enabled": True,
        "held_out_partition_required": True,
        "operator_cids": tuple(op.operator_cid for op in ops),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationCampaignPolicy(**fields)  # type: ignore[arg-type]


def _manifest(
    *,
    targets: Sequence[MutationTarget] | None = None,
    operators: Sequence[MutationOperatorDefinition] | None = None,
    **overrides: object,
) -> MutationGenerationManifest:
    fields = {
        "repository_id": REPO_ID,
        "repository_state_cid": REPO_STATE,
        "source_root_cid": SOURCE_ROOT,
        "targets": tuple(targets) if targets is not None else (_target(),),
        "operators": tuple(operators) if operators is not None else (_operator(),),
        "environment_cid": ENV_CID,
        "dependency_lock_cid": DEP_LOCK,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationGenerationManifest(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_inputs_produce_byte_identical_ordered_candidates_and_ids() -> None:
    operator = _operator()
    target = _target()
    policy = _policy(operators=[operator], seed_config=_seed_config(seed=11))
    manifest = _manifest(targets=[target], operators=[operator])

    first = generate_mutation_candidates(manifest, policy)
    second = generate_mutation_candidates(manifest, policy)

    assert len(first) >= 1
    assert len(first) == len(second)
    assert [c.candidate_id for c in first] == [c.candidate_id for c in second]
    assert [c.candidate_cid for c in first] == [c.candidate_cid for c in second]
    assert [c.to_dict() for c in first] == [c.to_dict() for c in second]
    # Identity recomputation is stable.
    for candidate in first:
        assert candidate.candidate_cid == cid_for_structured(candidate.identity_payload())
        assert MutationCandidate.from_dict(candidate.to_dict()).candidate_cid == (
            candidate.candidate_cid
        )


def test_same_source_target_operator_seed_policy_across_manifest_round_trip() -> None:
    operator = _operator()
    target = _target()
    policy = _policy(operators=[operator], seed_config=_seed_config(seed=99))
    manifest = _manifest(targets=[target], operators=[operator])
    sealed = MutationGenerationManifest.from_dict(manifest.to_dict())
    policy_sealed = MutationCampaignPolicy.from_dict(policy.to_dict())

    left = generate_mutation_candidates(sealed, policy_sealed)
    right = generate_mutation_candidates(manifest.to_dict(), policy.to_dict())
    assert [c.candidate_cid for c in left] == [c.candidate_cid for c in right]


def test_seed_change_changes_candidate_identities() -> None:
    operator = _operator()
    target = _target()
    manifest = _manifest(targets=[target], operators=[operator])
    policy_a = _policy(operators=[operator], seed_config=_seed_config(seed=1))
    policy_b = _policy(operators=[operator], seed_config=_seed_config(seed=2))

    left = generate_mutation_candidates(manifest, policy_a)
    right = generate_mutation_candidates(manifest, policy_b)
    assert [c.candidate_id for c in left] != [c.candidate_id for c in right]
    assert [c.candidate_cid for c in left] != [c.candidate_cid for c in right]


def test_source_root_change_changes_candidate_identities() -> None:
    operator = _operator()
    target = _target()
    policy = _policy(operators=[operator], seed_config=_seed_config(seed=5))
    left = generate_mutation_candidates(
        _manifest(
            targets=[target],
            operators=[operator],
            source_root_cid=_cid("source-root-a"),
        ),
        policy,
    )
    right = generate_mutation_candidates(
        _manifest(
            targets=[target],
            operators=[operator],
            source_root_cid=_cid("source-root-b"),
        ),
        policy,
    )
    assert [c.candidate_cid for c in left] != [c.candidate_cid for c in right]
    assert left[0].source_root_cid != right[0].source_root_cid


def test_operator_override_seed_config_binds_into_candidates() -> None:
    operator = _operator()
    target = _target()
    policy = _policy(operators=[operator], seed_config=_seed_config(seed=1))
    override = _seed_config(seed=77, config={"mode": "override"})
    candidates = generate_mutation_candidates(
        _manifest(targets=[target], operators=[operator]),
        policy,
        seed_config=override,
    )
    assert all(c.seed_config.seed == 77 for c in candidates)
    assert all(c.seed_config.config_cid == override.config_cid for c in candidates)


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


def test_global_budget_truncates_candidates() -> None:
    operator = _operator(max_mutants_per_target=3)
    targets = [
        _target(target_id="t_a", symbol_ids=("a.one", "a.two"), risk_weight_bp=9_000),
        _target(
            target_id="t_b",
            symbol_ids=("b.one", "b.two"),
            artifact_cids=(_cid("artifact-b"),),
            risk_weight_bp=8_000,
        ),
        _target(
            target_id="t_c",
            symbol_ids=("c.one", "c.two"),
            artifact_cids=(_cid("artifact-c"),),
            risk_weight_bp=7_000,
        ),
    ]
    policy = _policy(
        operators=[operator],
        budget=_budget(
            max_total_candidates=3,
            max_candidates_per_target=3,
            max_candidates_per_operator=3,
        ),
        seed_config=_seed_config(seed=3),
        operator_cids=(),
    )
    result = generate_mutation_candidates(
        _manifest(targets=targets, operators=[operator]),
        policy,
        return_result=True,
    )
    assert isinstance(result, MutationGenerationResult)
    assert result.candidate_count == 3
    assert len(result.candidates) == 3
    assert result.candidate_count <= policy.budget.max_total_candidates


def test_per_target_budget_enforced() -> None:
    operator = _operator(max_mutants_per_target=8)
    target = _target(symbol_ids=("s1", "s2", "s3", "s4"))
    policy = _policy(
        operators=[operator],
        budget=_budget(
            max_total_candidates=64,
            max_candidates_per_target=2,
            max_candidates_per_operator=64,
        ),
        seed_config=_seed_config(seed=4),
        operator_cids=(),
    )
    result = generate_mutation_candidates(
        _manifest(targets=[target], operators=[operator]),
        policy,
        return_result=True,
    )
    assert isinstance(result, MutationGenerationResult)
    assert result.candidates_per_target[target.target_id] == 2
    assert result.candidate_count == 2


def test_per_operator_budget_enforced_across_targets() -> None:
    # admits_operator requires max_mutants_per_target <= max_candidates_per_operator
    operator = _operator(max_mutants_per_target=2)
    targets = [
        _target(target_id="t1", symbol_ids=("a.x",), risk_weight_bp=9_000),
        _target(
            target_id="t2",
            symbol_ids=("b.x",),
            artifact_cids=(_cid("artifact-b"),),
            risk_weight_bp=8_000,
        ),
        _target(
            target_id="t3",
            symbol_ids=("c.x",),
            artifact_cids=(_cid("artifact-c"),),
            risk_weight_bp=7_000,
        ),
    ]
    policy = _policy(
        operators=[operator],
        budget=_budget(
            max_total_candidates=64,
            max_candidates_per_target=8,
            max_candidates_per_operator=2,
        ),
        seed_config=_seed_config(seed=5),
        operator_cids=(),
    )
    result = generate_mutation_candidates(
        _manifest(targets=targets, operators=[operator]),
        policy,
        return_result=True,
    )
    assert isinstance(result, MutationGenerationResult)
    assert result.candidates_per_operator[operator.operator_id] == 2
    assert result.candidate_count == 2


def test_operator_max_mutants_per_target_bounds_pair() -> None:
    operator = _operator(max_mutants_per_target=1)
    target = _target(symbol_ids=("s1", "s2", "s3", "s4"))
    policy = _policy(
        operators=[operator],
        budget=_budget(max_total_candidates=64, max_candidates_per_target=8),
        seed_config=_seed_config(seed=6),
        operator_cids=(),
    )
    candidates = generate_mutation_candidates(
        _manifest(targets=[target], operators=[operator]),
        policy,
    )
    assert len(candidates) == 1


def test_oversized_target_count_fails_closed() -> None:
    operator = _operator()
    targets = [
        _target(
            target_id=f"t{i}",
            symbol_ids=(f"s{i}.fn",),
            artifact_cids=(_cid(f"art-{i}"),),
            risk_weight_bp=1_000 + i,
        )
        for i in range(3)
    ]
    policy = _policy(
        operators=[operator],
        budget=_budget(max_targets=2, max_total_candidates=64),
        operator_cids=(),
    )
    with pytest.raises(MutationGenerationError, match="max_targets"):
        generate_mutation_candidates(
            _manifest(targets=targets, operators=[operator]),
            policy,
        )


def test_oversized_operator_count_fails_closed() -> None:
    ops = [
        _operator(operator_id="op_a"),
        _operator(operator_id="op_b"),
        _operator(operator_id="op_c"),
    ]
    policy = _policy(
        operators=ops,
        budget=_budget(max_operators=2, max_total_candidates=64),
        operator_cids=(),
    )
    with pytest.raises(MutationGenerationError, match="max_operators"):
        generate_mutation_candidates(
            _manifest(targets=[_target()], operators=ops),
            policy,
        )


# ---------------------------------------------------------------------------
# Policy / support filters
# ---------------------------------------------------------------------------


def test_unsupported_language_target_is_skipped_when_other_pairs_exist() -> None:
    supported = _operator(operator_id="op_supported")
    unsupported_only = _operator(
        operator_id="op_ts_only",
        supported_languages=("typescript",),
    )
    target = _target(language="python")
    policy = _policy(
        operators=[supported, unsupported_only],
        seed_config=_seed_config(seed=8),
        operator_cids=(),
    )
    candidates = generate_mutation_candidates(
        _manifest(targets=[target], operators=[supported, unsupported_only]),
        policy,
    )
    assert candidates
    assert all(c.operator_id == "op_supported" for c in candidates)


def test_no_supporting_operator_fails_closed() -> None:
    operator = _operator(supported_languages=("typescript",))
    target = _target(language="python")
    policy = _policy(operators=[operator], operator_cids=())
    with pytest.raises(MutationGenerationError, match="no mutation candidates"):
        generate_mutation_candidates(
            _manifest(targets=[target], operators=[operator]),
            policy,
        )


def test_policy_risk_class_filters_targets() -> None:
    operator = _operator(risk_class=MutationRiskClass.AUTHORIZATION)
    local = _target(risk_class=MutationRiskClass.LOCAL_BUG)
    policy = _policy(
        operators=[operator],
        admitted_risk_classes=(MutationRiskClass.AUTHORIZATION,),
        admitted_operator_classes=(OperatorClass.CONTROL_FLOW,),
        operator_cids=(),
    )
    with pytest.raises(MutationGenerationError, match="no targets admitted"):
        generate_mutation_candidates(
            _manifest(targets=[local], operators=[operator]),
            policy,
        )


def test_policy_operator_cids_filter() -> None:
    keep = _operator(operator_id="keep_op")
    drop = _operator(operator_id="drop_op")
    target = _target()
    policy = _policy(
        operators=[keep, drop],
        operator_cids=(keep.operator_cid,),
        seed_config=_seed_config(seed=9),
    )
    candidates = generate_mutation_candidates(
        _manifest(targets=[target], operators=[keep, drop]),
        policy,
    )
    assert candidates
    assert all(c.operator_cid == keep.operator_cid for c in candidates)


def test_policy_operator_class_filter() -> None:
    control = _operator()
    auth = _operator_auth()
    target = _target_auth(
        prerequisites=("parsed_ast", "symbol_table"),
        risk_class=MutationRiskClass.AUTHORIZATION,
    )
    # Target is authorization risk; both operators support python source.
    # Admit only authorization_policy class.
    policy = _policy(
        operators=[control, auth],
        admitted_operator_classes=(OperatorClass.AUTHORIZATION_POLICY,),
        admitted_risk_classes=(MutationRiskClass.AUTHORIZATION,),
        operator_cids=(),
        seed_config=_seed_config(seed=10),
    )
    candidates = generate_mutation_candidates(
        _manifest(targets=[target], operators=[control, auth]),
        policy,
    )
    assert candidates
    assert all(c.operator_id == auth.operator_id for c in candidates)


# ---------------------------------------------------------------------------
# Ordering / multi-target
# ---------------------------------------------------------------------------


def test_higher_risk_targets_ordered_before_lower_risk() -> None:
    operator = _operator(max_mutants_per_target=1)
    low = _target(
        target_id="low_risk",
        risk_weight_bp=1_000,
        symbol_ids=("low.fn",),
        artifact_cids=(_cid("artifact-low"),),
    )
    high = _target(
        target_id="high_risk",
        risk_weight_bp=9_000,
        symbol_ids=("high.fn",),
        artifact_cids=(_cid("artifact-high"),),
    )
    policy = _policy(
        operators=[operator],
        budget=_budget(
            max_total_candidates=2,
            max_candidates_per_target=1,
            max_candidates_per_operator=2,
        ),
        seed_config=_seed_config(seed=12),
        operator_cids=(),
    )
    # Input order is low then high; generator reorders by risk weight.
    candidates = generate_mutation_candidates(
        _manifest(targets=[low, high], operators=[operator]),
        policy,
    )
    assert candidates[0].target_id == "high_risk"
    assert candidates[1].target_id == "low_risk"


def test_operators_sorted_deterministically_in_output() -> None:
    op_b = _operator(operator_id="zzz_op", max_mutants_per_target=1)
    op_a = _operator(operator_id="aaa_op", max_mutants_per_target=1)
    target = _target(symbol_ids=("only.one",))
    policy = _policy(
        operators=[op_b, op_a],
        budget=_budget(
            max_total_candidates=8,
            max_candidates_per_target=8,
            max_candidates_per_operator=8,
        ),
        seed_config=_seed_config(seed=13),
        operator_cids=(),
    )
    candidates = generate_mutation_candidates(
        _manifest(targets=[target], operators=[op_b, op_a]),
        policy,
    )
    ids = [c.operator_id for c in candidates]
    # After sorting operators by id, aaa_op emits before zzz_op for the target.
    assert ids == sorted(ids)


def test_registry_input_accepted() -> None:
    operator = _operator()
    target = _target()
    registry = MutationOperatorRegistry.from_operators([operator])
    policy = _policy(operators=[operator], seed_config=_seed_config(seed=14))
    candidates = generate_mutation_candidates(
        _manifest(targets=[target], operators=registry),
        policy,
    )
    assert candidates
    assert candidates[0].operator_cid == operator.operator_cid


# ---------------------------------------------------------------------------
# Manifest / negative cases
# ---------------------------------------------------------------------------


def test_manifest_identity_stable() -> None:
    manifest = _manifest()
    assert manifest.manifest_cid == cid_for_structured(manifest.identity_payload())
    assert (
        MutationGenerationManifest.from_dict(manifest.to_dict()).manifest_cid
        == manifest.manifest_cid
    )
    assert manifest.to_dict()["interface_id"] == MUTATION_GENERATION_MANIFEST_INTERFACE


def test_empty_targets_fail_closed() -> None:
    with pytest.raises(MutationGenerationError, match="targets must not be empty"):
        _manifest(targets=())


def test_repository_mismatch_between_target_and_manifest_fails() -> None:
    with pytest.raises(MutationGenerationError, match="repository_id"):
        _manifest(
            targets=[
                _target(repository_id="repository:sha256:other-repo-identity"),
            ]
        )


def test_policy_repository_mismatch_fails() -> None:
    operator = _operator()
    policy = _policy(
        operators=[operator],
        header=_header(
            "mutation_campaign_policy",
            repository_id="repository:sha256:other-repo-identity",
        ),
    )
    with pytest.raises(MutationGenerationError, match="repository_id"):
        generate_mutation_candidates(_manifest(operators=[operator]), policy)


def test_missing_prerequisites_skips_pair() -> None:
    operator = _operator(target_prerequisites=("parsed_ast", "symbol_table", "cfg"))
    target = _target(prerequisites=("parsed_ast",))
    other = _operator(
        operator_id="simple_op",
        target_prerequisites=("parsed_ast",),
        max_mutants_per_target=1,
    )
    policy = _policy(
        operators=[operator, other],
        seed_config=_seed_config(seed=15),
        operator_cids=(),
    )
    candidates = generate_mutation_candidates(
        _manifest(
            targets=[target],
            operators=[operator, other],
        ),
        policy,
    )
    assert all(c.operator_id == "simple_op" for c in candidates)


def test_candidate_binds_expected_property_classes_and_scope() -> None:
    operator = _operator()
    target = _target()
    policy = _policy(operators=[operator], seed_config=_seed_config(seed=16))
    candidates = generate_mutation_candidates(
        _manifest(targets=[target], operators=[operator]),
        policy,
    )
    cand = candidates[0]
    assert PropertyClass.CONTROL_INVARIANT.value in cand.expected_violated_property_classes
    assert cand.scope_symbol_ids
    assert cand.scope_paths == ("mod.py",)
    assert cand.likely_equivalent is False
    assert cand.header.versions.generator.generator_id == GENERATOR_ID
    assert cand.header.versions.generator.interface_id == (
        GENERATE_MUTATION_CANDIDATES_INTERFACE
    )
    assert "replace_if_test_with_not_test" in cand.transformation_summary


def test_return_result_includes_budget_accounting() -> None:
    operator = _operator()
    target = _target()
    policy = _policy(operators=[operator], seed_config=_seed_config(seed=17))
    result = generate_mutation_candidates(
        _manifest(targets=[target], operators=[operator]),
        policy,
        return_result=True,
    )
    assert isinstance(result, MutationGenerationResult)
    assert result.candidate_count == len(result.candidates)
    assert result.result_cid == cid_for_structured(result.identity_payload())
    assert result.metadata["generator_id"] == GENERATOR_ID
    assert result.metadata["generator_version"] == GENERATOR_VERSION


def test_forged_manifest_cid_fails_closed() -> None:
    manifest = _manifest()
    payload = manifest.to_dict()
    payload["manifest_cid"] = _cid("forged-manifest")
    with pytest.raises(MutationGenerationError, match="manifest_cid identity mismatch"):
        MutationGenerationManifest.from_dict(payload)


def test_private_metadata_rejected_on_manifest() -> None:
    # Never-expose sentinel: exercises private-field rejection without
    # introducing proposal-gate secret_change_forbidden material.
    with pytest.raises(MutationGenerationError):
        _manifest(metadata={"api_key": "should-never-appear"})
