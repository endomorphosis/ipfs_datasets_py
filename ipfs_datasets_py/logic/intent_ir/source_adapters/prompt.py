"""Safe, deterministic Intent source adapter for free-form prompts.

Prompts are untrusted external data.  This adapter bounds text, computes a
stable content identity, classifies hostile input without executing or
following any instructions in the prompt, and only emits IntentIR-compatible
records when policy permits content use.

Non-goals (fail-closed invariants):
- Never treat prompt text as trusted instructions for this process.
- Never execute shell/tool markup found in prompt bodies.
- Never rewrite or sanitize adversarial content into a "clean" body; quarantine
  or exclude instead so callers retain the original bytes for review.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Pattern
from urllib.parse import quote

from multiformats import CID

from ...ir_core.identity import identity_preimage
from ...profile_g import validate_cid
from ..schema import (
    IntentAction,
    IntentIRDocument,
    IntentKind,
    IntentModality,
    IntentStatement,
    NodeGrounding,
    ReviewStatus,
    SourceRef,
    SourceSpan,
    StatementKind,
    validate_intent_ir,
)
from ....utils.cid_utils import cid_for_bytes


PROMPT_INTENT_ADAPTER = "PromptIntentAdapter@1"
PROMPT_ENTRY_IDENTITY_SCHEMA_VERSION = "prompt-entry-identity/v1"
PROMPT_ENTRY_IDENTITY_DOMAIN = "intent-ir.prompt-entry"
PROMPT_SOURCE_POLICY_VERSION = "prompt-source-policy/v1"
PROMPT_RECORD_SCHEMA_VERSION = "prompt-source-record/v1"
DEFAULT_MAX_TEXT_CHARS = 1_000_000
DEFAULT_MAX_TITLE_CHARS = 512
DEFAULT_MAX_METADATA_CHARS = 64_000
MAX_FINDINGS_PER_DETECTOR = 64
MAX_TAGS = 64
MAX_TAG_CHARS = 128

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BASE64_BLOCK_RE = re.compile(
    r"(?:^|\s)(?:[A-Za-z0-9+/]{256,}={0,2})(?:\s|$)", re.MULTILINE
)
_SPACE_RE = re.compile(r"\s+")


class PromptSourceError(ValueError):
    """Raised when a prompt record or adapt request is invalid."""


class PromptRecordError(PromptSourceError):
    """Raised when a prompt body is malformed or exceeds safety bounds."""


class PromptPolicyError(PromptSourceError):
    """Raised when policy prohibits content use (fail closed)."""

    def __init__(self, decision: "PromptSourcePolicyDecision") -> None:
        self.decision = decision
        super().__init__(
            "Prompt is not eligible for content normalization: "
            f"{decision.allowed_use.value}"
        )


class AllowedUseDecision(str, Enum):
    """Maximum permitted use for one prompt record."""

    ALLOW_INTERNAL_EVALUATION = "allow_internal_evaluation"
    METADATA_ONLY = "metadata_only"
    QUARANTINED_UNKNOWN = "quarantined_unknown"
    EXCLUDED = "excluded"


class TrustDecision(str, Enum):
    """Trust state kept separate from allowed-use decisions."""

    UNTRUSTED = "untrusted"
    QUARANTINED = "quarantined"


class FindingCategory(str, Enum):
    """Classes of hostile or sensitive prompt data."""

    SECRET = "secret"
    PERSONAL_DATA = "personal_data"
    PROMPT_INJECTION = "prompt_injection"
    TOOL_DIRECTIVE = "tool_directive"
    UNSAFE_METADATA = "unsafe_metadata"
    GENERATED_BINARY = "generated_binary"


class FindingDecision(str, Enum):
    """Outcome for one family of detectors."""

    CLEAR = "clear"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class PromptPolicyFinding:
    """Non-sensitive pointer to a policy match (matched text omitted)."""

    category: FindingCategory
    code: str
    field: str
    start_char: int
    end_char: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "code": self.code,
            "end_char": self.end_char,
            "field": self.field,
            "start_char": self.start_char,
        }


@dataclass(frozen=True, slots=True)
class PromptSourcePolicyDecision:
    """Complete fail-closed policy result for one prompt record."""

    prompt_id: str
    policy_version: str
    allowed_use: AllowedUseDecision
    trust_decision: TrustDecision
    findings: tuple[PromptPolicyFinding, ...] = ()

    @property
    def hostile_input_decision(self) -> FindingDecision:
        if any(
            finding.category
            in {
                FindingCategory.PROMPT_INJECTION,
                FindingCategory.TOOL_DIRECTIVE,
                FindingCategory.GENERATED_BINARY,
            }
            for finding in self.findings
        ):
            return FindingDecision.QUARANTINED
        return FindingDecision.CLEAR

    @property
    def secret_pii_decision(self) -> FindingDecision:
        if any(
            finding.category
            in {FindingCategory.SECRET, FindingCategory.PERSONAL_DATA}
            for finding in self.findings
        ):
            return FindingDecision.QUARANTINED
        return FindingDecision.CLEAR

    @property
    def review_status(self) -> ReviewStatus:
        if self.trust_decision is TrustDecision.QUARANTINED:
            return ReviewStatus.QUARANTINED
        return ReviewStatus.UNREVIEWED

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_use": self.allowed_use.value,
            "findings": [finding.to_dict() for finding in self.findings],
            "hostile_input_decision": self.hostile_input_decision.value,
            "policy_version": self.policy_version,
            "prompt_id": self.prompt_id,
            "secret_pii_decision": self.secret_pii_decision.value,
            "trust_decision": self.trust_decision.value,
        }


@dataclass(frozen=True, slots=True)
class PromptEntryIdentity:
    """Multiformats identity for one container-independent prompt entry."""

    cid: str
    cid_bytes: bytes
    multihash_bytes: bytes
    sha256: str
    identity_schema_version: str = PROMPT_ENTRY_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            decoded = CID.decode(self.cid)
        except (TypeError, ValueError) as exc:
            raise PromptRecordError("entry identity CID is malformed") from exc
        if (
            decoded.version != 1
            or decoded.codec.name != "raw"
            or decoded.hashfun.name != "sha2-256"
            or bytes(decoded) != self.cid_bytes
            or bytes(decoded.digest) != self.multihash_bytes
            or decoded.raw_digest.hex() != self.sha256
        ):
            raise PromptRecordError(
                "entry identity does not use CIDv1/raw/sha2-256 consistently"
            )
        if self.identity_schema_version != PROMPT_ENTRY_IDENTITY_SCHEMA_VERSION:
            raise PromptRecordError("entry identity schema version is unsupported")

    def to_dict(self) -> dict[str, str]:
        return {
            "cid": self.cid,
            "identity_schema_version": self.identity_schema_version,
            "multibase": "base32",
            "multicodec": "raw",
            "multihash": "sha2-256",
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class PromptRecord:
    """One bounded free-form prompt body with explicit provenance."""

    text: str
    title: str = ""
    source_uri: str = ""
    source_id: str = ""
    source_revision: str = "unpinned"
    language: str = "en"
    tags: tuple[str, ...] = ()
    metadata_json: str = "{}"
    schema_version: str = PROMPT_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        text = _require_text(self.text, "text")
        title = _optional_text(self.title, "title")
        source_uri = _optional_text(self.source_uri, "source_uri")
        source_id = _optional_text(self.source_id, "source_id")
        source_revision = _require_text(self.source_revision, "source_revision")
        language = _require_text(self.language, "language")
        metadata_json = _normalize_metadata_json(self.metadata_json)
        tags = _normalize_tags(self.tags)
        if self.schema_version != PROMPT_RECORD_SCHEMA_VERSION:
            raise PromptRecordError("prompt record schema version is unsupported")
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "source_uri", source_uri)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "source_revision", source_revision)
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "metadata_json", metadata_json)

    @property
    def prompt_id(self) -> str:
        """Stable local identifier derived from the entry identity digest."""

        return f"prompt:{self.entry_identity.sha256[:32]}"

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def intrinsic_payload(self) -> dict[str, Any]:
        """Canonical payload for identity (excludes mutable packaging fields)."""

        return {
            "language": self.language,
            "metadata_json": self.metadata_json,
            "schema_version": self.schema_version,
            "tags": list(self.tags),
            "text": self.text,
            "title": self.title,
        }

    @property
    def entry_identity(self) -> PromptEntryIdentity:
        preimage = identity_preimage(
            self.intrinsic_payload(),
            domain=PROMPT_ENTRY_IDENTITY_DOMAIN,
            schema_version=PROMPT_ENTRY_IDENTITY_SCHEMA_VERSION,
        )
        cid_text = validate_cid(
            cid_for_bytes(
                preimage,
                base="base32",
                codec="raw",
                mh_type="sha2-256",
                version=1,
            ),
            path="/entry_cid",
        )
        cid = CID.decode(cid_text)
        return PromptEntryIdentity(
            cid=str(cid),
            cid_bytes=bytes(cid),
            multihash_bytes=bytes(cid.digest),
            sha256=cid.raw_digest.hex(),
        )

    @property
    def entry_cid(self) -> str:
        return self.entry_identity.cid

    @property
    def content_cid(self) -> str:
        return validate_cid(
            cid_for_bytes(
                self.text.encode("utf-8"),
                base="base32",
                codec="raw",
                mh_type="sha2-256",
                version=1,
            ),
            path="/content_cid",
        )

    def to_source_ref(
        self,
        *,
        review_status: ReviewStatus = ReviewStatus.UNREVIEWED,
        content_cid: str = "",
        span: SourceSpan | None = None,
    ) -> SourceRef:
        encoded_id = quote(self.prompt_id, safe=":")
        source_uri = self.source_uri or f"prompt://local/{encoded_id}"
        source_id = self.source_id or self.prompt_id
        reference_material = (
            f"{source_id}@{self.source_revision}#{self.content_sha256}"
        )
        reference_digest = hashlib.sha256(
            reference_material.encode("utf-8")
        ).hexdigest()
        return SourceRef(
            ref_id=f"prompt:{reference_digest}",
            source_uri=source_uri,
            source_id=source_id,
            source_revision=self.source_revision,
            content_sha256=self.content_sha256,
            container_uri=source_uri,
            container_sha256="",
            content_cid=content_cid or self.content_cid,
            license_expression="",
            review_status=review_status,
            span=span,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_cid": self.entry_cid,
            "language": self.language,
            "metadata_json": self.metadata_json,
            "prompt_id": self.prompt_id,
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_uri": self.source_uri,
            "tags": list(self.tags),
            "text": self.text,
            "title": self.title,
        }


@dataclass(frozen=True, slots=True)
class _Detector:
    category: FindingCategory
    code: str
    pattern: Pattern[str]
    fields: frozenset[str] | None = None


def _pattern(value: str, *, flags: int = re.IGNORECASE | re.MULTILINE) -> Pattern[str]:
    return re.compile(value, flags)


_DETECTORS = (
    _Detector(
        FindingCategory.SECRET,
        "secret.private_key",
        _pattern(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    _Detector(
        FindingCategory.SECRET,
        "secret.aws_access_key",
        _pattern(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])", flags=0),
    ),
    _Detector(
        FindingCategory.SECRET,
        "secret.github_token",
        _pattern(
            r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,255}|"
            r"github_pat_[A-Za-z0-9_]{40,255})(?![A-Za-z0-9])"
        ),
    ),
    _Detector(
        FindingCategory.SECRET,
        "secret.api_token",
        _pattern(
            r"(?<![A-Za-z0-9])(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|"
            r"AIza[A-Za-z0-9_-]{35})(?![A-Za-z0-9])"
        ),
    ),
    _Detector(
        FindingCategory.PERSONAL_DATA,
        "personal.email",
        _pattern(
            r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
            r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
            r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+"
            r"(?![A-Za-z0-9-])"
        ),
    ),
    _Detector(
        FindingCategory.PROMPT_INJECTION,
        "hostile.ignore_instructions",
        _pattern(
            r"\b(?:(?:ignore|disregard|forget)\s+(?:all\s+)?|"
            r"do\s+not\s+(?:obey|follow)\s+)"
            r"(?:previous|prior|above|earlier|system|developer)\s+instructions?\b"
        ),
    ),
    _Detector(
        FindingCategory.PROMPT_INJECTION,
        "hostile.override_prompt",
        _pattern(
            r"\b(?:override|bypass|replace)\s+(?:the\s+)?"
            r"(?:system|developer|safety)\s+(?:prompt|message|instructions?|rules?)\b"
        ),
    ),
    _Detector(
        FindingCategory.PROMPT_INJECTION,
        "hostile.prompt_exfiltration",
        _pattern(
            r"\b(?:reveal|print|show|leak|repeat)\s+(?:the\s+|your\s+)?"
            r"(?:hidden\s+)?(?:system|developer)\s+(?:prompt|message|instructions?)\b"
        ),
    ),
    _Detector(
        FindingCategory.PROMPT_INJECTION,
        "hostile.role_markup",
        _pattern(r"(?:<\s*/?\s*system\s*>|^\s*#{0,3}\s*system\s*:|\[INST\])"),
    ),
    _Detector(
        FindingCategory.TOOL_DIRECTIVE,
        "hostile.tool_call_markup",
        _pattern(
            r"(?:<\s*(?:tool[_ -]?call|function_calls?)\b|"
            r"[\"']tool_calls?[\"']\s*:|"
            r"\b(?:assistant\s+to|recipient)\s*=\s*(?:functions|tools)\.|"
            r"\b(?:functions|tools)\.[A-Za-z_][A-Za-z0-9_]*\s*\()"
        ),
    ),
    _Detector(
        FindingCategory.TOOL_DIRECTIVE,
        "hostile.tool_instruction",
        _pattern(
            r"\b(?:call|invoke|use|execute|run)\s+(?:the\s+)?"
            r"(?:shell|terminal|command|tool|function)\b"
        ),
    ),
    _Detector(
        FindingCategory.TOOL_DIRECTIVE,
        "hostile.pipe_to_shell",
        _pattern(r"\b(?:curl|wget)\b[^\r\n|]{0,500}\|\s*(?:ba|z|k)?sh\b"),
    ),
    _Detector(
        FindingCategory.UNSAFE_METADATA,
        "metadata.template_secret",
        _pattern(
            r"(?:\$\{\{\s*secrets?\.|\{\{\s*(?:secret|env|config)\b|"
            r"\$\{(?:SECRET|TOKEN|PASSWORD|API_KEY)\b)"
        ),
        frozenset({"metadata_json", "title"}),
    ),
)

_TEXT_FIELDS = ("title", "text", "source_uri", "source_id", "metadata_json")
_BLOCKED_ALLOWED_USES = frozenset(
    {
        AllowedUseDecision.METADATA_ONLY,
        AllowedUseDecision.QUARANTINED_UNKNOWN,
        AllowedUseDecision.EXCLUDED,
    }
)


class PromptSourcePolicy:
    """Deterministic, side-effect-free policy for free-form prompts."""

    def __init__(
        self,
        *,
        max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
        max_title_chars: int = DEFAULT_MAX_TITLE_CHARS,
        max_metadata_chars: int = DEFAULT_MAX_METADATA_CHARS,
    ) -> None:
        for name, value in (
            ("max_text_chars", max_text_chars),
            ("max_title_chars", max_title_chars),
            ("max_metadata_chars", max_metadata_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.max_text_chars = max_text_chars
        self.max_title_chars = max_title_chars
        self.max_metadata_chars = max_metadata_chars

    def evaluate(self, record: PromptRecord) -> PromptSourcePolicyDecision:
        if not isinstance(record, PromptRecord):
            raise TypeError("record must be a PromptRecord")
        findings: list[PromptPolicyFinding] = []
        if len(record.text) > self.max_text_chars:
            findings.append(
                PromptPolicyFinding(
                    FindingCategory.UNSAFE_METADATA,
                    "input.scan_limit_exceeded",
                    "text",
                    self.max_text_chars,
                    len(record.text),
                )
            )
        if len(record.title) > self.max_title_chars:
            findings.append(
                PromptPolicyFinding(
                    FindingCategory.UNSAFE_METADATA,
                    "input.scan_limit_exceeded",
                    "title",
                    self.max_title_chars,
                    len(record.title),
                )
            )
        if len(record.metadata_json) > self.max_metadata_chars:
            findings.append(
                PromptPolicyFinding(
                    FindingCategory.UNSAFE_METADATA,
                    "input.scan_limit_exceeded",
                    "metadata_json",
                    self.max_metadata_chars,
                    len(record.metadata_json),
                )
            )
        for field in _TEXT_FIELDS:
            value = getattr(record, field)
            findings.extend(self._scan_field(field, value))
        findings = _deduplicate_and_sort_findings(findings)
        if findings:
            allowed_use = AllowedUseDecision.EXCLUDED
            trust = TrustDecision.QUARANTINED
        else:
            allowed_use = AllowedUseDecision.ALLOW_INTERNAL_EVALUATION
            trust = TrustDecision.UNTRUSTED
        return PromptSourcePolicyDecision(
            prompt_id=record.prompt_id,
            policy_version=PROMPT_SOURCE_POLICY_VERSION,
            allowed_use=allowed_use,
            trust_decision=trust,
            findings=tuple(findings),
        )

    evaluate_record = evaluate

    def _scan_field(self, field: str, value: str) -> list[PromptPolicyFinding]:
        findings: list[PromptPolicyFinding] = []
        scan_limit = {
            "text": self.max_text_chars,
            "title": self.max_title_chars,
            "metadata_json": self.max_metadata_chars,
        }.get(field, self.max_text_chars)
        if len(value) > scan_limit:
            value = value[:scan_limit]
        for detector in _DETECTORS:
            if detector.fields is not None and field not in detector.fields:
                continue
            accepted = 0
            for match in detector.pattern.finditer(value):
                if accepted >= MAX_FINDINGS_PER_DETECTOR:
                    findings.append(
                        PromptPolicyFinding(
                            FindingCategory.UNSAFE_METADATA,
                            "input.detector_matches_truncated",
                            field,
                            0,
                            len(value),
                        )
                    )
                    break
                accepted += 1
                findings.append(
                    PromptPolicyFinding(
                        detector.category,
                        detector.code,
                        field,
                        match.start(),
                        match.end(),
                    )
                )
        for index, match in enumerate(_CONTROL_CHAR_RE.finditer(value)):
            if index >= MAX_FINDINGS_PER_DETECTOR:
                findings.append(
                    PromptPolicyFinding(
                        FindingCategory.UNSAFE_METADATA,
                        "input.detector_matches_truncated",
                        field,
                        0,
                        len(value),
                    )
                )
                break
            category = (
                FindingCategory.UNSAFE_METADATA
                if field != "text"
                else FindingCategory.GENERATED_BINARY
            )
            code = (
                "metadata.control_character"
                if field != "text"
                else "content.control_character"
            )
            findings.append(
                PromptPolicyFinding(
                    category, code, field, match.start(), match.end()
                )
            )
        if field == "text":
            for index, match in enumerate(_BASE64_BLOCK_RE.finditer(value)):
                if index >= MAX_FINDINGS_PER_DETECTOR:
                    findings.append(
                        PromptPolicyFinding(
                            FindingCategory.UNSAFE_METADATA,
                            "input.detector_matches_truncated",
                            field,
                            0,
                            len(value),
                        )
                    )
                    break
                findings.append(
                    PromptPolicyFinding(
                        FindingCategory.GENERATED_BINARY,
                        "content.encoded_binary_block",
                        field,
                        match.start(),
                        match.end(),
                    )
                )
        return findings


class PromptIntentAdapter:
    """Normalize free-form prompts into IntentIR-compatible records.

    Interface: ``PromptIntentAdapter@1``.
    """

    def __init__(
        self,
        *,
        policy: PromptSourcePolicy | None = None,
        max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
    ) -> None:
        if (
            isinstance(max_text_chars, bool)
            or not isinstance(max_text_chars, int)
            or max_text_chars < 1
        ):
            raise ValueError("max_text_chars must be a positive integer")
        if policy is not None and not isinstance(policy, PromptSourcePolicy):
            raise TypeError("policy must be a PromptSourcePolicy")
        self.max_text_chars = max_text_chars
        self.policy = policy or PromptSourcePolicy(max_text_chars=max_text_chars)
        self.interface = PROMPT_INTENT_ADAPTER

    def make_record(
        self,
        text: str,
        *,
        title: str = "",
        source_uri: str = "",
        source_id: str = "",
        source_revision: str = "unpinned",
        language: str = "en",
        tags: Iterable[str] = (),
        metadata: Mapping[str, Any] | str | None = None,
    ) -> PromptRecord:
        """Build a bounded prompt record without interpreting text as instructions."""

        if not isinstance(text, str) or not text.strip():
            raise PromptRecordError("text must be a non-empty string")
        if len(text) > self.max_text_chars:
            raise PromptRecordError("text exceeds max_text_chars")
        metadata_json = "{}"
        if metadata is not None:
            if isinstance(metadata, str):
                metadata_json = metadata
            elif isinstance(metadata, Mapping):
                metadata_json = json.dumps(
                    dict(metadata),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            else:
                raise TypeError("metadata must be a mapping, JSON string, or None")
        return PromptRecord(
            text=text,
            title=title,
            source_uri=source_uri,
            source_id=source_id,
            source_revision=source_revision,
            language=language,
            tags=tuple(tags),
            metadata_json=metadata_json,
        )

    def evaluate(self, record: PromptRecord) -> PromptSourcePolicyDecision:
        return self.policy.evaluate(record)

    def adapt(self, record: PromptRecord) -> IntentIRDocument:
        """Return validated Intent IR or raise :class:`PromptPolicyError`."""

        return self.adapt_with_policy(record)[0]

    def adapt_with_policy(
        self, record: PromptRecord
    ) -> tuple[IntentIRDocument, PromptSourcePolicyDecision]:
        if not isinstance(record, PromptRecord):
            raise TypeError("record must be a PromptRecord")
        if len(record.text) > self.max_text_chars:
            raise PromptRecordError("text exceeds max_text_chars")
        decision = self.policy.evaluate(record)
        if decision.allowed_use in _BLOCKED_ALLOWED_USES:
            raise PromptPolicyError(decision)
        document = _build_prompt_intent_document(record, decision)
        validate_intent_ir(document)
        return document, decision

    # Explicit pipeline spellings.
    normalize = adapt
    normalize_record = adapt_with_policy


def _build_prompt_intent_document(
    record: PromptRecord,
    decision: PromptSourcePolicyDecision,
) -> IntentIRDocument:
    base_source = record.to_source_ref(review_status=decision.review_status)
    base_source.validate()
    goal_text = _normalize_evidence(record.text)
    if not goal_text:
        raise PromptRecordError("prompt text has no usable evidence after normalize")
    span = SourceSpan(0, len(record.text))
    span.validate()
    spanned = record.to_source_ref(
        review_status=decision.review_status,
        span=span,
    )
    statement_id = _stable_id("statement", "goal", 0, len(record.text))
    statement = IntentStatement(
        statement_id=statement_id,
        kind=StatementKind.GOAL,
        modality=IntentModality.INTENDED,
        normalized_text=goal_text,
        source_ref_ids=(spanned.ref_id,),
        grounding=NodeGrounding.GROUNDED,
        review_status=ReviewStatus.MACHINE_EXTRACTED,
    )
    action_id = _stable_id("action", "prompt", 0, len(record.text))
    action = IntentAction(
        action_id=action_id,
        actor="user",
        verb="request",
        object_refs=(),
        source_ref_ids=(spanned.ref_id,),
        grounding=NodeGrounding.GROUNDED,
    )
    title = record.title.strip() or goal_text[:120]
    sources_by_id = {base_source.ref_id: base_source, spanned.ref_id: spanned}
    return IntentIRDocument(
        document_id=record.prompt_id,
        title=title,
        intent_kind=IntentKind.DECLARATIVE,
        sources=tuple(sources_by_id[key] for key in sorted(sources_by_id)),
        statements=(statement,),
        actions=(action,),
        entry_action_ids=(action_id,),
        terminal_action_ids=(action_id,),
        tags=record.tags,
    )


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        # Allow internal whitespace; only reject surrounding whitespace and empty.
        if not isinstance(value, str) or not value.strip():
            raise PromptRecordError(f"{label} must be a non-empty string")
        if value.strip() != value:
            raise PromptRecordError(
                f"{label} must not have surrounding whitespace"
            )
    if "\x00" in value:
        raise PromptRecordError(f"{label} must not contain NUL")
    return value


def _optional_text(value: Any, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PromptRecordError(f"{label} must be a string")
    if value and value.strip() != value:
        raise PromptRecordError(f"{label} must not have surrounding whitespace")
    if "\x00" in value:
        raise PromptRecordError(f"{label} must not contain NUL")
    return value


def _normalize_metadata_json(value: Any) -> str:
    if value is None:
        return "{}"
    if not isinstance(value, str):
        raise PromptRecordError("metadata_json must be a string")
    if "\x00" in value:
        raise PromptRecordError("metadata_json must not contain NUL")
    text = value if value else "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PromptRecordError("metadata_json must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise PromptRecordError("metadata_json must be a JSON object")
    if any(not isinstance(key, str) for key in parsed):
        raise PromptRecordError("metadata_json keys must be strings")
    return json.dumps(parsed, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _normalize_tags(tags: Any) -> tuple[str, ...]:
    if tags is None:
        return ()
    if isinstance(tags, str):
        raise PromptRecordError("tags must be a sequence of strings")
    try:
        items = tuple(tags)
    except TypeError as exc:
        raise PromptRecordError("tags must be a sequence of strings") from exc
    if len(items) > MAX_TAGS:
        raise PromptRecordError(f"tags exceeds maximum of {MAX_TAGS}")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item or item.strip() != item:
            raise PromptRecordError("each tag must be non-empty normalized text")
        if "\x00" in item or len(item) > MAX_TAG_CHARS:
            raise PromptRecordError("tag is malformed or exceeds max length")
        if item not in seen:
            seen.add(item)
            normalized.append(item)
    return tuple(sorted(normalized))


def _normalize_evidence(text: str) -> str:
    return _SPACE_RE.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _stable_id(*parts: Any) -> str:
    material = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    prefix = str(parts[0]) if parts else "node"
    candidate = f"{prefix}:{digest}"
    if not _IDENTIFIER_RE.fullmatch(candidate):
        candidate = f"node:{digest}"
    return candidate


def _deduplicate_and_sort_findings(
    findings: Iterable[PromptPolicyFinding],
) -> list[PromptPolicyFinding]:
    return sorted(
        set(findings),
        key=lambda finding: (
            finding.field,
            finding.start_char,
            finding.end_char,
            finding.category.value,
            finding.code,
        ),
    )


# Convenience alias used by acceptance wording.
ALLOWED_USE_BLOCKED = _BLOCKED_ALLOWED_USES


__all__ = [
    "ALLOWED_USE_BLOCKED",
    "AllowedUseDecision",
    "DEFAULT_MAX_METADATA_CHARS",
    "DEFAULT_MAX_TEXT_CHARS",
    "DEFAULT_MAX_TITLE_CHARS",
    "FindingCategory",
    "FindingDecision",
    "MAX_FINDINGS_PER_DETECTOR",
    "PROMPT_ENTRY_IDENTITY_DOMAIN",
    "PROMPT_ENTRY_IDENTITY_SCHEMA_VERSION",
    "PROMPT_INTENT_ADAPTER",
    "PROMPT_RECORD_SCHEMA_VERSION",
    "PROMPT_SOURCE_POLICY_VERSION",
    "PromptEntryIdentity",
    "PromptIntentAdapter",
    "PromptPolicyError",
    "PromptPolicyFinding",
    "PromptRecord",
    "PromptRecordError",
    "PromptSourceError",
    "PromptSourcePolicy",
    "PromptSourcePolicyDecision",
    "TrustDecision",
]
