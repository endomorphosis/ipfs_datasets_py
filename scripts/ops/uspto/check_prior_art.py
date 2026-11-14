#!/usr/bin/env python3
"""Check portfolio applications against public prior art (ODP / local snapshot).

Operator workflow (review only — no patentability conclusions, no auto-file IDS):

  1. Auto-load claims from GraphRAG OCR (CLM_*.txt) or --claims-file
  2. Plan + search prior art (USPTO ODP by default when key is present)
  3. Run submission compliance audit with the new prior-art run attached
  4. Print compact status + paths

Examples
--------
# Live ODP search for one application (sources ~/.config/.../uspto.env)
python3 scripts/ops/uspto/check_prior_art.py --application-number 18654466

# Offline local snapshot
python3 scripts/ops/uspto/check_prior_art.py --application-number 18654466 \\
  --local-snapshot ~/snapshots/us_public_patents.json --no-odp

# Plan only (no live search)
python3 scripts/ops/uspto/check_prior_art.py --application-number 18654466 --plan-only

# All non-candidate seed applications
python3 scripts/ops/uspto/check_prior_art.py --all-seed

Standing rules: not legal advice; never Sign/Pay/Submit; never auto-file IDS;
foreign/NPL gaps stay named unless licensed adapters are provided.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_uspto_env() -> Path | None:
    """Source USPTO ODP key from the operator env file when unset."""
    if os.environ.get("USPTO_ODP_API_KEY"):
        return None
    candidates = [
        Path.home() / ".config" / "ipfs_datasets_py" / "uspto.env",
    ]
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        candidates.insert(0, Path(xdg) / "ipfs_datasets_py" / "uspto.env")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                # Support both KEY=val and shell-style `export KEY=val`
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("'").strip('"')
                if key and key not in os.environ and val:
                    os.environ[key] = val
            # Common aliases
            if not os.environ.get("USPTO_ODP_API_KEY"):
                for alt in ("ODP_API_KEY", "USPTO_API_KEY"):
                    if os.environ.get(alt):
                        os.environ["USPTO_ODP_API_KEY"] = os.environ[alt]
                        break
            return path
        except OSError:
            continue
    return None


def _state_root(explicit: str | None) -> Path:
    from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
        default_state_root,
    )

    if explicit:
        return Path(explicit).expanduser().resolve()
    return default_state_root()


def _seed_apps(state: Path) -> list[str]:
    from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
        load_portfolio_seed,
    )

    seed_path = state / "portfolio_seed.json"
    if not seed_path.is_file():
        return []
    seed = load_portfolio_seed(seed_path)
    return [
        m.application_number
        for m in seed.matters
        if not str(m.ownership).startswith("candidate")
    ]


def _check_one(
    app: str,
    *,
    state: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
        PriorArtSearchClientError,
        load_claims_from_exports,
        load_export_temporal_anchors,
        plan_prior_art,
        search_prior_art,
    )
    from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
        SubmissionComplianceAuditError,
        audit_submission,
        list_compliance_audits,
    )

    out: dict[str, Any] = {
        "application_number": app,
        "ok": False,
        "steps": {},
    }

    # Claims auto-load preview (also done inside plan/search when omitted)
    claims_info = load_claims_from_exports(
        app,
        state_root=state,
        max_claims=int(getattr(args, "max_claims", 8) or 8),
        independent_only=not bool(getattr(args, "all_claims", False)),
    )
    anchors = load_export_temporal_anchors(app, state_root=state)
    out["claims"] = {
        "ok": claims_info.get("ok"),
        "claim_count": claims_info.get("claim_count"),
        "source_path": claims_info.get("source_path"),
        "warnings": claims_info.get("warnings") or [],
    }
    out["anchors"] = {
        k: anchors.get(k)
        for k in ("filing_date", "priority_date", "invention_title", "classifications", "source_path")
        if anchors.get(k)
    }

    claims_file = str(args.claims_file or "") or None
    claims_text = str(args.claims_text or "") or None
    if not claims_file and not claims_text and not claims_info.get("ok"):
        out["error"] = "missing_claims"
        out["message"] = (
            "No claims found. Pass --claims-file / --claims-text or run "
            "export-messages + graphrag-exports so CLM_*.txt extracts exist."
        )
        return out

    classifications = [
        c.strip()
        for c in str(args.classifications or "").split(",")
        if c.strip()
    ]
    if not classifications and anchors.get("classifications"):
        classifications = [
            c.strip()
            for c in str(anchors["classifications"]).split(",")
            if c.strip()
        ]

    # Optional: only plan
    if bool(args.plan_only):
        try:
            plan = plan_prior_art(
                application_number=app,
                state_root=state,
                claims=claims_info.get("claims") if claims_info.get("ok") and not claims_file and not claims_text else None,
                claims_file=claims_file,
                claims_text=claims_text,
                filing_date=str(args.filing_date or "") or None,
                priority_date=str(args.priority_date or "") or None,
                classifications=classifications,
                rank_cutoff=int(args.rank_cutoff or 10),
                persist=not bool(args.no_persist),
            )
            out["steps"]["plan"] = {
                k: plan.get(k)
                for k in (
                    "ok",
                    "run_id",
                    "run_dir",
                    "plan_id",
                    "query_count",
                    "claim_count",
                    "claims_source",
                    "filing_date",
                    "paths",
                )
                if plan.get(k) is not None
            }
            out["ok"] = bool(plan.get("ok"))
            out["run_id"] = plan.get("run_id")
            out["run_dir"] = plan.get("run_dir")
            out["disclaimer"] = plan.get("disclaimer")
            return out
        except PriorArtSearchClientError as exc:
            out["error"] = exc.code
            out["message"] = str(exc)
            return out

    use_odp = bool(args.odp) and not bool(args.no_odp)
    local_snap = str(args.local_snapshot or "") or None
    if use_odp and not os.environ.get("USPTO_ODP_API_KEY"):
        out["error"] = "missing_odp_key"
        out["message"] = (
            "USPTO_ODP_API_KEY not set. Place it in "
            "~/.config/ipfs_datasets_py/uspto.env or pass --local-snapshot / --no-odp."
        )
        return out
    if not use_odp and not local_snap:
        out["error"] = "no_search_backend"
        out["message"] = "Need --odp (default) with API key, or --local-snapshot PATH"
        return out

    try:
        search = search_prior_art(
            application_number=app,
            state_root=state,
            claims=claims_info.get("claims")
            if claims_info.get("ok") and not claims_file and not claims_text
            else None,
            claims_file=claims_file,
            claims_text=claims_text,
            filing_date=str(args.filing_date or "") or None,
            priority_date=str(args.priority_date or "") or None,
            classifications=classifications,
            rank_cutoff=int(args.rank_cutoff or 10),
            use_odp=use_odp,
            local_snapshot_path=local_snap,
            max_odp_pages=int(args.max_odp_pages or 1),
            max_queries=int(args.max_queries)
            if args.max_queries is not None
            else None,
            enable_foreign=bool(args.enable_foreign)
            or bool(args.live_foreign)
            or not bool(getattr(args, "no_foreign_gap", False)),
            live_foreign=bool(args.live_foreign),
            # Without EPO keys we register foreign as an explicit named gap
            # (unlicensed / not_run) rather than silently omitting it.
            foreign_licensed=bool(args.live_foreign),
            enable_npl=bool(args.enable_npl) or bool(args.live_npl),
            live_npl=bool(args.live_npl),
            npl_licensed=bool(args.npl_licensed),
            build_report=not bool(args.no_report),
            build_pps_checklist=not bool(args.no_pps_checklist),
            auto_acknowledge=bool(args.auto_acknowledge),
            acknowledger_name=str(args.acknowledger or "operator:local"),
        )
    except PriorArtSearchClientError as exc:
        out["error"] = exc.code
        out["message"] = str(exc)
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}:{exc}"
        out["message"] = str(exc)
        return out

    out["steps"]["search"] = {
        k: search.get(k)
        for k in (
            "ok",
            "run_id",
            "run_dir",
            "plan_id",
            "journal_id",
            "chart_id",
            "coverage_id",
            "report_id",
            "adapter_status",
            "summary",
            "paths",
        )
        if search.get(k) is not None
    }
    out["run_id"] = search.get("run_id")
    out["run_dir"] = search.get("run_dir")
    out["disclaimer"] = search.get("disclaimer")

    # Seed PPS checklist from automated ODP hit counts (human may still re-check
    # in Patent Public Search; counts are recorded with explicit notes).
    if (
        not bool(args.no_pps_seed)
        and search.get("run_dir")
        and not bool(args.no_pps_checklist)
    ):
        try:
            from ipfs_datasets_py.processors.domains.uspto.prior_art_operator_extensions import (
                record_pps_verification,
            )
            from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
                _read_json,
            )

            run_dir = Path(str(search["run_dir"]))
            journal_path = run_dir / "search_journal.json"
            results_rows: list[dict[str, Any]] = []
            if journal_path.is_file():
                journal = _read_json(journal_path)
                for rec in journal.get("records") or []:
                    if not isinstance(rec, Mapping):
                        continue
                    qid = str(rec.get("query_id") or "").strip()
                    if not qid:
                        continue
                    n_hits = int(rec.get("result_count") or len(rec.get("hits") or []) or 0)
                    outcome = str(rec.get("outcome") or "")
                    results_rows.append(
                        {
                            "query_id": qid,
                            "human_result_count": n_hits,
                            "human_notes": (
                                f"Seeded from automated ODP search "
                                f"(outcome={outcome}, hits={n_hits}). "
                                "Operator should spot-check critical hits in "
                                "Patent Public Search before IDS/filing."
                            ),
                            "status": "verified",
                        }
                    )
            if results_rows:
                pps = record_pps_verification(
                    run_dir,
                    results=results_rows,
                    verified_by=str(args.acknowledger or "operator:local"),
                    notes=(
                        "PPS checklist seeded from ODP automated hit counts "
                        "(not a PPS scrape). Confirm high-value hits manually."
                    ),
                )
                out["steps"]["pps_seed"] = {
                    "ok": pps.get("ok"),
                    "checklist_summary": pps.get("checklist_summary"),
                }
        except Exception as exc:  # noqa: BLE001
            out["steps"]["pps_seed"] = {
                "ok": False,
                "error": f"{type(exc).__name__}:{exc}",
            }

    if bool(args.no_audit):
        out["ok"] = bool(search.get("ok"))
        return out

    # Previous audit for delta (optional)
    delta_from = str(args.delta_from or "") or None
    if not delta_from and bool(args.delta_from_latest):
        listed = list_compliance_audits(
            application_number=app, state_root=state, limit=1
        )
        audits = listed.get("audits") or listed.get("items") or []
        if audits and isinstance(audits[0], dict):
            delta_from = str(
                audits[0].get("audit_id") or audits[0].get("id") or ""
            ) or None

    try:
        audit = audit_submission(
            application_number=app,
            state_root=state,
            prior_art_run_id=str(search.get("run_id") or "") or None,
            prior_art_run_dir=str(search.get("run_dir") or "") or None,
            application_type=str(args.application_type or "utility"),
            scenario=str(args.scenario or "") or None,
            with_law_index=bool(args.with_law_index),
            build_ids_queue=not bool(args.no_ids_queue),
            persist=not bool(args.no_persist),
            delta_from=delta_from,
        )
    except SubmissionComplianceAuditError as exc:
        out["steps"]["audit"] = {
            "ok": False,
            "error": getattr(exc, "code", None),
            "message": str(exc),
        }
        out["ok"] = bool(search.get("ok"))
        out["message"] = f"search_ok_audit_failed:{exc}"
        return out

    filing = (audit.get("summary") or {}).get("filing_rules") or {}
    prior = (audit.get("summary") or {}).get("prior_art") or {}
    out["steps"]["audit"] = {
        "ok": audit.get("ok"),
        "audit_id": audit.get("audit_id"),
        "overall_status": audit.get("overall_status"),
        "filing_status": filing.get("status"),
        "prior_art_status": prior.get("status"),
        "prior_art_blocking": prior.get("blocking_codes"),
        "prior_art_warnings": prior.get("warning_codes"),
        "missing_mandatory_count": filing.get("missing_mandatory_count"),
        "paths": audit.get("paths"),
        "delta": audit.get("delta")
        or (audit.get("summary") or {}).get("delta"),
        "action_plan": (audit.get("summary") or {}).get("action_plan"),
        "ids_queue": (audit.get("summary") or {}).get("ids_queue"),
    }
    out["ok"] = bool(search.get("ok") and audit.get("ok"))
    out["overall_status"] = audit.get("overall_status")
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Check applications against public prior art (ODP/snapshot) and "
            "re-run filing compliance audit. Review only."
        )
    )
    p.add_argument("--state-root", default="")
    p.add_argument(
        "--application-number",
        action="append",
        default=[],
        help="Application number (repeatable). Default: none unless --all-seed",
    )
    p.add_argument(
        "--all-seed",
        action="store_true",
        help="Run for all non-candidate portfolio seed applications",
    )
    p.add_argument("--claims-file", default="", help="Override claims JSON/text file")
    p.add_argument("--claims-text", default="", help="Inline claim text")
    p.add_argument(
        "--max-claims",
        type=int,
        default=8,
        help="Max claims from auto-export load (default 8 independent)",
    )
    p.add_argument(
        "--all-claims",
        action="store_true",
        help="Include dependent claims from export (may hit plan size limits)",
    )
    p.add_argument("--filing-date", default="")
    p.add_argument("--priority-date", default="")
    p.add_argument("--classifications", default="", help="Comma-separated CPC/IPC")
    p.add_argument("--rank-cutoff", type=int, default=10)
    p.add_argument("--max-queries", type=int, default=8)
    p.add_argument("--max-odp-pages", type=int, default=1)
    p.add_argument(
        "--odp",
        action="store_true",
        default=True,
        help="Use USPTO ODP (default on)",
    )
    p.add_argument(
        "--no-odp",
        action="store_true",
        help="Disable ODP (require --local-snapshot)",
    )
    p.add_argument("--local-snapshot", default="", help="Local public-patent JSON/JSONL")
    p.add_argument("--enable-foreign", action="store_true")
    p.add_argument("--live-foreign", action="store_true", help="EPO OPS (needs keys)")
    p.add_argument(
        "--no-foreign-gap",
        action="store_true",
        help="Do not register foreign corpus as an explicit named unlicensed gap",
    )
    p.add_argument("--enable-npl", action="store_true")
    p.add_argument(
        "--live-npl",
        action="store_true",
        help="Search public NPL metadata (OpenAlex/Crossref)",
    )
    p.add_argument("--npl-licensed", action="store_true")
    p.add_argument("--plan-only", action="store_true", help="Build plan only; no search")
    p.add_argument("--no-audit", action="store_true", help="Skip compliance re-audit")
    p.add_argument("--no-report", action="store_true")
    p.add_argument("--no-pps-checklist", action="store_true")
    p.add_argument(
        "--auto-acknowledge",
        action="store_true",
        help="Record operator acknowledgement of named coverage gaps",
    )
    p.add_argument("--acknowledger", default="operator:local")
    p.add_argument(
        "--no-pps-seed",
        action="store_true",
        help="Do not seed PPS checklist from ODP hit counts",
    )
    p.add_argument("--application-type", default="utility")
    p.add_argument("--scenario", default="", help="Filing scenario override for audit")
    p.add_argument("--with-law-index", action="store_true")
    p.add_argument("--no-ids-queue", action="store_true")
    p.add_argument("--no-persist", action="store_true")
    p.add_argument("--delta-from", default="", help="Prior audit_id for re-audit delta")
    p.add_argument(
        "--delta-from-latest",
        action="store_true",
        help="Delta against the latest compliance audit for the app",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Include full nested step payloads",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = _load_uspto_env()
    state = _state_root(args.state_root or None)
    state.mkdir(parents=True, exist_ok=True)

    apps = [str(a).strip() for a in (args.application_number or []) if str(a).strip()]
    if bool(args.all_seed):
        apps = list(dict.fromkeys(apps + _seed_apps(state)))
    if not apps:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "pass --application-number or --all-seed",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    results: list[dict[str, Any]] = []
    exit_code = 0
    for app in apps:
        try:
            result = _check_one(app, state=state, args=args)
        except Exception as exc:  # noqa: BLE001
            result = {
                "application_number": app,
                "ok": False,
                "error": f"{type(exc).__name__}:{exc}",
            }
        results.append(result)
        if not result.get("ok"):
            exit_code = 1

    # Compact multi-app report
    compact = []
    for r in results:
        if bool(args.verbose):
            compact.append(r)
            continue
        step_search = (r.get("steps") or {}).get("search") or {}
        step_audit = (r.get("steps") or {}).get("audit") or {}
        compact.append(
            {
                "application_number": r.get("application_number"),
                "ok": r.get("ok"),
                "error": r.get("error"),
                "message": r.get("message"),
                "claims": r.get("claims"),
                "run_id": r.get("run_id"),
                "run_dir": r.get("run_dir"),
                "search_summary": step_search.get("summary"),
                "adapter_status": step_search.get("adapter_status"),
                "overall_status": r.get("overall_status")
                or step_audit.get("overall_status"),
                "prior_art_status": step_audit.get("prior_art_status"),
                "filing_status": step_audit.get("filing_status"),
                "audit_id": step_audit.get("audit_id"),
                "audit_paths": step_audit.get("paths"),
                "ids_queue": step_audit.get("ids_queue"),
                "delta": step_audit.get("delta"),
            }
        )

    payload: dict[str, Any] = {
        "schema": "patlaw-check-prior-art-v1",
        "ok": exit_code == 0,
        "state_root": str(state),
        "env_file_loaded": str(env_path) if env_path else None,
        "odp_key_present": bool(os.environ.get("USPTO_ODP_API_KEY")),
        "application_count": len(apps),
        "results": compact,
        "disclaimer": (
            "Prior-art check is decision support only — not legal advice, not a "
            "patentability determination, and not an IDS filing. Sign/Pay/Submit "
            "and IDS remain human-only in Patent Center."
        ),
    }

    # Persist receipt
    try:
        receipt_dir = state / "exports"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt = receipt_dir / "check_prior_art_receipt.json"
        receipt.write_text(json.dumps(payload, indent=2, default=str) + "\n")
        try:
            os.chmod(receipt, 0o600)
        except OSError:
            pass
        payload["receipt"] = str(receipt)
    except Exception:
        pass

    print(json.dumps(payload, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
