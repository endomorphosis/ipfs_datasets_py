"""Regression contract for the deterministic source-withheld paraphraser."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.semantic_roundtrip import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ContractError,
    FailureReason,
    RealizerRequest,
    RoundTripRealizer,
)
from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
    TypedDeonticCanonicalConstructor,
)
from benchmarks.semantic_roundtrip.matrix import (
    polarity_diagnostics,
    source_copy_diagnostics,
)
from benchmarks.semantic_roundtrip.metrics import compare_semantic_ir
from benchmarks.semantic_roundtrip.realizers.deterministic import (
    CanonicalDeterministicRealizer,
)
from benchmarks.semantic_roundtrip.realizers.source_withheld_paraphrase import (
    FROZEN_REPLACEMENT_CONFIG,
    FROZEN_REPLACEMENT_CONFIG_CID,
    SOURCE_WITHHELD_CANONICAL_PARAPHRASER_INTERFACE,
    SOURCE_WITHHELD_PARAPHRASE_ATTRIBUTION_INTERFACE,
    SOURCE_WITHHELD_PARAPHRASE_ATTRIBUTION_SCHEMA,
    SOURCE_WITHHELD_PARAPHRASE_RENDERING_SPEC_CID,
    SourceWithheldCanonicalParaphraser,
    frozen_replacement_config,
    paraphrase_rule,
)


ROOT = Path(__file__).resolve().parents[4]
PILOT_CASES = json.loads(
    (
        ROOT / "tests/fixtures/semantic_roundtrip/pilot_cases.json"
    ).read_text(encoding="utf-8")
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
        config=(
            frozen_replacement_config()
            if config is None
            else config
        ),
    )


def _case(case_id: str) -> dict[str, object]:
    return next(case for case in PILOT_CASES if case["id"] == case_id)


def test_frozen_profile_renders_distinct_polarities_and_every_facet() -> None:
    rules = (
        CanonicalRule(
            modality="O",
            actor="company_a",
            action="file",
            object="annual_report",
            conditions=("public_interest", "required_by_law"),
            exceptions=("emergency",),
            temporal=("after_approval", "within_10_days"),
        ),
        CanonicalRule(
            modality="P",
            actor="court",
            action="review",
            object="notice",
        ),
        CanonicalRule(
            modality="F",
            actor="agency",
            action="inspect",
            object="records",
        ),
    )

    result = SourceWithheldCanonicalParaphraser().realize(_request(*rules))

    assert result.status is ComponentStatus.SUCCESS
    assert result.text == (
        "Agency must not inspect records. "
        "Company a must file annual report after approval and within 10 days "
        "if public interest and required by law unless emergency. "
        "Court may review notice."
    )
    assert "Agency must inspect" not in result.text
    assert " shall " not in result.text
    assert paraphrase_rule(
        CanonicalRule(
            modality="P",
            actor="court",
            action="review",
            object="",
            temporal=("after_approval",),
        )
    ) == "Court may review after approval."


def test_exception_with_window_must_regression_reparses_exactly() -> None:
    case = _case("exception_with_window")
    vocabulary = AllowedAtomVocabulary.from_dict(case["allowed_atoms"])
    gold = CanonicalRuleIR.from_dict(case["gold_ir"], vocabulary)
    constructor = TypedDeonticCanonicalConstructor()
    l1_result = constructor.construct(
        ConstructorRequest(case["source_text"], vocabulary, {})
    )
    assert l1_result.status is ComponentStatus.SUCCESS
    assert l1_result.canonical_ir == gold
    assert l1_result.canonical_ir is not None

    old = CanonicalDeterministicRealizer().realize(
        RealizerRequest(l1_result.canonical_ir, vocabulary, {})
    )
    result = SourceWithheldCanonicalParaphraser().realize(
        RealizerRequest(
            l1_result.canonical_ir,
            vocabulary,
            frozen_replacement_config(),
        )
    )

    assert old.text == (
        "Company a shall submit backup report within 10 days unless emergency."
    )
    assert result.text == (
        "Company a must submit backup report within 10 days unless emergency."
    )
    assert source_copy_diagnostics(
        case["source_text"], old.text
    )["shared_8gram_precision"] == 1.0
    repaired_copy = source_copy_diagnostics(case["source_text"], result.text)
    assert repaired_copy["exact_normalized_copy"] is False
    assert repaired_copy["shared_8gram_precision"] == 0.25
    assert repaired_copy["gate_passed"] is True

    l2_result = constructor.construct(
        ConstructorRequest(result.text, vocabulary, {})
    )
    assert l2_result.status is ComponentStatus.SUCCESS
    assert l2_result.canonical_ir == gold
    assert polarity_diagnostics(gold, l2_result.canonical_ir)[
        "gate_passed"
    ] is True


def test_five_case_typed_constructor_round_trip_matches_frozen_baseline() -> None:
    constructor = TypedDeonticCanonicalConstructor()
    realizer = SourceWithheldCanonicalParaphraser()
    overlap_precisions: list[float] = []
    primary_losses: list[float] = []

    for case in PILOT_CASES:
        vocabulary = AllowedAtomVocabulary.from_dict(case["allowed_atoms"])
        gold = CanonicalRuleIR.from_dict(case["gold_ir"], vocabulary)
        l1_result = constructor.construct(
            ConstructorRequest(case["source_text"], vocabulary, {})
        )
        assert l1_result.status is ComponentStatus.SUCCESS, case["id"]
        assert l1_result.canonical_ir is not None, case["id"]
        assert not l1_result.canonical_ir.is_empty, case["id"]

        t1_result = realizer.realize(
            RealizerRequest(
                l1_result.canonical_ir,
                vocabulary,
                frozen_replacement_config(),
            )
        )
        assert t1_result.status is ComponentStatus.SUCCESS, case["id"]
        assert t1_result.text is not None and t1_result.text.strip(), case["id"]

        l2_result = constructor.construct(
            ConstructorRequest(t1_result.text, vocabulary, {})
        )
        assert l2_result.status is ComponentStatus.SUCCESS, case["id"]
        assert l2_result.canonical_ir is not None, case["id"]
        assert not l2_result.canonical_ir.is_empty, case["id"]

        copy = source_copy_diagnostics(case["source_text"], t1_result.text)
        polarity = polarity_diagnostics(gold, l2_result.canonical_ir)
        assert copy["exact_normalized_copy"] is False, case["id"]
        assert copy["gate_passed"] is True, case["id"]
        assert polarity["gate_passed"] is True, case["id"]
        overlap_precisions.append(
            round(float(copy["shared_8gram_precision"]), 3)
        )
        primary_losses.append(
            float(
                compare_semantic_ir(
                    gold, l2_result.canonical_ir
                )["semantic_loss"]
            )
        )

    # PLAT-082 improved typed_deontic projection; shared-8gram and cycle losses
    # move with the stronger L1. Keep the sealed plateau mean as a ceiling.
    assert overlap_precisions == [0.25, 0.045, 0.118, 0.051, 0.038]
    assert primary_losses == [0.0, 0.083333333, 0.0, 0.025, 0.0]
    mean_primary = sum(primary_losses) / len(primary_losses)
    assert mean_primary <= 0.0883333334 + 1e-9
    assert mean_primary == pytest.approx(0.0216666666, abs=1e-9)


def test_exact_copy_and_eight_token_overlap_negative_controls_pass() -> None:
    rule = CanonicalRule(
        modality="O",
        actor="agency",
        action="publish",
        object="annual_report",
        temporal=("within_10_days",),
    )
    result = SourceWithheldCanonicalParaphraser().realize(_request(rule))
    assert result.text == "Agency must publish annual report within 10 days."

    exact_control = source_copy_diagnostics(
        "Agency shall publish annual report within 10 days.",
        result.text,
    )
    overlap_control = source_copy_diagnostics(
        (
            "The agency shall publish annual report within 10 days after "
            "approval."
        ),
        result.text,
    )
    assert exact_control["exact_normalized_copy"] is False
    assert exact_control["gate_passed"] is True
    assert overlap_control["shared_8gram_precision"] < 0.8
    assert overlap_control["gate_passed"] is True


def test_accepts_only_the_exact_frozen_replacement_configuration() -> None:
    realizer = SourceWithheldCanonicalParaphraser()
    rule = CanonicalRule(
        modality="O",
        actor="agency",
        action="file",
        object="notice",
    )
    detached = frozen_replacement_config()
    detached["obligation_surface"] = "shall"

    altered = realizer.realize(_request(rule, config=detached))
    empty = realizer.realize(_request(rule, config={}))

    for result in (altered, empty):
        assert result.status is ComponentStatus.FAILED
        assert result.failure_reason is FailureReason.INVALID_OUTPUT
        assert result.text is None
        assert FROZEN_REPLACEMENT_CONFIG_CID in result.failure_detail
    with pytest.raises(TypeError):
        FROZEN_REPLACEMENT_CONFIG["profile"] = "mutable"  # type: ignore[index]
    assert frozen_replacement_config() == dict(FROZEN_REPLACEMENT_CONFIG)
    assert FROZEN_REPLACEMENT_CONFIG_CID == cid_for_dag_json(
        frozen_replacement_config()
    )


@pytest.mark.parametrize(
    "forbidden",
    (
        "source_text",
        "t0",
        "gold_ir",
        "native_record",
        "source_bearing_cache",
        "hidden_case_fields",
    ),
)
def test_public_boundary_forbids_noncanonical_channels(
    forbidden: str,
) -> None:
    payload = _request(
        CanonicalRule(
            modality="O",
            actor="agency",
            action="file",
            object="notice",
        )
    ).to_payload()
    with pytest.raises(ContractError):
        RealizerRequest.from_payload({**payload, forbidden: "secret"})


def test_hidden_config_and_non_request_inputs_fail_closed() -> None:
    rule = CanonicalRule(
        modality="F",
        actor="agency",
        action="publish",
        object="records",
    )
    hidden = frozen_replacement_config()
    hidden["case_id"] = "hidden-case-key"
    realizer = SourceWithheldCanonicalParaphraser()

    result = realizer.realize(_request(rule, config=hidden))
    malformed = realizer.realize(  # type: ignore[arg-type]
        {"canonical_ir": _request(rule).canonical_ir.to_dict()}
    )

    assert result.status is ComponentStatus.FAILED
    assert result.failure_reason is FailureReason.INVALID_OUTPUT
    assert malformed.status is ComponentStatus.FAILED
    assert malformed.failure_reason is FailureReason.INVALID_OUTPUT
    with pytest.raises(ContractError, match="sourceCacheKey"):
        RealizerRequest(
            _request(rule).canonical_ir,
            _vocabulary(),
            {
                **frozen_replacement_config(),
                "nested": {"sourceCacheKey": "forbidden"},
            },
        )


def test_empty_l1_is_a_bounded_typed_failure() -> None:
    result = SourceWithheldCanonicalParaphraser().realize(_request())

    assert result.status is ComponentStatus.FAILED
    assert result.text is None
    assert result.failure_reason is FailureReason.EMPTY_L1
    assert result.failure_detail == "canonical IR contains no rules"
    with pytest.raises(ContractError, match="rule must be CanonicalRule"):
        paraphrase_rule({"modality": "O"})  # type: ignore[arg-type]


def test_cid_attribution_binds_only_public_inputs_and_t1() -> None:
    request = _request(
        CanonicalRule(
            modality="P",
            actor="court",
            action="review",
            object="notice",
            conditions=("public_interest",),
        )
    )
    result, receipt = (
        SourceWithheldCanonicalParaphraser().realize_with_receipt(request)
    )

    assert result.status is ComponentStatus.SUCCESS
    assert result.text == "Court may review notice if public interest."
    assert receipt is not None
    assert set(receipt) == {
        "interface",
        "schema_version",
        "realizer_identity",
        "rendering_spec_cid",
        "deterministic",
        "source_withheld",
        "observed_input_fields",
        "excluded_input_channels",
        "input_attribution",
        "output_attribution",
        "receipt_cid",
    }
    assert receipt["interface"] == (
        SOURCE_WITHHELD_PARAPHRASE_ATTRIBUTION_INTERFACE
    )
    assert receipt["schema_version"] == (
        SOURCE_WITHHELD_PARAPHRASE_ATTRIBUTION_SCHEMA
    )
    assert receipt["realizer_identity"] == (
        SOURCE_WITHHELD_CANONICAL_PARAPHRASER_INTERFACE
    )
    assert receipt["rendering_spec_cid"] == (
        SOURCE_WITHHELD_PARAPHRASE_RENDERING_SPEC_CID
    )
    assert receipt["source_withheld"] is True
    assert receipt["observed_input_fields"] == [
        "canonical_ir",
        "allowed_atom_vocabulary",
        "config",
    ]
    assert receipt["input_attribution"] == {
        "canonical_l1_cid": cid_for_dag_json(
            request.canonical_ir.to_dict()
        ),
        "public_closed_vocabulary_cid": cid_for_dag_json(
            request.allowed_atom_vocabulary.to_dict()
        ),
        "frozen_replacement_config_cid": FROZEN_REPLACEMENT_CONFIG_CID,
        "public_request_cid": cid_for_dag_json(request.to_payload()),
    }
    assert receipt["output_attribution"] == {
        "t1_cid": cid_for_bytes(result.text.encode("utf-8")),
        "character_count": len(result.text),
    }
    body = dict(receipt)
    receipt_cid = body.pop("receipt_cid")
    assert receipt_cid == cid_for_dag_json(body)
    assert "a source sentence that must never appear" not in json.dumps(
        receipt, sort_keys=True
    )


def test_realizer_is_stateless_and_performs_no_source_or_cache_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        CanonicalRule(
            modality="F",
            actor="agency",
            action="publish",
            object="records",
            conditions=("public_interest",),
        )
    )

    def forbidden_open(*args: object, **kwargs: object) -> object:
        raise AssertionError("paraphraser attempted a source-bearing lookup")

    monkeypatch.setattr(builtins, "open", forbidden_open)
    first = SourceWithheldCanonicalParaphraser().realize(request)
    second = SourceWithheldCanonicalParaphraser().realize(request)

    assert first == second
    assert first.text == (
        "Agency must not publish records if public interest."
    )
    realizer = SourceWithheldCanonicalParaphraser()
    assert realizer.identity == (
        SOURCE_WITHHELD_CANONICAL_PARAPHRASER_INTERFACE
    )
    assert isinstance(realizer, RoundTripRealizer)
    with pytest.raises(AttributeError):
        realizer.source_text = "unavailable"  # type: ignore[attr-defined]
