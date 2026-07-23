"""Fail-closed replay of historical compiler-guidance distillation reports.

Historical ``*.compiler-guidance-distillation.json`` files were produced as
operator hints.  In particular, their old ``promotion_allowed`` field is not a
signature and is not current promotion evidence.  This module inventories the
complete historical corpus and treats that field only as a way to select
records for replay.

A selected report can emit a feature update only after two independent
boundaries have passed:

* the historical report has a current, supported schema, an authentic
  signature, internally consistent promotion fields, source-free contents,
  and compiler/holdout/lineage bindings matching the replay policy; and
* an injected current revalidator returns a separately signed receipt proving
  reconstruction and current compiler, canonicalization, fixed-holdout,
  proof, provenance, and anti-copy checks.

Public replay state contains digests, bounded identifiers, counters, and
rejection classes.  Raw reports are retained only in the private in-memory
candidate passed to the revalidator; prompts, decoded text, source previews,
and source-derived terms are never copied into an inventory, outcome, cache,
or feature update.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol


LEGAL_IR_GUIDANCE_REPLAY_SCHEMA_VERSION: Final = (
    "legal-ir-compiler-guidance-replay-v1"
)
LEGAL_IR_GUIDANCE_INVENTORY_SCHEMA_VERSION: Final = (
    "legal-ir-compiler-guidance-inventory-v1"
)
LEGAL_IR_GUIDANCE_CANDIDATE_SCHEMA_VERSION: Final = (
    "legal-ir-compiler-guidance-replay-candidate-v1"
)
LEGAL_IR_GUIDANCE_REVALIDATION_SCHEMA_VERSION: Final = (
    "legal-ir-compiler-guidance-current-revalidation-v1"
)
LEGAL_IR_GUIDANCE_FEATURE_UPDATE_SCHEMA_VERSION: Final = (
    "legal-ir-compiler-guidance-bounded-feature-update-v1"
)

CANONICAL_HISTORICAL_REPORT_COUNT: Final = 142
CANONICAL_HISTORICAL_PROMOTION_CANDIDATE_COUNT: Final = 17
DEFAULT_MAX_REPORT_BYTES: Final = 2 * 1024 * 1024
HARD_MAX_FEATURE_DELTAS: Final = 64

_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,191}$")
_SAFE_FEATURE_PREFIXES = (
    "compiler-quality:",
    "contract:",
    "family:",
    "legal-ir-view:",
    "logic-signature:",
    "proof-head:",
    "repair-lane:",
    "route:",
    "semantic-slot:",
)
_SOURCE_FEATURE_MARKERS = (
    "decoded",
    "prompt",
    "raw-source",
    "raw_source",
    "sample-id",
    "sample-memory",
    "sample_id",
    "source-copy",
    "source-span",
    "source-text",
    "source_copy",
    "source_span",
    "source_text",
    "text-preview",
    "text_preview",
    "token:",
    "token2:",
    "token3:",
)
_SOURCE_KEYS = frozenset(
    {
        "completion",
        "decoded",
        "decoded_modal_text",
        "decoded_text",
        "generated_text",
        "model_output",
        "prompt",
        "prompts",
        "raw",
        "raw_prompt",
        "raw_source",
        "raw_source_text",
        "source_span",
        "source_spans",
        "source_text",
        "statement",
        "statute_text",
        "text",
        "text_preview",
    }
)
_SOURCE_COLLECTION_KEYS = frozenset(
    {
        "semantic_overlay_terms",
        "top_semantic_overlay_terms",
    }
)
_SOURCE_POLICY_KEYS = frozenset(
    {
        "contains_source_material",
        "source_copy_policy_version",
        "source_copy_valid",
    }
)


class GuidanceReplayError(ValueError):
    """Base error for malformed replay configuration or input."""


class GuidanceInventoryError(GuidanceReplayError):
    """The historical report corpus could not be inventoried."""


class GuidanceRevalidationError(GuidanceReplayError):
    """A current revalidation receipt is malformed."""


class GuidanceReplayRejection(str, Enum):
    """Stable, source-free reasons why a historical report cannot update state."""

    HISTORICAL_PROMOTION_NOT_ALLOWED = "historical_promotion_not_allowed"
    INVALID_REPORT = "invalid_report"
    INVENTORY_MISMATCH = "inventory_mismatch"
    SCHEMA_MISMATCH = "schema_mismatch"
    UNSIGNED = "unsigned"
    STALE = "stale"
    CONTRADICTORY = "contradictory"
    SOURCE_BEARING = "source_bearing"
    LINEAGE_MISMATCH = "lineage_mismatch"
    REVALIDATION_UNAVAILABLE = "revalidation_unavailable"
    RECEIPT_MISMATCH = "receipt_mismatch"
    RECEIPT_UNSIGNED = "receipt_unsigned"
    NONRECONSTRUCTIBLE = "nonreconstructible"
    COMPILER_REJECTED = "compiler_rejected"
    CANONICALIZATION_REJECTED = "canonicalization_rejected"
    FIXED_HOLDOUT_REJECTED = "fixed_holdout_rejected"
    PROOF_REJECTED = "proof_rejected"
    PROVENANCE_REJECTED = "provenance_rejected"
    SOURCE_COPY_REJECTED = "source_copy_rejected"
    FEATURE_UPDATE_INVALID = "feature_update_invalid"
    REVALIDATOR_ERROR = "revalidator_error"


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GuidanceReplayError("non-finite values are not canonical JSON")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise GuidanceReplayError(
        f"value of type {type(value).__name__} is not canonical JSON"
    )


def canonical_guidance_replay_json(value: Any) -> str:
    """Encode a finite JSON value using the replay content-address format."""

    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def guidance_replay_digest(value: Any, *, prefixed: bool = True) -> str:
    digest = hashlib.sha256(
        canonical_guidance_replay_json(value).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}" if prefixed else digest


def _path_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _without_signature(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _json_ready(value)
        for key, value in payload.items()
        if str(key) not in {"signature", "report_sha256", "receipt_sha256"}
    }


def sign_guidance_replay_payload(
    payload: Mapping[str, Any],
    *,
    signer_id: str,
    secret: str | bytes,
) -> dict[str, str]:
    """Create the supported HMAC signature envelope.

    Production callers normally obtain the secret from an external trust
    store.  It is deliberately never included in a policy or replay report.
    """

    signer = _safe_identifier(signer_id, name="signer_id")
    key = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if not key:
        raise GuidanceReplayError("signature secret must be non-empty")
    message = canonical_guidance_replay_json(_without_signature(payload)).encode(
        "utf-8"
    )
    return {
        "algorithm": "hmac-sha256",
        "signer_id": signer,
        "value": hmac.new(key, message, hashlib.sha256).hexdigest(),
    }


def _safe_identifier(value: Any, *, name: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_IDENTIFIER_RE.fullmatch(text):
        raise GuidanceReplayError(f"{name} must be a bounded identifier")
    return text


def _normalized_digest(value: Any, *, name: str, required: bool = True) -> str:
    text = str(value or "").strip().lower()
    if not text and not required:
        return ""
    if not _SHA256_RE.fullmatch(text):
        raise GuidanceReplayError(f"{name} must be a SHA-256 digest")
    return text if text.startswith("sha256:") else f"sha256:{text}"


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(_json_ready(value))


def _verify_signature(
    payload: Mapping[str, Any],
    trusted_signers: Mapping[str, str | bytes],
) -> bool:
    signature = payload.get("signature")
    if not isinstance(signature, Mapping):
        return False
    if str(signature.get("algorithm") or "") != "hmac-sha256":
        return False
    signer_id = str(signature.get("signer_id") or "")
    secret = trusted_signers.get(signer_id)
    if secret is None:
        return False
    try:
        expected = sign_guidance_replay_payload(
            payload,
            signer_id=signer_id,
            secret=secret,
        )["value"]
    except GuidanceReplayError:
        return False
    supplied = str(signature.get("value") or "").lower()
    return bool(supplied) and hmac.compare_digest(expected, supplied)


def _looks_source_like(value: str) -> bool:
    text = str(value or "").strip()
    lowered = text.lower()
    words = re.findall(r"[A-Za-z0-9']+", text)
    return (
        any(marker in lowered for marker in _SOURCE_FEATURE_MARKERS)
        or len(text.encode("utf-8")) > 512
        or len(words) >= 8
        or (len(words) >= 5 and text.endswith((".", ";", "?", "!")))
    )


def _path_key(key: str) -> str:
    if len(key) <= 80 and re.fullmatch(r"[A-Za-z0-9_.:-]+", key):
        return key
    return "{key-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16] + "}"


def _source_bearing_paths(value: Any, *, path: str = "$") -> tuple[str, ...]:
    """Return bounded field paths, never the sensitive values themselves."""

    found: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            lowered = key.strip().lower().replace("-", "_")
            child = f"{path}.{_path_key(key)}"
            key_words = re.findall(r"[A-Za-z0-9']+", key)
            if not _SAFE_IDENTIFIER_RE.fullmatch(key) and (
                len(key.encode("utf-8")) > 512
                or len(key_words) >= 8
                or (len(key_words) >= 5 and key.endswith((".", ";", "?", "!")))
            ):
                found.append(child)
                continue
            if lowered in _SOURCE_KEYS:
                found.append(child)
                continue
            if lowered in _SOURCE_COLLECTION_KEYS and bool(item):
                found.append(child)
                continue
            if lowered in _SOURCE_POLICY_KEYS:
                continue
            found.extend(_source_bearing_paths(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value[:128]):
            found.extend(_source_bearing_paths(item, path=f"{path}[{index}]"))
    elif isinstance(value, str) and _looks_source_like(value):
        found.append(path)
    return tuple(sorted(set(found))[:64])


def _report_is_contradictory(report: Mapping[str, Any]) -> bool:
    if report.get("promotion_allowed") is not True:
        return False
    direct_conflict = (
        report.get("has_candidates") is not True
        or str(report.get("quality_gate") or "") != "pass"
        or bool(str(report.get("promotion_block_reason") or "").strip())
        or str(report.get("recommended_mode") or "")
        != "promote_deterministic_rules"
    )
    if direct_conflict:
        return True
    attribution = report.get("guidance_attribution")
    if not isinstance(attribution, Mapping):
        return False

    def has_failed_gate(value: Any) -> bool:
        if isinstance(value, Mapping):
            if str(value.get("quality_gate") or "") == "fail":
                return True
            return any(has_failed_gate(item) for item in value.values())
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return any(has_failed_gate(item) for item in value)
        return False

    return has_failed_gate(attribution)


@dataclass(frozen=True, slots=True)
class GuidanceReplayPolicy:
    """Complete current-policy identity used to revalidate old guidance."""

    compiler_commit: str
    compiler_schema_version: str
    canonicalization_version: str
    fixed_holdout_id: str
    fixed_holdout_digest: str
    proof_policy_version: str
    provenance_policy_version: str
    source_copy_policy_version: str
    lineage_id: str
    base_state_digest: str
    trusted_signers: Mapping[str, str | bytes] = field(
        default_factory=dict, repr=False
    )
    expected_report_count: int | None = CANONICAL_HISTORICAL_REPORT_COUNT
    expected_candidate_count: int | None = (
        CANONICAL_HISTORICAL_PROMOTION_CANDIDATE_COUNT
    )
    evaluation_time: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    max_report_age_seconds: float = 180 * 24 * 60 * 60
    max_feature_deltas: int = 32

    def __post_init__(self) -> None:
        for name in (
            "compiler_commit",
            "compiler_schema_version",
            "canonicalization_version",
            "fixed_holdout_id",
            "proof_policy_version",
            "provenance_policy_version",
            "source_copy_policy_version",
            "lineage_id",
        ):
            object.__setattr__(
                self, name, _safe_identifier(getattr(self, name), name=name)
            )
        object.__setattr__(
            self,
            "fixed_holdout_digest",
            _normalized_digest(
                self.fixed_holdout_digest, name="fixed_holdout_digest"
            ),
        )
        object.__setattr__(
            self,
            "base_state_digest",
            _normalized_digest(self.base_state_digest, name="base_state_digest"),
        )
        if _parse_timestamp(self.evaluation_time) is None:
            raise GuidanceReplayError("evaluation_time must be an ISO-8601 timestamp")
        age = float(self.max_report_age_seconds)
        if not math.isfinite(age) or age < 0.0:
            raise GuidanceReplayError(
                "max_report_age_seconds must be finite and non-negative"
            )
        object.__setattr__(self, "max_report_age_seconds", age)
        limit = int(self.max_feature_deltas)
        if limit < 1 or limit > HARD_MAX_FEATURE_DELTAS:
            raise GuidanceReplayError(
                f"max_feature_deltas must be in [1, {HARD_MAX_FEATURE_DELTAS}]"
            )
        object.__setattr__(self, "max_feature_deltas", limit)
        for name in ("expected_report_count", "expected_candidate_count"):
            value = getattr(self, name)
            if value is not None and int(value) < 0:
                raise GuidanceReplayError(f"{name} must be non-negative or null")
            if value is not None:
                object.__setattr__(self, name, int(value))
        signers: dict[str, str | bytes] = {}
        for signer_id, secret in self.trusted_signers.items():
            signers[_safe_identifier(signer_id, name="trusted signer")] = secret
        object.__setattr__(self, "trusted_signers", MappingProxyType(signers))

    @property
    def fingerprint(self) -> str:
        return guidance_replay_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_state_digest": self.base_state_digest,
            "canonicalization_version": self.canonicalization_version,
            "compiler_commit": self.compiler_commit,
            "compiler_schema_version": self.compiler_schema_version,
            "evaluation_time": self.evaluation_time,
            "expected_candidate_count": self.expected_candidate_count,
            "expected_report_count": self.expected_report_count,
            "fixed_holdout_digest": self.fixed_holdout_digest,
            "fixed_holdout_id": self.fixed_holdout_id,
            "lineage_id": self.lineage_id,
            "max_feature_deltas": self.max_feature_deltas,
            "max_report_age_seconds": self.max_report_age_seconds,
            "proof_policy_version": self.proof_policy_version,
            "provenance_policy_version": self.provenance_policy_version,
            "source_copy_policy_version": self.source_copy_policy_version,
            "trusted_signer_ids": sorted(self.trusted_signers),
        }


@dataclass(frozen=True, slots=True)
class HistoricalGuidanceReport:
    """One historical artifact; raw payload is intentionally non-serializable."""

    report_id: str
    content_digest: str
    byte_count: int
    promotion_candidate: bool
    _payload: Mapping[str, Any] = field(repr=False, compare=False)
    load_error: str = ""

    @property
    def payload(self) -> Mapping[str, Any]:
        """In-memory input for a current revalidator.  Never place it in state."""

        return self._payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_count": self.byte_count,
            "content_digest": self.content_digest,
            "load_error": self.load_error,
            "promotion_candidate": self.promotion_candidate,
            "report_id": self.report_id,
        }


@dataclass(frozen=True, slots=True)
class HistoricalGuidanceInventory:
    reports: tuple[HistoricalGuidanceReport, ...]
    schema_version: str = LEGAL_IR_GUIDANCE_INVENTORY_SCHEMA_VERSION

    @property
    def report_count(self) -> int:
        return len(self.reports)

    @property
    def promotion_candidate_count(self) -> int:
        return sum(item.promotion_candidate for item in self.reports)

    @property
    def inventory_id(self) -> str:
        descriptor = {
            "reports": [
                {
                    "content_digest": item.content_digest,
                    "promotion_candidate": item.promotion_candidate,
                }
                for item in self.reports
            ],
            "schema_version": self.schema_version,
        }
        return "lir-guidance-inventory-" + guidance_replay_digest(
            descriptor, prefixed=False
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "inventory_id": self.inventory_id,
            "privacy": {
                "decoded_text_serialized": False,
                "prompts_serialized": False,
                "raw_reports_serialized": False,
                "source_text_serialized": False,
            },
            "promotion_candidate_count": self.promotion_candidate_count,
            "report_count": self.report_count,
            "reports": [item.to_dict() for item in self.reports],
            "schema_version": self.schema_version,
        }


def _report_paths(inputs: Iterable[str | Path]) -> tuple[Path, ...]:
    found: dict[str, Path] = {}
    for raw_path in inputs:
        path = Path(raw_path).expanduser()
        if path.is_dir():
            candidates = path.rglob("*.compiler-guidance-distillation.json")
        elif path.is_file():
            candidates = (path,)
        else:
            raise GuidanceInventoryError(f"historical input does not exist: {path}")
        for candidate in candidates:
            resolved = candidate.resolve()
            found[str(resolved)] = resolved
    if not found:
        raise GuidanceInventoryError("no compiler-guidance distillation reports found")
    return tuple(found[key] for key in sorted(found))


def load_historical_compiler_guidance_reports(
    inputs: Iterable[str | Path],
    *,
    max_report_bytes: int = DEFAULT_MAX_REPORT_BYTES,
) -> HistoricalGuidanceInventory:
    """Load and content-address every historical report deterministically."""

    limit = int(max_report_bytes)
    if limit < 1:
        raise GuidanceInventoryError("max_report_bytes must be positive")
    reports: list[HistoricalGuidanceReport] = []
    for path in _report_paths(inputs):
        byte_count = path.stat().st_size
        digest = _path_digest(path)
        load_error = ""
        payload: Mapping[str, Any] = {}
        if byte_count > limit:
            load_error = "report_size_limit_exceeded"
        else:
            try:
                data = path.read_bytes()
                decoded = json.loads(data)
                if not isinstance(decoded, Mapping):
                    load_error = "report_root_not_mapping"
                else:
                    payload = _freeze_mapping(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError, GuidanceReplayError):
                load_error = "report_json_invalid"
        reports.append(
            HistoricalGuidanceReport(
                report_id="historical-guidance-" + digest.split(":", 1)[1],
                content_digest=digest,
                byte_count=byte_count,
                promotion_candidate=(
                    not load_error and payload.get("promotion_allowed") is True
                ),
                _payload=payload,
                load_error=load_error,
            )
        )
    reports.sort(key=lambda item: (item.content_digest, item.report_id))
    return HistoricalGuidanceInventory(tuple(reports))


@dataclass(frozen=True, slots=True)
class GuidanceRevalidationContext:
    report_id: str
    report_digest: str
    policy_fingerprint: str
    compiler_commit: str
    compiler_schema_version: str
    canonicalization_version: str
    fixed_holdout_id: str
    fixed_holdout_digest: str
    proof_policy_version: str
    provenance_policy_version: str
    source_copy_policy_version: str
    lineage_id: str
    base_state_digest: str

    @classmethod
    def for_report(
        cls, report: HistoricalGuidanceReport, policy: GuidanceReplayPolicy
    ) -> "GuidanceRevalidationContext":
        return cls(
            report_id=report.report_id,
            report_digest=report.content_digest,
            policy_fingerprint=policy.fingerprint,
            compiler_commit=policy.compiler_commit,
            compiler_schema_version=policy.compiler_schema_version,
            canonicalization_version=policy.canonicalization_version,
            fixed_holdout_id=policy.fixed_holdout_id,
            fixed_holdout_digest=policy.fixed_holdout_digest,
            proof_policy_version=policy.proof_policy_version,
            provenance_policy_version=policy.provenance_policy_version,
            source_copy_policy_version=policy.source_copy_policy_version,
            lineage_id=policy.lineage_id,
            base_state_digest=policy.base_state_digest,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            name: str(getattr(self, name))
            for name in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class GuidanceFeatureDelta:
    """A single bounded, categorical compiler-guidance update."""

    feature_id: str
    family: str
    weight_delta: float
    support_count: int = 1
    evidence_digest: str = ""

    def __post_init__(self) -> None:
        try:
            feature_id = _safe_identifier(self.feature_id, name="feature_id")
        except GuidanceReplayError as exc:
            raise GuidanceRevalidationError(str(exc)) from exc
        lowered = feature_id.lower()
        if (
            not lowered.startswith(_SAFE_FEATURE_PREFIXES)
            or any(marker in lowered for marker in _SOURCE_FEATURE_MARKERS)
        ):
            raise GuidanceRevalidationError(
                "feature_id is not an approved source-free feature"
            )
        object.__setattr__(self, "feature_id", feature_id)
        try:
            family = _safe_identifier(self.family, name="family")
        except GuidanceReplayError as exc:
            raise GuidanceRevalidationError(str(exc)) from exc
        object.__setattr__(self, "family", family)
        if isinstance(self.weight_delta, bool):
            raise GuidanceRevalidationError("weight_delta must be numeric")
        weight = float(self.weight_delta)
        if not math.isfinite(weight) or abs(weight) > 1.0:
            raise GuidanceRevalidationError(
                "weight_delta must be finite and within [-1, 1]"
            )
        object.__setattr__(self, "weight_delta", weight)
        support = int(self.support_count)
        if support < 1 or support > 1_000_000_000:
            raise GuidanceRevalidationError("support_count is out of bounds")
        object.__setattr__(self, "support_count", support)
        if self.evidence_digest:
            try:
                digest = _normalized_digest(
                    self.evidence_digest, name="evidence_digest"
                )
            except GuidanceReplayError as exc:
                raise GuidanceRevalidationError(str(exc)) from exc
            object.__setattr__(self, "evidence_digest", digest)

    @classmethod
    def from_value(cls, value: Any) -> "GuidanceFeatureDelta":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise GuidanceRevalidationError("feature delta must be a mapping")
        return cls(
            feature_id=str(
                value.get("feature_id")
                or value.get("feature_key")
                or value.get("id")
                or ""
            ),
            family=str(value.get("family") or value.get("semantic_family") or ""),
            weight_delta=value.get(
                "weight_delta", value.get("delta", value.get("weight", 0.0))
            ),
            support_count=value.get("support_count", value.get("support", 1)),
            evidence_digest=str(value.get("evidence_digest") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_digest": self.evidence_digest,
            "family": self.family,
            "feature_id": self.feature_id,
            "support_count": self.support_count,
            "weight_delta": round(self.weight_delta, 12),
        }


@dataclass(frozen=True, slots=True)
class CurrentGuidanceRevalidation:
    """Fresh current-policy result returned by a replay revalidator."""

    report_digest: str
    policy_fingerprint: str
    compiler_commit: str
    compiler_schema_version: str
    canonicalization_version: str
    fixed_holdout_id: str
    fixed_holdout_digest: str
    proof_policy_version: str
    provenance_policy_version: str
    source_copy_policy_version: str
    lineage_id: str
    base_state_digest: str
    reconstructed: bool
    compiler_valid: bool
    schema_valid: bool
    canonicalization_valid: bool
    holdout_valid: bool
    proof_valid: bool
    provenance_valid: bool
    source_copy_valid: bool
    contradictory: bool = False
    contains_source_material: bool = False
    proof_receipt_ids: tuple[str, ...] = ()
    provenance_digest: str = ""
    feature_deltas: tuple[GuidanceFeatureDelta, ...] = ()
    signature: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_GUIDANCE_REVALIDATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "compiler_commit",
            "compiler_schema_version",
            "canonicalization_version",
            "fixed_holdout_id",
            "proof_policy_version",
            "provenance_policy_version",
            "source_copy_policy_version",
            "lineage_id",
        ):
            value = str(getattr(self, name) or "").strip()
            if value and not _SAFE_IDENTIFIER_RE.fullmatch(value):
                raise GuidanceRevalidationError(
                    f"{name} must be empty or a bounded identifier"
                )
            object.__setattr__(self, name, value)
        for name in (
            "report_digest",
            "policy_fingerprint",
            "fixed_holdout_digest",
            "base_state_digest",
            "provenance_digest",
        ):
            try:
                digest = _normalized_digest(
                    getattr(self, name), name=name, required=False
                )
            except GuidanceReplayError as exc:
                raise GuidanceRevalidationError(str(exc)) from exc
            object.__setattr__(self, name, digest)
        receipt_ids: list[str] = []
        for receipt_id in self.proof_receipt_ids:
            try:
                receipt_ids.append(
                    _safe_identifier(receipt_id, name="proof_receipt_id")
                )
            except GuidanceReplayError as exc:
                raise GuidanceRevalidationError(str(exc)) from exc
        object.__setattr__(self, "proof_receipt_ids", tuple(receipt_ids))
        object.__setattr__(
            self,
            "feature_deltas",
            tuple(GuidanceFeatureDelta.from_value(item) for item in self.feature_deltas),
        )
        object.__setattr__(self, "signature", _freeze_mapping(self.signature))
        for name in (
            "reconstructed",
            "compiler_valid",
            "schema_valid",
            "canonicalization_valid",
            "holdout_valid",
            "proof_valid",
            "provenance_valid",
            "source_copy_valid",
            "contradictory",
            "contains_source_material",
        ):
            if not isinstance(getattr(self, name), bool):
                raise GuidanceRevalidationError(f"{name} must be boolean")

    @classmethod
    def from_value(cls, value: Any) -> "CurrentGuidanceRevalidation":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise GuidanceRevalidationError(
                "current revalidation result must be a mapping"
            )
        gates = value.get("gates")
        gates = gates if isinstance(gates, Mapping) else {}

        def boolean(name: str, *aliases: str) -> bool:
            for key in (name, *aliases):
                if key in value:
                    return value[key] is True
                if key in gates:
                    return gates[key] is True
            return False

        raw_deltas = value.get("feature_deltas", value.get("feature_updates", ()))
        if not isinstance(raw_deltas, Sequence) or isinstance(
            raw_deltas, (str, bytes, bytearray)
        ):
            raise GuidanceRevalidationError("feature_deltas must be a sequence")
        raw_receipts = value.get("proof_receipt_ids", ())
        if not isinstance(raw_receipts, Sequence) or isinstance(
            raw_receipts, (str, bytes, bytearray)
        ):
            raise GuidanceRevalidationError(
                "proof_receipt_ids must be a sequence"
            )
        return cls(
            report_digest=str(
                value.get("report_digest")
                or value.get("candidate_digest")
                or ""
            ),
            policy_fingerprint=str(value.get("policy_fingerprint") or ""),
            compiler_commit=str(value.get("compiler_commit") or ""),
            compiler_schema_version=str(
                value.get("compiler_schema_version")
                or value.get("compiler_schema")
                or ""
            ),
            canonicalization_version=str(
                value.get("canonicalization_version") or ""
            ),
            fixed_holdout_id=str(value.get("fixed_holdout_id") or ""),
            fixed_holdout_digest=str(value.get("fixed_holdout_digest") or ""),
            proof_policy_version=str(value.get("proof_policy_version") or ""),
            provenance_policy_version=str(
                value.get("provenance_policy_version") or ""
            ),
            source_copy_policy_version=str(
                value.get("source_copy_policy_version") or ""
            ),
            lineage_id=str(value.get("lineage_id") or ""),
            base_state_digest=str(value.get("base_state_digest") or ""),
            reconstructed=boolean("reconstructed", "reconstruction_valid"),
            compiler_valid=boolean("compiler_valid", "compiler_passed"),
            schema_valid=boolean("schema_valid", "schema_passed"),
            canonicalization_valid=boolean(
                "canonicalization_valid", "canonicalization_passed"
            ),
            holdout_valid=boolean(
                "holdout_valid", "fixed_holdout_valid", "holdout_passed"
            ),
            proof_valid=boolean("proof_valid", "proof_passed"),
            provenance_valid=boolean(
                "provenance_valid", "provenance_passed"
            ),
            source_copy_valid=boolean(
                "source_copy_valid",
                "source_copy_passed",
                "anti_copy_passed",
            ),
            contradictory=boolean("contradictory"),
            contains_source_material=boolean("contains_source_material"),
            proof_receipt_ids=tuple(str(item) for item in raw_receipts),
            provenance_digest=str(value.get("provenance_digest") or ""),
            feature_deltas=tuple(
                GuidanceFeatureDelta.from_value(item) for item in raw_deltas
            ),
            signature=_freeze_mapping(
                value.get("signature")
                if isinstance(value.get("signature"), Mapping)
                else {}
            ),
            schema_version=str(value.get("schema_version") or ""),
        )

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.to_dict().items()
            if key != "signature"
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_state_digest": self.base_state_digest,
            "canonicalization_valid": self.canonicalization_valid,
            "canonicalization_version": self.canonicalization_version,
            "compiler_commit": self.compiler_commit,
            "compiler_schema_version": self.compiler_schema_version,
            "compiler_valid": self.compiler_valid,
            "contains_source_material": self.contains_source_material,
            "contradictory": self.contradictory,
            "feature_deltas": [item.to_dict() for item in self.feature_deltas],
            "fixed_holdout_digest": self.fixed_holdout_digest,
            "fixed_holdout_id": self.fixed_holdout_id,
            "holdout_valid": self.holdout_valid,
            "lineage_id": self.lineage_id,
            "policy_fingerprint": self.policy_fingerprint,
            "proof_policy_version": self.proof_policy_version,
            "proof_receipt_ids": list(self.proof_receipt_ids),
            "proof_valid": self.proof_valid,
            "provenance_digest": self.provenance_digest,
            "provenance_policy_version": self.provenance_policy_version,
            "provenance_valid": self.provenance_valid,
            "reconstructed": self.reconstructed,
            "report_digest": self.report_digest,
            "schema_valid": self.schema_valid,
            "schema_version": self.schema_version,
            "signature": _json_ready(self.signature),
            "source_copy_policy_version": self.source_copy_policy_version,
            "source_copy_valid": self.source_copy_valid,
        }


class GuidanceRevalidator(Protocol):
    def __call__(
        self,
        report: HistoricalGuidanceReport,
        context: GuidanceRevalidationContext,
    ) -> CurrentGuidanceRevalidation | Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class BoundedGuidanceFeatureUpdate:
    """Content-addressed update packet; applying it is a separate transaction."""

    update_id: str
    report_digest: str
    policy_fingerprint: str
    base_state_digest: str
    lineage_id: str
    proof_receipt_ids: tuple[str, ...]
    provenance_digest: str
    feature_deltas: tuple[GuidanceFeatureDelta, ...]
    schema_version: str = LEGAL_IR_GUIDANCE_FEATURE_UPDATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_state_digest": self.base_state_digest,
            "bounded": True,
            "capacity_family": "compiler_guidance",
            "feature_delta_count": len(self.feature_deltas),
            "feature_deltas": [item.to_dict() for item in self.feature_deltas],
            "lineage_id": self.lineage_id,
            "policy_fingerprint": self.policy_fingerprint,
            "proof_receipt_ids": list(self.proof_receipt_ids),
            "provenance_digest": self.provenance_digest,
            "report_digest": self.report_digest,
            "schema_version": self.schema_version,
            "update_id": self.update_id,
        }


@dataclass(frozen=True, slots=True)
class GuidanceReportAudit:
    report_id: str
    report_digest: str
    promotion_candidate: bool
    rejection_reasons: tuple[str, ...]
    source_bearing_field_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "promotion_candidate": self.promotion_candidate,
            "rejection_reasons": list(self.rejection_reasons),
            "report_digest": self.report_digest,
            "report_id": self.report_id,
            "source_bearing_field_paths": list(self.source_bearing_field_paths),
        }


@dataclass(frozen=True, slots=True)
class GuidanceReplayOutcome:
    report_id: str
    report_digest: str
    accepted: bool
    rejection_reasons: tuple[str, ...]
    feature_update: BoundedGuidanceFeatureUpdate | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "feature_update": (
                self.feature_update.to_dict() if self.feature_update else None
            ),
            "rejection_reasons": list(self.rejection_reasons),
            "report_digest": self.report_digest,
            "report_id": self.report_id,
        }


@dataclass(frozen=True, slots=True)
class GuidanceReplayReport:
    inventory_id: str
    policy_fingerprint: str
    audited_report_count: int
    replay_candidate_count: int
    audits: tuple[GuidanceReportAudit, ...]
    outcomes: tuple[GuidanceReplayOutcome, ...]
    inventory_errors: tuple[str, ...] = ()
    schema_version: str = LEGAL_IR_GUIDANCE_REPLAY_SCHEMA_VERSION

    @property
    def accepted_count(self) -> int:
        return sum(item.accepted for item in self.outcomes)

    @property
    def rejected_candidate_count(self) -> int:
        return len(self.outcomes) - self.accepted_count

    @property
    def feature_updates(self) -> tuple[BoundedGuidanceFeatureUpdate, ...]:
        return tuple(
            item.feature_update
            for item in self.outcomes
            if item.feature_update is not None
        )

    def to_dict(self) -> dict[str, Any]:
        reason_counts: Counter[str] = Counter()
        candidate_audits: list[GuidanceReportAudit] = []
        for audit in self.audits:
            reason_counts.update(set(audit.rejection_reasons))
            if audit.promotion_candidate:
                candidate_audits.append(audit)
        for index, outcome in enumerate(self.outcomes):
            preflight_reasons = (
                set(candidate_audits[index].rejection_reasons)
                if index < len(candidate_audits)
                else set()
            )
            reason_counts.update(
                set(outcome.rejection_reasons) - preflight_reasons
            )
        payload = {
            "accepted_count": self.accepted_count,
            "audited_report_count": self.audited_report_count,
            "audits": [item.to_dict() for item in self.audits],
            "feature_updates": [item.to_dict() for item in self.feature_updates],
            "inventory_errors": list(self.inventory_errors),
            "inventory_id": self.inventory_id,
            "historical_promotion_is_only_replay_eligibility": True,
            "policy_fingerprint": self.policy_fingerprint,
            "privacy": {
                "decoded_text_serialized": False,
                "prompts_serialized": False,
                "raw_reports_serialized": False,
                "source_text_serialized": False,
            },
            "rejected_candidate_count": self.rejected_candidate_count,
            "rejection_reason_counts": dict(sorted(reason_counts.items())),
            "replay_candidate_count": self.replay_candidate_count,
            "replay_outcomes": [item.to_dict() for item in self.outcomes],
            "schema_version": self.schema_version,
        }
        payload["report_sha256"] = guidance_replay_digest(payload)
        return payload


def _historical_preflight(
    report: HistoricalGuidanceReport,
    policy: GuidanceReplayPolicy,
) -> tuple[list[str], tuple[str, ...]]:
    payload = report.payload
    reasons: list[str] = []
    if report.load_error:
        reasons.append(GuidanceReplayRejection.INVALID_REPORT.value)
        return reasons, ()
    if str(payload.get("schema_version") or "") != (
        LEGAL_IR_GUIDANCE_CANDIDATE_SCHEMA_VERSION
    ):
        reasons.append(GuidanceReplayRejection.SCHEMA_MISMATCH.value)
    if not _verify_signature(payload, policy.trusted_signers):
        reasons.append(GuidanceReplayRejection.UNSIGNED.value)
    report_time = _parse_timestamp(payload.get("created_at"))
    evaluation_time = _parse_timestamp(policy.evaluation_time)
    if (
        report_time is None
        or evaluation_time is None
        or report_time > evaluation_time
        or (evaluation_time - report_time).total_seconds()
        > policy.max_report_age_seconds
        or str(payload.get("compiler_commit") or "") != policy.compiler_commit
        or str(payload.get("compiler_schema_version") or "")
        != policy.compiler_schema_version
    ):
        reasons.append(GuidanceReplayRejection.STALE.value)
    if _report_is_contradictory(payload):
        reasons.append(GuidanceReplayRejection.CONTRADICTORY.value)
    source_paths = _source_bearing_paths(payload)
    if source_paths:
        reasons.append(GuidanceReplayRejection.SOURCE_BEARING.value)
    bindings = {
        "canonicalization_version": policy.canonicalization_version,
        "fixed_holdout_digest": policy.fixed_holdout_digest,
        "fixed_holdout_id": policy.fixed_holdout_id,
        "lineage_id": policy.lineage_id,
    }
    if any(str(payload.get(name) or "") != expected for name, expected in bindings.items()):
        reasons.append(GuidanceReplayRejection.LINEAGE_MISMATCH.value)
    return list(dict.fromkeys(reasons)), source_paths


def _receipt_rejections(
    receipt: CurrentGuidanceRevalidation,
    *,
    report: HistoricalGuidanceReport,
    policy: GuidanceReplayPolicy,
) -> list[str]:
    reasons: list[str] = []
    receipt_payload = receipt.to_dict()
    if receipt.schema_version != LEGAL_IR_GUIDANCE_REVALIDATION_SCHEMA_VERSION:
        reasons.append(GuidanceReplayRejection.SCHEMA_MISMATCH.value)
    if receipt.report_digest != report.content_digest:
        reasons.append(GuidanceReplayRejection.RECEIPT_MISMATCH.value)
    if (
        receipt.policy_fingerprint != policy.fingerprint
        or receipt.compiler_commit != policy.compiler_commit
        or receipt.compiler_schema_version != policy.compiler_schema_version
    ):
        reasons.append(GuidanceReplayRejection.STALE.value)
    if not _verify_signature(receipt_payload, policy.trusted_signers):
        reasons.append(GuidanceReplayRejection.RECEIPT_UNSIGNED.value)
    if (
        receipt.lineage_id != policy.lineage_id
        or receipt.base_state_digest != policy.base_state_digest
    ):
        reasons.append(GuidanceReplayRejection.LINEAGE_MISMATCH.value)
    if not receipt.reconstructed:
        reasons.append(GuidanceReplayRejection.NONRECONSTRUCTIBLE.value)
    if not receipt.compiler_valid or not receipt.schema_valid:
        reasons.append(GuidanceReplayRejection.COMPILER_REJECTED.value)
    if (
        not receipt.canonicalization_valid
        or receipt.canonicalization_version != policy.canonicalization_version
    ):
        reasons.append(GuidanceReplayRejection.CANONICALIZATION_REJECTED.value)
    if (
        not receipt.holdout_valid
        or receipt.fixed_holdout_id != policy.fixed_holdout_id
        or receipt.fixed_holdout_digest != policy.fixed_holdout_digest
    ):
        reasons.append(GuidanceReplayRejection.FIXED_HOLDOUT_REJECTED.value)
    if (
        not receipt.proof_valid
        or receipt.proof_policy_version != policy.proof_policy_version
        or not receipt.proof_receipt_ids
    ):
        reasons.append(GuidanceReplayRejection.PROOF_REJECTED.value)
    if (
        not receipt.provenance_valid
        or receipt.provenance_policy_version != policy.provenance_policy_version
        or not _SHA256_RE.fullmatch(receipt.provenance_digest.lower())
    ):
        reasons.append(GuidanceReplayRejection.PROVENANCE_REJECTED.value)
    if (
        not receipt.source_copy_valid
        or receipt.contains_source_material
        or receipt.source_copy_policy_version != policy.source_copy_policy_version
        or _source_bearing_paths(receipt_payload)
    ):
        reasons.append(GuidanceReplayRejection.SOURCE_COPY_REJECTED.value)
    if receipt.contradictory:
        reasons.append(GuidanceReplayRejection.CONTRADICTORY.value)
    if (
        not receipt.feature_deltas
        or len(receipt.feature_deltas) > policy.max_feature_deltas
        or len({item.feature_id for item in receipt.feature_deltas})
        != len(receipt.feature_deltas)
    ):
        reasons.append(GuidanceReplayRejection.FEATURE_UPDATE_INVALID.value)
    return list(dict.fromkeys(reasons))


def _feature_update(
    report: HistoricalGuidanceReport,
    receipt: CurrentGuidanceRevalidation,
    policy: GuidanceReplayPolicy,
) -> BoundedGuidanceFeatureUpdate:
    deltas = tuple(
        sorted(receipt.feature_deltas, key=lambda item: (item.family, item.feature_id))
    )
    descriptor = {
        "base_state_digest": policy.base_state_digest,
        "capacity_family": "compiler_guidance",
        "feature_deltas": [item.to_dict() for item in deltas],
        "lineage_id": policy.lineage_id,
        "policy_fingerprint": policy.fingerprint,
        "proof_receipt_ids": sorted(set(receipt.proof_receipt_ids)),
        "provenance_digest": receipt.provenance_digest,
        "report_digest": report.content_digest,
        "schema_version": LEGAL_IR_GUIDANCE_FEATURE_UPDATE_SCHEMA_VERSION,
    }
    return BoundedGuidanceFeatureUpdate(
        update_id="lir-guidance-update-"
        + guidance_replay_digest(descriptor, prefixed=False),
        report_digest=report.content_digest,
        policy_fingerprint=policy.fingerprint,
        base_state_digest=policy.base_state_digest,
        lineage_id=policy.lineage_id,
        proof_receipt_ids=tuple(sorted(set(receipt.proof_receipt_ids))),
        provenance_digest=receipt.provenance_digest,
        feature_deltas=deltas,
    )


def replay_historical_compiler_guidance(
    inventory: HistoricalGuidanceInventory,
    *,
    policy: GuidanceReplayPolicy,
    revalidator: GuidanceRevalidator | None = None,
) -> GuidanceReplayReport:
    """Audit all reports and replay only old promotion-eligible candidates."""

    inventory_errors: list[str] = []
    if (
        policy.expected_report_count is not None
        and inventory.report_count != policy.expected_report_count
    ):
        inventory_errors.append(
            "historical_report_count_mismatch:"
            f"expected={policy.expected_report_count}:actual={inventory.report_count}"
        )
    if (
        policy.expected_candidate_count is not None
        and inventory.promotion_candidate_count != policy.expected_candidate_count
    ):
        inventory_errors.append(
            "historical_candidate_count_mismatch:"
            f"expected={policy.expected_candidate_count}:"
            f"actual={inventory.promotion_candidate_count}"
        )

    audits: list[GuidanceReportAudit] = []
    candidates: list[tuple[HistoricalGuidanceReport, list[str]]] = []
    for report in inventory.reports:
        preflight, source_paths = _historical_preflight(report, policy)
        if not report.promotion_candidate:
            preflight.insert(
                0,
                GuidanceReplayRejection.HISTORICAL_PROMOTION_NOT_ALLOWED.value,
            )
        audits.append(
            GuidanceReportAudit(
                report_id=report.report_id,
                report_digest=report.content_digest,
                promotion_candidate=report.promotion_candidate,
                rejection_reasons=tuple(dict.fromkeys(preflight)),
                source_bearing_field_paths=source_paths,
            )
        )
        if report.promotion_candidate:
            candidates.append((report, preflight))

    outcomes: list[GuidanceReplayOutcome] = []
    for report, preflight in candidates:
        reasons = list(preflight)
        receipt: CurrentGuidanceRevalidation | None = None
        if revalidator is None:
            reasons.extend(
                (
                    GuidanceReplayRejection.REVALIDATION_UNAVAILABLE.value,
                    GuidanceReplayRejection.NONRECONSTRUCTIBLE.value,
                )
            )
        else:
            context = GuidanceRevalidationContext.for_report(report, policy)
            try:
                raw_receipt = revalidator(report, context)
                receipt = CurrentGuidanceRevalidation.from_value(raw_receipt)
                reasons.extend(
                    _receipt_rejections(receipt, report=report, policy=policy)
                )
            except Exception:
                # Exception messages can contain source text and are never state.
                reasons.extend(
                    (
                        GuidanceReplayRejection.REVALIDATOR_ERROR.value,
                        GuidanceReplayRejection.NONRECONSTRUCTIBLE.value,
                    )
                )
        if inventory_errors:
            reasons.append(GuidanceReplayRejection.INVENTORY_MISMATCH.value)
        reasons = list(dict.fromkeys(reasons))
        update = (
            _feature_update(report, receipt, policy)
            if not reasons and receipt is not None
            else None
        )
        outcomes.append(
            GuidanceReplayOutcome(
                report_id=report.report_id,
                report_digest=report.content_digest,
                accepted=update is not None,
                rejection_reasons=tuple(reasons),
                feature_update=update,
            )
        )

    return GuidanceReplayReport(
        inventory_id=inventory.inventory_id,
        policy_fingerprint=policy.fingerprint,
        audited_report_count=inventory.report_count,
        replay_candidate_count=inventory.promotion_candidate_count,
        audits=tuple(audits),
        outcomes=tuple(outcomes),
        inventory_errors=tuple(inventory_errors),
    )


class LegalIRGuidanceReplay:
    """Reusable coordinator around inventory loading and current revalidation."""

    def __init__(
        self,
        *,
        policy: GuidanceReplayPolicy,
        revalidator: GuidanceRevalidator | None = None,
    ) -> None:
        self.policy = policy
        self.revalidator = revalidator

    def run(
        self, inputs: Iterable[str | Path] | HistoricalGuidanceInventory
    ) -> GuidanceReplayReport:
        inventory = (
            inputs
            if isinstance(inputs, HistoricalGuidanceInventory)
            else load_historical_compiler_guidance_reports(inputs)
        )
        return replay_historical_compiler_guidance(
            inventory,
            policy=self.policy,
            revalidator=self.revalidator,
        )


# Descriptive aliases retained for callers that prefer the full task wording.
CompilerGuidanceReplayPolicy = GuidanceReplayPolicy
CompilerGuidanceRevalidation = CurrentGuidanceRevalidation
CompilerGuidanceFeatureUpdate = BoundedGuidanceFeatureUpdate
HistoricalCompilerGuidanceReplay = LegalIRGuidanceReplay


__all__ = [
    "BoundedGuidanceFeatureUpdate",
    "CANONICAL_HISTORICAL_PROMOTION_CANDIDATE_COUNT",
    "CANONICAL_HISTORICAL_REPORT_COUNT",
    "CompilerGuidanceFeatureUpdate",
    "CompilerGuidanceReplayPolicy",
    "CompilerGuidanceRevalidation",
    "CurrentGuidanceRevalidation",
    "GuidanceFeatureDelta",
    "GuidanceInventoryError",
    "GuidanceReplayError",
    "GuidanceReplayOutcome",
    "GuidanceReplayPolicy",
    "GuidanceReplayRejection",
    "GuidanceReplayReport",
    "GuidanceRevalidationContext",
    "GuidanceRevalidationError",
    "HistoricalCompilerGuidanceReplay",
    "HistoricalGuidanceInventory",
    "HistoricalGuidanceReport",
    "LEGAL_IR_GUIDANCE_CANDIDATE_SCHEMA_VERSION",
    "LEGAL_IR_GUIDANCE_FEATURE_UPDATE_SCHEMA_VERSION",
    "LEGAL_IR_GUIDANCE_INVENTORY_SCHEMA_VERSION",
    "LEGAL_IR_GUIDANCE_REPLAY_SCHEMA_VERSION",
    "LEGAL_IR_GUIDANCE_REVALIDATION_SCHEMA_VERSION",
    "LegalIRGuidanceReplay",
    "canonical_guidance_replay_json",
    "guidance_replay_digest",
    "load_historical_compiler_guidance_reports",
    "replay_historical_compiler_guidance",
    "sign_guidance_replay_payload",
]
