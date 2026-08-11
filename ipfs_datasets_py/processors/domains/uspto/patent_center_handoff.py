"""Human Patent Center handoff state machine (PATLAW-154 / PATLAW-G172).

Records the filing-package lifecycle after package compilation (PATLAW-153):

    draft → validated → human-approved → exported
          → user-submitted → receipt-verified

Design invariants
-----------------
* Invalid transitions fail closed.
* The system **cannot advance past** ``exported`` without an **external
  human assertion** that a natural person submitted outside this process.
* The system **cannot advance to** ``receipt-verified`` without **verified
  official artifacts** (acknowledgement and/or payment receipts and optional
  USPTO-converted files) bound to the approved/submitted package digest.
* Emits **content-free** instructions for Patent Center **training** and
  **live** review. Never signs, pays, files, automates a browser, stores
  credentials/sessions, or fabricates training/live receipts.
* Signatures, Rule 11.18 certification, fees, and Submit remain natural-
  person actions in Patent Center outside this processor.

Conflict policy (PATLAW-154): own the handoff state machine, tests, and
runbook only.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

HANDOFF_SCHEMA_VERSION: Final = "uspto.patent-center-handoff.v1"
HANDOFF_INTERFACE: Final = "PatentCenterHandoff@1"
FILING_STATE_MACHINE_INTERFACE: Final = "FilingStateMachine@1"
HANDOFF_RULESET_VERSION: Final = "patent-center-handoff-rules@1"
PARSER_VERSION: Final = "patlaw-154.patent-center-handoff.v1"

OUTPUT_KIND_HANDOFF_RECORD: Final = "patent_center_handoff_record"
OUTPUT_KIND_HANDOFF_INSTRUCTIONS: Final = "patent_center_handoff_instructions"
OUTPUT_KIND_HUMAN_APPROVAL: Final = "handoff_human_approval"
OUTPUT_KIND_EXPORT_BUNDLE: Final = "handoff_export_bundle"
OUTPUT_KIND_USER_SUBMISSION: Final = "handoff_user_submission_assertion"
OUTPUT_KIND_OFFICIAL_ARTIFACT: Final = "handoff_official_artifact"

HANDOFF_DISCLAIMER: Final = (
    "This Patent Center handoff is decision support for a natural person. "
    "It never signs, pays, files, certifies under 37 C.F.R. 11.18, controls a "
    "browser, stores credentials or sessions, or fabricates receipts. "
    "Training and live Patent Center use remain interactive human actions. "
    "Receipt-verified status requires user-imported official artifacts."
)

# Public Patent Center entry points as plain text labels only (never opened).
PATENT_CENTER_LIVE_URL_LABEL: Final = "https://patentcenter.uspto.gov"
PATENT_CENTER_TRAINING_URL_LABEL: Final = (
    "https://patentcenter-training.uspto.gov"
)

DEFAULT_MAX_ARTIFACTS: Final = 64
DEFAULT_MAX_INSTRUCTIONS: Final = 64
DEFAULT_MAX_REASON_CODES: Final = 128
DEFAULT_MAX_TRANSITION_LOG: Final = 64
DEFAULT_MAX_WARNINGS: Final = 256

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)

# Capabilities / interfaces this module must never expose successfully.
FORBIDDEN_HANDOFF_INTERFACES: Final[frozenset[str]] = frozenset(
    {
        "network",
        "network_login",
        "network_request",
        "http_client",
        "browser",
        "browser_control",
        "automate_browser",
        "selenium",
        "playwright",
        "puppeteer",
        "session",
        "session_cookie_replay",
        "session_store",
        "read_browser_profile_or_session_storage",
        "store_credentials_or_cookies",
        "payment",
        "payment_interface",
        "pay",
        "pay_fee",
        "charge_card",
        "sign",
        "apply_signature",
        "file",
        "file_application",
        "submit",
        "perform_final_submission",
        "automate_patent_center",
        "scrape_authenticated_patent_center",
        "automate_mfa",
        "bypass_mfa",
        "fabricate_acknowledgement",
        "fabricate_payment_receipt",
        "fabricate_receipt",
        "fabricate_training_receipt",
        "fabricate_live_receipt",
        "claim_filing_occurred",
        "mark_submitted_without_human",
    }
)

# Method names that must never appear on the handoff surface.
FORBIDDEN_METHOD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "login",
        "network_login",
        "open_browser",
        "control_browser",
        "automate_browser",
        "launch_selenium",
        "launch_playwright",
        "pay",
        "pay_fee",
        "charge_payment",
        "submit_to_uspto",
        "file_application",
        "perform_final_submission",
        "scrape_patent_center",
        "store_session",
        "load_session_cookies",
        "fabricate_acknowledgement",
        "fabricate_payment_receipt",
        "fabricate_receipt",
    }
)

# Third-party modules that must not be imported by this handoff module.
FORBIDDEN_IMPORT_MODULES: Final[frozenset[str]] = frozenset(
    {
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "selenium",
        "playwright",
        "pyppeteer",
        "splinter",
        "mechanize",
    }
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class HandoffState(str, Enum):
    """Lifecycle states for the human Patent Center handoff.

    Values use hyphenated labels matching the backlog acceptance language.
    """

    DRAFT = "draft"
    VALIDATED = "validated"
    HUMAN_APPROVED = "human-approved"
    EXPORTED = "exported"
    USER_SUBMITTED = "user-submitted"
    RECEIPT_VERIFIED = "receipt-verified"
    INVALIDATED = "invalidated"


class HandoffMode(str, Enum):
    """Patent Center operating mode for content-free instructions."""

    TRAINING = "training"
    LIVE = "live"


class OfficialArtifactKind(str, Enum):
    """Kinds of official USPTO artifacts admitted after human submission."""

    ACKNOWLEDGEMENT = "acknowledgement"
    PAYMENT_RECEIPT = "payment_receipt"
    USPTO_CONVERTED_PDF = "uspto_converted_pdf"
    OTHER_OFFICIAL = "other_official"


class ArtifactVerificationStatus(str, Enum):
    """Whether an imported official artifact has been verified."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"
    CONFLICTING = "conflicting"


class HandoffReasonCode(str, Enum):
    HANDOFF_STARTED = "handoff_started"
    PACKAGE_BOUND = "package_bound"
    STATE_VALIDATED = "state_validated"
    HUMAN_APPROVED = "human_approved"
    EXPORTED = "exported"
    INSTRUCTIONS_EMITTED = "instructions_emitted"
    USER_SUBMISSION_RECORDED = "user_submission_recorded"
    OFFICIAL_ARTIFACT_BOUND = "official_artifact_bound"
    RECEIPT_VERIFIED = "receipt_verified"
    INVALID_TRANSITION = "invalid_transition"
    EXTERNAL_HUMAN_ASSERTION_REQUIRED = "external_human_assertion_required"
    VERIFIED_ARTIFACTS_REQUIRED = "verified_artifacts_required"
    DIGEST_MISMATCH = "digest_mismatch"
    HANDOFF_INVALIDATED = "handoff_invalidated"
    EXTERNAL_FILING_ONLY = "external_filing_only"
    NEVER_AUTOMATED = "never_automated"
    CONTENT_FREE_INSTRUCTIONS = "content_free_instructions"
    NOT_LEGAL_ADVICE = "not_legal_advice"
    NO_NETWORK_BROWSER_SESSION_PAYMENT = "no_network_browser_session_payment"


# Ordered happy-path states (invalidated is terminal side path).
_FORWARD_ORDER: Final[tuple[HandoffState, ...]] = (
    HandoffState.DRAFT,
    HandoffState.VALIDATED,
    HandoffState.HUMAN_APPROVED,
    HandoffState.EXPORTED,
    HandoffState.USER_SUBMITTED,
    HandoffState.RECEIPT_VERIFIED,
)

# Explicit allowed edges. No skips. Invalidated only via invalidate().
ALLOWED_TRANSITIONS: Final[Mapping[HandoffState, frozenset[HandoffState]]] = (
    MappingProxyType(
        {
            HandoffState.DRAFT: frozenset({HandoffState.VALIDATED}),
            HandoffState.VALIDATED: frozenset({HandoffState.HUMAN_APPROVED}),
            HandoffState.HUMAN_APPROVED: frozenset({HandoffState.EXPORTED}),
            HandoffState.EXPORTED: frozenset({HandoffState.USER_SUBMITTED}),
            HandoffState.USER_SUBMITTED: frozenset(
                {HandoffState.RECEIPT_VERIFIED}
            ),
            HandoffState.RECEIPT_VERIFIED: frozenset(),
            HandoffState.INVALIDATED: frozenset(),
        }
    )
)

# States at or after which an external human assertion is mandatory to leave.
_REQUIRES_HUMAN_ASSERTION_TO_LEAVE: Final[frozenset[HandoffState]] = frozenset(
    {HandoffState.EXPORTED}
)

# States that require verified official artifacts to enter.
_REQUIRES_VERIFIED_ARTIFACTS_TO_ENTER: Final[frozenset[HandoffState]] = (
    frozenset({HandoffState.RECEIPT_VERIFIED})
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HandoffError(ValueError):
    """Base error for Patent Center handoff failures."""

    def __init__(self, message: str, *, code: str = "handoff_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


class InvalidTransitionError(HandoffError):
    """Raised when a state transition is not on the allowed edge set."""

    def __init__(
        self,
        message: str,
        *,
        from_state: str | None = None,
        to_state: str | None = None,
    ) -> None:
        super().__init__(message, code="invalid_transition")
        self.from_state = from_state
        self.to_state = to_state


class ExternalHumanAssertionRequiredError(HandoffError):
    """Raised when advancing past exported without a human submission claim."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="external_human_assertion_required")


class VerifiedArtifactsRequiredError(HandoffError):
    """Raised when advancing to receipt-verified without verified artifacts."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="verified_artifacts_required")


class ForbiddenHandoffInterfaceError(HandoffError):
    """Raised when a network/browser/session/payment interface is requested."""

    def __init__(self, interface: str, message: str | None = None) -> None:
        iface = str(interface)
        super().__init__(
            message
            or (
                f"handoff forbids interface {iface!r}: no network, browser, "
                "session, payment, signature, or automated filing surface exists"
            ),
            code="forbidden_handoff_interface",
        )
        self.interface = iface


class HandoffDigestMismatchError(HandoffError):
    """Raised when an approval/submission/artifact digest does not bind."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="digest_mismatch")


class HandoffInvalidatedError(HandoffError):
    """Raised when operating on an invalidated handoff."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="handoff_invalidated")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


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
    return _require_str(value, field, max_len=max_len)


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} has invalid identifier shape")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field)


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    lowered = text.lower()
    if not _SHA256_RE.match(lowered):
        raise ValueError(f"{field} must be a 64-char lowercase hex sha256")
    return lowered


def _optional_sha256(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _sha256_hex_field(value, field)


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp")
    return text


def _optional_iso_utc(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _iso_utc(value, field)


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value)
        except ValueError as exc:
            raise ValueError(f"invalid classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence of str")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise TypeError(f"{field}[{i}] must be str")
        text = item.strip()
        if not text:
            raise ValueError(f"{field}[{i}] must be non-empty")
        if len(text) > 512:
            raise ValueError(f"{field}[{i}] exceeds max length 512")
        out.append(text)
    return tuple(out)


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 64
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise TypeError(f"{field} keys and values must be str")
        ks, vs = k.strip(), v.strip()
        if not ks:
            raise ValueError(f"{field} key must be non-empty")
        out[ks] = vs
    return MappingProxyType(out)


def _default_id_factory() -> str:
    return uuid.uuid4().hex[:12]


def normalize_interface_name(name: str) -> str:
    return _require_str(name, "interface", max_len=128).lower().replace(" ", "_")


def assert_interface_allowed(interface: str) -> None:
    """Fail closed if *interface* is a forbidden network/browser/session/payment surface."""
    key = normalize_interface_name(interface)
    if key in FORBIDDEN_HANDOFF_INTERFACES:
        raise ForbiddenHandoffInterfaceError(key)
    for token in (
        "network",
        "browser",
        "selenium",
        "playwright",
        "session_cookie",
        "payment",
        "pay_fee",
        "fabricate_receipt",
        "automate_patent_center",
        "scrape_authenticated",
        "apply_signature",
        "perform_final_submission",
    ):
        if token in key:
            raise ForbiddenHandoffInterfaceError(key)


def is_forbidden_interface(interface: str) -> bool:
    try:
        assert_interface_allowed(interface)
    except ForbiddenHandoffInterfaceError:
        return True
    except (TypeError, ValueError):
        return True
    return False


def is_transition_allowed(
    from_state: HandoffState | str, to_state: HandoffState | str
) -> bool:
    src = _coerce_enum(HandoffState, from_state, "from_state")
    dst = _coerce_enum(HandoffState, to_state, "to_state")
    allowed = ALLOWED_TRANSITIONS.get(src, frozenset())  # type: ignore[arg-type]
    return dst in allowed


def assert_transition_allowed(
    from_state: HandoffState | str, to_state: HandoffState | str
) -> None:
    src = _coerce_enum(HandoffState, from_state, "from_state")
    dst = _coerce_enum(HandoffState, to_state, "to_state")
    if not is_transition_allowed(src, dst):
        raise InvalidTransitionError(
            f"invalid handoff transition {src.value!r} → {dst.value!r}",
            from_state=src.value,
            to_state=dst.value,
        )


# ---------------------------------------------------------------------------
# Component records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransitionEvent:
    """Immutable log entry for one successful (or attempted) transition."""

    from_state: HandoffState | str
    to_state: HandoffState | str
    at_utc: str
    actor: str
    reason_code: str
    note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "from_state",
            _coerce_enum(HandoffState, self.from_state, "from_state"),
        )
        object.__setattr__(
            self,
            "to_state",
            _coerce_enum(HandoffState, self.to_state, "to_state"),
        )
        object.__setattr__(self, "at_utc", _iso_utc(self.at_utc, "at_utc"))
        object.__setattr__(
            self, "actor", _require_str(self.actor, "actor", max_len=256)
        )
        object.__setattr__(
            self,
            "reason_code",
            _require_str(self.reason_code, "reason_code", max_len=128),
        )
        object.__setattr__(
            self, "note", _optional_str(self.note, "note", max_len=512)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "at_utc": self.at_utc,
            "from_state": self.from_state.value
            if isinstance(self.from_state, HandoffState)
            else str(self.from_state),
            "note": self.note,
            "reason_code": self.reason_code,
            "to_state": self.to_state.value
            if isinstance(self.to_state, HandoffState)
            else str(self.to_state),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TransitionEvent":
        if not isinstance(value, Mapping):
            raise TypeError("TransitionEvent must be a mapping")
        return cls(
            from_state=value.get("from_state", HandoffState.DRAFT.value),
            to_state=value.get("to_state", HandoffState.DRAFT.value),
            at_utc=value.get("at_utc", ""),
            actor=value.get("actor", ""),
            reason_code=value.get("reason_code", ""),
            note=value.get("note"),
        )


@dataclass(frozen=True, slots=True)
class HumanApprovalRecord:
    """Named human approval of an exact package digest (pre-export)."""

    approval_id: str
    package_digest: str
    approver_name: str
    approved_at_utc: str
    statement: str
    role: str = "inventor_or_practitioner"
    output_kind: str = OUTPUT_KIND_HUMAN_APPROVAL
    content_digest: str = ""
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "approval_id", _identifier(self.approval_id, "approval_id")
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "approver_name",
            _require_str(self.approver_name, "approver_name", max_len=256),
        )
        object.__setattr__(
            self,
            "approved_at_utc",
            _iso_utc(self.approved_at_utc, "approved_at_utc"),
        )
        object.__setattr__(
            self,
            "statement",
            _require_str(self.statement, "statement", max_len=4096),
        )
        object.__setattr__(
            self, "role", _require_str(self.role, "role", max_len=128)
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_HUMAN_APPROVAL:
            raise HandoffError(
                f"output_kind must be {OUTPUT_KIND_HUMAN_APPROVAL!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise HandoffError(
                    "content_digest does not match approval material payload",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    def material_payload(self) -> dict[str, Any]:
        return {
            "approved_at_utc": self.approved_at_utc,
            "approver_name": self.approver_name,
            "labels": dict(self.labels),
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "role": self.role,
            "statement": self.statement,
        }

    def binds_package_digest(self, package_digest: str) -> bool:
        return self.package_digest == _sha256_hex_field(
            package_digest, "package_digest"
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["approval_id"] = self.approval_id
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanApprovalRecord":
        if not isinstance(value, Mapping):
            raise TypeError("HumanApprovalRecord must be a mapping")
        return cls(
            approval_id=value.get("approval_id", ""),
            package_digest=value.get("package_digest", ""),
            approver_name=value.get("approver_name", ""),
            approved_at_utc=value.get("approved_at_utc", ""),
            statement=value.get("statement", ""),
            role=value.get("role", "inventor_or_practitioner"),
            output_kind=value.get("output_kind", OUTPUT_KIND_HUMAN_APPROVAL),
            content_digest=value.get("content_digest", ""),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class InstructionStep:
    """One content-free operator step (no document bodies or secrets)."""

    step_id: str
    ordinal: int
    summary: str
    actor: str = "natural_person"
    requires_external_tool: bool = True
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _identifier(self.step_id, "step_id"))
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int):
            raise TypeError("ordinal must be int")
        if self.ordinal < 1:
            raise ValueError("ordinal must be >= 1")
        object.__setattr__(
            self, "summary", _require_str(self.summary, "summary", max_len=1024)
        )
        object.__setattr__(
            self, "actor", _require_str(self.actor, "actor", max_len=128)
        )
        if not isinstance(self.requires_external_tool, bool):
            raise TypeError("requires_external_tool must be bool")
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        # Content-free guard: reject obvious secret / body markers.
        # Ban concrete secret material patterns, not educational vocabulary
        # (e.g. the word "password" in "do not enter passwords here").
        lowered = self.summary.lower()
        for banned in (
            "bearer ey",
            "api_key=",
            "apikey=",
            "cookie=",
            "set-cookie:",
            "private key-----",
            "-----begin",
            "-----end private",
            "authorization: bearer ",
        ):
            if banned in lowered:
                raise HandoffError(
                    "instruction summary must remain content-free",
                    code="content_free_violation",
                )
        # Reject long base64-looking blobs that look like pasted secrets.
        if re.search(r"(?<![a-z0-9])[a-z0-9+/]{80,}={0,2}(?![a-z0-9])", lowered):
            raise HandoffError(
                "instruction summary must remain content-free",
                code="content_free_violation",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "labels": dict(self.labels),
            "ordinal": self.ordinal,
            "requires_external_tool": self.requires_external_tool,
            "step_id": self.step_id,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InstructionStep":
        if not isinstance(value, Mapping):
            raise TypeError("InstructionStep must be a mapping")
        return cls(
            step_id=value.get("step_id", ""),
            ordinal=int(value.get("ordinal", 0) or 0),
            summary=value.get("summary", ""),
            actor=value.get("actor", "natural_person"),
            requires_external_tool=bool(
                value.get("requires_external_tool", True)
            ),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class HandoffInstructions:
    """Content-free training or live Patent Center review instructions."""

    instructions_id: str
    mode: HandoffMode | str
    package_digest: str
    patent_center_url_label: str
    steps: tuple[InstructionStep, ...]
    disclaimer: str = HANDOFF_DISCLAIMER
    output_kind: str = OUTPUT_KIND_HANDOFF_INSTRUCTIONS
    content_digest: str = ""
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instructions_id",
            _identifier(self.instructions_id, "instructions_id"),
        )
        object.__setattr__(
            self, "mode", _coerce_enum(HandoffMode, self.mode, "mode")
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "patent_center_url_label",
            _require_str(
                self.patent_center_url_label,
                "patent_center_url_label",
                max_len=512,
            ),
        )
        if not isinstance(self.steps, tuple):
            object.__setattr__(self, "steps", tuple(self.steps or ()))
        if len(self.steps) > DEFAULT_MAX_INSTRUCTIONS:
            raise HandoffError(
                f"steps exceed max {DEFAULT_MAX_INSTRUCTIONS}",
                code="too_many_steps",
            )
        cleaned: list[InstructionStep] = []
        for i, step in enumerate(self.steps):
            if isinstance(step, InstructionStep):
                cleaned.append(step)
            elif isinstance(step, Mapping):
                cleaned.append(InstructionStep.from_dict(step))
            else:
                raise TypeError(f"steps[{i}] must be InstructionStep or mapping")
        object.__setattr__(self, "steps", tuple(cleaned))
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=2048),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_HANDOFF_INSTRUCTIONS:
            raise HandoffError(
                f"output_kind must be {OUTPUT_KIND_HANDOFF_INSTRUCTIONS!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise HandoffError(
                    "content_digest does not match instructions material",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    def material_payload(self) -> dict[str, Any]:
        return {
            "disclaimer": self.disclaimer,
            "labels": dict(self.labels),
            "mode": self.mode.value
            if isinstance(self.mode, HandoffMode)
            else str(self.mode),
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "patent_center_url_label": self.patent_center_url_label,
            "steps": [s.to_dict() for s in self.steps],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["content_digest"] = self.content_digest
        payload["instructions_id"] = self.instructions_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HandoffInstructions":
        if not isinstance(value, Mapping):
            raise TypeError("HandoffInstructions must be a mapping")
        return cls(
            instructions_id=value.get("instructions_id", ""),
            mode=value.get("mode", HandoffMode.LIVE.value),
            package_digest=value.get("package_digest", ""),
            patent_center_url_label=value.get("patent_center_url_label", ""),
            steps=tuple(value.get("steps") or ()),
            disclaimer=value.get("disclaimer", HANDOFF_DISCLAIMER),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_HANDOFF_INSTRUCTIONS
            ),
            content_digest=value.get("content_digest", ""),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ExportBundle:
    """Export descriptor: files + digest for external Patent Center use."""

    export_id: str
    package_digest: str
    exported_at_utc: str
    exported_by: str
    export_root_label: str
    file_digests: Mapping[str, str] = MappingProxyType({})
    training_instructions_id: str | None = None
    live_instructions_id: str | None = None
    output_kind: str = OUTPUT_KIND_EXPORT_BUNDLE
    content_digest: str = ""
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "export_id", _identifier(self.export_id, "export_id")
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "exported_at_utc",
            _iso_utc(self.exported_at_utc, "exported_at_utc"),
        )
        object.__setattr__(
            self,
            "exported_by",
            _require_str(self.exported_by, "exported_by", max_len=256),
        )
        object.__setattr__(
            self,
            "export_root_label",
            _require_str(
                self.export_root_label, "export_root_label", max_len=1024
            ),
        )
        # file_digests: filename → sha256 (content-address only, no bodies)
        if self.file_digests is None:
            object.__setattr__(self, "file_digests", MappingProxyType({}))
        elif not isinstance(self.file_digests, Mapping):
            raise TypeError("file_digests must be a mapping")
        else:
            cleaned: dict[str, str] = {}
            if len(self.file_digests) > DEFAULT_MAX_ARTIFACTS:
                raise HandoffError(
                    "file_digests exceeds max entries",
                    code="too_many_file_digests",
                )
            for name, digest in self.file_digests.items():
                ns = _require_str(name, "file_digests key", max_len=512)
                cleaned[ns] = _sha256_hex_field(digest, f"file_digests[{ns}]")
            object.__setattr__(self, "file_digests", MappingProxyType(cleaned))
        object.__setattr__(
            self,
            "training_instructions_id",
            _optional_identifier(
                self.training_instructions_id, "training_instructions_id"
            ),
        )
        object.__setattr__(
            self,
            "live_instructions_id",
            _optional_identifier(
                self.live_instructions_id, "live_instructions_id"
            ),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_EXPORT_BUNDLE:
            raise HandoffError(
                f"output_kind must be {OUTPUT_KIND_EXPORT_BUNDLE!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise HandoffError(
                    "content_digest does not match export material",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    def material_payload(self) -> dict[str, Any]:
        return {
            "export_root_label": self.export_root_label,
            "exported_at_utc": self.exported_at_utc,
            "exported_by": self.exported_by,
            "file_digests": dict(self.file_digests),
            "labels": dict(self.labels),
            "live_instructions_id": self.live_instructions_id,
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "training_instructions_id": self.training_instructions_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["content_digest"] = self.content_digest
        payload["export_id"] = self.export_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExportBundle":
        if not isinstance(value, Mapping):
            raise TypeError("ExportBundle must be a mapping")
        return cls(
            export_id=value.get("export_id", ""),
            package_digest=value.get("package_digest", ""),
            exported_at_utc=value.get("exported_at_utc", ""),
            exported_by=value.get("exported_by", ""),
            export_root_label=value.get("export_root_label", ""),
            file_digests=value.get("file_digests") or {},
            training_instructions_id=value.get("training_instructions_id"),
            live_instructions_id=value.get("live_instructions_id"),
            output_kind=value.get("output_kind", OUTPUT_KIND_EXPORT_BUNDLE),
            content_digest=value.get("content_digest", ""),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class UserSubmissionAssertion:
    """External human assertion that Patent Center submission occurred.

    Required to leave ``exported``. The system never invents this record.
    """

    assertion_id: str
    package_digest: str
    submitted_digest: str
    asserted_by: str
    asserted_at_utc: str
    statement: str
    mode: HandoffMode | str = HandoffMode.LIVE
    confirmation_number: str | None = None
    external_human_action: bool = True
    output_kind: str = OUTPUT_KIND_USER_SUBMISSION
    content_digest: str = ""
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assertion_id",
            _identifier(self.assertion_id, "assertion_id"),
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "submitted_digest",
            _sha256_hex_field(self.submitted_digest, "submitted_digest"),
        )
        object.__setattr__(
            self,
            "asserted_by",
            _require_str(self.asserted_by, "asserted_by", max_len=256),
        )
        object.__setattr__(
            self,
            "asserted_at_utc",
            _iso_utc(self.asserted_at_utc, "asserted_at_utc"),
        )
        object.__setattr__(
            self,
            "statement",
            _require_str(self.statement, "statement", max_len=4096),
        )
        object.__setattr__(
            self, "mode", _coerce_enum(HandoffMode, self.mode, "mode")
        )
        object.__setattr__(
            self,
            "confirmation_number",
            _optional_str(
                self.confirmation_number, "confirmation_number", max_len=128
            ),
        )
        if not isinstance(self.external_human_action, bool):
            raise TypeError("external_human_action must be bool")
        if not self.external_human_action:
            raise ExternalHumanAssertionRequiredError(
                "user submission requires external_human_action=True; "
                "the system cannot invent a submission"
            )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_USER_SUBMISSION:
            raise HandoffError(
                f"output_kind must be {OUTPUT_KIND_USER_SUBMISSION!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise HandoffError(
                    "content_digest does not match submission assertion",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    def material_payload(self) -> dict[str, Any]:
        return {
            "asserted_at_utc": self.asserted_at_utc,
            "asserted_by": self.asserted_by,
            "confirmation_number": self.confirmation_number,
            "external_human_action": self.external_human_action,
            "labels": dict(self.labels),
            "mode": self.mode.value
            if isinstance(self.mode, HandoffMode)
            else str(self.mode),
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "statement": self.statement,
            "submitted_digest": self.submitted_digest,
        }

    def binds_package_digest(self, package_digest: str) -> bool:
        return self.package_digest == _sha256_hex_field(
            package_digest, "package_digest"
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["assertion_id"] = self.assertion_id
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UserSubmissionAssertion":
        if not isinstance(value, Mapping):
            raise TypeError("UserSubmissionAssertion must be a mapping")
        return cls(
            assertion_id=value.get("assertion_id", ""),
            package_digest=value.get("package_digest", ""),
            submitted_digest=value.get("submitted_digest", ""),
            asserted_by=value.get("asserted_by", ""),
            asserted_at_utc=value.get("asserted_at_utc", ""),
            statement=value.get("statement", ""),
            mode=value.get("mode", HandoffMode.LIVE.value),
            confirmation_number=value.get("confirmation_number"),
            external_human_action=bool(
                value.get("external_human_action", True)
            ),
            output_kind=value.get("output_kind", OUTPUT_KIND_USER_SUBMISSION),
            content_digest=value.get("content_digest", ""),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class OfficialArtifact:
    """User-imported official USPTO artifact (never fabricated)."""

    artifact_id: str
    kind: OfficialArtifactKind | str
    content_digest: str
    package_digest: str
    verification_status: ArtifactVerificationStatus | str
    imported_at_utc: str
    imported_by: str
    source_receipt_id: str | None = None
    filename: str | None = None
    fabricated: bool = False
    output_kind: str = OUTPUT_KIND_OFFICIAL_ARTIFACT
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "kind",
            _coerce_enum(OfficialArtifactKind, self.kind, "kind"),
        )
        object.__setattr__(
            self,
            "content_digest",
            _sha256_hex_field(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "verification_status",
            _coerce_enum(
                ArtifactVerificationStatus,
                self.verification_status,
                "verification_status",
            ),
        )
        object.__setattr__(
            self,
            "imported_at_utc",
            _iso_utc(self.imported_at_utc, "imported_at_utc"),
        )
        object.__setattr__(
            self,
            "imported_by",
            _require_str(self.imported_by, "imported_by", max_len=256),
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_identifier(
                self.source_receipt_id, "source_receipt_id"
            ),
        )
        object.__setattr__(
            self,
            "filename",
            _optional_str(self.filename, "filename", max_len=512),
        )
        if not isinstance(self.fabricated, bool):
            raise TypeError("fabricated must be bool")
        if self.fabricated:
            raise ForbiddenHandoffInterfaceError(
                "fabricate_receipt",
                "official artifacts must be user-imported; fabrication is forbidden",
            )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_OFFICIAL_ARTIFACT:
            raise HandoffError(
                f"output_kind must be {OUTPUT_KIND_OFFICIAL_ARTIFACT!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    @property
    def is_verified(self) -> bool:
        return (
            self.verification_status is ArtifactVerificationStatus.VERIFIED
            and not self.fabricated
        )

    def binds_package_digest(self, package_digest: str) -> bool:
        return self.package_digest == _sha256_hex_field(
            package_digest, "package_digest"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_digest": self.content_digest,
            "fabricated": self.fabricated,
            "filename": self.filename,
            "imported_at_utc": self.imported_at_utc,
            "imported_by": self.imported_by,
            "kind": self.kind.value
            if isinstance(self.kind, OfficialArtifactKind)
            else str(self.kind),
            "labels": dict(self.labels),
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "source_receipt_id": self.source_receipt_id,
            "verification_status": self.verification_status.value
            if isinstance(self.verification_status, ArtifactVerificationStatus)
            else str(self.verification_status),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OfficialArtifact":
        if not isinstance(value, Mapping):
            raise TypeError("OfficialArtifact must be a mapping")
        return cls(
            artifact_id=value.get("artifact_id", ""),
            kind=value.get("kind", OfficialArtifactKind.OTHER_OFFICIAL.value),
            content_digest=value.get("content_digest", ""),
            package_digest=value.get("package_digest", ""),
            verification_status=value.get(
                "verification_status",
                ArtifactVerificationStatus.UNVERIFIED.value,
            ),
            imported_at_utc=value.get("imported_at_utc", ""),
            imported_by=value.get("imported_by", ""),
            source_receipt_id=value.get("source_receipt_id"),
            filename=value.get("filename"),
            fabricated=bool(value.get("fabricated", False)),
            output_kind=value.get("output_kind", OUTPUT_KIND_OFFICIAL_ARTIFACT),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Handoff record (state carrier)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HandoffRecord:
    """Immutable snapshot of a Patent Center handoff lifecycle."""

    handoff_id: str
    matter_id: str
    package_id: str
    package_digest: str
    state: HandoffState | str
    schema_version: str = HANDOFF_SCHEMA_VERSION
    output_kind: str = OUTPUT_KIND_HANDOFF_RECORD
    approval: HumanApprovalRecord | None = None
    export_bundle: ExportBundle | None = None
    training_instructions: HandoffInstructions | None = None
    live_instructions: HandoffInstructions | None = None
    submission: UserSubmissionAssertion | None = None
    official_artifacts: tuple[OfficialArtifact, ...] = ()
    transition_log: tuple[TransitionEvent, ...] = ()
    reason_codes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    classification: DisclosureClassification | str = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
    )
    review_state: ReviewState | str = ReviewState.REQUIRED
    inventor_reviewer: str | None = None
    practitioner_reviewer: str | None = None
    content_digest: str = ""
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "handoff_id", _identifier(self.handoff_id, "handoff_id")
        )
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "package_id", _identifier(self.package_id, "package_id")
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self, "state", _coerce_enum(HandoffState, self.state, "state")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_HANDOFF_RECORD:
            raise HandoffError(
                f"output_kind must be {OUTPUT_KIND_HANDOFF_RECORD!r}",
                code="invalid_output_kind",
            )
        if self.approval is not None and not isinstance(
            self.approval, HumanApprovalRecord
        ):
            if isinstance(self.approval, Mapping):
                object.__setattr__(
                    self, "approval", HumanApprovalRecord.from_dict(self.approval)
                )
            else:
                raise TypeError("approval must be HumanApprovalRecord or None")
        if self.export_bundle is not None and not isinstance(
            self.export_bundle, ExportBundle
        ):
            if isinstance(self.export_bundle, Mapping):
                object.__setattr__(
                    self,
                    "export_bundle",
                    ExportBundle.from_dict(self.export_bundle),
                )
            else:
                raise TypeError("export_bundle must be ExportBundle or None")
        for field_name, cls in (
            ("training_instructions", HandoffInstructions),
            ("live_instructions", HandoffInstructions),
            ("submission", UserSubmissionAssertion),
        ):
            val = getattr(self, field_name)
            if val is not None and not isinstance(val, cls):
                if isinstance(val, Mapping):
                    object.__setattr__(self, field_name, cls.from_dict(val))
                else:
                    raise TypeError(f"{field_name} must be {cls.__name__} or None")
        arts: list[OfficialArtifact] = []
        raw_arts = self.official_artifacts or ()
        if not isinstance(raw_arts, (tuple, list)):
            raise TypeError("official_artifacts must be a sequence")
        if len(raw_arts) > DEFAULT_MAX_ARTIFACTS:
            raise HandoffError(
                "official_artifacts exceeds max",
                code="too_many_artifacts",
            )
        for i, art in enumerate(raw_arts):
            if isinstance(art, OfficialArtifact):
                arts.append(art)
            elif isinstance(art, Mapping):
                arts.append(OfficialArtifact.from_dict(art))
            else:
                raise TypeError(
                    f"official_artifacts[{i}] must be OfficialArtifact or mapping"
                )
        object.__setattr__(self, "official_artifacts", tuple(arts))
        events: list[TransitionEvent] = []
        raw_log = self.transition_log or ()
        if not isinstance(raw_log, (tuple, list)):
            raise TypeError("transition_log must be a sequence")
        if len(raw_log) > DEFAULT_MAX_TRANSITION_LOG:
            raise HandoffError(
                "transition_log exceeds max",
                code="too_many_transitions",
            )
        for i, ev in enumerate(raw_log):
            if isinstance(ev, TransitionEvent):
                events.append(ev)
            elif isinstance(ev, Mapping):
                events.append(TransitionEvent.from_dict(ev))
            else:
                raise TypeError(
                    f"transition_log[{i}] must be TransitionEvent or mapping"
                )
        object.__setattr__(self, "transition_log", tuple(events))
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(
                self.reason_codes, "reason_codes", max_items=DEFAULT_MAX_REASON_CODES
            ),
        )
        object.__setattr__(
            self,
            "warnings",
            _tuple_of_str(
                self.warnings, "warnings", max_items=DEFAULT_MAX_WARNINGS
            ),
        )
        object.__setattr__(
            self,
            "classification",
            _coerce_classification(self.classification),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self,
            "inventor_reviewer",
            _optional_str(
                self.inventor_reviewer, "inventor_reviewer", max_len=256
            ),
        )
        object.__setattr__(
            self,
            "practitioner_reviewer",
            _optional_str(
                self.practitioner_reviewer, "practitioner_reviewer", max_len=256
            ),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise HandoffError(
                    "content_digest does not match handoff material",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    # -- derived properties -------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        return self.state in (
            HandoffState.RECEIPT_VERIFIED,
            HandoffState.INVALIDATED,
        )

    @property
    def is_submitted(self) -> bool:
        """True only after an external human assertion of submission."""
        return self.state in (
            HandoffState.USER_SUBMITTED,
            HandoffState.RECEIPT_VERIFIED,
        ) and self.submission is not None

    @property
    def filing_is_external(self) -> bool:
        return True

    @property
    def can_file(self) -> bool:
        return False

    @property
    def filing_authorization(self) -> bool:
        return False

    @property
    def verified_official_artifacts(self) -> tuple[OfficialArtifact, ...]:
        return tuple(a for a in self.official_artifacts if a.is_verified)

    @property
    def has_verified_acknowledgement(self) -> bool:
        return any(
            a.is_verified and a.kind is OfficialArtifactKind.ACKNOWLEDGEMENT
            for a in self.official_artifacts
        )

    def material_payload(self) -> dict[str, Any]:
        return {
            "approval": self.approval.to_dict() if self.approval else None,
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "export_bundle": self.export_bundle.to_dict()
            if self.export_bundle
            else None,
            "handoff_id": self.handoff_id,
            "inventor_reviewer": self.inventor_reviewer,
            "labels": dict(self.labels),
            "live_instructions": self.live_instructions.to_dict()
            if self.live_instructions
            else None,
            "matter_id": self.matter_id,
            "official_artifacts": [a.to_dict() for a in self.official_artifacts],
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "package_id": self.package_id,
            "practitioner_reviewer": self.practitioner_reviewer,
            "reason_codes": list(self.reason_codes),
            "review_state": self.review_state.value
            if isinstance(self.review_state, ReviewState)
            else str(self.review_state),
            "schema_version": self.schema_version,
            "state": self.state.value
            if isinstance(self.state, HandoffState)
            else str(self.state),
            "submission": self.submission.to_dict() if self.submission else None,
            "training_instructions": self.training_instructions.to_dict()
            if self.training_instructions
            else None,
            "transition_log": [e.to_dict() for e in self.transition_log],
            "warnings": list(self.warnings),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["content_digest"] = self.content_digest
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HandoffRecord":
        if not isinstance(value, Mapping):
            raise TypeError("HandoffRecord must be a mapping")
        return cls(
            handoff_id=value.get("handoff_id", ""),
            matter_id=value.get("matter_id", ""),
            package_id=value.get("package_id", ""),
            package_digest=value.get("package_digest", ""),
            state=value.get("state", HandoffState.DRAFT.value),
            schema_version=value.get("schema_version", HANDOFF_SCHEMA_VERSION),
            output_kind=value.get("output_kind", OUTPUT_KIND_HANDOFF_RECORD),
            approval=value.get("approval"),
            export_bundle=value.get("export_bundle"),
            training_instructions=value.get("training_instructions"),
            live_instructions=value.get("live_instructions"),
            submission=value.get("submission"),
            official_artifacts=tuple(value.get("official_artifacts") or ()),
            transition_log=tuple(value.get("transition_log") or ()),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            classification=value.get(
                "classification",
                DisclosureClassification.CONFIDENTIAL_APPLICATION.value,
            ),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            inventor_reviewer=value.get("inventor_reviewer"),
            practitioner_reviewer=value.get("practitioner_reviewer"),
            content_digest=value.get("content_digest", ""),
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Instruction builders (content-free)
# ---------------------------------------------------------------------------


def build_content_free_instructions(
    *,
    mode: HandoffMode | str,
    package_digest: str,
    instructions_id: str,
    export_root_label: str = "local-export-package",
) -> HandoffInstructions:
    """Build content-free training or live Patent Center review steps.

    Steps never contain document bodies, credentials, cookies, or payment
    instrument data. They only describe human actions outside this process.
    """
    mode_e = _coerce_enum(HandoffMode, mode, "mode")
    digest = _sha256_hex_field(package_digest, "package_digest")
    if mode_e is HandoffMode.TRAINING:
        url = PATENT_CENTER_TRAINING_URL_LABEL
        env = "training"
    else:
        url = PATENT_CENTER_LIVE_URL_LABEL
        env = "live"

    steps = (
        InstructionStep(
            step_id="open-patent-center",
            ordinal=1,
            summary=(
                f"Open USPTO Patent Center ({env}) in your own browser at the "
                f"published entry point labeled {url}. This system does not "
                "open network connections or control a browser."
            ),
        ),
        InstructionStep(
            step_id="authenticate-yourself",
            ordinal=2,
            summary=(
                "Authenticate with your own USPTO credentials and complete any "
                "MFA challenge yourself. Never paste passwords, cookies, or "
                "session tokens into this processor."
            ),
        ),
        InstructionStep(
            step_id="upload-export-package",
            ordinal=3,
            summary=(
                f"Upload files from the local export root labeled "
                f"{export_root_label!r}. Confirm each file digest matches the "
                f"approved package digest {digest[:16]}… before continuing."
            ),
        ),
        InstructionStep(
            step_id="human-certify-and-sign",
            ordinal=4,
            summary=(
                "As a natural person, complete any required signatures and "
                "Rule 11.18 certifications inside Patent Center. This system "
                "never signs or certifies."
            ),
        ),
        InstructionStep(
            step_id="pay-fees-yourself",
            ordinal=5,
            summary=(
                "Pay applicable fees through Patent Center using your own "
                "payment instrument. This system has no payment interface."
            ),
        ),
        InstructionStep(
            step_id="submit-yourself",
            ordinal=6,
            summary=(
                "Press Submit yourself in Patent Center. This system never "
                "performs final submission and never marks a package submitted "
                "without your later external assertion."
            ),
        ),
        InstructionStep(
            step_id="download-official-artifacts",
            ordinal=7,
            summary=(
                "Download the Electronic Acknowledgement Receipt, payment "
                "receipt, and any USPTO-converted artifacts. Keep them as "
                "local files for authorized import."
            ),
        ),
        InstructionStep(
            step_id="record-submitted-digest",
            ordinal=8,
            summary=(
                f"Return to this handoff and record an external human assertion "
                f"with the submitted package digest (approved digest "
                f"{digest[:16]}…) so state may advance past exported."
            ),
        ),
        InstructionStep(
            step_id="import-verified-artifacts",
            ordinal=9,
            summary=(
                "Import the official artifacts with verification status bound "
                "to the approved/submitted digest. Receipt-verified requires "
                "at least one verified acknowledgement artifact."
            ),
        ),
    )
    return HandoffInstructions(
        instructions_id=instructions_id,
        mode=mode_e,
        package_digest=digest,
        patent_center_url_label=url,
        steps=steps,
        labels={"environment": env, "content_free": "true"},
    )


def has_verified_official_artifacts_for_receipt(
    artifacts: Sequence[OfficialArtifact],
    *,
    package_digest: str,
) -> bool:
    """Return True when artifacts satisfy receipt-verified entry gates.

    Requires at least one **verified**, non-fabricated acknowledgement
    bound to *package_digest*. Payment-only is insufficient.
    """
    digest = _sha256_hex_field(package_digest, "package_digest")
    for art in artifacts:
        if not isinstance(art, OfficialArtifact):
            continue
        if not art.is_verified:
            continue
        if not art.binds_package_digest(digest):
            continue
        if art.kind is OfficialArtifactKind.ACKNOWLEDGEMENT:
            return True
    return False


# ---------------------------------------------------------------------------
# Filing state machine
# ---------------------------------------------------------------------------


class FilingStateMachine:
    """Pure transition engine for :class:`HandoffState`.

    Guards:
    * only :data:`ALLOWED_TRANSITIONS` edges succeed;
    * leaving ``exported`` requires an external human assertion object;
    * entering ``receipt-verified`` requires verified official artifacts.
    """

    interface: Final = FILING_STATE_MACHINE_INTERFACE

    def allowed_targets(self, state: HandoffState | str) -> frozenset[HandoffState]:
        src = _coerce_enum(HandoffState, state, "state")
        return ALLOWED_TRANSITIONS.get(src, frozenset())  # type: ignore[return-value]

    def can_transition(
        self,
        from_state: HandoffState | str,
        to_state: HandoffState | str,
        *,
        submission: UserSubmissionAssertion | None = None,
        official_artifacts: Sequence[OfficialArtifact] = (),
        package_digest: str | None = None,
    ) -> bool:
        try:
            self.assert_can_transition(
                from_state,
                to_state,
                submission=submission,
                official_artifacts=official_artifacts,
                package_digest=package_digest,
            )
        except HandoffError:
            return False
        return True

    def assert_can_transition(
        self,
        from_state: HandoffState | str,
        to_state: HandoffState | str,
        *,
        submission: UserSubmissionAssertion | None = None,
        official_artifacts: Sequence[OfficialArtifact] = (),
        package_digest: str | None = None,
    ) -> None:
        src = _coerce_enum(HandoffState, from_state, "from_state")
        dst = _coerce_enum(HandoffState, to_state, "to_state")
        if src is HandoffState.INVALIDATED:
            raise HandoffInvalidatedError(
                "cannot transition from an invalidated handoff"
            )
        assert_transition_allowed(src, dst)

        # Past exported requires external human assertion.
        if src in _REQUIRES_HUMAN_ASSERTION_TO_LEAVE:
            if submission is None:
                raise ExternalHumanAssertionRequiredError(
                    "cannot advance past exported without an external human "
                    "submission assertion"
                )
            if not submission.external_human_action:
                raise ExternalHumanAssertionRequiredError(
                    "submission assertion must record external_human_action=True"
                )
            if package_digest is not None and not submission.binds_package_digest(
                package_digest
            ):
                raise HandoffDigestMismatchError(
                    "submission assertion package_digest does not match handoff"
                )

        # Entering receipt-verified requires verified official artifacts.
        if dst in _REQUIRES_VERIFIED_ARTIFACTS_TO_ENTER:
            if package_digest is None:
                raise VerifiedArtifactsRequiredError(
                    "package_digest is required to verify official artifacts"
                )
            if not has_verified_official_artifacts_for_receipt(
                official_artifacts, package_digest=package_digest
            ):
                raise VerifiedArtifactsRequiredError(
                    "cannot advance to receipt-verified without verified "
                    "official artefacts (acknowledgement bound to package digest)"
                )

    def apply(
        self,
        record: HandoffRecord,
        to_state: HandoffState | str,
        *,
        actor: str,
        at_utc: str,
        reason_code: str,
        note: str | None = None,
        submission: UserSubmissionAssertion | None = None,
        official_artifacts: Sequence[OfficialArtifact] | None = None,
        approval: HumanApprovalRecord | None = None,
        export_bundle: ExportBundle | None = None,
        training_instructions: HandoffInstructions | None = None,
        live_instructions: HandoffInstructions | None = None,
        extra_reason_codes: Sequence[str] = (),
    ) -> HandoffRecord:
        """Return a new :class:`HandoffRecord` advanced to *to_state*."""
        if not isinstance(record, HandoffRecord):
            raise TypeError("record must be HandoffRecord")
        dst = _coerce_enum(HandoffState, to_state, "to_state")
        arts = (
            tuple(official_artifacts)
            if official_artifacts is not None
            else record.official_artifacts
        )
        sub = submission if submission is not None else record.submission
        self.assert_can_transition(
            record.state,
            dst,
            submission=sub,
            official_artifacts=arts,
            package_digest=record.package_digest,
        )
        event = TransitionEvent(
            from_state=record.state,
            to_state=dst,
            at_utc=at_utc,
            actor=actor,
            reason_code=reason_code,
            note=note,
        )
        log = list(record.transition_log)
        log.append(event)
        if len(log) > DEFAULT_MAX_TRANSITION_LOG:
            log = log[-DEFAULT_MAX_TRANSITION_LOG:]
        reasons = list(record.reason_codes)
        reasons.append(reason_code)
        reasons.extend(extra_reason_codes)
        reasons = list(dict.fromkeys(reasons))

        review = record.review_state
        if dst is HandoffState.HUMAN_APPROVED:
            review = ReviewState.COMPLETE
        elif dst is HandoffState.RECEIPT_VERIFIED:
            review = ReviewState.COMPLETE

        data = record.to_dict()
        data.pop("content_digest", None)
        data["state"] = dst.value
        data["transition_log"] = [e.to_dict() for e in log]
        data["reason_codes"] = reasons
        data["review_state"] = (
            review.value if isinstance(review, ReviewState) else str(review)
        )
        if approval is not None:
            data["approval"] = approval.to_dict()
        if export_bundle is not None:
            data["export_bundle"] = export_bundle.to_dict()
        if training_instructions is not None:
            data["training_instructions"] = training_instructions.to_dict()
        if live_instructions is not None:
            data["live_instructions"] = live_instructions.to_dict()
        if sub is not None:
            data["submission"] = sub.to_dict()
        data["official_artifacts"] = [a.to_dict() for a in arts]
        return HandoffRecord.from_dict(data)


# ---------------------------------------------------------------------------
# PatentCenterHandoff orchestrator
# ---------------------------------------------------------------------------


class PatentCenterHandoff:
    """Human Patent Center handoff orchestrator (no network/browser/payment).

    Advances a matter through draft → validated → human-approved → exported
    → user-submitted → receipt-verified with fail-closed guards.
    """

    interface: Final = HANDOFF_INTERFACE
    schema_version: Final = HANDOFF_SCHEMA_VERSION

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        state_machine: FilingStateMachine | None = None,
    ) -> None:
        self._id_factory = id_factory or _default_id_factory
        self._sm = state_machine or FilingStateMachine()

    # -- surface guards -----------------------------------------------------

    def assert_capability_allowed(self, capability: str) -> None:
        """Alias used by tests; rejects forbidden interfaces."""
        assert_interface_allowed(capability)

    def assert_interface_allowed(self, interface: str) -> None:
        assert_interface_allowed(interface)

    def list_forbidden_interfaces(self) -> frozenset[str]:
        return FORBIDDEN_HANDOFF_INTERFACES

    def has_network_interface(self) -> bool:
        return False

    def has_browser_interface(self) -> bool:
        return False

    def has_session_interface(self) -> bool:
        return False

    def has_payment_interface(self) -> bool:
        return False

    # Explicit closed stubs for forbidden names (always raise).
    def login(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("network_login")

    def open_browser(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("browser")

    def control_browser(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("browser_control")

    def pay(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("payment")

    def pay_fee(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("pay_fee")

    def submit_to_uspto(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("perform_final_submission")

    def file_application(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("file")

    def store_session(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("session")

    def load_session_cookies(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("session_cookie_replay")

    def fabricate_acknowledgement(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("fabricate_acknowledgement")

    def fabricate_payment_receipt(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("fabricate_payment_receipt")

    def fabricate_receipt(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenHandoffInterfaceError("fabricate_receipt")

    # -- lifecycle ----------------------------------------------------------

    def start_draft(
        self,
        *,
        matter_id: str,
        package_id: str,
        package_digest: str,
        handoff_id: str | None = None,
        inventor_reviewer: str | None = None,
        practitioner_reviewer: str | None = None,
        classification: DisclosureClassification | str = (
            DisclosureClassification.CONFIDENTIAL_APPLICATION
        ),
        labels: Mapping[str, str] | None = None,
        started_at_utc: str | None = None,
        started_by: str = "system",
    ) -> HandoffRecord:
        """Create a handoff in ``draft`` bound to a package digest."""
        hid = handoff_id or f"ho:{self._id_factory()}"
        reasons = (
            HandoffReasonCode.HANDOFF_STARTED.value,
            HandoffReasonCode.PACKAGE_BOUND.value,
            HandoffReasonCode.EXTERNAL_FILING_ONLY.value,
            HandoffReasonCode.NEVER_AUTOMATED.value,
            HandoffReasonCode.NO_NETWORK_BROWSER_SESSION_PAYMENT.value,
            HandoffReasonCode.NOT_LEGAL_ADVICE.value,
        )
        log: tuple[TransitionEvent, ...] = ()
        if started_at_utc:
            log = (
                TransitionEvent(
                    from_state=HandoffState.DRAFT,
                    to_state=HandoffState.DRAFT,
                    at_utc=started_at_utc,
                    actor=started_by,
                    reason_code=HandoffReasonCode.HANDOFF_STARTED.value,
                    note="handoff opened in draft",
                ),
            )
        return HandoffRecord(
            handoff_id=hid,
            matter_id=matter_id,
            package_id=package_id,
            package_digest=package_digest,
            state=HandoffState.DRAFT,
            reason_codes=reasons,
            transition_log=log,
            classification=classification,
            review_state=ReviewState.REQUIRED,
            inventor_reviewer=inventor_reviewer,
            practitioner_reviewer=practitioner_reviewer,
            labels=labels or {},
        )

    def mark_validated(
        self,
        record: HandoffRecord,
        *,
        actor: str,
        at_utc: str,
        package_digest: str | None = None,
        note: str | None = None,
    ) -> HandoffRecord:
        """Advance draft → validated (package already validated externally)."""
        self._require_active(record)
        if package_digest is not None:
            pd = _sha256_hex_field(package_digest, "package_digest")
            if pd != record.package_digest:
                raise HandoffDigestMismatchError(
                    "validated package_digest does not match handoff binding"
                )
        return self._sm.apply(
            record,
            HandoffState.VALIDATED,
            actor=actor,
            at_utc=at_utc,
            reason_code=HandoffReasonCode.STATE_VALIDATED.value,
            note=note or "package validated for human review",
        )

    def record_human_approval(
        self,
        record: HandoffRecord,
        *,
        approver_name: str,
        approved_at_utc: str,
        statement: str,
        role: str = "inventor_or_practitioner",
        approval_id: str | None = None,
        package_digest: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> HandoffRecord:
        """Advance validated → human-approved with exact-digest approval."""
        self._require_active(record)
        digest = (
            _sha256_hex_field(package_digest, "package_digest")
            if package_digest is not None
            else record.package_digest
        )
        if digest != record.package_digest:
            raise HandoffDigestMismatchError(
                "approval package_digest does not match handoff binding"
            )
        approval = HumanApprovalRecord(
            approval_id=approval_id or f"hap:{self._id_factory()}",
            package_digest=digest,
            approver_name=approver_name,
            approved_at_utc=approved_at_utc,
            statement=statement,
            role=role,
            labels=labels or {},
        )
        return self._sm.apply(
            record,
            HandoffState.HUMAN_APPROVED,
            actor=approver_name,
            at_utc=approved_at_utc,
            reason_code=HandoffReasonCode.HUMAN_APPROVED.value,
            note="exact package digest human-approved for external handoff",
            approval=approval,
        )

    def export_for_patent_center(
        self,
        record: HandoffRecord,
        *,
        exported_by: str,
        exported_at_utc: str,
        export_root_label: str,
        file_digests: Mapping[str, str] | None = None,
        export_id: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> HandoffRecord:
        """Advance human-approved → exported; emit training + live instructions."""
        self._require_active(record)
        if record.approval is None:
            raise InvalidTransitionError(
                "export requires a recorded human approval",
                from_state=record.state.value
                if isinstance(record.state, HandoffState)
                else str(record.state),
                to_state=HandoffState.EXPORTED.value,
            )
        if not record.approval.binds_package_digest(record.package_digest):
            raise HandoffDigestMismatchError(
                "approval no longer binds package digest"
            )

        train = build_content_free_instructions(
            mode=HandoffMode.TRAINING,
            package_digest=record.package_digest,
            instructions_id=f"ins-train:{self._id_factory()}",
            export_root_label=export_root_label,
        )
        live = build_content_free_instructions(
            mode=HandoffMode.LIVE,
            package_digest=record.package_digest,
            instructions_id=f"ins-live:{self._id_factory()}",
            export_root_label=export_root_label,
        )
        bundle = ExportBundle(
            export_id=export_id or f"exp:{self._id_factory()}",
            package_digest=record.package_digest,
            exported_at_utc=exported_at_utc,
            exported_by=exported_by,
            export_root_label=export_root_label,
            file_digests=file_digests or {},
            training_instructions_id=train.instructions_id,
            live_instructions_id=live.instructions_id,
            labels=labels or {},
        )
        return self._sm.apply(
            record,
            HandoffState.EXPORTED,
            actor=exported_by,
            at_utc=exported_at_utc,
            reason_code=HandoffReasonCode.EXPORTED.value,
            note="export bundle and content-free instructions emitted",
            export_bundle=bundle,
            training_instructions=train,
            live_instructions=live,
            extra_reason_codes=(
                HandoffReasonCode.INSTRUCTIONS_EMITTED.value,
                HandoffReasonCode.CONTENT_FREE_INSTRUCTIONS.value,
                HandoffReasonCode.EXTERNAL_FILING_ONLY.value,
            ),
        )

    def record_user_submission(
        self,
        record: HandoffRecord,
        *,
        asserted_by: str,
        asserted_at_utc: str,
        statement: str,
        submitted_digest: str | None = None,
        mode: HandoffMode | str = HandoffMode.LIVE,
        confirmation_number: str | None = None,
        assertion_id: str | None = None,
        external_human_action: bool = True,
        labels: Mapping[str, str] | None = None,
    ) -> HandoffRecord:
        """Advance exported → user-submitted via external human assertion.

        Without ``external_human_action=True`` and a binding assertion this
        transition **fails**. The system cannot invent a submission.
        """
        self._require_active(record)
        if not external_human_action:
            raise ExternalHumanAssertionRequiredError(
                "cannot advance past exported without external_human_action=True"
            )
        sub_digest = (
            _sha256_hex_field(submitted_digest, "submitted_digest")
            if submitted_digest is not None
            else record.package_digest
        )
        # Submitted digest must match approved package (exact handoff binding).
        if sub_digest != record.package_digest:
            raise HandoffDigestMismatchError(
                "submitted_digest must match the approved package_digest; "
                "material changes require a new handoff"
            )
        assertion = UserSubmissionAssertion(
            assertion_id=assertion_id or f"usa:{self._id_factory()}",
            package_digest=record.package_digest,
            submitted_digest=sub_digest,
            asserted_by=asserted_by,
            asserted_at_utc=asserted_at_utc,
            statement=statement,
            mode=mode,
            confirmation_number=confirmation_number,
            external_human_action=True,
            labels=labels or {},
        )
        return self._sm.apply(
            record,
            HandoffState.USER_SUBMITTED,
            actor=asserted_by,
            at_utc=asserted_at_utc,
            reason_code=HandoffReasonCode.USER_SUBMISSION_RECORDED.value,
            note="external human asserted Patent Center submission",
            submission=assertion,
            extra_reason_codes=(
                HandoffReasonCode.EXTERNAL_HUMAN_ASSERTION_REQUIRED.value,
            ),
        )

    def bind_official_artifact(
        self,
        record: HandoffRecord,
        artifact: OfficialArtifact,
    ) -> HandoffRecord:
        """Attach a user-imported official artifact without changing state."""
        self._require_active(record)
        if not isinstance(artifact, OfficialArtifact):
            raise TypeError("artifact must be OfficialArtifact")
        if artifact.fabricated:
            raise ForbiddenHandoffInterfaceError("fabricate_receipt")
        if not artifact.binds_package_digest(record.package_digest):
            raise HandoffDigestMismatchError(
                "artifact package_digest does not match handoff"
            )
        arts = list(record.official_artifacts)
        # Replace same artifact_id if re-imported.
        arts = [a for a in arts if a.artifact_id != artifact.artifact_id]
        arts.append(artifact)
        if len(arts) > DEFAULT_MAX_ARTIFACTS:
            raise HandoffError(
                "official_artifacts exceeds max",
                code="too_many_artifacts",
            )
        reasons = list(record.reason_codes)
        reasons.append(HandoffReasonCode.OFFICIAL_ARTIFACT_BOUND.value)
        reasons = list(dict.fromkeys(reasons))
        data = record.to_dict()
        data.pop("content_digest", None)
        data["official_artifacts"] = [a.to_dict() for a in arts]
        data["reason_codes"] = reasons
        return HandoffRecord.from_dict(data)

    def verify_receipts(
        self,
        record: HandoffRecord,
        *,
        actor: str,
        at_utc: str,
        note: str | None = None,
    ) -> HandoffRecord:
        """Advance user-submitted → receipt-verified if artifacts qualify.

        Fails on invalid source state, missing submission assertion, or when
        verified official acknowledgement artifacts are absent.
        """
        self._require_active(record)
        # Fail closed on wrong phase before secondary guards (acceptance:
        # invalid transitions fail).
        assert_transition_allowed(record.state, HandoffState.RECEIPT_VERIFIED)
        if record.submission is None:
            raise ExternalHumanAssertionRequiredError(
                "receipt verification requires a prior user-submission assertion"
            )
        if not has_verified_official_artifacts_for_receipt(
            record.official_artifacts, package_digest=record.package_digest
        ):
            raise VerifiedArtifactsRequiredError(
                "cannot advance to receipt-verified without verified official "
                "artefacts (acknowledgement bound to the package digest)"
            )
        return self._sm.apply(
            record,
            HandoffState.RECEIPT_VERIFIED,
            actor=actor,
            at_utc=at_utc,
            reason_code=HandoffReasonCode.RECEIPT_VERIFIED.value,
            note=note or "verified official artefacts bound to submitted digest",
            extra_reason_codes=(
                HandoffReasonCode.VERIFIED_ARTIFACTS_REQUIRED.value,
            ),
        )

    def invalidate(
        self,
        record: HandoffRecord,
        *,
        actor: str,
        at_utc: str,
        reason: str,
    ) -> HandoffRecord:
        """Force handoff into invalidated (digest drift or operator cancel)."""
        if record.state is HandoffState.INVALIDATED:
            return record
        event = TransitionEvent(
            from_state=record.state,
            to_state=HandoffState.INVALIDATED,
            at_utc=at_utc,
            actor=actor,
            reason_code=HandoffReasonCode.HANDOFF_INVALIDATED.value,
            note=_require_str(reason, "reason", max_len=512),
        )
        log = list(record.transition_log)
        log.append(event)
        reasons = list(record.reason_codes)
        reasons.append(HandoffReasonCode.HANDOFF_INVALIDATED.value)
        reasons = list(dict.fromkeys(reasons))
        data = record.to_dict()
        data.pop("content_digest", None)
        data["state"] = HandoffState.INVALIDATED.value
        data["transition_log"] = [e.to_dict() for e in log]
        data["reason_codes"] = reasons
        data["review_state"] = ReviewState.REQUIRED.value
        data["warnings"] = list(record.warnings) + [
            _require_str(reason, "reason", max_len=512)
        ]
        return HandoffRecord.from_dict(data)

    def generate_instructions(
        self,
        record: HandoffRecord,
        *,
        mode: HandoffMode | str,
        export_root_label: str | None = None,
    ) -> HandoffInstructions:
        """Generate (or re-generate) content-free instructions for *mode*."""
        root = export_root_label
        if root is None and record.export_bundle is not None:
            root = record.export_bundle.export_root_label
        if root is None:
            root = "local-export-package"
        return build_content_free_instructions(
            mode=mode,
            package_digest=record.package_digest,
            instructions_id=f"ins:{self._id_factory()}",
            export_root_label=root,
        )

    def _require_active(self, record: HandoffRecord) -> None:
        if not isinstance(record, HandoffRecord):
            raise TypeError("record must be HandoffRecord")
        if record.state is HandoffState.INVALIDATED:
            raise HandoffInvalidatedError(
                "handoff is invalidated; start a new handoff for a new digest"
            )

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}:{self._id_factory()}"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def create_handoff(
    *,
    matter_id: str,
    package_id: str,
    package_digest: str,
    id_factory: Callable[[], str] | None = None,
    **kwargs: Any,
) -> HandoffRecord:
    """Module-level draft handoff factory."""
    return PatentCenterHandoff(id_factory=id_factory).start_draft(
        matter_id=matter_id,
        package_id=package_id,
        package_digest=package_digest,
        **kwargs,
    )


def prove_no_forbidden_interfaces(
    handoff: PatentCenterHandoff | None = None,
) -> dict[str, Any]:
    """Return a structured proof that forbidden interfaces are closed.

    Used by integration tests and the ops runbook. Never opens network,
    browser, session, or payment surfaces.
    """
    h = handoff or PatentCenterHandoff()
    closed: dict[str, bool] = {
        "network": not h.has_network_interface(),
        "browser": not h.has_browser_interface(),
        "session": not h.has_session_interface(),
        "payment": not h.has_payment_interface(),
    }
    rejected: list[str] = []
    for iface in sorted(FORBIDDEN_HANDOFF_INTERFACES):
        try:
            h.assert_interface_allowed(iface)
            closed_ok = False
        except ForbiddenHandoffInterfaceError:
            closed_ok = True
            rejected.append(iface)
        if not closed_ok:
            raise HandoffError(
                f"interface {iface!r} was not rejected",
                code="interface_leak",
            )
    # Forbidden method names must raise, not succeed.
    for name in sorted(FORBIDDEN_METHOD_NAMES):
        if not hasattr(h, name):
            continue
        method = getattr(h, name)
        if not callable(method):
            continue
        try:
            method()
            raise HandoffError(
                f"forbidden method {name!r} did not raise",
                code="method_leak",
            )
        except ForbiddenHandoffInterfaceError:
            pass
    # Module import graph must not include forbidden clients.
    import sys

    mod = sys.modules.get(__name__)
    leaked = sorted(
        m
        for m in FORBIDDEN_IMPORT_MODULES
        if m in sys.modules
        and mod is not None
        and any(
            getattr(mod, attr, None) is sys.modules[m]
            for attr in dir(mod)
            if not attr.startswith("__")
        )
    )
    # Stronger check: source of this module does not import them.
    import pathlib

    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    for m in FORBIDDEN_IMPORT_MODULES:
        if re.search(rf"^\s*(import|from)\s+{re.escape(m)}\b", source, re.M):
            leaked.append(m)
    if leaked:
        raise HandoffError(
            f"forbidden imports present: {', '.join(sorted(set(leaked)))}",
            code="import_leak",
        )
    return {
        "closed": closed,
        "forbidden_interfaces": sorted(FORBIDDEN_HANDOFF_INTERFACES),
        "rejected_count": len(rejected),
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "interface": HANDOFF_INTERFACE,
        "no_network_browser_session_payment": all(closed.values()),
    }


__all__ = [
    "ALLOWED_TRANSITIONS",
    "ARTIFACT_VERIFICATION_STATUSES",
    "DEFAULT_MAX_ARTIFACTS",
    "DEFAULT_MAX_INSTRUCTIONS",
    "FILING_STATE_MACHINE_INTERFACE",
    "FORBIDDEN_HANDOFF_INTERFACES",
    "FORBIDDEN_IMPORT_MODULES",
    "FORBIDDEN_METHOD_NAMES",
    "HANDOFF_DISCLAIMER",
    "HANDOFF_INTERFACE",
    "HANDOFF_RULESET_VERSION",
    "HANDOFF_SCHEMA_VERSION",
    "OUTPUT_KIND_EXPORT_BUNDLE",
    "OUTPUT_KIND_HANDOFF_INSTRUCTIONS",
    "OUTPUT_KIND_HANDOFF_RECORD",
    "OUTPUT_KIND_HUMAN_APPROVAL",
    "OUTPUT_KIND_OFFICIAL_ARTIFACT",
    "OUTPUT_KIND_USER_SUBMISSION",
    "PARSER_VERSION",
    "PATENT_CENTER_LIVE_URL_LABEL",
    "PATENT_CENTER_TRAINING_URL_LABEL",
    "ArtifactVerificationStatus",
    "ExportBundle",
    "ExternalHumanAssertionRequiredError",
    "FilingStateMachine",
    "ForbiddenHandoffInterfaceError",
    "HandoffDigestMismatchError",
    "HandoffError",
    "HandoffInstructions",
    "HandoffInvalidatedError",
    "HandoffMode",
    "HandoffReasonCode",
    "HandoffRecord",
    "HandoffState",
    "HumanApprovalRecord",
    "InstructionStep",
    "InvalidTransitionError",
    "OfficialArtifact",
    "OfficialArtifactKind",
    "PatentCenterHandoff",
    "TransitionEvent",
    "UserSubmissionAssertion",
    "VerifiedArtifactsRequiredError",
    "assert_interface_allowed",
    "assert_transition_allowed",
    "build_content_free_instructions",
    "create_handoff",
    "has_verified_official_artifacts_for_receipt",
    "is_forbidden_interface",
    "is_transition_allowed",
    "prove_no_forbidden_interfaces",
    "sha256_hex",
]

# Convenience alias used in __all__ documentation only.
ARTIFACT_VERIFICATION_STATUSES: Final[frozenset[str]] = frozenset(
    s.value for s in ArtifactVerificationStatus
)
