"""Tests for scoreable paired autoencoder guidance."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
    RoundTripConstructor,
)
from benchmarks.semantic_roundtrip.constructors.autoencoder_guided import (
    AUTOENCODER_GUIDED_CANONICAL_CONSTRUCTOR_INTERFACE,
    COMMON_REALIZER_IDENTITIES,
    PINNED_AUTOENCODER_DECLARED_ARCHITECTURE,
    PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE,
    PINNED_AUTOENCODER_STATE_CID,
    PINNED_AUTOENCODER_STATE_SCHEMA,
    PINNED_AUTOENCODER_STATE_SHA256,
    AutoencoderCompositionStatus,
    AutoencoderGuidanceArm,
    AutoencoderGuidedCanonicalConstructor,
    CausalGuidanceApplication,
    FrozenAutoencoderGuidance,
    canonical_field_changes,
    make_autoencoder_guidance_pair,
)
from benchmarks.semantic_roundtrip.realizers.deterministic import (
    CANONICAL_DETERMINISTIC_REALIZER_INTERFACE,
)
from benchmarks.semantic_roundtrip.realizers.leanstral import (
    LEANSTRAL_CANONICAL_REALIZER_INTERFACE,
)


VOCABULARY = AllowedAtomVocabulary(
    actors=("agency", "company"),
    actions=("file", "submit"),
    objects=("notice", "report"),
    qualifiers=("emergency", "within_10_days"),
)
BASELINE_IR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="company",
            action="submit",
            object="report",
            temporal=("within_10_days",),
        ),
    )
)


class FixedConstructor:
    identity = "FixedCanonicalConstructor@1"

    def __init__(self, result: ConstructorResult | None = None) -> None:
        self.result = result or ConstructorResult(
            ComponentStatus.SUCCESS, canonical_ir=BASELINE_IR
        )
        self.requests: list[ConstructorRequest] = []

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        self.requests.append(request)
        return self.result


def request(config: dict[str, object] | None = None) -> ConstructorRequest:
    return ConstructorRequest(
        "The company shall submit the report within 10 days.",
        VOCABULARY,
        config or {},
    )


def frozen_guidance(
    *,
    stable_export: dict[str, object] | None = None,
) -> FrozenAutoencoderGuidance:
    return FrozenAutoencoderGuidance(
        state_cid=PINNED_AUTOENCODER_STATE_CID,
        state_sha256=PINNED_AUTOENCODER_STATE_SHA256,
        state_schema=PINNED_AUTOENCODER_STATE_SCHEMA,
        declared_architecture=(
            PINNED_AUTOENCODER_DECLARED_ARCHITECTURE
        ),
        effective_architecture=(
            PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE
        ),
        stable_export=stable_export
        or {
            "export_id": "stable-export-1",
            "sample_memory_included": False,
            "stable_features": [
                {
                    "feature": "semantic-slot:exception-present",
                    "feature_group": "semantic_slot",
                    "stable": True,
                }
            ],
            "excluded_categories": [
                "sample_memory",
                "decoded_embeddings",
            ],
        },
    )


def test_paired_arms_share_base_state_pin_and_common_realizers() -> None:
    base = FixedConstructor()
    loader_calls: list[Path] = []

    def loader(path: Path) -> FrozenAutoencoderGuidance:
        loader_calls.append(path)
        return frozen_guidance()

    pair = make_autoencoder_guidance_pair(
        base,
        guidance_applicator=lambda ir, vocabulary, guidance: ir,
        guidance_loader=loader,
    )

    assert pair.guidance.arm is AutoencoderGuidanceArm.GUIDANCE
    assert pair.no_guidance.arm is AutoencoderGuidanceArm.NO_GUIDANCE
    assert pair.guidance.base_constructor is pair.no_guidance.base_constructor
    assert pair.common_realizer_identities == (
        CANONICAL_DETERMINISTIC_REALIZER_INTERFACE,
        LEANSTRAL_CANONICAL_REALIZER_INTERFACE,
    )
    assert pair.common_realizer_identities == COMMON_REALIZER_IDENTITIES
    assert pair.guidance.compatible_realizer_identities == (
        pair.no_guidance.compatible_realizer_identities
    )
    assert PINNED_AUTOENCODER_STATE_CID in pair.guidance.identity
    assert PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE in pair.guidance.identity
    assert pair.guidance.identity.startswith(
        AUTOENCODER_GUIDED_CANONICAL_CONSTRUCTOR_INTERFACE
    )
    assert isinstance(pair.guidance, RoundTripConstructor)
    assert loader_calls == []


def test_no_guidance_arm_returns_exact_baseline_without_loading_state() -> None:
    base = FixedConstructor()
    calls: list[str] = []
    constructor = AutoencoderGuidedCanonicalConstructor(
        base,
        arm=AutoencoderGuidanceArm.NO_GUIDANCE,
        guidance_applicator=lambda *_: calls.append(  # type: ignore[arg-type]
            "applicator"
        ),
        guidance_loader=lambda path: (_ for _ in ()).throw(
            AssertionError("state must not be loaded")
        ),
    )

    construction = constructor.construct_with_diagnostics(request())

    assert construction.result.canonical_ir is BASELINE_IR
    assert construction.diagnostics.composition_status is (
        AutoencoderCompositionStatus.NO_GUIDANCE
    )
    assert construction.diagnostics.changed_fields == ()
    assert construction.diagnostics.field_changes == ()
    assert construction.diagnostics.sample_memory_used is False
    assert (
        construction.diagnostics.target_embedding_selection_used is False
    )
    assert calls == []


def test_guidance_arm_records_exact_canonical_field_changes() -> None:
    base = FixedConstructor()
    seen: dict[str, object] = {}

    def apply_guidance(
        baseline: CanonicalRuleIR,
        vocabulary: AllowedAtomVocabulary,
        guidance: FrozenAutoencoderGuidance,
    ) -> CanonicalRuleIR:
        seen.update(
            {
                "baseline": baseline,
                "vocabulary": vocabulary,
                "guidance": guidance,
            }
        )
        rule = baseline.rules[0]
        return CanonicalRuleIR(
            (
                replace(
                    rule,
                    modality="F",
                    exceptions=("emergency",),
                ),
            )
        )

    constructor = AutoencoderGuidedCanonicalConstructor(
        base,
        guidance_applicator=apply_guidance,
        guidance_loader=lambda path: frozen_guidance(),
    )
    construction = constructor.construct_with_diagnostics(request())

    assert construction.result.status is ComponentStatus.SUCCESS
    assert construction.result.canonical_ir is not None
    assert construction.result.canonical_ir.rules[0].modality == "F"
    assert construction.diagnostics.composition_status is (
        AutoencoderCompositionStatus.APPLIED
    )
    assert construction.diagnostics.composition_supported is True
    assert construction.diagnostics.canonical_l1_changed is True
    assert construction.diagnostics.changed_fields == (
        "modality",
        "exceptions",
    )
    assert [
        (change.canonical_field, change.before, change.after)
        for change in construction.diagnostics.field_changes
    ] == [
        ("modality", "O", "F"),
        ("exceptions", [], ["emergency"]),
    ]
    assert construction.diagnostics.guidance_export_id == "stable-export-1"
    assert seen["baseline"] is BASELINE_IR
    assert seen["vocabulary"] is VOCABULARY
    assert isinstance(seen["guidance"], FrozenAutoencoderGuidance)
    assert set(construction.attribution_receipt["changed_fields"]) == {
        "modality",
        "exceptions",
    }


def test_default_guidance_arm_reports_unsupported_causal_composition() -> None:
    constructor = AutoencoderGuidedCanonicalConstructor(FixedConstructor())

    construction = constructor.construct_with_diagnostics(request())

    assert construction.result.status is ComponentStatus.FAILED
    assert construction.result.failure_reason is (
        FailureReason.CAPABILITY_UNAVAILABLE
    )
    assert "unsupported composition" in (
        construction.result.failure_detail or ""
    )
    assert construction.diagnostics.composition_status is (
        AutoencoderCompositionStatus.UNSUPPORTED
    )
    assert construction.diagnostics.composition_supported is False
    assert construction.diagnostics.changed_fields == ()


def test_applicator_can_explicitly_report_unsupported_composition() -> None:
    constructor = AutoencoderGuidedCanonicalConstructor(
        FixedConstructor(),
        guidance_applicator=lambda baseline, vocabulary, guidance: (
            CausalGuidanceApplication.unsupported(
                "stable features are annotations only"
            )
        ),
        guidance_loader=lambda path: frozen_guidance(),
    )

    construction = constructor.construct_with_diagnostics(request())

    assert construction.result.failure_reason is (
        FailureReason.CAPABILITY_UNAVAILABLE
    )
    assert construction.diagnostics.composition_status is (
        AutoencoderCompositionStatus.UNSUPPORTED
    )
    assert "annotations only" in (
        construction.result.failure_detail or ""
    )


@pytest.mark.parametrize(
    "config",
    [
        {"use_sample_memory": False},
        {"selection": {"targetEmbedding": "candidate-vector"}},
        {"selection_mode": "target_embedding"},
        {"target_vector": [0.1, 0.2]},
    ],
)
def test_sample_memory_and_target_embedding_config_are_forbidden(
    config: dict[str, object],
) -> None:
    base = FixedConstructor()
    constructor = AutoencoderGuidedCanonicalConstructor(
        base,
        arm=AutoencoderGuidanceArm.NO_GUIDANCE,
    )

    construction = constructor.construct_with_diagnostics(request(config))

    assert construction.result.failure_reason is FailureReason.INVALID_OUTPUT
    assert "forbidden" in (construction.result.failure_detail or "")
    assert base.requests == []


@pytest.mark.parametrize(
    "unsafe_export",
    [
        {
            "export_id": "bad",
            "sample_memory_included": True,
        },
        {
            "export_id": "bad",
            "decoded_embeddings": {"case": [1.0]},
            "sample_memory_included": False,
        },
        {
            "export_id": "bad",
            "targetEmbedding": [1.0],
            "sample_memory_included": False,
        },
    ],
)
def test_sanitized_guidance_boundary_rejects_memory_and_targets(
    unsafe_export: dict[str, object],
) -> None:
    with pytest.raises(ContractError):
        frozen_guidance(stable_export=unsafe_export)


def test_guided_output_must_remain_nonempty_and_in_vocabulary() -> None:
    outside = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="intruder",
                action="submit",
                object="report",
            ),
        )
    )
    invalid = AutoencoderGuidedCanonicalConstructor(
        FixedConstructor(),
        guidance_applicator=lambda baseline, vocabulary, guidance: outside,
        guidance_loader=lambda path: frozen_guidance(),
    ).construct_with_diagnostics(request())
    empty = AutoencoderGuidedCanonicalConstructor(
        FixedConstructor(),
        guidance_applicator=lambda baseline, vocabulary, guidance: (
            CanonicalRuleIR(())
        ),
        guidance_loader=lambda path: frozen_guidance(),
    ).construct_with_diagnostics(request())

    assert invalid.result.failure_reason is FailureReason.INVALID_OUTPUT
    assert empty.result.failure_reason is FailureReason.EMPTY_L1


def test_base_failure_is_preserved_and_guidance_is_not_loaded() -> None:
    failed = ConstructorResult(
        ComponentStatus.FAILED,
        failure_reason=FailureReason.EMPTY_L1,
        failure_detail="baseline empty",
    )
    constructor = AutoencoderGuidedCanonicalConstructor(
        FixedConstructor(failed),
        guidance_applicator=lambda baseline, vocabulary, guidance: baseline,
        guidance_loader=lambda path: (_ for _ in ()).throw(
            AssertionError("guidance must not load after base failure")
        ),
    )

    construction = constructor.construct_with_diagnostics(request())

    assert construction.result is failed
    assert construction.diagnostics.composition_status is (
        AutoencoderCompositionStatus.FAILED
    )


def test_state_identity_failure_is_an_explicit_capability_outcome() -> None:
    def unavailable(path: Path) -> FrozenAutoencoderGuidance:
        raise ContractError("state CID differs from the pin")

    construction = AutoencoderGuidedCanonicalConstructor(
        FixedConstructor(),
        guidance_applicator=lambda baseline, vocabulary, guidance: baseline,
        guidance_loader=unavailable,
    ).construct_with_diagnostics(request())

    assert construction.result.failure_reason is (
        FailureReason.CAPABILITY_UNAVAILABLE
    )
    assert "guidance unavailable" in (
        construction.result.failure_detail or ""
    )
    assert construction.diagnostics.field_changes == ()


def test_rule_additions_and_removals_record_every_canonical_field() -> None:
    empty = CanonicalRuleIR(())

    additions = canonical_field_changes(empty, BASELINE_IR)
    removals = canonical_field_changes(BASELINE_IR, empty)

    assert [change.canonical_field for change in additions] == [
        "modality",
        "actor",
        "action",
        "object",
        "conditions",
        "exceptions",
        "temporal",
    ]
    assert all(change.before is None for change in additions)
    assert all(change.after is None for change in removals)
