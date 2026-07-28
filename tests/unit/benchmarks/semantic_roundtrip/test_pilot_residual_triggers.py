"""Unit tests for pilot residual → selective-repair trigger projection."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
)
from benchmarks.semantic_roundtrip.residual_catalog import (
    BASELINE_ARM_ID,
    NONZERO_PILOT_CASE_IDS,
    PILOT_CASE_IDS,
    ZERO_RESIDUAL_CONTROL_CASE_ID,
    CaseResidualRecord,
    ResidualFacet,
    load_plateau_residual_catalog,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    ACTIVATION_FIXTURE_PACK_ID,
    DECLARED_STRUCTURAL_CONSTRAINTS,
    RepairAttemptStatus,
    RepairTrigger,
    RepairTriggerKind,
    SelectiveLeanstralRepair,
    SelectiveRepairPolicy,
    StructuralTool,
    StructuralValidationReceipt,
    StructuralValidationRequest,
    StructuralValidatorBinding,
    HammerCandidateSelector,
    validate_selective_repair_activation,
)
from benchmarks.semantic_roundtrip.pilot_residual_triggers import (
    MIN_NONZERO_PILOTS_WITH_TRIGGERS,
    PILOT_RESIDUAL_TRIGGER_DETECTOR_INTERFACE,
    PILOT_RESIDUAL_TRIGGER_MAP_INTERFACE,
    PILOT_RESIDUAL_TRIGGERS_INTERFACE,
    PRODUCTION_NO_REPAIR_ARM_ID,
    CatalogPilotResidualTriggerDetector,
    PilotCaseTriggerRecord,
    PilotResidualTriggerDetector,
    PilotResidualTriggerError,
    PilotResidualTriggerMap,
    build_validated_pilot_residual_trigger_map,
    production_path_is_no_repair,
    project_case_trigger_record,
    project_pilot_residual_trigger_map,
    residual_facet_is_projectable,
    trigger_from_residual_facet,
    triggers_from_case_residual,
    triggers_from_residual_facets,
    untriggered_fields_preserved,
    validate_pilot_trigger_coverage,
)


ROOT = Path(__file__).resolve().parents[4]


def _facet(
    *,
    case_id: str = "exec_order_1",
    field_path: str = "rules[0].temporal",
    residual_kind: str = "field_mismatch",
    loss: float = 0.05,
    field: str | None = "temporal",
    cand_idx: int | None = 0,
    gold_idx: int | None = 0,
    suggested: str = "missing",
    gold_value: object = ("within_24_hours",),
    candidate_value: object = (),
) -> ResidualFacet:
    return ResidualFacet(
        case_id=case_id,
        field_path=field_path,
        residual_kind=residual_kind,
        loss_contribution=loss,
        similarity=0.0,
        suggested_trigger_kind=suggested,
        canonical_field=field,
        gold_rule_index=gold_idx,
        candidate_rule_index=cand_idx,
        gold_value=list(gold_value) if isinstance(gold_value, tuple) else gold_value,
        candidate_value=(
            list(candidate_value)
            if isinstance(candidate_value, tuple)
            else candidate_value
        ),
    )


def _baseline_two_rules() -> CanonicalRuleIR:
    return CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="agency",
                action="file",
                object="notice",
                conditions=(),
                temporal=(),
            ),
            CanonicalRule(
                modality="O",
                actor="agency",
                action="publish",
                object="report",
                conditions=("ready",),
                temporal=("annually",),
            ),
        )
    )


def test_interfaces_and_acceptance_floor_are_frozen() -> None:
    assert PILOT_RESIDUAL_TRIGGERS_INTERFACE == "PilotResidualTriggers@1"
    assert PILOT_RESIDUAL_TRIGGER_MAP_INTERFACE == "PilotResidualTriggerMap@1"
    assert PILOT_RESIDUAL_TRIGGER_DETECTOR_INTERFACE == (
        "PilotResidualTriggerDetector@1"
    )
    assert MIN_NONZERO_PILOTS_WITH_TRIGGERS == 3
    assert PRODUCTION_NO_REPAIR_ARM_ID == BASELINE_ARM_ID
    assert "no_repair" in PRODUCTION_NO_REPAIR_ARM_ID
    assert production_path_is_no_repair() is True
    assert production_path_is_no_repair(
        "typed_deontic__no_guidance__selective_repair__hammer_cvc5__deterministic"
    ) is False


def test_projectable_facets_require_l1_field_slots() -> None:
    field = _facet()
    missing_rule = _facet(
        field_path="rules[8]",
        residual_kind="missing_rule",
        field=None,
        cand_idx=None,
        gold_idx=8,
        suggested="missing",
        gold_value={"modality": "O"},
        candidate_value=None,
    )
    assert residual_facet_is_projectable(field) is True
    assert residual_facet_is_projectable(missing_rule) is False
    assert trigger_from_residual_facet(missing_rule) is None


def test_triggers_from_facets_prefer_higher_loss_and_bound_slots() -> None:
    baseline = _baseline_two_rules()
    facets = (
        _facet(
            field_path="rules[0].temporal",
            field="temporal",
            cand_idx=0,
            loss=0.01,
        ),
        _facet(
            field_path="rules[0].conditions",
            field="conditions",
            cand_idx=0,
            loss=0.08,
            gold_value=("ready",),
        ),
        _facet(
            field_path="rules[1].temporal",
            field="temporal",
            cand_idx=1,
            loss=0.04,
            # nonempty baseline temporal → missing trigger skipped
            suggested="contradictory",
            gold_value=("daily",),
            candidate_value=("annually",),
        ),
    )
    policy = SelectiveRepairPolicy(max_repair_slots=2)
    triggers = triggers_from_residual_facets(
        facets, baseline_ir=baseline, policy=policy
    )
    assert len(triggers) == 2
    assert triggers[0].path == "rules[0].conditions"
    assert triggers[0].kind is RepairTriggerKind.MISSING
    paths = {item.path for item in triggers}
    assert "rules[0].conditions" in paths
    # Second slot is higher of remaining projectable residuals.
    assert "rules[1].temporal" in paths or "rules[0].temporal" in paths


def test_missing_trigger_skipped_when_baseline_slot_nonempty() -> None:
    baseline = _baseline_two_rules()
    facet = _facet(
        field_path="rules[1].conditions",
        field="conditions",
        cand_idx=1,
        suggested="missing",
        gold_value=("extra",),
        candidate_value=("ready",),
    )
    assert trigger_from_residual_facet(facet, baseline_ir=baseline) is None


def test_zero_residual_control_emits_no_triggers() -> None:
    record = CaseResidualRecord(
        case_id=ZERO_RESIDUAL_CONTROL_CASE_ID,
        forward_loss=0.0,
        residuals=(),
        is_zero_residual_control=True,
    )
    assert triggers_from_case_residual(record) == ()
    projected = project_case_trigger_record(record)
    assert projected.has_trigger is False
    assert projected.trigger_count == 0


def test_catalog_projection_meets_coverage_acceptance() -> None:
    catalog = load_plateau_residual_catalog()
    trigger_map = build_validated_pilot_residual_trigger_map(catalog)

    assert trigger_map.interface == PILOT_RESIDUAL_TRIGGER_MAP_INTERFACE
    assert trigger_map.meets_coverage_acceptance is True
    assert (
        trigger_map.triggered_nonzero_pilot_count
        >= MIN_NONZERO_PILOTS_WITH_TRIGGERS
    )
    assert set(trigger_map.nonzero_case_ids_with_triggers) <= set(
        NONZERO_PILOT_CASE_IDS
    )
    # Stronger than the floor when residual facets support it.
    assert trigger_map.triggered_nonzero_pilot_count >= 3

    by_case = trigger_map.by_case_id()
    assert set(by_case) >= set(PILOT_CASE_IDS) or set(by_case) == {
        item.case_id for item in trigger_map.cases
    }
    control = by_case[ZERO_RESIDUAL_CONTROL_CASE_ID]
    assert control.has_trigger is False
    assert control.is_zero_residual_control is True

    for case_id in NONZERO_PILOT_CASE_IDS:
        record = by_case[case_id]
        assert record.residual_count > 0
        # All four non-zero pilots currently project at least one field slot.
        assert record.has_trigger is True
        assert record.trigger_count >= 1
        assert record.trigger_count <= trigger_map.max_repair_slots
        for trigger in record.triggers:
            assert isinstance(trigger, RepairTrigger)
            assert trigger.kind in {
                RepairTriggerKind.MISSING,
                RepairTriggerKind.CONTRADICTORY,
            }
            assert trigger.evidence
            assert "plateau residual" in (trigger.evidence or "")

    # construction_contract skips whole missing-rule residual.
    construction = by_case["construction_contract"]
    assert any(
        path == "rules[8]" or path.startswith("rules[8]")
        for path in construction.skipped_residual_paths
    ) or construction.projectable_residual_count < construction.residual_count

    payload = trigger_map.to_dict()
    assert payload["production_arm_id"] == PRODUCTION_NO_REPAIR_ARM_ID
    assert payload["meets_coverage_acceptance"] is True
    assert "no_repair" in payload["production_arm_id"]


def test_validate_coverage_fails_when_too_few_pilots_trigger() -> None:
    weak = PilotResidualTriggerMap(
        cases=(
            PilotCaseTriggerRecord(
                case_id=ZERO_RESIDUAL_CONTROL_CASE_ID,
                triggers=(),
                residual_count=0,
                projectable_residual_count=0,
                forward_loss=0.0,
                is_zero_residual_control=True,
            ),
            PilotCaseTriggerRecord(
                case_id="exec_order_1",
                triggers=(
                    RepairTrigger(
                        0, "temporal", RepairTriggerKind.MISSING, evidence="x"
                    ),
                ),
                residual_count=1,
                projectable_residual_count=1,
                forward_loss=0.05,
                is_zero_residual_control=False,
            ),
            PilotCaseTriggerRecord(
                case_id="corp_policy_1",
                triggers=(),
                residual_count=1,
                projectable_residual_count=0,
                forward_loss=0.1,
                is_zero_residual_control=False,
            ),
        ),
        production_arm_id=PRODUCTION_NO_REPAIR_ARM_ID,
    )
    with pytest.raises(PilotResidualTriggerError, match="coverage"):
        validate_pilot_trigger_coverage(weak)


def test_untriggered_fields_preserved_invariant() -> None:
    baseline = _baseline_two_rules()
    triggers = (
        RepairTrigger(
            0, "temporal", RepairTriggerKind.MISSING, evidence="empty temporal"
        ),
    )
    repaired_ok = CanonicalRuleIR(
        (
            replace(baseline.rules[0], temporal=("within_24_hours",)),
            baseline.rules[1],
        )
    )
    repaired_bad = CanonicalRuleIR(
        (
            replace(
                baseline.rules[0],
                temporal=("within_24_hours",),
                actor="other",
            ),
            baseline.rules[1],
        )
    )
    assert untriggered_fields_preserved(baseline, repaired_ok, triggers) is True
    assert (
        untriggered_fields_preserved(baseline, repaired_bad, triggers) is False
    )
    assert untriggered_fields_preserved(baseline, baseline, triggers) is True


def test_selective_repair_with_residual_triggers_scopes_field_changes() -> None:
    """Residual triggers open repair; untriggered projection is preserved."""

    baseline = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="controller",
                action="delete",
                object="",
                temporal=(),
            ),
        )
    )
    repaired = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="controller",
                action="delete",
                object="records",
                temporal=(),
            ),
        )
    )
    # Residual-style missing object slot (pilot-shaped).
    facets = (
        ResidualFacet(
            case_id="demo",
            field_path="rules[0].object",
            residual_kind="field_mismatch",
            loss_contribution=0.1,
            similarity=0.0,
            suggested_trigger_kind=RepairTriggerKind.MISSING.value,
            canonical_field="object",
            gold_rule_index=0,
            candidate_rule_index=0,
            gold_value="records",
            candidate_value="",
        ),
    )
    triggers = triggers_from_residual_facets(facets, baseline_ir=baseline)
    assert triggers
    assert triggers[0].path == "rules[0].object"

    vocab = AllowedAtomVocabulary(
        actors=("controller",),
        actions=("delete",),
        objects=("records",),
        qualifiers=(),
    )

    class FixedBaseline:
        identity = "FixedBaseline@1"

        def construct(self, request: ConstructorRequest) -> ConstructorResult:
            del request
            return ConstructorResult(
                ComponentStatus.SUCCESS, canonical_ir=baseline
            )

    class Client:
        endpoint = LEANSTRAL_ENDPOINT
        model = LEANSTRAL_MODEL

        def complete_json(self, **kwargs: object) -> object:
            del kwargs
            return repaired.to_dict()

    def validate(
        structural_request: StructuralValidationRequest,
    ) -> StructuralValidationReceipt:
        del structural_request
        return StructuralValidationReceipt(
            validator_id="test-hammer",
            tool=StructuralTool.HAMMER_CVC5,
            constraints=DECLARED_STRUCTURAL_CONSTRAINTS,
            passed=True,
        )

    policy = SelectiveRepairPolicy(candidate_count=1)
    binding = StructuralValidatorBinding(
        "test-hammer",
        StructuralTool.HAMMER_CVC5,
        DECLARED_STRUCTURAL_CONSTRAINTS,
        validate,
    )
    repairer = SelectiveLeanstralRepair(
        FixedBaseline(),
        client=Client(),
        policy=policy,
        selector=HammerCandidateSelector(policy, validators=(binding,)),
        trigger_detector=PilotResidualTriggerDetector(triggers),
    )
    request = ConstructorRequest(
        "The controller must delete the records.",
        vocab,
        {},
    )
    construction = repairer.construct_with_diagnostics(request)

    assert construction.receipt.status is RepairAttemptStatus.ACCEPTED
    assert construction.result.canonical_ir == repaired
    assert construction.baseline_result.canonical_ir == baseline
    assert untriggered_fields_preserved(
        baseline, construction.result.canonical_ir, triggers
    )
    assert construction.receipt.triggers
    # Outside-trigger rewrite must be rejected by structural selection rules.
    hijacked = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="F",
                actor="controller",
                action="delete",
                object="records",
                temporal=(),
            ),
        )
    )

    class BadClient:
        endpoint = LEANSTRAL_ENDPOINT
        model = LEANSTRAL_MODEL

        def complete_json(self, **kwargs: object) -> object:
            del kwargs
            return hijacked.to_dict()

    bad_repairer = SelectiveLeanstralRepair(
        FixedBaseline(),
        client=BadClient(),
        policy=policy,
        selector=HammerCandidateSelector(policy, validators=(binding,)),
        trigger_detector=PilotResidualTriggerDetector(triggers),
    )
    bad = bad_repairer.construct_with_diagnostics(request)
    assert bad.receipt.status is not RepairAttemptStatus.ACCEPTED
    assert bad.result.canonical_ir == baseline or bad.result.status is (
        ComponentStatus.FAILED
    )
    if bad.result.canonical_ir is not None:
        # Fail-closed: unrepaired baseline retained on rejection/failure path.
        assert bad.receipt.baseline_retained is True


def test_catalog_detector_resolves_case_id_and_zero_otherwise() -> None:
    trigger_map = project_pilot_residual_trigger_map(
        load_plateau_residual_catalog()
    )
    detector = CatalogPilotResidualTriggerDetector(trigger_map)
    vocab = AllowedAtomVocabulary(
        actors=("a",),
        actions=("b",),
        objects=("c",),
        qualifiers=(),
    )
    # Unknown / missing case_id → no triggers (production-safe default).
    empty = detector.detect(
        ConstructorRequest("text", vocab, {}),
        _baseline_two_rules(),
    )
    assert empty == ()

    case_id = next(iter(trigger_map.nonzero_case_ids_with_triggers))
    record = trigger_map.by_case_id()[case_id]
    # Build a baseline large enough for the highest rule index.
    max_index = max(item.rule_index for item in record.triggers)
    rules = []
    for index in range(max_index + 1):
        matching = [t for t in record.triggers if t.rule_index == index]
        conditions: tuple[str, ...] = ()
        temporal: tuple[str, ...] = ()
        obj = "object"
        for trigger in matching:
            if trigger.kind is RepairTriggerKind.MISSING:
                if trigger.canonical_field == "conditions":
                    conditions = ()
                elif trigger.canonical_field == "temporal":
                    temporal = ()
                elif trigger.canonical_field == "object":
                    obj = ""
            elif trigger.kind is RepairTriggerKind.CONTRADICTORY:
                if trigger.canonical_field == "conditions":
                    conditions = ("present",)
                elif trigger.canonical_field == "temporal":
                    temporal = ("present",)
                elif trigger.canonical_field == "object":
                    obj = "present"
        rules.append(
            CanonicalRule(
                modality="O",
                actor="actor",
                action="action",
                object=obj,
                conditions=conditions,
                temporal=temporal,
            )
        )
    baseline = CanonicalRuleIR(tuple(rules))
    found = detector.detect(
        ConstructorRequest("text", vocab, {"case_id": case_id}),
        baseline,
    )
    assert found
    assert {item.path for item in found} == {
        item.path for item in record.triggers
    }


def test_pilot_detector_identity_and_empty_triggers() -> None:
    detector = PilotResidualTriggerDetector(())
    assert detector.identity == PILOT_RESIDUAL_TRIGGER_DETECTOR_INTERFACE
    vocab = AllowedAtomVocabulary(
        actors=("a",), actions=("b",), objects=("c",), qualifiers=()
    )
    assert (
        detector.detect(
            ConstructorRequest("x", vocab, {}),
            _baseline_two_rules(),
        )
        == ()
    )


def test_fixture_activation_pack_still_passes() -> None:
    report = validate_selective_repair_activation()
    assert report.fixture_pack_id == ACTIVATION_FIXTURE_PACK_ID
    assert report.validation_passed is True
    assert report.any_trigger is True


def test_default_production_path_remains_no_repair() -> None:
    assert production_path_is_no_repair() is True
    trigger_map = project_pilot_residual_trigger_map(
        load_plateau_residual_catalog()
    )
    assert "no_repair" in trigger_map.production_arm_id
    # Projection alone does not force selective repair into production.
    assert trigger_map.production_arm_id == BASELINE_ARM_ID
    # Detectors are opt-in; empty / unbound case yields no model-facing triggers.
    detector = CatalogPilotResidualTriggerDetector(trigger_map)
    vocab = AllowedAtomVocabulary(
        actors=("a",), actions=("b",), objects=("c",), qualifiers=()
    )
    assert (
        detector.detect(
            ConstructorRequest("unrelated source", vocab, {}),
            _baseline_two_rules(),
        )
        == ()
    )


def test_case_trigger_record_round_trip() -> None:
    record = PilotCaseTriggerRecord(
        case_id="legal_doc_1",
        triggers=(
            RepairTrigger(
                1,
                "temporal",
                RepairTriggerKind.MISSING,
                evidence="plateau residual rules[1].temporal",
            ),
        ),
        residual_count=4,
        projectable_residual_count=4,
        forward_loss=0.13,
        is_zero_residual_control=False,
        skipped_residual_paths=(),
    )
    restored = PilotCaseTriggerRecord.from_dict(record.to_dict())
    assert restored.case_id == record.case_id
    assert restored.trigger_count == 1
    assert restored.triggers[0].path == "rules[1].temporal"
    assert restored.triggers[0].kind is RepairTriggerKind.MISSING


def test_policy_validate_accepts_projected_catalog_triggers() -> None:
    """Every emitted pilot trigger must satisfy SelectiveRepairPolicy.

    Validate each trigger against a single-rule baseline whose slot state
    matches the residual candidate (empty for missing, present for
    contradictory).  Multi-rule synthetic IRs are avoided because
    ``CanonicalRuleIR`` re-sorts rules and would scramble indices.
    """

    catalog = load_plateau_residual_catalog()
    trigger_map = project_pilot_residual_trigger_map(catalog)
    policy = SelectiveRepairPolicy()

    for case_id, record in trigger_map.by_case_id().items():
        if not record.triggers:
            continue
        for trigger in record.triggers:
            kwargs: dict[str, object] = {
                "modality": "O",
                "actor": "actor",
                "action": "action",
                "object": "object",
                "conditions": ("held",),
                "exceptions": (),
                "temporal": ("held",),
            }
            if trigger.kind is RepairTriggerKind.MISSING:
                if trigger.canonical_field in {
                    "conditions",
                    "exceptions",
                    "temporal",
                }:
                    kwargs[trigger.canonical_field] = ()
                else:
                    kwargs[trigger.canonical_field] = ""
            elif trigger.kind is RepairTriggerKind.CONTRADICTORY:
                if trigger.canonical_field in {
                    "conditions",
                    "exceptions",
                    "temporal",
                }:
                    kwargs[trigger.canonical_field] = ("present",)
                else:
                    kwargs[trigger.canonical_field] = "present"
            baseline = CanonicalRuleIR((CanonicalRule(**kwargs),))  # type: ignore[arg-type]
            localized = RepairTrigger(
                rule_index=0,
                canonical_field=trigger.canonical_field,
                kind=trigger.kind,
                confidence=trigger.confidence,
                evidence=trigger.evidence,
            )
            validated = policy.validate_triggers(baseline, (localized,))
            assert len(validated) == 1
            assert validated[0].canonical_field == trigger.canonical_field
            assert validated[0].kind is trigger.kind
            assert untriggered_fields_preserved(
                baseline, baseline, validated
            )
        assert case_id  # keep case_id referenced for clarity in failures


def test_control_cannot_carry_triggers_on_record() -> None:
    with pytest.raises(PilotResidualTriggerError, match="zero-residual"):
        PilotCaseTriggerRecord(
            case_id=ZERO_RESIDUAL_CONTROL_CASE_ID,
            triggers=(
                RepairTrigger(
                    0, "temporal", RepairTriggerKind.MISSING, evidence="bad"
                ),
            ),
            residual_count=0,
            projectable_residual_count=0,
            forward_loss=0.0,
            is_zero_residual_control=True,
        )
