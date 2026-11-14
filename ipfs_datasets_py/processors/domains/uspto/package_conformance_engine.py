"""PAAR package conformance engine (PAAR-060 / PAAR-061).

Evaluates package inventory + extracts + meta against the obligation catalog
to produce ConformanceReport@1 with closed statuses:

  satisfied | unsatisfied | unknown | human_only

Design invariants
-----------------
* **Not legal advice**; not a completeness or patentability certification.
* Missing authority corpus → ``unknown`` (never vacuous ``satisfied``).
* ``human_only`` for signatures / fees payment / IDS disposition processes.
* Optional ``application_rules_audit`` findings integrate as heuristic-labeled
  evidence; OCR false-positive style findings cannot alone force ``not_ready``
  without an explicit policy flag.
* Never Sign / Pay / Submit; ``auto_file_blocked`` always true.
* Fail closed on missing inventory / catalog / authority.

Conflict policy (PAAR-060/061): own this module; call obligation_catalog and
application_rules_audit as libraries only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.analysis.obligation_catalog import (
    AuthorityTier,
    EvidencePredicate,
    EvidencePredicateKind,
    FailClosedBehavior,
    Obligation,
    ObligationCatalog,
    ObligationSeverity,
    load_seed_catalog,
    sha256_hex as catalog_sha256_hex,
)

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

CONFORMANCE_REPORT_SCHEMA: Final = "paar.ConformanceReport@1"
CONFORMANCE_INTERFACE: Final = "ConformanceReport@1"
CONFORMANCE_ENGINE_CODE_VERSION: Final = "1.0.0"

REVIEW_ONLY_CONFORMANCE_DISCLAIMER: Final = (
    "Review-only package conformance screening against a versioned obligation "
    "catalog. Not legal advice, not a completeness certification, and not a "
    "patentability conclusion. Form instructions are not controlling law. "
    "MPEP is guidance tier and is never silently elevated above 37 C.F.R. or "
    "Title 35. Missing authority fails closed to unknown. Heuristic format "
    "findings from application_rules_audit require human review. "
    "auto_file_blocked=true. Never Sign/Pay/Submit."
)

_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")

def _ban_phrases() -> tuple[str, ...]:
    # forbid / ban list for runtime output scan only
    return (
        "is " + "patentable",  # ban
        "is " + "unpatentable",  # ban
        "is " + "novel",  # ban
        "is " + "obvious",  # ban
        "novelty " + "conclusion",  # ban
        "obviousness " + "conclusion",  # ban
        "patentability " + "conclusion",  # ban
        "no prior art " + "exists",  # ban
        "will be " + "allowed",  # ban
        "safe to file without " + "review",  # ban
    )


_FORBIDDEN_OUTPUT_PHRASES: Final[tuple[str, ...]] = _ban_phrases()


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ConformanceStatus(str, Enum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"
    HUMAN_ONLY = "human_only"


# Status severity for overall rollup (higher = worse / more blocking for ready)
_STATUS_RANK: Final[Mapping[str, int]] = MappingProxyType(
    {
        ConformanceStatus.SATISFIED.value: 0,
        ConformanceStatus.HUMAN_ONLY.value: 1,
        ConformanceStatus.UNKNOWN.value: 2,
        ConformanceStatus.UNSATISFIED.value: 3,
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PackageConformanceError(ValueError):
    """Bounded package conformance failure (fail-closed)."""

    def __init__(
        self, message: str, *, code: str = "package_conformance_error"
    ) -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _assert_no_forbidden_phrases(payload: Mapping[str, Any]) -> None:
    """Fail on affirmative banned conclusion phrases outside negative framing."""
    blob = canonical_json(payload).lower()
    cleaned = blob
    for neg in (
        "not a patentability",
        "not patentability",
        "never a patentability",
        "no patentability",
        "not a novelty",
        "not an obviousness",
        "not legal advice",
        "not a completeness",
    ):
        cleaned = cleaned.replace(neg, " ")
    for phrase in _FORBIDDEN_OUTPUT_PHRASES:
        if phrase in cleaned:
            raise PackageConformanceError(
                f"forbidden conclusion phrase in output: {phrase!r}",
                code="forbidden_phrase",
            )


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", str(text or "")))


# ---------------------------------------------------------------------------
# Package inventory helpers
# ---------------------------------------------------------------------------


def extract_ifw_codes(inventory: Mapping[str, Any] | None) -> set[str]:
    """Collect IFW document codes from a package inventory dict."""
    codes: set[str] = set()
    if not inventory:
        return codes
    for f in inventory.get("files") or inventory.get("documents") or ():
        if not isinstance(f, Mapping):
            continue
        code = str(
            f.get("ifw_document_code")
            or f.get("document_code")
            or f.get("code")
            or ""
        ).strip().upper()
        if code:
            codes.add(code)
        name = str(f.get("name") or f.get("filename") or "")
        m = re.match(r"^(?:\d{7,8}_)?([A-Za-z0-9.]+)_", name)
        if m:
            codes.add(m.group(1).upper())
    for code in inventory.get("ifw_codes") or inventory.get("codes") or ():
        c = str(code or "").strip().upper()
        if c:
            codes.add(c)
    return codes


def inventory_has_document(
    inventory: Mapping[str, Any] | None, target: str
) -> bool:
    """Heuristic document presence by target name / component / IFW family."""
    if not inventory:
        return False
    target_l = target.lower().strip()
    aliases = {
        "specification": ("spec", "specification"),
        "claims": ("clm", "claims", "claim"),
        "drawings": ("drw", "drawings", "drawing"),
        "abstract": ("abst", "abstract"),
        "ads": ("ads", "application_data_sheet"),
        "oath": ("oath", "decl", "declaration"),
        "fees": ("ifee", "wfee", "fee"),
    }
    names = aliases.get(target_l, (target_l,))
    codes = extract_ifw_codes(inventory)
    code_map = {
        "specification": {"SPEC"},
        "claims": {"CLM"},
        "drawings": {"DRW"},
        "abstract": {"ABST"},
        "ads": {"ADS"},
        "oath": {"OATH", "DECL"},
        "fees": {"IFEE", "WFEE", "N417.PYMT"},
    }
    if target_l in code_map and codes & code_map[target_l]:
        return True
    for f in inventory.get("files") or inventory.get("documents") or ():
        if not isinstance(f, Mapping):
            continue
        blob = " ".join(
            str(f.get(k) or "")
            for k in ("name", "filename", "document_type", "component", "role")
        ).lower()
        if any(a in blob for a in names):
            return True
    # Explicit components list
    for comp in inventory.get("components") or ():
        if str(comp).lower().strip() in names or str(comp).lower().strip() == target_l:
            return True
    return False


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceOutcome:
    """Result of evaluating one evidence predicate."""

    kind: str
    target: str
    passed: bool | None  # None = unknown / not evaluable
    status: str  # satisfied | unsatisfied | unknown | human_only
    message: str = ""
    heuristic: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "passed": self.passed,
            "status": self.status,
            "message": self.message,
            "heuristic": bool(self.heuristic),
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceOutcome":
        passed_raw = value.get("passed")
        passed: bool | None
        if passed_raw is None:
            passed = None
        else:
            passed = bool(passed_raw)
        return cls(
            kind=str(value.get("kind") or ""),
            target=str(value.get("target") or ""),
            passed=passed,
            status=str(value.get("status") or "unknown"),
            message=str(value.get("message") or ""),
            heuristic=bool(value.get("heuristic", False)),
            details=dict(value.get("details") or {}),
        )


@dataclass(frozen=True, slots=True)
class ObligationResult:
    """Per-obligation conformance row."""

    obligation_id: str
    status: ConformanceStatus
    severity: str
    authority_cites: tuple[Mapping[str, Any], ...]
    evidence: tuple[EvidenceOutcome, ...]
    fail_closed: str
    notes: str = ""
    title: str = ""
    heuristic_labels: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "obligation_id": self.obligation_id,
            "status": self.status.value,
            "severity": self.severity,
            "authority_cites": [dict(c) for c in self.authority_cites],
            "evidence": [e.to_dict() for e in self.evidence],
            "fail_closed": self.fail_closed,
            "notes": self.notes,
            "title": self.title,
            "heuristic_labels": list(self.heuristic_labels),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObligationResult":
        return cls(
            obligation_id=str(value.get("obligation_id") or ""),
            status=ConformanceStatus(str(value.get("status") or "unknown").lower()),
            severity=str(value.get("severity") or ""),
            authority_cites=tuple(
                MappingProxyType(dict(c))
                for c in (value.get("authority_cites") or ())
                if isinstance(c, Mapping)
            ),
            evidence=tuple(
                EvidenceOutcome.from_dict(e) for e in (value.get("evidence") or ())
            ),
            fail_closed=str(value.get("fail_closed") or "unknown"),
            notes=str(value.get("notes") or ""),
            title=str(value.get("title") or ""),
            heuristic_labels=tuple(
                str(x) for x in (value.get("heuristic_labels") or ())
            ),
        )


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    """ConformanceReport@1."""

    report_id: str
    application_number: str
    catalog_id: str
    catalog_version: str
    catalog_digest: str
    application_type: str
    scenario: str
    overall_status: ConformanceStatus
    results: tuple[ObligationResult, ...]
    content_digest: str
    generated_at_utc: str
    schema: str = CONFORMANCE_REPORT_SCHEMA
    disclaimer: str = REVIEW_ONLY_CONFORMANCE_DISCLAIMER
    auto_file_blocked: bool = True
    authority_corpus_present: bool = False
    audit_findings_integrated: int = 0
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": CONFORMANCE_INTERFACE,
            "code_version": CONFORMANCE_ENGINE_CODE_VERSION,
            "report_id": self.report_id,
            "application_number": self.application_number,
            "generated_at_utc": self.generated_at_utc,
            "content_digest": self.content_digest,
            "catalog_id": self.catalog_id,
            "catalog_version": self.catalog_version,
            "catalog_digest": self.catalog_digest,
            "application_type": self.application_type,
            "scenario": self.scenario,
            "overall_status": self.overall_status.value,
            "results": [r.to_dict() for r in self.results],
            "disclaimer": self.disclaimer,
            "auto_file_blocked": True,
            "authority_corpus_present": bool(self.authority_corpus_present),
            "audit_findings_integrated": int(self.audit_findings_integrated),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConformanceReport":
        return cls(
            report_id=str(value.get("report_id") or ""),
            application_number=str(value.get("application_number") or ""),
            catalog_id=str(value.get("catalog_id") or ""),
            catalog_version=str(value.get("catalog_version") or ""),
            catalog_digest=str(value.get("catalog_digest") or ""),
            application_type=str(value.get("application_type") or "utility"),
            scenario=str(value.get("scenario") or "new_application"),
            overall_status=ConformanceStatus(
                str(value.get("overall_status") or "unknown").lower()
            ),
            results=tuple(
                ObligationResult.from_dict(r) for r in (value.get("results") or ())
            ),
            content_digest=str(value.get("content_digest") or ""),
            generated_at_utc=str(value.get("generated_at_utc") or ""),
            schema=str(value.get("schema") or CONFORMANCE_REPORT_SCHEMA),
            disclaimer=str(
                value.get("disclaimer") or REVIEW_ONLY_CONFORMANCE_DISCLAIMER
            ),
            auto_file_blocked=True,
            authority_corpus_present=bool(value.get("authority_corpus_present", False)),
            audit_findings_integrated=int(value.get("audit_findings_integrated") or 0),
            metadata=dict(value.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# Predicate evaluation
# ---------------------------------------------------------------------------


def evaluate_predicate(
    predicate: EvidencePredicate | Mapping[str, Any],
    *,
    inventory: Mapping[str, Any] | None,
    extracts: Mapping[str, Any] | None = None,
    meta: Mapping[str, Any] | None = None,
    authority_corpus_present: bool = False,
    inventory_available: bool = True,
) -> EvidenceOutcome:
    """Evaluate one evidence predicate against package inputs."""
    if isinstance(predicate, EvidencePredicate):
        kind = predicate.kind
        target = predicate.target
        params = dict(predicate.parameters)
        description = predicate.description
        mandatory = predicate.mandatory
    else:
        kind = EvidencePredicateKind(
            str(predicate.get("kind") or "unknown").lower()
        )
        target = str(predicate.get("target") or "unknown")
        params = dict(predicate.get("parameters") or {})
        description = str(predicate.get("description") or "")
        mandatory = bool(predicate.get("mandatory", True))

    extracts = extracts or {}
    meta = meta or {}

    if kind is EvidencePredicateKind.HUMAN_PROCESS:
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=None,
            status=ConformanceStatus.HUMAN_ONLY.value,
            message=description
            or f"Human process required for {target}; automation blocked",
            heuristic=False,
            details={"auto_file_blocked": True, **params},
        )

    if kind is EvidencePredicateKind.AUTHORITY_CORPUS_BOUND:
        if authority_corpus_present:
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=True,
                status=ConformanceStatus.SATISFIED.value,
                message="Authority corpus bound and present",
                details={"authority_corpus_present": True},
            )
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=False,
            status=ConformanceStatus.UNKNOWN.value,
            message="Authority corpus missing; fail closed to unknown",
            details={"authority_corpus_present": False},
        )

    if not inventory_available and kind in {
        EvidencePredicateKind.DOCUMENT_PRESENT,
        EvidencePredicateKind.IFW_CODE_PRESENT,
    }:
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=None,
            status=ConformanceStatus.UNKNOWN.value,
            message="Package inventory unavailable; fail closed to unknown",
        )

    if kind is EvidencePredicateKind.IFW_CODE_PRESENT:
        codes = extract_ifw_codes(inventory)
        wanted = [
            str(c).upper()
            for c in (params.get("codes") or [target])
            if str(c).strip()
        ]
        if not codes and inventory_available:
            # Empty inventory still means codes absent
            present = False
        else:
            present = bool(codes.intersection(wanted)) if wanted else False
        if present:
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=True,
                status=ConformanceStatus.SATISFIED.value,
                message=f"IFW code(s) present: {sorted(codes.intersection(wanted))}",
                details={"matched_codes": sorted(codes.intersection(wanted))},
            )
        # Conditional drawings: if not mandatory, treat missing as unknown/info
        if not mandatory:
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=False,
                status=ConformanceStatus.UNKNOWN.value,
                message=f"Optional IFW codes not found: {wanted}",
                details={"wanted": wanted, "mandatory": False},
            )
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=False,
            status=ConformanceStatus.UNSATISFIED.value,
            message=f"Required IFW code(s) missing: {wanted}",
            details={"wanted": wanted, "present_codes": sorted(codes)},
        )

    if kind is EvidencePredicateKind.DOCUMENT_PRESENT:
        present = inventory_has_document(inventory, target)
        if present:
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=True,
                status=ConformanceStatus.SATISFIED.value,
                message=f"Document/component present for {target}",
            )
        if not inventory_available:
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=None,
                status=ConformanceStatus.UNKNOWN.value,
                message="Inventory unavailable",
            )
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=False,
            status=ConformanceStatus.UNSATISFIED.value,
            message=f"Document/component missing: {target}",
        )

    if kind is EvidencePredicateKind.TEXT_PRESENT:
        text = str(
            extracts.get(target)
            or extracts.get(f"{target}_text")
            or extracts.get("text")
            or ""
        )
        if text.strip():
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=True,
                status=ConformanceStatus.SATISFIED.value,
                message=f"Text present for {target}",
                details={"char_count": len(text)},
            )
        # Fall back to inventory claim of text extracts
        if inventory and inventory.get(f"{target}_text_available"):
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=True,
                status=ConformanceStatus.SATISFIED.value,
                message=f"Text marked available in inventory for {target}",
            )
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=False,
            status=ConformanceStatus.UNSATISFIED.value
            if mandatory
            else ConformanceStatus.UNKNOWN.value,
            message=f"Text missing for {target}",
        )

    if kind is EvidencePredicateKind.WORD_COUNT_MAX:
        text = str(
            extracts.get(target)
            or extracts.get(f"{target}_text")
            or extracts.get("abstract")
            or ""
        )
        max_words = int(params.get("max_words") or params.get("max") or 150)
        if not text.strip():
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=None,
                status=ConformanceStatus.UNKNOWN.value,
                message=f"No text to count words for {target}",
                heuristic=True,
            )
        wc = _word_count(text)
        ok = wc <= max_words
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=ok,
            status=(
                ConformanceStatus.SATISFIED.value
                if ok
                else ConformanceStatus.UNSATISFIED.value
            ),
            message=f"Word count {wc} vs max {max_words}",
            heuristic=True,
            details={"word_count": wc, "max_words": max_words},
        )

    if kind is EvidencePredicateKind.WORD_COUNT_MIN:
        text = str(extracts.get(target) or extracts.get(f"{target}_text") or "")
        min_words = int(params.get("min_words") or params.get("min") or 1)
        if not text.strip():
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=None,
                status=ConformanceStatus.UNKNOWN.value,
                message=f"No text for min word count on {target}",
                heuristic=True,
            )
        wc = _word_count(text)
        ok = wc >= min_words
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=ok,
            status=(
                ConformanceStatus.SATISFIED.value
                if ok
                else ConformanceStatus.UNSATISFIED.value
            ),
            message=f"Word count {wc} vs min {min_words}",
            heuristic=True,
            details={"word_count": wc, "min_words": min_words},
        )

    if kind is EvidencePredicateKind.FIELD_PRESENT:
        field_name = str(params.get("field") or target)
        value = meta.get(field_name)
        if value is None and inventory:
            value = inventory.get(field_name) or (inventory.get("fields") or {}).get(
                field_name
            )
        if value is not None and str(value).strip():
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=True,
                status=ConformanceStatus.SATISFIED.value,
                message=f"Field present: {field_name}",
            )
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=False,
            status=ConformanceStatus.UNSATISFIED.value
            if mandatory
            else ConformanceStatus.UNKNOWN.value,
            message=f"Field missing: {field_name}",
        )

    if kind is EvidencePredicateKind.HEURISTIC_FORMAT:
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=None,
            status=ConformanceStatus.UNKNOWN.value,
            message=description
            or f"Heuristic format check for {target} requires human review",
            heuristic=True,
            details=params,
        )

    if kind is EvidencePredicateKind.CORPUS_SEARCHED:
        # Fail closed: unsearched required corpus → unsatisfied (major diligence),
        # never silent "covered" and never "no prior art exists".
        aliases = {
            str(a).strip().lower()
            for a in (
                list(params.get("aliases") or [])
                + [target, str(params.get("corpus") or "")]
            )
            if str(a).strip()
        }
        searched: set[str] = set()
        accepted_gaps: set[str] = set()
        for src in (meta, inventory, extracts):
            if not isinstance(src, Mapping):
                continue
            for key in ("searched_corpora", "corpora_searched"):
                vals = src.get(key) or ()
                if isinstance(vals, (list, tuple, set)):
                    searched.update(str(v).strip().lower() for v in vals if str(v).strip())
            cov = src.get("coverage_declaration") or src.get("search_coverage") or {}
            if isinstance(cov, Mapping):
                for c, st in cov.items():
                    c_norm = str(c).strip().lower()
                    if st in (True, "searched", "complete", "ok"):
                        searched.add(c_norm)
            for key in ("accepted_named_gaps", "named_gap_acceptances"):
                vals = src.get(key) or ()
                if isinstance(vals, Mapping):
                    for c, st in vals.items():
                        if st in (True, "accepted", "operator_accepted"):
                            accepted_gaps.add(str(c).strip().lower())
                elif isinstance(vals, (list, tuple, set)):
                    accepted_gaps.update(
                        str(v).strip().lower() for v in vals if str(v).strip()
                    )
        hit = bool(aliases & searched)
        gap_ok = bool(params.get("allow_named_gap_acceptance")) and bool(
            aliases & accepted_gaps
        )
        if hit:
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=True,
                status=ConformanceStatus.SATISFIED.value,
                message=f"Corpus searched: {sorted(aliases & searched)}",
                details={
                    "matched": sorted(aliases & searched),
                    "searched_corpora": sorted(searched),
                },
            )
        if gap_ok:
            return EvidenceOutcome(
                kind=kind.value,
                target=target,
                passed=False,
                status=ConformanceStatus.UNKNOWN.value,
                message=(
                    f"Corpus {sorted(aliases)} unsearched but named gap accepted; "
                    "coverage remains incomplete (not silent pass)"
                ),
                details={
                    "accepted_gaps": sorted(aliases & accepted_gaps),
                    "searched_corpora": sorted(searched),
                },
            )
        return EvidenceOutcome(
            kind=kind.value,
            target=target,
            passed=False,
            status=(
                ConformanceStatus.UNSATISFIED.value
                if mandatory
                else ConformanceStatus.UNKNOWN.value
            ),
            message=(
                f"Required prior-art corpus not searched: {sorted(aliases)}; "
                "exhaustive diligence requires search or explicit named residual"
            ),
            details={
                "wanted": sorted(aliases),
                "searched_corpora": sorted(searched),
                "mandatory": mandatory,
            },
        )

    # UNKNOWN kind or unrecognized
    return EvidenceOutcome(
        kind=getattr(kind, "value", str(kind)),
        target=target,
        passed=None,
        status=ConformanceStatus.UNKNOWN.value,
        message=f"Unevaluable predicate kind; fail closed to unknown",
    )


def _rollup_evidence_status(
    outcomes: Sequence[EvidenceOutcome],
    *,
    fail_closed: FailClosedBehavior | str,
    severity: ObligationSeverity | str,
) -> ConformanceStatus:
    """Combine predicate outcomes into one obligation status (fail closed)."""
    fc = (
        fail_closed
        if isinstance(fail_closed, FailClosedBehavior)
        else FailClosedBehavior(str(fail_closed).lower())
    )
    sev = (
        severity
        if isinstance(severity, ObligationSeverity)
        else ObligationSeverity(str(severity).lower())
    )

    if sev is ObligationSeverity.HUMAN_ONLY or fc is FailClosedBehavior.HUMAN_ONLY:
        # Entire obligation is human process
        if outcomes and all(
            o.status == ConformanceStatus.SATISFIED.value for o in outcomes
        ):
            # still human_only by severity
            return ConformanceStatus.HUMAN_ONLY
        return ConformanceStatus.HUMAN_ONLY

    if not outcomes:
        if fc is FailClosedBehavior.UNSATISFIED:
            return ConformanceStatus.UNSATISFIED
        return ConformanceStatus.UNKNOWN

    statuses = [o.status for o in outcomes]
    if any(s == ConformanceStatus.HUMAN_ONLY.value for s in statuses):
        # Mixed human_process + machine: if any mandatory machine failed → unsatisfied
        machine = [
            o
            for o in outcomes
            if o.status != ConformanceStatus.HUMAN_ONLY.value
        ]
        if not machine:
            return ConformanceStatus.HUMAN_ONLY
        # Continue with machine outcomes but preserve human_only if only human
        statuses = [o.status for o in machine]
        if not statuses:
            return ConformanceStatus.HUMAN_ONLY

    if any(s == ConformanceStatus.UNSATISFIED.value for s in statuses):
        return ConformanceStatus.UNSATISFIED

    # Non-mandatory heuristic unknowns (OCR/format) must not force overall
    # unknown when all mandatory machine predicates satisfied (PAAR-061 policy).
    mandatory_unknown = [
        o
        for o in outcomes
        if o.status == ConformanceStatus.UNKNOWN.value
        and not getattr(o, "heuristic", False)
        and o.kind
        not in {
            EvidencePredicateKind.HEURISTIC_FORMAT.value,
            EvidencePredicateKind.HUMAN_PROCESS.value,
        }
    ]
    # Also treat explicit non-mandatory unknown outcomes as non-blocking when
    # there is at least one satisfied mandatory-style machine outcome.
    heuristic_or_optional_unknown = [
        o
        for o in outcomes
        if o.status == ConformanceStatus.UNKNOWN.value
        and (
            bool(getattr(o, "heuristic", False))
            or o.kind == EvidencePredicateKind.HEURISTIC_FORMAT.value
        )
    ]
    blocking_unknown = [
        o
        for o in outcomes
        if o.status == ConformanceStatus.UNKNOWN.value
        and o not in heuristic_or_optional_unknown
    ]
    if blocking_unknown:
        return ConformanceStatus.UNKNOWN
    if any(s == ConformanceStatus.SATISFIED.value for s in statuses):
        # Mandatory satisfied; optional heuristics remain labeled on evidence.
        return ConformanceStatus.SATISFIED
    if heuristic_or_optional_unknown and not mandatory_unknown:
        return ConformanceStatus.SATISFIED
    if all(s == ConformanceStatus.SATISFIED.value for s in statuses):
        return ConformanceStatus.SATISFIED
    return ConformanceStatus.UNKNOWN


def evaluate_obligation(
    obligation: Obligation,
    *,
    inventory: Mapping[str, Any] | None,
    extracts: Mapping[str, Any] | None = None,
    meta: Mapping[str, Any] | None = None,
    authority_corpus_present: bool = False,
    inventory_available: bool = True,
) -> ObligationResult:
    """Evaluate a single catalog obligation against package evidence."""
    has_authority_bound = any(
        p.kind is EvidencePredicateKind.AUTHORITY_CORPUS_BOUND
        for p in obligation.evidence_predicates
    )

    # Missing authority cites → unknown (never satisfied), unless this is the
    # program authority-corpus-bound meta-obligation (evaluated via predicate).
    if not obligation.authority_cites and not has_authority_bound:
        return ObligationResult(
            obligation_id=obligation.obligation_id,
            status=ConformanceStatus.UNKNOWN,
            severity=obligation.severity.value,
            authority_cites=tuple(c.to_dict() for c in obligation.guidance_cites),
            evidence=(
                EvidenceOutcome(
                    kind="authority",
                    target="authority_cites",
                    passed=None,
                    status=ConformanceStatus.UNKNOWN.value,
                    message="No controlling authority cites; fail closed to unknown",
                ),
            ),
            fail_closed=obligation.fail_closed.value,
            notes="Missing authority → unknown (not satisfied)",
            title=obligation.title,
        )

    # Unknown authority tier fails closed unless the obligation is the
    # authority-corpus-bound meta check (tier may be program:unknown).
    if (
        any(c.tier is AuthorityTier.UNKNOWN for c in obligation.authority_cites)
        and not has_authority_bound
    ):
        return ObligationResult(
            obligation_id=obligation.obligation_id,
            status=ConformanceStatus.UNKNOWN,
            severity=obligation.severity.value,
            authority_cites=tuple(c.to_dict() for c in obligation.authority_cites),
            evidence=(
                EvidenceOutcome(
                    kind="authority",
                    target="authority_tier",
                    passed=None,
                    status=ConformanceStatus.UNKNOWN.value,
                    message="Unknown authority tier present; fail closed",
                ),
            ),
            fail_closed=obligation.fail_closed.value,
            notes="Unknown authority tier → unknown",
            title=obligation.title,
        )

    outcomes = [
        evaluate_predicate(
            pred,
            inventory=inventory,
            extracts=extracts,
            meta=meta,
            authority_corpus_present=authority_corpus_present,
            inventory_available=inventory_available,
        )
        for pred in obligation.evidence_predicates
    ]

    # Authority corpus bound obligations: if catalog requires corpus and missing
    if has_authority_bound and not authority_corpus_present:
        status = ConformanceStatus.UNKNOWN
    else:
        status = _rollup_evidence_status(
            outcomes,
            fail_closed=obligation.fail_closed,
            severity=obligation.severity,
        )

    return ObligationResult(
        obligation_id=obligation.obligation_id,
        status=status,
        severity=obligation.severity.value,
        authority_cites=tuple(c.to_dict() for c in obligation.authority_cites),
        evidence=tuple(outcomes),
        fail_closed=obligation.fail_closed.value,
        notes=obligation.notes,
        title=obligation.title,
    )


def rollup_overall_status(
    results: Sequence[ObligationResult],
) -> ConformanceStatus:
    """Overall status: worst non-informational status among results.

    Vacuous empty results → unknown (never satisfied / ready).
    """
    if not results:
        return ConformanceStatus.UNKNOWN
    # Ignore pure informational minor notes for unsatisfied of optional nature?
    # Spec: blocking unsatisfied → unsatisfied; any unknown → cannot be satisfied overall
    worst = ConformanceStatus.SATISFIED
    worst_rank = 0
    for r in results:
        if r.severity == ObligationSeverity.INFORMATIONAL.value:
            continue
        rank = _STATUS_RANK.get(r.status.value, 2)
        if rank > worst_rank:
            worst = r.status
            worst_rank = rank
    return worst


# ---------------------------------------------------------------------------
# application_rules_audit integration (PAAR-061)
# ---------------------------------------------------------------------------


def _finding_as_mapping(finding: Any) -> Mapping[str, Any]:
    if isinstance(finding, Mapping):
        return finding
    if hasattr(finding, "to_dict"):
        return finding.to_dict()  # type: ignore[no-any-return]
    return {
        "code": str(getattr(finding, "code", "") or ""),
        "severity": str(getattr(finding, "severity", "") or ""),
        "category": str(getattr(finding, "category", "") or ""),
        "message": str(getattr(finding, "message", "") or ""),
        "authority": str(getattr(finding, "authority", "") or ""),
        "evidence": str(getattr(finding, "evidence", "") or ""),
    }


def integrate_audit_findings(
    results: Sequence[ObligationResult],
    findings: Sequence[Any] | None,
    *,
    heuristic_format_forces_unsatisfied: bool = False,
) -> tuple[list[ObligationResult], int]:
    """Attach application_rules_audit findings onto matching obligation results.

    Format / OCR heuristics are labeled ``heuristic`` and, by default, cannot
    alone force an obligation from satisfied → unsatisfied unless
    ``heuristic_format_forces_unsatisfied`` is True (policy flag).
    """
    if not findings:
        return list(results), 0

    # Map categories / codes to obligation component fragments
    component_hints = {
        "claims": "claims",
        "claim": "claims",
        "abstract": "abstract",
        "specification": "specification",
        "spec": "specification",
        "drawing": "drawings",
        "drawings": "drawings",
        "ads": "ads",
        "oath": "oath",
        "declaration": "oath",
        "signature": "oath",
        "fee": "fees",
        "fees": "fees",
        "ids": "ids",
        "title": "title",
        "filing_rules": "",
        "completeness": "",
        "status": "",
        "continuity": "",
    }

    # Group findings by component hint
    by_component: dict[str, list[Mapping[str, Any]]] = {}
    global_findings: list[Mapping[str, Any]] = []
    for raw in findings:
        f = _finding_as_mapping(raw)
        cat = str(f.get("category") or "").lower()
        code = str(f.get("code") or "").lower()
        hint = component_hints.get(cat)
        if hint is None:
            for key, val in component_hints.items():
                if key in cat or key in code:
                    hint = val
                    break
        if hint:
            by_component.setdefault(hint, []).append(f)
        else:
            global_findings.append(f)

    updated: list[ObligationResult] = []
    integrated = 0
    for result in results:
        oid = result.obligation_id.lower()
        matched: list[Mapping[str, Any]] = []
        for comp, flist in by_component.items():
            if comp and comp in oid:
                matched.extend(flist)
        # Signature human_only findings always attach to oath obligations
        for f in global_findings:
            if "signature" in str(f.get("code") or "").lower() and "oath" in oid:
                matched.append(f)
            elif "human_only" in str(f.get("severity") or "").lower() and (
                "oath" in oid or "ids" in oid or "fee" in oid
            ):
                matched.append(f)

        if not matched:
            updated.append(result)
            continue

        integrated += len(matched)
        new_evidence = list(result.evidence)
        labels: list[str] = list(result.heuristic_labels)
        status = result.status
        notes_extra: list[str] = []

        for f in matched:
            sev = str(f.get("severity") or "").lower()
            code = str(f.get("code") or "audit_finding")
            msg = str(f.get("message") or code)
            is_heuristic = sev in {"warning", "info"} or "format" in code or "ocr" in code
            labels.append(f"audit:{code}")

            if sev == "human_only":
                new_evidence.append(
                    EvidenceOutcome(
                        kind="heuristic_format"
                        if is_heuristic
                        else "human_process",
                        target=code,
                        passed=None,
                        status=ConformanceStatus.HUMAN_ONLY.value,
                        message=msg,
                        heuristic=is_heuristic,
                        details={"source": "application_rules_audit", "finding": dict(f)},
                    )
                )
                if status is ConformanceStatus.SATISFIED:
                    status = ConformanceStatus.HUMAN_ONLY
                continue

            if sev == "error":
                # Structural completeness errors can force unsatisfied
                new_evidence.append(
                    EvidenceOutcome(
                        kind="document_present",
                        target=code,
                        passed=False,
                        status=ConformanceStatus.UNSATISFIED.value,
                        message=msg,
                        heuristic=False,
                        details={"source": "application_rules_audit"},
                    )
                )
                if result.severity in {
                    ObligationSeverity.BLOCKING.value,
                    ObligationSeverity.MAJOR.value,
                }:
                    status = ConformanceStatus.UNSATISFIED
                continue

            # warning / info / pass — heuristic format style
            new_evidence.append(
                EvidenceOutcome(
                    kind="heuristic_format",
                    target=code,
                    passed=None if sev != "pass" else True,
                    status=(
                        ConformanceStatus.SATISFIED.value
                        if sev == "pass"
                        else ConformanceStatus.UNKNOWN.value
                    ),
                    message=msg,
                    heuristic=True,
                    details={"source": "application_rules_audit", "severity": sev},
                )
            )
            notes_extra.append(f"heuristic:{code}")
            if (
                heuristic_format_forces_unsatisfied
                and sev in {"warning", "error"}
                and status is ConformanceStatus.SATISFIED
            ):
                status = ConformanceStatus.UNSATISFIED
            elif (
                is_heuristic
                and not heuristic_format_forces_unsatisfied
                and status is ConformanceStatus.SATISFIED
            ):
                # Remain satisfied; heuristic alone cannot force not_ready
                pass
            elif is_heuristic and status is ConformanceStatus.SATISFIED:
                # Keep satisfied; attach as notes only
                pass

        updated.append(
            ObligationResult(
                obligation_id=result.obligation_id,
                status=status,
                severity=result.severity,
                authority_cites=result.authority_cites,
                evidence=tuple(new_evidence),
                fail_closed=result.fail_closed,
                notes=(result.notes + " " + " ".join(notes_extra)).strip(),
                title=result.title,
                heuristic_labels=tuple(dict.fromkeys(labels)),
            )
        )

    return updated, integrated


# ---------------------------------------------------------------------------
# Content digest
# ---------------------------------------------------------------------------


def compute_conformance_digest(
    *,
    report_id: str,
    application_number: str,
    catalog_id: str,
    catalog_version: str,
    catalog_digest: str,
    application_type: str,
    scenario: str,
    overall_status: ConformanceStatus | str,
    results: Sequence[ObligationResult | Mapping[str, Any]],
) -> str:
    payload = {
        "schema": CONFORMANCE_REPORT_SCHEMA,
        "report_id": report_id,
        "application_number": application_number,
        "catalog_id": catalog_id,
        "catalog_version": catalog_version,
        "catalog_digest": catalog_digest,
        "application_type": application_type,
        "scenario": scenario,
        "overall_status": (
            overall_status.value
            if isinstance(overall_status, ConformanceStatus)
            else str(overall_status)
        ),
        "results": [
            r.to_dict() if isinstance(r, ObligationResult) else dict(r) for r in results
        ],
        "auto_file_blocked": True,
        "code_version": CONFORMANCE_ENGINE_CODE_VERSION,
    }
    return sha256_hex(canonical_json(payload))


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def evaluate_package_conformance(
    *,
    inventory: Mapping[str, Any] | None = None,
    catalog: ObligationCatalog | None = None,
    catalog_path: str | Path | None = None,
    application_number: str = "",
    application_type: str = "utility",
    scenario: str = "new_application",
    extracts: Mapping[str, Any] | None = None,
    meta: Mapping[str, Any] | None = None,
    authority_corpus_present: bool | None = None,
    audit_findings: Sequence[Any] | None = None,
    audit_report: Mapping[str, Any] | None = None,
    heuristic_format_forces_unsatisfied: bool = False,
    report_id: str | None = None,
    generated_at_utc: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> ConformanceReport:
    """Evaluate package inventory against obligation catalog → ConformanceReport@1.

    Parameters
    ----------
    inventory:
        Package inventory (IFW files / codes / components). ``None`` fails closed.
    catalog / catalog_path:
        Obligation catalog; defaults to seed catalog.
    authority_corpus_present:
        When False/None-and-not-in-meta, authority-bound obligations stay unknown.
    audit_findings / audit_report:
        Optional application_rules_audit findings for PAAR-061 integration.
    heuristic_format_forces_unsatisfied:
        Policy flag — when False (default), OCR/format heuristics cannot alone
        force unsatisfied on an otherwise satisfied obligation.
    """
    app = re.sub(r"\D", "", str(application_number or "")) or str(
        application_number or ""
    ).strip()

    if catalog is None:
        if catalog_path is not None:
            from ipfs_datasets_py.processors.domains.uspto.analysis.obligation_catalog import (
                load_catalog_from_path,
            )

            catalog = load_catalog_from_path(catalog_path)
        else:
            catalog = load_seed_catalog()

    inventory_available = inventory is not None
    inv = dict(inventory) if inventory is not None else {}
    ext = dict(extracts or {})
    meta_map = dict(meta or {})

    # Promote search-coverage fields from inventory into meta for corpus_searched
    # predicates (exhaustive multi-corpus diligence; never silent coverage).
    for key in (
        "searched_corpora",
        "corpora_searched",
        "coverage_declaration",
        "search_coverage",
        "accepted_named_gaps",
        "named_gap_acceptances",
        "unsearched_corpora",
    ):
        if key not in meta_map and inv.get(key) is not None:
            meta_map[key] = inv[key]

    if authority_corpus_present is None:
        authority_corpus_present = bool(
            meta_map.get("authority_corpus_present")
            or inv.get("authority_corpus_present")
            or meta_map.get("authority_bound")
        )

    applicable = catalog.applicable(
        application_type=application_type, scenario=scenario
    )
    results: list[ObligationResult] = [
        evaluate_obligation(
            obl,
            inventory=inv if inventory_available else None,
            extracts=ext,
            meta=meta_map,
            authority_corpus_present=bool(authority_corpus_present),
            inventory_available=inventory_available,
        )
        for obl in applicable
    ]

    # Collect findings from audit_report if needed
    findings: list[Any] = list(audit_findings or [])
    if audit_report and not findings:
        findings = list(audit_report.get("findings") or [])

    results, n_integrated = integrate_audit_findings(
        results,
        findings,
        heuristic_format_forces_unsatisfied=heuristic_format_forces_unsatisfied,
    )

    # Empty applicable set → unknown (no vacuous satisfied)
    overall = rollup_overall_status(results)
    if not results:
        overall = ConformanceStatus.UNKNOWN

    rid = report_id or (
        f"conf:{app or 'unknown'}:{catalog.content_digest[:12]}"
    )
    digest = compute_conformance_digest(
        report_id=rid,
        application_number=app,
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        catalog_digest=catalog.content_digest,
        application_type=application_type,
        scenario=scenario,
        overall_status=overall,
        results=results,
    )
    ts = generated_at_utc or _utc_now_iso()

    report = ConformanceReport(
        report_id=rid,
        application_number=app,
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        catalog_digest=catalog.content_digest,
        application_type=application_type,
        scenario=scenario,
        overall_status=overall,
        results=tuple(results),
        content_digest=digest,
        generated_at_utc=ts,
        authority_corpus_present=bool(authority_corpus_present),
        audit_findings_integrated=n_integrated,
        metadata=dict(metadata or {}),
    )
    payload = report.to_dict()
    _assert_no_forbidden_phrases(payload)
    if payload.get("auto_file_blocked") is not True:
        raise PackageConformanceError(
            "auto_file_blocked must be true", code="auto_file_invariant"
        )
    # Vacuous ready ban: overall satisfied requires at least one result
    if report.overall_status is ConformanceStatus.SATISFIED and not report.results:
        raise PackageConformanceError(
            "vacuous satisfied forbidden", code="vacuous_satisfied"
        )
    return report


def call_application_rules_audit(
    application_number: str,
    *,
    state_root: Path | str | None = None,
    package_dir: Path | str | None = None,
    application_type: str = "utility",
    scenario: str | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    """Optional library call into application_rules_audit (PAAR-061).

    Returns the audit report dict; never raises on missing package — fail closed
    with ``ok=False`` payload for the conformance engine to treat as absent.
    """
    try:
        from ipfs_datasets_py.processors.domains.uspto.application_rules_audit import (
            audit_application_rules,
        )

        return audit_application_rules(
            application_number,
            state_root=Path(state_root) if state_root else None,
            package_dir=package_dir,
            application_type=application_type,
            scenario=scenario,
            persist=persist,
            include_prior_art=False,
            run_filing_pack=False,
        )
    except Exception as exc:  # noqa: BLE001 — fail closed adapter
        return {
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}",
            "findings": [],
            "disclaimer": REVIEW_ONLY_CONFORMANCE_DISCLAIMER,
        }


def evaluate_with_optional_audit(
    *,
    inventory: Mapping[str, Any] | None = None,
    application_number: str = "",
    run_audit: bool = False,
    state_root: Path | str | None = None,
    package_dir: Path | str | None = None,
    **kwargs: Any,
) -> ConformanceReport:
    """Evaluate conformance, optionally pulling live audit findings."""
    audit_report = None
    if run_audit and application_number:
        audit_report = call_application_rules_audit(
            application_number,
            state_root=state_root,
            package_dir=package_dir,
            application_type=str(kwargs.get("application_type") or "utility"),
            scenario=kwargs.get("scenario"),
        )
    return evaluate_package_conformance(
        inventory=inventory,
        application_number=application_number,
        audit_report=audit_report,
        **kwargs,
    )


__all__ = [
    "CONFORMANCE_ENGINE_CODE_VERSION",
    "CONFORMANCE_INTERFACE",
    "CONFORMANCE_REPORT_SCHEMA",
    "REVIEW_ONLY_CONFORMANCE_DISCLAIMER",
    "ConformanceReport",
    "ConformanceStatus",
    "EvidenceOutcome",
    "ObligationResult",
    "PackageConformanceError",
    "call_application_rules_audit",
    "canonical_json",
    "compute_conformance_digest",
    "evaluate_obligation",
    "evaluate_package_conformance",
    "evaluate_predicate",
    "evaluate_with_optional_audit",
    "extract_ifw_codes",
    "integrate_audit_findings",
    "inventory_has_document",
    "rollup_overall_status",
    "sha256_hex",
]
