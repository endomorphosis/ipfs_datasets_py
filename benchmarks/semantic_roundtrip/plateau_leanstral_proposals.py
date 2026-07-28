"""Leanstral selective proposal teacher for plateau-break (PLAT-040).

Interface: ``PlateauLeanstralProposals@1``

Offline teacher pipeline (never a production realizer):

```text
residual / fixture triggers
        │
        ▼
Leanstral (± dry-run fixtures) selective IR patch
  • change only triggered fields
  • retain prior L1 on model failure / reject
        │
        ▼
StructuralAdmissionGate  (Hammer/cvc5 / Lean / local constraints)
  admit | reject | timeout | error  (fail-closed)
        │
        ▼
PlateauCodexPacket@1
  implementable=true only after admission accepts
```

Acceptance contract (PLAT-040 / PLAT-G040):

* Dry-run fixtures pass without a live model.
* Live path records ``accept_rate`` and ``retry_exhausted`` separately from e2e.
* Only triggered fields may change.
* ``StructuralAdmissionGate`` is applied before ``implementable=true``.
* Rejects leave prior L1 unchanged; Leanstral is never the default realizer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.semantic_roundtrip.constructors.autoencoder_guided import (
    CanonicalFieldChange,
    canonical_field_changes,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    CompletionClient,
    LeanstralClient,
    LeanstralClientError,
    LeanstralTimeoutError,
    LeanstralUnavailableError,
)
from benchmarks.semantic_roundtrip.contracts import (
    LIST_FIELDS,
    RULE_FIELDS,
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ContractError,
    FailureReason,
)
from benchmarks.semantic_roundtrip.evaluation_status import (
    DEFAULT_DETERMINISTIC_BASELINE_ARM_ID,
)
from benchmarks.semantic_roundtrip.plateau_codex_packet import (
    DEFAULT_BASELINE_E2E,
    DEFAULT_PREDICTED_FILES,
    DEFAULT_VALIDATION_COMMANDS,
    PlateauCodexPacket,
    ResidualRef,
    TeacherProposal,
    baseline_l1_digest,
    build_packet_from_proposal_admission,
)
from benchmarks.semantic_roundtrip.pilot_residual_triggers import (
    untriggered_fields_preserved,
)
from benchmarks.semantic_roundtrip.selective_repair import (
    DECLARED_STRUCTURAL_CONSTRAINTS,
    DEFAULT_CANDIDATE_COUNT,
    DEFAULT_MAX_REPAIR_SLOTS,
    RepairAttemptStatus,
    RepairTrigger,
    RepairTriggerKind,
    SelectiveLeanstralRepair,
    SelectiveRepairPolicy,
    StructuralTool,
)
from benchmarks.semantic_roundtrip.structural_admission import (
    AdmissionDisposition,
    StructuralAdmissionGate,
    StructuralAdmissionPolicy,
    StructuralAdmissionResult,
    admit_hybrid_repair,
)


PLATEAU_LEANSTRAL_PROPOSALS_INTERFACE: Final = "PlateauLeanstralProposals@1"
PLATEAU_LEANSTRAL_PROPOSAL_RECEIPT_INTERFACE: Final = (
    "PlateauLeanstralProposalCaseReceipt@1"
)
PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_INTERFACE: Final = (
    "PlateauLeanstralProposalReceipts@1"
)
PLATEAU_LEANSTRAL_PROPOSALS_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau-leanstral-proposals.v1"
)
PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-plateau-leanstral-proposal-receipts.v1"
)
PLATEAU_LEANSTRAL_PROPOSALS_EVIDENCE: Final = "PLATEV040LLM"
PLATEAU_BREAK_TASK_ID: Final = "PLAT-040"
PLATEAU_BREAK_BOARD_NAMESPACE: Final = "semantic-roundtrip-plateau-break-v1"
TEACHER_IDENTITY: Final = "leanstral"
PROVIDER_ID: Final = "leanstral-local"
DRY_RUN_FIXTURE_PACK_ID: Final = "plateau-leanstral-proposal-dry-run-fixtures@1"

DEFAULT_RECEIPTS_RELATIVE_PATH: Final = Path(
    "workspace/benchmarks/semantic-roundtrip-compositions/"
    "plateau_leanstral_proposal_receipts.json"
)

DEFAULT_BASELINE_ARM_ID: Final = DEFAULT_DETERMINISTIC_BASELINE_ARM_ID
DEFAULT_PRODUCTION_REALIZER: Final = "deterministic"
RECEIPTS_CID_SCOPE: Final = "payload_without_receipts_cid"
RECEIPTS_CID_CODEC: Final = "dag-json"

ACCEPT_RATE_DEFINITION: Final = (
    "accept_rate = accepted_proposals / proposal_attempts "
    "(triggered cases only; not end-to-end semantic loss)"
)
RETRY_EXHAUSTED_RATE_DEFINITION: Final = (
    "retry_exhausted_rate = retry_exhausted_proposals / proposal_attempts "
    "(triggered cases only; recorded separately from accept_rate and e2e)"
)


class PlateauLeanstralProposalError(ContractError):
    """Contract violation in the Leanstral selective proposal teacher."""


class ProposalMode(str, Enum):
    """Whether the teacher uses fixtures or a live Leanstral client."""

    DRY_RUN = "dry_run"
    LIVE = "live"


class ProposalOutcome(str, Enum):
    """Terminal outcome of one teacher proposal attempt."""

    NOT_TRIGGERED = "not_triggered"
    ACCEPTED = "accepted"
    ADMISSION_REJECTED = "admission_rejected"
    MODEL_REJECTED = "model_rejected"
    RETRY_EXHAUSTED = "retry_exhausted"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _detail(value: object, fallback: str) -> str:
    text = " ".join(str(value or fallback).split())
    return (text or fallback)[:1000]


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlateauLeanstralProposalError(f"{field} must be a nonblank string")
    return value.strip()


def _finite_unit(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise PlateauLeanstralProposalError(
            f"{field} must be a finite number from zero to one"
        )
    return float(value)


def _nonneg_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PlateauLeanstralProposalError(
            f"{field} must be a nonnegative integer"
        )
    return value


def trigger_paths(triggers: Sequence[RepairTrigger]) -> tuple[str, ...]:
    """Stable ordered allowed field paths from repair triggers."""

    paths: list[str] = []
    seen: set[str] = set()
    for item in triggers:
        if not isinstance(item, RepairTrigger):
            raise PlateauLeanstralProposalError(
                "triggers must be RepairTrigger records"
            )
        if item.path not in seen:
            seen.add(item.path)
            paths.append(item.path)
    return tuple(paths)


def apply_field_patch(
    baseline_l1: CanonicalRuleIR,
    *,
    rule_index: int,
    canonical_field: str,
    value: object,
) -> CanonicalRuleIR:
    """Return a copy of *baseline_l1* with one rule field replaced."""

    if not isinstance(baseline_l1, CanonicalRuleIR):
        raise PlateauLeanstralProposalError(
            "baseline_l1 must be CanonicalRuleIR"
        )
    if canonical_field not in RULE_FIELDS:
        raise PlateauLeanstralProposalError(
            f"unknown canonical field: {canonical_field!r}"
        )
    if (
        isinstance(rule_index, bool)
        or not isinstance(rule_index, int)
        or rule_index < 0
        or rule_index >= len(baseline_l1.rules)
    ):
        raise PlateauLeanstralProposalError(
            f"rule_index out of range: {rule_index!r}"
        )

    if canonical_field in LIST_FIELDS:
        if value is None:
            normalized: object = ()
        elif isinstance(value, str):
            normalized = (value,) if value else ()
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            normalized = tuple(str(item) for item in value)
        else:
            raise PlateauLeanstralProposalError(
                f"list field {canonical_field!r} requires a sequence"
            )
    else:
        if value is None:
            normalized = ""
        elif isinstance(value, str):
            normalized = value
        else:
            normalized = str(value)

    rules = list(baseline_l1.rules)
    rules[rule_index] = replace(
        rules[rule_index], **{canonical_field: normalized}
    )
    return CanonicalRuleIR(tuple(rules))


def apply_trigger_patches(
    baseline_l1: CanonicalRuleIR,
    patches: Mapping[str, object] | Sequence[tuple[RepairTrigger, object]],
) -> CanonicalRuleIR:
    """Apply path→value patches, restricted to triggered slots when keys are paths."""

    if not isinstance(baseline_l1, CanonicalRuleIR):
        raise PlateauLeanstralProposalError(
            "baseline_l1 must be CanonicalRuleIR"
        )
    candidate = baseline_l1
    if isinstance(patches, Mapping):
        items = list(patches.items())
        for path, value in items:
            path_s = _nonblank(path, "patch path")
            if not path_s.startswith("rules[") or "]." not in path_s:
                raise PlateauLeanstralProposalError(
                    f"patch path has invalid shape: {path_s!r}"
                )
            head, field = path_s.split("].", 1)
            index_text = head[len("rules[") :]
            try:
                rule_index = int(index_text)
            except ValueError as exc:
                raise PlateauLeanstralProposalError(
                    f"patch path has invalid rule index: {path_s!r}"
                ) from exc
            candidate = apply_field_patch(
                candidate,
                rule_index=rule_index,
                canonical_field=field,
                value=value,
            )
        return candidate

    if isinstance(patches, Sequence) and not isinstance(
        patches, (str, bytes, bytearray)
    ):
        for item in patches:
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes, bytearray))
                or len(item) != 2
            ):
                raise PlateauLeanstralProposalError(
                    "patch pairs must be (RepairTrigger, value)"
                )
            trigger, value = item
            if not isinstance(trigger, RepairTrigger):
                raise PlateauLeanstralProposalError(
                    "patch trigger must be RepairTrigger"
                )
            candidate = apply_field_patch(
                candidate,
                rule_index=trigger.rule_index,
                canonical_field=trigger.canonical_field,
                value=value,
            )
        return candidate

    raise PlateauLeanstralProposalError("patches must be a mapping or sequence")


def only_triggered_fields_changed(
    baseline_l1: CanonicalRuleIR,
    candidate_l1: CanonicalRuleIR,
    triggers: Sequence[RepairTrigger],
) -> bool:
    """Structural invariant: candidate may differ only on trigger paths."""

    return untriggered_fields_preserved(baseline_l1, candidate_l1, triggers)


@dataclass(frozen=True, slots=True)
class DryRunFixtureCase:
    """One offline fixture used to exercise the teacher without a live model."""

    case_id: str
    baseline_l1: CanonicalRuleIR
    triggers: tuple[RepairTrigger, ...]
    candidate_l1: CanonicalRuleIR | None
    expected_outcome: ProposalOutcome
    residual_field_paths: tuple[str, ...] = ()
    detail: str | None = None
    force_retry_exhausted: bool = False
    source_text: str = "Fixture source text for plateau Leanstral proposals."
    vocabulary: AllowedAtomVocabulary | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "case_id", _nonblank(self.case_id, "case_id")
        )
        if not isinstance(self.baseline_l1, CanonicalRuleIR):
            raise PlateauLeanstralProposalError(
                "baseline_l1 must be CanonicalRuleIR"
            )
        object.__setattr__(self, "triggers", tuple(self.triggers))
        if not all(isinstance(item, RepairTrigger) for item in self.triggers):
            raise PlateauLeanstralProposalError(
                "triggers must be RepairTrigger records"
            )
        if self.candidate_l1 is not None and not isinstance(
            self.candidate_l1, CanonicalRuleIR
        ):
            raise PlateauLeanstralProposalError(
                "candidate_l1 must be CanonicalRuleIR or None"
            )
        if not isinstance(self.expected_outcome, ProposalOutcome):
            try:
                object.__setattr__(
                    self,
                    "expected_outcome",
                    ProposalOutcome(self.expected_outcome),
                )
            except (TypeError, ValueError) as exc:
                raise PlateauLeanstralProposalError(
                    "expected_outcome is invalid"
                ) from exc
        object.__setattr__(
            self,
            "residual_field_paths",
            tuple(
                _nonblank(item, "residual_field_paths item")
                for item in self.residual_field_paths
            )
            or trigger_paths(self.triggers),
        )
        if self.detail is not None:
            object.__setattr__(
                self, "detail", _detail(self.detail, "fixture detail")
            )
        if not isinstance(self.force_retry_exhausted, bool):
            raise PlateauLeanstralProposalError(
                "force_retry_exhausted must be boolean"
            )
        object.__setattr__(
            self,
            "source_text",
            _nonblank(self.source_text, "source_text"),
        )
        if self.vocabulary is not None and not isinstance(
            self.vocabulary, AllowedAtomVocabulary
        ):
            raise PlateauLeanstralProposalError(
                "vocabulary must be AllowedAtomVocabulary or None"
            )

    @property
    def allowed_field_paths(self) -> tuple[str, ...]:
        return trigger_paths(self.triggers)

    def constructor_request(self) -> ConstructorRequest:
        vocab = self.vocabulary or AllowedAtomVocabulary(
            actors=("controller", "processor", "agency"),
            actions=("delete", "retain", "file", "publish"),
            objects=("records", "notice", "report"),
            qualifiers=("after_30_days", "within_24_hours", "annually"),
        )
        return ConstructorRequest(
            self.source_text,
            vocab,
            {"case_id": self.case_id, "dry_run": True},
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed_field_paths": list(self.allowed_field_paths),
            "baseline_l1": self.baseline_l1.to_dict(),
            "candidate_l1": (
                None
                if self.candidate_l1 is None
                else self.candidate_l1.to_dict()
            ),
            "case_id": self.case_id,
            "detail": self.detail,
            "expected_outcome": self.expected_outcome.value,
            "force_retry_exhausted": self.force_retry_exhausted,
            "residual_field_paths": list(self.residual_field_paths),
            "source_text": self.source_text,
            "triggers": [item.to_dict() for item in self.triggers],
            "vocabulary": (
                None
                if self.vocabulary is None
                else self.vocabulary.to_dict()
            ),
        }


def dry_run_fixture_pack() -> tuple[DryRunFixtureCase, ...]:
    """Offline fixtures proving admission gating without a live Leanstral model.

    Cases cover:

    * accepted selective fill (only triggered field changes);
    * admission reject when an untriggered field changes (prior L1 retained);
    * retry_exhausted without a candidate;
    * not_triggered control (empty triggers).
    """

    baseline = CanonicalRuleIR(
        (
            CanonicalRule(
                modality="O",
                actor="controller",
                action="delete",
                object="",
                conditions=(),
                exceptions=(),
                temporal=(),
            ),
            CanonicalRule(
                modality="O",
                actor="processor",
                action="retain",
                object="records",
                conditions=("active_hold",),
                exceptions=(),
                temporal=("until_released",),
            ),
        )
    )
    object_trigger = RepairTrigger(
        rule_index=0,
        canonical_field="object",
        kind=RepairTriggerKind.MISSING,
        evidence="fixture: rules[0].object is empty on baseline L1",
    )
    accepted_candidate = apply_field_patch(
        baseline,
        rule_index=0,
        canonical_field="object",
        value="records",
    )
    # Illegal candidate: also mutates an untriggered rule field.
    illegal_candidate = apply_field_patch(
        accepted_candidate,
        rule_index=1,
        canonical_field="actor",
        value="controller",
    )

    return (
        DryRunFixtureCase(
            case_id="fixture_accept_missing_object",
            baseline_l1=baseline,
            triggers=(object_trigger,),
            candidate_l1=accepted_candidate,
            expected_outcome=ProposalOutcome.ACCEPTED,
            residual_field_paths=("rules[0].object",),
            detail="dry-run selective object fill within trigger set",
        ),
        DryRunFixtureCase(
            case_id="fixture_admission_reject_untriggered",
            baseline_l1=baseline,
            triggers=(object_trigger,),
            candidate_l1=illegal_candidate,
            expected_outcome=ProposalOutcome.ADMISSION_REJECTED,
            residual_field_paths=("rules[0].object",),
            detail=(
                "dry-run candidate changes untriggered field; gate retains prior L1"
            ),
        ),
        DryRunFixtureCase(
            case_id="fixture_retry_exhausted",
            baseline_l1=baseline,
            triggers=(object_trigger,),
            candidate_l1=None,
            expected_outcome=ProposalOutcome.RETRY_EXHAUSTED,
            residual_field_paths=("rules[0].object",),
            force_retry_exhausted=True,
            detail="dry-run live-path analogue: all model calls failed",
        ),
        DryRunFixtureCase(
            case_id="fixture_not_triggered",
            baseline_l1=baseline,
            triggers=(),
            candidate_l1=None,
            expected_outcome=ProposalOutcome.NOT_TRIGGERED,
            residual_field_paths=(),
            detail="dry-run control: empty triggers emit no proposal",
        ),
    )


@dataclass(frozen=True, slots=True)
class ProposalReliabilityMetrics:
    """Model/teacher reliability rates, separate from end-to-end semantic loss.

    ``accept_rate`` and ``retry_exhausted_rate`` are recorded independently.
    Neither field is an e2e loss substitute (``end_to_end_loss`` is always
    null on this receipt surface).
    """

    proposal_attempts: int
    accepted_proposals: int
    retry_exhausted_proposals: int
    admission_rejected_proposals: int
    model_rejected_proposals: int
    not_triggered: int
    failed_proposals: int
    model_calls: int

    def __post_init__(self) -> None:
        for name in (
            "proposal_attempts",
            "accepted_proposals",
            "retry_exhausted_proposals",
            "admission_rejected_proposals",
            "model_rejected_proposals",
            "not_triggered",
            "failed_proposals",
            "model_calls",
        ):
            object.__setattr__(
                self, name, _nonneg_int(getattr(self, name), name)
            )
        if self.accepted_proposals > self.proposal_attempts:
            raise PlateauLeanstralProposalError(
                "accepted_proposals exceeds proposal_attempts"
            )
        if self.retry_exhausted_proposals > self.proposal_attempts:
            raise PlateauLeanstralProposalError(
                "retry_exhausted_proposals exceeds proposal_attempts"
            )

    @property
    def accept_rate(self) -> float | None:
        if self.proposal_attempts == 0:
            return None
        return self.accepted_proposals / self.proposal_attempts

    @property
    def retry_exhausted_rate(self) -> float | None:
        if self.proposal_attempts == 0:
            return None
        return self.retry_exhausted_proposals / self.proposal_attempts

    def to_dict(self) -> dict[str, object]:
        return {
            "accept_rate": self.accept_rate,
            "accept_rate_definition": ACCEPT_RATE_DEFINITION,
            "accepted_proposals": self.accepted_proposals,
            "admission_rejected_proposals": self.admission_rejected_proposals,
            "end_to_end_loss": None,
            "failed_proposals": self.failed_proposals,
            "model_calls": self.model_calls,
            "model_rejected_proposals": self.model_rejected_proposals,
            "not_triggered": self.not_triggered,
            "proposal_attempts": self.proposal_attempts,
            "retry_exhausted_proposals": self.retry_exhausted_proposals,
            "retry_exhausted_rate": self.retry_exhausted_rate,
            "retry_exhausted_rate_definition": RETRY_EXHAUSTED_RATE_DEFINITION,
            "separate_from_end_to_end_loss": True,
        }


def aggregate_proposal_reliability(
    receipts: Sequence["LeanstralProposalCaseReceipt"],
) -> ProposalReliabilityMetrics:
    """Aggregate accept / retry_exhausted rates across case receipts."""

    if not isinstance(receipts, Sequence) or isinstance(
        receipts, (str, bytes, bytearray)
    ):
        raise PlateauLeanstralProposalError(
            "receipts must be a sequence of case receipts"
        )

    attempts = 0
    accepted = 0
    retry_exhausted = 0
    admission_rejected = 0
    model_rejected = 0
    not_triggered = 0
    failed = 0
    model_calls = 0

    for item in receipts:
        if not isinstance(item, LeanstralProposalCaseReceipt):
            raise PlateauLeanstralProposalError(
                "receipts must contain LeanstralProposalCaseReceipt records"
            )
        model_calls += int(item.model_calls)
        if item.outcome is ProposalOutcome.NOT_TRIGGERED:
            not_triggered += 1
            continue
        # Triggered proposal attempts enter the reliability denominator.
        attempts += 1
        if item.outcome is ProposalOutcome.ACCEPTED:
            accepted += 1
        elif item.outcome is ProposalOutcome.RETRY_EXHAUSTED:
            retry_exhausted += 1
        elif item.outcome is ProposalOutcome.ADMISSION_REJECTED:
            admission_rejected += 1
        elif item.outcome is ProposalOutcome.MODEL_REJECTED:
            model_rejected += 1
        elif item.outcome is ProposalOutcome.FAILED:
            failed += 1
        elif item.outcome is ProposalOutcome.NOT_APPLICABLE:
            # Identity candidates after triggers still count as attempts
            # but are neither accept nor retry_exhausted.
            pass

    return ProposalReliabilityMetrics(
        proposal_attempts=attempts,
        accepted_proposals=accepted,
        retry_exhausted_proposals=retry_exhausted,
        admission_rejected_proposals=admission_rejected,
        model_rejected_proposals=model_rejected,
        not_triggered=not_triggered,
        failed_proposals=failed,
        model_calls=model_calls,
    )


@dataclass(frozen=True, slots=True)
class LeanstralProposalCaseReceipt:
    """Per-case teacher proposal + admission receipt."""

    case_id: str
    outcome: ProposalOutcome
    mode: ProposalMode
    baseline_l1_digest: str
    admitted_l1_digest: str
    prior_l1_unchanged: bool
    only_triggered_fields_changed: bool
    implementable: bool
    admission_disposition: str | None
    triggers: tuple[RepairTrigger, ...]
    allowed_field_paths: tuple[str, ...]
    field_changes: tuple[CanonicalFieldChange, ...] = ()
    proposal_id: str | None = None
    packet_id: str | None = None
    packet_digest: str | None = None
    residual_ref_id: str | None = None
    model_calls: int = 0
    retry_exhausted: bool = False
    semantic_authority: bool = False
    detail: str | None = None
    candidate_l1: CanonicalRuleIR | None = None
    admitted_l1: CanonicalRuleIR | None = None
    packet: PlateauCodexPacket | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "case_id", _nonblank(self.case_id, "case_id")
        )
        if not isinstance(self.outcome, ProposalOutcome):
            try:
                object.__setattr__(
                    self, "outcome", ProposalOutcome(self.outcome)
                )
            except (TypeError, ValueError) as exc:
                raise PlateauLeanstralProposalError(
                    "outcome is invalid"
                ) from exc
        if not isinstance(self.mode, ProposalMode):
            try:
                object.__setattr__(self, "mode", ProposalMode(self.mode))
            except (TypeError, ValueError) as exc:
                raise PlateauLeanstralProposalError("mode is invalid") from exc
        object.__setattr__(
            self,
            "baseline_l1_digest",
            _nonblank(self.baseline_l1_digest, "baseline_l1_digest"),
        )
        object.__setattr__(
            self,
            "admitted_l1_digest",
            _nonblank(self.admitted_l1_digest, "admitted_l1_digest"),
        )
        for name in (
            "prior_l1_unchanged",
            "only_triggered_fields_changed",
            "implementable",
            "retry_exhausted",
        ):
            if not isinstance(getattr(self, name), bool):
                raise PlateauLeanstralProposalError(f"{name} must be boolean")
        if self.semantic_authority is not False:
            raise PlateauLeanstralProposalError(
                "teacher receipts cannot claim semantic authority"
            )
        object.__setattr__(self, "triggers", tuple(self.triggers))
        object.__setattr__(
            self, "allowed_field_paths", tuple(self.allowed_field_paths)
        )
        object.__setattr__(self, "field_changes", tuple(self.field_changes))
        object.__setattr__(
            self, "model_calls", _nonneg_int(self.model_calls, "model_calls")
        )
        if self.admission_disposition is not None:
            object.__setattr__(
                self,
                "admission_disposition",
                _nonblank(
                    self.admission_disposition, "admission_disposition"
                ),
            )
        for optional in (
            "proposal_id",
            "packet_id",
            "packet_digest",
            "residual_ref_id",
            "detail",
        ):
            value = getattr(self, optional)
            if value is not None:
                object.__setattr__(
                    self, optional, _nonblank(value, optional)
                )

        # Fail-closed implementable consistency.
        if self.implementable:
            if self.outcome is not ProposalOutcome.ACCEPTED:
                raise PlateauLeanstralProposalError(
                    "implementable=true requires outcome=accepted"
                )
            if self.admission_disposition != AdmissionDisposition.ACCEPTED.value:
                raise PlateauLeanstralProposalError(
                    "implementable=true requires StructuralAdmissionGate accept"
                )
            if self.prior_l1_unchanged:
                raise PlateauLeanstralProposalError(
                    "implementable=true cannot retain prior L1 unchanged"
                )
            if not self.only_triggered_fields_changed:
                raise PlateauLeanstralProposalError(
                    "implementable=true requires only triggered fields changed"
                )
            if self.retry_exhausted:
                raise PlateauLeanstralProposalError(
                    "implementable=true cannot be retry_exhausted"
                )
        if self.retry_exhausted and self.outcome is not (
            ProposalOutcome.RETRY_EXHAUSTED
        ):
            raise PlateauLeanstralProposalError(
                "retry_exhausted flag requires outcome=retry_exhausted"
            )
        if (
            self.outcome is ProposalOutcome.RETRY_EXHAUSTED
            and not self.retry_exhausted
        ):
            raise PlateauLeanstralProposalError(
                "outcome=retry_exhausted requires retry_exhausted=true"
            )
        if self.outcome is ProposalOutcome.ADMISSION_REJECTED:
            if not self.prior_l1_unchanged:
                raise PlateauLeanstralProposalError(
                    "admission reject must retain prior L1"
                )
            if self.implementable:
                raise PlateauLeanstralProposalError(
                    "admission reject cannot be implementable"
                )
        if self.packet is not None:
            if self.packet.implementable != self.implementable:
                raise PlateauLeanstralProposalError(
                    "packet.implementable must match case receipt"
                )
            packet_payload = self.packet.to_dict()
            if packet_payload.get("semantic_authority") is not False:
                raise PlateauLeanstralProposalError(
                    "packet cannot claim semantic authority"
                )
            for proposal in self.packet.proposals:
                if proposal.semantic_authority is not False:
                    raise PlateauLeanstralProposalError(
                        "packet proposal cannot claim semantic authority"
                    )
            for receipt in self.packet.admission_receipts:
                if receipt.semantic_authority is not False:
                    raise PlateauLeanstralProposalError(
                        "packet admission cannot claim semantic authority"
                    )

    def to_dict(self) -> dict[str, object]:
        return {
            "admission_disposition": self.admission_disposition,
            "admitted_l1": (
                None
                if self.admitted_l1 is None
                else self.admitted_l1.to_dict()
            ),
            "admitted_l1_digest": self.admitted_l1_digest,
            "allowed_field_paths": list(self.allowed_field_paths),
            "baseline_l1_digest": self.baseline_l1_digest,
            "candidate_l1": (
                None
                if self.candidate_l1 is None
                else self.candidate_l1.to_dict()
            ),
            "case_id": self.case_id,
            "detail": self.detail,
            "field_changes": [item.to_dict() for item in self.field_changes],
            "implementable": self.implementable,
            "interface": PLATEAU_LEANSTRAL_PROPOSAL_RECEIPT_INTERFACE,
            "mode": self.mode.value,
            "model_calls": self.model_calls,
            "only_triggered_fields_changed": (
                self.only_triggered_fields_changed
            ),
            "outcome": self.outcome.value,
            "packet_digest": self.packet_digest,
            "packet_id": self.packet_id,
            "prior_l1_unchanged": self.prior_l1_unchanged,
            "proposal_id": self.proposal_id,
            "residual_ref_id": self.residual_ref_id,
            "retry_exhausted": self.retry_exhausted,
            "semantic_authority": False,
            "triggers": [item.to_dict() for item in self.triggers],
        }

    @classmethod
    def from_dict(cls, value: object) -> "LeanstralProposalCaseReceipt":
        if not isinstance(value, Mapping):
            raise PlateauLeanstralProposalError(
                "case receipt must be an object"
            )
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
            for item in (value.get("triggers") or ())
        )
        raw_changes = value.get("field_changes") or ()
        changes: list[CanonicalFieldChange] = []
        for item in raw_changes:
            if isinstance(item, CanonicalFieldChange):
                changes.append(item)
            elif isinstance(item, Mapping):
                changes.append(
                    CanonicalFieldChange(
                        canonical_field=item["canonical_field"],  # type: ignore[arg-type]
                        before=item.get("before"),
                        after=item.get("after"),
                        baseline_rule_index=item.get("baseline_rule_index"),  # type: ignore[arg-type]
                        guided_rule_index=item.get("guided_rule_index"),  # type: ignore[arg-type]
                    )
                )
            else:
                raise PlateauLeanstralProposalError(
                    "field_changes items are invalid"
                )
        candidate_raw = value.get("candidate_l1")
        admitted_raw = value.get("admitted_l1")
        return cls(
            case_id=value.get("case_id"),  # type: ignore[arg-type]
            outcome=ProposalOutcome(value.get("outcome")),  # type: ignore[arg-type]
            mode=ProposalMode(value.get("mode")),  # type: ignore[arg-type]
            baseline_l1_digest=value.get("baseline_l1_digest"),  # type: ignore[arg-type]
            admitted_l1_digest=value.get("admitted_l1_digest"),  # type: ignore[arg-type]
            prior_l1_unchanged=bool(value.get("prior_l1_unchanged")),
            only_triggered_fields_changed=bool(
                value.get("only_triggered_fields_changed", True)
            ),
            implementable=bool(value.get("implementable")),
            admission_disposition=value.get("admission_disposition"),  # type: ignore[arg-type]
            triggers=triggers,
            allowed_field_paths=tuple(
                value.get("allowed_field_paths") or ()
            ),
            field_changes=tuple(changes),
            proposal_id=value.get("proposal_id"),  # type: ignore[arg-type]
            packet_id=value.get("packet_id"),  # type: ignore[arg-type]
            packet_digest=value.get("packet_digest"),  # type: ignore[arg-type]
            residual_ref_id=value.get("residual_ref_id"),  # type: ignore[arg-type]
            model_calls=int(value.get("model_calls") or 0),
            retry_exhausted=bool(value.get("retry_exhausted")),
            semantic_authority=False,
            detail=value.get("detail"),  # type: ignore[arg-type]
            candidate_l1=(
                None
                if candidate_raw is None
                else CanonicalRuleIR.from_dict(candidate_raw)
            ),
            admitted_l1=(
                None
                if admitted_raw is None
                else CanonicalRuleIR.from_dict(admitted_raw)
            ),
        )


@dataclass(frozen=True, slots=True)
class PlateauLeanstralProposalReceipts:
    """Sealed multi-case teacher proposal receipt bundle."""

    cases: tuple[LeanstralProposalCaseReceipt, ...]
    mode: ProposalMode
    reliability: ProposalReliabilityMetrics
    fixture_pack_id: str | None = DRY_RUN_FIXTURE_PACK_ID
    catalog_cid: str | None = None
    receipts_cid: str | None = None
    teacher: str = TEACHER_IDENTITY
    task_id: str = PLATEAU_BREAK_TASK_ID
    board_namespace: str = PLATEAU_BREAK_BOARD_NAMESPACE
    baseline_arm_id: str = DEFAULT_BASELINE_ARM_ID
    production_realizer: str = DEFAULT_PRODUCTION_REALIZER
    leanstral_is_default_realizer: bool = False
    production_runtime_unchanged: bool = True
    interface: str = PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_INTERFACE
    schema_version: str = PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_SCHEMA
    evidence: str = PLATEAU_LEANSTRAL_PROPOSALS_EVIDENCE
    structural_admission_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))
        if not all(
            isinstance(item, LeanstralProposalCaseReceipt)
            for item in self.cases
        ):
            raise PlateauLeanstralProposalError(
                "cases must be LeanstralProposalCaseReceipt records"
            )
        case_ids = [item.case_id for item in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise PlateauLeanstralProposalError(
                "case_ids must be unique within proposal receipts"
            )
        if not isinstance(self.mode, ProposalMode):
            try:
                object.__setattr__(self, "mode", ProposalMode(self.mode))
            except (TypeError, ValueError) as exc:
                raise PlateauLeanstralProposalError("mode is invalid") from exc
        if not isinstance(self.reliability, ProposalReliabilityMetrics):
            raise PlateauLeanstralProposalError(
                "reliability must be ProposalReliabilityMetrics"
            )
        if self.leanstral_is_default_realizer is not False:
            raise PlateauLeanstralProposalError(
                "Leanstral must never be marked as the default realizer"
            )
        if self.production_runtime_unchanged is not True:
            raise PlateauLeanstralProposalError(
                "production_runtime_unchanged must remain true for teacher path"
            )
        if self.structural_admission_required is not True:
            raise PlateauLeanstralProposalError(
                "structural admission is required before implementable=true"
            )
        object.__setattr__(
            self, "teacher", _nonblank(self.teacher, "teacher").lower()
        )
        if self.teacher != TEACHER_IDENTITY:
            raise PlateauLeanstralProposalError(
                f"teacher must be {TEACHER_IDENTITY!r}"
            )
        # Implementable cases must have gone through accepted admission.
        for item in self.cases:
            if item.implementable and (
                item.admission_disposition
                != AdmissionDisposition.ACCEPTED.value
            ):
                raise PlateauLeanstralProposalError(
                    f"{item.case_id}: implementable without admission accept"
                )

    @property
    def accept_rate(self) -> float | None:
        return self.reliability.accept_rate

    @property
    def retry_exhausted_rate(self) -> float | None:
        return self.reliability.retry_exhausted_rate

    def by_case_id(self) -> Mapping[str, LeanstralProposalCaseReceipt]:
        return MappingProxyType({item.case_id: item for item in self.cases})

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "baseline_arm_id": self.baseline_arm_id,
            "board_namespace": self.board_namespace,
            "cases": [item.to_dict() for item in self.cases],
            "catalog_cid": self.catalog_cid,
            "doctrine": {
                "accept_rate_separate_from_e2e": True,
                "leanstral_default_realizer": False,
                "only_triggered_fields_change": True,
                "production_runtime_unchanged": True,
                "rejects_retain_prior_l1": True,
                "retry_exhausted_separate_from_accept_rate": True,
                "structural_admission_before_implementable": True,
                "teacher_only": True,
            },
            "evidence": self.evidence,
            "fixture_pack_id": self.fixture_pack_id,
            "interface": self.interface,
            "leanstral_is_default_realizer": False,
            "mode": self.mode.value,
            "production_realizer": self.production_realizer,
            "production_runtime_unchanged": True,
            "provider_id": PROVIDER_ID,
            "reliability": self.reliability.to_dict(),
            "schema_version": self.schema_version,
            "structural_admission_required": True,
            "task_id": self.task_id,
            "teacher": self.teacher,
        }
        # CID is bound over the payload without itself (like residual catalog).
        if self.receipts_cid is not None:
            payload["receipts_cid"] = self.receipts_cid
            payload["receipts_cid_codec"] = RECEIPTS_CID_CODEC
            payload["receipts_cid_scope"] = RECEIPTS_CID_SCOPE
        return payload

    def with_receipts_cid(self) -> "PlateauLeanstralProposalReceipts":
        """Return a copy sealed with a content-addressed receipts CID."""

        payload = self.to_dict()
        payload.pop("receipts_cid", None)
        payload.pop("receipts_cid_codec", None)
        payload.pop("receipts_cid_scope", None)
        cid = cid_for_dag_json(payload)
        return PlateauLeanstralProposalReceipts(
            cases=self.cases,
            mode=self.mode,
            reliability=self.reliability,
            fixture_pack_id=self.fixture_pack_id,
            catalog_cid=self.catalog_cid,
            receipts_cid=cid,
            teacher=self.teacher,
            task_id=self.task_id,
            board_namespace=self.board_namespace,
            baseline_arm_id=self.baseline_arm_id,
            production_realizer=self.production_realizer,
            leanstral_is_default_realizer=False,
            production_runtime_unchanged=True,
            interface=self.interface,
            schema_version=self.schema_version,
            evidence=self.evidence,
            structural_admission_required=True,
        )


def parse_plateau_leanstral_proposal_receipts(
    value: object,
) -> PlateauLeanstralProposalReceipts:
    """Parse and validate a sealed proposal receipts payload."""

    if not isinstance(value, Mapping):
        raise PlateauLeanstralProposalError("receipts payload must be an object")
    if value.get("interface") != PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_INTERFACE:
        raise PlateauLeanstralProposalError(
            "receipts interface mismatch"
        )
    if value.get("schema_version") != PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_SCHEMA:
        raise PlateauLeanstralProposalError(
            "receipts schema_version mismatch"
        )
    if value.get("leanstral_is_default_realizer") is not False:
        raise PlateauLeanstralProposalError(
            "leanstral_is_default_realizer must be false"
        )
    cases = tuple(
        LeanstralProposalCaseReceipt.from_dict(item)
        for item in (value.get("cases") or ())
    )
    rel_raw = value.get("reliability") or {}
    if not isinstance(rel_raw, Mapping):
        raise PlateauLeanstralProposalError("reliability must be an object")
    reliability = ProposalReliabilityMetrics(
        proposal_attempts=int(rel_raw.get("proposal_attempts") or 0),
        accepted_proposals=int(rel_raw.get("accepted_proposals") or 0),
        retry_exhausted_proposals=int(
            rel_raw.get("retry_exhausted_proposals") or 0
        ),
        admission_rejected_proposals=int(
            rel_raw.get("admission_rejected_proposals") or 0
        ),
        model_rejected_proposals=int(
            rel_raw.get("model_rejected_proposals") or 0
        ),
        not_triggered=int(rel_raw.get("not_triggered") or 0),
        failed_proposals=int(rel_raw.get("failed_proposals") or 0),
        model_calls=int(rel_raw.get("model_calls") or 0),
    )
    # Recompute to ensure sealed metrics match case rows.
    recomputed = aggregate_proposal_reliability(cases)
    if (
        recomputed.proposal_attempts != reliability.proposal_attempts
        or recomputed.accepted_proposals != reliability.accepted_proposals
        or recomputed.retry_exhausted_proposals
        != reliability.retry_exhausted_proposals
    ):
        raise PlateauLeanstralProposalError(
            "reliability metrics do not match case receipts"
        )
    receipts = PlateauLeanstralProposalReceipts(
        cases=cases,
        mode=ProposalMode(value.get("mode")),  # type: ignore[arg-type]
        reliability=recomputed,
        fixture_pack_id=value.get("fixture_pack_id"),  # type: ignore[arg-type]
        catalog_cid=value.get("catalog_cid"),  # type: ignore[arg-type]
        receipts_cid=value.get("receipts_cid"),  # type: ignore[arg-type]
        teacher=str(value.get("teacher") or TEACHER_IDENTITY),
        task_id=str(value.get("task_id") or PLATEAU_BREAK_TASK_ID),
        board_namespace=str(
            value.get("board_namespace") or PLATEAU_BREAK_BOARD_NAMESPACE
        ),
        baseline_arm_id=str(
            value.get("baseline_arm_id") or DEFAULT_BASELINE_ARM_ID
        ),
        production_realizer=str(
            value.get("production_realizer") or DEFAULT_PRODUCTION_REALIZER
        ),
        leanstral_is_default_realizer=False,
        production_runtime_unchanged=True,
        evidence=str(
            value.get("evidence") or PLATEAU_LEANSTRAL_PROPOSALS_EVIDENCE
        ),
    )
    if receipts.receipts_cid is not None:
        payload = receipts.to_dict()
        payload.pop("receipts_cid", None)
        payload.pop("receipts_cid_codec", None)
        payload.pop("receipts_cid_scope", None)
        expected = cid_for_dag_json(payload)
        if receipts.receipts_cid != expected:
            raise PlateauLeanstralProposalError(
                "receipts_cid does not match payload"
            )
        validate_cid(receipts.receipts_cid, codecs=(RECEIPTS_CID_CODEC,))
    return receipts


class LeanstralSelectiveProposalTeacher:
    """Structure-bounded Leanstral proposal teacher + structural admission.

    Dry-run mode uses fixtures / injected candidate L1s and never opens a
    network client.  Live mode may call Leanstral through
    :class:`SelectiveLeanstralRepair` (or an injected client) and always
    records ``accept_rate`` / ``retry_exhausted`` separately from e2e.
    """

    interface: Final = PLATEAU_LEANSTRAL_PROPOSALS_INTERFACE
    provider_id: Final = PROVIDER_ID
    teacher: Final = TEACHER_IDENTITY

    def __init__(
        self,
        *,
        mode: ProposalMode | str = ProposalMode.DRY_RUN,
        client: CompletionClient | None = None,
        admission_gate: StructuralAdmissionGate | None = None,
        repair_policy: SelectiveRepairPolicy | None = None,
        selective_repair: SelectiveLeanstralRepair | None = None,
    ) -> None:
        if not isinstance(mode, ProposalMode):
            try:
                mode = ProposalMode(mode)
            except (TypeError, ValueError) as exc:
                raise PlateauLeanstralProposalError(
                    "mode must be dry_run or live"
                ) from exc
        self._mode = mode
        self._policy = repair_policy or SelectiveRepairPolicy()
        if not isinstance(self._policy, SelectiveRepairPolicy):
            raise PlateauLeanstralProposalError(
                "repair_policy must be SelectiveRepairPolicy"
            )
        # Default gate: local structural constraints only (no live provers).
        # Callers may inject Hammer/cvc5 + Lean bindings for the live path.
        self._gate = admission_gate or StructuralAdmissionGate(
            StructuralAdmissionPolicy(
                tools=(StructuralTool.HAMMER_CVC5,),
                structural_constraints=DECLARED_STRUCTURAL_CONSTRAINTS,
            ),
            validators=(),
        )
        if not isinstance(self._gate, StructuralAdmissionGate):
            raise PlateauLeanstralProposalError(
                "admission_gate must be StructuralAdmissionGate"
            )
        self._client = client
        self._selective_repair = selective_repair
        if self._mode is ProposalMode.LIVE:
            if self._selective_repair is None and self._client is None:
                # Lazy-bind the frozen client only on the live path.
                self._client = LeanstralClient()
            if self._client is not None:
                if (
                    self._client.endpoint.rstrip("/") != LEANSTRAL_ENDPOINT
                    or self._client.model != LEANSTRAL_MODEL
                ):
                    raise PlateauLeanstralProposalError(
                        "live client must bind the frozen Leanstral identity"
                    )

    @property
    def mode(self) -> ProposalMode:
        return self._mode

    @property
    def admission_gate(self) -> StructuralAdmissionGate:
        return self._gate

    @property
    def policy(self) -> SelectiveRepairPolicy:
        return self._policy

    @property
    def identity(self) -> str:
        return (
            f"{self.interface}:{self._mode.value}:"
            f"{self._gate.identity}:{self._policy.digest}:"
            f"{LEANSTRAL_ENDPOINT}:{LEANSTRAL_MODEL}"
        )

    def _residual_ref(
        self,
        *,
        case_id: str,
        field_paths: Sequence[str],
        residual_id: str | None = None,
        catalog_digest: str | None = None,
        detail: str | None = None,
    ) -> ResidualRef:
        rid = residual_id or f"resid-{case_id}-leanstral"
        paths = tuple(field_paths) or ("rules[0].object",)
        return ResidualRef(
            residual_id=rid,
            case_id=case_id,
            field_paths=paths,
            facet=paths[0].rsplit(".", 1)[-1] if paths else None,
            catalog_digest=catalog_digest,
            detail=detail or "leanstral selective proposal residual ref",
        )

    def _build_packet(
        self,
        *,
        case_id: str,
        baseline_l1: CanonicalRuleIR,
        candidate_l1: CanonicalRuleIR | None,
        admission: StructuralAdmissionResult,
        triggers: Sequence[RepairTrigger],
        residual_ref: ResidualRef,
        proposal_id: str,
        packet_id: str,
        detail: str | None,
    ) -> tuple[TeacherProposal, PlateauCodexPacket]:
        allowed = trigger_paths(triggers)
        changes: tuple[CanonicalFieldChange, ...] = ()
        if candidate_l1 is not None and candidate_l1 != baseline_l1:
            changes = canonical_field_changes(baseline_l1, candidate_l1)
        proposal = TeacherProposal(
            proposal_id=proposal_id,
            teacher=TEACHER_IDENTITY,
            residual_ref_ids=(residual_ref.residual_id,),
            allowed_field_paths=allowed or residual_ref.field_paths,
            candidate_l1=candidate_l1,
            field_changes=changes,
            detail=detail,
            semantic_authority=False,
        )
        packet = build_packet_from_proposal_admission(
            packet_id=packet_id,
            baseline_l1=baseline_l1,
            residual_ref=residual_ref,
            proposal=proposal,
            admission=admission,
            predicted_files=DEFAULT_PREDICTED_FILES,
            validation_commands=DEFAULT_VALIDATION_COMMANDS,
            case_id=case_id,
            detail=detail,
        )
        # Hard fail-closed: never trust a packet that skipped admission accept.
        if packet.implementable and admission.disposition is not (
            AdmissionDisposition.ACCEPTED
        ):
            raise PlateauLeanstralProposalError(
                "implementable packet without StructuralAdmissionGate accept"
            )
        return proposal, packet

    def _live_candidate(
        self,
        request: ConstructorRequest,
        baseline_l1: CanonicalRuleIR,
        triggers: Sequence[RepairTrigger],
    ) -> tuple[
        CanonicalRuleIR | None,
        ProposalOutcome | None,
        int,
        str | None,
    ]:
        """Invoke selective Leanstral repair; return candidate + model outcome."""

        repairer = self._selective_repair
        if repairer is None:
            repairer = SelectiveLeanstralRepair(
                client=self._client,
                policy=self._policy,
            )
        construction = repairer.repair(
            request,
            baseline_l1,
            triggers,
        )
        model_calls = len(construction.receipt.model_calls)
        status = construction.receipt.status
        if status is RepairAttemptStatus.NOT_TRIGGERED:
            return None, ProposalOutcome.NOT_TRIGGERED, model_calls, None
        if status is RepairAttemptStatus.ACCEPTED:
            assert construction.result.canonical_ir is not None
            return (
                construction.result.canonical_ir,
                None,
                model_calls,
                construction.receipt.detail,
            )
        if status is RepairAttemptStatus.FAILED:
            failure = construction.result.failure_reason
            if failure is FailureReason.RETRY_EXHAUSTED or model_calls == 0:
                return (
                    None,
                    ProposalOutcome.RETRY_EXHAUSTED,
                    model_calls,
                    construction.receipt.detail
                    or "all Leanstral repair calls failed",
                )
            # Failed with returned-but-invalid calls still counts as model reject
            # when no candidate was selected; retry_exhausted only when no returns.
            returned = [
                call
                for call in construction.receipt.model_calls
                if call.status.value == "returned"
            ]
            if not returned:
                return (
                    None,
                    ProposalOutcome.RETRY_EXHAUSTED,
                    model_calls,
                    construction.receipt.detail
                    or "retry exhausted without returned candidates",
                )
            return (
                None,
                ProposalOutcome.MODEL_REJECTED,
                model_calls,
                construction.receipt.detail
                or "repair candidates failed structural selection",
            )
        if status is RepairAttemptStatus.REJECTED:
            return (
                None,
                ProposalOutcome.MODEL_REJECTED,
                model_calls,
                construction.receipt.detail
                or "every returned repair candidate was rejected",
            )
        return (
            None,
            ProposalOutcome.FAILED,
            model_calls,
            construction.receipt.detail or "selective repair failed",
        )

    def propose(
        self,
        *,
        case_id: str,
        baseline_l1: CanonicalRuleIR,
        triggers: Sequence[RepairTrigger],
        request: ConstructorRequest | None = None,
        candidate_l1: CanonicalRuleIR | None = None,
        residual_ref: ResidualRef | None = None,
        residual_field_paths: Sequence[str] | None = None,
        force_retry_exhausted: bool = False,
        detail: str | None = None,
        catalog_digest: str | None = None,
    ) -> LeanstralProposalCaseReceipt:
        """Emit one teacher proposal, admit it, and seal a case receipt.

        Structural admission always runs before ``implementable`` is derived.
        """

        case = _nonblank(case_id, "case_id")
        if not isinstance(baseline_l1, CanonicalRuleIR):
            raise PlateauLeanstralProposalError(
                "baseline_l1 must be CanonicalRuleIR"
            )
        normalized_triggers = tuple(triggers)
        if not all(
            isinstance(item, RepairTrigger) for item in normalized_triggers
        ):
            raise PlateauLeanstralProposalError(
                "triggers must be RepairTrigger records"
            )
        baseline_digest = baseline_l1_digest(baseline_l1)
        allowed = trigger_paths(normalized_triggers)
        residual = residual_ref or self._residual_ref(
            case_id=case,
            field_paths=residual_field_paths or allowed,
            catalog_digest=catalog_digest,
            detail=detail,
        )
        proposal_id = f"prop-leanstral-{case}"
        packet_id = f"pkt-leanstral-{case}"

        # --- no triggers -------------------------------------------------
        if not normalized_triggers:
            admission = admit_hybrid_repair(
                baseline_l1,
                None,
                gate=self._gate,
                allowed_field_paths=(),
            )
            return LeanstralProposalCaseReceipt(
                case_id=case,
                outcome=ProposalOutcome.NOT_TRIGGERED,
                mode=self._mode,
                baseline_l1_digest=baseline_digest,
                admitted_l1_digest=baseline_digest,
                prior_l1_unchanged=True,
                only_triggered_fields_changed=True,
                implementable=False,
                admission_disposition=admission.disposition.value,
                triggers=(),
                allowed_field_paths=(),
                residual_ref_id=residual.residual_id,
                model_calls=0,
                retry_exhausted=False,
                detail=detail or "no residual triggers; no proposal emitted",
                admitted_l1=baseline_l1,
            )

        # --- obtain candidate --------------------------------------------
        model_calls = 0
        model_outcome: ProposalOutcome | None = None
        active_candidate = candidate_l1
        active_detail = detail

        if force_retry_exhausted:
            active_candidate = None
            model_outcome = ProposalOutcome.RETRY_EXHAUSTED
            active_detail = active_detail or "retry exhausted (forced)"
        elif self._mode is ProposalMode.DRY_RUN:
            # Dry-run never opens a network client.  Candidate must be supplied
            # (fixture / residual gold patch) or the attempt is not_applicable.
            if active_candidate is None:
                model_outcome = ProposalOutcome.NOT_APPLICABLE
                active_detail = (
                    active_detail
                    or "dry-run without candidate_l1; no model call issued"
                )
        else:
            if request is None:
                raise PlateauLeanstralProposalError(
                    "live propose() requires a ConstructorRequest"
                )
            if active_candidate is None:
                try:
                    (
                        active_candidate,
                        model_outcome,
                        model_calls,
                        live_detail,
                    ) = self._live_candidate(
                        request, baseline_l1, normalized_triggers
                    )
                except (
                    LeanstralClientError,
                    LeanstralTimeoutError,
                    LeanstralUnavailableError,
                ) as exc:
                    active_candidate = None
                    model_outcome = ProposalOutcome.RETRY_EXHAUSTED
                    model_calls = max(model_calls, 1)
                    active_detail = _detail(exc, "Leanstral client failure")
                except BaseException as exc:
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    active_candidate = None
                    model_outcome = ProposalOutcome.FAILED
                    active_detail = _detail(
                        exc, f"proposal failed: {type(exc).__name__}"
                    )
                else:
                    if live_detail and not active_detail:
                        active_detail = live_detail

        if model_outcome is ProposalOutcome.NOT_TRIGGERED:
            return LeanstralProposalCaseReceipt(
                case_id=case,
                outcome=ProposalOutcome.NOT_TRIGGERED,
                mode=self._mode,
                baseline_l1_digest=baseline_digest,
                admitted_l1_digest=baseline_digest,
                prior_l1_unchanged=True,
                only_triggered_fields_changed=True,
                implementable=False,
                admission_disposition=AdmissionDisposition.NOT_APPLICABLE.value,
                triggers=normalized_triggers,
                allowed_field_paths=allowed,
                residual_ref_id=residual.residual_id,
                model_calls=model_calls,
                retry_exhausted=False,
                detail=active_detail or "repair not triggered",
                admitted_l1=baseline_l1,
            )

        if model_outcome is ProposalOutcome.RETRY_EXHAUSTED:
            return LeanstralProposalCaseReceipt(
                case_id=case,
                outcome=ProposalOutcome.RETRY_EXHAUSTED,
                mode=self._mode,
                baseline_l1_digest=baseline_digest,
                admitted_l1_digest=baseline_digest,
                prior_l1_unchanged=True,
                only_triggered_fields_changed=True,
                implementable=False,
                admission_disposition=None,
                triggers=normalized_triggers,
                allowed_field_paths=allowed,
                residual_ref_id=residual.residual_id,
                model_calls=model_calls,
                retry_exhausted=True,
                detail=active_detail or "retry exhausted; prior L1 retained",
                admitted_l1=baseline_l1,
            )

        if model_outcome is ProposalOutcome.MODEL_REJECTED:
            return LeanstralProposalCaseReceipt(
                case_id=case,
                outcome=ProposalOutcome.MODEL_REJECTED,
                mode=self._mode,
                baseline_l1_digest=baseline_digest,
                admitted_l1_digest=baseline_digest,
                prior_l1_unchanged=True,
                only_triggered_fields_changed=True,
                implementable=False,
                admission_disposition=None,
                triggers=normalized_triggers,
                allowed_field_paths=allowed,
                residual_ref_id=residual.residual_id,
                model_calls=model_calls,
                retry_exhausted=False,
                detail=active_detail or "model candidates rejected",
                admitted_l1=baseline_l1,
            )

        if model_outcome is ProposalOutcome.FAILED:
            return LeanstralProposalCaseReceipt(
                case_id=case,
                outcome=ProposalOutcome.FAILED,
                mode=self._mode,
                baseline_l1_digest=baseline_digest,
                admitted_l1_digest=baseline_digest,
                prior_l1_unchanged=True,
                only_triggered_fields_changed=True,
                implementable=False,
                admission_disposition=None,
                triggers=normalized_triggers,
                allowed_field_paths=allowed,
                residual_ref_id=residual.residual_id,
                model_calls=model_calls,
                retry_exhausted=False,
                detail=active_detail or "proposal pipeline failed",
                admitted_l1=baseline_l1,
            )

        if active_candidate is None:
            # Dry-run / live path with no candidate and no hard failure.
            return LeanstralProposalCaseReceipt(
                case_id=case,
                outcome=ProposalOutcome.NOT_APPLICABLE,
                mode=self._mode,
                baseline_l1_digest=baseline_digest,
                admitted_l1_digest=baseline_digest,
                prior_l1_unchanged=True,
                only_triggered_fields_changed=True,
                implementable=False,
                admission_disposition=AdmissionDisposition.NOT_APPLICABLE.value,
                triggers=normalized_triggers,
                allowed_field_paths=allowed,
                residual_ref_id=residual.residual_id,
                model_calls=model_calls,
                retry_exhausted=False,
                detail=active_detail or "no candidate L1 available",
                admitted_l1=baseline_l1,
            )

        # --- structural invariant pre-check (only triggered fields) ------
        only_triggered = only_triggered_fields_changed(
            baseline_l1, active_candidate, normalized_triggers
        )
        changes = canonical_field_changes(baseline_l1, active_candidate)

        # --- StructuralAdmissionGate BEFORE implementable ----------------
        admission = self._gate.admit(
            baseline_l1,
            active_candidate,
            allowed_field_paths=allowed,
        )
        if not isinstance(admission, StructuralAdmissionResult):
            raise PlateauLeanstralProposalError(
                "admission gate must return StructuralAdmissionResult"
            )

        proposal, packet = self._build_packet(
            case_id=case,
            baseline_l1=baseline_l1,
            candidate_l1=active_candidate,
            admission=admission,
            triggers=normalized_triggers,
            residual_ref=residual,
            proposal_id=proposal_id,
            packet_id=packet_id,
            detail=active_detail,
        )
        del proposal  # sealed inside packet

        # Implementable only after gate accept (packet builder enforces too).
        implementable = (
            admission.disposition is AdmissionDisposition.ACCEPTED
            and packet.implementable
            and only_triggered
            and not admission.prior_l1_unchanged
        )
        if implementable and admission.disposition is not (
            AdmissionDisposition.ACCEPTED
        ):
            raise PlateauLeanstralProposalError(
                "internal: implementable without admission accept"
            )

        if admission.disposition is AdmissionDisposition.ACCEPTED and (
            only_triggered
        ):
            outcome = ProposalOutcome.ACCEPTED
        elif admission.disposition in {
            AdmissionDisposition.VALIDATOR_REJECT,
            AdmissionDisposition.TIMEOUT,
            AdmissionDisposition.ERROR,
        }:
            outcome = ProposalOutcome.ADMISSION_REJECTED
            implementable = False
        elif admission.disposition is AdmissionDisposition.NOT_APPLICABLE:
            outcome = ProposalOutcome.NOT_APPLICABLE
            implementable = False
        else:
            # Accepted disposition but untriggered fields changed — fail closed.
            outcome = ProposalOutcome.ADMISSION_REJECTED
            implementable = False

        admitted = admission.admitted_l1
        admitted_digest = baseline_l1_digest(admitted)
        prior_unchanged = bool(admission.prior_l1_unchanged)

        # Rejects / fail-closed must retain prior L1.
        if outcome is not ProposalOutcome.ACCEPTED:
            if admitted != baseline_l1:
                raise PlateauLeanstralProposalError(
                    "non-accepted admission must retain prior L1"
                )
            prior_unchanged = True
            implementable = False

        return LeanstralProposalCaseReceipt(
            case_id=case,
            outcome=outcome,
            mode=self._mode,
            baseline_l1_digest=baseline_digest,
            admitted_l1_digest=admitted_digest,
            prior_l1_unchanged=prior_unchanged,
            only_triggered_fields_changed=only_triggered,
            implementable=implementable,
            admission_disposition=admission.disposition.value,
            triggers=normalized_triggers,
            allowed_field_paths=allowed,
            field_changes=changes if implementable else admission.field_changes,
            proposal_id=proposal_id,
            packet_id=packet.packet_id,
            packet_digest=packet.packet_digest,
            residual_ref_id=residual.residual_id,
            model_calls=model_calls,
            retry_exhausted=False,
            detail=active_detail or admission.detail,
            candidate_l1=active_candidate,
            admitted_l1=admitted,
            packet=packet if implementable or packet is not None else None,
        )

    def propose_fixture(
        self, fixture: DryRunFixtureCase
    ) -> LeanstralProposalCaseReceipt:
        """Run one dry-run fixture case through the teacher pipeline."""

        if not isinstance(fixture, DryRunFixtureCase):
            raise PlateauLeanstralProposalError(
                "fixture must be DryRunFixtureCase"
            )
        # Fixtures always use dry-run semantics even if the teacher was
        # constructed for live (fixtures never require a network client).
        return self.propose(
            case_id=fixture.case_id,
            baseline_l1=fixture.baseline_l1,
            triggers=fixture.triggers,
            request=fixture.constructor_request(),
            candidate_l1=fixture.candidate_l1,
            residual_field_paths=fixture.residual_field_paths,
            force_retry_exhausted=fixture.force_retry_exhausted,
            detail=fixture.detail,
        )

    def run_dry_run_fixtures(
        self,
        fixtures: Sequence[DryRunFixtureCase] | None = None,
    ) -> PlateauLeanstralProposalReceipts:
        """Execute the offline fixture pack and seal reliability receipts."""

        pack = tuple(fixtures) if fixtures is not None else dry_run_fixture_pack()
        if not pack:
            raise PlateauLeanstralProposalError(
                "dry-run fixture pack must be nonempty"
            )
        # Force dry-run mode for the fixture path.
        teacher = self
        if self._mode is not ProposalMode.DRY_RUN:
            teacher = LeanstralSelectiveProposalTeacher(
                mode=ProposalMode.DRY_RUN,
                admission_gate=self._gate,
                repair_policy=self._policy,
            )
        case_receipts = tuple(teacher.propose_fixture(item) for item in pack)
        reliability = aggregate_proposal_reliability(case_receipts)
        return PlateauLeanstralProposalReceipts(
            cases=case_receipts,
            mode=ProposalMode.DRY_RUN,
            reliability=reliability,
            fixture_pack_id=DRY_RUN_FIXTURE_PACK_ID,
        ).with_receipts_cid()

    def run_live_cases(
        self,
        cases: Sequence[
            tuple[
                str,
                CanonicalRuleIR,
                Sequence[RepairTrigger],
                ConstructorRequest,
            ]
        ],
        *,
        catalog_digest: str | None = None,
    ) -> PlateauLeanstralProposalReceipts:
        """Run the live Leanstral path for explicit (case, L1, triggers, request) rows."""

        if self._mode is not ProposalMode.LIVE:
            raise PlateauLeanstralProposalError(
                "run_live_cases requires mode=live"
            )
        if not cases:
            raise PlateauLeanstralProposalError("live cases must be nonempty")
        receipts: list[LeanstralProposalCaseReceipt] = []
        for case_id, baseline_l1, triggers, request in cases:
            receipts.append(
                self.propose(
                    case_id=case_id,
                    baseline_l1=baseline_l1,
                    triggers=triggers,
                    request=request,
                    catalog_digest=catalog_digest,
                )
            )
        reliability = aggregate_proposal_reliability(receipts)
        return PlateauLeanstralProposalReceipts(
            cases=tuple(receipts),
            mode=ProposalMode.LIVE,
            reliability=reliability,
            fixture_pack_id=None,
            catalog_cid=catalog_digest,
        ).with_receipts_cid()


def build_dry_run_proposal_receipts(
    *,
    fixtures: Sequence[DryRunFixtureCase] | None = None,
    admission_gate: StructuralAdmissionGate | None = None,
) -> PlateauLeanstralProposalReceipts:
    """Build sealed dry-run proposal receipts (no live model)."""

    teacher = LeanstralSelectiveProposalTeacher(
        mode=ProposalMode.DRY_RUN,
        admission_gate=admission_gate,
    )
    return teacher.run_dry_run_fixtures(fixtures)


def write_plateau_leanstral_proposal_receipts(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
    receipts: PlateauLeanstralProposalReceipts | Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Atomically write the sealed proposal receipts JSON artifact."""

    root = repo_root if repo_root is not None else _repo_root()
    out = (
        path
        if path is not None
        else root / DEFAULT_RECEIPTS_RELATIVE_PATH
    )
    if receipts is None:
        sealed = build_dry_run_proposal_receipts()
    elif isinstance(receipts, PlateauLeanstralProposalReceipts):
        sealed = (
            receipts
            if receipts.receipts_cid is not None
            else receipts.with_receipts_cid()
        )
    else:
        sealed = parse_plateau_leanstral_proposal_receipts(receipts)
        if sealed.receipts_cid is None:
            sealed = sealed.with_receipts_cid()

    payload = sealed.to_dict()
    parse_plateau_leanstral_proposal_receipts(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    )
    if not encoded.endswith("\n"):
        encoded += "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".plateau_leanstral_proposal_receipts.",
        suffix=".json.tmp",
        dir=str(out.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, out)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    return payload


def load_plateau_leanstral_proposal_receipts(
    path: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> PlateauLeanstralProposalReceipts:
    """Load and validate the checked-in proposal receipts artifact."""

    root = repo_root if repo_root is not None else _repo_root()
    receipts_path = (
        path if path is not None else root / DEFAULT_RECEIPTS_RELATIVE_PATH
    )
    payload = json.loads(receipts_path.read_text(encoding="utf-8"))
    return parse_plateau_leanstral_proposal_receipts(payload)


def validate_dry_run_fixture_pack(
    receipts: PlateauLeanstralProposalReceipts | None = None,
) -> PlateauLeanstralProposalReceipts:
    """Fail closed when dry-run fixtures do not meet PLAT-040 acceptance."""

    sealed = receipts or build_dry_run_proposal_receipts()
    if sealed.mode is not ProposalMode.DRY_RUN:
        raise PlateauLeanstralProposalError(
            "fixture pack validation requires dry_run mode"
        )
    by_id = sealed.by_case_id()
    expected = {item.case_id: item for item in dry_run_fixture_pack()}
    for case_id, fixture in expected.items():
        if case_id not in by_id:
            raise PlateauLeanstralProposalError(
                f"missing dry-run fixture receipt: {case_id}"
            )
        receipt = by_id[case_id]
        if receipt.outcome is not fixture.expected_outcome:
            raise PlateauLeanstralProposalError(
                f"{case_id}: expected outcome {fixture.expected_outcome.value}, "
                f"got {receipt.outcome.value}"
            )
        if receipt.implementable and receipt.admission_disposition != (
            AdmissionDisposition.ACCEPTED.value
        ):
            raise PlateauLeanstralProposalError(
                f"{case_id}: implementable without StructuralAdmissionGate accept"
            )
        if (
            receipt.outcome is ProposalOutcome.ACCEPTED
            and not receipt.only_triggered_fields_changed
        ):
            raise PlateauLeanstralProposalError(
                f"{case_id}: accepted proposal changed untriggered fields"
            )
        if (
            receipt.outcome is ProposalOutcome.ADMISSION_REJECTED
            and not receipt.prior_l1_unchanged
        ):
            raise PlateauLeanstralProposalError(
                f"{case_id}: reject must retain prior L1"
            )
        if (
            receipt.outcome is ProposalOutcome.RETRY_EXHAUSTED
            and not receipt.retry_exhausted
        ):
            raise PlateauLeanstralProposalError(
                f"{case_id}: retry_exhausted outcome missing flag"
            )
    # Reliability must expose accept_rate and retry_exhausted separately.
    rel = sealed.reliability
    if rel.accept_rate is None or rel.retry_exhausted_rate is None:
        raise PlateauLeanstralProposalError(
            "fixture pack must record accept_rate and retry_exhausted_rate"
        )
    rel_payload = rel.to_dict()
    if rel_payload.get("end_to_end_loss") is not None:
        raise PlateauLeanstralProposalError(
            "proposal reliability must not report end_to_end_loss"
        )
    if rel_payload.get("separate_from_end_to_end_loss") is not True:
        raise PlateauLeanstralProposalError(
            "accept_rate/retry_exhausted must be separate from e2e loss"
        )
    if sealed.leanstral_is_default_realizer is not False:
        raise PlateauLeanstralProposalError(
            "Leanstral must not be the default realizer"
        )
    return sealed


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or validate PlateauLeanstralProposalReceipts@1"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Receipts JSON path",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate existing receipts instead of writing",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.repo_root or _repo_root()
    path = args.output or (root / DEFAULT_RECEIPTS_RELATIVE_PATH)
    if args.validate:
        sealed = load_plateau_leanstral_proposal_receipts(path, repo_root=root)
        validate_dry_run_fixture_pack(sealed)
        print(f"validated {path} cid={sealed.receipts_cid}")
        return 0
    payload = write_plateau_leanstral_proposal_receipts(path, repo_root=root)
    print(
        f"wrote {path} cid={payload.get('receipts_cid')} "
        f"accept_rate={payload['reliability']['accept_rate']} "
        f"retry_exhausted_rate={payload['reliability']['retry_exhausted_rate']}"
    )
    return 0


__all__ = [
    "ACCEPT_RATE_DEFINITION",
    "DEFAULT_RECEIPTS_RELATIVE_PATH",
    "DRY_RUN_FIXTURE_PACK_ID",
    "PLATEAU_BREAK_TASK_ID",
    "PLATEAU_LEANSTRAL_PROPOSALS_EVIDENCE",
    "PLATEAU_LEANSTRAL_PROPOSALS_INTERFACE",
    "PLATEAU_LEANSTRAL_PROPOSALS_SCHEMA",
    "PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_INTERFACE",
    "PLATEAU_LEANSTRAL_PROPOSAL_RECEIPTS_SCHEMA",
    "PLATEAU_LEANSTRAL_PROPOSAL_RECEIPT_INTERFACE",
    "PROVIDER_ID",
    "RETRY_EXHAUSTED_RATE_DEFINITION",
    "TEACHER_IDENTITY",
    "DryRunFixtureCase",
    "LeanstralProposalCaseReceipt",
    "LeanstralSelectiveProposalTeacher",
    "PlateauLeanstralProposalError",
    "PlateauLeanstralProposalReceipts",
    "ProposalMode",
    "ProposalOutcome",
    "ProposalReliabilityMetrics",
    "aggregate_proposal_reliability",
    "apply_field_patch",
    "apply_trigger_patches",
    "build_dry_run_proposal_receipts",
    "dry_run_fixture_pack",
    "load_plateau_leanstral_proposal_receipts",
    "only_triggered_fields_changed",
    "parse_plateau_leanstral_proposal_receipts",
    "trigger_paths",
    "validate_dry_run_fixture_pack",
    "write_plateau_leanstral_proposal_receipts",
]


if __name__ == "__main__":
    raise SystemExit(_main())
