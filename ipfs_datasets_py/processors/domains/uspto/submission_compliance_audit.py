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
    "remarks": ("remarks",),
    "amended_specification": ("specification",),
    "substitute_specification": ("specification",),
    "amended_drawings": ("drawings",),
    "declaration": ("oath_declaration",),
    "fee_transmittal": ("fee", "fee_transmittal"),
    "ids": ("ids",),
    "amendment_transmittal": ("amendment_transmittal",),
    "evidence": ("evidence",),
}

_FILENAME_KIND_RE: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"claim", re.I), "amended_claims"),
    (re.compile(r"remark|argument|response", re.I), "remarks"),
    (re.compile(r"spec", re.I), "amended_specification"),
    (re.compile(r"draw", re.I), "amended_drawings"),
    (re.compile(r"ids|information.?disclosure", re.I), "ids"),
    (re.compile(r"fee", re.I), "fee_transmittal"),
    (re.compile(r"declar|oath", re.I), "declaration"),
    (re.compile(r"transmittal", re.I), "amendment_transmittal"),
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
    """List files under a response package directory with role hints."""
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
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        rel = str(path.relative_to(root))
        role = _infer_role(path.name)
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
            }
        )
    return {
        "package_dir": str(root),
        "file_count": len(files),
        "files": files,
        "roles_present": sorted(roles),
        "evidence_kinds_present": sorted(kinds),
    }


def _infer_role(filename: str) -> str | None:
    for pattern, role in _FILENAME_KIND_RE:
        if pattern.search(filename):
            return role
    return None


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
            excerpts.append(lookup_authority_excerpt(str(cite), roots=roots))
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

    def to_dict(self) -> dict[str, Any]:
        return {
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
    persist: bool = True,
) -> dict[str, Any]:
    """Run a combined MPEP/filing-rule + prior-art compliance audit."""
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

    if package_dir:
        package_path = Path(package_dir).expanduser().resolve()
    inventory = inventory_package_dir(package_path)

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

    summary = {
        "schema": AUDIT_SCHEMA,
        "application_number": app,
        "revision_id": getattr(case, "revision_id", None) if case else revision_id,
        "overall_status": overall,
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
            "sample_excerpts": (authority.get("local_excerpts") or [])[:6],
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

    audit_id = f"audit:{app}:{utc_now_iso().replace(':', '').replace('-', '')[:15]}"
    paths: dict[str, str] = {}
    if persist:
        out_dir = root / "compliance_audits" / app / audit_id.replace(":", "_")
        paths["audit"] = str(_write_json(out_dir / "submission_compliance_audit.json", summary))
        paths["authority"] = str(
            _write_json(out_dir / "mpep_authority_surface.json", authority)
        )
        paths["filing_rules"] = str(
            _write_json(out_dir / "filing_rules_audit.json", filing_audit)
        )
        paths["prior_art"] = str(
            _write_json(out_dir / "prior_art_audit.json", prior_audit)
        )
        # Attach pointer on revision case when present
        if case is not None and getattr(case, "case_dir", None):
            case_dir = Path(case.case_dir)
            pointer = {
                "schema": AUDIT_SCHEMA,
                "audit_id": audit_id,
                "audit_path": paths["audit"],
                "overall_status": overall,
                "attached_at_utc": utc_now_iso(),
                "disclaimer": AUDIT_DISCLAIMER,
            }
            paths["revision_pointer"] = str(
                _write_json(case_dir / "submission_compliance_audit.json", pointer)
            )

    result = SubmissionAuditResult(
        ok=True,
        audit_id=audit_id,
        application_number=app,
        overall_status=overall,
        paths=paths,
        summary=summary,
    )
    return result.to_dict()


__all__ = [
    "AUDIT_DISCLAIMER",
    "AUDIT_SCHEMA",
    "SubmissionAuditResult",
    "SubmissionComplianceAuditError",
    "audit_filing_rules",
    "audit_mpep_authority_surface",
    "audit_prior_art_compliance",
    "audit_submission",
    "inventory_package_dir",
    "load_prior_art_audit_bundle",
]
