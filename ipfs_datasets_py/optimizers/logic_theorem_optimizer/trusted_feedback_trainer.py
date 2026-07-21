"""Guarded production updates from verifier-owned Legal IR feedback.

The modal autoencoder has a deliberately small primitive for applying trusted
Hammer/Leanstral features.  This module is the production boundary around that
primitive.  It pins the proof-feedback version, keeps frozen holdout samples
out of training, deduplicates content-addressed receipts, rejects source-copy
signals, requires the referenced sample, and checks a held-out ablation before
any persistent state is changed.

No prover or model is called from this module.  It consumes already persisted
feedback and ablation receipts, making replay deterministic and safe to run in
an asynchronous trainer.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Optional

from ...logic.integration.reasoning.legal_ir_learned_guidance import (
    TRUSTED_FEEDBACK_ABLATION_SCHEMA_VERSION,
    TrustedFeedbackAblationEvidence,
)
from ...logic.integration.reasoning.legal_ir_proof_feedback import (
    LEGAL_IR_PROOF_FEEDBACK_SCHEMA_VERSION,
    LegalIRProofFeedbackRecord,
    ProofFeedbackPartition,
    ProofFeedbackTrustStatus,
    ProofFeedbackVersions,
    proof_feedback_content_digest,
)
from .modal_autoencoder import (
    AdaptiveModalAutoencoder,
    build_trusted_hammer_leanstral_feature_bus,
    legal_ir_trainable_head_delta_norm_report,
)


TRUSTED_FEEDBACK_TRAINER_SCHEMA_VERSION: Final = (
    "legal-ir-trusted-feedback-weight-updates-v1"
)
DEFAULT_TRUSTED_FEEDBACK_MAX_LEARNING_RATE: Final = 0.10
DEFAULT_TRUSTED_FEEDBACK_MAX_UPDATES: Final = 64

_TRUE = frozenset({"1", "accepted", "passed", "proved", "true", "trusted", "verified", "yes"})
_FALSE = frozenset({"0", "false", "failed", "no", "rejected", "untrusted"})
_SOURCE_COPY_REJECTION_MARKERS = frozenset(
    {
        "copied_source_span",
        "drafted_logic_candidate_copies_source",
        "source_copy",
        "source_copy_rejected",
    }
)
_SOURCE_COPY_BOOLEAN_GUARDS = frozenset(
    {
        "copied_source_span_rejected",
        "copy_source_span_rejected",
        "source_copy_rejected",
    }
)
_VERIFIER_KEYS = (
    "leanstral_verified",
    "verifier_confirmed",
    "verified",
    "proof_checked",
)


class _SerializableMapping(Mapping[str, Any]):
    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - protocol method
        raise NotImplementedError

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True)
class TrustedFeedbackTrainerConfig:
    """Fail-closed bounds for one asynchronous trainer instance."""

    expected_version_fingerprint: str = ""
    learning_rate: float = 0.05
    maximum_learning_rate: float = DEFAULT_TRUSTED_FEEDBACK_MAX_LEARNING_RATE
    max_updates_per_batch: int = DEFAULT_TRUSTED_FEEDBACK_MAX_UPDATES
    production_weight_writes_enabled: bool = False
    require_ablation: bool = True
    require_sample: bool = True
    require_explicit_train_partition: bool = False
    maximum_source_copy_penalty: float = 0.0

    def __post_init__(self) -> None:
        for name in ("learning_rate", "maximum_learning_rate", "maximum_source_copy_penalty"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.learning_rate > self.maximum_learning_rate:
            raise ValueError("learning_rate exceeds the trusted-feedback bound")
        if int(self.max_updates_per_batch) < 1 or int(self.max_updates_per_batch) > 1024:
            raise ValueError("max_updates_per_batch must be between 1 and 1024")


@dataclass(frozen=True)
class TrustedFeedbackUpdateReport(_SerializableMapping):
    """Explicit accounting for every candidate presented to the trainer."""

    candidate_count: int
    applied_count: int = 0
    duplicate_count: int = 0
    stale_count: int = 0
    untrusted_count: int = 0
    missing_sample_count: int = 0
    guardrail_blocked_count: int = 0
    holdout_count: int = 0
    invalid_count: int = 0
    limit_skipped_count: int = 0
    applied_feedback_ids: tuple[str, ...] = ()
    gradient_norms_by_family: Mapping[str, float] = field(default_factory=dict)
    gradient_norms_by_head: Mapping[str, float] = field(default_factory=dict)
    head_family_gradient_norms: Mapping[str, float] = field(default_factory=dict)
    head_family_update_norms: Mapping[str, float] = field(default_factory=dict)
    trainable_legal_ir_head_norms: Mapping[str, Any] = field(default_factory=dict)
    update_norms_by_family: Mapping[str, float] = field(default_factory=dict)
    update_norms_by_head: Mapping[str, float] = field(default_factory=dict)
    block_reasons: Mapping[str, int] = field(default_factory=dict)
    ablation_evidence: Mapping[str, Any] = field(default_factory=dict)
    production_weight_writes_enabled: bool = False
    write_to_autoencoder_weights: bool = False
    schema_version: str = TRUSTED_FEEDBACK_TRAINER_SCHEMA_VERSION

    @property
    def accounted_count(self) -> int:
        return sum(
            (
                self.applied_count,
                self.duplicate_count,
                self.stale_count,
                self.untrusted_count,
                self.missing_sample_count,
                self.guardrail_blocked_count,
                self.invalid_count,
                self.limit_skipped_count,
            )
        )

    @property
    def status(self) -> str:
        if self.applied_count:
            return "applied"
        if not self.candidate_count:
            return "no_feedback"
        return "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ablation_evidence": _json_ready(self.ablation_evidence),
            "accounted_count": self.accounted_count,
            "applied_count": self.applied_count,
            "applied_feedback_ids": list(self.applied_feedback_ids),
            "block_reasons": dict(sorted(self.block_reasons.items())),
            "candidate_count": self.candidate_count,
            "duplicate_count": self.duplicate_count,
            "guardrail_blocked_count": self.guardrail_blocked_count,
            "gradient_norms_by_family": dict(sorted(self.gradient_norms_by_family.items())),
            "gradient_norms_by_head": dict(sorted(self.gradient_norms_by_head.items())),
            "head_family_gradient_norms": dict(
                sorted(self.head_family_gradient_norms.items())
            ),
            "head_family_update_norms": dict(
                sorted(self.head_family_update_norms.items())
            ),
            "holdout_count": self.holdout_count,
            "invalid_count": self.invalid_count,
            "limit_skipped_count": self.limit_skipped_count,
            "missing_sample_count": self.missing_sample_count,
            "production_weight_writes_enabled": self.production_weight_writes_enabled,
            "schema_version": self.schema_version,
            # Explicit names requested by pipeline/telemetry consumers.
            "skipped_duplicate_count": self.duplicate_count,
            "skipped_guardrail_blocked_count": self.guardrail_blocked_count,
            "skipped_missing_sample_count": self.missing_sample_count,
            "skipped_stale_count": self.stale_count,
            "skipped_untrusted_count": self.untrusted_count,
            "stale_count": self.stale_count,
            "status": self.status,
            "trainable_legal_ir_head_norms": _json_ready(
                self.trainable_legal_ir_head_norms
            ),
            "untrusted_count": self.untrusted_count,
            "update_norms_by_family": dict(sorted(self.update_norms_by_family.items())),
            "update_norms_by_head": dict(sorted(self.update_norms_by_head.items())),
            "write_to_autoencoder_weights": self.write_to_autoencoder_weights,
        }


class TrustedFeedbackTrainer:
    """Apply trusted feedback to an autoencoder only after all guards pass."""

    def __init__(
        self,
        autoencoder: AdaptiveModalAutoencoder,
        *,
        expected_versions: ProofFeedbackVersions | Mapping[str, Any] | str | None = None,
        config: Optional[TrustedFeedbackTrainerConfig] = None,
    ) -> None:
        self.autoencoder = autoencoder
        self.config = config or TrustedFeedbackTrainerConfig()
        self.expected_versions = _coerce_versions(expected_versions)
        expected = _version_fingerprint(expected_versions)
        configured = str(self.config.expected_version_fingerprint or "")
        if expected and configured and expected != configured:
            raise ValueError("configured and supplied proof-feedback versions differ")
        self.expected_version_fingerprint = configured or expected
        self._lock = threading.RLock()

    def train(
        self,
        feedback: Any,
        samples_by_id: Mapping[str, Any],
        *,
        ablation_evidence: TrustedFeedbackAblationEvidence | Mapping[str, Any] | None = None,
        production_weight_writes_enabled: Optional[bool] = None,
        learning_rate: Optional[float] = None,
    ) -> TrustedFeedbackUpdateReport:
        """Validate and apply one bounded batch, returning exhaustive counters."""

        items = _feedback_items(feedback)
        enabled = (
            self.config.production_weight_writes_enabled
            if production_weight_writes_enabled is None
            else bool(production_weight_writes_enabled)
        )
        step = self.config.learning_rate if learning_rate is None else float(learning_rate)
        if not math.isfinite(step) or step < 0.0 or step > self.config.maximum_learning_rate:
            raise ValueError("learning_rate is outside the trusted-feedback bound")
        ablation, ablation_allowed = _ablation_gate(ablation_evidence)
        holdout_ids = {
            str(value)
            for value in ablation.get("heldout_sample_ids", ())
            if str(value)
        }
        ablation_train_ids = {
            str(value)
            for value in ablation.get("training_sample_ids", ())
            if str(value)
        }
        counts = {
            "applied_count": 0,
            "duplicate_count": 0,
            "stale_count": 0,
            "untrusted_count": 0,
            "missing_sample_count": 0,
            "guardrail_blocked_count": 0,
            "holdout_count": 0,
            "invalid_count": 0,
            "limit_skipped_count": 0,
        }
        reasons: dict[str, int] = {}
        applied: list[str] = []
        update_norm_reports: list[Mapping[str, Any]] = []

        def block(counter: str, reason: str) -> None:
            counts[counter] += 1
            reasons[reason] = reasons.get(reason, 0) + 1

        with self._lock:
            state_ids = set(
                str(value)
                for value in getattr(
                    self.autoencoder.state,
                    "applied_leanstral_guidance_ids",
                    (),
                )
            )
            for index, envelope in enumerate(items):
                if index >= int(self.config.max_updates_per_batch):
                    block("limit_skipped_count", "batch_update_limit_exceeded")
                    continue
                item, proof_record = _normalize_feedback(envelope)
                if not item:
                    block("invalid_count", "invalid_feedback")
                    continue
                feedback_id = _feedback_id(item, proof_record)
                if feedback_id in state_ids:
                    block("duplicate_count", "duplicate_feedback")
                    continue
                candidate_version = _candidate_version_fingerprint(item, proof_record)
                if (
                    not self.expected_version_fingerprint
                    or not candidate_version
                    or candidate_version != self.expected_version_fingerprint
                ):
                    block("stale_count", "version_missing_or_mismatched")
                    continue
                if not _feedback_is_trusted(item, proof_record):
                    block("untrusted_count", "untrusted_or_unverified_feedback")
                    continue
                sample_id = _sample_id(item, proof_record)
                if not sample_id or sample_id not in samples_by_id:
                    block("missing_sample_count", "referenced_sample_missing")
                    continue
                partition = _partition(item, proof_record)
                if partition == ProofFeedbackPartition.HOLDOUT.value or sample_id in holdout_ids:
                    counts["holdout_count"] += 1
                    block("guardrail_blocked_count", "holdout_feedback_isolation")
                    continue
                if partition == "mismatch":
                    block("guardrail_blocked_count", "feedback_partition_mismatch")
                    continue
                if self.config.require_explicit_train_partition and partition != ProofFeedbackPartition.TRAIN.value:
                    block("guardrail_blocked_count", "train_partition_not_attested")
                    continue
                copy_reason = _source_copy_block_reason(
                    item,
                    maximum_penalty=self.config.maximum_source_copy_penalty,
                )
                if copy_reason:
                    block("guardrail_blocked_count", copy_reason)
                    continue
                if not enabled:
                    block("guardrail_blocked_count", "production_weight_writes_disabled")
                    continue
                if self.config.require_ablation and not ablation_allowed:
                    block("guardrail_blocked_count", "heldout_ablation_not_passed")
                    continue
                if (
                    self.config.require_ablation
                    and ablation_train_ids
                    and sample_id not in ablation_train_ids
                ):
                    block("guardrail_blocked_count", "sample_not_covered_by_ablation")
                    continue
                if step <= 0.0:
                    block("guardrail_blocked_count", "learning_rate_disabled")
                    continue

                snapshot = self.autoencoder.state.copy()
                try:
                    updated = _apply_bounded_sample_update(
                        self.autoencoder,
                        item,
                        samples_by_id[sample_id],
                        feedback_id=feedback_id,
                        learning_rate=step,
                    )
                    if not updated:
                        self.autoencoder.state = snapshot
                        block("guardrail_blocked_count", "no_bounded_learning_target")
                        continue
                    if proof_record is not None and hasattr(
                        self.autoencoder, "train_proof_auxiliary_heads"
                    ):
                        proof_update = self.autoencoder.train_proof_auxiliary_heads(
                            [proof_record],
                            expected_versions=self.expected_versions,
                            learning_rate=step,
                        )
                        if int(proof_update.get("applied_count", 0) or 0) != 1:
                            self.autoencoder.state = snapshot
                            block("guardrail_blocked_count", "proof_head_update_rejected")
                            continue
                    update_norm_reports.append(
                        legal_ir_trainable_head_delta_norm_report(
                            snapshot,
                            self.autoencoder.state,
                            learning_rate=step,
                        )
                    )
                except Exception:
                    # The snapshot makes each receipt atomic even when a
                    # custom autoencoder implementation raises unexpectedly.
                    self.autoencoder.state = snapshot
                    block("guardrail_blocked_count", "transactional_update_failed")
                    continue
                state_ids.add(feedback_id)
                applied.append(feedback_id)
                counts["applied_count"] += 1

        return TrustedFeedbackUpdateReport(
            candidate_count=len(items),
            applied_feedback_ids=tuple(applied),
            **_aggregate_update_norm_reports(update_norm_reports, learning_rate=step),
            block_reasons=reasons,
            ablation_evidence=ablation,
            production_weight_writes_enabled=enabled,
            write_to_autoencoder_weights=bool(enabled and applied),
            **counts,
        )

    def apply(self, *args: Any, **kwargs: Any) -> TrustedFeedbackUpdateReport:
        """Alias used by replay workers."""

        return self.train(*args, **kwargs)

    def apply_trusted_feedback(self, *args: Any, **kwargs: Any) -> TrustedFeedbackUpdateReport:
        return self.train(*args, **kwargs)

    def apply_weight_updates(self, *args: Any, **kwargs: Any) -> TrustedFeedbackUpdateReport:
        return self.train(*args, **kwargs)


def apply_trusted_feedback_weight_updates(
    autoencoder: AdaptiveModalAutoencoder,
    feedback: Any,
    samples_by_id: Mapping[str, Any],
    *,
    expected_versions: ProofFeedbackVersions | Mapping[str, Any] | str,
    ablation_evidence: TrustedFeedbackAblationEvidence | Mapping[str, Any],
    config: Optional[TrustedFeedbackTrainerConfig] = None,
    learning_rate: Optional[float] = None,
) -> TrustedFeedbackUpdateReport:
    """One-shot production entry point with weight writes explicitly enabled."""

    resolved_config = config or TrustedFeedbackTrainerConfig(
        production_weight_writes_enabled=True
    )
    trainer = TrustedFeedbackTrainer(
        autoencoder,
        expected_versions=expected_versions,
        config=resolved_config,
    )
    return trainer.train(
        feedback,
        samples_by_id,
        ablation_evidence=ablation_evidence,
        production_weight_writes_enabled=True,
        learning_rate=learning_rate,
    )


train_trusted_feedback = apply_trusted_feedback_weight_updates


def _aggregate_update_norm_reports(
    reports: Sequence[Mapping[str, Any]],
    *,
    learning_rate: float,
) -> dict[str, Any]:
    update_head_squares: dict[str, float] = {}
    update_family_squares: dict[str, float] = {}
    update_head_family_squares: dict[str, float] = {}
    scalar_counts: dict[str, int] = {}
    finite = True

    def add_square(target: dict[str, float], key: str, value: Any) -> None:
        nonlocal finite
        try:
            number = float(value)
        except (TypeError, ValueError):
            finite = False
            return
        if not math.isfinite(number):
            finite = False
            return
        if number <= 0.0:
            return
        target[key] = target.get(key, 0.0) + (number * number)

    for report in reports:
        finite = finite and bool(report.get("finite", True))
        for head, norm in dict(report.get("update_norms_by_head", {}) or {}).items():
            add_square(update_head_squares, str(head), norm)
        for family, norm in dict(report.get("update_norms_by_family", {}) or {}).items():
            add_square(update_family_squares, str(family), norm)
        for family, norm in dict(report.get("head_family_update_norms", {}) or {}).items():
            add_square(update_head_family_squares, str(family), norm)
        for head, count in dict(report.get("scalar_update_counts_by_head", {}) or {}).items():
            try:
                scalar_counts[str(head)] = scalar_counts.get(str(head), 0) + int(count)
            except (TypeError, ValueError):
                finite = False

    update_norms_by_head = _sqrt_norms(update_head_squares)
    update_norms_by_family = _sqrt_norms(update_family_squares)
    head_family_update_norms = _sqrt_norms(update_head_family_squares)
    step = abs(float(learning_rate)) if math.isfinite(float(learning_rate)) else 0.0
    gradient_norms_by_head = _divide_norms(update_norms_by_head, step)
    gradient_norms_by_family = _divide_norms(update_norms_by_family, step)
    head_family_gradient_norms = _divide_norms(head_family_update_norms, step)
    total_update_norm = math.sqrt(sum(update_head_squares.values()))
    total_gradient_norm = total_update_norm / step if step > 0.0 else 0.0
    norm_report = {
        "applied_update_report_count": len(reports),
        "finite": bool(finite),
        "gradient_norm": round(total_gradient_norm, 12),
        "gradient_norms_by_family": gradient_norms_by_family,
        "gradient_norms_by_head": gradient_norms_by_head,
        "head_family_gradient_norms": head_family_gradient_norms,
        "head_family_update_norms": head_family_update_norms,
        "learning_rate": float(learning_rate),
        "nonzero_gradient": bool(total_gradient_norm > 0.0),
        "nonzero_update": bool(total_update_norm > 0.0),
        "scalar_update_counts_by_head": dict(sorted(scalar_counts.items())),
        "update_norm": round(total_update_norm, 12),
        "update_norms_by_family": update_norms_by_family,
        "update_norms_by_head": update_norms_by_head,
    }
    return {
        "gradient_norms_by_family": gradient_norms_by_family,
        "gradient_norms_by_head": gradient_norms_by_head,
        "head_family_gradient_norms": head_family_gradient_norms,
        "head_family_update_norms": head_family_update_norms,
        "trainable_legal_ir_head_norms": norm_report,
        "update_norms_by_family": update_norms_by_family,
        "update_norms_by_head": update_norms_by_head,
    }


def _sqrt_norms(squares: Mapping[str, float]) -> dict[str, float]:
    return {
        key: round(math.sqrt(max(0.0, float(value))), 12)
        for key, value in sorted(squares.items())
    }


def _divide_norms(norms: Mapping[str, float], denominator: float) -> dict[str, float]:
    if denominator <= 0.0:
        return {key: 0.0 for key in sorted(norms)}
    return {
        key: round(float(value) / denominator, 12)
        for key, value in sorted(norms.items())
    }


def _coerce_versions(value: Any) -> Optional[ProofFeedbackVersions]:
    if isinstance(value, ProofFeedbackVersions):
        return value
    if isinstance(value, Mapping):
        try:
            return ProofFeedbackVersions.from_dict(value)
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _version_fingerprint(value: Any) -> str:
    if isinstance(value, ProofFeedbackVersions):
        return value.fingerprint
    if isinstance(value, Mapping):
        versions = _coerce_versions(value)
        return versions.fingerprint if versions is not None else proof_feedback_content_digest(value)
    return str(value or "").strip()


def _candidate_version_fingerprint(
    item: Mapping[str, Any],
    record: Optional[LegalIRProofFeedbackRecord],
) -> str:
    if record is not None:
        for key in (
            "proof_feedback_version_fingerprint",
            "version_fingerprint",
            "model_version_fingerprint",
        ):
            claimed = str(item.get(key) or "").strip()
            if claimed and claimed != record.version_fingerprint:
                return "conflicting-record-version"
        return record.version_fingerprint
    for key in (
        "proof_feedback_version_fingerprint",
        "version_fingerprint",
        "model_version_fingerprint",
    ):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    versions = item.get("versions")
    if isinstance(versions, Mapping):
        return _version_fingerprint(versions)
    feedback_record = item.get("proof_feedback_record")
    if isinstance(feedback_record, Mapping):
        return str(feedback_record.get("version_fingerprint") or "")
    return ""


def _feedback_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, LegalIRProofFeedbackRecord):
        return [value]
    if isinstance(value, Mapping):
        # An envelope binding guidance to a proof record is one atomic item.
        if "proof_feedback_record" in value and any(
            key in value for key in ("guidance", "feedback", "sample_id")
        ):
            return [value]
        nested: list[Any] = []
        for key in (
            "feedback_records",
            "trusted_feedback",
            "verified_guidance",
            "hammer_guidance_artifacts",
            "guidance_items",
            "items",
        ):
            if key in value:
                nested.extend(_feedback_items(value[key]))
        return nested or [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [item for child in value for item in _feedback_items(child)]
    return [value]


def _normalize_feedback(
    value: Any,
) -> tuple[dict[str, Any], Optional[LegalIRProofFeedbackRecord]]:
    record: Optional[LegalIRProofFeedbackRecord] = None
    if isinstance(value, LegalIRProofFeedbackRecord):
        record = value
        item: dict[str, Any] = {}
    elif isinstance(value, Mapping):
        item = {str(key): child for key, child in value.items()}
        raw_record = item.get("proof_feedback_record")
        if isinstance(raw_record, LegalIRProofFeedbackRecord):
            record = raw_record
        elif isinstance(raw_record, Mapping):
            try:
                record = LegalIRProofFeedbackRecord.from_dict(raw_record)
            except (TypeError, ValueError):
                return {}, None
        nested = item.get("guidance") or item.get("feedback")
        if isinstance(nested, Mapping):
            envelope = item
            item = {str(key): child for key, child in nested.items()}
            for key in ("sample_id", "partition", "version_fingerprint"):
                if key in envelope and key not in item:
                    item[key] = envelope[key]
    else:
        to_dict = getattr(value, "to_dict", None)
        if not callable(to_dict):
            return {}, None
        try:
            converted = to_dict()
        except (TypeError, ValueError):
            return {}, None
        return _normalize_feedback(converted)
    if record is not None:
        for key in ("legal_ir_view", "target_component", "target_view"):
            claimed_view = str(item.get(key) or "").strip()
            if claimed_view and claimed_view != record.legal_ir_view:
                return {}, None
        item.setdefault("guidance_id", record.record_id)
        item.setdefault("sample_id", record.obligation_id)
        item.setdefault("legal_ir_view", record.legal_ir_view)
        item.setdefault("target_component", record.legal_ir_view)
        item.setdefault("partition", record.partition.value)
        item.setdefault("proof_feedback_version_fingerprint", record.version_fingerprint)
        item.setdefault("proof_checked", record.positive)
        item.setdefault("trusted", record.eligible_for_training)
        item.setdefault("source", "legal_ir_proof_feedback")
        item.setdefault("schema_version", LEGAL_IR_PROOF_FEEDBACK_SCHEMA_VERSION)
    return item, record


def _feedback_id(
    item: Mapping[str, Any],
    record: Optional[LegalIRProofFeedbackRecord],
) -> str:
    if record is not None:
        return record.record_id
    for key in ("guidance_id", "record_id", "feedback_id", "receipt_id"):
        value = str(item.get(key) or "").strip()
        if value:
            if len(value) <= 128 and all(
                character.isalnum() or character in "._:/@+-"
                for character in value
            ):
                return value
            return "trusted-feedback-" + hashlib.sha256(
                value.encode("utf-8")
            ).hexdigest()
    payload = json.dumps(_json_ready(item), ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "trusted-feedback-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sample_id(
    item: Mapping[str, Any],
    record: Optional[LegalIRProofFeedbackRecord],
) -> str:
    for key in ("sample_id", "training_sample_id", "legal_sample_id"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return record.obligation_id if record is not None else ""


def _apply_bounded_sample_update(
    autoencoder: AdaptiveModalAutoencoder,
    item: Mapping[str, Any],
    sample: Any,
    *,
    feedback_id: str,
    learning_rate: float,
) -> bool:
    """Update only bounded reusable view heads, never sample memory.

    The legacy guidance path invokes the complete multi-thousand-feature Legal
    IR training step.  Trusted feedback needs a narrower operation: one global
    view head plus at most 48 source-free categorical features, some of which
    are selected from the referenced sample's deterministic structural view.
    This makes the update genuinely sample-aware while keeping both work and
    state growth bounded.
    """

    feature_bus = build_trusted_hammer_leanstral_feature_bus(
        item,
        require_trusted=False,
    )
    target = autoencoder._leanstral_guidance_target_distribution(
        feature_bus.learning_payload
    )
    if not target:
        return False
    sample_features = autoencoder._legal_ir_view_feature_keys_for(sample)
    bounded_sample_features = [
        str(feature)
        for feature in sample_features
        if _safe_structural_feature_key(feature)
    ][:24]
    feature_keys = list(feature_bus.feature_keys) + bounded_sample_features
    global_changed = autoencoder._nudge_legal_ir_view_global_logits_toward_distribution(
        target,
        learning_rate=learning_rate,
    )
    feature_count = autoencoder._nudge_leanstral_guidance_feature_logits(
        feature_keys[:48],
        target,
        learning_rate=learning_rate,
    )
    if not global_changed or feature_count <= 0 or not bounded_sample_features:
        return False
    autoencoder.state.applied_leanstral_guidance_ids.append(feedback_id)
    return True


def _safe_structural_feature_key(value: Any) -> bool:
    text = str(value or "")
    lowered = text.lower()
    return (
        bool(text)
        and len(text.encode("utf-8")) <= 256
        and text.startswith(("legal-ir:", "compiler-contract:", "logic-view:"))
        and not any(
            marker in lowered
            for marker in (
                "raw-source",
                "raw_source",
                "source-span",
                "source-text",
                "source_copy",
                "source_span",
                "source_text",
                "token:",
            )
        )
    )


def _partition(
    item: Mapping[str, Any],
    record: Optional[LegalIRProofFeedbackRecord],
) -> str:
    if record is not None:
        claimed = item.get("partition") or item.get("feedback_partition")
        claimed_text = str(
            getattr(claimed, "value", claimed) or ""
        ).strip().lower()
        if claimed_text and claimed_text != record.partition.value:
            if ProofFeedbackPartition.HOLDOUT.value in {
                claimed_text,
                record.partition.value,
            }:
                return ProofFeedbackPartition.HOLDOUT.value
            return "mismatch"
        return record.partition.value
    value = item.get("partition") or item.get("feedback_partition")
    return str(getattr(value, "value", value) or "").strip().lower()


def _feedback_is_trusted(
    item: Mapping[str, Any],
    record: Optional[LegalIRProofFeedbackRecord],
) -> bool:
    if record is not None:
        # A trusted receipt cannot override an explicit rejection on the
        # guidance envelope to which it is bound.
        if any(
            _truth(item.get(key)) is False
            for key in ("accepted", "trusted")
            if key in item
        ):
            return False
        return (
            record.trust_status == ProofFeedbackTrustStatus.TRUSTED
            and record.eligible_for_training
            and record.positive
        )
    trusted = any(_truth(item.get(key)) is True for key in ("accepted", "trusted"))
    if not trusted or any(_truth(item.get(key)) is False for key in ("accepted", "trusted") if key in item):
        return False
    source = str(item.get("source") or "").lower()
    schema = str(item.get("schema_version") or "").lower()
    hammer = "hammer" in source or "hammer" in schema or bool(item.get("backend_statuses"))
    verifier_confirmed = any(_truth(item.get(key)) is True for key in _VERIFIER_KEYS)
    if hammer:
        reconstruction_verified = str(item.get("reconstruction_status") or "").lower() in {
            "kernel_verified",
            "native_reconstruction",
            "verified",
        }
        proved = _truth(item.get("proved")) is True
        return verifier_confirmed or proved or reconstruction_verified
    # A Leanstral acceptance is a proposal until a verifier explicitly confirms it.
    return "leanstral" in source and verifier_confirmed


def _truth(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True if float(value) == 1.0 else False if float(value) == 0.0 else None
    text = str(value or "").strip().lower()
    return True if text in _TRUE else False if text in _FALSE else None


def _source_copy_block_reason(item: Mapping[str, Any], *, maximum_penalty: float) -> str:
    for key, value in _walk_key_values(item):
        lowered = key.lower()
        if lowered in _SOURCE_COPY_BOOLEAN_GUARDS and _truth(value) is True:
            return "source_copy_rejected"
        if lowered in {"source_copy_guard_passed", "source_copy_passed"} and _truth(value) is False:
            return "source_copy_guard_failed"
        if lowered in {"source_copy_penalty", "source_copy_reward_hack_penalty", "source_span_copy_ratio"}:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return "source_copy_metric_invalid"
            if not math.isfinite(number) or number > float(maximum_penalty):
                return "source_copy_penalty_exceeded"
        if lowered in {"rejection_reason", "rejection_reasons"}:
            values = value if isinstance(value, Sequence) and not isinstance(value, str) else (value,)
            markers = {_atom(child) for child in values}
            if markers.intersection(_SOURCE_COPY_REJECTION_MARKERS):
                return "source_copy_rejected"
    return ""


def _walk_key_values(value: Any, *, depth: int = 0) -> Iterable[tuple[str, Any]]:
    if depth > 5:
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key), child
            yield from _walk_key_values(child, depth=depth + 1)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for child in value[:64]:
            yield from _walk_key_values(child, depth=depth + 1)


def _atom(value: Any) -> str:
    return "_".join(str(value or "").strip().lower().replace("-", "_").split())


def _ablation_gate(
    evidence: TrustedFeedbackAblationEvidence | Mapping[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    if evidence is None:
        return {}, False
    payload = evidence.to_dict() if isinstance(evidence, TrustedFeedbackAblationEvidence) else dict(evidence)
    if str(payload.get("schema_version") or "") != TRUSTED_FEEDBACK_ABLATION_SCHEMA_VERSION:
        return _json_ready(payload), False
    try:
        improvement = float(payload.get("heldout_improvement"))
        minimum = float(payload.get("minimum_improvement"))
    except (TypeError, ValueError):
        return _json_ready(payload), False
    heldout_ids = {str(value) for value in payload.get("heldout_sample_ids", ()) if str(value)}
    training_ids = {str(value) for value in payload.get("training_sample_ids", ()) if str(value)}
    recomputed = (
        bool(payload.get("holdout_id"))
        and bool(heldout_ids)
        and not heldout_ids.intersection(training_ids)
        and _truth(payload.get("fixed_sample_set")) is True
        and _truth(payload.get("holdout_isolated")) is True
        and math.isfinite(improvement)
        and math.isfinite(minimum)
        and improvement > 0.0
        and improvement >= max(0.0, minimum)
        and _truth(payload.get("source_copy_guard_passed")) is True
        and _truth(payload.get("symbolic_validity_guard_passed")) is True
        and _truth(payload.get("metric_guardrails_passed")) is True
        and not payload.get("block_reasons")
    )
    # Never trust a serialized convenience boolean without recomputing the gate.
    return _json_ready(payload), bool(recomputed)


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(child) for key, child in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_ready(child) for child in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


__all__ = [
    "DEFAULT_TRUSTED_FEEDBACK_MAX_LEARNING_RATE",
    "DEFAULT_TRUSTED_FEEDBACK_MAX_UPDATES",
    "TRUSTED_FEEDBACK_TRAINER_SCHEMA_VERSION",
    "TrustedFeedbackTrainer",
    "TrustedFeedbackTrainerConfig",
    "TrustedFeedbackUpdateReport",
    "apply_trusted_feedback_weight_updates",
    "train_trusted_feedback",
]
