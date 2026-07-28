"""Redacted proof-query audit receipts (ProofQueryAuditReceipt@1 / LIG-031).

Every hard-filtered proof query emits a content-addressed audit receipt that
traces considered / filtered / ranked / selected / rejected counts and
reasons, budgets, and coverage gaps — without raw prompts, arguments,
secrets, witnesses, private formulas, or unbounded free-form labels.

This leaf consumes :mod:`.applicability` results and never re-runs ranking as
authority.  Private diagnostic material is replaced with bounded redaction
placeholders that preserve length and content digests for forensic correlation
without leaking values.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from .applicability import (
    PROOF_APPLICABILITY_FILTER_INTERFACE,
    FilterDisposition,
    HardFilterAssessment,
    ProofApplicabilityError,
    ProofApplicabilityQuery,
    ProofApplicabilityResult,
    RankedCandidate,
    SelectionDisposition,
    _reason_label,
)

PROOF_QUERY_AUDIT_RECEIPT_INTERFACE: Final = "ProofQueryAuditReceipt@1"
PROOF_QUERY_AUDIT_RECEIPT_SCHEMA_VERSION: Final = "proof-query-audit-receipt/v1"
AUDIT_TRACE_EVENT_SCHEMA_VERSION: Final = "proof-query-audit-event/v1"
REDACTION_NOTE_SCHEMA_VERSION: Final = "proof-query-redaction-note/v1"

MAX_AUDIT_EVENTS: Final = 1_024
MAX_REASON_LABELS: Final = 256
MAX_LABEL_CHARS: Final = 128
MAX_REDACTION_NOTES: Final = 256
MAX_TRACE_DEPTH: Final = 64

# Keys / substrings that must never appear as raw values in audit receipts.
_SECRET_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "credential",
    "auth_header",
    "authorization",
    "bearer",
    "session",
    "cookie",
    "witness",
    "prover_key",
    "signing_key",
)

_PRIVATE_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "prompt",
        "prompts",
        "raw_prompt",
        "system_prompt",
        "user_prompt",
        "arguments",
        "args",
        "kwargs",
        "call_arguments",
        "tool_arguments",
        "secret",
        "secrets",
        "password",
        "token",
        "api_key",
        "private_key",
        "witness",
        "witnesses",
        "witness_bytes",
        "private_formula",
        "private_formulas",
        "formula_text",
        "raw_formula",
        "llm_text",
        "model_output",
        "plaintext",
        "cleartext",
        "unredacted",
    }
)

# Unbounded free-form text keys that are replaced with digests.
_UNBOUNDED_LABEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "notes",
        "description",
        "message",
        "detail",
        "details",
        "comment",
        "comments",
        "rationale",
        "explanation",
        "label",
        "labels",
        "text",
        "body",
        "content",
        "statement",
        "raw",
        "debug",
        "trace_text",
    }
)

_REDACTION_PLACEHOLDER_RE: Final = re.compile(
    r"^<redacted:[a-z0-9_./+-]+ length=\d+ digest=sha256:[0-9a-f]{16,64}>$"
)


class ProofQueryAuditError(ProofApplicabilityError):
    """Raised when an audit receipt cannot be constructed safely."""


class AuditEventKind(str, Enum):
    """Closed vocabulary for redacted audit trace events."""

    QUERY_START = "query_start"
    CANDIDATE_CONSIDERED = "candidate_considered"
    CANDIDATE_FILTERED = "candidate_filtered"
    CANDIDATE_REJECTED = "candidate_rejected"
    CANDIDATE_ADMITTED = "candidate_admitted"
    CANDIDATE_RANKED = "candidate_ranked"
    CANDIDATE_SELECTED = "candidate_selected"
    BUDGET_APPLIED = "budget_applied"
    GAP_RECORDED = "gap_recorded"
    QUERY_COMPLETE = "query_complete"
    REDACTION = "redaction"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_hex_prefix(data: bytes, length: int = 16) -> str:
    return hashlib.sha256(data).hexdigest()[:length]


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise ProofQueryAuditError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the audit receipt"
    )


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProofQueryAuditError(f"{label} must be a mapping")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProofQueryAuditError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if len(value) > 4_096:
        raise ProofQueryAuditError(
            f"{field_name} exceeds maximum safe length"
        )
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, field_name)


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProofQueryAuditError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProofQueryAuditError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _parse_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ProofQueryAuditError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def _key_looks_secret(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in _PRIVATE_PAYLOAD_KEYS or lowered in _UNBOUNDED_LABEL_KEYS:
        return True
    return any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS)


def redaction_placeholder(label: str, value: Any) -> str:
    """Return a bounded redaction placeholder for a private value."""

    safe_label = re.sub(r"[^a-z0-9_./+-]", "", label.lower())[:64] or "value"
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        length = len(raw)
        digest = _sha256_hex_prefix(raw, 32)
    else:
        text = value if isinstance(value, str) else json.dumps(
            _json_ready(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        raw = text.encode("utf-8")
        length = len(text)
        digest = _sha256_hex_prefix(raw, 32)
    return f"<redacted:{safe_label} length={length} digest=sha256:{digest}>"


def is_redaction_placeholder(value: Any) -> bool:
    """Return whether *value* is already a redaction placeholder."""

    return isinstance(value, str) and bool(_REDACTION_PLACEHOLDER_RE.fullmatch(value))


@dataclass(frozen=True, slots=True)
class RedactionNote:
    """One redaction applied while building an audit receipt."""

    path: str
    label: str
    length: int
    content_digest: str
    schema_version: str = REDACTION_NOTE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _require_text(self.path, "path"))
        object.__setattr__(self, "label", _require_text(self.label, "label"))
        object.__setattr__(
            self, "length", _non_negative_int(self.length, "length")
        )
        digest = _require_text(self.content_digest, "content_digest")
        if not digest.startswith("sha256:"):
            raise ProofQueryAuditError(
                "content_digest must be a sha256:<hex> digest"
            )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != REDACTION_NOTE_SCHEMA_VERSION:
            raise ProofQueryAuditError(
                f"unsupported redaction note schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "label": self.label,
            "length": self.length,
            "path": self.path,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "RedactionNote":
        payload = dict(_as_mapping(value, "redaction note"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "content_digest",
                    "label",
                    "length",
                    "path",
                    "schema_version",
                }
            ),
            "redaction note",
        )
        return cls(
            path=payload.get("path", ""),
            label=payload.get("label", ""),
            length=int(payload.get("length", 0)),
            content_digest=payload.get("content_digest", ""),
            schema_version=payload.get(
                "schema_version", REDACTION_NOTE_SCHEMA_VERSION
            ),
        )


def redact_value(
    value: Any,
    *,
    path: str = "root",
    notes: list[RedactionNote] | None = None,
    depth: int = 0,
) -> Any:
    """Recursively redact private / unbounded content from a JSON-like value.

    Safe scalars, bounded reason labels, CIDs, digests, and counts pass
    through.  Private keys, secret-like keys, and unbounded free-form strings
    become redaction placeholders.
    """

    if depth > MAX_TRACE_DEPTH:
        placeholder = redaction_placeholder("depth_exceeded", str(value)[:64])
        if notes is not None:
            notes.append(
                RedactionNote(
                    path=path,
                    label="depth_exceeded",
                    length=len(str(value)),
                    content_digest="sha256:"
                    + _sha256_hex_prefix(str(value).encode("utf-8"), 32),
                )
            )
        return placeholder

    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and (
            value != value or value in (float("inf"), float("-inf"))
        ):
            return 0.0
        return value

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, (bytes, bytearray)):
        placeholder = redaction_placeholder("bytes", value)
        if notes is not None:
            notes.append(
                RedactionNote(
                    path=path,
                    label="bytes",
                    length=len(value),
                    content_digest="sha256:"
                    + _sha256_hex_prefix(bytes(value), 32),
                )
            )
        return placeholder

    if isinstance(value, str):
        if is_redaction_placeholder(value):
            return value
        # Digests, CIDs, and short bounded reason labels are allowed.
        if value.startswith("sha256:") and len(value) <= 80:
            return value
        if re.fullmatch(r"b[a-z2-7]{10,200}", value):
            return value
        if len(value) <= MAX_LABEL_CHARS and re.fullmatch(
            r"[a-zA-Z0-9_.:/@+-]+", value
        ):
            return value
        placeholder = redaction_placeholder("text", value)
        if notes is not None:
            notes.append(
                RedactionNote(
                    path=path,
                    label="text",
                    length=len(value),
                    content_digest="sha256:"
                    + _sha256_hex_prefix(value.encode("utf-8"), 32),
                )
            )
        return placeholder

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if _key_looks_secret(key_text):
                placeholder = redaction_placeholder(key_text, item)
                redacted[key_text] = placeholder
                if notes is not None:
                    raw = (
                        item
                        if isinstance(item, (str, bytes, bytearray))
                        else json.dumps(
                            _json_ready(item),
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    )
                    if isinstance(raw, str):
                        raw_bytes = raw.encode("utf-8")
                        length = len(raw)
                    else:
                        raw_bytes = bytes(raw)
                        length = len(raw_bytes)
                    notes.append(
                        RedactionNote(
                            path=child_path,
                            label=key_text,
                            length=length,
                            content_digest="sha256:"
                            + _sha256_hex_prefix(raw_bytes, 32),
                        )
                    )
                continue
            redacted[key_text] = redact_value(
                item, path=child_path, notes=notes, depth=depth + 1
            )
        return redacted

    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [
            redact_value(
                item,
                path=f"{path}[{index}]",
                notes=notes,
                depth=depth + 1,
            )
            for index, item in enumerate(value)
        ]

    # Fallback: opaque object → placeholder.
    placeholder = redaction_placeholder("opaque", str(type(value).__name__))
    if notes is not None:
        notes.append(
            RedactionNote(
                path=path,
                label="opaque",
                length=0,
                content_digest="sha256:"
                + _sha256_hex_prefix(type(value).__name__.encode("utf-8"), 32),
            )
        )
    return placeholder


@dataclass(frozen=True, slots=True)
class AuditTraceEvent:
    """One ordered, redacted event in a proof-query audit trace."""

    ordinal: int
    kind: AuditEventKind | str
    envelope_cid: str = ""
    reasons: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = AUDIT_TRACE_EVENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ordinal", _non_negative_int(self.ordinal, "ordinal")
        )
        object.__setattr__(
            self, "kind", _parse_enum(self.kind, AuditEventKind, "kind")
        )
        if self.envelope_cid not in ("", None):
            cid = _require_text(self.envelope_cid, "envelope_cid")
            if not re.fullmatch(r"b[a-z2-7]{10,200}", cid):
                raise ProofQueryAuditError(
                    "envelope_cid must be a CIDv1 base32 string when set"
                )
            object.__setattr__(self, "envelope_cid", cid)
        else:
            object.__setattr__(self, "envelope_cid", "")

        reasons_raw = self.reasons if self.reasons is not None else ()
        if isinstance(reasons_raw, (str, bytes, bytearray)):
            raise ProofQueryAuditError("reasons must be a sequence of strings")
        ordered_reasons: list[str] = []
        seen: set[str] = set()
        for item in reasons_raw:
            label = _reason_label(str(item))
            if label not in seen:
                seen.add(label)
                ordered_reasons.append(label)
        if len(ordered_reasons) > MAX_REASON_LABELS:
            raise ProofQueryAuditError(
                f"reasons exceeds {MAX_REASON_LABELS} labels"
            )
        object.__setattr__(self, "reasons", tuple(ordered_reasons))

        attrs = redact_value(
            dict(_as_mapping(self.attributes, "attributes")),
            path="attributes",
        )
        if not isinstance(attrs, dict):
            raise ProofQueryAuditError("attributes must redact to a mapping")
        # Reject any private keys that survived (defense in depth).
        for key in attrs:
            if _key_looks_secret(str(key)):
                # Value should already be a placeholder; key presence is ok
                # only when value is redacted.
                if not is_redaction_placeholder(attrs[key]):
                    raise ProofQueryAuditError(
                        f"attributes contain unredacted private key: {key!r}"
                    )
        object.__setattr__(self, "attributes", MappingProxyType(attrs))
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != AUDIT_TRACE_EVENT_SCHEMA_VERSION:
            raise ProofQueryAuditError(
                f"unsupported audit event schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "envelope_cid": self.envelope_cid,
            "kind": self.kind.value,
            "ordinal": self.ordinal,
            "reasons": list(self.reasons),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "AuditTraceEvent":
        payload = dict(_as_mapping(value, "audit trace event"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "attributes",
                    "envelope_cid",
                    "kind",
                    "ordinal",
                    "reasons",
                    "schema_version",
                }
            ),
            "audit trace event",
        )
        return cls(
            ordinal=int(payload.get("ordinal", 0)),
            kind=payload.get("kind", AuditEventKind.QUERY_COMPLETE),
            envelope_cid=payload.get("envelope_cid", ""),
            reasons=tuple(payload.get("reasons", ()) or ()),
            attributes=dict(payload.get("attributes", {}) or {}),
            schema_version=payload.get(
                "schema_version", AUDIT_TRACE_EVENT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ProofQueryAuditReceipt:
    """ProofQueryAuditReceipt@1 — redacted, content-addressed query audit.

    Traces considered / filtered / ranked / selected / rejected counts and
    reasons, budgets, and gaps without private payloads.  Ranking is recorded
    only as an advisory ordering of hard-filter admissions.
    """

    receipt_id: str
    query_id: str
    disposition: SelectionDisposition | str
    considered_count: int = 0
    filtered_count: int = 0
    ranked_count: int = 0
    selected_count: int = 0
    rejected_count: int = 0
    reason_counts: Mapping[str, int] = field(default_factory=dict)
    budgets: Mapping[str, int] = field(default_factory=dict)
    gaps: tuple[str, ...] = ()
    selected_cids: tuple[str, ...] = ()
    rejected_reason_summary: tuple[str, ...] = ()
    events: tuple[AuditTraceEvent, ...] = ()
    redaction_notes: tuple[RedactionNote, ...] = ()
    retrieval_rank_used_for_authority: bool = False
    query_digest: str = ""
    result_digest: str = ""
    policy_digest: str = ""
    applicability_interface: str = PROOF_APPLICABILITY_FILTER_INTERFACE
    producer_id: str = ""
    content_digest: str = ""
    content_cid: str = ""
    schema_version: str = PROOF_QUERY_AUDIT_RECEIPT_SCHEMA_VERSION
    interface: str = PROOF_QUERY_AUDIT_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _require_text(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "query_id", _require_text(self.query_id, "query_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _parse_enum(self.disposition, SelectionDisposition, "disposition"),
        )
        for name in (
            "considered_count",
            "filtered_count",
            "ranked_count",
            "selected_count",
            "rejected_count",
        ):
            object.__setattr__(
                self, name, _non_negative_int(getattr(self, name), name)
            )

        reason_counts_raw = dict(_as_mapping(self.reason_counts, "reason_counts"))
        reason_counts: dict[str, int] = {}
        for key, value in sorted(
            reason_counts_raw.items(), key=lambda pair: str(pair[0])
        ):
            label = _reason_label(str(key))
            reason_counts[label] = _non_negative_int(
                value, f"reason_counts[{label}]"
            )
        if len(reason_counts) > MAX_REASON_LABELS:
            raise ProofQueryAuditError(
                f"reason_counts exceeds {MAX_REASON_LABELS} labels"
            )
        object.__setattr__(self, "reason_counts", MappingProxyType(reason_counts))

        budgets_raw = dict(_as_mapping(self.budgets, "budgets"))
        budgets: dict[str, int] = {}
        for key, value in sorted(
            budgets_raw.items(), key=lambda pair: str(pair[0])
        ):
            key_text = _require_text(str(key), "budgets key")
            if _key_looks_secret(key_text):
                raise ProofQueryAuditError(
                    f"budgets key must not be private: {key_text!r}"
                )
            budgets[key_text] = _non_negative_int(value, f"budgets[{key_text}]")
        object.__setattr__(self, "budgets", MappingProxyType(budgets))

        gaps_ordered: list[str] = []
        seen_gaps: set[str] = set()
        for item in self.gaps or ():
            label = _reason_label(str(item))
            if label not in seen_gaps:
                seen_gaps.add(label)
                gaps_ordered.append(label)
        object.__setattr__(self, "gaps", tuple(gaps_ordered))

        selected: list[str] = []
        seen_sel: set[str] = set()
        for item in self.selected_cids or ():
            cid = _require_text(str(item), "selected_cids")
            if not re.fullmatch(r"b[a-z2-7]{10,200}", cid):
                raise ProofQueryAuditError(
                    "selected_cids must be CIDv1 base32 strings"
                )
            if cid not in seen_sel:
                seen_sel.add(cid)
                selected.append(cid)
        object.__setattr__(self, "selected_cids", tuple(selected))

        rejected_summary: list[str] = []
        seen_rej: set[str] = set()
        for item in self.rejected_reason_summary or ():
            label = _reason_label(str(item))
            if label not in seen_rej:
                seen_rej.add(label)
                rejected_summary.append(label)
        object.__setattr__(
            self, "rejected_reason_summary", tuple(rejected_summary)
        )

        events = tuple(self.events)
        if len(events) > MAX_AUDIT_EVENTS:
            raise ProofQueryAuditError(
                f"events exceeds {MAX_AUDIT_EVENTS} entries"
            )
        for event in events:
            if not isinstance(event, AuditTraceEvent):
                raise ProofQueryAuditError(
                    "events must be AuditTraceEvent instances"
                )
        object.__setattr__(
            self,
            "events",
            tuple(sorted(events, key=lambda item: item.ordinal)),
        )

        notes = tuple(self.redaction_notes)
        if len(notes) > MAX_REDACTION_NOTES:
            raise ProofQueryAuditError(
                f"redaction_notes exceeds {MAX_REDACTION_NOTES} entries"
            )
        for note in notes:
            if not isinstance(note, RedactionNote):
                raise ProofQueryAuditError(
                    "redaction_notes must be RedactionNote instances"
                )
        object.__setattr__(
            self,
            "redaction_notes",
            tuple(sorted(notes, key=lambda item: item.path)),
        )

        if not isinstance(self.retrieval_rank_used_for_authority, bool):
            raise ProofQueryAuditError(
                "retrieval_rank_used_for_authority must be a bool"
            )
        if self.retrieval_rank_used_for_authority:
            raise ProofQueryAuditError(
                "audit receipts must not claim ranking establishes authority"
            )

        object.__setattr__(
            self,
            "query_digest",
            _optional_text(self.query_digest, "query_digest"),
        )
        object.__setattr__(
            self,
            "result_digest",
            _optional_text(self.result_digest, "result_digest"),
        )
        object.__setattr__(
            self,
            "policy_digest",
            _optional_text(self.policy_digest, "policy_digest"),
        )
        object.__setattr__(
            self,
            "applicability_interface",
            _require_text(
                self.applicability_interface, "applicability_interface"
            ),
        )
        object.__setattr__(
            self, "producer_id", _optional_text(self.producer_id, "producer_id")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_QUERY_AUDIT_RECEIPT_SCHEMA_VERSION:
            raise ProofQueryAuditError(
                f"unsupported audit receipt schema: {self.schema_version!r}"
            )
        if self.interface != PROOF_QUERY_AUDIT_RECEIPT_INTERFACE:
            raise ProofQueryAuditError(
                f"unsupported audit receipt interface: {self.interface!r}"
            )

        # Bind content identity when not supplied.
        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        # Lightweight CID-like binding: hash digest into a deterministic token
        # without requiring the full multiformats stack for the audit leaf.
        # Prefer digest equality; store digest-derived pseudo-CID for stability.
        from ..ir_core.identity import cid_v1_from_digest

        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest and self.content_digest != digest:
            raise ProofQueryAuditError(
                "content_digest does not match recomputed audit identity"
            )
        if self.content_cid and self.content_cid != cid:
            raise ProofQueryAuditError(
                "content_cid does not match recomputed audit identity"
            )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)

        if self.selected_count != len(self.selected_cids):
            raise ProofQueryAuditError(
                "selected_count does not match selected_cids"
            )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "applicability_interface": self.applicability_interface,
            "budgets": dict(self.budgets),
            "considered_count": self.considered_count,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, SelectionDisposition)
                else str(self.disposition)
            ),
            "events": [item.to_dict() for item in self.events],
            "filtered_count": self.filtered_count,
            "gaps": list(self.gaps),
            "interface": self.interface,
            "policy_digest": self.policy_digest,
            "producer_id": self.producer_id,
            "query_digest": self.query_digest,
            "query_id": self.query_id,
            "ranked_count": self.ranked_count,
            "reason_counts": dict(self.reason_counts),
            "receipt_id": self.receipt_id,
            "redaction_notes": [item.to_dict() for item in self.redaction_notes],
            "rejected_count": self.rejected_count,
            "rejected_reason_summary": list(self.rejected_reason_summary),
            "result_digest": self.result_digest,
            "retrieval_rank_used_for_authority": False,
            "schema_version": self.schema_version,
            "selected_cids": list(self.selected_cids),
            "selected_count": self.selected_count,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        payload["ranking_establishes_applicability"] = False
        return payload

    def verify_integrity(self) -> "ProofQueryAuditReceipt":
        """Recompute identity; fail closed on digest/CID drift."""

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        from ..ir_core.identity import cid_v1_from_digest

        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if digest != self.content_digest:
            raise ProofQueryAuditError(
                "content_digest does not match recomputed audit identity"
            )
        if cid != self.content_cid:
            raise ProofQueryAuditError(
                "content_cid does not match recomputed audit identity"
            )
        return self

    def contains_private_payload_keys(self) -> bool:
        """Return True if any unredacted private *value* is present.

        Redaction notes intentionally record the private *key labels* that were
        withheld; those labels are not treated as payload leaks.  A leak is a
        private key whose value is still cleartext (not a redaction placeholder).
        """

        def _walk(node: Any, *, under_redaction_notes: bool = False) -> bool:
            if isinstance(node, Mapping):
                for key, value in node.items():
                    key_text = str(key)
                    # Metadata describing what was redacted is not a leak.
                    if under_redaction_notes and key_text in {
                        "label",
                        "path",
                        "length",
                        "content_digest",
                        "schema_version",
                    }:
                        continue
                    child_under_notes = under_redaction_notes or (
                        key_text == "redaction_notes"
                    )
                    if (
                        not child_under_notes
                        and _key_looks_secret(key_text)
                        and not is_redaction_placeholder(value)
                    ):
                        return True
                    if _walk(value, under_redaction_notes=child_under_notes):
                        return True
            elif isinstance(node, Sequence) and not isinstance(
                node, (str, bytes, bytearray)
            ):
                return any(
                    _walk(item, under_redaction_notes=under_redaction_notes)
                    for item in node
                )
            return False

        return _walk(self.to_dict())

    @classmethod
    def from_dict(cls, value: Any) -> "ProofQueryAuditReceipt":
        payload = dict(_as_mapping(value, "proof query audit receipt"))
        payload.pop("ranking_establishes_applicability", None)
        _reject_unknown(
            payload,
            frozenset(
                {
                    "applicability_interface",
                    "budgets",
                    "considered_count",
                    "content_cid",
                    "content_digest",
                    "disposition",
                    "events",
                    "filtered_count",
                    "gaps",
                    "interface",
                    "policy_digest",
                    "producer_id",
                    "query_digest",
                    "query_id",
                    "ranked_count",
                    "reason_counts",
                    "receipt_id",
                    "redaction_notes",
                    "rejected_count",
                    "rejected_reason_summary",
                    "result_digest",
                    "retrieval_rank_used_for_authority",
                    "schema_version",
                    "selected_cids",
                    "selected_count",
                }
            ),
            "proof query audit receipt",
        )
        if payload.get("retrieval_rank_used_for_authority"):
            raise ProofQueryAuditError(
                "audit receipts must not claim ranking establishes authority"
            )
        return cls(
            receipt_id=payload.get("receipt_id", ""),
            query_id=payload.get("query_id", ""),
            disposition=payload.get("disposition", SelectionDisposition.EMPTY),
            considered_count=int(payload.get("considered_count", 0)),
            filtered_count=int(payload.get("filtered_count", 0)),
            ranked_count=int(payload.get("ranked_count", 0)),
            selected_count=int(payload.get("selected_count", 0)),
            rejected_count=int(payload.get("rejected_count", 0)),
            reason_counts=dict(payload.get("reason_counts", {}) or {}),
            budgets=dict(payload.get("budgets", {}) or {}),
            gaps=tuple(payload.get("gaps", ()) or ()),
            selected_cids=tuple(payload.get("selected_cids", ()) or ()),
            rejected_reason_summary=tuple(
                payload.get("rejected_reason_summary", ()) or ()
            ),
            events=tuple(
                AuditTraceEvent.from_dict(item)
                for item in (payload.get("events") or ())
            ),
            redaction_notes=tuple(
                RedactionNote.from_dict(item)
                for item in (payload.get("redaction_notes") or ())
            ),
            retrieval_rank_used_for_authority=False,
            query_digest=payload.get("query_digest", ""),
            result_digest=payload.get("result_digest", ""),
            policy_digest=payload.get("policy_digest", ""),
            applicability_interface=payload.get(
                "applicability_interface", PROOF_APPLICABILITY_FILTER_INTERFACE
            ),
            producer_id=payload.get("producer_id", ""),
            content_digest=payload.get("content_digest", ""),
            content_cid=payload.get("content_cid", ""),
            schema_version=payload.get(
                "schema_version", PROOF_QUERY_AUDIT_RECEIPT_SCHEMA_VERSION
            ),
            interface=payload.get(
                "interface", PROOF_QUERY_AUDIT_RECEIPT_INTERFACE
            ),
        )


def _build_events(
    result: ProofApplicabilityResult,
    *,
    max_events: int = MAX_AUDIT_EVENTS,
) -> tuple[AuditTraceEvent, ...]:
    """Build a bounded redacted event stream from an applicability result."""

    events: list[AuditTraceEvent] = []
    ordinal = 0

    def _push(
        kind: AuditEventKind,
        *,
        envelope_cid: str = "",
        reasons: Sequence[str] = (),
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        nonlocal ordinal
        if len(events) >= max_events:
            return
        events.append(
            AuditTraceEvent(
                ordinal=ordinal,
                kind=kind,
                envelope_cid=envelope_cid,
                reasons=tuple(reasons),
                attributes=dict(attributes or {}),
            )
        )
        ordinal += 1

    _push(
        AuditEventKind.QUERY_START,
        attributes={
            "query_id": result.query_id,
            "query_digest": result.query_digest,
        },
    )
    _push(
        AuditEventKind.BUDGET_APPLIED,
        attributes=dict(result.budgets),
    )

    for assessment in result.assessments:
        assert isinstance(assessment, HardFilterAssessment)
        _push(
            AuditEventKind.CANDIDATE_CONSIDERED,
            envelope_cid=assessment.envelope_cid,
        )
        if assessment.disposition is FilterDisposition.ADMITTED:
            _push(
                AuditEventKind.CANDIDATE_ADMITTED,
                envelope_cid=assessment.envelope_cid,
                attributes={
                    "filter_dimensions": list(assessment.filter_dimensions),
                },
            )
        elif assessment.disposition is FilterDisposition.FILTERED:
            _push(
                AuditEventKind.CANDIDATE_FILTERED,
                envelope_cid=assessment.envelope_cid,
                reasons=assessment.reasons,
                attributes={
                    "filter_dimensions": list(assessment.filter_dimensions),
                },
            )
        else:
            _push(
                AuditEventKind.CANDIDATE_REJECTED,
                envelope_cid=assessment.envelope_cid,
                reasons=assessment.reasons,
                attributes={
                    "filter_dimensions": list(assessment.filter_dimensions),
                },
            )

    for candidate in result.ranked:
        assert isinstance(candidate, RankedCandidate)
        _push(
            AuditEventKind.CANDIDATE_RANKED,
            envelope_cid=candidate.envelope_cid,
            attributes={
                "rank_index": candidate.rank_index,
                "rank_score": candidate.rank_score,
                # score_features are advisory numerics only
                "score_features": dict(candidate.score_features),
            },
        )

    for cid in result.selected_cids:
        _push(AuditEventKind.CANDIDATE_SELECTED, envelope_cid=cid)

    for gap in result.gaps:
        _push(AuditEventKind.GAP_RECORDED, reasons=(gap,))

    _push(
        AuditEventKind.QUERY_COMPLETE,
        attributes={
            "disposition": result.disposition.value,
            "considered_count": result.considered_count,
            "filtered_count": result.filtered_count,
            "ranked_count": result.ranked_count,
            "selected_count": result.selected_count,
            "rejected_count": result.rejected_count,
            "retrieval_rank_used_for_authority": False,
        },
    )
    return tuple(events)


def build_proof_query_audit_receipt(
    result: ProofApplicabilityResult,
    *,
    query: ProofApplicabilityQuery | None = None,
    receipt_id: str = "",
    producer_id: str = "proof-query-audit",
    extra_diagnostics: Mapping[str, Any] | None = None,
    max_events: int = MAX_AUDIT_EVENTS,
) -> ProofQueryAuditReceipt:
    """Build a redacted :class:`ProofQueryAuditReceipt` from a filter result.

    *extra_diagnostics* is redacted before inclusion.  Raw prompts, arguments,
    secrets, witnesses, and private formulas never appear in the clear.
    """

    if not isinstance(result, ProofApplicabilityResult):
        raise ProofQueryAuditError(
            "result must be a ProofApplicabilityResult"
        )
    if result.retrieval_rank_used_for_authority:
        raise ProofQueryAuditError(
            "cannot audit a result that claims ranking authority"
        )
    if result.ranking_establishes_applicability:
        raise ProofQueryAuditError(
            "cannot audit a result that claims ranking establishes applicability"
        )

    notes: list[RedactionNote] = []
    if extra_diagnostics:
        redact_value(
            dict(extra_diagnostics),
            path="extra_diagnostics",
            notes=notes,
        )

    events = _build_events(result, max_events=max_events)
    # Re-redact event attributes defensively and collect notes.
    safe_events: list[AuditTraceEvent] = []
    for event in events:
        redacted_attrs = redact_value(
            dict(event.attributes),
            path=f"events[{event.ordinal}].attributes",
            notes=notes,
        )
        safe_events.append(
            AuditTraceEvent(
                ordinal=event.ordinal,
                kind=event.kind,
                envelope_cid=event.envelope_cid,
                reasons=event.reasons,
                attributes=redacted_attrs if isinstance(redacted_attrs, dict) else {},
            )
        )

    if not receipt_id:
        seed = {
            "query_id": result.query_id,
            "query_digest": result.query_digest,
            "result_digest": result.result_digest(),
            "selected_cids": list(result.selected_cids),
        }
        receipt_id = "audit:" + _sha256_hex_prefix(
            _canonical_bytes(seed), 24
        )

    query_digest = result.query_digest
    if query is not None:
        if not isinstance(query, ProofApplicabilityQuery):
            raise ProofQueryAuditError(
                "query must be a ProofApplicabilityQuery when provided"
            )
        query_digest = query.query_digest()

    # Cap redaction notes deterministically.
    notes_sorted = sorted(notes, key=lambda item: item.path)[:MAX_REDACTION_NOTES]

    return ProofQueryAuditReceipt(
        receipt_id=receipt_id,
        query_id=result.query_id,
        disposition=result.disposition,
        considered_count=result.considered_count,
        filtered_count=result.filtered_count,
        ranked_count=result.ranked_count,
        selected_count=result.selected_count,
        rejected_count=result.rejected_count,
        reason_counts=dict(result.reason_counts),
        budgets=dict(result.budgets),
        gaps=result.gaps,
        selected_cids=result.selected_cids,
        rejected_reason_summary=tuple(sorted(result.reason_counts.keys())),
        events=tuple(safe_events),
        redaction_notes=tuple(notes_sorted),
        retrieval_rank_used_for_authority=False,
        query_digest=query_digest,
        result_digest=result.result_digest(),
        policy_digest=result.policy_digest,
        producer_id=producer_id,
    )


def audit_applicability_query(
    envelopes: Sequence[Any],
    query: ProofApplicabilityQuery,
    *,
    trust_policy: Any = None,
    revocation_snapshot: Any = None,
    revoked_target_cids: Sequence[str] = (),
    advisory_scores: Mapping[str, float] | None = None,
    extra_diagnostics: Mapping[str, Any] | None = None,
    producer_id: str = "proof-query-audit",
) -> tuple[ProofApplicabilityResult, ProofQueryAuditReceipt]:
    """Run hard-filtered selection and emit a redacted audit receipt."""

    from .applicability import ProofApplicabilityFilter

    result = ProofApplicabilityFilter(
        trust_policy=trust_policy,
        revocation_snapshot=revocation_snapshot,
        revoked_target_cids=tuple(revoked_target_cids),
    ).select(envelopes, query, advisory_scores=advisory_scores)
    receipt = build_proof_query_audit_receipt(
        result,
        query=query,
        producer_id=producer_id,
        extra_diagnostics=extra_diagnostics,
    )
    return result, receipt


__all__ = [
    "AUDIT_TRACE_EVENT_SCHEMA_VERSION",
    "MAX_AUDIT_EVENTS",
    "PROOF_QUERY_AUDIT_RECEIPT_INTERFACE",
    "PROOF_QUERY_AUDIT_RECEIPT_SCHEMA_VERSION",
    "REDACTION_NOTE_SCHEMA_VERSION",
    "AuditEventKind",
    "AuditTraceEvent",
    "ProofQueryAuditError",
    "ProofQueryAuditReceipt",
    "RedactionNote",
    "audit_applicability_query",
    "build_proof_query_audit_receipt",
    "is_redaction_placeholder",
    "redact_value",
    "redaction_placeholder",
]
