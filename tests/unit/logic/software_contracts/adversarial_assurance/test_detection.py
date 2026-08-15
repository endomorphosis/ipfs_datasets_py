"""Unit vectors for explained expected-detection construction (AAE-023)."""

from __future__ import annotations

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
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.execution_contracts import (
    DetectorKind,
    DetectorPrediction,
    DetectorStrength,
    ExpectedDetectionSet,
    verify_detection_set_identity,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MutationCandidate,
    MutationRiskClass,
    PropertyClass,
    SeedConfigBinding,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.detection import (
    CLAIM_BINDING_SCHEMA,
    DETECTION_ASSURANCE_MANIFEST_INTERFACE,
    DETECTOR_CATALOG_ENTRY_SCHEMA,
    GENERATOR_ID,
    GENERATOR_VERSION,
    PREDICT_DETECTION_SET_INTERFACE,
    PROPERTY_CLASS_DETECTOR_KINDS,
    SEMANTIC_DEPENDENCY_EDGE_SCHEMA,
    SYNTHETIC_FULL_SUITE_ID,
    SYNTHETIC_HUMAN_REVIEW_ID,
    SYNTHETIC_SEAL_ID,
    SYNTHETIC_TYPE_CHECK_ID,
    ClaimBinding,
    DependencyRelation,
    DetectionAssuranceManifest,
    DetectionPredictionError,
    DetectorCatalogEntry,
    SemanticDependencyEdge,
    assert_prediction_explained,
    dependency_relations,
    predict_detection_set,
    preferred_detector_kinds_for_property,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


REPO_ID = "repository:sha256:test-repo-identity"
REPO_STATE = _cid("repo-state")


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
        "repository_id": REPO_ID,
        "repository_state_cid": REPO_STATE,
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


def _candidate(**overrides: object) -> MutationCandidate:
    fields = {
        "header": _header("mutation_candidate"),
        "candidate_id": "cand_control_flow_invert_0",
        "operator_id": "control_flow_invert",
        "operator_version": "1",
        "operator_cid": _cid("operator-control-flow"),
        "target_id": "mod_fn",
        "target_cid": _cid("target-mod-fn"),
        "seed_config": _seed_config(),
        "source_root_cid": _cid("source-root"),
        "repository_state_cid": REPO_STATE,
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


def _unit_detector(**overrides: object) -> DetectorCatalogEntry:
    fields = {
        "detector_id": "unit.test_branch",
        "detector_revision": "3.2.1",
        "detector_kind": DetectorKind.UNIT_TEST,
        "covered_property_classes": (PropertyClass.CONTROL_INVARIANT,),
        "anchor_ids": ("tests.test_branch",),
        "default_strength": DetectorStrength.REQUIRED,
        "expected_terminal_status": AssuranceTerminalStatus.COMPLETE,
        "observation_template": "unit test asserts inverted branch is rejected",
        "claim_ids": ("claim.control_branch",),
        "notes": "selected unit detector",
        "metadata": {},
    }
    fields.update(overrides)
    return DetectorCatalogEntry(**fields)  # type: ignore[arg-type]


def _static_detector(**overrides: object) -> DetectorCatalogEntry:
    fields = {
        "detector_id": "static.authz_rule",
        "detector_revision": "1.4.0",
        "detector_kind": DetectorKind.STATIC_RULE,
        "covered_property_classes": (PropertyClass.AUTHORIZATION,),
        "anchor_ids": ("static.authz",),
        "default_strength": DetectorStrength.REQUIRED,
        "expected_terminal_status": AssuranceTerminalStatus.COMPLETE,
        "observation_template": "static rule flags removed authorization guard",
        "claim_ids": ("claim.authz",),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return DetectorCatalogEntry(**fields)  # type: ignore[arg-type]


def _edge(
    from_id: str,
    to_id: str,
    relation: DependencyRelation | str = DependencyRelation.TESTED_BY,
    **overrides: object,
) -> SemanticDependencyEdge:
    fields = {
        "from_id": from_id,
        "to_id": to_id,
        "relation": relation,
        "notes": None,
    }
    fields.update(overrides)
    return SemanticDependencyEdge(**fields)  # type: ignore[arg-type]


def _claim(**overrides: object) -> ClaimBinding:
    fields = {
        "claim_id": "claim.control_branch",
        "property_class": PropertyClass.CONTROL_INVARIANT,
        "statement": "branch predicate must preserve control invariant",
        "symbol_ids": ("mod.fn",),
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return ClaimBinding(**fields)  # type: ignore[arg-type]


def _manifest(**overrides: object) -> DetectionAssuranceManifest:
    fields = {
        "repository_id": REPO_ID,
        "repository_state_cid": REPO_STATE,
        "detectors": (_unit_detector(),),
        "dependency_edges": (
            _edge("mod.fn", "tests.test_branch", DependencyRelation.TESTED_BY),
        ),
        "claims": (_claim(),),
        "enable_type_check_fallback": True,
        "enable_full_suite_fallback": True,
        "enable_incremental_seal_fallback": True,
        "enable_human_review_fallback": True,
        "observation_complete": True,
        "notes": None,
        "metadata": {},
    }
    fields.update(overrides)
    return DetectionAssuranceManifest(**fields)  # type: ignore[arg-type]


def _assert_fully_explained(prediction: DetectorPrediction) -> None:
    assert prediction.violated_claim
    assert prediction.observation_rationale
    assert prediction.dependency_path
    assert prediction.strength in {
        DetectorStrength.REQUIRED.value,
        DetectorStrength.OPTIONAL.value,
    }
    assert prediction.expected_terminal_status
    assert prediction.detector_id
    assert prediction.metadata["detector_identity"] == prediction.detector_id
    assert prediction.metadata["detector_revision"]
    assert_prediction_explained(prediction)


# ---------------------------------------------------------------------------
# Model sealing / identity
# ---------------------------------------------------------------------------


def test_detector_catalog_entry_round_trip_and_identity() -> None:
    entry = _unit_detector()
    restored = DetectorCatalogEntry.from_dict(entry.to_dict())
    assert restored == entry
    assert restored.catalog_entry_cid == entry.catalog_entry_cid
    assert restored.detector_revision == "3.2.1"


def test_semantic_dependency_edge_rejects_self_loop() -> None:
    with pytest.raises(DetectionPredictionError, match="self-loop"):
        _edge("mod.fn", "mod.fn")


def test_claim_binding_round_trip() -> None:
    claim = _claim()
    restored = ClaimBinding.from_dict(claim.to_dict())
    assert restored.claim_cid == claim.claim_cid
    assert restored.statement == claim.statement


def test_manifest_round_trip_and_unique_detectors() -> None:
    manifest = _manifest()
    restored = DetectionAssuranceManifest.from_dict(manifest.to_dict())
    assert restored.manifest_cid == manifest.manifest_cid
    assert restored.interface_id if hasattr(restored, "interface_id") else True
    payload = manifest.to_dict()
    assert payload["schema"]
    assert payload["interface_id"] == DETECTION_ASSURANCE_MANIFEST_INTERFACE

    with pytest.raises(DetectionPredictionError, match="unique"):
        _manifest(detectors=(_unit_detector(), _unit_detector()))


def test_property_class_detector_kind_mapping_is_total() -> None:
    for prop in PropertyClass:
        kinds = preferred_detector_kinds_for_property(prop)
        assert kinds
        assert PROPERTY_CLASS_DETECTOR_KINDS[prop.value] == kinds
    assert DependencyRelation.TESTED_BY.value in dependency_relations()


# ---------------------------------------------------------------------------
# predict_detection_set happy path
# ---------------------------------------------------------------------------


def test_predict_detection_set_binds_explained_catalog_detector() -> None:
    eds = predict_detection_set(_candidate(), _manifest())
    assert isinstance(eds, ExpectedDetectionSet)
    verify_detection_set_identity(eds)
    assert eds.candidate_id == "cand_control_flow_invert_0"
    assert eds.header.artifact_kind == "expected_detection_set"
    assert eds.header.versions.generator.generator_id == GENERATOR_ID
    assert eds.header.versions.generator.generator_version == GENERATOR_VERSION
    assert (
        eds.header.versions.generator.interface_id
        == PREDICT_DETECTION_SET_INTERFACE
    )

    assert "unit.test_branch" in eds.predicted_detector_ids
    prediction = eds.detector_by_id("unit.test_branch")
    _assert_fully_explained(prediction)
    assert prediction.detector_kind == DetectorKind.UNIT_TEST.value
    assert prediction.strength == DetectorStrength.REQUIRED.value
    assert (
        prediction.expected_terminal_status
        == AssuranceTerminalStatus.COMPLETE.value
    )
    assert (
        prediction.violated_claim
        == "branch predicate must preserve control invariant"
    )
    assert "tests.test_branch" in prediction.dependency_path
    assert "mod.fn" in prediction.dependency_path
    assert prediction.metadata["detector_identity"] == "unit.test_branch"
    assert prediction.metadata["detector_revision"] == "3.2.1"
    assert prediction.metadata["claim_id"] == "claim.control_branch"
    assert "inverted branch" in prediction.observation_rationale


def test_predict_detection_set_is_deterministic() -> None:
    mutation = _candidate()
    manifest = _manifest()
    first = predict_detection_set(mutation, manifest)
    second = predict_detection_set(mutation, manifest)
    assert first.detection_set_cid == second.detection_set_cid
    assert first.to_dict() == second.to_dict()


def test_predict_detection_set_accepts_mapping_inputs() -> None:
    mutation = _candidate()
    manifest = _manifest()
    eds = predict_detection_set(mutation.to_dict(), manifest.to_dict())
    assert eds.candidate_cid == mutation.candidate_cid
    for prediction in eds.predicted_detectors:
        _assert_fully_explained(prediction)


def test_multi_hop_dependency_path_reaches_detector() -> None:
    manifest = _manifest(
        dependency_edges=(
            _edge("mod.fn", "mod.helper", DependencyRelation.CALLS),
            _edge(
                "mod.helper",
                "tests.test_branch",
                DependencyRelation.TESTED_BY,
            ),
        )
    )
    eds = predict_detection_set(_candidate(), manifest)
    prediction = eds.detector_by_id("unit.test_branch")
    path = set(prediction.dependency_path)
    assert "mod.fn" in path
    assert "mod.helper" in path
    assert "tests.test_branch" in path
    _assert_fully_explained(prediction)


def test_authorization_detector_and_high_risk_fallbacks() -> None:
    mutation = _candidate(
        expected_violated_property_classes=(PropertyClass.AUTHORIZATION,),
        risk_class=MutationRiskClass.CRITICAL_SECURITY,
        transformation_summary="drop principal check in auth.guard",
        scope_symbol_ids=("auth.guard",),
        header=_header(
            "mutation_candidate",
            target_symbol_ids=("auth.guard",),
            metadata={"risk_class": "critical_security"},
        ),
    )
    manifest = _manifest(
        detectors=(_static_detector(),),
        dependency_edges=(
            _edge("auth.guard", "static.authz", DependencyRelation.ENFORCED_BY),
        ),
        claims=(
            _claim(
                claim_id="claim.authz",
                property_class=PropertyClass.AUTHORIZATION,
                statement="caller principal must match tenant binding",
                symbol_ids=("auth.guard",),
            ),
        ),
    )
    eds = predict_detection_set(mutation, manifest)
    ids = set(eds.predicted_detector_ids)
    assert "static.authz_rule" in ids
    assert SYNTHETIC_FULL_SUITE_ID in ids
    assert SYNTHETIC_HUMAN_REVIEW_ID in ids
    for prediction in eds.predicted_detectors:
        _assert_fully_explained(prediction)
    static = eds.detector_by_id("static.authz_rule")
    assert static.metadata["detector_revision"] == "1.4.0"
    assert static.strength == DetectorStrength.REQUIRED.value
    suite = eds.detector_by_id(SYNTHETIC_FULL_SUITE_ID)
    assert suite.strength == DetectorStrength.OPTIONAL.value
    assert suite.detector_kind == DetectorKind.FULL_SUITE.value


def test_type_check_fallback_for_schema_contract() -> None:
    mutation = _candidate(
        expected_violated_property_classes=(PropertyClass.SCHEMA_CONTRACT,),
        risk_class=MutationRiskClass.CRITICAL_INVARIANT,
        transformation_summary="widen required field to optional",
    )
    # No catalog detectors; synthetic type-check should still apply.
    manifest = _manifest(
        detectors=(),
        dependency_edges=(),
        claims=(
            _claim(
                claim_id="claim.schema",
                property_class=PropertyClass.SCHEMA_CONTRACT,
                statement="required fields must remain required",
                symbol_ids=("mod.fn",),
            ),
        ),
    )
    eds = predict_detection_set(mutation, manifest)
    assert SYNTHETIC_TYPE_CHECK_ID in eds.predicted_detector_ids
    prediction = eds.detector_by_id(SYNTHETIC_TYPE_CHECK_ID)
    _assert_fully_explained(prediction)
    assert prediction.detector_kind == DetectorKind.TYPE_CHECK.value
    assert prediction.metadata["synthetic"] is True
    assert prediction.metadata["detector_revision"]


def test_incremental_seal_fallback_for_proof_adequacy() -> None:
    mutation = _candidate(
        expected_violated_property_classes=(PropertyClass.PROOF_ADEQUACY,),
        risk_class=MutationRiskClass.PROOF_RECEIPT_TRUST,
        transformation_summary="omit obligation from proof discharge",
    )
    manifest = _manifest(
        detectors=(),
        dependency_edges=(),
        claims=(
            _claim(
                claim_id="claim.proof",
                property_class=PropertyClass.PROOF_ADEQUACY,
                statement="authorization lemma must discharge obligation",
                symbol_ids=("mod.fn",),
            ),
        ),
    )
    eds = predict_detection_set(mutation, manifest)
    assert SYNTHETIC_SEAL_ID in eds.predicted_detector_ids
    prediction = eds.detector_by_id(SYNTHETIC_SEAL_ID)
    _assert_fully_explained(prediction)
    assert prediction.detector_kind == DetectorKind.INCREMENTAL_SEAL.value


def test_likely_equivalent_marks_detectors_optional_and_human_review() -> None:
    mutation = _candidate(likely_equivalent=True)
    eds = predict_detection_set(mutation, _manifest())
    unit = eds.detector_by_id("unit.test_branch")
    assert unit.strength == DetectorStrength.OPTIONAL.value
    assert SYNTHETIC_HUMAN_REVIEW_ID in eds.predicted_detector_ids
    human = eds.detector_by_id(SYNTHETIC_HUMAN_REVIEW_ID)
    assert (
        human.expected_terminal_status
        == AssuranceTerminalStatus.HUMAN_REVIEW_REQUIRED.value
    )
    for prediction in eds.predicted_detectors:
        _assert_fully_explained(prediction)


def test_every_prediction_names_required_explanation_fields() -> None:
    eds = predict_detection_set(
        _candidate(
            expected_violated_property_classes=(
                PropertyClass.CONTROL_INVARIANT,
                PropertyClass.AUTHORIZATION,
            ),
            risk_class=MutationRiskClass.AUTHORIZATION,
        ),
        _manifest(
            detectors=(_unit_detector(), _static_detector()),
            dependency_edges=(
                _edge("mod.fn", "tests.test_branch"),
                _edge("mod.fn", "static.authz", DependencyRelation.ENFORCED_BY),
            ),
            claims=(
                _claim(),
                _claim(
                    claim_id="claim.authz",
                    property_class=PropertyClass.AUTHORIZATION,
                    statement="authorization check must remain present",
                    symbol_ids=("mod.fn",),
                ),
            ),
        ),
    )
    assert len(eds.predicted_detectors) >= 2
    for prediction in eds.predicted_detectors:
        _assert_fully_explained(prediction)
        # Exact identity/revision pair is sealed into prediction identity.
        sealed = DetectorPrediction.from_dict(prediction.to_dict())
        assert sealed.prediction_cid == prediction.prediction_cid
        assert sealed.metadata["detector_identity"] == sealed.detector_id
        assert sealed.metadata["detector_revision"]


# ---------------------------------------------------------------------------
# Fail-closed negatives
# ---------------------------------------------------------------------------


def test_fails_closed_when_observation_incomplete() -> None:
    with pytest.raises(DetectionPredictionError, match="observation_complete"):
        predict_detection_set(
            _candidate(),
            _manifest(observation_complete=False),
        )


def test_fails_closed_on_repository_mismatch() -> None:
    with pytest.raises(DetectionPredictionError, match="repository_id"):
        predict_detection_set(
            _candidate(),
            _manifest(repository_id="repository:sha256:other-repo"),
        )
    with pytest.raises(DetectionPredictionError, match="repository_state_cid"):
        predict_detection_set(
            _candidate(),
            _manifest(repository_state_cid=_cid("other-state")),
        )


def test_fails_closed_when_no_detectors_reachable() -> None:
    manifest = _manifest(
        detectors=(_unit_detector(),),
        dependency_edges=(
            # Edge does not connect mutation scope to the detector anchor.
            _edge("other.module", "tests.test_branch"),
        ),
        claims=(_claim(),),
        enable_type_check_fallback=False,
        enable_full_suite_fallback=False,
        enable_incremental_seal_fallback=False,
        enable_human_review_fallback=False,
    )
    with pytest.raises(DetectionPredictionError, match="no detectors reachable"):
        predict_detection_set(_candidate(), manifest)


def test_unreachable_detector_is_not_predicted() -> None:
    manifest = _manifest(
        detectors=(
            _unit_detector(),
            _unit_detector(
                detector_id="unit.orphan",
                detector_revision="9.0.0",
                anchor_ids=("tests.orphan",),
                claim_ids=(),
            ),
        ),
        dependency_edges=(
            _edge("mod.fn", "tests.test_branch"),
            # orphan detector is isolated
        ),
        enable_full_suite_fallback=False,
        enable_human_review_fallback=False,
        enable_type_check_fallback=False,
        enable_incremental_seal_fallback=False,
    )
    eds = predict_detection_set(_candidate(), manifest)
    assert "unit.test_branch" in eds.predicted_detector_ids
    assert "unit.orphan" not in eds.predicted_detector_ids


def test_assert_prediction_explained_rejects_missing_revision() -> None:
    prediction = DetectorPrediction(
        detector_id="unit.test_branch",
        detector_kind=DetectorKind.UNIT_TEST,
        violated_claim="claim",
        observation_rationale="rationale",
        dependency_path=("mod.fn", "tests.test_branch"),
        strength=DetectorStrength.REQUIRED,
        expected_terminal_status=AssuranceTerminalStatus.COMPLETE,
        metadata={"detector_identity": "unit.test_branch"},
    )
    with pytest.raises(DetectionPredictionError, match="detector_revision"):
        assert_prediction_explained(prediction)


def test_catalog_entry_rejects_empty_anchors_and_properties() -> None:
    with pytest.raises(DetectionPredictionError, match="anchor_ids"):
        _unit_detector(anchor_ids=())
    with pytest.raises(DetectionPredictionError, match="covered_property_classes"):
        _unit_detector(covered_property_classes=())


def test_unknown_dependency_relation_fails_closed() -> None:
    with pytest.raises(DetectionPredictionError, match="relation"):
        _edge("mod.fn", "tests.test_branch", relation="invented_relation")


def test_manifest_schema_constants_are_versioned() -> None:
    assert DETECTOR_CATALOG_ENTRY_SCHEMA.endswith("@1")
    assert SEMANTIC_DEPENDENCY_EDGE_SCHEMA.endswith("@1")
    assert CLAIM_BINDING_SCHEMA.endswith("@1")
    assert PREDICT_DETECTION_SET_INTERFACE == "predict_detection_set@1"


def test_prediction_cid_changes_with_detector_revision() -> None:
    mutation = _candidate()
    base = predict_detection_set(mutation, _manifest())
    revised = predict_detection_set(
        mutation,
        _manifest(detectors=(_unit_detector(detector_revision="3.2.2"),)),
    )
    left = base.detector_by_id("unit.test_branch")
    right = revised.detector_by_id("unit.test_branch")
    assert left.metadata["detector_revision"] == "3.2.1"
    assert right.metadata["detector_revision"] == "3.2.2"
    assert left.prediction_cid != right.prediction_cid
    assert base.detection_set_cid != revised.detection_set_cid


def test_synthesized_claim_when_manifest_omits_claims() -> None:
    eds = predict_detection_set(
        _candidate(),
        _manifest(claims=()),
    )
    prediction = eds.detector_by_id("unit.test_branch")
    assert "control_invariant" in prediction.violated_claim
    assert "cand_control_flow_invert_0" in prediction.violated_claim
    _assert_fully_explained(prediction)
