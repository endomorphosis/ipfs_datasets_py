"""Immutable source evidence and fail-closed sanctions snapshot validation.

This module deliberately has no network client.  Callers inject downloaded
bytes and transport evidence; the original bytes remain the authority for all
parsed records and content identities.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType

from ....logic.crypto_ir.compliance.models import SanctionsSnapshot

DEFAULT_MAXIMUM_SNAPSHOT_AGE = timedelta(hours=24)
DEFAULT_MINIMUM_COUNT_RATIO = 0.80
DEFAULT_CLOCK_SKEW = timedelta(minutes=5)


class SnapshotEvidenceStatus(StrEnum):
    """Evidence usability, intentionally distinct from an ``ALLOW`` verdict."""

    CURRENT = "current"
    UNKNOWN = "unknown"
    STALE = "stale"


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SnapshotDiagnostic:
    """A stable, machine-readable parser or validator finding."""

    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.strip():
            raise ValueError("diagnostic code must be non-empty and trimmed")
        if not self.message or self.message != self.message.strip():
            raise ValueError("diagnostic message must be non-empty and trimmed")
        if not isinstance(self.severity, DiagnosticSeverity):
            object.__setattr__(self, "severity", DiagnosticSeverity(self.severity))


@dataclass(frozen=True, slots=True)
class PublishedHashEvidence:
    """A publisher- or transport-supplied digest, without implied verification."""

    algorithm: str
    value: str
    source: str
    verified: bool = False

    def __post_init__(self) -> None:
        algorithm = self.algorithm.strip().lower().replace("-", "")
        if algorithm not in {"sha256", "sha384", "sha512"}:
            raise ValueError(f"unsupported published hash algorithm: {self.algorithm}")
        expected = {"sha256": 64, "sha384": 96, "sha512": 128}[algorithm]
        value = self.value.strip().lower()
        if len(value) != expected or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"invalid {algorithm} published hash")
        if not self.source or self.source != self.source.strip():
            raise ValueError("published hash source must be non-empty and trimmed")
        if type(self.verified) is not bool:
            raise ValueError("published hash verified must be a boolean")
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class SignatureEvidence:
    """Detached signature evidence retained exactly as supplied by a transport."""

    scheme: str
    value: bytes
    source: str
    verification: str = "not_verified"

    def __post_init__(self) -> None:
        if not self.scheme or self.scheme != self.scheme.strip():
            raise ValueError("signature scheme must be non-empty and trimmed")
        if type(self.value) is not bytes or not self.value:
            raise ValueError("signature value must be non-empty bytes")
        if not self.source or self.source != self.source.strip():
            raise ValueError("signature source must be non-empty and trimmed")
        if self.verification not in {"not_verified", "verified", "invalid"}:
            raise ValueError("unsupported signature verification state")


def _instant(value: str | datetime | None, name: str) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str:
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO-8601 instant") from exc
    else:
        raise TypeError(f"{name} must be a string or datetime")
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    parsed = parsed.astimezone(UTC)
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_instant(value: str) -> datetime:
    """Parse a normalized snapshot instant."""

    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(candidate).astimezone(UTC)


def raw_cid(data: bytes) -> str:
    """Return a dependency-free CIDv1 for raw bytes using sha2-256."""

    digest = hashlib.sha256(data).digest()
    # CIDv1, raw multicodec (0x55), sha2-256 multihash (0x12, length 0x20).
    binary = b"\x01\x55\x12\x20" + digest
    return "b" + base64.b32encode(binary).decode("ascii").rstrip("=").lower()


@dataclass(frozen=True, slots=True)
class SnapshotSource:
    """Untouched downloaded bytes and all available acquisition evidence."""

    raw_bytes: bytes
    source_url: str
    transport: str
    retrieved_at: str | datetime
    published_at: str | datetime | None = None
    effective_at: str | datetime | None = None
    transport_metadata: Mapping[str, str] = field(default_factory=dict)
    published_hashes: tuple[PublishedHashEvidence, ...] = ()
    signatures: tuple[SignatureEvidence, ...] = ()
    content_sha256: str = field(init=False)
    cid: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.raw_bytes) is not bytes:
            raise TypeError("raw_bytes must be bytes")
        if not self.raw_bytes:
            raise ValueError("raw_bytes must not be empty")
        for name in ("source_url", "transport"):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{name} must be a non-empty trimmed string")
        object.__setattr__(
            self, "retrieved_at", _instant(self.retrieved_at, "retrieved_at")
        )
        object.__setattr__(
            self, "published_at", _instant(self.published_at, "published_at")
        )
        object.__setattr__(
            self, "effective_at", _instant(self.effective_at, "effective_at")
        )
        metadata: dict[str, str] = {}
        for key, value in self.transport_metadata.items():
            if type(key) is not str or type(value) is not str or not key:
                raise ValueError("transport_metadata must contain non-empty string keys")
            metadata[key] = value
        object.__setattr__(self, "transport_metadata", MappingProxyType(metadata))
        object.__setattr__(self, "published_hashes", tuple(self.published_hashes))
        object.__setattr__(self, "signatures", tuple(self.signatures))
        digest = hashlib.sha256(self.raw_bytes).hexdigest()
        object.__setattr__(self, "content_sha256", f"sha256:{digest}")
        object.__setattr__(self, "cid", raw_cid(self.raw_bytes))


@dataclass(frozen=True, slots=True)
class ParsedSanctionsSnapshot:
    """Parser output that preserves evidence even when the schema is unusable."""

    source: SnapshotSource
    parser_identity: str
    parser_version: str
    schema_identity: str
    snapshot: SanctionsSnapshot | None
    declared_entry_count: int | None
    parsed_entry_count: int
    digital_identifier_count: int
    diagnostics: tuple[SnapshotDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        for name in ("parser_identity", "parser_version", "schema_identity"):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{name} must be a non-empty trimmed string")
        for name in ("parsed_entry_count", "digital_identifier_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.declared_entry_count is not None and (
            type(self.declared_entry_count) is not int
            or self.declared_entry_count < 0
        ):
            raise ValueError("declared_entry_count must be a non-negative integer")
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def snapshot_cid(self) -> str:
        return self.source.cid

    @property
    def has_errors(self) -> bool:
        return any(item.severity is DiagnosticSeverity.ERROR for item in self.diagnostics)


@dataclass(frozen=True, slots=True)
class SnapshotDelta:
    """Deterministic designation and identifier changes between two revisions."""

    previous_snapshot_id: str
    current_snapshot_id: str
    added_designation_ids: tuple[str, ...]
    removed_designation_ids: tuple[str, ...]
    changed_designation_ids: tuple[str, ...]
    added_identifier_keys: tuple[tuple[str, str, str, str], ...]
    removed_identifier_keys: tuple[tuple[str, str, str, str], ...]

    @classmethod
    def between(
        cls,
        previous: ParsedSanctionsSnapshot,
        current: ParsedSanctionsSnapshot,
    ) -> SnapshotDelta:
        if previous.snapshot is None or current.snapshot is None:
            raise ValueError("both parsed records must contain usable snapshots")
        old = {item.designation_id: item for item in previous.snapshot.designations}
        new = {item.designation_id: item for item in current.snapshot.designations}
        added = tuple(sorted(set(new) - set(old)))
        removed = tuple(sorted(set(old) - set(new)))
        changed = tuple(
            sorted(
                key
                for key in set(old) & set(new)
                if old[key].to_dict() != new[key].to_dict()
            )
        )
        old_identifiers = {
            identifier.comparison_key
            for designation in old.values()
            for identifier in designation.identifiers
        }
        new_identifiers = {
            identifier.comparison_key
            for designation in new.values()
            for identifier in designation.identifiers
        }
        return cls(
            previous_snapshot_id=previous.snapshot.snapshot_id,
            current_snapshot_id=current.snapshot.snapshot_id,
            added_designation_ids=added,
            removed_designation_ids=removed,
            changed_designation_ids=changed,
            added_identifier_keys=tuple(sorted(new_identifiers - old_identifiers)),
            removed_identifier_keys=tuple(sorted(old_identifiers - new_identifiers)),
        )


@dataclass(frozen=True, slots=True)
class SnapshotValidation:
    """Fail-closed evidence assessment; it never authorizes a transaction."""

    status: SnapshotEvidenceStatus
    diagnostics: tuple[SnapshotDiagnostic, ...]
    delta: SnapshotDelta | None = None

    @property
    def permits_allow(self) -> bool:
        """Whether this evidence may participate in a later policy ``ALLOW``."""

        return self.status is SnapshotEvidenceStatus.CURRENT


class SanctionsSnapshotValidator:
    """Validate completeness, chronology, rollback, delisting, and freshness."""

    def __init__(
        self,
        *,
        maximum_age: timedelta = DEFAULT_MAXIMUM_SNAPSHOT_AGE,
        minimum_count_ratio: float = DEFAULT_MINIMUM_COUNT_RATIO,
        clock_skew: timedelta = DEFAULT_CLOCK_SKEW,
    ) -> None:
        if maximum_age <= timedelta(0):
            raise ValueError("maximum_age must be positive")
        if not 0 < minimum_count_ratio <= 1:
            raise ValueError("minimum_count_ratio must be in (0, 1]")
        if clock_skew < timedelta(0):
            raise ValueError("clock_skew must not be negative")
        self.maximum_age = maximum_age
        self.minimum_count_ratio = minimum_count_ratio
        self.clock_skew = clock_skew

    def validate(
        self,
        current: ParsedSanctionsSnapshot,
        *,
        now: str | datetime,
        previous: ParsedSanctionsSnapshot | None = None,
    ) -> SnapshotValidation:
        diagnostics = list(current.diagnostics)
        snapshot = current.snapshot
        delta: SnapshotDelta | None = None

        if snapshot is None:
            if (
                previous is not None
                and previous.parsed_entry_count > 0
                and current.parsed_entry_count
                < previous.parsed_entry_count * self.minimum_count_ratio
            ):
                diagnostics.append(
                    SnapshotDiagnostic(
                        "snapshot.suspicious_count_drop",
                        "Entry count fell below the configured safety ratio",
                    )
                )
            diagnostics.append(
                SnapshotDiagnostic(
                    "snapshot.unparseable",
                    "No typed sanctions snapshot could be constructed",
                )
            )
            return SnapshotValidation(
                SnapshotEvidenceStatus.UNKNOWN, _dedupe(diagnostics)
            )

        if not snapshot.complete:
            diagnostics.append(
                SnapshotDiagnostic(
                    "snapshot.incomplete", "Snapshot is explicitly incomplete"
                )
            )
        if current.declared_entry_count is None:
            diagnostics.append(
                SnapshotDiagnostic(
                    "snapshot.count_missing",
                    "Publisher entry count is missing",
                )
            )
        elif current.declared_entry_count != current.parsed_entry_count:
            diagnostics.append(
                SnapshotDiagnostic(
                    "snapshot.truncated",
                    "Declared and parsed entry counts do not match",
                )
            )
        if snapshot.content_digest != current.source.content_sha256:
            diagnostics.append(
                SnapshotDiagnostic(
                    "snapshot.digest_mismatch",
                    "Typed snapshot digest does not bind the untouched source bytes",
                )
            )

        for evidence in current.source.published_hashes:
            if evidence.algorithm == "sha256" and evidence.verified:
                actual = current.source.content_sha256.removeprefix("sha256:")
                if evidence.value != actual:
                    diagnostics.append(
                        SnapshotDiagnostic(
                            "snapshot.published_hash_mismatch",
                            "Verified publisher hash does not match source bytes",
                        )
                    )
        if any(sig.verification == "invalid" for sig in current.source.signatures):
            diagnostics.append(
                SnapshotDiagnostic(
                    "snapshot.invalid_signature",
                    "At least one retained signature was verified as invalid",
                )
            )

        published = parse_instant(snapshot.published_at)
        effective = parse_instant(snapshot.effective_at)
        retrieved = parse_instant(snapshot.retrieved_at)
        at = parse_instant(_instant(now, "now"))
        if effective > retrieved + self.clock_skew or published > retrieved + self.clock_skew:
            diagnostics.append(
                SnapshotDiagnostic(
                    "snapshot.future_effective_time",
                    "Publication/effective time is after retrieval time",
                )
            )

        if previous is not None:
            if previous.snapshot is None:
                diagnostics.append(
                    SnapshotDiagnostic(
                        "snapshot.previous_unparseable",
                        "The previous snapshot is not usable rollback evidence",
                    )
                )
            else:
                old = previous.snapshot
                delta = SnapshotDelta.between(previous, current)
                if current.source.cid == previous.source.cid:
                    if snapshot.snapshot_id != old.snapshot_id:
                        diagnostics.append(
                            SnapshotDiagnostic(
                                "snapshot.replay_identity_mismatch",
                                "Identical source bytes produced a different identity",
                            )
                        )
                else:
                    if published <= parse_instant(old.published_at):
                        diagnostics.append(
                            SnapshotDiagnostic(
                                "snapshot.publication_rollback",
                                "A changed snapshot must have a later publication time",
                            )
                        )
                    if effective <= parse_instant(old.effective_at):
                        diagnostics.append(
                            SnapshotDiagnostic(
                                "snapshot.effective_time_rollback",
                                "A changed snapshot must have a later effective time",
                            )
                        )
                    if snapshot.supersedes_snapshot_id != old.snapshot_id:
                        diagnostics.append(
                            SnapshotDiagnostic(
                                "snapshot.lineage_error",
                                "Changed snapshot does not supersede the previous snapshot",
                            )
                        )
                if (
                    previous.parsed_entry_count > 0
                    and current.parsed_entry_count
                    < previous.parsed_entry_count * self.minimum_count_ratio
                ):
                    diagnostics.append(
                        SnapshotDiagnostic(
                            "snapshot.suspicious_count_drop",
                            "Entry count fell below the configured safety ratio",
                        )
                    )
                if delta.removed_designation_ids and effective <= parse_instant(
                    old.effective_at
                ):
                    diagnostics.append(
                        SnapshotDiagnostic(
                            "snapshot.delisting_time_error",
                            "Removed designations lack a later effective epoch",
                        )
                    )

        errors = tuple(
            item
            for item in diagnostics
            if item.severity is DiagnosticSeverity.ERROR
        )
        if errors:
            return SnapshotValidation(
                SnapshotEvidenceStatus.UNKNOWN, _dedupe(diagnostics), delta
            )
        if at > effective + self.maximum_age:
            diagnostics.append(
                SnapshotDiagnostic(
                    "snapshot.expired",
                    "Snapshot is older than the configured freshness window",
                    DiagnosticSeverity.WARNING,
                )
            )
            return SnapshotValidation(
                SnapshotEvidenceStatus.STALE, _dedupe(diagnostics), delta
            )
        return SnapshotValidation(
            SnapshotEvidenceStatus.CURRENT, _dedupe(diagnostics), delta
        )


class AppendOnlySnapshotJournal:
    """In-memory append-only import journal suitable for an injected store."""

    def __init__(self) -> None:
        self._records: list[ParsedSanctionsSnapshot] = []
        self._cids: set[str] = set()

    @property
    def records(self) -> tuple[ParsedSanctionsSnapshot, ...]:
        return tuple(self._records)

    def append(self, record: ParsedSanctionsSnapshot) -> None:
        if not isinstance(record, ParsedSanctionsSnapshot):
            raise TypeError("record must be a ParsedSanctionsSnapshot")
        if record.source.cid in self._cids:
            raise ValueError("snapshot source CID is already recorded")
        self._records.append(record)
        self._cids.add(record.source.cid)


def _dedupe(
    diagnostics: Sequence[SnapshotDiagnostic],
) -> tuple[SnapshotDiagnostic, ...]:
    seen: set[tuple[str, str, DiagnosticSeverity]] = set()
    result: list[SnapshotDiagnostic] = []
    for diagnostic in diagnostics:
        key = (diagnostic.code, diagnostic.message, diagnostic.severity)
        if key not in seen:
            seen.add(key)
            result.append(diagnostic)
    return tuple(result)


__all__ = [
    "AppendOnlySnapshotJournal",
    "DEFAULT_CLOCK_SKEW",
    "DEFAULT_MAXIMUM_SNAPSHOT_AGE",
    "DEFAULT_MINIMUM_COUNT_RATIO",
    "DiagnosticSeverity",
    "ParsedSanctionsSnapshot",
    "PublishedHashEvidence",
    "SanctionsSnapshotValidator",
    "SignatureEvidence",
    "SnapshotDelta",
    "SnapshotDiagnostic",
    "SnapshotEvidenceStatus",
    "SnapshotSource",
    "SnapshotValidation",
    "parse_instant",
    "raw_cid",
]
