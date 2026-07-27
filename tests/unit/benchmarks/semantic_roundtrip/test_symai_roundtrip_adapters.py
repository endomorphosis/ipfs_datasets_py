from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from benchmarks.semantic_roundtrip import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    FailureReason,
    RealizerRequest,
    RoundTripConstructor,
    RoundTripRealizer,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    CONSTRUCTOR_MAX_TOKENS,
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    LEANSTRAL_TIMEOUT_SECONDS,
    LeanstralTimeoutError,
)
from benchmarks.semantic_roundtrip.constructors.symai import (
    SYMAI_CACHE_ENABLED,
    SYMAI_MAX_RETRIES,
    SYMAI_SEED,
    SYMAI_STOP,
    SYMAI_TEMPERATURE,
    SyMAICanonicalConstructor,
    SyMAIClient,
    SyMAICompletion,
    SyMAIGenerationSettings,
)
from benchmarks.semantic_roundtrip.realizers.leanstral import (
    REALIZER_MAX_TOKENS,
)
from benchmarks.semantic_roundtrip.realizers.symai import (
    SyMAICanonicalRealizer,
)
from benchmarks.semantic_roundtrip_capabilities import (
    LEANSTRAL_BACKEND,
    LEANSTRAL_PROVIDER,
)


VOCABULARY = AllowedAtomVocabulary(
    actors=("controller", "processor"),
    actions=("delete", "retain"),
    objects=("records",),
    qualifiers=("after_30_days", "unless_required_by_law"),
)
IR_DICT = {
    "rules": [
        {
            "modality": "O",
            "actor": "controller",
            "action": "delete",
            "object": "records",
            "conditions": [],
            "exceptions": ["unless_required_by_law"],
            "temporal": ["after_30_days"],
        }
    ]
}
IR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="controller",
            action="delete",
            object="records",
            exceptions=("unless_required_by_law",),
            temporal=("after_30_days",),
        ),
    )
)
ROUTE_METADATA = {
    "resolved_provider_name": LEANSTRAL_PROVIDER,
    "resolved_model_name": LEANSTRAL_MODEL,
    "service_endpoint": LEANSTRAL_ENDPOINT,
    "routing_backend": LEANSTRAL_BACKEND,
    "attempts": 1,
    "retries": 0,
    "cache_enabled": False,
    "cache_hit": False,
}


class RecordingClient:
    endpoint = LEANSTRAL_ENDPOINT
    model = LEANSTRAL_MODEL

    def __init__(
        self,
        responses: list[object],
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.responses = responses
        self.metadata = metadata or ROUTE_METADATA
        self.calls: list[dict[str, object]] = []

    def complete_json(self, **kwargs: object) -> Any:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return SyMAICompletion(response, self.metadata)  # type: ignore[arg-type]


def constructor_request(
    source: str = "A private original sentence.",
) -> ConstructorRequest:
    return ConstructorRequest(source, VOCABULARY, {"public_label": "case-a"})


def realizer_request(
    config: dict[str, object] | None = None,
) -> RealizerRequest:
    return RealizerRequest(IR, VOCABULARY, config or {})


def test_adapters_are_protocol_components_bound_to_one_shared_model() -> None:
    constructor = SyMAICanonicalConstructor(RecordingClient([IR_DICT]))
    realizer = SyMAICanonicalRealizer(
        RecordingClient([{"text": "The controller must delete records."}])
    )

    assert isinstance(constructor, RoundTripConstructor)
    assert isinstance(realizer, RoundTripRealizer)
    for component in (constructor, realizer):
        assert LEANSTRAL_ENDPOINT in component.identity
        assert LEANSTRAL_MODEL in component.identity
        assert "symai_router" in component.identity
        assert "independent_model=false" in component.identity

    with pytest.raises(ValueError, match="exact frozen"):
        SyMAICanonicalConstructor(
            SimpleNamespace(
                endpoint="http://elsewhere/v1",
                model=LEANSTRAL_MODEL,
            )
        )


def test_generation_settings_match_direct_leanstral_per_role() -> None:
    constructor_client = RecordingClient([IR_DICT])
    realizer_client = RecordingClient([{"text": "Controller must delete."}])

    assert (
        SyMAICanonicalConstructor(constructor_client).construct(
            constructor_request()
        ).status
        is ComponentStatus.SUCCESS
    )
    assert (
        SyMAICanonicalRealizer(realizer_client).realize(realizer_request()).status
        is ComponentStatus.SUCCESS
    )

    assert constructor_client.calls[0]["max_tokens"] == CONSTRUCTOR_MAX_TOKENS
    assert realizer_client.calls[0]["max_tokens"] == REALIZER_MAX_TOKENS
    for maximum in (CONSTRUCTOR_MAX_TOKENS, REALIZER_MAX_TOKENS):
        settings = SyMAIGenerationSettings.for_role(maximum)
        assert settings.endpoint == LEANSTRAL_ENDPOINT
        assert settings.model == LEANSTRAL_MODEL
        assert settings.temperature == SYMAI_TEMPERATURE == 0
        assert settings.seed == SYMAI_SEED == 0
        assert settings.stop == SYMAI_STOP == ("<|im_end|>",)
        assert settings.timeout_seconds == LEANSTRAL_TIMEOUT_SECONDS
        assert settings.cache_prompt is False
    assert SYMAI_MAX_RETRIES == 0
    assert SYMAI_CACHE_ENABLED is False


def test_symai_constructor_returns_exact_canonical_rules_for_l1_and_l2() -> None:
    client = RecordingClient([IR_DICT, IR_DICT])
    constructor = SyMAICanonicalConstructor(client)

    l1 = constructor.construct(constructor_request())
    l2 = constructor.construct(
        constructor_request(
            "The controller must delete records after thirty days."
        )
    )

    assert l1.canonical_ir == IR
    assert l2.canonical_ir == IR
    assert constructor.round_trip_contract == {
        "l1": "canonical_rules",
        "l2": "canonical_rules",
        "same_constructor_required": True,
        "coarse_forward_only_rankable": False,
        "comparison_scope": "incremental_symai_orchestration_only",
    }
    assert len(client.calls) == 2


def test_realizer_is_source_withheld_and_does_not_serialize_public_config() -> None:
    client = RecordingClient(
        [{"text": "The controller must delete records after 30 days."}]
    )
    realizer = SyMAICanonicalRealizer(client)
    source_marker = "PRIVATE_SOURCE_MUST_NEVER_REACH_REVERSE"
    result = realizer.realize(
        realizer_request(
            {
                "display_style": "plain",
                "unrelated_marker": source_marker,
            }
        )
    )

    assert result.status is ComponentStatus.SUCCESS
    call = client.calls[0]
    assert "CANONICAL_IR_JSON" in str(call["prompt"])
    assert source_marker not in str(call)
    assert "display_style" not in str(call)
    assert realizer.round_trip_contract["source_withheld"] is True


def test_receipt_reports_route_retry_cache_and_incremental_attribution() -> None:
    constructor = SyMAICanonicalConstructor(RecordingClient([IR_DICT]))
    result = constructor.construct(constructor_request())

    assert result.status is ComponentStatus.SUCCESS
    receipt = constructor.last_receipt
    assert receipt is not None
    value = receipt.to_dict()
    assert value["routing"]["resolved_endpoint"] == LEANSTRAL_ENDPOINT
    assert value["routing"]["resolved_model"] == LEANSTRAL_MODEL
    assert value["retry"] == {
        "policy": "none",
        "attempts": 1,
        "retries": 0,
    }
    assert value["cache"] == {"enabled": False, "hit": False}
    assert value["attribution"] == {
        "independent_model_evidence": False,
        "comparison_scope": "incremental_symai_orchestration_only",
    }
    assert value["canonical_contract_validated"] is True
    assert value["ranking_eligible"] is True


@pytest.mark.parametrize(
    "metadata",
    [
        {**ROUTE_METADATA, "resolved_model_name": "another-model"},
        {**ROUTE_METADATA, "service_endpoint": "http://elsewhere/v1"},
        {**ROUTE_METADATA, "retries": 1, "attempts": 2},
        {**ROUTE_METADATA, "cache_hit": True},
        {**ROUTE_METADATA, "temperature": 0.7},
        {**ROUTE_METADATA, "independent_model": True},
    ],
)
def test_route_or_retry_or_cache_drift_is_a_capability_failure(
    metadata: dict[str, object],
) -> None:
    result = SyMAICanonicalConstructor(
        RecordingClient([IR_DICT], metadata=metadata)
    ).construct(constructor_request())

    assert result.status is ComponentStatus.FAILED
    assert result.failure_reason is FailureReason.CAPABILITY_UNAVAILABLE
    assert result.canonical_ir is None


def test_coarse_forward_only_response_is_excluded_from_ranking() -> None:
    coarse = {
        "candidate_ir": {"summary": "controller deletion duty"},
        "entities": ["controller", "records"],
        "confidence": 0.99,
    }
    constructor = SyMAICanonicalConstructor(RecordingClient([coarse]))

    result = constructor.construct(constructor_request())

    assert result.status is ComponentStatus.FAILED
    assert result.failure_reason is FailureReason.INVALID_OUTPUT
    receipt = constructor.last_receipt
    assert receipt is not None
    assert receipt.canonical_contract_validated is False
    assert receipt.ranking_eligible is False
    assert (
        receipt.ranking_exclusion_reason
        == "coarse_or_noncanonical_forward_response"
    )


def test_default_client_forwards_the_frozen_settings_to_symai_router() -> None:
    captured: dict[str, object] = {}

    def invoke(**kwargs: object) -> object:
        captured.update(kwargs)
        return IR_DICT, ROUTE_METADATA

    client = SyMAIClient(invoker=invoke)
    result = SyMAICanonicalConstructor(client).construct(constructor_request())

    assert result.status is ComponentStatus.SUCCESS
    settings = captured["settings"]
    assert isinstance(settings, SyMAIGenerationSettings)
    assert settings.to_dict() == {
        "endpoint": LEANSTRAL_ENDPOINT,
        "model": LEANSTRAL_MODEL,
        "temperature": 0,
        "seed": 0,
        "max_tokens": CONSTRUCTOR_MAX_TOKENS,
        "stop": ["<|im_end|>"],
        "timeout_seconds": LEANSTRAL_TIMEOUT_SECONDS,
        "cache_prompt": False,
    }
    assert captured["route"] == "symai_router"


def test_reverse_contract_and_terminal_failures_are_fail_closed() -> None:
    extra = SyMAICanonicalRealizer(
        RecordingClient([{"text": "ok", "source": "leak"}])
    ).realize(realizer_request())
    blank = SyMAICanonicalRealizer(
        RecordingClient([{"text": "   "}])
    ).realize(realizer_request())
    timeout = SyMAICanonicalRealizer(
        RecordingClient([LeanstralTimeoutError("late")])
    ).realize(realizer_request())

    assert extra.failure_reason is FailureReason.INVALID_OUTPUT
    assert blank.failure_reason is FailureReason.BLANK_T1
    assert timeout.failure_reason is FailureReason.TIMEOUT
    assert extra.text is blank.text is timeout.text is None
