"""Bind obligations to specific submission evidence and proofs (PATLAW-130).

Normalizes each government demand into atomic obligations and binds them to
exact responsive document / claim / argument / amendment / declaration / fee /
form evidence, required conditions, exceptions, contradictions, and proof
results.

Design invariants
-----------------
* **Unrelated remarks cannot satisfy a rejection response.** Category presence
  alone (e.g. any remarks document) is never enough; claim and/or citation
  overlap with the demand is required for rejection/objection responses.
* **Partial / conditional / contradictory evidence** yields incomplete /
  unknown / fail as appropriate — never an implicit pass.
* **Every result** carries obligation, evidence, authority, and proof
  provenance legs (identifiers/digests; no body-text logging).
* **Model similarity may rank candidates only.** Satisfaction requires
  admitted exact-binding evidence plus a proof receipt or documented
  deterministic rule; model-origin scores never establish satisfaction.
* Lack of counter-evidence is never converted into proof of satisfaction.
* Document body text is never written to logs or exception messages.

Owns obligation-specific matching and proof orchestration only (conflict
policy for PATLAW-130). Consumes office-action semantics v2, submission-
package semantics v2, and privacy-safe Legal IR proof execution.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
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
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_proof_executor import (
    LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
    AtomicLiteral,
    LegalIRProofExecutor,
    LogicFamily,
    PremiseCitation,
    ProofExecutionRequest,
    ProofExecutorConfig,
    ProofOutcome,
    ProofProblem,
    ProofReasonCode,
    execute_legal_ir_proof,
)

# Optional v2 semantics (consume without owning). Soft imports keep unit tests
# runnable when only compact obligation/evidence fixtures are supplied.
try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_semantics_v2 import (
        SEMANTICS_V2_SCHEMA_VERSION as OA_SEMANTICS_SCHEMA_VERSION,
        AdmissionState as OaAdmissionState,
        FieldOrigin as OaFieldOrigin,
        SemanticField,
        SemanticFieldKind,
    )
except Exception:  # pragma: no cover
    OA_SEMANTICS_SCHEMA_VERSION = "uspto.office-action-semantics.v2"
    OaAdmissionState = None  # type: ignore[misc, assignment]
    OaFieldOrigin = None  # type: ignore[misc, assignment]
    SemanticField = None  # type: ignore[misc, assignment]
    SemanticFieldKind = None  # type: ignore[misc, assignment]

try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.submission_package_semantics_v2 import (
        SEMANTICS_V2_SCHEMA_VERSION as PKG_SEMANTICS_SCHEMA_VERSION,
        AdmissionState as PkgAdmissionState,
        FactKind,
        FieldOrigin as PkgFieldOrigin,
        NormalizedFact,
    )
except Exception:  # pragma: no cover
    PKG_SEMANTICS_SCHEMA_VERSION = "uspto.submission-package-semantics.v2"
    PkgAdmissionState = None  # type: ignore[misc, assignment]
    FactKind = None  # type: ignore[misc, assignment]
    PkgFieldOrigin = None  # type: ignore[misc, assignment]
    NormalizedFact = None  # type: ignore[misc, assignment]

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

SEMANTIC_COMPLIANCE_SCHEMA_VERSION: Final = "uspto.semantic-compliance.v1"
SEMANTIC_COMPLIANCE_INTERFACE: Final = "SemanticComplianceProcessor@1"
SEMANTIC_COMPLIANCE_RULESET_VERSION: Final = "semantic-compliance-rules@1"
PARSER_VERSION: Final = "patlaw-130.semantic-compliance.v1"

OUTPUT_KIND_SEMANTIC_COMPLIANCE: Final = (
    "semantic_obligation_evidence_proof_binding"
)

NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER: Final = (
    "This output binds government demands to exact submission evidence and "
    "optional bounded proof receipts for review only. It does not make a final "
    "legal determination, does not establish compliance for filing or docket "
    "purposes, and is not a substitute for attorney judgment. Human review is "
    "required before any legal conclusion."
)

DEFAULT_MAX_OBLIGATIONS: Final = 4096
DEFAULT_MAX_CANDIDATES: Final = 256
DEFAULT_MAX_BINDINGS: Final = 128
DEFAULT_MAX_SURFACE: Final = 8000
DEFAULT_MAX_EXCERPT: Final = 4000

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")

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
        "summary_substituted_for_obligation",
        "summary_substituted_for_evidence",
        "paraphrase_as_authority",
        "paraphrase_as_obligation",
    }
)

# ---------------------------------------------------------------------------
# Documented deterministic rules (identity + digest; not free-form heuristics)
# ---------------------------------------------------------------------------


def _rule_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json(dict(payload)).encode("utf-8")
    ).hexdigest()


_RULE_EXACT_CLAIM_CITATION_BINDING: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "rule_id": "sc.exact_claim_citation_binding",
        "rule_version": "1",
        "description": (
            "Admitted evidence of a compatible responsive kind shares at least "
            "one claim token and/or citation key with the obligation; no "
            "unresolved counter-evidence; conditions empty or all met."
        ),
        "preconditions": (
            "obligation_admitted_or_normalized",
            "evidence_admitted",
            "kind_compatible",
            "claim_or_citation_overlap",
            "no_unresolved_counter",
            "conditions_resolved",
        ),
        "on_no_match": "no_op",
        "deterministic": True,
    }
)

_RULE_FEE_FORM_PRESENCE: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "rule_id": "sc.fee_form_presence_binding",
        "rule_version": "1",
        "description": (
            "Fee or form obligation is bound to admitted fee/form evidence with "
            "matching normalized identifier when supplied; category presence of "
            "unrelated document kinds never satisfies."
        ),
        "preconditions": (
            "obligation_kind_fee_or_form",
            "evidence_admitted",
            "kind_compatible",
            "identifier_match_or_absent",
            "no_unresolved_counter",
        ),
        "on_no_match": "no_op",
        "deterministic": True,
    }
)

_RULE_REJECTION_REQUIRES_RESPONSIVE_ARGUMENT: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "rule_id": "sc.rejection_requires_responsive_argument",
        "rule_version": "1",
        "description": (
            "Rejection/objection response obligations require admitted "
            "argument/amendment/claim evidence that overlaps claim tokens "
            "and/or statutory/regulatory citation keys of the demand. Unrelated "
            "remarks (no claim/citation overlap) cannot satisfy."
        ),
        "preconditions": (
            "obligation_kind_rejection_or_objection",
            "evidence_admitted",
            "responsive_kind",
            "claim_or_citation_overlap",
            "no_unresolved_counter",
        ),
        "on_no_match": "no_op",
        "deterministic": True,
    }
)

_DOCUMENTED_RULES_RAW: Final[tuple[Mapping[str, Any], ...]] = (
    _RULE_EXACT_CLAIM_CITATION_BINDING,
    _RULE_FEE_FORM_PRESENCE,
    _RULE_REJECTION_REQUIRES_RESPONSIVE_ARGUMENT,
)

DOCUMENTED_DETERMINISTIC_RULES: Final[Mapping[str, Mapping[str, Any]]] = MappingProxyType(
    {
        f"{r['rule_id']}@{r['rule_version']}": MappingProxyType(
            {
                **dict(r),
                "rule_digest": _rule_digest(r),
            }
        )
        for r in _DOCUMENTED_RULES_RAW
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ObligationKind(str, Enum):
    """Normalized atomic government demand kinds."""

    REJECTION_RESPONSE = "rejection_response"
    OBJECTION_RESPONSE = "objection_response"
    REQUIREMENT_ACT = "requirement_act"
    AMENDMENT = "amendment"
    DECLARATION = "declaration"
    FEE = "fee"
    FORM = "form"
    ELECTION = "election"
    SIGNATURE = "signature"
    SEQUENCE = "sequence"
    OTHER = "other"
    UNKNOWN = "unknown"


class ResponsiveEvidenceKind(str, Enum):
    """Evidence kinds that may respond to an obligation (closed set)."""

    ARGUMENT = "argument"
    AMENDMENT = "amendment"
    CLAIM = "claim"
    DECLARATION = "declaration"
    FEE = "fee"
    FORM = "form"
    SIGNATURE = "signature"
    SEQUENCE = "sequence"
    DOCUMENT = "document"
    RECEIPT = "receipt"
    OTHER = "other"
    UNKNOWN = "unknown"


class SatisfactionStatus(str, Enum):
    """Per-obligation satisfaction outcome (fail-closed)."""

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    FAIL = "fail"


class BindingRole(str, Enum):
    """Role of an evidence binding relative to an obligation."""

    SUPPORT = "support"
    COUNTER = "counter"
    CANDIDATE_RANKED = "candidate_ranked"
    CONDITION = "condition"
    EXCEPTION = "exception"
    UNRELATED = "unrelated"


class EvidenceAdmission(str, Enum):
    """Admission state of candidate evidence for satisfaction."""

    ADMITTED = "admitted"
    CANDIDATE = "candidate"
    REJECTED = "rejected"
    REVIEW_REQUIRED = "review_required"


class EvidenceOrigin(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    MODEL = "model"
    METADATA = "metadata"
    LAYOUT = "layout"
    OTHER = "other"


class ComplianceDisposition(str, Enum):
    """Top-level pipeline disposition."""

    BOUND = "bound"
    PARTIAL = "partial"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    REVIEW = "review"
    UNKNOWN = "unknown"
    QUARANTINE = "quarantine"
    EMPTY = "empty"
    REJECTED = "rejected"


class SemanticComplianceReasonCode(str, Enum):
    """Stable machine-readable reason codes."""

    OBLIGATIONS_NORMALIZED = "obligations_normalized"
    OBLIGATIONS_BOUND = "obligations_bound"
    RESULTS_EMITTED = "results_emitted"
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    INCOMPLETE = "incomplete"
    UNKNOWN_STATUS = "unknown_status"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    UNRELATED_REMARKS_REJECTED = "unrelated_remarks_rejected"
    CLAIM_OVERLAP = "claim_overlap"
    CLAIM_NO_OVERLAP = "claim_no_overlap"
    CITATION_OVERLAP = "citation_overlap"
    CITATION_NO_OVERLAP = "citation_no_overlap"
    KIND_COMPATIBLE = "kind_compatible"
    KIND_INCOMPATIBLE = "kind_incompatible"
    EVIDENCE_ADMITTED = "evidence_admitted"
    EVIDENCE_CANDIDATE_ONLY = "evidence_candidate_only"
    EVIDENCE_ABSENT = "evidence_absent"
    EVIDENCE_COUNTER = "evidence_counter"
    CONTRADICTION = "contradiction"
    UNRESOLVED_CONTRADICTION = "unresolved_contradiction"
    CONDITIONS_MET = "conditions_met"
    CONDITIONS_UNMET = "conditions_unmet"
    CONDITIONS_PARTIAL = "conditions_partial"
    EXCEPTION_APPLIES = "exception_applies"
    AUTHORITY_PROVENANCE = "authority_provenance"
    AUTHORITY_MISSING = "authority_missing"
    PROOF_PROVED = "proof_proved"
    PROOF_DISPROVED = "proof_disproved"
    PROOF_UNKNOWN = "proof_unknown"
    PROOF_TIMEOUT = "proof_timeout"
    PROOF_ERROR = "proof_error"
    PROOF_SKIPPED = "proof_skipped"
    DETERMINISTIC_RULE_APPLIED = "deterministic_rule_applied"
    DETERMINISTIC_RULE_FAILED = "deterministic_rule_failed"
    MODEL_SIMILARITY_RANKED = "model_similarity_ranked"
    MODEL_SIMILARITY_NOT_SATISFACTION = "model_similarity_not_satisfaction"
    MODEL_ORIGIN_CANNOT_SATISFY = "model_origin_cannot_satisfy"
    CATEGORY_PRESENCE_NOT_SATISFACTION = "category_presence_not_satisfaction"
    PROVENANCE_COMPLETE = "provenance_complete"
    PROVENANCE_INCOMPLETE = "provenance_incomplete"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    HUMAN_REVIEW_BOUNDARY_EXPOSED = "human_review_boundary_exposed"
    NOT_FINAL_LEGAL_DETERMINATION = "not_final_legal_determination"
    NO_MODEL_SUMMARY_SUBSTITUTION = "no_model_summary_substitution"
    EMPTY_INPUT = "empty_input"
    QUARANTINED = "quarantined"
    OBLIGATION_LIMIT = "obligation_limit"
    CANDIDATE_LIMIT = "candidate_limit"
    FORBIDDEN_LABEL_STRIPPED = "forbidden_label_stripped"
    OVERALL_PASS = "overall_pass"
    OVERALL_FAIL_CLOSED = "overall_fail_closed"


class SemanticComplianceError(ValueError):
    """Bounded violation with a stable machine-readable code."""

    def __init__(
        self, message: str, *, code: str = "semantic_compliance_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Kind compatibility maps
# ---------------------------------------------------------------------------

_OBLIGATION_RESPONSIVE_KINDS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        ObligationKind.REJECTION_RESPONSE.value: frozenset(
            {
                ResponsiveEvidenceKind.ARGUMENT.value,
                ResponsiveEvidenceKind.AMENDMENT.value,
                ResponsiveEvidenceKind.CLAIM.value,
                ResponsiveEvidenceKind.DECLARATION.value,
            }
        ),
        ObligationKind.OBJECTION_RESPONSE.value: frozenset(
            {
                ResponsiveEvidenceKind.ARGUMENT.value,
                ResponsiveEvidenceKind.AMENDMENT.value,
                ResponsiveEvidenceKind.CLAIM.value,
                ResponsiveEvidenceKind.DOCUMENT.value,
            }
        ),
        ObligationKind.REQUIREMENT_ACT.value: frozenset(
            {
                ResponsiveEvidenceKind.ARGUMENT.value,
                ResponsiveEvidenceKind.AMENDMENT.value,
                ResponsiveEvidenceKind.DOCUMENT.value,
                ResponsiveEvidenceKind.FORM.value,
                ResponsiveEvidenceKind.DECLARATION.value,
            }
        ),
        ObligationKind.AMENDMENT.value: frozenset(
            {
                ResponsiveEvidenceKind.AMENDMENT.value,
                ResponsiveEvidenceKind.CLAIM.value,
            }
        ),
        ObligationKind.DECLARATION.value: frozenset(
            {ResponsiveEvidenceKind.DECLARATION.value}
        ),
        ObligationKind.FEE.value: frozenset(
            {
                ResponsiveEvidenceKind.FEE.value,
                ResponsiveEvidenceKind.RECEIPT.value,
            }
        ),
        ObligationKind.FORM.value: frozenset({ResponsiveEvidenceKind.FORM.value}),
        ObligationKind.ELECTION.value: frozenset(
            {
                ResponsiveEvidenceKind.ARGUMENT.value,
                ResponsiveEvidenceKind.DOCUMENT.value,
                ResponsiveEvidenceKind.FORM.value,
            }
        ),
        ObligationKind.SIGNATURE.value: frozenset(
            {ResponsiveEvidenceKind.SIGNATURE.value}
        ),
        ObligationKind.SEQUENCE.value: frozenset(
            {ResponsiveEvidenceKind.SEQUENCE.value}
        ),
        ObligationKind.OTHER.value: frozenset(
            {k.value for k in ResponsiveEvidenceKind if k is not ResponsiveEvidenceKind.UNKNOWN}
        ),
        ObligationKind.UNKNOWN.value: frozenset(),
    }
)

# Obligation kinds that require claim/citation overlap (not mere category presence).
_OVERLAP_REQUIRED_KINDS: Final[frozenset[str]] = frozenset(
    {
        ObligationKind.REJECTION_RESPONSE.value,
        ObligationKind.OBJECTION_RESPONSE.value,
        ObligationKind.AMENDMENT.value,
    }
)

_OA_FIELD_TO_OBLIGATION: Final[Mapping[str, str]] = MappingProxyType(
    {
        "rejection": ObligationKind.REJECTION_RESPONSE.value,
        "objection": ObligationKind.OBJECTION_RESPONSE.value,
        "requirement": ObligationKind.REQUIREMENT_ACT.value,
        "form": ObligationKind.FORM.value,
        "allowance": ObligationKind.FEE.value,  # issue fee demand often co-located
        "signature": ObligationKind.SIGNATURE.value,
    }
)

_PKG_FACT_TO_EVIDENCE: Final[Mapping[str, str]] = MappingProxyType(
    {
        "argument": ResponsiveEvidenceKind.ARGUMENT.value,
        "amendment": ResponsiveEvidenceKind.AMENDMENT.value,
        "claim": ResponsiveEvidenceKind.CLAIM.value,
        "declaration": ResponsiveEvidenceKind.DECLARATION.value,
        "fee_assertion": ResponsiveEvidenceKind.FEE.value,
        "form": ResponsiveEvidenceKind.FORM.value,
        "signature_presence": ResponsiveEvidenceKind.SIGNATURE.value,
        "sequence_listing": ResponsiveEvidenceKind.SEQUENCE.value,
        "attachment": ResponsiveEvidenceKind.DOCUMENT.value,
        "receipt": ResponsiveEvidenceKind.RECEIPT.value,
        "specification": ResponsiveEvidenceKind.DOCUMENT.value,
        "drawing": ResponsiveEvidenceKind.DOCUMENT.value,
        "other": ResponsiveEvidenceKind.OTHER.value,
    }
)


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


def _require_str(value: Any, field_name: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field_name} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field_name: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str or None")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field_name} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field_name: str) -> str:
    text = _require_str(value, field_name, max_len=256)
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field_name} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field_name: str) -> str | None:
    text = _optional_str(value, field_name, max_len=256)
    if text is None:
        return None
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field_name} is not a valid identifier: {text!r}")
    return text


def _nonneg_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _optional_float_01(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be float or None")
    f = float(value)
    if f < 0.0 or f > 1.0:
        raise ValueError(f"{field_name} must be in [0, 1]")
    return f


def _coerce_enum(enum_cls: type[Enum], value: Any, field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError:
            for member in enum_cls:
                if member.value == value or member.name.lower() == value.lower():
                    return member
    raise ValueError(f"{field_name} is not a valid {enum_cls.__name__}: {value!r}")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if value is None:
        return DisclosureClassification.PUBLIC_USER
    return _coerce_enum(DisclosureClassification, value, "classification")  # type: ignore[return-value]


def _tuple_of_str(
    value: Any, field_name: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, Sequence):
        items = tuple(str(x).strip() for x in value if str(x).strip())
    else:
        raise TypeError(f"{field_name} must be a sequence of str")
    if len(items) > max_items:
        items = items[:max_items]
    return items


def _frozen_str_map(
    value: Any, field_name: str, *, max_items: int = 64
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    out: dict[str, str] = {}
    for i, (k, v) in enumerate(value.items()):
        if i >= max_items:
            break
        key = str(k).strip()
        if not key or key in _FORBIDDEN_SUMMARY_KEYS:
            continue
        if contains_forbidden_unlawful_token(key) or contains_forbidden_unlawful_token(
            str(v)
        ):
            continue
        out[key] = str(v)[:512]
    return MappingProxyType(out)


def _optional_sha256(value: Any, field_name: str) -> str | None:
    text = _optional_str(value, field_name, max_len=64)
    if text is None:
        return None
    lowered = text.lower()
    if not _SHA256_RE.match(lowered):
        raise ValueError(f"{field_name} must be sha256 hex")
    return lowered


def _sha256_hex_field(value: Any, field_name: str) -> str:
    text = _require_str(value, field_name, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field_name} must be sha256 hex")
    return text


def contains_forbidden_unlawful_token(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower().replace("-", "_").replace(" ", "_")
    for tok in _FORBIDDEN_UNLAWFUL_TOKENS:
        if tok in lowered:
            return True
    return False


def sanitize_labels(
    labels: Mapping[str, str] | None,
) -> tuple[Mapping[str, str], tuple[str, ...]]:
    if not labels:
        return MappingProxyType({}), ()
    reasons: list[str] = []
    out: dict[str, str] = {}
    for k, v in labels.items():
        key = str(k).strip()
        if key in _FORBIDDEN_SUMMARY_KEYS or contains_forbidden_unlawful_token(key):
            reasons.append(SemanticComplianceReasonCode.FORBIDDEN_LABEL_STRIPPED.value)
            continue
        if contains_forbidden_unlawful_token(str(v)):
            reasons.append(SemanticComplianceReasonCode.FORBIDDEN_LABEL_STRIPPED.value)
            continue
        out[key] = str(v)[:512]
    return MappingProxyType(out), tuple(dict.fromkeys(reasons))


def tokenize_surface(text: str) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall((text or "").lower()))


def jaccard_similarity(a: Iterable[str], b: Iterable[str]) -> float:
    """Bounded token Jaccard used only for candidate ranking (never satisfaction)."""
    sa = set(a)
    sb = set(b)
    if not sa and not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    if union == 0:
        return 0.0
    return inter / union


def responsive_kinds_for(obligation_kind: ObligationKind | str) -> frozenset[str]:
    key = (
        obligation_kind.value
        if isinstance(obligation_kind, ObligationKind)
        else str(obligation_kind)
    )
    return _OBLIGATION_RESPONSIVE_KINDS.get(key, frozenset())


def requires_claim_or_citation_overlap(obligation_kind: ObligationKind | str) -> bool:
    key = (
        obligation_kind.value
        if isinstance(obligation_kind, ObligationKind)
        else str(obligation_kind)
    )
    return key in _OVERLAP_REQUIRED_KINDS


def is_satisfaction_pass(status: SatisfactionStatus | str) -> bool:
    if isinstance(status, SatisfactionStatus):
        return status is SatisfactionStatus.SATISFIED
    return str(status) == SatisfactionStatus.SATISFIED.value


def documented_rule(rule_key: str) -> Mapping[str, Any] | None:
    return DOCUMENTED_DETERMINISTIC_RULES.get(rule_key)


def list_documented_rules() -> tuple[str, ...]:
    return tuple(sorted(DOCUMENTED_DETERMINISTIC_RULES.keys()))


def map_pkg_fact_kind(kind: Any) -> ResponsiveEvidenceKind:
    if isinstance(kind, ResponsiveEvidenceKind):
        return kind
    raw = kind.value if hasattr(kind, "value") else str(kind or "unknown")
    mapped = _PKG_FACT_TO_EVIDENCE.get(raw.lower(), ResponsiveEvidenceKind.OTHER.value)
    return ResponsiveEvidenceKind(mapped)


def map_oa_field_kind(kind: Any) -> ObligationKind:
    if isinstance(kind, ObligationKind):
        return kind
    raw = kind.value if hasattr(kind, "value") else str(kind or "unknown")
    mapped = _OA_FIELD_TO_OBLIGATION.get(
        raw.lower(), ObligationKind.OTHER.value
    )
    # Prefer rejection_response for rejection fields.
    if raw.lower() == "rejection":
        return ObligationKind.REJECTION_RESPONSE
    if raw.lower() == "objection":
        return ObligationKind.OBJECTION_RESPONSE
    try:
        return ObligationKind(mapped)
    except ValueError:
        return ObligationKind.OTHER


# ---------------------------------------------------------------------------
# Data records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisBounds:
    max_obligations: int = DEFAULT_MAX_OBLIGATIONS
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    max_bindings: int = DEFAULT_MAX_BINDINGS
    max_surface: int = DEFAULT_MAX_SURFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_obligations", max(1, int(self.max_obligations))
        )
        object.__setattr__(
            self, "max_candidates", max(1, int(self.max_candidates))
        )
        object.__setattr__(self, "max_bindings", max(1, int(self.max_bindings)))
        object.__setattr__(self, "max_surface", max(64, int(self.max_surface)))


@dataclass(frozen=True, slots=True)
class AuthorityProvenance:
    """Authority leg of a compliance result (identifiers / versions only)."""

    authority_id: str
    citation_surface: str | None
    citation_key: str | None
    version: str | None
    node_id: str | None
    content_sha256: str | None
    authority_rank: str | None
    resolution_state: str
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "authority_id", _identifier(self.authority_id, "authority_id")
        )
        object.__setattr__(
            self,
            "citation_surface",
            _optional_str(self.citation_surface, "citation_surface", max_len=256),
        )
        object.__setattr__(
            self,
            "citation_key",
            _optional_str(self.citation_key, "citation_key", max_len=128),
        )
        object.__setattr__(
            self, "version", _optional_str(self.version, "version", max_len=64)
        )
        object.__setattr__(
            self, "node_id", _optional_identifier(self.node_id, "node_id")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _optional_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self,
            "authority_rank",
            _optional_str(self.authority_rank, "authority_rank", max_len=64),
        )
        object.__setattr__(
            self,
            "resolution_state",
            _require_str(self.resolution_state, "resolution_state", max_len=64),
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

    @property
    def is_resolved(self) -> bool:
        return self.resolution_state in ("resolved", "exact", "binding")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "authority_rank": self.authority_rank,
            "citation_key": self.citation_key,
            "citation_surface": self.citation_surface,
            "content_sha256": self.content_sha256,
            "is_resolved": self.is_resolved,
            "labels": dict(self.labels),
            "node_id": self.node_id,
            "resolution_state": self.resolution_state,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityProvenance":
        if not isinstance(value, Mapping):
            raise TypeError("AuthorityProvenance must be a mapping")
        return cls(
            authority_id=str(value.get("authority_id") or "auth:unknown"),
            citation_surface=value.get("citation_surface"),
            citation_key=value.get("citation_key"),
            version=value.get("version"),
            node_id=value.get("node_id"),
            content_sha256=value.get("content_sha256"),
            authority_rank=value.get("authority_rank"),
            resolution_state=str(value.get("resolution_state") or "unknown"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ProofProvenance:
    """Proof leg of a compliance result (identifiers / outcomes only)."""

    receipt_id: str
    outcome: str
    reason_codes: tuple[str, ...]
    engine_id: str | None
    engine_version: str | None
    config_digest: str | None
    problem_id: str | None
    premise_ids: tuple[str, ...]
    statement_digest: str | None
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
            self, "problem_id", _optional_identifier(self.problem_id, "problem_id")
        )
        object.__setattr__(
            self,
            "premise_ids",
            _tuple_of_str(self.premise_ids, "premise_ids", max_items=128),
        )
        object.__setattr__(
            self,
            "statement_digest",
            _optional_sha256(self.statement_digest, "statement_digest"),
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

    @property
    def is_proved(self) -> bool:
        return self.outcome == ProofOutcome.PROVED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_digest": self.config_digest,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "is_proved": self.is_proved,
            "labels": dict(self.labels),
            "outcome": self.outcome,
            "premise_ids": list(self.premise_ids),
            "problem_id": self.problem_id,
            "reason_codes": list(self.reason_codes),
            "receipt_id": self.receipt_id,
            "statement_digest": self.statement_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofProvenance":
        if not isinstance(value, Mapping):
            raise TypeError("ProofProvenance must be a mapping")
        return cls(
            receipt_id=str(value.get("receipt_id") or "proof:unknown"),
            outcome=str(value.get("outcome") or ProofOutcome.UNKNOWN.value),
            reason_codes=tuple(value.get("reason_codes") or ()),
            engine_id=value.get("engine_id"),
            engine_version=value.get("engine_version"),
            config_digest=value.get("config_digest"),
            problem_id=value.get("problem_id"),
            premise_ids=tuple(value.get("premise_ids") or ()),
            statement_digest=value.get("statement_digest"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class DeterministicRuleReceipt:
    """Receipt that a named deterministic rule's preconditions were met."""

    receipt_id: str
    rule_id: str
    rule_version: str
    rule_digest: str
    applied: bool
    preconditions_met: tuple[str, ...]
    preconditions_failed: tuple[str, ...]
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
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
            _tuple_of_str(self.preconditions_met, "preconditions_met", max_items=64),
        )
        object.__setattr__(
            self,
            "preconditions_failed",
            _tuple_of_str(
                self.preconditions_failed, "preconditions_failed", max_items=64
            ),
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "labels": dict(self.labels),
            "preconditions_failed": list(self.preconditions_failed),
            "preconditions_met": list(self.preconditions_met),
            "receipt_id": self.receipt_id,
            "rule_digest": self.rule_digest,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeterministicRuleReceipt":
        if not isinstance(value, Mapping):
            raise TypeError("DeterministicRuleReceipt must be a mapping")
        return cls(
            receipt_id=str(value.get("receipt_id") or "rule:unknown"),
            rule_id=str(value.get("rule_id") or "unknown"),
            rule_version=str(value.get("rule_version") or "0"),
            rule_digest=str(value.get("rule_digest") or ("0" * 64)),
            applied=bool(value.get("applied", False)),
            preconditions_met=tuple(value.get("preconditions_met") or ()),
            preconditions_failed=tuple(value.get("preconditions_failed") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class HumanReviewBoundary:
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
        # Never a final legal determination from this module.
        object.__setattr__(self, "is_final_legal_determination", False)
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self,
            "boundary_reason",
            _require_str(self.boundary_reason, "boundary_reason", max_len=256),
        )
        object.__setattr__(
            self,
            "review_question",
            _require_str(self.review_question, "review_question", max_len=1024),
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
            "review_state": self.review_state.value
            if isinstance(self.review_state, ReviewState)
            else str(self.review_state),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanReviewBoundary":
        if not isinstance(value, Mapping):
            raise TypeError("HumanReviewBoundary must be a mapping")
        return cls(
            requires_human_review=bool(value.get("requires_human_review", True)),
            is_final_legal_determination=False,
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            boundary_reason=str(value.get("boundary_reason") or "review_required"),
            review_question=str(
                value.get("review_question") or "Human review required."
            ),
            confidence=value.get("confidence"),
            may_auto_pass=bool(value.get("may_auto_pass", False)),
        )


@dataclass(frozen=True, slots=True)
class AtomicObligation:
    """One normalized atomic government demand with exact source anchors."""

    obligation_id: str
    kind: ObligationKind
    source_span_ids: tuple[str, ...]
    source_field_id: str | None
    surface_text: str
    text_digest: str
    claim_tokens: tuple[str, ...]
    citation_keys: tuple[str, ...]
    legal_citations: tuple[str, ...]
    required_conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    required_act: str | None
    authority_refs: tuple[AuthorityProvenance, ...]
    admission: EvidenceAdmission
    confidence: float | None
    classification: DisclosureClassification
    labels: Mapping[str, str] = field(default_factory=dict)
    normalized_value: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(ObligationKind, self.kind, "kind")
        )
        spans = _tuple_of_str(self.source_span_ids, "source_span_ids", max_items=64)
        if not spans:
            raise ValueError("source_span_ids must be non-empty")
        object.__setattr__(self, "source_span_ids", spans)
        object.__setattr__(
            self,
            "source_field_id",
            _optional_identifier(self.source_field_id, "source_field_id"),
        )
        if not isinstance(self.surface_text, str):
            raise TypeError("surface_text must be str")
        surface = self.surface_text[:DEFAULT_MAX_SURFACE]
        object.__setattr__(self, "surface_text", surface)
        digest = self.text_digest or _text_digest(surface)
        object.__setattr__(
            self, "text_digest", _sha256_hex_field(digest, "text_digest")
        )
        object.__setattr__(
            self,
            "claim_tokens",
            _tuple_of_str(self.claim_tokens, "claim_tokens", max_items=256),
        )
        object.__setattr__(
            self,
            "citation_keys",
            _tuple_of_str(self.citation_keys, "citation_keys", max_items=64),
        )
        object.__setattr__(
            self,
            "legal_citations",
            _tuple_of_str(self.legal_citations, "legal_citations", max_items=64),
        )
        object.__setattr__(
            self,
            "required_conditions",
            _tuple_of_str(
                self.required_conditions, "required_conditions", max_items=64
            ),
        )
        object.__setattr__(
            self, "exceptions", _tuple_of_str(self.exceptions, "exceptions", max_items=32)
        )
        object.__setattr__(
            self,
            "required_act",
            _optional_str(self.required_act, "required_act", max_len=256),
        )
        refs = tuple(self.authority_refs or ())
        object.__setattr__(self, "authority_refs", refs)
        object.__setattr__(
            self,
            "admission",
            _coerce_enum(EvidenceAdmission, self.admission, "admission"),
        )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        cleaned, _ = sanitize_labels(dict(self.labels) if self.labels else {})
        object.__setattr__(self, "labels", cleaned)
        object.__setattr__(
            self,
            "normalized_value",
            _optional_str(self.normalized_value, "normalized_value", max_len=512),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission": self.admission.value
            if isinstance(self.admission, EvidenceAdmission)
            else str(self.admission),
            "authority_refs": [a.to_dict() for a in self.authority_refs],
            "citation_keys": list(self.citation_keys),
            "claim_tokens": list(self.claim_tokens),
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "confidence": self.confidence,
            "exceptions": list(self.exceptions),
            "kind": self.kind.value
            if isinstance(self.kind, ObligationKind)
            else str(self.kind),
            "labels": dict(self.labels),
            "legal_citations": list(self.legal_citations),
            "normalized_value": self.normalized_value,
            "obligation_id": self.obligation_id,
            "required_act": self.required_act,
            "required_conditions": list(self.required_conditions),
            "source_field_id": self.source_field_id,
            "source_span_ids": list(self.source_span_ids),
            "surface_text": self.surface_text,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AtomicObligation":
        if not isinstance(value, Mapping):
            raise TypeError("AtomicObligation must be a mapping")
        refs = tuple(
            AuthorityProvenance.from_dict(a)
            for a in (value.get("authority_refs") or ())
            if isinstance(a, Mapping)
        )
        return cls(
            obligation_id=str(value.get("obligation_id") or ""),
            kind=value.get("kind", ObligationKind.UNKNOWN.value),
            source_span_ids=tuple(value.get("source_span_ids") or ()),
            source_field_id=value.get("source_field_id"),
            surface_text=str(value.get("surface_text") or ""),
            text_digest=str(value.get("text_digest") or _text_digest(str(value.get("surface_text") or ""))),
            claim_tokens=tuple(value.get("claim_tokens") or ()),
            citation_keys=tuple(value.get("citation_keys") or ()),
            legal_citations=tuple(value.get("legal_citations") or ()),
            required_conditions=tuple(value.get("required_conditions") or ()),
            exceptions=tuple(value.get("exceptions") or ()),
            required_act=value.get("required_act"),
            authority_refs=refs,
            admission=value.get("admission", EvidenceAdmission.ADMITTED.value),
            confidence=value.get("confidence"),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_USER.value
            ),
            labels=value.get("labels") or {},
            normalized_value=value.get("normalized_value"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One submission evidence item available for binding."""

    evidence_id: str
    kind: ResponsiveEvidenceKind
    document_id: str | None
    anchor_ids: tuple[str, ...]
    surface_text: str
    text_digest: str
    claim_tokens: tuple[str, ...]
    citation_keys: tuple[str, ...]
    admission: EvidenceAdmission
    origin: EvidenceOrigin
    confidence: float | None
    content_sha256: str | None
    is_counter: bool
    labels: Mapping[str, str] = field(default_factory=dict)
    normalized_value: str | None = None
    model_similarity: float | None = None  # ranking only; never satisfaction

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(ResponsiveEvidenceKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "document_id", _optional_identifier(self.document_id, "document_id")
        )
        anchors = _tuple_of_str(self.anchor_ids, "anchor_ids", max_items=64)
        if not anchors:
            raise ValueError("anchor_ids must be non-empty")
        object.__setattr__(self, "anchor_ids", anchors)
        if not isinstance(self.surface_text, str):
            raise TypeError("surface_text must be str")
        surface = self.surface_text[:DEFAULT_MAX_SURFACE]
        object.__setattr__(self, "surface_text", surface)
        digest = self.text_digest or _text_digest(surface)
        object.__setattr__(
            self, "text_digest", _sha256_hex_field(digest, "text_digest")
        )
        object.__setattr__(
            self,
            "claim_tokens",
            _tuple_of_str(self.claim_tokens, "claim_tokens", max_items=256),
        )
        object.__setattr__(
            self,
            "citation_keys",
            _tuple_of_str(self.citation_keys, "citation_keys", max_items=64),
        )
        object.__setattr__(
            self,
            "admission",
            _coerce_enum(EvidenceAdmission, self.admission, "admission"),
        )
        object.__setattr__(
            self, "origin", _coerce_enum(EvidenceOrigin, self.origin, "origin")
        )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self,
            "content_sha256",
            _optional_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(self, "is_counter", bool(self.is_counter))
        cleaned, _ = sanitize_labels(dict(self.labels) if self.labels else {})
        object.__setattr__(self, "labels", cleaned)
        object.__setattr__(
            self,
            "normalized_value",
            _optional_str(self.normalized_value, "normalized_value", max_len=512),
        )
        object.__setattr__(
            self,
            "model_similarity",
            _optional_float_01(self.model_similarity, "model_similarity"),
        )
        # Model-origin items cannot be admitted without explicit admission.
        if (
            self.origin is EvidenceOrigin.MODEL
            and self.admission is EvidenceAdmission.ADMITTED
            and "admission_receipt_id" not in self.labels
        ):
            object.__setattr__(self, "admission", EvidenceAdmission.CANDIDATE)

    @property
    def is_admitted(self) -> bool:
        return self.admission is EvidenceAdmission.ADMITTED

    @property
    def is_model_origin(self) -> bool:
        return self.origin is EvidenceOrigin.MODEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "admission": self.admission.value
            if isinstance(self.admission, EvidenceAdmission)
            else str(self.admission),
            "anchor_ids": list(self.anchor_ids),
            "citation_keys": list(self.citation_keys),
            "claim_tokens": list(self.claim_tokens),
            "confidence": self.confidence,
            "content_sha256": self.content_sha256,
            "document_id": self.document_id,
            "evidence_id": self.evidence_id,
            "is_counter": self.is_counter,
            "kind": self.kind.value
            if isinstance(self.kind, ResponsiveEvidenceKind)
            else str(self.kind),
            "labels": dict(self.labels),
            "model_similarity": self.model_similarity,
            "normalized_value": self.normalized_value,
            "origin": self.origin.value
            if isinstance(self.origin, EvidenceOrigin)
            else str(self.origin),
            "surface_text": self.surface_text,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceItem":
        if not isinstance(value, Mapping):
            raise TypeError("EvidenceItem must be a mapping")
        return cls(
            evidence_id=str(value.get("evidence_id") or ""),
            kind=value.get("kind", ResponsiveEvidenceKind.UNKNOWN.value),
            document_id=value.get("document_id"),
            anchor_ids=tuple(value.get("anchor_ids") or ()),
            surface_text=str(value.get("surface_text") or ""),
            text_digest=str(
                value.get("text_digest")
                or _text_digest(str(value.get("surface_text") or ""))
            ),
            claim_tokens=tuple(value.get("claim_tokens") or ()),
            citation_keys=tuple(value.get("citation_keys") or ()),
            admission=value.get("admission", EvidenceAdmission.CANDIDATE.value),
            origin=value.get("origin", EvidenceOrigin.OTHER.value),
            confidence=value.get("confidence"),
            content_sha256=value.get("content_sha256"),
            is_counter=bool(value.get("is_counter", False)),
            labels=value.get("labels") or {},
            normalized_value=value.get("normalized_value"),
            model_similarity=value.get("model_similarity"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    """Exact binding of one evidence item to one obligation."""

    binding_id: str
    obligation_id: str
    evidence_id: str
    role: BindingRole
    kind_compatible: bool
    claim_overlap: tuple[str, ...]
    citation_overlap: tuple[str, ...]
    similarity_score: float | None  # ranking only
    establishes_satisfaction: bool
    reason_codes: tuple[str, ...]
    evidence_admission: EvidenceAdmission
    evidence_origin: EvidenceOrigin
    content_sha256: str | None
    anchor_ids: tuple[str, ...]
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "binding_id", _identifier(self.binding_id, "binding_id")
        )
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "role", _coerce_enum(BindingRole, self.role, "role")
        )
        object.__setattr__(self, "kind_compatible", bool(self.kind_compatible))
        object.__setattr__(
            self,
            "claim_overlap",
            _tuple_of_str(self.claim_overlap, "claim_overlap", max_items=64),
        )
        object.__setattr__(
            self,
            "citation_overlap",
            _tuple_of_str(self.citation_overlap, "citation_overlap", max_items=64),
        )
        object.__setattr__(
            self,
            "similarity_score",
            _optional_float_01(self.similarity_score, "similarity_score"),
        )
        object.__setattr__(
            self, "establishes_satisfaction", bool(self.establishes_satisfaction)
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self,
            "evidence_admission",
            _coerce_enum(
                EvidenceAdmission, self.evidence_admission, "evidence_admission"
            ),
        )
        object.__setattr__(
            self,
            "evidence_origin",
            _coerce_enum(EvidenceOrigin, self.evidence_origin, "evidence_origin"),
        )
        object.__setattr__(
            self,
            "content_sha256",
            _optional_sha256(self.content_sha256, "content_sha256"),
        )
        object.__setattr__(
            self,
            "anchor_ids",
            _tuple_of_str(self.anchor_ids, "anchor_ids", max_items=64),
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_ids": list(self.anchor_ids),
            "binding_id": self.binding_id,
            "citation_overlap": list(self.citation_overlap),
            "claim_overlap": list(self.claim_overlap),
            "content_sha256": self.content_sha256,
            "establishes_satisfaction": self.establishes_satisfaction,
            "evidence_admission": self.evidence_admission.value
            if isinstance(self.evidence_admission, EvidenceAdmission)
            else str(self.evidence_admission),
            "evidence_id": self.evidence_id,
            "evidence_origin": self.evidence_origin.value
            if isinstance(self.evidence_origin, EvidenceOrigin)
            else str(self.evidence_origin),
            "kind_compatible": self.kind_compatible,
            "labels": dict(self.labels),
            "obligation_id": self.obligation_id,
            "reason_codes": list(self.reason_codes),
            "role": self.role.value
            if isinstance(self.role, BindingRole)
            else str(self.role),
            "similarity_score": self.similarity_score,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceBinding":
        if not isinstance(value, Mapping):
            raise TypeError("EvidenceBinding must be a mapping")
        return cls(
            binding_id=str(value.get("binding_id") or ""),
            obligation_id=str(value.get("obligation_id") or ""),
            evidence_id=str(value.get("evidence_id") or ""),
            role=value.get("role", BindingRole.UNRELATED.value),
            kind_compatible=bool(value.get("kind_compatible", False)),
            claim_overlap=tuple(value.get("claim_overlap") or ()),
            citation_overlap=tuple(value.get("citation_overlap") or ()),
            similarity_score=value.get("similarity_score"),
            establishes_satisfaction=bool(
                value.get("establishes_satisfaction", False)
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            evidence_admission=value.get(
                "evidence_admission", EvidenceAdmission.CANDIDATE.value
            ),
            evidence_origin=value.get(
                "evidence_origin", EvidenceOrigin.OTHER.value
            ),
            content_sha256=value.get("content_sha256"),
            anchor_ids=tuple(value.get("anchor_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ObligationComplianceResult:
    """Per-obligation binding result with full provenance legs."""

    schema_version: str
    result_id: str
    obligation: AtomicObligation
    status: SatisfactionStatus
    bindings: tuple[EvidenceBinding, ...]
    support_evidence_ids: tuple[str, ...]
    counter_evidence_ids: tuple[str, ...]
    ranked_candidate_ids: tuple[str, ...]
    authority_provenance: tuple[AuthorityProvenance, ...]
    proof_provenance: ProofProvenance | None
    rule_receipts: tuple[DeterministicRuleReceipt, ...]
    conditions_met: tuple[str, ...]
    conditions_unmet: tuple[str, ...]
    exceptions_applied: tuple[str, ...]
    reason_codes: tuple[str, ...]
    human_review: HumanReviewBoundary
    confidence: float | None
    is_pass: bool
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SEMANTIC_COMPLIANCE_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {SEMANTIC_COMPLIANCE_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "result_id", _identifier(self.result_id, "result_id")
        )
        if not isinstance(self.obligation, AtomicObligation):
            raise TypeError("obligation must be AtomicObligation")
        object.__setattr__(
            self, "status", _coerce_enum(SatisfactionStatus, self.status, "status")
        )
        object.__setattr__(self, "bindings", tuple(self.bindings or ()))
        object.__setattr__(
            self,
            "support_evidence_ids",
            _tuple_of_str(
                self.support_evidence_ids, "support_evidence_ids", max_items=128
            ),
        )
        object.__setattr__(
            self,
            "counter_evidence_ids",
            _tuple_of_str(
                self.counter_evidence_ids, "counter_evidence_ids", max_items=128
            ),
        )
        object.__setattr__(
            self,
            "ranked_candidate_ids",
            _tuple_of_str(
                self.ranked_candidate_ids, "ranked_candidate_ids", max_items=128
            ),
        )
        object.__setattr__(
            self, "authority_provenance", tuple(self.authority_provenance or ())
        )
        object.__setattr__(self, "rule_receipts", tuple(self.rule_receipts or ()))
        object.__setattr__(
            self,
            "conditions_met",
            _tuple_of_str(self.conditions_met, "conditions_met", max_items=64),
        )
        object.__setattr__(
            self,
            "conditions_unmet",
            _tuple_of_str(self.conditions_unmet, "conditions_unmet", max_items=64),
        )
        object.__setattr__(
            self,
            "exceptions_applied",
            _tuple_of_str(
                self.exceptions_applied, "exceptions_applied", max_items=32
            ),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=128),
        )
        if not isinstance(self.human_review, HumanReviewBoundary):
            raise TypeError("human_review must be HumanReviewBoundary")
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        # Fail closed: only explicit satisfied + is_pass.
        pass_ok = (
            self.status is SatisfactionStatus.SATISFIED and bool(self.is_pass)
        )
        object.__setattr__(self, "is_pass", pass_ok)
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))

    @property
    def has_obligation_provenance(self) -> bool:
        return bool(self.obligation.obligation_id and self.obligation.source_span_ids)

    @property
    def has_evidence_provenance(self) -> bool:
        return bool(self.support_evidence_ids or self.counter_evidence_ids or self.bindings)

    @property
    def has_authority_provenance(self) -> bool:
        return bool(self.authority_provenance)

    @property
    def has_proof_provenance(self) -> bool:
        return self.proof_provenance is not None or bool(self.rule_receipts)

    @property
    def provenance_complete(self) -> bool:
        """All four legs present (authority may be explicit missing record)."""
        return (
            self.has_obligation_provenance
            and self.has_evidence_provenance
            and self.has_authority_provenance
            and self.has_proof_provenance
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_provenance": [a.to_dict() for a in self.authority_provenance],
            "bindings": [b.to_dict() for b in self.bindings],
            "conditions_met": list(self.conditions_met),
            "conditions_unmet": list(self.conditions_unmet),
            "confidence": self.confidence,
            "counter_evidence_ids": list(self.counter_evidence_ids),
            "exceptions_applied": list(self.exceptions_applied),
            "has_authority_provenance": self.has_authority_provenance,
            "has_evidence_provenance": self.has_evidence_provenance,
            "has_obligation_provenance": self.has_obligation_provenance,
            "has_proof_provenance": self.has_proof_provenance,
            "human_review": self.human_review.to_dict(),
            "is_pass": self.is_pass,
            "labels": dict(self.labels),
            "obligation": self.obligation.to_dict(),
            "proof_provenance": (
                self.proof_provenance.to_dict() if self.proof_provenance else None
            ),
            "provenance_complete": self.provenance_complete,
            "ranked_candidate_ids": list(self.ranked_candidate_ids),
            "reason_codes": list(self.reason_codes),
            "result_id": self.result_id,
            "rule_receipts": [r.to_dict() for r in self.rule_receipts],
            "schema_version": self.schema_version,
            "status": self.status.value
            if isinstance(self.status, SatisfactionStatus)
            else str(self.status),
            "support_evidence_ids": list(self.support_evidence_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObligationComplianceResult":
        if not isinstance(value, Mapping):
            raise TypeError("ObligationComplianceResult must be a mapping")
        proof_raw = value.get("proof_provenance")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTIC_COMPLIANCE_SCHEMA_VERSION
            ),
            result_id=str(value.get("result_id") or ""),
            obligation=AtomicObligation.from_dict(value.get("obligation") or {}),
            status=value.get("status", SatisfactionStatus.UNKNOWN.value),
            bindings=tuple(
                EvidenceBinding.from_dict(b)
                for b in (value.get("bindings") or ())
                if isinstance(b, Mapping)
            ),
            support_evidence_ids=tuple(value.get("support_evidence_ids") or ()),
            counter_evidence_ids=tuple(value.get("counter_evidence_ids") or ()),
            ranked_candidate_ids=tuple(value.get("ranked_candidate_ids") or ()),
            authority_provenance=tuple(
                AuthorityProvenance.from_dict(a)
                for a in (value.get("authority_provenance") or ())
                if isinstance(a, Mapping)
            ),
            proof_provenance=(
                ProofProvenance.from_dict(proof_raw)
                if isinstance(proof_raw, Mapping)
                else None
            ),
            rule_receipts=tuple(
                DeterministicRuleReceipt.from_dict(r)
                for r in (value.get("rule_receipts") or ())
                if isinstance(r, Mapping)
            ),
            conditions_met=tuple(value.get("conditions_met") or ()),
            conditions_unmet=tuple(value.get("conditions_unmet") or ()),
            exceptions_applied=tuple(value.get("exceptions_applied") or ()),
            reason_codes=tuple(value.get("reason_codes") or ()),
            human_review=HumanReviewBoundary.from_dict(
                value.get("human_review") or {}
            ),
            confidence=value.get("confidence"),
            is_pass=bool(value.get("is_pass", False)),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class SemanticComplianceInput:
    """Input: obligations + evidence (+ optional condition satisfaction map)."""

    analysis_id: str | None
    matter_id: str | None
    office_action_artifact_id: str | None
    package_id: str | None
    obligations: tuple[AtomicObligation, ...]
    evidence: tuple[EvidenceItem, ...]
    condition_facts: Mapping[str, bool]
    classification: DisclosureClassification
    run_proofs: bool
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "analysis_id",
            _optional_identifier(self.analysis_id, "analysis_id"),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "office_action_artifact_id",
            _optional_identifier(
                self.office_action_artifact_id, "office_action_artifact_id"
            ),
        )
        object.__setattr__(
            self, "package_id", _optional_identifier(self.package_id, "package_id")
        )
        object.__setattr__(self, "obligations", tuple(self.obligations or ()))
        object.__setattr__(self, "evidence", tuple(self.evidence or ()))
        facts: dict[str, bool] = {}
        if self.condition_facts:
            if not isinstance(self.condition_facts, Mapping):
                raise TypeError("condition_facts must be a mapping")
            for k, v in self.condition_facts.items():
                key = str(k).strip()
                if key:
                    facts[key] = bool(v)
        object.__setattr__(self, "condition_facts", MappingProxyType(facts))
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(self, "run_proofs", bool(self.run_proofs))
        cleaned, _ = sanitize_labels(dict(self.labels) if self.labels else {})
        object.__setattr__(self, "labels", cleaned)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "condition_facts": dict(self.condition_facts),
            "evidence": [e.to_dict() for e in self.evidence],
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "obligations": [o.to_dict() for o in self.obligations],
            "office_action_artifact_id": self.office_action_artifact_id,
            "package_id": self.package_id,
            "run_proofs": self.run_proofs,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticComplianceInput":
        if not isinstance(value, Mapping):
            raise TypeError("SemanticComplianceInput must be a mapping")
        return cls(
            analysis_id=value.get("analysis_id"),
            matter_id=value.get("matter_id"),
            office_action_artifact_id=value.get("office_action_artifact_id"),
            package_id=value.get("package_id"),
            obligations=tuple(
                AtomicObligation.from_dict(o)
                for o in (value.get("obligations") or ())
                if isinstance(o, Mapping)
            ),
            evidence=tuple(
                EvidenceItem.from_dict(e)
                for e in (value.get("evidence") or ())
                if isinstance(e, Mapping)
            ),
            condition_facts=value.get("condition_facts") or {},
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_USER.value
            ),
            run_proofs=bool(value.get("run_proofs", True)),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class SemanticComplianceResult:
    """Package-level obligation binding / compliance result."""

    schema_version: str
    analysis_id: str
    matter_id: str | None
    office_action_artifact_id: str | None
    package_id: str | None
    disposition: ComplianceDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    output_kind: str
    disclaimer: str
    is_final_legal_determination: bool
    is_model_summary_substitution: bool
    is_pass: bool
    overall_pass: bool
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    results: tuple[ObligationComplianceResult, ...]
    satisfied_count: int
    unsatisfied_count: int
    incomplete_count: int
    unknown_count: int
    fail_count: int
    ruleset_versions: Mapping[str, str]
    documented_rules: tuple[str, ...]
    labels: Mapping[str, str]
    text_digest: str
    human_review: HumanReviewBoundary

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != SEMANTIC_COMPLIANCE_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {SEMANTIC_COMPLIANCE_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "analysis_id", _identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "office_action_artifact_id",
            _optional_identifier(
                self.office_action_artifact_id, "office_action_artifact_id"
            ),
        )
        object.__setattr__(
            self, "package_id", _optional_identifier(self.package_id, "package_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(ComplianceDisposition, self.disposition, "disposition"),
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
            self, "disclaimer", _require_str(self.disclaimer, "disclaimer", max_len=2048)
        )
        object.__setattr__(self, "is_final_legal_determination", False)
        object.__setattr__(self, "is_model_summary_substitution", False)
        object.__setattr__(self, "is_pass", bool(self.is_pass))
        object.__setattr__(self, "overall_pass", bool(self.overall_pass) and bool(self.is_pass))
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=256),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=128)
        )
        object.__setattr__(self, "results", tuple(self.results or ()))
        object.__setattr__(
            self, "satisfied_count", _nonneg_int(self.satisfied_count, "satisfied_count")
        )
        object.__setattr__(
            self,
            "unsatisfied_count",
            _nonneg_int(self.unsatisfied_count, "unsatisfied_count"),
        )
        object.__setattr__(
            self,
            "incomplete_count",
            _nonneg_int(self.incomplete_count, "incomplete_count"),
        )
        object.__setattr__(
            self, "unknown_count", _nonneg_int(self.unknown_count, "unknown_count")
        )
        object.__setattr__(
            self, "fail_count", _nonneg_int(self.fail_count, "fail_count")
        )
        if isinstance(self.ruleset_versions, Mapping):
            object.__setattr__(
                self,
                "ruleset_versions",
                MappingProxyType({str(k): str(v) for k, v in self.ruleset_versions.items()}),
            )
        else:
            object.__setattr__(self, "ruleset_versions", MappingProxyType({}))
        object.__setattr__(
            self,
            "documented_rules",
            _tuple_of_str(self.documented_rules, "documented_rules", max_items=64),
        )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels, "labels"))
        object.__setattr__(
            self, "text_digest", _sha256_hex_field(self.text_digest, "text_digest")
        )
        if not isinstance(self.human_review, HumanReviewBoundary):
            raise TypeError("human_review must be HumanReviewBoundary")

    def public_projection(self) -> dict[str, Any]:
        """Redacted projection without obligation/evidence body text."""
        return {
            "analysis_id": self.analysis_id,
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value
            if isinstance(self.disposition, ComplianceDisposition)
            else str(self.disposition),
            "documented_rules": list(self.documented_rules),
            "fail_count": self.fail_count,
            "incomplete_count": self.incomplete_count,
            "is_final_legal_determination": False,
            "is_model_summary_substitution": False,
            "is_pass": self.is_pass,
            "matter_id": self.matter_id,
            "office_action_artifact_id": self.office_action_artifact_id,
            "output_kind": self.output_kind,
            "overall_pass": self.overall_pass,
            "package_id": self.package_id,
            "reason_codes": list(self.reason_codes),
            "result_ids": [r.result_id for r in self.results],
            "result_statuses": [
                r.status.value if isinstance(r.status, SatisfactionStatus) else str(r.status)
                for r in self.results
            ],
            "review_state": self.review_state.value
            if isinstance(self.review_state, ReviewState)
            else str(self.review_state),
            "ruleset_versions": dict(self.ruleset_versions),
            "satisfied_count": self.satisfied_count,
            "schema_version": self.schema_version,
            "text_digest": self.text_digest,
            "unknown_count": self.unknown_count,
            "unsatisfied_count": self.unsatisfied_count,
            "warnings": list(self.warnings),
            "human_review": self.human_review.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value
            if isinstance(self.disposition, ComplianceDisposition)
            else str(self.disposition),
            "documented_rules": list(self.documented_rules),
            "fail_count": self.fail_count,
            "human_review": self.human_review.to_dict(),
            "incomplete_count": self.incomplete_count,
            "is_final_legal_determination": False,
            "is_model_summary_substitution": False,
            "is_pass": self.is_pass,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "office_action_artifact_id": self.office_action_artifact_id,
            "output_kind": self.output_kind,
            "overall_pass": self.overall_pass,
            "package_id": self.package_id,
            "reason_codes": list(self.reason_codes),
            "results": [r.to_dict() for r in self.results],
            "review_state": self.review_state.value
            if isinstance(self.review_state, ReviewState)
            else str(self.review_state),
            "ruleset_versions": dict(self.ruleset_versions),
            "satisfied_count": self.satisfied_count,
            "schema_version": self.schema_version,
            "text_digest": self.text_digest,
            "unknown_count": self.unknown_count,
            "unsatisfied_count": self.unsatisfied_count,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticComplianceResult":
        if not isinstance(value, Mapping):
            raise TypeError("SemanticComplianceResult must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", SEMANTIC_COMPLIANCE_SCHEMA_VERSION
            ),
            analysis_id=str(value.get("analysis_id") or ""),
            matter_id=value.get("matter_id"),
            office_action_artifact_id=value.get("office_action_artifact_id"),
            package_id=value.get("package_id"),
            disposition=value.get(
                "disposition", ComplianceDisposition.UNKNOWN.value
            ),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            classification=value.get(
                "classification", DisclosureClassification.PUBLIC_USER.value
            ),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_SEMANTIC_COMPLIANCE
            ),
            disclaimer=str(
                value.get("disclaimer") or NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER
            ),
            is_final_legal_determination=False,
            is_model_summary_substitution=False,
            is_pass=bool(value.get("is_pass", False)),
            overall_pass=bool(value.get("overall_pass", False)),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            results=tuple(
                ObligationComplianceResult.from_dict(r)
                for r in (value.get("results") or ())
                if isinstance(r, Mapping)
            ),
            satisfied_count=int(value.get("satisfied_count") or 0),
            unsatisfied_count=int(value.get("unsatisfied_count") or 0),
            incomplete_count=int(value.get("incomplete_count") or 0),
            unknown_count=int(value.get("unknown_count") or 0),
            fail_count=int(value.get("fail_count") or 0),
            ruleset_versions=value.get("ruleset_versions") or {},
            documented_rules=tuple(value.get("documented_rules") or ()),
            labels=value.get("labels") or {},
            text_digest=str(value.get("text_digest") or sha256_hex("")),
            human_review=HumanReviewBoundary.from_dict(
                value.get("human_review") or {}
            ),
        )


# ---------------------------------------------------------------------------
# Normalization from v2 semantics
# ---------------------------------------------------------------------------


def obligation_from_oa_field(
    field: Any,
    *,
    obligation_id: str | None = None,
    authority_refs: Sequence[AuthorityProvenance] = (),
    required_conditions: Sequence[str] = (),
    exceptions: Sequence[str] = (),
    required_act: str | None = None,
) -> AtomicObligation:
    """Normalize an office-action SemanticField into an AtomicObligation."""
    if SemanticField is not None and not isinstance(field, SemanticField):
        if not isinstance(field, Mapping):
            raise TypeError("field must be SemanticField or mapping")
        # Minimal mapping path.
        kind_raw = field.get("kind", "other")
        kind = map_oa_field_kind(kind_raw)
        admission_raw = str(field.get("admission") or "admitted")
        admission = (
            EvidenceAdmission.ADMITTED
            if admission_raw == "admitted"
            else EvidenceAdmission.CANDIDATE
            if admission_raw == "candidate"
            else EvidenceAdmission.REVIEW_REQUIRED
        )
        surface = str(field.get("surface_text") or "")
        return AtomicObligation(
            obligation_id=obligation_id or str(field.get("field_id") or f"obl:{uuid.uuid4().hex[:10]}"),
            kind=kind,
            source_span_ids=tuple(field.get("source_span_ids") or ("span:unknown",)),
            source_field_id=field.get("field_id"),
            surface_text=surface,
            text_digest=str(field.get("text_digest") or _text_digest(surface)),
            claim_tokens=tuple(field.get("claim_tokens") or ()),
            citation_keys=tuple(field.get("citation_keys") or ()),
            legal_citations=tuple(field.get("citation_keys") or ()),
            required_conditions=tuple(required_conditions),
            exceptions=tuple(exceptions),
            required_act=required_act,
            authority_refs=tuple(authority_refs),
            admission=admission,
            confidence=field.get("confidence"),
            classification=field.get(
                "classification", DisclosureClassification.PUBLIC_USER.value
            ),
            labels=field.get("labels") or {},
            normalized_value=field.get("normalized_value"),
        )

    kind = map_oa_field_kind(getattr(field, "kind", "other"))
    admission_state = getattr(field, "admission", None)
    admission_val = (
        admission_state.value
        if hasattr(admission_state, "value")
        else str(admission_state or "admitted")
    )
    if admission_val == "admitted":
        admission = EvidenceAdmission.ADMITTED
    elif admission_val == "candidate":
        admission = EvidenceAdmission.CANDIDATE
    elif admission_val == "rejected":
        admission = EvidenceAdmission.REJECTED
    else:
        admission = EvidenceAdmission.REVIEW_REQUIRED

    surface = str(getattr(field, "surface_text", "") or "")
    return AtomicObligation(
        obligation_id=obligation_id
        or str(getattr(field, "field_id", None) or f"obl:{uuid.uuid4().hex[:10]}"),
        kind=kind,
        source_span_ids=tuple(getattr(field, "source_span_ids", ()) or ("span:unknown",)),
        source_field_id=getattr(field, "field_id", None),
        surface_text=surface,
        text_digest=str(getattr(field, "text_digest", None) or _text_digest(surface)),
        claim_tokens=tuple(getattr(field, "claim_tokens", ()) or ()),
        citation_keys=tuple(getattr(field, "citation_keys", ()) or ()),
        legal_citations=tuple(getattr(field, "citation_keys", ()) or ()),
        required_conditions=tuple(required_conditions),
        exceptions=tuple(exceptions),
        required_act=required_act,
        authority_refs=tuple(authority_refs),
        admission=admission,
        confidence=getattr(field, "confidence", None),
        classification=DisclosureClassification.PUBLIC_USER,
        labels=dict(getattr(field, "labels", {}) or {}),
        normalized_value=getattr(field, "normalized_value", None),
    )


def evidence_from_normalized_fact(
    fact: Any,
    *,
    evidence_id: str | None = None,
    is_counter: bool = False,
    content_sha256: str | None = None,
    model_similarity: float | None = None,
) -> EvidenceItem:
    """Normalize a package NormalizedFact into an EvidenceItem."""
    if NormalizedFact is not None and not isinstance(fact, NormalizedFact):
        if not isinstance(fact, Mapping):
            raise TypeError("fact must be NormalizedFact or mapping")
        kind = map_pkg_fact_kind(fact.get("kind", "other"))
        admission_raw = str(fact.get("admission") or "candidate")
        if admission_raw == "admitted":
            admission = EvidenceAdmission.ADMITTED
        elif admission_raw == "rejected":
            admission = EvidenceAdmission.REJECTED
        elif admission_raw == "review_required":
            admission = EvidenceAdmission.REVIEW_REQUIRED
        else:
            admission = EvidenceAdmission.CANDIDATE
        origin_raw = str(fact.get("origin") or "other")
        origin = (
            EvidenceOrigin.MODEL
            if origin_raw == "model"
            else EvidenceOrigin.DETERMINISTIC_RULE
            if origin_raw == "deterministic_rule"
            else EvidenceOrigin.OTHER
        )
        surface = str(fact.get("surface_text") or "")
        labels = dict(fact.get("labels") or {})
        if fact.get("admission_receipt_id"):
            labels["admission_receipt_id"] = str(fact["admission_receipt_id"])
        return EvidenceItem(
            evidence_id=evidence_id or str(fact.get("fact_id") or f"ev:{uuid.uuid4().hex[:10]}"),
            kind=kind,
            document_id=fact.get("document_id"),
            anchor_ids=tuple(fact.get("anchor_ids") or ("anchor:unknown",)),
            surface_text=surface,
            text_digest=str(fact.get("text_digest") or _text_digest(surface)),
            claim_tokens=tuple(fact.get("claim_tokens") or ()),
            citation_keys=tuple(fact.get("citation_keys") or ()),
            admission=admission,
            origin=origin,
            confidence=fact.get("confidence"),
            content_sha256=content_sha256 or fact.get("content_sha256"),
            is_counter=is_counter,
            labels=labels,
            normalized_value=fact.get("normalized_value"),
            model_similarity=model_similarity,
        )

    kind = map_pkg_fact_kind(getattr(fact, "kind", "other"))
    admission_state = getattr(fact, "admission", None)
    admission_val = (
        admission_state.value
        if hasattr(admission_state, "value")
        else str(admission_state or "candidate")
    )
    if admission_val == "admitted":
        admission = EvidenceAdmission.ADMITTED
    elif admission_val == "rejected":
        admission = EvidenceAdmission.REJECTED
    elif admission_val == "review_required":
        admission = EvidenceAdmission.REVIEW_REQUIRED
    else:
        admission = EvidenceAdmission.CANDIDATE

    origin_state = getattr(fact, "origin", None)
    origin_val = (
        origin_state.value
        if hasattr(origin_state, "value")
        else str(origin_state or "other")
    )
    if origin_val == "model":
        origin = EvidenceOrigin.MODEL
    elif origin_val == "deterministic_rule":
        origin = EvidenceOrigin.DETERMINISTIC_RULE
    else:
        origin = EvidenceOrigin.OTHER

    surface = str(getattr(fact, "surface_text", "") or "")
    labels = dict(getattr(fact, "labels", {}) or {})
    receipt = getattr(fact, "admission_receipt_id", None)
    if receipt:
        labels["admission_receipt_id"] = str(receipt)

    return EvidenceItem(
        evidence_id=evidence_id
        or str(getattr(fact, "fact_id", None) or f"ev:{uuid.uuid4().hex[:10]}"),
        kind=kind,
        document_id=getattr(fact, "document_id", None),
        anchor_ids=tuple(getattr(fact, "anchor_ids", ()) or ("anchor:unknown",)),
        surface_text=surface,
        text_digest=str(getattr(fact, "text_digest", None) or _text_digest(surface)),
        claim_tokens=tuple(getattr(fact, "claim_tokens", ()) or ()),
        citation_keys=tuple(getattr(fact, "citation_keys", ()) or ()),
        admission=admission,
        origin=origin,
        confidence=getattr(fact, "confidence", None),
        content_sha256=content_sha256,
        is_counter=is_counter,
        labels=labels,
        normalized_value=getattr(fact, "normalized_value", None),
        model_similarity=model_similarity,
    )


# ---------------------------------------------------------------------------
# Matching / binding
# ---------------------------------------------------------------------------


def claim_overlap(
    obligation: AtomicObligation, evidence: EvidenceItem
) -> tuple[str, ...]:
    obl = {c.strip() for c in obligation.claim_tokens if c and str(c).strip()}
    ev = {c.strip() for c in evidence.claim_tokens if c and str(c).strip()}
    if not obl or not ev:
        return ()
    return tuple(sorted(obl & ev))


def citation_overlap(
    obligation: AtomicObligation, evidence: EvidenceItem
) -> tuple[str, ...]:
    obl = {c.strip().lower() for c in obligation.citation_keys if c}
    obl |= {c.strip().lower() for c in obligation.legal_citations if c}
    ev = {c.strip().lower() for c in evidence.citation_keys if c}
    if not obl or not ev:
        return ()
    return tuple(sorted(obl & ev))


def kind_is_compatible(
    obligation: AtomicObligation, evidence: EvidenceItem
) -> bool:
    allowed = responsive_kinds_for(obligation.kind)
    if not allowed:
        return False
    kind_val = (
        evidence.kind.value
        if isinstance(evidence.kind, ResponsiveEvidenceKind)
        else str(evidence.kind)
    )
    return kind_val in allowed


def rank_similarity(
    obligation: AtomicObligation, evidence: EvidenceItem
) -> float:
    """Token Jaccard for ranking only; never used alone for satisfaction."""
    if evidence.model_similarity is not None:
        # Blend model score with surface tokens; still ranking-only.
        surface = jaccard_similarity(
            tokenize_surface(obligation.surface_text),
            tokenize_surface(evidence.surface_text),
        )
        return max(0.0, min(1.0, 0.5 * evidence.model_similarity + 0.5 * surface))
    return jaccard_similarity(
        tokenize_surface(obligation.surface_text),
        tokenize_surface(evidence.surface_text),
    )


def evaluate_conditions(
    required: Sequence[str],
    condition_facts: Mapping[str, bool],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    met: list[str] = []
    unmet: list[str] = []
    for cond in required:
        key = str(cond).strip()
        if not key:
            continue
        if condition_facts.get(key) is True:
            met.append(key)
        else:
            unmet.append(key)
    return tuple(met), tuple(unmet)


def bind_evidence_to_obligation(
    *,
    obligation: AtomicObligation,
    evidence_items: Sequence[EvidenceItem],
    id_factory: Callable[[], str],
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_bindings: int = DEFAULT_MAX_BINDINGS,
) -> tuple[EvidenceBinding, ...]:
    """Score and bind evidence; mark unrelated remarks; rank model candidates."""
    scored: list[tuple[float, EvidenceItem, EvidenceBinding]] = []
    seq = 0
    for item in evidence_items:
        seq += 1
        if seq > max_candidates * 4:
            break
        compatible = kind_is_compatible(obligation, item)
        c_overlap = claim_overlap(obligation, item)
        cit_overlap = citation_overlap(obligation, item)
        sim = rank_similarity(obligation, item)
        reasons: list[str] = []

        if compatible:
            reasons.append(SemanticComplianceReasonCode.KIND_COMPATIBLE.value)
        else:
            reasons.append(SemanticComplianceReasonCode.KIND_INCOMPATIBLE.value)

        if c_overlap:
            reasons.append(SemanticComplianceReasonCode.CLAIM_OVERLAP.value)
        else:
            reasons.append(SemanticComplianceReasonCode.CLAIM_NO_OVERLAP.value)

        if cit_overlap:
            reasons.append(SemanticComplianceReasonCode.CITATION_OVERLAP.value)
        else:
            reasons.append(SemanticComplianceReasonCode.CITATION_NO_OVERLAP.value)

        if item.is_admitted:
            reasons.append(SemanticComplianceReasonCode.EVIDENCE_ADMITTED.value)
        else:
            reasons.append(SemanticComplianceReasonCode.EVIDENCE_CANDIDATE_ONLY.value)

        needs_overlap = requires_claim_or_citation_overlap(obligation.kind)
        has_overlap = bool(c_overlap or cit_overlap)

        # Determine role and whether binding can establish satisfaction.
        establishes = False
        if item.is_counter:
            role = BindingRole.COUNTER
            reasons.append(SemanticComplianceReasonCode.EVIDENCE_COUNTER.value)
        elif item.is_model_origin or item.admission is EvidenceAdmission.CANDIDATE:
            role = BindingRole.CANDIDATE_RANKED
            reasons.append(SemanticComplianceReasonCode.MODEL_SIMILARITY_RANKED.value)
            reasons.append(
                SemanticComplianceReasonCode.MODEL_SIMILARITY_NOT_SATISFACTION.value
            )
            if item.is_model_origin:
                reasons.append(
                    SemanticComplianceReasonCode.MODEL_ORIGIN_CANNOT_SATISFY.value
                )
        elif not compatible:
            role = BindingRole.UNRELATED
            reasons.append(
                SemanticComplianceReasonCode.CATEGORY_PRESENCE_NOT_SATISFACTION.value
            )
        elif needs_overlap and not has_overlap:
            # Unrelated remarks / non-responsive argument for a rejection.
            role = BindingRole.UNRELATED
            reasons.append(
                SemanticComplianceReasonCode.UNRELATED_REMARKS_REJECTED.value
            )
            reasons.append(
                SemanticComplianceReasonCode.CATEGORY_PRESENCE_NOT_SATISFACTION.value
            )
        elif compatible and item.is_admitted and (has_overlap or not needs_overlap):
            role = BindingRole.SUPPORT
            # Still require rule/proof at obligation level for establishes_satisfaction.
            establishes = True
        else:
            role = BindingRole.UNRELATED

        binding = EvidenceBinding(
            binding_id=f"bind:{id_factory()}",
            obligation_id=obligation.obligation_id,
            evidence_id=item.evidence_id,
            role=role,
            kind_compatible=compatible,
            claim_overlap=c_overlap,
            citation_overlap=cit_overlap,
            similarity_score=sim,
            establishes_satisfaction=establishes and not item.is_counter,
            reason_codes=tuple(dict.fromkeys(reasons)),
            evidence_admission=item.admission
            if isinstance(item.admission, EvidenceAdmission)
            else EvidenceAdmission(str(item.admission)),
            evidence_origin=item.origin
            if isinstance(item.origin, EvidenceOrigin)
            else EvidenceOrigin(str(item.origin)),
            content_sha256=item.content_sha256 or item.text_digest,
            anchor_ids=item.anchor_ids,
            labels={},
        )
        # Rank key: support first, then candidates by similarity, counters, unrelated last.
        rank_key = (
            0 if role is BindingRole.SUPPORT else
            1 if role is BindingRole.CANDIDATE_RANKED else
            2 if role is BindingRole.COUNTER else
            3
        )
        scored.append((rank_key - sim, item, binding))

    scored.sort(key=lambda t: t[0])
    bindings = [t[2] for t in scored[:max_bindings]]
    return tuple(bindings)


def _evaluate_rule_receipt(
    *,
    rule_key: str,
    preconditions: Mapping[str, bool],
    id_factory: Callable[[], str],
) -> DeterministicRuleReceipt | None:
    rule = documented_rule(rule_key)
    if rule is None:
        return None
    required = tuple(rule.get("preconditions") or ())
    met = tuple(p for p in required if preconditions.get(p))
    failed = tuple(p for p in required if not preconditions.get(p))
    applied = len(failed) == 0 and len(required) > 0
    return DeterministicRuleReceipt(
        receipt_id=f"rule:{id_factory()}",
        rule_id=str(rule["rule_id"]),
        rule_version=str(rule["rule_version"]),
        rule_digest=str(rule["rule_digest"]),
        applied=applied,
        preconditions_met=met,
        preconditions_failed=failed,
        labels={},
    )


def _run_obligation_proof(
    *,
    obligation: AtomicObligation,
    support_ids: Sequence[str],
    counter_ids: Sequence[str],
    id_factory: Callable[[], str],
    proof_executor: LegalIRProofExecutor | None,
    run_proofs: bool,
) -> ProofProvenance:
    """Execute privacy-safe proof; incomplete premises → unknown."""
    if not run_proofs:
        return ProofProvenance(
            receipt_id=f"proof:{id_factory()}",
            outcome=ProofOutcome.UNKNOWN.value,
            reason_codes=(SemanticComplianceReasonCode.PROOF_SKIPPED.value,),
            engine_id="skipped",
            engine_version=LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
            config_digest=None,
            problem_id=None,
            premise_ids=tuple(support_ids),
            statement_digest=sha256_hex(
                canonical_json(
                    {
                        "obligation_id": obligation.obligation_id,
                        "support": list(support_ids),
                    }
                )
            ),
            labels={"mode": "skipped"},
        )

    # Atom ids are bare evidence identifiers; required_premise_ids match atom_id.
    goal_atom = f"obl_satisfied:{obligation.obligation_id}"
    premises = tuple(
        AtomicLiteral(atom_id=str(eid), polarity=True) for eid in support_ids
    )
    # Counters appear as negative polarity premises for consistency detection.
    counter_lits = tuple(
        AtomicLiteral(atom_id=str(eid), polarity=False) for eid in counter_ids
    )
    all_premises = premises + counter_lits
    required = tuple(str(eid) for eid in support_ids)

    problem = ProofProblem(
        problem_id=f"prob:{obligation.obligation_id}",
        logic_family=LogicFamily.PROPOSITIONAL_ATOMS,
        goal=AtomicLiteral(atom_id=goal_atom, polarity=True)
        if support_ids
        else None,
        premises=all_premises
        + (
            (AtomicLiteral(atom_id=goal_atom, polarity=True),)
            if support_ids and not counter_ids
            else ()
        ),
        required_premise_ids=required,
        assumption_ids=(),
        counter_evidence_ids=tuple(counter_ids),
        premise_citations=tuple(
            PremiseCitation(
                premise_id=str(eid),
                kind="fact",
                digest=None,
                labels={},
            )
            for eid in support_ids
        ),
        classification=obligation.classification
        if isinstance(obligation.classification, DisclosureClassification)
        else DisclosureClassification.PUBLIC_USER,
        force_timeout=False,
        fixture_kind=None,
        labels={
            "obligation_kind": (
                obligation.kind.value
                if isinstance(obligation.kind, ObligationKind)
                else str(obligation.kind)
            )
        },
    )

    request = ProofExecutionRequest(
        request_id=f"req:{id_factory()}",
        problem=problem,
        classification=obligation.classification
        if isinstance(obligation.classification, DisclosureClassification)
        else DisclosureClassification.PUBLIC_USER,
        labels={"obligation_id": obligation.obligation_id},
    )

    try:
        if proof_executor is not None:
            result = proof_executor.execute(request)
        else:
            result = execute_legal_ir_proof(request)
        outcome = result.outcome
        conclusion = result.conclusion
        reasons = tuple(conclusion.reason_codes if conclusion else ())
        if outcome is ProofOutcome.PROVED:
            reasons = reasons + (SemanticComplianceReasonCode.PROOF_PROVED.value,)
        elif outcome is ProofOutcome.DISPROVED:
            reasons = reasons + (SemanticComplianceReasonCode.PROOF_DISPROVED.value,)
        elif outcome is ProofOutcome.TIMEOUT:
            reasons = reasons + (SemanticComplianceReasonCode.PROOF_TIMEOUT.value,)
        elif outcome is ProofOutcome.ERROR:
            reasons = reasons + (SemanticComplianceReasonCode.PROOF_ERROR.value,)
        else:
            reasons = reasons + (SemanticComplianceReasonCode.PROOF_UNKNOWN.value,)
        premise_ids = tuple(
            c.premise_id for c in (conclusion.premise_citations if conclusion else ())
        ) or tuple(support_ids)
        engine_cfg = getattr(result, "engine_config", None)
        return ProofProvenance(
            receipt_id=str(
                getattr(result, "receipt_id", None) or f"proof:{id_factory()}"
            ),
            outcome=outcome.value if isinstance(outcome, ProofOutcome) else str(outcome),
            reason_codes=tuple(dict.fromkeys(reasons)),
            engine_id=(
                engine_cfg.engine_id
                if engine_cfg is not None
                else "legal_ir_proof_executor"
            ),
            engine_version=(
                engine_cfg.engine_version
                if engine_cfg is not None
                else LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION
            ),
            config_digest=(
                engine_cfg.config_digest if engine_cfg is not None else None
            ),
            problem_id=problem.problem_id,
            premise_ids=premise_ids,
            statement_digest=sha256_hex(
                canonical_json(
                    {
                        "obligation_id": obligation.obligation_id,
                        "support": list(support_ids),
                        "counter": list(counter_ids),
                        "outcome": outcome.value
                        if isinstance(outcome, ProofOutcome)
                        else str(outcome),
                    }
                )
            ),
            labels={},
        )
    except Exception:
        return ProofProvenance(
            receipt_id=f"proof:{id_factory()}",
            outcome=ProofOutcome.ERROR.value,
            reason_codes=(SemanticComplianceReasonCode.PROOF_ERROR.value,),
            engine_id="legal_ir_proof_executor",
            engine_version=LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
            config_digest=None,
            problem_id=problem.problem_id,
            premise_ids=tuple(support_ids),
            statement_digest=sha256_hex(obligation.obligation_id),
            labels={"error": "execution_failed"},
        )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class SemanticComplianceProcessor:
    """Bind atomic obligations to exact submission evidence and proofs.

    Parameters
    ----------
    id_factory:
        Deterministic ID factory for tests.
    bounds:
        Safety bounds on output size.
    proof_executor:
        Optional shared Legal IR proof executor.
    """

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        bounds: AnalysisBounds | None = None,
        proof_executor: LegalIRProofExecutor | None = None,
    ) -> None:
        self._id_factory = id_factory or (
            lambda: f"sc:{uuid.uuid4().hex[:12]}"
        )
        self.bounds = bounds or AnalysisBounds()
        self.proof_executor = proof_executor

    def analyze(
        self,
        value: SemanticComplianceInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> SemanticComplianceResult:
        """Bind obligations to evidence and return fail-closed results."""
        inp = self._coerce_input(value, **kwargs)
        return self._analyze(inp)

    # Aliases
    def bind(
        self,
        value: SemanticComplianceInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> SemanticComplianceResult:
        return self.analyze(value, **kwargs)

    def verify(
        self,
        value: SemanticComplianceInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> SemanticComplianceResult:
        return self.analyze(value, **kwargs)

    def _coerce_input(
        self,
        value: Any,
        **kwargs: Any,
    ) -> SemanticComplianceInput:
        if value is None and not kwargs:
            raise SemanticComplianceError(
                "semantic compliance input is required", code="missing_input"
            )
        if isinstance(value, SemanticComplianceInput):
            return value
        if isinstance(value, Mapping):
            merged = dict(value)
            merged.update(kwargs)
            return SemanticComplianceInput.from_dict(merged)
        if kwargs:
            return SemanticComplianceInput.from_dict(kwargs)
        raise SemanticComplianceError(
            f"unsupported input type: {type(value).__name__}",
            code="invalid_input_type",
        )

    def _ruleset_versions(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "semantic_compliance": SEMANTIC_COMPLIANCE_RULESET_VERSION,
                "semantic_compliance_processor": SEMANTIC_COMPLIANCE_SCHEMA_VERSION,
                "parser": PARSER_VERSION,
                "contracts": CONTRACTS_SCHEMA_VERSION,
                "legal_ir_proof_executor": LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
                "office_action_semantics": str(OA_SEMANTICS_SCHEMA_VERSION),
                "submission_package_semantics": str(PKG_SEMANTICS_SCHEMA_VERSION),
            }
        )

    def _analyze(self, inp: SemanticComplianceInput) -> SemanticComplianceResult:
        analysis_id = inp.analysis_id or self._id_factory()
        reason_codes: list[str] = [
            SemanticComplianceReasonCode.NOT_FINAL_LEGAL_DETERMINATION.value,
            SemanticComplianceReasonCode.NO_MODEL_SUMMARY_SUBSTITUTION.value,
            SemanticComplianceReasonCode.HUMAN_REVIEW_BOUNDARY_EXPOSED.value,
        ]
        warnings: list[str] = []
        classification = inp.classification

        if requires_quarantine(classification):
            reason_codes.append(SemanticComplianceReasonCode.QUARANTINED.value)
            boundary = HumanReviewBoundary(
                requires_human_review=True,
                is_final_legal_determination=False,
                review_state=ReviewState.REQUIRED,
                boundary_reason="disclosure_quarantine",
                review_question=(
                    "Quarantine required; human review before any obligation binding."
                ),
                confidence=None,
                may_auto_pass=False,
            )
            return SemanticComplianceResult(
                schema_version=SEMANTIC_COMPLIANCE_SCHEMA_VERSION,
                analysis_id=analysis_id,
                matter_id=inp.matter_id,
                office_action_artifact_id=inp.office_action_artifact_id,
                package_id=inp.package_id,
                disposition=ComplianceDisposition.QUARANTINE,
                review_state=ReviewState.REQUIRED,
                classification=classification,
                output_kind=OUTPUT_KIND_SEMANTIC_COMPLIANCE,
                disclaimer=NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER,
                is_final_legal_determination=False,
                is_model_summary_substitution=False,
                is_pass=False,
                overall_pass=False,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                warnings=tuple(warnings),
                results=(),
                satisfied_count=0,
                unsatisfied_count=0,
                incomplete_count=0,
                unknown_count=0,
                fail_count=0,
                ruleset_versions=self._ruleset_versions(),
                documented_rules=list_documented_rules(),
                labels=dict(inp.labels),
                text_digest=sha256_hex(analysis_id),
                human_review=boundary,
            )

        if not inp.obligations:
            reason_codes.append(SemanticComplianceReasonCode.EMPTY_INPUT.value)
            boundary = HumanReviewBoundary(
                requires_human_review=True,
                is_final_legal_determination=False,
                review_state=ReviewState.PENDING,
                boundary_reason="empty_obligations",
                review_question="No obligations provided for semantic compliance binding.",
                confidence=None,
                may_auto_pass=False,
            )
            return SemanticComplianceResult(
                schema_version=SEMANTIC_COMPLIANCE_SCHEMA_VERSION,
                analysis_id=analysis_id,
                matter_id=inp.matter_id,
                office_action_artifact_id=inp.office_action_artifact_id,
                package_id=inp.package_id,
                disposition=ComplianceDisposition.EMPTY,
                review_state=ReviewState.PENDING,
                classification=classification,
                output_kind=OUTPUT_KIND_SEMANTIC_COMPLIANCE,
                disclaimer=NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER,
                is_final_legal_determination=False,
                is_model_summary_substitution=False,
                is_pass=False,
                overall_pass=False,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                warnings=tuple(warnings),
                results=(),
                satisfied_count=0,
                unsatisfied_count=0,
                incomplete_count=0,
                unknown_count=0,
                fail_count=0,
                ruleset_versions=self._ruleset_versions(),
                documented_rules=list_documented_rules(),
                labels=dict(inp.labels),
                text_digest=sha256_hex(analysis_id),
                human_review=boundary,
            )

        reason_codes.append(
            SemanticComplianceReasonCode.OBLIGATIONS_NORMALIZED.value
        )
        results: list[ObligationComplianceResult] = []
        for seq, obl in enumerate(inp.obligations, start=1):
            if seq > self.bounds.max_obligations:
                reason_codes.append(
                    SemanticComplianceReasonCode.OBLIGATION_LIMIT.value
                )
                warnings.append("obligation_limit")
                break
            results.append(
                self._bind_one(
                    analysis_id=analysis_id,
                    seq=seq,
                    obligation=obl,
                    evidence_items=inp.evidence,
                    condition_facts=inp.condition_facts,
                    run_proofs=inp.run_proofs,
                )
            )

        reason_codes.append(SemanticComplianceReasonCode.OBLIGATIONS_BOUND.value)
        reason_codes.append(SemanticComplianceReasonCode.RESULTS_EMITTED.value)

        satisfied = sum(
            1 for r in results if r.status is SatisfactionStatus.SATISFIED
        )
        unsatisfied = sum(
            1 for r in results if r.status is SatisfactionStatus.UNSATISFIED
        )
        incomplete = sum(
            1 for r in results if r.status is SatisfactionStatus.INCOMPLETE
        )
        unknown = sum(
            1 for r in results if r.status is SatisfactionStatus.UNKNOWN
        )
        fail = sum(
            1
            for r in results
            if r.status is SatisfactionStatus.FAIL
        )
        for r in results:
            reason_codes.extend(r.reason_codes)

        all_pass = (
            satisfied == len(results)
            and len(results) > 0
            and all(r.is_pass for r in results)
        )
        if all_pass:
            disposition = ComplianceDisposition.BOUND
            review_state = ReviewState.NOT_REQUIRED
            is_pass = True
            reason_codes.append(SemanticComplianceReasonCode.OVERALL_PASS.value)
        elif fail > 0 and satisfied == 0:
            disposition = ComplianceDisposition.FAILED
            review_state = ReviewState.REQUIRED
            is_pass = False
            reason_codes.append(
                SemanticComplianceReasonCode.OVERALL_FAIL_CLOSED.value
            )
        elif unsatisfied > 0 and satisfied == 0 and incomplete == 0 and unknown == 0:
            disposition = ComplianceDisposition.FAILED
            review_state = ReviewState.REQUIRED
            is_pass = False
            reason_codes.append(
                SemanticComplianceReasonCode.OVERALL_FAIL_CLOSED.value
            )
        elif incomplete > 0 and satisfied == 0:
            disposition = ComplianceDisposition.INCOMPLETE
            review_state = ReviewState.REQUIRED
            is_pass = False
            reason_codes.append(
                SemanticComplianceReasonCode.OVERALL_FAIL_CLOSED.value
            )
        elif satisfied > 0 and (unsatisfied + incomplete + unknown + fail) > 0:
            disposition = ComplianceDisposition.PARTIAL
            review_state = ReviewState.REQUIRED
            is_pass = False
            reason_codes.append(
                SemanticComplianceReasonCode.OVERALL_FAIL_CLOSED.value
            )
        elif unknown > 0:
            disposition = ComplianceDisposition.UNKNOWN
            review_state = ReviewState.REQUIRED
            is_pass = False
            reason_codes.append(
                SemanticComplianceReasonCode.OVERALL_FAIL_CLOSED.value
            )
        else:
            disposition = ComplianceDisposition.REVIEW
            review_state = ReviewState.REQUIRED
            is_pass = False
            reason_codes.append(
                SemanticComplianceReasonCode.OVERALL_FAIL_CLOSED.value
            )

        if not is_pass:
            reason_codes.append(
                SemanticComplianceReasonCode.HUMAN_REVIEW_REQUIRED.value
            )

        confidences = [r.confidence for r in results if r.confidence is not None]
        agg_conf = sum(confidences) / len(confidences) if confidences else None

        boundary = HumanReviewBoundary(
            requires_human_review=not is_pass,
            is_final_legal_determination=False,
            review_state=review_state,
            boundary_reason=(
                "all_obligations_satisfied_with_provenance"
                if is_pass
                else "obligation_binding_incomplete_or_failed"
            ),
            review_question=(
                "Optional review of bound obligation satisfaction before any "
                "legal conclusion; this module never issues a final legal determination."
                if is_pass
                else (
                    "Human review required: one or more obligations lack exact "
                    "responsive evidence, have contradictions, unmet conditions, "
                    "or incomplete proof provenance."
                )
            ),
            confidence=agg_conf,
            may_auto_pass=is_pass,
        )

        text_digest = sha256_hex(
            canonical_json(
                {
                    "analysis_id": analysis_id,
                    "result_ids": [r.result_id for r in results],
                    "statuses": [
                        r.status.value
                        if isinstance(r.status, SatisfactionStatus)
                        else str(r.status)
                        for r in results
                    ],
                    "is_pass": is_pass,
                }
            )
        )

        return SemanticComplianceResult(
            schema_version=SEMANTIC_COMPLIANCE_SCHEMA_VERSION,
            analysis_id=analysis_id,
            matter_id=inp.matter_id,
            office_action_artifact_id=inp.office_action_artifact_id,
            package_id=inp.package_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            output_kind=OUTPUT_KIND_SEMANTIC_COMPLIANCE,
            disclaimer=NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER,
            is_final_legal_determination=False,
            is_model_summary_substitution=False,
            is_pass=is_pass,
            overall_pass=is_pass,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(dict.fromkeys(warnings)),
            results=tuple(results),
            satisfied_count=satisfied,
            unsatisfied_count=unsatisfied,
            incomplete_count=incomplete,
            unknown_count=unknown,
            fail_count=fail,
            ruleset_versions=self._ruleset_versions(),
            documented_rules=list_documented_rules(),
            labels=dict(inp.labels),
            text_digest=text_digest,
            human_review=boundary,
        )

    def _bind_one(
        self,
        *,
        analysis_id: str,
        seq: int,
        obligation: AtomicObligation,
        evidence_items: Sequence[EvidenceItem],
        condition_facts: Mapping[str, bool],
        run_proofs: bool,
    ) -> ObligationComplianceResult:
        result_id = f"ocr:{analysis_id}:{seq:04d}"
        reasons: list[str] = [
            SemanticComplianceReasonCode.NOT_FINAL_LEGAL_DETERMINATION.value,
            SemanticComplianceReasonCode.HUMAN_REVIEW_BOUNDARY_EXPOSED.value,
            SemanticComplianceReasonCode.MODEL_SIMILARITY_NOT_SATISFACTION.value,
        ]

        bindings = bind_evidence_to_obligation(
            obligation=obligation,
            evidence_items=evidence_items,
            id_factory=self._id_factory,
            max_candidates=self.bounds.max_candidates,
            max_bindings=self.bounds.max_bindings,
        )
        for b in bindings:
            reasons.extend(b.reason_codes)

        support = tuple(
            b.evidence_id
            for b in bindings
            if b.role is BindingRole.SUPPORT and b.establishes_satisfaction
        )
        counter = tuple(
            b.evidence_id for b in bindings if b.role is BindingRole.COUNTER
        )
        ranked = tuple(
            b.evidence_id
            for b in bindings
            if b.role is BindingRole.CANDIDATE_RANKED
        )
        unrelated = tuple(
            b for b in bindings if b.role is BindingRole.UNRELATED
        )

        if any(
            SemanticComplianceReasonCode.UNRELATED_REMARKS_REJECTED.value
            in b.reason_codes
            for b in unrelated
        ):
            reasons.append(
                SemanticComplianceReasonCode.UNRELATED_REMARKS_REJECTED.value
            )

        # Conditions / exceptions.
        met, unmet = evaluate_conditions(
            obligation.required_conditions, condition_facts
        )
        exceptions_applied = tuple(
            e
            for e in obligation.exceptions
            if condition_facts.get(e) is True
        )
        if met and not unmet:
            reasons.append(SemanticComplianceReasonCode.CONDITIONS_MET.value)
        elif met and unmet:
            reasons.append(SemanticComplianceReasonCode.CONDITIONS_PARTIAL.value)
        elif unmet:
            reasons.append(SemanticComplianceReasonCode.CONDITIONS_UNMET.value)
        if exceptions_applied:
            reasons.append(SemanticComplianceReasonCode.EXCEPTION_APPLIES.value)

        # Authority provenance — always emit at least one record.
        authority_prov: list[AuthorityProvenance] = list(obligation.authority_refs)
        if not authority_prov:
            if obligation.citation_keys or obligation.legal_citations:
                authority_prov.append(
                    AuthorityProvenance(
                        authority_id=f"auth:missing:{obligation.obligation_id}",
                        citation_surface=(
                            obligation.legal_citations[0]
                            if obligation.legal_citations
                            else None
                        ),
                        citation_key=(
                            obligation.citation_keys[0]
                            if obligation.citation_keys
                            else None
                        ),
                        version=None,
                        node_id=None,
                        content_sha256=None,
                        authority_rank=None,
                        resolution_state="missing",
                        labels={"source": "obligation_citation_only"},
                    )
                )
                reasons.append(
                    SemanticComplianceReasonCode.AUTHORITY_MISSING.value
                )
            else:
                authority_prov.append(
                    AuthorityProvenance(
                        authority_id=f"auth:none:{obligation.obligation_id}",
                        citation_surface=None,
                        citation_key=None,
                        version=None,
                        node_id=None,
                        content_sha256=None,
                        authority_rank=None,
                        resolution_state="absent",
                        labels={},
                    )
                )
                reasons.append(
                    SemanticComplianceReasonCode.AUTHORITY_MISSING.value
                )
        else:
            reasons.append(
                SemanticComplianceReasonCode.AUTHORITY_PROVENANCE.value
            )

        # Deterministic rules.
        kind_val = (
            obligation.kind.value
            if isinstance(obligation.kind, ObligationKind)
            else str(obligation.kind)
        )
        has_support = bool(support)
        has_counter = bool(counter)
        needs_overlap = requires_claim_or_citation_overlap(obligation.kind)
        support_bindings = [
            b for b in bindings if b.evidence_id in support
        ]
        has_overlap = any(
            b.claim_overlap or b.citation_overlap for b in support_bindings
        )
        all_admitted = all(
            b.evidence_admission is EvidenceAdmission.ADMITTED
            for b in support_bindings
        ) if support_bindings else False
        conditions_ok = not unmet
        no_counter = not has_counter

        pre_common = {
            "obligation_admitted_or_normalized": obligation.admission
            is not EvidenceAdmission.REJECTED,
            "evidence_admitted": has_support and all_admitted,
            "kind_compatible": any(b.kind_compatible for b in support_bindings)
            if support_bindings
            else False,
            "claim_or_citation_overlap": has_overlap if needs_overlap else True,
            "no_unresolved_counter": no_counter,
            "conditions_resolved": conditions_ok,
            "obligation_kind_rejection_or_objection": kind_val
            in (
                ObligationKind.REJECTION_RESPONSE.value,
                ObligationKind.OBJECTION_RESPONSE.value,
            ),
            "responsive_kind": any(b.kind_compatible for b in support_bindings)
            if support_bindings
            else False,
            "obligation_kind_fee_or_form": kind_val
            in (ObligationKind.FEE.value, ObligationKind.FORM.value),
            "identifier_match_or_absent": True,
        }

        rule_receipts: list[DeterministicRuleReceipt] = []
        rule_keys: list[str] = []
        if kind_val in (
            ObligationKind.REJECTION_RESPONSE.value,
            ObligationKind.OBJECTION_RESPONSE.value,
        ):
            rule_keys.append("sc.rejection_requires_responsive_argument@1")
        elif kind_val in (ObligationKind.FEE.value, ObligationKind.FORM.value):
            rule_keys.append("sc.fee_form_presence_binding@1")
        else:
            rule_keys.append("sc.exact_claim_citation_binding@1")

        rule_applied = False
        for rk in rule_keys:
            receipt = _evaluate_rule_receipt(
                rule_key=rk,
                preconditions=pre_common,
                id_factory=self._id_factory,
            )
            if receipt is not None:
                rule_receipts.append(receipt)
                if receipt.applied:
                    rule_applied = True
                    reasons.append(
                        SemanticComplianceReasonCode.DETERMINISTIC_RULE_APPLIED.value
                    )
                else:
                    reasons.append(
                        SemanticComplianceReasonCode.DETERMINISTIC_RULE_FAILED.value
                    )

        # Proof provenance — always produce a receipt for the proof leg.
        proof = _run_obligation_proof(
            obligation=obligation,
            support_ids=support,
            counter_ids=counter,
            id_factory=self._id_factory,
            proof_executor=self.proof_executor,
            run_proofs=run_proofs and has_support and no_counter and conditions_ok,
        )
        reasons.extend(proof.reason_codes)

        # Evidence absence.
        if not evidence_items:
            reasons.append(SemanticComplianceReasonCode.EVIDENCE_ABSENT.value)
        if not support and not counter and not ranked:
            reasons.append(SemanticComplianceReasonCode.EVIDENCE_ABSENT.value)

        # Status decision tree (fail closed).
        status: SatisfactionStatus
        is_pass = False

        if exceptions_applied and not support:
            # Exception alone does not auto-satisfy without evidence of applicability.
            status = SatisfactionStatus.UNKNOWN
            reasons.append(SemanticComplianceReasonCode.UNKNOWN_STATUS.value)
        elif has_counter and has_support:
            status = SatisfactionStatus.FAIL
            reasons.append(SemanticComplianceReasonCode.CONTRADICTION.value)
            reasons.append(
                SemanticComplianceReasonCode.UNRESOLVED_CONTRADICTION.value
            )
            reasons.append(SemanticComplianceReasonCode.FAIL.value)
        elif has_counter and not has_support:
            status = SatisfactionStatus.FAIL
            reasons.append(SemanticComplianceReasonCode.EVIDENCE_COUNTER.value)
            reasons.append(SemanticComplianceReasonCode.FAIL.value)
        elif unmet and has_support:
            # Partial / conditional: some evidence but conditions incomplete.
            status = SatisfactionStatus.INCOMPLETE
            reasons.append(SemanticComplianceReasonCode.INCOMPLETE.value)
            reasons.append(SemanticComplianceReasonCode.CONDITIONS_PARTIAL.value)
        elif unmet and not has_support:
            status = SatisfactionStatus.INCOMPLETE
            reasons.append(SemanticComplianceReasonCode.INCOMPLETE.value)
            reasons.append(SemanticComplianceReasonCode.CONDITIONS_UNMET.value)
        elif not has_support:
            # Check if only model candidates ranked high — still not satisfaction.
            if ranked:
                status = SatisfactionStatus.UNSATISFIED
                reasons.append(SemanticComplianceReasonCode.UNSATISFIED.value)
                reasons.append(
                    SemanticComplianceReasonCode.MODEL_SIMILARITY_NOT_SATISFACTION.value
                )
            elif any(
                SemanticComplianceReasonCode.UNRELATED_REMARKS_REJECTED.value
                in b.reason_codes
                for b in bindings
            ):
                status = SatisfactionStatus.UNSATISFIED
                reasons.append(SemanticComplianceReasonCode.UNSATISFIED.value)
                reasons.append(
                    SemanticComplianceReasonCode.UNRELATED_REMARKS_REJECTED.value
                )
            else:
                status = SatisfactionStatus.UNSATISFIED
                reasons.append(SemanticComplianceReasonCode.UNSATISFIED.value)
                reasons.append(SemanticComplianceReasonCode.EVIDENCE_ABSENT.value)
        elif has_support and rule_applied and (
            proof.is_proved
            or (
                proof.outcome == ProofOutcome.UNKNOWN.value
                and rule_applied
            )
        ):
            # Satisfied only with support + deterministic rule (proof optional
            # when rule fully applied; proof still always receipted).
            # If proof explicitly disproved, fail instead.
            if proof.outcome == ProofOutcome.DISPROVED.value:
                status = SatisfactionStatus.FAIL
                reasons.append(SemanticComplianceReasonCode.FAIL.value)
            elif proof.outcome == ProofOutcome.ERROR.value:
                status = SatisfactionStatus.UNKNOWN
                reasons.append(SemanticComplianceReasonCode.UNKNOWN_STATUS.value)
            elif proof.outcome == ProofOutcome.TIMEOUT.value:
                status = SatisfactionStatus.UNKNOWN
                reasons.append(SemanticComplianceReasonCode.UNKNOWN_STATUS.value)
            else:
                status = SatisfactionStatus.SATISFIED
                is_pass = True
                reasons.append(SemanticComplianceReasonCode.SATISFIED.value)
        elif has_support and not rule_applied:
            # Evidence present but rule preconditions incomplete → incomplete/unknown.
            if not conditions_ok:
                status = SatisfactionStatus.INCOMPLETE
                reasons.append(SemanticComplianceReasonCode.INCOMPLETE.value)
            else:
                status = SatisfactionStatus.UNKNOWN
                reasons.append(SemanticComplianceReasonCode.UNKNOWN_STATUS.value)
        else:
            status = SatisfactionStatus.UNKNOWN
            reasons.append(SemanticComplianceReasonCode.UNKNOWN_STATUS.value)

        # Provenance completeness flags.
        if (
            obligation.source_span_ids
            and (support or counter or ranked or bindings)
            and authority_prov
            and (proof is not None or rule_receipts)
        ):
            reasons.append(
                SemanticComplianceReasonCode.PROVENANCE_COMPLETE.value
            )
        else:
            reasons.append(
                SemanticComplianceReasonCode.PROVENANCE_INCOMPLETE.value
            )

        conf = obligation.confidence
        if support_bindings:
            sims = [
                b.similarity_score
                for b in support_bindings
                if b.similarity_score is not None
            ]
            if sims:
                conf = (conf or 0.0) * 0.5 + (sum(sims) / len(sims)) * 0.5

        boundary = HumanReviewBoundary(
            requires_human_review=not is_pass,
            is_final_legal_determination=False,
            review_state=(
                ReviewState.NOT_REQUIRED if is_pass else ReviewState.REQUIRED
            ),
            boundary_reason=(
                "obligation_satisfied_with_exact_binding"
                if is_pass
                else f"obligation_{status.value}"
            ),
            review_question=(
                f"Optional review of satisfied obligation {obligation.obligation_id}."
                if is_pass
                else (
                    f"Human review required for obligation {obligation.obligation_id} "
                    f"(status={status.value}): verify exact responsive evidence, "
                    f"conditions, contradictions, and proof provenance."
                )
            ),
            confidence=conf,
            may_auto_pass=is_pass,
        )

        return ObligationComplianceResult(
            schema_version=SEMANTIC_COMPLIANCE_SCHEMA_VERSION,
            result_id=result_id,
            obligation=obligation,
            status=status,
            bindings=bindings,
            support_evidence_ids=support,
            counter_evidence_ids=counter,
            ranked_candidate_ids=ranked,
            authority_provenance=tuple(authority_prov),
            proof_provenance=proof,
            rule_receipts=tuple(rule_receipts),
            conditions_met=met,
            conditions_unmet=unmet,
            exceptions_applied=exceptions_applied,
            reason_codes=tuple(dict.fromkeys(reasons)),
            human_review=boundary,
            confidence=conf,
            is_pass=is_pass,
            labels=dict(obligation.labels),
        )


def analyze_semantic_compliance(
    value: SemanticComplianceInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> SemanticComplianceResult:
    """Module-level convenience entry point."""
    return SemanticComplianceProcessor().analyze(value, **kwargs)


# ---------------------------------------------------------------------------
# Compact fixture builders (tests / integration recipes)
# ---------------------------------------------------------------------------


def build_authority(
    *,
    authority_id: str = "auth:112b",
    citation_surface: str = "35 U.S.C. § 112(b)",
    citation_key: str = "35-usc-112(b)",
    version: str = "aia-2011",
    resolved: bool = True,
) -> AuthorityProvenance:
    return AuthorityProvenance(
        authority_id=authority_id,
        citation_surface=citation_surface,
        citation_key=citation_key,
        version=version if resolved else None,
        node_id=authority_id if resolved else None,
        content_sha256=sha256_hex(citation_key + (version or "")),
        authority_rank="official-base" if resolved else None,
        resolution_state="resolved" if resolved else "missing",
        labels={},
    )


def build_rejection_obligation(
    *,
    obligation_id: str = "obl:rej-112b",
    claims: Sequence[str] = ("1", "2", "3"),
    citation_key: str = "35-usc-112(b)",
    conditions: Sequence[str] = (),
    authority: AuthorityProvenance | None = None,
) -> AtomicObligation:
    surface = (
        f"Claims {', '.join(claims)} are rejected under 35 U.S.C. § 112(b) "
        f"as indefinite."
    )
    return AtomicObligation(
        obligation_id=obligation_id,
        kind=ObligationKind.REJECTION_RESPONSE,
        source_span_ids=("span:oa:rej-112b",),
        source_field_id="field:rej-112b",
        surface_text=surface,
        text_digest=_text_digest(surface),
        claim_tokens=tuple(claims),
        citation_keys=(citation_key,),
        legal_citations=("35 U.S.C. § 112(b)",),
        required_conditions=tuple(conditions),
        exceptions=(),
        required_act="amend_or_traverse",
        authority_refs=(authority or build_authority(),),
        admission=EvidenceAdmission.ADMITTED,
        confidence=0.92,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={"fixture": "rejection_112b"},
    )


def build_responsive_argument_evidence(
    *,
    evidence_id: str = "ev:arg-112b",
    claims: Sequence[str] = ("1", "2", "3"),
    citation_key: str = "35-usc-112(b)",
    admitted: bool = True,
    is_counter: bool = False,
) -> EvidenceItem:
    surface = (
        f"Applicant traverses the rejection of claims {', '.join(claims)} "
        f"under 35 U.S.C. § 112(b) and amends claim {claims[0]} for clarity."
    )
    return EvidenceItem(
        evidence_id=evidence_id,
        kind=ResponsiveEvidenceKind.ARGUMENT,
        document_id="doc:remarks",
        anchor_ids=("anchor:remarks:1",),
        surface_text=surface,
        text_digest=_text_digest(surface),
        claim_tokens=tuple(claims),
        citation_keys=(citation_key,),
        admission=(
            EvidenceAdmission.ADMITTED if admitted else EvidenceAdmission.CANDIDATE
        ),
        origin=EvidenceOrigin.DETERMINISTIC_RULE,
        confidence=0.9,
        content_sha256=sha256_hex(surface),
        is_counter=is_counter,
        labels={"admission_receipt_id": "adm:arg-1"} if admitted else {},
        model_similarity=None,
    )


def build_unrelated_remarks_evidence(
    *,
    evidence_id: str = "ev:remarks-unrelated",
) -> EvidenceItem:
    """Remarks that do not address the rejection's claims or citation."""
    surface = (
        "Applicant respectfully requests reconsideration of the overall "
        "application and notes that the drawings are satisfactory."
    )
    return EvidenceItem(
        evidence_id=evidence_id,
        kind=ResponsiveEvidenceKind.ARGUMENT,
        document_id="doc:remarks",
        anchor_ids=("anchor:remarks:unrelated",),
        surface_text=surface,
        text_digest=_text_digest(surface),
        claim_tokens=(),  # no claim binding
        citation_keys=(),  # no citation overlap with 112(b)
        admission=EvidenceAdmission.ADMITTED,
        origin=EvidenceOrigin.DETERMINISTIC_RULE,
        confidence=0.85,
        content_sha256=sha256_hex(surface),
        is_counter=False,
        labels={"admission_receipt_id": "adm:unrelated"},
        model_similarity=0.77,  # high similarity must not satisfy
    )


def build_model_candidate_evidence(
    *,
    evidence_id: str = "ev:model-cand",
    claims: Sequence[str] = ("1", "2", "3"),
    citation_key: str = "35-usc-112(b)",
    similarity: float = 0.95,
) -> EvidenceItem:
    surface = (
        f"Model-proposed response addressing claims {', '.join(claims)} "
        f"and citation {citation_key}."
    )
    return EvidenceItem(
        evidence_id=evidence_id,
        kind=ResponsiveEvidenceKind.ARGUMENT,
        document_id="doc:model",
        anchor_ids=("anchor:model:1",),
        surface_text=surface,
        text_digest=_text_digest(surface),
        claim_tokens=tuple(claims),
        citation_keys=(citation_key,),
        admission=EvidenceAdmission.CANDIDATE,
        origin=EvidenceOrigin.MODEL,
        confidence=similarity,
        content_sha256=sha256_hex(surface),
        is_counter=False,
        labels={},
        model_similarity=similarity,
    )


def build_fee_obligation(
    *,
    obligation_id: str = "obl:fee-issue",
) -> AtomicObligation:
    surface = "Issue fee payment is required under 37 C.F.R. § 1.18."
    return AtomicObligation(
        obligation_id=obligation_id,
        kind=ObligationKind.FEE,
        source_span_ids=("span:oa:fee",),
        source_field_id="field:fee",
        surface_text=surface,
        text_digest=_text_digest(surface),
        claim_tokens=(),
        citation_keys=("37-cfr-1.18",),
        legal_citations=("37 C.F.R. § 1.18",),
        required_conditions=(),
        exceptions=(),
        required_act="pay_issue_fee",
        authority_refs=(
            build_authority(
                authority_id="auth:1.18",
                citation_surface="37 C.F.R. § 1.18",
                citation_key="37-cfr-1.18",
                version="2020-base",
            ),
        ),
        admission=EvidenceAdmission.ADMITTED,
        confidence=0.95,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={"fixture": "fee"},
    )


def build_fee_evidence(
    *,
    evidence_id: str = "ev:fee-1",
    admitted: bool = True,
) -> EvidenceItem:
    surface = "Fee code 1501 issue fee paid; receipt ACK-12345."
    return EvidenceItem(
        evidence_id=evidence_id,
        kind=ResponsiveEvidenceKind.FEE,
        document_id="doc:fee",
        anchor_ids=("anchor:fee:1",),
        surface_text=surface,
        text_digest=_text_digest(surface),
        claim_tokens=(),
        citation_keys=("37-cfr-1.18",),
        admission=(
            EvidenceAdmission.ADMITTED if admitted else EvidenceAdmission.CANDIDATE
        ),
        origin=EvidenceOrigin.DETERMINISTIC_RULE,
        confidence=0.95,
        content_sha256=sha256_hex(surface),
        is_counter=False,
        labels={"admission_receipt_id": "adm:fee"} if admitted else {},
    )


def build_unrelated_remarks_fixture() -> SemanticComplianceInput:
    """Rejection + only unrelated remarks — must not satisfy."""
    return SemanticComplianceInput(
        analysis_id="analysis:unrelated-remarks",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(build_rejection_obligation(),),
        evidence=(build_unrelated_remarks_evidence(),),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={"fixture": "unrelated_remarks"},
    )


def build_responsive_satisfaction_fixture() -> SemanticComplianceInput:
    """Rejection + claim/citation-overlapping admitted argument — may satisfy."""
    return SemanticComplianceInput(
        analysis_id="analysis:responsive-ok",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(build_rejection_obligation(),),
        evidence=(build_responsive_argument_evidence(),),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={"fixture": "responsive_satisfaction"},
    )


def build_partial_conditions_fixture() -> SemanticComplianceInput:
    """Support present but required conditions only partially met."""
    return SemanticComplianceInput(
        analysis_id="analysis:partial-cond",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(
            build_rejection_obligation(
                conditions=("timely_response", "fee_paid"),
            ),
        ),
        evidence=(build_responsive_argument_evidence(),),
        condition_facts={"timely_response": True},  # fee_paid unmet
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={"fixture": "partial_conditions"},
    )


def build_contradiction_fixture() -> SemanticComplianceInput:
    """Support and counter evidence for the same rejection."""
    return SemanticComplianceInput(
        analysis_id="analysis:contradiction",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(build_rejection_obligation(),),
        evidence=(
            build_responsive_argument_evidence(evidence_id="ev:support"),
            build_responsive_argument_evidence(
                evidence_id="ev:counter",
                is_counter=True,
            ),
        ),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={"fixture": "contradiction"},
    )


def build_model_similarity_only_fixture() -> SemanticComplianceInput:
    """High model similarity candidate only — cannot establish satisfaction."""
    return SemanticComplianceInput(
        analysis_id="analysis:model-only",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(build_rejection_obligation(),),
        evidence=(
            build_model_candidate_evidence(similarity=0.99),
            build_unrelated_remarks_evidence(),
        ),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={"fixture": "model_similarity_only"},
    )


def build_fee_satisfaction_fixture() -> SemanticComplianceInput:
    return SemanticComplianceInput(
        analysis_id="analysis:fee-ok",
        matter_id="matter:1",
        office_action_artifact_id="art:oa:1",
        package_id="pkg:1",
        obligations=(build_fee_obligation(),),
        evidence=(build_fee_evidence(),),
        condition_facts={},
        classification=DisclosureClassification.PUBLIC_USER,
        run_proofs=True,
        labels={"fixture": "fee_satisfaction"},
    )


__all__ = [
    "SEMANTIC_COMPLIANCE_SCHEMA_VERSION",
    "SEMANTIC_COMPLIANCE_INTERFACE",
    "SEMANTIC_COMPLIANCE_RULESET_VERSION",
    "PARSER_VERSION",
    "OUTPUT_KIND_SEMANTIC_COMPLIANCE",
    "NOT_FINAL_LEGAL_DETERMINATION_DISCLAIMER",
    "DOCUMENTED_DETERMINISTIC_RULES",
    "ObligationKind",
    "ResponsiveEvidenceKind",
    "SatisfactionStatus",
    "BindingRole",
    "EvidenceAdmission",
    "EvidenceOrigin",
    "ComplianceDisposition",
    "SemanticComplianceReasonCode",
    "SemanticComplianceError",
    "AnalysisBounds",
    "AuthorityProvenance",
    "ProofProvenance",
    "DeterministicRuleReceipt",
    "HumanReviewBoundary",
    "AtomicObligation",
    "EvidenceItem",
    "EvidenceBinding",
    "ObligationComplianceResult",
    "SemanticComplianceInput",
    "SemanticComplianceResult",
    "SemanticComplianceProcessor",
    "sha256_hex",
    "jaccard_similarity",
    "tokenize_surface",
    "responsive_kinds_for",
    "requires_claim_or_citation_overlap",
    "is_satisfaction_pass",
    "documented_rule",
    "list_documented_rules",
    "contains_forbidden_unlawful_token",
    "sanitize_labels",
    "map_pkg_fact_kind",
    "map_oa_field_kind",
    "obligation_from_oa_field",
    "evidence_from_normalized_fact",
    "claim_overlap",
    "citation_overlap",
    "kind_is_compatible",
    "rank_similarity",
    "evaluate_conditions",
    "bind_evidence_to_obligation",
    "analyze_semantic_compliance",
    "build_authority",
    "build_rejection_obligation",
    "build_responsive_argument_evidence",
    "build_unrelated_remarks_evidence",
    "build_model_candidate_evidence",
    "build_fee_obligation",
    "build_fee_evidence",
    "build_unrelated_remarks_fixture",
    "build_responsive_satisfaction_fixture",
    "build_partial_conditions_fixture",
    "build_contradiction_fixture",
    "build_model_similarity_only_fixture",
    "build_fee_satisfaction_fixture",
]
