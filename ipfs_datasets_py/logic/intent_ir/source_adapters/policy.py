"""Fail-closed policy for untrusted SkillCenter source records.

This module classifies source *data*.  It does not render source text into a
prompt, parse arbitrary YAML objects, follow links, invoke tools, execute
commands, or rewrite/sanitize a record.  Detectors only produce bounded,
non-secret findings that callers can retain with the original quarantined
artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import ipaddress
import re
from typing import Any, Iterable, Mapping, Pattern
from urllib.parse import urlsplit

from ..schema import ReviewStatus
from .skillcenter import SkillCenterSkillRecord


SKILL_SOURCE_POLICY_VERSION = "skill-source-policy/v1"
DEFAULT_MAX_POLICY_TEXT_CHARS = 1_000_000
MAX_FINDINGS_PER_DETECTOR = 64


class AllowedUseDecision(str, Enum):
    """The maximum use permitted for one source record.

    Decisions are deliberately ordered by policy meaning, not by an implicit
    numeric risk score:

    * ``ALLOW_TRAIN_AND_PUBLISH`` permits content in training corpora and
      publication when provenance and attribution are retained.
    * ``ALLOW_INTERNAL_EVALUATION`` permits bounded internal evaluation, but
      not training or republication.
    * ``METADATA_ONLY`` permits lineage/index metadata, but not source bodies.
    * ``QUARANTINED_UNKNOWN`` retains the record for review when its license is
      absent, unknown, malformed, or contradictory.
    * ``EXCLUDED`` blocks content use because of an explicit prohibition or a
      detected secret, personal-data, hostile-input, or unsafe-metadata risk.
    """

    ALLOW_TRAIN_AND_PUBLISH = "allow_train_and_publish"
    ALLOW_INTERNAL_EVALUATION = "allow_internal_evaluation"
    METADATA_ONLY = "metadata_only"
    QUARANTINED_UNKNOWN = "quarantined_unknown"
    EXCLUDED = "excluded"


# Compatibility-friendly domain spelling: callers often name this interface
# after the source rather than the generic allowed-use dimension.
SkillSourceDecision = AllowedUseDecision
AllowedUse = AllowedUseDecision


class TrustDecision(str, Enum):
    """Trust state kept separate from license and allowed-use decisions."""

    UNTRUSTED = "untrusted"
    QUARANTINED = "quarantined"


class FindingCategory(str, Enum):
    """Classes of hostile or sensitive source data detected by the policy."""

    SECRET = "secret"
    PERSONAL_DATA = "personal_data"
    PROMPT_INJECTION = "prompt_injection"
    TOOL_DIRECTIVE = "tool_directive"
    UNSAFE_METADATA = "unsafe_metadata"
    GENERATED_BINARY = "generated_binary"


class FindingDecision(str, Enum):
    """Explicit outcome for one family of bounded detectors."""

    CLEAR = "clear"
    QUARANTINED = "quarantined"


class LicenseStatus(str, Enum):
    """Why a license decision was reached."""

    RECOGNIZED = "recognized"
    MISSING = "missing"
    UNKNOWN = "unknown"
    CONTRADICTORY = "contradictory"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class PolicyFinding:
    """A non-sensitive pointer to a policy match.

    Matched text is intentionally omitted so policy reports do not duplicate
    credentials or personal data into logs and downstream artifacts.
    """

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
class LicenseDecision:
    """Fail-closed classification of per-record license metadata."""

    expression: str
    status: LicenseStatus
    allowed_use: AllowedUseDecision
    reason_code: str
    recognized_licenses: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_use": self.allowed_use.value,
            "expression": self.expression,
            "reason_code": self.reason_code,
            "recognized_licenses": list(self.recognized_licenses),
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class SkillSourcePolicyDecision:
    """Complete policy result for one SkillCenter record."""

    skill_id: str
    policy_version: str
    allowed_use: AllowedUseDecision
    trust_decision: TrustDecision
    license_decision: LicenseDecision
    findings: tuple[PolicyFinding, ...] = ()

    @property
    def secret_findings(self) -> tuple[PolicyFinding, ...]:
        return self._findings_for(FindingCategory.SECRET)

    @property
    def personal_data_findings(self) -> tuple[PolicyFinding, ...]:
        return self._findings_for(FindingCategory.PERSONAL_DATA)

    @property
    def hostile_input_findings(self) -> tuple[PolicyFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if finding.category
            in {
                FindingCategory.PROMPT_INJECTION,
                FindingCategory.TOOL_DIRECTIVE,
                FindingCategory.GENERATED_BINARY,
            }
        )

    @property
    def unsafe_metadata_findings(self) -> tuple[PolicyFinding, ...]:
        return self._findings_for(FindingCategory.UNSAFE_METADATA)

    @property
    def secret_pii_decision(self) -> FindingDecision:
        return self._finding_decision(
            {FindingCategory.SECRET, FindingCategory.PERSONAL_DATA}
        )

    # More general spelling retained alongside the acceptance-contract term.
    sensitive_data_decision = secret_pii_decision

    @property
    def hostile_input_decision(self) -> FindingDecision:
        return self._finding_decision(
            {
                FindingCategory.PROMPT_INJECTION,
                FindingCategory.TOOL_DIRECTIVE,
                FindingCategory.GENERATED_BINARY,
            }
        )

    @property
    def unsafe_metadata_decision(self) -> FindingDecision:
        return self._finding_decision({FindingCategory.UNSAFE_METADATA})

    @property
    def review_status(self) -> ReviewStatus:
        """Review state suitable for the record's :class:`SourceRef`."""

        if self.trust_decision is TrustDecision.QUARANTINED:
            return ReviewStatus.QUARANTINED
        return ReviewStatus.UNREVIEWED

    def _findings_for(
        self, category: FindingCategory
    ) -> tuple[PolicyFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if finding.category is category
        )

    def _finding_decision(
        self, categories: set[FindingCategory]
    ) -> FindingDecision:
        if any(
            finding.category in categories for finding in self.findings
        ):
            return FindingDecision.QUARANTINED
        return FindingDecision.CLEAR

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_use": self.allowed_use.value,
            "findings": [finding.to_dict() for finding in self.findings],
            "hostile_input_decision": self.hostile_input_decision.value,
            "license_decision": self.license_decision.to_dict(),
            "policy_version": self.policy_version,
            "secret_pii_decision": self.secret_pii_decision.value,
            "skill_id": self.skill_id,
            "trust_decision": self.trust_decision.value,
            "unsafe_metadata_decision": self.unsafe_metadata_decision.value,
        }


_TRAIN_AND_PUBLISH_LICENSES: Mapping[str, str] = {
    "0bsd": "0BSD",
    "apache-2.0": "Apache-2.0",
    "bsd-2-clause": "BSD-2-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "bsl-1.0": "BSL-1.0",
    "cc-by-4.0": "CC-BY-4.0",
    "cc0-1.0": "CC0-1.0",
    "isc": "ISC",
    "mit": "MIT",
    "mit-0": "MIT-0",
    "python-2.0": "Python-2.0",
    "unlicense": "Unlicense",
    "wtfpl": "WTFPL",
    "zlib": "Zlib",
}
_INTERNAL_EVALUATION_LICENSES: Mapping[str, str] = {
    "agpl-3.0-only": "AGPL-3.0-only",
    "agpl-3.0-or-later": "AGPL-3.0-or-later",
    "cddl-1.0": "CDDL-1.0",
    "epl-2.0": "EPL-2.0",
    "eupl-1.2": "EUPL-1.2",
    "gpl-2.0-only": "GPL-2.0-only",
    "gpl-2.0-or-later": "GPL-2.0-or-later",
    "gpl-3.0-only": "GPL-3.0-only",
    "gpl-3.0-or-later": "GPL-3.0-or-later",
    "lgpl-2.1-only": "LGPL-2.1-only",
    "lgpl-2.1-or-later": "LGPL-2.1-or-later",
    "lgpl-3.0-only": "LGPL-3.0-only",
    "lgpl-3.0-or-later": "LGPL-3.0-or-later",
    "mpl-2.0": "MPL-2.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
}
_METADATA_ONLY_LICENSES: Mapping[str, str] = {
    "all rights reserved": "All-Rights-Reserved",
    "cc-by-nd-4.0": "CC-BY-ND-4.0",
    "cc-by-nc-4.0": "CC-BY-NC-4.0",
    "cc-by-nc-nd-4.0": "CC-BY-NC-ND-4.0",
    "cc-by-nc-sa-4.0": "CC-BY-NC-SA-4.0",
    "proprietary": "Proprietary",
}
_EXCLUDED_LICENSES: Mapping[str, str] = {
    "ai training prohibited": "AI-Training-Prohibited",
    "do not use": "Do-Not-Use",
    "no license": "NONE",
    "none": "NONE",
    "use prohibited": "Use-Prohibited",
}
_LICENSE_ALIASES: Mapping[str, str] = {
    "apache 2": "apache-2.0",
    "apache 2.0": "apache-2.0",
    "apache license 2.0": "apache-2.0",
    "bsd 2-clause": "bsd-2-clause",
    "bsd 3-clause": "bsd-3-clause",
    "cc0": "cc0-1.0",
    "gpl-2.0": "gpl-2.0-only",
    "gpl-3.0": "gpl-3.0-only",
    "mit license": "mit",
    "mozilla public license 2.0": "mpl-2.0",
    "public domain": "cc0-1.0",
    "the unlicense": "unlicense",
}
_LICENSE_RISK_DECISIONS: Mapping[str, AllowedUseDecision] = {
    "allow": AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
    "allow_train_and_publish": AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
    "internal": AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    "internal_evaluation": AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    "allow_internal_evaluation": AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    "metadata": AllowedUseDecision.METADATA_ONLY,
    "metadata_only": AllowedUseDecision.METADATA_ONLY,
    "deny": AllowedUseDecision.EXCLUDED,
    "exclude": AllowedUseDecision.EXCLUDED,
    "excluded": AllowedUseDecision.EXCLUDED,
    "prohibited": AllowedUseDecision.EXCLUDED,
    "quarantine": AllowedUseDecision.QUARANTINED_UNKNOWN,
    "unknown": AllowedUseDecision.QUARANTINED_UNKNOWN,
}
_LICENSE_SCALAR_RE = re.compile(
    r"^(?P<key>license_spdx|license|license_risk):[ \t]*(?P<value>.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_LICENSE_OPERATOR_RE = re.compile(r"\s+(?:AND|OR)\s+", re.IGNORECASE)
_LICENSE_WITH_RE = re.compile(
    r"\s+WITH\s+[A-Za-z0-9][A-Za-z0-9.+-]*$", re.IGNORECASE
)


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
        FindingCategory.SECRET,
        "secret.slack_token",
        _pattern(r"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{20,}(?![A-Za-z0-9])"),
    ),
    _Detector(
        FindingCategory.SECRET,
        "secret.jwt",
        _pattern(
            r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\."
            r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
        ),
    ),
    _Detector(
        FindingCategory.SECRET,
        "secret.assigned_credential",
        _pattern(
            r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
            r"password|secret[_-]?key)\b[ \t]*[:=][ \t]*[\"']?"
            r"(?!example\b|placeholder\b|redacted\b|changeme\b|<)"
            r"[A-Za-z0-9/+_.:@-]{12,}"
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
        FindingCategory.PERSONAL_DATA,
        "personal.us_ssn",
        _pattern(r"(?<!\d)(?!000|666|9\d\d)\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}(?!\d)"),
    ),
    _Detector(
        FindingCategory.PERSONAL_DATA,
        "personal.phone",
        _pattern(
            r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})"
            r"[\s.-]\d{3}[\s.-]\d{4}(?!\d)"
        ),
    ),
    _Detector(
        FindingCategory.PERSONAL_DATA,
        "personal.payment_card",
        _pattern(
            r"(?<![A-Za-z0-9])(?:\d[ -]?){12,18}\d(?![A-Za-z0-9])"
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
        "metadata.yaml_tag",
        _pattern(r"(?:^|[\s:[{,])!!?[A-Za-z_][A-Za-z0-9_./:-]*"),
        frozenset({"metadata_yaml"}),
    ),
    _Detector(
        FindingCategory.UNSAFE_METADATA,
        "metadata.yaml_directive",
        _pattern(r"^\s*%(?:YAML|TAG)\b"),
        frozenset({"metadata_yaml"}),
    ),
    _Detector(
        FindingCategory.UNSAFE_METADATA,
        "metadata.yaml_alias_or_merge",
        _pattern(
            r"(?:^|\s)(?:<<\s*:\s*\*[A-Za-z0-9_-]+|"
            r"[&*][A-Za-z_][A-Za-z0-9_-]*)"
        ),
        frozenset({"metadata_yaml"}),
    ),
    _Detector(
        FindingCategory.UNSAFE_METADATA,
        "metadata.template_secret",
        _pattern(
            r"(?:\$\{\{\s*secrets?\.|\{\{\s*(?:secret|env|config)\b|"
            r"\$\{(?:SECRET|TOKEN|PASSWORD|API_KEY)\b)"
        ),
        frozenset({"metadata_yaml"}),
    ),
    _Detector(
        FindingCategory.UNSAFE_METADATA,
        "metadata.prototype_key",
        _pattern(r"^\s*(?:__proto__|prototype|constructor)\s*:"),
        frozenset({"metadata_yaml"}),
    ),
    _Detector(
        FindingCategory.UNSAFE_METADATA,
        "metadata.unsafe_uri",
        _pattern(r"\b(?:data|file|javascript|vbscript):", flags=re.IGNORECASE),
        frozenset({"metadata_yaml", "source_url"}),
    ),
)

_TEXT_FIELDS = (
    "title",
    "source_url",
    "domain",
    "profile",
    "source_type",
    "language",
    "source_id",
    "primary_source_id",
    "metadata_yaml",
    "skill_md",
    "library_md",
)
_METADATA_FIELDS = frozenset(_TEXT_FIELDS) - {"skill_md", "library_md"}
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BASE64_BLOCK_RE = re.compile(
    r"(?:^|\s)(?:[A-Za-z0-9+/]{256,}={0,2})(?:\s|$)", re.MULTILINE
)


class SkillSourcePolicy:
    """Deterministic, side-effect-free policy for SkillCenter records."""

    def __init__(
        self, *, max_text_chars: int = DEFAULT_MAX_POLICY_TEXT_CHARS
    ) -> None:
        if (
            isinstance(max_text_chars, bool)
            or not isinstance(max_text_chars, int)
            or max_text_chars < 1
        ):
            raise ValueError("max_text_chars must be a positive integer")
        self.max_text_chars = max_text_chars

    def evaluate(
        self, record: SkillCenterSkillRecord
    ) -> SkillSourcePolicyDecision:
        """Classify ``record`` without interpreting any field as instructions."""

        if not isinstance(record, SkillCenterSkillRecord):
            raise TypeError("record must be a SkillCenterSkillRecord")

        license_decision = self.classify_license(record.metadata_yaml)
        findings: list[PolicyFinding] = []
        for field in _TEXT_FIELDS:
            value = getattr(record, field)
            findings.extend(self._scan_field(field, value))
        findings.extend(self._scan_source_url(record.source_url))
        findings = _deduplicate_and_sort_findings(findings)

        if findings:
            allowed_use = AllowedUseDecision.EXCLUDED
            trust = TrustDecision.QUARANTINED
        else:
            allowed_use = license_decision.allowed_use
            trust = (
                TrustDecision.QUARANTINED
                if allowed_use is AllowedUseDecision.QUARANTINED_UNKNOWN
                else TrustDecision.UNTRUSTED
            )
        return SkillSourcePolicyDecision(
            skill_id=record.skill_id,
            policy_version=SKILL_SOURCE_POLICY_VERSION,
            allowed_use=allowed_use,
            trust_decision=trust,
            license_decision=license_decision,
            findings=tuple(findings),
        )

    # Explicit spelling used by ingestion pipelines.
    evaluate_record = evaluate

    def classify_license(self, metadata_yaml: str) -> LicenseDecision:
        """Classify allowlisted scalar license metadata without YAML loading."""

        if not isinstance(metadata_yaml, str):
            raise TypeError("metadata_yaml must be a string")
        values = _license_metadata_values(metadata_yaml)
        declarations = values["license_spdx"] + values["license"]
        risk_values = values["license_risk"]

        if not declarations:
            return LicenseDecision(
                expression="",
                status=LicenseStatus.MISSING,
                allowed_use=AllowedUseDecision.QUARANTINED_UNKNOWN,
                reason_code="license.missing",
            )

        classified = [_classify_license_expression(value) for value in declarations]
        expression = " | ".join(declarations)
        if any(item is None for item in classified):
            return LicenseDecision(
                expression=expression,
                status=LicenseStatus.UNKNOWN,
                allowed_use=AllowedUseDecision.QUARANTINED_UNKNOWN,
                reason_code="license.unknown",
            )

        typed_classified = [item for item in classified if item is not None]
        distinct_identifiers = {
            item[1] for item in typed_classified
        }
        distinct_decisions = {item[0] for item in typed_classified}
        if len(distinct_identifiers) > 1 or len(distinct_decisions) > 1:
            return LicenseDecision(
                expression=expression,
                status=LicenseStatus.CONTRADICTORY,
                allowed_use=AllowedUseDecision.QUARANTINED_UNKNOWN,
                reason_code="license.contradictory_declarations",
                recognized_licenses=tuple(
                    sorted(
                        {
                            identifier
                            for item in typed_classified
                            for identifier in item[1]
                        }
                    )
                ),
            )

        allowed_use, recognized = typed_classified[0]
        risk_decisions: set[AllowedUseDecision] = set()
        for value in risk_values:
            risk = _LICENSE_RISK_DECISIONS.get(_normalized_text(value))
            if risk is None:
                return LicenseDecision(
                    expression=expression,
                    status=LicenseStatus.UNKNOWN,
                    allowed_use=AllowedUseDecision.QUARANTINED_UNKNOWN,
                    reason_code="license.unknown_risk",
                    recognized_licenses=recognized,
                )
            risk_decisions.add(risk)
        if risk_decisions and (
            len(risk_decisions) > 1 or allowed_use not in risk_decisions
        ):
            return LicenseDecision(
                expression=expression,
                status=LicenseStatus.CONTRADICTORY,
                allowed_use=AllowedUseDecision.QUARANTINED_UNKNOWN,
                reason_code="license.contradictory_risk",
                recognized_licenses=recognized,
            )

        return LicenseDecision(
            expression=expression,
            status=LicenseStatus.RECOGNIZED,
            allowed_use=allowed_use,
            reason_code=f"license.{allowed_use.value}",
            recognized_licenses=recognized,
        )

    def _scan_field(self, field: str, value: str) -> list[PolicyFinding]:
        findings: list[PolicyFinding] = []
        if len(value) > self.max_text_chars:
            findings.append(
                PolicyFinding(
                    category=FindingCategory.UNSAFE_METADATA,
                    code="input.scan_limit_exceeded",
                    field=field,
                    start_char=self.max_text_chars,
                    end_char=len(value),
                )
            )
            value = value[: self.max_text_chars]
        for detector in _DETECTORS:
            if detector.fields is not None and field not in detector.fields:
                continue
            accepted_matches = 0
            for match in detector.pattern.finditer(value):
                if (
                    detector.code == "personal.payment_card"
                    and not _passes_luhn_check(match.group(0))
                ):
                    continue
                if accepted_matches >= MAX_FINDINGS_PER_DETECTOR:
                    findings.append(
                        PolicyFinding(
                            category=FindingCategory.UNSAFE_METADATA,
                            code="input.detector_matches_truncated",
                            field=field,
                            start_char=0,
                            end_char=len(value),
                        )
                    )
                    break
                accepted_matches += 1
                findings.append(
                    PolicyFinding(
                        category=detector.category,
                        code=detector.code,
                        field=field,
                        start_char=match.start(),
                        end_char=match.end(),
                    )
                )
        if field in _METADATA_FIELDS:
            for index, match in enumerate(_CONTROL_CHAR_RE.finditer(value)):
                if index >= MAX_FINDINGS_PER_DETECTOR:
                    findings.append(
                        PolicyFinding(
                            category=FindingCategory.UNSAFE_METADATA,
                            code="input.detector_matches_truncated",
                            field=field,
                            start_char=0,
                            end_char=len(value),
                        )
                    )
                    break
                findings.append(
                    PolicyFinding(
                        category=FindingCategory.UNSAFE_METADATA,
                        code="metadata.control_character",
                        field=field,
                        start_char=match.start(),
                        end_char=match.end(),
                    )
                )
        else:
            for index, match in enumerate(_CONTROL_CHAR_RE.finditer(value)):
                if index >= MAX_FINDINGS_PER_DETECTOR:
                    findings.append(
                        PolicyFinding(
                            category=FindingCategory.UNSAFE_METADATA,
                            code="input.detector_matches_truncated",
                            field=field,
                            start_char=0,
                            end_char=len(value),
                        )
                    )
                    break
                findings.append(
                    PolicyFinding(
                        category=FindingCategory.GENERATED_BINARY,
                        code="content.control_character",
                        field=field,
                        start_char=match.start(),
                        end_char=match.end(),
                    )
                )
            for index, match in enumerate(_BASE64_BLOCK_RE.finditer(value)):
                if index >= MAX_FINDINGS_PER_DETECTOR:
                    findings.append(
                        PolicyFinding(
                            category=FindingCategory.UNSAFE_METADATA,
                            code="input.detector_matches_truncated",
                            field=field,
                            start_char=0,
                            end_char=len(value),
                        )
                    )
                    break
                findings.append(
                    PolicyFinding(
                        category=FindingCategory.GENERATED_BINARY,
                        code="content.encoded_binary_block",
                        field=field,
                        start_char=match.start(),
                        end_char=match.end(),
                    )
                )
        return findings

    @staticmethod
    def _scan_source_url(value: str) -> list[PolicyFinding]:
        if not value:
            return []
        findings: list[PolicyFinding] = []
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            return [
                PolicyFinding(
                    FindingCategory.UNSAFE_METADATA,
                    "metadata.malformed_source_url",
                    "source_url",
                    0,
                    len(value),
                )
            ]
        if not parsed.scheme or parsed.scheme.casefold() not in {
            "http",
            "https",
            "hf",
            "ipfs",
        }:
            findings.append(
                PolicyFinding(
                    FindingCategory.UNSAFE_METADATA,
                    "metadata.unsupported_source_scheme",
                    "source_url",
                    0,
                    len(value),
                )
            )
        if parsed.username is not None or parsed.password is not None:
            findings.append(
                PolicyFinding(
                    FindingCategory.UNSAFE_METADATA,
                    "metadata.source_url_credentials",
                    "source_url",
                    0,
                    len(value),
                )
            )
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(
            ".local"
        ):
            findings.append(
                PolicyFinding(
                    FindingCategory.UNSAFE_METADATA,
                    "metadata.local_source_url",
                    "source_url",
                    0,
                    len(value),
                )
            )
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            findings.append(
                PolicyFinding(
                    FindingCategory.UNSAFE_METADATA,
                    "metadata.non_public_source_address",
                    "source_url",
                    0,
                    len(value),
                )
            )
        # Accessing ``parsed.port`` above validates malformed/out-of-range
        # ports.  Assign to a local so static analyzers do not mistake it for a
        # missing validation branch.
        _ = port
        return findings


def _passes_luhn_check(value: str) -> bool:
    """Return whether a card-shaped digit sequence has a valid checksum."""

    digits = [int(character) for character in value if character.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _license_metadata_values(metadata_yaml: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {
        "license_spdx": [],
        "license": [],
        "license_risk": [],
    }
    for match in _LICENSE_SCALAR_RE.finditer(metadata_yaml):
        key = match.group("key").casefold()
        value = _decode_scalar(match.group("value"))
        if value:
            values[key].append(value)
    return values


def _decode_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _classify_license_expression(
    expression: str,
) -> tuple[AllowedUseDecision, tuple[str, ...]] | None:
    normalized = _normalized_text(expression)
    if not normalized or any(character in normalized for character in "\r\n\x00"):
        return None
    normalized = _LICENSE_ALIASES.get(normalized, normalized)
    parts = _LICENSE_OPERATOR_RE.split(normalized.strip("() "))
    decisions: list[AllowedUseDecision] = []
    identifiers: list[str] = []
    for part in parts:
        part = _LICENSE_WITH_RE.sub("", part.strip("() "))
        part = _LICENSE_ALIASES.get(part, part)
        classified = _classify_license_identifier(part)
        if classified is None:
            return None
        decision, identifier = classified
        decisions.append(decision)
        identifiers.append(identifier)
    if not decisions:
        return None
    if AllowedUseDecision.EXCLUDED in decisions and len(set(decisions)) > 1:
        return None
    # Composite licenses are classified to their most restrictive recognized
    # use.  This is conservative for both AND and OR expressions and avoids
    # claiming that a downstream consumer selected a dual-license branch.
    rank = {
        AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH: 3,
        AllowedUseDecision.ALLOW_INTERNAL_EVALUATION: 2,
        AllowedUseDecision.METADATA_ONLY: 1,
        AllowedUseDecision.EXCLUDED: 0,
    }
    result = min(decisions, key=rank.__getitem__)
    return result, tuple(sorted(set(identifiers)))


def _classify_license_identifier(
    normalized: str,
) -> tuple[AllowedUseDecision, str] | None:
    if normalized in _TRAIN_AND_PUBLISH_LICENSES:
        return (
            AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
            _TRAIN_AND_PUBLISH_LICENSES[normalized],
        )
    if normalized in _INTERNAL_EVALUATION_LICENSES:
        return (
            AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
            _INTERNAL_EVALUATION_LICENSES[normalized],
        )
    if normalized in _METADATA_ONLY_LICENSES:
        return (
            AllowedUseDecision.METADATA_ONLY,
            _METADATA_ONLY_LICENSES[normalized],
        )
    if normalized in _EXCLUDED_LICENSES:
        return AllowedUseDecision.EXCLUDED, _EXCLUDED_LICENSES[normalized]
    return None


def _deduplicate_and_sort_findings(
    findings: Iterable[PolicyFinding],
) -> list[PolicyFinding]:
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


__all__ = [
    "AllowedUse",
    "AllowedUseDecision",
    "DEFAULT_MAX_POLICY_TEXT_CHARS",
    "FindingCategory",
    "FindingDecision",
    "LicenseDecision",
    "LicenseStatus",
    "MAX_FINDINGS_PER_DETECTOR",
    "PolicyFinding",
    "SKILL_SOURCE_POLICY_VERSION",
    "SkillSourceDecision",
    "SkillSourcePolicy",
    "SkillSourcePolicyDecision",
    "TrustDecision",
]
