"""Human IDS-candidate review queue (PATLAW-151).

Routes possible information-disclosure references to a natural-person queue.
No reference enters an IDS-ready state without explicit relevance **and**
materiality review by a natural person. The queue never auto-files an IDS and
never claims an exhaustive search or patentability.

Design invariants
-----------------
* Candidates start as non-IDS-ready; automation cannot promote to IDS-ready.
* IDS-ready requires natural-person relevance review **and** materiality review.
* Reviewer actions are append-only versioned records.
* Outputs never auto-file, never assert materiality as a machine conclusion,
  and never claim an exhaustive prior-art search.
* Coverage-gap acknowledgement may be required before packaging for handoff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .claim_chart_v2 import (
    CLAIM_CHART_V2_DISCLAIMER,
    ClaimChartCellV2,
    ClaimChartV2,
    CoverageGapAcknowledgement,
    ExhaustiveSearchClaimError,
    ReviewerDisposition,
    assert_no_exhaustive_search_claim,
    content_digest as chart_content_digest,
)
from .prior_art import PriorArtError
from .retrieval_contracts import SourceLink

# ---------------------------------------------------------------------------
# Schema / identity pins
# ---------------------------------------------------------------------------

IDS_REVIEW_QUEUE_SCHEMA_VERSION: Final = "patent.ids_review_queue.v1"
IDS_REVIEW_QUEUE_INTERFACE: Final = "IdsReviewQueue@1"
IDS_REVIEW_QUEUE_CODE_VERSION: Final = "1.0.0"

OUTPUT_KIND_IDS_QUEUE: Final = "ids_review_queue_v1"
OUTPUT_KIND_IDS_CANDIDATE: Final = "ids_reference_candidate_v1"
OUTPUT_KIND_IDS_REVIEW_ACTION: Final = "ids_review_action_v1"

IDS_REVIEW_QUEUE_DISCLAIMER: Final = (
    "This artifact is a human IDS-candidate review queue. Possible references "
    "require natural-person relevance and materiality review before any "
    "IDS-ready state. This system never auto-files an IDS, never makes a legal "
    "materiality or patentability determination, never claims an exhaustive "
    "search, and is not a substitute for counsel judgment under 37 C.F.R. "
    "§ 1.56 or related duties."
)

_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)

DEFAULT_MAX_CANDIDATES: Final = 512
DEFAULT_MAX_REVIEW_ACTIONS: Final = 256

_FORBIDDEN_CONCLUSION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "anticipates",
        "auto_filed",
        "auto_filed_ids",
        "exhaustive_search",
        "is_exhaustive",
        "is_novel",
        "is_obvious",
        "novelty",
        "novelty_conclusion",
        "obviousness",
        "obviousness_conclusion",
        "patentability",
        "patentability_conclusion",
        "patentable",
        "renders_obvious",
        "unpatentable",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IdsReviewQueueError(PriorArtError):
    """Base error for IDS review queue failures."""

    code: str = "ids_review_queue_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class IdsReadyGateError(IdsReviewQueueError):
    """Raised when a reference would enter IDS-ready without required reviews."""

    code = "ids_ready_gate"


class IdsAutoFileError(IdsReviewQueueError):
    """Raised when an operation would auto-file an IDS."""

    code = "ids_auto_file_blocked"


class IdsReviewVersionError(IdsReviewQueueError):
    """Raised on invalid versioned review actions."""

    code = "ids_review_version_invalid"


class IdsNaturalPersonError(IdsReviewQueueError):
    """Raised when a non-natural-person attempts a gated review action."""

    code = "ids_natural_person_required"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class IdsCandidateState(str, Enum):
    """Lifecycle state of one IDS reference candidate."""

    CANDIDATE = "candidate"
    UNDER_REVIEW = "under_review"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    # Intermediate after partial human review:
    RELEVANCE_REVIEWED = "relevance_reviewed"
    MATERIALITY_REVIEWED = "materiality_reviewed"
    # Terminal gated state — only after both reviews by a natural person:
    IDS_READY = "ids_ready"


class RelevanceDisposition(str, Enum):
    """Natural-person relevance disposition (not a machine conclusion)."""

    UNREVIEWED = "unreviewed"
    RELEVANT = "relevant"
    NOT_RELEVANT = "not_relevant"
    UNCERTAIN = "uncertain"


class MaterialityDisposition(str, Enum):
    """Natural-person materiality disposition (not a machine conclusion)."""

    UNREVIEWED = "unreviewed"
    MATERIAL = "material"
    NOT_MATERIAL = "not_material"
    UNCERTAIN = "uncertain"


class IdsReviewActionKind(str, Enum):
    """Kind of versioned human review action."""

    ENQUEUE = "enqueue"
    START_REVIEW = "start_review"
    SET_RELEVANCE = "set_relevance"
    SET_MATERIALITY = "set_materiality"
    PROMOTE_IDS_READY = "promote_ids_ready"
    REJECT = "reject"
    DEFER = "defer"
    NOTE = "note"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    import json

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp, got {text!r}")
    return text


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 1:
        raise ValueError(f"{field} must be >= 1")
    return value


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    return value


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _frozen_str_map(value: Any, field: str, *, max_items: int = 64) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for key, raw in value.items():
        k = _require_str(key, f"{field}.key", max_len=128)
        v = _require_str(raw, f"{field}[{k}]", max_len=2048)
        out[k] = v
    return MappingProxyType(dict(sorted(out.items())))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(value).__name__}")
    return value


def _tuple_of_source_links(
    value: Any, field: str, *, max_items: int = 32
) -> tuple[SourceLink, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[SourceLink] = []
    for i, item in enumerate(value):
        if isinstance(item, SourceLink):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(SourceLink.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be SourceLink or mapping")
    return tuple(out)


def _assert_no_forbidden_keys(metadata: Mapping[str, str], label: str) -> None:
    hits = sorted(set(k.lower() for k in metadata) & _FORBIDDEN_CONCLUSION_KEYS)
    if hits:
        raise IdsReviewQueueError(
            f"{label} metadata must not assert conclusion keys: {', '.join(hits)}"
        )


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdsReviewAction:
    """One versioned natural-person review action on an IDS candidate."""

    action_id: str
    candidate_id: str
    version: int
    action_kind: IdsReviewActionKind
    reviewer_id: str
    acted_at_utc: str
    is_natural_person: bool = True
    relevance: RelevanceDisposition | None = None
    materiality: MaterialityDisposition | None = None
    notes: str | None = None
    previous_version_digest: str | None = None
    content_digest: str | None = None
    output_kind: str = OUTPUT_KIND_IDS_REVIEW_ACTION
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "version", _positive_int(self.version, "version"))
        object.__setattr__(
            self,
            "action_kind",
            _coerce_enum(IdsReviewActionKind, self.action_kind, "action_kind"),
        )
        object.__setattr__(
            self, "reviewer_id", _identifier(self.reviewer_id, "reviewer_id")
        )
        object.__setattr__(
            self, "acted_at_utc", _iso_utc(self.acted_at_utc, "acted_at_utc")
        )
        if not isinstance(self.is_natural_person, bool):
            raise TypeError("is_natural_person must be bool")
        if not self.is_natural_person:
            raise IdsNaturalPersonError(
                f"IDS review action {self.action_id} requires a natural person"
            )
        if self.relevance is not None:
            object.__setattr__(
                self,
                "relevance",
                _coerce_enum(RelevanceDisposition, self.relevance, "relevance"),
            )
        if self.materiality is not None:
            object.__setattr__(
                self,
                "materiality",
                _coerce_enum(MaterialityDisposition, self.materiality, "materiality"),
            )
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=4096)
        )
        object.__setattr__(
            self,
            "previous_version_digest",
            _optional_str(
                self.previous_version_digest, "previous_version_digest", max_len=64
            ),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_IDS_REVIEW_ACTION:
            raise ValueError(
                f"output_kind must be {OUTPUT_KIND_IDS_REVIEW_ACTION!r}"
            )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "IdsReviewAction")

        identity = {
            "action_id": self.action_id,
            "action_kind": self.action_kind.value,
            "acted_at_utc": self.acted_at_utc,
            "candidate_id": self.candidate_id,
            "is_natural_person": True,
            "materiality": (
                None if self.materiality is None else self.materiality.value
            ),
            "metadata": dict(self.metadata),
            "notes": self.notes,
            "previous_version_digest": self.previous_version_digest,
            "relevance": None if self.relevance is None else self.relevance.value,
            "reviewer_id": self.reviewer_id,
            "version": self.version,
        }
        digest = content_digest(identity)
        provided = _optional_str(self.content_digest, "content_digest", max_len=64)
        if provided is not None and provided.lower() != digest:
            raise IdsReviewVersionError(
                f"content_digest mismatch for action {self.action_id}"
            )
        object.__setattr__(self, "content_digest", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_kind": self.action_kind.value,
            "acted_at_utc": self.acted_at_utc,
            "candidate_id": self.candidate_id,
            "content_digest": self.content_digest,
            "is_natural_person": True,
            "materiality": (
                None if self.materiality is None else self.materiality.value
            ),
            "metadata": dict(self.metadata),
            "notes": self.notes,
            "output_kind": self.output_kind,
            "previous_version_digest": self.previous_version_digest,
            "relevance": None if self.relevance is None else self.relevance.value,
            "reviewer_id": self.reviewer_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IdsReviewAction":
        value = _mapping(value, "IdsReviewAction")
        return cls(
            action_id=value.get("action_id", ""),
            candidate_id=value.get("candidate_id", ""),
            version=int(value.get("version") or 0),
            action_kind=value.get("action_kind", IdsReviewActionKind.NOTE.value),
            reviewer_id=value.get("reviewer_id", ""),
            acted_at_utc=value.get("acted_at_utc", ""),
            is_natural_person=bool(value.get("is_natural_person", True)),
            relevance=value.get("relevance"),
            materiality=value.get("materiality"),
            notes=value.get("notes"),
            previous_version_digest=value.get("previous_version_digest"),
            content_digest=value.get("content_digest"),
            output_kind=value.get("output_kind", OUTPUT_KIND_IDS_REVIEW_ACTION),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class IdsReferenceCandidate:
    """One possible IDS reference awaiting natural-person review.

    Never enters :attr:`IdsCandidateState.IDS_READY` without both relevance and
    materiality reviews by a natural person.
    """

    candidate_id: str
    document_id: str
    subject_id: str
    state: IdsCandidateState = IdsCandidateState.CANDIDATE
    chart_cell_ids: tuple[str, ...] = ()
    source_links: tuple[SourceLink, ...] = ()
    citation_text: str | None = None
    identifiers: Mapping[str, str] = MappingProxyType({})
    relevance: RelevanceDisposition = RelevanceDisposition.UNREVIEWED
    materiality: MaterialityDisposition = MaterialityDisposition.UNREVIEWED
    relevance_reviewer_id: str | None = None
    materiality_reviewer_id: str | None = None
    relevance_reviewed_at_utc: str | None = None
    materiality_reviewed_at_utc: str | None = None
    review_history: tuple[IdsReviewAction, ...] = ()
    auto_file_blocked: bool = True
    is_ids_ready: bool = False
    output_kind: str = OUTPUT_KIND_IDS_CANDIDATE
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "document_id", _identifier(self.document_id, "document_id")
        )
        object.__setattr__(
            self, "subject_id", _identifier(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self, "state", _coerce_enum(IdsCandidateState, self.state, "state")
        )
        if not isinstance(self.chart_cell_ids, Sequence) or isinstance(
            self.chart_cell_ids, (str, bytes)
        ):
            raise TypeError("chart_cell_ids must be a sequence")
        object.__setattr__(
            self,
            "chart_cell_ids",
            tuple(
                _identifier(c, f"chart_cell_ids[{i}]")
                for i, c in enumerate(self.chart_cell_ids)
            ),
        )
        object.__setattr__(
            self,
            "source_links",
            _tuple_of_source_links(self.source_links, "source_links"),
        )
        object.__setattr__(
            self,
            "citation_text",
            _optional_str(self.citation_text, "citation_text", max_len=2048),
        )
        object.__setattr__(
            self, "identifiers", _frozen_str_map(self.identifiers, "identifiers")
        )
        object.__setattr__(
            self,
            "relevance",
            _coerce_enum(RelevanceDisposition, self.relevance, "relevance"),
        )
        object.__setattr__(
            self,
            "materiality",
            _coerce_enum(MaterialityDisposition, self.materiality, "materiality"),
        )
        object.__setattr__(
            self,
            "relevance_reviewer_id",
            _optional_str(
                self.relevance_reviewer_id, "relevance_reviewer_id", max_len=256
            ),
        )
        object.__setattr__(
            self,
            "materiality_reviewer_id",
            _optional_str(
                self.materiality_reviewer_id, "materiality_reviewer_id", max_len=256
            ),
        )
        object.__setattr__(
            self,
            "relevance_reviewed_at_utc",
            (
                None
                if self.relevance_reviewed_at_utc is None
                else _iso_utc(
                    self.relevance_reviewed_at_utc, "relevance_reviewed_at_utc"
                )
            ),
        )
        object.__setattr__(
            self,
            "materiality_reviewed_at_utc",
            (
                None
                if self.materiality_reviewed_at_utc is None
                else _iso_utc(
                    self.materiality_reviewed_at_utc, "materiality_reviewed_at_utc"
                )
            ),
        )
        history = _coerce_actions(self.review_history, "review_history")
        if len(history) > DEFAULT_MAX_REVIEW_ACTIONS:
            raise IdsReviewVersionError(
                f"review_history exceeds max {DEFAULT_MAX_REVIEW_ACTIONS}"
            )
        _assert_action_history_versioned(history, candidate_id=self.candidate_id)
        object.__setattr__(self, "review_history", history)

        if self.auto_file_blocked is not True:
            raise IdsAutoFileError(
                "auto_file_blocked must be True; the queue never auto-files an IDS"
            )
        object.__setattr__(self, "auto_file_blocked", True)

        # Fail closed: IDS_READY / is_ids_ready only after both human reviews.
        ready_by_state = self.state is IdsCandidateState.IDS_READY
        if self.is_ids_ready or ready_by_state:
            _assert_ids_ready_gate(self)
            object.__setattr__(self, "is_ids_ready", True)
            object.__setattr__(self, "state", IdsCandidateState.IDS_READY)
        else:
            object.__setattr__(self, "is_ids_ready", False)

        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_IDS_CANDIDATE:
            raise ValueError(f"output_kind must be {OUTPUT_KIND_IDS_CANDIDATE!r}")
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "IdsReferenceCandidate")

    def current_review_version(self) -> int:
        if not self.review_history:
            return 0
        return max(a.version for a in self.review_history)

    def has_natural_person_relevance_review(self) -> bool:
        return (
            self.relevance is not RelevanceDisposition.UNREVIEWED
            and self.relevance_reviewer_id is not None
            and self.relevance_reviewed_at_utc is not None
        )

    def has_natural_person_materiality_review(self) -> bool:
        return (
            self.materiality is not MaterialityDisposition.UNREVIEWED
            and self.materiality_reviewer_id is not None
            and self.materiality_reviewed_at_utc is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_file_blocked": True,
            "candidate_id": self.candidate_id,
            "chart_cell_ids": list(self.chart_cell_ids),
            "citation_text": self.citation_text,
            "document_id": self.document_id,
            "identifiers": dict(self.identifiers),
            "is_ids_ready": self.is_ids_ready,
            "materiality": self.materiality.value,
            "materiality_reviewed_at_utc": self.materiality_reviewed_at_utc,
            "materiality_reviewer_id": self.materiality_reviewer_id,
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "relevance": self.relevance.value,
            "relevance_reviewed_at_utc": self.relevance_reviewed_at_utc,
            "relevance_reviewer_id": self.relevance_reviewer_id,
            "review_history": [a.to_dict() for a in self.review_history],
            "source_links": [link.to_dict() for link in self.source_links],
            "state": self.state.value,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IdsReferenceCandidate":
        value = _mapping(value, "IdsReferenceCandidate")
        return cls(
            candidate_id=value.get("candidate_id", ""),
            document_id=value.get("document_id", ""),
            subject_id=value.get("subject_id", ""),
            state=value.get("state", IdsCandidateState.CANDIDATE.value),
            chart_cell_ids=tuple(value.get("chart_cell_ids") or ()),
            source_links=tuple(value.get("source_links") or ()),
            citation_text=value.get("citation_text"),
            identifiers=value.get("identifiers") or {},
            relevance=value.get("relevance", RelevanceDisposition.UNREVIEWED.value),
            materiality=value.get(
                "materiality", MaterialityDisposition.UNREVIEWED.value
            ),
            relevance_reviewer_id=value.get("relevance_reviewer_id"),
            materiality_reviewer_id=value.get("materiality_reviewer_id"),
            relevance_reviewed_at_utc=value.get("relevance_reviewed_at_utc"),
            materiality_reviewed_at_utc=value.get("materiality_reviewed_at_utc"),
            review_history=tuple(value.get("review_history") or ()),
            auto_file_blocked=bool(value.get("auto_file_blocked", True)),
            is_ids_ready=bool(value.get("is_ids_ready", False)),
            output_kind=value.get("output_kind", OUTPUT_KIND_IDS_CANDIDATE),
            metadata=value.get("metadata") or {},
        )


def _coerce_actions(value: Any, field: str) -> tuple[IdsReviewAction, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[IdsReviewAction] = []
    for i, item in enumerate(value):
        if isinstance(item, IdsReviewAction):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(IdsReviewAction.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be IdsReviewAction or mapping")
    return tuple(sorted(out, key=lambda a: a.version))


def _assert_action_history_versioned(
    history: Sequence[IdsReviewAction], *, candidate_id: str
) -> None:
    if not history:
        return
    versions = [a.version for a in history]
    if len(set(versions)) != len(versions):
        raise IdsReviewVersionError(
            f"candidate {candidate_id} has duplicate review versions"
        )
    prev_digest: str | None = None
    for action in sorted(history, key=lambda a: a.version):
        if action.candidate_id != candidate_id:
            raise IdsReviewVersionError(
                f"action {action.action_id} candidate_id mismatch"
            )
        if action.version == 1:
            if action.previous_version_digest is not None:
                raise IdsReviewVersionError(
                    f"version 1 of {candidate_id} must not set previous_version_digest"
                )
        else:
            if action.previous_version_digest is None:
                raise IdsReviewVersionError(
                    f"version {action.version} of {candidate_id} requires "
                    "previous_version_digest"
                )
            if (
                prev_digest is not None
                and action.previous_version_digest != prev_digest
            ):
                raise IdsReviewVersionError(
                    f"version {action.version} of {candidate_id} "
                    "previous_version_digest mismatch"
                )
        prev_digest = action.content_digest


def _assert_ids_ready_gate(candidate: IdsReferenceCandidate) -> None:
    """No reference enters IDS-ready without natural-person relevance+materiality."""
    if candidate.relevance is not RelevanceDisposition.RELEVANT:
        raise IdsReadyGateError(
            f"candidate {candidate.candidate_id} cannot be IDS-ready without "
            f"relevance=relevant (got {candidate.relevance.value})"
        )
    if candidate.materiality is not MaterialityDisposition.MATERIAL:
        raise IdsReadyGateError(
            f"candidate {candidate.candidate_id} cannot be IDS-ready without "
            f"materiality=material (got {candidate.materiality.value})"
        )
    if not candidate.relevance_reviewer_id or not candidate.relevance_reviewed_at_utc:
        raise IdsReadyGateError(
            f"candidate {candidate.candidate_id} missing natural-person relevance review"
        )
    if (
        not candidate.materiality_reviewer_id
        or not candidate.materiality_reviewed_at_utc
    ):
        raise IdsReadyGateError(
            f"candidate {candidate.candidate_id} missing natural-person materiality review"
        )
    # Ensure at least one natural-person action for each review kind is in history.
    has_rel = any(
        a.action_kind is IdsReviewActionKind.SET_RELEVANCE
        and a.is_natural_person
        and a.relevance is RelevanceDisposition.RELEVANT
        for a in candidate.review_history
    )
    has_mat = any(
        a.action_kind is IdsReviewActionKind.SET_MATERIALITY
        and a.is_natural_person
        and a.materiality is MaterialityDisposition.MATERIAL
        for a in candidate.review_history
    )
    if not has_rel or not has_mat:
        raise IdsReadyGateError(
            f"candidate {candidate.candidate_id} IDS-ready requires versioned "
            "natural-person relevance and materiality actions in review_history"
        )


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdsReviewQueue:
    """Human IDS-candidate queue bound to a subject / claim chart.

    Never auto-files. Never claims exhaustive search. IDS-ready is gated.
    """

    schema_version: str
    queue_id: str
    subject_id: str
    candidates: tuple[IdsReferenceCandidate, ...]
    chart_id: str | None = None
    coverage_acknowledgement: CoverageGapAcknowledgement | None = None
    auto_file_blocked: bool = True
    claims_exhaustive_search: bool = False
    output_kind: str = OUTPUT_KIND_IDS_QUEUE
    disclaimer: str = IDS_REVIEW_QUEUE_DISCLAIMER
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        schema = _require_str(self.schema_version, "schema_version", max_len=64)
        if schema != IDS_REVIEW_QUEUE_SCHEMA_VERSION:
            raise IdsReviewQueueError(
                f"schema_version must be {IDS_REVIEW_QUEUE_SCHEMA_VERSION}, "
                f"got {schema!r}"
            )
        object.__setattr__(self, "schema_version", schema)
        object.__setattr__(self, "queue_id", _identifier(self.queue_id, "queue_id"))
        object.__setattr__(
            self, "subject_id", _identifier(self.subject_id, "subject_id")
        )
        candidates = _coerce_candidates(self.candidates, "candidates")
        if len(candidates) > DEFAULT_MAX_CANDIDATES:
            raise IdsReviewQueueError(
                f"candidates exceeds max {DEFAULT_MAX_CANDIDATES}"
            )
        object.__setattr__(self, "candidates", candidates)
        for cand in candidates:
            if cand.subject_id != self.subject_id:
                raise IdsReviewQueueError(
                    f"candidate {cand.candidate_id} subject_id mismatch"
                )
            if cand.is_ids_ready or cand.state is IdsCandidateState.IDS_READY:
                _assert_ids_ready_gate(cand)

        object.__setattr__(
            self, "chart_id", _optional_str(self.chart_id, "chart_id", max_len=256)
        )
        if self.coverage_acknowledgement is not None:
            if isinstance(self.coverage_acknowledgement, Mapping):
                object.__setattr__(
                    self,
                    "coverage_acknowledgement",
                    CoverageGapAcknowledgement.from_dict(
                        self.coverage_acknowledgement
                    ),
                )
            elif not isinstance(
                self.coverage_acknowledgement, CoverageGapAcknowledgement
            ):
                raise TypeError(
                    "coverage_acknowledgement must be CoverageGapAcknowledgement, "
                    "mapping, or None"
                )

        if self.auto_file_blocked is not True:
            raise IdsAutoFileError("queue.auto_file_blocked must be True")
        object.__setattr__(self, "auto_file_blocked", True)

        if self.claims_exhaustive_search is not False:
            raise ExhaustiveSearchClaimError(
                "claims_exhaustive_search must be False on the IDS review queue"
            )
        object.__setattr__(self, "claims_exhaustive_search", False)

        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_IDS_QUEUE:
            raise ValueError(f"output_kind must be {OUTPUT_KIND_IDS_QUEUE!r}")
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        lower = self.disclaimer.lower()
        if "auto-file" not in lower and "never auto-file" not in lower:
            if "never auto-files" not in lower:
                raise IdsAutoFileError(
                    "disclaimer must state that the system never auto-files an IDS"
                )
        object.__setattr__(self, "metadata", _frozen_str_map(self.metadata, "metadata"))
        _assert_no_forbidden_keys(self.metadata, "IdsReviewQueue")
        assert_no_exhaustive_search_claim(self.to_dict())

    @property
    def content_digest(self) -> str:
        return content_digest(self.to_dict())

    def candidate(self, candidate_id: str) -> IdsReferenceCandidate:
        for cand in self.candidates:
            if cand.candidate_id == candidate_id:
                return cand
        raise KeyError(f"candidate_id {candidate_id!r} not in queue")

    def ids_ready_candidates(self) -> tuple[IdsReferenceCandidate, ...]:
        return tuple(c for c in self.candidates if c.is_ids_ready)

    def pending_review(self) -> tuple[IdsReferenceCandidate, ...]:
        return tuple(
            c
            for c in self.candidates
            if c.state
            in (
                IdsCandidateState.CANDIDATE,
                IdsCandidateState.UNDER_REVIEW,
                IdsCandidateState.RELEVANCE_REVIEWED,
                IdsCandidateState.MATERIALITY_REVIEWED,
            )
            and not c.is_ids_ready
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_file_blocked": True,
            "candidates": [c.to_dict() for c in self.candidates],
            "chart_id": self.chart_id,
            "claims_exhaustive_search": False,
            "coverage_acknowledgement": (
                None
                if self.coverage_acknowledgement is None
                else self.coverage_acknowledgement.to_dict()
            ),
            "disclaimer": self.disclaimer,
            "metadata": dict(self.metadata),
            "output_kind": self.output_kind,
            "queue_id": self.queue_id,
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IdsReviewQueue":
        value = _mapping(value, "IdsReviewQueue")
        return cls(
            schema_version=value.get(
                "schema_version", IDS_REVIEW_QUEUE_SCHEMA_VERSION
            ),
            queue_id=value.get("queue_id", ""),
            subject_id=value.get("subject_id", ""),
            candidates=tuple(value.get("candidates") or ()),
            chart_id=value.get("chart_id"),
            coverage_acknowledgement=value.get("coverage_acknowledgement"),
            auto_file_blocked=bool(value.get("auto_file_blocked", True)),
            claims_exhaustive_search=bool(
                value.get("claims_exhaustive_search", False)
            ),
            output_kind=value.get("output_kind", OUTPUT_KIND_IDS_QUEUE),
            disclaimer=value.get("disclaimer") or IDS_REVIEW_QUEUE_DISCLAIMER,
            metadata=value.get("metadata") or {},
        )


def _coerce_candidates(
    value: Any, field: str
) -> tuple[IdsReferenceCandidate, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence")
    out: list[IdsReferenceCandidate] = []
    for i, item in enumerate(value):
        if isinstance(item, IdsReferenceCandidate):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(IdsReferenceCandidate.from_dict(item))
        else:
            raise TypeError(f"{field}[{i}] must be IdsReferenceCandidate or mapping")
    return tuple(out)


# ---------------------------------------------------------------------------
# Builders / mutators
# ---------------------------------------------------------------------------


def build_ids_review_queue(
    *,
    subject_id: str,
    candidates: Sequence[IdsReferenceCandidate | Mapping[str, Any]] = (),
    queue_id: str | None = None,
    chart_id: str | None = None,
    coverage_acknowledgement: CoverageGapAcknowledgement | None = None,
    metadata: Mapping[str, str] | None = None,
) -> IdsReviewQueue:
    """Construct an empty or pre-populated human IDS review queue."""
    parsed = _coerce_candidates(candidates, "candidates")
    identity = {
        "candidates": [c.candidate_id for c in parsed],
        "chart_id": chart_id,
        "subject_id": subject_id,
    }
    digest = content_digest(identity)[:16]
    return IdsReviewQueue(
        schema_version=IDS_REVIEW_QUEUE_SCHEMA_VERSION,
        queue_id=queue_id or f"ids-queue:{digest}",
        subject_id=subject_id,
        candidates=parsed,
        chart_id=chart_id,
        coverage_acknowledgement=coverage_acknowledgement,
        auto_file_blocked=True,
        claims_exhaustive_search=False,
        metadata=metadata or {},
    )


def enqueue_from_chart_cell(
    queue: IdsReviewQueue,
    cell: ClaimChartCellV2 | Mapping[str, Any],
    *,
    reviewer_id: str,
    acted_at_utc: str,
    candidate_id: str | None = None,
    citation_text: str | None = None,
    identifiers: Mapping[str, str] | None = None,
    is_natural_person: bool = True,
) -> IdsReviewQueue:
    """Enqueue a chart cell's document as an IDS candidate (not IDS-ready)."""
    if not is_natural_person:
        raise IdsNaturalPersonError("enqueue requires a natural person operator")
    if isinstance(cell, Mapping):
        cell = ClaimChartCellV2.from_dict(cell)
    if cell.document_id is None:
        raise IdsReviewQueueError(
            f"cell {cell.cell_id} has no document_id; cannot enqueue for IDS"
        )

    # Deduplicate by document_id.
    for existing in queue.candidates:
        if existing.document_id == cell.document_id:
            # Attach cell id if missing.
            if cell.cell_id in existing.chart_cell_ids:
                return queue
            updated = IdsReferenceCandidate(
                candidate_id=existing.candidate_id,
                document_id=existing.document_id,
                subject_id=existing.subject_id,
                state=existing.state,
                chart_cell_ids=(*existing.chart_cell_ids, cell.cell_id),
                source_links=existing.source_links or cell.evidence_links,
                citation_text=existing.citation_text or citation_text,
                identifiers=dict(existing.identifiers),
                relevance=existing.relevance,
                materiality=existing.materiality,
                relevance_reviewer_id=existing.relevance_reviewer_id,
                materiality_reviewer_id=existing.materiality_reviewer_id,
                relevance_reviewed_at_utc=existing.relevance_reviewed_at_utc,
                materiality_reviewed_at_utc=existing.materiality_reviewed_at_utc,
                review_history=existing.review_history,
                is_ids_ready=existing.is_ids_ready,
                metadata=dict(existing.metadata),
            )
            return _replace_candidate(queue, updated)

    cand_id = candidate_id or f"ids-cand:{cell.document_id}:{content_digest(cell.cell_id)[:12]}"
    action = IdsReviewAction(
        action_id=f"act:{cand_id}:v1",
        candidate_id=cand_id,
        version=1,
        action_kind=IdsReviewActionKind.ENQUEUE,
        reviewer_id=reviewer_id,
        acted_at_utc=acted_at_utc,
        is_natural_person=True,
        notes=f"enqueued from chart cell {cell.cell_id}",
    )
    candidate = IdsReferenceCandidate(
        candidate_id=cand_id,
        document_id=cell.document_id,
        subject_id=queue.subject_id,
        state=IdsCandidateState.CANDIDATE,
        chart_cell_ids=(cell.cell_id,),
        source_links=cell.evidence_links,
        citation_text=citation_text,
        identifiers=identifiers or {"document_id": cell.document_id},
        relevance=RelevanceDisposition.UNREVIEWED,
        materiality=MaterialityDisposition.UNREVIEWED,
        review_history=(action,),
        is_ids_ready=False,
        metadata={
            "limitation_id": cell.limitation_id,
            "source_cell_disposition": cell.disposition.value,
        },
    )
    return IdsReviewQueue(
        schema_version=queue.schema_version,
        queue_id=queue.queue_id,
        subject_id=queue.subject_id,
        candidates=(*queue.candidates, candidate),
        chart_id=queue.chart_id,
        coverage_acknowledgement=queue.coverage_acknowledgement,
        auto_file_blocked=True,
        claims_exhaustive_search=False,
        disclaimer=queue.disclaimer,
        metadata=dict(queue.metadata),
    )


def enqueue_flagged_from_chart(
    queue: IdsReviewQueue,
    chart: ClaimChartV2,
    *,
    reviewer_id: str,
    acted_at_utc: str,
) -> IdsReviewQueue:
    """Enqueue all chart cells flagged for IDS (FLAG_FOR_IDS disposition)."""
    result = queue
    if queue.chart_id is None:
        result = IdsReviewQueue(
            schema_version=queue.schema_version,
            queue_id=queue.queue_id,
            subject_id=queue.subject_id,
            candidates=queue.candidates,
            chart_id=chart.chart_id,
            coverage_acknowledgement=queue.coverage_acknowledgement,
            auto_file_blocked=True,
            claims_exhaustive_search=False,
            disclaimer=queue.disclaimer,
            metadata=dict(queue.metadata),
        )
    for cell in chart.flagged_for_ids():
        if cell.document_id is None:
            continue
        result = enqueue_from_chart_cell(
            result,
            cell,
            reviewer_id=reviewer_id,
            acted_at_utc=acted_at_utc,
        )
    # Also allow FOUND cells explicitly routed even without flag when disposition
    # is FLAG_FOR_IDS only — already handled. Optionally enqueue any FOUND cell
    # with disposition FLAG_FOR_IDS only.
    return result


def _replace_candidate(
    queue: IdsReviewQueue, candidate: IdsReferenceCandidate
) -> IdsReviewQueue:
    new_cands: list[IdsReferenceCandidate] = []
    replaced = False
    for cand in queue.candidates:
        if cand.candidate_id == candidate.candidate_id:
            new_cands.append(candidate)
            replaced = True
        else:
            new_cands.append(cand)
    if not replaced:
        new_cands.append(candidate)
    return IdsReviewQueue(
        schema_version=queue.schema_version,
        queue_id=queue.queue_id,
        subject_id=queue.subject_id,
        candidates=tuple(new_cands),
        chart_id=queue.chart_id,
        coverage_acknowledgement=queue.coverage_acknowledgement,
        auto_file_blocked=True,
        claims_exhaustive_search=False,
        disclaimer=queue.disclaimer,
        metadata=dict(queue.metadata),
    )


def _append_action(
    candidate: IdsReferenceCandidate,
    *,
    action_kind: IdsReviewActionKind,
    reviewer_id: str,
    acted_at_utc: str,
    relevance: RelevanceDisposition | None = None,
    materiality: MaterialityDisposition | None = None,
    notes: str | None = None,
    action_id: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> tuple[IdsReferenceCandidate, IdsReviewAction]:
    next_version = candidate.current_review_version() + 1
    prev_digest = (
        candidate.review_history[-1].content_digest
        if candidate.review_history
        else None
    )
    action = IdsReviewAction(
        action_id=action_id
        or f"act:{candidate.candidate_id}:v{next_version}",
        candidate_id=candidate.candidate_id,
        version=next_version,
        action_kind=action_kind,
        reviewer_id=reviewer_id,
        acted_at_utc=acted_at_utc,
        is_natural_person=True,
        relevance=relevance,
        materiality=materiality,
        notes=notes,
        previous_version_digest=prev_digest,
        metadata=metadata or {},
    )
    # Caller rebuilds candidate with updated fields + history.
    return candidate, action


def record_relevance_review(
    queue: IdsReviewQueue,
    *,
    candidate_id: str,
    reviewer_id: str,
    disposition: RelevanceDisposition | str,
    acted_at_utc: str,
    notes: str | None = None,
    is_natural_person: bool = True,
) -> IdsReviewQueue:
    """Record natural-person relevance review (does not alone make IDS-ready)."""
    if not is_natural_person:
        raise IdsNaturalPersonError("relevance review requires a natural person")
    disp = _coerce_enum(RelevanceDisposition, disposition, "disposition")
    assert isinstance(disp, RelevanceDisposition)
    if disp is RelevanceDisposition.UNREVIEWED:
        raise IdsReviewQueueError("relevance disposition must not be unreviewed")

    cand = queue.candidate(candidate_id)
    _, action = _append_action(
        cand,
        action_kind=IdsReviewActionKind.SET_RELEVANCE,
        reviewer_id=reviewer_id,
        acted_at_utc=acted_at_utc,
        relevance=disp,
        notes=notes,
    )
    new_state = cand.state
    if cand.has_natural_person_materiality_review():
        new_state = IdsCandidateState.MATERIALITY_REVIEWED
    else:
        new_state = IdsCandidateState.RELEVANCE_REVIEWED
    if new_state is IdsCandidateState.CANDIDATE:
        new_state = IdsCandidateState.UNDER_REVIEW

    updated = IdsReferenceCandidate(
        candidate_id=cand.candidate_id,
        document_id=cand.document_id,
        subject_id=cand.subject_id,
        state=new_state if not cand.is_ids_ready else IdsCandidateState.IDS_READY,
        chart_cell_ids=cand.chart_cell_ids,
        source_links=cand.source_links,
        citation_text=cand.citation_text,
        identifiers=dict(cand.identifiers),
        relevance=disp,
        materiality=cand.materiality,
        relevance_reviewer_id=reviewer_id,
        materiality_reviewer_id=cand.materiality_reviewer_id,
        relevance_reviewed_at_utc=acted_at_utc,
        materiality_reviewed_at_utc=cand.materiality_reviewed_at_utc,
        review_history=(*cand.review_history, action),
        is_ids_ready=False,  # never auto-promote
        metadata=dict(cand.metadata),
    )
    return _replace_candidate(queue, updated)


def record_materiality_review(
    queue: IdsReviewQueue,
    *,
    candidate_id: str,
    reviewer_id: str,
    disposition: MaterialityDisposition | str,
    acted_at_utc: str,
    notes: str | None = None,
    is_natural_person: bool = True,
) -> IdsReviewQueue:
    """Record natural-person materiality review (does not alone make IDS-ready)."""
    if not is_natural_person:
        raise IdsNaturalPersonError("materiality review requires a natural person")
    disp = _coerce_enum(MaterialityDisposition, disposition, "disposition")
    assert isinstance(disp, MaterialityDisposition)
    if disp is MaterialityDisposition.UNREVIEWED:
        raise IdsReviewQueueError("materiality disposition must not be unreviewed")

    cand = queue.candidate(candidate_id)
    _, action = _append_action(
        cand,
        action_kind=IdsReviewActionKind.SET_MATERIALITY,
        reviewer_id=reviewer_id,
        acted_at_utc=acted_at_utc,
        materiality=disp,
        notes=notes,
    )
    if cand.has_natural_person_relevance_review():
        new_state = IdsCandidateState.RELEVANCE_REVIEWED
    else:
        new_state = IdsCandidateState.MATERIALITY_REVIEWED
    if cand.state is IdsCandidateState.CANDIDATE:
        new_state = IdsCandidateState.UNDER_REVIEW

    updated = IdsReferenceCandidate(
        candidate_id=cand.candidate_id,
        document_id=cand.document_id,
        subject_id=cand.subject_id,
        state=new_state,
        chart_cell_ids=cand.chart_cell_ids,
        source_links=cand.source_links,
        citation_text=cand.citation_text,
        identifiers=dict(cand.identifiers),
        relevance=cand.relevance,
        materiality=disp,
        relevance_reviewer_id=cand.relevance_reviewer_id,
        materiality_reviewer_id=reviewer_id,
        relevance_reviewed_at_utc=cand.relevance_reviewed_at_utc,
        materiality_reviewed_at_utc=acted_at_utc,
        review_history=(*cand.review_history, action),
        is_ids_ready=False,  # never auto-promote
        metadata=dict(cand.metadata),
    )
    return _replace_candidate(queue, updated)


def promote_to_ids_ready(
    queue: IdsReviewQueue,
    *,
    candidate_id: str,
    reviewer_id: str,
    acted_at_utc: str,
    notes: str | None = None,
    is_natural_person: bool = True,
    require_coverage_acknowledgement: bool = False,
) -> IdsReviewQueue:
    """Promote a candidate to IDS-ready only after relevance + materiality review.

    Raises :class:`IdsReadyGateError` if natural-person relevance and materiality
    reviews are incomplete or non-affirmative.
    """
    if not is_natural_person:
        raise IdsNaturalPersonError("IDS-ready promotion requires a natural person")
    if require_coverage_acknowledgement:
        ack = queue.coverage_acknowledgement
        if ack is None or not ack.is_signed:
            raise IdsReadyGateError(
                "signed coverage-gap acknowledgement required before IDS-ready "
                "promotion when require_coverage_acknowledgement=True"
            )

    cand = queue.candidate(candidate_id)
    # Pre-check gate using projected fields.
    if not cand.has_natural_person_relevance_review():
        raise IdsReadyGateError(
            f"candidate {candidate_id} lacks natural-person relevance review"
        )
    if not cand.has_natural_person_materiality_review():
        raise IdsReadyGateError(
            f"candidate {candidate_id} lacks natural-person materiality review"
        )
    if cand.relevance is not RelevanceDisposition.RELEVANT:
        raise IdsReadyGateError(
            f"candidate {candidate_id} relevance must be relevant for IDS-ready"
        )
    if cand.materiality is not MaterialityDisposition.MATERIAL:
        raise IdsReadyGateError(
            f"candidate {candidate_id} materiality must be material for IDS-ready"
        )

    _, action = _append_action(
        cand,
        action_kind=IdsReviewActionKind.PROMOTE_IDS_READY,
        reviewer_id=reviewer_id,
        acted_at_utc=acted_at_utc,
        relevance=cand.relevance,
        materiality=cand.materiality,
        notes=notes or "promoted to IDS-ready after natural-person review",
    )
    updated = IdsReferenceCandidate(
        candidate_id=cand.candidate_id,
        document_id=cand.document_id,
        subject_id=cand.subject_id,
        state=IdsCandidateState.IDS_READY,
        chart_cell_ids=cand.chart_cell_ids,
        source_links=cand.source_links,
        citation_text=cand.citation_text,
        identifiers=dict(cand.identifiers),
        relevance=cand.relevance,
        materiality=cand.materiality,
        relevance_reviewer_id=cand.relevance_reviewer_id,
        materiality_reviewer_id=cand.materiality_reviewer_id,
        relevance_reviewed_at_utc=cand.relevance_reviewed_at_utc,
        materiality_reviewed_at_utc=cand.materiality_reviewed_at_utc,
        review_history=(*cand.review_history, action),
        is_ids_ready=True,
        metadata=dict(cand.metadata),
    )
    return _replace_candidate(queue, updated)


def reject_candidate(
    queue: IdsReviewQueue,
    *,
    candidate_id: str,
    reviewer_id: str,
    acted_at_utc: str,
    notes: str | None = None,
    is_natural_person: bool = True,
) -> IdsReviewQueue:
    """Reject a candidate (versioned); never files anything."""
    if not is_natural_person:
        raise IdsNaturalPersonError("rejection requires a natural person")
    cand = queue.candidate(candidate_id)
    _, action = _append_action(
        cand,
        action_kind=IdsReviewActionKind.REJECT,
        reviewer_id=reviewer_id,
        acted_at_utc=acted_at_utc,
        notes=notes,
    )
    updated = IdsReferenceCandidate(
        candidate_id=cand.candidate_id,
        document_id=cand.document_id,
        subject_id=cand.subject_id,
        state=IdsCandidateState.REJECTED,
        chart_cell_ids=cand.chart_cell_ids,
        source_links=cand.source_links,
        citation_text=cand.citation_text,
        identifiers=dict(cand.identifiers),
        relevance=cand.relevance,
        materiality=cand.materiality,
        relevance_reviewer_id=cand.relevance_reviewer_id,
        materiality_reviewer_id=cand.materiality_reviewer_id,
        relevance_reviewed_at_utc=cand.relevance_reviewed_at_utc,
        materiality_reviewed_at_utc=cand.materiality_reviewed_at_utc,
        review_history=(*cand.review_history, action),
        is_ids_ready=False,
        metadata=dict(cand.metadata),
    )
    return _replace_candidate(queue, updated)


def attach_queue_coverage_acknowledgement(
    queue: IdsReviewQueue,
    acknowledgement: CoverageGapAcknowledgement,
) -> IdsReviewQueue:
    """Attach a signed searched/gap acknowledgement to the queue."""
    if not acknowledgement.is_signed:
        raise IdsReadyGateError(
            "coverage acknowledgement must be signed before attachment"
        )
    return IdsReviewQueue(
        schema_version=queue.schema_version,
        queue_id=queue.queue_id,
        subject_id=queue.subject_id,
        candidates=queue.candidates,
        chart_id=queue.chart_id or acknowledgement.chart_id,
        coverage_acknowledgement=acknowledgement,
        auto_file_blocked=True,
        claims_exhaustive_search=False,
        disclaimer=queue.disclaimer,
        metadata=dict(queue.metadata),
    )


def assert_not_ids_ready_without_review(
    queue: IdsReviewQueue | Mapping[str, Any] | IdsReferenceCandidate,
) -> None:
    """Raise if any IDS-ready candidate lacks natural-person dual review."""
    if isinstance(queue, IdsReferenceCandidate):
        if queue.is_ids_ready or queue.state is IdsCandidateState.IDS_READY:
            _assert_ids_ready_gate(queue)
        return
    if isinstance(queue, Mapping):
        queue = IdsReviewQueue.from_dict(queue)
    for cand in queue.candidates:
        if cand.is_ids_ready or cand.state is IdsCandidateState.IDS_READY:
            _assert_ids_ready_gate(cand)


def assert_auto_file_blocked(
    queue: IdsReviewQueue | Mapping[str, Any],
) -> None:
    """Raise if the queue is configured to auto-file."""
    if isinstance(queue, Mapping):
        queue = IdsReviewQueue.from_dict(queue)
    if not queue.auto_file_blocked:
        raise IdsAutoFileError("queue must block auto-file")
    for cand in queue.candidates:
        if not cand.auto_file_blocked:
            raise IdsAutoFileError(
                f"candidate {cand.candidate_id} must block auto-file"
            )


def build_prior_art_review_package(
    chart: ClaimChartV2,
    queue: IdsReviewQueue,
    *,
    package_id: str | None = None,
    coverage_acknowledgement: CoverageGapAcknowledgement | None = None,
    metadata: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Serialize a combined prior-art review package (chart + IDS queue).

    Requires that coverage gaps remain prominent on the chart and that the
    package does not claim an exhaustive search. When a coverage acknowledgement
    is supplied it must be signed and is attached to both surfaces in the
    package payload.
    """
    from .claim_chart_v2 import (
        OUTPUT_KIND_PRIOR_ART_REVIEW,
        assert_cells_link_spans_or_status,
        assert_coverage_gaps_prominent,
        assert_reviewer_changes_versioned,
    )

    assert_cells_link_spans_or_status(chart)
    assert_coverage_gaps_prominent(chart)
    assert_reviewer_changes_versioned(chart)
    assert_not_ids_ready_without_review(queue)
    assert_auto_file_blocked(queue)

    ack = coverage_acknowledgement or chart.coverage_acknowledgement or (
        queue.coverage_acknowledgement
    )
    if ack is not None and not ack.is_signed:
        raise IdsReadyGateError(
            "coverage acknowledgement on the review package must be signed"
        )

    package = {
        "chart": chart.to_dict(),
        "claims_exhaustive_search": False,
        "coverage_acknowledgement": None if ack is None else ack.to_dict(),
        "disclaimer": (
            f"{CLAIM_CHART_V2_DISCLAIMER} {IDS_REVIEW_QUEUE_DISCLAIMER}"
        ),
        "ids_queue": queue.to_dict(),
        "metadata": dict(metadata or {}),
        "output_kind": OUTPUT_KIND_PRIOR_ART_REVIEW,
        "package_id": package_id
        or f"review:{chart.chart_id}:{queue.queue_id}",
        "schema_version": "patent.prior_art_review_package.v1",
        "subject_id": chart.subject_id,
    }
    assert_no_exhaustive_search_claim(package)
    return package


# Re-export for callers that only import the queue module.
content_digest_chart = chart_content_digest


__all__ = [
    "IDS_REVIEW_QUEUE_CODE_VERSION",
    "IDS_REVIEW_QUEUE_DISCLAIMER",
    "IDS_REVIEW_QUEUE_INTERFACE",
    "IDS_REVIEW_QUEUE_SCHEMA_VERSION",
    "OUTPUT_KIND_IDS_CANDIDATE",
    "OUTPUT_KIND_IDS_QUEUE",
    "OUTPUT_KIND_IDS_REVIEW_ACTION",
    "IdsAutoFileError",
    "IdsCandidateState",
    "IdsNaturalPersonError",
    "IdsReadyGateError",
    "IdsReferenceCandidate",
    "IdsReviewAction",
    "IdsReviewActionKind",
    "IdsReviewQueue",
    "IdsReviewQueueError",
    "IdsReviewVersionError",
    "MaterialityDisposition",
    "RelevanceDisposition",
    "assert_auto_file_blocked",
    "assert_not_ids_ready_without_review",
    "attach_queue_coverage_acknowledgement",
    "build_ids_review_queue",
    "build_prior_art_review_package",
    "canonical_json",
    "content_digest",
    "enqueue_flagged_from_chart",
    "enqueue_from_chart_cell",
    "promote_to_ids_ready",
    "record_materiality_review",
    "record_relevance_review",
    "reject_candidate",
]
