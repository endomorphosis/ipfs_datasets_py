"""Contract tests for the canonical semantic round-trip core."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

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
    RoundTripConstructor,
    RoundTripRealizer,
    RoundTripResult,
    compare_semantic_ir,
    make_round_trip_result,
    maximum_weight_assignment,
    round_trip_losses,
)


def _vocabulary() -> AllowedAtomVocabulary:
    return AllowedAtomVocabulary(
        actors=("agency", "court"),
        actions=("file", "review"),
        objects=("notice", "order"),
        qualifiers=("emergency", "within_10_days"),
    )


def _rule(**changes: object) -> CanonicalRule:
    values: dict[str, object] = {
        "modality": "O",
        "actor": "agency",
        "action": "file",
        "object": "notice",
        "conditions": (),
        "exceptions": ("emergency",),
        "temporal": ("within_10_days",),
    }
    values.update(changes)
    return CanonicalRule(**values)


def _ir(*rules: CanonicalRule) -> CanonicalRuleIR:
    return CanonicalRuleIR(tuple(rules or (_rule(),)))


def test_canonical_ir_is_deeply_immutable_and_canonically_serialized() -> None:
    ir = CanonicalRuleIR(
        (
            _rule(
                conditions=(" within_10_days ", "within_10_days"),
                exceptions=("emergency",),
            ),
        )
    )

    assert ir.rules[0].conditions == ("within_10_days",)
    assert ir.to_dict() == {
        "rules": [
            {
                "modality": "O",
                "actor": "agency",
                "action": "file",
                "object": "notice",
                "conditions": ["within_10_days"],
                "exceptions": ["emergency"],
                "temporal": ["within_10_days"],
            }
        ]
    }
    with pytest.raises(FrozenInstanceError):
        ir.rules = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ir.rules[0].actor = "court"  # type: ignore[misc]


def test_canonical_ir_enforces_exact_schema_bounds_and_vocabulary() -> None:
    rule = _rule().to_dict()
    with pytest.raises(ContractError, match="exactly"):
        CanonicalRule.from_dict({**rule, "native_payload": {}})
    with pytest.raises(ContractError, match="item bound"):
        CanonicalRule.from_dict(
            {**rule, "conditions": [f"q{index}" for index in range(9)]}
        )
    with pytest.raises(ContractError, match="outside"):
        CanonicalRuleIR((_rule(actor="invented"),)).validate_vocabulary(
            _vocabulary()
        )
    with pytest.raises(ContractError, match="string array"):
        AllowedAtomVocabulary.from_dict(
            {**_vocabulary().to_dict(), "actors": "agency"}
        )


def test_requests_freeze_configuration_and_protocols_are_crossable() -> None:
    config = {"decode": {"temperature": 0}, "stops": ["END"]}
    constructor_request = ConstructorRequest(
        "Agency shall file notice.", _vocabulary(), config
    )
    config["decode"]["temperature"] = 1  # type: ignore[index]

    assert (
        constructor_request.config["decode"]["temperature"] == 0  # type: ignore[index]
    )
    with pytest.raises(TypeError):
        constructor_request.config["new"] = True  # type: ignore[index]

    class Constructor:
        identity = "constructor@1"

        def construct(self, request: ConstructorRequest) -> ConstructorResult:
            return ConstructorResult(ComponentStatus.SUCCESS, _ir())

    class Realizer:
        identity = "realizer@1"

        def realize(self, request: RealizerRequest) -> RealizerResult:
            return RealizerResult(
                ComponentStatus.SUCCESS, "Agency shall file notice."
            )

    assert isinstance(Constructor(), RoundTripConstructor)
    assert isinstance(Realizer(), RoundTripRealizer)


@pytest.mark.parametrize("forbidden", ["source_text", "native_payload"])
def test_realizer_boundary_rejects_source_and_native_fields(
    forbidden: str,
) -> None:
    payload = {
        "canonical_ir": _ir().to_dict(),
        "allowed_atom_vocabulary": _vocabulary().to_dict(),
        "config": {},
        forbidden: "must not cross",
    }

    with pytest.raises(ContractError, match="forbidden"):
        RealizerRequest.from_payload(payload)


def test_realizer_boundary_rejects_nested_leakage_and_undeclared_fields() -> None:
    with pytest.raises(ContractError, match="native_record"):
        RealizerRequest(_ir(), _vocabulary(), {"native_record": {"x": 1}})
    with pytest.raises(ContractError, match="sourceText"):
        RealizerRequest(_ir(), _vocabulary(), {"decode": {"sourceText": "x"}})
    with pytest.raises(ContractError, match="native-record"):
        RealizerRequest(_ir(), _vocabulary(), {"decode": {"native-record": {}}})
    with pytest.raises(ContractError, match="undeclared"):
        RealizerRequest.from_payload(
            {
                "canonical_ir": _ir().to_dict(),
                "allowed_atom_vocabulary": _vocabulary().to_dict(),
                "config": {},
                "diagnostics": {},
            }
        )


def test_terminal_component_results_enforce_typed_consistent_states() -> None:
    with pytest.raises(ContractError, match="nonempty"):
        ConstructorResult(ComponentStatus.SUCCESS, CanonicalRuleIR(()))
    with pytest.raises(ContractError, match="canonical_ir"):
        ConstructorResult(
            ComponentStatus.SUCCESS,
            _ir().to_dict(),  # type: ignore[arg-type]
        )
    with pytest.raises(ContractError, match="failure information"):
        RealizerResult(
            ComponentStatus.SUCCESS,
            "Agency shall file notice.",
            failure_detail="not a successful state",
        )
    with pytest.raises(ContractError, match="failure reason"):
        RealizerResult(
            ComponentStatus.FAILED,
            failure_reason="timeout",  # type: ignore[arg-type]
        )


def test_weighted_exact_assignment_score_matches_existing_pilot() -> None:
    exact = compare_semantic_ir(_ir(), _ir())
    changed = compare_semantic_ir(
        _ir(),
        _ir(_rule(modality="P", exceptions=(), temporal=())),
    )

    assert exact["semantic_score"] == 1.0
    assert exact["semantic_loss"] == 0.0
    # actor + action + object + conditions survive:
    # .15 + .20 + .10 + .10 = .55
    assert changed["semantic_score"] == 0.55
    assert changed["semantic_loss"] == 0.45


def test_maximum_weight_assignment_avoids_greedy_local_optimum() -> None:
    assignment = maximum_weight_assignment(
        [[0.90, 0.80], [0.85, 0.0]]
    )

    assert assignment == [(0, 1), (1, 0)]
    assert sum(
        [[0.90, 0.80], [0.85, 0.0]][row][column]
        for row, column in assignment
    ) == pytest.approx(1.65)


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf"), "x"])
def test_maximum_weight_assignment_rejects_nonfinite_weights(
    invalid: object,
) -> None:
    with pytest.raises(ContractError, match=r"\[0\]\[1\].*finite"):
        maximum_weight_assignment([[1.0, invalid]])  # type: ignore[list-item]


def test_forward_cycle_and_end_to_end_losses_remain_distinct() -> None:
    gold = _ir(_rule())
    wrong = _ir(_rule(modality="P"))
    losses = round_trip_losses(
        gold,
        wrong,
        "The agency may file the notice.",
        wrong,
    )

    assert losses.forward == 0.25
    assert losses.cycle == 0.0
    assert losses.end_to_end == 0.25
    assert losses.primary == losses.end_to_end


@pytest.mark.parametrize(
    ("l1", "text", "l2", "failed"),
    [
        (None, "text", _ir(), False),
        (_ir(), None, _ir(), False),
        (_ir(), "   ", _ir(), False),
        (CanonicalRuleIR(()), "text", _ir(), False),
        (_ir(), "text", CanonicalRuleIR(()), False),
        (_ir(), "text", _ir(), True),
    ],
)
def test_failures_missing_and_empty_results_assign_all_losses_one(
    l1: CanonicalRuleIR | None,
    text: str | None,
    l2: CanonicalRuleIR | None,
    failed: bool,
) -> None:
    losses = round_trip_losses(_ir(), l1, text, l2, failed=failed)

    assert losses.forward == 1.0
    assert losses.cycle == 1.0
    assert losses.end_to_end == 1.0


def test_round_trip_result_binds_primary_loss_and_failure_policy() -> None:
    success = make_round_trip_result(
        _ir(), _ir(), "Agency shall file notice.", _ir()
    )
    failure = make_round_trip_result(
        _ir(),
        _ir(),
        None,
        None,
        failure_reason=FailureReason.TIMEOUT,
        failure_detail="bounded call timed out",
    )

    assert success.is_complete
    assert success.primary_loss == 0.0
    assert failure.status is ComponentStatus.FAILED
    assert failure.primary_loss == 1.0
    assert not failure.is_complete

    inferred_empty = make_round_trip_result(
        _ir(), CanonicalRuleIR(()), "text", _ir()
    )
    assert inferred_empty.status is ComponentStatus.FAILED
    assert inferred_empty.failure_reason is FailureReason.EMPTY_L1


def test_round_trip_result_rejects_internally_inconsistent_states() -> None:
    with pytest.raises(ContractError, match="must be failed"):
        RoundTripResult(
            status=ComponentStatus.SUCCESS,
            l1=None,
            reconstruction=None,
            l2=None,
            forward_loss=1.0,
            cycle_loss=1.0,
            end_to_end_loss=1.0,
        )
