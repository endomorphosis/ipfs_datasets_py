"""Detect and quarantine instruction-like untrusted task data (SCG-013).

Comments, docstrings, issue/task text, tests, logs, and retrieved documentation
are untrusted. This module scans those surfaces for instruction-like patterns
and records bounded quarantine evidence only.

Normative rules:

* Detection produces audit evidence; it never mutates policy, routing,
  assurance, trusted keys, proof systems, sampling, verification, source
  inclusion, or promotion.
* Deterministic governor decisions consume only trusted configuration
  channels. Untrusted text and quarantine evidence are attached for audit
  and are ignored by the decision function even when they mimic
  configuration or authorization language.
* Durable evidence stores digests and bounded printable previews — never
  private source field names or model-written authority claims.
* Identical fragment inputs yield identical evidence identities.
* Canonical identity uses ``software_contracts.content`` only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
import re
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    AuthoritySource,
    ExecutionMode,
    SemanticGovernorBaseError,
    reject_private_and_model_authority,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

DETECT_INSTRUCTION_LIKE_CONTENT_INTERFACE: Final[str] = (
    "detect_instruction_like_content@1"
)
UNTRUSTED_INSTRUCTION_EVIDENCE_INTERFACE: Final[str] = (
    "UntrustedInstructionEvidence@1"
)
UNTRUSTED_INSTRUCTION_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-untrusted-instruction-evidence@1"
)
INSTRUCTION_LIKE_MATCH_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-instruction-like-match@1"
)
UNTRUSTED_INPUT_FRAGMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-untrusted-input-fragment@1"
)
TRUSTED_DECISION_CONFIG_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-trusted-decision-config@1"
)
DETERMINISTIC_DECISION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-deterministic-decision@1"
)

GENERATOR_ID: Final[str] = "untrusted_input_scanner"
GENERATOR_VERSION: Final[str] = "1.0.0"
PRODUCER_ID: Final[str] = "semantic_governor"
PRODUCER_VERSION: Final[str] = "1"
TOOL_ID: Final[str] = "untrusted_input.v1"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_FRAGMENT_CHARS: Final[int] = 65_536
MAX_FRAGMENTS: Final[int] = 1_024
MAX_MATCHES: Final[int] = 512
MAX_EXCERPT_PREVIEW_CHARS: Final[int] = 128
MAX_PATH_CHARS: Final[int] = 1_024
MAX_CID_LIST: Final[int] = 4_096
MAX_PATTERN_IDS: Final[int] = 64
MAX_REASON_CODES: Final[int] = 256

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_TASK_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.:/+-]{0,127}$"
)
_REPO_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[A-Za-z0-9_./@+-][A-Za-z0-9_./@+-]{0,1022})$"
)
_FRAGMENT_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.:/+-]{0,127}$"
)

# Protected decision domains that untrusted text must never control.
PROTECTED_DECISION_DOMAINS: Final[tuple[str, ...]] = (
    "routing",
    "verification",
    "capsule_classification",
    "trusted_keys",
    "proof_systems",
    "sampling",
    "source_inclusion",
    "promotion",
    "policy",
    "assurance",
    "authorization",
)


class UntrustedInputError(SemanticGovernorBaseError):
    """Raised when untrusted-input scanning fails closed."""


# ---------------------------------------------------------------------------
# Closed enumerations
# ---------------------------------------------------------------------------


class UntrustedSourceKind(str, Enum):
    """Closed untrusted surfaces scanned for instruction-like content."""

    COMMENT = "comment"
    DOCSTRING = "docstring"
    TASK_TEXT = "task_text"
    ISSUE_TEXT = "issue_text"
    TEST = "test"
    LOG = "log"
    DOCUMENTATION = "documentation"
    RETRIEVED_DOC = "retrieved_doc"
    FIXTURE = "fixture"
    OTHER = "other"


class InstructionLikePatternId(str, Enum):
    """Closed catalog of instruction-like injection pattern families."""

    IGNORE_PRIOR_INSTRUCTIONS = "ignore_prior_instructions"
    SYSTEM_ROLE_CLAIM = "system_role_claim"
    DEVELOPER_ROLE_CLAIM = "developer_role_claim"
    AUTHORITY_OVERRIDE = "authority_override"
    POLICY_MUTATION = "policy_mutation"
    ROUTING_OVERRIDE = "routing_override"
    PROMOTION_OVERRIDE = "promotion_override"
    TRUSTED_KEY_CLAIM = "trusted_key_claim"
    VERIFICATION_BYPASS = "verification_bypass"
    PROOF_SYSTEM_MUTATION = "proof_system_mutation"
    SAMPLING_OVERRIDE = "sampling_override"
    SOURCE_INCLUSION_OVERRIDE = "source_inclusion_override"
    CONFIG_MIMIC = "config_mimic"
    AUTHORIZATION_MIMIC = "authorization_mimic"
    HIDDEN_INSTRUCTION = "hidden_instruction"
    TOOL_EXFILTRATION = "tool_exfiltration"
    JAILBREAK = "jailbreak"


class QuarantineDisposition(str, Enum):
    """Closed disposition for scanned untrusted content."""

    CLEAN = "clean"
    QUARANTINED = "quarantined"
    TRUNCATED = "truncated"


class DecisionAction(str, Enum):
    """Closed deterministic decision actions from trusted configuration only."""

    CONTINUE = "continue"
    REQUIRE_HUMAN_REVIEW = "require_human_review"
    REJECT = "reject"
    MARK_INCONCLUSIVE = "mark_inconclusive"


# Pattern catalog: (pattern_id, compiled regex). Order is stable for
# deterministic match emission (lower start offset, then pattern id).
# Case-insensitivity is applied via re.IGNORECASE only — never mid-pattern
# inline flags (Python 3.11+ rejects global flags after the start).
_PATTERN_CATALOG: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        InstructionLikePatternId.IGNORE_PRIOR_INSTRUCTIONS.value,
        re.compile(
            r"\b(?:ignore|disregard|forget)\s+(?:all\s+)?"
            r"(?:previous|prior|above|earlier)\s+instructions?\b",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.SYSTEM_ROLE_CLAIM.value,
        re.compile(
            r"(?:^|\n)\s*(?:system|\[?\s*system\s*\]?)\s*:"
            r"|\byou\s+are\s+(?:now\s+)?(?:a\s+)?system\b"
            r"|\bbegin\s+system\s+prompt\b",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.DEVELOPER_ROLE_CLAIM.value,
        re.compile(
            r"(?:^|\n)\s*(?:developer|\[?\s*developer\s*\]?)\s*:"
            r"|\bdeveloper\s+message\b",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.AUTHORITY_OVERRIDE.value,
        re.compile(
            r"\b(?:grant|assume|take|elevate)\s+(?:full\s+)?"
            r"(?:admin|root|operator|authority)\b"
            r"|\bself[-_\s]?authori[sz]e\b"
            r"|\bmodel[-_\s]?authority\b"
            r"|\bllm[-_\s]?authority\b",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.POLICY_MUTATION.value,
        re.compile(
            r"\b(?:set|update|override|mutate|change)\s+"
            r"(?:the\s+)?(?:compression\s+)?policy\b"
            r"|\bpolicy\s*[:=]\s*[A-Za-z0-9_.+-]+"
            r"|\bpolicy_cid\s*[:=]",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.ROUTING_OVERRIDE.value,
        re.compile(
            r"\b(?:route|routing|model\s+tier|use\s+frontier)\b"
            r".{0,40}?(?:frontier|bypass|force|must|always)"
            r"|\broute\s*[:=]\s*(?:frontier|human|small|medium|deterministic)"
            r"|\bforce\s+(?:the\s+)?(?:frontier|expensive)\s+route\b",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.PROMOTION_OVERRIDE.value,
        re.compile(
            r"\b(?:promote|promotion)\s+(?:this\s+)?"
            r"(?:policy|candidate|now|immediately)\b"
            r"|\bpromotion_authority\s*[:=]"
            r"|\bauto[-_\s]?promote\b",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.TRUSTED_KEY_CLAIM.value,
        re.compile(
            r"\btrusted[-_\s]?keys?\b"
            r"|\b(?:install|rotate|replace)\s+trusted\s+key\b"
            r"|\bprivate[-_\s]?key\s*[:=]",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.VERIFICATION_BYPASS.value,
        re.compile(
            r"\b(?:skip|bypass|disable|ignore)\s+"
            r"(?:all\s+)?(?:verification|proofs?|tests?|checks?)\b"
            r"|\bverification\s*[:=]\s*(?:off|false|disabled|skip)",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.PROOF_SYSTEM_MUTATION.value,
        re.compile(
            r"\b(?:change|switch|override)\s+(?:the\s+)?proof\s+system\b"
            r"|\bproof_system\s*[:=]"
            r"|\baccept\s+unproven\s+claims?\b",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.SAMPLING_OVERRIDE.value,
        re.compile(
            r"\b(?:temperature|top_p|top_k|sampling)\s*[:=]\s*"
            r"|\bset\s+temperature\b"
            r"|\bdisable\s+deterministic\s+sampling\b",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.SOURCE_INCLUSION_OVERRIDE.value,
        re.compile(
            r"\b(?:include|disclose|exfiltrate)\s+"
            r"(?:all\s+)?(?:private\s+)?(?:source|secrets?|keys?)\b"
            r"|\bsource_inclusion\s*[:=]"
            r"|\bdo\s+not\s+redact\b",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.CONFIG_MIMIC.value,
        re.compile(
            r"\b(?:trusted_config|governor_config|runtime_config)\s*[:=]"
            r"|\"(?:route_tier|promote|authorization_cid|policy_cid)\"\s*:"
            r"|\bBEGIN\s+TRUSTED\s+CONFIG\b"
            r"|\b\[trusted[_-]config\]\b",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.AUTHORIZATION_MIMIC.value,
        re.compile(
            r"\bauthorization(?:_cid)?\s*[:=]"
            r"|\bauthorized\s+by\s+(?:operator|admin|root)\b"
            r"|\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"
            r"|\baccess_token\s*[:=]",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.HIDDEN_INSTRUCTION.value,
        re.compile(
            r"<!--\s*(?:instruction|system|prompt)"
            r"|\[(?:INST|/INST|SYS|/SYS)\]"
            r"|<<\s*SYS\s*>>"
            r"|<\|(?:system|endoftext|im_start)\|>",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.TOOL_EXFILTRATION.value,
        re.compile(
            r"\b(?:send|upload|post|exfiltrate)\s+"
            r"(?:this\s+)?(?:to|via)\s+(?:webhook|external|http)"
            r"|\bcurl\s+https?://"
            r"|\bexfiltrat",
            re.IGNORECASE,
        ),
    ),
    (
        InstructionLikePatternId.JAILBREAK.value,
        re.compile(
            r"\bjailbreak\b"
            r"|\bDAN\s+mode\b"
            r"|\bdo\s+anything\s+now\b"
            r"|\bdeveloper\s+mode\s+enabled\b"
            r"|\bunrestricted\s+mode\b",
            re.IGNORECASE,
        ),
    ),
)

_PATTERN_BY_ID: Final[Mapping[str, re.Pattern[str]]] = MappingProxyType(
    {pattern_id: regex for pattern_id, regex in _PATTERN_CATALOG}
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, max_chars: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise UntrustedInputError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise UntrustedInputError(f"{name} must be trimmed NFC text")
    if len(value) > max_chars:
        raise UntrustedInputError(f"{name} exceeds maximum length {max_chars}")
    if any(ord(char) < 32 and char not in "\n\t\r" for char in value):
        raise UntrustedInputError(f"{name} contains invalid control characters")
    if any(unicodedata.category(char) == "Cc" and char not in "\n\t\r" for char in value):
        raise UntrustedInputError(f"{name} contains invalid control characters")
    return value


def _optional_text(
    value: Any,
    name: str,
    *,
    max_chars: int = MAX_TEXT_CHARS,
) -> str | None:
    if value is None:
        return None
    return _text(value, name, max_chars=max_chars)


def _scan_text(value: Any, name: str) -> str:
    """Accept fragment body text (may include internal newlines; NFC required)."""

    if type(value) is not str:
        raise UntrustedInputError(f"{name} must be a string")
    if unicodedata.normalize("NFC", value) != value:
        raise UntrustedInputError(f"{name} must be NFC-normalized text")
    if len(value) > MAX_FRAGMENT_CHARS:
        raise UntrustedInputError(f"{name} exceeds maximum fragment length")
    if any(ord(char) < 32 and char not in "\n\t\r" for char in value):
        raise UntrustedInputError(f"{name} contains invalid control characters")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise UntrustedInputError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _task_id(value: Any, name: str = "task_id") -> str:
    text = _text(value, name)
    if _TASK_ID_RE.fullmatch(text) is None:
        raise UntrustedInputError(f"{name} must match {_TASK_ID_RE.pattern}")
    return text


def _fragment_id(value: Any, name: str = "fragment_id") -> str:
    text = _text(value, name)
    if _FRAGMENT_ID_RE.fullmatch(text) is None:
        raise UntrustedInputError(f"{name} must match {_FRAGMENT_ID_RE.pattern}")
    return text


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise UntrustedInputError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise UntrustedInputError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise UntrustedInputError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise UntrustedInputError(f"{name} must be a nonnegative integer")
    return value


def _repo_path(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_PATH_CHARS)
    if text.startswith("/") or text.startswith("\\"):
        raise UntrustedInputError(f"{name} must be a relative repository path")
    if text.startswith("~") or ".." in text.split("/"):
        raise UntrustedInputError(f"{name} rejects parent traversal or home paths")
    if "\\" in text or "\x00" in text:
        raise UntrustedInputError(f"{name} contains invalid path characters")
    if _REPO_PATH_RE.fullmatch(text) is None:
        raise UntrustedInputError(f"{name} is not a bounded relative path")
    return text


def _optional_repo_path(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _repo_path(value, name)


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise UntrustedInputError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise UntrustedInputError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise UntrustedInputError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_and_model_authority(thawed, path=name)
    except SemanticGovernorBaseError as exc:
        raise UntrustedInputError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UntrustedInputError(f"{name} must be a mapping")
    return _freeze_structured(_require_structured(dict(value), name))


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    max_items: int,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise UntrustedInputError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > max_items:
        raise UntrustedInputError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise UntrustedInputError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise UntrustedInputError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise UntrustedInputError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise UntrustedInputError(f"{name} must not contain duplicates")
    return ordered


def _content_digest(text: str) -> str:
    return cid_for_bytes(text.encode("utf-8"))


def _sha256_hex(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _bounded_preview(text: str, start: int, end: int) -> str:
    """Build a printable, bounded preview of a match span (audit only)."""

    span = text[start:end]
    # Collapse whitespace for stable previews; strip control newlines.
    collapsed = " ".join(span.split())
    if len(collapsed) > MAX_EXCERPT_PREVIEW_CHARS:
        collapsed = collapsed[: MAX_EXCERPT_PREVIEW_CHARS - 1] + "…"
    # Ensure printable NFC for durable storage.
    preview = unicodedata.normalize("NFC", collapsed)
    # Replace any remaining non-printable with '?'.
    cleaned = "".join(
        char if char.isprintable() else "?" for char in preview
    )
    return cleaned


def _line_number_at(text: str, offset: int) -> int:
    if offset < 0:
        return 1
    return text.count("\n", 0, min(offset, len(text))) + 1


# ---------------------------------------------------------------------------
# Input fragment (scan-time view; body is not durable evidence)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UntrustedInputFragment:
    """One untrusted text surface to scan.

    ``content`` is accepted at scan time only. Durable evidence stores digests
    and bounded previews — never full private source under private field names.
    """

    fragment_id: str
    source_kind: UntrustedSourceKind | str
    content: str
    path: str | None = None
    metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fragment_id", _fragment_id(self.fragment_id, "fragment_id")
        )
        object.__setattr__(
            self,
            "source_kind",
            _enum(self.source_kind, UntrustedSourceKind, "source_kind"),
        )
        object.__setattr__(self, "content", _scan_text(self.content, "content"))
        object.__setattr__(self, "path", _optional_repo_path(self.path, "path"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def content_digest(self) -> str:
        return _content_digest(self.content)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": UNTRUSTED_INPUT_FRAGMENT_SCHEMA,
            "fragment_id": self.fragment_id,
            "source_kind": self.source_kind,
            "content_digest": self.content_digest,
            "path": self.path,
            "metadata": _thaw_structured(self.metadata),
            "char_count": len(self.content),
        }

    @property
    def fragment_cid(self) -> str:
        return cid_for_structured(self.identity_payload())


# ---------------------------------------------------------------------------
# Match / evidence records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstructionLikeMatch:
    """One bounded instruction-like match inside an untrusted fragment."""

    match_id: str
    fragment_id: str
    source_kind: UntrustedSourceKind | str
    pattern_id: InstructionLikePatternId | str
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    excerpt_digest: str
    excerpt_preview: str
    path: str | None = None
    content_digest: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "match_id",
            "fragment_id",
            "source_kind",
            "pattern_id",
            "char_start",
            "char_end",
            "line_start",
            "line_end",
            "excerpt_digest",
            "excerpt_preview",
            "path",
            "content_digest",
            "match_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "match_id", _token(self.match_id, "match_id"))
        object.__setattr__(
            self, "fragment_id", _fragment_id(self.fragment_id, "fragment_id")
        )
        object.__setattr__(
            self,
            "source_kind",
            _enum(self.source_kind, UntrustedSourceKind, "source_kind"),
        )
        object.__setattr__(
            self,
            "pattern_id",
            _enum(self.pattern_id, InstructionLikePatternId, "pattern_id"),
        )
        start = _nonneg_int(self.char_start, "char_start")
        end = _nonneg_int(self.char_end, "char_end")
        if end <= start:
            raise UntrustedInputError("char_end must be greater than char_start")
        if end - start > MAX_FRAGMENT_CHARS:
            raise UntrustedInputError("match span exceeds maximum length")
        object.__setattr__(self, "char_start", start)
        object.__setattr__(self, "char_end", end)
        line_start = _nonneg_int(self.line_start, "line_start")
        line_end = _nonneg_int(self.line_end, "line_end")
        if line_start < 1 or line_end < line_start:
            raise UntrustedInputError("line range must be 1-based and ordered")
        object.__setattr__(self, "line_start", line_start)
        object.__setattr__(self, "line_end", line_end)
        object.__setattr__(
            self,
            "excerpt_digest",
            _cid(self.excerpt_digest, "excerpt_digest"),
        )
        preview = _text(
            self.excerpt_preview,
            "excerpt_preview",
            max_chars=MAX_EXCERPT_PREVIEW_CHARS + 1,
        )
        object.__setattr__(self, "excerpt_preview", preview)
        object.__setattr__(self, "path", _optional_repo_path(self.path, "path"))
        object.__setattr__(
            self,
            "content_digest",
            _optional_cid(self.content_digest, "content_digest"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": INSTRUCTION_LIKE_MATCH_SCHEMA,
            "match_id": self.match_id,
            "fragment_id": self.fragment_id,
            "source_kind": self.source_kind,
            "pattern_id": self.pattern_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "excerpt_digest": self.excerpt_digest,
            "excerpt_preview": self.excerpt_preview,
            "path": self.path,
            "content_digest": self.content_digest,
        }

    @property
    def match_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["match_cid"] = self.match_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InstructionLikeMatch":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("match_cid")
        if payload.pop("schema") != INSTRUCTION_LIKE_MATCH_SCHEMA:
            raise UntrustedInputError(
                "unsupported InstructionLikeMatch schema version"
            )
        result = cls(
            match_id=payload["match_id"],
            fragment_id=payload["fragment_id"],
            source_kind=payload["source_kind"],
            pattern_id=payload["pattern_id"],
            char_start=payload["char_start"],
            char_end=payload["char_end"],
            line_start=payload["line_start"],
            line_end=payload["line_end"],
            excerpt_digest=payload["excerpt_digest"],
            excerpt_preview=payload["excerpt_preview"],
            path=payload["path"],
            content_digest=payload["content_digest"],
        )
        if claimed != result.match_cid:
            raise UntrustedInputError(
                "InstructionLikeMatch match_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class UntrustedInstructionEvidence:
    """Bounded quarantine evidence for instruction-like untrusted content.

    This record is audit-only. It must not be used as an authority source for
    routing, verification, policy, keys, promotion, or any protected domain.
    """

    evidence_id: str
    task_id: str
    disposition: QuarantineDisposition | str
    matches: Sequence[InstructionLikeMatch]
    fragment_cids: Sequence[str]
    scanned_fragment_count: int
    match_count: int
    pattern_ids: Sequence[str]
    source_kinds: Sequence[str]
    protected_domains: Sequence[str] = PROTECTED_DECISION_DOMAINS
    authority_source: AuthoritySource | str = AuthoritySource.DETERMINISTIC
    execution_mode: ExecutionMode | str = ExecutionMode.LIVE
    repository_state_cid: str | None = None
    policy_cid: str | None = None
    truncated: bool = False
    notes: str | None = None
    metadata: Mapping[str, Any] = MappingProxyType({})

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "evidence_id",
            "task_id",
            "disposition",
            "matches",
            "fragment_cids",
            "scanned_fragment_count",
            "match_count",
            "pattern_ids",
            "source_kinds",
            "protected_domains",
            "authority_source",
            "execution_mode",
            "repository_state_cid",
            "policy_cid",
            "truncated",
            "notes",
            "metadata",
            "generator_id",
            "generator_version",
            "tool_id",
            "evidence_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _token(self.evidence_id, "evidence_id")
        )
        object.__setattr__(self, "task_id", _task_id(self.task_id, "task_id"))
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, QuarantineDisposition, "disposition"),
        )
        if not isinstance(self.matches, (list, tuple)):
            raise UntrustedInputError("matches must be a list")
        if len(self.matches) > MAX_MATCHES:
            raise UntrustedInputError("matches exceeds maximum length")
        sealed_matches: list[InstructionLikeMatch] = []
        for index, item in enumerate(self.matches):
            if isinstance(item, InstructionLikeMatch):
                sealed_matches.append(item)
            elif isinstance(item, Mapping):
                sealed_matches.append(InstructionLikeMatch.from_dict(item))
            else:
                raise UntrustedInputError(
                    f"matches[{index}] must be InstructionLikeMatch or mapping"
                )
        # Deterministic order: char offsets within fragment, then pattern, id.
        sealed_matches.sort(
            key=lambda m: (
                m.fragment_id,
                m.char_start,
                m.char_end,
                m.pattern_id,
                m.match_id,
            )
        )
        object.__setattr__(self, "matches", tuple(sealed_matches))
        object.__setattr__(
            self,
            "fragment_cids",
            _unique_sorted_cids(list(self.fragment_cids), "fragment_cids"),
        )
        scanned = _nonneg_int(self.scanned_fragment_count, "scanned_fragment_count")
        if scanned > MAX_FRAGMENTS:
            raise UntrustedInputError("scanned_fragment_count exceeds maximum")
        object.__setattr__(self, "scanned_fragment_count", scanned)
        match_count = _nonneg_int(self.match_count, "match_count")
        if match_count != len(self.matches) and not self.truncated:
            # When not truncated, declared count must equal sealed matches.
            raise UntrustedInputError(
                "match_count must equal len(matches) unless truncated"
            )
        if match_count < len(self.matches):
            raise UntrustedInputError(
                "match_count cannot be less than sealed matches"
            )
        object.__setattr__(self, "match_count", match_count)
        pattern_ids = _unique_sorted_tokens(
            list(self.pattern_ids), "pattern_ids", max_items=MAX_PATTERN_IDS
        )
        derived_patterns = tuple(
            sorted({match.pattern_id for match in self.matches})
        )
        if pattern_ids != derived_patterns:
            raise UntrustedInputError(
                "pattern_ids must equal the sorted unique match pattern ids"
            )
        object.__setattr__(self, "pattern_ids", pattern_ids)
        source_kinds = _unique_sorted_tokens(
            list(self.source_kinds), "source_kinds", max_items=64
        )
        # Source kinds may include scanned kinds even without matches.
        for kind in source_kinds:
            try:
                UntrustedSourceKind(kind)
            except ValueError as exc:
                raise UntrustedInputError(
                    f"source_kinds has unsupported value {kind!r}"
                ) from exc
        object.__setattr__(self, "source_kinds", source_kinds)
        domains = _unique_sorted_tokens(
            list(self.protected_domains),
            "protected_domains",
            max_items=MAX_REASON_CODES,
        )
        if not domains:
            raise UntrustedInputError("protected_domains must not be empty")
        object.__setattr__(self, "protected_domains", domains)
        object.__setattr__(
            self,
            "authority_source",
            _enum(self.authority_source, AuthoritySource, "authority_source"),
        )
        if self.authority_source != AuthoritySource.DETERMINISTIC.value:
            raise UntrustedInputError(
                "UntrustedInstructionEvidence authority_source must be deterministic"
            )
        object.__setattr__(
            self,
            "execution_mode",
            _enum(self.execution_mode, ExecutionMode, "execution_mode"),
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _optional_cid(self.repository_state_cid, "repository_state_cid"),
        )
        object.__setattr__(
            self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid")
        )
        object.__setattr__(self, "truncated", _bool(self.truncated, "truncated"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        if self.matches and self.disposition == QuarantineDisposition.CLEAN.value:
            raise UntrustedInputError(
                "disposition cannot be clean when matches are present"
            )
        if (
            not self.matches
            and not self.truncated
            and self.disposition == QuarantineDisposition.QUARANTINED.value
        ):
            raise UntrustedInputError(
                "disposition cannot be quarantined without matches"
            )
        if self.truncated and self.disposition != QuarantineDisposition.TRUNCATED.value:
            raise UntrustedInputError(
                "truncated evidence must use disposition truncated"
            )
        if (
            not self.truncated
            and not self.matches
            and self.disposition != QuarantineDisposition.CLEAN.value
        ):
            raise UntrustedInputError(
                "empty match set without truncation must be disposition clean"
            )

    @property
    def has_instruction_like_content(self) -> bool:
        return self.match_count > 0 or bool(self.matches)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": UNTRUSTED_INSTRUCTION_EVIDENCE_SCHEMA,
            "interface_id": UNTRUSTED_INSTRUCTION_EVIDENCE_INTERFACE,
            "evidence_id": self.evidence_id,
            "task_id": self.task_id,
            "disposition": self.disposition,
            "matches": [match.identity_payload() for match in self.matches],
            "fragment_cids": list(self.fragment_cids),
            "scanned_fragment_count": self.scanned_fragment_count,
            "match_count": self.match_count,
            "pattern_ids": list(self.pattern_ids),
            "source_kinds": list(self.source_kinds),
            "protected_domains": list(self.protected_domains),
            "authority_source": self.authority_source,
            "execution_mode": self.execution_mode,
            "repository_state_cid": self.repository_state_cid,
            "policy_cid": self.policy_cid,
            "truncated": self.truncated,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "tool_id": TOOL_ID,
        }

    @property
    def evidence_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        # Durable form embeds sealed match envelopes (with match_cid).
        value["matches"] = [match.to_dict() for match in self.matches]
        value["evidence_cid"] = self.evidence_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UntrustedInstructionEvidence":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("evidence_cid")
        if payload.pop("schema") != UNTRUSTED_INSTRUCTION_EVIDENCE_SCHEMA:
            raise UntrustedInputError(
                "unsupported UntrustedInstructionEvidence schema version"
            )
        if payload.pop("interface_id") != UNTRUSTED_INSTRUCTION_EVIDENCE_INTERFACE:
            raise UntrustedInputError(
                "unsupported UntrustedInstructionEvidence interface pin"
            )
        if payload.pop("generator_id") != GENERATOR_ID:
            raise UntrustedInputError("unexpected generator_id")
        if payload.pop("generator_version") != GENERATOR_VERSION:
            raise UntrustedInputError("unexpected generator_version")
        if payload.pop("tool_id") != TOOL_ID:
            raise UntrustedInputError("unexpected tool_id")
        matches_raw = payload.pop("matches")
        result = cls(
            evidence_id=payload["evidence_id"],
            task_id=payload["task_id"],
            disposition=payload["disposition"],
            matches=matches_raw,
            fragment_cids=payload["fragment_cids"],
            scanned_fragment_count=payload["scanned_fragment_count"],
            match_count=payload["match_count"],
            pattern_ids=payload["pattern_ids"],
            source_kinds=payload["source_kinds"],
            protected_domains=payload["protected_domains"],
            authority_source=payload["authority_source"],
            execution_mode=payload["execution_mode"],
            repository_state_cid=payload["repository_state_cid"],
            policy_cid=payload["policy_cid"],
            truncated=payload["truncated"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.evidence_cid:
            raise UntrustedInputError(
                "UntrustedInstructionEvidence evidence_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Trusted decision channel (immune to untrusted text)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrustedDecisionConfig:
    """Trusted configuration for deterministic governor decisions.

    Only values constructed through this type participate in decisions.
    Strings that appear inside untrusted fragments never populate these fields.
    """

    route_tier: str
    promote: bool
    verification_required: bool
    allow_private_source_disclosure: bool
    sampling_deterministic: bool
    policy_cid: str | None = None
    authorization_cid: str | None = None
    proof_system_id: str = "default"
    notes: str | None = None

    _ALLOWED_ROUTE_TIERS: ClassVar[frozenset[str]] = frozenset(
        {
            "deterministic",
            "small",
            "medium",
            "frontier",
            "human",
        }
    )

    def __post_init__(self) -> None:
        route = _token(self.route_tier, "route_tier")
        if route not in self._ALLOWED_ROUTE_TIERS:
            raise UntrustedInputError(
                f"route_tier has unsupported value {route!r}"
            )
        object.__setattr__(self, "route_tier", route)
        object.__setattr__(self, "promote", _bool(self.promote, "promote"))
        object.__setattr__(
            self,
            "verification_required",
            _bool(self.verification_required, "verification_required"),
        )
        object.__setattr__(
            self,
            "allow_private_source_disclosure",
            _bool(
                self.allow_private_source_disclosure,
                "allow_private_source_disclosure",
            ),
        )
        object.__setattr__(
            self,
            "sampling_deterministic",
            _bool(self.sampling_deterministic, "sampling_deterministic"),
        )
        object.__setattr__(
            self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid")
        )
        object.__setattr__(
            self,
            "authorization_cid",
            _optional_cid(self.authorization_cid, "authorization_cid"),
        )
        object.__setattr__(
            self, "proof_system_id", _token(self.proof_system_id, "proof_system_id")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TRUSTED_DECISION_CONFIG_SCHEMA,
            "route_tier": self.route_tier,
            "promote": self.promote,
            "verification_required": self.verification_required,
            "allow_private_source_disclosure": self.allow_private_source_disclosure,
            "sampling_deterministic": self.sampling_deterministic,
            "policy_cid": self.policy_cid,
            "authorization_cid": self.authorization_cid,
            "proof_system_id": self.proof_system_id,
            "notes": self.notes,
        }

    @property
    def config_cid(self) -> str:
        return cid_for_structured(self.identity_payload())


@dataclass(frozen=True, slots=True)
class DeterministicDecision:
    """Decision derived solely from trusted configuration."""

    action: DecisionAction | str
    route_tier: str
    promote: bool
    verification_required: bool
    allow_private_source_disclosure: bool
    sampling_deterministic: bool
    proof_system_id: str
    policy_cid: str | None
    authorization_cid: str | None
    config_cid: str
    evidence_cid: str | None
    untrusted_ignored: bool
    protected_domains: Sequence[str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action", _enum(self.action, DecisionAction, "action")
        )
        object.__setattr__(self, "route_tier", _token(self.route_tier, "route_tier"))
        object.__setattr__(self, "promote", _bool(self.promote, "promote"))
        object.__setattr__(
            self,
            "verification_required",
            _bool(self.verification_required, "verification_required"),
        )
        object.__setattr__(
            self,
            "allow_private_source_disclosure",
            _bool(
                self.allow_private_source_disclosure,
                "allow_private_source_disclosure",
            ),
        )
        object.__setattr__(
            self,
            "sampling_deterministic",
            _bool(self.sampling_deterministic, "sampling_deterministic"),
        )
        object.__setattr__(
            self, "proof_system_id", _token(self.proof_system_id, "proof_system_id")
        )
        object.__setattr__(
            self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid")
        )
        object.__setattr__(
            self,
            "authorization_cid",
            _optional_cid(self.authorization_cid, "authorization_cid"),
        )
        object.__setattr__(self, "config_cid", _cid(self.config_cid, "config_cid"))
        object.__setattr__(
            self, "evidence_cid", _optional_cid(self.evidence_cid, "evidence_cid")
        )
        object.__setattr__(
            self, "untrusted_ignored", _bool(self.untrusted_ignored, "untrusted_ignored")
        )
        object.__setattr__(
            self,
            "protected_domains",
            _unique_sorted_tokens(
                list(self.protected_domains),
                "protected_domains",
                max_items=MAX_REASON_CODES,
            ),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DETERMINISTIC_DECISION_SCHEMA,
            "action": self.action,
            "route_tier": self.route_tier,
            "promote": self.promote,
            "verification_required": self.verification_required,
            "allow_private_source_disclosure": self.allow_private_source_disclosure,
            "sampling_deterministic": self.sampling_deterministic,
            "proof_system_id": self.proof_system_id,
            "policy_cid": self.policy_cid,
            "authorization_cid": self.authorization_cid,
            "config_cid": self.config_cid,
            "evidence_cid": self.evidence_cid,
            "untrusted_ignored": self.untrusted_ignored,
            "protected_domains": list(self.protected_domains),
        }

    @property
    def decision_cid(self) -> str:
        return cid_for_structured(self.identity_payload())


# ---------------------------------------------------------------------------
# Detection / quarantine
# ---------------------------------------------------------------------------


def instruction_like_pattern_ids() -> tuple[str, ...]:
    """Return the closed instruction-like pattern catalog in stable order."""

    return tuple(pattern_id for pattern_id, _ in _PATTERN_CATALOG)


def untrusted_source_kinds() -> tuple[str, ...]:
    """Return the closed untrusted source-kind vocabulary."""

    return tuple(item.value for item in UntrustedSourceKind)


def protected_decision_domains() -> tuple[str, ...]:
    """Return domains that untrusted content must never control."""

    return PROTECTED_DECISION_DOMAINS


def detect_instruction_like_interface_id() -> str:
    """Return the versioned public interface pin for detection."""

    return DETECT_INSTRUCTION_LIKE_CONTENT_INTERFACE


def _scan_fragment(fragment: UntrustedInputFragment) -> list[InstructionLikeMatch]:
    text = fragment.content
    found: list[InstructionLikeMatch] = []
    for pattern_id, regex in _PATTERN_CATALOG:
        for match in regex.finditer(text):
            start, end = match.start(), match.end()
            if end <= start:
                continue
            excerpt = text[start:end]
            preview = _bounded_preview(text, start, end)
            match_id = (
                f"m_{fragment.fragment_id}_{pattern_id}_"
                f"{start}_{end}"
            )
            # match_id must be a lowercase token; normalize.
            match_id = re.sub(r"[^a-z0-9_.:/+-]", "_", match_id.lower())
            if not match_id[0].isalpha():
                match_id = f"m_{match_id}"
            match_id = match_id[:128]
            found.append(
                InstructionLikeMatch(
                    match_id=match_id,
                    fragment_id=fragment.fragment_id,
                    source_kind=fragment.source_kind,
                    pattern_id=pattern_id,
                    char_start=start,
                    char_end=end,
                    line_start=_line_number_at(text, start),
                    line_end=_line_number_at(text, max(end - 1, start)),
                    excerpt_digest=_content_digest(excerpt),
                    excerpt_preview=preview,
                    path=fragment.path,
                    content_digest=fragment.content_digest,
                )
            )
    found.sort(
        key=lambda m: (
            m.fragment_id,
            m.char_start,
            m.char_end,
            m.pattern_id,
            m.match_id,
        )
    )
    return found


def _normalize_fragment(
    value: UntrustedInputFragment | Mapping[str, Any],
    index: int,
) -> UntrustedInputFragment:
    if isinstance(value, UntrustedInputFragment):
        return value
    if isinstance(value, Mapping):
        try:
            return UntrustedInputFragment(
                fragment_id=value.get("fragment_id", f"fragment_{index}"),
                source_kind=value.get("source_kind", UntrustedSourceKind.OTHER),
                content=value.get("content", ""),
                path=value.get("path"),
                metadata=value.get("metadata", {}),
            )
        except UntrustedInputError:
            raise
        except Exception as exc:
            raise UntrustedInputError(
                f"fragments[{index}] is not a valid untrusted fragment"
            ) from exc
    raise UntrustedInputError(
        f"fragments[{index}] must be UntrustedInputFragment or mapping"
    )


def detect_instruction_like_content(
    fragments: Sequence[UntrustedInputFragment | Mapping[str, Any]],
    *,
    task_id: str,
    evidence_id: str = "untrusted_instruction_evidence",
    repository_state_cid: str | None = None,
    policy_cid: str | None = None,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    max_matches: int = MAX_MATCHES,
) -> UntrustedInstructionEvidence:
    """Scan untrusted fragments and return bounded quarantine evidence.

    The returned evidence records instruction-like matches for audit. It does
    not and cannot authorize changes to any protected decision domain.
    """

    if not isinstance(fragments, (list, tuple)):
        raise UntrustedInputError("fragments must be a list")
    if len(fragments) > MAX_FRAGMENTS:
        raise UntrustedInputError("fragments exceeds maximum length")
    if type(max_matches) is not int or isinstance(max_matches, bool):
        raise UntrustedInputError("max_matches must be a positive integer")
    if max_matches < 1 or max_matches > MAX_MATCHES:
        raise UntrustedInputError(
            f"max_matches must be in 1..{MAX_MATCHES}"
        )

    sealed_fragments: list[UntrustedInputFragment] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(fragments):
        fragment = _normalize_fragment(raw, index)
        if fragment.fragment_id in seen_ids:
            raise UntrustedInputError(
                f"duplicate fragment_id {fragment.fragment_id!r}"
            )
        seen_ids.add(fragment.fragment_id)
        sealed_fragments.append(fragment)

    # Stable scan order by fragment_id for deterministic match_id sequences.
    sealed_fragments.sort(key=lambda item: item.fragment_id)

    all_matches: list[InstructionLikeMatch] = []
    for fragment in sealed_fragments:
        all_matches.extend(_scan_fragment(fragment))

    all_matches.sort(
        key=lambda m: (
            m.fragment_id,
            m.char_start,
            m.char_end,
            m.pattern_id,
            m.match_id,
        )
    )

    truncated = len(all_matches) > max_matches
    sealed_matches = all_matches[:max_matches]
    total_match_count = len(all_matches)

    if truncated:
        disposition = QuarantineDisposition.TRUNCATED.value
    elif sealed_matches:
        disposition = QuarantineDisposition.QUARANTINED.value
    else:
        disposition = QuarantineDisposition.CLEAN.value

    pattern_ids = tuple(sorted({match.pattern_id for match in sealed_matches}))
    source_kinds = tuple(
        sorted({fragment.source_kind for fragment in sealed_fragments})
    )
    fragment_cids = tuple(
        sorted({fragment.fragment_cid for fragment in sealed_fragments})
    )

    meta: dict[str, Any] = {
        "scanner_interface": DETECT_INSTRUCTION_LIKE_CONTENT_INTERFACE,
        "pattern_catalog_size": len(_PATTERN_CATALOG),
        "total_match_count": total_match_count,
        "content_digests": sorted(
            {fragment.content_digest for fragment in sealed_fragments}
        ),
    }
    if metadata:
        for key, value in dict(metadata).items():
            if key in meta:
                continue
            meta[key] = value

    return UntrustedInstructionEvidence(
        evidence_id=evidence_id,
        task_id=task_id,
        disposition=disposition,
        matches=sealed_matches,
        fragment_cids=fragment_cids,
        scanned_fragment_count=len(sealed_fragments),
        match_count=total_match_count if truncated else len(sealed_matches),
        pattern_ids=pattern_ids,
        source_kinds=source_kinds,
        protected_domains=PROTECTED_DECISION_DOMAINS,
        authority_source=AuthoritySource.DETERMINISTIC,
        execution_mode=ExecutionMode.LIVE,
        repository_state_cid=repository_state_cid,
        policy_cid=policy_cid,
        truncated=truncated,
        notes=notes,
        metadata=meta,
    )


def apply_trusted_decision(
    config: TrustedDecisionConfig,
    *,
    evidence: UntrustedInstructionEvidence | None = None,
    untrusted_text: str | None = None,
    untrusted_overrides: Mapping[str, Any] | None = None,
) -> DeterministicDecision:
    """Derive a deterministic decision from trusted configuration only.

    ``evidence``, ``untrusted_text``, and ``untrusted_overrides`` are accepted
    so callers can attach audit context, but they are never consulted when
    computing action, route, promotion, verification, disclosure, sampling,
    policy, authorization, or proof-system fields.

    Injection strings that mimic trusted configuration or authorization
    therefore cannot alter the decision.
    """

    if not isinstance(config, TrustedDecisionConfig):
        raise UntrustedInputError(
            "config must be a TrustedDecisionConfig instance"
        )

    # Explicitly ignore untrusted channels (bound for audit side-effects only).
    _ = untrusted_text
    _ = untrusted_overrides
    evidence_cid: str | None = None
    if evidence is not None:
        if not isinstance(evidence, UntrustedInstructionEvidence):
            raise UntrustedInputError(
                "evidence must be UntrustedInstructionEvidence or None"
            )
        evidence_cid = evidence.evidence_cid

    # Decision logic uses only trusted fields.
    if config.promote and config.authorization_cid is None:
        action = DecisionAction.REJECT.value
    elif not config.verification_required:
        # Verification cannot be disabled by untrusted text; only trusted
        # config may set this, and when false we still mark review rather
        # than silently accepting unverified promotion paths.
        action = DecisionAction.REQUIRE_HUMAN_REVIEW.value
    else:
        action = DecisionAction.CONTINUE.value

    return DeterministicDecision(
        action=action,
        route_tier=config.route_tier,
        promote=config.promote,
        verification_required=config.verification_required,
        allow_private_source_disclosure=config.allow_private_source_disclosure,
        sampling_deterministic=config.sampling_deterministic,
        proof_system_id=config.proof_system_id,
        policy_cid=config.policy_cid,
        authorization_cid=config.authorization_cid,
        config_cid=config.config_cid,
        evidence_cid=evidence_cid,
        untrusted_ignored=True,
        protected_domains=PROTECTED_DECISION_DOMAINS,
    )


def reject_untrusted_authority_claims(value: Any, *, path: str = "$") -> None:
    """Fail closed if a mapping asserts authority from untrusted/model channels."""

    try:
        reject_private_and_model_authority(value, path=path)
    except SemanticGovernorBaseError as exc:
        raise UntrustedInputError(str(exc)) from exc
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {
                "untrusted_authority",
                "instruction_authority",
                "prompt_authority",
                "comment_authority",
                "fixture_authority",
            }:
                raise UntrustedInputError(
                    f"{path}.{key} rejects untrusted authority field"
                )
            reject_untrusted_authority_claims(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_untrusted_authority_claims(item, path=f"{path}[{index}]")


def evidence_cannot_mutate_config(
    config: TrustedDecisionConfig,
    evidence: UntrustedInstructionEvidence,
) -> TrustedDecisionConfig:
    """Return the original trusted config; evidence never mutates it.

    Exists as an explicit fail-closed seam for callers and tests.
    """

    if not isinstance(config, TrustedDecisionConfig):
        raise UntrustedInputError("config must be TrustedDecisionConfig")
    if not isinstance(evidence, UntrustedInstructionEvidence):
        raise UntrustedInputError("evidence must be UntrustedInstructionEvidence")
    # Touch evidence so the binding is intentional, then return config unchanged.
    _ = evidence.evidence_cid
    return config


__all__ = [
    "DETECT_INSTRUCTION_LIKE_CONTENT_INTERFACE",
    "DETERMINISTIC_DECISION_SCHEMA",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "INSTRUCTION_LIKE_MATCH_SCHEMA",
    "MAX_EXCERPT_PREVIEW_CHARS",
    "MAX_FRAGMENTS",
    "MAX_MATCHES",
    "PROTECTED_DECISION_DOMAINS",
    "PRODUCER_ID",
    "PRODUCER_VERSION",
    "TOOL_ID",
    "TRUSTED_DECISION_CONFIG_SCHEMA",
    "UNTRUSTED_INPUT_FRAGMENT_SCHEMA",
    "UNTRUSTED_INSTRUCTION_EVIDENCE_INTERFACE",
    "UNTRUSTED_INSTRUCTION_EVIDENCE_SCHEMA",
    "DecisionAction",
    "DeterministicDecision",
    "InstructionLikeMatch",
    "InstructionLikePatternId",
    "QuarantineDisposition",
    "TrustedDecisionConfig",
    "UntrustedInputError",
    "UntrustedInputFragment",
    "UntrustedInstructionEvidence",
    "UntrustedSourceKind",
    "apply_trusted_decision",
    "detect_instruction_like_content",
    "detect_instruction_like_interface_id",
    "evidence_cannot_mutate_config",
    "instruction_like_pattern_ids",
    "protected_decision_domains",
    "reject_untrusted_authority_claims",
    "untrusted_source_kinds",
]
