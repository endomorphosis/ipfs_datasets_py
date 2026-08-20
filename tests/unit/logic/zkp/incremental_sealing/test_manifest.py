"""Regression tests for VerificationPolicy and VerificationRequirementManifest (IPS-009)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.zkp.incremental_sealing.evidence import ProofUnitKind
from ipfs_datasets_py.logic.zkp.incremental_sealing.identity import (
    CANONICALIZATION_VERSION,
    canonical_cid,
)
from ipfs_datasets_py.logic.zkp.incremental_sealing.manifest import (
    ABSENCE_TOKEN,
    CLOSED_REMOVAL_REASONS,
    MANIFEST_REQUIRED_FIELDS,
    MANIFEST_SUBSET,
    REQUIRED_UNIT_DESCRIPTOR_SCHEMA,
    UNIT_REMOVAL_AUTHORIZATION_SCHEMA,
    VERIFICATION_POLICY_SCHEMA,
    VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA,
    ManifestError,
    RequiredUnitDescriptor,
    UnitRemovalAuthorization,
    VerificationPolicy,
    VerificationRequirementManifest,
    assert_no_unauthorized_disappearance,
    build_verification_requirement_manifest,
    known_vectors,
    sample_required_unit,
    sample_verification_policy,
    sample_verification_requirement_manifest,
)


def _cid(label: str) -> str:
    return canonical_cid({"ips_manifest_test": label, "v": 1})


def test_manifest_subset_and_schemas_are_closed() -> None:
    assert MANIFEST_SUBSET == "ips/verification-manifest@1"
    assert VERIFICATION_POLICY_SCHEMA.endswith("/verification-policy@1")
    assert VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA.endswith(
        "/verification-requirement-manifest@1"
    )
    assert REQUIRED_UNIT_DESCRIPTOR_SCHEMA.endswith("/required-unit-descriptor@1")
    assert UNIT_REMOVAL_AUTHORIZATION_SCHEMA.endswith(
        "/unit-removal-authorization@1"
    )
    for required in (
        "repository_id",
        "revision",
        "repository_state_cid",
        "source_root_cid",
        "required_units",
        "policy_cid",
        "test_selector_cid",
        "environment_cid",
        "dependency_lock_cid",
        "configuration_cid",
        "network_policy_cid",
        "proof_schema_version",
        "canonicalization_version",
        "dependency_graph_schema_version",
        "permitted_removals",
        "logical_epoch",
    ):
        assert required in MANIFEST_REQUIRED_FIELDS
    assert "test_deleted" in CLOSED_REMOVAL_REASONS


def test_policy_and_manifest_round_trip_are_deterministic() -> None:
    policy = sample_verification_policy()
    assert policy.policy_cid() == sample_verification_policy().policy_cid()
    restored_policy = VerificationPolicy.from_canonical(
        json.loads(policy.to_canonical_json())
    )
    assert restored_policy == policy
    assert restored_policy.policy_cid() == policy.policy_cid()

    manifest = sample_verification_requirement_manifest(
        policy_cid=policy.policy_cid()
    )
    again = sample_verification_requirement_manifest(policy_cid=policy.policy_cid())
    assert manifest.manifest_root() == again.manifest_root()
    assert manifest.manifest_cid() == manifest.root == manifest.manifest_root()
    restored = VerificationRequirementManifest.from_canonical(
        json.loads(manifest.to_canonical_json())
    )
    assert restored == manifest
    assert restored.manifest_root() == manifest.manifest_root()
    assert restored.required_unit_ids == ("unit/a", "unit/b")
    assert all(unit.required_for_seal for unit in restored.required_units)


def test_added_selected_units_are_required() -> None:
    policy = sample_verification_policy()
    units = (
        sample_required_unit(proof_unit_id="unit/a", selection_source="selected_test"),
        sample_required_unit(
            proof_unit_id="unit/b", selection_source="selected_property"
        ),
    )
    manifest = build_verification_requirement_manifest(
        repository_id="repo/datasets",
        revision="rev-1",
        repository_state_cid=_cid("state"),
        source_root_cid=_cid("source"),
        required_units=units,
        policy=policy,
        test_selector_cid=_cid("selector"),
        environment_cid=_cid("env"),
        dependency_lock_cid=_cid("lock"),
        configuration_cid=_cid("config"),
        selected_unit_ids=["unit/a", "unit/b"],
        logical_epoch=1,
    )
    manifest.assert_selected_units_required(["unit/a", "unit/b"])
    for unit in manifest.required_units:
        assert unit.required_for_seal is True
        assert unit.selection_source in {
            "selected_test",
            "selected_property",
            "selected_unit",
            "policy_selected",
            "discovery_selected",
        }

    with pytest.raises(ManifestError, match="added selected units are required"):
        manifest.assert_selected_units_required(["unit/a", "unit/b", "unit/missing"])

    with pytest.raises(ManifestError, match="added selected units are required"):
        RequiredUnitDescriptor(
            proof_unit_id="unit/x",
            unit_descriptor_cid=_cid("desc-x"),
            proof_unit_kind=ProofUnitKind.UNIT_TEST,
            selection_source="selected_test",
            risk_class="high",
            required_for_seal=False,
        )


def test_unauthorized_disappearance_fails() -> None:
    policy = sample_verification_policy()
    previous = sample_verification_requirement_manifest(policy_cid=policy.policy_cid())
    # Drop unit/b without a removal authorization.
    remaining = tuple(
        unit for unit in previous.required_units if unit.proof_unit_id != "unit/b"
    )
    unauthorized = build_verification_requirement_manifest(
        repository_id=previous.repository_id,
        revision=previous.revision,
        repository_state_cid=previous.repository_state_cid,
        source_root_cid=previous.source_root_cid,
        required_units=remaining,
        policy=previous.policy_cid,
        test_selector_cid=previous.test_selector_cid,
        environment_cid=previous.environment_cid,
        dependency_lock_cid=previous.dependency_lock_cid,
        configuration_cid=previous.configuration_cid,
        network_policy_cid=previous.network_policy_cid,
        proof_schema_version=previous.proof_schema_version,
        canonicalization_version=previous.canonicalization_version,
        dependency_graph_schema_version=previous.dependency_graph_schema_version,
        permitted_removals=(),
        logical_epoch=previous.logical_epoch + 1,
    )
    with pytest.raises(ManifestError, match="unauthorized disappearance"):
        assert_no_unauthorized_disappearance(previous, unauthorized, policy=policy)

    # Explicit unauthorized=false record is rejected at construction.
    with pytest.raises(ManifestError, match="unauthorized disappearance|authorized"):
        UnitRemovalAuthorization(
            proof_unit_id="unit/b",
            policy_cid=previous.policy_cid,
            removal_reason="test_deleted",
            risk_class="medium",
            tombstone_cid=ABSENCE_TOKEN,
            authorized=False,
            logical_epoch=2,
        )

    # Authorized removal under current policy succeeds.
    removal = UnitRemovalAuthorization(
        proof_unit_id="unit/b",
        policy_cid=previous.policy_cid,
        removal_reason="test_deleted",
        risk_class="medium",
        tombstone_cid=_cid("tombstone-b"),
        authorized=True,
        logical_epoch=previous.logical_epoch + 1,
    )
    authorized = build_verification_requirement_manifest(
        repository_id=previous.repository_id,
        revision=previous.revision,
        repository_state_cid=previous.repository_state_cid,
        source_root_cid=previous.source_root_cid,
        required_units=remaining,
        policy=previous.policy_cid,
        test_selector_cid=previous.test_selector_cid,
        environment_cid=previous.environment_cid,
        dependency_lock_cid=previous.dependency_lock_cid,
        configuration_cid=previous.configuration_cid,
        network_policy_cid=previous.network_policy_cid,
        proof_schema_version=previous.proof_schema_version,
        canonicalization_version=previous.canonicalization_version,
        dependency_graph_schema_version=previous.dependency_graph_schema_version,
        permitted_removals=(removal,),
        logical_epoch=previous.logical_epoch + 1,
    )
    assert_no_unauthorized_disappearance(previous, authorized, policy=policy)
    assert "unit/b" not in authorized.required_unit_ids
    assert authorized.manifest_root() != previous.manifest_root()

    # Wrong risk class under policy is unauthorized.
    high_risk_removal = UnitRemovalAuthorization(
        proof_unit_id="unit/b",
        policy_cid=previous.policy_cid,
        removal_reason="test_deleted",
        risk_class="high",
        tombstone_cid=_cid("tombstone-b-high"),
        authorized=True,
        logical_epoch=previous.logical_epoch + 1,
    )
    high_risk = build_verification_requirement_manifest(
        repository_id=previous.repository_id,
        revision=previous.revision,
        repository_state_cid=previous.repository_state_cid,
        source_root_cid=previous.source_root_cid,
        required_units=remaining,
        policy=previous.policy_cid,
        test_selector_cid=previous.test_selector_cid,
        environment_cid=previous.environment_cid,
        dependency_lock_cid=previous.dependency_lock_cid,
        configuration_cid=previous.configuration_cid,
        network_policy_cid=previous.network_policy_cid,
        proof_schema_version=previous.proof_schema_version,
        canonicalization_version=previous.canonicalization_version,
        dependency_graph_schema_version=previous.dependency_graph_schema_version,
        permitted_removals=(high_risk_removal,),
        logical_epoch=previous.logical_epoch + 1,
    )
    with pytest.raises(ManifestError, match="unauthorized disappearance"):
        assert_no_unauthorized_disappearance(previous, high_risk, policy=policy)


def test_manifest_root_changes_for_required_set_policy_selector_and_context() -> None:
    vectors = known_vectors()
    assert vectors["manifest_subset"] == MANIFEST_SUBSET
    base_root = vectors["base"]["manifest_root"]
    added_root = vectors["added_selected_unit"]["manifest_root"]
    assert added_root != base_root
    assert "unit/c" in vectors["added_selected_unit"]["required_unit_ids"]

    removal_root = vectors["authorized_removal"]["manifest_root"]
    assert removal_root != base_root

    mutations = vectors["context_mutations"]
    expected_fields = {
        "policy_cid",
        "test_selector_cid",
        "environment_cid",
        "dependency_lock_cid",
        "configuration_cid",
        "source_root_cid",
        "repository_state_cid",
        "network_policy_cid",
        "canonicalization_version",
        "dependency_graph_schema_version",
        "proof_schema_version",
        "revision",
        "logical_epoch",
    }
    assert expected_fields <= set(mutations)
    for field, mutated_root in mutations.items():
        assert mutated_root != base_root, field

    # Independent recomputation: mutate required set only.
    base = VerificationRequirementManifest.from_canonical(vectors["base"]["manifest"])
    extra = sample_required_unit(proof_unit_id="unit/z")
    rebuilt = build_verification_requirement_manifest(
        repository_id=base.repository_id,
        revision=base.revision,
        repository_state_cid=base.repository_state_cid,
        source_root_cid=base.source_root_cid,
        required_units=tuple(
            sorted(
                list(base.required_units) + [extra],
                key=lambda item: item.proof_unit_id,
            )
        ),
        policy=base.policy_cid,
        test_selector_cid=base.test_selector_cid,
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        configuration_cid=base.configuration_cid,
        network_policy_cid=base.network_policy_cid,
        proof_schema_version=base.proof_schema_version,
        canonicalization_version=base.canonicalization_version,
        dependency_graph_schema_version=base.dependency_graph_schema_version,
        logical_epoch=base.logical_epoch,
        selected_unit_ids=list(base.required_unit_ids) + ["unit/z"],
    )
    assert rebuilt.manifest_root() != base_root


def test_duplicate_and_reordered_required_units_are_rejected() -> None:
    policy = sample_verification_policy()
    unit_a = sample_required_unit(proof_unit_id="unit/a")
    unit_b = sample_required_unit(proof_unit_id="unit/b")
    with pytest.raises(ManifestError, match="canonically sorted"):
        build_verification_requirement_manifest(
            repository_id="repo/datasets",
            revision="rev-1",
            repository_state_cid=_cid("state"),
            source_root_cid=_cid("source"),
            required_units=(unit_b, unit_a),
            policy=policy,
            environment_cid=_cid("env"),
            dependency_lock_cid=_cid("lock"),
            configuration_cid=_cid("config"),
        )
    with pytest.raises(ManifestError, match="duplicate"):
        build_verification_requirement_manifest(
            repository_id="repo/datasets",
            revision="rev-1",
            repository_state_cid=_cid("state"),
            source_root_cid=_cid("source"),
            required_units=(unit_a, unit_a),
            policy=policy,
            environment_cid=_cid("env"),
            dependency_lock_cid=_cid("lock"),
            configuration_cid=_cid("config"),
        )


def test_missing_fields_secrets_and_incomplete_set_fail_closed() -> None:
    base = sample_verification_requirement_manifest().to_canonical()
    missing = dict(base)
    del missing["policy_cid"]
    with pytest.raises(ManifestError, match="missing required fields"):
        VerificationRequirementManifest.from_canonical(missing)

    with pytest.raises(ManifestError, match="secret"):
        VerificationRequirementManifest.from_canonical({**base, "witness": "leak"})

    with pytest.raises(ManifestError, match="secret"):
        VerificationPolicy.from_canonical(
            {**sample_verification_policy().to_canonical(), "created_at": "now"}
        )

    manifest = sample_verification_requirement_manifest()
    with pytest.raises(ManifestError, match="incomplete required set"):
        manifest.assert_required_set_complete(["unit/a"])  # missing unit/b

    # Policy cannot disable removal authorization or allow selected omission.
    with pytest.raises(ManifestError, match="require_removal_authorization"):
        sample_verification_policy(require_removal_authorization=False)
    with pytest.raises(ManifestError, match="allow_selected_unit_omission"):
        sample_verification_policy(allow_selected_unit_omission=True)

    # Removal must bind the manifest policy CID.
    policy = sample_verification_policy()
    foreign_policy = sample_verification_policy(policy_id="policy/foreign")
    unit = sample_required_unit(proof_unit_id="unit/a")
    removal = UnitRemovalAuthorization(
        proof_unit_id="unit/z",
        policy_cid=foreign_policy.policy_cid(),
        removal_reason="test_deleted",
        risk_class="medium",
        tombstone_cid=ABSENCE_TOKEN,
        authorized=True,
        logical_epoch=1,
    )
    with pytest.raises(ManifestError, match="mismatched policy"):
        build_verification_requirement_manifest(
            repository_id="repo/datasets",
            revision="rev-1",
            repository_state_cid=_cid("state"),
            source_root_cid=_cid("source"),
            required_units=(unit,),
            policy=policy,
            environment_cid=_cid("env"),
            dependency_lock_cid=_cid("lock"),
            configuration_cid=_cid("config"),
            permitted_removals=(removal,),
            logical_epoch=1,
        )


def test_source_root_is_not_repository_state() -> None:
    policy = sample_verification_policy()
    shared = _cid("shared")
    with pytest.raises(ManifestError, match="source_root_cid"):
        build_verification_requirement_manifest(
            repository_id="repo/datasets",
            revision="rev-1",
            repository_state_cid=shared,
            source_root_cid=shared,
            required_units=(sample_required_unit(),),
            policy=policy,
            environment_cid=_cid("env"),
            dependency_lock_cid=_cid("lock"),
            configuration_cid=_cid("config"),
        )


def test_unknown_removal_reason_and_schema_fail_closed() -> None:
    with pytest.raises(ManifestError, match="unknown removal reason"):
        UnitRemovalAuthorization(
            proof_unit_id="unit/a",
            policy_cid=_cid("policy"),
            removal_reason="deleted_for_fun",
            risk_class="low",
            tombstone_cid=ABSENCE_TOKEN,
            authorized=True,
            logical_epoch=0,
        )
    with pytest.raises(ManifestError, match="unknown removal reasons"):
        sample_verification_policy(permitted_removal_reasons=["not-a-reason"])

    payload = sample_verification_requirement_manifest().to_canonical()
    payload["schema"] = "wrong/schema@9"
    with pytest.raises(ManifestError, match="unsupported manifest schema"):
        VerificationRequirementManifest.from_canonical(payload)


def test_canonicalization_version_is_bound() -> None:
    policy = sample_verification_policy()
    assert policy.canonicalization_version == CANONICALIZATION_VERSION
    manifest = sample_verification_requirement_manifest(policy_cid=policy.policy_cid())
    assert manifest.canonicalization_version == CANONICALIZATION_VERSION
    payload = manifest.to_canonical()
    payload["canonicalization_version"] = "ips/canonicalization@99"
    mutated = VerificationRequirementManifest.from_canonical(payload)
    assert mutated.manifest_root() != manifest.manifest_root()
