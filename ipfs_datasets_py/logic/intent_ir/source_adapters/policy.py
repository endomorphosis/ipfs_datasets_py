"""Fail-closed policy for untrusted SkillCenter source records.

The scanner in this module is deliberately passive.  It compares bounded text
to deterministic patterns and never renders, interpolates, parses as YAML,
imports, invokes, or executes anything found in a source record.  Findings do
not retain matched text, so a policy receipt cannot accidentally publish a
credential or a piece of personal data.

This is a routing policy, not a claim that pattern matching proves content
safe.  A clean result remains explicitly untrusted and is allowed only for the
use permitted by the record's declared license.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final


SKILL_SOURCE_POLICY_SCHEMA_VERSION: Final = "skill-source-policy/v1"
DEFAULT_MAX_POLICY_TEXT_CHARS: Final = 1_000_000
DEFAULT_MAX_POLICY_FINDINGS: Final = 128


class SkillSourcePolicyError(ValueError):
    """Raised when policy input or configuration violates safety bounds."""


class AllowedUse(str, Enum):
    """Stable routing decisions for a SkillCenter source record.

    ``ALLOW_TRAIN_PUBLISH``
        Content may enter approved training and publication workflows, subject
        to attribution and all other obligations outside this scanner.
    ``INTERNAL_EVALUATION``
        Content may be retained in access-controlled evaluation only.  It must
        not enter training or published artifacts.
    ``METADATA_ONLY``
        Only non-sensitive provenance and descriptive metadata may be retained;
        source bodies must not enter training, evaluation, or publication.
    ``QUARANTINED_UNKNOWN``
        No content use is allowed until a human resolves an absent, unknown, or
        contradictory license declaration.
    ``EXCLUDED``
        Neither source content nor unsafe metadata may enter a downstream
        corpus.  Minimal policy/provenance receipts may still record the block.
    """

    ALLOW_TRAIN_PUBLISH = "allow-train/publish"
    INTERNAL_EVALUATION = "internal-evaluation"
    METADATA_ONLY = "metadata-only"
    QUARANTINED_UNKNOWN = "quarantined-unknown"
    EXCLUDED = "excluded"


# The license classifier emits the same stable vocabulary as the final router.
# Keeping this as an alias makes it impossible to accidentally widen use while
# copying a license outcome into a source decision.
LicenseDecision = AllowedUse


class TrustDecision(str, Enum):
    """Trust state after license and hostile-content evaluation."""

    UNTRUSTED_BOUNDED = "untrusted-bounded"
    QUARANTINED_UNKNOWN = "quarantined-unknown"
    EXCLUDED_LICENSE = "excluded-license"
    EXCLUDED_SENSITIVE = "excluded-sensitive"
    EXCLUDED_HOSTILE = "excluded-hostile"


class ScanDecision(str, Enum):
    """Outcome of one passive content-scan family."""

    NOT_DETECTED = "not-detected"
    DETECTED = "detected"


class FindingKind(str, Enum):
    """Machine-readable categories emitted without retaining matched text."""

    SECRET = "secret"
    PERSONAL_DATA = "personal-data"
    PROMPT_INJECTION = "prompt-injection"
    TOOL_DIRECTIVE = "tool-directive"
    UNSAFE_METADATA = "unsafe-metadata"
    UNKNOWN_LICENSE = "unknown-license"
    CONTRADICTORY_LICENSE = "contradictory-license"


@dataclass(frozen=True, slots=True)
class PolicyFinding:
    """One passive match, represented without the potentially sensitive text."""

    kind: FindingKind
    field: str
    detector: str
    start: int
    end: int
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "end": self.end,
            "evidence_sha256": self.evidence_sha256,
            "field": self.field,
            "kind": self.kind.value,
            "start": self.start,
        }


@dataclass(frozen=True, slots=True)
class SkillSourcePolicyDecision:
    """Complete immutable policy receipt for one SkillCenter source record."""

    record_id: str
    source_content_sha256: str
    license_expression: str
    license_expression_sha256: str
    normalized_licenses: tuple[str, ...]
    license_decision: LicenseDecision
    trust_decision: TrustDecision
    secret_pii_decision: ScanDecision
    hostile_input_decision: ScanDecision
    unsafe_metadata_decision: ScanDecision
    allowed_use: AllowedUse
    reason_codes: tuple[str, ...]
    findings: tuple[PolicyFinding, ...]
    schema_version: str = SKILL_SOURCE_POLICY_SCHEMA_VERSION

    @property
    def publishable(self) -> bool:
        return self.allowed_use is AllowedUse.ALLOW_TRAIN_PUBLISH

    @property
    def trainable(self) -> bool:
        return self.allowed_use is AllowedUse.ALLOW_TRAIN_PUBLISH

    @property
    def quarantined(self) -> bool:
        return self.allowed_use is AllowedUse.QUARANTINED_UNKNOWN

    @property
    def excluded(self) -> bool:
        return self.allowed_use is AllowedUse.EXCLUDED

    def has_finding(self, kind: FindingKind | str) -> bool:
        """Return whether a finding category is present."""

        expected = kind.value if isinstance(kind, FindingKind) else str(kind)
        return any(finding.kind.value == expected for finding in self.findings)

    def to_dict(self) -> dict[str, Any]:
        """Return a stable, source-body-free policy receipt."""

        return {
            "allowed_use": self.allowed_use.value,
            "findings": [finding.to_dict() for finding in self.findings],
            "hostile_input_decision": self.hostile_input_decision.value,
            "license_decision": self.license_decision.value,
            "license_expression": self.license_expression,
            "license_expression_sha256": self.license_expression_sha256,
            "normalized_licenses": list(self.normalized_licenses),
            "reason_codes": list(self.reason_codes),
            "record_id": self.record_id,
            "schema_version": self.schema_version,
            "secret_pii_decision": self.secret_pii_decision.value,
            "source_content_sha256": self.source_content_sha256,
            "trust_decision": self.trust_decision.value,
            "unsafe_metadata_decision": self.unsafe_metadata_decision.value,
        }


_LICENSE_ALIASES: Final[dict[str, str]] = {
    "0bsd": "0BSD",
    "apache 2": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache-2": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "agpl-3.0": "AGPL-3.0-only",
    "agpl-3.0-only": "AGPL-3.0-only",
    "agpl-3.0-or-later": "AGPL-3.0-or-later",
    "all rights reserved": "All-Rights-Reserved",
    "all-rights-reserved": "All-Rights-Reserved",
    "bsd 2-clause": "BSD-2-Clause",
    "bsd 3-clause": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "bsl-1.0": "BSL-1.0",
    "cc-by-4.0": "CC-BY-4.0",
    "cc-by-nc-4.0": "CC-BY-NC-4.0",
    "cc-by-nc-nd-4.0": "CC-BY-NC-ND-4.0",
    "cc-by-nc-sa-4.0": "CC-BY-NC-SA-4.0",
    "cc-by-nd-4.0": "CC-BY-ND-4.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc0": "CC0-1.0",
    "cc0-1.0": "CC0-1.0",
    "cddl-1.0": "CDDL-1.0",
    "epl-2.0": "EPL-2.0",
    "gpl-2.0": "GPL-2.0-only",
    "gpl-2.0-only": "GPL-2.0-only",
    "gpl-2.0-or-later": "GPL-2.0-or-later",
    "gpl-3.0": "GPL-3.0-only",
    "gpl-3.0-only": "GPL-3.0-only",
    "gpl-3.0-or-later": "GPL-3.0-or-later",
    "isc": "ISC",
    "lgpl-2.1": "LGPL-2.1-only",
    "lgpl-2.1-only": "LGPL-2.1-only",
    "lgpl-2.1-or-later": "LGPL-2.1-or-later",
    "lgpl-3.0": "LGPL-3.0-only",
    "lgpl-3.0-only": "LGPL-3.0-only",
    "lgpl-3.0-or-later": "LGPL-3.0-or-later",
    "mit": "MIT",
    "mpl-2.0": "MPL-2.0",
    "no license": "NOASSERTION",
    "no-license": "NOASSERTION",
    "none": "NOASSERTION",
    "proprietary": "Proprietary",
    "the unlicense": "Unlicense",
    "unlicense": "Unlicense",
    "zlib": "Zlib",
}

_ALLOW_TRAIN_PUBLISH_LICENSES: Final[frozenset[str]] = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSL-1.0",
        "CC-BY-4.0",
        "CC0-1.0",
        "ISC",
        "MIT",
        "Unlicense",
        "Zlib",
    }
)
_INTERNAL_EVALUATION_LICENSES: Final[frozenset[str]] = frozenset(
    {
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "CC-BY-SA-4.0",
        "CDDL-1.0",
        "EPL-2.0",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "MPL-2.0",
    }
)
_METADATA_ONLY_LICENSES: Final[frozenset[str]] = frozenset(
    {
        "CC-BY-NC-4.0",
        "CC-BY-NC-SA-4.0",
        "CC-BY-ND-4.0",
    }
)
_EXCLUDED_LICENSES: Final[frozenset[str]] = frozenset(
    {"All-Rights-Reserved", "CC-BY-NC-ND-4.0", "Proprietary"}
)

_SPDX_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
_SPDX_OPERATOR_TOKENS: Final = frozenset({"AND", "OR", "WITH"})
_SAFE_EXPRESSION_RE: Final = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9.+() -]*(?:\s+(?:AND|OR|WITH)\s+"
    r"[A-Za-z0-9][A-Za-z0-9.+() -]*)*$",
    re.IGNORECASE,
)
_METADATA_SCALAR_RE: Final = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):[ \t]*(?P<value>[^\r\n]*)$",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class _Detector:
    kind: FindingKind
    detector: str
    pattern: re.Pattern[str]


_CONTENT_DETECTORS: Final[tuple[_Detector, ...]] = (
    _Detector(
        FindingKind.SECRET,
        "aws-access-key",
        re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"),
    ),
    _Detector(
        FindingKind.SECRET,
        "github-token",
        re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    ),
    _Detector(
        FindingKind.SECRET,
        "openai-secret-key",
        re.compile(r"(?<![A-Za-z0-9-])sk-[A-Za-z0-9_-]{20,}"),
    ),
    _Detector(
        FindingKind.SECRET,
        "slack-token",
        re.compile(r"(?<![A-Za-z0-9-])xox[baprs]-[A-Za-z0-9-]{10,}"),
    ),
    _Detector(
        FindingKind.SECRET,
        "bearer-token",
        re.compile(r"\bBearer[ \t]+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    ),
    _Detector(
        FindingKind.SECRET,
        "private-key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ),
    _Detector(
        FindingKind.SECRET,
        "credential-assignment",
        re.compile(
            r"\b(?:password|passwd|api[_-]?key|access[_-]?token|auth[_-]?token|"
            r"client[_-]?secret)\b[ \t]*[:=][ \t]*[\"']?"
            r"(?!example\b|placeholder\b|redacted\b|changeme\b|your[_ -])"
            r"[A-Za-z0-9._~+/=-]{8,}",
            re.IGNORECASE,
        ),
    ),
    _Detector(
        FindingKind.PERSONAL_DATA,
        "email-address",
        re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])"),
    ),
    _Detector(
        FindingKind.PERSONAL_DATA,
        "us-ssn",
        re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}(?!\d)"),
    ),
    _Detector(
        FindingKind.PERSONAL_DATA,
        "phone-number",
        re.compile(
            r"(?<!\d)(?:\+?1[-. ]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})"
            r"[-. ][2-9]\d{2}[-. ]\d{4}(?!\d)"
        ),
    ),
    _Detector(
        FindingKind.PROMPT_INJECTION,
        "instruction-override",
        re.compile(
            r"\b(?:ignore|disregard|override|forget)\b.{0,48}"
            r"\b(?:previous|prior|above|system|developer)\b.{0,24}"
            r"\b(?:instruction|message|prompt|rule)s?\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    _Detector(
        FindingKind.PROMPT_INJECTION,
        "prompt-exfiltration",
        re.compile(
            r"\b(?:reveal|print|show|leak|exfiltrate)\b.{0,48}"
            r"\b(?:system|developer|hidden)\b.{0,24}\b(?:prompt|message|instruction)s?\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    _Detector(
        FindingKind.PROMPT_INJECTION,
        "role-escalation",
        re.compile(
            r"\b(?:you are now|act as)\b.{0,32}\b(?:system|developer|administrator|root)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    _Detector(
        FindingKind.PROMPT_INJECTION,
        "jailbreak-marker",
        re.compile(r"\b(?:jailbreak|developer mode|DAN mode)\b", re.IGNORECASE),
    ),
    _Detector(
        FindingKind.TOOL_DIRECTIVE,
        "serialized-tool-call",
        re.compile(
            r"(?:<tool_call\b|</tool_call>|[\"'](?:tool_calls?|tool_name)[\"'][ \t]*:|"
            r"\bassistant[ \t]+to=|functions\.[A-Za-z_][A-Za-z0-9_]*)",
            re.IGNORECASE,
        ),
    ),
    _Detector(
        FindingKind.TOOL_DIRECTIVE,
        "tool-imperative",
        re.compile(
            r"\b(?:call|invoke|use|run)\b.{0,32}\b(?:MCP|function|tool)\b"
            r"[ \t]+(?:now|immediately|without[ \t]+confirmation)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    _Detector(
        FindingKind.TOOL_DIRECTIVE,
        "download-and-execute",
        re.compile(r"\b(?:curl|wget)\b[^\r\n|;]{0,240}\|\s*(?:ba)?sh\b", re.IGNORECASE),
    ),
)

_UNSAFE_METADATA_DETECTORS: Final[tuple[_Detector, ...]] = (
    _Detector(
        FindingKind.UNSAFE_METADATA,
        "yaml-constructor-tag",
        re.compile(r"(?:^|[ \t])!![A-Za-z]|!<[^>\r\n]+>|!python/", re.MULTILINE | re.IGNORECASE),
    ),
    _Detector(
        FindingKind.UNSAFE_METADATA,
        "yaml-anchor-or-alias",
        re.compile(r"(?:^|[ \t])(?:&|\*)[A-Za-z_][A-Za-z0-9_-]*", re.MULTILINE),
    ),
    _Detector(
        FindingKind.UNSAFE_METADATA,
        "yaml-merge-key",
        re.compile(r"^[ \t]*<<[ \t]*:", re.MULTILINE),
    ),
    _Detector(
        FindingKind.UNSAFE_METADATA,
        "yaml-directive-or-document",
        re.compile(r"^[ \t]*(?:%YAML|%TAG|---|\.\.\.)[ \t]*(?:$|#)", re.MULTILINE),
    ),
    _Detector(
        FindingKind.UNSAFE_METADATA,
        "executable-metadata-key",
        re.compile(
            r"^[ \t]*(?:system(?:_prompt)?|developer(?:_message)?|tool_calls?|"
            r"command|exec|__proto__|constructor)[ \t]*:",
            re.MULTILINE | re.IGNORECASE,
        ),
    ),
    _Detector(
        FindingKind.UNSAFE_METADATA,
        "control-character",
        re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"),
    ),
)


class SkillSourcePolicy:
    """Deterministic, passive evaluator for one untrusted source record."""

    def __init__(
        self,
        *,
        max_text_chars: int = DEFAULT_MAX_POLICY_TEXT_CHARS,
        max_findings: int = DEFAULT_MAX_POLICY_FINDINGS,
    ) -> None:
        if isinstance(max_text_chars, bool) or not isinstance(max_text_chars, int):
            raise SkillSourcePolicyError("max_text_chars must be an integer")
        if isinstance(max_findings, bool) or not isinstance(max_findings, int):
            raise SkillSourcePolicyError("max_findings must be an integer")
        if max_text_chars < 1:
            raise SkillSourcePolicyError("max_text_chars must be positive")
        if max_findings < 1:
            raise SkillSourcePolicyError("max_findings must be positive")
        self.max_text_chars = max_text_chars
        self.max_findings = max_findings

    def classify_license(self, expression: str) -> LicenseDecision:
        """Classify one license expression, failing closed on unknown syntax."""

        decision, _licenses = _classify_license_expression(expression)
        return decision

    def evaluate(self, record: Any) -> SkillSourcePolicyDecision:
        """Evaluate a SkillCenter record or equivalent mapping.

        Values are read as inert strings only.  Objects are not iterated,
        called, formatted, or deserialized.
        """

        return self.evaluate_fields(
            record_id=_field(record, "skill_id"),
            source_content_sha256=_field(record, "content_sha256"),
            license_expression=_field(record, "license_expression"),
            license_risk=_field(record, "license_risk"),
            title=_field(record, "title"),
            metadata_yaml=_field(record, "metadata_yaml"),
            skill_md=_field(record, "skill_md"),
            library_md=_field(record, "library_md"),
        )

    # Explicit alias for callers that prefer a descriptive method name.
    evaluate_record = evaluate

    def evaluate_fields(
        self,
        *,
        record_id: str,
        license_expression: str = "",
        license_risk: str = "",
        title: str = "",
        metadata_yaml: str = "",
        skill_md: str = "",
        library_md: str = "",
        source_content_sha256: str = "",
    ) -> SkillSourcePolicyDecision:
        """Evaluate already-extracted fields without interpreting their text."""

        text_fields = {
            "title": _require_string(title, "title"),
            "metadata_yaml": _require_string(metadata_yaml, "metadata_yaml"),
            "skill_md": _require_string(skill_md, "skill_md"),
            "library_md": _require_string(library_md, "library_md"),
        }
        record_id = _require_string(record_id, "record_id").strip()
        if not record_id:
            raise SkillSourcePolicyError("record_id must not be empty")
        license_expression = _require_string(
            license_expression, "license_expression"
        ).strip()
        license_risk = _require_string(license_risk, "license_risk").strip()
        if len(record_id) > 1_024:
            raise SkillSourcePolicyError("record_id exceeds 1024 characters")
        if any(ord(character) < 32 for character in record_id):
            raise SkillSourcePolicyError("record_id must not contain control characters")
        if len(license_expression) > self.max_text_chars:
            raise SkillSourcePolicyError("license_expression exceeds max_text_chars")
        if len(license_risk) > 128:
            raise SkillSourcePolicyError("license_risk exceeds 128 characters")
        if not license_risk:
            metadata_risks = _metadata_scalars(
                text_fields["metadata_yaml"], "license_risk"
            )
            if len(set(metadata_risks)) > 1:
                # Conflicting risk labels are handled like conflicting license
                # declarations below, without attempting to choose one.
                license_risk = "<contradictory>"
            elif metadata_risks:
                license_risk = metadata_risks[0]

        for field, text in text_fields.items():
            if len(text) > self.max_text_chars:
                raise SkillSourcePolicyError(
                    f"{record_id}: {field} exceeds max_text_chars"
                )

        if source_content_sha256:
            source_content_sha256 = _require_string(
                source_content_sha256, "source_content_sha256"
            )
            if not re.fullmatch(r"[0-9a-f]{64}", source_content_sha256):
                raise SkillSourcePolicyError(
                    "source_content_sha256 must be 64 lowercase hexadecimal characters"
                )
        else:
            source_content_sha256 = hashlib.sha256(
                text_fields["skill_md"].encode("utf-8")
            ).hexdigest()

        declarations = _license_declarations(
            license_expression, text_fields["metadata_yaml"]
        )
        (
            effective_expression,
            normalized_licenses,
            license_decision,
            license_reason,
            license_finding,
        ) = _evaluate_license_declarations(declarations, license_risk)

        findings: list[PolicyFinding] = []
        if license_finding is not None:
            findings.append(
                _synthetic_finding(
                    license_finding,
                    "metadata_yaml",
                    license_reason,
                    "\n".join(declarations) or "<missing-license>",
                )
            )

        for field, text in text_fields.items():
            findings.extend(
                self._scan(
                    field,
                    text,
                    _CONTENT_DETECTORS,
                    remaining=self.max_findings - len(findings),
                )
            )
            if field == "metadata_yaml":
                findings.extend(
                    self._scan(
                        field,
                        text,
                        _UNSAFE_METADATA_DETECTORS,
                        remaining=self.max_findings - len(findings),
                    )
                )

        duplicate_keys = _duplicate_metadata_keys(text_fields["metadata_yaml"])
        for key, start, end in duplicate_keys:
            if len(findings) >= self.max_findings:
                raise SkillSourcePolicyError(
                    f"{record_id}: policy findings exceed max_findings"
                )
            findings.append(
                _finding(
                    FindingKind.UNSAFE_METADATA,
                    "metadata_yaml",
                    f"duplicate-metadata-key:{key}",
                    start,
                    end,
                    key,
                )
            )

        findings = sorted(
            findings,
            key=lambda item: (
                item.field,
                item.start,
                item.end,
                item.kind.value,
                item.detector,
            ),
        )
        if len(findings) > self.max_findings:
            raise SkillSourcePolicyError(
                f"{record_id}: policy findings exceed max_findings"
            )

        finding_tuple = tuple(findings)
        sensitive = any(
            finding.kind in {FindingKind.SECRET, FindingKind.PERSONAL_DATA}
            for finding in finding_tuple
        )
        hostile = any(
            finding.kind
            in {FindingKind.PROMPT_INJECTION, FindingKind.TOOL_DIRECTIVE}
            for finding in finding_tuple
        )
        unsafe_metadata = any(
            finding.kind is FindingKind.UNSAFE_METADATA
            for finding in finding_tuple
        )

        if sensitive:
            allowed_use = AllowedUse.EXCLUDED
            trust_decision = TrustDecision.EXCLUDED_SENSITIVE
            final_reason = "sensitive-data-detected"
        elif hostile or unsafe_metadata:
            allowed_use = AllowedUse.EXCLUDED
            trust_decision = TrustDecision.EXCLUDED_HOSTILE
            final_reason = (
                "hostile-input-detected"
                if hostile
                else "unsafe-metadata-detected"
            )
        elif license_decision is AllowedUse.QUARANTINED_UNKNOWN:
            allowed_use = AllowedUse.QUARANTINED_UNKNOWN
            trust_decision = TrustDecision.QUARANTINED_UNKNOWN
            final_reason = license_reason
        elif license_decision is AllowedUse.EXCLUDED:
            allowed_use = AllowedUse.EXCLUDED
            trust_decision = TrustDecision.EXCLUDED_LICENSE
            final_reason = license_reason
        else:
            allowed_use = license_decision
            trust_decision = TrustDecision.UNTRUSTED_BOUNDED
            final_reason = license_reason

        reason_codes = tuple(
            dict.fromkeys(
                (
                    license_reason,
                    *(
                        finding.kind.value
                        for finding in finding_tuple
                        if finding.kind
                        not in {
                            FindingKind.UNKNOWN_LICENSE,
                            FindingKind.CONTRADICTORY_LICENSE,
                        }
                    ),
                    final_reason,
                )
            )
        )
        return SkillSourcePolicyDecision(
            record_id=record_id,
            source_content_sha256=source_content_sha256,
            license_expression=_receipt_license_expression(
                effective_expression,
                normalized_licenses,
                license_decision,
            ),
            license_expression_sha256=hashlib.sha256(
                effective_expression.encode("utf-8")
            ).hexdigest(),
            normalized_licenses=normalized_licenses,
            license_decision=license_decision,
            trust_decision=trust_decision,
            secret_pii_decision=(
                ScanDecision.DETECTED if sensitive else ScanDecision.NOT_DETECTED
            ),
            hostile_input_decision=(
                ScanDecision.DETECTED if hostile else ScanDecision.NOT_DETECTED
            ),
            unsafe_metadata_decision=(
                ScanDecision.DETECTED
                if unsafe_metadata
                else ScanDecision.NOT_DETECTED
            ),
            allowed_use=allowed_use,
            reason_codes=reason_codes,
            findings=finding_tuple,
        )

    def _scan(
        self,
        field: str,
        text: str,
        detectors: tuple[_Detector, ...],
        *,
        remaining: int,
    ) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        for detector in detectors:
            for match in detector.pattern.finditer(text):
                if len(findings) >= remaining:
                    raise SkillSourcePolicyError(
                        "policy findings exceed max_findings"
                    )
                findings.append(
                    _finding(
                        detector.kind,
                        field,
                        detector.detector,
                        match.start(),
                        match.end(),
                        match.group(0),
                    )
                )
        return findings


def _field(record: Any, name: str) -> str:
    if isinstance(record, Mapping):
        value = record.get(name, "")
    else:
        try:
            value = getattr(record, name)
        except AttributeError:
            value = ""
    if callable(value):
        # Properties such as ``content_sha256`` are evaluated by getattr, but
        # methods and arbitrary callable values are never invoked.
        return ""
    return _require_string(value, name)


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise SkillSourcePolicyError(f"{label} must be a string")
    return value


def _metadata_scalars(metadata: str, key: str) -> tuple[str, ...]:
    values: list[str] = []
    expected = key.casefold().replace("-", "_")
    for match in _METADATA_SCALAR_RE.finditer(metadata):
        actual = match.group("key").casefold().replace("-", "_")
        if actual != expected:
            continue
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1].strip()
        if value:
            values.append(value)
    return tuple(values)


def _license_declarations(
    explicit_expression: str, metadata: str
) -> tuple[str, ...]:
    values: list[str] = []
    if explicit_expression:
        values.append(explicit_expression)
    for key in ("license_spdx", "license"):
        values.extend(_metadata_scalars(metadata, key))
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _classify_license_expression(
    expression: str,
) -> tuple[LicenseDecision, tuple[str, ...]]:
    expression = str(expression or "").strip()
    if not expression or not _SAFE_EXPRESSION_RE.fullmatch(expression):
        return AllowedUse.QUARANTINED_UNKNOWN, ()

    direct = _LICENSE_ALIASES.get(expression.casefold())
    if direct is not None:
        if direct == "NOASSERTION":
            return AllowedUse.QUARANTINED_UNKNOWN, ()
        return _license_id_decision(direct), (direct,)

    raw_tokens = _SPDX_TOKEN_RE.findall(expression)
    license_tokens = [
        token
        for token in raw_tokens
        if token.upper() not in _SPDX_OPERATOR_TOKENS
    ]
    normalized: list[str] = []
    for token in license_tokens:
        canonical = _LICENSE_ALIASES.get(token.casefold())
        if canonical is None:
            return AllowedUse.QUARANTINED_UNKNOWN, tuple(normalized)
        if canonical == "NOASSERTION":
            return AllowedUse.QUARANTINED_UNKNOWN, ()
        normalized.append(canonical)
    if not normalized:
        return AllowedUse.QUARANTINED_UNKNOWN, ()

    decisions = [_license_id_decision(value) for value in normalized]
    if any(value is AllowedUse.QUARANTINED_UNKNOWN for value in decisions):
        return AllowedUse.QUARANTINED_UNKNOWN, tuple(dict.fromkeys(normalized))

    unique_licenses = tuple(dict.fromkeys(normalized))
    if re.search(r"\bOR\b", expression, re.IGNORECASE) and not re.search(
        r"\bAND\b", expression, re.IGNORECASE
    ):
        # An SPDX OR expression grants a choice; select the least restrictive
        # known option.  Mixed/nested expressions remain conservative below.
        decision = min(decisions, key=_decision_rank)
    else:
        decision = max(decisions, key=_decision_rank)
    return decision, unique_licenses


def _license_id_decision(license_id: str) -> LicenseDecision:
    if license_id in _ALLOW_TRAIN_PUBLISH_LICENSES:
        return AllowedUse.ALLOW_TRAIN_PUBLISH
    if license_id in _INTERNAL_EVALUATION_LICENSES:
        return AllowedUse.INTERNAL_EVALUATION
    if license_id in _METADATA_ONLY_LICENSES:
        return AllowedUse.METADATA_ONLY
    if license_id in _EXCLUDED_LICENSES:
        return AllowedUse.EXCLUDED
    return AllowedUse.QUARANTINED_UNKNOWN


def _receipt_license_expression(
    expression: str,
    normalized_licenses: tuple[str, ...],
    decision: LicenseDecision,
) -> str:
    """Return only canonical, recognized license text for a public receipt."""

    if decision is AllowedUse.QUARANTINED_UNKNOWN:
        return " AND ".join(normalized_licenses)
    return expression


def _decision_rank(decision: LicenseDecision) -> int:
    return {
        AllowedUse.ALLOW_TRAIN_PUBLISH: 0,
        AllowedUse.INTERNAL_EVALUATION: 1,
        AllowedUse.METADATA_ONLY: 2,
        AllowedUse.QUARANTINED_UNKNOWN: 3,
        AllowedUse.EXCLUDED: 4,
    }[decision]


def _evaluate_license_declarations(
    declarations: tuple[str, ...], license_risk: str
) -> tuple[str, tuple[str, ...], LicenseDecision, str, FindingKind | None]:
    if not declarations:
        return (
            "",
            (),
            AllowedUse.QUARANTINED_UNKNOWN,
            "license-missing",
            FindingKind.UNKNOWN_LICENSE,
        )

    assessments = [
        (declaration, *_classify_license_expression(declaration))
        for declaration in declarations
    ]
    canonical_declarations = {
        (decision, licenses)
        for _expression, decision, licenses in assessments
    }
    if len(canonical_declarations) > 1:
        return (
            " | ".join(declarations),
            tuple(
                dict.fromkeys(
                    license_id
                    for _expression, _decision, licenses in assessments
                    for license_id in licenses
                )
            ),
            AllowedUse.QUARANTINED_UNKNOWN,
            "license-declarations-contradict",
            FindingKind.CONTRADICTORY_LICENSE,
        )

    expression, decision, licenses = assessments[0]
    risk = license_risk.casefold().strip()
    if risk == "<contradictory>":
        return (
            expression,
            licenses,
            AllowedUse.QUARANTINED_UNKNOWN,
            "license-risk-declarations-contradict",
            FindingKind.CONTRADICTORY_LICENSE,
        )
    allow_risks = {"", "allow", "allowed", "low", "permissive"}
    review_risks = {"review", "unknown", "medium", "quarantine"}
    deny_risks = {"deny", "denied", "block", "blocked", "exclude", "excluded", "high"}
    if risk not in allow_risks | review_risks | deny_risks:
        return (
            expression,
            licenses,
            AllowedUse.QUARANTINED_UNKNOWN,
            "license-risk-unknown",
            FindingKind.UNKNOWN_LICENSE,
        )
    if risk in review_risks:
        return (
            expression,
            licenses,
            AllowedUse.QUARANTINED_UNKNOWN,
            "license-risk-requires-review",
            FindingKind.UNKNOWN_LICENSE,
        )
    if (
        risk in deny_risks
        and decision is not AllowedUse.EXCLUDED
    ) or (
        risk in {"allow", "allowed", "low", "permissive"}
        and decision
        not in {
            AllowedUse.ALLOW_TRAIN_PUBLISH,
            AllowedUse.QUARANTINED_UNKNOWN,
        }
    ):
        return (
            expression,
            licenses,
            AllowedUse.QUARANTINED_UNKNOWN,
            "license-risk-contradicts-expression",
            FindingKind.CONTRADICTORY_LICENSE,
        )
    if decision is AllowedUse.QUARANTINED_UNKNOWN:
        return (
            expression,
            licenses,
            decision,
            "license-unknown",
            FindingKind.UNKNOWN_LICENSE,
        )
    return expression, licenses, decision, f"license-{decision.value}", None


def _duplicate_metadata_keys(metadata: str) -> tuple[tuple[str, int, int], ...]:
    seen: set[str] = set()
    duplicates: list[tuple[str, int, int]] = []
    for match in _METADATA_SCALAR_RE.finditer(metadata):
        key = match.group("key").casefold().replace("-", "_")
        if key in seen:
            duplicates.append((key, match.start("key"), match.end("key")))
        seen.add(key)
    return tuple(duplicates)


def _finding(
    kind: FindingKind,
    field: str,
    detector: str,
    start: int,
    end: int,
    matched_text: str,
) -> PolicyFinding:
    return PolicyFinding(
        kind=kind,
        field=field,
        detector=detector,
        start=start,
        end=end,
        evidence_sha256=hashlib.sha256(matched_text.encode("utf-8")).hexdigest(),
    )


def _synthetic_finding(
    kind: FindingKind, field: str, detector: str, evidence: str
) -> PolicyFinding:
    return _finding(kind, field, detector, -1, -1, evidence)


# Compatibility spellings for consumers that use the interface nouns from the
# architecture plan.
SkillAllowedUse = AllowedUse
SkillSourcePolicyFinding = PolicyFinding


__all__ = [
    "AllowedUse",
    "DEFAULT_MAX_POLICY_FINDINGS",
    "DEFAULT_MAX_POLICY_TEXT_CHARS",
    "FindingKind",
    "LicenseDecision",
    "PolicyFinding",
    "SKILL_SOURCE_POLICY_SCHEMA_VERSION",
    "ScanDecision",
    "SkillAllowedUse",
    "SkillSourcePolicy",
    "SkillSourcePolicyDecision",
    "SkillSourcePolicyError",
    "SkillSourcePolicyFinding",
    "TrustDecision",
]
