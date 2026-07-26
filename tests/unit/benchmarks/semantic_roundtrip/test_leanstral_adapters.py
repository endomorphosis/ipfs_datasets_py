from __future__ import annotations

import json
from dataclasses import dataclass
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
    LeanstralCanonicalConstructor,
    LeanstralClient,
    LeanstralConstructorArm,
    LeanstralMalformedResponseError,
    LeanstralTimeoutError,
    LeanstralUnavailableError,
)
from benchmarks.semantic_roundtrip.realizers.leanstral import (
    REALIZER_MAX_TOKENS,
    LeanstralCanonicalRealizer,
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


class RecordingClient:
    endpoint = LEANSTRAL_ENDPOINT
    model = LEANSTRAL_MODEL

    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def complete_json(self, **kwargs: object) -> Any:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def constructor_request(
    source: str = (
        "The controller must delete records after 30 days unless required by law."
    ),
    config: dict[str, object] | None = None,
) -> ConstructorRequest:
    return ConstructorRequest(source, VOCABULARY, config or {})


def realizer_request(
    config: dict[str, object] | None = None,
) -> RealizerRequest:
    return RealizerRequest(IR, VOCABULARY, config or {})


def test_adapters_implement_public_protocols_and_bind_exact_identity() -> None:
    constructor = LeanstralCanonicalConstructor(RecordingClient([IR_DICT]))
    realizer = LeanstralCanonicalRealizer(
        RecordingClient([{"text": "The controller must delete records."}])
    )

    assert isinstance(constructor, RoundTripConstructor)
    assert isinstance(realizer, RoundTripRealizer)
    assert LEANSTRAL_ENDPOINT in constructor.identity
    assert LEANSTRAL_MODEL in constructor.identity
    assert LEANSTRAL_ENDPOINT in realizer.identity
    assert LEANSTRAL_MODEL in realizer.identity

    with pytest.raises(ValueError, match="exact frozen"):
        LeanstralCanonicalConstructor(
            SimpleNamespace(
                endpoint="http://elsewhere/v1",
                model=LEANSTRAL_MODEL,
            )
        )
    with pytest.raises(ValueError, match="frozen identity"):
        LeanstralClient(model="another-model")


def test_constructor_uses_fixed_schema_and_tokens_without_gold_counts() -> None:
    first = RecordingClient([IR_DICT])
    second = RecordingClient([IR_DICT])
    request_a = constructor_request(
        config={"gold_rule_count": 1, "unrelated": "a"}
    )
    request_b = constructor_request(
        config={"gold_rule_count": 99, "unrelated": "b"}
    )

    result_a = LeanstralCanonicalConstructor(first).construct(request_a)
    result_b = LeanstralCanonicalConstructor(second).construct(request_b)

    assert result_a.status is ComponentStatus.SUCCESS
    assert result_b.status is ComponentStatus.SUCCESS
    assert first.calls[0]["schema"] == second.calls[0]["schema"]
    assert first.calls[0]["max_tokens"] == CONSTRUCTOR_MAX_TOKENS
    assert second.calls[0]["max_tokens"] == CONSTRUCTOR_MAX_TOKENS
    assert first.calls[0]["prompt"] == second.calls[0]["prompt"]
    assert "gold" not in str(first.calls[0]).lower()
    schema = first.calls[0]["schema"]
    rules_schema = schema["properties"]["rules"]  # type: ignore[index]
    assert rules_schema["maxItems"] == 16


@dataclass
class FakeToken:
    text: str
    lemma_: str
    pos_: str
    dep_: str
    i: int

    @property
    def head(self) -> "FakeToken":
        return self


class FakeSpacy:
    pipe_names = (
        "tok2vec",
        "tagger",
        "parser",
        "attribute_ruler",
        "lemmatizer",
        "ner",
    )
    lang = "en"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, text: str) -> object:
        self.seen.append(text)
        tokens = [FakeToken("controller", "controller", "NOUN", "nsubj", 0)]
        return SimpleNamespace(
            __iter__=lambda self: iter(tokens),
            ents=(),
        )


class IterableDoc:
    def __init__(self) -> None:
        self.ents: tuple[object, ...] = ()
        self._tokens = [
            FakeToken("controller", "controller", "NOUN", "nsubj", 0)
        ]

    def __iter__(self):
        return iter(self._tokens)

    def has_annotation(self, name: str) -> bool:
        return name in {
            "DEP",
            "ENT_IOB",
            "LEMMA",
            "POS",
            "SENT_START",
            "TAG",
        }


class WorkingSpacy(FakeSpacy):
    def __call__(self, text: str) -> IterableDoc:
        self.seen.append(text)
        return IterableDoc()


def test_spacy_evidence_is_exposed_only_to_declared_arm() -> None:
    direct_client = RecordingClient([IR_DICT])
    evidence_client = RecordingClient([IR_DICT])
    nlp = WorkingSpacy()

    direct = LeanstralCanonicalConstructor(direct_client)
    evidence = LeanstralCanonicalConstructor(
        evidence_client,
        arm=LeanstralConstructorArm.SPACY_EVIDENCE,
        spacy_pipeline=nlp,
    )
    assert direct.construct(constructor_request()).status is ComponentStatus.SUCCESS
    assert evidence.construct(constructor_request()).status is ComponentStatus.SUCCESS

    assert "SPACY_EVIDENCE_JSON" not in direct_client.calls[0]["prompt"]
    assert "SPACY_EVIDENCE_JSON" in evidence_client.calls[0]["prompt"]
    assert nlp.seen == [constructor_request().source_text]
    with pytest.raises(ValueError, match="may not receive"):
        LeanstralCanonicalConstructor(
            RecordingClient([IR_DICT]), spacy_pipeline=nlp
        )


def test_missing_or_degraded_spacy_is_capability_failure() -> None:
    client = RecordingClient([IR_DICT])
    missing = LeanstralCanonicalConstructor(
        client, arm=LeanstralConstructorArm.SPACY_EVIDENCE
    ).construct(constructor_request())
    assert missing.status is ComponentStatus.FAILED
    assert missing.failure_reason is FailureReason.CAPABILITY_UNAVAILABLE
    assert client.calls == []

    degraded = WorkingSpacy()
    degraded.pipe_names = ("tok2vec", "parser")
    result = LeanstralCanonicalConstructor(
        client,
        arm=LeanstralConstructorArm.SPACY_EVIDENCE,
        spacy_pipeline=degraded,
    ).construct(constructor_request())
    assert result.failure_reason is FailureReason.CAPABILITY_UNAVAILABLE
    assert client.calls == []


def test_realizer_receives_only_ir_and_ignores_public_config() -> None:
    client = RecordingClient(
        [{"text": "The controller must delete records after 30 days."}]
    )
    result = LeanstralCanonicalRealizer(client).realize(
        realizer_request(config={"display_style": "source-like prose"})
    )

    assert result.status is ComponentStatus.SUCCESS
    assert result.text == "The controller must delete records after 30 days."
    call = client.calls[0]
    assert call["max_tokens"] == REALIZER_MAX_TOKENS
    assert "CANONICAL_IR_JSON" in call["prompt"]
    assert "display_style" not in call["prompt"]
    assert "source-like prose" not in call["prompt"]


def test_client_sends_one_stateless_exchange_and_disables_prompt_cache() -> None:
    captured: list[tuple[str, dict[str, object], float]] = []

    def transport(url: str, body: bytes, timeout: float) -> object:
        captured.append((url, json.loads(body), timeout))
        return {
            "model": LEANSTRAL_MODEL,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(IR_DICT)},
                }
            ],
        }

    client = LeanstralClient(transport=transport)
    result = LeanstralCanonicalConstructor(client).construct(
        constructor_request()
    )
    assert result.status is ComponentStatus.SUCCESS
    url, payload, _ = captured[0]
    assert url == LEANSTRAL_ENDPOINT + "/chat/completions"
    assert payload["model"] == LEANSTRAL_MODEL
    assert payload["cache_prompt"] is False
    assert [message["role"] for message in payload["messages"]] == [
        "system",
        "user",
    ]
    assert not hasattr(client, "cache")


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (LeanstralTimeoutError("late"), FailureReason.TIMEOUT),
        (
            LeanstralUnavailableError("offline"),
            FailureReason.CAPABILITY_UNAVAILABLE,
        ),
        (
            LeanstralMalformedResponseError("bad JSON"),
            FailureReason.INVALID_OUTPUT,
        ),
    ],
)
def test_constructor_records_terminal_failures(
    failure: BaseException, reason: FailureReason
) -> None:
    result = LeanstralCanonicalConstructor(
        RecordingClient([failure])
    ).construct(constructor_request())
    assert result.status is ComponentStatus.FAILED
    assert result.failure_reason is reason
    assert result.canonical_ir is None


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (LeanstralTimeoutError("late"), FailureReason.TIMEOUT),
        (
            LeanstralUnavailableError("offline"),
            FailureReason.CAPABILITY_UNAVAILABLE,
        ),
        (
            LeanstralMalformedResponseError("bad JSON"),
            FailureReason.INVALID_OUTPUT,
        ),
    ],
)
def test_realizer_records_terminal_failures(
    failure: BaseException, reason: FailureReason
) -> None:
    result = LeanstralCanonicalRealizer(
        RecordingClient([failure])
    ).realize(realizer_request())
    assert result.status is ComponentStatus.FAILED
    assert result.failure_reason is reason
    assert result.text is None


def test_malformed_semantics_and_empty_or_blank_outputs_are_failures() -> None:
    invalid = LeanstralCanonicalConstructor(
        RecordingClient(
            [
                {
                    "rules": [
                        {
                            **IR_DICT["rules"][0],
                            "actor": "out_of_vocabulary",
                        }
                    ]
                }
            ]
        )
    ).construct(constructor_request())
    empty = LeanstralCanonicalConstructor(
        RecordingClient([{"rules": []}])
    ).construct(constructor_request())
    extra = LeanstralCanonicalRealizer(
        RecordingClient([{"text": "ok", "source": "leak"}])
    ).realize(realizer_request())
    blank = LeanstralCanonicalRealizer(
        RecordingClient([{"text": "   "}])
    ).realize(realizer_request())

    assert invalid.failure_reason is FailureReason.INVALID_OUTPUT
    assert empty.failure_reason is FailureReason.EMPTY_L1
    assert extra.failure_reason is FailureReason.INVALID_OUTPUT
    assert blank.failure_reason is FailureReason.BLANK_T1
