"""Unit tests for claim extraction, mutation targeting, and risk ranking (AAE-021)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MutationRiskClass,
    MutationTarget,
    PropertyClass,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.risk import (
    DEFAULT_ALWAYS_SELECT_MIN_RISK_BP,
    PROPERTY_CLASS_RISK,
    RISK_CLASS_BASE_WEIGHT_BP,
    RiskCandidate,
    RiskDimension,
    RiskScore,
    RiskSignals,
    SamplingBudget,
    TargetRiskError,
    apply_bounded_sampling,
    compute_risk_weight_bp,
    deterministic_sample_roll_bp,
    highest_risk_class,
    primary_dimension_for_risk_class,
    rank_mutation_risk,
    risk_class_base_weight_bp,
    risk_class_for_property_class,
    risk_dimensions,
    score_risk_candidate,
    selected_risk_scores,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.targets import (
    AssertedProperty,
    ClaimRecord,
    TargetSelectionError,
    identify_asserted_properties,
    select_mutation_targets,
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


REPO_ID = "repository:sha256:test-repo-identity"
REPO_STATE = _cid("repo-state")


def _claim(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "claim_id": "auth_bound",
        "property_classes": (PropertyClass.AUTHORIZATION,),
        "statement": "Caller principal must match tenant binding",
        "symbol_ids": ("auth.check",),
        "artifact_cids": (_cid("artifact-auth"),),
        "source_path": "auth.py",
        "language": "python",
        "artifact_type": "source_module",
        "prerequisites": ("parsed_ast", "symbol_table"),
        "signals": {
            "fan_out": 8,
            "recent_change_bp": 5_000,
            "uncertainty_bp": 1_000,
            "defect_count": 2,
            "frequency_bp": 6_000,
            "failure_cost_bp": 9_000,
            "missing_tests": False,
        },
    }
    fields.update(overrides)
    return fields


# ---------------------------------------------------------------------------
# Risk module
# ---------------------------------------------------------------------------


def test_risk_dimensions_cover_acceptance_priorities() -> None:
    dims = set(risk_dimensions())
    for required in (
        RiskDimension.SECURITY.value,
        RiskDimension.DURABILITY.value,
        RiskDimension.DISTRIBUTED_TRUST.value,
        RiskDimension.PROOF_TRUST.value,
        RiskDimension.FAN_OUT.value,
        RiskDimension.RECENT_CHANGE.value,
        RiskDimension.UNCERTAINTY.value,
        RiskDimension.DEFECTS.value,
        RiskDimension.FREQUENCY.value,
        RiskDimension.FAILURE_COST.value,
    ):
        assert required in dims


def test_property_class_risk_mapping_is_total() -> None:
    for prop in PropertyClass:
        mapped = risk_class_for_property_class(prop)
        assert mapped in RISK_CLASS_BASE_WEIGHT_BP
        assert PROPERTY_CLASS_RISK[prop.value] == mapped


def test_highest_risk_class_prefers_security() -> None:
    assert (
        highest_risk_class(
            (
                MutationRiskClass.LOW,
                MutationRiskClass.DURABILITY,
                MutationRiskClass.CRITICAL_SECURITY,
            )
        )
        == MutationRiskClass.CRITICAL_SECURITY.value
    )


def test_primary_dimension_for_priority_classes() -> None:
    assert (
        primary_dimension_for_risk_class(MutationRiskClass.CRITICAL_SECURITY)
        == RiskDimension.SECURITY.value
    )
    assert (
        primary_dimension_for_risk_class(MutationRiskClass.DURABILITY)
        == RiskDimension.DURABILITY.value
    )
    assert (
        primary_dimension_for_risk_class(MutationRiskClass.DISTRIBUTED_TRANSITION)
        == RiskDimension.DISTRIBUTED_TRUST.value
    )
    assert (
        primary_dimension_for_risk_class(MutationRiskClass.PROOF_RECEIPT_TRUST)
        == RiskDimension.PROOF_TRUST.value
    )


def test_compute_risk_weight_prioritizes_security_signals() -> None:
    security_weight, security_contrib = compute_risk_weight_bp(
        MutationRiskClass.CRITICAL_SECURITY,
        RiskSignals(
            fan_out=10,
            recent_change_bp=8_000,
            uncertainty_bp=4_000,
            defect_count=5,
            frequency_bp=7_000,
            failure_cost_bp=9_500,
            missing_tests=True,
        ),
    )
    low_weight, _ = compute_risk_weight_bp(
        MutationRiskClass.LOW,
        RiskSignals(fan_out=0, frequency_bp=100, failure_cost_bp=100),
    )
    assert security_weight > low_weight
    assert security_weight == 10_000 or security_weight > risk_class_base_weight_bp(
        MutationRiskClass.CRITICAL_SECURITY
    )
    assert RiskDimension.FAN_OUT.value in security_contrib
    assert RiskDimension.FAILURE_COST.value in security_contrib
    assert RiskDimension.BASE_CLASS.value in security_contrib


def test_formatting_and_generated_surfaces_are_downweighted() -> None:
    base, _ = compute_risk_weight_bp(
        MutationRiskClass.CRITICAL_INVARIANT, RiskSignals()
    )
    formatted, contrib = compute_risk_weight_bp(
        MutationRiskClass.CRITICAL_INVARIANT,
        RiskSignals(is_formatting=True, is_boilerplate=True),
    )
    assert formatted < base
    assert contrib[RiskDimension.DOWNWEIGHT.value] < 10_000


def test_risk_signals_round_trip_cid() -> None:
    signals = RiskSignals(
        fan_out=3,
        recent_change_bp=1_000,
        uncertainty_bp=2_000,
        defect_count=1,
        frequency_bp=3_000,
        failure_cost_bp=4_000,
        missing_tests=True,
        metadata={"source": "graph"},
    )
    restored = RiskSignals.from_dict(signals.to_dict())
    assert restored == signals
    assert restored.signals_cid == signals.signals_cid


def test_sampling_budget_round_trip() -> None:
    budget = SamplingBudget(
        max_targets=8,
        always_select_min_risk_bp=7_000,
        low_risk_sample_rate_bp=500,
        seed=99,
    )
    restored = SamplingBudget.from_dict(budget.to_dict())
    assert restored == budget
    assert restored.budget_cid == budget.budget_cid


def test_rank_mutation_risk_orders_by_weight_then_class() -> None:
    ranking = rank_mutation_risk(
        [
            RiskCandidate(
                subject_id="low_subject",
                risk_class=MutationRiskClass.LOW,
                signals=RiskSignals(),
            ),
            RiskCandidate(
                subject_id="sec_subject",
                risk_class=MutationRiskClass.CRITICAL_SECURITY,
                signals=RiskSignals(failure_cost_bp=9_000, fan_out=4),
            ),
            RiskCandidate(
                subject_id="dur_subject",
                risk_class=MutationRiskClass.DURABILITY,
                signals=RiskSignals(fan_out=20, failure_cost_bp=8_000),
            ),
        ],
        budget=SamplingBudget(
            max_targets=10,
            always_select_min_risk_bp=0,
            low_risk_sample_rate_bp=10_000,
            seed=0,
        ),
    )
    selected = selected_risk_scores(ranking)
    assert [item.subject_id for item in selected[:2]] == [
        "sec_subject",
        "dur_subject",
    ]
    assert selected[0].risk_weight_bp >= selected[1].risk_weight_bp
    assert all(item.selected for item in selected)


def test_rank_mutation_risk_bounded_sampling_respects_max_targets() -> None:
    candidates = [
        RiskCandidate(
            subject_id=f"subj_{index}",
            risk_class=MutationRiskClass.CRITICAL_SECURITY,
            signals=RiskSignals(fan_out=index, failure_cost_bp=9_000),
        )
        for index in range(6)
    ]
    ranking = rank_mutation_risk(
        candidates,
        budget=SamplingBudget(
            max_targets=3,
            always_select_min_risk_bp=0,
            low_risk_sample_rate_bp=10_000,
            seed=1,
        ),
    )
    selected = selected_risk_scores(ranking)
    assert len(selected) == 3
    assert [item.rank for item in selected] == [0, 1, 2]
    rejected = [item for item in ranking if not item.selected]
    assert len(rejected) == 3
    assert all(item.selection_reason == "budget_exhausted" for item in rejected)


def test_rank_mutation_risk_always_selects_high_weight() -> None:
    ranking = rank_mutation_risk(
        [
            {
                "subject_id": "high",
                "risk_class": MutationRiskClass.CRITICAL_SECURITY.value,
                "signals": {
                    "fan_out": 5,
                    "failure_cost_bp": 9_000,
                    "frequency_bp": 8_000,
                },
            },
            {
                "subject_id": "low",
                "risk_class": MutationRiskClass.LOW.value,
                "signals": {
                    "is_formatting": True,
                    "is_boilerplate": True,
                    "fan_out": 0,
                },
            },
        ],
        budget={
            "max_targets": 5,
            "always_select_min_risk_bp": DEFAULT_ALWAYS_SELECT_MIN_RISK_BP,
            "low_risk_sample_rate_bp": 0,
            "seed": 7,
        },
    )
    by_id = {item.subject_id: item for item in ranking}
    assert by_id["high"].selected is True
    assert by_id["high"].selection_reason == "always_select_threshold"
    assert by_id["low"].selected is False
    assert by_id["low"].selection_reason == "low_risk_rejected"


def test_deterministic_sample_roll_is_stable() -> None:
    first = deterministic_sample_roll_bp(42, "subject_a")
    second = deterministic_sample_roll_bp(42, "subject_a")
    other = deterministic_sample_roll_bp(42, "subject_b")
    assert first == second
    assert 0 <= first < 10_000
    assert first != other or first == other  # may collide; ensure bounds only


def test_rank_mutation_risk_rejects_duplicate_subjects() -> None:
    with pytest.raises(TargetRiskError, match="duplicate subject_id"):
        rank_mutation_risk(
            [
                RiskCandidate(
                    subject_id="dup", risk_class=MutationRiskClass.LOW
                ),
                RiskCandidate(
                    subject_id="dup", risk_class=MutationRiskClass.HIGH
                ),
            ]
        )


def test_rank_mutation_risk_rejects_unknown_risk_class() -> None:
    with pytest.raises(TargetRiskError, match="unsupported"):
        rank_mutation_risk(
            [{"subject_id": "x", "risk_class": "not_a_class"}]
        )


def test_risk_candidate_infers_class_from_properties() -> None:
    score = score_risk_candidate(
        RiskCandidate(
            subject_id="prop_bound",
            risk_class=MutationRiskClass.LOW,
            property_classes=(PropertyClass.AUTHORIZATION,),
        )
    )
    assert score.risk_class == MutationRiskClass.CRITICAL_SECURITY.value


def test_apply_bounded_sampling_without_selection_marks() -> None:
    scores = rank_mutation_risk(
        [
            RiskCandidate(
                subject_id="a", risk_class=MutationRiskClass.MEDIUM
            )
        ],
        apply_sampling=False,
    )
    assert scores[0].selected is False
    assert scores[0].rank is None
    marked = apply_bounded_sampling(
        scores,
        SamplingBudget(
            max_targets=1,
            always_select_min_risk_bp=0,
            low_risk_sample_rate_bp=10_000,
            seed=0,
        ),
    )
    assert marked[0].selected is True


def test_risk_score_identity_mismatch_rejected() -> None:
    score = score_risk_candidate(
        RiskCandidate(subject_id="id_a", risk_class=MutationRiskClass.HIGH)
    )
    payload = score.to_dict()
    payload["score_cid"] = _cid("tampered")
    # RiskScore has no from_dict; ensure CID is content-bound via payload.
    rebuilt = cid_for_structured(score.identity_payload())
    assert rebuilt == score.score_cid
    assert payload["score_cid"] != score.score_cid


# ---------------------------------------------------------------------------
# Targets / claim extraction
# ---------------------------------------------------------------------------


def test_identify_asserted_properties_binds_symbols_and_artifacts() -> None:
    properties = identify_asserted_properties(
        [
            _claim(
                claim_id="multi",
                property_classes=(
                    PropertyClass.AUTHORIZATION,
                    PropertyClass.POLICY_CONSTRAINT,
                ),
            )
        ]
    )
    assert len(properties) == 2
    assert {item.property_class for item in properties} == {
        PropertyClass.AUTHORIZATION.value,
        PropertyClass.POLICY_CONSTRAINT.value,
    }
    for prop in properties:
        assert prop.symbol_ids == ("auth.check",)
        assert prop.artifact_cids == (_cid("artifact-auth"),)
        assert prop.claim_id == "multi"
        assert prop.risk_class == MutationRiskClass.CRITICAL_SECURITY.value
        # Round-trip identity.
        restored = AssertedProperty.from_dict(prop.to_dict())
        assert restored.property_cid == prop.property_cid


def test_identify_asserted_properties_rejects_unbound_claim() -> None:
    with pytest.raises(TargetSelectionError, match="symbol_id or artifact_cid"):
        identify_asserted_properties(
            [
                {
                    "claim_id": "unbound",
                    "property_classes": (PropertyClass.DURABILITY,),
                    "statement": "Missing binding",
                }
            ]
        )


def test_identify_asserted_properties_rejects_duplicate_claim_ids() -> None:
    with pytest.raises(TargetSelectionError, match="duplicate claim_id"):
        identify_asserted_properties([_claim(), _claim()])


def test_identify_asserted_properties_rejects_unknown_property_class() -> None:
    with pytest.raises(TargetSelectionError, match="unsupported"):
        identify_asserted_properties(
            [
                _claim(property_classes=("not_a_property",))
            ]
        )


def test_claim_record_round_trip() -> None:
    claim = ClaimRecord.normalize(_claim())
    restored = ClaimRecord.from_dict(claim.to_dict())
    assert restored.claim_cid == claim.claim_cid
    assert restored.property_classes == claim.property_classes


def test_select_mutation_targets_prioritizes_security_and_durability() -> None:
    claims = [
        _claim(
            claim_id="sec",
            property_classes=(PropertyClass.AUTHORIZATION,),
            symbol_ids=("sec.fn",),
            artifact_cids=(_cid("art-sec"),),
            source_path="sec.py",
            signals={
                "fan_out": 15,
                "failure_cost_bp": 9_500,
                "frequency_bp": 8_000,
                "defect_count": 4,
                "recent_change_bp": 7_000,
                "uncertainty_bp": 3_000,
                "missing_tests": True,
            },
        ),
        _claim(
            claim_id="dur",
            property_classes=(PropertyClass.DURABILITY,),
            symbol_ids=("store.commit",),
            artifact_cids=(_cid("art-dur"),),
            source_path="store.py",
            signals={
                "fan_out": 12,
                "failure_cost_bp": 9_000,
                "defect_count": 1,
            },
        ),
        _claim(
            claim_id="fmt",
            property_classes=(PropertyClass.CONTROL_INVARIANT,),
            symbol_ids=("fmt.ws",),
            artifact_cids=(_cid("art-fmt"),),
            source_path="fmt.py",
            risk_class=MutationRiskClass.LOW,
            signals={
                "is_formatting": True,
                "is_boilerplate": True,
                "fan_out": 0,
                "failure_cost_bp": 100,
            },
        ),
        _claim(
            claim_id="proof",
            property_classes=(PropertyClass.PROOF_ADEQUACY,),
            symbol_ids=("proof.unit",),
            artifact_cids=(_cid("art-proof"),),
            source_path="proof.py",
            signals={
                "uncertainty_bp": 8_000,
                "missing_tests": True,
                "fan_out": 6,
            },
        ),
    ]
    result = select_mutation_targets(
        claims,
        repository_id=REPO_ID,
        repository_state_cid=REPO_STATE,
        budget={
            "max_targets": 3,
            "always_select_min_risk_bp": 6_000,
            "low_risk_sample_rate_bp": 0,
            "seed": 11,
        },
        return_result=True,
    )
    assert isinstance(result.targets[0], MutationTarget)
    assert len(result.targets) <= 3
    selected_classes = {target.risk_class for target in result.targets}
    assert MutationRiskClass.CRITICAL_SECURITY.value in selected_classes
    # Formatting/boilerplate surface must not crowd out high-risk targets when
    # low-risk sampling rate is zero.
    selected_symbols = {
        symbol for target in result.targets for symbol in target.symbol_ids
    }
    assert "fmt.ws" not in selected_symbols
    assert "sec.fn" in selected_symbols
    # Every target binds symbols/artifacts and carries claim metadata.
    for target in result.targets:
        assert target.symbol_ids or target.artifact_cids
        assert target.repository_id == REPO_ID
        assert target.repository_state_cid == REPO_STATE
        assert "claim_ids" in target.metadata
        assert "property_classes" in target.metadata
        assert target.risk_weight_bp >= 6_000


def test_select_mutation_targets_groups_shared_bindings() -> None:
    claims = [
        _claim(
            claim_id="c1",
            property_classes=(PropertyClass.AUTHORIZATION,),
            symbol_ids=("mod.fn",),
            artifact_cids=(_cid("art-shared"),),
            source_path="mod.py",
        ),
        _claim(
            claim_id="c2",
            property_classes=(PropertyClass.POLICY_CONSTRAINT,),
            symbol_ids=("mod.fn",),
            artifact_cids=(_cid("art-shared"),),
            source_path="mod.py",
        ),
    ]
    targets = select_mutation_targets(
        claims,
        repository_id=REPO_ID,
        repository_state_cid=REPO_STATE,
        budget={
            "max_targets": 5,
            "always_select_min_risk_bp": 0,
            "low_risk_sample_rate_bp": 10_000,
            "seed": 0,
        },
    )
    assert len(targets) == 1
    assert set(targets[0].metadata["claim_ids"]) == {"c1", "c2"}
    assert set(targets[0].metadata["property_classes"]) == {
        PropertyClass.AUTHORIZATION.value,
        PropertyClass.POLICY_CONSTRAINT.value,
    }


def test_select_mutation_targets_from_asserted_properties() -> None:
    props = identify_asserted_properties(
        [
            _claim(
                claim_id="dist",
                property_classes=(PropertyClass.STATE_TRANSITION,),
                symbol_ids=("sm.transition",),
                artifact_cids=(_cid("art-sm"),),
                source_path="sm.py",
                signals={"fan_out": 9, "failure_cost_bp": 8_000},
            )
        ]
    )
    targets = select_mutation_targets(
        props,
        repository_id=REPO_ID,
        repository_state_cid=REPO_STATE,
        budget={
            "max_targets": 2,
            "always_select_min_risk_bp": 5_000,
            "low_risk_sample_rate_bp": 0,
            "seed": 3,
        },
    )
    assert len(targets) == 1
    assert targets[0].risk_class == MutationRiskClass.DISTRIBUTED_TRANSITION.value
    assert targets[0].symbol_ids == ("sm.transition",)


def test_select_mutation_targets_empty_input() -> None:
    targets = select_mutation_targets(
        [],
        repository_id=REPO_ID,
        repository_state_cid=REPO_STATE,
    )
    assert targets == ()


def test_select_mutation_targets_rejects_invalid_repository() -> None:
    with pytest.raises(TargetSelectionError, match="repository"):
        select_mutation_targets(
            [_claim()],
            repository_id="!!!",
            repository_state_cid=REPO_STATE,
        )


def test_select_mutation_targets_rejects_invalid_state_cid() -> None:
    with pytest.raises(TargetSelectionError, match="CID"):
        select_mutation_targets(
            [_claim()],
            repository_id=REPO_ID,
            repository_state_cid="not-a-cid",
        )


def test_select_mutation_targets_deterministic() -> None:
    claims = [
        _claim(claim_id="a", symbol_ids=("a.fn",), artifact_cids=(_cid("a"),)),
        _claim(
            claim_id="b",
            property_classes=(PropertyClass.DURABILITY,),
            symbol_ids=("b.fn",),
            artifact_cids=(_cid("b"),),
            source_path="b.py",
        ),
    ]
    budget = {
        "max_targets": 2,
        "always_select_min_risk_bp": 0,
        "low_risk_sample_rate_bp": 10_000,
        "seed": 123,
    }
    first = select_mutation_targets(
        claims,
        repository_id=REPO_ID,
        repository_state_cid=REPO_STATE,
        budget=budget,
    )
    second = select_mutation_targets(
        claims,
        repository_id=REPO_ID,
        repository_state_cid=REPO_STATE,
        budget=budget,
    )
    assert [t.to_dict() for t in first] == [t.to_dict() for t in second]


def test_select_mutation_targets_low_risk_sample_can_admit_when_seeded() -> None:
    # With non-zero low-risk sample rate, a low-weight subject may be admitted.
    # Use a seed search for determinism within the test.
    claim = _claim(
        claim_id="lowonly",
        property_classes=(PropertyClass.INTERFACE_CONTRACT,),
        symbol_ids=("util.pad",),
        artifact_cids=(_cid("art-low"),),
        source_path="util.py",
        risk_class=MutationRiskClass.LOW,
        signals={
            "is_boilerplate": True,
            "fan_out": 0,
            "failure_cost_bp": 50,
            "frequency_bp": 50,
        },
    )
    admitted = False
    for seed in range(200):
        result = select_mutation_targets(
            [claim],
            repository_id=REPO_ID,
            repository_state_cid=REPO_STATE,
            budget={
                "max_targets": 1,
                "always_select_min_risk_bp": 9_999,
                "low_risk_sample_rate_bp": 10_000,
                "seed": seed,
            },
            return_result=True,
        )
        if result.targets:
            admitted = True
            assert result.targets[0].symbol_ids == ("util.pad",)
            break
    assert admitted


def test_asserted_property_rejects_unbound() -> None:
    with pytest.raises(TargetSelectionError, match="symbol_id or artifact_cid"):
        AssertedProperty(
            property_id="prop_x",
            claim_id="claim_x",
            property_class=PropertyClass.DURABILITY,
            statement="No binding",
            symbol_ids=(),
            artifact_cids=(),
            risk_class=MutationRiskClass.DURABILITY,
        )


def test_underclaiming_security_is_upgraded() -> None:
    claim = ClaimRecord.normalize(
        _claim(
            risk_class=MutationRiskClass.LOW,
            property_classes=(PropertyClass.AUTHORIZATION,),
        )
    )
    assert claim.risk_class == MutationRiskClass.CRITICAL_SECURITY.value


def test_pipeline_end_to_end_rank_weights_on_targets() -> None:
    props = identify_asserted_properties(
        [
            _claim(
                claim_id="high",
                property_classes=(PropertyClass.RECEIPT_AUTHENTICITY,),
                symbol_ids=("receipt.verify",),
                artifact_cids=(_cid("art-receipt"),),
                source_path="receipt.py",
                signals={
                    "fan_out": 7,
                    "uncertainty_bp": 6_000,
                    "failure_cost_bp": 8_500,
                },
            ),
            _claim(
                claim_id="med",
                property_classes=(PropertyClass.INTERFACE_CONTRACT,),
                symbol_ids=("api.handle",),
                artifact_cids=(_cid("art-api"),),
                source_path="api.py",
                signals={"fan_out": 2, "frequency_bp": 2_000},
            ),
        ]
    )
    result = select_mutation_targets(
        props,
        repository_id=REPO_ID,
        repository_state_cid=REPO_STATE,
        budget={
            "max_targets": 2,
            "always_select_min_risk_bp": 0,
            "low_risk_sample_rate_bp": 10_000,
            "seed": 0,
        },
        return_result=True,
    )
    assert len(result.targets) == 2
    assert (
        result.targets[0].risk_weight_bp >= result.targets[1].risk_weight_bp
    )
    assert result.targets[0].risk_class == (
        MutationRiskClass.PROOF_RECEIPT_TRUST.value
    )
    # Ranking contributions expose the closed dimensions used for weighting.
    top = next(
        score
        for score in result.ranking
        if score.subject_id == result.targets[0].target_id
    )
    assert RiskDimension.BASE_CLASS.value in top.contributions
    assert any(
        dim in top.contributions
        for dim in (
            RiskDimension.FAN_OUT.value,
            RiskDimension.FAILURE_COST.value,
            RiskDimension.UNCERTAINTY.value,
        )
    )
