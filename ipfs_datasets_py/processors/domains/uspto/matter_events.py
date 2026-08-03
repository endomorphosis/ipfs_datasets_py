"""Matter lifecycle events and non-lossy application status.

Models filing, status, transaction, document, response, appeal, abandonment,
allowance, and grant events with independent source-time and retrieval-time
axes. Application status is multi-dimensional and is never collapsed to a
single ``rejected`` boolean.

Normalized events map into the immutable :class:`MatterEvent` contract without
discarding upstream status fields. Ordering helpers sort by source event time
first, then retrieval time, then stable event id — never by retrieval alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    MatterEvent,
    MatterEventKind,
    canonical_json,
)

MATTER_EVENTS_SCHEMA_VERSION: Final = "uspto.matter-events.v1"
MATTER_EVENTS_INTERFACE: Final = "UsptoMatterEvents@1"

_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")

# Metadata keys reserved for temporal axes on MatterEvent.metadata
META_SOURCE_EVENT_UTC: Final = "source_event_utc"
META_RETRIEVAL_UTC: Final = "retrieval_utc"
META_STATUS_CODE: Final = "status_code"
META_STATUS_TEXT: Final = "status_text"
META_LIFECYCLE_PHASE: Final = "lifecycle_phase"
META_REJECTION_DISPOSITION: Final = "rejection_disposition"


class MatterEventError(ValueError):
    """Raised for invalid matter-event or status construction."""

    def __init__(self, message: str, *, code: str = "matter_event_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class ApplicationLifecyclePhase(str, Enum):
    """Coarse prosecution phase — complementary to detailed status text."""

    PRE_EXAMINATION = "pre_examination"
    EXAMINATION = "examination"
    APPEAL = "appeal"
    ALLOWANCE = "allowance"
    GRANT = "grant"
    ABANDONMENT = "abandonment"
    OTHER = "other"
    UNKNOWN = "unknown"


class RejectionDisposition(str, Enum):
    """Rejection-related disposition; deliberately not a single boolean.

    A matter may carry non-final, final, or advisory action history without
    being "rejected" as a terminal state. Terminal abandonment/allowance/
    grant live on other status axes.
    """

    NONE = "none"
    NONFINAL = "nonfinal"
    FINAL = "final"
    ADVISORY = "advisory"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class EventTemporalRole(str, Enum):
    """Which clock an instant belongs to."""

    SOURCE = "source"
    RETRIEVAL = "retrieval"


@dataclass(frozen=True, slots=True)
class ApplicationStatusSnapshot:
    """Multi-field application status; never a lone rejected flag.

    Upstream code/text and structured axes are all retained. Callers that
    need a boolean for UI filters must derive it explicitly from
    ``rejection_disposition`` and lifecycle phase rather than reading a
    collapsed ``rejected`` field (which this type intentionally omits).
    """

    schema_version: str
    status_code: str | None
    status_text: str | None
    lifecycle_phase: ApplicationLifecyclePhase
    rejection_disposition: RejectionDisposition
    is_pending: bool | None
    is_abandoned: bool | None
    is_allowed: bool | None
    is_patented: bool | None
    is_appealed: bool | None
    entity_status: str | None
    as_of_source_utc: str | None
    retrieval_utc: str | None
    raw_fields: Mapping[str, str]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != MATTER_EVENTS_SCHEMA_VERSION:
            raise ValueError(
                f"ApplicationStatusSnapshot.schema_version must be "
                f"{MATTER_EVENTS_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self,
            "status_code",
            _optional_str(self.status_code, "status_code", max_len=128),
        )
        object.__setattr__(
            self,
            "status_text",
            _optional_str(self.status_text, "status_text", max_len=512),
        )
        object.__setattr__(
            self,
            "lifecycle_phase",
            _coerce_enum(ApplicationLifecyclePhase, self.lifecycle_phase, "lifecycle_phase"),
        )
        object.__setattr__(
            self,
            "rejection_disposition",
            _coerce_enum(
                RejectionDisposition, self.rejection_disposition, "rejection_disposition"
            ),
        )
        for flag in (
            "is_pending",
            "is_abandoned",
            "is_allowed",
            "is_patented",
            "is_appealed",
        ):
            val = getattr(self, flag)
            if val is not None and not isinstance(val, bool):
                raise TypeError(f"{flag} must be bool or None")
        object.__setattr__(
            self,
            "entity_status",
            _optional_str(self.entity_status, "entity_status", max_len=64),
        )
        object.__setattr__(
            self,
            "as_of_source_utc",
            _optional_utc(self.as_of_source_utc, "as_of_source_utc"),
        )
        object.__setattr__(
            self,
            "retrieval_utc",
            _optional_utc(self.retrieval_utc, "retrieval_utc"),
        )
        object.__setattr__(
            self,
            "raw_fields",
            _frozen_str_map(self.raw_fields, "raw_fields", max_items=64),
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=32))
        # Hard guard: never accept a collapsed rejected flag via raw_fields alias
        # that would encourage lossy consumers — we keep raw upstream keys but
        # refuse a sole authoritative 'rejected' without disposition.
        if (
            "rejected" in self.raw_fields
            and self.rejection_disposition is RejectionDisposition.UNKNOWN
            and len(self.raw_fields) == 1
        ):
            raise MatterEventError(
                "application status must not be reduced to a single rejected flag; "
                "provide rejection_disposition and/or richer raw_fields",
                code="lossy_rejected_flag",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_source_utc": self.as_of_source_utc,
            "entity_status": self.entity_status,
            "is_abandoned": self.is_abandoned,
            "is_allowed": self.is_allowed,
            "is_appealed": self.is_appealed,
            "is_patented": self.is_patented,
            "is_pending": self.is_pending,
            "lifecycle_phase": self.lifecycle_phase.value,
            "notes": list(self.notes),
            "raw_fields": dict(self.raw_fields),
            "rejection_disposition": self.rejection_disposition.value,
            "retrieval_utc": self.retrieval_utc,
            "schema_version": self.schema_version,
            "status_code": self.status_code,
            "status_text": self.status_text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApplicationStatusSnapshot":
        value = _mapping(value, "ApplicationStatusSnapshot")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "status_code",
                    "status_text",
                    "lifecycle_phase",
                    "rejection_disposition",
                    "is_pending",
                    "is_abandoned",
                    "is_allowed",
                    "is_patented",
                    "is_appealed",
                    "entity_status",
                    "as_of_source_utc",
                    "retrieval_utc",
                    "raw_fields",
                    "notes",
                }
            ),
            "ApplicationStatusSnapshot",
        )
        return cls(
            schema_version=value.get("schema_version", MATTER_EVENTS_SCHEMA_VERSION),
            status_code=value.get("status_code"),
            status_text=value.get("status_text"),
            lifecycle_phase=value.get(
                "lifecycle_phase", ApplicationLifecyclePhase.UNKNOWN.value
            ),
            rejection_disposition=value.get(
                "rejection_disposition", RejectionDisposition.UNKNOWN.value
            ),
            is_pending=value.get("is_pending"),
            is_abandoned=value.get("is_abandoned"),
            is_allowed=value.get("is_allowed"),
            is_patented=value.get("is_patented"),
            is_appealed=value.get("is_appealed"),
            entity_status=value.get("entity_status"),
            as_of_source_utc=value.get("as_of_source_utc"),
            retrieval_utc=value.get("retrieval_utc"),
            raw_fields=value.get("raw_fields") or {},
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class NormalizedMatterEvent:
    """Matter event with explicit source and retrieval temporal axes.

    ``source_event_utc`` is when the USPTO (or other authority) records the
    event. ``retrieval_utc`` is when this system observed/fetched it. Both are
    preserved; neither overwrites the other. ``event_utc`` on the contract
    :class:`MatterEvent` is always the source time.
    """

    schema_version: str
    event_id: str
    matter_id: str
    kind: MatterEventKind
    source_event_utc: str
    retrieval_utc: str | None
    source_receipt_id: str | None
    description_digest: str | None
    related_artifact_ids: tuple[str, ...]
    classification: DisclosureClassification
    status_snapshot: ApplicationStatusSnapshot | None
    metadata: Mapping[str, str]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != MATTER_EVENTS_SCHEMA_VERSION:
            raise ValueError(
                f"NormalizedMatterEvent.schema_version must be {MATTER_EVENTS_SCHEMA_VERSION}"
            )
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(self, "matter_id", _identifier(self.matter_id, "matter_id"))
        object.__setattr__(
            self, "kind", _coerce_enum(MatterEventKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "source_event_utc", _require_utc(self.source_event_utc, "source_event_utc")
        )
        object.__setattr__(
            self, "retrieval_utc", _optional_utc(self.retrieval_utc, "retrieval_utc")
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_identifier(self.source_receipt_id, "source_receipt_id"),
        )
        object.__setattr__(
            self,
            "description_digest",
            _optional_sha256(self.description_digest, "description_digest"),
        )
        object.__setattr__(
            self,
            "related_artifact_ids",
            _tuple_of_str(self.related_artifact_ids, "related_artifact_ids", max_items=256),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if self.status_snapshot is not None and not isinstance(
            self.status_snapshot, ApplicationStatusSnapshot
        ):
            raise TypeError("status_snapshot must be ApplicationStatusSnapshot or None")
        object.__setattr__(
            self, "metadata", _frozen_str_map(self.metadata, "metadata", max_items=64)
        )
        object.__setattr__(self, "notes", _tuple_of_str(self.notes, "notes", max_items=32))

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "description_digest": self.description_digest,
            "event_id": self.event_id,
            "kind": self.kind.value,
            "matter_id": self.matter_id,
            "metadata": dict(self.metadata),
            "notes": list(self.notes),
            "related_artifact_ids": list(self.related_artifact_ids),
            "retrieval_utc": self.retrieval_utc,
            "schema_version": self.schema_version,
            "source_event_utc": self.source_event_utc,
            "source_receipt_id": self.source_receipt_id,
            "status_snapshot": (
                self.status_snapshot.to_dict() if self.status_snapshot else None
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormalizedMatterEvent":
        value = _mapping(value, "NormalizedMatterEvent")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema_version",
                    "event_id",
                    "matter_id",
                    "kind",
                    "source_event_utc",
                    "retrieval_utc",
                    "source_receipt_id",
                    "description_digest",
                    "related_artifact_ids",
                    "classification",
                    "status_snapshot",
                    "metadata",
                    "notes",
                }
            ),
            "NormalizedMatterEvent",
        )
        snap_raw = value.get("status_snapshot")
        snap = (
            ApplicationStatusSnapshot.from_dict(snap_raw)
            if snap_raw is not None
            else None
        )
        return cls(
            schema_version=value.get("schema_version", MATTER_EVENTS_SCHEMA_VERSION),
            event_id=value.get("event_id", ""),
            matter_id=value.get("matter_id", ""),
            kind=value.get("kind", MatterEventKind.OTHER.value),
            source_event_utc=value.get("source_event_utc", ""),
            retrieval_utc=value.get("retrieval_utc"),
            source_receipt_id=value.get("source_receipt_id"),
            description_digest=value.get("description_digest"),
            related_artifact_ids=tuple(value.get("related_artifact_ids") or ()),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            status_snapshot=snap,
            metadata=value.get("metadata") or {},
            notes=tuple(value.get("notes") or ()),
        )

    def to_matter_event(self) -> MatterEvent:
        """Project into the contracts :class:`MatterEvent`.

        Source time becomes ``event_utc``. Retrieval time and status axes are
        preserved in ``metadata`` so ordering and non-lossy status survive
        contract serialization.
        """
        meta: dict[str, str] = dict(self.metadata)
        meta[META_SOURCE_EVENT_UTC] = self.source_event_utc
        if self.retrieval_utc is not None:
            meta[META_RETRIEVAL_UTC] = self.retrieval_utc
        if self.status_snapshot is not None:
            snap = self.status_snapshot
            if snap.status_code:
                meta[META_STATUS_CODE] = snap.status_code
            if snap.status_text:
                meta[META_STATUS_TEXT] = snap.status_text
            meta[META_LIFECYCLE_PHASE] = snap.lifecycle_phase.value
            meta[META_REJECTION_DISPOSITION] = snap.rejection_disposition.value
            for key, flag in (
                ("is_pending", snap.is_pending),
                ("is_abandoned", snap.is_abandoned),
                ("is_allowed", snap.is_allowed),
                ("is_patented", snap.is_patented),
                ("is_appealed", snap.is_appealed),
            ):
                if flag is not None:
                    meta[key] = "true" if flag else "false"
            if snap.entity_status:
                meta["entity_status"] = snap.entity_status
            for rk, rv in snap.raw_fields.items():
                meta_key = f"raw.{rk}"
                if meta_key not in meta:
                    meta[meta_key] = rv
        for i, note in enumerate(self.notes):
            meta[f"note.{i}"] = note
        return MatterEvent(
            schema_version=CONTRACTS_SCHEMA_VERSION,
            event_id=self.event_id,
            matter_id=self.matter_id,
            kind=self.kind,
            event_utc=self.source_event_utc,
            source_receipt_id=self.source_receipt_id,
            description_digest=self.description_digest,
            related_artifact_ids=self.related_artifact_ids,
            classification=self.classification,
            metadata=meta,
        )

    @classmethod
    def from_matter_event(
        cls,
        event: MatterEvent | Mapping[str, Any],
        *,
        retrieval_utc: str | None = None,
        status_snapshot: ApplicationStatusSnapshot | None = None,
    ) -> "NormalizedMatterEvent":
        """Lift a contract event, restoring temporal axes from metadata when present."""
        if isinstance(event, Mapping):
            event = MatterEvent.from_dict(event)
        if not isinstance(event, MatterEvent):
            raise TypeError("event must be MatterEvent or mapping")
        meta = dict(event.metadata)
        source = meta.pop(META_SOURCE_EVENT_UTC, event.event_utc)
        retrieved = meta.pop(META_RETRIEVAL_UTC, retrieval_utc)
        notes: list[str] = []
        note_keys = sorted(k for k in meta if k.startswith("note."))
        for k in note_keys:
            notes.append(meta.pop(k))
        # Strip projected status keys from free metadata (status lives on snapshot).
        for key in (
            META_STATUS_CODE,
            META_STATUS_TEXT,
            META_LIFECYCLE_PHASE,
            META_REJECTION_DISPOSITION,
            "is_pending",
            "is_abandoned",
            "is_allowed",
            "is_patented",
            "is_appealed",
            "entity_status",
        ):
            meta.pop(key, None)
        raw_fields = {
            k[4:]: meta.pop(k) for k in list(meta.keys()) if k.startswith("raw.")
        }
        snap = status_snapshot
        if snap is None and (
            META_LIFECYCLE_PHASE in event.metadata
            or META_REJECTION_DISPOSITION in event.metadata
            or META_STATUS_CODE in event.metadata
        ):
            snap = ApplicationStatusSnapshot(
                schema_version=MATTER_EVENTS_SCHEMA_VERSION,
                status_code=event.metadata.get(META_STATUS_CODE),
                status_text=event.metadata.get(META_STATUS_TEXT),
                lifecycle_phase=event.metadata.get(
                    META_LIFECYCLE_PHASE, ApplicationLifecyclePhase.UNKNOWN.value
                ),
                rejection_disposition=event.metadata.get(
                    META_REJECTION_DISPOSITION, RejectionDisposition.UNKNOWN.value
                ),
                is_pending=_meta_bool(event.metadata.get("is_pending")),
                is_abandoned=_meta_bool(event.metadata.get("is_abandoned")),
                is_allowed=_meta_bool(event.metadata.get("is_allowed")),
                is_patented=_meta_bool(event.metadata.get("is_patented")),
                is_appealed=_meta_bool(event.metadata.get("is_appealed")),
                entity_status=event.metadata.get("entity_status"),
                as_of_source_utc=source,
                retrieval_utc=retrieved,
                raw_fields=raw_fields,
                notes=(),
            )
        return cls(
            schema_version=MATTER_EVENTS_SCHEMA_VERSION,
            event_id=event.event_id,
            matter_id=event.matter_id,
            kind=event.kind,
            source_event_utc=source,
            retrieval_utc=retrieved,
            source_receipt_id=event.source_receipt_id,
            description_digest=event.description_digest,
            related_artifact_ids=event.related_artifact_ids,
            classification=event.classification,
            status_snapshot=snap,
            metadata=meta,
            notes=tuple(notes),
        )


def build_matter_event(
    *,
    event_id: str,
    matter_id: str,
    kind: MatterEventKind | str,
    source_event_utc: str,
    retrieval_utc: str | None = None,
    source_receipt_id: str | None = None,
    description_digest: str | None = None,
    related_artifact_ids: Sequence[str] = (),
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN,
    status_snapshot: ApplicationStatusSnapshot | Mapping[str, Any] | None = None,
    metadata: Mapping[str, str] | None = None,
    notes: Sequence[str] = (),
) -> NormalizedMatterEvent:
    """Construct a normalized matter event with both temporal axes."""
    snap: ApplicationStatusSnapshot | None
    if status_snapshot is None:
        snap = None
    elif isinstance(status_snapshot, ApplicationStatusSnapshot):
        snap = status_snapshot
    else:
        snap = ApplicationStatusSnapshot.from_dict(status_snapshot)
    return NormalizedMatterEvent(
        schema_version=MATTER_EVENTS_SCHEMA_VERSION,
        event_id=event_id,
        matter_id=matter_id,
        kind=kind,
        source_event_utc=source_event_utc,
        retrieval_utc=retrieval_utc,
        source_receipt_id=source_receipt_id,
        description_digest=description_digest,
        related_artifact_ids=tuple(related_artifact_ids),
        classification=classification,
        status_snapshot=snap,
        metadata=metadata or {},
        notes=tuple(notes),
    )


def normalize_application_status(
    *,
    status_code: str | None = None,
    status_text: str | None = None,
    lifecycle_phase: ApplicationLifecyclePhase | str | None = None,
    rejection_disposition: RejectionDisposition | str | None = None,
    is_pending: bool | None = None,
    is_abandoned: bool | None = None,
    is_allowed: bool | None = None,
    is_patented: bool | None = None,
    is_appealed: bool | None = None,
    entity_status: str | None = None,
    as_of_source_utc: str | None = None,
    retrieval_utc: str | None = None,
    raw_fields: Mapping[str, str] | None = None,
    notes: Sequence[str] = (),
    infer: bool = True,
) -> ApplicationStatusSnapshot:
    """Build a status snapshot without collapsing to a single rejected flag.

    When ``infer`` is true, lifecycle phase and boolean axes are derived from
    status text/code heuristics only when still unset — inference never invents
    a boolean ``rejected``.
    """
    raw = dict(raw_fields or {})
    if status_code and "status_code" not in raw:
        raw.setdefault("status_code", status_code)
    if status_text and "status_text" not in raw:
        raw.setdefault("status_text", status_text)

    phase = (
        _coerce_enum(ApplicationLifecyclePhase, lifecycle_phase, "lifecycle_phase")
        if lifecycle_phase is not None
        else ApplicationLifecyclePhase.UNKNOWN
    )
    rejection = (
        _coerce_enum(RejectionDisposition, rejection_disposition, "rejection_disposition")
        if rejection_disposition is not None
        else RejectionDisposition.UNKNOWN
    )

    if infer:
        blob = " ".join(
            x for x in (status_code or "", status_text or "", *raw.values()) if x
        ).lower()
        if phase is ApplicationLifecyclePhase.UNKNOWN:
            phase = _infer_phase(blob)
        if rejection is RejectionDisposition.UNKNOWN:
            rejection = _infer_rejection(blob)
        if is_abandoned is None and ("abandon" in blob):
            is_abandoned = True
        if is_allowed is None and (
            "notice of allowance" in blob or "allowance" in blob
        ):
            is_allowed = True
        if is_patented is None and (
            "patented case" in blob or ("grant" in blob and "patent" in blob)
        ):
            is_patented = True
        if is_appealed is None and "appeal" in blob:
            is_appealed = True
        if is_pending is None:
            if is_abandoned or is_patented:
                is_pending = False
            elif phase in (
                ApplicationLifecyclePhase.PRE_EXAMINATION,
                ApplicationLifecyclePhase.EXAMINATION,
                ApplicationLifecyclePhase.APPEAL,
                ApplicationLifecyclePhase.ALLOWANCE,
            ):
                is_pending = True

    return ApplicationStatusSnapshot(
        schema_version=MATTER_EVENTS_SCHEMA_VERSION,
        status_code=status_code,
        status_text=status_text,
        lifecycle_phase=phase,
        rejection_disposition=rejection,
        is_pending=is_pending,
        is_abandoned=is_abandoned,
        is_allowed=is_allowed,
        is_patented=is_patented,
        is_appealed=is_appealed,
        entity_status=entity_status,
        as_of_source_utc=as_of_source_utc,
        retrieval_utc=retrieval_utc,
        raw_fields=raw,
        notes=tuple(notes),
    )


def order_matter_events(
    events: Iterable[NormalizedMatterEvent | MatterEvent | Mapping[str, Any]],
    *,
    primary: EventTemporalRole | str = EventTemporalRole.SOURCE,
    secondary: EventTemporalRole | str = EventTemporalRole.RETRIEVAL,
    reverse: bool = False,
) -> list[NormalizedMatterEvent]:
    """Order events by source time and retrieval time (both preserved).

    Default: ascending ``source_event_utc``, then ``retrieval_utc`` (missing
    retrieval sorts last among equal source times), then ``event_id``.
    Primary/secondary may be swapped but both axes remain on each event.
    """
    primary_role = _coerce_enum(EventTemporalRole, primary, "primary")
    secondary_role = _coerce_enum(EventTemporalRole, secondary, "secondary")
    if primary_role is secondary_role:
        raise MatterEventError(
            "primary and secondary temporal roles must differ",
            code="temporal_role_collision",
        )

    normalized: list[NormalizedMatterEvent] = []
    for item in events:
        if isinstance(item, NormalizedMatterEvent):
            normalized.append(item)
        elif isinstance(item, MatterEvent):
            normalized.append(NormalizedMatterEvent.from_matter_event(item))
        elif isinstance(item, Mapping):
            if "source_event_utc" in item or item.get("schema_version", "").startswith(
                "uspto.matter-events"
            ):
                normalized.append(NormalizedMatterEvent.from_dict(item))
            else:
                normalized.append(
                    NormalizedMatterEvent.from_matter_event(MatterEvent.from_dict(item))
                )
        else:
            raise TypeError(
                "events must be NormalizedMatterEvent, MatterEvent, or mapping"
            )

    def _axis(event: NormalizedMatterEvent, role: EventTemporalRole) -> str:
        if role is EventTemporalRole.SOURCE:
            return event.source_event_utc
        # Missing retrieval sorts after any concrete retrieval timestamp.
        return event.retrieval_utc if event.retrieval_utc is not None else "\uffff"

    def sort_key(event: NormalizedMatterEvent) -> tuple[str, str, str]:
        return (
            _axis(event, primary_role),
            _axis(event, secondary_role),
            event.event_id,
        )

    return sorted(normalized, key=sort_key, reverse=reverse)


def event_temporal_pair(
    event: NormalizedMatterEvent | MatterEvent | Mapping[str, Any],
) -> tuple[str, str | None]:
    """Return ``(source_event_utc, retrieval_utc)`` without conflating them."""
    if isinstance(event, NormalizedMatterEvent):
        return event.source_event_utc, event.retrieval_utc
    if isinstance(event, MatterEvent):
        source = event.metadata.get(META_SOURCE_EVENT_UTC, event.event_utc)
        retrieval = event.metadata.get(META_RETRIEVAL_UTC)
        return source, retrieval
    if isinstance(event, Mapping):
        if "source_event_utc" in event:
            return str(event["source_event_utc"]), event.get("retrieval_utc")
        lifted = NormalizedMatterEvent.from_matter_event(event)
        return lifted.source_event_utc, lifted.retrieval_utc
    raise TypeError("unsupported event type")


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------


def _infer_phase(blob: str) -> ApplicationLifecyclePhase:
    if "abandon" in blob:
        return ApplicationLifecyclePhase.ABANDONMENT
    if "grant" in blob or "patented" in blob:
        return ApplicationLifecyclePhase.GRANT
    if "allow" in blob:
        return ApplicationLifecyclePhase.ALLOWANCE
    if "appeal" in blob or "bpa" in blob or "ptab" in blob:
        return ApplicationLifecyclePhase.APPEAL
    if "docketed" in blob or "preexam" in blob or "pre-exam" in blob:
        return ApplicationLifecyclePhase.PRE_EXAMINATION
    if "examin" in blob or "nonfinal" in blob or "final reject" in blob or "office action" in blob:
        return ApplicationLifecyclePhase.EXAMINATION
    return ApplicationLifecyclePhase.UNKNOWN


def _infer_rejection(blob: str) -> RejectionDisposition:
    if "advisory" in blob:
        return RejectionDisposition.ADVISORY
    # Non-final must win over a bare "final" substring inside "non-final".
    if (
        "nonfinal" in blob
        or "non-final" in blob
        or "non final" in blob
        or "ctnf" in blob
    ):
        return RejectionDisposition.NONFINAL
    if (
        "final rejection" in blob
        or "final reject" in blob
        or "ctfr" in blob
        or re.search(r"\bfinal\b", blob)
        and "reject" in blob
    ):
        return RejectionDisposition.FINAL
    if "reject" in blob:
        return RejectionDisposition.UNKNOWN
    if "allow" in blob or "grant" in blob or "abandon" in blob:
        return RejectionDisposition.NOT_APPLICABLE
    return RejectionDisposition.NONE


def _meta_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


# ---------------------------------------------------------------------------
# Validation helpers (local copies; modules stay free of private contract imports)
# ---------------------------------------------------------------------------


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _require_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp")
    return text


def _optional_utc(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_sha256(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    text = text.lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown disclosure classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _frozen_str_map(value: Any, field: str, *, max_items: int = 64) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(str(key), f"{field}.key", max_len=128)
        if not isinstance(raw, str):
            raise TypeError(f"{field}[{k}] must be str")
        if len(raw) > 2048:
            raise ValueError(f"{field}[{k}] exceeds max length 2048")
        out[k] = raw
    return MappingProxyType(dict(sorted(out.items())))


def _tuple_of_str(value: Any, field: str, *, max_items: int = 256) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=256) for i, item in enumerate(value))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = set(value.keys()) - allowed
    if unknown:
        raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")


__all__ = [
    "MATTER_EVENTS_INTERFACE",
    "MATTER_EVENTS_SCHEMA_VERSION",
    "META_LIFECYCLE_PHASE",
    "META_REJECTION_DISPOSITION",
    "META_RETRIEVAL_UTC",
    "META_SOURCE_EVENT_UTC",
    "META_STATUS_CODE",
    "META_STATUS_TEXT",
    "ApplicationLifecyclePhase",
    "ApplicationStatusSnapshot",
    "EventTemporalRole",
    "MatterEventError",
    "MatterEventKind",
    "NormalizedMatterEvent",
    "RejectionDisposition",
    "build_matter_event",
    "canonical_json",
    "event_temporal_pair",
    "normalize_application_status",
    "order_matter_events",
]
