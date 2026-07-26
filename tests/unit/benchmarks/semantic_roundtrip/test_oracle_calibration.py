"""Tests for diagnostic-only oracle reverse-stage calibration."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from benchmarks.semantic_roundtrip import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
)
from benchmarks.semantic_roundtrip.calibration import (
    COMMON_REALIZER_IDS,
    NON_RANKING_REASON,
    ORACLE_REVERSE_CALIBRATION_INTERFACE,
    TYPED_RECOMPILER_IDENTITY,
    OracleCalibrationCase,
    OracleReverseCalibration,
    detect_vacuous_empty_identity,
    nonvacuous_exact_identity,
    run_oracle_reverse_calibration,
)


VOCABULARY = AllowedAtomVocabulary(
    actors=("agency",),
    actions=("file",),
    objects=("notice",),
    qualifiers=("under_policy",),
)
GOLD_IR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="agency",
            action="file",
            object="notice",
            conditions=("under_policy",),
        ),
    )
)
INVERTED_IR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="F",
            actor="agency",
            action="file",
            object="notice",
            conditions=("under_policy",),
        ),
    )
)


class RecordingRealizer:
    def __init__(
        self,
        identity: str,
        result: RealizerResult,
    ) -> None:
        self._identity = identity
        self.result = result
        self.requests: list[RealizerRequest] = []

    @property
    def identity(self) -> str:
        return self._identity

    def realize(self, request: RealizerRequest) -> RealizerResult:
        self.requests.append(request)
        return self.result


class RecordingTypedRecompiler:
    identity = TYPED_RECOMPILER_IDENTITY

    def __init__(
        self,
        outputs: Mapping[str, ConstructorResult],
    ) -> None:
        self.outputs = dict(outputs)
        self.requests: list[ConstructorRequest] = []

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        self.requests.append(request)
        return self.outputs[request.source_text]


def _case(case_id: str = "case-one") -> OracleCalibrationCase:
    return OracleCalibrationCase(case_id, VOCABULARY, GOLD_IR)


def _realizers() -> dict[str, RecordingRealizer]:
    return {
        "deterministic": RecordingRealizer(
            "deterministic@recording",
            RealizerResult(
                ComponentStatus.SUCCESS,
                text="Agency shall file notice under policy.",
            ),
        ),
        "leanstral": RecordingRealizer(
            "leanstral@recording",
            RealizerResult(
                ComponentStatus.SUCCESS,
                text="Agency shall not file notice under policy.",
            ),
        ),
    }


def _recompiler() -> RecordingTypedRecompiler:
    return RecordingTypedRecompiler(
        {
            "Agency shall file notice under policy.": ConstructorResult(
                ComponentStatus.SUCCESS,
                canonical_ir=GOLD_IR,
            ),
            "Agency shall not file notice under policy.": ConstructorResult(
                ComponentStatus.SUCCESS,
                canonical_ir=INVERTED_IR,
            ),
        }
    )


def test_gold_ir_is_measured_through_both_realizers_and_one_typed_recompiler(
) -> None:
    realizers = _realizers()
    recompiler = _recompiler()

    receipt = run_oracle_reverse_calibration(
        (_case(),),
        realizers,
        typed_recompiler=recompiler,
    )

    assert [record.realizer_id for record in receipt.records] == list(
        COMMON_REALIZER_IDS
    )
    assert [record.reverse_loss for record in receipt.records] == [0.0, 0.25]
    assert all(
        record.recompiler_identity == TYPED_RECOMPILER_IDENTITY
        for record in receipt.records
    )
    assert len(recompiler.requests) == 2
    assert all(request.config == {} for request in recompiler.requests)
    for realizer in realizers.values():
        assert len(realizer.requests) == 1
        request = realizer.requests[0]
        assert request.canonical_ir == GOLD_IR
        assert set(request.to_payload()) == {
            "canonical_ir",
            "allowed_atom_vocabulary",
            "config",
        }
        assert "gold" not in str(request.to_payload()).lower()


def test_oracle_arms_and_summaries_are_permanently_non_ranking() -> None:
    receipt = OracleReverseCalibration(
        _realizers(),
        typed_recompiler=_recompiler(),
    ).run((_case(),))
    serialized = receipt.to_dict()

    assert receipt.ranking_eligible is False
    assert receipt.rankable_arm_ids == ()
    assert serialized["interface"] == ORACLE_REVERSE_CALIBRATION_INTERFACE
    assert serialized["ranking"] == {
        "eligible": False,
        "rankable_arm_ids": [],
        "reason": NON_RANKING_REASON,
    }
    for record in receipt.records:
        assert record.non_ranking
        assert record.primary_loss is None
        assert record.to_dict()["ranking"]["eligible"] is False
    for summary in receipt.summaries.values():
        assert summary["ranking_eligible"] is False
        assert summary["selection_effect"] == "none"


def test_realizer_or_recompiler_failures_receive_loss_one_and_stay_in_mean(
) -> None:
    failed_realizer = RecordingRealizer(
        "deterministic@failed",
        RealizerResult(
            ComponentStatus.FAILED,
            failure_reason=FailureReason.TIMEOUT,
            failure_detail="bounded timeout",
        ),
    )
    working_realizer = RecordingRealizer(
        "leanstral@working",
        RealizerResult(ComponentStatus.SUCCESS, text="unparseable output"),
    )
    recompiler = RecordingTypedRecompiler(
        {
            "unparseable output": ConstructorResult(
                ComponentStatus.FAILED,
                failure_reason=FailureReason.EMPTY_L1,
                failure_detail="no typed rules",
            )
        }
    )

    receipt = OracleReverseCalibration(
        {
            "deterministic": failed_realizer,
            "leanstral": working_realizer,
        },
        typed_recompiler=recompiler,
    ).run((_case(),))

    first, second = receipt.records
    assert first.failure_reason is FailureReason.TIMEOUT
    assert second.failure_reason is FailureReason.EMPTY_L2
    assert all(record.reverse_loss == 1.0 for record in receipt.records)
    assert receipt.summaries["deterministic"]["mean_reverse_loss"] == 1.0
    assert receipt.summaries["leanstral"]["mean_reverse_loss"] == 1.0
    assert all(
        summary["denominator_policy"]
        == "all_scheduled_cases_including_failures"
        for summary in receipt.summaries.values()
    )


def test_empty_identity_is_explicitly_vacuous_and_cannot_be_a_case() -> None:
    empty = CanonicalRuleIR(())

    assert detect_vacuous_empty_identity(empty, empty)
    assert not nonvacuous_exact_identity(empty, empty)
    assert nonvacuous_exact_identity(GOLD_IR, GOLD_IR)
    with pytest.raises(ContractError, match="vacuous"):
        OracleCalibrationCase("empty", VOCABULARY, empty)


def test_calibration_requires_the_frozen_realizer_set_and_typed_recompiler(
) -> None:
    class WrongConstructor(RecordingTypedRecompiler):
        identity = "OriginatingCandidateConstructor@1"

    with pytest.raises(ContractError, match="deterministic and leanstral"):
        OracleReverseCalibration(
            {"deterministic": _realizers()["deterministic"]},
            typed_recompiler=_recompiler(),
        )
    with pytest.raises(ContractError, match="fixed typed deontic"):
        OracleReverseCalibration(
            _realizers(),
            typed_recompiler=WrongConstructor({}),
        )


def test_source_bearing_case_payload_is_rejected() -> None:
    with pytest.raises(ContractError, match="source/native"):
        OracleCalibrationCase.from_dict(
            {
                "case_id": "leaky",
                "source_text": "Agency shall file notice.",
                "allowed_atom_vocabulary": VOCABULARY.to_dict(),
                "gold_ir": GOLD_IR.to_dict(),
            }
        )
