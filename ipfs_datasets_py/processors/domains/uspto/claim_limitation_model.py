"""PAAR claim limitation model (PAAR-010 / PAAR-011 / PAAR-012).

Builds a deterministic, evidence-bound claim limitation graph from OCR or
export claim text: independent/dependent structure, limitation spans,
dependency and antecedent review flags, and an OCR quality score that gates
whether automated conflict screening may treat the graph as authoritative.

Design invariants
-----------------
* **Not legal advice**; never asserts claim construction, novelty,
  obviousness, patentability, or §112 rejections as legal conclusions.
* Review flags are **heuristics** for human triage only.
* Low OCR quality forces ``review_required`` authority mode — automated
  conflict screening is non-authoritative.
* **Never log full claim bodies** to ordinary logs (INFO/WARNING/DEBUG);
  private report files under operator state roots remain the sole body store.
* Reuses ``parse_claims_text`` / ``load_claims`` from prior_art_search_client.

Conflict policy (PAAR-010): own this module and its tests; call parsers via
stable imports only.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    load_claims,
    parse_claims_text,
)

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

CLAIM_LIMITATION_MODEL_SCHEMA: Final = "paar.claim-limitation-model.v1"
CLAIM_LIMITATION_MODEL_INTERFACE: Final = "ClaimLimitationModel@1"
CLAIM_LIMITATION_MODEL_CODE_VERSION: Final = "1.0.0"

OUTPUT_KIND_CLAIM_LIMITATION_GRAPH: Final = "claim_limitation_graph"

REVIEW_ONLY_CLAIM_MODEL_DISCLAIMER: Final = (
    "This claim limitation graph is a deterministic, review-only parse of "
    "claim text for conflict-risk screening and format triage. It is not "
    "legal advice, not claim construction, not a §112 determination, and "
    "not a novelty, obviousness, or patentability conclusion. Low OCR "
    "quality makes automated conflict screening non-authoritative. Named "
    "human review is required before any legal or filing action."
)

# Default quality gate: below this, automated conflict authority is blocked.
DEFAULT_QUALITY_THRESHOLD: Final = 0.55
DEFAULT_MAX_CLAIMS: Final = 256
DEFAULT_MAX_LIMITATIONS_PER_CLAIM: Final = 64
DEFAULT_MAX_LIMITATION_CHARS: Final = 8_000
DEFAULT_MAX_LOG_PREVIEW_CHARS: Final = 0  # never emit body preview

_DEPENDENT_CLAIM_RE = re.compile(
    r"\b(?:of|to)\s+claim\s+(\d+)\b",
    re.IGNORECASE,
)
_MULTIPLE_DEPENDENT_RE = re.compile(
    r"\b(?:of|to)\s+claims?\s+\d+\s*(?:(?:or|and|to|,)\s*\d+)+\b",
    re.IGNORECASE,
)
_LIMITATION_SPLIT_RE = re.compile(
    r"\s*(?:,\s*and\s+|;\s*|\s+wherein\s+|\s+comprising\s+|\s+including\s+|"
    r"\s+characterized\s+by\s+)\s*",
    re.IGNORECASE,
)
_INDEF_ARTICLE_RE = re.compile(
    r"\b(?:a|an)\s+([a-z][a-z0-9\-]{2,}(?:\s+[a-z][a-z0-9\-]{2,}){0,3})\b",
    re.I,
)
_ANTECEDENT_RE = re.compile(
    r"\b(?:said|the)\s+([a-z][a-z0-9\-]{2,}(?:\s+[a-z][a-z0-9\-]{2,}){0,3})\b",
    re.I,
)
_REF_NUMERAL_RE = re.compile(r"\b(\d{1,4})\b")
_OCR_GARBAGE_RE = re.compile(
    r"[^\w\s\-\.,;:()\'\"/%°±≤≥=\[\]{}#+*&@!?/\\]"
)
_REPLACEMENT_CHAR_RE = re.compile(r"\ufffd|�")
_WS_RE = re.compile(r"\s+")

_SKIP_ANTECEDENT_HEADS: Final[frozenset[str]] = frozenset(
    {
        "method",
        "system",
        "device",
        "apparatus",
        "invention",
        "group consisting",
        "following",
        "present invention",
        "claimed invention",
        "subject matter",
    }
)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ClaimDependencyKind(str, Enum):
    INDEPENDENT = "independent"
    DEPENDENT = "dependent"
    MULTIPLE_DEPENDENT = "multiple_dependent"
    UNKNOWN = "unknown"


class AuthorityMode(str, Enum):
    """Whether automated conflict screening may treat this graph as authority."""

    AUTHORITATIVE = "authoritative"
    REVIEW_REQUIRED = "review_required"
    NON_AUTHORITATIVE = "non_authoritative"


class ReviewFlagCode(str, Enum):
    """Heuristic review flags — not legal conclusions."""

    BROKEN_DEPENDENCY = "broken_dependency"
    FORWARD_DEPENDENCY = "forward_dependency"
    MISSING_PARENT = "missing_parent"
    MULTIPLE_DEPENDENT_FORM = "multiple_dependent_form"
    WEAK_ANTECEDENT = "weak_antecedent"
    VERY_SHORT_CLAIM = "very_short_claim"
    NUMBERING_GAP = "numbering_gap"
    NO_INDEPENDENT = "no_independent"
    EMPTY_CLAIMS = "empty_claims"
    LOW_OCR_QUALITY = "low_ocr_quality"
    TERMINAL_PUNCTUATION = "terminal_punctuation"
    HIGH_GARBAGE_RATIO = "high_garbage_ratio"


class QualityGateCode(str, Enum):
    PASS = "quality_pass"
    REVIEW_REQUIRED = "review_required"
    EMPTY = "empty_claims"
    BELOW_THRESHOLD = "below_quality_threshold"
    STRUCTURAL_FAILURE = "structural_failure"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ClaimLimitationModelError(ValueError):
    """Bounded claim-limitation model failure (fail-closed)."""

    def __init__(
        self, message: str, *, code: str = "claim_limitation_model_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Helpers (no body logging)
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _safe_log_event(event: str, **fields: Any) -> None:
    """Log operational fields only — never claim body text."""
    safe: dict[str, Any] = {"event": event}
    for key, value in fields.items():
        if key in {"claim_text", "text", "body", "claims_text", "limitation_text"}:
            continue
        if isinstance(value, str) and len(value) > 120:
            safe[key] = value[:80] + "…"
        else:
            safe[key] = value
    _logger.info("claim_limitation_model %s", safe)


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def _is_dependent_text(text: str) -> bool:
    return bool(_DEPENDENT_CLAIM_RE.search(text or ""))


def _parent_claim_numbers(text: str) -> tuple[int, ...]:
    parents = [int(m.group(1)) for m in _DEPENDENT_CLAIM_RE.finditer(text or "")]
    # Deduplicate preserving order
    seen: set[int] = set()
    out: list[int] = []
    for p in parents:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return tuple(out)


def _split_limitation_parts(claim_text: str) -> list[str]:
    cleaned = re.sub(r"^\s*\d+\.\s*", "", claim_text or "").strip()
    if not cleaned:
        return []
    parts = [
        p.strip(" .")
        for p in _LIMITATION_SPLIT_RE.split(cleaned)
        if p and p.strip()
    ]
    if not parts:
        parts = [cleaned]
    # Drop empty / tiny fragments
    return [p for p in parts if len(p) >= 2] or [cleaned]


def _ocr_garbage_ratio(text: str) -> float:
    if not text:
        return 1.0
    n = len(text)
    garbage = len(_OCR_GARBAGE_RE.findall(text)) + len(
        _REPLACEMENT_CHAR_RE.findall(text)
    )
    return min(1.0, garbage / max(1, n))


def _replacement_char_count(text: str) -> int:
    return len(_REPLACEMENT_CHAR_RE.findall(text or ""))


# ---------------------------------------------------------------------------
# Data records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LimitationSpan:
    """Character span of a limitation within its claim body."""

    start: int
    end: int
    unit: str = "char"

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ClaimLimitationModelError(
                f"invalid span {self.start}:{self.end}", code="invalid_span"
            )
        if self.unit != "char":
            raise ClaimLimitationModelError(
                f"unsupported span unit {self.unit!r}", code="invalid_span_unit"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "unit": self.unit}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LimitationSpan":
        return cls(
            start=int(value.get("start", 0)),
            end=int(value.get("end", 0)),
            unit=str(value.get("unit") or "char"),
        )


@dataclass(frozen=True, slots=True)
class ReviewFlag:
    """Heuristic review flag — never a legal conclusion."""

    code: str
    claim_number: int | None
    message: str
    severity: str = "info"  # info | warning | error

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "claim_number": self.claim_number,
            "message": self.message,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewFlag":
        cn = value.get("claim_number")
        return cls(
            code=str(value.get("code") or ""),
            claim_number=int(cn) if cn is not None else None,
            message=str(value.get("message") or ""),
            severity=str(value.get("severity") or "info"),
        )


@dataclass(frozen=True, slots=True)
class ClaimLimitationNode:
    """One limitation node in the claim graph."""

    limitation_id: str
    claim_number: int
    ordinal: int
    text: str
    span: LimitationSpan
    dependency_kind: ClaimDependencyKind
    parent_claim_numbers: tuple[int, ...] = ()
    reference_numerals: tuple[str, ...] = ()
    text_digest: str = ""

    def __post_init__(self) -> None:
        if not self.limitation_id:
            raise ClaimLimitationModelError(
                "limitation_id required", code="missing_limitation_id"
            )
        digest = self.text_digest or _sha256_hex(self.text)
        object.__setattr__(self, "text_digest", digest)

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "limitation_id": self.limitation_id,
            "claim_number": self.claim_number,
            "ordinal": self.ordinal,
            "span": self.span.to_dict(),
            "dependency_kind": self.dependency_kind.value,
            "parent_claim_numbers": list(self.parent_claim_numbers),
            "reference_numerals": list(self.reference_numerals),
            "text_digest": self.text_digest,
        }
        if include_text:
            payload["text"] = self.text
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimLimitationNode":
        return cls(
            limitation_id=str(value.get("limitation_id") or ""),
            claim_number=int(value.get("claim_number") or 0),
            ordinal=int(value.get("ordinal") or 1),
            text=str(value.get("text") or ""),
            span=LimitationSpan.from_dict(value.get("span") or {}),
            dependency_kind=ClaimDependencyKind(
                str(value.get("dependency_kind") or "unknown")
            ),
            parent_claim_numbers=tuple(
                int(x) for x in (value.get("parent_claim_numbers") or ())
            ),
            reference_numerals=tuple(
                str(x) for x in (value.get("reference_numerals") or ())
            ),
            text_digest=str(value.get("text_digest") or ""),
        )


@dataclass(frozen=True, slots=True)
class ClaimNode:
    """One claim with dependency metadata and child limitation ids."""

    claim_number: int
    dependency_kind: ClaimDependencyKind
    parent_claim_numbers: tuple[int, ...]
    limitation_ids: tuple[str, ...]
    text_digest: str
    char_count: int
    text: str = ""  # present for round-trip; omit from ordinary logs

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "claim_number": self.claim_number,
            "dependency_kind": self.dependency_kind.value,
            "parent_claim_numbers": list(self.parent_claim_numbers),
            "limitation_ids": list(self.limitation_ids),
            "text_digest": self.text_digest,
            "char_count": self.char_count,
        }
        if include_text:
            payload["text"] = self.text
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimNode":
        return cls(
            claim_number=int(value.get("claim_number") or 0),
            dependency_kind=ClaimDependencyKind(
                str(value.get("dependency_kind") or "unknown")
            ),
            parent_claim_numbers=tuple(
                int(x) for x in (value.get("parent_claim_numbers") or ())
            ),
            limitation_ids=tuple(str(x) for x in (value.get("limitation_ids") or ())),
            text_digest=str(value.get("text_digest") or ""),
            char_count=int(value.get("char_count") or 0),
            text=str(value.get("text") or ""),
        )


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    """OCR / parse quality score and authority gate result."""

    quality_score: float
    authority_mode: AuthorityMode
    gate_code: QualityGateCode
    threshold: float
    signals: Mapping[str, float] = field(default_factory=dict)
    low_ocr_quality: bool = False
    review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_score": round(self.quality_score, 4),
            "authority_mode": self.authority_mode.value,
            "gate_code": self.gate_code.value,
            "threshold": self.threshold,
            "signals": dict(self.signals),
            "low_ocr_quality": self.low_ocr_quality,
            "review_required": self.review_required,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QualityAssessment":
        return cls(
            quality_score=float(value.get("quality_score") or 0.0),
            authority_mode=AuthorityMode(
                str(value.get("authority_mode") or "review_required")
            ),
            gate_code=QualityGateCode(
                str(value.get("gate_code") or "review_required")
            ),
            threshold=float(
                value.get("threshold")
                if value.get("threshold") is not None
                else DEFAULT_QUALITY_THRESHOLD
            ),
            signals=dict(value.get("signals") or {}),
            low_ocr_quality=bool(value.get("low_ocr_quality", False)),
            review_required=bool(value.get("review_required", True)),
        )


@dataclass(frozen=True, slots=True)
class ClaimLimitationGraph:
    """Full claim limitation graph for a claim set."""

    schema: str
    claims: tuple[ClaimNode, ...]
    limitations: tuple[ClaimLimitationNode, ...]
    quality: QualityAssessment
    review_flags: tuple[ReviewFlag, ...]
    content_digest: str
    source_digest: str
    disclaimer: str = REVIEW_ONLY_CLAIM_MODEL_DISCLAIMER
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "claims": [c.to_dict(include_text=include_text) for c in self.claims],
            "limitations": [
                lim.to_dict(include_text=include_text) for lim in self.limitations
            ],
            "quality": self.quality.to_dict(),
            "review_flags": [f.to_dict() for f in self.review_flags],
            "content_digest": self.content_digest,
            "source_digest": self.source_digest,
            "disclaimer": self.disclaimer,
            "metadata": dict(self.metadata),
            "interface": CLAIM_LIMITATION_MODEL_INTERFACE,
            "code_version": CLAIM_LIMITATION_MODEL_CODE_VERSION,
            "output_kind": OUTPUT_KIND_CLAIM_LIMITATION_GRAPH,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimLimitationGraph":
        return cls(
            schema=str(value.get("schema") or CLAIM_LIMITATION_MODEL_SCHEMA),
            claims=tuple(
                ClaimNode.from_dict(c) for c in (value.get("claims") or ())
            ),
            limitations=tuple(
                ClaimLimitationNode.from_dict(lim)
                for lim in (value.get("limitations") or ())
            ),
            quality=QualityAssessment.from_dict(value.get("quality") or {}),
            review_flags=tuple(
                ReviewFlag.from_dict(f) for f in (value.get("review_flags") or ())
            ),
            content_digest=str(value.get("content_digest") or ""),
            source_digest=str(value.get("source_digest") or ""),
            disclaimer=str(
                value.get("disclaimer") or REVIEW_ONLY_CLAIM_MODEL_DISCLAIMER
            ),
            metadata=dict(value.get("metadata") or {}),
        )

    def independent_claim_numbers(self) -> tuple[int, ...]:
        return tuple(
            c.claim_number
            for c in self.claims
            if c.dependency_kind is ClaimDependencyKind.INDEPENDENT
        )

    def dependent_claim_numbers(self) -> tuple[int, ...]:
        return tuple(
            c.claim_number
            for c in self.claims
            if c.dependency_kind
            in (
                ClaimDependencyKind.DEPENDENT,
                ClaimDependencyKind.MULTIPLE_DEPENDENT,
            )
        )


# ---------------------------------------------------------------------------
# Quality scoring / gate
# ---------------------------------------------------------------------------


def score_claim_ocr_quality(
    claims: Sequence[Mapping[str, Any] | ClaimNode],
    *,
    raw_text: str | None = None,
    review_flags: Sequence[ReviewFlag] = (),
) -> dict[str, float]:
    """Compute quality signals in [0, 1] (higher is better)."""
    if not claims:
        return {
            "parse_coverage": 0.0,
            "length_adequacy": 0.0,
            "garbage_cleanliness": 0.0,
            "structure_integrity": 0.0,
            "replacement_cleanliness": 0.0,
        }

    texts: list[str] = []
    for c in claims:
        if isinstance(c, ClaimNode):
            texts.append(c.text)
        else:
            texts.append(str(c.get("claim_text") or c.get("text") or ""))

    joined = "\n".join(texts)
    n_claims = len(texts)
    avg_len = sum(len(t) for t in texts) / max(1, n_claims)
    length_adequacy = min(1.0, avg_len / 120.0)

    garbage = _ocr_garbage_ratio(joined)
    garbage_cleanliness = max(0.0, 1.0 - garbage * 8.0)

    repl = _replacement_char_count(joined)
    if raw_text:
        repl = max(repl, _replacement_char_count(raw_text))
    replacement_cleanliness = max(0.0, 1.0 - (repl / max(1, len(joined))) * 20.0)

    # Structure: presence of independent claims, contiguous numbering
    nums = []
    for c in claims:
        if isinstance(c, ClaimNode):
            nums.append(c.claim_number)
        else:
            try:
                nums.append(int(c.get("claim_number") or 0))
            except (TypeError, ValueError):
                continue
    nums = [n for n in nums if n > 0]
    independent = 0
    for t in texts:
        if not _is_dependent_text(t):
            independent += 1
    structure = 0.5
    if independent > 0:
        structure += 0.3
    if nums and set(nums) == set(range(min(nums), max(nums) + 1)):
        structure += 0.2
    structure = min(1.0, structure)

    # Penalize severe review flags lightly (quality signal only)
    flag_penalty = 0.0
    for f in review_flags:
        if f.severity == "error":
            flag_penalty += 0.08
        elif f.severity == "warning":
            flag_penalty += 0.03
    structure_integrity = max(0.0, structure - min(0.4, flag_penalty))

    parse_coverage = 1.0 if n_claims > 0 else 0.0
    if raw_text and len(raw_text.strip()) > 40 and n_claims == 1:
        # Single blob from long OCR may indicate weak numbering recovery
        if not re.search(r"(?m)^\s*\d+[\.\)]\s+\S", raw_text):
            parse_coverage = 0.6

    return {
        "parse_coverage": round(parse_coverage, 4),
        "length_adequacy": round(length_adequacy, 4),
        "garbage_cleanliness": round(min(1.0, garbage_cleanliness), 4),
        "structure_integrity": round(structure_integrity, 4),
        "replacement_cleanliness": round(min(1.0, replacement_cleanliness), 4),
    }


def aggregate_quality_score(signals: Mapping[str, float]) -> float:
    weights = {
        "parse_coverage": 0.25,
        "length_adequacy": 0.15,
        "garbage_cleanliness": 0.25,
        "structure_integrity": 0.25,
        "replacement_cleanliness": 0.10,
    }
    total_w = 0.0
    acc = 0.0
    for key, w in weights.items():
        if key in signals:
            acc += float(signals[key]) * w
            total_w += w
    if total_w <= 0:
        return 0.0
    return round(acc / total_w, 4)


def assess_quality_gate(
    *,
    claims: Sequence[Mapping[str, Any] | ClaimNode],
    review_flags: Sequence[ReviewFlag] = (),
    raw_text: str | None = None,
    threshold: float = DEFAULT_QUALITY_THRESHOLD,
) -> QualityAssessment:
    """Gate automated conflict authority on claim OCR quality.

    Below-threshold quality → ``review_required`` / non-authoritative mode
    with an explicit gate code (PAAR-012).
    """
    if not claims:
        return QualityAssessment(
            quality_score=0.0,
            authority_mode=AuthorityMode.REVIEW_REQUIRED,
            gate_code=QualityGateCode.EMPTY,
            threshold=threshold,
            signals={"parse_coverage": 0.0},
            low_ocr_quality=True,
            review_required=True,
        )

    signals = score_claim_ocr_quality(
        claims, raw_text=raw_text, review_flags=review_flags
    )
    score = aggregate_quality_score(signals)

    structural_errors = [
        f
        for f in review_flags
        if f.code
        in {
            ReviewFlagCode.NO_INDEPENDENT.value,
            ReviewFlagCode.EMPTY_CLAIMS.value,
        }
    ]
    if structural_errors:
        return QualityAssessment(
            quality_score=score,
            authority_mode=AuthorityMode.REVIEW_REQUIRED,
            gate_code=QualityGateCode.STRUCTURAL_FAILURE,
            threshold=threshold,
            signals=signals,
            low_ocr_quality=True,
            review_required=True,
        )

    if score < threshold:
        return QualityAssessment(
            quality_score=score,
            authority_mode=AuthorityMode.REVIEW_REQUIRED,
            gate_code=QualityGateCode.BELOW_THRESHOLD,
            threshold=threshold,
            signals=signals,
            low_ocr_quality=True,
            review_required=True,
        )

    return QualityAssessment(
        quality_score=score,
        authority_mode=AuthorityMode.AUTHORITATIVE,
        gate_code=QualityGateCode.PASS,
        threshold=threshold,
        signals=signals,
        low_ocr_quality=False,
        review_required=False,
    )


# ---------------------------------------------------------------------------
# Dependency / antecedent heuristics (PAAR-011)
# ---------------------------------------------------------------------------


def _collect_review_flags(
    claims: Sequence[tuple[int, str]],
) -> list[ReviewFlag]:
    flags: list[ReviewFlag] = []
    if not claims:
        flags.append(
            ReviewFlag(
                code=ReviewFlagCode.EMPTY_CLAIMS.value,
                claim_number=None,
                message="No claims parsed for limitation model.",
                severity="error",
            )
        )
        return flags

    nums = [n for n, _ in claims]
    num_set = set(nums)
    if nums:
        missing = [i for i in range(min(nums), max(nums) + 1) if i not in num_set]
        if missing:
            flags.append(
                ReviewFlag(
                    code=ReviewFlagCode.NUMBERING_GAP.value,
                    claim_number=None,
                    message=f"Claim numbering gaps detected: {missing} (OCR or parse issue).",
                    severity="warning",
                )
            )

    independent = [(n, t) for n, t in claims if not _is_dependent_text(t)]
    if not independent:
        flags.append(
            ReviewFlag(
                code=ReviewFlagCode.NO_INDEPENDENT.value,
                claim_number=None,
                message="No independent claims detected (heuristic).",
                severity="error",
            )
        )

    for n, text in claims:
        if len(text) < 40:
            flags.append(
                ReviewFlag(
                    code=ReviewFlagCode.VERY_SHORT_CLAIM.value,
                    claim_number=n,
                    message=f"Claim {n} text is very short ({len(text)} chars) — OCR/format risk.",
                    severity="warning",
                )
            )
        if text and not re.search(r"[\.\;]\s*$", text):
            flags.append(
                ReviewFlag(
                    code=ReviewFlagCode.TERMINAL_PUNCTUATION.value,
                    claim_number=n,
                    message=f"Claim {n} may lack terminal punctuation (OCR or format).",
                    severity="info",
                )
            )
        garbage = _ocr_garbage_ratio(text)
        if garbage > 0.08:
            flags.append(
                ReviewFlag(
                    code=ReviewFlagCode.HIGH_GARBAGE_RATIO.value,
                    claim_number=n,
                    message=(
                        f"Claim {n} has elevated non-prose character ratio "
                        f"({garbage:.2f}) — OCR quality concern."
                    ),
                    severity="warning",
                )
            )
        if _MULTIPLE_DEPENDENT_RE.search(text):
            flags.append(
                ReviewFlag(
                    code=ReviewFlagCode.MULTIPLE_DEPENDENT_FORM.value,
                    claim_number=n,
                    message=(
                        f"Claim {n} appears to use multiple-dependent form "
                        f"(review flag only; not a legal conclusion)."
                    ),
                    severity="info",
                )
            )
        parents = _parent_claim_numbers(text)
        for parent in parents:
            if parent >= n:
                flags.append(
                    ReviewFlag(
                        code=ReviewFlagCode.FORWARD_DEPENDENCY.value,
                        claim_number=n,
                        message=(
                            f"Claim {n} depends on claim {parent} "
                            f"(parent should be a lower number) — review flag only."
                        ),
                        severity="error",
                    )
                )
            elif parent not in num_set:
                flags.append(
                    ReviewFlag(
                        code=ReviewFlagCode.MISSING_PARENT.value,
                        claim_number=n,
                        message=(
                            f"Claim {n} references missing parent claim {parent} "
                            f"(broken dependency heuristic)."
                        ),
                        severity="warning",
                    )
                )
            if parent not in num_set or parent >= n:
                flags.append(
                    ReviewFlag(
                        code=ReviewFlagCode.BROKEN_DEPENDENCY.value,
                        claim_number=n,
                        message=(
                            f"Claim {n} has broken dependency reference to {parent}."
                        ),
                        severity="warning",
                    )
                )

        # Weak antecedent heuristic (independent claims only)
        if parents:
            continue
        introduced = {
            m.group(1).lower().strip() for m in _INDEF_ARTICLE_RE.finditer(text)
        }
        suspects: list[str] = []
        for m in _ANTECEDENT_RE.finditer(text):
            phrase = m.group(1).lower().strip()
            if phrase in introduced or phrase in _SKIP_ANTECEDENT_HEADS:
                continue
            head = phrase.split()[-1]
            if any(head == t.split()[-1] for t in introduced):
                continue
            suspects.append(phrase)
        if len(suspects) >= 6:
            flags.append(
                ReviewFlag(
                    code=ReviewFlagCode.WEAK_ANTECEDENT.value,
                    claim_number=n,
                    message=(
                        f"Claim {n}: many 'the/said' phrases without clear "
                        f"'a/an' introduction — human antecedent review advised "
                        f"(sample: {suspects[:5]}). Not a §112 conclusion."
                    ),
                    severity="info",
                )
            )
    return flags


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_claim_limitation_graph(
    *,
    claims: Sequence[Mapping[str, Any]] | None = None,
    claims_text: str | None = None,
    claims_file: str | None = None,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    max_claims: int = DEFAULT_MAX_CLAIMS,
    max_limitations_per_claim: int = DEFAULT_MAX_LIMITATIONS_PER_CLAIM,
    metadata: Mapping[str, str] | None = None,
) -> ClaimLimitationGraph:
    """Parse claims into a limitation graph with quality gate.

    Accepts the same claim sources as ``load_claims``. Never logs full claim
    bodies to ordinary logs.
    """
    raw_source = claims_text or ""
    if claims_file and not raw_source:
        # Digest only; load_claims reads the file
        raw_source = f"file:{claims_file}"

    try:
        parsed = load_claims(
            claims=claims, claims_file=claims_file, claims_text=claims_text
        )
    except Exception as exc:
        # Fail closed: empty graph with review_required
        _safe_log_event(
            "parse_failed",
            code=getattr(exc, "code", type(exc).__name__),
            message=str(exc)[:200],
        )
        quality = assess_quality_gate(
            claims=[], threshold=quality_threshold
        )
        empty_flags = (
            ReviewFlag(
                code=ReviewFlagCode.EMPTY_CLAIMS.value,
                claim_number=None,
                message=f"Claim load failed: {type(exc).__name__}",
                severity="error",
            ),
        )
        return ClaimLimitationGraph(
            schema=CLAIM_LIMITATION_MODEL_SCHEMA,
            claims=(),
            limitations=(),
            quality=quality,
            review_flags=empty_flags,
            content_digest=_sha256_hex("empty"),
            source_digest=_sha256_hex(raw_source or "empty"),
            metadata=dict(metadata or {}),
        )

    if max_claims > 0:
        parsed = parsed[:max_claims]

    claim_pairs: list[tuple[int, str]] = []
    for item in parsed:
        n = int(item["claim_number"])
        text = _collapse_ws(str(item.get("claim_text") or ""))
        if n > 0 and text:
            claim_pairs.append((n, text))

    source_material = claims_text or "\n".join(t for _, t in claim_pairs)
    source_digest = _sha256_hex(source_material)

    flags = _collect_review_flags(claim_pairs)
    quality = assess_quality_gate(
        claims=[{"claim_number": n, "claim_text": t} for n, t in claim_pairs],
        review_flags=flags,
        raw_text=claims_text,
        threshold=quality_threshold,
    )
    if quality.low_ocr_quality:
        flags.append(
            ReviewFlag(
                code=ReviewFlagCode.LOW_OCR_QUALITY.value,
                claim_number=None,
                message=(
                    f"Claim OCR quality score {quality.quality_score:.2f} "
                    f"below threshold {quality.threshold:.2f}; automated "
                    f"conflict screening is non-authoritative "
                    f"(gate={quality.gate_code.value})."
                ),
                severity="warning",
            )
        )

    claim_nodes: list[ClaimNode] = []
    limitation_nodes: list[ClaimLimitationNode] = []

    for n, text in claim_pairs:
        parents = _parent_claim_numbers(text)
        if _MULTIPLE_DEPENDENT_RE.search(text) and len(parents) > 1:
            kind = ClaimDependencyKind.MULTIPLE_DEPENDENT
        elif parents:
            kind = ClaimDependencyKind.DEPENDENT
        else:
            kind = ClaimDependencyKind.INDEPENDENT

        parts = _split_limitation_parts(text)[:max_limitations_per_claim]
        lim_ids: list[str] = []
        offset = 0
        for ordinal, part in enumerate(parts, start=1):
            lim_id = f"lim:c{n}-{ordinal}"
            lim_ids.append(lim_id)
            idx = text.find(part, offset)
            if idx < 0:
                idx = text.find(part)
            if idx < 0:
                idx = offset
            span = LimitationSpan(start=idx, end=idx + len(part))
            offset = span.end
            numerals = tuple(
                m.group(1)
                for m in _REF_NUMERAL_RE.finditer(part)
                if not (len(m.group(1)) == 1 and m.group(1) in {"1", "2", "3"})
            )[:16]
            limitation_nodes.append(
                ClaimLimitationNode(
                    limitation_id=lim_id,
                    claim_number=n,
                    ordinal=ordinal,
                    text=part[:DEFAULT_MAX_LIMITATION_CHARS],
                    span=span,
                    dependency_kind=kind,
                    parent_claim_numbers=parents,
                    reference_numerals=numerals,
                )
            )

        claim_nodes.append(
            ClaimNode(
                claim_number=n,
                dependency_kind=kind,
                parent_claim_numbers=parents,
                limitation_ids=tuple(lim_ids),
                text_digest=_sha256_hex(text),
                char_count=len(text),
                text=text,
            )
        )

    # Content digest excludes raw text bodies (stable structural fingerprint)
    structural = {
        "claims": [
            {
                "claim_number": c.claim_number,
                "dependency_kind": c.dependency_kind.value,
                "parent_claim_numbers": list(c.parent_claim_numbers),
                "limitation_ids": list(c.limitation_ids),
                "text_digest": c.text_digest,
            }
            for c in claim_nodes
        ],
        "limitations": [
            {
                "limitation_id": lim.limitation_id,
                "claim_number": lim.claim_number,
                "ordinal": lim.ordinal,
                "text_digest": lim.text_digest,
                "span": lim.span.to_dict(),
            }
            for lim in limitation_nodes
        ],
        "quality": quality.to_dict(),
    }
    import json as _json

    content_digest = _sha256_hex(
        _json.dumps(structural, sort_keys=True, separators=(",", ":"))
    )

    _safe_log_event(
        "graph_built",
        claim_count=len(claim_nodes),
        limitation_count=len(limitation_nodes),
        quality_score=quality.quality_score,
        authority_mode=quality.authority_mode.value,
        gate_code=quality.gate_code.value,
        flag_count=len(flags),
        content_digest=content_digest[:16],
    )

    return ClaimLimitationGraph(
        schema=CLAIM_LIMITATION_MODEL_SCHEMA,
        claims=tuple(claim_nodes),
        limitations=tuple(limitation_nodes),
        quality=quality,
        review_flags=tuple(flags),
        content_digest=content_digest,
        source_digest=source_digest,
        metadata=dict(metadata or {}),
    )


def parse_claims_to_graph(text: str, **kwargs: Any) -> ClaimLimitationGraph:
    """Convenience wrapper: free-text claims → limitation graph."""
    return build_claim_limitation_graph(claims_text=text, **kwargs)


def graph_is_authoritative_for_conflict(graph: ClaimLimitationGraph) -> bool:
    """Return True only when automated conflict screening may treat graph as authority."""
    return (
        graph.quality.authority_mode is AuthorityMode.AUTHORITATIVE
        and not graph.quality.low_ocr_quality
        and not graph.quality.review_required
        and bool(graph.claims)
    )


__all__ = [
    "CLAIM_LIMITATION_MODEL_SCHEMA",
    "CLAIM_LIMITATION_MODEL_INTERFACE",
    "CLAIM_LIMITATION_MODEL_CODE_VERSION",
    "OUTPUT_KIND_CLAIM_LIMITATION_GRAPH",
    "REVIEW_ONLY_CLAIM_MODEL_DISCLAIMER",
    "DEFAULT_QUALITY_THRESHOLD",
    "AuthorityMode",
    "ClaimDependencyKind",
    "ClaimLimitationGraph",
    "ClaimLimitationModelError",
    "ClaimLimitationNode",
    "ClaimNode",
    "LimitationSpan",
    "QualityAssessment",
    "QualityGateCode",
    "ReviewFlag",
    "ReviewFlagCode",
    "aggregate_quality_score",
    "assess_quality_gate",
    "build_claim_limitation_graph",
    "graph_is_authoritative_for_conflict",
    "parse_claims_text",
    "parse_claims_to_graph",
    "score_claim_ocr_quality",
]
