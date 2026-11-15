"""End-to-end application rules + format audit for Patent Center exports.

Combines:

1. Filing-obligation rule pack inventory (37 C.F.R. / MPEP surfaces)
2. As-filed document completeness (IFW codes present in the export)
3. Format / structure checks on OCR claim/abstract/spec text
   (37 C.F.R. §§ 1.52, 1.71–1.75 style heuristics — review support only)
4. Continuity / priority / status facts from application metadata
5. Latest prior-art compliance status when a run exists

Hard rules
----------
* Not legal advice; not a completeness or patentability certification.
* Never signs, pays, or files.
* OCR-derived format findings are **heuristic** and must be human-reviewed.
* Body text is not written to ordinary logs — only to private report files
  under the operator state root (mode 0600).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    default_state_root,
    utc_now_iso,
)
from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    load_claims_from_exports,
    load_export_temporal_anchors,
    parse_claims_text,
)
from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
    AUDIT_DISCLAIMER,
    audit_submission,
    inventory_package_dir,
    resolve_export_package_dir,
    suggest_filing_scenario,
)

RULES_AUDIT_SCHEMA = "patlaw-application-rules-format-audit-v1"

# Utility new-application expected IFW document codes (minimum set).
_UTILITY_REQUIRED_CODES: Final[tuple[str, ...]] = (
    "CLM",
    "SPEC",
    "ABST",
    "DRW",
    "ADS",
    "OATH",
)
_UTILITY_FEE_CODES = ("IFEE", "WFEE", "N417.PYMT")
_UTILITY_RECEIPT_CODES = ("APP.FILE.REC", "N417", "WELCOME.LET")

_ABSTRACT_MAX_WORDS = 150  # 37 C.F.R. § 1.72(b)
_CLAIM_ANTECEDENT_RE = re.compile(
    r"\b(?:said|the)\s+([a-z][a-z0-9\-]{2,}(?:\s+[a-z][a-z0-9\-]{2,}){0,3})\b",
    re.I,
)
_INDEF_ARTICLE_RE = re.compile(
    r"\b(?:a|an)\s+([a-z][a-z0-9\-]{2,}(?:\s+[a-z][a-z0-9\-]{2,}){0,3})\b",
    re.I,
)


@dataclass
class Finding:
    code: str
    severity: str  # pass | info | warning | error | human_only
    category: str
    message: str
    authority: str = ""
    evidence: str = ""
    auto_filled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "authority": self.authority,
            "evidence": self.evidence,
            "auto_filled": self.auto_filled,
        }


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _discover_extract_text(
    app: str,
    *,
    state_root: Path,
    code_prefix: str,
) -> tuple[str, str | None]:
    """Return (text, source_path) for CLM/SPEC/ABST OCR extracts."""
    graphrag = state_root / "graphrag"
    candidates: list[Path] = []
    if graphrag.is_dir():
        builds = sorted(
            [p for p in graphrag.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for build in builds:
            ext = build / "extracted_text" / app
            if not ext.is_dir():
                continue
            for p in sorted(ext.glob(f"{code_prefix}*.txt")):
                candidates.append(p)
            for p in sorted(ext.glob(f"{app}_{code_prefix}*.txt")):
                candidates.append(p)
    for p in candidates:
        if p.is_file() and p.stat().st_size > 40:
            return _read_text(p), str(p)
    return "", None


def _ifw_codes_present(inventory: Mapping[str, Any]) -> set[str]:
    codes: set[str] = set()
    for f in inventory.get("files") or []:
        if not isinstance(f, Mapping):
            continue
        code = str(f.get("ifw_document_code") or "").strip().upper()
        if code:
            codes.add(code)
        # Also parse from name
        name = str(f.get("name") or "")
        m = re.match(r"^(?:\d{7,8}_)?([A-Za-z0-9.]+)_", name)
        if m:
            codes.add(m.group(1).upper())
    return codes


def check_document_completeness(
    inventory: Mapping[str, Any],
    *,
    application_type: str = "utility",
) -> list[Finding]:
    findings: list[Finding] = []
    codes = _ifw_codes_present(inventory)
    required = _UTILITY_REQUIRED_CODES if application_type == "utility" else _UTILITY_REQUIRED_CODES
    for code in required:
        if code in codes:
            findings.append(
                Finding(
                    code=f"doc_present:{code}",
                    severity="pass",
                    category="completeness",
                    message=f"Required document code {code} present in export.",
                    authority="37 C.F.R. § 1.51 / application contents",
                    evidence=f"IFW code {code}",
                    auto_filled=True,
                )
            )
        else:
            findings.append(
                Finding(
                    code=f"doc_missing:{code}",
                    severity="error",
                    category="completeness",
                    message=f"Required document code {code} not found in export package.",
                    authority="37 C.F.R. § 1.51",
                    evidence="IFW inventory / files",
                )
            )
    if any(c in codes for c in _UTILITY_FEE_CODES):
        findings.append(
            Finding(
                code="fees_present",
                severity="pass",
                category="fees",
                message="Fee / payment-related IFW document(s) present.",
                authority="37 C.F.R. § 1.16",
                evidence=",".join(c for c in _UTILITY_FEE_CODES if c in codes),
                auto_filled=True,
            )
        )
    else:
        findings.append(
            Finding(
                code="fees_missing",
                severity="warning",
                category="fees",
                message="No fee/payment IFW codes detected (IFEE/WFEE/N417.PYMT).",
                authority="37 C.F.R. § 1.16",
            )
        )
    if any(c in codes for c in _UTILITY_RECEIPT_CODES):
        findings.append(
            Finding(
                code="receipt_present",
                severity="pass",
                category="completeness",
                message="Filing receipt / acknowledgment document present.",
                authority="37 C.F.R. § 1.54",
                auto_filled=True,
            )
        )
    if "IDS" in codes or "1449" in codes or "892" in codes:
        findings.append(
            Finding(
                code="ids_present",
                severity="pass",
                category="ids",
                message="IDS or citation list document present in IFW.",
                authority="37 C.F.R. §§ 1.56, 1.97, 1.98",
                auto_filled=True,
            )
        )
    else:
        findings.append(
            Finding(
                code="ids_absent",
                severity="info",
                category="ids",
                message="No IDS/1449/892 document in export (may be OK if no art cited).",
                authority="37 C.F.R. § 1.56",
            )
        )
    return findings


def check_claims_format(claims: Sequence[Mapping[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    if not claims:
        findings.append(
            Finding(
                code="claims_empty",
                severity="error",
                category="format_claims",
                message="No claims parsed for format review.",
                authority="37 C.F.R. § 1.75",
            )
        )
        return findings

    nums = [int(c["claim_number"]) for c in claims]
    findings.append(
        Finding(
            code="claims_count",
            severity="pass",
            category="format_claims",
            message=f"Parsed {len(claims)} claims (numbers {min(nums)}–{max(nums)}).",
            authority="37 C.F.R. § 1.75",
            auto_filled=True,
        )
    )
    missing = [i for i in range(min(nums), max(nums) + 1) if i not in set(nums)]
    if missing:
        findings.append(
            Finding(
                code="claims_numbering_gap",
                severity="warning",
                category="format_claims",
                message=f"Claim numbering gaps detected: {missing} (OCR or parse issue).",
                authority="37 C.F.R. § 1.126",
            )
        )
    else:
        findings.append(
            Finding(
                code="claims_numbering_contiguous",
                severity="pass",
                category="format_claims",
                message="Claim numbers form a contiguous sequence.",
                authority="37 C.F.R. § 1.126",
                auto_filled=True,
            )
        )

    independent = [
        c
        for c in claims
        if not re.search(r"\bof claim\s+\d+\b", str(c.get("claim_text") or ""), re.I)
    ]
    if independent:
        findings.append(
            Finding(
                code="claims_independent_present",
                severity="pass",
                category="format_claims",
                message=(
                    f"{len(independent)} independent claim(s): "
                    f"{[c['claim_number'] for c in independent]}"
                ),
                authority="37 C.F.R. § 1.75",
                auto_filled=True,
            )
        )
    else:
        findings.append(
            Finding(
                code="claims_no_independent",
                severity="error",
                category="format_claims",
                message="No independent claims detected.",
                authority="37 C.F.R. § 1.75",
            )
        )

    for c in claims:
        text = str(c.get("claim_text") or "")
        n = int(c["claim_number"])
        # Period at end (OCR may drop it)
        if text and not re.search(r"[\.\;]\s*$", text):
            findings.append(
                Finding(
                    code=f"claim_{n}_terminal_period",
                    severity="info",
                    category="format_claims",
                    message=f"Claim {n} may lack a terminal period (OCR or format).",
                    authority="37 C.F.R. § 1.75 / claim form practice",
                    evidence=f"claim {n}",
                )
            )
        # Dependent form
        m = re.search(r"\bof claim\s+(\d+)\b", text, re.I)
        if m:
            parent = int(m.group(1))
            if parent >= n:
                findings.append(
                    Finding(
                        code=f"claim_{n}_bad_dependency",
                        severity="error",
                        category="format_claims",
                        message=(
                            f"Claim {n} depends on claim {parent} "
                            f"(parent should be a lower number)."
                        ),
                        authority="37 C.F.R. § 1.75(c)",
                    )
                )
            elif parent not in set(nums):
                findings.append(
                    Finding(
                        code=f"claim_{n}_missing_parent",
                        severity="warning",
                        category="format_claims",
                        message=f"Claim {n} references missing parent claim {parent}.",
                        authority="37 C.F.R. § 1.75(c)",
                    )
                )
        # Very short claim body
        if len(text) < 40:
            findings.append(
                Finding(
                    code=f"claim_{n}_too_short",
                    severity="warning",
                    category="format_claims",
                    message=f"Claim {n} text is very short ({len(text)} chars) — OCR/format risk.",
                    authority="37 C.F.R. § 1.75",
                )
            )

    # Lightweight antecedent heuristic on independent claims only
    for c in independent[:5]:
        text = str(c.get("claim_text") or "")
        n = int(c["claim_number"])
        introduced = {
            m.group(1).lower().strip()
            for m in _INDEF_ARTICLE_RE.finditer(text)
        }
        # "said X" / "the X" where X never introduced with a/an
        suspects = []
        for m in _CLAIM_ANTECEDENT_RE.finditer(text):
            phrase = m.group(1).lower().strip()
            if phrase in introduced:
                continue
            # skip common non-antecedent phrases
            if phrase in {
                "method",
                "system",
                "device",
                "apparatus",
                "invention",
                "group consisting",
            }:
                continue
            # if phrase shares head noun with introduced terms, skip
            head = phrase.split()[-1]
            if any(head == t.split()[-1] for t in introduced):
                continue
            suspects.append(phrase)
        # Cap noise
        if len(suspects) >= 8:
            findings.append(
                Finding(
                    code=f"claim_{n}_antecedent_review",
                    severity="info",
                    category="format_claims",
                    message=(
                        f"Claim {n}: many 'the/said' phrases without clear "
                        f"'a/an' introduction — human antecedent basis review advised "
                        f"(sample: {suspects[:5]})."
                    ),
                    authority="35 U.S.C. § 112(b) / claim clarity practice",
                )
            )
    return findings


def check_abstract_format(abstract_text: str) -> list[Finding]:
    findings: list[Finding] = []
    text = (abstract_text or "").strip()
    if not text:
        findings.append(
            Finding(
                code="abstract_missing_text",
                severity="warning",
                category="format_abstract",
                message="Abstract text not available (OCR extract missing).",
                authority="37 C.F.R. § 1.72(b)",
            )
        )
        return findings
    # Strip common OCR garbage / headers
    lines = [
        ln
        for ln in text.splitlines()
        if re.search(r"[A-Za-z]{3,}", ln)
        and not re.match(r"^\s*\d+\s*$", ln)
    ]
    body = " ".join(" ".join(lines).split())
    # Drop leading boilerplate
    body = re.sub(
        r"(?i)^(abstract|what is claimed|united states patent).{0,40}",
        "",
        body,
    ).strip()
    words = re.findall(r"[A-Za-z0-9']+", body)
    n = len(words)
    if n == 0:
        findings.append(
            Finding(
                code="abstract_empty_after_cleanup",
                severity="warning",
                category="format_abstract",
                message="Abstract OCR cleaned to empty text.",
                authority="37 C.F.R. § 1.72(b)",
            )
        )
        return findings
    if n > _ABSTRACT_MAX_WORDS:
        findings.append(
            Finding(
                code="abstract_over_150_words",
                severity="warning",
                category="format_abstract",
                message=(
                    f"Abstract appears to have ~{n} words "
                    f"(limit {_ABSTRACT_MAX_WORDS} under 37 C.F.R. § 1.72(b); "
                    "verify on official text — OCR may inflate count)."
                ),
                authority="37 C.F.R. § 1.72(b)",
                evidence=f"word_count≈{n}",
            )
        )
    else:
        findings.append(
            Finding(
                code="abstract_word_count_ok",
                severity="pass",
                category="format_abstract",
                message=f"Abstract word count ≈{n} (≤ {_ABSTRACT_MAX_WORDS}).",
                authority="37 C.F.R. § 1.72(b)",
                evidence=f"word_count≈{n}",
                auto_filled=True,
            )
        )
    return findings


def check_spec_format(spec_text: str) -> list[Finding]:
    findings: list[Finding] = []
    text = (spec_text or "").strip()
    if not text or len(text) < 200:
        findings.append(
            Finding(
                code="spec_text_missing",
                severity="warning",
                category="format_spec",
                message="Specification OCR text missing or very short.",
                authority="37 C.F.R. § 1.71",
            )
        )
        return findings
    findings.append(
        Finding(
            code="spec_text_present",
            severity="pass",
            category="format_spec",
            message=f"Specification extract present ({len(text)} chars).",
            authority="37 C.F.R. § 1.71",
            auto_filled=True,
        )
    )
    low = text.lower()
    sections = {
        "background": r"background\s+of\s+the\s+invention|background",
        "summary": r"summary\s+of\s+the\s+invention|summary",
        "brief_description_drawings": r"brief\s+description\s+of\s+(?:the\s+)?drawings",
        "detailed_description": r"detailed\s+description",
    }
    for name, pat in sections.items():
        if re.search(pat, low):
            findings.append(
                Finding(
                    code=f"spec_section_{name}",
                    severity="pass",
                    category="format_spec",
                    message=f"Specification appears to include a '{name}' heading.",
                    authority="37 C.F.R. § 1.77 (preferred arrangement)",
                    auto_filled=True,
                )
            )
        else:
            findings.append(
                Finding(
                    code=f"spec_section_{name}_not_detected",
                    severity="info",
                    category="format_spec",
                    message=(
                        f"Did not detect '{name}' heading in OCR "
                        f"(may still exist — OCR/heading form varies)."
                    ),
                    authority="37 C.F.R. § 1.77",
                )
            )
    # Cross-reference figures
    if re.search(r"\bFIG(?:URE)?\.?\s*\d+", text, re.I):
        findings.append(
            Finding(
                code="spec_figure_refs",
                severity="pass",
                category="format_spec",
                message="Specification contains figure references (FIG. n).",
                authority="37 C.F.R. § 1.84 / drawing practice",
                auto_filled=True,
            )
        )
    return findings


def check_status_and_continuity(
    anchors: Mapping[str, Any],
    application_meta: Mapping[str, Any] | None,
) -> list[Finding]:
    findings: list[Finding] = []
    meta = application_meta or {}
    status = str(
        meta.get("applicationStatusDescriptionText")
        or meta.get("applicationStatusCode")
        or ""
    )
    if status:
        sev = "pass" if re.search(r"patent", status, re.I) else "info"
        findings.append(
            Finding(
                code="application_status",
                severity=sev,
                category="status",
                message=f"Application status: {status}",
                authority="USPTO application meta-data",
                evidence=status,
                auto_filled=True,
            )
        )
        if re.search(r"patent", status, re.I):
            findings.append(
                Finding(
                    code="granted_formal_acceptance",
                    severity="pass",
                    category="status",
                    message=(
                        "Application is patented — USPTO accepted formalities "
                        "sufficient for grant (does not certify every historical "
                        "amendment package)."
                    ),
                    authority="35 U.S.C. grant / issue",
                    auto_filled=True,
                )
            )
    if anchors.get("filing_date"):
        findings.append(
            Finding(
                code="filing_date_known",
                severity="pass",
                category="status",
                message=f"Filing date: {anchors['filing_date']}",
                auto_filled=True,
            )
        )
    if anchors.get("priority_date") and anchors.get("priority_date") != anchors.get(
        "filing_date"
    ):
        findings.append(
            Finding(
                code="priority_date_earlier",
                severity="pass",
                category="priority",
                message=(
                    f"Priority/effective date {anchors['priority_date']} "
                    f"precedes filing {anchors.get('filing_date')}."
                ),
                authority="35 U.S.C. §§ 119/120",
                auto_filled=True,
            )
        )
    patent = str(meta.get("patentNumber") or "").strip()
    if patent:
        findings.append(
            Finding(
                code="patent_number",
                severity="pass",
                category="status",
                message=f"Patent number: {patent}",
                auto_filled=True,
            )
        )
    title = str(meta.get("inventionTitle") or anchors.get("invention_title") or "")
    if title:
        findings.append(
            Finding(
                code="title_present",
                severity="pass",
                category="format_spec",
                message=f"Invention title present ({len(title)} chars).",
                authority="37 C.F.R. § 1.72(a)",
                auto_filled=True,
            )
        )
    return findings


def _load_application_meta(app: str, state_root: Path) -> dict[str, Any]:
    candidates = [
        state_root
        / "exports"
        / app
        / "patent_center_ui"
        / "metadata"
        / "application_data.json",
        state_root
        / "exports"
        / app
        / "patent_center_ui"
        / "package"
        / "application_data.json",
        state_root
        / "exports"
        / app
        / "patent_center_ui"
        / "metadata"
        / "public_application_data.json",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, Mapping):
            meta = data.get("applicationMetaData") or data
            if isinstance(meta, Mapping):
                return dict(meta)
    return {}


def _rollup(findings: Sequence[Finding]) -> str:
    sevs = {f.severity for f in findings}
    if "error" in sevs:
        return "not_ready"
    if "warning" in sevs or "human_only" in sevs:
        return "review_required"
    return "ready"


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        f"# Application rules & format audit — {report.get('application_number')}",
        "",
        f"**Status:** `{report.get('overall_status')}`  ",
        f"**Generated:** {report.get('generated_at_utc')}  ",
        f"**Package:** `{report.get('package_dir')}`  ",
        f"**Scenario:** `{report.get('scenario')}` / stage `{report.get('prosecution_stage')}`",
        "",
        report.get("disclaimer") or AUDIT_DISCLAIMER,
        "",
        "## Summary counts",
        "",
    ]
    counts = report.get("severity_counts") or {}
    for k in ("pass", "info", "warning", "error", "human_only"):
        lines.append(f"- **{k}:** {counts.get(k, 0)}")
    lines.extend(["", "## Findings", ""])
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for f in report.get("findings") or []:
        by_cat.setdefault(str(f.get("category") or "other"), []).append(f)
    for cat in sorted(by_cat):
        lines.append(f"### {cat}")
        lines.append("")
        for f in by_cat[cat]:
            mark = {
                "pass": "✓",
                "info": "ℹ",
                "warning": "⚠",
                "error": "✗",
                "human_only": "👤",
            }.get(str(f.get("severity")), "•")
            auth = f" — _{f.get('authority')}_" if f.get("authority") else ""
            filled = " `[auto]`" if f.get("auto_filled") else ""
            lines.append(
                f"- {mark} **{f.get('code')}** ({f.get('severity')}): "
                f"{f.get('message')}{auth}{filled}"
            )
        lines.append("")
    ap = report.get("action_plan") or []
    if ap:
        lines.extend(["## Action plan", ""])
        for i, step in enumerate(ap, 1):
            lines.append(f"{i}. {step}")
        lines.append("")
    return "\n".join(lines) + "\n"


def audit_application_rules(
    application_number: str,
    *,
    state_root: Path | None = None,
    package_dir: str | Path | None = None,
    application_type: str = "utility",
    scenario: str | None = None,
    run_filing_pack: bool = True,
    include_prior_art: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """Run combined rules + format audit for one application."""
    root = Path(state_root) if state_root is not None else default_state_root()
    app = re.sub(r"\D", "", str(application_number or ""))
    if not app:
        return {"ok": False, "error": "application_number required"}

    pkg = (
        Path(package_dir).expanduser().resolve()
        if package_dir
        else resolve_export_package_dir(app, state_root=root)
    )
    inventory = inventory_package_dir(pkg)
    scen, stage = (
        (scenario, "filing")
        if scenario
        else suggest_filing_scenario(
            app, state_root=root, package_inventory=inventory
        )
    )
    anchors = load_export_temporal_anchors(app, state_root=root)
    meta = _load_application_meta(app, root)

    findings: list[Finding] = []
    findings.extend(check_document_completeness(inventory, application_type=application_type))
    findings.extend(check_status_and_continuity(anchors, meta))

    # Claims
    claims_info = load_claims_from_exports(
        app, state_root=root, max_claims=40, independent_only=False
    )
    claims = list(claims_info.get("claims") or [])
    # Prefer full parse if truncated
    if claims_info.get("source_path"):
        raw_claims = _read_text(Path(str(claims_info["source_path"])))
        full = parse_claims_text(raw_claims)
        if len(full) > len(claims):
            claims = full
    findings.extend(check_claims_format(claims))

    # Abstract / spec extracts
    abst_text, abst_path = _discover_extract_text(app, state_root=root, code_prefix="ABST")
    spec_text, spec_path = _discover_extract_text(app, state_root=root, code_prefix="SPEC")
    findings.extend(check_abstract_format(abst_text))
    findings.extend(check_spec_format(spec_text))

    # Signature always human
    findings.append(
        Finding(
            code="signature_human_only",
            severity="human_only",
            category="signature",
            message="Oath/declaration signature remains a natural-person requirement.",
            authority="35 U.S.C. § 115 / 37 C.F.R. § 1.63",
        )
    )

    filing_pack: dict[str, Any] | None = None
    if run_filing_pack:
        try:
            filing_pack = audit_submission(
                application_number=app,
                state_root=root,
                package_dir=str(pkg) if pkg else None,
                application_type=application_type,
                scenario=scen,
                prosecution_stage=stage,
                persist=False,
                build_ids_queue=False,
            )
            fr = (filing_pack.get("summary") or {}).get("filing_rules") or {}
            for gap in fr.get("evidence_gaps") or []:
                if not isinstance(gap, Mapping):
                    continue
                status = str(gap.get("status") or "")
                sev = {
                    "missing": "error",
                    "human_only": "human_only",
                    "optional_missing": "info",
                }.get(status, "warning")
                findings.append(
                    Finding(
                        code=f"filing_pack:{gap.get('evidence_kind')}:{status}",
                        severity=sev,
                        category="filing_rules",
                        message=str(gap.get("message") or gap.get("evidence_kind")),
                        authority=str(gap.get("rule_id") or ""),
                        evidence=str(gap.get("evidence_kind") or ""),
                    )
                )
            if fr.get("status") == "ready" and not any(
                g.get("status") == "missing" for g in (fr.get("evidence_gaps") or [])
            ):
                findings.append(
                    Finding(
                        code="filing_pack_ready",
                        severity="pass",
                        category="filing_rules",
                        message=(
                            f"Filing-obligation pack status ready "
                            f"({fr.get('matched_count')} rules matched)."
                        ),
                        auto_filled=True,
                    )
                )
            # Prior art from same audit if present
            if include_prior_art:
                pa = (filing_pack.get("summary") or {}).get("prior_art") or {}
                if pa:
                    for code in pa.get("blocking_codes") or []:
                        findings.append(
                            Finding(
                                code=f"prior_art_blocking:{code}",
                                severity="error",
                                category="prior_art",
                                message=f"Prior-art blocking: {code}",
                            )
                        )
                    for code in pa.get("warning_codes") or []:
                        findings.append(
                            Finding(
                                code=f"prior_art_warning:{code}",
                                severity="warning",
                                category="prior_art",
                                message=f"Prior-art warning: {code}",
                            )
                        )
                    if pa.get("status") == "ready":
                        findings.append(
                            Finding(
                                code="prior_art_ready",
                                severity="pass",
                                category="prior_art",
                                message="Prior-art compliance status ready.",
                                auto_filled=True,
                            )
                        )
                    elif pa.get("status"):
                        findings.append(
                            Finding(
                                code="prior_art_status",
                                severity="info",
                                category="prior_art",
                                message=f"Prior-art compliance status: {pa.get('status')}",
                            )
                        )
        except Exception as exc:  # noqa: BLE001
            findings.append(
                Finding(
                    code="filing_pack_error",
                    severity="warning",
                    category="filing_rules",
                    message=f"Filing pack audit failed: {type(exc).__name__}: {exc}",
                )
            )

    # Incorporate gap-closure artifacts (foreign acceptance, family/PCT flags,
    # human diligence confirmations) when present. Never invent legal success.
    gap_closure = None
    foreign_acceptance = None
    try:
        from ipfs_datasets_py.processors.domains.uspto.application_gap_closure import (
            load_foreign_gap_acceptance_for_app,
            load_latest_gap_closure,
        )

        gap_closure = load_latest_gap_closure(app, state_root=root)
        foreign_acceptance = load_foreign_gap_acceptance_for_app(
            app, state_root=root
        )
    except Exception:  # noqa: BLE001
        gap_closure = None
        foreign_acceptance = None

    if foreign_acceptance and foreign_acceptance.get("acknowledger_name"):
        # Downgrade foreign warning → info when operator formally accepted the
        # *named gap* (coverage still NOT claimed).
        for i, f in enumerate(findings):
            if f.code.startswith("prior_art_warning:foreign"):
                findings[i] = Finding(
                    code="prior_art_foreign_gap_accepted",
                    severity="info",
                    category="prior_art",
                    message=(
                        "Foreign-patent corpus remains unsearched; operator "
                        f"accepted named gap "
                        f"({foreign_acceptance.get('acknowledger_name')} @ "
                        f"{foreign_acceptance.get('acknowledged_at_utc')}). "
                        "Does not assert foreign coverage."
                    ),
                    authority="37 C.F.R. §§ 1.56, 1.97 / prior-art diligence",
                    evidence=str(foreign_acceptance.get("package_id") or ""),
                    auto_filled=True,
                )
        findings.append(
            Finding(
                code="foreign_gap_acceptance_on_file",
                severity="pass",
                category="prior_art",
                message=(
                    "Foreign named-gap acceptance on file; gap remains visible; "
                    "EPO OPS live search remains optional."
                ),
                auto_filled=True,
            )
        )

    family = (gap_closure or {}).get("family_pct_isr") or {}
    for ff in family.get("findings") or []:
        if not isinstance(ff, Mapping):
            continue
        code = str(ff.get("code") or "")
        if code == "provisional_title_mismatch":
            findings.append(
                Finding(
                    code="family:provisional_title_mismatch",
                    severity="human_only",
                    category="priority",
                    message=str(ff.get("message") or "Provisional title mismatch"),
                    authority="35 U.S.C. §§ 119/120 / new-matter diligence",
                    evidence=(
                        f"prov={ff.get('provisional_title')!r} "
                        f"subject={ff.get('subject_title')!r}"
                    ),
                )
            )
        elif code == "inventorship_delta_vs_provisional":
            findings.append(
                Finding(
                    code="family:inventorship_delta_vs_provisional",
                    severity="human_only",
                    category="inventorship",
                    message=str(ff.get("message") or "Inventorship delta"),
                    authority="35 U.S.C. § 115",
                    evidence=f"added={ff.get('added_on_subject')}",
                )
            )
        elif code == "isr_wo_evidence_in_export":
            findings.append(
                Finding(
                    code="family:isr_wo_evidence",
                    severity="pass",
                    category="prior_art",
                    message=str(
                        ff.get("message")
                        or "ISR/WO evidence present in export extracts"
                    ),
                    auto_filled=True,
                )
            )
        elif code == "pct_family_member_present":
            findings.append(
                Finding(
                    code="family:pct_member",
                    severity="info",
                    category="priority",
                    message=str(ff.get("message") or "PCT family member present"),
                    auto_filled=True,
                )
            )

    overall = _rollup(findings)
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    action_plan: list[str] = []
    if counts.get("error"):
        action_plan.append(
            "Resolve error-severity completeness/format findings before relying on this audit."
        )
    if any(f.code.startswith("prior_art_warning:foreign") for f in findings):
        action_plan.append(
            "Foreign-patent corpus unsearched — add EPO OPS credentials "
            "(`EPO_OPS_KEY`/`EPO_OPS_SECRET`) or document acceptance of the named gap "
            "via `close_application_gaps.py --accept-foreign-gap`."
        )
    elif any(f.code == "prior_art_foreign_gap_accepted" for f in findings):
        action_plan.append(
            "Foreign named gap accepted (still unsearched). Optional: EPO OPS "
            "live foreign search (`EPO_OPS_KEY`/`EPO_OPS_SECRET` + --live-foreign)."
        )
    if any(f.code.startswith("prior_art_warning:npl") for f in findings):
        action_plan.append(
            "Run NPL search: `check_prior_art.py --live-npl` or accept named NPL gap."
        )
    if any(f.category == "format_claims" and f.severity in {"warning", "error"} for f in findings):
        action_plan.append(
            "Manually verify claim numbering/dependency on the official PDF "
            "(OCR may introduce false positives)."
        )
    if any(f.code == "abstract_over_150_words" for f in findings):
        action_plan.append(
            "Confirm abstract word count on the official abstract (≤150 words)."
        )
    if any(f.code == "family:provisional_title_mismatch" for f in findings):
        action_plan.append(
            "Human: compare provisional vs nonprovisional disclosure for priority "
            "support (title mismatch is a diligence flag, not a legal conclusion)."
        )
    if any(f.code == "family:inventorship_delta_vs_provisional" for f in findings):
        action_plan.append(
            "Human: confirm inventorship listing vs provisional inventor bag."
        )
    action_plan.append(
        "Human-only: signature / inventorship / export-control / new-matter review "
        "remain operator responsibilities unless explicitly confirmed via "
        "close_application_gaps.py --confirm-human-items."
    )
    if re.search(r"patent", str(meta.get("applicationStatusDescriptionText") or ""), re.I):
        action_plan.append(
            "Patented status indicates USPTO accepted formalities for grant; "
            "use this audit for portfolio diligence, not to re-open formalities "
            "without cause."
        )

    report: dict[str, Any] = {
        "schema": RULES_AUDIT_SCHEMA,
        "ok": True,
        "application_number": app,
        "overall_status": overall,
        "package_dir": str(pkg) if pkg else None,
        "scenario": scen,
        "prosecution_stage": stage,
        "application_type": application_type,
        "anchors": dict(anchors),
        "claims": {
            "count": len(claims),
            "numbers": [int(c["claim_number"]) for c in claims],
            "source": claims_info.get("source_path"),
            "independent": [
                int(c["claim_number"])
                for c in claims
                if not re.search(
                    r"\bof claim\s+\d+\b", str(c.get("claim_text") or ""), re.I
                )
            ],
        },
        "extracts": {
            "abstract_path": abst_path,
            "spec_path": spec_path,
            "abstract_chars": len(abst_text or ""),
            "spec_chars": len(spec_text or ""),
        },
        "inventory_summary": {
            "file_count": inventory.get("file_count"),
            "roles_present": inventory.get("roles_present"),
            "evidence_kinds_present": inventory.get("evidence_kinds_present"),
        },
        "findings": [f.to_dict() for f in findings],
        "severity_counts": counts,
        "action_plan": action_plan,
        "filing_pack_status": (
            ((filing_pack or {}).get("summary") or {}).get("filing_rules") or {}
        ).get("status")
        if filing_pack
        else None,
        "prior_art_status": (
            ((filing_pack or {}).get("summary") or {}).get("prior_art") or {}
        ).get("status")
        if filing_pack
        else None,
        "disclaimer": (
            "Application rules/format audit is decision support only — not legal "
            "advice, not a completeness certification, and not a patentability "
            "determination. OCR-based format checks are heuristic. Sign/Pay/Submit "
            "remain human-only."
        ),
        "generated_at_utc": utc_now_iso(),
    }

    # Map auto-filled evidence onto the operator mandatory checklist categories
    # where machine evidence is sufficient to *pre-check* (human may still override).
    from ipfs_datasets_py.processors.domains.uspto.filing_package import (
        default_mandatory_checklist,
    )

    checklist = [item.to_dict() for item in default_mandatory_checklist()]
    auto_map = {
        "check:forms": any(
            f.code.startswith("doc_present:") or f.code == "filing_pack_ready"
            for f in findings
            if f.severity == "pass"
        ),
        "check:fees": any(f.code == "fees_present" for f in findings),
        "check:priority": any(f.code == "priority_date_earlier" for f in findings)
        or bool(anchors.get("priority_date")),
        "check:inventorship": any(f.code == "doc_present:OATH" for f in findings),
        "check:ids": any(f.code == "ids_present" for f in findings),
    }
    now = utc_now_iso()
    for item in checklist:
        iid = str(item.get("item_id") or "")
        if auto_map.get(iid):
            item["confirmed"] = True
            item["confirmed_at_utc"] = now
            item["confirmed_by"] = "auto:application_rules_audit"
            item["labels"] = dict(item.get("labels") or {})
            item["labels"]["auto_source"] = "export_ifw_and_meta"
        # new-matter / nonpublication / export stay human unless gap-closure
        # recorded an explicit acknowledger confirmation.

    # Merge explicit human confirmations from latest gap_closure packs.
    human_conf_by_id: dict[str, Mapping[str, Any]] = {}
    if gap_closure:
        human = gap_closure.get("human_diligence") or {}
        for c in human.get("confirmations") or []:
            if isinstance(c, Mapping) and c.get("item_id") and c.get("confirmed"):
                human_conf_by_id[str(c["item_id"])] = c
        packs = human.get("packs") or {}
        if isinstance(packs, Mapping):
            for pack in packs.values():
                if not isinstance(pack, Mapping):
                    continue
                conf = pack.get("confirmation")
                iid = str(pack.get("item_id") or "")
                if conf and isinstance(conf, Mapping) and conf.get("confirmed") and iid:
                    human_conf_by_id.setdefault(iid, conf)
    for item in checklist:
        iid = str(item.get("item_id") or "")
        conf = human_conf_by_id.get(iid)
        if not conf:
            continue
        item["confirmed"] = True
        item["confirmed_by"] = conf.get("confirmed_by") or "human:gap_closure"
        item["confirmed_at_utc"] = conf.get("confirmed_at_utc") or now
        item["labels"] = dict(item.get("labels") or {})
        item["labels"]["confirmation_source"] = "human_diligence_pack"
        if conf.get("note"):
            item["labels"]["confirmation_note"] = conf.get("note")
    if foreign_acceptance and foreign_acceptance.get("acknowledger_name"):
        for item in checklist:
            if item.get("item_id") == "check:ids":
                item["labels"] = dict(item.get("labels") or {})
                item["labels"]["foreign_gap_accepted"] = True
                item["labels"]["foreign_still_unsearched"] = True

    report["operator_checklist"] = checklist
    report["operator_checklist_auto_confirmed"] = [
        i["item_id"] for i in checklist if i.get("confirmed")
    ]
    report["operator_checklist_still_human"] = [
        i["item_id"]
        for i in checklist
        if not i.get("confirmed") and i.get("requires_human_confirmation")
    ]
    if gap_closure:
        report["gap_closure_dir"] = gap_closure.get("_dir")
    if foreign_acceptance:
        report["foreign_gap_acceptance"] = {
            "acknowledger_name": foreign_acceptance.get("acknowledger_name"),
            "acknowledged_at_utc": foreign_acceptance.get("acknowledged_at_utc"),
            "gap_remains_visible": foreign_acceptance.get("gap_remains_visible"),
            "claims_foreign_coverage": foreign_acceptance.get(
                "claims_foreign_coverage", False
            ),
            "run_id": foreign_acceptance.get("run_id"),
        }

    if persist:
        stamp = utc_now_iso().replace(":", "").replace("-", "")[:15]
        out_dir = root / "compliance_audits" / app / f"rules_format_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = _write_json(out_dir / "application_rules_format_audit.json", report)
        md_path = out_dir / "application_rules_format_audit.md"
        md_path.write_text(render_markdown(report), encoding="utf-8")
        try:
            os.chmod(md_path, 0o600)
        except OSError:
            pass
        checklist_path = _write_json(
            out_dir / "operator_mandatory_checklist.json",
            {
                "schema": "patlaw-operator-mandatory-checklist-v1",
                "application_number": app,
                "generated_at_utc": now,
                "items": checklist,
                "note": (
                    "Auto-confirmed items are pre-checked from export evidence only. "
                    "Human remains responsible for legal accuracy before filing actions."
                ),
            },
        )
        report["paths"] = {
            "json": str(json_path),
            "markdown": str(md_path),
            "checklist": str(checklist_path),
            "dir": str(out_dir),
        }
        # pointer
        try:
            _write_json(
                root / "exports" / "application_rules_format_latest.json",
                {
                    "application_number": app,
                    "overall_status": overall,
                    "paths": report["paths"],
                    "generated_at_utc": report["generated_at_utc"],
                },
            )
        except Exception:
            pass

    return report


__all__ = [
    "RULES_AUDIT_SCHEMA",
    "Finding",
    "audit_application_rules",
    "check_abstract_format",
    "check_claims_format",
    "check_document_completeness",
    "check_spec_format",
    "render_markdown",
]
