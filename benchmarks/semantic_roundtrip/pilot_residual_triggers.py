"""Pilot residual → selective-repair trigger projection (PLAT-030).

Maps ``PlateauResidualCatalog@1`` case×facet residuals onto compiler-declared
``RepairTrigger@1`` slots so selective repair can fire on real pilot L1s, not
only the forced-defect activation fixture pack.

Projection rules (fail-closed):

* Only field-level residuals with a candidate (L1) rule index and a canonical
  field become triggers.  Whole missing/extra rules are skipped — they cannot
  open a slot on the unrepaired baseline cardinality.
* ``suggested_trigger_kind`` is taken from the residual catalog
  (``missing`` / ``contradictory``; structural forensics does not emit
  ``low_confidence``).
* Triggers are L1-local: ``rule_index = candidate_rule_index``.
* Slots are bounded by ``SelectiveRepairPolicy.max_repair_slots`` and validated
  against the baseline IR when one is supplied.
* The zero-residual control (``exception_with_window``) emits no triggers.
* Production composition remains the no-repair typed_deontic arm unless a
  caller explicitly wires this detector into selective repair.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRuleIR,
    ConstructorRequest,
    ContractError,
    RULE_FIELDS,
)
from benchmarks.semantic_roundtrip.residual_catalog import (
    BASELINE_ARM_ID,
    CaseResidualRecord,
    NONZERO_PILOT_CASE_IDS,
    PILOT_CASE_IDS,
    ResidualFacet,
    ZERO_RESIDUAL_CONTROL_CASE_ID,
    load_plateau_residual_catalog,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    DEFAULT_MAX_REPAIR_SLOTS,
    RepairTrigger,
    RepairTriggerKind,
    SelectiveRepairPolicy,
)


PILOT_RESIDUAL_TRIGGERS_INTERFACE: Final = "PilotResidualTriggers@1"
PILOT_RESIDUAL_TRIGGER_MAP_INTERFACE: Final = "PilotResidualTriggerMap@1"
PILOT_RESIDUAL_TRIGGER_DETECTOR_INTERFACE: Final = (
    "PilotResidualTriggerDetector@1"
)
PILOT_RESIDUAL_TRIGGERS_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-pilot-residual-triggers.v1"
)

# Acceptance: ≥3 of 4 non-zero pilots must emit ≥1 trigger.
MIN_NONZERO_PILOTS_WITH_TRIGGERS: Final = 3

# Residuals that can open a RepairTrigger slot on the baseline L1.
_PROJECTABLE_RESIDUAL_KINDS: Final = frozenset({"field_mismatch"})

PRODUCTION_NO_REPAIR_ARM_ID: Final = BASELINE_ARM_ID


class PilotResidualTriggerError(ContractError):
    """Raised when residual facets cannot be projected into repair triggers."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise PilotResidualTriggerError(message)


def _nonblank(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PilotResidualTriggerError(f"{path} must be a nonblank string")
    return value


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise PilotResidualTriggerError(f"{path} must be an object")
    return value


def is_slot_empty(baseline_ir: CanonicalRuleIR, rule_index: int, field: str) -> bool:
    """Return True when the baseline L1 slot is empty (scalar '' or list ())."""

    if rule_index < 0 or rule_index >= len(baseline_ir.rules):
        return False
    if field not in RULE_FIELDS:
        return False
    current = getattr(baseline_ir.rules[rule_index], field)
    return current in ("", ())


def residual_facet_is_projectable(facet: ResidualFacet) -> bool:
    """Whether a residual facet can become a field-scoped RepairTrigger."""

    if facet.residual_kind not in _PROJECTABLE_RESIDUAL_KINDS:
        return False
    if facet.canonical_field is None or facet.canonical_field not in RULE_FIELDS:
        return False
    if facet.candidate_rule_index is None:
        return False
    if (
        isinstance(facet.candidate_rule_index, bool)
        or not isinstance(facet.candidate_rule_index, int)
        or facet.candidate_rule_index < 0
    ):
        return False
    try:
        RepairTriggerKind(facet.suggested_trigger_kind)
    except (TypeError, ValueError):
        return False
    return True


def _evidence_for_facet(facet: ResidualFacet) -> str:
    return (
        f"plateau residual {facet.field_path}: "
        f"{facet.residual_kind} loss={facet.loss_contribution:g} "
        f"suggested={facet.suggested_trigger_kind}"
    )


def trigger_from_residual_facet(
    facet: ResidualFacet,
    *,
    baseline_ir: CanonicalRuleIR | None = None,
    require_projectable: bool = True,
) -> RepairTrigger | None:
    """Project one residual facet into a RepairTrigger, or None if skipped.

    When ``baseline_ir`` is provided, ``missing`` triggers are only emitted if
    the corresponding L1 slot is empty (matches SelectiveRepairPolicy).
    """

    if not residual_facet_is_projectable(facet):
        if require_projectable:
            return None
        raise PilotResidualTriggerError(
            f"residual facet {facet.field_path!r} is not projectable"
        )

    kind = RepairTriggerKind(facet.suggested_trigger_kind)
    rule_index = int(facet.candidate_rule_index)  # type: ignore[arg-type]
    field = str(facet.canonical_field)

    if baseline_ir is not None:
        if rule_index >= len(baseline_ir.rules):
            return None
        if kind is RepairTriggerKind.MISSING and not is_slot_empty(
            baseline_ir, rule_index, field
        ):
            return None
        if kind is RepairTriggerKind.LOW_CONFIDENCE:
            # Structural residual catalog does not supply confidences.
            return None

    confidence: float | None = None
    if kind is RepairTriggerKind.LOW_CONFIDENCE:
        # Teacher overlays may supply low_confidence later; structural map
        # never reaches here without confidence, so skip fail-closed.
        return None

    return RepairTrigger(
        rule_index=rule_index,
        canonical_field=field,
        kind=kind,
        confidence=confidence,
        evidence=_evidence_for_facet(facet),
    )


def triggers_from_residual_facets(
    facets: Sequence[ResidualFacet],
    *,
    baseline_ir: CanonicalRuleIR | None = None,
    policy: SelectiveRepairPolicy | None = None,
    max_repair_slots: int | None = None,
) -> tuple[RepairTrigger, ...]:
    """Project residual facets into a bounded, validated trigger set.

    Ordering prefers higher ``loss_contribution``, then path, then kind — the
    same prioritization used for residual catalog sort keys — so the bounded
    slot budget keeps the highest-impact pilot residuals.
    """

    if isinstance(facets, (str, bytes, bytearray)):
        raise PilotResidualTriggerError("facets must be a sequence")

    resolved_policy = policy if policy is not None else SelectiveRepairPolicy()
    bound = (
        int(max_repair_slots)
        if max_repair_slots is not None
        else int(resolved_policy.max_repair_slots)
    )
    if bound < 1:
        raise PilotResidualTriggerError("max_repair_slots must be positive")

    scored: list[tuple[float, str, str, RepairTrigger]] = []
    seen_paths: set[str] = set()
    for facet in facets:
        if not isinstance(facet, ResidualFacet):
            if isinstance(facet, Mapping):
                facet = ResidualFacet.from_dict(facet)
            else:
                raise PilotResidualTriggerError(
                    "facets must be ResidualFacet records"
                )
        trigger = trigger_from_residual_facet(
            facet, baseline_ir=baseline_ir
        )
        if trigger is None:
            continue
        if trigger.path in seen_paths:
            continue
        seen_paths.add(trigger.path)
        scored.append(
            (
                float(facet.loss_contribution),
                trigger.path,
                trigger.kind.value,
                trigger,
            )
        )

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected = tuple(item[3] for item in scored[:bound])

    if baseline_ir is not None and selected:
        return resolved_policy.validate_triggers(baseline_ir, selected)
    return selected


def triggers_from_case_residual(
    record: CaseResidualRecord | Mapping[str, object],
    *,
    baseline_ir: CanonicalRuleIR | None = None,
    policy: SelectiveRepairPolicy | None = None,
    max_repair_slots: int | None = None,
) -> tuple[RepairTrigger, ...]:
    """Project one case residual record into RepairTrigger slots."""

    case = (
        record
        if isinstance(record, CaseResidualRecord)
        else CaseResidualRecord.from_dict(record)
    )
    if case.is_zero_residual_control:
        return ()
    return triggers_from_residual_facets(
        case.residuals,
        baseline_ir=baseline_ir,
        policy=policy,
        max_repair_slots=max_repair_slots,
    )


@dataclass(frozen=True, slots=True)
class PilotCaseTriggerRecord:
    """Per-case residual → trigger projection receipt."""

    case_id: str
    triggers: tuple[RepairTrigger, ...]
    residual_count: int
    projectable_residual_count: int
    forward_loss: float
    is_zero_residual_control: bool
    skipped_residual_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _nonblank(self.case_id, "case_id"))
        object.__setattr__(self, "triggers", tuple(self.triggers))
        object.__setattr__(
            self,
            "skipped_residual_paths",
            tuple(self.skipped_residual_paths),
        )
        if not all(isinstance(item, RepairTrigger) for item in self.triggers):
            raise PilotResidualTriggerError(
                "triggers must be RepairTrigger records"
            )
        for name in ("residual_count", "projectable_residual_count"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise PilotResidualTriggerError(
                    f"{name} must be a nonnegative integer"
                )
        if (
            isinstance(self.forward_loss, bool)
            or not isinstance(self.forward_loss, (int, float))
            or not 0.0 <= float(self.forward_loss) <= 1.0
        ):
            raise PilotResidualTriggerError(
                "forward_loss must be a finite number from zero to one"
            )
        object.__setattr__(self, "forward_loss", float(self.forward_loss))
        if self.is_zero_residual_control and self.triggers:
            raise PilotResidualTriggerError(
                "zero-residual control cannot emit triggers"
            )

    @property
    def trigger_count(self) -> int:
        return len(self.triggers)

    @property
    def has_trigger(self) -> bool:
        return bool(self.triggers)

    @property
    def trigger_paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.triggers)

    @property
    def trigger_kinds(self) -> tuple[str, ...]:
        return tuple(item.kind.value for item in self.triggers)

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "forward_loss": self.forward_loss,
            "has_trigger": self.has_trigger,
            "is_zero_residual_control": self.is_zero_residual_control,
            "projectable_residual_count": self.projectable_residual_count,
            "residual_count": self.residual_count,
            "skipped_residual_paths": list(self.skipped_residual_paths),
            "trigger_count": self.trigger_count,
            "trigger_kinds": list(self.trigger_kinds),
            "trigger_paths": list(self.trigger_paths),
            "triggers": [item.to_dict() for item in self.triggers],
        }

    @classmethod
    def from_dict(cls, value: object) -> "PilotCaseTriggerRecord":
        data = _mapping(value, "pilot case trigger record")
        triggers = tuple(
            item
            if isinstance(item, RepairTrigger)
            else RepairTrigger(
                rule_index=int(item["rule_index"]),
                canonical_field=str(item["canonical_field"]),
                kind=RepairTriggerKind(item["kind"]),
                confidence=item.get("confidence"),
                evidence=item.get("evidence"),
            )
            for item in data.get("triggers", ())
        )
        return cls(
            case_id=_nonblank(data.get("case_id"), "case_id"),
            triggers=triggers,
            residual_count=int(data.get("residual_count", 0)),
            projectable_residual_count=int(
                data.get("projectable_residual_count", 0)
            ),
            forward_loss=float(data.get("forward_loss", 0.0)),
            is_zero_residual_control=bool(
                data.get("is_zero_residual_control")
            ),
            skipped_residual_paths=tuple(
                str(item) for item in data.get("skipped_residual_paths", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class PilotResidualTriggerMap:
    """Full pilot residual → trigger map for the sealed five-case set."""

    cases: tuple[PilotCaseTriggerRecord, ...]
    catalog_cid: str | None = None
    policy_digest: str | None = None
    max_repair_slots: int = DEFAULT_MAX_REPAIR_SLOTS
    production_arm_id: str = PRODUCTION_NO_REPAIR_ARM_ID
    interface: str = PILOT_RESIDUAL_TRIGGER_MAP_INTERFACE
    schema_version: str = PILOT_RESIDUAL_TRIGGERS_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))
        if not self.cases:
            raise PilotResidualTriggerError(
                "pilot residual trigger map requires case records"
            )
        if not all(
            isinstance(item, PilotCaseTriggerRecord) for item in self.cases
        ):
            raise PilotResidualTriggerError(
                "cases must be PilotCaseTriggerRecord records"
            )
        observed = tuple(item.case_id for item in self.cases)
        if len(set(observed)) != len(observed):
            raise PilotResidualTriggerError(
                "pilot residual trigger map case_ids must be unique"
            )
        if (
            isinstance(self.max_repair_slots, bool)
            or not isinstance(self.max_repair_slots, int)
            or self.max_repair_slots < 1
        ):
            raise PilotResidualTriggerError(
                "max_repair_slots must be a positive integer"
            )
        object.__setattr__(
            self,
            "production_arm_id",
            _nonblank(self.production_arm_id, "production_arm_id"),
        )
        object.__setattr__(
            self, "interface", _nonblank(self.interface, "interface")
        )
        object.__setattr__(
            self,
            "schema_version",
            _nonblank(self.schema_version, "schema_version"),
        )
        if self.catalog_cid is not None:
            object.__setattr__(
                self, "catalog_cid", _nonblank(self.catalog_cid, "catalog_cid")
            )
        if self.policy_digest is not None:
            object.__setattr__(
                self,
                "policy_digest",
                _nonblank(self.policy_digest, "policy_digest"),
            )

    def by_case_id(self) -> Mapping[str, PilotCaseTriggerRecord]:
        return MappingProxyType({item.case_id: item for item in self.cases})

    @property
    def nonzero_case_ids_with_triggers(self) -> tuple[str, ...]:
        return tuple(
            item.case_id
            for item in self.cases
            if item.case_id in NONZERO_PILOT_CASE_IDS and item.has_trigger
        )

    @property
    def triggered_nonzero_pilot_count(self) -> int:
        return len(self.nonzero_case_ids_with_triggers)

    @property
    def meets_coverage_acceptance(self) -> bool:
        return (
            self.triggered_nonzero_pilot_count
            >= MIN_NONZERO_PILOTS_WITH_TRIGGERS
        )

    def triggers_for(self, case_id: str) -> tuple[RepairTrigger, ...]:
        record = self.by_case_id().get(case_id)
        if record is None:
            raise PilotResidualTriggerError(
                f"unknown pilot case_id: {case_id!r}"
            )
        return record.triggers

    def to_dict(self) -> dict[str, object]:
        return {
            "cases": [item.to_dict() for item in self.cases],
            "catalog_cid": self.catalog_cid,
            "interface": self.interface,
            "max_repair_slots": self.max_repair_slots,
            "meets_coverage_acceptance": self.meets_coverage_acceptance,
            "min_nonzero_pilots_with_triggers": MIN_NONZERO_PILOTS_WITH_TRIGGERS,
            "nonzero_case_ids_with_triggers": list(
                self.nonzero_case_ids_with_triggers
            ),
            "policy_digest": self.policy_digest,
            "production_arm_id": self.production_arm_id,
            "schema_version": self.schema_version,
            "triggered_nonzero_pilot_count": self.triggered_nonzero_pilot_count,
        }


def project_case_trigger_record(
    record: CaseResidualRecord | Mapping[str, object],
    *,
    baseline_ir: CanonicalRuleIR | None = None,
    policy: SelectiveRepairPolicy | None = None,
    max_repair_slots: int | None = None,
) -> PilotCaseTriggerRecord:
    """Build a per-case trigger projection receipt from residual forensics."""

    case = (
        record
        if isinstance(record, CaseResidualRecord)
        else CaseResidualRecord.from_dict(record)
    )
    projectable = [
        facet
        for facet in case.residuals
        if residual_facet_is_projectable(facet)
    ]
    skipped = [
        facet.field_path
        for facet in case.residuals
        if not residual_facet_is_projectable(facet)
    ]
    triggers = triggers_from_case_residual(
        case,
        baseline_ir=baseline_ir,
        policy=policy,
        max_repair_slots=max_repair_slots,
    )
    return PilotCaseTriggerRecord(
        case_id=case.case_id,
        triggers=triggers,
        residual_count=case.residual_count,
        projectable_residual_count=len(projectable),
        forward_loss=case.forward_loss,
        is_zero_residual_control=case.is_zero_residual_control,
        skipped_residual_paths=tuple(skipped),
    )


def project_pilot_residual_trigger_map(
    catalog: Mapping[str, object] | None = None,
    *,
    baseline_ir_by_case: Mapping[str, CanonicalRuleIR] | None = None,
    policy: SelectiveRepairPolicy | None = None,
    max_repair_slots: int | None = None,
    repo_root: object | None = None,
) -> PilotResidualTriggerMap:
    """Project the sealed residual catalog into a pilot trigger map.

    When ``catalog`` is omitted, the checked-in plateau residual catalog is
    loaded.  Optional ``baseline_ir_by_case`` re-validates missing slots and
    policy bounds against live L1s.
    """

    del repo_root  # reserved for path overrides; catalog loader uses default
    payload = (
        dict(catalog)
        if catalog is not None
        else load_plateau_residual_catalog()
    )
    resolved_policy = policy if policy is not None else SelectiveRepairPolicy()
    bound = (
        int(max_repair_slots)
        if max_repair_slots is not None
        else int(resolved_policy.max_repair_slots)
    )
    baselines = dict(baseline_ir_by_case or {})
    case_records: list[PilotCaseTriggerRecord] = []
    for item in payload.get("cases", ()):
        case = CaseResidualRecord.from_dict(item)
        baseline = baselines.get(case.case_id)
        case_records.append(
            project_case_trigger_record(
                case,
                baseline_ir=baseline,
                policy=resolved_policy,
                max_repair_slots=bound,
            )
        )

    # Stable pilot order when present; otherwise preserve catalog order.
    order = {case_id: index for index, case_id in enumerate(PILOT_CASE_IDS)}
    case_records.sort(key=lambda record: order.get(record.case_id, 10_000))

    catalog_cid = payload.get("catalog_cid")
    return PilotResidualTriggerMap(
        cases=tuple(case_records),
        catalog_cid=str(catalog_cid) if catalog_cid else None,
        policy_digest=resolved_policy.digest,
        max_repair_slots=bound,
        production_arm_id=str(
            payload.get("baseline", {}).get("arm_id", PRODUCTION_NO_REPAIR_ARM_ID)
            if isinstance(payload.get("baseline"), Mapping)
            else PRODUCTION_NO_REPAIR_ARM_ID
        ),
    )


def validate_pilot_trigger_coverage(
    trigger_map: PilotResidualTriggerMap,
    *,
    min_nonzero_with_triggers: int = MIN_NONZERO_PILOTS_WITH_TRIGGERS,
) -> PilotResidualTriggerMap:
    """Fail closed when residual→trigger coverage is below acceptance."""

    if min_nonzero_with_triggers < 1:
        raise PilotResidualTriggerError(
            "min_nonzero_with_triggers must be positive"
        )
    control = trigger_map.by_case_id().get(ZERO_RESIDUAL_CONTROL_CASE_ID)
    if control is not None and control.has_trigger:
        raise PilotResidualTriggerError(
            "zero-residual control must not emit triggers"
        )
    if trigger_map.triggered_nonzero_pilot_count < min_nonzero_with_triggers:
        raise PilotResidualTriggerError(
            "pilot residual trigger coverage "
            f"{trigger_map.triggered_nonzero_pilot_count}/"
            f"{len(NONZERO_PILOT_CASE_IDS)} is below the acceptance floor "
            f"{min_nonzero_with_triggers}; "
            f"triggered={list(trigger_map.nonzero_case_ids_with_triggers)}"
        )
    if "no_repair" not in trigger_map.production_arm_id:
        raise PilotResidualTriggerError(
            "production arm must remain the no-repair deterministic path"
        )
    return trigger_map


def build_validated_pilot_residual_trigger_map(
    catalog: Mapping[str, object] | None = None,
    *,
    baseline_ir_by_case: Mapping[str, CanonicalRuleIR] | None = None,
    policy: SelectiveRepairPolicy | None = None,
    max_repair_slots: int | None = None,
) -> PilotResidualTriggerMap:
    """Project the catalog and enforce PLAT-030 coverage acceptance."""

    return validate_pilot_trigger_coverage(
        project_pilot_residual_trigger_map(
            catalog,
            baseline_ir_by_case=baseline_ir_by_case,
            policy=policy,
            max_repair_slots=max_repair_slots,
        )
    )


def untriggered_fields_preserved(
    baseline_ir: CanonicalRuleIR,
    candidate_ir: CanonicalRuleIR,
    triggers: Sequence[RepairTrigger],
) -> bool:
    """Return True when every field change lies inside the trigger set.

    This is the structural invariant selective repair enforces via
    ``only_triggered_fields_changed`` / ``untriggered_projection_preserved``.
    """

    if not isinstance(baseline_ir, CanonicalRuleIR):
        raise PilotResidualTriggerError("baseline_ir must be CanonicalRuleIR")
    if not isinstance(candidate_ir, CanonicalRuleIR):
        raise PilotResidualTriggerError("candidate_ir must be CanonicalRuleIR")
    if len(baseline_ir.rules) != len(candidate_ir.rules):
        return False

    allowed = {item.path for item in triggers}
    for rule_index, (left, right) in enumerate(
        zip(baseline_ir.rules, candidate_ir.rules)
    ):
        for field in RULE_FIELDS:
            if getattr(left, field) != getattr(right, field):
                path = f"rules[{rule_index}].{field}"
                if path not in allowed:
                    return False
    return True


class PilotResidualTriggerDetector:
    """``RepairTriggerDetector`` bound to a fixed residual-derived trigger set.

    Bind one detector per pilot case (or use
    :class:`CatalogPilotResidualTriggerDetector` for multi-case lookup).
    Explicit opt-in only — never the production constructor default.
    """

    identity: Final = PILOT_RESIDUAL_TRIGGER_DETECTOR_INTERFACE

    def __init__(
        self,
        triggers: Sequence[RepairTrigger],
        *,
        case_id: str | None = None,
        policy: SelectiveRepairPolicy | None = None,
    ) -> None:
        normalized = tuple(
            item
            if isinstance(item, RepairTrigger)
            else RepairTrigger(
                rule_index=int(item["rule_index"]),  # type: ignore[index]
                canonical_field=str(item["canonical_field"]),  # type: ignore[index]
                kind=RepairTriggerKind(item["kind"]),  # type: ignore[index]
                confidence=item.get("confidence"),  # type: ignore[union-attr]
                evidence=item.get("evidence"),  # type: ignore[union-attr]
            )
            for item in triggers
        )
        if not all(isinstance(item, RepairTrigger) for item in normalized):
            raise PilotResidualTriggerError(
                "detector triggers must be RepairTrigger records"
            )
        self._triggers = normalized
        self._case_id = (
            _nonblank(case_id, "case_id") if case_id is not None else None
        )
        self._policy = (
            policy if policy is not None else SelectiveRepairPolicy()
        )

    @property
    def case_id(self) -> str | None:
        return self._case_id

    @property
    def triggers(self) -> tuple[RepairTrigger, ...]:
        return self._triggers

    def detect(
        self,
        request: ConstructorRequest,
        baseline_ir: CanonicalRuleIR,
    ) -> tuple[RepairTrigger, ...]:
        del request
        if not self._triggers:
            return ()
        return self._policy.validate_triggers(baseline_ir, self._triggers)


class CatalogPilotResidualTriggerDetector:
    """Multi-case detector that looks up residual triggers by ``case_id``.

    Resolution order for the case identity:

    1. ``request.config['case_id']`` when present
    2. Constructor ``case_id`` bound at init (single-case mode)
    3. Empty triggers (fail closed / no repair) when unresolved
    """

    identity: Final = (
        "CatalogPilotResidualTriggerDetector@1"
    )

    def __init__(
        self,
        trigger_map: PilotResidualTriggerMap | Mapping[str, Sequence[RepairTrigger]],
        *,
        default_case_id: str | None = None,
        policy: SelectiveRepairPolicy | None = None,
    ) -> None:
        if isinstance(trigger_map, PilotResidualTriggerMap):
            mapping = {
                case_id: record.triggers
                for case_id, record in trigger_map.by_case_id().items()
            }
        else:
            mapping = {
                str(case_id): tuple(
                    item
                    if isinstance(item, RepairTrigger)
                    else RepairTrigger(
                        rule_index=int(item["rule_index"]),  # type: ignore[index]
                        canonical_field=str(item["canonical_field"]),  # type: ignore[index]
                        kind=RepairTriggerKind(item["kind"]),  # type: ignore[index]
                        confidence=item.get("confidence"),  # type: ignore[union-attr]
                        evidence=item.get("evidence"),  # type: ignore[union-attr]
                    )
                    for item in triggers
                )
                for case_id, triggers in dict(trigger_map).items()
            }
        self._by_case = MappingProxyType(mapping)
        self._default_case_id = (
            _nonblank(default_case_id, "default_case_id")
            if default_case_id is not None
            else None
        )
        self._policy = (
            policy if policy is not None else SelectiveRepairPolicy()
        )

    def detect(
        self,
        request: ConstructorRequest,
        baseline_ir: CanonicalRuleIR,
    ) -> tuple[RepairTrigger, ...]:
        case_id: str | None = None
        config = getattr(request, "config", {}) or {}
        if isinstance(config, Mapping):
            raw = config.get("case_id")
            if isinstance(raw, str) and raw.strip():
                case_id = raw.strip()
        if case_id is None:
            case_id = self._default_case_id
        if case_id is None or case_id not in self._by_case:
            return ()
        triggers = self._by_case[case_id]
        if not triggers:
            return ()
        return self._policy.validate_triggers(baseline_ir, triggers)


def production_path_is_no_repair(arm_id: str | None = None) -> bool:
    """True when the production arm id is the sealed no-repair baseline."""

    target = arm_id if arm_id is not None else PRODUCTION_NO_REPAIR_ARM_ID
    return (
        isinstance(target, str)
        and "no_repair" in target
        and target == PRODUCTION_NO_REPAIR_ARM_ID
    )


__all__ = [
    "MIN_NONZERO_PILOTS_WITH_TRIGGERS",
    "PILOT_RESIDUAL_TRIGGER_DETECTOR_INTERFACE",
    "PILOT_RESIDUAL_TRIGGER_MAP_INTERFACE",
    "PILOT_RESIDUAL_TRIGGERS_INTERFACE",
    "PILOT_RESIDUAL_TRIGGERS_SCHEMA",
    "PRODUCTION_NO_REPAIR_ARM_ID",
    "CatalogPilotResidualTriggerDetector",
    "PilotCaseTriggerRecord",
    "PilotResidualTriggerDetector",
    "PilotResidualTriggerError",
    "PilotResidualTriggerMap",
    "build_validated_pilot_residual_trigger_map",
    "is_slot_empty",
    "production_path_is_no_repair",
    "project_case_trigger_record",
    "project_pilot_residual_trigger_map",
    "residual_facet_is_projectable",
    "trigger_from_residual_facet",
    "triggers_from_case_residual",
    "triggers_from_residual_facets",
    "untriggered_fields_preserved",
    "validate_pilot_trigger_coverage",
]
