"""Semantic verification of government instructions against authority and logic (PATLAW-134).

Compares each instruction, deadline basis, required act, exception, and cited
proposition against exact quoted authority spans, hierarchy/effective date,
derived Legal IR, conflicts, and counterexamples.

Design invariants
-----------------
* **Citation resolution alone never yields consistency.** An exact citation
  with a wrong proposition fails or requires review.
* **Superseded, conflicting, or missing authority cannot pass.**
* **Verified consistency** requires proposition-level support **plus** either
  a replayable proof receipt or a documented deterministic rule identity.
* **Guidance/MPEP is never substituted** for controlling statute/regulation.
* Findings always expose **sources, assumptions, confidence, and the
  human-review boundary**. This module never makes a final legal determination
  and never declares unlawful conduct.
* Model summaries are never substituted for government or governing text.
* Document body text is never written to logs or exception messages.

Owns semantic instruction checking only (conflict policy for PATLAW-134).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ReviewState,
    canonical_json,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_contracts import (
    LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
    ActorRole,
    AssertionKind,
    AuthorityBinding,
    AuthorityRank,
    AuthorityResolutionState,
    CitationRef,
    LegalIRMapping,
    LegalModality,
    MappingStatus,
    NormalizedProposition,
    is_binding_authority_rank,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_proof_executor import (
    LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
    AtomicLiteral,
    FixtureKind,
    LegalIRProofExecutor,
    LogicFamily,
    PremiseCitation,
    ProofExecutionRequest,
    ProofExecutorConfig,
    ProofOutcome,
    ProofProblem,
    ProofReasonCode,
    execute_legal_ir_proof,
    run_local_bounded_kernel,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION: Final = (
    "uspto.semantic-instruction-consistency.v1"
)
SEMANTIC_INSTRUCTION_CONSISTENCY_INTERFACE: Final = (
    "SemanticInstructionConsistencyProcessor@1"
)
SEMANTIC_INSTRUCTION_CONSISTENCY_RULESET_VERSION: Final = (
    "semantic-instruction-consistency-rules@1"
)

OUTPUT_KIND_SEMANTIC_INSTRUCTION_ASSURANCE: Final = (
    "semantic_instruction_authority_logic_assurance"
)

NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER: Final = (
    "This output is a review-only semantic comparison of government instruction "
    "spans and cited propositions to independently resolved authority text at "
    "exact versions, with optional bounded proof or documented deterministic "
    "rule support. It does not make a final legal determination, does not "
    "declare any person or agency action unlawful, and is not a filing, "
    "docket, or compliance determination. Human review is required before any "
    "legal conclusion."
)

DEFAULT_MAX_FINDINGS: Final = 4096
DEFAULT_MAX_SURFACE: Final = 8000
DEFAULT_MAX_EXCERPT: Final = 4000
DEFAULT_MAX_PROPOSITIONS: Final = 256

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")
_QUOTED_FRAGMENT_RE = re.compile(
    r"[\"\u201c](?P<body>[^\"\u201d]{8,800})[\"\u201d]"
)

# Closed-set unlawful-conduct tokens — hard reject as outcome language.
_FORBIDDEN_UNLAWFUL_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "unlawful",
        "illegal",
        "examiner_unlawful",
        "examiner_illegal",
        "unlawful_conduct",
        "criminal",
        "malfeasance",
        "ultra_vires_declaration",
        "declares_unlawful",
        "is_unlawful",
    }
)

_FORBIDDEN_SUMMARY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "model_summary",
        "llm_summary",
        "ai_summary",
        "generated_summary",
        "summary_substituted_for_instruction",
        "summary_substituted_for_authority",
        "paraphrase_as_authority",
        "paraphrase_as_instruction",
    }
)

# Guidance / non-binding ranks that cannot alone support verified consistency.
_NON_CONTROLLING_RANKS: Final[frozenset[str]] = frozenset(
    {
        AuthorityRank.GUIDANCE.value,
        AuthorityRank.CANDIDATE.value,
        AuthorityRank.UNKNOWN.value,
        AuthorityRank.UNOFFICIAL_CURRENT.value,
        "mpep",
        "guidance",
        "editorial",
    }
)

# ---------------------------------------------------------------------------
# Documented deterministic rules (identity + digest; not free-form heuristics)
# ---------------------------------------------------------------------------

# Each rule has a stable id, version, description, and content digest of its
# contract. Verified consistency may cite a rule receipt *only* when the named
# rule's preconditions are fully satisfied by exact source anchors.


def _rule_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json(dict(payload)).encode("utf-8")
    ).hexdigest()


_RULE_QUOTE_EXACT_MATCH_BINDING: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "rule_id": "sic.quote_exact_match_binding",
        "rule_version": "1",
        "description": (
            "Normalized whitespace exact match between an instruction-quoted "
            "fragment and a binding (official-base or official-change) authority "
            "span at a resolved exact version; citation must resolve exactly."
        ),
        "preconditions": (
            "exact_citation_resolved",
            "binding_authority_rank",
            "exact_version_present",
            "quote_normalized_exact_match",
            "not_superseded",
            "not_conflicting",
        ),
        "on_no_match": "no_op",
        "deterministic": True,
    }
)

_RULE_PROPOSITION_ATOM_SUPPORT: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "rule_id": "sic.proposition_atom_support",
        "rule_version": "1",
        "description": (
            "Every claimed instruction proposition atom (predicate+polarity) is "
            "present in the closed authority support atom set for binding "
            "authority at exact version; no unsupported claimed atom remains."
        ),
        "preconditions": (
            "exact_citation_resolved",
            "binding_authority_rank",
            "exact_version_present",
            "all_claimed_atoms_supported",
            "not_superseded",
            "not_conflicting",
        ),
        "on_no_match": "no_op",
        "deterministic": True,
    }
)

_RULE_DEADLINE_BASIS_BINDING: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "rule_id": "sic.deadline_basis_binding",
        "rule_version": "1",
        "description": (
            "Deadline basis citation resolves to binding authority with exact "
            "version and matching basis predicate atom on the authority support set."
        ),
        "preconditions": (
            "deadline_basis_present",
            "exact_citation_resolved",
            "binding_authority_rank",
            "exact_version_present",
            "basis_predicate_supported",
            "not_superseded",
            "not_conflicting",
        ),
        "on_no_match": "no_op",
        "deterministic": True,
    }
)

_RULE_REQUIRED_ACT_SUPPORT: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "rule_id": "sic.required_act_support",
        "rule_version": "1",
        "description": (
            "Required-act proposition atoms are each supported by binding "
            "authority proposition support at exact version."
        ),
        "preconditions": (
            "required_act_present",
            "exact_citation_resolved",
            "binding_authority_rank",
            "exact_version_present",
            "all_claimed_atoms_supported",
            "not_superseded",
            "not_conflicting",
        ),
        "on_no_match": "no_op",
        "deterministic": True,
    }
)

DOCUMENTED_DETERMINISTIC_RULES: Final[Mapping[str, Mapping[str, Any]]] = MappingProxyType(
    {
        "sic.quote_exact_match_binding@1": MappingProxyType(
            {
                **dict(_RULE_QUOTE_EXACT_MATCH_BINDING),
                "rule_digest": _rule_digest(_RULE_QUOTE_EXACT_MATCH_BINDING),
            }
        ),
        "sic.proposition_atom_support@1": MappingProxyType(
            {
                **dict(_RULE_PROPOSITION_ATOM_SUPPORT),
                "rule_digest": _rule_digest(_RULE_PROPOSITION_ATOM_SUPPORT),
            }
        ),
        "sic.deadline_basis_binding@1": MappingProxyType(
            {
                **dict(_RULE_DEADLINE_BASIS_BINDING),
                "rule_digest": _rule_digest(_RULE_DEADLINE_BASIS_BINDING),
            }
        ),
        "sic.required_act_support@1": MappingProxyType(
            {
                **dict(_RULE_REQUIRED_ACT_SUPPORT),
                "rule_digest": _rule_digest(_RULE_REQUIRED_ACT_SUPPORT),
            }
        ),
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SemanticVerdict(str, Enum):
    """Per-instruction semantic verdict (closed set; never unlawful).

    Only ``VERIFIED_CONSISTENT`` is a pass candidate, and only when
    proposition-level support plus proof or a documented deterministic rule
    is present. All other verdicts fail or require review.
    """

    VERIFIED_CONSISTENT = "verified_consistent"
    CLERICAL_MISMATCH = "clerical_mismatch"
    UNSUPPORTED_INSTRUCTION = "unsupported_instruction"
    AMBIGUITY = "ambiguity"
    WRONG_PROPOSITION = "wrong_proposition"
    SUPERSEDED_AUTHORITY = "superseded_authority"
    CONFLICTING_AUTHORITY = "conflicting_authority"
    MISSING_AUTHORITY = "missing_authority"
    REQUIRES_REVIEW = "requires_review"
    UNKNOWN = "unknown"


class SupportKind(str, Enum):
    """How proposition-level support was established (mutually exclusive labels)."""

    PROOF_RECEIPT = "proof_receipt"
    DETERMINISTIC_RULE = "deterministic_rule"
    NONE = "none"
    INSUFFICIENT = "insufficient"


class FindingKind(str, Enum):
    """Kind of unit under comparison."""

    INSTRUCTION = "instruction"
    DEADLINE_BASIS = "deadline_basis"
    REQUIRED_ACT = "required_act"
    EXCEPTION = "exception"
    CITED_PROPOSITION = "cited_proposition"


class SemanticDisposition(str, Enum):
    """Top-level analysis disposition."""

    ASSURED = "assured"
    PARTIAL = "partial"
    FAILED = "failed"
    REVIEW = "review"
    UNKNOWN = "unknown"
    QUARANTINE = "quarantine"
    EMPTY = "empty"
    REJECTED = "rejected"


class SemanticReasonCode(str, Enum):
    """Stable machine-readable reason codes."""

    FINDINGS_EMITTED = "findings_emitted"
    VERDICT_VERIFIED_CONSISTENT = "verdict_verified_consistent"
    VERDICT_CLERICAL_MISMATCH = "verdict_clerical_mismatch"
    VERDICT_UNSUPPORTED = "verdict_unsupported_instruction"
    VERDICT_AMBIGUITY = "verdict_ambiguity"
    VERDICT_WRONG_PROPOSITION = "verdict_wrong_proposition"
    VERDICT_SUPERSEDED = "verdict_superseded_authority"
    VERDICT_CONFLICTING = "verdict_conflicting_authority"
    VERDICT_MISSING = "verdict_missing_authority"
    VERDICT_REQUIRES_REVIEW = "verdict_requires_review"
    VERDICT_UNKNOWN = "verdict_unknown"
    CITATION_RESOLVED = "citation_resolved"
    CITATION_UNRESOLVED = "citation_unresolved"
    CITATION_EXACT_BUT_WRONG_PROPOSITION = "citation_exact_but_wrong_proposition"
    PROPOSITION_SUPPORT_PRESENT = "proposition_support_present"
    PROPOSITION_SUPPORT_MISSING = "proposition_support_missing"
    PROPOSITION_ATOMS_MATCH = "proposition_atoms_match"
    PROPOSITION_ATOMS_MISMATCH = "proposition_atoms_mismatch"
    AUTHORITY_BINDING = "authority_binding"
    AUTHORITY_NON_BINDING = "authority_non_binding"
    AUTHORITY_GUIDANCE_NOT_CONTROLLING = "authority_guidance_not_controlling"
    AUTHORITY_SUPERSEDED = "authority_superseded"
    AUTHORITY_CONFLICTING = "authority_conflicting"
    AUTHORITY_MISSING = "authority_missing"
    AUTHORITY_VERSION_PRESENT = "authority_version_present"
    AUTHORITY_VERSION_MISSING = "authority_version_missing"
    QUOTE_MATCH = "quote_match"
    QUOTE_MISMATCH = "quote_mismatch"
    QUOTE_ABSENT = "quote_absent"
    CLERICAL_SURFACE_MISMATCH = "clerical_surface_mismatch"
    PROOF_PROVED = "proof_proved"
    PROOF_DISPROVED = "proof_disproved"
    PROOF_UNKNOWN = "proof_unknown"
    PROOF_TIMEOUT = "proof_timeout"
    PROOF_ERROR = "proof_error"
    PROOF_SKIPPED = "proof_skipped"
    DETERMINISTIC_RULE_APPLIED = "deterministic_rule_applied"
    DETERMINISTIC_RULE_FAILED = "deterministic_rule_failed"
    SUPPORT_INSUFFICIENT_FOR_CONSISTENT = "support_insufficient_for_consistent"
    CITATION_ALONE_NOT_CONSISTENT = "citation_alone_not_consistent"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    HUMAN_REVIEW_BOUNDARY_EXPOSED = "human_review_boundary_exposed"
    NOT_FINAL_LEGAL_DETERMINATION = "not_final_legal_determination"
    NO_MODEL_SUMMARY_SUBSTITUTION = "no_model_summary_substitution"
    SOURCES_EXPOSED = "sources_exposed"
    ASSUMPTIONS_RECORDED = "assumptions_recorded"
    CONFIDENCE_RECORDED = "confidence_recorded"
    EMPTY_INPUT = "empty_input"
    QUARANTINED = "quarantined"
    FINDING_LIMIT = "finding_limit"
    AS_OF_UNKNOWN = "as_of_unknown"
    COUNTEREXAMPLE_RECORDED = "counterexample_recorded"
    EXCEPTION_RECORDED = "exception_recorded"
    DEADLINE_BASIS_RECORDED = "deadline_basis_recorded"
    REQUIRED_ACT_RECORDED = "required_act_recorded"
    FORBIDDEN_LABEL_STRIPPED = "forbidden_label_stripped"


class SemanticInstructionConsistencyError(ValueError):
    """Bounded violation with a stable machine-readable code."""

    def __init__(
        self, message: str, *, code: str = "semantic_instruction_consistency_error"
    ) -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def _text_digest(text: str) -> str:
    return sha256_hex(_normalize_ws(text))


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
        raise TypeError(f"{field} must be str or None, got {type(value).__name__}")
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


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field} must be float or None") from exc
    if not (0.0 <= f <= 1.0):
        raise ValueError(f"{field} must be in [0, 1]")
    return f


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if value is None:
        raise ValueError(f"{field} is required")
    text = str(value).strip()
    for member in enum_cls:
        if member.value == text or member.name == text or member.name.lower() == text.lower():
            return member
    raise ValueError(f"{field} has unknown value: {value!r}")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    return _coerce_enum(  # type: ignore[return-value]
        DisclosureClassification, value, "classification"
    )


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence")
    out: list[str] = []
    for i, item in enumerate(value):
        if i >= max_items:
            break
        if not isinstance(item, str):
            raise TypeError(f"{field}[{i}] must be str")
        text = item.strip()
        if text:
            out.append(text[:512])
    return tuple(out)


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 32
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    out: dict[str, str] = {}
    for i, (k, v) in enumerate(sorted(value.items(), key=lambda kv: str(kv[0]))):
        if i >= max_items:
            break
        key = str(k).strip()
        if not key:
            continue
        if not isinstance(v, str):
            v = str(v)
        out[key[:128]] = v.strip()[:512]
    return MappingProxyType(out)


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be sha256 hex")
    return text


def _optional_sha256(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _sha256_hex_field(value, field)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _parse_as_of(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    # Accept YYYY-MM-DD prefix.
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def contains_forbidden_unlawful_token(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower().replace("-", "_").replace(" ", "_")
    for token in _FORBIDDEN_UNLAWFUL_TOKENS:
        if token in lowered:
            return True
    raw = text.lower()
    if "unlawful conduct" in raw or "declares unlawful" in raw:
        return True
    if "examiner is unlawful" in raw or "examiner unlawful" in raw:
        return True
    return False


def sanitize_labels(labels: Mapping[str, str] | None) -> tuple[Mapping[str, str], tuple[str, ...]]:
    if not labels:
        return MappingProxyType({}), ()
    cleaned: dict[str, str] = {}
    reasons: list[str] = []
    for key, value in labels.items():
        k = str(key).strip().lower()
        if k in _FORBIDDEN_SUMMARY_KEYS or k in _FORBIDDEN_UNLAWFUL_TOKENS:
            reasons.append(SemanticReasonCode.FORBIDDEN_LABEL_STRIPPED.value)
            continue
        if contains_forbidden_unlawful_token(k) or contains_forbidden_unlawful_token(value):
            reasons.append(SemanticReasonCode.FORBIDDEN_LABEL_STRIPPED.value)
            continue
        cleaned[str(key).strip()[:128]] = str(value).strip()[:512]
    return MappingProxyType(cleaned), tuple(dict.fromkeys(reasons))


def extract_quoted_fragments(surface: str) -> tuple[str, ...]:
    if not surface:
        return ()
    found: list[str] = []
    for m in _QUOTED_FRAGMENT_RE.finditer(surface):
        body = _normalize_ws(m.group("body"))
        if body and body not in found:
            found.append(body)
    return tuple(found[:8])


def quotes_match(quoted: str, source: str) -> bool:
    """Normalized whitespace exact containment or equality match."""
    q = _normalize_ws(quoted)
    s = _normalize_ws(source)
    if not q or not s:
        return False
    return q == s or q in s or s in q


def atom_key(predicate: str, *, polarity: bool = True) -> str:
    pred = _normalize_ws(predicate).lower()
    return f"{'+' if polarity else '-'}{pred}"


def is_pass_verdict(verdict: SemanticVerdict | str) -> bool:
    v = (
        verdict
        if isinstance(verdict, SemanticVerdict)
        else _coerce_enum(SemanticVerdict, verdict, "verdict")
    )
    return v is SemanticVerdict.VERIFIED_CONSISTENT


def documented_rule(rule_key: str) -> Mapping[str, Any] | None:
    return DOCUMENTED_DETERMINISTIC_RULES.get(rule_key)


def list_documented_rules() -> tuple[str, ...]:
    return tuple(sorted(DOCUMENTED_DETERMINISTIC_RULES.keys()))


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisBounds:
    max_findings: int = DEFAULT_MAX_FINDINGS
    max_surface: int = DEFAULT_MAX_SURFACE
    max_excerpt: int = DEFAULT_MAX_EXCERPT
    max_propositions: int = DEFAULT_MAX_PROPOSITIONS

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_findings", _nonneg_int(self.max_findings, "max_findings") or DEFAULT_MAX_FINDINGS
        )
        object.__setattr__(
            self, "max_surface", _nonneg_int(self.max_surface, "max_surface") or DEFAULT_MAX_SURFACE
        )
        object.__setattr__(
            self, "max_excerpt", _nonneg_int(self.max_excerpt, "max_excerpt") or DEFAULT_MAX_EXCERPT
        )
        object.__setattr__(
            self,
            "max_propositions",
            _nonneg_int(self.max_propositions, "max_propositions") or DEFAULT_MAX_PROPOSITIONS,
        )


@dataclass(frozen=True, slots=True)
class ExactSourceRef:
    """Exact source anchor (government or governing text, never a model paraphrase)."""

    source_id: str
    role: str  # instruction | authority | quote | counter | deadline | act | exception
    text: str
    text_digest: str
    span_id: str | None = None
    artifact_id: str | None = None
    version: str | None = None
    section: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "role", _require_str(self.role, "role", max_len=64))
        if not isinstance(self.text, str):
            raise TypeError("text must be str")
        object.__setattr__(self, "text", _truncate(self.text, DEFAULT_MAX_EXCERPT))
        digest = self.text_digest
        if not digest or not _SHA256_RE.match(str(digest).lower()):
            digest = _text_digest(self.text) if self.text else sha256_hex("")
        object.__setattr__(self, "text_digest", str(digest).lower())
        object.__setattr__(self, "span_id", _optional_identifier(self.span_id, "span_id"))
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "version", _optional_str(self.version, "version", max_len=128)
        )
        object.__setattr__(
            self, "section", _optional_str(self.section, "section", max_len=256)
        )
        if self.start_offset is not None:
            object.__setattr__(
                self, "start_offset", _nonneg_int(self.start_offset, "start_offset")
            )
        if self.end_offset is not None:
            object.__setattr__(
                self, "end_offset", _nonneg_int(self.end_offset, "end_offset")
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "end_offset": self.end_offset,
            "role": self.role,
            "section": self.section,
            "source_id": self.source_id,
            "span_id": self.span_id,
            "start_offset": self.start_offset,
            "text": self.text,
            "text_digest": self.text_digest,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExactSourceRef":
        if not isinstance(value, Mapping):
            raise TypeError("ExactSourceRef must be a mapping")
        return cls(
            source_id=str(value.get("source_id") or "src:unknown"),
            role=str(value.get("role") or "unknown"),
            text=str(value.get("text") or ""),
            text_digest=str(value.get("text_digest") or ""),
            span_id=value.get("span_id"),
            artifact_id=value.get("artifact_id"),
            version=value.get("version"),
            section=value.get("section"),
            start_offset=value.get("start_offset"),
            end_offset=value.get("end_offset"),
        )


@dataclass(frozen=True, slots=True)
class PropositionAtom:
    """Closed proposition atom (predicate + polarity) for support comparison."""

    atom_id: str
    predicate: str
    polarity: bool = True
    modality: str | None = None
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "atom_id", _identifier(self.atom_id, "atom_id"))
        object.__setattr__(
            self, "predicate", _require_str(self.predicate, "predicate", max_len=256)
        )
        object.__setattr__(self, "polarity", bool(self.polarity))
        object.__setattr__(
            self, "modality", _optional_str(self.modality, "modality", max_len=64)
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

    def key(self) -> str:
        return atom_key(self.predicate, polarity=self.polarity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "atom_id": self.atom_id,
            "key": self.key(),
            "labels": dict(self.labels),
            "modality": self.modality,
            "polarity": self.polarity,
            "predicate": self.predicate,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PropositionAtom":
        if not isinstance(value, Mapping):
            raise TypeError("PropositionAtom must be a mapping")
        return cls(
            atom_id=str(value.get("atom_id") or "atom:unknown"),
            predicate=str(value.get("predicate") or "unknown"),
            polarity=bool(value.get("polarity", True)),
            modality=value.get("modality"),
            labels=value.get("labels") or {},
        )

    @classmethod
    def from_normalized_proposition(
        cls, prop: NormalizedProposition
    ) -> "PropositionAtom":
        return cls(
            atom_id=prop.proposition_id,
            predicate=prop.predicate,
            polarity=True,
            modality=prop.modality.value if prop.modality else None,
            labels=dict(prop.labels),
        )


@dataclass(frozen=True, slots=True)
class AuthoritySupportRecord:
    """One authority candidate providing (or failing to provide) support."""

    support_id: str
    citation_surface: str
    citation_key: str | None
    resolution_state: str
    authority_rank: str
    version: str | None
    edition: str | None
    node_id: str | None
    record_id: str | None
    text_excerpt: str
    text_digest: str
    is_binding: bool
    is_superseded: bool
    is_withdrawn: bool
    effective_start: str | None
    effective_end: str | None
    content_sha256: str | None
    proposition_atoms: tuple[PropositionAtom, ...]
    reasons: tuple[str, ...]
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "support_id", _identifier(self.support_id, "support_id")
        )
        object.__setattr__(
            self,
            "citation_surface",
            _require_str(self.citation_surface, "citation_surface", max_len=512),
        )
        object.__setattr__(
            self,
            "citation_key",
            _optional_str(self.citation_key, "citation_key", max_len=256),
        )
        object.__setattr__(
            self,
            "resolution_state",
            _require_str(self.resolution_state, "resolution_state", max_len=64),
        )
        object.__setattr__(
            self,
            "authority_rank",
            _require_str(self.authority_rank, "authority_rank", max_len=64),
        )
        object.__setattr__(
            self, "version", _optional_str(self.version, "version", max_len=128)
        )
        object.__setattr__(
            self, "edition", _optional_str(self.edition, "edition", max_len=128)
        )
        object.__setattr__(
            self, "node_id", _optional_identifier(self.node_id, "node_id")
        )
        object.__setattr__(
            self, "record_id", _optional_identifier(self.record_id, "record_id")
        )
        if not isinstance(self.text_excerpt, str):
            raise TypeError("text_excerpt must be str")
        object.__setattr__(
            self, "text_excerpt", _truncate(self.text_excerpt, DEFAULT_MAX_EXCERPT)
        )
        digest = self.text_digest
        if not digest or not _SHA256_RE.match(str(digest).lower()):
            digest = (
                _text_digest(self.text_excerpt)
                if self.text_excerpt
                else sha256_hex("")
            )
        object.__setattr__(self, "text_digest", str(digest).lower())
        object.__setattr__(self, "is_binding", bool(self.is_binding))
        object.__setattr__(self, "is_superseded", bool(self.is_superseded))
        object.__setattr__(self, "is_withdrawn", bool(self.is_withdrawn))
        object.__setattr__(
            self,
            "effective_start",
            _optional_str(self.effective_start, "effective_start", max_len=32),
        )
        object.__setattr__(
            self,
            "effective_end",
            _optional_str(self.effective_end, "effective_end", max_len=32),
        )
        object.__setattr__(
            self,
            "content_sha256",
            _optional_sha256(self.content_sha256, "content_sha256"),
        )
        if not isinstance(self.proposition_atoms, tuple):
            object.__setattr__(
                self, "proposition_atoms", tuple(self.proposition_atoms or ())
            )
        object.__setattr__(
            self, "reasons", _tuple_of_str(self.reasons, "reasons", max_items=32)
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

    @property
    def has_exact_version(self) -> bool:
        return bool(self.version or self.edition)

    @property
    def is_controlling(self) -> bool:
        rank = (self.authority_rank or "").lower()
        if rank in _NON_CONTROLLING_RANKS:
            return False
        if not self.is_binding:
            return False
        if self.is_superseded or self.is_withdrawn:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_rank": self.authority_rank,
            "citation_key": self.citation_key,
            "citation_surface": self.citation_surface,
            "content_sha256": self.content_sha256,
            "edition": self.edition,
            "effective_end": self.effective_end,
            "effective_start": self.effective_start,
            "has_exact_version": self.has_exact_version,
            "is_binding": self.is_binding,
            "is_controlling": self.is_controlling,
            "is_superseded": self.is_superseded,
            "is_withdrawn": self.is_withdrawn,
            "labels": dict(self.labels),
            "node_id": self.node_id,
            "proposition_atoms": [a.to_dict() for a in self.proposition_atoms],
            "reasons": list(self.reasons),
            "record_id": self.record_id,
            "resolution_state": self.resolution_state,
            "support_id": self.support_id,
            "text_digest": self.text_digest,
            "text_excerpt": self.text_excerpt,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthoritySupportRecord":
        if not isinstance(value, Mapping):
            raise TypeError("AuthoritySupportRecord must be a mapping")
        return cls(
            support_id=str(value.get("support_id") or "support:unknown"),
            citation_surface=str(value.get("citation_surface") or "unknown"),
            citation_key=value.get("citation_key"),
            resolution_state=str(value.get("resolution_state") or "unknown"),
            authority_rank=str(value.get("authority_rank") or "unknown"),
            version=value.get("version"),
            edition=value.get("edition"),
            node_id=value.get("node_id"),
            record_id=value.get("record_id"),
            text_excerpt=str(value.get("text_excerpt") or ""),
            text_digest=str(value.get("text_digest") or ""),
            is_binding=bool(value.get("is_binding", False)),
            is_superseded=bool(value.get("is_superseded", False)),
            is_withdrawn=bool(value.get("is_withdrawn", False)),
            effective_start=value.get("effective_start"),
            effective_end=value.get("effective_end"),
            content_sha256=value.get("content_sha256"),
            proposition_atoms=tuple(
                PropositionAtom.from_dict(a)
                for a in (value.get("proposition_atoms") or ())
            ),
            reasons=tuple(value.get("reasons") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class DeterministicRuleReceipt:
    """Receipt that a documented deterministic rule was evaluated."""

    rule_key: str
    rule_id: str
    rule_version: str
    rule_digest: str
    applied: bool
    preconditions_met: tuple[str, ...]
    preconditions_failed: tuple[str, ...]
    description: str
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "rule_key", _require_str(self.rule_key, "rule_key", max_len=128)
        )
        object.__setattr__(
            self, "rule_id", _require_str(self.rule_id, "rule_id", max_len=128)
        )
        object.__setattr__(
            self,
            "rule_version",
            _require_str(self.rule_version, "rule_version", max_len=32),
        )
        object.__setattr__(
            self, "rule_digest", _sha256_hex_field(self.rule_digest, "rule_digest")
        )
        object.__setattr__(self, "applied", bool(self.applied))
        object.__setattr__(
            self,
            "preconditions_met",
            _tuple_of_str(self.preconditions_met, "preconditions_met", max_items=32),
        )
        object.__setattr__(
            self,
            "preconditions_failed",
            _tuple_of_str(
                self.preconditions_failed, "preconditions_failed", max_items=32
            ),
        )
        object.__setattr__(
            self,
            "description",
            _require_str(self.description, "description", max_len=1024),
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "description": self.description,
            "labels": dict(self.labels),
            "preconditions_failed": list(self.preconditions_failed),
            "preconditions_met": list(self.preconditions_met),
            "rule_digest": self.rule_digest,
            "rule_id": self.rule_id,
            "rule_key": self.rule_key,
            "rule_version": self.rule_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeterministicRuleReceipt":
        if not isinstance(value, Mapping):
            raise TypeError("DeterministicRuleReceipt must be a mapping")
        return cls(
            rule_key=str(value.get("rule_key") or ""),
            rule_id=str(value.get("rule_id") or ""),
            rule_version=str(value.get("rule_version") or "1"),
            rule_digest=str(value.get("rule_digest") or ("0" * 64)),
            applied=bool(value.get("applied", False)),
            preconditions_met=tuple(value.get("preconditions_met") or ()),
            preconditions_failed=tuple(value.get("preconditions_failed") or ()),
            description=str(value.get("description") or "documented rule"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ProofSupportReceipt:
    """Privacy-safe proof support receipt (identifiers/outcomes only)."""

    receipt_id: str
    outcome: str
    reason_codes: tuple[str, ...]
    engine_id: str | None
    engine_version: str | None
    config_digest: str | None
    problem_id: str | None
    premise_ids: tuple[str, ...]
    countermodel_ids: tuple[str, ...]
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "outcome", _require_str(self.outcome, "outcome", max_len=64)
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self, "engine_id", _optional_str(self.engine_id, "engine_id", max_len=128)
        )
        object.__setattr__(
            self,
            "engine_version",
            _optional_str(self.engine_version, "engine_version", max_len=64),
        )
        object.__setattr__(
            self,
            "config_digest",
            _optional_sha256(self.config_digest, "config_digest"),
        )
        object.__setattr__(
            self,
            "problem_id",
            _optional_identifier(self.problem_id, "problem_id"),
        )
        object.__setattr__(
            self,
            "premise_ids",
            _tuple_of_str(self.premise_ids, "premise_ids", max_items=128),
        )
        object.__setattr__(
            self,
            "countermodel_ids",
            _tuple_of_str(self.countermodel_ids, "countermodel_ids", max_items=32),
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

    @property
    def is_proved(self) -> bool:
        return self.outcome == ProofOutcome.PROVED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_digest": self.config_digest,
            "countermodel_ids": list(self.countermodel_ids),
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "is_proved": self.is_proved,
            "labels": dict(self.labels),
            "outcome": self.outcome,
            "premise_ids": list(self.premise_ids),
            "problem_id": self.problem_id,
            "reason_codes": list(self.reason_codes),
            "receipt_id": self.receipt_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofSupportReceipt":
        if not isinstance(value, Mapping):
            raise TypeError("ProofSupportReceipt must be a mapping")
        return cls(
            receipt_id=str(value.get("receipt_id") or "proof:unknown"),
            outcome=str(value.get("outcome") or ProofOutcome.UNKNOWN.value),
            reason_codes=tuple(value.get("reason_codes") or ()),
            engine_id=value.get("engine_id"),
            engine_version=value.get("engine_version"),
            config_digest=value.get("config_digest"),
            problem_id=value.get("problem_id"),
            premise_ids=tuple(value.get("premise_ids") or ()),
            countermodel_ids=tuple(value.get("countermodel_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class HumanReviewBoundary:
    """Explicit human-review boundary for a finding or result."""

    requires_human_review: bool
    is_final_legal_determination: bool
    review_state: ReviewState
    boundary_reason: str
    review_question: str
    confidence: float | None
    may_auto_pass: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "requires_human_review", bool(self.requires_human_review)
        )
        # Hard invariant: this module never makes a final legal determination.
        object.__setattr__(self, "is_final_legal_determination", False)
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self,
            "boundary_reason",
            _require_str(self.boundary_reason, "boundary_reason", max_len=512),
        )
        object.__setattr__(
            self,
            "review_question",
            _require_str(self.review_question, "review_question", max_len=2048),
        )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(self, "may_auto_pass", bool(self.may_auto_pass))

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary_reason": self.boundary_reason,
            "confidence": self.confidence,
            "is_final_legal_determination": False,
            "may_auto_pass": self.may_auto_pass,
            "requires_human_review": self.requires_human_review,
            "review_question": self.review_question,
            "review_state": self.review_state.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanReviewBoundary":
        if not isinstance(value, Mapping):
            raise TypeError("HumanReviewBoundary must be a mapping")
        return cls(
            requires_human_review=bool(value.get("requires_human_review", True)),
            is_final_legal_determination=False,
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            boundary_reason=str(
                value.get("boundary_reason") or "human_review_required"
            ),
            review_question=str(
                value.get("review_question") or "Human review required."
            ),
            confidence=value.get("confidence"),
            may_auto_pass=bool(value.get("may_auto_pass", False)),
        )


def build_human_review_question(
    *,
    unit_id: str,
    verdict: SemanticVerdict,
    citation_surfaces: Sequence[str],
    authority_versions: Sequence[str],
) -> str:
    cites = ", ".join(citation_surfaces[:4]) if citation_surfaces else "unresolved citation"
    versions = (
        ", ".join(authority_versions[:4]) if authority_versions else "version unknown"
    )
    if verdict is SemanticVerdict.WRONG_PROPOSITION:
        return (
            f"Human review required: instruction unit {unit_id} cites {cites} at "
            f"version(s) {versions}, but the claimed proposition is not supported "
            f"by the resolved authority text. Compare exact proposition atoms to "
            f"exact authority spans. This is not a determination of unlawful conduct."
        )
    if verdict is SemanticVerdict.SUPERSEDED_AUTHORITY:
        return (
            f"Human review required: authority for unit {unit_id} ({cites}) appears "
            f"superseded or withdrawn relative to the analysis as-of date. Resolve "
            f"current binding text before any legal conclusion."
        )
    if verdict is SemanticVerdict.CONFLICTING_AUTHORITY:
        return (
            f"Human review required: conflicting authority records for unit {unit_id} "
            f"({cites}) at version(s) {versions}. Competing sources are shown; do not "
            f"collapse them into a silent pick."
        )
    if verdict is SemanticVerdict.MISSING_AUTHORITY:
        return (
            f"Human review required: no resolved authority for unit {unit_id} "
            f"({cites}). Missing authority cannot pass consistency."
        )
    if verdict is SemanticVerdict.CLERICAL_MISMATCH:
        return (
            f"Human review required: clerical surface mismatch for unit {unit_id} "
            f"({cites}). Confirm the intended citation key and exact version."
        )
    if verdict is SemanticVerdict.UNSUPPORTED_INSTRUCTION:
        return (
            f"Human review required: instruction unit {unit_id} lacks proposition-level "
            f"support from controlling authority ({cites}; {versions}). Guidance alone "
            f"is not controlling law."
        )
    if verdict is SemanticVerdict.AMBIGUITY:
        return (
            f"Human review required: authority resolution is ambiguous for unit "
            f"{unit_id} ({cites}). Resolve ambiguity before any legal conclusion."
        )
    if verdict is SemanticVerdict.VERIFIED_CONSISTENT:
        return (
            f"Optional review: unit {unit_id} has proposition-level support plus "
            f"proof or a documented deterministic rule for {cites} at version(s) "
            f"{versions}. Confirm as-of applicability if material. This is not a "
            f"final legal determination."
        )
    return (
        f"Human review required: semantic assurance incomplete for unit {unit_id} "
        f"({cites}; {versions}). This is not a determination of unlawful conduct."
    )


@dataclass(frozen=True, slots=True)
class SemanticFinding:
    """One instruction / deadline / act / exception / proposition finding."""

    schema_version: str
    finding_id: str
    unit_id: str
    finding_kind: FindingKind
    verdict: SemanticVerdict
    instruction_span_id: str | None
    instruction_surface_text: str
    instruction_text_digest: str
    claimed_atoms: tuple[PropositionAtom, ...]
    supported_atoms: tuple[PropositionAtom, ...]
    unsupported_atoms: tuple[PropositionAtom, ...]
    authority_supports: tuple[AuthoritySupportRecord, ...]
    sources: tuple[ExactSourceRef, ...]
    assumptions: tuple[str, ...]
    counterexamples: tuple[ExactSourceRef, ...]
    support_kind: SupportKind
    deterministic_rule_receipts: tuple[DeterministicRuleReceipt, ...]
    proof_receipt: ProofSupportReceipt | None
    human_review: HumanReviewBoundary
    confidence: float | None
    reason_codes: tuple[str, ...]
    citation_surfaces: tuple[str, ...]
    authority_versions: tuple[str, ...]
    authority_node_ids: tuple[str, ...]
    classification: DisclosureClassification
    labels: Mapping[str, str]
    declares_unlawful_conduct: bool
    is_model_summary_substitution: bool
    is_pass: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION:
            raise ValueError(
                "SemanticFinding.schema_version must be "
                f"{SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "finding_id", _identifier(self.finding_id, "finding_id")
        )
        object.__setattr__(self, "unit_id", _identifier(self.unit_id, "unit_id"))
        object.__setattr__(
            self,
            "finding_kind",
            _coerce_enum(FindingKind, self.finding_kind, "finding_kind"),
        )
        object.__setattr__(
            self, "verdict", _coerce_enum(SemanticVerdict, self.verdict, "verdict")
        )
        object.__setattr__(
            self,
            "instruction_span_id",
            _optional_identifier(self.instruction_span_id, "instruction_span_id"),
        )
        if not isinstance(self.instruction_surface_text, str):
            raise TypeError("instruction_surface_text must be str")
        object.__setattr__(
            self,
            "instruction_surface_text",
            _truncate(self.instruction_surface_text, DEFAULT_MAX_SURFACE),
        )
        digest = self.instruction_text_digest
        if not digest or not _SHA256_RE.match(str(digest).lower()):
            digest = (
                _text_digest(self.instruction_surface_text)
                if self.instruction_surface_text
                else sha256_hex("")
            )
        object.__setattr__(self, "instruction_text_digest", str(digest).lower())
        for name in (
            "claimed_atoms",
            "supported_atoms",
            "unsupported_atoms",
            "authority_supports",
            "sources",
            "counterexamples",
            "deterministic_rule_receipts",
        ):
            val = getattr(self, name)
            if not isinstance(val, tuple):
                object.__setattr__(self, name, tuple(val or ()))
        object.__setattr__(
            self,
            "assumptions",
            _tuple_of_str(self.assumptions, "assumptions", max_items=64),
        )
        object.__setattr__(
            self,
            "support_kind",
            _coerce_enum(SupportKind, self.support_kind, "support_kind"),
        )
        if self.proof_receipt is not None and not isinstance(
            self.proof_receipt, ProofSupportReceipt
        ):
            raise TypeError("proof_receipt must be ProofSupportReceipt or None")
        if not isinstance(self.human_review, HumanReviewBoundary):
            raise TypeError("human_review must be HumanReviewBoundary")
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self,
            "citation_surfaces",
            _tuple_of_str(self.citation_surfaces, "citation_surfaces", max_items=64),
        )
        object.__setattr__(
            self,
            "authority_versions",
            _tuple_of_str(self.authority_versions, "authority_versions", max_items=64),
        )
        object.__setattr__(
            self,
            "authority_node_ids",
            _tuple_of_str(self.authority_node_ids, "authority_node_ids", max_items=64),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        cleaned, _ = sanitize_labels(dict(self.labels) if self.labels else {})
        object.__setattr__(self, "labels", cleaned)
        if not isinstance(self.declares_unlawful_conduct, bool):
            raise TypeError("declares_unlawful_conduct must be bool")
        if self.declares_unlawful_conduct:
            raise ValueError(
                "declares_unlawful_conduct must be False — never declare unlawful conduct"
            )
        if not isinstance(self.is_model_summary_substitution, bool):
            raise TypeError("is_model_summary_substitution must be bool")
        if self.is_model_summary_substitution:
            raise ValueError(
                "is_model_summary_substitution must be False — model summaries "
                "are never substituted for government or governing text"
            )
        # Pass invariant: only verified_consistent with support may pass.
        may_pass = (
            self.verdict is SemanticVerdict.VERIFIED_CONSISTENT
            and self.support_kind
            in (SupportKind.PROOF_RECEIPT, SupportKind.DETERMINISTIC_RULE)
            and (
                (
                    self.proof_receipt is not None
                    and self.proof_receipt.is_proved
                    and self.support_kind is SupportKind.PROOF_RECEIPT
                )
                or (
                    self.support_kind is SupportKind.DETERMINISTIC_RULE
                    and any(r.applied for r in self.deterministic_rule_receipts)
                )
            )
        )
        object.__setattr__(self, "is_pass", bool(may_pass and bool(self.is_pass)))
        if self.verdict is SemanticVerdict.VERIFIED_CONSISTENT and not may_pass:
            raise ValueError(
                "verified_consistent requires proposition-level support plus "
                "proof receipt or applied documented deterministic rule"
            )
        if self.is_pass and self.verdict is not SemanticVerdict.VERIFIED_CONSISTENT:
            raise ValueError("is_pass requires verified_consistent verdict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "authority_node_ids": list(self.authority_node_ids),
            "authority_supports": [a.to_dict() for a in self.authority_supports],
            "authority_versions": list(self.authority_versions),
            "citation_surfaces": list(self.citation_surfaces),
            "claimed_atoms": [a.to_dict() for a in self.claimed_atoms],
            "classification": self.classification.value,
            "confidence": self.confidence,
            "counterexamples": [c.to_dict() for c in self.counterexamples],
            "declares_unlawful_conduct": False,
            "deterministic_rule_receipts": [
                r.to_dict() for r in self.deterministic_rule_receipts
            ],
            "finding_id": self.finding_id,
            "finding_kind": self.finding_kind.value,
            "human_review": self.human_review.to_dict(),
            "instruction_span_id": self.instruction_span_id,
            "instruction_surface_text": self.instruction_surface_text,
            "instruction_text_digest": self.instruction_text_digest,
            "is_model_summary_substitution": False,
            "is_pass": self.is_pass,
            "labels": dict(self.labels),
            "proof_receipt": (
                self.proof_receipt.to_dict() if self.proof_receipt else None
            ),
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "sources": [s.to_dict() for s in self.sources],
            "support_kind": self.support_kind.value,
            "supported_atoms": [a.to_dict() for a in self.supported_atoms],
            "unit_id": self.unit_id,
            "unsupported_atoms": [a.to_dict() for a in self.unsupported_atoms],
            "verdict": self.verdict.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticFinding":
        if not isinstance(value, Mapping):
            raise TypeError("SemanticFinding must be a mapping")
        proof_raw = value.get("proof_receipt")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION
            ),
            finding_id=str(value.get("finding_id") or ""),
            unit_id=str(value.get("unit_id") or ""),
            finding_kind=value.get("finding_kind", FindingKind.INSTRUCTION.value),
            verdict=value.get("verdict", SemanticVerdict.UNKNOWN.value),
            instruction_span_id=value.get("instruction_span_id"),
            instruction_surface_text=str(
                value.get("instruction_surface_text") or ""
            ),
            instruction_text_digest=str(
                value.get("instruction_text_digest") or ""
            ),
            claimed_atoms=tuple(
                PropositionAtom.from_dict(a)
                for a in (value.get("claimed_atoms") or ())
            ),
            supported_atoms=tuple(
                PropositionAtom.from_dict(a)
                for a in (value.get("supported_atoms") or ())
            ),
            unsupported_atoms=tuple(
                PropositionAtom.from_dict(a)
                for a in (value.get("unsupported_atoms") or ())
            ),
            authority_supports=tuple(
                AuthoritySupportRecord.from_dict(a)
                for a in (value.get("authority_supports") or ())
            ),
            sources=tuple(
                ExactSourceRef.from_dict(s) for s in (value.get("sources") or ())
            ),
            assumptions=tuple(value.get("assumptions") or ()),
            counterexamples=tuple(
                ExactSourceRef.from_dict(c)
                for c in (value.get("counterexamples") or ())
            ),
            support_kind=value.get("support_kind", SupportKind.NONE.value),
            deterministic_rule_receipts=tuple(
                DeterministicRuleReceipt.from_dict(r)
                for r in (value.get("deterministic_rule_receipts") or ())
            ),
            proof_receipt=(
                ProofSupportReceipt.from_dict(proof_raw)
                if isinstance(proof_raw, Mapping)
                else None
            ),
            human_review=HumanReviewBoundary.from_dict(
                value.get("human_review") or {}
            ),
            confidence=value.get("confidence"),
            reason_codes=tuple(value.get("reason_codes") or ()),
            citation_surfaces=tuple(value.get("citation_surfaces") or ()),
            authority_versions=tuple(value.get("authority_versions") or ()),
            authority_node_ids=tuple(value.get("authority_node_ids") or ()),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
            declares_unlawful_conduct=bool(
                value.get("declares_unlawful_conduct", False)
            ),
            is_model_summary_substitution=bool(
                value.get("is_model_summary_substitution", False)
            ),
            is_pass=bool(value.get("is_pass", False)),
        )


@dataclass(frozen=True, slots=True)
class InstructionCheckUnit:
    """One unit to verify: instruction, deadline basis, act, exception, or proposition."""

    unit_id: str
    finding_kind: FindingKind
    instruction_span_id: str | None
    instruction_surface_text: str
    instruction_text_digest: str | None
    legal_citations: tuple[str, ...]
    citation_keys: tuple[str, ...]
    claimed_atoms: tuple[PropositionAtom, ...]
    quoted_authority_text: str | None
    deadline_basis: str | None
    required_act: str | None
    exceptions: tuple[str, ...]
    applicability_conditions: tuple[str, ...]
    assumptions: tuple[str, ...]
    authority_supports: tuple[AuthoritySupportRecord, ...]
    legal_ir_mapping: LegalIRMapping | None
    confidence: float | None
    classification: DisclosureClassification
    labels: Mapping[str, str]
    # Test/control flags for compact fixtures (never inferred silently).
    force_clerical_mismatch: bool = False
    force_skip_proof: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit_id", _identifier(self.unit_id, "unit_id"))
        object.__setattr__(
            self,
            "finding_kind",
            _coerce_enum(FindingKind, self.finding_kind, "finding_kind"),
        )
        object.__setattr__(
            self,
            "instruction_span_id",
            _optional_identifier(self.instruction_span_id, "instruction_span_id"),
        )
        if not isinstance(self.instruction_surface_text, str):
            raise TypeError("instruction_surface_text must be str")
        object.__setattr__(
            self,
            "instruction_surface_text",
            _truncate(self.instruction_surface_text, DEFAULT_MAX_SURFACE),
        )
        digest = self.instruction_text_digest
        if not digest or not _SHA256_RE.match(str(digest).lower()):
            digest = (
                _text_digest(self.instruction_surface_text)
                if self.instruction_surface_text
                else sha256_hex("")
            )
        object.__setattr__(self, "instruction_text_digest", str(digest).lower())
        object.__setattr__(
            self,
            "legal_citations",
            _tuple_of_str(self.legal_citations, "legal_citations", max_items=64),
        )
        object.__setattr__(
            self,
            "citation_keys",
            _tuple_of_str(self.citation_keys, "citation_keys", max_items=64),
        )
        if not isinstance(self.claimed_atoms, tuple):
            object.__setattr__(
                self, "claimed_atoms", tuple(self.claimed_atoms or ())
            )
        object.__setattr__(
            self,
            "quoted_authority_text",
            _optional_str(
                self.quoted_authority_text, "quoted_authority_text", max_len=DEFAULT_MAX_EXCERPT
            ),
        )
        object.__setattr__(
            self,
            "deadline_basis",
            _optional_str(self.deadline_basis, "deadline_basis", max_len=512),
        )
        object.__setattr__(
            self,
            "required_act",
            _optional_str(self.required_act, "required_act", max_len=512),
        )
        object.__setattr__(
            self,
            "exceptions",
            _tuple_of_str(self.exceptions, "exceptions", max_items=32),
        )
        object.__setattr__(
            self,
            "applicability_conditions",
            _tuple_of_str(
                self.applicability_conditions, "applicability_conditions", max_items=64
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            _tuple_of_str(self.assumptions, "assumptions", max_items=64),
        )
        if not isinstance(self.authority_supports, tuple):
            object.__setattr__(
                self, "authority_supports", tuple(self.authority_supports or ())
            )
        if self.legal_ir_mapping is not None and not isinstance(
            self.legal_ir_mapping, LegalIRMapping
        ):
            raise TypeError("legal_ir_mapping must be LegalIRMapping or None")
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        cleaned, _ = sanitize_labels(dict(self.labels) if self.labels else {})
        object.__setattr__(self, "labels", cleaned)
        object.__setattr__(
            self, "force_clerical_mismatch", bool(self.force_clerical_mismatch)
        )
        object.__setattr__(self, "force_skip_proof", bool(self.force_skip_proof))

    def to_dict(self) -> dict[str, Any]:
        return {
            "applicability_conditions": list(self.applicability_conditions),
            "assumptions": list(self.assumptions),
            "authority_supports": [a.to_dict() for a in self.authority_supports],
            "citation_keys": list(self.citation_keys),
            "claimed_atoms": [a.to_dict() for a in self.claimed_atoms],
            "classification": self.classification.value,
            "confidence": self.confidence,
            "deadline_basis": self.deadline_basis,
            "exceptions": list(self.exceptions),
            "finding_kind": self.finding_kind.value,
            "force_clerical_mismatch": self.force_clerical_mismatch,
            "force_skip_proof": self.force_skip_proof,
            "instruction_span_id": self.instruction_span_id,
            "instruction_surface_text": self.instruction_surface_text,
            "instruction_text_digest": self.instruction_text_digest,
            "labels": dict(self.labels),
            "legal_citations": list(self.legal_citations),
            "legal_ir_mapping": (
                self.legal_ir_mapping.to_dict()
                if self.legal_ir_mapping is not None
                and hasattr(self.legal_ir_mapping, "to_dict")
                else None
            ),
            "quoted_authority_text": self.quoted_authority_text,
            "required_act": self.required_act,
            "unit_id": self.unit_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InstructionCheckUnit":
        if not isinstance(value, Mapping):
            raise TypeError("InstructionCheckUnit must be a mapping")
        mapping_raw = value.get("legal_ir_mapping")
        mapping: LegalIRMapping | None = None
        if isinstance(mapping_raw, LegalIRMapping):
            mapping = mapping_raw
        elif isinstance(mapping_raw, Mapping) and mapping_raw:
            # Optional; ignore if incomplete.
            try:
                mapping = LegalIRMapping.from_dict(mapping_raw)  # type: ignore[attr-defined]
            except Exception:
                mapping = None
        return cls(
            unit_id=str(value.get("unit_id") or ""),
            finding_kind=value.get("finding_kind", FindingKind.INSTRUCTION.value),
            instruction_span_id=value.get("instruction_span_id"),
            instruction_surface_text=str(
                value.get("instruction_surface_text") or ""
            ),
            instruction_text_digest=value.get("instruction_text_digest"),
            legal_citations=tuple(value.get("legal_citations") or ()),
            citation_keys=tuple(value.get("citation_keys") or ()),
            claimed_atoms=tuple(
                PropositionAtom.from_dict(a)
                for a in (value.get("claimed_atoms") or ())
            ),
            quoted_authority_text=value.get("quoted_authority_text"),
            deadline_basis=value.get("deadline_basis"),
            required_act=value.get("required_act"),
            exceptions=tuple(value.get("exceptions") or ()),
            applicability_conditions=tuple(
                value.get("applicability_conditions") or ()
            ),
            assumptions=tuple(value.get("assumptions") or ()),
            authority_supports=tuple(
                AuthoritySupportRecord.from_dict(a)
                for a in (value.get("authority_supports") or ())
            ),
            legal_ir_mapping=mapping,
            confidence=value.get("confidence"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
            force_clerical_mismatch=bool(value.get("force_clerical_mismatch", False)),
            force_skip_proof=bool(value.get("force_skip_proof", False)),
        )


@dataclass(frozen=True, slots=True)
class SemanticConsistencyInput:
    """Input packet for semantic instruction consistency analysis."""

    artifact_id: str
    units: tuple[InstructionCheckUnit, ...] = ()
    classification: DisclosureClassification = DisclosureClassification.UNKNOWN
    as_of: str | date | None = None
    analysis_id: str | None = None
    matter_id: str | None = None
    snapshot_id: str | None = None
    run_proofs: bool = True
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        if not isinstance(self.units, tuple):
            object.__setattr__(self, "units", tuple(self.units or ()))
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        if isinstance(self.as_of, date) and not isinstance(self.as_of, datetime):
            object.__setattr__(self, "as_of", self.as_of.isoformat())
        elif self.as_of is not None:
            object.__setattr__(
                self, "as_of", _optional_str(str(self.as_of), "as_of", max_len=64)
            )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "snapshot_id", _optional_identifier(self.snapshot_id, "snapshot_id")
        )
        object.__setattr__(self, "run_proofs", bool(self.run_proofs))
        cleaned, _ = sanitize_labels(dict(self.labels) if self.labels else {})
        object.__setattr__(self, "labels", cleaned)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "artifact_id": self.artifact_id,
            "as_of": self.as_of,
            "classification": self.classification.value,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "run_proofs": self.run_proofs,
            "snapshot_id": self.snapshot_id,
            "units": [u.to_dict() for u in self.units],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticConsistencyInput":
        if not isinstance(value, Mapping):
            raise TypeError("SemanticConsistencyInput must be a mapping")
        return cls(
            artifact_id=str(value.get("artifact_id") or "artifact:unknown"),
            units=tuple(
                InstructionCheckUnit.from_dict(u)
                for u in (value.get("units") or ())
            ),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            as_of=value.get("as_of"),
            analysis_id=value.get("analysis_id"),
            matter_id=value.get("matter_id"),
            snapshot_id=value.get("snapshot_id"),
            run_proofs=bool(value.get("run_proofs", True)),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class SemanticConsistencyResult:
    """Result of semantic instruction consistency analysis."""

    schema_version: str
    analysis_id: str
    source_artifact_id: str
    matter_id: str | None
    disposition: SemanticDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    output_kind: str
    disclaimer: str
    declares_unlawful_conduct: bool
    is_model_summary_substitution: bool
    is_final_legal_determination: bool
    is_pass: bool
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    findings: tuple[SemanticFinding, ...]
    pass_count: int
    fail_count: int
    review_count: int
    ruleset_versions: Mapping[str, str]
    documented_rules: tuple[str, ...]
    snapshot_id: str | None
    as_of: str | None
    labels: Mapping[str, str]
    text_digest: str
    human_review: HumanReviewBoundary

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION:
            raise ValueError(
                "SemanticConsistencyResult.schema_version must be "
                f"{SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "analysis_id", _identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self,
            "source_artifact_id",
            _identifier(self.source_artifact_id, "source_artifact_id"),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(SemanticDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=2048),
        )
        if self.declares_unlawful_conduct:
            raise ValueError("declares_unlawful_conduct must be False")
        if self.is_model_summary_substitution:
            raise ValueError("is_model_summary_substitution must be False")
        object.__setattr__(self, "is_final_legal_determination", False)
        object.__setattr__(self, "is_pass", bool(self.is_pass))
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=128),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=64)
        )
        if not isinstance(self.findings, tuple):
            object.__setattr__(self, "findings", tuple(self.findings or ()))
        object.__setattr__(
            self, "pass_count", _nonneg_int(self.pass_count, "pass_count")
        )
        object.__setattr__(
            self, "fail_count", _nonneg_int(self.fail_count, "fail_count")
        )
        object.__setattr__(
            self, "review_count", _nonneg_int(self.review_count, "review_count")
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=32),
        )
        object.__setattr__(
            self,
            "documented_rules",
            _tuple_of_str(self.documented_rules, "documented_rules", max_items=32),
        )
        object.__setattr__(
            self, "snapshot_id", _optional_identifier(self.snapshot_id, "snapshot_id")
        )
        object.__setattr__(
            self, "as_of", _optional_str(self.as_of, "as_of", max_len=64)
        )
        cleaned, _ = sanitize_labels(dict(self.labels) if self.labels else {})
        object.__setattr__(self, "labels", cleaned)
        object.__setattr__(
            self, "text_digest", _sha256_hex_field(self.text_digest, "text_digest")
        )
        if not isinstance(self.human_review, HumanReviewBoundary):
            raise TypeError("human_review must be HumanReviewBoundary")
        # Global pass requires every finding to pass and disposition assured.
        if self.is_pass:
            if self.disposition is not SemanticDisposition.ASSURED:
                raise ValueError("is_pass requires disposition assured")
            if any(not f.is_pass for f in self.findings):
                raise ValueError("is_pass requires every finding to pass")
            if not self.findings:
                raise ValueError("is_pass requires at least one finding")

    def findings_by_verdict(
        self, verdict: SemanticVerdict | str
    ) -> tuple[SemanticFinding, ...]:
        v = _coerce_enum(SemanticVerdict, verdict, "verdict")
        return tuple(f for f in self.findings if f.verdict is v)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "as_of": self.as_of,
            "classification": self.classification.value,
            "declares_unlawful_conduct": False,
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "documented_rules": list(self.documented_rules),
            "fail_count": self.fail_count,
            "findings": [f.to_dict() for f in self.findings],
            "human_review": self.human_review.to_dict(),
            "is_final_legal_determination": False,
            "is_model_summary_substitution": False,
            "is_pass": self.is_pass,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "pass_count": self.pass_count,
            "reason_codes": list(self.reason_codes),
            "review_count": self.review_count,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "source_artifact_id": self.source_artifact_id,
            "text_digest": self.text_digest,
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifiers and counts only — no instruction/authority body text."""
        return {
            "analysis_id": self.analysis_id,
            "as_of": self.as_of,
            "classification": self.classification.value,
            "declares_unlawful_conduct": False,
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "documented_rules": list(self.documented_rules),
            "fail_count": self.fail_count,
            "finding_count": len(self.findings),
            "finding_ids": [f.finding_id for f in self.findings],
            "human_review": {
                "requires_human_review": self.human_review.requires_human_review,
                "is_final_legal_determination": False,
                "review_state": self.human_review.review_state.value,
                "may_auto_pass": self.human_review.may_auto_pass,
                "boundary_reason": self.human_review.boundary_reason,
            },
            "is_final_legal_determination": False,
            "is_model_summary_substitution": False,
            "is_pass": self.is_pass,
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "pass_count": self.pass_count,
            "reason_codes": list(self.reason_codes),
            "review_count": self.review_count,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "source_artifact_id": self.source_artifact_id,
            "text_digest": self.text_digest,
            "verdicts": [f.verdict.value for f in self.findings],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticConsistencyResult":
        if not isinstance(value, Mapping):
            raise TypeError("SemanticConsistencyResult must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION
            ),
            analysis_id=str(value.get("analysis_id") or ""),
            source_artifact_id=str(value.get("source_artifact_id") or ""),
            matter_id=value.get("matter_id"),
            disposition=value.get(
                "disposition", SemanticDisposition.UNKNOWN.value
            ),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_SEMANTIC_INSTRUCTION_ASSURANCE
            ),
            disclaimer=value.get(
                "disclaimer", NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER
            ),
            declares_unlawful_conduct=bool(
                value.get("declares_unlawful_conduct", False)
            ),
            is_model_summary_substitution=bool(
                value.get("is_model_summary_substitution", False)
            ),
            is_final_legal_determination=False,
            is_pass=bool(value.get("is_pass", False)),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            findings=tuple(
                SemanticFinding.from_dict(f) for f in (value.get("findings") or ())
            ),
            pass_count=int(value.get("pass_count", 0)),
            fail_count=int(value.get("fail_count", 0)),
            review_count=int(value.get("review_count", 0)),
            ruleset_versions=value.get("ruleset_versions") or {},
            documented_rules=tuple(value.get("documented_rules") or ()),
            snapshot_id=value.get("snapshot_id"),
            as_of=value.get("as_of"),
            labels=value.get("labels") or {},
            text_digest=str(value.get("text_digest") or sha256_hex("")),
            human_review=HumanReviewBoundary.from_dict(
                value.get("human_review") or {}
            ),
        )


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------


def _evaluate_rule(
    rule_key: str,
    *,
    preconditions: Mapping[str, bool],
) -> DeterministicRuleReceipt:
    rule = DOCUMENTED_DETERMINISTIC_RULES.get(rule_key)
    if rule is None:
        raise SemanticInstructionConsistencyError(
            f"unknown documented rule: {rule_key}",
            code="unknown_deterministic_rule",
        )
    required = tuple(rule.get("preconditions") or ())
    met: list[str] = []
    failed: list[str] = []
    for name in required:
        if preconditions.get(name):
            met.append(str(name))
        else:
            failed.append(str(name))
    applied = len(failed) == 0 and len(required) > 0
    return DeterministicRuleReceipt(
        rule_key=rule_key,
        rule_id=str(rule["rule_id"]),
        rule_version=str(rule["rule_version"]),
        rule_digest=str(rule["rule_digest"]),
        applied=applied,
        preconditions_met=tuple(met),
        preconditions_failed=tuple(failed),
        description=str(rule["description"]),
        labels={"deterministic": "true"},
    )


def _authority_atom_keys(
    supports: Sequence[AuthoritySupportRecord],
    *,
    controlling_only: bool = True,
) -> set[str]:
    keys: set[str] = set()
    for s in supports:
        if controlling_only and not s.is_controlling:
            continue
        for atom in s.proposition_atoms:
            keys.add(atom.key())
    return keys


def _match_atoms(
    claimed: Sequence[PropositionAtom],
    support_keys: set[str],
) -> tuple[tuple[PropositionAtom, ...], tuple[PropositionAtom, ...]]:
    supported: list[PropositionAtom] = []
    unsupported: list[PropositionAtom] = []
    for atom in claimed:
        if atom.key() in support_keys:
            supported.append(atom)
        else:
            unsupported.append(atom)
    return tuple(supported), tuple(unsupported)


def _detect_conflicts(
    supports: Sequence[AuthoritySupportRecord],
) -> bool:
    """True when same citation_key has multiple controlling content digests."""
    by_key: dict[str, set[str]] = {}
    for s in supports:
        if not s.citation_key:
            continue
        if s.is_superseded or s.is_withdrawn:
            continue
        digest = s.content_sha256 or s.text_digest
        if not digest:
            continue
        by_key.setdefault(s.citation_key, set()).add(digest)
    return any(len(digests) > 1 for digests in by_key.values())


def _any_superseded(supports: Sequence[AuthoritySupportRecord]) -> bool:
    return any(s.is_superseded or s.is_withdrawn for s in supports)


def _any_controlling(supports: Sequence[AuthoritySupportRecord]) -> bool:
    return any(s.is_controlling for s in supports)


def _any_exact_resolved(supports: Sequence[AuthoritySupportRecord]) -> bool:
    return any(
        s.resolution_state in ("resolved", "exact", AuthorityResolutionState.RESOLVED.value)
        and s.has_exact_version
        for s in supports
    )


def _guidance_only(supports: Sequence[AuthoritySupportRecord]) -> bool:
    if not supports:
        return False
    if _any_controlling(supports):
        return False
    return all(
        (s.authority_rank or "").lower() in _NON_CONTROLLING_RANKS
        or not s.is_binding
        for s in supports
    )


def _build_proof_receipt_for_unit(
    unit: InstructionCheckUnit,
    *,
    supported_atoms: Sequence[PropositionAtom],
    unsupported_atoms: Sequence[PropositionAtom],
    run_proofs: bool,
    analysis_id: str,
    seq: int,
) -> ProofSupportReceipt | None:
    if not run_proofs or unit.force_skip_proof:
        return None
    # If mapping is present and accepted, prefer mapping-based problem.
    if unit.legal_ir_mapping is not None:
        try:
            result = execute_legal_ir_proof(
                ProofExecutionRequest(
                    request_id=f"sic-proof:{analysis_id}:{seq:04d}",
                    mapping=unit.legal_ir_mapping,
                    classification=unit.classification,
                )
            )
            conclusion = result.conclusion
            return ProofSupportReceipt(
                receipt_id=result.request_id or f"proof:{analysis_id}:{seq:04d}",
                outcome=conclusion.outcome.value
                if hasattr(conclusion.outcome, "value")
                else str(conclusion.outcome),
                reason_codes=tuple(conclusion.reason_codes),
                engine_id=getattr(conclusion.engine, "engine_id", None)
                if conclusion.engine
                else None,
                engine_version=getattr(conclusion.engine, "engine_version", None)
                if conclusion.engine
                else None,
                config_digest=getattr(conclusion.engine, "config_digest", None)
                if conclusion.engine
                else None,
                problem_id=getattr(result.problem, "problem_id", None)
                if result.problem
                else None,
                premise_ids=tuple(
                    c.premise_id for c in (conclusion.premise_citations or ())
                ),
                countermodel_ids=tuple(
                    cm.countermodel_id for cm in (conclusion.countermodels or ())
                ),
                labels={"route": "mapping"},
            )
        except Exception:
            # Fall through to local atom entailment problem.
            pass

    if not supported_atoms and not unit.claimed_atoms:
        return None

    premises: list[AtomicLiteral] = []
    citations: list[PremiseCitation] = []
    for atom in supported_atoms:
        premises.append(AtomicLiteral(atom_id=atom.atom_id, polarity=atom.polarity))
        citations.append(
            PremiseCitation(
                premise_id=atom.atom_id,
                kind="proposition",
                digest=_text_digest(atom.predicate),
            )
        )
    # Goal: conjunction of claimed atoms represented as first claimed atom when
    # all are supported; if any unsupported, required premises include them
    # (incomplete → unknown).
    goal_atom = unit.claimed_atoms[0] if unit.claimed_atoms else (
        supported_atoms[0] if supported_atoms else None
    )
    if goal_atom is None:
        return None
    required = tuple(a.atom_id for a in unit.claimed_atoms) or (goal_atom.atom_id,)
    problem = ProofProblem(
        problem_id=f"sic:problem:{analysis_id}:{seq:04d}",
        logic_family=LogicFamily.ENTAILMENT_CHECK,
        goal=AtomicLiteral(atom_id=goal_atom.atom_id, polarity=goal_atom.polarity),
        premises=tuple(premises),
        required_premise_ids=required,
        assumption_ids=(),
        counter_evidence_ids=(),
        premise_citations=tuple(citations),
        classification=unit.classification,
        force_timeout=False,
        fixture_kind=None,
        labels={"source": "semantic_instruction_consistency"},
    )
    kernel = run_local_bounded_kernel(problem, max_steps=10_000, timeout_ms=5_000)
    return ProofSupportReceipt(
        receipt_id=f"proof:{analysis_id}:{seq:04d}",
        outcome=kernel.outcome.value,
        reason_codes=tuple(kernel.reason_codes),
        engine_id="uspto.local-bounded-proof-kernel@1",
        engine_version=LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
        config_digest=sha256_hex("local-bounded-v1"),
        problem_id=problem.problem_id,
        premise_ids=tuple(p.atom_id for p in premises),
        countermodel_ids=tuple(
            cm.countermodel_id for cm in (kernel.countermodels or ())
        ),
        labels={"route": "local_bounded_kernel"},
    )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class SemanticInstructionConsistencyProcessor:
    """Verify government instructions against authority and logic (PATLAW-134).

    Parameters
    ----------
    id_factory:
        Deterministic ID factory for tests.
    bounds:
        Safety bounds on output size.
    proof_executor:
        Optional shared executor; local kernel is used when omitted.
    """

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        bounds: AnalysisBounds | None = None,
        proof_executor: LegalIRProofExecutor | None = None,
    ) -> None:
        self._id_factory = id_factory or (
            lambda: f"sic:{uuid.uuid4().hex[:12]}"
        )
        self.bounds = bounds or AnalysisBounds()
        self.proof_executor = proof_executor

    def verify(
        self,
        value: SemanticConsistencyInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> SemanticConsistencyResult:
        """Verify instruction units against authority and logic."""
        inp = self._coerce_input(value, **kwargs)
        return self._verify(inp)

    # alias for symmetry with other processors
    def compare(
        self,
        value: SemanticConsistencyInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> SemanticConsistencyResult:
        return self.verify(value, **kwargs)

    def _coerce_input(
        self,
        value: Any,
        **kwargs: Any,
    ) -> SemanticConsistencyInput:
        if value is None and not kwargs:
            raise SemanticInstructionConsistencyError(
                "semantic consistency input is required", code="missing_input"
            )
        if isinstance(value, SemanticConsistencyInput):
            return value
        if isinstance(value, Mapping):
            merged = dict(value)
            merged.update(kwargs)
            return SemanticConsistencyInput.from_dict(merged)
        if kwargs:
            return SemanticConsistencyInput.from_dict(kwargs)
        raise SemanticInstructionConsistencyError(
            f"unsupported input type: {type(value).__name__}",
            code="invalid_input_type",
        )

    def _verify(self, inp: SemanticConsistencyInput) -> SemanticConsistencyResult:
        analysis_id = inp.analysis_id or self._id_factory()
        reason_codes: list[str] = [
            SemanticReasonCode.NOT_FINAL_LEGAL_DETERMINATION.value,
            SemanticReasonCode.NO_MODEL_SUMMARY_SUBSTITUTION.value,
            SemanticReasonCode.HUMAN_REVIEW_BOUNDARY_EXPOSED.value,
        ]
        warnings: list[str] = []
        classification = inp.classification

        if requires_quarantine(classification):
            reason_codes.append(SemanticReasonCode.QUARANTINED.value)
            boundary = HumanReviewBoundary(
                requires_human_review=True,
                is_final_legal_determination=False,
                review_state=ReviewState.REQUIRED,
                boundary_reason="disclosure_quarantine",
                review_question=(
                    "Quarantine required; human review before any semantic assurance."
                ),
                confidence=None,
                may_auto_pass=False,
            )
            return SemanticConsistencyResult(
                schema_version=SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
                analysis_id=analysis_id,
                source_artifact_id=inp.artifact_id,
                matter_id=inp.matter_id,
                disposition=SemanticDisposition.QUARANTINE,
                review_state=ReviewState.REQUIRED,
                classification=classification,
                output_kind=OUTPUT_KIND_SEMANTIC_INSTRUCTION_ASSURANCE,
                disclaimer=NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER,
                declares_unlawful_conduct=False,
                is_model_summary_substitution=False,
                is_final_legal_determination=False,
                is_pass=False,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                warnings=tuple(warnings),
                findings=(),
                pass_count=0,
                fail_count=0,
                review_count=0,
                ruleset_versions=self._ruleset_versions(),
                documented_rules=list_documented_rules(),
                snapshot_id=inp.snapshot_id,
                as_of=str(inp.as_of) if inp.as_of else None,
                labels=dict(inp.labels),
                text_digest=sha256_hex(analysis_id),
                human_review=boundary,
            )

        if not inp.as_of:
            reason_codes.append(SemanticReasonCode.AS_OF_UNKNOWN.value)
            warnings.append("as_of_unknown")

        findings: list[SemanticFinding] = []
        for seq, unit in enumerate(inp.units, start=1):
            if seq > self.bounds.max_findings:
                reason_codes.append(SemanticReasonCode.FINDING_LIMIT.value)
                warnings.append("finding_limit")
                break
            finding = self._verify_one(
                analysis_id=analysis_id,
                seq=seq,
                unit=unit,
                as_of=inp.as_of,
                run_proofs=inp.run_proofs,
                classification=classification,
            )
            findings.append(finding)
            reason_codes.extend(finding.reason_codes)

        if not findings:
            reason_codes.append(SemanticReasonCode.EMPTY_INPUT.value)
            boundary = HumanReviewBoundary(
                requires_human_review=True,
                is_final_legal_determination=False,
                review_state=ReviewState.PENDING,
                boundary_reason="empty_input",
                review_question="No instruction units provided for semantic assurance.",
                confidence=None,
                may_auto_pass=False,
            )
            return SemanticConsistencyResult(
                schema_version=SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
                analysis_id=analysis_id,
                source_artifact_id=inp.artifact_id,
                matter_id=inp.matter_id,
                disposition=SemanticDisposition.EMPTY,
                review_state=ReviewState.PENDING,
                classification=classification,
                output_kind=OUTPUT_KIND_SEMANTIC_INSTRUCTION_ASSURANCE,
                disclaimer=NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER,
                declares_unlawful_conduct=False,
                is_model_summary_substitution=False,
                is_final_legal_determination=False,
                is_pass=False,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                warnings=tuple(dict.fromkeys(warnings)),
                findings=(),
                pass_count=0,
                fail_count=0,
                review_count=0,
                ruleset_versions=self._ruleset_versions(),
                documented_rules=list_documented_rules(),
                snapshot_id=inp.snapshot_id,
                as_of=str(inp.as_of) if inp.as_of else None,
                labels=dict(inp.labels),
                text_digest=sha256_hex(analysis_id),
                human_review=boundary,
            )

        reason_codes.append(SemanticReasonCode.FINDINGS_EMITTED.value)
        reason_codes.append(SemanticReasonCode.SOURCES_EXPOSED.value)
        reason_codes.append(SemanticReasonCode.ASSUMPTIONS_RECORDED.value)
        reason_codes.append(SemanticReasonCode.CONFIDENCE_RECORDED.value)

        pass_count = sum(1 for f in findings if f.is_pass)
        fail_count = sum(
            1
            for f in findings
            if f.verdict
            in (
                SemanticVerdict.WRONG_PROPOSITION,
                SemanticVerdict.SUPERSEDED_AUTHORITY,
                SemanticVerdict.CONFLICTING_AUTHORITY,
                SemanticVerdict.MISSING_AUTHORITY,
                SemanticVerdict.UNSUPPORTED_INSTRUCTION,
                SemanticVerdict.CLERICAL_MISMATCH,
            )
        )
        review_count = sum(1 for f in findings if f.human_review.requires_human_review)

        all_pass = pass_count == len(findings) and len(findings) > 0
        any_fail = fail_count > 0
        any_review = review_count > 0

        if all_pass:
            disposition = SemanticDisposition.ASSURED
            review_state = ReviewState.NOT_REQUIRED
            # Still not a final legal determination; optional review remains.
            is_pass = True
        elif any_fail and pass_count == 0:
            disposition = SemanticDisposition.FAILED
            review_state = ReviewState.REQUIRED
            is_pass = False
        elif pass_count > 0 and (any_fail or any_review):
            disposition = SemanticDisposition.PARTIAL
            review_state = ReviewState.REQUIRED
            is_pass = False
        elif any_review:
            disposition = SemanticDisposition.REVIEW
            review_state = ReviewState.REQUIRED
            is_pass = False
        else:
            disposition = SemanticDisposition.UNKNOWN
            review_state = ReviewState.REQUIRED
            is_pass = False

        if any_review or not is_pass:
            reason_codes.append(SemanticReasonCode.HUMAN_REVIEW_REQUIRED.value)

        # Aggregate confidence.
        confidences = [f.confidence for f in findings if f.confidence is not None]
        agg_conf = (
            sum(confidences) / len(confidences) if confidences else None
        )

        boundary = HumanReviewBoundary(
            requires_human_review=not is_pass,
            is_final_legal_determination=False,
            review_state=review_state,
            boundary_reason=(
                "all_units_verified_with_support"
                if is_pass
                else "semantic_assurance_incomplete_or_failed"
            ),
            review_question=(
                "Optional review of verified semantic assurance before any "
                "legal conclusion; this module never issues a final legal determination."
                if is_pass
                else (
                    "Human review required: one or more instruction units failed "
                    "semantic assurance or lack proof/deterministic-rule support."
                )
            ),
            confidence=agg_conf,
            may_auto_pass=is_pass,
        )

        text_digest = sha256_hex(
            canonical_json(
                {
                    "analysis_id": analysis_id,
                    "finding_ids": [f.finding_id for f in findings],
                    "verdicts": [f.verdict.value for f in findings],
                    "is_pass": is_pass,
                }
            )
        )

        return SemanticConsistencyResult(
            schema_version=SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            analysis_id=analysis_id,
            source_artifact_id=inp.artifact_id,
            matter_id=inp.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            output_kind=OUTPUT_KIND_SEMANTIC_INSTRUCTION_ASSURANCE,
            disclaimer=NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER,
            declares_unlawful_conduct=False,
            is_model_summary_substitution=False,
            is_final_legal_determination=False,
            is_pass=is_pass,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(dict.fromkeys(warnings)),
            findings=tuple(findings),
            pass_count=pass_count,
            fail_count=fail_count,
            review_count=review_count,
            ruleset_versions=self._ruleset_versions(),
            documented_rules=list_documented_rules(),
            snapshot_id=inp.snapshot_id,
            as_of=str(inp.as_of) if inp.as_of else None,
            labels=dict(inp.labels),
            text_digest=text_digest,
            human_review=boundary,
        )

    def _ruleset_versions(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "semantic_instruction_consistency": (
                    SEMANTIC_INSTRUCTION_CONSISTENCY_RULESET_VERSION
                ),
                "semantic_instruction_consistency_processor": (
                    SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION
                ),
                "contracts": CONTRACTS_SCHEMA_VERSION,
                "legal_ir_contracts": LEGAL_IR_CONTRACTS_SCHEMA_VERSION,
                "legal_ir_proof_executor": LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
            }
        )

    def _verify_one(
        self,
        *,
        analysis_id: str,
        seq: int,
        unit: InstructionCheckUnit,
        as_of: str | date | None,
        run_proofs: bool,
        classification: DisclosureClassification,
    ) -> SemanticFinding:
        finding_id = f"find:{analysis_id}:{seq:04d}"
        reasons: list[str] = []
        assumptions = list(unit.assumptions)
        sources: list[ExactSourceRef] = []
        counterexamples: list[ExactSourceRef] = []
        rule_receipts: list[DeterministicRuleReceipt] = []

        surface = unit.instruction_surface_text[: self.bounds.max_surface]
        digest = unit.instruction_text_digest or _text_digest(surface)

        sources.append(
            ExactSourceRef(
                source_id=f"instr:{unit.unit_id}",
                role="instruction",
                text=surface,
                text_digest=digest,
                span_id=unit.instruction_span_id,
                version=None,
                section=None,
            )
        )

        supports = list(unit.authority_supports)
        as_of_date = _parse_as_of(as_of)
        if as_of_date is not None:
            assumptions.append(f"as_of:{as_of_date.isoformat()}")
            # Re-evaluate superseded relative to as_of if effective_end present.
            refreshed: list[AuthoritySupportRecord] = []
            for s in supports:
                superseded = s.is_superseded or s.is_withdrawn
                if s.effective_end and as_of_date:
                    try:
                        end = date.fromisoformat(s.effective_end[:10])
                        if end < as_of_date:
                            superseded = True
                    except ValueError:
                        pass
                if s.effective_start and as_of_date:
                    try:
                        start = date.fromisoformat(s.effective_start[:10])
                        if start > as_of_date:
                            # Later law must not support earlier as-of.
                            superseded = True
                    except ValueError:
                        pass
                if superseded != s.is_superseded:
                    refreshed.append(
                        AuthoritySupportRecord(
                            support_id=s.support_id,
                            citation_surface=s.citation_surface,
                            citation_key=s.citation_key,
                            resolution_state=s.resolution_state,
                            authority_rank=s.authority_rank,
                            version=s.version,
                            edition=s.edition,
                            node_id=s.node_id,
                            record_id=s.record_id,
                            text_excerpt=s.text_excerpt,
                            text_digest=s.text_digest,
                            is_binding=s.is_binding and not superseded,
                            is_superseded=superseded,
                            is_withdrawn=s.is_withdrawn,
                            effective_start=s.effective_start,
                            effective_end=s.effective_end,
                            content_sha256=s.content_sha256,
                            proposition_atoms=s.proposition_atoms,
                            reasons=s.reasons
                            + (
                                ("as_of_superseded",)
                                if superseded
                                else ()
                            ),
                            labels=dict(s.labels),
                        )
                    )
                else:
                    refreshed.append(s)
            supports = refreshed

        for s in supports:
            if s.text_excerpt:
                sources.append(
                    ExactSourceRef(
                        source_id=s.support_id,
                        role="authority",
                        text=s.text_excerpt,
                        text_digest=s.text_digest,
                        span_id=s.node_id,
                        version=s.version or s.edition,
                        section=s.citation_key,
                    )
                )

        # Claimed atoms — enrich from required_act / deadline_basis only when
        # the unit kind is dedicated to that claim (avoid treating a procedural
        # act on a rejection unit as an unsupported statutory proposition).
        claimed = list(unit.claimed_atoms)
        if (
            unit.finding_kind is FindingKind.REQUIRED_ACT
            and unit.required_act
            and not any(a.predicate == unit.required_act for a in claimed)
        ):
            claimed.append(
                PropositionAtom(
                    atom_id=f"act:{unit.unit_id}",
                    predicate=unit.required_act,
                    polarity=True,
                    modality=LegalModality.OBLIGATION.value,
                )
            )
            reasons.append(SemanticReasonCode.REQUIRED_ACT_RECORDED.value)
        elif unit.required_act:
            # Record presence without elevating to a claimed legal atom.
            reasons.append(SemanticReasonCode.REQUIRED_ACT_RECORDED.value)
            assumptions.append(f"required_act:{unit.required_act}")
        if (
            unit.finding_kind is FindingKind.DEADLINE_BASIS
            and unit.deadline_basis
            and not any(a.predicate == unit.deadline_basis for a in claimed)
        ):
            claimed.append(
                PropositionAtom(
                    atom_id=f"deadline:{unit.unit_id}",
                    predicate=unit.deadline_basis,
                    polarity=True,
                    modality=LegalModality.OBLIGATION.value,
                )
            )
            reasons.append(SemanticReasonCode.DEADLINE_BASIS_RECORDED.value)
        elif unit.deadline_basis:
            reasons.append(SemanticReasonCode.DEADLINE_BASIS_RECORDED.value)
            assumptions.append(f"deadline_basis:{unit.deadline_basis}")
        if unit.exceptions:
            reasons.append(SemanticReasonCode.EXCEPTION_RECORDED.value)
            for i, exc in enumerate(unit.exceptions[:8]):
                assumptions.append(f"exception:{exc}")

        claimed = claimed[: self.bounds.max_propositions]

        # Quote handling.
        quotes: list[str] = []
        if unit.quoted_authority_text:
            quotes.append(_normalize_ws(unit.quoted_authority_text))
        for frag in extract_quoted_fragments(surface):
            if frag not in quotes:
                quotes.append(frag)

        any_quote_match = False
        any_quote_mismatch = False
        if quotes:
            for q in quotes:
                matched_any = False
                for s in supports:
                    if not s.text_excerpt:
                        continue
                    if quotes_match(q, s.text_excerpt):
                        any_quote_match = True
                        matched_any = True
                        reasons.append(SemanticReasonCode.QUOTE_MATCH.value)
                    else:
                        # Only count mismatch against controlling/resolved texts.
                        if s.is_controlling or s.resolution_state in (
                            "resolved",
                            "exact",
                        ):
                            any_quote_mismatch = True
                if not matched_any and supports:
                    any_quote_mismatch = True
                    reasons.append(SemanticReasonCode.QUOTE_MISMATCH.value)
                    counterexamples.append(
                        ExactSourceRef(
                            source_id=f"quote:{unit.unit_id}",
                            role="quote",
                            text=q,
                            text_digest=_text_digest(q),
                            span_id=unit.instruction_span_id,
                        )
                    )
                elif matched_any:
                    # Clear false mismatch if any controlling source matched.
                    pass
        else:
            reasons.append(SemanticReasonCode.QUOTE_ABSENT.value)

        # If we had both match and mismatch signals, prefer match when any
        # controlling authority matched the quote.
        if any_quote_match and any_quote_mismatch:
            # Recompute: mismatch only if no controlling source matches.
            controlling_match = False
            for q in quotes:
                for s in supports:
                    if s.is_controlling and s.text_excerpt and quotes_match(q, s.text_excerpt):
                        controlling_match = True
                        break
            if controlling_match:
                any_quote_mismatch = False

        conflicting = _detect_conflicts(supports)
        superseded = _any_superseded(supports) and not _any_controlling(supports)
        # Superseded controlling path: any support marked superseded without
        # a remaining controlling non-superseded record.
        has_controlling = _any_controlling(supports)
        has_any_support = bool(supports)
        exact_resolved = _any_exact_resolved(supports)
        guidance_only = _guidance_only(supports)

        if conflicting:
            reasons.append(SemanticReasonCode.AUTHORITY_CONFLICTING.value)
        if any(s.is_superseded or s.is_withdrawn for s in supports):
            reasons.append(SemanticReasonCode.AUTHORITY_SUPERSEDED.value)
        if not has_any_support:
            reasons.append(SemanticReasonCode.AUTHORITY_MISSING.value)
            reasons.append(SemanticReasonCode.CITATION_UNRESOLVED.value)
        if has_controlling:
            reasons.append(SemanticReasonCode.AUTHORITY_BINDING.value)
        if guidance_only:
            reasons.append(SemanticReasonCode.AUTHORITY_GUIDANCE_NOT_CONTROLLING.value)
            reasons.append(SemanticReasonCode.AUTHORITY_NON_BINDING.value)
        if exact_resolved:
            reasons.append(SemanticReasonCode.CITATION_RESOLVED.value)
            reasons.append(SemanticReasonCode.AUTHORITY_VERSION_PRESENT.value)
        elif has_any_support and not any(s.has_exact_version for s in supports):
            reasons.append(SemanticReasonCode.AUTHORITY_VERSION_MISSING.value)

        # Proposition-level support.
        support_keys = _authority_atom_keys(supports, controlling_only=True)
        # If no controlling atoms, also consider binding non-superseded.
        if not support_keys:
            support_keys = _authority_atom_keys(supports, controlling_only=False)
            # Still exclude guidance-only from "support" for pass purposes later.
        supported_atoms, unsupported_atoms = _match_atoms(claimed, support_keys)

        if claimed:
            if unsupported_atoms:
                reasons.append(SemanticReasonCode.PROPOSITION_ATOMS_MISMATCH.value)
                reasons.append(SemanticReasonCode.PROPOSITION_SUPPORT_MISSING.value)
            else:
                reasons.append(SemanticReasonCode.PROPOSITION_ATOMS_MATCH.value)
                reasons.append(SemanticReasonCode.PROPOSITION_SUPPORT_PRESENT.value)
        else:
            # No claimed atoms — cannot establish proposition-level support.
            reasons.append(SemanticReasonCode.PROPOSITION_SUPPORT_MISSING.value)

        proposition_support = bool(claimed) and not unsupported_atoms and (
            has_controlling or (exact_resolved and not guidance_only and support_keys)
        )

        # Clerical mismatch: citation key aligns but surface differs, flagged.
        clerical = bool(unit.force_clerical_mismatch)
        if not clerical and unit.legal_citations and supports:
            for cite in unit.legal_citations:
                for s in supports:
                    if s.citation_key and s.citation_key in (
                        unit.citation_keys or ()
                    ):
                        if _normalize_ws(cite).lower() != _normalize_ws(
                            s.citation_surface
                        ).lower() and _normalize_ws(cite) != _normalize_ws(
                            s.citation_surface
                        ):
                            # Soft signal only when keys match.
                            if unit.citation_keys and s.citation_key in unit.citation_keys:
                                # Different surface, same key → possible clerical.
                                if abs(len(cite) - len(s.citation_surface)) <= 8:
                                    clerical = True
                                    reasons.append(
                                        SemanticReasonCode.CLERICAL_SURFACE_MISMATCH.value
                                    )

        # Ambiguity: multiple resolved nodes without conflict digests but ambiguous state.
        ambiguous = any(
            s.resolution_state
            in ("ambiguous", AuthorityResolutionState.AMBIGUOUS.value)
            for s in supports
        )

        # --- Verdict selection (fail-closed priority) ---
        verdict: SemanticVerdict
        if not has_any_support:
            verdict = SemanticVerdict.MISSING_AUTHORITY
            reasons.append(SemanticReasonCode.VERDICT_MISSING.value)
        elif conflicting:
            verdict = SemanticVerdict.CONFLICTING_AUTHORITY
            reasons.append(SemanticReasonCode.VERDICT_CONFLICTING.value)
        elif superseded or (
            any(s.is_superseded or s.is_withdrawn for s in supports)
            and not has_controlling
        ):
            verdict = SemanticVerdict.SUPERSEDED_AUTHORITY
            reasons.append(SemanticReasonCode.VERDICT_SUPERSEDED.value)
        elif exact_resolved and claimed and unsupported_atoms:
            # Exact citation but wrong / unsupported proposition.
            verdict = SemanticVerdict.WRONG_PROPOSITION
            reasons.append(SemanticReasonCode.CITATION_EXACT_BUT_WRONG_PROPOSITION.value)
            reasons.append(SemanticReasonCode.VERDICT_WRONG_PROPOSITION.value)
            reasons.append(SemanticReasonCode.CITATION_ALONE_NOT_CONSISTENT.value)
            for s in supports:
                if s.text_excerpt:
                    counterexamples.append(
                        ExactSourceRef(
                            source_id=f"counter:{s.support_id}",
                            role="counter",
                            text=s.text_excerpt,
                            text_digest=s.text_digest,
                            span_id=s.node_id,
                            version=s.version or s.edition,
                            section=s.citation_key,
                        )
                    )
            reasons.append(SemanticReasonCode.COUNTEREXAMPLE_RECORDED.value)
        elif any_quote_mismatch and exact_resolved and not any_quote_match:
            # Quoted text does not match resolved authority → wrong proposition path.
            verdict = SemanticVerdict.WRONG_PROPOSITION
            reasons.append(SemanticReasonCode.CITATION_EXACT_BUT_WRONG_PROPOSITION.value)
            reasons.append(SemanticReasonCode.VERDICT_WRONG_PROPOSITION.value)
            reasons.append(SemanticReasonCode.CITATION_ALONE_NOT_CONSISTENT.value)
        elif clerical and not proposition_support:
            verdict = SemanticVerdict.CLERICAL_MISMATCH
            reasons.append(SemanticReasonCode.VERDICT_CLERICAL_MISMATCH.value)
        elif ambiguous and not proposition_support:
            verdict = SemanticVerdict.AMBIGUITY
            reasons.append(SemanticReasonCode.VERDICT_AMBIGUITY.value)
        elif guidance_only or (exact_resolved and not has_controlling and not proposition_support):
            verdict = SemanticVerdict.UNSUPPORTED_INSTRUCTION
            reasons.append(SemanticReasonCode.VERDICT_UNSUPPORTED.value)
            reasons.append(SemanticReasonCode.CITATION_ALONE_NOT_CONSISTENT.value)
        elif exact_resolved and not claimed and not any_quote_match:
            # Citation alone is never enough.
            verdict = SemanticVerdict.REQUIRES_REVIEW
            reasons.append(SemanticReasonCode.CITATION_ALONE_NOT_CONSISTENT.value)
            reasons.append(SemanticReasonCode.SUPPORT_INSUFFICIENT_FOR_CONSISTENT.value)
            reasons.append(SemanticReasonCode.VERDICT_REQUIRES_REVIEW.value)
        else:
            # Candidate for verified consistency if support + proof/rule.
            verdict = SemanticVerdict.REQUIRES_REVIEW
            reasons.append(SemanticReasonCode.VERDICT_REQUIRES_REVIEW.value)

        # Evaluate deterministic rules when proposition support looks viable.
        base_pre = {
            "exact_citation_resolved": exact_resolved,
            "binding_authority_rank": has_controlling,
            "exact_version_present": any(s.has_exact_version for s in supports),
            "not_superseded": not any(
                s.is_superseded or s.is_withdrawn for s in supports if s.is_binding
            )
            or has_controlling,
            "not_conflicting": not conflicting,
            "quote_normalized_exact_match": any_quote_match and not any_quote_mismatch,
            "all_claimed_atoms_supported": bool(claimed) and not unsupported_atoms,
            "deadline_basis_present": bool(unit.deadline_basis),
            "basis_predicate_supported": bool(unit.deadline_basis)
            and bool(claimed)
            and not unsupported_atoms,
            "required_act_present": bool(unit.required_act),
        }

        rule_keys_to_try: list[str] = []
        if unit.finding_kind is FindingKind.DEADLINE_BASIS or unit.deadline_basis:
            rule_keys_to_try.append("sic.deadline_basis_binding@1")
        if unit.finding_kind is FindingKind.REQUIRED_ACT or unit.required_act:
            rule_keys_to_try.append("sic.required_act_support@1")
        if any_quote_match:
            rule_keys_to_try.append("sic.quote_exact_match_binding@1")
        if claimed:
            rule_keys_to_try.append("sic.proposition_atom_support@1")
        # Deduplicate preserving order.
        rule_keys_to_try = list(dict.fromkeys(rule_keys_to_try))

        for rk in rule_keys_to_try:
            receipt = _evaluate_rule(rk, preconditions=base_pre)
            rule_receipts.append(receipt)
            if receipt.applied:
                reasons.append(SemanticReasonCode.DETERMINISTIC_RULE_APPLIED.value)
            else:
                reasons.append(SemanticReasonCode.DETERMINISTIC_RULE_FAILED.value)

        applied_rules = [r for r in rule_receipts if r.applied]

        # Proof support.
        proof_receipt = _build_proof_receipt_for_unit(
            unit,
            supported_atoms=supported_atoms,
            unsupported_atoms=unsupported_atoms,
            run_proofs=run_proofs and not unit.force_skip_proof,
            analysis_id=analysis_id,
            seq=seq,
        )
        if proof_receipt is None:
            reasons.append(SemanticReasonCode.PROOF_SKIPPED.value)
        else:
            outcome = proof_receipt.outcome
            if outcome == ProofOutcome.PROVED.value:
                reasons.append(SemanticReasonCode.PROOF_PROVED.value)
            elif outcome == ProofOutcome.DISPROVED.value:
                reasons.append(SemanticReasonCode.PROOF_DISPROVED.value)
            elif outcome == ProofOutcome.TIMEOUT.value:
                reasons.append(SemanticReasonCode.PROOF_TIMEOUT.value)
            elif outcome == ProofOutcome.ERROR.value:
                reasons.append(SemanticReasonCode.PROOF_ERROR.value)
            else:
                reasons.append(SemanticReasonCode.PROOF_UNKNOWN.value)

        # Elevate to verified_consistent only with prop support + proof or rule.
        support_kind = SupportKind.NONE
        is_pass = False
        if proposition_support and has_controlling and not conflicting:
            if proof_receipt is not None and proof_receipt.is_proved:
                support_kind = SupportKind.PROOF_RECEIPT
                verdict = SemanticVerdict.VERIFIED_CONSISTENT
                reasons.append(SemanticReasonCode.VERDICT_VERIFIED_CONSISTENT.value)
                is_pass = True
            elif applied_rules:
                support_kind = SupportKind.DETERMINISTIC_RULE
                verdict = SemanticVerdict.VERIFIED_CONSISTENT
                reasons.append(SemanticReasonCode.VERDICT_VERIFIED_CONSISTENT.value)
                is_pass = True
            else:
                support_kind = SupportKind.INSUFFICIENT
                reasons.append(
                    SemanticReasonCode.SUPPORT_INSUFFICIENT_FOR_CONSISTENT.value
                )
                if verdict is SemanticVerdict.REQUIRES_REVIEW:
                    pass
                elif verdict not in (
                    SemanticVerdict.WRONG_PROPOSITION,
                    SemanticVerdict.MISSING_AUTHORITY,
                    SemanticVerdict.SUPERSEDED_AUTHORITY,
                    SemanticVerdict.CONFLICTING_AUTHORITY,
                ):
                    verdict = SemanticVerdict.REQUIRES_REVIEW
        elif exact_resolved and not proposition_support:
            # Citation alone cannot pass.
            reasons.append(SemanticReasonCode.CITATION_ALONE_NOT_CONSISTENT.value)
            support_kind = SupportKind.INSUFFICIENT
            if verdict is SemanticVerdict.REQUIRES_REVIEW:
                pass

        # Fail-closed: superseded/conflicting/missing never pass.
        if verdict in (
            SemanticVerdict.SUPERSEDED_AUTHORITY,
            SemanticVerdict.CONFLICTING_AUTHORITY,
            SemanticVerdict.MISSING_AUTHORITY,
            SemanticVerdict.WRONG_PROPOSITION,
        ):
            is_pass = False
            support_kind = (
                SupportKind.INSUFFICIENT
                if support_kind is SupportKind.NONE
                else support_kind
            )

        # Confidence heuristic (exposed, not a legal determination).
        confidence = unit.confidence
        if confidence is None:
            if is_pass:
                confidence = 0.85
            elif verdict is SemanticVerdict.WRONG_PROPOSITION:
                confidence = 0.75
            elif verdict in (
                SemanticVerdict.MISSING_AUTHORITY,
                SemanticVerdict.SUPERSEDED_AUTHORITY,
                SemanticVerdict.CONFLICTING_AUTHORITY,
            ):
                confidence = 0.9
            else:
                confidence = 0.4

        requires_review = not is_pass
        review_state = (
            ReviewState.NOT_REQUIRED if is_pass else ReviewState.REQUIRED
        )
        if requires_review:
            reasons.append(SemanticReasonCode.HUMAN_REVIEW_REQUIRED.value)

        citation_surfaces = tuple(
            dict.fromkeys(
                [s.citation_surface for s in supports if s.citation_surface]
                or list(unit.legal_citations)
            )
        )
        authority_versions = tuple(
            dict.fromkeys(
                v
                for s in supports
                for v in (s.version, s.edition)
                if v
            )
        )
        authority_node_ids = tuple(
            dict.fromkeys(s.node_id for s in supports if s.node_id)
        )

        human_q = build_human_review_question(
            unit_id=unit.unit_id,
            verdict=verdict,
            citation_surfaces=citation_surfaces,
            authority_versions=authority_versions,
        )
        boundary = HumanReviewBoundary(
            requires_human_review=requires_review,
            is_final_legal_determination=False,
            review_state=review_state,
            boundary_reason=verdict.value,
            review_question=human_q,
            confidence=confidence,
            may_auto_pass=is_pass,
        )

        if unit.applicability_conditions:
            for cond in unit.applicability_conditions:
                assumptions.append(f"applicability:{cond}")
        if assumptions:
            reasons.append(SemanticReasonCode.ASSUMPTIONS_RECORDED.value)
        reasons.append(SemanticReasonCode.SOURCES_EXPOSED.value)
        reasons.append(SemanticReasonCode.CONFIDENCE_RECORDED.value)
        reasons.append(SemanticReasonCode.HUMAN_REVIEW_BOUNDARY_EXPOSED.value)
        reasons.append(SemanticReasonCode.NOT_FINAL_LEGAL_DETERMINATION.value)

        reasons = list(dict.fromkeys(reasons))

        # Deduplicate counterexamples by digest.
        seen: set[str] = set()
        unique_counters: list[ExactSourceRef] = []
        for c in counterexamples:
            if c.text_digest in seen:
                continue
            seen.add(c.text_digest)
            unique_counters.append(c)

        return SemanticFinding(
            schema_version=SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
            finding_id=finding_id,
            unit_id=unit.unit_id,
            finding_kind=unit.finding_kind,
            verdict=verdict,
            instruction_span_id=unit.instruction_span_id,
            instruction_surface_text=surface,
            instruction_text_digest=digest,
            claimed_atoms=tuple(claimed),
            supported_atoms=supported_atoms,
            unsupported_atoms=unsupported_atoms,
            authority_supports=tuple(supports),
            sources=tuple(sources),
            assumptions=tuple(dict.fromkeys(assumptions)),
            counterexamples=tuple(unique_counters),
            support_kind=support_kind,
            deterministic_rule_receipts=tuple(rule_receipts),
            proof_receipt=proof_receipt,
            human_review=boundary,
            confidence=confidence,
            reason_codes=tuple(reasons),
            citation_surfaces=citation_surfaces,
            authority_versions=authority_versions,
            authority_node_ids=authority_node_ids,
            classification=(
                unit.classification
                if unit.classification is not DisclosureClassification.UNKNOWN
                else classification
            ),
            labels=dict(unit.labels),
            declares_unlawful_conduct=False,
            is_model_summary_substitution=False,
            is_pass=is_pass,
        )


# ---------------------------------------------------------------------------
# Public helpers / fixture builders
# ---------------------------------------------------------------------------


def verify_semantic_instruction_consistency(
    value: SemanticConsistencyInput | Mapping[str, Any],
    **kwargs: Any,
) -> SemanticConsistencyResult:
    """Module-level convenience entry point."""
    return SemanticInstructionConsistencyProcessor().verify(value, **kwargs)


def build_binding_authority_support(
    *,
    support_id: str,
    citation_surface: str,
    citation_key: str,
    text_excerpt: str,
    version: str,
    proposition_predicates: Sequence[str],
    node_id: str | None = None,
    authority_rank: str = AuthorityRank.OFFICIAL_BASE.value,
    is_binding: bool = True,
    is_superseded: bool = False,
    is_withdrawn: bool = False,
    effective_start: str | None = None,
    effective_end: str | None = None,
    content_sha256: str | None = None,
) -> AuthoritySupportRecord:
    """Compact factory for tests and integration recipes."""
    atoms = tuple(
        PropositionAtom(
            atom_id=f"auth-atom:{support_id}:{i}",
            predicate=pred,
            polarity=True,
        )
        for i, pred in enumerate(proposition_predicates)
    )
    digest = _text_digest(text_excerpt) if text_excerpt else sha256_hex("")
    return AuthoritySupportRecord(
        support_id=support_id,
        citation_surface=citation_surface,
        citation_key=citation_key,
        resolution_state=AuthorityResolutionState.RESOLVED.value,
        authority_rank=authority_rank,
        version=version,
        edition=version,
        node_id=node_id or support_id,
        record_id=support_id,
        text_excerpt=text_excerpt,
        text_digest=digest,
        is_binding=is_binding and not is_superseded and not is_withdrawn,
        is_superseded=is_superseded,
        is_withdrawn=is_withdrawn,
        effective_start=effective_start,
        effective_end=effective_end,
        content_sha256=content_sha256 or digest,
        proposition_atoms=atoms,
        reasons=("fixture_binding_support",),
        labels={},
    )


def build_wrong_proposition_fixture() -> SemanticConsistencyInput:
    """Exact citation resolves; claimed proposition does not match authority."""
    statute = (
        "The specification shall conclude with one or more claims particularly "
        "pointing out and distinctly claiming the subject matter."
    )
    support = build_binding_authority_support(
        support_id="auth:112b",
        citation_surface="35 U.S.C. § 112(b)",
        citation_key="35-usc-112(b)",
        text_excerpt=statute,
        version="aia-2011",
        proposition_predicates=(
            "claims_must_particularly_point_out",
            "specification_concludes_with_claims",
        ),
        effective_start="2011-09-16",
    )
    unit = InstructionCheckUnit(
        unit_id="unit:wrong-prop",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:wrong-prop",
        instruction_surface_text=(
            'Claims 1-3 are rejected under 35 U.S.C. § 112(b) because the '
            f'statute provides "The specification may omit claims when the '
            f'drawings are sufficient."'
        ),
        instruction_text_digest=None,
        legal_citations=("35 U.S.C. § 112(b)",),
        citation_keys=("35-usc-112(b)",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="claim:omit-ok",
                predicate="specification_may_omit_claims",
                polarity=True,
            ),
        ),
        quoted_authority_text=(
            "The specification may omit claims when the drawings are sufficient."
        ),
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(support,),
        legal_ir_mapping=None,
        confidence=0.8,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={"fixture": "exact_citation_wrong_proposition"},
    )
    return SemanticConsistencyInput(
        artifact_id="art:oa:wrong-prop",
        units=(unit,),
        classification=DisclosureClassification.PUBLIC_USER,
        as_of="2024-06-01",
        analysis_id="analysis:wrong-prop",
        matter_id="matter:1",
        run_proofs=True,
        labels={"fixture": "exact_citation_wrong_proposition"},
    )


def build_verified_consistent_fixture(
    *, use_proof: bool = True
) -> SemanticConsistencyInput:
    """Proposition-level support with proof or deterministic rule path."""
    statute = (
        "The specification shall conclude with one or more claims particularly "
        "pointing out and distinctly claiming the subject matter."
    )
    support = build_binding_authority_support(
        support_id="auth:112b-ok",
        citation_surface="35 U.S.C. § 112(b)",
        citation_key="35-usc-112(b)",
        text_excerpt=statute,
        version="aia-2011",
        proposition_predicates=(
            "claims_must_particularly_point_out",
            "specification_concludes_with_claims",
        ),
        effective_start="2011-09-16",
    )
    unit = InstructionCheckUnit(
        unit_id="unit:ok",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:ok",
        instruction_surface_text=(
            f'Claims 1-3 are rejected under 35 U.S.C. § 112(b) as indefinite '
            f'because the statute provides "{statute}".'
        ),
        instruction_text_digest=None,
        legal_citations=("35 U.S.C. § 112(b)",),
        citation_keys=("35-usc-112(b)",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="claim:point-out",
                predicate="claims_must_particularly_point_out",
                polarity=True,
            ),
        ),
        quoted_authority_text=statute,
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=("utility_application",),
        assumptions=(),
        authority_supports=(support,),
        legal_ir_mapping=None,
        confidence=0.9,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={"fixture": "verified_consistent"},
        force_skip_proof=not use_proof,
    )
    return SemanticConsistencyInput(
        artifact_id="art:oa:ok",
        units=(unit,),
        classification=DisclosureClassification.PUBLIC_USER,
        as_of="2024-06-01",
        analysis_id="analysis:ok",
        matter_id="matter:1",
        run_proofs=use_proof,
        labels={"fixture": "verified_consistent"},
    )


def build_superseded_authority_fixture() -> SemanticConsistencyInput:
    support = build_binding_authority_support(
        support_id="auth:old",
        citation_surface="35 U.S.C. § 112(b)",
        citation_key="35-usc-112(b)",
        text_excerpt="Pre-AIA definiteness text.",
        version="pre-aia-2000",
        proposition_predicates=("claims_must_particularly_point_out",),
        is_superseded=True,
        effective_start="2000-01-01",
        effective_end="2011-09-15",
    )
    unit = InstructionCheckUnit(
        unit_id="unit:superseded",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:superseded",
        instruction_surface_text="Rejected under 35 U.S.C. § 112(b).",
        instruction_text_digest=None,
        legal_citations=("35 U.S.C. § 112(b)",),
        citation_keys=("35-usc-112(b)",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="claim:point-out",
                predicate="claims_must_particularly_point_out",
                polarity=True,
            ),
        ),
        quoted_authority_text=None,
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(support,),
        legal_ir_mapping=None,
        confidence=0.7,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={"fixture": "superseded"},
    )
    return SemanticConsistencyInput(
        artifact_id="art:oa:superseded",
        units=(unit,),
        classification=DisclosureClassification.PUBLIC_USER,
        as_of="2024-06-01",
        analysis_id="analysis:superseded",
        run_proofs=True,
        labels={"fixture": "superseded"},
    )


def build_conflicting_authority_fixture() -> SemanticConsistencyInput:
    s1 = build_binding_authority_support(
        support_id="auth:a",
        citation_surface="35 U.S.C. § 112(b)",
        citation_key="35-usc-112(b)",
        text_excerpt="Edition A definiteness text alpha.",
        version="aia-2011-a",
        proposition_predicates=("claims_must_particularly_point_out",),
        content_sha256="a" * 64,
        effective_start="2011-09-16",
    )
    s2 = build_binding_authority_support(
        support_id="auth:b",
        citation_surface="35 U.S.C. § 112(b)",
        citation_key="35-usc-112(b)",
        text_excerpt="Edition B definiteness text beta differs.",
        version="aia-2011-b",
        proposition_predicates=("claims_must_particularly_point_out",),
        content_sha256="b" * 64,
        effective_start="2011-09-16",
    )
    unit = InstructionCheckUnit(
        unit_id="unit:conflict",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:conflict",
        instruction_surface_text="Rejected under 35 U.S.C. § 112(b).",
        instruction_text_digest=None,
        legal_citations=("35 U.S.C. § 112(b)",),
        citation_keys=("35-usc-112(b)",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="claim:point-out",
                predicate="claims_must_particularly_point_out",
                polarity=True,
            ),
        ),
        quoted_authority_text=None,
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(s1, s2),
        legal_ir_mapping=None,
        confidence=0.6,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={"fixture": "conflicting"},
    )
    return SemanticConsistencyInput(
        artifact_id="art:oa:conflict",
        units=(unit,),
        classification=DisclosureClassification.PUBLIC_USER,
        as_of="2024-06-01",
        analysis_id="analysis:conflict",
        run_proofs=True,
        labels={"fixture": "conflicting"},
    )


def build_missing_authority_fixture() -> SemanticConsistencyInput:
    unit = InstructionCheckUnit(
        unit_id="unit:missing",
        finding_kind=FindingKind.INSTRUCTION,
        instruction_span_id="span:missing",
        instruction_surface_text="Rejected under 35 U.S.C. § 999(z).",
        instruction_text_digest=None,
        legal_citations=("35 U.S.C. § 999(z)",),
        citation_keys=("35-usc-999(z)",),
        claimed_atoms=(
            PropositionAtom(
                atom_id="claim:mystery",
                predicate="mystery_obligation",
                polarity=True,
            ),
        ),
        quoted_authority_text=None,
        deadline_basis=None,
        required_act=None,
        exceptions=(),
        applicability_conditions=(),
        assumptions=(),
        authority_supports=(),
        legal_ir_mapping=None,
        confidence=0.5,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={"fixture": "missing"},
    )
    return SemanticConsistencyInput(
        artifact_id="art:oa:missing",
        units=(unit,),
        classification=DisclosureClassification.PUBLIC_USER,
        as_of="2024-06-01",
        analysis_id="analysis:missing",
        run_proofs=True,
        labels={"fixture": "missing"},
    )


__all__ = [
    "SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION",
    "SEMANTIC_INSTRUCTION_CONSISTENCY_INTERFACE",
    "SEMANTIC_INSTRUCTION_CONSISTENCY_RULESET_VERSION",
    "OUTPUT_KIND_SEMANTIC_INSTRUCTION_ASSURANCE",
    "NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER",
    "DOCUMENTED_DETERMINISTIC_RULES",
    "SemanticVerdict",
    "SupportKind",
    "FindingKind",
    "SemanticDisposition",
    "SemanticReasonCode",
    "SemanticInstructionConsistencyError",
    "AnalysisBounds",
    "ExactSourceRef",
    "PropositionAtom",
    "AuthoritySupportRecord",
    "DeterministicRuleReceipt",
    "ProofSupportReceipt",
    "HumanReviewBoundary",
    "SemanticFinding",
    "InstructionCheckUnit",
    "SemanticConsistencyInput",
    "SemanticConsistencyResult",
    "SemanticInstructionConsistencyProcessor",
    "sha256_hex",
    "quotes_match",
    "atom_key",
    "is_pass_verdict",
    "documented_rule",
    "list_documented_rules",
    "extract_quoted_fragments",
    "contains_forbidden_unlawful_token",
    "sanitize_labels",
    "build_human_review_question",
    "verify_semantic_instruction_consistency",
    "build_binding_authority_support",
    "build_wrong_proposition_fixture",
    "build_verified_consistent_fixture",
    "build_superseded_authority_fixture",
    "build_conflicting_authority_fixture",
    "build_missing_authority_fixture",
]
