"""Audit submission packages for MPEP/CFR filing rules + prior-art coverage.

Operator-facing decision support that unifies:

1. **Filing-obligation rule packs** (baseline pack cites 37 C.F.R. / MPEP /
   statute surfaces for the response scenario)
2. **Package inventory** vs required evidence kinds (amended claims, remarks, …)
3. **Prior-art report / coverage / distinguishability** artifacts from
   ``prior-art search`` runs
4. Optional **public legal hybrid index** hits (MPEP/CFR) for cited rules
5. Local **authority corpus** excerpts when materialized

Hard rules
----------
* Not legal advice; not a completeness certification; not patentability.
* Never signs, pays, or files.
* Failures and gaps remain visible (fail closed on missing priors when claimed).
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioAutomationError,
    default_state_root,
    utc_now_iso,
)

AUDIT_SCHEMA: Final = "patlaw-submission-compliance-audit-v1"
AUDIT_DISCLAIMER: Final = (
    "Submission compliance audit is decision support only — not legal advice, "
    "not a completeness or MPEP-compliance certification, and not a "
    "patentability determination. Filing-obligation packs and authority "
    "excerpts may be incomplete or stale. A natural person must revise "
    "documents and Sign / Pay / Submit in Patent Center."
)

# Attachment filename / role hints → evidence kinds used by the rule pack
_ROLE_HINTS: Final[Mapping[str, tuple[str, ...]]] = {
    "amended_claims": ("claim_amendment", "claims"),
    "claims": ("claim_amendment", "claims"),
    "remarks": ("remarks",),
    "amended_specification": ("specification",),
    "substitute_specification": ("specification",),
    "specification": ("specification",),
    "amended_drawings": ("drawings",),
    "drawings": ("drawings",),
    "declaration": ("oath_declaration",),
    "fee_transmittal": ("fee", "fee_transmittal"),
    "ids": ("ids",),
    "ads": ("ads", "identifier"),
    "abstract": ("specification",),
    "amendment_transmittal": ("amendment_transmittal", "attachment", "form"),
    "evidence": ("evidence",),
    "filing_receipt": ("identifier", "form", "attachment"),
    "application_data": ("identifier", "ads", "form", "attachment"),
}

# USPTO IFW document codes (prefix of export filenames like CLM_xxx.pdf)
_IFW_CODE_ROLES: Final[Mapping[str, str]] = {
    # For as-filed IFW dumps, CLM/SPEC/DRW are original application parts.
    # Evidence-kind mapping still includes claims/specification/drawings via
    # _ROLE_HINTS (amended_* aliases keep OA-response packs working).
    "CLM": "amended_claims",
    "SPEC": "amended_specification",
    "ABST": "abstract",
    "DRW": "amended_drawings",
    "ADS": "ads",
    "OATH": "declaration",
    "IDS": "ids",
    "1449": "ids",
    "892": "ids",
    "IFEE": "fee_transmittal",
    "WFEE": "fee_transmittal",
    "N417.PYMT": "fee_transmittal",
    "N417": "filing_receipt",
    "APP.FILE.REC": "filing_receipt",
    "TRNA": "amendment_transmittal",
    "PA": "application_data",
    "BIB": "application_data",
    "WELCOME.LET": "filing_receipt",
    "NOA": "evidence",
    "CTNF": "evidence",
    "CTFR": "evidence",
    "ISSUE.NTF": "evidence",
    "EGRANT.NTF": "evidence",
    "NTC.PUB": "evidence",
    "REF.OTHER": "ids",
    "PTA.IDS": "ids",
}

_FILENAME_KIND_RE: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # Prefer USPTO IFW-style code_ prefix (CLM_, SPEC_, …)
    (re.compile(r"(?:^|[_/-])CLM(?:[_./-]|\.pdf$)", re.I), "amended_claims"),
    (re.compile(r"(?:^|[_/-])SPEC(?:[_./-]|\.pdf$)", re.I), "amended_specification"),
    (re.compile(r"(?:^|[_/-])ABST(?:[_./-]|\.pdf$)", re.I), "abstract"),
    (re.compile(r"(?:^|[_/-])DRW(?:[_./-]|\.pdf$)", re.I), "amended_drawings"),
    (re.compile(r"(?:^|[_/-])ADS(?:[_./-]|\.pdf$)", re.I), "ads"),
    (re.compile(r"(?:^|[_/-])OATH(?:[_./-]|\.pdf$)", re.I), "declaration"),
    (re.compile(r"(?:^|[_/-])IDS(?:[_./-]|\.pdf$)", re.I), "ids"),
    (re.compile(r"(?:^|[_/-])(?:1449|892)(?:[_./-]|\.pdf$)", re.I), "ids"),
    (re.compile(r"(?:^|[_/-])(?:IFEE|WFEE|N417\.PYMT)(?:[_./-]|\.pdf$)", re.I), "fee_transmittal"),
    (re.compile(r"(?:^|[_/-])(?:APP\.FILE\.REC|N417|WELCOME\.LET)(?:[_./-]|\.pdf$)", re.I), "filing_receipt"),
    (re.compile(r"(?:^|[_/-])TRNA(?:[_./-]|\.pdf$)", re.I), "amendment_transmittal"),
    (re.compile(r"claim", re.I), "amended_claims"),
    (re.compile(r"remark|argument|response", re.I), "remarks"),
    (re.compile(r"spec", re.I), "amended_specification"),
    (re.compile(r"draw", re.I), "amended_drawings"),
    (re.compile(r"ids|information.?disclosure", re.I), "ids"),
    (re.compile(r"fee", re.I), "fee_transmittal"),
    (re.compile(r"declar|oath", re.I), "declaration"),
    (re.compile(r"transmittal", re.I), "amendment_transmittal"),
    (re.compile(r"abstract", re.I), "abstract"),
)


class SubmissionComplianceAuditError(PortfolioAutomationError):
    """Fail-closed submission audit error."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: Mapping[str, Any], *, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise SubmissionComplianceAuditError(
            f"expected JSON object in {path}", code="invalid_json"
        )
    return dict(data)


def _normalize_app(application_number: str) -> str:
    app = re.sub(r"[^0-9A-Za-z]", "", str(application_number or "").strip())
    if not app:
        raise SubmissionComplianceAuditError(
            "application_number is required", code="invalid_application_number"
        )
    return app


def inventory_package_dir(package_dir: Path | str | None) -> dict[str, Any]:
    """List files under a response package directory with role hints.

    Understands both operator draft packages (claim.pdf, remarks.pdf) and
    Patent Center / IFW export filenames (``CLM_*.pdf``, ``SPEC_*.pdf``, …).
    Also merges roles from sibling ``metadata/*_summary.json`` / IFW inventory
    when present next to the package.
    """
    if not package_dir:
        return {
            "package_dir": None,
            "file_count": 0,
            "files": [],
            "roles_present": [],
            "evidence_kinds_present": [],
        }
    root = Path(package_dir).expanduser().resolve()
    if not root.is_dir():
        return {
            "package_dir": str(root),
            "file_count": 0,
            "files": [],
            "roles_present": [],
            "evidence_kinds_present": [],
            "error": "package_dir_missing",
        }
    files: list[dict[str, Any]] = []
    roles: set[str] = set()
    kinds: set[str] = set()
    seen_names: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        # Skip huge graph/json noise in graphrag dirs
        if path.suffix.lower() in {".jsonl"}:
            continue
        if path.name in {
            "export_receipt.json",
            "export_manifest.json",
            "authorization.json",
            "graphrag_receipt.json",
        }:
            continue
        rel = str(path.relative_to(root))
        # De-dupe same basename from package/ vs files/
        key = path.name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        role = _infer_role(path.name)
        code = _ifw_code_from_filename(path.name)
        if role:
            roles.add(role)
            for k in _ROLE_HINTS.get(role, ()):
                kinds.add(k)
        files.append(
            {
                "relative_path": rel,
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "inferred_role": role,
                "ifw_document_code": code,
            }
        )

    # Merge IFW inventory metadata (document codes) when available nearby
    for inv_path in _nearby_ifw_inventories(root):
        for code, desc in _ifw_codes_from_inventory(inv_path):
            role = _IFW_CODE_ROLES.get(code.upper()) or _IFW_CODE_ROLES.get(code)
            if not role:
                # try prefix match for codes like N417.PYMT
                for k, v in _IFW_CODE_ROLES.items():
                    if code.upper().startswith(k):
                        role = v
                        break
            if role:
                roles.add(role)
                for k in _ROLE_HINTS.get(role, ()):
                    kinds.add(k)

    return {
        "package_dir": str(root),
        "file_count": len(files),
        "files": files,
        "roles_present": sorted(roles),
        "evidence_kinds_present": sorted(kinds),
    }


def _ifw_code_from_filename(filename: str) -> str | None:
    """Extract IFW document code from ``CODE_docid.pdf`` or ``app_CODE_docid.pdf``."""
    stem = Path(filename).stem
    # strip leading 8-digit application number prefix from mirrors
    stem = re.sub(r"^\d{7,8}_", "", stem)
    m = re.match(r"^([A-Za-z0-9.]+)_", stem)
    if m:
        return m.group(1)
    return None


def _infer_role(filename: str) -> str | None:
    code = _ifw_code_from_filename(filename)
    if code:
        upper = code.upper()
        if upper in _IFW_CODE_ROLES:
            return _IFW_CODE_ROLES[upper]
        for k, v in _IFW_CODE_ROLES.items():
            if upper.startswith(k):
                return v
    for pattern, role in _FILENAME_KIND_RE:
        if pattern.search(filename):
            return role
    return None


def _nearby_ifw_inventories(package_root: Path) -> list[Path]:
    """Find IFW inventory JSON near an export package directory."""
    candidates: list[Path] = []
    search_roots = [
        package_root,
        package_root.parent,
        package_root.parent / "metadata",
        package_root.parent.parent / "metadata",
    ]
    # messages_correspondence layout
    app_guess = None
    for part in package_root.parts:
        if re.fullmatch(r"\d{7,8}", part):
            app_guess = part
    if app_guess:
        state_exports = package_root
        for _ in range(6):
            if state_exports.name == "exports":
                break
            state_exports = state_exports.parent
        if state_exports.name == "exports":
            search_roots.append(
                state_exports
                / "messages_correspondence"
                / "applications"
                / app_guess
                / "metadata"
            )
            search_roots.append(
                state_exports / app_guess / "patent_center_ui" / "metadata"
            )
    names = (
        "ifw_document_inventory.json",
        "ifw_document_summary.json",
        "correspondence_document_summary.json",
    )
    out: list[Path] = []
    seen: set[str] = set()
    for base in search_roots:
        if not base.is_dir():
            # still allow direct file
            pass
        for name in names:
            p = base / name if base.is_dir() else base
            if base.is_dir():
                p = base / name
            if p.is_file() and str(p) not in seen:
                seen.add(str(p))
                out.append(p)
        if base.is_dir():
            for p in base.glob("**/ifw_document_*.json"):
                if str(p) not in seen:
                    seen.add(str(p))
                    out.append(p)
    return out


def _ifw_codes_from_inventory(path: Path) -> list[tuple[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    codes: list[tuple[str, str]] = []
    docs: list[Any] = []
    if isinstance(data, Mapping):
        if isinstance(data.get("documents"), list):
            docs = list(data["documents"])
        bags = data.get("resultBag") or []
        if isinstance(bags, list):
            for bag in bags:
                if isinstance(bag, Mapping) and isinstance(
                    bag.get("documentBag"), list
                ):
                    docs.extend(bag["documentBag"])
                elif isinstance(bag, Mapping) and bag.get("documentCode"):
                    docs.append(bag)
    elif isinstance(data, list):
        docs = data
    for d in docs:
        if not isinstance(d, Mapping):
            continue
        code = str(d.get("documentCode") or "").strip()
        desc = str(d.get("documentDescription") or "").strip()
        if code:
            codes.append((code, desc))
    return codes


def resolve_export_package_dir(
    application_number: str,
    *,
    state_root: Path | None = None,
) -> Path | None:
    """Pick the best local export folder to audit for an application.

    Preference order:
      1. patent_center_ui/files
      2. patent_center_ui/package
      3. messages_correspondence/applications/<app>/files
      4. public_odp_wrapper
      5. patent_center_ui root
    """
    root = Path(state_root) if state_root is not None else default_state_root()
    app = _normalize_app(application_number)
    exports = root / "exports"
    candidates = [
        exports / app / "patent_center_ui" / "files",
        exports / app / "patent_center_ui" / "package",
        exports / "messages_correspondence" / "applications" / app / "files",
        exports / app / "public_odp_wrapper",
        exports / app / "patent_center_ui",
        exports / app,
    ]
    for path in candidates:
        if path.is_dir() and any(path.rglob("*.pdf")):
            return path.resolve()
    return None


def suggest_filing_scenario(
    application_number: str,
    *,
    state_root: Path | None = None,
    package_inventory: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Heuristic (scenario, prosecution_stage) when operator omits --scenario.

    Baseline pack matches:

    * ``new_application`` only at stage ``filing`` (or ``any``)
    * ``office_action_response`` at stage ``examination``

    Heuristics:

    * As-filed export (CLM+SPEC+ADS) → ``new_application`` / ``filing``
    * Response-style roles (remarks) → ``office_action_response`` / ``examination``
    * Otherwise prefer as-filed completeness review when IFW codes look complete
    """
    root = Path(state_root) if state_root is not None else default_state_root()
    app = re.sub(r"\D", "", str(application_number or ""))
    inv = package_inventory or {}
    roles = set(inv.get("roles_present") or [])
    names = " ".join(
        str(f.get("name") or "")
        for f in (inv.get("files") or [])
        if isinstance(f, Mapping)
    ).upper()
    codes = {
        str(f.get("ifw_document_code") or "").upper()
        for f in (inv.get("files") or [])
        if isinstance(f, Mapping)
    }
    codes.update(
        c
        for c in re.findall(
            r"\b(CLM|SPEC|ADS|OATH|DRW|IDS|ABST|IFEE|NOA|CTNF|CTFR)\b", names
        )
    )

    if "remarks" in roles and "amended_specification" not in roles:
        return "office_action_response", "examination"

    # Full IFW as-filed package → retrospective original-filing audit
    as_filed_markers = {"CLM", "SPEC", "ADS"}
    if as_filed_markers.issubset(codes) or (
        "CLM" in names and "SPEC" in names and "ADS" in names
    ):
        return "new_application", "filing"

    if "remarks" in roles or "amended_claims" in roles:
        return "office_action_response", "examination"

    # Default: original filing completeness (most export dumps)
    return "new_application", "filing"


def _roles_from_revision_attachments(case: Any) -> set[str]:
    roles: set[str] = set()
    for att in getattr(case, "attachments", None) or ():
        if isinstance(att, Mapping):
            role = str(att.get("role") or "").strip()
        else:
            role = str(getattr(att, "role", "") or "").strip()
        if role:
            roles.add(role)
    return roles


def _condition_appears_met(
    conditional_on: str,
    roles: set[str],
    kinds_present: set[str],
) -> bool:
    """Heuristic: whether a rule condition is in play for this package."""
    cond = str(conditional_on or "").strip().lower()
    if not cond:
        return True
    if cond in {"claims_amended", "claim_amendment", "claims_amended_true"}:
        return (
            "amended_claims" in roles
            or "claim_amendment" in kinds_present
            or "claims" in kinds_present
        )
    if cond in {"drawings_amended", "drawing_amendment"}:
        return "amended_drawings" in roles or "drawings" in kinds_present
    if cond in {"specification_amended", "spec_amended"}:
        return (
            "amended_specification" in roles
            or "substitute_specification" in roles
            or "specification" in kinds_present
        )
    # Sequence listing is only required when sequences are disclosed
    if any(
        token in cond
        for token in (
            "sequence",
            "nucleotide",
            "amino_acid",
            "amino-acid",
            "seq_listing",
        )
    ):
        role_blob = " ".join(roles).lower()
        return (
            "sequence_listing" in kinds_present
            or "sequence_listing" in roles
            or "seq" in role_blob
            or "sequence" in role_blob
        )
    # Benefit / priority claim only when asserted
    if any(token in cond for token in ("benefit", "priority", "continuity")):
        role_blob = " ".join(roles).lower()
        return (
            "benefit_claim" in kinds_present
            or "priority" in role_blob
            or "benefit" in role_blob
            or "continuity" in role_blob
        )
    # Unknown conditions: treat as applicable so we don't hide gaps
    return True


def _find_latest_prior_art_run(
    application_number: str,
    *,
    state_root: Path,
) -> Path | None:
    from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
        prior_art_app_dir,
    )

    app_dir = prior_art_app_dir(application_number, state_root=state_root)
    if not app_dir.is_dir():
        return None
    runs = [p for p in app_dir.iterdir() if p.is_dir()]
    if not runs:
        return None
    # Prefer runs with a report, then newest mtime
    def sort_key(p: Path) -> tuple[int, float]:
        has_report = 1 if (p / "prior_art_report.json").is_file() else 0
        return (has_report, p.stat().st_mtime)

    return sorted(runs, key=sort_key, reverse=True)[0]


def load_prior_art_audit_bundle(run_dir: Path | str | None) -> dict[str, Any]:
    """Load prior-art artifacts for compliance binding."""
    if not run_dir:
        return {"present": False, "reason": "no_prior_art_run"}
    root = Path(run_dir).expanduser().resolve()
    if not root.is_dir():
        return {"present": False, "reason": "run_dir_missing", "run_dir": str(root)}

    out: dict[str, Any] = {
        "present": True,
        "run_dir": str(root),
        "run_id": root.name,
        "artifacts": {},
        "coverage_gaps": [],
        "searched_corpora": [],
        "unsearched_corpora": [],
        "named_gaps": [],
        "chart_entry_count": 0,
        "query_count": 0,
        "pps_complete": None,
        "human_ack_present": False,
        "rule_checklist_readiness": None,
        "prior_art_search_complete": None,
    }
    for name in (
        "prior_art_plan.json",
        "prior_art_report.json",
        "search_journal.json",
        "coverage_declaration.json",
        "claim_chart.json",
        "distinguishability_summary.json",
        "distinguishability_matrix.json",
        "pps_verification_checklist.json",
        "human_coverage_acknowledgment.json",
        "prior_art_rule_checklist.json",
        "run_manifest.json",
    ):
        path = root / name
        if path.is_file():
            out["artifacts"][name] = str(path)

    if (root / "coverage_declaration.json").is_file():
        cov = _read_json(root / "coverage_declaration.json")
        out["coverage_id"] = cov.get("declaration_id")
        out["searched_corpora"] = list(cov.get("searched_corpora") or [])
        out["unsearched_corpora"] = list(cov.get("unsearched_corpora") or [])
        out["named_gaps"] = list(cov.get("named_gaps") or [])
        out["coverage_gaps"] = out["named_gaps"]

    if (root / "claim_chart.json").is_file():
        chart = _read_json(root / "claim_chart.json")
        out["chart_entry_count"] = len(chart.get("entries") or [])
        out["plan_gaps"] = chart.get("coverage_gaps") or []

    if (root / "prior_art_plan.json").is_file():
        plan = _read_json(root / "prior_art_plan.json")
        out["query_count"] = len(plan.get("queries") or [])
        out["plan_id"] = plan.get("plan_id")
        out["limitation_count"] = len(plan.get("limitations") or [])

    if (root / "pps_verification_checklist.json").is_file():
        pps = _read_json(root / "pps_verification_checklist.json")
        out["pps_complete"] = bool(pps.get("complete"))
        out["pps_verified_count"] = pps.get("verified_count")
        out["pps_pending_count"] = pps.get("pending_count")

    if (root / "human_coverage_acknowledgment.json").is_file():
        out["human_ack_present"] = True
        out["human_ack"] = _read_json(root / "human_coverage_acknowledgment.json")

    if (root / "prior_art_rule_checklist.json").is_file():
        chk = _read_json(root / "prior_art_rule_checklist.json")
        out["rule_checklist_readiness"] = chk.get("readiness")
        out["prior_art_search_complete"] = chk.get("prior_art_search_complete")
        out["blocking_reason_codes"] = list(chk.get("blocking_reason_codes") or [])

    if (root / "prior_art_report.json").is_file():
        report = _read_json(root / "prior_art_report.json")
        out["report_id"] = report.get("report_id")

    return out


def audit_prior_art_compliance(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Score prior-art readiness from a loaded artifact bundle."""
    findings: list[dict[str, Any]] = []
    blocking: list[str] = []
    warnings: list[str] = []

    if not bundle.get("present"):
        findings.append(
            {
                "code": "prior_art_run_missing",
                "severity": "error",
                "message": (
                    "No prior-art search run found. Run portfolio_cli prior-art search "
                    "before claiming IDS / prior-art coverage."
                ),
            }
        )
        blocking.append("prior_art_run_missing")
        return {
            "status": "not_ready",
            "findings": findings,
            "blocking_codes": blocking,
            "warning_codes": warnings,
            "ids_review_ready": False,
            "coverage_complete": False,
        }

    if not bundle.get("artifacts", {}).get("prior_art_report.json") and not bundle.get(
        "artifacts", {}
    ).get("search_journal.json"):
        findings.append(
            {
                "code": "prior_art_report_missing",
                "severity": "error",
                "message": "Prior-art run lacks report/journal artifacts.",
            }
        )
        blocking.append("prior_art_report_missing")

    unsearched = [str(c) for c in bundle.get("unsearched_corpora") or []]
    named = bundle.get("named_gaps") or []
    if any("foreign" in str(c).lower() for c in unsearched) or any(
        "foreign" in json.dumps(g).lower() for g in named
    ):
        findings.append(
            {
                "code": "foreign_patent_gap",
                "severity": "warning",
                "message": (
                    "Foreign-patent corpus remains a visible gap. Document "
                    "consciously or run --live-foreign / foreign hits before IDS."
                ),
            }
        )
        warnings.append("foreign_patent_gap")

    if any(c.lower() == "npl" or "npl" in str(c).lower() for c in unsearched) or any(
        "npl" in json.dumps(g).lower() for g in named
    ):
        findings.append(
            {
                "code": "npl_gap",
                "severity": "warning",
                "message": (
                    "NPL corpus remains a visible gap. Add licensed/public NPL "
                    "catalog or --live-npl before asserting complete coverage."
                ),
            }
        )
        warnings.append("npl_gap")

    if bundle.get("pps_complete") is False:
        findings.append(
            {
                "code": "pps_verification_incomplete",
                "severity": "warning",
                "message": (
                    "Patent Public Search human verification checklist is incomplete. "
                    "Use prior-art pps-assist / pps-record."
                ),
            }
        )
        warnings.append("pps_verification_incomplete")

    if not bundle.get("human_ack_present"):
        findings.append(
            {
                "code": "human_coverage_ack_missing",
                "severity": "warning",
                "message": (
                    "No human coverage acknowledgment on the prior-art run. "
                    "Use prior-art acknowledge after reviewing gaps."
                ),
            }
        )
        warnings.append("human_coverage_ack_missing")

    if bundle.get("prior_art_search_complete") is False:
        findings.append(
            {
                "code": "prior_art_search_not_complete",
                "severity": "info",
                "message": (
                    "Rule checklist does not claim prior_art_search_complete "
                    "(expected until report + human ack prerequisites hold)."
                ),
            }
        )

    if int(bundle.get("chart_entry_count") or 0) == 0:
        findings.append(
            {
                "code": "empty_claim_chart",
                "severity": "warning",
                "message": (
                    "Claim chart has zero source-linked entries — re-run search "
                    "or broaden queries before distinguishability drafting."
                ),
            }
        )
        warnings.append("empty_claim_chart")

    status = "ready" if not blocking else "not_ready"
    if not blocking and warnings:
        status = "review_required"

    return {
        "status": status,
        "findings": findings,
        "blocking_codes": blocking,
        "warning_codes": warnings,
        "ids_review_ready": not blocking and "human_coverage_ack_missing" not in warnings,
        "coverage_complete": bool(bundle.get("prior_art_search_complete")),
        "run_dir": bundle.get("run_dir"),
        "report_id": bundle.get("report_id"),
        "searched_corpora": bundle.get("searched_corpora") or [],
        "unsearched_corpora": unsearched,
    }


def audit_filing_rules(
    *,
    application_number: str,
    application_type: str = "utility",
    scenario: str = "office_action_response",
    prosecution_stage: str = "examination",
    attached_roles: Sequence[str] = (),
    package_inventory: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve filing-obligation pack and compare to package evidence."""
    from ipfs_datasets_py.processors.domains.uspto.analysis.filing_obligation_processor import (
        FilingObligationProcessor,
        FilingObligationRequest,
        ProsecutionStage,
    )
    from ipfs_datasets_py.processors.domains.uspto.analysis.filing_rule_packs import (
        ApplicationType,
        FilingScenario,
    )
    from ipfs_datasets_py.processors.domains.uspto.contracts import (
        DisclosureClassification,
    )
    from ipfs_datasets_py.processors.domains.uspto.revision_law_guide import (
        _EVIDENCE_TO_ROLES,
    )

    try:
        app_type = ApplicationType(application_type)
    except ValueError:
        app_type = ApplicationType.UTILITY
    try:
        scen = FilingScenario(scenario)
    except ValueError:
        scen = FilingScenario.OFFICE_ACTION_RESPONSE
    try:
        stage = ProsecutionStage(prosecution_stage)
    except ValueError:
        stage = ProsecutionStage.EXAMINATION

    processor = FilingObligationProcessor()
    req = FilingObligationRequest(
        request_id=f"req:audit:{application_number}:{scen.value}",
        application_type=app_type,
        scenario=scen,
        prosecution_stage=stage,
        matter_id=f"matter:{application_number}",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    result = processor.process(req)
    payload = result.to_dict()
    matched = list(payload.get("matched_obligations") or [])

    roles = set(attached_roles or ())
    inv = package_inventory or {}
    roles.update(inv.get("roles_present") or [])
    kinds_present = set(inv.get("evidence_kinds_present") or [])
    for role in roles:
        kinds_present.update(_ROLE_HINTS.get(role, ()))

    evidence_gaps: list[dict[str, Any]] = []
    citations: list[str] = []
    mpep_refs: list[str] = []
    cfr_refs: list[str] = []

    for match in matched:
        rule = match.get("rule") if isinstance(match, Mapping) else None
        if not isinstance(rule, Mapping):
            # Some serializers flatten
            rule = match if isinstance(match, Mapping) else {}
        rule_id = rule.get("rule_id") or match.get("rule_id")
        cite_bags = []
        cite_bags.extend(rule.get("citations") or [])
        cite_bags.extend(rule.get("guidance_citations") or [])
        cite_bags.extend(match.get("citations") or [])
        for cite in cite_bags:
            if isinstance(cite, Mapping):
                text = str(
                    cite.get("citation")
                    or cite.get("citation_text")
                    or cite.get("normalized_text")
                    or cite.get("label")
                    or cite.get("authority_citation")
                    or ""
                )
            else:
                text = str(cite)
            if text:
                citations.append(text)
                low = text.lower()
                if "mpep" in low:
                    mpep_refs.append(text)
                if "c.f.r" in low or "cfr" in low or re.search(r"\b37\b", low):
                    cfr_refs.append(text)
        for ev in rule.get("required_evidence") or []:
            if not isinstance(ev, Mapping):
                continue
            kind = str(ev.get("evidence_kind") or "")
            mandatory = bool(ev.get("mandatory", True))
            conditional_on = str(ev.get("conditional_on") or "").strip()
            # Conditional evidence (e.g. claim_amendment when claims_amended) is
            # only mandatory if the condition appears satisfied by package roles.
            if conditional_on:
                condition_met = _condition_appears_met(conditional_on, roles, kinds_present)
                if not condition_met:
                    # Not applicable — skip as not required for this package
                    continue
            if kind == "signature_presence":
                evidence_gaps.append(
                    {
                        "rule_id": rule_id,
                        "evidence_kind": kind,
                        "mandatory": True,
                        "status": "human_only",
                        "message": "Signature remains a natural-person hard barrier.",
                    }
                )
                continue
            mapped_roles = _EVIDENCE_TO_ROLES.get(kind, ())
            present = kind in kinds_present or any(r in roles for r in mapped_roles)
            if not present and mandatory:
                evidence_gaps.append(
                    {
                        "rule_id": rule_id,
                        "evidence_kind": kind,
                        "mandatory": True,
                        "status": "missing",
                        "expected_roles": list(mapped_roles),
                        "conditional_on": conditional_on or None,
                        "message": (
                            f"Mandatory evidence '{kind}' not found in package "
                            f"(look for roles {list(mapped_roles) or ['(none mapped)']})."
                        ),
                    }
                )
            elif not present:
                evidence_gaps.append(
                    {
                        "rule_id": rule_id,
                        "evidence_kind": kind,
                        "mandatory": False,
                        "status": "optional_missing",
                        "expected_roles": list(mapped_roles),
                        "conditional_on": conditional_on or None,
                    }
                )

    missing_mandatory = [g for g in evidence_gaps if g.get("status") == "missing"]
    status = "ready" if matched and not missing_mandatory else "review_required"
    if not matched:
        status = "not_ready"

    # Operator mandatory categories (IDS, forms, fees, …)
    from ipfs_datasets_py.processors.domains.uspto.filing_package import (
        default_mandatory_checklist,
    )

    checklist = [item.to_dict() for item in default_mandatory_checklist()]

    return {
        "status": status,
        "scenario": scen.value,
        "prosecution_stage": stage.value
        if hasattr(stage, "value")
        else str(stage),
        "application_type": app_type.value,
        "pack_id": payload.get("pack_id"),
        "pack_version": payload.get("pack_version"),
        "matched_rule_ids": payload.get("matched_rule_ids") or [],
        "matched_count": len(matched),
        "coverage_gaps": payload.get("coverage_gaps") or [],
        "reason_codes": payload.get("reason_codes") or [],
        "evidence_gaps": evidence_gaps,
        "missing_mandatory_count": len(missing_mandatory),
        "citations": list(dict.fromkeys(citations)),
        "mpep_citations": list(dict.fromkeys(mpep_refs)),
        "cfr_citations": list(dict.fromkeys(cfr_refs)),
        "roles_present": sorted(roles),
        "evidence_kinds_present": sorted(kinds_present),
        "operator_mandatory_checklist": checklist,
        "disclaimer": payload.get("disclaimer") or AUDIT_DISCLAIMER,
    }


def audit_mpep_authority_surface(
    *,
    citations: Sequence[str],
    state_root: Path | None = None,
    with_law_index: bool = False,
    top_k: int = 4,
) -> dict[str, Any]:
    """Lookup MPEP/CFR citations in local corpus and optional HF hybrid index."""
    from ipfs_datasets_py.processors.domains.uspto.revision_law_guide import (
        default_authority_corpus_roots,
        lookup_authority_excerpt,
    )

    roots = default_authority_corpus_roots(state_root)
    excerpts: list[dict[str, Any]] = []
    for cite in list(citations)[:20]:
        try:
            excerpts.append(lookup_authority_excerpt(str(cite), corpus_roots=roots))
        except Exception as exc:  # noqa: BLE001
            excerpts.append(
                {
                    "citation": cite,
                    "found": False,
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )

    index_hits: list[dict[str, Any]] = []
    index_error: str | None = None
    if with_law_index and citations:
        try:
            from ipfs_datasets_py.processors.domains.uspto.public_legal_index_client import (
                search_public_legal,
            )

            for cite in list(citations)[:8]:
                # Prefer MPEP / 37 CFR flavored queries
                q = str(cite)
                if "mpep" not in q.lower() and re.search(r"\b210\d", q):
                    q = f"MPEP {q}"
                res = search_public_legal(q, top_k=int(top_k))
                for h in (res.get("hits") or [])[:top_k]:
                    index_hits.append(
                        {
                            "query": cite,
                            "document_id": h.get("document_id"),
                            "citation": h.get("citation"),
                            "score": h.get("score"),
                            "excerpt": (h.get("excerpt") or "")[:400],
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            index_error = f"{type(exc).__name__}:{exc}"

    found_local = sum(1 for e in excerpts if e.get("found"))
    return {
        "citation_count": len(citations),
        "local_excerpts_found": found_local,
        "local_excerpts": excerpts,
        "authority_corpus_roots": [str(r) for r in roots],
        "hybrid_index_hits": index_hits,
        "hybrid_index_error": index_error,
        "with_law_index": bool(with_law_index),
    }


# ---------------------------------------------------------------------------
# Action plan + IDS candidates from prior-art runs
# ---------------------------------------------------------------------------


def build_audit_action_plan(
    summary: Mapping[str, Any],
    *,
    application_number: str,
    revision_id: str | None = None,
    prior_art_run_id: str | None = None,
    delta_from: str | None = None,
) -> list[dict[str, Any]]:
    """Translate audit findings into ordered operator next steps (CLI hints)."""
    app = application_number
    rev = revision_id or ""
    run = prior_art_run_id or (summary.get("prior_art_bundle") or {}).get("run_id") or ""
    # Prefer explicit arg, then summary fields (audit_id of *this* run for next re-audit)
    this_audit_id = (
        str(summary.get("audit_id") or "").strip()
        or str(delta_from or "").strip()
        or ""
    )
    actions: list[dict[str, Any]] = []

    prior = summary.get("prior_art") or {}
    filing = summary.get("filing_rules") or {}
    bundle = summary.get("prior_art_bundle") or {}

    if not bundle.get("present") or "prior_art_run_missing" in (
        prior.get("blocking_codes") or []
    ):
        actions.append(
            {
                "priority": 1,
                "code": "run_prior_art_search",
                "title": "Run public prior-art search",
                "command": (
                    f"portfolio_cli prior-art search --application-number {app} "
                    "--claims-file <claims.json> --odp --max-queries 8"
                ),
            }
        )
    else:
        if "foreign_patent_gap" in (prior.get("warning_codes") or []):
            actions.append(
                {
                    "priority": 2,
                    "code": "cover_foreign_patents",
                    "title": "Search or document foreign-patent coverage gap",
                    "command": (
                        f"portfolio_cli prior-art search --application-number {app} "
                        "--claims-file <claims.json> --odp --live-foreign --max-queries 6"
                    ),
                }
            )
        if "npl_gap" in (prior.get("warning_codes") or []):
            actions.append(
                {
                    "priority": 2,
                    "code": "cover_npl",
                    "title": "Search or document NPL coverage gap",
                    "command": (
                        f"portfolio_cli prior-art search --application-number {app} "
                        "--claims-file <claims.json> --live-npl --max-queries 6"
                    ),
                }
            )
        if "pps_verification_incomplete" in (prior.get("warning_codes") or []) or (
            bundle.get("pps_complete") is False
        ):
            assist_cmd = (
                f"portfolio_cli prior-art pps-assist --application-number {app} "
                f"--run-id {run}"
                if run
                else "portfolio_cli prior-art pps-assist --run-dir <run_dir>"
            )
            record_cmd = (
                f"portfolio_cli prior-art pps-record --application-number {app} "
                f"--run-id {run} --verified-by operator:you"
                if run
                else (
                    "portfolio_cli prior-art pps-record --run-dir <run_dir> "
                    "--verified-by operator:you"
                )
            )
            actions.append(
                {
                    "priority": 3,
                    "code": "complete_pps_verification",
                    "title": "Complete Patent Public Search human verification",
                    "command": assist_cmd,
                    "follow_up_command": record_cmd,
                    "notes": (
                        "Attended PPS assist opens the public landing page only; "
                        "it never auto-searches, scrapes, or submits queries. "
                        "Operator pastes queries interactively, then records results."
                    ),
                    "warning_code": "pps_verification_incomplete",
                }
            )
        if "human_coverage_ack_missing" in (prior.get("warning_codes") or []):
            actions.append(
                {
                    "priority": 3,
                    "code": "acknowledge_prior_art_coverage",
                    "title": "Record human prior-art coverage acknowledgment",
                    "command": (
                        f"portfolio_cli prior-art acknowledge --application-number {app} "
                        f"--run-id {run} --acknowledger operator:you"
                        if run
                        else "portfolio_cli prior-art acknowledge --run-dir <run_dir> "
                        "--acknowledger operator:you"
                    ),
                }
            )
        if run:
            actions.append(
                {
                    "priority": 4,
                    "code": "build_ids_queue",
                    "title": "Build IDS candidate queue from prior-art hits (human review)",
                    "command": (
                        f"portfolio_cli prior-art ids-queue --application-number {app} "
                        f"--run-id {run}"
                    ),
                }
            )

    for gap in filing.get("evidence_gaps") or []:
        if gap.get("status") != "missing":
            continue
        kind = gap.get("evidence_kind")
        roles = gap.get("expected_roles") or []
        role = roles[0] if roles else "other"
        if rev:
            cmd = (
                f"portfolio_cli revise attach --revision-id {rev} "
                f"--file <{kind}.pdf> --role {role}"
            )
        else:
            cmd = f"Add package file for evidence '{kind}' (role {role})"
        actions.append(
            {
                "priority": 1,
                "code": f"attach_{kind}",
                "title": f"Attach missing package evidence: {kind}",
                "command": cmd,
                "rule_id": gap.get("rule_id"),
            }
        )

    # Hint next re-audit with --delta-from so closed/opened gaps are measurable
    delta_suffix = (
        f" --delta-from {this_audit_id}" if this_audit_id else ""
    )
    if rev:
        actions.append(
            {
                "priority": 5,
                "code": "re_audit",
                "title": "Re-run compliance audit after fixes (delta vs this audit)",
                "command": (
                    f"portfolio_cli revise audit --revision-id {rev}"
                    f"{delta_suffix}"
                ),
            }
        )
    else:
        actions.append(
            {
                "priority": 5,
                "code": "re_audit",
                "title": "Re-run compliance audit after fixes (delta vs this audit)",
                "command": (
                    f"portfolio_cli audit-submission --application-number {app}"
                    f"{delta_suffix}"
                ),
            }
        )

    if rev:
        actions.append(
            {
                "priority": 9,
                "code": "filing_assist_human",
                "title": "Attended Patent Center assist (YOU Sign/Pay/Submit)",
                "command": (
                    f"portfolio_cli revise filing-assist --revision-id {rev}"
                ),
            }
        )

    actions.sort(key=lambda a: int(a.get("priority") or 99))
    return actions



def build_ids_queue_from_prior_art_run(
    run_dir: str | Path,
    *,
    application_number: str,
    reviewer_id: str = "operator:local",
    max_candidates: int = 40,
    persist: bool = True,
    state_root: Path | None = None,
) -> dict[str, Any]:
    """Build a human IDS review queue from claim-chart / journal hits.

    Never auto-files; all candidates start unreviewed (not IDS-ready).
    """
    from ipfs_datasets_py.processors.domains.patent.ids_review_queue import (
        IdsReferenceCandidate,
        build_ids_review_queue,
        content_digest,
    )
    from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
        SourceLink,
        SourceSpan,
    )

    root = Path(run_dir).expanduser().resolve()
    if not root.is_dir():
        raise SubmissionComplianceAuditError(
            f"prior-art run_dir not found: {root}", code="run_not_found"
        )
    app = _normalize_app(application_number)
    subject_id = f"subject:app-{app}"

    docs: dict[str, dict[str, Any]] = {}

    chart_path = root / "claim_chart.json"
    if chart_path.is_file():
        chart = _read_json(chart_path)
        for entry in chart.get("entries") or []:
            if not isinstance(entry, Mapping):
                continue
            doc_id = str(entry.get("document_id") or "").strip()
            if not doc_id:
                continue
            slot = docs.setdefault(
                doc_id,
                {
                    "document_id": doc_id,
                    "entry_ids": [],
                    "source_links": [],
                    "identifiers": {},
                    "titles": [],
                },
            )
            eid = str(entry.get("entry_id") or "")
            if eid:
                slot["entry_ids"].append(eid)
            for link in entry.get("source_links") or []:
                if isinstance(link, Mapping):
                    slot["source_links"].append(link)
            if entry.get("passage_excerpt"):
                slot["titles"].append(str(entry.get("passage_excerpt"))[:200])

    journal_path = root / "search_journal.json"
    if journal_path.is_file():
        journal = _read_json(journal_path)
        for rec in journal.get("records") or []:
            if not isinstance(rec, Mapping):
                continue
            for hit in rec.get("hits") or []:
                if not isinstance(hit, Mapping):
                    continue
                doc_id = str(hit.get("document_id") or "").strip()
                if not doc_id:
                    continue
                slot = docs.setdefault(
                    doc_id,
                    {
                        "document_id": doc_id,
                        "entry_ids": [],
                        "source_links": [],
                        "identifiers": {},
                        "titles": [],
                    },
                )
                ids = hit.get("identifiers") or {}
                if isinstance(ids, Mapping):
                    slot["identifiers"].update(
                        {str(k): str(v) for k, v in ids.items() if v}
                    )
                for link in hit.get("source_links") or []:
                    if isinstance(link, Mapping):
                        slot["source_links"].append(link)
                meta = hit.get("metadata") or {}
                if isinstance(meta, Mapping) and meta.get("title"):
                    slot["titles"].append(str(meta["title"])[:200])
                if hit.get("passage_excerpt"):
                    slot["titles"].append(str(hit["passage_excerpt"])[:200])

    candidates: list[Any] = []
    for doc_id, slot in list(docs.items())[: int(max_candidates)]:
        links_raw = slot["source_links"][:4]
        links: list[Any] = []
        for link in links_raw:
            try:
                if isinstance(link, Mapping):
                    # Ensure span for SourceLink contract
                    d = dict(link)
                    if not d.get("span"):
                        d["span"] = {"start": 0, "end": 1, "unit": "char"}
                    links.append(SourceLink.from_dict(d))
            except Exception:
                continue
        if not links:
            # Synthetic link so candidate remains source-traceable to the run
            safe = re.sub(r"[^a-zA-Z0-9]", "", doc_id)[:24] or "doc"
            links = [
                SourceLink(
                    source_cid=f"bafybeigids{safe.lower().ljust(20, 'x')[:28]}",
                    artifact_id=f"artifact:ids:{safe}"[:200],
                    span=SourceSpan(start=0, end=1, unit="char"),
                )
            ]
        title = (slot["titles"][0] if slot["titles"] else doc_id)[:200]
        identifiers = dict(slot["identifiers"])
        identifiers.setdefault("document_id", doc_id)
        cand_id = f"ids-cand:{content_digest([doc_id, subject_id])[:16]}"
        try:
            candidates.append(
                IdsReferenceCandidate(
                    candidate_id=cand_id,
                    document_id=doc_id,
                    subject_id=subject_id,
                    chart_cell_ids=tuple(slot["entry_ids"][:8]),
                    source_links=tuple(links),
                    citation_text=title,
                    identifiers=identifiers,
                    metadata={
                        "source": "prior_art_run",
                        "run_dir": str(root),
                        "auto_file_blocked": "true",
                    },
                )
            )
        except Exception:
            continue

    queue = build_ids_review_queue(
        subject_id=subject_id,
        candidates=candidates,
        chart_id=(
            _read_json(chart_path).get("chart_id")
            if chart_path.is_file()
            else None
        ),
        metadata={
            "application_number": app,
            "prior_art_run_dir": str(root),
            "reviewer_id": reviewer_id,
            "built_at_utc": utc_now_iso(),
        },
    )
    payload = queue.to_dict()
    out: dict[str, Any] = {
        "schema": AUDIT_SCHEMA,
        "ok": True,
        "application_number": app,
        "subject_id": subject_id,
        "queue_id": queue.queue_id,
        "candidate_count": len(queue.candidates),
        "auto_file_blocked": True,
        "ids_ready_count": sum(1 for c in queue.candidates if c.is_ids_ready),
        "queue": payload,
        "disclaimer": (
            "IDS candidates require natural-person relevance and materiality "
            "review. Never auto-filed. Not a 37 C.F.R. § 1.56 determination."
        ),
        "generated_at_utc": utc_now_iso(),
    }
    if persist:
        path = _write_json(root / "ids_review_queue.json", payload)
        out["paths"] = {"ids_queue": str(path)}
        # Also under state compliance if state_root given
        if state_root is not None:
            dest = (
                Path(state_root)
                / "ids_queues"
                / app
                / f"{queue.queue_id.replace(':', '_')}.json"
            )
            out["paths"]["ids_queue_state"] = str(_write_json(dest, payload))
    return out


# ---------------------------------------------------------------------------
# Full audit
# ---------------------------------------------------------------------------


@dataclass
class SubmissionAuditResult:
    ok: bool
    audit_id: str
    application_number: str
    overall_status: str
    paths: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    disclaimer: str = AUDIT_DISCLAIMER
    delta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "schema": AUDIT_SCHEMA,
            "ok": self.ok,
            "audit_id": self.audit_id,
            "application_number": self.application_number,
            "overall_status": self.overall_status,
            "paths": dict(self.paths),
            "summary": dict(self.summary),
            "disclaimer": self.disclaimer,
            "generated_at_utc": utc_now_iso(),
        }
        if self.delta is not None:
            out["delta"] = dict(self.delta)
        return out



def audit_submission(
    *,
    application_number: str | None = None,
    revision_id: str | None = None,
    state_root: Path | None = None,
    package_dir: str | Path | None = None,
    prior_art_run_dir: str | Path | None = None,
    prior_art_run_id: str | None = None,
    application_type: str = "utility",
    scenario: str | None = None,
    prosecution_stage: str | None = None,
    with_law_index: bool = False,
    build_ids_queue: bool = True,
    persist: bool = True,
    delta_from: str | None = None,
) -> dict[str, Any]:
    """Run a combined MPEP/filing-rule + prior-art compliance audit.

    When ``delta_from`` is set (previous ``audit_id``, audit directory, or path
    to ``submission_compliance_audit.json``), the new audit includes a
    ``delta`` block with ``closed_gaps``, ``opened_gaps``, and
    ``status_transition``. The prior audit is loaded read-only and is never
    modified (no history rewrite).
    """
    root = Path(state_root) if state_root is not None else default_state_root()
    case = None
    app = ""
    attached_roles: set[str] = set()
    package_path: Path | None = None
    scenario_s = scenario or "office_action_response"
    stage_s = prosecution_stage or "examination"

    if revision_id:
        from ipfs_datasets_py.processors.domains.uspto.revision_response import (
            load_revision_case,
        )
        from ipfs_datasets_py.processors.domains.uspto.revision_law_guide import (
            _trigger_scenario,
        )

        case = load_revision_case(str(revision_id), state_root=root)
        app = case.application_number
        attached_roles = _roles_from_revision_attachments(case)
        if case.package_dir:
            package_path = Path(case.package_dir)
        if not scenario:
            scenario_s, stage_s = _trigger_scenario(case.trigger.kind)

    if application_number:
        app = _normalize_app(application_number)
    elif app:
        app = _normalize_app(app)
    else:
        raise SubmissionComplianceAuditError(
            "pass --application-number or --revision-id",
            code="missing_application_number",
        )

    export_package_auto = False
    if package_dir:
        package_path = Path(package_dir).expanduser().resolve()
    elif package_path is None:
        # Auto-use Patent Center / messages export package when present
        auto = resolve_export_package_dir(app, state_root=root)
        if auto is not None:
            package_path = auto
            export_package_auto = True
    inventory = inventory_package_dir(package_path)

    # Scenario: explicit CLI/API wins; revision trigger next; else infer from
    # export inventory / matter status (as-filed completeness, IDS, issue fee…).
    scenario_auto = False
    if not scenario and case is None:
        scenario_s, inferred_stage = suggest_filing_scenario(
            app, state_root=root, package_inventory=inventory
        )
        scenario_auto = True
        stage_s = prosecution_stage or inferred_stage

    # Baseline audit for re-audit delta (read-only; never rewritten)
    previous_audit_payload: dict[str, Any] | None = None
    previous_audit_id: str | None = None
    previous_audit_path: str | None = None
    delta_from_ref = str(delta_from or "").strip() or None
    if delta_from_ref:
        previous_audit_payload = resolve_compliance_audit(
            audit_id=delta_from_ref,
            application_number=app,
            state_root=root,
        )
        previous_audit_id = str(previous_audit_payload.get("audit_id") or delta_from_ref)
        previous_audit_path = str(previous_audit_payload.get("audit_path") or "")
        # Snapshot prior summary before any new writes (immutability guard)
        previous_summary_snapshot = dict(previous_audit_payload.get("summary") or {})
    else:
        previous_summary_snapshot = {}

    # Prior-art run resolution
    pa_dir: Path | None = None
    if prior_art_run_dir:
        pa_dir = Path(prior_art_run_dir).expanduser().resolve()
    elif prior_art_run_id:
        from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
            prior_art_app_dir,
        )

        pa_dir = prior_art_app_dir(app, state_root=root) / prior_art_run_id
    else:
        pa_dir = _find_latest_prior_art_run(app, state_root=root)

    prior_bundle = load_prior_art_audit_bundle(pa_dir)
    prior_audit = audit_prior_art_compliance(prior_bundle)

    filing_audit = audit_filing_rules(
        application_number=app,
        application_type=application_type,
        scenario=scenario_s,
        prosecution_stage=stage_s,
        attached_roles=sorted(attached_roles),
        package_inventory=inventory,
    )

    # Authority surface: pack citations + letter citations
    citations = list(filing_audit.get("mpep_citations") or [])
    citations.extend(filing_audit.get("cfr_citations") or [])
    if case is not None:
        from ipfs_datasets_py.processors.domains.uspto.revision_law_guide import (
            collect_citations_from_case,
        )

        citations.extend(collect_citations_from_case(case))
    # Always include core response authorities
    citations.extend(
        [
            "37 C.F.R. § 1.121",
            "37 C.F.R. § 1.111",
            "37 C.F.R. § 1.56",
            "MPEP § 714",
            "MPEP § 707",
            "MPEP § 2106",
        ]
    )
    citations = list(dict.fromkeys(str(c) for c in citations if str(c).strip()))

    authority = audit_mpep_authority_surface(
        citations=citations,
        state_root=root,
        with_law_index=with_law_index,
    )

    # Overall rollup
    statuses = [prior_audit.get("status"), filing_audit.get("status")]
    if "not_ready" in statuses:
        overall = "not_ready"
    elif "review_required" in statuses:
        overall = "review_required"
    else:
        overall = "ready"

    review_tips = [
        "Confirm every mandatory evidence gap is addressed in the response package.",
        "Review foreign/NPL prior-art gaps before IDS and remarks on art.",
        "Use distinguishability_matrix / claim chart only as drafting aids — "
        "not patentability conclusions.",
        "Sign / Pay / Submit remain human-only in Patent Center.",
        "Verify critical MPEP/CFR text against official USPTO/eCFR sources.",
    ]
    if prior_audit.get("blocking_codes"):
        review_tips.insert(
            0,
            "Prior-art blocking issues must be resolved before claiming coverage complete.",
        )
    if filing_audit.get("missing_mandatory_count"):
        review_tips.insert(
            0,
            f"{filing_audit['missing_mandatory_count']} mandatory filing-evidence "
            "item(s) appear missing from the package.",
        )
    found_excerpts = int(authority.get("local_excerpts_found") or 0)
    if found_excerpts > 0:
        review_tips.append(
            f"{found_excerpts} local MPEP/CFR authority excerpt(s) attached — "
            "verify against official USPTO/eCFR before relying on fixture text."
        )
    else:
        review_tips.append(
            "No local authority excerpts resolved; seed authority_corpus "
            "(PATLAW-199) or set USPTO_AUTHORITY_CORPUS_ROOT for offline cites."
        )

    # Microsecond stamp keeps concurrent / same-second re-audits from colliding
    # and overwriting prior history under the same directory.
    _stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    audit_id = f"audit:{app}:{_stamp}"
    # Extremely unlikely same-us collision: extend rather than overwrite
    _candidate_dir = root / "compliance_audits" / app / audit_id.replace(":", "_")
    if persist and _candidate_dir.exists():
        audit_id = f"audit:{app}:{_stamp}{secrets.token_hex(3)}"

    summary = {
        "schema": AUDIT_SCHEMA,
        "audit_id": audit_id,
        "application_number": app,
        "revision_id": getattr(case, "revision_id", None) if case else revision_id,
        "overall_status": overall,
        "delta_from": previous_audit_id,
        "package_dir": str(package_path) if package_path else None,
        "package_auto_resolved_from_exports": export_package_auto,
        "scenario": scenario_s,
        "scenario_auto_selected": scenario_auto,
        "filing_rules": filing_audit,
        "prior_art": prior_audit,
        "prior_art_bundle": {
            k: prior_bundle.get(k)
            for k in (
                "present",
                "run_dir",
                "run_id",
                "report_id",
                "plan_id",
                "chart_entry_count",
                "query_count",
                "pps_complete",
                "pps_pending_count",
                "pps_verified_count",
                "pps_item_count",
                "human_ack_present",
                "artifacts",
            )
        },
        "package_inventory": inventory,
        "mpep_authority": {
            "citation_count": authority.get("citation_count"),
            "local_excerpts_found": authority.get("local_excerpts_found"),
            "hybrid_index_hit_count": len(authority.get("hybrid_index_hits") or []),
            "hybrid_index_error": authority.get("hybrid_index_error"),
            "authority_corpus_roots": authority.get("authority_corpus_roots") or [],
            "sample_excerpts": (authority.get("local_excerpts") or [])[:6],
            "sample_citations": [
                str(e.get("citation"))
                for e in (authority.get("local_excerpts") or [])
                if e.get("found") and e.get("citation")
            ][:8],
            "sample_index_hits": (authority.get("hybrid_index_hits") or [])[:6],
        },
        "review_tips": review_tips,
        "hard_barriers": {
            "sign": "human_only",
            "pay": "human_only",
            "submit": "human_only",
        },
        "disclaimer": AUDIT_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }

    # IDS candidate queue from prior-art hits (human review only)
    ids_info: dict[str, Any] | None = None
    if build_ids_queue and prior_bundle.get("present") and pa_dir is not None:
        try:
            ids_info = build_ids_queue_from_prior_art_run(
                pa_dir,
                application_number=app,
                persist=persist,
                state_root=root if persist else None,
            )
        except Exception as exc:  # noqa: BLE001
            ids_info = {
                "ok": False,
                "error": f"{type(exc).__name__}:{exc}",
                "candidate_count": 0,
            }
    summary["ids_queue"] = {
        "ok": bool(ids_info and ids_info.get("ok")),
        "queue_id": (ids_info or {}).get("queue_id"),
        "candidate_count": (ids_info or {}).get("candidate_count") or 0,
        "auto_file_blocked": True,
        "paths": (ids_info or {}).get("paths") or {},
        "error": (ids_info or {}).get("error"),
    }

    action_plan = build_audit_action_plan(
        summary,
        application_number=app,
        revision_id=getattr(case, "revision_id", None) if case else revision_id,
        prior_art_run_id=prior_bundle.get("run_id"),
        delta_from=previous_audit_id,
    )
    summary["action_plan"] = action_plan
    summary["action_plan_count"] = len(action_plan)

    # Re-audit delta vs previous audit_id (new audit only; history stays intact)
    delta: dict[str, Any] | None = None
    if previous_audit_payload is not None:
        delta = compute_audit_delta(
            previous_summary_snapshot,
            summary,
            previous_audit_id=previous_audit_id,
            current_audit_id=audit_id,
        )
        delta["previous_audit_path"] = previous_audit_path
        delta["history_rewritten"] = False
        summary["delta"] = delta
        # Operator tip for measurable gap closure
        closed_n = int(delta.get("closed_gap_count") or 0)
        opened_n = int(delta.get("opened_gap_count") or 0)
        st = delta.get("status_transition") or {}
        review_tips.insert(
            0,
            (
                f"Re-audit delta vs {previous_audit_id}: "
                f"{closed_n} closed, {opened_n} opened; "
                f"status {st.get('from') or '—'} → {st.get('to') or '—'}."
            ),
        )
        summary["review_tips"] = review_tips

    paths: dict[str, str] = {}
    if persist:
        out_dir = root / "compliance_audits" / app / audit_id.replace(":", "_")
        paths["audit"] = str(
            _write_json(out_dir / "submission_compliance_audit.json", summary)
        )
        paths["authority"] = str(
            _write_json(out_dir / "mpep_authority_surface.json", authority)
        )
        paths["filing_rules"] = str(
            _write_json(out_dir / "filing_rules_audit.json", filing_audit)
        )
        paths["prior_art"] = str(
            _write_json(out_dir / "prior_art_audit.json", prior_audit)
        )
        paths["action_plan"] = str(
            _write_json(out_dir / "action_plan.json", {"actions": action_plan})
        )
        if delta is not None:
            paths["delta"] = str(
                _write_json(out_dir / "re_audit_delta.json", delta)
            )
        if ids_info and ids_info.get("ok"):
            paths["ids_queue"] = str(
                _write_json(
                    out_dir / "ids_review_queue.json",
                    ids_info.get("queue") or {},
                )
            )
            # Keep copy under prior-art run as well (already written by builder)
            if (ids_info.get("paths") or {}).get("ids_queue"):
                paths["ids_queue_run"] = ids_info["paths"]["ids_queue"]
        # Human-readable markdown report
        try:
            md = render_audit_markdown(summary)
            md_path = out_dir / "submission_compliance_audit.md"
            md_path.write_text(md, encoding="utf-8")
            try:
                os.chmod(md_path, 0o600)
            except OSError:
                pass
            paths["markdown"] = str(md_path)
        except Exception:
            pass
        # Attach pointer on revision case when present
        if case is not None and getattr(case, "case_dir", None):
            case_dir = Path(case.case_dir)
            pointer = {
                "schema": AUDIT_SCHEMA,
                "audit_id": audit_id,
                "audit_path": paths["audit"],
                "markdown_path": paths.get("markdown"),
                "overall_status": overall,
                "action_plan_count": len(action_plan),
                "ids_candidate_count": summary["ids_queue"].get("candidate_count"),
                "delta_from": previous_audit_id,
                "closed_gap_count": (delta or {}).get("closed_gap_count"),
                "opened_gap_count": (delta or {}).get("opened_gap_count"),
                "attached_at_utc": utc_now_iso(),
                "disclaimer": AUDIT_DISCLAIMER,
            }
            paths["revision_pointer"] = str(
                _write_json(case_dir / "submission_compliance_audit.json", pointer)
            )

        # Immutability check: previous audit file must still match snapshot
        if previous_audit_path:
            prior_path = Path(previous_audit_path)
            if prior_path.is_file():
                try:
                    reread = _read_json(prior_path)
                    if reread != previous_summary_snapshot:
                        raise SubmissionComplianceAuditError(
                            "re-audit mutated prior audit history "
                            f"({previous_audit_path})",
                            code="history_rewrite_detected",
                        )
                except SubmissionComplianceAuditError:
                    raise
                except Exception:
                    pass

    result = SubmissionAuditResult(
        ok=True,
        audit_id=audit_id,
        application_number=app,
        overall_status=overall,
        paths=paths,
        summary=summary,
        delta=delta,
    )
    return result.to_dict()



def list_compliance_audits(
    *,
    application_number: str | None = None,
    state_root: Path | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List recent compliance audits under the portfolio state tree."""
    root = Path(state_root) if state_root is not None else default_state_root()
    base = root / "compliance_audits"
    rows: list[dict[str, Any]] = []
    if not base.is_dir():
        return {
            "schema": AUDIT_SCHEMA,
            "ok": True,
            "count": 0,
            "audits": [],
            "disclaimer": AUDIT_DISCLAIMER,
        }
    app_filter = (
        _normalize_app(application_number) if application_number else None
    )
    for app_dir in sorted(base.iterdir()):
        if not app_dir.is_dir():
            continue
        if app_filter and app_dir.name != app_filter:
            continue
        for audit_dir in sorted(app_dir.iterdir(), reverse=True):
            man = audit_dir / "submission_compliance_audit.json"
            if not man.is_file():
                continue
            try:
                payload = _read_json(man)
            except Exception:
                payload = {}
            rows.append(
                {
                    "application_number": app_dir.name,
                    "audit_dir": str(audit_dir),
                    "audit_path": str(man),
                    "overall_status": payload.get("overall_status"),
                    "revision_id": payload.get("revision_id"),
                    "generated_at_utc": payload.get("generated_at_utc"),
                    "action_plan_count": payload.get("action_plan_count")
                    or len(payload.get("action_plan") or []),
                    "ids_candidates": (payload.get("ids_queue") or {}).get(
                        "candidate_count"
                    ),
                }
            )
            if len(rows) >= int(limit):
                break
        if len(rows) >= int(limit):
            break
    return {
        "schema": AUDIT_SCHEMA,
        "ok": True,
        "count": len(rows),
        "audits": rows,
        "disclaimer": AUDIT_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }


def show_compliance_audit(
    *,
    application_number: str | None = None,
    audit_path: str | Path | None = None,
    audit_dir: str | Path | None = None,
    state_root: Path | None = None,
    write_markdown: bool = True,
) -> dict[str, Any]:
    """Load latest (or specified) audit and optionally write a markdown report."""
    if audit_path:
        path = Path(audit_path).expanduser().resolve()
    elif audit_dir:
        path = Path(audit_dir).expanduser().resolve() / "submission_compliance_audit.json"
    else:
        listed = list_compliance_audits(
            application_number=application_number,
            state_root=state_root,
            limit=1,
        )
        if not listed["audits"]:
            raise SubmissionComplianceAuditError(
                "no compliance audits found", code="audit_not_found"
            )
        path = Path(listed["audits"][0]["audit_path"])

    if not path.is_file():
        raise SubmissionComplianceAuditError(
            f"audit not found: {path}", code="audit_not_found"
        )
    summary = _read_json(path)
    md_path = None
    if write_markdown:
        md = render_audit_markdown(summary)
        md_path = path.with_name("submission_compliance_audit.md")
        md_path.write_text(md, encoding="utf-8")
        try:
            os.chmod(md_path, 0o600)
        except OSError:
            pass

    return {
        "schema": AUDIT_SCHEMA,
        "ok": True,
        "audit_path": str(path),
        "markdown_path": str(md_path) if md_path else None,
        "overall_status": summary.get("overall_status"),
        "application_number": summary.get("application_number"),
        "revision_id": summary.get("revision_id"),
        "action_plan": summary.get("action_plan") or [],
        "ids_queue": summary.get("ids_queue") or {},
        "filing_missing_mandatory": (
            (summary.get("filing_rules") or {}).get("missing_mandatory_count")
        ),
        "prior_art_status": (summary.get("prior_art") or {}).get("status"),
        "summary": summary,
        "disclaimer": AUDIT_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }


def render_audit_markdown(summary: Mapping[str, Any]) -> str:
    """Render a human-readable compliance audit report."""
    lines: list[str] = [
        "# Submission compliance audit",
        "",
        str(summary.get("disclaimer") or AUDIT_DISCLAIMER),
        "",
        f"- **Application:** `{summary.get('application_number')}`",
        f"- **Audit id:** `{summary.get('audit_id') or '—'}`",
        f"- **Revision:** `{summary.get('revision_id') or '—'}`",
        f"- **Overall status:** **{summary.get('overall_status')}**",
        f"- **Generated:** {summary.get('generated_at_utc')}",
    ]
    if summary.get("delta_from"):
        lines.append(f"- **Delta from:** `{summary.get('delta_from')}`")
    lines.extend(
        [
            "",
            "## Filing rules (MPEP / CFR pack)",
            "",
        ]
    )
    fr = summary.get("filing_rules") or {}
    lines.extend(
        [
            f"- Status: `{fr.get('status')}`",
            f"- Scenario: `{fr.get('scenario')}` / stage `{fr.get('prosecution_stage')}`",
            f"- Matched rules: **{fr.get('matched_count')}**",
            f"- Missing mandatory evidence: **{fr.get('missing_mandatory_count')}**",
            f"- CFR cites: {', '.join(fr.get('cfr_citations') or []) or '—'}",
            f"- MPEP cites: {', '.join(fr.get('mpep_citations') or []) or '—'}",
            f"- Roles present: {', '.join(fr.get('roles_present') or []) or '—'}",
            "",
            "### Evidence gaps",
            "",
        ]
    )
    gaps = fr.get("evidence_gaps") or []
    if not gaps:
        lines.append("_None_")
    else:
        for g in gaps[:30]:
            lines.append(
                f"- `{g.get('status')}` **{g.get('evidence_kind')}** "
                f"(rule `{g.get('rule_id')}`) — {g.get('message') or ''}"
            )

    pa = summary.get("prior_art") or {}
    lines.extend(
        [
            "",
            "## Prior-art coverage",
            "",
            f"- Status: `{pa.get('status')}`",
            f"- Blocking: {', '.join(pa.get('blocking_codes') or []) or '—'}",
            f"- Warnings: {', '.join(pa.get('warning_codes') or []) or '—'}",
            f"- Searched: {', '.join(pa.get('searched_corpora') or []) or '—'}",
            f"- Unsearched: {', '.join(pa.get('unsearched_corpora') or []) or '—'}",
            "",
            "## IDS candidates",
            "",
        ]
    )
    iq = summary.get("ids_queue") or {}
    lines.append(
        f"- Queue ok: `{iq.get('ok')}` — candidates **{iq.get('candidate_count') or 0}** "
        f"(auto-file blocked)"
    )

    lines.extend(["", "## Action plan", ""])
    plan = summary.get("action_plan") or []
    if not plan:
        lines.append("_No actions_")
    else:
        for i, a in enumerate(plan, 1):
            lines.append(
                f"{i}. **{a.get('title')}** (`{a.get('code')}`)\n"
                f"   `{a.get('command')}`"
            )

    tips = summary.get("review_tips") or []
    if tips:
        lines.extend(["", "## Review tips", ""])
        for t in tips:
            lines.append(f"- {t}")

    # Re-audit delta (closed / opened gaps vs previous audit_id)
    delta = summary.get("delta")
    if isinstance(delta, Mapping) and (
        delta.get("previous_audit_id")
        or delta.get("delta_from")
        or delta.get("closed_gaps") is not None
    ):
        st = delta.get("status_transition") or {}
        lines.extend(
            [
                "",
                "## Re-audit delta",
                "",
                f"- Baseline audit: `{delta.get('previous_audit_id') or delta.get('delta_from') or '—'}`",
                f"- Status transition: "
                f"`{st.get('from') or '—'}` → `{st.get('to') or '—'}`"
                f" (changed={st.get('changed')})",
                f"- Closed gaps: **{delta.get('closed_gap_count') or 0}**",
                f"- Opened gaps: **{delta.get('opened_gap_count') or 0}**",
                f"- Unchanged gaps: **{delta.get('unchanged_gap_count') or 0}**",
                f"- History rewritten: `{bool(delta.get('history_rewritten'))}`",
                "",
                "### Closed gaps",
                "",
            ]
        )
        closed = list(delta.get("closed_gaps") or [])
        if not closed:
            lines.append("_None_")
        else:
            for g in closed[:40]:
                lines.append(
                    f"- `{g.get('gap_id')}` — {g.get('code')} "
                    f"({g.get('severity')})"
                )
        lines.extend(["", "### Opened gaps", ""])
        opened = list(delta.get("opened_gaps") or [])
        if not opened:
            lines.append("_None_")
        else:
            for g in opened[:40]:
                lines.append(
                    f"- `{g.get('gap_id')}` — {g.get('code')} "
                    f"({g.get('severity')})"
                )

    # Local MPEP/CFR authority excerpts (decision support; not binding law).
    auth = summary.get("mpep_authority") or {}
    lines.extend(
        [
            "",
            "## MPEP / CFR authority excerpts",
            "",
            f"- Local excerpts found: **{auth.get('local_excerpts_found') or 0}** "
            f"(of {auth.get('citation_count') or 0} citations scanned)",
            f"- Hybrid index hits: **{auth.get('hybrid_index_hit_count') or 0}**",
            "",
            "### Sample citations",
            "",
        ]
    )
    samples = list(auth.get("sample_excerpts") or [])
    found_samples = [s for s in samples if s.get("found")]
    # Prefer found excerpts; fall back to any samples so the section is never empty
    # when citations were collected.
    display = found_samples or samples
    if not display:
        # Surface pack citation lists so operators still see what was audited.
        pack_cites: list[str] = []
        pack_cites.extend(fr.get("cfr_citations") or [])
        pack_cites.extend(fr.get("mpep_citations") or [])
        if pack_cites:
            for cite in pack_cites[:12]:
                lines.append(f"- `{cite}` — _no local excerpt resolved_")
        else:
            lines.append(
                "_No local authority excerpts resolved. Seed "
                "`authority_corpus/` (PATLAW-199) or set "
                "`USPTO_AUTHORITY_CORPUS_ROOT`._"
            )
    else:
        for s in display[:8]:
            cite = s.get("citation") or "—"
            if s.get("found"):
                excerpt = (s.get("excerpt") or "").strip().replace("\n", " ")
                if len(excerpt) > 280:
                    excerpt = excerpt[:277] + "…"
                path = s.get("path") or ""
                path_bit = f" (`{path}`)" if path else ""
                lines.append(f"- **{cite}**{path_bit}")
                if excerpt:
                    lines.append(f"  > {excerpt}")
            else:
                err = s.get("error") or s.get("hint") or "not found locally"
                lines.append(f"- `{cite}` — _{err}_")
    if auth.get("hybrid_index_error"):
        lines.append(f"- Hybrid index error: `{auth.get('hybrid_index_error')}`")

    lines.extend(
        [
            "",
            "## Hard barriers",
            "",
            "- Sign / Pay / Submit: **human only** (Patent Center)",
            "",
            "_Authority excerpts are decision support only — verify against "
            "official USPTO / eCFR sources. MPEP guidance never elevates to "
            "binding law._",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "AUDIT_DISCLAIMER",
    "AUDIT_SCHEMA",
    "SubmissionAuditResult",
    "SubmissionComplianceAuditError",
    "audit_filing_rules",
    "audit_mpep_authority_surface",
    "audit_prior_art_compliance",
    "audit_submission",
    "build_audit_action_plan",
    "build_ids_queue_from_prior_art_run",
    "inventory_package_dir",
    "list_compliance_audits",
    "load_prior_art_audit_bundle",
    "render_audit_markdown",
    "resolve_compliance_audit",
    "resolve_export_package_dir",
    "show_compliance_audit",
    "suggest_filing_scenario",
]


__all__ = ['AUDIT_DISCLAIMER', 'AUDIT_SCHEMA', 'SubmissionAuditResult', 'SubmissionComplianceAuditError', 'audit_filing_rules', 'audit_mpep_authority_surface', 'audit_prior_art_compliance', 'audit_submission', 'build_audit_action_plan', 'build_ids_queue_from_prior_art_run', 'inventory_package_dir', 'list_compliance_audits', 'load_prior_art_audit_bundle', 'render_audit_markdown', 'resolve_compliance_audit', 'resolve_export_package_dir', 'show_compliance_audit', 'suggest_filing_scenario']


def evaluate_pps_checklist_completeness(
    checklist: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate human PPS verification checklist completeness (fail-closed).

    Matches ``record_pps_verification``: complete only when there are no
    pending items and at least one verified item. Explicit ``complete=False``
    always remains incomplete; explicit ``complete=True`` is accepted only when
    no pending items remain (stale flags with pending items fail closed).

    Incomplete checklists (including fresh all-pending artifacts) yield
    ``complete=False`` so audits emit ``pps_verification_incomplete`` and
    action plans include a ``complete_pps_verification`` step.
    """
    if not checklist:
        return {
            "present": False,
            "complete": None,
            "item_count": 0,
            "pending_count": 0,
            "verified_count": 0,
            "derived_complete": False,
        }
    items = list(checklist.get("items") or [])
    if items:
        pending = sum(
            1
            for it in items
            if str(it.get("status") or "pending").strip().lower() == "pending"
        )
        verified = sum(
            1
            for it in items
            if str(it.get("status") or "").strip().lower() == "verified"
        )
    else:
        try:
            pending = int(checklist.get("pending_count") or 0)
        except (TypeError, ValueError):
            pending = 0
        try:
            verified = int(checklist.get("verified_count") or 0)
        except (TypeError, ValueError):
            verified = 0
    item_count = int(checklist.get("item_count") or len(items) or 0)
    # Canonical rule used by prior_art_operator_extensions.record_pps_verification
    derived_complete = pending == 0 and verified > 0
    explicit = checklist.get("complete")
    if pending > 0:
        complete = False
    elif explicit is True:
        # Accept operator-marked complete when nothing remains pending.
        complete = True if verified > 0 or item_count == 0 else derived_complete
    elif explicit is False:
        complete = False
    else:
        complete = derived_complete
    return {
        "present": True,
        "complete": bool(complete),
        "item_count": item_count,
        "pending_count": pending,
        "verified_count": verified,
        "derived_complete": derived_complete,
    }



def _audit_id_to_dir_name(audit_id: str) -> str:
    """Map ``audit:APP:TS`` → directory name ``audit_APP_TS`` (and accept either)."""
    raw = str(audit_id or "").strip()
    if not raw:
        raise SubmissionComplianceAuditError(
            "audit_id is required", code="invalid_audit_id"
        )
    return raw.replace(":", "_")



def _dir_name_to_audit_id(dir_name: str) -> str:
    """Best-effort reverse of :func:`_audit_id_to_dir_name` for list rows."""
    name = str(dir_name or "").strip()
    if not name:
        return ""
    if name.startswith("audit_") and name.count("_") >= 2:
        # audit_<app>_<timestamp> — app may contain only alphanumerics
        rest = name[len("audit_") :]
        # Prefer last underscore split for timestamp suffix (ISO-like, no colons)
        parts = rest.rsplit("_", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return f"audit:{parts[0]}:{parts[1]}"
    if name.startswith("audit:"):
        return name
    return name.replace("_", ":", 2) if name.startswith("audit_") else name



def extract_audit_gaps(summary: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Extract stable gap records from a persisted audit summary.

    Gap identities cover:
    * filing-rule evidence gaps (missing / optional_missing / human_only)
    * prior-art blocking codes
    * prior-art warning codes

    Each gap has a stable ``gap_id`` used for closed/opened set comparison.
    """
    if not summary:
        return []
    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(
        gap_id: str,
        *,
        category: str,
        code: str,
        severity: str,
        message: str = "",
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        if not gap_id or gap_id in seen:
            return
        seen.add(gap_id)
        row: dict[str, Any] = {
            "gap_id": gap_id,
            "category": category,
            "code": code,
            "severity": severity,
            "message": message or "",
        }
        if detail:
            row["detail"] = dict(detail)
        gaps.append(row)

    filing = summary.get("filing_rules") or {}
    for ev in filing.get("evidence_gaps") or []:
        if not isinstance(ev, Mapping):
            continue
        status = str(ev.get("status") or "").strip().lower()
        # Only open problems count as gaps (present evidence is not a gap)
        if status not in {"missing", "optional_missing", "human_only"}:
            continue
        kind = str(ev.get("evidence_kind") or "").strip() or "unknown"
        rule_id = str(ev.get("rule_id") or "").strip()
        gap_id = f"filing:{kind}:{status}:{rule_id}"
        severity = (
            "error"
            if status == "missing" and bool(ev.get("mandatory", True))
            else ("info" if status == "human_only" else "warning")
        )
        _add(
            gap_id,
            category="filing_rules",
            code=f"{kind}:{status}",
            severity=severity,
            message=str(ev.get("message") or ""),
            detail={
                "evidence_kind": kind,
                "status": status,
                "rule_id": rule_id or None,
                "mandatory": bool(ev.get("mandatory", status == "missing")),
                "expected_roles": list(ev.get("expected_roles") or []),
                "conditional_on": ev.get("conditional_on"),
            },
        )

    prior = summary.get("prior_art") or {}
    for code in prior.get("blocking_codes") or []:
        c = str(code or "").strip()
        if not c:
            continue
        _add(
            f"prior_art:blocking:{c}",
            category="prior_art",
            code=c,
            severity="error",
            message=f"Prior-art blocking: {c}",
            detail={"channel": "blocking_codes"},
        )
    for code in prior.get("warning_codes") or []:
        c = str(code or "").strip()
        if not c:
            continue
        _add(
            f"prior_art:warning:{c}",
            category="prior_art",
            code=c,
            severity="warning",
            message=f"Prior-art warning: {c}",
            detail={"channel": "warning_codes"},
        )

    gaps.sort(key=lambda g: str(g.get("gap_id") or ""))
    return gaps



def compute_audit_delta(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    *,
    previous_audit_id: str | None = None,
    current_audit_id: str | None = None,
) -> dict[str, Any]:
    """Diff two audit summaries into closed/opened gaps and status transition.

    Pure function: never mutates either summary. History rewriting is impossible
    from this path; callers must persist the delta only on the *new* audit.
    """
    prev = dict(previous or {})
    curr = dict(current or {})
    prev_gaps = extract_audit_gaps(prev)
    curr_gaps = extract_audit_gaps(curr)
    prev_by_id = {str(g["gap_id"]): g for g in prev_gaps}
    curr_by_id = {str(g["gap_id"]): g for g in curr_gaps}
    prev_ids = set(prev_by_id)
    curr_ids = set(curr_by_id)

    closed_ids = sorted(prev_ids - curr_ids)
    opened_ids = sorted(curr_ids - prev_ids)
    unchanged_ids = sorted(prev_ids & curr_ids)

    prev_status = str(prev.get("overall_status") or "") or None
    curr_status = str(curr.get("overall_status") or "") or None
    status_transition = {
        "from": prev_status,
        "to": curr_status,
        "changed": prev_status != curr_status,
    }

    prev_id = (
        previous_audit_id
        or prev.get("audit_id")
        or (prev.get("delta") or {}).get("current_audit_id")
        or None
    )
    curr_id = current_audit_id or curr.get("audit_id") or None

    return {
        "schema": DELTA_SCHEMA,
        "delta_from": prev_id,
        "previous_audit_id": prev_id,
        "current_audit_id": curr_id,
        "closed_gaps": [prev_by_id[i] for i in closed_ids],
        "opened_gaps": [curr_by_id[i] for i in opened_ids],
        "unchanged_gaps": [curr_by_id[i] for i in unchanged_ids],
        "closed_gap_count": len(closed_ids),
        "opened_gap_count": len(opened_ids),
        "unchanged_gap_count": len(unchanged_ids),
        "previous_gap_count": len(prev_ids),
        "current_gap_count": len(curr_ids),
        "status_transition": status_transition,
        "previous_overall_status": prev_status,
        "current_overall_status": curr_status,
        "history_rewritten": False,
        "disclaimer": AUDIT_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
    }



def resolve_compliance_audit(
    *,
    audit_id: str | None = None,
    audit_path: str | Path | None = None,
    audit_dir: str | Path | None = None,
    application_number: str | None = None,
    state_root: Path | None = None,
) -> dict[str, Any]:
    """Locate a persisted compliance audit without modifying it.

    Resolution order: explicit ``audit_path`` / ``audit_dir``, then
    ``audit_id`` under ``state_root/compliance_audits/<app>/``, then fail closed.
    """
    root = Path(state_root) if state_root is not None else default_state_root()
    path: Path | None = None
    resolved_id = str(audit_id or "").strip() or None

    if audit_path:
        path = Path(audit_path).expanduser().resolve()
    elif audit_dir:
        path = (
            Path(audit_dir).expanduser().resolve()
            / "submission_compliance_audit.json"
        )
    elif resolved_id:
        # Accept path-like audit_id
        candidate = Path(resolved_id).expanduser()
        if candidate.is_file() and candidate.name.endswith(".json"):
            path = candidate.resolve()
        elif candidate.is_dir() and (
            candidate / "submission_compliance_audit.json"
        ).is_file():
            path = (candidate / "submission_compliance_audit.json").resolve()
        else:
            dir_name = _audit_id_to_dir_name(resolved_id)
            app = (
                _normalize_app(application_number)
                if application_number
                else None
            )
            # Derive app from audit_id when possible: audit:APP:TS
            if not app and resolved_id.startswith("audit:"):
                bits = resolved_id.split(":")
                if len(bits) >= 3:
                    try:
                        app = _normalize_app(bits[1])
                    except SubmissionComplianceAuditError:
                        app = None
            if not app and dir_name.startswith("audit_"):
                rest = dir_name[len("audit_") :]
                parts = rest.rsplit("_", 1)
                if len(parts) == 2:
                    try:
                        app = _normalize_app(parts[0])
                    except SubmissionComplianceAuditError:
                        app = None
            search_roots: list[Path] = []
            base = root / "compliance_audits"
            if app:
                search_roots.append(base / app)
            elif base.is_dir():
                search_roots.extend(
                    p for p in sorted(base.iterdir()) if p.is_dir()
                )
            for app_dir in search_roots:
                cand = app_dir / dir_name / "submission_compliance_audit.json"
                if cand.is_file():
                    path = cand
                    break
                # Also accept already-normalized dir under app
                if (app_dir / resolved_id / "submission_compliance_audit.json").is_file():
                    path = (
                        app_dir
                        / resolved_id
                        / "submission_compliance_audit.json"
                    )
                    break
    else:
        raise SubmissionComplianceAuditError(
            "pass audit_id, audit_path, or audit_dir",
            code="missing_audit_reference",
        )

    if path is None or not path.is_file():
        raise SubmissionComplianceAuditError(
            f"compliance audit not found for "
            f"audit_id={resolved_id!r} path={audit_path!r} dir={audit_dir!r}",
            code="audit_not_found",
        )

    summary = _read_json(path)
    # Prefer embedded audit_id; fall back to directory name
    embedded = str(summary.get("audit_id") or "").strip()
    if embedded:
        resolved_id = embedded
    elif path.parent.name:
        resolved_id = resolved_id or _dir_name_to_audit_id(path.parent.name)

    return {
        "schema": AUDIT_SCHEMA,
        "ok": True,
        "audit_id": resolved_id,
        "audit_path": str(path),
        "audit_dir": str(path.parent),
        "application_number": summary.get("application_number"),
        "overall_status": summary.get("overall_status"),
        "generated_at_utc": summary.get("generated_at_utc"),
        "summary": summary,
        "disclaimer": AUDIT_DISCLAIMER,
    }



def load_compliance_audit_by_id(
    audit_id: str,
    *,
    application_number: str | None = None,
    state_root: Path | None = None,
) -> dict[str, Any]:
    """Load a prior audit by id (read-only; never rewrites history)."""
    return resolve_compliance_audit(
        audit_id=audit_id,
        application_number=application_number,
        state_root=state_root,
    )

DELTA_SCHEMA: Final = "patlaw-submission-compliance-audit-delta-v1"
