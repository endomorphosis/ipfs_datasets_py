"""Safe, deterministic Intent source adapter for MCP tool definitions.

MCP tool schemas and descriptions are untrusted data.  This adapter bounds
payloads, computes a stable content identity, classifies hostile markup without
invoking tools, and only emits IntentIR-compatible records when policy permits
content use.

Non-goals (fail-closed invariants):
- Never execute, invoke, or dispatch the described MCP tool.
- Never follow links, load remote schemas, or evaluate JSON Schema as code.
- Never treat tool description text as trusted process instructions.
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


MCP_TOOL_INTENT_ADAPTER = "MCPToolIntentAdapter@1"
MCP_TOOL_ENTRY_IDENTITY_SCHEMA_VERSION = "mcp-tool-entry-identity/v1"
MCP_TOOL_ENTRY_IDENTITY_DOMAIN = "intent-ir.mcp-tool-entry"
MCP_TOOL_SOURCE_POLICY_VERSION = "mcp-tool-source-policy/v1"
MCP_TOOL_RECORD_SCHEMA_VERSION = "mcp-tool-source-record/v1"
DEFAULT_MAX_TEXT_CHARS = 1_000_000
DEFAULT_MAX_NAME_CHARS = 256
DEFAULT_MAX_SCHEMA_CHARS = 256_000
DEFAULT_MAX_METADATA_CHARS = 64_000
MAX_FINDINGS_PER_DETECTOR = 64
MAX_TAGS = 64
MAX_TAG_CHARS = 128
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 10_000

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,255}$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")


class MCPToolSourceError(ValueError):
    """Raised when an MCP tool record or adapt request is invalid."""


class MCPToolRecordError(MCPToolSourceError):
    """Raised when an MCP tool payload is malformed or exceeds bounds."""


class MCPToolPolicyError(MCPToolSourceError):
    """Raised when policy prohibits content use (fail closed)."""

    def __init__(self, decision: "MCPToolSourcePolicyDecision") -> None:
        self.decision = decision
        super().__init__(
            "MCP tool is not eligible for content normalization: "
            f"{decision.allowed_use.value}"
        )


class AllowedUseDecision(str, Enum):
    """Maximum permitted use for one MCP tool record."""

    ALLOW_INTERNAL_EVALUATION = "allow_internal_evaluation"
    METADATA_ONLY = "metadata_only"
    QUARANTINED_UNKNOWN = "quarantined_unknown"
    EXCLUDED = "excluded"


class TrustDecision(str, Enum):
    """Trust state kept separate from allowed-use decisions."""

    UNTRUSTED = "untrusted"
    QUARANTINED = "quarantined"


class FindingCategory(str, Enum):
    """Classes of hostile or sensitive MCP tool data."""

    SECRET = "secret"
    PERSONAL_DATA = "personal_data"
    PROMPT_INJECTION = "prompt_injection"
    TOOL_DIRECTIVE = "tool_directive"
    UNSAFE_METADATA = "unsafe_metadata"
    UNSAFE_SCHEMA = "unsafe_schema"


class FindingDecision(str, Enum):
    """Outcome for one family of detectors."""

    CLEAR = "clear"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class MCPToolPolicyFinding:
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
class MCPToolSourcePolicyDecision:
    """Complete fail-closed policy result for one MCP tool record."""

    tool_id: str
    policy_version: str
    allowed_use: AllowedUseDecision
    trust_decision: TrustDecision
    findings: tuple[MCPToolPolicyFinding, ...] = ()

    @property
    def hostile_input_decision(self) -> FindingDecision:
        if any(
            finding.category
            in {
                FindingCategory.PROMPT_INJECTION,
                FindingCategory.TOOL_DIRECTIVE,
                FindingCategory.UNSAFE_SCHEMA,
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
            "secret_pii_decision": self.secret_pii_decision.value,
            "tool_id": self.tool_id,
            "trust_decision": self.trust_decision.value,
        }


@dataclass(frozen=True, slots=True)
class MCPToolEntryIdentity:
    """Multiformats identity for one container-independent MCP tool entry."""

    cid: str
    cid_bytes: bytes
    multihash_bytes: bytes
    sha256: str
    identity_schema_version: str = MCP_TOOL_ENTRY_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            decoded = CID.decode(self.cid)
        except (TypeError, ValueError) as exc:
            raise MCPToolRecordError("entry identity CID is malformed") from exc
        if (
            decoded.version != 1
            or decoded.codec.name != "raw"
            or decoded.hashfun.name != "sha2-256"
            or bytes(decoded) != self.cid_bytes
            or bytes(decoded.digest) != self.multihash_bytes
            or decoded.raw_digest.hex() != self.sha256
        ):
            raise MCPToolRecordError(
                "entry identity does not use CIDv1/raw/sha2-256 consistently"
            )
        if self.identity_schema_version != MCP_TOOL_ENTRY_IDENTITY_SCHEMA_VERSION:
            raise MCPToolRecordError(
                "entry identity schema version is unsupported"
            )

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
class MCPToolRecord:
    """One bounded MCP tool definition with explicit provenance."""

    name: str
    description: str = ""
    input_schema_json: str = '{"type":"object","properties":{}}'
    output_schema_json: str = ""
    server_name: str = ""
    source_uri: str = ""
    source_id: str = ""
    source_revision: str = "unpinned"
    annotations_json: str = "{}"
    tags: tuple[str, ...] = ()
    schema_version: str = MCP_TOOL_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        name = _require_tool_name(self.name)
        description = _optional_text(self.description, "description")
        input_schema_json = _normalize_json_object(
            self.input_schema_json, "input_schema_json", allow_empty=False
        )
        output_schema_json = _normalize_json_object(
            self.output_schema_json, "output_schema_json", allow_empty=True
        )
        server_name = _optional_text(self.server_name, "server_name")
        source_uri = _optional_text(self.source_uri, "source_uri")
        source_id = _optional_text(self.source_id, "source_id")
        source_revision = _require_text(self.source_revision, "source_revision")
        annotations_json = _normalize_json_object(
            self.annotations_json, "annotations_json", allow_empty=False
        )
        tags = _normalize_tags(self.tags)
        if self.schema_version != MCP_TOOL_RECORD_SCHEMA_VERSION:
            raise MCPToolRecordError(
                "mcp tool record schema version is unsupported"
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "input_schema_json", input_schema_json)
        object.__setattr__(self, "output_schema_json", output_schema_json)
        object.__setattr__(self, "server_name", server_name)
        object.__setattr__(self, "source_uri", source_uri)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "source_revision", source_revision)
        object.__setattr__(self, "annotations_json", annotations_json)
        object.__setattr__(self, "tags", tags)

    @property
    def tool_id(self) -> str:
        return f"mcp-tool:{self.entry_identity.sha256[:32]}"

    @property
    def content_sha256(self) -> str:
        material = self.intrinsic_payload()
        payload = json.dumps(
            material, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def intrinsic_payload(self) -> dict[str, Any]:
        """Canonical payload for identity (excludes mutable packaging fields)."""

        return {
            "annotations_json": self.annotations_json,
            "description": self.description,
            "input_schema_json": self.input_schema_json,
            "name": self.name,
            "output_schema_json": self.output_schema_json,
            "schema_version": self.schema_version,
            "server_name": self.server_name,
            "tags": list(self.tags),
        }

    @property
    def entry_identity(self) -> MCPToolEntryIdentity:
        preimage = identity_preimage(
            self.intrinsic_payload(),
            domain=MCP_TOOL_ENTRY_IDENTITY_DOMAIN,
            schema_version=MCP_TOOL_ENTRY_IDENTITY_SCHEMA_VERSION,
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
        return MCPToolEntryIdentity(
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
        payload = json.dumps(
            self.intrinsic_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return validate_cid(
            cid_for_bytes(
                payload,
                base="base32",
                codec="raw",
                mh_type="sha2-256",
                version=1,
            ),
            path="/content_cid",
        )

    def input_schema(self) -> dict[str, Any]:
        return json.loads(self.input_schema_json)

    def to_source_ref(
        self,
        *,
        review_status: ReviewStatus = ReviewStatus.UNREVIEWED,
        content_cid: str = "",
        span: SourceSpan | None = None,
    ) -> SourceRef:
        encoded_name = quote(self.name, safe="")
        source_uri = (
            self.source_uri
            or f"mcp://tool/{quote(self.server_name or 'local', safe='')}/{encoded_name}"
        )
        source_id = self.source_id or self.tool_id
        reference_material = (
            f"{source_id}@{self.source_revision}#{self.content_sha256}"
        )
        reference_digest = hashlib.sha256(
            reference_material.encode("utf-8")
        ).hexdigest()
        return SourceRef(
            ref_id=f"mcp-tool:{reference_digest}",
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
            "annotations_json": self.annotations_json,
            "description": self.description,
            "entry_cid": self.entry_cid,
            "input_schema_json": self.input_schema_json,
            "name": self.name,
            "output_schema_json": self.output_schema_json,
            "schema_version": self.schema_version,
            "server_name": self.server_name,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_uri": self.source_uri,
            "tags": list(self.tags),
            "tool_id": self.tool_id,
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
        "hostile.role_markup",
        _pattern(r"(?:<\s*/?\s*system\s*>|^\s*#{0,3}\s*system\s*:|\[INST\])"),
    ),
    _Detector(
        FindingCategory.TOOL_DIRECTIVE,
        "hostile.tool_call_markup",
        _pattern(
            r"(?:<\s*(?:tool[_ -]?call|function_calls?)\b|"
            r"[\"']tool_calls?[\"']\s*:|"
            r"\b(?:assistant\s+to|recipient)\s*=\s*(?:functions|tools)\.)"
        ),
    ),
    _Detector(
        FindingCategory.TOOL_DIRECTIVE,
        "hostile.shell_tool",
        _pattern(
            r"\b(?:execute|run|spawn)\s+(?:arbitrary\s+)?(?:shell|bash|command|os)\b|"
            r"\b(?:rm\s+-rf|curl\b[^\r\n|]{0,200}\|\s*(?:ba|z|k)?sh)\b"
        ),
    ),
    _Detector(
        FindingCategory.UNSAFE_SCHEMA,
        "schema.code_execution_hint",
        _pattern(
            r"\b(?:eval|exec|subprocess|os\.system|__import__|"
            r"pickle\.loads|yaml\.load)\b"
        ),
        frozenset({"input_schema_json", "output_schema_json", "annotations_json"}),
    ),
    _Detector(
        FindingCategory.UNSAFE_METADATA,
        "metadata.template_secret",
        _pattern(
            r"(?:\$\{\{\s*secrets?\.|\{\{\s*(?:secret|env|config)\b|"
            r"\$\{(?:SECRET|TOKEN|PASSWORD|API_KEY)\b)"
        ),
    ),
)

_TEXT_FIELDS = (
    "name",
    "description",
    "input_schema_json",
    "output_schema_json",
    "server_name",
    "source_uri",
    "source_id",
    "annotations_json",
)
_BLOCKED_ALLOWED_USES = frozenset(
    {
        AllowedUseDecision.METADATA_ONLY,
        AllowedUseDecision.QUARANTINED_UNKNOWN,
        AllowedUseDecision.EXCLUDED,
    }
)


class MCPToolSourcePolicy:
    """Deterministic, side-effect-free policy for MCP tool definitions."""

    def __init__(
        self,
        *,
        max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
        max_name_chars: int = DEFAULT_MAX_NAME_CHARS,
        max_schema_chars: int = DEFAULT_MAX_SCHEMA_CHARS,
        max_metadata_chars: int = DEFAULT_MAX_METADATA_CHARS,
    ) -> None:
        for name, value in (
            ("max_text_chars", max_text_chars),
            ("max_name_chars", max_name_chars),
            ("max_schema_chars", max_schema_chars),
            ("max_metadata_chars", max_metadata_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.max_text_chars = max_text_chars
        self.max_name_chars = max_name_chars
        self.max_schema_chars = max_schema_chars
        self.max_metadata_chars = max_metadata_chars

    def evaluate(self, record: MCPToolRecord) -> MCPToolSourcePolicyDecision:
        if not isinstance(record, MCPToolRecord):
            raise TypeError("record must be an MCPToolRecord")
        findings: list[MCPToolPolicyFinding] = []
        limits = {
            "name": self.max_name_chars,
            "description": self.max_text_chars,
            "input_schema_json": self.max_schema_chars,
            "output_schema_json": self.max_schema_chars,
            "annotations_json": self.max_metadata_chars,
            "server_name": self.max_name_chars,
            "source_uri": self.max_text_chars,
            "source_id": self.max_name_chars,
        }
        for field, limit in limits.items():
            value = getattr(record, field)
            if len(value) > limit:
                findings.append(
                    MCPToolPolicyFinding(
                        FindingCategory.UNSAFE_METADATA,
                        "input.scan_limit_exceeded",
                        field,
                        limit,
                        len(value),
                    )
                )
        for field in _TEXT_FIELDS:
            findings.extend(self._scan_field(field, getattr(record, field)))
        findings.extend(self._scan_schema_structure(record.input_schema_json, "input_schema_json"))
        if record.output_schema_json:
            findings.extend(
                self._scan_schema_structure(
                    record.output_schema_json, "output_schema_json"
                )
            )
        findings = _deduplicate_and_sort_findings(findings)
        if findings:
            allowed_use = AllowedUseDecision.EXCLUDED
            trust = TrustDecision.QUARANTINED
        else:
            allowed_use = AllowedUseDecision.ALLOW_INTERNAL_EVALUATION
            trust = TrustDecision.UNTRUSTED
        return MCPToolSourcePolicyDecision(
            tool_id=record.tool_id,
            policy_version=MCP_TOOL_SOURCE_POLICY_VERSION,
            allowed_use=allowed_use,
            trust_decision=trust,
            findings=tuple(findings),
        )

    evaluate_record = evaluate

    def _scan_field(self, field: str, value: str) -> list[MCPToolPolicyFinding]:
        findings: list[MCPToolPolicyFinding] = []
        limit = {
            "name": self.max_name_chars,
            "description": self.max_text_chars,
            "input_schema_json": self.max_schema_chars,
            "output_schema_json": self.max_schema_chars,
            "annotations_json": self.max_metadata_chars,
        }.get(field, self.max_text_chars)
        if len(value) > limit:
            value = value[:limit]
        for detector in _DETECTORS:
            if detector.fields is not None and field not in detector.fields:
                continue
            accepted = 0
            for match in detector.pattern.finditer(value):
                if accepted >= MAX_FINDINGS_PER_DETECTOR:
                    findings.append(
                        MCPToolPolicyFinding(
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
                    MCPToolPolicyFinding(
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
                    MCPToolPolicyFinding(
                        FindingCategory.UNSAFE_METADATA,
                        "input.detector_matches_truncated",
                        field,
                        0,
                        len(value),
                    )
                )
                break
            findings.append(
                MCPToolPolicyFinding(
                    FindingCategory.UNSAFE_METADATA,
                    "metadata.control_character",
                    field,
                    match.start(),
                    match.end(),
                )
            )
        return findings

    def _scan_schema_structure(
        self, schema_json: str, field: str
    ) -> list[MCPToolPolicyFinding]:
        if not schema_json:
            return []
        try:
            parsed = json.loads(schema_json)
        except json.JSONDecodeError:
            return [
                MCPToolPolicyFinding(
                    FindingCategory.UNSAFE_SCHEMA,
                    "schema.malformed_json",
                    field,
                    0,
                    len(schema_json),
                )
            ]
        findings: list[MCPToolPolicyFinding] = []
        try:
            _validate_json_bounds(parsed, path="$")
        except MCPToolRecordError as exc:
            findings.append(
                MCPToolPolicyFinding(
                    FindingCategory.UNSAFE_SCHEMA,
                    "schema.bounds_exceeded",
                    field,
                    0,
                    len(schema_json),
                )
            )
            _ = exc
        if isinstance(parsed, Mapping):
            schema_type = parsed.get("type")
            if schema_type is not None and schema_type not in {
                "object",
                "array",
                "string",
                "number",
                "integer",
                "boolean",
                "null",
            }:
                findings.append(
                    MCPToolPolicyFinding(
                        FindingCategory.UNSAFE_SCHEMA,
                        "schema.unsupported_type",
                        field,
                        0,
                        len(schema_json),
                    )
                )
            # Reject remote $ref / dynamic resolution — no network follow.
            if _contains_key(parsed, "$ref") or _contains_key(parsed, "$dynamicRef"):
                findings.append(
                    MCPToolPolicyFinding(
                        FindingCategory.UNSAFE_SCHEMA,
                        "schema.remote_or_dynamic_ref",
                        field,
                        0,
                        len(schema_json),
                    )
                )
        return findings


class MCPToolIntentAdapter:
    """Normalize MCP tool schemas into IntentIR-compatible records.

    Interface: ``MCPToolIntentAdapter@1``.
    """

    def __init__(
        self,
        *,
        policy: MCPToolSourcePolicy | None = None,
        max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
        max_schema_chars: int = DEFAULT_MAX_SCHEMA_CHARS,
    ) -> None:
        for name, value in (
            ("max_text_chars", max_text_chars),
            ("max_schema_chars", max_schema_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if policy is not None and not isinstance(policy, MCPToolSourcePolicy):
            raise TypeError("policy must be an MCPToolSourcePolicy")
        self.max_text_chars = max_text_chars
        self.max_schema_chars = max_schema_chars
        self.policy = policy or MCPToolSourcePolicy(
            max_text_chars=max_text_chars,
            max_schema_chars=max_schema_chars,
        )
        self.interface = MCP_TOOL_INTENT_ADAPTER

    def make_record(
        self,
        name: str,
        *,
        description: str = "",
        input_schema: Mapping[str, Any] | str | None = None,
        output_schema: Mapping[str, Any] | str | None = None,
        server_name: str = "",
        source_uri: str = "",
        source_id: str = "",
        source_revision: str = "unpinned",
        annotations: Mapping[str, Any] | str | None = None,
        tags: Iterable[str] = (),
    ) -> MCPToolRecord:
        """Build a bounded MCP tool record without invoking the tool."""

        input_schema_json = _coerce_json_object(
            input_schema, default={"type": "object", "properties": {}}
        )
        output_schema_json = (
            ""
            if output_schema is None
            else _coerce_json_object(output_schema, default={})
        )
        annotations_json = _coerce_json_object(annotations, default={})
        if len(description) > self.max_text_chars:
            raise MCPToolRecordError("description exceeds max_text_chars")
        if len(input_schema_json) > self.max_schema_chars:
            raise MCPToolRecordError("input_schema exceeds max_schema_chars")
        if len(output_schema_json) > self.max_schema_chars:
            raise MCPToolRecordError("output_schema exceeds max_schema_chars")
        return MCPToolRecord(
            name=name,
            description=description,
            input_schema_json=input_schema_json,
            output_schema_json=output_schema_json,
            server_name=server_name,
            source_uri=source_uri,
            source_id=source_id,
            source_revision=source_revision,
            annotations_json=annotations_json,
            tags=tuple(tags),
        )

    def evaluate(self, record: MCPToolRecord) -> MCPToolSourcePolicyDecision:
        return self.policy.evaluate(record)

    def adapt(self, record: MCPToolRecord) -> IntentIRDocument:
        """Return validated Intent IR or raise :class:`MCPToolPolicyError`."""

        return self.adapt_with_policy(record)[0]

    def adapt_with_policy(
        self, record: MCPToolRecord
    ) -> tuple[IntentIRDocument, MCPToolSourcePolicyDecision]:
        if not isinstance(record, MCPToolRecord):
            raise TypeError("record must be an MCPToolRecord")
        if len(record.description) > self.max_text_chars:
            raise MCPToolRecordError("description exceeds max_text_chars")
        if len(record.input_schema_json) > self.max_schema_chars:
            raise MCPToolRecordError("input_schema exceeds max_schema_chars")
        decision = self.policy.evaluate(record)
        if decision.allowed_use in _BLOCKED_ALLOWED_USES:
            raise MCPToolPolicyError(decision)
        document = _build_mcp_tool_intent_document(record, decision)
        validate_intent_ir(document)
        return document, decision

    normalize = adapt
    normalize_record = adapt_with_policy


def _build_mcp_tool_intent_document(
    record: MCPToolRecord,
    decision: MCPToolSourcePolicyDecision,
) -> IntentIRDocument:
    base_source = record.to_source_ref(review_status=decision.review_status)
    base_source.validate()
    description = record.description.strip() or f"MCP tool capability: {record.name}"
    body = (
        f"name: {record.name}\n"
        f"description: {description}\n"
        f"input_schema: {record.input_schema_json}"
    )
    span = SourceSpan(0, len(body))
    span.validate()
    spanned = record.to_source_ref(
        review_status=decision.review_status,
        span=span,
    )
    goal_text = _normalize_evidence(description)
    statement_id = _stable_id("statement", "goal", record.name)
    statement = IntentStatement(
        statement_id=statement_id,
        kind=StatementKind.GOAL,
        modality=IntentModality.INTENDED,
        normalized_text=goal_text,
        source_ref_ids=(spanned.ref_id,),
        grounding=NodeGrounding.GROUNDED,
        review_status=ReviewStatus.MACHINE_EXTRACTED,
    )
    action_id = _stable_id("action", "mcp-tool", record.name)
    action = IntentAction(
        action_id=action_id,
        actor="tool",
        verb=record.name,
        object_refs=(),
        source_ref_ids=(spanned.ref_id,),
        tool_refs=(record.name,),
        grounding=NodeGrounding.GROUNDED,
    )
    sources_by_id = {base_source.ref_id: base_source, spanned.ref_id: spanned}
    tags = tuple(sorted(set(record.tags) | {"mcp-tool"}))
    return IntentIRDocument(
        document_id=record.tool_id,
        title=record.name,
        intent_kind=IntentKind.CAPABILITY,
        sources=tuple(sources_by_id[key] for key in sorted(sources_by_id)),
        statements=(statement,),
        actions=(action,),
        entry_action_ids=(action_id,),
        terminal_action_ids=(action_id,),
        tags=tags,
    )


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MCPToolRecordError(f"{label} must be a non-empty string")
    if value.strip() != value:
        raise MCPToolRecordError(f"{label} must not have surrounding whitespace")
    if "\x00" in value:
        raise MCPToolRecordError(f"{label} must not contain NUL")
    return value


def _optional_text(value: Any, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MCPToolRecordError(f"{label} must be a string")
    if value and value.strip() != value:
        raise MCPToolRecordError(f"{label} must not have surrounding whitespace")
    if "\x00" in value:
        raise MCPToolRecordError(f"{label} must not contain NUL")
    return value


def _require_tool_name(value: Any) -> str:
    name = _require_text(value, "name")
    if not _TOOL_NAME_RE.fullmatch(name):
        raise MCPToolRecordError("name must be a stable tool identifier")
    return name


def _normalize_json_object(
    value: Any, label: str, *, allow_empty: bool
) -> str:
    if value is None or value == "":
        if allow_empty:
            return ""
        raise MCPToolRecordError(f"{label} must be a JSON object")
    if not isinstance(value, str):
        raise MCPToolRecordError(f"{label} must be a string")
    if "\x00" in value:
        raise MCPToolRecordError(f"{label} must not contain NUL")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise MCPToolRecordError(f"{label} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise MCPToolRecordError(f"{label} must be a JSON object")
    _validate_json_bounds(parsed, path="$")
    return json.dumps(parsed, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _coerce_json_object(
    value: Mapping[str, Any] | str | None, *, default: Mapping[str, Any]
) -> str:
    if value is None:
        payload = dict(default)
    elif isinstance(value, str):
        if not value.strip():
            payload = dict(default)
        else:
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise MCPToolRecordError("JSON payload must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise MCPToolRecordError("JSON payload must be an object")
            payload = parsed
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        raise TypeError("JSON payload must be a mapping, JSON string, or None")
    _validate_json_bounds(payload, path="$")
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _validate_json_bounds(value: Any, *, path: str, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    counter[0] += 1
    if counter[0] > MAX_JSON_NODES:
        raise MCPToolRecordError("JSON payload exceeds maximum node count")
    if depth > MAX_JSON_DEPTH:
        raise MCPToolRecordError("JSON payload exceeds maximum depth")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise MCPToolRecordError(f"{path} contains a non-string key")
            _validate_json_bounds(
                item, path=f"{path}.{key}", depth=depth + 1, counter=counter
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_bounds(
                item, path=f"{path}[{index}]", depth=depth + 1, counter=counter
            )
        return
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    raise MCPToolRecordError(f"{path} has unsupported JSON value type")


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, Mapping):
        if key in value:
            return True
        return any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _normalize_tags(tags: Any) -> tuple[str, ...]:
    if tags is None:
        return ()
    if isinstance(tags, str):
        raise MCPToolRecordError("tags must be a sequence of strings")
    try:
        items = tuple(tags)
    except TypeError as exc:
        raise MCPToolRecordError("tags must be a sequence of strings") from exc
    if len(items) > MAX_TAGS:
        raise MCPToolRecordError(f"tags exceeds maximum of {MAX_TAGS}")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item or item.strip() != item:
            raise MCPToolRecordError("each tag must be non-empty normalized text")
        if "\x00" in item or len(item) > MAX_TAG_CHARS:
            raise MCPToolRecordError("tag is malformed or exceeds max length")
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
    findings: Iterable[MCPToolPolicyFinding],
) -> list[MCPToolPolicyFinding]:
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


ALLOWED_USE_BLOCKED = _BLOCKED_ALLOWED_USES


__all__ = [
    "ALLOWED_USE_BLOCKED",
    "AllowedUseDecision",
    "DEFAULT_MAX_METADATA_CHARS",
    "DEFAULT_MAX_NAME_CHARS",
    "DEFAULT_MAX_SCHEMA_CHARS",
    "DEFAULT_MAX_TEXT_CHARS",
    "FindingCategory",
    "FindingDecision",
    "MAX_FINDINGS_PER_DETECTOR",
    "MCPToolEntryIdentity",
    "MCPToolIntentAdapter",
    "MCPToolPolicyError",
    "MCPToolPolicyFinding",
    "MCPToolRecord",
    "MCPToolRecordError",
    "MCPToolSourceError",
    "MCPToolSourcePolicy",
    "MCPToolSourcePolicyDecision",
    "MCP_TOOL_ENTRY_IDENTITY_DOMAIN",
    "MCP_TOOL_ENTRY_IDENTITY_SCHEMA_VERSION",
    "MCP_TOOL_INTENT_ADAPTER",
    "MCP_TOOL_RECORD_SCHEMA_VERSION",
    "MCP_TOOL_SOURCE_POLICY_VERSION",
    "TrustDecision",
]
