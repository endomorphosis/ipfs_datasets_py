"""Adversarial source-withholding tests for calibration realizers."""

from __future__ import annotations

import builtins

import pytest

from benchmarks.semantic_roundtrip import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ContractError,
)
from benchmarks.semantic_roundtrip.calibration import RealizerLeakageGuard
from benchmarks.semantic_roundtrip.realizers.deterministic import (
    CanonicalDeterministicRealizer,
)


VOCABULARY = AllowedAtomVocabulary(
    actors=("agency", "court"),
    actions=("file", "review"),
    objects=("notice",),
    qualifiers=("under_policy",),
)
IR = CanonicalRuleIR(
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


def _payload() -> dict[str, object]:
    return {
        "canonical_ir": IR.to_dict(),
        "allowed_atom_vocabulary": VOCABULARY.to_dict(),
        "config": {},
    }


@pytest.mark.parametrize(
    "forbidden",
    (
        "source_text",
        "sourceExcerpt",
        "t0",
        "gold_ir",
        "goldRuleCount",
        "nativeRecord",
        "parse_tree",
        "constructorPayload",
        "hiddenCaseFields",
        "priorReconstruction",
        "validatorOutput",
    ),
)
def test_guard_rejects_top_level_source_native_gold_and_hidden_channels(
    forbidden: str,
) -> None:
    with pytest.raises(ContractError, match="forbidden"):
        RealizerLeakageGuard.request_from_payload(
            {**_payload(), forbidden: "secret"}
        )


@pytest.mark.parametrize(
    "config",
    (
        {"nested": {"sourceCacheKey": "cid"}},
        {"nested": {"nativeCompilerRecord": {"rule": 1}}},
        {"nested": {"goldContent": "answer"}},
        {"originatingConstructor": "typed"},
        {"prior_reconstruction": "selected answer"},
        {"observedSemanticOutcome": 0.0},
    ),
)
def test_guard_rejects_nested_and_camel_case_hidden_channels(
    config: dict[str, object],
) -> None:
    with pytest.raises(ContractError, match="may not contain"):
        RealizerLeakageGuard.request_from_payload(
            {**_payload(), "config": config}
        )


@pytest.mark.parametrize(
    "budget_input",
    (
        "gold_ir",
        "goldRuleCount",
        "gold-content",
        "validator_output",
        "observedSemanticOutcome",
    ),
)
def test_gold_derived_budget_inputs_fail_closed(budget_input: str) -> None:
    with pytest.raises(ContractError, match="gold-derived budgets"):
        RealizerLeakageGuard.build_request(
            IR,
            VOCABULARY,
            {"max_tokens": 100},
            budget_inputs=(budget_input,),
        )


def test_budget_provenance_cannot_be_smuggled_inside_public_config() -> None:
    with pytest.raises(ContractError, match="gold-derived budgets"):
        RealizerLeakageGuard.build_request(
            IR,
            VOCABULARY,
            {
                "max_tokens": 100,
                "budget_provenance": ["fixed_manifest", "gold_rule_count"],
            },
        )

    request = RealizerLeakageGuard.build_request(
        IR,
        VOCABULARY,
        {"max_tokens": 100, "budget_source": "fixed_manifest"},
        budget_inputs=("frozen_manifest",),
    )
    assert request.config["max_tokens"] == 100


def test_request_is_detached_and_contains_only_the_public_wire_contract() -> None:
    config: dict[str, object] = {
        "decode": {"temperature": 0, "max_tokens": 100}
    }
    request = RealizerLeakageGuard.build_request(IR, VOCABULARY, config)
    config["decode"]["temperature"] = 99  # type: ignore[index]

    assert set(request.to_payload()) == {
        "canonical_ir",
        "allowed_atom_vocabulary",
        "config",
    }
    assert request.config["decode"]["temperature"] == 0  # type: ignore[index]
    assert "source" not in str(request.to_payload()).lower()
    assert "native" not in str(request.to_payload()).lower()
    assert "gold" not in str(request.to_payload()).lower()


def test_deterministic_realizer_never_observes_an_originating_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingOrigin:
        @property
        def identity(self) -> str:
            raise AssertionError("originating constructor was observed")

        @property
        def native_record(self) -> object:
            raise AssertionError("native record was observed")

        @property
        def source_text(self) -> str:
            raise AssertionError("source text was observed")

    # Merely keep a hostile origin object alive in the caller.  The leakage
    # guard has no parameter for it, and the deterministic realizer has no
    # constructor import, slot, cache, callback, or file lookup.
    origin = ExplodingOrigin()

    def forbidden_open(*args: object, **kwargs: object) -> object:
        raise AssertionError("deterministic realizer attempted file access")

    monkeypatch.setattr(builtins, "open", forbidden_open)
    request = RealizerLeakageGuard.build_request(
        IR,
        VOCABULARY,
        {"decode": {"temperature": 0}},
    )
    result = RealizerLeakageGuard.invoke(
        CanonicalDeterministicRealizer(), request
    )

    assert origin is not None
    assert result.status is ComponentStatus.SUCCESS
    assert result.text == "Agency shall file notice if under policy."


def test_deterministic_output_depends_on_ir_not_constructor_ancestry() -> None:
    first = RealizerLeakageGuard.build_request(
        IR, VOCABULARY, {"arm_label": "first"}
    )
    second = RealizerLeakageGuard.build_request(
        IR, VOCABULARY, {"arm_label": "second"}
    )
    realizer = CanonicalDeterministicRealizer()

    assert realizer.realize(first) == realizer.realize(second)
