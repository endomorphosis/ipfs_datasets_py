"""Unit tests for DistributedStorageMutationOperators@1 (AAE-019)."""

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
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.distributed_storage import (
    ADMITTED_OPERATOR_CLASSES,
    DEFAULT_STATE_DISTRIBUTED_RISK_CLASS,
    DEFAULT_STORAGE_DURABILITY_RISK_CLASS,
    DISTRIBUTED_STORAGE_OPERATORS_INTERFACE,
    DISTRIBUTED_STORAGE_OPERATORS_SCHEMA,
    DURABILITY_DISTINCTIONS,
    REQUIRED_DISTRIBUTED_STORAGE_FAMILIES,
    REQUIRED_STATE_DISTRIBUTED_FAMILIES,
    REQUIRED_STORAGE_DURABILITY_FAMILIES,
    DistributedStorageCoverageError,
    DistributedStorageError,
    DistributedStorageFamily,
    DistributedStorageMutationOperators,
    DistributedStorageOperator,
    DistributedStorageOperatorSpec,
    assert_distributed_storage_operator_defaults,
    build_distributed_storage_operator,
    build_distributed_storage_operators,
    default_distributed_storage_operators,
    distributed_storage_families_covered,
    distributed_storage_operator_definitions,
    distributed_storage_operator_specs,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.registry import (
    MutationOperatorRegistryBuilder,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _target(**overrides: object) -> MutationTarget:
    fields = {
        "target_id": "distributed_gate_fn",
        "repository_id": "repository:sha256:test-repo-identity",
        "repository_state_cid": _cid("repo-state-ds"),
        "symbol_ids": ("mod.distributed_gate",),
        "artifact_cids": (_cid("artifact-ds"),),
        "language": "python",
        "artifact_type": "source_module",
        "prerequisites": ("parsed_ast", "symbol_table"),
        "risk_class": MutationRiskClass.DISTRIBUTED_TRANSITION,
        "risk_weight_bp": 8_000,
        "capsule_cids": (_cid("capsule-ds"),),
        "proof_unit_cids": (_cid("proof-ds"),),
        "source_path": "mod/distributed_gate.py",
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return MutationTarget(**fields)  # type: ignore[arg-type]


def _minimal_state_spec(**overrides: object) -> DistributedStorageOperatorSpec:
    fields: dict[str, object] = {
        "operator_id": "sd_illegal_state_transition",
        "family": DistributedStorageFamily.ILLEGAL_TRANSITION,
        "semantic_intent": "Force an illegal state transition",
        "syntactic_transformation": "replace_transition_target_with_illegal_state",
        "expected_violated_property_classes": (PropertyClass.STATE_TRANSITION,),
        "likely_equivalent_conditions": (
            "target_state_is_already_reachable_via_legal_path",
        ),
    }
    fields.update(overrides)
    return DistributedStorageOperatorSpec(**fields)  # type: ignore[arg-type]


def _minimal_storage_spec(**overrides: object) -> DistributedStorageOperatorSpec:
    fields: dict[str, object] = {
        "operator_id": "st_skip_directory_sync",
        "family": DistributedStorageFamily.DIRECTORY_SYNC,
        "semantic_intent": "Skip directory fsync after rename",
        "syntactic_transformation": "omit_directory_fsync_after_rename_or_create",
        "expected_violated_property_classes": (
            PropertyClass.DURABILITY,
            PropertyClass.STORAGE_INTEGRITY,
        ),
        "likely_equivalent_conditions": (
            "filesystem_guarantees_directory_atomicity",
        ),
    }
    fields.update(overrides)
    return DistributedStorageOperatorSpec(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Spec validation and defaults
# ---------------------------------------------------------------------------


def test_default_risk_classes() -> None:
    assert (
        DEFAULT_STATE_DISTRIBUTED_RISK_CLASS
        == MutationRiskClass.DISTRIBUTED_TRANSITION.value
    )
    assert DEFAULT_STORAGE_DURABILITY_RISK_CLASS == MutationRiskClass.DURABILITY.value


def test_interface_constants() -> None:
    assert (
        DISTRIBUTED_STORAGE_OPERATORS_INTERFACE
        == "DistributedStorageMutationOperators@1"
    )
    assert "distributed-storage-mutation-operators@1" in (
        DISTRIBUTED_STORAGE_OPERATORS_SCHEMA
    )
    assert OperatorClass.STATE_DISTRIBUTED.value in ADMITTED_OPERATOR_CLASSES
    assert OperatorClass.STORAGE_DURABILITY.value in ADMITTED_OPERATOR_CLASSES
    assert OperatorClass.SIDE_EFFECT.value not in ADMITTED_OPERATOR_CLASSES


def test_spec_requires_equivalence_hints() -> None:
    with pytest.raises(DistributedStorageError, match="equivalence hints"):
        DistributedStorageOperatorSpec(
            operator_id="sd_no_equiv",
            family=DistributedStorageFamily.ILLEGAL_TRANSITION,
            semantic_intent="Illegal without hints",
            syntactic_transformation="replace_transition_target_with_illegal_state",
            expected_violated_property_classes=(PropertyClass.STATE_TRANSITION,),
            likely_equivalent_conditions=(),
        )


def test_spec_rejects_unknown_family() -> None:
    with pytest.raises(
        DistributedStorageError,
        match="unsupported state/distributed or storage family",
    ):
        DistributedStorageOperatorSpec(
            operator_id="sd_unknown_family",
            family="not_a_family",
            semantic_intent="Unknown family must fail closed",
            syntactic_transformation="noop",
            expected_violated_property_classes=(PropertyClass.STATE_TRANSITION,),
            likely_equivalent_conditions=("always_dead",),
        )


def test_spec_rejects_empty_semantic_intent() -> None:
    with pytest.raises(DistributedStorageError, match="semantic_intent"):
        DistributedStorageOperatorSpec(
            operator_id="sd_empty_intent",
            family=DistributedStorageFamily.ILLEGAL_TRANSITION,
            semantic_intent="   ",
            syntactic_transformation="replace_transition_target_with_illegal_state",
            expected_violated_property_classes=(PropertyClass.STATE_TRANSITION,),
            likely_equivalent_conditions=("x",),
        )


def test_spec_rejects_class_family_mismatch() -> None:
    with pytest.raises(DistributedStorageError, match="requires operator_class"):
        DistributedStorageOperatorSpec(
            operator_id="sd_wrong_class",
            family=DistributedStorageFamily.ILLEGAL_TRANSITION,
            operator_class=OperatorClass.STORAGE_DURABILITY,
            semantic_intent="State family cannot be storage_durability class",
            syntactic_transformation="replace_transition_target_with_illegal_state",
            expected_violated_property_classes=(PropertyClass.STATE_TRANSITION,),
            likely_equivalent_conditions=("x",),
        )


def test_storage_spec_requires_matching_durability_distinction() -> None:
    with pytest.raises(
        DistributedStorageError, match="requires durability_distinction"
    ):
        DistributedStorageOperatorSpec(
            operator_id="st_wrong_distinction",
            family=DistributedStorageFamily.CHECKSUM,
            durability_distinction="read_back",
            semantic_intent="Checksum family with wrong distinction",
            syntactic_transformation="bypass_storage_checksum_verification",
            expected_violated_property_classes=(PropertyClass.STORAGE_INTEGRITY,),
            likely_equivalent_conditions=("x",),
        )


def test_state_spec_rejects_durability_distinction() -> None:
    with pytest.raises(
        DistributedStorageError, match="must not set durability_distinction"
    ):
        DistributedStorageOperatorSpec(
            operator_id="sd_with_distinction",
            family=DistributedStorageFamily.CAS,
            durability_distinction="checksum",
            semantic_intent="CAS must not carry storage distinction",
            syntactic_transformation="drop_expected_old_check_from_cas",
            expected_violated_property_classes=(PropertyClass.STATE_TRANSITION,),
            likely_equivalent_conditions=("x",),
        )


def test_build_state_operator_seals() -> None:
    sealed = build_distributed_storage_operator(_minimal_state_spec())
    assert sealed.operator_class == OperatorClass.STATE_DISTRIBUTED.value
    assert sealed.risk_class == MutationRiskClass.DISTRIBUTED_TRANSITION.value
    assert sealed.deterministic is True
    assert sealed.required_sandbox.network_disabled is True
    assert sealed.required_sandbox.production_credentials_forbidden is True
    assert sealed.rollback.preserves_production is True
    assert sealed.metadata["ds_family"] == "illegal_transition"
    assert sealed.metadata["ds_operator_class"] == "state_distributed"
    assert sealed.semantic_intent
    assert sealed.likely_equivalent_conditions
    assert_distributed_storage_operator_defaults(sealed)


def test_build_storage_operator_seals_with_distinction() -> None:
    sealed = build_distributed_storage_operator(_minimal_storage_spec())
    assert sealed.operator_class == OperatorClass.STORAGE_DURABILITY.value
    assert sealed.risk_class == MutationRiskClass.DURABILITY.value
    assert sealed.metadata["ds_family"] == "directory_sync"
    assert sealed.metadata["durability_distinction"] == "directory_sync"
    assert_distributed_storage_operator_defaults(sealed)


def test_assert_defaults_rejects_wrong_operator_class() -> None:
    wrong = MutationOperatorDefinition(
        operator_id="cf_invert_conditional",
        operator_version="1",
        operator_class=OperatorClass.CONTROL_FLOW,
        supported_languages=("python",),
        supported_artifact_types=("source_module",),
        target_prerequisites=("parsed_ast",),
        semantic_intent="Not a distributed or storage operator",
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
    with pytest.raises(
        DistributedStorageError,
        match="state_distributed or storage_durability",
    ):
        assert_distributed_storage_operator_defaults(wrong)


# ---------------------------------------------------------------------------
# Normative catalogue coverage
# ---------------------------------------------------------------------------


def test_normative_specs_cover_every_required_family() -> None:
    specs = distributed_storage_operator_specs()
    families = {spec.family for spec in specs}
    assert families == REQUIRED_DISTRIBUTED_STORAGE_FAMILIES
    assert REQUIRED_STATE_DISTRIBUTED_FAMILIES <= families
    assert REQUIRED_STORAGE_DURABILITY_FAMILIES <= families


def test_every_spec_has_semantic_intent_and_equivalence_hints() -> None:
    for spec in distributed_storage_operator_specs():
        assert spec.semantic_intent.strip()
        assert len(spec.likely_equivalent_conditions) >= 1
        assert all(c.strip() for c in spec.likely_equivalent_conditions)
        assert spec.syntactic_transformation.strip()


def test_state_distributed_families_coverage() -> None:
    by_family = {
        family: [
            s for s in distributed_storage_operator_specs() if s.family == family
        ]
        for family in REQUIRED_STATE_DISTRIBUTED_FAMILIES
    }
    for family in (
        DistributedStorageFamily.ILLEGAL_TRANSITION.value,
        DistributedStorageFamily.SKIPPED_TRANSITION.value,
        DistributedStorageFamily.CAS.value,
        DistributedStorageFamily.FENCING.value,
        DistributedStorageFamily.LEASE.value,
        DistributedStorageFamily.OWNERSHIP.value,
        DistributedStorageFamily.IDEMPOTENCY.value,
        DistributedStorageFamily.PARTIAL_MUTATION.value,
        DistributedStorageFamily.COMPENSATION.value,
        DistributedStorageFamily.CONVERGENCE.value,
        DistributedStorageFamily.PROOF_FOREST.value,
        DistributedStorageFamily.PARENT_SEALS.value,
    ):
        assert by_family[family], f"missing operators for {family}"
        for s in by_family[family]:
            assert s.operator_class == OperatorClass.STATE_DISTRIBUTED.value
            assert s.durability_distinction is None


def test_storage_durability_families_coverage() -> None:
    by_family = {
        family: [
            s for s in distributed_storage_operator_specs() if s.family == family
        ]
        for family in REQUIRED_STORAGE_DURABILITY_FAMILIES
    }
    for family in (
        DistributedStorageFamily.PRE_COMMIT_ACK.value,
        DistributedStorageFamily.DIRECTORY_SYNC.value,
        DistributedStorageFamily.CHECKSUM.value,
        DistributedStorageFamily.STALE_READ.value,
        DistributedStorageFamily.READ_BACK.value,
        DistributedStorageFamily.CORRUPTION_REPLACEMENT.value,
        DistributedStorageFamily.QUEUED_AS_COMMITTED.value,
        DistributedStorageFamily.PROVIDER_ACK.value,
        DistributedStorageFamily.DURABLE_COMMIT.value,
    ):
        assert by_family[family], f"missing operators for {family}"
        for s in by_family[family]:
            assert s.operator_class == OperatorClass.STORAGE_DURABILITY.value
            assert s.durability_distinction is not None
            assert s.durability_distinction in DURABILITY_DISTINCTIONS


def test_transitions_cas_fencing_lease_ownership_ids() -> None:
    ids = {s.operator_id for s in distributed_storage_operator_specs()}
    assert "sd_illegal_state_transition" in ids
    assert "sd_skip_required_transition" in ids
    assert "sd_cas_ignore_expected_old" in ids
    assert "sd_accept_stale_fencing_token" in ids
    assert "sd_ignore_lease_expiry" in ids
    assert "sd_mutate_without_ownership" in ids


def test_idempotency_compensation_convergence_proof_parent_ids() -> None:
    ids = {s.operator_id for s in distributed_storage_operator_specs()}
    assert "sd_drop_idempotency_key" in ids
    assert "sd_skip_distributed_compensation" in ids
    assert "sd_declare_convergence_early" in ids
    assert "sd_drop_proof_forest_node" in ids
    assert "sd_omit_parent_seal_link" in ids
    assert "sd_bind_wrong_parent_seal" in ids


def test_durable_commit_sync_checksum_read_back_distinction_ids() -> None:
    ids = {s.operator_id for s in distributed_storage_operator_specs()}
    # Durable commit distinctions
    assert "st_claim_commit_without_sync" in ids
    assert "st_claim_commit_without_checksum" in ids
    assert "st_claim_commit_without_read_back" in ids
    # Sync / checksum / read-back families
    assert "st_skip_directory_sync" in ids
    assert "st_skip_checksum_verification" in ids
    assert "st_skip_read_back_verification" in ids
    assert "st_read_back_from_write_buffer" in ids
    # Pre-commit / provider / queue
    assert "st_ack_before_durable_commit" in ids
    assert "st_treat_queued_as_committed" in ids
    assert "st_trust_provider_ack_without_verify" in ids


def test_default_catalogue_is_complete_and_bounded() -> None:
    catalogue = default_distributed_storage_operators()
    assert catalogue.catalogue_id
    assert catalogue.to_dict()["interface_id"] == DISTRIBUTED_STORAGE_OPERATORS_INTERFACE
    assert catalogue.to_dict()["schema"] == DISTRIBUTED_STORAGE_OPERATORS_SCHEMA
    catalogue.assert_complete_coverage()
    assert set(catalogue.families()) == REQUIRED_DISTRIBUTED_STORAGE_FAMILIES
    assert (
        distributed_storage_families_covered()
        == REQUIRED_DISTRIBUTED_STORAGE_FAMILIES
    )
    assert set(catalogue.operator_classes()) == ADMITTED_OPERATOR_CLASSES
    for operator in catalogue:
        assert operator.definition.operator_class in ADMITTED_OPERATOR_CLASSES
        assert operator.definition.deterministic is True
        assert operator.family in REQUIRED_DISTRIBUTED_STORAGE_FAMILIES
        assert operator.definition.semantic_intent
        assert operator.definition.likely_equivalent_conditions
        assert_distributed_storage_operator_defaults(operator.definition)


def test_durability_distinctions_present_and_distinct() -> None:
    catalogue = default_distributed_storage_operators()
    distinctions = set(catalogue.durability_distinctions())
    for required in (
        "durable_commit",
        "directory_sync",
        "checksum",
        "read_back",
        "pre_commit_ack",
        "provider_ack",
        "queued_as_committed",
        "stale_read",
        "corruption_replacement",
    ):
        assert required in distinctions, f"missing distinction {required}"
        ops = catalogue.operators_for_durability_distinction(required)
        assert ops
        assert all(op.durability_distinction == required for op in ops)
        assert all(
            op.definition.operator_class
            == OperatorClass.STORAGE_DURABILITY.value
            for op in ops
        )


def test_durable_commit_distinction_separates_sync_checksum_read_back() -> None:
    """Commit-without-X operators must not collapse to a single observation mode."""

    catalogue = default_distributed_storage_operators()
    commit_ops = catalogue.operators_for_family(
        DistributedStorageFamily.DURABLE_COMMIT
    )
    ids = {op.operator_id for op in commit_ops}
    assert "st_claim_commit_without_sync" in ids
    assert "st_claim_commit_without_checksum" in ids
    assert "st_claim_commit_without_read_back" in ids
    # Each claim targets a different observation gap in semantic_intent text.
    intents = {
        op.operator_id: op.definition.semantic_intent.lower() for op in commit_ops
    }
    assert "sync" in intents["st_claim_commit_without_sync"]
    assert "checksum" in intents["st_claim_commit_without_checksum"]
    assert "read-back" in intents["st_claim_commit_without_read_back"] or (
        "read_back" in intents["st_claim_commit_without_read_back"]
    )
    # Distinct syntactic transformations
    transforms = {op.definition.syntactic_transformation for op in commit_ops}
    assert len(transforms) == len(commit_ops)


def test_expected_operator_ids_present() -> None:
    ids = set(default_distributed_storage_operators().operator_ids())
    expected = {
        "sd_illegal_state_transition",
        "sd_skip_required_transition",
        "sd_bypass_transition_guard",
        "sd_cas_ignore_expected_old",
        "sd_cas_accept_stale_head",
        "sd_accept_stale_fencing_token",
        "sd_omit_fencing_on_mutation",
        "sd_ignore_lease_expiry",
        "sd_extend_lease_without_authority",
        "sd_mutate_without_ownership",
        "sd_transfer_ownership_without_quorum",
        "sd_drop_idempotency_key",
        "sd_reuse_idempotency_key_for_new_op",
        "sd_commit_partial_replica_set",
        "sd_skip_second_phase_write",
        "sd_skip_distributed_compensation",
        "sd_incomplete_distributed_compensation",
        "sd_declare_convergence_early",
        "sd_ignore_divergent_replica",
        "sd_drop_proof_forest_node",
        "sd_reuse_stale_proof_forest",
        "sd_omit_parent_seal_link",
        "sd_bind_wrong_parent_seal",
        "st_ack_before_durable_commit",
        "st_treat_journal_write_as_commit",
        "st_skip_directory_sync",
        "st_sync_file_not_directory",
        "st_skip_checksum_verification",
        "st_accept_mismatched_checksum",
        "st_serve_stale_read_as_current",
        "st_skip_read_your_writes",
        "st_skip_read_back_verification",
        "st_read_back_from_write_buffer",
        "st_replace_corrupt_with_empty",
        "st_accept_corrupt_as_valid",
        "st_treat_queued_as_committed",
        "st_success_on_queue_accept_only",
        "st_trust_provider_ack_without_verify",
        "st_conflate_provider_recv_with_durable",
        "st_claim_commit_without_sync",
        "st_claim_commit_without_checksum",
        "st_claim_commit_without_read_back",
    }
    assert expected <= ids


def test_catalogue_identity_is_deterministic() -> None:
    left = default_distributed_storage_operators()
    right = default_distributed_storage_operators()
    assert left.catalogue_id == right.catalogue_id
    assert left.operator_cids() == right.operator_cids()
    assert left.identity_payload() == right.identity_payload()


def test_catalogue_round_trip_preserves_identity() -> None:
    original = default_distributed_storage_operators()
    restored = DistributedStorageMutationOperators.from_dict(original.to_dict())
    assert restored.catalogue_id == original.catalogue_id
    assert restored.operator_ids() == original.operator_ids()
    assert restored.operator_cids() == original.operator_cids()
    assert set(restored.families()) == set(original.families())
    assert set(restored.operator_classes()) == set(original.operator_classes())
    assert set(restored.durability_distinctions()) == set(
        original.durability_distinctions()
    )


def test_definitions_helper_matches_catalogue() -> None:
    defs = distributed_storage_operator_definitions()
    catalogue = default_distributed_storage_operators()
    assert [d.operator_cid for d in defs] == list(catalogue.operator_cids())
    assert all(d.operator_class in ADMITTED_OPERATOR_CLASSES for d in defs)


# ---------------------------------------------------------------------------
# Lookup, target support, rollback
# ---------------------------------------------------------------------------


def test_get_and_get_by_cid() -> None:
    catalogue = default_distributed_storage_operators()
    op = catalogue.get("sd_cas_ignore_expected_old")
    assert op.family == DistributedStorageFamily.CAS.value
    by_cid = catalogue.get_by_cid(op.operator_cid)
    assert by_cid.operator_id == op.operator_id
    assert "sd_cas_ignore_expected_old" in catalogue
    assert op.operator_cid in catalogue
    with pytest.raises(DistributedStorageError, match="unknown operator_id"):
        catalogue.get("sd_does_not_exist")
    with pytest.raises(DistributedStorageError, match="unknown operator_cid"):
        catalogue.get_by_cid(_cid("missing-operator"))


def test_operators_for_family_class_and_target() -> None:
    catalogue = default_distributed_storage_operators()
    fencing_ops = catalogue.operators_for_family(DistributedStorageFamily.FENCING)
    assert len(fencing_ops) == 2
    assert {op.operator_id for op in fencing_ops} == {
        "sd_accept_stale_fencing_token",
        "sd_omit_fencing_on_mutation",
    }

    state_ops = catalogue.operators_for_class(OperatorClass.STATE_DISTRIBUTED)
    storage_ops = catalogue.operators_for_class(OperatorClass.STORAGE_DURABILITY)
    assert len(state_ops) + len(storage_ops) == len(catalogue)
    assert all(
        op.definition.operator_class == OperatorClass.STATE_DISTRIBUTED.value
        for op in state_ops
    )
    assert all(
        op.definition.operator_class == OperatorClass.STORAGE_DURABILITY.value
        for op in storage_ops
    )

    target = _target()
    supporting = catalogue.operators_for_target(target)
    assert len(supporting) == len(catalogue)
    assert all(op.supports_target(target) for op in supporting)

    unsupported = catalogue.operators_for_target(_target(language="cobol"))
    assert unsupported == ()


def test_rollback_record_is_deterministic() -> None:
    catalogue = default_distributed_storage_operators()
    target = _target()
    pre = _cid("pre-mutation-ds")
    first = catalogue.rollback_record(
        "st_skip_checksum_verification",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    second = catalogue.rollback_record(
        "st_skip_checksum_verification",
        pre_mutation_state_cid=pre,
        target=target,
        source_root_cid=_cid("source-root"),
    )
    assert isinstance(first, OperatorRollbackRecord)
    assert first.record_cid == second.record_cid
    assert first.preserves_production is True
    assert first.requires_clean_worktree is True
    assert first.operator_id == "st_skip_checksum_verification"


def test_rollback_record_fails_closed_for_unsupported_target() -> None:
    catalogue = default_distributed_storage_operators()
    with pytest.raises(Exception, match="does not support|language|artifact"):
        catalogue.rollback_record(
            "sd_illegal_state_transition",
            pre_mutation_state_cid=_cid("pre"),
            target=_target(language="cobol"),
        )


# ---------------------------------------------------------------------------
# Registry projection
# ---------------------------------------------------------------------------


def test_as_registry_admits_all_operators() -> None:
    catalogue = default_distributed_storage_operators()
    registry = catalogue.as_registry()
    assert len(registry) == len(catalogue)
    for operator_id in catalogue.operator_ids():
        admitted = registry.get(operator_id)
        assert admitted.operator_class in ADMITTED_OPERATOR_CLASSES


def test_register_into_builder() -> None:
    catalogue = default_distributed_storage_operators()
    builder = MutationOperatorRegistryBuilder()
    sealed = catalogue.register_into(builder)
    assert len(sealed) == len(catalogue)
    registry = builder.build()
    assert set(registry.operator_ids()) == set(catalogue.operator_ids())


def test_registry_dispatch_for_state_and_storage() -> None:
    catalogue = default_distributed_storage_operators()
    registry = catalogue.as_registry()
    target = _target()

    state_matches = registry.dispatch(
        target, operator_class=OperatorClass.STATE_DISTRIBUTED
    )
    assert len(state_matches) == len(
        catalogue.operators_for_class(OperatorClass.STATE_DISTRIBUTED)
    )

    storage_matches = registry.dispatch(
        target, operator_class=OperatorClass.STORAGE_DURABILITY
    )
    assert len(storage_matches) == len(
        catalogue.operators_for_class(OperatorClass.STORAGE_DURABILITY)
    )

    one = registry.dispatch_one(
        target,
        operator_id="sd_accept_stale_fencing_token",
        operator_class=OperatorClass.STATE_DISTRIBUTED,
    )
    assert one.operator_id == "sd_accept_stale_fencing_token"
    assert PropertyClass.STATE_TRANSITION.value in one.expected_violated_property_classes


# ---------------------------------------------------------------------------
# Coverage / negative assembly
# ---------------------------------------------------------------------------


def test_incomplete_catalogue_rejected() -> None:
    only = _minimal_state_spec()
    with pytest.raises(DistributedStorageCoverageError, match="missing required"):
        build_distributed_storage_operators([only])

    sealed = build_distributed_storage_operator(only)
    handle = DistributedStorageOperator(
        _definition=sealed,
        family=DistributedStorageFamily.ILLEGAL_TRANSITION.value,
        spec_operator_id="sd_illegal_state_transition",
    )
    with pytest.raises(DistributedStorageCoverageError, match="missing required"):
        DistributedStorageMutationOperators(operators=(handle,))


def test_duplicate_operator_id_rejected() -> None:
    specs = list(distributed_storage_operator_specs())
    specs.append(
        DistributedStorageOperatorSpec(
            operator_id="sd_illegal_state_transition",
            family=DistributedStorageFamily.ILLEGAL_TRANSITION,
            semantic_intent="Duplicate id must fail",
            syntactic_transformation="replace_transition_target_with_illegal_state_v2",
            expected_violated_property_classes=(PropertyClass.STATE_TRANSITION,),
            likely_equivalent_conditions=("dead_transition",),
        )
    )
    with pytest.raises(DistributedStorageError, match="duplicate operator_id"):
        build_distributed_storage_operators(specs)


def test_from_dict_rejects_unknown_fields() -> None:
    payload = default_distributed_storage_operators().to_dict()
    payload["unexpected_field"] = True
    with pytest.raises(DistributedStorageError, match="unknown fields"):
        DistributedStorageMutationOperators.from_dict(payload)


def test_operator_handle_family_metadata_mismatch_rejected() -> None:
    sealed = build_distributed_storage_operator(_minimal_state_spec())
    with pytest.raises(DistributedStorageError, match="ds_family"):
        DistributedStorageOperator(
            _definition=sealed,
            family=DistributedStorageFamily.CAS.value,
            spec_operator_id="sd_illegal_state_transition",
        )


def test_property_classes_for_key_families() -> None:
    catalogue = default_distributed_storage_operators()
    cas = catalogue.get("sd_cas_ignore_expected_old")
    assert PropertyClass.STATE_TRANSITION.value in (
        cas.definition.expected_violated_property_classes
    )

    idem = catalogue.get("sd_drop_idempotency_key")
    assert PropertyClass.IDEMPOTENCY.value in (
        idem.definition.expected_violated_property_classes
    )

    comp = catalogue.get("sd_skip_distributed_compensation")
    assert PropertyClass.COMPENSATION.value in (
        comp.definition.expected_violated_property_classes
    )

    forest = catalogue.get("sd_drop_proof_forest_node")
    assert PropertyClass.PROOF_ADEQUACY.value in (
        forest.definition.expected_violated_property_classes
    )

    parent = catalogue.get("sd_omit_parent_seal_link")
    assert PropertyClass.RECEIPT_AUTHENTICITY.value in (
        parent.definition.expected_violated_property_classes
    )

    checksum = catalogue.get("st_skip_checksum_verification")
    assert PropertyClass.STORAGE_INTEGRITY.value in (
        checksum.definition.expected_violated_property_classes
    )
    assert PropertyClass.DURABILITY.value in (
        checksum.definition.expected_violated_property_classes
    )


def test_identity_payload_is_cid_addressable() -> None:
    catalogue = default_distributed_storage_operators()
    payload = catalogue.identity_payload()
    recomputed = cid_for_structured(
        {
            k: v
            for k, v in catalogue._identity_payload_without_catalogue_id().items()
        }
    )
    assert catalogue.catalogue_id == recomputed
    assert payload["catalogue_id"] == catalogue.catalogue_id
    assert payload["operator_count"] == len(catalogue)
