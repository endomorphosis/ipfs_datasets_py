"""Qualification tests for causal autoencoder guidance."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
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
    PINNED_AUTOENCODER_DECLARED_ARCHITECTURE,
    PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE,
    PINNED_AUTOENCODER_STATE_CID,
    PINNED_AUTOENCODER_STATE_SCHEMA,
    PINNED_AUTOENCODER_STATE_SHA256,
    FrozenAutoencoderGuidance,
)
from benchmarks.semantic_roundtrip.constructors.causal_autoencoder_guidance import (
    CAUSAL_AUTOENCODER_GUIDANCE_INTERFACE,
    CAUSAL_GUIDANCE_QUALIFICATION_INTERFACE,
    CAUSAL_MATRIX_PLANNER_INTERFACE,
    DEFAULT_QUALIFICATION_PATH,
    EVALUATION_STATUS_NOT_MEASURED,
    MATRIX_SCHEDULE_POLICY,
    MISSING_CAUSAL_CONTRACT_FIELDS,
    SCORED_SUPPORTED,
    SEMANTIC_SCHEDULE_EXCLUDED,
    TERMINAL_UNSUPPORTED,
    UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER,
    CausalAdapterOutput,
    CausalAutoencoderGuidance,
    CausalFeatureAttribution,
    CausalQualificationStatus,
    FeatureToCanonicalFieldIntervention,
    ReviewedCausalL1Contract,
    StableExportEvidence,
    build_causal_guidance_qualification,
    filter_semantic_schedule_candidates,
    guided_scored_support_from_qualification,
    load_causal_guidance_qualification,
    plan_guided_semantic_schedule,
    validate_causal_guidance_qualification,
)


VOCABULARY = AllowedAtomVocabulary(
    actors=("company",),
    actions=("submit",),
    objects=("notice", "report"),
    qualifiers=("within_10_days",),
)
BASELINE_IR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="company",
            action="submit",
            object="",
            temporal=("within_10_days",),
        ),
    )
)
GUIDED_IR = CanonicalRuleIR(
    (replace(BASELINE_IR.rules[0], object="report"),)
)
FEATURE_ID = "lir-feature-source-grounded-object"
FEATURE_NAME = "semantic-slot:object:report"


class FixedConstructor:
    identity = "FixedSourceGroundedConstructor@1"

    def __init__(self) -> None:
        self.requests: list[ConstructorRequest] = []

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        self.requests.append(request)
        return ConstructorResult(
            ComponentStatus.SUCCESS, canonical_ir=BASELINE_IR
        )


def request(config: dict[str, object] | None = None) -> ConstructorRequest:
    return ConstructorRequest(
        "The company shall submit the report within 10 days.",
        VOCABULARY,
        config or {},
    )


def frozen_guidance(
    *,
    sample_count: int = 0,
    sample_memory_included: bool = False,
    stable: bool = True,
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
        stable_export={
            "excluded_categories": [
                "decoded_embeddings",
                "raw_source_text",
                "sample_identifiers",
                "sample_memory",
                "source_spans",
                "token_features",
            ],
            "export_id": "reviewed-export-1",
            "feature_count": 1,
            "sample_count": sample_count,
            "sample_memory_included": sample_memory_included,
            "schema_version": (
                "legal-ir-stable-autoencoder-feature-export-v1"
            ),
            "stable_features": [
                {
                    "feature": FEATURE_NAME,
                    "feature_id": FEATURE_ID,
                    "stable": stable,
                }
            ],
        },
    )


def reviewed_contract(
    *,
    canonical_fields: tuple[str, ...] = ("object",),
) -> ReviewedCausalL1Contract:
    review = {
        "adapter_id": "reviewed-object-intervention-v1",
        "decision": "approved",
        "scope": "causal_feature_to_canonical_field",
    }
    return ReviewedCausalL1Contract(
        adapter_id="reviewed-object-intervention-v1",
        independent_review_cid=cid_for_dag_json(review),
        reviewed_by="independent-compiler-review",
        stable_export_id="reviewed-export-1",
        interventions=(
            FeatureToCanonicalFieldIntervention(
                feature_id=FEATURE_ID,
                feature=FEATURE_NAME,
                canonical_fields=canonical_fields,
            ),
        ),
    )


def attributed_output(
    guided_ir: CanonicalRuleIR = GUIDED_IR,
    *,
    path: str = "rules[0->0].object",
    feature_id: str = FEATURE_ID,
    feature: str = FEATURE_NAME,
) -> CausalAdapterOutput:
    return CausalAdapterOutput(
        canonical_ir=guided_ir,
        attributions=(
            CausalFeatureAttribution(
                feature_id=feature_id,
                feature=feature,
                changed_field_path=path,
            ),
        ),
    )


def test_frozen_state_is_loaded_by_cid_as_global_sample_free_export() -> None:
    qualification = build_causal_guidance_qualification()

    assert qualification["state"] == {
        "access": "read_only",
        "cid": PINNED_AUTOENCODER_STATE_CID,
        "cid_verified": True,
        "declared_architecture": (
            PINNED_AUTOENCODER_DECLARED_ARCHITECTURE
        ),
        "effective_architecture": (
            PINNED_AUTOENCODER_EFFECTIVE_ARCHITECTURE
        ),
        "schema": PINNED_AUTOENCODER_STATE_SCHEMA,
        "sha256": PINNED_AUTOENCODER_STATE_SHA256,
    }
    export = qualification["stable_export"]
    assert export["global"] is True
    assert export["sample_free"] is True
    assert export["sample_count"] == 0
    assert export["sample_memory_included"] is False
    assert export["feature_count"] == 64


def test_no_reviewed_adapter_is_explicit_terminal_unsupported() -> None:
    base = FixedConstructor()
    loader_calls: list[Path] = []

    def loader(path: Path) -> FrozenAutoencoderGuidance:
        loader_calls.append(path)
        return frozen_guidance()

    constructor = CausalAutoencoderGuidance(
        base, guidance_loader=loader
    )
    paired = constructor.construct_pair(request())

    assert isinstance(constructor, RoundTripConstructor)
    assert constructor.identity.startswith(
        CAUSAL_AUTOENCODER_GUIDANCE_INTERFACE
    )
    assert len(loader_calls) == 1
    assert len(base.requests) == 1
    assert paired.status is CausalQualificationStatus.UNAVAILABLE
    assert paired.no_guidance.status is ComponentStatus.SUCCESS
    assert paired.no_guidance.canonical_ir is BASELINE_IR
    assert paired.guided.status is ComponentStatus.FAILED
    assert paired.guided.failure_reason is FailureReason.CAPABILITY_UNAVAILABLE
    assert UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER in (
        paired.guided.failure_detail or ""
    )
    assert (
        paired.missing_causal_contract
        == MISSING_CAUSAL_CONTRACT_FIELDS
    )
    assert paired.guided_disposition == "terminal_unsupported"
    assert paired.change_receipt is None


def test_disabled_guidance_negative_control_proves_exact_zero_change() -> None:
    paired = CausalAutoencoderGuidance(
        FixedConstructor(),
        guidance_loader=lambda path: frozen_guidance(),
    ).construct_pair(request())

    control = paired.negative_control
    assert control.guidance_enabled is False
    assert control.canonical_l1_changed is False
    assert control.changed_fields == ()
    assert control.causal_feature_ids == ()
    assert control.baseline_sha256 == control.no_guidance_sha256
    assert paired.no_guidance.canonical_ir == BASELINE_IR


def test_reviewed_contract_produces_paired_feature_attributed_change() -> None:
    base = FixedConstructor()
    seen: dict[str, object] = {}

    def apply(
        baseline_ir: CanonicalRuleIR,
        vocabulary: AllowedAtomVocabulary,
        guidance: FrozenAutoencoderGuidance,
    ) -> CausalAdapterOutput:
        seen.update(
            {
                "baseline_ir": baseline_ir,
                "vocabulary": vocabulary,
                "guidance": guidance,
            }
        )
        return attributed_output()

    paired = CausalAutoencoderGuidance(
        base,
        reviewed_contract=reviewed_contract(),
        applicator=apply,
        guidance_loader=lambda path: frozen_guidance(),
    ).construct_pair(request())

    assert len(base.requests) == 1
    assert paired.status is CausalQualificationStatus.QUALIFIED
    assert paired.no_guidance.canonical_ir == BASELINE_IR
    assert paired.guided.canonical_ir == GUIDED_IR
    assert paired.negative_control.canonical_l1_changed is False
    assert paired.change_receipt is not None
    assert paired.change_receipt.changed_fields == ("object",)
    assert paired.change_receipt.changed_field_paths == (
        "rules[0->0].object",
    )
    assert paired.change_receipt.causal_feature_ids == (FEATURE_ID,)
    assert seen == {
        "baseline_ir": BASELINE_IR,
        "vocabulary": VOCABULARY,
        "guidance": seen["guidance"],
    }
    # The adapter boundary contains baseline L1, closed vocabulary, and the
    # sanitized global export, but no source, target, label, count, or outcome.
    assert isinstance(seen["guidance"], FrozenAutoencoderGuidance)


@pytest.mark.parametrize(
    ("output", "match"),
    [
        (attributed_output(BASELINE_IR), "nonempty canonical change"),
        (
            attributed_output(path="rules[0->0].modality"),
            "every and only changed field",
        ),
        (
            attributed_output(feature_id="unreviewed-feature"),
            "unreviewed stable feature",
        ),
        (
            attributed_output(
                CanonicalRuleIR(
                    (
                        replace(BASELINE_IR.rules[0], object="notice"),
                        BASELINE_IR.rules[0],
                    )
                )
            ),
            "rule cardinality",
        ),
    ],
)
def test_fabricated_or_incomplete_causal_mutations_are_rejected(
    output: CausalAdapterOutput, match: str
) -> None:
    constructor = CausalAutoencoderGuidance(
        FixedConstructor(),
        reviewed_contract=reviewed_contract(),
        applicator=lambda baseline, vocabulary, guidance: output,
        guidance_loader=lambda path: frozen_guidance(),
    )

    with pytest.raises(ContractError, match=match):
        constructor.construct_pair(request())


def test_reviewed_feature_cannot_mutate_an_undeclared_field() -> None:
    modality_change = CanonicalRuleIR(
        (replace(BASELINE_IR.rules[0], modality="F"),)
    )
    constructor = CausalAutoencoderGuidance(
        FixedConstructor(),
        reviewed_contract=reviewed_contract(),
        applicator=lambda baseline, vocabulary, guidance: attributed_output(
            modality_change, path="rules[0->0].modality"
        ),
        guidance_loader=lambda path: frozen_guidance(),
    )

    with pytest.raises(ContractError, match="unreviewed field"):
        constructor.construct_pair(request())


@pytest.mark.parametrize(
    "config",
    [
        {"sample_memory": ["case-a"]},
        {"evaluation": {"gold_labels": ["O"]}},
        {"gold_rule_count": 1},
        {"target_embeddings": [0.1]},
        {"selection_outcome": "best_loss"},
    ],
)
def test_forbidden_inputs_are_rejected_before_baseline_or_adapter(
    config: dict[str, object],
) -> None:
    base = FixedConstructor()
    constructor = CausalAutoencoderGuidance(
        base,
        guidance_loader=lambda path: frozen_guidance(),
    )

    with pytest.raises(ContractError, match="forbidden"):
        constructor.construct_pair(request(config))
    assert base.requests == []


def test_stable_export_must_be_global_sample_free_and_stable() -> None:
    for kwargs, match in (
        ({"sample_count": 1}, "global and sample-free"),
        ({"stable": False}, "not stable"),
    ):
        guidance = frozen_guidance(**kwargs)
        with pytest.raises(ContractError, match=match):
            StableExportEvidence.from_guidance(guidance)

    with pytest.raises(ContractError, match="sample-memory"):
        frozen_guidance(sample_memory_included=True)


def test_contract_and_applicator_must_be_preregistered_together() -> None:
    with pytest.raises(ContractError, match="supplied together"):
        CausalAutoencoderGuidance(
            FixedConstructor(),
            reviewed_contract=reviewed_contract(),
            guidance_loader=lambda path: frozen_guidance(),
        )
    with pytest.raises(ContractError, match="supplied together"):
        CausalAutoencoderGuidance(
            FixedConstructor(),
            applicator=lambda baseline, vocabulary, guidance: (
                attributed_output()
            ),
            guidance_loader=lambda path: frozen_guidance(),
        )


def test_checked_in_qualification_is_exact_cid_bound_evidence() -> None:
    qualification = load_causal_guidance_qualification()

    assert qualification == build_causal_guidance_qualification()
    assert qualification["interface"] == (
        CAUSAL_GUIDANCE_QUALIFICATION_INTERFACE
    )
    assert qualification["status"] == (
        UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER
    )
    assert qualification["evaluation_status"] == (
        EVALUATION_STATUS_NOT_MEASURED
    )
    assert qualification["evaluation_status_reason"] == TERMINAL_UNSUPPORTED
    causal_contract = qualification["causal_contract"]
    assert causal_contract["preregistered"] is False
    assert causal_contract["missing"] == list(
        MISSING_CAUSAL_CONTRACT_FIELDS
    )
    assert (
        causal_contract["advisory_diagnostics_are_causal_guidance"]
        is False
    )
    coordinates = qualification["guided_coordinates"]
    assert coordinates["count"] == 12
    assert coordinates["disposition"] == TERMINAL_UNSUPPORTED
    assert coordinates["evaluation_status"] == (
        EVALUATION_STATUS_NOT_MEASURED
    )
    assert coordinates["schedule_for_semantic_scoring"] is False
    assert all(
        item["status"] == TERMINAL_UNSUPPORTED
        and item["evaluation_status"] == EVALUATION_STATUS_NOT_MEASURED
        and item["schedule_for_semantic_scoring"] is False
        and item["reason"]
        == UNAVAILABLE_NO_REVIEWED_CAUSAL_L1_ADAPTER
        for item in coordinates["coordinates"]
    )
    planner = qualification["matrix_planner"]
    assert planner["interface"] == CAUSAL_MATRIX_PLANNER_INTERFACE
    assert planner["include_guided_in_semantic_schedule"] is False
    assert planner["semantic_schedule"] == SEMANTIC_SCHEDULE_EXCLUDED
    assert planner["policy"] == MATRIX_SCHEDULE_POLICY
    assert planner["scheduled_for_semantic_scoring_arm_ids"] == []
    assert set(planner["excluded_guided_arm_ids"]) == {
        item["arm_id"] for item in coordinates["coordinates"]
    }
    assert DEFAULT_QUALIFICATION_PATH.is_file()
    # CID must stay bound to the refreshed path-(b) payload.
    assert isinstance(qualification["qualification_cid"], str)
    assert qualification["qualification_cid"].startswith("baguqeera")


def test_missing_contract_fail_closed_excludes_guided_from_semantic_schedule() -> None:
    """Path (b): missing reviewed contract → not_measured, not scheduled."""

    qualification = build_causal_guidance_qualification(
        guidance_loader=lambda path: frozen_guidance(),
    )
    # Pair construction still fails closed without a contract.
    paired = CausalAutoencoderGuidance(
        FixedConstructor(),
        guidance_loader=lambda path: frozen_guidance(),
    ).construct_pair(request())
    assert paired.status is CausalQualificationStatus.UNAVAILABLE
    assert paired.guided_disposition == TERMINAL_UNSUPPORTED
    assert paired.change_receipt is None
    assert paired.missing_causal_contract == MISSING_CAUSAL_CONTRACT_FIELDS
    assert guided_scored_support_from_qualification(qualification) == (
        TERMINAL_UNSUPPORTED
    )
    assert guided_scored_support_from_qualification(None) == (
        TERMINAL_UNSUPPORTED
    )

    baseline = (
        "typed_deontic__no_guidance__no_repair__not_applicable__deterministic"
    )
    guided = (
        "typed_deontic__guided__no_repair__not_applicable__deterministic"
    )
    candidates = [
        {"cell_id": baseline, "composition": {"guidance": "no_guidance"}},
        {"cell_id": guided, "composition": {"guidance": "guided"}},
        guided,
    ]
    plan = plan_guided_semantic_schedule(candidates, qualification)
    assert plan["interface"] == CAUSAL_MATRIX_PLANNER_INTERFACE
    assert plan["guided_disposition"] == TERMINAL_UNSUPPORTED
    assert plan["semantic_schedule"] == SEMANTIC_SCHEDULE_EXCLUDED
    assert plan["scheduled_arm_ids"] == [baseline]
    assert plan["not_measured_arm_ids"] == [guided, guided]
    assert all(
        item["evaluation_status"] == EVALUATION_STATUS_NOT_MEASURED
        and item["schedule_for_semantic_scoring"] is False
        and item["status"] == TERMINAL_UNSUPPORTED
        for item in plan["not_measured"]
    )
    admitted = filter_semantic_schedule_candidates(
        candidates, qualification
    )
    assert admitted == [candidates[0]]
    # Qualification matrix planner freezes the same exclusion set.
    assert set(qualification["matrix_planner"]["excluded_guided_arm_ids"]) == {
        item["arm_id"]
        for item in qualification["guided_coordinates"]["coordinates"]
    }
    assert (
        qualification["matrix_planner"][
            "scheduled_for_semantic_scoring_arm_ids"
        ]
        == []
    )


def test_scored_supported_qualification_admits_guided_to_semantic_schedule() -> None:
    """When a reviewed contract marks scored_supported, guided arms schedule."""

    qualification = {
        "status": SCORED_SUPPORTED,
        "disposition": SCORED_SUPPORTED,
        "guided_coordinates": {"disposition": SCORED_SUPPORTED},
        "causal_contract": {"preregistered": True},
        "matrix_planner": {
            "include_guided_in_semantic_schedule": True,
        },
    }
    assert guided_scored_support_from_qualification(qualification) == (
        SCORED_SUPPORTED
    )
    guided = {
        "cell_id": "typed_deontic__guided__no_repair__not_applicable__deterministic",
        "composition": {"guidance": "guided"},
    }
    plan = plan_guided_semantic_schedule([guided], qualification)
    assert plan["guided_disposition"] == SCORED_SUPPORTED
    assert plan["scheduled_arm_ids"] == [guided["cell_id"]]
    assert plan["not_measured_arm_ids"] == []
    assert filter_semantic_schedule_candidates([guided], qualification) == [
        guided
    ]


def test_qualification_rejects_self_consistent_fabricated_relabeling() -> None:
    qualification = build_causal_guidance_qualification()
    fabricated = copy.deepcopy(qualification)
    fabricated["status"] = "qualified_causal_l1_adapter"
    fabricated["evaluation_status"] = "semantic_scored"
    fabricated["guided_coordinates"]["disposition"] = SCORED_SUPPORTED
    fabricated["matrix_planner"]["include_guided_in_semantic_schedule"] = True
    fabricated["causal_contract"][
        "advisory_diagnostics_are_causal_guidance"
    ] = True
    del fabricated["qualification_cid"]
    fabricated["qualification_cid"] = cid_for_dag_json(fabricated)

    with pytest.raises(ContractError, match="contradicts"):
        validate_causal_guidance_qualification(fabricated)
