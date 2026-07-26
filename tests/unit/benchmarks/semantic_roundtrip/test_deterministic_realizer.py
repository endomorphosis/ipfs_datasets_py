"""Tests for the common source-withheld deterministic realizer."""

from __future__ import annotations

import builtins

import pytest

from benchmarks.semantic_roundtrip import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ContractError,
    FailureReason,
    RealizerRequest,
    RoundTripRealizer,
)
from benchmarks.semantic_roundtrip.realizers.deterministic import (
    CANONICAL_DETERMINISTIC_REALIZER_INTERFACE,
    CanonicalDeterministicRealizer,
    realize_rule,
)


def _vocabulary() -> AllowedAtomVocabulary:
    return AllowedAtomVocabulary(
        actors=("agency", "company_a", "court"),
        actions=("file", "inspect", "publish", "review"),
        objects=("annual_report", "notice", "records"),
        qualifiers=(
            "after_approval",
            "emergency",
            "public_interest",
            "required_by_law",
            "within_10_days",
        ),
    )


def _request(
    *rules: CanonicalRule,
    config: dict[str, object] | None = None,
) -> RealizerRequest:
    return RealizerRequest(
        canonical_ir=CanonicalRuleIR(tuple(rules)),
        allowed_atom_vocabulary=_vocabulary(),
        config=config or {},
    )


def test_realizes_every_canonical_facet_from_ir() -> None:
    request = _request(
        CanonicalRule(
            modality="O",
            actor="company_a",
            action="file",
            object="annual_report",
            conditions=("public_interest", "required_by_law"),
            exceptions=("emergency",),
            temporal=("after_approval", "within_10_days"),
        )
    )

    result = CanonicalDeterministicRealizer().realize(request)

    assert result.status is ComponentStatus.SUCCESS
    assert result.text == (
        "Company a shall file annual report after approval and within 10 days "
        "if public interest and required by law unless emergency."
    )


@pytest.mark.parametrize(
    ("modality", "modal_phrase"),
    [
        ("O", "shall"),
        ("P", "may"),
        ("F", "shall not"),
    ],
)
def test_preserves_modality_polarity(
    modality: str,
    modal_phrase: str,
) -> None:
    result = CanonicalDeterministicRealizer().realize(
        _request(
            CanonicalRule(
                modality=modality,
                actor="agency",
                action="publish",
                object="notice",
            )
        )
    )

    assert result.text == f"Agency {modal_phrase} publish notice."
    if modality == "F":
        assert "shall publish" not in result.text


def test_optional_empty_object_does_not_add_placeholder_text() -> None:
    rule = CanonicalRule(
        modality="P",
        actor="court",
        action="review",
        object="",
        temporal=("after_approval",),
    )

    assert realize_rule(rule) == "Court may review after approval."


def test_canonical_order_and_configuration_cannot_change_output() -> None:
    first = CanonicalRule(
        modality="F",
        actor="agency",
        action="inspect",
        object="records",
        exceptions=("required_by_law", "emergency"),
    )
    second = CanonicalRule(
        modality="P",
        actor="court",
        action="review",
        object="notice",
    )
    realizer = CanonicalDeterministicRealizer()

    plain = realizer.realize(_request(second, first))
    distracted = realizer.realize(
        _request(
            first,
            second,
            config={
                "unscored_context": "TOP SECRET SOURCE SENTENCE",
                "decode": {"temperature": 99, "seed": 123},
            },
        )
    )

    assert plain == distracted
    assert plain.text == (
        "Agency shall not inspect records unless emergency or required by law. "
        "Court may review notice."
    )
    assert "TOP SECRET" not in plain.text


def test_empty_ir_is_a_typed_loss_one_path_not_blank_success() -> None:
    result = CanonicalDeterministicRealizer().realize(_request())

    assert result.status is ComponentStatus.FAILED
    assert result.text is None
    assert result.failure_reason is FailureReason.EMPTY_L1
    assert result.failure_detail == "canonical IR contains no rules"


def test_adapter_has_frozen_identity_and_crosses_realizer_protocol() -> None:
    realizer = CanonicalDeterministicRealizer()

    assert realizer.identity == "CanonicalDeterministicRealizer@1"
    assert realizer.identity == CANONICAL_DETERMINISTIC_REALIZER_INTERFACE
    assert isinstance(realizer, RoundTripRealizer)
    with pytest.raises(AttributeError):
        realizer.source_text = "unavailable"  # type: ignore[attr-defined]


def test_source_and_native_records_cannot_cross_adapter_boundary() -> None:
    payload = _request(
        CanonicalRule(
            modality="O",
            actor="agency",
            action="file",
            object="notice",
        )
    ).to_payload()

    for forbidden in ("source_text", "gold_ir", "native_record"):
        with pytest.raises(ContractError, match="forbidden"):
            RealizerRequest.from_payload({**payload, forbidden: "secret"})
    with pytest.raises(ContractError, match="nativeRecord"):
        RealizerRequest.from_payload(
            {
                **payload,
                "config": {"nested": {"nativeRecord": "secret"}},
            }
        )


def test_realization_performs_no_file_or_native_record_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        CanonicalRule(
            modality="F",
            actor="agency",
            action="publish",
            object="records",
            conditions=("public_interest",),
        ),
        config={"case_id": "a-cache-key-that-must-not-be-read"},
    )

    def forbidden_open(*args: object, **kwargs: object) -> object:
        raise AssertionError("the deterministic realizer attempted file access")

    monkeypatch.setattr(builtins, "open", forbidden_open)
    result = CanonicalDeterministicRealizer().realize(request)

    assert result.status is ComponentStatus.SUCCESS
    assert result.text == (
        "Agency shall not publish records if public interest."
    )
    assert "cache" not in result.text


def test_rejects_objects_outside_the_public_contract() -> None:
    result = CanonicalDeterministicRealizer().realize(  # type: ignore[arg-type]
        {"canonical_ir": {"rules": []}}
    )

    assert result.status is ComponentStatus.FAILED
    assert result.failure_reason is FailureReason.INVALID_OUTPUT
    assert result.failure_detail == "request must be RealizerRequest"
    with pytest.raises(ContractError, match="rule must be CanonicalRule"):
        realize_rule({"modality": "O"})  # type: ignore[arg-type]
