"""Contract tests for the eight-cell semantic round-trip matrix."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    FailureReason,
    RealizerRequest,
    RealizerResult,
)
from benchmarks.semantic_roundtrip.matrix import (
    EXPECTED_CELL_IDS,
    MATRIX_CONSTRUCTOR_IDS,
    MATRIX_REALIZER_IDS,
    MatrixCase,
    SemanticRoundTripMatrix,
    polarity_diagnostics,
    source_copy_diagnostics,
)


VOCABULARY = AllowedAtomVocabulary(
    actors=("agency",),
    actions=("file",),
    objects=("notice",),
    qualifiers=("under_policy",),
)
O_IR = CanonicalRuleIR(
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
F_IR = CanonicalRuleIR(
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


class RecordingConstructor:
    def __init__(self, identity: str) -> None:
        self.identity = identity
        self.requests: list[ConstructorRequest] = []

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        self.requests.append(request)
        if "scheduled failure" in request.source_text:
            return ConstructorResult(
                ComponentStatus.FAILED,
                failure_reason=FailureReason.CAPABILITY_UNAVAILABLE,
                failure_detail="fixture-requested unavailable capability",
            )
        ir = F_IR if "inverted" in request.source_text else O_IR
        return ConstructorResult(ComponentStatus.SUCCESS, canonical_ir=ir)


class RecordingRealizer:
    def __init__(self, identity: str, text: str) -> None:
        self.identity = identity
        self.text = text
        self.requests: list[RealizerRequest] = []

    def realize(self, request: RealizerRequest) -> RealizerResult:
        self.requests.append(request)
        return RealizerResult(ComponentStatus.SUCCESS, text=self.text)


def _case(case_id: str = "case-1", source: str | None = None) -> MatrixCase:
    return MatrixCase(
        case_id=case_id,
        source_text=source
        or "Under policy, the agency shall file a notice for public review.",
        allowed_atom_vocabulary=VOCABULARY,
        gold_ir=O_IR,
    )


def _components() -> tuple[
    dict[str, RecordingConstructor], dict[str, RecordingRealizer]
]:
    constructors = {
        constructor_id: RecordingConstructor(f"{constructor_id}@1")
        for constructor_id in MATRIX_CONSTRUCTOR_IDS
    }
    realizers = {
        "deterministic": RecordingRealizer(
            "deterministic@1",
            "The agency shall file notice under policy.",
        ),
        "leanstral": RecordingRealizer(
            "leanstral@1",
            "The agency shall not file notice under policy; inverted.",
        ),
    }
    return constructors, realizers


def test_runs_all_eight_cells_with_one_identical_l1_fanout() -> None:
    constructors, realizers = _components()
    validator_calls: list[tuple[str, CanonicalRuleIR, CanonicalRuleIR]] = []

    def validator(
        left: CanonicalRuleIR,
        right: CanonicalRuleIR,
        request_id: str,
    ) -> Mapping[str, object]:
        validator_calls.append((request_id, left, right))
        return {
            "status": "success",
            "equivalent": left == right,
            "nonvacuous": not left.is_empty and not right.is_empty,
        }

    matrix = SemanticRoundTripMatrix(
        constructors,
        realizers,
        constructor_configs={
            constructor_id: {"temperature": 0}
            for constructor_id in MATRIX_CONSTRUCTOR_IDS
        },
        validators={"hammer_cvc5": validator, "lean": validator},
    )
    case_record = matrix.run_case(_case())

    assert len(case_record.coordinates) == 8
    assert tuple(
        coordinate.cell_id for coordinate in case_record.coordinates
    ) == EXPECTED_CELL_IDS
    assert len(validator_calls) == 16
    assert all(
        coordinate.validation["phase"]
        == "post_hoc_after_candidate_binding"
        for coordinate in case_record.coordinates
    )
    assert all(
        coordinate.validation["candidate_unchanged"] is True
        for coordinate in case_record.coordinates
    )

    for constructor in constructors.values():
        # T0 is constructed once and the same implementation is applied once
        # to each of the two independent T1 values.
        assert len(constructor.requests) == 3
        assert sum(
            request.source_text == _case().source_text
            for request in constructor.requests
        ) == 1
        assert all(
            request.to_payload()["config"] == {"temperature": 0}
            for request in constructor.requests
        )

    for realizer in realizers.values():
        assert len(realizer.requests) == 4
        assert all(request.canonical_ir == O_IR for request in realizer.requests)
        assert all(
            set(request.to_payload())
            == {"canonical_ir", "allowed_atom_vocabulary", "config"}
            for request in realizer.requests
        )

    for constructor_id in MATRIX_CONSTRUCTOR_IDS:
        fanout = [
            coordinate
            for coordinate in case_record.coordinates
            if coordinate.constructor_id == constructor_id
        ]
        assert len({coordinate.l1_cid for coordinate in fanout}) == 1
        assert all(
            coordinate.diagnostics["l1_payload_cid"]
            == coordinate.l1_cid
            for coordinate in fanout
        )


def test_failures_remain_in_denominators_and_receive_loss_one() -> None:
    constructors, realizers = _components()
    matrix = SemanticRoundTripMatrix(
        constructors,
        realizers,
        validators={},
    )
    result = matrix.run(
        (
            _case(),
            _case("failure", "scheduled failure for this case"),
        )
    )

    assert len(result.cases) == 2
    assert all(len(case.coordinates) == 8 for case in result.cases)
    assert all(
        coordinate.status is ComponentStatus.FAILED
        and coordinate.result.forward_loss == 1.0
        and coordinate.result.cycle_loss == 1.0
        and coordinate.result.end_to_end_loss == 1.0
        for coordinate in result.cases[1].coordinates
    )
    for summary in result.summaries.values():
        assert summary["scheduled_case_count"] == 2
        assert summary["success_count"] == 1
        assert summary["failure_count"] == 1
        assert (
            summary["denominator_policy"]
            == "all_scheduled_cases_including_failures"
        )

    deterministic = result.summaries["typed_deontic__deterministic"]
    leanstral = result.summaries["typed_deontic__leanstral"]
    assert deterministic["mean_end_to_end_loss"] == 0.5
    assert leanstral["mean_end_to_end_loss"] == 0.625


def test_copy_and_polarity_diagnostics_are_fail_closed() -> None:
    copied = source_copy_diagnostics(
        "Agencies shall maintain records within ten days after final approval.",
        "Agency shall maintain record within ten days after final approval.",
    )
    assert copied["exact_normalized_copy"] is True
    assert copied["copy_risk"] is True
    assert copied["gate_passed"] is False

    short = source_copy_diagnostics(
        "The agency shall file a notice.",
        "Agency files notice.",
    )
    assert short["shared_8gram_precision"] == 0.0
    assert short["gate_passed"] is True

    preserved = polarity_diagnostics(O_IR, O_IR)
    inverted = polarity_diagnostics(O_IR, F_IR)
    missing = polarity_diagnostics(O_IR, None)
    assert preserved["gate_passed"] is True
    assert inverted["inversion_count"] == 1
    assert inverted["gate_passed"] is False
    assert missing["evaluated"] is False
    assert missing["gate_passed"] is False


def test_records_are_cid_addressed_at_coordinate_case_and_run_levels() -> None:
    constructors, realizers = _components()
    result = SemanticRoundTripMatrix(
        constructors,
        realizers,
        validators={},
    ).run((_case(),))
    case_record = result.cases[0]

    assert (
        validate_cid(result.run_cid, codecs=("dag-json",)) == result.run_cid
    )
    assert (
        validate_cid(case_record.record_cid, codecs=("dag-json",))
        == case_record.record_cid
    )
    for coordinate in case_record.coordinates:
        assert (
            validate_cid(coordinate.candidate_cid, codecs=("dag-json",))
            == coordinate.candidate_cid
        )
        assert (
            validate_cid(coordinate.record_cid, codecs=("dag-json",))
            == coordinate.record_cid
        )
        serialized = coordinate.to_dict()
        record_cid = serialized.pop("record_cid")
        assert cid_for_dag_json(serialized) == record_cid

    case_serialized = case_record.to_dict()
    case_cid = case_serialized.pop("record_cid")
    assert cid_for_dag_json(case_serialized) == case_cid
    run_serialized = result.to_dict()
    run_cid = run_serialized.pop("run_cid")
    assert cid_for_dag_json(run_serialized) == run_cid


def test_second_constructor_empty_output_is_reported_as_empty_l2() -> None:
    class EmptySecondConstructor(RecordingConstructor):
        def construct(self, request: ConstructorRequest) -> ConstructorResult:
            self.requests.append(request)
            if len(self.requests) == 1:
                return ConstructorResult(
                    ComponentStatus.SUCCESS, canonical_ir=O_IR
                )
            return ConstructorResult(
                ComponentStatus.FAILED,
                failure_reason=FailureReason.EMPTY_L1,
                failure_detail="adapter calls all empty output L1",
            )

    constructor = EmptySecondConstructor("empty-second@1")
    realizer = RecordingRealizer(
        "realizer@1", "Agency shall file notice under policy."
    )
    matrix = SemanticRoundTripMatrix(
        {"one": constructor},
        {"one": realizer},
        validators={},
        require_eight_cells=False,
    )
    coordinate = matrix.run_case(_case()).coordinates[0]

    assert coordinate.status is ComponentStatus.FAILED
    assert coordinate.result.failure_reason is FailureReason.EMPTY_L2
    assert coordinate.result.l1 == O_IR
    assert coordinate.result.reconstruction == realizer.text
    assert coordinate.result.l2 is None
    assert coordinate.primary_loss == 1.0


@pytest.mark.parametrize(
    ("constructors", "realizers", "message"),
    [
        ({"wrong": RecordingConstructor("c@1")}, {}, "nonempty"),
        (
            {"wrong": RecordingConstructor("c@1")},
            {"wrong": RecordingRealizer("r@1", "text")},
            "four frozen arms",
        ),
    ],
)
def test_registry_shape_is_frozen(
    constructors: dict[str, RecordingConstructor],
    realizers: dict[str, RecordingRealizer],
    message: str,
) -> None:
    with pytest.raises(Exception, match=message):
        SemanticRoundTripMatrix(
            constructors,
            realizers,
            validators={},
        )
